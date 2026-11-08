# 家事安康会 · 每日内容助手

一套跑在 Linux 服务器上的 Python 程序，每天定时完成：**采集选题灵感 → 大模型原创写稿 → 公众号排版与封面 → 自动存入公众号草稿箱 → 手机推送提醒**。你每天只需要在公众号后台点一下「发表」。

Python 3.9+，只依赖 `requests / beautifulsoup4 / Pillow`，不需要数据库服务（用 SQLite）。

---

## 一、先说一件必须知道的事

> **个人主体订阅号无法用程序「直接发表」文章。** 微信官方自 **2025 年 7 月**起，回收了个人主体账号、未认证企业账号、不支持认证账号的**发布能力接口（`freepublish`）**调用权限，强行调用返回 `48001` [^1][^2]。但个人号**仍可用官方 API 创建草稿、上传封面和正文图片** [^3]。

| 能力 | 个人订阅号（你的情况） | 已认证服务号 / 订阅号 |
| --- | :---: | :---: |
| 获取 `access_token` | ✅ | ✅ |
| 上传图片素材、正文图 | ✅ | ✅ |
| **新建草稿 `draft/add`** | ✅ **本程序用这个** | ✅ |
| 发布 `freepublish/submit` | ❌ 权限已回收 | ✅ |
| 每天群发次数 | 1 条 | 1 条（订阅号）|
| 微信认证 | 个人号不支持 | 需企业主体，约 300 元/年 |

所以本程序的定位是「**自动出稿 + 自动进草稿箱**」，最后一步人工确认。这是官方允许、零封号风险的做法。如果你以后换成**已认证的服务号/订阅号**，把 `config.json` 里 `wechat.auto_publish` 改成 `true`，就能真正做到全自动发表。

程序**不使用**浏览器模拟登录、不逆向接口、不群发脚本——只用微信官方开放 API，安全边界清晰。

[^1]: [微信官方文档 · 发布能力](https://developers.weixin.qq.com/doc/subscription/guide/product/publish.html)
[^2]: [微信开放社区 · 文章发布与群发功能说明](https://developers.weixin.qq.com/community/develop/doc/000a06bca74460a48a34ec71061000)
[^3]: [实战复盘 · 个人号用官方 API 一键建草稿](http://mp.weixin.qq.com/s?__biz=MzU4OTgzMjg3NA==&mid=2247483799&idx=1&sn=18cde9d918dd9a6c49119a4afc82e581)

---

## 二、它每天做什么

| 步骤 | 做了什么 | 兜底策略 |
| --- | --- | --- |
| 1. 采集 | 抓取 5 个官方媒体栏目页的**公开标题**作为选题灵感，按关键词过滤掉时政/广告/标题党 | 源全挂也能出稿 |
| 2. 选题 | 三大栏目按权重轮换，避开前一天栏目；近 30 天用过的选题自动排除 | 内置 **60 条常青选题**兜底 |
| 3. 写稿 | 把选题角度 + 季节提示交给大模型，生成 **1200~1800 字原创文**，自拟标题与摘要 | 没配 API Key 时用本地模板出演示稿 |
| 4. 合规 | 过滤夸大疗效、广告法极限词、标题党；健康类强制加免责声明，故事类强制加化名声明 | 标注「需复核」并推送提醒 |
| 5. 排版 | 转成**全内联样式**的公众号 HTML（中老年友好：17px 字、1.9 行高、大留白） | — |
| 6. 封面 | 本地绘制 900×383 暖色封面，含栏目与标题 | 无中文字体时降级为无文字装饰版 |
| 7. 建草稿 | 官方 API 上传封面 → 上传正文图 → `draft/add` 存入草稿箱 | 失败也不丢本地成品 |
| 8. 提醒 | Server酱 / 企业微信机器人推送「草稿已就绪」 | 未配置则只写日志 |

**幂等保护**：同一天正式跑成功后重复触发会自动跳过，不会产生两篇草稿。

---

## 三、快速开始（5 步）

```bash
cd jiashi-ankang-daily

# 1) 装依赖 + 建库 + 生成 .env
bash deploy/install.sh

# 2) 填凭据（见下一节）
vi .env

# 3) 自检，并实测每个采集源是否通
.venv/bin/python main.py check --probe

# 4) 本地试跑：只生成成品文件，不碰微信接口
.venv/bin/python main.py run --dry-run

# 5) 看效果（打开输出目录里的 *.preview.html），满意后正式跑
.venv/bin/python main.py run

# 6) 挂定时（每天 06:30）
bash deploy/install.sh --cron
```

`sample/index.html` 是三个栏目的成品示例，可先打开看排版效果（点击卡片进入预览页）。

**只想用 Docker？** 不用装 Python 环境，直接看下面「八·二 Docker 部署」：

```bash
cp .env.example .env && vi .env       # 填 API Key 等凭据
docker compose up -d --build          # 构建并常驻定时（每天 06:30）
docker compose run --rm app python main.py run --dry-run   # 试跑一篇
```

---

## 四、拿公众号凭据（最容易踩坑的一步）

1. 打开 **[微信开发者平台](https://developers.weixin.qq.com/platform)** → 「我的业务与服务」→「公众号」→「基础信息」→「**开发密钥**」。
   > 注意：旧教程说的「公众号后台 → 设置与开发 → 基本配置」已经找不到入口了，AppSecret 和 IP 白名单现在都迁到了开发者平台。
2. 点「生成」AppSecret，**管理员微信扫码后只明文显示一次**，立刻复制存进 `.env` 的 `WX_APPSECRET`。
3. 在服务器上查公网 IP：`curl ifconfig.me`，把它加到同一页面的「**API IP 白名单**」。IP 不对会报 `40164`。
4. 把 `WX_APPID` 也填进 `.env`。

```dotenv
WX_APPID=wx1234567890abcdef
WX_APPSECRET=这里填那串只显示一次的密钥
LLM_API_KEY=sk-xxxxxxxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
NOTIFY_WEBHOOK=            # 可选
```

> **安全**：`.env` 已被 `.gitignore` 排除，不要提交到 git，也不要写进 `config.json`。服务器部署推荐用环境变量 `JAZK_WX_APPID` / `JAZK_WX_APPSECRET` / `JAZK_LLM_API_KEY` 注入（systemd / Docker 场景）。

---

## 五、配大模型（原创写稿）

程序走 **OpenAI 兼容的 `/chat/completions` 协议**，换厂商只需改 `.env` 两行：

| 厂商 | `LLM_BASE_URL` | `LLM_MODEL` |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 腾讯混元 | `https://api.hunyuan.cloud.tencent.com/v1` | `hunyuan` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |

**不填 `LLM_API_KEY` 也能跑**：程序自动降级到本地模板生成器，产出结构完整的演示稿（`sample/` 里就是），用来验证链路和排版。正式发文前请配上 Key，让内容变成真正的原创稿。

### 大模型 API Key 到底填在哪

**就一个地方：项目根目录 `.env` 文件的 `LLM_API_KEY=` 这一行。**

```dotenv
LLM_API_KEY=sk-你的真实Key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

填完不用改任何代码。程序读取优先级是：**`JAZK_*` 环境变量 > `.env` / Docker `env_file` 注入的环境变量 > `config.json` 默认值**。所以 Docker 下有三种等效写法：

| 方式 | 怎么写 | 适合 |
| --- | --- | --- |
| `.env`（推荐） | 编辑根目录 `.env`，`docker compose up -d` 自动注入 | 单机自建 |
| `docker-compose.yml` 的 `environment` | 加一行 `JAZK_LLM_API_KEY: ${LLM_API_KEY}` | 想用宿主机 shell 环境变量 |
| 命令行 / CI | `docker run -e JAZK_LLM_API_KEY=sk-xxx ...` | 临时覆盖、密钥托管 |

**验证是否生效**：`python main.py check` 里「llm_原创生成」显示 `OK`；Docker 用 `docker compose exec app python main.py check`。

> **安全**：`.env` 同时列在 `.gitignore` 和 `.dockerignore` 里，**不会被提交到 GitHub、也不会被打进 Docker 镜像**。仓库里只保留不含密钥的 `.env.example` 模板。

---

## 六、命令速查

| 命令 | 作用 |
| --- | --- |
| `python main.py init` | 初始化：生成 `.env`、建库、检查依赖 |
| `python main.py check --probe` | 自检配置/字体/凭据/微信连通性，并实测采集源 |
| `python main.py run --dry-run` | 完整跑一遍，**只出本地成品，不调微信接口** |
| `python main.py run` | 正式跑：出稿 + 自动存入草稿箱 + 推送提醒 |
| `python main.py run --topic senior_health` | 指定今天写哪个栏目 |
| `python main.py run --force` | 忽略当天幂等保护，强制重跑 |
| `python main.py topics` | 只看今天采集到的选题灵感 |
| `python main.py history` / `stats` | 历史成稿 / 统计与运行记录 |
| `python main.py daemon` | 常驻定时模式（不想装 cron 时用）|
| `python main.py publish-latest` | 尝试发布最近一条草稿（个人号会明确提示无权限）|
| `python tools/make_samples.py` | 重新生成三个栏目的示例成品 |

`--topic` 可选：`family_story`（家长里短）、`inlaw_relation`（婆媳相处）、`senior_health`（中老年养生）。

---

## 七、每天产出什么

```
output/2026-11-08/
├── 文章标题.md              # Markdown 原稿（含参考线索、配图建议、合规记录）
├── 文章标题.html            # 可直接提交给微信的正文 HTML（全内联样式）
├── 文章标题.preview.html    # 本地手机宽度排版预览
└── cover.png                # 900×383 封面图
```

`.md` 和 `.html` 都留在本地，即使微信接口临时故障，文章也不会丢，可手动复制粘贴到后台。

---

## 八、定时部署

**推荐 cron**（服务器 7×24 开机）：

```bash
bash deploy/install.sh --cron
# 或手动 crontab -e，内容见 deploy/crontab.example
```

**不想装 cron**：`python main.py daemon` 常驻，按 `config.json` 里 `schedule.cron` 的时间每天执行；用 `systemd` 或 `nohup` 托管即可。

**本地电脑**：用「计划任务 / launchd / cron」调用同一条 `main.py run` 命令即可，代码跨平台。

日志在 `data/logs/run-YYYYMM.log`，运行记录在 SQLite（`python main.py stats` 可查）。

---

## 八·二、Docker 部署（推荐）

镜像里已装好 Python 依赖、中文字体和 `Asia/Shanghai` 时区，服务器上不需要再配 Python 或字体。

### 三步启动

```bash
cd jiashi-ankang-daily
cp .env.example .env && vi .env      # 填 WX_APPID / WX_APPSECRET / LLM_API_KEY
docker compose up -d --build         # 构建 + 后台常驻定时
docker compose logs -f               # 看日志
```

容器默认执行 `python main.py daemon`，按 `config.json` 里 `schedule.cron`（默认每天 06:30，北京时间）出稿并存入公众号草稿箱，再推送提醒，你在后台点「发表」。

### 常用命令

| 命令 | 作用 |
| --- | --- |
| `docker compose up -d --build` | 构建并启动 |
| `docker compose logs -f --tail=100` | 实时日志 |
| `docker compose run --rm app python main.py run --dry-run` | 本地试跑，不碰微信接口 |
| `docker compose run --rm app python main.py check --probe` | 自检 + 实测采集源 |
| `docker compose run --rm app python main.py run --force` | 立即手动出一篇（忽略当天幂等）|
| `docker compose run --rm app python main.py stats` | 统计与运行记录 |
| `docker compose restart` | 改完 `.env` / `config.json` 后重启生效 |
| `docker compose down` | 停止（数据不丢）|

### 数据与凭据映射

| 宿主机 | 容器内 | 说明 |
| --- | --- | --- |
| `.env` | 环境变量注入 | 凭据；**不进镜像、不进 GitHub** |
| `./data` | `/app/data` | SQLite、access_token 缓存、日志，持久化 |
| `./output` | `/app/output` | 每日成品（md / html / 封面），持久化 |
| `./input` | `/app/input` | 手动素材 |
| `./config.json` | `/app/config.json:ro` | 改采集源 / 关键词 / 定时时间不用重建镜像，重启即可 |

容器以非 root 用户运行，入口脚本会自动修正挂载目录属主，宿主机文件不会被写成 root 所有。

> **二选一**：Docker 常驻 `daemon` 和宿主机 `cron` 不要同时开。真同时开了也没关系，程序的「当天幂等保护」会挡住第二次，不会产生两篇草稿。

---

## 九、内容来源与合规设计

**采集源**（`config.json` 可增删，均为公开列表页，实测可用）：人民网健康、中新网健康、生命时报、新华网健康、中国妇女网。国家卫健委官网实测返回 412 反爬，默认关闭；也支持自定义公开 RSS 和 `input/materials.txt` 手动素材。

采集器**只取列表页的标题与链接**，不抓正文、不登录、不绕反爬、每个源只请求一次、请求间有礼貌间隔。

**版权与内容安全**是重点设计：

- 采集结果**只作为选题灵感**进入 Prompt，明确禁止照抄任何句子；正文由模型原创生成，标题也由模型自拟。
- 内置 60 条常青选题库（覆盖三大栏目）+ 30 天去重，断网或源失效也不会断更、不撞题。
- 健康类：**强制**文末免责声明；自动替换「根治/治愈/包好/疗效显著」等违规表述；不写药名剂量、不推荐保健品。
- 故事类：**强制**「人物均为化名、情节为艺术加工」声明。
- 婆媳类：Prompt 强制中立，禁止「恶婆婆/不孝」等对立标签。
- 标题党、广告法极限词、无出处的「研究表明」、时政内容都会命中过滤或标记「需人工复核」，并在推送提醒里注明。

> **仍建议**：AI 生成的文章发布前人工通读一遍；是否声明「原创」、是否标注 AI 辅助创作，请按平台规则和自身判断处理。养生内容切勿替代医生诊疗。

---

## 十、排错

| 现象 | 原因 / 处理 |
| --- | --- |
| 跑了 `--dry-run`，草稿箱里没有内容 | **正常**。`--dry-run` 刻意不调用任何微信接口，只生成本地成品用于验内容/排版。正式命令去掉 `--dry-run` |
| 正式命令输出「未存入草稿箱」 | `.env` 的 `WX_APPID` / `WX_APPSECRET` 未填，或 `config.json` 的 `draft_enabled` 为 false。手动 `run` 填完直接生效；常驻 daemon 需 `docker compose up -d --force-recreate`（`restart` 不会重读 `env_file`），再用 `check` 确认 |
| 填了凭据仍提示「今天已成功跑过一次」 | 幂等保护。加 `--force` 重跑；升级到最新版后 `dry-run` 已不再占用当天的正式名额 |
| `40013 invalid appid` | `WX_APPID` 填错 |
| `40001` / `40125` | AppSecret 错误或已重置，重新生成并更新 `.env` |
| `40164` | 服务器公网 IP 未加入 API IP 白名单，`curl ifconfig.me` 查后添加 |
| `48001 api unauthorized` | 个人号调用发布接口被拒。**正常现象**：草稿已建好，去后台点「发表」 |
| `45009` | 接口频率超限，稍后再试 |
| 封面没有中文、只有图形 | 缺中文字体：`sudo apt install -y fonts-noto-cjk` |
| 采集源全部 FAIL | 服务器网络受限；不影响出稿（内置选题库兜底），检查 `check --probe` 结果 |
| 大模型调用失败 | 自动降级本地模板稿，日志有原因；检查 Key、余额、`LLM_BASE_URL` 是否以 `/v1` 结尾 |
| 文章只有 600~800 字 | 说明当前是本地演示稿；配好 `LLM_API_KEY` 后为 1200~1800 字原创稿 |
| 第二天没生成 | `python main.py stats` 看运行记录；检查 `data/cron.log` 与 crontab 路径是否为绝对路径 |

---

## 十一、自定义

| 想改什么 | 改哪里 |
| --- | --- |
| 选题角度、栏目名、季节提示 | `lib/topics.py` |
| 采集源、过滤词、栏目权重、定时时间 | `config.json` |
| 写稿风格、字数、各栏目规则 | `lib/generator.py` 的 `SYSTEM_PROMPT` / `TOPIC_RULES` |
| 配色、字号、排版样式 | `lib/formatter.py` 顶部常量、`lib/cover.py` |
| 合规词表、免责声明 | `lib/compliance.py` |
| 通知渠道 | `.env` 的 `NOTIFY_WEBHOOK`（Server酱 / 企业微信群机器人 / 通用 webhook） |

---

## 十二、常见问题

**跑了 `run --dry-run`，为什么公众号草稿箱没有内容？** 因为 `--dry-run` 是本地试跑，设计上完全不调用微信接口，只在 `output/` 下生成成品文件，用来先验内容和排版。要真正存入草稿箱，运行不带 `--dry-run` 的命令：`docker compose run --rm app python main.py run`，并先确认 `.env` 已填 `WX_APPID` / `WX_APPSECRET`、`python main.py check` 显示 `wechat_草稿箱 OK`。常驻的 `daemon` 到点也会自动执行正式流程。

**能完全无人值守吗？** 个人订阅号不行，微信不开放发布接口；认证服务号/订阅号可以（开 `auto_publish`）。

**一天能发几条？** 订阅号每天 1 条群发，程序每天只出 1 篇，正好匹配。

**会不会封号？** 只用官方 API、不模拟登录、不逆向、不刷量，属于平台允许的用法；风险主要在**内容合规**，所以程序做了多层过滤，仍请人工终审。

**一定要服务器吗？** 不一定。cron 需要机器按时开机；本地电脑每天定时跑也可以，只是电脑关机那天会漏。

**能直接搬别人的文章吗？** 程序刻意不这么做。搬运有侵权和原创声明风险，长期看对账号不利。

---

## 十三、上传到 GitHub

仓库里**不含任何密钥**：`.env`（真实凭据）、`data/`、`output/`、`__pycache__/` 都在 `.gitignore` 里，只提交不含密钥的 `.env.example` 模板。

```bash
bash deploy/push_to_github.sh                          # 默认 jeffreys125/jiashi-ankang-daily
bash deploy/push_to_github.sh <仓库名> <用户名>        # 自定义
```

脚本做 `git init → add → commit → remote → push`，凭据走本机 git credential helper，命令里不写 token；它还会检查 `.env` 是否被误暂存，发现就中止。

> **若报 `403 Resource not accessible by integration`**：说明当前 GitHub App 授权不允许「新建仓库」（只授权了推送到已有仓库）。请先在网页手动建一个**完全空**的仓库：
> 1. 打开 [github.com/new](https://github.com/new)
> 2. Repository name 填 `jiashi-ankang-daily`，选 **Private**
> 3. **不要**勾选 Add a README / .gitignore / license
> 4. 再执行上面的脚本即可（或把仓库名告诉我，我来推）

---

## 附：目录结构

```
jiashi-ankang-daily/
├── main.py                  # CLI 入口
├── config.json              # 主配置（源、过滤、权重、定时）
├── .env.example / .env      # 凭据模板 / 你的真实凭据（不入库）
├── lib/
│   ├── collector.py         # 多源采集 + 过滤
│   ├── topics.py            # 60 条常青选题库 + 季节提示
│   ├── generator.py         # 大模型原创写稿 + 离线降级
│   ├── compliance.py        # 合规检查与声明
│   ├── formatter.py         # 公众号内联样式 HTML
│   ├── cover.py             # Pillow 封面绘制
│   ├── wechat.py            # 微信官方 API（token/上传/草稿/发布）
│   ├── notify.py            # 手机推送提醒
│   ├── store.py             # SQLite 存储 + 去重 + 幂等
│   ├── pipeline.py          # 每日流程编排
│   ├── settings.py          # 配置加载
│   └── util.py              # 日志 / 重试 / 工具
├── Dockerfile               # 镜像（Python + 中文字体 + 北京时间）
├── docker-compose.yml       # 常驻定时容器、数据卷、凭据注入
├── .dockerignore            # 排除 .env / data / output，防止密钥进镜像
├── deploy/install.sh        # 裸机一键部署
├── deploy/crontab.example   # 裸机定时任务示例
├── deploy/docker-entrypoint.sh  # 容器降权与目录属主修正
├── tools/make_samples.py    # 重新生成示例
├── input/materials.txt      # 手动素材（可选）
├── sample/                  # 三个栏目的成品示例
├── output/                  # 每日成品
└── data/                    # SQLite、token 缓存、日志
```

---

本工具仅用于辅助合规的内容运营；文章发布前的最终审核责任在运营者本人。
