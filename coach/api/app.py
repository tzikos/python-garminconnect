"""FastAPI app factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from coach.api.routes import plans, profile, settings, sync, workouts


def create_app() -> FastAPI:
    """Build and configure the FastAPI app."""
    app = FastAPI(title="Garmin Coach", version="0.1.0")

    # Local single-user app: allow the Next.js dev server to call us.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(profile.router)
    app.include_router(plans.router)
    app.include_router(workouts.router)
    app.include_router(sync.router)
    app.include_router(settings.router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
