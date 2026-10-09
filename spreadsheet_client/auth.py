from googleapiclient.discovery import build
from google.oauth2 import service_account
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_service = None

def get_service_account():
        global _service
        if _service is None:
            cred_path = Path("credentials.json")
            creds = service_account.Credentials.from_service_account_file(cred_path, scopes=SCOPES)
            _service = build("sheets", "v4", credentials=creds)

        return _service
