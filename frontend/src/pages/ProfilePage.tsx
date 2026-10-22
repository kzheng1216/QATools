import { useEffect, useState } from "react";
import { Button, Modal, Select, Space, Typography, message } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import ConfigManager from "./ConfigManager";
import {
  listProfiles,
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

const PROFILE_TEMPLATE = JSON.stringify(
  { name: "", description: "", tasks: [] },
  null,
  4
);

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

export default function ProfilePage() {
  return (
    <ConfigManager
      title="Profile"
      addTemplate={PROFILE_TEMPLATE}
      searchable
      api={{
        list: listProfiles,
        get: getProfile,
        add: addProfile,
        update: updateProfile,
        remove: deleteProfile,
      }}
      extraActions={(reload) => <GenerateWithRunPlan onDone={reload} />}
    />
  );
}
