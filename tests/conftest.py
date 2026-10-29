import json
import logging

import pytest

import aws_client.account
import aws_client.secrets
import aws_client.storage
import config
import qbo_client.auth
import qbo_client.client
import spreadsheet_client.auth
import spreadsheet_client.client


class NetworkBlocked(Exception):
    pass


def _blocked(*args, **kwargs):
    raise NetworkBlocked("Tests must not call QBO, Google or AWS. Use the fake fixtures instead.")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """
    Safety net: any test that reaches a real QBO, Google or AWS call fails instead of touching
    live data or rotating the QBO refresh token. Tests that need these calls use the fakes below.
    """
    monkeypatch.setattr(qbo_client.auth, "AuthClient", _blocked)
    monkeypatch.setattr(qbo_client.client._session, "get", _blocked)
    monkeypatch.setattr(spreadsheet_client.client, "get_session", _blocked)
    monkeypatch.setattr(aws_client.secrets, "_get_client", _blocked)
    monkeypatch.setattr(aws_client.storage, "_get_client", _blocked)
    monkeypatch.setattr(aws_client.account, "_get_client", _blocked)


@pytest.fixture(autouse=True)
def test_settings(monkeypatch):
    # known settings for every test, independent of the .env
    for name, value in {
        "QBO_SECRET_ID": "test-qbo-secret",
        "GOOGLE_SECRET_ID": "test-google-secret",
        "BACKUP_BUCKET": "test-bucket",
        "SPREADSHEET_ID": "test-sheet",
    }.items():
        monkeypatch.setenv(name, value)
        monkeypatch.setattr(config, name, value)

    # a local run (tests never run on Lambda) with a named profile and no keys in the environment
    monkeypatch.setattr(config, "ON_LAMBDA", False)
    monkeypatch.setenv("AWS_PROFILE", "test-profile")
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)

    monkeypatch.setattr(config, "QBO_ENVIRONMENT", "sandbox")
    monkeypatch.setattr(config, "QBO_BASE_URL", config.QBO_BASE_URLS["sandbox"])
    monkeypatch.setattr(config, "TIMEZONE", "America/New_York")
    qbo_client.auth.use_store(None)
    spreadsheet_client.auth.use_store(None)

    yield

    qbo_client.auth.use_store(None)
    spreadsheet_client.auth.use_store(None)
    # handlers added by setup_logging() in a test must not leak into the next one
    logging.getLogger().handlers.clear()


# --- Secrets Manager

class FakeSecretsClient:
    def __init__(self, secrets: dict):
        self.secrets = secrets
        self.puts = []

    def get_secret_value(self, SecretId):
        return {"SecretString": json.dumps(self.secrets[SecretId])}

    def put_secret_value(self, SecretId, SecretString):
        self.puts.append((SecretId, json.loads(SecretString)))
        self.secrets[SecretId] = json.loads(SecretString)


QBO_CREDENTIALS = {
    "QBO_CLIENT_ID": "id",
    "QBO_CLIENT_SECRET": "secret",
    "QBO_REDIRECT_URI": "https://example.com/callback",
    "QBO_REALM_ID": "123",
    "QBO_REFRESH_TOKEN": "refresh-1",
}

GOOGLE_KEY = {
    "type": "service_account",
    "client_email": "etl@example.iam.gserviceaccount.com",
    "private_key": "not-a-real-key",
}


@pytest.fixture
def fake_secrets(monkeypatch):
    client = FakeSecretsClient({
        "test-qbo-secret": dict(QBO_CREDENTIALS),
        "test-google-secret": dict(GOOGLE_KEY),
    })
    monkeypatch.setattr(aws_client.secrets, "_get_client", lambda: client)
    return client


# --- S3

class FakeS3Client:
    def __init__(self):
        self.objects = {}
        self.fail = None

    def put_object(self, Bucket, Key, Body, ContentType):
        if self.fail:
            raise self.fail
        self.objects[(Bucket, Key)] = {"body": Body, "content_type": ContentType}


@pytest.fixture
def fake_s3(monkeypatch):
    client = FakeS3Client()
    monkeypatch.setattr(aws_client.storage, "_get_client", lambda: client)
    return client


# --- Google Sheets API

class FakeResponse:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self.ok = status_code < 400
        self._body = body
        self._text = text
        self.content = (json.dumps(body) if body is not None else (text or "")).encode()

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeSheetsSession:
    """
    Records every Sheets API request. `respond(method, url, **kwargs)` decides the response;
    by default every request succeeds with an empty JSON object.
    """
    def __init__(self):
        self.calls = []
        self.respond = lambda method, url, **kwargs: FakeResponse(200, {})

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.respond(method, url, **kwargs)


@pytest.fixture
def fake_sheets(monkeypatch):
    session = FakeSheetsSession()
    monkeypatch.setattr(spreadsheet_client.client, "get_session", lambda: session)
    return session
