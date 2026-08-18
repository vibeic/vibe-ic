/**
 * src/devices/_registry.js — auto-discovery + auto-registration of
 * vendor-supplied device tools (scopes, FPGAs, logic analyzers, signal
 * generators, power supplies, ...).
 *
 * Plugin point: any vendor can drop a directory under `src/devices/<vendor>/`
 * containing a manifest.json + driver script, and at server-start time this
 * module will register every declared MCP tool against the running server.
 *
 * Hard rule: this module is the ONLY place that talks to `server.tool` for
 * device IO. Core EDA tools in src/index.js are untouched.
 *
 * Scanned layout:
 *   src/devices/
 *     _registry.js           ← this file (skipped — leading underscore)
 *     _shared/               ← shared Python helpers (skipped)
 *     README.md              ← top-level overview (skipped — not a dir)
 *     CONTRIBUTING.md        ← vendor guide       (skipped — not a dir)
 *     scope/keysight-scope/
 *       manifest.json        ← declares 1+ MCP tools
 *       driver.py            ← executable, JSON-stdin → JSON-stdout
 *       README.md            ← vendor-specific docs
 *       udev/*.rules         ← optional udev rules to ship to users
 *
 * Manifest schema (the only contract this registry enforces):
 *
 *   {
 *     "vendor":       "keysight",                          // required
 *     "device_class": "oscilloscope",                      // required
 *     "ivi_class":    "IviScope",                          // optional, IVI Foundation class name
 *     "supported_platforms": ["linux"],                    // optional, default ["linux"]
 *     "permissions":  ["require_group:plugdev"],           // optional, soft-warn only
 *     "tools": [                                           // required, ≥1
 *       {
 *         "name":        "device_scope_capture",          // required, MCP tool name
 *         "description": "Capture a window from the scope.", // required
 *         "driver":      "driver.py",                     // required, relative to vendor dir
 *         "tool_mode":   "capture",                       // optional, passed as --mode to driver
 *         "mode":        "hw",                            // optional, one of hw/sim/mock; default "hw"
 *         "timeout_sec": 60,                              // optional, default 60
 *         "schema": {                                     // required, JSON-Schema-lite
 *           "channel":   {"type":"integer","default":4,"description":"..."},
 *           "span_ms":   {"type":"number","default":50},
 *           "trigger":   {"type":"string","enum":["rising","falling"],"default":"falling"},
 *           "verbose":   {"type":"boolean","default":false,"optional":true}
 *         }
 *       }
 *     ],
 *     "resources": [                                       // v0.68 — optional
 *       {
 *         "name":        "current_setup",                 // required, short name
 *         "uri":         "scope://keysight-dso-x-3014t/current_setup", // required, URI
 *         "description": "Live read of scope setup via SCPI.", // required
 *         "driver":      "driver.py",                     // required, relative to vendor dir
 *         "tool_mode":   "read_state",                    // optional, passed as --mode
 *         "mime_type":   "application/json",              // optional, default "application/json"
 *         "timeout_sec": 10                               // optional, default 10
 *       }
 *     ]
 *   }
 *
 * Supported JSON-Schema-lite types: string, integer, number, boolean.
 * Modifiers: enum (string only), default, optional, description.
 * Anything else triggers a per-field warning and is treated as `string`.
 *
 * Resources vs tools (v0.68): `tools[]` are actions (side effects — arm a
 * capture, program an FPGA, send a test packet). `resources[]` are
 * read-only state the MCP client can fetch any time via URI (current
 * scope setup, last-programmed SOF hash, hidraw enumeration). Resources
 * have no input schema: the driver's `tool_mode` decides what state to
 * read, and the URI is how MCP clients reference it.
 */

import { readdirSync, statSync, readFileSync, existsSync } from "fs";
import { join, resolve, dirname } from "path";
import { fileURLToPath } from "url";
import { spawn, execSync } from "child_process";
import { delimiter as PATH_DELIM } from "path";
import { z } from "zod";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DEFAULT_TIMEOUT_SEC = 60;

// v0.68: resources (read-only state) default to a short timeout — they
// should be fast SCPI queries / hidraw reads / filesystem stats. Tool
// actions keep the 60 s default because they may arm a capture, program
// an FPGA, etc.
const DEFAULT_RESOURCE_TIMEOUT_SEC = 10;

// v0.68: URI convention for device resources. Format:
//   <category>://<vendor-device>/<resource-name>
// where each segment is lowercase ASCII, digits, `_` or `-`. We enforce
// this shape at manifest validation so MCP clients can pattern-match URIs
// by category (e.g. "all scope:// resources").
const RESOURCE_URI_RE = /^[a-z][a-z0-9_-]*:\/\/[a-z0-9_-]+\/[a-z0-9_-]+$/;

// v0.67: known IVI Foundation instrument classes. Warning-only — vendors
// may invent new class names as the IVI spec evolves; we want to surface
// typos (e.g. "IVIScope" vs "IviScope") without blocking registration.
const KNOWN_IVI_CLASSES = new Set([
  "IviScope", "IviDmm", "IviFgen", "IviDCPwr", "IviACPwr",
  "IviSpecAn", "IviRFSigGen", "IviSwtch", "IviPwrMeter", "IviCounter",
  "IviDigitizer",
]);

// v0.67: allowed values for the per-tool `mode` field (hw/sim/mock). A
// vendor-device may ship a `_hw` variant that talks to real silicon and a
// `_sim` variant that reads a pre-recorded CSV, etc.
const ALLOWED_TOOL_MODES_HWMIX = new Set(["hw", "sim", "mock"]);

// v0.67: allowed values for `supported_platforms[]`. Map to Node's
// process.platform tokens.
const ALLOWED_PLATFORMS = new Set(["linux", "darwin", "win32"]);

// v0.67: supported `permissions[]` prefix set. Anything else prints a
// warning but does not block registration.
const ALLOWED_PERMISSION_PREFIXES = [
  "require_group:", "require_binary:", "require_env:", "require_file:",
];

// ───────────────────────── JSON-Schema-lite → zod ─────────────────────────
function jsonFieldToZod(name, spec) {
  if (typeof spec !== "object" || spec === null) {
    console.error(`[devices] field '${name}': spec is not an object, defaulting to string`);
    return z.string();
  }
  let base;
  switch (spec.type) {
    case "string":
      base = (Array.isArray(spec.enum) && spec.enum.length > 0)
        ? z.enum(spec.enum)
        : z.string();
      break;
    case "integer":
      base = z.number().int();
      break;
    case "number":
      base = z.number();
      break;
    case "boolean":
      base = z.boolean();
      break;
    case "array": {
      // v1.6.18 Fix: support `{type:"array", items:{type:...}}`.
      // `items` is optional (default = z.any() to mirror JSON-Schema 'no items'
      // semantics), but recursing through jsonFieldToZod keeps the same
      // type/enum/description/default modifiers we already support.
      const itemSpec = (typeof spec.items === "object" && spec.items !== null)
        ? spec.items
        : { type: "string" };
      const itemZod = jsonFieldToZod(`${name}[*]`, itemSpec);
      base = z.array(itemZod);
      break;
    }
    default:
      console.error(`[devices] field '${name}': unsupported type '${spec.type}', defaulting to string`);
      base = z.string();
  }
  if (spec.description) base = base.describe(spec.description);
  if (Object.prototype.hasOwnProperty.call(spec, "default")) {
    base = base.default(spec.default);
  } else if (spec.optional) {
    base = base.optional();
  }
  return base;
}

function jsonSchemaToZod(schema) {
  const out = {};
  for (const [name, spec] of Object.entries(schema || {})) {
    out[name] = jsonFieldToZod(name, spec);
  }
  return out;
}

// ───────────────────────── Driver subprocess runner ───────────────────────
function runDriver(driverPath, toolMode, args, timeoutMs) {
  return new Promise((resolveP) => {
    const argv = [driverPath];
    if (toolMode) argv.push("--mode", toolMode);
    argv.push("--json-args", "-");
    const proc = spawn("python3", argv, {
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let killed = false;
    const t = setTimeout(() => {
      killed = true;
      try { proc.kill("SIGKILL"); } catch (_) {}
    }, timeoutMs);
    proc.stdout.on("data", (b) => { stdout += b.toString(); });
    proc.stderr.on("data", (b) => { stderr += b.toString(); });
    proc.on("error", (err) => {
      clearTimeout(t);
      resolveP({ exitCode: -1, stdout, stderr: stderr + `\nspawn error: ${err.message}`, killed });
    });
    proc.on("close", (code) => {
      clearTimeout(t);
      resolveP({ exitCode: code, stdout, stderr, killed });
    });
    try {
      proc.stdin.write(JSON.stringify(args || {}));
      proc.stdin.end();
    } catch (e) {
      // process may already be dead; close handler will fire
    }
  });
}

// ───────────────────────── Manifest discovery ─────────────────────────────
//
// v0.66 layout: two-level category/vendor-device structure.
//
//   src/devices/
//     <category>/                       — e.g. scope/, fpga/, tester/, camera/
//       <vendor-device>/                — e.g. keysight-scope/, terasic-de10lite/
//         manifest.json
//         driver.{py,sh,js}
//         ...
//
// The category folder lets browsing the tree surface device classes at
// a glance, and lets us keep multiple vendors offering the same class
// (e.g. rigol-scope + keysight-scope under scope/) side-by-side.
//
// Implementation: do a one-level-deep recursive walk. At each `entry`
// directly under `rootDir`, if entry itself has a manifest.json it's an
// old flat-layout vendor dir (we no longer ship any — memory rule
// "no backwards compat"); otherwise entry is a category dir, and we
// descend one more level to look for manifest.json under each
// sub-entry.
function discoverManifests(rootDir) {
  const manifests = [];
  let entries;
  try {
    entries = readdirSync(rootDir);
  } catch (e) {
    console.error(`[devices] cannot scan ${rootDir}: ${e.message}`);
    return manifests;
  }
  for (const entry of entries) {
    if (entry.startsWith("_") || entry.startsWith(".")) continue;
    const categoryDir = join(rootDir, entry);
    let catStat;
    try { catStat = statSync(categoryDir); } catch (_) { continue; }
    if (!catStat.isDirectory()) continue;

    // Descend into each category dir looking for vendor-device subdirs.
    let subs;
    try {
      subs = readdirSync(categoryDir);
    } catch (e) {
      console.error(`[devices] cannot scan ${categoryDir}: ${e.message}`);
      continue;
    }
    for (const sub of subs) {
      if (sub.startsWith("_") || sub.startsWith(".")) continue;
      const vendorDir = join(categoryDir, sub);
      let vStat;
      try { vStat = statSync(vendorDir); } catch (_) { continue; }
      if (!vStat.isDirectory()) continue;
      const manifestPath = join(vendorDir, "manifest.json");
      if (!existsSync(manifestPath)) continue;
      let raw;
      try {
        raw = readFileSync(manifestPath, "utf8");
      } catch (e) {
        console.error(`[devices] cannot read ${manifestPath}: ${e.message}`);
        continue;
      }
      let parsed;
      try {
        parsed = JSON.parse(raw);
      } catch (e) {
        console.error(`[devices] invalid JSON in ${manifestPath}: ${e.message}`);
        continue;
      }
      parsed.__category = entry;
      parsed.__dir = vendorDir;
      parsed.__path = manifestPath;
      manifests.push(parsed);
    }
  }
  return manifests;
}

function validateManifest(m) {
  const errs = [];
  if (typeof m.vendor !== "string" || !m.vendor) errs.push("missing string field 'vendor'");
  if (typeof m.device_class !== "string" || !m.device_class) errs.push("missing string field 'device_class'");
  if (!Array.isArray(m.tools) || m.tools.length === 0) errs.push("missing non-empty array 'tools'");
  if (Array.isArray(m.tools)) {
    m.tools.forEach((t, i) => {
      if (typeof t.name !== "string" || !t.name) errs.push(`tools[${i}].name missing`);
      if (typeof t.description !== "string" || !t.description) errs.push(`tools[${i}].description missing`);
      if (typeof t.driver !== "string" || !t.driver) errs.push(`tools[${i}].driver missing`);
      if (typeof t.schema !== "object" || t.schema === null) errs.push(`tools[${i}].schema missing/invalid`);
      // v0.67: per-tool `mode` is one of hw/sim/mock. Unknown = error.
      if (t.mode !== undefined) {
        if (typeof t.mode !== "string" || !ALLOWED_TOOL_MODES_HWMIX.has(t.mode)) {
          errs.push(
            `tools[${i}].mode must be one of ${Array.from(ALLOWED_TOOL_MODES_HWMIX).join("/")} ` +
            `(got: ${JSON.stringify(t.mode)})`
          );
        }
      }
      // v0.67: `timeout_sec` must be a positive number if present. We
      // intentionally DO NOT accept `timeout_ms` any more — hard rename
      // (memory rule: no backwards-compat aliases).
      if (t.timeout_sec !== undefined) {
        if (typeof t.timeout_sec !== "number" || !(t.timeout_sec > 0)) {
          errs.push(`tools[${i}].timeout_sec must be a positive number (got: ${t.timeout_sec})`);
        }
      }
      if (t.timeout_ms !== undefined) {
        errs.push(
          `tools[${i}].timeout_ms is no longer supported — rename to timeout_sec ` +
          `(value should be seconds, not milliseconds)`
        );
      }
    });
  }
  // v0.68: resources[] — optional top-level array, mirrors tools[].
  if (m.resources !== undefined) {
    if (!Array.isArray(m.resources)) {
      errs.push("optional 'resources' must be an array");
    } else {
      m.resources.forEach((r, i) => {
        if (typeof r.name !== "string" || !r.name) {
          errs.push(`resources[${i}].name missing`);
        }
        if (typeof r.uri !== "string" || !r.uri) {
          errs.push(`resources[${i}].uri missing`);
        } else if (!RESOURCE_URI_RE.test(r.uri)) {
          errs.push(
            `resources[${i}].uri '${r.uri}' must match ` +
            `<category>://<vendor-device>/<name> ` +
            `(lowercase ASCII + digits + _ or -)`
          );
        }
        if (typeof r.description !== "string" || !r.description) {
          errs.push(`resources[${i}].description missing`);
        }
        if (typeof r.driver !== "string" || !r.driver) {
          errs.push(`resources[${i}].driver missing`);
        }
        if (typeof r.tool_mode !== "string" || !r.tool_mode) {
          errs.push(`resources[${i}].tool_mode missing (required for resources)`);
        }
        if (r.mime_type !== undefined && typeof r.mime_type !== "string") {
          errs.push(`resources[${i}].mime_type must be a string`);
        }
        if (r.timeout_sec !== undefined) {
          if (typeof r.timeout_sec !== "number" || !(r.timeout_sec > 0)) {
            errs.push(
              `resources[${i}].timeout_sec must be a positive number ` +
              `(got: ${r.timeout_sec})`
            );
          }
        }
      });
    }
  }

  // Optional vendor metadata. If present, validate format so a typo in the
  // homepage doesn't ship to MCP clients unnoticed.
  if (m.vendor_full_name !== undefined && typeof m.vendor_full_name !== "string") {
    errs.push("optional 'vendor_full_name' must be a string");
  }
  if (m.vendor_homepage !== undefined) {
    if (typeof m.vendor_homepage !== "string") {
      errs.push("optional 'vendor_homepage' must be a string");
    } else if (!/^https?:\/\/[^\s]+$/.test(m.vendor_homepage)) {
      errs.push(`optional 'vendor_homepage' must be http(s):// URL (got: ${m.vendor_homepage})`);
    }
  }
  // v0.67: ivi_class — warning only (unknown name is not fatal).
  if (m.ivi_class !== undefined) {
    if (typeof m.ivi_class !== "string") {
      errs.push("optional 'ivi_class' must be a string");
    } else if (!KNOWN_IVI_CLASSES.has(m.ivi_class)) {
      // Warning only — we don't push to errs[]. But surface it loudly.
      console.error(
        `[devices] NOTE ${m.__path || m.vendor}: ivi_class '${m.ivi_class}' is not in ` +
        `the known IVI list (typo? new class?). Registration proceeds.`
      );
    }
  }
  // v0.67: supported_platforms — unknown entry is ERROR.
  if (m.supported_platforms !== undefined) {
    if (!Array.isArray(m.supported_platforms) || m.supported_platforms.length === 0) {
      errs.push("optional 'supported_platforms' must be a non-empty array of strings");
    } else {
      for (const p of m.supported_platforms) {
        if (typeof p !== "string" || !ALLOWED_PLATFORMS.has(p)) {
          errs.push(
            `supported_platforms entry '${p}' not in ` +
            `${Array.from(ALLOWED_PLATFORMS).join("/")}`
          );
        }
      }
    }
  }
  // v0.67: permissions — warn on unknown prefix, don't block.
  if (m.permissions !== undefined) {
    if (!Array.isArray(m.permissions)) {
      errs.push("optional 'permissions' must be an array of strings");
    } else {
      for (const perm of m.permissions) {
        if (typeof perm !== "string") {
          errs.push(`permissions entry must be string (got: ${JSON.stringify(perm)})`);
          continue;
        }
        const recognised = ALLOWED_PERMISSION_PREFIXES.some((pfx) => perm.startsWith(pfx));
        if (!recognised) {
          console.error(
            `[devices] NOTE ${m.__path || m.vendor}: permission '${perm}' has no ` +
            `recognised prefix (${ALLOWED_PERMISSION_PREFIXES.join(", ")}). Ignored.`
          );
        }
      }
    }
  }
  return errs;
}

// ───────────────────────── v0.67 permission evaluators ────────────────────
function _currentUnixGroups() {
  try {
    return execSync("id -nG", { stdio: ["ignore", "pipe", "ignore"] })
      .toString()
      .trim()
      .split(/\s+/);
  } catch (_) {
    return [];
  }
}

function _whichBinary(name) {
  // Replicates Python shutil.which semantics against $PATH plus a
  // common vendor-tool fallback: $<NAME>_ROOTDIR/bin/<name>. The
  // latter is used for Quartus (QUARTUS_ROOTDIR) and similar.
  const paths = (process.env.PATH || "").split(PATH_DELIM);
  for (const p of paths) {
    if (!p) continue;
    const cand = join(p, name);
    if (existsSync(cand)) return cand;
  }
  // Vendor-root fallback — e.g. QUARTUS_ROOTDIR/bin/quartus_pgm.
  const rootEnv = `${name.toUpperCase()}_ROOTDIR`;
  if (process.env[rootEnv]) {
    const cand = join(process.env[rootEnv], "bin", name);
    if (existsSync(cand)) return cand;
  }
  // `quartus_pgm` → try `QUARTUS_ROOTDIR` (strip trailing _*).
  const m = name.match(/^([a-z0-9]+)_/i);
  if (m) {
    const altRoot = `${m[1].toUpperCase()}_ROOTDIR`;
    if (process.env[altRoot]) {
      const cand = join(process.env[altRoot], "bin", name);
      if (existsSync(cand)) return cand;
    }
  }
  return null;
}

// v1.6.18 Fix 1 — many EDA binaries (quartus_pgm, magic, klayout, …) live
// inside the iic-osic-tools Docker container declared via $EDA_CONTAINER,
// not on the host. Treat that as a satisfied `require_binary:` so we don't
// emit a misleading "not in PATH" NOTE for tools the runtime CAN actually
// execute (driver.py shells out to `docker exec $EDA_CONTAINER …`).
//
// Cache by (container, binary) so we don't re-spawn `docker exec` on every
// permission check.
const _CONTAINER_BINARY_CACHE = new Map();
function _binaryInContainer(binName) {
  const container = process.env.EDA_CONTAINER;
  if (!container) return null;
  const key = `${container}::${binName}`;
  if (_CONTAINER_BINARY_CACHE.has(key)) return _CONTAINER_BINARY_CACHE.get(key);
  let path = null;
  try {
    // 1.5 s probe; if docker is absent / container down / binary missing
    // we treat as "no fallback" and fall through to the host-PATH NOTE.
    const out = execSync(
      `docker exec ${container} sh -c 'command -v ${binName}'`,
      { stdio: ["ignore", "pipe", "ignore"], timeout: 1500, encoding: "utf-8" }
    ).trim();
    if (out) path = `${container}:${out}`;
  } catch (_) {
    path = null;
  }
  _CONTAINER_BINARY_CACHE.set(key, path);
  return path;
}

function evaluatePermission(perm) {
  // Returns {ok, detail}. `ok=true` = satisfied. `ok=false` means the
  // perm was understood but not satisfied; the caller logs a NOTE but
  // registers the tool anyway (per v0.67 spec: permissions are for MCP
  // discoverability, not gatekeeping).
  if (perm.startsWith("require_group:")) {
    const want = perm.slice("require_group:".length);
    const groups = _currentUnixGroups();
    return { ok: groups.includes(want), detail: `groups=${groups.join(",")}` };
  }
  if (perm.startsWith("require_binary:")) {
    const want = perm.slice("require_binary:".length);
    const hit = _whichBinary(want);
    if (hit !== null) return { ok: true, detail: `found at ${hit}` };
    // v1.6.18 Fix 1 — fall through to the EDA_CONTAINER (Docker) probe so
    // tools served by the iic-osic-tools image don't emit a noisy
    // "not in PATH" NOTE on hosts that intentionally don't ship Quartus.
    const inCtr = _binaryInContainer(want);
    if (inCtr !== null) return { ok: true, detail: `found in container at ${inCtr}` };
    const ctrSuffix = process.env.EDA_CONTAINER
      ? ` and not in container '${process.env.EDA_CONTAINER}'`
      : "";
    return { ok: false, detail: `not in PATH${ctrSuffix}` };
  }
  if (perm.startsWith("require_env:")) {
    const want = perm.slice("require_env:".length);
    const val = process.env[want];
    return { ok: val !== undefined && val !== "", detail: val ? "set" : "unset" };
  }
  if (perm.startsWith("require_file:")) {
    const want = perm.slice("require_file:".length);
    return { ok: existsSync(want), detail: existsSync(want) ? "present" : "missing" };
  }
  // Unknown prefix — already warned in validateManifest.
  return { ok: true, detail: "unrecognised permission prefix (no-op)" };
}

// ───────────────────────── Public entry point ─────────────────────────────
export async function registerDevices(server, options = {}) {
  const rootDir = options.rootDir || __dirname;
  const manifests = discoverManifests(rootDir);
  let toolsRegistered = 0;
  let resourcesRegistered = 0;
  let manifestsAccepted = 0;
  let manifestsSkipped = 0;

  // v0.68: detect which resource-registration entry point the current
  // MCP SDK exposes. Prefer the newer `registerResource(name, uri,
  // config, handler)`; fall back to `resource(name, uri, metadata,
  // handler)`. If neither exists, resources are silently skipped and
  // we log once — the server still boots so tools keep working.
  let registerResourceFn = null;
  if (typeof server.registerResource === "function") {
    registerResourceFn = (n, u, meta, h) => server.registerResource(n, u, meta, h);
  } else if (typeof server.resource === "function") {
    registerResourceFn = (n, u, meta, h) => server.resource(n, u, meta, h);
  }

  for (const m of manifests) {
    const errs = validateManifest(m);
    if (errs.length) {
      console.error(`[devices] SKIP ${m.__path} — ${errs.join("; ")}`);
      continue;
    }

    // v0.67: platform filter. Drivers declaring supported_platforms
    // that excludes the current OS are skipped silently (not an error).
    const supported = Array.isArray(m.supported_platforms) && m.supported_platforms.length > 0
      ? m.supported_platforms
      : ["linux"]; // default
    if (!supported.includes(process.platform)) {
      console.error(
        `[devices] SKIP ${m.__category}/${m.vendor} — platform ${process.platform} ` +
        `not in ${JSON.stringify(supported)}`
      );
      manifestsSkipped++;
      continue;
    }

    // v0.67: permissions pre-check. Unmet permissions print a NOTE but
    // do NOT block registration — the driver itself surfaces the real
    // error when the MCP client invokes it. The list is for
    // discoverability: MCP clients can filter "tools the user can
    // actually use" by reading manifest.permissions.
    if (Array.isArray(m.permissions)) {
      for (const perm of m.permissions) {
        const { ok, detail } = evaluatePermission(perm);
        if (!ok) {
          console.error(
            `[devices] NOTE ${m.__category}/${m.vendor} declares ${perm} — ` +
            `not satisfied (${detail}); tool will still register but may fail ` +
            `at invocation time`
          );
        }
      }
    }

    manifestsAccepted++;
    // Compose vendor attribution string. Display = vendor_full_name when
    // present (e.g. "Keysight Technologies"); falls back to the slug
    // ("keysight"). Homepage URL is appended if present so MCP clients
    // see "by Keysight Technologies <https://www.keysight.com/>" in
    // the tool description.
    const vendorDisplay = m.vendor_full_name || m.vendor;
    const vendorTag = m.vendor_homepage
      ? `${vendorDisplay} <${m.vendor_homepage}>`
      : vendorDisplay;
    for (const tool of m.tools) {
      const driverPath = resolve(m.__dir, tool.driver);
      if (!existsSync(driverPath)) {
        console.error(`[devices] SKIP tool '${tool.name}' — driver not found at ${driverPath}`);
        continue;
      }
      const zodSchema = jsonSchemaToZod(tool.schema);
      // v0.67: timeout_sec is authoritative; no timeout_ms fallback.
      const timeoutSec = Number.isFinite(tool.timeout_sec) ? tool.timeout_sec : DEFAULT_TIMEOUT_SEC;
      const timeoutMs = timeoutSec * 1000;
      // Driver dispatch keyword (passed as --mode to the subprocess).
      // Was `mode` pre-v0.67; renamed to `tool_mode` so `mode` can
      // carry the hw/sim/mock semantic.
      const toolMode = tool.tool_mode || null;
      const desc = `[${m.device_class} · by ${vendorTag}] ${tool.description}`;

      try {
        server.tool(tool.name, desc, zodSchema, async (args) => {
          const res = await runDriver(driverPath, toolMode, args, timeoutMs);
          // Try to parse driver stdout as JSON; if not, wrap as error body.
          let body;
          try {
            body = JSON.parse(res.stdout);
            if (typeof body !== "object" || body === null) throw new Error("driver returned non-object JSON");
          } catch (e) {
            body = {
              success: false,
              error: "driver produced non-JSON stdout",
              parse_error: e.message,
              exit_code: res.exitCode,
              stdout: res.stdout.slice(-2000),
              stderr: res.stderr.slice(-2000),
            };
          }
          if (res.killed) {
            body = {
              ...body,
              success: false,
              error: body.error || `driver killed after ${timeoutMs}ms timeout`,
              timeout_ms: timeoutMs,
            };
          } else if (res.exitCode !== 0 && body.success !== false) {
            // Non-zero exit but body looked OK — flip the success flag so
            // MCP clients can act on it.
            body = { ...body, success: false, exit_code: res.exitCode };
          }
          return { content: [{ type: "text", text: JSON.stringify(body) }] };
        });
        toolsRegistered++;
      } catch (e) {
        console.error(`[devices] FAIL register '${tool.name}': ${e.message}`);
      }
    }

    // v0.68: resources (read-only state) — optional per manifest.
    if (Array.isArray(m.resources) && m.resources.length > 0) {
      if (registerResourceFn === null) {
        console.error(
          `[devices] NOTE ${m.__category}/${m.vendor} declares ` +
          `${m.resources.length} resource(s) but MCP SDK exposes neither ` +
          `server.registerResource nor server.resource — skipping`
        );
      } else {
        for (const resource of m.resources) {
          const driverPath = resolve(m.__dir, resource.driver);
          if (!existsSync(driverPath)) {
            console.error(
              `[devices] SKIP resource '${resource.name}' — ` +
              `driver not found at ${driverPath}`
            );
            continue;
          }
          const timeoutSec = Number.isFinite(resource.timeout_sec)
            ? resource.timeout_sec
            : DEFAULT_RESOURCE_TIMEOUT_SEC;
          const timeoutMs = timeoutSec * 1000;
          const mimeType = resource.mime_type || "application/json";
          const toolMode = resource.tool_mode;
          const composedDesc = `[${m.device_class} · by ${vendorTag}] ${resource.description}`;

          try {
            registerResourceFn(
              resource.name,
              resource.uri,
              { description: composedDesc, mimeType },
              async (uri) => {
                const res = await runDriver(driverPath, toolMode, {}, timeoutMs);
                let body;
                try {
                  body = JSON.parse(res.stdout);
                  if (typeof body !== "object" || body === null) {
                    throw new Error("driver returned non-object JSON");
                  }
                } catch (e) {
                  body = {
                    success: false,
                    error: "driver produced non-JSON stdout",
                    parse_error: e.message,
                    exit_code: res.exitCode,
                    stdout: res.stdout.slice(-2000),
                    stderr: res.stderr.slice(-2000),
                  };
                }
                if (res.killed) {
                  body = {
                    ...body,
                    success: false,
                    error: body.error || `driver killed after ${timeoutMs}ms timeout`,
                    timeout_ms: timeoutMs,
                  };
                } else if (res.exitCode !== 0 && body.success !== false) {
                  body = { ...body, success: false, exit_code: res.exitCode };
                }
                // `uri` is the URL object the SDK passes to the handler;
                // `.href` is the stable string form we echo back.
                const uriStr = uri && typeof uri === "object" && "href" in uri
                  ? uri.href
                  : (typeof uri === "string" ? uri : resource.uri);
                return {
                  contents: [{
                    uri: uriStr,
                    mimeType,
                    text: JSON.stringify(body, null, 2),
                  }],
                };
              },
            );
            resourcesRegistered++;
          } catch (e) {
            console.error(
              `[devices] FAIL register resource '${resource.name}': ${e.message}`
            );
          }
        }
      }
    }
  }

  // eda_device_list — introspection tool: returns all discovered devices,
  // their tools, resources, permissions status, and vendor info.
  try {
    server.tool(
      "eda_device_list",
      "List all available device tools and resources registered by the MCP EDA Server. " +
      "Returns vendor info, device class, tools, resources, platform compatibility, " +
      "and permission status for each discovered device manifest.",
      {
        category: z.string().optional().describe(
          "Filter by device category (e.g. 'scope', 'fpga', 'tester'). Omit to list all."
        ),
        verbose: z.boolean().default(false).describe(
          "Include per-tool input schema and per-resource URI details."
        ),
      },
      async (args) => {
        const freshManifests = discoverManifests(rootDir);
        const devices = [];
        for (const m of freshManifests) {
          const errs = validateManifest(m);
          if (errs.length) continue;

          const supported = Array.isArray(m.supported_platforms) && m.supported_platforms.length > 0
            ? m.supported_platforms
            : ["linux"];
          const platformOk = supported.includes(process.platform);

          if (args.category && m.__category !== args.category) continue;

          const permResults = [];
          if (Array.isArray(m.permissions)) {
            for (const perm of m.permissions) {
              const { ok, detail } = evaluatePermission(perm);
              permResults.push({ permission: perm, satisfied: ok, detail });
            }
          }

          const toolList = (m.tools || []).map((t) => {
            const entry = {
              name: t.name,
              description: t.description,
              mode: t.mode || "hw",
              timeout_sec: t.timeout_sec || DEFAULT_TIMEOUT_SEC,
            };
            if (args.verbose && t.schema) {
              entry.input_schema = Object.fromEntries(
                Object.entries(t.schema).map(([k, v]) => [k, {
                  type: v.type,
                  ...(v.description ? { description: v.description } : {}),
                  ...(v.default !== undefined ? { default: v.default } : {}),
                  ...(v.enum ? { enum: v.enum } : {}),
                  ...(v.optional ? { optional: true } : {}),
                }])
              );
            }
            return entry;
          });

          const resourceList = (m.resources || []).map((r) => {
            const entry = {
              name: r.name,
              description: r.description,
            };
            if (args.verbose) {
              entry.uri = r.uri;
              entry.mime_type = r.mime_type || "application/json";
              entry.timeout_sec = r.timeout_sec || DEFAULT_RESOURCE_TIMEOUT_SEC;
            }
            return entry;
          });

          devices.push({
            category: m.__category,
            vendor: m.vendor,
            vendor_full_name: m.vendor_full_name || null,
            vendor_homepage: m.vendor_homepage || null,
            device_class: m.device_class,
            ivi_class: m.ivi_class || null,
            supported_platforms: supported,
            platform_compatible: platformOk,
            permissions: permResults.length > 0 ? permResults : undefined,
            tools: toolList,
            resources: resourceList.length > 0 ? resourceList : undefined,
          });
        }

        const summary = {
          total_devices: devices.length,
          total_tools: devices.reduce((s, d) => s + d.tools.length, 0),
          total_resources: devices.reduce((s, d) => s + (d.resources || []).length, 0),
          devices,
        };
        return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
      },
    );
    toolsRegistered++;
  } catch (e) {
    console.error(`[devices] FAIL register 'eda_device_list': ${e.message}`);
  }

  console.error(
    `[devices] registered ${toolsRegistered} tool(s) + ${resourcesRegistered} resource(s) ` +
    `from ${manifestsAccepted} manifest(s) under ${rootDir}` +
    (manifestsSkipped > 0 ? ` (${manifestsSkipped} skipped by platform)` : "")
  );
  return { toolsRegistered, resourcesRegistered, manifestsAccepted, manifestsSkipped };
}

// Exposed for unit tests.
export const __test = {
  jsonSchemaToZod,
  jsonFieldToZod,
  discoverManifests,
  validateManifest,
  evaluatePermission,
  KNOWN_IVI_CLASSES,
  ALLOWED_TOOL_MODES_HWMIX,
  ALLOWED_PLATFORMS,
  RESOURCE_URI_RE,
  DEFAULT_RESOURCE_TIMEOUT_SEC,
};
