import logging

import pytest

from qbo_client import auth
from tests.conftest import QBO_CREDENTIALS


class FakeStore:
    def __init__(self, credentials):
        self.credentials = dict(credentials)
        self.saved = []
        self.fail_save = False

    def load(self):
        return dict(self.credentials)

    def save(self, credentials):
        if self.fail_save:
            raise RuntimeError("Secrets Manager unavailable")
        self.saved.append(dict(credentials))


@pytest.fixture
def intuit(monkeypatch):
    """
    Fakes Intuit's AuthClient. Set `new_refresh_token` to make the refresh rotate the token.
    """
    class FakeAuthClient:
        instances = []
        new_refresh_token = None

        def __init__(self, client_id, client_secret, redirect_uri, environment):
            self.args = (client_id, client_secret, redirect_uri, environment)
            self.refresh_token = None
            self.access_token = None
            FakeAuthClient.instances.append(self)

        def refresh(self, refresh_token):
            self.refreshed_with = refresh_token
            self.refresh_token = FakeAuthClient.new_refresh_token or refresh_token
            self.access_token = "access-1"

    monkeypatch.setattr(auth, "AuthClient", FakeAuthClient)
    return FakeAuthClient


def test_access_token_uses_stored_credentials(intuit):
    auth.use_store(FakeStore(QBO_CREDENTIALS))

    assert auth.get_access_token() == "access-1"

    [client] = intuit.instances
    assert client.args == ("id", "secret", "https://example.com/callback", "sandbox")
    assert client.refreshed_with == "refresh-1"


def test_rotated_refresh_token_is_saved(intuit):
    store = FakeStore(QBO_CREDENTIALS)
    auth.use_store(store)
    intuit.new_refresh_token = "refresh-2"

    auth.get_access_token()

    assert [saved["QBO_REFRESH_TOKEN"] for saved in store.saved] == ["refresh-2"]
    assert store.saved[0]["QBO_CLIENT_ID"] == "id"


def test_unchanged_refresh_token_is_not_saved(intuit):
    store = FakeStore(QBO_CREDENTIALS)
    auth.use_store(store)

    auth.get_access_token()

    assert store.saved == []


def test_failed_save_is_critical_and_raises(intuit, caplog):
    store = FakeStore(QBO_CREDENTIALS)
    store.fail_save = True
    auth.use_store(store)
    intuit.new_refresh_token = "refresh-2"

    with caplog.at_level(logging.CRITICAL), pytest.raises(RuntimeError):
        auth.get_access_token()

    assert "saving it failed" in caplog.text


def test_access_token_cached_within_a_run(intuit):
    auth.use_store(FakeStore(QBO_CREDENTIALS))

    auth.get_access_token()
    auth.get_access_token()

    assert len(intuit.instances) == 1


def test_new_run_refreshes_again(intuit):
    auth.use_store(FakeStore(QBO_CREDENTIALS))
    auth.get_access_token()

    auth.use_store(FakeStore(QBO_CREDENTIALS))
    auth.get_access_token()

    assert len(intuit.instances) == 2


def test_realm_id():
    auth.use_store(FakeStore(QBO_CREDENTIALS))

    assert auth.get_realm_id() == "123"


def test_missing_credentials_are_named():
    incomplete = dict(QBO_CREDENTIALS, QBO_REALM_ID="")
    del incomplete["QBO_CLIENT_SECRET"]
    auth.use_store(FakeStore(incomplete))

    with pytest.raises(ValueError, match="QBO credentials are missing: QBO_CLIENT_SECRET, QBO_REALM_ID"):
        auth.get_realm_id()


def test_no_store_set():
    auth.use_store(None)

    with pytest.raises(RuntimeError, match="use_store"):
        auth.get_access_token()
