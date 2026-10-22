import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Typography,
  Upload,
  message,
} from "antd";
import type { UploadFile } from "antd";
import {
  ReloadOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  EyeOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  listReference,
  addReference,
  updateReference,
  deleteReference,
  uploadDoc,
  getDocContent,
  type RefKind,
  type RefItem,
} from "../api/client";

const { Title, Text } = Typography;

interface SectionState {
  items: RefItem[];
  categories: string[];
  search: string;
  category: string | undefined;
}

const EMPTY: SectionState = { items: [], categories: [], search: "", category: undefined };

export default function ReferencePage() {
  const [loading, setLoading] = useState(false);
  const [ref, setRef] = useState<SectionState>(EMPTY);
  const [docs, setDocs] = useState<SectionState>(EMPTY);
  const [activeTab, setActiveTab] = useState<RefKind>("ref");

  // Ref Add/Edit modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [editIndex, setEditIndex] = useState<number | null>(null);
  const [formName, setFormName] = useState("");
  const [formCategory, setFormCategory] = useState("");
  const [formUrl, setFormUrl] = useState("");
  const [saving, setSaving] = useState(false);

  // Docs upload modal state
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadCategory, setUploadCategory] = useState("");
  const [uploadFile, setUploadFile] = useState<UploadFile | null>(null);
  const [uploadContent, setUploadContent] = useState("");
  const [uploading, setUploading] = useState(false);

  // Docs view modal state
  const [viewOpen, setViewOpen] = useState(false);
  const [viewName, setViewName] = useState("");
  const [viewContent, setViewContent] = useState("");
  const [viewLoading, setViewLoading] = useState(false);

  const load = () => {
    setLoading(true);
    listReference()
      .then((d) => {
        setRef((s) => ({
          ...s,
          items: d.ref,
          categories: d.ref_categories,
          category: s.category && d.ref_categories.includes(s.category) ? s.category : undefined,
        }));
        setDocs((s) => ({
          ...s,
          items: d.docs,
          categories: d.docs_categories,
          category: s.category && d.docs_categories.includes(s.category) ? s.category : undefined,
        }));
      })
      .catch((e: Error) => message.error(`Load reference failed: ${e.message}`))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  // ---------- Ref add/edit ----------
  const openAddRef = () => {
    setEditIndex(null);
    setFormName("");
    setFormCategory("");
    setFormUrl("");
    setModalOpen(true);
  };

  const openEditRef = (item: RefItem) => {
    setEditIndex(item.index);
    setFormName(item.name);
    setFormCategory(item.category);
    setFormUrl(item.url);
    setModalOpen(true);
  };

  const handleSaveRef = async () => {
    if (!formName.trim()) {
      message.warning("Please enter a name");
      return;
    }
    if (!formUrl.trim()) {
      message.warning("Please enter a URL / path");
      return;
    }
    setSaving(true);
    try {
      const item = {
        name: formName.trim(),
        category: formCategory.trim(),
        url: formUrl.trim(),
      };
      const res =
        editIndex === null
          ? await addReference("ref", item)
          : await updateReference("ref", editIndex, item);
      message.success(res.message);
      setModalOpen(false);
      load();
    } catch (e) {
      message.error(`Save failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  // ---------- Docs upload ----------
  const openUpload = () => {
    setUploadCategory("");
    setUploadFile(null);
    setUploadContent("");
    setUploadOpen(true);
  };

  // Read the picked .md file's text; reject non-md. Return false to stop antd
  // from auto-uploading — we send the content ourselves on Save.
  const beforeUpload = (file: File) => {
    const isMd = file.name.toLowerCase().endsWith(".md");
    if (!isMd) {
      message.error("Only .md (Markdown) files are supported");
      return Upload.LIST_IGNORE;
    }
    const reader = new FileReader();
    reader.onload = () => setUploadContent(String(reader.result ?? ""));
    reader.onerror = () => message.error("Failed to read file");
    reader.readAsText(file);
    setUploadFile({ uid: file.name, name: file.name } as UploadFile);
    return false;
  };

  const handleUpload = async () => {
    if (!uploadFile) {
      message.warning("Please choose a .md file");
      return;
    }
    setUploading(true);
    try {
      const res = await uploadDoc({
        name: uploadFile.name,
        category: uploadCategory.trim(),
        content: uploadContent,
      });
      message.success(res.message);
      setUploadOpen(false);
      load();
    } catch (e) {
      message.error(`Upload failed: ${(e as Error).message}`);
    } finally {
      setUploading(false);
    }
  };

  // ---------- Docs view ----------
  const openView = async (item: RefItem) => {
    setViewName(item.name);
    setViewContent("");
    setViewOpen(true);
    setViewLoading(true);
    try {
      setViewContent(await getDocContent(item.name));
    } catch (e) {
      message.error(`Open failed: ${(e as Error).message}`);
      setViewOpen(false);
    } finally {
      setViewLoading(false);
    }
  };

  const handleDelete = async (kind: RefKind, index: number) => {
    try {
      const res = await deleteReference(kind, index);
      message.success(res.message);
      load();
    } catch (e) {
      message.error(`Delete failed: ${(e as Error).message}`);
    }
  };

  const filterItems = (state: SectionState) => {
    const q = state.search.trim().toLowerCase();
    return state.items.filter((it) => {
      const matchName = !q || it.name.toLowerCase().includes(q);
      const matchCat = !state.category || it.category === state.category;
      return matchName && matchCat;
    });
  };
  const refFiltered = useMemo(() => filterItems(ref), [ref]);
  const docsFiltered = useMemo(() => filterItems(docs), [docs]);

  const filterBar = (
    state: SectionState,
    setState: React.Dispatch<React.SetStateAction<SectionState>>
  ) => (
    <Space style={{ marginBottom: 12 }} wrap>
      <Input.Search
        allowClear
        placeholder="Search by name"
        style={{ width: 260 }}
        value={state.search}
        onChange={(e) => setState((s) => ({ ...s, search: e.target.value }))}
      />
      <Select
        allowClear
        placeholder="Filter by category"
        style={{ minWidth: 200 }}
        value={state.category}
        onChange={(v) => setState((s) => ({ ...s, category: v }))}
        options={state.categories.map((c) => ({ value: c, label: c }))}
      />
    </Space>
  );

  const nameCol = {
    title: "Name",
    dataIndex: "name",
    key: "name",
    sorter: (a: RefItem, b: RefItem) => a.name.localeCompare(b.name),
  };
  const categoryCol = {
    title: "Category",
    dataIndex: "category",
    key: "category",
    width: 160,
    render: (c: string) => c || <Text type="secondary">-</Text>,
  };
  const urlCol = {
    title: "URL / Path",
    dataIndex: "url",
    key: "url",
    render: (url: string) =>
      /^https?:\/\//i.test(url) ? (
        <a href={url} target="_blank" rel="noopener noreferrer">
          {url}
        </a>
      ) : (
        <Text code>{url}</Text>
      ),
  };

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>
        Reference
      </Title>

      <Tabs
        activeKey={activeTab}
        onChange={(k) => setActiveTab(k as RefKind)}
        tabBarExtraContent={
          <Space>
            <Button size="small" icon={<ReloadOutlined />} onClick={load} loading={loading}>
              Refresh
            </Button>
            {activeTab === "ref" ? (
              <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openAddRef}>
                Add
              </Button>
            ) : (
              <Button size="small" type="primary" icon={<UploadOutlined />} onClick={openUpload}>
                Add
              </Button>
            )}
          </Space>
        }
        items={[
          {
            key: "ref",
            label: `Ref (${refFiltered.length})`,
            children: (
              <>
                {filterBar(ref, setRef)}
                <Table<RefItem>
                  size="small"
                  rowKey="index"
                  dataSource={refFiltered}
                  pagination={{ defaultPageSize: 10, pageSizeOptions: [10, 20, 50], showSizeChanger: true }}
                  columns={[
                    nameCol,
                    categoryCol,
                    urlCol,
                    {
                      title: "Action",
                      key: "action",
                      width: 140,
                      render: (_, item) => (
                        <Space>
                          <Button size="small" icon={<EditOutlined />} onClick={() => openEditRef(item)}>
                            Edit
                          </Button>
                          <Popconfirm
                            title="Delete this item?"
                            onConfirm={() => handleDelete("ref", item.index)}
                          >
                            <Button size="small" danger icon={<DeleteOutlined />} />
                          </Popconfirm>
                        </Space>
                      ),
                    },
                  ]}
                />
              </>
            ),
          },
          {
            key: "docs",
            label: `Docs (${docsFiltered.length})`,
            children: (
              <>
                {filterBar(docs, setDocs)}
                <Table<RefItem>
                  size="small"
                  rowKey="index"
                  dataSource={docsFiltered}
                  pagination={{ defaultPageSize: 10, pageSizeOptions: [10, 20, 50], showSizeChanger: true }}
                  columns={[
                    nameCol,
                    categoryCol,
                    urlCol,
                    {
                      title: "Action",
                      key: "action",
                      width: 140,
                      render: (_, item) => (
                        <Space>
                          <Button size="small" icon={<EyeOutlined />} onClick={() => openView(item)}>
                            View
                          </Button>
                          <Popconfirm
                            title="Delete this record? (the file is kept)"
                            onConfirm={() => handleDelete("docs", item.index)}
                          >
                            <Button size="small" danger icon={<DeleteOutlined />} />
                          </Popconfirm>
                        </Space>
                      ),
                    },
                  ]}
                />
              </>
            ),
          },
        ]}
      />

      {/* Ref Add/Edit modal */}
      <Modal
        title={`${editIndex === null ? "Add" : "Edit"} Ref`}
        open={modalOpen}
        onOk={handleSaveRef}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        okText="Save"
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong>Name</Text>
            <Input value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="Display name" />
          </div>
          <div>
            <Text strong>Category</Text>
            <Input value={formCategory} onChange={(e) => setFormCategory(e.target.value)} placeholder="e.g. Zen" />
          </div>
          <div>
            <Text strong>URL / Path</Text>
            <Input value={formUrl} onChange={(e) => setFormUrl(e.target.value)} placeholder="https://..." />
          </div>
        </Space>
      </Modal>

      {/* Docs upload modal */}
      <Modal
        title="Add Document"
        open={uploadOpen}
        onOk={handleUpload}
        confirmLoading={uploading}
        onCancel={() => setUploadOpen(false)}
        okText="Upload"
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong>Category</Text>
            <Input
              value={uploadCategory}
              onChange={(e) => setUploadCategory(e.target.value)}
              placeholder="e.g. Zen"
            />
          </div>
          <div>
            <Text strong style={{ display: "block", marginBottom: 8 }}>
              Markdown file (.md only)
            </Text>
            <Upload
              accept=".md"
              maxCount={1}
              beforeUpload={beforeUpload}
              onRemove={() => {
                setUploadFile(null);
                setUploadContent("");
              }}
              fileList={uploadFile ? [uploadFile] : []}
            >
              <Button icon={<UploadOutlined />}>Choose .md file</Button>
            </Upload>
            <Text type="secondary" style={{ display: "block", marginTop: 8 }}>
              If a file with the same name already exists it will be overwritten.
            </Text>
          </div>
        </Space>
      </Modal>

      {/* Docs markdown view modal — width auto, height 2/3 of viewport */}
      <Modal
        title={viewName}
        open={viewOpen}
        onCancel={() => setViewOpen(false)}
        footer={null}
        width="fit-content"
        styles={{ body: { maxHeight: "66vh", overflow: "auto" } }}
      >
        <div className="chat-markdown" style={{ minWidth: 320 }}>
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
