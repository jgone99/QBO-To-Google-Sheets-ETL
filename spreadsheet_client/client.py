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
        result = service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        ).execute()

        logging.info(f"Wrote to spreadsheet: {result}")

        last_row = len(values)

        clear = service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=f"Invoices!A{last_row+1}:Z",
            body={}
        ).execute()

        logging.info(f"Cleared sheet from row {last_row+1}: {clear}")

    except Exception as error:
        logging.error(f"Spreadsheet id {spreadsheet_id} does not exist. Error: {error}")
        result = None

    return result