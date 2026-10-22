import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  PlayCircleOutlined,
  ReloadOutlined,
  EyeOutlined,
  DeleteOutlined,
  ExperimentOutlined,
  SaveOutlined,
  CopyOutlined,
} from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  listDevices,
  runRokuTest,
  getRokuTestStatus,
  listRokuTestLogs,
  viewRokuTestLog,
  deleteRokuTestLog,
  agentAnalyze,
  getAnalyzeConfig,
  basename,
  listBranches,
  getCurrentBranch,
  checkoutBranch,
  type RokuTestLog,
  type AnalyzeLocale,
} from "../api/client";

const { Title, Text } = Typography;

const POLL_MS = 5000; // poll status/{pid} every 5 seconds
const LOG_POLL_MS = 3000; // refresh running log content every 3 seconds

// Lines matching this are error lines and get highlighted red.
const ERROR_RE = /\b(ERROR|Traceback|FAIL|Exception|AssertionError|res: (Fail|Error))\b/;
const WARNING_RE = /\b(WARNING|WARN)\b/;

// Render log content line-by-line, highlighting error lines in red.
function renderLog(content: string) {
  if (!content) return null;
  return content.split("\n").map((line, i) => {
    const cls = ERROR_RE.test(line) ? "err" : WARNING_RE.test(line) ? "warn" : "";
    return (
      <div
        key={i}
        style={
          cls === "err"
            ? { color: "#ff5c5c", fontWeight: 600, background: "rgba(255,0,0,0.12)" }
            : cls === "warn"
            ? { color: "#ffb020", fontWeight: 600, background: "rgba(255,176,32,0.12)" }
            : undefined
        }
      >
        {line || " "}
      </div>
    );
  });
}

interface ActiveRun {
  pid: number;
  command: string;
  logName: string; // basename of log_file
  status: string; // running | not_running | ...
}

// Log name rule (fields are "__"-delimited, so each may itself contain single
// underscores without ambiguity):
//   roku_test__{automation_id}__{testrail_case_id}__{device}__{repeat}__{timestamp}.log
// where timestamp = YYYYMMDD_HHMMSS.
//
// Older logs were written device-first
//   (roku_test__{device}__{automation_id}__{testrail_case_id}__{repeat}__{timestamp}),
// so rather than trust positions we anchor on the known device list to find the
// device field, then disambiguate the remaining two (testrail_case_id is purely
// numeric, automation_id is the other) — works for both orderings.
function parseLogName(
  name: string,
  knownDevices: string[]
): {
  device: string;
  automationId: string;
  testrailCaseId: string;
  date: string;
} | null {
  const base = name.replace(/\.log$/i, "");
  if (!base.startsWith("roku_test__")) return null;
  const parts = base.slice("roku_test__".length).split("__");
  // Expect 5 fields: {device, automation_id, testrail_case_id} + repeat + timestamp.
  if (parts.length < 5) return null;

  const timestamp = parts[parts.length - 1];
  const raw = (timestamp.match(/^(\d{8})_\d{6}$/) || [])[1] || "";
  const date = raw
    ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`
    : "";

  // The three identity fields are everything before repeat + timestamp.
  const ids = parts.slice(0, parts.length - 2);

  // Locate the device by matching the known device list (exact match).
  const deviceSet = new Set(knownDevices);
  let deviceIdx = ids.findIndex((p) => deviceSet.has(p));
  // Fallback for an unknown/renamed device: assume automation-first layout where
  // the device sits in the 3rd id slot.
  if (deviceIdx === -1) deviceIdx = Math.min(2, ids.length - 1);
  const device = ids[deviceIdx];

  // Of the remaining two, the purely-numeric one is the testrail_case_id.
  const rest = ids.filter((_, i) => i !== deviceIdx);
  let automationId = "";
  let testrailCaseId = "";
  if (rest.length === 2) {
    const [a, b] = rest;
    if (/^\d+$/.test(b)) {
      automationId = a;
      testrailCaseId = b;
    } else if (/^\d+$/.test(a)) {
      automationId = b;
      testrailCaseId = a;
    } else {
      [automationId, testrailCaseId] = [a, b];
    }
  } else if (rest.length === 1) {
    automationId = rest[0];
  }

  return { device, automationId, testrailCaseId, date };
}

export default function RokuTestPage() {
  const [devices, setDevices] = useState<string[]>([]);
  const [device, setDevice] = useState<string>();
  const [automationId, setAutomationId] = useState<string>("");
  const [testrailCaseId, setTestrailCaseId] = useState<string>("");
  const [repeat, setRepeat] = useState<number>(0);
  const [loadingDevices, setLoadingDevices] = useState(false);
  const [running, setRunning] = useState(false);

  // automated_tests git branch
  const [branches, setBranches] = useState<string[]>([]);
  const [branch, setBranch] = useState<string>();
  const [loadingBranches, setLoadingBranches] = useState(false);
  const [checkingOut, setCheckingOut] = useState(false);

  const [logs, setLogs] = useState<RokuTestLog[]>([]);
  const [loadingLogs, setLoadingLogs] = useState(false);

  // Filters for the log list
  const [filterDevice, setFilterDevice] = useState<string>();
  const [filterAutomationId, setFilterAutomationId] = useState<string>();
  const [filterTestrailCaseId, setFilterTestrailCaseId] = useState<string>();
  const [filterResult, setFilterResult] = useState<string>();
  const [filterDate, setFilterDate] = useState<string>();

  // The test launched from this page — tracked by pid via status polling.
  const [active, setActive] = useState<ActiveRun | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string>("");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Live tail of the running test's log, shown under the Run button.
  const [liveLog, setLiveLog] = useState<string>("");
  const [liveLogUpdated, setLiveLogUpdated] = useState<string>("");
  const logTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const liveLogRef = useRef<HTMLPreElement>(null);

  // Auto-scroll the live log to the bottom whenever it updates.
  useEffect(() => {
    const el = liveLogRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [liveLog]);

  const [viewer, setViewer] = useState<{ name: string; content: string } | null>(null);

  // Log analysis modal (AI summary of a log file)
  const [analyzeOpen, setAnalyzeOpen] = useState(false);
  const [analyzeName, setAnalyzeName] = useState("");
  const [analyzeResult, setAnalyzeResult] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeLocale, setAnalyzeLocale] = useState<AnalyzeLocale>("en-US");
  // Configured default Analyze locale (from Settings); used when opening Analyze.
  const defaultLocaleRef = useRef<AnalyzeLocale>("en-US");
  // Cache the fetched log content so a language switch re-analyzes without refetching.
  const analyzeContentRef = useRef<string>("");
  // automation id / testrail case id for the log being analyzed (sent to the
  // analyze API as case_id / testrail_case_id).
  const analyzeCaseRef = useRef<string>("");
  const analyzeTestrailRef = useRef<string>("");
  const analyzeResultRef = useRef<string>("");

  // Load the configured default Analyze locale (set in Settings).
  useEffect(() => {
    getAnalyzeConfig()
      .then((c) => {
        defaultLocaleRef.current = c.default_locale;
        setAnalyzeLocale(c.default_locale);
      })
      .catch(() => {
        /* keep the en-US fallback if config can't be read */
      });
  }, []);

  // Load devices for the dropdown.
  useEffect(() => {
    setLoadingDevices(true);
    listDevices()
      .then(setDevices)
      .catch((e: Error) => message.error(`Load devices failed: ${e.message}`))
      .finally(() => setLoadingDevices(false));
  }, []);

  // Load branches + current branch for the automated_tests repo.
  const loadBranches = () => {
    setLoadingBranches(true);
    Promise.all([listBranches(), getCurrentBranch()])
      .then(([list, current]) => {
        setBranches(list);
        setBranch(current || undefined);
      })
      .catch((e: Error) => message.error(`Load branches failed: ${e.message}`))
      .finally(() => setLoadingBranches(false));
  };
  useEffect(loadBranches, []);

  const handleCheckout = async (name: string) => {
    setCheckingOut(true);
    try {
      await checkoutBranch(name);
      setBranch(name);
      message.success(`Checked out branch: ${name}`);
    } catch (e) {
      message.error(`Checkout failed: ${(e as Error).message}`);
      loadBranches(); // resync to actual current branch on failure
    } finally {
      setCheckingOut(false);
    }
  };

  const refreshLogs = async () => {
    setLoadingLogs(true);
    try {
      setLogs(await listRokuTestLogs());
    } catch (e) {
      message.error(`Load logs failed: ${(e as Error).message}`);
    } finally {
      setLoadingLogs(false);
    }
  };

  useEffect(() => {
    refreshLogs();
  }, []);

  // Poll /v1/rokutest/status/{pid} every 5s for the active run.
  useEffect(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (!active) return;

    const tick = async () => {
      try {
        const st = await getRokuTestStatus(active.pid);
        setLastUpdated(new Date().toLocaleTimeString());
        setActive((prev) => (prev ? { ...prev, status: st.status } : prev));
        refreshLogs();
        // Stop polling once the process is no longer running.
        if (st.status !== "running" && timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = null;
        }
      } catch {
        /* keep polling on transient errors */
      }
    };

    tick();
    timerRef.current = setInterval(tick, POLL_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.pid]);

  // The log to live-tail: the run launched here while still running, otherwise
  // (e.g. after a page refresh) the first log the backend reports as 'running'.
  const runningLogName =
    active && active.status === "running"
      ? active.logName
      : logs.find((l) => l.state === "running")?.name;

  // While some test is 'running', refresh its log content every 3s and show it
  // under the Run button. Survives page refresh / re-entry (driven by the log
  // list's running state, not just the in-page active run).
  useEffect(() => {
    if (logTimerRef.current) {
      clearInterval(logTimerRef.current);
      logTimerRef.current = null;
    }
    if (!runningLogName) return;

    const pullLog = async () => {
      try {
        const content = await viewRokuTestLog(runningLogName);
        setLiveLog(content);
        setLiveLogUpdated(new Date().toLocaleTimeString());
      } catch {
        /* keep trying; log file may not be written yet */
      }
    };

    pullLog();
    logTimerRef.current = setInterval(() => {
      pullLog();
      // also refresh the log list so running -> completed is detected even after
      // a page refresh (when the pid-based status poll isn't active).
      if (!active) refreshLogs();
    }, LOG_POLL_MS);
    return () => {
      if (logTimerRef.current) clearInterval(logTimerRef.current);
      logTimerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runningLogName]);

  // Run is only enabled once every input (device, automation id, testrail case
  // id) has a value — enforced both here and on the button's disabled state.
  const canRun =
    !!device && !!automationId.trim() && !!testrailCaseId.trim();

  const handleRun = async () => {
    if (!canRun) {
      message.warning("Please fill in device, automation id and testrail case id");
      return;
    }
    setRunning(true);
    try {
      const res = await runRokuTest(
        device!,
        automationId.trim(),
        testrailCaseId.trim(),
        repeat
      );
      message.success(`${res.message} (pid ${res.pid})`);
      setLiveLog("");
      setLiveLogUpdated("");
      setActive({
        pid: res.pid,
        command: res.command,
        logName: basename(res.log_file),
        status: "running",
      });
      refreshLogs();
    } catch (e) {
      message.error(`Run failed: ${(e as Error).message}`);
    } finally {
      setRunning(false);
    }
  };

  const openLog = async (name: string) => {
    try {
      const content = await viewRokuTestLog(name);
      setViewer({ name, content });
    } catch (e) {
      message.error(`View failed: ${(e as Error).message}`);
    }
  };

  // Run the analysis over cached log content for a given locale.
  const runAnalyze = async (content: string, locale: "zh-CN" | "en-US") => {
    if (!content.trim()) {
      setAnalyzeResult("_(log is empty — nothing to analyze)_");
      return;
    }
    setAnalyzing(true);
    try {
      const res = await agentAnalyze(
        content,
        locale,
        false,
        analyzeCaseRef.current || undefined,
        undefined,
        analyzeResultRef.current || undefined,
        analyzeTestrailRef.current || undefined,
        // Local runs aren't profile-driven; tag them "local" so they're
        // distinguishable in the Analyze History Profile column/filter.
        "local"
      );
      setAnalyzeResult(res.response);
    } catch (e) {
      message.error(`Analyze failed: ${(e as Error).message}`);
    } finally {
      setAnalyzing(false);
    }
  };

  // Normalize a "bdd-<digits>" automation id to just the digits for the
  // analyze-history case_id; otherwise pass the automation id through as-is.
  const normalizeCaseId = (automationId: string): string => {
    const bdd = automationId.match(/^bdd-(\d+)$/i);
    return bdd ? bdd[1] : automationId;
  };

  const handleAnalyzeLog = async (name: string, testResult?: string) => {
    setAnalyzeName(name);
    setAnalyzeResult("");
    // Use the configured default Analyze locale.
    const locale = defaultLocaleRef.current;
    setAnalyzeLocale(locale);
    setAnalyzeOpen(true);
    setAnalyzing(true);
    const parsed = parseLogName(name, devices);
    analyzeCaseRef.current = parsed ? normalizeCaseId(parsed.automationId) : "";
    analyzeTestrailRef.current = parsed?.testrailCaseId || "";
    analyzeResultRef.current = testResult || "";
    try {
      const content = await viewRokuTestLog(name);
      analyzeContentRef.current = content;
      await runAnalyze(content, locale);
    } catch (e) {
      message.error(`Analyze failed: ${(e as Error).message}`);
      setAnalyzeOpen(false);
      setAnalyzing(false);
    }
  };

  // Toggle language and re-analyze the cached log content in that locale.
  const switchAnalyzeLocale = (locale: "zh-CN" | "en-US") => {
    if (locale === analyzeLocale || analyzing) return;
    setAnalyzeLocale(locale);
    setAnalyzeResult("");
    runAnalyze(analyzeContentRef.current, locale);
  };

  const handleSaveAnalysis = async () => {
    if (!analyzeResult) return;
    const base = analyzeName.replace(/\.[^.]+$/, "") || "log";
    const suggestedName = `${base}-analysis.md`;
    const picker = (window as unknown as {
      showSaveFilePicker?: (opts: unknown) => Promise<{
        createWritable: () => Promise<{
          write: (data: BlobPart) => Promise<void>;
          close: () => Promise<void>;
        }>;
      }>;
    }).showSaveFilePicker;
    if (picker) {
      try {
        const handle = await picker({
          suggestedName,
          types: [{ description: "Markdown", accept: { "text/markdown": [".md"] } }],
        });
        const writable = await handle.createWritable();
        await writable.write(analyzeResult);
        await writable.close();
        message.success("Saved");
      } catch (e) {
        if ((e as Error).name !== "AbortError") {
          message.error(`Save failed: ${(e as Error).message}`);
        }
      }
      return;
    }
    const blob = new Blob([analyzeResult], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = suggestedName;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleCopyAnalysis = async () => {
    if (!analyzeResult) return;
    try {
      await navigator.clipboard.writeText(analyzeResult);
      message.success("Copied");
    } catch {
      // Fallback for non-secure (http) contexts without the clipboard API.
      const ta = document.createElement("textarea");
      ta.value = analyzeResult;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        message.success("Copied");
      } catch {
        message.error("Copy failed");
      }
      document.body.removeChild(ta);
    }
  };

  const handleDeleteLog = async (name: string) => {
    try {
      const res = await deleteRokuTestLog(name);
      message.success(res.message);
      refreshLogs();
    } catch (e) {
      message.error(`Delete failed: ${(e as Error).message}`);
    }
  };

  // Row state: the active run's log is driven by pid status
  // (running -> running, not_running -> completed); others use backend state.
  const displayState = (r: RokuTestLog): "running" | "completed" => {
    if (active && r.name === active.logName) {
      return active.status === "running" ? "running" : "completed";
    }
    return r.state;
  };

  // Parse each log once; build filter option lists and apply the active filters.
  const parsedLogs = logs.map((l) => ({ ...l, parsed: parseLogName(l.name, devices) }));
  const deviceOptions = Array.from(
    new Set(parsedLogs.map((l) => l.parsed?.device).filter(Boolean) as string[])
  ).sort();
  const automationIdOptions = Array.from(
    new Set(
      parsedLogs
        .filter((l) => !filterDevice || l.parsed?.device === filterDevice)
        .map((l) => l.parsed?.automationId)
        .filter(Boolean) as string[]
    )
  ).sort();
  // Auto-size the automation-id filter to its longest option (~8px/char + padding).
  const longestAutomationId = automationIdOptions.reduce(
    (m, c) => Math.max(m, c.length),
    0
  );
  const automationIdSelectWidth = Math.min(
    Math.max(260, longestAutomationId * 8 + 60),
    560
  );
  const testrailCaseIdOptions = Array.from(
    new Set(
      parsedLogs
        .filter((l) => !filterDevice || l.parsed?.device === filterDevice)
        .map((l) => l.parsed?.testrailCaseId)
        .filter(Boolean) as string[]
    )
  ).sort();
  const dateOptions = Array.from(
    new Set(parsedLogs.map((l) => l.parsed?.date).filter(Boolean) as string[])
  ).sort((a, b) => b.localeCompare(a)); // newest first
  const filteredLogs = parsedLogs.filter(
    (l) =>
      (!filterDevice || l.parsed?.device === filterDevice) &&
      (!filterAutomationId || l.parsed?.automationId === filterAutomationId) &&
      (!filterTestrailCaseId ||
        l.parsed?.testrailCaseId === filterTestrailCaseId) &&
      (!filterResult || l.result === filterResult) &&
      (!filterDate || l.parsed?.date === filterDate)
  );

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>
        Roku Test
      </Title>

      {/* Run controls */}
      <Card style={{ marginBottom: 16 }}>
        <Space size="large" wrap align="end">
          <div style={{ minWidth: 320 }}>
            <Text strong>Branch (automated_tests)</Text>
            <Select
              style={{ width: "100%", marginTop: 8 }}
              placeholder="Select a branch"
              loading={loadingBranches || checkingOut}
              value={branch}
              onChange={handleCheckout}
              options={branches.map((b) => ({ value: b, label: b }))}
              showSearch
              optionFilterProp="label"
              popupMatchSelectWidth={false}
            />
          </div>
          <div style={{ minWidth: 240 }}>
            <Text strong>Device</Text>
            <Select
              style={{ width: "100%", marginTop: 8 }}
              placeholder="Select a device"
              loading={loadingDevices}
              value={device}
              onChange={setDevice}
              options={devices.map((d) => ({ value: d, label: d }))}
              showSearch
              optionFilterProp="label"
              allowClear
            />
          </div>
          <div style={{ minWidth: 420 }}>
            <Text strong>Automation ID</Text>
            <Input
              style={{ marginTop: 8 }}
              placeholder="e.g. bdd-2659886031 or a UT automation id"
              value={automationId}
              onChange={(e) => setAutomationId(e.target.value)}
              onPressEnter={handleRun}
              allowClear
            />
          </div>
          <div style={{ minWidth: 220 }}>
            <Text strong>TestRail Case ID</Text>
            <Input
              style={{ marginTop: 8 }}
              placeholder="e.g. 2294354569"
              value={testrailCaseId}
              onChange={(e) => setTestrailCaseId(e.target.value)}
              onPressEnter={handleRun}
              allowClear
            />
          </div>
          <div>
            <Text strong>Repeat</Text>
            <br />
            <InputNumber
              style={{ marginTop: 8, width: 100 }}
              min={0}
              value={repeat}
              onChange={(v) => setRepeat(v ?? 0)}
            />
          </div>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={running}
            disabled={!canRun}
            onClick={handleRun}
          >
            Run
          </Button>
        </Space>

        {/* Full command + pid + live status after a run */}
        {active && (
          <Alert
            style={{ marginTop: 16 }}
            type={active.status === "running" ? "info" : "success"}
            message={
              <Space wrap>
                <span>
                  PID <Text strong>{active.pid}</Text>
                </span>
                <Tag color={active.status === "running" ? "processing" : "success"}>
                  {active.status === "running" ? "running" : "completed"}
                </Tag>
                {lastUpdated && <Text type="secondary">polled {lastUpdated}</Text>}
              </Space>
            }
            description={
              <Text code style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>
                {active.command}
              </Text>
            }
          />
        )}

        {/* Live log tail of the running test, refreshed every 3s. Also shows
            after a page refresh if the backend reports a running log. */}
        {runningLogName && (
          <div style={{ marginTop: 16 }}>
            <Space style={{ marginBottom: 8 }}>
              <Text strong>Live log: {runningLogName}</Text>
              {liveLogUpdated && (
                <Text type="secondary">refreshed {liveLogUpdated}</Text>
              )}
            </Space>
            <pre
              ref={liveLogRef}
              style={{
                margin: 0,
                padding: 12,
                background: "#1e1e1e",
                color: "#00b000",
                borderRadius: 6,
                minHeight: 240,
                maxHeight: 630,
                overflow: "auto",
                fontFamily: "monospace",
                fontSize: 12,
                lineHeight: 0.9,
                whiteSpace: "pre-wrap",
              }}
            >
              {liveLog ? renderLog(liveLog) : "(waiting for log output...)"}
            </pre>
          </div>
        )}
      </Card>

      {/* Log list */}
      <Card
        title={`Test Logs (${filteredLogs.length})`}
        extra={
          <Button size="small" icon={<ReloadOutlined />} onClick={refreshLogs}>
            Refresh
          </Button>
        }
      >
        <Space style={{ marginBottom: 16 }} wrap>
          <Select
            style={{ width: 260 }}
            placeholder="Filter by device"
            value={filterDevice}
            onChange={(v) => {
              setFilterDevice(v);
              // reset id filters when device changes
              setFilterAutomationId(undefined);
              setFilterTestrailCaseId(undefined);
            }}
            options={deviceOptions.map((d) => ({ value: d, label: d }))}
            showSearch
            optionFilterProp="label"
            allowClear
          />
          <Select
            style={{ width: automationIdSelectWidth }}
            placeholder="Filter by automation id"
            value={filterAutomationId}
            onChange={setFilterAutomationId}
            options={automationIdOptions.map((c) => ({ value: c, label: c }))}
            popupMatchSelectWidth={false}
            showSearch
            optionFilterProp="label"
            allowClear
          />
          <Select
            style={{ width: 220 }}
            placeholder="Filter by testrail case id"
            value={filterTestrailCaseId}
            onChange={setFilterTestrailCaseId}
            options={testrailCaseIdOptions.map((c) => ({ value: c, label: c }))}
            popupMatchSelectWidth={false}
            showSearch
            optionFilterProp="label"
            allowClear
          />
          <Select
            style={{ width: 160 }}
            placeholder="Filter by result"
            value={filterResult}
            onChange={setFilterResult}
            options={["Pass", "Fail", "Skipped", "Blocked", "Unknown"].map((r) => ({ value: r, label: r }))}
            allowClear
          />
          <Select
            style={{ width: 180 }}
            placeholder="Filter by date"
            value={filterDate}
            onChange={setFilterDate}
            options={dateOptions.map((d) => ({ value: d, label: d }))}
            showSearch
            optionFilterProp="label"
            allowClear
          />
        </Space>
        <Table<RokuTestLog>
          size="small"
          rowKey="name"
          loading={loadingLogs}
          dataSource={filteredLogs}
          pagination={{
            defaultPageSize: 15,
            pageSizeOptions: [10, 15, 30, 50],
            showSizeChanger: true,
          }}
          columns={[
            {
              title: "Log File",
              dataIndex: "name",
              key: "name",
              ellipsis: true,
              sorter: (a: RokuTestLog, b: RokuTestLog) => a.name.localeCompare(b.name),
              sortDirections: ["ascend", "descend"],
            },
            {
              title: "State",
              key: "state",
              width: 130,
              render: (_: unknown, r: RokuTestLog) => {
                const s = displayState(r);
                return <Tag color={s === "running" ? "processing" : "success"}>{s}</Tag>;
              },
            },
            {
              title: "Result",
              dataIndex: "result",
              key: "result",
              width: 120,
              render: (res: RokuTestLog["result"]) => {
                const color =
                  res === "Pass"
                    ? "success"
                    : res === "Fail"
                    ? "error"
                    : res === "Skipped"
                    ? "warning"
                    : res === "Blocked"
                    ? "volcano"
                    : "default";
                return <Tag color={color}>{res}</Tag>;
              },
            },
            {
              title: "Action",
              key: "action",
              width: 280,
              render: (_: unknown, r: RokuTestLog) => (
                <Space>
                  <Button
                    size="small"
                    icon={<EyeOutlined />}
                    onClick={() => openLog(r.name)}
                  >
                    View
                  </Button>
                  <Button
                    type="primary"
                    size="small"
                    icon={<ExperimentOutlined />}
                    disabled={r.result === "Pass"}
                    onClick={() => handleAnalyzeLog(r.name, r.result)}
                  >
                    Analyze
                  </Button>
                  <Popconfirm
                    title="Delete this log file?"
                    okText="Delete"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => handleDeleteLog(r.name)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />}>
                      Delete
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      {/* Log content viewer */}
      <Modal
        title={viewer?.name}
        open={!!viewer}
        onCancel={() => setViewer(null)}
        footer={null}
        width="90vw"
        style={{ top: 24, maxWidth: 1400 }}
      >
        <pre
          style={{
            margin: 0,
            padding: 12,
            background: "#1e1e1e",
            color: "#00b000",
            borderRadius: 6,
            minHeight: 200,
            maxHeight: "80vh",
            overflow: "auto",
            fontFamily: "monospace",
            fontSize: 12,
            lineHeight: 0.9,
            whiteSpace: "pre-wrap",
          }}
        >
          {viewer?.content ? renderLog(viewer.content) : "(log is empty)"}
        </pre>
      </Modal>

      {/* AI log analysis */}
      <Modal
        title={`Analyze: ${analyzeName}`}
        open={analyzeOpen}
        onCancel={() => setAnalyzeOpen(false)}
        width="fit-content"
        style={{ top: 24 }}
        styles={{ body: { maxHeight: "70vh", overflow: "auto" } }}
        footer={
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <Segmented
              value={analyzeLocale}
              onChange={(v) => switchAnalyzeLocale(v as "zh-CN" | "en-US")}
              disabled={analyzing}
              options={[
                { label: "中文", value: "zh-CN" },
                { label: "English", value: "en-US" },
              ]}
            />
            <Space>
              <Button
                icon={<SaveOutlined />}
                disabled={!analyzeResult || analyzing}
                onClick={handleSaveAnalysis}
              >
                Save
              </Button>
              <Button
                icon={<CopyOutlined />}
                disabled={!analyzeResult || analyzing}
                onClick={handleCopyAnalysis}
              >
                Copy
              </Button>
              <Button type="primary" onClick={() => setAnalyzeOpen(false)}>
                Close
              </Button>
            </Space>
          </div>
        }
      >
        <div
          className="chat-markdown"
          style={{ minWidth: 360, maxWidth: "80vw", minHeight: 120 }}
        >
          {analyzing ? (
            <Text type="secondary">Analyzing log…</Text>
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{analyzeResult}</ReactMarkdown>
          )}
        </div>
      </Modal>
    </div>
  );
}
