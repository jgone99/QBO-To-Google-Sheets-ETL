from qbo_client.auth import get_access_token, get_realm_id
from qbo_client.client import query, QBOAPIError
import config
from datetime import date
import logging

# required for QBO to return custom fields like "Customer PO" on invoices
INVOICE_QUERY_PARAMS = {'include': 'enhancedAllCustomFields'}

# custom field "Type" -> key that holds its value
CUSTOM_FIELD_VALUE_KEYS = {
    'StringType': 'StringValue',
    'NumberType': 'NumberValue',
    'DateType': 'DateValue',
}

# values of the "Payment Type" custom field -> label shown in the sheet
PAYMENT_TYPE_LABELS = {
    '1': 'Check',
    '2': 'CC',
}

def get_all_invoices_since(date_str: str) -> list[dict]:
    realm_id = get_realm_id()
    access_token = get_access_token()

    where_clause = f"WHERE TxnDate >= '{date_str}'"

    invoice_count = query(realm_id, access_token, f"SELECT COUNT(*) FROM Invoice {where_clause}")['QueryResponse']['totalCount']

    raw_invoices = []
    start_position = 1

    while True:
        query_string = f"SELECT * FROM Invoice {where_clause} " \
        "ORDERBY MetaData.CreateTime " \
        f"STARTPOSITION {start_position} MAXRESULTS 1000"

        response = query(realm_id, access_token, query_string, INVOICE_QUERY_PARAMS)

        raw_invoices_n = response['QueryResponse'].get('Invoice', [])

        if len(raw_invoices_n) == 0:
            break

        raw_invoices += raw_invoices_n
        start_position += len(raw_invoices_n)

    # fewer than counted means pages were missed: stop rather than overwrite the sheet
    # with partial data. More than counted just means invoices were created mid-fetch
    if len(raw_invoices) < invoice_count:
        raise QBOAPIError(f"Incomplete fetch: QBO counted {invoice_count} invoices but only {len(raw_invoices)} were returned")

    if len(raw_invoices) > invoice_count:
        logging.warning(f"Fetched {len(raw_invoices)} invoices but QBO counted {invoice_count}, likely created during the fetch")

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
        clean_invoice['DaysUntilDue'] = (date.fromisoformat(clean_invoice['DueDate']) - config.today()).days if clean_invoice['DueDate'] else None
        clean_invoice['CustomerPO'] = _get_custom_field(invoice, 'Customer PO')
        if config.INCLUDE_PAYMENT_TYPE_COLUMN:
            clean_invoice['PaymentType'] = _payment_type_label(_get_custom_field(invoice, 'Payment Type'), invoice.get('DocNumber'))
        clean_invoices.append(clean_invoice)

    return clean_invoices

def _get_custom_field(invoice: dict, name: str):
    # QBO omits the value key when the field is blank on that invoice
    for field in invoice.get('CustomField', []):
        if field.get('Name') != name:
            continue

        field_type = field.get('Type')
        value_key = CUSTOM_FIELD_VALUE_KEYS.get(field_type)

        if value_key is None:
            logging.warning(f"Unsupported type '{field_type}' for custom field '{name}' on invoice {invoice.get('DocNumber')}")
            return None

        return field.get(value_key)
    return None

def _payment_type_label(value, doc_number: str):
    # Payment Type is a StringType field, so values come back as "1", "2", ...
    if value is None or value == '':
        return None

    if value not in PAYMENT_TYPE_LABELS:
        # keep the raw value so it still shows up in the sheet and can be added to the mapping
        logging.warning(f"Unknown Payment Type '{value}' on invoice {doc_number}")
        return value

    return PAYMENT_TYPE_LABELS[value]