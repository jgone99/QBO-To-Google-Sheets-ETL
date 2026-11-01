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
from aws_client.credentials import AwsCredentials
from aws_client.secrets import JsonSecret

ETL_PATH = Path(etl.__file__)


@pytest.fixture
def pipeline(monkeypatch):
    """
    Fakes everything the run talks to and returns the mocks. All fakes are children of
    one mock, so `pipeline.mock_calls` records the order of calls across them.
    """
    fakes = mock.Mock()
    fakes.fetch.return_value = [{"Id": "1", "DocNumber": "1001"}, {"Id": "2", "DocNumber": "1002"}]
    monkeypatch.setattr(etl, "get_all_invoices_since", fakes.fetch)
    monkeypatch.setattr(etl, "set_spreadsheet_values", fakes.write)
    monkeypatch.setattr(etl, "setup_logging", fakes.setup_logging)
    monkeypatch.setattr(etl.qbo_auth, "use_store", fakes.qbo_store)
    monkeypatch.setattr(etl.sheets_auth, "use_store", fakes.sheets_store)
    monkeypatch.setattr(backup, "backup_sheet", fakes.backup)
    monkeypatch.setattr(status_sheet, "record_success", fakes.success)
    monkeypatch.setattr(status_sheet, "record_failure", fakes.failure)
    monkeypatch.setattr(config, "START_DATE", date(2026, 7, 1))
    return fakes


def steps(pipeline, *names):
    return [name for name, _, _ in pipeline.mock_calls if name in names]


# --- main

def test_successful_run(pipeline):
    etl.main("sheet-id")

    pipeline.fetch.assert_called_once_with("2026-07-01")
    pipeline.write.assert_called_once_with("sheet-id", "Invoices", invoice_sheet.to_rows(pipeline.fetch.return_value))
    pipeline.success.assert_called_once_with("sheet-id", "2 invoices since 2026-07-01")
    pipeline.failure.assert_not_called()


def test_sheet_is_backed_up_before_it_is_overwritten(pipeline):
    etl.main("sheet-id")

    assert steps(pipeline, "backup", "write") == ["backup", "write"]
    pipeline.backup.assert_called_once_with("sheet-id", "Invoices")


def test_failed_backup_stops_the_overwrite(pipeline):
    pipeline.backup.side_effect = RuntimeError("AccessDenied")

    with pytest.raises(RuntimeError):
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


# --- handler (what Lambda calls)

def test_handler_success(pipeline):
    assert etl.handler({}, None) == {"status": "succeeded"}

    pipeline.setup_logging.assert_called_once()
    pipeline.success.assert_called_once()


def test_handler_points_credentials_at_the_secrets(pipeline):
    etl.handler({}, None)

    [qbo_store] = pipeline.qbo_store.call_args.args
    [sheets_store] = pipeline.sheets_store.call_args.args
    assert isinstance(qbo_store, JsonSecret) and qbo_store.secret_id == "test-qbo-secret"
    assert isinstance(sheets_store, JsonSecret) and sheets_store.secret_id == "test-google-secret"
    # federation configs sign in with the run's AWS credentials
    assert isinstance(pipeline.sheets_store.call_args.kwargs["aws_credentials"], AwsCredentials)


def test_handler_resets_credentials_before_the_sync(pipeline):
    # Lambda can reuse the process, so each run must start from fresh credentials
    etl.handler({}, None)

    assert steps(pipeline, "qbo_store", "sheets_store", "fetch") == ["qbo_store", "sheets_store", "fetch"]


def test_handler_failure_is_recorded_and_raised(pipeline, caplog):
    # raising is what makes Lambda count an error, which fires the alarm
    pipeline.fetch.side_effect = RuntimeError("QBO down")

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="QBO down"):
        etl.handler({}, None)

    pipeline.failure.assert_called_once_with("test-sheet", "RuntimeError: QBO down")
    assert "Run failed" in caplog.text


def test_handler_invalid_config_stops_before_fetching(pipeline, monkeypatch):
    monkeypatch.setattr(config, "QBO_BASE_URL", None)

    with pytest.raises(ValueError, match="Invalid configuration"):
        etl.handler({}, None)

    pipeline.fetch.assert_not_called()
    pipeline.failure.assert_called_once()
    assert pipeline.failure.call_args.args[1].startswith("ValueError: Invalid configuration")


def test_handler_without_spreadsheet_id_only_logs(pipeline, monkeypatch, caplog):
    monkeypatch.delenv("SPREADSHEET_ID")
    monkeypatch.setattr(config, "SPREADSHEET_ID", None)

    with caplog.at_level(logging.ERROR), pytest.raises(ValueError):
        etl.handler({}, None)

    pipeline.failure.assert_not_called()
    assert "Run failed" in caplog.text


# --- running etl.py locally

@pytest.fixture
def script(pipeline, monkeypatch):
    """
    Runs etl.py as `python etl.py` does. runpy executes the file fresh, so the fakes are
    patched where the script imports them from. Returns the exit code.
    """
    monkeypatch.setattr(logger, "setup_logging", pipeline.setup_logging)
    monkeypatch.setattr("qbo_client.invoices.get_all_invoices_since", pipeline.fetch)
    monkeypatch.setattr("spreadsheet_client.client.set_spreadsheet_values", pipeline.write)
    monkeypatch.setattr("qbo_client.auth.use_store", pipeline.qbo_store)
    monkeypatch.setattr("spreadsheet_client.auth.use_store", pipeline.sheets_store)

    def run():
        try:
            runpy.run_path(str(ETL_PATH), run_name="__main__")
        except SystemExit as exit:
            return exit.code
        return 0

    return run


def test_local_run_success(script, pipeline):
    assert script() == 0

    pipeline.success.assert_called_once()


def test_local_run_failure_exits_1(script, pipeline):
    pipeline.fetch.side_effect = RuntimeError("QBO down")

    assert script() == 1

    pipeline.failure.assert_called_once_with("test-sheet", "RuntimeError: QBO down")


def test_importing_etl_runs_nothing(pipeline):
    import importlib
    importlib.reload(etl)

    pipeline.setup_logging.assert_not_called()
    pipeline.fetch.assert_not_called()
