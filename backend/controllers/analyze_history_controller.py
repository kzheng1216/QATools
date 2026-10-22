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


@router.get("/v1/analyze_history/list")
def list_history(
    case_id: str | None = None,
    profile: str | None = None,
    result: str | None = None,
    date: str | None = None,
) -> dict:
    """List saved analyses (newest first), with optional filters.

    Filters are case-insensitive substring matches, except `result` which is an
    exact (case-insensitive) match and `date` which is a prefix match (YYYY,
    YYYY-MM, or YYYY-MM-DD).
    """
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
