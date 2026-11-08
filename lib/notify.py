# -*- coding: utf-8 -*-
"""通知：草稿就绪后推送到手机，提醒去后台点「发表」。

支持 Server酱、企业微信群机器人、通用 Webhook。未配置时静默跳过。
"""
from __future__ import annotations

import requests

from .util import log

MP_URL = "https://mp.weixin.qq.com/"


def notify_draft(cfg: dict, summary: dict) -> dict:
    n = cfg["notify"]
    if not n.get("enabled") or not n.get("webhook"):
        return {"sent": False, "message": "未配置通知"}
    url = n["webhook"]
    kind = n.get("type", "serverchan")
    if "qyapi.weixin.qq.com" in url:
        kind = "wecom"

    title = f"家事安康会｜草稿已就绪，请点发表"
    review = "（有合规提示，发布前建议扫一眼）" if summary.get("need_review") else ""
    desp = (
        f"**{summary.get('title', '')}**\n\n"
        f"> 栏目：{summary.get('column', '')}　字数：{summary.get('words', 0)}\n\n"
        f"{summary.get('digest', '')}\n\n"
        f"{review}\n\n"
        f"草稿已自动存入公众号草稿箱，请打开后台「内容与互动 → 草稿箱」核对后点发表。\n\n"
        f"[打开公众号后台]({MP_URL})\n\n"
        f"成品文件：{summary.get('files', '')}"
    )

    try:
        if kind == "wecom":
            payload = {"msgtype": "markdown", "markdown": {"content": f"### {title}\n\n{desp}"}}
            r = requests.post(url, json=payload, timeout=n.get("timeout", 10))
        elif kind == "generic":
            r = requests.post(
                url,
                json={"title": title, "content": desp, "summary": summary},
                timeout=n.get("timeout", 10),
            )
        else:  # serverchan
            r = requests.post(
                url,
                data={"title": title, "desp": desp},
                timeout=n.get("timeout", 10),
            )
        ok = r.status_code < 400
        log("notify").info("%s 通知发送：HTTP %s", "✓" if ok else "✗", r.status_code)
        return {"sent": ok, "message": f"HTTP {r.status_code}"}
    except Exception as e:  # noqa: BLE001
        log("notify").warning("通知发送失败：%s", str(e)[:120])
        return {"sent": False, "message": str(e)[:120]}
