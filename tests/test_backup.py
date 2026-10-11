import csv
import logging
from datetime import date, timedelta
from unittest import mock

import pytest

import backup


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


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.reader(file))


# --- backup_sheet

def test_backup_saves_current_sheet_as_csv(sheet_contents, isolated_backups):
    rows = [["Id", "DocNumber", "TotalAmt"], ["1", "1001", "$250.00"], ["2", "1002", "$20.00"]]
    get = sheet_contents(rows)

    path = backup.backup_sheet("sheet-id", "Invoices")

    get.assert_called_once_with("sheet-id", "Invoices")
    assert path.parent == isolated_backups
    assert read_csv(path) == rows


def test_backup_file_name_has_timestamp_and_sheet_name(sheet_contents):
    sheet_contents([["Id"]])

    path = backup.backup_sheet("sheet-id", "Invoices")

    assert backup.BACKUP_NAME_PATTERN.match(path.name)
    assert path.name.startswith(date.today().isoformat())
    assert path.name.endswith("_Invoices.csv")


def test_backup_file_name_is_safe_for_any_sheet_name(sheet_contents):
    sheet_contents([["Id"]])

    path = backup.backup_sheet("sheet-id", "Bob's Sheet/2026")

    assert path.name.endswith("_Bob_s_Sheet_2026.csv")


def test_backup_handles_commas_quotes_and_accents(sheet_contents):
    rows = [["CustomerName"], ['Smith, "Bob" & Sons'], ["Peña Cerrajería"]]
    sheet_contents(rows)

    path = backup.backup_sheet("sheet-id", "Invoices")

    assert read_csv(path) == rows


def test_backup_keeps_uneven_rows(sheet_contents):
    # Sheets drops trailing empty cells, so rows can have different lengths
    rows = [["Id", "DueDate", "CustomerPO"], ["1", "2026-08-01"], ["2"]]
    sheet_contents(rows)

    path = backup.backup_sheet("sheet-id", "Invoices")

    assert read_csv(path) == rows


def test_empty_sheet_is_not_backed_up(sheet_contents, isolated_backups, caplog):
    sheet_contents([])

    with caplog.at_level(logging.INFO):
        assert backup.backup_sheet("sheet-id", "Invoices") is None

    assert not isolated_backups.exists() or not any(isolated_backups.iterdir())
    assert "nothing to back up" in caplog.text


def test_read_failure_raises(monkeypatch):
    # the caller relies on this raising so it doesn't overwrite the sheet without a backup
    monkeypatch.setattr(backup, "get_spreadsheet_values", mock.Mock(side_effect=RuntimeError("Sheets down")))

    with pytest.raises(RuntimeError, match="Sheets down"):
        backup.backup_sheet("sheet-id", "Invoices")


# --- cleanup_old_backups

def make_backup(backups_dir, days_old):
    backups_dir.mkdir(exist_ok=True)
    path = backups_dir / f"{date.today() - timedelta(days=days_old)}_093000_Invoices.csv"
    path.write_text("x")
    return path


def test_cleanup_deletes_backups_at_or_past_the_limit(isolated_backups, monkeypatch):
    monkeypatch.setattr(backup, "MAX_BACKUP_RETENTION_DAYS", 30)
    monkeypatch.setattr(backup, "MAX_BACKUP_RETENTION_BUFFER_DAYS", 1)
    kept = [make_backup(isolated_backups, days) for days in (0, 1, 28)]
    deleted = [make_backup(isolated_backups, days) for days in (29, 30, 90)]

    backup.cleanup_old_backups()

    assert all(p.exists() for p in kept)
    assert not any(p.exists() for p in deleted)


def test_cleanup_leaves_other_files_alone(isolated_backups):
    make_backup(isolated_backups, 90)
    other = isolated_backups / "restored-copy.csv"
    other.write_text("x")

    backup.cleanup_old_backups()

    assert other.exists()


def test_cleanup_with_no_backups_folder(isolated_backups):
    assert not isolated_backups.exists()

    backup.cleanup_old_backups()


def test_cleanup_failure_is_logged_not_raised(isolated_backups, monkeypatch, caplog):
    isolated_backups.mkdir()
    monkeypatch.setattr(backup, "delete_expired_files", mock.Mock(side_effect=PermissionError("file in use")))

    with caplog.at_level(logging.ERROR):
        backup.cleanup_old_backups()

    assert "Backup cleanup failed" in caplog.text
