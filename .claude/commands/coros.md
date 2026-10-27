---
description: Pull new COROS data, rebuild the dashboard, write due reports and workouts
argument-hint: "[push]"
---

Refresh the COROS Training dashboard: https://claude.ai/artifact/684Px6daBtGf8fM7T4Ke47

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

## 2. Build

Run `python3 coros.py build`. It prints what's due:

- `report_due`: for each week listed, write `report` into `data/weeks/<monday>.json`: `{"summary": "...", "good": [...], "bad": [...], "advice": [...]}`. Base it on `out/weeks.json`, `out/activities.json`, `out/laps.json` and `out/daily.json` for that week, and the previous reports. Judge everything against the goal: higher VO2max and better endurance, measured by heart-rate drift (under 5%), pace at easy HR and the longest easy run. Quote real numbers. Plain words, no em dashes.
- `plan_due`: write `workouts` into `data/weeks/<plan_due>.json`: 3 or 4 runs, each `{"date", "name", "kind": "easy|long|strides|tempo|intervals", "duration_min", "zone_max", "description", "status": "draft"}`. In the `baseline` phase use only easy and long runs plus one strides session. In `build`, add at most one tempo or interval session. Base duration and spacing on recent load, readiness and how last week's runs graded.
- `zones_set: false`: remind the user to send their heart-rate zone tops from the COROS app so you can save `data/zones.json` as `{"zone_max": [z1, z2, z3, z4, z5]}` (bpm, the top of each zone).

If you wrote anything, run `python3 coros.py build` again.

## 3. Publish

For each of `daily`, `activities`, `laps`, `weeks`, `workouts`: upload `out/<name>.json` with the Artifact tool (`url` above, `asset: true`, one file per call). Read the `datasets/<name>` documents, then in one `ArtifactData` batch `update` each with the new `source.url` and `updated: {"at": <now, ISO UTC>, "by": "Claude, from /coros"}`, pinned to the versions you read. Then delete the replaced uploads (Artifact `delete`, `url` above, `path` = old asset id).

## 4. Tell the user

In a few lines: today's readiness, anything that changed, any swap warning, and new drafts waiting for "push them". If workouts were drafted, list them briefly.

## Push workouts

Only when the user asks. For each `draft` workout dated today or later in `data/weeks/*.json`, call `createScheduledWorkout` (running, sportType 1) with the workout's date, `name`, `description`, and sections that use heart-rate zones (intensityType 1, `sectionIntensity`) capped at `zone_max`. For strides use pace (intensityType 2). Set its `status` to `on_watch`, then do steps 2 to 4. Remind the user that moving or deleting a pushed workout is done in the COROS app.
