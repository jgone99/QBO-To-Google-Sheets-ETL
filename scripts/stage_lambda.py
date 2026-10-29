"""
Copy only the files the Lambda function needs into .aws-sam-stage/, which template.yaml
uses as the function's code. An allowlist means .env, credentials, logs and tests can never
end up in the deployment package.

Run from the project folder before `sam build`:
    .venv/Scripts/python.exe scripts/stage_lambda.py
"""
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STAGE_DIR = PROJECT_ROOT / ".aws-sam-stage"

FILES = [
    "backup.py",
    "config.py",
    "etl.py",
    "invoice_sheet.py",
    "logger.py",
    "status_sheet.py",
    "requirements.txt",
]

PACKAGES = ["aws_client", "qbo_client", "spreadsheet_client"]

def main():
    if STAGE_DIR.exists():
        shutil.rmtree(STAGE_DIR)
    STAGE_DIR.mkdir()

    for name in FILES:
        shutil.copy2(PROJECT_ROOT / name, STAGE_DIR / name)

    for name in PACKAGES:
        shutil.copytree(PROJECT_ROOT / name, STAGE_DIR / name, ignore=shutil.ignore_patterns("__pycache__"))

    print(f"Staged {len(FILES)} files and {len(PACKAGES)} packages in {STAGE_DIR}")

if __name__ == "__main__":
    main()
