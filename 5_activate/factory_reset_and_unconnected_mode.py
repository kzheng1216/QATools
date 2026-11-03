#!/usr/bin/env python3
"""Factory reset a Roku TV and run guided setup in the configured connection mode.

By default (``CONNECT_TO_NETWORK = False``) guided setup is driven through the network
screen and the "Connect to network later" option is selected, so the device ends up
unconnected (no network, no account activation).

Set ``CONNECT_TO_NETWORK = True`` to instead connect during guided setup; the default
connection type is wired (``WIRED_NETWORK``).
"""

from __future__ import annotations

import os
import sys
import time
from importlib import import_module
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.device_conf.device_info import DeviceInfo
from config.env import QATOOLS_ROOT, ROKU_AUTOMATION_RELATIVE_DIR
from config.log import LogUtil

logger = LogUtil.init_logger(
    log_dir=str(Path(__file__).parent / "logs"), log_name="activate.log"
)

SAVE_WIFI_DATA = False
GUI_RESET = True
LANGUAGE = "en"

# Default connection type used when the device DOES connect during guided setup.
WIRED_NETWORK = {"wired": True}

# Connection mode:
#   False -> unconnected mode: guided setup selects "Connect to network later" (current default).
#   True  -> connect during guided setup using WIRED_NETWORK.
CONNECT_TO_NETWORK = False

# network=None makes guided setup select "Connect to network later" => unconnected mode.
NETWORK = WIRED_NETWORK if CONNECT_TO_NETWORK else None

ROKU_AUTOMATION_PATHS = (
    Path(os.path.abspath(os.path.join(QATOOLS_ROOT, ROKU_AUTOMATION_RELATIVE_DIR))),
    Path("/workspaces/automation-ide/roku_automation"),
)


def print_log(msg: str) -> None:
    """Print log messages with a consistent prefix."""
    logger.info("#####################################################################")
    logger.info(f"## {msg}")
    logger.info("#####################################################################")


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


def factory_reset(r: Any) -> None:
    """Factory reset the TV and refresh the Roku object after reboot."""
    print_log("Performing factory reset...")
    r.system.reset_to_factory_defaults(save_wifi_data=SAVE_WIFI_DATA, gui=GUI_RESET)
    r.refresh()


def run_guided_setup(r: Any) -> None:
    """Run guided setup for the configured connection mode.

    With ``NETWORK`` set to ``None`` (CONNECT_TO_NETWORK=False), ``complete_guided_setup``
    focuses the ``connect-later`` option on the "Choose your network" screen and returns,
    leaving the device in unconnected mode. With ``NETWORK`` set (e.g. wired), guided setup
    connects and links an account as usual.
    """
    mode = (
        f"connected: {NETWORK}"
        if NETWORK is not None
        else "unconnected (Connect to network later)"
    )
    print_log(f"Starting guided setup ({mode})...")
    setup_params = {
        "language": f"language:{LANGUAGE}",
        "country": f"country:{r.system.country}",
        "network": NETWORK,
    }
    r.ui.complete_guided_setup(params=setup_params, link_account_using_email=True)


def additional_actions(r: Any) -> None:
    """Disable auto power down and enable fast TV start."""
    print_log("Performing additional actions...")
    try:
        r.system.set_auto_power_down(state=False)
        r.system.set_fast_tv_start(enable=True)
        time.sleep(15)
    except Exception:
        logger.exception("Error performing additional actions")

    r.ui.keypress(codes=["home"])
    r.ui.focus(["settings", "system-settings", "about"])


def activate(ip_address: str) -> None:
    """Factory reset the target TV and run guided setup for the configured connection mode."""
    try:
        roku = create_roku(ip_address)
        factory_reset(roku)
        run_guided_setup(roku)
        if NETWORK is None:
            print_log("Guided setup complete: device left in unconnected mode.")
        else:
            print_log(f"Guided setup complete: device connected via {NETWORK}.")

        # Additional actions
        additional_actions(roku)
    except Exception:
        logger.exception(f"Error activating device at {ip_address}")


def start_activation(device_name: str) -> dict:
    """Factory reset and set up the named device, returning a result dict."""
    device = DeviceInfo().devices.get(device_name, {})
    device_ip = device.get("config", {}).get("roku", {}).get("ip_address", "")
    if not device_ip:
        logger.error(f"Setup failed: Device {device_name} not found")
        return {
            "success": False,
            "message": f"Setup failed: Device {device_name} not found",
        }

    logger.info(f"Setup started for device {device_name} at {device_ip}")
    try:
        activate(device_ip)
    except Exception as exc:
        logger.exception(f"Error setting up device {device_name} at {device_ip}")
        return {
            "success": False,
            "message": f"Setup failed for device {device_name}: {exc}",
        }

    return {
        "success": True,
        "message": f"Setup completed for device {device_name}",
    }


def main() -> int:
    if len(sys.argv) != 2:
        logger.error(
            "Usage: python -m QATools.5_activate.factory_reset_and_unconnected_mode <device_name>"
        )
        return 1
    device_name = sys.argv[1]
    try:
        result = start_activation(device_name)
        logger.info(f"Setup result: {result}")
        return 0 if result.get("success") else 1
    except Exception:
        logger.exception(f"Error setting up device {device_name}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
