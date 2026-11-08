# -*- coding: utf-8 -*-
"""微信公众平台官方 API 客户端（个人订阅号可用部分）。

个人主体订阅号能力边界（2025-07 起官方调整）：
  ✅ access_token、素材上传、草稿箱 draft/add
  ❌ freepublish/submit 发布接口（调用返回 48001，权限已回收）

因此本程序默认只「建草稿」，最后一步由人在公众号后台点「发表」。
已认证服务号/订阅号可把 wechat.auto_publish 打开，实现真正全自动。

官方文档：https://developers.weixin.qq.com/doc/subscription/guide/product/publish.html
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from .util import DATA_DIR, log, retry

BASE = "https://api.weixin.qq.com/cgi-bin"
TOKEN_CACHE = DATA_DIR / "wx_token.json"

ERR_HINTS = {
    40013: "AppID 无效，请检查 .env 里的 WX_APPID",
    40001: "AppSecret 错误或 access_token 失效，请检查 WX_APPSECRET",
    40125: "AppSecret 无效",
    40164: "调用方 IP 不在白名单：到微信开发者平台把本机公网 IP 加入「API IP 白名单」（curl ifconfig.me 可查）",
    48001: "接口未授权：个人主体订阅号自 2025 年 7 月起已无发布接口权限，草稿已创建，请在公众号后台手动点「发表」",
    40007: "media_id 无效，封面素材可能未上传成功",
    45009: "接口调用超过频率限制，稍后再试",
    41001: "缺少 access_token",
    -1: "微信服务繁忙，稍后重试",
}


class WeChatError(RuntimeError):
    def __init__(self, errcode: int, errmsg: str, api: str = ""):
        self.errcode, self.errmsg, self.api = errcode, errmsg, api
        hint = ERR_HINTS.get(errcode, "")
        super().__init__(
            f"[{api}] errcode={errcode} errmsg={errmsg}" + (f" | 提示：{hint}" if hint else "")
        )


class WeChatClient:
    def __init__(self, cfg: dict, dry_run: bool = False):
        self.cfg = cfg
        self.dry_run = dry_run
        self.appid = cfg["wechat_credentials"].get("appid", "").strip()
        self.secret = cfg["wechat_credentials"].get("appsecret", "").strip()
        self.timeout = 20

    @property
    def configured(self) -> bool:
        return bool(self.appid and self.secret)

    # ---------------- token ----------------
    def _cached_token(self) -> str:
        if not TOKEN_CACHE.exists():
            return ""
        try:
            d = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            if d.get("appid") == self.appid and d.get("expires_at", 0) > time.time() + 120:
                return d.get("access_token", "")
        except Exception:  # noqa: BLE001
            pass
        return ""

    @retry(times=2, base_delay=1.5)
    def token(self) -> str:
        cached = self._cached_token()
        if cached:
            return cached
        if not self.configured:
            raise WeChatError(41001, "未配置 WX_APPID / WX_APPSECRET", "token")
        r = requests.get(
            f"{BASE}/token",
            params={
                "grant_type": "client_credential",
                "appid": self.appid,
                "secret": self.secret,
            },
            timeout=self.timeout,
        )
        d = self._parse(r, "token")
        tok = d["access_token"]
        TOKEN_CACHE.write_text(
            json.dumps({
                "appid": self.appid,
                "access_token": tok,
                "expires_at": time.time() + int(d.get("expires_in", 7200)) - 300,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        log("wechat").info("✓ access_token 获取成功（已缓存）")
        return tok

    @staticmethod
    def _parse(r: requests.Response, api: str) -> dict:
        r.raise_for_status()
        try:
            d = r.json()
        except ValueError as e:
            raise WeChatError(-1, f"非 JSON 响应：{r.text[:100]}", api) from e
        if d.get("errcode", 0) != 0:
            raise WeChatError(int(d.get("errcode", -1)), d.get("errmsg", ""), api)
        return d

    def _url(self, path: str) -> str:
        return f"{BASE}/{path}?access_token={self.token()}"

    # ---------------- 图片 ----------------
    @staticmethod
    def _prepare(path: Path) -> Path:
        """uploadimg 限制 1MB，超大时转 JPEG 压缩。"""
        if path.stat().st_size <= 1024 * 1024:
            return path
        from PIL import Image  # 延迟导入
        jpg = path.with_suffix(".jpg")
        Image.open(path).convert("RGB").save(jpg, "JPEG", quality=86, optimize=True)
        log("wechat").info("封面 PNG 超过 1MB，已转成 JPEG（%.0f KB）", jpg.stat().st_size / 1024)
        return jpg

    @retry(times=2, base_delay=1.5)
    def upload_content_image(self, path: Path) -> str:
        """上传正文内图片，返回可写入 content 的微信 URL（不占素材库）。"""
        p = self._prepare(path)
        with p.open("rb") as f:
            r = requests.post(
                self._url("media/uploadimg"),
                files={"media": (p.name, f, "image/png" if p.suffix == ".png" else "image/jpeg")},
                timeout=30,
            )
        return self._parse(r, "media/uploadimg")["url"]

    @retry(times=2, base_delay=1.5)
    def upload_cover(self, path: Path) -> str:
        """上传永久图片素材作为封面，返回 thumb_media_id。"""
        p = self._prepare(path)
        with p.open("rb") as f:
            r = requests.post(
                self._url("material/add_material") + "&type=image",
                files={"media": (p.name, f, "image/png" if p.suffix == ".png" else "image/jpeg")},
                timeout=30,
            )
        d = self._parse(r, "material/add_material")
        return d["media_id"]

    # ---------------- 草稿 ----------------
    @retry(times=2, base_delay=2.0)
    def add_draft(self, article: dict, content_html: str, thumb_media_id: str) -> str:
        w = self.cfg["wechat"]
        payload = {
            "articles": [{
                "title": article["title"],
                "author": self.cfg["account"].get("author", "家事安康会"),
                "digest": article["digest"],
                "content": content_html,
                "content_source_url": w.get("content_source_url", ""),
                "thumb_media_id": thumb_media_id,
                "need_open_comment": int(w.get("need_open_comment", 1)),
                "only_fans_can_comment": int(w.get("only_fans_can_comment", 0)),
            }]
        }
        r = requests.post(
            self._url("draft/add"),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=30,
        )
        d = self._parse(r, "draft/add")
        media_id = d["media_id"]
        log("wechat").info("✓ 草稿已存入公众号草稿箱：media_id=%s", media_id)
        return media_id

    # ---------------- 发布（可选）----------------
    def publish(self, media_id: str) -> dict:
        """仅认证服务号/订阅号可用。个人号会返回 48001，由调用方友好提示。"""
        r = requests.post(
            self._url("freepublish/submit"),
            data=json.dumps({"media_id": media_id}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=30,
        )
        try:
            d = self._parse(r, "freepublish/submit")
            return {"ok": True, "publish_id": d.get("publish_id", ""), "raw": d}
        except WeChatError as e:
            return {"ok": False, "errcode": e.errcode, "message": str(e), "hint": ERR_HINTS.get(e.errcode, "")}

    # ---------------- 连通性自检 ----------------
    def check(self) -> dict:
        if self.dry_run or not self.configured:
            return {
                "ok": False,
                "message": "未配置 WX_APPID / WX_APPSECRET，当前只能生成成品文件（dry-run 模式）",
            }
        try:
            tok = self.token()
            return {"ok": True, "message": f"access_token 获取成功（{tok[:8]}…）", "appid": self.appid}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": str(e)}


def build_client(cfg: dict, dry_run: bool = False) -> WeChatClient:
    return WeChatClient(cfg, dry_run=dry_run)
