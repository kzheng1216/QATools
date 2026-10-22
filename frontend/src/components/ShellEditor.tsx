import { useRef, type CSSProperties } from "react";

// Editable shell-script field with live syntax highlighting. Same technique as
// JsonEditor: a transparent <textarea> sits on top of a highlighted <pre> with
// identical font metrics so glyphs line up.
const COLORS = {
  comment: "#6a9955",
  string: "#ce9178",
  keyword: "#c586c0",
  builtin: "#4ec9b0",
  variable: "#9cdcfe",
  number: "#b5cea8",
  shebang: "#808080",
  text: "#d4d4d4",
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

const KEYWORDS = [
  "if", "then", "elif", "else", "fi", "for", "while", "until", "do", "done",
  "case", "esac", "in", "function", "select", "return", "break", "continue",
  "local", "export", "declare", "readonly", "set", "unset", "shift",
];
const BUILTINS = [
  "echo", "printf", "cd", "pwd", "read", "source", "exit", "test", "eval",
  "exec", "trap", "wait", "sleep", "kill", "mkdir", "rm", "cp", "mv", "ls",
  "cat", "grep", "sed", "awk", "curl", "wget", "ssh", "scp", "python", "python3",
  "pip", "git", "docker", "sudo", "chmod", "chown", "tar", "find", "xargs",
];

// Tokenize a single line and return highlighted HTML. Order matters: comments
// and strings first (they swallow everything inside), then variables, numbers,
// keywords/builtins on bare words.
function highlightLine(line: string): string {
  // Shebang.
  if (/^#!/.test(line)) {
    return `<span style="color:${COLORS.shebang}">${escapeHtml(line)}</span>`;
  }
  let out = "";
  let i = 0;
  const n = line.length;
  const isWordChar = (c: string) => /[A-Za-z0-9_]/.test(c);
  while (i < n) {
    const c = line[i];
    // Comment to end of line (only when # starts a word, not inside $#, etc.).
    if (c === "#" && (i === 0 || /\s/.test(line[i - 1]))) {
      out += `<span style="color:${COLORS.comment}">${escapeHtml(line.slice(i))}</span>`;
      break;
    }
    // Single-quoted string (no escapes inside).
    if (c === "'") {
      let j = i + 1;
      while (j < n && line[j] !== "'") j++;
      const seg = line.slice(i, Math.min(j + 1, n));
      out += `<span style="color:${COLORS.string}">${escapeHtml(seg)}</span>`;
      i = j + 1;
      continue;
    }
    // Double-quoted string (escapes allowed).
    if (c === '"') {
      let j = i + 1;
      while (j < n && line[j] !== '"') {
        if (line[j] === "\\") j++;
        j++;
      }
      const seg = line.slice(i, Math.min(j + 1, n));
      out += `<span style="color:${COLORS.string}">${escapeHtml(seg)}</span>`;
      i = j + 1;
      continue;
    }
    // Variable: $VAR, ${VAR}, $1, $@, $?, $(...).
    if (c === "$") {
      let j = i + 1;
      if (line[j] === "{") {
        while (j < n && line[j] !== "}") j++;
        j++;
      } else if (line[j] === "(") {
        // leave $( ) for normal processing of inner tokens; just color the $(
        out += `<span style="color:${COLORS.variable}">$(</span>`;
        i += 2;
        continue;
      } else {
        while (j < n && (isWordChar(line[j]) || "@*?#!$-".includes(line[j]))) j++;
        if (j === i + 1) j++; // at least consume one special char
      }
      const seg = line.slice(i, j);
      out += `<span style="color:${COLORS.variable}">${escapeHtml(seg)}</span>`;
      i = j;
      continue;
    }
    // Bare word -> keyword / builtin / number / plain.
    if (isWordChar(c)) {
      let j = i;
      while (j < n && isWordChar(line[j])) j++;
      const word = line.slice(i, j);
      let color = COLORS.text;
      if (KEYWORDS.includes(word)) color = COLORS.keyword;
      else if (BUILTINS.includes(word)) color = COLORS.builtin;
      else if (/^\d+$/.test(word)) color = COLORS.number;
      out +=
        color === COLORS.text
          ? escapeHtml(word)
          : `<span style="color:${color}">${escapeHtml(word)}</span>`;
      i = j;
      continue;
    }
    // Any other single char.
    out += escapeHtml(c);
    i++;
  }
  return out;
}

function highlight(text: string): string {
  return text.split("\n").map(highlightLine).join("\n");
}

export default function ShellEditor({
  value,
  onChange,
  minHeight = 240,
  maxHeight = "60vh",
}: {
  value: string;
  onChange: (v: string) => void;
  minHeight?: number | string;
  maxHeight?: number | string;
}) {
  const preRef = useRef<HTMLPreElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  const lineCount = value.split("\n").length + 1;
  const contentHeight = Math.round(lineCount * 19.5) + 24;

  const syncScroll = () => {
    if (preRef.current && taRef.current) {
      preRef.current.scrollTop = taRef.current.scrollTop;
      preRef.current.scrollLeft = taRef.current.scrollLeft;
    }
  };

  // Tab inserts two spaces instead of moving focus.
  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const ta = e.currentTarget;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const next = value.slice(0, start) + "  " + value.slice(end);
      onChange(next);
      requestAnimationFrame(() => {
        ta.selectionStart = ta.selectionEnd = start + 2;
      });
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
          color: COLORS.text,
          overflow: "auto",
          pointerEvents: "none",
        }}
        dangerouslySetInnerHTML={{ __html: highlight(value) + "\n" }}
      />
      <textarea
        ref={taRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onScroll={syncScroll}
        onKeyDown={onKeyDown}
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
