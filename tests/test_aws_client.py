from unittest import mock

from aws_client import account, secrets, storage


def test_account_id_comes_from_the_caller_identity(monkeypatch):
    sts = mock.Mock()
    sts.get_caller_identity.return_value = {"Account": "123456789012", "Arn": "arn", "UserId": "id"}
    monkeypatch.setattr(account, "_get_client", lambda: sts)

    assert account.get_account_id() == "123456789012"


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
