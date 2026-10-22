import asyncio
import os
import shlex
import shutil
import subprocess
import sys
from datetime import UTC, datetime

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import DATA_BASE_DIR, QATOOLS_ROOT, ROKU_TEST_LOG_DIR

from . import logger

# config.yml holds the Run-in-local input history under roku_test_cache_data:
#   roku_test_cache_data:
#     automation_id: [ ... ]
#     testrail_case_id: [ ... ]
_config_path = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        os.path.join(QATOOLS_ROOT, "backend", "conf", "config.yml"),
    )
)
_CACHE_KEY = "roku_test_cache_data"
_CACHE_FIELDS = ("automation_id", "testrail_case_id")

device_conf_dir = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), os.path.join(QATOOLS_ROOT, "config", "device_conf")
    )
)
roku_test_dir = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        os.path.join(QATOOLS_ROOT, DATA_BASE_DIR, ROKU_TEST_LOG_DIR),
    )
)
router = APIRouter()


def _load_config() -> dict:
    with open(_config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_config(config: dict) -> None:
    # Full round-trip rewrite (drops YAML comments — acceptable, machine-managed);
    # sort_keys=False keeps section ordering stable.
    with open(_config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)


def _cache_list(field: str) -> list[str]:
    data = _load_config().get(_CACHE_KEY) or {}
    vals = data.get(field)
    return [str(v) for v in vals] if isinstance(vals, list) else []


def _cache_add(field: str, value: str) -> list[str]:
    """Prepend value to roku_test_cache_data.<field> (dedup, newest first)."""
    value = value.strip()
    if not value:
        return _cache_list(field)
    config = _load_config()
    cache = config.setdefault(_CACHE_KEY, {})
    if not isinstance(cache, dict):
        cache = {}
        config[_CACHE_KEY] = cache
    vals = cache.get(field)
    vals = [str(v) for v in vals] if isinstance(vals, list) else []
    vals = [v for v in vals if v != value]
    vals.insert(0, value)
    cache[field] = vals[:100]  # keep the 100 most recent
    _save_config(config)
    return cache[field]


def _cache_delete(field: str, value: str) -> list[str]:
    config = _load_config()
    cache = config.get(_CACHE_KEY) or {}
    vals = cache.get(field) if isinstance(cache, dict) else None
    if not isinstance(vals, list):
        return []
    kept = [str(v) for v in vals if str(v) != value]
    if len(kept) == len(vals):
        raise HTTPException(status_code=404, detail=f"'{value}' not found in {field}")
    cache[field] = kept
    config[_CACHE_KEY] = cache
    _save_config(config)
    return kept


@router.get("/v1/rokutest/cache/{field}")
def list_roku_test_cache(field: str) -> dict:
    """List cached input history for 'automation_id' or 'testrail_case_id'."""
    if field not in _CACHE_FIELDS:
        raise HTTPException(status_code=400, detail=f"Unknown field '{field}'")
    try:
        return {"values": _cache_list(field)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Error listing {field} cache: {exc}"
        ) from exc


class CacheValueBody(BaseModel):
    value: str = Field(..., description="Value to remember in the history list.")


@router.post("/v1/rokutest/cache/{field}/add")
def add_roku_test_cache(field: str, body: CacheValueBody) -> dict:
    """Remember a value in the input history (no-op if blank)."""
    if field not in _CACHE_FIELDS:
        raise HTTPException(status_code=400, detail=f"Unknown field '{field}'")
    try:
        return {"values": _cache_add(field, body.value)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Error saving {field} cache: {exc}"
        ) from exc


@router.delete("/v1/rokutest/cache/{field}/{value}")
def delete_roku_test_cache(field: str, value: str) -> dict:
    """Remove a value from the input history."""
    if field not in _CACHE_FIELDS:
        raise HTTPException(status_code=400, detail=f"Unknown field '{field}'")
    try:
        return {"values": _cache_delete(field, value)}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Error deleting {field} cache: {exc}"
        ) from exc


def _roku_test_bin() -> str:
    venv_bin = os.path.join(os.path.dirname(sys.executable), "roku_test")
    if os.path.isfile(venv_bin):
        return venv_bin
    return shutil.which("roku_test") or "roku_test"


async def _run_roku_test_cmd(cmd: str, log_file: str) -> int:
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    shell_cmd = f"({cmd} > {shlex.quote(log_file)} 2>&1 & echo $!)"
    process = await asyncio.create_subprocess_shell(
        shell_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    return int(stdout.decode().strip())


def _get_git_branch_name() -> str:
    """Get the current git branch name."""
    cmd = "cd ~/automated_tests && git rev-parse --abbrev-ref HEAD"
    process = subprocess.Popen(
        cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    stdout, _ = process.communicate()
    return stdout.decode().strip()


@router.post("/v1/rokutest/run")
async def run_roku_test(
    device: str,
    automated_test_id: str,
    testrail_case_id: str,
    repeat: int = 0,
) -> dict:
    """
    Run a Roku test with the specified device, case_id and repeat.
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(
        roku_test_dir,
        f"roku_test__{automated_test_id}__{testrail_case_id}__{device}__{repeat}__{timestamp}.log",
    )
    repeat_arg = f"--repeat {repeat}" if repeat > 0 else ""
    cmd = f"{_roku_test_bin()} -d {device_conf_dir}/{device}.json {repeat_arg} --allow dangerous --allow duration-hours --filter '{automated_test_id}' ~/automated_tests/tests"
    logger.info(
        "Run roku test: device='%s' automated_test_id='%s' testrail_case_id='%s' repeat=%s",
        device,
        automated_test_id,
        testrail_case_id,
        repeat,
    )
    pid = await _run_roku_test_cmd(cmd, log_file)

    # Remember the inputs in the history cache (best-effort; never fail the run).
    try:
        _cache_add("automation_id", automated_test_id)
        _cache_add("testrail_case_id", testrail_case_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to update roku_test input cache: %s", exc)

    logger.info(
        "Roku test started: device='%s' automated_test_id='%s' testrail_case_id='%s' pid=%s log=%s",
        device,
        automated_test_id,
        testrail_case_id,
        pid,
        log_file,
    )
    return {
        "message": f"Roku test with device '{device}', automated_test_id '{automated_test_id}' and testrail_case_id '{testrail_case_id}' and repeat '{repeat}' started",
        "command": cmd,
        "log_file": log_file,
        "pid": pid,
    }


@router.get("/v1/rokutest/status/{pid}")
def get_roku_test_status(pid: int) -> dict:
    """
    Get the status of a Roku test.
    """
    if pid <= 0:
        return {"pid": pid, "status": "not_running"}

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return {"pid": pid, "status": "not_running"}

    command = ""
    try:
        with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
            command = f.read().strip()
    except OSError:
        pass

    return {"pid": pid, "status": "running", "command": command}


@router.get("/v1/rokutest/log/list")
def list_roku_test_logs() -> dict:
    """
    List Roku test log files with their running/completed state.
    """
    try:
        os.makedirs(roku_test_dir, exist_ok=True)
        files = [f for f in os.listdir(roku_test_dir) if f.endswith(".log")]
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Error listing roku test logs: {exc}"
        ) from exc

    # Snapshot of live roku_test process command lines. The log file name is NOT
    # in the args (output is shell-redirected), so running state is matched via the
    # automation_id (passed via --filter) and device (-d device_conf/<device>.json).
    running_cmds = [
        line
        for line in os.popen("ps -eo args").read().splitlines()
        if "roku_test" in line and "grep" not in line
    ]

    def _parse_name(name: str) -> tuple[str, str] | None:
        # Log name: roku_test__{automation_id}__{testrail_case_id}__{device}__{repeat}__{ts}.log
        base = name[: -len(".log")] if name.endswith(".log") else name
        parts = base.split("__")
        if len(parts) < 4 or parts[0] != "roku_test":
            return None
        return parts[1], parts[3]  # (automation_id, device)

    # For each live process, mark only the single newest matching log as running
    # (an automation_id+device can have many old logs; only the latest is live).
    running_names: set[str] = set()
    candidates = sorted(files, key=lambda n: os.path.getmtime(os.path.join(roku_test_dir, n)) if os.path.exists(os.path.join(roku_test_dir, n)) else 0, reverse=True)
    for cmd in running_cmds:
        for name in candidates:
            parsed = _parse_name(name)
            if not parsed:
                continue
            automation_id, device = parsed
            if automation_id and device and automation_id in cmd and f"{device}.json" in cmd:
                running_names.add(name)  # newest matching log for this process
                break

    def parse_result(path: str) -> str:
        """Derive Pass/Fail/Skipped/Blocked from 'res: <X>' in the log; else Unknown.

        'res: Error' is treated as Fail.
        """
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return "Unknown"
        if "res: Error" in content:
            return "Fail"
        for res in ("Pass", "Fail", "Skipped", "Blocked"):
            if f"res: {res}" in content:
                return res
        return "Unknown"

    logs = []
    for name in files:
        full = os.path.join(roku_test_dir, name)
        state = "running" if name in running_names else "completed"
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            mtime = 0
        logs.append(
            {
                "name": name,
                "state": state,
                "mtime": mtime,
                "result": parse_result(full),
            }
        )

    # Newest first
    logs.sort(key=lambda x: x["mtime"], reverse=True)
    return {"logs": logs}


@router.get("/v1/rokutest/log/view/{log_file}")
def view_roku_test_log(log_file: str) -> dict:
    """
    View a Roku test log file.
    """
    try:
        with open(os.path.join(roku_test_dir, log_file), "r") as f:
            return {"log": "\n".join(f.readlines())}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Log file '{log_file}' not found")


@router.get("/v1/rokutest/log/delete/{log_file}")
def delete_roku_test_log(log_file: str) -> dict:
    """
    Delete a Roku test log file and all its associated data files.
    """
    try:
        os.remove(os.path.join(roku_test_dir, log_file))
        return {"message": f"Log file '{log_file}' deleted"}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Log file '{log_file}' not found")


if __name__ == "__main__":
    print(_get_git_branch_name())
