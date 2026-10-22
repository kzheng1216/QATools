import json
import os
import sys
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import AGENT_SESSION_PATH

from . import logger

agent_session_dir = os.path.abspath(AGENT_SESSION_PATH)

router = APIRouter()

# Cap on how many past messages are replayed to the model per turn.
_HISTORY_LIMIT = 30
# Max characters used from the first prompt to auto-generate a session title.
_TITLE_MAX = 40


def _ensure_dir() -> None:
    os.makedirs(agent_session_dir, exist_ok=True)


def _session_file(sid: str) -> str:
    # Guard against path traversal via a crafted session id.
    if os.path.basename(sid) != sid or not sid:
        raise HTTPException(status_code=400, detail=f"Invalid session id '{sid}'")
    return os.path.join(agent_session_dir, f"{sid}.json")


def _load(sid: str) -> dict:
    path = _session_file(sid)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Session '{sid}' not found")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        logger.error("Error reading session '%s': %s", sid, exc)
        raise HTTPException(
            status_code=500, detail=f"Error reading session '{sid}'"
        ) from exc


def _save(obj: dict) -> None:
    _ensure_dir()
    path = _session_file(obj["id"])
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.error("Error writing session '%s': %s", obj.get("id"), exc)
        raise HTTPException(
            status_code=500, detail=f"Error writing session '{obj.get('id')}'"
        ) from exc


def _new_id() -> str:
    return f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"


@router.get("/v1/session/list")
def list_sessions() -> dict:
    """List sessions (summary only) sorted by most-recently-updated first."""
    logger.info("List sessions from: %s", agent_session_dir)
    summaries: list[dict] = []
    try:
        names = [n for n in os.listdir(agent_session_dir) if n.endswith(".json")]
    except OSError:
        names = []
    for name in names:
        try:
            with open(
                os.path.join(agent_session_dir, name), "r", encoding="utf-8"
            ) as f:
                obj = json.load(f)
        except (OSError, ValueError):
            continue
        summaries.append(
            {
                "id": obj.get("id", name[:-5]),
                "title": obj.get("title") or "(untitled)",
                "updated": obj.get("updated", 0),
                "count": len(obj.get("messages", [])),
            }
        )
    summaries.sort(key=lambda s: s["updated"], reverse=True)
    return {"sessions": summaries}


@router.get("/v1/session/{sid}")
def get_session(sid: str) -> dict:
    """Return the full session object including all messages."""
    logger.info("Get session: %s", sid)
    return _load(sid)


@router.post("/v1/session/create")
def create_session() -> dict:
    """Create a new empty session and return it."""
    now = time.time()
    obj = {
        "id": _new_id(),
        "title": "",
        "created": now,
        "updated": now,
        "messages": [],
    }
    _save(obj)
    logger.info("Session '%s' created", obj["id"])
    return obj


@router.delete("/v1/session/delete/{sid}")
def delete_session(sid: str) -> dict:
    """Delete a session file."""
    logger.info("Delete session: %s", sid)
    path = _session_file(sid)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Session '{sid}' not found")
    try:
        os.remove(path)
    except OSError as exc:
        logger.error("Error deleting session '%s': %s", sid, exc)
        raise HTTPException(
            status_code=500, detail=f"Error deleting session '{sid}'"
        ) from exc
    return {"message": f"Session '{sid}' deleted successfully"}


# ---------- helpers used directly by the agent controller (no HTTP) ----------


def get_history(sid: str, limit: int = _HISTORY_LIMIT) -> list[dict]:
    """Return recent messages as [{role, content}, ...] for replay to the model.

    Returns an empty list if the session does not exist (chat must not fail
    just because a session id went stale).
    """
    path = _session_file(sid)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError):
        return []
    msgs = obj.get("messages", [])[-limit:]
    return [{"role": m["role"], "content": m["content"]} for m in msgs]


def append_turn(sid: str, user_text: str, assistant_text: str) -> None:
    """Append a user+assistant turn to the session, creating it if missing.

    Auto-generates the title from the first user message.
    """
    path = _session_file(sid)
    now = time.time()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except (OSError, ValueError):
            obj = {"id": sid, "title": "", "created": now, "messages": []}
    else:
        obj = {"id": sid, "title": "", "created": now, "messages": []}

    if not obj.get("title"):
        title = " ".join(user_text.split())[:_TITLE_MAX].strip()
        obj["title"] = title or "(untitled)"

    obj.setdefault("messages", [])
    obj["messages"].append({"role": "user", "content": user_text, "ts": now})
    obj["messages"].append({"role": "assistant", "content": assistant_text, "ts": now})
    obj["updated"] = now
    _save(obj)


if __name__ == "__main__":
    list_sessions()
