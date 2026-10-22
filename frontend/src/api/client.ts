// Backend base URL. Backend runs on 127.0.0.1:9888 with open CORS.
export const API_BASE = "/api";

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    // FastAPI errors come back as { detail: "..." }
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const err = await resp.json();
      if (err?.detail) detail = err.detail;
    } catch {
      /* ignore non-json error bodies */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

// Backend list APIs return filenames WITH the .json suffix, but the item APIs
// (view/add/update/delete) take the name WITHOUT .json. Strip it once here.
const stripJson = (f: string) => f.replace(/\.json$/i, "");

// ---------- Device ----------
export async function listDevices(): Promise<string[]> {
  const data = await request<{ devices: string[] }>("GET", "/v1/device/list");
  return (data.devices ?? []).map(stripJson);
}

// Per-device presence flags for the key roku config sub-sections, shown as
// check/cross columns in the Device table.
export interface DeviceDetail {
  name: string;
  ip_address: string;
  qa_bot_config: boolean;
  maxwell_config: boolean;
  power_config: boolean;
  avr_info_config: boolean;
  hdmi_1: boolean;
  hdmi_2: boolean;
  hdmi_3: boolean;
  // Index signature so it satisfies ConfigManager's Row ({name} & record).
  [key: string]: string | boolean;
}
export async function listDeviceDetails(): Promise<DeviceDetail[]> {
  const data = await request<{ devices: DeviceDetail[] }>("GET", "/v1/device/list_details");
  return data.devices ?? [];
}
export function getDevice(name: string): Promise<Record<string, unknown>> {
  return request("GET", `/v1/device/${name}`);
}
export function addDevice(name: string, data: unknown): Promise<{ message: string }> {
  return request("POST", `/v1/device/add/${name}`, data);
}
export function updateDevice(name: string, data: unknown): Promise<{ message: string }> {
  return request("PATCH", `/v1/device/update/${name}`, data);
}
export function deleteDevice(name: string): Promise<{ message: string }> {
  return request("DELETE", `/v1/device/delete/${name}`);
}

export function syncDeviceWithQaHub(name: string): Promise<Record<string, unknown>> {
  return request("PATCH", `/v1/device/sync_with_qa_hub/${name}`);
}

// ---------- Admin login ----------
export function adminLogin(
  username: string,
  password: string
): Promise<{ ok: boolean }> {
  return request("POST", "/v1/config/admin/login", { username, password });
}

// ---------- Config (tab visibility) ----------
export interface TabConfig {
  name: string;
  status: boolean;
  order: number;
}

export async function listTabs(): Promise<TabConfig[]> {
  const data = await request<{ tabs: TabConfig[] }>("GET", "/v1/config/tabs/list");
  return data.tabs ?? [];
}

export function setTabVisibility(
  name: string,
  status: boolean
): Promise<{ message: string }> {
  const action = status ? "enable" : "disable";
  return request("GET", `/v1/config/tabs/${encodeURIComponent(name)}/${action}`);
}

// Set the full display order (left-nav renders in this order).
export function reorderTabs(order: string[]): Promise<{ message: string }> {
  return request("PUT", "/v1/config/tabs/reorder", { order });
}

export interface AgentModelConfig {
  name: string;
  description: string;
  model: string;
  max_tokens: number;
  temperature: number;
}

export async function listModels(): Promise<AgentModelConfig[]> {
  const data = await request<{ models: AgentModelConfig[] }>(
    "GET",
    "/v1/config/models/list"
  );
  return data.models ?? [];
}

export function addModel(m: AgentModelConfig): Promise<{ message: string }> {
  return request("POST", "/v1/config/models/add", m);
}

export function updateModel(
  name: string,
  m: AgentModelConfig
): Promise<{ message: string }> {
  return request("PUT", `/v1/config/models/update/${encodeURIComponent(name)}`, m);
}

export function deleteModel(name: string): Promise<{ message: string }> {
  return request("DELETE", `/v1/config/models/delete/${encodeURIComponent(name)}`);
}

export interface AgentCred {
  api_key_masked: string;
  api_key_set: boolean;
  key_id_masked: string;
  key_id_set: boolean;
  key_alias: string;
}

export function getAgentCred(): Promise<AgentCred> {
  return request("GET", "/v1/config/agent/get");
}

// Empty api_key/key_id are ignored by the backend (keeps the stored value).
export function updateAgentCred(body: {
  api_key?: string;
  key_id?: string;
  key_alias?: string;
}): Promise<{ message: string }> {
  return request("PUT", "/v1/config/agent/update", body);
}

export interface DefaultModel {
  model: string;
  timeout_sec: number;
  max_tokens: number;
  temperature: number;
}

export function getDefaultModel(): Promise<DefaultModel> {
  return request("GET", "/v1/config/agent/default");
}

export function setDefaultModel(body: DefaultModel): Promise<{ message: string }> {
  return request("PUT", "/v1/config/agent/default", body);
}

// ---------- Account settings (config/env.py overrides) ----------
// Secret fields come back masked with a matching *_set flag; secret_fields lists
// which keys are secret.
export interface AccountSettings {
  QAHUB_TOKEN: string;
  EMAIL: string;
  TESTRAIL_USERNAME: string;
  TESTRAIL_API_KEY: string;
  JIRA_TOKEN: string;
  DATA_BASE_DIR: string;
  ROKU_TEST_LOG_DIR: string;
  AUTOMATED_TESTS_RELATIVE_DIR: string;
  secret_fields: string[];
  [k: string]: string | string[] | boolean;
}

export function getAccount(): Promise<AccountSettings> {
  return request("GET", "/v1/config/account/get");
}

export function updateAccount(
  body: Record<string, string>
): Promise<{ message: string }> {
  return request("PUT", "/v1/config/account/update", body);
}

export type AnalyzeLocale = "en-US" | "zh-CN";

export interface AnalyzeConfig {
  default_locale: AnalyzeLocale;
  prompt_template: string;
}

export function getAnalyzeConfig(): Promise<AnalyzeConfig> {
  return request("GET", "/v1/config/analyze/get");
}

export function updateAnalyzeConfig(
  body: AnalyzeConfig
): Promise<{ message: string }> {
  return request("PUT", "/v1/config/analyze/update", body);
}

export function restartBackend(): Promise<{ message: string }> {
  return request("POST", "/v1/config/backend/restart");
}

// ---------- Profile ----------
export async function listProfiles(): Promise<string[]> {
  const data = await request<{ profiles: string[] }>("GET", "/v1/profile/list");
  return (data.profiles ?? []).map(stripJson);
}
export function getProfile(name: string): Promise<Record<string, unknown>> {
  return request("GET", `/v1/profile/${name}`);
}
export function addProfile(name: string, data: unknown): Promise<{ message: string }> {
  return request("POST", `/v1/profile/add/${name}`, data);
}
export function updateProfile(name: string, data: unknown): Promise<{ message: string }> {
  return request("PATCH", `/v1/profile/update/${name}`, data);
}
export function deleteProfile(name: string): Promise<{ message: string }> {
  return request("DELETE", `/v1/profile/delete/${name}`);
}

// ---------- Run case ----------
// Backend takes profile_name + select as query params.
export function runCase(
  profileName: string,
  select: string
): Promise<{ message: string; pid: number }> {
  const qs = `?profile_name=${encodeURIComponent(profileName)}&select=${encodeURIComponent(select)}`;
  return request("POST", `/v1/runcase/run${qs}`);
}

export interface RunningCase {
  pid: string;
  profile: string;
  select: string;
}

// list_running returns lines like:
//   [PID]:12345    [Profile]:p_01    [Select]:All
//   Total: 1
export async function listRunningCases(): Promise<RunningCase[]> {
  const data = await request<{ running_cases: string }>("GET", "/v1/runcase/list_running");
  const text = data.running_cases || "";
  const rows: RunningCase[] = [];
  for (const line of text.split("\n")) {
    const m = line.match(/\[PID\]:\s*(\S+)\s*\[Profile\]:\s*(\S*)\s*\[Select\]:\s*(\S*)/);
    if (m) rows.push({ pid: m[1], profile: m[2], select: m[3] });
  }
  return rows;
}

export function stopCase(pid: string | number): Promise<unknown> {
  return request("POST", `/v1/runcase/stop?pid=${pid}`);
}

// ---------- Users ----------
// GET /v1/runcase/user_query_list -> { user_query_list: [{ name }] }; we only need names.
export async function listUserNames(): Promise<string[]> {
  const data = await request<{ user_query_list: { name: string }[] }>("GET", "/v1/runcase/user_query_list");
  return (data.user_query_list ?? []).map((u) => u.name).filter(Boolean);
}

// Remember a searched user name; returns the updated name list.
export async function addUserQuery(name: string): Promise<string[]> {
  const data = await request<{ user_query_list: { name: string }[] }>(
    "POST",
    "/v1/runcase/user_query_list/add",
    { name }
  );
  return (data.user_query_list ?? []).map((u) => u.name).filter(Boolean);
}

// Delete a saved user name; returns the updated name list.
export async function deleteUserQuery(name: string): Promise<string[]> {
  const data = await request<{ user_query_list: { name: string }[] }>(
    "DELETE",
    `/v1/runcase/user_query_list/${encodeURIComponent(name)}`
  );
  return (data.user_query_list ?? []).map((u) => u.name).filter(Boolean);
}

// list_cache / list_report return [{ name, mtime(epoch secs) }].
export interface RunFile {
  name: string;
  mtime: number;
}

export async function listRunCache(): Promise<RunFile[]> {
  const data = await request<{ files: RunFile[] }>("GET", "/v1/runcase/list_cache");
  return data.files ?? [];
}

export async function listRunReports(): Promise<RunFile[]> {
  const data = await request<{ files: RunFile[] }>("GET", "/v1/runcase/list_report");
  return data.files ?? [];
}

export async function viewRunCache(file: string): Promise<string> {
  const data = await request<{ cache_file_content: string }>(
    "GET",
    `/v1/runcase/view_cache/${encodeURIComponent(file)}`
  );
  return data.cache_file_content || "";
}

export async function viewRunReport(file: string): Promise<string> {
  const data = await request<{ summary_report_content: string }>(
    "GET",
    `/v1/runcase/view_report/${encodeURIComponent(file)}`
  );
  return data.summary_report_content || "";
}

export function clearRunData(): Promise<{ message: string }> {
  return request("GET", "/v1/runcase/clear");
}

export function deleteRunCache(file: string): Promise<{ message: string }> {
  return request("GET", `/v1/runcase/delete_cache/${encodeURIComponent(file)}`);
}

export function deleteRunReport(file: string): Promise<{ message: string }> {
  return request("GET", `/v1/runcase/delete_report/${encodeURIComponent(file)}`);
}

// ---------- Suites (QAHub) ----------
export interface Suite {
  id: number;
  name: string;
  user: string;
  state: string;
  tests_total: number;
  tests_complete: number;
  progress: number;
}

export async function listSuites(user: string, state = "running"): Promise<Suite[]> {
  const qs = `?user=${encodeURIComponent(user)}&state=${encodeURIComponent(state)}`;
  const data = await request<{ suites: Suite[] }>("GET", `/v1/runcase/list_suites${qs}`);
  return data.suites ?? [];
}

export function terminateSuite(suiteId: number): Promise<{ status: string }> {
  return request("GET", `/v1/runcase/terminate_suite?suite_id=${suiteId}`);
}

// Resolve a suite's Jenkins build console URL (looks up build_number via QAHub).
export function getSuiteBuildUrl(
  suiteId: number
): Promise<{ build_number: number; url: string }> {
  return request("GET", `/v1/runcase/suite_build_url?suite_id=${suiteId}`);
}

// ---------- Roku Test ----------
export interface RokuTestRunResult {
  message: string;
  command: string;
  log_file: string;
  pid: number;
}

export function runRokuTest(
  device: string,
  automationId: string,
  testrailCaseId: string,
  repeat = 0
): Promise<RokuTestRunResult> {
  const qs =
    `?device=${encodeURIComponent(device)}` +
    `&automated_test_id=${encodeURIComponent(automationId)}` +
    `&testrail_case_id=${encodeURIComponent(testrailCaseId)}` +
    `&repeat=${repeat}`;
  return request("POST", `/v1/rokutest/run${qs}`);
}

export function getRokuTestStatus(
  pid: number
): Promise<{ pid: number; status: string; command?: string }> {
  return request("GET", `/v1/rokutest/status/${pid}`);
}

export interface RokuTestLog {
  name: string;
  state: "running" | "completed";
  mtime: number;
  result: "Pass" | "Fail" | "Skipped" | "Blocked" | "Unknown";
}

export async function listRokuTestLogs(): Promise<RokuTestLog[]> {
  const data = await request<{ logs: RokuTestLog[] }>("GET", "/v1/rokutest/log/list");
  return data.logs ?? [];
}

export async function viewRokuTestLog(logFile: string): Promise<string> {
  const data = await request<{ log: string }>(
    "GET",
    `/v1/rokutest/log/view/${encodeURIComponent(logFile)}`
  );
  return data.log || "";
}

export function deleteRokuTestLog(logFile: string): Promise<{ message: string }> {
  return request("GET", `/v1/rokutest/log/delete/${encodeURIComponent(logFile)}`);
}

// Backend returns an absolute log_file path; the view endpoint wants the basename.
export const basename = (p: string) => p.split("/").pop() || p;

// ---------- Branch (automated_tests git) ----------
export async function listBranches(): Promise<string[]> {
  const data = await request<{ automated_tests_branches: string[] }>(
    "GET",
    "/v1/branch/automated_tests/list"
  );
  return data.automated_tests_branches ?? [];
}

export async function getCurrentBranch(): Promise<string> {
  const data = await request<{ automated_tests_branch: string }>(
    "GET",
    "/v1/branch/automated_tests/current"
  );
  return data.automated_tests_branch || "";
}

export function checkoutBranch(branchName: string): Promise<{ checkout_result: string }> {
  return request("POST", "/v1/branch/automated_tests/checkout", { branch_name: branchName });
}

// ---------- TestRail plans ----------
export interface TestRailPlan {
  id: number;
  name: string;
}

export async function listTestRailPlans(): Promise<TestRailPlan[]> {
  const data = await request<{ plans: TestRailPlan[] }>("GET", "/v1/testrail/plan/list");
  return data.plans ?? [];
}

export function addTestRailPlan(plan: TestRailPlan): Promise<{ success: boolean }> {
  return request("POST", "/v1/testrail/plan/add", plan);
}

export function deleteTestRailPlan(planId: number): Promise<{ success: boolean }> {
  return request("DELETE", `/v1/testrail/plan/delete?plan_id=${planId}`);
}

export interface TestRailCase {
  run_id: number;
  test_id: number;
  case_id: number;
  title: string | null;
  automation_id: string | null;
  link: string;
}

export interface TestRailCaseList {
  plan: string;
  status: string;
  count: number;
  cases: TestRailCase[];
}

// Uses the display label (e.g. "For Review", "Retest"); backend resolves the id.
// sync=true forces a fresh fetch from TestRail (bypasses/refreshes the cache).
export function listTestRailPlanCases(
  planId: number,
  status = "Failed",
  sync = false
): Promise<TestRailCaseList> {
  const qs = `?plan=${planId}&status=${encodeURIComponent(status)}&sync=${sync}`;
  return request("GET", `/v1/testrail/plan/case/list${qs}`);
}

// Plans/statuses that already have a cached testrail_data file, grouped as
// { "<plan>": { "<status>": "<plan>_<status>.json" } }.
export async function listAvailableTestRailData(): Promise<
  Record<string, Record<string, string>>
> {
  const data = await request<{ plans: Record<string, Record<string, string>> }>(
    "GET",
    "/v1/testrail/testrail_data/available"
  );
  return data.plans ?? {};
}

// Generate a profile from a testrail_data file (<plan>_<status>.json).
export function generateProfileWithTestrailData(
  plan: string,
  device: string,
  testrailDataFile: string
): Promise<{ message: string }> {
  const qs =
    `?plan=${encodeURIComponent(plan)}` +
    `&device=${encodeURIComponent(device)}` +
    `&testrail_data_file=${encodeURIComponent(testrailDataFile)}`;
  return request("GET", `/v1/profile/generate_with_testrail_data${qs}`);
}

export interface TestRailStatus {
  id: number;
  name: string;
  label: string;
}

// Instance-specific status list (id + display label), fetched live from TestRail.
export async function listTestRailStatuses(): Promise<TestRailStatus[]> {
  const data = await request<{ statuses: TestRailStatus[] }>("GET", "/v1/testrail/status/list");
  return data.statuses ?? [];
}

// ---------- Agent (AI) ----------
export interface AgentInfo {
  model: string;
  base_url: string;
  key_alias: string;
  max_tokens: number;
  temperature: number;
}

export function getAgentInfo(): Promise<AgentInfo> {
  return request("GET", "/v1/agent/info");
}

export function switchAgent(patch: {
  model?: string;
  max_tokens?: number;
  temperature?: number;
}): Promise<{ message: string; agent: AgentInfo }> {
  return request("POST", "/v1/agent/switch", patch);
}

export interface AgentModel {
  name: string;
  description: string;
  model: string;
  max_tokens: number;
  temperature: number;
}

export function listAgentModels(): Promise<AgentModel[]> {
  return request("GET", "/v1/agent/models");
}

export interface AgentChatResult {
  response: string;
  prompt: string;
  model: string;
  response_time: number;
}

export function agentChat(
  prompt: string,
  useInternal = true,
  sources?: string[],
  sessionId?: string
): Promise<AgentChatResult> {
  return request("POST", "/v1/agent/chat", {
    prompt,
    use_internal: useInternal,
    sources,
    session_id: sessionId,
  });
}

// Analyze arbitrary text (e.g. a log file). The backend wraps the prompt in an
// analysis instruction and returns a markdown summary in the requested locale
// (zh-CN default, or en-US).
export function agentAnalyze(
  content: string,
  locale: "zh-CN" | "en-US" = "zh-CN",
  useInternal = false,
  caseId?: string,
  deviceId?: string,
  caseTestResult?: string,
  testrailCaseId?: string,
  profileName?: string
): Promise<AgentChatResult> {
  const qs =
    `?locale=${encodeURIComponent(locale)}` +
    (caseId ? `&case_id=${encodeURIComponent(caseId)}` : "") +
    (deviceId ? `&device_id=${encodeURIComponent(deviceId)}` : "") +
    (caseTestResult ? `&case_test_result=${encodeURIComponent(caseTestResult)}` : "") +
    (testrailCaseId ? `&testrail_case_id=${encodeURIComponent(testrailCaseId)}` : "") +
    (profileName ? `&profile_name=${encodeURIComponent(profileName)}` : "");
  return request("POST", `/v1/agent/analyze${qs}`, {
    prompt: content,
    use_internal: useInternal,
  });
}

// ---------- Analyze History ----------
export interface AnalyzeHistoryItem {
  name: string;
  testrail_case_id: string;
  profile: string;
  case_id: string;
  device_id: string;
  result: string;
  locale: string;
  datetime: string;
  date: string;
}

export async function listAnalyzeHistory(filters?: {
  case_id?: string;
  profile?: string;
  device_id?: string;
  result?: string;
  date?: string;
}): Promise<AnalyzeHistoryItem[]> {
  const p = new URLSearchParams();
  if (filters?.case_id) p.set("case_id", filters.case_id);
  if (filters?.profile) p.set("profile", filters.profile);
  if (filters?.device_id) p.set("device_id", filters.device_id);
  if (filters?.result) p.set("result", filters.result);
  if (filters?.date) p.set("date", filters.date);
  const qs = p.toString() ? `?${p.toString()}` : "";
  const data = await request<{ items: AnalyzeHistoryItem[] }>(
    "GET",
    `/v1/analyze_history/list${qs}`
  );
  return data.items ?? [];
}

export async function getAnalyzeHistory(name: string): Promise<string> {
  const data = await request<{ name: string; content: string }>(
    "GET",
    `/v1/analyze_history/view?name=${encodeURIComponent(name)}`
  );
  return data.content;
}

export function deleteAnalyzeHistory(name: string): Promise<{ message: string }> {
  return request("DELETE", `/v1/analyze_history/delete?name=${encodeURIComponent(name)}`);
}

// ---------- Chat sessions ----------
export interface SessionSummary {
  id: string;
  title: string;
  updated: number;
  count: number;
}

export interface SessionMessage {
  role: "user" | "assistant";
  content: string;
  ts: number;
}

export interface SessionDetail {
  id: string;
  title: string;
  created: number;
  updated: number;
  messages: SessionMessage[];
}

export async function listSessions(): Promise<SessionSummary[]> {
  const data = await request<{ sessions: SessionSummary[] }>(
    "GET",
    "/v1/session/list"
  );
  return data.sessions ?? [];
}

export function getSession(id: string): Promise<SessionDetail> {
  return request("GET", `/v1/session/${encodeURIComponent(id)}`);
}

export function createSession(): Promise<SessionDetail> {
  return request("POST", "/v1/session/create");
}

export function deleteSession(id: string): Promise<{ message: string }> {
  return request("DELETE", `/v1/session/delete/${encodeURIComponent(id)}`);
}

export interface AgentSearchResult {
  document_id?: string;
  chunk_id?: number;
  content?: string;
  [k: string]: unknown;
}

export interface AgentSearchResponse {
  query: string;
  sources: string[] | null;
  count: number;
  results: AgentSearchResult[];
}

export function agentSearch(
  query: string,
  sources?: string[],
  limit = 10
): Promise<AgentSearchResponse> {
  return request("POST", "/v1/agent/search", { query, sources, limit });
}

// ---------- Skill ----------
// Backend list returns filenames WITH the .md suffix; the item APIs
// (view/add/delete) take the name WITHOUT .md. Strip it here.
const stripMd = (f: string) => f.replace(/\.md$/i, "");

export async function listSkills(): Promise<string[]> {
  const data = await request<{ skills: string[] }>("GET", "/v1/skill/list");
  return (data.skills ?? []).map(stripMd);
}

export async function getSkill(name: string): Promise<string> {
  const data = await request<{ skill: string }>("GET", `/v1/skill/${name}`);
  return data.skill;
}

export function addSkill(
  name: string,
  skill: string
): Promise<{ message: string }> {
  return request("POST", `/v1/skill/add/${name}`, { skill });
}

export function updateSkill(
  name: string,
  skill: string
): Promise<{ message: string }> {
  return request("PUT", `/v1/skill/update/${name}`, { skill });
}

export function deleteSkill(name: string): Promise<{ message: string }> {
  return request("DELETE", `/v1/skill/delete/${name}`);
}

// Direct download URL for the whole skill_data dir as a .zip (GET endpoint sets
// Content-Disposition, so navigating to it triggers a browser download).
export function exportSkillsUrl(): string {
  return `${API_BASE}/v1/skill/export/all`;
}

// ---------- Reference (Ref / Docs) ----------
export type RefKind = "ref" | "docs";

export interface RefItem {
  index: number;
  name: string;
  category: string;
  url: string;
}

export interface ReferenceList {
  ref: RefItem[];
  ref_categories: string[];
  docs: RefItem[];
  docs_categories: string[];
}

export function listReference(): Promise<ReferenceList> {
  return request("GET", "/v1/reference/list");
}

export function addReference(
  kind: RefKind,
  item: { name: string; category: string; url: string }
): Promise<{ message: string }> {
  return request("POST", "/v1/reference/add", { kind, ...item });
}

export function updateReference(
  kind: RefKind,
  index: number,
  item: { name: string; category: string; url: string }
): Promise<{ message: string }> {
  return request("PUT", "/v1/reference/update", { kind, index, ...item });
}

export function deleteReference(
  kind: RefKind,
  index: number
): Promise<{ message: string }> {
  return request(
    "DELETE",
    `/v1/reference/delete?kind=${encodeURIComponent(kind)}&index=${index}`
  );
}

export function uploadDoc(item: {
  name: string;
  category: string;
  content: string;
}): Promise<{ message: string }> {
  return request("POST", "/v1/reference/doc/upload", item);
}

export async function getDocContent(name: string): Promise<string> {
  const data = await request<{ name: string; content: string }>(
    "GET",
    `/v1/reference/doc/content?name=${encodeURIComponent(name)}`
  );
  return data.content;
}

// ---------- File Transfer ----------
export interface FileTreeNode {
  name: string;
  path: string; // relative to the root
  type: "dir" | "file";
  size?: number;
  children?: FileTreeNode[];
}

export interface FileTransferConfig {
  root: string;
  http_port: number;
}

export interface HttpServerStatus {
  running: boolean;
  pid?: number;
  port?: number;
  dir?: string;
}

export function getFileTransferConfig(): Promise<FileTransferConfig> {
  return request("GET", "/v1/file_transfer/config");
}

export function updateFileTransferConfig(body: {
  root?: string;
  http_port?: number;
}): Promise<{ message: string } & FileTransferConfig> {
  return request("PUT", "/v1/file_transfer/config", body);
}

export async function getFileTree(): Promise<{ root: string; tree: FileTreeNode[] }> {
  return request("GET", "/v1/file_transfer/tree");
}

// Upload a file as base64 JSON (the backend has no multipart dep). Uses XHR so
// the caller gets real upload progress via onProgress(0..100).
export function uploadFileTransfer(
  body: { dir: string; name: string; content_base64: string },
  onProgress?: (percent: number) => void
): Promise<{ message: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/v1/file_transfer/upload`);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.upload.onprogress = (e) => {
      if (onProgress && e.lengthComputable) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          resolve({ message: "Uploaded" });
        }
      } else {
        let detail = `${xhr.status} ${xhr.statusText}`;
        try {
          const err = JSON.parse(xhr.responseText);
          if (err?.detail) detail = err.detail;
        } catch {
          /* ignore */
        }
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(JSON.stringify(body));
  });
}

export function deleteFileTransferFile(path: string): Promise<{ message: string }> {
  return request("DELETE", `/v1/file_transfer/file?path=${encodeURIComponent(path)}`);
}

export function makeFileTransferDir(path: string): Promise<{ message: string }> {
  return request("POST", "/v1/file_transfer/mkdir", { path });
}

export function deleteFileTransferDir(path: string): Promise<{ message: string }> {
  return request("DELETE", `/v1/file_transfer/dir?path=${encodeURIComponent(path)}`);
}

export function getHttpServerStatus(): Promise<HttpServerStatus> {
  return request("GET", "/v1/file_transfer/http/status");
}

export function startHttpServer(): Promise<{ message: string; pid: number; port: number }> {
  return request("POST", "/v1/file_transfer/http/start");
}

export function stopHttpServer(): Promise<{ message: string }> {
  return request("POST", "/v1/file_transfer/http/stop");
}

export interface ScpStatus {
  status: string;
  percent: number;
  message: string;
  done: boolean;
  ok: boolean;
}

// Start a background scp upload; returns a job_id to poll for progress.
export function startScpUpload(body: {
  rel_path: string;
  is_dir: boolean;
  user: string;
  host: string;
  remote_dir: string;
  password: string;
}): Promise<{ job_id: string }> {
  return request("POST", "/v1/file_transfer/scp/start", body);
}

export function getScpStatus(jobId: string): Promise<ScpStatus> {
  return request("GET", `/v1/file_transfer/scp/status/${encodeURIComponent(jobId)}`);
}

export interface ScpServer {
  server: string;
  upload_dir: string;
  username: string;
}

export async function listScpServers(): Promise<ScpServer[]> {
  const data = await request<{ servers: ScpServer[] }>(
    "GET",
    "/v1/file_transfer/scp/servers"
  );
  return data.servers ?? [];
}

export function deleteScpServer(entry: ScpServer): Promise<{ message: string }> {
  const p = new URLSearchParams({
    server: entry.server,
    username: entry.username,
    upload_dir: entry.upload_dir,
  });
  return request("DELETE", `/v1/file_transfer/scp/servers?${p.toString()}`);
}

// ---------- Run Script (cmd) ----------
export interface CmdTreeNode {
  name: string;
  path: string;
  type: "dir" | "file";
  size?: number;
  children?: CmdTreeNode[];
}

export interface CmdRunResult {
  cmdline: string;
  exit_code: number;
  timed_out: boolean;
  elapsed: number;
  stdout: string;
  stderr: string;
  cwd?: string;
}

export interface CmdCacheEntry {
  cmdline: string;
  exit_code: number;
  at: string;
}

export async function getCmdTree(): Promise<{ root: string; tree: CmdTreeNode[] }> {
  return request("GET", "/v1/cmd/tree");
}

export async function getCmdFile(path: string): Promise<string> {
  const data = await request<{ path: string; content: string }>(
    "GET",
    `/v1/cmd/file?path=${encodeURIComponent(path)}`
  );
  return data.content;
}

export function saveCmdFile(body: {
  dir: string;
  name: string;
  content: string;
}): Promise<{ message: string }> {
  return request("POST", "/v1/cmd/file", body);
}

export function uploadCmdFile(body: {
  dir: string;
  name: string;
  content_base64: string;
}): Promise<{ message: string }> {
  return request("POST", "/v1/cmd/upload", body);
}

export function deleteCmdFile(path: string): Promise<{ message: string }> {
  return request("DELETE", `/v1/cmd/file?path=${encodeURIComponent(path)}`);
}

export function makeCmdDir(path: string): Promise<{ message: string }> {
  return request("POST", "/v1/cmd/mkdir", { path });
}

export function deleteCmdDir(path: string): Promise<{ message: string }> {
  return request("DELETE", `/v1/cmd/dir?path=${encodeURIComponent(path)}`);
}

export function runCmd(
  cmdline: string,
  password?: string,
  cwd?: string
): Promise<CmdRunResult> {
  return request("POST", "/v1/cmd/run", { cmdline, password, cwd });
}

export async function listCmdCache(): Promise<CmdCacheEntry[]> {
  const data = await request<{ cache: CmdCacheEntry[] }>("GET", "/v1/cmd/cache");
  return data.cache ?? [];
}

export function deleteCmdCache(cmdline: string): Promise<{ message: string }> {
  const p = new URLSearchParams({ cmdline });
  return request("DELETE", `/v1/cmd/cache?${p.toString()}`);
}

// ---------- Interactive SSH sessions ----------
export function sshStart(body: {
  host: string;
  user: string;
  password?: string;
}): Promise<{ session_id: string; label: string }> {
  return request("POST", "/v1/cmd/ssh/start", body);
}

export function sshInput(session_id: string, data: string): Promise<{ ok: boolean }> {
  return request("POST", "/v1/cmd/ssh/input", { session_id, data });
}

export function sshOutput(
  session_id: string,
  since: number
): Promise<{ data: string; offset: number; alive: boolean }> {
  const p = new URLSearchParams({ session_id, since: String(since) });
  return request("GET", `/v1/cmd/ssh/output?${p.toString()}`);
}

export function sshStop(session_id: string): Promise<{ message: string }> {
  const p = new URLSearchParams({ session_id });
  return request("POST", `/v1/cmd/ssh/stop?${p.toString()}`);
}
