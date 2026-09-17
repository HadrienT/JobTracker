"""`structlog` JSON logging, with the `run_id` injected by context.

See blueprint/07-ERRORS-AND-LOGGING.md §2: `event` is a stable identifier,
never a sentence, and every event is logged at a component boundary.
"""

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import structlog
from structlog.typing import FilteringBoundLogger, Processor


def configure_logging(*, level: str = "INFO", fmt: str = "json") -> None:
    """Configure `structlog` once, at startup."""
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer() if fmt == "json" else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> FilteringBoundLogger:
    """Return a bound logger for `name`, ready to carry contextual fields."""
    return cast(FilteringBoundLogger, structlog.get_logger(name))


@contextmanager
def bound_run_id(run_id: str) -> Iterator[None]:
    """Bind `run_id` to every log event emitted within the context."""
    structlog.contextvars.bind_contextvars(run_id=run_id)
    try:
        yield
    finally:
        structlog.contextvars.unbind_contextvars("run_id")
