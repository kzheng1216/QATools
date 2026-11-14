from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import QATOOLS_ROOT

from .device_controller import view_device

ACTIVATE_DIR = os.path.abspath(os.path.join(QATOOLS_ROOT, "5_activate"))
RUN_ACTIVATE_SCRIPT_CONNECTED = os.path.join(
    ACTIVATE_DIR, "factory_reset_and_activate.py"
)
RUN_ACTIVATE_SCRIPT_UNCONNECTED = os.path.join(
    ACTIVATE_DIR, "factory_reset_and_unconnected_mode.py"
)
RUN_PRECHECK_SCRIPT = os.path.join(ACTIVATE_DIR, "precheck_connection.py")
ACTIVATE_ACCOUNT_YAML = os.path.abspath(
    os.path.join(QATOOLS_ROOT, "config", "activate_account.yml")
)
ACTIVATE_ACCOUNT_FALLBACK = "trc_gctest_us2@roku.com"
LOG_DIR = os.path.join(ACTIVATE_DIR, "logs")
JOBS_PATH = os.path.abspath(
    os.path.join(QATOOLS_ROOT, "backend", "conf", "activate_jobs.json")
)

PRECHECK_TIMEOUT_SECONDS = 90
MAX_JOBS = 200

os.makedirs(LOG_DIR, exist_ok=True)

router = APIRouter()

MODE_CONNECTED = "connected"
MODE_UNCONNECTED = "unconnected"
MODES = (MODE_CONNECTED, MODE_UNCONNECTED)

# Conversion log file name:  {mode}__activate__{device_name}__{YYYYmmdd_HHMMSS}.log
#
# The fields are "__"-delimited so that a device name containing single
# underscores (UK_KIT_5616, US_KIT-428_athens_wired, ...) stays unambiguous.
# Logs written before that rule used single underscores throughout and are
# migrated on startup by _migrate_log_names().
_LEGACY_LOG_RE = re.compile(
    r"^(?P<mode>connected|unconnected)_activate_(?P<device>.+)_(?P<ts>\d{8}_\d{6})\.log$"
)

_jobs_lock = threading.Lock()


def _log_name(mode: str, device_name: str, timestamp: str) -> str:
    """Build a conversion log file name in the canonical "__" format."""
    return f"{mode}__activate__{device_name}__{timestamp}.log"


def _parse_log_name(log_file: str) -> dict:
    """Pull {mode, device_name, timestamp} back out of a log file name.

    Understands both the canonical "__" format and the legacy single-underscore
    one (logs that could not be migrated, e.g. a name collision).
    """
    name = os.path.basename(log_file or "")
    base = name.removesuffix(".log")
    parts = base.split("__")
    if len(parts) == 4 and parts[1] == "activate":
        return {"mode": parts[0], "device_name": parts[2], "timestamp": parts[3]}
    legacy = _LEGACY_LOG_RE.match(name)
    if legacy:
        return {
            "mode": legacy.group("mode"),
            "device_name": legacy.group("device"),
            "timestamp": legacy.group("ts"),
        }
    return {"mode": "", "device_name": "", "timestamp": ""}


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
        logger.error("Error writing activate jobs file: %s", exc)


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


def _log_path(log_file: str) -> str:
    """Resolve a log file name inside LOG_DIR (no path traversal)."""
    name = os.path.basename(log_file or "")
    if not name:
        raise HTTPException(status_code=400, detail="Missing log file name")
    return os.path.join(LOG_DIR, name)


def _migrate_log_names() -> dict:
    """Rename legacy single-underscore conversion logs to the "__" format.

    {mode}_activate_{device}_{ts}.log  ->  {mode}__activate__{device}__{ts}.log

    Runs once at import. The job entries in activate_jobs.json are rewritten to
    point at the new names, so View / Delete / Result keep working for history.
    A pre-existing target is never overwritten (the old file is left in place).
    """
    renamed: dict[str, str] = {}
    skipped: list[str] = []
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        names = os.listdir(LOG_DIR)
    except OSError as exc:
        logger.error("Cannot list %s for log migration: %s", LOG_DIR, exc)
        return {"renamed": {}, "skipped": []}

    for name in sorted(names):
        match = _LEGACY_LOG_RE.match(name)
        if not match:
            continue  # already "__", or the shared activate.log / rotations
        new_name = _log_name(
            match.group("mode"), match.group("device"), match.group("ts")
        )
        if new_name == name:
            continue
        src = os.path.join(LOG_DIR, name)
        dst = os.path.join(LOG_DIR, new_name)
        if os.path.exists(dst):
            logger.warning(
                "Skipping log migration for %s: %s already exists", name, new_name
            )
            skipped.append(name)
            continue
        try:
            os.rename(src, dst)
        except OSError as exc:
            logger.error("Failed to rename log %s -> %s: %s", name, new_name, exc)
            skipped.append(name)
            continue
        renamed[name] = new_name

    if renamed:
        # Re-point the tracked jobs at the renamed files.
        try:
            with _jobs_lock:
                jobs = _load_jobs()
                changed = False
                for job in jobs:
                    old = os.path.basename(job.get("log_file") or "")
                    if old in renamed:
                        job["log_file"] = renamed[old]
                        changed = True
                if changed:
                    _save_jobs(jobs)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to update job log_file references")
        logger.info(
            "Migrated %s activate log file name(s) to the '__' format", len(renamed)
        )
    return {"renamed": renamed, "skipped": skipped}


def _job_result(log_file: str) -> str:
    """Derive a coarse outcome from the job's log file."""
    path = _log_path(log_file)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return "Unknown"
    low = content.lower()
    if "guided setup complete" in low or "activation successful" in low:
        return "Success"
    if "'success': true" in low or '"success": true' in low:
        return "Success"
    if "traceback (most recent call last)" in low or "error" in low:
        return "Failed"
    return "Unknown"


def _decorate(job: dict) -> dict:
    """Return the job with live running state / result / mtime attached."""
    pid = int(job.get("pid") or 0)
    running = _pid_alive(pid)
    job = dict(job)
    job["running"] = running
    job["status"] = "running" if running else "finished"
    job["result"] = "" if running else _job_result(job.get("log_file", ""))
    try:
        job["log_mtime"] = os.path.getmtime(_log_path(job.get("log_file", "")))
    except (OSError, HTTPException):
        job["log_mtime"] = 0
    # Epoch form of started_at, so the table can sort on it (the string is a
    # display format, not sortable across months).
    job["started_epoch"] = _started_epoch(job)
    return job


def _started_epoch(job: dict) -> float:
    """started_at as a UTC epoch (0 when it cannot be parsed)."""
    raw = str(job.get("started_at") or "").replace(" UTC", "").strip()
    if raw:
        try:
            return (
                datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=UTC)
                .timestamp()
            )
        except ValueError:
            pass
    # Fall back to the timestamp embedded in the log file name.
    stamp = _parse_log_name(job.get("log_file", "")).get("timestamp", "")
    if stamp:
        try:
            return (
                datetime.strptime(stamp, "%Y%m%d_%H%M%S")
                .replace(tzinfo=UTC)
                .timestamp()
            )
        except ValueError:
            pass
    return 0


def _activate_accounts() -> dict:
    """country -> activation email mapping, re-read from activate_account.yml."""
    try:
        with open(ACTIVATE_ACCOUNT_YAML, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, ValueError) as exc:
        logger.error("Error reading %s: %s", ACTIVATE_ACCOUNT_YAML, exc)
        return {}
    accounts = data.get("activate_account") or {}
    return accounts if isinstance(accounts, dict) else {}


def _default_email(device_name: str) -> str:
    """Default activation email for a device.

    Mirrors config/device_conf/device_info.py: the first country key contained
    in the device name wins, otherwise DEFAULT.
    """
    accounts = _activate_accounts()
    upper = (device_name or "").upper()
    for key, email in accounts.items():
        if str(key).upper() == "DEFAULT":
            continue
        if str(key).upper() in upper:
            return str(email)
    return str(accounts.get("DEFAULT") or ACTIVATE_ACCOUNT_FALLBACK)


def _device_ip(device_name: str) -> str:
    """IP address of a device from its device_conf json (404 if unknown)."""
    data = view_device(device_name)
    ip = ((data.get("roku") or {}) if isinstance(data, dict) else {}).get("ip_address")
    if not ip:
        raise HTTPException(
            status_code=400, detail=f"Device '{device_name}' has no roku.ip_address"
        )
    return str(ip)


def _run_precheck(ip_address: str) -> dict:
    """Run precheck_connection.py for an ip; returns its parsed JSON output."""
    cmd = f"python3 {shlex.quote(RUN_PRECHECK_SCRIPT)} {shlex.quote(ip_address)}"
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=PRECHECK_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"Precheck timed out after {PRECHECK_TIMEOUT_SECONDS}s"}

    out = (proc.stdout or "").strip()
    # The script prints a single JSON object as its LAST line.
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return {"error": (proc.stderr or out or "Precheck produced no output").strip()}


def _precheck_device(device_name: str, mode: str) -> dict:
    """Probe one device and decide whether converting to `mode` is allowed.

    Rule: a device connected over wireless (wifi) cannot be converted to
    Unconnected Mode.
    """
    if mode not in MODES:
        raise HTTPException(status_code=400, detail=f"Unknown mode '{mode}'")

    result: dict = {
        "device_name": device_name,
        "mode": mode,
        "ip_address": "",
        "connection_type": "",
        "is_linked": None,
        "allowed": False,
        "reason": "",
    }
    try:
        result["ip_address"] = _device_ip(device_name)
    except HTTPException as exc:
        result["reason"] = str(exc.detail)
        return result

    probe = _run_precheck(result["ip_address"])
    if probe.get("error"):
        result["reason"] = f"Precheck failed: {probe['error']}"
        return result

    connection_type = str(probe.get("connection_type") or "")
    result["connection_type"] = connection_type
    result["is_linked"] = probe.get("is_linked")

    is_wireless = connection_type.lower() in ("wifi", "wireless", "wlan")
    if mode == MODE_UNCONNECTED and is_wireless:
        result["reason"] = (
            f"Device is on wireless ({connection_type}); converting to Unconnected "
            "Mode is not allowed. Switch the device to a wired connection first."
        )
        return result

    result["allowed"] = True
    result["reason"] = "OK"
    return result


class ActivateBody(BaseModel):
    device_name: str = Field(..., description="Device name to activate.")


class PrecheckBody(BaseModel):
    device_names: list[str] = Field(..., description="Device names to precheck.")
    mode: str = Field(
        default=MODE_CONNECTED,
        description="Target mode: 'connected' or 'unconnected'.",
    )


class StartBody(BaseModel):
    device_names: list[str] = Field(
        ..., description="One or more device names to convert (run in parallel)."
    )
    mode: str = Field(..., description="Target mode: 'connected' or 'unconnected'.")
    skip_precheck: bool = Field(
        default=False, description="Start without running the precheck first."
    )
    emails: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional device_name -> activation email override (Connected Mode "
            "only). Devices not listed use their default account email."
        ),
    )


@router.post("/v1/activate/emails")
def get_activate_emails(body: PrecheckBody) -> dict:
    """Default activation account email of each given device."""
    names = [n for n in (body.device_names or []) if n]
    return {"emails": {n: _default_email(n) for n in names}}


@router.get("/v1/activate/email/{device_name}")
def get_activate_email(device_name: str) -> dict:
    """Default activation account email for one device."""
    return {"device_name": device_name, "email": _default_email(device_name)}


@router.post("/v1/activate/precheck")
def precheck_devices(body: PrecheckBody) -> dict:
    """Precheck one or more devices for the requested target mode.

    Returns one row per device with connection_type / is_linked / allowed.
    A wireless device may NOT be converted to Unconnected Mode.
    """
    if body.mode not in MODES:
        raise HTTPException(status_code=400, detail=f"Unknown mode '{body.mode}'")
    names = [n for n in (body.device_names or []) if n]
    if not names:
        raise HTTPException(status_code=400, detail="No device selected")

    results: list[dict] = [None] * len(names)  # type: ignore[list-item]
    threads: list[threading.Thread] = []

    def work(idx: int, name: str) -> None:
        try:
            results[idx] = _precheck_device(name, body.mode)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Precheck error for %s", name)
            results[idx] = {
                "device_name": name,
                "mode": body.mode,
                "ip_address": "",
                "connection_type": "",
                "is_linked": None,
                "allowed": False,
                "reason": f"Precheck error: {exc}",
            }

    for i, name in enumerate(names):
        t = threading.Thread(target=work, args=(i, name), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    return {"mode": body.mode, "results": results}


def _spawn(device_name: str, mode: str, email: str = "") -> dict:
    """Start the conversion script for one device, returning its job dict."""
    script = (
        RUN_ACTIVATE_SCRIPT_CONNECTED
        if mode == MODE_CONNECTED
        else RUN_ACTIVATE_SCRIPT_UNCONNECTED
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    log_file_name = _log_name(mode, device_name, timestamp)
    log_file = os.path.join(LOG_DIR, log_file_name)
    cmd = f"python3 {shlex.quote(script)} {shlex.quote(device_name)}"
    # Connected Mode links an account, so the email may be overridden per run.
    if mode == MODE_CONNECTED and email:
        cmd += f" {shlex.quote(email)}"
    # setsid: own session/process group, so stopping the job never signals the
    # backend and the child survives an HTTP request ending.
    shell_cmd = f"(setsid {cmd} > {shlex.quote(log_file)} 2>&1 & echo $!)"
    process = subprocess.Popen(
        shell_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    stdout, _ = process.communicate()
    try:
        pid = int((stdout or b"").decode().strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to start conversion for {device_name}"
        ) from exc

    logger.info(
        "Activate started: device=%s mode=%s email=%s pid=%s log=%s",
        device_name,
        mode,
        email or "-",
        pid,
        log_file_name,
    )
    return {
        "id": uuid.uuid4().hex[:12],
        "device_name": device_name,
        "mode": mode,
        "email": email,
        "pid": pid,
        "log_file": log_file_name,
        "command": cmd,
        "started_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


@router.post("/v1/activate/start")
def start_activation(body: StartBody) -> dict:
    """Convert one or more devices to Connected / Unconnected mode in parallel.

    Each device is prechecked first (unless skip_precheck); devices that fail the
    precheck are reported in `rejected` and are NOT started. Everything else is
    launched concurrently, one process + log file per device.
    """
    if body.mode not in MODES:
        raise HTTPException(status_code=400, detail=f"Unknown mode '{body.mode}'")
    names = list(dict.fromkeys(n for n in (body.device_names or []) if n))
    if not names:
        raise HTTPException(status_code=400, detail="No device selected")

    # Refuse devices that already have a running job.
    with _jobs_lock:
        busy = {
            j.get("device_name")
            for j in _load_jobs()
            if _pid_alive(int(j.get("pid") or 0))
        }

    started: list[dict] = []
    rejected: list[dict] = []
    prechecks: list[dict] = []

    for name in names:
        if name in busy:
            rejected.append(
                {
                    "device_name": name,
                    "allowed": False,
                    "reason": "A conversion is already running for this device",
                }
            )
            continue
        if body.skip_precheck:
            check = {"device_name": name, "allowed": True, "reason": "Precheck skipped"}
        else:
            check = _precheck_device(name, body.mode)
        prechecks.append(check)
        if not check.get("allowed"):
            rejected.append(check)
            continue
        email = ""
        if body.mode == MODE_CONNECTED:
            email = ((body.emails or {}).get(name) or "").strip() or _default_email(
                name
            )
        job = _spawn(name, body.mode, email)
        job["precheck"] = check
        _add_job(job)
        started.append(_decorate(job))

    return {
        "mode": body.mode,
        "started": started,
        "rejected": rejected,
        "prechecks": prechecks,
    }


@router.post("/v1/activate/connected/start")
def start_connected_activation(body: ActivateBody) -> dict:
    """Start the Connected Mode conversion for a single device."""
    res = start_activation(
        StartBody(device_names=[body.device_name], mode=MODE_CONNECTED)
    )
    if not res["started"]:
        reason = (res["rejected"] or [{}])[0].get("reason", "Not allowed")
        raise HTTPException(status_code=400, detail=reason)
    job = res["started"][0]
    return {"pid": job["pid"], "log_file": job["log_file"]}


@router.post("/v1/activate/unconnected/start")
def start_unconnected_activation(body: ActivateBody) -> dict:
    """Start the Unconnected Mode conversion for a single device."""
    res = start_activation(
        StartBody(device_names=[body.device_name], mode=MODE_UNCONNECTED)
    )
    if not res["started"]:
        reason = (res["rejected"] or [{}])[0].get("reason", "Not allowed")
        raise HTTPException(status_code=400, detail=reason)
    job = res["started"][0]
    return {"pid": job["pid"], "log_file": job["log_file"]}


@router.get("/v1/activate/jobs")
def list_activation_jobs(limit: int = 50) -> dict:
    """List tracked conversion jobs (newest first) with live running state."""
    with _jobs_lock:
        jobs = _load_jobs()
    return {"jobs": [_decorate(j) for j in jobs[: max(1, limit)]]}


@router.delete("/v1/activate/jobs/{job_id}")
def delete_activation_job(job_id: str) -> dict:
    """Forget a job (does not touch the log file). Running jobs must be stopped first."""
    with _jobs_lock:
        jobs = _load_jobs()
        keep = [j for j in jobs if j.get("id") != job_id]
        if len(keep) == len(jobs):
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        removed = next(j for j in jobs if j.get("id") == job_id)
        if _pid_alive(int(removed.get("pid") or 0)):
            raise HTTPException(
                status_code=400, detail="Job is still running; stop it first"
            )
        _save_jobs(keep)
    return {"message": f"Job '{job_id}' removed"}


@router.get("/v1/activate/status/{pid}")
def get_device_activation_status(pid: int) -> dict:
    """Whether the conversion process `pid` is still running."""
    return {"pid": pid, "status": "running" if _pid_alive(pid) else "not_running"}


def _signal_job(pid: int, sig: int) -> bool:
    """Signal the job's process group (safe: jobs are started with setsid)."""
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, ValueError):
        return False
    try:
        if pgid != os.getpgid(0):
            os.killpg(pgid, sig)
        else:
            os.kill(pid, sig)
    except ProcessLookupError:
        return False
    return True


@router.post("/v1/activate/stop/{pid}")
def stop_activation(pid: int) -> dict:
    """Stop a running conversion (and its children)."""
    if pid <= 0 or not _signal_job(pid, signal.SIGTERM):
        return {"pid": pid, "status": "not_running"}
    for _ in range(20):  # up to ~2s, then escalate
        time.sleep(0.1)
        if not _pid_alive(pid):
            break
    else:
        _signal_job(pid, signal.SIGKILL)
    logger.info("Stopped activate job pid=%s", pid)
    return {"pid": pid, "status": "stopped"}


@router.get("/v1/activate/log/list")
def list_activation_logs() -> dict:
    """List the conversion log files in 5_activate/logs (newest first).

    Each entry also carries the fields parsed out of its name (mode / device /
    timestamp), which the UI uses for its filter dropdowns.
    """
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        files = [f for f in os.listdir(LOG_DIR) if f.endswith(".log")]
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Error listing activate logs: {exc}"
        ) from exc
    logs = []
    for name in files:
        full = os.path.join(LOG_DIR, name)
        try:
            mtime = os.path.getmtime(full)
            size = os.path.getsize(full)
        except OSError:
            mtime, size = 0, 0
        parsed = _parse_log_name(name)
        logs.append(
            {
                "name": name,
                "mtime": mtime,
                "size": size,
                "mode": parsed.get("mode", ""),
                "device_name": parsed.get("device_name", ""),
                "timestamp": parsed.get("timestamp", ""),
            }
        )
    logs.sort(key=lambda x: x["mtime"], reverse=True)
    return {"logs": logs}


@router.get("/v1/activate/log/view/{log_file}")
def view_activation_log(log_file: str, lines: int = 1000) -> dict:
    """Tail a conversion log file (last `lines` lines)."""
    path = _log_path(log_file)
    if not os.path.isfile(path):
        return {"name": os.path.basename(path), "content": "", "exists": False}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.readlines()
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Error reading log '{log_file}': {exc}"
        ) from exc
    if lines > 0:
        content = content[-lines:]
    return {
        "name": os.path.basename(path),
        "content": "".join(content),
        "exists": True,
        "mtime": os.path.getmtime(path),
    }


@router.delete("/v1/activate/log/{log_file}")
def delete_activation_log(log_file: str) -> dict:
    """Delete a conversion log file."""
    path = _log_path(log_file)
    try:
        os.remove(path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"Log file '{log_file}' not found"
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Error deleting log '{log_file}': {exc}"
        ) from exc
    return {"message": f"Log file '{log_file}' deleted"}


# Bring historical log file names up to the canonical "__" format on startup.
_migrate_log_names()
