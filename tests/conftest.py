import pytest
from unittest import mock

import backup
import logger
import qbo_client.auth
import qbo_client.client
import qbo_client.invoices
import spreadsheet_client.client


class NetworkBlocked(Exception):
    pass


def _blocked(*args, **kwargs):
    raise NetworkBlocked("Tests must not call QBO or Google. Mock the call instead.")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """
    Safety net: any test that reaches a real QBO or Google call fails instead of touching
    live data or rotating the QBO refresh token. Tests that need these calls patch over them.
    """
    monkeypatch.setattr(qbo_client.auth, "get_access_token", _blocked)
    # invoices imported get_access_token by name, so its copy has to be blocked too
    monkeypatch.setattr(qbo_client.invoices, "get_access_token", _blocked)
    monkeypatch.setattr(qbo_client.client._session, "get", _blocked)
    monkeypatch.setattr(spreadsheet_client.client, "get_service_account", _blocked)


@pytest.fixture(autouse=True)
def isolated_logs(tmp_path, monkeypatch):
    # any log files a test creates go to a temp folder, never the real logs/
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    monkeypatch.setattr(logger, "LOGS_DIR", logs_dir)
    return logs_dir


@pytest.fixture(autouse=True)
def isolated_backups(tmp_path, monkeypatch):
    # backups go to a temp folder, never the real backups/. Not created up front,
    # since backup_sheet is responsible for creating it
    backups_dir = tmp_path / "backups"
    monkeypatch.setattr(backup, "BACKUPS_DIR", backups_dir)
    return backups_dir


@pytest.fixture
def sheets_service(monkeypatch):
    """
    A fake Google Sheets service. Returns the mock for spreadsheets().values() as `values`
    and spreadsheets() as `spreadsheets` so tests can inspect calls.
    """
    service = mock.MagicMock()
    monkeypatch.setattr(spreadsheet_client.client, "get_service_account", lambda: service)
    return mock.Mock(
        service=service,
        spreadsheets=service.spreadsheets.return_value,
        values=service.spreadsheets.return_value.values.return_value,
    )
