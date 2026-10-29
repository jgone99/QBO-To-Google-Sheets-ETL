from unittest import mock

import pytest

from spreadsheet_client import auth


class FakeStore:
    def __init__(self, key):
        self.key = key
        self.loads = 0

    def load(self):
        self.loads += 1
        return self.key


@pytest.fixture
def google(monkeypatch):
    """
    Fakes google-auth: the credential factory and the authorized session.
    """
    fakes = mock.Mock()
    monkeypatch.setattr(auth.service_account.Credentials, "from_service_account_info", fakes.from_info)
    monkeypatch.setattr(auth, "AuthorizedSession", fakes.Session)
    return fakes


def test_session_built_from_the_stored_key(google):
    store = FakeStore({"type": "service_account", "client_email": "etl@example.com"})
    auth.use_store(store)

    session = auth.get_session()

    google.from_info.assert_called_once_with(store.key, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    google.Session.assert_called_once_with(google.from_info.return_value)
    assert session is google.Session.return_value


def test_session_retries_transient_errors(google):
    auth.use_store(FakeStore({}))

    session = auth.get_session()

    prefix, adapter = session.mount.call_args.args
    assert prefix == "https://"
    retry = adapter.max_retries
    assert retry.total == 3
    assert {429, 500, 502, 503, 504} <= set(retry.status_forcelist)
    assert {"GET", "POST", "PUT"} <= set(retry.allowed_methods)
    assert retry.raise_on_status is False


def test_session_is_reused_within_a_run(google):
    store = FakeStore({})
    auth.use_store(store)

    assert auth.get_session() is auth.get_session()
    assert store.loads == 1


def test_new_run_builds_a_new_session(google):
    first = FakeStore({})
    second = FakeStore({})
    auth.use_store(first)
    auth.get_session()

    auth.use_store(second)
    auth.get_session()

    assert (first.loads, second.loads) == (1, 1)


def test_no_store_set():
    auth.use_store(None)

    with pytest.raises(RuntimeError, match="use_store"):
        auth.get_session()
