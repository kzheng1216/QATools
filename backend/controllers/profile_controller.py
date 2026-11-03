import json
import os
import sys

from fastapi import APIRouter, HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import QATOOLS_ROOT, TESTRAIL_DATA_PATH

from . import logger

profile_conf_dir = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), os.path.join(QATOOLS_ROOT, "4_runcase", "profiles")
    )
)

testrail_data_dir = os.path.abspath(TESTRAIL_DATA_PATH)
router = APIRouter()


@router.get("/v1/profile/list")
def list_profiles() -> dict[str, list[str]]:
    """List the available profile configuration files."""
    logger.info("List profiles from: %s", profile_conf_dir)
    try:
        os.makedirs(profile_conf_dir, exist_ok=True)
        files = [f for f in os.listdir(profile_conf_dir) if f.endswith(".json")]
    except OSError as exc:
        logger.error("Profile configuration directory not accessible: %s", exc)
        raise HTTPException(
            status_code=500, detail="Profile configuration directory not accessible"
        ) from exc

    return {"profiles": files}


@router.get("/v1/profile/list_details")
def list_profile_details() -> dict:
    """List profiles with the summary fields shown by the Profile table.

    For each profile file report:
        description      -> "description"
        total_tasks      -> len("tasks")
        execution_mode   -> "execution_mode"

    A profile that fails to parse still appears, with empty/zero values.
    """
    logger.info("List profile details from: %s", profile_conf_dir)
    try:
        os.makedirs(profile_conf_dir, exist_ok=True)
        files = sorted(f for f in os.listdir(profile_conf_dir) if f.endswith(".json"))
    except OSError as exc:
        logger.error("Profile configuration directory not accessible: %s", exc)
        raise HTTPException(
            status_code=500, detail="Profile configuration directory not accessible"
        ) from exc

    profiles = []
    for fname in files:
        name = fname[: -len(".json")]
        data: dict = {}
        try:
            with open(os.path.join(profile_conf_dir, fname), encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError) as exc:
            logger.warning("Could not parse profile '%s': %s", name, exc)

        tasks = data.get("tasks")
        profiles.append(
            {
                "name": name,
                "description": str(data.get("description") or ""),
                "total_tasks": len(tasks) if isinstance(tasks, list) else 0,
                "execution_mode": str(data.get("execution_mode") or ""),
            }
        )
    return {"profiles": profiles}


def _get_profile_template(plan: str, device: str) -> dict:
    """Generate a profile template for a given device and automation id."""
    return {
        "name": f"{device}_{plan}",
        "description": "",
        "tasks": [],
        "execution_mode": "SERIAL",
    }


@router.get("/v1/profile/generate_with_testrail_data")
def generate_profile_with_testrail_data(
    plan: str, device: str, testrail_data_file: str
) -> dict:
    """Generate a profile from a TestRail data file (<plan>_<status>.json)."""
    logger.info(
        "Generate profile: plan=%s device=%s testrail_data_file=%s",
        plan,
        device,
        testrail_data_file,
    )

    try:
        plan_id = int(plan)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"'plan' must be an integer, got '{plan}'"
        ) from exc

    # Guard against path traversal via the file name.
    if os.path.basename(testrail_data_file) != testrail_data_file:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid testrail data file name '{testrail_data_file}'",
        )

    testrail_data_path = os.path.join(testrail_data_dir, testrail_data_file)
    if not os.path.isfile(testrail_data_path):
        raise HTTPException(
            status_code=404,
            detail=f"TestRail data file '{testrail_data_file}' not found",
        )

    try:
        with open(testrail_data_path, encoding="utf-8") as f:
            testrail_data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Error reading testrail data '%s': %s", testrail_data_file, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error reading testrail data file '{testrail_data_file}'",
        ) from exc

    profile_data = _get_profile_template(plan, device)
    for case in testrail_data.get("cases") or []:
        automation_id = case.get("automation_id")
        if not automation_id:
            logger.warning("Skipping case without automation_id: %s", case.get("id"))
            continue

        is_bdd = automation_id.startswith("bdd-")
        profile_data["tasks"].append(
            {
                "config": {
                    "case_type": "BDD" if is_bdd else "UT",
                    "case_id": automation_id.split("-")[1]
                    if is_bdd
                    else automation_id,
                    "testrail_case_id": case.get("case_id"),
                    "device": device,
                    "testrail_plan_id": plan_id,
                    "repeat": 0,
                    "automation_test_branch": "main",
                    "roku_automation_branch": "main",
                },
                "timeout": 360000,
            },
        )

    base_name = testrail_data_file.removesuffix(".json")
    profile_name = f"profile_{base_name}_{device}"
    add_profile(profile_name, profile_data)
    return {"message": f"Profile '{profile_name}' generated successfully"}


@router.get("/v1/profile/{profile_name}")
def view_profile(profile_name: str) -> dict:
    """View the contents of a specific profile configuration file."""
    logger.info("View profile: %s", profile_name)

    profile_file_path = os.path.join(profile_conf_dir, f"{profile_name}.json")

    if not os.path.isfile(profile_file_path):
        logger.warning("Profile configuration '%s' not found", profile_name)
        raise HTTPException(
            status_code=404, detail=f"Profile configuration '{profile_name}' not found"
        )

    try:
        with open(profile_file_path, "r") as f:
            profile_data = f.read()
    except OSError as exc:
        logger.error("Error reading profile '%s': %s", profile_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error reading profile configuration '{profile_name}'",
        ) from exc

    return json.loads(profile_data)


@router.patch("/v1/profile/update/{profile_name}")
def update_profile(profile_name: str, profile_data: dict) -> dict:
    """Update an existing profile configuration file."""
    logger.info("Update profile: %s", profile_name)

    profile_file_path = os.path.join(profile_conf_dir, f"{profile_name}.json")

    if not os.path.isfile(profile_file_path):
        logger.warning("Profile configuration '%s' not found", profile_name)
        raise HTTPException(
            status_code=404, detail=f"Profile configuration '{profile_name}' not found"
        )

    try:
        with open(profile_file_path, "w") as f:
            json.dump(profile_data, f, indent=4)
    except OSError as exc:
        logger.error("Error updating profile '%s': %s", profile_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error updating profile configuration '{profile_name}'",
        ) from exc

    logger.info("Profile configuration '%s' updated", profile_name)
    return {"message": f"Profile configuration '{profile_name}' updated successfully"}


@router.post("/v1/profile/add/{profile_name}")
def add_profile(profile_name: str, profile_data: dict) -> dict:
    """Add a new profile configuration file."""
    logger.info("Add profile: %s", profile_name)

    profile_file_path = os.path.join(profile_conf_dir, f"{profile_name}.json")

    if os.path.isfile(profile_file_path):
        logger.warning("Profile configuration '%s' already exists", profile_name)
        raise HTTPException(
            status_code=400,
            detail=f"Profile configuration '{profile_name}' already exists",
        )

    try:
        with open(profile_file_path, "w") as f:
            json.dump(profile_data, f, indent=4)
    except OSError as exc:
        logger.error("Error adding profile '%s': %s", profile_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error adding profile configuration '{profile_name}'",
        ) from exc

    logger.info("Profile configuration '%s' added", profile_name)
    return {"message": f"Profile configuration '{profile_name}' added successfully"}


@router.delete("/v1/profile/delete/{profile_name}")
def delete_profile(profile_name: str) -> dict:
    """Delete an existing profile configuration file."""
    logger.info("Delete profile: %s", profile_name)

    profile_file_path = os.path.join(profile_conf_dir, f"{profile_name}.json")

    if not os.path.isfile(profile_file_path):
        logger.warning("Profile configuration '%s' not found", profile_name)
        raise HTTPException(
            status_code=404, detail=f"Profile configuration '{profile_name}' not found"
        )

    try:
        os.remove(profile_file_path)
    except OSError as exc:
        logger.error("Error deleting profile '%s': %s", profile_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting profile configuration '{profile_name}'",
        ) from exc

    logger.info("Profile configuration '%s' deleted", profile_name)
    return {"message": f"Profile configuration '{profile_name}' deleted successfully"}
