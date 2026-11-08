# -*- coding: utf-8 -*-
"""封面图生成：Pillow 本地绘制 900x383（微信推荐的 2.35:1 比例）。

不依赖任何外部图库或在线图片服务，纯代码绘制，避免版权与网络依赖。
中文需要系统装 CJK 字体（README 有 apt 命令）；找不到字体时会退化为
无文字的装饰封面并给出警告，避免出现方块乱码。
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .util import log

FONT_CANDIDATES = [
    os.environ.get("JAZK_FONT_PATH", ""),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/arphic/ukai.ttc",
    "/usr/share/fonts/SourceHanSansSC-Regular.otf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
]


def find_font(size: int) -> ImageFont.FreeTypeFont | None:
    for p in FONT_CANDIDATES:
        if not p or not Path(p).exists():
            continue
        # NotoSansCJK 系列 .ttc 的 index=2 通常是简体中文字形，优先用它
        indices = (2, 0) if "CJK" in p and p.endswith(".ttc") else (0,)
        for idx in indices:
            try:
                return ImageFont.truetype(p, size, index=idx)
            except Exception:  # noqa: BLE001
                continue
    return None


def _lerp(a: tuple[int, ...], b: tuple[int, ...], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: float, max_lines: int = 2) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if draw.textlength(trial, font=font) > max_width and cur:
            lines.append(cur)
            cur = ch
            if len(lines) >= max_lines:
                break
        else:
            cur = trial
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and draw.textlength("".join(lines), font=font) > max_width * 1.9:
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def generate_cover(
    out_path: Path,
    title: str,
    column: str,
    signature: str = "愿每一个家，都平安喜乐",
    cfg: dict | None = None,
) -> dict:
    """生成封面 PNG，返回 {path, has_text, font}。"""
    cfg = cfg or {}
    c = cfg.get("cover", {})
    w = int(c.get("width", 900))
    h = int(c.get("height", 383))
    fs = int(c.get("font_size", 54))
    sfs = int(c.get("sub_font_size", 22))
    base = tuple(c.get("bg_color", [200, 96, 66]))
    accent = tuple(c.get("accent_color", [247, 232, 210]))
    top = _lerp(base, (255, 255, 255), 0.18)
    bottom = _lerp(base, (0, 0, 0), 0.20)

    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=_lerp(top, bottom, y / h))

    # 右下角柔和光晕（同心圆）
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for r in range(80, 330, 42):
        od.ellipse(
            [w - r - 40, h - r - 10, w - r + 260, h - r + 260],
            outline=(255, 240, 220, 16), width=2,
        )
    od.ellipse([w - 250, h - 210, w + 90, h + 130], fill=(255, 240, 220, 14))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    d = ImageDraw.Draw(img)

    # 左侧竖装饰条
    d.rectangle([0, 0, 10, h], fill=accent)
    d.rectangle([46, 62, 50, h - 62], fill=(255, 255, 255))

    font_big = find_font(fs)
    font_small = find_font(sfs)
    has_text = font_big is not None and font_small is not None

    if not has_text:
        # 无中文字体：只画几何装饰，坚决不输出方块乱码
        cx, cy = int(w * 0.62), h // 2
        for r in (70, 110, 150):
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=accent, width=3)
        d.rounded_rectangle([70, h // 2 - 46, 74, h // 2 + 46], radius=2, fill=accent)
        log("cover").warning(
            "未找到中文字体，封面已降级为无文字装饰版。请安装：sudo apt install fonts-noto-cjk"
        )
    else:
        pad = 78
        # 顶部账号名
        d.text((pad, 40), "家 事 安 康 会", font=font_small, fill=accent)
        d.line([(pad, 78), (pad + 118, 78)], fill=accent, width=2)
        # 栏目
        d.text((pad, 96), column, font=font_small, fill=(255, 240, 226))

        # 主标题
        lines = _wrap(d, title, font_big, w - pad * 2 - 170)
        y = 152 if len(lines) > 1 else 178
        for ln in lines:
            # 轻微阴影提升可读性
            d.text((pad + 2, y + 2), ln, font=font_big, fill=(120, 50, 34))
            d.text((pad, y), ln, font=font_big, fill=(255, 252, 246))
            y += fs + 14

        # 底部签名
        d.line([(pad, h - 66), (w - pad, h - 66)], fill=(255, 255, 255), width=1)
        d.text((pad, h - 54), signature, font=font_small, fill=accent)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    log("cover").info(
        "✓ 封面已生成：%s（%dx%d，%s）",
        out_path.name, w, h, "含中文" if has_text else "无文字装饰版",
    )
    return {"path": str(out_path), "has_text": has_text, "font": str(font_big.path) if font_big else ""}
