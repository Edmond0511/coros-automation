import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import coros

# Real run from 2026-10-24.
RUN = {"id": "r1", "date": "2026-10-24", "start": 1792881222, "sport": "run", "name": "Outdoor Run",
       "duration_s": 3094, "distance_m": 6910, "avg_hr": 157, "load": 100, "aerobic_te": 2.9,
       "laps": [[1000, 452.10, 154], [1000, 463.38, 155], [1000, 445.92, 152], [1000, 476.26, 158],
                [1000, 473.02, 159], [1000, 455.02, 161], [908.19, 328.72, 157]]}
ZONES = [140, 155, 165, 175, 200]


class Metrics(unittest.TestCase):
    def test_drift_uses_full_laps_split_in_half(self):
        # First 3 km avg 153.7 bpm at 7:34/km, next 3 km 159.3 bpm at 7:48/km.
        self.assertEqual(coros.drift_pct(RUN), 6.9)

    def test_drift_needs_30_minutes(self):
        self.assertIsNone(coros.drift_pct({**RUN, "duration_s": 1700}))

    def test_easy_pace_only_counts_laps_under_zone_2(self):
        laps = coros.easy_laps(RUN, ZONES)
        self.assertEqual([l[2] for l in laps], [154, 155, 152])
        self.assertEqual(coros.pace_of(laps), 454)

    def test_readiness_flags_low_hrv_and_short_sleep(self):
        prior = [{"hrv": 40, "rhr": 60}] * 5
        status, note = coros.readiness({"hrv": 30, "rhr": 60, "sleep_min": 340}, prior)
        self.assertEqual(status, "easy")
        self.assertIn("HRV 30", note)
        self.assertIn("5h 40m", note)

    def test_readiness_unknown_before_sleep_syncs(self):
        self.assertEqual(coros.readiness({"rhr": 60}, [{"hrv": 40}] * 5)[0], "unknown")

    def test_readiness_waits_for_baseline(self):
        self.assertEqual(coros.readiness({"hrv": 30, "sleep_min": 420}, [{"hrv": 40}])[0], "baseline")

    def test_grade_easy_run(self):
        workout = {"duration_min": 50, "zone_max": 2}
        verdict, note = coros.grade(workout, RUN, ZONES)
        self.assertEqual(verdict, "Off target")
        self.assertEqual(note, "103% of planned time, 44% at or under zone 2 heart rate")


class Build(unittest.TestCase):
    def run_build(self, tmp):
        coros.DATA, coros.OUT = tmp / "data", tmp / "out"
        with redirect_stdout(StringIO()) as out:
            coros.build(date(2026, 10, 25))
        return json.loads(out.getvalue()), {p.name: p.read_text() for p in coros.OUT.glob("*.json")}

    def test_build_is_repeatable_and_reports_due_work(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            (tmp / "data").mkdir()
            (tmp / "data/activities.json").write_text(json.dumps({"r1": RUN}))
            (tmp / "data/days.json").write_text(json.dumps({"2026-10-24": {"date": "2026-10-24", "hrv": 24}}))
            (tmp / "data/zones.json").write_text(json.dumps({"zone_max": ZONES}))
            status, first = self.run_build(tmp)
            _, second = self.run_build(tmp)
            self.assertEqual(first, second)
            # Sunday closes the week, so its report and next week's plan are due.
            self.assertEqual(status["report_due"], ["2026-10-19"])
            self.assertEqual(status["plan_due"], "2026-10-26")
            self.assertEqual(status["plan_phase"], "baseline")


if __name__ == "__main__":
    unittest.main()
