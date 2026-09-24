# ---- builder ----
FROM python:3.14.7-alpine AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Third-party deps only — the project itself is not installed (koffito is run
# via PYTHONPATH in the runtime stage, not as an installed package)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=from=ghcr.io/astral-sh/uv,source=/uv,target=/bin/uv \
    uv sync --frozen --no-install-project --no-dev

# ---- runtime ----
FROM python:3.14.7-alpine

RUN adduser -D -u 1000 appuser
WORKDIR /app

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser src ./src

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app/src"
USER appuser

EXPOSE 8000
CMD ["uvicorn", "koffito.asgi:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
