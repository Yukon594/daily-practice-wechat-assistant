from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from config import Settings
from core.focus import PomodoroSyncService
from core.store import Store


class FocusSyncTest(unittest.TestCase):
    def _build_settings(self, root: Path, settings_path: Path) -> Settings:
        settings = Settings(
            deepseek_api_key="",
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="deepseek-chat",
            request_timeout=30,
            dashboard_port=9900,
            note_categories=["产品灵感", "生活感悟", "工作", "学习", "其它"],
            data_dir=root / "data",
            db_path=root / "data" / "assistant.db",
            notes_dir=root / "data" / "notes",
            pomodoro_settings_path=settings_path,
        )
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.notes_dir.mkdir(parents=True, exist_ok=True)
        return settings

    def test_sync_imports_days_from_pomodoro_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings_path = root / "pomodoro-settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "forestStats": {
                            "days": {
                                "2026-06-08": {
                                    "focusSeconds": 3600,
                                    "treesCompleted": 2,
                                    "projects": {
                                        "writing": {
                                            "focusSeconds": 2400,
                                            "treesCompleted": 1,
                                        }
                                    },
                                }
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            settings = self._build_settings(root, settings_path)
            store = Store(settings)

            result = PomodoroSyncService(store, settings).sync()
            summary = store.get_focus_month_summary(2026, 6)

            self.assertTrue(result.ok)
            self.assertEqual(result.imported_days, 1)
            self.assertEqual(summary["total_focus_seconds"], 3600)
            self.assertEqual(summary["total_trees"], 2)
            self.assertEqual(summary["days_with_focus"], 1)

    def test_sync_replaces_old_snapshot_instead_of_accumulating(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings_path = root / "pomodoro-settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "forestStats": {
                            "days": {
                                "2026-06-08": {"focusSeconds": 1800, "treesCompleted": 1, "projects": {}},
                                "2026-06-09": {"focusSeconds": 1200, "treesCompleted": 1, "projects": {}},
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = self._build_settings(root, settings_path)
            store = Store(settings)
            sync = PomodoroSyncService(store, settings)

            first = sync.sync()
            settings_path.write_text(
                json.dumps(
                    {
                        "forestStats": {
                            "days": {
                                "2026-06-09": {"focusSeconds": 2400, "treesCompleted": 2, "projects": {}},
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            second = sync.sync()
            summary = store.get_focus_month_summary(2026, 6)

            self.assertTrue(first.ok)
            self.assertTrue(second.ok)
            self.assertEqual(summary["days_with_focus"], 1)
            self.assertEqual(summary["total_focus_seconds"], 2400)
            self.assertEqual(summary["total_trees"], 2)

    def test_sync_keeps_cached_data_when_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings_path = root / "pomodoro-settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "forestStats": {
                            "days": {
                                "2026-06-08": {"focusSeconds": 3600, "treesCompleted": 2, "projects": {}},
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = self._build_settings(root, settings_path)
            store = Store(settings)
            sync = PomodoroSyncService(store, settings)

            sync.sync()
            settings_path.unlink()
            result = sync.sync()
            summary = store.get_focus_month_summary(2026, 6)

            self.assertFalse(result.ok)
            self.assertTrue(result.used_cached_data)
            self.assertEqual(summary["total_focus_seconds"], 3600)

    def test_sync_reports_invalid_json_without_overwriting_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings_path = root / "pomodoro-settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "forestStats": {
                            "days": {
                                "2026-06-08": {"focusSeconds": 3600, "treesCompleted": 2, "projects": {}},
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = self._build_settings(root, settings_path)
            store = Store(settings)
            sync = PomodoroSyncService(store, settings)

            sync.sync()
            settings_path.write_text("{broken", encoding="utf-8")
            result = sync.sync()
            summary = store.get_focus_month_summary(2026, 6)

            self.assertFalse(result.ok)
            self.assertIn("格式异常", result.error)
            self.assertEqual(summary["total_focus_seconds"], 3600)

    def test_sync_prefers_the_freshest_active_candidate_under_same_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app_support = root / "Library" / "Application Support"
            stale = app_support / "com.stickerpomodoro.mac" / "settings.json"
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
            settings = self._build_settings(root, stale)
            store = Store(settings)

            result = PomodoroSyncService(store, settings).sync()
            summary = store.get_focus_month_summary(2026, 6)

            self.assertTrue(result.ok)
            self.assertIn("com.stickerpomodoro.timer", result.source_path)
            self.assertEqual(summary["total_focus_seconds"], 3600)

    def test_focus_project_breakdown_aggregates_project_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings_path = root / "pomodoro-settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "projects": [
                            {"id": "writing", "name": "写论文"},
                            {"id": "fitness", "name": "健身"},
                        ],
                        "forestStats": {
                            "days": {
                                "2026-06-08": {
                                    "focusSeconds": 3600,
                                    "treesCompleted": 2,
                                    "projects": {
                                        "writing": {"focusSeconds": 2400, "treesCompleted": 1},
                                        "fitness": {"focusSeconds": 1200, "treesCompleted": 1},
                                    },
                                }
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = self._build_settings(root, settings_path)
            store = Store(settings)

            PomodoroSyncService(store, settings).sync()
            rows = store.get_focus_project_breakdown(date(2026, 6, 1))

            self.assertEqual(rows[0]["project"], "写论文")
            self.assertEqual(rows[0]["focus_seconds"], 2400)
            self.assertEqual(rows[1]["project"], "健身")
            self.assertEqual(rows[1]["trees_completed"], 1)


if __name__ == "__main__":
    unittest.main()
