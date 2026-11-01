from aws_client import session
import config

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = session.get_session().client("s3")
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
