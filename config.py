import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Lambda sets this variable on every function, so it tells the two environments apart
ON_LAMBDA = "AWS_LAMBDA_FUNCTION_NAME" in os.environ

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"

# local runs read settings from .env. On Lambda they come from the function's
# environment variables, and python-dotenv isn't part of the deployment package
if not ON_LAMBDA:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)

AWS_REGION = os.getenv("AWS_REGION", "us-east-2")

# Secrets Manager secrets: the QBO credentials with the rotating refresh token, and the
# Google service account key
QBO_SECRET_ID = os.getenv("QBO_SECRET_ID")
GOOGLE_SECRET_ID = os.getenv("GOOGLE_SECRET_ID")

# private S3 bucket holding the sheet backups. A lifecycle rule on the bucket deletes
# them after the retention period (set in template.yaml)
BACKUP_BUCKET = os.getenv("BACKUP_BUCKET")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

QBO_BASE_URLS = {
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
    "production": "https://quickbooks.api.intuit.com",
}

QBO_ENVIRONMENT = os.getenv("QBO_ENVIRONMENT", "sandbox")
QBO_BASE_URL = QBO_BASE_URLS.get(QBO_ENVIRONMENT)

# must be set (in .env locally, as Lambda environment variables on AWS) for a sync to run
REQUIRED_ENV_VARS = [
    "QBO_SECRET_ID",
    "GOOGLE_SECRET_ID",
    "BACKUP_BUCKET",
    "SPREADSHEET_ID",
]

# the business's time zone. Lambda's clock is UTC, so "today" (DaysUntilDue) and the
# timestamps (Sync Status, backup names) are always worked out in this zone
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")

REQUEST_TIMEOUT_SECONDS = 30

# invoices with a TxnDate on or after this date are synced to the sheet
START_DATE = date(2026, 10, 9)

# adds a PaymentType column from the invoice's "Payment Type" custom field
INCLUDE_PAYMENT_TYPE_COLUMN = True

def now() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))

def today() -> date:
    return now().date()

def local_aws_problems() -> list[str]:
    """
    Local runs must say which AWS CLI profile to use. Without AWS_PROFILE, boto3 silently
    falls back to the [default] credentials, and access keys in the environment are used
    ahead of any profile. Lambda gets its credentials from the function's role, so it's skipped there.
    """
    if ON_LAMBDA:
        return []

    problems = []
    if not os.getenv("AWS_PROFILE"):
        problems.append("AWS_PROFILE must be set for local runs (the qbo-sheets-etl profile)")
    if os.getenv("AWS_ACCESS_KEY_ID"):
        problems.append("AWS_ACCESS_KEY_ID is set, which boto3 uses instead of AWS_PROFILE; unset it")
    return problems

def validate():
    """
    Check that everything a sync needs is in place, so a misconfiguration fails
    immediately with a clear message. Only names are reported, never values.
    """
    problems = []

    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        problems.append(f"missing settings: {', '.join(missing)}")

    problems.extend(local_aws_problems())

    if QBO_BASE_URL is None:
        problems.append(f"QBO_ENVIRONMENT must be one of {list(QBO_BASE_URLS)}, got '{QBO_ENVIRONMENT}'")

    try:
        ZoneInfo(TIMEZONE)
    except Exception:
        problems.append(f"TIMEZONE is not a valid time zone: '{TIMEZONE}'")

    if problems:
        raise ValueError("Invalid configuration: " + "; ".join(problems))
