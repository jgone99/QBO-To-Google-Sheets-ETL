from unittest import mock

import pytest
import requests

import config
from qbo_client import client
from qbo_client.client import QBOAPIError


def response(status, body=None, json_error=False):
    r = mock.Mock(status_code=status)
    if json_error:
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = body
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(f"{status} Error")
    return r


@pytest.fixture
def fake_get(monkeypatch):
    def setup(resp):
        get = mock.Mock(return_value=resp)
        monkeypatch.setattr(client._session, "get", get)
        return get
    return setup


def test_query_returns_data(fake_get):
    data = {"QueryResponse": {"Invoice": []}}
    fake_get(response(200, data))

    assert client.query("realm", "token", "SELECT * FROM Invoice") == data


def test_query_request_details(fake_get, monkeypatch):
    monkeypatch.setattr(config, "QBO_BASE_URL", "https://qbo.example")
    get = fake_get(response(200, {}))

    client.query("realm-1", "token-1", "SELECT 1", {"include": "enhancedAllCustomFields"})

    url = get.call_args.args[0]
    kwargs = get.call_args.kwargs
    assert url == "https://qbo.example/v3/company/realm-1/query"
    assert kwargs["params"] == {"query": "SELECT 1", "include": "enhancedAllCustomFields"}
    assert kwargs["headers"]["Authorization"] == "Bearer token-1"
    assert kwargs["timeout"] == config.REQUEST_TIMEOUT_SECONDS


def test_fault_message_surfaces(fake_get):
    body = {"Fault": {"Error": [{"Message": "Error parsing query", "Detail": "bad token", "code": "4000"}]}}
    fake_get(response(400, body))

    with pytest.raises(QBOAPIError, match=r"Error parsing query - bad token \(code 4000, HTTP 400\)"):
        client.query("realm", "token", "SELECT")


def test_lowercase_auth_fault_surfaces(fake_get):
    body = {"fault": {"error": [{"message": "AuthenticationFailed", "detail": "Token expired", "code": "3200"}]}}
    fake_get(response(401, body))

    with pytest.raises(QBOAPIError, match=r"AuthenticationFailed - Token expired \(code 3200, HTTP 401\)"):
        client.query("realm", "token", "SELECT")


def test_fault_in_200_response_raises(fake_get):
    body = {"Fault": {"Error": [{"Message": "Something went wrong"}]}}
    fake_get(response(200, body))

    with pytest.raises(QBOAPIError, match="Something went wrong"):
        client.query("realm", "token", "SELECT")


def test_http_error_without_fault(fake_get):
    fake_get(response(503, {"unexpected": True}))

    with pytest.raises(requests.HTTPError):
        client.query("realm", "token", "SELECT")


def test_non_json_error_response(fake_get):
    fake_get(response(502, json_error=True))

    with pytest.raises(requests.HTTPError):
        client.query("realm", "token", "SELECT")


def test_non_json_success_response(fake_get):
    fake_get(response(200, json_error=True))

    with pytest.raises(QBOAPIError, match="non-JSON response"):
        client.query("realm", "token", "SELECT")


def test_retries_transient_errors():
    retry = client._session.get_adapter("https://quickbooks.api.intuit.com").max_retries

    assert retry.total == 3
    assert {429, 500, 502, 503, 504} <= set(retry.status_forcelist)
    # the final response is returned (not raised) so its Fault message can be read
    assert retry.raise_on_status is False
