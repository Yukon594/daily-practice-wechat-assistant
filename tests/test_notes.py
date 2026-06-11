from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config import Settings
from core.assistant import AssistantEngine
from core.notes import (
    NotesService,
    _extract_own_title,
    _parse_category_directive,
    _strip_capture_marker,
)
from core.store import Store


def _settings(root: Path) -> Settings:
    data_dir = root / "data"
    notes_dir = data_dir / "notes"
    data_dir.mkdir(parents=True, exist_ok=True)
    notes_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        deepseek_api_key="",  # offline: capture uses the rule fallback
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


def _add_note(store: Store, title: str, category: str = "生活感悟") -> int:
    store.add_note(
        {
            "title": title,
            "category": category,
            "tags": ["示例"],
            "markdown": (
                f"---\ntitle: {title}\ncategory: {category}\ntags: [示例]\n"
                f"created: 2026-06-10\n---\n\n{title} 的正文内容。\n"
            ),
        }
    )
    return store.list_notes(limit=1)[0]["id"]


class CaptureTest(unittest.TestCase):
    def test_one_shot_capture_stores_body_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = _settings(Path(tmpdir))
            store = Store(settings)
            service = NotesService(store, settings)  # no llm -> fallback meta
            body = "我想做一个自己喜欢的pdf浏览器，支持转格式、加文字、贴纸、一键转录"
            reply = service.capture(body)

            self.assertIn("已经记下来了", reply)
            notes = store.list_notes()
            self.assertEqual(len(notes), 1)
            self.assertTrue(notes[0]["title"])
            self.assertTrue(notes[0]["category"])
            content = store.get_note_by_id(notes[0]["id"])["content"]
            self.assertIn(body, content)  # the thought is stored faithfully

    def test_note_intent_captures_in_one_shot_no_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = AssistantEngine(_settings(Path(tmpdir)))
            reply = engine.handle_message("随手记一个想法：把番茄钟数据同步到看板会很有用", "wx")
            self.assertIn("已经记下来了", reply)
            self.assertEqual(len(engine.store.list_notes()), 1)


class DirectiveAndTitleTest(unittest.TestCase):
    def test_category_directive_parsing(self) -> None:
        self.assertEqual(_parse_category_directive("记录到ai碎碎念：对话很慢"), ("ai碎碎念", "对话很慢"))
        self.assertEqual(_parse_category_directive("记到工作 今天加薪"), ("工作", "今天加薪"))
        self.assertEqual(_parse_category_directive("归到生活感悟，很有感触"), ("生活感悟", "很有感触"))
        self.assertEqual(_parse_category_directive("/ai碎碎念 对话很慢"), ("ai碎碎念", "对话很慢"))
        # a path must NOT be mistaken for a category
        self.assertEqual(_parse_category_directive("/Users/liu/x 这是路径")[0], None)
        self.assertEqual(_parse_category_directive("普通想法没有指令")[0], None)

    def test_capture_marker_stripped(self) -> None:
        self.assertEqual(_strip_capture_marker("记一个想法：试试早起"), "试试早起")
        self.assertEqual(_strip_capture_marker("想法：买牛奶"), "买牛奶")
        self.assertEqual(_strip_capture_marker("记下班路上的点子"), "记下班路上的点子")  # no false strip

    def test_own_title_extraction(self) -> None:
        self.assertEqual(_extract_own_title("# 工作复盘\n今天加薪")[0], "工作复盘")  # heading kept in body
        self.assertEqual(_extract_own_title("## 早起实验\n第一天")[0], "早起实验")
        title, body = _extract_own_title("标题：早起实验\n第一天")
        self.assertEqual(title, "早起实验")
        self.assertNotIn("标题：", body)  # label line dropped
        self.assertIsNone(_extract_own_title("没有标题的第一行")[0])

    def test_capture_honours_directive_and_own_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = _settings(Path(tmpdir))
            store = Store(settings)
            service = NotesService(store, settings)  # offline
            reply = service.capture("记录到AI碎碎念：# 对话延迟\n对话是最慢最脆的一块")
            self.assertIn("分类：AI碎碎念", reply)
            self.assertIn("（新分类）", reply)
            note = store.list_notes()[0]
            self.assertEqual(note["title"], "对话延迟")  # own title, not AI-generated
            content = store.get_note_by_id(note["id"])["content"]
            self.assertNotIn("记录到AI碎碎念", content)  # directive stripped from body
            self.assertIn("对话是最慢最脆的一块", content)


class NoteUndoTest(unittest.TestCase):
    def test_store_delete_last_note_trashes_recent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(_settings(Path(tmpdir)))
            self.assertIsNone(store.delete_last_note())
            nid = _add_note(store, "会被撤销的想法")
            removed = store.delete_last_note(within_seconds=900)
            self.assertIsNotNone(removed)
            self.assertEqual(removed["title"], "会被撤销的想法")
            self.assertEqual(len(store.list_notes()), 0)
            self.assertEqual(len(store.list_trashed_notes()), 1)  # recoverable
            self.assertIsNone(store.delete_last_note())

    def test_undo_note_via_chat(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = AssistantEngine(_settings(Path(tmpdir)))
            engine.handle_message("记个想法：周末去爬山", "wx")
            self.assertEqual(len(engine.store.list_notes()), 1)
            undo = engine.handle_message("撤销刚才的想法", "wx")
            self.assertIn("已撤销刚才的想法", undo)
            self.assertEqual(len(engine.store.list_notes()), 0)
            self.assertEqual(len(engine.store.list_trashed_notes()), 1)

    def test_bare_undo_picks_most_recent_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = AssistantEngine(_settings(Path(tmpdir)))
            engine.handle_message("今天跑步5公里 32分钟", "wx")   # exercise first
            engine.handle_message("记个想法：试试新的早起习惯", "wx")  # note is newer
            undo = engine.handle_message("撤销", "wx")  # bare -> undo the newer one (the note)
            self.assertIn("已撤销刚才的想法", undo)
            self.assertEqual(len(engine.store.list_notes()), 0)
            self.assertEqual(len(engine.store.list_recent_exercise_sessions()), 1)  # exercise kept


class TrashEditTest(unittest.TestCase):
    def test_update_note_category_moves_file_and_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(_settings(Path(tmpdir)))
            nid = _add_note(store, "布局提示", category="生活感悟")
            new_path = store.update_note_category(nid, "AI碎碎念")
            updated = store.get_note_by_id(nid)
            self.assertTrue(new_path.exists())
            self.assertEqual(updated["category"], "AI碎碎念")
            self.assertIn("/AI碎碎念/", updated["file_path"])
            self.assertIn("category: AI碎碎念", updated["content"])

    def test_trash_restore_purge_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(_settings(Path(tmpdir)))
            nid = _add_note(store, "会被删的想法")
            store.trash_note(nid)
            self.assertEqual(len(store.list_notes()), 0)
            self.assertEqual(len(store.search_notes(query="会被删")), 0)
            trash = store.list_trashed_notes()
            self.assertEqual(len(trash), 1)
            self.assertEqual(trash[0]["days_left"], 30)

            new_path = store.restore_note(nid)
            self.assertTrue(new_path.exists())
            self.assertEqual(len(store.list_notes()), 1)
            self.assertIn("/生活感悟/", str(new_path))

            store.trash_note(nid)
            store.purge_note(nid)
            self.assertIsNone(store.get_note_by_id(nid))

    def test_empty_and_expire_trash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(_settings(Path(tmpdir)))
            store.trash_note(_add_note(store, "想法甲"))
            store.trash_note(_add_note(store, "想法乙"))
            self.assertEqual(store.empty_trash(), 2)

            c = _add_note(store, "想法丙")
            store.trash_note(c)
            with store._connect() as conn:
                conn.execute("UPDATE notes SET deleted_at = '2000-01-01T00:00:00' WHERE id = ?", (c,))
            self.assertEqual(store.purge_expired_trash(30), 1)
            self.assertIsNone(store.get_note_by_id(c))

    def test_update_note_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(_settings(Path(tmpdir)))
            nid = _add_note(store, "旧标题", category="工作")
            store.update_note_content(nid, "新标题", "改过的正文。")
            updated = store.get_note_by_id(nid)
            self.assertEqual(updated["title"], "新标题")
            self.assertEqual(updated["category"], "工作")
            self.assertIn("title: 新标题", updated["content"])
            self.assertIn("改过的正文", updated["content"])

    def test_delete_last_exercise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(_settings(Path(tmpdir)))
            self.assertIsNone(store.delete_last_exercise())
            store.add_exercise_session(
                {"activity": "跑步", "duration_minutes": 30, "distance_km": 5.0, "calories": None},
                raw_text="跑步5公里30分钟", ts="2026-06-10",
            )
            removed = store.delete_last_exercise(within_seconds=900)
            self.assertEqual(removed["activity"], "跑步")
            self.assertIsNone(store.delete_last_exercise())


if __name__ == "__main__":
    unittest.main()
