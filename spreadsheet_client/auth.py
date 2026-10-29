from typing import Protocol
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

class CredentialStore(Protocol):
    """
    Where the Google service account key (the JSON Google provides) lives. The entry point
    picks one (e.g. aws_client.secrets.JsonSecret), so this package has no AWS dependency.
    """
    def load(self) -> dict: ...

# retry transient failures (rate limits, server errors) with exponential backoff.
# Every call this client makes is safe to repeat. raise_on_status=False hands back the
# final response so its error message can be read
_retry = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST", "PUT"],
    raise_on_status=False
)

_store: CredentialStore | None = None
_session = None

def use_store(store: CredentialStore):
    """
    Set where the service account key is read from, and forget any session from a
    previous run. Called at the start of every run, since Lambda can reuse this process.
    """
    global _store, _session
    _store = store
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

        credentials = service_account.Credentials.from_service_account_info(_store.load(), scopes=SCOPES)
        session = AuthorizedSession(credentials)
        session.mount("https://", HTTPAdapter(max_retries=_retry))
        _session = session

    return _session
