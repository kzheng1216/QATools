import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from config.env import QAHUB_HEADERS, QAHUB_URL
from fastapi import APIRouter, HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import QATOOLS_ROOT

from . import logger

device_conf_dir = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), os.path.join(QATOOLS_ROOT, "config", "device_conf")
    )
)

router = APIRouter()


@router.get("/v1/device/list")
def list_devices() -> dict[str, list[str]]:
    """List the available device configuration files."""
    logger.info("List devices from: %s", device_conf_dir)

    try:
        os.makedirs(device_conf_dir, exist_ok=True)
        files = [f for f in os.listdir(device_conf_dir) if f.endswith(".json")]
    except OSError as exc:
        logger.error("Device configuration directory not accessible: %s", exc)
        raise HTTPException(
            status_code=500, detail="Device configuration directory not accessible"
        ) from exc

    return {"devices": files}


@router.get("/v1/device/list_details")
def list_device_details() -> dict:
    """List devices with presence flags for key roku config sub-sections.

    For each device file, report whether these fields exist (used by the Device
    table to show a check/cross per column):
        roku.qa_bot_config, roku.maxwell_config, roku.power_config,
        roku.avr_info_config,
        roku.devices_config["HDMI 1"|"HDMI 2"|"HDMI 3"].
    Also returns roku.ip_address as a value for the IP column.

    A device that fails to parse still appears, with all flags false.
    """
    logger.info("List device details from: %s", device_conf_dir)
    try:
        os.makedirs(device_conf_dir, exist_ok=True)
        files = sorted(f for f in os.listdir(device_conf_dir) if f.endswith(".json"))
    except OSError as exc:
        logger.error("Device configuration directory not accessible: %s", exc)
        raise HTTPException(
            status_code=500, detail="Device configuration directory not accessible"
        ) from exc

    devices = []
    for fname in files:
        name = fname[: -len(".json")]
        roku: dict = {}
        try:
            with open(os.path.join(device_conf_dir, fname), encoding="utf-8") as f:
                data = json.load(f)
            roku = data.get("roku") or {}
            if not isinstance(roku, dict):
                roku = {}
        except (OSError, ValueError) as exc:
            logger.warning("Could not parse device '%s': %s", name, exc)

        devices_config = roku.get("devices_config") or {}
        if not isinstance(devices_config, dict):
            devices_config = {}

        stb_present = (
            any(
                device_value.get("device_type") == "ROKU"
                for device_value in devices_config.values()
            )
            if devices_config
            else False
        )
        devices.append(
            {
                "name": name,
                "ip_address": str(roku.get("ip_address") or ""),
                "qa_bot_config": "qa_bot_config" in roku,
                "maxwell_config": "maxwell_config" in roku,
                "power_config": "power_config" in roku,
                "avr_info_config": "avr_info_config" in roku,
                "hdmi_1": "HDMI 1" in devices_config,
                "hdmi_2": "HDMI 2" in devices_config,
                "hdmi_3": "HDMI 3" in devices_config,
                "stb": stb_present,
            }
        )
    return {"devices": devices}


@router.get("/v1/device/{device_name}")
def view_device(device_name: str) -> dict:
    """View the contents of a specific device configuration file."""
    logger.info("View device: %s", device_name)

    device_file_path = os.path.join(device_conf_dir, f"{device_name}.json")

    if not os.path.isfile(device_file_path):
        logger.warning("Device configuration '%s' not found", device_name)
        raise HTTPException(
            status_code=404, detail=f"Device configuration '{device_name}' not found"
        )

    try:
        with open(device_file_path, "r") as f:
            device_data = f.read()
    except OSError as exc:
        logger.error("Error reading device '%s': %s", device_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error reading device configuration '{device_name}'",
        ) from exc

    return json.loads(device_data)


@router.patch("/v1/device/update/{device_name}")
def update_device(device_name: str, device_data: dict) -> dict:
    """Update an existing device configuration file."""
    logger.info("Update device: %s", device_name)

    device_file_path = os.path.join(device_conf_dir, f"{device_name}.json")

    if not os.path.isfile(device_file_path):
        logger.warning("Device configuration '%s' not found", device_name)
        raise HTTPException(
            status_code=404, detail=f"Device configuration '{device_name}' not found"
        )

    try:
        with open(device_file_path, "w") as f:
            json.dump(device_data, f, indent=4)
    except OSError as exc:
        logger.error("Error updating device '%s': %s", device_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error updating device configuration '{device_name}'",
        ) from exc

    logger.info("Device configuration '%s' updated", device_name)
    return {"message": f"Device configuration '{device_name}' updated successfully"}


@router.post("/v1/device/add/{device_name}")
def add_device(device_name: str, device_data: dict) -> dict:
    """Add a new device configuration file."""
    logger.info("Add device: %s", device_name)

    try:
        os.makedirs(device_conf_dir, exist_ok=True)
    except OSError as exc:
        logger.error("Device configuration directory not accessible: %s", exc)
        raise HTTPException(
            status_code=500, detail="Device configuration directory not accessible"
        ) from exc

    device_file_path = os.path.join(device_conf_dir, f"{device_name}.json")

    if os.path.isfile(device_file_path):
        logger.warning("Device configuration '%s' already exists", device_name)
        raise HTTPException(
            status_code=400,
            detail=f"Device configuration '{device_name}' already exists",
        )

    try:
        with open(device_file_path, "w") as f:
            json.dump(device_data, f, indent=4)
    except OSError as exc:
        logger.error("Error writing device '%s': %s", device_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error writing device configuration '{device_name}'",
        ) from exc

    logger.info("Device configuration '%s' added", device_name)
    return {"message": f"Device configuration '{device_name}' added successfully"}


@router.delete("/v1/device/delete/{device_name}")
def delete_device(device_name: str) -> dict:
    """Delete a specific device configuration file."""
    logger.info("Delete device: %s", device_name)

    device_file_path = os.path.join(device_conf_dir, f"{device_name}.json")

    if not os.path.isfile(device_file_path):
        logger.warning("Device configuration '%s' not found", device_name)
        raise HTTPException(
            status_code=404, detail=f"Device configuration '{device_name}' not found"
        )

    try:
        os.remove(device_file_path)
    except OSError as exc:
        logger.error("Error deleting device '%s': %s", device_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting device configuration '{device_name}'",
        ) from exc

    logger.info("Device configuration '%s' deleted", device_name)
    return {"message": f"Device configuration '{device_name}' deleted successfully"}


@router.patch("/v1/device/sync_with_qa_hub/{device_name}")
def sync_with_qa_hub(device_name: str) -> dict:
    """Sync the device configuration with the QA Hub."""
    logger.info("Sync device: %s with QA Hub", device_name)

    device_file_path = os.path.join(device_conf_dir, f"{device_name}.json")
    if not os.path.isfile(device_file_path):
        logger.warning("Device configuration '%s' not found", device_name)
        raise HTTPException(
            status_code=404, detail=f"Device configuration '{device_name}' not found"
        )

    try:
        with open(device_file_path, encoding="utf-8") as f:
            local_device = json.load(f)
        serial_number = local_device["roku"]["serial_number"]

        req = urllib.request.Request(
            f"{QAHUB_URL.rstrip('/')}/roku/preview-device-json/{serial_number}",
            headers=QAHUB_HEADERS,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")

        synced_device = payload.get("device")
        if not synced_device:
            raise ValueError(
                f"QA Hub returned no device data for serial '{serial_number}'"
            )

        with open(device_file_path, "w", encoding="utf-8") as f:
            json.dump(synced_device, f, indent=4)

        logger.info(
            "Device configuration '%s' synced with QA Hub (serial=%s)",
            device_name,
            serial_number,
        )
        return {
            "Result": "SUCCESS",
            "Message": f"Device configuration '{device_name}' synced with QA Hub successfully",
        }

    except HTTPException:
        raise
    except (KeyError, TypeError) as exc:
        logger.error("Device '%s' missing serial_number: %s", device_name, exc)
        return {
            "Result": "FAILED",
            "Message": f"Device configuration '{device_name}' missing roku.serial_number",
        }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        logger.error(
            "QA Hub sync failed for '%s': HTTP %s %s", device_name, exc.code, body
        )
        return {
            "Result": "FAILED",
            "Message": f"QA Hub returned HTTP {exc.code} while syncing '{device_name}'",
        }
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        logger.error("Error syncing device '%s' with QA Hub: %s", device_name, exc)
        return {
            "Result": "FAILED",
            "Message": f"Device configuration '{device_name}' synced with QA Hub failed: {exc}",
        }


@router.patch("/v1/device/reservations/{device_name}")
def reserve_device(device_name: str) -> dict:
    """Reserve a device for a user."""
    logger.info("Reserve device: %s", device_name)

    device_file_path = os.path.join(device_conf_dir, f"{device_name}.json")
    if not os.path.isfile(device_file_path):
        logger.warning("Device configuration '%s' not found", device_name)
        raise HTTPException(
            status_code=404, detail=f"Device configuration '{device_name}' not found"
        )

    try:
        with open(device_file_path, encoding="utf-8") as f:
            local_device = json.load(f)
        serial_number = local_device["roku"]["serial_number"]
        if not serial_number:
            raise KeyError("serial_number")

        end = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
        req = urllib.request.Request(
            f"{QAHUB_URL.rstrip('/')}/roku/reservations",
            data=json.dumps(
                {
                    "serial_numbers": [serial_number],
                    "start": -1,
                    "end": end,
                    "steal": True,
                }
            ).encode("utf-8"),
            # QA Hub only parses the JSON body when Content-Type says so; without
            # it the request fails with 422 "serial_numbers is a required parameter".
            headers={**QAHUB_HEADERS, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            response = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")

        # QA Hub answers { "status": 0 } on success (non-zero status + "error" on
        # failure); there is no "result" field.
        if response.get("status") not in (0, None):
            raise ValueError(
                response.get("error") or response.get("message") or "unknown error"
            )

        logger.info(
            "Device '%s' (serial=%s) reserved until %s", device_name, serial_number, end
        )
        return {
            "Result": "SUCCESS",
            "Message": f"Device '{device_name}' reserved until {end}",
        }

    except HTTPException:
        raise
    except (KeyError, TypeError) as exc:
        logger.error("Device '%s' missing serial_number: %s", device_name, exc)
        return {
            "Result": "FAILED",
            "Message": f"Device configuration '{device_name}' missing roku.serial_number",
        }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        try:
            detail = json.loads(body).get("error") or body
        except (json.JSONDecodeError, AttributeError):
            detail = body
        logger.error(
            "Reserve failed for '%s': HTTP %s %s", device_name, exc.code, detail
        )
        return {
            "Result": "FAILED",
            "Message": f"QA Hub returned HTTP {exc.code}: {detail}",
        }
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        logger.error("Error reserving device '%s': %s", device_name, exc)
        return {
            "Result": "FAILED",
            "Message": f"Reserving device '{device_name}' failed: {exc}",
        }
