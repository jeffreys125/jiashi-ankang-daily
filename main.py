# -*- coding: utf-8 -*-
"""家事安康会 · 每日内容助手 CLI

常用命令：
    python main.py init                     初始化（生成 .env、建库、装依赖检查）
    python main.py check --probe           自检 + 实测采集源
    python main.py run --dry-run           完整跑一遍，但只出本地成品，不碰微信
    python main.py run                     正式跑：出稿 + 自动存进公众号草稿箱
    python main.py run --topic senior_health --force   指定栏目 / 强制重跑
    python main.py topics                  只看今天采集到的选题灵感
    python main.py history                 查看历史成稿
    python main.py stats                   统计
    python main.py daemon                  常驻定时（不装 cron 也能用）
    python main.py publish-latest          尝试发布最近一条草稿（个人号会提示无权限）
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from lib.settings import ROOT, check_credentials, load_settings, mask
from lib.util import setup_logging


def _banner():
    print("=" * 64)
    print("  家事安康会 · 每日内容助手")
    print("  采集选题 → AI 原创写稿 → 公众号排版 → 自动存草稿 → 提醒发表")
    print("=" * 64)


def _deps() -> list[tuple[str, bool]]:
    out = []
    for name, mod in [("requests", "requests"), ("beautifulsoup4", "bs4"), ("Pillow", "PIL")]:
        try:
            __import__(mod)
            out.append((name, True))
        except ImportError:
            out.append((name, False))
    return out


def cmd_init(cfg, args):
    from lib import store
    _banner()
    print("\n[1/4] 依赖检查")
    missing = [n for n, ok in _deps() if not ok]
    for n, ok in _deps():
        print(f"  {'OK ' if ok else '缺失'}  {n}")
    if missing:
        print(f"\n  请先安装：pip3 install -r requirements.txt")
        print("  （缺少：" + ", ".join(missing) + "）")
    else:
        print("  依赖齐全")

    print("\n[2/4] 生成 .env")
    env = ROOT / ".env"
    if env.exists():
        print(f"  已存在，保留不改：{env}")
    else:
        shutil.copy(ROOT / ".env.example", env)
        print(f"  已创建：{env}  ← 请填入 WX_APPID / WX_APPSECRET / LLM_API_KEY")

    print("\n[3/4] 初始化数据库")
    store.init_db()
    print(f"  已建立：{ROOT / 'data' / 'jazk.db'}")

    print("\n[4/4] 下一步")
    print("  1. 编辑 .env 填入凭据（不知道怎么拿 AppSecret 看 README）")
    print("  2. python main.py check --probe      # 自检并实测采集源")
    print("  3. python main.py run --dry-run      # 本地试跑，生成示例文章")
    print("  4. 确认效果后：python main.py run    # 正式建草稿")
    print("  5. 定时：crontab -e 加一行，见 deploy/crontab.example")
    print()


def cmd_check(cfg, args):
    from lib import cover, store, topics
    from lib.collector import Collector
    from lib.wechat import WeChatClient
    _banner()

    print(f"\n[环境] Python {sys.version.split()[0]}｜项目 {ROOT}")
    missing = [n for n, ok in _deps() if not ok]
    print(f"  依赖：{'齐全' if not missing else '缺少 ' + ', '.join(missing)}")

    f = cover.find_font(24)
    print(f"  中文字体：{'已找到 ' + str(f.path) if f else '未找到（封面会降级为无文字版，建议 sudo apt install fonts-noto-cjk）'}")
    print(f"  内置选题库：{topics.count()} 条（{', '.join(topics.TOPIC_LABELS.values())}）")

    print("\n[能力就绪]")
    for k, v in check_credentials(cfg).items():
        print(f"  {'OK ' if v else '-- '}  {k}")
    print(f"  公众号 AppID：{mask(cfg['wechat_credentials'].get('appid',''))}")
    print(f"  AppSecret：{mask(cfg['wechat_credentials'].get('appsecret',''))}")
    print(f"  LLM：{cfg['llm'].get('base_url')} / {cfg['llm'].get('model')}")
    print(f"  API Key：{mask(cfg['llm_credentials'].get('api_key',''))}")
    print(f"  自动发布：{'开启' if cfg['wechat'].get('auto_publish') else '关闭（个人号请保持关闭）'}")
    ap = cfg.get("ai_photo", {})
    print(f"  AI 生图：{ap.get('base_url', '')} / {ap.get('model', '')}")
    print(f"  生图 Key：{mask(cfg.get('image_credentials', {}).get('api_key', ''))}")

    print("\n[微信接口连通性]")
    wx = WeChatClient(cfg, dry_run=args.dry_run)
    r = wx.check()
    print(f"  {'OK ' if r['ok'] else '-- '}  {r['message']}")
    if r["ok"]:
        print("  提醒：个人订阅号只能建草稿，最后一步请在公众号后台点「发表」")

    if args.probe:
        print("\n[采集源实测]（每个源一次 GET，约 10 秒）")
        setup_logging(cfg["runtime"].get("log_level", "INFO"), to_file=False)
        c = Collector(cfg)
        items = c.collect()
        for h in c.health:
            print(f"  {'OK ' if h['ok'] else 'FAIL'}  {h['source']:<14} "
                  f"{h.get('raw', '')}{h.get('error', '')}")
        from collections import Counter
        cnt = Counter(x["topic"] for x in items)
        print(f"  候选池共 {len(items)} 条：" + "，".join(
            f"{topics.TOPIC_LABELS.get(k,k)} {v}" for k, v in cnt.items()
        ))
    else:
        print("\n  提示：加 --probe 可实测每个采集源是否可用")

    store.init_db()
    print(f"\n[数据库] {ROOT / 'data' / 'jazk.db'}")
    print()


def cmd_run(cfg, args):
    from lib.pipeline import run
    dry = args.dry_run or cfg["runtime"].get("dry_run_default", False)
    s = run(cfg, dry_run=dry, force=args.force,
            topic_override=args.topic, no_notify=args.no_notify)

    _banner()
    if s.get("skipped"):
        print(f"\n  {s['message']}\n")
        return 0
    if s.get("status") == "failed":
        print(f"\n  流程失败：{s.get('error')}")
        print("  可先看日志：" + str(ROOT / "data" / "logs"))
        print("  常见原因见 README「排错」一节\n")
        if args.verbose:
            print(s.get("traceback", ""))
        return 1

    print(f"\n  日期栏目：{s['day']}　{s.get('column','')}（{s.get('topic_label','')}）")
    print(f"  文章标题：{s.get('title')}")
    print(f"  摘要：{s.get('digest')}")
    print(f"  字数：{s.get('words')}　生成方式：{s.get('generated_by')} / {s.get('model')}")
    print(f"  状态：{s.get('status')}　{s.get('draft_note')}")
    if s.get("illustrations"):
        extra = f"，其中 AI 生成 {s['ai_illustrations']} 张（已加显式标识）" if s.get("ai_illustrations") else ""
        print(f"  正文插图：{s['illustrations']} 张（产出目录 illust-*.png / .jpg）{extra}")
    if s.get("need_review"):
        print(f"  ⚠ 合规提示 {len(s.get('compliance_issues', []))} 项，发布前建议扫一眼（见 .md 文件）")
    if s.get("sources"):
        ok = sum(1 for x in s["sources"] if x["ok"])
        print(f"  采集源：{ok}/{len(s['sources'])} 可用")
        for x in s["sources"]:
            if not x["ok"]:
                print(f"    - {x['source']}: {x.get('error','')[:70]}")
    print("\n  产出文件：")
    for label, key in [("Markdown 原稿", "md_path"), ("微信正文 HTML", "html_path"),
                       ("本地排版预览", "preview_path"), ("封面图", "cover_path")]:
        print(f"    {label:<16} {s.get(key, '')}")
    if dry:
        print("\n  ⚠ 本次是【本地试跑 --dry-run】，刻意不调用微信接口：")
        print("    公众号草稿箱不会有任何内容，这是正常的。")
        print("    要正式出稿并存入草稿箱，请执行：")
        print("      docker compose run --rm app python main.py run")
        print("    （或等常驻 daemon 到点自动执行）")
    elif s.get("status") == "local_only":
        print("\n  ⚠ 未存入草稿箱：公众号凭据未配置，或 draft_enabled 被关闭。")
        print("    请在 .env 填 WX_APPID / WX_APPSECRET。手动 run 直接生效；")
        print("    常驻 daemon 需执行：docker compose up -d --force-recreate")
        print("    自检：docker compose run --rm app python main.py check")
    else:
        print("\n  下一步：到公众号后台「草稿箱」找到这篇，点「发表」。")
    print(f"  打开上面的「本地排版预览」可先看排版效果。\n")
    return 0


def cmd_topics(cfg, args):
    from lib import store, topics
    from lib.collector import Collector
    setup_logging(cfg["runtime"].get("log_level", "WARNING"), to_file=False)
    store.init_db()
    c = Collector(cfg)
    pool = c.collect()
    _banner()
    print(f"\n今日候选池 {len(pool)} 条（前 30 条）：\n")
    for i, x in enumerate(pool[:30], 1):
        tag = {"portal": "网", "rss": "订", "manual": "手", "builtin": "库"}.get(x.get("origin", ""), "?")
        print(f"  {i:2d}. [{tag}][{topics.TOPIC_LABELS.get(x['topic'], x['topic']):<10}] {x['title']}")
    print("\n  网=官网栏目新鲜线索　库=内置常青选题　手=手动素材\n")
    return 0


def cmd_history(cfg, args):
    from lib import store
    store.init_db()
    _banner()
    rows = store.list_articles(args.limit)
    print(f"\n最近 {len(rows)} 篇成稿：\n")
    if not rows:
        print("  （暂无，先跑 python main.py run --dry-run）\n")
    for r in rows:
        print(f"  {r['day']}  [{r['status']:<12}] {r['title']}  ({r['words']}字)")
        print(f"             {r.get('html_path','')}")
    print()
    return 0


def cmd_stats(cfg, args):
    from lib import store
    store.init_db()
    _banner()
    print()
    for k, v in store.stats().items():
        print(f"  {k:<14} {v}")
    print("\n  最近运行：")
    for r in store.list_runs(8):
        print(f"    {r['created_at']}  {r['stage']:<6} {r['status']:<8} {r['message'][:60]}")
    print()
    return 0


def _next_run(cron: str) -> datetime:
    """解析简化的 '分 时 * * *'，返回下一次执行时刻。"""
    parts = cron.split()
    minute, hour = int(parts[0]), int(parts[1])
    now = datetime.now()
    nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return nxt


def cmd_daemon(cfg, args):
    from lib.pipeline import run
    cron = cfg["schedule"].get("cron", "30 6 * * *")
    setup_logging(cfg["runtime"].get("log_level", "INFO"))
    _banner()
    print(f"\n常驻定时模式，计划：{cron}（Ctrl+C 退出）")
    print("若部署在服务器，更推荐用 cron，见 deploy/crontab.example\n")
    while True:
        nxt = _next_run(cron)
        wait = (nxt - datetime.now()).total_seconds()
        print(f"  下次执行：{nxt:%Y-%m-%d %H:%M}（等待 {wait/3600:.1f} 小时）", flush=True)
        time.sleep(max(1, min(wait, 3600)))
        if datetime.now() + timedelta(seconds=1) >= nxt:
            s = run(cfg, dry_run=args.dry_run)
            print(f"  [{datetime.now():%H:%M}] 结果：{s.get('status')} {s.get('title','')}", flush=True)
    return 0


def cmd_publish_latest(cfg, args):
    from lib import store
    from lib.wechat import WeChatClient
    store.init_db()
    with store.conn() as c:
        row = c.execute(
            "SELECT * FROM drafts WHERE status='draft_ok' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    _banner()
    if not row:
        print("\n  没有可发布的草稿（先跑一次 python main.py run）\n")
        return 1
    print(f"\n  目标草稿 media_id={row['media_id']}（{row['day']}）")
    wx = WeChatClient(cfg, dry_run=args.dry_run)
    if not wx.configured:
        print("  未配置公众号凭据，无法调用发布接口\n")
        return 1
    r = wx.publish(row["media_id"])
    if r["ok"]:
        print(f"  发布成功：publish_id={r['publish_id']}\n")
        store.save_draft({"article_id": row["article_id"], "media_id": row["media_id"],
                          "status": "published", "publish_result": "ok", "message": "手动补发成功"})
    else:
        print(f"  发布失败：{r['message']}")
        print(f"  {r.get('hint','')}")
        print("\n  个人订阅号请直接到公众号后台「草稿箱」点「发表」，效果一样。\n")
    return 0 if r["ok"] else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="家事安康会 · 每日内容助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, helptext in [
        ("init", "初始化：生成 .env、建库、检查依赖"),
        ("check", "自检：配置、字体、凭据、微信连通性"),
        ("run", "跑一天的完整流程"),
        ("topics", "查看今天采集到的选题灵感"),
        ("history", "查看历史成稿"),
        ("stats", "查看统计与运行记录"),
        ("daemon", "常驻定时模式（不装 cron 时可用）"),
        ("publish-latest", "尝试发布最近一条草稿"),
    ]:
        sp = sub.add_parser(name, help=helptext)
        if name == "run":
            sp.add_argument("--dry-run", action="store_true", help="只生成本地成品，不调用微信接口")
            sp.add_argument("--force", action="store_true", help="忽略当日幂等保护，强制重跑")
            sp.add_argument("--topic", choices=["family_story", "inlaw_relation", "senior_health"],
                            help="指定今天的栏目")
            sp.add_argument("--no-notify", action="store_true", help="不发送通知")
            sp.add_argument("-v", "--verbose", action="store_true", help="失败时打印堆栈")
        elif name == "check":
            sp.add_argument("--probe", action="store_true", help="实测每个采集源")
            sp.add_argument("--dry-run", action="store_true", help="不真的获取 access_token")
        elif name == "history":
            sp.add_argument("--limit", type=int, default=10)
        elif name == "daemon":
            sp.add_argument("--dry-run", action="store_true")

    args = p.parse_args(argv)
    cfg = load_settings()
    handlers = {
        "init": cmd_init, "check": cmd_check, "run": cmd_run, "topics": cmd_topics,
        "history": cmd_history, "stats": cmd_stats, "daemon": cmd_daemon,
        "publish-latest": cmd_publish_latest,
    }
    return handlers[args.cmd](cfg, args) or 0


if __name__ == "__main__":
    sys.exit(main())
