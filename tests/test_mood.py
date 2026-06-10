"""Tests for emotion (mood) recording, routing and dashboard aggregation.

    python -m unittest tests.test_mood
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
from core.assistant import AssistantEngine
from core.mood import (
    MOOD_PICKER_PROMPT,
    MOOD_PROMPT,
    is_confident_mood,
    looks_like_mood,
    parse_mood,
)
from core.router import classify_intent
from core.store import Store

WEEKS = 12


def _engine() -> AssistantEngine:
    return AssistantEngine(load_settings(data_dir_override=tempfile.mkdtemp(prefix="mood_test_")))


def _store() -> Store:
    return Store(load_settings(data_dir_override=tempfile.mkdtemp(prefix="mood_test_")))


class MoodParsingTest(unittest.TestCase):
    def test_canonical_and_marker_and_custom(self):
        self.assertEqual(parse_mood("今天好焦虑"), {"emotion": "焦虑", "note": ""})
        self.assertEqual(parse_mood("心情 平静"), {"emotion": "平静", "note": ""})
        custom = parse_mood("心情：累成狗")
        self.assertEqual(custom["emotion"], "自定义")
        self.assertIn("累", custom["note"])
        self.assertIsNone(parse_mood("跑步30分钟"))

    def test_longer_mood_sentence_keeps_note(self):
        parsed = parse_mood("今天因为开会的事情难过了一天")
        self.assertEqual(parsed["emotion"], "难过")
        self.assertIn("开会", parsed["note"])

        unhappy = parse_mood("今天不开心")
        self.assertEqual(unhappy["emotion"], "难过")

        complex_mood = parse_mood("今天心情复杂")
        self.assertEqual(complex_mood["emotion"], "很难描述")

    def test_router_classifies_mood(self):
        self.assertEqual(classify_intent("今天有点焦虑", llm=None), "mood")
        self.assertEqual(classify_intent("心情不好", llm=None), "mood")
        self.assertEqual(classify_intent("情绪 平静", llm=None), "mood")
        self.assertEqual(classify_intent("今天因为项目的事情焦虑了一天", llm=None), "mood")
        self.assertEqual(classify_intent("记录情绪", llm=None), "mood")
        # a fuller reflection stays a note, not a one-line mood
        self.assertEqual(classify_intent("我突然觉得专注靠环境而不是意志力", llm=None), "note")
        self.assertTrue(looks_like_mood("开心"))

    def test_confident_mood_gating(self):
        # high-confidence shortcuts
        self.assertTrue(is_confident_mood("焦虑"))
        self.assertTrue(is_confident_mood("今天有点焦虑"))
        self.assertTrue(is_confident_mood("记录情绪"))
        # an idea that merely mentions an emotion must NOT short-circuit to mood
        self.assertFalse(is_confident_mood("我想把情绪卡做成月历模式"))
        # a longer event-triggered feeling defers to the LLM classifier, not the shortcut
        self.assertFalse(is_confident_mood("想到那件事就有点恐惧"))


class MoodStoreTest(unittest.TestCase):
    def test_one_per_day_overwrites(self):
        store = _store()
        store.add_mood("焦虑", source="manual")
        store.add_mood("平静", source="manual")  # same day -> overwrite
        today = store.get_today_mood()
        self.assertEqual(today["emotion"], "平静")
        dist = store.get_mood_distribution()
        self.assertEqual(sum(r["count"] for r in dist), 1)

    def test_heatmap_rolling_colors_and_future(self):
        store = _store()
        today = date.today()
        store.add_mood("开心", day=today.isoformat())
        store.add_mood("难过", day=(today - timedelta(days=3)).isoformat())
        grid = store.get_mood_heatmap_rolling(WEEKS)
        self.assertEqual(len(grid), WEEKS)
        self.assertTrue(all(len(col) == 7 for col in grid))
        cells = {c["date"]: c for col in grid for c in col}
        self.assertEqual(cells[today.isoformat()]["emotion"], "开心")
        self.assertTrue(cells[today.isoformat()]["color"].startswith("#"))
        # a day with no mood has no color; future days flagged
        blank = cells[(today - timedelta(days=1)).isoformat()]
        self.assertIsNone(blank["color"])
        tomorrow = (today + timedelta(days=1)).isoformat()
        if tomorrow in cells:
            self.assertTrue(cells[tomorrow]["is_future"])

    def test_window_stats(self):
        store = _store()
        today = date.today()
        store.add_mood("开心", day=today.isoformat())
        store.add_mood("平静", day=(today - timedelta(days=1)).isoformat())
        store.add_mood("焦虑", day=(today - timedelta(days=2)).isoformat())
        stats = store.get_mood_window_stats(WEEKS)
        self.assertEqual(stats["logged_days"], 3)
        self.assertIn(stats["top_emotion"], {"开心", "平静", "焦虑"})
        self.assertAlmostEqual(stats["positive_ratio"], 2 / 3, places=3)  # 开心+平静 = 积极

    def test_month_calendar_contains_notes_and_padding(self):
        store = _store()
        target = date(2026, 6, 1)
        store.add_mood("开心", note="上午挺轻松", day="2026-06-08")
        store.add_mood("焦虑", day="2026-06-09")

        calendar = store.get_mood_calendar_month(target)
        self.assertEqual(calendar["month"], "2026-06")
        self.assertIn(len(calendar["weeks"]), {5, 6})
        self.assertTrue(all(len(week) == 7 for week in calendar["weeks"]))
        self.assertEqual(calendar["logged_days"], 2)
        self.assertEqual(calendar["noted_days"], 1)
        self.assertIn(calendar["top_emotion"], {"开心", "焦虑"})
        self.assertEqual(len(calendar["distribution"]), 2)
        self.assertEqual(calendar["distribution"][0]["count"], 1)
        self.assertIn("ratio", calendar["distribution"][0])

        cells = {cell["date"]: cell for week in calendar["weeks"] for cell in week}
        self.assertEqual(cells["2026-06-08"]["emotion"], "开心")
        self.assertEqual(cells["2026-06-08"]["note"], "上午挺轻松")
        self.assertTrue(cells["2026-06-08"]["has_note"])
        self.assertTrue(cells["2026-06-08"]["color"].startswith("#"))
        self.assertFalse(cells["2026-05-31"]["in_month"])

    def test_available_months_include_mood_only_data(self):
        store = _store()
        store.add_mood("平静", day="2026-01-15")
        self.assertIn("2026-01", store.get_available_months())


class MoodAssistantFlowTest(unittest.TestCase):
    def test_record_then_prompt_then_capture_then_silent(self):
        eng = _engine()
        # first successful exercise of the day -> reply carries the mood prompt
        reply = eng.handle_message("跑步 5公里 30分钟", "s1")
        self.assertIn("已记录运动", reply)
        self.assertIn(MOOD_PROMPT, reply)
        # the next short reply is captured as today's mood
        captured = eng.handle_message("焦虑", "s1")
        self.assertIn("记下了今天的心情：焦虑", captured)
        self.assertEqual(eng.store.get_today_mood()["emotion"], "焦虑")
        # a second record same day: mood already logged -> no prompt appended
        again = eng.handle_message("骑行 20分钟", "s1")
        self.assertIn("已记录运动", again)
        self.assertNotIn(MOOD_PROMPT, again)

    def test_active_mood_record(self):
        eng = _engine()
        reply = eng.handle_message("情绪 平静", "s2")
        self.assertIn("记下了今天的心情：平静", reply)
        self.assertEqual(eng.store.get_today_mood()["emotion"], "平静")

    def test_active_mood_picker_flow(self):
        eng = _engine()
        prompt = eng.handle_message("记录情绪", "s3")
        self.assertIn(MOOD_PICKER_PROMPT, prompt)

        picked = eng.handle_message("3", "s3")
        self.assertIn("记下了今天的心情：焦虑", picked)
        self.assertEqual(eng.store.get_today_mood()["emotion"], "焦虑")

    def test_mood_sentence_does_not_become_note(self):
        eng = _engine()
        reply = eng.handle_message("今天因为开会的事情难过了一天", "s4")
        today = eng.store.get_today_mood()
        self.assertIsNotNone(today)
        self.assertEqual(today["emotion"], "难过")
        self.assertIn("开会", today["note"])
        self.assertIn("记下了今天的心情：难过", reply)


if __name__ == "__main__":
    unittest.main()
