# syntax=docker/dockerfile:1.7
# One image, several process roles: `api` (default), `engine`, `worker`.

ARG PYTHON_VERSION=3.12

# ── build: resolve the locked dependencies into a self-contained virtualenv ──
FROM python:${PYTHON_VERSION}-slim AS builder
ARG UV_VERSION=0.8.17
RUN pip install --no-cache-dir --disable-pip-version-check "uv==${UV_VERSION}"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ── runtime: no build tools, no source tree, non-root ────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runtime
RUN groupadd --system --gid 10001 kterminal \
 && useradd --system --uid 10001 --gid kterminal --no-create-home --shell /usr/sbin/nologin kterminal
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    KT_API__HOST=0.0.0.0
WORKDIR /app
USER kterminal:kterminal
EXPOSE 8000
ENTRYPOINT ["kterminal"]
CMD ["api"]
