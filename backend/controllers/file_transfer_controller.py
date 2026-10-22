import base64
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import DATA_DIR, FILE_TRANSFER_PATH, QATOOLS_ROOT

from . import logger

_config_dir = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), os.path.join(QATOOLS_ROOT, "backend", "conf")
    )
)
_config_path = os.path.join(_config_dir, "config.yml")

# PID file tracking the single managed `python -m http.server` instance.
_pid_file = os.path.join(DATA_DIR, ".file_transfer_http.pid")

router = APIRouter()


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


def _ft_config() -> dict:
    """Effective file-transfer config: {root, http_port}. Empty root -> default."""
    ft = _load_config().get("file_transfer") or {}
    root = str(ft.get("root") or "").strip() or FILE_TRANSFER_PATH
    if not os.path.isabs(root):
        root = os.path.join(QATOOLS_ROOT, root)
    root = os.path.abspath(root)
    try:
        port = int(ft.get("http_port") or 9000)
    except (TypeError, ValueError):
        port = 9000
    return {"root": root, "http_port": port}


def _scp_cache() -> list[dict]:
    """The scp_server_cache list from config.yml (each {server, upload_dir, username})."""
    ft = _load_config().get("file_transfer") or {}
    cache = ft.get("scp_server_cache")
    return cache if isinstance(cache, list) else []


def _scp_cache_upsert(server: str, upload_dir: str, username: str) -> None:
    """Add/refresh a cache entry keyed by (server, username, upload_dir).

    A brand-new (server, user, dir) combination is appended; an exact duplicate is
    moved to the front so the most-recently-used entry leads the list.
    """
    config = _load_config()
    ft = config.setdefault("file_transfer", {})
    cache = ft.get("scp_server_cache")
    if not isinstance(cache, list):
        cache = []
    entry = {"server": server, "upload_dir": upload_dir, "username": username}
    cache = [
        c
        for c in cache
        if not (
            c.get("server") == server
            and c.get("username") == username
            and c.get("upload_dir") == upload_dir
        )
    ]
    cache.insert(0, entry)
    ft["scp_server_cache"] = cache
    _save_config(config)


def _root_dir() -> str:
    root = _ft_config()["root"]
    os.makedirs(root, exist_ok=True)
    return root


def _resolve(rel_path: str) -> str:
    """Resolve a root-relative path to an absolute path, rejecting traversal.

    An empty / "." / "/" relative path resolves to the root itself.
    """
    root = _root_dir()
    rel = (rel_path or "").strip().lstrip("/\\")
    target = os.path.abspath(os.path.join(root, rel))
    # Must stay within root (allow root itself).
    if target != root and not target.startswith(root + os.sep):
        raise HTTPException(status_code=400, detail=f"Invalid path '{rel_path}'")
    return target


# ---------- config endpoints ----------
class FileTransferConfigBody(BaseModel):
    root: str | None = Field(default=None, description="New root dir, or omit to keep.")
    http_port: int | None = Field(default=None, description="New http.server port.")


@router.get("/v1/file_transfer/config")
def get_config() -> dict:
    """Return the effective file-transfer root dir and http.server port."""
    return _ft_config()


@router.put("/v1/file_transfer/config")
def update_config(body: FileTransferConfigBody) -> dict:
    """Update the file-transfer root dir and/or http.server port in config.yml."""
    config = _load_config()
    ft = config.setdefault("file_transfer", {})
    changed = []
    if body.root is not None:
        new_root = body.root.strip()
        if new_root:
            abs_root = (
                new_root
                if os.path.isabs(new_root)
                else os.path.join(QATOOLS_ROOT, new_root)
            )
            try:
                os.makedirs(os.path.abspath(abs_root), exist_ok=True)
            except OSError as exc:
                raise HTTPException(
                    status_code=400, detail=f"Cannot use root '{new_root}': {exc}"
                ) from exc
        ft["root"] = new_root
        changed.append("root")
    if body.http_port is not None:
        if body.http_port < 1 or body.http_port > 65535:
            raise HTTPException(status_code=400, detail="http_port out of range")
        ft["http_port"] = body.http_port
        changed.append("http_port")
    if not changed:
        return {"message": "No changes", **_ft_config()}
    _save_config(config)
    logger.info("File-transfer config updated: %s", ", ".join(changed))
    return {"message": f"Updated: {', '.join(changed)}", **_ft_config()}


# ---------- tree ----------
def _build_tree(abs_dir: str, root: str) -> list[dict]:
    """Recursive listing under abs_dir as [{name, path(rel), type, size?, children?}]."""
    nodes: list[dict] = []
    try:
        entries = sorted(
            os.scandir(abs_dir),
            key=lambda e: (not e.is_dir(), e.name.lower()),
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


@router.get("/v1/file_transfer/tree")
def get_tree() -> dict:
    """Recursive tree of the file-transfer root directory."""
    root = _root_dir()
    return {"root": root, "tree": _build_tree(root, root)}


# ---------- upload / delete / mkdir ----------
class UploadBody(BaseModel):
    dir: str = Field(default="", description="Target directory, relative to root.")
    name: str = Field(..., description="File name (no path separators).")
    content_base64: str = Field(..., description="Base64-encoded file content.")


@router.post("/v1/file_transfer/upload")
def upload_file(body: UploadBody) -> dict:
    """Upload a file (base64) into a directory under the root."""
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
    logger.info("File uploaded: %s (%d bytes)", path, len(data))
    return {"message": f"Uploaded '{body.name}'"}


@router.delete("/v1/file_transfer/file")
def delete_file(path: str) -> dict:
    """Delete a file at a root-relative path."""
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


@router.post("/v1/file_transfer/mkdir")
def make_dir(body: MkdirBody) -> dict:
    """Create a directory at a root-relative path."""
    target = _resolve(body.path)
    if target == _root_dir():
        raise HTTPException(status_code=400, detail="Path cannot be the root itself")
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"mkdir failed: {exc}") from exc
    return {"message": f"Created directory '{body.path}'"}


@router.delete("/v1/file_transfer/dir")
def delete_dir(path: str) -> dict:
    """Delete a directory (recursive) at a root-relative path."""
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


# ---------- http.server lifecycle (singleton via PID file) ----------
def _read_pid() -> dict | None:
    if not os.path.isfile(_pid_file):
        return None
    try:
        with open(_pid_file, "r", encoding="utf-8") as f:
            parts = f.read().strip().split()
        pid = int(parts[0])
        port = int(parts[1]) if len(parts) > 1 else None
        serve_dir = parts[2] if len(parts) > 2 else None
        return {"pid": pid, "port": port, "dir": serve_dir}
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return pid  # PermissionError means it exists but not ours -> treat alive
    except OSError:
        return False


@router.get("/v1/file_transfer/http/status")
def http_status() -> dict:
    """Report whether the managed http.server is running."""
    info = _read_pid()
    if info and _pid_alive(info["pid"]):
        return {"running": True, **info}
    # stale pid file
    if info:
        try:
            os.remove(_pid_file)
        except OSError:
            pass
    return {"running": False, "port": _ft_config()["http_port"]}


@router.post("/v1/file_transfer/http/start")
def http_start() -> dict:
    """Start `python -m http.server <port> -b 0.0.0.0 -d <root>` (singleton)."""
    info = _read_pid()
    if info and _pid_alive(info["pid"]):
        raise HTTPException(
            status_code=409, detail=f"http.server already running (pid {info['pid']})"
        )
    cfg = _ft_config()
    root = cfg["root"]
    port = cfg["http_port"]
    os.makedirs(root, exist_ok=True)
    try:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "http.server",
                str(port),
                "-b",
                "0.0.0.0",
                "-d",
                root,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # detach so it survives this request's process
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to start http.server")
        raise HTTPException(
            status_code=500, detail=f"Failed to start http.server: {exc}"
        ) from exc
    try:
        with open(_pid_file, "w", encoding="utf-8") as f:
            f.write(f"{proc.pid} {port} {root}")
    except OSError as exc:
        logger.warning("Failed to write pid file: %s", exc)
    logger.info("http.server started pid=%s port=%s dir=%s", proc.pid, port, root)
    return {
        "message": f"http.server started on port {port}",
        "pid": proc.pid,
        "port": port,
    }


@router.post("/v1/file_transfer/http/stop")
def http_stop() -> dict:
    """Stop the managed http.server."""
    info = _read_pid()
    if not info:
        return {"message": "http.server is not running"}
    pid = info["pid"]
    try:
        # Kill the whole process group (start_new_session set it as group leader).
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    try:
        os.remove(_pid_file)
    except OSError:
        pass
    logger.info("http.server stopped pid=%s", pid)
    return {"message": f"http.server stopped (pid {pid})"}


# ---------- scp upload to a remote server ----------
class ScpBody(BaseModel):
    rel_path: str = Field(..., description="File/dir path under root to send.")
    is_dir: bool = Field(default=False, description="True for a directory (scp -r).")
    user: str = Field(..., description="Remote SSH user.")
    host: str = Field(..., description="Remote server IP/hostname.")
    remote_dir: str = Field(..., description="Remote target directory.")
    password: str = Field(
        ..., description="Remote SSH password (used in-process only)."
    )


# In-memory registry of scp jobs: job_id -> {status, percent, message, done, ok}.
_scp_jobs: dict[str, dict] = {}
_scp_lock = threading.Lock()

# Common ssh options: skip host-key prompts and don't block on an unknown host.
_SSH_OPTS = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "LogLevel=ERROR",
]


def _local_size(path: str) -> int:
    """Total byte size of a local file or directory tree."""
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total


def _remote_size(password: str, user: str, host: str, remote_target: str) -> int:
    """Byte size of the uploaded target on the remote (via sshpass+ssh `du -sb`).

    Returns 0 if it can't be read yet (target not created, transient error, etc.).
    """
    env = dict(os.environ, SSHPASS=password)
    cmd = [
        "sshpass", "-e", "ssh",
        "-o", "ConnectTimeout=10",
        *_SSH_OPTS,
        f"{user}@{host}",
        f"du -sb {shlex.quote(remote_target)} 2>/dev/null | cut -f1",
    ]
    try:
        out = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=15)
        val = (out.stdout or "").strip()
        return int(val) if val.isdigit() else 0
    except (subprocess.SubprocessError, ValueError):
        return 0


def _progress_poller(
    job_id: str, password: str, user: str, host: str, remote_target: str, total: int
) -> None:
    """Poll the remote target size and update percent until the job is done."""
    while True:
        with _scp_lock:
            job = _scp_jobs.get(job_id)
            if job is None or job["done"]:
                return
        if total > 0:
            got = _remote_size(password, user, host, remote_target)
            pct = max(0, min(99, int(got * 100 / total)))  # cap at 99 until done
            with _scp_lock:
                j = _scp_jobs.get(job_id)
                if j and not j["done"] and pct > j["percent"]:
                    j["percent"] = pct
        time.sleep(1.5)


def _run_scp_job(
    job_id: str,
    src: str,
    is_dir: bool,
    user: str,
    host: str,
    remote_dir: str,
    password: str,
    label: str,
    cache_entry: dict | None = None,
) -> None:
    """Upload via `sshpass + scp` and report real progress by polling the remote
    target size against the local size (scp's own meter is swallowed by sshpass).

    On success, cache_entry (if given) is upserted into config.yml's
    scp_server_cache so the Host dropdown remembers it.
    """
    env = dict(os.environ, SSHPASS=password)
    total = _local_size(src)
    base = os.path.basename(src.rstrip("/"))
    remote_target = remote_dir.rstrip("/") + "/" + base
    try:
        scmd = ["sshpass", "-e", "scp", "-o", "ConnectTimeout=20", *_SSH_OPTS]
        if is_dir:
            scmd.append("-r")
        scmd += [src, f"{user}@{host}:{remote_dir}"]
        proc = subprocess.Popen(
            scmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        # Poll remote size for progress while scp runs.
        threading.Thread(
            target=_progress_poller,
            args=(job_id, password, user, host, remote_target, total),
            daemon=True,
        ).start()
        _out, err = proc.communicate()

        succeeded = proc.returncode == 0
        with _scp_lock:
            job = _scp_jobs[job_id]
            job["done"] = True
            if succeeded:
                job["ok"] = True
                job["percent"] = 100
                job["status"] = "done"
                job["message"] = f"Uploaded {label}"
            else:
                job["ok"] = False
                job["status"] = "error"
                detail = (err or b"").decode("utf-8", errors="replace").strip()
                last = detail.splitlines()[-1] if detail else "scp failed"
                job["message"] = f"scp failed: {last}"
        if succeeded and cache_entry:
            try:
                _scp_cache_upsert(
                    cache_entry["server"],
                    cache_entry["upload_dir"],
                    cache_entry["username"],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("scp succeeded but cache update failed: %s", exc)
    except FileNotFoundError:
        with _scp_lock:
            _scp_jobs[job_id].update(
                done=True, ok=False, status="error",
                message="sshpass/scp not available on the server",
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("scp job failed")
        with _scp_lock:
            _scp_jobs[job_id].update(
                done=True, ok=False, status="error", message=f"scp failed: {exc}",
            )


@router.post("/v1/file_transfer/scp/start")
def scp_start(body: ScpBody) -> dict:
    """Start an scp upload in the background; returns a job_id to poll for progress.

    The password is passed to sshpass via the environment (never in argv or logs).
    """
    src = _resolve(body.rel_path)
    if not os.path.exists(src):
        raise HTTPException(status_code=404, detail=f"'{body.rel_path}' not found")
    if body.is_dir and not os.path.isdir(src):
        raise HTTPException(status_code=400, detail="Path is not a directory")
    if not body.is_dir and not os.path.isfile(src):
        raise HTTPException(status_code=400, detail="Path is not a file")
    for field, val in (
        ("user", body.user),
        ("host", body.host),
        ("remote_dir", body.remote_dir),
    ):
        if not str(val).strip():
            raise HTTPException(status_code=400, detail=f"{field} is required")

    label = f"'{body.rel_path}' to {body.user}@{body.host}:{body.remote_dir}"
    job_id = uuid.uuid4().hex
    with _scp_lock:
        _scp_jobs[job_id] = {
            "status": "running",
            "percent": 0,
            "message": "",
            "done": False,
            "ok": False,
            "started": time.time(),
        }
    logger.info(
        "scp %s -> %s@%s:%s (job %s)",
        body.rel_path,
        body.user,
        body.host,
        body.remote_dir,
        job_id,
    )
    cache_entry = {
        "server": body.host.strip(),
        "upload_dir": body.remote_dir.strip(),
        "username": body.user.strip(),
    }
    threading.Thread(
        target=_run_scp_job,
        args=(
            job_id, src, body.is_dir, body.user.strip(), body.host.strip(),
            body.remote_dir.strip(), body.password, label, cache_entry,
        ),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@router.get("/v1/file_transfer/scp/servers")
def list_scp_servers() -> dict:
    """List cached scp targets for the Host dropdown (server/upload_dir/username)."""
    return {"servers": _scp_cache()}


@router.delete("/v1/file_transfer/scp/servers")
def delete_scp_server(server: str, username: str = "", upload_dir: str = "") -> dict:
    """Delete cached scp target(s). Matches by server, optionally narrowed by
    username and upload_dir (empty = match any)."""
    config = _load_config()
    ft = config.setdefault("file_transfer", {})
    cache = ft.get("scp_server_cache")
    if not isinstance(cache, list):
        return {"message": "No cached servers"}

    def _match(c: dict) -> bool:
        if c.get("server") != server:
            return False
        if username and c.get("username") != username:
            return False
        if upload_dir and c.get("upload_dir") != upload_dir:
            return False
        return True

    kept = [c for c in cache if not _match(c)]
    removed = len(cache) - len(kept)
    if removed == 0:
        raise HTTPException(status_code=404, detail=f"No cached entry for '{server}'")
    ft["scp_server_cache"] = kept
    _save_config(config)
    logger.info("Removed %d scp cache entry(ies) for %s", removed, server)
    return {"message": f"Removed {removed} entry(ies) for '{server}'"}


@router.get("/v1/file_transfer/scp/status/{job_id}")
def scp_status(job_id: str) -> dict:
    """Poll an scp job's progress: {status, percent, message, done, ok}."""
    with _scp_lock:
        job = _scp_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown scp job")
        out = {
            "status": job["status"],
            "percent": job["percent"],
            "message": job["message"],
            "done": job["done"],
            "ok": job["ok"],
        }
    # Reap finished jobs once reported as done (next poll will 404 -> UI stops).
    if out["done"]:
        with _scp_lock:
            _scp_jobs.pop(job_id, None)
    return out
