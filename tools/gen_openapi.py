#!/usr/bin/env python3
"""Serialize the API's OpenAPI schema — no database, no running server.

blueprint/wp/WP07-api.md §7: this only imports `jobtracker.api.app:app` and
calls its `.openapi()` method. Creating the app never opens a connection —
only its `lifespan` does, and that only runs under a real server (or a
`TestClient` used as a context manager) — so this script is safe to run in
CI with no `jobtracker.db` anywhere on disk.

Usage:
    uv run python tools/gen_openapi.py web/openapi.json
"""

import json
import sys
from pathlib import Path

from jobtracker.api.app import app


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: gen_openapi.py <output-path>", file=sys.stderr)
        return 1
    output_path = Path(sys.argv[1])
    schema = app.openapi()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
