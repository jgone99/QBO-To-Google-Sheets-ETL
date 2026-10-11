import logging
import datetime
import re
import sys
from pathlib import Path
from config import LOGS_DIR, MAX_LOG_RETENTION_DAYS, MAX_LOG_RETENTION_BUFFER_DAYS

LOG_NAME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.log$")

def cleanup_old_logs():
    # materialize the listing so it can be iterated more than once
    log_files = list(LOGS_DIR.iterdir())
    dated_logs = [log for log in log_files if log.is_file() and LOG_NAME_PATTERN.match(log.name)]

    if len(dated_logs) != len(log_files):
        logging.warning(f"Log count ({len(dated_logs)}) does not match total file count ({len(log_files)}) in Logs directory")

    today = datetime.date.today()
    expired_logs = [log for log in dated_logs if (today - datetime.date.fromisoformat(log.stem)).days >= MAX_LOG_RETENTION_DAYS - MAX_LOG_RETENTION_BUFFER_DAYS]

    logging.info(f"Found {len(expired_logs)} logs close to exceeding the ({MAX_LOG_RETENTION_DAYS}) day data retention limit...")

    delete_expired_logs(expired_logs)

def setup_logging():
    LOGS_DIR.mkdir(exist_ok=True)

    timestamp = datetime.date.today().strftime("%Y-%m-%d")
    log_path = LOGS_DIR / f"{timestamp}.log"

    logging.basicConfig(
        filename=log_path,
        encoding="utf-8",
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

    # send any crash that isn't caught elsewhere (e.g. a failed import) to the log
    # instead of only the console, which nobody sees when run from Task Scheduler
    sys.excepthook = _log_uncaught_exception

    logging.info("Begin logging...")

    # log housekeeping must never stop a sync from running
    try:
        cleanup_old_logs()
    except Exception:
        logging.exception("Log cleanup failed")

def delete_expired_logs(logs: list[Path]):
    for log in logs:
        log.unlink()
    logging.info(f"Deleted {len(logs)} logs")

def _log_uncaught_exception(exc_type, exc_value, exc_traceback):
    logging.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    sys.__excepthook__(exc_type, exc_value, exc_traceback)
