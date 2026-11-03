import { type CSSProperties } from "react";

// Zero-dependency JSON syntax highlighter for read-only display on the dark
// theme. Tokenises a pretty-printed JSON string and colours keys / strings /
// numbers / booleans / null. Escapes HTML first so content can't inject markup.
const COLORS = {
  key: "#79b8ff", // property names
  string: "#a5d6a7", // string values
  number: "#f7c873", // numbers
  bool: "#c792ea", // true / false
  null: "#8b98a5", // null
  punct: "#d0d0d0", // braces, colons, commas
};

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function highlight(jsonText: string): string {
  const escaped = escapeHtml(jsonText);
  // Match strings (incl. keys), numbers, booleans, null.
  const re =
    /("(\\.|[^"\\])*"\s*:)|("(\\.|[^"\\])*")|(\b-?\d+(\.\d+)?([eE][+-]?\d+)?\b)|(\b(true|false)\b)|(\bnull\b)/g;
  return escaped.replace(re, (match) => {
    let color = COLORS.punct;
    if (/^".*:\s*$/.test(match)) color = COLORS.key;
    else if (/^"/.test(match)) color = COLORS.string;
    else if (/true|false/.test(match)) color = COLORS.bool;
    else if (/null/.test(match)) color = COLORS.null;
    else color = COLORS.number;
    return `<span style="color:${color}">${match}</span>`;
  });
}

export default function JsonView({
  text,
  style,
}: {
  text: string;
  style?: CSSProperties;
}) {
  return (
    <pre
      style={{
        margin: 0,
        padding: 12,
        background: "#1e1e1e",
        color: COLORS.punct,
        borderRadius: 6,
        border: "1px solid #424242",
        fontFamily: "Consolas, Menlo, monospace",
        fontSize: 13,
        lineHeight: 1.5,
        whiteSpace: "pre",
        overflow: "auto",
        ...style,
      }}
      dangerouslySetInnerHTML={{ __html: highlight(text) }}
    />
  );
}

// Estimate a comfortable modal width so the widest JSON line fits without
// horizontal scrolling in the CodeMirror editor. Budget: ~7.3px per monospace
// char at 13px for the content, plus the editor gutters (line numbers + fold +
// lint markers, ~60px), plus the Modal body/padding (~90px). The line-count
// factor widens the line-number gutter for long files. Clamped to the viewport.
export function jsonModalWidth(text: string): number {
  const lines = text.split("\n");
  const maxLine = lines.reduce((m, line) => Math.max(m, line.length), 0);
  const gutter = 60 + String(lines.length).length * 9; // line-number + fold + lint
  const px = Math.round(maxLine * 7.3) + gutter + 90;
  const vw = typeof window !== "undefined" ? window.innerWidth : 1600;
  return Math.min(Math.round(vw * 0.95), Math.max(520, px));
}
