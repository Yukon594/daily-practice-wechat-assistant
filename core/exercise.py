from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Dict, Optional

from core.llm import DeepSeekClient, LLMError

from core.ledger import chinese_to_number

ACTIVITY_ALIASES = {
    "跑步": ["跑步", "慢跑", "夜跑", "晨跑"],
    "骑行": ["骑车", "骑行", "单车", "动感单车"],
    "游泳": ["游泳"],
    "步行": ["走路", "步行", "散步", "徒步"],
    "瑜伽": ["瑜伽"],
    "羽毛球": ["羽毛球"],
    "篮球": ["篮球"],
    "足球": ["足球"],
    "力量训练": ["练胸", "练腿", "练背", "练肩", "撸铁", "力量", "健身", "训练"],
}
QUERY_HINTS = ("多少", "统计", "看看", "查询", "同步", "总结", "汇总", "合计")

NUMBER_TOKEN = r"(\d+(?:\.\d+)?|[零一二两三四五六七八九十百千万半]+)"
DURATION_RE = re.compile(NUMBER_TOKEN + r"\s*(小时|分钟|分|h|hr)", re.IGNORECASE)
DISTANCE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(公里|km|千米)", re.IGNORECASE)
CALORIES_RE = re.compile(r"(\d+)\s*(千卡|大卡|kcal|卡)", re.IGNORECASE)
CANONICAL_ACTIVITIES = tuple(ACTIVITY_ALIASES.keys())
EXERCISE_PARSE_SYSTEM = (
    "你是一个中文运动记录解析器。"
    "把输入解析为结构化 JSON。"
    '只返回 JSON 对象，格式为 {"session":{"ts":"YYYY-MM-DD","activity":"跑步","duration_minutes":30,"distance_km":5.0,"calories":320}}。'
    f"activity 只能是：{', '.join(CANONICAL_ACTIVITIES)}。"
    "如果原文是上肢/下肢/胸/腿/背/肩/健身房训练，都归为「力量训练」。"
    "能确定的字段就填，不能确定的 distance_km 或 calories 填 null。"
    "duration_minutes 必须是分钟整数；像半小时要换算成 30。"
    "ts 必须是 ISO 日期；今天/昨天/前天按用户原文理解。"
)


def detect_activity(text: str) -> Optional[str]:
    for activity, aliases in ACTIVITY_ALIASES.items():
        if any(alias in text for alias in aliases):
            return activity
    return None


_UNDO_VERBS = ("撤销", "删掉", "删除", "去掉", "去除", "撤回")
_UNDO_HINTS = ("刚才", "上一条", "最近一条", "最近那条", "这条", "那条", "刚记", "刚刚", "记录")
# filler that may surround a bare undo phrase (e.g. 「撤销一下」「删掉吧」「去掉那条」)
_UNDO_FILLER_RE = re.compile(
    r"(撤销|撤回|去除|删掉|删除|去掉|不要|取消|一下|吧|了|啦|呗|刚才|这|那|条|个|的|，|。|！|？|!|\?|\s)"
)


def looks_like_exercise_undo(text: str) -> bool:
    """A chat-side 'undo my last exercise' gesture.

    Matches explicit「删掉刚才的运动/撤销运动」, recency phrasing「删掉刚才那条」, and a
    bare「去除/删掉/撤销」(handled with a recency window so it can't nuke an old record).
    """
    raw = (text or "").strip()
    if not raw or len(raw) > 20:
        return False
    if not any(verb in raw for verb in _UNDO_VERBS):
        return False
    if detect_activity(raw) is not None or "运动" in raw or "健身" in raw:
        return True
    if any(hint in raw for hint in _UNDO_HINTS):
        return True
    # bare undo: nothing substantive remains once verbs/fillers are stripped
    return _UNDO_FILLER_RE.sub("", raw) == ""


def looks_like_exercise_text(text: str) -> bool:
    activity = detect_activity(text)
    if not activity:
        return False
    if any(token in text for token in QUERY_HINTS):
        return False
    return bool(DURATION_RE.search(text) or DISTANCE_RE.search(text) or CALORIES_RE.search(text))


def parse_exercise(text: str, llm: Optional[DeepSeekClient] = None) -> Dict:
    try:
        return _parse_with_rules(text)
    except ValueError as local_error:
        if llm and llm.is_configured:
            try:
                parsed = _parse_with_llm(text, llm)
                if parsed:
                    return parsed
            except LLMError:
                pass
        raise local_error


def _parse_with_rules(text: str) -> Dict:
    activity = detect_activity(text)
    if not activity:
        raise ValueError("无法识别运动类型")

    duration_minutes = _parse_duration_minutes(text)
    distance_km = _parse_distance(text)
    calories = _parse_calories(text)

    if duration_minutes is None and distance_km is None and calories is None:
        raise ValueError("无法识别运动数据")

    if duration_minutes is None:
        duration_minutes = 0

    return {
        "ts": _parse_relative_date(text).isoformat(),
        "activity": activity,
        "duration_minutes": duration_minutes,
        "distance_km": distance_km,
        "calories": calories,
        "source": "manual",
    }


def _parse_with_llm(text: str, llm: DeepSeekClient) -> Optional[Dict]:
    payload = llm.chat(
        [
            {"role": "system", "content": EXERCISE_PARSE_SYSTEM},
            {"role": "user", "content": f"请解析这条运动记录：{text}"},
        ],
        json_mode=True,
        temperature=0.1,
        max_tokens=240,
    )
    return _normalize_session(payload.get("session", {}), text)


def format_exercise_confirmation(session: Dict) -> str:
    parts = [session["activity"]]
    if session.get("duration_minutes"):
        parts.append(f'{session["duration_minutes"]}分钟')
    if session.get("distance_km") is not None:
        parts.append(f'{session["distance_km"]:g}公里')
    if session.get("calories") is not None:
        parts.append(f'{session["calories"]}千卡')
    return "已记录运动：" + "，".join(parts)


def _parse_duration_minutes(text: str) -> Optional[int]:
    match = DURATION_RE.search(text)
    if not match:
        return None
    value = chinese_to_number(match.group(1))
    if value is None:
        return None
    unit = match.group(2).lower()
    minutes = float(value) * 60 if unit in {"小时", "h", "hr"} else float(value)
    return max(int(round(minutes)), 0)


def _parse_distance(text: str) -> Optional[float]:
    match = DISTANCE_RE.search(text)
    if not match:
        return None
    return round(float(match.group(1)), 2)


def _parse_calories(text: str) -> Optional[int]:
    match = CALORIES_RE.search(text)
    if not match:
        return None
    return int(match.group(1))


def _parse_relative_date(text: str) -> date:
    today = date.today()
    if "大前天" in text:
        return today - timedelta(days=3)
    if "前天" in text:
        return today - timedelta(days=2)
    if "昨天" in text:
        return today - timedelta(days=1)
    return today


# Date expressions the rule parser can't resolve on its own (so the LLM's date may be
# trusted). Deliberately EXCLUDES 今天/昨天/前天/大前天 — those are handled deterministically.
_EXPLICIT_DATE_RE = re.compile(
    r"(\d{4}\s*[-/年]\s*\d{1,2}"          # 2026-06-01 / 2026年6月
    r"|\d{1,2}\s*月\s*\d{1,2}"            # 6月1日
    r"|\d{1,2}\s*[日号]"                   # 5日 / 5号
    r"|\d+\s*天前"                          # 3天前
    r"|上+\s*(?:周|个?星期|礼拜)"          # 上周 / 上上周 / 上个星期
    r"|这\s*周|本\s*周"                     # 这周 / 本周
    r"|周[一二三四五六日天]|星期[一二三四五六日天]|礼拜[一二三四五六日天])"
)


def _resolve_ts(llm_ts: str, raw_text: str) -> str:
    """Resolve a workout date safely: never trust an LLM date the text doesn't justify.

    If the text carries no explicit calendar date, the date comes from the rule parser
    (今天/昨天/前天 → today/-1/-2). Only an explicit expression (6月1日, 3天前, 上周三…)
    lets the LLM's ISO date through, and future dates are clamped to today.
    """
    today = date.today()
    rule_dt = _parse_relative_date(raw_text)
    ts = (llm_ts or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ts):
        return rule_dt.isoformat()
    if not _EXPLICIT_DATE_RE.search(raw_text or ""):
        return rule_dt.isoformat()
    try:
        parsed = date.fromisoformat(ts)
    except ValueError:
        return rule_dt.isoformat()
    if parsed > today:                       # a finished workout can't be in the future
        return today.isoformat()
    if parsed < today - timedelta(days=730) and not re.search(r"\d{4}", raw_text):
        return rule_dt.isoformat()           # absurdly old with no explicit year → distrust
    return ts


def _normalize_session(payload: Dict, raw_text: str) -> Optional[Dict]:
    if not isinstance(payload, dict):
        return None

    activity = _normalize_activity(str(payload.get("activity", "")).strip())
    if not activity:
        return None

    ts = _resolve_ts(str(payload.get("ts", "")), raw_text)

    duration_minutes = _coerce_minutes(payload.get("duration_minutes"))
    distance_km = _coerce_distance(payload.get("distance_km"))
    calories = _coerce_calories(payload.get("calories"))

    if duration_minutes is None and distance_km is None and calories is None:
        return None

    return {
        "ts": ts,
        "activity": activity,
        "duration_minutes": duration_minutes or 0,
        "distance_km": distance_km,
        "calories": calories,
        "source": "manual",
    }


def _normalize_activity(token: str) -> Optional[str]:
    if not token:
        return None
    if token in ACTIVITY_ALIASES:
        return token
    return detect_activity(token)


def _coerce_minutes(value) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return max(int(round(float(value))), 0)
    except (TypeError, ValueError):
        number = chinese_to_number(str(value).strip())
        if number is None:
            return None
        return max(int(round(float(number))), 0)


def _coerce_distance(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _coerce_calories(value) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return max(int(round(float(value))), 0)
    except (TypeError, ValueError):
        return None
