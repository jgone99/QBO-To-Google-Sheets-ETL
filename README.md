# QBO to Google Sheets ETL

Copies QuickBooks Online invoices into a Google Sheet every morning, so the sheet's other tabs can run calculations on current invoice data. Runs as an AWS Lambda function on a daily schedule.

## How it works

Each run (daily at 6:00 AM America/New_York):

1. Reads the QBO credentials and the Google sign-in (a service account key or a workload identity federation config) from Secrets Manager.
2. Fetches every invoice with a `TxnDate` on or after `START_DATE` (`config.py`), page by page, and checks the total against QBO's count. Fewer than counted stops the run, so the sheet is never replaced with partial data.
3. Cleans each invoice into one row: the standard fields, `DaysUntilDue`, and the custom fields in `CUSTOM_FIELDS` (`config.py`), such as the PO number and `PaymentType` (its codes mapped to labels like "Check").
4. Backs up the current "Invoices" tab as a CSV in S3. If the backup fails, the run stops and the sheet is left alone.
5. Writes the new rows to the "Invoices" tab starting at A1, then clears whatever is left below and to the right of them. The sheet is never empty at any point.
6. Records the outcome in the "Sync Status" tab: last successful sync, last run, and its result.

A failed run raises, which counts as a Lambda error and sends an alarm email.

## Design decisions

- **Write, then clear.** Clearing first would leave the sheet empty if the write failed. Blank values are written as `""` (not `null`, which Sheets skips), so a cell that's now empty can't keep last run's value.
- **Columns come from the invoice fields.** The header row is the keys of the cleaned invoice, in order, so adding a field in `qbo_client/invoices.py` adds a column. New fields go at the end so formulas that use column letters don't shift.
- **Text columns.** `TEXT_COLUMNS` in `invoice_sheet.py` are written with a leading apostrophe, so Sheets keeps values like `00451` as text instead of converting them to numbers.
- **Custom fields are read by their `Type`** (`StringType` → `StringValue`, etc.), with `include=enhancedAllCustomFields` on the query. An unknown type or Payment Type value is logged, not silently dropped.
- **Custom field names are settings.** `CUSTOM_FIELDS` maps each sheet column to the QBO custom field it's read from, because the same field can be named differently in another QBO company. The column names stay fixed, and every column is on every row (blank when an invoice has no value), so formulas don't shift. The `PaymentType` column's values are mapped through `PAYMENT_TYPE_LABELS`; leaving it out of `CUSTOM_FIELDS` leaves the column out. If a configured field is on no invoice in a run, one warning lists the custom field names QBO did return (names only, never values), which usually shows the right name.
- **Zero invoices is a warning, not a failure.** The sheet is left as it is and the status tab says so.
- **QBO errors carry Intuit's request ID.** A failed QBO call's error includes the `intuit_tid` response header (token refresh errors from Intuit's OAuth library already do), so it shows in the Sync Status tab and the logs and can be quoted to Intuit support.
- **No automatic retries of a failed run.** A retry would refresh the QBO token again; the next day's run picks up, or rerun by hand.
- **Credentials only in Secrets Manager.** QBO rotates the refresh token; the rotated token is saved before anything else happens, and Secrets Manager is the only copy (two copies would invalidate each other). The Google sign-in lives there too, so nothing secret is on disk or in the package.
- **Two ways to sign in to Google**, chosen by which file is seeded (its `type` field): a **service account key** (`service_account`), or **workload identity federation** (`external_account`), where the function's AWS role is exchanged for a short-lived token of the service account, so no Google key exists at all. Federation suits Google Workspace organizations, which block service account key creation by default. Either way the sheet is shared with the service account. Federation signs in with the credentials boto3 uses (the function's role on Lambda, `aws login` locally), and the config's URLs are checked to be Google's before use.
- **Retention is handled by AWS.** Backups expire through an S3 lifecycle rule and logs through the CloudWatch log group's retention, both 30 days by default (`BackupRetentionDays`, `LogRetentionDays`).
- **Business time zone.** Lambda's clock is UTC, so `DaysUntilDue`, the status timestamps and the backup names use `TIMEZONE` (America/New_York). The stack's `TimeZone` parameter sets both this and the schedule's time zone, so the run time and the dates it writes always agree.
- **Direct Sheets REST calls** through google-auth's `AuthorizedSession`, instead of google-api-python-client, which is about 100 MB of discovery documents for other APIs.

## Code structure

| Business logic (no AWS) | AWS layer |
|---|---|
| `qbo_client/`: QBO auth, queries, invoices | `aws_client/secrets.py`: Secrets Manager |
| `spreadsheet_client/`: Sheets auth and calls | `aws_client/storage.py`: S3 backups |
| `invoice_sheet.py`: the Invoices tab layout | `backup.py`: backs the sheet up to S3 |
| `status_sheet.py`: the Sync Status tab | `aws_client/credentials.py`: AWS credentials for Google federation |
| | `aws_client/session.py`: the one boto3 session every AWS client and credential comes from |
| | `aws_client/account.py`: the account ID `seed_secrets.py` shows before writing |
| | `etl.py`: the entry point (`handler`) |

`qbo_client.auth` and `spreadsheet_client.auth` get their credentials through a store the entry point passes in (`use_store(JsonSecret(...))`), and federation gets its AWS credentials the same way (`aws_credentials=AwsCredentials()`), so neither package depends on AWS.

Other files: `config.py` (settings), `logger.py` (logging), `template.yaml` (infrastructure), `scripts/` (packaging and seeding), `tests/`.

## Local development

```
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest
```

Tests use fakes for QBO, Google and AWS and never touch real services.

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
4. **Seed the secrets:** set up Google one of the two ways below and save the result as `credentials.json`, then run `.venv/Scripts/python.exe scripts/seed_secrets.py` (moves `QBO_*` from `.env` and `credentials.json` into Secrets Manager).

   **Option A: service account key.** In Google Cloud, enable the Google Sheets API, create a service account, download a JSON key as `credentials.json`, and share the spreadsheet (Editor) with the service account's email.

   **Option B: workload identity federation (no Google key).** In Cloud Shell, with `PROJECT_ID`, `PROJECT_NUMBER` (the number, not the ID) and `ACCOUNT_ID` (the 12-digit AWS account) filled in, and `ROLE_NAME` the function's role (`aws cloudformation describe-stack-resource --stack-name qbo-sheets-etl --logical-resource-id SyncFunctionRole --profile qbo-sheets-etl`):
   ```
   gcloud services enable iam.googleapis.com sts.googleapis.com iamcredentials.googleapis.com sheets.googleapis.com
   gcloud iam service-accounts create qbo-sheets-etl --display-name="QBO Sheets ETL"
   gcloud iam workload-identity-pools create aws-pool --location=global --display-name="AWS"
   gcloud iam workload-identity-pools providers create-aws aws-provider --location=global \
     --workload-identity-pool=aws-pool --account-id=ACCOUNT_ID \
     --attribute-mapping="google.subject=assertion.arn,attribute.aws_role=assertion.arn.extract('assumed-role/{role_name}/')" \
     --attribute-condition="assertion.arn.startsWith('arn:aws:sts::ACCOUNT_ID:assumed-role/')"
   gcloud iam service-accounts add-iam-policy-binding qbo-sheets-etl@PROJECT_ID.iam.gserviceaccount.com \
     --role=roles/iam.workloadIdentityUser \
     --member="principalSet://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/aws-pool/attribute.aws_role/ROLE_NAME"
   gcloud iam workload-identity-pools create-cred-config \
     projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/aws-pool/providers/aws-provider \
     --service-account=qbo-sheets-etl@PROJECT_ID.iam.gserviceaccount.com --aws --output-file=credentials.json
   ```
   Download `credentials.json` into the project folder (it holds no secret) and share the spreadsheet (Editor) with `qbo-sheets-etl@PROJECT_ID.iam.gserviceaccount.com`. For local runs, repeat the `add-iam-policy-binding` command with the role your `aws login` uses (the role name in `aws sts get-caller-identity --profile qbo-sheets-etl`); skip it to allow only the Lambda. Nothing changes on the AWS side.
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
- **Google returns 403 / permission denied:** the spreadsheet must be shared (Editor) with the service account's email. With federation, also check that the `workloadIdentityUser` binding names the function's current role: if the stack ever replaces `SyncFunctionRole`, its name changes and the binding must be updated.
- **Switch between a key and federation:** set up the other option (setup step 4), save it as `credentials.json`, run `seed_secrets.py --force`. Only the Google secret changes when `.env` has none of the QBO credentials (`QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`, `QBO_REDIRECT_URI`, `QBO_REALM_ID`, `QBO_REFRESH_TOKEN`); `QBO_SECRET_ID` and `QBO_ENVIRONMENT` are settings and stay.
- **Undo a bad secret write:** Secrets Manager console, the secret, Versions; the previous value is `AWSPREVIOUS`.
- **Change a setting** (spreadsheet, schedule, time zone, retention, QBO environment): `sam deploy --profile qbo-sheets-etl --parameter-overrides Name=value`, and the same value in `samconfig.toml`'s `parameter_overrides`, which every later `sam deploy` sends. Don't edit the function's environment variables in the Lambda console: the stack doesn't know about the change, and a later deploy can silently put the old value back. `START_DATE`, `CUSTOM_FIELDS`, `TEXT_COLUMNS` and `PAYMENT_TYPE_LABELS` are in the code: change them, then deploy a code change. A new custom field column goes at the end of `CUSTOM_FIELDS`; add it to `TEXT_COLUMNS` too if its values must stay text.
- **A custom field column is blank:** look in CloudWatch Logs for "was not found on any invoice". It lists the custom field names QBO returned; put the right one in `CUSTOM_FIELDS` and deploy.
- **Deploy a code change:** run `.venv/Scripts/python.exe -m pytest`, then `scripts/stage_lambda.py`, `sam build`, `sam deploy --profile qbo-sheets-etl`.
