# -*- coding: utf-8 -*-
"""正文插图生成：用户自放图片优先 + 本地绘制「要点提示卡」兜底。

设计取舍
--------
* 公众号正文里的 <img> 必须是微信域名 URL（外链会被编辑器过滤），所以所有
  插图都要经 media/uploadimg 上传；本模块只负责产出**本地图片文件**。
* 不抓取网络图片、不调用 AI 生图接口：零版权风险、零额外费用、无外网依赖。
* 兜底卡片的文字取自文章自身的小标题 / 加粗金句，保证与内容「相关」，
  而不是一张纯装饰图。
* 所有输出统一为 900x500 且压到 1MB 以下（微信 uploadimg 的硬限制）。
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw

from .aiphoto import AIPhotoGenerator
from .cover import _wrap, find_font
from .util import ROOT, log

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
W, H = 900, 500
BG = (251, 246, 239)
ACCENT = (200, 96, 60)
INK = (62, 56, 51)
MUTED = (154, 141, 128)
PAPER = (243, 228, 210)
LINE = (234, 217, 196)

LABELS = ["本期要点", "记住这句话", "家常提醒", "日子慢一点"]
FALLBACK = [
    "家里的事，慢慢说",
    "多一点体谅，少一点计较",
    "平安喜乐，就是最好的福气",
    "把惦记说出口，别只放在心里",
]


def _clean(s: str) -> str:
    """只剥掉 Markdown 标记，保留中文标点。

    注意不能删「」『』《》：像「先把『猜』字拿掉」去掉引号后会变成
    「先把猜字拿掉」这种读不通的半句话。
    """
    s = re.sub(r"[*`#]", "", s).strip()
    return re.sub(r"\s+", "", s)


def pick_phrases(body_md: str, n: int) -> list[str]:
    """从文章本身提取相关的小标题 / 金句，作为提示卡文案。"""
    out: list[str] = []
    for line in body_md.splitlines():
        m = re.match(r"^#{1,6}\s+(.+)$", line.strip())
        if m:
            t = _clean(m.group(1))
            if 4 <= len(t) <= 24:
                out.append(t)
    for m in re.finditer(r"\*\*(.+?)\*\*", body_md):
        t = _clean(m.group(1))
        if 6 <= len(t) <= 26 and t not in out:
            out.append(t)
    for line in body_md.splitlines():
        s = _clean(line)
        # 普通段落只收「完整成句」的短句，避免截出半句话
        if (10 <= len(s) <= 26 and s not in out
                and re.search(r"[。！？]$", s)
                and not s.startswith(("-", "愿每", "（文"))):
            out.append(s)
    out.extend(FALLBACK)

    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return (uniq or FALLBACK)[:n]


def _center_text(d: ImageDraw.ImageDraw, text: str, font, y_top: int, fill) -> int:
    """按 textbbox 手动居中（不依赖 anchor 参数，兼容旧版 Pillow）。"""
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((W - tw) / 2 - bb[0], y_top - bb[1]), text, font=font, fill=fill)
    return th


def _draw_card(text: str, label: str, out: Path) -> bool:
    """绘制一张暖色「要点提示卡」：900x500、大字、适老、留白多。"""
    font_big = find_font(48)
    font_label = find_font(23)
    font_small = find_font(20)
    if not font_big:
        log("illustrator").warning(
            "未找到中文字体，跳过绘制型插图。安装：sudo apt install fonts-noto-cjk"
        )
        return False

    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 12], fill=ACCENT)
    d.rectangle([0, H - 12, W, H], fill=ACCENT)
    d.rounded_rectangle([26, 26, W - 26, H - 26], radius=16, outline=LINE, width=2)

    # 顶部胶囊标签
    if font_label:
        tw = d.textlength(label, font=font_label)
        bx = (W - (tw + 46)) / 2
        d.rounded_rectangle([bx, 62, bx + tw + 46, 108], radius=23, fill=PAPER)
        _center_text(d, label, font_label, 72, ACCENT)

    # 主文案（最多两行，自动换行）
    lines = _wrap(d, text, font_big, W - 170, max_lines=2)
    y = 178 if len(lines) > 1 else 208
    for ln in lines:
        _center_text(d, ln, font_big, y, INK)
        y += 70

    # 文案下方短分隔线 + 三个小点
    d.line([(W / 2 - 34, 348), (W / 2 + 34, 348)], fill=ACCENT, width=2)
    for dx in (-14, 0, 14):
        d.ellipse([W / 2 + dx - 3, 372, W / 2 + dx + 3, 378], fill=PAPER)

    if font_small:
        _center_text(d, "家事安康会 · 愿每一个家，都平安喜乐", font_small, 414, MUTED)

    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "PNG", optimize=True)
    return True


def _normalize_user_image(src: Path, dst: Path) -> bool:
    """把用户自放图片居中裁切成 900x500 JPEG，避免变形或超过 1MB。"""
    try:
        im = Image.open(src).convert("RGB")
        sw, sh = im.size
        scale = max(W / sw, H / sh)
        nw, nh = max(W, int(sw * scale + 0.5)), max(H, int(sh * scale + 0.5))
        im = im.resize((nw, nh), Image.LANCZOS)
        left, top = (nw - W) // 2, (nh - H) // 2
        im = im.crop([left, top, left + W, top + H])
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, "JPEG", quality=86, optimize=True)
        return True
    except Exception as e:  # noqa: BLE001
        log("illustrator").warning("用户图片 %s 处理失败，已跳过：%s", src.name, str(e)[:100])
        return False


def build(
    article: dict, body_md: str, outdir: Path, cfg: dict, topic: str = ""
) -> list[dict]:
    """产出插图文件，返回 [{path, name, caption, source}]，最多 4 张。

    通道优先级：
      user   = input/images/ 里你自己的照片
      ai     = AI 生图（需 IMAGE_API_KEY，失败自动跳过）
      drawn  = 本地绘制的要点提示卡（永远可用的兜底）
    图片文件名固定为 illust-1 / illust-2 ...，方便本地预览用相对路径引用。
    """
    c = cfg.get("illustrations", {})
    if not c.get("enabled", True):
        return []
    count = max(0, min(4, int(c.get("count", 2))))
    if not count:
        return []

    phrases = pick_phrases(body_md, count)
    results: list[dict] = []

    # 通道 A：用户自放图片（按文件名排序，优先使用）
    user_dir = ROOT / c.get("user_dir", "input/images")
    if user_dir.exists():
        files = sorted(
            p for p in user_dir.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXT
        )
        for p in files:
            if len(results) >= count:
                break
            dst = outdir / f"illust-{len(results) + 1}.jpg"
            if _normalize_user_image(p, dst):
                cap = _clean(p.stem)[:18] or "家事安康会 · 配图"
                results.append({
                    "path": dst, "name": dst.name,
                    "caption": cap, "source": "user",
                })

    # 通道 B：AI 生图（未配 Key / 调用失败 / 额度用尽都会自动跳过）
    aicfg = cfg.get("ai_photo", {})
    if aicfg.get("enabled") and len(results) < count:
        gen = AIPhotoGenerator(cfg)
        if gen.available:
            for i in range(len(results), count):
                item = gen.generate(topic, article.get("title", ""),
                                    outdir / f"illust-{i + 1}")
                if item:
                    results.append(item)
        else:
            log("illustrator").info(
                "未配置 IMAGE_API_KEY，AI 生图跳过，使用本地绘制卡"
            )

    # 通道 C：仍不足的用本地绘制提示卡补齐
    for i in range(len(results), count):
        dst = outdir / f"illust-{i + 1}.png"
        if _draw_card(phrases[i % len(phrases)], LABELS[i % len(LABELS)], dst):
            results.append({
                "path": dst, "name": dst.name,
                "caption": LABELS[i % len(LABELS)], "source": "drawn",
            })

    log("illustrator").info(
        "✓ 正文插图 %d 张（%s）", len(results),
        "、".join(f"{x['name']}[{x['source']}]" for x in results) or "无",
    )
    return results
