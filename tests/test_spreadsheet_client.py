import pytest

from spreadsheet_client import client
from spreadsheet_client.client import SheetsAPIError
from tests.conftest import FakeResponse

API = "https://sheets.googleapis.com/v4/spreadsheets"


# --- as_text / ranges

@pytest.mark.parametrize("value, expected", [
    ("00451", "'00451"),
    (123, "'123"),
    (None, None),
    ("", ""),
])
def test_as_text(value, expected):
    assert client.as_text(value) == expected


@pytest.mark.parametrize("sheet_name, expected", [
    ("Invoices", "'Invoices'!A1"),
    ("Sync Status", "'Sync Status'!A1"),
    ("Bob's Sheet", "'Bob''s Sheet'!A1"),
])
def test_range_quotes_sheet_names(sheet_name, expected):
    assert client._range(sheet_name, "A1") == expected


def test_ranges_in_the_url_are_encoded():
    assert client._path_range("Sync Status", "A1:B3") == "%27Sync%20Status%27%21A1%3AB3"


def test_column_letters():
    assert client._column_letter(1) == "A"
    assert client._column_letter(26) == "Z"
    assert client._column_index("A") == 1
    assert client._column_index("Z") == 26


# --- set_spreadsheet_values

def calls_to(session, suffix):
    return [call for call in session.calls if call["url"].endswith(suffix)]


def test_writes_from_a1_with_user_entered(fake_sheets):
    client.set_spreadsheet_values("sheet-id", "Invoices", [["Id"], ["1"]])

    [write] = calls_to(fake_sheets, "/values:batchUpdate")
    assert write["method"] == "POST"
    assert write["url"] == f"{API}/sheet-id/values:batchUpdate"
    assert write["json"]["valueInputOption"] == "USER_ENTERED"
    assert write["json"]["data"][0]["range"] == "'Invoices'!A1"


def test_blanks_are_written_so_old_values_are_overwritten(fake_sheets):
    # None would make Sheets skip the cell and keep the previous run's value
    client.set_spreadsheet_values("sheet-id", "Invoices", [["Id", "PO"], ["1", None], ["2"]])

    [write] = calls_to(fake_sheets, "/values:batchUpdate")
    assert write["json"]["data"][0]["values"] == [["Id", "PO"], ["1", ""], ["2", ""]]


def test_clears_rows_below_and_columns_right_of_new_data(fake_sheets):
    client.set_spreadsheet_values("sheet-id", "Invoices", [["a", "b"], ["1", "2"], ["3", "4"]])

    [clear] = calls_to(fake_sheets, "/values:batchClear")
    assert clear["json"] == {"ranges": ["'Invoices'!A4:Z", "'Invoices'!C1:Z3"]}


def test_full_width_data_only_clears_rows(fake_sheets):
    row = [str(i) for i in range(26)]

    client.set_spreadsheet_values("sheet-id", "Invoices", [row, row])

    [clear] = calls_to(fake_sheets, "/values:batchClear")
    assert clear["json"] == {"ranges": ["'Invoices'!A3:Z"]}


def test_write_happens_before_clear(fake_sheets):
    client.set_spreadsheet_values("sheet-id", "Invoices", [["a"]])

    assert [call["url"].rsplit(":", 1)[-1] for call in fake_sheets.calls] == ["batchUpdate", "batchClear"]


def test_failed_write_leaves_sheet_untouched(fake_sheets):
    fake_sheets.respond = lambda method, url, **kw: FakeResponse(429, {"error": {"message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}})

    with pytest.raises(SheetsAPIError, match="Quota exceeded"):
        client.set_spreadsheet_values("sheet-id", "Invoices", [["a"]])

    assert calls_to(fake_sheets, "/values:batchClear") == []


def test_failed_clear_raises(fake_sheets):
    fake_sheets.respond = lambda method, url, **kw: (
        FakeResponse(500, {"error": {"message": "Internal error", "status": "INTERNAL"}})
        if url.endswith("batchClear") else FakeResponse(200, {})
    )

    with pytest.raises(SheetsAPIError, match="Internal error"):
        client.set_spreadsheet_values("sheet-id", "Invoices", [["a"]])


# --- other calls

def test_update_values_writes_only_given_cells(fake_sheets):
    client.update_values("sheet-id", "Sync Status", "A2:B3", [["x", "y"]])

    [call] = fake_sheets.calls
    assert call["method"] == "PUT"
    assert call["url"] == f"{API}/sheet-id/values/%27Sync%20Status%27%21A2%3AB3"
    assert call["params"] == {"valueInputOption": "USER_ENTERED"}
    assert call["json"] == {"values": [["x", "y"]]}


def test_get_spreadsheet_values(fake_sheets):
    fake_sheets.respond = lambda method, url, **kw: FakeResponse(200, {"values": [["Id"], ["1"]]})

    result = client.get_spreadsheet_values("sheet-id", "Invoices")

    assert result == {"values": [["Id"], ["1"]]}
    [call] = fake_sheets.calls
    assert call["method"] == "GET"
    assert call["url"] == f"{API}/sheet-id/values/%27Invoices%27%21A%3AZ"


def test_ensure_sheet_exists_does_nothing_when_present(fake_sheets):
    fake_sheets.respond = lambda method, url, **kw: FakeResponse(200, {"sheets": [
        {"properties": {"title": "Invoices"}}, {"properties": {"title": "Sync Status"}}]})

    client.ensure_sheet_exists("sheet-id", "Sync Status")

    [lookup] = fake_sheets.calls
    assert lookup["method"] == "GET"
    assert lookup["params"] == {"fields": "sheets.properties.title"}


def test_ensure_sheet_exists_creates_missing_sheet(fake_sheets):
    fake_sheets.respond = lambda method, url, **kw: FakeResponse(200, {"sheets": [{"properties": {"title": "Invoices"}}]})

    client.ensure_sheet_exists("sheet-id", "Sync Status")

    [_, create] = fake_sheets.calls
    assert create["url"] == f"{API}/sheet-id:batchUpdate"
    assert create["json"] == {"requests": [{"addSheet": {"properties": {"title": "Sync Status"}}}]}


# --- request handling

def test_every_request_has_a_timeout(fake_sheets):
    client.update_values("sheet-id", "Invoices", "A1", [["x"]])

    assert fake_sheets.calls[0]["timeout"] == client.REQUEST_TIMEOUT_SECONDS


def test_google_error_message_surfaces(fake_sheets):
    fake_sheets.respond = lambda method, url, **kw: FakeResponse(400, {"error": {
        "code": 400, "message": "Unable to parse range: 'Invoices'!A1", "status": "INVALID_ARGUMENT"}})

    with pytest.raises(SheetsAPIError, match=r"Unable to parse range.*INVALID_ARGUMENT, HTTP 400"):
        client.get_spreadsheet_values("sheet-id", "Invoices")


def test_non_json_error(fake_sheets):
    fake_sheets.respond = lambda method, url, **kw: FakeResponse(502, text="<html>Bad Gateway</html>")

    with pytest.raises(SheetsAPIError, match="HTTP 502"):
        client.get_spreadsheet_values("sheet-id", "Invoices")


def test_empty_success_response(fake_sheets):
    fake_sheets.respond = lambda method, url, **kw: FakeResponse(200, text="")

    assert client.update_values("sheet-id", "Invoices", "A1", [["x"]]) == {}
