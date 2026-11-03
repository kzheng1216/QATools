import { useRef, type CSSProperties } from "react";

// Editable JSON field with live syntax highlighting. Technique: a transparent
// <textarea> sits exactly on top of a highlighted <pre>; the user types into the
// textarea (caret + selection visible) while the coloured <pre> shows through.
// Both share identical font metrics, padding and wrapping so glyphs line up.
const COLORS = {
  key: "#79b8ff",
  string: "#a5d6a7",
  number: "#f7c873",
  bool: "#c792ea",
  null: "#8b98a5",
  punct: "#d0d0d0",
};

const SHARED: CSSProperties = {
  margin: 0,
  padding: 12,
  fontFamily: "Consolas, Menlo, monospace",
  fontSize: 13,
  lineHeight: 1.5,
  whiteSpace: "pre",
  tabSize: 4,
  border: "none",
  boxSizing: "border-box",
};

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function highlight(jsonText: string): string {
  const escaped = escapeHtml(jsonText);
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

export default function JsonEditor({
  value,
  onChange,
  minHeight = 80,
  maxHeight = "60vh",
}: {
  value: string;
  onChange: (v: string) => void;
  minHeight?: number | string;
  maxHeight?: number | string;
}) {
  const preRef = useRef<HTMLPreElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  // Grow the box to fit the content (like the read-only JsonView), so the Edit
  // dialog opens at the same size as View. 13px font * 1.5 line-height ≈ 19.5px
  // per line, plus 24px vertical padding. maxHeight caps it (then it scrolls).
  const lineCount = value.split("\n").length + 1; // +1 for the trailing newline
  const contentHeight = Math.round(lineCount * 19.5) + 24;

  // Keep the coloured layer scrolled in lockstep with the textarea.
  const syncScroll = () => {
    if (preRef.current && taRef.current) {
      preRef.current.scrollTop = taRef.current.scrollTop;
      preRef.current.scrollLeft = taRef.current.scrollLeft;
    }
  };

  return (
    <div
      style={{
        position: "relative",
        marginTop: 4,
        background: "#1e1e1e",
        border: "1px solid #424242",
        borderRadius: 6,
        height: `min(${contentHeight}px, ${typeof maxHeight === "number" ? `${maxHeight}px` : maxHeight})`,
        minHeight,
        maxHeight,
        overflow: "hidden",
      }}
    >
      <pre
        ref={preRef}
        aria-hidden
        style={{
          ...SHARED,
          position: "absolute",
          inset: 0,
          color: COLORS.punct,
          overflow: "auto",
          pointerEvents: "none",
        }}
        // Trailing newline keeps the last line visible while typing.
        dangerouslySetInnerHTML={{ __html: highlight(value) + "\n" }}
      />
      <textarea
        ref={taRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onScroll={syncScroll}
        spellCheck={false}
        style={{
          ...SHARED,
          position: "relative",
          width: "100%",
          height: "100%",
          resize: "none",
          background: "transparent",
          color: "transparent",
          caretColor: "#fff",
          outline: "none",
          overflow: "auto",
        }}
      />
    </div>
  );
}
