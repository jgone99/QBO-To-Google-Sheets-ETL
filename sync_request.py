from google.auth import exceptions as google_exceptions
from google.auth.transport.requests import Request
from google.oauth2 import id_token
import config

# the "Sync now" button in the sheet calls the function's URL with a Google identity token
# for whoever clicked it (Apps Script's ScriptApp.getIdentityToken). Google signs the token,
# so nothing secret is stored on either side: the function only accepts tokens issued to
# the sheet's script, for an allowed Google account

class Rejected(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message

def is_url_request(event) -> bool:
    """
    True for a request to the function's URL; scheduled and background runs have no requestContext.
    """
    return isinstance(event, dict) and "http" in event.get("requestContext", {})

def authorize(event: dict) -> str:
    """
    Check a URL request and return the email of the Google account that sent it.
    Raises Rejected with the HTTP status to reply with. The token is never logged.
    """
    if not config.GOOGLE_SCRIPT_CLIENT_ID or not config.ALLOWED_SYNC_EMAILS:
        raise Rejected(403, "Manual sync is not set up")

    if event["requestContext"]["http"].get("method") != "POST":
        raise Rejected(405, "Use POST")

    headers = {name.lower(): value for name, value in (event.get("headers") or {}).items()}
    scheme, _, token = headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Rejected(401, "Missing Google identity token")

    # checks Google's signature, the issuer, the expiry, and that the token was issued to
    # the sheet's script, so a Google token meant for any other app is refused
    try:
        claims = id_token.verify_oauth2_token(token, Request(), audience=config.GOOGLE_SCRIPT_CLIENT_ID)
    except (ValueError, google_exceptions.GoogleAuthError):
        raise Rejected(401, "Invalid Google identity token")

    email = (claims.get("email") or "").lower()
    # Google sends email_verified as true, or sometimes as the string "true"
    if not email or str(claims.get("email_verified")).lower() != "true":
        raise Rejected(403, "The Google account's email is missing or unverified")

    if email not in config.ALLOWED_SYNC_EMAILS:
        raise Rejected(403, f"{email} is not allowed to start a sync")

    return email
