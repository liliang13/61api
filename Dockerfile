# syntax=docker/dockerfile:1
# 61API 私有化交付镜像:前端构建 + 后端运行时,单镜像自带静态资源,不依赖外网。

FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    DEPLOYMENT_MODE=private

WORKDIR /app

RUN useradd --system --uid 10001 --create-home --home-dir /app app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/
COPY --from=frontend-build /build/dist /app/frontend/dist

RUN mkdir -p /app/backend/data && chown -R app:app /app

USER app

EXPOSE 8300
VOLUME ["/app/backend/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8300/health', timeout=3)"

CMD ["sh", "-c", "python backend/manage.py init-private && exec gunicorn --chdir backend --workers 2 --threads 8 --worker-class gthread --bind 0.0.0.0:8300 --access-logfile - --error-logfile - app:app"]
