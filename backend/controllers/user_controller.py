import os
import sys

import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import ADMIN_AUTH_SALT, ADMIN_HASHED_PASSWORD, ADMIN_USERNAME

router = APIRouter()


class AdminLoginBody(BaseModel):
    username: str = Field(..., description="Username.")
    password: str = Field(..., description="Password.")


@router.post("/v1/user/admin/login")
def admin_login(body: AdminLoginBody) -> dict:
    """Admin login."""
    hashed_password = bcrypt.hashpw(body.password.encode(), ADMIN_AUTH_SALT).decode()
    if body.username == ADMIN_USERNAME and hashed_password == ADMIN_HASHED_PASSWORD:
        return {"message": "SUCCESS"}
    else:
        raise HTTPException(status_code=401, detail="FAILURE")
