import logging
import datetime
import re
import sys
from config import LOGS_DIR, MAX_LOG_RETENTION_DAYS, MAX_LOG_RETENTION_BUFFER_DAYS
from retention import delete_expired_files

LOG_NAME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.log$")

def cleanup_old_logs():
    delete_expired_files(LOGS_DIR, LOG_NAME_PATTERN, MAX_LOG_RETENTION_DAYS, MAX_LOG_RETENTION_BUFFER_DAYS, "log")

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

def _log_uncaught_exception(exc_type, exc_value, exc_traceback):
    logging.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    sys.__excepthook__(exc_type, exc_value, exc_traceback)
