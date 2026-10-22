"""Launch one BDD case in QA Hub and upload results to a TestRail plan."""

import datetime
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from time import sleep

from .launch_qahub_testcase import Config, launch_test, terminate_suite
from .track_pipeline import track_result
from .util import (
    CONST_ALL,
    CONST_NOTEST,
    QUEUED_RETRY_COUNT,
    QUEUED_RETRY_DELAY,
    TRACK_RESULT_INTERVAL,
    ExecutionMode,
    TaskStatus,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import CASE_CACHE_PATH, REPORT_PATH

from . import logger


class QAHubTask:
    def __init__(
        self,
        config: Config,
        execution_mode: str = ExecutionMode.SERIAL.value,
        stop_if_success: bool = False,  # Stop all tasks and exit if a test suite passes
        print_console_message=True,  # Whether to print the console message from Jenkins
        timeout: int = 6 * 60 * 60,  # Timeout in seconds for tracking the test suite
        status: TaskStatus = TaskStatus.PENDING,
    ):
        self.stop_if_success = stop_if_success
        self.execution_mode = execution_mode
        self.config = config
        # Kept as single-element lists so the cache/report/frontend formats (which
        # expect case_ids / testrail_case_ids arrays) stay unchanged.
        self.case_ids = [config.CASE_ID]
        self.testrail_case_ids = [config.TESTRAIL_CASE_ID]
        self.suite_id = None
        self.build_number = None
        self.log_url = None
        self.print_console_message = print_console_message
        self.timeout = timeout
        self.status = status

    def triger_test_suite(self, config: Config):
        """Trigger the test suite for each configuration in the task."""
        self.result = launch_test(config)
        logger.info(f"Result: {self.result}")
        suite_ids = self.result.get("suite_ids", [])
        if not suite_ids:
            self.suite_id = None
            self.status = TaskStatus.ABORTED
            logger.error(
                f"No suite was created for {self.case_ids}. "
                f"QA Hub response: {self.result}"
            )
            return
        self.suite_id = suite_ids[0]
        logger.info(f"Current suite ID: {self.suite_id}")

    def retry_trigger_test_suite(self, config: Config):
        if self.suite_id is not None:
            terminate_suite(self.suite_id)
        self.triger_test_suite(config)

    def launch(self):
        """Launch the test suite for the task's configuration."""
        self.triger_test_suite(self.config)
        if self.execution_mode == ExecutionMode.PARALLEL.value:
            return

        self.track()
        self.should_continue()

    def should_continue(self) -> bool:
        """Check if the execution should continue."""
        if self.status == TaskStatus.QUEUED:
            logger.info(f"Test suite {self.suite_id} is queued. Retrying...")
            for _ in range(QUEUED_RETRY_COUNT):
                self.retry_trigger_test_suite(self.config)
                self.track()
                if self.status != TaskStatus.QUEUED:
                    return False
                sleep(QUEUED_RETRY_DELAY)

        if self.status == TaskStatus.PASS:
            logger.info(f"Test suite {self.suite_id} passed.")
            if self.stop_if_success:
                logger.info("Stopping further execution due to stop_if_success=True.")
                return False
        return True

    def track(self):
        """Track the result of the test suite until it is no longer running or until timeout."""
        while True:
            if self.timeout <= 0:
                logger.error(f"Test suite {self.suite_id} tracking timed out.")
                return
            if self.suite_id is None:
                logger.error("No suite ID to track.")
                return
            try:
                result = track_result(
                    self.suite_id, print_console_message=self.print_console_message
                )
                curr_task_status = result["task_status"]

                if curr_task_status.value != self.status.value:
                    self.status = curr_task_status
                    self.log_url = result["log_url"]
                    self.build_number = result["build_number"]
                    logger.info(
                        f"Test suite: {self.suite_id} status: {self.status.value}"
                    )

                if self.status not in [
                    TaskStatus.PROCESSING,
                    TaskStatus.SETUP,
                    TaskStatus.RUNNING,
                ]:
                    break

                sleep(TRACK_RESULT_INTERVAL)
                self.timeout -= TRACK_RESULT_INTERVAL
            except Exception as e:
                logger.error(f"Error Occurred for test suite {self.suite_id}: {e}")
                self.status = TaskStatus.ABORTED
                break


class TaskExecution:
    def __init__(
        self,
        tasks: list[QAHubTask],
        execution_mode: str = ExecutionMode.SERIAL.value,
        profile_name: str = "",
    ):
        self.tasks = tasks
        self.current_task_index = 1
        self.execution_mode = execution_mode
        self.profile_name = profile_name

        # Set up cache directory and load existing cache if available
        cache_dir = Path(CASE_CACHE_PATH)
        cache_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        self.cache_path = cache_dir / (timestamp + "_" + self.profile_name + ".cache")
        self.cache: dict[str, str] = {}  # Initialize cache as an empty dictionary
        self.load_cache()  # Load existing cache if available

        # Clear cache at the start of execution
        self.clear_cache()

    def execute(self, select=CONST_ALL):
        """Execute the tasks based on the provided selection criteria."""
        threads = []
        task_count = len(self.tasks)
        logger.info(f"Total tasks to execute: {task_count}")
        self.current_task_index = 1

        # Clear cache if executing all tasks
        if select == CONST_ALL:
            self.clear_cache()
            self.cache = {}

        for task in self.tasks:
            if self.check_skip_tasks(task, select):
                continue

            logger.info("--------------------------------------------------------")
            logger.info(f"- Run Task: {self.current_task_index}/{task_count}")
            logger.info(f"- Case IDs: {task.case_ids}")

            if self.execution_mode == ExecutionMode.SERIAL.value:
                task.launch()
            else:
                thread = Thread(target=task.launch)
                thread.start()
                threads.append(thread)
            logger.info(f"- Case IDs: {task.case_ids}, Status: {task.status.value}")
            self.save_case_cache(
                {
                    str(task.case_ids): {
                        "case_ids": task.case_ids,
                        "testrail_case_ids": task.testrail_case_ids,
                        "status": task.status.value,
                        "log_url": task.log_url,
                        "build_number": task.build_number,
                    }
                }
            )
            if self.current_task_index < task_count:
                self.current_task_index += 1

        logger.info("#########################################################")
        logger.info("-- [Summary] --")
        logger.info("#########################################################")
        logger.info(f"- Result: {self.current_task_index}/{task_count}")
        for task in self.tasks:
            logger.info(f"- Case IDs: {task.case_ids}, Status: {task.status.value}")
        self.generate_summary_report()

        # Wait for all parallel threads to complete
        for thread in threads:
            thread.join()

    def generate_summary_report(self):
        """Generate a summary report of the executed tasks.
        Report format:
        {
            "profile_name": "p_01.json",
            "count": 1,
            "tasks": [
                {
                    "case_ids": [
                        "2726306176"
                    ],
                    "testrail_case_ids": [
                        "2726306176"
                    ],
                    "status": "Skipped",
                    "log_url": "https://jenkins.eswat.rokulabs.net/job/qa_hub_launch_suite/1317209/consoleFull",
                    "build_number": 1317209
                }
            ]
        }
        """
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        report_dir = Path(REPORT_PATH)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / (
            timestamp + "_" + self.profile_name + "_summary_report.txt"
        )
        report_data = {
            "profile_name": self.profile_name,
            "count": len(self.tasks),
            "tasks": [],
        }

        for task in self.tasks:
            report_data["tasks"].append(
                {
                    "case_ids": task.case_ids,
                    "testrail_case_ids": task.testrail_case_ids,
                    "status": task.status.value,
                    "log_url": task.log_url,
                    "build_number": task.build_number,
                }
            )

        with open(report_path, "w") as f:
            json.dump(report_data, f, indent=4)

    def check_skip_tasks(self, task: QAHubTask, select: str) -> bool:
        """Check if the task should be skipped based on the cache and the select parameter.
        Cache format:
        {
            "task_results": {
                "['2726306176']": {
                    "status": "Skipped",
                    "log_url": "https://jenkins.eswat.rokulabs.net/job/qa_hub_launch_suite/1317209/consoleFull",
                    "build_number": 1317209
                }
            },
            "task_progress": "1/1"
        }
        """
        # No tasks are skipped if "All" is selected
        if select == CONST_ALL:
            return False

        # Check if the task has been executed before and if "NoTest" is selected
        if select == CONST_NOTEST and str(task.case_ids) in self.cache.get(
            "task_results", {}
        ):
            logger.info(f"Skipping task '{task.case_ids}'")
            self.current_task_index += 1
            return True

        # Skip the task if its result is not in the selected criteria
        if (
            str(task.case_ids) in self.cache.get("task_results", {})
            and self.cache.get(str(task.case_ids), {}).get("status", None) not in select
        ):
            logger.info(f"Skipping task '{task.case_ids}'")
            self.current_task_index += 1
            return True
        return False

    def clear_cache(self):
        """Clear the cache file if it exists."""
        if self.cache_path.exists():
            self.cache_path.unlink()

    def save_case_cache(self, result: dict[str, str]):
        """Save the result of the current task to the cache file."""
        if self.cache_path.exists():
            with open(self.cache_path, "r") as f:
                try:
                    self.cache = json.load(f)
                except json.JSONDecodeError:
                    self.cache = {}
        else:
            self.cache_path.write_text(json.dumps({}))
            self.cache = {}

        if "task_results" not in self.cache:
            self.cache["task_results"] = {}
        self.cache["task_results"].update(result)

        self.cache["task_progress"] = f"{self.current_task_index}/{len(self.tasks)}"

        with open(self.cache_path, "w") as f:
            json.dump(self.cache, f, indent=4)

    def load_cache(self) -> dict[str, str]:
        """Load the cache from the cache file."""
        if not self.cache_path.exists():
            self.cache_path.write_text(json.dumps({}))
            self.cache = {}
            return self.cache

        with open(self.cache_path, "r") as f:
            try:
                self.cache = json.load(f)
                return self.cache
            except json.JSONDecodeError:
                self.cache = {}
                return self.cache
