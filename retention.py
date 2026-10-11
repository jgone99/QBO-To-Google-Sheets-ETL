import datetime
import logging
import re
from pathlib import Path

def delete_expired_files(directory: Path, name_pattern: re.Pattern, retention_days: int, buffer_days: int, label: str):
    """
    Delete files in `directory` whose names start with a YYYY-MM-DD date that is at least
    (retention_days - buffer_days) days old. Files not matching `name_pattern` are left alone.
    `label` names the files in log messages, e.g. "log" or "backup".
    """
    # materialize the listing so it can be iterated more than once
    files = list(directory.iterdir())
    dated_files = [file for file in files if file.is_file() and name_pattern.match(file.name)]

    if len(dated_files) != len(files):
        logging.warning(f"{label.capitalize()} count ({len(dated_files)}) does not match total file count ({len(files)}) in {directory.name} directory")

    today = datetime.date.today()
    expired = [file for file in dated_files if (today - datetime.date.fromisoformat(file.name[:10])).days >= retention_days - buffer_days]

    logging.info(f"Found {len(expired)} {label}s close to exceeding the ({retention_days}) day data retention limit...")

    for file in expired:
        file.unlink()

    logging.info(f"Deleted {len(expired)} {label}s")
