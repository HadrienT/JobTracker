"""The project's entire exception taxonomy — see blueprint/07-ERRORS-AND-LOGGING.md §1.

No other module defines its own exception class: a package that grows its own
would break the runtime's ability to classify failures.
"""


class JobTrackerError(Exception):
    """Base class for every error raised deliberately by JobTracker."""


class ConfigError(JobTrackerError):
    """Invalid YAML, a missing environment variable, an absent token."""


class StorageError(JobTrackerError):
    """SQLite failure: connection, migration, violated constraint."""


class CollectError(JobTrackerError):
    """Base class for failures encountered while collecting a source."""


class SourceUnavailable(CollectError):
    """Network error, 5xx, timeout — transient, worth retrying soon."""


class SourceBlocked(CollectError):
    """403/429, anti-bot challenge, captcha — requires exponential backoff."""


class SourceSchemaChanged(CollectError):
    """200 OK but the payload no longer matches the expected shape."""


class BoardNotFound(CollectError):
    """404 on a board token — the registry is wrong, not the network."""


class NormalizeError(JobTrackerError):
    """A posting that failed to normalize — never fatal for the run."""


class LlmUnavailable(JobTrackerError):
    """The local LLM server is busy or down — a skipped turn, not a failure."""
