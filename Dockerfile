# 家事安康会 · 每日内容助手
# 用法见 README「Docker 部署」章节
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

# fonts-noto-cjk : 封面中文渲染
# tzdata         : 让「每天 06:30」按北京时间执行
# gosu           : 以非 root 用户运行，同时自动修正挂载卷的属主
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-noto-cjk tzdata gosu \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN groupadd -g 1000 appuser \
    && useradd -u 1000 -g appuser -m -s /bin/sh appuser \
    && mkdir -p /app/data /app/data/logs /app/output /app/input \
    && chmod +x /app/deploy/*.sh \
    && chown -R appuser:appuser /app

ENTRYPOINT ["/app/deploy/docker-entrypoint.sh"]
CMD ["python", "main.py", "daemon"]
