from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from dotenv import load_dotenv, set_key
import os

# load variables from .env file
load_dotenv()

_access_token = None

def get_access_token():
    global _access_token
    if _access_token is not None:
        return _access_token

    # access variables
    client_id = os.getenv("QBO_CLIENT_ID")
    client_secret = os.getenv("QBO_CLIENT_SECRET")
    redirect_uri = os.getenv("QBO_REDIRECT_URI")
    refresh_token = os.getenv("QBO_REFRESH_TOKEN")

    auth_client = AuthClient(client_id, client_secret, redirect_uri, "sandbox")
    auth_client.refresh(refresh_token=refresh_token)

    # save refresh token every time
    set_key(".env", "QBO_REFRESH_TOKEN", auth_client.refresh_token)
    os.environ["QBO_REFRESH_TOKEN"] = auth_client.refresh_token

    _access_token = auth_client.access_token

    return _access_token