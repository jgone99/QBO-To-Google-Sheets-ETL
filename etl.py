from qbo_client import auth as qbo_auth
from qbo_client.invoices import get_all_invoices_since
from spreadsheet_client import auth as sheets_auth
from spreadsheet_client.client import set_spreadsheet_values
from aws_client.credentials import AwsCredentials
from aws_client.functions import start_background_run
from aws_client.secrets import JsonSecret
from logger import setup_logging
import backup
import config
import invoice_sheet
import status_sheet
import sync_request
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
    Lambda entry point. Called three ways:
      - daily by EventBridge Scheduler (event {}), or from the console's Test button
      - by the sheet's "Sync now" button, through the function URL: checked, then the sync
        is started as a background run and the button gets its answer straight away
      - as that background run (event {"requested_by": email})
    Raises when a sync fails, so Lambda counts it as an error and the alarm fires.
    """
    setup_logging()

    if sync_request.is_url_request(event):
        return _start_requested_sync(event, context)

    if isinstance(event, dict) and event.get("requested_by"):
        logging.info(f"Sync requested by {event['requested_by']}")

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

def _start_requested_sync(event, context):
    # a refused request is an answer, not a function error, so it never fires the alarm
    try:
        email = sync_request.authorize(event)
    except sync_request.Rejected as e:
        logging.warning(f"Sync request refused ({e.status}): {e.message}")
        return _url_response(e.status, e.message)

    # the sync can take longer than the button should wait, so it runs as a separate
    # invocation of this function. If starting it fails this raises, which the alarm reports
    start_background_run(context.invoked_function_arn, {"requested_by": email})
    logging.info(f"Sync requested by {email}, started in the background")

    return _url_response(202, "Sync started")

def _url_response(status: int, message: str) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "text/plain"}, "body": message}

if __name__ == "__main__":
    # local run, using the AWS profile from .env for Secrets Manager, S3 and Google federation
    try:
        handler({}, None)
    except Exception:
        sys.exit(1)
