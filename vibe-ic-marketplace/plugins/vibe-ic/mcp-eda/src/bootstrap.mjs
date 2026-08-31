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
 * Why the probe is a lockfile-completeness check, not one statSync (#1931):
 * an interrupted `npm install` during a plugin update left node_modules
 * HALF-EXTRACTED — 91 of 93 packages in, the SDK dir holding only `dist/`,
 * and `.package-lock.json` recording the install as complete. The old
 * single-file SDK probe cannot see that state (and even when it goes red,
 * plain `npm install` reads `.package-lock.json`, judges the tree complete,
 * and NO-OPS — so the old flow died FATAL on every start, deterministically).
 * The check now asks the real question — every package the lockfile requires
 * is present — and when npm's incremental install cannot repair the tree,
 * the tree is treated as corrupt: remove node_modules entirely and install
 * once more from scratch before going FATAL. That converts an unrecoverable
 * wedge into one extra install (~93 packages, seconds with a warm cache).
 *
 * Failure modes:
 *   - npm not in PATH                    → log to stderr, exit 1 (unrecoverable)
 *   - npm install fails                  → log to stderr, exit 1 (unrecoverable)
 *   - tree still incomplete after a
 *     FRESH install                      → log the missing packages, exit 1
 *   - imports succeed                    → server starts normally
 *
 * .mcp.json points its `command`/`args` here so Claude Code's MCP client
 * always invokes the bootstrap, never `index.js` directly.
 */

import { existsSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { missingPackages, clearNeedsAuthCacheEntry } from "./deps_complete.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = resolve(__dirname, "..");
const PKG_JSON = join(PKG_ROOT, "package.json");
const NODE_MODULES = join(PKG_ROOT, "node_modules");

function npmInstall(label) {
  process.stderr.write(`[bootstrap] ${label}: running 'npm install --production' in ${PKG_ROOT}\n`);
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
}

function ensureDeps() {
  let missing = missingPackages(PKG_ROOT);
  if (missing !== null && missing.length === 0) return; // hot path — tree matches the lockfile
  if (missing === null) {
    if (!existsSync(PKG_JSON)) {
      process.stderr.write(
        `[bootstrap] FATAL: package.json missing at ${PKG_JSON}; cannot self-install. ` +
        `Reinstall the plugin.\n`
      );
      process.exit(1);
    }
    missing = []; // manifest unreadable but package.json exists — let npm decide
  }
  process.stderr.write(
    `[bootstrap] node_modules incomplete — ${missing.length} package(s) missing ` +
    `vs the lockfile (first: ${missing.slice(0, 3).join(", ") || "n/a"})\n`
  );
  npmInstall("incremental repair");

  missing = missingPackages(PKG_ROOT) || [];
  if (missing.length > 0) {
    // npm read the (lying) .package-lock.json and no-opped, or tripped on
    // abandoned staging dirs (ENOTEMPTY renames). The tree is corrupt beyond
    // incremental repair: the only recovery measured to work (#1931) is a
    // full wipe + fresh install, so do that once before giving up.
    process.stderr.write(
      `[bootstrap] tree still incomplete after npm install (${missing.length} ` +
      `missing) — treating node_modules as corrupt: wiping and reinstalling\n`
    );
    rmSync(NODE_MODULES, { recursive: true, force: true, maxRetries: 3 });
    npmInstall("fresh install after wipe");
    missing = missingPackages(PKG_ROOT) || [];
    if (missing.length > 0) {
      process.stderr.write(
        `[bootstrap] FATAL: node_modules still incomplete after a FRESH install. ` +
        `Missing vs lockfile: ${missing.join(", ")}\n` +
        `[bootstrap] Manually run: cd ${PKG_ROOT} && rm -rf node_modules && npm install --production\n`
      );
      process.exit(1);
    }
  }
  // A repair happened and the tree is now complete. The MCP client may have
  // cached the previous FATALs (mcp-needs-auth-cache.json) — drop our stale
  // entry so the repaired server is retried rather than stay marked broken.
  if (clearNeedsAuthCacheEntry()) {
    process.stderr.write(`[bootstrap] cleared stale needs-auth cache entry\n`);
  }
  process.stderr.write(`[bootstrap] npm install OK — starting server\n`);
}

ensureDeps();
await import("./index.js");
