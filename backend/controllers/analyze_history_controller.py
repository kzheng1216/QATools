# backend/controllers/analyze_history_controller.py
"""Analyze History: list / view / delete the saved analysis markdown files."""

import os
import sys

from fastapi import APIRouter, HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import ANALYZER_PATH

from . import logger

router = APIRouter()

analyze_history_dir = os.path.abspath(ANALYZER_PATH)


def _history_file(name: str) -> str:
    # Guard against path traversal; files live flat in analyze_history_dir.
    if os.path.basename(name) != name or not name:
        raise HTTPException(status_code=400, detail=f"Invalid file name '{name}'")
    if not name.lower().endswith(".md"):
        raise HTTPException(status_code=400, detail="Only .md files are supported")
    return os.path.join(analyze_history_dir, name)


def _profile_report_file(name: str) -> str:
    """Validate and resolve a profile analyze report (.yml) file name."""
    if os.path.basename(name) != name or not name:
        raise HTTPException(status_code=400, detail=f"Invalid file name '{name}'")
    if not name.lower().endswith((".yml", ".yaml")):
        raise HTTPException(status_code=400, detail="Only .yml files are supported")
    return os.path.join(analyze_history_dir, name)


def _parse(name: str) -> dict:
    """Parse a history file name into structured fields.

    Returns a record with best-effort fields; unparseable names still list with
    the raw name so nothing is hidden.
    """
    base = name[:-3] if name.lower().endswith(".md") else name
    parts = base.split("__")
    rec = {
        "name": name,
        "testrail_case_id": "",
        "profile": "",
        "case_id": "",
        "result": "",
        "locale": "",
        "datetime": "",
        "date": "",
    }
    # Current format:
    #   testrail_case_id__profile__case_id__result__locale__YYYY-MM-DD_HH-MM-SS
    if len(parts) == 6:
        (
            rec["testrail_case_id"],
            rec["profile"],
            rec["case_id"],
            rec["result"],
            rec["locale"],
            dt,
        ) = parts
        rec["datetime"] = dt
        rec["date"] = dt.split("_")[0] if "_" in dt else dt
    # Legacy (no profile): testrail_case_id__case_id__result__locale__datetime
    elif len(parts) == 5:
        (
            rec["testrail_case_id"],
            rec["case_id"],
            rec["result"],
            rec["locale"],
            dt,
        ) = parts
        rec["datetime"] = dt
        rec["date"] = dt.split("_")[0] if "_" in dt else dt
    # Legacy (no testrail id/profile): case_id__result__locale__datetime
    elif len(parts) == 4:
        rec["case_id"], rec["result"], rec["locale"], dt = parts
        rec["datetime"] = dt
        rec["date"] = dt.split("_")[0] if "_" in dt else dt
    return rec


def _parse_profile_report(name: str) -> dict:
    """Parse a profile report file name into structured fields."""
    base = name.rsplit(".", 1)[0]
    parts = base.split("__")
    rec = {
        "name": name,
        "profile_name": "",
        # Reports written by older runs have no `status:` line; treat them as
        # finished so they still show their case links.
        "status": "completed",
        "count_nopass_case": 0,
        "count_case": 0,
        "locale": "",
        "datetime": "",
        "date": "",
        "case_analyze_report": [],
    }
    # p__<profile>__<nopass>__<count>__<locale>__<YYYY-MM-DD_HH-MM-SS>
    if len(parts) >= 6 and parts[0] == "p":
        rec["profile_name"] = "__".join(parts[1:-4])
        nopass, count, locale, dt = parts[-4:]
        rec["count_nopass_case"] = int(nopass) if nopass.isdigit() else 0
        rec["count_case"] = int(count) if count.isdigit() else 0
        rec["locale"] = locale
        rec["datetime"] = dt
        rec["date"] = dt.split("_")[0] if "_" in dt else dt
    return rec


def _read_profile_report(name: str) -> dict:
    """Parse name + body of a profile report (body wins where available)."""
    rec = _parse_profile_report(name)
    path = os.path.join(analyze_history_dir, name)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return rec

    in_list = False
    reports: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("case_analyze_report:"):
            in_list = True
            continue
        if in_list:
            if stripped.startswith("-"):
                item = stripped.lstrip("-").strip().strip("'\"")
                if item:
                    reports.append(item)
                continue
            if stripped and not line.startswith((" ", "\t")):
                in_list = False
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key, value = key.strip(), value.strip()
        if key == "profile_name" and value:
            rec["profile_name"] = value
        elif key == "status" and value:
            rec["status"] = value
        elif key == "count_nopass_case" and value.isdigit():
            rec["count_nopass_case"] = int(value)
        elif key == "count_case" and value.isdigit():
            rec["count_case"] = int(value)
        elif key == "date" and value:
            rec["datetime"] = value
            rec["date"] = value.split("_")[0] if "_" in value else value
    rec["case_analyze_report"] = reports
    # Expose the testrail case id of each referenced case report for the UI.
    rec["cases"] = [
        {"testrail_case_id": _parse(r)["testrail_case_id"] or r, "name": r}
        for r in reports
    ]
    # How many of the non-passing cases have an analysis so far; the UI shows
    # "Analyzing n/m" until status flips to completed.
    rec["analyzed_count"] = len(reports)
    return rec


def _list_profile_report_names() -> list[str]:
    try:
        return [
            n
            for n in os.listdir(analyze_history_dir)
            if n.lower().endswith((".yml", ".yaml")) and n.startswith("p__")
        ]
    except OSError:
        return []


def _case_report_bindings() -> dict[str, list[str]]:
    """Map case report (.md) name -> profile reports (.yml) that reference it."""
    bindings: dict[str, list[str]] = {}
    for report in _list_profile_report_names():
        for case_report in _read_profile_report(report)["case_analyze_report"]:
            bindings.setdefault(case_report, []).append(report)
    return bindings


@router.get("/v1/analyze_history/profile/list")
def list_profile_reports(
    profile: str | None = None,
    locale: str | None = None,
    date: str | None = None,
) -> dict:
    """List profile analyze reports (newest first), with optional filters."""
    logger.info("List profile analyze reports from: %s", analyze_history_dir)
    records = [_read_profile_report(n) for n in _list_profile_report_names()]

    def _match(rec: dict) -> bool:
        if profile and profile.lower() not in rec["profile_name"].lower():
            return False
        if locale and locale.lower() != rec["locale"].lower():
            return False
        if date and not rec["date"].startswith(date):
            return False
        return True

    records = [r for r in records if _match(r)]
    records.sort(key=lambda r: r["datetime"] or r["name"], reverse=True)
    return {"items": records}


@router.get("/v1/analyze_history/profile/view")
def view_profile_report(name: str) -> dict:
    """Return the raw yaml content of a profile analyze report."""
    path = _profile_report_file(name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"File '{name}' not found")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as exc:
        logger.error("Error reading profile report '%s': %s", name, exc)
        raise HTTPException(
            status_code=500, detail=f"Error reading file '{name}'"
        ) from exc
    return {"name": name, "content": content, **_read_profile_report(name)}


@router.delete("/v1/analyze_history/profile/delete")
def delete_profile_report(name: str) -> dict:
    """Delete a profile analyze report file."""
    path = _profile_report_file(name)
    logger.info("Delete profile analyze report: %s", name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"File '{name}' not found")
    try:
        os.remove(path)
    except OSError as exc:
        logger.error("Error deleting profile report '%s': %s", name, exc)
        raise HTTPException(
            status_code=500, detail=f"Error deleting file '{name}'"
        ) from exc
    return {"message": f"'{name}' deleted successfully"}


@router.get("/v1/analyze_history/list")
def list_history(
    case_id: str | None = None,
    profile: str | None = None,
    result: str | None = None,
    date: str | None = None,
) -> dict:
    """List saved analyses (newest first), with optional filters."""
    logger.info("List analyze history from: %s", analyze_history_dir)
    try:
        names = [
            n for n in os.listdir(analyze_history_dir) if n.lower().endswith(".md")
        ]
    except OSError:
        names = []

    def _match(rec: dict) -> bool:
        if case_id and case_id.lower() not in rec["case_id"].lower():
            return False
        if profile and profile.lower() not in rec["profile"].lower():
            return False
        if result and result.lower() != rec["result"].lower():
            return False
        if date and not rec["date"].startswith(date):
            return False
        return True

    records = [_parse(n) for n in names]
    records = [r for r in records if _match(r)]
    # Tell the UI which case reports are bound to a profile report, so it can
    # disable their Delete button up front.
    bindings = _case_report_bindings()
    for r in records:
        r["bound_profile_reports"] = bindings.get(r["name"], [])
    # Newest first by the datetime field (falls back to name).
    records.sort(key=lambda r: r["datetime"] or r["name"], reverse=True)
    return {"items": records}


@router.get("/v1/analyze_history/categories")
def history_categories() -> dict:
    """Distinct case_id / result values across all files (for filter
    dropdowns)."""
    try:
        names = [
            n for n in os.listdir(analyze_history_dir) if n.lower().endswith(".md")
        ]
    except OSError:
        names = []
    recs = [_parse(n) for n in names]
    return {
        "case_ids": sorted({r["case_id"] for r in recs if r["case_id"]}),
        "results": sorted({r["result"] for r in recs if r["result"]}),
    }


@router.get("/v1/analyze_history/view")
def view_history(name: str) -> dict:
    """Return the markdown content of a saved analysis."""
    path = _history_file(name)
    logger.info("View analyze history: %s", name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"File '{name}' not found")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as exc:
        logger.error("Error reading analyze history '%s': %s", name, exc)
        raise HTTPException(
            status_code=500, detail=f"Error reading file '{name}'"
        ) from exc
    return {"name": name, "content": content}


@router.delete("/v1/analyze_history/delete")
def delete_history(name: str) -> dict:
    """Delete a saved analysis file."""
    path = _history_file(name)
    logger.info("Delete analyze history: %s", name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"File '{name}' not found")
    # Refuse to delete a case report that a profile report still references;
    # the profile report must be deleted first.
    bound = _case_report_bindings().get(name, [])
    if bound:
        logger.warning(
            "Refused to delete '%s': referenced by profile report(s) %s", name, bound
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"'{name}' is referenced by profile analyze report(s): "
                f"{', '.join(bound)}. Delete the profile report first."
            ),
        )
    try:
        os.remove(path)
    except OSError as exc:
        logger.error("Error deleting analyze history '%s': %s", name, exc)
        raise HTTPException(
            status_code=500, detail=f"Error deleting file '{name}'"
        ) from exc
    return {"message": f"'{name}' deleted successfully"}


if __name__ == "__main__":
    list_history()
