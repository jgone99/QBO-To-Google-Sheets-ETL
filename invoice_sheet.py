import logging
from spreadsheet_client.client import as_text

# layout of the Invoices sheet. Columns come from the keys of the cleaned invoice
# objects (qbo_client.invoices._clean_invoices), in that order, so adding or removing
# a field there adds or removes the column here automatically

SHEET_NAME = "Invoices"

# columns stored as plain text instead of letting Sheets convert them (e.g. "00451" -> 451)
TEXT_COLUMNS = {"CustomerPO", "DocNumber", "CustomerName"}

def to_rows(invoices: list[dict]) -> list[list]:
    """
    Convert cleaned invoices into sheet rows, header first.
    """
    if not invoices:
        return []

    header = list(invoices[0].keys())

    missing = TEXT_COLUMNS - set(header)
    if missing:
        logging.warning(f"Text columns {missing} are not in the invoice fields and will be ignored")

    rows = [
        [as_text(invoice.get(key)) if key in TEXT_COLUMNS else invoice.get(key) for key in header]
        for invoice in invoices
    ]

    return [header] + rows
