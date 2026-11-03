import io
import os
import sys
import zipfile
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import SKILL_DATA_PATH
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from . import logger

skill_conf_dir = os.path.abspath(SKILL_DATA_PATH)
router = APIRouter()


class SkillBody(BaseModel):
    skill: str = Field(..., description="The Markdown content of the skill.")


def _skill_dir(skill_name: str) -> str:
    return os.path.join(skill_conf_dir, skill_name)


def _skill_file(skill_name: str) -> str:
    return os.path.join(_skill_dir(skill_name), "SKILL.md")


@router.get("/v1/skill/list")
def list_skills() -> dict[str, list[str]]:
    """List the available skill configuration directories."""
    logger.info("List skills from: %s", skill_conf_dir)

    try:
        skills = [
            name
            for name in os.listdir(skill_conf_dir)
            if os.path.isfile(_skill_file(name))
        ]
    except OSError:
        skills = []

    return {"skills": skills}


@router.get("/v1/skill/export/all")
def export_skills() -> Response:
    """Download the entire skill_data directory as a .zip.

    Declared before the dynamic /{skill_name} route so it is not shadowed.
    """
    logger.info("Export all skills from: %s", skill_conf_dir)
    buf = io.BytesIO()
    file_count = 0
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _dirs, files in os.walk(skill_conf_dir):
                for name in files:
                    full = os.path.join(dirpath, name)
                    # Store paths relative to skill_data/, under a top-level folder.
                    rel = os.path.relpath(full, skill_conf_dir)
                    zf.write(full, os.path.join("skill_data", rel))
                    file_count += 1
    except OSError as exc:
        logger.error("Error zipping skill_data: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"Error exporting skills: {exc}"
        ) from exc

    if file_count == 0:
        raise HTTPException(status_code=404, detail="No skills to export")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"skill_data_{ts}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/v1/skill/{skill_name}")
def view_skill(skill_name: str) -> dict:
    """View the contents of a specific skill configuration file."""
    logger.info("View skill: %s", skill_name)

    skill_file_path = _skill_file(skill_name)

    if not os.path.isfile(skill_file_path):
        logger.warning("Skill configuration '%s' not found", skill_name)
        raise HTTPException(
            status_code=404, detail=f"Skill configuration '{skill_name}' not found"
        )

    try:
        with open(skill_file_path, "r", encoding="utf-8") as f:
            skill_data = f.read()
    except OSError as exc:
        logger.error("Error reading skill '%s': %s", skill_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error reading skill configuration '{skill_name}'",
        ) from exc

    return {"skill": skill_data}


@router.post("/v1/skill/add/{skill_name}")
def add_skill(skill_name: str, body: SkillBody) -> dict:
    """Add a new skill: create <skill_name>/SKILL.md and write body into it."""
    logger.info("Add skill: %s", skill_name)

    skill_dir = _skill_dir(skill_name)
    skill_file_path = _skill_file(skill_name)

    if os.path.isfile(skill_file_path):
        logger.warning("Skill configuration '%s' already exists", skill_name)
        raise HTTPException(
            status_code=400,
            detail=f"Skill configuration '{skill_name}' already exists",
        )

    try:
        os.makedirs(skill_dir, exist_ok=True)
        with open(skill_file_path, "w", encoding="utf-8") as f:
            f.write(body.skill)
    except OSError as exc:
        logger.error("Error writing skill '%s': %s", skill_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error writing skill configuration '{skill_name}'",
        ) from exc

    logger.info("Skill configuration '%s' added", skill_name)
    return {"message": f"Skill configuration '{skill_name}' added successfully"}


@router.put("/v1/skill/update/{skill_name}")
def update_skill(skill_name: str, body: SkillBody) -> dict:
    """Update an existing skill: overwrite <skill_name>/SKILL.md with body."""
    logger.info("Update skill: %s", skill_name)

    skill_file_path = _skill_file(skill_name)

    if not os.path.isfile(skill_file_path):
        logger.warning("Skill configuration '%s' not found", skill_name)
        raise HTTPException(
            status_code=404, detail=f"Skill configuration '{skill_name}' not found"
        )

    try:
        with open(skill_file_path, "w", encoding="utf-8") as f:
            f.write(body.skill)
    except OSError as exc:
        logger.error("Error updating skill '%s': %s", skill_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error updating skill configuration '{skill_name}'",
        ) from exc

    logger.info("Skill configuration '%s' updated", skill_name)
    return {"message": f"Skill configuration '{skill_name}' updated successfully"}


@router.delete("/v1/skill/delete/{skill_name}")
def delete_skill(skill_name: str) -> dict:
    """Delete a specific skill directory (<skill_name>/SKILL.md)."""
    logger.info("Delete skill: %s", skill_name)

    skill_dir = _skill_dir(skill_name)
    skill_file_path = _skill_file(skill_name)

    if not os.path.isfile(skill_file_path):
        logger.warning("Skill configuration '%s' not found", skill_name)
        raise HTTPException(
            status_code=404, detail=f"Skill configuration '{skill_name}' not found"
        )

    try:
        os.remove(skill_file_path)
        os.rmdir(skill_dir)
    except OSError as exc:
        logger.error("Error deleting skill '%s': %s", skill_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting skill configuration '{skill_name}'",
        ) from exc

    logger.info("Skill configuration '%s' deleted", skill_name)
    return {"message": f"Skill configuration '{skill_name}' deleted successfully"}


if __name__ == "__main__":
    list_skills()
