#!/usr/bin/env python3
"""Factory reset a Roku TV and activate it with the WebNinjas API."""

from __future__ import annotations

import sys
import threading
import time
from importlib import import_module
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.device_conf.device_info import DeviceInfo

device: dict[str, Any] = DeviceInfo().devices["d_us_428"]

DEVICE_IP = device["config"]["roku"]["ip_address"]
ACCOUNT_EMAIL = device["activate_email"]
SAVE_WIFI_DATA = True
GUI_RESET = True
NETWORK = {"wired": True}
LANGUAGE = "en"
ACTIVATION_TIMEOUT_SECONDS = 600
DEVICE_LOCATION = "Office"

ROKU_AUTOMATION_PATHS = (
    Path("/workspaces/automation-ide/roku_automation"),
    Path("/home/roku/workspaces/automation-ide/roku_automation"),
)


def print_log(msg: str) -> None:
    """Print log messages with a consistent prefix."""
    print("#####################################################################")
    print(f"## {msg}")
    print("#####################################################################")


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


def guided_setup(r: Any, link_account: str) -> None:
    """Complete guided setup while another thread performs WebNinjas activation."""
    print_log("Starting guided setup...")
    setup_params = {
        "language": f"language:{LANGUAGE}",
        "country": f"country:{r.system.country}",
        "network": NETWORK,
        "link_account": link_account,
    }
    try:
        r.ui.complete_guided_setup(params=setup_params, link_account_using_email=True)
    except Exception as exc:
        print(f"==== [Guided Setup]: {exc}")


def account_link(r: Any, SN: str, link_account: str) -> None:
    """Activate the device by calling the WebNinjas activation API."""
    print_log("Starting account link...")
    url = "https://webninjas.portal.roku.com/api/1.0/activate"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "PostmanRuntime/7.29.0",
    }
    payload = {
        "env": "production",
        "linkCode": "",
        "esn": SN,
        "deviceDeviceId": "",
        "email": link_account,
        "deviceName": "",
        "deviceLocation": DEVICE_LOCATION,
    }
    max_retries = 5
    for attempt in range(max_retries):
        response = requests.post(url=url, json=payload, headers=headers, timeout=10)
        print(f"==== [WebNinjas Activation]: {response.status_code} - {response.text}")
        # if response.status_code == 200:
        #     break
        if attempt < max_retries - 1:
            print(
                f"==== [WebNinjas Activation]: retrying account link in 30 seconds... (attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(30)


def additional_actions(r: Any) -> None:
    """Disable auto power down and enable fast TV start."""
    print_log("Performing additional actions...")
    r.system.set_auto_power_down(state=False)
    r.system.set_fast_tv_start(enable=True)

    r.ui.keypress(codes=["home"])
    r.ui.focus(["settings", "system-settings", "about"])


def is_activation_screen(screen_text: str) -> bool:
    """Return whether current screen text is an activation screen."""
    return any(
        text in screen_text
        for text in ("Activate your TV", "Activate your Roku player", "roku.com/link")
    )


def activate(ip_address: str, link_account: str) -> None:
    """Factory reset the target TV, complete guided setup, and activate it."""
    try:
        roku = create_roku(ip_address)
        SN = roku.hardware.serial_number
        factory_reset(roku)

        threading.Thread(target=guided_setup, args=(roku, link_account)).start()

        start_time = time.time()
        activation_sent = False
        while time.time() - start_time <= ACTIVATION_TIMEOUT_SECONDS:
            screen_text = roku.ui.get_screen_text()
            print(f"---->>Current screen text: {screen_text}")
            if not activation_sent and is_activation_screen(screen_text):
                print(
                    "==== [WebNinjas Activation]: Activation screen detected, sending account link request..."
                )
                account_link(roku, SN, link_account)
                activation_sent = True

            print("====>>> verifying activation result")
            if "connect your devices" in screen_text:
                print("Activation successful, finishing guided setup...")
                roku.ui.keypress(codes=["ok", "down", "ok"])
                break

            time.sleep(2)

        # Additional actions
        additional_actions(roku)
    except Exception as exc:
        print(
            f"==== [WebNinjas Activation]: Error activating device at {ip_address}: {exc}"
        )


def main() -> int:
    activate(DEVICE_IP, ACCOUNT_EMAIL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
