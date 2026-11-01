import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import config

class QBOAPIError(Exception):
    pass

# retry transient failures (rate limits, server errors) with exponential backoff.
# raise_on_status=False hands back the final response so its Fault message can be read
_retry = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    raise_on_status=False
)

_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=_retry))

def query(realm_id: str, access_token: str, query_string: str, extra_params: dict = None):
    response = _session.get(f"{config.QBO_BASE_URL}/v3/company/{realm_id}/query",
        params={"query": query_string, **(extra_params or {})},
        headers={
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    },
        timeout=config.REQUEST_TIMEOUT_SECONDS)

    try:
        data = response.json()
    except ValueError:
        data = None

    # check for a Fault before raise_for_status so QBO's error message isn't lost
    if isinstance(data, dict):
        _raise_for_fault(data, response)

    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        raise QBOAPIError(f"{e}{_tid_suffix(response)}") from e

    if data is None:
        raise QBOAPIError(f"QBO returned a non-JSON response (HTTP {response.status_code}{_tid_suffix(response)})")

    return data

def _tid_suffix(response) -> str:
    # Intuit support uses the intuit_tid response header to find a request in their logs
    tid = response.headers.get("intuit_tid")
    return f", intuit_tid {tid}" if tid else ""

def _raise_for_fault(data: dict, response):
    # QBO uses 'Fault'/'Error' on most errors but lowercase 'fault'/'error' on auth errors
    fault = data.get("Fault") or data.get("fault")
    if not fault:
        return

    errors = fault.get("Error") or fault.get("error") or [{}]
    error = errors[0]
    message = error.get("Message") or error.get("message")
    detail = error.get("Detail") or error.get("detail")
    code = error.get("code")

    raise QBOAPIError(f"{message} - {detail} (code {code}, HTTP {response.status_code}{_tid_suffix(response)})")
