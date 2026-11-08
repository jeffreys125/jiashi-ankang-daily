# -*- coding: utf-8 -*-
"""文章生成：OpenAI 兼容协议的大模型原创写稿 + 无 Key 时的本地降级。

重要：参考素材只作为「选题灵感」进入 Prompt，明确禁止照抄原文句子，
正文由模型原创生成，以规避搬运侵权与公众号原创声明风险。
"""
from __future__ import annotations

import json
import re
from typing import Any

import requests

from . import topics
from .util import cn_len, log, retry, truncate

SYSTEM_PROMPT = """你是微信公众号「家事安康会」的主笔。

【账号定位】分享家长里短家庭故事，聊聊婆媳相处之道，中老年养生健康知识，守护家人平安喜乐。
【目标读者】中老年朋友，以及关心家庭生活的中年读者。
【文风要求】
- 温暖、平实、接地气，像街坊邻居坐在院子里拉家常；短句为主，一段 2~4 句。
- 不用网络流行语、不用夸张标题党、不堆砌辞藻、不煽情、不制造焦虑。
- 不挑动家庭矛盾，不贴「恶婆婆」「刁媳妇」「不孝」这类标签，始终留一份体谅。
- 面向长辈的内容，字号与节奏要照顾阅读舒适度，重要句子可适当加粗。

【硬性底线】
- 全部原创。参考素材只是选题灵感，禁止照抄、改写或拼接其中的任何句子。
- 不编造真实人物、真实新闻、统计数据、医学研究结论。
- 健康类内容只做生活常识科普：不承诺疗效、不写「根治/治愈/包好」、不给用药剂量、
  不推荐具体药品或保健品品牌，涉及身体不适一律引导「及时就医、遵医嘱」。
- 不涉及时政、宗教、投资理财、医疗广告。

【输出格式】只输出一个 JSON 对象，不要 Markdown 代码块，不要解释。字段：
{
  "title": "文章标题，18~28 字，平实有画面感，不耸动",
  "digest": "摘要，60~100 字，用于公众号图文摘要，概括全文并留一点余味",
  "cover_text": "封面短句，不超过 12 字，如「好好说话，就是福气」",
  "body": "正文 Markdown，1200~1800 字。结构：开头一个具体生活场景引子；然后 3~4 个 ## 小标题分段展开；每段短句；适当用 **加粗** 点出关键句；结尾温和收束并引导读者留言互动",
  "image_hints": ["2~3 条配图建议，描述画面即可，不要 URL"]
}"""

TOPIC_RULES = {
    "family_story": """
【本期栏目：家里那点事｜家长里短家庭故事】
- 写一个完整、具体、有细节的小故事，人物用化名（如「李婶」「老周」），场景落在饭桌、菜市场、阳台、小区长椅这类日常处。
- 情节要克制，不洒狗血、不制造冲突博眼球；结尾落在理解、陪伴或一句家常话上。
- 正文最后一行加：（文中人物均为化名，情节为艺术加工，如有雷同纯属巧合）
""",
    "inlaw_relation": """
【本期栏目：好好说话｜婆媳相处之道】
- 立场中立，两边都写到位：既写长辈的来路与不易，也写年轻人的处境与委屈。
- 给 2~3 条今天就能用上的具体做法（一句话怎么说、一件事怎么商量），少讲大道理。
- 强调「不必亲如母女，彼此安稳就好」这类松弛、真实的期待，不给关系打分。
- 禁止使用「必须」「应该」「不孝」等命令式或道德评判措辞。
""",
    "senior_health": """
【本期栏目：安康小课堂｜中老年养生健康知识】
- 只讲生活常识与可操作的小习惯，用「可以留意」「不妨试试」「建议咨询医生」这类表述。
- 正文结尾必须原样保留这句：本文为健康科普与生活分享，不构成医疗建议；身体不适请及时就医，并遵从医生指导。
- 不出现具体药名、剂量、疗程、保健品品牌，不写「根治」「治愈」「包好」「疗效显著」。
- 可提醒读者把体检报告、用药清单整理好，找医生或药师咨询。
""",
}


def _extract_json(text: str) -> dict:
    """容错解析：去掉代码块围栏，截取第一个 { 到最后一个 }。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 再兜一层：去掉控制字符
        return json.loads(re.sub(r"[\x00-\x1f]", " ", text))


def _build_user_prompt(topic: str, ref: list[dict], hints: list[str], cfg: dict) -> str:
    rng = cfg["llm"].get("target_words", [1200, 1800])
    lines = [
        f"请为今天的「{topics.TOPIC_LABELS[topic]}」栏目写一篇原创文章。",
        "",
        "【今日参考素材（仅供选题灵感，严禁照抄其中任何句子）】",
    ]
    for i, r in enumerate(ref[:3], 1):
        src = r.get("source") or "内置选题库"
        angle = r.get("digest") or r.get("angle") or ""
        lines.append(f"{i}. 线索标题：{r['title']}｜切入点：{truncate(angle, 90)}｜来源：{src}")
    if hints:
        lines.append("")
        lines.append("【时令参考】" + "；".join(hints))
    lines += [
        "",
        TOPIC_RULES.get(topic, ""),
        "【关于参考素材】若某些线索带有标题党、吓人或煽动语气，请只取其中的事实话题，"
        "忽略它的语气与措辞，一律按本号平实、温和的风格重写；标题必须自行拟定，不要沿用线索标题。",
        f"【篇幅】正文 {rng[0]}~{rng[1]} 字，不要写太长。",
        "【署名】文末统一带一句：愿每一个家，都平安喜乐。——家事安康会",
        "",
        "现在只输出 JSON 对象。",
    ]
    return "\n".join(lines)


class Generator:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.api_key = cfg["llm_credentials"].get("api_key", "").strip()
        self.base_url = cfg["llm"].get("base_url", "").rstrip("/")
        self.model = cfg["llm"].get("model", "")

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    @retry(times=2, base_delay=2.0)
    def _call_llm(self, user_prompt: str) -> dict:
        url = self.base_url + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.cfg["llm"].get("temperature", 0.8),
            "max_tokens": self.cfg["llm"].get("max_tokens", 3000),
            "stream": False,
        }
        r = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.cfg["llm"].get("timeout", 120),
        )
        if r.status_code != 200:
            raise RuntimeError(f"LLM HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        content = data["choices"][0]["message"].get("content") or ""
        if not content.strip():
            raise RuntimeError("模型返回空内容")
        return _extract_json(content)

    def generate(self, topic: str, ref: list[dict], hints: list[str]) -> dict:
        """返回 {title, digest, cover_text, body, image_hints, generated_by, model}。"""
        if self.available:
            try:
                result = self._call_llm(_build_user_prompt(topic, ref, hints, self.cfg))
                title = (result.get("title") or "").strip()
                body = (result.get("body") or "").strip()
                if not title or cn_len(body) < 300:
                    raise RuntimeError("模型输出过短或字段缺失")
                log("generator").info(
                    "✓ 大模型原创生成：%s（%d 字）", title, cn_len(body)
                )
                return {
                    "title": title,
                    "digest": (result.get("digest") or "").strip(),
                    "cover_text": (result.get("cover_text") or "愿每一个家，都平安喜乐").strip(),
                    "body": body,
                    "image_hints": result.get("image_hints") or [],
                    "fresh_refs": [r["title"] for r in ref if r.get("origin") != "builtin"],
                    "generated_by": "llm",
                    "model": self.model,
                }
            except Exception as e:  # noqa: BLE001
                log("generator").warning("大模型调用失败，降级到本地模板：%s", str(e)[:160])

        return self._local_template(topic, ref, hints)

    # ---------------- 无 Key 降级：结构完整的演示稿 ----------------
    def _local_template(self, topic: str, ref: list[dict], hints: list[str]) -> dict:
        """不依赖任何外部服务，保证流程可跑通、排版可预览。

        产出的文章标注为「本地演示稿」，仅用于验证链路与排版效果；
        配置 LLM_API_KEY 后自动切换为大模型原创稿。
        """
        block = topics.TOPIC_BANK[topic]
        # 标题只取内置常青选题：角度经过打磨、调性稳定。
        # 网络线索可能有标题党语气，绝不能直接拿来当本号的文章标题。
        builtin_refs = [r for r in ref if r.get("origin") == "builtin"]
        main = builtin_refs[0] if builtin_refs else next(
            x for x in topics.all_builtin_items() if x["topic"] == topic
        )
        fresh_refs = [r["title"] for r in ref if r.get("origin") != "builtin"]
        title = main["title"]
        angle = main.get("digest") or main.get("angle") or ""
        season = hints[0] if hints else "日子一天天过，家里的温度最要紧"

        if topic == "senior_health":
            body = f"""**入冬以后，早晚的风明显凉了。** 小区长椅上，几位老邻居照旧坐着晒太阳，手里捧着保温杯。张姨说，最近总觉得起床时头有点晕，想着「年纪大了都这样」，也就没当回事。

一句话说得轻，可身边人都听进去了。今天我们就聊聊「{title}」这件事，不吓人，也不开方子，只说几句能放在日子里的常识。

## 先把「年纪大了」这句话放一放

很多不舒服，长辈习惯往岁数上一推，觉得忍忍就过去了。**可「常见」不等于「不用管」。** 身体给出的信号，值得被认真记一笔：什么时候开始的、多久一次、什么情况下会明显一些。

{season}。把这些小变化写在本子上，去看医生时比凭记忆描述清楚得多。

## 日常里能自己做的几件小事

不必大改生活习惯，先从容易坚持的开始：

- **起居慢半拍**：早上醒来先在床边坐一会儿，再慢慢起身；夜里起夜留一盏不刺眼的小灯。
- **动静结合**：天气好时出门走走，量力而行，不必硬凑步数；觉得累就歇，别跟自己较劲。
- **吃得杂一点**：主食、蔬菜、蛋奶豆制品搭配着来，喝水分次少量，别等口渴才想起。
- **记录别偷懒**：血压、血糖这类指标按医生建议的时间测，记下来，复诊时一起带上。

这些都不是「偏方」，只是把日子过得更规整一些。

## 有这几样情况，别自己扛

> 身体出现明显不适、症状和平时不一样、或者持续几天不见好，最稳妥的做法是及时就医，听医生怎么判断。

还有一件常被忽略的事：药盒里那几种药，别凭感觉加减，也别把别人吃着有效的方子拿来自己试。**用药清单整理好，拿给医生或药师看一遍**，比到处打听更踏实。家里不妨给爸妈备一份小档案：既往病史、正在吃的药、过敏史、紧急联系人，放在抽屉里，用得上的时候不慌。

## 说到底，是有人惦记着

{angle[:60]}。很多时候，长辈缺的不是道理，是有人多问一句、陪着走一趟。

愿每一个家，都平安喜乐。——家事安康会

本文为健康科普与生活分享，不构成医疗建议；身体不适请及时就医，并遵从医生指导。"""
        elif topic == "inlaw_relation":
            body = f"""**饭吃到一半，碗筷声忽然轻了下来。** 一句本来没什么的话，落在两个人耳朵里，却各自转了几个弯。这样的场面，不少家里都遇到过。

今天聊的「{title}」，不想评判谁对谁错。婆媳之间大多数时候，争的其实不是那件事本身，而是「我有没有被放在心上」。

## 先把「猜」字拿掉

一句「您歇着」，说的人是好意，听的人却可能觉得「我是不是帮不上忙了」。**好意隔了一层，就容易变成误会。**

有话不妨直说，但把语气放软：把「你应该」换成「我想请你」，把「你怎么又」换成「我有点担心」。同一个意思，落到心里是两种温度。{season}。

## 两代人，来路本就不同

长辈经历过物资紧的日子，节俭、囤东西、舍不得扔，背后是几十年的习惯；年轻人讲效率、讲边界，也不是不孝顺。**不是谁故意较劲，是各自带着自己的年代进门。**

看明白这一层，很多小火苗就烧不起来。不必说服对方改，先允许「不一样」存在。

## 中间那个人，别只当传话筒

家里最容易被忽略的，是既当儿子又当丈夫的那位。把两边的原话来回传，只会让话越传越硬。

更稳妥的做法是：**各自先听完，再把事说清，不把人评价带进去。** 就事论事，不翻旧账，也不在孩子面前分谁更亲。

## 三件今天就能试的小事

- **把感谢说出口**：一句「妈，今天这菜真合胃口」，比买东西更暖。
- **商量个各退一步的约定**：习惯改不了，就约定具体做法，比讲道理管用。
- **给关系一个松一点的期待**：不必亲如母女，彼此安稳、互相留面子，就已经很好。

{angle[:60]}。相处是慢功夫，不必一天里论出输赢。

你家是怎么把话说开的？欢迎在留言区聊聊，也许正好能帮到另一个人。

愿每一个家，都平安喜乐。——家事安康会"""
        else:
            body = f"""**傍晚的厨房里，锅盖轻轻响了一声。** 李婶把菜端上桌，顺手又把那盘孩子爱吃的往对面推了推。人还没到，位置已经留好了。

这样的细节，家里天天有，小到谁也不会特意记一笔。可许多年后再想起来，最清楚的偏偏就是这些。

## 一件小事，藏着没说出口的话

「{title}」——说的其实就是这份不动声色。长辈表达惦记，很少用「我想你」，多用「多吃点」「路上慢些」「带件外套」。**话越短，心思越沉。**

年轻时我们总急着往外走，觉得这些叮嘱啰嗦；等自己也开始操心别人，才慢慢听懂里头的意思。{season}。

## 两代人之间，隔着的不只是岁数

父亲不太会用手机，却会在深夜发一条语音；母亲把旧照片压在玻璃板下，擦桌子时总顺手抹一遍。他们不是不肯学新东西，是怕打扰，怕添麻烦。

**「我没事」这三个字，有时候最需要被多问一句。** 不必追问到底，坐下来陪着喝杯茶，话自己就出来了。

## 把日子过成可以回看的

- **常联系**：一通没接到的电话，别拖成日后的遗憾。
- **多问问**：请长辈讲讲从前，把老照片背后的名字记下来，这就是家史。
- **留位置**：团圆饭桌上，给不在场的人也留副碗筷，是一种温柔的记挂。

{angle[:60]}。家里的事，大多没有什么大道理，靠的是一遍遍不嫌烦。

你家有没有这样一件小东西，一看见就想起谁？欢迎在留言区说说。

愿每一个家，都平安喜乐。——家事安康会

（文中人物均为化名，情节为艺术加工，如有雷同纯属巧合）"""

        return {
            "title": title,
            "digest": truncate(
                f"{block['column']}｜{title}。{angle} 愿每一个家，都平安喜乐。", 100, ""
            ),
            "cover_text": f"{block['column']}·{truncate(title, 10, '')}",
            "body": body,
            "image_hints": [
                "暖色调的家常场景：饭桌、热汤、窗边的光",
                "长辈与家人并肩说话的侧影，画面松弛",
                "一张留白较多的封面底图，配手写感的短句",
            ],
            "fresh_refs": fresh_refs,
            "generated_by": "local-template-demo",
            "model": "local-template",
        }
