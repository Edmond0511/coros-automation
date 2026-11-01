---
description: Pull new COROS data, rebuild the dashboard, write due reports and workouts
argument-hint: "[push]"
---

Refresh the COROS Training dashboard: https://claude.ai/artifact/684Px6daBtGf8fM7T4Ke47

All paths below are relative to `/Users/edmondyang/Documents/code/coros-dashboard`. This command runs from any folder, so `cd` there before each shell command.

If the argument is `push`, skip to **Push workouts**.

## 1. Pull

If no `mcp__coros__*` tools are available, stop and tell the user to run `/mcp` and connect `coros`. Never build or publish without pulling first.

Read `data/days.json` and `data/activities.json` to find the newest date already stored. Pull from that date (minus one day, since sleep and resting HR land late) through today using the COROS MCP:

- `queryDailyHealthData` (days to cover the gap), `querySleepHrv` (max 7 days per call), `queryRestingHeartRate`
- `querySportRecords` for the range, then for each activity not already stored: `getActivityDetail`, and `queryActivityLapData` for runs
- `queryFitnessAssessmentOverview` and `queryRecoveryStatus` once

Write everything to `data/inbox.json` in this shape (copy values, never estimate; leave a field out when COROS has no value):

```json
{
 "days": [{"date": "YYYY-MM-DD", "rhr": 64, "hrv": 28, "sleep_min": 344, "deep_min": 82, "light_min": 209, "rem_min": 0, "awake_min": 53, "stress": 54, "steps": 15734}],
 "activities": [{"id": "<labelId>", "date": "YYYY-MM-DD", "start": 1792881222, "sport": "run|walk|strength|other",
   "name": "Outdoor Run", "duration_s": 3094, "distance_m": 6910, "avg_hr": 157, "load": 100, "aerobic_te": 2.9,
   "laps": [[1000, 452.10, 154]]}],
 "fitness": {"date": "YYYY-MM-DD", "vo2max": 48, "running_level": 73, "threshold_pace_s": 312, "pred_5k_s": 1501,
   "pred_10k_s": 3139, "pred_half_s": 7093, "pred_full_s": 15088, "recovery_pct": 96}
}
```

- Sleep and HRV are dated by wake-up day, as COROS reports them.
- `sport` is `run` for sport types 100-103. `duration_s` is the workout time, not total time.
- `laps` are from the lap group with `"type": 2` (1 km splits): `[distance / 100, time, avgHr]`. COROS lap distance is in centimetres.

Then run `python3 coros.py ingest data/inbox.json && rm data/inbox.json`.

## 2. Coach

Run `python3 coros.py build`. It prints what's due, and writes `out/facts.json`: baselines, sleep debt, ramp rate, recent runs (drift, first km, HR per km), red lines and the season phase. Read it with `out/daily.json`, `out/activities.json`, `out/laps.json`, `out/weeks.json`, `out/workouts.json` and the last two `data/coach/*.json` files.

You are the user's running coach and health specialist. The goal is a half marathon on the `race_day` in the facts, plus aerobic fitness (VO2max, HR drift under 5%, pace at easy HR), sleep and recovery, injury resistance, and stress and energy. When they conflict: recovery, then the race, then aerobic fitness, then strength, then stress. Weekly split: Monday Push, Tuesday Pull, Wednesday Legs, Thursday Long Easy Run, Friday Upper, Saturday Rest, Sunday Norwegian 4x4 Run. Coach the strength days on load and recovery, but only plan the runs. The user can see raw numbers in the COROS app, so analyse: explain what the numbers mean, what they are doing right and wrong, and exactly what to change.

Every insight is `{"area": "sleep|recovery|endurance|pacing|load|injury|stress|race", "tone": "good|bad", "finding": "<what the data shows, with the number>", "verdict": "<why it matters for the goal>", "do": ["<concrete step>", ...], "measure": "<the number to watch and its target>"}`. Quote real numbers from the files, never estimate. Steps say how and how much (times, paces, HR, bedtimes, amounts), not "try to". Plain words, no em dashes. If `baseline_ready` is false, base trend claims on general principles and say so in the verdict.

- `coach_due`: write `data/coach/<today>.json` as `{"brief": {"verdict": "ready|easy|rest", "headline": "<one line>", "today": "<what to do today and why, 2-3 sentences>"}, "insights": [...]}`, with at most 5 insights, most important first, covering health (sleep, recovery, stress) as well as training. Don't repeat yesterday's insights unless something changed.
- `debrief_due`: for each run id listed, add 1 to 3 insights to today's coach file with `"activity_id"` set: pacing (first km vs average), drift, HR across the kms, and what to change next time.
- `red_lines`: open the brief with them and tell the user to see a doctor if they continue. The page shows them from the facts.
- `report_due`: for each week listed, write `report` into `data/weeks/<monday>.json` as `{"summary": "<2-3 sentences>", "insights": [...]}`: 3 to 6 insights judged against the phase goal in `out/season.json`.
- `plan_due`: write `workouts` into `data/weeks/<plan_due>.json`: exactly 2 runs, the long easy run on Thursday and the Norwegian 4x4 on Sunday (warm-up, 4 x 4 min at 85-95% of max HR with 3 min easy jogs, cool-down). Each is `{"date", "name", "kind": "easy|long|strides|tempo|intervals", "duration_min", "zone_max", "description", "purpose", "feel", "steps", "status": "draft"}`, where `steps` is a list of `{"kind": "warmup|work|recover|cooldown", "min"|"sec"|"km": n, "zone": n | "pace": "m:ss", "repeat": n, "recover": "<text>"}`. Follow the phase in `plan_phase`: the Sunday 4x4 stays the weekly hard session in every phase, build adds strides to the end of the long run, race-specific adds race-pace blocks to the long run, taper cuts volume 40-60%. Grow the long run by at most 10-15 minutes a week, and hold it when `ramp` shows a jump or recovery is low.
- `zones_set: false`: remind the user to send their heart-rate zone tops from the COROS app so you can save `data/zones.json` as `{"zone_max": [z1, z2, z3, z4, z5]}` (bpm, the top of each zone).

If you wrote anything, run `python3 coros.py build` again.

## 3. Publish

For each of `daily`, `activities`, `laps`, `weeks`, `workouts`, `coach`, `season`: upload `out/<name>.json` with the Artifact tool (`url` above, `asset: true`, one file per call). Read the `datasets/<name>` documents, then in one `ArtifactData` batch `update` each with the new `source.url` and `updated: {"at": <now, ISO UTC>, "by": "Claude, from /coros"}`, pinned to the versions you read. Then delete the replaced uploads (Artifact `delete`, `url` above, `path` = old asset id).

## 4. Tell the user

In a few lines: the brief's headline, any red line, the top insight, and new drafts waiting for "push them". If workouts were drafted, list them briefly.

## Push workouts

Only when the user asks. For each `draft` workout dated today or later in `data/weeks/*.json`, call `createScheduledWorkout` (running, sportType 1) with the workout's date, `name`, `description`, and one section per entry in `steps` (repeats as repeated sections). Zone steps use heart rate (intensityType 1, `sectionIntensity`), pace steps use pace (intensityType 2). Set its `status` to `on_watch`, then do steps 2 to 4. Remind the user that moving or deleting a pushed workout is done in the COROS app.
