import { useEffect, useRef, useState } from "react";
import {
  Button,
  Card,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Tag,
  Tree,
  Typography,
  Upload,
  message,
} from "antd";
import type { DataNode } from "antd/es/tree";
import type { UploadProps } from "antd";
import {
  ReloadOutlined,
  ClearOutlined,
  FolderAddOutlined,
  DeleteOutlined,
  UploadOutlined,
  FileAddOutlined,
  EditOutlined,
  FolderOutlined,
  FileOutlined,
} from "@ant-design/icons";
import {
  getCmdTree,
  getCmdFile,
  saveCmdFile,
  uploadCmdFile,
  deleteCmdFile,
  makeCmdDir,
  deleteCmdDir,
  runCmd,
  listCmdCache,
  deleteCmdCache,
  sshStart,
  sshInput,
  sshOutput,
  sshStop,
  type CmdTreeNode,
  type CmdRunResult,
  type CmdCacheEntry,
} from "../api/client";
import ShellEditor from "../components/ShellEditor";

const { Text } = Typography;

function fmtSize(n?: number): string {
  if (n === undefined) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function toDataNodes(nodes: CmdTreeNode[]): DataNode[] {
  return nodes.map((n) => ({
    key: n.path,
    title: n.type === "file" ? `${n.name}  (${fmtSize(n.size)})` : n.name,
    icon: n.type === "dir" ? <FolderOutlined /> : <FileOutlined />,
    isLeaf: n.type === "file",
    children: n.children ? toDataNodes(n.children) : undefined,
  }));
}

function findNode(nodes: CmdTreeNode[], path: string): CmdTreeNode | null {
  for (const n of nodes) {
    if (n.path === path) return n;
    if (n.children) {
      const hit = findNode(n.children, path);
      if (hit) return hit;
    }
  }
  return null;
}

export default function RunScriptCard() {
  const [tree, setTree] = useState<CmdTreeNode[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string>("");
  const [selectedIsDir, setSelectedIsDir] = useState<boolean>(true);

  // Terminal console: the prompt input + a scrollback of past runs.
  const [cmdline, setCmdline] = useState("");
  const [running, setRunning] = useState(false);
  // A console line is either a real run result, a bare prompt echo, or raw SSH
  // session output (raw text, no exit line).
  const [console_, setConsole] = useState<
    (CmdRunResult & { bare?: boolean; raw?: string })[]
  >([]);
  const consoleRef = useRef<HTMLDivElement>(null);
  const promptRef = useRef<HTMLInputElement>(null);
  // Current working dir, carried across commands so `cd` persists (undefined =
  // the backend's cmd root). Updated from each run's reported cwd.
  const cwdRef = useRef<string | undefined>(undefined);
  // Up/Down arrow history navigation within the prompt.
  const [histIdx, setHistIdx] = useState<number>(-1);
  // Password prompt for ssh/scp commands. pwMode distinguishes a one-shot run
  // from opening an interactive login session.
  const [pwOpen, setPwOpen] = useState(false);
  const [pwCmd, setPwCmd] = useState("");
  const [pwValue, setPwValue] = useState("");
  const [pwMode, setPwMode] = useState<"run" | "login">("run");
  const [pwLogin, setPwLogin] = useState<{ user: string; host: string } | null>(null);

  // Interactive ssh session (persistent login). When set, the prompt sends input
  // to the remote shell instead of running local commands.
  const sshRef = useRef<{ id: string; offset: number } | null>(null);
  const [sshLabel, setSshLabel] = useState<string>("");
  const sshPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Run cache (history)
  const [cache, setCache] = useState<CmdCacheEntry[]>([]);

  // Editor modal (create / edit a text script)
  const [editOpen, setEditOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editIsNew, setEditIsNew] = useState(true);
  const [editSaving, setEditSaving] = useState(false);

  // New folder modal (themed, controlled — not Modal.confirm, which ignores theme)
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [newFolderSaving, setNewFolderSaving] = useState(false);

  const uploadingRef = useRef(false);

  const loadTree = () => {
    setTreeLoading(true);
    getCmdTree()
      .then((d) => setTree(d.tree))
      .catch((e: Error) => message.error(`Load scripts failed: ${e.message}`))
      .finally(() => setTreeLoading(false));
  };

  const loadCache = () => {
    listCmdCache()
      // Keep only well-formed records (ignore any legacy/hand-edited entries).
      .then((list) =>
        setCache(list.filter((c) => typeof c.cmdline === "string" && c.cmdline))
      )
      .catch(() => {
        /* non-fatal */
      });
  };

  useEffect(() => {
    loadTree();
    loadCache();
  }, []);

  // Directory that a new file / folder / upload should target.
  const targetDir = (): string => {
    if (!selectedPath) return "";
    if (selectedIsDir) return selectedPath;
    const idx = selectedPath.lastIndexOf("/");
    return idx === -1 ? "" : selectedPath.slice(0, idx);
  };

  // Keep the console scrolled to the bottom as new output lands.
  useEffect(() => {
    const el = consoleRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [console_, running]);

  // ssh/scp with a remote command needs a password; detect to prompt first.
  const needsPassword = (cmd: string) => /^\s*(ssh|scp)\b/.test(cmd);
  // A bare `ssh [opts] user@host` (no trailing remote command) = interactive login.
  const parseSshLogin = (cmd: string): { user: string; host: string } | null => {
    const m = cmd.match(/^\s*ssh\s+(?:-\S+\s+)*([^\s@]+)@([^\s]+)\s*$/);
    return m ? { user: m[1], host: m[2] } : null;
  };

  const appendRaw = (text: string) =>
    setConsole((prev) => {
      // Merge consecutive raw chunks into the last raw line for a smooth stream.
      const last = prev[prev.length - 1];
      if (last && last.raw !== undefined) {
        const copy = [...prev];
        copy[copy.length - 1] = { ...last, raw: last.raw + text };
        return copy;
      }
      return [
        ...prev,
        { cmdline: "", exit_code: 0, timed_out: false, elapsed: 0, stdout: "", stderr: "", raw: text },
      ];
    });

  const stopSshPoll = () => {
    if (sshPollRef.current) {
      clearInterval(sshPollRef.current);
      sshPollRef.current = null;
    }
  };

  const endSshSession = (note?: string) => {
    stopSshPoll();
    sshRef.current = null;
    setSshLabel("");
    if (note) appendRaw(note);
    requestAnimationFrame(() => promptRef.current?.focus());
  };

  // Poll the session's output and stream it into the console.
  const pollSsh = async () => {
    const sess = sshRef.current;
    if (!sess) return;
    try {
      const res = await sshOutput(sess.id, sess.offset);
      if (res.data) {
        sess.offset = res.offset;
        appendRaw(res.data);
      }
      if (!res.alive) {
        endSshSession("\n[session closed]\n");
      }
    } catch {
      endSshSession("\n[session lost]\n");
    }
  };

  const startSshSession = async (user: string, host: string, password?: string) => {
    appendRaw(`$ ssh ${user}@${host}\n`);
    try {
      const { session_id, label } = await sshStart({ host, user, password });
      sshRef.current = { id: session_id, offset: 0 };
      setSshLabel(label);
      stopSshPoll();
      sshPollRef.current = setInterval(pollSsh, 500);
    } catch (e) {
      appendRaw(`[ssh failed: ${(e as Error).message}]\n`);
    }
    requestAnimationFrame(() => promptRef.current?.focus());
  };

  // Password modal OK: either open a login session or run a one-shot command.
  const submitPassword = () => {
    setPwOpen(false);
    const pw = pwValue;
    if (pwMode === "login" && pwLogin) {
      startSshSession(pwLogin.user, pwLogin.host, pw || undefined);
    } else {
      execRun(pwCmd, pw);
    }
  };

  // Tear down any live ssh session when the component unmounts.
  useEffect(() => {
    return () => {
      const sess = sshRef.current;
      stopSshPoll();
      if (sess) sshStop(sess.id).catch(() => {});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRun = async () => {
    const raw = cmdline;
    const cmd = cmdline.trim();

    // If an interactive ssh session is active, send the line to the remote shell.
    if (sshRef.current) {
      appendRaw(raw + "\n"); // local echo of what we typed
      const sess = sshRef.current;
      setCmdline("");
      try {
        await sshInput(sess.id, raw + "\n");
      } catch (e) {
        appendRaw(`[send failed: ${(e as Error).message}]\n`);
      }
      requestAnimationFrame(() => promptRef.current?.focus());
      return;
    }

    // Empty Enter: echo a bare prompt line (like a real shell), run nothing.
    if (!cmd) {
      setConsole((prev) => [
        ...prev,
        {
          cmdline: "",
          exit_code: 0,
          timed_out: false,
          elapsed: 0,
          stdout: "",
          stderr: "",
          bare: true,
        },
      ]);
      setCmdline("");
      setHistIdx(-1);
      requestAnimationFrame(() => promptRef.current?.focus());
      return;
    }

    // Bare `ssh user@host` -> open a persistent interactive login session.
    const login = parseSshLogin(cmd);
    if (login) {
      setCmdline("");
      setHistIdx(-1);
      setPwCmd(cmd);
      setPwValue("");
      setPwMode("login");
      setPwLogin(login);
      setPwOpen(true);
      return;
    }

    // ssh/scp with a remote command -> one-shot run, ask for a password first.
    if (needsPassword(cmd)) {
      setPwCmd(cmd);
      setPwValue("");
      setPwMode("run");
      setPwOpen(true);
      return;
    }
    await execRun(cmd);
  };

  // Actually run a command (optionally with an ssh/scp password) and append the
  // result to the console.
  const execRun = async (cmd: string, password?: string) => {
    setRunning(true);
    setCmdline("");
    setHistIdx(-1);
    try {
      const res = await runCmd(cmd, password, cwdRef.current);
      if (res.cwd) cwdRef.current = res.cwd; // persist cd across commands
      setConsole((prev) => [...prev, res]);
      loadCache();
    } catch (e) {
      setConsole((prev) => [
        ...prev,
        {
          cmdline: cmd,
          exit_code: -1,
          timed_out: false,
          elapsed: 0,
          stdout: "",
          stderr: (e as Error).message,
        },
      ]);
    } finally {
      setRunning(false);
      requestAnimationFrame(() => promptRef.current?.focus());
    }
  };

  // Up/Down to walk through previous commands (newest cache first).
  const handlePromptKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (sshRef.current) return; // in a session, don't do local history nav
    if (e.key === "ArrowUp") {
      if (cache.length === 0) return;
      e.preventDefault();
      const next = Math.min(histIdx + 1, cache.length - 1);
      setHistIdx(next);
      setCmdline(cache[next]?.cmdline ?? "");
    } else if (e.key === "ArrowDown") {
      if (histIdx < 0) return;
      e.preventDefault();
      const next = histIdx - 1;
      setHistIdx(next);
      setCmdline(next < 0 ? "" : cache[next]?.cmdline ?? "");
    }
  };

  // Click a tree file to insert its path into the cmdline for convenience.
  const insertPathIntoCmdline = (path: string) => {
    setCmdline((prev) => (prev ? `${prev} ${path}` : path));
  };

  const openNewFile = () => {
    setEditIsNew(true);
    setEditName("");
    setEditContent("#!/usr/bin/env bash\n");
    setEditOpen(true);
  };

  const openEditFile = async () => {
    if (!selectedPath || selectedIsDir) {
      message.warning("Select a file to edit");
      return;
    }
    try {
      const content = await getCmdFile(selectedPath);
      const name = selectedPath.includes("/")
        ? selectedPath.slice(selectedPath.lastIndexOf("/") + 1)
        : selectedPath;
      setEditIsNew(false);
      setEditName(name);
      setEditContent(content);
      setEditOpen(true);
    } catch (e) {
      message.error(`Open failed: ${(e as Error).message}`);
    }
  };

  const handleSaveFile = async () => {
    if (!editName.trim()) {
      message.warning("File name is required");
      return;
    }
    setEditSaving(true);
    try {
      // New file: save into the selected dir. Edit: save back to its own dir.
      const dir = editIsNew
        ? targetDir()
        : selectedPath.includes("/")
        ? selectedPath.slice(0, selectedPath.lastIndexOf("/"))
        : "";
      const res = await saveCmdFile({ dir, name: editName.trim(), content: editContent });
      message.success(res.message);
      setEditOpen(false);
      loadTree();
    } catch (e) {
      message.error(`Save failed: ${(e as Error).message}`);
    } finally {
      setEditSaving(false);
    }
  };

  const uploadProps: UploadProps = {
    showUploadList: false,
    beforeUpload: (file) => {
      if (uploadingRef.current) return false;
      uploadingRef.current = true;
      const reader = new FileReader();
      reader.onload = async () => {
        const dataUrl = reader.result as string;
        const b64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
        try {
          const res = await uploadCmdFile({
            dir: targetDir(),
            name: file.name,
            content_base64: b64,
          });
          message.success(res.message);
          loadTree();
        } catch (e) {
          message.error(`Upload failed: ${(e as Error).message}`);
        } finally {
          uploadingRef.current = false;
        }
      };
      reader.readAsDataURL(file);
      return false;
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
      const res = await makeCmdDir(path);
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
        ? await deleteCmdDir(selectedPath)
        : await deleteCmdFile(selectedPath);
      message.success(res.message);
      setSelectedPath("");
      loadTree();
    } catch (e) {
      message.error(`Delete failed: ${(e as Error).message}`);
    }
  };

  // Pick a history entry: load its cmdline back into the input.
  const applyCache = (c: CmdCacheEntry) => {
    setCmdline(c.cmdline);
  };

  const removeCache = async (c: CmdCacheEntry) => {
    try {
      await deleteCmdCache(c.cmdline);
      setCache((prev) => prev.filter((x) => x.cmdline !== c.cmdline));
    } catch (e) {
      message.error(`Delete failed: ${(e as Error).message}`);
    }
  };

  return (
    <Card
      title="Script files"
      extra={
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={loadTree}
          loading={treeLoading}
        >
          Refresh
        </Button>
      }
    >
      <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
        Scripts &amp; data files under <Text code>QATools/data/cmd</Text>. Select a
        script, enter arguments, and Run.
      </Text>

      <Space style={{ marginBottom: 12 }} wrap>
        <Button icon={<FileAddOutlined />} onClick={openNewFile}>
          New File
        </Button>
        <Button
          icon={<EditOutlined />}
          disabled={!selectedPath || selectedIsDir}
          onClick={openEditFile}
        >
          Edit
        </Button>
        <Upload {...uploadProps}>
          <Button icon={<UploadOutlined />}>Upload</Button>
        </Upload>
        <Button icon={<FolderAddOutlined />} onClick={handleNewFolder}>
          New Folder
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
      </Space>

      {/* Tree (collapsed by default). Click a file to append its path to the cmdline. */}
      <Tree
        showIcon
        blockNode
        treeData={toDataNodes(tree)}
        selectedKeys={selectedPath ? [selectedPath] : []}
        onSelect={(keys) => {
          const key = (keys[0] as string) || "";
          setSelectedPath(key);
          const node = key ? findNode(tree, key) : null;
          const isDir = node ? node.type === "dir" : true;
          setSelectedIsDir(isDir);
          if (key && !isDir) insertPathIntoCmdline(key);
        }}
      />
      {tree.length === 0 && !treeLoading && (
        <Text type="secondary">(no scripts yet)</Text>
      )}

      {/* Terminal console: scrollback of past runs + a bottom prompt. Enter runs. */}
      <div style={{ marginTop: 16 }}>
        <Space style={{ marginBottom: 6 }}>
          <Text strong>Cmdline</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            press Enter to run &middot; ↑/↓ for history
          </Text>
          {console_.length > 0 && (
            <Button
              size="small"
              type="text"
              icon={<ClearOutlined />}
              onClick={() => setConsole([])}
            >
              Clear
            </Button>
          )}
          {cache.length > 0 && (
            <Select
              size="small"
              style={{ minWidth: 200 }}
              placeholder="history"
              value={undefined}
              onChange={(idx: number) => applyCache(cache[idx])}
              popupMatchSelectWidth={false}
              options={cache.map((c, i) => ({
                value: i,
                label: (
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: 12,
                    }}
                  >
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                      <Tag color={c.exit_code === 0 ? "green" : "red"}>
                        {c.exit_code}
                      </Tag>
                      {c.cmdline}
                    </span>
                    <DeleteOutlined
                      style={{ color: "#ff4d4f" }}
                      onClick={(e) => {
                        e.stopPropagation();
                        removeCache(c);
                      }}
                    />
                  </div>
                ),
              }))}
            />
          )}
        </Space>

        <div
          ref={consoleRef}
          style={{
            background: "#1e1e1e",
            color: "#d4d4d4",
            borderRadius: 6,
            padding: 12,
            // Grow with content; only scroll once it exceeds ~40 lines.
            // 40 lines * 1.5 * 12px + 24px padding ≈ 744px.
            maxHeight: 744,
            overflow: "auto",
            fontFamily: "Consolas, Menlo, monospace",
            fontSize: 12,
            lineHeight: 1.5,
          }}
          onClick={() => promptRef.current?.focus()}
        >
          {console_.map((r, i) =>
            r.raw !== undefined ? (
              // Raw interactive (ssh session) output, streamed verbatim.
              <div key={i} style={{ whiteSpace: "pre-wrap" }}>{r.raw}</div>
            ) : r.bare ? (
              // Bare empty-Enter line: just the prompt, like a real shell.
              <div key={i} style={{ color: "#5fb85f" }}>$</div>
            ) : (
              <div key={i} style={{ marginBottom: 8 }}>
                <div style={{ color: "#8ab4f8", whiteSpace: "pre-wrap" }}>
                  <span style={{ color: "#5fb85f" }}>$ </span>
                  {r.cmdline}
                </div>
                {r.stdout && (
                  <div style={{ whiteSpace: "pre-wrap" }}>{r.stdout}</div>
                )}
                {r.stderr && (
                  <div style={{ color: "#ff8080", whiteSpace: "pre-wrap" }}>
                    {r.stderr}
                  </div>
                )}
                <div style={{ color: "#777" }}>
                  [exit {r.exit_code}
                  {r.timed_out ? ", timed out" : ""} &middot; {r.elapsed}s]
                </div>
              </div>
            )
          )}
          {/* Inline prompt, part of the console like a real terminal. */}
          <div style={{ display: "flex", alignItems: "center" }}>
            <span
              style={{
                color: sshLabel ? "#f7c873" : "#5fb85f",
                marginRight: 6,
                whiteSpace: "nowrap",
              }}
            >
              {sshLabel ? `${sshLabel} $` : "$"}
            </span>
            <input
              ref={promptRef}
              value={cmdline}
              disabled={running && !sshLabel}
              placeholder={
                sshLabel
                  ? "remote shell — Enter to send, type exit to disconnect"
                  : running
                  ? "running…"
                  : "type a command and press Enter"
              }
              onChange={(e) => setCmdline(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleRun();
                else handlePromptKey(e);
              }}
              style={{
                flex: 1,
                background: "transparent",
                border: "none",
                outline: "none",
                color: "#d4d4d4",
                fontFamily: "inherit",
                fontSize: 12,
              }}
            />
          </div>
        </div>
      </div>

      {/* Create / edit file modal */}
      <Modal
        title={editIsNew ? "New File" : `Edit: ${editName}`}
        open={editOpen}
        onOk={handleSaveFile}
        confirmLoading={editSaving}
        onCancel={() => setEditOpen(false)}
        okText="Save"
        width={760}
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong>File name</Text>
            <Input
              value={editName}
              disabled={!editIsNew}
              placeholder="e.g. hello.sh or deploy.py"
              onChange={(e) => setEditName(e.target.value)}
            />
          </div>
          <div>
            <Text strong>Content</Text>
            <ShellEditor value={editContent} onChange={setEditContent} />
          </div>
        </Space>
      </Modal>

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

      {/* SSH/SCP password prompt */}
      <Modal
        title="SSH Password"
        open={pwOpen}
        onOk={submitPassword}
        onCancel={() => setPwOpen(false)}
        okText={pwMode === "login" ? "Connect" : "Run"}
      >
        <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
          Password for <Text code>{pwCmd}</Text>
          <br />
          (leave empty to use key-based auth)
        </Text>
        <Input.Password
          autoFocus
          value={pwValue}
          placeholder="SSH password (used only for this session)"
          onChange={(e) => setPwValue(e.target.value)}
          onPressEnter={submitPassword}
        />
      </Modal>
    </Card>
  );
}
