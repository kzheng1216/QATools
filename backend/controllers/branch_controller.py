import os
import shlex
import sys

from fastapi import APIRouter, HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import AUTOMATED_TESTS_DIR

from . import logger

automated_tests_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), AUTOMATED_TESTS_DIR)
)
router = APIRouter()


@router.get("/v1/branch/automated_tests/list")
def automated_tests_list_branch() -> dict:
    """
    List all git branches of the automated_tests repository.
    """
    try:
        logger.info("List git branches in: %s", automated_tests_dir)
        branches = os.popen(f"git -C {automated_tests_dir} branch").read().strip()
        branches = branches.replace("*", "").replace(
            " ", ""
        )  # Remove the '*' from the current branch
        return {"automated_tests_branches": branches.splitlines()}
    except Exception as exc:
        logger.error("Error listing git branches: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"Error listing git branches: {exc}"
        ) from exc


@router.get("/v1/branch/automated_tests/current")
def automated_tests_current() -> dict:
    """
    Get the current git branch of the automated_tests repository.
    """
    try:
        logger.info("Get current git branch in: %s", automated_tests_dir)
        branch = (
            os.popen(f"git -C {automated_tests_dir} rev-parse --abbrev-ref HEAD")
            .read()
            .strip()
        )
        return {"automated_tests_branch": branch}
    except Exception as exc:
        logger.error("Error getting git branch: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"Error getting git branch: {exc}"
        ) from exc


@router.post("/v1/branch/automated_tests/checkout")
def automated_tests_checkout(device_data: dict) -> dict:
    """
    Checkout a specific git branch of the automated_tests repository.
    """
    branch_name = device_data.get("branch_name")
    try:
        logger.info("Checkout git branch '%s' in: %s", branch_name, automated_tests_dir)
        command = f"git -C {automated_tests_dir} checkout {shlex.quote(branch_name)}"
        os.popen(command).read().strip()
        logger.info("Checked out git branch '%s'", branch_name)
        return {"checkout_result": "success"}
    except Exception as exc:
        logger.error("Error checking out git branch '%s': %s", branch_name, exc)
        raise HTTPException(
            status_code=500, detail=f"Error checking out git branch: {exc}"
        ) from exc


if __name__ == "__main__":
    print()
