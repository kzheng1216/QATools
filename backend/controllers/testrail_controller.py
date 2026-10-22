import base64
import json
import os
import sys
import urllib.error
import urllib.request

import requests
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import (
    EMAIL,
    QATOOLS_ROOT,
    TESTRAIL_API_KEY,
    TESTRAIL_DATA_PATH,
    TESTRAIL_URL,
)
from fastapi import APIRouter, HTTPException
from requests.auth import HTTPBasicAuth

from . import logger

testrail_data_dir = os.path.abspath(TESTRAIL_DATA_PATH)
testrail_conf_path = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        os.path.join(QATOOLS_ROOT, "backend", "conf", "testrail.yml"),
    )
)

try:
    with open(testrail_conf_path, encoding="utf-8") as _f:
        testrail_conf = yaml.safe_load(_f) or {}
except FileNotFoundError:
    testrail_conf = {}
testrail_conf.setdefault("testrail", {}).setdefault("plan", [])

router = APIRouter()

# TestRail API base and per-test result view link.
_API_URL = f"{TESTRAIL_URL.rstrip('/')}/index.php?/api/v2"
_TEST_VIEW = f"{TESTRAIL_URL.rstrip('/')}/index.php?/tests/view/"
_LINK_SUFFIX = "&group_by=cases:title&group_order=asc&display=tree&group_id=-1"
# TestRail Basic Auth requires the login email as the username (not a token alias).
_AUTH = base64.b64encode(f"{EMAIL}:{TESTRAIL_API_KEY}".encode()).decode()
_HEADERS = {"Authorization": f"Basic {_AUTH}", "Content-Type": "application/json"}


def _tr_get(endpoint: str) -> dict | list:
    """Call a TestRail API v2 GET endpoint and return the parsed JSON.
    Example: https://testrail.eswat.roku.com/testrail/index.php?/api/v2/get_tests/26595380&status_id=Failed
    """
    req = urllib.request.Request(
        f"{_API_URL}/{endpoint}", headers=_HEADERS, method="GET"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body) if body else {}


def _statuses() -> list[dict]:
    """Return the instance's statuses: [{id, name(internal), label(display)}].

    Example: https://testrail.eswat.roku.com/testrail/index.php?/api/v2/get_statuses
    Passed: 1, Blocked: 2, Untested: 3, For Review: 4, Failed: 5, NA: 8, Retest: 9, Broken: 10
    """
    data = _tr_get("get_statuses")
    return [
        {"id": s["id"], "name": s.get("name"), "label": s.get("label")}
        for s in (data if isinstance(data, list) else data.get("statuses", []))
    ]


def _status_label_to_id(label: str) -> int | None:
    """Map a user-facing status label (case-insensitive) to its status_id."""
    target = label.strip().lower()
    for s in _statuses():
        if (s.get("label") or "").lower() == target:
            return s["id"]
    return None


@router.get("/v1/testrail/status/list")
def list_statuses() -> dict:
    """List this TestRail instance's statuses (id + display label)."""
    try:
        return {"statuses": _statuses()}
    except Exception as exc:
        logger.exception("Error listing testrail statuses")
        raise HTTPException(
            status_code=500, detail=f"Error listing testrail statuses: {exc}"
        ) from exc


def _plan_run_ids(plan: str) -> list[int]:
    """Return every run id contained in a TestRail plan."""
    data = _tr_get(f"get_plan/{plan}")
    run_ids = []
    for entry in data.get("entries", []):
        for run in entry.get("runs", []):
            run_ids.append(run["id"])
    return run_ids


def _cache_file(plan: str, status: str) -> str:
    """Cache file path for a plan+status. Status is sanitized for the filename."""
    safe_status = status.strip().replace(" ", "_").replace("/", "_")
    return os.path.join(testrail_data_dir, f"{plan}_{safe_status}.json")


def _fetch_cases_from_testrail(plan: str, status: str) -> dict:
    """Fetch cases of a given status under a plan directly from TestRail."""
    # Resolve the status_id live (labels/ids are instance-specific).
    status_id = _status_label_to_id(status)
    if status_id is None:
        valid = [s.get("label") for s in _statuses()]
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported status: {status}. Use one of {valid}.",
        )

    cases = []
    for run_id in _plan_run_ids(plan):
        tests = _tr_get(f"get_tests/{run_id}&status_id={status_id}")
        for test in tests.get("tests", tests) if isinstance(tests, dict) else tests:
            cases.append(
                {
                    "run_id": run_id,
                    "test_id": test["id"],
                    "case_id": test["case_id"],
                    "title": test.get("title"),
                    "automation_id": test.get("custom_automated"),
                    "link": f"{_TEST_VIEW}{test['id']}{_LINK_SUFFIX}",
                }
            )
    return {"plan": plan, "status": status, "count": len(cases), "cases": cases}


@router.get("/v1/testrail/plan/case/list")
def list_cases_by_plan(plan: str, status: str = "Failed", sync: bool = False) -> dict:
    """List testrail cases of a given status under a plan, with caching.

    :param plan: TestRail plan id
    :param status: e.g. Passed, Blocked, Untested, Retest, Failed, For Review, NA
    :param sync: if True, always fetch fresh from TestRail and refresh the cache.

    Behavior:
        - sync=True                       -> fetch from TestRail, (re)write cache
        - no cache file exists            -> fetch from TestRail, write cache
        - sync=False and cache exists     -> return the cached file
    """
    os.makedirs(testrail_data_dir, exist_ok=True)
    cache_path = _cache_file(plan, status)

    # Serve from cache when allowed and available.
    if not sync and os.path.isfile(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
            data["cached"] = True
            return data
        except Exception as exc:
            logger.exception("Error loading testrail cache %s", cache_path)
            raise HTTPException(
                status_code=500, detail=f"Error loading testrail cache: {exc}"
            ) from exc

    # Otherwise fetch fresh from TestRail.
    try:
        data = _fetch_cases_from_testrail(plan, status)
    except HTTPException:
        raise
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=exc.code, detail=f"TestRail API error: {exc.reason}"
        ) from exc
    except Exception as exc:
        logger.exception("Error listing testrail plan cases")
        raise HTTPException(
            status_code=500, detail=f"Error listing testrail plan cases: {exc}"
        ) from exc

    # Write/overwrite the cache.
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.warning("Failed to write testrail cache %s: %s", cache_path, exc)

    data["cached"] = False
    return data


@router.get("/v1/testrail/plan/list")
def list_plans() -> dict:
    """List all testrail plans."""
    with open(testrail_conf_path, "r") as f:
        testrail_conf = yaml.safe_load(f)
    return {"plans": testrail_conf.get("testrail", {}).get("plan", [])}


@router.post("/v1/testrail/plan/add")
def add_plan(plan_data: dict) -> dict:
    """Add a testrail plan."""
    if not testrail_conf.get("testrail", {}).get("plan"):
        testrail_conf["testrail"]["plan"] = []
    testrail_conf["testrail"]["plan"].append(plan_data)
    with open(testrail_conf_path, "w") as f:
        yaml.safe_dump({"testrail": {"plan": testrail_conf["testrail"]["plan"]}}, f)
    return {"success": True}


@router.delete("/v1/testrail/plan/delete")
def delete_plan(plan_id: int) -> dict:
    """Delete a testrail plan."""
    if not testrail_conf.get("testrail", {}).get("plan"):
        testrail_conf["testrail"]["plan"] = []
    testrail_conf["testrail"]["plan"] = [
        plan for plan in testrail_conf["testrail"]["plan"] if plan["id"] != plan_id
    ]
    with open(testrail_conf_path, "w") as f:
        yaml.safe_dump({"testrail": {"plan": testrail_conf["testrail"]["plan"]}}, f)
    return {"success": True}


@router.get("/v1/testrail/testrail_data/list")
def list_testrail_data(plan: str) -> dict:
    """List all testrail data for a given plan.
    return data:
    {
        "Failed": "26595350_Failed.json",
        "For Review": "26595350_For Review.json",
        "Retest": "26595350_Retest.json"
    }
    """
    testrail_data_files = [
        f
        for f in os.listdir(testrail_data_dir)
        if f.startswith(plan) and f.endswith(".json")
    ]
    testrail_data = {}
    for file in testrail_data_files:
        testrail_data[file.split("_")[1].split(".")[0]] = file
    return testrail_data


@router.get("/v1/testrail/testrail_data/available")
def list_available_testrail_data() -> dict:
    """Group existing testrail_data files by plan and status.

    File names are '<plan>_<status>.json' (status may contain underscores/spaces).
    Returns:
    {
        "plans": {
            "26595350": {"Failed": "26595350_Failed.json"},
            "26595408": {"Failed": "26595408_Failed.json"}
        }
    }
    """
    plans: dict[str, dict[str, str]] = {}
    try:
        files = [f for f in os.listdir(testrail_data_dir) if f.endswith(".json")]
    except OSError:
        files = []

    for file in files:
        stem = file[:-5]  # drop ".json"
        if "_" not in stem:
            continue
        plan, status = stem.split("_", 1)  # plan before first "_", status = rest
        plans.setdefault(plan, {})[status] = file

    return {"plans": plans}


def import_cases_to_testrail_plan(plan_id: int, case_ids: list[int]) -> None:
    """Import cases to a testrail plan."""
    case_ids = case_ids if isinstance(case_ids, list) else [case_ids]
    auth = HTTPBasicAuth(EMAIL, TESTRAIL_API_KEY)
    headers = {"Content-Type": "application/json"}

    cases_by_suite = {}

    for case_id in case_ids:
        case_url = f"{TESTRAIL_URL}index.php?/api/v2/get_case/{case_id}"
        case_response = requests.get(case_url, auth=auth, headers=headers)

        if case_response.status_code != 200:
            logger.warning(
                f"Error getting case {case_id} - {case_response.status_code}"
            )
            continue

        case_data = case_response.json()
        suite_id = case_data.get("suite_id")

        if suite_id not in cases_by_suite:
            suite_url = f"{TESTRAIL_URL}index.php?/api/v2/get_suite/{suite_id}"
            suite_response = requests.get(suite_url, auth=auth, headers=headers)

            if suite_response.status_code != 200:
                logger.warning(
                    f"Error getting suite {suite_id} - {suite_response.status_code}"
                )
                continue

            suite_data = suite_response.json()
            suite_name = suite_data.get("name")
            cases_by_suite[suite_id] = {"suite_name": suite_name, "case_ids": []}

        cases_by_suite[suite_id]["case_ids"].append(case_id)

    plan_url = f"{TESTRAIL_URL}index.php?/api/v2/get_plan/{plan_id}"
    plan_response = requests.get(plan_url, auth=auth, headers=headers)

    if plan_response.status_code != 200:
        logger.warning(f"Error getting plan {plan_id} - {plan_response.status_code}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting plan {plan_id} - {plan_response.status_code}",
        )

    plan_data = plan_response.json()
    entries = plan_data.get("entries", [])
    total_added = 0
    total_skipped = 0

    for suite_id, suite_info in cases_by_suite.items():
        suite_name = suite_info["suite_name"]
        new_case_ids = suite_info["case_ids"]

        target_run = None
        target_entry_id = None

        for entry in entries:
            if entry.get("suite_id") == suite_id:
                runs = entry.get("runs", [])
                if runs:
                    target_run = runs[0]
                    target_entry_id = entry.get("id")
                    break

        if not target_run:
            entry_data = {
                "suite_id": suite_id,
                "name": suite_name,
                "include_all": False,
                "case_ids": new_case_ids,
            }

            add_entry_url = f"{TESTRAIL_URL}index.php?/api/v2/add_plan_entry/{plan_id}"

            entry_response = requests.post(
                add_entry_url, auth=auth, headers=headers, json=entry_data
            )

            if entry_response.status_code != 200:
                logger.warning(
                    f"Error creating plan entry - {entry_response.status_code}"
                )
                continue

            new_entry = entry_response.json()
            total_added += len(new_case_ids)
            logger.info(
                f"Successfully created plan entry and added {len(new_case_ids)} cases"
            )
            if new_entry.get("runs"):
                logger.info(
                    f"Run URL: {TESTRAIL_URL}index.php?/runs/view/{new_entry['runs'][0].get('id')}"
                )

        else:
            run_id = target_run.get("id")
            all_tests = []
            offset = 0
            limit = 250

            while True:
                tests_url = f"{TESTRAIL_URL}index.php?/api/v2/get_tests/{run_id}&limit={limit}&offset={offset}"
                tests_response = requests.get(tests_url, auth=auth, headers=headers)

                if tests_response.status_code != 200:
                    logger.warning(
                        f"Error getting tests - {tests_response.status_code}"
                    )
                    break

                tests_data = tests_response.json()
                if isinstance(tests_data, dict) and "tests" in tests_data:
                    tests_list = tests_data["tests"]
                elif isinstance(tests_data, list):
                    tests_list = tests_data
                else:
                    tests_list = []

                if not tests_list:
                    break

                all_tests.extend(tests_list)

                if len(tests_list) < limit:
                    break

                offset += limit

            current_case_ids = [test["case_id"] for test in all_tests]
            logger.info(f"Current running case count: {len(current_case_ids)}")

            if target_run.get("include_all"):
                logger.info("This run already contains all test cases")
                total_skipped += len(new_case_ids)
            else:
                cases_to_add = [
                    cid for cid in new_case_ids if cid not in current_case_ids
                ]
                already_exists = [
                    cid for cid in new_case_ids if cid in current_case_ids
                ]

                if already_exists:
                    logger.info(f"Already existing cases: {already_exists}")
                    total_skipped += len(already_exists)

                if cases_to_add:
                    updated_case_ids = current_case_ids + cases_to_add
                    update_data = {"case_ids": updated_case_ids}

                    update_url = f"{TESTRAIL_URL}index.php?/api/v2/update_plan_entry/{plan_id}/{target_entry_id}"
                    logger.info(f"Adding new cases: {cases_to_add}")
                    logger.info(
                        f"Total case count after update: {len(updated_case_ids)}"
                    )

                    update_response = requests.post(
                        update_url, auth=auth, headers=headers, json=update_data
                    )

                    if update_response.status_code != 200:
                        logger.warning(
                            f"Error updating plan entry - {update_response.status_code}"
                        )
                        continue

                    total_added += len(cases_to_add)
                    logger.info(f"Successfully added {len(cases_to_add)} test cases")
                    logger.info(f"Run URL: {TESTRAIL_URL}index.php?/runs/view/{run_id}")
                else:
                    logger.info("All cases already exist, no need to add")

    logger.info(f"Total added: {total_added} test cases")
    logger.info(f"Total skipped: {total_skipped} test cases")
    logger.info(f"Plan URL: {TESTRAIL_URL}index.php?/plans/view/{plan_id}")


@router.post("/v1/testrail/plan/case/add")
def add_plan_cases(request_data: dict) -> dict:
    """Add cases to a testrail plan."""
    plan_id = request_data.get("plan_id")
    case_ids = request_data.get("case_ids")
    if not plan_id or not case_ids:
        return {"success": False, "message": "Plan ID and case IDs are required"}

    try:
        import_cases_to_testrail_plan(plan_id, case_ids)
        return {"success": True, "message": "Cases added to plan successfully"}
    except Exception as exc:
        logger.exception("Error adding plan cases")
        return {"success": False, "message": f"Error adding plan cases: {exc}"}
