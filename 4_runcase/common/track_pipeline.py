"""Check the status of one QA Hub Jenkins testcase (single query)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

from config.env import JENKINS_JOB_URL, QAHUB_HEADERS, QAHUB_URL

from .util import TaskStatus

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


def http_get(
    url: str, *, as_json: bool = False, headers: dict[str, str] | None = None
) -> Any:
    """Fetch a URL, returning parsed JSON when ``as_json`` else decoded text."""
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=600) as response:
        text = response.read().decode("utf-8", errors="replace")
    return json.loads(text) if as_json else text


def get_suite(suite_id: int | str) -> dict[str, Any]:
    """Get the suite information from QA Hub.
    GET https://qahub.eswat.rokulabs.net/api/v1/suite/{suite_id}
    Returns:
        dict: The suite information.
    """
    return http_get(
        f"{QAHUB_URL.rstrip('/')}/suite/{suite_id}", as_json=True, headers=QAHUB_HEADERS
    )["suite"]


def get_build_url(suite_id: int | str) -> str | None:
    """Resolve the Jenkins build URL, or None if no build is assigned yet."""
    if isinstance(suite_id, (list, tuple)):
        suite_id = suite_id[0]
    suite = get_suite(suite_id)
    build_number = suite["jenkins_build_info"]["build_number"]
    return f"{JENKINS_JOB_URL}/{build_number}/"


def track_result(suite_id: int | str, print_console_message=False) -> dict[str, Any]:
    """Query the testcase status once and return an exit code."""
    # -----------------------------------
    # Check result
    # res: Blocked
    # res: Pass
    # res: Skipped
    # res: Error
    # -----------------------------------

    suite_data = get_suite(suite_id)
    state = str(suite_data["state"]).lower()
    build_number = suite_data["jenkins_build_info"]["build_number"]
    log_url = f"https://jenkins.eswat.rokulabs.net/job/qa_hub_launch_suite/{build_number}/consoleFull"

    result = {
        "suite_id": suite_id,
        "build_number": build_number,
        "log_url": log_url,
        "task_status": None,
    }

    if state == "queued":
        time.sleep(15)
        suite_data = get_suite(suite_id)
        state = str(suite_data["state"]).lower()
        if state == "queued":
            result["task_status"] = TaskStatus.QUEUED
            return result

    if state == "processing":
        result["task_status"] = TaskStatus.PROCESSING
        return result
    if state == "setup":
        result["task_status"] = TaskStatus.SETUP
        return result
    if state == "running":
        result["task_status"] = TaskStatus.RUNNING
        return result

    if state == "complete":
        build_url = get_build_url(suite_id)
        console_message = re.sub(
            r"\x1b\[[0-9;]*m", "", http_get(f"{build_url}consoleText")
        )
        if "res: Blocked" in console_message:
            result["task_status"] = TaskStatus.BLOCKED
            return result
        if "res: Pass" in console_message:
            result["task_status"] = TaskStatus.PASS
            return result
        if "res: Skipped" in console_message:
            result["task_status"] = TaskStatus.SKIPPED
            return result
        if "res: Error" in console_message:
            result["task_status"] = TaskStatus.FAILED
            return result
    result["task_status"] = TaskStatus.UNKNOWN
    return result
