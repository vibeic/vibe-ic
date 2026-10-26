#!/usr/bin/env node
/**
 * bootstrap.mjs — self-healing entry point for the MCP EDA Server.
 *
 * Why this file exists (v1.6.18 Fix Prevention):
 * The plugin ships with a `package.json` and depends on
 * @modelcontextprotocol/sdk, but no `node_modules/`. SessionStart is read-only;
 * this entry prepares a content-bound external snapshot before installing deps.
 * `/plugin install` + `/reload-plugins` can leave deps un-installed,
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

import { cpSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync,
         readdirSync, readlinkSync, realpathSync, renameSync, rmSync, rmdirSync,
         unlinkSync, writeFileSync } from "node:fs";
import { createHash, randomUUID } from "node:crypto";
import { homedir } from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { spawnSync } from "node:child_process";
import { missingPackages } from "./deps_complete.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SOURCE = realpathSync(resolve(__dirname, "../.."));
let PKG_ROOT, PKG_JSON, NODE_MODULES, INSTALL_LOCK, DEPS_SEAL;

// Bind shipped source, including package/lock/server and relative program
// imports, not a version label. Inspect excluded source dependencies too:
// never hide a symlink from the installed tree's independent trust consumer.
function sourceIdentity(root, runtime = false) {
  const hash = createHash("sha256");
  function walk(dir, excluded = false) {
    for (const name of readdirSync(dir).sort()) {
      const path = join(dir, name), rel = relative(root, path);
      let st;
      try { st = lstatSync(path); }
      catch (error) {
        if (runtime && error.code === "ENOENT" &&
            [join("mcp-eda", "node_modules"), join("mcp-eda", ".bootstrap-install.lock")].includes(rel)) continue;
        throw error;
      }
      if (!st.isDirectory() && !st.isFile()) throw new Error(`unsupported source entry: ${path}`);
      if (runtime && rel === join("mcp-eda", ".bootstrap-deps.json")) continue;
      if (runtime && rel === join("mcp-eda", ".bootstrap-install.lock")) {
        if (!st.isDirectory()) throw new Error(`invalid runtime lock: ${path}`);
        continue;
      }
      const deps = excluded || rel === join("mcp-eda", "node_modules");
      if (!deps) {
        hash.update(JSON.stringify([rel, st.mode, st.isDirectory() ? "directory" : "file"]));
        if (st.isFile()) hash.update(createHash("sha256").update(readFileSync(path)).digest());
      }
      // Only external npm state may contain bin links.
      if (st.isDirectory() && !(runtime && deps)) walk(path, deps);
    }
  }
  walk(root);
  return hash.digest("hex");
}

function materializeRuntime() {
  const identity = sourceIdentity(SOURCE);
  const cache = process.env.XDG_CACHE_HOME || join(homedir(), ".cache");
  if (!isAbsolute(cache)) throw new Error("XDG_CACHE_HOME must be absolute");
  const base = join(cache, "vibe-ic", "mcp-runtime");
  // Resolve existing ancestors before mkdir, including a symlinked cache home.
  let ancestor = base;
  while (!existsSync(ancestor)) ancestor = dirname(ancestor);
  const canonical = resolve(realpathSync(ancestor), relative(ancestor, base));
  if (canonical === SOURCE || canonical.startsWith(SOURCE + sep)) {
    throw new Error("external runtime must be outside the installed plugin");
  }
  mkdirSync(canonical, { recursive: true, mode: 0o700 });
  const destination = join(canonical, identity);
  if (!existsSync(destination)) {
    const staging = mkdtempSync(join(canonical, ".stage-"));
    try {
      cpSync(SOURCE, staging, { recursive: true,
        filter: path => path !== join(SOURCE, "mcp-eda", "node_modules") });
      if (sourceIdentity(staging) !== identity || sourceIdentity(SOURCE) !== identity) {
        throw new Error("plugin source changed while materializing runtime");
      }
      try { renameSync(staging, destination); }
      catch (error) {
        if (!["EEXIST", "ENOTEMPTY"].includes(error.code)) throw error;
      }
    } finally {
      rmSync(staging, { recursive: true, force: true }); // only our unique stage
    }
  }
  if (!lstatSync(destination).isDirectory() || sourceIdentity(destination, true) !== identity) {
    throw new Error(`runtime source identity mismatch: ${destination}`);
  }
  return join(destination, "mcp-eda");
}

// #3357: npm's incremental repair and #1931's wipe must be one transaction
// across clients of this package. Never evict a live owner based on lock age.
function acquireInstallLock() {
  const owner = `${process.pid}-${randomUUID()}`;
  const deadline = performance.now() + 400_000; // two 180s npm attempts + margin
  const sleeper = new Int32Array(new SharedArrayBuffer(4));
  let announced = false;
  while (performance.now() < deadline) {
    try {
      mkdirSync(INSTALL_LOCK, { mode: 0o700 });
    } catch (error) {
      if (error.code !== "EEXIST") throw error;
      // A token-specific unlink elects exactly one stale-lock reaper. A
      // second waiter must not unlink/rmdir a replacement owner's lock.
      try {
        const entries = readdirSync(INSTALL_LOCK);
        if (entries.length === 1 && /^[1-9][0-9]*-.+$/.test(entries[0])) {
          const pid = Number(entries[0].split("-", 1)[0]);
          if (Number.isSafeInteger(pid)) {
            try {
              process.kill(pid, 0);
            } catch (probe) {
              if (probe.code === "ESRCH") {
                unlinkSync(join(INSTALL_LOCK, entries[0]));
                rmdirSync(INSTALL_LOCK);
                continue;
              }
              if (probe.code !== "EPERM") throw probe;
            }
          }
        }
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
      // Empty/unrecognised owner records are not proof of process death.
      // They wait/refuse within the same bound rather than authorise a wipe.
      if (!announced) {
        process.stderr.write(`[bootstrap] waiting for dependency repair in ${PKG_ROOT}\n`);
        announced = true;
      }
      Atomics.wait(sleeper, 0, 0, 50);
      continue;
    }
    try {
      writeFileSync(join(INSTALL_LOCK, owner), "", { flag: "wx", mode: 0o600 });
    } catch (error) {
      rmdirSync(INSTALL_LOCK);
      throw error;
    }
    return () => {
      unlinkSync(join(INSTALL_LOCK, owner));
      rmdirSync(INSTALL_LOCK);
    };
  }
  throw new Error(`dependency repair lock timed out at ${INSTALL_LOCK}; retry after its owner exits`);
}

function npmInstall(label) {
  process.stderr.write(`[bootstrap] ${label}: running 'npm install --production' in ${PKG_ROOT}\n`);
  const res = spawnSync(
    "npm",
    ["install", "--production", "--no-audit", "--no-fund", "--silent"],
    { cwd: PKG_ROOT, stdio: ["ignore", "pipe", "pipe"], encoding: "utf-8", timeout: 180_000 }
  );
  if (res.error) {
    throw new Error(
      `[bootstrap] FATAL: npm spawn failed: ${res.error.message}\n` +
      `[bootstrap] Manually run: cd ${PKG_ROOT} && npm install --production\n`
    );
  }
  if (res.status !== 0) {
    throw new Error(
      `[bootstrap] FATAL: npm install exit=${res.status}\n${res.stderr || ""}\n` +
      `[bootstrap] Manually run: cd ${PKG_ROOT} && npm install --production\n`
    );
  }
}

function ensureDeps() {
  const release = acquireInstallLock();
  try {
    // No-follow inspection precedes even the existence-only completeness probe.
    const before = dependencyEntries();
    if (existsSync(DEPS_SEAL)) {
      if (!lstatSync(DEPS_SEAL).isFile()) throw new Error("invalid dependency integrity seal");
      const sealed = JSON.parse(readFileSync(DEPS_SEAL, "utf8"));
      for (const [path, value] of Object.entries(before)) {
        if (path in sealed && sealed[path] !== value) throw new Error(`dependency integrity mismatch: ${path}`);
      }
      if (missingPackages(PKG_ROOT)?.length === 0 && JSON.stringify(before) !== JSON.stringify(sealed)) {
        throw new Error("dependency integrity mismatch");
      }
    } else if (missingPackages(PKG_ROOT)?.length === 0) {
      throw new Error("complete dependencies have no integrity seal");
    }
    repairDeps(); // re-probe: another client may have completed the repair
    const entries = dependencyEntries();
    writeFileSync(DEPS_SEAL, JSON.stringify(entries), { mode: 0o600 });
  } finally {
    release(); // includes npm nonzero, missing npm and an unrepairable tree
  }
}

function dependencyEntries() {
  const entries = {}, bins = new Map();
  const lock = JSON.parse(readFileSync(PKG_JSON.replace(/package.json$/, "package-lock.json"), "utf8"));
  if (!lock.packages || typeof lock.packages !== "object") throw new Error("required package lock missing packages");
  for (const [pkg, metadata] of Object.entries(lock.packages)) {
    if (!pkg.startsWith("node_modules/") || !metadata.bin) continue;
    for (const [name, target] of Object.entries(metadata.bin)) {
      const destination = resolve(PKG_ROOT, pkg, target);
      if (name.includes("/") || !destination.startsWith(resolve(PKG_ROOT, pkg) + sep)) {
        throw new Error("invalid locked dependency bin");
      }
      bins.set(join(pkg.slice(0, pkg.lastIndexOf("node_modules/") + "node_modules".length), ".bin", name), destination);
    }
  }
  function walk(path) {
    const rel = relative(PKG_ROOT, path), st = lstatSync(path);
    if (st.isSymbolicLink()) {
      const target = bins.get(rel);
      if (!target || resolve(dirname(path), readlinkSync(path)) !== target ||
          realpathSync(target) !== target || !lstatSync(target).isFile()) {
        throw new Error(`unsupported dependency entry: ${rel}`);
      }
      entries[rel] = "link:" + readlinkSync(path);
    } else if (st.isDirectory()) {
      entries[rel] = `directory:${st.mode}`;
      for (const name of readdirSync(path).sort()) walk(join(path, name));
    } else if (st.isFile()) {
      entries[rel] = `file:${st.mode}:` + createHash("sha256").update(readFileSync(path)).digest("hex");
    } else throw new Error(`unsupported dependency entry: ${rel}`);
  }
  if (existsSync(NODE_MODULES)) walk(NODE_MODULES);
  return entries;
}

function repairDeps() {
  let missing = missingPackages(PKG_ROOT);
  if (missing !== null && missing.length === 0) return; // hot path — tree matches the lockfile
  if (missing === null) {
    if (!existsSync(PKG_JSON)) {
      throw new Error(
        `[bootstrap] FATAL: package.json missing at ${PKG_JSON}; cannot self-install. ` +
        `Reinstall the plugin.\n`
      );
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
      throw new Error(
        `[bootstrap] FATAL: node_modules still incomplete after a FRESH install. ` +
        `Missing vs lockfile: ${missing.join(", ")}\n` +
        `[bootstrap] Manually run: cd ${PKG_ROOT} && rm -rf node_modules && npm install --production\n`
      );
    }
  }
  // Dependency repair owns only the external runtime, never client auth state.
  process.stderr.write(`[bootstrap] npm install OK — starting server\n`);
}

try {
  PKG_ROOT = materializeRuntime();
  PKG_JSON = join(PKG_ROOT, "package.json");
  NODE_MODULES = join(PKG_ROOT, "node_modules");
  INSTALL_LOCK = join(PKG_ROOT, ".bootstrap-install.lock");
  DEPS_SEAL = join(PKG_ROOT, ".bootstrap-deps.json");
  ensureDeps();
  if (sourceIdentity(dirname(PKG_ROOT), true) !== dirname(PKG_ROOT).split(sep).pop()) {
    throw new Error("runtime source changed during dependency repair");
  }
} catch (error) {
  const message = error.message;
  process.stderr.write(message.startsWith("[bootstrap] FATAL:")
    ? message : `[bootstrap] FATAL: ${message}\n`);
  process.exit(1);
}
await import(pathToFileURL(join(PKG_ROOT, "src", "index.js")).href);
