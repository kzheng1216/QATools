import { useEffect, useState, type ReactNode } from "react";
import {
  Button,
  Input,
  Modal,
  Space,
  Table,
  Tabs,
  Typography,
  message,
  Popconfirm,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  PlusOutlined,
  EditOutlined,
  EyeOutlined,
  DeleteOutlined,
  ReloadOutlined,
  FormOutlined,
  CodeOutlined,
} from "@ant-design/icons";
import { jsonModalWidth } from "../components/JsonView";
import JsonCodeEditor from "../components/JsonCodeEditor";

const { Title } = Typography;

// A table row always carries a `name`; callers can attach extra fields for
// their own columns (e.g. device presence flags).
export type Row = { name: string } & Record<string, unknown>;

// CRUD API surface for one resource kind (device or profile).
export interface CrudApi {
  list: () => Promise<string[]>;
  get: (name: string) => Promise<Record<string, unknown>>;
  add: (name: string, data: unknown) => Promise<{ message: string }>;
  update: (name: string, data: unknown) => Promise<{ message: string }>;
  remove: (name: string) => Promise<{ message: string }>;
}

interface Props {
  title: string;
  api: CrudApi;
  // Placeholder JSON shown in the editor when creating a new item.
  addTemplate?: string;
  // Show a keyword filter box over the Name column.
  searchable?: boolean;
  // Extra buttons for the top-right toolbar (before Add). Receives a `reload`
  // callback so the action can refresh the list after it succeeds.
  extraActions?: (reload: () => void) => ReactNode;
  // Extra per-row buttons appended to the Actions column. Receives the row's
  // name and a `reload` callback.
  rowActions?: (name: string, reload: () => void) => ReactNode;
  // Width (px) of the Actions column. Keep it tight so wide tables (e.g. the
  // Device page with its flag columns) stay inside the layout width.
  actionsWidth?: number;
  // Optional richer row loader: when given, rows come from here (carrying extra
  // fields) instead of api.list(). Falls back to api.list() names on error.
  loadRows?: () => Promise<Row[]>;
  // Extra columns inserted between Name and Actions (e.g. device flags).
  extraColumns?: ColumnsType<Row>;
  // Optional map of JSON field name -> description. When set, hovering a key in
  // the View/Edit JSON editor shows its description in a tooltip.
  fieldDocs?: Record<string, string>;
  // Optional guided (form-based) editor. When given, the Add/Edit/View dialog
  // shows two tabs -- "Guided" (this component) and "JSON" (the raw editor) --
  // both bound to the same JSON text, so switching tabs keeps every edit.
  formEditor?: (props: {
    value: string;
    onChange: (next: string) => void;
    readOnly?: boolean;
  }) => ReactNode;
  // Fixed dialog width used while the guided tab is active. The JSON tab keeps
  // auto-sizing to its content.
  formEditorWidth?: number;
}

type Mode = "add" | "edit" | "view";

export default function ConfigManager({
  title,
  api,
  addTemplate = "{\n\n}",
  searchable = false,
  extraActions,
  rowActions,
  actionsWidth,
  loadRows,
  extraColumns,
  fieldDocs,
  formEditor,
  formEditorWidth = 1000,
}: Props) {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");

  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("add");
  const [name, setName] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Which editor tab is showing. Defaults to the guided one when available,
  // since that's the friendlier entry point for building a profile.
  const [editorTab, setEditorTab] = useState<"form" | "json">("form");

  const load = () => {
    setLoading(true);
    const loader: Promise<Row[]> = loadRows
      ? loadRows()
      : api.list().then((names) => names.map((n) => ({ name: n })));
    loader
      .then(setRows)
      .catch((e: Error) => message.error(`Load failed: ${e.message}`))
      .finally(() => setLoading(false));
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const openAdd = () => {
    setMode("add");
    setName("");
    setJsonText(addTemplate);
    setJsonError(null);
    setEditorTab(formEditor ? "form" : "json");
    setOpen(true);
  };

  const openEditOrView = async (item: string, m: "edit" | "view") => {
    try {
      const data = await api.get(item);
      setMode(m);
      setName(item);
      setJsonText(JSON.stringify(data, null, 4));
      setJsonError(null);
      setEditorTab(formEditor ? "form" : "json");
      setOpen(true);
    } catch (e) {
      message.error(`Open failed: ${(e as Error).message}`);
    }
  };

  const handleSave = async () => {
    if (!name.trim()) {
      message.warning("Name is required");
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(jsonText);
    } catch {
      message.error("Invalid JSON content");
      return;
    }
    setSaving(true);
    try {
      if (mode === "add") {
        const res = await api.add(name.trim(), parsed);
        message.success(res.message);
      } else {
        const res = await api.update(name, parsed);
        message.success(res.message);
      }
      setOpen(false);
      load();
    } catch (e) {
      message.error(`Save failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (item: string) => {
    try {
      const res = await api.remove(item);
      message.success(res.message);
      load();
    } catch (e) {
      message.error(`Delete failed: ${(e as Error).message}`);
    }
  };

  const columns: ColumnsType<Row> = [
    {
      title: "Name",
      dataIndex: "name",
      key: "name",
      width: 220,
      ellipsis: true,
      sorter: (a: Row, b: Row) => a.name.localeCompare(b.name),
      defaultSortOrder: "descend" as const,
    },
    ...(extraColumns ?? []),
    {
      title: "Actions",
      key: "actions",
      width: actionsWidth ?? (rowActions ? 300 : 200),
      fixed: "right" as const,
      render: (_: unknown, record: Row) => (
        <Space size={4} wrap={false}>
          <Button
            size="small"
            icon={<EyeOutlined />}
            onClick={() => openEditOrView(record.name, "view")}
          >
            View
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEditOrView(record.name, "edit")}
          >
            Edit
          </Button>
          {rowActions?.(record.name, load)}
          <Popconfirm
            title={`Delete "${record.name}"?`}
            okText="Delete"
            okButtonProps={{ danger: true }}
            onConfirm={() => handleDelete(record.name)}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              Delete
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const modalTitle =
    mode === "add" ? `Add ${title}` : mode === "edit" ? `Edit ${title}: ${name}` : `View ${title}: ${name}`;

  // The raw JSON editor, shared by the single-editor layout and the JSON tab.
  const jsonEditor = (
    <div>
      <JsonCodeEditor
        value={jsonText}
        readOnly={mode === "view"}
        onChange={setJsonText}
        onValidityChange={setJsonError}
        fieldDocs={fieldDocs}
      />
      {mode !== "view" && jsonError && (
        <Typography.Text
          type="danger"
          style={{ display: "block", marginTop: 6, fontFamily: "monospace" }}
        >
          Invalid JSON: {jsonError}
        </Typography.Text>
      )}
    </div>
  );

  const editorBody = formEditor ? (
    <Tabs
      activeKey={editorTab}
      onChange={(k) => setEditorTab(k as "form" | "json")}
      size="small"
      items={[
        {
          key: "form",
          label: (
            <span>
              <FormOutlined /> Guided
            </span>
          ),
          children: formEditor({
            value: jsonText,
            onChange: (next) => {
              setJsonText(next);
              // The guided editor always emits valid JSON, so clear any error
              // left over from hand-editing on the JSON tab.
              setJsonError(null);
            },
            readOnly: mode === "view",
          }),
        },
        {
          key: "json",
          label: (
            <span>
              <CodeOutlined /> JSON
            </span>
          ),
          children: jsonEditor,
        },
      ]}
    />
  ) : (
    <div>
      <Typography.Text strong>Content (JSON)</Typography.Text>
      {jsonEditor}
    </div>
  );

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          {title} Management
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            Refresh
          </Button>
          {extraActions?.(load)}
          <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>
            Add {title}
          </Button>
        </Space>
      </div>

      {searchable && (
        <Input.Search
          style={{ width: 320, marginBottom: 16 }}
          placeholder={`Search ${title.toLowerCase()} name`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          allowClear
        />
      )}

      <Table
        rowKey="name"
        loading={loading}
        columns={columns}
        dataSource={rows.filter((r) =>
          r.name.toLowerCase().includes(search.trim().toLowerCase())
        )}
        // Keep the table inside the layout: surplus width scrolls within the
        // table instead of stretching the page.
        scroll={{ x: "max-content" }}
        tableLayout="fixed"
        pagination={{
          defaultPageSize: 15,
          pageSizeOptions: [10, 15, 30, 50],
          showSizeChanger: true,
        }}
      />

      <Modal
        title={modalTitle}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        okButtonProps={{
          style: mode === "view" ? { display: "none" } : undefined,
          // Block Save while the JSON has a syntax error.
          disabled: mode !== "view" && !!jsonError,
        }}
        cancelText={mode === "view" ? "Close" : "Cancel"}
        // The guided tab uses a roomy fixed width; the JSON tab auto-sizes to
        // its content (widest line), clamped.
        width={
          formEditor && editorTab === "form"
            ? formEditorWidth
            : jsonModalWidth(jsonText)
        }
        // Pin the dialog near the top and cap the body height so a tall form
        // (the guided editor runs well past one screen) scrolls inside the
        // modal instead of overflowing off-screen, which would leave the last
        // fields unreachable.
        style={{ top: 24 }}
        styles={{ body: { maxHeight: "calc(100vh - 220px)", overflowY: "auto" } }}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <div>
            <Typography.Text strong>Name</Typography.Text>
            <Input
              style={{ marginTop: 4 }}
              placeholder={`${title.toLowerCase()} name (without .json)`}
              value={name}
              disabled={mode !== "add"}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          {editorBody}
        </Space>
      </Modal>
    </div>
  );
}
