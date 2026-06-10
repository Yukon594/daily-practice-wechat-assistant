from __future__ import annotations

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
    format_mood_confirmation,
    is_mood_prompt_request,
    parse_mood,
)
from core.notes import NotesService
from core.router import classify_intent
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

        cancelled = self.notes.cancel_if_needed(session_id, text)
        if cancelled:
            return cancelled

        if self.notes.has_active_session(session_id):
            reply = self.notes.handle_message(session_id, text)
            return self._maybe_append_mood_prompt(session_id, reply, self.notes.consume_just_saved())

        if looks_like_exercise_undo(text):
            undo_reply = self._handle_exercise_undo(session_id, text)
            if undo_reply is not None:
                return undo_reply

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
            reply = self.notes.handle_message(session_id, text)
            return self._maybe_append_mood_prompt(session_id, reply, self.notes.consume_just_saved())
        if intent == "query":
            return self._handle_query(text)
        return self._handle_chat(text)

    def _handle_exercise_undo(self, session_id: str, text: str) -> Optional[str]:
        # explicit「运动/跑步…」undoes the latest record; a bare「去除/删掉」only undoes
        # one just logged (recency window), so it can't nuke a much older record
        explicit = detect_activity(text) is not None or "运动" in text or "健身" in text
        deleted = self.store.delete_last_exercise(within_seconds=None if explicit else 900)
        if deleted:
            # the just-recorded session triggered a mood prompt; undo cancels that ask too
            self.store.clear_mood_pending(session_id)
            detail = format_exercise_confirmation(deleted).replace("已记录运动：", "", 1)
            return "已撤销刚才的运动记录：" + detail
        if explicit:
            return "最近没有可撤销的运动记录。"
        # a bare「去除/删掉」with nothing recent isn't really an undo — let normal handling take over
        return None

    def _handle_exercise(self, text: str) -> Tuple[str, bool]:
        try:
            session = parse_exercise(text, llm=self.llm)
        except ValueError:
            return ("我还没从这句话里拆出明确运动记录。你可以试试：今天跑步5公里 32分钟。", False)
        self.store.add_exercise_session(session, raw_text=text, ts=session["ts"])
        return (format_exercise_confirmation(session), True)

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
