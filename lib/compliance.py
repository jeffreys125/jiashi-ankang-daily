# -*- coding: utf-8 -*-
"""合规检查：健康科普风险词、广告法极限词、版权与虚构声明、标题/摘要长度。

设计取向：不阻断出稿（避免断更），而是自动修正 + 标记「需人工复核」，
并在通知里提示。养生健康类内容尤其需要这层兜底。
"""
from __future__ import annotations

import re
from typing import Any

from .util import cn_len, log, truncate

# 命中即尽量替换的夸大/违规表述
REPLACEMENTS: dict[str, str] = {
    "根治": "改善", "治愈": "缓解", "包治": "有助于", "包好": "有帮助",
    "药到病除": "逐步调养", "疗效显著": "或有帮助", "特效药": "相关药物",
    "无副作用": "相对温和", "保证见效": "值得尝试", "彻底痊愈": "明显好转",
    "100%有效": "多数人反馈不错", "完全康复": "逐步恢复",
    "最佳": "合适", "最好": "较好", "最强": "不错", "国家级": "正规",
    "第一品牌": "常见品牌", "绝对": "相对", "顶级": "不错",
}

# 命中后只提示、不自动改写（需结合上下文人工判断）
WARN_PATTERNS = {
    "无出处权威表述": ["研究表明", "专家指出", "数据显示", "临床证明", "科学证实"],
    "用药剂量": [r"\d+\s*(?:mg|毫升|克|片|粒|次/日)", r"每日\s*[一二三]\s*次[，,]\s*每次"],
    "具体药品或保健品营销": ["处方", "疗程", "停药", "替代药物", "保健品可治", "服用后立即"],
    "极限承诺": ["永不复发", "一劳永逸", "立竿见影", "三天见效"],
    "对立标签": ["恶婆婆", "刁媳妇", "不孝", "白眼狼"],
    "时政宗教": ["两会", "政治局", "总书记", "选举", "宗教", "信仰治疗"],
}

NEGATION = ["别", "不", "勿", "莫", "谨防", "警惕", "避免", "不是", "切忌", "切勿", "别信", "轻信", "声称"]

# 标题党/耸动措辞：只提示复核，不自动改写（改标题容易破坏语义）
TITLE_RISK = [
    "举报", "曝光", "震惊", "竟然", "意想不到", "紧急提醒", "千万别", "别怪",
    "速看", "速转", "必看", "太可怕", "吓人", "抢救", "猝死", "悲剧", "出事",
    "后悔", "晚了", "赶紧", "太吓", "当心", "警惕", "小心", "哭", "泪目",
]

HEALTH_DISCLAIMER = "本文为健康科普与生活分享，不构成医疗建议；身体不适请及时就医，并遵从医生指导。"
STORY_DISCLAIMER = "（文中人物均为化名，情节为艺术加工，如有雷同纯属巧合）"
SIGNATURE = "愿每一个家，都平安喜乐。——家事安康会"


def _negated(text: str, pos: int, window: int = 14) -> bool:
    left = text[max(0, pos - window):pos]
    return any(w in left for w in NEGATION)


def _check_warn(body: str) -> list[dict]:
    issues = []
    for category, patterns in WARN_PATTERNS.items():
        for p in patterns:
            for m in re.finditer(p, body):
                if _negated(body, m.start()):
                    continue
                issues.append({
                    "level": "warn", "category": category,
                    "text": m.group(0)[:40],
                })
                break  # 每类最多报一处，避免刷屏
    return issues


def check(article: dict, cfg: dict) -> dict:
    """输入生成结果，输出修正后的内容与检查报告。"""
    topic = article.get("topic", "family_story")
    strict = cfg["compliance"].get("strict", True)
    max_title = cfg["compliance"].get("max_title_len", 30)
    digest_max = cfg["wechat"].get("digest_max_len", 110)

    title = (article.get("title") or "").strip()
    body = (article.get("body") or "").strip()
    digest = (article.get("digest") or "").strip()
    issues: list[dict] = []
    changed = False

    # --- 标题 ---
    if not title:
        title = "家里的日子，慢慢过"
        issues.append({"level": "error", "category": "标题缺失", "text": "已使用兜底标题"})
    if len(title) > max_title:
        cut = title[:max_title]
        # 尽量在标点处收尾
        m = list(re.finditer(r"[，。！？、；：,!?;]", cut))
        if m and m[-1].end() > max_title * 0.6:
            cut = cut[: m[-1].start()]
        title = cut.rstrip("，。！？、；：,!?; ")
        issues.append({"level": "warn", "category": "标题过长", "text": "已截断"})
        changed = True

    for w in TITLE_RISK:
        if w in title:
            issues.append({
                "level": "warn", "category": "标题耸动",
                "text": f"含「{w}」，与本号平实调性不符，建议发布前改一版标题",
            })

    # --- 正文夸大表述修正 ---
    for bad, good in REPLACEMENTS.items():
        for m in list(re.finditer(re.escape(bad), body)):
            if _negated(body, m.start()):
                continue
            body = body.replace(bad, good, 1)
            issues.append({"level": "info", "category": "夸大表述", "text": f"{bad} → {good}"})
            changed = True
            break

    # --- 风险提示 ---
    issues += _check_warn(body)

    # --- 必备声明 ---
    disclaimer_added = False
    if topic == "senior_health" and HEALTH_DISCLAIMER not in body:
        body = body.rstrip() + "\n\n" + HEALTH_DISCLAIMER
        disclaimer_added = True
        changed = True
    if topic == "family_story" and STORY_DISCLAIMER not in body:
        body = body.rstrip() + "\n\n" + STORY_DISCLAIMER
        changed = True
    if SIGNATURE not in body:
        body = body.rstrip() + "\n\n" + SIGNATURE
        changed = True

    # --- 摘要 ---
    if not digest:
        digest = truncate(title + "。" + "愿每一个家，都平安喜乐。", digest_max, "")
    if len(digest) > digest_max:
        digest = truncate(digest, digest_max, "")
        changed = True

    errors = [i for i in issues if i["level"] == "error"]
    warns = [i for i in issues if i["level"] == "warn"]
    need_review = bool(warns) or bool(errors)

    log("compliance").info(
        "合规检查：%d 项提示 / 需复核=%s / 字数=%d / 免责声明补充=%s",
        len(issues), need_review, cn_len(body), disclaimer_added,
    )
    for i in issues[:8]:
        log("compliance").debug("  [%s] %s: %s", i["level"], i["category"], i["text"])

    return {
        "passed": not errors,
        "need_review": need_review,
        "issues": issues,
        "strict": strict,
        "title": title,
        "digest": digest,
        "body": body,
        "cover_text": article.get("cover_text", ""),
        "changed": changed,
        "disclaimer_added": disclaimer_added,
        "words": cn_len(body),
    }
