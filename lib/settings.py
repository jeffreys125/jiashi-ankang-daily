# -*- coding: utf-8 -*-
"""配置加载：config.json + .env + 进程环境变量（优先级从低到高）。

设计原则：敏感凭据绝不写进 config.json，只放 .env 或环境变量。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .util import ROOT, log

CONFIG_PATH = ROOT / "config.json"
ENV_PATH = ROOT / ".env"

# 系统环境变量 -> 配置路径的映射（便于 systemd / Docker 注入）
ENV_OVERRIDES = {
    "JAZK_WX_APPID": ("wechat_credentials", "appid"),
    "JAZK_WX_APPSECRET": ("wechat_credentials", "appsecret"),
    "JAZK_LLM_API_KEY": ("llm_credentials", "api_key"),
    "JAZK_LLM_BASE_URL": ("llm", "base_url"),
    "JAZK_LLM_MODEL": ("llm", "model"),
    "JAZK_NOTIFY_WEBHOOK": ("notify", "webhook"),
    "JAZK_IMAGE_API_KEY": ("image_credentials", "api_key"),
    "JAZK_IMAGE_BASE_URL": ("ai_photo", "base_url"),
    "JAZK_IMAGE_MODEL": ("ai_photo", "model"),
    "JAZK_IMAGE_SIZE": ("ai_photo", "size"),
}

DEFAULTS: dict[str, Any] = {
    "account": {
        "name": "家事安康会",
        "author": "家事安康会",
        "intro": "分享家长里短家庭故事，聊聊婆媳相处之道，中老年养生健康知识，守护家人平安喜乐",
        "signature": "愿每一个家，都平安喜乐",
        "audience": "中老年朋友和关心家庭生活的读者",
    },
    "schedule": {"cron": "30 6 * * *", "timezone": "Asia/Shanghai"},
    "topics": {
        "avoid_repeat_days": 30,
        "weights": {
            "family_story": 3,
            "inlaw_relation": 3,
            "senior_health": 4,
        },
    },
    "collector": {
        "timeout": 12,
        "max_items_per_source": 10,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "sources": [],
        "custom_rss": [],
        "manual_file": "input/materials.txt",
        "fallback_to_builtin": True,
    },
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "temperature": 0.8,
        "max_tokens": 3000,
        "timeout": 120,
        "target_words": [1200, 1800],
    },
    "llm_credentials": {"api_key": ""},
    "wechat": {
        "draft_enabled": True,
        "auto_publish": False,
        "need_open_comment": 1,
        "only_fans_can_comment": 0,
        "content_source_url": "",
        "digest_max_len": 110,
    },
    "wechat_credentials": {"appid": "", "appsecret": ""},
    "illustrations": {
        "enabled": True,
        "count": 2,
        "user_dir": "input/images",
        "caption": True,
    },
    "ai_photo": {
        "enabled": True,
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Kwai-Kolors/Kolors",
        "size": "1024x1024",
        "timeout": 120,
        "disclosure": True,
    },
    "image_credentials": {"api_key": ""},
    "cover": {
        "width": 900,
        "height": 383,
        "font_size": 54,
        "sub_font_size": 22,
        "bg_color": [200, 96, 66],
        "accent_color": [247, 232, 210],
    },
    "notify": {
        "enabled": False,
        "type": "serverchan",
        "webhook": "",
        "timeout": 10,
    },
    "compliance": {"strict": True, "max_title_len": 30},
    "runtime": {"log_level": "INFO", "dry_run_default": False},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _parse_dotenv(path: Path) -> dict[str, str]:
    """标准库解析 .env，支持 # 注释和引号。"""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key] = value
    return result


def load_settings() -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULTS))  # 深拷贝
    if CONFIG_PATH.exists():
        try:
            cfg = _deep_merge(cfg, json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            log("settings").error("config.json 解析失败：%s，使用默认配置", e)
    else:
        log("settings").warning("未找到 config.json，使用内置默认配置")

    env = _parse_dotenv(ENV_PATH)
    # .env 中的 Known Key（大小写兼容）
    mapping = {
        "WX_APPID": ("wechat_credentials", "appid"),
        "WX_APPSECRET": ("wechat_credentials", "appsecret"),
        "LLM_API_KEY": ("llm_credentials", "api_key"),
        "LLM_BASE_URL": ("llm", "base_url"),
        "LLM_MODEL": ("llm", "model"),
        "NOTIFY_WEBHOOK": ("notify", "webhook"),
        "IMAGE_API_KEY": ("image_credentials", "api_key"),
        "IMAGE_BASE_URL": ("ai_photo", "base_url"),
        "IMAGE_MODEL": ("ai_photo", "model"),
        "IMAGE_SIZE": ("ai_photo", "size"),
    }
    for key, (sec, field) in mapping.items():
        val = env.get(key) or env.get(key.lower()) or os.environ.get(key)
        if val:
            cfg.setdefault(sec, {})[field] = val

    for key, (sec, field) in ENV_OVERRIDES.items():
        val = os.environ.get(key)
        if val:
            cfg.setdefault(sec, {})[field] = val

    # 通知开关：填了 webhook 就自动启用
    if cfg["notify"].get("webhook"):
        cfg["notify"]["enabled"] = True

    return cfg


def mask(secret: str) -> str:
    if not secret:
        return "(未配置)"
    return secret[:4] + "*" * max(0, len(secret) - 8) + secret[-4:]


def check_credentials(cfg: dict) -> dict[str, bool]:
    """返回各能力就绪状态，供 `main.py check` 使用。"""
    return {
        "llm_原创生成": bool(cfg["llm_credentials"].get("api_key")),
        "wechat_草稿箱": bool(
            cfg["wechat_credentials"].get("appid")
            and cfg["wechat_credentials"].get("appsecret")
        ),
        "微信自动发布": bool(
            cfg["wechat"].get("auto_publish")
            and cfg["wechat_credentials"].get("appid")
        ),
        "消息通知": bool(cfg["notify"].get("webhook")),
        "ai_生图": bool(
            cfg.get("ai_photo", {}).get("enabled", True)
            and cfg.get("image_credentials", {}).get("api_key")
        ),
    }
