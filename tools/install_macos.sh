#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$ROOT_DIR" == *:* ]]; then
  cat <<EOF
当前项目目录里包含英文冒号 `:`，Python 会拒绝在这里创建虚拟环境。

当前目录：
$ROOT_DIR

请把项目放到一个不带 `:` 的目录里，例如：
$HOME/daily-practice-wechat-assistant

如果你是用一键安装命令装的新电脑版本，重新运行安装脚本即可。
EOF
  exit 1
fi

if [[ "${OSTYPE:-}" != darwin* ]]; then
  echo "提示：这个脚本主要为 macOS 准备，当前系统是 ${OSTYPE:-unknown}。"
  echo "如果你只是想继续安装，也可以直接回车继续。"
  read -r -p "继续安装吗？[Y/n] " continue_anyway
  continue_anyway="${continue_anyway:-Y}"
  if [[ ! "$continue_anyway" =~ ^[Yy]$ ]]; then
    exit 1
  fi
fi

if ! command -v python3 >/dev/null 2>&1; then
  cat <<'EOF'
没有检测到 python3。

请先安装 Python 3，再重新运行这个脚本。

最简单的方式：
1. 打开 https://www.python.org/downloads/macos/
2. 下载并安装最新版 Python 3
3. 安装完成后重新打开终端
4. 再执行：bash "$HOME/daily-practice-wechat-assistant/tools/install_macos.sh"
EOF
  exit 1
fi

if ! python3 - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 8) else 1)
PY
then
  echo "需要 Python 3.8 或更高版本。当前版本是：$(python3 --version 2>&1)"
  exit 1
fi

echo
echo "==> 1/5 创建虚拟环境"
python3 -m venv .venv

echo
echo "==> 2/5 安装 Python 依赖"
".venv/bin/python" -m pip install --upgrade pip
".venv/bin/python" -m pip install -r requirements.txt

if [[ ! -f config.json ]]; then
  echo
  echo "==> 3/5 生成配置文件 config.json"
  cp config.example.json config.json
else
  echo
  echo "==> 3/5 检测到已有 config.json，保留现有配置"
fi

echo
echo "==> 4/5 配置模型"
echo "直接回车会使用默认值。"

current_provider="$(".venv/bin/python" - <<'PY'
import json
from pathlib import Path
path = Path("config.json")
data = json.loads(path.read_text(encoding="utf-8"))
print(data.get("llm_provider", "deepseek"))
PY
)"
current_base_url="$(".venv/bin/python" - <<'PY'
import json
from pathlib import Path
path = Path("config.json")
data = json.loads(path.read_text(encoding="utf-8"))
print(data.get("llm_base_url", "https://api.deepseek.com"))
PY
)"
current_model="$(".venv/bin/python" - <<'PY'
import json
from pathlib import Path
path = Path("config.json")
data = json.loads(path.read_text(encoding="utf-8"))
print(data.get("llm_model", "deepseek-chat"))
PY
)"
current_key="$(".venv/bin/python" - <<'PY'
import json
from pathlib import Path
path = Path("config.json")
data = json.loads(path.read_text(encoding="utf-8"))
value = data.get("llm_api_key", "")
if value and value != "YOUR_LLM_API_KEY":
    print(value)
PY
)"

read -r -p "模型提供商 [${current_provider:-deepseek}]: " llm_provider
llm_provider="${llm_provider:-${current_provider:-deepseek}}"

if [[ -n "$current_key" ]]; then
  masked_key="${current_key:0:6}******"
  read -r -p "检测到已有 API key (${masked_key})，是否保留？[Y/n] " keep_existing_key
  keep_existing_key="${keep_existing_key:-Y}"
  if [[ "$keep_existing_key" =~ ^[Yy]$ ]]; then
    llm_api_key="$current_key"
  else
    current_key=""
  fi
fi

if [[ -z "${current_key:-}" ]]; then
  while true; do
    read -r -s -p "LLM API key: " llm_api_key
    echo
    if [[ -n "$llm_api_key" ]]; then
      break
    fi
    echo "API key 不能为空。"
  done
fi

read -r -p "LLM base URL [${current_base_url:-https://api.deepseek.com}]: " llm_base_url
llm_base_url="${llm_base_url:-${current_base_url:-https://api.deepseek.com}}"

read -r -p "LLM model [${current_model:-deepseek-chat}]: " llm_model
llm_model="${llm_model:-${current_model:-deepseek-chat}}"

LLM_PROVIDER="$llm_provider" \
LLM_API_KEY="$llm_api_key" \
LLM_BASE_URL="$llm_base_url" \
LLM_MODEL="$llm_model" \
".venv/bin/python" - <<'PY'
import json
import os
from pathlib import Path

path = Path("config.json")
data = json.loads(path.read_text(encoding="utf-8"))
data["llm_provider"] = os.environ["LLM_PROVIDER"]
data["llm_api_key"] = os.environ["LLM_API_KEY"]
data["llm_base_url"] = os.environ["LLM_BASE_URL"]
data["llm_model"] = os.environ["LLM_MODEL"]
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo
echo "==> 5/5 安装完成"
echo
echo "接下来你可以这样使用："
echo
echo "1. 命令行聊天："
echo "   bash \"$ROOT_DIR/tools/run_cli_macos.sh\""
echo
echo "2. 打开本地看板："
echo "   bash \"$ROOT_DIR/tools/run_dashboard_macos.sh\""
echo
read -r -p "现在就启动命令行模式吗？[Y/n] " start_cli_now
start_cli_now="${start_cli_now:-Y}"
if [[ "$start_cli_now" =~ ^[Yy]$ ]]; then
  source .venv/bin/activate
  exec python3 cli.py
fi
