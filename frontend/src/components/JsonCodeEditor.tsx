import { useMemo } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { json } from "@codemirror/lang-json";
import { linter, lintGutter, type Diagnostic } from "@codemirror/lint";
import { EditorView, hoverTooltip, type Tooltip } from "@codemirror/view";
import { foldGutter, syntaxTree } from "@codemirror/language";

// A CodeMirror-6 based JSON editor/viewer used by the Device/Profile dialogs.
// Gives native code folding (fold gutter), JSON syntax highlighting, and live
// syntax validation with red error markers. In read-only mode it is the "View"
// widget; editable it is the "Edit"/"Add" widget.
//
// onValidityChange reports a human-readable error (with line/column) or null when
// the document parses, so the parent can show a red bar and disable Save.

// Dark theme matching the app's existing JSON widgets (#1e1e1e bg + token colors).
const darkTheme = EditorView.theme(
  {
    "&": { backgroundColor: "#1e1e1e", color: "#d0d0d0", fontSize: "13px" },
    ".cm-content": {
      fontFamily: "Consolas, Menlo, monospace",
      caretColor: "#fff",
    },
    ".cm-gutters": {
      backgroundColor: "#1e1e1e",
      color: "#6b7280",
      border: "none",
    },
    ".cm-activeLine": { backgroundColor: "rgba(255,255,255,0.04)" },
    ".cm-activeLineGutter": { backgroundColor: "rgba(255,255,255,0.06)" },
    "&.cm-focused": { outline: "none" },
    ".cm-foldPlaceholder": {
      backgroundColor: "#333",
      border: "1px solid #555",
      color: "#ccc",
      padding: "0 4px",
    },
    // Notepad++ "JSON Viewer"-style fold markers: a small boxed [-]/[+].
    ".cm-foldGutter .cm-gutterElement": { padding: "0 2px" },
    ".cm-npp-fold": {
      display: "inline-block",
      width: "13px",
      height: "13px",
      lineHeight: "11px",
      textAlign: "center",
      border: "1px solid #7a8290",
      borderRadius: "2px",
      color: "#c7ccd4",
      background: "#2a2d33",
      fontSize: "12px",
      cursor: "pointer",
    },
    // Field-description hover tooltip.
    ".cm-tooltip.cm-field-doc": {
      backgroundColor: "#2a2d33",
      border: "1px solid #4b5563",
      borderRadius: "6px",
      color: "#e5e7eb",
      padding: "6px 10px",
      maxWidth: "360px",
      fontSize: "12px",
      lineHeight: "1.5",
      boxShadow: "0 2px 8px rgba(0,0,0,0.4)",
    },
    ".cm-field-doc .cm-field-doc-name": {
      color: "#7dd3fc",
      fontFamily: "Consolas, Menlo, monospace",
      fontWeight: 600,
    },
    ".cm-field-doc .cm-field-doc-label": {
      color: "#9ca3af",
      fontSize: "11px",
      marginTop: "4px",
    },
    ".cm-field-doc .cm-field-doc-example": {
      marginTop: "2px",
      fontFamily: "Consolas, Menlo, monospace",
      color: "#a7f3d0",
      whiteSpace: "pre-wrap",
      wordBreak: "break-word",
    },
  },
  { dark: true }
);

// A hover tooltip that, when the pointer is over a JSON key (PropertyName), shows
// the matching description from `fieldDocs` (keyed by the bare field name).
function fieldDocTooltip(fieldDocs: Record<string, string>) {
  return hoverTooltip((view, pos): Tooltip | null => {
    const tree = syntaxTree(view.state);
    let node = tree.resolveInner(pos, 0);
    // Walk up to the PropertyName node if we're inside the key string.
    while (node && node.name !== "PropertyName" && node.parent) {
      if (node.name === "Property") break;
      node = node.parent;
    }
    if (!node || node.name !== "PropertyName") return null;
    // The key text includes the surrounding quotes; strip them.
    const rawKey = view.state.sliceDoc(node.from, node.to);
    const key = rawKey.replace(/^"|"$/g, "");
    const doc = fieldDocs[key];
    if (!doc) return null;
    return {
      pos: node.from,
      end: node.to,
      above: true,
      create() {
        const dom = document.createElement("div");
        dom.className = "cm-field-doc";
        const name = document.createElement("span");
        name.className = "cm-field-doc-name";
        name.textContent = key;
        const label = document.createElement("div");
        label.className = "cm-field-doc-label";
        label.textContent = "Example:";
        const example = document.createElement("div");
        example.className = "cm-field-doc-example";
        example.textContent = doc;
        dom.appendChild(name);
        dom.appendChild(label);
        dom.appendChild(example);
        return { dom };
      },
    };
  });
}

// Custom fold gutter whose markers look like Notepad++'s JSON Viewer: a boxed
// minus when open, boxed plus when folded.
const nppFoldGutter = foldGutter({
  markerDOM(open) {
    const el = document.createElement("span");
    el.className = "cm-npp-fold";
    el.textContent = open ? "−" : "+"; // − / +
    el.title = open ? "Collapse" : "Expand";
    return el;
  },
});

// Parse-error -> line/column, for both the inline lint diagnostic and the parent
// error bar. Node/V8 SyntaxError messages often include "position N"; fall back to
// highlighting the whole doc if we can't locate it.
function jsonError(text: string): { message: string; pos: number } | null {
  if (text.trim() === "") return null; // empty is treated as valid-ish (no marker)
  try {
    JSON.parse(text);
    return null;
  } catch (e) {
    const raw = (e as Error).message || "JSON parse error";
    const m = raw.match(/position (\d+)/i);
    const pos = m ? Math.min(Number(m[1]), text.length) : 0;
    return { message: raw, pos };
  }
}

function lineCol(text: string, pos: number): { line: number; col: number } {
  let line = 1,
    col = 1;
  for (let i = 0; i < pos && i < text.length; i++) {
    if (text[i] === "\n") {
      line++;
      col = 1;
    } else {
      col++;
    }
  }
  return { line, col };
}

export default function JsonCodeEditor({
  value,
  onChange,
  readOnly = false,
  onValidityChange,
  minHeight = "120px",
  maxHeight = "60vh",
  fieldDocs,
}: {
  value: string;
  onChange?: (v: string) => void;
  readOnly?: boolean;
  onValidityChange?: (error: string | null) => void;
  minHeight?: string;
  maxHeight?: string;
  // Optional map of JSON field name -> description. When set, hovering a key in
  // the editor shows its description in a tooltip.
  fieldDocs?: Record<string, string>;
}) {
  const extensions = useMemo(
    () => [
      json(),
      nppFoldGutter,
      lintGutter(),
      ...(fieldDocs ? [fieldDocTooltip(fieldDocs)] : []),
      // Linter: surface a positioned JSON diagnostic + report validity upward.
      linter((view): Diagnostic[] => {
        const text = view.state.doc.toString();
        const err = jsonError(text);
        if (!err) {
          onValidityChange?.(null);
          return [];
        }
        const { line, col } = lineCol(text, err.pos);
        onValidityChange?.(`${err.message} (line ${line}, column ${col})`);
        const from = Math.max(0, Math.min(err.pos, text.length - 1));
        return [
          {
            from,
            to: Math.min(from + 1, text.length),
            severity: "error",
            message: err.message,
          },
        ];
      }),
      darkTheme,
    ],
    [onValidityChange, fieldDocs]
  );

  return (
    <div
      style={{
        marginTop: 4,
        border: "1px solid #424242",
        borderRadius: 6,
        overflow: "hidden",
      }}
    >
      <CodeMirror
        value={value}
        editable={!readOnly}
        readOnly={readOnly}
        onChange={onChange}
        extensions={extensions}
        theme="dark"
        minHeight={minHeight}
        maxHeight={maxHeight}
        basicSetup={{
          lineNumbers: true,
          foldGutter: false, // using the custom Notepad++-style gutter instead
          highlightActiveLine: !readOnly,
          highlightActiveLineGutter: !readOnly,
          bracketMatching: true,
        }}
      />
    </div>
  );
}
