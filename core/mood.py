from __future__ import annotations

import re
from typing import Dict, List, Optional

# Single source of truth for emotions: key / color (Almanac palette) / valence / aliases.
# Icons live in the dashboard (custom thin-line SVG); WeChat replies are text-only.
EMOTIONS: List[Dict] = [
    {
        "key": "开心",
        "color": "#c0902f",
        "valence": "积极",
        "aliases": ["开心", "高兴", "愉快", "快乐", "喜悦", "满足", "幸福", "挺好", "很好", "爽"],
    },
    {
        "key": "平静",
        "color": "#3f6f63",
        "valence": "积极",
        "aliases": ["平静", "平和", "放松", "淡定", "安心", "踏实", "平稳", "松弛", "还好"],
    },
    {
        "key": "焦虑",
        "color": "#c0432a",
        "valence": "低落",
        "aliases": ["焦虑", "紧张", "烦躁", "心烦", "压力", "不安", "着急", "焦灼", "慌"],
    },
    {
        "key": "难过",
        "color": "#4a5b6b",
        "valence": "低落",
        "aliases": ["难过", "伤心", "低落", "沮丧", "委屈", "失落", "郁闷", "难受", "不开心", "心情不好"],
    },
    {
        "key": "恐惧",
        "color": "#5b3a40",
        "valence": "低落",
        "aliases": ["恐惧", "害怕", "担心", "畏惧", "发怵", "惊恐", "惶恐"],
    },
    {
        "key": "很难描述",
        "color": "#8a7f69",
        "valence": "中性",
        "aliases": ["很难描述", "说不清", "说不上来", "一言难尽", "五味杂陈", "复杂", "麻木", "混乱"],
    },
    {
        "key": "自定义",
        "color": "#6f6a3a",
        "valence": "中性",
        "aliases": [],
    },
]

EMOTION_BY_KEY: Dict[str, Dict] = {emo["key"]: emo for emo in EMOTIONS}
CANONICAL_KEYS = [emo["key"] for emo in EMOTIONS if emo["key"] != "自定义"]
POSITIVE_KEYS = [emo["key"] for emo in EMOTIONS if emo["valence"] == "积极"]
CUSTOM_KEY = "自定义"
MOOD_OPTION_KEYS = CANONICAL_KEYS
MOOD_OPTION_MAP = {str(index + 1): key for index, key in enumerate(MOOD_OPTION_KEYS)}
ALIAS_TO_KEY = sorted(
    [
        (alias, emo["key"])
        for emo in EMOTIONS
        for alias in emo["aliases"]
        if alias
    ],
    key=lambda item: len(item[0]),
    reverse=True,
)

MOOD_MARKERS = ("情绪", "心情", "心境", "今天感觉", "今天心情", "感觉", "状态")
MOOD_COMMANDS = (
    "记录情绪", "记情绪", "写情绪", "情绪记录",
    "记录心情", "记心情", "写心情", "心情记录",
)
MOOD_PROMPT = "顺手记下今天的心情吧——开心 / 平静 / 焦虑 / 难过 / 恐惧 / 很难描述，或自己说一句。"
MOOD_PICKER_PROMPT = (
    "想记录哪一种心情？\n"
    "1. 开心\n"
    "2. 平静\n"
    "3. 焦虑\n"
    "4. 难过\n"
    "5. 恐惧\n"
    "6. 很难描述\n"
    "也可以直接回一句自己的感受。"
)

_STRIP_RE = re.compile(r"^(?:今天)?(?:的)?(?:记录|记)?(?:情绪|心情|心境|感觉|状态)?\s*[:：是]?\s*")
_FILLER_RE = re.compile(
    r"^(?:今天|我今天|今天我|此刻|现在|今天整天|今天一整天|一整天|整天|今天都|最近|这会儿|刚刚|有点|有些|有一点|挺|很|太|比较|特别|非常|一直|都|就|还|还挺|真的|确实|是|觉得|感觉|心情|情绪|状态|因为|由于|为了|被|了|的|\s)+"
)
_TAIL_RE = re.compile(r"(了一天|一整天|整天|很久|很久了|到现在|到晚上|到刚刚|一上午|一下午|一晚上)$")
_CAUSE_RE = re.compile(r"(因为|由于|被|为了|和|跟|关于|对)\S+")


def _match_canonical(text: str) -> Optional[str]:
    for alias, key in ALIAS_TO_KEY:
        if alias in text:
            return key
    return None


def _has_marker(text: str) -> bool:
    return any(marker in text for marker in MOOD_MARKERS)


def _strip_markers(text: str) -> str:
    return _STRIP_RE.sub("", text).strip()


def _extract_note(raw: str, emotion: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    aliases = EMOTION_BY_KEY.get(emotion, {}).get("aliases", [])
    for alias in sorted(aliases, key=len, reverse=True):
        if alias and alias in text:
            text = text.replace(alias, " ", 1)
            break
    text = _strip_markers(text)
    text = _FILLER_RE.sub("", text).strip("，,。！？!?：:；; ")
    text = _TAIL_RE.sub("", text).strip("，,。！？!?：:；; ")
    if not text:
        return ""
    # Very short residue usually means only intensity / filler, not a useful note.
    if len(text) <= 3 and not _CAUSE_RE.search(raw):
        return ""
    return text


def parse_mood_choice(text: str) -> Optional[Dict]:
    raw = (text or "").strip()
    if not raw:
        return None
    key = MOOD_OPTION_MAP.get(raw)
    if not key:
        return None
    return {"emotion": key, "note": ""}


def is_mood_prompt_request(text: str) -> bool:
    raw = re.sub(r"\s+", "", (text or "").strip())
    if not raw:
        return False
    return raw in {re.sub(r"\s+", "", item) for item in MOOD_COMMANDS}


def parse_mood(text: str) -> Optional[Dict]:
    """Return {"emotion", "note"} for a mood statement, else None.

    Canonical emotions match by alias; a mood marker (情绪/心情…) with no canonical
    match falls back to a free-text custom entry. Plain non-mood text returns None.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if is_mood_prompt_request(raw):
        return None
    chosen = parse_mood_choice(raw)
    if chosen:
        return chosen
    key = _match_canonical(raw)
    if key:
        return {"emotion": key, "note": _extract_note(raw, key)}
    if _has_marker(raw):
        note = _strip_markers(raw)
        return {"emotion": CUSTOM_KEY, "note": note or raw}
    return None


def looks_like_mood(text: str) -> bool:
    """Intent-level detection: an explicit mood statement or a bare emotion word."""
    raw = (text or "").strip()
    if not raw:
        return False
    if is_mood_prompt_request(raw):
        return True
    if parse_mood_choice(raw):
        return True
    if _has_marker(raw) and len(raw) <= 24:
        return True
    if _match_canonical(raw) and len(raw) <= 8:
        return True
    if any(token in raw for token in ("今天", "现在", "此刻", "一整天", "整天", "一天")) and _match_canonical(raw):
        return True
    if _CAUSE_RE.search(raw) and _match_canonical(raw):
        return True
    return False


def is_mood_answer(text: str) -> bool:
    """A concise reply that should be captured as the answer to a proactive mood prompt."""
    raw = (text or "").strip()
    if not raw or len(raw) > 16:
        return False
    return _has_marker(raw) or _match_canonical(raw) is not None or parse_mood_choice(raw) is not None


def format_mood_confirmation(emotion: str, note: str = "") -> str:
    if emotion != CUSTOM_KEY and note:
        return f"记下了今天的心情：{emotion}\n备注：{note}"
    if emotion == CUSTOM_KEY and note:
        return f"记下了今天的心情：{note}"
    return f"记下了今天的心情：{emotion}"


def emotion_color(emotion: str) -> str:
    return EMOTION_BY_KEY.get(emotion, EMOTION_BY_KEY[CUSTOM_KEY])["color"]


def palette() -> List[Dict]:
    """Compact list for the dashboard (key/color/valence), in canonical order."""
    return [{"key": e["key"], "color": e["color"], "valence": e["valence"]} for e in EMOTIONS]
