import logging
from spreadsheet_client.auth import get_service_account

LAST_COLUMN = "Z"
NUM_RETRIES = 3

def as_text(value):
    """
    Mark a value to be stored as plain text, so USER_ENTERED doesn't convert it
    (e.g. "00451" -> 451). The leading apostrophe is not shown in the cell.
    """
    if value is None or value == "":
        return value
    return f"'{value}"


def ensure_sheet_exists(spreadsheet_id: str, sheet_name: str):
    service = get_service_account()

    spreadsheet = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets.properties.title"
    ).execute(num_retries=NUM_RETRIES)

    titles = [sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])]
    if sheet_name in titles:
        return

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
    ).execute(num_retries=NUM_RETRIES)

    logging.info(f"Created sheet '{sheet_name}'")


def update_values(spreadsheet_id: str, sheet_name: str, cells: str, values: list[list]):
    """
    Write values to specific cells (e.g. "A1:B3"), leaving the rest of the sheet untouched.
    """
    service = get_service_account()

    return service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=_range(sheet_name, cells),
        valueInputOption="USER_ENTERED",
        body={"values": values}
    ).execute(num_retries=NUM_RETRIES)


def get_spreadsheet_values(spreadsheet_id: str, sheet_name: str):
    service = get_service_account()

    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=_range(sheet_name, f"A:{LAST_COLUMN}")
    ).execute(num_retries=NUM_RETRIES)

    return result


def set_spreadsheet_values(spreadsheet_id: str, sheet_name: str, values: list[list[str]]):
    """
    Overwrite a sheet without ever leaving it empty: write the new block
    starting at A1, then clear everything outside of it.
    """
    service = get_service_account()

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
        result = service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        ).execute(num_retries=NUM_RETRIES)

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
        service.spreadsheets().values().batchClear(
            spreadsheetId=spreadsheet_id,
            body={"ranges": stale_ranges}
        ).execute(num_retries=NUM_RETRIES)

    except Exception:
        logging.error(f"New data was written, but clearing stale cells {stale_ranges} failed. Old rows may remain below row {row_count}")
        raise

    logging.info(f"Cleared stale ranges: {stale_ranges}")

    return result


def _range(sheet_name: str, cells: str) -> str:
    # quote the sheet name so names with spaces or symbols work ('Sync Status'!A1);
    # a quote inside the name is escaped by doubling it
    escaped = sheet_name.replace("'", "''")
    return f"'{escaped}'!{cells}"


def _column_letter(index: int) -> str:
    # 1 -> A, 26 -> Z
    return chr(ord("A") + index - 1)


def _column_index(letter: str) -> int:
    # A -> 1, Z -> 26
    return ord(letter) - ord("A") + 1
