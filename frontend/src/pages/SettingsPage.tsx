import { useEffect, useRef, useState } from "react";
import {
  Button,
  Card,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Segmented,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import {
  ReloadOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  CheckCircleOutlined,
} from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  listTabs,
  setTabVisibility,
  reorderTabs,
  listModels,
  addModel,
  updateModel,
  deleteModel,
  getAgentCred,
  updateAgentCred,
  getDefaultModel,
  setDefaultModel,
  restartBackend,
  getAnalyzeConfig,
  updateAnalyzeConfig,
  getAccount,
  updateAccount,
  type TabConfig,
  type AgentModelConfig,
  type AgentCred,
  type AnalyzeLocale,
  type AccountSettings,
} from "../api/client";

const { TextArea } = Input;

const { Title, Text } = Typography;

// Human-friendly labels for the tab keys stored in config.yml.
const TAB_LABELS: Record<string, string> = {
  device: "Device",
  profile: "Profile",
  runcase: "Run Case",
  rokutest: "Run Case in local",
  testrail: "TestRail Case",
  agent: "Prompt",
  reference: "Reference",
  analyzehistory: "Analyze History",
  filetransfer: "File Transfer",
};

const EMPTY_MODEL: AgentModelConfig = {
  name: "",
  description: "",
  model: "",
  max_tokens: 128000,
  temperature: 0.7,
};

export default function SettingsPage({ onChanged }: { onChanged?: () => void }) {
  const [tabs, setTabs] = useState<TabConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const dragIndex = useRef<number | null>(null); // row being dragged

  // Agent models
  const [models, setModels] = useState<AgentModelConfig[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editName, setEditName] = useState<string | null>(null); // null = add
  const [form, setForm] = useState<AgentModelConfig>(EMPTY_MODEL);
  const [saving, setSaving] = useState(false);

  // Agent credentials
  const [cred, setCred] = useState<AgentCred | null>(null);
  const [credLoading, setCredLoading] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [keyIdInput, setKeyIdInput] = useState("");
  const [keyAliasInput, setKeyAliasInput] = useState("");
  const [credSaving, setCredSaving] = useState(false);

  // Default model: track which model id is the current default (from
  // agent_config.model) and the timeout to preserve when switching.
  const [defaultModel, setDefaultModelState] = useState<string>("");
  const [defaultTimeout, setDefaultTimeout] = useState<number>(300);
  const [settingDefault, setSettingDefault] = useState<string | null>(null);

  const loadDefaultModel = () => {
    getDefaultModel()
      .then((d) => {
        setDefaultModelState(d.model);
        setDefaultTimeout(d.timeout_sec);
      })
      .catch((e: Error) => message.error(`Load default model failed: ${e.message}`));
  };

  // Analyze settings: default locale (radio) + prompt template (textarea).
  const [analyzeLocale, setAnalyzeLocale] = useState<AnalyzeLocale>("en-US");
  const [analyzePrompt, setAnalyzePrompt] = useState<string>("");
  const [analyzeLoading, setAnalyzeLoading] = useState(false);
  const [analyzeSaving, setAnalyzeSaving] = useState(false);
  // Prompt template view mode: "edit" (raw textarea) or "preview" (markdown).
  const [promptView, setPromptView] = useState<"edit" | "preview">("preview");

  const loadAnalyzeConfig = () => {
    setAnalyzeLoading(true);
    getAnalyzeConfig()
      .then((c) => {
        setAnalyzeLocale(c.default_locale);
        setAnalyzePrompt(c.prompt_template);
      })
      .catch((e: Error) => message.error(`Load analyze settings failed: ${e.message}`))
      .finally(() => setAnalyzeLoading(false));
  };

  const handleSaveAnalyze = async () => {
    if (!analyzePrompt.trim()) {
      message.warning("Prompt template cannot be empty");
      return;
    }
    setAnalyzeSaving(true);
    try {
      const res = await updateAnalyzeConfig({
        default_locale: analyzeLocale,
        prompt_template: analyzePrompt,
      });
      message.success(res.message); // applied live, no restart needed
    } catch (e) {
      message.error(`Save failed: ${(e as Error).message}`);
    } finally {
      setAnalyzeSaving(false);
    }
  };

  // Account settings (config/env.py overrides). Secret fields are blank inputs
  // with a masked placeholder; non-secret fields are editable text.
  const ACCOUNT_SECRET_FIELDS = [
    "QAHUB_TOKEN",
    "TESTRAIL_USERNAME",
    "TESTRAIL_API_KEY",
    "JIRA_TOKEN",
  ];
  const ACCOUNT_PLAIN_FIELDS = [
    "EMAIL",
    "DATA_BASE_DIR",
    "ROKU_TEST_LOG_DIR",
    "AUTOMATED_TESTS_RELATIVE_DIR",
  ];
  const ACCOUNT_LABELS: Record<string, string> = {
    QAHUB_TOKEN: "QA Hub Token",
    EMAIL: "Email (TestRail)",
    TESTRAIL_USERNAME: "TestRail Username",
    TESTRAIL_API_KEY: "TestRail API Key",
    JIRA_TOKEN: "JIRA Token",
    DATA_BASE_DIR: "Data Base Dir",
    ROKU_TEST_LOG_DIR: "Roku Test Log Dir",
    AUTOMATED_TESTS_RELATIVE_DIR: "Automated Tests Relative Dir",
  };
  const [account, setAccount] = useState<AccountSettings | null>(null);
  const [accountLoading, setAccountLoading] = useState(false);
  const [accountSaving, setAccountSaving] = useState(false);
  // Form values: secrets start empty (empty = keep), plain fields start from server.
  const [accountForm, setAccountForm] = useState<Record<string, string>>({});

  const loadAccount = () => {
    setAccountLoading(true);
    getAccount()
      .then((a) => {
        setAccount(a);
        const form: Record<string, string> = {};
        for (const k of ACCOUNT_PLAIN_FIELDS) form[k] = String(a[k] ?? "");
        for (const k of ACCOUNT_SECRET_FIELDS) form[k] = ""; // blank = unchanged
        setAccountForm(form);
      })
      .catch((e: Error) => message.error(`Load account failed: ${e.message}`))
      .finally(() => setAccountLoading(false));
  };

  const handleSaveAccount = async () => {
    setAccountSaving(true);
    try {
      // Send plain fields always; send secrets only when typed (empty = keep).
      const body: Record<string, string> = {};
      for (const k of ACCOUNT_PLAIN_FIELDS) body[k] = accountForm[k] ?? "";
      for (const k of ACCOUNT_SECRET_FIELDS) {
        if (accountForm[k]) body[k] = accountForm[k];
      }
      const res = await updateAccount(body);
      Modal.confirm({
        title: "Account settings saved",
        content: `${res.message} The backend must restart to apply. Restart now?`,
        okText: "Restart",
        cancelText: "Later",
        onOk: doRestart,
      });
      loadAccount();
    } catch (e) {
      message.error(`Save failed: ${(e as Error).message}`);
    } finally {
      setAccountSaving(false);
    }
  };

  // Set a given model row as the default (writes model + its params into
  // agent_config, preserving the current timeout_sec).
  const handleSetDefault = async (m: AgentModelConfig) => {
    setSettingDefault(m.model);
    try {
      const res = await setDefaultModel({
        model: m.model,
        timeout_sec: defaultTimeout,
        max_tokens: m.max_tokens,
        temperature: m.temperature,
      });
      setDefaultModelState(m.model);
      message.success(res.message); // applied live, no restart needed
    } catch (e) {
      message.error(`Set default failed: ${(e as Error).message}`);
    } finally {
      setSettingDefault(null);
    }
  };

  // Shared: trigger a backend restart.
  const doRestart = async () => {
    try {
      const res = await restartBackend();
      message.success(res.message);
    } catch (e) {
      message.error(`Restart failed: ${(e as Error).message}`);
    }
  };

  const loadCredData = () => {
    setCredLoading(true);
    getAgentCred()
      .then((c) => {
        setCred(c);
        setApiKeyInput("");
        setKeyIdInput("");
        setKeyAliasInput(c.key_alias);
      })
      .catch((e: Error) => message.error(`Load credentials failed: ${e.message}`))
      .finally(() => setCredLoading(false));
  };

  const handleSaveCred = async () => {
    setCredSaving(true);
    try {
      // Only send secrets that were actually typed; empty = keep existing.
      const res = await updateAgentCred({
        api_key: apiKeyInput || undefined,
        key_id: keyIdInput || undefined,
        key_alias: keyAliasInput,
      });
      loadCredData();
      Modal.confirm({
        title: "Credentials saved",
        content: `${res.message} The backend must restart to apply. Restart now?`,
        okText: "Restart",
        cancelText: "Later",
        onOk: doRestart,
      });
    } catch (e) {
      message.error(`Save failed: ${(e as Error).message}`);
    } finally {
      setCredSaving(false);
    }
  };

  const loadTabsData = () => {
    setLoading(true);
    listTabs()
      .then(setTabs)
      .catch((e: Error) => message.error(`Load tabs failed: ${e.message}`))
      .finally(() => setLoading(false));
  };

  const loadModelsData = () => {
    setModelsLoading(true);
    listModels()
      .then(setModels)
      .catch((e: Error) => message.error(`Load models failed: ${e.message}`))
      .finally(() => setModelsLoading(false));
  };

  useEffect(() => {
    loadTabsData();
    loadModelsData();
    loadCredData();
    loadDefaultModel();
    loadAnalyzeConfig();
    loadAccount();
  }, []);

  const handleToggle = async (name: string, status: boolean) => {
    setSavingKey(name);
    try {
      const res = await setTabVisibility(name, status);
      message.success(res.message);
      setTabs((prev) => prev.map((t) => (t.name === name ? { ...t, status } : t)));
      onChanged?.();
    } catch (e) {
      message.error(`Update failed: ${(e as Error).message}`);
    } finally {
      setSavingKey(null);
    }
  };

  // Drag-to-reorder: move the row at `from` to `to`, persist the full order.
  const moveTab = async (from: number, to: number) => {
    if (from === to || from < 0 || to < 0 || to >= tabs.length) return;
    const next = [...tabs];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    const reindexed = next.map((t, i) => ({ ...t, order: i }));
    setTabs(reindexed); // optimistic
    try {
      await reorderTabs(reindexed.map((t) => t.name));
      onChanged?.();
    } catch (e) {
      message.error(`Reorder failed: ${(e as Error).message}`);
      loadTabsData(); // revert to server truth
    }
  };

  const openAdd = () => {
    setEditName(null);
    setForm(EMPTY_MODEL);
    setModalOpen(true);
  };

  const openEdit = (m: AgentModelConfig) => {
    setEditName(m.name);
    setForm({ ...m });
    setModalOpen(true);
  };

  const handleSaveModel = async () => {
    if (!form.name.trim()) {
      message.warning("Name is required");
      return;
    }
    if (!form.model.trim()) {
      message.warning("Model identifier is required");
      return;
    }
    setSaving(true);
    try {
      const payload = { ...form, name: form.name.trim(), model: form.model.trim() };
      const res =
        editName === null
          ? await addModel(payload)
          : await updateModel(editName, payload);
      message.success(res.message);
      setModalOpen(false);
      loadModelsData();
    } catch (e) {
      message.error(`Save failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteModel = async (name: string) => {
    try {
      const res = await deleteModel(name);
      message.success(res.message);
      loadModelsData();
    } catch (e) {
      message.error(`Delete failed: ${(e as Error).message}`);
    }
  };

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>
        Settings
      </Title>

      <Tabs
        defaultActiveKey="tab"
        items={[
          {
            key: "tab",
            label: "Tab Settings",
            children: (
      <Card
        title="Tab Visibility"
        style={{ marginBottom: 16 }}
        extra={
          <Button size="small" icon={<ReloadOutlined />} onClick={loadTabsData} loading={loading}>
            Refresh
          </Button>
        }
      >
        <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
          Toggle which tabs appear in the left navigation, and drag the ⣿ handle
          to reorder. Changes take effect immediately.
        </Text>
        <Table<TabConfig>
          size="small"
          rowKey="name"
          loading={loading}
          pagination={false}
          dataSource={tabs}
          onRow={(_, index) => ({
            draggable: true,
            onDragStart: () => {
              dragIndex.current = index ?? null;
            },
            onDragOver: (e) => e.preventDefault(), // allow drop
            onDrop: () => {
              if (dragIndex.current !== null && index !== undefined) {
                moveTab(dragIndex.current, index);
              }
              dragIndex.current = null;
            },
          })}
          columns={[
            {
              title: "",
              key: "drag",
              width: 40,
              render: () => (
                <span style={{ cursor: "grab", color: "#999", userSelect: "none" }}>
                  ⣿
                </span>
              ),
            },
            {
              title: "Tab",
              dataIndex: "name",
              key: "name",
              render: (name: string) => (
                <Space>
                  <Text strong>{TAB_LABELS[name] ?? name}</Text>
                  <Text type="secondary" code>
                    {name}
                  </Text>
                </Space>
              ),
            },
            {
              title: "Visible",
              dataIndex: "status",
              key: "status",
              width: 140,
              render: (status: boolean, record) => (
                <Switch
                  checked={status}
                  loading={savingKey === record.name}
                  onChange={(checked) => handleToggle(record.name, checked)}
                />
              ),
            },
          ]}
        />
      </Card>
            ),
          },
          {
            key: "agent",
            label: "Agent Settings",
            children: (
              <>
      <Card
        title="Agent Credentials"
        style={{ marginBottom: 16 }}
        extra={
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={loadCredData}
            loading={credLoading}
          >
            Refresh
          </Button>
        }
      >
        <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
          AI gateway credentials
        </Text>
        <Space direction="vertical" style={{ width: "100%", maxWidth: 560 }} size="middle">
          <div>
            <Text strong>API Key</Text>
            <Input.Password
              value={apiKeyInput}
              placeholder={cred?.api_key_set ? "************ (unchanged)" : "not set"}
              onChange={(e) => setApiKeyInput(e.target.value)}
              autoComplete="new-password"
              visibilityToggle={false}
            />
          </div>
          <div>
            <Text strong>Key ID</Text>
            <Input.Password
              value={keyIdInput}
              placeholder={cred?.key_id_set ? "************ (unchanged)" : "not set"}
              onChange={(e) => setKeyIdInput(e.target.value)}
              autoComplete="new-password"
              visibilityToggle={false}
            />
          </div>
          <div>
            <Text strong>Key Alias</Text>
            <Input
              value={keyAliasInput}
              placeholder="e.g. kzheng"
              onChange={(e) => setKeyAliasInput(e.target.value)}
            />
          </div>
          <Button type="primary" loading={credSaving} onClick={handleSaveCred}>
            Save Credentials
          </Button>
        </Space>
      </Card>

      <Card
        title="Analyze Settings"
        style={{ marginBottom: 16 }}
        extra={
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={loadAnalyzeConfig}
            loading={analyzeLoading}
          >
            Refresh
          </Button>
        }
      >
        <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
          Default locale and prompt template used when you click{" "}
          <Text strong>Analyze</Text>. Changes apply immediately (no restart).
        </Text>
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong style={{ display: "block", marginBottom: 6 }}>
              Default Analyze Locale
            </Text>
            <Radio.Group
              value={analyzeLocale}
              onChange={(e) => setAnalyzeLocale(e.target.value as AnalyzeLocale)}
            >
              <Radio value="en-US">English (en-US)</Radio>
              <Radio value="zh-CN">中文 (zh-CN)</Radio>
            </Radio.Group>
          </div>
          <div>
            <Space
              style={{
                display: "flex",
                justifyContent: "space-between",
                marginBottom: 6,
              }}
            >
              <Text strong>Prompt Template</Text>
              <Segmented
                size="small"
                value={promptView}
                onChange={(v) => setPromptView(v as "edit" | "preview")}
                options={[
                  { label: "Edit", value: "edit" },
                  { label: "Preview", value: "preview" },
                ]}
              />
            </Space>
            <Text type="secondary" style={{ display: "block", marginBottom: 6 }}>
              Markdown. Use <Text code>{"{lang}"}</Text> for the output language
              and <Text code>{"{content}"}</Text> for the log content.
            </Text>
            {promptView === "edit" ? (
              <TextArea
                value={analyzePrompt}
                onChange={(e) => setAnalyzePrompt(e.target.value)}
                autoSize={{ minRows: 10, maxRows: 28 }}
                style={{ fontFamily: "monospace", fontSize: 12 }}
              />
            ) : (
              <div
                className="chat-markdown"
                style={{
                  border: "1px solid rgba(255,255,255,0.15)",
                  borderRadius: 6,
                  padding: "8px 14px",
                  maxHeight: 520,
                  overflow: "auto",
                }}
              >
                {analyzePrompt.trim() ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {analyzePrompt}
                  </ReactMarkdown>
                ) : (
                  <Text type="secondary">
                    (empty — switch to Edit to add a prompt template)
                  </Text>
                )}
              </div>
            )}
          </div>
          <Button type="primary" loading={analyzeSaving} onClick={handleSaveAnalyze}>
            Save Analyze Settings
          </Button>
        </Space>
      </Card>

      <Card
        title="Agent Models"
        extra={
          <Space>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={loadModelsData}
              loading={modelsLoading}
            >
              Refresh
            </Button>
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openAdd}>
              Add
            </Button>
          </Space>
        }
      >
        <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
          Models available in the Prompt page's model switcher. Use{" "}
          <Text strong>Set Default</Text> to make a model the default.
        </Text>
        <Table<AgentModelConfig>
          size="small"
          rowKey="name"
          loading={modelsLoading}
          pagination={false}
          dataSource={models}
          columns={[
            {
              title: "Default",
              key: "default",
              width: 90,
              render: (_, m) =>
                m.model === defaultModel ? (
                  <Tag color="green" icon={<CheckCircleOutlined />}>
                    Default
                  </Tag>
                ) : null,
            },
            {
              title: "Name",
              dataIndex: "name",
              key: "name",
              sorter: (a: AgentModelConfig, b: AgentModelConfig) =>
                a.name.localeCompare(b.name),
            },
            {
              title: "Model",
              dataIndex: "model",
              key: "model",
              sorter: (a: AgentModelConfig, b: AgentModelConfig) =>
                a.model.localeCompare(b.model),
              render: (m: string) => <Text code>{m}</Text>,
            },
            { title: "Description", dataIndex: "description", key: "description" },
            {
              title: "Max Tokens",
              dataIndex: "max_tokens",
              key: "max_tokens",
              width: 110,
              sorter: (a: AgentModelConfig, b: AgentModelConfig) =>
                a.max_tokens - b.max_tokens,
            },
            {
              title: "Temp",
              dataIndex: "temperature",
              key: "temperature",
              width: 80,
              sorter: (a: AgentModelConfig, b: AgentModelConfig) =>
                a.temperature - b.temperature,
            },
            {
              title: "Action",
              key: "action",
              width: 260,
              render: (_, m) => (
                <Space>
                  <Button
                    size="small"
                    style={{ width: 96 }}
                    type={m.model === defaultModel ? "default" : "primary"}
                    ghost={m.model !== defaultModel}
                    disabled={m.model === defaultModel}
                    loading={settingDefault === m.model}
                    onClick={() => handleSetDefault(m)}
                  >
                    {m.model === defaultModel ? "Default" : "Set Default"}
                  </Button>
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(m)}>
                    Edit
                  </Button>
                  <Popconfirm
                    title={`Delete "${m.name}"?`}
                    okText="Delete"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => handleDeleteModel(m.name)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={editName === null ? "Add Model" : `Edit Model: ${editName}`}
        open={modalOpen}
        onOk={handleSaveModel}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        okText="Save"
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong>Name</Text>
            <Input
              value={form.name}
              disabled={editName !== null}
              placeholder="e.g. claude-sonnet-4-6"
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </div>
          <div>
            <Text strong>Model identifier</Text>
            <Input
              value={form.model}
              placeholder="model id sent to the AI gateway"
              onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
            />
          </div>
          <div>
            <Text strong>Description</Text>
            <Input
              value={form.description}
              placeholder="e.g. Claude Sonnet 4.6"
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </div>
          <Space size="large">
            <div>
              <Text strong style={{ display: "block" }}>
                Max Tokens
              </Text>
              <InputNumber
                min={1}
                style={{ width: 160 }}
                value={form.max_tokens}
                onChange={(v) => setForm((f) => ({ ...f, max_tokens: Number(v) || 0 }))}
              />
            </div>
            <div>
              <Text strong style={{ display: "block" }}>
                Temperature
              </Text>
              <InputNumber
                min={0}
                max={2}
                step={0.1}
                style={{ width: 160 }}
                value={form.temperature}
                onChange={(v) => setForm((f) => ({ ...f, temperature: Number(v) || 0 }))}
              />
            </div>
          </Space>
        </Space>
      </Modal>
              </>
            ),
          },
          {
            key: "account",
            label: "Account Settings",
            children: (
              <Card
                title="Account Settings"
                extra={
                  <Button
                    size="small"
                    icon={<ReloadOutlined />}
                    onClick={loadAccount}
                    loading={accountLoading}
                  >
                    Refresh
                  </Button>
                }
              >
                <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
                  Credentials and paths.
                </Text>
                <Space direction="vertical" style={{ width: "100%", maxWidth: 640 }} size="middle">
                  {ACCOUNT_SECRET_FIELDS.map((k) => (
                    <div key={k}>
                      <Text strong>{ACCOUNT_LABELS[k]}</Text>
                      <Input.Password
                        value={accountForm[k] ?? ""}
                        placeholder={
                          account && (account[`${k}_set`] as boolean)
                            ? "************ (unchanged)"
                            : "not set"
                        }
                        onChange={(e) =>
                          setAccountForm((f) => ({ ...f, [k]: e.target.value }))
                        }
                        autoComplete="new-password"
                        visibilityToggle={false}
                      />
                    </div>
                  ))}
                  {ACCOUNT_PLAIN_FIELDS.map((k) => (
                    <div key={k}>
                      <Text strong>{ACCOUNT_LABELS[k]}</Text>
                      <Input
                        value={accountForm[k] ?? ""}
                        onChange={(e) =>
                          setAccountForm((f) => ({ ...f, [k]: e.target.value }))
                        }
                      />
                    </div>
                  ))}
                  <Button type="primary" loading={accountSaving} onClick={handleSaveAccount}>
                    Save Account Settings
                  </Button>
                </Space>
              </Card>
            ),
          },
        ]}
      />
    </div>
  );
}
