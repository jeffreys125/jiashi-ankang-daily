# -*- coding: utf-8 -*-
"""SQLite 存储：素材库、文章、草稿、运行记录 + 选题去重 + 当日幂等。

只用标准库 sqlite3，服务器无需额外装数据库。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable

from .util import DATA_DIR, days_ago, log, md5, now_str, today

DB_PATH = DATA_DIR / "jazk.db"
_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    topic TEXT,
    title TEXT NOT NULL,
    digest TEXT,
    url TEXT,
    source TEXT,
    origin TEXT,
    hash TEXT UNIQUE,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_materials_day ON materials(day);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    topic TEXT,
    topic_label TEXT,
    column TEXT,
    title TEXT NOT NULL,
    digest TEXT,
    md_path TEXT,
    html_path TEXT,
    cover_path TEXT,
    words INTEGER,
    llm_model TEXT,
    compliance TEXT,
    status TEXT DEFAULT 'generated',
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_articles_day ON articles(day);
CREATE INDEX IF NOT EXISTS idx_articles_title ON articles(title);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER,
    day TEXT,
    media_id TEXT,
    status TEXT,
    publish_result TEXT,
    message TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    stage TEXT,
    status TEXT,
    message TEXT,
    elapsed REAL,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_day ON runs(day);

CREATE TABLE IF NOT EXISTS used_seeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    topic TEXT,
    seed_title TEXT,
    hash TEXT UNIQUE,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_seeds_day ON used_seeds(day);
"""


@contextmanager
def conn():
    with _LOCK:
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
    log("store").debug("数据库就绪：%s", DB_PATH)


def save_materials(items: Iterable[dict]) -> int:
    """写入素材，hash 去重，返回新增条数。"""
    n = 0
    with conn() as c:
        for it in items:
            h = md5((it.get("title") or "") + "|" + (it.get("url") or ""))
            try:
                c.execute(
                    """INSERT INTO materials
                       (day,topic,title,digest,url,source,origin,hash,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        today(), it.get("topic"), it.get("title", ""),
                        it.get("digest", ""), it.get("url", ""),
                        it.get("source", ""), it.get("origin", ""), h, now_str(),
                    ),
                )
                n += 1
            except sqlite3.IntegrityError:
                pass
    return n


def _ngrams(text: str, n: int = 2) -> set[str]:
    text = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff" or ch.isalnum())
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def similarity(a: str, b: str) -> float:
    """中文字符二元组 Jaccard 相似度，用于近似选题查重。"""
    sa, sb = _ngrams(a), _ngrams(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def recent_titles(days: int = 30) -> list[str]:
    with conn() as c:
        rows = c.execute(
            "SELECT title FROM articles WHERE day >= ?", (days_ago(days),)
        ).fetchall()
    return [r["title"] for r in rows]


def is_duplicate(title: str, days: int = 30, threshold: float = 0.55) -> bool:
    for used in recent_titles(days):
        if similarity(title, used) >= threshold:
            log("store").info("选题与近 %d 天《%s》相似，跳过", days, used)
            return True
    return False


def save_article(a: dict) -> int:
    with conn() as c:
        cur = c.execute(
            """INSERT INTO articles
               (day,topic,topic_label,column,title,digest,md_path,html_path,
                cover_path,words,llm_model,compliance,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                today(), a.get("topic"), a.get("topic_label"), a.get("column"),
                a.get("title"), a.get("digest"), a.get("md_path"),
                a.get("html_path"), a.get("cover_path"), a.get("words", 0),
                a.get("llm_model", ""),
                json.dumps(a.get("compliance", {}), ensure_ascii=False),
                a.get("status", "generated"), now_str(),
            ),
        )
        return cur.lastrowid


def update_article(article_id: int, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE articles SET {sets} WHERE id=?", (*fields.values(), article_id))


def save_draft(d: dict) -> int:
    with conn() as c:
        cur = c.execute(
            """INSERT INTO drafts
               (article_id,day,media_id,status,publish_result,message,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                d.get("article_id"), today(), d.get("media_id", ""),
                d.get("status", ""), d.get("publish_result", ""),
                d.get("message", ""), now_str(),
            ),
        )
        return cur.lastrowid


def mark_run(stage: str, status: str, message: str = "", elapsed: float = 0.0) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO runs (day,stage,status,message,elapsed,created_at) VALUES (?,?,?,?,?,?)",
            (today(), stage, status, message[:500], elapsed, now_str()),
        )


def succeeded_today(stage: str = "full") -> bool:
    with conn() as c:
        row = c.execute(
            "SELECT 1 FROM runs WHERE day=? AND stage=? AND status='success' LIMIT 1",
            (today(), stage),
        ).fetchone()
    return row is not None


def seed_used(seed_title: str, days: int = 30) -> bool:
    """内置选题在近 N 天内是否已被用过，保证每天不撞题。"""
    with conn() as c:
        row = c.execute(
            "SELECT 1 FROM used_seeds WHERE day >= ? AND hash=? LIMIT 1",
            (days_ago(days), md5(seed_title)),
        ).fetchone()
    return row is not None


def mark_seed(seed_title: str, topic: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO used_seeds (day,topic,seed_title,hash,created_at) VALUES (?,?,?,?,?)",
            (today(), topic, seed_title, md5(seed_title), now_str()),
        )


def list_articles(limit: int = 10) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM articles ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def list_runs(limit: int = 20) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def stats() -> dict:
    with conn() as c:
        def one(sql, args=()):
            return c.execute(sql, args).fetchone()[0]
        return {
            "素材总数": one("SELECT COUNT(*) FROM materials"),
            "已生成文章": one("SELECT COUNT(*) FROM articles"),
            "已进入草稿箱": one("SELECT COUNT(*) FROM drafts WHERE status='draft_ok'"),
            "已发布": one("SELECT COUNT(*) FROM drafts WHERE status='published'"),
            "累计运行次数": one("SELECT COUNT(*) FROM runs"),
        }
