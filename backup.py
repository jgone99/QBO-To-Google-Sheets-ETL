import csv
import logging
import re
from datetime import datetime
from pathlib import Path
from config import BACKUPS_DIR, MAX_BACKUP_RETENTION_DAYS, MAX_BACKUP_RETENTION_BUFFER_DAYS
from retention import delete_expired_files
from spreadsheet_client.client import get_spreadsheet_values

# e.g. 2026-10-11_093000_Invoices.csv
BACKUP_NAME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}_.+\.csv$")

def backup_sheet(spreadsheet_id: str, sheet_name: str) -> Path | None:
    """
    Save the sheet's current contents to a CSV in backups/ before it is overwritten.
    Raises if the backup can't be made, so the caller doesn't overwrite without one.
    """
    values = get_spreadsheet_values(spreadsheet_id, sheet_name).get("values", [])

    if not values:
        logging.info(f"Sheet '{sheet_name}' is empty, nothing to back up")
        return None

    BACKUPS_DIR.mkdir(exist_ok=True)
    path = BACKUPS_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}_{_safe_file_name(sheet_name)}.csv"

    # utf-8-sig so Excel shows accented characters correctly when opening the file
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        csv.writer(file).writerows(values)

    logging.info(f"Backed up {len(values)} rows of '{sheet_name}' to {path.name}")

    return path

def cleanup_old_backups():
    # housekeeping must never stop a sync from running
    try:
        if BACKUPS_DIR.exists():
            delete_expired_files(BACKUPS_DIR, BACKUP_NAME_PATTERN, MAX_BACKUP_RETENTION_DAYS, MAX_BACKUP_RETENTION_BUFFER_DAYS, "backup")
    except Exception:
        logging.exception("Backup cleanup failed")

def _safe_file_name(name: str) -> str:
    # sheet names can contain characters that aren't allowed in file names
    return re.sub(r"[^\w-]+", "_", name)
