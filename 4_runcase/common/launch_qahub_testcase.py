"""Launch one BDD case in QA Hub and upload results to a TestRail plan."""

import enum
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.device_conf.device_info import PlanId
from config.env import QAHUB_TOKEN, QAHUB_URL, SUITE_NAME_PREFIX

from . import logger


class TestCategory(enum.Enum):
    # test_source: file-system //执行单个case
    SingleCase = "file-system"

    # test_source: testrail    //执行整个plan下所有case
    TestPLAN = "testrail"


class CaseType(enum.Enum):
    BDD = "BDD"
    UNITTEST = "UT"
    NEW_CASE = "NEW"  # 新Automated case


class Config:
    def __init__(
        self,
        case_type: str,
        case_id: str,
        device: dict[str, Any],
        testrail_case_id: str = "",
        testrail_plan_id: int = PlanId.NO_PLAN.value,
        repeat: int = 0,
        automation_test_branch: str = "main",
        roku_automation_branch: str = "main",
        test_source: str = TestCategory.SingleCase.value,
    ):
        self.CASE_TYPE = case_type
        self.CASE_ID = case_id
        self.TESTRAIL_CASE_ID = testrail_case_id
        self.device: dict[str, Any] = device

        self.TESTRAIL_PLAN_ID = testrail_plan_id
        self.REPEAT = repeat

        self.AUTOMATION_TEST_BRANCH = automation_test_branch
        self.ROKU_AUTOMATION_BRANCH = roku_automation_branch

        self.TEST_SOURCE = test_source


def build_payload(config: Config) -> dict[str, Any]:
    SN = config.device["config"]["roku"]["serial_number"]
    # print(
    #     f"config: {config.CASE_TYPE}, {config.CASE_ID}, {config.device['name']}, {SN}, {config.TESTRAIL_PLAN_ID}, {config.REPEAT}, {config.AUTOMATION_TEST_BRANCH}, {config.ROKU_AUTOMATION_BRANCH}, {config.TEST_SOURCE}"
    # )

    TESTS = (
        f"BehaveTestCase.test_behave_bdd_{config.CASE_ID}"
        if config.CASE_TYPE == CaseType.BDD.value
        else config.CASE_ID
    )

    TEST_FILTER = (
        f"bdd-{config.CASE_ID}"
        if config.CASE_TYPE in [CaseType.BDD.value, CaseType.NEW_CASE.value]
        else config.CASE_ID
    )

    # SUITE_NAME = f"[JWS]-[{config.device['name']}]-[TP:<{config.TEST_SOURCE}>:{config.TESTRAIL_PLAN_ID}]-[{config.CASE_TYPE}:{config.CASE_ID}]-[SN:{SN}]"
    SUITE_NAME = f"{SUITE_NAME_PREFIX}{config.device['name']}_{config.CASE_ID}_{config.TESTRAIL_PLAN_ID}_{config.REPEAT}"

    payload: dict[str, Any] = {
        "suite_name": SUITE_NAME,
        "test_source": config.TEST_SOURCE,
        "launch_type": "launch",
        "automated_tests_gitlab_branch": config.AUTOMATION_TEST_BRANCH,
        "framework_gitlab_branch": config.ROKU_AUTOMATION_BRANCH,
        "automated_tests_branch_filter": TEST_FILTER,
        "tests": [TESTS] if config.CASE_TYPE != CaseType.NEW_CASE else [],
        "emit_data": True,
        "allows": ["duration-days", "duration-hours", "dangerous"],
        "additional_roku_test_flags": "--xml --xml-split --skip-on-req-error --local-output --non-interactive",
        "device_configs": {
            SN: {
                "custom_json": config.device["config"],
            },
        },
    }

    repeat_int = int(config.REPEAT)

    if repeat_int > 0:
        payload["repeat"] = repeat_int

    if config.TESTRAIL_PLAN_ID:
        payload["testrail_config"] = {
            "push_results": True,
            "live_results": True,
            "project_id": 1,
            "group_type": "plan",
            "group_id": config.TESTRAIL_PLAN_ID,
            "filter": ["all"],
        }

    return payload


def post_suite(qahub_url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{qahub_url.rstrip('/')}/suite"
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)


def print_log(config: Config):
    log_dir = Path(__file__).resolve().parents[1]
    log_path = log_dir / "log.txt"
    existing_content = log_path.read_text() if log_path.exists() else ""
    line_count = len(existing_content.splitlines()) + 1

    log_msg = (
        f"{line_count}".ljust(2)
        + " | "
        + str(config.CASE_TYPE).ljust(3)
        + " | Case:"
        + str(config.CASE_ID).ljust(10)
        + " | "
        + config.AUTOMATION_TEST_BRANCH.ljust(5)
        + " | "
        + config.ROKU_AUTOMATION_BRANCH.ljust(5)
        + " | DeviceName:"
        + config.device["name"].ljust(10)
        + " | DeviceSN:"
        + config.device["config"]["roku"]["serial_number"].ljust(10)
        + " | DeviceIP:"
        + config.device["config"]["roku"]["ip_address"].ljust(15)
        + " | PlanId:["
        + str(config.TEST_SOURCE)
        + "]"
        + str(config.TESTRAIL_PLAN_ID).ljust(3)
        + " | Repeat:"
        + str(config.REPEAT).ljust(3)
        + " | Time:"
        + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        + " |"
    )
    log_path.write_text(log_msg + "\n" + existing_content)
    logger.info(log_msg[log_msg.index("Case:") :])


def launch_test(config: Config) -> dict[str, Any]:
    payload = build_payload(config)
    print_log(config)
    # LogUtil.info("payload: %s" % json.dumps(payload, indent=2))

    try:
        result = post_suite(QAHUB_URL, QAHUB_TOKEN, payload)
    except urllib.error.HTTPError as err:
        logger.error(
            f"QA Hub returned HTTP {err.code}\n{err.read().decode('utf-8', errors='replace')}"
        )
        return {"error": f"QA Hub returned HTTP {err.code}"}

    return result


def terminate_suite(suite_id: int) -> dict[str, Any]:
    headers = {
        "Authorization": f"Token {QAHUB_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        f"{QAHUB_URL.rstrip('/')}/suite/terminate/{suite_id}",
        headers=headers,
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as err:
        logger.error(
            f"Terminate suite {suite_id} returned HTTP {err.code}\n"
            f"{err.read().decode('utf-8', errors='replace')}"
        )
        return {"error": f"QA Hub returned HTTP {err.code}"}
