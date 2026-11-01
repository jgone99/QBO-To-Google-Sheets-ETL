from aws_client import session

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = session.get_session().client("sts")
    return _client

def get_account_id() -> str:
    """
    The AWS account the current credentials belong to. STS GetCallerIdentity needs no
    IAM permission, so this works with any valid credentials.
    """
    return _get_client().get_caller_identity()["Account"]
