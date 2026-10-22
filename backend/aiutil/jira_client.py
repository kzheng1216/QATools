#!/usr/bin/env python3

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from config.env import EMAIL, JIRA_TOKEN, JIRA_URL

from . import logger

_AUTH = base64.b64encode(f"{EMAIL}:{JIRA_TOKEN}".encode()).decode()
_HEADERS = {
    "Authorization": f"Basic {_AUTH}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
_BASE = JIRA_URL.rstrip("/")


class JiraError(Exception):
    """Raised when the JIRA API returns an error."""


async def search_jql(
    jql: str, *, max_results: int = 25, fields: list[str] | None = None
) -> list[dict[str, Any]]:
    """Run a JQL query and return a compact list of issues.

    Uses the v3 /search/jql endpoint (v2 /search was removed by Atlassian).
    """
    field_list = fields or [
        "key",
        "summary",
        "status",
        "assignee",
        "issuetype",
        "priority",
        "resolutiondate",
        "updated",
    ]
    params = {
        "jql": jql,
        "maxResults": max_results,
        "fields": ",".join(field_list),
    }
    url = f"{_BASE}/rest/api/3/search/jql"
    async with httpx.AsyncClient(timeout=30.0, headers=_HEADERS) as client:
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.exception("JIRA JQL transport failure")
            raise JiraError(f"JIRA transport error: {exc}") from exc

    if resp.status_code >= 400:
        logger.error("JIRA JQL %s: %s", resp.status_code, resp.text[:400])
        raise JiraError(f"JIRA {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    if data.get("errorMessages"):
        raise JiraError("; ".join(data["errorMessages"]))

    return [_compact_issue(i) for i in data.get("issues", [])]


def _compact_issue(issue: dict[str, Any]) -> dict[str, Any]:
    f = issue.get("fields", {}) or {}
    assignee = f.get("assignee") or {}
    status = f.get("status") or {}
    itype = f.get("issuetype") or {}
    prio = f.get("priority") or {}
    key = issue.get("key", "")
    return {
        "key": key,
        "url": f"{_BASE}/browse/{key}",
        "summary": f.get("summary", ""),
        "status": status.get("name", ""),
        "type": itype.get("name", ""),
        "priority": prio.get("name", ""),
        "assignee": assignee.get("displayName", ""),
        "resolved": f.get("resolutiondate"),
        "updated": f.get("updated"),
    }


def jql_context() -> str:
    """Return a dated JQL-authoring cheat-sheet for the model.

    Gives the model today's date and last-week boundaries so it can build
    correct date ranges, and tells it currentUser() maps to the caller.
    """
    today = datetime.now(tz=UTC).date()
    # Monday of the current ISO week, then previous week's Mon..Sun.
    this_mon = today - timedelta(days=today.weekday())
    last_mon = this_mon - timedelta(days=7)
    last_sun = this_mon - timedelta(days=1)
    return (
        f"Today is {today.isoformat()} ({today.strftime('%A')}). "
        f'"Last week" = {last_mon.isoformat()} (Mon) to {last_sun.isoformat()} '
        f"(Sun). This week started {this_mon.isoformat()} (Mon). "
        "In JQL, currentUser() is the person asking. "
        'For "completed/done/closed/resolved" issues, prefer '
        'status CHANGED TO ("Done","Closed","Resolved","Fixed") DURING '
        '(start, "end 23:59"). Always add ORDER BY updated DESC.'
    )


def format_issues(issues: list[dict[str, Any]]) -> str:
    """Turn JQL results into a context block for the model."""
    if not issues:
        return "(No JIRA issues matched the query.)"
    lines = []
    for it in issues:
        lines.append(
            f"- {it['key']} ({it['status']}) [{it['type']}] {it['summary']}\n"
            f"  {it['url']}"
        )
    return "\n".join(lines)
