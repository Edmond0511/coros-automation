"""Turn pulled COROS data into the dashboard's datasets.

  python3 coros.py ingest data/inbox.json   merge a pull into data/
  python3 coros.py build [--today YYYY-MM-DD]   write out/*.json, print what's due
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = ROOT / "out"

RACE_DAY = date(2027, 5, 16)  # half marathon; move when a race is picked
SEASON = [
    {"phase": "baseline", "name": "Baseline", "end": "2026-11-08",
     "goal": "Learn your normal HRV, resting HR and easy pace",
     "key": "Easy runs in zone 2, one strides session", "signs": "14+ days of HRV and resting HR, a race target set"},
    {"phase": "base", "name": "Base", "end": "2027-01-31",
     "goal": "Grow easy volume and the Thursday long run",
     "key": "Long run building toward 90 min, strides weekly", "signs": "Drift under 5% on long runs, faster pace at the same easy HR"},
    {"phase": "build", "name": "Build", "end": "2027-03-28",
     "goal": "Raise threshold and VO2max",
     "key": "One tempo or threshold session a week, long run to 1:45", "signs": "Threshold pace and VO2max rising, HRV holding"},
    {"phase": "race", "name": "Race-specific", "end": "2027-05-02",
     "goal": "Practise race pace and fuelling",
     "key": "Long runs with race-pace blocks, one 18-19 km run", "signs": "Race pace feels controlled at the end of long runs"},
    {"phase": "taper", "name": "Taper", "end": RACE_DAY.isoformat(),
     "goal": "Arrive fresh",
     "key": "Volume down 40-60%, a few short race-pace efforts", "signs": "HRV up, resting HR down, legs feel springy"},
]
SLEEP_GOAL_MIN = 450
START_FAST_S = 15  # first km this much faster than the run's average pace
STEP_NAMES = {"warmup": "Warm-up", "work": "Run", "recover": "Recover", "cooldown": "Cool-down"}
HARD_KINDS = {"intervals", "tempo", "strides"}
FULL_LAP_M = 950  # partial last laps skew drift and pace


def load(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True))


def d(s):
    return date.fromisoformat(s)


def monday(day):
    return day - timedelta(days=day.weekday())


def phase_of(day):
    for p in SEASON:
        if day <= d(p["end"]):
            return p["phase"]
    return "after"


def step_line(step):
    """{"kind": "work", "repeat": 6, "sec": 20, "pace": "4:45", "recover": "60 s easy jog"} -> one readable line."""
    size = next(f"{step[k]} {u}" for k, u in (("min", "min"), ("sec", "s"), ("km", "km")) if k in step)
    target = f"zone {step['zone']}" if "zone" in step else f"{step['pace']}/km" if "pace" in step else "easy"
    line = f"{STEP_NAMES[step['kind']]} {size} at {target}"
    if step.get("repeat", 1) > 1:
        line = f"{step['repeat']} x {line}"
    return line + (f", {step['recover']} between" if step.get("recover") else "")


def clock(seconds):
    """3094 -> '51:34', 7093 -> '1:58:13'."""
    if seconds is None:
        return None
    h, rest = divmod(round(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


# ---------- ingest ----------

def ingest(pull_path):
    pull = json.loads(Path(pull_path).read_text())
    days = load(DATA / "days.json", {})
    for row in pull.get("days", []):
        # A day's data arrives in pieces (sleep syncs the next morning), so keep known fields.
        merged = days.get(row["date"], {})
        merged.update({k: v for k, v in row.items() if v is not None})
        days[row["date"]] = merged
    acts = load(DATA / "activities.json", {})
    for a in pull.get("activities", []):
        acts[a["id"]] = a
    fitness = load(DATA / "fitness.json", {})
    if pull.get("fitness"):
        fitness[pull["fitness"]["date"]] = pull["fitness"]
    save(DATA / "days.json", days)
    save(DATA / "activities.json", acts)
    save(DATA / "fitness.json", fitness)
    print(f"ingested {len(pull.get('days', []))} days, {len(pull.get('activities', []))} activities")


# ---------- metrics ----------

def zone_of(hr, zone_max):
    for i, top in enumerate(zone_max):
        if hr <= top:
            return i + 1
    return len(zone_max)


def efficiency(laps):
    dist = sum(l[0] for l in laps)
    time = sum(l[1] for l in laps)
    hr = sum(l[1] * l[2] for l in laps) / time
    return dist / time / hr


def drift_pct(act):
    """Pace-to-HR decoupling, first half vs second half. Positive means HR rose for the same pace."""
    full = [l for l in act.get("laps", []) if l[0] >= FULL_LAP_M]
    if act["duration_s"] < 1800 or len(full) < 4:
        return None
    half = len(full) // 2
    return round((efficiency(full[:half]) / efficiency(full[half:]) - 1) * 100, 1)


def easy_laps(act, zone_max):
    return [l for l in act.get("laps", []) if l[0] >= FULL_LAP_M and l[2] <= zone_max[1]]


def pace_of(laps):
    dist = sum(l[0] for l in laps)
    return round(sum(l[1] for l in laps) / dist * 1000) if dist else None


def readiness(day, prior):
    """Morning check from HRV, resting HR and sleep against the previous 7 days."""
    if not day.get("hrv") and not day.get("sleep_min"):
        return "unknown", "Last night's sleep hasn't synced yet"
    reasons = []
    hrvs = [p["hrv"] for p in prior if p.get("hrv")]
    rhrs = [p["rhr"] for p in prior if p.get("rhr")]
    if day.get("hrv") and len(hrvs) >= 3 and day["hrv"] < mean(hrvs) * 0.85:
        reasons.append(f"HRV {day['hrv']} ms is well below your 7-day average of {mean(hrvs):.0f}")
    if day.get("rhr") and len(rhrs) >= 3 and day["rhr"] >= mean(rhrs) + 5:
        reasons.append(f"Resting HR {day['rhr']} is up from your 7-day average of {mean(rhrs):.0f}")
    if day.get("sleep_min") and day["sleep_min"] < 360:
        reasons.append(f"Only {day['sleep_min'] // 60}h {day['sleep_min'] % 60}m of sleep")
    if reasons:
        return "easy", "; ".join(reasons)
    if len(hrvs) < 3:
        return "baseline", "Still learning your normal HRV and resting HR"
    return "ready", "HRV, resting HR and sleep are in your normal range"


def grade(workout, run, zone_max):
    completion = run["duration_s"] / (workout["duration_min"] * 60)
    in_zone = None
    cap = workout.get("zone_max")
    if cap and zone_max and run.get("laps"):
        laps = run["laps"]
        in_zone = sum(l[1] for l in laps if l[2] <= zone_max[cap - 1]) / sum(l[1] for l in laps)
    if completion >= 0.9 and (in_zone is None or in_zone >= 0.8):
        verdict = "On target"
    elif completion >= 0.6 and (in_zone is None or in_zone >= 0.5):
        verdict = "Partly"
    else:
        verdict = "Off target"
    note = f"{completion:.0%} of planned time"
    if in_zone is not None:
        note += f", {in_zone:.0%} at or under zone {cap} heart rate"
    return verdict, note


# ---------- facts for the coaching ----------

def baseline(days, metric, today):
    """Newest value on or before today, against the 7 and 28 days before it."""
    dated = sorted((k, v[metric]) for k, v in days.items() if v.get(metric) is not None and d(k) <= today)
    if not dated:
        return None
    last_day, last = dated[-1]

    def avg(n):
        vals = [v for k, v in dated if 0 < (d(last_day) - d(k)).days <= n]
        return round(mean(vals), 1) if vals else None
    return {"date": last_day, "latest": last, "avg7": avg(7), "avg28": avg(28),
            "days_28": sum(1 for k, _ in dated if (today - d(k)).days < 28)}


def streak(days, metric, last_day, test):
    n, day = 0, d(last_day)
    while (v := days.get(day.isoformat(), {}).get(metric)) is not None and test(v):
        n += 1
        day -= timedelta(days=1)
    return n


def red_lines(days, base):
    """Patterns worth a doctor's opinion rather than a training tweak."""
    out = []
    rhr, hrv = base.get("rhr"), base.get("hrv")
    if rhr and rhr["avg28"] and rhr["days_28"] >= 7:
        n = streak(days, "rhr", rhr["date"], lambda v: v >= rhr["avg28"] + 10)
        if n >= 3:
            out.append(f"Resting HR has been 10+ bpm above your 28-day average ({rhr['avg28']:.0f}) for {n} days")
    if hrv and hrv["avg28"] and hrv["days_28"] >= 7:
        n = streak(days, "hrv", hrv["date"], lambda v: v < hrv["avg28"] * 0.8)
        if n >= 5:
            out.append(f"HRV has been under 80% of your 28-day average ({hrv['avg28']:.0f} ms) for {n} days")
    return out


def run_facts(a):
    full = [l for l in a.get("laps", []) if l[0] >= FULL_LAP_M]
    avg_pace = pace_of(full)
    first = round(full[0][1] / full[0][0] * 1000) if full else None
    return {"id": a["id"], "date": a["date"], "name": a["name"], "km": round(a["distance_m"] / 1000, 2),
            "minutes": round(a["duration_s"] / 60), "avg_hr": a.get("avg_hr"), "pace": clock(a["duration_s"] / a["distance_m"] * 1000),
            "drift_pct": drift_pct(a), "first_km": clock(first),
            "started_fast": bool(first and avg_pace and avg_pace - first > START_FAST_S),
            "hr_by_km": [l[2] for l in a.get("laps", [])]}


def facts(today, days, runs, weeks):
    base = {m: baseline(days, m, today) for m in ("hrv", "rhr", "sleep_min", "stress")}
    week_sleep = [days.get((today - timedelta(days=i)).isoformat(), {}).get("sleep_min") for i in range(7)]
    cur, prev = weeks[-1], [w for w in weeks[-4:-1] if w["runs"]]
    prev_km = mean(w["run_km"] for w in prev) if prev else None
    this_long = max((a["duration_s"] for a in runs if d(a["date"]) >= d(cur["week"])), default=0) / 60
    last_long = max((a["duration_s"] for a in runs
                     if d(cur["week"]) - timedelta(days=7) <= d(a["date"]) < d(cur["week"])), default=0) / 60
    phase = phase_of(today)
    return {
        # Baselines need about two weeks before trends mean anything.
        "baseline_ready": all(base[m] and base[m]["days_28"] >= 14 for m in ("hrv", "rhr")),
        "baselines": base,
        "sleep_debt_7d_min": sum(max(0, SLEEP_GOAL_MIN - s) for s in week_sleep if s),
        "ramp": {"week_km": cur["run_km"], "prev_3wk_avg_km": round(prev_km, 1) if prev_km else None,
                 "km_jump": bool(prev_km and cur["run_km"] > prev_km * 1.1),
                 "long_run_min": round(this_long), "last_long_run_min": round(last_long),
                 "long_run_jump": bool(last_long and this_long - last_long > 15)},
        "red_lines": red_lines(days, base),
        "recent_runs": [run_facts(a) for a in runs[-5:]],
        "season": {"phase": phase, "phase_ends": next((p["end"] for p in SEASON if p["phase"] == phase), None),
                   "race_day": RACE_DAY.isoformat(), "weeks_to_race": (RACE_DAY - today).days // 7},
    }


def insight_row(n, date_, kind, ins, week=None):
    return {"id": f"{date_}-{kind}-{n}", "date": date_, "kind": kind, "week": week,
            "area": ins.get("area"), "tone": ins.get("tone"), "title": ins["finding"],
            "verdict": ins.get("verdict"), "do": "\n".join(ins.get("do", [])), "measure": ins.get("measure"),
            "activity_id": ins.get("activity_id"), "order": n, "alerts": None, "baseline_ready": None}


# ---------- build ----------

def build(today):
    days = load(DATA / "days.json", {})
    acts = sorted(load(DATA / "activities.json", {}).values(), key=lambda a: a["start"])
    fitness = load(DATA / "fitness.json", {})
    zones = load(DATA / "zones.json", None)
    zone_max = zones["zone_max"] if zones else None
    weeks_dir = DATA / "weeks"
    week_docs = {p.stem: json.loads(p.read_text()) for p in sorted(weeks_dir.glob("*.json"))}
    coach_docs = {p.stem: json.loads(p.read_text()) for p in sorted((DATA / "coach").glob("*.json"))}

    dates = sorted(set(days) | {a["date"] for a in acts} | set(fitness))
    if not dates:
        sys.exit("no data yet: ingest a pull first")
    first = d(dates[0])

    # daily
    daily = []
    day = first
    while day <= today:
        key = day.isoformat()
        row = {"date": key, **{k: v for k, v in days.get(key, {}).items() if k != "date"}}
        prior = [days.get((day - timedelta(days=i)).isoformat(), {}) for i in range(1, 8)]
        row["readiness"], row["readiness_note"] = readiness(row, prior)
        week_load = sum(a.get("load") or 0 for a in acts if 0 <= (day - d(a["date"])).days < 7)
        month_load = sum(a.get("load") or 0 for a in acts if 0 <= (day - d(a["date"])).days < 28)
        row["load_7d"] = week_load
        # Acute:chronic is meaningless until there are 4 weeks of history.
        row["load_ratio"] = round(week_load / (month_load / 4), 2) if (day - first).days >= 27 and month_load else None
        for k, v in fitness.get(key, {}).items():
            if k != "date":
                row[k] = v
        if row.get("sleep_min"):
            row["sleep"] = f"{row['sleep_min'] // 60}h {row['sleep_min'] % 60}m"
        for k in ("threshold_pace", "pred_5k", "pred_10k", "pred_half", "pred_full"):
            if row.get(k + "_s"):
                row[k] = clock(row[k + "_s"])
        daily.append(row)
        day += timedelta(days=1)

    # workouts, matched to runs by date
    runs_by_date = {}
    for a in acts:
        if a["sport"] == "run" and a["duration_s"] >= 600:
            best = runs_by_date.get(a["date"])
            if not best or a["duration_s"] > best["duration_s"]:
                runs_by_date[a["date"]] = a
    today_ready = daily[-1]["readiness"]
    workouts, graded = [], {}
    for wk, doc in week_docs.items():
        for i, w in enumerate(doc.get("workouts", [])):
            row = {"id": f"{w['date']}-{i}", "week": wk, **w, "result": "upcoming", "grade": None,
                   "grade_note": None, "swap": False}
            row["steps_text"] = "\n".join(step_line(s) for s in row.pop("steps", []))
            run = runs_by_date.get(w["date"])
            if run:
                row["result"] = "done"
                row["grade"], row["grade_note"] = grade(w, run, zone_max)
                graded[run["id"]] = (w["name"], row["grade"])
            elif d(w["date"]) < today:
                row["result"] = "missed"
            elif d(w["date"]) == today:
                row["result"] = "today"
                row["swap"] = w["kind"] in HARD_KINDS and today_ready == "easy"
            workouts.append(row)

    # activities and laps
    activities, laps = [], []
    for a in reversed(acts):
        row = {k: a.get(k) for k in ("id", "date", "sport", "name", "duration_s", "distance_m", "avg_hr", "load", "aerobic_te")}
        row["km"] = round(a["distance_m"] / 1000, 2) if a.get("distance_m") else None
        row["minutes"] = round(a["duration_s"] / 60)
        is_run = a["sport"] == "run" and a["duration_s"] >= 600
        row["pace_s"] = round(a["duration_s"] / a["distance_m"] * 1000) if is_run and a.get("distance_m") else None
        row["drift_pct"] = drift_pct(a) if is_run else None
        row["easy"] = (a["avg_hr"] <= zone_max[1]) if is_run and zone_max else None
        row["easy_pace_s"] = pace_of(easy_laps(a, zone_max)) if is_run and zone_max else None
        row["time"], row["pace"] = clock(a["duration_s"]), clock(row["pace_s"])
        row["workout"], row["grade"] = graded.get(a["id"], (None, None))
        activities.append(row)
        for n, (dist, time, hr) in enumerate(a.get("laps", []), 1):
            laps.append({"id": a["id"], "lap": n, "km": round(dist / 1000, 2),
                         "pace_s": round(time / dist * 1000), "pace": clock(time / dist * 1000), "avg_hr": hr,
                         "zone": zone_of(hr, zone_max) if zone_max else None})

    # weeks
    weeks = []
    wk = monday(first)
    n = 1
    while wk <= today:
        end = wk + timedelta(days=6)
        in_week = [a for a in acts if wk <= d(a["date"]) <= end]
        runs = [a for a in in_week if a["sport"] == "run" and a["duration_s"] >= 600]
        drifts = [x for x in (drift_pct(a) for a in runs) if x is not None]
        row = {"week": wk.isoformat(), "week_no": n, "phase": phase_of(wk),
               "run_km": round(sum(a["distance_m"] for a in runs) / 1000, 1), "runs": len(runs),
               "load": sum(a.get("load") or 0 for a in in_week),
               "drift_avg": round(mean(drifts), 1) if drifts else None,
               "longest_easy_min": None, "easy_pace_s": None}
        if zone_max:
            easy_runs = [a for a in runs if a["avg_hr"] <= zone_max[1]]
            row["longest_easy_min"] = round(max(a["duration_s"] for a in easy_runs) / 60) if easy_runs else 0
            row["easy_pace_s"] = pace_of([l for a in runs for l in easy_laps(a, zone_max)])
            row["easy_pace"] = clock(row["easy_pace_s"])
            for z in range(1, 6):
                row[f"z{z}_min"] = round(sum(l[1] for a in runs for l in a.get("laps", [])
                                             if zone_of(l[2], zone_max) == z) / 60)
        report = week_docs.get(wk.isoformat(), {}).get("report")
        row["summary"] = report["summary"] if report else None
        weeks.append(row)
        wk += timedelta(weeks=1)
        n += 1

    runs = [a for a in acts if a["sport"] == "run" and a["duration_s"] >= 600]
    fx = facts(today, days, runs, weeks)
    save(OUT / "facts.json", fx)

    # coaching: daily briefs and insights, run debriefs, weekly reviews
    coach = []
    newest_brief = max((k for k, v in coach_docs.items() if v.get("brief")), default=None)
    for day_, doc in coach_docs.items():
        if doc.get("brief"):
            b = doc["brief"]
            # Red lines come from the facts, never from the written brief, so they can't be left out.
            now = day_ == newest_brief
            coach.append({**insight_row(0, day_, "brief", {"tone": b["verdict"], "finding": b["headline"]}),
                          "id": f"{day_}-brief", "verdict": b["today"],
                          "alerts": "\n".join(fx["red_lines"]) if now else None,
                          "baseline_ready": fx["baseline_ready"] if now else None})
        for i, ins in enumerate(doc.get("insights", [])):
            coach.append(insight_row(i, day_, "debrief" if ins.get("activity_id") else "insight", ins))
    for wk_, doc in week_docs.items():
        for i, ins in enumerate((doc.get("report") or {}).get("insights", [])):
            coach.append(insight_row(i, wk_, "review", ins, week=wk_))
    season = [{**p, "start": (d(SEASON[i - 1]["end"]) + timedelta(days=1)).isoformat() if i else first.isoformat(),
               "current": p["phase"] == phase_of(today)} for i, p in enumerate(SEASON)]

    for name, rows in [("daily", daily), ("activities", activities), ("laps", laps),
                       ("weeks", weeks), ("workouts", workouts), ("coach", coach), ("season", season)]:
        save(OUT / f"{name}.json", rows)

    debriefed = {r["activity_id"] for r in coach if r["activity_id"]}
    debrief_due = [a["id"] for a in runs if a["id"] not in debriefed and (today - d(a["date"])).days <= 14]

    report_due = [w["week"] for w in weeks
                  if d(w["week"]) + timedelta(days=6) <= today and not w["summary"]
                  and (w["runs"] or w["load"])]
    reported = [w["week"] for w in weeks if w["summary"]] + report_due
    plan_due = None
    if reported:
        nxt = d(max(reported)) + timedelta(weeks=1)
        if nxt <= today + timedelta(days=1) and not week_docs.get(nxt.isoformat(), {}).get("workouts"):
            plan_due = nxt.isoformat()
    print(json.dumps({
        "zones_set": bool(zone_max),
        "report_due": report_due,
        "plan_due": plan_due,
        "plan_phase": phase_of(d(plan_due)) if plan_due else None,
        "coach_due": today.isoformat() not in coach_docs,
        "debrief_due": debrief_due,
        "red_lines": fx["red_lines"],
        "today_readiness": daily[-1]["readiness"],
        "swap_today": any(w["swap"] for w in workouts),
    }, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "ingest" and len(sys.argv) == 3:
        ingest(sys.argv[2])
    elif cmd == "build":
        args = sys.argv[2:]
        build(d(args[1]) if args[:1] == ["--today"] else date.today())
    else:
        sys.exit(__doc__)
