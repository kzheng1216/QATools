import { Button, message, Tooltip } from "antd";
import {
  CloudDownloadOutlined,
  CheckOutlined,
  CloseOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import ConfigManager, { type Row } from "./ConfigManager";
import {
  listDevices,
  listDeviceDetails,
  getDevice,
  addDevice,
  updateDevice,
  deleteDevice,
  syncDeviceWithQaHub,
} from "../api/client";

const DEVICE_TEMPLATE = JSON.stringify(
  { name: "", ip_address: "", brand_name: "" },
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
  jsonPath: string
): ColumnsType<Row>[number] => ({
  title: <Tooltip title={jsonPath}>{title}</Tooltip>,
  key: field,
  dataIndex: field,
  width: 110,
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
    width: 130,
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
  flagColumn("QA Bot", "qa_bot_config", "roku.qa_bot_config"),
  flagColumn("Maxwell", "maxwell_config", "roku.maxwell_config"),
  flagColumn("Power", "power_config", "roku.power_config"),
  flagColumn("AVR", "avr_info_config", "roku.avr_info_config"),
  flagColumn("HDMI 1", "hdmi_1", 'roku.devices_config."HDMI 1"'),
  flagColumn("HDMI 2", "hdmi_2", 'roku.devices_config."HDMI 2"'),
  flagColumn("HDMI 3", "hdmi_3", 'roku.devices_config."HDMI 3"'),
];

export default function DevicePage() {
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

  return (
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
        <Button
          type="primary"
          size="small"
          icon={<CloudDownloadOutlined />}
          onClick={() => handleSync(name, reload)}
        >
          QA Hub Sync
        </Button>
      )}
    />
  );
}
