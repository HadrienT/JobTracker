import json

import pytest

from jobtracker.core.logging import bound_run_id, configure_logging, get_logger


def test_configure_logging_json_emits_parseable_lines(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", fmt="json")
    logger = get_logger("test")
    logger.info("run_started", source="greenhouse")
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])
    assert payload["event"] == "run_started"
    assert payload["source"] == "greenhouse"


def test_bound_run_id_is_attached_and_released(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", fmt="json")
    logger = get_logger("test")
    with bound_run_id("01J0RUNIDRUNIDRUNIDRUNID0"):
        logger.info("run_started")
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])
    assert payload["run_id"] == "01J0RUNIDRUNIDRUNIDRUNID0"

    logger.info("run_finished")
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])
    assert "run_id" not in payload


def test_get_logger_returns_something_bindable() -> None:
    configure_logging(level="INFO", fmt="json")
    logger = get_logger("test")
    bound = logger.bind(company_slug="jane_street")
    assert hasattr(bound, "info")
