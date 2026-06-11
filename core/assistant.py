from __future__ import annotations

import re
from datetime import date
from typing import Optional, Tuple

from config import Settings
from core.exercise import (
    detect_activity,
    format_exercise_confirmation,
    looks_like_exercise_text,
    looks_like_exercise_undo,
    parse_exercise,
)
from core.focus import PomodoroSyncService, format_focus_duration
from core.llm import DeepSeekClient, LLMError
from core.mood import (
    MOOD_PICKER_PROMPT,
    MOOD_PROMPT,
    _match_canonical,
    classify_mood,
    format_mood_confirmation,
    is_mood_prompt_request,
    parse_mood,
)
from core.notes import NotesService
from core.router import classify_intent

# a bare 「改到X / 挪到X / 改成X分类」 (no body) -> re-categorize the most recent note
_RECAT_RE = re.compile(r"^(?:改到|挪到|换到|改分类到|归类到|放到)\s*(?P<cat>[^\s：:，,。/]{1,8})(?:\s*分类)?\s*$")
from core.store import Store

EXERCISE_ALIASES = ("运动", "跑步", "骑行", "健身", "游泳", "步行", "瑜伽", "羽毛球", "篮球", "足球")
FOCUS_ALIASES = ("专注", "番茄", "番茄钟", "森林")


class AssistantEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = Store(settings)
        self.llm = DeepSeekClient(settings)
        self.notes = NotesService(self.store, settings, self.llm)
        self.focus_sync = PomodoroSyncService(self.store, settings)

    def handle_message(self, text: str, session_id: str = "default") -> str:
        text = text.strip()
        if not text:
            return "你可以发我一条运动记录、一个想法、一句心情，或者问我这周运动和专注情况。"

        undo_reply = self._handle_undo(session_id, text)
        if undo_reply is not None:
            return undo_reply

        recat = self._handle_recategorize(text)
        if recat is not None:
            return recat

        captured = self._capture_mood_answer(session_id, text)
        if captured is not None:
            return captured

        intent = classify_intent(text, self.llm)
        if intent == "mood":
            return self._handle_mood(session_id, text)
        if intent == "exercise":
            reply, recorded = self._handle_exercise(text)
            return self._maybe_append_mood_prompt(session_id, reply, recorded)
        if intent == "note":
            reply = self.notes.capture(text)
            return self._maybe_append_mood_prompt(session_id, reply, True)
        if intent == "query":
            return self._handle_query(text)
        return self._handle_chat(text)

    def _handle_undo(self, session_id: str, text: str) -> Optional[str]:
        """Unified chat undo. Explicit「运动/想法」picks the target; a bare「撤销/删掉」undoes
        whichever record (exercise or note) is most recent within a short window."""
        if not looks_like_exercise_undo(text):
            return None
        explicit_ex = detect_activity(text) is not None or any(w in text for w in ("运动", "健身", "锻炼"))
        explicit_note = any(w in text for w in ("想法", "笔记", "点子", "随想"))
        if explicit_note and not explicit_ex:
            return self._undo_note(session_id, None) or "最近没有可撤销的想法。"
        if explicit_ex and not explicit_note:
            return self._undo_exercise(session_id, None) or "最近没有可撤销的运动记录。"
        # bare / ambiguous: undo the more recent of the two, only if recently created
        ex_ts, nt_ts = self.store.last_exercise_ts(), self.store.last_note_ts()
        prefer_note = nt_ts is not None and (ex_ts is None or nt_ts >= ex_ts)
        order = ("note", "exercise") if prefer_note else ("exercise", "note")
        for kind in order:
            reply = self._undo_note(session_id, 900) if kind == "note" else self._undo_exercise(session_id, 900)
            if reply is not None:
                return reply
        return None  # nothing recent to undo -> let normal handling take over

    def _undo_exercise(self, session_id: str, window: Optional[int]) -> Optional[str]:
        deleted = self.store.delete_last_exercise(within_seconds=window)
        if not deleted:
            return None
        self.store.clear_mood_pending(session_id)  # cancels the mood prompt that record triggered
        detail = format_exercise_confirmation(deleted).replace("已记录运动：", "", 1)
        return "已撤销刚才的运动记录：" + detail

    def _undo_note(self, session_id: str, window: Optional[int]) -> Optional[str]:
        deleted = self.store.delete_last_note(within_seconds=window)
        if not deleted:
            return None
        self.store.clear_mood_pending(session_id)
        return f"已撤销刚才的想法：{deleted['title']}（已移到废纸篓，30 天内可在网页恢复）"

    def _handle_recategorize(self, text: str) -> Optional[str]:
        m = _RECAT_RE.match(text.strip())
        if not m:
            return None
        cat = m.group("cat").strip()
        note = self.store.recategorize_last_note(cat)
        if not note:
            return "最近没有可改分类的想法。"
        return f"已把「{note['title']}」改到「{cat}」。"

    def _handle_exercise(self, text: str) -> Tuple[str, bool]:
        try:
            session = parse_exercise(text, llm=self.llm)
        except ValueError:
            return ("我还没从这句话里拆出明确运动记录。你可以试试：今天跑步5公里 32分钟。", False)
        self.store.add_exercise_session(session, raw_text=text, ts=session["ts"])
        reply = format_exercise_confirmation(session)
        mood = self._companion_mood(text)  # 运动+心情可叠加
        if mood:
            reply += f"\n顺手记下心情：{mood}"
        return (reply, True)

    def _companion_mood(self, text: str) -> Optional[str]:
        """If an exercise message also states a mood, log it too (don't overwrite today's)."""
        if self.store.get_today_mood():
            return None
        emotion, note = _match_canonical(text), ""  # deterministic 开心/爽/焦虑/难过…
        if not emotion and self.llm and self.llm.is_configured:
            # classify the non-exercise remainder (e.g. "好累" after the run)
            tail = "，".join(
                s for s in re.split(r"[，,。；;\n]+", text)
                if s.strip() and not looks_like_exercise_text(s)
            )
            if tail.strip():
                parsed = classify_mood(tail, self.llm)
                if parsed:
                    emotion, note = parsed["emotion"], parsed.get("note", "")
        if not emotion:
            return None
        self.store.add_mood(emotion, note, source="auto")
        return emotion

    # ---------- mood ----------
    def _handle_mood(self, session_id: str, text: str) -> str:
        if is_mood_prompt_request(text):
            self.store.set_mood_prompted(session_id, date.today().isoformat(), pending=1)
            return MOOD_PICKER_PROMPT
        parsed = parse_mood(text, self.llm)
        if not parsed:
            return "想记录心情的话，可以说：开心 / 平静 / 焦虑 / 难过 / 恐惧 / 很难描述，或直接说说今天的感受。"
        self.store.add_mood(parsed["emotion"], parsed.get("note", ""), source="manual")
        self.store.clear_mood_pending(session_id)
        return format_mood_confirmation(parsed["emotion"], parsed.get("note", ""))

    def _capture_mood_answer(self, session_id: str, text: str) -> Optional[str]:
        """If we proactively asked for mood, capture this reply only when it's really a mood.

        Anything that isn't a mood statement (greetings, thanks, a new command, an
        exercise, a question…) declines the prompt and falls through to normal handling,
        rather than being silently logged as a junk 自定义 mood.
        """
        if not self.store.get_mood_state(session_id).get("pending"):
            return None
        if is_mood_prompt_request(text):
            return MOOD_PICKER_PROMPT
        # obvious non-mood actions: stop asking and let normal handling take over
        if looks_like_exercise_text(text) or looks_like_exercise_undo(text):
            self.store.clear_mood_pending(session_id)
            return None
        # parse_mood maps a real feeling to a canonical emotion (LLM-aware) and returns
        # None for non-feelings (the classifier's 非情绪 escape / offline alias miss)
        parsed = parse_mood(text, self.llm)
        if parsed is None:
            self.store.clear_mood_pending(session_id)
            return None
        self.store.add_mood(parsed["emotion"], parsed.get("note", ""), source="prompted")
        self.store.clear_mood_pending(session_id)
        return format_mood_confirmation(parsed["emotion"], parsed.get("note", ""))

    def _maybe_append_mood_prompt(self, session_id: str, reply: str, recorded: bool) -> str:
        """After a successful record, ask about mood once a day (skip if already logged/asked)."""
        if not recorded:
            return reply
        today = date.today().isoformat()
        if self.store.get_today_mood():
            return reply
        if self.store.get_mood_state(session_id).get("prompted_date") == today:
            return reply
        self.store.set_mood_prompted(session_id, today, pending=1)
        return f"{reply}\n\n{MOOD_PROMPT}"

    def _handle_query(self, text: str) -> str:
        if "想法" in text or "笔记" in text:
            notes = self.store.list_notes(limit=5)
            if not notes:
                return "还没有已保存的想法笔记。"
            lines = [
                f"{index + 1}. {note['title']} [{note['category']}]"
                for index, note in enumerate(notes)
            ]
            return "最近的想法笔记：\n" + "\n".join(lines)

        if "同步" in text and any(alias in text for alias in FOCUS_ALIASES):
            sync_result = self.focus_sync.sync()
            if not sync_result.ok:
                return self._focus_sync_error_reply(sync_result)
            month_focus = self.store.get_focus_month_summary(target=date.today())
            if month_focus["total_focus_seconds"] <= 0 and month_focus["total_trees"] <= 0:
                return (
                    f"已同步番茄钟记录 {sync_result.imported_days} 天。\n"
                    f"最近同步到 {sync_result.last_day or '历史数据'}，但本月暂时还没有专注记录。"
                )
            return (
                f"已同步番茄钟记录 {sync_result.imported_days} 天。\n"
                f"本月专注 {format_focus_duration(month_focus['total_focus_seconds'])}"
                f"，完成 {month_focus['total_trees']} 个番茄。"
            )

        has_focus = any(alias in text for alias in FOCUS_ALIASES)
        has_exercise = any(alias in text for alias in EXERCISE_ALIASES)
        if has_focus and has_exercise:
            sync_result = self.focus_sync.sync()
            if not sync_result.ok:
                return "\n".join([self._exercise_summary_reply(text), self._focus_sync_error_reply(sync_result)])
            return "\n".join([self._exercise_summary_reply(text), self._focus_summary_reply(text)])
        if any(alias in text for alias in FOCUS_ALIASES):
            sync_result = self.focus_sync.sync()
            if not sync_result.ok:
                return self._focus_sync_error_reply(sync_result)
            return self._focus_summary_reply(text)

        if has_exercise:
            return self._exercise_summary_reply(text)

        return "\n".join([self._exercise_summary_reply(text), self._focus_summary_reply(text)])

    def _exercise_summary_reply(self, text: str) -> str:
        range_name, label = self._detect_range(text)
        summary = self.store.get_exercise_range_summary(range_name, date.today())
        if summary["count"] == 0:
            return f"{label}还没有运动记录。"
        if range_name == "month":
            breakdown = self.store.get_exercise_activity_breakdown(date.today())
            top = "；".join(
                f"{row['activity']} {row['total_duration_minutes']}分钟"
                for row in breakdown[:3]
            )
            return (
                f"{label}运动 {summary['count']} 次，共 {summary['total_duration_minutes']} 分钟"
                f"，累计 {summary['total_distance_km']:g} 公里。\n"
                f"主要项目：{top}"
            )
        return (
            f"{label}运动 {summary['count']} 次，共 {summary['total_duration_minutes']} 分钟"
            + (f"，累计 {summary['total_distance_km']:g} 公里。" if summary['total_distance_km'] > 0 else "。")
        )

    def _focus_summary_reply(self, text: str) -> str:
        range_name, label = self._detect_range(text)
        summary = self.store.get_focus_range_summary(range_name, date.today())
        meta = self.store.get_focus_sync_meta()
        if summary["total_focus_seconds"] <= 0 and summary["total_trees"] <= 0:
            if meta["synced_days"] > 0:
                return f"{label}暂时没有专注记录。最近同步覆盖到 {meta['last_day'] or '历史数据'}。"
            return f"{label}还没有同步到专注记录。"
        return (
            f"{label}专注 {format_focus_duration(summary['total_focus_seconds'])}"
            f"，完成 {summary['total_trees']} 个番茄，活跃 {summary['days_with_focus']} 天。"
        )

    @staticmethod
    def _focus_sync_error_reply(sync_result) -> str:
        base = f"番茄钟同步失败：{sync_result.error}。"
        if sync_result.used_cached_data and sync_result.last_synced_at:
            return (
                f"{base}\n"
                f"当前先沿用上次同步的数据（{sync_result.last_synced_at}，共 {sync_result.synced_days} 天）。\n"
                f"路径：{sync_result.source_path}"
            )
        return f"{base}\n路径：{sync_result.source_path}"

    @staticmethod
    def _detect_range(text: str) -> Tuple[str, str]:
        if "今天" in text:
            return "day", "今天"
        if "这周" in text or "本周" in text:
            return "week", "本周"
        return "month", "本月"

    def _handle_chat(self, text: str) -> str:
        if self.llm.is_configured:
            try:
                return self.llm.chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "你是一个本地微信助手，擅长帮助用户记录运动、同步专注数据、记录想法。"
                                "如果用户只是闲聊，也请简洁自然地回复。"
                            ),
                        },
                        {"role": "user", "content": text},
                    ],
                    json_mode=False,
                    temperature=0.6,
                    max_tokens=200,
                )
            except LLMError:
                pass

        return "我现在更擅长三件事：记运动、看专注、记想法。你可以直接发一句试试。"
