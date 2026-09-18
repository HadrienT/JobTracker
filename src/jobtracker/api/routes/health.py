"""`GET /health` — blueprint/07-ERRORS-AND-LOGGING.md §5.

Always 200, even degraded (it is a status page, not a liveness probe): a
stale feed must stay visible while scrolling, never hidden behind an error.
"""

from fastapi import APIRouter

from jobtracker.api.deps import Conn
from jobtracker.store.health import HealthSnapshot, health_snapshot

router = APIRouter(tags=["health"])


@router.get("/health")
def get_health(conn: Conn) -> HealthSnapshot:
    return health_snapshot(conn)
