"""Regression tests for the rolling-window dashboard helpers.

    python -m unittest tests.test_dashboard_data
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core.store import Store

WEEKS = 12


class RollingDashboardTest(unittest.TestCase):
    def _fresh_store(self) -> Store:
        return Store(load_settings(data_dir_override=tempfile.mkdtemp(prefix="dash_test_")))

    def _seed(self, store: Store) -> date:
        today = date.today()
        # (days_ago, activity, minutes, distance_km)
        for off, activity, minutes, km in [
            (0, "跑步", 30, 5.0),
            (1, "健身", 40, None),
            (10, "骑行", 50, 15.0),
            (30, "瑜伽", 35, None),
        ]:
            d = today - timedelta(days=off)
            store.add_exercise_session(
                {"activity": activity, "duration_minutes": minutes, "distance_km": km, "calories": None, "source": "t"},
                raw_text="x",
                ts=d.isoformat(),
            )
        store.replace_focus_days(
            [{"day": today.isoformat(), "focus_seconds": 3000, "trees_completed": 2, "projects": {}}],
            source_path="/x",
        )
        return today

    def test_heatmap_is_rolling_and_ends_today(self):
        store = self._fresh_store()
        today = self._seed(store)
        grid = store.get_exercise_heatmap_rolling(WEEKS)

        self.assertEqual(len(grid), WEEKS)
        self.assertTrue(all(len(col) == 7 for col in grid))

        cells = {c["date"]: c for col in grid for c in col}
        today_iso = today.isoformat()
        self.assertIn(today_iso, cells)
        self.assertFalse(cells[today_iso]["is_future"])
        self.assertEqual(cells[today_iso]["value"], 30)

        tomorrow = (today + timedelta(days=1)).isoformat()
        if tomorrow in cells:
            self.assertTrue(cells[tomorrow]["is_future"], "days after today must be flagged future")

        expected_start = today - timedelta(days=today.weekday()) - timedelta(days=(WEEKS - 1) * 7)
        self.assertEqual(min(cells), expected_start.isoformat())

    def test_window_stats_distance_and_active_days(self):
        store = self._fresh_store()
        self._seed(store)
        win = store.get_exercise_window_stats(WEEKS)
        self.assertEqual(win["active_days"], 4)
        self.assertEqual(win["total_distance_km"], 20.0)  # 5 + 15, ignores distance-less sessions
        self.assertIn(win["top_activity"], {"跑步", "健身", "骑行", "瑜伽"})

        focus = store.get_focus_window_stats(WEEKS)
        self.assertEqual(focus["days_with_focus"], 1)
        self.assertEqual(focus["total_trees"], 2)

    def test_month_summary_exposes_active_days(self):
        store = self._fresh_store()
        today = self._seed(store)
        summary = store.get_exercise_month_summary(today)
        self.assertIn("active_days", summary)
        self.assertGreaterEqual(summary["active_days"], 1)

    def test_zero_distance_window_reports_zero_km(self):
        store = self._fresh_store()
        today = date.today()
        store.add_exercise_session(
            {"activity": "健身", "duration_minutes": 45, "distance_km": None, "calories": None, "source": "t"},
            raw_text="x",
            ts=today.isoformat(),
        )
        win = store.get_exercise_window_stats(WEEKS)
        self.assertEqual(win["total_distance_km"], 0.0)  # front-end then hides 里程
        self.assertEqual(win["active_days"], 1)


if __name__ == "__main__":
    unittest.main()
