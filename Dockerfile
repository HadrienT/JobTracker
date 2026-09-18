# Backend image — the collector and the API run from this one image (blueprint/wp/WP15-deploy.md §2).
#
# The project is installed *editable* on purpose: `jobtracker.runtime.cli` and
# `store.schema` locate configs/ and migrations/ relative to the source tree, so the
# package must be imported from /app/src, not copied into site-packages.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir "uv==0.12.9"

WORKDIR /app

# Dependencies first: this layer is only rebuilt when pyproject/uv.lock change.
# `api` = FastAPI/uvicorn; `aggregators` = curl_cffi (TLS impersonation, WP13).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra api --extra aggregators

COPY src ./src
COPY configs ./configs
COPY migrations ./migrations
RUN uv sync --frozen --no-dev --extra api --extra aggregators

# Non-root. /data holds jobtracker.db (a named volume, never a network mount:
# SQLite in WAL mode on NFS corrupts silently) and /backups the online backups.
RUN useradd --system --uid 1001 --home-dir /app jobtracker \
    && mkdir -p /data /backups \
    && chown -R jobtracker:jobtracker /data /backups
USER jobtracker

ENV JT_DB_PATH=/data/jobtracker.db
VOLUME ["/data"]

CMD ["jobtracker", "--help"]
