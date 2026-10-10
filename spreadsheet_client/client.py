import logging
from spreadsheet_client.auth import get_service_account

def get_spreadsheet_values(spreadsheet_id: str):
    service = get_service_account()

    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range="Invoices!A:Z"
    ).execute()

    return result


def set_spreadsheet_values(spreadsheet_id: str, values: list[list[str]]):
    service = get_service_account()

    data = [
        {
            "range": "Invoices!A:Z",
            "values": values    
        }
    ]

    body = {
        "valueInputOption": "USER_ENTERED",
        "data": data
    }

    try:
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=f"Invoices!A:Z",
            body={}
        ).execute()

    except Exception:
        logging.error(f"Clear failed for spreadsheet {spreadsheet_id}")
        raise
        
    logging.info(f"Cleared sheet")
    
    try:
        result = service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        ).execute()

    except Exception:
        logging.error(f"Write failed to spreadsheet {spreadsheet_id}. Sheet is now EMPTY")
        raise
    
    logging.info(f"Wrote to spreadsheet: {result}")
    
    return result