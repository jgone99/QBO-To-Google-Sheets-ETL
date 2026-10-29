import boto3
import config

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = boto3.client("sts", region_name=config.AWS_REGION)
    return _client

def get_account_id() -> str:
    """
    The AWS account the current credentials belong to. STS GetCallerIdentity needs no
    IAM permission, so this works with any valid credentials.
    """
    return _get_client().get_caller_identity()["Account"]
