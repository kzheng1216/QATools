import { useEffect, useRef, useState } from "react";
import {
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tabs,
  Typography,
  message,
} from "antd";
import {
  ReloadOutlined,
  SwapOutlined,
  SendOutlined,
  PlusOutlined,
  EyeOutlined,
  EditOutlined,
  DeleteOutlined,
  RobotOutlined,
  ClearOutlined,
  SaveOutlined,
  CopyOutlined,
  DownloadOutlined,
} from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  getAgentInfo,
  switchAgent,
  listAgentModels,
  agentChat,
  listSkills,
  getSkill,
  addSkill,
  updateSkill,
  deleteSkill,
  exportSkillsUrl,
  listSessions,
  getSession,
  createSession,
  deleteSession,
  type AgentInfo,
  type AgentModel,
  type SessionSummary,
  type SessionMessage,
} from "../api/client";

const { Title, Text } = Typography;

export default function AgentPage() {
  const [info, setInfo] = useState<AgentInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [models, setModels] = useState<AgentModel[]>([]);

  // Switch form (model only)
  const [model, setModel] = useState<string>();
  const [switching, setSwitching] = useState(false);

  // Chat
  const [prompt, setPrompt] = useState("");
  const [chatting, setChatting] = useState(false);
  const [answer, setAnswer] = useState<{ text: string; model: string; time: number } | null>(null);

  // Chat sessions (multi-turn conversation persistence)
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [history, setHistory] = useState<SessionMessage[]>([]);
  const historyRef = useRef<HTMLDivElement>(null);

  // Skills
  const [skills, setSkills] = useState<string[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [viewSkill, setViewSkill] = useState<{ name: string; content: string } | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [newSkillName, setNewSkillName] = useState("");
  const [newSkillContent, setNewSkillContent] = useState("");
  const [savingSkill, setSavingSkill] = useState(false);
  // When set, the Add modal is in Edit mode for this existing skill name.
  const [editSkillName, setEditSkillName] = useState<string | null>(null);

  // Prompt Run: skills appended into the prompt box (all stay highlighted)
  const [activeSkills, setActiveSkills] = useState<string[]>([]);

  const loadSkills = () => {
    setSkillsLoading(true);
    listSkills()
      .then(setSkills)
      .catch((e: Error) => message.error(`Load skills failed: ${e.message}`))
      .finally(() => setSkillsLoading(false));
  };

  const handleViewSkill = async (name: string) => {
    try {
      const content = await getSkill(name);
      setViewSkill({ name, content });
    } catch (e) {
      message.error(`View skill failed: ${(e as Error).message}`);
    }
  };

  const openAddSkill = () => {
    setEditSkillName(null);
    setNewSkillName("");
    setNewSkillContent("");
    setAddOpen(true);
  };

  const openEditSkill = async (name: string) => {
    try {
      const content = await getSkill(name);
      setEditSkillName(name);
      setNewSkillName(name);
      setNewSkillContent(content);
      setAddOpen(true);
    } catch (e) {
      message.error(`Load skill failed: ${(e as Error).message}`);
    }
  };

  const handleSaveSkill = async () => {
    const name = newSkillName.trim();
    if (!name) {
      message.warning("Please enter a skill name");
      return;
    }
    if (!newSkillContent.trim()) {
      message.warning("Please enter skill content");
      return;
    }
    setSavingSkill(true);
    try {
      const res = editSkillName
        ? await updateSkill(editSkillName, newSkillContent)
        : await addSkill(name, newSkillContent);
      message.success(res.message);
      setAddOpen(false);
      setEditSkillName(null);
      setNewSkillName("");
      setNewSkillContent("");
      loadSkills();
    } catch (e) {
      message.error(
        `${editSkillName ? "Update" : "Add"} skill failed: ${(e as Error).message}`
      );
    } finally {
      setSavingSkill(false);
    }
  };

  const handleDeleteSkill = async (name: string) => {
    try {
      const res = await deleteSkill(name);
      message.success(res.message);
      loadSkills();
    } catch (e) {
      message.error(`Delete skill failed: ${(e as Error).message}`);
    }
  };

  const handleAppendSkill = async (name: string) => {
    try {
      const content = await getSkill(name);
      setPrompt((prev) => (prev.trim() ? `${prev}\n\n${content}` : content));
      setActiveSkills((prev) => (prev.includes(name) ? prev : [...prev, name]));
    } catch (e) {
      message.error(`Add skill failed: ${(e as Error).message}`);
    }
  };

  const handleClearPrompt = () => {
    setPrompt("");
    setActiveSkills([]);
    setAnswer(null);
  };

  // ---------- Chat sessions ----------
  const loadSessions = () => {
    listSessions()
      .then(setSessions)
      .catch((e: Error) => message.error(`Load sessions failed: ${e.message}`));
  };

  const handleSelectSession = async (id: string) => {
    setCurrentSessionId(id);
    setAnswer(null);
    try {
      const detail = await getSession(id);
      setHistory(detail.messages);
    } catch (e) {
      message.error(`Load session failed: ${(e as Error).message}`);
      setHistory([]);
    }
  };

  const handleNewSession = async () => {
    try {
      const detail = await createSession();
      setCurrentSessionId(detail.id);
      setHistory([]);
      setAnswer(null);
      loadSessions();
    } catch (e) {
      message.error(`Create session failed: ${(e as Error).message}`);
    }
  };

  const handleDeleteSession = async () => {
    if (!currentSessionId) return;
    try {
      await deleteSession(currentSessionId);
      message.success("Session deleted");
      setCurrentSessionId(null);
      setHistory([]);
      setAnswer(null);
      loadSessions();
    } catch (e) {
      message.error(`Delete session failed: ${(e as Error).message}`);
    }
  };

  const handleSaveResult = async () => {
    if (!answer) return;
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    const suggestedName = `prompt-result-${stamp}.md`;

    // Preferred: File System Access API — a real native "Save As" dialog that
    // lets the user pick both the folder and the file name. Chromium-only and
    // requires a secure context; fall back to a normal download otherwise.
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
          types: [
            {
              description: "Markdown",
              accept: { "text/markdown": [".md"] },
            },
          ],
        });
        const writable = await handle.createWritable();
        await writable.write(answer.text);
        await writable.close();
        message.success("Saved");
      } catch (e) {
        // User cancelled the dialog — not an error.
        if ((e as Error).name !== "AbortError") {
          message.error(`Save failed: ${(e as Error).message}`);
        }
      }
      return;
    }

    // Fallback: trigger a browser download (respects the browser's
    // "ask where to save" setting).
    const blob = new Blob([answer.text], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = suggestedName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleCopyResult = async () => {
    if (!answer) return;
    // navigator.clipboard only exists in a secure context (https / localhost).
    // Over http://<ip> it is undefined, so fall back to a hidden-textarea +
    // document.execCommand("copy"), which works on plain http.
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(answer.text);
        message.success("Copied to clipboard");
        return;
      } catch {
        /* fall through to the legacy path */
      }
    }
    try {
      const ta = document.createElement("textarea");
      ta.value = answer.text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      if (ok) message.success("Copied to clipboard");
      else message.error("Copy failed");
    } catch {
      message.error("Copy failed");
    }
  };

  const load = () => {
    setLoading(true);
    getAgentInfo()
      .then((d) => {
        setInfo(d);
        setModel(d.model);
      })
      .catch((e: Error) => message.error(`Load agent failed: ${e.message}`))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    loadSkills();
    loadSessions();
    listAgentModels()
      .then(setModels)
      .catch((e: Error) => message.error(`Load models failed: ${e.message}`));
  }, []);

  // Auto-scroll the session history box to the bottom when new turns arrive.
  useEffect(() => {
    const el = historyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [history]);

  const handleSwitch = async () => {
    if (!model || model === info?.model) {
      message.warning("Select a different model before switching");
      return;
    }
    setSwitching(true);
    try {
      const res = await switchAgent({ model });
      message.success(res.message);
      setInfo(res.agent);
    } catch (e) {
      message.error(`Switch failed: ${(e as Error).message}`);
    } finally {
      setSwitching(false);
    }
  };

  const handleChat = async () => {
    if (!prompt.trim()) {
      message.warning("Please enter a prompt");
      return;
    }
    setChatting(true);
    setAnswer(null);
    try {
      // Ensure a session exists so the turn is persisted and multi-turn context works.
      let sid = currentSessionId;
      if (!sid) {
        const detail = await createSession();
        sid = detail.id;
        setCurrentSessionId(sid);
      }
      const res = await agentChat(prompt.trim(), true, undefined, sid); // access Roku internal data
      setAnswer({ text: res.response, model: res.model, time: res.response_time });
      // Refresh persisted history + session list (title is set from first prompt).
      try {
        const detail = await getSession(sid);
        setHistory(detail.messages);
      } catch {
        /* non-fatal: answer already shown */
      }
      loadSessions();
    } catch (e) {
      message.error(`Chat failed: ${(e as Error).message}`);
    } finally {
      setChatting(false);
    }
  };

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>
        Prompt Agent
      </Title>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={12}>
          <Card
            title="Agent"
            style={{ height: "100%" }}
            extra={
              <Button size="small" icon={<ReloadOutlined />} onClick={load} loading={loading}>
                Refresh
              </Button>
            }
          >
            {info ? (
              <Descriptions column={1} size="small">
                <Descriptions.Item label="Model">{info.model}</Descriptions.Item>
                <Descriptions.Item label="Key Alias">{info.key_alias}</Descriptions.Item>
                <Descriptions.Item label="Max Tokens">{info.max_tokens}</Descriptions.Item>
                <Descriptions.Item label="Temperature">{info.temperature}</Descriptions.Item>
                <Descriptions.Item label="Base URL">{info.base_url}</Descriptions.Item>
              </Descriptions>
            ) : (
              <Text type="secondary">Loading…</Text>
            )}
            <Space size="large" wrap align="end" style={{ marginTop: 16, width: "100%" }}>
              <div style={{ minWidth: 260 }}>
                <Text strong>Switch Model</Text>
                <Select
                  style={{ width: "100%", marginTop: 8 }}
                  placeholder="Select a model"
                  value={model}
                  onChange={setModel}
                  options={models.map((m) => ({
                    value: m.model,
                    label: m.description ? `${m.name} — ${m.description}` : m.name,
                  }))}
                  showSearch
                  optionFilterProp="label"
                />
              </div>
              <Button
                type="primary"
                icon={<SwapOutlined />}
                loading={switching}
                onClick={handleSwitch}
              >
                Switch
              </Button>
            </Space>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card
            title="Skills"
            style={{ height: "100%" }}
            extra={
              <Space>
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  onClick={loadSkills}
                  loading={skillsLoading}
                >
                  Refresh
                </Button>
                <Button
                  size="small"
                  icon={<DownloadOutlined />}
                  disabled={skills.length === 0}
                  onClick={() => {
                    // GET endpoint returns the zip with Content-Disposition; let
                    // the browser download it.
                    window.location.href = exportSkillsUrl();
                  }}
                >
                  Export All
                </Button>
                <Button
                  size="small"
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={openAddSkill}
                >
                  Add
                </Button>
              </Space>
            }
          >
            <Table<{ name: string }>
              size="small"
              rowKey="name"
              loading={skillsLoading}
              dataSource={skills.map((name) => ({ name }))}
              pagination={{ defaultPageSize: 10, pageSizeOptions: [10, 20, 50], showSizeChanger: true }}
              locale={{ emptyText: "No skills" }}
              columns={[
                {
                  title: "Skill",
                  dataIndex: "name",
                  key: "name",
                  sorter: (a, b) => a.name.localeCompare(b.name),
                  defaultSortOrder: "ascend",
                },
                {
                  title: "Actions",
                  key: "actions",
                  width: 260,
                  render: (_, r) => (
                    <Space>
                      <Button
                        size="small"
                        icon={<EyeOutlined />}
                        onClick={() => handleViewSkill(r.name)}
                      >
                        View
                      </Button>
                      <Button
                        size="small"
                        icon={<EditOutlined />}
                        onClick={() => openEditSkill(r.name)}
                      >
                        Edit
                      </Button>
                      <Popconfirm
                        title="Delete this skill?"
                        onConfirm={() => handleDeleteSkill(r.name)}
                        okText="Delete"
                        okButtonProps={{ danger: true }}
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
        </Col>
      </Row>

      <Modal
        title={viewSkill?.name}
        open={!!viewSkill}
        onCancel={() => setViewSkill(null)}
        footer={<Button onClick={() => setViewSkill(null)}>Close</Button>}
        width={720}
      >
        <div
          className="chat-markdown"
          style={{
            padding: "4px 16px",
            background: "#1e1e1e",
            color: "#d0d0d0",
            borderRadius: 6,
            border: "1px solid #424242",
            maxHeight: "60vh",
            overflow: "auto",
          }}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {viewSkill?.content ?? ""}
          </ReactMarkdown>
        </div>
      </Modal>

      <Modal
        title={editSkillName ? `Edit Skill: ${editSkillName}` : "Add Skill"}
        open={addOpen}
        onCancel={() => {
          setAddOpen(false);
          setEditSkillName(null);
        }}
        onOk={handleSaveSkill}
        okText="Save"
        confirmLoading={savingSkill}
        width={720}
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong>Name</Text>
            <Input
              style={{ marginTop: 4 }}
              placeholder="skill_name (no .md)"
              value={newSkillName}
              disabled={!!editSkillName}
              onChange={(e) => setNewSkillName(e.target.value)}
            />
          </div>
          <div>
            <Text strong>Content (Markdown)</Text>
            <Tabs
              style={{ marginTop: 4 }}
              size="small"
              items={[
                {
                  key: "edit",
                  label: "Edit",
                  children: (
                    <Input.TextArea
                      rows={12}
                      placeholder="# My Skill&#10;&#10;Describe the skill in Markdown..."
                      value={newSkillContent}
                      onChange={(e) => setNewSkillContent(e.target.value)}
                    />
                  ),
                },
                {
                  key: "preview",
                  label: "Preview",
                  children: (
                    <div
                      className="chat-markdown"
                      style={{
                        padding: "4px 16px",
                        background: "#1e1e1e",
                        color: "#d0d0d0",
                        borderRadius: 6,
                        border: "1px solid #424242",
                        minHeight: 260,
                        maxHeight: "50vh",
                        overflow: "auto",
                      }}
                    >
                      {newSkillContent.trim() ? (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {newSkillContent}
                        </ReactMarkdown>
                      ) : (
                        <Text type="secondary">Nothing to preview</Text>
                      )}
                    </div>
                  ),
                },
              ]}
            />
          </div>
        </Space>
      </Modal>

      <Card title="Prompt Run" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong style={{ display: "block", marginBottom: 8 }}>
              Session
            </Text>
            <Space wrap>
              <Select
                style={{ minWidth: 260 }}
                placeholder="New conversation"
                value={currentSessionId ?? undefined}
                onChange={handleSelectSession}
                allowClear
                onClear={() => {
                  setCurrentSessionId(null);
                  setHistory([]);
                  setAnswer(null);
                }}
                options={sessions.map((s) => ({
                  value: s.id,
                  label: `${s.title || "(untitled)"} (${s.count})`,
                }))}
              />
              <Button icon={<PlusOutlined />} onClick={handleNewSession}>
                New
              </Button>
              <Popconfirm
                title="Delete this session?"
                onConfirm={handleDeleteSession}
                disabled={!currentSessionId}
              >
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  disabled={!currentSessionId}
                >
                  Delete
                </Button>
              </Popconfirm>
            </Space>
          </div>
          {history.length > 0 && (
            <div
              ref={historyRef}
              className="chat-markdown"
              style={{
                maxHeight: "40vh",
                overflow: "auto",
                padding: "8px 12px",
                background: "#161616",
                borderRadius: 6,
                border: "1px solid #424242",
              }}
            >
              {history.map((m, i) => (
                <div key={i} style={{ marginBottom: 12 }}>
                  <Text
                    strong
                    style={{ color: m.role === "user" ? "#40a9ff" : "#73d13d" }}
                  >
                    {m.role === "user" ? "You" : "Assistant"}
                  </Text>
                  <div
                    style={{
                      marginTop: 4,
                      padding: "4px 12px",
                      background: m.role === "user" ? "#111d2c" : "#1e1e1e",
                      borderRadius: 6,
                      color: "#d0d0d0",
                      overflowX: "auto",
                    }}
                  >
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {m.content}
                    </ReactMarkdown>
                  </div>
                </div>
              ))}
            </div>
          )}
          <div>
            <Text strong style={{ display: "block", marginBottom: 8 }}>
              Skills
            </Text>
            {skills.length === 0 ? (
              <Text type="secondary">No skills</Text>
            ) : (
              <Space wrap size={[8, 8]}>
                {skills.map((s) => {
                  const active = activeSkills.includes(s);
                  return (
                    <div
                      key={s}
                      onClick={() => handleAppendSkill(s)}
                      title={`Add "${s}" to the prompt`}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "6px 12px",
                        cursor: "pointer",
                        borderRadius: 6,
                        color: active ? "#40a9ff" : "#d0d0d0",
                        background: active ? "#111d2c" : "#1e1e1e",
                        border: active
                          ? "2px solid #40a9ff"
                          : "1px solid #424242",
                        // keep box size stable when the border thickens
                        margin: active ? 0 : 1,
                        userSelect: "none",
                      }}
                    >
                      <RobotOutlined />
                      <span>{s}</span>
                    </div>
                  );
                })}
              </Space>
            )}
          </div>
          <Tabs
            size="small"
            items={[
              {
                key: "edit",
                label: "Edit",
                children: (
                  <Input.TextArea
                    // Auto-grow to fit content, keeping ~2 blank rows below the text.
                    autoSize={{ minRows: prompt.split("\n").length + 2 }}
                    placeholder="Ask the agent something..."
                    value={prompt}
                    onChange={(e) => {
                      const v = e.target.value;
                      setPrompt(v);
                      if (!v.trim()) setAnswer(null); // hide result when input is cleared
                    }}
                  />
                ),
              },
              {
                key: "preview",
                label: "Preview",
                children: (
                  <div
                    className="chat-markdown"
                    style={{
                      padding: "4px 16px",
                      background: "#1e1e1e",
                      color: "#d0d0d0",
                      borderRadius: 6,
                      border: "1px solid #424242",
                      minHeight: 100,
                      maxHeight: "50vh",
                      overflow: "auto",
                    }}
                  >
                    {prompt.trim() ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {prompt}
                      </ReactMarkdown>
                    ) : (
                      <Text type="secondary">Nothing to preview</Text>
                    )}
                  </div>
                ),
              },
            ]}
          />
          <Space>
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={chatting}
              onClick={handleChat}
            >
              Send
            </Button>
            <Button
              icon={<ClearOutlined />}
              onClick={handleClearPrompt}
              disabled={!prompt && activeSkills.length === 0}
            >
              Clear
            </Button>
          </Space>
          {answer && (
            <div>
              <Text type="secondary">
                {answer.model} · {answer.time}s
              </Text>
              <div
                className="chat-markdown"
                style={{
                  marginTop: 8,
                  padding: "4px 16px",
                  background: "#1e1e1e",
                  color: "#d0d0d0",
                  borderRadius: 6,
                  border: "1px solid #424242",
                  overflowX: "auto",
                }}
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {answer.text}
                </ReactMarkdown>
              </div>
              <Space style={{ marginTop: 8 }}>
                <Button
                  size="small"
                  icon={<SaveOutlined />}
                  onClick={handleSaveResult}
                >
                  Save
                </Button>
                <Button
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={handleCopyResult}
                >
                  Copy
                </Button>
              </Space>
            </div>
          )}
        </Space>
      </Card>
    </div>
  );
}
