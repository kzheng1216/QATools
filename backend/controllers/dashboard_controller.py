# backend/controllers/dashboard_controller.py

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime

from fastapi import APIRouter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import (
    AGENT_SESSION_PATH,
    ANALYZER_PATH,
    CASE_CACHE_PATH,
    DATA_BASE_DIR,
    DOCS_DATA_PATH,
    QATOOLS_ROOT,
    REPORT_PATH,
    SKILL_DATA_PATH,
    TESTRAIL_DATA_PATH,
)
from services.data_service import (
    AGENT_STORE,
    FILE_TRANSFER_STORE,
    REF_STORE,
    TESTRAIL_STORE,
    DataServiceError,
)

from . import logger

router = APIRouter()

# ---------- paths (mirrors the per-tab controllers) ----------
_DEVICE_CONF_DIR = os.path.join(QATOOLS_ROOT, "config", "device_conf")
_PROFILE_CONF_DIR = os.path.join(QATOOLS_ROOT, "4_runcase", "profiles")
_BACKEND_CONF_DIR = os.path.join(QATOOLS_ROOT, "backend", "conf")
# backend/conf yaml data is read through the data service stores imported above.
# Run-in-local log directory, under the data dir (mirrors roku_test_controller).
_ROKU_TEST_LOG_DIR = os.path.join(QATOOLS_ROOT, DATA_BASE_DIR, "roku_test_log")
_ACTIVATE_JOBS = os.path.join(_BACKEND_CONF_DIR, "activate_jobs.json")
_DONUT_RUNS = os.path.join(QATOOLS_ROOT, "data", "donut_runs.json")

# How many rows each card's "recent" list shows.
_RECENT = 5
# Run-in-local: the result statuses reported per case, how many case rows the
# card returns, and how many log files it is willing to crunch (newest win).
_RESULT_STATUSES = ("Pass", "Fail", "Skipped", "Blocked")
_CASE_ROWS = 8
_MAX_LOG_SCAN = 300
# Run Case: statuses a summary report's tasks can carry, and how many reports
# (newest first) the card lists.
_REPORT_STATUSES = ("Pass", "Failed", "Blocked", "Skipped", "Aborted", "Unknown")
_REPORT_ROWS = 8
# TestRail Case: the statuses a cached snapshot can hold (file name suffix /
# the `status` field) and how many plans the card lists.
_TESTRAIL_STATUSES = (
    "Passed",
    "Failed",
    "Blocked",
    "Retest",
    "Broken",
    "For Review",
    "Untested",
)
_CACHED_ROWS = 10
# TestRail Case: how many plans the card lists (worst Failed ratio first).
_TESTRAIL_ROWS = 8
# Reference / Activate: how many tiles those cards draw (3x3 and 2x3 grids).
_REFERENCE_TILES = 9
_ACTIVATE_TILES = 6
# Activate: log markers used to tell a finished job's outcome apart (mirrors
# activate_controller._job_result).
_ACTIVATE_LOG_DIR = os.path.join(QATOOLS_ROOT, "5_activate", "logs")
# Analyze History: how many ranked cases the card lists.
_RANK_ROWS = 10


# ---------- small helpers ----------
def _listdir(path: str) -> list[str]:
    try:
        return os.listdir(path)
    except OSError:
        return []


def _json_file(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _conf_section(store, section: str, default=None):
    """Read a backend/conf section through the data service (never raises).

    The dashboard is read-only and best-effort: a missing/broken data file just
    renders an empty card instead of failing the whole page.
    """
    try:
        value = store.get_section(section)
    except DataServiceError:
        value = None
    return default if value is None else value


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:  # exists, just not ours
        return True
    except OSError:
        return False


def _counter_series(counter: Counter) -> list[dict]:
    """Counter -> [{name, value}] sorted by value desc (chart friendly)."""
    return [
        {"name": str(k), "value": int(v)}
        for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
    ]


def _log_result_counts(path: str) -> Counter:
    """Count the ``res: <status>`` markers in one roku_test log.

    Mirrors roku_test_controller._parse_result: 'res: Error' is folded into Fail
    so the card only ever reports the four statuses the Run-in-local tab shows.
    """
    counts: Counter = Counter()
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return counts
    for status in ("Pass", "Fail", "Skipped", "Blocked", "Error"):
        hits = content.count(f"res: {status}")
        if hits:
            counts["Fail" if status == "Error" else status] += hits
    return counts


def _known_devices() -> set[str]:
    """Device names from config/device_conf (used to disambiguate log names)."""
    return {
        f[: -len(".json")] for f in _listdir(_DEVICE_CONF_DIR) if f.endswith(".json")
    }


def _parse_log_name(name: str, devices: set[str]) -> tuple[str, str, str, str] | None:
    """Split a roku_test log file name into (case, testrail_id, device, stamp).

    Two layouts exist in data/roku_test_log:
      current: roku_test__{automation_id}__{testrail_case_id}__{device}__{repeat}__{ts}
      legacy:  roku_test__{device}__{automation_id}__{testrail_case_id}__{repeat}__{ts}
    They are told apart by which slot holds a known device name; if neither
    does (the device config was since renamed/removed) the current layout is
    assumed, which is what new runs always produce.
    """
    parts = name[: -len(".log")].split("__") if name.endswith(".log") else []
    if len(parts) < 4 or parts[0] != "roku_test":
        return None
    stamp = parts[-1]
    if parts[1] in devices:  # legacy: device first
        return parts[2], parts[3], parts[1], stamp
    return parts[1], parts[2], parts[3], stamp


def _status_key(status: str) -> str:
    """Row field name for a status ('For Review' -> 'for_review')."""
    return status.lower().replace(" ", "_")


def _status_breakdown(counts: Counter, statuses: tuple[str, ...]) -> dict:
    """Flatten a status Counter into `{status: n, status_pct: %}` fields."""
    total = sum(counts.values())
    out: dict = {}
    for status in statuses:
        count = int(counts.get(status, 0))
        key = _status_key(status)
        out[key] = count
        # Share of this row's results, in percent (0 when nothing ran).
        out[f"{key}_pct"] = round(count * 100.0 / total, 1) if total else 0.0
    return out


def _safe(name: str, fn):
    """Run one widget builder, never letting it break the whole response."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dashboard widget '%s' failed: %s", name, exc)
        return {"error": str(exc)}


# ---------- per-tab widgets ----------
def _device_card() -> dict:
    """Device: total configs + how many carry each optional sub-config."""
    files = sorted(f for f in _listdir(_DEVICE_CONF_DIR) if f.endswith(".json"))
    flags = Counter()
    with_ip = 0
    recent: list[dict] = []
    for fname in files:
        path = os.path.join(_DEVICE_CONF_DIR, fname)
        roku = {}
        data = _json_file(path, {})
        if isinstance(data, dict) and isinstance(data.get("roku"), dict):
            roku = data["roku"]
        devices_config = roku.get("devices_config")
        if not isinstance(devices_config, dict):
            devices_config = {}
        if roku.get("ip_address"):
            with_ip += 1
        features: list[str] = []
        for key, present in (
            ("qa_bot", "qa_bot_config" in roku),
            ("maxwell", "maxwell_config" in roku),
            ("power", "power_config" in roku),
            ("avr", "avr_info_config" in roku),
            ("hdmi", bool(devices_config)),
            (
                "stb",
                any(
                    (v or {}).get("device_type") == "ROKU"
                    for v in devices_config.values()
                    if isinstance(v, dict)
                ),
            ),
        ):
            if present:
                flags[key] += 1
                features.append(key)
        recent.append(
            {
                "name": fname[: -len(".json")],
                "ip_address": str(roku.get("ip_address") or ""),
                # device serial / id, shown next to the name on the Dashboard
                "serial_number": str(roku.get("serial_number") or ""),
                "device_id": str(roku.get("device_id") or ""),
                "features": features,
            }
        )
    return {
        "total": len(files),
        "with_ip": with_ip,
        "without_ip": len(files) - with_ip,
        # chart: how many devices have each optional sub-config
        "chart": [
            {"name": label, "value": flags[key]}
            for key, label in (
                ("qa_bot", "QA Bot"),
                ("maxwell", "Maxwell"),
                ("power", "Power"),
                ("avr", "AVR"),
                ("hdmi", "HDMI"),
                ("stb", "STB"),
            )
        ],
        "recent": recent[:_RECENT],
    }


def _profile_card() -> dict:
    """Profile: run profiles + the testrail_data snapshots they build from."""
    profiles = sorted(f for f in _listdir(_PROFILE_CONF_DIR) if f.endswith(".json"))
    testrail_data = sorted(
        f for f in _listdir(TESTRAIL_DATA_PATH) if f.endswith(".json")
    )
    cases = Counter()
    # Per-profile detail for the Dashboard's Profile card: how many tasks each
    # profile runs, in which execution mode, over which devices / case types.
    rows: list[dict] = []
    case_types: Counter = Counter()
    modes: Counter = Counter()
    devices_all: set[str] = set()
    for fname in profiles[:200]:
        data = _json_file(os.path.join(_PROFILE_CONF_DIR, fname), {})
        if not isinstance(data, dict):
            data = {}
        tasks = data.get("tasks")
        tasks = tasks if isinstance(tasks, list) else []
        count = 0
        for value in data.values():
            if isinstance(value, (list, dict)):
                count += len(value)
        name = fname[: -len(".json")]
        cases[name] = count

        p_types: Counter = Counter()
        p_devices: set[str] = set()
        for task in tasks:
            if not isinstance(task, dict):
                continue
            cfg = task.get("config")
            cfg = cfg if isinstance(cfg, dict) else {}
            p_types[str(cfg.get("case_type") or "OTHER").upper()] += 1
            device = str(cfg.get("device") or "")
            if device:
                p_devices.add(device)
        mode = str(data.get("execution_mode") or "").upper() or "SERIAL"
        modes[mode] += 1
        case_types.update(p_types)
        devices_all |= p_devices
        rows.append(
            {
                "name": name,
                "tasks": len(tasks),
                "entries": count,
                "execution_mode": mode,
                "devices": sorted(p_devices),
                "device_count": len(p_devices),
                "case_types": dict(p_types),
                "description": str(data.get("description") or ""),
            }
        )
    rows.sort(key=lambda r: (-int(r["tasks"] or 0), str(r["name"])))
    return {
        "total": len(profiles),
        "testrail_data_files": len(testrail_data),
        "tasks_total": sum(int(r["tasks"] or 0) for r in rows),
        "devices_total": len(devices_all),
        "case_types": dict(case_types),
        "modes": dict(modes),
        # chart: the biggest profiles by number of entries
        "chart": _counter_series(cases)[:6],
        "profile_rows": rows[:_REPORT_ROWS],
        "recent": [{"name": f[: -len(".json")]} for f in profiles[:_RECENT]],
    }


def _runcase_card() -> dict:
    """Run Case: the summary reports in time order, one row per profile run.

    Each ``{ts}_{profile}.json_summary_report.txt`` under data/runcase_report is
    a JSON doc ``{profile_name, count, tasks:[{status, ...}]}``, i.e. exactly one
    profile execution. The card lists the newest runs with how many cases the
    profile executed plus the per-status counts and their ratios, so a run's
    outcome mix is readable without opening the report.
    """
    suffix = ".json_summary_report.txt"
    # File names start with YYYYMMDD_HHMMSS, so a plain name sort IS time order.
    names = sorted(
        (f for f in _listdir(REPORT_PATH) if f.endswith(suffix)), reverse=True
    )

    rows: list[dict] = []
    totals: Counter = Counter()
    for name in names[:_REPORT_ROWS]:
        data = _json_file(os.path.join(REPORT_PATH, name), {})
        if not isinstance(data, dict):
            data = {}
        tasks = data.get("tasks")
        tasks = tasks if isinstance(tasks, list) else []
        counts: Counter = Counter()
        for task in tasks:
            if isinstance(task, dict):
                counts[str(task.get("status") or "Unknown")] += 1
        totals.update(counts)

        stamp = name[:15]  # YYYYMMDD_HHMMSS
        profile = str(data.get("profile_name") or name[16 : -len(suffix)] + ".json")
        executed = sum(counts.values())
        rows.append(
            {
                "file": name,
                # "2026-10-08 12:01:02" — readable run time from the file name.
                "at": (
                    f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]} "
                    f"{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}"
                    if len(stamp) == 15 and stamp[8] == "_"
                    else stamp
                ),
                "profile": profile[: -len(".json")]
                if profile.endswith(".json")
                else profile,
                # `count` is what the profile planned; tasks are what reported.
                "planned": int(data.get("count") or 0),
                "executed": executed,
                **_status_breakdown(counts, _REPORT_STATUSES),
                "other": sum(
                    n for s, n in counts.items() if s not in _REPORT_STATUSES
                ),
            }
        )

    # Live BDD runners, so the card still shows in-flight work.
    running = 0
    try:
        with os.popen(
            "ps -eo pid,args | grep test_runner.py | grep -v grep | wc -l"
        ) as fh:
            running = int((fh.read() or "0").strip() or 0)
    except (OSError, ValueError):
        running = 0

    grand_total = sum(totals.values())
    return {
        "running": running,
        "reports": len(names),
        "caches": len([f for f in _listdir(CASE_CACHE_PATH) if f.endswith(".cache")]),
        "cases": grand_total,
        "pass_rate": (
            round(int(totals.get("Pass", 0)) * 100.0 / grand_total, 1)
            if grand_total
            else 0.0
        ),
        "totals": {s.lower(): int(totals.get(s, 0)) for s in _REPORT_STATUSES},
        # Newest runs first — the card's main (stacked) chart.
        "report_rows": rows,
        # Overall status distribution across the listed runs, drawn as a donut.
        "pie": [
            {"name": s, "value": int(totals.get(s, 0))}
            for s in _REPORT_STATUSES
            if totals.get(s)
        ],
    }


def _rokutest_card() -> dict:
    """Run Case in local: per-case Pass/Fail/Skipped/Blocked counts + ratios.

    Jobs are NOT reported here (the tracking file only covers runs launched by
    the current backend and gets cleared); the durable source of truth is the
    log directory, where each file is one run named
    ``roku_test__{automation_id}__{testrail_case_id}__{device}__{repeat}__{ts}.log``
    (or the legacy device-first variant) and carries one ``res: <status>`` line
    per executed test.

    Counts are aggregated per automation_id (the case), so a case run many
    times shows its cumulative status mix and its pass ratio.
    """
    names = sorted(n for n in _listdir(_ROKU_TEST_LOG_DIR) if n.endswith(".log"))
    devices = _known_devices()

    # case key -> {counts, runs, testrail id, newest run timestamp}
    cases: dict[str, dict] = {}
    totals: Counter = Counter()
    for name in names[-_MAX_LOG_SCAN:]:
        parsed = _parse_log_name(name, devices)
        if parsed is None:
            continue
        case, testrail_id, _device, stamp = parsed

        counts = _log_result_counts(os.path.join(_ROKU_TEST_LOG_DIR, name))
        entry = cases.setdefault(
            case,
            {
                "case": case,
                "testrail_case_id": testrail_id,
                "runs": 0,
                "last_run": "",
                "counts": Counter(),
            },
        )
        entry["runs"] += 1
        if stamp > entry["last_run"]:
            entry["last_run"] = stamp
            entry["testrail_case_id"] = testrail_id or entry["testrail_case_id"]
        entry["counts"].update(counts)
        totals.update(counts)

    def _row(entry: dict) -> dict:
        counts = entry["counts"]
        return {
            "case": entry["case"],
            # Short display label: drop the TestCase class prefix if present.
            "label": entry["case"].split(".")[-1],
            "testrail_case_id": entry["testrail_case_id"],
            "runs": entry["runs"],
            "last_run": entry["last_run"],
            "total": sum(counts.values()),
            **_status_breakdown(counts, _RESULT_STATUSES),
        }

    rows = [_row(e) for e in cases.values()]
    # Most-exercised cases first; ties broken by run count then name.
    rows.sort(key=lambda r: (-r["total"], -r["runs"], r["case"]))

    grand_total = sum(totals.values())
    return {
        "cases": len(rows),
        "runs": sum(r["runs"] for r in rows),
        "results": grand_total,
        # Overall status totals + global pass ratio, for the header stats.
        "totals": {s.lower(): int(totals.get(s, 0)) for s in _RESULT_STATUSES},
        "pass_rate": (
            round(int(totals.get("Pass", 0)) * 100.0 / grand_total, 1)
            if grand_total
            else 0.0
        ),
        # Per-case stacked rows (counts + percentages) — the card's main chart.
        "case_rows": rows[:_CASE_ROWS],
        # Overall status distribution, drawn as a donut.
        "pie": [
            {"name": s, "value": int(totals.get(s, 0))}
            for s in _RESULT_STATUSES
            if totals.get(s)
        ],
    }


def _analyze_card() -> dict:
    """Analyze History: how often each case was analyzed, ranked.

    Every ``*.md`` under data/analyzer_history is one saved analysis, named
    ``{testrail_case_id}__{profile}__{case_id}__{result}__{locale}__{ts}``. The
    card ranks cases by how many analyses they accumulated — i.e. the cases that
    keep needing a look — instead of showing an activity trend.
    """
    from . import analyze_history_controller as ahc

    names = [n for n in _listdir(ANALYZER_PATH) if n.lower().endswith(".md")]
    records = [ahc._parse(n) for n in names]
    records.sort(key=lambda r: r.get("datetime", ""), reverse=True)

    def _verdict(rec: dict) -> str:
        """Normalized verdict: 'Fail' and 'Failed' are the same outcome."""
        value = (rec.get("result") or "Unknown").title()
        return "Failed" if value in ("Fail", "Failed") else value

    results = Counter(_verdict(r) for r in records)

    # Group by case: count analyses, remember the TestRail id and newest run.
    cases: dict[str, dict] = {}
    for rec in records:
        case = rec.get("case_id") or "(unknown)"
        entry = cases.setdefault(
            case,
            {
                "case": case,
                "testrail_case_id": rec.get("testrail_case_id", ""),
                "count": 0,
                "last": "",
                "results": Counter(),
            },
        )
        entry["count"] += 1
        entry["results"][_verdict(rec)] += 1
        stamp = rec.get("datetime", "")
        if stamp > entry["last"]:
            entry["last"] = stamp
            entry["testrail_case_id"] = (
                rec.get("testrail_case_id") or entry["testrail_case_id"]
            )

    # Most-analyzed first; ties broken by the newest analysis (python's sort is
    # stable, so ranking by count over a date-sorted list keeps that order).
    ranked = sorted(cases.values(), key=lambda e: e["last"], reverse=True)
    ranked.sort(key=lambda e: e["count"], reverse=True)
    total = len(records)
    rank_rows = [
        {
            "rank": i + 1,
            "case": e["case"],
            # Short display label: drop the TestCase class prefix if present.
            "label": str(e["case"]).split(".")[-1],
            "testrail_case_id": e["testrail_case_id"],
            "count": e["count"],
            # Share of all saved analyses, in percent.
            "pct": round(e["count"] * 100.0 / total, 1) if total else 0.0,
            "last": e["last"],
            # Dominant verdict for this case, as a hint of why it keeps coming up.
            "top_result": (e["results"].most_common(1) or [("", 0)])[0][0],
        }
        for i, e in enumerate(ranked[:_RANK_ROWS])
    ]

    # Per-verdict detail, so the donut's tooltip can explain a slice: how many
    # distinct cases it covers, the TestRail ids involved, the newest analysis
    # and its top cases.
    by_result: dict[str, dict] = {}
    for rec in records:
        verdict = _verdict(rec)
        entry = by_result.setdefault(
            verdict,
            {
                "cases": Counter(),
                "last": "",
                "locales": Counter(),
                "testrail_ids": Counter(),
            },
        )
        entry["cases"][str(rec.get("case_id") or "(unknown)").split(".")[-1]] += 1
        entry["locales"][str(rec.get("locale") or "")] += 1
        tr_id = str(rec.get("testrail_case_id") or "").strip()
        if tr_id:
            entry["testrail_ids"][tr_id] += 1
        stamp = rec.get("datetime", "")
        if stamp > entry["last"]:
            entry["last"] = stamp
    pie_detail = [
        {
            "name": verdict,
            "value": int(results.get(verdict, 0)),
            "pct": round(results.get(verdict, 0) * 100.0 / total, 1) if total else 0.0,
            "cases": len(entry["cases"]),
            "last": entry["last"],
            "locales": [loc for loc, _ in entry["locales"].most_common(3) if loc],
            # TestRail ids seen for this verdict, most frequent first.
            "testrail_ids": [
                tr_id for tr_id, _ in entry["testrail_ids"].most_common(8)
            ],
            "testrail_id_count": len(entry["testrail_ids"]),
            "top_cases": [
                {"label": label, "count": count}
                for label, count in entry["cases"].most_common(3)
            ],
        }
        for verdict, entry in sorted(
            by_result.items(), key=lambda kv: -results.get(kv[0], 0)
        )
    ]

    return {
        "total": total,
        "cases": len(cases),
        "today": sum(
            1 for r in records if r.get("date") == datetime.now().date().isoformat()
        ),
        # The card's main content: the analysis-count ranking.
        "rank_rows": rank_rows,
        # Overall verdict distribution, drawn as a donut.
        "pie": _counter_series(results)[:6],
        # Same slices, with the extra numbers the donut's tooltip shows.
        "pie_detail": pie_detail[:6],
    }


def _testrail_card() -> dict:
    """TestRail Case: cached case counts per plan, broken down by status.

    Each ``{plan}_{status}.json`` under data/testrail_data is one fetch of a
    plan's cases for one status (``{plan, status, count, cases:[...]}``). The
    card groups those files by plan and reports the per-status case counts, so
    one stacked bar per plan shows at a glance where the cases sit (how much is
    Failed vs Blocked vs Retest ...) and how fresh the data is.

    Only plans that still exist in the TestRail config are reported (cached
    files of deleted plans are ignored), and the rows are ordered by the
    highest Failed ratio first, i.e. the ones worth looking at.
    """
    plans = (_conf_section(TESTRAIL_STORE, "testrail", {}) or {}).get("plan") or []
    if not isinstance(plans, list):
        plans = []
    # Plan id -> display name, so a cached plan can be labelled.
    plan_names = {
        str(p.get("id")): str(p.get("name") or "")
        for p in plans
        if isinstance(p, dict) and p.get("id") is not None
    }

    # plan id -> {per-status case counts, file count, newest mtime}
    grouped: dict[str, dict] = {}
    totals: Counter = Counter()
    for name in _listdir(TESTRAIL_DATA_PATH):
        if not name.endswith(".json"):
            continue
        path = os.path.join(TESTRAIL_DATA_PATH, name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0
        data = _json_file(path, {})
        if not isinstance(data, dict):
            data = {}
        cases = data.get("cases")
        plan = str(data.get("plan") or name.split("_")[0])
        # Drop cached data whose plan was removed from the TestRail config.
        if plan not in plan_names:
            continue
        # File names sanitize spaces to '_' ("For Review" -> "For_Review").
        status = str(data.get("status") or "").replace("_", " ").strip()
        count = int(
            data.get("count")
            if isinstance(data.get("count"), int)
            else (len(cases) if isinstance(cases, list) else 0)
        )

        entry = grouped.setdefault(
            plan,
            {
                "plan": plan,
                "plan_name": plan_names.get(plan, ""),
                "files": 0,
                "mtime": 0.0,
                "counts": Counter(),
            },
        )
        entry["files"] += 1
        entry["mtime"] = max(entry["mtime"], mtime)
        if status:
            entry["counts"][status] += count
            totals[status] += count

    def _row(entry: dict) -> dict:
        counts = entry["counts"]
        total = sum(counts.values())
        bad = int(counts.get("Failed", 0)) + int(counts.get("Blocked", 0))
        return {
            "plan": entry["plan"],
            "plan_name": entry["plan_name"],
            "files": entry["files"],
            "cases": total,
            # Failed + Blocked, the "needs attention" share this card ranks by.
            "bad": bad,
            "bad_pct": round(bad * 100.0 / total, 1) if total else 0.0,
            "at": datetime.fromtimestamp(entry["mtime"]).strftime("%Y-%m-%d %H:%M")
            if entry["mtime"]
            else "",
            **_status_breakdown(counts, _TESTRAIL_STATUSES),
        }

    rows = [_row(e) for e in grouped.values()]
    # Freshest first, then (stable) worst Failed share first: the card ranks by
    # the Failed ratio, falling back to Failed+Blocked and then case counts, so
    # ties keep the most recently pulled plan on top.
    rows.sort(key=lambda r: r["at"], reverse=True)
    rows.sort(
        key=lambda r: (
            -float(r.get("failed_pct") or 0),
            -int(r.get("failed") or 0),
            -float(r.get("bad_pct") or 0),
            -int(r.get("bad") or 0),
        )
    )

    return {
        "plans": len(plans),
        "cached_plans": len(rows),
        "cached_files": sum(r["files"] for r in rows),
        "cases": sum(totals.values()),
        "totals": {_status_key(s): int(totals.get(s, 0)) for s in _TESTRAIL_STATUSES},
        # One row per plan, worst Failed ratio first — the card's chart.
        "plan_rows": rows[:_TESTRAIL_ROWS],
    }


def _agent_card() -> dict:
    """Prompt: the active model, configured models, sessions and skills."""
    agent_conf = _conf_section(AGENT_STORE, "agent_config", {}) or {}
    models = _conf_section(AGENT_STORE, "agent_model", []) or []
    sessions = []
    for name in _listdir(AGENT_SESSION_PATH):
        if not name.endswith(".json"):
            continue
        obj = _json_file(os.path.join(AGENT_SESSION_PATH, name), {})
        if not isinstance(obj, dict):
            continue
        sessions.append(
            {
                "id": obj.get("id", name[:-5]),
                "title": obj.get("title") or "(untitled)",
                "updated": obj.get("updated", 0),
                "count": len(obj.get("messages") or []),
            }
        )
    sessions.sort(key=lambda s: s.get("updated", 0), reverse=True)
    skills = [
        d
        for d in _listdir(SKILL_DATA_PATH)
        if os.path.isfile(os.path.join(SKILL_DATA_PATH, d, "SKILL.md"))
    ]
    return {
        "model": str(agent_conf.get("model") or ""),
        "models": len(models) if isinstance(models, list) else 0,
        "sessions": len(sessions),
        "skills": len(skills),
        "messages": sum(s["count"] for s in sessions),
        # chart: message count of the busiest sessions
        "chart": [{"name": s["title"][:18], "value": s["count"]} for s in sessions[:6]],
        "recent": sessions[:_RECENT],
    }


def _reference_card() -> dict:
    """Reference: link/doc counts and how they split across categories."""
    refs = _conf_section(REF_STORE, "ref", []) or []
    docs = _conf_section(REF_STORE, "docs", []) or []
    refs = refs if isinstance(refs, list) else []
    docs = docs if isinstance(docs, list) else []

    def _cat(it) -> str:
        return str((it or {}).get("category") or "uncategorized")

    ref_cats = Counter(_cat(it) for it in refs if isinstance(it, dict))
    doc_cats = Counter(_cat(it) for it in docs if isinstance(it, dict))
    categories = ref_cats + doc_cats
    doc_files = [f for f in _listdir(DOCS_DATA_PATH) if not f.startswith(".")]

    def _rows(counter: Counter) -> list[dict]:
        """Category rows for one item type, biggest first."""
        return [
            {"name": name, "value": int(total)}
            for name, total in counter.most_common(_REFERENCE_TILES)
        ]

    # One row per category, biggest first: used by the card's tile grid.
    cat_rows = [
        {
            "name": name,
            "value": int(total),
            "refs": int(ref_cats.get(name, 0)),
            "docs": int(doc_cats.get(name, 0)),
        }
        for name, total in categories.most_common(_REFERENCE_TILES)
    ]
    return {
        "refs": len(refs),
        "docs": len(docs),
        "doc_files": len(doc_files),
        "categories": len(categories),
        # chart: items per category
        "chart": _counter_series(categories)[:6],
        "category_rows": cat_rows,
        # Per-type category splits, so the card can group Links vs Docs.
        "link_rows": _rows(ref_cats),
        "doc_rows": _rows(doc_cats),
        "recent": [
            {"name": str((it or {}).get("name") or ""), "kind": "ref"}
            for it in refs[:_RECENT]
            if isinstance(it, dict)
        ],
    }


def _file_transfer_card() -> dict:
    """File Transfer: the shared root's size/shape + http server state."""
    conf = _conf_section(FILE_TRANSFER_STORE, "file_transfer", {}) or {}
    root = str(conf.get("root") or os.path.join(QATOOLS_ROOT, "data", "file_transfer"))
    files = 0
    dirs = 0
    total_size = 0
    by_ext = Counter()
    for base, dirnames, filenames in os.walk(root):
        dirs += len(dirnames)
        for name in filenames:
            files += 1
            ext = (os.path.splitext(name)[1] or "(none)").lower()
            try:
                size = os.path.getsize(os.path.join(base, name))
            except OSError:
                size = 0
            total_size += size
            by_ext[ext] += 1
    servers = conf.get("scp_server_cache") or []
    pid_file = os.path.join(root, ".http_server.pid")
    http_running = False
    info = _json_file(pid_file, {})
    if isinstance(info, dict) and info.get("pid"):
        http_running = _pid_alive(int(info.get("pid") or 0))
    return {
        "root": root,
        "files": files,
        "dirs": dirs,
        "total_size": total_size,
        "http_port": conf.get("http_port", 9000),
        "http_running": http_running,
        "scp_servers": len(servers) if isinstance(servers, list) else 0,
        # chart: file count per extension
        "chart": _counter_series(by_ext)[:6],
    }


def _donut_card() -> dict:
    """Donuts: the runs launched from QATools (local record only, no QA Hub)."""
    runs = _json_file(_DONUT_RUNS, [])
    if not isinstance(runs, list):
        runs = []
    products = Counter(str(r.get("product") or "unknown") for r in runs)
    return {
        "total": len(runs),
        "products": len(products),
        # chart: runs per product
        "chart": _counter_series(products)[:6],
        "recent": [
            {
                "donut": r.get("donut", ""),
                "product": r.get("product", ""),
                "branch": r.get("branch", ""),
                "device": r.get("device_name", r.get("serial_number", "")),
                "created": r.get("created", r.get("at", "")),
            }
            for r in runs[:_RECENT]
        ],
    }


def _activate_result(log_file: str) -> str:
    """Coarse outcome of a finished job from its log (same rules as the tab).

    return: "Success" | "Failed" | "Unknown"
    """
    if not log_file:
        return "Unknown"
    try:
        with open(
            os.path.join(_ACTIVATE_LOG_DIR, log_file), encoding="utf-8", errors="replace"
        ) as fh:
            low = fh.read().lower()
    except OSError:
        return "Unknown"
    if "guided setup complete" in low or "activation successful" in low:
        return "Success"
    if "'success': true" in low or '"success": true' in low:
        return "Success"
    if "traceback (most recent call last)" in low or "error" in low:
        return "Failed"
    return "Unknown"


def _activate_card() -> dict:
    """Activate: tracked conversion jobs, by state and by mode."""
    jobs = _json_file(_ACTIVATE_JOBS, [])
    if not isinstance(jobs, list):
        jobs = []
    running = sum(1 for j in jobs if _pid_alive(int(j.get("pid") or 0)))
    modes = Counter(str(j.get("mode") or "unknown") for j in jobs)

    recent: list[dict] = []
    for j in jobs[:_ACTIVATE_TILES]:
        is_running = _pid_alive(int(j.get("pid") or 0))
        log_file = j.get("log_file", "")
        recent.append(
            {
                "id": j.get("id", ""),
                "device": j.get("device_name", j.get("device", "")),
                "mode": j.get("mode", ""),
                "running": is_running,
                # "" while running, else Success / Failed / Unknown.
                "result": "" if is_running else _activate_result(log_file),
                "started": j.get(
                    "started", j.get("started_at", j.get("start_time", ""))
                ),
                "log_file": log_file,
            }
        )
    return {
        "total": len(jobs),
        "running": running,
        "finished": len(jobs) - running,
        # chart: jobs per conversion mode
        "chart": _counter_series(modes)[:6],
        "recent": recent,
    }


_WIDGETS = {
    "device": _device_card,
    "profile": _profile_card,
    "runcase": _runcase_card,
    "rokutest": _rokutest_card,
    "analyzehistory": _analyze_card,
    "testrail": _testrail_card,
    "agent": _agent_card,
    "reference": _reference_card,
    "filetransfer": _file_transfer_card,
    "donuts": _donut_card,
    "activate": _activate_card,
}


@router.get("/v1/dashboard/summary")
def dashboard_summary() -> dict:
    """One snapshot for every Dashboard card (all local reads, no external HTTP).

    return:
    {
      "generated_at": "2026-01-01T10:00:00",
      "cards": {"device": {...}, "profile": {...}, ...}
    }

    Each card is independent and best-effort: a failing one comes back as
    {"error": "..."} instead of failing the request.
    """
    logger.info("Build dashboard summary")
    cards = {key: _safe(key, fn) for key, fn in _WIDGETS.items()}
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cards": cards,
    }


@router.get("/v1/dashboard/card/{name}")
def dashboard_card(name: str) -> dict:
    """Refresh a single card (same payload shape as one entry of /summary)."""
    fn = _WIDGETS.get(name)
    if fn is None:
        return {"error": f"Unknown dashboard card '{name}'"}
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "card": _safe(name, fn),
    }
