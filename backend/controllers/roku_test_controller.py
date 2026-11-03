import asyncio
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import DATA_BASE_DIR, QATOOLS_ROOT, ROKU_TEST_LOG_PATH
from services.data_service import RUNCASE_STORE, DataServiceError

from . import logger

_CACHE_KEY = "roku_test_cache_data"
_CACHE_FIELDS = ("automation_id", "testrail_case_id")

device_conf_dir = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), os.path.join(QATOOLS_ROOT, "config", "device_conf")
    )
)
# Run-in-local log directory, under the data dir.
roku_test_dir = os.path.abspath(ROKU_TEST_LOG_PATH)

_LOG_TS_RE = re.compile(r"^(\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}\.\d{3})", re.M)
_LOG_TS_FMT = "%m-%d-%Y %H:%M:%S.%f"
_RAN_IN_RE = re.compile(r"^Ran \d+ tests? in ([\d.]+)s", re.M)

JOBS_PATH = os.path.abspath(
    os.path.join(QATOOLS_ROOT, "backend", "conf", "roku_test_jobs.json")
)
MAX_JOBS = 200
_jobs_lock = threading.Lock()

router = APIRouter()


def _load_jobs() -> list[dict]:
    try:
        with open(JOBS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_jobs(jobs: list[dict]) -> None:
    os.makedirs(os.path.dirname(JOBS_PATH), exist_ok=True)
    try:
        with open(JOBS_PATH, "w", encoding="utf-8") as f:
            json.dump(jobs[:MAX_JOBS], f, indent=2)
    except OSError as exc:
        logger.error("Error writing roku test jobs file: %s", exc)


def _add_job(job: dict) -> None:
    with _jobs_lock:
        jobs = _load_jobs()
        jobs.insert(0, job)
        _save_jobs(jobs)


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


def _decorate_job(job: dict) -> dict:
    """Attach live running state / result / elapsed time to a stored job."""
    job = dict(job)
    running = _pid_alive(int(job.get("pid") or 0))
    log_name = os.path.basename(job.get("log_file") or "")
    full = os.path.join(roku_test_dir, log_name) if log_name else ""
    job["log_file"] = log_name
    job["running"] = running
    job["status"] = "running" if running else "finished"
    job["result"] = "" if running else (_parse_result(full) if full else "Unknown")
    job["elapsed_time"] = _get_elapsed_time(full) if full else 0
    try:
        job["log_mtime"] = os.path.getmtime(full)
    except OSError:
        job["log_mtime"] = 0
    return job


def _parse_result(path: str) -> str:
    """Derive Pass/Fail/Skipped/Blocked from 'res: <X>' in the log; else Unknown.

    'res: Error' is treated as Fail.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return "Unknown"
    result = []
    for res in ("Pass", "Fail", "Skipped", "Blocked", "Error"):
        if f"res: {res}" in content:
            count = content.count(f"res: {res}")
            result_data = f"{res} {count}"
            if res == "Error":
                result_data = f"Fail {count}"
            result.append(result_data)
    return ",".join(result) if result else "Unknown"


def _get_elapsed_time(path: str) -> float:
    """Wall-clock seconds a run took, from its log file.

    Uses the first and last timestamped lines ("MM-DD-YYYY HH:MM:SS.mmm - ...");
    falls back to unittest's "Ran N tests in X.XXXs" footer, else 0.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return 0

    stamps = _LOG_TS_RE.findall(content)
    if len(stamps) >= 2:
        try:
            start = datetime.strptime(stamps[0], _LOG_TS_FMT)
            end = datetime.strptime(stamps[-1], _LOG_TS_FMT)
            elapsed = round((end - start).total_seconds(), 2)
            if elapsed >= 0:
                return elapsed
        except ValueError:
            pass

    ran = _RAN_IN_RE.findall(content)
    if ran:
        return round(sum(float(x) for x in ran), 2)
    return 0


def _load_cache() -> dict:
    """Read the roku_test_cache_data section through the data service."""
    try:
        return RUNCASE_STORE.get_dict(_CACHE_KEY)
    except DataServiceError as exc:
        logger.error("%s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _save_cache(cache: dict) -> None:
    """Persist the roku_test_cache_data section through the data service."""
    try:
        RUNCASE_STORE.set_section(_CACHE_KEY, cache)
    except DataServiceError as exc:
        logger.error("%s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _cache_list(field: str) -> list[str]:
    vals = _load_cache().get(field)
    return [str(v) for v in vals] if isinstance(vals, list) else []


def _cache_add(field: str, value: str) -> list[str]:
    """Prepend value to roku_test_cache_data.<field> (dedup, newest first)."""
    value = value.strip()
    if not value:
        return _cache_list(field)
    cache = _load_cache()
    vals = cache.get(field)
    vals = [str(v) for v in vals] if isinstance(vals, list) else []
    vals = [v for v in vals if v != value]
    vals.insert(0, value)
    cache[field] = vals[:100]  # keep the 100 most recent
    _save_cache(cache)
    return cache[field]


def _cache_delete(field: str, value: str) -> list[str]:
    cache = _load_cache()
    vals = cache.get(field)
    if not isinstance(vals, list):
        return []
    kept = [str(v) for v in vals if str(v) != value]
    if len(kept) == len(vals):
        raise HTTPException(status_code=404, detail=f"'{value}' not found in {field}")
    cache[field] = kept
    _save_cache(cache)
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
    # setsid puts the test in its own session/process group so that stopping it
    # can signal the whole group (roku_test spawns child processes) without ever
    # touching the backend's own group.
    shell_cmd = f"(setsid {cmd} > {shlex.quote(log_file)} 2>&1 & echo $!)"
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

    # Track the run as a job so several runs can be shown / stopped separately.
    job = {
        "id": uuid.uuid4().hex[:12],
        "device": device,
        "automation_id": automated_test_id,
        "testrail_case_id": testrail_case_id,
        "repeat": repeat,
        "pid": pid,
        "log_file": os.path.basename(log_file),
        "command": cmd,
        "started_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    try:
        _add_job(job)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to persist roku test job: %s", exc)

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
        "job": _decorate_job(job),
    }


@router.get("/v1/rokutest/jobs")
def list_roku_test_jobs(limit: int = 50) -> dict:
    """List tracked roku_test runs (newest first) with live running state."""
    with _jobs_lock:
        jobs = _load_jobs()
    return {"jobs": [_decorate_job(j) for j in jobs[: max(1, limit)]]}


@router.delete("/v1/rokutest/jobs")
def clear_roku_test_jobs() -> dict:
    """Clear all finished jobs. Running jobs are kept (stop them first).

    Log files are never touched — only the tracking entries are dropped.
    """
    with _jobs_lock:
        jobs = _load_jobs()
        kept = [j for j in jobs if _pid_alive(int(j.get("pid") or 0))]
        removed = len(jobs) - len(kept)
        if removed:
            _save_jobs(kept)
    logger.info("Cleared %s finished roku test job(s)", removed)
    return {
        "message": f"Cleared {removed} finished job(s)",
        "removed": removed,
        "kept": len(kept),
    }


@router.delete("/v1/rokutest/jobs/{job_id}")
def delete_roku_test_job(job_id: str) -> dict:
    """Forget a job (log file untouched). Running jobs must be stopped first."""
    with _jobs_lock:
        jobs = _load_jobs()
        target = next((j for j in jobs if j.get("id") == job_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        if _pid_alive(int(target.get("pid") or 0)):
            raise HTTPException(
                status_code=400, detail="Job is still running; stop it first"
            )
        _save_jobs([j for j in jobs if j.get("id") != job_id])
    return {"message": f"Job '{job_id}' removed"}


@router.post("/v1/rokutest/jobs/{job_id}/stop")
def stop_roku_test_job(job_id: str) -> dict:
    """Stop one tracked run (by job id), leaving the other runs alone."""
    with _jobs_lock:
        job = next((j for j in _load_jobs() if j.get("id") == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    res = stop_roku_test(int(job.get("pid") or 0))
    res["id"] = job_id
    return res


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


def _signal_run(pid: int, sig: int) -> bool:
    """Signal the test's whole process group when it is safe to do so.

    Runs are started with `setsid`, so their process group is distinct from the
    backend's; only then is killpg used (otherwise fall back to a single pid)
    to make sure we never signal the server itself.
    """
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return False
    try:
        if pgid != os.getpgid(0):
            os.killpg(pgid, sig)
        else:
            os.kill(pid, sig)
    except ProcessLookupError:
        return False
    return True


@router.get("/v1/rokutest/stop/{pid}")
def stop_roku_test(pid: int) -> dict:
    """
    Stop a Roku test (and its child processes).
    """
    if pid <= 0:
        return {"pid": pid, "status": "not_running"}
    if not _signal_run(pid, signal.SIGTERM):
        return {"pid": pid, "status": "not_running"}

    # Give it a moment to exit; escalate to SIGKILL so the log list flips to
    # "completed" instead of staying stuck as "running".
    for _ in range(20):  # up to ~2s
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
    else:
        _signal_run(pid, signal.SIGKILL)

    logger.info("Stopped roku test pid=%s", pid)
    return {"pid": pid, "status": "stopped"}


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

    # Primary source of truth: the tracked jobs (pid -> log file). Several runs
    # can be live at once, so every job whose pid is still alive marks its own
    # log as running.
    with _jobs_lock:
        stored_jobs = _load_jobs()
    running_names: set[str] = {
        os.path.basename(j.get("log_file") or "")
        for j in stored_jobs
        if _pid_alive(int(j.get("pid") or 0))
    }
    running_names.discard("")
    known_names = {os.path.basename(j.get("log_file") or "") for j in stored_jobs}

    # Fallback for runs started before job tracking existed (or started outside
    # this backend): the log file name is NOT in the process args (output is
    # shell-redirected), so match via automation_id (--filter) + device
    # (-d device_conf/<device>.json).
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
    candidates = sorted(
        files,
        key=lambda n: (
            os.path.getmtime(os.path.join(roku_test_dir, n))
            if os.path.exists(os.path.join(roku_test_dir, n))
            else 0
        ),
        reverse=True,
    )
    for cmd in running_cmds:
        for name in candidates:
            parsed = _parse_name(name)
            if not parsed:
                continue
            automation_id, device = parsed
            if name in known_names:
                continue  # tracked jobs already decided this log's state
            if (
                automation_id
                and device
                and automation_id in cmd
                and f"{device}.json" in cmd
            ):
                running_names.add(name)  # newest matching log for this process
                break

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
                "result": _parse_result(full),
                "elapsed_time": _get_elapsed_time(full),
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


@router.get("/v1/rokutest/log/download/{log_file}")
def download_roku_test_log(log_file: str) -> FileResponse:
    """Download a Roku test log file as an attachment."""
    # basename() keeps the request inside roku_test_dir (no path traversal).
    name = os.path.basename(log_file or "")
    path = os.path.join(roku_test_dir, name)
    if not name or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Log file '{log_file}' not found")
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=name,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


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
