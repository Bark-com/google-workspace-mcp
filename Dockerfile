# syntax=docker/dockerfile:1
# Bark-owned (see BARK.md): upstream's python:3.13-slim base is replaced by the
# Bark golden image. Pass the Python version from .python-version:
#   docker build --build-arg PYTHON_VERSION=$(cat .python-version) .
# .python-version is the golden-images v1 bump target. Golden images have no
# 3.13 line and upstream supports 3.11-3.13, so this stays on the 3.12 line.
ARG PYTHON_VERSION
FROM ghcr.io/bark-com/python:${PYTHON_VERSION}-alpine-3.22.4-nonroot

# WORKDIR is already /app, uv and curl are already installed, and PATH points
# at the golden image's pre-created venv (/venv), so `uv sync` installs into
# it. There is no /app/.venv here. COPY defaults to root:root, hence --chown.
USER bark
COPY --chown=bark:bark . .

# Install Python dependencies using uv sync
# --extra otel ships the OpenTelemetry SDK/exporter so tracing can be enabled at
# runtime via OTEL_* env vars; it stays a no-op unless an OTLP endpoint is set.
# Upstream also installs --extra valkey (WORKSPACE_MCP_OAUTH_PROXY_STORAGE_BACKEND
# =valkey). It is left out: valkey-glide has no musllinux (Alpine) wheel, and
# Bark runs stateless with OAuth 2.1 off, so that storage backend is never used.
RUN uv sync --frozen --no-dev --compile-bytecode --extra disk --extra otel

# Give read and write access to the store_creds volume
RUN mkdir -p /app/store_creds \
    && chmod 755 /app/store_creds

# Expose port (use default of 8000 if PORT not set)
EXPOSE 8000
# Expose additional port if PORT environment variable is set to a different value
ARG PORT
EXPOSE ${PORT:-8000}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD sh -c 'curl -f http://localhost:${PORT:-8000}/health || exit 1'

# Set environment variables for Python startup args
ENV TOOL_TIER=""
ENV TOOLS=""

# Use entrypoint for the base command and CMD for args
ENTRYPOINT ["/bin/sh", "-c"]
CMD ["exec python main.py --transport streamable-http ${TOOL_TIER:+--tool-tier \"$TOOL_TIER\"} ${TOOLS:+--tools $TOOLS}"]
