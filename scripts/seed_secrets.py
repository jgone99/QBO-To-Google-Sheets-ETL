"""
One-time move of the credentials into Secrets Manager:
  - the QBO_* values from .env into the QBO secret, then removed from .env
  - credentials.json (the Google service account key) into the Google secret

Afterwards Secrets Manager holds the only copy of the QBO refresh token: two live copies
would invalidate each other the next time either one is refreshed. Delete credentials.json
yourself once a run has worked.

Also used to load a fresh refresh token (e.g. production keys from the Intuit OAuth
Playground): put the new QBO_* values in .env and run with --force.

Run from the project folder, signed in with `aws login`:
    .venv/Scripts/python.exe scripts/seed_secrets.py
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import dotenv_values, unset_key
from aws_client.account import get_account_id
from aws_client.secrets import get_json_secret, put_json_secret
from qbo_client.auth import SECRET_KEYS
import config

CREDENTIALS_PATH = config.PROJECT_ROOT / "credentials.json"

def seed_qbo(force: bool):
    env_values = dotenv_values(config.ENV_PATH)
    missing = [key for key in SECRET_KEYS if not env_values.get(key)]
    if missing:
        print(f"QBO: skipped, missing from .env: {', '.join(missing)}")
        return

    current = get_json_secret(config.QBO_SECRET_ID)
    if current.get("QBO_REFRESH_TOKEN") and not force:
        sys.exit("QBO: the secret already holds a refresh token, which may be newer than the one in .env "
                 "(it rotates on every run). Rerun with --force only if .env has a freshly issued token.")

    put_json_secret(config.QBO_SECRET_ID, {key: env_values[key] for key in SECRET_KEYS})
    print(f"QBO: saved {', '.join(SECRET_KEYS)} to {config.QBO_SECRET_ID}")

    for key in SECRET_KEYS:
        unset_key(config.ENV_PATH, key)
    print("QBO: removed them from .env")

def seed_google(force: bool):
    if not CREDENTIALS_PATH.is_file():
        print("Google: skipped, credentials.json not found")
        return

    key = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    if key.get("type") != "service_account":
        sys.exit("Google: credentials.json is not a service account key")

    current = get_json_secret(config.GOOGLE_SECRET_ID)
    if current.get("type") == "service_account" and not force:
        print("Google: skipped, the secret already holds a service account key (use --force to replace it)")
        return

    put_json_secret(config.GOOGLE_SECRET_ID, key)
    print(f"Google: saved the service account key ({key.get('client_email')}) to {config.GOOGLE_SECRET_ID}")
    print("Google: delete credentials.json once a run has worked")

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="replace secrets that already hold credentials")
    args = parser.parse_args()

    missing = [name for name in ("QBO_SECRET_ID", "GOOGLE_SECRET_ID") if not getattr(config, name)]
    if missing:
        sys.exit(f"Set {', '.join(missing)} in .env (qbo-sheets-etl/qbo and qbo-sheets-etl/google)")

    problems = config.local_aws_problems()
    if problems:
        sys.exit("; ".join(problems))

    # last check before writing credentials: the account they're about to go to
    print(f"AWS profile {os.environ['AWS_PROFILE']}, account {get_account_id()}, region {config.AWS_REGION}")
    print(f"Secrets: {config.QBO_SECRET_ID}, {config.GOOGLE_SECRET_ID}")
    if input("Write the credentials to this account? [y/N] ").strip().lower() != "y":
        sys.exit("Cancelled, nothing was written")

    seed_qbo(args.force)
    seed_google(args.force)

if __name__ == "__main__":
    main()
