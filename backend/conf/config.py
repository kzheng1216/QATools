#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Reading the conf/*.yml files is the data service's job. The *_FILE names are
# re-exported for callers that still import them from here.
from services.data_service import (  # noqa: E402,F401
    AGENT_FILE,
    ANALYZE_FILE,
    CONFIG_FILE,
    FILE_TRANSFER_FILE,
    RUNCASE_FILE,
    SECTION_FILES,
    TABS_FILE,
    DataServiceError,
    get_store,
)
from services.data_service import read_section as _read_section  # noqa: E402

from . import logger


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    base_url: str
    api_key: str
    key_id: str
    key_alias: str
    model: str
    timeout_sec: float
    max_tokens: int
    temperature: float


# Maps flat config keys -> (yaml_section, yaml_key, env_var, caster).
_SCHEMA: tuple[tuple[str, str, str, str, type], ...] = (
    ("host", "server_config", "host", "QATOOLS_SERVER_HOST", str),
    ("port", "server_config", "port", "QATOOLS_SERVER_PORT", int),
    ("base_url", "agent_config", "base_url", "QATOOLS_AGENT_BASE_URL", str),
    ("api_key", "agent_config", "api_key", "QATOOLS_AGENT_API_KEY", str),
    ("key_id", "agent_config", "key_id", "QATOOLS_AGENT_KEY_ID", str),
    ("key_alias", "agent_config", "key_alias", "QATOOLS_AGENT_KEY_ALIAS", str),
    ("model", "agent_config", "model", "QATOOLS_AGENT_MODEL", str),
    ("timeout_sec", "agent_config", "timeout_sec", "QATOOLS_AGENT_TIMEOUT_SEC", float),
    ("max_tokens", "agent_config", "max_tokens", "QATOOLS_AGENT_MAX_TOKENS", int),
    ("temperature", "agent_config", "temperature", "QATOOLS_AGENT_TEMPERATURE", float),
)


# config.yml only keeps `server_config`; every other section was split out into
# its own data file in this same directory. The file names and the
# section -> file map are owned by services/data_service.py and re-exported
# here for backwards compatibility.
_SECTION_FILES = SECTION_FILES


def conf_dir() -> Path:
    """Directory holding config.yml and the *_data.yml files.

    QATOOLS_AGENT_CONFIG_PATH still points at config.yml; the data files are
    resolved next to it.
    """
    override = os.getenv("QATOOLS_AGENT_CONFIG_PATH")
    if override:
        return Path(override).expanduser().resolve().parent
    return Path(__file__).resolve().parent


def yaml_path(file_name: str = CONFIG_FILE) -> Path:
    """Absolute path of a conf yaml file (config.yml by default)."""
    return conf_dir() / file_name


def section_path(section: str) -> Path:
    """Path of the yaml file that owns the given top-level section."""
    return yaml_path(_SECTION_FILES.get(section, CONFIG_FILE))


def _default_yaml_path() -> Path:
    return Path(__file__).resolve().parent / CONFIG_FILE


def _yaml_path() -> Path:
    override = os.getenv("QATOOLS_AGENT_CONFIG_PATH")
    return Path(override).expanduser() if override else _default_yaml_path()


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a conf yaml file through the data service."""
    try:
        return get_store(str(path)).read_all()
    except DataServiceError as exc:
        raise ConfigError(str(exc)) from exc


def _cast(value: Any, caster: type, key: str) -> Any:
    try:
        if caster is bool:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "on"}
        return caster(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"invalid value for config key '{key}': {value!r} ({exc})"
        ) from exc


def _resolve(
    key: str,
    section: str,
    yaml_key: str,
    env_var: str,
    caster: type,
    yaml_data: dict[str, Any],
) -> Any:
    env_val = os.getenv(env_var)
    if env_val not in (None, ""):
        return _cast(env_val, caster, key)

    section_data = yaml_data.get(section)
    if isinstance(section_data, dict) and yaml_key in section_data:
        val = section_data[yaml_key]
        if val is not None and val != "":
            return _cast(val, caster, key)

    raise ConfigError(
        f"missing required agent config '{key}': set yaml key '{section}.{yaml_key}' "
        f"or env var '{env_var}'"
    )


def read_section(section: str) -> Any:
    """Read one top-level section from whichever data store owns it."""
    try:
        return _read_section(section)
    except DataServiceError as exc:
        raise ConfigError(str(exc)) from exc


def load() -> Config:
    # Sections now live in different files; merge the ones the schema needs.
    yaml_data: dict[str, Any] = {}
    for file_name in dict.fromkeys(_SECTION_FILES[s] for _, s, _, _, _ in _SCHEMA):
        path = yaml_path(file_name)
        data = _read_yaml(path)
        if data:
            logger.info("loaded config from %s", path)
        else:
            logger.info("config yaml %s not found; relying on env vars", path)
        yaml_data.update(data)

    values: dict[str, Any] = {}
    missing: list[str] = []
    for key, section, yaml_key, env_var, caster in _SCHEMA:
        try:
            values[key] = _resolve(key, section, yaml_key, env_var, caster, yaml_data)
        except ConfigError as exc:
            missing.append(str(exc))

    if missing:
        raise ConfigError("configuration is incomplete:\n  - " + "\n  - ".join(missing))

    return Config(**values)


config = load()
