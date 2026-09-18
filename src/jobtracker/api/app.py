"""The FastAPI application — blueprint/wp/WP07-api.md.

`tools/gen_openapi.py` imports `app` and serializes its schema without a
database or a running server: creating the app never opens a connection —
only `lifespan`, which FastAPI runs solely when actually served, does.
"""

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from jobtracker.api.routes import companies, facets, health, postings
from jobtracker.core.config import load_settings
from jobtracker.core.db import apply_migrations, connect
from jobtracker.store.schema import MIGRATIONS_DIR


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    conn: sqlite3.Connection = connect(settings.db_path)
    apply_migrations(conn, MIGRATIONS_DIR)
    app.state.conn = conn
    try:
        yield
    finally:
        conn.close()


app = FastAPI(title="JobTracker API", version="0.1.0", lifespan=lifespan)

# Mono-user tool behind a private tunnel, no auth (ADR-011) — the front's
# origin varies by deployment (Vite dev server, nginx in prod), and there is
# nothing here worth protecting behind an origin check.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(postings.router)
app.include_router(facets.router)
app.include_router(companies.router)
app.include_router(health.router)
