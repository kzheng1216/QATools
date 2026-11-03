from __future__ import annotations

import json
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

ROKU_AUTOMATION_PATHS = (
    Path(__file__).resolve().parents[3] / "roku_automation",
    Path("/workspaces/automation-ide/roku_automation"),
)


def add_roku_automation_to_path() -> None:
    """Make the local roku_automation checkout importable when running this script directly."""
    for candidate in ROKU_AUTOMATION_PATHS:
        if candidate.exists():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)
            return
    raise RuntimeError(f"Could not find roku_automation in: {ROKU_AUTOMATION_PATHS}")


def create_roku(ip_address: str) -> Any:
    """Create a Roku API object for the target device."""
    add_roku_automation_to_path()
    try:
        return import_module("roku_api.roku").Roku(ip_address)
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"Missing Python dependency while importing roku_api: {exc.name!r}. "
            "Run this script in the automation environment with roku_automation dependencies installed."
        ) from exc


def precheck(ip_address: str) -> dict:
    """Return connection/link state and whether activation is allowed."""
    roku = create_roku(ip_address)
    connection_type = roku.network.info["connection_type"]
    is_linked = roku.account.is_linked
    activation_allowed = not (not is_linked and connection_type == "wifi")
    return {
        "connection_type": connection_type,
        "is_linked": is_linked,
        "activation_allowed": activation_allowed,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "Usage: precheck_connection.py <ip_address>"}))
        return 1
    ip_address = sys.argv[1]
    try:
        print(json.dumps(precheck(ip_address)))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
