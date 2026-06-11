from __future__ import annotations

import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from config import Settings
from core.llm import DeepSeekClient, LLMError
from core.store import Store

# ---------- prompt ----------
CAPTURE_SYSTEM = """\
你是「日迹」的想法归档器。用户发来一段已经想清楚的想法 / 总结，你只做三件事：起标题、归类、打标签。
**不要改写、复述或补充正文，不要追问。** 只返回 JSON：
{"title":"≤14字的精炼标题，点出这条想法的核心","category":"","category_is_new":false,"tags":["3~4个概念主题词"]}

- category 选择梯度：① 先从下面已有分类里挑**最贴切**的一个；② 若这条明显属于一个尚无的新主题，
  就**新建**一个简洁分类名（≤6字）并令 category_is_new=true；③ 只有真正零散、不值得单独成类的，才用「其它」。
  已有分类（含说明与示例）：
<<CATEGORIES>>
- tags：3~4 个具体、可检索的概念主题词；优先复用已有标签：<<TAGS>>，确是新主题才新建。
只返回 JSON，不要任何多余文字。
"""

# one-line meaning for the seed categories (user-custom ones get examples instead)
CATEGORY_HINTS = {
    "产品灵感": "产品/功能/创业点子、工具与协作的想法",
    "生活感悟": "生活随想、人际、个人体会",
    "工作": "工作事务、同事、项目执行",
    "学习": "读书/课程/文章的观点与笔记",
    "其它": "暂时归不到上面任何一类的零散内容",
}

# ---- start-anchored category directives (the verb / slash forms) ----
_CAT_VERBS = "记到|记录到|归到|归类到|分类到|存到|保存到|收录到|放到|放进|加到"
_CAT_VERB_RE = re.compile(
    rf"^(?:{_CAT_VERBS})\s*(?P<cat>[^\s：:，,。、/]{{1,8}})\s*[：:，,。、\s\-]+(?P<body>.+)$", re.S
)
_CAT_SLASH_RE = re.compile(r"^/\s*(?P<cat>[^\s：:/]{1,8})[\s：:]+(?P<body>.+)$", re.S)

# ---- a leading "记一个想法 / 想法：…" capture marker (routing cue, not content) ----
_CAPTURE_PREFIX_RE = re.compile(
    r"^(?:随手记一个想法|记一个想法|记个想法|记一下想法|记录一下|帮我记一下|帮我记|随手记"
    r"|记下来|记一下|记下|想法|笔记|灵感|点子)\s*[：:，,。、\s]+"
)

# ---- a thought that carries its own title ----
_TITLE_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*(?:\n|$)")
_TITLE_LABEL_RE = re.compile(r"^(?:标题|题)\s*[：:]\s*(?P<title>.+?)\s*(?:\n|$)")


def _strip_capture_marker(body: str) -> str:
    stripped = _CAPTURE_PREFIX_RE.sub("", body.lstrip(), count=1).strip()
    return stripped or body


def _parse_category_directive(text: str) -> Tuple[Optional[str], str]:
    """Detect a leading 「记到X：…」/「/X …」 directive → (forced_category, cleaned_body)."""
    raw = (text or "").strip()
    for rx in (_CAT_VERB_RE, _CAT_SLASH_RE):
        m = rx.match(raw)
        if m:
            cat, body = m.group("cat").strip(), m.group("body").strip()
            if cat and body:
                return cat, body
    return None, text


def _extract_own_title(body: str) -> Tuple[Optional[str], str]:
    """If the thought starts with its own title, use it (don't let AI clobber)."""
    raw = body.lstrip("\n ")
    m = _TITLE_HEADING_RE.match(raw)
    if m:  # markdown heading: keep the line (reader de-dups), title = heading text
        return m.group("title").strip()[:30], body
    m = _TITLE_LABEL_RE.match(raw)
    if m:  # 「标题：X」: use it and drop that line
        return m.group("title").strip()[:30], raw[m.end():].lstrip("\n")
    return None, body


class NotesService:
    """One-shot capture: faithfully store the thought, only auto title / category / tags."""

    def __init__(self, store: Store, settings: Settings, llm: Optional[DeepSeekClient] = None) -> None:
        self.store = store
        self.settings = settings
        self.llm = llm

    # ---------- public: record a thought in one shot ----------
    def capture(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return "想记点什么？直接把想法发我，我来归档。"

        forced, body = _parse_category_directive(text)
        body = _strip_capture_marker(body)
        own_title, body = _extract_own_title(body)
        body = body.strip() or text

        meta = self._classify(body)
        title = own_title or meta["title"]
        if forced:
            category, category_is_new = forced, forced not in self._known_categories()
        else:
            category, category_is_new = meta["category"], meta["category_is_new"]

        note = {"title": title, "category": category, "tags": meta["tags"]}
        note["markdown"] = self._render(note, body)
        path = self.store.add_note(note)
        lines = [
            f"已经记下来了：{title}",
            f"分类：{category}" + ("（新分类）" if category_is_new else ""),
            f"标签：{', '.join(note['tags']) if note['tags'] else '无'}",
            f"文件：{path}",
        ]
        return "\n".join(lines)

    def _known_categories(self) -> set:
        known = set(self.settings.note_categories)
        try:
            known |= {row["category"] for row in self.store.get_note_categories()}
        except Exception:  # noqa
            pass
        return known

    # ---------- title / category / tags ----------
    def _category_context(self) -> str:
        examples = self.store.category_examples(3)
        ordered = list(self.settings.note_categories)
        for cat in examples:
            if cat not in ordered:
                ordered.append(cat)
        lines = []
        for cat in ordered:
            parts = []
            if CATEGORY_HINTS.get(cat):
                parts.append(CATEGORY_HINTS[cat])
            if examples.get(cat):
                parts.append("例：" + "、".join(examples[cat]))
            suffix = "（" + "；".join(parts) + "）" if parts else ""
            lines.append(f"- {cat}{suffix}")
        return "\n".join(lines)

    def _classify(self, text: str) -> Dict:
        if self.llm and self.llm.is_configured:
            try:
                system = CAPTURE_SYSTEM.replace(
                    "<<CATEGORIES>>", self._category_context()
                ).replace(
                    "<<TAGS>>", ", ".join(self.store.get_all_tags()) or "（暂无，自行命名）"
                )
                payload = self.llm.chat(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": text},
                    ],
                    json_mode=True,
                    temperature=0.2,
                    max_tokens=200,
                )
                if isinstance(payload, dict):
                    return self._normalize_meta(payload, text)
            except LLMError:
                pass
        return self._fallback_meta(text)

    def _normalize_meta(self, payload: Dict, text: str) -> Dict:
        title = str(payload.get("title", "") or "").strip() or text[:14].strip() or "未命名想法"
        raw_tags = payload.get("tags", [])
        tags = (
            [str(t).strip() for t in raw_tags if str(t).strip()][:4]
            if isinstance(raw_tags, list)
            else []
        )
        if not tags:
            tags = self._extract_tags(text)

        category = str(payload.get("category", "") or "").strip()
        category_is_new = bool(payload.get("category_is_new"))
        if not category or len(category) > 8:  # missing or a sentence -> fall back
            category = self._classify_category(title + " " + text)
            category_is_new = category not in self.settings.note_categories
        elif category not in self._known_categories():
            category_is_new = True

        return {"title": title, "category": category, "category_is_new": category_is_new, "tags": tags}

    def _fallback_meta(self, text: str) -> Dict:
        title = text[:14].strip("。！？,. ") or "未命名想法"
        return {
            "title": title,
            "category": self._classify_category(text),
            "category_is_new": False,
            "tags": self._extract_tags(text),
        }

    # ---------- render: frontmatter + the user's text, verbatim ----------
    @staticmethod
    def _render(note: Dict, body: str) -> str:
        tags = ", ".join(note.get("tags", []))
        return (
            "---\n"
            f"title: {note['title']}\n"
            f"category: {note['category']}\n"
            f"tags: [{tags}]\n"
            f"created: {date.today().isoformat()}\n"
            "---\n\n"
            f"{body.strip()}\n"
        )

    # ---------- offline classification / tag fallbacks ----------
    def _classify_category(self, text: str) -> str:
        mapping = {
            "产品": "产品灵感", "功能": "产品灵感", "创业": "产品灵感", "协作": "产品灵感",
            "版本": "产品灵感", "用户": "产品灵感",
            "书": "学习", "读": "学习", "学习": "学习", "课程": "学习",
            "生活": "生活感悟", "感受": "生活感悟",
            "工作": "工作", "同事": "工作",
        }
        for keyword, category in mapping.items():
            if keyword in text:
                return category
        return "其它"

    @staticmethod
    def _extract_tags(text: str) -> List[str]:
        deduped: List[str] = []
        for token in re.split(r"[\s，,。；;、]+", text):
            token = token.strip()
            if 1 < len(token) <= 8 and token not in deduped:
                deduped.append(token)
        return deduped[:4]
