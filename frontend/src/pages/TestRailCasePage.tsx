import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Checkbox,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  PlusOutlined,
  ReloadOutlined,
  DeleteOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import {
  listTestRailPlans,
  addTestRailPlan,
  deleteTestRailPlan,
  listTestRailPlanCases,
  listTestRailStatuses,
  type TestRailPlan,
  type TestRailCase,
} from "../api/client";

const { Title, Text } = Typography;

// Color per TestRail status label (falls back to default).
const STATUS_COLOR: Record<string, string> = {
  Passed: "success",
  Failed: "error",
  Blocked: "volcano",
  Retest: "gold",
  Untested: "default",
  "For Review": "processing",
  NA: "purple",
  Broken: "magenta",
  Waived: "cyan",
};

export default function TestRailCasePage() {
  const [plans, setPlans] = useState<TestRailPlan[]>([]);
  const [loading, setLoading] = useState(false);

  const [addOpen, setAddOpen] = useState(false);
  const [newId, setNewId] = useState<number | null>(null);
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);

  // Case search: pick a plan + status, then Search.
  const [queryPlanId, setQueryPlanId] = useState<number | undefined>();
  const [queryStatus, setQueryStatus] = useState<string>("Failed");
  const [sync, setSync] = useState(false);
  const [searchedStatus, setSearchedStatus] = useState<string>("Failed");
  const [cases, setCases] = useState<TestRailCase[]>([]);
  const [loadingCases, setLoadingCases] = useState(false);
  const [searched, setSearched] = useState(false);

  const [statusOptions, setStatusOptions] = useState<string[]>(["Failed"]);

  useEffect(() => {
    // Hide "Waived" from the filter (Retest comes from the live status list).
    const HIDDEN = new Set(["Waived"]);
    listTestRailStatuses()
      .then((list) =>
        setStatusOptions(list.map((s) => s.label).filter((l) => l && !HIDDEN.has(l)))
      )
      .catch((e: Error) => message.error(`Load statuses failed: ${e.message}`));
  }, []);

  const handleSearch = () => {
    if (queryPlanId === undefined) {
      message.warning("Please select a plan");
      return;
    }
    setLoadingCases(true);
    setSearched(true);
    setSearchedStatus(queryStatus);
    listTestRailPlanCases(queryPlanId, queryStatus, sync)
      .then((res) => setCases(res.cases))
      .catch((e: Error) => message.error(`Search failed: ${e.message}`))
      .finally(() => setLoadingCases(false));
  };

  const load = () => {
    setLoading(true);
    listTestRailPlans()
      .then(setPlans)
      .catch((e: Error) => message.error(`Load plans failed: ${e.message}`))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleAdd = async () => {
    if (newId === null || Number.isNaN(newId)) {
      message.warning("Plan ID is required");
      return;
    }
    if (!newName.trim()) {
      message.warning("Plan name is required");
      return;
    }
    setSaving(true);
    try {
      await addTestRailPlan({ id: newId, name: newName.trim() });
      message.success(`Plan ${newId} added`);
      setAddOpen(false);
      setNewId(null);
      setNewName("");
      load();
    } catch (e) {
      message.error(`Add failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteTestRailPlan(id);
      message.success(`Plan ${id} deleted`);
      load();
    } catch (e) {
      message.error(`Delete failed: ${(e as Error).message}`);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          TestRail Plans
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            Refresh
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
            Add Plan
          </Button>
        </Space>
      </div>

      <Card>
        <Table<TestRailPlan>
          rowKey="id"
          loading={loading}
          dataSource={plans}
          pagination={{
            defaultPageSize: 15,
            pageSizeOptions: [10, 15, 30, 50],
            showSizeChanger: true,
          }}
          columns={[
            {
              title: "Plan ID",
              dataIndex: "id",
              key: "id",
              width: 140,
              sorter: (a, b) => a.id - b.id,
              render: (id: number) => (
                <a
                  href={`https://testrail.eswat.roku.com/testrail/index.php?/plans/view/${id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {id}
                </a>
              ),
            },
            {
              title: "Name",
              dataIndex: "name",
              key: "name",
              sorter: (a, b) => a.name.localeCompare(b.name),
            },
            {
              title: "Action",
              key: "action",
              width: 120,
              render: (_: unknown, r: TestRailPlan) => (
                <Popconfirm
                  title={`Delete plan ${r.id}?`}
                  okText="Delete"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => handleDelete(r.id)}
                >
                  <Button size="small" danger icon={<DeleteOutlined />}>
                    Delete
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>

      {/* Case search: Plan + Status + Search (below the plans list) */}
      <Card title="Search Cases" style={{ marginTop: 16 }}>
        <Space wrap align="end" style={{ marginBottom: cases.length || searched ? 16 : 0 }}>
          <div style={{ minWidth: 320 }}>
            <Text strong>Plan</Text>
            <Select
              style={{ width: "100%", marginTop: 4 }}
              placeholder="Select a plan"
              value={queryPlanId}
              onChange={setQueryPlanId}
              options={plans.map((p) => ({ value: p.id, label: `${p.id} — ${p.name}` }))}
              showSearch
              optionFilterProp="label"
              popupMatchSelectWidth={false}
            />
          </div>
          <div style={{ minWidth: 160 }}>
            <Text strong>Status</Text>
            <Select
              style={{ width: "100%", marginTop: 4 }}
              value={queryStatus}
              onChange={setQueryStatus}
              optionLabelProp="label"
              options={statusOptions.map((s) => ({
                value: s,
                label: <Tag color={STATUS_COLOR[s] ?? "default"}>{s}</Tag>,
              }))}
            />
          </div>
          <Checkbox checked={sync} onChange={(e) => setSync(e.target.checked)}>
            sync
          </Checkbox>
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={loadingCases}
            disabled={queryPlanId === undefined}
            onClick={handleSearch}
          >
            Search
          </Button>
          {searched && <Text type="secondary">{cases.length} case(s)</Text>}
        </Space>

        {searched && (
          <Table<TestRailCase>
            size="small"
            rowKey="test_id"
            loading={loadingCases}
            dataSource={cases}
            pagination={{ defaultPageSize: 15, pageSizeOptions: [10, 15, 30, 50], showSizeChanger: true }}
            columns={[
              {
                title: "Case ID",
                dataIndex: "case_id",
                key: "case_id",
                width: 120,
                render: (cid: number, r: TestRailCase) => (
                  <a href={r.link} target="_blank" rel="noopener noreferrer">
                    C{cid}
                  </a>
                ),
              },
              { title: "Title", dataIndex: "title", key: "title", ellipsis: true },
              {
                title: "Automation ID",
                dataIndex: "automation_id",
                key: "automation_id",
                ellipsis: true,
                render: (aid: string | null) => aid || "-",
              },
              {
                title: "Status",
                key: "status",
                width: 110,
                render: () => (
                  <Tag color={STATUS_COLOR[searchedStatus] ?? "default"}>{searchedStatus}</Tag>
                ),
              },
              {
                title: "Run ID",
                dataIndex: "run_id",
                key: "run_id",
                width: 110,
                sorter: (a: TestRailCase, b: TestRailCase) => a.run_id - b.run_id,
                render: (runId: number) => (
                  <a
                    href={`https://testrail.eswat.roku.com/testrail/index.php?/runs/view/${runId}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {runId}
                  </a>
                ),
              },
            ]}
          />
        )}
      </Card>

      <Modal
        title="Add TestRail Plan"
        open={addOpen}
        onCancel={() => setAddOpen(false)}
        onOk={handleAdd}
        confirmLoading={saving}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <div>
            <Text strong>Plan ID</Text>
            <InputNumber
              style={{ width: "100%", marginTop: 4 }}
              placeholder="e.g. 26595408"
              value={newId ?? undefined}
              onChange={(v) => setNewId(v ?? null)}
              controls={false}
            />
          </div>
          <div>
            <Text strong>Name</Text>
            <Input
              style={{ marginTop: 4 }}
              placeholder="Plan name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onPressEnter={handleAdd}
            />
          </div>
        </Space>
      </Modal>
    </div>
  );
}
