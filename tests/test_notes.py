from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config import Settings
from core.assistant import AssistantEngine
from core.notes import NotesService
from core.store import Store


class NotesBehaviorTest(unittest.TestCase):
    def _build_settings(self, root: Path) -> Settings:
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
            pomodoro_settings_path=root / "missing-settings.json",
        )

    def test_save_to_category_forces_note_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            engine = AssistantEngine(self._build_settings(root))

            # an action-type thought opens a collecting session (a clear 随想 would
            # finalize on the first turn), so 「保存到X」 has a session to attach to
            first = engine.handle_message("我想做一个功能，把每天记录的想法自动按主题归类", session_id="note")
            second = engine.handle_message("保存到AI碎碎念", session_id="note")

            self.assertIn("先一起把这个想法理清", first)
            self.assertIn("分类：AI碎碎念", second)

            store = Store(self._build_settings(root))
            note = store.list_notes(limit=1)[0]
            self.assertEqual(note["category"], "AI碎碎念")
            self.assertIn("/AI碎碎念/", note["file_path"])

    def test_update_note_category_moves_file_and_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = self._build_settings(root)
            store = Store(settings)

            path = store.add_note(
                {
                    "title": "布局提示",
                    "category": "生活感悟",
                    "tags": ["AI对话"],
                    "markdown": (
                        "---\n"
                        "title: 布局提示\n"
                        "category: 生活感悟\n"
                        "tags: [AI对话]\n"
                        "type: 生活随想/情绪\n"
                        "created: 2026-06-09\n"
                        "---\n\n"
                        "## 一句话\n"
                        "描述要更具体。\n"
                    ),
                }
            )
            note_id = store.list_notes(limit=1)[0]["id"]

            new_path = store.update_note_category(note_id, "AI碎碎念")
            updated = store.get_note_by_id(note_id)

            self.assertFalse(path.exists())
            self.assertTrue(new_path.exists())
            self.assertEqual(updated["category"], "AI碎碎念")
            self.assertIn("/AI碎碎念/", updated["file_path"])
            self.assertIn("category: AI碎碎念", updated["content"])

    def test_free_form_type_is_normalized_to_stable_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = self._build_settings(root)
            service = NotesService(Store(settings), settings)

            note = service._normalize_note(
                {
                    "type": "读书笔记",
                    "title": "把时间当作朋友",
                    "is_book_note": False,
                    "book": "",
                    "category": "学习",
                    "category_is_new": False,
                    "tags": ["阅读"],
                    "one_liner": "长期主义更重要。",
                    "background": "今天读到一段话。",
                    "summary": "书里提到要把目光放长远。",
                    "next_steps": [],
                    "challenge": "",
                    "related_hints": [],
                }
            )

            self.assertEqual(note["type"], "来源")

    def test_book_frontmatter_uses_stable_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = self._build_settings(root)
            service = NotesService(Store(settings), settings)

            frontmatter = service._book_frontmatter(
                {
                    "title": "把时间当作朋友",
                    "category": "学习",
                    "tags": ["阅读"],
                    "type": "来源",
                }
            )

            self.assertIn("type: 来源", frontmatter)


class TrashEditUndoTest(unittest.TestCase):
    def _build_settings(self, root: Path) -> Settings:
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
            pomodoro_settings_path=root / "missing-settings.json",
        )

    def _add_note(self, store: Store, title: str, category: str = "生活感悟") -> int:
        store.add_note(
            {
                "title": title,
                "category": category,
                "tags": ["示例"],
                "markdown": (
                    f"---\ntitle: {title}\ncategory: {category}\ntags: [示例]\n"
                    f"type: 随想\ncreated: 2026-06-10\n---\n\n# {title}\n\n正文内容。\n"
                ),
            }
        )
        return store.list_notes(limit=1)[0]["id"]

    def test_trash_restore_purge_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(self._build_settings(Path(tmpdir)))
            note_id = self._add_note(store, "会被删的想法")
            self.assertEqual(len(store.list_notes()), 1)

            store.trash_note(note_id)
            self.assertEqual(len(store.list_notes()), 0)  # hidden from hot path
            self.assertEqual(len(store.search_notes(query="会被删")), 0)
            trash = store.list_trashed_notes()
            self.assertEqual(len(trash), 1)
            self.assertEqual(trash[0]["days_left"], 30)
            self.assertIn("/.trash/", store.get_note_by_id(note_id)["file_path"])

            new_path = store.restore_note(note_id)
            self.assertTrue(new_path.exists())
            self.assertEqual(len(store.list_notes()), 1)
            self.assertEqual(len(store.list_trashed_notes()), 0)
            self.assertIn("/生活感悟/", str(new_path))

            store.trash_note(note_id)
            store.purge_note(note_id)
            self.assertIsNone(store.get_note_by_id(note_id))
            self.assertEqual(len(store.list_trashed_notes()), 0)

    def test_empty_and_expire_trash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(self._build_settings(Path(tmpdir)))
            a = self._add_note(store, "想法甲")
            b = self._add_note(store, "想法乙")
            store.trash_note(a)
            store.trash_note(b)
            self.assertEqual(store.empty_trash(), 2)
            self.assertEqual(len(store.list_trashed_notes()), 0)

            c = self._add_note(store, "想法丙")
            store.trash_note(c)
            with store._connect() as conn:  # age it past retention
                conn.execute(
                    "UPDATE notes SET deleted_at = '2000-01-01T00:00:00' WHERE id = ?", (c,)
                )
            self.assertEqual(store.purge_expired_trash(30), 1)
            self.assertIsNone(store.get_note_by_id(c))

    def test_update_note_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(self._build_settings(Path(tmpdir)))
            note_id = self._add_note(store, "旧标题", category="工作")
            store.update_note_content(note_id, "新标题", "# 新标题\n\n改过的正文。")
            updated = store.get_note_by_id(note_id)
            self.assertEqual(updated["title"], "新标题")
            self.assertEqual(updated["category"], "工作")  # unchanged
            self.assertIn("title: 新标题", updated["content"])
            self.assertIn("改过的正文", updated["content"])
            self.assertNotIn("正文内容", updated["content"])

    def test_delete_last_exercise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(self._build_settings(Path(tmpdir)))
            self.assertIsNone(store.delete_last_exercise())
            store.add_exercise_session(
                {"activity": "跑步", "duration_minutes": 30, "distance_km": 5.0, "calories": None},
                raw_text="跑步5公里30分钟",
                ts="2026-06-10",
            )
            removed = store.delete_last_exercise(within_seconds=900)
            self.assertIsNotNone(removed)
            self.assertEqual(removed["activity"], "跑步")
            self.assertIsNone(store.delete_last_exercise())

    def test_cancel_guard_requires_active_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = self._build_settings(Path(tmpdir))
            service = NotesService(Store(settings), settings)
            # no active session -> skip words must not trigger a cancel message
            self.assertIsNone(service.cancel_if_needed("s1", "跳过"))
            # active session -> cancel works
            service.store.save_note_session("s1", status="collecting", messages=[{"role": "user", "content": "一个想法"}])
            self.assertIsNotNone(service.cancel_if_needed("s1", "不记录"))
            self.assertFalse(service.has_active_session("s1"))

    def test_cancel_only_on_standalone_phrase_not_buried_word(self) -> None:
        # F3: a cancel word inside a real thought must NOT abort the in-progress note
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = self._build_settings(Path(tmpdir))
            service = NotesService(Store(settings), settings)
            service.store.save_note_session("s2", status="collecting", messages=[{"role": "user", "content": "想法"}])
            self.assertIsNone(service.cancel_if_needed("s2", "我打算先跳过登录这一块"))
            self.assertIsNone(service.cancel_if_needed("s2", "这事算了的话也行，但我想先验证"))
            self.assertTrue(service.has_active_session("s2"))  # still collecting
            self.assertIsNotNone(service.cancel_if_needed("s2", "跳过"))  # standalone -> cancels

    def test_source_reliability_and_medium_neutral_label(self) -> None:
        # P2: a 来源 note with a named source merges even if the model forgot the flag,
        # and a podcast/article is NOT mislabelled 读书笔记
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = self._build_settings(Path(tmpdir))
            service = NotesService(Store(settings), settings)
            n = service._normalize_note({
                "type": "来源", "title": "某播客", "is_book_note": False,
                "book": "某播客", "source_type": "播客", "summary": "我的看法", "category": "学习",
            })
            self.assertTrue(n["is_book_note"])
            self.assertEqual(n["source_type"], "播客")
            self.assertEqual(service._source_label("播客"), "播客笔记")
            self.assertEqual(service._source_label("文章"), "文章摘记")
            self.assertEqual(service._source_label("书"), "读书笔记")
            self.assertEqual(service._source_label(""), "来源笔记")


if __name__ == "__main__":
    unittest.main()
