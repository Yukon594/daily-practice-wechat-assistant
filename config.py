from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Union

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_NOTE_CATEGORIES = ["产品灵感", "生活感悟", "工作", "学习", "其它"]


@dataclass
class Settings:
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    request_timeout: int
    dashboard_port: int
    note_categories: List[str]
    data_dir: Path
    db_path: Path
    notes_dir: Path
    pomodoro_settings_path: Path

    @property
    def chat_endpoint(self) -> str:
        base = self.deepseek_base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


def _read_config_file(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_data_dir(raw_value: Optional[Union[str, Path]]) -> Path:
    if not raw_value:
        return ROOT_DIR / "data"

    path = Path(raw_value)
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def _resolve_pomodoro_settings_path(raw_value: Optional[Union[str, Path]]) -> Path:
    if raw_value:
        path = Path(raw_value).expanduser()
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path

    candidates = [
        Path.home() / "Library/Application Support/com.stickerpomodoro.mac/settings.json",
        Path.home() / "Library/Application Support/com.stickerpomodoro/settings.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _first_non_empty(candidates: Iterable[Optional[str]], default: str = "") -> str:
    for candidate in candidates:
        if candidate is None:
            continue
        value = str(candidate).strip()
        if value:
            return value
    return default


def load_settings(
    config_path: Optional[Path] = None,
    data_dir_override: Optional[Union[str, Path]] = None,
) -> Settings:
    config_path = config_path or ROOT_DIR / "config.json"
    config_data = _read_config_file(config_path)

    configured_data_dir = data_dir_override or os.getenv(
        "ASSISTANT_DATA_DIR",
        config_data.get("data_dir", ""),
    )
    data_dir = _resolve_data_dir(configured_data_dir)
    notes_dir = data_dir / "notes"

    deepseek_api_key = _first_non_empty(
        [
            os.getenv("LLM_API_KEY"),
            os.getenv("DEEPSEEK_API_KEY"),
            config_data.get("llm_api_key"),
            config_data.get("deepseek_api_key"),
        ],
    )
    deepseek_base_url = _first_non_empty(
        [
            os.getenv("LLM_BASE_URL"),
            os.getenv("DEEPSEEK_BASE_URL"),
            config_data.get("llm_base_url"),
            config_data.get("deepseek_base_url"),
        ],
        default="https://api.deepseek.com",
    )
    deepseek_model = _first_non_empty(
        [
            os.getenv("LLM_MODEL"),
            os.getenv("DEEPSEEK_MODEL"),
            config_data.get("llm_model"),
            config_data.get("deepseek_model"),
        ],
        default="deepseek-chat",
    )

    request_timeout = int(
        os.getenv(
            "REQUEST_TIMEOUT",
            config_data.get("request_timeout", 45),
        )
    )
    dashboard_port = int(
        os.getenv(
            "DASHBOARD_PORT",
            config_data.get("dashboard_port", 9900),
        )
    )

    note_categories = config_data.get("note_categories", DEFAULT_NOTE_CATEGORIES)
    if not note_categories:
        note_categories = DEFAULT_NOTE_CATEGORIES
    pomodoro_settings_path = _resolve_pomodoro_settings_path(
        os.getenv(
            "POMODORO_SETTINGS_PATH",
            config_data.get("pomodoro_settings_path", ""),
        )
    )

    settings = Settings(
        deepseek_api_key=deepseek_api_key.strip(),
        deepseek_base_url=deepseek_base_url.strip(),
        deepseek_model=deepseek_model.strip(),
        request_timeout=request_timeout,
        dashboard_port=dashboard_port,
        note_categories=list(note_categories),
        data_dir=data_dir,
        db_path=data_dir / "ledger.db",
        notes_dir=notes_dir,
        pomodoro_settings_path=pomodoro_settings_path,
    )

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.notes_dir.mkdir(parents=True, exist_ok=True)
    for category in settings.note_categories:
        (settings.notes_dir / category).mkdir(parents=True, exist_ok=True)

    return settings
