import base64
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import DATA_DIR, QATOOLS_ROOT

from . import logger

# Scripts / data files for the "Run Script" feature live under QATools/data/cmd.
CMD_DIR = os.path.join(DATA_DIR, "cmd")

_config_dir = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), os.path.join(QATOOLS_ROOT, "backend", "conf")
    )
)
_config_path = os.path.join(_config_dir, "config.yml")

# Max run time (s) and captured-output size for a single script execution.
_RUN_TIMEOUT = 600
_MAX_OUTPUT = 200_000

router = APIRouter()


# ---------- config.yml helpers ----------
def _load_config() -> dict:
    try:
        with open(_config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except OSError as exc:
        logger.error("Error reading config.yml: %s", exc)
        raise HTTPException(status_code=500, detail="Error reading config.yml") from exc


def _save_config(config: dict) -> None:
    try:
        with open(_config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
    except OSError as exc:
        logger.error("Error writing config.yml: %s", exc)
        raise HTTPException(status_code=500, detail="Error writing config.yml") from exc


# ---------- path helpers (confined to CMD_DIR) ----------
def _root_dir() -> str:
    os.makedirs(CMD_DIR, exist_ok=True)
    return os.path.abspath(CMD_DIR)


def _resolve(rel_path: str) -> str:
    """Resolve a root-relative path, rejecting traversal. Empty -> the root."""
    root = _root_dir()
    rel = (rel_path or "").strip().lstrip("/\\")
    target = os.path.abspath(os.path.join(root, rel))
    if target != root and not target.startswith(root + os.sep):
        raise HTTPException(status_code=400, detail=f"Invalid path '{rel_path}'")
    return target


# ---------- tree ----------
def _build_tree(abs_dir: str, root: str) -> list[dict]:
    nodes: list[dict] = []
    try:
        entries = sorted(
            os.scandir(abs_dir), key=lambda e: (not e.is_dir(), e.name.lower())
        )
    except OSError:
        return nodes
    for e in entries:
        rel = os.path.relpath(e.path, root).replace(os.sep, "/")
        if e.is_dir():
            nodes.append(
                {
                    "name": e.name,
                    "path": rel,
                    "type": "dir",
                    "children": _build_tree(e.path, root),
                }
            )
        else:
            try:
                size = e.stat().st_size
            except OSError:
                size = 0
            nodes.append({"name": e.name, "path": rel, "type": "file", "size": size})
    return nodes


@router.get("/v1/cmd/tree")
def get_tree() -> dict:
    """Recursive tree of the cmd directory (QATools/data/cmd)."""
    root = _root_dir()
    return {"root": root, "tree": _build_tree(root, root)}


# ---------- file content view / save ----------
@router.get("/v1/cmd/file")
def view_file(path: str) -> dict:
    """Return a script/data file's text content for the editor."""
    target = _resolve(path)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail=f"File '{path}' not found")
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Read failed: {exc}") from exc
    return {"path": path, "content": content}


class SaveBody(BaseModel):
    dir: str = Field(default="", description="Target directory, relative to root.")
    name: str = Field(..., description="File name (no path separators).")
    content: str = Field(default="", description="UTF-8 text content.")


@router.post("/v1/cmd/file")
def save_file(body: SaveBody) -> dict:
    """Create or overwrite a text script/data file under the cmd directory."""
    if os.path.basename(body.name) != body.name or not body.name:
        raise HTTPException(status_code=400, detail=f"Invalid file name '{body.name}'")
    target_dir = _resolve(body.dir)
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, body.name)
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body.content)
        # Make shell/python scripts executable for convenience.
        if body.name.endswith((".sh", ".py", ".bash")):
            os.chmod(path, 0o755)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Write failed: {exc}") from exc
    logger.info("cmd file saved: %s", path)
    return {"message": f"Saved '{body.name}'"}


# ---------- binary upload (data files) ----------
class UploadBody(BaseModel):
    dir: str = Field(default="", description="Target directory, relative to root.")
    name: str = Field(..., description="File name (no path separators).")
    content_base64: str = Field(..., description="Base64-encoded file content.")


@router.post("/v1/cmd/upload")
def upload_file(body: UploadBody) -> dict:
    """Upload a data file (base64) into the cmd directory."""
    if os.path.basename(body.name) != body.name or not body.name:
        raise HTTPException(status_code=400, detail=f"Invalid file name '{body.name}'")
    target_dir = _resolve(body.dir)
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, body.name)
    try:
        data = base64.b64decode(body.content_base64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid base64: {exc}") from exc
    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Write failed: {exc}") from exc
    logger.info("cmd file uploaded: %s (%d bytes)", path, len(data))
    return {"message": f"Uploaded '{body.name}'"}


@router.delete("/v1/cmd/file")
def delete_file(path: str) -> dict:
    """Delete a file under the cmd directory."""
    target = _resolve(path)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail=f"File '{path}' not found")
    try:
        os.remove(target)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}") from exc
    return {"message": f"Deleted file '{path}'"}


class MkdirBody(BaseModel):
    path: str = Field(..., description="Directory path to create, relative to root.")


@router.post("/v1/cmd/mkdir")
def make_dir(body: MkdirBody) -> dict:
    """Create a directory under the cmd directory."""
    target = _resolve(body.path)
    if target == _root_dir():
        raise HTTPException(status_code=400, detail="Path cannot be the root itself")
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"mkdir failed: {exc}") from exc
    return {"message": f"Created directory '{body.path}'"}


@router.delete("/v1/cmd/dir")
def delete_dir(path: str) -> dict:
    """Delete a directory (recursive) under the cmd directory."""
    target = _resolve(path)
    if target == _root_dir():
        raise HTTPException(status_code=400, detail="Refusing to delete the root")
    if not os.path.isdir(target):
        raise HTTPException(status_code=404, detail=f"Directory '{path}' not found")
    try:
        shutil.rmtree(target)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}") from exc
    return {"message": f"Deleted directory '{path}'"}


# ---------- run cache (config.yml file_transfer.cmd_cache) ----------
def _run_cache() -> list[dict]:
    ft = _load_config().get("file_transfer") or {}
    cache = ft.get("cmd_cache")
    return cache if isinstance(cache, list) else []


def _run_cache_add(entry: dict) -> None:
    """Prepend a run record to file_transfer.cmd_cache (dedup identical cmdline)."""
    config = _load_config()
    ft = config.setdefault("file_transfer", {})
    cache = ft.get("cmd_cache")
    if not isinstance(cache, list):
        cache = []
    cache = [c for c in cache if c.get("cmdline") != entry["cmdline"]]
    cache.insert(0, entry)
    ft["cmd_cache"] = cache[:100]  # keep the 100 most recent
    _save_config(config)


@router.get("/v1/cmd/cache")
def list_run_cache() -> dict:
    """List the recent run records (newest first)."""
    return {"cache": _run_cache()}


@router.delete("/v1/cmd/cache")
def delete_run_cache(cmdline: str) -> dict:
    """Delete a run record matching the cmdline."""
    config = _load_config()
    ft = config.setdefault("file_transfer", {})
    cache = ft.get("cmd_cache")
    if not isinstance(cache, list):
        return {"message": "No cache"}
    kept = [c for c in cache if c.get("cmdline") != cmdline]
    removed = len(cache) - len(kept)
    if removed == 0:
        raise HTTPException(status_code=404, detail="No matching cache entry")
    ft["cmd_cache"] = kept
    _save_config(config)
    return {"message": f"Removed {removed} entry(ies)"}


class RunBody(BaseModel):
    cmdline: str = Field(..., description="Full command line to execute.")
    password: str | None = Field(
        default=None,
        description="SSH password for ssh/scp commands (used in-process only).",
    )
    cwd: str | None = Field(
        default=None,
        description="Working directory to run in (so cd persists across commands).",
    )


# Sentinel used to read back the shell's final $PWD after a command runs, so a
# `cd` persists to the next command (like a real terminal).
_PWD_SENTINEL = "__ZEN_CWD__:"


# ssh options injected into ssh/scp so they never block on a host-key prompt in
# the non-interactive backend.
_SSH_INJECT = (
    "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
)


def _wrap_ssh(cmdline: str, password: str | None) -> str:
    """Prepare an ssh/scp command line for non-interactive execution."""
    prog = (cmdline.lstrip().split(None, 1) or [""])[0]
    if prog not in ("ssh", "scp"):
        return cmdline
    injected = re.sub(rf"^(\s*{prog})\b", rf"\1 {_SSH_INJECT}", cmdline, count=1)
    return f"sshpass -e {injected}" if password else injected


def _resolve_cwd(req_cwd: str | None) -> str:
    """Pick the working directory for a run, defaulting to the cmd root.

    A client-supplied cwd (carried over from a previous command's `cd`) is honored
    only if it still exists, so a stale/deleted dir falls back to the root.
    """
    root = _root_dir()
    if req_cwd:
        cand = os.path.abspath(req_cwd)
        if os.path.isdir(cand):
            return cand
    return root


@router.post("/v1/cmd/run")
def run_script(body: RunBody) -> dict:
    """Run an arbitrary command line and return its output.

    The shell's final working directory is echoed back as `cwd` so a `cd` in one
    command persists to the next (terminal-like behavior).
    """
    cmdline = body.cmdline.strip()
    if not cmdline:
        raise HTTPException(status_code=400, detail="cmdline is required")

    cwd = _resolve_cwd(body.cwd)
    exec_line = _wrap_ssh(cmdline, body.password)
    # Append a marker that prints the shell's final $PWD, so `cd` persists.
    exec_line = f"{exec_line}\nprintf '\\n{_PWD_SENTINEL}%s\\n' \"$PWD\""
    env = dict(os.environ)
    if body.password:
        env["SSHPASS"] = body.password  # consumed by sshpass -e; never in argv
    logger.info("cmd run: %r (cwd=%s)", cmdline, cwd)
    start = time.time()
    timed_out = False
    try:
        proc = subprocess.run(
            exec_line,
            shell=True,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_RUN_TIMEOUT,
        )
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\n[timed out after {_RUN_TIMEOUT}s]"
        code, timed_out = -1, True
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        logger.exception("cmd run failed")
        raise HTTPException(status_code=500, detail=f"Run failed: {exc}") from exc

    # Pull the final $PWD marker out of stdout; what remains is the real output.
    new_cwd = cwd
    if stdout:
        lines = stdout.split("\n")
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].startswith(_PWD_SENTINEL):
                new_cwd = lines[i][len(_PWD_SENTINEL):].strip() or cwd
                # Drop the marker line (and the blank line we printed before it).
                del lines[i]
                if i > 0 and lines[i - 1] == "":
                    del lines[i - 1]
                stdout = "\n".join(lines)
                break

    elapsed = round(time.time() - start, 2)
    stdout = (stdout or "")[:_MAX_OUTPUT]
    stderr = (stderr or "")[:_MAX_OUTPUT]

    # Record this run in config.yml's file_transfer.cmd_cache.
    _run_cache_add(
        {
            "cmdline": cmdline,
            "exit_code": code,
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )

    return {
        "cmdline": cmdline,
        "exit_code": code,
        "timed_out": timed_out,
        "elapsed": elapsed,
        "stdout": stdout,
        "stderr": stderr,
        "cwd": new_cwd,
    }


# ---------- interactive SSH sessions (persistent login) ----------
# `ssh user@ip` (no remote command) is an interactive login; we keep the ssh
# process alive on a PTY and let the UI stream output + send input, until exit.
import fcntl  # noqa: E402
import pty  # noqa: E402
import select  # noqa: E402
import struct  # noqa: E402
import termios  # noqa: E402
import threading  # noqa: E402
import uuid  # noqa: E402

_ssh_sessions: dict[str, dict] = {}
_ssh_lock = threading.Lock()
# Idle sessions are reaped after this many seconds without a poll.
_SSH_IDLE_TIMEOUT = 1800


def _ssh_reader(sid: str, fd: int) -> None:
    """Drain the PTY master fd into the session's output buffer until EOF."""
    while True:
        try:
            r, _, _ = select.select([fd], [], [], 0.5)
        except (OSError, ValueError):
            break
        if fd in r:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            with _ssh_lock:
                s = _ssh_sessions.get(sid)
                if s is None:
                    break
                s["buf"] += chunk.decode("utf-8", errors="replace")
                # Cap the in-memory buffer so a chatty session can't grow forever.
                if len(s["buf"]) > 500_000:
                    s["buf"] = s["buf"][-500_000:]
        with _ssh_lock:
            s = _ssh_sessions.get(sid)
            if s is None:
                break
            proc = s["proc"]
        if proc.poll() is not None:
            # Drain any final bytes.
            try:
                while True:
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    with _ssh_lock:
                        if sid in _ssh_sessions:
                            _ssh_sessions[sid]["buf"] += chunk.decode(
                                "utf-8", errors="replace"
                            )
            except OSError:
                pass
            break
    with _ssh_lock:
        s = _ssh_sessions.get(sid)
        if s is not None:
            s["alive"] = False


class SshStartBody(BaseModel):
    host: str = Field(..., description="Remote host/IP.")
    user: str = Field(..., description="Remote SSH user.")
    password: str | None = Field(default=None, description="SSH password (optional).")


@router.post("/v1/cmd/ssh/start")
def ssh_start(body: SshStartBody) -> dict:
    """Open an interactive ssh login session on a PTY; returns a session_id."""
    if not body.host.strip() or not body.user.strip():
        raise HTTPException(status_code=400, detail="host and user are required")

    sid = uuid.uuid4().hex
    cmd = [
        "ssh",
        "-tt",  # force a remote PTY even though our side isn't a real terminal
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        f"{body.user.strip()}@{body.host.strip()}",
    ]
    if body.password:
        cmd = ["sshpass", "-e", *cmd]
    env = dict(os.environ)
    if body.password:
        env["SSHPASS"] = body.password

    master, slave = pty.openpty()
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    except OSError:
        pass
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            close_fds=True,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        os.close(master)
        os.close(slave)
        raise HTTPException(
            status_code=500, detail=f"ssh/sshpass not available: {exc}"
        ) from exc
    os.close(slave)

    with _ssh_lock:
        _ssh_sessions[sid] = {
            "proc": proc,
            "fd": master,
            "buf": "",
            "alive": True,
            "label": f"{body.user.strip()}@{body.host.strip()}",
            "last": time.time(),
        }
    threading.Thread(target=_ssh_reader, args=(sid, master), daemon=True).start()
    logger.info("ssh session %s started: %s@%s", sid, body.user, body.host)
    return {"session_id": sid, "label": f"{body.user.strip()}@{body.host.strip()}"}


class SshInputBody(BaseModel):
    session_id: str = Field(..., description="Session id from ssh/start.")
    data: str = Field(..., description="Text to send to the session's stdin.")


@router.post("/v1/cmd/ssh/input")
def ssh_input(body: SshInputBody) -> dict:
    """Send input (e.g. a command + newline) to an interactive ssh session."""
    with _ssh_lock:
        s = _ssh_sessions.get(body.session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Unknown ssh session")
        fd = s["fd"]
        s["last"] = time.time()
    try:
        os.write(fd, body.data.encode("utf-8"))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"write failed: {exc}") from exc
    return {"ok": True}


@router.get("/v1/cmd/ssh/output")
def ssh_output(session_id: str, since: int = 0) -> dict:
    """Return the session's output from byte offset `since` onward + liveness.

    The client passes back the `offset` it last received so it only gets new
    output each poll.
    """
    with _ssh_lock:
        s = _ssh_sessions.get(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Unknown ssh session")
        s["last"] = time.time()
        buf = s["buf"]
        alive = s["alive"]
        # Reap finished sessions once their output has been fully consumed.
    data = buf[since:] if 0 <= since <= len(buf) else buf
    new_offset = len(buf)
    if not alive and since >= len(buf):
        with _ssh_lock:
            _close_ssh(session_id)
    return {"data": data, "offset": new_offset, "alive": alive}


def _close_ssh(sid: str) -> None:
    """Terminate + forget a session. Caller must hold _ssh_lock."""
    s = _ssh_sessions.pop(sid, None)
    if s is None:
        return
    try:
        proc = s["proc"]
        if proc.poll() is None:
            import signal

            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        os.close(s["fd"])
    except OSError:
        pass


@router.post("/v1/cmd/ssh/stop")
def ssh_stop(session_id: str) -> dict:
    """Close an interactive ssh session."""
    with _ssh_lock:
        if session_id not in _ssh_sessions:
            return {"message": "session already closed"}
        _close_ssh(session_id)
    logger.info("ssh session %s stopped", session_id)
    return {"message": "session closed"}
