import json
import os
import sys

from config.device_conf.device_info import DeviceInfo, PlanId

from .launch_qahub_testcase import Config, TestCategory
from .task_handle import QAHubTask, TaskExecution
from .util import ExecutionMode

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from . import logger


def _parse_config(config_data: dict) -> Config:
    """Build a Config from one task config dict (shared by new and legacy formats)."""
    return Config(
        case_type=config_data["case_type"],
        case_id=config_data["case_id"],
        device=DeviceInfo().devices[config_data["device"]],
        testrail_case_id=config_data.get("testrail_case_id", ""),
        testrail_plan_id=config_data.get("testrail_plan_id", PlanId.NO_PLAN.value),
        automation_test_branch=config_data.get("automation_test_branch", "main"),
        roku_automation_branch=config_data.get("roku_automation_branch", "main"),
        repeat=config_data.get("repeat", 0),
        test_source=config_data.get("test_source", TestCategory.SingleCase.value),
    )


def create_execution_with_profile(profile: str) -> TaskExecution:
    """Create a TaskExecution object based on the provided profile JSON file."""
    if not profile.endswith(".json"):
        profile += ".json"

    profile_path = os.path.join(os.path.dirname(__file__), "../profiles", profile)
    logger.info(f"Parsing profile from: {profile_path}")
    if not os.path.exists(profile_path):
        raise FileNotFoundError(f"Profile file not found: {profile_path}")

    with open(profile_path, "r") as f:
        profile_data = json.load(f)

    tasks = []
    for task_data in profile_data.get("tasks", []):
        # New format: each task carries a single `config` object. Fall back to the
        # first entry of the legacy `configs` list so older profile files keep working.
        if "config" in task_data:
            config_data = task_data["config"]
        else:
            legacy = task_data.get("configs", [])
            if not legacy:
                continue
            config_data = legacy[0]

        tasks.append(
            QAHubTask(
                config=_parse_config(config_data),
                execution_mode=ExecutionMode[
                    task_data.get("execution_mode", "SERIAL")
                ].value,
                stop_if_success=bool(task_data.get("stop_if_success", False)),
                print_console_message=bool(
                    task_data.get("print_console_message", False)
                ),
                timeout=task_data.get("timeout", 36000),
            )
        )

    return TaskExecution(
        tasks=tasks,
        execution_mode=ExecutionMode[
            profile_data.get("execution_mode", "SERIAL")
        ].value,
        profile_name=profile,
    )


if __name__ == "__main__":
    task_execution = create_execution_with_profile("p2659886400")
    logger.info(
        f"Parsed TaskExecution: {task_execution.tasks[0].print_console_message}"
    )
