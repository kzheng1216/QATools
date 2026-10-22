import os
import sys

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import DOCS_DATA_PATH, QATOOLS_ROOT

from . import logger

ref_conf_path = os.path.abspath(
    os.path.join(QATOOLS_ROOT, "backend", "conf", "ref.yml")
)

docs_dir = os.path.abspath(DOCS_DATA_PATH)
router = APIRouter()

_KINDS = ("ref", "docs")


class RefItem(BaseModel):
    kind: str = Field(..., description="Which list: 'ref' or 'docs'.")
    name: str = Field(..., description="Display name.")
    category: str = Field(default="", description="Category for grouping/filtering.")
    url: str = Field(..., description="Link (URL) or file path.")


class RefUpdate(RefItem):
    index: int = Field(..., description="0-based index of the item to update.")


class DocUpload(BaseModel):
    name: str = Field(..., description="File name, must end with .md")
    category: str = Field(default="", description="Category for grouping/filtering.")
    content: str = Field(..., description="Markdown file content (UTF-8 text).")


def _doc_file(name: str) -> str:
    # Guard against path traversal; docs live flat under docs_dir.
    if os.path.basename(name) != name or not name:
        raise HTTPException(status_code=400, detail=f"Invalid document name '{name}'")
    if not name.lower().endswith(".md"):
        raise HTTPException(
            status_code=400, detail="Only .md (Markdown) files are supported"
        )
    return os.path.join(docs_dir, name)


def _check_kind(kind: str) -> None:
    if kind not in _KINDS:
        raise HTTPException(
            status_code=400, detail=f"Invalid kind '{kind}' (expected 'ref' or 'docs')"
        )


def _load() -> dict:
    if not os.path.isfile(ref_conf_path):
        return {"ref": [], "docs": []}
    try:
        with open(ref_conf_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.error("Error reading ref.yml: %s", exc)
        raise HTTPException(status_code=500, detail="Error reading ref.yml") from exc
    # Normalize: ensure both lists exist.
    for k in _KINDS:
        if not isinstance(data.get(k), list):
            data[k] = []
    return data


def _save(data: dict) -> None:
    try:
        with open(ref_conf_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {k: data.get(k, []) for k in _KINDS},
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
    except OSError as exc:
        logger.error("Error writing ref.yml: %s", exc)
        raise HTTPException(status_code=500, detail="Error writing ref.yml") from exc


def _categories(items: list[dict]) -> list[str]:
    return sorted(
        {(it.get("category") or "").strip() for it in items if it.get("category")}
    )


@router.get("/v1/reference/list")
def list_reference() -> dict:
    """Return both lists (each item tagged with its index) plus their categories."""
    logger.info("List reference from: %s", ref_conf_path)
    data = _load()
    out: dict = {}
    for k in _KINDS:
        items = data.get(k, [])
        out[k] = [
            {
                "index": i,
                "name": it.get("name", ""),
                "category": it.get("category", ""),
                "url": it.get("url", ""),
            }
            for i, it in enumerate(items)
        ]
        out[f"{k}_categories"] = _categories(items)
    return out


@router.post("/v1/reference/add")
def add_reference(item: RefItem) -> dict:
    """Append a new item to the ref or docs list."""
    _check_kind(item.kind)
    logger.info("Add reference (%s): %s", item.kind, item.name)
    data = _load()
    data[item.kind].append(
        {"name": item.name, "category": item.category, "url": item.url}
    )
    _save(data)
    return {"message": f"{item.kind} '{item.name}' added successfully"}


@router.put("/v1/reference/update")
def update_reference(item: RefUpdate) -> dict:
    """Overwrite the item at the given index."""
    _check_kind(item.kind)
    logger.info("Update reference (%s) #%d: %s", item.kind, item.index, item.name)
    data = _load()
    lst = data[item.kind]
    if item.index < 0 or item.index >= len(lst):
        raise HTTPException(
            status_code=404, detail=f"{item.kind} index {item.index} out of range"
        )
    lst[item.index] = {"name": item.name, "category": item.category, "url": item.url}
    _save(data)
    return {"message": f"{item.kind} '{item.name}' updated successfully"}


@router.delete("/v1/reference/delete")
def delete_reference(kind: str, index: int) -> dict:
    """Delete the item at the given index from the ref or docs list."""
    _check_kind(kind)
    logger.info("Delete reference (%s) #%d", kind, index)
    data = _load()
    lst = data[kind]
    if index < 0 or index >= len(lst):
        raise HTTPException(
            status_code=404, detail=f"{kind} index {index} out of range"
        )
    removed = lst.pop(index)
    _save(data)
    return {"message": f"{kind} '{removed.get('name', '')}' deleted successfully"}


@router.post("/v1/reference/doc/upload")
def upload_doc(doc: DocUpload) -> dict:
    """Save a Markdown file under docs/ and add/refresh its docs-list record."""
    path = _doc_file(doc.name)
    logger.info("Upload doc: %s", doc.name)
    try:
        os.makedirs(docs_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(doc.content)
    except OSError as exc:
        logger.error("Error writing document '%s': %s", doc.name, exc)
        raise HTTPException(
            status_code=500, detail=f"Error writing document '{doc.name}'"
        ) from exc

    url = f"docs/{doc.name}"
    data = _load()
    docs = data["docs"]
    for it in docs:
        if it.get("name") == doc.name:
            it["category"] = doc.category
            it["url"] = url
            break
    else:
        docs.append({"name": doc.name, "category": doc.category, "url": url})
    _save(data)
    return {"message": f"document '{doc.name}' uploaded successfully"}


@router.get("/v1/reference/doc/content")
def get_doc_content(name: str) -> dict:
    """Return a Markdown document's text for the View dialog."""
    path = _doc_file(name)
    logger.info("View doc: %s", name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Document '{name}' not found")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as exc:
        logger.error("Error reading document '%s': %s", name, exc)
        raise HTTPException(
            status_code=500, detail=f"Error reading document '{name}'"
        ) from exc
    return {"name": name, "content": content}


if __name__ == "__main__":
    list_reference()
