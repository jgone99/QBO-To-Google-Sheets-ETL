from datetime import datetime, timezone

import pytest

import config


def test_valid_config_passes():
    # conftest sets every required setting to a fake value
    config.validate()


def test_missing_settings_are_named(monkeypatch):
    monkeypatch.delenv("SPREADSHEET_ID")
    monkeypatch.setenv("BACKUP_BUCKET", "")

    with pytest.raises(ValueError, match="missing settings: BACKUP_BUCKET, SPREADSHEET_ID"):
        config.validate()


def test_error_never_contains_setting_values(monkeypatch):
    monkeypatch.delenv("BACKUP_BUCKET")
    monkeypatch.setattr(config, "QBO_BASE_URL", None)

    with pytest.raises(ValueError) as error:
        config.validate()

    assert "test-qbo-secret" not in str(error.value)
    assert "test-sheet" not in str(error.value)


def test_invalid_environment(monkeypatch):
    monkeypatch.setattr(config, "QBO_ENVIRONMENT", "prod")
    monkeypatch.setattr(config, "QBO_BASE_URL", None)

    with pytest.raises(ValueError, match="QBO_ENVIRONMENT must be one of .* got 'prod'"):
        config.validate()


def test_invalid_time_zone(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "Eastern")

    with pytest.raises(ValueError, match="TIMEZONE is not a valid time zone: 'Eastern'"):
        config.validate()


def test_local_run_needs_a_profile(monkeypatch):
    # without one, boto3 would fall back to the [default] credentials
    monkeypatch.delenv("AWS_PROFILE")

    with pytest.raises(ValueError, match="AWS_PROFILE must be set for local runs"):
        config.validate()


def test_local_run_rejects_access_keys_in_the_environment(monkeypatch):
    # boto3 uses these ahead of AWS_PROFILE
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")

    with pytest.raises(ValueError, match="AWS_ACCESS_KEY_ID is set") as error:
        config.validate()

    assert "AKIAEXAMPLE" not in str(error.value)


def test_lambda_skips_the_profile_check(monkeypatch):
    # Lambda gets credentials from the function's role, and sets AWS_ACCESS_KEY_ID itself
    monkeypatch.setattr(config, "ON_LAMBDA", True)
    monkeypatch.delenv("AWS_PROFILE")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")

    config.validate()


def test_all_problems_reported_together(monkeypatch):
    monkeypatch.delenv("SPREADSHEET_ID")
    monkeypatch.setattr(config, "QBO_BASE_URL", None)
    monkeypatch.setattr(config, "TIMEZONE", "Eastern")

    with pytest.raises(ValueError) as error:
        config.validate()

    message = str(error.value)
    assert "SPREADSHEET_ID" in message
    assert "QBO_ENVIRONMENT" in message
    assert "TIMEZONE" in message


def test_now_is_in_the_business_time_zone():
    local = config.now()
    utc = datetime.now(timezone.utc)

    assert str(local.tzinfo) == "America/New_York"
    # same moment, different wall clock
    assert abs((local - utc).total_seconds()) < 5


def test_today_is_the_business_date():
    assert config.today() == config.now().date()


def test_base_urls():
    assert config.QBO_BASE_URLS["sandbox"] == "https://sandbox-quickbooks.api.intuit.com"
    assert config.QBO_BASE_URLS["production"] == "https://quickbooks.api.intuit.com"
