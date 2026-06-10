from __future__ import annotations

import re
from datetime import date
from typing import Dict, List, Optional

from config import Settings
from core.llm import DeepSeekClient, LLMError
from core.store import Store

FINALIZE_RE = re.compile(r"(记下来|就这样|保存|先这样|可以了|收录|写下来)")
CANCEL_RE = re.compile(r"(取消|算了|先不记|结束这个想法)")
# a user turn that is *only* a control phrase shouldn't leak into the note body
BARE_TRIGGER_RE = re.compile(r"^(记下来|就这样吧?|保存|先这样|可以了|收录|写下来|好的?|嗯+)$")
FORCE_CATEGORY_RE = re.compile(r"^(?:保存到|记到|归档到|放到|收录到)\s*([^\s，。,！!？?]+?)(?:分类|里|里面)?$")

TYPE_ACTION = "行动"
TYPE_SOURCE = "来源"
TYPE_REFLECTION = "随想"
TYPE_REVIEW = "复盘"
TYPE_OTHER = "其它"
STABLE_TYPES = (TYPE_ACTION, TYPE_SOURCE, TYPE_REFLECTION, TYPE_REVIEW, TYPE_OTHER)

# ---------- prompts ----------
CONVERSE_SYSTEM = """\
你是「日迹」里的想法整理伙伴，中文、口语化、简洁。用户随手发来一个想法，你用尽量少的对话帮他理清，然后交给整理环节。

每轮只做一件事：先判断这条想法的「性质」，再据此决定「追问一个短问题」还是「已经够了，可以收」。注意——按性质来定策略，而不是按固定分类（用户有自己的、会不断增加的分类，别假设只有某几类）。常见性质与对应策略：

- 可执行/计划类（要做的事、方案、功能、改进）：可以深挖。优先问最关键的一点——要解决谁的什么问题 / 比现状好在哪 / 最站不住脚的假设是什么；可提一个挑战盲点的反问。最多追问 2~3 轮。
- 来自某个来源（书、文章、播客、课程…）：适度拓展但克制。务必问清并确认来源名称（书名/标题）——因为同一来源要并入同一条笔记；可问是哪个观点触发了你、你同意还是反对。
- 感受/观察/情绪/随想：最多问一个温和的小问题；若已说清楚，直接判定够了，不要硬聊。
- 其它/拿不准：问一个最能让想法具体起来的问题。

结束条件：信息足以整理成一条有价值的笔记，或用户说了「记下来/就这样/可以了」，或属于随想类且已说清。

只输出 JSON，不要任何多余文字：
{"type":"行动|来源|随想|复盘|其它","enough":true|false,"reply":"给用户看的一句话"}
其中 reply：enough=false 时是一个具体的短追问；enough=true 时是一句简短确认（如「这条挺清楚了，帮你整理成笔记？」）。reply ≤40 字，一次只问一个问题，口吻自然。
"""

BUILD_SYSTEM = """\
你是「日迹」的笔记整理器。把下面这段关于某个想法的对话整理成结构化笔记。中文，只输出 JSON。

核心原则——自适应：每个板块是否出现，取决于这条想法「本身的性质」，而不是它属于哪个分类（分类是用户自定义的、会不断增加，别把板块和某个具体分类名绑死）。逐项按下面的判断来定，空的就留空，不要硬凑：

- next_steps（可执行的下一步）：仅当这条想法是「要去做的事 / 计划 / 可推进的方案」时才给；纯感受、观察、情绪、纯记录就留空，别强行行动化。
- challenge（盲点/反问）：仅当其中有一个主张、决定或假设值得被质疑时，给一个挑战性反问；温和的随想可留空，或给一个温柔的反思问句。
- is_book_note / book：当这条想法来自某个具体来源（某本书/文章/播客/课程）时，is_book_note=true，book 填来源名称，title 也用该名称（便于同一来源并入同一条笔记）；summary 整理「要点/摘录 + 你的看法」。否则 is_book_note=false、book 留空。
- background（背景/触发点）：能还原「为什么会想到这件事」就给，通常有用。
- summary（核心内容）：始终给，忠实保留用户原话的关键句，不过度改写或拔高。
- one_liner（一句话/金句）：始终给，点出核心或最值得记住的一句。
- related_hints：给 1~3 个便于关联到其它笔记的关键词/主题（用于双链）。

分类 category：这是用户自己的分类体系，优先从已有分类里选：<<CATEGORIES>>。若都明显不合适，可新建一个简洁分类名（≤6 字），并令 category_is_new=true。注意：category 与上面的板块判断相互独立——不要因为分类名是什么就决定给哪些板块，始终看想法本身的性质。

type：必须只填这 5 个稳定值之一：行动 / 来源 / 随想 / 复盘 / 其它。
tags：3~5 个，具体、可检索。

输出 JSON（所有键都要在，空值用 "" 或 []）：
{"type":"","title":"","is_book_note":false,"book":"","category":"","category_is_new":false,"tags":[],"one_liner":"","background":"","summary":"","next_steps":[],"challenge":"","related_hints":[]}
"""


class NotesService:
    def __init__(self, store: Store, settings: Settings, llm: Optional[DeepSeekClient] = None) -> None:
        self.store = store
        self.settings = settings
        self.llm = llm
        self._just_saved = False  # set when a note was finalized this turn

    def consume_just_saved(self) -> bool:
        """Return whether the most recent handle_message finalized a note, then reset."""
        saved = self._just_saved
        self._just_saved = False
        return saved

    # ---------- session helpers ----------
    def has_active_session(self, session_id: str) -> bool:
        return bool(self.store.get_note_session(session_id))

    def cancel_if_needed(self, session_id: str, text: str) -> Optional[str]:
        if CANCEL_RE.search(text):
            self.store.clear_note_session(session_id)
            return "这条想法收集先取消了。你之后随时可以重新开始。"
        return None

    # ---------- main flow ----------
    def handle_message(self, session_id: str, text: str) -> str:
        existing = self.store.get_note_session(session_id)
        forced_category = self._extract_forced_category(text)

        if not existing:
            # a lone control word with nothing in progress must not become a note
            if BARE_TRIGGER_RE.match(text.strip()) or forced_category:
                return "现在没有正在记录的想法哦～直接把想法发给我，我来帮你整理。"
            messages = [{"role": "user", "content": text}]
            decision = self._converse(messages, first_turn=True)
            if decision["enough"]:
                return self._finalize(session_id, messages)
            self.store.save_note_session(
                session_id,
                status="collecting",
                messages=messages + [{"role": "assistant", "content": decision["reply"]}],
                meta={"started_on": date.today().isoformat(), "type": decision["type"]},
            )
            return (
                "先一起把这个想法理清。\n"
                f"{decision['reply']}\n"
                '（聊清楚我会自动整理；想直接存就说"记下来"）'
            )

        if forced_category:
            return self._finalize(session_id, existing["messages"], forced_category=forced_category)

        messages = existing["messages"] + [{"role": "user", "content": text}]
        if FINALIZE_RE.search(text):
            return self._finalize(session_id, messages)

        decision = self._converse(messages)
        if decision["enough"]:
            return self._finalize(session_id, messages)

        self.store.save_note_session(
            session_id,
            status="collecting",
            messages=messages + [{"role": "assistant", "content": decision["reply"]}],
            meta=existing.get("meta", {}),
        )
        return decision["reply"]

    # ---------- hook 1: typed conversation with auto-finalize ----------
    def _converse(self, messages: List[Dict], first_turn: bool = False) -> Dict:
        if self.llm and self.llm.is_configured:
            try:
                payload = self.llm.chat(
                    [{"role": "system", "content": CONVERSE_SYSTEM}] + messages,
                    json_mode=True,
                    temperature=0.5,
                    max_tokens=160,
                )
                reply = str(payload.get("reply", "")).strip()
                if reply:
                    return {
                        "type": self._normalize_type(
                            str(payload.get("type", TYPE_OTHER)).strip() or TYPE_OTHER,
                            " ".join(
                                m["content"] for m in messages if m.get("role") == "user"
                            ),
                        ),
                        "enough": bool(payload.get("enough")),
                        "reply": reply,
                    }
            except LLMError:
                pass
        return self._fallback_decision(messages, first_turn)

    def _fallback_decision(self, messages: List[Dict], first_turn: bool) -> Dict:
        user_messages = [m["content"] for m in messages if m["role"] == "user"]
        inferred_type = self._infer_type("\n".join(user_messages))
        if first_turn:
            if inferred_type == TYPE_SOURCE:
                return {"type": inferred_type, "enough": False, "reply": "这条想法是来自哪本书、文章或播客？"}
            return {"type": inferred_type, "enough": False, "reply": "你最想先说清楚的是哪一点？"}
        if len(user_messages) >= 3:
            return {"type": inferred_type, "enough": True, "reply": "这条够清楚了，帮你整理成笔记。"}
        latest = user_messages[-1] if user_messages else ""
        if inferred_type == TYPE_SOURCE and not re.search(r"(书名|标题|作者|播客|课程|文章)", latest):
            return {"type": inferred_type, "enough": False, "reply": "来源名称是什么？我好帮你并到同一条笔记。"}
        if inferred_type == TYPE_REVIEW:
            return {"type": inferred_type, "enough": False, "reply": "这次最值得记住的一条经验是什么？"}
        if "为什么" not in latest and "原因" not in latest:
            return {"type": inferred_type, "enough": False, "reply": "你为什么会想到这件事？背后的触发点是什么？"}
        return {"type": inferred_type, "enough": False, "reply": "如果只做一个最小可行版本，你会先做哪一步？"}

    # ---------- finalize: build, link, render, save / merge ----------
    def _finalize(self, session_id: str, messages: List[Dict], forced_category: Optional[str] = None) -> str:
        if not self._has_real_content(messages):
            self.store.clear_note_session(session_id)
            return "现在没有可整理的想法内容～直接说说你的想法就好。"
        # every path below saves/merges a note → mark this turn as a successful record
        self._just_saved = True
        note = self._build_note(messages)
        if forced_category:
            note["category"] = forced_category
            note["category_is_new"] = forced_category not in self.settings.note_categories
        related = self._resolve_related(note.get("related_hints", []), note.get("title", ""))

        # hook 2: same book -> append into one note instead of creating a new file
        if note.get("is_book_note") and note.get("book"):
            book = self._norm_book(note["book"])
            note["title"] = book
            if not note.get("category"):
                note["category"] = "读书"
            entry = self._render_book_entry(note, related)
            existing = self.store.find_note_by_title(book)
            if existing:
                path = self.store.append_to_note(existing["id"], entry, extra_tags=note.get("tags"))
                self.store.clear_note_session(session_id)
                return (
                    f"已并入《{book}》读书笔记（追加了今天的内容）。\n"
                    f"分类：{existing['category']}\n文件：{path}"
                )
            note["markdown"] = self._book_frontmatter(note) + entry
            path = self.store.add_note(note)
            self.store.clear_note_session(session_id)
            return f"已新建《{book}》读书笔记。\n分类：{note['category']}\n文件：{path}"

        note["markdown"] = self._render_markdown(note, related)
        path = self.store.add_note(note)
        self.store.clear_note_session(session_id)
        lines = [
            f"已经记下来了：{note['title']}",
            f"分类：{note['category']}" + ("（新分类）" if note.get("category_is_new") else ""),
            f"标签：{', '.join(note['tags']) if note['tags'] else '无'}",
        ]
        if note.get("one_liner"):
            lines.append(f"一句话：{note['one_liner']}")
        if related:
            lines.append("关联：" + "、".join(related))
        lines.append(f"文件：{path}")
        return "\n".join(lines)

    @staticmethod
    def _extract_forced_category(text: str) -> Optional[str]:
        match = FORCE_CATEGORY_RE.match(text.strip())
        if not match:
            return None
        category = match.group(1).strip()
        return category or None

    # ---------- build structured note (prompt 2) ----------
    @staticmethod
    def _has_real_content(messages: List[Dict]) -> bool:
        """True if any user turn carries actual content (not just a control phrase)."""
        for m in messages:
            if m["role"] == "user":
                text = m["content"].strip()
                if text and not BARE_TRIGGER_RE.match(text):
                    return True
        return False

    @staticmethod
    def _content_messages(messages: List[Dict]) -> List[Dict]:
        """Drop user turns that are only a control phrase (e.g. just "记下来")."""
        cleaned = [
            m for m in messages
            if not (m["role"] == "user" and BARE_TRIGGER_RE.match(m["content"].strip()))
        ]
        return cleaned or messages

    def _build_note(self, messages: List[Dict]) -> Dict:
        messages = self._content_messages(messages)
        if self.llm and self.llm.is_configured:
            try:
                system = BUILD_SYSTEM.replace(
                    "<<CATEGORIES>>", ", ".join(self.settings.note_categories)
                )
                payload = self.llm.chat(
                    [{"role": "system", "content": system}] + messages,
                    json_mode=True,
                    temperature=0.2,
                    max_tokens=900,
                )
                return self._normalize_note(payload)
            except LLMError:
                pass
        return self._fallback_note(messages)

    def _normalize_note(self, payload: Dict) -> Dict:
        def s(key: str) -> str:
            return str(payload.get(key, "") or "").strip()

        def lst(key: str) -> List[str]:
            value = payload.get(key, [])
            if not isinstance(value, list):
                return []
            return [str(item).strip() for item in value if str(item).strip()]

        title = s("title") or "未命名想法"
        category = s("category")
        category_is_new = bool(payload.get("category_is_new"))
        note_type = self._normalize_type(
            s("type"),
            " ".join([title, s("summary"), s("background"), s("book")]).strip(),
        )

        if not category:
            category = self._classify_category(title + " " + s("summary"))
            category_is_new = category not in self.settings.note_categories
        elif len(category) > 8:
            # guard against the model returning a sentence as a category
            category = self._classify_category(title + " " + s("summary"))
            category_is_new = False
        elif category not in self.settings.note_categories:
            category_is_new = True

        return {
            "type": TYPE_SOURCE if bool(payload.get("is_book_note")) else note_type,
            "title": title,
            "is_book_note": bool(payload.get("is_book_note")),
            "book": s("book"),
            "category": category,
            "category_is_new": category_is_new,
            "tags": lst("tags")[:6],
            "one_liner": s("one_liner"),
            "background": s("background"),
            "summary": s("summary"),
            "next_steps": lst("next_steps"),
            "challenge": s("challenge"),
            "related_hints": lst("related_hints"),
        }

    def _fallback_note(self, messages: List[Dict]) -> Dict:
        user_messages = [m["content"] for m in messages if m["role"] == "user"]
        seed = user_messages[0] if user_messages else "未命名想法"
        title = seed[:20].strip("。！？,. ") or "未命名想法"
        return {
            "type": self._infer_type("\n".join(user_messages)),
            "title": title,
            "is_book_note": False,
            "book": "",
            "category": self._classify_category(" ".join(user_messages)),
            "category_is_new": False,
            "tags": self._extract_tags(" ".join(user_messages)),
            "one_liner": "",
            "background": user_messages[1] if len(user_messages) > 1 else "",
            "summary": "\n".join(user_messages),
            "next_steps": [],
            "challenge": "",
            "related_hints": [],
        }

    # ---------- hook 3: related double-links ----------
    def _resolve_related(self, hints: List[str], exclude_title: str) -> List[str]:
        if not hints:
            return []
        exclude = self._norm(exclude_title)
        found: List[str] = []
        for hint in hints:
            hint = str(hint).strip()
            if not hint:
                continue
            try:
                results = self.store.search_notes(query=hint, limit=3)
            except Exception:
                results = []
            for row in results:
                title = row["title"]
                if self._norm(title) == exclude or title in found:
                    continue
                found.append(title)
            if len(found) >= 3:
                break
        return found[:3]

    # ---------- classification / tag fallbacks ----------
    def _normalize_type(self, raw_type: str, text: str = "") -> str:
        value = re.sub(r"\s+", "", str(raw_type or "")).lower()
        alias_groups = {
            TYPE_ACTION: ("行动", "计划", "方案", "执行", "推进", "功能", "改进", "灵感", "项目", "待办"),
            TYPE_SOURCE: ("来源", "读书", "书摘", "书", "文章", "播客", "课程", "摘录", "资料"),
            TYPE_REFLECTION: ("随想", "感受", "观察", "情绪", "想法", "碎碎念", "生活随想"),
            TYPE_REVIEW: ("复盘", "总结", "回顾", "反思", "经验", "教训"),
            TYPE_OTHER: ("其它", "其他", "other"),
        }
        for stable, aliases in alias_groups.items():
            if value == stable.lower() or any(alias in value for alias in aliases):
                return stable
        return self._infer_type(text)

    def _infer_type(self, text: str) -> str:
        text = str(text or "")
        if not text.strip():
            return TYPE_OTHER
        rules = [
            ((r"书", r"书里", r"书名", r"作者", r"文章", r"播客", r"课程", r"读到", r"看到"), TYPE_SOURCE),
            ((r"复盘", r"回顾", r"总结", r"经验", r"教训", r"踩坑", r"这次"), TYPE_REVIEW),
            ((r"计划", r"打算", r"准备", r"要做", r"方案", r"功能", r"改进", r"优化", r"项目", r"需求"), TYPE_ACTION),
            ((r"感觉", r"发现", r"意识到", r"感受", r"观察", r"心情", r"随想", r"想到"), TYPE_REFLECTION),
        ]
        for keywords, stable in rules:
            if any(keyword in text for keyword in keywords):
                return stable
        return TYPE_OTHER

    def _classify_category(self, text: str) -> str:
        mapping = {
            "产品": "产品灵感",
            "功能": "产品灵感",
            "创业": "产品灵感",
            "协作": "产品灵感",
            "版本": "产品灵感",
            "用户": "产品灵感",
            "书": "学习",
            "读": "学习",
            "学习": "学习",
            "课程": "学习",
            "生活": "生活感悟",
            "感受": "生活感悟",
            "工作": "工作",
            "同事": "工作",
        }
        for keyword, category in mapping.items():
            if keyword in text:
                return category
        return "其它"

    def _extract_tags(self, text: str) -> List[str]:
        candidates = []
        for token in re.split(r"[\s，,。；;、]+", text):
            token = token.strip()
            if 1 < len(token) <= 8 and not FINALIZE_RE.search(token):
                candidates.append(token)
        deduped: List[str] = []
        for token in candidates:
            if token not in deduped:
                deduped.append(token)
        return deduped[:5]

    # ---------- hook 4: conditional markdown rendering ----------
    def _render_markdown(self, note: Dict, related_titles: List[str]) -> str:
        tags = ", ".join(note.get("tags", []))
        lines = [
            "---",
            f"title: {note['title']}",
            f"category: {note['category']}",
            f"tags: [{tags}]",
            f"type: {note.get('type', '')}",
            f"created: {date.today().isoformat()}",
            "---",
            "",
        ]

        def section(heading: str, body: str) -> None:
            lines.append(f"## {heading}")
            lines.append(body)
            lines.append("")

        if note.get("one_liner"):
            section("一句话", note["one_liner"])
        if note.get("summary"):
            section("核心内容", note["summary"])
        if note.get("background"):
            section("背景 / 触发点", note["background"])
        if note.get("next_steps"):
            section("可行的下一步", "\n".join(f"- [ ] {step}" for step in note["next_steps"]))
        if note.get("challenge"):
            section("盲点 / 反方", note["challenge"])
        if related_titles:
            section("关联", " ".join(f"[[{title}]]" for title in related_titles))

        return "\n".join(lines).rstrip() + "\n"

    def _book_frontmatter(self, note: Dict) -> str:
        tags = ", ".join(note.get("tags", []))
        return (
            "---\n"
            f"title: {note['title']}\n"
            f"category: {note['category']}\n"
            f"tags: [{tags}]\n"
            f"type: {note.get('type') or TYPE_SOURCE}\n"
            f"created: {date.today().isoformat()}\n"
            "---\n\n"
            f"# 《{note['title']}》读书笔记\n\n"
        )

    def _render_book_entry(self, note: Dict, related_titles: List[str]) -> str:
        parts = [f"## {date.today().isoformat()}"]
        if note.get("one_liner"):
            parts.append(f"> {note['one_liner']}")
        if note.get("summary"):
            parts.append(note["summary"])
        if note.get("background"):
            parts.append(f"**触发 / 背景**：{note['background']}")
        if note.get("next_steps"):
            parts.append("**可行的下一步**\n" + "\n".join(f"- [ ] {step}" for step in note["next_steps"]))
        if note.get("challenge"):
            parts.append(f"**盲点 / 反方**：{note['challenge']}")
        if related_titles:
            parts.append("**关联**：" + " ".join(f"[[{title}]]" for title in related_titles))
        return "\n\n".join(parts)

    # ---------- text normalizers ----------
    @staticmethod
    def _norm_book(text: str) -> str:
        return str(text).strip().strip("《》〈〉\"'“”").strip() or "未命名书"

    @staticmethod
    def _norm(text: str) -> str:
        return re.sub(r"\s+", "", str(text)).strip("《》〈〉\"'“”").lower()
