# -*- coding: utf-8 -*-
"""通用工具：日志、重试、时间、文本清洗。仅依赖标准库。"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
INPUT_DIR = ROOT / "input"
SAMPLE_DIR = ROOT / "sample"
LOG_DIR = DATA_DIR / "logs"

for _d in (DATA_DIR, OUTPUT_DIR, INPUT_DIR, SAMPLE_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

_LOG_CONFIGURED = False


def setup_logging(level: str = "INFO", to_file: bool = True) -> logging.Logger:
    """配置全局日志（控制台 + 按天滚动的文件）。"""
    global _LOG_CONFIGURED
    logger = logging.getLogger("jazk")
    if _LOG_CONFIGURED:
        return logger
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    if to_file:
        fh = logging.FileHandler(
            LOG_DIR / f"run-{datetime.now():%Y%m}.log", encoding="utf-8"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    _LOG_CONFIGURED = True
    return logger


def log(name: str = "") -> logging.Logger:
    return logging.getLogger("jazk" + ("." + name if name else ""))


def retry(times: int = 3, base_delay: float = 1.5, exceptions=(Exception,)):
    """带指数退避的重试装饰器。"""

    def deco(fn):
        def wrapper(*args, **kwargs):
            last = None
            for i in range(times):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:  # noqa: BLE001
                    last = e
                    if i < times - 1:
                        delay = base_delay * (2 ** i)
                        log("retry").warning(
                            "%s 第 %d/%d 次失败：%s，%.1fs 后重试",
                            fn.__name__, i + 1, times, str(e)[:120], delay
                        )
                        time.sleep(delay)
            raise last

        wrapper.__name__ = fn.__name__
        return wrapper

    return deco


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()


def clean_text(text: str) -> str:
    """去 HTML 标签、压缩空白、去控制字符。"""
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", '"').replace("&#39;", "'")
    )
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def safe_filename(text: str, maxlen: int = 40) -> str:
    """生成可安全用于文件名的字符串（保留中文）。"""
    text = re.sub(r"[\\/:*?\"<>|\r\n\t]", "", text)
    text = re.sub(r"\s+", "-", text).strip("-")
    return (text[:maxlen] or "untitled")


def truncate(text: str, n: int, suffix: str = "…") -> str:
    return text if len(text) <= n else text[: n - len(suffix)] + suffix


def strip_md(text: str) -> str:
    """粗略剥离 Markdown 标记，用于摘要与字数统计。"""
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"[*_`>|\-]{1,}", "", text)
    return clean_text(text)


def cn_len(text: str) -> int:
    """中文按字计数的近似长度。"""
    return len(re.sub(r"\s+", "", text))
