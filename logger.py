import logging

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

def setup_logging():
    """
    Called at the start of every run. On Lambda, anything logged goes to CloudWatch Logs,
    which keeps it for the retention period set on the log group. Locally it prints to the console.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Lambda's Python runtime attaches its own CloudWatch handler. Only add one when
    # nothing is attached (local runs), so lines aren't printed twice
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)

    logging.info("Begin logging...")
