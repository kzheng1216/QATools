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
from datetime import UTC, datetime, timedelta

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
# Finished entries kept in the jobs file; queued / running ones are never
# dropped (they are the queue itself).
MAX_JOBS = 200
_jobs_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Per-device run queues
#
# Every device has its own FIFO queue and runs AT MOST ONE case at a time;
# different devices still run in parallel. The jobs file is the single source
# of truth (so a backend restart resumes the queues), and one worker thread per
# busy device starts the next case as soon as the current one exits.
# ---------------------------------------------------------------------------
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"
STATUS_STOPPED = "stopped"
STATUS_ERROR = "error"
# Statuses that keep a job in its device queue.
ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING)
# How often a worker re-checks whether its running case has exited.
QUEUE_POLL_SECONDS = 1.0

_queues_lock = threading.Lock()
_queue_workers: dict[str, threading.Thread] = {}

router = APIRouter()


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _load_jobs() -> list[dict]:
    try:
        with open(JOBS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _trim_jobs(jobs: list[dict]) -> list[dict]:
    """Cap the history at MAX_JOBS finished entries, keeping every active job.

    Plain truncation could drop a queued job (and with it a case the user is
    still waiting for), so only finished entries are discarded.
    """
    kept: list[dict] = []
    finished = 0
    for job in jobs:
        if _stored_status(job) in ACTIVE_STATUSES:
            kept.append(job)
            continue
        if finished < MAX_JOBS:
            kept.append(job)
            finished += 1
    return kept


def _save_jobs(jobs: list[dict]) -> None:
    """Persist the jobs file. Callers must hold _jobs_lock."""
    os.makedirs(os.path.dirname(JOBS_PATH), exist_ok=True)
    try:
        # Write-then-rename: a crash mid-write would otherwise leave a
        # truncated file and lose every queued job.
        tmp = f"{JOBS_PATH}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_trim_jobs(jobs), f, indent=2)
        # Keep the original file mode (the fresh temp file would reset it).
        try:
            os.chmod(tmp, os.stat(JOBS_PATH).st_mode & 0o7777)
        except OSError:
            pass
        os.replace(tmp, JOBS_PATH)
    except OSError as exc:
        logger.error("Error writing roku test jobs file: %s", exc)


def _proc_stat(pid: int) -> tuple[str, int] | None:
    """(state, starttime) of a pid from /proc, or None when it is gone."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
            data = fh.read()
    except OSError:
        return None
    # The comm field can contain spaces and parens, so parse after its ')'.
    try:
        fields = data[data.rindex(")") + 1 :].split()
        return fields[0], int(fields[19])
    except (ValueError, IndexError):
        return None


def _pid_alive(pid: int) -> bool:
    """Whether pid is a live process (a zombie counts as finished).

    Runs are started detached, so a not-yet-reaped child would still answer
    kill(0) and could block its device queue forever.
    """
    if not pid or pid <= 0:
        return False
    stat = _proc_stat(pid)
    if stat is not None:
        return stat[0] != "Z"
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


def _job_process_alive(job: dict) -> bool:
    """Whether the job's own process is still running.

    Also compares the recorded process start time, so a recycled pid (e.g.
    after a container restart) can't be mistaken for the original run and
    stall the device queue.
    """
    pid = int(job.get("pid") or 0)
    if not _pid_alive(pid):
        return False
    want = job.get("proc_start")
    if want in (None, ""):
        return True
    stat = _proc_stat(pid)
    if stat is None:
        return True
    return int(want) == stat[1]


def _stored_status(job: dict) -> str:
    """Lifecycle status of a stored job (jobs written before the queue existed
    have no 'status' field, so fall back to their pid)."""
    status = str(job.get("status") or "")
    if status:
        return status
    return STATUS_RUNNING if _job_process_alive(job) else STATUS_FINISHED


def _queue_key(job: dict) -> tuple[int, str]:
    """Sort key giving a device's queue its order (enqueue order by default)."""
    return (int(job.get("seq") or 0), str(job.get("queued_at") or ""))


def _next_seq(jobs: list[dict]) -> int:
    return max((int(j.get("seq") or 0) for j in jobs), default=-1) + 1


def _queue_positions(jobs: list[dict]) -> dict[str, int]:
    """job id -> place in its device queue: 0 = running now, 1..n = waiting."""
    positions: dict[str, int] = {}
    by_device: dict[str, list[dict]] = {}
    for job in jobs:
        status = _stored_status(job)
        if status == STATUS_RUNNING:
            positions[str(job.get("id") or "")] = 0
        elif status == STATUS_QUEUED:
            by_device.setdefault(str(job.get("device") or ""), []).append(job)
    for queued in by_device.values():
        for place, job in enumerate(sorted(queued, key=_queue_key), start=1):
            positions[str(job.get("id") or "")] = place
    return positions


def _decorate_job(job: dict, positions: dict[str, int] | None = None) -> dict:
    """Attach live state / queue place / result / elapsed time to a stored job."""
    job = dict(job)
    status = _stored_status(job)
    # The worker persists this a moment later; report it right away.
    if status == STATUS_RUNNING and not _job_process_alive(job):
        status = STATUS_FINISHED
    running = status == STATUS_RUNNING
    queued = status == STATUS_QUEUED
    log_name = os.path.basename(job.get("log_file") or "")
    full = os.path.join(roku_test_dir, log_name) if log_name else ""
    job["log_file"] = log_name
    job["running"] = running
    job["status"] = status
    job["queue_position"] = (positions or {}).get(str(job.get("id") or ""), -1)
    if running or queued:
        job["result"] = ""
    else:
        job["result"] = _parse_result(full) if full else "Unknown"
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


def _spawn_roku_test(cmd: str, log_file: str) -> int:
    """Start `cmd` detached, redirect its output to log_file, return its pid."""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    # setsid puts the test in its own session/process group so that stopping it
    # can signal the whole group (roku_test spawns child processes) without ever
    # touching the backend's own group.
    shell_cmd = f"(setsid {cmd} > {shlex.quote(log_file)} 2>&1 & echo $!)"
    process = subprocess.Popen(
        shell_cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    stdout, _ = process.communicate()
    return int((stdout or b"").decode().strip())


def _get_git_branch_name() -> str:
    """Get the current git branch name."""
    cmd = "cd ~/automated_tests && git rev-parse --abbrev-ref HEAD"
    process = subprocess.Popen(
        cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    stdout, _ = process.communicate()
    return stdout.decode().strip()


def _build_cmd(job: dict) -> tuple[str, str]:
    """(command, log file path) for a queued job, named at start time."""
    device = str(job.get("device") or "")
    automation_id = str(job.get("automation_id") or "")
    testrail_case_id = str(job.get("testrail_case_id") or "")
    repeat = int(job.get("repeat") or 0)

    timestamp = datetime.now(UTC)
    log_file = ""
    # A queue starts cases back to back, so two runs of the same case can land
    # in the same second; bump the stamp rather than overwrite an older log.
    for _ in range(60):
        candidate = os.path.join(
            roku_test_dir,
            f"roku_test__{automation_id}__{testrail_case_id}__{device}__{repeat}"
            f"__{timestamp.strftime('%Y%m%d_%H%M%S')}.log",
        )
        if not os.path.exists(candidate):
            log_file = candidate
            break
        timestamp += timedelta(seconds=1)
    else:
        log_file = candidate

    repeat_arg = f"--repeat {repeat}" if repeat > 0 else ""
    cmd = (
        f"{_roku_test_bin()} -d {device_conf_dir}/{device}.json {repeat_arg} "
        f"--allow dangerous --allow duration-hours --filter {shlex.quote(automation_id)} "
        f"{os.path.expanduser('~/automated_tests/tests')}"
    )
    return cmd, log_file


def _advance_device(device: str) -> bool:
    """Move a device's queue forward one step.

    Reaps the finished run (if any), then starts the oldest waiting case when
    the device is idle. Returns True while the device still has work, so its
    worker knows whether to keep polling.

    Holds _jobs_lock across the spawn: only one case may ever be starting on a
    device, and the job must never be observable as running without its pid.
    """
    with _jobs_lock:
        jobs = _load_jobs()
        mine = [j for j in jobs if j.get("device") == device]
        dirty = False

        # 1. Reap: a job recorded as running whose process is gone is finished.
        running = None
        for job in mine:
            if _stored_status(job) != STATUS_RUNNING:
                continue
            if _job_process_alive(job):
                running = job
            else:
                job["status"] = STATUS_FINISHED
                job["finished_at"] = _utc_now()
                dirty = True
                logger.info(
                    "Roku test finished: device='%s' automation_id='%s' pid=%s",
                    device,
                    job.get("automation_id"),
                    job.get("pid"),
                )

        queued = sorted(
            (j for j in mine if _stored_status(j) == STATUS_QUEUED), key=_queue_key
        )

        # 2. Device still busy: nothing to start yet.
        if running is not None:
            if dirty:
                _save_jobs(jobs)
            return True

        if not queued:
            if dirty:
                _save_jobs(jobs)
            return False

        # 3. Device idle: start the case at the head of its queue.
        job = queued[0]
        cmd, log_file = _build_cmd(job)
        try:
            pid = _spawn_roku_test(cmd, log_file)
        except (OSError, ValueError) as exc:
            job["status"] = STATUS_ERROR
            job["error"] = f"Failed to start: {exc}"
            job["finished_at"] = _utc_now()
            _save_jobs(jobs)
            logger.error(
                "Failed to start roku test on device '%s' (%s): %s",
                device,
                job.get("automation_id"),
                exc,
            )
            # Don't wedge the queue on one bad case.
            return len(queued) > 1

        stat = _proc_stat(pid)
        job["pid"] = pid
        job["log_file"] = os.path.basename(log_file)
        job["command"] = cmd
        job["status"] = STATUS_RUNNING
        job["proc_start"] = stat[1] if stat else ""
        job["started_at"] = _utc_now()
        _save_jobs(jobs)

    logger.info(
        "Roku test started: device='%s' automated_test_id='%s' testrail_case_id='%s' pid=%s log=%s",
        device,
        job.get("automation_id"),
        job.get("testrail_case_id"),
        pid,
        log_file,
    )
    return True


def _queue_worker(device: str) -> None:
    """Drain one device's queue, one case at a time."""
    try:
        while True:
            try:
                busy = _advance_device(device)
            except Exception:  # noqa: BLE001
                logger.exception("Roku test queue worker error on device %s", device)
                busy = True  # back off, then retry
            if not busy:
                # Exit only if nothing slipped in while we were deciding
                # (enqueue takes _queues_lock to (re)start the worker).
                with _queues_lock:
                    if not _device_has_active(device):
                        _queue_workers.pop(device, None)
                        return
            time.sleep(QUEUE_POLL_SECONDS)
    finally:
        with _queues_lock:
            if _queue_workers.get(device) is threading.current_thread():
                _queue_workers.pop(device, None)


def _device_has_active(device: str) -> bool:
    with _jobs_lock:
        return any(
            j.get("device") == device and _stored_status(j) in ACTIVE_STATUSES
            for j in _load_jobs()
        )


def list_running_runs() -> list[dict]:
    """The cases executing right now, across all devices.

    Exposed for other controllers (the branch switch is blocked while a case is
    running, since every run reads the test files out of the shared
    automated_tests working tree).
    """
    with _jobs_lock:
        jobs = _load_jobs()
    return [
        {
            "id": j.get("id", ""),
            "device": j.get("device", ""),
            "automation_id": j.get("automation_id", ""),
            "pid": int(j.get("pid") or 0),
        }
        for j in jobs
        if _stored_status(j) == STATUS_RUNNING and _job_process_alive(j)
    ]


def list_queued_runs() -> list[dict]:
    """The cases waiting in a device queue (they have not started yet)."""
    with _jobs_lock:
        jobs = _load_jobs()
    return [
        {
            "id": j.get("id", ""),
            "device": j.get("device", ""),
            "automation_id": j.get("automation_id", ""),
        }
        for j in jobs
        if _stored_status(j) == STATUS_QUEUED
    ]


def _ensure_worker(device: str) -> None:
    """Make sure a worker thread is draining this device's queue."""
    with _queues_lock:
        thread = _queue_workers.get(device)
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(
            target=_queue_worker,
            args=(device,),
            name=f"rokutest-queue-{device}",
            daemon=True,
        )
        _queue_workers[device] = thread
        thread.start()


def _resume_queues() -> None:
    """Restart the queue workers for every device with unfinished work.

    The jobs file survives a backend restart, so cases queued before it still
    run, and runs that outlived the backend are adopted (not restarted).
    """
    try:
        with _jobs_lock:
            devices = {
                str(j.get("device") or "")
                for j in _load_jobs()
                if _stored_status(j) in ACTIVE_STATUSES
            }
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read roku test jobs while resuming queues")
        return
    for device in sorted(d for d in devices if d):
        logger.info("Resuming roku test queue for device %s", device)
        _ensure_worker(device)


@router.post("/v1/rokutest/run")
def run_roku_test(
    device: str,
    automated_test_id: str,
    testrail_case_id: str,
    repeat: int = 0,
) -> dict:
    """Queue a Roku test case on a device.

    Each device has its own FIFO queue and runs one case at a time: the job
    starts immediately when the device is idle, otherwise it waits behind the
    cases already queued for that device. Different devices run in parallel.
    """
    if not os.path.isfile(os.path.join(device_conf_dir, f"{device}.json")):
        raise HTTPException(status_code=400, detail=f"Unknown device '{device}'")

    job = {
        "id": uuid.uuid4().hex[:12],
        "device": device,
        "automation_id": automated_test_id,
        "testrail_case_id": testrail_case_id,
        "repeat": repeat,
        "pid": 0,
        "log_file": "",
        "command": "",
        "status": STATUS_QUEUED,
        "queued_at": _utc_now(),
        "started_at": "",
    }
    logger.info(
        "Queue roku test: device='%s' automated_test_id='%s' testrail_case_id='%s' repeat=%s",
        device,
        automated_test_id,
        testrail_case_id,
        repeat,
    )
    with _jobs_lock:
        jobs = _load_jobs()
        job["seq"] = _next_seq(jobs)
        jobs.insert(0, job)
        _save_jobs(jobs)

    # Start it right away when the device is idle, so the response can carry
    # the pid / log file of a run that is live by the time the UI gets it.
    _advance_device(device)
    _ensure_worker(device)

    # Remember the inputs in the history cache (best-effort; never fail the run).
    try:
        _cache_add("automation_id", automated_test_id)
        _cache_add("testrail_case_id", testrail_case_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to update roku_test input cache: %s", exc)

    with _jobs_lock:
        jobs = _load_jobs()
        positions = _queue_positions(jobs)
        stored = next((j for j in jobs if j.get("id") == job["id"]), job)
    current = _decorate_job(stored, positions)
    position = current["queue_position"]
    queued = current["status"] == STATUS_QUEUED

    if queued:
        msg = (
            f"Case '{automated_test_id}' queued on device '{device}' at position "
            f"{position} (the device is busy; it runs when the cases ahead finish)"
        )
    else:
        msg = (
            f"Roku test with device '{device}', automated_test_id "
            f"'{automated_test_id}' and testrail_case_id '{testrail_case_id}' "
            f"and repeat '{repeat}' started"
        )
    return {
        "message": msg,
        "command": current.get("command", ""),
        "log_file": current.get("log_file", ""),
        "pid": current.get("pid", 0),
        "queued": queued,
        "queue_position": position,
        "job": current,
    }


@router.get("/v1/rokutest/queues")
def list_roku_test_queues() -> dict:
    """The per-device queues: each device's running case + the cases waiting."""
    with _jobs_lock:
        jobs = _load_jobs()
        positions = _queue_positions(jobs)
    queues: dict[str, dict] = {}
    for job in jobs:
        if _stored_status(job) not in ACTIVE_STATUSES:
            continue
        device = str(job.get("device") or "")
        entry = queues.setdefault(device, {"device": device, "running": None, "queued": []})
        decorated = _decorate_job(job, positions)
        if decorated["status"] == STATUS_RUNNING:
            entry["running"] = decorated
        else:
            entry["queued"].append(decorated)
    for entry in queues.values():
        entry["queued"].sort(key=lambda j: j["queue_position"])
        entry["pending"] = len(entry["queued"])
    return {"queues": [queues[d] for d in sorted(queues)]}


@router.post("/v1/rokutest/queues/{device}/move/{job_id}")
def move_roku_test_queue_job(device: str, job_id: str, direction: str) -> dict:
    """Reorder a waiting case inside its device queue ('up' or 'down')."""
    if direction not in ("up", "down"):
        raise HTTPException(
            status_code=400, detail="direction must be 'up' or 'down'"
        )
    with _jobs_lock:
        jobs = _load_jobs()
        queued = sorted(
            (
                j
                for j in jobs
                if j.get("device") == device and _stored_status(j) == STATUS_QUEUED
            ),
            key=_queue_key,
        )
        idx = next(
            (i for i, j in enumerate(queued) if j.get("id") == job_id), None
        )
        if idx is None:
            raise HTTPException(
                status_code=404,
                detail=f"No queued job '{job_id}' for device '{device}'",
            )
        swap = idx - 1 if direction == "up" else idx + 1
        if swap < 0 or swap >= len(queued):
            raise HTTPException(
                status_code=400, detail=f"Job is already {'first' if swap < 0 else 'last'}"
            )
        # Swapping the sort keys moves the job without renumbering the queue.
        a, b = queued[idx], queued[swap]
        a["seq"], b["seq"] = b.get("seq", 0), a.get("seq", 0)
        a["queued_at"], b["queued_at"] = (
            b.get("queued_at", ""),
            a.get("queued_at", ""),
        )
        _save_jobs(jobs)
        positions = _queue_positions(jobs)
    logger.info("Moved queued job %s %s on device %s", job_id, direction, device)
    return {
        "message": f"Job '{job_id}' moved {direction}",
        "queue_position": positions.get(job_id, -1),
    }


@router.delete("/v1/rokutest/queues/{device}")
def clear_roku_test_queue(device: str) -> dict:
    """Drop every WAITING case of a device. A running case is left alone."""
    with _jobs_lock:
        jobs = _load_jobs()
        kept = [
            j
            for j in jobs
            if not (
                j.get("device") == device and _stored_status(j) == STATUS_QUEUED
            )
        ]
        removed = len(jobs) - len(kept)
        if removed:
            _save_jobs(kept)
    logger.info("Cleared %s queued job(s) on device %s", removed, device)
    return {
        "message": f"Cleared {removed} queued case(s) on '{device}'",
        "removed": removed,
    }


@router.get("/v1/rokutest/jobs")
def list_roku_test_jobs(limit: int = 50) -> dict:
    """List tracked roku_test runs (newest first) with live running state.

    Active (queued / running) jobs are always included, whatever the limit, so
    the UI can never lose sight of a queue.
    """
    with _jobs_lock:
        jobs = _load_jobs()
        positions = _queue_positions(jobs)
    limit = max(1, limit)
    head = jobs[:limit]
    seen = {id(j) for j in head}
    extra = [
        j for j in jobs[limit:] if _stored_status(j) in ACTIVE_STATUSES and id(j) not in seen
    ]
    return {"jobs": [_decorate_job(j, positions) for j in head + extra]}


@router.delete("/v1/rokutest/jobs")
def clear_roku_test_jobs() -> dict:
    """Clear all finished jobs. Queued / running jobs are kept (stop them first).

    Log files are never touched — only the tracking entries are dropped.
    """
    with _jobs_lock:
        jobs = _load_jobs()
        kept = [j for j in jobs if _stored_status(j) in ACTIVE_STATUSES]
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
    """Forget a job (log file untouched).

    A QUEUED job is cancelled (dropped from its device queue); a RUNNING job
    must be stopped first.
    """
    with _jobs_lock:
        jobs = _load_jobs()
        target = next((j for j in jobs if j.get("id") == job_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        if _stored_status(target) == STATUS_RUNNING:
            raise HTTPException(
                status_code=400, detail="Job is still running; stop it first"
            )
        was_queued = _stored_status(target) == STATUS_QUEUED
        _save_jobs([j for j in jobs if j.get("id") != job_id])
    if was_queued:
        logger.info("Cancelled queued roku test job %s", job_id)
        return {"message": f"Queued job '{job_id}' cancelled"}
    return {"message": f"Job '{job_id}' removed"}


@router.post("/v1/rokutest/jobs/{job_id}/stop")
def stop_roku_test_job(job_id: str) -> dict:
    """Stop one tracked run (by job id), leaving the other runs alone.

    The device queue is NOT paused: the next case waiting for that device
    starts right after. Use DELETE /v1/rokutest/queues/{device} to drop the
    rest of the queue.
    """
    with _jobs_lock:
        job = next((j for j in _load_jobs() if j.get("id") == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    if _stored_status(job) == STATUS_QUEUED:
        raise HTTPException(
            status_code=400,
            detail="Job has not started yet; delete it to cancel the queued case",
        )
    res = stop_roku_test(int(job.get("pid") or 0))
    res["id"] = job_id
    # Record it as stopped so the worker doesn't relabel it as finished, then
    # let the device move on to the next queued case.
    device = str(job.get("device") or "")
    with _jobs_lock:
        jobs = _load_jobs()
        stored = next((j for j in jobs if j.get("id") == job_id), None)
        if stored is not None and _stored_status(stored) == STATUS_RUNNING:
            stored["status"] = STATUS_STOPPED
            stored["finished_at"] = _utc_now()
            _save_jobs(jobs)
    if device:
        _advance_device(device)
        _ensure_worker(device)
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
        if _stored_status(j) == STATUS_RUNNING and _job_process_alive(j)
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


# Cases queued before a backend restart keep their place and still run.
_resume_queues()


if __name__ == "__main__":
    print(_get_git_branch_name())
