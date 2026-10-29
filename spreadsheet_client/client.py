import logging
from urllib.parse import quote
from spreadsheet_client.auth import get_session

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
LAST_COLUMN = "Z"
REQUEST_TIMEOUT_SECONDS = 30

class SheetsAPIError(Exception):
    pass

def as_text(value):
    """
    Mark a value to be stored as plain text, so USER_ENTERED doesn't convert it
    (e.g. "00451" -> 451). The leading apostrophe is not shown in the cell.
    """
    if value is None or value == "":
        return value
    return f"'{value}"


def ensure_sheet_exists(spreadsheet_id: str, sheet_name: str):
    spreadsheet = _request("GET", spreadsheet_id, params={"fields": "sheets.properties.title"})

    titles = [sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])]
    if sheet_name in titles:
        return

    _request("POST", f"{spreadsheet_id}:batchUpdate",
             json={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]})

    logging.info(f"Created sheet '{sheet_name}'")


def update_values(spreadsheet_id: str, sheet_name: str, cells: str, values: list[list]):
    """
    Write values to specific cells (e.g. "A1:B3"), leaving the rest of the sheet untouched.
    """
    return _request("PUT", f"{spreadsheet_id}/values/{_path_range(sheet_name, cells)}",
                    params={"valueInputOption": "USER_ENTERED"}, json={"values": values})


def get_spreadsheet_values(spreadsheet_id: str, sheet_name: str):
    return _request("GET", f"{spreadsheet_id}/values/{_path_range(sheet_name, f'A:{LAST_COLUMN}')}")


def set_spreadsheet_values(spreadsheet_id: str, sheet_name: str, values: list[list[str]]):
    """
    Overwrite a sheet without ever leaving it empty: write the new block
    starting at A1, then clear everything outside of it.
    """
    # Sheets skips None cells (leaving the old value in place), so every cell is
    # written as a value or "" and every row is padded to the same width. This way
    # each cell inside the new block is overwritten, including ones that are now blank
    width = max((len(row) for row in values), default=0)
    padded_values = [
        ["" if cell is None else cell for cell in row] + [""] * (width - len(row))
        for row in values
    ]

    body = {
        "valueInputOption": "USER_ENTERED",
        "data": [
            {
                "range": _range(sheet_name, "A1"),
                "values": padded_values
            }
        ]
    }

    try:
        result = _request("POST", f"{spreadsheet_id}/values:batchUpdate", json=body)

    except Exception:
        logging.error(f"Write failed to spreadsheet {spreadsheet_id}. Previous data was left in place")
        raise

    logging.info(f"Wrote to spreadsheet: {result}")

    # clear leftovers from previous runs: rows below the new block and columns to its right
    row_count = len(padded_values)
    stale_ranges = [_range(sheet_name, f"A{row_count + 1}:{LAST_COLUMN}")]

    if 0 < width < _column_index(LAST_COLUMN):
        stale_ranges.append(_range(sheet_name, f"{_column_letter(width + 1)}1:{LAST_COLUMN}{row_count}"))

    try:
        _request("POST", f"{spreadsheet_id}/values:batchClear", json={"ranges": stale_ranges})

    except Exception:
        logging.error(f"New data was written, but clearing stale cells {stale_ranges} failed. Old rows may remain below row {row_count}")
        raise

    logging.info(f"Cleared stale ranges: {stale_ranges}")

    return result


def _request(method: str, path: str, **kwargs) -> dict:
    response = get_session().request(method, f"{SHEETS_API}/{path}", timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)

    if not response.ok:
        # Google puts the useful explanation in the body, e.g. "Unable to parse range"
        try:
            error = response.json().get("error", {})
            message = f"{error.get('message')} ({error.get('status')}, HTTP {response.status_code})"
        except ValueError:
            message = f"HTTP {response.status_code}"
        raise SheetsAPIError(f"Sheets API {method} request failed: {message}")

    return response.json() if response.content else {}


def _range(sheet_name: str, cells: str) -> str:
    # quote the sheet name so names with spaces or symbols work ('Sync Status'!A1);
    # a quote inside the name is escaped by doubling it
    escaped = sheet_name.replace("'", "''")
    return f"'{escaped}'!{cells}"


def _path_range(sheet_name: str, cells: str) -> str:
    # a range in the URL path (rather than a JSON body) must be percent-encoded
    return quote(_range(sheet_name, cells), safe="")


def _column_letter(index: int) -> str:
    # 1 -> A, 26 -> Z
    return chr(ord("A") + index - 1)


def _column_index(letter: str) -> int:
    # A -> 1, Z -> 26
    return ord(letter) - ord("A") + 1
