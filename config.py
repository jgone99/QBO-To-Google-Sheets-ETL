import os
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

# all paths are anchored to the project folder so the ETL works no matter
# which directory it is launched from (e.g. Task Scheduler)
PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"
CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"
LOGS_DIR = PROJECT_ROOT / "logs"

# logs are deleted once they are (retention - buffer) days old
MAX_LOG_RETENTION_DAYS = 30
MAX_LOG_RETENTION_BUFFER_DAYS = 1

load_dotenv(ENV_PATH)

QBO_BASE_URLS = {
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
    "production": "https://quickbooks.api.intuit.com",
}

QBO_ENVIRONMENT = os.getenv("QBO_ENVIRONMENT", "sandbox")
QBO_BASE_URL = QBO_BASE_URLS.get(QBO_ENVIRONMENT)

# must be set in .env for a sync to run
REQUIRED_ENV_VARS = [
    "QBO_CLIENT_ID",
    "QBO_CLIENT_SECRET",
    "QBO_REDIRECT_URI",
    "QBO_REFRESH_TOKEN",
    "QBO_REALM_ID",
    "SPREADSHEET_ID",
]

REQUEST_TIMEOUT_SECONDS = 30

# invoices with a TxnDate on or after this date are synced to the sheet
START_DATE = date(2026, 7, 1)

# adds a PaymentType column from the invoice's "Payment Type" custom field
INCLUDE_PAYMENT_TYPE_COLUMN = True

def validate():
    """
    Check that everything a sync needs is in place, so a misconfiguration fails
    immediately with a clear message. Only names are reported, never values.
    """
    problems = []

    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        problems.append(f"missing from .env: {', '.join(missing)}")

    if QBO_BASE_URL is None:
        problems.append(f"QBO_ENVIRONMENT must be one of {list(QBO_BASE_URLS)}, got '{QBO_ENVIRONMENT}'")

    if not CREDENTIALS_PATH.is_file():
        problems.append(f"Google credentials file not found: {CREDENTIALS_PATH}")

    if problems:
        raise ValueError("Invalid configuration: " + "; ".join(problems))
