"""Launch one BDD case in QA Hub and upload results to a TestRail plan."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "common"))
from common.base_runner import BaseRunner
from common.profile_parse import create_execution_with_profile


class Runner(BaseRunner):
    def __init__(self, param_profile_name=None, param_select=None):
        self.param_profile_name = param_profile_name
        self.param_select = param_select

    def run(self):

        profile_name = "p2"

        profile = self.param_profile_name or profile_name
        create_execution_with_profile(profile).execute(self.param_select)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Launch BDD case and upload results to TestRail"
    )
    parser.add_argument(
        "-p", "--profile", type=str, help="Profile name or path to profile JSON file"
    )
    parser.add_argument(
        "-s",
        "--select",
        default="All",
        type=str,
        help="select case (e.g., All, Fail, Pass, Skipped, Blocked, NA, Unknown, NoTest)",
    )

    args = parser.parse_args()

    raise SystemExit(Runner(args.profile, args.select).run())
