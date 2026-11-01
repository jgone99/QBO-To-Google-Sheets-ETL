import json
from aws_client import session

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = session.get_session().client("secretsmanager")
    return _client

def get_json_secret(secret_id: str) -> dict:
    """
    Read a secret stored as a JSON object. Raises if it doesn't exist or isn't readable.
    """
    response = _get_client().get_secret_value(SecretId=secret_id)
    return json.loads(response["SecretString"])

def put_json_secret(secret_id: str, value: dict):
    """
    Store a new version of a JSON secret. The new version becomes AWSCURRENT and the
    old one is kept as AWSPREVIOUS, so a bad write can be rolled back in the console.
    """
    _get_client().put_secret_value(SecretId=secret_id, SecretString=json.dumps(value))

class JsonSecret:
    """
    A JSON secret used as a credential store, e.g. qbo_client.auth.use_store(JsonSecret(secret_id)).
    """
    def __init__(self, secret_id: str):
        self.secret_id = secret_id

    def load(self) -> dict:
        return get_json_secret(self.secret_id)

    def save(self, value: dict):
        put_json_secret(self.secret_id, value)
