import os
import subprocess
import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import ADMIN_HASHED_PASSWORD, ADMIN_USERNAME, QATOOLS_ROOT

# All backend/conf yaml access goes through the data service layer.
from services.data_service import (
    AGENT_STORE,
    ANALYZE_STORE,
    CONF_DIR,
    TABS_STORE,
    DataServiceError,
)

from . import logger

config_dir = CONF_DIR

router = APIRouter()


# ---------- Admin login ----------
class AdminLoginBody(BaseModel):
    username: str = Field(..., description="Admin username.")
    password: str = Field(..., description="Admin password.")


@router.post("/v1/config/admin/login")
def admin_login(body: AdminLoginBody) -> dict:
    """Verify admin credentials (bcrypt). Returns {ok: true} on success, else 401.

    Gates the Settings tab in the UI; the password is checked server-side against
    the bcrypt hash in config/env.py and never stored or echoed.
    """
    ok = False
    if body.username == ADMIN_USERNAME:
        try:
            import bcrypt

            ok = bcrypt.checkpw(
                body.password.encode("utf-8"), ADMIN_HASHED_PASSWORD.encode("utf-8")
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Admin login check failed: %s", exc)
            raise HTTPException(
                status_code=500, detail="Admin auth not available"
            ) from exc
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    logger.info("Admin login succeeded")
    return {"ok": True}


def _read(store, section: str, default=None):
    """Read a section through a data store, mapping errors to HTTP 500."""
    try:
        return store.get_section(section, default)
    except DataServiceError as exc:
        logger.error("%s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _write(store, section: str, value) -> None:
    """Persist a section through a data store, mapping errors to HTTP 500."""
    try:
        store.set_section(section, value)
    except DataServiceError as exc:
        logger.error("%s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _set_tab(tab_name: str, status: bool) -> dict:
    tabs = _read(TABS_STORE, "tabs")
    if not isinstance(tabs, dict) or tab_name not in tabs:
        raise HTTPException(status_code=404, detail=f"Unknown tab '{tab_name}'")
    tabs[tab_name] = status
    _write(TABS_STORE, "tabs", tabs)
    logger.info("Tab '%s' set to %s", tab_name, status)
    return {
        "message": f"Tab '{tab_name}' {'enabled' if status else 'disabled'} successfully"
    }


@router.get("/v1/config/tabs/list")
def list_tabs() -> dict:
    """List all tabs with visibility + display order.

    The order is the key order in tabs_data.yml's `tabs` map (which the left-nav
    renders in). `order` is the 0-based index.

    return:
    {"tabs": [{"name": "device", "status": true, "order": 0}, ...]}
    """
    tabs = _read(TABS_STORE, "tabs", {}) or {}
    return {
        "tabs": [
            {"name": name, "status": bool(tabs[name]), "order": i}
            for i, name in enumerate(tabs)
        ]
    }


@router.get("/v1/config/tabs/{tab_name}/disable")
def disable_tab(tab_name: str) -> dict:
    """Hide a tab (set its visibility to false)."""
    return _set_tab(tab_name, False)


@router.get("/v1/config/tabs/{tab_name}/enable")
def enable_tab(tab_name: str) -> dict:
    """Show a tab (set its visibility to true)."""
    return _set_tab(tab_name, True)


class TabOrderBody(BaseModel):
    order: list[str] = Field(..., description="Tab names in the desired display order.")


@router.put("/v1/config/tabs/reorder")
def reorder_tabs(body: TabOrderBody) -> dict:
    """Rewrite the tabs map in the given order (display order = key order).

    Any tabs omitted from `order` are appended at the end in their existing
    order, so a partial list never drops tabs.
    """
    tabs = _read(TABS_STORE, "tabs")
    if not isinstance(tabs, dict):
        raise HTTPException(status_code=404, detail="No tabs configured")
    unknown = [n for n in body.order if n not in tabs]
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"Unknown tab(s): {', '.join(unknown)}"
        )
    new_tabs = {name: tabs[name] for name in body.order}
    for name in tabs:  # keep any not listed, at the end
        new_tabs.setdefault(name, tabs[name])
    _write(TABS_STORE, "tabs", new_tabs)
    logger.info("Tabs reordered: %s", ", ".join(new_tabs))
    return {"message": "Tab order updated"}


class AgentModelBody(BaseModel):
    name: str = Field(..., description="Unique display name / key for the model.")
    description: str = Field(default="", description="Human-readable description.")
    model: str = Field(..., description="Model identifier passed to the AI gateway.")
    max_tokens: int = Field(
        default=128000, description="Max tokens per completion.", gt=0
    )
    temperature: float = Field(
        default=0.7, description="Sampling temperature.", ge=0, le=2
    )


def _model_entry(body: AgentModelBody) -> dict:
    return {
        "name": body.name,
        "description": body.description,
        "model": body.model,
        "max_tokens": body.max_tokens,
        "temperature": body.temperature,
    }


@router.get("/v1/config/models/list")
def list_models() -> dict:
    """List all configured agent models from agent_data.yml's `agent_model`."""
    return {"models": _read(AGENT_STORE, "agent_model", []) or []}


@router.post("/v1/config/models/add")
def add_model(body: AgentModelBody) -> dict:
    """Append a new agent model. Fails if the name already exists."""
    models = _read(AGENT_STORE, "agent_model", []) or []
    if any(m.get("name") == body.name for m in models):
        raise HTTPException(
            status_code=400, detail=f"Model '{body.name}' already exists"
        )
    models.append(_model_entry(body))
    _write(AGENT_STORE, "agent_model", models)
    logger.info("Agent model '%s' added", body.name)
    return {"message": f"Model '{body.name}' added successfully"}


@router.put("/v1/config/models/update/{name}")
def update_model(name: str, body: AgentModelBody) -> dict:
    """Update the agent model identified by `name` (path), replacing its fields."""
    models = _read(AGENT_STORE, "agent_model", []) or []
    for i, m in enumerate(models):
        if m.get("name") == name:
            models[i] = _model_entry(body)
            _write(AGENT_STORE, "agent_model", models)
            logger.info("Agent model '%s' updated", name)
            return {"message": f"Model '{name}' updated successfully"}
    raise HTTPException(status_code=404, detail=f"Model '{name}' not found")


@router.delete("/v1/config/models/delete/{name}")
def delete_model(name: str) -> dict:
    """Delete the agent model identified by `name`."""
    models = _read(AGENT_STORE, "agent_model", []) or []
    new_models = [m for m in models if m.get("name") != name]
    if len(new_models) == len(models):
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")
    _write(AGENT_STORE, "agent_model", new_models)
    logger.info("Agent model '%s' deleted", name)
    return {"message": f"Model '{name}' deleted successfully"}


class AgentCredBody(BaseModel):
    # Secrets are write-only from the UI: an empty/None value means "leave the
    # stored value unchanged" (so the masked placeholder is never written back).
    api_key: str | None = Field(
        default=None, description="New API key, or empty to keep."
    )
    key_id: str | None = Field(
        default=None, description="New key id, or empty to keep."
    )
    key_alias: str | None = Field(
        default=None, description="New key alias (shown in clear)."
    )


@router.get("/v1/config/agent/get")
def get_agent_cred() -> dict:
    """Return agent credentials for the Settings form.

    api_key / key_id are returned MASKED (never in clear); `*_set` flags tell
    the UI whether a value exists. key_alias is returned in clear.
    """
    ac = _read(AGENT_STORE, "agent_config", {}) or {}
    api_key = str(ac.get("api_key") or "")
    key_id = str(ac.get("key_id") or "")
    return {
        "api_key_masked": "*" * len(api_key),
        "api_key_set": bool(api_key),
        "key_id_masked": "*" * len(key_id),
        "key_id_set": bool(key_id),
        "key_alias": str(ac.get("key_alias") or ""),
    }


@router.put("/v1/config/agent/update")
def update_agent_cred(body: AgentCredBody) -> dict:
    """Update agent credentials. Empty api_key/key_id are ignored (kept as-is)."""
    ac = _read(AGENT_STORE, "agent_config", {}) or {}
    changed = []
    if body.api_key:
        ac["api_key"] = body.api_key
        changed.append("api_key")
    if body.key_id:
        ac["key_id"] = body.key_id
        changed.append("key_id")
    if body.key_alias is not None:
        ac["key_alias"] = body.key_alias
        changed.append("key_alias")
    if not changed:
        return {"message": "No changes"}
    _write(AGENT_STORE, "agent_config", ac)
    logger.info("Agent credentials updated: %s", ", ".join(changed))
    return {"message": f"Updated: {', '.join(changed)}"}


class DefaultModelBody(BaseModel):
    model: str = Field(..., description="Model identifier to set as the default.")
    timeout_sec: float = Field(
        default=300.0, description="Request timeout seconds.", gt=0
    )
    max_tokens: int = Field(
        default=128000, description="Max tokens per completion.", gt=0
    )
    temperature: float = Field(
        default=0.7, description="Sampling temperature.", ge=0, le=2
    )


@router.get("/v1/config/agent/default")
def get_default_model() -> dict:
    """Return the active agent_config model params (the current default)."""
    ac = _read(AGENT_STORE, "agent_config", {}) or {}
    return {
        "model": ac.get("model", ""),
        "timeout_sec": ac.get("timeout_sec", 300.0),
        "max_tokens": ac.get("max_tokens", 128000),
        "temperature": ac.get("temperature", 0.7),
    }


@router.put("/v1/config/agent/default")
def set_default_model(body: DefaultModelBody) -> dict:
    """Set the default AI model: persist it to agent_data.yml AND apply it to the
    live agent service so it takes effect immediately (no restart needed)."""
    ac = _read(AGENT_STORE, "agent_config", {}) or {}
    ac["model"] = body.model
    ac["timeout_sec"] = body.timeout_sec
    ac["max_tokens"] = body.max_tokens
    ac["temperature"] = body.temperature
    _write(AGENT_STORE, "agent_config", ac)

    # Apply to the running AgentService singleton so the Prompt page uses the
    # new model right away, without a backend restart.
    try:
        from . import agent_controller

        svc = agent_controller._service
        if svc is not None:
            svc.switch(
                model=body.model,
                max_tokens=body.max_tokens,
                temperature=body.temperature,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Default saved but live switch failed: %s", exc)

    logger.info("Default agent model set to '%s' (applied live)", body.model)
    return {"message": f"Default model set to '{body.model}'"}


class AnalyzeConfigBody(BaseModel):
    default_locale: str = Field(
        ..., description="Default Analyze locale: 'en-US' or 'zh-CN'."
    )
    prompt_template: str = Field(
        ...,
        description="Analyze prompt template. Supports {lang} and {content} placeholders.",
    )


@router.get("/v1/config/analyze/get")
def get_analyze_config() -> dict:
    """Return the Analyze default locale + prompt template.

    Both fall back to the agent_controller built-in defaults when not
    configured. `default_prompt_template` is the built-in prompt, used by
    Settings' "Reset to Default".
    """
    from . import agent_controller

    ac = _read(ANALYZE_STORE, "analyze_config", {}) or {}
    configured = ac.get("prompt_template") or ""
    # Same shape as the Split prompt GET (default / is_default / placeholders).
    return {
        "default_locale": ac.get("default_locale")
        or agent_controller._DEFAULT_ANALYZE_LOCALE,
        "prompt_template": configured or agent_controller.DEFAULT_ANALYZE_PROMPT_TEMPLATE,
        "default_prompt_template": agent_controller.DEFAULT_ANALYZE_PROMPT_TEMPLATE,
        "is_default": not configured,
        "placeholders": list(agent_controller.ANALYZE_PROMPT_PLACEHOLDERS),
    }


@router.put("/v1/config/analyze/update")
def update_analyze_config(body: AnalyzeConfigBody) -> dict:
    """Persist the Analyze default locale + prompt template to analyze_data.yml.

    Read fresh per analyze request by the agent controller, so this applies with
    no backend restart.
    """
    locale = body.default_locale.strip()
    if locale not in ("en-US", "zh-CN"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid locale '{locale}' (expected 'en-US' or 'zh-CN')",
        )
    if not body.prompt_template.strip():
        raise HTTPException(status_code=400, detail="prompt_template cannot be empty")
    from .agent_controller import ANALYZE_PROMPT_PLACEHOLDERS

    # Same validation as the Split prompt update.
    missing = [p for p in ANALYZE_PROMPT_PLACEHOLDERS if p not in body.prompt_template]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Prompt template must contain the placeholder(s): {', '.join(missing)}",
        )

    analyze = _read(ANALYZE_STORE, "analyze_config", {}) or {}
    analyze["default_locale"] = locale
    analyze["prompt_template"] = body.prompt_template
    _write(ANALYZE_STORE, "analyze_config", analyze)
    logger.info("Analyze config updated (default_locale=%s)", locale)
    return {"message": "Analyze settings saved"}


# ---------- Split Profile prompt (analyze_data.yml: analyze_config.split_prompt_template)


class SplitPromptBody(BaseModel):
    split_prompt_template: str = Field(
        ...,
        description="Prompt used by Profile -> Split. Must contain {devices} and {cases}.",
    )


@router.get("/v1/config/analyze/split_prompt/get")
def get_split_prompt() -> dict:
    """Return the Split prompt (configured, else built-in) and the default."""
    from .profile_controller import DEFAULT_SPLIT_PROMPT, SPLIT_PROMPT_PLACEHOLDERS

    ac = _read(ANALYZE_STORE, "analyze_config", {}) or {}
    configured = ac.get("split_prompt_template") or ""
    return {
        "split_prompt_template": configured or DEFAULT_SPLIT_PROMPT,
        "default_split_prompt_template": DEFAULT_SPLIT_PROMPT,
        "is_default": not configured,
        "placeholders": list(SPLIT_PROMPT_PLACEHOLDERS),
    }


@router.put("/v1/config/analyze/split_prompt/update")
def update_split_prompt(body: SplitPromptBody) -> dict:
    """Persist the Split prompt to analyze_data.yml (applies on the next split).

    Only `split_prompt_template` is touched; the rest of analyze_config
    (locale, analyze prompt) is preserved.
    """
    from .profile_controller import SPLIT_PROMPT_PLACEHOLDERS

    template = body.split_prompt_template
    if not template.strip():
        raise HTTPException(status_code=400, detail="split_prompt_template cannot be empty")
    missing = [p for p in SPLIT_PROMPT_PLACEHOLDERS if p not in template]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Split prompt must contain the placeholder(s): {', '.join(missing)}",
        )

    analyze = _read(ANALYZE_STORE, "analyze_config", {}) or {}
    analyze["split_prompt_template"] = template
    _write(ANALYZE_STORE, "analyze_config", analyze)
    logger.info("Split prompt updated (%d chars)", len(template))
    return {"message": "Split prompt saved"}


# ---------- Account settings (stored directly in config/env.py) ----------
import re  # noqa: E402

_env_path = os.path.abspath(os.path.join(QATOOLS_ROOT, "config", "env.py"))

# Editable account fields. Secrets are masked on read + write-only on update.
_ACCOUNT_FIELDS = (
    "QAHUB_TOKEN",
    "EMAIL",
    "TESTRAIL_USERNAME",
    "TESTRAIL_API_KEY",
    "JIRA_TOKEN",
    "AUTOMATED_TESTS_RELATIVE_DIR",
    "ROKU_AUTOMATION_RELATIVE_DIR",
)
_ACCOUNT_SECRETS = {
    "QAHUB_TOKEN",
    "TESTRAIL_USERNAME",
    "TESTRAIL_API_KEY",
    "JIRA_TOKEN",
}


def _effective_account() -> dict:
    """Current effective values, read from the live config.env module."""
    from config import env

    return {k: str(getattr(env, k, "") or "") for k in _ACCOUNT_FIELDS}


def _assignment_re(key: str) -> re.Pattern[str]:
    """Match a top-level `KEY = "value"` assignment in env.py (single line)."""
    return re.compile(rf'^{re.escape(key)}\s*=\s*.*$', re.M)


def _write_env_values(values: dict[str, str]) -> list[str]:
    """Rewrite the given KEY = "value" assignments in config/env.py.

    Only the module-level assignments for _ACCOUNT_FIELDS are touched; the rest
    of the file (comments, constants, derived values) is left untouched. A key
    that has no assignment yet is appended under an "Account settings" section.
    Returns the list of keys actually changed.
    """
    try:
        with open(_env_path, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        logger.error("Error reading env.py: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"Error reading env.py: {exc}"
        ) from exc

    changed: list[str] = []
    appended: list[str] = []
    for key, value in values.items():
        if key not in _ACCOUNT_FIELDS:
            continue
        literal = f'{key} = {value!r}'
        pattern = _assignment_re(key)
        match = pattern.search(text)
        if match:
            if match.group(0) == literal:
                continue  # unchanged
            text = text[: match.start()] + literal + text[match.end() :]
        else:
            appended.append(literal)
        changed.append(key)

    if appended:
        text = text.rstrip("\n") + "\n\n# Account settings (appended by Settings -> Account Settings)\n"
        text += "\n".join(appended) + "\n"

    if not changed:
        return []

    # Write via a temp file + replace so a failed write can never truncate env.py.
    tmp_path = f"{_env_path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_path, _env_path)
    except OSError as exc:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        logger.error("Error writing env.py: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"Error writing account settings: {exc}"
        ) from exc
    return changed


@router.get("/v1/config/account/get")
def get_account() -> dict:
    """Return account settings for the form. Secret fields are returned MASKED
    (never in clear) with an `*_set` flag; non-secret fields are returned as-is."""
    values = _effective_account()
    out: dict = {}
    for k in _ACCOUNT_FIELDS:
        v = values.get(k, "")
        if k in _ACCOUNT_SECRETS:
            out[k] = "*" * min(len(v), 12)
            out[f"{k}_set"] = bool(v)
        else:
            out[k] = v
    out["secret_fields"] = sorted(_ACCOUNT_SECRETS)
    return out


class AccountBody(BaseModel):
    # All optional: a None/empty secret means "keep the stored value"; non-secret
    # fields are written through to env.py as given.
    QAHUB_TOKEN: str | None = None
    EMAIL: str | None = None
    TESTRAIL_USERNAME: str | None = None
    TESTRAIL_API_KEY: str | None = None
    JIRA_TOKEN: str | None = None
    AUTOMATED_TESTS_RELATIVE_DIR: str | None = None
    ROKU_AUTOMATION_RELATIVE_DIR: str | None = None


@router.put("/v1/config/account/update")
def update_account(body: AccountBody) -> dict:
    """Persist account settings by rewriting the assignments in config/env.py.

    Secret fields are only written when a non-empty value is supplied (so the
    masked placeholder is never saved back). Takes effect after a backend restart.
    """
    # pydantic v2 -> model_dump(), v1 -> dict(); the backend venv may be either.
    payload = (
        body.model_dump() if hasattr(body, "model_dump") else body.dict()  # type: ignore[attr-defined]
    )
    updates: dict[str, str] = {}
    for k in _ACCOUNT_FIELDS:
        v = payload.get(k)
        if v is None:
            continue
        if k in _ACCOUNT_SECRETS and not v:
            continue  # only overwrite a secret when a new value is typed
        updates[k] = v

    if not updates:
        return {"message": "No changes"}

    changed = _write_env_values(updates)
    if not changed:
        return {"message": "No changes"}

    logger.info("Account settings updated in env.py: %s", ", ".join(changed))
    return {
        "message": f"Updated: {', '.join(changed)} (restart the backend to apply)"
    }


@router.post("/v1/config/backend/restart")
def restart_backend() -> dict:
    """Restart the backend by invoking backend/restart.sh.

    restart.sh runs shutdown.sh (kills the current uvicorn) then startup.sh
    (relaunches it). Since shutdown kills the very process serving this request,
    the script is launched DETACHED (its own session) with a short delay so this
    HTTP response can return first, and so the script survives our exit.
    """
    backend_dir = os.path.abspath(os.path.join(QATOOLS_ROOT, "backend"))
    restart_sh = os.path.join(backend_dir, "restart.sh")
    if not os.path.isfile(restart_sh):
        raise HTTPException(
            status_code=500, detail=f"restart.sh not found at {restart_sh}"
        )
    # Wait ~1s so this response flushes, then run restart.sh from backend_dir.
    helper = f'sleep 1; cd "{backend_dir}" && exec bash restart.sh'
    try:
        subprocess.Popen(
            ["bash", "-c", helper],
            cwd=backend_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # detach so it survives our own exit
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to schedule backend restart")
        raise HTTPException(
            status_code=500, detail=f"Failed to restart backend: {exc}"
        ) from exc
    logger.info("Backend restart scheduled via restart.sh")
    return {"message": "Backend is restarting; reconnect in a few seconds."}
