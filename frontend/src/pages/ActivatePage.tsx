/**
 * Connected / Unconnected Mode page.
 *
 * Converts one or more Roku TVs between:
 *   Connected Mode   -> 5_activate/factory_reset_and_activate.py          (factory reset + account link)
 *   Unconnected Mode -> 5_activate/factory_reset_and_unconnected_mode.py  (factory reset, "connect later")
 *
 * Features
 *  - multi-device selection: every device is converted by its own backend
 *    process, in parallel, with its own log file;
 *  - precheck (POST /v1/activate/precheck): shows connection_type / is_linked
 *    and blocks converting a WIRELESS device to Unconnected Mode;
 *  - Connected Mode: the activation account email of every selected device is
 *    shown (prefilled from config/activate_account.yml), can be edited, and is
 *    passed to the backend as the activation parameter;
 *  - live log tailing per job with a configurable refresh interval (default 5s,
 *    switchable off) that auto-scrolls to the bottom when new output arrives.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import {
  ApiOutlined,
  DeleteOutlined,
  MailOutlined,
  DisconnectOutlined,
  EyeOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  StopOutlined,
} from "@ant-design/icons";
import {
  deleteActivateJob,
  getActivateEmails,
  listActivateJobs,
  listDevices,
  precheckActivate,
  startActivate,
  stopActivate,
  viewActivateLog,
  type ActivateJob,
  type ActivateMode,
  type ActivatePrecheck,
} from "../api/client";

const { Title, Text } = Typography;

// Auto-refresh interval options (ms). 5s is the default.
const REFRESH_OPTIONS = [
  { label: "1s", value: 1000 },
  { label: "2s", value: 2000 },
  { label: "3s", value: 3000 },
  { label: "5s", value: 5000 },
  { label: "10s", value: 10000 },
  { label: "30s", value: 30000 },
  { label: "60s", value: 60000 },
];
const DEFAULT_REFRESH_MS = 5000;
const REFRESH_STORAGE_KEY = "activate-log-refresh";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const ERROR_RE = /\b(ERROR|CRITICAL|FATAL|Traceback|Exception|FAILED|FAIL)\b/;
const WARNING_RE = /\b(WARNING|WARN)\b/;

// Render log content line-by-line, highlighting errors / warnings.
function renderLog(content: string) {
  if (!content) return null;
  return content.split("\n").map((line, i) => {
    const err = ERROR_RE.test(line);
    const warn = !err && WARNING_RE.test(line);
    return (
      <div
        key={i}
        style={
          err
            ? { color: "#ff5c5c", fontWeight: 600, background: "rgba(255,0,0,0.12)" }
            : warn
            ? { color: "#ffb020", fontWeight: 600, background: "rgba(255,176,32,0.12)" }
            : undefined
        }
      >
        {line || " "}
      </div>
    );
  });
}

const modeLabel = (m: ActivateMode) =>
  m === "connected" ? "Connected Mode" : "Unconnected Mode";

const fmtTime = (epoch?: number) =>
  epoch ? new Date(epoch * 1000).toLocaleString() : "-";

/** One live-tailing log pane. Scrolls to the bottom whenever content grows. */
function LogPane({
  logFile,
  content,
  updatedAt,
}: {
  logFile: string;
  content: string;
  updatedAt: string;
}) {
  const ref = useRef<HTMLPreElement>(null);
  // Only stick to the bottom while the user is already near the bottom, so
  // scrolling up to read history isn't yanked away on every refresh.
  const stickRef = useRef(true);

  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  useEffect(() => {
    const el = ref.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [content]);

  return (
    <div>
      <Space style={{ marginBottom: 8 }} wrap>
        <Text strong>{logFile}</Text>
        {updatedAt && <Text type="secondary">refreshed {updatedAt}</Text>}
      </Space>
      <pre
        ref={ref}
        onScroll={onScroll}
        style={{
          margin: 0,
          padding: 12,
          background: "#1e1e1e",
          color: "#00b000",
          borderRadius: 6,
          minHeight: 260,
          maxHeight: 560,
          overflow: "auto",
          fontFamily: "monospace",
          fontSize: 13,
          lineHeight: 1.35,
          whiteSpace: "pre-wrap",
        }}
      >
        {content ? renderLog(content) : "(waiting for log output...)"}
      </pre>
    </div>
  );
}

export default function ActivatePage() {
  const [devices, setDevices] = useState<string[]>([]);
  const [loadingDevices, setLoadingDevices] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [mode, setMode] = useState<ActivateMode>("connected");

  // device_name -> activation account email (Connected Mode only). Prefilled
  // from the backend default (country mapping) and editable by the user.
  const [emails, setEmails] = useState<Record<string, string>>({});
  const [loadingEmails, setLoadingEmails] = useState(false);

  const [prechecks, setPrechecks] = useState<ActivatePrecheck[]>([]);
  const [prechecking, setPrechecking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [rejected, setRejected] = useState<ActivatePrecheck[]>([]);

  const [jobs, setJobs] = useState<ActivateJob[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [stoppingPid, setStoppingPid] = useState<number | null>(null);

  // Log files currently being tailed (one tab each) + their content.
  const [openLogs, setOpenLogs] = useState<string[]>([]);
  const [activeLog, setActiveLog] = useState<string>();
  const [logContent, setLogContent] = useState<Record<string, string>>({});
  const [logUpdated, setLogUpdated] = useState<Record<string, string>>({});

  // Auto-refresh settings (persisted).
  const [autoRefresh, setAutoRefresh] = useState<boolean>(() => {
    const raw = localStorage.getItem(REFRESH_STORAGE_KEY);
    return raw ? JSON.parse(raw).enabled !== false : true;
  });
  const [refreshMs, setRefreshMs] = useState<number>(() => {
    const raw = localStorage.getItem(REFRESH_STORAGE_KEY);
    return raw ? Number(JSON.parse(raw).interval) || DEFAULT_REFRESH_MS : DEFAULT_REFRESH_MS;
  });
  useEffect(() => {
    localStorage.setItem(
      REFRESH_STORAGE_KEY,
      JSON.stringify({ enabled: autoRefresh, interval: refreshMs })
    );
  }, [autoRefresh, refreshMs]);

  const [viewer, setViewer] = useState<{ name: string; content: string } | null>(null);

  // ---------- loaders ----------
  useEffect(() => {
    setLoadingDevices(true);
    listDevices()
      .then(setDevices)
      .catch((e: Error) => message.error(`Load devices failed: ${e.message}`))
      .finally(() => setLoadingDevices(false));
  }, []);

  // Prefill the email of every newly selected device (keeps user edits).
  useEffect(() => {
    const missing = selected.filter((d) => emails[d] === undefined);
    if (!missing.length) return;
    setLoadingEmails(true);
    getActivateEmails(missing)
      .then((map) => setEmails((prev) => ({ ...map, ...prev })))
      .catch((e: Error) => message.error(`Load activation emails failed: ${e.message}`))
      .finally(() => setLoadingEmails(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected.join("|")]);

  const invalidEmails = useMemo(
    () =>
      mode === "connected"
        ? selected.filter((d) => !EMAIL_RE.test((emails[d] ?? "").trim()))
        : [],
    [mode, selected, emails]
  );

  const refreshJobs = useCallback(async (silent = false) => {
    if (!silent) setLoadingJobs(true);
    try {
      setJobs(await listActivateJobs());
    } catch (e) {
      if (!silent) message.error(`Load jobs failed: ${(e as Error).message}`);
    } finally {
      if (!silent) setLoadingJobs(false);
    }
  }, []);

  useEffect(() => {
    refreshJobs();
  }, [refreshJobs]);

  const runningJobs = useMemo(() => jobs.filter((j) => j.running), [jobs]);

  // Running jobs are tailed automatically; keep their tabs open.
  useEffect(() => {
    const names = runningJobs.map((j) => j.log_file);
    if (!names.length) return;
    setOpenLogs((prev) => {
      const merged = [...names, ...prev.filter((n) => !names.includes(n))];
      return merged;
    });
    setActiveLog((prev) => (prev && names.concat(openLogs).includes(prev) ? prev : names[0]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runningJobs.map((j) => j.log_file).join("|")]);

  // Single timer drives: job list + every open log tab. Stops when the
  // auto-refresh switch is off (manual Refresh still works).
  const tick = useCallback(async () => {
    await refreshJobs(true);
    const names = openLogs;
    if (!names.length) return;
    const results = await Promise.allSettled(
      names.map((n) => viewActivateLog(n).then((r) => [n, r.content] as const))
    );
    const now = new Date().toLocaleTimeString();
    setLogContent((prev) => {
      const next = { ...prev };
      results.forEach((r) => {
        if (r.status === "fulfilled") next[r.value[0]] = r.value[1];
      });
      return next;
    });
    setLogUpdated((prev) => {
      const next = { ...prev };
      results.forEach((r) => {
        if (r.status === "fulfilled") next[r.value[0]] = now;
      });
      return next;
    });
  }, [openLogs, refreshJobs]);

  useEffect(() => {
    tick(); // immediate load whenever the tab set / interval changes
    if (!autoRefresh) return;
    const id = setInterval(tick, refreshMs);
    return () => clearInterval(id);
  }, [autoRefresh, refreshMs, tick]);

  // ---------- actions ----------
  // Convert = precheck, then start. The precheck result is always shown; only
  // devices that pass it are converted, and nothing is started at all when no
  // device passes.
  const handleConvert = async () => {
    if (!selected.length) {
      message.warning("Select at least one device");
      return;
    }
    if (invalidEmails.length) {
      message.error(
        `Invalid activation email for: ${invalidEmails.join(", ")}`
      );
      return;
    }

    // --- phase 1: precheck ---
    setPrechecking(true);
    setRejected([]);
    setPrechecks([]);
    let results: ActivatePrecheck[];
    try {
      results = await precheckActivate(selected, mode);
    } catch (e) {
      message.error(`Precheck failed, conversion not started: ${(e as Error).message}`);
      setPrechecking(false);
      return;
    } finally {
      setPrechecking(false);
    }
    setPrechecks(results);

    const passed = results.filter((r) => r.allowed);
    const blocked = results.filter((r) => !r.allowed);
    setRejected(blocked);

    if (blocked.length) {
      message.warning(
        `Precheck blocked ${blocked.length} device(s) — not converted: ` +
          blocked.map((r) => r.device_name).join(", ")
      );
    }
    if (!passed.length) {
      message.error(`Precheck did not pass; conversion to ${modeLabel(mode)} was not started`);
      return;
    }

    // --- phase 2: convert the devices that passed (precheck just ran) ---
    setStarting(true);
    try {
      const res = await startActivate({
        device_names: passed.map((r) => r.device_name),
        mode,
        skip_precheck: true,
        // Connected Mode links an account; send the (possibly edited) email.
        emails:
          mode === "connected"
            ? Object.fromEntries(
                passed.map((r) => [r.device_name, (emails[r.device_name] ?? "").trim()])
              )
            : undefined,
      });
      if (res.rejected?.length) {
        setRejected((prev) => [...prev, ...res.rejected]);
      }
      if (res.started.length) {
        message.success(
          `Precheck passed — started ${res.started.length} conversion(s) to ${modeLabel(mode)}: ` +
            res.started.map((j) => j.device_name).join(", ")
        );
        const names = res.started.map((j) => j.log_file);
        setOpenLogs((prev) => [...names, ...prev.filter((n) => !names.includes(n))]);
        setActiveLog(names[0]);
      }
      refreshJobs(true);
    } catch (e) {
      message.error(`Start failed: ${(e as Error).message}`);
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async (pid: number) => {
    setStoppingPid(pid);
    try {
      await stopActivate(pid);
      message.success(`Stopped PID ${pid}`);
      refreshJobs(true);
    } catch (e) {
      message.error(`Stop failed: ${(e as Error).message}`);
    } finally {
      setStoppingPid(null);
    }
  };

  const handleDeleteJob = async (id: string) => {
    try {
      await deleteActivateJob(id);
      refreshJobs(true);
    } catch (e) {
      message.error(`Remove failed: ${(e as Error).message}`);
    }
  };

  const handleViewLog = async (logFile: string) => {
    try {
      const r = await viewActivateLog(logFile, 5000);
      setViewer({ name: logFile, content: r.content });
    } catch (e) {
      message.error(`Open log failed: ${(e as Error).message}`);
    }
  };

  // ---------- tables ----------
  const precheckColumns = [
    { title: "Device", dataIndex: "device_name", key: "device_name" },
    { title: "IP", dataIndex: "ip_address", key: "ip_address", width: 140 },
    {
      title: "Connection",
      dataIndex: "connection_type",
      key: "connection_type",
      width: 130,
      render: (v: string) =>
        v ? (
          <Tag color={/wifi|wireless|wlan/i.test(v) ? "orange" : "blue"}>{v}</Tag>
        ) : (
          "-"
        ),
    },
    {
      title: "Account Linked",
      dataIndex: "is_linked",
      key: "is_linked",
      width: 130,
      render: (v: boolean | null | undefined) =>
        v === null || v === undefined ? "-" : <Tag color={v ? "green" : "default"}>{String(v)}</Tag>,
    },
    {
      title: "Allowed",
      dataIndex: "allowed",
      key: "allowed",
      width: 100,
      render: (v: boolean) => <Tag color={v ? "success" : "error"}>{v ? "Yes" : "No"}</Tag>,
    },
    { title: "Reason", dataIndex: "reason", key: "reason", ellipsis: true },
  ];

  const jobColumns = [
    { title: "Device", dataIndex: "device_name", key: "device_name", width: 220 },
    {
      title: "Mode",
      dataIndex: "mode",
      key: "mode",
      width: 170,
      render: (m: ActivateMode) => (
        <Tag color={m === "connected" ? "blue" : "purple"}>{modeLabel(m)}</Tag>
      ),
    },
    {
      title: "Account Email",
      dataIndex: "email",
      key: "email",
      width: 220,
      ellipsis: true,
      render: (v: string) => v || "-",
    },
    { title: "PID", dataIndex: "pid", key: "pid", width: 90 },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (_: string, r: ActivateJob) => (
        <Tag color={r.running ? "processing" : "default"}>
          {r.running ? "running" : "finished"}
        </Tag>
      ),
    },
    {
      title: "Result",
      dataIndex: "result",
      key: "result",
      width: 110,
      render: (v: string) =>
        !v ? (
          "-"
        ) : (
          <Tag color={v === "Success" ? "success" : v === "Failed" ? "error" : "default"}>
            {v}
          </Tag>
        ),
    },
    { title: "Started (UTC)", dataIndex: "started_at", key: "started_at", width: 190 },
    {
      title: "Log Updated",
      dataIndex: "log_mtime",
      key: "log_mtime",
      width: 190,
      render: (v: number) => fmtTime(v),
    },
    {
      title: "Action",
      key: "action",
      width: 220,
      render: (_: unknown, r: ActivateJob) => (
        <Space size={4} wrap>
          <Button size="small" icon={<EyeOutlined />} onClick={() => handleViewLog(r.log_file)}>
            View
          </Button>
          <Popconfirm
            title={`Stop PID ${r.pid}?`}
            okText="Stop"
            okButtonProps={{ danger: true }}
            disabled={!r.running}
            onConfirm={() => handleStop(r.pid)}
          >
            <Button
              size="small"
              danger
              icon={<StopOutlined />}
              disabled={!r.running}
              loading={stoppingPid === r.pid}
            >
              Stop
            </Button>
          </Popconfirm>
          <Popconfirm
            title="Remove this job from the list?"
            okText="Remove"
            okButtonProps={{ danger: true }}
            disabled={r.running}
            onConfirm={() => handleDeleteJob(r.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} disabled={r.running}>
              Delete
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>
        Connected / Unconnected Mode
      </Title>

      {/* Conversion controls */}
      <Card style={{ marginBottom: 16 }}>
        <Space size="large" wrap align="end">
          <div style={{ minWidth: 420 }}>
            <Text strong>Devices (multiple allowed)</Text>
            <Select
              mode="multiple"
              style={{ width: "100%", marginTop: 8 }}
              placeholder="Select one or more devices"
              loading={loadingDevices}
              value={selected}
              onChange={setSelected}
              options={devices.map((d) => ({ value: d, label: d }))}
              showSearch
              optionFilterProp="label"
              allowClear
              maxTagCount="responsive"
            />
          </div>
          <div>
            <Text strong>Target Mode</Text>
            <br />
            <Radio.Group
              style={{ marginTop: 8 }}
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              optionType="button"
              buttonStyle="solid"
            >
              <Radio.Button value="connected">
                <ApiOutlined /> Connected
              </Radio.Button>
              <Radio.Button value="unconnected">
                <DisconnectOutlined /> Unconnected
              </Radio.Button>
            </Radio.Group>
          </div>
          <Popconfirm
            title={`Convert ${selected.length} device(s) to ${modeLabel(mode)}?`}
            description="A precheck runs first; each device that passes will be factory reset."
            okText="Convert"
            okButtonProps={{ danger: true }}
            disabled={!selected.length || !!invalidEmails.length}
            onConfirm={handleConvert}
          >
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={prechecking || starting}
              disabled={!selected.length || !!invalidEmails.length}
            >
              {prechecking ? "Prechecking..." : "Convert"}
            </Button>
          </Popconfirm>
        </Space>

        {/* Connected Mode links a Roku account, so each selected device shows
            its activation email (prefilled, editable) which is passed through
            to the activation script. */}
        {mode === "connected" && selected.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <Space size={6}>
              <MailOutlined />
              <Text strong>Activation Account Email</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                prefilled from config/activate_account.yml — edit to override
              </Text>
            </Space>
            <Table
              style={{ marginTop: 8, maxWidth: 760 }}
              size="small"
              rowKey="device"
              loading={loadingEmails}
              pagination={false}
              dataSource={selected.map((d) => ({ device: d }))}
              columns={[
                { title: "Device", dataIndex: "device", key: "device", width: 280 },
                {
                  title: "Email",
                  key: "email",
                  render: (_: unknown, r: { device: string }) => {
                    const value = emails[r.device] ?? "";
                    const bad = !EMAIL_RE.test(value.trim());
                    return (
                      <Input
                        size="small"
                        value={value}
                        status={bad ? "error" : undefined}
                        placeholder="account@roku.com"
                        allowClear
                        onChange={(e) =>
                          setEmails((prev) => ({ ...prev, [r.device]: e.target.value }))
                        }
                      />
                    );
                  },
                },
              ]}
            />
            {invalidEmails.length > 0 && (
              <Text type="danger" style={{ fontSize: 12 }}>
                Enter a valid email for: {invalidEmails.join(", ")}
              </Text>
            )}
          </div>
        )}

        {rejected.length > 0 && (
          <Alert
            style={{ marginTop: 12 }}
            type="warning"
            showIcon
            message={`${rejected.length} device(s) were not started`}
            description={
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {rejected.map((r) => (
                  <li key={r.device_name}>
                    <Text strong>{r.device_name}</Text>: {r.reason}
                  </li>
                ))}
              </ul>
            }
          />
        )}

        {/* The rule hint only makes sense next to a precheck result, so it
            appears and disappears together with the result table. */}
        {prechecks.length > 0 && (
          <>
            <Alert
              style={{ marginTop: 16, padding: "4px 10px", fontSize: 12 }}
              type="info"
              showIcon
              banner
              message={
                <Text style={{ fontSize: 12 }}>
                  <Text strong style={{ fontSize: 12 }}>
                    Precheck rule:
                  </Text>{" "}
                  A device connected over wireless cannot be converted to Unconnected
                  Mode (the factory reset would drop the only route to it). Switch it to
                  a wired connection first.
                </Text>
              }
            />
            <Text strong style={{ display: "block", marginTop: 16 }}>
              Precheck result
            </Text>
            <Table
              style={{ marginTop: 8 }}
              size="small"
              rowKey="device_name"
              columns={precheckColumns}
              dataSource={prechecks}
              pagination={false}
            />
          </>
        )}
      </Card>

      {/* Live logs */}
      <Card
        style={{ marginBottom: 16 }}
        title={`Live Logs (${openLogs.length})`}
        extra={
          <Space wrap>
            <Text type="secondary">Auto refresh</Text>
            <Switch checked={autoRefresh} onChange={setAutoRefresh} size="small" />
            <Select
              size="small"
              style={{ width: 90 }}
              value={refreshMs}
              onChange={setRefreshMs}
              disabled={!autoRefresh}
              options={REFRESH_OPTIONS}
            />
            <Button size="small" icon={<ReloadOutlined />} onClick={() => tick()}>
              Refresh now
            </Button>
          </Space>
        }
      >
        {openLogs.length === 0 ? (
          <Empty description="No log is being tailed. Start a conversion to see its live log here." />
        ) : (
          <Tabs
            type="editable-card"
            hideAdd
            activeKey={activeLog}
            onChange={setActiveLog}
            onEdit={(key, action) => {
              if (action !== "remove") return;
              const name = String(key);
              setOpenLogs((prev) => {
                const next = prev.filter((n) => n !== name);
                setActiveLog((cur) => (cur === name ? next[0] : cur));
                return next;
              });
            }}
            items={openLogs.map((name) => {
              const job = jobs.find((j) => j.log_file === name);
              return {
                key: name,
                label: (
                  <Space size={4}>
                    <span>{job?.device_name ?? name}</span>
                    {job?.running && <Tag color="processing">running</Tag>}
                  </Space>
                ),
                children: (
                  <LogPane
                    logFile={name}
                    content={logContent[name] ?? ""}
                    updatedAt={logUpdated[name] ?? ""}
                  />
                ),
              };
            })}
          />
        )}
      </Card>

      {/* Jobs */}
      <Card
        title={`Conversion Jobs (${jobs.length}${runningJobs.length ? `, ${runningJobs.length} running` : ""})`}
        extra={
          <Button size="small" icon={<ReloadOutlined />} onClick={() => refreshJobs()}>
            Refresh
          </Button>
        }
      >
        <Table
          size="small"
          rowKey="id"
          loading={loadingJobs}
          columns={jobColumns}
          dataSource={jobs}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          scroll={{ x: 1520 }}
        />
      </Card>

      {/* Full log viewer */}
      <Modal
        title={viewer?.name}
        open={!!viewer}
        onCancel={() => setViewer(null)}
        footer={null}
        width="80%"
      >
        <pre
          style={{
            margin: 0,
            padding: 12,
            background: "#1e1e1e",
            color: "#00b000",
            borderRadius: 6,
            maxHeight: "70vh",
            overflow: "auto",
            fontFamily: "monospace",
            fontSize: 13,
            whiteSpace: "pre-wrap",
          }}
        >
          {viewer?.content ? renderLog(viewer.content) : "(log is empty)"}
        </pre>
      </Modal>
    </div>
  );
}
