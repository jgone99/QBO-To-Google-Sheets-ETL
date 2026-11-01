import boto3
import config

_session = None

def get_session() -> boto3.Session:
    """
    The one boto3 session the app uses. Every AWS client, and the credentials Google
    federation signs in with, come from it, so they always share one identity and region:
    the function's role on Lambda, the AWS_PROFILE sign-in (`aws login`) locally.
    """
    global _session
    if _session is None:
        _session = boto3.Session(region_name=config.AWS_REGION)
    return _session
