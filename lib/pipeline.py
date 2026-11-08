# -*- coding: utf-8 -*-
"""每日主流程编排：采集 → 选题 → 原创写稿 → 合规 → 排版 → 封面 → 建草稿 → 通知。

幂等：同一天正式模式跑成功后再跑会自动跳过（--force 可强制重跑）。
兜底：任何网络源/模型/微信接口失败，都尽量把「本地成品」产出，不空手而归。
"""
from __future__ import annotations

import random
import time
import traceback
from pathlib import Path
from typing import Any

from . import compliance, cover, formatter, store, topics
from .collector import Collector
from .generator import Generator
from .notify import notify_draft
from .util import OUTPUT_DIR, log, safe_filename, setup_logging, today
from .wechat import WeChatClient, WeChatError


def choose_topic(cfg: dict, override: str | None = None) -> str:
    if override:
        if override not in topics.TOPIC_BANK:
            raise ValueError(f"未知主题：{override}，可选 {list(topics.TOPIC_BANK)}")
        return override
    weights = cfg["topics"].get("weights", {}) or {k: 1 for k in topics.TOPIC_BANK}
    last = store.list_articles(1)
    avoid = last[0]["topic"] if last else None
    pool = [t for t in weights if t != avoid] or list(weights)
    w = [max(0.1, weights.get(t, 1)) for t in pool]
    return random.choices(pool, weights=w, k=1)[0]


def _candidates(pool: list[dict], topic: str, days: int) -> list[dict]:
    """按主题筛候选：网络新素材优先，内置选题兜底，剔除近 N 天用过的种子。"""
    fresh, builtin = [], []
    for x in pool:
        if x.get("topic") != topic:
            continue
        if store.seed_used(x["title"], days):
            continue
        (fresh if x.get("origin") != "builtin" else builtin).append(x)
    random.shuffle(fresh)
    random.shuffle(builtin)
    return fresh + builtin


def _pick_refs(cands: list[dict], attempt: int) -> list[dict]:
    """参考素材 = 2 条新鲜线索 + 1 条内置常青选题。

    内置选题必须始终在场：它的角度经过人工打磨、调性稳定，既保证断网可出稿，
    也避免把网络上的标题党语气带进本号的文章。
    """
    fresh = [x for x in cands if x.get("origin") != "builtin"]
    builtin = [x for x in cands if x.get("origin") == "builtin"]
    off = attempt * 2
    ref = fresh[off:off + 2] + builtin[off:off + 1]
    if not ref:
        ref = fresh[:2] + builtin[:1]
    return ref or cands[:3]


def run(
    cfg: dict,
    dry_run: bool = False,
    force: bool = False,
    topic_override: str | None = None,
    no_notify: bool = False,
) -> dict:
    """执行一天的完整流程，返回结果摘要。"""
    setup_logging(cfg["runtime"].get("log_level", "INFO"))
    store.init_db()
    t0 = time.time()

    if not dry_run and store.succeeded_today("full") and not force:
        msg = "今天已成功跑过一次（幂等保护）。如需重跑请加 --force"
        log("pipeline").info(msg)
        return {"skipped": True, "message": msg}

    summary: dict[str, Any] = {
        "day": today(), "dry_run": dry_run, "topic": "", "title": "",
        "status": "", "files": "", "need_review": False,
    }

    try:
        # ---------- 1. 采集 ----------
        log("pipeline").info("=" * 60)
        log("pipeline").info("开始每日流程：%s（%s）", today(), "dry-run 本地模式" if dry_run else "正式模式")
        collector = Collector(cfg)
        pool = collector.collect()
        summary["sources"] = collector.health
        store.save_materials(pool)

        # ---------- 2. 选题 ----------
        topic = choose_topic(cfg, topic_override)
        days = cfg["topics"].get("avoid_repeat_days", 30)
        cands = _candidates(pool, topic, days)
        if not cands:  # 选题库被用尽 → 清空该主题的历史限制，重新开始一轮
            log("pipeline").warning("该主题候选已用尽，重置选题去重窗口")
            with store.conn() as c:
                c.execute("DELETE FROM used_seeds WHERE topic=?", (topic,))
            cands = _candidates(pool, topic, days)
        if not cands:
            cands = [x for x in topics.all_builtin_items() if x["topic"] == topic]
        block = topics.TOPIC_BANK[topic]
        log("pipeline").info("今日栏目：%s｜候选 %d 条", block["label"], len(cands))

        # ---------- 3. 原创写稿 ----------
        gen = Generator(cfg)
        hints = topics.season_hints()
        article, seed = None, None
        for attempt in range(2):
            ref = _pick_refs(cands, attempt)
            seed = next((x for x in ref if x.get("origin") == "builtin"), ref[0])
            result = gen.generate(topic, ref, hints)
            result["topic"] = topic
            checked = compliance.check(result, cfg)
            if not (attempt == 0 and store.is_duplicate(checked["title"], days)):
                article = {**result, **checked}
                break
            log("pipeline").warning("生成的标题撞车，换一组参考素材重写一次")
        if article is None:
            raise RuntimeError("文章生成失败")

        store.mark_seed(seed["title"], topic)
        summary.update({
            "topic": topic,
            "topic_label": block["label"],
            "column": block["column"],
            "title": article["title"],
            "digest": article["digest"],
            "words": article["words"],
            "generated_by": article["generated_by"],
            "model": article["model"],
            "need_review": article["need_review"],
            "compliance_issues": article["issues"],
            "compliance_changed": article["changed"],
        })
        log("pipeline").info(
            "成稿：《%s》 %d 字｜生成方式 %s", article["title"], article["words"], article["generated_by"]
        )

        # ---------- 4. 文件产出 ----------
        outdir = OUTPUT_DIR / today()
        outdir.mkdir(parents=True, exist_ok=True)
        base = safe_filename(article["title"])
        md_path = outdir / f"{base}.md"
        html_path = outdir / f"{base}.html"
        preview_path = outdir / f"{base}.preview.html"
        cover_path = outdir / "cover.png"

        cover_info = cover.generate_cover(
            cover_path, article["title"], block["column"],
            cfg["account"].get("signature", ""), cfg,
        )
        md_text = formatter.build_markdown(article, article["body"], block["column"])
        md_path.write_text(md_text, encoding="utf-8")

        # 先落一条文章记录，后续草稿记录可以关联它
        article_id = store.save_article({
            **summary,
            "compliance": article["issues"],
            "md_path": str(md_path), "html_path": str(html_path),
            "cover_path": str(cover_path), "status": "generated",
        })
        summary["article_id"] = article_id

        is_original = article["generated_by"] == "llm"
        # 本地预览版：头图用同目录相对路径
        preview_inner = formatter.render_wechat_html(
            article, article["body"], block["column"], block["color"],
            head_image_url="cover.png", is_original=is_original,
        )
        preview_path.write_text(formatter.wrap_preview(preview_inner, article["title"]), encoding="utf-8")
        summary["files"] = str(outdir)

        # ---------- 5. 微信草稿 ----------
        wx = WeChatClient(cfg, dry_run=dry_run)
        status = "local_only"
        draft_note = ""
        content_html = formatter.render_wechat_html(
            article, article["body"], block["column"], block["color"],
            head_image_url="", is_original=is_original,
        )

        if dry_run:
            draft_note = "dry-run：未调用微信接口，成品已生成在本地"
            html_path.write_text(content_html, encoding="utf-8")
            log("pipeline").info("dry-run 模式，跳过微信接口")

        elif not wx.configured or not cfg["wechat"].get("draft_enabled", True):
            draft_note = "未配置公众号凭据或已关闭草稿功能，仅产出本地成品"
            html_path.write_text(content_html, encoding="utf-8")
            log("pipeline").warning(draft_note)

        else:
            thumb_id = ""
            head_url = ""
            try:
                thumb_id = wx.upload_cover(cover_path)
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"封面上传失败（草稿必须要有封面）：{e}") from e
            try:
                head_url = wx.upload_content_image(cover_path)
                content_html = formatter.render_wechat_html(
                    article, article["body"], block["column"], block["color"],
                    head_image_url=head_url, is_original=is_original,
                )
            except Exception as e:  # noqa: BLE001
                log("pipeline").warning("正文头图上传失败，改用无头图版本：%s", str(e)[:120])
            html_path.write_text(content_html, encoding="utf-8")

            media_id = wx.add_draft(article, content_html, thumb_id)
            status = "draft_ok"
            draft_note = "草稿已存入公众号草稿箱，请到后台点「发表」"
            store.save_draft({
                "article_id": article_id, "media_id": media_id, "status": status,
                "message": draft_note,
            })

            # 自动发布（仅认证号可用）
            if cfg["wechat"].get("auto_publish", False):
                pub = wx.publish(media_id)
                if pub["ok"]:
                    status = "published"
                    draft_note = "已通过 freepublish 接口自动发布"
                    store.save_draft({
                        "article_id": article_id, "media_id": media_id,
                        "status": status, "publish_result": "ok",
                        "message": draft_note,
                    })
                else:
                    draft_note = pub.get("hint") or pub.get("message") or "发布失败"
                    log("pipeline").warning("自动发布未成功：%s", draft_note)
                    store.save_draft({
                        "article_id": article_id, "media_id": media_id,
                        "status": "publish_failed",
                        "publish_result": str(pub.get("errcode", "")),
                        "message": draft_note,
                    })

        # ---------- 6. 落库 ----------
        store.update_article(
            article_id, status=status, html_path=str(html_path),
            cover_path=str(cover_path), words=article["words"],
        )
        summary["status"] = status
        summary["draft_note"] = draft_note
        summary["cover_has_text"] = cover_info["has_text"]
        summary["md_path"] = str(md_path)
        summary["html_path"] = str(html_path)
        summary["preview_path"] = str(preview_path)
        summary["cover_path"] = str(cover_path)

        # ---------- 7. 通知 ----------
        if not dry_run and not no_notify and status in ("draft_ok", "published"):
            summary["notify"] = notify_draft(cfg, summary)

        store.mark_run("full", "success", f"{status} | {article['title']}", time.time() - t0)
        log("pipeline").info("完成：%s（耗时 %.1fs）", draft_note, time.time() - t0)
        log("pipeline").info("成品目录：%s", outdir)
        return summary

    except Exception as e:  # noqa: BLE001
        log("pipeline").error("流程失败：%s", e)
        log("pipeline").debug(traceback.format_exc())
        store.mark_run("full", "failed", str(e), time.time() - t0)
        summary["status"] = "failed"
        summary["error"] = str(e)
        summary["traceback"] = traceback.format_exc()
        return summary
