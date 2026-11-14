import os
import shlex
import sys

from fastapi import APIRouter, HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import AUTOMATED_TESTS_RELATIVE_DIR, QATOOLS_ROOT

from . import logger


def _running_runs() -> list[dict]:
    """Cases running right now (imported lazily to avoid a circular import)."""
    try:
        from .roku_test_controller import list_running_runs

        return list_running_runs()
    except Exception:  # noqa: BLE001
        # Never block a checkout because the run tracker is unreadable.
        logger.exception("Could not determine running roku_test cases")
        return []

automated_tests_dir = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        os.path.join(QATOOLS_ROOT, AUTOMATED_TESTS_RELATIVE_DIR),
    )
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


@router.get("/v1/branch/automated_tests/lock")
def automated_tests_branch_lock() -> dict:
    """Whether switching branch is currently blocked, and why.

    Every local run executes the tests out of this one shared automated_tests
    working tree, so checking out another branch mid-run would swap the files
    under a live test. Queued cases do NOT block (they have not read anything
    yet) — they will simply run on whatever branch is checked out when started.
    """
    running = _running_runs()
    return {
        "locked": bool(running),
        "running": running,
        "reason": (
            f"{len(running)} case(s) running: "
            + ", ".join(f"{r['automation_id']} on {r['device']}" for r in running)
            if running
            else ""
        ),
    }


@router.post("/v1/branch/automated_tests/checkout")
def automated_tests_checkout(device_data: dict) -> dict:
    """
    Checkout a specific git branch of the automated_tests repository.

    Refused with 409 while any local case is running: the run reads its test
    files from this shared working tree, so switching the branch underneath it
    would corrupt the run.
    """
    branch_name = device_data.get("branch_name")
    running = _running_runs()
    if running:
        detail = (
            "Cannot switch branch while a case is running: "
            + ", ".join(f"{r['automation_id']} on {r['device']}" for r in running)
            + ". Wait for it to finish or stop it first."
        )
        logger.warning(
            "Refused branch checkout to '%s': %s run(s) in progress",
            branch_name,
            len(running),
        )
        raise HTTPException(status_code=409, detail=detail)
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
