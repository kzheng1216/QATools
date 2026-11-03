import { useState } from "react";
import { Button, message, Modal, Popconfirm, Tooltip, Typography } from "antd";
import {
  CloudDownloadOutlined,
  CheckOutlined,
  CloseOutlined,
  DownloadOutlined,
  LockOutlined,
  EyeOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ConfigManager, { type Row } from "./ConfigManager";
import {
  listDevices,
  listDeviceDetails,
  getDevice,
  addDevice,
  updateDevice,
  deleteDevice,
  syncDeviceWithQaHub,
  getDeviceInfoFromQAHub,
  reserveDevice,
  deviceDownloadUrl,
} from "../api/client";

const { Text } = Typography;

// Escape the few characters that would break a GFM table cell.
const mdCell = (v: unknown): string => {
  const raw =
    v === null || v === undefined
      ? ""
      : typeof v === "object"
        ? JSON.stringify(v)
        : String(v);
  return raw
    .replace(/\\/g, "\\\\")
    .replace(/\|/g, "\\|")
    // react-markdown has no raw-HTML plugin here, so collapse newlines.
    .replace(/\r?\n+/g, " ");
};

// Render the backend JSON as a two-column GFM table (Field | Value).
// Nested objects/arrays are flattened into dotted field names.
const jsonToMarkdownTable = (data: unknown): string => {
  const rows: Array<[string, unknown]> = [];
  const walk = (value: unknown, prefix: string) => {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const entries = Object.entries(value as Record<string, unknown>);
      if (entries.length === 0) {
        rows.push([prefix || "(empty)", "{}"]);
        return;
      }
      entries.forEach(([k, v]) => walk(v, prefix ? `${prefix}.${k}` : k));
      return;
    }
    rows.push([prefix || "value", value]);
  };
  walk(data, "");
  if (rows.length === 0) return "_No data_";
  const head = "| Field | Value |\n| --- | --- |";
  const body = rows
    .map(([k, v]) => `| ${mdCell(k)} | ${mdCell(v)} |`)
    .join("\n");
  return `${head}\n${body}`;
};

const DEVICE_TEMPLATE = JSON.stringify(
  { roku: { name: "", ip_address: "", serial_number: "", device_id: "", brand_name: ""}},
  null,
  4
);

// Render a white check on a green circle / white cross on a red circle.
const flagCell = (present: boolean) => (
  <span
    style={{
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: 15,
      height: 15,
      borderRadius: "50%",
      background: present ? "#52c41a" : "#ff4d4f",
      color: "#fff",
    }}
  >
    {present ? (
      <CheckOutlined style={{ fontSize: 9 }} />
    ) : (
      <CloseOutlined style={{ fontSize: 9 }} />
    )}
  </span>
);

// One presence column: title, the row flag field, and a tooltip naming the
// underlying JSON path.
const flagColumn = (
  title: string,
  field: string,
  jsonPath: string,
  width = 65
): ColumnsType<Row>[number] => ({
  title: <Tooltip title={jsonPath}>{title}</Tooltip>,
  key: field,
  dataIndex: field,
  // Half of the previous 110px; Name / IP / Actions keep their widths.
  width,
  align: "center",
  // false < true: ascending puts crosses first, present (✓) last.
  sorter: (a: Row, b: Row) => Number(Boolean(a[field])) - Number(Boolean(b[field])),
  render: (v: unknown) => flagCell(Boolean(v)),
});

const DEVICE_FLAG_COLUMNS: ColumnsType<Row> = [
  {
    title: <Tooltip title="roku.ip_address">IP</Tooltip>,
    key: "ip_address",
    dataIndex: "ip_address",
    width: 100,
    // Sort by IP numerically per octet so 10.64.9.x < 10.64.19.x.
    sorter: (a: Row, b: Row) => {
      const toNum = (ip: unknown) =>
        String(ip ?? "")
          .split(".")
          .reduce((acc, o) => acc * 256 + (Number(o) || 0), 0);
      return toNum(a.ip_address) - toNum(b.ip_address);
    },
    render: (v: unknown) => (v ? String(v) : "-"),
  },
  flagColumn("QA Bot", "qa_bot_config", "roku.qa_bot_config", 90),
  flagColumn("Maxwell", "maxwell_config", "roku.maxwell_config"),
  flagColumn("STB", "stb", "roku.stb"),
  flagColumn("Power", "power_config", "roku.power_config"),
  flagColumn("AVR", "avr_info_config", "roku.avr_info_config"),
  flagColumn("HDMI 1", "hdmi_1", 'roku.devices_config."HDMI 1"'),
  flagColumn("HDMI 2", "hdmi_2", 'roku.devices_config."HDMI 2"'),
  flagColumn("HDMI 3", "hdmi_3", 'roku.devices_config."HDMI 3"'),

];

export default function DevicePage() {
  const [infoOpen, setInfoOpen] = useState(false);
  const [infoName, setInfoName] = useState("");
  const [infoLoading, setInfoLoading] = useState(false);
  const [infoMarkdown, setInfoMarkdown] = useState("");

  const handleSync = async (name: string, reload: () => void) => {
    const hide = message.loading(`Syncing ${name} with QA Hub…`, 0);
    try {
      const res = await syncDeviceWithQaHub(name);
      hide();
      const ok = String(res?.Result ?? "").toUpperCase() === "SUCCESS";
      const msg = String(res?.Message ?? (ok ? "Sync SUCCESS" : "Sync FAILED"));
      if (ok) {
        message.success(msg);
        reload();
      } else {
        message.error(msg);
      }
    } catch (e) {
      hide();
      message.error(`Sync failed: ${(e as Error).message}`);
    }
  };

  const handleViewRokuInfo = async (name: string) => {
    setInfoName(name);
    setInfoMarkdown("");
    setInfoLoading(true);
    setInfoOpen(true);
    try {
      const res = await getDeviceInfoFromQAHub(name);
      // Backends may answer either with the raw info object or with the
      // { Result, Message } envelope used by the other device endpoints.
      const result = String((res as Record<string, unknown>)?.Result ?? "").toUpperCase();
      if (result === "FAILED") {
        const msg = String((res as Record<string, unknown>)?.Message ?? "View Roku Info FAILED");
        message.error(msg);
        setInfoMarkdown(`_${msg}_`);
        return;
      }
      setInfoMarkdown(jsonToMarkdownTable(res));
    } catch (e) {
      const msg = `View Roku Info failed: ${(e as Error).message}`;
      message.error(msg);
      setInfoMarkdown(`_${msg}_`);
    } finally {
      setInfoLoading(false);
    }
  };

  // Reserve on QA Hub (30 days, steal). Backend normalizes the QA Hub reply to
  // { Result: "SUCCESS" | "FAILED", Message }.
  const handleReserve = async (name: string) => {
    const hide = message.loading(`Reserving ${name}…`, 0);
    try {
      const res = await reserveDevice(name);
      hide();
      const ok = String(res?.Result ?? "").toUpperCase() === "SUCCESS";
      const msg = String(
        res?.Message ?? (ok ? `${name} reserved` : `Reserve ${name} failed`)
      );
      if (ok) {
        message.success(msg);
      } else {
        message.error(msg);
      }
    } catch (e) {
      hide();
      message.error(`Reserve failed: ${(e as Error).message}`);
    }
  };

  return (
    <>
    <ConfigManager
      title="Device"
      addTemplate={DEVICE_TEMPLATE}
      searchable
      loadRows={listDeviceDetails}
      extraColumns={DEVICE_FLAG_COLUMNS}
      api={{
        list: listDevices,
        get: getDevice,
        add: addDevice,
        update: updateDevice,
        remove: deleteDevice,
      }}
      rowActions={(name, reload) => (
        <>
          {/* Download the device's raw <name>.json config file. */}
          <Tooltip title="Download JSON">
            <Button
              size="small"
              icon={<DownloadOutlined />}
              href={deviceDownloadUrl(name)}
              download={`${name}.json`}
            />
          </Tooltip>
          <Tooltip title="View Roku Info">
            <Button
              type="primary"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => handleViewRokuInfo(name)}
            />
          </Tooltip>
          <Popconfirm
            title="QA Hub Sync"
            description={`Sync "${name}" from QA Hub?`}
            okText="Confirm"
            cancelText="Cancel"
            onConfirm={() => handleSync(name, reload)}
          >
            <Tooltip title="QA Hub Sync">
              <Button
                type="primary"
                size="small"
                icon={<CloudDownloadOutlined />}
              />
            </Tooltip>
          </Popconfirm>
          <Popconfirm
            title="Reserve on QA Hub"
            description={`Reserve "${name}" on QA Hub?`}
            okText="Confirm"
            cancelText="Cancel"
            onConfirm={() => handleReserve(name)}
          >
            <Tooltip title="Reserve on QA Hub">
              <Button type="primary" size="small" icon={<LockOutlined />} />
            </Tooltip>
          </Popconfirm>
        </>
      )}
      actionsWidth={340}
    />

    {/* Roku info — width shrink-wraps the widest table cell, capped at 3/4
        of the page width; height capped at 2/3 of the viewport. */}
    <Modal
      title={`Roku Info - ${infoName}`}
      open={infoOpen}
      onCancel={() => setInfoOpen(false)}
      footer={null}
      width="fit-content"
      style={{ maxWidth: "75vw" }}
      styles={{
        content: { maxWidth: "75vw" },
        body: { maxHeight: "66vh", overflow: "auto" },
      }}
    >
      <div className="chat-markdown device-info-md" style={{ minWidth: 320 }}>
        {infoLoading ? (
          <Text type="secondary">Loading…</Text>
        ) : (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{infoMarkdown}</ReactMarkdown>
        )}
      </div>
    </Modal>
    </>
  );
}
