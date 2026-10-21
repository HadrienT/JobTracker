"""The folder of past applications — WP21 §3."""

import os
from datetime import UTC, date, datetime
from pathlib import Path

from jobtracker.career.dossier import FileKind, classify, scan_dossier


def _touch(path: Path, day: date | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    if day is not None:
        stamp = datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp()
        os.utime(path, (stamp, stamp))


def test_classify_tells_offer_cv_and_letter_apart() -> None:
    siblings = frozenset({"Acme_QD.tex", "Acme_QD.pdf", "offer.pdf", "1.png", "LM.odt"})
    assert classify(Path("1.png"), siblings) is FileKind.OFFER
    assert classify(Path("offer.pdf"), siblings) is FileKind.OFFER
    assert classify(Path("Acme_QD.pdf"), siblings) is FileKind.CV  # a .tex twin: a CV
    assert classify(Path("CV_Someone.pdf"), siblings) is FileKind.CV
    assert classify(Path("LM.odt"), siblings) is FileKind.LETTER


def test_each_folder_holding_files_is_one_application(tmp_path: Path) -> None:
    _touch(tmp_path / "Acme" / "Quant Dev NY" / "1.png", date(2026, 3, 20))
    _touch(tmp_path / "Acme" / "Quant Dev NY" / "CV.pdf", date(2026, 3, 19))
    _touch(tmp_path / "Acme" / "offer.pdf", date(2024, 10, 27))
    entries = {e.relative: e for e in scan_dossier(tmp_path).entries}
    assert set(entries) == {"Acme", "Acme/Quant Dev NY"}
    assert entries["Acme/Quant Dev NY"].role == "Quant Dev NY"
    assert entries["Acme"].role is None
    # dated by the screenshot, not the CV prepared the day before
    assert entries["Acme/Quant Dev NY"].first_seen == date(2026, 3, 20)


def test_a_cv_above_sub_folders_is_shared_by_them_not_an_application(tmp_path: Path) -> None:
    _touch(tmp_path / "Borealis" / "CV.pdf")
    _touch(tmp_path / "Borealis" / "Analyst Asia" / "1.png")
    _touch(tmp_path / "Borealis" / "Analyst US" / "1.png")
    entries = scan_dossier(tmp_path).entries
    assert [e.relative for e in entries] == ["Borealis/Analyst Asia", "Borealis/Analyst US"]
    assert all(e.inherited == ("Borealis/CV.pdf",) for e in entries)


def test_workshop_and_scratch_folders_are_skipped_with_a_reason(tmp_path: Path) -> None:
    _touch(tmp_path / "CV" / "Finance" / "CV.tex")
    (tmp_path / "Empty Co").mkdir()
    _touch(tmp_path / "Diploma.pdf")
    scan = scan_dossier(tmp_path)
    assert scan.entries == []
    assert {s.relative: s.reason for s in scan.skipped} == {
        "CV": "not an application",
        "Diploma.pdf": "loose file, not tied to a company",
        "Empty Co": "empty",
    }


def test_a_root_screenshot_joins_its_company_folder(tmp_path: Path) -> None:
    _touch(tmp_path / "Cobalt" / "1.png")
    _touch(tmp_path / "Cobalt.png")
    _touch(tmp_path / "Delta.png")
    entries = {e.relative: e for e in scan_dossier(tmp_path).entries}
    assert entries["Cobalt"].inherited == ("Cobalt.png",)
    assert entries["Delta.png"].company == "Delta"
