#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "还没有检测到本地虚拟环境。"
  echo "请先运行：bash \"$ROOT_DIR/tools/install_macos.sh\""
  exit 1
fi

port="$(".venv/bin/python" - <<'PY'
import json
from pathlib import Path

path = Path("config.json")
if path.exists():
    data = json.loads(path.read_text(encoding="utf-8"))
    print(data.get("dashboard_port", 9900))
else:
    print(9900)
PY
)"

echo "正在启动本地看板：http://127.0.0.1:${port}"
open "http://127.0.0.1:${port}" >/dev/null 2>&1 || true
exec ".venv/bin/python" dashboard/app.py
