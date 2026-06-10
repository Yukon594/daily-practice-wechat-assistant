#!/usr/bin/env bash

set -euo pipefail

if command -v openclaw >/dev/null 2>&1; then
  OPENCLAW_BIN="$(command -v openclaw)"
elif [[ -x "$HOME/.openclaw/bin/openclaw" ]]; then
  OPENCLAW_BIN="$HOME/.openclaw/bin/openclaw"
else
  echo "没有找到 openclaw。"
  echo "如果你已经安装过 OpenClaw，请先确认它在 PATH 里，或者确认文件存在："
  echo "$HOME/.openclaw/bin/openclaw"
  exit 1
fi

echo "使用：$OPENCLAW_BIN"
"$OPENCLAW_BIN" gateway status >/dev/null 2>&1 || true
exec "$OPENCLAW_BIN" dashboard
