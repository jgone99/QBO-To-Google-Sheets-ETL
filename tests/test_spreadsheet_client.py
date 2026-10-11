import pytest

from spreadsheet_client import client


# --- as_text / _range

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


def test_column_letters():
    assert client._column_letter(1) == "A"
    assert client._column_letter(26) == "Z"
    assert client._column_index("A") == 1
    assert client._column_index("Z") == 26


# --- set_spreadsheet_values

def written(sheets_service):
    return sheets_service.values.batchUpdate.call_args.kwargs["body"]


def cleared_ranges(sheets_service):
    return sheets_service.values.batchClear.call_args.kwargs["body"]["ranges"]


def test_writes_from_a1_with_user_entered(sheets_service):
    client.set_spreadsheet_values("sheet-id", "Invoices", [["Id"], ["1"]])

    body = written(sheets_service)
    assert sheets_service.values.batchUpdate.call_args.kwargs["spreadsheetId"] == "sheet-id"
    assert body["valueInputOption"] == "USER_ENTERED"
    assert body["data"][0]["range"] == "'Invoices'!A1"


def test_blanks_are_written_so_old_values_are_overwritten(sheets_service):
    # None would make Sheets skip the cell and keep the previous run's value
    client.set_spreadsheet_values("sheet-id", "Invoices", [["Id", "PO"], ["1", None], ["2"]])

    assert written(sheets_service)["data"][0]["values"] == [["Id", "PO"], ["1", ""], ["2", ""]]


def test_clears_rows_below_and_columns_right_of_new_data(sheets_service):
    client.set_spreadsheet_values("sheet-id", "Invoices", [["a", "b"], ["1", "2"], ["3", "4"]])

    assert cleared_ranges(sheets_service) == ["'Invoices'!A4:Z", "'Invoices'!C1:Z3"]


def test_full_width_data_only_clears_rows(sheets_service):
    row = [str(i) for i in range(26)]

    client.set_spreadsheet_values("sheet-id", "Invoices", [row, row])

    assert cleared_ranges(sheets_service) == ["'Invoices'!A3:Z"]


def test_write_happens_before_clear(sheets_service):
    order = []
    sheets_service.values.batchUpdate.side_effect = lambda **kw: order.append("write") or sheets_service.values.batchUpdate.return_value
    sheets_service.values.batchClear.side_effect = lambda **kw: order.append("clear") or sheets_service.values.batchClear.return_value

    client.set_spreadsheet_values("sheet-id", "Invoices", [["a"]])

    assert order == ["write", "clear"]


def test_failed_write_leaves_sheet_untouched(sheets_service):
    sheets_service.values.batchUpdate.return_value.execute.side_effect = RuntimeError("quota exceeded")

    with pytest.raises(RuntimeError, match="quota exceeded"):
        client.set_spreadsheet_values("sheet-id", "Invoices", [["a"]])

    sheets_service.values.batchClear.assert_not_called()


def test_failed_clear_raises(sheets_service):
    sheets_service.values.batchClear.return_value.execute.side_effect = RuntimeError("network")

    with pytest.raises(RuntimeError, match="network"):
        client.set_spreadsheet_values("sheet-id", "Invoices", [["a"]])


def test_requests_are_retried(sheets_service):
    client.set_spreadsheet_values("sheet-id", "Invoices", [["a"]])

    sheets_service.values.batchUpdate.return_value.execute.assert_called_once_with(num_retries=client.NUM_RETRIES)
    sheets_service.values.batchClear.return_value.execute.assert_called_once_with(num_retries=client.NUM_RETRIES)


# --- update_values / ensure_sheet_exists

def test_update_values_writes_only_given_cells(sheets_service):
    client.update_values("sheet-id", "Sync Status", "A2:B3", [["x", "y"]])

    kwargs = sheets_service.values.update.call_args.kwargs
    assert kwargs["range"] == "'Sync Status'!A2:B3"
    assert kwargs["body"] == {"values": [["x", "y"]]}
    sheets_service.values.batchClear.assert_not_called()


def test_ensure_sheet_exists_does_nothing_when_present(sheets_service):
    sheets_service.spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Invoices"}}, {"properties": {"title": "Sync Status"}}]
    }

    client.ensure_sheet_exists("sheet-id", "Sync Status")

    sheets_service.spreadsheets.batchUpdate.assert_not_called()


def test_ensure_sheet_exists_creates_missing_sheet(sheets_service):
    sheets_service.spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Invoices"}}]
    }

    client.ensure_sheet_exists("sheet-id", "Sync Status")

    body = sheets_service.spreadsheets.batchUpdate.call_args.kwargs["body"]
    assert body == {"requests": [{"addSheet": {"properties": {"title": "Sync Status"}}}]}
