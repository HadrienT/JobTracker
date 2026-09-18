"""Online backups — blueprint/wp/WP15-deploy.md §5, §7."""

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.db import connect
from jobtracker.core.errors import StorageError
from jobtracker.store import backup as backup_module
from jobtracker.store.backup import backup_database, prune_backups
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import upsert_posting

pytestmark = pytest.mark.db

_NOW = datetime(2026, 9, 18, 3, 0, tzinfo=UTC)


def _posting(conn: sqlite3.Connection, i: int) -> None:
    posting = make_posting(posting_id=f"p{i}", source_job_id=f"j{i}")
    upsert_posting(
        conn, posting.model_copy(update={"fingerprint": f"fp{i}"}), make_verdict(posting_id=f"p{i}")
    )


def test_a_backup_taken_during_a_collection_cycle_is_consistent_and_restorable(
    store_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    sync_companies(store_conn, [make_board()])
    store_conn.commit()
    db_path = Path(store_conn.execute("PRAGMA database_list").fetchone()["file"])

    stop = threading.Event()
    written = []

    def collect_cycle() -> None:
        writer = connect(db_path)
        i = 0
        while not stop.is_set():
            _posting(writer, i)
            writer.commit()  # one posting per transaction, like a real cycle
            written.append(i)
            i += 1
        writer.close()

    thread = threading.Thread(target=collect_cycle)
    thread.start()
    try:
        while len(written) < 20:
            pass
        path = backup_database(store_conn, tmp_path / "backups", now=_NOW)
    finally:
        stop.set()
        thread.join()

    restored = sqlite3.connect(path)
    try:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        count = restored.execute("SELECT COUNT(*) FROM postings").fetchone()[0]
        assert 20 <= count <= len(written)
        # A snapshot, not a torn read: every posting has its verdict and its company.
        orphans = restored.execute(
            "SELECT COUNT(*) FROM postings p LEFT JOIN verdicts v ON v.posting_id = p.posting_id "
            "WHERE v.posting_id IS NULL"
        ).fetchone()[0]
        assert orphans == 0
    finally:
        restored.close()


def test_the_backup_is_named_by_its_timestamp(
    store_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    path = backup_database(store_conn, tmp_path, now=_NOW)
    assert path.name == "jobtracker-20260918-030000.db"


def test_backups_older_than_thirty_days_are_pruned(tmp_path: Path) -> None:
    for days_ago in (1, 29, 31, 90):
        stamp = (_NOW - timedelta(days=days_ago)).strftime("%Y%m%d-%H%M%S")
        (tmp_path / f"jobtracker-{stamp}.db").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("keep me")  # not a backup: never touched

    assert prune_backups(tmp_path, now=_NOW) == 2
    kept = [(_NOW - timedelta(days=d)).strftime("jobtracker-%Y%m%d-%H%M%S.db") for d in (29, 1)]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([*kept, "notes.txt"])


def test_a_backup_that_fails_its_integrity_check_is_removed_not_kept(
    store_conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup_module, "_integrity_check", lambda conn: "page 3 is corrupt")
    with pytest.raises(StorageError):
        backup_database(store_conn, tmp_path, now=_NOW)
    assert list(tmp_path.glob("jobtracker-*.db")) == []
