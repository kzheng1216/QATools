import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  AutoComplete,
  Col,
  Input,
  InputNumber,
  Modal,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
  Popconfirm,
} from "antd";
import {
  PlayCircleOutlined,
  ReloadOutlined,
  EyeOutlined,
  ClearOutlined,
  SearchOutlined,
  StopOutlined,
  DeleteOutlined,
  ExperimentOutlined,
  SaveOutlined,
  CopyOutlined,
  DownloadOutlined,
} from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  listProfiles,
  listUserNames,
  addUserQuery,
  deleteUserQuery,
  runCase,
  listRunningCases,
  stopCase,
  listRunCache,
  listRunReports,
  viewRunCache,
  viewRunReport,
  clearRunData,
  deleteRunCache,
  deleteRunReport,
  listSuites,
  terminateSuite,
  getSuiteBuildUrl,
  agentAnalyze,
  getAnalyzeConfig,
  type Suite,
  type RunningCase,
  type RunFile,
  type AnalyzeLocale,
} from "../api/client";

const { Title, Text } = Typography;

const SELECT_OPTIONS = [
  "All",
  "Fail",
  "Pass",
  "Skipped",
  "Blocked",
  "NA",
  "Unknown",
  "NoTest",
].map((v) => ({ value: v, label: v }));

const DEFAULT_POLL_SEC = 5;

export default function RunCasePage() {
  const [profiles, setProfiles] = useState<string[]>([]);
  const [profile, setProfile] = useState<string>();
  const [select, setSelect] = useState<string>("All");
  const [loadingProfiles, setLoadingProfiles] = useState(false);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const [caches, setCaches] = useState<RunFile[]>([]);
  const [reports, setReports] = useState<RunFile[]>([]);
  const [loadingLists, setLoadingLists] = useState(false);
  const [polling, setPolling] = useState(true); // auto-refresh enabled by default
  const [pollSec, setPollSec] = useState(DEFAULT_POLL_SEC); // refresh interval (s)
  const [lastUpdated, setLastUpdated] = useState<string>("");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Viewer holds raw text; when `rows` is present the modal renders a table
  // (parsed from the cache/report JSON) instead of the raw <pre>.
  type TaskRow = {
    key: string;
    testrail_case_ids: string;
    case_ids: string;
    status?: string;
    log_url?: string | null;
    build_number?: number | null;
  };
  const [viewer, setViewer] = useState<
    {
      title: string;
      content: string;
      profile?: string;
      rows?: TaskRow[];
      progress?: string;
      count?: number;
    } | null
  >(null);

  // Log analysis modal (AI summary of a task's log). Driven by a task's log_url.
  const [analyzeOpen, setAnalyzeOpen] = useState(false);
  const [analyzeTitle, setAnalyzeTitle] = useState("");
  const [analyzeResult, setAnalyzeResult] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeLocale, setAnalyzeLocale] = useState<AnalyzeLocale>("en-US");
  // Configured default Analyze locale (from Settings); used when opening Analyze.
  const defaultLocaleRef = useRef<AnalyzeLocale>("en-US");
  // Cache the prompt (log url) so a language switch re-analyzes without rebuilding.
  const analyzePromptRef = useRef<string>("");
  // case id / device id for the row being analyzed (sent to the analyze API).
  const analyzeCaseRef = useRef<string>("");
  const analyzeTestrailRef = useRef<string>("");
  const analyzeDeviceRef = useRef<string>("");
  const analyzeResultRef = useRef<string>("");
  const analyzeProfileRef = useRef<string>("");

  // Running cases (local test_runner.py processes)
  const [runningCases, setRunningCases] = useState<RunningCase[]>([]);
  const [loadingRunning, setLoadingRunning] = useState(false);
  const [stoppingPid, setStoppingPid] = useState<string | null>(null);
  const [runningSearch, setRunningSearch] = useState("");

  const refreshRunning = async () => {
    setLoadingRunning(true);
    try {
      setRunningCases(await listRunningCases());
    } catch (e) {
      message.error(`Load running cases failed: ${(e as Error).message}`);
    } finally {
      setLoadingRunning(false);
    }
  };

  const handleStop = async (pid: string) => {
    setStoppingPid(pid);
    try {
      await stopCase(pid);
      message.success(`Stopped PID ${pid}`);
      refreshRunning();
    } catch (e) {
      message.error(`Stop failed: ${(e as Error).message}`);
    } finally {
      setStoppingPid(null);
    }
  };

  // Running suites (QAHub) by user
  const [suiteUser, setSuiteUser] = useState<string>("");
  const [users, setUsers] = useState<string[]>([]);
  const [suites, setSuites] = useState<Suite[]>([]);
  const [loadingSuites, setLoadingSuites] = useState(false);
  const [terminatingId, setTerminatingId] = useState<number | null>(null);

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

  // Load user names for the Running Suites dropdown.
  useEffect(() => {
    listUserNames()
      .then(setUsers)
      .catch((e: Error) => message.error(`Load users failed: ${e.message}`));
  }, []);

  const querySuites = async () => {
    const user = suiteUser.trim();
    if (!user) {
      message.warning("Please enter a user");
      return;
    }
    setLoadingSuites(true);
    try {
      const list = await listSuites(user, "running");
      setSuites(list);
      if (list.length === 0) message.info("No running suites for this user");
      // Remember the searched user into config.yml:runcase_user_query_list.
      if (!users.includes(user)) {
        addUserQuery(user)
          .then(setUsers)
          .catch((e: Error) => message.error(`Save user failed: ${e.message}`));
      }
    } catch (e) {
      message.error(`Query suites failed: ${(e as Error).message}`);
    } finally {
      setLoadingSuites(false);
    }
  };

  // Delete a saved user name from the query-history dropdown.
  const handleDeleteUser = async (name: string) => {
    try {
      const next = await deleteUserQuery(name);
      setUsers(next);
      message.success(`Removed "${name}"`);
    } catch (e) {
      message.error(`Remove failed: ${(e as Error).message}`);
    }
  };

  const openSuiteBuild = async (suiteId: number) => {
    const hide = message.loading("Resolving Jenkins build...", 0);
    try {
      const { url } = await getSuiteBuildUrl(suiteId);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      message.error(`Open build failed: ${(e as Error).message}`);
    } finally {
      hide();
    }
  };

  const handleTerminate = async (suiteId: number) => {
    setTerminatingId(suiteId);
    try {
      const res = await terminateSuite(suiteId);
      message.success(`Terminate ${suiteId}: ${res.status}`);
      querySuites(); // refresh after terminating
    } catch (e) {
      message.error(`Terminate failed: ${(e as Error).message}`);
    } finally {
      setTerminatingId(null);
    }
  };

  // Load profiles for the dropdown.
  useEffect(() => {
    setLoadingProfiles(true);
    listProfiles()
      .then((list) => setProfiles([...list].sort((a, b) => a.localeCompare(b))))
      .catch((e: Error) => message.error(`Load profiles failed: ${e.message}`))
      .finally(() => setLoadingProfiles(false));
  }, []);

  const refreshLists = async () => {
    setLoadingLists(true);
    try {
      const [c, r] = await Promise.all([listRunCache(), listRunReports()]);
      setCaches(c);
      setReports(r);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (e) {
      message.error(`Refresh failed: ${(e as Error).message}`);
    } finally {
      setLoadingLists(false);
    }
  };

  // Poll running cases + cache/report lists while enabled.
  useEffect(() => {
    if (!polling) {
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = null;
      return;
    }
    const tick = () => {
      refreshLists();
      refreshRunning();
    };
    tick();
    timerRef.current = setInterval(tick, Math.max(1, pollSec) * 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = null;
    };
  }, [polling, pollSec]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRun = async () => {
    if (!profile) {
      message.warning("Please select a profile");
      return;
    }
    setRunning(true);
    try {
      const res = await runCase(profile, select);
      const text = `${res.message} (pid ${res.pid})`;
      message.success(text);
      setRunResult({ type: "success", text });
      refreshLists();
      refreshRunning();
    } catch (e) {
      const text = `Run failed: ${(e as Error).message}`;
      message.error(text);
      setRunResult({ type: "error", text });
    } finally {
      setRunning(false);
    }
  };

  // Extract the Jenkins build number from a consoleFull URL, e.g.
  // ".../qa_hub_launch_suite/1316933/consoleFull" -> 1316933.
  const buildFromUrl = (url?: string | null): number | null => {
    const m = url?.match(/\/(\d+)\/console/);
    return m ? Number(m[1]) : null;
  };

  // strip Python list quoting: "['X']" -> "X"
  const cleanCase = (k: string) => k.replace(/^\[?'?|'?\]?$/g, "").replace(/'/g, "");

  // Parse cache/report content into table rows (+ optional progress string).
  // Real shapes:
  //   Report (_summary_report.txt):
  //     { tasks: [{case_ids:[...], status, log_url, build_number}] }
  //   Cache (.cache):
  //     { task_results: { "<case>": <VAL> }, task_progress: "n/m" }
  //   where <VAL> is EITHER an object {status, log_url, build_number}
  //   OR a "status|log_url" string. Both are handled.
  // Returns {rows: undefined} for anything else (caller shows raw text).
  const parseTaskRows = (
    content: string
  ): { rows?: TaskRow[]; progress?: string; count?: number } => {
    try {
      const data = JSON.parse(content);
      // Report shape
      if (Array.isArray(data?.tasks)) {
        return {
          rows: data.tasks.map((t: Record<string, unknown>, i: number) => ({
            key: String(i),
            testrail_case_ids: Array.isArray(t.testrail_case_ids)
              ? (t.testrail_case_ids as unknown[]).join(", ")
              : String(t.testrail_case_ids ?? ""),
            case_ids: Array.isArray(t.case_ids)
              ? (t.case_ids as unknown[]).join(", ")
              : String(t.case_ids ?? ""),
            status: t.status as string | undefined,
            log_url: (t.log_url as string | null) ?? null,
            build_number:
              (t.build_number as number | null) ?? buildFromUrl(t.log_url as string),
          })),
          count: data.count as number | undefined,
        };
      }
      // Cache shape: task_results maps case -> object OR "status|log_url"
      if (data?.task_results && typeof data.task_results === "object") {
        const rows = Object.entries(
          data.task_results as Record<string, unknown>
        ).map(([caseKey, val], i) => {
          let status: string | undefined;
          let log_url: string | null = null;
          let build_number: number | null = null;
          let testrail_case_ids = "";
          if (typeof val === "string") {
            const [s, u] = val.split("|");
            status = s || undefined;
            log_url = u || null;
            build_number = buildFromUrl(u);
          } else if (val && typeof val === "object") {
            const o = val as Record<string, unknown>;
            status = o.status as string | undefined;
            log_url = (o.log_url as string | null) ?? null;
            build_number =
              (o.build_number as number | null) ?? buildFromUrl(o.log_url as string);
            testrail_case_ids = Array.isArray(o.testrail_case_ids)
              ? (o.testrail_case_ids as unknown[]).join(", ")
              : String(o.testrail_case_ids ?? "");
          }
          return {
            key: String(i),
            testrail_case_ids,
            case_ids: cleanCase(caseKey),
            status,
            log_url,
            build_number,
          };
        });
        return { rows, progress: data.task_progress as string | undefined };
      }
    } catch {
      /* not JSON — caller shows raw text */
    }
    return {};
  };

  const openCache = async (file: string) => {
    try {
      const content = await viewRunCache(file);
      const { rows, progress, count } = parseTaskRows(content);
      setViewer({
        title: `Cache: ${file}`,
        content,
        profile: profileName(file),
        rows,
        progress,
        count,
      });
    } catch (e) {
      message.error(`View failed: ${(e as Error).message}`);
    }
  };

  const openReport = async (file: string) => {
    try {
      const content = await viewRunReport(file);
      const { rows, progress, count } = parseTaskRows(content);
      setViewer({
        title: `Report: ${file}`,
        content,
        profile: profileName(file),
        rows,
        progress,
        count,
      });
    } catch (e) {
      message.error(`View failed: ${(e as Error).message}`);
    }
  };

  // Build a Markdown table from the parsed viewer rows and download it.
  const exportViewerMarkdown = () => {
    if (!viewer?.rows) return;
    const esc = (s: string) => s.replace(/\|/g, "\\|");
    const header =
      "| TestRail Case ID | Automation ID | Status | Build | Log |\n" +
      "| --- | --- | --- | --- | --- |";
    const lines = viewer.rows.map((r) => {
      const tr = (r.testrail_case_ids || "")
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean)
        .map(
          (id) =>
            `[${id}](https://testrail.eswat.roku.com/testrail/index.php?/cases/view/${id})`
        )
        .join(", ");
      const log = r.log_url ? `[log](${r.log_url})` : "";
      return `| ${esc(tr)} | ${esc(r.case_ids)} | ${r.status ?? ""} | ${
        r.build_number ?? ""
      } | ${log} |`;
    });
    const meta: string[] = [`# ${viewer.title}`, ""];
    if (viewer.progress) meta.push(`**Progress:** ${viewer.progress}`, "");
    if (viewer.count !== undefined) meta.push(`**Count:** ${viewer.count}`, "");
    const md = [...meta, header, ...lines, ""].join("\n");

    const base = (viewer.title || "export").replace(/[^\w.-]+/g, "_");
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${base}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ---------- Log analysis ----------
  const runAnalyze = async (prompt: string, locale: "zh-CN" | "en-US") => {
    if (!prompt.trim()) {
      setAnalyzeResult("_(no log link to analyze)_");
      return;
    }
    setAnalyzing(true);
    try {
      const res = await agentAnalyze(
        prompt,
        locale,
        false,
        analyzeCaseRef.current || undefined,
        analyzeDeviceRef.current || undefined,
        analyzeResultRef.current || undefined,
        analyzeTestrailRef.current || undefined,
        analyzeProfileRef.current || undefined
      );
      setAnalyzeResult(res.response);
    } catch (e) {
      message.error(`Analyze failed: ${(e as Error).message}`);
    } finally {
      setAnalyzing(false);
    }
  };

  // Profiles are named profile_<plan>_<status>_<device>.json — best-effort
  // device id from the selected profile for the analyze history file name.
  const deviceFromProfile = (): string => {
    if (!profile) return "";
    const base = profile.replace(/\.json$/i, "");
    const parts = base.split("_");
    return parts.length >= 2 ? parts[parts.length - 1] : "";
  };

  const handleAnalyzeRow = (row: TaskRow) => {
    const prompt = row.log_url || "";
    // TestRail id and automation id are stored as distinct fields in the
    // analyze-history record.
    analyzePromptRef.current = prompt;
    analyzeTestrailRef.current = row.testrail_case_ids || "";
    analyzeCaseRef.current = row.case_ids || "";
    analyzeDeviceRef.current = deviceFromProfile();
    analyzeResultRef.current = row.status || "";
    // Profile of the cache/report file this row came from (for the history name).
    analyzeProfileRef.current = viewer?.profile || "";
    setAnalyzeTitle(`Analyze: ${row.testrail_case_ids || row.case_ids || ""}`);
    setAnalyzeResult("");
    // Use the configured default Analyze locale.
    const locale = defaultLocaleRef.current;
    setAnalyzeLocale(locale);
    setAnalyzeOpen(true);
    runAnalyze(prompt, locale);
  };

  const switchAnalyzeLocale = (locale: "zh-CN" | "en-US") => {
    if (locale === analyzeLocale || analyzing) return;
    setAnalyzeLocale(locale);
    setAnalyzeResult("");
    runAnalyze(analyzePromptRef.current, locale);
  };

  const handleSaveAnalysis = async () => {
    if (!analyzeResult) return;
    const suggestedName = "log-analysis.md";
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

  const handleClear = async () => {
    try {
      const res = await clearRunData();
      message.success(res.message);
      refreshLists();
    } catch (e) {
      message.error(`Clear failed: ${(e as Error).message}`);
    }
  };

  const handleDeleteCache = async (file: string) => {
    try {
      const res = await deleteRunCache(file);
      message.success(res.message);
      refreshLists();
    } catch (e) {
      message.error(`Delete failed: ${(e as Error).message}`);
    }
  };

  const handleDeleteReport = async (file: string) => {
    try {
      const res = await deleteRunReport(file);
      message.success(res.message);
      refreshLists();
    } catch (e) {
      message.error(`Delete failed: ${(e as Error).message}`);
    }
  };

  // Cache/report files are named <timestamp>_<profile>.json.cache or
  // <timestamp>_<profile>.json_summary_report.txt. Show just the profile name.
  const profileName = (fileName: string): string =>
    fileName
      .replace(/^\d{8}_\d{6}_/, "")
      .replace(/\.json_summary_report\.txt$/, "")
      .replace(/_summary_report\.txt$/, "")
      .replace(/\.json\.cache$/, "")
      .replace(/\.cache$/, "")
      .replace(/\.json$/, "");

  const fileColumns = (
    onView: (f: string) => void,
    onDelete: (f: string) => void
  ) => [
    {
      title: "Profile Name",
      dataIndex: "name",
      key: "name",
      sorter: (a: RunFile, b: RunFile) =>
        profileName(a.name).localeCompare(profileName(b.name)),
      render: (name: string) => profileName(name),
    },
    {
      title: "Date",
      dataIndex: "mtime",
      key: "mtime",
      width: 180,
      sorter: (a: RunFile, b: RunFile) => a.mtime - b.mtime,
      defaultSortOrder: "descend" as const,
      render: (mtime: number) =>
        mtime ? new Date(mtime * 1000).toLocaleString() : "-",
    },
    {
      title: "Action",
      key: "action",
      width: 190,
      render: (_: unknown, record: RunFile) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => onView(record.name)}>
            View
          </Button>
          <Popconfirm
            title={`Delete "${record.name}"?`}
            okText="Delete"
            okButtonProps={{ danger: true }}
            onConfirm={() => onDelete(record.name)}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
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
        Run Case
      </Title>

      <Card style={{ marginBottom: 16 }}>
        <Space size="large" wrap align="end">
          <div
            style={{
              // Auto-fit to the longest profile name: ~7.3px/char + room for the
              // search/clear icons, clamped so it never gets absurdly wide.
              width: Math.min(
                720,
                Math.max(
                  260,
                  Math.round(
                    profiles.reduce((m, p) => Math.max(m, p.length), 0) * 7.3
                  ) + 60
                )
              ),
            }}
          >
            <Text strong>Profile</Text>
            <Select
              style={{ width: "100%", marginTop: 8 }}
              placeholder="Select a profile"
              loading={loadingProfiles}
              value={profile}
              onChange={setProfile}
              options={profiles.map((p) => ({ value: p, label: p }))}
              showSearch
              optionFilterProp="label"
              allowClear
            />
          </div>
          <div style={{ minWidth: 180 }}>
            <Text strong>Select</Text>
            <Select
              style={{ width: "100%", marginTop: 8 }}
              value={select}
              onChange={setSelect}
              options={SELECT_OPTIONS}
            />
          </div>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={running}
            onClick={handleRun}
          >
            Run
          </Button>
        </Space>
        {runResult && (
          <Alert
            style={{ marginTop: 16 }}
            type={runResult.type}
            message={runResult.text}
            showIcon
            closable
            onClose={() => setRunResult(null)}
          />
        )}
      </Card>

      <Card
        title={`Running Cases (${runningCases.length})`}
        style={{ marginBottom: 16 }}
        extra={
          <Space>
            <Text type="secondary">{lastUpdated ? `Updated ${lastUpdated}` : ""}</Text>
            <Text>Auto refresh</Text>
            <Switch checked={polling} onChange={setPolling} />
            <InputNumber
              size="small"
              min={1}
              max={3600}
              style={{ width: 70 }}
              value={pollSec}
              onChange={(v) => setPollSec(Number(v) || DEFAULT_POLL_SEC)}
              addonAfter="s"
              disabled={!polling}
            />
            <Button size="small" icon={<ReloadOutlined />} onClick={refreshRunning}>
              Refresh
            </Button>
          </Space>
        }
      >
        <Input.Search
          style={{ width: 320, marginBottom: 12 }}
          placeholder="Search PID / profile / select"
          value={runningSearch}
          onChange={(e) => setRunningSearch(e.target.value)}
          allowClear
        />
        <Table<RunningCase>
          size="small"
          rowKey="pid"
          loading={loadingRunning}
          dataSource={runningCases.filter((r) => {
            const q = runningSearch.trim().toLowerCase();
            if (!q) return true;
            return `${r.pid} ${r.profile} ${r.select}`.toLowerCase().includes(q);
          })}
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
          columns={[
            { title: "PID", dataIndex: "pid", key: "pid", width: 100 },
            { title: "Profile", dataIndex: "profile", key: "profile", ellipsis: true },
            { title: "Select", dataIndex: "select", key: "select", width: 120 },
            {
              title: "Action",
              key: "action",
              width: 110,
              render: (_: unknown, r: RunningCase) => (
                <Popconfirm
                  title={`Stop PID ${r.pid}?`}
                  okText="Stop"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => handleStop(r.pid)}
                >
                  <Button
                    size="small"
                    danger
                    icon={<StopOutlined />}
                    loading={stoppingPid === r.pid}
                  >
                    Stop
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>

      <Card title="Running Suites" style={{ marginBottom: 16 }}>
        <Space style={{ marginBottom: 16 }}>
          <AutoComplete
            style={{ width: 260 }}
            placeholder="Enter or select user"
            value={suiteUser}
            onChange={setSuiteUser}
            options={users.map((u) => ({
              value: u,
              label: (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                  }}
                >
                  <span>{u}</span>
                  <Popconfirm
                    title={`Remove "${u}" from history?`}
                    okText="Remove"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => handleDeleteUser(u)}
                  >
                    <DeleteOutlined
                      style={{ color: "#999" }}
                      onClick={(e) => {
                        // Don't let the click select the option / fill the input.
                        e.stopPropagation();
                        e.preventDefault();
                      }}
                      onMouseDown={(e) => e.stopPropagation()}
                    />
                  </Popconfirm>
                </div>
              ),
            }))}
            filterOption={(input, option) =>
              String(option?.value ?? "").toLowerCase().includes(input.toLowerCase())
            }
            onKeyDown={(e) => {
              if (e.key === "Enter") querySuites();
            }}
            allowClear
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={loadingSuites}
            onClick={querySuites}
          >
            Query
          </Button>
        </Space>
        <Table<Suite>
          size="small"
          rowKey="id"
          loading={loadingSuites}
          dataSource={suites}
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
          columns={[
            { title: "Suite ID", dataIndex: "id", key: "id", width: 100 },
            {
              title: "Name",
              dataIndex: "name",
              key: "name",
              ellipsis: true,
              render: (name: string, r: Suite) => (
                <a onClick={() => openSuiteBuild(r.id)}>{name}</a>
              ),
            },
            { title: "State", dataIndex: "state", key: "state", width: 110,
              render: (s: string) => <Tag color="processing">{s}</Tag> },
            {
              title: "Progress",
              key: "progress",
              width: 160,
              render: (_: unknown, r: Suite) => (
                <Progress
                  percent={Math.round(r.progress)}
                  size="small"
                  format={() => `${r.tests_complete}/${r.tests_total}`}
                />
              ),
            },
            {
              title: "Action",
              key: "action",
              width: 130,
              render: (_: unknown, r: Suite) => (
                <Popconfirm
                  title={`Terminate suite ${r.id}?`}
                  okText="Terminate"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => handleTerminate(r.id)}
                >
                  <Button
                    size="small"
                    danger
                    icon={<StopOutlined />}
                    loading={terminatingId === r.id}
                  >
                    Terminate
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>

      <Card
        title="Run Results"
        extra={
          <Space>
            <Text type="secondary">{lastUpdated ? `Updated ${lastUpdated}` : ""}</Text>
            <Text>Auto refresh</Text>
            <Switch checked={polling} onChange={setPolling} />
            <InputNumber
              size="small"
              min={1}
              max={3600}
              style={{ width: 70 }}
              value={pollSec}
              onChange={(v) => setPollSec(Number(v) || DEFAULT_POLL_SEC)}
              addonAfter="s"
              disabled={!polling}
            />
            <Button size="small" icon={<ReloadOutlined />} onClick={refreshLists}>
              Refresh
            </Button>
            <Popconfirm
              title="Clear all cache & report files?"
              okText="Clear"
              okButtonProps={{ danger: true }}
              onConfirm={handleClear}
            >
              <Button size="small" danger icon={<ClearOutlined />} style={{ marginLeft: 16 }}>
                Clear
              </Button>
            </Popconfirm>
          </Space>
        }
      >
        <Row gutter={16}>
          <Col xs={24} lg={12}>
            <Text strong>Cache files ({caches.length})</Text>
            <Table
              style={{ marginTop: 8 }}
              size="small"
              rowKey="name"
              loading={loadingLists}
              columns={fileColumns(openCache, handleDeleteCache)}
              dataSource={caches}
              pagination={{ pageSize: 5, hideOnSinglePage: true }}
            />
          </Col>
          <Col xs={24} lg={12}>
            <Text strong>Summary reports ({reports.length})</Text>
            <Table
              style={{ marginTop: 8 }}
              size="small"
              rowKey="name"
              loading={loadingLists}
              columns={fileColumns(openReport, handleDeleteReport)}
              dataSource={reports}
              pagination={{ pageSize: 5, hideOnSinglePage: true }}
            />
          </Col>
        </Row>
      </Card>

      {/* File content viewer — table for cache/report JSON, raw text otherwise */}
      <Modal
        title={viewer?.title}
        open={!!viewer}
        onCancel={() => setViewer(null)}
        footer={null}
        // Auto-fit width to the content. For the table, size to the longest
        // log_url / case_ids; clamp 640–1300. Raw text keeps a wide default.
        width={
          viewer?.rows
            ? Math.min(
                1300,
                Math.max(
                  640,
                  Math.round(
                    Math.max(
                      0,
                      ...viewer.rows.map((r) =>
                        Math.max((r.log_url ?? "").length, r.case_ids.length * 2)
                      )
                    ) * 7
                  ) + 320
                )
              )
            : 900
        }
        style={{ top: 40 }}
        styles={{
          body: { paddingTop: 12 },
          content: { borderRadius: 12 },
          header: { marginBottom: 8 },
        }}
      >
        {viewer?.rows ? (
          <>
          <div style={{ marginBottom: 8, textAlign: "right" }}>
            <Button size="small" icon={<DownloadOutlined />} onClick={exportViewerMarkdown}>
              Export Markdown
            </Button>
          </div>
          <Table<TaskRow>
            size="small"
            rowKey="key"
            dataSource={viewer.rows}
            pagination={false}
            scroll={{ y: "80vh" }}
            columns={[
              {
                title: "TestRail Case ID",
                dataIndex: "testrail_case_ids",
                key: "testrail_case_ids",
                width: 150,
                render: (t: string) => {
                  if (!t) return "-";
                  // Comma-separated ids each get a TestRail link.
                  return t.split(",").map((raw, idx, arr) => {
                    const id = raw.trim();
                    return (
                      <span key={id || idx}>
                        {id ? (
                          <a
                            href={`https://testrail.eswat.roku.com/testrail/index.php?/cases/view/${id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {id}
                          </a>
                        ) : (
                          "-"
                        )}
                        {idx < arr.length - 1 ? ", " : ""}
                      </span>
                    );
                  });
                },
              },
              {
                title: "Automation ID",
                dataIndex: "case_ids",
                key: "case_ids",
                render: (c: string) => <span style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{c}</span>,
              },
              {
                title: "Status",
                dataIndex: "status",
                key: "status",
                width: 110,
                render: (s?: string) =>
                  s ? (
                    <Tag
                      color={
                        s === "Passed"
                          ? "success"
                          : s === "Failed"
                          ? "error"
                          : s === "Blocked"
                          ? "volcano"
                          : "default"
                      }
                    >
                      {s}
                    </Tag>
                  ) : (
                    "-"
                  ),
              },
              {
                title: "Build",
                dataIndex: "build_number",
                key: "build_number",
                width: 100,
                render: (b?: number | null) => (b ?? "-"),
              },
              {
                title: "Log",
                dataIndex: "log_url",
                key: "log_url",
                render: (u?: string | null) =>
                  u ? (
                    <a href={u} target="_blank" rel="noopener noreferrer">
                      log
                    </a>
                  ) : (
                    "-"
                  ),
              },
              {
                title: "Action",
                key: "action",
                width: 110,
                render: (_: unknown, row: TaskRow) => {
                  const isPass = /pass/i.test(row.status ?? "");
                  return (
                    <Button
                      type="primary"
                      size="small"
                      icon={<ExperimentOutlined />}
                      disabled={isPass || !row.log_url}
                      onClick={() => handleAnalyzeRow(row)}
                    >
                      Analyze
                    </Button>
                  );
                },
              },
            ]}
          />
          {viewer.progress && (
            <div style={{ marginTop: 8, textAlign: "left" }}>
              <Text strong>Progress: </Text>
              <Text>{viewer.progress}</Text>
            </div>
          )}
          {viewer.count !== undefined && (
            <div style={{ marginTop: 8, textAlign: "left" }}>
              <Text strong>Count: </Text>
              <Text>{viewer.count}</Text>
            </div>
          )}
          </>
        ) : (
          <pre
            style={{
              margin: 0,
              padding: 16,
              background: "#1e1e1e",
              color: "#d4d4d4",
              borderRadius: 6,
              maxHeight: "91vh",
              overflow: "auto",
              fontFamily: "'Fira Code', Consolas, monospace",
              fontSize: 13,
              lineHeight: 1.5,
              whiteSpace: "pre-wrap",
              border: "1px solid #424242",
            }}
          >
            {viewer?.content || "(empty)"}
          </pre>
        )}
      </Modal>

      {/* AI log analysis */}
      <Modal
        title={analyzeTitle}
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
