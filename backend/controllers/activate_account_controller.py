from __future__ import annotations

import os
import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import QATOOLS_ROOT

# Same data service layer as the backend/conf files (absolute path store).
from services.data_service import DataServiceError, get_store

from . import logger

_YAML_PATH = os.path.abspath(
    os.path.join(QATOOLS_ROOT, "config", "activate_account.yml")
)
_STORE = get_store(_YAML_PATH)
_SECTION = "activate_account"

router = APIRouter()

DEFAULT_KEY = "DEFAULT"


def _load() -> dict:
    """Load the country -> activation email mapping from activate_account.yml."""
    try:
        return _STORE.get_dict(_SECTION)
    except DataServiceError as exc:
        logger.error("%s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _save(accounts: dict) -> None:
    try:
        _STORE.set_section(_SECTION, accounts)
    except DataServiceError as exc:
        logger.error("%s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class ActivateAccountBody(BaseModel):
    country: str = Field(
        ..., description="Country code key, e.g. 'US', 'UK', or 'DEFAULT'."
    )
    email: str = Field(..., description="Activation account email for this country.")


class ActivateAccountUpdateBody(BaseModel):
    email: str = Field(..., description="New activation account email.")


@router.get("/v1/activate_account/list")
def list_activate_accounts() -> dict:
    """List all country -> activation email mappings from activate_account.yml."""
    accounts = _load()
    return {
        "accounts": [
            {"country": country, "email": email} for country, email in accounts.items()
        ]
    }


@router.get("/v1/activate_account/{country}")
def get_activate_account(country: str) -> dict:
    """Get a single country's activation account email."""
    accounts = _load()
    key = country.upper()
    if key not in accounts:
        raise HTTPException(
            status_code=404, detail=f"Activate account '{country}' not found"
        )
    return {"country": key, "email": accounts[key]}


@router.post("/v1/activate_account/add")
def add_activate_account(body: ActivateAccountBody) -> dict:
    """Add a new country -> activation email mapping. Fails if it already exists."""
    accounts = _load()
    key = body.country.upper()
    if key in accounts:
        raise HTTPException(
            status_code=400, detail=f"Activate account '{key}' already exists"
        )
    accounts[key] = body.email
    _save(accounts)
    logger.info("Activate account '%s' added", key)
    return {"message": f"Activate account '{key}' added successfully"}


@router.put("/v1/activate_account/update/{country}")
def update_activate_account(country: str, body: ActivateAccountUpdateBody) -> dict:
    """Update an existing country's activation email."""
    accounts = _load()
    key = country.upper()
    if key not in accounts:
        raise HTTPException(
            status_code=404, detail=f"Activate account '{country}' not found"
        )
    accounts[key] = body.email
    _save(accounts)
    logger.info("Activate account '%s' updated", key)
    return {"message": f"Activate account '{key}' updated successfully"}


@router.delete("/v1/activate_account/delete/{country}")
def delete_activate_account(country: str) -> dict:
    """Delete a country's activation account mapping.

    The 'DEFAULT' key is protected: device_info.py falls back to it when no
    country matches a device name, so it cannot be removed via this API.
    """
    key = country.upper()
    if key == DEFAULT_KEY:
        raise HTTPException(
            status_code=400,
            detail="'DEFAULT' is the fallback account and cannot be deleted",
        )
    accounts = _load()
    if key not in accounts:
        raise HTTPException(
            status_code=404, detail=f"Activate account '{country}' not found"
        )
    del accounts[key]
    _save(accounts)
    logger.info("Activate account '%s' deleted", key)
    return {"message": f"Activate account '{key}' deleted successfully"}
