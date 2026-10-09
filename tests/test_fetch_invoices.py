from logger import setup_logging
setup_logging()

from qbo_client.invoices import get_new_and_changed_invoices
from pprint import pprint
from datetime import date, datetime

invoices = get_new_and_changed_invoices(datetime.fromisoformat("2026-07-25T10:00:00-04:00"))

pprint(invoices)