from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import load_settings


class ConfigLoadTest(unittest.TestCase):
    def test_prefers_generic_llm_config_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "llm_api_key": "generic-key",
                        "llm_base_url": "https://example.com/v1",
                        "llm_model": "demo-model",
                        "data_dir": "sandbox-data",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(config_path=config_path)

            self.assertEqual(settings.deepseek_api_key, "generic-key")
            self.assertEqual(settings.deepseek_base_url, "https://example.com/v1")
            self.assertEqual(settings.deepseek_model, "demo-model")
            self.assertEqual(settings.chat_endpoint, "https://example.com/v1/chat/completions")
            self.assertEqual(settings.data_dir.name, "sandbox-data")

    def test_generic_env_overrides_legacy_and_file_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "llm_api_key": "file-generic",
                        "deepseek_api_key": "file-legacy",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "LLM_API_KEY": "env-generic",
                    "DEEPSEEK_API_KEY": "env-legacy",
                },
                clear=True,
            ):
                settings = load_settings(config_path=config_path)

            self.assertEqual(settings.deepseek_api_key, "env-generic")


if __name__ == "__main__":
    unittest.main()
