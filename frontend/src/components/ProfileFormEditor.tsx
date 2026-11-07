import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Empty,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  CopyOutlined,
  DeleteOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { listDevices, matchDeviceForCase } from "../api/client";
import {
  CASE_TYPES,
  EXEC_MODES,
  newTask,
  normalizeProfile,
  parseProfile,
  stringifyProfile,
  type ProfileData,
  type ProfileTask,
  type TaskConfig,
} from "./profileModel";

const { Text } = Typography;

// A labelled field with an optional hint tooltip.
function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 12 }}>
      <Space size={4} style={{ marginBottom: 4 }}>
        <Text strong style={{ fontSize: 13 }}>
          {label}
        </Text>
        {hint && (
          <Tooltip title={hint}>
            <QuestionCircleOutlined style={{ color: "#999", fontSize: 12 }} />
          </Tooltip>
        )}
      </Space>
      {children}
    </div>
  );
}

interface Props {
  /** Current JSON text (shared with the JSON tab). */
  value: string;
  onChange: (next: string) => void;
  readOnly?: boolean;
}

/**
 * Guided profile editor: the graphical counterpart to the raw JSON tab.
 *
 * It reads and writes the very same JSON text, so switching tabs never loses
 * edits. Anything it cannot represent (unknown keys) is preserved untouched.
 */
export default function ProfileFormEditor({ value, onChange, readOnly }: Props) {
  const [devices, setDevices] = useState<string[]>([]);
  const [activeKeys, setActiveKeys] = useState<string[]>(["0"]);
  const [matchingIndex, setMatchingIndex] = useState<number | null>(null);

  useEffect(() => {
    listDevices()
      .then(setDevices)
      .catch(() => {
        /* dropdown falls back to free text when devices can't be loaded */
      });
  }, []);

  const profile = useMemo(() => parseProfile(value), [value]);
  const tasks = profile?.tasks ?? [];

  // Write the defaults the widgets display back into the JSON, so what the
  // form shows is exactly what gets saved. Runs whenever the parsed profile
  // gains fields that are still missing (e.g. an older profile without
  // `timeout`).
  useEffect(() => {
    if (!profile || readOnly) return;
    const normalized = normalizeProfile(profile);
    if (normalized) onChange(stringifyProfile(normalized));
  }, [profile, readOnly]); // eslint-disable-line react-hooks/exhaustive-deps

  // Every mutation goes through here so unknown/extra keys survive a round-trip.
  const patch = (changes: Partial<ProfileData>) => {
    if (!profile || readOnly) return;
    onChange(stringifyProfile({ ...profile, ...changes }));
  };

  const patchTask = (index: number, changes: Partial<ProfileTask>) => {
    if (!profile || readOnly) return;
    const next = tasks.map((t, i) => (i === index ? { ...t, ...changes } : t));
    patch({ tasks: next });
  };

  const patchConfig = (index: number, changes: Partial<TaskConfig>) => {
    if (!profile || readOnly) return;
    const next = tasks.map((t, i) =>
      i === index ? { ...t, config: { ...t.config, ...changes } } : t
    );
    patch({ tasks: next });
  };

  const addTask = () => {
    if (!profile || readOnly) return;
    patch({ tasks: [...tasks, newTask()] });
    setActiveKeys([String(tasks.length)]); // open the one just added
  };

  const duplicateTask = (index: number) => {
    if (!profile || readOnly) return;
    const copy = JSON.parse(JSON.stringify(tasks[index])) as ProfileTask;
    const next = [...tasks.slice(0, index + 1), copy, ...tasks.slice(index + 1)];
    patch({ tasks: next });
    setActiveKeys([String(index + 1)]);
  };

  const removeTask = (index: number) => {
    if (!profile || readOnly) return;
    patch({ tasks: tasks.filter((_, i) => i !== index) });
  };

  const autoMatchDevice = async (index: number, testrailCaseId: string) => {
    if (readOnly) return;
    setMatchingIndex(index);
    try {
      const res = await matchDeviceForCase(testrailCaseId);
      const device = res.device.replace(/\.json$/i, "");
      patchConfig(index, { device });
      message.success(
        res.reason ? `Matched ${device}: ${res.reason}` : `Matched ${device}`
      );
    } catch (e) {
      message.error(`Auto-match failed: ${(e as Error).message}`);
    } finally {
      setMatchingIndex(null);
    }
  };

  // The JSON tab can hold text this editor can't drive — say so instead of
  // silently showing an empty form (which would discard the user's work).
  if (!profile) {
    return (
      <Alert
        type="warning"
        showIcon
        message="Cannot show the guided editor"
        description="The current content is not a valid JSON object. Fix it on the JSON tab, then come back."
      />
    );
  }

  return (
    <div>
      {/* ---------- Profile level ---------- */}
      <Card size="small" title="Profile" style={{ marginBottom: 12 }}>
        <Row gutter={12}>
          <Col span={12}>
            <Field label="Name" hint='e.g. "execution plan 2659884070"'>
              <Input
                value={profile.name ?? ""}
                disabled={readOnly}
                placeholder="execution plan 2659884070"
                onChange={(e) => patch({ name: e.target.value })}
              />
            </Field>
          </Col>
          <Col span={12}>
            <Field
              label="Execution mode"
              hint="How the tasks of this profile run relative to each other."
            >
              <Select
                style={{ width: "100%" }}
                value={profile.execution_mode ?? "SERIAL"}
                disabled={readOnly}
                onChange={(v) => patch({ execution_mode: v })}
                options={EXEC_MODES.map((m) => ({ value: m, label: m }))}
              />
            </Field>
          </Col>
        </Row>
        <Field label="Description" hint='Any free text; "" is allowed.'>
          <Input.TextArea
            value={profile.description ?? ""}
            disabled={readOnly}
            autoSize={{ minRows: 1, maxRows: 3 }}
            placeholder="4K NA blocked re-run"
            onChange={(e) => patch({ description: e.target.value })}
          />
        </Field>
      </Card>

      {/* ---------- Tasks ---------- */}
      <Card
        size="small"
        title={`Tasks (${tasks.length})`}
        extra={
          !readOnly && (
            <Button
              type="primary"
              size="small"
              icon={<PlusOutlined />}
              onClick={addTask}
            >
              Add Task
            </Button>
          )
        }
      >
        {tasks.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="No tasks yet"
          >
            {!readOnly && (
              <Button type="primary" icon={<PlusOutlined />} onClick={addTask}>
                Add Task
              </Button>
            )}
          </Empty>
        ) : (
          <Collapse
            activeKey={activeKeys}
            onChange={(k) => setActiveKeys(Array.isArray(k) ? k : [k])}
            items={tasks.map((task, i) => {
              const cfg = task.config ?? ({} as TaskConfig);
              return {
                key: String(i),
                label: (
                  <Space size={6} wrap>
                    <Text strong>#{i + 1}</Text>
                    <Tag color="blue">{cfg.case_type || "?"}</Tag>
                    <Text style={{ fontFamily: "monospace", fontSize: 12 }}>
                      {cfg.case_id || <Text type="secondary">(no case id)</Text>}
                    </Text>
                    {cfg.device && <Tag>{cfg.device}</Tag>}
                  </Space>
                ),
                extra: !readOnly && (
                  <Space size={4}>
                    <Tooltip title="Duplicate task">
                      <Button
                        size="small"
                        type="text"
                        icon={<CopyOutlined />}
                        onClick={(e) => {
                          e.stopPropagation();
                          duplicateTask(i);
                        }}
                      />
                    </Tooltip>
                    <Tooltip title="Remove task">
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        onClick={(e) => {
                          e.stopPropagation();
                          removeTask(i);
                        }}
                      />
                    </Tooltip>
                  </Space>
                ),
                children: (
                  <div>
                    <Row gutter={12}>
                      <Col span={8}>
                        <Field label="Case type" hint="BDD | UT | NEW">
                          <Select
                            style={{ width: "100%" }}
                            value={cfg.case_type ?? "BDD"}
                            disabled={readOnly}
                            onChange={(v) => patchConfig(i, { case_type: v })}
                            options={CASE_TYPES.map((t) => ({
                              value: t,
                              label: t,
                            }))}
                          />
                        </Field>
                      </Col>
                      <Col span={16}>
                        <Field
                          label="Case ID"
                          hint={
                            cfg.case_type === "BDD"
                              ? 'BDD: numeric id, no bdd- prefix, e.g. "2659884070"'
                              : 'UT/NEW: "MyTestCase.test_something"'
                          }
                        >
                          <Input
                            value={String(cfg.case_id ?? "")}
                            disabled={readOnly}
                            style={{ fontFamily: "monospace" }}
                            placeholder={
                              cfg.case_type === "BDD"
                                ? "2659884070"
                                : "HdmiInputResQuantumDataTest.test_1080i_60"
                            }
                            onChange={(e) =>
                              patchConfig(i, { case_id: e.target.value })
                            }
                          />
                        </Field>
                      </Col>
                    </Row>
                    <Row gutter={12}>
                      <Col span={12}>
                        <Field
                          label="TestRail case ID"
                          hint="e.g. 2659884070. Leave empty when not uploading."
                        >
                          <Input
                            value={String(cfg.testrail_case_id ?? "")}
                            disabled={readOnly}
                            placeholder="2659884070"
                            onChange={(e) => {
                              const raw = e.target.value.trim();
                              // Keep it numeric when possible: profiles in the
                              // wild store this as a number.
                              patchConfig(i, {
                                testrail_case_id:
                                  raw === ""
                                    ? ""
                                    : /^\d+$/.test(raw)
                                    ? Number(raw)
                                    : raw,
                              });
                            }}
                          />
                        </Field>
                      </Col>
                      <Col span={12}>
                        <Field
                          label="Device"
                          hint="A device name from the Device tab. Auto-match uses the TestRail case ID."
                        >
                          <div style={{ display: "flex", gap: 8 }}>
                            <Select
                              style={{ flex: 1, minWidth: 0 }}
                              value={cfg.device || undefined}
                              disabled={readOnly}
                              placeholder="Select a device"
                              showSearch
                              options={devices.map((d) => ({
                                value: d,
                                label: d,
                              }))}
                              onChange={(v) => patchConfig(i, { device: v })}
                              notFoundContent="No devices"
                            />
                            <Button
                              icon={<ThunderboltOutlined />}
                              disabled={
                                readOnly ||
                                String(cfg.testrail_case_id ?? "").trim() === ""
                              }
                              loading={matchingIndex === i}
                              onClick={() =>
                                autoMatchDevice(
                                  i,
                                  String(cfg.testrail_case_id ?? "").trim()
                                )
                              }
                            >
                              Auto-match
                            </Button>
                          </div>
                        </Field>
                      </Col>
                    </Row>
                    <Row gutter={12}>
                      <Col span={8}>
                        <Field
                          label="TestRail plan ID"
                          hint="0 = no plan (results are not uploaded)."
                        >
                          <InputNumber
                            style={{ width: "100%" }}
                            value={cfg.testrail_plan_id ?? 0}
                            disabled={readOnly}
                            min={0}
                            onChange={(v) =>
                              patchConfig(i, { testrail_plan_id: Number(v ?? 0) })
                            }
                          />
                        </Field>
                      </Col>
                      <Col span={8}>
                        <Field
                          label="Repeat"
                          hint="0 = run once, 2 = run 3 times total."
                        >
                          <InputNumber
                            style={{ width: "100%" }}
                            value={cfg.repeat ?? 0}
                            disabled={readOnly}
                            min={0}
                            onChange={(v) => patchConfig(i, { repeat: Number(v ?? 0) })}
                          />
                        </Field>
                      </Col>
                      <Col span={8}>
                        <Field label="Timeout (s)" hint="e.g. 36000 or 360000.">
                          <InputNumber
                            style={{ width: "100%" }}
                            value={task.timeout ?? 36000}
                            disabled={readOnly}
                            min={1}
                            onChange={(v) =>
                              patchTask(i, { timeout: Number(v ?? 36000) })
                            }
                          />
                        </Field>
                      </Col>
                    </Row>
                    <Row gutter={12}>
                      <Col span={12}>
                        <Field
                          label="Automation test branch"
                          hint='e.g. "main" or "yuzheng/AUTO-73326/fix"'
                        >
                          <Input
                            value={cfg.automation_test_branch ?? "main"}
                            disabled={readOnly}
                            onChange={(e) =>
                              patchConfig(i, {
                                automation_test_branch: e.target.value,
                              })
                            }
                          />
                        </Field>
                      </Col>
                      <Col span={12}>
                        <Field label="Roku automation branch" hint='e.g. "main"'>
                          <Input
                            value={cfg.roku_automation_branch ?? "main"}
                            disabled={readOnly}
                            onChange={(e) =>
                              patchConfig(i, {
                                roku_automation_branch: e.target.value,
                              })
                            }
                          />
                        </Field>
                      </Col>
                    </Row>
                  </div>
                ),
              };
            })}
          />
        )}
      </Card>
    </div>
  );
}
