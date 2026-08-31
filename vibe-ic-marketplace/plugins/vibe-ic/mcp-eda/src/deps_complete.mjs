#!/usr/bin/env node
/**
 * deps_complete.mjs — the ONE question both install guards must ask:
 * does the installed node_modules tree match the lockfile?
 *
 * Why this file exists (#1931): an interrupted `npm install` during a plugin
 * update left a HALF-EXTRACTED tree — 91 of 93 packages present, the SDK
 * directory holding only `dist/` (no package.json), npm staging dirs
 * (`.hono-565qHAHp`, …) abandoned alongside, and `.package-lock.json`
 * recording the install as COMPLETE. Both shipped guards passed over it:
 *   - post_install.sh tested `-d node_modules` (the directory existed), and
 *   - bootstrap.mjs probed ONE file (the SDK's package.json — present in
 *     variants of this state, and even when present it says nothing about
 *     the other 92 packages `index.js` transitively imports).
 * Worse, the recovery path (`npm install`) read `.package-lock.json`, judged
 * the tree complete, and no-opped — so the FATAL was deterministic on every
 * start. A guard that cannot see the state it exists for is no guard; this
 * module makes both guards ask the real question.
 *
 * The denominator comes from the lockfile, not from package.json: the shipped
 * `package-lock.json` names every transitive package (93 today), while
 * `dependencies` names one. A package COUNTS AS INSTALLED only if its own
 * `package.json` exists — the field state's `sdk/` held only `dist/`, so a
 * bare directory test would re-create the original blindness one level down.
 */

import { existsSync, readFileSync, writeFileSync, renameSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

/**
 * The package paths (relative to pkgRoot, e.g. "node_modules/zod") that the
 * lockfile says a production install must contain.
 *
 * Source order: the SHIPPED root package-lock.json first (immutable, cannot
 * have been truncated by the interrupted install we are guarding against),
 * then the hidden node_modules/.package-lock.json, then — with no lockfile at
 * all — the direct dependencies from package.json (weaker, but still strictly
 * stronger than `-d node_modules`).
 */
export function requiredPackages(pkgRoot) {
  for (const lockPath of [
    join(pkgRoot, "package-lock.json"),
    join(pkgRoot, "node_modules", ".package-lock.json"),
  ]) {
    const lock = readJson(lockPath);
    const pkgs = lock && lock.packages;
    if (!pkgs || typeof pkgs !== "object") continue;
    const required = Object.entries(pkgs)
      .filter(([key, meta]) =>
        key.startsWith("node_modules/") &&
        meta && !meta.dev && !meta.optional && !meta.link)
      .map(([key]) => key);
    if (required.length > 0) return required;
  }
  const pkg = readJson(join(pkgRoot, "package.json"));
  if (pkg && pkg.dependencies && typeof pkg.dependencies === "object") {
    return Object.keys(pkg.dependencies).map((n) => join("node_modules", n));
  }
  return null; // no manifest at all — the caller decides what that means
}

/** The required packages whose own package.json is absent — [] means complete. */
export function missingPackages(pkgRoot) {
  const required = requiredPackages(pkgRoot);
  if (required === null) return null;
  return required.filter(
    (rel) => !existsSync(join(pkgRoot, rel, "package.json")));
}

/**
 * Drop this plugin's entry from the MCP client's needs-auth failure cache.
 *
 * When bootstrap died FATAL on every start (#1931), the client cached the
 * failure in mcp-needs-auth-cache.json — so even after the tree is repaired,
 * the stale entry keeps the server marked broken. On a successful REPAIR
 * (and only then — never on the hot path) we remove our own key. Best-effort:
 * the file belongs to the client, so any surprise in it means leave it alone.
 * Returns true only when an entry was actually removed.
 */
export function clearNeedsAuthCacheEntry() {
  try {
    const cfgDir = process.env.CLAUDE_CONFIG_DIR || join(homedir(), ".claude");
    const cachePath = join(cfgDir, "mcp-needs-auth-cache.json");
    const cache = readJson(cachePath);
    if (!cache || typeof cache !== "object") return false;
    const ours = Object.keys(cache).filter(
      (k) => k.includes("vibe-ic") && k.includes("eda-tools"));
    if (ours.length === 0) return false;
    for (const k of ours) delete cache[k];
    const tmp = cachePath + ".tmp";
    writeFileSync(tmp, JSON.stringify(cache));
    renameSync(tmp, cachePath);
    return true;
  } catch {
    return false;
  }
}

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf-8"));
  } catch {
    return null;
  }
}

/**
 * CLI — the same question, callable from bash (post_install.sh):
 *   node deps_complete.mjs [--pkg-root <dir>]        exit 0 complete
 *                                                    exit 1 incomplete (missing listed on stdout)
 *                                                    exit 2 no manifest to check against
 *   node deps_complete.mjs --clear-needs-auth-cache  exit 0 always (prints what it did)
 */
const invokedDirectly =
  process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedDirectly) {
  const args = process.argv.slice(2);
  if (args.includes("--clear-needs-auth-cache")) {
    const cleared = clearNeedsAuthCacheEntry();
    process.stdout.write(cleared
      ? "cleared stale needs-auth cache entry\n"
      : "no needs-auth cache entry to clear\n");
    process.exit(0);
  }
  const rootIdx = args.indexOf("--pkg-root");
  const pkgRoot = rootIdx >= 0 && args[rootIdx + 1]
    ? args[rootIdx + 1]
    : join(process.cwd());
  const missing = missingPackages(pkgRoot);
  if (missing === null) {
    process.stderr.write(`deps_complete: no package.json or lockfile under ${pkgRoot}\n`);
    process.exit(2);
  }
  if (missing.length > 0) {
    for (const rel of missing) process.stdout.write(rel + "\n");
    process.exit(1);
  }
  process.exit(0);
}
