from __future__ import annotations

from typing import Optional

from core.exercise import looks_like_exercise_text
from core.llm import DeepSeekClient, LLMError
from core.mood import is_confident_mood, looks_like_mood

INTENTS = {"exercise", "mood", "note", "query", "chat"}
QUERY_KEYWORDS = [
    "统计", "总共", "合计", "看看", "查询", "本月", "这个月", "本周", "这周",
    "今天", "专注", "番茄", "番茄钟", "森林", "运动", "跑了", "同步",
]
NOTE_KEYWORDS = [
    "想法", "灵感", "记录", "记一下", "备忘", "我想", "想到", "做个",
    "感悟", "在读", "读到", "读完", "看完", "书里", "笔记",
]
# substantive first-person reflections ("随想/感悟") that rarely contain a note keyword
REFLECTION_MARKERS = [
    "觉得", "感觉", "其实", "突然", "意识到", "原来", "明白", "感慨", "领悟",
    "越来越", "有时候", "我发现", "人生", "成长", "人和人", "关系",
]

CLASSIFY_SYSTEM = (
    "你是「日迹」助手的意图分类器，判断用户这句话属于哪一类，只返回 JSON："
    '{"intent":"exercise|mood|note|query|chat"}。\n'
    "判据：\n"
    "- exercise：在记录一次运动，如「今天跑步5公里32分钟」「晚上练胸45分钟」。\n"
    "- mood：在说自己此刻/今天的心情感受（哪怕是被某件事触发的），如「今天有点焦虑」"
    "「心情不错」「情绪 平静」「想到那件事就有点恐惧」「一忙起来就烦」。\n"
    "- query：在查询运动/专注/想法统计，如「这周运动了几次」「这个月专注了多久」「看看最近想法」。\n"
    "- note：在展开一个想法、点子、观点、观察或感悟——重点是「构想一个东西」或「分析一个道理」，"
    "即使句中带情绪词，如「我想把情绪卡做成月历模式」「散步时想到，很多焦虑本质上是对失控的感觉」"
    "「在读纳瓦尔宝典，财富是睡后收入」。\n"
    "- chat：仅当它是对助手的寒暄、操作指令或简短问答时，如「你好」「你能干嘛」「谢谢」「在吗」。\n"
    "区分要点：句子在「说我现在的感受」→ mood；在「构想/分析某个东西或道理」→ note。"
    "情绪词出现在被构想/分析的对象里（如「情绪卡」「焦虑的本质」）时归 note。只返回 JSON。"
)


def _looks_like_reflection(text: str) -> bool:
    return len(text) >= 10 and any(marker in text for marker in REFLECTION_MARKERS)


def classify_intent(text: str, llm: Optional[DeepSeekClient] = None) -> str:
    lowered = text.strip().lower()
    if not lowered:
        return "chat"

    # high-confidence deterministic shortcuts
    if _looks_like_query(text):
        return "query"
    if looks_like_exercise_text(text):
        return "exercise"
    if is_confident_mood(text):
        return "mood"

    # ambiguous mood-vs-note-vs-chat: let the LLM arbitrate before any keyword shortcut,
    # so a reflection/idea that mentions an emotion isn't stolen by mood, and a short
    # event-triggered feeling isn't stolen by a NOTE keyword like 「想到」
    if llm and llm.is_configured:
        try:
            payload = llm.chat(
                [
                    {"role": "system", "content": CLASSIFY_SYSTEM},
                    {"role": "user", "content": f"请判断这句话的意图：{text}"},
                ],
                json_mode=True,
                temperature=0.0,
                max_tokens=80,
            )
            intent = payload.get("intent", "chat")
            if intent in INTENTS:
                return intent
        except LLMError:
            pass

    # offline heuristics (no LLM available)
    if looks_like_mood(text):
        return "mood"
    if any(keyword in lowered for keyword in NOTE_KEYWORDS):
        return "note"
    if _looks_like_reflection(text):
        return "note"
    return "chat"


def _looks_like_query(text: str) -> bool:
    if any(token in text for token in ("多少", "统计", "看看", "查询", "同步", "汇总", "总结", "合计")):
        return True
    domain_words = ("运动", "跑步", "骑行", "健身", "专注", "番茄", "番茄钟", "森林", "想法", "笔记")
    period_words = ("今天", "本周", "这周", "本月", "这个月", "最近")
    return (
        any(domain in text for domain in domain_words)
        and any(period in text for period in period_words)
        and not looks_like_exercise_text(text)
    )
