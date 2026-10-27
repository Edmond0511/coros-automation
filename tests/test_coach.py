import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import coros
from test_coros import RUN


def days_from(start, values, metric):
    return {(date.fromisoformat(start) + timedelta(days=i)).isoformat(): {metric: v} for i, v in enumerate(values)}


class Facts(unittest.TestCase):
    def test_phases_follow_the_season_dates(self):
        self.assertEqual(coros.phase_of(date(2026, 11, 8)), "baseline")
        self.assertEqual(coros.phase_of(date(2026, 11, 9)), "base")
        self.assertEqual(coros.phase_of(date(2027, 5, 16)), "taper")
        self.assertEqual(coros.phase_of(date(2027, 5, 17)), "after")

    def test_step_lines(self):
        self.assertEqual(coros.step_line({"kind": "warmup", "min": 10, "zone": 1}), "Warm-up 10 min at zone 1")
        self.assertEqual(coros.step_line({"kind": "work", "repeat": 6, "sec": 20, "pace": "4:45", "recover": "60 s jog"}),
                         "6 x Run 20 s at 4:45/km, 60 s jog between")

    def test_baseline_excludes_the_latest_day(self):
        days = days_from("2026-10-01", [60] * 10 + [70], "rhr")
        b = coros.baseline(days, "rhr", date(2026, 10, 11))
        self.assertEqual((b["latest"], b["avg7"], b["days_28"]), (70, 60, 11))

    def test_resting_hr_red_line_needs_three_high_days(self):
        days = days_from("2026-10-01", [60] * 14 + [72, 72], "rhr")
        base = {"rhr": coros.baseline(days, "rhr", date(2026, 10, 16))}
        self.assertEqual(coros.red_lines(days, base), [])
        days["2026-10-17"] = {"rhr": 73}
        base = {"rhr": coros.baseline(days, "rhr", date(2026, 10, 17))}
        self.assertEqual(len(coros.red_lines(days, base)), 1)

    def test_fast_start_is_flagged(self):
        fast = {**RUN, "laps": [[1000, 380, 150]] + RUN["laps"][1:]}
        self.assertFalse(coros.run_facts(RUN)["started_fast"])
        self.assertTrue(coros.run_facts(fast)["started_fast"])


class CoachBuild(unittest.TestCase):
    def test_coach_rows_and_debrief_due(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            coros.DATA, coros.OUT = tmp / "data", tmp / "out"
            coros.save(coros.DATA / "activities.json", {"r1": RUN})
            coros.save(coros.DATA / "days.json", {"2026-10-24": {"rhr": 64}})
            ins = {"area": "pacing", "tone": "bad", "finding": "First km 6:16", "do": ["Start slower", "Check HR at 10 min"]}
            coros.save(coros.DATA / "coach" / "2026-10-25.json",
                       {"brief": {"verdict": "easy", "headline": "Short sleep", "today": "Rest"}, "insights": [ins]})
            out = StringIO()
            with redirect_stdout(out):
                coros.build(date(2026, 10, 25))
            status = json.loads(out.getvalue())
            self.assertEqual(status["debrief_due"], ["r1"])
            self.assertFalse(status["coach_due"])
            coach = json.loads((coros.OUT / "coach.json").read_text())
            self.assertEqual([r["kind"] for r in coach], ["brief", "insight"])
            self.assertEqual(coach[1]["do"], "Start slower\nCheck HR at 10 min")
            season = json.loads((coros.OUT / "season.json").read_text())
            self.assertEqual([s["current"] for s in season], [True, False, False, False, False])


if __name__ == "__main__":
    unittest.main()
