import boto3
import config

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = boto3.client("s3", region_name=config.AWS_REGION)
    return _client

def put_object(key: str, body: bytes, content_type: str):
    """
    Write an object to the backup bucket.
    """
    _get_client().put_object(
        Bucket=config.BACKUP_BUCKET,
        Key=key,
        Body=body,
        ContentType=content_type,
    )
