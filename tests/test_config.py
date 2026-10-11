import pytest

import config


@pytest.fixture
def valid_config(tmp_path, monkeypatch):
    # a complete config made of fake values, independent of the real .env and credentials
    for name in config.REQUIRED_ENV_VARS:
        monkeypatch.setenv(name, f"fake-{name}")

    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}")
    monkeypatch.setattr(config, "CREDENTIALS_PATH", credentials)
    monkeypatch.setattr(config, "QBO_ENVIRONMENT", "sandbox")
    monkeypatch.setattr(config, "QBO_BASE_URL", config.QBO_BASE_URLS["sandbox"])


def test_valid_config_passes(valid_config):
    config.validate()


def test_missing_env_vars_are_named(valid_config, monkeypatch):
    monkeypatch.delenv("SPREADSHEET_ID")
    monkeypatch.setenv("QBO_REALM_ID", "")

    with pytest.raises(ValueError, match="missing from .env: QBO_REALM_ID, SPREADSHEET_ID"):
        config.validate()


def test_error_never_contains_secret_values(valid_config, monkeypatch):
    monkeypatch.delenv("QBO_REALM_ID")
    monkeypatch.setattr(config, "QBO_BASE_URL", None)

    with pytest.raises(ValueError) as error:
        config.validate()

    assert "fake-QBO_CLIENT_SECRET" not in str(error.value)
    assert "fake-QBO_REFRESH_TOKEN" not in str(error.value)


def test_invalid_environment(valid_config, monkeypatch):
    monkeypatch.setattr(config, "QBO_ENVIRONMENT", "prod")
    monkeypatch.setattr(config, "QBO_BASE_URL", None)

    with pytest.raises(ValueError, match="QBO_ENVIRONMENT must be one of .* got 'prod'"):
        config.validate()


def test_missing_credentials_file(valid_config, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CREDENTIALS_PATH", tmp_path / "missing.json")

    with pytest.raises(ValueError, match="Google credentials file not found"):
        config.validate()


def test_all_problems_reported_together(valid_config, monkeypatch, tmp_path):
    monkeypatch.delenv("SPREADSHEET_ID")
    monkeypatch.setattr(config, "QBO_BASE_URL", None)
    monkeypatch.setattr(config, "CREDENTIALS_PATH", tmp_path / "missing.json")

    with pytest.raises(ValueError) as error:
        config.validate()

    message = str(error.value)
    assert "SPREADSHEET_ID" in message
    assert "QBO_ENVIRONMENT" in message
    assert "credentials file" in message


def test_base_urls():
    assert config.QBO_BASE_URLS["sandbox"] == "https://sandbox-quickbooks.api.intuit.com"
    assert config.QBO_BASE_URLS["production"] == "https://quickbooks.api.intuit.com"
