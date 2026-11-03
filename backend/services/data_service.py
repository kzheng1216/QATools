#!/usr/bin/env python3
"""Data-access layer for the backend's structured data files.

Every controller that needs to read or write a data file under
``backend/conf`` goes through a *data store* defined here instead of opening
the file itself. That keeps the file format (and one day the storage backend)
an implementation detail of this module.

Layout::

    BaseDataStore      abstract base: section-oriented CRUD API
      |- YamlDataStore   stores sections in a YAML file under backend/conf
      `- DbDataStore     stores sections in a database table (placeholder)

A "section" is a top-level key of the document, e.g. ``tabs``,
``agent_model`` or ``file_transfer``.

Typical use from a controller::

    from services.data_service import TABS_STORE

    tabs = TABS_STORE.get_section("tabs", {})
    tabs["device"] = False
    TABS_STORE.set_section("tabs", tabs)
"""

from __future__ import annotations

import os
import sys
import threading
from abc import ABC, abstractmethod
from typing import Any

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import QATOOLS_ROOT

from . import logger


class DataServiceError(RuntimeError):
    """Raised when a data store cannot be read or written."""


# Directory holding every backend data file managed here.
CONF_DIR = os.path.abspath(os.path.join(QATOOLS_ROOT, "backend", "conf"))

# conf/config.yml is the bootstrap file: it is the only name hard-coded here,
# because its `data_files` map names every other data file.
CONFIG_FILE = "config.yml"

# Logical data-file keys that config.yml's `data_files` map must define. There
# are deliberately no built-in defaults: the file names live in config.yml only.
_REQUIRED_DATA_FILE_KEYS: tuple[str, ...] = (
    "tabs",
    "agent",
    "analyze",
    "file_transfer",
    "runcase",
    "ref",
    "testrail",
    "user",
)

# Top-level yaml section -> the logical data-file key that owns it.
SECTION_KEYS: dict[str, str] = {
    "server_config": "config",
    "data_files": "config",
    "tabs": "tabs",
    "agent_config": "agent",
    "agent_model": "agent",
    "analyze_config": "analyze",
    "file_transfer": "file_transfer",
    "runcase_user_query_list": "runcase",
    "roku_test_cache_data": "runcase",
    "ref": "ref",
    "docs": "ref",
    "testrail": "testrail",
}


def _read_data_files() -> dict[str, str]:
    """Read the `data_files` map from conf/config.yml.

    This is the single source of truth for every data file name, so a missing
    map or a missing/blank entry is a hard configuration error rather than
    something silently patched up with a built-in default.

    Done with a plain yaml load rather than a store, since the stores are what
    this map is used to build.
    """
    path = os.path.join(CONF_DIR, CONFIG_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.error("Error reading %s: %s", path, exc)
        raise DataServiceError(f"Error reading {CONFIG_FILE}: {exc}") from exc

    configured = data.get("data_files") if isinstance(data, dict) else None
    if not isinstance(configured, dict):
        raise DataServiceError(
            f"{path} must define a 'data_files' mapping naming the data files "
            f"({', '.join(_REQUIRED_DATA_FILE_KEYS)})"
        )

    files: dict[str, str] = {}
    missing: list[str] = []
    for key in _REQUIRED_DATA_FILE_KEYS:
        name = str(configured.get(key) or "").strip()
        if not name:
            missing.append(key)
            continue
        files[key] = name
    if missing:
        raise DataServiceError(
            f"{path} 'data_files' is missing a file name for: {', '.join(missing)}"
        )

    for key in configured:
        if key not in _REQUIRED_DATA_FILE_KEYS and key != "config":
            logger.warning("Ignoring unknown data_files key '%s' in %s", key, path)

    # config.yml names itself; honouring a different value here would make the
    # bootstrap read above inconsistent, so keep it pinned.
    files["config"] = CONFIG_FILE
    logger.info("Loaded data file names from %s: %s", path, files)
    return files


# Logical key -> actual file name, as configured in conf/config.yml.
DATA_FILES: dict[str, str] = _read_data_files()

# File names (resolved from config.yml's `data_files`).
TABS_FILE = DATA_FILES["tabs"]
AGENT_FILE = DATA_FILES["agent"]
ANALYZE_FILE = DATA_FILES["analyze"]
FILE_TRANSFER_FILE = DATA_FILES["file_transfer"]
RUNCASE_FILE = DATA_FILES["runcase"]
REF_FILE = DATA_FILES["ref"]
TESTRAIL_FILE = DATA_FILES["testrail"]
USER_FILE = DATA_FILES["user"]

# Top-level section -> the file that owns it.
SECTION_FILES: dict[str, str] = {
    section: DATA_FILES[key] for section, key in SECTION_KEYS.items()
}


class BaseDataStore(ABC):
    """Section-oriented CRUD over one logical document.

    Subclasses only implement :meth:`read_all` / :meth:`write_all`; every other
    method is expressed in terms of those two, so a new backend (YAML, DB, ...)
    needs no extra code in the controllers.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._lock = threading.RLock()

    # ----- backend-specific -------------------------------------------------
    @abstractmethod
    def read_all(self) -> dict[str, Any]:
        """Return the whole document as a dict (``{}`` when missing)."""

    @abstractmethod
    def write_all(self, data: dict[str, Any]) -> None:
        """Replace the whole document."""

    @abstractmethod
    def exists(self) -> bool:
        """True when the underlying storage already holds the document."""

    # ----- generic section API ---------------------------------------------
    def get_section(self, section: str, default: Any = None) -> Any:
        """Return one top-level section, or `default` when absent/empty."""
        value = self.read_all().get(section)
        return default if value is None else value

    def set_section(self, section: str, value: Any) -> None:
        """Create/replace one top-level section, keeping the others intact."""
        with self._lock:
            data = self.read_all()
            data[section] = value
            self.write_all(data)

    def update_sections(self, sections: dict[str, Any]) -> None:
        """Create/replace several top-level sections in a single write."""
        with self._lock:
            data = self.read_all()
            data.update(sections)
            self.write_all(data)

    def delete_section(self, section: str) -> bool:
        """Drop a section. Returns False when it was not there."""
        with self._lock:
            data = self.read_all()
            if section not in data:
                return False
            del data[section]
            self.write_all(data)
            return True

    # ----- typed helpers (sections are either a mapping or a list) ----------
    def get_dict(self, section: str) -> dict[str, Any]:
        value = self.get_section(section)
        return value if isinstance(value, dict) else {}

    def get_list(self, section: str) -> list[Any]:
        value = self.get_section(section)
        return value if isinstance(value, list) else []

    def update_dict(self, section: str, values: dict[str, Any]) -> dict[str, Any]:
        """Merge `values` into a mapping section and persist it."""
        with self._lock:
            data = self.read_all()
            current = data.get(section)
            if not isinstance(current, dict):
                current = {}
            current.update(values)
            data[section] = current
            self.write_all(data)
            return current

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<{type(self).__name__} {self.name}>"


class YamlDataStore(BaseDataStore):
    """YAML-file implementation of :class:`BaseDataStore`.

    One instance == one ``*.yml`` file under ``backend/conf`` (or any absolute
    path passed in). Writes are a full round-trip rewrite: YAML comments are
    lost, which is fine since these files are machine-managed. ``sort_keys``
    stays off so section order (used by the left-nav tab order) is stable.
    """

    def __init__(
        self,
        file_name: str,
        conf_dir: str | None = None,
        allow_unicode: bool = True,
    ) -> None:
        path = (
            file_name
            if os.path.isabs(file_name)
            else os.path.join(conf_dir or CONF_DIR, file_name)
        )
        super().__init__(os.path.basename(path))
        self.path = os.path.abspath(path)
        self.allow_unicode = allow_unicode

    def exists(self) -> bool:
        return os.path.isfile(self.path)

    def read_all(self) -> dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {}
        except (OSError, yaml.YAMLError) as exc:
            logger.error("Error reading %s: %s", self.name, exc)
            raise DataServiceError(f"Error reading {self.name}: {exc}") from exc
        if not isinstance(data, dict):
            raise DataServiceError(f"{self.name} must be a mapping at the top level")
        return data

    def write_all(self, data: dict[str, Any]) -> None:
        tmp_path = f"{self.path}.tmp"
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            # Write to a temp file then replace, so a failed write can never
            # truncate a good data file.
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    data,
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=self.allow_unicode,
                )
            os.replace(tmp_path, self.path)
        except (OSError, yaml.YAMLError) as exc:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            logger.error("Error writing %s: %s", self.name, exc)
            raise DataServiceError(f"Error writing {self.name}: {exc}") from exc


class DbDataStore(BaseDataStore):
    """Database-backed implementation of :class:`BaseDataStore`.

    Placeholder for the planned migration off YAML: each document becomes a row
    set of ``(document, section, value)`` in `table`. Controllers already talk
    only to the base API, so switching a store from :class:`YamlDataStore` to
    this class is the only change they will need.
    """

    def __init__(
        self,
        document: str,
        connection: Any = None,
        table: str = "qatools_data",
    ) -> None:
        super().__init__(document)
        self.document = document
        self.connection = connection
        self.table = table

    def _require_connection(self) -> Any:
        if self.connection is None:
            raise DataServiceError(
                f"no database connection configured for document '{self.document}'"
            )
        return self.connection

    def exists(self) -> bool:
        raise NotImplementedError("DbDataStore is not implemented yet")

    def read_all(self) -> dict[str, Any]:
        self._require_connection()
        raise NotImplementedError("DbDataStore is not implemented yet")

    def write_all(self, data: dict[str, Any]) -> None:
        self._require_connection()
        raise NotImplementedError("DbDataStore is not implemented yet")


# ---------------------------------------------------------------------------
# Store registry: one shared instance per file, so the per-store lock actually
# serializes concurrent read-modify-write cycles from different controllers.
# ---------------------------------------------------------------------------
_stores: dict[str, BaseDataStore] = {}
_registry_lock = threading.Lock()


def get_store(file_name: str) -> BaseDataStore:
    """Return the (cached) store for a conf file name, e.g. ``"tabs_data.yml"``."""
    key = os.path.abspath(
        file_name if os.path.isabs(file_name) else os.path.join(CONF_DIR, file_name)
    )
    with _registry_lock:
        store = _stores.get(key)
        if store is None:
            store = YamlDataStore(key)
            _stores[key] = store
        return store


def store_for_section(section: str) -> BaseDataStore:
    """Return the store owning a top-level section (e.g. ``"agent_model"``)."""
    return get_store(SECTION_FILES.get(section, CONFIG_FILE))


def read_section(section: str, default: Any = None) -> Any:
    """Convenience read of a section from whichever store owns it."""
    return store_for_section(section).get_section(section, default)


# Named stores used by the controllers.
CONFIG_STORE = get_store(CONFIG_FILE)
TABS_STORE = get_store(TABS_FILE)
AGENT_STORE = get_store(AGENT_FILE)
ANALYZE_STORE = get_store(ANALYZE_FILE)
FILE_TRANSFER_STORE = get_store(FILE_TRANSFER_FILE)
RUNCASE_STORE = get_store(RUNCASE_FILE)
REF_STORE = get_store(REF_FILE)
TESTRAIL_STORE = get_store(TESTRAIL_FILE)
USER_STORE = get_store(USER_FILE)
