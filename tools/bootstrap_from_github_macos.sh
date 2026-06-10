#!/usr/bin/env bash

set -euo pipefail

REPO_ZIP_URL="${REPO_ZIP_URL:-https://github.com/Yukon594/daily-practice-wechat-assistant/archive/refs/heads/main.zip}"
REPO_ROOT_NAME="${REPO_ROOT_NAME:-daily-practice-wechat-assistant-main}"
DEFAULT_TARGET_DIR="${DEFAULT_TARGET_DIR:-$HOME/daily-practice-wechat-assistant}"

if [[ "${OSTYPE:-}" != darwin* ]]; then
  echo "提示：这个一键脚本主要面向 macOS。"
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "没有检测到 curl，无法自动下载安装包。"
  exit 1
fi

if ! command -v unzip >/dev/null 2>&1; then
  echo "没有检测到 unzip，无法解压安装包。"
  exit 1
fi

echo "这个脚本会先从 GitHub 下载项目，再继续安装。"
read -r -p "安装到哪里？直接回车使用默认目录 [${DEFAULT_TARGET_DIR}]: " target_dir
target_dir="${target_dir:-$DEFAULT_TARGET_DIR}"
target_dir="${target_dir/#\~/$HOME}"

if [[ -e "$target_dir" ]]; then
  echo "目标目录已经存在：$target_dir"
  read -r -p "是否覆盖这个目录里的内容？[y/N] " overwrite
  if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
    echo "已取消安装。"
    exit 1
  fi
  rm -rf "$target_dir"
fi

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

zip_path="$tmpdir/project.zip"
extract_dir="$tmpdir/extracted"

echo
echo "==> 1/4 下载项目"
curl -L "$REPO_ZIP_URL" -o "$zip_path"

echo
echo "==> 2/4 解压项目"
mkdir -p "$extract_dir"
unzip -q "$zip_path" -d "$extract_dir"

repo_dir="$extract_dir/$REPO_ROOT_NAME"
if [[ ! -d "$repo_dir" ]]; then
  echo "下载完成，但没有找到预期目录：$REPO_ROOT_NAME"
  exit 1
fi

echo
echo "==> 3/4 拷贝到本地目录"
mkdir -p "$(dirname "$target_dir")"
mv "$repo_dir" "$target_dir"

echo
echo "==> 4/4 开始本地安装"
cd "$target_dir"
bash tools/install_macos.sh
