import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Row,
  Space,
  Spin,
  Statistic,
  Tag,
  Tooltip,
  Typography,
  theme,
} from "antd";
import {
  ArrowRightOutlined,
  ReloadOutlined,
  ApiOutlined,
  BarcodeOutlined,
  BookOutlined,
  BulbOutlined,
  CloudServerOutlined,
  DeploymentUnitOutlined,
  DesktopOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  HistoryOutlined,
  LinkOutlined,
  PlayCircleOutlined,
  ProfileOutlined,
  RobotOutlined,
  BranchesOutlined,
  CheckCircleOutlined,
  CheckOutlined,
  CloseOutlined,
  MinusCircleOutlined,
  OrderedListOutlined,
  SoundOutlined,
  SwitcherOutlined,
  SyncOutlined,
  ThunderboltOutlined,
  WarningOutlined,
  WifiOutlined,
} from "@ant-design/icons";
import {
  getDashboardSummary,
  type DashboardCard,
  type DashboardPoint,
  type DashboardRow,
  type DashboardSummary,
} from "../api/client";

const { Text, Title } = Typography;

// Dashboard card keys match the tab keys in config.yml / App.tsx PageKey, so
// the "Open" link can jump straight to the matching tab.
export type DashboardTabKey =
  | "device"
  | "profile"
  | "runcase"
  | "rokutest"
  | "analyzehistory"
  | "testrail"
  | "agent"
  | "reference"
  | "filetransfer"
  | "donuts"
  | "activate";

const CARD_META: {
  key: DashboardTabKey;
  title: string;
  icon: React.ReactNode;
}[] = [
  { key: "device", title: "Device", icon: <DesktopOutlined /> },
  { key: "profile", title: "Profile", icon: <ProfileOutlined /> },
  { key: "runcase", title: "Run Case", icon: <PlayCircleOutlined /> },
  { key: "rokutest", title: "Run Case in local", icon: <ExperimentOutlined /> },
  { key: "analyzehistory", title: "Analyze History", icon: <HistoryOutlined /> },
  { key: "testrail", title: "TestRail Case", icon: <FileTextOutlined /> },
  { key: "agent", title: "Prompt", icon: <RobotOutlined /> },
  { key: "reference", title: "Reference", icon: <BookOutlined /> },
  { key: "filetransfer", title: "File Transfer", icon: <CloudServerOutlined /> },
  { key: "donuts", title: "Donuts", icon: <DeploymentUnitOutlined /> },
  { key: "activate", title: "Activate", icon: <ApiOutlined /> },
];

// ---------- tiny dependency-free charts ----------
// The project has no chart library, so these are small inline flex charts drawn
// from the backend's {name,value} / {date,count} series.
//
// Every ratio / progress bar on this page goes through <RatioBar>, so they all
// share one geometry and one theme-derived palette: change these two constants
// (or the tokens in useChartColors) and the whole Dashboard follows. The bars
// are thin but span the full free width of their row.
const BAR_HEIGHT = 10;
const BAR_RADIUS = 2;

const pointLabel = (p: DashboardPoint) => p.name ?? p.date ?? "";
const pointValue = (p: DashboardPoint) => p.value ?? p.count ?? 0;

/**
 * Theme-derived chart palette. Everything is read from antd's token set (which
 * follows the ConfigProvider algorithm + colorPrimary picked in the header), so
 * switching theme recolors every bar, segment and pie slice automatically.
 */
function useChartColors() {
  const { token } = theme.useToken();
  // Status -> color. Keys are the lower-cased status names the backend
  // flattens onto each row (Pass/Fail/Failed/Blocked/Skipped/Aborted/Unknown).
  const status: Record<string, string> = {
    pass: token.colorSuccess,
    passed: token.colorSuccess,
    fail: token.colorError,
    failed: token.colorError,
    blocked: token.colorWarning,
    skipped: token.colorInfo,
    retest: token.colorInfo,
    broken: token.magenta6,
    for_review: token.cyan6,
    untested: token.colorTextQuaternary,
    aborted: token.colorTextQuaternary,
    unknown: token.purple6,
  };
  return {
    status,
    // Generic categorical palette (pie slices, unknown statuses).
    palette: [
      token.colorSuccess,
      token.colorError,
      token.colorWarning,
      token.colorInfo,
      token.cyan6,
      token.purple6,
    ],
    primary: token.colorPrimary,
    track: token.colorFillSecondary,
    fallback: token.colorTextQuaternary,
    statusColor: (s: string) => status[s] ?? token.colorTextQuaternary,
  };
}

/**
 * The single ratio / progress bar used across the whole Dashboard.
 *
 * `segments` are drawn left-to-right as percentages of the bar's width; pass
 * one segment for a plain progress bar, several for a stacked 100% bar. An
 * empty list renders just the (theme-colored) track, so rows never collapse.
 */
function RatioBar({
  segments,
}: {
  segments: { key: string; pct: number; color: string; tip?: string }[];
}) {
  const { track } = useChartColors();
  return (
    <div
      style={{
        display: "flex",
        height: BAR_HEIGHT,
        borderRadius: BAR_RADIUS,
        background: track,
        overflow: "hidden",
      }}
    >
      {segments.map((s) =>
        s.pct <= 0 ? null : (
          <Tooltip key={s.key} title={s.tip}>
            <div
              style={{
                width: `${s.pct}%`,
                minWidth: 2,
                background: s.color,
                transition: "width .3s",
              }}
            />
          </Tooltip>
        )
      )}
    </div>
  );
}

/**
 * Horizontal ratio bars — the Dashboard's default chart, used for the
 * "items per category" series every card reports as `chart`.
 */
function BarChart({ data }: { data: DashboardPoint[] }) {
  const { primary } = useChartColors();
  const max = Math.max(1, ...data.map(pointValue));
  if (!data.length)
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {data.map((p, i) => {
        const label = pointLabel(p);
        const value = pointValue(p);
        return (
          <div
            key={`${label}-${i}`}
            style={{ display: "flex", alignItems: "center", gap: 8 }}
          >
            <Text
              style={{ width: 92, fontSize: 12, textAlign: "right", opacity: 0.8 }}
              ellipsis={{ tooltip: label }}
            >
              {label}
            </Text>
            <div style={{ flex: 1, minWidth: 0 }}>
              <RatioBar
                segments={[
                  {
                    key: label,
                    pct: (value / max) * 100,
                    color: primary,
                    tip: `${label}: ${value}`,
                  },
                ]}
              />
            </div>
            <Text style={{ width: 34, fontSize: 12 }}>{value}</Text>
          </div>
        );
      })}
    </div>
  );
}

/**
 * One stacked 100% bar: each visible status becomes a segment sized by its
 * ratio, labelled "count (pct%)" in its tooltip. `statuses` fixes the segment
 * order so every row in a card reads the same way.
 */
function StatusBar({
  row,
  statuses,
  total,
}: {
  row: DashboardRow;
  statuses: string[];
  total: number;
}) {
  const { statusColor } = useChartColors();
  if (!total) return <RatioBar segments={[]} />;
  return (
    <RatioBar
      segments={statuses.map((s) => {
        const count = Number(row[s] ?? 0);
        const pct = count ? Number(row[`${s}_pct`] ?? (count / total) * 100) : 0;
        return {
          key: s,
          pct,
          color: statusColor(s),
          tip: `${s}: ${count} (${pct}%)`,
        };
      })}
    />
  );
}

/** Legend for the statuses actually present across a card's rows. */
function StatusLegend({
  statuses,
  totals,
}: {
  statuses: string[];
  totals?: Record<string, number>;
}) {
  const { statusColor } = useChartColors();
  return (
    <Space size={10} wrap style={{ marginTop: 8 }}>
      {statuses.map((s) => (
        <Text key={s} style={{ fontSize: 11, opacity: 0.8 }}>
          <span
            style={{
              display: "inline-block",
              width: 8,
              height: 8,
              borderRadius: 2,
              marginRight: 5,
              background: statusColor(s),
            }}
          />
          {s}
          {totals?.[s] !== undefined ? ` ${totals[s]}` : ""}
        </Text>
      ))}
    </Space>
  );
}

/**
 * Compact one-line-per-row status list — the simple form used by the two Run
 * Case cards: "[icon] label  [pass/fail bar]  N".
 *
 * Only the statuses actually present are drawn, the leading icon says whether
 * the row is clean (all pass), had failures, or only non-pass results, and
 * everything else (sublabel, per-status counts) moves into the row tooltip, so
 * no legend or second text line is needed.
 */
function StatusLines({
  rows,
  statuses,
  label,
  sublabel,
  totalKey,
  passKeys = ["pass", "passed"],
  failKeys = ["fail", "failed"],
}: {
  rows: DashboardRow[];
  statuses: string[];
  label: (r: DashboardRow) => string;
  sublabel?: (r: DashboardRow) => string;
  totalKey: string;
  passKeys?: string[];
  failKeys?: string[];
}) {
  const { statusColor, fallback } = useChartColors();
  // Skip statuses nothing in this card uses, so the bars stay two-tone simple.
  const present = useMemo(
    () => statuses.filter((s) => rows.some((r) => Number(r[s] ?? 0) > 0)),
    [rows, statuses]
  );
  if (!rows.length)
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {rows.map((r, i) => {
        const total = Number(r[totalKey] ?? 0);
        const sum = (keys: string[]) =>
          keys.reduce((s, k) => s + Number(r[k] ?? 0), 0);
        const passed = sum(passKeys);
        const failed = sum(failKeys);
        const pct = total ? Math.round((passed / total) * 100) : 0;
        const tip = [
          label(r),
          sublabel?.(r),
          statuses
            .map((s) => `${s} ${Number(r[s] ?? 0)}`)
            .filter((s) => !s.endsWith(" 0"))
            .join(" · "),          total ? `pass ${pct}% of ${total}` : "",
        ]
          .filter(Boolean)
          .join("\n");
        return (
          <Tooltip key={i} title={<span style={{ whiteSpace: "pre-line" }}>{tip}</span>}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
              <span
                style={{
                  fontSize: 13,
                  flex: "0 0 auto",
                  color: failed
                    ? statusColor("failed")
                    : passed === total && total
                    ? statusColor("pass")
                    : fallback,
                }}
              >
                {failed ? (
                  <WarningOutlined />
                ) : passed === total && total ? (
                  <CheckCircleOutlined />
                ) : (
                  <MinusCircleOutlined />
                )}
              </span>
              <Text style={{ width: 118, minWidth: 118, fontSize: 12 }} ellipsis>
                {label(r)}
              </Text>
              <div style={{ flex: 1, minWidth: 0 }}>
                <StatusBar row={r} statuses={present} total={total} />
              </div>
              <Text style={{ width: 46, fontSize: 12, textAlign: "right" }}>
                {total}
                <Text type="secondary" style={{ fontSize: 10 }}> {pct}%</Text>
              </Text>
            </div>
          </Tooltip>
        );
      })}
    </div>
  );
}

// ---------- card helpers ----------
const num = (card: DashboardCard, key: string) => Number(card?.[key] ?? 0);
const str = (card: DashboardCard, key: string) => String(card?.[key] ?? "");

const humanSize = (bytes: number) => {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`;
};

// Status segment order for the two run cards (must match the backend's
// _REPORT_STATUSES / _RESULT_STATUSES, lower-cased).
const RUNCASE_STATUSES = ["pass", "failed", "blocked", "skipped", "aborted", "unknown"];
const ROKUTEST_STATUSES = ["pass", "fail", "blocked", "skipped"];
// TestRail's own status labels (see the backend's _TESTRAIL_STATUSES).
const TESTRAIL_STATUSES = [
  "passed",
  "failed",
  "blocked",
  "retest",
  "broken",
  "for_review",
  "untested",
];

/** Compact "key: value" stat row shown above each chart. */
function Stats({ items }: { items: { label: string; value: React.ReactNode }[] }) {
  return (
    <Row gutter={[8, 4]}>
      {items.map((it) => (
        <Col key={it.label} span={8}>
          <Statistic
            title={<span style={{ fontSize: 12 }}>{it.label}</span>}
            value={it.value as never}
            valueStyle={{ fontSize: 18 }}
          />
        </Col>
      ))}
    </Row>
  );
}

/** Small "recent items" list under the chart. */
function RecentList({ rows, fields }: { rows?: Record<string, unknown>[]; fields: string[] }) {
  if (!rows?.length) return null;
  return (
    <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 2 }}>
      {rows.map((r, i) => (
        <Text key={i} style={{ fontSize: 12, opacity: 0.75 }} ellipsis>
          {fields
            .map((f) => (r[f] === undefined || r[f] === "" ? null : String(r[f])))
            .filter(Boolean)
            .join(" · ") || "—"}
        </Text>
      ))}
    </div>
  );
}

/**
 * Verdict distribution as a big centered donut: a conic-gradient ring colored
 * by the status palette, the grand total in its hole, and a centered legend
 * below where every verdict shows its count and share.
 *
 * Hovering the ring (or a legend entry) shows the verdict's detail: how many
 * analyses and distinct cases it covers, its locales, the TestRail case ids
 * involved, the newest analysis and the cases that hit it most often.
 *
 * "Fail" and "Failed" are folded into one slice. Used by the Analyze History
 * card, whose only question is "how do the saved analyses split by result".
 */
function ResultPie({
  data,
  detail,
  total: grandTotal,
  cases,
  today,
}: {
  data: DashboardPoint[];
  detail?: Record<string, unknown>[];
  total?: number;
  cases?: number;
  today?: number;
}) {
  const { statusColor } = useChartColors();
  // "Fail" and "Failed" are the same outcome: fold them into one slice, so the
  // donut shows one red wedge even if an older backend still splits them.
  const merged = useMemo(() => {
    const acc = new Map<string, number>();
    for (const p of data) {
      const raw = pointLabel(p);
      const key = /^fail(ed)?$/i.test(raw) ? "Failed" : raw;
      acc.set(key, (acc.get(key) ?? 0) + pointValue(p));
    }
    return [...acc.entries()]
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);
  }, [data]);
  const total = merged.reduce((s, p) => s + p.value, 0);
  if (!total)
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No analyses" />;
  const SIZE = 150;
  // name -> backend detail row, with Fail/Failed detail merged as well.
  const byName = new Map<string, Record<string, unknown>>();
  for (const d of detail ?? []) {
    const raw = String(d.name ?? "");
    const key = (/^fail(ed)?$/i.test(raw) ? "failed" : raw).toLowerCase();
    const prev = byName.get(key);
    if (!prev) {
      byName.set(key, { ...d, name: key === "failed" ? "Failed" : raw });
      continue;
    }
    // Merge the two rows: sum counts, keep the newest stamp, union the lists.
    const list = (k: string, obj: Record<string, unknown>) =>
      Array.isArray(obj[k]) ? (obj[k] as unknown[]) : [];
    byName.set(key, {
      ...prev,
      value: Number(prev.value ?? 0) + Number(d.value ?? 0),
      pct: Number(prev.pct ?? 0) + Number(d.pct ?? 0),
      cases: Number(prev.cases ?? 0) + Number(d.cases ?? 0),
      last:
        String(d.last ?? "") > String(prev.last ?? "")
          ? String(d.last ?? "")
          : String(prev.last ?? ""),
      locales: [...new Set([...list("locales", prev), ...list("locales", d)])],
      testrail_ids: [
        ...new Set([...list("testrail_ids", prev), ...list("testrail_ids", d)]),
      ],
      top_cases: [...list("top_cases", prev), ...list("top_cases", d)]
        .slice(0, 3),
    });
  }
  /** Multi-line tooltip for one verdict. */
  const sliceTip = (label: string, value: number, pct: number) => {
    const d = byName.get(label.toLowerCase());
    const topCases = Array.isArray(d?.top_cases)
      ? (d!.top_cases as Record<string, unknown>[])
      : [];
    const locales = Array.isArray(d?.locales) ? (d!.locales as string[]) : [];
    const trIds = Array.isArray(d?.testrail_ids)
      ? (d!.testrail_ids as string[])
      : [];
    const trTotal = Number(d?.testrail_id_count ?? trIds.length);
    return [
      `${label} — ${value} analysis/analyses (${pct}%)`,
      d?.cases !== undefined ? `${d.cases} distinct case(s)` : "",
      locales.length ? `locales: ${locales.join(", ")}` : "",
      trIds.length
        ? `TestRail ids (${trTotal}): ${trIds.join(", ")}${
            trTotal > trIds.length ? " …" : ""
          }`
        : "",
      d?.last ? `last ${String(d.last).replace("_", " ")}` : "",
      topCases.length
        ? `top: ${topCases.map((c) => `${c.label} x${c.count}`).join(", ")}`
        : "",
    ]
      .filter(Boolean)
      .join("\n");
  };
  let acc = 0;
  const slices = merged.map((p) => {
    const label = p.name;
    const value = p.value;
    const from = (acc / total) * 100;
    acc += value;
    const pct = Math.round((value / total) * 100);
    return {
      label,
      value,
      pct,
      color: statusColor(label.toLowerCase()),
      stop: `${statusColor(label.toLowerCase())} ${from}% ${(acc / total) * 100}%`,
      tip: sliceTip(label, value, pct),
    };
  });
  // Whole-chart summary, shown when hovering the ring itself.
  const ringTip = [
    `${grandTotal ?? total} analyses`,
    cases !== undefined ? `${cases} case(s)` : "",
    today !== undefined ? `${today} today` : "",
    "—",
    ...slices.map((s) => `${s.label}: ${s.value} (${s.pct}%)`),
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 12,
      }}
    >
      {/* ring + the grand total in its hole */}
      <Tooltip title={<span style={{ whiteSpace: "pre-line" }}>{ringTip}</span>}>
        <div style={{ position: "relative", width: SIZE, height: SIZE }}>
          <div
            style={{
              width: SIZE,
              height: SIZE,
              borderRadius: "50%",
              background: `conic-gradient(${slices.map((s) => s.stop).join(",")})`,
              mask: "radial-gradient(circle, transparent 58%, #000 59%)",
              WebkitMask: "radial-gradient(circle, transparent 58%, #000 59%)",
            }}
          />
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Text strong style={{ fontSize: 30, lineHeight: "32px" }}>
              {total}
            </Text>
            <Text type="secondary" style={{ fontSize: 11 }}>
              analyses
            </Text>
          </div>
        </div>
      </Tooltip>
      {/* centered legend: color dot, verdict, count and share */}
      <Space size={[16, 4]} wrap style={{ justifyContent: "center" }}>
        {slices.map((s, i) => (
          <Tooltip
            key={`${s.label}-${i}`}
            title={<span style={{ whiteSpace: "pre-line" }}>{s.tip}</span>}
          >
            <Text style={{ fontSize: 12 }}>
              <span
                style={{
                  display: "inline-block",
                  width: 9,
                  height: 9,
                  borderRadius: "50%",
                  marginRight: 6,
                  background: s.color,
                }}
              />
              {s.label}
              <Text strong style={{ fontSize: 12 }}>
                {" "}
                {s.value}
              </Text>
              <Text type="secondary" style={{ fontSize: 11 }}>
                {" "}
                ({s.pct}%)
              </Text>
            </Text>
          </Tooltip>
        ))}
      </Space>
    </div>
  );
}

// ---------- testrail card: plan tiles (same shape as the Device card) ----------
/**
 * The worst cached plans (up to 8) as icon chips, mirroring the Device card's
 * tile grid: per tile an alert icon, the Failed percentage (what the list is
 * ranked by), the short plan name, and a mini stacked bar (Failed + Blocked
 * over the plan's cases).
 *
 * Two tiles per row, so the long plan names stay readable; the plan id, case
 * total, fetch time and per-status counts stay in the tooltip.
 */
function TestRailPlanGrid({ rows }: { rows?: DashboardRow[] }) {
  const { statusColor, track, fallback } = useChartColors();
  if (!rows?.length)
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No cached plans" />;
  return (
    <Row gutter={[8, 8]}>
      {rows.slice(0, 8).map((r, i) => {
        const cases = Number(r.cases ?? 0);
        const failed = Number(r.failed ?? 0);
        const blocked = Number(r.blocked ?? 0);
        const bad = failed + blocked;
        // Tiles are ranked (by the backend) on the Failed ratio, so that's the
        // headline number; Blocked still shows up in the bar and the tooltip.
        const failPct = Number(r.failed_pct ?? (cases ? (failed / cases) * 100 : 0));
        const badPct = Number(r.bad_pct ?? (cases ? (bad / cases) * 100 : 0));
        const name = String(r.plan_name || r.plan || "");
        // "Athens UK" out of "CTS-Preview-MFG - 239 - Athens UK - 20260918".
        const short = name.split(" - ").slice(-2, -1)[0] || name;
        const tip = [
          name,
          `plan ${r.plan} · ${cases} case(s) · ${r.at ?? ""}`,
          `Failed ${failed} (${failPct}%) · Blocked ${blocked} → ${badPct}%`,
          TESTRAIL_STATUSES.map((s) => `${s} ${Number(r[s] ?? 0)}`)
            .filter((s) => !s.endsWith(" 0"))
            .join(" · "),
        ]
          .filter(Boolean)
          .join("\n");
        return (
          <Col key={`${r.plan}-${i}`} span={12}>
            <Tooltip title={<span style={{ whiteSpace: "pre-line" }}>{tip}</span>}>
              <div
                style={{
                  border: `1px solid ${track}`,
                  borderRadius: 6,
                  padding: "6px 8px",
                  opacity: bad ? 1 : 0.45,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span
                    style={{
                      fontSize: 15,
                      color: failed ? statusColor("failed") : fallback,
                    }}
                  >
                    {failed ? <WarningOutlined /> : <CheckCircleOutlined />}
                  </span>
                  <Text strong style={{ fontSize: 14 }}>
                    {Math.round(failPct)}%
                  </Text>
                  <Text type="secondary" style={{ fontSize: 11 }} ellipsis>
                    {failed}/{cases}
                  </Text>
                </div>
                <div style={{ marginTop: 4 }}>
                  <RatioBar
                    segments={[
                      {
                        key: "failed",
                        pct: cases ? (failed / cases) * 100 : 0,
                        color: statusColor("failed"),
                        tip: `Failed ${failed}/${cases}`,
                      },
                      {
                        key: "blocked",
                        pct: cases ? (blocked / cases) * 100 : 0,
                        color: statusColor("blocked"),
                        tip: `Blocked ${blocked}/${cases}`,
                      },
                    ]}
                  />
                </div>
                <Text style={{ fontSize: 10, opacity: 0.75 }} ellipsis>
                  {short}
                </Text>
              </div>
            </Tooltip>
          </Col>
        );
      })}
    </Row>
  );
}

// ---------- reference / activate cards: Device-style icon tiles ----------
/**
 * Reference categories grouped by item type: a "Links" block and a "Docs"
 * block, each a Device-style tile grid (icon + count + category name + mini
 * ratio bar), 3 tiles per row and at most 3 rows per block.
 *
 * Splitting by type answers "which categories hold links vs. documents"
 * directly, instead of mixing both into one anonymous count.
 */
function ReferenceCategoryGrid({
  linkRows,
  docRows,
}: {
  linkRows?: Record<string, unknown>[];
  docRows?: Record<string, unknown>[];
}) {
  const { primary, palette, track } = useChartColors();
  const blocks = [
    {
      key: "links",
      title: "Links",
      icon: <LinkOutlined />,
      color: primary,
      rows: linkRows ?? [],
    },
    {
      key: "docs",
      title: "Docs",
      icon: <FileTextOutlined />,
      color: palette[4],
      rows: docRows ?? [],
    },
  ].filter((b) => b.rows.length);
  if (!blocks.length)
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No categories" />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {blocks.map((block) => {
        const tiles = block.rows.slice(0, 9); // 3 columns x 3 rows
        const max = Math.max(1, ...tiles.map((r) => Number(r.value ?? 0)));
        const sum = tiles.reduce((s, r) => s + Number(r.value ?? 0), 0);
        return (
          <div key={block.key}>
            {/* block header: the item type and its total */}
            <Text style={{ fontSize: 11, opacity: 0.75 }}>
              <span style={{ color: block.color, marginRight: 5 }}>{block.icon}</span>
              {block.title}
              <Text type="secondary" style={{ fontSize: 11 }}>
                {" "}
                {sum}
              </Text>
            </Text>
            <Row gutter={[8, 8]} style={{ marginTop: 5 }}>
              {tiles.map((r, i) => {
                const name = String(r.name ?? "");
                const value = Number(r.value ?? 0);
                return (
                  <Col key={`${block.key}-${name}-${i}`} span={8}>
                    <Tooltip
                      title={`${block.title} · ${name}: ${value} item(s)`}
                    >
                      <div
                        style={{
                          border: `1px solid ${track}`,
                          borderRadius: 6,
                          padding: "6px 8px",
                          opacity: value ? 1 : 0.45,
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={{ fontSize: 15, color: block.color }}>
                            {block.icon}
                          </span>
                          <Text strong style={{ fontSize: 14 }}>
                            {value}
                          </Text>
                          <Text type="secondary" style={{ fontSize: 11 }} ellipsis>
                            {name}
                          </Text>
                        </div>
                        <div style={{ marginTop: 4 }}>
                          <RatioBar
                            segments={[
                              {
                                key: name,
                                pct: (value / max) * 100,
                                color: block.color,
                              },
                            ]}
                          />
                        </div>
                      </div>
                    </Tooltip>
                  </Col>
                );
              })}
            </Row>
          </div>
        );
      })}
    </div>
  );
}

// Conversion mode -> highlight color key, so "connected" and "unconnected"
// jobs are told apart at a glance in the Activate tiles.
const ACTIVATE_MODE_COLOR: Record<string, "cyan" | "purple"> = {
  connected: "cyan",
  unconnected: "purple",
};

/**
 * Activate jobs as a square-tile grid (3 per row): each tile is a centered
 * status icon over the device name and the conversion mode.
 *
 * Icon colors: blue while the job runs, green when it finished successfully,
 * red when the log shows a failure (grey for an undecidable log). The job id,
 * start time and log file stay in the tooltip.
 */
function ActivateJobGrid({ rows }: { rows?: Record<string, unknown>[] }) {
  const { token } = theme.useToken();
  if (!rows?.length)
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No jobs" />;
  return (
    <Row gutter={[8, 8]}>
      {rows.slice(0, 6).map((r, i) => {
        const device = String(r.device ?? "") || "—";
        const mode = String(r.mode ?? "");
        const started = String(r.started ?? "");
        const running = Boolean(r.running);
        // Backend sends "" while running, else Success / Failed / Unknown. An
        // older backend sends no `result` at all, so anything not explicitly
        // failed counts as a finished (green) job instead of a grey unknown.
        const result = String(r.result ?? "").toLowerCase();
        const failed = !running && result === "failed";
        // running -> blue, failed -> red, finished -> green.
        const color = running
          ? token.colorInfo // blue
          : failed
          ? token.colorError // red
          : token.colorSuccess; // green
        const state = running ? "running" : result || "finished";
        const modeKey = ACTIVATE_MODE_COLOR[mode.toLowerCase()];
        const modeColor =
          modeKey === "cyan"
            ? token.cyan6
            : modeKey === "purple"
            ? token.purple6
            : token.colorTextSecondary;
        const tip = [
          device,
          [mode && `mode ${mode}`, state].filter(Boolean).join(" · "),
          started && `started ${started}`,
          r.id ? `id ${String(r.id)}` : "",
          r.log_file ? String(r.log_file) : "",
        ]
          .filter(Boolean)
          .join("\n");
        return (
          <Col key={`${r.id ?? device}-${i}`} span={8}>
            <Tooltip title={<span style={{ whiteSpace: "pre-line" }}>{tip}</span>}>
              <div
                style={{
                  border: `1px solid ${color}`,
                  borderRadius: 6,
                  padding: "8px 6px",
                  textAlign: "center",
                  // Light tint of the state color, so the whole tile reads as
                  // blue (running) / green (finished) / red (failed).
                  background: `${color}14`,
                }}
              >
                {/* centered status icon = the tile's focal point, drawn as a
                    filled circular badge in the state color so it pops */}
                <div
                  style={{
                    width: 18,
                    height: 18,
                    margin: "0 auto 3px",
                    borderRadius: "50%",
                    background: color,
                    color: token.colorBgContainer,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 10,
                    boxShadow: `0 0 0 2px ${color}33`,
                  }}
                >
                  {running ? (
                    <SyncOutlined spin />
                  ) : failed ? (
                    <CloseOutlined />
                  ) : (
                    <CheckOutlined />
                  )}
                </div>
                <Text
                  strong
                  style={{ fontSize: 11, display: "block", lineHeight: "15px" }}
                  ellipsis
                >
                  {device}
                </Text>
                {/* mode highlighted on its own: cyan connected / purple unconnected */}
                <Text
                  style={{
                    fontSize: 10,
                    display: "block",
                    lineHeight: "13px",
                    color: modeColor,
                    fontWeight: 500,
                  }}
                  ellipsis
                >
                  {mode || "—"}
                </Text>
              </div>
            </Tooltip>
          </Col>
        );
      })}
    </Row>
  );
}

// ---------- device card: icon-based presentation ----------
// Sub-config name (as sent by the backend's device chart) -> icon + short tip.
// Shown as icon chips instead of anonymous bars, so a glance tells which
// capabilities (power switch, QA Bot, HDMI sources, ...) the lab devices have.
const DEVICE_FEATURE_META: Record<
  string,
  { icon: React.ReactNode; tip: string }
> = {
  "QA Bot": { icon: <RobotOutlined />, tip: "QA Bot (IR / button robot)" },
  Maxwell: { icon: <BulbOutlined />, tip: "Maxwell light / sensor box" },
  Power: { icon: <ThunderboltOutlined />, tip: "Power switch / PDU outlet" },
  AVR: { icon: <SoundOutlined />, tip: "AVR / audio receiver" },
  HDMI: { icon: <SwitcherOutlined />, tip: "HDMI input sources" },
  STB: { icon: <DesktopOutlined />, tip: "Roku STB on an HDMI input" },
};

/**
 * Device capabilities as icon chips: one tile per sub-config with its icon, the
 * number of devices that have it, and a mini ratio bar against the device
 * total. Replaces the generic bar chart for the Device card.
 */
function DeviceFeatureGrid({
  data,
  total,
}: {
  data: DashboardPoint[];
  total: number;
}) {
  const { primary, track } = useChartColors();
  if (!data.length)
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" />;
  const denom = Math.max(1, total || Math.max(...data.map(pointValue)));
  return (
    <Row gutter={[8, 8]}>
      {data.map((p, i) => {
        const label = pointLabel(p);
        const value = pointValue(p);
        const meta = DEVICE_FEATURE_META[label];
        const pct = Math.round((value / denom) * 100);
        return (
          <Col key={`${label}-${i}`} span={8}>
            <Tooltip title={`${meta?.tip ?? label}: ${value}/${denom} device(s)`}>
              <div
                style={{
                  border: `1px solid ${track}`,
                  borderRadius: 6,
                  padding: "6px 8px",
                  opacity: value ? 1 : 0.45,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 15, color: value ? primary : undefined }}>
                    {meta?.icon ?? <ApiOutlined />}
                  </span>
                  <Text strong style={{ fontSize: 14 }}>
                    {value}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 11 }} ellipsis>
                    {label}
                  </Text>
                </div>
                <div style={{ marginTop: 4 }}>
                  <RatioBar
                    segments={[{ key: label, pct, color: primary }]}
                  />
                </div>
              </div>
            </Tooltip>
          </Col>
        );
      })}
    </Row>
  );
}

/**
 * Recent devices: "NAME · ip · serial", each field behind its own icon so the
 * three identifiers are told apart at a glance (and the SN is visible without
 * opening the Device tab).
 */
function DeviceRecentList({ rows }: { rows?: Record<string, unknown>[] }) {
  if (!rows?.length) return null;
  return (
    <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 4 }}>
      {rows.map((r, i) => {
        const name = String(r.name ?? "");
        const ip = String(r.ip_address ?? "");
        const sn = String(r.serial_number ?? "");
        const deviceId = String(r.device_id ?? "");
        return (
          <div
            key={i}
            style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}
          >
            <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: name }}>
              <DesktopOutlined style={{ marginRight: 5, opacity: 0.65 }} />
              {name}
            </Text>
            {ip && (
              <Tooltip title={`IP ${ip}`}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  <WifiOutlined style={{ marginRight: 4 }} />
                  {ip}
                </Text>
              </Tooltip>
            )}
            {sn && (
              <Tooltip title={`Serial number ${sn}${deviceId ? ` · device id ${deviceId}` : ""}`}>
                <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                  <BarcodeOutlined style={{ marginRight: 4 }} />
                  {sn}
                </Text>
              </Tooltip>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------- profile card: badge-list presentation ----------
// Execution mode -> icon. SERIAL runs tasks one after another, PARALLEL fans
// them out, so the icons mirror that shape.
const PROFILE_MODE_META: Record<
  string,
  { icon: React.ReactNode; label: string }
> = {
  SERIAL: { icon: <OrderedListOutlined />, label: "serial" },
  PARALLEL: { icon: <BranchesOutlined />, label: "parallel" },
};

// Case type -> bar color kind (BDD feature files, unit tests, anything else).
const CASE_TYPE_BAR: Record<string, "primary" | "info" | "muted"> = {
  BDD: "primary",
  UT: "info",
  PYTHON: "info",
};

/**
 * Profile card chart: one compact line per run profile —
 * "[mode icon] name  [task bar]  N".
 *
 * The leading icon says serial vs. parallel, the bar is split by case type and
 * scaled against the biggest profile, and everything else (case-type counts,
 * devices, description) lives in the row's tooltip, so the card stays quiet.
 * Deliberately a different shape from the Device card's icon-chip grid.
 */
function ProfileBadgeList({ rows }: { rows?: Record<string, unknown>[] }) {
  const { primary, palette, fallback } = useChartColors();
  if (!rows?.length)
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No profiles" />;
  const max = Math.max(1, ...rows.map((r) => Number(r.tasks ?? 0)));
  const barColor = (t: string) => {
    const kind = CASE_TYPE_BAR[t] ?? "muted";
    return kind === "primary" ? primary : kind === "info" ? palette[4] : fallback;
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
      {rows.map((r, i) => {
        const name = String(r.name ?? "");
        const tasks = Number(r.tasks ?? 0);
        const mode = String(r.execution_mode ?? "SERIAL").toUpperCase();
        const modeMeta = PROFILE_MODE_META[mode] ?? {
          icon: <ApiOutlined />,
          label: mode.toLowerCase(),
        };
        const devices = Array.isArray(r.devices) ? (r.devices as string[]) : [];
        const types = Object.entries((r.case_types ?? {}) as Record<string, number>);
        // Everything the row doesn't draw is summarized here.
        const tip = [
          name,
          `${tasks} task(s) · ${modeMeta.label}`,
          types.map(([t, n]) => `${t} ${n}`).join(" · "),
          devices.length ? `devices: ${devices.join(", ")}` : "",
          r.description ? String(r.description) : "",
        ]
          .filter(Boolean)
          .join("\n");
        return (
          <Tooltip key={`${name}-${i}`} title={<span style={{ whiteSpace: "pre-line" }}>{tip}</span>}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
              <span style={{ fontSize: 13, color: primary, flex: "0 0 auto" }}>
                {modeMeta.icon}
              </span>
              <Text style={{ width: 118, minWidth: 118, fontSize: 12 }} ellipsis>
                {name}
              </Text>
              <div style={{ flex: 1, minWidth: 0 }}>
                <RatioBar
                  segments={types.map(([t, n]) => ({
                    key: t,
                    pct: (Number(n) / max) * 100,
                    color: barColor(t),
                    tip: `${t}: ${n} of ${tasks} task(s)`,
                  }))}
                />
              </div>
              <Text style={{ width: 24, fontSize: 12, textAlign: "right" }}>{tasks}</Text>
            </div>
          </Tooltip>
        );
      })}
    </div>
  );
}

/** Per-card body: the stats + the ratio-bar chart + the recent list. */
function CardBody({ tabKey, card }: { tabKey: DashboardTabKey; card: DashboardCard }) {
  const chartNode = <BarChart data={card.chart ?? []} />;

  switch (tabKey) {
    case "device":
      return (
        <>
          <Stats
            items={[
              { label: "Devices", value: num(card, "total") },
              { label: "With IP", value: num(card, "with_ip") },
              { label: "No IP", value: num(card, "without_ip") },
            ]}
          />
          <div style={{ marginTop: 10 }}>
            <DeviceFeatureGrid
              data={card.chart ?? []}
              total={num(card, "total")}
            />
          </div>
          <DeviceRecentList rows={card.recent} />
        </>
      );
    case "profile":
      return (
        <>
          <Stats
            items={[
              { label: "Profiles", value: num(card, "total") },
              { label: "Tasks", value: num(card, "tasks_total") },
              { label: "Devices", value: num(card, "devices_total") },
            ]}
          />
          <div style={{ marginTop: 10 }}>
            <ProfileBadgeList rows={card.profile_rows} />
          </div>
        </>
      );
    case "runcase":
      return (
        <>
          <Stats
            items={[
              { label: "Cases", value: num(card, "cases") },
              { label: "Reports", value: num(card, "reports") },
              { label: "Running", value: num(card, "running") },
            ]}
          />
          {/* One compact line per summary report, newest first. */}
          <div style={{ marginTop: 10 }}>
            <StatusLines
              rows={card.report_rows ?? []}
              statuses={RUNCASE_STATUSES}
              totalKey="executed"
              label={(r) => String(r.profile ?? "")}
              sublabel={(r) => String(r.at ?? "")}
            />
          </div>
        </>
      );
    case "rokutest":
      return (
        <>
          <Stats
            items={[
              { label: "Cases", value: num(card, "cases") },
              { label: "Runs", value: num(card, "runs") },
              { label: "Results", value: num(card, "results") },
            ]}
          />
          {/* One compact line per case: cumulative statuses across its runs. */}
          <div style={{ marginTop: 10 }}>
            <StatusLines
              rows={card.case_rows ?? []}
              statuses={ROKUTEST_STATUSES}
              totalKey="total"
              label={(r) => String(r.label ?? r.case ?? "")}
              sublabel={(r) => `${r.runs ?? 0} run(s) · ${r.testrail_case_id ?? ""}`}
            />
          </div>
        </>
      );
    case "analyzehistory":
      return (
        <>
          <Stats
            items={[
              { label: "Analyses", value: num(card, "total") },
              { label: "Cases", value: num(card, "cases") },
              { label: "Today", value: num(card, "today") },
            ]}
          />
          {/* Verdict distribution as a donut (the card's only chart). */}
          <div style={{ marginTop: 12 }}>
            <ResultPie
              data={card.pie ?? []}
              detail={card.pie_detail as Record<string, unknown>[] | undefined}
              total={num(card, "total")}
              cases={num(card, "cases")}
              today={num(card, "today")}
            />
          </div>
        </>
      );
    case "testrail":
      return (
        <>
          <Stats
            items={[
              { label: "Plans", value: num(card, "plans") },
              { label: "Cached", value: num(card, "cached_plans") },
              { label: "Cases", value: num(card, "cases") },
            ]}
          />
          {/* Plans ranked by Failed ratio (top 8), two Device-style tiles per row. */}
          <div style={{ marginTop: 10 }}>
            <TestRailPlanGrid rows={card.plan_rows} />
            <StatusLegend statuses={["failed", "blocked"]} />
          </div>
        </>
      );
    case "agent":
      return (
        <>
          <Stats
            items={[
              { label: "Sessions", value: num(card, "sessions") },
              { label: "Messages", value: num(card, "messages") },
              { label: "Skills", value: num(card, "skills") },
            ]}
          />
          <Space size={4} wrap style={{ marginTop: 6 }}>
            <Tag color="blue">model: {str(card, "model") || "—"}</Tag>
            <Tag>{num(card, "models")} configured</Tag>
          </Space>
          <div style={{ marginTop: 10 }}>{chartNode}</div>
          <RecentList rows={card.recent} fields={["title", "count"]} />
        </>
      );
    case "reference":
      return (
        <>
          <Stats
            items={[
              { label: "Links", value: num(card, "refs") },
              { label: "Docs", value: num(card, "docs") },
              { label: "Doc files", value: num(card, "doc_files") },
            ]}
          />
          {/* Categories grouped by type (Links / Docs): 3 tiles per row. */}
          <div style={{ marginTop: 10 }}>
            <ReferenceCategoryGrid
              linkRows={card.link_rows as Record<string, unknown>[] | undefined}
              docRows={card.doc_rows as Record<string, unknown>[] | undefined}
            />
          </div>
        </>
      );
    case "filetransfer":
      return (
        <>
          <Stats
            items={[
              { label: "Files", value: num(card, "files") },
              { label: "Size", value: humanSize(num(card, "total_size")) },
              { label: "SCP servers", value: num(card, "scp_servers") },
            ]}
          />
          <Space size={4} wrap style={{ marginTop: 6 }}>
            <Tag color={card.http_running ? "green" : "default"}>
              http :{num(card, "http_port")} {card.http_running ? "running" : "stopped"}
            </Tag>
          </Space>
          <div style={{ marginTop: 10 }}>{chartNode}</div>
        </>
      );
    case "donuts":
      return (
        <>
          <Stats
            items={[
              { label: "Runs", value: num(card, "total") },
              { label: "Products", value: num(card, "products") },
            ]}
          />
          <div style={{ marginTop: 10 }}>{chartNode}</div>
          <RecentList rows={card.recent} fields={["donut", "branch", "device"]} />
        </>
      );
    case "activate":
      return (
        <>
          <Stats
            items={[
              { label: "Jobs", value: num(card, "total") },
              { label: "Running", value: num(card, "running") },
              { label: "Finished", value: num(card, "finished") },
            ]}
          />
          {/* Jobs as a square-tile grid, 3 per row. */}
          <div style={{ marginTop: 10 }}>
            <ActivateJobGrid rows={card.recent} />
          </div>
        </>
      );
    default:
      return chartNode;
  }
}

/**
 * Dashboard: a 2-column grid of cards, one per other tab, each showing a few
 * key numbers, a small chart, and an "Open" link that jumps to that tab.
 *
 * `onNavigate` is supplied by App.tsx (it sets the active page); `visibleTabs`
 * limits the grid to the tabs the user can actually see, so a hidden tab never
 * gets a card with a dead link.
 */
export default function DashboardPage({
  onNavigate,
  visibleTabs,
}: {
  onNavigate?: (key: DashboardTabKey) => void;
  visibleTabs?: string[];
}) {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  // Chart colors come from the theme inside each chart (useChartColors), so the
  // page itself needs no token.

  const load = useCallback(() => {
    setLoading(true);
    getDashboardSummary()
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const cards = useMemo(
    () =>
      CARD_META.filter((m) => !visibleTabs?.length || visibleTabs.includes(m.key)),
    [visibleTabs]
  );

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            Dashboard
          </Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {data?.generated_at ? `Snapshot at ${data.generated_at}` : "Loading snapshot…"}
          </Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
          Refresh
        </Button>
      </div>

      {error && <Alert type="error" showIcon message={`Failed to load dashboard: ${error}`} />}

      <Spin spinning={loading && !data}>
        {/* 3 columns on wide screens, 2 on tablets, 1 on phones; rows wrap. */}
        <Row gutter={[16, 16]}>
          {cards.map(({ key, title, icon }) => {
            const card = data?.cards?.[key] ?? {};
            return (
              <Col key={key} xs={24} sm={24} md={12} lg={8} xxl={8}>
                <Card
                  size="small"
                  style={{ height: "100%" }}
                  title={
                    <Space>
                      {icon}
                      <span>{title}</span>
                    </Space>
                  }
                  extra={
                    // Jump link into the corresponding tab.
                    <Button
                      type="link"
                      size="small"
                      onClick={() => onNavigate?.(key)}
                      disabled={!onNavigate}
                    >
                      Open <ArrowRightOutlined />
                    </Button>
                  }
                >
                  {card.error ? (
                    <Alert type="warning" showIcon message={String(card.error)} />
                  ) : (
                    <CardBody tabKey={key} card={card} />
                  )}
                </Card>
              </Col>
            );
          })}
        </Row>
      </Spin>
    </Space>
  );
}
