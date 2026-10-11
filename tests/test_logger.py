import logging
import sys
from datetime import date, timedelta
from unittest import mock

import pytest

import logger


def make_log(logs_dir, days_old):
    path = logs_dir / f"{date.today() - timedelta(days=days_old)}.log"
    path.write_text("x")
    return path


def test_deletes_logs_at_or_past_the_limit(isolated_logs, monkeypatch):
    monkeypatch.setattr(logger, "MAX_LOG_RETENTION_DAYS", 30)
    monkeypatch.setattr(logger, "MAX_LOG_RETENTION_BUFFER_DAYS", 1)
    kept = [make_log(isolated_logs, days) for days in (0, 1, 28)]
    deleted = [make_log(isolated_logs, days) for days in (29, 30, 90)]

    logger.cleanup_old_logs()

    assert all(p.exists() for p in kept)
    assert not any(p.exists() for p in deleted)


def test_ignores_files_that_are_not_dated_logs(isolated_logs, caplog):
    other = isolated_logs / "notes.txt"
    other.write_text("x")
    make_log(isolated_logs, 0)

    with caplog.at_level(logging.WARNING):
        logger.cleanup_old_logs()

    assert other.exists()
    assert "Log count (1) does not match total file count (2)" in caplog.text


def test_empty_logs_folder(isolated_logs):
    logger.cleanup_old_logs()


def test_setup_logging_survives_cleanup_failure(isolated_logs, monkeypatch, caplog):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # restored after the test
    monkeypatch.setattr(logger, "cleanup_old_logs", mock.Mock(side_effect=ValueError("bad log name")))

    with caplog.at_level(logging.ERROR):
        logger.setup_logging()

    assert "Log cleanup failed" in caplog.text


def test_setup_logging_survives_invalid_dated_log_name(isolated_logs, monkeypatch, caplog):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    (isolated_logs / "2026-13-45.log").write_text("x")

    with caplog.at_level(logging.ERROR):
        logger.setup_logging()

    assert "Log cleanup failed" in caplog.text


def test_setup_logging_logs_uncaught_exceptions(isolated_logs, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(logger, "cleanup_old_logs", lambda: None)

    logger.setup_logging()

    assert sys.excepthook is logger._log_uncaught_exception


def test_uncaught_exception_goes_to_log_and_console(monkeypatch, caplog):
    console = mock.Mock()
    monkeypatch.setattr(sys, "__excepthook__", console)
    error = ImportError("No module named 'intuitlib'")

    with caplog.at_level(logging.CRITICAL):
        logger._log_uncaught_exception(ImportError, error, None)

    assert "Uncaught exception" in caplog.text
    assert "intuitlib" in caplog.text
    console.assert_called_once_with(ImportError, error, None)
