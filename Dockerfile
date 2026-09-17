# DeltaConverge — 本地代码审查服务
#
# 多阶段构建：前端在构建阶段编译，运行阶段不再需要 Node，
# 用户无需在宿主机安装 Node/Python 即可 `docker run` 使用。
#
# 构建（默认精简版：含 semgrep/pylint 等 Python 扫描器）：
#   docker build -t deltaconverge:latest .
#
# 构建完整版（额外包含 eslint/tsc/checkstyle/pmd/go/rubocop 等多语言扫描器，镜像显著变大）：
#   docker build --build-arg WITH_EXTRA_SCANNERS=1 -t deltaconverge:full .

# ============ Stage 1: 前端构建 ============
FROM node:20-alpine AS frontend

WORKDIR /frontend

# 先只复制清单文件，最大化依赖层缓存命中
COPY frontend/react/package.json frontend/react/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/react/ ./
RUN npm run build


# ============ Stage 2: 运行时 ============
FROM python:3.11-slim AS runtime

ARG WITH_EXTRA_SCANNERS=0

LABEL org.opencontainers.image.title="DeltaConverge" \
  org.opencontainers.image.authors="Gust-feng" \
  org.opencontainers.image.licenses="MIT" \
  org.opencontainers.image.source="https://github.com/Gust-feng/DeltaConverge"

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  PIP_NO_CACHE_DIR=1

WORKDIR /app

# 基础系统依赖：git 用于 diff 采集，curl/ca-certificates 用于诊断与 HTTPS
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    build-essential \
  && rm -rf /var/lib/apt/lists/* \
  # 挂载卷常出现 fileMode / 行尾符差异，避免被识别成虚假变更
  && git config --global core.fileMode false \
  && git config --global core.autocrlf input \
  && git config --global safe.directory '*'

# 可选：多语言扫描器（体积较大，默认关闭）
RUN if [ "$WITH_EXTRA_SCANNERS" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        nodejs npm unzip openjdk-21-jre-headless golang-go ruby-full \
      && rm -rf /var/lib/apt/lists/* \
      && npm install -g eslint typescript \
      && gem install rubocop -N \
      && GCL_VERSION="1.55.2" \
      && curl -sSfL -o /tmp/golangci-lint.tar.gz \
           "https://github.com/golangci/golangci-lint/releases/download/v${GCL_VERSION}/golangci-lint-${GCL_VERSION}-linux-amd64.tar.gz" \
      && tar -xzf /tmp/golangci-lint.tar.gz -C /tmp \
      && mv "/tmp/golangci-lint-${GCL_VERSION}-linux-amd64/golangci-lint" /usr/local/bin/golangci-lint \
      && chmod +x /usr/local/bin/golangci-lint \
      && rm -rf /tmp/golangci-lint* ; \
    fi

# ---- Python 依赖层（放在 COPY 应用代码之前，提高缓存命中率）----
COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip \
  && pip install -r requirements.txt

# ---- 应用代码 ----
COPY Agent ./Agent
COPY kernel ./kernel
COPY adapters ./adapters
COPY UI ./UI
COPY etc ./etc
COPY run_ui.py ./run_ui.py
COPY README.md ./README.md
COPY LICENSE ./LICENSE

# 前端产物由构建阶段提供，运行时无需 Node
COPY --from=frontend /frontend/dist ./frontend/react/dist

# 会话数据与 env 建议挂载到容器外
VOLUME ["/app/data"]
EXPOSE 54321

CMD ["python", "-m", "uvicorn", "adapters.web.app:app", "--host", "0.0.0.0", "--port", "54321"]
