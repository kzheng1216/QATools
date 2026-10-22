#!/usr/bin/env python3
import os
import sys

# QATools Root
QATOOLS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if QATOOLS_ROOT not in sys.path:
    sys.path.insert(0, QATOOLS_ROOT)

# RUNCASE Suite Name Prefix
SUITE_NAME_PREFIX = "[Zen]_"

####################################################################################
# - Config
####################################################################################
# QA Hub
QAHUB_TOKEN = "4cfd27273c0ad5e7d3b2fa60e2729f59e760ddcd"

# Testrail
EMAIL = "yuzheng@roku.com"
TESTRAIL_USERNAME = "TestrailToken0820"
TESTRAIL_API_KEY = "6Z5wvi91Kjc6M8fTbT4g-07d97HGTKt5gEmtlXsdE"

# JIRA
JIRA_TOKEN = "ATATT3xFfGF0bMRM_3yUYEmW29I8428CqHz3lKscJ0OVQS5IQ97zQ-PTCGnk09UoDLOAJ6a3QoN8O9HLX_VyaERdzte9_zAhRVhPDUVmi35idm075tWk1bx664U_D2K2YDSBoEdJejUnCpTgBN1hc8fAXpt4Nkt7_13xRiV-7g0QKeUuZZgwK9g=E2CC6E05"

# Data Directory
DATA_BASE_DIR = "data"

# roku_test log directory
ROKU_TEST_LOG_DIR = "roku_test_log"

# Automated Tests Directory
AUTOMATED_TESTS_RELATIVE_DIR = "../../automated_tests"

# Apply user overrides (editable via Settings -> Account Settings), stored in
# config/account.json. Only the keys below are overridable; a missing file or key
# leaves the default above untouched.
ACCOUNT_OVERRIDE_PATH = os.path.join(QATOOLS_ROOT, "config", "account.json")
ACCOUNT_KEYS = (
    "QAHUB_TOKEN",
    "EMAIL",
    "TESTRAIL_USERNAME",
    "TESTRAIL_API_KEY",
    "JIRA_TOKEN",
    "DATA_BASE_DIR",
    "ROKU_TEST_LOG_DIR",
    "AUTOMATED_TESTS_RELATIVE_DIR",
)
try:
    import json as _json

    if os.path.isfile(ACCOUNT_OVERRIDE_PATH):
        with open(ACCOUNT_OVERRIDE_PATH, encoding="utf-8") as _f:
            _overrides = _json.load(_f) or {}
        for _k in ACCOUNT_KEYS:
            _v = _overrides.get(_k)
            if isinstance(_v, str) and _v != "":
                globals()[_k] = _v
except Exception:  # noqa: BLE001 - never let a bad override file break startup
    pass

####################################################################################
# - Constants
####################################################################################
# - Automated Tests Directory
AUTOMATED_TESTS_DIR = os.path.join(QATOOLS_ROOT, AUTOMATED_TESTS_RELATIVE_DIR)

# - QA Hub
QAHUB_BASE_URL = "https://qahub.eswat.rokulabs.net"
QAHUB_URL = f"{QAHUB_BASE_URL}/api/v1"
QAHUB_HEADERS = {"Authorization": f"Token {QAHUB_TOKEN}", "Accept": "application/json"}
QAHUB_LOGS_SUITE_URL = f"{QAHUB_BASE_URL}/tests/suite/logs/"

# - Testrail
TESTRAIL_URL = "https://testrail.eswat.roku.com/testrail/"

# - Jenkins
JENKINS_JOB_URL = "https://jenkins.eswat.rokulabs.net/job/qa_hub_launch_suite"
JENKINS_TREE = "building,result"

# - JIRA
JIRA_URL = "https://roku.atlassian.net"

# - Data Directories
DATA_DIR = os.path.join(QATOOLS_ROOT, DATA_BASE_DIR)

REPORT_DIR = "runcase_report"
TESTRAIL_DATA_DIR = "testrail_data"
CASE_CACHE_DIR = "runcase_report"
ANALYZER_DIR = "analyzer_history"
AGENT_SESSION_DIR = "agent_session"
SKILL_DATA_DIR = "skill_data"
DOCS_DATA_DIR = "docs"
FILE_TRANSFER_DIR = "file_transfer"

REPORT_PATH = os.path.join(DATA_DIR, REPORT_DIR)
TESTRAIL_DATA_PATH = os.path.join(DATA_DIR, TESTRAIL_DATA_DIR)
CASE_CACHE_PATH = os.path.join(DATA_DIR, CASE_CACHE_DIR)
ANALYZER_PATH = os.path.join(DATA_DIR, ANALYZER_DIR)
AGENT_SESSION_PATH = os.path.join(DATA_DIR, AGENT_SESSION_DIR)
SKILL_DATA_PATH = os.path.join(DATA_DIR, SKILL_DATA_DIR)
DOCS_DATA_PATH = os.path.join(DATA_DIR, DOCS_DATA_DIR)
# Default root for the File Transfer tab (overridable via config.yml file_transfer.root).
FILE_TRANSFER_PATH = os.path.join(DATA_DIR, FILE_TRANSFER_DIR)

# Admin login credentials
ADMIN_AUTH_SALT = b"$2b$12$abcdefghijklmnopqrstuu"
ADMIN_USERNAME = "admin"
# Zaq1@wsx
ADMIN_HASHED_PASSWORD = "$2b$12$abcdefghijklmnopqrstuucPZfSaWgEdMsPKgHYz9gmkm0zJgflOu"
