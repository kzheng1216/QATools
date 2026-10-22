#!/usr/bin/env python3
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

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


def _default_yaml_path() -> Path:
    return Path(__file__).resolve().parent / "config.yml"


def _yaml_path() -> Path:
    override = os.getenv("QATOOLS_AGENT_CONFIG_PATH")
    return Path(override).expanduser() if override else _default_yaml_path()


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"failed to read agent config yaml {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"agent config yaml {path} must be a mapping at the top level"
        )
    return data


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


def load() -> Config:
    path = _yaml_path()
    yaml_data = _read_yaml(path)
    if yaml_data:
        logger.info("loaded config from %s", path)
    else:
        logger.info("config yaml %s not found; relying on env vars", path)

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
