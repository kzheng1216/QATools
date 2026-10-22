import { useEffect, useMemo, useRef, useState } from "react";
import {
  AutoComplete,
  Button,
  Card,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Space,
  Tabs,
  Tag,
  Tree,
  Typography,
  Upload,
  message,
} from "antd";
import { DeleteOutlined as DeleteIcon } from "@ant-design/icons";
import type { DataNode } from "antd/es/tree";
import type { UploadProps } from "antd";
import {
  ReloadOutlined,
  PlayCircleOutlined,
  StopOutlined,
  FolderAddOutlined,
  DeleteOutlined,
  UploadOutlined,
  CloudUploadOutlined,
  SaveOutlined,
  FileOutlined,
  FolderOutlined,
} from "@ant-design/icons";
import {
  getFileTransferConfig,
  updateFileTransferConfig,
  getFileTree,
  uploadFileTransfer,
  deleteFileTransferFile,
  makeFileTransferDir,
  deleteFileTransferDir,
  getHttpServerStatus,
  startHttpServer,
  stopHttpServer,
  startScpUpload,
  getScpStatus,
  listScpServers,
  deleteScpServer,
  type FileTreeNode,
  type HttpServerStatus,
  type ScpServer,
} from "../api/client";
import RunScriptCard from "./RunScriptCard";

const { Title, Text } = Typography;

// Human-readable file size.
function fmtSize(n?: number): string {
  if (n === undefined) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

// Map the backend tree into antd Tree DataNodes. `q` (lowercased search text)
// bold-highlights matching name substrings.
function toDataNodes(nodes: FileTreeNode[], q = ""): DataNode[] {
  return nodes.map((n) => {
    const sizeSuffix = n.type === "file" ? `  (${fmtSize(n.size)})` : "";
    let title: React.ReactNode = n.name + sizeSuffix;
    if (q) {
      const i = n.name.toLowerCase().indexOf(q);
      if (i !== -1) {
        title = (
          <span>
            {n.name.slice(0, i)}
            <span style={{ color: "#ff7a45", fontWeight: 600 }}>
              {n.name.slice(i, i + q.length)}
            </span>
            {n.name.slice(i + q.length)}
            {sizeSuffix}
          </span>
        );
      }
    }
    return {
      key: n.path,
      title,
      icon: n.type === "dir" ? <FolderOutlined /> : <FileOutlined />,
      isLeaf: n.type === "file",
      children: n.children ? toDataNodes(n.children, q) : undefined,
    };
  });
}

// Filter the tree to nodes whose name matches `q` (keeping ancestor dirs of any
// match). Returns the pruned tree and the keys of all dirs that must be expanded
// to reveal matches.
function filterTree(
  nodes: FileTreeNode[],
  q: string
): { nodes: FileTreeNode[]; expand: string[] } {
  const expand: string[] = [];
  const walk = (list: FileTreeNode[]): FileTreeNode[] => {
    const out: FileTreeNode[] = [];
    for (const n of list) {
      const selfMatch = n.name.toLowerCase().includes(q);
      const kids = n.children ? walk(n.children) : [];
      if (selfMatch || kids.length > 0) {
        if (n.type === "dir" && (kids.length > 0 || n.children)) expand.push(n.path);
        out.push({ ...n, children: n.children ? kids : undefined });
      }
    }
    return out;
  };
  return { nodes: walk(nodes), expand };
}

// Find a node by its path in the raw tree.
function findNode(nodes: FileTreeNode[], path: string): FileTreeNode | null {
  for (const n of nodes) {
    if (n.path === path) return n;
    if (n.children) {
      const hit = findNode(n.children, path);
      if (hit) return hit;
    }
  }
  return null;
}

export default function FileTransferPage() {
  // Config
  const [root, setRoot] = useState<string>("");
  const [rootInput, setRootInput] = useState<string>("");
  const [port, setPort] = useState<number>(9000);
  const [savingCfg, setSavingCfg] = useState(false);

  // HTTP server
  const [http, setHttp] = useState<HttpServerStatus>({ running: false });
  const [httpBusy, setHttpBusy] = useState(false);

  // Tree
  const [tree, setTree] = useState<FileTreeNode[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string>("");
  const [selectedIsDir, setSelectedIsDir] = useState<boolean>(true);
  // File search: filters the tree by name (case-insensitive substring).
  const [search, setSearch] = useState<string>("");
  const [expandedKeys, setExpandedKeys] = useState<React.Key[]>([]);
  const [autoExpand, setAutoExpand] = useState<boolean>(true);

  // Local upload progress (0..100, or null when idle).
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [uploadName, setUploadName] = useState("");

  // New folder modal (themed, controlled — not Modal.confirm, which ignores theme)
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [newFolderSaving, setNewFolderSaving] = useState(false);

  // SCP modal
  const [scpOpen, setScpOpen] = useState(false);
  const [scpUser, setScpUser] = useState("");
  const [scpHost, setScpHost] = useState("");
  const [scpRemoteDir, setScpRemoteDir] = useState("");
  const [scpPassword, setScpPassword] = useState("");
  const [scpBusy, setScpBusy] = useState(false);
  const [scpPct, setScpPct] = useState<number | null>(null);
  // Cached scp targets (config.yml scp_server_cache) for the Host dropdown.
  const [scpServers, setScpServers] = useState<ScpServer[]>([]);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadConfig = () => {
    getFileTransferConfig()
      .then((c) => {
        setRoot(c.root);
        setRootInput(c.root);
        setPort(c.http_port);
      })
      .catch((e: Error) => message.error(`Load config failed: ${e.message}`));
  };

  const loadTree = () => {
    setTreeLoading(true);
    getFileTree()
      .then((d) => {
        setRoot(d.root);
        setTree(d.tree);
      })
      .catch((e: Error) => message.error(`Load tree failed: ${e.message}`))
      .finally(() => setTreeLoading(false));
  };

  const loadHttp = () => {
    getHttpServerStatus()
      .then((s) => {
        setHttp(s);
        if (s.port) setPort(s.port);
      })
      .catch(() => {
        /* transient */
      });
  };

  useEffect(() => {
    loadConfig();
    loadTree();
    loadHttp();
    pollRef.current = setInterval(loadHttp, 5000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The directory an upload / new folder should target: the selected dir, or the
  // parent dir of a selected file, or the root ("").
  const targetDir = (): string => {
    if (!selectedPath) return "";
    if (selectedIsDir) return selectedPath;
    const idx = selectedPath.lastIndexOf("/");
    return idx === -1 ? "" : selectedPath.slice(0, idx);
  };

  const handleSaveConfig = async () => {
    setSavingCfg(true);
    try {
      const res = await updateFileTransferConfig({ root: rootInput, http_port: port });
      message.success(res.message);
      setRoot(res.root);
      setPort(res.http_port);
      loadTree();
    } catch (e) {
      message.error(`Save failed: ${(e as Error).message}`);
    } finally {
      setSavingCfg(false);
    }
  };

  const handleStart = async () => {
    setHttpBusy(true);
    try {
      const res = await startHttpServer();
      message.success(res.message);
      loadHttp();
    } catch (e) {
      message.error(`Start failed: ${(e as Error).message}`);
    } finally {
      setHttpBusy(false);
    }
  };

  const handleStop = async () => {
    setHttpBusy(true);
    try {
      const res = await stopHttpServer();
      message.success(res.message);
      loadHttp();
    } catch (e) {
      message.error(`Stop failed: ${(e as Error).message}`);
    } finally {
      setHttpBusy(false);
    }
  };

  // antd Upload: read the file as base64 and POST it with a real progress bar,
  // then refresh the tree.
  const uploadProps: UploadProps = {
    showUploadList: false,
    beforeUpload: (file) => {
      const reader = new FileReader();
      reader.onload = async () => {
        const dataUrl = reader.result as string;
        const b64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
        setUploadName(file.name);
        setUploadPct(0);
        try {
          const res = await uploadFileTransfer(
            { dir: targetDir(), name: file.name, content_base64: b64 },
            (p) => setUploadPct(p)
          );
          setUploadPct(100);
          message.success(res.message);
          loadTree();
        } catch (e) {
          message.error(`Upload failed: ${(e as Error).message}`);
        } finally {
          // Briefly show 100% then clear.
          setTimeout(() => {
            setUploadPct(null);
            setUploadName("");
          }, 800);
        }
      };
      reader.readAsDataURL(file);
      return false; // prevent antd's own upload
    },
  };

  const handleNewFolder = () => {
    setNewFolderName("");
    setNewFolderOpen(true);
  };

  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) {
      message.warning("Folder name required");
      return;
    }
    setNewFolderSaving(true);
    try {
      const base = targetDir();
      const path = base ? `${base}/${newFolderName.trim()}` : newFolderName.trim();
      const res = await makeFileTransferDir(path);
      message.success(res.message);
      setNewFolderOpen(false);
      loadTree();
    } catch (e) {
      message.error(`Create failed: ${(e as Error).message}`);
    } finally {
      setNewFolderSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedPath) return;
    try {
      const res = selectedIsDir
        ? await deleteFileTransferDir(selectedPath)
        : await deleteFileTransferFile(selectedPath);
      message.success(res.message);
      setSelectedPath("");
      loadTree();
    } catch (e) {
      message.error(`Delete failed: ${(e as Error).message}`);
    }
  };

  const loadScpServers = () => {
    listScpServers()
      .then(setScpServers)
      .catch(() => {
        /* non-fatal; dropdown just stays empty */
      });
  };

  // Autofill Remote Directory + User when a cached Host is chosen.
  const onHostPick = (host: string) => {
    setScpHost(host);
    const hit = scpServers.find((s) => s.server === host);
    if (hit) {
      setScpRemoteDir(hit.upload_dir);
      setScpUser(hit.username);
    }
  };

  const removeScpServer = async (entry: ScpServer) => {
    try {
      const res = await deleteScpServer(entry);
      message.success(res.message);
      setScpServers((prev) =>
        prev.filter(
          (s) =>
            !(
              s.server === entry.server &&
              s.username === entry.username &&
              s.upload_dir === entry.upload_dir
            )
        )
      );
    } catch (e) {
      message.error(`Delete failed: ${(e as Error).message}`);
    }
  };

  const openScp = () => {
    if (!selectedPath) {
      message.warning("Select a file or directory first");
      return;
    }
    setScpPassword("");
    loadScpServers();
    setScpOpen(true);
  };

  const handleScp = async () => {
    if (!scpUser.trim() || !scpHost.trim() || !scpRemoteDir.trim()) {
      message.warning("User, host and remote directory are required");
      return;
    }
    setScpBusy(true);
    setScpPct(0);
    try {
      const { job_id } = await startScpUpload({
        rel_path: selectedPath,
        is_dir: selectedIsDir,
        user: scpUser.trim(),
        host: scpHost.trim(),
        remote_dir: scpRemoteDir.trim(),
        password: scpPassword,
      });
      // Poll progress until done.
      await new Promise<void>((resolve, reject) => {
        const tick = async () => {
          try {
            const s = await getScpStatus(job_id);
            setScpPct(s.percent);
            if (s.done) {
              if (s.ok) {
                message.success(s.message);
                resolve();
              } else {
                reject(new Error(s.message));
              }
              return;
            }
          } catch (e) {
            reject(e as Error);
            return;
          }
          setTimeout(tick, 700);
        };
        tick();
      });
      setScpOpen(false);
      setScpPassword("");
      loadScpServers(); // the successful target is now cached
    } catch (e) {
      message.error(`SCP failed: ${(e as Error).message}`);
    } finally {
      setScpBusy(false);
      setScpPct(null);
    }
  };

  const serverUrl = `http://${window.location.hostname}:${http.port ?? port}/`;

  // Apply the file search: prune the tree to matches and auto-expand to reveal them.
  const q = search.trim().toLowerCase();
  const { nodes: shownTree, expand: matchExpand } = useMemo(
    () => (q ? filterTree(tree, q) : { nodes: tree, expand: [] }),
    [tree, q]
  );
  // While searching, expand to matches; otherwise honor manual expand/collapse.
  const treeExpandedKeys = q && autoExpand ? matchExpand : expandedKeys;

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>
        File Transfer
      </Title>

      <Tabs
        defaultActiveKey="transfer"
        items={[
          {
            key: "transfer",
            label: "File Transfer",
            children: (
              <>
      {/* Root + HTTP server */}
      <Card title="Root &amp; HTTP Server" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong style={{ display: "block", marginBottom: 6 }}>
              Root Directory
            </Text>
            <Space.Compact style={{ width: "100%", maxWidth: 720 }}>
              <Input
                value={rootInput}
                onChange={(e) => setRootInput(e.target.value)}
                placeholder="absolute path, or empty for the default data/file_transfer"
              />
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={savingCfg}
                onClick={handleSaveConfig}
              >
                Save
              </Button>
            </Space.Compact>
            <Text type="secondary" style={{ display: "block", marginTop: 4 }}>
              Effective root: <Text code>{root}</Text>
            </Text>
          </div>

          <Space wrap align="center">
            <Text strong>HTTP Server Port</Text>
            <InputNumber
              min={1}
              max={65535}
              value={port}
              onChange={(v) => setPort(Number(v) || 9000)}
              disabled={http.running}
            />
            {http.running ? (
              <Button
                danger
                icon={<StopOutlined />}
                loading={httpBusy}
                onClick={handleStop}
              >
                Stop
              </Button>
            ) : (
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={httpBusy}
                onClick={handleStart}
              >
                Start
              </Button>
            )}
            {http.running ? (
              <Tag color="green">
                running (pid {http.pid}) &mdash;{" "}
                <a href={serverUrl} target="_blank" rel="noopener noreferrer">
                  {serverUrl}
                </a>
              </Tag>
            ) : (
              <Tag>stopped</Tag>
            )}
          </Space>
          <Text type="secondary">
            Serves the root directory via{" "}
            <Text code>python -m http.server &lt;port&gt; -b 0.0.0.0 -d &lt;root&gt;</Text>.
          </Text>
        </Space>
      </Card>

      {/* File tree + actions */}
      <Card
        title="Files"
        extra={
          <Space>
            <Input.Search
              allowClear
              placeholder="Search files"
              style={{ width: 240 }}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setAutoExpand(true);
              }}
            />
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={loadTree}
              loading={treeLoading}
            >
              Refresh
            </Button>
          </Space>
        }
      >
        <Space style={{ marginBottom: 12 }} wrap>
          <Upload {...uploadProps}>
            <Button icon={<UploadOutlined />}>Upload</Button>
          </Upload>
          <Button icon={<FolderAddOutlined />} onClick={handleNewFolder}>
            New Folder
          </Button>
          <Button
            icon={<CloudUploadOutlined />}
            disabled={!selectedPath}
            onClick={openScp}
          >
            SCP Upload
          </Button>
          <Popconfirm
            title={`Delete "${selectedPath}"?`}
            okText="Delete"
            okButtonProps={{ danger: true }}
            onConfirm={handleDelete}
            disabled={!selectedPath}
          >
            <Button danger icon={<DeleteOutlined />} disabled={!selectedPath}>
              Delete
            </Button>
          </Popconfirm>
          {selectedPath && (
            <Text type="secondary">
              Selected: <Text code>{selectedPath}</Text>{" "}
              ({selectedIsDir ? "directory" : "file"})
            </Text>
          )}
        </Space>
        {uploadPct !== null && (
          <div style={{ maxWidth: 480, marginBottom: 12 }}>
            <Text type="secondary">Uploading {uploadName}</Text>
            <Progress percent={uploadPct} size="small" />
          </div>
        )}
        <Tree
          showIcon
          blockNode
          treeData={toDataNodes(shownTree, q)}
          selectedKeys={selectedPath ? [selectedPath] : []}
          expandedKeys={treeExpandedKeys}
          onExpand={(keys) => {
            setExpandedKeys(keys);
            setAutoExpand(false); // user took manual control of expansion
          }}
          onSelect={(keys) => {
            const key = (keys[0] as string) || "";
            setSelectedPath(key);
            const node = key ? findNode(tree, key) : null;
            setSelectedIsDir(node ? node.type === "dir" : true);
          }}
        />
        {tree.length === 0 && !treeLoading && (
          <Text type="secondary">(root is empty)</Text>
        )}
        {tree.length > 0 && shownTree.length === 0 && (
          <Text type="secondary">(no files match "{search}")</Text>
        )}
      </Card>
              </>
            ),
          },
          {
            key: "runscript",
            label: "Cmdline",
            children: <RunScriptCard />,
          },
        ]}
      />

      {/* New folder modal (controlled, so it follows the app theme) */}
      <Modal
        title={`New Folder in "${targetDir() || "/"}"`}
        open={newFolderOpen}
        onOk={handleCreateFolder}
        confirmLoading={newFolderSaving}
        onCancel={() => setNewFolderOpen(false)}
        okText="Create"
      >
        <Input
          placeholder="folder name"
          value={newFolderName}
          onChange={(e) => setNewFolderName(e.target.value)}
          onPressEnter={handleCreateFolder}
        />
      </Modal>

      {/* SCP modal */}
      <Modal
        title={`SCP Upload: ${selectedPath}`}
        open={scpOpen}
        onOk={handleScp}
        confirmLoading={scpBusy}
        onCancel={() => setScpOpen(false)}
        okText="Upload"
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong>Host (IP)</Text>
            <AutoComplete
              style={{ width: "100%" }}
              value={scpHost}
              onChange={(v) => setScpHost(v)}
              onSelect={(v) => onHostPick(v)}
              placeholder="e.g. 10.64.16.16 (pick a saved host to autofill)"
              // Dedupe hosts for the dropdown; each option is deletable.
              options={Array.from(
                new Map(scpServers.map((s) => [s.server, s])).values()
              ).map((s) => ({
                value: s.server,
                label: (
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                  >
                    <span>
                      {s.server}{" "}
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {s.username}@…:{s.upload_dir}
                      </Text>
                    </span>
                    <DeleteIcon
                      style={{ color: "#ff4d4f" }}
                      onClick={(e) => {
                        e.stopPropagation();
                        removeScpServer(s);
                      }}
                    />
                  </div>
                ),
              }))}
              filterOption={(input, option) =>
                String(option?.value ?? "")
                  .toLowerCase()
                  .includes(input.toLowerCase())
              }
            />
          </div>
          <div>
            <Text strong>Remote Directory</Text>
            <Input
              value={scpRemoteDir}
              placeholder="e.g. /home/qauser/incoming"
              onChange={(e) => setScpRemoteDir(e.target.value)}
            />
          </div>
          <div>
            <Text strong>User</Text>
            <Input
              value={scpUser}
              placeholder="e.g. qauser"
              onChange={(e) => setScpUser(e.target.value)}
            />
          </div>
          <div>
            <Text strong>Password</Text>
            <Input.Password
              value={scpPassword}
              placeholder="SSH password (used only for this transfer)"
              onChange={(e) => setScpPassword(e.target.value)}
              autoComplete="new-password"
            />
          </div>
          {scpPct !== null && (
            <div>
              <Text type="secondary">Transferring…</Text>
              <Progress percent={scpPct} size="small" />
            </div>
          )}
        </Space>
      </Modal>
    </div>
  );
}
