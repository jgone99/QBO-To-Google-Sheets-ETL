import logging
from typing import Protocol
from urllib.parse import urlparse
from google.auth import aws
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# the two ways to sign in, told apart by the "type" field of the stored JSON:
#   service_account   a service account key (the JSON Google provides)
#   external_account  a workload identity federation config (from gcloud create-cred-config --aws):
#                     AWS credentials are exchanged for a token of the service account, so no
#                     Google key exists anywhere
SERVICE_ACCOUNT_KEY = "service_account"
FEDERATION_CONFIG = "external_account"

AWS_SUBJECT_TOKEN_TYPE = "urn:ietf:params:aws:token-type:aws4_request"

class CredentialStore(Protocol):
    """
    Where the service account key or federation config lives. The entry point picks one
    (e.g. aws_client.secrets.JsonSecret), so this package has no AWS dependency.
    """
    def load(self) -> dict: ...

class AwsCredentialSource(Protocol):
    """
    Supplies the AWS credentials that federation signs in with (e.g. aws_client.credentials.AwsCredentials).
    """
    @property
    def region(self) -> str: ...
    def get(self) -> tuple[str, str, str | None]: ...

# retry transient failures (rate limits, server errors) with exponential backoff.
# Writing and clearing values are safe to repeat. Adding a sheet isn't (a retry after a
# lost response fails with "already exists"), but the status sheet only logs that and the
# next run finds the sheet. raise_on_status=False hands back the final response so its
# error message can be read
_retry = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST", "PUT"],
    raise_on_status=False
)

_store: CredentialStore | None = None
_aws_credentials: AwsCredentialSource | None = None
_session = None

def use_store(store: CredentialStore, aws_credentials: AwsCredentialSource | None = None):
    """
    Set where the Google credentials are read from (and, for federation, which AWS
    credentials to sign in with), and forget any session from a previous run. Called at
    the start of every run, since Lambda can reuse this process.
    """
    global _store, _aws_credentials, _session
    _store = store
    _aws_credentials = aws_credentials
    _session = None

def get_session() -> AuthorizedSession:
    """
    A requests session that adds the service account's access token to every request
    and refreshes it when it expires.
    """
    global _session
    if _session is None:
        if _store is None:
            raise RuntimeError("No Google credential store set, call spreadsheet_client.auth.use_store() first")

        session = AuthorizedSession(_build_credentials(_store.load()))
        session.mount("https://", HTTPAdapter(max_retries=_retry))
        _session = session

    return _session

def check_credentials_info(info: dict):
    """
    Raise ValueError unless info is a service account key or a usable AWS federation config.
    Also used by scripts/seed_secrets.py before storing it. Never includes secret values.
    """
    kind = info.get("type")
    if kind == SERVICE_ACCOUNT_KEY:
        return
    if kind != FEDERATION_CONFIG:
        raise ValueError(f"Google credentials must be a service account key or a workload identity "
                         f"federation config ('type' {SERVICE_ACCOUNT_KEY} or {FEDERATION_CONFIG}), got {kind!r}")

    if info.get("subject_token_type") != AWS_SUBJECT_TOKEN_TYPE:
        raise ValueError("The federation config is not for AWS: create it with `gcloud iam "
                         "workload-identity-pools create-cred-config ... --aws`")
    # a sheet can only be shared with a service account, not with an AWS identity directly
    if not info.get("service_account_impersonation_url"):
        raise ValueError("The federation config has no service account to act as: create it with --service-account")

    # google-auth sends the AWS-signed request to these URLs without checking them, so make
    # sure they are Google's, as Google recommends for configs not straight from gcloud
    for field in ("token_url", "service_account_impersonation_url"):
        host = urlparse(info.get(field) or "").hostname or ""
        if not host.endswith(".googleapis.com"):
            raise ValueError(f"The federation config's {field} is not a googleapis.com address")

def _build_credentials(info: dict):
    check_credentials_info(info)

    if info["type"] == SERVICE_ACCOUNT_KEY:
        logging.info(f"Google sign-in: service account key for {info.get('client_email')}")
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    if _aws_credentials is None:
        raise RuntimeError("The Google credentials are a federation config, but no AWS credentials were "
                           "passed to spreadsheet_client.auth.use_store()")

    logging.info("Google sign-in: workload identity federation with AWS credentials")
    # the supplier replaces the config's credential_source (EC2 metadata / environment
    # variables), so local `aws login` sign-ins work as well as Lambda's role
    return aws.Credentials.from_info(
        {**info, "credential_source": None},
        aws_security_credentials_supplier=_AwsSupplier(_aws_credentials),
        scopes=SCOPES,
    )

class _AwsSupplier(aws.AwsSecurityCredentialsSupplier):
    """
    Hands google-auth the AWS credentials to sign its GetCallerIdentity request with.
    google-auth doesn't cache them; the source (boto3) caches and refreshes them itself.
    """
    def __init__(self, source: AwsCredentialSource):
        self._source = source

    def get_aws_security_credentials(self, context, request):
        access_key_id, secret_access_key, session_token = self._source.get()
        return aws.AwsSecurityCredentials(access_key_id, secret_access_key, session_token)

    def get_aws_region(self, context, request):
        return self._source.region
