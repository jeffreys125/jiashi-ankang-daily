# -*- coding: utf-8 -*-
"""重新生成 sample/ 下的三个栏目示例（纯本地 dry-run，不碰微信接口）。

用法：python tools/make_samples.py
用于演示排版效果、验证全链路；不会消耗公众号接口额度。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.settings import load_settings  # noqa: E402
from lib.pipeline import run  # noqa: E402
from lib.util import SAMPLE_DIR  # noqa: E402

NAMES = {
    "family_story": ("家长里短·家庭故事", "家里那点事"),
    "inlaw_relation": ("婆媳相处·相处之道", "好好说话"),
    "senior_health": ("中老年养生·健康知识", "安康小课堂"),
}


def main() -> None:
    cfg = load_settings()
    cards = []
    for topic, slug in [("family_story", "family_story"),
                        ("inlaw_relation", "inlaw_relation"),
                        ("senior_health", "senior_health")]:
        s = run(cfg, dry_run=True, topic_override=topic, no_notify=True)
        if s.get("status") == "failed":
            raise SystemExit(f"[{topic}] 生成失败：{s.get('error')}")
        print(f"[{topic}] 《{s.get('title')}》 {s.get('words')} 字")
        d = SAMPLE_DIR / slug
        d.mkdir(parents=True, exist_ok=True)
        cover_name = f"cover-{slug}.png"
        shutil.copy(s["cover_path"], d / cover_name)
        # 正文插图用相对路径引用，保持同名复制到示例目录即可显示
        for p in sorted(Path(s["preview_path"]).parent.glob("illust-*")):
            shutil.copy(p, d / p.name)
        html = (Path(s["preview_path"]).read_text(encoding="utf-8")
                .replace('src="cover.png"', f'src="{cover_name}"'))
        (d / "preview.html").write_text(html, encoding="utf-8")
        shutil.copy(s["md_path"], d / "article.md")
        shutil.copy(s["html_path"], d / "wechat-body.html")
        cards.append({**s, "slug": slug, "cover": f"{slug}/{cover_name}",
                      "link": f"{slug}/preview.html",
                      "label": NAMES[topic][0], "column": NAMES[topic][1]})

    card_html = "\n".join(f"""
    <a class="card" href="{c['link']}">
      <img src="{c['cover']}" alt="{c['title']}">
      <div class="meta">{c['column']} · {c['label']}</div>
      <h3>{c['title']}</h3>
      <p>{c['digest'][:70]}</p>
      <div class="foot"><span>{c['words']} 字</span><span>查看排版 →</span></div>
    </a>""" for c in cards)

    index = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>家事安康会 · 每日内容助手 · 成品示例</title>
<style>
 *{{box-sizing:border-box}}
 body{{margin:0;padding:36px 20px 60px;background:#F3EDE4;color:#3E3833;
      font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;}}
 .wrap{{max-width:1080px;margin:0 auto}}
 .head{{text-align:center;margin-bottom:34px}}
 .head h1{{font-size:27px;margin:0 0 10px;color:#C0603C;letter-spacing:1px}}
 .head p{{margin:6px 0;color:#7A7068;font-size:14px;line-height:1.8}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:22px}}
 .card{{display:block;background:#fff;border-radius:12px;overflow:hidden;text-decoration:none;
       color:inherit;box-shadow:0 4px 20px rgba(90,60,40,.10);transition:transform .2s,box-shadow .2s}}
 .card:hover{{transform:translateY(-4px);box-shadow:0 10px 30px rgba(90,60,40,.18)}}
 .card img{{width:100%;display:block;aspect-ratio:900/383;object-fit:cover}}
 .card .meta{{padding:16px 18px 0;font-size:12px;color:#C0603C;letter-spacing:1px}}
 .card h3{{padding:8px 18px 0;margin:0;font-size:18px;line-height:1.5}}
 .card p{{padding:8px 18px 0;margin:0;font-size:13px;line-height:1.75;color:#7A7068;min-height:68px}}
 .card .foot{{display:flex;justify-content:space-between;padding:16px 18px 20px;
             font-size:12px;color:#A79C90;border-top:1px solid #F0E8DC;margin-top:14px}}
 .note{{max-width:1080px;margin:30px auto 0;background:#fff;border-left:4px solid #C0603C;
       border-radius:6px;padding:18px 22px;font-size:13px;line-height:1.9;color:#6B6157}}
 .note b{{color:#C0603C}}
 code{{background:#F3EDE4;padding:2px 6px;border-radius:3px;font-size:12px}}
</style></head><body><div class="wrap">
 <div class="head">
   <h1>家事安康会 · 每日内容助手</h1>
   <p>三个栏目的成品示例 · 采集 → AI 原创写稿 → 公众号排版 → 封面 → 自动存草稿</p>
   <p>点击任意卡片查看该篇的公众号排版预览（含封面图与内联样式正文）</p>
 </div>
 <div class="grid">{card_html}
 </div>
 <div class="note">
   <b>关于示例内容：</b>这三篇由「本地模板生成器」产出，仅用于演示排版与全链路跑通效果，
   字数较短。在 <code>.env</code> 里配置 <code>LLM_API_KEY</code> 后，程序会自动切换为大模型原创稿
   （1200~1800 字），并按当日选题与季节提示写作。<br>
   <b>关于发布：</b>个人主体订阅号自 2025 年 7 月起已无官方发布接口权限，程序默认把文章
   <b>自动存入公众号草稿箱</b>并推送提醒，最后一步在后台点「发表」即可。
 </div>
</div></body></html>"""
    (SAMPLE_DIR / "index.html").write_text(index, encoding="utf-8")
    print("示例总览已生成：", SAMPLE_DIR / "index.html")


if __name__ == "__main__":
    main()
