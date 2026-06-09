from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from config import Settings
from core.store import Store


@dataclass
class SyncResult:
    ok: bool
    source_path: str
    file_exists: bool
    synced_days: int
    imported_days: int
    last_day: Optional[str] = None
    error: Optional[str] = None
    last_synced_at: Optional[str] = None
    used_cached_data: bool = False


@dataclass
class SourceCandidate:
    path: Path
    payload: Dict
    latest_day: Optional[str]
    days_count: int
    mtime: float


class PomodoroSyncService:
    def __init__(self, store: Store, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    def sync(self) -> SyncResult:
        path = self._resolve_source_path()
        if not path.exists():
            meta = self.store.get_focus_sync_meta()
            return SyncResult(
                ok=False,
                source_path=str(path),
                file_exists=False,
                synced_days=meta["synced_days"],
                imported_days=0,
                last_day=meta["last_day"],
                last_synced_at=meta["last_synced_at"],
                error="未找到番茄钟 settings.json",
                used_cached_data=meta["synced_days"] > 0,
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            meta = self.store.get_focus_sync_meta()
            return SyncResult(
                ok=False,
                source_path=str(path),
                file_exists=True,
                synced_days=meta["synced_days"],
                imported_days=0,
                last_day=meta["last_day"],
                last_synced_at=meta["last_synced_at"],
                error=f"番茄钟数据文件读取失败：{exc}",
                used_cached_data=meta["synced_days"] > 0,
            )
        except json.JSONDecodeError as exc:
            meta = self.store.get_focus_sync_meta()
            return SyncResult(
                ok=False,
                source_path=str(path),
                file_exists=True,
                synced_days=meta["synced_days"],
                imported_days=0,
                last_day=meta["last_day"],
                last_synced_at=meta["last_synced_at"],
                error=f"番茄钟数据文件格式异常（第 {exc.lineno} 行，第 {exc.colno} 列）",
                used_cached_data=meta["synced_days"] > 0,
            )
        return self._sync_payload(payload, path)

    def _sync_payload(self, payload: Dict, path: Path) -> SyncResult:
        projects = {
            item.get("id"): item.get("name", item.get("id", "未分类"))
            for item in payload.get("projects", [])
            if isinstance(item, dict) and item.get("id")
        }
        days = payload.get("forestStats", {}).get("days", {})
        normalized: List[Dict] = []
        for day, value in days.items():
            if not isinstance(value, dict):
                continue
            focus_seconds = int(value.get("focusSeconds", 0) or 0)
            trees_completed = int(value.get("treesCompleted", 0) or 0)
            if focus_seconds <= 0 and trees_completed <= 0:
                continue
            raw_projects = value.get("projects", {}) or {}
            mapped_projects = {}
            for project_id, stats in raw_projects.items():
                if not isinstance(stats, dict):
                    continue
                mapped_projects[projects.get(project_id, project_id)] = {
                    "focus_seconds": int(stats.get("focusSeconds", 0) or 0),
                    "trees_completed": int(stats.get("treesCompleted", 0) or 0),
                }
            normalized.append(
                {
                    "day": day,
                    "focus_seconds": focus_seconds,
                    "trees_completed": trees_completed,
                    "projects": mapped_projects,
                }
            )
        imported_days = self.store.replace_focus_days(normalized, str(path))
        meta = self.store.get_focus_sync_meta()
        return SyncResult(
            ok=True,
            source_path=str(path),
            file_exists=True,
            synced_days=meta["synced_days"],
            imported_days=imported_days,
            last_day=meta["last_day"],
            last_synced_at=meta["last_synced_at"],
        )

    def _resolve_source_path(self) -> Path:
        configured = self.settings.pomodoro_settings_path
        candidates = self._load_candidates()
        if candidates:
            best = max(
                candidates,
                key=lambda item: (
                    item.latest_day or "",
                    item.days_count,
                    item.mtime,
                ),
            )
            return best.path
        return configured

    def _load_candidates(self) -> List[SourceCandidate]:
        candidates: List[Path] = []
        seen = set()

        def add(path: Path) -> None:
            path = Path(path)
            key = str(path)
            if key in seen:
                return
            seen.add(key)
            candidates.append(path)

        configured = self.settings.pomodoro_settings_path
        add(configured)
        if len(configured.parents) >= 2:
            root = configured.parents[1]
            # never scan the filesystem root (happens when the configured path is shallow)
            if root.exists() and root != Path(root.anchor):
                try:
                    for path in root.glob("*/settings.json"):
                        path_str = str(path).lower()
                        if "pomodoro" in path_str or "sticker" in path_str:
                            add(path)
                except OSError:
                    pass

        loaded: List[SourceCandidate] = []
        for path in candidates:
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            days = payload.get("forestStats", {}).get("days", {})
            if not isinstance(days, dict):
                continue
            loaded.append(
                SourceCandidate(
                    path=path,
                    payload=payload,
                    latest_day=max(days) if days else None,
                    days_count=len(days),
                    mtime=path.stat().st_mtime,
                )
            )
        return loaded

    @staticmethod
    def status_dict(result: SyncResult) -> Dict:
        return {
            "ok": result.ok,
            "source_path": result.source_path,
            "file_exists": result.file_exists,
            "synced_days": result.synced_days,
            "imported_days": result.imported_days,
            "last_day": result.last_day,
            "last_synced_at": result.last_synced_at,
            "error": result.error,
            "used_cached_data": result.used_cached_data,
        }


def format_focus_duration(seconds: int) -> str:
    total_minutes = max(int(seconds), 0) // 60
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours == 0:
        return f"{minutes}分钟"
    if minutes == 0:
        return f"{hours}小时"
    return f"{hours}小时{minutes}分钟"
