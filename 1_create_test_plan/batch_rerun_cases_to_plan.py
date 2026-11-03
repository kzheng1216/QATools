import getpass
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import requests
from config.device_conf.device_info import PlanId
from config.env import EMAIL, TESTRAIL_API_KEY, TESTRAIL_URL
from const import (
    CASE_IDS_AU,
    CASE_IDS_EU,
    CASE_IDS_LATAM,
    CASE_IDS_NA,
    PLAN_ID_AU,
    PLAN_ID_EU,
    PLAN_ID_LATAM,
    PLAN_ID_NA,
    CASE_IDS_EU_New,
    CASE_IDS_Global,
    CASE_IDS_Global_New,
    PLAN_ID_Global,
)
from requests.auth import HTTPBasicAuth

# 配置
# 支持多个case IDs - 可以是列表或单个ID
PLAN_ID = PLAN_ID_EU
CASE_IDS = CASE_IDS_EU_New


def main():
    execute_imp()


def execute_imp():
    print("TestRail - Batch Re-run Cases to Plan")
    print("=" * 60)

    # 确保CASE_IDS是列表
    case_ids = CASE_IDS if isinstance(CASE_IDS, list) else [CASE_IDS]
    print(f"待添加的Case IDs: {case_ids}")
    print(f"目标Plan ID: {PLAN_ID}")

    # 获取用户凭据
    email = EMAIL
    api_key = TESTRAIL_API_KEY

    # 创建认证
    auth = HTTPBasicAuth(email, api_key)
    headers = {"Content-Type": "application/json"}

    # 1. 批量获取测试用例信息并按suite分组
    print(f"\n{'=' * 60}")
    print("步骤1: 获取测试用例信息并按Suite分组")
    print(f"{'=' * 60}")
    cases_by_suite = {}  # {suite_id: {'suite_name': name, 'case_ids': [...]}}

    for case_id in case_ids:
        case_url = f"{TESTRAIL_URL}index.php?/api/v2/get_case/{case_id}"
        case_response = requests.get(case_url, auth=auth, headers=headers)

        if case_response.status_code != 200:
            print(f"⚠ 警告: 无法获取测试用例 {case_id} - {case_response.status_code}")
            continue

        case_data = case_response.json()
        suite_id = case_data.get("suite_id")

        if suite_id not in cases_by_suite:
            # 获取suite信息
            suite_url = f"{TESTRAIL_URL}index.php?/api/v2/get_suite/{suite_id}"
            suite_response = requests.get(suite_url, auth=auth, headers=headers)

            if suite_response.status_code != 200:
                print(f"⚠ 警告: 无法获取suite信息 {suite_id}")
                continue

            suite_data = suite_response.json()
            suite_name = suite_data.get("name")
            cases_by_suite[suite_id] = {"suite_name": suite_name, "case_ids": []}

        cases_by_suite[suite_id]["case_ids"].append(case_id)
        print(
            f"✓ Case {case_id}: {case_data.get('title')[:50]}... -> Suite: {cases_by_suite[suite_id]['suite_name']}"
        )

    # 2. 获取测试计划信息
    print(f"\n{'=' * 60}")
    print("步骤2: 获取测试计划信息")
    print(f"{'=' * 60}")
    plan_url = f"{TESTRAIL_URL}index.php?/api/v2/get_plan/{PLAN_ID}"
    plan_response = requests.get(plan_url, auth=auth, headers=headers)

    if plan_response.status_code != 200:
        print(f"❌ 错误: 无法获取测试计划 - {plan_response.status_code}")
        print(plan_response.text)
        return

    plan_data = plan_response.json()
    print(f"✓ 测试计划: {plan_data.get('name')}")
    print(f"✓ 项目 ID: {plan_data.get('project_id')}")

    # 3. 遍历每个suite，添加对应的cases
    entries = plan_data.get("entries", [])
    print(f"\n{'=' * 60}")
    print(f"步骤3: 处理 {len(cases_by_suite)} 个Suite的测试用例")
    print(f"{'=' * 60}")

    total_added = 0
    total_skipped = 0

    for suite_id, suite_info in cases_by_suite.items():
        suite_name = suite_info["suite_name"]
        new_case_ids = suite_info["case_ids"]

        print(f"\n{'─' * 60}")
        print(f"处理Suite: {suite_name} (ID: {suite_id})")
        print(f"待添加Cases: {new_case_ids}")
        print(f"{'─' * 60}")

        target_run = None
        target_entry_id = None

        # 查找匹配suite_id的entry
        for entry in entries:
            if entry.get("suite_id") == suite_id:
                print(f"找到匹配的Suite Entry: {entry.get('name')}")

                runs = entry.get("runs", [])
                if runs:
                    target_run = runs[0]  # 使用第一个运行
                    target_entry_id = entry.get("id")
                    print(f"Run ID: {target_run.get('id')}")
                    break

        if not target_run:
            print("未找到匹配的测试运行，创建新的Plan Entry...")

            # 创建新的Plan Entry
            entry_data = {
                "suite_id": suite_id,
                "name": suite_name,
                "include_all": False,
                "case_ids": new_case_ids,
            }

            add_entry_url = f"{TESTRAIL_URL}index.php?/api/v2/add_plan_entry/{PLAN_ID}"

            entry_response = requests.post(
                add_entry_url, auth=auth, headers=headers, json=entry_data
            )

            if entry_response.status_code != 200:
                print(f"❌ 错误: 无法创建Plan Entry - {entry_response.status_code}")
                print(entry_response.text)
                continue

            new_entry = entry_response.json()
            total_added += len(new_case_ids)
            print(f"✓ 成功创建Plan Entry并添加 {len(new_case_ids)} 个测试用例")
            if new_entry.get("runs"):
                print(
                    f"✓ Run URL: {TESTRAIL_URL}index.php?/runs/view/{new_entry['runs'][0].get('id')}"
                )

        else:
            # 更新现有的Plan Entry
            run_id = target_run.get("id")
            print("更新现有的Plan Entry...")

            # 从Run中获取当前所有的tests (处理分页)
            print("正在获取运行中的所有测试用例...")
            all_tests = []
            offset = 0
            limit = 250  # TestRail API默认限制

            while True:
                tests_url = f"{TESTRAIL_URL}index.php?/api/v2/get_tests/{run_id}&limit={limit}&offset={offset}"
                tests_response = requests.get(tests_url, auth=auth, headers=headers)

                if tests_response.status_code != 200:
                    print(f"❌ 错误: 无法获取tests - {tests_response.status_code}")
                    break

                tests_data = tests_response.json()
                if isinstance(tests_data, dict) and "tests" in tests_data:
                    tests_list = tests_data["tests"]
                elif isinstance(tests_data, list):
                    tests_list = tests_data
                else:
                    tests_list = []

                if not tests_list:
                    break

                all_tests.extend(tests_list)

                if len(tests_list) < limit:
                    break

                offset += limit

            current_case_ids = [test["case_id"] for test in all_tests]
            print(f"当前运行中的Case数量: {len(current_case_ids)}")

            # 检查哪些cases需要添加
            if target_run.get("include_all"):
                print("该运行已包含所有测试用例")
                total_skipped += len(new_case_ids)
            else:
                cases_to_add = [
                    cid for cid in new_case_ids if cid not in current_case_ids
                ]
                already_exists = [
                    cid for cid in new_case_ids if cid in current_case_ids
                ]

                if already_exists:
                    print(f"已存在的Cases: {already_exists}")
                    total_skipped += len(already_exists)

                if cases_to_add:
                    # 添加新的cases
                    updated_case_ids = current_case_ids + cases_to_add
                    update_data = {"case_ids": updated_case_ids}

                    update_url = f"{TESTRAIL_URL}index.php?/api/v2/update_plan_entry/{PLAN_ID}/{target_entry_id}"
                    print(f"添加新Cases: {cases_to_add}")
                    print(f"更新后总Case数量: {len(updated_case_ids)}")

                    update_response = requests.post(
                        update_url, auth=auth, headers=headers, json=update_data
                    )

                    if update_response.status_code != 200:
                        print(
                            f"❌ 错误: 无法更新Plan Entry - {update_response.status_code}"
                        )
                        print(update_response.text)
                        continue

                    total_added += len(cases_to_add)
                    print(f"✓ 成功添加 {len(cases_to_add)} 个测试用例")
                    print(f"✓ Run URL: {TESTRAIL_URL}index.php?/runs/view/{run_id}")
                else:
                    print("所有Cases都已存在，无需添加")

    # 最终总结
    print(f"\n{'=' * 60}")
    print("完成!")
    print(f"{'=' * 60}")
    print(f"成功添加: {total_added} 个测试用例")
    print(f"已存在跳过: {total_skipped} 个测试用例")
    print(f"Plan URL: {TESTRAIL_URL}index.php?/plans/view/{PLAN_ID}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
