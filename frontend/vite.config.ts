import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const confDir = dirname(fileURLToPath(import.meta.url));

// Read host/port and tab visibility from conf/config.yml. No YAML dependency:
// the file is a small nested map, so a tiny indent-aware parser is enough.
// Falls back to sane defaults if the file or a key is missing.
function loadConfig() {
  const cfg = {
    server: { host: "0.0.0.0", port: 9898 },
    backend: { host: "127.0.0.1", port: 9888 },
  };
  try {
    const text = readFileSync(resolve(confDir, "conf/config.yml"), "utf-8");
    let section: "server" | "backend" | null = null;
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.replace(/#.*$/, ""); // strip comments
      if (!line.trim()) continue;
      const top = line.match(/^(\w+):\s*$/); // "server:" / "backend:"
      if (top) {
        const name = top[1];
        section = name === "server" || name === "backend" ? name : null;
        continue;
      }
      const kv = line.match(/^\s+([\w-]+):\s*"?([^"\s]+)"?\s*$/); // "  key: val"
      if (!kv || !section) continue;
      const [, key, value] = kv;
      if (key === "host") cfg[section].host = value;
      else if (key === "port") cfg[section].port = Number(value);
    }
  } catch {
    // config.yml unreadable — keep defaults.
  }
  return cfg;
}

const cfg = loadConfig();

// Tab visibility is loaded at runtime from the backend, not injected here.
export default defineConfig({
  plugins: [react()],
  server: {
    host: cfg.server.host,
    port: cfg.server.port,
    proxy: {
      "/api": {
        target: `http://${cfg.backend.host}:${cfg.backend.port}`,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
