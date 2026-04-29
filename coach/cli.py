"""`coach` CLI: setup, profile, plan management, sync."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Annotated

import typer
from sqlalchemy import select

from coach import secrets
from coach.config import app_dir, db_path
from coach.db import init_db, session
from coach.models import Plan, ScheduledWorkout, UserProfile
from coach.primitives import PRIMITIVES

app = typer.Typer(no_args_is_help=True, add_completion=False)
profile_app = typer.Typer(no_args_is_help=True, help="Manage your user profile.")
plan_app = typer.Typer(no_args_is_help=True, help="View and manage training plans.")
secrets_app = typer.Typer(no_args_is_help=True, help="Manage credentials in keyring.")
sync_app = typer.Typer(no_args_is_help=True, help="Push plans to Garmin Connect.")
app.add_typer(profile_app, name="profile")
app.add_typer(plan_app, name="plan")
app.add_typer(secrets_app, name="secrets")
app.add_typer(sync_app, name="sync")


# ----------------------------------------------------------------- init


@app.command()
def init() -> None:
    """Create the data directory and initialize the SQLite DB."""
    init_db()
    typer.echo(f"Data dir:  {app_dir()}")
    typer.echo(f"Database:  {db_path()}")
    typer.echo("Initialized.")


# --------------------------------------------------------------- profile


def _parse_5k(value: str) -> int:
    """Parse 'mm:ss' or seconds-as-int into seconds."""
    if ":" in value:
        m, s = value.split(":", 1)
        return int(m) * 60 + int(s)
    return int(value)


@profile_app.command("show")
def profile_show() -> None:
    """Print the stored user profile."""
    with session() as s:
        prof = s.get(UserProfile, 1)
        if prof is None:
            typer.echo("No profile set. Use `coach profile set --name ...`.")
            raise typer.Exit(code=1)
        typer.echo(json.dumps({
            "id": prof.id,
            "name": prof.name,
            "garmin_email": prof.garmin_email,
            "recent_5k_seconds": prof.recent_5k_seconds,
            "threshold_hr": prof.threshold_hr,
            "max_hr": prof.max_hr,
            "preferred_days": prof.preferred_days,
            "weekly_hours_target": prof.weekly_hours_target,
            "notes": prof.notes,
        }, indent=2))


@profile_app.command("set")
def profile_set(
    name: Annotated[str | None, typer.Option(help="Display name.")] = None,
    garmin_email: Annotated[str | None, typer.Option()] = None,
    recent_5k: Annotated[
        str | None,
        typer.Option(help="Recent 5k time as 'mm:ss' or seconds."),
    ] = None,
    threshold_hr: Annotated[int | None, typer.Option()] = None,
    max_hr: Annotated[int | None, typer.Option()] = None,
    weekly_hours: Annotated[float | None, typer.Option()] = None,
    notes: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Create or update the local user profile (singleton row)."""
    with session() as s:
        prof = s.get(UserProfile, 1)
        if prof is None:
            if name is None:
                typer.echo("First run requires --name.")
                raise typer.Exit(code=1)
            prof = UserProfile(id=1, name=name)
            s.add(prof)

        if name is not None:
            prof.name = name
        if garmin_email is not None:
            prof.garmin_email = garmin_email
        if recent_5k is not None:
            prof.recent_5k_seconds = _parse_5k(recent_5k)
        if threshold_hr is not None:
            prof.threshold_hr = threshold_hr
        if max_hr is not None:
            prof.max_hr = max_hr
        if weekly_hours is not None:
            prof.weekly_hours_target = weekly_hours
        if notes is not None:
            prof.notes = notes

    typer.echo("Profile saved.")


# --------------------------------------------------------------- secrets


@secrets_app.command("set-garmin-password")
def secrets_set_garmin_password() -> None:
    """Store your Garmin password in the OS keychain."""
    pw = typer.prompt("Garmin password", hide_input=True, confirmation_prompt=True)
    secrets.set_(secrets.GARMIN_PASSWORD, pw)
    typer.echo("Stored.")


@secrets_app.command("set-openrouter")
def secrets_set_openrouter(
    model: Annotated[str | None, typer.Option(help="Override model id.")] = None,
) -> None:
    """Store your OpenRouter API key (and optional model override)."""
    key = typer.prompt("OpenRouter API key", hide_input=True)
    secrets.set_(secrets.OPENROUTER_API_KEY, key)
    if model:
        secrets.set_(secrets.OPENROUTER_MODEL, model)
    typer.echo("Stored.")


@secrets_app.command("clear")
def secrets_clear() -> None:
    """Remove all stored secrets."""
    for key in (
        secrets.GARMIN_PASSWORD,
        secrets.OPENROUTER_API_KEY,
        secrets.OPENROUTER_MODEL,
    ):
        secrets.delete(key)
    typer.echo("Cleared.")


# ---------------------------------------------------------------- plans


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


@plan_app.command("list")
def plan_list() -> None:
    """List all plans, newest first."""
    with session() as s:
        plans = s.execute(select(Plan).order_by(Plan.created_at.desc())).scalars().all()
        if not plans:
            typer.echo("No plans yet.")
            return
        for p in plans:
            typer.echo(
                f"[{p.id}] {p.name}  ({p.start_date} -> {p.end_date})  "
                f"status={p.status} v{p.version}"
            )


@plan_app.command("create")
def plan_create(
    name: Annotated[str, typer.Option()],
    goal: Annotated[str, typer.Option(help="Goal description.")],
    start: Annotated[str, typer.Option(help="Start date YYYY-MM-DD.")],
    end: Annotated[str, typer.Option(help="End date YYYY-MM-DD.")],
) -> None:
    """Create an empty plan."""
    with session() as s:
        p = Plan(
            name=name,
            goal_text=goal,
            start_date=_parse_date(start),
            end_date=_parse_date(end),
        )
        s.add(p)
        s.flush()
        plan_id = p.id
    typer.echo(f"Created plan [{plan_id}].")


@plan_app.command("add")
def plan_add(
    plan_id: Annotated[int, typer.Option("--plan-id")],
    when: Annotated[str, typer.Option("--date", help="YYYY-MM-DD")],
    sport: Annotated[str, typer.Option(help="e.g. running, strength.")],
    primitive: Annotated[
        str, typer.Option("--type", help=f"One of: {', '.join(sorted(PRIMITIVES))}")
    ],
    params: Annotated[
        str, typer.Option(help='Primitive params as JSON, e.g. \'{"duration_min": 45}\'')
    ],
    title: Annotated[str | None, typer.Option()] = None,
    description: Annotated[str | None, typer.Option()] = None,
    week: Annotated[int, typer.Option(help="Plan week number.")] = 1,
) -> None:
    """Add a workout to a plan (manual entry; LLM path comes later)."""
    if primitive not in PRIMITIVES:
        typer.echo(f"Unknown primitive {primitive!r}. Valid: {sorted(PRIMITIVES)}")
        raise typer.Exit(code=1)

    try:
        parsed_params = json.loads(params)
    except json.JSONDecodeError as e:
        typer.echo(f"Invalid --params JSON: {e}")
        raise typer.Exit(code=1) from e

    # Sanity-check by actually building the workout.
    try:
        built = PRIMITIVES[primitive](**parsed_params)
    except Exception as e:  # noqa: BLE001
        typer.echo(f"Primitive rejected params: {e}")
        raise typer.Exit(code=1) from e

    with session() as s:
        if s.get(Plan, plan_id) is None:
            typer.echo(f"Plan {plan_id} not found.")
            raise typer.Exit(code=1)
        sw = ScheduledWorkout(
            plan_id=plan_id,
            date=_parse_date(when),
            week_number=week,
            sport=sport,
            title=title or built.workoutName,
            description=description,
            primitive_type=primitive,
            primitive_params=parsed_params,
        )
        s.add(sw)
        s.flush()
        sw_id = sw.id
    typer.echo(f"Added workout [{sw_id}] to plan {plan_id}.")


@plan_app.command("generate")
def plan_generate(
    goal: Annotated[str, typer.Option(help="Goal description.")],
    start: Annotated[str, typer.Option(help="Start date YYYY-MM-DD (Monday).")],
    end: Annotated[str, typer.Option(help="End date YYYY-MM-DD.")],
    start_volume: Annotated[float, typer.Option(help="Starting weekly km.")] = 25.0,
    peak_volume: Annotated[
        float | None, typer.Option(help="Peak weekly km. Inferred if omitted.")
    ] = None,
    taper_weeks: Annotated[int, typer.Option(help="Number of taper weeks.")] = 2,
) -> None:
    """Generate a draft plan via the LLM and persist it for review."""
    from coach.llm import generate_plan

    start_d = _parse_date(start)
    if start_d.weekday() != 0:
        typer.echo(f"Warning: {start} is not a Monday — weeks may misalign.")

    typer.echo("Generating plan… (1 LLM call, may take 30-60s)")
    result = generate_plan(
        goal_text=goal,
        start_date=start_d,
        end_date=_parse_date(end),
        start_volume_km=start_volume,
        peak_volume_km=peak_volume,
        taper_weeks=taper_weeks,
    )
    typer.echo(
        f"\nCreated plan [{result.plan_id}] '{result.plan_name}' "
        f"with {result.workouts_created} workouts (model: {result.model_used})."
    )
    if result.warnings:
        typer.echo(f"\n{len(result.warnings)} warning(s):")
        for w in result.warnings:
            typer.echo(f"  [{w.severity}] {w.message}")
    typer.echo(f"\nReview with:  coach plan show {result.plan_id}")
    typer.echo(f"Push with:    coach sync push --plan-id {result.plan_id}")


@plan_app.command("show")
def plan_show(plan_id: Annotated[int, typer.Argument()]) -> None:
    """List workouts in a plan."""
    with session() as s:
        plan = s.get(Plan, plan_id)
        if plan is None:
            typer.echo(f"Plan {plan_id} not found.")
            raise typer.Exit(code=1)
        rows = s.execute(
            select(ScheduledWorkout)
            .where(ScheduledWorkout.plan_id == plan_id)
            .order_by(ScheduledWorkout.date)
        ).scalars().all()
        typer.echo(f"[{plan.id}] {plan.name} — {plan.goal_text}")
        typer.echo(f"  {plan.start_date} -> {plan.end_date}  status={plan.status}")
        if not rows:
            typer.echo("  (no workouts)")
            return
        for r in rows:
            tag = f"#{r.garmin_workout_id}" if r.garmin_workout_id else r.status
            typer.echo(
                f"  {r.date}  W{r.week_number}  {r.sport:9} "
                f"{r.primitive_type:18} {r.title}  [{tag}]"
            )


@plan_app.command("export")
def plan_export(
    plan_id: Annotated[int, typer.Argument()],
    out: Annotated[
        str | None,
        typer.Option(help="Write to file instead of stdout."),
    ] = None,
) -> None:
    """Dump a plan as JSON for editing."""
    from coach.plan_io import export_plan

    try:
        plan_dict = export_plan(plan_id)
    except ValueError as e:
        typer.echo(str(e))
        raise typer.Exit(code=1) from e

    text = json.dumps(plan_dict, indent=2)
    if out:
        from pathlib import Path

        Path(out).write_text(text + "\n")
        typer.echo(f"Wrote {out}")
    else:
        typer.echo(text)


@plan_app.command("import")
def plan_import(
    file: Annotated[str, typer.Argument(help="Path to plan JSON.")],
    plan_id: Annotated[
        int | None,
        typer.Option("--plan-id", help="Overwrite this plan instead of creating new."),
    ] = None,
) -> None:
    """Create or overwrite a plan from a JSON file."""
    from pathlib import Path

    from coach.plan_io import import_plan

    try:
        data = json.loads(Path(file).read_text())
    except (OSError, json.JSONDecodeError) as e:
        typer.echo(f"Could not read {file}: {e}")
        raise typer.Exit(code=1) from e

    try:
        new_id, n = import_plan(data, plan_id_to_overwrite=plan_id)
    except ValueError as e:
        typer.echo(f"Import failed: {e}")
        raise typer.Exit(code=1) from e

    verb = "Overwrote" if plan_id else "Created"
    typer.echo(f"{verb} plan [{new_id}] with {n} workouts.")


@plan_app.command("delete")
def plan_delete(
    plan_id: Annotated[int, typer.Argument()],
    yes: Annotated[bool, typer.Option("--yes", help="Skip confirmation.")] = False,
) -> None:
    """Delete a plan and its workouts (local DB only — does NOT remove from Garmin)."""
    with session() as s:
        plan = s.get(Plan, plan_id)
        if plan is None:
            typer.echo(f"Plan {plan_id} not found.")
            raise typer.Exit(code=1)
        if not yes:
            typer.confirm(
                f"Delete plan [{plan_id}] '{plan.name}' and its workouts? "
                "(Garmin uploads NOT removed.)",
                abort=True,
            )
        s.delete(plan)
    typer.echo(f"Deleted plan {plan_id}.")


# ----------------------------------------------------------------- sync


@sync_app.command("push")
def sync_push(
    plan_id: Annotated[int, typer.Option("--plan-id")],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be uploaded; no API calls."),
    ] = False,
) -> None:
    """Upload + schedule every planned workout in the plan."""
    from coach.sync import push_plan

    with session() as s:
        plan = s.get(Plan, plan_id)
        if plan is None:
            typer.echo(f"Plan {plan_id} not found.")
            raise typer.Exit(code=1)
        rows = s.execute(
            select(ScheduledWorkout)
            .where(ScheduledWorkout.plan_id == plan_id)
            .where(ScheduledWorkout.status == "planned")
            .order_by(ScheduledWorkout.date)
        ).scalars().all()

    if not rows:
        typer.echo("Nothing to push: no workouts with status=planned.")
        return

    typer.echo(f"Plan [{plan_id}] '{plan.name}': {len(rows)} workout(s) to push:")
    for r in rows:
        typer.echo(f"  {r.date}  {r.sport:9} {r.primitive_type:18} {r.title}")

    if dry_run:
        typer.echo("(dry-run; no upload performed)")
        return

    typer.confirm("\nPush to Garmin?", abort=True, default=False)

    from coach.garmin_client import get_client

    api = get_client()
    result = push_plan(plan_id, api)
    typer.echo(
        f"\nUploaded: {result.uploaded}  "
        f"Skipped: {result.skipped}  "
        f"Failed: {len(result.failed)}"
    )
    for wid, msg in result.failed:
        typer.echo(f"  ! workout {wid}: {msg}")


@sync_app.command("unpush")
def sync_unpush(
    plan_id: Annotated[int, typer.Option("--plan-id")],
    yes: Annotated[bool, typer.Option("--yes", help="Skip confirmation.")] = False,
) -> None:
    """Remove every uploaded workout in this plan from Garmin.

    Unschedules them from the calendar and deletes them from the workout
    library. Rows revert to status='planned' so they can be re-pushed.
    """
    from coach.sync import unpush_plan

    with session() as s:
        plan = s.get(Plan, plan_id)
        if plan is None:
            typer.echo(f"Plan {plan_id} not found.")
            raise typer.Exit(code=1)
        rows = s.execute(
            select(ScheduledWorkout)
            .where(ScheduledWorkout.plan_id == plan_id)
            .where(ScheduledWorkout.status == "uploaded")
            .order_by(ScheduledWorkout.date)
        ).scalars().all()

    if not rows:
        typer.echo("Nothing to unpush: no workouts with status=uploaded.")
        return

    typer.echo(f"Plan [{plan_id}] '{plan.name}': {len(rows)} workout(s) to remove:")
    for r in rows:
        typer.echo(
            f"  {r.date}  {r.sport:9} {r.primitive_type:18} {r.title}  "
            f"#{r.garmin_workout_id}"
        )

    if not yes:
        typer.confirm("\nRemove from Garmin?", abort=True, default=False)

    from coach.garmin_client import get_client

    api = get_client()
    result = unpush_plan(plan_id, api)
    typer.echo(
        f"\nRemoved: {result.removed}  "
        f"Skipped: {result.skipped}  "
        f"Failed: {len(result.failed)}"
    )
    for wid, msg in result.failed:
        typer.echo(f"  ! workout {wid}: {msg}")


# ----------------------------------------------------------------- serve


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Host to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to bind.")] = 8000,
    reload: Annotated[bool, typer.Option(help="Auto-reload on code changes.")] = False,
) -> None:
    """Run the FastAPI backend (for use with the Next.js frontend)."""
    import uvicorn

    init_db()  # safe to call multiple times; ensures tables exist
    uvicorn.run(
        "coach.api.app:app",
        host=host,
        port=port,
        reload=reload,
    )


# ----------------------------------------------------------------- entry


def main() -> None:
    """Entry point used by the console_scripts hook."""
    app()


if __name__ == "__main__":
    main()
