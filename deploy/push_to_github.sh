#!/usr/bin/env bash
# 把本项目推送到 GitHub。
# 前置：在 https://github.com/new 手动创建一个「完全空」的仓库（不要勾选 README/.gitignore/license）。
# 用法：
#   bash deploy/push_to_github.sh                          # 默认 jeffreys125/jiashi-ankang-daily
#   bash deploy/push_to_github.sh <仓库名> [用户名]
# 凭据走你本机的 git credential helper，命令里不含任何 token。
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

REPO="${1:-jiashi-ankang-daily}"
OWNER="${2:-jeffreys125}"
URL="https://github.com/${OWNER}/${REPO}.git"

if [ ! -d .git ]; then
  git init -q
fi
git config user.name  "${GIT_AUTHOR_NAME:-$OWNER}"                      2>/dev/null || true
git config user.email "${GIT_AUTHOR_EMAIL:-$OWNER@users.noreply.github.com}" 2>/dev/null || true

git add -A
if git diff --cached --name-only | grep -qE '(^|/)\.env$'; then
  echo "✗ .env（真实凭据）被暂存，已中止。请检查 .gitignore 后重试。" >&2
  exit 1
fi
if ! git diff --cached --quiet; then
  git commit -q -m "chore: sync 家事安康会每日内容助手"
fi

git branch -M main
git remote remove origin 2>/dev/null || true
git remote add origin "$URL"

echo "目标仓库：$URL"
echo "提示：若提示认证失败，请先在本机登录 GitHub（git credential helper / gh auth login）。"
git push -u origin main
echo "✓ 已推送到 https://github.com/${OWNER}/${REPO}"
