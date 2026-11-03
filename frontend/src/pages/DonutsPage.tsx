import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Empty,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  PlayCircleOutlined,
  ReloadOutlined,
  StopOutlined,
  DeleteOutlined,
  LinkOutlined,
  ProfileOutlined,
} from "@ant-design/icons";
import {
  listDevices,
  listDonutsForDevice,
  triggerDonutRun,
  listDonutRuns,
  abortDonutJob,
  cancelQueuedDonutRun,
  getDonutResults,
  deleteDonutRun,
  type DonutOption,
  type DonutRun,
  type DonutJob,
  type DonutQueued,
  type DonutResult,
} from "../api/client";

const { Title, Text, Paragraph } = Typography;

// Poll the run list while anything is still in flight. A donut takes minutes,
// so a 10s cadence is plenty and keeps the API load low.
const POLL_MS = 10000;

// Run-level status -> tag color.
const STATUS_COLORS: Record<string, string> = {
  running: "processing",
  queued: "warning",
  finished: "success",
};

const fmtTime = (iso?: string | null) =>
  iso ? String(iso).replace("T", " ").slice(0, 19) : "-";

export default function DonutsPage() {
  // ---- trigger form ----
  const [devices, setDevices] = useState<string[]>([]);
  const [device, setDevice] = useState<string>();
  const [serial, setSerial] = useState("");
  const [options, setOptions] = useState<DonutOption[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);
  // Index into `options` — (product, donut, branch) is the real key.
  const [optionIdx, setOptionIdx] = useState<number>();
  const [buildNumber, setBuildNumber] = useState("");
  const [downstream, setDownstream] = useState(false);
  const [cloudSerialLogs, setCloudSerialLogs] = useState(false);
  const [triggering, setTriggering] = useState(false);

  // ---- run list ----
  const [runs, setRuns] = useState<DonutRun[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [aborting, setAborting] = useState<string | null>(null);

  // ---- results modal ----
  const [results, setResults] = useState<DonutResult[] | null>(null);
  const [resultsRun, setResultsRun] = useState<DonutRun | null>(null);
  const [resultsOpen, setResultsOpen] = useState(false);
  const [resultsLoading, setResultsLoading] = useState(false);

  // Keep the polling timer in a ref so refreshes never stack up, and guard
  // against overlapping requests (a slow QA Hub reply must not queue more).
  const timerRef = useRef<number | null>(null);
  const inFlightRef = useRef(false);

  useEffect(() => {
    listDevices()
      .then(setDevices)
      .catch((e: Error) => message.error(`Load devices failed: ${e.message}`));
  }, []);

  // When the device changes, ask QA Hub which donuts it is registered on.
  useEffect(() => {
    setOptions([]);
    setOptionIdx(undefined);
    setSerial("");
    if (!device) return;
    let cancelled = false; // ignore a slow reply for a device we left
    setOptionsLoading(true);
    listDonutsForDevice(device)
      .then((d) => {
        if (cancelled) return;
        setSerial(d.serial_number);
        setOptions(d.donuts);
        if (d.donuts.length === 0) {
          message.warning(
            `Device '${device}' (${d.serial_number}) is not registered on any donut`
          );
        }
      })
      .catch((e: Error) => {
        if (!cancelled) message.error(`Load donuts failed: ${e.message}`);
      })
      .finally(() => {
        if (!cancelled) setOptionsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [device]);

  const refreshRuns = useCallback(async (quiet = false) => {
    // Skip this tick if the previous poll is still outstanding.
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    if (!quiet) setLoadingRuns(true);
    try {
      setRuns(await listDonutRuns(30));
    } catch (e) {
      if (!quiet) message.error(`Load runs failed: ${(e as Error).message}`);
    } finally {
      inFlightRef.current = false;
      if (!quiet) setLoadingRuns(false);
    }
  }, []);

  useEffect(() => {
    refreshRuns();
  }, [refreshRuns]);

  // Poll only while something is running, so an idle page is quiet. Depends on
  // a boolean (not the whole runs array) so the interval is not torn down and
  // rebuilt on every poll result.
  const anyRunning = runs.some((r) => r.running);
  useEffect(() => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (anyRunning) {
      timerRef.current = window.setInterval(() => refreshRuns(true), POLL_MS);
    }
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, [anyRunning, refreshRuns]);

  const handleTrigger = async () => {
    if (!device || optionIdx === undefined || !buildNumber.trim()) {
      message.warning("Select a device, a donut and enter a build number");
      return;
    }
    const opt = options[optionIdx];
    setTriggering(true);
    try {
      const res = await triggerDonutRun({
        device,
        product: opt.product,
        branch: opt.branch,
        donut: opt.donut,
        build_number: buildNumber.trim(),
        run_downstream_donuts: downstream,
        cloud_serial_logs: cloudSerialLogs,
      });
      message.success(res.message);
      if (res.run?.queued_run_id) {
        const busy = Object.entries(res.run.busy_devices ?? {})
          .map(([k, v]) => `${k}: ${v}`)
          .join("; ");
        message.info(`Queued (device busy)${busy ? ` — ${busy}` : ""}`, 6);
      }
      // A launch reaches Jenkins asynchronously, so the job will not appear in
      // the very next poll; refresh now and again shortly after.
      refreshRuns();
      window.setTimeout(() => refreshRuns(true), 8000);
    } catch (e) {
      message.error(`Trigger failed: ${(e as Error).message}`);
    } finally {
      setTriggering(false);
    }
  };

  const handleAbortJob = async (run: DonutRun, job: DonutJob) => {
    const key = `${run.id}-job-${job.build_number}`;
    setAborting(key);
    try {
      const res = await abortDonutJob({
        product: run.product,
        branch: run.branch,
        build_number: job.build_number,
        job_name: job.job_name,
      });
      message.success(res.message);
      refreshRuns();
    } catch (e) {
      message.error(`Abort failed: ${(e as Error).message}`);
    } finally {
      setAborting(null);
    }
  };

  const handleCancelQueued = async (run: DonutRun, q: DonutQueued) => {
    const key = `${run.id}-q-${q.queued_run_id}`;
    setAborting(key);
    try {
      const res = await cancelQueuedDonutRun({
        product: run.product,
        branch: run.branch,
        queued_run_id: q.queued_run_id,
      });
      message.success(res.message);
      refreshRuns();
    } catch (e) {
      message.error(`Cancel failed: ${(e as Error).message}`);
    } finally {
      setAborting(null);
    }
  };

  const openResults = async (run: DonutRun) => {
    setResultsOpen(true);
    setResultsLoading(true);
    setResults(null);
    setResultsRun(run);
    try {
      setResults(
        await getDonutResults(run.build_number, {
          serial_number: run.serial_number,
          donut: run.donut,
        })
      );
    } catch (e) {
      message.error(`Load results failed: ${(e as Error).message}`);
      setResultsOpen(false);
    } finally {
      setResultsLoading(false);
    }
  };

  const handleDeleteRun = async (runId: string) => {
    try {
      await deleteDonutRun(runId);
      message.success("Run removed from history");
      refreshRuns();
    } catch (e) {
      message.error(`Remove failed: ${(e as Error).message}`);
    }
  };

  const runColumns = [
    { title: "Device", dataIndex: "device", key: "device", width: 165 },
    {
      title: "Donut",
      key: "donut",
      render: (_: unknown, r: DonutRun) => (
        <Space direction="vertical" size={0}>
          <Text strong>{r.donut}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {r.product} / {r.branch}
          </Text>
        </Space>
      ),
    },
    { title: "Build", dataIndex: "build_number", key: "build_number", width: 140 },
    {
      title: "Status",
      key: "status",
      width: 120,
      render: (_: unknown, r: DonutRun) => (
        <Tag color={STATUS_COLORS[r.status] ?? "default"}>{r.status}</Tag>
      ),
    },
    {
      title: "Triggered",
      dataIndex: "triggered_at",
      key: "triggered_at",
      width: 165,
      render: (t: string) => fmtTime(t),
    },
    {
      title: "Action",
      key: "action",
      width: 200,
      render: (_: unknown, r: DonutRun) => (
        <Space>
          <Button size="small" icon={<ProfileOutlined />} onClick={() => openResults(r)}>
            Results
          </Button>
          <Popconfirm
            title="Remove from history?"
            description="Only removes the local record; QA Hub is untouched."
            onConfirm={() => handleDeleteRun(r.id)}
          >
            <Button size="small" type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const selectedOption = optionIdx !== undefined ? options[optionIdx] : undefined;

  // Expanded row: the live Jenkins job(s) and/or queued request(s) for a run.
  const expandedRow = (r: DonutRun) => {
    if (r.jobs.length === 0 && r.queued.length === 0) {
      return (
        <Text type="secondary">
          No running Jenkins job or queued request matches this run. It has either
          finished (use <b>Results</b>) or has not reached Jenkins yet.
        </Text>
      );
    }
    return (
      <Space direction="vertical" size="small" style={{ width: "100%" }}>
        {r.jobs.map((j) => (
          <Card size="small" key={`${j.job_name}-${j.build_number}`}>
            <Row gutter={[12, 8]} align="middle">
              <Col xs={24} md={14}>
                <Space direction="vertical" size={0}>
                  <Text strong>{j.donut_display_name || j.donut}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {j.serial_number} · target {j.target_build || "-"}
                    {j.launched_by ? ` · by ${j.launched_by}` : ""}
                  </Text>
                  <Space size="small" wrap>
                    {j.jenkins_url && (
                      <a href={j.jenkins_url} target="_blank" rel="noreferrer">
                        Jenkins #{j.build_number} <LinkOutlined />
                      </a>
                    )}
                    {j.testrail_link && (
                      <a href={j.testrail_link} target="_blank" rel="noreferrer">
                        TestRail plan <LinkOutlined />
                      </a>
                    )}
                  </Space>
                </Space>
              </Col>
              <Col xs={24} md={10} style={{ textAlign: "right" }}>
                <Space>
                  <Tag color="processing">running</Tag>
                  <Popconfirm
                    title="Terminate this donut job?"
                    description="Stops the Jenkins job that is executing this donut."
                    onConfirm={() => handleAbortJob(r, j)}
                  >
                    <Button
                      size="small"
                      danger
                      icon={<StopOutlined />}
                      loading={aborting === `${r.id}-job-${j.build_number}`}
                    >
                      Abort
                    </Button>
                  </Popconfirm>
                </Space>
              </Col>
            </Row>
          </Card>
        ))}

        {r.queued.map((q) => (
          <Card size="small" key={`q-${q.queued_run_id}`}>
            <Row gutter={[12, 8]} align="middle">
              <Col xs={24} md={16}>
                <Space direction="vertical" size={0}>
                  <Text strong>{q.donut || r.donut}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    queued id {q.queued_run_id} · build {q.build_number || "-"}
                    {q.username ? ` · by ${q.username}` : ""}
                  </Text>
                  {q.launch_detail && (
                    <Tooltip title={q.launch_detail}>
                      <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                        {q.launch_detail.slice(0, 110)}
                      </Text>
                    </Tooltip>
                  )}
                </Space>
              </Col>
              <Col xs={24} md={8} style={{ textAlign: "right" }}>
                <Space>
                  <Tag color={q.launch_state === "attention" ? "error" : "warning"}>
                    {q.launch_state || "queued"}
                  </Tag>
                  <Popconfirm
                    title="Cancel this queued run?"
                    onConfirm={() => handleCancelQueued(r, q)}
                  >
                    <Button
                      size="small"
                      danger
                      icon={<StopOutlined />}
                      loading={aborting === `${r.id}-q-${q.queued_run_id}`}
                    >
                      Cancel
                    </Button>
                  </Popconfirm>
                </Space>
              </Col>
            </Row>
          </Card>
        ))}
      </Space>
    );
  };

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Title level={4} style={{ margin: 0 }}>
        Donuts
      </Title>

      <Card size="small" title="Trigger a donut run">
        <Row gutter={[12, 12]}>
          <Col xs={24} md={6}>
            <Text type="secondary" style={{ fontSize: 12 }}>Device</Text>
            <Select
              showSearch
              placeholder="Select device"
              style={{ width: "100%" }}
              value={device}
              onChange={setDevice}
              options={devices.map((d) => ({ label: d, value: d }))}
            />
            {serial && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                serial: {serial}
              </Text>
            )}
          </Col>
          <Col xs={24} md={10}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              Donut (only those this device is registered on)
            </Text>
            <Select
              showSearch
              placeholder={optionsLoading ? "Loading..." : "Select donut"}
              style={{ width: "100%" }}
              loading={optionsLoading}
              value={optionIdx}
              onChange={setOptionIdx}
              disabled={!device || options.length === 0}
              optionFilterProp="label"
              options={options.map((o, i) => ({
                label: `${o.donut} — ${o.product} / ${o.branch}`,
                value: i,
              }))}
            />
          </Col>
          <Col xs={24} md={8}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              Build number (TeamCity format, e.g. 16.1.4.00100)
            </Text>
            <Select
              mode="tags"
              maxCount={1}
              style={{ width: "100%" }}
              placeholder="e.g. 16.1.4.00100"
              value={buildNumber ? [buildNumber] : []}
              onChange={(v) => setBuildNumber(v[v.length - 1] ?? "")}
              options={[]}
            />
          </Col>
        </Row>

        <Row gutter={[12, 12]} style={{ marginTop: 12 }} align="middle">
          <Col>
            <Checkbox checked={downstream} onChange={(e) => setDownstream(e.target.checked)}>
              Run downstream donuts
            </Checkbox>
          </Col>
          <Col>
            <Checkbox
              checked={cloudSerialLogs}
              onChange={(e) => setCloudSerialLogs(e.target.checked)}
            >
              Cloud serial logs
            </Checkbox>
          </Col>
          <Col flex="auto" style={{ textAlign: "right" }}>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => refreshRuns()} loading={loadingRuns}>
                Refresh
              </Button>
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={triggering}
                onClick={handleTrigger}
                disabled={!device || optionIdx === undefined || !buildNumber.trim()}
              >
                Trigger
              </Button>
            </Space>
          </Col>
        </Row>

        {selectedOption && (
          <Alert
            style={{ marginTop: 12 }}
            type="info"
            showIcon
            message={
              <Text style={{ fontSize: 12 }}>
                Will run <b>{selectedOption.donut}</b> on <b>{serial}</b> (
                {selectedOption.platform_name || "unknown platform"}) for{" "}
                <b>{selectedOption.product} / {selectedOption.branch}</b>
              </Text>
            }
          />
        )}
      </Card>

      <Card
        size="small"
        title="Runs triggered from QATools"
        extra={
          <Text type="secondary" style={{ fontSize: 12 }}>
            {anyRunning ? `auto-refreshing every ${POLL_MS / 1000}s` : "idle"}
          </Text>
        }
      >
        <Table
          rowKey="id"
          size="small"
          loading={loadingRuns}
          dataSource={runs}
          columns={runColumns}
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
          locale={{
            emptyText: <Empty description="No donut runs triggered from QATools yet" />,
          }}
          expandable={{ defaultExpandAllRows: true, expandedRowRender: expandedRow }}
        />
      </Card>

      <Modal
        title={
          resultsRun
            ? `Results — ${resultsRun.donut} @ ${resultsRun.build_number}`
            : "Results"
        }
        open={resultsOpen}
        onCancel={() => setResultsOpen(false)}
        footer={null}
        width={900}
      >
        {resultsLoading && <Text>Loading...</Text>}
        {results && resultsRun && (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="Device">{resultsRun.device}</Descriptions.Item>
              <Descriptions.Item label="Serial">{resultsRun.serial_number}</Descriptions.Item>
              <Descriptions.Item label="Donut">{resultsRun.donut}</Descriptions.Item>
              <Descriptions.Item label="Build">{resultsRun.build_number}</Descriptions.Item>
            </Descriptions>

            {results.length === 0 ? (
              <Alert
                type="info"
                showIcon
                message="No finished donut result reported for this build/device yet."
                description="QA Hub only publishes a result once the donut completes. If the run is still executing, check the running job above."
              />
            ) : (
              <Table
                rowKey="id"
                size="small"
                dataSource={results}
                pagination={{ pageSize: 20, hideOnSinglePage: true }}
                columns={[
                  { title: "Donut", dataIndex: "run_type", key: "run_type", width: 150 },
                  { title: "Device", dataIndex: "device", key: "device", width: 150 },
                  {
                    title: "Pass %",
                    dataIndex: "pass_percentage",
                    key: "pass_percentage",
                    width: 100,
                    render: (p: number | null) =>
                      p == null ? (
                        "-"
                      ) : (
                        <Tag color={p >= 95 ? "success" : p >= 80 ? "warning" : "error"}>
                          {p.toFixed(1)}%
                        </Tag>
                      ),
                  },
                  {
                    title: "Stage",
                    dataIndex: "stage",
                    key: "stage",
                    width: 110,
                    render: (s: string) => (
                      <Tag color={s === "complete" ? "success" : "processing"}>{s || "-"}</Tag>
                    ),
                  },
                  {
                    title: "Re-ran failures",
                    dataIndex: "failures_re_ran",
                    key: "failures_re_ran",
                    width: 130,
                    render: (v: boolean | null) => (v ? "yes" : "no"),
                  },
                  {
                    title: "Logs",
                    key: "logs",
                    width: 120,
                    render: (_: unknown, r: DonutResult) =>
                      r.logs_url ? (
                        <a href={r.logs_url} target="_blank" rel="noreferrer">
                          suite {r.suite_id} <LinkOutlined />
                        </a>
                      ) : (
                        "-"
                      ),
                  },
                ]}
              />
            )}
          </Space>
        )}
      </Modal>

      <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
        Donut runs are executed by QA Hub via Jenkins, so a launch is asynchronous: a
        triggered run appears as <Text code>queued</Text> while the device is busy, then
        as <Text code>running</Text> once Jenkins picks it up, and finally reports a pass
        rate under <b>Results</b>. <b>Abort</b> terminates the Jenkins job that owns the run.
      </Paragraph>
    </Space>
  );
}
