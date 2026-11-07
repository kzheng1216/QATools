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
        stop_if_success: bool = False,  # Stop all tasks and exit if a test suite passes
        timeout: int = 6 * 60 * 60,  # Timeout in seconds for tracking the test suite
        status: TaskStatus = TaskStatus.PROCESSING,
    ):
        self.stop_if_success = stop_if_success
        self.config = config
        self.case_ids = [config.CASE_ID]
        self.testrail_case_ids = [config.TESTRAIL_CASE_ID]
        self.suite_id = None
        self.build_number = None
        self.log_url = None
        self.timeout = timeout
        self.status = status

    def cache_result(self) -> dict[str, str]:
        """Cache the result of the test suite."""
        return {
            str(self.case_ids): {
                "case_ids": self.case_ids,
                "testrail_case_ids": self.testrail_case_ids,
                "status": self.status.value,
                "log_url": self.log_url,
                "build_number": self.build_number,
            }
        }

    def triger_test_suite(self, config: Config):
        """Trigger the test suite for each configuration in the task."""
        self.result = launch_test(config)
        # logger.info(f"Result: {self.result}")
        suite_ids = self.result.get("suite_ids", [])
        if not suite_ids:
            self.suite_id = None
            self.status = TaskStatus.ABORTED
            return
        self.suite_id = suite_ids[0]

    def launch(self):
        """Launch the test suite for the task's configuration."""
        for _ in range(QUEUED_RETRY_COUNT):
            self.triger_test_suite(self.config)
            self.track()
            if self.status == TaskStatus.QUEUED and self.suite_id is not None:
                terminate_suite(self.suite_id)
                sleep(QUEUED_RETRY_DELAY)
                continue
            break

    def is_stop_tracking(self) -> bool:
        """Check if the tracking should be stopped."""
        # Timeout
        if self.timeout <= 0:
            logger.error(f"Test suite {self.suite_id} tracking timed out.")
            return True

        # No suite ID to track
        if self.suite_id is None:
            logger.error(f"Test suite {self.suite_id} no suite ID to track.")
            return True

        # Not running or setup or running
        if self.status not in [
            TaskStatus.PROCESSING,
            TaskStatus.SETUP,
            TaskStatus.RUNNING,
        ]:
            logger.warning(
                f"Test suite {self.suite_id} status: {self.status.value}, breaking out of the tracking loop..."
            )
            return True

        # Sleep and continue tracking
        sleep(TRACK_RESULT_INTERVAL)
        self.timeout -= TRACK_RESULT_INTERVAL
        return False

    def track(self):
        """Track the result of the test suite until it is no longer running or until timeout."""
        try:
            while True:
                if self.is_stop_tracking():
                    break

                # Track the result of the test suite
                result = track_result(self.suite_id)
                curr_task_status = result["task_status"]

                if curr_task_status.value != self.status.value:
                    self.status = curr_task_status
                    self.log_url = result["log_url"]
                    self.build_number = result["build_number"]

        except Exception as e:
            logger.error(f"Error Occurred for test suite {self.suite_id}: {e}")
            self.status = TaskStatus.ABORTED


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
        self.task_count = len(self.tasks)

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
        logger.info(f"Total tasks to execute: {self.task_count}")
        self.current_task_index = 1
        threads: list[Thread] = []

        if select == CONST_ALL:
            self.clear_cache()
            self.cache = {}

        is_serial = self.execution_mode == ExecutionMode.SERIAL.value
        for task in self.tasks:
            if self.check_skip_tasks(task, select):
                continue

            logger.info("--------------------------------------------------------")
            logger.info(
                f"- [Task:{self.current_task_index}/{self.task_count}] - Case: [{task.testrail_case_ids}][{task.case_ids}]"
            )
            if is_serial:
                task.launch()
            else:
                thread = Thread(target=task.launch)
                thread.start()
                threads.append(thread)

            logger.info(f"- [Result]: {task.status.value}")
            self.save_case_cache(task.cache_result())
            self.current_task_index = min(self.current_task_index + 1, self.task_count)

        self.print_summary()
        self.generate_summary_report()
        for thread in threads:
            thread.join()

    def print_summary(self):
        """Print the summary of the executed tasks."""
        logger.info("#########################################################")
        logger.info("-- [Summary] --")
        logger.info("#########################################################")
        logger.info(
            f"- Total Tasks: {self.task_count}, Executed Tasks: {self.current_task_index}"
        )
        for task in self.tasks:
            logger.info(
                f"- Case: {task.testrail_case_ids} - {task.case_ids}, Result: {task.status.value}"
            )

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
