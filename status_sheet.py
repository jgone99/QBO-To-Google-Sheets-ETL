import logging
from datetime import datetime
from spreadsheet_client.client import ensure_sheet_exists, update_values

# layout of the Sync Status sheet, so anyone looking at the spreadsheet can tell
# whether the invoice data is current:
#   A1 Last successful sync | B1 <timestamp>   (only updated when a sync succeeds)
#   A2 Last run             | B2 <timestamp>
#   A3 Last run result      | B3 OK / FAILED + details

SHEET_NAME = "Sync Status"

def record_success(spreadsheet_id: str, details: str):
    now = _now()
    _write(spreadsheet_id, "A1:B3", [
        ["Last successful sync", now],
        ["Last run", now],
        ["Last run result", f"OK - {details}"],
    ])

def record_failure(spreadsheet_id: str, details: str):
    # leaves "Last successful sync" alone so it shows how stale the data is
    _write(spreadsheet_id, "A2:B3", [
        ["Last run", _now()],
        ["Last run result", f"FAILED - {details}"],
    ])

def _write(spreadsheet_id: str, cells: str, values: list[list]):
    # the status sheet is a convenience: a problem updating it is logged, never raised,
    # so it can't fail a sync or hide the original error
    try:
        ensure_sheet_exists(spreadsheet_id, SHEET_NAME)
        update_values(spreadsheet_id, SHEET_NAME, cells, values)
    except Exception:
        logging.exception(f"Could not update the {SHEET_NAME} sheet")

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
