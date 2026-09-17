# /newplan - Interview, research the race, design a plan, save it

`$ARGUMENTS` = an optional starting hint ("marathon in November", "get back
into shape"). Empty is fine — the interview starts from scratch.

Read the `workout-design` skill before writing any JSON.

## 1. Start from what is already known

```bash
uv run coach profile show
uv run coach plan list
```

Never ask for anything the profile already holds. If there is no profile yet,
gather the basics in the interview and offer to store them at the end.

## 2. Interview

One question at a time, in plain language, in this order:

1. **Goal** — race, general fitness, body composition, return from injury, or
   a strength goal.
2. **The race, by name** — the name is what unlocks course research. Also the
   date, and whether they have run it before.
3. **Current load** — weekly km and longest recent run. Never guess these;
   an over-ambitious week 1 is the main way plans fail.
4. **Calendar** — days per week, which days, and the longest session they can
   fit on a weekday vs a weekend.
5. **Other sports** — what else they keep doing, and what gives way when time
   is short.
6. **Body** — injuries, current niggles, movements to avoid.
7. **Constraints** — equipment, terrain they can actually reach, blackout
   dates, hard rules ("never Sundays").

The athlete answers in their own words. Converting to standard values is your
job: miles → km, "tue thu sat" → days, "second Sunday of November" → a date,
"sub 3:30" → a target time. **When you cannot convert confidently, ask
again** naming the ambiguity ("which November — 2026?"). Never record a fact
you had to guess.

Stop when you can write a responsible plan, not when the list is exhausted.

## 3. Research the race

As soon as you have the race name, search for it. Use WebSearch, and read the
race's own site and Wikipedia where they exist.

What matters is what changes the training:
- total elevation gain, and **where** the climbs fall (which km)
- surface, altitude, technical sections
- typical weather on that date, and the start time
- laps vs point-to-point

Report what you found with sources, and say plainly what you could not find.
"Unknown" is a fine answer; an invented elevation profile is not.

## 4. Design the plan

Follow the `workout-design` skill: the five primitives, the coaching rules,
and `coach.tools` for pace zones and volume progression rather than mental
arithmetic. Shape the specifics around the course — hill work where the
course climbs, heat work if it will be hot.

Show the athlete the shape before you save it: weeks, themes, weekly volume,
and the key sessions. Explain *why* it looks like that in two or three
sentences. Let them object.

## 5. Save

Write the JSON to `/tmp/plan.json`, then:

```bash
uv run coach plan import /tmp/plan.json
```

If it rejects a workout, fix that workout and re-import. Report the new plan
id and the workout count.

## 6. Hand off

End with what they can do next, and do not do it for them:

> Plan 4 saved — 11 weeks, 58 workouts, ending on race day.
> `/push` to send it to your watch, `/adjust` to change anything first.
