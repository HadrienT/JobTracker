from jobtracker.core.errors import (
    BoardNotFound,
    CollectError,
    ConfigError,
    JobTrackerError,
    LlmUnavailable,
    NormalizeError,
    SourceBlocked,
    SourceSchemaChanged,
    SourceUnavailable,
    StorageError,
)


def test_all_errors_derive_from_job_tracker_error() -> None:
    for error_cls in (
        ConfigError,
        StorageError,
        CollectError,
        SourceUnavailable,
        SourceBlocked,
        SourceSchemaChanged,
        BoardNotFound,
        NormalizeError,
        LlmUnavailable,
    ):
        assert issubclass(error_cls, JobTrackerError)


def test_collect_errors_derive_from_collect_error() -> None:
    for error_cls in (SourceUnavailable, SourceBlocked, SourceSchemaChanged, BoardNotFound):
        assert issubclass(error_cls, CollectError)
