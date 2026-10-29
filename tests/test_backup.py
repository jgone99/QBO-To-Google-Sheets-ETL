import csv
import io
import logging
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

import backup
import config


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(config, "now", lambda: datetime(2026, 10, 29, 6, 0, 5, tzinfo=ZoneInfo("America/New_York")))


@pytest.fixture
def sheet_contents(monkeypatch):
    """
    Fakes reading the sheet. Call it with the rows the sheet should contain.
    Returns the mock so tests can check what was requested.
    """
    def setup(rows):
        response = {"range": "'Invoices'!A1:K3", "majorDimension": "ROWS"}
        if rows:
            response["values"] = rows  # Sheets leaves "values" out entirely for an empty sheet
        get = mock.Mock(return_value=response)
        monkeypatch.setattr(backup, "get_spreadsheet_values", get)
        return get
    return setup


def stored_rows(fake_s3, key):
    body = fake_s3.objects[("test-bucket", key)]["body"]
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig"), newline="")))


def test_backup_saves_current_sheet_to_s3(sheet_contents, fake_s3):
    rows = [["Id", "DocNumber", "TotalAmt"], ["1", "1001", "$250.00"], ["2", "1002", "$20.00"]]
    get = sheet_contents(rows)

    key = backup.backup_sheet("sheet-id", "Invoices")

    get.assert_called_once_with("sheet-id", "Invoices")
    assert stored_rows(fake_s3, key) == rows
    assert fake_s3.objects[("test-bucket", key)]["content_type"] == "text/csv; charset=utf-8"


def test_backup_key_has_prefix_local_timestamp_and_sheet_name(sheet_contents, fake_s3):
    sheet_contents([["Id"]])

    # 6:00:05 AM in New York, not the UTC time Lambda's clock shows
    assert backup.backup_sheet("sheet-id", "Invoices") == "backups/2026-10-29_060005_Invoices.csv"


def test_backups_land_under_the_prefix_the_lifecycle_rule_expires(sheet_contents, fake_s3):
    sheet_contents([["Id"]])

    key = backup.backup_sheet("sheet-id", "Invoices")

    assert key.startswith(backup.BACKUP_PREFIX)
    assert backup.BACKUP_PREFIX == "backups/"


def test_backup_name_is_safe_for_any_sheet_name(sheet_contents, fake_s3):
    sheet_contents([["Id"]])

    key = backup.backup_sheet("sheet-id", "Bob's Sheet/2026")

    assert key.endswith("_Bob_s_Sheet_2026.csv")


def test_backup_handles_commas_quotes_and_accents(sheet_contents, fake_s3):
    rows = [["CustomerName"], ['Smith, "Bob" & Sons'], ["Peña Cerrajería"]]
    sheet_contents(rows)

    key = backup.backup_sheet("sheet-id", "Invoices")

    assert stored_rows(fake_s3, key) == rows


def test_backup_keeps_uneven_rows(sheet_contents, fake_s3):
    # Sheets drops trailing empty cells, so rows can have different lengths
    rows = [["Id", "DueDate", "CustomerPO"], ["1", "2026-08-01"], ["2"]]
    sheet_contents(rows)

    key = backup.backup_sheet("sheet-id", "Invoices")

    assert stored_rows(fake_s3, key) == rows


def test_empty_sheet_is_not_backed_up(sheet_contents, fake_s3, caplog):
    sheet_contents([])

    with caplog.at_level(logging.INFO):
        assert backup.backup_sheet("sheet-id", "Invoices") is None

    assert fake_s3.objects == {}
    assert "nothing to back up" in caplog.text


def test_read_failure_raises(monkeypatch):
    # the caller relies on this raising so it doesn't overwrite the sheet without a backup
    monkeypatch.setattr(backup, "get_spreadsheet_values", mock.Mock(side_effect=RuntimeError("Sheets down")))

    with pytest.raises(RuntimeError, match="Sheets down"):
        backup.backup_sheet("sheet-id", "Invoices")


def test_upload_failure_raises(sheet_contents, fake_s3):
    sheet_contents([["Id"]])
    fake_s3.fail = RuntimeError("AccessDenied")

    with pytest.raises(RuntimeError, match="AccessDenied"):
        backup.backup_sheet("sheet-id", "Invoices")
