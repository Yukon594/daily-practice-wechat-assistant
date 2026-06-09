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

            first = engine.handle_message("我发现跟 AI 沟通视觉布局时，要把约束拆得更具体", session_id="note")
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


if __name__ == "__main__":
    unittest.main()
