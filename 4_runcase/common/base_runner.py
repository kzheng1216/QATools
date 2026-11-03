"""Base class for running QA Hub tasks. Only sample cases are provided here."""

from config.device_conf.device_info import DeviceInfo, PlanId

from .launch_qahub_testcase import CaseType, Config, TestCategory
from .profile_parse import create_execution_with_profile
from .task_handle import ExecutionMode, QAHubTask, TaskExecution


class BaseRunner:
    """Base class for running QA Hub tasks. Only sample cases are provided here."""

    def __init__(self):
        pass

    def c_sample(self):
        return Config(
            case_type=CaseType.NEW_CASE.value,
            # case_type=CaseType.BDD.value,
            # case_type=CaseType.UNITTEST.value,
            case_id="2910861311",
            # case_id="LiveTVPauseGenericTestCase.test_live_tv_pause_move_live_tv_tile",
            device=DeviceInfo().devices["de_us_428"],
            testrail_plan_id=PlanId.NO_PLAN.value,
            automation_test_branch="main",
            roku_automation_branch="main",
            repeat=2,
            test_source=TestCategory.SingleCase.value,
        )

    def c2659886400_DE(self):
        return Config(
            case_type=CaseType.BDD.value,
            case_id="2659886400",
            device=DeviceInfo().devices["d_de_2"],
            automation_test_branch="main",
            roku_automation_branch="main",
            repeat=0,
        )

    def run_direct(self):
        """Run a single QA Hub task directly without using a profile."""
        TaskExecution(
            tasks=[
                QAHubTask(
                    config=self.c2659886400_DE(),
                    execution_mode=ExecutionMode.SERIAL.value,
                    stop_if_success=True,
                    print_console_message=False,
                    timeout=36000,
                )
            ],
            execution_mode=ExecutionMode.SERIAL.value,
        ).execute()

    def run_profile(self):
        """Run a single QA Hub task using a profile."""
        create_execution_with_profile("p2659886400").execute()
