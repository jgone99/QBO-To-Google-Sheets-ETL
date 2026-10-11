import logging
from unittest import mock

import pytest

import status_sheet


@pytest.fixture
def writes(monkeypatch):
    ensure = mock.Mock()
    update = mock.Mock()
    monkeypatch.setattr(status_sheet, "ensure_sheet_exists", ensure)
    monkeypatch.setattr(status_sheet, "update_values", update)
    monkeypatch.setattr(status_sheet, "_now", lambda: "2026-10-11 09:30:00")
    return mock.Mock(ensure=ensure, update=update)


def test_success_updates_all_rows(writes):
    status_sheet.record_success("sheet-id", "14 invoices since 2026-07-01")

    writes.ensure.assert_called_once_with("sheet-id", "Sync Status")
    writes.update.assert_called_once_with("sheet-id", "Sync Status", "A1:B3", [
        ["Last successful sync", "2026-10-11 09:30:00"],
        ["Last run", "2026-10-11 09:30:00"],
        ["Last run result", "OK - 14 invoices since 2026-07-01"],
    ])


def test_failure_leaves_last_successful_sync_alone(writes):
    status_sheet.record_failure("sheet-id", "QBOAPIError: Token expired")

    writes.update.assert_called_once_with("sheet-id", "Sync Status", "A2:B3", [
        ["Last run", "2026-10-11 09:30:00"],
        ["Last run result", "FAILED - QBOAPIError: Token expired"],
    ])


@pytest.mark.parametrize("record", [status_sheet.record_success, status_sheet.record_failure])
def test_status_errors_are_logged_not_raised(writes, record, caplog):
    writes.update.side_effect = RuntimeError("Sheets is down")

    with caplog.at_level(logging.ERROR):
        record("sheet-id", "details")

    assert "Could not update the Sync Status sheet" in caplog.text
    assert "Sheets is down" in caplog.text


def test_timestamp_format():
    stamp = status_sheet._now()

    assert len(stamp) == len("2026-10-11 09:30:00")
    assert stamp[4] == "-" and stamp[10] == " " and stamp[13] == ":"
