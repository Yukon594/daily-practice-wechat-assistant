from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from config import Settings
from core.assistant import AssistantEngine


class AssistantEnginePivotTest(unittest.TestCase):
    def _build_settings(self, root: Path, pomodoro_settings_path: Path) -> Settings:
        data_dir = root / "data"
        notes_dir = data_dir / "notes"
        data_dir.mkdir(parents=True, exist_ok=True)
        notes_dir.mkdir(parents=True, exist_ok=True)
        return Settings(
            deepseek_api_key="",
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="deepseek-chat",
            request_timeout=30,
            dashboard_port=9900,
            note_categories=["产品灵感", "生活感悟", "工作", "学习", "其它"],
            data_dir=data_dir,
            db_path=data_dir / "assistant.db",
            notes_dir=notes_dir,
            pomodoro_settings_path=pomodoro_settings_path,
        )

    def test_records_exercise_and_answers_focus_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pomodoro_settings_path = root / "pomodoro-settings.json"
            pomodoro_settings_path.write_text(
                json.dumps(
                    {
                        "forestStats": {
                            "days": {
                                "2026-06-08": {
                                    "focusSeconds": 5400,
                                    "treesCompleted": 3,
                                    "projects": {},
                                }
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            engine = AssistantEngine(self._build_settings(root, pomodoro_settings_path))

            exercise_reply = engine.handle_message("今天跑步5公里 32分钟", session_id="test")
            focus_reply = engine.handle_message("看看这个月专注了多久", session_id="test")

            self.assertIn("已记录", exercise_reply)
            self.assertIn("跑步", exercise_reply)
            self.assertIn("本月专注", focus_reply)
            self.assertIn("1小时30分钟", focus_reply)

    def test_records_ambiguous_exercise_via_llm_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pomodoro_settings_path = root / "pomodoro-settings.json"
            settings = self._build_settings(root, pomodoro_settings_path)
            settings.deepseek_api_key = "test-key"
            engine = AssistantEngine(settings)

            def fake_chat(messages, json_mode=False, temperature=0.2, max_tokens=800):
                system = messages[0]["content"]
                if "意图分类器" in system:
                    return {"intent": "exercise"}
                if "运动记录解析器" in system:
                    return {
                        "session": {
                            "ts": "2026-06-10",
                            "activity": "力量训练",
                            "duration_minutes": 30,
                            "distance_km": None,
                            "calories": None,
                        }
                    }
                raise AssertionError(f"unexpected prompt: {system}")

            with patch.object(engine.llm, "chat", side_effect=fake_chat):
                reply = engine.handle_message("今天练了个上肢，差不多半小时", session_id="test")

            self.assertIn("已记录运动", reply)
            self.assertIn("力量训练", reply)
            summary = engine.store.get_exercise_month_summary(date(2026, 6, 10))
            self.assertEqual(summary["count"], 1)
            self.assertEqual(summary["total_duration_minutes"], 30)

    def test_focus_query_reports_missing_sync_file_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            engine = AssistantEngine(self._build_settings(root, root / "missing-settings.json"))

            reply = engine.handle_message("看看这个月专注了多久", session_id="test")

            self.assertIn("番茄钟同步失败", reply)
            self.assertIn("missing-settings.json", reply)

    def test_focus_query_distinguishes_synced_history_from_current_month_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pomodoro_settings_path = root / "pomodoro-settings.json"
            pomodoro_settings_path.write_text(
                json.dumps(
                    {
                        "forestStats": {
                            "days": {
                                "2026-05-20": {
                                    "focusSeconds": 1800,
                                    "treesCompleted": 1,
                                    "projects": {},
                                }
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            engine = AssistantEngine(self._build_settings(root, pomodoro_settings_path))

            reply = engine.handle_message("看看这个月专注了多久", session_id="test")

            self.assertIn("本月暂时没有专注记录", reply)
            self.assertIn("2026-05-20", reply)

    def test_focus_query_uses_auto_detected_fresh_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app_support = root / "Library" / "Application Support"
            stale = app_support / "com.liuyuhang.stickerpomodoro.mac" / "settings.json"
            fresh = app_support / "com.stickerpomodoro.timer" / "settings.json"
            stale.parent.mkdir(parents=True, exist_ok=True)
            fresh.parent.mkdir(parents=True, exist_ok=True)
            stale.write_text(
                json.dumps(
                    {"forestStats": {"days": {"2026-05-20": {"focusSeconds": 600, "treesCompleted": 1, "projects": {}}}}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            fresh.write_text(
                json.dumps(
                    {"forestStats": {"days": {"2026-06-08": {"focusSeconds": 3600, "treesCompleted": 2, "projects": {}}}}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            engine = AssistantEngine(self._build_settings(root, stale))

            with patch("core.assistant.date") as fake_date:
                fake_date.today.return_value = date(2026, 6, 9)
                reply = engine.handle_message("看看这个月专注了多久", session_id="test")

            self.assertIn("本月专注 1小时", reply)


if __name__ == "__main__":
    unittest.main()
