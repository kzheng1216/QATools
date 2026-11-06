/**
 * Profile data model: types, backend-mirrored defaults and JSON helpers.
 *
 * Kept separate from the editor component on purpose: a file that exports both
 * a React component and plain helpers breaks React Fast Refresh ("export is
 * incompatible"), which forces a full reload on every edit and can leave the
 * browser running stale code.
 *
 * All defaults mirror 4_runcase/common/profile_parse.py and
 * launch_qahub_testcase.py, so a profile built here behaves exactly like a
 * hand-written one.
 */

export const CASE_TYPES = ["BDD", "UT", "NEW"] as const;
export const EXEC_MODES = ["SERIAL", "PARALLEL"] as const;

export interface TaskConfig {
  case_type: string;
  case_id: string;
  testrail_case_id?: string | number;
  device: string;
  testrail_plan_id?: number;
  repeat?: number;
  automation_test_branch?: string;
  roku_automation_branch?: string;
}

export interface ProfileTask {
  config: TaskConfig;
  timeout?: number;
}

export interface ProfileData {
  name?: string;
  description?: string;
  tasks?: ProfileTask[];
  /** Profile-level mode: how the tasks run relative to each other. */
  execution_mode?: string;
}

// Per-task defaults, from profile_parse.py's `task_data.get(...)` fallbacks.
// NOTE the per-task `execution_mode`, `stop_if_success` and
// `print_console_message` are deliberately not managed here: profiles built by
// this UI leave them out entirely and let profile_parse.py apply its own
// defaults at run time. The profile-level `execution_mode` is still kept.
export const TASK_DEFAULTS: Required<Pick<ProfileTask, "timeout">> = {
  timeout: 36000,
};

// Task keys this UI no longer supports; stripped from anything it saves.
export const DROPPED_TASK_KEYS = [
  "execution_mode",
  "stop_if_success",
  "print_console_message",
] as const;

// Task-config keys this UI no longer supports; stripped from anything it saves.
export const DROPPED_CONFIG_KEYS = ["test_source"] as const;

// Per-config defaults, from profile_parse.py's `config_data.get(...)` fallbacks
// (testrail_plan_id uses PlanId.NO_PLAN == 0).
export const CONFIG_DEFAULTS: Required<
  Pick<
    TaskConfig,
    | "testrail_case_id"
    | "testrail_plan_id"
    | "repeat"
    | "automation_test_branch"
    | "roku_automation_branch"
  >
> = {
  testrail_case_id: "",
  testrail_plan_id: 0,
  repeat: 0,
  automation_test_branch: "main",
  roku_automation_branch: "main",
};

/**
 * A fresh task with every optional key written out explicitly.
 *
 * Spelling the defaults out (instead of leaving them to a UI-side `??`
 * fallback) keeps "what the form shows" and "what the file contains" in sync.
 */
export function newTask(): ProfileTask {
  return {
    config: {
      case_type: "BDD",
      case_id: "",
      device: "",
      ...CONFIG_DEFAULTS,
    },
    ...TASK_DEFAULTS,
  };
}

/** A new, empty profile holding one blank task. */
export function newProfile(): ProfileData {
  return {
    name: "",
    description: "",
    tasks: [newTask()],
    execution_mode: "SERIAL",
  };
}

/** Parse editor text into a profile object. Returns null when not usable. */
export function parseProfile(text: string): ProfileData | null {
  try {
    const data = JSON.parse(text);
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    return data as ProfileData;
  } catch {
    return null;
  }
}

/** Serialize with the same 4-space indent the JSON tab uses. */
export function stringifyProfile(data: ProfileData): string {
  return JSON.stringify(data, null, 4);
}

/** The template used for a brand-new profile (JSON tab + guided tab). */
export const PROFILE_TEMPLATE = stringifyProfile(newProfile());

/**
 * Materialize the defaults the form displays into the profile itself.
 *
 * Older profiles (and ones built by earlier versions of the RunPlan generator)
 * omit keys like `timeout`. Without this, the widgets would show a default that
 * was never stored, and saving would silently drop it. Existing values and
 * unknown keys are left untouched -- except the DROPPED_* keys, which are
 * removed so saved profiles never carry them.
 *
 * Returns null when nothing had to change, so callers can skip a redundant
 * state update -- that also keeps this safe to call from an effect.
 */
export function normalizeProfile(profile: ProfileData): ProfileData | null {
  let changed = false;

  const tasks = (profile.tasks ?? []).map((task) => {
    const next: ProfileTask = {
      ...task,
      config: { ...(task.config ?? {}) } as TaskConfig,
    };
    const taskRec = next as unknown as Record<string, unknown>;
    for (const key of DROPPED_TASK_KEYS) {
      if (key in taskRec) {
        delete taskRec[key];
        changed = true;
      }
    }
    for (const [key, fallback] of Object.entries(TASK_DEFAULTS)) {
      if (taskRec[key] === undefined) {
        taskRec[key] = fallback;
        changed = true;
      }
    }
    const cfgRec = next.config as unknown as Record<string, unknown>;
    for (const key of DROPPED_CONFIG_KEYS) {
      if (key in cfgRec) {
        delete cfgRec[key];
        changed = true;
      }
    }
    for (const [key, fallback] of Object.entries(CONFIG_DEFAULTS)) {
      if (cfgRec[key] === undefined) {
        cfgRec[key] = fallback;
        changed = true;
      }
    }
    return next;
  });

  if (profile.execution_mode === undefined) changed = true;
  if (!changed) return null;

  return {
    ...profile,
    execution_mode: profile.execution_mode ?? "SERIAL",
    tasks,
  };
}
