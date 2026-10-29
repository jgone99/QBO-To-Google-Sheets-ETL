from logger import setup_logging
if __name__ == "__main__":
    # set up logging before anything else so even import and config errors are logged.
    # only when run as a script, so importing this module (e.g. from tests) doesn't write to logs/
    setup_logging()

from qbo_client.invoices import get_all_invoices_since
from spreadsheet_client.client import set_spreadsheet_values
import backup
import config
import invoice_sheet
import status_sheet
import logging
import os
import sys

def main(spreadsheet_id: str):
    start_date = config.START_DATE.isoformat()

    invoices = get_all_invoices_since(start_date)
    logging.info(f"Fetched {len(invoices)} invoices")

    if len(invoices) == 0:
        # not a failure, but unusual enough to call out in the log and the status sheet
        logging.warning(f"No invoices found since {start_date}. Invoice sheet was not updated")
        status_sheet.record_success(spreadsheet_id, f"no invoices found since {start_date}, invoice sheet was not updated")
        return

    values = invoice_sheet.to_rows(invoices)
    logging.info("Transformed invoices to sheet rows")

    # keep a copy of what's about to be overwritten. If the backup fails this raises,
    # so the sheet is never overwritten without one
    backup.backup_sheet(spreadsheet_id, invoice_sheet.SHEET_NAME)

    set_spreadsheet_values(spreadsheet_id, invoice_sheet.SHEET_NAME, values)

    status_sheet.record_success(spreadsheet_id, f"{len(invoices)} invoices since {start_date}")
    logging.info("Run finished")

if __name__ == "__main__":
    # runs every time, alongside the log cleanup in setup_logging, so backups keep to the
    # retention limit even when the sync fails. It logs its own errors and never raises
    backup.cleanup_old_backups()

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    logging.info(f"Loaded spreadsheet id: {spreadsheet_id}")

    try:
        config.validate()
        main(spreadsheet_id)
    except Exception as e:
        logging.exception("Run failed")
        # without a spreadsheet id there is nowhere to record the failure; the log has it
        if spreadsheet_id:
            status_sheet.record_failure(spreadsheet_id, f"{type(e).__name__}: {e}")
        sys.exit(1)
