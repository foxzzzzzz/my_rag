ARG NODE_IMAGE=node:22.14.0-bookworm-slim
FROM ${NODE_IMAGE} AS frontend
WORKDIR /build/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
COPY config/ /build/config/
RUN npm run build
FROM python:3.12-slim-bookworm
COPY config/debian.sources /etc/apt/sources.list.d/debian.sources
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY config/ /app/config/
RUN export PIP_CONFIG_FILE=/app/config/pip-build.conf && pip install --no-cache-dir -r config/web-requirements-lock.txt -r config/oss-requirements.txt -r config/douyin-favorites-requirements.txt sqlite-vec==0.1.9 && python -m venv /opt/douyin && /opt/douyin/bin/pip install --no-cache-dir -r config/douyin-resolver-requirements.txt && /opt/douyin/bin/pip install --no-cache-dir --no-deps -r config/douyin-resolver-f2.txt
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 && playwright install --with-deps --no-shell chromium && rm -rf /var/lib/apt/lists/*
COPY personalkb/ /app/personalkb/
COPY tools/ /app/tools/
COPY --from=frontend /build/web/dist /app/web/dist
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "tools.web_server", "--config", "/app/config/web.json"]
