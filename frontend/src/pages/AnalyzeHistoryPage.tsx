import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import { ReloadOutlined, EyeOutlined, DeleteOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  listAnalyzeHistory,
  getAnalyzeHistory,
  deleteAnalyzeHistory,
  listProfileAnalyzeReports,
  deleteProfileAnalyzeReport,
  type AnalyzeHistoryItem,
  type ProfileAnalyzeReport,
} from "../api/client";

const { Title, Text } = Typography;

const RESULT_COLORS: Record<string, string> = {
  Failed: "error",
  Fail: "error",
  Blocked: "volcano",
  Skipped: "warning",
  Unknown: "default",
  Passed: "success",
  Pass: "success",
};

export default function AnalyzeHistoryPage() {
  // Full list loaded once; filtering is done client-side so typing a case id
  // filters instantly without per-keystroke server round-trips.
  const [allItems, setAllItems] = useState<AnalyzeHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);

  // Profile analyze reports (p__<profile>__<nopass>__<count>__<locale>__<dt>.yml)
  const [profileReports, setProfileReports] = useState<ProfileAnalyzeReport[]>([]);
  const [profileLoading, setProfileLoading] = useState(false);
  const [prProfile, setPrProfile] = useState<string | undefined>();
  const [prLocale, setPrLocale] = useState<string | undefined>();
  const [prDate, setPrDate] = useState<string | undefined>();

  // Filters
  const [testrailCaseId, setTestrailCaseId] = useState<string | undefined>();
  const [profile, setProfile] = useState<string | undefined>();
  const [caseId, setCaseId] = useState<string | undefined>();
  const [result, setResult] = useState<string | undefined>();
  const [locale, setLocale] = useState<string | undefined>();
  const [date, setDate] = useState<string | undefined>();

  // View modal
  const [viewOpen, setViewOpen] = useState(false);
  const [viewName, setViewName] = useState("");
  const [viewContent, setViewContent] = useState("");
  const [viewLoading, setViewLoading] = useState(false);

  const load = () => {
    setLoading(true);
    listAnalyzeHistory()
      .then(setAllItems)
      .catch((e: Error) => message.error(`Load failed: ${e.message}`))
      .finally(() => setLoading(false));
  };

  const loadProfileReports = () => {
    setProfileLoading(true);
    listProfileAnalyzeReports()
      .then(setProfileReports)
      .catch((e: Error) => message.error(`Load profile reports failed: ${e.message}`))
      .finally(() => setProfileLoading(false));
  };

  useEffect(load, []);
  useEffect(loadProfileReports, []);

  // While any profile is still analyzing, poll so the row flips from
  // "Analyzing n/m" to the case links on its own.
  const anyAnalyzing = profileReports.some((r) => r.status === "analyzing");
  useEffect(() => {
    if (!anyAnalyzing) return;
    // Refresh both lists: case reports written during the run become bound to
    // the profile report, which changes whether they can be deleted.
    const t = setInterval(() => {
      loadProfileReports();
      load();
    }, 5000);
    return () => clearInterval(t);
  }, [anyAnalyzing]); // eslint-disable-line react-hooks/exhaustive-deps

  // Distinct values for the profile-report filters.
  const prProfileOptions = Array.from(
    new Set(profileReports.map((i) => i.profile_name).filter(Boolean))
  ).sort();
  const prLocaleOptions = Array.from(
    new Set(profileReports.map((i) => i.locale).filter(Boolean))
  ).sort();
  const prDateOptions = Array.from(
    new Set(profileReports.map((i) => i.date).filter(Boolean))
  ).sort((a, b) => b.localeCompare(a));

  const filteredProfileReports = profileReports.filter((i) => {
    if (prProfile && i.profile_name !== prProfile) return false;
    if (prLocale && i.locale !== prLocale) return false;
    if (prDate && i.date !== prDate) return false;
    return true;
  });

  const handleDeleteProfileReport = async (name: string) => {
    try {
      const res = await deleteProfileAnalyzeReport(name);
      message.success(res.message);
      loadProfileReports();
      // Its case reports may now be unbound (deletable) -- refresh that list.
      load();
    } catch (e) {
      message.error(`Delete failed: ${(e as Error).message}`);
    }
  };

  // Distinct values for the dropdown filters.
  const testrailOptions = Array.from(
    new Set(allItems.map((i) => i.testrail_case_id).filter(Boolean))
  ).sort();
  const profileOptions = Array.from(
    new Set(allItems.map((i) => i.profile).filter(Boolean))
  ).sort();
  const caseIdOptions = Array.from(
    new Set(allItems.map((i) => i.case_id).filter(Boolean))
  ).sort();
  const resultOptions = Array.from(
    new Set(allItems.map((i) => i.result).filter(Boolean))
  ).sort();
  const localeOptions = Array.from(
    new Set(allItems.map((i) => i.locale).filter(Boolean))
  ).sort();
  const dateOptions = Array.from(
    new Set(allItems.map((i) => i.date).filter(Boolean))
  ).sort((a, b) => b.localeCompare(a));

  // Client-side filtered view.
  const items = allItems.filter((i) => {
    if (testrailCaseId && i.testrail_case_id !== testrailCaseId) return false;
    if (profile && i.profile !== profile) return false;
    if (caseId && i.case_id !== caseId) return false;
    if (result && i.result !== result) return false;
    if (locale && i.locale !== locale) return false;
    if (date && i.date !== date) return false;
    return true;
  });

  const openView = async (name: string) => {
    setViewName(name);
    setViewContent("");
    setViewOpen(true);
    setViewLoading(true);
    try {
      setViewContent(await getAnalyzeHistory(name));
    } catch (e) {
      message.error(`Open failed: ${(e as Error).message}`);
      setViewOpen(false);
    } finally {
      setViewLoading(false);
    }
  };

  const handleDelete = async (name: string) => {
    try {
      const res = await deleteAnalyzeHistory(name);
      message.success(res.message);
      load();
    } catch (e) {
      message.error(`Delete failed: ${(e as Error).message}`);
    }
  };

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>
        Analyze History
      </Title>
      {/* Profile-level analyze reports, one row per profile run. */}
      <Card
        style={{ marginBottom: 16 }}
        title={`Profile Analyze Reports (${filteredProfileReports.length})`}
        extra={
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={loadProfileReports}
            loading={profileLoading}
          >
            Refresh
          </Button>
        }
      >
        <Space style={{ marginBottom: 12 }} wrap>
          <Select
            allowClear
            showSearch
            placeholder="profile"
            style={{
              width: Math.min(
                600,
                Math.max(
                  200,
                  prProfileOptions.reduce((m, c) => Math.max(m, c.length), 10) * 8 + 56
                )
              ),
            }}
            value={prProfile}
            onChange={setPrProfile}
            options={prProfileOptions.map((p) => ({ value: p, label: p }))}
          />
          <Select
            allowClear
            placeholder="locale"
            style={{ minWidth: 130 }}
            value={prLocale}
            onChange={setPrLocale}
            options={prLocaleOptions.map((l) => ({ value: l, label: l }))}
          />
          <Select
            allowClear
            showSearch
            placeholder="date"
            style={{ minWidth: 150 }}
            value={prDate}
            onChange={setPrDate}
            options={prDateOptions.map((d) => ({ value: d, label: d }))}
          />
        </Space>
        <Table<ProfileAnalyzeReport>
          size="small"
          rowKey="name"
          loading={profileLoading}
          dataSource={filteredProfileReports}
          tableLayout="fixed"
          pagination={{ defaultPageSize: 10, pageSizeOptions: [10, 15, 30, 50], showSizeChanger: true }}
          columns={[
            {
              title: "Profile Name",
              dataIndex: "profile_name",
              key: "profile_name",
              ellipsis: true,
              sorter: (a, b) => a.profile_name.localeCompare(b.profile_name),
              render: (p: string) => p || "-",
            },
            {
              title: "NoPass Cases",
              dataIndex: "count_nopass_case",
              key: "count_nopass_case",
              width: 130,
              sorter: (a, b) => a.count_nopass_case - b.count_nopass_case,
              render: (n: number) =>
                n > 0 ? <Tag color="error">{n}</Tag> : <Tag color="success">0</Tag>,
            },
            {
              title: "Total Cases",
              dataIndex: "count_case",
              key: "count_case",
              width: 120,
              sorter: (a, b) => a.count_case - b.count_case,
            },
            {
              title: "Locale",
              dataIndex: "locale",
              key: "locale",
              width: 90,
            },
            {
              title: "Date/Time",
              dataIndex: "datetime",
              key: "datetime",
              width: 190,
              sorter: (a, b) => a.datetime.localeCompare(b.datetime),
              defaultSortOrder: "descend",
              render: (dt: string) => (dt ? dt.replace("_", " ") : "-"),
            },
            {
              title: "Case Report",
              key: "cases",
              render: (_, r) => {
                // Case links only appear once every non-passing case has been
                // analyzed; until then the row reports its progress.
                if (r.status === "analyzing") {
                  return (
                    <Space size={6}>
                      <Spin size="small" />
                      <Tag color="processing">
                        Analyzing {r.analyzed_count}/{r.count_nopass_case}
                      </Tag>
                    </Space>
                  );
                }
                if (!r.cases || !r.cases.length) return "-";
                return (
                  <span>
                    {r.cases.map((c, idx) => (
                      <span key={c.name}>
                        {/* Clicking shows the case's analyze report in the modal. */}
                        <a onClick={() => openView(c.name)}>
                          {c.testrail_case_id || c.name}
                        </a>
                        {idx < r.cases.length - 1 ? ", " : ""}
                      </span>
                    ))}
                  </span>
                );
              },
            },
            {
              title: "Action",
              key: "action",
              width: 100,
              render: (_, r) => (
                <Popconfirm
                  title="Delete this profile report?"
                  okText="Delete"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => handleDeleteProfileReport(r.name)}
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

      <Card
        title={`Saved Analyses (${items.length})`}
        extra={
          <Button size="small" icon={<ReloadOutlined />} onClick={load} loading={loading}>
            Refresh
          </Button>
        }
      >
        <Space style={{ marginBottom: 12 }} wrap>
          <Select
            allowClear
            showSearch
            placeholder="testrail_case_id"
            // Width auto-fits the longest testrail_case_id value.
            style={{
              width: Math.min(
                600,
                Math.max(
                  180,
                  testrailOptions.reduce((m, c) => Math.max(m, c.length), 10) * 8 + 56
                )
              ),
            }}
            value={testrailCaseId}
            onChange={setTestrailCaseId}
            options={testrailOptions.map((c) => ({ value: c, label: c }))}
          />
          <Select
            allowClear
            showSearch
            placeholder="profile"
            // Width auto-fits the longest profile value.
            style={{
              width: Math.min(
                600,
                Math.max(
                  180,
                  profileOptions.reduce((m, c) => Math.max(m, c.length), 10) * 8 + 56
                )
              ),
            }}
            value={profile}
            onChange={setProfile}
            options={profileOptions.map((p) => ({ value: p, label: p }))}
          />
          <Select
            allowClear
            showSearch
            placeholder="case_id"
            // Width auto-fits the longest case_id (≈8px/char + icon/padding room),
            // clamped so it never gets absurdly narrow or wide.
            style={{
              width: Math.min(
                600,
                Math.max(
                  180,
                  caseIdOptions.reduce((m, c) => Math.max(m, c.length), 8) * 8 + 56
                )
              ),
            }}
            value={caseId}
            onChange={setCaseId}
            options={caseIdOptions.map((c) => ({ value: c, label: c }))}
          />
          <Select
            allowClear
            placeholder="result"
            style={{ minWidth: 150 }}
            value={result}
            onChange={setResult}
            options={resultOptions.map((r) => ({ value: r, label: r }))}
          />
          <Select
            allowClear
            placeholder="locale"
            style={{ minWidth: 130 }}
            value={locale}
            onChange={setLocale}
            options={localeOptions.map((l) => ({ value: l, label: l }))}
          />
          <Select
            allowClear
            showSearch
            placeholder="date"
            style={{ minWidth: 150 }}
            value={date}
            onChange={setDate}
            options={dateOptions.map((d) => ({ value: d, label: d }))}
          />
        </Space>
        <Table<AnalyzeHistoryItem>
          size="small"
          rowKey="name"
          loading={loading}
          dataSource={items}
          // Fixed layout + explicit column widths so columns never reflow when
          // the filtered row set changes.
          tableLayout="fixed"
          pagination={{ defaultPageSize: 15, pageSizeOptions: [10, 15, 30, 50], showSizeChanger: true }}
          columns={[
            {
              title: "TestRail Case ID",
              dataIndex: "testrail_case_id",
              key: "testrail_case_id",
              width: 160,
              sorter: (a, b) => a.testrail_case_id.localeCompare(b.testrail_case_id),
              render: (t: string) => {
                if (!t) return "-";
                // Only link when the id is purely numeric; otherwise show plain text.
                return /^\d+$/.test(t) ? (
                  <a
                    href={`https://testrail.eswat.roku.com/testrail/index.php?/cases/view/${t}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t}
                  </a>
                ) : (
                  t
                );
              },
            },
            {
              title: "Profile",
              dataIndex: "profile",
              key: "profile",
              width: 180,
              ellipsis: true,
              sorter: (a, b) => a.profile.localeCompare(b.profile),
              render: (p: string) => p || "-",
            },
            {
              title: "Case ID",
              dataIndex: "case_id",
              key: "case_id",
              ellipsis: true,
              sorter: (a, b) => a.case_id.localeCompare(b.case_id),
            },
            {
              title: "Result",
              dataIndex: "result",
              key: "result",
              width: 110,
              render: (r: string) =>
                r ? <Tag color={RESULT_COLORS[r] ?? "default"}>{r}</Tag> : "-",
            },
            {
              title: "Locale",
              dataIndex: "locale",
              key: "locale",
              width: 90,
            },
            {
              title: "Date/Time",
              dataIndex: "datetime",
              key: "datetime",
              width: 200,
              sorter: (a, b) => a.datetime.localeCompare(b.datetime),
              defaultSortOrder: "descend",
              render: (dt: string) => dt.replace("_", " "),
            },
            {
              title: "Action",
              key: "action",
              width: 150,
              render: (_, r) => (
                <Space>
                  <Button size="small" icon={<EyeOutlined />} onClick={() => openView(r.name)}>
                    View
                  </Button>
                  {r.bound_profile_reports && r.bound_profile_reports.length > 0 ? (
                    // Bound to a profile report: deleting it would leave that
                    // report pointing at a missing file, so it's blocked here
                    // (and by the backend, which returns 409).
                    <Tooltip
                      title={
                        <div>
                          Used by Profile Analyze Report(s):
                          {r.bound_profile_reports.map((p) => (
                            <div key={p} style={{ fontFamily: "monospace", fontSize: 12 }}>
                              {p}
                            </div>
                          ))}
                          Delete the profile report first.
                        </div>
                      }
                    >
                      <Button size="small" danger disabled icon={<DeleteOutlined />}>
                        Delete
                      </Button>
                    </Tooltip>
                  ) : (
                    <Popconfirm
                      title="Delete this analysis?"
                      okText="Delete"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => handleDelete(r.name)}
                    >
                      <Button size="small" danger icon={<DeleteOutlined />}>
                        Delete
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      {/* Markdown view — width fits content, height 2/3 viewport */}
      <Modal
        title={viewName}
        open={viewOpen}
        onCancel={() => setViewOpen(false)}
        footer={null}
        width="fit-content"
        styles={{ body: { maxHeight: "66vh", overflow: "auto" } }}
      >
        <div className="chat-markdown" style={{ minWidth: 360, maxWidth: "80vw" }}>
          {viewLoading ? (
            <Text type="secondary">Loading…</Text>
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{viewContent}</ReactMarkdown>
          )}
        </div>
      </Modal>
    </div>
  );
}
