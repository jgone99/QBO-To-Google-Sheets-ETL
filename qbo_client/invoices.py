from qbo_client.auth import get_access_token
from qbo_client.client import query
from dotenv import load_dotenv
import os
from datetime import date, datetime
import logging

load_dotenv()

def get_open_invoices() -> list[dict]:
    realm_id = os.getenv("QBO_REALM_ID")
    access_token = get_access_token()
    query_string = "SELECT * FROM Invoice WHERE Balance > '0'"

    response = query(realm_id, access_token, query_string)

    raw_invoices = response['QueryResponse'].get('Invoice', [])

    return _clean_invoices(raw_invoices)

def get_new_and_changed_invoices(datetime: str = None) -> list[dict]:
    if not datetime:
        return []

    realm_id = os.getenv("QBO_REALM_ID")
    access_token = get_access_token()
    query_string = "SELECT * FROM Invoice " \
    f"WHERE MetaData.LastUpdatedTime > '{datetime}' " \
    "ORDER BY MetaData.LastUpdatedTime"

    response = query(realm_id, access_token, query_string)

    raw_invoices = response['QueryResponse'].get('Invoice', [])

    return _clean_invoices(raw_invoices)

def get_all_invoices_since(date_str: str) -> list[dict]:
    realm_id = os.getenv("QBO_REALM_ID")
    access_token = get_access_token()

    where_clause = f"WHERE TxnDate >= '{date_str}'"

    invoice_count = query(realm_id, access_token, f"SELECT COUNT(*) FROM Invoice {where_clause}")['QueryResponse']['totalCount']

    raw_invoices = []
    start_position = 1

    while True:
        query_string = f"SELECT * FROM Invoice {where_clause} " \
        "ORDERBY MetaData.CreateTime " \
        f"STARTPOSITION {start_position} MAXRESULTS 1000"

        response = query(realm_id, access_token, query_string)

        raw_invoices_n = response['QueryResponse'].get('Invoice', [])

        if len(raw_invoices_n) == 0:
            break

        raw_invoices += raw_invoices_n
        start_position += len(raw_invoices_n)

    if invoice_count != len(raw_invoices):
        logging.warning(f"QB page count mismatch. Total invoice count is {invoice_count} but actually fetched count is {len(raw_invoices)}")

    return _clean_invoices(raw_invoices)

def _clean_invoices(raw_invoices: list[dict]) -> list[dict]:
    clean_invoices = []

    for invoice in raw_invoices:
        clean_invoice = {
            'Id': invoice.get('Id'),
            'DocNumber': invoice.get('DocNumber'),
            'TxnDate': invoice.get('TxnDate'),
            'DueDate': invoice.get('DueDate'),
            'TotalAmt': invoice.get('TotalAmt'),
            'Balance': invoice.get('Balance'),
            'CustomerName': invoice.get('CustomerRef', {}).get('name'),
            'LastUpdatedTime': invoice.get('MetaData', {}).get('LastUpdatedTime')
        }
        clean_invoice['DaysUntilDue'] = (date.fromisoformat(clean_invoice['DueDate']) - date.today()).days if clean_invoice['DueDate'] else None
        clean_invoices.append(clean_invoice)

    return clean_invoices