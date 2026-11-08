# -*- coding: utf-8 -*-
"""AI 配图生成：OpenAI 兼容的 /v1/images/generations 协议。

一套代码兼容国内多家生图服务（硅基流动、阿里百炼、以及任何 OpenAI 兼容网关），
只需在 .env 配 IMAGE_API_KEY，按需改 IMAGE_BASE_URL / IMAGE_MODEL。

合规要点（重要）
--------------
* 《人工智能生成合成内容标识办法》2025-09-01 施行，微信要求发布 AI 生成内容时主动声明。
* 本模块**不重新编码图片**：服务商写入文件元数据的隐式标识会被完整保留；
  显式标识由图注「AI 生成」+ 正文末尾声明实现（见 formatter）。
  刻意不给图片本身加水印/裁切，避免破坏或隐匿隐式标识。
* 正文文字、带字的要点卡仍由程序本地绘制——AI 生成中文极易出错字。
* 生成失败/未配 Key/额度用尽时返回 None，由 illustrator 回退到本地绘制卡，绝不阻断出稿。
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

import requests
from PIL import Image

from .util import log

# 分栏目场景：全部落在「中国普通家庭 / 中老年日常」，避免西方面孔与医院感
TOPIC_SCENES = {
    "family_story": (
        "中国普通人家里的饭桌，几样家常菜、一碗冒着热气的汤、老式木椅与搪瓷杯，"
        "午后阳光从窗户斜照进来，桌面上有岁月使用过的痕迹，安静而有人情味"
    ),
    "inlaw_relation": (
        "中国家庭客厅一角，布艺沙发、茶几上一杯温茶、窗台绿植，"
        "椅背上随意搭着一件外套，光线温暖克制，气氛松弛平和"
    ),
    "senior_health": (
        "清晨公园里长辈散步的背影，或一碗清淡的杂粮粥配应季蔬菜，"
        "或窗边慢慢伸展手臂的剪影，明亮柔和，干净舒展"
    ),
    "default": "中国家庭里安静温暖的一角，自然光，生活气息，构图留白",
}

STYLE = (
    "写实摄影风格，暖色调，自然光，浅景深，生活化，构图留白，质感温润，"
    "适合中老年读者阅读，画面干净不杂乱"
)

NEGATIVE = (
    "画面中不要出现任何文字、字母、数字、水印、logo、招牌；"
    "不要西方面孔；不要卡通、插画、3D 渲染、油画；"
    "不要夸张表情、不要人物正脸特写；不要医疗器械、药片、疾病或医院场景"
)


def build_prompt(topic: str, title: str, cfg: dict) -> str:
    """拼 Prompt：栏目场景 + 本篇线索 + 统一风格 + 负面约束（写进正文以兼容各家）。"""
    a = cfg.get("ai_photo", {})
    scenes = a.get("prompt_by_topic") or TOPIC_SCENES
    scene = scenes.get(topic) or TOPIC_SCENES.get(topic) or TOPIC_SCENES["default"]
    hint = re.sub(r"[^\u4e00-\u9fff]", "", title or "")[:16]
    parts = [
        scene,
        f"贴合本篇主题：{hint}" if hint else "",
        a.get("style_suffix") or STYLE,
        a.get("negative") or NEGATIVE,
    ]
    return "；".join(x for x in parts if x) + "。"


class AIPhotoGenerator:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        a = cfg.get("ai_photo", {})
        self.base_url = (a.get("base_url") or "").rstrip("/")
        self.model = a.get("model") or ""
        self.size = a.get("size") or "1024x1024"
        self.timeout = int(a.get("timeout", 120))
        self.api_key = (cfg.get("image_credentials", {}).get("api_key") or "").strip()

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    @staticmethod
    def _friendly(status: int, body: str) -> str:
        if status in (401, 403):
            return "API Key 无效或该 Key 没有生图权限（401/403）"
        if status == 404:
            return "端点或模型名不对，请核对 IMAGE_BASE_URL / IMAGE_MODEL（404）"
        if status == 429:
            return "调用频率或额度超限（429）"
        if status == 400:
            return f"请求参数被拒（400）：{body[:140]}"
        return f"HTTP {status}：{body[:140]}"

    def _extract(self, data: dict) -> bytes:
        """兼容 data[0].url / data[0].b64_json，以及部分国产 output.results 结构。"""
        items = data.get("data")
        if not items:
            out = data.get("output") or {}
            items = out.get("results") or out.get("images") or []
        if isinstance(items, dict):
            items = [items]
        if not items:
            raise RuntimeError(f"响应中没有图片数据：{str(data)[:180]}")
        first = items[0] or {}

        if first.get("b64_json"):
            raw = str(first["b64_json"])
            if "," in raw[:64]:
                raw = raw.split(",", 1)[1]
            return base64.b64decode(raw)

        url = first.get("url") or first.get("image_url") or first.get("image")
        if isinstance(url, dict):
            url = url.get("url")
        if not url:
            raise RuntimeError(f"无法从响应解析图片地址：{str(first)[:180]}")
        r = requests.get(str(url), timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return r.content

    def generate(self, topic: str, title: str, out_stem: Path) -> dict | None:
        """生成一张配图并原样落盘，返回可插入 illustrator 结果列表的 dict。"""
        if not self.available:
            return None
        prompt = build_prompt(topic, title, self.cfg)
        payload = {"model": self.model, "prompt": prompt, "n": 1, "size": self.size}
        try:
            r = requests.post(
                f"{self.base_url}/images/generations",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
            if r.status_code != 200:
                log("aiphoto").warning(
                    "生图失败：%s", self._friendly(r.status_code, r.text)
                )
                return None
            raw = self._extract(r.json())
        except Exception as e:  # noqa: BLE001
            log("aiphoto").warning("生图调用异常，回退本地绘制卡：%s", str(e)[:180])
            return None

        # 原样写盘，不重编码 —— 保住服务商写入的隐式标识元数据
        ext = ".png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
        path = out_stem.with_suffix(ext)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            with Image.open(path) as im:
                im.verify()
        except Exception as e:  # noqa: BLE001
            path.unlink(missing_ok=True)
            log("aiphoto").warning("生成的图片无效，回退本地绘制卡：%s", str(e)[:120])
            return None

        log("aiphoto").info(
            "✓ AI 配图已生成：%s（%d KB，%.0f 字 Prompt）",
            path.name, path.stat().st_size // 1024, len(prompt),
        )
        return {
            "path": path,
            "name": path.name,
            "caption": "AI 生成 · 氛围示意",
            "source": "ai",
            "prompt": prompt,
        }
