import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import { ScissorOutlined } from "@ant-design/icons";
import {
  listDevices,
  splitProfile,
  type SplitAssignment,
  type SplitResult,
} from "../api/client";

const { Text } = Typography;

interface Props {
  profile: string;
  // Refresh the profile list after new split profiles are written.
  onDone: () => void;
}

/**
 * "Split" row action: distribute a profile's cases across several devices.
 *
 * The backend asks the AI which selected devices satisfy each case's TestRail
 * execution conditions, then assigns every case to exactly one device while
 * keeping per-device totals even. Cases no device satisfies go to the FIRST
 * selected device, so selection order matters and is shown to the user.
 */
export default function SplitProfileButton({ profile, onDone }: Props) {
  const [open, setOpen] = useState(false);
  const [devices, setDevices] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [splitting, setSplitting] = useState(false);
  const [result, setResult] = useState<SplitResult | null>(null);

  useEffect(() => {
    if (!open) return;
    listDevices()
      .then((d) => setDevices([...d].sort((a, b) => a.localeCompare(b))))
      .catch((e: Error) => message.error(`Load devices failed: ${e.message}`));
  }, [open]);

  const reset = () => {
    setSelected([]);
    setResult(null);
  };

  const handleSplit = async () => {
    if (selected.length === 0) {
      message.warning("Select at least one device");
      return;
    }
    setSplitting(true);
    setResult(null);
    try {
      const res = await splitProfile(profile, selected);
      setResult(res);
      message.success(res.message);
      onDone();
    } catch (e) {
      message.error(`Split failed: ${(e as Error).message}`);
    } finally {
      setSplitting(false);
    }
  };

  return (
    <>
      {/* Same style as Device → "QA Hub Sync": icon-only primary small button,
          label shown in a hover tooltip. */}
      <Tooltip title="Split">
        <Button
          type="primary"
          size="small"
          icon={<ScissorOutlined />}
          onClick={() => {
            reset();
            setOpen(true);
          }}
        />
      </Tooltip>
      <Modal
        title={`Split Profile: ${profile}`}
        open={open}
        onCancel={() => !splitting && setOpen(false)}
        width={result ? 1100 : 640}
        style={{ top: 24 }}
        styles={{ body: { maxHeight: "calc(100vh - 200px)", overflowY: "auto" } }}
        maskClosable={!splitting}
        destroyOnClose
        footer={
          // Once the split has run and its result is shown, the only action
          // left is Close (re-opening the dialog starts a fresh split).
          result ? (
            <Button type="primary" onClick={() => setOpen(false)}>
              Close
            </Button>
          ) : (
            <Space>
              <Button onClick={() => setOpen(false)} disabled={splitting}>
                Cancel
              </Button>
              <Button
                type="primary"
                icon={<ScissorOutlined />}
                loading={splitting}
                disabled={selected.length === 0}
                onClick={handleSplit}
              >
                Split
              </Button>
            </Space>
          )
        }
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong>Devices</Text>
            <Select
              mode="multiple"
              style={{ width: "100%", marginTop: 4 }}
              placeholder="Select one or more devices"
              value={selected}
              onChange={setSelected}
              disabled={splitting || !!result}
              options={devices.map((d) => ({ value: d, label: d }))}
              showSearch
              allowClear
            />
            {selected.length > 0 && (
              <Text type="secondary" style={{ display: "block", marginTop: 6, fontSize: 12 }}>
                Cases that no selected device can run go to the first one:{" "}
                <Tag color="gold" style={{ marginInlineEnd: 0 }}>
                  {selected[0]}
                </Tag>
              </Text>
            )}
          </div>

          <Text type="secondary" style={{ fontSize: 12 }}>
            New profiles are named <Text code>{profile}__001</Text>,{" "}
            <Text code>{profile}__002</Text>, … (numbers already in use are skipped;
            existing profiles are never overwritten).
          </Text>

          {splitting && (
            <Alert
              type="info"
              showIcon
              message="Analyzing cases…"
              description="Fetching TestRail execution conditions and asking the AI to match each case to the devices. This can take a minute for large profiles."
            />
          )}

          {result && <SplitResultView result={result} />}
        </Space>
      </Modal>
    </>
  );
}

function SplitResultView({ result }: { result: SplitResult }) {
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Alert
        type="success"
        showIcon
        message={result.message}
        description={
          <Space wrap>
            {result.profiles.map((p) => (
              <Tag key={p.profile} color="blue">
                {p.profile} ({p.count})
              </Tag>
            ))}
          </Space>
        }
      />
      <Table<SplitAssignment>
        size="small"
        rowKey={(r, i) => `${r.case_id}-${i}`}
        dataSource={result.assignments}
        pagination={{ defaultPageSize: 10, showSizeChanger: true, hideOnSinglePage: true }}
        columns={[
          {
            title: "TestRail",
            dataIndex: "testrail_case_id",
            width: 110,
            render: (t: string | number) =>
              /^\d+$/.test(String(t)) ? (
                <a
                  href={`https://testrail.eswat.roku.com/testrail/index.php?/cases/view/${t}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {t}
                </a>
              ) : (
                t || "-"
              ),
          },
          {
            title: "Case",
            key: "case",
            ellipsis: true,
            render: (_, r) => (
              <Tooltip title={r.case_id}>
                <span>{r.title || r.case_id}</span>
              </Tooltip>
            ),
          },
          {
            title: "Assigned device",
            dataIndex: "device",
            width: 220,
            filters: result.profiles.map((p) => ({ text: p.device, value: p.device })),
            onFilter: (v, r) => r.device === v,
            render: (d: string, r) => (
              <Space size={4} wrap>
                <Tag color="blue">{d}</Tag>
                {r.fallback && (
                  <Tooltip title="No selected device met this case's conditions; placed on the first device.">
                    <Tag color="gold">fallback</Tag>
                  </Tooltip>
                )}
                {r.ai_failed && (
                  <Tooltip title="AI analysis failed for this case; it was treated as compatible with every device.">
                    <Tag color="red">AI failed</Tag>
                  </Tooltip>
                )}
              </Space>
            ),
          },
          {
            title: "Compatible",
            dataIndex: "compatible",
            width: 90,
            align: "center" as const,
            render: (c: string[]) => (
              <Tooltip title={c.length ? c.join(", ") : "none"}>
                <span>{c.length}</span>
              </Tooltip>
            ),
          },
          {
            title: "Reason",
            dataIndex: "reason",
            ellipsis: true,
            render: (t: string) => (
              <Tooltip title={t}>
                <span>{t}</span>
              </Tooltip>
            ),
          },
        ]}
      />
    </Space>
  );
}
