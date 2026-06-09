from __future__ import annotations

import calendar
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from config import Settings


class Store:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._initialize()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.settings.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    item TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    raw TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS exercise_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    activity TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    distance_km REAL,
                    calories INTEGER,
                    source TEXT NOT NULL,
                    raw TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS focus_days (
                    day TEXT PRIMARY KEY,
                    focus_seconds INTEGER NOT NULL,
                    trees_completed INTEGER NOT NULL,
                    projects_json TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    synced_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS note_sessions (
                    session_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    messages_json TEXT NOT NULL,
                    meta_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mood_logs (
                    day TEXT PRIMARY KEY,
                    emotion TEXT NOT NULL,
                    note TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mood_state (
                    session_id TEXT PRIMARY KEY,
                    prompted_date TEXT,
                    pending INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _month_bounds(target: Optional[date] = None) -> Tuple[date, date]:
        target = target or date.today()
        start = target.replace(day=1)
        if target.month == 12:
            next_month = date(target.year + 1, 1, 1)
        else:
            next_month = date(target.year, target.month + 1, 1)
        return start, next_month - timedelta(days=1)

    def add_exercise_session(self, session: Dict, raw_text: str, ts: Optional[str] = None) -> int:
        created_at = datetime.now().isoformat(timespec="seconds")
        session_ts = ts or session.get("ts") or date.today().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO exercise_sessions (
                    ts, activity, duration_minutes, distance_km, calories, source, raw, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_ts,
                    session["activity"],
                    int(session["duration_minutes"]),
                    session.get("distance_km"),
                    session.get("calories"),
                    session.get("source", "manual"),
                    raw_text,
                    created_at,
                ),
            )
        return 1

    def get_exercise_month_summary(self, target: Optional[date] = None) -> Dict:
        start, end = self._month_bounds(target)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS count,
                    COUNT(DISTINCT ts) AS active_days,
                    COALESCE(SUM(duration_minutes), 0) AS total_duration_minutes,
                    ROUND(COALESCE(SUM(distance_km), 0), 2) AS total_distance_km
                FROM exercise_sessions
                WHERE ts >= ? AND ts <= ?
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchone()
        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "count": int(row["count"] or 0),
            "active_days": int(row["active_days"] or 0),
            "total_duration_minutes": int(row["total_duration_minutes"] or 0),
            "total_distance_km": float(row["total_distance_km"] or 0),
        }

    def get_exercise_activity_breakdown(self, target: Optional[date] = None) -> List[Dict]:
        start, end = self._month_bounds(target)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    activity,
                    COUNT(*) AS count,
                    COALESCE(SUM(duration_minutes), 0) AS total_duration_minutes,
                    ROUND(COALESCE(SUM(distance_km), 0), 2) AS total_distance_km
                FROM exercise_sessions
                WHERE ts >= ? AND ts <= ?
                GROUP BY activity
                ORDER BY total_duration_minutes DESC, count DESC, activity ASC
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_exercise_daily_minutes(self, target: Optional[date] = None) -> List[Dict]:
        start, end = self._month_bounds(target)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    ts,
                    COALESCE(SUM(duration_minutes), 0) AS total_minutes,
                    ROUND(COALESCE(SUM(distance_km), 0), 2) AS total_distance_km
                FROM exercise_sessions
                WHERE ts >= ? AND ts <= ?
                GROUP BY ts
                ORDER BY ts ASC
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        daily = {row["ts"]: dict(row) for row in rows}
        out: List[Dict] = []
        day = start
        while day <= end:
            iso = day.isoformat()
            out.append(daily.get(iso, {"ts": iso, "total_minutes": 0, "total_distance_km": 0.0}))
            day += timedelta(days=1)
        return out

    def list_recent_exercise_sessions(self, limit: int = 8) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ts, activity, duration_minutes, distance_km, calories, source, raw
                FROM exercise_sessions
                ORDER BY ts DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_exercise_range_summary(self, range_name: str = "month", today_value: Optional[date] = None) -> Dict:
        today_value = today_value or date.today()
        if range_name == "day":
            start = end = today_value
        elif range_name == "week":
            start = today_value - timedelta(days=today_value.weekday())
            end = today_value
        else:
            start, end = self._month_bounds(today_value)
            end = min(end, today_value)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS count,
                    COALESCE(SUM(duration_minutes), 0) AS total_duration_minutes,
                    ROUND(COALESCE(SUM(distance_km), 0), 2) AS total_distance_km
                FROM exercise_sessions
                WHERE ts >= ? AND ts <= ?
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchone()
        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "count": int(row["count"] or 0),
            "total_duration_minutes": int(row["total_duration_minutes"] or 0),
            "total_distance_km": float(row["total_distance_km"] or 0),
        }

    def replace_focus_days(self, days: Iterable[Dict], source_path: str) -> int:
        synced_at = datetime.now().isoformat(timespec="seconds")
        rows = [
            (
                item["day"],
                int(item["focus_seconds"]),
                int(item["trees_completed"]),
                json.dumps(item.get("projects", {}), ensure_ascii=False),
                source_path,
                synced_at,
            )
            for item in days
        ]
        with self._connect() as conn:
            conn.execute("DELETE FROM focus_days")
            if rows:
                conn.executemany(
                    """
                    INSERT INTO focus_days (
                        day, focus_seconds, trees_completed, projects_json, source_path, synced_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
        return len(rows)

    def get_focus_sync_meta(self) -> Dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS synced_days,
                    MIN(day) AS first_day,
                    MAX(day) AS last_day,
                    MAX(synced_at) AS last_synced_at,
                    MAX(source_path) AS source_path
                FROM focus_days
                """
            ).fetchone()
        return {
            "synced_days": int(row["synced_days"] or 0),
            "first_day": row["first_day"],
            "last_day": row["last_day"],
            "last_synced_at": row["last_synced_at"],
            "source_path": row["source_path"],
        }

    def get_focus_month_summary(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        target: Optional[date] = None,
    ) -> Dict:
        if target is None:
            if year is not None and month is not None:
                target = date(year, month, 1)
            else:
                target = date.today()
        start, end = self._month_bounds(target)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS days_with_focus,
                    COALESCE(SUM(focus_seconds), 0) AS total_focus_seconds,
                    COALESCE(SUM(trees_completed), 0) AS total_trees
                FROM focus_days
                WHERE day >= ? AND day <= ?
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchone()
        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days_with_focus": int(row["days_with_focus"] or 0),
            "total_focus_seconds": int(row["total_focus_seconds"] or 0),
            "total_trees": int(row["total_trees"] or 0),
        }

    def get_focus_range_summary(self, range_name: str = "month", today_value: Optional[date] = None) -> Dict:
        today_value = today_value or date.today()
        if range_name == "day":
            start = end = today_value
        elif range_name == "week":
            start = today_value - timedelta(days=today_value.weekday())
            end = today_value
        else:
            start, end = self._month_bounds(today_value)
            end = min(end, today_value)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS days_with_focus,
                    COALESCE(SUM(focus_seconds), 0) AS total_focus_seconds,
                    COALESCE(SUM(trees_completed), 0) AS total_trees
                FROM focus_days
                WHERE day >= ? AND day <= ?
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchone()
        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days_with_focus": int(row["days_with_focus"] or 0),
            "total_focus_seconds": int(row["total_focus_seconds"] or 0),
            "total_trees": int(row["total_trees"] or 0),
        }

    def get_focus_daily_seconds(self, target: Optional[date] = None) -> List[Dict]:
        start, end = self._month_bounds(target)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT day AS ts, focus_seconds, trees_completed
                FROM focus_days
                WHERE day >= ? AND day <= ?
                ORDER BY day ASC
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        daily = {row["ts"]: dict(row) for row in rows}
        out: List[Dict] = []
        day = start
        while day <= end:
            iso = day.isoformat()
            out.append(daily.get(iso, {"ts": iso, "focus_seconds": 0, "trees_completed": 0}))
            day += timedelta(days=1)
        return out

    def get_recent_focus_days(self, limit: int = 7) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT day AS ts, focus_seconds, trees_completed, projects_json, synced_at
                FROM focus_days
                ORDER BY day DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["projects"] = json.loads(item.pop("projects_json"))
            out.append(item)
        return out

    def get_focus_project_breakdown(self, target: Optional[date] = None) -> List[Dict]:
        start, end = self._month_bounds(target)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT day, projects_json
                FROM focus_days
                WHERE day >= ? AND day <= ?
                ORDER BY day ASC
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        projects: Dict[str, Dict] = {}
        for row in rows:
            payload = json.loads(row["projects_json"])
            for project, stats in payload.items():
                current = projects.setdefault(
                    project,
                    {"project": project, "focus_seconds": 0, "trees_completed": 0},
                )
                current["focus_seconds"] += int(stats.get("focus_seconds", 0) or 0)
                current["trees_completed"] += int(stats.get("trees_completed", 0) or 0)
        return sorted(
            projects.values(),
            key=lambda item: (item["focus_seconds"], item["trees_completed"], item["project"]),
            reverse=True,
        )

    def get_exercise_heatmap_weeks(self, target: Optional[date] = None, week_count: int = 12) -> List[List[Dict]]:
        return self._build_heatmap_weeks(
            daily_rows=self.get_exercise_daily_minutes(target),
            target=target,
            week_count=week_count,
            key="total_minutes",
            level_fn=lambda value: 4 if value >= 90 else 3 if value >= 45 else 2 if value >= 20 else 1 if value > 0 else 0,
        )

    def get_focus_heatmap_weeks(self, target: Optional[date] = None, week_count: int = 12) -> List[List[Dict]]:
        return self._build_heatmap_weeks(
            daily_rows=self.get_focus_daily_seconds(target),
            target=target,
            week_count=week_count,
            key="focus_seconds",
            level_fn=lambda value: 4 if value >= 6000 else 3 if value >= 3000 else 2 if value >= 1500 else 1 if value > 0 else 0,
        )

    def get_available_months(self) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ym FROM (
                    SELECT DISTINCT substr(ts, 1, 7) AS ym FROM exercise_sessions
                    UNION
                    SELECT DISTINCT substr(day, 1, 7) AS ym FROM focus_days
                    UNION
                    SELECT DISTINCT substr(day, 1, 7) AS ym FROM mood_logs
                )
                WHERE ym IS NOT NULL AND ym != ''
                ORDER BY ym DESC
                """
            ).fetchall()
        months = [row["ym"] for row in rows]
        current = date.today().strftime("%Y-%m")
        if current not in months:
            months.insert(0, current)
        return months

    @staticmethod
    def _build_heatmap_weeks(
        daily_rows: List[Dict],
        target: Optional[date],
        week_count: int,
        key: str,
        level_fn,
    ) -> List[List[Dict]]:
        target = target or date.today()
        start, end = Store._month_bounds(target)
        today_value = date.today()
        if (target.year, target.month) == (today_value.year, today_value.month):
            anchor = min(end, today_value)
        else:
            anchor = end
        start_of_week = anchor - timedelta(days=anchor.weekday())
        start_grid = start_of_week - timedelta(days=(week_count - 1) * 7)
        totals = {row["ts"]: row for row in daily_rows}
        weeks: List[List[Dict]] = []
        for week_index in range(week_count):
            week: List[Dict] = []
            for day_index in range(7):
                current = start_grid + timedelta(days=week_index * 7 + day_index)
                iso = current.isoformat()
                row = totals.get(iso, {})
                value = row.get(key, 0) or 0
                week.append(
                    {
                        "date": iso,
                        "value": value,
                        "level": level_fn(value),
                        "in_month": current.month == target.month and current.year == target.year,
                        "is_future": current > anchor,
                    }
                )
            weeks.append(week)
        return weeks

    # ---------- rolling-window (today-anchored, independent of selected month) ----------
    @staticmethod
    def _rolling_window(weeks: int = 12) -> Tuple[date, date]:
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        start_grid = start_of_week - timedelta(days=(weeks - 1) * 7)
        return start_grid, today

    @staticmethod
    def _heatmap_grid(start_grid: date, weeks: int, today: date, value_map: Dict[str, float], level_fn) -> List[List[Dict]]:
        out: List[List[Dict]] = []
        for week_index in range(weeks):
            column: List[Dict] = []
            for day_index in range(7):
                current = start_grid + timedelta(days=week_index * 7 + day_index)
                iso = current.isoformat()
                value = value_map.get(iso, 0) or 0
                column.append(
                    {
                        "date": iso,
                        "value": value,
                        "level": level_fn(value),
                        "is_future": current > today,
                    }
                )
            out.append(column)
        return out

    def get_exercise_heatmap_rolling(self, weeks: int = 12) -> List[List[Dict]]:
        start_grid, today = self._rolling_window(weeks)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ts, COALESCE(SUM(duration_minutes), 0) AS minutes
                FROM exercise_sessions WHERE ts >= ? AND ts <= ? GROUP BY ts
                """,
                (start_grid.isoformat(), today.isoformat()),
            ).fetchall()
        value_map = {row["ts"]: int(row["minutes"] or 0) for row in rows}
        return self._heatmap_grid(
            start_grid, weeks, today, value_map,
            lambda v: 4 if v >= 90 else 3 if v >= 45 else 2 if v >= 20 else 1 if v > 0 else 0,
        )

    def get_focus_heatmap_rolling(self, weeks: int = 12) -> List[List[Dict]]:
        start_grid, today = self._rolling_window(weeks)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT day AS ts, focus_seconds FROM focus_days WHERE day >= ? AND day <= ?",
                (start_grid.isoformat(), today.isoformat()),
            ).fetchall()
        value_map = {row["ts"]: int(row["focus_seconds"] or 0) for row in rows}
        return self._heatmap_grid(
            start_grid, weeks, today, value_map,
            lambda v: 4 if v >= 6000 else 3 if v >= 3000 else 2 if v >= 1500 else 1 if v > 0 else 0,
        )

    def get_exercise_window_stats(self, weeks: int = 12) -> Dict:
        start_grid, today = self._rolling_window(weeks)
        with self._connect() as conn:
            agg = conn.execute(
                """
                SELECT COUNT(*) AS count,
                       COALESCE(SUM(duration_minutes), 0) AS minutes,
                       ROUND(COALESCE(SUM(distance_km), 0), 2) AS km,
                       COUNT(DISTINCT ts) AS active_days
                FROM exercise_sessions WHERE ts >= ? AND ts <= ?
                """,
                (start_grid.isoformat(), today.isoformat()),
            ).fetchone()
            top = conn.execute(
                """
                SELECT activity FROM exercise_sessions WHERE ts >= ? AND ts <= ?
                GROUP BY activity ORDER BY SUM(duration_minutes) DESC, COUNT(*) DESC LIMIT 1
                """,
                (start_grid.isoformat(), today.isoformat()),
            ).fetchone()
        return {
            "start_date": start_grid.isoformat(),
            "end_date": today.isoformat(),
            "weeks": weeks,
            "count": int(agg["count"] or 0),
            "total_duration_minutes": int(agg["minutes"] or 0),
            "total_distance_km": float(agg["km"] or 0),
            "active_days": int(agg["active_days"] or 0),
            "top_activity": top["activity"] if top else None,
        }

    def get_focus_window_stats(self, weeks: int = 12) -> Dict:
        start_grid, today = self._rolling_window(weeks)
        with self._connect() as conn:
            agg = conn.execute(
                """
                SELECT COUNT(*) AS days,
                       COALESCE(SUM(focus_seconds), 0) AS secs,
                       COALESCE(SUM(trees_completed), 0) AS trees
                FROM focus_days WHERE day >= ? AND day <= ?
                """,
                (start_grid.isoformat(), today.isoformat()),
            ).fetchone()
        return {
            "start_date": start_grid.isoformat(),
            "end_date": today.isoformat(),
            "weeks": weeks,
            "days_with_focus": int(agg["days"] or 0),
            "total_focus_seconds": int(agg["secs"] or 0),
            "total_trees": int(agg["trees"] or 0),
        }

    # ---------- mood (one row per day, re-logging overwrites) ----------
    def add_mood(self, emotion: str, note: str = "", source: str = "manual", day: Optional[str] = None) -> str:
        day = day or date.today().isoformat()
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mood_logs (day, emotion, note, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET
                    emotion = excluded.emotion,
                    note = excluded.note,
                    source = excluded.source,
                    created_at = excluded.created_at
                """,
                (day, emotion, note or "", source, created_at),
            )
        return day

    def get_today_mood(self, day: Optional[str] = None) -> Optional[Dict]:
        day = day or date.today().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT day, emotion, note, source, created_at FROM mood_logs WHERE day = ?",
                (day,),
            ).fetchone()
        return dict(row) if row else None

    def get_mood_heatmap_rolling(self, weeks: int = 12) -> List[List[Dict]]:
        from core.mood import emotion_color  # local import to avoid a cycle

        start_grid, today = self._rolling_window(weeks)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT day, emotion FROM mood_logs WHERE day >= ? AND day <= ?",
                (start_grid.isoformat(), today.isoformat()),
            ).fetchall()
        by_day = {row["day"]: row["emotion"] for row in rows}

        out: List[List[Dict]] = []
        for week_index in range(weeks):
            column: List[Dict] = []
            for day_index in range(7):
                current = start_grid + timedelta(days=week_index * 7 + day_index)
                iso = current.isoformat()
                emotion = by_day.get(iso)
                column.append(
                    {
                        "date": iso,
                        "emotion": emotion,
                        "color": emotion_color(emotion) if emotion else None,
                        "is_future": current > today,
                    }
                )
            out.append(column)
        return out

    def get_mood_window_stats(self, weeks: int = 12) -> Dict:
        from core.mood import POSITIVE_KEYS

        start_grid, today = self._rolling_window(weeks)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT emotion, COUNT(*) AS count FROM mood_logs WHERE day >= ? AND day <= ? GROUP BY emotion",
                (start_grid.isoformat(), today.isoformat()),
            ).fetchall()
        counts = {row["emotion"]: int(row["count"]) for row in rows}
        logged_days = sum(counts.values())
        top_emotion = max(counts, key=counts.get) if counts else None
        positive_days = sum(count for emo, count in counts.items() if emo in POSITIVE_KEYS)
        positive_ratio = round(positive_days / logged_days, 4) if logged_days else 0.0
        return {
            "start_date": start_grid.isoformat(),
            "end_date": today.isoformat(),
            "weeks": weeks,
            "logged_days": logged_days,
            "top_emotion": top_emotion,
            "positive_ratio": positive_ratio,
        }

    def get_mood_distribution(self, target: Optional[date] = None) -> List[Dict]:
        from core.mood import EMOTION_BY_KEY, emotion_color

        start, end = self._month_bounds(target)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT emotion, COUNT(*) AS count
                FROM mood_logs WHERE day >= ? AND day <= ?
                GROUP BY emotion ORDER BY count DESC
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [
            {
                "emotion": row["emotion"],
                "count": int(row["count"]),
                "color": emotion_color(row["emotion"]),
                "valence": EMOTION_BY_KEY.get(row["emotion"], {}).get("valence", "中性"),
            }
            for row in rows
        ]

    def get_mood_calendar_month(self, target: Optional[date] = None) -> Dict:
        from core.mood import EMOTION_BY_KEY, emotion_color

        target = (target or date.today()).replace(day=1)
        start, end = self._month_bounds(target)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT day, emotion, note, source, created_at
                FROM mood_logs
                WHERE day >= ? AND day <= ?
                ORDER BY day ASC
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()

        by_day = {row["day"]: dict(row) for row in rows}
        counts: Dict[str, int] = {}
        noted_days = 0
        for row in rows:
            emotion = row["emotion"]
            counts[emotion] = counts.get(emotion, 0) + 1
            if (row["note"] or "").strip():
                noted_days += 1

        weeks: List[List[Dict]] = []
        cal = calendar.Calendar(firstweekday=6)
        for week in cal.monthdatescalendar(target.year, target.month):
            cells: List[Dict] = []
            for current in week:
                iso = current.isoformat()
                entry = by_day.get(iso)
                emotion = entry["emotion"] if entry else None
                note = (entry["note"] if entry else "") or ""
                cells.append(
                    {
                        "date": iso,
                        "day": current.day,
                        "in_month": current.month == target.month and current.year == target.year,
                        "is_today": current == date.today(),
                        "is_future": current > date.today(),
                        "emotion": emotion,
                        "note": note,
                        "has_note": bool(note.strip()),
                        "color": emotion_color(emotion) if emotion else None,
                    }
                )
            weeks.append(cells)

        top_emotion = max(counts, key=counts.get) if counts else None
        logged_days = len(rows)
        distribution = [
            {
                "emotion": emotion,
                "count": count,
                "ratio": round(count / logged_days, 4) if logged_days else 0.0,
                "color": emotion_color(emotion),
                "valence": EMOTION_BY_KEY.get(emotion, {}).get("valence", "中性"),
            }
            for emotion, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        return {
            "month": target.strftime("%Y-%m"),
            "weeks": weeks,
            "logged_days": logged_days,
            "noted_days": noted_days,
            "top_emotion": top_emotion,
            "days_in_month": end.day,
            "distribution": distribution,
        }

    # ---------- mood prompt state (per session) ----------
    def get_mood_state(self, session_id: str) -> Dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT session_id, prompted_date, pending FROM mood_state WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return {"session_id": session_id, "prompted_date": None, "pending": 0}
        data = dict(row)
        data["pending"] = int(data["pending"] or 0)
        return data

    def set_mood_prompted(self, session_id: str, prompted_date: str, pending: int = 1) -> None:
        updated_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mood_state (session_id, prompted_date, pending, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    prompted_date = excluded.prompted_date,
                    pending = excluded.pending,
                    updated_at = excluded.updated_at
                """,
                (session_id, prompted_date, int(pending), updated_at),
            )

    def clear_mood_pending(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE mood_state SET pending = 0 WHERE session_id = ?",
                (session_id,),
            )

    def add_expenses(self, expenses: Iterable[Dict], raw_text: str, ts: Optional[str] = None) -> int:
        created_at = datetime.now().isoformat(timespec="seconds")
        ts = ts or date.today().isoformat()
        rows = [
            (
                ts,
                item["item"],
                float(item["amount"]),
                item["category"],
                raw_text,
                created_at,
            )
            for item in expenses
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO expenses (ts, item, amount, category, raw, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def query_expenses(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict]:
        query = "SELECT ts, item, amount, category, raw, created_at FROM expenses WHERE 1=1"
        params: List = []

        if start_date:
            query += " AND ts >= ?"
            params.append(start_date)
        if end_date:
            query += " AND ts <= ?"
            params.append(end_date)
        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY ts DESC, id DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_month_summary(self, target: Optional[date] = None, category: Optional[str] = None) -> Dict:
        target = target or date.today()
        start = target.replace(day=1)
        if target.month == 12:
            next_month = date(target.year + 1, 1, 1)
        else:
            next_month = date(target.year, target.month + 1, 1)
        end = next_month - timedelta(days=1)

        expenses = self.query_expenses(start.isoformat(), end.isoformat(), category)
        total = round(sum(row["amount"] for row in expenses), 2)
        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "count": len(expenses),
            "total": total,
            "items": expenses,
        }

    def get_category_breakdown(self, target: Optional[date] = None) -> List[Dict]:
        target = target or date.today()
        start = target.replace(day=1).isoformat()
        if target.month == 12:
            next_month = date(target.year + 1, 1, 1)
        else:
            next_month = date(target.year, target.month + 1, 1)
        end = (next_month - timedelta(days=1)).isoformat()

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT category, ROUND(SUM(amount), 2) AS total, COUNT(*) AS count
                FROM expenses
                WHERE ts >= ? AND ts <= ?
                GROUP BY category
                ORDER BY total DESC
                """,
                (start, end),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_daily_totals(self, days: int = 30) -> List[Dict]:
        end = date.today()
        start = end - timedelta(days=days - 1)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ts, ROUND(SUM(amount), 2) AS total
                FROM expenses
                WHERE ts >= ? AND ts <= ?
                GROUP BY ts
                ORDER BY ts ASC
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_month_daily_totals(self, target: Optional[date] = None) -> List[Dict]:
        target = target or date.today()
        start = target.replace(day=1)
        if target.month == 12:
            next_month = date(target.year + 1, 1, 1)
        else:
            next_month = date(target.year, target.month + 1, 1)
        month_end = next_month - timedelta(days=1)

        today = date.today()
        is_current = (target.year, target.month) == (today.year, today.month)
        end_cap = min(month_end, today) if is_current else month_end

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ts, ROUND(SUM(amount), 2) AS total
                FROM expenses
                WHERE ts >= ? AND ts <= ?
                GROUP BY ts
                """,
                (start.isoformat(), end_cap.isoformat()),
            ).fetchall()
        totals = {row["ts"]: row["total"] for row in rows}

        out: List[Dict] = []
        day = start
        while day <= end_cap:
            iso = day.isoformat()
            out.append({"ts": iso, "total": totals.get(iso, 0.0)})
            day += timedelta(days=1)
        return out

    def add_note(self, note: Dict) -> Path:
        category_dir = self.settings.notes_dir / note["category"]
        category_dir.mkdir(parents=True, exist_ok=True)

        safe_title = note["title"].replace("/", "-").replace(":", " ").strip() or "未命名想法"
        stem = f"{date.today().isoformat()}-{safe_title}"
        file_path = category_dir / f"{stem}.md"
        suffix = 2
        while file_path.exists():
            file_path = category_dir / f"{stem}-{suffix}.md"
            suffix += 1
        file_path.write_text(note["markdown"], encoding="utf-8")

        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO notes (title, category, tags, file_path, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    note["title"],
                    note["category"],
                    json.dumps(note["tags"], ensure_ascii=False),
                    str(file_path),
                    created_at,
                ),
            )
        return file_path

    def list_notes(self, limit: int = 20) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, category, tags, file_path, created_at
                FROM notes
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item["tags"])
            result.append(item)
        return result

    def get_note_categories(self) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT category, COUNT(*) AS count
                FROM notes
                GROUP BY category
                ORDER BY count DESC, category ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _build_snippet(content: str, query: str, radius: int = 42) -> Optional[str]:
        if not content or not query:
            return None
        body = content
        if body.startswith("---"):
            end = body.find("---", 3)
            if end != -1:
                body = body[end + 3 :]
        flat = " ".join(body.split())
        low = flat.lower()
        idx = low.find(query)
        if idx == -1:
            return (flat[: radius * 2].strip() or None)
        start = max(0, idx - radius)
        end = min(len(flat), idx + len(query) + radius)
        snippet = flat[start:end].strip()
        if start > 0:
            snippet = "…" + snippet
        if end < len(flat):
            snippet = snippet + "…"
        return snippet

    def search_notes(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 60,
    ) -> List[Dict]:
        sql = "SELECT id, title, category, tags, file_path, created_at FROM notes WHERE 1=1"
        params: List = []
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY id DESC"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        q = (query or "").strip().lower()
        results: List[Dict] = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item["tags"])
            if q:
                meta_hay = " ".join(
                    [item["title"], item["category"], " ".join(item["tags"])]
                ).lower()
                content = ""
                path = Path(item["file_path"])
                if path.exists():
                    try:
                        content = path.read_text(encoding="utf-8")
                    except OSError:
                        content = ""
                if q not in meta_hay and q not in content.lower():
                    continue
                snippet = self._build_snippet(content, q)
                if snippet:
                    item["snippet"] = snippet
            item.pop("file_path", None)
            results.append(item)
            if len(results) >= limit:
                break
        return results

    def get_note_by_id(self, note_id: int) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, category, tags, file_path, created_at
                FROM notes
                WHERE id = ?
                """,
                (note_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["tags"] = json.loads(item["tags"])
        note_path = Path(item["file_path"])
        if note_path.exists():
            item["content"] = note_path.read_text(encoding="utf-8")
        else:
            item["content"] = ""
        return item

    def find_note_by_title(self, title: str) -> Optional[Dict]:
        """Find the earliest note with an exact title match (used to merge book notes)."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, category, tags, file_path, created_at
                FROM notes
                WHERE title = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (title,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["tags"] = json.loads(item["tags"])
        return item

    def append_to_note(self, note_id: int, addition_md: str, extra_tags: Optional[List[str]] = None) -> Path:
        """Append a markdown block to an existing note file and merge in any new tags."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT file_path, tags FROM notes WHERE id = ?", (note_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"note {note_id} not found")
            file_path = Path(row["file_path"])
            existing_tags = json.loads(row["tags"])

            content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
            new_content = content.rstrip() + "\n\n" + addition_md.rstrip() + "\n"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(new_content, encoding="utf-8")

            if extra_tags:
                merged = list(existing_tags)
                for tag in extra_tags:
                    if tag and tag not in merged:
                        merged.append(tag)
                if merged != existing_tags:
                    conn.execute(
                        "UPDATE notes SET tags = ? WHERE id = ?",
                        (json.dumps(merged, ensure_ascii=False), note_id),
                    )
        return file_path

    @staticmethod
    def _rewrite_note_category(content: str, category: str) -> str:
        if not content.startswith("---"):
            return content
        end = content.find("\n---", 3)
        if end == -1:
            return content
        frontmatter = content[: end + 4]
        body = content[end + 4 :]
        updated = re.sub(
            r"^category:\s*.*$",
            f"category: {category}",
            frontmatter,
            count=1,
            flags=re.MULTILINE,
        )
        return updated + body

    def update_note_category(self, note_id: int, category: str) -> Path:
        category = str(category or "").strip()
        if not category:
            raise ValueError("category is required")

        with self._connect() as conn:
            row = conn.execute(
                "SELECT category, file_path FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"note {note_id} not found")

            old_path = Path(row["file_path"])
            new_dir = self.settings.notes_dir / category
            new_dir.mkdir(parents=True, exist_ok=True)

            target_name = old_path.name if old_path.name else f"{note_id}.md"
            new_path = new_dir / target_name
            if old_path.resolve() != new_path.resolve():
                suffix = 2
                while new_path.exists():
                    new_path = new_dir / f"{new_path.stem}-{suffix}{new_path.suffix or '.md'}"
                    suffix += 1

            content = old_path.read_text(encoding="utf-8") if old_path.exists() else ""
            updated_content = self._rewrite_note_category(content, category)
            new_path.write_text(updated_content, encoding="utf-8")
            if old_path.exists() and old_path.resolve() != new_path.resolve():
                old_path.unlink()

            conn.execute(
                "UPDATE notes SET category = ?, file_path = ? WHERE id = ?",
                (category, str(new_path), note_id),
            )
        return new_path

    def get_note_session(self, session_id: str) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, status, messages_json, meta_json, updated_at
                FROM note_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["messages"] = json.loads(data.pop("messages_json"))
        data["meta"] = json.loads(data.pop("meta_json"))
        return data

    def save_note_session(self, session_id: str, status: str, messages: List[Dict], meta: Optional[Dict] = None) -> None:
        meta = meta or {}
        updated_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO note_sessions (session_id, status, messages_json, meta_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    status = excluded.status,
                    messages_json = excluded.messages_json,
                    meta_json = excluded.meta_json,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    status,
                    json.dumps(messages, ensure_ascii=False),
                    json.dumps(meta, ensure_ascii=False),
                    updated_at,
                ),
            )

    def clear_note_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM note_sessions WHERE session_id = ?", (session_id,))
