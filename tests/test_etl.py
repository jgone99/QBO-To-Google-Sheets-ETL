import logging
import runpy
from datetime import date
from pathlib import Path
from unittest import mock

import pytest

import backup
import config
import etl
import invoice_sheet
import logger
import status_sheet

ETL_PATH = Path(etl.__file__)


@pytest.fixture
def pipeline(monkeypatch):
    """
    Fakes everything etl.main talks to and returns the mocks.
    """
    fakes = mock.Mock()
    fakes.fetch.return_value = [{"Id": "1", "DocNumber": "1001"}, {"Id": "2", "DocNumber": "1002"}]
    monkeypatch.setattr(etl, "get_all_invoices_since", fakes.fetch)
    monkeypatch.setattr(etl, "set_spreadsheet_values", fakes.write)
    monkeypatch.setattr(backup, "backup_sheet", fakes.backup)
    monkeypatch.setattr(backup, "cleanup_old_backups", fakes.cleanup_backups)
    monkeypatch.setattr(status_sheet, "record_success", fakes.success)
    monkeypatch.setattr(status_sheet, "record_failure", fakes.failure)
    monkeypatch.setattr(config, "START_DATE", date(2026, 7, 1))
    return fakes


# --- main

def test_successful_run(pipeline):
    etl.main("sheet-id")

    pipeline.fetch.assert_called_once_with("2026-07-01")
    pipeline.write.assert_called_once_with("sheet-id", "Invoices", invoice_sheet.to_rows(pipeline.fetch.return_value))
    pipeline.success.assert_called_once_with("sheet-id", "2 invoices since 2026-07-01")
    pipeline.failure.assert_not_called()


def test_sheet_is_backed_up_before_it_is_overwritten(pipeline):
    etl.main("sheet-id")

    # all fakes are children of one mock, so mock_calls records the order across them
    steps = [name for name, _, _ in pipeline.mock_calls if name in ("backup", "write")]
    assert steps == ["backup", "write"]
    pipeline.backup.assert_called_once_with("sheet-id", "Invoices")


def test_failed_backup_stops_the_overwrite(pipeline):
    pipeline.backup.side_effect = OSError("disk full")

    with pytest.raises(OSError):
        etl.main("sheet-id")

    pipeline.write.assert_not_called()
    pipeline.success.assert_not_called()


def test_zero_invoices_is_a_warning_not_a_failure(pipeline, caplog):
    pipeline.fetch.return_value = []

    with caplog.at_level(logging.WARNING):
        etl.main("sheet-id")

    pipeline.backup.assert_not_called()
    pipeline.write.assert_not_called()
    pipeline.success.assert_called_once_with("sheet-id", "no invoices found since 2026-07-01, invoice sheet was not updated")
    pipeline.failure.assert_not_called()
    assert "No invoices found since 2026-07-01" in caplog.text


def test_fetch_error_stops_before_writing(pipeline):
    pipeline.fetch.side_effect = RuntimeError("QBO down")

    with pytest.raises(RuntimeError):
        etl.main("sheet-id")

    pipeline.write.assert_not_called()
    pipeline.success.assert_not_called()


def test_write_error_is_not_recorded_as_success(pipeline):
    pipeline.write.side_effect = RuntimeError("Sheets down")

    with pytest.raises(RuntimeError):
        etl.main("sheet-id")

    pipeline.success.assert_not_called()


# --- running etl.py as a script

@pytest.fixture
def script(pipeline, monkeypatch):
    """
    Runs etl.py the way Task Scheduler does (as __main__), with logging setup and
    config validation faked. Returns the exit code (0 when it finishes normally).
    """
    monkeypatch.setattr(logger, "setup_logging", mock.Mock())
    monkeypatch.setattr(config, "validate", mock.Mock())
    monkeypatch.setenv("SPREADSHEET_ID", "sheet-id")
    # the script re-imports these by name, so patch them at their source modules
    monkeypatch.setattr("qbo_client.invoices.get_all_invoices_since", pipeline.fetch)
    monkeypatch.setattr("spreadsheet_client.client.set_spreadsheet_values", pipeline.write)

    def run():
        try:
            runpy.run_path(str(ETL_PATH), run_name="__main__")
        except SystemExit as exit:
            return exit.code
        return 0

    return run


def test_script_success(script, pipeline):
    assert script() == 0

    logger.setup_logging.assert_called_once()
    pipeline.success.assert_called_once()


def test_script_cleans_up_backups_before_the_sync(script, pipeline):
    assert script() == 0

    steps = [name for name, _, _ in pipeline.mock_calls if name in ("cleanup_backups", "fetch")]
    assert steps == ["cleanup_backups", "fetch"]


@pytest.mark.parametrize("break_run", ["sync", "config"])
def test_script_cleans_up_backups_even_when_the_run_fails(script, pipeline, break_run):
    if break_run == "sync":
        pipeline.fetch.side_effect = RuntimeError("QBO down")
    else:
        config.validate.side_effect = ValueError("Invalid configuration")

    assert script() == 1

    pipeline.cleanup_backups.assert_called_once()


def test_script_failure_exits_1_and_records_it(script, pipeline, caplog):
    pipeline.fetch.side_effect = RuntimeError("QBO down")

    with caplog.at_level(logging.ERROR):
        assert script() == 1

    pipeline.failure.assert_called_once_with("sheet-id", "RuntimeError: QBO down")
    assert "Run failed" in caplog.text


def test_script_invalid_config_stops_before_fetching(script, pipeline):
    config.validate.side_effect = ValueError("Invalid configuration: missing from .env: QBO_REALM_ID")

    assert script() == 1

    pipeline.fetch.assert_not_called()
    pipeline.failure.assert_called_once_with("sheet-id", "ValueError: Invalid configuration: missing from .env: QBO_REALM_ID")


def test_script_without_spreadsheet_id_only_logs(script, pipeline, monkeypatch, caplog):
    monkeypatch.delenv("SPREADSHEET_ID")
    config.validate.side_effect = ValueError("Invalid configuration: missing from .env: SPREADSHEET_ID")

    with caplog.at_level(logging.ERROR):
        assert script() == 1

    pipeline.failure.assert_not_called()
    assert "Run failed" in caplog.text


def test_importing_etl_does_not_set_up_logging():
    # importing (as tests do) must not write to the real logs/ folder; only running the script does
    import importlib
    with mock.patch.object(logger, "setup_logging") as setup:
        importlib.reload(etl)

    setup.assert_not_called()
