#!/usr/bin/env bash
# 家事安康会 · 每日内容助手 部署脚本（Linux）
# 用法：
#   bash deploy/install.sh            # 装依赖 + 初始化，不改动 crontab
#   bash deploy/install.sh --cron     # 额外把每天定时任务写入 crontab
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
PY="${PYTHON:-python3}"

echo "============================================================"
echo " 家事安康会 · 每日内容助手 部署"
echo " 目录：$APP_DIR"
echo "============================================================"

# 1. Python 版本
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "✗ 未找到 $PY，请先安装 Python 3.9+"; exit 1
fi
"$PY" - <<'PYCHECK'
import sys
v = sys.version_info
if v < (3, 9):
    sys.exit("需要 Python 3.9 及以上，当前 " + sys.version.split()[0])
print(f"  Python {sys.version.split()[0]}  OK")
PYCHECK

# 2. 虚拟环境 + 依赖
VENV="$APP_DIR/.venv"
if [ ! -d "$VENV" ]; then
  echo "  创建虚拟环境 .venv ..."
  "$PY" -m venv "$VENV" || { echo "  创建 venv 失败，可改用系统 pip3 安装"; exit 1; }
fi
PYBIN="$VENV/bin/python"
"$PYBIN" -m pip install -q --upgrade pip
"$PYBIN" -m pip install -q -r requirements.txt
echo "  ✓ 依赖已安装（requests / beautifulsoup4 / Pillow）"

# 3. 中文字体（封面渲染需要）
if "$PYBIN" - <<'PYFONT' >/dev/null 2>&1
import sys; sys.path.insert(0, ".")
from lib.cover import find_font
sys.exit(0 if find_font(24) else 1)
PYFONT
then
  echo "  ✓ 中文字体已就绪"
else
  echo "  ! 未找到中文字体，封面会降级为无文字装饰版"
  echo "    建议执行：sudo apt update && sudo apt install -y fonts-noto-cjk"
fi

# 4. 配置与数据库
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "  ✓ 已创建 .env（请填入凭据）"
else
  echo "  ✓ .env 已存在，保留不改"
fi
"$PYBIN" main.py init >/dev/null
echo "  ✓ 数据库已初始化"

# 5. 定时任务（可选）
if [[ "${1:-}" == "--cron" ]]; then
  LINE="30 6 * * * cd $APP_DIR && $PYBIN $APP_DIR/main.py run >> $APP_DIR/data/cron.log 2>&1"
  ( crontab -l 2>/dev/null | grep -Fv "jiashi-ankang-daily/main.py run" || true; echo "$LINE" ) | crontab -
  echo "  ✓ 已写入 crontab：每天 06:30 执行"
  echo "    查看：crontab -l"
else
  echo "  - 未写入定时任务。需要时执行：bash deploy/install.sh --cron"
  echo "    或手动 crontab -e，参考 deploy/crontab.example"
fi

echo
echo "下一步："
echo "  1) 编辑 .env 填入 WX_APPID / WX_APPSECRET / LLM_API_KEY"
echo "  2) $PYBIN main.py check --probe     # 自检 + 实测采集源"
echo "  3) $PYBIN main.py run --dry-run    # 本地试跑"
echo "  4) $PYBIN main.py run              # 正式建草稿"
echo "  5) 手机收到提醒后，到公众号后台点「发表」"
echo
