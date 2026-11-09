import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt, jwt
from google.oauth2 import id_token

import config
import sync_request

CLIENT_ID = "123-script.apps.googleusercontent.com"
KEY_ID = "test-key"


def _private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


SIGNING_KEY = _private_key()
OTHER_KEY = _private_key()


def _pem(key, public=False):
    if public:
        return key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def make_token(key=SIGNING_KEY, **overrides):
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1001",
        "email": "owner@example.com",
        "email_verified": True,
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    signer = crypt.RSASigner.from_string(_pem(key), key_id=KEY_ID)
    return jwt.encode(signer, claims).decode()


def url_event(token=None, method="POST", header="authorization"):
    headers = {header: f"Bearer {token}"} if token else {}
    return {"requestContext": {"http": {"method": method}}, "headers": headers}


@pytest.fixture(autouse=True)
def button_settings(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_SCRIPT_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(config, "ALLOWED_SYNC_EMAILS", {"owner@example.com"})


@pytest.fixture
def google_certs(monkeypatch):
    """
    Google's real verifier, checking against our test key instead of fetching Google's certificates.
    """
    monkeypatch.setattr(sync_request.id_token, "verify_oauth2_token", REAL_VERIFY)
    monkeypatch.setattr(id_token, "_fetch_certs", lambda request, url: {KEY_ID: _pem(SIGNING_KEY, public=True)})


# conftest blocks the verifier; kept here to test the real one
REAL_VERIFY = id_token.verify_oauth2_token


def rejection(event):
    with pytest.raises(sync_request.Rejected) as raised:
        sync_request.authorize(event)
    return raised.value.status, raised.value.message


# --- telling requests apart

def test_url_request_is_recognized():
    assert sync_request.is_url_request(url_event())


@pytest.mark.parametrize("event", [{}, {"requested_by": "owner@example.com"}, None, {"requestContext": {}}])
def test_other_events_are_not_url_requests(event):
    assert not sync_request.is_url_request(event)


# --- accepted

def test_valid_token_from_an_allowed_account(google_certs):
    assert sync_request.authorize(url_event(make_token())) == "owner@example.com"


def test_header_name_and_email_case_dont_matter(google_certs):
    event = url_event(make_token(email="Owner@Example.com"), header="Authorization")

    assert sync_request.authorize(event) == "owner@example.com"


def test_email_verified_as_a_string(google_certs):
    assert sync_request.authorize(url_event(make_token(email_verified="true"))) == "owner@example.com"


def test_issuer_without_https(google_certs):
    assert sync_request.authorize(url_event(make_token(iss="accounts.google.com"))) == "owner@example.com"


# --- refused before the token is looked at

@pytest.mark.parametrize("setting, value", [("GOOGLE_SCRIPT_CLIENT_ID", None), ("ALLOWED_SYNC_EMAILS", set())])
def test_refused_when_not_set_up(setting, value, monkeypatch):
    monkeypatch.setattr(config, setting, value)

    assert rejection(url_event(make_token())) == (403, "Manual sync is not set up")


def test_only_post():
    assert rejection(url_event(make_token(), method="GET"))[0] == 405


@pytest.mark.parametrize("event", [
    url_event(),
    {"requestContext": {"http": {"method": "POST"}}, "headers": {"authorization": "Basic abc"}},
    {"requestContext": {"http": {"method": "POST"}}, "headers": {"authorization": "Bearer "}},
    {"requestContext": {"http": {"method": "POST"}}},
])
def test_missing_token(event):
    assert rejection(event) == (401, "Missing Google identity token")


# --- refused by Google's checks

@pytest.mark.parametrize("token", [
    make_token(aud="another-app.apps.googleusercontent.com"),
    make_token(iss="https://evil.example.com"),
    make_token(exp=int(time.time()) - 60, iat=int(time.time()) - 3660),
    make_token(key=OTHER_KEY),
    "not-a-jwt",
])
def test_invalid_tokens(token, google_certs):
    assert rejection(url_event(token)) == (401, "Invalid Google identity token")


# --- refused by the account checks

def test_account_not_on_the_list(google_certs):
    assert rejection(url_event(make_token(email="someone@example.com"))) == (403, "someone@example.com is not allowed to start a sync")


@pytest.mark.parametrize("email_verified", [False, "false"])
def test_unverified_email(email_verified, google_certs):
    assert rejection(url_event(make_token(email_verified=email_verified)))[0] == 403


def test_token_without_email(google_certs):
    # what the script sends if its manifest lacks the userinfo.email scope
    assert rejection(url_event(make_token(email=None, email_verified=None)))[0] == 403


def test_rejection_never_contains_the_token(google_certs):
    token = make_token(aud="another-app.apps.googleusercontent.com")

    assert token not in rejection(url_event(token))[1]
