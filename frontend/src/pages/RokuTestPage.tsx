import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Empty,
  InputNumber,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
  Tooltip,
} from "antd";
import {
  PlayCircleOutlined,
  ReloadOutlined,
  EyeOutlined,
  DeleteOutlined,
  DownloadOutlined,
  ClearOutlined,
  ExperimentOutlined,
  SaveOutlined,
  CopyOutlined,
  StopOutlined,
  PlusOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
} from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  listDevices,
  runRokuTest,
  listRokuTestCache,
  deleteRokuTestCache,
  listRokuTestJobs,
  stopRokuTestJob,
  deleteRokuTestJob,
  clearRokuTestJobs,
  listRokuTestQueues,
  moveRokuTestQueueJob,
  clearRokuTestQueue,
  listRokuTestLogs,
  viewRokuTestLog,
  deleteRokuTestLog,
  rokuTestLogDownloadUrl,
  agentAnalyze,
  getAnalyzeConfig,
  basename,
  listBranches,
  getCurrentBranch,
  checkoutBranch,
  type RokuTestLog,
  type RokuTestJob,
  type RokuTestQueue,
  type AnalyzeLocale,
} from "../api/client";

const { Title, Text } = Typography;

// Auto-refresh interval options (ms) for the live-log tabs + job list.
const REFRESH_OPTIONS = [
  { label: "1s", value: 1000 },
  { label: "2s", value: 2000 },
  { label: "3s", value: 3000 },
  { label: "5s", value: 5000 },
  { label: "10s", value: 10000 },
  { label: "30s", value: 30000 },
  { label: "60s", value: 60000 },
];
const DEFAULT_REFRESH_MS = 3000;
const REFRESH_STORAGE_KEY = "rokutest-log-refresh";

/** Which rows the merged Cases table shows. */
type CaseView = "active" | "finished" | "all";

// Lines matching this are error lines and get highlighted red.
const ERROR_RE = /\b(ERROR|Traceback|FAIL|Exception|AssertionError|res: (Fail|Error))\b/;
const WARNING_RE = /\b(WARNING|WARN)\b/;

/** Result may be a single status or a composite like "Fail 1,Pass 2". */
function resultParts(res: string | undefined | null): string[] {
  if (!res) return [];
  return res.split(",").map((s) => s.trim()).filter(Boolean);
}

function resultPartColor(part: string): string {
  if (/^Pass\b/i.test(part)) return "success";
  if (/^Fail\b/i.test(part)) return "error";
  if (/^Skipped\b/i.test(part)) return "warning";
  if (/^Blocked\b/i.test(part)) return "volcano";
  return "default";
}

/** True when the run is pure Pass (no Fail/Blocked/Skipped/Unknown). */
function isPurePassResult(res: string | undefined | null): boolean {
  const parts = resultParts(res);
  return parts.length > 0 && parts.every((p) => /^Pass\b/i.test(p));
}

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

// Seconds -> compact "1h 02m 03s" / "12m 03s" / "45s".
function formatElapsed(sec?: number | null): string {
  if (!sec || sec <= 0) return "-";
  const total = Math.round(sec);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
  if (m) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

/** One live-tailing log pane (one per running roku_test job tab). */
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

  // Always jump to the bottom on every refresh so the newest log output is
  // visible without scrolling. Also re-sticks when switching between tabs
  // (the pane is re-measured after the content is painted).
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const toBottom = () => {
      el.scrollTop = el.scrollHeight;
    };
    toBottom();
    // The <pre> height settles one frame later on the first paint / tab switch.
    const raf = requestAnimationFrame(toBottom);
    return () => cancelAnimationFrame(raf);
  }, [content, logFile]);

  return (
    <div>
      <Space style={{ marginBottom: 8 }} wrap>
        <Text strong>{logFile}</Text>
        {updatedAt && <Text type="secondary">refreshed {updatedAt}</Text>}
      </Space>
      <pre
        ref={ref}
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
          fontSize: 14,
          lineHeight: 1.3,
          whiteSpace: "pre-wrap",
        }}
      >
        {content ? renderLog(content) : "(waiting for log output...)"}
      </pre>
    </div>
  );
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
  // Input history (from config.yml roku_test_cache_data), shown as dropdowns.
  const [automationIdHistory, setAutomationIdHistory] = useState<string[]>([]);
  const [testrailCaseIdHistory, setTestrailCaseIdHistory] = useState<string[]>([]);
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

  // All tracked roku_test runs (backend/conf/roku_test_jobs.json). Every device
  // has its own queue and runs ONE case at a time (different devices run in
  // parallel); each running case gets its own live-log tab and Stop button.
  const [jobs, setJobs] = useState<RokuTestJob[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [clearingJobs, setClearingJobs] = useState(false);

  // Per-device queues (GET /v1/rokutest/queues), used to group the Cases table.
  const [queues, setQueues] = useState<RokuTestQueue[]>([]);
  const [queueBusyId, setQueueBusyId] = useState<string | null>(null);
  const [clearingQueue, setClearingQueue] = useState<string | null>(null);

  // Which slice of the merged Cases table to show. Active = queued + running
  // (grouped per device), so the queue is readable without the finished noise.
  const [caseView, setCaseView] = useState<CaseView>("active");

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
    return raw
      ? Number(JSON.parse(raw).interval) || DEFAULT_REFRESH_MS
      : DEFAULT_REFRESH_MS;
  });
  useEffect(() => {
    localStorage.setItem(
      REFRESH_STORAGE_KEY,
      JSON.stringify({ enabled: autoRefresh, interval: refreshMs })
    );
  }, [autoRefresh, refreshMs]);

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

  // Load the Automation ID / TestRail Case ID input history.
  useEffect(() => {
    listRokuTestCache("automation_id").then(setAutomationIdHistory).catch(() => {});
    listRokuTestCache("testrail_case_id").then(setTestrailCaseIdHistory).catch(() => {});
  }, []);

  // Delete one saved value from a history dropdown.
  const handleDeleteAutomationId = async (value: string) => {
    try {
      setAutomationIdHistory(await deleteRokuTestCache("automation_id", value));
      message.success(`Removed "${value}"`);
    } catch (e) {
      message.error(`Remove failed: ${(e as Error).message}`);
    }
  };
  const handleDeleteTestrailCaseId = async (value: string) => {
    try {
      setTestrailCaseIdHistory(await deleteRokuTestCache("testrail_case_id", value));
      message.success(`Removed "${value}"`);
    } catch (e) {
      message.error(`Remove failed: ${(e as Error).message}`);
    }
  };

  // Build AutoComplete options with a delete icon per entry.
  const historyOptions = (values: string[], onDelete: (v: string) => void) =>
    values.map((v) => ({
      value: v,
      label: (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{v}</span>
          <Popconfirm
            title={`Remove "${v}" from history?`}
            okText="Remove"
            okButtonProps={{ danger: true }}
            onConfirm={() => onDelete(v)}
          >
            <DeleteOutlined
              style={{ color: "#999", marginLeft: 8 }}
              onClick={(e) => {
                e.stopPropagation();
                e.preventDefault();
              }}
              onMouseDown={(e) => e.stopPropagation()}
            />
          </Popconfirm>
        </div>
      ),
    }));

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
    // A run reads its test files from the shared automated_tests tree, so the
    // branch must stay put while a case is executing (the backend also
    // enforces this with a 409).
    if (branchLocked) {
      message.warning(
        "A case is running — wait for it to finish or stop it before switching branch"
      );
      return;
    }
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

  // `silent` is used by the background pollers: showing the Table's loading
  // mask every few seconds swallowed clicks on the View / Delete buttons.
  const refreshLogs = async (silent = false) => {
    if (!silent) setLoadingLogs(true);
    try {
      setLogs(await listRokuTestLogs());
    } catch (e) {
      if (!silent) message.error(`Load logs failed: ${(e as Error).message}`);
    } finally {
      if (!silent) setLoadingLogs(false);
    }
  };

  useEffect(() => {
    refreshLogs();
  }, []);

  // ---------- jobs + live log tabs ----------
  const refreshJobs = useCallback(async (silent = false) => {
    if (!silent) setLoadingJobs(true);
    try {
      const [jobList, queueList] = await Promise.all([
        listRokuTestJobs(),
        listRokuTestQueues(),
      ]);
      setJobs(jobList);
      setQueues(queueList);
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
  // The branch is shared by every run (one automated_tests working tree), so it
  // is locked as soon as any case is executing. Queued cases do NOT lock it:
  // they run on whatever branch is checked out when their turn comes.
  const branchLocked = runningJobs.length > 0;
  const queuedJobs = useMemo(
    () => jobs.filter((j) => j.status === "queued"),
    [jobs]
  );
  // Jobs that can be dropped from the list (queued ones are cancelled instead).
  const finishedJobCount = useMemo(
    () => jobs.filter((j) => !j.running && j.status !== "queued").length,
    [jobs]
  );
  // Cases already lined up for the device selected above, so the Run button can
  // say whether this one starts now or joins the queue.
  const selectedDeviceQueue = useMemo(
    () => queues.find((q) => q.device === device),
    [queues, device]
  );
  const selectedDeviceBusy = !!(
    selectedDeviceQueue?.running || selectedDeviceQueue?.pending
  );

  // ---------- merged Cases table ----------
  // Active rows come from the per-device queues so each device's cases stay
  // together and in execution order: running first, then its waiting cases.
  const activeRows = useMemo(
    () =>
      queues.flatMap((q) => [...(q.running ? [q.running] : []), ...q.queued]),
    [queues]
  );
  const finishedRows = useMemo(
    () => jobs.filter((j) => !j.running && j.status !== "queued"),
    [jobs]
  );
  const caseRows = useMemo(() => {
    if (caseView === "active") return activeRows;
    if (caseView === "finished") return finishedRows;
    return [...activeRows, ...finishedRows]; // active on top, history below
  }, [caseView, activeRows, finishedRows]);

  // device -> { first row id, waiting count } so only the first row of a device
  // prints its name + queue controls (the rest are indented continuations).
  const deviceGroups = useMemo(() => {
    const map: Record<string, { firstId: string; pending: number }> = {};
    caseRows.forEach((r) => {
      if (!map[r.device]) {
        map[r.device] = {
          firstId: r.id,
          pending: queues.find((q) => q.device === r.device)?.pending ?? 0,
        };
      }
    });
    return map;
  }, [caseRows, queues]);

  // Every running job is tailed automatically; keep its tab open (and keep any
  // tab the user opened manually / left open after the run finished).
  useEffect(() => {
    const names = runningJobs.map((j) => j.log_file);
    if (!names.length) return;
    setOpenLogs((prev) => [...names, ...prev.filter((n) => !names.includes(n))]);
    setActiveLog((prev) => (prev && [...names, ...openLogs].includes(prev) ? prev : names[0]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runningJobs.map((j) => j.log_file).join("|")]);

  // One timer drives: job list + test-log list + every open log tab.
  const tick = useCallback(async () => {
    await refreshJobs(true);
    refreshLogs(true);
    const names = openLogs;
    if (!names.length) return;
    const results = await Promise.allSettled(
      names.map((n) => viewRokuTestLog(n).then((c) => [n, c] as const))
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openLogs, refreshJobs]);

  useEffect(() => {
    tick(); // immediate load whenever the tab set / interval changes
    if (!autoRefresh) return;
    const id = setInterval(tick, refreshMs);
    return () => clearInterval(id);
  }, [autoRefresh, refreshMs, tick]);

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
      if (res.queued) {
        // The device is busy: the case waits its turn, so there is no log to
        // tail yet (the tab opens by itself once the case starts).
        message.success(
          `Queued on '${device}' at position ${res.queue_position} — it runs when the case(s) ahead finish`
        );
      } else {
        message.success(`${res.message} (pid ${res.pid})`);
        // Open a live-log tab for this run; previously started runs keep theirs.
        const name = basename(res.log_file);
        setOpenLogs((prev) => [name, ...prev.filter((n) => n !== name)]);
        setActiveLog(name);
        setLogContent((prev) => ({ ...prev, [name]: "" }));
      }
      refreshJobs(true);
      // The backend persists the inputs to config.yml; reflect it in the
      // dropdowns right away (newest first, de-duped).
      const aid = automationId.trim();
      const tid = testrailCaseId.trim();
      if (aid) setAutomationIdHistory((h) => [aid, ...h.filter((x) => x !== aid)]);
      if (tid) setTestrailCaseIdHistory((h) => [tid, ...h.filter((x) => x !== tid)]);
      refreshLogs();
    } catch (e) {
      message.error(`Run failed: ${(e as Error).message}`);
    } finally {
      setRunning(false);
    }
  };

  // Stop ONE tracked run (other running jobs are untouched). The device queue
  // is not paused: the next case waiting for that device starts right after.
  const handleStopJob = async (job: RokuTestJob) => {
    setStoppingId(job.id);
    try {
      const res = await stopRokuTestJob(job.id);
      if (res.status === "stopped") message.success(`Stopped PID ${job.pid}`);
      else message.info(`PID ${job.pid} is ${res.status}`);
      // The process needs a beat to disappear from `ps`; refresh twice so the
      // row flips running -> completed without waiting for the next poll.
      refreshJobs(true);
      refreshLogs(true);
      setTimeout(() => {
        refreshJobs(true);
        refreshLogs(true);
      }, 1500);
    } catch (e) {
      message.error(`Stop failed: ${(e as Error).message}`);
    } finally {
      setStoppingId(null);
    }
  };

  const handleDeleteJob = async (id: string) => {
    try {
      await deleteRokuTestJob(id);
      refreshJobs(true);
    } catch (e) {
      message.error(`Remove failed: ${(e as Error).message}`);
    }
  };

  // Reorder a WAITING case inside its device queue.
  const handleMoveQueueJob = async (
    job: RokuTestJob,
    direction: "up" | "down"
  ) => {
    setQueueBusyId(job.id);
    try {
      await moveRokuTestQueueJob(job.device, job.id, direction);
      await refreshJobs(true);
    } catch (e) {
      message.error(`Move failed: ${(e as Error).message}`);
    } finally {
      setQueueBusyId(null);
    }
  };

  // Drop every waiting case of one device (its running case keeps going).
  const handleClearQueue = async (deviceName: string) => {
    setClearingQueue(deviceName);
    try {
      const res = await clearRokuTestQueue(deviceName);
      message.success(res.message);
      await refreshJobs(true);
    } catch (e) {
      message.error(`Clear queue failed: ${(e as Error).message}`);
    } finally {
      setClearingQueue(null);
    }
  };

  // Clear every FINISHED job entry; queued / running jobs stay in the list.
  const handleClearJobs = async () => {
    setClearingJobs(true);
    try {
      const res = await clearRokuTestJobs();
      message.success(res.message);
      refreshJobs(true);
    } catch (e) {
      message.error(`Clear failed: ${(e as Error).message}`);
    } finally {
      setClearingJobs(false);
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

  // Row state: a log belonging to a live job is 'running' (the job list is the
  // authoritative source for the runs started from this page); otherwise fall
  // back to the backend's own detection.
  const runningJobLogs = useMemo(
    () => new Set(runningJobs.map((j) => j.log_file)),
    [runningJobs]
  );
  const displayState = (r: RokuTestLog): "running" | "completed" =>
    runningJobLogs.has(r.name) ? "running" : r.state;

  // Parse each log once; build filter option lists and apply the active filters.
  // Backend list does not return testrail_case_id — derive it from the log name.
  const parsedLogs = logs.map((l) => {
    const parsed = parseLogName(l.name, devices);
    return {
      ...l,
      parsed,
      testrail_case_id: parsed?.testrailCaseId || l.testrail_case_id || "",
    };
  });
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
      (!filterResult || (l.result?.includes(filterResult) ?? false)) &&
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
            <Space size={6}>
              <Text strong>Branch (automated_tests)</Text>
              {branchLocked && (
                <Tooltip
                  title={`Locked while a case runs: ${runningJobs
                    .map((j) => `${j.automation_id} on ${j.device}`)
                    .join(", ")}`}
                >
                  <Text type="warning" style={{ fontSize: 12 }}>
                    Locked:{" "}
                    {runningJobs.length === 1
                      ? "case is running"
                      : `${runningJobs.length} cases are running`}
                  </Text>
                </Tooltip>
              )}
            </Space>
            <Tooltip
              title={
                branchLocked
                  ? `Branch is locked while a case runs: ${runningJobs
                      .map((j) => `${j.automation_id} on ${j.device}`)
                      .join(", ")}`
                  : ""
              }
            >
              <Select
                style={{ width: "100%", marginTop: 8 }}
                placeholder="Select a branch"
                loading={loadingBranches || checkingOut}
                // Switching branch mid-run would swap the test files under the
                // live run (one shared automated_tests working tree).
                disabled={branchLocked}
                value={branch}
                onChange={handleCheckout}
                options={branches.map((b) => ({ value: b, label: b }))}
                showSearch
                optionFilterProp="label"
                popupMatchSelectWidth={false}
              />
            </Tooltip>
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
            <AutoComplete
              style={{ marginTop: 8, width: "100%" }}
              placeholder="e.g. bdd-2659886031 or a UT automation id"
              value={automationId}
              onChange={setAutomationId}
              options={historyOptions(automationIdHistory, handleDeleteAutomationId)}
              filterOption={(input, option) =>
                String(option?.value ?? "").toLowerCase().includes(input.toLowerCase())
              }
              onKeyDown={(e) => {
                if (e.key === "Enter") handleRun();
              }}
              allowClear
            />
          </div>
          <div style={{ minWidth: 220 }}>
            <Text strong>TestRail Case ID</Text>
            <AutoComplete
              style={{ marginTop: 8, width: "100%" }}
              placeholder="e.g. 2294354569"
              value={testrailCaseId}
              onChange={setTestrailCaseId}
              options={historyOptions(testrailCaseIdHistory, handleDeleteTestrailCaseId)}
              filterOption={(input, option) =>
                String(option?.value ?? "").toLowerCase().includes(input.toLowerCase())
              }
              onKeyDown={(e) => {
                if (e.key === "Enter") handleRun();
              }}
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
            icon={selectedDeviceBusy ? <PlusOutlined /> : <PlayCircleOutlined />}
            loading={running}
            disabled={!canRun}
            onClick={handleRun}
          >
            {selectedDeviceBusy ? "Add to queue" : "Run"}
          </Button>
        </Space>

        {/* The device runs one case at a time, so make it obvious that this
            case will wait rather than start now. */}
        {selectedDeviceBusy && (
          <Text type="secondary" style={{ display: "block", marginTop: 8 }}>
            {`'${device}' is busy (${selectedDeviceQueue?.running ? "1 running" : "idle"}, ${
              selectedDeviceQueue?.pending ?? 0
            } waiting) — this case is appended to its queue and runs in order.`}
          </Text>
        )}

        {runningJobs.length > 0 && (
          <Alert
            style={{ marginTop: 16 }}
            type="info"
            showIcon
            message={
              `${runningJobs.length} roku_test run(s) in progress` +
              (queuedJobs.length ? `, ${queuedJobs.length} case(s) queued` : "")
            }
            description={
              <Space direction="vertical" size={2} style={{ width: "100%" }}>
                {runningJobs.map((j) => (
                  <Text key={j.id} code style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>
                    [pid {j.pid}] {j.command}
                  </Text>
                ))}
              </Space>
            }
          />
        )}
      </Card>

      {/* Per-device queues: one case runs at a time per device, in order. */}
      {/* Cases: per-device queues (active, grouped) + finished history, in one table */}
      <Card
        style={{ marginBottom: 16 }}
        title={`Cases (${activeRows.length} active${
          finishedJobCount ? `, ${finishedJobCount} finished` : ""
        })`}
        extra={
          <Space size={4}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              Show
            </Text>
            <Segmented
              size="small"
              value={caseView}
              onChange={(v) => setCaseView(v as CaseView)}
              options={[
                { label: `Active (${activeRows.length})`, value: "active" },
                { label: `Finished (${finishedJobCount})`, value: "finished" },
                { label: "All", value: "all" },
              ]}
            />
            <Popconfirm
              title="Clear finished cases?"
              description="Only stopped / finished cases leave the list. Queued, running cases and all log files are kept."
              okText="Clear"
              okButtonProps={{ danger: true }}
              disabled={!finishedJobCount}
              onConfirm={handleClearJobs}
            >
              <Button
                size="small"
                danger
                icon={<ClearOutlined />}
                loading={clearingJobs}
                disabled={!finishedJobCount}
              >
                Clear finished
              </Button>
            </Popconfirm>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => refreshJobs()}>
              Refresh
            </Button>
          </Space>
        }
      >
        <Table<RokuTestJob>
          size="small"
          rowKey="id"
          loading={loadingJobs}
          dataSource={caseRows}
          pagination={
            caseView === "active"
              ? false
              : { pageSize: 10, showSizeChanger: true, size: "small" }
          }
          locale={{
            emptyText:
              caseView === "finished"
                ? "No finished case yet."
                : "No case queued or running. Add one above.",
          }}
          columns={[
            {
              // Device + queue place in one cell: the first row of each device
              // carries the name and its queue controls, the rest just show
              // their position, which reads like a grouped list.
              title: "Device / Queue",
              key: "device",
              width: 260,
              render: (_: unknown, r: RokuTestJob) => {
                const group = deviceGroups[r.device];
                const isFirst = group?.firstId === r.id;
                return (
                  <Space size={4} wrap>
                    {isFirst ? (
                      <>
                        <Tag color="blue" style={{ marginRight: 0 }}>
                          {r.device}
                        </Tag>
                        {group && group.pending > 0 && (
                          <Popconfirm
                            title={`Clear the queue of '${r.device}'?`}
                            description="Every WAITING case is dropped. A running case keeps going."
                            okText="Clear"
                            okButtonProps={{ danger: true }}
                            onConfirm={() => handleClearQueue(r.device)}
                          >
                            <Tooltip title={`Clear ${group.pending} waiting case(s)`}>
                              <Button
                                size="small"
                                type="text"
                                danger
                                icon={<ClearOutlined />}
                                loading={clearingQueue === r.device}
                              />
                            </Tooltip>
                          </Popconfirm>
                        )}
                      </>
                    ) : (
                      <Text type="secondary" style={{ fontSize: 12, paddingLeft: 8 }}>
                        ↳
                      </Text>
                    )}
                    {r.running ? (
                      <Tag color="processing">now</Tag>
                    ) : r.status === "queued" ? (
                      <Tag>#{r.queue_position}</Tag>
                    ) : null}
                  </Space>
                );
              },
            },
            {
              title: "Case",
              key: "case",
              ellipsis: true,
              render: (_: unknown, r: RokuTestJob) => (
                <Space direction="vertical" size={0}>
                  <Text style={{ fontSize: 13 }}>{r.automation_id}</Text>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {r.testrail_case_id ? (
                      <a
                        href={`https://testrail.eswat.roku.com/testrail/index.php?/cases/view/${r.testrail_case_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {r.testrail_case_id}
                      </a>
                    ) : (
                      "-"
                    )}
                    {r.repeat > 0 && ` · repeat ${r.repeat}`}
                    {r.pid > 0 && ` · pid ${r.pid}`}
                  </Text>
                </Space>
              ),
            },
            {
              title: "Status",
              key: "status",
              width: 110,
              render: (_: unknown, r: RokuTestJob) =>
                r.status === "queued" ? (
                  <Tooltip title={`Waiting for '${r.device}' — position ${r.queue_position}`}>
                    <Tag color="warning">queued</Tag>
                  </Tooltip>
                ) : (
                  <Tooltip title={r.error || ""}>
                    <Tag color={r.running ? "processing" : "default"}>{r.status}</Tag>
                  </Tooltip>
                ),
            },
            {
              title: "Result",
              dataIndex: "result",
              key: "result",
              width: 150,
              render: (res: string) => {
                const parts = resultParts(res);
                if (!parts.length) return <Text type="secondary">-</Text>;
                return (
                  <Space size={4} wrap>
                    {parts.map((p, i) => (
                      <Tag key={`${p}-${i}`} color={resultPartColor(p)}>
                        {p}
                      </Tag>
                    ))}
                  </Space>
                );
              },
            },
            {
              // Started + elapsed in one column: the time is what matters, the
              // duration is secondary.
              title: "Started / Elapsed",
              key: "timing",
              width: 175,
              render: (_: unknown, r: RokuTestJob) => {
                if (r.status === "queued") {
                  return <Text type="secondary">waiting…</Text>;
                }
                const elapsed = formatElapsed(r.elapsed_time);
                return (
                  <Space direction="vertical" size={0}>
                    <Text style={{ fontSize: 12 }}>
                      {r.started_at ? r.started_at.replace(" UTC", "") : "-"}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {r.running ? "running…" : elapsed === "-" ? "-" : elapsed}
                    </Text>
                  </Space>
                );
              },
            },
            {
              title: "Action",
              key: "action",
              width: 150,
              render: (_: unknown, r: RokuTestJob) => {
                const group = deviceGroups[r.device];
                if (r.running) {
                  return (
                    <Popconfirm
                      title={`Stop PID ${r.pid}?`}
                      description="Only this case is terminated; the next queued case starts."
                      okText="Stop"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => handleStopJob(r)}
                    >
                      <Tooltip title="Stop">
                        <Button
                          size="small"
                          danger
                          icon={<StopOutlined />}
                          loading={stoppingId === r.id}
                        />
                      </Tooltip>
                    </Popconfirm>
                  );
                }
                if (r.status === "queued") {
                  return (
                    <Space size={4}>
                      <Tooltip title="Run earlier">
                        <Button
                          size="small"
                          icon={<ArrowUpOutlined />}
                          disabled={r.queue_position <= 1}
                          loading={queueBusyId === r.id}
                          onClick={() => handleMoveQueueJob(r, "up")}
                        />
                      </Tooltip>
                      <Tooltip title="Run later">
                        <Button
                          size="small"
                          icon={<ArrowDownOutlined />}
                          disabled={r.queue_position >= (group?.pending ?? 0)}
                          loading={queueBusyId === r.id}
                          onClick={() => handleMoveQueueJob(r, "down")}
                        />
                      </Tooltip>
                      <Popconfirm
                        title="Remove this case from the queue?"
                        okText="Remove"
                        okButtonProps={{ danger: true }}
                        onConfirm={() => handleDeleteJob(r.id)}
                      >
                        <Tooltip title="Cancel">
                          <Button size="small" danger icon={<DeleteOutlined />} />
                        </Tooltip>
                      </Popconfirm>
                    </Space>
                  );
                }
                return (
                  <Space size={4}>
                    {r.log_file && (
                      <Tooltip title="View log">
                        <Button
                          size="small"
                          icon={<EyeOutlined />}
                          onClick={() => openLog(r.log_file)}
                        />
                      </Tooltip>
                    )}
                    <Popconfirm
                      title="Remove this case from the list?"
                      description="The log file is kept."
                      okText="Remove"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => handleDeleteJob(r.id)}
                    >
                      <Tooltip title="Remove">
                        <Button size="small" danger icon={<DeleteOutlined />} />
                      </Tooltip>
                    </Popconfirm>
                  </Space>
                );
              },
            },
          ]}
        />
      </Card>

      {/* Live logs: one tab per run (multiple runs can be live at once) */}
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
          <Empty description="No log is being tailed. Start a run to see its live log here." />
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
                    <span>
                      {job ? `${job.device} · ${job.automation_id}` : name}
                    </span>
                    {job?.running && <Tag color="processing">running</Tag>}
                  </Space>
                ),
                children: (
                  <div>
                    {job && (
                      <Space style={{ marginBottom: 8 }} wrap>
                        <Tag>pid {job.pid}</Tag>
                        <Tag color="blue">{job.device}</Tag>
                        <Tag color="geekblue">{job.automation_id}</Tag>
                        {job.testrail_case_id && (
                          <Tag color="purple">case {job.testrail_case_id}</Tag>
                        )}
                        {/* Each run can be stopped on its own. */}
                        <Popconfirm
                          title={`Stop PID ${job.pid}?`}
                          description="Only this test process will be terminated."
                          okText="Stop"
                          okButtonProps={{ danger: true }}
                          disabled={!job.running}
                          onConfirm={() => handleStopJob(job)}
                        >
                          <Button
                            size="small"
                            danger
                            icon={<StopOutlined />}
                            disabled={!job.running}
                            loading={stoppingId === job.id}
                          >
                            Stop
                          </Button>
                        </Popconfirm>
                      </Space>
                    )}
                    <LogPane
                      logFile={name}
                      content={logContent[name] ?? ""}
                      updatedAt={logUpdated[name] ?? ""}
                    />
                  </div>
                ),
              };
            })}
          />
        )}
      </Card>

      {/* Log list */}
      <Card
        title={`Test Logs (${filteredLogs.length})`}
        extra={
          <Button size="small" icon={<ReloadOutlined />} onClick={() => refreshLogs()}>
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
              title: "TestRail Case ID",
              dataIndex: "testrail_case_id",
              key: "testrail_case_id",
              width: 150,
              sorter: (a: RokuTestLog, b: RokuTestLog) =>
                (a.testrail_case_id || "").localeCompare(b.testrail_case_id || ""),
              sortDirections: ["ascend", "descend"],
              render: (id: string) =>
                id ? (
                  <a
                    href={`https://testrail.eswat.roku.com/testrail/index.php?/cases/view/${id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {id}
                  </a>
                ) : (
                  "-"
                ),
            },
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
              width: 100,
              render: (_: unknown, r: RokuTestLog) => {
                const s = displayState(r);
                return <Tag color={s === "running" ? "processing" : "success"}>{s}</Tag>;
              },
            },
            {
              title: "Result",
              dataIndex: "result",
              key: "result",
              width: 200,
              render: (res: RokuTestLog["result"]) => {
                const parts = resultParts(res);
                if (!parts.length) return <Tag>-</Tag>;
                return (
                  <Space size={4} wrap>
                    {parts.map((p, i) => (
                      <Tag key={`${p}-${i}`} color={resultPartColor(p)}>
                        {p}
                      </Tag>
                    ))}
                  </Space>
                );
              },
            },
            {
              title: "Elapsed time",
              dataIndex: "elapsed_time",
              key: "elapsed_time",
              width: 130,
              sorter: (a: RokuTestLog, b: RokuTestLog) =>
                (a.elapsed_time ?? 0) - (b.elapsed_time ?? 0),
              sortDirections: ["descend", "ascend"],
              render: (v: number | undefined, r: RokuTestLog) => {
                if (displayState(r) === "running") {
                  return <Tag color="processing">running</Tag>;
                }
                const text = formatElapsed(v);
                if (!v || v <= 0 || text === "-") {
                  return <span>-</span>;
                }
                return (
                  <Tooltip title={`${v}s`}>
                    <Tag color="yellow">{text}</Tag>
                  </Tooltip>
                );
              },
            },
            {
              title: "Action",
              key: "action",
              width: 240,
              render: (_: unknown, r: RokuTestLog) => (
                <Space>
                  <Button
                    size="small"
                    icon={<EyeOutlined />}
                    onClick={() => openLog(r.name)}
                  >
                    View
                  </Button>
                  <Tooltip title="Download">
                    <Button
                      size="small"
                      icon={<DownloadOutlined />}
                      href={rokuTestLogDownloadUrl(r.name)}
                      download={r.name}
                    />
                  </Tooltip>
                  {/* <Button
                    type="primary"
                    size="small"
                    icon={<ExperimentOutlined />}
                    disabled={isPurePassResult(r.result)}
                    onClick={() => handleAnalyzeLog(r.name, r.result)}
                  >
                    Analyze
                  </Button> */}
                  <Tooltip title="Analyze">
                    <Button
                      type="primary"
                      size="small"
                      icon={<ExperimentOutlined />}
                      disabled={isPurePassResult(r.result)}
                      onClick={() => handleAnalyzeLog(r.name, r.result)}
                    />
                  </Tooltip>
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
