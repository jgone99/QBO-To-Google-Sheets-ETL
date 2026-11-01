from qbo_client import auth as qbo_auth
from qbo_client.invoices import get_all_invoices_since
from spreadsheet_client import auth as sheets_auth
from spreadsheet_client.client import set_spreadsheet_values
from aws_client.credentials import AwsCredentials
from aws_client.secrets import JsonSecret
from logger import setup_logging
import backup
import config
import invoice_sheet
import status_sheet
import logging
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

def handler(event, context):
    """
    Lambda entry point, run daily by EventBridge Scheduler.
    Raises when the run fails, so Lambda counts it as an error and the alarm fires.
    """
    setup_logging()

    # Lambda can reuse this process from yesterday's run, so reset the credentials per run
    qbo_auth.use_store(JsonSecret(config.QBO_SECRET_ID))
    # the Google secret holds a service account key or a federation config; federation
    # signs in with the AWS credentials (the function's role, or `aws login` locally)
    sheets_auth.use_store(JsonSecret(config.GOOGLE_SECRET_ID), aws_credentials=AwsCredentials())

    spreadsheet_id = config.SPREADSHEET_ID

    try:
        config.validate()
        main(spreadsheet_id)
    except Exception as e:
        logging.exception("Run failed")
        # without a spreadsheet id there is nowhere to record the failure; the log has it
        if spreadsheet_id:
            status_sheet.record_failure(spreadsheet_id, f"{type(e).__name__}: {e}")
        raise

    return {"status": "succeeded"}

if __name__ == "__main__":
    # local run, using the AWS profile from .env for Secrets Manager, S3 and Google federation
    try:
        handler({}, None)
    except Exception:
        sys.exit(1)
