// Reading guides behind the (i) buttons on the analysis page.

export type Help = { shows: string; lookFor: string[]; caveats?: string[] };

export const HELP = {
  page: {
    shows:
      "How your aerobic engine, training load and recovery are moving over time. Filters at the top apply to every chart; the sliders under Aerobic engine decide which runs feed the efficiency trends.",
    lookFor: [
      "Read top-down: is the load sensible (calendar, volume, intensity, form)? Is the engine improving (efficiency, decoupling, drift)? Is recovery keeping up (resting HR, HRV, sleep)?",
      "HR creeping up at the same pace has three usual causes: fatigue (form very negative, resting HR up, HRV down), too much intensity (low-intensity share well under 80%), or conditions (heat, hills). The charts are arranged to tell those apart.",
      "Judge trends over 4–8+ weeks. Single sessions are noisy.",
    ],
  },
  calendar: {
    shows: "One square per day, coloured by that day's Garmin training load summed over the selected sports. Hover for the activities, click to filter the table below.",
    lookFor: [
      "Rhythm: hard days should be followed by light or empty days.",
      "Clusters of bright squares without a dark day between them are where fatigue builds.",
      "Empty stretches you didn't plan (illness, travel) explain later dips in fitness.",
    ],
    caveats: ["Colour is relative to the busiest day in the range, so a light week looks brighter when viewed alone."],
  },
  volume: {
    shows: "Hours of activity per period, stacked by sport.",
    lookFor: [
      "Steady progression: running volume rising by roughly 10% or less per week, with a lighter week every 3–4 weeks.",
      "Sudden jumps (often from cycling or hiking added on top of running) are the most common hidden cause of HR creep and fatigue.",
    ],
    caveats: ["Hours treat all sports equally; a commute ride is far less load than a run of the same length. Use the form chart for load."],
  },
  intensity: {
    shows: "Share of time spent in your Garmin heart-rate zones each period: low = Z1–2, moderate = Z3, high = Z4–5. The dashed line marks 80%.",
    lookFor: [
      "Polarized/80-20 training keeps the low band at or above the 80% line most weeks.",
      "A thick moderate (Z3) band is the 'grey zone': too hard to build aerobic base cheaply, too easy to be a quality session. Easy runs drifting into Z3 is the usual reason.",
      "Race or interval weeks will dip below 80%; that's fine if the surrounding weeks recover.",
    ],
    caveats: [
      "Zones come from the HR zones configured on your watch. If those are set from an estimated max HR, the split can be off. Check them in Garmin Connect.",
      "Includes all selected sports; toggle to running only to judge your running distribution.",
    ],
  },
  load: {
    shows:
      "Fitness = 42-day average of daily Garmin training load (what you've built). Fatigue = 7-day average (what you're carrying). Form = fitness − fatigue going into each day.",
    lookFor: [
      "Fitness rising slowly and steadily over weeks is the goal.",
      "Form between about −10 and −30 is productive training. Below about −30 for more than a week is deep fatigue: expect higher HR at a given pace, worse sleep and HRV.",
      "Form turning positive (+5 to +20) before a race means you've tapered.",
    ],
    caveats: ["Uses Garmin's own load per activity (an EPOC estimate), not power-based TSS. The thresholds are rough rules of thumb."],
  },
  efficiency: {
    shows:
      "Efficiency factor (EF) = speed ÷ heart rate, measured only while moving and only after the first 15 moving minutes, because HR is still climbing during the warm-up and would make every run look efficient. Runs with less than 10 moving minutes after that have no value and don't appear. For runs the speed is grade-adjusted, so hills count fairly. It's shown as the pace (or speed) you'd hold at the reference HR set by the slider. Filled dots are sessions that meet the filters and feed the trend line (the median per period); faint rings are sessions the filters leave out (no tooltip; loosen the filters to inspect one, or find it in the Activities table).",
    lookFor: [
      "The trend line moving up over 8–16 weeks: you run faster for the same heartbeat. That's the clearest sign the aerobic base is growing.",
      "A flat or falling trend while volume rises usually means fatigue or too much intensity. Cross-check form and resting HR.",
      "Colour the dots by temperature: hot days sit lower. If the drop lines up with heat, it isn't lost fitness.",
    ],
    caveats: [
      "Compare like with like: tighten the filters (duration, pace variability, climbing) until the remaining runs are similar sessions.",
      "The reference-HR pace assumes speed scales linearly with HR, so it's a fair comparison number, not a prediction.",
      "Cycling uses plain speed (no power is recorded), so wind and traffic add a lot of noise.",
    ],
  },
  decoupling: {
    shows:
      "Pa:HR decoupling: how much efficiency (grade-adjusted speed ÷ HR) fell from the first half of the session to the second, after the warm-up. Positive means HR rose and/or pace fell later on. The green band is ±5%.",
    lookFor: [
      "On steady runs of 60–90+ min, decoupling under 5% means your aerobic base comfortably supports that duration. Above 5% means the duration or pace is beyond it for now.",
      "The trend coming down for the same kind of long run is durability improving.",
      "Negative values usually mean the second half was easier (downhill, tailwind, slowing for a stop) or the warm-up wasn't finished.",
    ],
    caveats: [
      "Only meaningful on steady efforts. On intervals or fartleks it's noise, which is why those are excluded by default.",
      "Heat, dehydration and missing fuel all raise decoupling without any change in fitness.",
    ],
  },
  drift: {
    shows:
      "Drift onset: the minute when your 5-minute efficiency drops more than 3% below its baseline (moving minutes 15–25) and stays there for 5 minutes. Filled dots are runs that drifted; hollow rings are runs that never drifted, plotted at their full length.",
    lookFor: [
      "The onset minute moving later over weeks: you hold steady state for longer before cardiac drift starts.",
      "Onset consistently right after the baseline (around minute 30) on easy runs means the 'easy' pace is above your current steady-state ceiling. Slowing down or capping HR on those runs is usually the fix.",
      "More hollow rings over time is good news.",
    ],
    caveats: [
      "The earliest possible onset is about minute 30 (15 min warm-up + 10 min baseline + a 5-minute window), and runs need at least 35 moving minutes to be checked. Dots there mean drift began as early as the method can measure.",
      "Pace changes (hills, stops, surges) move efficiency too. Check pace variability in the tooltip.",
    ],
  },
  gct: {
    shows: "Ground contact time over the last 10 minutes minus moving minutes 15–25 of the run (runs of 45+ moving minutes only), in milliseconds. Positive = feet spending longer on the ground late in the run.",
    lookFor: [
      "Small values (under about 5–10 ms) mean form held up.",
      "A run with both high decoupling and big GCT creep points to muscular or elastic fatigue driving the HR rise. Strength work and long-run durability help more than slowing down.",
      "High decoupling with flat GCT points to the cardiovascular side: heat, hydration, pace too high for your base.",
    ],
    caveats: ["Slowing down lengthens ground contact by itself, so read it with the run's pace profile (click the dot to open its streams)."],
  },
  hrr: {
    shows: "Average heart-rate drop in the 60 s after each work interval that is followed by a recovery or rest lap, per session. Only structured workouts with recovery laps appear.",
    lookFor: [
      "Higher is better: 30–40+ bpm in a minute shows fast parasympathetic recovery; below about 20 is slow.",
      "A trend down over consecutive interval sessions, alongside low HRV or negative form, is an early sign of accumulating fatigue.",
    ],
    caveats: ["Standing still vs jogging the recovery changes the number a lot. Compare sessions with similar recoveries."],
  },
  restingHr: {
    shows: "Your daily resting heart rate from the watch, and its 7-day average (dashed).",
    lookFor: [
      "A slow drift down over months follows aerobic gains.",
      "The 7-day average rising 3–5+ bpm above normal for several days means fatigue, illness, heat, alcohol or poor sleep. If it lines up with HR creep in runs, recover rather than push.",
    ],
  },
  hrv: {
    shows: "Overnight HRV (average over the night), its 7-day average (dashed), and Garmin's 'balanced' band for you (shaded).",
    lookFor: [
      "The 7-day line inside the band means recovery is keeping up with training.",
      "The 7-day line dropping below the band for several days means your body is under strain. Ease off before HR creep and poor sessions follow.",
      "Single low nights after a hard session or a late night are normal; look at the 7-day line.",
    ],
    caveats: ["HRV is personal. Compare only with your own band, never with other people's numbers."],
  },
  sleep: {
    shows: "Garmin sleep score (0–100) per night.",
    lookFor: [
      "Runs of nights under about 70 often come right before resting HR rises and efficiency dips.",
      "Use it to explain a bad session rather than as a training target.",
    ],
  },
  bodyBattery: {
    shows: "Garmin body battery when you woke up (0–100).",
    lookFor: [
      "Waking repeatedly below about 50 means you're not recharging overnight. Hard sessions on those days tend to show more decoupling.",
    ],
    caveats: ["Body battery is derived from HRV and stress, so it overlaps with the HRV chart. It's the quickest daily read."],
  },
  table: {
    shows: "Every activity in the range (or the day picked on the calendar). The derived columns: @HR = pace/speed at the reference HR; Decoupl. = first-to-second-half efficiency loss; Drift = onset minute, or 'none'; GCT Δ = late minus early ground contact; HRR60 = HR drop 60 s after intervals; m/km = climbing per km.",
    lookFor: ["Click a row to open its streams and see why a session's numbers look the way they do."],
  },
  streams: {
    shows: "The session's recordings in 15-second bins: heart rate, grade-adjusted pace (or speed), power, ground contact, elevation and cadence on a shared time axis. Hover one panel and all of them follow. Dashed lines mark the end of the 15-min warm-up and the drift onset.",
    lookFor: [
      "Cardiac drift: HR rising while pace stays flat.",
      "Fatigue: pace falling and GCT rising late while HR stays the same.",
      "Whether a hill, stop or surge explains a jump in the numbers.",
    ],
  },
} satisfies Record<string, Help>;

export type HelpKey = keyof typeof HELP;
