#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "还没有检测到本地虚拟环境。"
  echo "请先运行：bash \"$ROOT_DIR/tools/install_macos.sh\""
  exit 1
fi

exec ".venv/bin/python" cli.py
