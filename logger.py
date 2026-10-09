import logging
import datetime
import re
from pathlib import Path

MAX_LOG_RETENTION_DAYS = 30
MAX_LOG_RETENTION_BUFFER_DAYS = 1

def cleanup_old_logs():
    logs_dir = Path("logs")
    logs_files = logs_dir.iterdir()

    file_count = sum(1 for _ in logs_files)
    log_count = sum(1 for log in logs_files if log.match(re.compile(r"^\d{4}-\d{2}-\d{2}.log$"))) 

    if file_count != log_count:
        logging.warning(f"Log count ({log_count}) does not match total file count ({file_count}) in Logs directory")

    expired_logs = [log for log in logs_files if (datetime.datetime.today().date() - datetime.date.fromisoformat(log.name[:-4])).days >= MAX_LOG_RETENTION_DAYS - MAX_LOG_RETENTION_BUFFER_DAYS]

    logging.info(f"Found {len(expired_logs)} logs close to exceeding the ({MAX_LOG_RETENTION_DAYS}) day data retention limit...")

    delete_expired_logs(expired_logs)

def setup_logging():
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    timestamp = datetime.datetime.today().date().strftime("%Y-%m-%d")
    log_path = logs_dir / f"{timestamp}.log"

    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

    logging.info("Begin logging...")
    cleanup_old_logs()
    
def delete_expired_logs(logs: list[Path]):
    for log in logs:
        log.unlink()
    logging.info(f"Deleted {len(logs)} logs")
