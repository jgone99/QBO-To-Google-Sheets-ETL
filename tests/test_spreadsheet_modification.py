from logger import setup_logging
setup_logging()

import os
from spreadsheet_client.client import get_spreadsheet_values, set_spreadsheet_values
from dotenv import load_dotenv
load_dotenv()

spreadsheet_id = os.getenv("SPREADSHEET_ID")

values = set_spreadsheet_values(spreadsheet_id, [["YOOOOOOOOOOOOOOOOOOO"]])