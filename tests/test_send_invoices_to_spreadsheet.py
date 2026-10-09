from logger import setup_logging, delete_expired_logs
import logging
setup_logging()
from qbo_client.invoices import get_all_invoices
from spreadsheet_client.client import set_spreadsheet_values
import os
import sys
from pprint import pprint
from dotenv import load_dotenv, set_key

load_dotenv()

def transform_invoices_to_list_rows(invoices: list[dict]) -> list[list[str]]:
    return [[attr for attr in invoice.values()] for invoice in invoices]

last_updated_datetime = os.getenv("LAST_UPDATED") or '2026-07-25T10:00:00-04:00'
logging.info(f"Loaded last updated time: {last_updated_datetime}")

invoices = get_all_invoices()
logging.info(f"Fetched {len(invoices)} invoices")

if len(invoices) == 0:
    logging.warning("No invoices found. Ending run")
    sys.exit(0)

spreadsheet_id = os.getenv("SPREADSHEET_ID")
logging.info(f"Loaded spreadsheet id: {spreadsheet_id}")

invoice_rows = transform_invoices_to_list_rows(invoices)
logging.info("Transformed invoices to nested list format")

header = list(invoices[0].keys())
values = [header] + invoice_rows

result = set_spreadsheet_values(spreadsheet_id, values)

# if len(invoices) > 0:
#     last_updated_datetime = invoices[-1]['LastUpdatedTime']
#     set_key(".env", "LAST_UPDATED", last_updated_datetime)
#     logging.info(f"Set last updated time: {last_updated_datetime}")