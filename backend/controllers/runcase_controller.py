import importlib
import importlib.util
import json
import os
import subprocess
import sys
import urllib.request
from typing import Any

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import (
    CASE_CACHE_PATH,
    QAHUB_HEADERS,
    QAHUB_URL,
    QATOOLS_ROOT,
    REPORT_PATH,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import logger

runcase_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.path.join(QATOOLS_ROOT, "4_runcase"))
)

config_conf_path = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        os.path.join(QATOOLS_ROOT, "backend", "conf", "config.yml"),
    )
)

# Case cache files and summary reports both live under QATools/data/runcase_report.
cache_dir = os.path.abspath(CASE_CACHE_PATH)
report_dir = os.path.abspath(REPORT_PATH)


def _load_test_runner():
    """Load 4_runcase/test_runner.py and return its Runner class.

    `common` is a self-contained package (its modules use relative imports), so
    we only need 4_runcase on sys.path for `import common.*` to resolve.
    """
    if runcase_dir not in sys.path:
        sys.path.insert(0, runcase_dir)

    spec = importlib.util.spec_from_file_location(
        "test_runner", os.path.join(runcase_dir, "test_runner.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Runner


Runner = _load_test_runner()

router = APIRouter()


@router.post("/v1/runcase/run")
def run_case(profile_name: str, select: str = "All") -> dict:
    """Run a BDD case with the specified profile and selection."""
    logger.info("Run case: profile='%s' select='%s'", profile_name, select)
    try:
        process = subprocess.Popen(
            ["python3", "-u", "test_runner.py", "-p", profile_name, "-s", select],
            cwd=runcase_dir,
            start_new_session=True,
        )
    except Exception as exc:
        logger.error(
            "Error running profile '%s' select '%s': %s", profile_name, select, exc
        )
        raise HTTPException(
            status_code=500,
            detail=f"Error running profile '{profile_name}' with selection '{select}': {exc}",
        ) from exc

    logger.info("Run case started: profile='%s' pid=%s", profile_name, process.pid)
    return {
        "message": f"Profile '{profile_name}' executed with selection '{select}' started",
        "pid": process.pid,
    }


@router.get("/v1/runcase/list_running")
def list_running_cases() -> dict:
    """List all currently running BDD cases."""
    try:
        command = 'ps aux | grep test_runner.py | grep -v grep | awk \'{pid=$2; p=""; s=""; for(i=1;i<=NF;i++){if($i=="-p") p=$(i+1); if($i=="-s") s=$(i+1)} printf "[PID]:%-8s [Profile]:%-55s [Select]:%s\\n", pid, p, s; c++} END{print "Total: "c}\''
        result = os.popen(command).read()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error listing running cases: {exc}"
        ) from exc
    return {"running_cases": result.strip()}


runcase_log_path = os.path.join(
    os.path.abspath(os.path.join(runcase_dir, "logs")), "runcase.log"
)


@router.get("/v1/runcase/log")
def view_runcase_log(lines: int = 500) -> dict:
    """Return the tail of 4_runcase/logs/runcase.log.

    :param lines: Max number of trailing lines to return (default 500).
    :return: {"content": "<tail text>", "exists": bool}
    """
    if not os.path.isfile(runcase_log_path):
        return {"content": "", "exists": False}
    try:
        with open(runcase_log_path, encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        tail = all_lines[-lines:] if lines > 0 else all_lines
        return {"content": "".join(tail), "exists": True}
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Error reading runcase log: {exc}"
        ) from exc


@router.post("/v1/runcase/stop")
def stop_case(pid: int) -> dict:
    """Stop a BDD case."""
    logger.info("Stop case: pid=%s", pid)
    try:
        os.kill(pid, 9)
    except ProcessLookupError:
        logger.warning("Stop case: process %s not running", pid)
        return {"message": f"Process {pid} not running"}
    except Exception as exc:
        logger.error("Error stopping case pid=%s: %s", pid, exc)
        raise HTTPException(
            status_code=500, detail=f"Error stopping case: {exc}"
        ) from exc
    return {"message": f"Process {pid} stopped"}


def _list_report_dir(pattern: str) -> list[dict]:
    """Return [{name, mtime}] for files in the data report dir matching a glob.

    mtime is epoch seconds (float) so the frontend can format/sort by date.
    """
    import glob

    os.makedirs(report_dir, exist_ok=True)
    entries = []
    for path in glob.glob(os.path.join(report_dir, pattern)):
        try:
            entries.append(
                {"name": os.path.basename(path), "mtime": os.path.getmtime(path)}
            )
        except OSError:
            continue
    return entries


@router.get("/v1/runcase/list_cache")
def list_case_cache_files() -> dict:
    """List all case cache files with their modification time."""
    try:
        files = _list_report_dir("*.cache")
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error listing case cache files: {exc}"
        ) from exc
    return {"files": files}


@router.get("/v1/runcase/view_cache/{cache_file}")
def view_case_cache_file(cache_file: str) -> dict:
    """
    View a case cache file.
    """
    try:
        with open(os.path.join(cache_dir, cache_file), "r") as file:
            cache_file_content = file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error viewing case cache file: {exc}"
        ) from exc

    return {"cache_file_content": cache_file_content.strip()}


@router.get("/v1/runcase/delete_cache/{cache_file}")
def delete_case_cache_file(cache_file: str) -> dict:
    """
    Delete a case cache file.
    """
    try:
        os.remove(os.path.join(cache_dir, cache_file))
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error deleting case cache file: {exc}"
        ) from exc
    return {"message": f"Case cache file '{cache_file}' deleted successfully"}


@router.get("/v1/runcase/list_report")
def list_case_report_files() -> dict:
    """List all case summary report files with their modification time."""
    try:
        files = _list_report_dir("*summary_report.txt")
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error listing case report files: {exc}"
        ) from exc
    return {"files": files}


@router.get("/v1/runcase/view_report/{report_file}")
def view_case_summary_report_file(report_file: str) -> dict:
    """
    View a case summary report file.
    """
    try:
        summary_report_file_path = os.path.join(report_dir, report_file)
        if not os.path.isfile(summary_report_file_path):
            raise HTTPException(
                status_code=404,
                detail=f"Case summary report file '{report_file}' not found",
            )
        with open(summary_report_file_path, "r") as file:
            summary_report_content = file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error viewing case summary report file: {exc}"
        ) from exc

    return {"summary_report_content": summary_report_content.strip()}


@router.get("/v1/runcase/delete_report/{report_file}")
def delete_case_summary_report_file(report_file: str) -> dict:
    """
    Delete a case summary report file.
    """
    try:
        os.remove(os.path.join(report_dir, report_file))
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error deleting case summary report file: {exc}"
        ) from exc
    return {"message": f"Case summary report file '{report_file}' deleted successfully"}


@router.get("/v1/runcase/clear")
def clear_case_data() -> None:
    """
    Clear all case data files.
    """
    try:
        command = f"rm -rf {cache_dir}/*.cache; rm -rf {report_dir}/*summary_report.txt"
        os.popen(command).read()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error clearing case data: {exc}"
        ) from exc

    return {"message": "Case data cleared successfully"}


@router.get("/v1/runcase/list_suites")
def list_suites(user: str, state: str = "running") -> dict:
    """
    List suites by user and state.
    : state: running, complete
    """
    try:
        req = urllib.request.Request(
            f"{QAHUB_URL.rstrip('/')}/suite?user={user}&state={state}",
            headers=QAHUB_HEADERS,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            suites = json.loads(body) if body else {}
            return {"suites": suites.get("suites", [])}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error listing suites: {exc}"
        ) from exc


@router.get("/v1/runcase/terminate_suite")
def terminate_suite(suite_id: int) -> dict[str, Any]:
    """
    Terminate a suite.
    """
    try:
        req = urllib.request.Request(
            f"{QAHUB_URL.rstrip('/')}/suite/terminate/{suite_id}",
            headers=QAHUB_HEADERS,
            method="PATCH",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            result = json.loads(body) if body else {}
            return {"status": result.get("status", "failed")}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error terminating suite: {exc}"
        ) from exc


@router.get("/v1/runcase/suite_build_url")
def suite_build_url(suite_id: int) -> dict:
    """
    Resolve a suite's Jenkins build console URL.

    Looks up the suite's jenkins_build_info.build_number via QAHub and builds the
    qa_hub_launch_suite console URL.
    """
    try:
        req = urllib.request.Request(
            f"{QAHUB_URL.rstrip('/')}/suite/{suite_id}",
            headers=QAHUB_HEADERS,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            result = json.loads(body) if body else {}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error resolving suite build url: {exc}"
        ) from exc

    suite = result.get("suite", {})
    build_number = (suite.get("jenkins_build_info") or {}).get("build_number")
    if not build_number:
        raise HTTPException(
            status_code=404,
            detail=f"No jenkins build_number found for suite {suite_id}",
        )
    url = (
        f"https://jenkins.eswat.rokulabs.net/job/qa_hub_launch_suite/"
        f"{build_number}/console"
    )
    return {"build_number": build_number, "url": url}


@router.get("/v1/runcase/status")
def get_status() -> dict:
    """Get the status of currently running BDD cases."""
    try:
        # Use the same command as in the comment to get the status
        command = 'ps aux | grep test_runner.py | grep -v grep | awk \'{pid=$2; p=""; s=""; for(i=1;i<=NF;i++){if($i=="-p") p=$(i+1); if($i=="-s") s=$(i+1)} printf "[PID]:%-8s [Profile]:%-55s [Select]:%s\\n", pid, p, s; c++} END{print "Total: "c}\''
        result = os.popen(command).read()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving status: {exc}"
        ) from exc

    return {"status": result.strip()}


def _load_runcase_config() -> dict:
    with open(config_conf_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_runcase_config(config_data: dict) -> None:
    # Full round-trip rewrite (drops YAML comments — acceptable, the file is
    # machine-managed); sort_keys=False keeps section ordering stable.
    with open(config_conf_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f, default_flow_style=False, sort_keys=False)


@router.get("/v1/runcase/user_query_list")
def list_user_query_list() -> dict:
    """
    List all user query list.
    """
    try:
        logger.info("List user query list from: %s", config_conf_path)
        config_data = _load_runcase_config()
        return {"user_query_list": config_data.get("runcase_user_query_list", [])}
    except Exception as exc:
        logger.error("Error listing users: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"Error listing users: {exc}"
        ) from exc


class UserQueryBody(BaseModel):
    name: str = Field(..., description="User name to remember in the query list.")


@router.post("/v1/runcase/user_query_list/add")
def add_user_query_list(body: UserQueryBody) -> dict:
    """Remember a searched user name in runcase_user_query_list (no-op if present)."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name cannot be empty")
    try:
        config_data = _load_runcase_config()
        users = config_data.get("runcase_user_query_list") or []
        if any((u or {}).get("name") == name for u in users):
            return {"message": f"'{name}' already saved", "user_query_list": users}
        users.append({"name": name})
        config_data["runcase_user_query_list"] = users
        _save_runcase_config(config_data)
        logger.info("Saved runcase user query '%s'", name)
        return {"message": f"Saved '{name}'", "user_query_list": users}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error saving user query '%s': %s", name, exc)
        raise HTTPException(
            status_code=500, detail=f"Error saving user query: {exc}"
        ) from exc


@router.delete("/v1/runcase/user_query_list/{name}")
def delete_user_query_list(name: str) -> dict:
    """Remove a user name from runcase_user_query_list."""
    try:
        config_data = _load_runcase_config()
        users = config_data.get("runcase_user_query_list") or []
        new_users = [u for u in users if (u or {}).get("name") != name]
        if len(new_users) == len(users):
            raise HTTPException(status_code=404, detail=f"'{name}' not found")
        config_data["runcase_user_query_list"] = new_users
        _save_runcase_config(config_data)
        logger.info("Deleted runcase user query '%s'", name)
        return {"message": f"Deleted '{name}'", "user_query_list": new_users}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error deleting user query '%s': %s", name, exc)
        raise HTTPException(
            status_code=500, detail=f"Error deleting user query: {exc}"
        ) from exc


if __name__ == "__main__":
    run_case("p_01", "All")
