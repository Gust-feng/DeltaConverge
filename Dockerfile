FROM python:3.11-slim AS base

LABEL org.opencontainers.image.title="DeltaConverge" \
    org.opencontainers.image.authors="Gust-feng" \
    org.opencontainers.image.version="2.9.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps:
# - git: semgrep may invoke git for some operations; also common for repo context
# - curl/ca-certificates: diagnostics / HTTPS
# - build-essential: required by some Python deps with native extensions (safe default)
# - nodejs/npm: eslint/tsc
# - openjdk: checkstyle/pmd
# - golang: go vet + golangci-lint
# - ruby: rubocop
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git \
       curl \
       ca-certificates \
       build-essential \
       unzip \
       nodejs \
       npm \
       openjdk-21-jre-headless \
       golang-go \
       ruby-full \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g eslint typescript \
    && gem install rubocop -N \
    && pip install semgrep pylint

# -------- External scanner binaries (pinned versions) --------
# Note: These tools are installed once and rarely change; keeping them before
# application COPY steps improves rebuild times when code changes.
RUN set -eux; \
    \
    # golangci-lint
    GCL_VERSION="1.55.2"; \
    curl -sSfL -o /tmp/golangci-lint.tar.gz \
      "https://github.com/golangci/golangci-lint/releases/download/v${GCL_VERSION}/golangci-lint-${GCL_VERSION}-linux-amd64.tar.gz"; \
    tar -xzf /tmp/golangci-lint.tar.gz -C /tmp; \
    mv "/tmp/golangci-lint-${GCL_VERSION}-linux-amd64/golangci-lint" /usr/local/bin/golangci-lint; \
    chmod +x /usr/local/bin/golangci-lint; \
    rm -rf /tmp/golangci-lint*; \
    \
    # checkstyle
    CHECKSTYLE_VERSION="10.12.5"; \
    mkdir -p /opt/checkstyle; \
    curl -sSfL -o /opt/checkstyle/checkstyle.jar \
      "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-${CHECKSTYLE_VERSION}/checkstyle-${CHECKSTYLE_VERSION}-all.jar"; \
    curl -sSfL -o /google_checks.xml \
      "https://raw.githubusercontent.com/checkstyle/checkstyle/checkstyle-${CHECKSTYLE_VERSION}/src/main/resources/google_checks.xml"; \
    \
    # PMD 7
    PMD_VERSION="7.0.0"; \
    mkdir -p /opt/pmd; \
    curl -sSfL -o /tmp/pmd.zip \
      "https://github.com/pmd/pmd/releases/download/pmd_releases/${PMD_VERSION}/pmd-dist-${PMD_VERSION}-bin.zip"; \
    unzip -q /tmp/pmd.zip -d /opt; \
    rm -f /tmp/pmd.zip; \
    mv "/opt/pmd-bin-${PMD_VERSION}" /opt/pmd/app; \
    mv /opt/pmd/app/bin/pmd /opt/pmd/app/bin/pmd.bin; \
    \
    # sanity checks (fail early during build)
    semgrep --version >/dev/null; \
    pylint --version >/dev/null; \
    eslint --version >/dev/null; \
    tsc --version >/dev/null; \
    java -version; \
    go version; \
    rubocop -V; \
    golangci-lint --version

RUN printf '%s\n' \
  '#!/usr/bin/env sh' \
  'set -eu' \
  'has_config=0' \
  'for arg in "$@"; do' \
  '  if [ "$arg" = "-c" ] || [ "$arg" = "--config" ]; then' \
  '    has_config=1' \
  '    break' \
  '  fi' \
  'done' \
  'if [ "$has_config" -eq 0 ]; then' \
  '  exec java -jar /opt/checkstyle/checkstyle.jar -c /google_checks.xml "$@"' \
  'fi' \
  'exec java -jar /opt/checkstyle/checkstyle.jar "$@"' \
  > /usr/local/bin/checkstyle \
  && chmod +x /usr/local/bin/checkstyle

RUN printf '%s\n' \
  '#!/usr/bin/env sh' \
  'set -eu' \
  'if [ "${1:-}" = "check" ]; then' \
  '  shift' \
  '  has_ruleset=0' \
  '  for arg in "$@"; do' \
  '    if [ "$arg" = "-R" ] || [ "$arg" = "--rulesets" ]; then' \
  '      has_ruleset=1' \
  '      break' \
  '    fi' \
  '  done' \
  '  if [ "$has_ruleset" -eq 0 ]; then' \
  '    exec /opt/pmd/app/bin/pmd.bin check -R category/java/bestpractices.xml "$@"' \
  '  fi' \
  '  exec /opt/pmd/app/bin/pmd.bin check "$@"' \
  'fi' \
  'exec /opt/pmd/app/bin/pmd.bin "$@"' \
  > /usr/local/bin/pmd \
  && chmod +x /usr/local/bin/pmd

# -------- Python dependencies layer (best cache hit rate) --------
COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# -------- Application code (changes here won't bust dependency cache) --------
COPY Agent ./Agent
COPY UI ./UI
COPY run_ui.py ./run_ui.py
COPY README.md ./README.md

# Session data & env file live outside the image by default.
# UI/server.py reads /app/.env if present.
EXPOSE 54321

# Default command: run FastAPI via uvicorn.
# In Docker you should bind to 0.0.0.0.
CMD ["python", "-m", "uvicorn", "UI.server:app", "--host", "0.0.0.0", "--port", "54321"]
