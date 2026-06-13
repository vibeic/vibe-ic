#!/usr/bin/env node
/**
 * bootstrap.mjs — self-healing entry point for the MCP EDA Server.
 *
 * Why this file exists (v1.6.18 Fix Prevention):
 * The plugin ships with a `package.json` and depends on
 * @modelcontextprotocol/sdk, but no `node_modules/`. The post_install.sh
 * SessionStart hook is supposed to run `npm install` on first plugin load,
 * but it only fires on a fresh Claude Code session — `/plugin install`
 * + `/reload-plugins` in an existing session leaves the deps un-installed,
 * and the next `/mcp` reconnect fails with ERR_MODULE_NOT_FOUND. The MCP
 * client surfaces this as the cryptic "Failed to reconnect to
 * plugin:vibe-ic:eda-tools".
 *
 * This bootstrap closes that race: before importing `index.js` (which
 * pulls in `@modelcontextprotocol/sdk` at module-load time), we verify
 * the SDK is resolvable. If not, we run `npm install --production` once,
 * synchronously, then proceed. On the steady-state hot path (deps
 * already installed) the check is a single statSync.
 *
 * Failure modes:
 *   - npm not in PATH       → log to stderr, exit 1 (unrecoverable)
 *   - npm install fails     → log to stderr, exit 1 (unrecoverable)
 *   - imports succeed       → server starts normally
 *
 * .mcp.json points its `command`/`args` here so Claude Code's MCP client
 * always invokes the bootstrap, never `index.js` directly.
 */

import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = resolve(__dirname, "..");
const SDK_PROBE = join(PKG_ROOT, "node_modules", "@modelcontextprotocol", "sdk", "package.json");
const PKG_JSON = join(PKG_ROOT, "package.json");

function ensureDeps() {
  if (existsSync(SDK_PROBE)) return; // hot path — deps present
  if (!existsSync(PKG_JSON)) {
    process.stderr.write(
      `[bootstrap] FATAL: package.json missing at ${PKG_JSON}; cannot self-install. ` +
      `Reinstall the plugin.\n`
    );
    process.exit(1);
  }
  process.stderr.write(
    `[bootstrap] node_modules missing — running 'npm install --production' in ${PKG_ROOT}\n`
  );
  const res = spawnSync(
    "npm",
    ["install", "--production", "--no-audit", "--no-fund", "--silent"],
    { cwd: PKG_ROOT, stdio: ["ignore", "pipe", "pipe"], encoding: "utf-8", timeout: 180_000 }
  );
  if (res.error) {
    process.stderr.write(
      `[bootstrap] FATAL: npm spawn failed: ${res.error.message}\n` +
      `[bootstrap] Manually run: cd ${PKG_ROOT} && npm install --production\n`
    );
    process.exit(1);
  }
  if (res.status !== 0) {
    process.stderr.write(
      `[bootstrap] FATAL: npm install exit=${res.status}\n${res.stderr || ""}\n` +
      `[bootstrap] Manually run: cd ${PKG_ROOT} && npm install --production\n`
    );
    process.exit(1);
  }
  if (!existsSync(SDK_PROBE)) {
    process.stderr.write(
      `[bootstrap] FATAL: npm install completed but SDK still not at ${SDK_PROBE}\n`
    );
    process.exit(1);
  }
  process.stderr.write(`[bootstrap] npm install OK — starting server\n`);
}

ensureDeps();
await import("./index.js");
