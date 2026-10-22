import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import QATOOLS_ROOT
from config.log import LogUtil

PATH_4_RUNCASE_LOG_DIR = os.path.abspath(os.path.join(QATOOLS_ROOT, "4_runcase", "logs"))
logger = LogUtil.init_logger(log_dir=PATH_4_RUNCASE_LOG_DIR, log_name="runcase.log")
