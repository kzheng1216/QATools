# backend/controllers/__init__.py
import os
import sys

from fastapi import APIRouter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import QATOOLS_ROOT
from config.log import LogUtil

PATH_BACKEND_LOG_DIR = os.path.abspath(os.path.join(QATOOLS_ROOT, "backend", "logs"))
logger = LogUtil.init_logger(log_dir=PATH_BACKEND_LOG_DIR, log_name="backend.log")


# 4_runcase on sys.path so `common` imports as a package. (runcase_controller
# further registers common submodules under their bare names for legacy imports.)
PATH_RUNCASE_DIR = os.path.join(QATOOLS_ROOT, "4_runcase")
for _p in (QATOOLS_ROOT, PATH_RUNCASE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


from . import (
    agent_controller,
    analyze_history_controller,
    branch_controller,
    cmd_controller,
    config_controller,
    device_controller,
    file_transfer_controller,
    profile_controller,
    reference_controller,
    roku_test_controller,
    runcase_controller,
    session_controller,
    skill_controller,
    testrail_controller,
    user_controller,
)

api_router = APIRouter()

api_router.include_router(
    device_controller.router, prefix="", tags=["Device Controller"]
)
api_router.include_router(
    profile_controller.router, prefix="", tags=["Profile Controller"]
)
api_router.include_router(
    runcase_controller.router, prefix="", tags=["Run Case Controller"]
)
api_router.include_router(
    roku_test_controller.router, prefix="", tags=["Roku Test Controller"]
)
api_router.include_router(
    branch_controller.router, prefix="", tags=["Branch Controller"]
)
api_router.include_router(user_controller.router, prefix="", tags=["User Controller"])
api_router.include_router(
    testrail_controller.router, prefix="", tags=["Testrail Controller"]
)
api_router.include_router(agent_controller.router, prefix="", tags=["Agent Controller"])
api_router.include_router(skill_controller.router, prefix="", tags=["Skill Controller"])
api_router.include_router(
    session_controller.router, prefix="", tags=["Session Controller"]
)
api_router.include_router(
    reference_controller.router, prefix="", tags=["Reference Controller"]
)
api_router.include_router(
    config_controller.router, prefix="", tags=["Config Controller"]
)
api_router.include_router(
    analyze_history_controller.router, prefix="", tags=["Analyze History Controller"]
)
api_router.include_router(
    file_transfer_controller.router, prefix="", tags=["File Transfer Controller"]
)
api_router.include_router(cmd_controller.router, prefix="", tags=["Cmd Controller"])
