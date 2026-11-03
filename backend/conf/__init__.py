import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import QATOOLS_ROOT
from config.log import LogUtil

PATH_BACKEND_LOG_DIR = os.path.abspath(os.path.join(QATOOLS_ROOT, "backend", "logs"))
logger = LogUtil.init_logger(log_dir=PATH_BACKEND_LOG_DIR, log_name="backend.log")
