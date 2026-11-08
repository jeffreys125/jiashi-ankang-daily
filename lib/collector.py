# -*- coding: utf-8 -*-
"""多源采集器。

采集目标**只是选题灵感与事实线索**，不是正文。正文一律由大模型原创生成，
这样既避开搬运侵权，也符合公众号原创声明的要求。

支持四类来源：
  1. portal    官方媒体栏目页，抓 <a> 标题（人民网健康、中新网健康等，实测可用）
  2. rss       自定义公开 RSS / Atom（标准库解析，不引入 feedparser）
  3. manual    input/materials.txt 手动录入的线索
  4. builtin   内置常青选题库（断网兜底，保证每天出稿）

合规：遵守 robots 精神，只取公开列表页的标题与链接，不抓正文、不登录、
不绕过反爬、不高频请求（每个源一次 GET）。
"""
from __future__ import annotations

import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import requests
from bs4 import BeautifulSoup

from . import topics
from .util import INPUT_DIR, ROOT, clean_text, log, md5, retry

UA_DEFAULT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class Collector:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.c = cfg["collector"]
        self.f = self.c.get("filters", {})
        self.timeout = self.c.get("timeout", 12)
        self.ua = self.c.get("user_agent", UA_DEFAULT)
        self.limit = self.c.get("max_items_per_source", 10)
        self.health: list[dict] = []

    # ---------------- 公共入口 ----------------
    def collect(self) -> list[dict]:
        items: list[dict] = []
        items += self._from_portals()
        items += self._from_rss()
        items += self._from_manual()

        before = len(items)
        items = self._filter(items)
        log("collector").info(
            "网络采集 %d 条 → 过滤后 %d 条", before, len(items)
        )

        # 内置选题库始终并入：既补充家庭/婆媳题材，也做断网兜底
        builtin = topics.all_builtin_items()
        items += builtin
        log("collector").info(
            "并入内置选题库 %d 条，候选池共 %d 条", len(builtin), len(items)
        )

        # 同批去重
        seen, uniq = set(), []
        for it in items:
            h = md5(it["title"] + "|" + it.get("url", ""))
            if h in seen:
                continue
            seen.add(h)
            uniq.append(it)
        return uniq

    def pick_reference(self, pool: list[dict], topic: str, used_titles: set[str], n: int = 3) -> list[dict]:
        """为指定主题挑 n 条参考素材：优先新鲜网络素材，其次内置选题。"""
        fresh = [
            x for x in pool
            if x.get("topic") == topic
            and x.get("origin") != "builtin"
            and x["title"] not in used_titles
        ]
        builtin = [
            x for x in pool
            if x.get("topic") == topic
            and x.get("origin") == "builtin"
            and x["title"] not in used_titles
        ]
        picked = fresh[: max(0, n - 1)] + builtin
        return picked[:n]

    # ---------------- 1. 栏目页 ----------------
    @retry(times=2, base_delay=1.0)
    def _fetch(self, url: str) -> str:
        r = requests.get(
            url,
            headers={"User-Agent": self.ua, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.content.decode(self._guess_encoding(r), errors="ignore")

    @staticmethod
    def _guess_encoding(resp: requests.Response) -> str:
        m = re.search(rb'charset=["\']?([\w-]+)', resp.content[:4000], re.I)
        if m:
            enc = m.group(1).decode("ascii", "ignore").lower()
            if enc in ("gb2312", "gbk", "gb18030"):
                return "gb18030"
            return enc
        return resp.apparent_encoding or "utf-8"

    def _from_portals(self) -> list[dict]:
        out: list[dict] = []
        for src in self.c.get("sources", []):
            if not src.get("enabled") or src.get("type") != "portal":
                continue
            name, url = src.get("name", ""), src.get("url", "")
            try:
                html = self._fetch(url)
                soup = BeautifulSoup(html, "html.parser")
                cnt = 0
                for a in soup.find_all("a", href=True):
                    title = clean_text(a.get_text(" ", strip=True))
                    if not title:
                        continue
                    href = urllib.parse.urljoin(url, a["href"])
                    out.append({
                        "topic": src.get("topic", "senior_health"),
                        "topic_label": topics.TOPIC_LABELS.get(src.get("topic"), ""),
                        "column": topics.TOPIC_BANK.get(src.get("topic"), {}).get("column", ""),
                        "color": topics.TOPIC_BANK.get(src.get("topic"), {}).get("color", "#C0603C"),
                        "title": title,
                        "digest": "",
                        "url": href,
                        "source": name,
                        "origin": "portal",
                        "tags": [],
                    })
                    cnt += 1
                    if cnt >= self.limit * 6:  # 先多取一些，后面按关键词筛
                        break
                self.health.append({"source": name, "ok": True, "raw": cnt})
                log("collector").info("✓ %-12s 抓到 %d 个链接", name, cnt)
                time.sleep(0.6)  # 礼貌间隔
            except Exception as e:  # noqa: BLE001
                self.health.append({"source": name, "ok": False, "error": str(e)[:100]})
                log("collector").warning("✗ %-12s 采集失败：%s", name, str(e)[:100])
        return out

    # ---------------- 2. 自定义 RSS ----------------
    def _from_rss(self) -> list[dict]:
        out: list[dict] = []
        for src in self.c.get("custom_rss", []):
            if not src.get("enabled") or not src.get("url"):
                continue
            name = src.get("name", "自定义RSS")
            try:
                r = requests.get(src["url"], headers={"User-Agent": self.ua}, timeout=self.timeout)
                r.raise_for_status()
                root = ET.fromstring(r.content)
                ns = {"a": "http://www.w3.org/2005/Atom"}
                entries = root.findall(".//item") or root.findall(".//a:entry", ns)
                for e in entries[: self.limit]:
                    def tx(*paths):
                        for p in paths:
                            node = e.find(p, ns) if ":" in p else e.find(p)
                            if node is not None and (node.text or node.get("href")):
                                return (node.text or node.get("href") or "").strip()
                        return ""
                    title = clean_text(tx("title", "a:title"))
                    link = tx("link", "a:link")
                    digest = clean_text(tx("description", "summary", "a:summary"))[:160]
                    if not title:
                        continue
                    t = src.get("topic", "family_story")
                    out.append({
                        "topic": t, "topic_label": topics.TOPIC_LABELS.get(t, ""),
                        "column": topics.TOPIC_BANK.get(t, {}).get("column", ""),
                        "color": topics.TOPIC_BANK.get(t, {}).get("color", "#C0603C"),
                        "title": title, "digest": digest, "url": link,
                        "source": name, "origin": "rss", "tags": [],
                    })
                self.health.append({"source": name, "ok": True, "raw": len(entries)})
                log("collector").info("✓ %-12s RSS %d 条", name, len(entries))
            except Exception as e:  # noqa: BLE001
                self.health.append({"source": name, "ok": False, "error": str(e)[:100]})
                log("collector").warning("✗ %-12s RSS 失败：%s", name, str(e)[:100])
        return out

    # ---------------- 3. 手动素材 ----------------
    def _from_manual(self) -> list[dict]:
        rel = self.c.get("manual_file", "input/materials.txt")
        path = ROOT / rel
        out: list[dict] = []
        if not path.exists():
            return out
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            title = parts[0] if parts else ""
            if not title:
                continue
            digest = parts[1] if len(parts) > 1 else ""
            url = parts[2] if len(parts) > 2 else ""
            t = "family_story"
            out.append({
                "topic": t, "topic_label": topics.TOPIC_LABELS[t],
                "column": topics.TOPIC_BANK[t]["column"],
                "color": topics.TOPIC_BANK[t]["color"],
                "title": title, "digest": digest, "url": url,
                "source": "手动素材", "origin": "manual", "tags": [],
            })
        if out:
            log("collector").info("✓ 手动素材 %d 条", len(out))
        return out

    # ---------------- 4. 过滤 ----------------
    def _filter(self, items: list[dict]) -> list[dict]:
        min_len = self.f.get("min_len", 8)
        max_len = self.f.get("max_len", 46)
        excludes = self.f.get("exclude", [])
        include_map = self.f.get("include_by_topic", {})
        cross = self.f.get("cross_topic_exclude", {})
        out: list[dict] = []
        for it in items:
            title = it["title"]
            if not (min_len <= len(title) <= max_len):
                continue
            if not re.search(r"[\u4e00-\u9fff]{4,}", title):
                continue
            if any(w in title for w in excludes):
                continue
            # 防止家庭/婆媳栏目混入医疗健康稿
            if any(w in title for w in cross.get(it.get("topic", ""), [])):
                continue
            kws = include_map.get(it.get("topic", ""), [])
            if kws and not any(w in title for w in kws):
                continue
            out.append(it)
        return out
