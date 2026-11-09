import json
from aws_client import session

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = session.get_session().client("lambda")
    return _client

def start_background_run(function_arn: str, payload: dict):
    """
    Invoke a function without waiting for it (an asynchronous "Event" invocation), so the
    caller can reply straight away. Lambda queues the run; its retries are set in template.yaml.
    """
    _get_client().invoke(
        FunctionName=function_arn,
        InvocationType="Event",
        Payload=json.dumps(payload).encode(),
    )
