# -*- coding: utf-8 -*-
"""Markdown → 微信公众号内联样式 HTML。

微信公众号正文会过滤 <style> 标签和 class，所有样式必须写在 style 属性里。
本渲染器针对中老年读者：17px 字号、1.9 行高、大段间距、暖色低对比配色。
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from .util import log

# 暖陶土配色，贴合「家事安康会」的家常气质
PRIMARY = "#C0603C"
TEXT = "#3E3833"
MUTED = "#8A7F72"
PAPER = "#FBF6EF"
LINE = "#EADFCE"
FONT = ("-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB',"
        "'Microsoft YaHei',Arial,sans-serif")

S_BODY = (f"font-size:17px;line-height:1.9;letter-spacing:0.5px;color:{TEXT};"
          f"font-family:{FONT};")
S_P = S_BODY + "margin:0 0 20px 0;text-align:justify;"
S_H2 = (f"font-size:19px;line-height:1.6;font-weight:bold;color:{PRIMARY};"
        f"font-family:{FONT};margin:34px 0 18px 0;padding:8px 14px;"
        f"background:{PAPER};border-left:4px solid {PRIMARY};border-radius:0 4px 4px 0;")
S_STRONG = f"font-weight:bold;color:{PRIMARY};"
S_QUOTE = (f"font-size:16px;line-height:1.85;color:#6B6157;font-family:{FONT};"
           f"margin:22px 0;padding:16px 18px;background:{PAPER};"
           f"border-left:3px solid #D9BFA3;border-radius:0 6px 6px 0;")
S_LI = (S_BODY + f"margin:0 0 12px 0;padding-left:2px;"
        f"text-align:justify;")
S_DOT = (f"display:inline-block;width:7px;height:7px;background:{PRIMARY};"
         f"border-radius:50%;margin-right:10px;vertical-align:middle;")
S_SMALL = (f"font-size:13px;line-height:1.8;color:{MUTED};font-family:{FONT};"
           f"text-align:center;margin:0 0 8px 0;")


def _inline(text: str) -> str:
    """行内：HTML 转义 + **加粗** + `代码`。"""
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", rf'<strong style="{S_STRONG}">\1</strong>', text)
    text = re.sub(r"`(.+?)`", r'<span style="color:#8A6E52;">\1</span>', text)
    return text


def _render_blocks(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i].rstrip()
        line = raw.strip()
        if not line:
            i += 1
            continue

        # 分隔线
        if re.fullmatch(r"[-*_]{3,}", line):
            out.append(
                f'<section style="text-align:center;margin:30px 0;color:{LINE};'
                f'font-size:14px;letter-spacing:6px;">· · ·</section>'
            )
            i += 1
            continue

        # 标题（统一渲染为 h2 风格的栏目标题）
        m = re.match(r"^#{1,6}\s+(.+)$", line)
        if m:
            out.append(f'<h2 style="{S_H2}">{_inline(m.group(1))}</h2>')
            i += 1
            continue

        # 引用块（合并连续行）
        if line.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(
                f'<section style="{S_QUOTE}">'
                + "".join(f'<p style="{S_BODY}margin:0 0 8px 0;">{_inline(x)}</p>' for x in buf if x)
                + "</section>"
            )
            continue

        # 列表（合并连续项）
        if re.match(r"^[-*+]\s+", line):
            items = []
            while i < n and re.match(r"^[-*+]\s+", lines[i].strip()):
                items.append(re.sub(r"^[-*+]\s+", "", lines[i].strip()))
                i += 1
            for it in items:
                out.append(
                    f'<p style="{S_LI}"><span style="{S_DOT}"></span>{_inline(it)}</p>'
                )
            continue

        # 有序列表
        if re.match(r"^\d+[.、]\s*", line):
            items = []
            while i < n and re.match(r"^\d+[.、]\s*", lines[i].strip()):
                items.append(re.sub(r"^\d+[.、]\s*", "", lines[i].strip()))
                i += 1
            for idx, it in enumerate(items, 1):
                out.append(
                    f'<p style="{S_LI}"><span style="color:{PRIMARY};font-weight:bold;'
                    f'margin-right:10px;">{idx:02d}</span>{_inline(it)}</p>'
                )
            continue

        # 普通段落（合并连续非空行）
        buf = [line]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith(">") or nxt.startswith("#")
                    or re.match(r"^[-*+]\s+", nxt) or re.match(r"^\d+[.、]\s*", nxt)
                    or re.fullmatch(r"[-*_]{3,}", nxt)):
                break
            buf.append(nxt)
            i += 1
        out.append(f'<p style="{S_P}">{_inline(" ".join(buf))}</p>')
    return "\n".join(out)


def render_wechat_html(
    article: dict,
    body_md: str,
    column: str,
    color: str,
    head_image_url: str = "",
    is_original: bool = False,
) -> str:
    """生成可直接提交给 draft/add 的正文 HTML。"""
    _now = datetime.now()
    date_cn = f"{_now.year}年{_now.month}月{_now.day}日"  # 不用 %-m，兼容 Windows
    primary = color or PRIMARY

    head = (
        f'<section style="margin:0 0 26px 0;text-align:center;">'
        f'<span style="display:inline-block;font-size:13px;letter-spacing:2px;'
        f'color:{primary};border:1px solid {primary};border-radius:20px;'
        f'padding:5px 18px;font-family:{FONT};">{html.escape(column)} · {date_cn}</span>'
        f'</section>'
    )

    img = ""
    if head_image_url:
        img = (
            f'<section style="text-align:center;margin:0 0 26px 0;">'
            f'<img src="{html.escape(head_image_url, quote=True)}" '
            f'style="width:100%;max-width:100%;height:auto;border-radius:6px;" '
            f'alt="家事安康会"/>'
            f'</section>'
        )

    body_html = _render_blocks(body_md)

    footer = f"""
<section style="margin:36px 0 0 0;padding:22px 18px;background:{PAPER};border-radius:8px;text-align:center;">
  <p style="font-size:16px;color:{primary};font-weight:bold;margin:0 0 10px 0;font-family:{FONT};">愿每一个家，都平安喜乐</p>
  <p style="{S_SMALL}">这里是家事安康会，聊聊家长里短、相处之道与安康小事。</p>
  <p style="{S_SMALL}">觉得有用，点个「在看」，也转给惦记的人。</p>
</section>
<section style="margin:18px 0 0 0;text-align:center;">
  <p style="font-size:12px;line-height:1.8;color:#A79C90;font-family:{FONT};margin:0;">
    {'本文为家事安康会原创内容，转载请联系授权。' if is_original else '内容仅供生活参考，具体情况请咨询专业人士。'}
  </p>
</section>"""

    return (
        f'<section style="max-width:100%;margin:0 auto;padding:8px 2px;'
        f'background:#FFFFFF;font-family:{FONT};">\n'
        + head + "\n" + img + "\n" + body_html + "\n" + footer + "\n</section>"
    )


def wrap_preview(inner_html: str, title: str) -> str:
    """包一层手机宽度的本地预览页（仅用于本地查看，不提交给微信）。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{html.escape(title)} · 预览</title>
<style>
  body{{margin:0;background:#EDE7DE;padding:24px 12px;}}
  .phone{{max-width:414px;margin:0 auto;background:#fff;border-radius:12px;
         box-shadow:0 6px 30px rgba(0,0,0,.12);overflow:hidden;}}
  .bar{{padding:14px 18px;background:#FAF7F2;border-bottom:1px solid #EADFCE;
       font-size:13px;color:#8A7F72;font-family:{FONT};}}
  .title{{padding:22px 20px 4px;font-size:22px;font-weight:bold;line-height:1.5;
         color:{TEXT};font-family:{FONT};}}
  .meta{{padding:0 20px 16px;font-size:12px;color:#A79C90;font-family:{FONT};}}
  .content{{padding:8px 20px 32px;}}
  .tip{{max-width:414px;margin:16px auto 0;font-size:12px;color:#7A7068;
       line-height:1.7;font-family:{FONT};}}
</style></head><body>
<div class="phone">
  <div class="bar">家事安康会 · 公众号正文预览</div>
  <div class="title">{html.escape(title)}</div>
  <div class="meta">家事安康会　{datetime.now().strftime('%Y-%m-%d')}　原创稿</div>
  <div class="content">{inner_html}</div>
</div>
<p class="tip">此页面仅用于本地预览排版效果。实际提交到微信时，标题与摘要由草稿接口单独传入，正文只用中间这段内容。</p>
</body></html>"""


def build_markdown(article: dict, body_md: str, column: str) -> str:
    """生成可备份/人工修改的 Markdown 版本。"""
    hints = article.get("image_hints") or []
    hint_md = "\n".join(f"- {h}" for h in hints)
    refs = article.get("fresh_refs") or []
    ref_md = ("\n".join(f"- {r}（仅作选题灵感，正文未采用其措辞）" for r in refs)
              or "- 今日无可用网络线索，使用内置常青选题")
    issues = article.get("compliance_issues") or article.get("issues") or []
    issue_md = ("\n".join(f"- [{i['level']}] {i['category']}：{i['text']}" for i in issues)
                or "- 无")
    return (
        f"# {article['title']}\n\n"
        f"> 栏目：{column}　|　账号：家事安康会　|　{datetime.now():%Y-%m-%d}\n>\n"
        f"> 摘要：{article.get('digest','')}\n\n"
        f"{body_md}\n\n"
        f"---\n\n"
        f"## 今日参考线索（不进入正文）\n\n{ref_md}\n\n"
        f"## 配图建议（不进入正文）\n\n{hint_md}\n\n"
        f"## 合规检查记录\n\n{issue_md}\n\n"
        f"## 生成信息\n\n"
        f"- 生成方式：{article.get('generated_by','')}\n"
        f"- 模型：{article.get('model','')}\n"
        f"- 字数：{article.get('words',0)}\n"
    )
