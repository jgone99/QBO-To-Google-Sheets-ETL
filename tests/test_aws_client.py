from unittest import mock

import pytest

from aws_client import account, credentials, secrets, session, storage

# conftest blocks get_session; kept here to test the real one
REAL_GET_SESSION = session.get_session


@pytest.fixture
def boto_session(monkeypatch):
    """
    A fake shared session, with temporary credentials like Lambda's role or `aws login` give.
    """
    fake = mock.Mock(region_name="us-east-2")
    frozen = fake.get_credentials.return_value.get_frozen_credentials.return_value
    frozen.access_key, frozen.secret_key, frozen.token = "AKIDEXAMPLE", "secret-example", "session-example"
    monkeypatch.setattr(session, "get_session", lambda: fake)
    return fake


# --- the shared session

def test_one_session_is_created_in_the_app_region(monkeypatch):
    monkeypatch.setattr(session, "get_session", REAL_GET_SESSION)
    monkeypatch.setattr(session, "_session", None)
    Session = mock.Mock()
    monkeypatch.setattr(session.boto3, "Session", Session)

    assert session.get_session() is session.get_session()
    Session.assert_called_once_with(region_name="us-east-2")


@pytest.mark.parametrize("module, service", [
    (secrets, "secretsmanager"),
    (storage, "s3"),
    (account, "sts"),
])
def test_clients_come_from_the_shared_session(module, service, monkeypatch, boto_session):
    monkeypatch.setattr(module, "_client", None)

    assert module._get_client() is boto_session.client.return_value
    boto_session.client.assert_called_once_with(service)


# --- clients

def test_account_id_comes_from_the_caller_identity(monkeypatch):
    sts = mock.Mock()
    sts.get_caller_identity.return_value = {"Account": "123456789012", "Arn": "arn", "UserId": "id"}
    monkeypatch.setattr(account, "_get_client", lambda: sts)

    assert account.get_account_id() == "123456789012"


def test_aws_credentials_come_from_the_shared_session(boto_session):
    source = credentials.AwsCredentials()

    assert source.get() == ("AKIDEXAMPLE", "secret-example", "session-example")
    assert source.region == "us-east-2"


def test_no_aws_credentials(boto_session):
    boto_session.get_credentials.return_value = None

    with pytest.raises(RuntimeError, match="No AWS credentials"):
        credentials.AwsCredentials().get()


def test_read_json_secret(fake_secrets):
    assert secrets.get_json_secret("test-qbo-secret")["QBO_REALM_ID"] == "123"


def test_write_json_secret(fake_secrets):
    secrets.put_json_secret("test-qbo-secret", {"a": 1})

    assert fake_secrets.puts == [("test-qbo-secret", {"a": 1})]


def test_json_secret_store(fake_secrets):
    store = secrets.JsonSecret("test-google-secret")

    assert store.load()["type"] == "service_account"

    store.save({"type": "service_account", "client_email": "new@example.com"})
    assert fake_secrets.secrets["test-google-secret"]["client_email"] == "new@example.com"


def test_put_object_goes_to_the_backup_bucket(fake_s3):
    storage.put_object("backups/x.csv", b"Id\r\n", "text/csv")

    assert fake_s3.objects == {("test-bucket", "backups/x.csv"): {"body": b"Id\r\n", "content_type": "text/csv"}}
