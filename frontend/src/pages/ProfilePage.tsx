import { useEffect, useState } from "react";
import { Button, Modal, Select, Space, Tooltip, Typography, message } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import ConfigManager, { type Row } from "./ConfigManager";
import ProfileFormEditor from "../components/ProfileFormEditor";
import SplitProfileButton from "../components/SplitProfileButton";
import { PROFILE_TEMPLATE } from "../components/profileModel";
import {
  listProfiles,
  listProfileDetails,
  getProfile,
  addProfile,
  updateProfile,
  deleteProfile,
  listDevices,
  listAvailableTestRailData,
  listTestRailPlans,
  generateProfileWithTestrailData,
} from "../api/client";

const { Text } = Typography;

// New profiles start from the shared template (one blank task with every
// optional field written out), so the JSON tab and the guided tab agree.

// Modal that generates a profile from an existing testrail_data file.
function GenerateWithRunPlan({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false);
  // { "<plan>": { "<status>": "<plan>_<status>.json" } }
  const [available, setAvailable] = useState<Record<string, Record<string, string>>>({});
  const [devices, setDevices] = useState<string[]>([]);
  // Map of plan id -> plan name, for showing "id - name" in the Plan dropdown.
  const [planNames, setPlanNames] = useState<Record<string, string>>({});
  const [plan, setPlan] = useState<string>();
  const [status, setStatus] = useState<string>();
  const [device, setDevice] = useState<string>();
  const [saving, setSaving] = useState(false);

  const loadOptions = () => {
    listAvailableTestRailData()
      .then(setAvailable)
      .catch((e: Error) => message.error(`Load plans failed: ${e.message}`));
    listDevices()
      .then(setDevices)
      .catch((e: Error) => message.error(`Load devices failed: ${e.message}`));
    listTestRailPlans()
      .then((plans) =>
        setPlanNames(
          Object.fromEntries(plans.map((p) => [String(p.id), p.name]))
        )
      )
      .catch((e: Error) => message.error(`Load plan names failed: ${e.message}`));
  };

  useEffect(() => {
    if (open) loadOptions();
  }, [open]);

  const planOptions = Object.keys(available).sort();
  // Statuses only for the selected plan (those that have a data file).
  const statusOptions = plan ? Object.keys(available[plan] ?? {}).sort() : [];

  const handleAdd = async () => {
    if (!plan || !status || !device) {
      message.warning("Select plan, status and device");
      return;
    }
    const file = available[plan]?.[status];
    if (!file) {
      message.error("No testrail data file for that plan/status");
      return;
    }
    setSaving(true);
    try {
      const res = await generateProfileWithTestrailData(plan, device, file);
      message.success(res.message);
      setOpen(false);
      setPlan(undefined);
      setStatus(undefined);
      setDevice(undefined);
      onDone();
    } catch (e) {
      message.error(`Generate failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
        Add Profile with RunPlan
      </Button>
      <Modal
        title="Add Profile with RunPlan"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={handleAdd}
        okText="Add"
        confirmLoading={saving}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong>Plan</Text>
            <Select
              style={{ width: "100%", marginTop: 4 }}
              placeholder="Select a plan"
              value={plan}
              onChange={(v) => {
                setPlan(v);
                setStatus(undefined); // reset status when plan changes
              }}
              options={planOptions.map((p) => ({
                value: p, // value is the plan id — this is what the API receives
                label: planNames[p] ? `${p} - ${planNames[p]}` : p,
              }))}
              showSearch
              optionFilterProp="label"
              notFoundContent="No plans with cached data"
            />
          </div>
          <div>
            <Text strong>Status</Text>
            <Select
              style={{ width: "100%", marginTop: 4 }}
              placeholder={plan ? "Select a status" : "Select a plan first"}
              value={status}
              onChange={setStatus}
              disabled={!plan}
              options={statusOptions.map((s) => ({ value: s, label: s }))}
              notFoundContent="No cached statuses"
            />
          </div>
          <div>
            <Text strong>Device</Text>
            <Select
              style={{ width: "100%", marginTop: 4 }}
              placeholder="Select a device"
              value={device}
              onChange={setDevice}
              options={devices.map((d) => ({ value: d, label: d }))}
              showSearch
              notFoundContent="No devices"
            />
          </div>
        </Space>
      </Modal>
    </>
  );
}

// Example values shown when hovering a field name in the profile JSON editor
// (View/Edit). Keyed by the bare JSON key; each value illustrates what can be
// filled in for that field.
const PROFILE_FIELD_DOCS: Record<string, string> = {
  name: 'e.g. "execution plan 2659884070"',
  description: 'e.g. "4K NA blocked re-run" (any free text, "" allowed)',
  tasks: 'Array of task objects, e.g. [ { "config": { ... }, "timeout": 36000 }, ... ]',
  execution_mode: '"SERIAL" or "PARALLEL" (profile level: how the tasks run)',
  config:
    'A config object, e.g. { "case_type": "BDD", "case_id": "2659884070", "device": "d_01", "testrail_plan_id": 0, "repeat": 0, "automation_test_branch": "main", "roku_automation_branch": "main" }',
  case_type: '"BDD" | "UT" | "NEW"',
  case_id:
    'BDD: "2659884070" (numeric, no bdd- prefix). UT/NEW: "MyTestCase.test_something"',
  testrail_case_id: 'e.g. 2659884070 (number) or "2659884070"',
  device: 'A device name from the Device tab, e.g. "d_01" or "d_ws22_Damon_US"',
  testrail_plan_id: 'e.g. 26595350. Use 0 for no plan (results not uploaded)',
  repeat: "e.g. 0 (run once), 2 (run 3 times total)",
  automation_test_branch: 'e.g. "main" or "yuzheng/AUTO-73326/fix"',
  roku_automation_branch: 'e.g. "main"',
  timeout: "Seconds, e.g. 36000 or 360000",
};

// Summary columns between Name and Actions, fed by listProfileDetails().
const PROFILE_COLUMNS: ColumnsType<Row> = [
  {
    title: "Description",
    key: "description",
    dataIndex: "description",
    ellipsis: true,
    render: (v: unknown) => {
      const text = String(v ?? "");
      return text ? <Tooltip title={text}>{text}</Tooltip> : "-";
    },
  },
  {
    title: "Execution mode",
    key: "execution_mode",
    dataIndex: "execution_mode",
    width: 140,
    render: (v: unknown) => String(v ?? "") || "-",
  },
  {
    title: "Total tasks",
    key: "total_tasks",
    dataIndex: "total_tasks",
    width: 130,
    align: "center" as const,
    sorter: (a: Row, b: Row) => Number(a.total_tasks ?? 0) - Number(b.total_tasks ?? 0),
  },
];

export default function ProfilePage() {
  return (
    <ConfigManager
      title="Profile"
      actionsWidth={280}
      addTemplate={PROFILE_TEMPLATE}
      searchable
      loadRows={listProfileDetails}
      extraColumns={PROFILE_COLUMNS}
      fieldDocs={PROFILE_FIELD_DOCS}
      formEditor={(p) => <ProfileFormEditor {...p} />}
      api={{
        list: listProfiles,
        get: getProfile,
        add: addProfile,
        update: updateProfile,
        remove: deleteProfile,
      }}
      extraActions={(reload) => <GenerateWithRunPlan onDone={reload} />}
      rowActions={(name, reload) => <SplitProfileButton profile={name} onDone={reload} />}
    />
  );
}
