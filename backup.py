import csv
import io
import logging
import re
import config
from aws_client import storage
from spreadsheet_client.client import get_spreadsheet_values

# backups go in the backup bucket under this prefix, e.g. backups/2026-10-11_093000_Invoices.csv.
# The bucket's lifecycle rule (template.yaml) deletes them after the retention period
BACKUP_PREFIX = "backups/"

def backup_sheet(spreadsheet_id: str, sheet_name: str) -> str | None:
    """
    Save the sheet's current contents as a CSV in the backup bucket before it is overwritten,
    and return its key. Raises if the backup can't be made, so the caller doesn't overwrite
    without one.
    """
    values = get_spreadsheet_values(spreadsheet_id, sheet_name).get("values", [])

    if not values:
        logging.info(f"Sheet '{sheet_name}' is empty, nothing to back up")
        return None

    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(values)

    key = f"{BACKUP_PREFIX}{config.now():%Y-%m-%d_%H%M%S}_{_safe_file_name(sheet_name)}.csv"

    # utf-8-sig so Excel shows accented characters correctly when opening a downloaded backup
    storage.put_object(key, buffer.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8")

    logging.info(f"Backed up {len(values)} rows of '{sheet_name}' to {key}")

    return key

def _safe_file_name(name: str) -> str:
    # sheet names can contain characters that don't belong in a file name
    return re.sub(r"[^\w-]+", "_", name)
