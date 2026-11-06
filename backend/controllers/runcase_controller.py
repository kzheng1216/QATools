import asyncio
import glob
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import (
    ANALYZER_PATH,
    CASE_CACHE_PATH,
    QAHUB_HEADERS,
    QAHUB_URL,
    QATOOLS_ROOT,
    REPORT_PATH,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from services.data_service import RUNCASE_STORE, DataServiceError

from . import logger

runcase_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.path.join(QATOOLS_ROOT, "4_runcase"))
)

# runcase_user_query_list / roku_test_cache_data were split out of config.yml
# into conf/runcase_data.yml; all access goes through the data service layer.
_USER_QUERY_KEY = "runcase_user_query_list"
config_conf_path = RUNCASE_STORE.path

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

analyzer_dir = os.path.abspath(ANALYZER_PATH)

# Statuses that count as "passed" and are therefore skipped by auto analyze.
_PASS_STATUSES = {"pass", "passed", "success", "successful"}


def _is_pass(status: str | None) -> bool:
    return (status or "").strip().lower() in _PASS_STATUSES


def _profile_label(profile_name: str) -> str:
    """Profile name without the .json suffix (used in report file names)."""
    name = os.path.basename(profile_name or "")
    return name[:-5] if name.lower().endswith(".json") else name


def _latest_summary_report(profile_name: str, newer_than: float = 0.0) -> str | None:
    """Newest `*<profile>*_summary_report.txt` written after `newer_than`."""
    label = _profile_label(profile_name)
    pattern = os.path.join(report_dir, f"*{label}*_summary_report.txt")
    best, best_mtime = None, newer_than
    for path in glob.glob(pattern):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime >= best_mtime:
            best, best_mtime = path, mtime
    return best


def _report_tasks(report_path: str) -> list[dict]:
    """Parse the `tasks` list out of a summary report file."""
    try:
        with open(report_path, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        logger.error("Auto analyze: cannot parse report '%s': %s", report_path, exc)
        return []
    tasks = data.get("tasks")
    return tasks if isinstance(tasks, list) else []


def _join_ids(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if str(v).strip())
    return str(value or "")


# Status written into the profile report while cases are still being analyzed
# vs. once the whole batch is done. The UI shows "Analyzing" (instead of the
# case links) until the report flips to ANALYZE_DONE.
ANALYZE_RUNNING = "analyzing"
ANALYZE_DONE = "completed"


def _profile_report_name(
    profile_name: str, locale: str, count_nopass: int, count_case: int, now: str
) -> str:
    """p__<profile>__<nopass>__<count>__<locale>__<datetime>.yml"""
    label = _profile_label(profile_name)
    return f"p__{label}__{count_nopass}__{count_case}__{locale}__{now}.yml"


def _write_profile_analyze_report(
    name: str,
    profile_name: str,
    now: str,
    count_nopass: int,
    count_case: int,
    case_reports: list[str],
    status: str = ANALYZE_DONE,
) -> str:
    """(Re)write the profile roll-up report.

    Called once up front with `status=analyzing` and an empty/partial case list,
    again after every finished case, and a last time with `status=completed`,
    so the Analyze History page can show live progress.
    """
    os.makedirs(analyzer_dir, exist_ok=True)
    lines = [
        f"profile_name: {_profile_label(profile_name)}",
        f"date: {now}",
        f"status: {status}",
        f"count_nopass_case: {count_nopass}",
        f"count_case: {count_case}",
        "case_analyze_report:",
    ]
    lines += [f" - {r}" for r in case_reports]
    path = os.path.join(analyzer_dir, name)
    # Write-then-replace so a reader never sees a half-written report.
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    logger.info(
        "Auto analyze: profile report '%s' status=%s (%s/%s cases)",
        name,
        status,
        len(case_reports),
        count_nopass,
    )
    return name


def _is_loop_binding_error(exc: BaseException) -> bool:
    """True for the httpx/asyncio "wrong event loop" family of errors.

    The shared client's pool objects remember the loop they were created on, so
    the first call from a new loop can fail with "Event loop is closed" or
    "... bound to a different event loop". Retrying once is enough: the failure
    discards the stale connection and the retry builds a fresh one.
    """
    text = f"{getattr(exc, 'detail', '') or ''} {exc}".lower()
    return "event loop" in text


def _run_coro_with_retry(make_coro, loop: asyncio.AbstractEventLoop | None):
    """Run `make_coro()` on `loop`, retrying once past a stale-pool error.

    `make_coro` is a factory (not a coroutine) because a coroutine object can
    only be awaited once, so the retry needs a fresh one.
    """
    try:
        return _run_coro(make_coro(), loop)
    except Exception as exc:  # noqa: BLE001
        if not _is_loop_binding_error(exc):
            raise
        logger.warning(
            "Auto analyze: stale AI connection (%s); retrying once",
            _error_text(exc),
        )
        return _run_coro(make_coro(), loop)


def _error_text(exc: BaseException) -> str:
    """Readable message for an exception.

    `fastapi.HTTPException` carries its message in `.detail` and stringifies to
    an empty string, which would otherwise hide the real failure in the log.
    """
    detail = getattr(exc, "detail", None)
    return f"{type(exc).__name__}: {detail if detail else exc}"


# A single dedicated event loop for all AI analysis calls. Created on first use
# and deliberately never closed, so the shared httpx connection pool stays
# valid for the life of the process.
_analyze_loop_ref: asyncio.AbstractEventLoop | None = None
_analyze_loop_lock = threading.Lock()


def _analyze_loop() -> asyncio.AbstractEventLoop:
    """Return the dedicated analysis event loop, starting it on first use."""
    global _analyze_loop_ref
    with _analyze_loop_lock:
        if _analyze_loop_ref is None or _analyze_loop_ref.is_closed():
            _analyze_loop_ref = asyncio.new_event_loop()
            threading.Thread(
                target=_analyze_loop_ref.run_forever,
                daemon=True,
                name="auto-analyze-loop",
            ).start()
            logger.info("Auto analyze: started dedicated analysis event loop")
        return _analyze_loop_ref


def _run_coro(coro, loop: asyncio.AbstractEventLoop | None = None):
    """Run an async call from a worker thread.

    The AI client is a single shared `httpx.AsyncClient` built at import time,
    and an httpx connection pool must only ever be driven by one event loop.
    `asyncio.run()` per case closes its loop each time, which kills the pooled
    TLS connections and makes every later case fail with "Event loop is
    closed". Note the failure surfaces on the *next* call, so case 1 appears to
    succeed and cases 2..n all fail.

    Therefore every analysis coroutine is funnelled onto one dedicated,
    never-closed loop. A caller-supplied loop is used when given and still open
    (e.g. the app loop for the async endpoint).
    """
    target = loop if loop is not None and not loop.is_closed() else _analyze_loop()
    return asyncio.run_coroutine_threadsafe(coro, target).result()


def _analyze_one_task(
    task: dict,
    profile_name: str,
    locale: str,
    loop: asyncio.AbstractEventLoop | None = None,
) -> str | None:
    """Analyze a single non-passing task; return the created .md file name."""
    from . import agent_controller

    log_url = task.get("log_url")
    if not log_url:
        logger.warning("Auto analyze: task without log_url skipped: %s", task)
        return None

    before = set(os.listdir(analyzer_dir)) if os.path.isdir(analyzer_dir) else set()

    def make_coro():
        # Rebuilt per attempt: a request model and coroutine are single-use.
        req = agent_controller.AgentChatRequest(
            prompt=str(log_url), use_internal=False
        )
        return agent_controller.agent_analyze(
            req,
            profile_name=_profile_label(profile_name),
            locale=locale,
            testrail_case_id=_join_ids(task.get("testrail_case_ids"))
            or "unknown_testrail_case_id",
            case_id=_join_ids(task.get("case_ids")) or "unknown_case_id",
            case_test_result=str(task.get("status") or "Unknown"),
        )

    _run_coro_with_retry(make_coro, loop)
    after = set(os.listdir(analyzer_dir)) if os.path.isdir(analyzer_dir) else set()
    created = sorted(n for n in after - before if n.lower().endswith(".md"))
    return created[-1] if created else None


def auto_analyze_profile(
    profile_name: str,
    locale: str,
    started_at: float,
    loop: asyncio.AbstractEventLoop | None = None,
) -> dict:
    """Analyze every non-passing case of a finished profile run."""
    report_path = _latest_summary_report(profile_name, started_at)
    if not report_path:
        logger.warning(
            "Auto analyze: no summary report found for profile '%s'", profile_name
        )
        report_path = _latest_summary_report(profile_name)
    tasks = _report_tasks(report_path) if report_path else []
    nopass = [t for t in tasks if not _is_pass(t.get("status"))]
    logger.info(
        "Auto analyze: profile='%s' cases=%s nopass=%s report='%s'",
        profile_name,
        len(tasks),
        len(nopass),
        report_path,
    )

    # Publish the report immediately so the profile shows up as "analyzing"
    # while the per-case analyses are still running.
    now = time.strftime("%Y-%m-%d_%H-%M-%S")
    report_name = _profile_report_name(
        profile_name, locale, len(nopass), len(tasks), now
    )
    case_reports: list[str] = []
    _write_profile_analyze_report(
        report_name,
        profile_name,
        now,
        len(nopass),
        len(tasks),
        case_reports,
        status=ANALYZE_RUNNING if nopass else ANALYZE_DONE,
    )

    try:
        for task in nopass:
            try:
                name = _analyze_one_task(task, profile_name, locale, loop)
            except Exception as exc:  # noqa: BLE001 - never break the whole batch
                logger.error(
                    "Auto analyze failed for case %s: %s",
                    _join_ids(task.get("case_ids")),
                    _error_text(exc),
                )
                continue
            if name:
                case_reports.append(name)
                # Refresh the roll-up after each case so the UI can show
                # progress (n of m analyzed).
                _write_profile_analyze_report(
                    report_name,
                    profile_name,
                    now,
                    len(nopass),
                    len(tasks),
                    case_reports,
                    status=ANALYZE_RUNNING,
                )
    finally:
        # Always flip to completed, even if a case blew up, so the row never
        # stays stuck on "Analyzing".
        _write_profile_analyze_report(
            report_name,
            profile_name,
            now,
            len(nopass),
            len(tasks),
            case_reports,
            status=ANALYZE_DONE,
        )

    return {
        "profile_report": report_name,
        "status": ANALYZE_DONE,
        "count_case": len(tasks),
        "count_nopass_case": len(nopass),
        "case_analyze_report": case_reports,
    }


def _auto_analyze_after_run(
    process: subprocess.Popen,
    profile_name: str,
    locale: str,
    started_at: float,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Background worker: wait for the run to finish, then auto analyze."""
    try:
        process.wait()
    except Exception as exc:  # noqa: BLE001
        logger.error("Auto analyze: waiting for pid %s failed: %s", process.pid, exc)
        return
    time.sleep(2)
    try:
        auto_analyze_profile(profile_name, locale, started_at, loop)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Auto analyze failed for profile '%s': %s",
            profile_name,
            _error_text(exc),
        )


def _default_analyze_locale() -> str:
    try:
        from . import agent_controller

        return agent_controller._analyze_config()["default_locale"]
    except Exception:  # noqa: BLE001
        return "en-US"


@router.post("/v1/runcase/run")
async def run_case(
    profile_name: str,
    select: str = "All",
    auto_analyze: bool = False,
    locale: str | None = None,
) -> dict:
    """Run a BDD case with the specified profile and selection."""
    logger.info(
        "Run case: profile='%s' select='%s' auto_analyze=%s",
        profile_name,
        select,
        auto_analyze,
    )
    started_at = time.time()
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
    if auto_analyze:
        # Capture the app's event loop and hand it to the worker thread. The AI
        # client is shared with the interactive /v1/agent/analyze endpoint, so
        # all of its calls must run on this one loop. `run_case` is async
        # precisely so a running loop exists here -- as a sync endpoint FastAPI
        # would run it in a threadpool with no loop, and the analysis would
        # fall back to a throw-away loop per case and fail.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - defensive
            loop = None
        threading.Thread(
            target=_auto_analyze_after_run,
            args=(
                process,
                profile_name,
                locale or _default_analyze_locale(),
                started_at,
                loop,
            ),
            daemon=True,
            name=f"auto-analyze-{process.pid}",
        ).start()
    return {
        "message": f"Profile '{profile_name}' executed with selection '{select}' started"
        + (" (auto analyze enabled)" if auto_analyze else ""),
        "pid": process.pid,
        "auto_analyze": auto_analyze,
    }


@router.post("/v1/runcase/analyze_profile")
async def analyze_profile(profile_name: str, locale: str | None = None) -> dict:
    """Analyze the non-passing cases of the latest run of a profile now.

    Same output as the auto-analyze step of `/v1/runcase/run`: one markdown
    report per non-passing case plus the `p__...yml` profile report.
    """
    # Async so we can hand this loop to the worker: the analysis itself is
    # blocking, so it runs in a thread and calls back into this loop for the
    # shared async AI client.
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None,
            auto_analyze_profile,
            profile_name,
            locale or _default_analyze_locale(),
            0.0,
            loop,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Analyze profile '%s' failed: %s", profile_name, _error_text(exc))
        raise HTTPException(
            status_code=500,
            detail=f"Error analyzing profile '{profile_name}': {_error_text(exc)}",
        ) from exc


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


def _load_user_query_list() -> list[dict]:
    """Read runcase_user_query_list through the data service."""
    try:
        return RUNCASE_STORE.get_list(_USER_QUERY_KEY)
    except DataServiceError as exc:
        logger.error("%s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _save_user_query_list(users: list[dict]) -> None:
    """Persist runcase_user_query_list through the data service."""
    try:
        RUNCASE_STORE.set_section(_USER_QUERY_KEY, users)
    except DataServiceError as exc:
        logger.error("%s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/v1/runcase/user_query_list")
def list_user_query_list() -> dict:
    """
    List all user query list.
    """
    try:
        logger.info("List user query list from: %s", config_conf_path)
        return {"user_query_list": _load_user_query_list()}
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
        users = _load_user_query_list()
        if any((u or {}).get("name") == name for u in users):
            return {"message": f"'{name}' already saved", "user_query_list": users}
        users.append({"name": name})
        _save_user_query_list(users)
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
        users = _load_user_query_list()
        new_users = [u for u in users if (u or {}).get("name") != name]
        if len(new_users) == len(users):
            raise HTTPException(status_code=404, detail=f"'{name}' not found")
        _save_user_query_list(new_users)
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
    # run_case is async (it needs the app's event loop for auto-analyze).
    asyncio.run(run_case("p_01", "All"))
