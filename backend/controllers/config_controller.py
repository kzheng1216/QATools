import os
import subprocess
import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import yaml
from config.env import ADMIN_HASHED_PASSWORD, ADMIN_USERNAME, QATOOLS_ROOT

from . import logger

config_dir = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        os.path.join(QATOOLS_ROOT, "backend", "conf"),
    )
)
_config_path = os.path.join(config_dir, "config.yml")

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


def _load_config() -> dict:
    try:
        with open(_config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except OSError as exc:
        logger.error("Error reading config.yml: %s", exc)
        raise HTTPException(status_code=500, detail="Error reading config.yml") from exc


def _save_config(config: dict) -> None:
    # NOTE: a full round-trip rewrite drops YAML comments. That's acceptable
    # here (the file is machine-managed); sort_keys=False keeps the existing
    # top-level/section ordering stable.
    try:
        with open(_config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
    except OSError as exc:
        logger.error("Error writing config.yml: %s", exc)
        raise HTTPException(status_code=500, detail="Error writing config.yml") from exc


def _set_tab(tab_name: str, status: bool) -> dict:
    config = _load_config()
    tabs = config.get("tabs")
    if not isinstance(tabs, dict) or tab_name not in tabs:
        raise HTTPException(status_code=404, detail=f"Unknown tab '{tab_name}'")
    tabs[tab_name] = status
    _save_config(config)
    logger.info("Tab '%s' set to %s", tab_name, status)
    return {
        "message": f"Tab '{tab_name}' {'enabled' if status else 'disabled'} successfully"
    }


@router.get("/v1/config/tabs/list")
def list_tabs() -> dict:
    """List all tabs with visibility + display order.

    The order is the key order in config.yml's `tabs` map (which the left-nav
    renders in). `order` is the 0-based index.

    return:
    {"tabs": [{"name": "device", "status": true, "order": 0}, ...]}
    """
    config = _load_config()
    tabs = config.get("tabs") or {}
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
    config = _load_config()
    tabs = config.get("tabs")
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
    config["tabs"] = new_tabs
    _save_config(config)
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
    """List all configured agent models from config.yml's `agent_model`."""
    config = _load_config()
    models = config.get("agent_model") or []
    return {"models": models}


@router.post("/v1/config/models/add")
def add_model(body: AgentModelBody) -> dict:
    """Append a new agent model. Fails if the name already exists."""
    config = _load_config()
    models = config.setdefault("agent_model", [])
    if any(m.get("name") == body.name for m in models):
        raise HTTPException(
            status_code=400, detail=f"Model '{body.name}' already exists"
        )
    models.append(_model_entry(body))
    _save_config(config)
    logger.info("Agent model '%s' added", body.name)
    return {"message": f"Model '{body.name}' added successfully"}


@router.put("/v1/config/models/update/{name}")
def update_model(name: str, body: AgentModelBody) -> dict:
    """Update the agent model identified by `name` (path), replacing its fields."""
    config = _load_config()
    models = config.get("agent_model") or []
    for i, m in enumerate(models):
        if m.get("name") == name:
            models[i] = _model_entry(body)
            config["agent_model"] = models
            _save_config(config)
            logger.info("Agent model '%s' updated", name)
            return {"message": f"Model '{name}' updated successfully"}
    raise HTTPException(status_code=404, detail=f"Model '{name}' not found")


@router.delete("/v1/config/models/delete/{name}")
def delete_model(name: str) -> dict:
    """Delete the agent model identified by `name`."""
    config = _load_config()
    models = config.get("agent_model") or []
    new_models = [m for m in models if m.get("name") != name]
    if len(new_models) == len(models):
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")
    config["agent_model"] = new_models
    _save_config(config)
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
    config = _load_config()
    ac = config.get("agent_config") or {}
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
    config = _load_config()
    ac = config.setdefault("agent_config", {})
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
    _save_config(config)
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
    config = _load_config()
    ac = config.get("agent_config") or {}
    return {
        "model": ac.get("model", ""),
        "timeout_sec": ac.get("timeout_sec", 300.0),
        "max_tokens": ac.get("max_tokens", 128000),
        "temperature": ac.get("temperature", 0.7),
    }


@router.put("/v1/config/agent/default")
def set_default_model(body: DefaultModelBody) -> dict:
    """Set the default AI model: persist it to config.yml AND apply it to the
    live agent service so it takes effect immediately (no restart needed)."""
    config = _load_config()
    ac = config.setdefault("agent_config", {})
    ac["model"] = body.model
    ac["timeout_sec"] = body.timeout_sec
    ac["max_tokens"] = body.max_tokens
    ac["temperature"] = body.temperature
    _save_config(config)

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

    `default_locale` falls back to the agent_controller default; the prompt
    template has no built-in default and is "" until configured in Settings.
    """
    from . import agent_controller

    config = _load_config()
    ac = config.get("analyze_config") or {}
    return {
        "default_locale": ac.get("default_locale")
        or agent_controller._DEFAULT_ANALYZE_LOCALE,
        "prompt_template": ac.get("prompt_template") or "",
    }


@router.put("/v1/config/analyze/update")
def update_analyze_config(body: AnalyzeConfigBody) -> dict:
    """Persist the Analyze default locale + prompt template to config.yml.

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

    config = _load_config()
    analyze = config.setdefault("analyze_config", {})
    analyze["default_locale"] = locale
    analyze["prompt_template"] = body.prompt_template
    _save_config(config)
    logger.info("Analyze config updated (default_locale=%s)", locale)
    return {"message": "Analyze settings saved"}


# ---------- Account settings (config/account.json, consumed by config/env.py) ----------
import json  # noqa: E402

_account_path = os.path.abspath(os.path.join(QATOOLS_ROOT, "config", "account.json"))

# Editable account fields. Secrets are masked on read + write-only on update.
_ACCOUNT_FIELDS = (
    "QAHUB_TOKEN",
    "EMAIL",
    "TESTRAIL_USERNAME",
    "TESTRAIL_API_KEY",
    "JIRA_TOKEN",
    "DATA_BASE_DIR",
    "ROKU_TEST_LOG_DIR",
    "AUTOMATED_TESTS_RELATIVE_DIR",
)
_ACCOUNT_SECRETS = {
    "QAHUB_TOKEN",
    "TESTRAIL_USERNAME",
    "TESTRAIL_API_KEY",
    "JIRA_TOKEN",
}


def _effective_account() -> dict:
    """Current effective values: the account.json override, falling back to the
    env.py defaults for any key not overridden."""
    from config import env

    values = {k: str(getattr(env, k, "") or "") for k in _ACCOUNT_FIELDS}
    return values


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
    # fields are written through as given (empty clears the override -> env default).
    QAHUB_TOKEN: str | None = None
    EMAIL: str | None = None
    TESTRAIL_USERNAME: str | None = None
    TESTRAIL_API_KEY: str | None = None
    JIRA_TOKEN: str | None = None
    DATA_BASE_DIR: str | None = None
    ROKU_TEST_LOG_DIR: str | None = None
    AUTOMATED_TESTS_RELATIVE_DIR: str | None = None


@router.put("/v1/config/account/update")
def update_account(body: AccountBody) -> dict:
    """Persist account overrides to config/account.json.

    Secret fields are only written when a non-empty value is supplied (so the
    masked placeholder is never saved back). Takes effect after a backend restart.
    """
    try:
        if os.path.isfile(_account_path):
            with open(_account_path, encoding="utf-8") as f:
                data = json.load(f) or {}
        else:
            data = {}
    except (OSError, ValueError):
        data = {}

    payload = body.model_dump()
    changed = []
    for k in _ACCOUNT_FIELDS:
        v = payload.get(k)
        if v is None:
            continue
        if k in _ACCOUNT_SECRETS:
            if v:  # only overwrite a secret when a new value is typed
                data[k] = v
                changed.append(k)
        else:
            data[k] = v
            changed.append(k)

    if not changed:
        return {"message": "No changes"}

    try:
        os.makedirs(os.path.dirname(_account_path), exist_ok=True)
        with open(_account_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as exc:
        logger.error("Error writing account.json: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"Error writing account settings: {exc}"
        ) from exc
    logger.info("Account settings updated: %s", ", ".join(changed))
    return {"message": f"Updated: {', '.join(changed)}"}


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
