"""Donut controller — QA Hub donut triggering, live status, abort and summary.

Thin proxy over the QA Hub v1 REST API (see docs/QAHub_Donuts_REST_API.md plus
``{QAHUB_URL}/swagger.json``, which is the authoritative contract):

    GET  /donut/product                                 -> products
    GET  /donut/branch/{product}                        -> branches
    GET  /donut/device?product=&donut=&branch=          -> product/donut/branch/serial tree
    GET  /donut/configuration/{product}/{branch}/{donut} -> donut_config.id
    POST /donut/run                                     -> launch (NO suite id returned)
    GET  /donut/jenkins-running/{product}/{branch}      -> live Jenkins donut jobs
    DELETE /donut/jenkins-running/{product}/{branch}    -> terminate a running job
    GET  /donut/queued-runs/{product}/{branch}          -> queued (device-busy) requests
    DELETE /donut/queued-runs/{product}/{branch}        -> cancel a queued request
    GET  /donut/results/{build_number}                  -> finished donut runs + pass %
    GET  /suite/{id}, /suite/{id}/tests                 -> suite detail / per-test results

Status tracking deliberately does NOT rely on a suite id coming back from
``POST /donut/run``: per swagger that endpoint only returns 200, or 202 with
``queued_run_id``/``busy_devices``. A donut launch is asynchronous (QA Hub ->
Jenkins -> suite), so a run is correlated by (serial, donut, branch) against
``/donut/jenkins-running`` while it executes and ``/donut/results`` once it has
finished.

Launched runs are remembered in data/donut_runs.json so the UI keeps showing
them across page reloads and backend restarts.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import QAHUB_BASE_URL, QAHUB_HEADERS, QAHUB_URL, QATOOLS_ROOT

from . import logger

router = APIRouter()

device_conf_dir = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), os.path.join(QATOOLS_ROOT, "config", "device_conf")
    )
)
_runs_path = os.path.abspath(
    os.path.join(QATOOLS_ROOT, "data", "donut_runs.json")
)

# QA Hub suite states (qa_hub_clients.SuiteStates). Anything not terminal is
# still in flight, so the UI keeps polling it. An unknown/empty state is NOT
# treated as running, otherwise the UI would poll such a row forever.
_TERMINAL_STATES = {"complete", "killed", "abandoned", "device_issue"}
_ACTIVE_STATES = {"running", "upgrading", "terminating", "kill"}
# Writing this state is how QA Hub aborts a suite; there is no /abort route.
_KILL_STATE = "kill"
# QA Hub caps page_size at 200 (swagger: GET /suite).
_MAX_PAGE_SIZE = 200

# Serialises read-modify-write of donut_runs.json (FastAPI runs sync endpoints
# in a threadpool, so two launches can land concurrently).
_runs_lock = threading.Lock()

# Jenkins host that QA Hub dispatches donut jobs to; used only to build a
# clickable job link next to a running donut.
_JENKINS_BASE = "https://jenkins.eswat.rokulabs.net"


def _testrail_url(group_type: str | None, group_id: object) -> str:
    """Build a TestRail plan/run URL from a suite's testrail_config.

    QA Hub suites carry ``testrail_config.group_type`` ('plan' or 'run') plus
    ``group_id``; there is no ready-made URL field on the suite.
    """
    if not group_id:
        return ""
    kind = "plans" if str(group_type or "plan") == "plan" else "runs"
    return f"https://testrail.eswat.roku.com/testrail/index.php?/{kind}/view/{group_id}"


# ---------- QA Hub HTTP ----------
def _qahub(
    location: str,
    method: str = "GET",
    data: dict | None = None,
    timeout: int = 60,
) -> dict:
    """Call QA Hub and return the decoded JSON body.

    :param location: Path below /api/v1, e.g. "donut/run" or "suite/123".
    :param method: HTTP verb.
    :param data: JSON body for write calls.
    :param timeout: Seconds.

    :returns: Decoded JSON object (``{}`` for an empty body).

    :raises HTTPException: QA Hub errors are surfaced with their own status code
        and message so the UI can show "forbidden"/"not found" meaningfully.
    """
    url = f"{QAHUB_URL.rstrip('/')}/{location.lstrip('/')}"
    headers = dict(QAHUB_HEADERS)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, headers=headers, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        detail = raw[:400]
        try:
            payload = json.loads(raw)
            detail = payload.get("error") or payload.get("message") or detail
        except ValueError:
            pass
        logger.error("QA Hub %s %s -> HTTP %s %s", method, location, exc.code, detail)
        raise HTTPException(
            status_code=exc.code, detail=f"QA Hub: {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.error("QA Hub %s %s failed: %s", method, location, exc)
        raise HTTPException(
            status_code=502, detail=f"QA Hub unreachable: {exc}"
        ) from exc


# ---------- launched-run bookkeeping ----------
def _load_runs() -> list[dict]:
    try:
        with open(_runs_path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_runs(runs: list[dict]) -> None:
    try:
        os.makedirs(os.path.dirname(_runs_path), exist_ok=True)
        with open(_runs_path, "w", encoding="utf-8") as f:
            json.dump(runs, f, indent=2)
    except OSError as exc:
        # Bookkeeping must never fail a launch that QA Hub already accepted.
        logger.error("Error writing donut_runs.json: %s", exc)


def _record_run(entry: dict) -> None:
    with _runs_lock:
        runs = _load_runs()
        runs.insert(0, entry)
        _save_runs(runs[:200])  # keep the file bounded


def _device_serial(device_name: str) -> str:
    """Resolve a QATools device config name to its Roku serial number."""
    path = os.path.join(device_conf_dir, f"{device_name}.json")
    if not os.path.isfile(path):
        raise HTTPException(
            status_code=404, detail=f"Device configuration '{device_name}' not found"
        )
    try:
        with open(path, encoding="utf-8") as f:
            serial = json.load(f)["roku"]["serial_number"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Device '{device_name}' has no roku.serial_number",
        ) from exc
    if not serial:
        raise HTTPException(
            status_code=400, detail=f"Device '{device_name}' has an empty serial_number"
        )
    return str(serial)


# ---------- catalogue ----------
@router.get("/v1/donut/products")
def list_products() -> dict:
    """List donut products (Roku OS, Grand Central, ...)."""
    return {"products": _qahub("donut/product").get("products") or []}


@router.get("/v1/donut/branches/{product}")
def list_branches(product: str) -> dict:
    """List the branches configured for a product."""
    data = _qahub(f"donut/branch/{urllib.parse.quote(product, safe='')}")
    return {"branches": data.get("branches") or []}


@router.get("/v1/donut/for_device/{device_name}")
def donuts_for_device(device_name: str, product: str | None = None) -> dict:
    """List the donuts this device is actually registered on.

    QA Hub returns a product -> donut -> branch -> serial tree; this flattens it
    to the (product, donut, branch) rows whose serial matches the device, which
    is what the UI needs to offer a valid trigger target.
    """
    serial = _device_serial(device_name)
    location = "donut/device"
    if product:
        location += f"?product={urllib.parse.quote(product, safe='')}"
    tree = _qahub(location, timeout=120).get("devices") or {}

    rows: list[dict] = []
    for prod, donuts in (tree or {}).items():
        if not isinstance(donuts, dict):
            continue
        for donut, branches in donuts.items():
            if not isinstance(branches, dict):
                continue
            for branch, serials in branches.items():
                if isinstance(serials, dict) and serial in serials:
                    info = serials.get(serial) or {}
                    rows.append(
                        {
                            "product": prod,
                            "donut": donut,
                            "branch": branch,
                            "platform_name": info.get("Platform Name", ""),
                            "platform_version": info.get("Platform Version", ""),
                        }
                    )
    rows.sort(key=lambda r: (r["product"], r["donut"], r["branch"]))
    logger.info(
        "Device '%s' (serial=%s) is on %d donut(s)", device_name, serial, len(rows)
    )
    return {"device": device_name, "serial_number": serial, "donuts": rows}


@router.get("/v1/donut/configuration")
def get_configuration(product: str, branch: str, donut: str) -> dict:
    """Return a donut configuration, including the donut_config_id needed to run."""
    q = urllib.parse.quote
    data = _qahub(
        f"donut/configuration/{q(product, safe='')}/{q(branch, safe='')}/{q(donut, safe='')}"
    )
    cfg = data.get("donut_config") or {}
    return {"donut_config_id": cfg.get("id"), "donut_config": cfg}


# ---------- trigger ----------
class DonutRunBody(BaseModel):
    device: str = Field(..., description="QATools device config name.")
    product: str = Field(..., description="Donut product, e.g. 'Roku OS'.")
    branch: str = Field(..., description="Donut branch.")
    donut: str = Field(..., description="Donut name, e.g. 'BVAT'.")
    build_number: str = Field(..., description="Build number to run against.")
    run_downstream_donuts: bool = Field(default=False)
    log_verbosity: int = Field(default=1, ge=0, le=3)
    cloud_serial_logs: bool = Field(default=False)


@router.post("/v1/donut/run")
def trigger_run(body: DonutRunBody) -> dict:
    """Trigger a donut run for one device.

    Resolves the device serial and the donut_config_id, then POSTs /donut/run
    with a single-element ``serial_numbers``. QA Hub answers 202 with a
    ``queued_run_id`` when the device is busy, which is reported as queued
    rather than treated as an error.
    """
    serial = _device_serial(body.device)
    cfg = get_configuration(body.product, body.branch, body.donut)
    donut_config_id = cfg.get("donut_config_id")
    if not donut_config_id:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No donut configuration for {body.product} / {body.branch} / {body.donut}"
            ),
        )

    payload = {
        "donut_config_id": donut_config_id,
        "build_number": body.build_number,
        "run_downstream_donuts": body.run_downstream_donuts,
        "log_verbosity": body.log_verbosity,
        "cloud_serial_logs": body.cloud_serial_logs,
        "serial_numbers": [serial],
    }
    logger.info("Trigger donut run: %s", payload)
    result = _qahub("donut/run", method="POST", data=payload, timeout=180)

    # Per swagger, POST /donut/run returns 200 ("runs were successfully
    # started") or 202 with queued_run_id/busy_devices. It never returns a
    # suite id: the launch is asynchronous (QA Hub -> Jenkins -> suite), so the
    # run is correlated later by (serial, donut) in list_runs().
    entry = {
        "id": f"{donut_config_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "device": body.device,
        "serial_number": serial,
        "product": body.product,
        "branch": body.branch,
        "donut": body.donut,
        "build_number": body.build_number,
        "donut_config_id": donut_config_id,
        "queued_run_id": result.get("queued_run_id"),
        "launch_batch_id": result.get("launch_batch_id"),
        "busy_devices": result.get("busy_devices") or {},
        "triggered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _record_run(entry)

    return {
        "message": (
            f"Donut '{body.donut}' queued for '{body.device}'"
            if entry["queued_run_id"]
            else f"Donut '{body.donut}' triggered for '{body.device}'"
        ),
        "run": entry,
        "qa_hub_response": result,
    }


# ---------- live status ----------
def _suite_brief(suite: dict) -> dict:
    """Normalise a QA Hub suite into the fields the UI table shows."""
    device = suite.get("device") or {}
    state = str(suite.get("state") or "").lower()
    tc = suite.get("testrail_config") or {}
    return {
        "suite_id": suite.get("id"),
        "name": suite.get("name") or "",
        "user": suite.get("user") or "",
        "state": state,
        "state_message": suite.get("state_message") or "",
        "progress": suite.get("progress"),
        "tests_total": suite.get("tests_total"),
        "tests_complete": suite.get("tests_complete"),
        "serial_number": device.get("serial_number") or "",
        "model": device.get("model") or "",
        "version": device.get("version") or "",
        "start": suite.get("start"),
        "end": suite.get("end"),
        "duration": suite.get("duration"),
        # Only known-active states count as running; an empty or unrecognised
        # state must not keep the UI polling indefinitely.
        "running": state in _ACTIVE_STATES,
        "logs_url": f"{QAHUB_BASE_URL.rstrip('/')}/tests/suite/logs/{suite.get('id')}",
        "testrail_link": _testrail_url(tc.get("group_type"), tc.get("group_id")),
    }


def _running_jobs(product: str, branch: str) -> list[dict]:
    """Return the Jenkins donut jobs currently running for a product/branch.

    Errors are swallowed to an empty list: a run row must still render (with its
    recorded metadata) when QA Hub's Jenkins bridge is unavailable (it answers
    424 when Jenkins itself is down).
    """
    q = urllib.parse.quote
    try:
        data = _qahub(
            f"donut/jenkins-running/{q(product, safe='')}/{q(branch, safe='')}",
            timeout=90,
        )
    except HTTPException as exc:
        logger.info(
            "jenkins-running unavailable for %s/%s: %s", product, branch, exc.detail
        )
        return []
    return [j for j in (data.get("running_jobs") or []) if isinstance(j, dict)]


def _queued_runs(product: str, branch: str) -> list[dict]:
    """Return the queued (device-busy) donut run requests for a product/branch."""
    q = urllib.parse.quote
    try:
        data = _qahub(
            f"donut/queued-runs/{q(product, safe='')}/{q(branch, safe='')}", timeout=90
        )
    except HTTPException as exc:
        logger.info(
            "queued-runs unavailable for %s/%s: %s", product, branch, exc.detail
        )
        return []
    return [r for r in (data.get("queued_runs") or []) if isinstance(r, dict)]


def _job_brief(job: dict) -> dict:
    """Normalise a Jenkins donut job into the fields the UI shows."""
    params = job.get("parameters") or {}
    return {
        "job_name": job.get("job_name") or "",
        "build_number": job.get("build_number"),
        "serial_number": params.get("SERIAL_NUMBER") or "",
        "donut": params.get("DONUT") or "",
        "donut_display_name": params.get("USER_FRIENDLY_DONUT_NAME")
        or params.get("PLAN_DONUT_NAME")
        or params.get("DONUT")
        or "",
        "product": params.get("PRODUCT") or "",
        "branch": params.get("BRANCH_NAME") or "",
        "target_build": params.get("TARGET_BUILD_NUMBER") or "",
        "donut_config_id": params.get("DONUT_CONFIG_ID"),
        "launched_by": params.get("LAUNCHED_BY") or "",
        "testrail_link": params.get("TESTRAIL_PLAN_URL") or "",
        "jenkins_url": f"{_JENKINS_BASE}/job/{job.get('job_name')}/{job.get('build_number')}/"
        if job.get("job_name") and job.get("build_number")
        else "",
    }


def _matches_run(job_params: dict, run: dict) -> bool:
    """Whether a Jenkins job belongs to a run we launched.

    Correlates on serial + donut, which is what uniquely identifies a launch on
    a given branch (the same device can be on several donuts). donut_config_id
    is compared too when Jenkins reports it, since that is the exact identity.
    """
    if (job_params.get("SERIAL_NUMBER") or "") != run.get("serial_number"):
        return False
    cfg_id = job_params.get("DONUT_CONFIG_ID")
    if cfg_id not in (None, "") and str(cfg_id) == str(run.get("donut_config_id")):
        return True
    return (job_params.get("DONUT") or "") == run.get("donut")


@router.get("/v1/donut/runs")
def list_runs(limit: int = 30) -> dict:
    """List the donut runs launched from QATools, with their live status.

    ``POST /donut/run`` does not return a suite id (the launch is asynchronous:
    QA Hub -> Jenkins -> suite), so each recorded run is correlated by
    (serial, donut/donut_config_id) against the Jenkins job list for its
    product/branch, and against the queued-run list while it is still waiting
    for the device. QA Hub is queried once per distinct product/branch rather
    than once per run, so the cost does not grow with history length.
    """
    runs = _load_runs()[: max(1, min(limit, 200))]

    # One jenkins-running / queued-runs call per distinct (product, branch).
    jobs_cache: dict[tuple[str, str], list[dict]] = {}
    queued_cache: dict[tuple[str, str], list[dict]] = {}
    for run in runs:
        key = (run.get("product") or "", run.get("branch") or "")
        if not all(key):
            continue
        if key not in jobs_cache:
            jobs_cache[key] = _running_jobs(*key)
            queued_cache[key] = _queued_runs(*key)

    out: list[dict] = []
    for run in runs:
        key = (run.get("product") or "", run.get("branch") or "")
        jobs = [
            _job_brief(j)
            for j in jobs_cache.get(key, [])
            if _matches_run(j.get("parameters") or {}, run)
        ]
        queued = [
            {
                "queued_run_id": r.get("id"),
                "donut_config_id": r.get("donut_config_id"),
                "donut": r.get("donut_config_name") or "",
                "build_number": r.get("build_number") or "",
                "launch_state": r.get("launch_state") or "",
                "launch_detail": str(r.get("launch_detail") or "")[:300],
                "username": r.get("username") or "",
            }
            for r in queued_cache.get(key, [])
            if str(r.get("donut_config_id")) == str(run.get("donut_config_id"))
        ]

        if jobs:
            status = "running"
        elif queued:
            status = "queued"
        else:
            status = "finished"

        out.append(
            {
                **run,
                "jobs": jobs,
                "queued": queued,
                "status": status,
                "running": bool(jobs) or bool(queued),
            }
        )
    return {"runs": out}


@router.get("/v1/donut/suite/{suite_id}")
def get_suite(suite_id: int) -> dict:
    """Return one suite's live detail (state, progress, device, timings)."""
    suite = _qahub(f"suite/{suite_id}", timeout=30).get("suite") or {}
    if not suite:
        raise HTTPException(status_code=404, detail=f"Suite {suite_id} not found")
    return {"suite": _suite_brief(suite), "raw": suite}


@router.get("/v1/donut/suites")
def list_suites(state: str | None = None, user: str | None = None, page_size: int = 50) -> dict:
    """List QA Hub suites, optionally filtered by state or owner.

    Lets the UI show in-flight donut suites that were not launched from QATools
    (for example triggered by a build hook or by the Donut Shop).
    """
    params = [f"page_size={max(1, min(page_size, _MAX_PAGE_SIZE))}"]
    if state:
        params.append(f"state={urllib.parse.quote(state, safe='')}")
    if user:
        params.append(f"user={urllib.parse.quote(user, safe='')}")
    data = _qahub(f"suite?{'&'.join(params)}", timeout=60)
    return {"suites": [_suite_brief(s) for s in (data.get("suites") or [])]}


# ---------- abort ----------
class AbortJobBody(BaseModel):
    product: str = Field(..., description="Donut product.")
    branch: str = Field(..., description="Donut branch.")
    build_number: int = Field(..., description="Jenkins build number to terminate.")
    job_name: str | None = Field(default=None, description="Jenkins job name.")


@router.post("/v1/donut/abort/job")
def abort_job(body: AbortJobBody) -> dict:
    """Terminate a running donut job in Jenkins.

    This is the correct way to stop a donut that is already executing:
    ``DELETE /donut/jenkins-running/{product}/{branch}`` with the Jenkins build
    number. (Killing the QA Hub suite alone would leave the Jenkins job running.)
    """
    q = urllib.parse.quote
    payload: dict = {"build_number": body.build_number}
    if body.job_name:
        payload["job_name"] = body.job_name
    logger.info(
        "Terminating donut job %s#%s (%s/%s)",
        body.job_name,
        body.build_number,
        body.product,
        body.branch,
    )
    _qahub(
        f"donut/jenkins-running/{q(body.product, safe='')}/{q(body.branch, safe='')}",
        method="DELETE",
        data=payload,
        timeout=90,
    )
    return {"message": f"Termination requested for job {body.job_name} #{body.build_number}"}


class CancelQueuedBody(BaseModel):
    product: str = Field(..., description="Donut product.")
    branch: str = Field(..., description="Donut branch.")
    queued_run_id: int = Field(..., description="Queued run request id to cancel.")


@router.post("/v1/donut/abort/queued")
def cancel_queued_run(body: CancelQueuedBody) -> dict:
    """Cancel a donut run that is still queued waiting for a busy device."""
    q = urllib.parse.quote
    logger.info(
        "Cancelling queued donut run %s (%s/%s)",
        body.queued_run_id,
        body.product,
        body.branch,
    )
    _qahub(
        f"donut/queued-runs/{q(body.product, safe='')}/{q(body.branch, safe='')}",
        method="DELETE",
        data={"queued_run_id": body.queued_run_id},
        timeout=90,
    )
    return {"message": f"Queued run {body.queued_run_id} cancelled"}


@router.post("/v1/donut/abort/suite/{suite_id}")
def abort_suite(suite_id: int) -> dict:
    """Abort a QA Hub suite by setting its state to "kill".

    QA Hub has no /abort route, and it only authorises PATCH /suite/{id} when
    the body is a state change to "kill" (a bare PATCH is rejected with 403).
    Prefer ``/v1/donut/abort/job`` for a donut: that stops the Jenkins job that
    owns the suite.
    """
    logger.info("Aborting suite %s", suite_id)
    _qahub(f"suite/{suite_id}", method="PATCH", data={"state": _KILL_STATE}, timeout=60)
    suite = _qahub(f"suite/{suite_id}", timeout=30).get("suite") or {}
    return {
        "message": f"Abort requested for suite {suite_id}",
        "suite": _suite_brief(suite) if suite else {"suite_id": suite_id},
    }


# ---------- summary ----------
@router.get("/v1/donut/summary/{suite_id}")
def suite_summary(suite_id: int) -> dict:
    """Summarise a finished (or running) suite: pass/fail counts and TestRail link.

    Test results come from /suite/{id}/tests when the token may read them; the
    suite-level totals are always returned so the card still renders if the
    per-test endpoint is not permitted.
    """
    suite = _qahub(f"suite/{suite_id}", timeout=30).get("suite") or {}
    if not suite:
        raise HTTPException(status_code=404, detail=f"Suite {suite_id} not found")

    counts: dict[str, int] = {}
    tests: list[dict] = []
    try:
        data = _qahub(f"suite/{suite_id}/tests", timeout=90)
        for t in data.get("tests") or []:
            state = str(t.get("state") or "unknown").lower()
            counts[state] = counts.get(state, 0) + 1
            tests.append(
                {
                    "name": t.get("test") or t.get("name") or "",
                    "script": t.get("script") or "",
                    "state": state,
                    "duration": t.get("duration"),
                    "message": (t.get("message") or "")[:500],
                }
            )
    except HTTPException as exc:
        # 403/404 here is normal for a read-only token; keep the suite totals.
        logger.info("Per-test results unavailable for suite %s: %s", suite_id, exc.detail)

    brief = _suite_brief(suite)
    return {
        "suite": brief,
        "counts": counts,
        "tests": tests,
        # Derived from testrail_config.group_type/group_id; the suite has no
        # ready-made URL field.
        "testrail_link": brief["testrail_link"],
        "complete": not brief["running"],
    }


@router.get("/v1/donut/results/{build_number}")
def donut_results(
    build_number: str, serial_number: str | None = None, donut: str | None = None
) -> dict:
    """Summarise finished donut runs for a build.

    ``GET /donut/results/{build_number}`` is the only endpoint that reports a
    completed donut's outcome (pass percentage, stage, TestRail ids), so it is
    what the UI uses once a run no longer appears in jenkins-running.
    """
    data = _qahub(f"donut/results/{urllib.parse.quote(build_number, safe='')}", timeout=120)
    runs = [r for r in (data.get("runs") or []) if isinstance(r, dict)]

    if donut:
        runs = [r for r in runs if (r.get("run_type") or "") == donut]
    if serial_number:
        # Results are keyed by device identifier, which may be the serial or a
        # friendly platform name, so match either.
        runs = [
            r
            for r in runs
            if serial_number
            in (
                (r.get("device") or {}).get("serial_number") or "",
                (r.get("device") or {}).get("identifier") or "",
            )
        ]

    out = [
        {
            "id": r.get("id"),
            "run_type": r.get("run_type") or "",
            "product": r.get("product") or "",
            "build_number": r.get("build_number") or "",
            "device": (r.get("device") or {}).get("identifier")
            or (r.get("device") or {}).get("serial_number")
            or "",
            "pass_percentage": r.get("pass_percentage"),
            "stage": r.get("stage") or "",
            "failures_re_ran": r.get("failures_re_ran"),
            "duration": r.get("duration"),
            # Results rows carry suite_id (not a TestRail id); the suite is the
            # route to logs and per-test results.
            "suite_id": r.get("suite_id"),
            "logs_url": f"{QAHUB_BASE_URL.rstrip('/')}/tests/suite/logs/{r.get('suite_id')}"
            if r.get("suite_id")
            else "",
        }
        for r in runs
    ]
    return {"build_number": build_number, "count": len(out), "results": out}


@router.delete("/v1/donut/runs/{run_id}")
def delete_run(run_id: str) -> dict:
    """Forget a launched run locally (does not touch QA Hub)."""
    with _runs_lock:
        runs = _load_runs()
        kept = [r for r in runs if r.get("id") != run_id]
        if len(kept) == len(runs):
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        _save_runs(kept)
    logger.info("Donut run '%s' removed from local history", run_id)
    return {"message": f"Run '{run_id}' removed"}
