# -*- coding: utf-8 -*-
"""生成 AI 配图示例页。

依赖：先跑 tools/make_samples.py 生成三个栏目的成品。
产出：
  sample/ai-demo/index.html    两张 AI 示例图展示 + 说明
  sample/ai-demo/preview.html  把 AI 图插进真实文章排版后的效果
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "sample" / "ai-demo"
SRC = ROOT / "sample" / "senior_health" / "preview.html"

IMGS = [
    ("ai-family-table.jpg", "家长里短 · 家里的饭桌",
     "老式木桌、冒热气的汤、午后窗光，暖褐色调，安静有人情味"),
    ("ai-senior-morning.jpg", "中老年养生 · 清晨散步",
     "公园落叶小道、长辈背影、柔和晨光，明亮舒展"),
]

DISCLOSURE = (
    '<section style="margin:22px 0 0;padding:14px 16px;background:#FBF6EF;'
    'border-radius:6px;">'
    '<p style="font-size:12px;line-height:1.8;color:#8A7F72;margin:0;'
    'text-align:center;font-family:-apple-system,BlinkMacSystemFont,\'PingFang SC\','
    '\'Microsoft YaHei\',Arial,sans-serif;">'
    '说明：本文部分配图由 AI 生成，仅作氛围示意，非真实人物与场景。</p></section>'
)


def make_index() -> None:
    cards = "\n".join(
        f"""
    <figure>
      <img src="{src}" alt="{label}">
      <figcaption><b>{label}</b><span>{desc}</span></figcaption>
    </figure>""" for src, label, desc in IMGS
    )
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>家事安康会 · AI 配图效果示例</title>
<style>
 *{{box-sizing:border-box}}
 body{{margin:0;padding:36px 20px 60px;background:#F3EDE4;color:#3E3833;
      font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;}}
 .wrap{{max-width:1000px;margin:0 auto}}
 h1{{font-size:26px;color:#C0603C;margin:0 0 10px;text-align:center;letter-spacing:1px}}
 .sub{{text-align:center;color:#7A7068;font-size:14px;line-height:1.8;margin:0 0 28px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:22px}}
 figure{{margin:0;background:#fff;border-radius:12px;overflow:hidden;
        box-shadow:0 4px 20px rgba(90,60,40,.10)}}
 figure img{{width:100%;display:block;aspect-ratio:3/2;object-fit:cover}}
 figcaption{{padding:16px 18px 20px;display:flex;flex-direction:column;gap:6px}}
 figcaption b{{font-size:16px;color:#C0603C}}
 figcaption span{{font-size:13px;line-height:1.7;color:#7A7068}}
 .btn{{display:block;width:fit-content;margin:28px auto 0;background:#C0603C;color:#fff;
      text-decoration:none;padding:12px 26px;border-radius:24px;font-size:15px}}
 .note{{margin:30px auto 0;background:#fff;border-left:4px solid #C0603C;
       border-radius:6px;padding:18px 22px;font-size:13px;line-height:1.95;color:#6B6157}}
 .note b{{color:#C0603C}}
 code{{background:#F3EDE4;padding:2px 6px;border-radius:3px;font-size:12px}}
</style></head><body><div class="wrap">
 <h1>AI 配图效果示例</h1>
 <p class="sub">按栏目生成贴合「家事安康会」气质的画面 · 点击查看插进文章后的真实排版</p>
 <div class="grid">{cards}
 </div>
 <a class="btn" href="preview.html">查看插入文章后的排版效果 →</a>
 <div class="note">
   <b>关于这两张图：</b>由平台图像生成能力生成，仅用于演示效果。程序在你的服务器上运行时，
   走的是你自己配的 <code>IMAGE_API_KEY</code>（硅基流动 / 阿里百炼等 OpenAI 兼容服务），
   按张计费约 ¥0.10~0.20，每天 2 张约 ¥6~12/月。<br>
   <b>关于标识：</b>图上的「AI生成」是生成平台自动加的显式标识，
   依据 2025-09-01 施行的《人工智能生成合成内容标识办法》与微信平台要求，程序<b>不会去除或篡改</b>；
   同时程序还会在图注和正文末尾补充文字声明。发布时请在公众号后台主动勾选 AI 内容声明。<br>
   <b>关于文字：</b>AI 生成中文容易出错字，所以带字的「要点提示卡」仍由程序本地绘制，
   AI 只负责不含文字的画面。<br>
   <b>降级：</b>没配 Key、额度用尽或接口故障时，自动回退到本地绘制卡，出稿不受影响。
 </div>
</div></body></html>"""
    (D / "index.html").write_text(html, encoding="utf-8")
    print("已生成:", D / "index.html")


def make_preview() -> None:
    if not SRC.exists():
        raise SystemExit(f"缺少 {SRC}，请先运行 tools/make_samples.py")
    t = SRC.read_text(encoding="utf-8")
    t = t.replace('src="illust-1.png"', f'src="{IMGS[0][0]}"')
    t = t.replace('src="illust-2.png"', f'src="{IMGS[1][0]}"')
    # 原预览的头图在 senior_health/ 目录下，这里要改成跨目录相对路径
    t = re.sub(r'src="(cover-[^"]+\.png)"', r'src="../senior_health/\1"', t)
    # 图注换成 AI 显式标识；注入文末声明
    t = re.sub(
        r'>(本期要点|记住这句话|家常提醒|日子慢一点)</p>',
        '>AI 生成 · 氛围示意</p>', t,
    )
    if "本文部分配图由 AI 生成" not in t:
        t = t.replace(
            '<section style="margin:36px 0 0 0;padding:22px 18px;',
            DISCLOSURE + '<section style="margin:36px 0 0 0;padding:22px 18px;', 1,
        )
    t = t.replace("家事安康会 · 公众号正文预览", "家事安康会 · AI 配图效果预览")
    (D / "preview.html").write_text(t, encoding="utf-8")
    print("已生成:", D / "preview.html")


if __name__ == "__main__":
    D.mkdir(parents=True, exist_ok=True)
    make_index()
    make_preview()
