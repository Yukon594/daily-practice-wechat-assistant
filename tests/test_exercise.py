from __future__ import annotations

import unittest
from unittest.mock import Mock

from core.exercise import looks_like_exercise_undo, parse_exercise


class ExerciseUndoDetectionTest(unittest.TestCase):
    def test_detects_explicit_and_recent_undo(self) -> None:
        self.assertTrue(looks_like_exercise_undo("删掉刚才的运动"))
        self.assertTrue(looks_like_exercise_undo("撤销运动"))
        self.assertTrue(looks_like_exercise_undo("去掉刚才那条跑步"))
        self.assertTrue(looks_like_exercise_undo("删除最近一条记录"))

    def test_ignores_non_undo_or_unrelated(self) -> None:
        self.assertFalse(looks_like_exercise_undo("今天跑步5公里"))
        self.assertFalse(looks_like_exercise_undo("删掉这个想法的标题"))  # no exercise/recency cue
        self.assertFalse(looks_like_exercise_undo("你好"))


class ExerciseParsingTest(unittest.TestCase):
    def test_parse_running_with_distance_and_duration(self) -> None:
        session = parse_exercise("今天跑步5公里 32分钟")

        self.assertEqual(session["activity"], "跑步")
        self.assertEqual(session["duration_minutes"], 32)
        self.assertEqual(session["distance_km"], 5.0)
        self.assertEqual(session["source"], "manual")

    def test_parse_strength_training_without_distance(self) -> None:
        session = parse_exercise("晚上练胸45分钟")

        self.assertEqual(session["activity"], "力量训练")
        self.assertEqual(session["duration_minutes"], 45)
        self.assertIsNone(session["distance_km"])

    def test_parse_with_llm_fallback_for_ambiguous_strength_text(self) -> None:
        llm = Mock()
        llm.is_configured = True
        llm.chat.return_value = {
            "session": {
                "ts": "2026-06-10",
                "activity": "力量训练",
                "duration_minutes": 30,
                "distance_km": None,
                "calories": None,
            }
        }

        session = parse_exercise("今天练了个上肢，差不多半小时", llm=llm)

        self.assertEqual(session["activity"], "力量训练")
        self.assertEqual(session["duration_minutes"], 30)
        self.assertEqual(session["ts"], "2026-06-10")
        self.assertEqual(session["source"], "manual")
        llm.chat.assert_called_once()


if __name__ == "__main__":
    unittest.main()
