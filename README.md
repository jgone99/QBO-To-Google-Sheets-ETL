# QBO to Google Sheets ETL

Copies QuickBooks Online invoices into a Google Sheet every morning, so the sheet's other tabs can run calculations on current invoice data. Runs as an AWS Lambda function on a daily schedule.

## How it works

Each run (daily at 6:00 AM America/New_York):

1. Reads the QBO and Google credentials from Secrets Manager.
2. Fetches every invoice with a `TxnDate` on or after `START_DATE` (`config.py`), page by page, and checks the total against QBO's count. Fewer than counted stops the run, so the sheet is never replaced with partial data.
3. Cleans each invoice into one row: the standard fields, `DaysUntilDue`, the `Customer PO` custom field and, when `INCLUDE_PAYMENT_TYPE_COLUMN` is on, `PaymentType` (mapped from the "Payment Type" custom field).
4. Backs up the current "Invoices" tab as a CSV in S3. If the backup fails, the run stops and the sheet is left alone.
5. Writes the new rows to the "Invoices" tab starting at A1, then clears whatever is left below and to the right of them. The sheet is never empty at any point.
6. Records the outcome in the "Sync Status" tab: last successful sync, last run, and its result.

A failed run raises, which counts as a Lambda error and sends an alarm email.

## Design decisions

- **Write, then clear.** Clearing first would leave the sheet empty if the write failed. Blank values are written as `""` (not `null`, which Sheets skips), so a cell that's now empty can't keep last run's value.
- **Columns come from the invoice fields.** The header row is the keys of the cleaned invoice, in order, so adding a field in `qbo_client/invoices.py` adds a column. New fields go at the end so formulas that use column letters don't shift.
- **Text columns.** `TEXT_COLUMNS` in `invoice_sheet.py` are written with a leading apostrophe, so Sheets keeps values like `00451` as text instead of converting them to numbers.
- **Custom fields are read by their `Type`** (`StringType` → `StringValue`, etc.), with `include=enhancedAllCustomFields` on the query. An unknown type or Payment Type value is logged, not silently dropped.
- **Zero invoices is a warning, not a failure.** The sheet is left as it is and the status tab says so.
- **No automatic retries of a failed run.** A retry would refresh the QBO token again; the next day's run picks up, or rerun by hand.
- **Credentials only in Secrets Manager.** QBO rotates the refresh token; the rotated token is saved before anything else happens, and Secrets Manager is the only copy (two copies would invalidate each other). The Google service account key lives there too, so nothing secret is on disk or in the package.
- **Retention is handled by AWS.** Backups expire through an S3 lifecycle rule and logs through the CloudWatch log group's retention, both 30 days by default (`BackupRetentionDays`, `LogRetentionDays`).
- **Business time zone.** Lambda's clock is UTC, so `DaysUntilDue`, the status timestamps and the backup names use `TIMEZONE` (America/New_York).
- **Direct Sheets REST calls** through google-auth's `AuthorizedSession`, instead of google-api-python-client, which is about 100 MB of discovery documents for other APIs.

## Code structure

| Business logic (no AWS) | AWS layer |
|---|---|
| `qbo_client/`: QBO auth, queries, invoices | `aws_client/secrets.py`: Secrets Manager |
| `spreadsheet_client/`: Sheets auth and calls | `aws_client/storage.py`: S3 backups |
| `invoice_sheet.py`: the Invoices tab layout | `backup.py`: backs the sheet up to S3 |
| `status_sheet.py`: the Sync Status tab | `etl.py`: the entry point (`handler`) |

`qbo_client.auth` and `spreadsheet_client.auth` get their credentials through a store the entry point passes in (`use_store(JsonSecret(...))`), so neither package depends on AWS.

Other files: `config.py` (settings), `logger.py` (logging), `template.yaml` (infrastructure), `scripts/` (packaging and seeding), `tests/`.

## Local development

```
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest
```

Tests use fakes for QBO, Google, Secrets Manager and S3 and never touch real services.

To run against real AWS: copy `.env.example` to `.env` and fill it in, run `aws login --profile qbo-sheets-etl`, then `.venv/Scripts/python.exe etl.py`. This writes the real sheet and rotates the real QBO token, exactly like a scheduled run.

Local runs and `seed_secrets.py` refuse to start unless `AWS_PROFILE` is set and `AWS_ACCESS_KEY_ID` is not. Without a profile, boto3 would fall back to the `[default]` credentials, and access keys in the environment take precedence over any profile. Before it writes anything, `seed_secrets.py` also shows the AWS account it's about to write to and asks you to confirm.

`requirements.txt` is what ships to Lambda; `requirements-dev.txt` adds local-only tools (pytest, python-dotenv for `.env`, awscrt for `aws login` credentials).

## Setup checklist

Steps that need the account owner. Everything else is in the repo. Region us-east-2, deployed with the AWS CLI and SAM CLI under its own AWS CLI profile, `qbo-sheets-etl` (`aws login --profile qbo-sheets-etl`).

1. **Python packages:** `.venv/Scripts/python.exe -m pip install -r requirements-dev.txt`, then `.venv/Scripts/python.exe -m pip uninstall -y google-api-python-client`, then run the tests.
2. **Deploy:** copy `.env.example` to `.env` and fill it in (keep the current `QBO_*` lines for step 4), then from the project folder:
   ```
   .venv/Scripts/python.exe scripts/stage_lambda.py
   sam build
   sam deploy --guided --profile qbo-sheets-etl
   ```
   Stack name `qbo-sheets-etl`, region `us-east-2`, keep `ScheduleState=DISABLED`. Afterwards, put the `BackupBucketName` output in `.env` as `BACKUP_BUCKET`.
3. **Confirm the alarm subscription** email from AWS Notifications.
4. **Seed the secrets:** `.venv/Scripts/python.exe scripts/seed_secrets.py` (moves `QBO_*` from `.env` and `credentials.json` into Secrets Manager).
5. **Test locally:** `.venv/Scripts/python.exe etl.py`; check the console output, the Invoices and Sync Status tabs, and the new backup in the S3 bucket.
6. **Test on Lambda:** Lambda console, the function, Test, event `{}`. Check the same things, plus the CloudWatch log group `/qbo-sheets-etl/sync`.
7. **Turn on the schedule:** `sam deploy --profile qbo-sheets-etl --parameter-overrides ScheduleState=ENABLED` (other saved parameters are kept).
8. **Clean up:** delete `credentials.json`, and disable the old Windows Task Scheduler task if there is one.
9. **QBO production keys:** get an initial refresh token for the production app, put the `QBO_*` values in `.env`, run `seed_secrets.py --force`, and deploy with `QboEnvironment=production`. Change `START_DATE` if production needs a different range.

## Runbook

- **Alarm email, or "FAILED" in the Sync Status tab:** read the error in the status tab or CloudWatch Logs group `/qbo-sheets-etl/sync`, fix the cause, then rerun with the Lambda console Test button and event `{}`. A rerun is always safe: it rebuilds the whole sheet.
- **Restore the sheet from a backup:** S3 console, the backup bucket, `backups/`, download the CSV. In Google Sheets, File, Import, Upload, "Replace current sheet", and untick "Convert text to numbers, dates, and formulas" so values like `00451` keep their zeros. The next run overwrites it again, so pause the schedule first if needed.
- **Pause the daily run:** EventBridge Scheduler console, disable the schedule, or `sam deploy --profile qbo-sheets-etl --parameter-overrides ScheduleState=DISABLED`.
- **QBO says the refresh token is invalid:** re-authorize the app, put the new `QBO_*` values in `.env`, run `seed_secrets.py --force`.
- **Google returns 403 / permission denied:** the spreadsheet must be shared (Editor) with the service account's `client_email`.
- **Undo a bad secret write:** Secrets Manager console, the secret, Versions; the previous value is `AWSPREVIOUS`.
- **Change a setting** (schedule, retention, QBO environment): `sam deploy --profile qbo-sheets-etl --parameter-overrides Name=value`. `START_DATE`, `TEXT_COLUMNS`, `INCLUDE_PAYMENT_TYPE_COLUMN` and `PAYMENT_TYPE_LABELS` are in the code: change them, then deploy a code change.
- **Deploy a code change:** run `.venv/Scripts/python.exe -m pytest`, then `scripts/stage_lambda.py`, `sam build`, `sam deploy --profile qbo-sheets-etl`.
