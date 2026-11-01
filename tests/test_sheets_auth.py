from unittest import mock

import pytest

from spreadsheet_client import auth

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

KEY = {"type": "service_account", "client_email": "etl@example.iam.gserviceaccount.com"}

# the shape `gcloud iam workload-identity-pools create-cred-config --aws` writes
FEDERATION = {
    "type": "external_account",
    "audience": "//iam.googleapis.com/projects/123/locations/global/workloadIdentityPools/aws-pool/providers/aws-provider",
    "subject_token_type": "urn:ietf:params:aws:token-type:aws4_request",
    "service_account_impersonation_url": "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/etl@example.iam.gserviceaccount.com:generateAccessToken",
    "token_url": "https://sts.googleapis.com/v1/token",
    "credential_source": {
        "environment_id": "aws1",
        "region_url": "http://169.254.169.254/latest/meta-data/placement/availability-zone",
        "url": "http://169.254.169.254/latest/meta-data/iam/security-credentials",
        "regional_cred_verification_url": "https://sts.{region}.amazonaws.com?Action=GetCallerIdentity&Version=2011-06-15",
    },
}


class FakeStore:
    def __init__(self, info):
        self.info = info
        self.loads = 0

    def load(self):
        self.loads += 1
        return self.info


class FakeAwsCredentials:
    region = "us-east-2"

    def get(self):
        return "AKIDEXAMPLE", "secret-example", "session-example"


@pytest.fixture
def google(monkeypatch):
    """
    Fakes google-auth: both credential factories and the authorized session.
    """
    fakes = mock.Mock()
    monkeypatch.setattr(auth.service_account.Credentials, "from_service_account_info", fakes.from_key)
    monkeypatch.setattr(auth.aws.Credentials, "from_info", fakes.from_federation)
    monkeypatch.setattr(auth, "AuthorizedSession", fakes.Session)
    return fakes


# --- service account key

def test_session_built_from_the_stored_key(google):
    store = FakeStore(KEY)
    auth.use_store(store)

    session = auth.get_session()

    google.from_key.assert_called_once_with(KEY, scopes=SCOPES)
    google.from_federation.assert_not_called()
    google.Session.assert_called_once_with(google.from_key.return_value)
    assert session is google.Session.return_value


def test_key_needs_no_aws_credentials(google):
    auth.use_store(FakeStore(KEY), aws_credentials=None)

    auth.get_session()

    google.from_key.assert_called_once()


# --- workload identity federation

def test_session_built_from_the_federation_config(google):
    aws_credentials = FakeAwsCredentials()
    auth.use_store(FakeStore(FEDERATION), aws_credentials=aws_credentials)

    session = auth.get_session()

    google.from_key.assert_not_called()
    [info] = google.from_federation.call_args.args
    kwargs = google.from_federation.call_args.kwargs
    # the supplier replaces the config's EC2/environment credential source
    assert info["credential_source"] is None
    assert info["audience"] == FEDERATION["audience"]
    assert info["service_account_impersonation_url"] == FEDERATION["service_account_impersonation_url"]
    assert kwargs["scopes"] == SCOPES
    assert isinstance(kwargs["aws_security_credentials_supplier"], auth.aws.AwsSecurityCredentialsSupplier)
    google.Session.assert_called_once_with(google.from_federation.return_value)
    assert session is google.Session.return_value


def test_stored_config_is_not_modified(google):
    store = FakeStore(dict(FEDERATION))
    auth.use_store(store, aws_credentials=FakeAwsCredentials())

    auth.get_session()

    assert store.info["credential_source"] == FEDERATION["credential_source"]


def test_supplier_hands_over_the_aws_credentials():
    supplier = auth._AwsSupplier(FakeAwsCredentials())

    credentials = supplier.get_aws_security_credentials(None, None)

    assert credentials.access_key_id == "AKIDEXAMPLE"
    assert credentials.secret_access_key == "secret-example"
    assert credentials.session_token == "session-example"
    assert supplier.get_aws_region(None, None) == "us-east-2"


def test_federation_without_aws_credentials(google):
    auth.use_store(FakeStore(FEDERATION), aws_credentials=None)

    with pytest.raises(RuntimeError, match="no AWS credentials"):
        auth.get_session()


def test_real_google_auth_accepts_the_config():
    # no fakes: google-auth itself builds the credentials (nothing is fetched until a request)
    auth.use_store(FakeStore(FEDERATION), aws_credentials=FakeAwsCredentials())

    credentials = auth._build_credentials(FEDERATION)

    assert isinstance(credentials, auth.aws.Credentials)
    assert credentials.service_account_email == "etl@example.iam.gserviceaccount.com"


# --- check_credentials_info

def test_valid_credentials_pass():
    auth.check_credentials_info(KEY)
    auth.check_credentials_info(FEDERATION)


@pytest.mark.parametrize("info, message", [
    ({"type": "authorized_user"}, "service account key or a workload identity federation config"),
    ({}, "got None"),
    ({**FEDERATION, "subject_token_type": "urn:ietf:params:oauth:token-type:jwt"}, "not for AWS"),
    ({**FEDERATION, "service_account_impersonation_url": None}, "no service account to act as"),
    ({**FEDERATION, "token_url": "https://evil.example.com/token"}, "token_url is not a googleapis.com address"),
    ({**FEDERATION, "service_account_impersonation_url": "https://googleapis.com.evil.example/x"},
     "service_account_impersonation_url is not a googleapis.com address"),
])
def test_unusable_credentials_are_rejected(info, message, google):
    with pytest.raises(ValueError, match=message):
        auth.check_credentials_info(info)

    auth.use_store(FakeStore(info), aws_credentials=FakeAwsCredentials())
    with pytest.raises(ValueError):
        auth.get_session()
    google.Session.assert_not_called()


# --- session lifetime

def test_session_retries_transient_errors(google):
    auth.use_store(FakeStore(KEY))

    session = auth.get_session()

    prefix, adapter = session.mount.call_args.args
    assert prefix == "https://"
    retry = adapter.max_retries
    assert retry.total == 3
    assert {429, 500, 502, 503, 504} <= set(retry.status_forcelist)
    assert {"GET", "POST", "PUT"} <= set(retry.allowed_methods)
    assert retry.raise_on_status is False


def test_session_is_reused_within_a_run(google):
    store = FakeStore(KEY)
    auth.use_store(store)

    assert auth.get_session() is auth.get_session()
    assert store.loads == 1


def test_new_run_builds_a_new_session(google):
    first = FakeStore(KEY)
    second = FakeStore(KEY)
    auth.use_store(first)
    auth.get_session()

    auth.use_store(second)
    auth.get_session()

    assert (first.loads, second.loads) == (1, 1)


def test_no_store_set():
    auth.use_store(None)

    with pytest.raises(RuntimeError, match="use_store"):
        auth.get_session()
