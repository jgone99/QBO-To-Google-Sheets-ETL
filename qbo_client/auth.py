import logging
from typing import Protocol
from intuitlib.client import AuthClient
import config

# the QBO credentials are a JSON object with these keys
SECRET_KEYS = ["QBO_CLIENT_ID", "QBO_CLIENT_SECRET", "QBO_REDIRECT_URI", "QBO_REALM_ID", "QBO_REFRESH_TOKEN"]

class CredentialStore(Protocol):
    """
    Where the QBO credentials live. The entry point picks one (e.g. aws_client.secrets.JsonSecret),
    so this package has no AWS dependency.
    """
    def load(self) -> dict: ...
    def save(self, credentials: dict) -> None: ...

_store: CredentialStore | None = None
_credentials = None
_access_token = None

def use_store(store: CredentialStore):
    """
    Set where credentials are read from and the rotated refresh token is saved to,
    and forget anything cached from a previous run. Called at the start of every run,
    because Lambda can reuse this process for the next day's run, after the token expired.
    """
    global _store
    _store = store
    reset()

def reset():
    global _credentials, _access_token
    _credentials = None
    _access_token = None

def get_realm_id() -> str:
    return _get_credentials()["QBO_REALM_ID"]

def get_access_token() -> str:
    global _access_token
    if _access_token is not None:
        return _access_token

    credentials = _get_credentials()

    auth_client = AuthClient(
        credentials["QBO_CLIENT_ID"],
        credentials["QBO_CLIENT_SECRET"],
        credentials["QBO_REDIRECT_URI"],
        config.QBO_ENVIRONMENT,
    )
    auth_client.refresh(refresh_token=credentials["QBO_REFRESH_TOKEN"])

    # QBO rotates the refresh token, and the old one stops working once the new one is
    # used. Save it before doing anything else: losing it means re-authorizing by hand
    if auth_client.refresh_token != credentials["QBO_REFRESH_TOKEN"]:
        credentials["QBO_REFRESH_TOKEN"] = auth_client.refresh_token
        try:
            _store.save(credentials)
        except Exception:
            logging.critical("QBO issued a new refresh token but saving it failed. "
                             "The stored token may no longer work and QBO may need to be re-authorized")
            raise
        logging.info("Saved the rotated QBO refresh token")

    _access_token = auth_client.access_token

    return _access_token

def _get_credentials() -> dict:
    global _credentials
    if _credentials is None:
        if _store is None:
            raise RuntimeError("No QBO credential store set, call qbo_client.auth.use_store() first")

        credentials = _store.load()

        missing = [key for key in SECRET_KEYS if not credentials.get(key)]
        if missing:
            raise ValueError(f"QBO credentials are missing: {', '.join(missing)}")

        _credentials = credentials

    return _credentials
