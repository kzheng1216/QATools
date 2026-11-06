import asyncio
import json
import os
import re
import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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

SPLIT_PROMPT_PLACEHOLDERS = ("{devices}", "{cases}")
DEFAULT_SPLIT_PROMPT = """You are assigning Roku automated test cases to test devices.
For EACH case decide which of the candidate devices satisfy the case's
execution conditions. Compare the case's preconditions / steps / mode-account
status / region / required equipment with each device's peripherals (QA Bot,
Maxwell, STB, Power, AVR, HDMI inputs, tuner) and Roku info (Account Type =
region, Linked = connected/unconnected mode, Connection Type = wifi/ethernet,
form factor, 4K, tuner types, ...).

Rules:
- A device is compatible only if nothing in the case conditions rules it out.
- "Connected Mode / Linked" requires Linked=True; "Unconnected Mode / Unlinked"
    requires Linked=False; "Connected Mode & Unconnected Mode" accepts either.
- Region requirements must match the device Account Type / Model Region
    (UK == GB). "Global" accepts any region.
- If a case needs equipment (e.g. Maxwell, an STB on HDMI, AVR, a signal
    generator) the device must have it.
- If no condition can be determined, every device is compatible.
- Do NOT balance load; only judge compatibility.

Return ONLY a JSON object, no prose, no code fence:
{"cases": [{"key": "<case key>", "compatible": ["<device>", ...],
            "reason": "<= 20 words"}]}

CANDIDATE DEVICES:
{devices}

CASES:
{cases}
"""


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


# Mirrors TestCategory.SingleCase in 4_runcase/common/launch_qahub_testcase.py
# ("file-system" = run this one case; "testrail" = run the whole plan).
TEST_SOURCE_SINGLE_CASE = "file-system"

# Keys the UI no longer exposes. They are dropped from every profile written
# through this API, so profile_parse.py falls back to its own defaults.
DROPPED_TASK_KEYS = ("execution_mode", "stop_if_success", "print_console_message")
DROPPED_CONFIG_KEYS = ("test_source",)


def _strip_dropped_task_keys(profile_data: dict) -> dict:
    """Return the profile without the keys this tool doesn't manage."""
    if not isinstance(profile_data, dict):
        return profile_data

    cleaned = dict(profile_data)

    tasks = cleaned.get("tasks")
    if not isinstance(tasks, list):
        return cleaned

    cleaned_tasks = []
    for task in tasks:
        if isinstance(task, dict):
            task = {k: v for k, v in task.items() if k not in DROPPED_TASK_KEYS}
            config = task.get("config")
            if isinstance(config, dict):
                task["config"] = {
                    k: v for k, v in config.items() if k not in DROPPED_CONFIG_KEYS
                }
        cleaned_tasks.append(task)

    cleaned["tasks"] = cleaned_tasks
    return cleaned


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
                    "case_id": automation_id.split("-")[1] if is_bdd else automation_id,
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
            json.dump(_strip_dropped_task_keys(profile_data), f, indent=4)
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
            json.dump(_strip_dropped_task_keys(profile_data), f, indent=4)
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


# ===========================================================================
# Split a profile across several devices (AI-assisted case -> device matching)
# ===========================================================================

_ROKU_INFO_KEYS = (
    "Account Type",
    "Linked",
    "Connection Type",
    "Model Region",
    "Locale",
    "Form Factor",
    "Device Type",
    "Platform Name",
    "Brand Name",
    "Model",
    "Software Major Version",
    "Num HDMI Inputs",
    "Supports 4k",
    "Supports 8k",
    "Supports ATSC",
    "Supported Tuner Types",
    "Supports Bluetooth",
    "Is Soundbar",
    "Headless",
    "Supported Power Regulation",
    "Freeview Certified",
    "Image Type",
)

# TestRail case fields that describe execution conditions. Dropdown /
# multi-select ids are resolved to labels via get_case_fields.
_CASE_TEXT_FIELDS = ("custom_preconds", "custom_testobjective", "custom_steps")
_CASE_LABEL_FIELDS = (
    "custom_mode_account_status",
    "custom_region",
    "custom_product_area",
    "custom_functionality",
)
_CASE_TEXT_LIMIT = 900  # chars per text field sent to the model
_AI_BATCH_SIZE = 10  # cases per AI request
_AI_CONCURRENCY = 3
_TESTRAIL_CONCURRENCY = 8

_case_field_labels: dict[str, dict[str, str]] | None = None


class SplitProfileRequest(BaseModel):
    devices: list[str] = Field(..., description="Selected device names (ordered).")


def _write_new_split_profile(
    profile_name: str, data: dict, start: int
) -> tuple[str, int]:
    """Write `data` as `<profile_name>__<nnn>` (e.g. p_01__001) using the first free n >= start.

    Never overwrites: the file is opened with mode "x" (exclusive create), so
    an existing profile -- including one created concurrently -- is skipped
    and the next number is tried. Returns (new profile name, n used).
    """
    n = start
    while True:
        name = f"{profile_name}__{n:03d}"
        path = os.path.join(profile_conf_dir, f"{name}.json")
        try:
            with open(path, "x") as f:
                json.dump(_strip_dropped_task_keys(data), f, indent=4)
            return name, n
        except FileExistsError:
            n += 1


def _device_summary(device: str) -> dict:
    """Matching-relevant facts about a device (no credentials)."""
    from .device_controller import device_conf_dir, view_device_info

    path = os.path.join(device_conf_dir, f"{device}.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Device '{device}' not found")
    with open(path, encoding="utf-8") as f:
        roku = (json.load(f) or {}).get("roku") or {}

    devices_config = roku.get("devices_config") or {}
    if not isinstance(devices_config, dict):
        devices_config = {}

    def _hdmi(port: str) -> str | None:
        entry = devices_config.get(port)
        if not isinstance(entry, dict):
            return None
        return entry.get("device_type") or "connected"

    peripherals = {
        "QA Bot": "qa_bot_config" in roku,
        "Maxwell": "maxwell_config" in roku,
        "STB": any(
            isinstance(v, dict) and v.get("device_type") == "ROKU"
            for v in devices_config.values()
        ),
        "Power": "power_config" in roku,
        "AVR": "avr_info_config" in roku,
        "HDMI1": _hdmi("HDMI 1"),
        "HDMI2": _hdmi("HDMI 2"),
        "HDMI3": _hdmi("HDMI 3"),
        "Tuner input": bool(roku.get("tuner_input_config")),
    }

    roku_info: dict = {}
    try:
        info = view_device_info(device) or {}
        roku_info = {k: info[k] for k in _ROKU_INFO_KEYS if k in info}
    except Exception as exc:  # noqa: BLE001 - info is best-effort
        logger.warning("Split: no Roku info for '%s': %s", device, exc)

    return {"device": device, "peripherals": peripherals, "roku_info": roku_info}


def _load_case_field_labels() -> dict[str, dict[str, str]]:
    """{system_name: {option_id: label}} for dropdown/multi-select fields."""
    global _case_field_labels
    if _case_field_labels is not None:
        return _case_field_labels
    from .testrail_controller import _tr_get

    labels: dict[str, dict[str, str]] = {}
    try:
        for field in _tr_get("get_case_fields") or []:
            name = field.get("system_name")
            if name not in _CASE_LABEL_FIELDS:
                continue
            options: dict[str, str] = {}
            for cfg in field.get("configs") or []:
                items = ((cfg or {}).get("options") or {}).get("items") or ""
                for line in str(items).splitlines():
                    if "," in line:
                        key, _, label = line.partition(",")
                        options[key.strip()] = label.strip()
            labels[name] = options
    except Exception as exc:  # noqa: BLE001
        logger.warning("Split: could not load TestRail case fields: %s", exc)
    _case_field_labels = labels
    return labels


def _case_conditions(testrail_case_id) -> dict:
    """Execution conditions of a TestRail case (empty dict if unavailable)."""
    from .testrail_controller import _tr_get

    if not str(testrail_case_id or "").strip().isdigit():
        return {}
    try:
        case = _tr_get(f"get_case/{testrail_case_id}") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Split: TestRail case %s unavailable: %s", testrail_case_id, exc)
        return {}

    labels = _load_case_field_labels()
    out: dict = {"title": case.get("title", "")}
    for key in _CASE_TEXT_FIELDS:
        text = str(case.get(key) or "").strip()
        if text:
            out[key.removeprefix("custom_")] = text[:_CASE_TEXT_LIMIT]
    for key in _CASE_LABEL_FIELDS:
        raw = case.get(key)
        if raw in (None, "", []):
            continue
        ids = raw if isinstance(raw, list) else [raw]
        names = [labels.get(key, {}).get(str(i), str(i)) for i in ids]
        names = [n for n in names if n and n.lower() not in ("none", "not applicable")]
        if names:
            out[key.removeprefix("custom_")] = names
    return out


def _split_prompt_template() -> str:
    """The configured Split prompt, falling back to the built-in default."""
    try:
        from conf import config as config_module

        template = (config_module.read_section("analyze_config") or {}).get(
            "split_prompt_template"
        ) or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("Split: cannot read split prompt config: %s", exc)
        template = ""

    if not template.strip():
        return DEFAULT_SPLIT_PROMPT
    missing = [p for p in SPLIT_PROMPT_PLACEHOLDERS if p not in template]
    if missing:
        logger.warning(
            "Split: configured prompt lacks %s; using built-in default", missing
        )
        return DEFAULT_SPLIT_PROMPT
    return template


def _extract_json(text: str) -> dict:
    """Parse the model reply, tolerating code fences or surrounding prose."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


async def _ai_compatibility(
    batch: list[dict],
    devices: list[dict],
    sem: asyncio.Semaphore,
    template: str,
) -> dict[str, dict]:
    """{case_key: {"compatible": [...], "reason": str}} for one batch."""
    from .agent_controller import _get_service

    names = [d["device"] for d in devices]
    prompt = template.replace(
        "{devices}", json.dumps(devices, ensure_ascii=False, indent=1)
    ).replace("{cases}", json.dumps(batch, ensure_ascii=False, indent=1))

    async with sem:
        reply = await _get_service().chat(prompt, use_internal=False)

    parsed = _extract_json(reply)
    result: dict[str, dict] = {}
    for item in parsed.get("cases") or []:
        key = str(item.get("key", ""))
        # Keep only real candidate names, in selection order.
        compatible = [n for n in names if n in (item.get("compatible") or [])]
        result[key] = {"compatible": compatible, "reason": str(item.get("reason", ""))}
    return result


def _balance(cases: list[dict], device_names: list[str]) -> dict[str, str]:
    """Assign every case to exactly one device, keeping totals even."""
    load = {d: 0 for d in device_names}
    assignment: dict[str, str] = {}

    for case in cases:
        if not case["compatible"]:
            assignment[case["key"]] = device_names[0]
            load[device_names[0]] += 1

    flexible = [c for c in cases if c["compatible"]]
    flexible.sort(key=lambda c: len(c["compatible"]))  # stable: keeps order
    for case in flexible:
        target = min(case["compatible"], key=lambda d: (load[d], device_names.index(d)))
        assignment[case["key"]] = target
        load[target] += 1
    return assignment


@router.post("/v1/profile/split/{profile_name}")
async def split_profile(profile_name: str, req: SplitProfileRequest) -> dict:
    """Split a profile's cases across the selected devices"""
    device_names = list(dict.fromkeys(d.strip() for d in req.devices if d.strip()))
    if not device_names:
        raise HTTPException(status_code=400, detail="Select at least one device")

    profile = view_profile(profile_name)
    tasks = profile.get("tasks") or []
    if not tasks:
        raise HTTPException(status_code=400, detail="Profile has no tasks to split")

    logger.info("Split profile '%s' across %s", profile_name, device_names)

    devices = await asyncio.gather(
        *(asyncio.to_thread(_device_summary, d) for d in device_names)
    )

    tr_sem = asyncio.Semaphore(_TESTRAIL_CONCURRENCY)

    async def _conditions(tid):
        async with tr_sem:
            return await asyncio.to_thread(_case_conditions, tid)

    await asyncio.to_thread(_load_case_field_labels)  # warm the label cache once
    cases: list[dict] = []
    for i, task in enumerate(tasks):
        cfg = (task or {}).get("config") or {}
        cases.append(
            {
                "key": str(i),
                "case_id": str(cfg.get("case_id", "")),
                "case_type": cfg.get("case_type", ""),
                "testrail_case_id": cfg.get("testrail_case_id", ""),
            }
        )
    conditions = await asyncio.gather(
        *(_conditions(c["testrail_case_id"]) for c in cases)
    )
    for case, cond in zip(cases, conditions):
        case["conditions"] = cond

    ai_sem = asyncio.Semaphore(_AI_CONCURRENCY)
    template = _split_prompt_template()
    batches = [
        cases[i : i + _AI_BATCH_SIZE] for i in range(0, len(cases), _AI_BATCH_SIZE)
    ]
    results = await asyncio.gather(
        *(_ai_compatibility(b, devices, ai_sem, template) for b in batches),
        return_exceptions=True,
    )
    verdicts: dict[str, dict] = {}
    for batch, res in zip(batches, results):
        if isinstance(res, BaseException):
            detail = getattr(res, "detail", None) or res
            logger.error("Split: AI batch failed: %s", detail)
            # Unknown -> treat as compatible everywhere, and say so.
            for c in batch:
                verdicts[c["key"]] = {
                    "compatible": list(device_names),
                    "reason": f"AI analysis failed ({type(res).__name__}); "
                    "treated as compatible with all devices",
                    "ai_failed": True,
                }
        else:
            verdicts.update(res)

    for case in cases:
        v = verdicts.get(case["key"]) or {
            "compatible": list(device_names),
            "reason": "No AI verdict; treated as compatible with all devices",
            "ai_failed": True,
        }
        case["compatible"] = v["compatible"]
        case["reason"] = v["reason"]
        case["ai_failed"] = bool(v.get("ai_failed"))

    assignment = _balance(cases, device_names)

    written: list[dict] = []
    next_n = 1
    for device in device_names:
        dev_tasks = []
        for case, task in zip(cases, tasks):
            if assignment[case["key"]] != device:
                continue
            new_task = json.loads(json.dumps(task))
            new_task.setdefault("config", {})["device"] = device
            dev_tasks.append(new_task)
        if not dev_tasks:
            continue
        new_profile = {
            **{k: v for k, v in profile.items() if k != "tasks"},
            "name": f"{profile.get('name') or profile_name} [{device}]",
            "description": (
                f"Split from '{profile_name}' for device '{device}'"
                + (f" - {profile['description']}" if profile.get("description") else "")
            ),
            "tasks": dev_tasks,
        }
        name, used = _write_new_split_profile(profile_name, new_profile, next_n)
        next_n = used + 1
        written.append({"device": device, "profile": name, "count": len(dev_tasks)})
        logger.info("Split: wrote '%s' (%d cases)", name, len(dev_tasks))

    return {
        "message": f"Split '{profile_name}' into {len(written)} profile(s)",
        "profiles": written,
        "assignments": [
            {
                "case_id": c["case_id"],
                "testrail_case_id": c["testrail_case_id"],
                "title": (c.get("conditions") or {}).get("title", ""),
                "device": assignment[c["key"]],
                "compatible": c["compatible"],
                "reason": c["reason"],
                "fallback": not c["compatible"],
                "ai_failed": c["ai_failed"],
            }
            for c in cases
        ],
    }
