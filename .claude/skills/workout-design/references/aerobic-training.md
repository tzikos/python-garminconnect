# Athlete's preferred aerobic training approach

Source: the athlete's supplied transcripts, “how to build a monster aerobic
system” and “how to build your vo2 max.” These are planning preferences, not
independently verified research. Use these practical principles; do not treat
the precise gain estimates, percentages, equal-volume claims or study sprint
timings as guaranteed outcomes or universal prescriptions.

## Cover the endurance demands

Keep most training easy and build sustainable volume. Across a rolling
10–14-day block, aim to include easy/long aerobic work, threshold/tempo,
VO2-oriented intervals and short speed when readiness permits. Do not force
all four into seven days. Recovery, injury return, deloads and taper take
precedence; explain intentional omissions. Establish consistency in beginners
before adding the full variety.

For an athlete who can recover from it, use **up to two quality days and one
mostly easy long day per week**, with remaining sessions easy. Rotate quality:
e.g. threshold + VO2 one week, threshold + speed the next. This is a framework,
not a minimum quota. Calendar, other sports, strength and recovery can require
fewer hard runs. Separate hard days with easy/rest days. A long run with hard
finishing work counts as a quality day, not an extra third hard running day.

## Progress what the athlete can absorb

Anchor the next block to completed, tolerable training, not planned kilometres.
Increase volume or a quality-session demand when execution and recovery support
it, rather than increasing both automatically. The repo's 10% volume ceiling
is a guardrail, not a guarantee or weekly target. Retain deloads and taper;
plateaus and load reductions are valid responses to actual recovery.

Protect fueling, sleep and recovery as volume grows. Record reported
constraints without assuming a calorie deficit or diagnosing low energy
availability from Garmin data. Avoid pairing aggressive training increases
with aggressive weight loss. Do not derive calorie prescriptions from these
transcripts.

## VO2 and durability

Use consistent volume for long-term development, with targeted VO2 sessions.
A familiar example is 4 × 4 minutes hard but repeatable with easy recoveries,
scaled to the athlete. Repeated all-out sprints are not a default for novices
or fatigued runners. Do not add three sprint sessions weekly just because a
study protocol in the video used them.

When training history and race demands justify it, emphasize VO2 in a limited
block (the transcript suggests roughly 6–8 weeks before racing), then reassess
instead of escalating indefinitely. Preserve the actual taper. Judge progress
by execution, sustainable pace/effort, recovery and consistency, not a watch
VO2 number alone. Make no guaranteed timeline for improvement.

Build durability through consistent volume, gradually longer easy runs and
suitable strength. Add occasional race-pace efforts late in a long run only
after the athlete tolerates the duration and recovers well. Introduce heavy
or explosive strength according to experience and technique; cross-sport
interference rules still apply. Do not impose elite volume or lifting loads.

## Encode the intended stimulus

| Stimulus | Supported representation |
|---|---|
| Easy aerobic / long steady | `easy_run` / `long_run`, easy targets; 60+ minutes only when appropriate to current capacity |
| Sustained threshold | `tempo_run`, threshold targets |
| Broken threshold, e.g. 5 × 6 or 3 × 10 minutes | `interval_session`, threshold work targets and easy recoveries |
| VO2 repeats, e.g. 4 × 4 | `interval_session`, interval targets and repeatable effort |
| Short speed | When appropriate, 4–5 × 10–20 seconds with generous recovery; fractional `work_min` is supported, e.g. 0.25 for 15 seconds |
| Strength for durability | `strength_session`, appropriate loads, notes and recovery |

For strides, use controlled relaxed accelerations with full recovery; all-out
sprints are not cost-free. Easy running plus strides can use `interval_session`
with the easy portion in `warmup_min`; warmup has no pace target, so explain
its easy effort in the description. Prefer effort/form cues over unstable GPS
pace alerts for short reps. Include warmup, recovery and cooldown in totals.

An `interval_session` is not automatically VO2: classify its actual work
intensity and duration. `long_run` is one steady step and cannot encode a
separate fast finish. For mixed sessions requiring structured alerts, use a
supported interval construction that truly represents the session, or extend
and validate the builder before prescribing unsupported parameters. Do not
label a single steady step as a structured progressive workout.
