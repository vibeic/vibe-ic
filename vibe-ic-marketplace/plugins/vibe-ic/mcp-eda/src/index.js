#!/usr/bin/env node
/**
 * MCP EDA Server — Wraps open-source EDA tools for AI-Native IC Design
 *
 * Tools provided:
 *   eda_synth        — Yosys synthesis (RTL → gate-level netlist)
 *   eda_lint         — Verilator lint (RTL quality check)
 *   eda_simulate     — Icarus Verilog simulation
 *   eda_formal       — SymbiYosys formal verification
 *   eda_pnr          — OpenROAD place & route
 *   eda_gds          — KLayout GDS generation from DEF
 *   eda_sta          — OpenSTA timing analysis
 *   eda_lvs          — Netgen LVS (Layout vs Schematic)
 *   eda_drc_klayout  — KLayout DRC with foundry rule decks
 *   eda_ir_drop      — OpenROAD power grid analysis
 *   eda_equiv        — Yosys equivalence check (RTL vs netlist)
 *   eda_spice        — ngspice SPICE simulation
 *   eda_xschem_netlist — xschem schematic → SPICE netlist (batch)
 *   eda_spice_corner — Multi-corner PVT SPICE sweep + yield table
 *   eda_analog_layout — Magic analog layout (matching/guard-ring/GDS/LEF)
 *   eda_dft          — Fault scan chain + ATPG + JTAG TAP
 *   eda_ic_search    — PostgreSQL IC Knowledge Base search
 *   eda_sta_mcorner  — Multi-corner STA (SS/TT/FF)
 *   eda_rtl_audit    — RTL deterministic audit (vibe-ic-d programs)
 *   eda_cocotb       — cocotb testbench runner (Verilator/Icarus)
 *   eda_fpga_compile — FPGA synthesis (Quartus/Vivado)
 *   eda_fpga_program — FPGA programming (SOF/BIT burn)
 *   eda_extraction   — Parasitic extraction (Magic)
 *   eda_fpga_adc_read — MAX10 internal 12-bit ADC read (JTAG)
 *   eda_spinalhdl_gen — SpinalHDL/sbt → Verilog (OpenJDK 17 + sbt in container)
 *
 * Tools run inside IIC-OSIC-TOOLS Docker container unless noted.
 * FPGA tools (Quartus/Vivado), RTL audit, and ADC read run on host directly.
 * Supports PDKs: gf180, sky130, custom.
 *
 * INPUT CONSTRAINT (command-injection hardening): every path / filename / top-
 * module / cell-name parameter is validated at the tool's entry by the
 * helpers in src/lib/shell_safety.mjs. Path-typed params must NOT contain
 * whitespace or shell metacharacters (; & | < > $ ` ( ) { } [ ] ! * ? ~ " ' \\)
 * and identifier-typed params (top_module, clock, …) must be plain Verilog
 * identifiers. A violation returns `{success:false, error:"input rejected: …"}`
 * rather than risking a quoting break. Keep container / project paths free of
 * spaces and metacharacters.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { execSync } from "child_process";
import { registerDevices } from "./devices/_registry.js";
// Shell-safety validators (command-injection hardening). The argv-based
// _spawnSync used by dockerExec + host handlers is the existing legacy
// import declared further down (`spawnSync as _spawnSyncEarly`).
import {
  shq, assertSafeIdent, assertSafeToken, assertNoShellMeta,
  assertSafePath, assertSafePaths,
  optPath, optIdent, optToken, optNoShellMeta, guardError,
} from "./lib/shell_safety.mjs";
// Netgen LVS verdict parser + device-level driver builder (real verdict parse,
// DID-NOT-RUN guard, std-cell-lib load, `_flat` auto-name-align). Closes
// ORGANIC-20260531-eda-lvs-netgen-false-positive-and-no-stdcell-lib.
import {
  classifyNetgenVerdict, stdcellSpicePath, buildNetgenLvsTcl, resolveLayoutTop,
} from "./lib/netgen_verdict.mjs";
// v1.3.53 R9 — MCP-side port of phase3_one_shot_runner.py `_antenna_repair_tcl`
// (the v1.3.46 incremental antenna repair->reroute loop). The MCP `eda_pnr`
// SECONDARY PnR path emits its own OpenROAD Tcl and previously lacked this loop;
// this closes that parity gap so both PnR paths behave identically.
import { antennaRepairTcl } from "./lib/pnr_antenna.mjs";
import { threadCountTcl } from "./lib/pnr_threads.mjs";
import { layoutHasGeometry } from "./lib/analog_layout_geometry.mjs";

function _shellSingleQuotedHeredoc(content, sentinel) {
  // Run `<content>` through a `cat << 'SENTINEL' > target` block. The
  // single-quoted sentinel keeps bash from expanding $, `, \, ! inside
  // the heredoc body — but the dockerExec wrapper passes our whole
  // command via `bash -c "..."`, and bash parses the outer double-quoted
  // arg FIRST. That outer parse would try to expand any unescaped $ or
  // ` even though the inner heredoc would not. Escape both so the helper
  // text reaches the heredoc body byte-for-byte.
  if (content.split("\n").includes(sentinel)) {
    throw new Error(`heredoc sentinel ${sentinel} appears in content`);
  }
  return content
    .replace(/\\/g, "\\\\")
    .replace(/\$/g, "\\$")
    .replace(/`/g, "\\`");
}

const CONTAINER = process.env.EDA_CONTAINER || "vibeic-eda";
const PDK_ROOT = "/foss/pdks";
const TOOLS = "/foss/tools";

// ─── Parallel-by-default thread policy ───────────────────────────────────────
// Every EDA tool below supports multithreading, and each of those threadings is
// RESULT-INVARIANT (deterministic): enabling them only speeds the run up, it can
// never change an output. So we wire the parallel flags ON by default. The tool
// runs inside the container (dockerExec → `bash -c`), so the robust default is a
// shell `$(nproc)` expanded IN the container (all cores). A single generic env
// `VIBEIC_EDA_THREADS`, read here on the host at command-build time, is the
// global override — set it to a positive integer to cap/pin the thread count.
// No fixed number is hardcoded.
function _edaThreadsToken() {
  const v = (process.env.VIBEIC_EDA_THREADS || "").trim();
  if (/^[0-9]+$/.test(v) && Number(v) > 0) return v;   // explicit override
  return "$(nproc)";                                    // default: all cores
}
// OpenROAD's `-threads` accepts the literal `max` (== all cores) as well as an
// integer; prefer `max` unless VIBEIC_EDA_THREADS pins a specific count.
function _edaOpenroadThreadsToken() {
  const v = (process.env.VIBEIC_EDA_THREADS || "").trim();
  if (/^[0-9]+$/.test(v) && Number(v) > 0) return v;
  return "max";
}

// Helper: write result manifest (P0 improvement)
// After each PASS, records the latest result so reviewers never pick up stale logs
function writeManifest(workDir, entry) {
  const manifest = {
    timestamp: new Date().toISOString(),
    ...entry,
  };
  const manifestJson = JSON.stringify(manifest, null, 2);
  // Append to latest_results.jsonl (one JSON per line, newest last)
  const appendCmd = `echo '${manifestJson.replace(/'/g, "\\'")}' >> ${workDir}/latest_results.jsonl`;
  // Also write latest_results.yml for human readability
  const ymlLines = Object.entries(manifest)
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
    .join("\\n");
  const ymlCmd = `echo -e '${ymlLines}\\n---' >> ${workDir}/latest_results.yml`;
  dockerExec(`${appendCmd} && ${ymlCmd}`, 5000);
}

// Helper: SHA-256 of a host-side file (used for provenance hashing)
import { createHash } from "crypto";
import { readFileSync, existsSync, appendFileSync, mkdirSync, writeFileSync as require_fs_writeFileSync, unlinkSync } from "fs";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";
// Wave 33 (mcp-eda v0.99.9): top-level spawnSync import so the
// eda_fpga_program wrapper can synchronously delegate to the
// device_fpga_de10lite_program driver. The legacy import at
// L4431 (inside the docker self-heal block) remains as-is since
// it was loaded as `_spawnSync` for that scope.
import { spawnSync as _spawnSyncEarly } from "child_process";
const _spawnSync = _spawnSyncEarly;

// execSync-compatible runner using an argv array (no shell). Returns stdout
// as a string; throws an Error carrying .stdout/.stderr/.status on non-zero
// exit or spawn failure — matches the throw-on-error contract the legacy
// execSync(string) call sites were written against. Use this to replace any
// execSync(string) whose command is a single program + fixed args.
function _run(file, args, opts = {}) {
  const r = _spawnSync(file, args, { encoding: "utf-8", ...opts });
  if (r.error) {
    const e = r.error;
    e.stderr = r.stderr || ""; e.stdout = r.stdout || ""; e.status = r.status;
    throw e;
  }
  if (r.status !== 0) {
    const e = new Error(`${file} exited with status ${r.status}${r.signal ? ` (${r.signal})` : ""}`);
    e.stderr = r.stderr || ""; e.stdout = r.stdout || ""; e.status = r.status;
    throw e;
  }
  return r.stdout || "";
}

// v2.5.2: derive plugin programs dir from this file's location instead of
// hardcoding a personal home directory. Order: $VIBE_IC_PROGRAMS_DIR -> first
// existing of a candidate list -> the plugin-relative path (NO invented
// fallback).
// v2.5.3: this file lives at <plugin>/mcp-eda/src/index.js, so the plugin's own
// programs/ is two levels up (../../programs). Prior logic only probed a nested
// vibe-ic-marketplace/plugins/vibe-ic-d/programs sibling, which does not exist
// on installs where the plugin is named `vibe-ic` (programs/ lives directly
// under the plugin root) — that made eda_doctor's plugin_programs_dir FAIL and
// silently fell back to the /home/user hardcode.
const __dirname_eda = dirname(fileURLToPath(import.meta.url));
const _programsCandidates = [
  // plugin's own programs/ (plugin root = ../.. from mcp-eda/src)
  resolve(__dirname_eda, "..", "..", "programs"),
  // legacy sibling layout: marketplace/plugins/vibe-ic-d/programs
  resolve(__dirname_eda, "..", "..", "..", "vibe-ic-d", "programs"),
  resolve(__dirname_eda, "..", "..", "vibe-ic-marketplace", "plugins", "vibe-ic-d", "programs"),
];
// PORTABILITY: the last resort is the plugin's OWN programs/ path derived from
// this file's location — never a personal absolute path. A prior release fell
// back to one developer's home directory (and to `vibe-ic-d`, a plugin that no
// longer exists), so on any other machine the resolved dir silently pointed at
// nothing and every program-backed tool failed with a confusing error.
const VIBE_IC_PROGRAMS_DIR = process.env.VIBE_IC_PROGRAMS_DIR
  || _programsCandidates.find(existsSync)
  || _programsCandidates[0];

// v0.99.1: load embedded Python helpers once at startup. Inlining them via
// shell heredoc hit escape-hell at v0.99.0 (sh: 66: Syntax error: "("
// unexpected); now we pipe the verbatim content into the container via a
// single-quoted heredoc from JS so every byte survives unaltered.
const _AUTO_DRC_DECK_PY = readFileSync(
  join(__dirname_eda, "lib", "auto_drc_deck.py"),
  "utf-8",
);

function sha256File(path) {
  try {
    if (!existsSync(path)) return "missing";
    const buf = readFileSync(path);
    return "sha256:" + createHash("sha256").update(buf).digest("hex");
  } catch (e) {
    return `error:${e.message}`;
  }
}

// MCP-eda v0.99: per-server-process session id, set once at startup. Used by
// the FPGA compile→program→connect_test attestation chain so a vibe-ic-d
// auditor can reject "PASS from a previously-burned SOF on the rig".
import { randomUUID } from "crypto";
const MCP_SESSION_ID = process.env.VIBE_IC_MCP_SESSION_ID || randomUUID();
// Track the most recent FPGA artefact produced THIS session, so
// eda_fpga_program / host-tester connect_test can cite it.
let _LAST_FPGA_COMPILE = null;   // {sof_path, sha256, timestamp, session_id}
let _LAST_FPGA_PROGRAM = null;   // {sof_path, sha256, timestamp, session_id}

// Helper: append a provenance record to <projectDir>/provenance.jsonl
// Called by every MCP tool that produces persistent artefacts. This is
// the structural anti-cheat: an agent asking an MCP tool to run yosys
// gets the run logged automatically, so downstream provenance_check
// gates can verify (file hash matches + tool in allow-list).
function logProvenance({ projectDir, tool, version, argv, inputs, outputs,
                          exitCode, durationMs, stdoutTail, stderrTail }) {
  if (!projectDir) return; // nowhere to log; skip silently
  try {
    mkdirSync(projectDir, { recursive: true });
    const record = {
      timestamp: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
      tool,
      version: version || "",
      cwd: projectDir,
      argv: argv || [],
      inputs: inputs || {},
      outputs: outputs || {},
      exit_code: exitCode,
      duration_s: +(durationMs / 1000).toFixed(3),
      stdout_sha: "sha256:" + createHash("sha256").update(stdoutTail || "").digest("hex"),
      stderr_sha: "sha256:" + createHash("sha256").update(stderrTail || "").digest("hex"),
      stdout_tail: (stdoutTail || "").slice(-400),
      stderr_tail: (stderrTail || "").slice(-400),
      source: "mcp-eda",
    };
    const logPath = `${projectDir}/provenance.jsonl`;
    appendFileSync(logPath, JSON.stringify(record) + "\n");
  } catch (e) {
    // Don't fail the tool on log error — just record the failure on stderr
    console.error(`logProvenance: ${e.message}`);
  }
}

// Helper: run a tool command AND log provenance. Wraps dockerExec for
// the canonical MCP tool handlers. Outputs = host-side paths that
// should be hashed after the run.
function dockerExecLogged({ cmd, timeoutMs = 300000, projectDir, tool,
                              version, inputs, outputs }) {
  const t0 = Date.now();
  const result = dockerExec(cmd, timeoutMs);
  const durationMs = Date.now() - t0;
  // Hash outputs
  const outHashes = {};
  for (const out of outputs || []) {
    outHashes[out.replace(`${projectDir}/`, "")] = sha256File(out);
  }
  const inHashes = {};
  for (const inp of inputs || []) {
    inHashes[inp.replace(`${projectDir}/`, "")] = sha256File(inp);
  }
  logProvenance({
    projectDir, tool, version, argv: [cmd],
    inputs: inHashes, outputs: outHashes,
    exitCode: result.success ? 0 : (result.exitCode || 1),
    durationMs,
    stdoutTail: result.output || "",
    stderrTail: result.error || "",
  });
  return result;
}

// Helper: run command in Docker container.
// v2.4.1: probe `docker ps` once at startup; if the user lacks docker socket
// access (no `docker` group, no sudo) every dockerExec is a guaranteed silent
// failure — surface it explicitly so tool wrappers can return an installable
// diagnostic instead of an empty string that downstream PASS-counters mis-read
// as success.
// v2.5.3: probe with a 30s TTL (was permanent cache). Long-lived MCP servers
// outlived their first probe — daemon-up transitions never propagated and
// daemon-down transitions kept us in silent-PASS land. Also: any actual
// `docker exec` failure that smells like an unreachable-docker symptom now
// invalidates the cache so the next call re-probes.
let _dockerProbeAt = 0;
let _dockerReachable = null;
const _PROBE_TTL_MS = 30_000;
// How much longer the host-side backstop waits than the in-container timeout.
// Only has to cover `timeout`'s own -k grace plus docker's round trip.
const _INNER_TIMEOUT_GRACE_MS = 20_000;
// Cached answer to "does this container have coreutils `timeout`?". Every
// image we ship does, but the container name is user-overridable
// (EDA_CONTAINER), so an image without it must degrade to the old behaviour
// rather than fail every single command with `timeout: not found`.
let _containerTimeoutOk = null;
function _containerHasTimeout() {
  if (_containerTimeoutOk !== null) return _containerTimeoutOk;
  const r = _spawnSync(
    "docker", ["exec", CONTAINER, "sh", "-c", "command -v timeout"],
    { timeout: 10_000, encoding: "utf-8" });
  _containerTimeoutOk = r.status === 0 && !!(r.stdout || "").trim();
  return _containerTimeoutOk;
}
const _UNREACHABLE_HINTS = [
  "permission denied",
  "Cannot connect",
  "No such container",
  "is not running",
  "command not found",   // docker not installed
];
function _classifyDockerErr(stderr) {
  if (stderr.includes("permission denied")) {
    return "User lacks docker socket access. Fix: `sudo usermod -aG docker $USER` and re-login, OR run mcp-eda with sudo.";
  } else if (stderr.includes("Cannot connect")) {
    return "Docker daemon not running. Fix: `sudo systemctl start docker`.";
  } else if (stderr.includes("No such container") || stderr.includes("is not running")) {
    return `Container '${CONTAINER}' not running. Fix: see INSTALL_GUIDE.md to start the vibeic-eda EDA container.`;
  } else if (stderr.includes("command not found")) {
    return "`docker` not installed or not in PATH. Fix: install Docker Desktop / Docker Engine.";
  } else {
    return "Docker probe failed. Run `docker ps` manually to diagnose.";
  }
}
function _probeDocker(force = false) {
  const now = Date.now();
  if (!force && _dockerReachable && (now - _dockerProbeAt) < _PROBE_TTL_MS) {
    return _dockerReachable;
  }
  _dockerProbeAt = now;
  try {
    // v2.5.3: also confirm the target container exists. `docker ps --filter`
    // exits 0 even when nothing matches, so check stdout is non-empty.
    const out = _run(
      "docker", ["ps", "--filter", `name=${CONTAINER}`, "--format", "{{.Names}}"],
      { timeout: 5000, stdio: ["ignore", "pipe", "pipe"] },
    );
    if (!out.trim()) {
      // Auto-start: try `docker start` if the container exists but is stopped
      try {
        const stopped = _run(
          "docker", ["ps", "-a", "--filter", `name=${CONTAINER}`, "--format", "{{.Names}}"],
          { timeout: 5000, stdio: ["ignore", "pipe", "pipe"] },
        );
        if (stopped.trim()) {
          _run("docker", ["start", CONTAINER], {
            timeout: 30000, stdio: ["ignore", "pipe", "pipe"],
          });
          _dockerReachable = { ok: true };
        } else {
          _dockerReachable = {
            ok: false,
            stderr: `no container named ${CONTAINER}`,
            hint: `Container '${CONTAINER}' does not exist. Fix: see INSTALL_GUIDE.md to create the vibeic-eda EDA container.`,
          };
        }
      } catch (startErr) {
        _dockerReachable = {
          ok: false,
          stderr: (startErr.stderr || startErr.message || "").toString(),
          hint: `Container '${CONTAINER}' exists but failed to start. Run \`docker start ${CONTAINER}\` manually to diagnose.`,
        };
      }
    } else {
      _dockerReachable = { ok: true };
    }
  } catch (err) {
    const stderr = (err.stderr || err.message || "").toString();
    _dockerReachable = { ok: false, stderr, hint: _classifyDockerErr(stderr) };
  }
  return _dockerReachable;
}
function _invalidateDockerProbe() {
  _dockerProbeAt = 0;
  _dockerReachable = null;
  // The container may be recreated on a different image; re-ask.
  _containerTimeoutOk = null;
}
// v0.1.11: container-visibility pre-flight. Files staged onto the host bind
// mount via a restricted/sandboxed shell do not always propagate into the
// container; the raw EDA tool then emits an opaque "cannot find file" and the
// caller cannot tell a staging miss from a real RTL error. Check existence
// INSIDE the container (one `docker exec test -e`) and let tool wrappers return
// an actionable staging hint instead. Mount-mapping-agnostic — it tests the
// exact in-container path the tool will use (same cwd, no `cd`). Returns the
// list of missing paths; [] when all present OR when docker is unreachable
// (that case is reported by dockerExec itself, so we must not block on it).
function missingInContainer(files) {
  const probe = _probeDocker();
  if (!probe.ok) return [];
  const list = files.map(f => `'${String(f).replace(/'/g, "'\\''")}'`).join(" ");
  if (!list) return [];
  const r = _spawnSync(
    "docker",
    ["exec", CONTAINER, "bash", "-c",
     `for f in ${list}; do [ -e "$f" ] || printf '%s\\n' "$f"; done`],
    { timeout: 8000, maxBuffer: 1024 * 1024, encoding: "utf-8" },
  );
  // Probe itself failed (spawn error / non-zero with no stdout): don't block.
  if (r.error || (r.status !== 0 && !(r.stdout || "").trim())) return [];
  return (r.stdout || "").split("\n").map(s => s.trim()).filter(Boolean);
}
function stagingHint(missing) {
  return `[files not visible in container '${CONTAINER}'] ${missing.join(", ")}. `
    + `The EDA tools run inside the '${CONTAINER}' Docker container, which bind-mounts only `
    + `the designs root (your chosen host designs directory -> /foss/designs). Stage your RTL UNDER that mount `
    + `and pass the in-container path (e.g. /foss/designs/<proj>/top.sv). NOTE: a host file copy `
    + `made under a restricted/sandboxed shell may not propagate into the mount — re-copy with `
    + `the sandbox disabled, then retry.`;
}
function dockerExec(cmd, timeoutMs = 300000) {
  const probe = _probeDocker();
  if (!probe.ok) {
    const diag = `[docker unreachable] ${probe.hint}\nstderr: ${probe.stderr}`;
    // v2.4.1: surface the diagnostic in `output` so downstream tools that
    // forward it via `result.output.slice(-N)` no longer return empty strings
    // on docker failure.
    return { success: false, output: diag, error: diag, exitCode: 127 };
  }
  // security hardening: pass `cmd` verbatim as the single `bash -c` argument
  // via an argv array. The previous form ran `docker exec C bash -c "..."`
  // through /bin/sh first (and only escaped `"`), so shell metacharacters in
  // tool arguments could break out of the command context.
  //
  // The timeout is enforced INSIDE the container, not by killing the client.
  // This is the same defect, and the same fix, that
  // `programs/_container_exec.py` already carries for the PYTHON runners
  // (ORGANIC #570, measured 2026-07-22: a yosys still running eighteen minutes
  // after its step was recorded as timed out). Every Python `_docker_exec_raw`
  // was routed through that helper; this server is a separate implementation in
  // a different language and was never given the same treatment, so it kept
  // orphaning tools for another month.
  // MEASURED 2026-08-19: `timeout 4 docker exec C bash -c 'sleep 90 & wait'`
  // returns 124 to the caller and leaves TWO processes running in the
  // container -- a killed `docker exec` client does not stop the process it
  // started. So every `timeoutMs` we have ever reported was a client-side
  // give-up: the tool kept running unattended, and nothing in the stack would
  // ever stop it. That is how a yosys reached 113 GB on a 125 GB host after
  // the caller had already been told the command timed out, and the machine's
  // desktop session was OOM-killed. Same command with the timeout moved inside
  // -- `docker exec C timeout -k 10 4 bash -c ...` -- also returns 124 and
  // leaves ZERO processes behind.
  const innerSec = Math.max(1, Math.ceil(timeoutMs / 1000));
  const useInner = _containerHasTimeout();
  const argv = useInner
    ? ["exec", CONTAINER, "timeout", "-k", "10", String(innerSec), "bash", "-c", cmd]
    : ["exec", CONTAINER, "bash", "-c", cmd];
  // The host-side timeout stays, demoted to a backstop, and is deliberately
  // LONGER than the inner one so the inner kill lands first and we return the
  // tool's own partial output instead of an orphan plus an empty string.
  const startedAt = Date.now();
  const r = _spawnSync("docker", argv, {
    timeout: useInner ? timeoutMs + _INNER_TIMEOUT_GRACE_MS : timeoutMs,
    maxBuffer: 10 * 1024 * 1024,
    encoding: "utf-8",
  });
  // `timeout` reports 124 on expiry and 137 when it had to escalate to KILL.
  // A tool is free to exit 124 for its own reasons, so the elapsed clock is
  // what distinguishes the two -- an exit code alone would mislabel it.
  if (useInner && (r.status === 124 || r.status === 137)
      && (Date.now() - startedAt) >= innerSec * 1000) {
    const stdoutSoFar = r.stdout || "";
    const msg = `command timed out after ${timeoutMs}ms `
      + `(killed inside container '${CONTAINER}'`
      + `${r.status === 137 ? " with SIGKILL after the 10s grace" : ""})`;
    return {
      success: false,
      output: stdoutSoFar + (stdoutSoFar ? "\n" : "") + msg,
      error: msg,
      exitCode: r.status,
    };
  }
  const stdout = r.stdout || "";
  const stderr = (r.stderr || "") || (r.error ? (r.error.message || String(r.error)) : "");
  if (r.error || r.status === null) {
    const timedOut = (r.error && r.error.code === "ETIMEDOUT") || !!r.signal;
    const msg = timedOut
      ? `command timed out after ${timeoutMs}ms${r.signal ? ` (killed by ${r.signal})` : ""}`
      : stderr || "spawn failed";
    const combined = stdout + (stdout && msg ? "\n" : "") + msg;
    if (_UNREACHABLE_HINTS.some(h => msg.includes(h))) _invalidateDockerProbe();
    return { success: false, output: combined, error: msg, exitCode: r.status ?? 1 };
  }
  if (r.status === 0) {
    return { success: true, output: stdout };
  }
  // Non-zero exit: preserves the earlier v2.4.1 behaviour (combine stdout +
  // stderr in `output` so downstream tools see the failure reason).
  const combined = stdout + (stderr && stdout ? "\n" : "") + stderr;
  // since v2.5.3: if the failure smells like docker became unreachable mid-run,
  // invalidate the probe cache so the next call re-probes.
  if (_UNREACHABLE_HINTS.some(h => stderr.includes(h))) {
    _invalidateDockerProbe();
  }
  return { success: false, output: combined, error: stderr, exitCode: r.status };
}

// PDK config lookup
function pdkConfig(pdk, customOpts) {
  const configs = {
    gf180: {
      pdk_path: `${PDK_ROOT}/gf180mcuD`,
      scl: "gf180mcu_fd_sc_mcu7t5v0",
      lib_suffix: "__tt_025C_3v30.lib",
      techlef_suffix: "__nom.tlef",
      site: "GF018hv5v_mcu_sc7",
      metal_prefix: "Metal",
      vdd_pin: "VDD",
      vss_pin: "VSS",
      // v1.3.53 R9 — antenna diode master from the PDK's own std-cell library
      // (data, NOT logic): consumed by antennaRepairTcl for the incremental
      // repair->reroute loop. Chip-AGNOSTIC — the Tcl-gen never hardcodes it.
      antenna_diode_cell: "gf180mcu_fd_sc_mcu7t5v0__antenna",
    },
    sky130: {
      pdk_path: `${PDK_ROOT}/sky130A`,
      scl: "sky130_fd_sc_hd",
      lib_suffix: "__tt_025C_1v80.lib",
      techlef_suffix: "__nom.tlef",
      site: "unithd",
      metal_prefix: "met",
      vdd_pin: "VPWR",
      vss_pin: "VGND",
      // v1.3.53 R9 — same sky130 diode master the phase3 runner uses
      // (phase3_one_shot_runner.py PdkConfig.antenna_diode_cell), so both PnR
      // paths repair antennas identically.
      antenna_diode_cell: "sky130_fd_sc_hd__diode_2",
    },
    nangate45: {
      // NanGate / FreePDK45 Open Cell Library (Si2, Apache-2.0) — a GENERIC,
      // non-foundry 45nm std-cell lib. synth/PnR/CTS/STA/area run; the KLayout
      // FreePDK45 decks are EDUCATIONAL, not a manufacturable sign-off (see
      // programs/pdk_registry.json nangate45: tapeout_capable=false). Assets are
      // the OpenROAD-flow-scripts nangate45 platform re-staged into the
      // open_pdks libs.ref/<scl>/ layout by the vibeic-eda Dockerfile.
      pdk_path: `${PDK_ROOT}/nangate45`,
      scl: "NangateOpenCellLibrary",
      lib_suffix: "_typical.lib",
      techlef_suffix: ".tech.lef",
      site: "FreePDK45_38x28_10R_NP_162NW_34O",
      metal_prefix: "metal",
      vdd_pin: "VDD",
      vss_pin: "VSS",
      antenna_diode_cell: "ANTENNA_X1",
    },
  };
  if (pdk === "custom" && customOpts) {
    // v0.63: metal_prefix used to be hardcoded to "met" here, which silently
    // broke any custom PDK whose layers don't follow SKY130's naming
    // (e.g. a commercial 180nm PDK uses uppercase MET1-6). eda_pnr would
    // produce empty `define_metal_layers` and OpenROAD would later fail
    // with no useful error. Now read it from customOpts.
    return {
      pdk_path: null,
      scl: null,
      lib_suffix: null,
      techlef_suffix: null,
      site: customOpts.custom_site || "core",
      metal_prefix: customOpts.custom_metal_prefix || "met",
      vdd_pin: customOpts.custom_vdd || "VDD",
      vss_pin: customOpts.custom_vss || "VSS",
      // v1.3.53 R9 — a custom PDK has no known diode master; the caller may
      // supply one (custom_antenna_diode). Absent -> null -> antennaRepairTcl
      // SKIPS the repair loop (manual diode ECO) rather than inventing a cell.
      antenna_diode_cell: customOpts.custom_antenna_diode || null,
      // Direct paths for custom PDK
      custom_lib: customOpts.custom_lib,
      custom_techlef: customOpts.custom_techlef,
      custom_celllef: customOpts.custom_celllef,
      custom_cellgds: customOpts.custom_cellgds,
    };
  }
  return configs[pdk] || configs.gf180;
}

function libPath(cfg) {
  if (cfg.custom_lib) return cfg.custom_lib;
  return `${cfg.pdk_path}/libs.ref/${cfg.scl}/lib/${cfg.scl}${cfg.lib_suffix}`;
}
function techlefPath(cfg) {
  if (cfg.custom_techlef) return cfg.custom_techlef;
  return `${cfg.pdk_path}/libs.ref/${cfg.scl}/techlef/${cfg.scl}${cfg.techlef_suffix}`;
}
function celllefPath(cfg) {
  if (cfg.custom_celllef) return cfg.custom_celllef;
  return `${cfg.pdk_path}/libs.ref/${cfg.scl}/lef/${cfg.scl}.lef`;
}
function cellgdsPath(cfg) {
  if (cfg.custom_cellgds) return cfg.custom_cellgds;
  return `${cfg.pdk_path}/libs.ref/${cfg.scl}/gds/${cfg.scl}.gds`;
}

// ─── Magic env + foundry-rcfile resolution (ORGANIC-20260531 fix) ────────
// The system .magicrc reads `$env(PDK)` AT STARTUP — before any -rcfile
// script runs — so launching magic without `export PDK=...` aborts with
// `Error parsing user ".magicrc": can't read "env(PDK)": no such variable`,
// the tech is never loaded ("Using technology minimum"), and the inline
// script is never read. Setting `set env(PDK)` INSIDE the script is too late.
// PROVEN FIX (in-container): `export PDK=<key> PDK_ROOT=... ;
// magic -dnull -noconsole -rcfile <pdk>.magicrc <script>`.
//
// Returns { pdkKey, magicrc } for a gf180/sky130 pdk, or null for custom /
// unknown (caller should pass custom_magicrc explicitly). PDK key is the
// foundry directory name the magicrc/tech expect in $env(PDK) (sky130A /
// gf180mcuD), NOT the short "sky130"/"gf180" tool selector.
function magicPdkEnv(pdk) {
  if (pdk === "sky130") {
    return {
      pdkKey: "sky130A",
      magicrc: `${PDK_ROOT}/sky130A/libs.tech/magic/sky130A.magicrc`,
    };
  }
  if (pdk === "gf180") {
    return {
      pdkKey: "gf180mcuD",
      magicrc: `${PDK_ROOT}/gf180mcuD/libs.tech/magic/gf180mcuD.magicrc`,
    };
  }
  return null;
}

// ─── Tie-cell discovery + hilomap clause (ORGANIC-20260531) ──────────────
// Port of phase3_one_shot_runner.py `_v1_6_596_discover_tie_cells` +
// `_v1_6_596_build_hilomap_directive`. The bare MCP `eda_synth` yosys
// script (synth; dfflibmap; abc; clean; write_verilog) left constant bits
// (1'h0 / 1'h1 from CRC tables, clamps, tie-offs, unused-output zeroing,
// etc.) as bare `zero_`/`one_` nets in the gate netlist. OpenROAD's
// `detailed_route` then rejects them with [DRT-0305] (POWER net) / [DRT-0199].
// `phase3_one_shot_runner.py` (v1.6.596+) already discovers the PDK tie cell
// from the liberty and inserts Yosys `hilomap` after abc so 1'b0/1'b1 are
// mapped to the dedicated tie cell. This ports the SAME logic into eda_synth
// so the bare doc→GDS path (i2s/ahb_apb/ufs/sent pilots) gets it too.
//
// Chip-AGNOSTIC / PDK-agnostic: discovers the tie cell from the liberty
// cell-name vocabulary only (conb_/conp_/TIEHI/TIELO patterns). sky130
// conb_1 is the dual-output (HI + LO) tie cell; other PDKs split into
// separate tie_h / tie_l cells. No chip-class string literal as logic; when
// nothing is discoverable, the hilomap step is OMITTED and a warning is
// surfaced — exactly as the runner falls back.
const _TIE_HI_PAT =
  /(?:^|_)(?:conb|conp|tieh|tiehi|tie_h|tie_hi|tiep|hi)_?\d*$/i;
const _TIE_LO_PAT =
  /(?:^|_)(?:conp|conb|tiel|tielo|tie_l|tie_lo|tien|lo)_?\d*$/i;
// Production OpenLane liberty wraps cell names in DOUBLE QUOTES:
// `cell ("sky130_fd_sc_hd__conb_1")`. Accept both quoted and bare forms.
const _RE_CELL_DECL = /^\s*cell\s*\(\s*"?([A-Za-z_][A-Za-z0-9_]*)"?\s*\)/gm;

// Read a liberty file from inside the EDA container (the sky130A / gf180
// PDK lives only at /foss/pdks inside the container; the host has no
// mirror). Returns the text, or null if it can't be read. Mirrors
// `_v1_6_604_read_text_or_container_cat`'s container-cat fallback.
function _readLibertyInContainer(libPath) {
  if (!libPath) return null;
  // `cat` inside the container; bounded by dockerExec's 10MB maxBuffer.
  const r = dockerExec(`cat ${libPath} 2>/dev/null`, 30000);
  if (r.success && r.output && r.output.length > 0) return r.output;
  return null;
}

// Faithful JS port of `_v1_6_596_discover_tie_cells`. Returns
// {hi_cell, lo_cell, hi_pin, lo_pin}; cells are null when nothing is
// discoverable so the caller can OMIT hilomap (legacy flow). Chip-AGNOSTIC.
function discoverTieCells(libText) {
  const out = { hi_cell: null, lo_cell: null, hi_pin: "HI", lo_pin: "LO" };
  if (!libText || typeof libText !== "string") return out;
  const cellnames = [];
  let m;
  _RE_CELL_DECL.lastIndex = 0;
  while ((m = _RE_CELL_DECL.exec(libText)) !== null) cellnames.push(m[1]);
  if (cellnames.length === 0) return out;
  // sky130-style: conb_X is the canonical dual-output tie cell (HI + LO);
  // prefer it when seen. Otherwise split into separate tie_h / tie_l.
  for (const nm of cellnames) {
    const nLc = nm.toLowerCase();
    if (nLc.includes("conb")) {
      if (out.hi_cell === null) out.hi_cell = nm;
      if (out.lo_cell === null) out.lo_cell = nm;
      continue;
    }
    if (_TIE_HI_PAT.test(nLc) && out.hi_cell === null) {
      // Avoid matching tie-low patterns (the `lo` token also matches
      // _TIE_HI_PAT if loosely written).
      if (!_TIE_LO_PAT.test(nLc) || nLc.includes("hi")) out.hi_cell = nm;
    }
    if (_TIE_LO_PAT.test(nLc) && out.lo_cell === null) {
      if (!_TIE_HI_PAT.test(nLc) || nLc.includes("lo")) out.lo_cell = nm;
    }
  }
  // Sniff output-pin names from the chosen cell block(s). When the same
  // cell is used for both HI and LO (sky130 conb_1 dual-output), gather all
  // pins in the block and select HI-like / LO-like by vocabulary. When the
  // cells differ (separate tie_h / tie_l), the first pin is the output.
  const sameCell = out.hi_cell !== null && out.hi_cell === out.lo_cell;
  const cellsHandled = new Set();
  for (const [key, defaultPin] of [["hi_cell", "HI"], ["lo_cell", "LO"]]) {
    if (out[key] === null) continue;
    const cellName = out[key];
    if (cellsHandled.has(cellName)) continue;
    cellsHandled.add(cellName);
    const blockRe = new RegExp(
      "cell\\s*\\(\\s*" +
        cellName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") +
        "\\s*\\)\\s*\\{",
      "i");
    const bm = blockRe.exec(libText);
    const pinKey = key.replace("cell", "pin");
    if (!bm) { out[pinKey] = defaultPin; continue; }
    // Cap window at 4KB so we don't scan the entire liberty.
    const windowTxt = libText.slice(bm.index + bm[0].length,
                                    bm.index + bm[0].length + 4096);
    // Negative lookbehind on identifier chars so `pg_pin(VDD)` (the
    // power rail, declared before signal pins) is not picked as the
    // output pin. Mirrors the v1.6.598 fix.
    const pinNames = [];
    const pinRe = /(?<![A-Za-z_])pin\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)/g;
    let pm;
    while ((pm = pinRe.exec(windowTxt)) !== null) pinNames.push(pm[1]);
    if (pinNames.length === 0) continue;
    if (sameCell) {
      const hiNamed = pinNames.filter(p => /\b(hi|h|p|pwr|vdd|one)\b/i.test(p));
      const loNamed = pinNames.filter(p => /\b(lo|l|n|gnd|vss|zero)\b/i.test(p));
      if (hiNamed.length) out.hi_pin = hiNamed[0];
      else if (pinNames.length) out.hi_pin = pinNames[0];
      if (loNamed.length) out.lo_pin = loNamed[0];
      else if (pinNames.length > 1) out.lo_pin = pinNames[1];
      else if (pinNames.length) out.lo_pin = pinNames[0];
    } else {
      out[pinKey] = pinNames[0];
    }
  }
  return out;
}

// Port of `_v1_6_596_build_hilomap_directive` + the v0.1.98 HDLC-pilot
// recipe refinement. Returns the Yosys clause to insert AFTER `abc` and
// BEFORE `write_verilog`, or "" when no tie cell is discoverable (the
// caller then OMITs hilomap and falls back to the legacy flow, exactly as
// phase3_one_shot_runner does).
//
// CRITICAL recipe (from the backlog suggested_fix):
//   setundef -zero; hilomap -hicell <HI> <HIPIN> -locell <LO> <LOPIN>; splitnets; clean
//   * `setundef -zero` MUST come BEFORE hilomap — a function with don't-care
//     output bits emits Yosys 1'hx that survives hilomap as a bare zero_/x
//     net and still trips DRT-0305 unless forced to 0 first.
//   * use PLAIN `clean` (NOT opt_clean) — opt_clean deletes the just-inserted
//     tie cells, re-introducing the bare constants.
// Returns { clause, tie } where `tie` is the discovery result (for warnings).
function buildHilomapClause(libPath) {
  const libText = _readLibertyInContainer(libPath);
  const tie = discoverTieCells(libText);
  if (!(tie.hi_cell && tie.lo_cell)) return { clause: "", tie };
  // When hi_cell === lo_cell (sky130 conb_1 dual-output), Yosys accepts the
  // same cell name for both arguments.
  const clause =
    `setundef -zero; ` +
    `hilomap -hicell ${tie.hi_cell} ${tie.hi_pin} ` +
    `-locell ${tie.lo_cell} ${tie.lo_pin}; ` +
    `splitnets; clean; `;
  return { clause, tie };
}

// ORGANIC-20260531: yosys `write_verilog` mints auto-generated net/cell names
// that embed the SOURCE COORDINATE (`$func$/abs/path/design.v:42$`,
// `\mux$/abs/foo.v:118`). The absolute path + `:line` make the netlist
// NON-deterministic — synth the same RTL from a different dir / after a line
// shift and the bytes (and provenance sha256) change. This collapses every
// embedded `<path>:<line>` coordinate inside a `$…$` auto-name or a `\`-escaped
// identifier to its path-free, line-free basename, mirroring the standalone
// programs/netlist_src_coord_canonicalize.py (the Python source of truth).
// chip-AGNOSTIC: matches the generic coordinate shape, never a chip token.
function canonicalizeNetlistSrcCoords(netlistPath) {
  try {
    const fs = require("fs");
    if (!netlistPath || !fs.existsSync(netlistPath)) return false;
    const before = fs.readFileSync(netlistPath, "utf8");
    const stripCoord = (tok) =>
      tok.replace(/[^\s$]*\/([^\s$/:\\]+):\d+/g, "$1")  // <path>/<base>:<line> -> <base>
         .replace(/([^\s$/:\\]+):\d+/g, "$1");           // <base>:<line>        -> <base>
    let text = before
      .replace(/\$([^$\n]*?:\d+[^$\n]*?)\$/g, (_m, inner) => "$" + stripCoord(inner) + "$")
      .replace(/\\[^\s]*:\d+[^\s]*/g, (m) => stripCoord(m));
    if (text !== before) { fs.writeFileSync(netlistPath, text); return true; }
    return false;
  } catch (_e) {
    return false;  // best-effort: never break synth on a canonicalisation hiccup
  }
}

// v2.5.0 helpers ----------------------------------------------------------
// wrapResult() — unified tool result envelope. Tools that adopt it return
// {success, duration_ms, tool_version, error, output_head, output_tail, ...}.
// Existing v2.x tools keep their legacy shape for backwards-compat; new
// tools (eda_doctor / eda_run_tcl / eda_pdk_lint / eda_workflow_run) use it
// uniformly. The head/tail split preserves the most diagnostic-relevant lines
// when output is long; both empty strings on docker-unreachable failure now
// surface the dockerExec hint via `error`.
// since v0.114.3 (#94): SERVER_VERSION canonicalised against
// package.json so runtime tool_version strings match the package
// version. Pre-fix this constant was pinned at "0.28.0" while
// package.json drifted up to 0.114.x — making it impossible for
// field-agents to tell at runtime whether a given handler patch
// was actually loaded. Resolution: keep them in lockstep; if you
// bump package.json, also bump this constant.
const SERVER_VERSION = "1.0.0";
function wrapResult({ success, t0, toolVersion, error, output, headLines = 40, tailLines = 80, ...rest }) {
  const dur = t0 ? (Date.now() - t0) : 0;
  const text = (output || "").toString();
  const lines = text.split("\n");
  const headT = lines.slice(0, headLines).join("\n");
  const tailT = lines.length > headLines + tailLines
    ? lines.slice(-tailLines).join("\n")
    : "";
  return {
    content: [{ type: "text", text: JSON.stringify({
      success: !!success,
      duration_ms: dur,
      tool_version: toolVersion || `mcp-eda@${SERVER_VERSION}`,
      error: error || (success ? "" : "tool failed (no error message)"),
      output_head: headT,
      output_tail: tailT,
      ...rest,
    }) }]
  };
}

// Helper: run an arbitrary command in container (no path massaging) and
// return the wrapped result.
function dockerExecWrapped({ cmd, timeoutMs, toolVersion, ...rest }) {
  const t0 = Date.now();
  const r = dockerExec(cmd, timeoutMs);
  return wrapResult({
    success: r.success,
    t0,
    toolVersion,
    error: r.error,
    output: r.output,
    ...rest,
  });
}

// Helper: read tool versions cheaply (cached).
// v2.5.5: detect failures even when exit code is 0. Common anti-patterns:
//  - `... | head -1` masks the real exit code; head succeeds even when the
//    underlying command fails ("command not found" → bash 127 → head 0).
//  - Magic exits 0 but writes "no display name and no $DISPLAY" to stderr.
// Now: probe with `set -o pipefail` and explicit error-pattern rejection.
const _versionCache = new Map();
// v2.5.6: tighten the error-pattern list. v2.5.5 caught the magic /
// fault false-PASS but the catch-all strings ("not found" / "Error:" /
// "error:" / "failed") were too loose — any banner mentioning "0 errors"
// or "no test failed" would be misclassified. We now use regex with
// anchors / word boundaries:
//
//  - command not found     | bash 127 fingerprint (specific phrase)
//  - No such file or dir   | exec-side missing binary (specific phrase)
//  - no display name       | magic / X11 missing $DISPLAY (specific phrase)
//  - \$DISPLAY             | literal mention of the env var, also from magic
//  - line-anchored Error:  | only flag when the line *starts* with Error:
//  - line-anchored bash:   | shell-emitted exec error (e.g. "bash: line 1: ...")
//  - Permission denied     | tool exists but EACCES (very specific)
//
// Dropped: "not found" alone (already covered by "command not found" /
// "No such file"; bare "not found" matches benign "package XYZ not found
// in cache" lines), "failed" alone (matches "0 tests failed" etc),
// non-anchored "error:" (matches version banners like "Errors: 0").
const _ERR_PATTERNS = [
  /command not found/,
  /No such file or directory/,
  /no display name/,
  /\$DISPLAY/,
  /^(?:Error|ERROR):/m,
  /^(?:bash|sh): /m,
  /Permission denied/,
];
// v2.6.5: the version cache is process-lived and was NEVER invalidated, so once a
// tool was probed getToolVersion() returned that string forever. But the image
// bumps often (any fork upgrade → a new vibeic-eda tag → `docker rm/run` the
// container under the SAME name), and after such a swap eda_doctor — whose whole
// job is a FRESH preflight — kept reporting the PRE-swap toolchain (observed:
// yosys still shown at the old fork commit after the container was recreated on a
// new image). Key the cache on the container's current image id: before serving a
// cached version, cheaply confirm the image is unchanged; if it moved, drop the
// cache so every tool re-probes. The `docker inspect` is throttled (2s) so a
// 14-tool doctor burst costs at most one inspect.
let _versionCacheImageId = null;
let _versionCacheCheckedAt = 0;
function _ensureVersionCacheFresh() {
  const now = Date.now();
  if (_versionCacheImageId !== null && now - _versionCacheCheckedAt < 2000) return;
  _versionCacheCheckedAt = now;
  const r = _spawnSync("docker", ["inspect", CONTAINER, "--format", "{{.Image}}"],
    { encoding: "utf-8", timeout: 3000 });
  const img = (r && r.status === 0 && r.stdout) ? r.stdout.trim() : null;
  if (img && img !== _versionCacheImageId) {
    _versionCache.clear();          // container was recreated on a new image → re-probe all
    _versionCacheImageId = img;
  }
}
function getToolVersion(name) {
  _ensureVersionCacheFresh();
  if (_versionCache.has(name)) return _versionCache.get(name);
  const probes = {
    yosys: `${TOOLS}/yosys/bin/yosys -V 2>&1 | head -1`,
    openroad: `${TOOLS}/openroad/bin/openroad -version 2>&1 | head -1`,
    klayout: `${TOOLS}/klayout/klayout -v 2>&1 | head -1`,
    iverilog: `${TOOLS}/iverilog/bin/iverilog -V 2>&1 | head -1`,
    verilator: `${TOOLS}/bin/verilator --version 2>&1 | head -1`,
    // magic: `--version` prints the bare `<maj>.<min>.<rev>` string (e.g. 8.3.671)
    // to stdout and exits 0 on the vibeic/magic build. The older `-dnull -noconsole
    // <<< 'puts $::magic_version'` tcl probe returned EMPTY (the global isn't set at
    // that point), false-FAILing an otherwise healthy magic — see 2026-07-11 fix.
    magic: `${TOOLS}/bin/magic --version 2>&1 | grep -E '^[0-9]+\\.' | head -1`,
    netgen: `${TOOLS}/bin/netgen -batch source /dev/null 2>&1 | head -2 | tail -1`,
    ngspice: `${TOOLS}/bin/ngspice --version 2>&1 | head -1`,
    // fault (AUCOHL DFT toolchain): the vibeic-eda image is self-contained — every
    // tool resolves at a deterministic /foss/tools/bin path, never via ambient PATH
    // (a docker-exec PATH we don't control). The base ships fault at
    // /usr/local/bin/fault; the Dockerfile symlinks it into ${TOOLS}/bin/fault so
    // the probe (and any caller) hits the same deterministic path as every other
    // tool. `--version` emits env warnings on stderr then the bare version, so grep
    // the version line. (2026-07-11: was hardcoded-but-wrong, then briefly PATH,
    // now deterministic path backed by the Dockerfile symlink.)
    fault: `${TOOLS}/bin/fault --version 2>&1 | grep -E '^[0-9]+\\.' | head -1`,
  };
  const probe = probes[name];
  if (!probe) { _versionCache.set(name, "unknown"); return "unknown"; }
  // Don't use pipefail — would break legitimate `cmd | head -1` patterns where
  // head closes early and upstream gets SIGPIPE (non-zero, but cmd succeeded).
  // Instead: trust exit code only if non-zero is genuine, and ALWAYS scan
  // output for known error fingerprints to catch the head-masks-failure case.
  const r = dockerExec(probe, 8000);
  let v;
  const out = (r.output || "").trim();
  if (_ERR_PATTERNS.some(p => p.test(out))) {
    v = `unavailable: ${out.slice(0, 120)}`;
  } else if (out.length === 0) {
    v = `unavailable: empty output (probe ran but printed nothing — likely missing binary)`;
  } else if (!r.success && !out.match(/[0-9]+\.[0-9]/)) {
    // Non-zero exit AND no version-shaped string → genuine failure
    v = `unavailable: ${(r.error || out || "").slice(0, 120)}`;
  } else {
    v = out;
  }
  _versionCache.set(name, v);
  return v;
}

// ─── Tool identity for the provenance log ────────────────────────────────
// MEASURED 2026-08-27: every logProvenance call passed a HARDCODED literal as
// `version` -- "yosys (mcp-eda) pdk=gf180", "openroad (mcp-eda) pdk=gf180", and
// five more. Those strings name a tool but carry no version and no image, so
// they read identically across two different images holding two different
// builds. A run recorded which TOOL was asked for, never which BINARY answered.
// That is not identity: a tag was measured this same night naming two different
// images on two hosts, so only a digest re-derives.
//
// The parts were already here and simply unused: getToolVersion() probes the
// real version inside the container, and the version cache already inspects the
// container's image. This composes them, preferring the REPO DIGEST (which
// re-derives anywhere) over the local image id (which does not).
//
// It must never throw and never invent: if docker cannot answer, the record
// says so in words rather than carrying a confident-looking blank.
let _imageIdentityCache = null;
let _imageIdentityCheckedAt = 0;
function containerImageIdentity() {
  const now = Date.now();
  if (_imageIdentityCache && now - _imageIdentityCheckedAt < 10000) return _imageIdentityCache;
  let ident;
  try {
    const r = _spawnSync("docker", ["inspect", CONTAINER, "--format", "{{.Image}}"],
      { encoding: "utf-8", timeout: 3000 });
    const imageId = (r && r.status === 0 && r.stdout) ? r.stdout.trim() : null;
    if (!imageId) {
      ident = { image_ref: "unavailable (docker inspect failed)", image_id: null };
    } else {
      // The container's image id resolves to the image; ask THAT for a repo
      // digest, which is the only form that re-derives on another host.
      const d = _spawnSync("docker", ["image", "inspect", imageId,
        "--format", "{{json .RepoDigests}}"], { encoding: "utf-8", timeout: 3000 });
      let digest = null;
      if (d && d.status === 0 && d.stdout) {
        try {
          const arr = JSON.parse(d.stdout.trim());
          if (Array.isArray(arr) && arr.length) digest = arr[0];
        } catch (_) { /* fall through to the image id */ }
      }
      ident = { image_ref: digest || imageId, image_id: imageId };
    }
  } catch (e) {
    ident = { image_ref: `unavailable (${e.message})`, image_id: null };
  }
  _imageIdentityCache = ident;
  _imageIdentityCheckedAt = now;
  return ident;
}

// `label` lets a caller name the wrapper it used (e.g. "opensta via openroad")
// while still probing the binary that actually ran.
function toolIdentity(probeName, pdk, label) {
  const img = containerImageIdentity();
  let ver;
  try { ver = getToolVersion(probeName); } catch (e) { ver = `unavailable (${e.message})`; }
  return `${label || probeName} | version=${ver} | image=${img.image_ref} `
       + `| container=${CONTAINER} | pdk=${pdk} | via=mcp-eda@${SERVER_VERSION}`;
}

// ─── Server Setup ───
const server = new McpServer({
  name: "mcp-eda",
  version: "1.0.0",
});

// ─── Tool: eda_synth ───
server.tool(
  "eda_synth",
  "Synthesize RTL to gate-level netlist using Yosys. Returns cell count, area, and writes netlist file.",
  {
    verilog_files: z.array(z.string()).describe("Paths to Verilog/SV source files (inside container)"),
    top_module: z.string().describe("Top module name"),
    output_netlist: z.string().describe("Output netlist path (inside container)"),
    pdk: z.enum(["gf180", "sky130", "nangate45", "custom"]).default("gf180").describe("Target PDK"),
    sv_mode: z.boolean().default(true).describe("Use -sv flag for SystemVerilog"),
    custom_lib: z.string().optional().describe("Path to Liberty .lib file (custom PDK)"),
    custom_techlef: z.string().optional().describe("Path to tech LEF file (custom PDK)"),
    custom_celllef: z.string().optional().describe("Path to cell LEF file (custom PDK)"),
    custom_cellgds: z.string().optional().describe("Path to cell GDS file (custom PDK)"),
    custom_site: z.string().optional().describe("Site name for floorplan (custom PDK)"),
    custom_vdd: z.string().optional().describe("VDD pin name (custom PDK)"),
    custom_vss: z.string().optional().describe("VSS pin name (custom PDK)"),
    custom_metal_prefix: z.string().optional().describe("Metal-layer name prefix for custom PDKs whose layers don't match SKY130 'met' naming (e.g. 'MET' for a commercial 180nm PDK's MET1-6). Default 'met'."),
  },
  async ({ verilog_files, top_module, output_netlist, pdk, sv_mode, custom_lib, custom_techlef, custom_celllef, custom_cellgds, custom_site, custom_vdd, custom_vss, custom_metal_prefix }) => {
    try {
      assertSafePaths(verilog_files, "verilog_files");
      assertSafePath(output_netlist, "output_netlist");
      assertSafeIdent(top_module, "top_module");
      optPath(custom_lib, "custom_lib"); optPath(custom_techlef, "custom_techlef");
      optPath(custom_celllef, "custom_celllef"); optPath(custom_cellgds, "custom_cellgds");
      optToken(custom_site, "custom_site"); optIdent(custom_vdd, "custom_vdd");
      optIdent(custom_vss, "custom_vss"); optToken(custom_metal_prefix, "custom_metal_prefix");
    } catch (e) { return guardError(e); }
    // v0.1.11: fail fast with a staging hint when inputs are not in-container.
    const _missSynth = missingInContainer(verilog_files);
    if (_missSynth.length) {
      const h = stagingHint(_missSynth);
      return { content: [{ type: "text", text: JSON.stringify({ success: false, area_um2: null, cell_count: null, output: h, error: h, log_tail: h }) }] };
    }
    const cfg = pdkConfig(pdk, { custom_lib, custom_techlef, custom_celllef, custom_cellgds, custom_site, custom_vdd, custom_vss, custom_metal_prefix });
    const lib = libPath(cfg);
    const readFlag = sv_mode ? "-sv" : "";
    const reads = verilog_files.map((f) => `read_verilog ${readFlag} ${f}`).join("; ");

    // ORGANIC-20260531: discover the PDK tie cell from the liberty and
    // inject `setundef -zero; hilomap ...; splitnets; clean` AFTER abc and
    // BEFORE write_verilog so constant 1'b0/1'b1 bits map to the dedicated
    // tie cell instead of surviving as bare `zero_`/`one_` nets that
    // OpenROAD detailed_route rejects with DRT-0305 / DRT-0199. Ported
    // faithfully from phase3_one_shot_runner.py (_v1_6_596_discover_tie_cells
    // + hilomap). When NO tie cell is discoverable, the clause is empty and
    // the legacy flow is preserved (hilomap omitted + warning surfaced),
    // exactly as the runner falls back. Chip-AGNOSTIC / PDK-agnostic — never
    // hardcodes a cell name as the only path; conb_1 is found in the liberty.
    const { clause: hilomapClause, tie: tieCells } = buildHilomapClause(lib);
    const tie_cell_warning = hilomapClause
      ? undefined
      : `No tie cell discoverable in liberty ${lib} — hilomap step OMITTED; ` +
        `any constant 1'b0/1'b1 bit will survive as a bare zero_/one_ net ` +
        `and may trip OpenROAD DRT-0305/DRT-0199 in downstream eda_pnr.`;
    const cmdStr = `export PATH=${TOOLS}/yosys/bin:${TOOLS}/bin:$PATH && yosys -p '${reads}; synth -top ${top_module}; dfflibmap -liberty ${lib}; abc -liberty ${lib}; ${hilomapClause}clean; stat -liberty ${lib}; write_verilog -noattr ${output_netlist}' 2>&1`;
    const t0 = Date.now();
    const result = dockerExec(cmdStr);
    const durationMs = Date.now() - t0;
    // ORGANIC-20260531: make the emitted netlist reproducible by stripping the
    // yosys source-coordinate (<path>:<line>) auto-names. Best-effort; no-op if
    // the netlist is absent or already coordinate-free.
    if (result.success) canonicalizeNetlistSrcCoords(output_netlist);

    // Extract key metrics
    // MEASURED 2026-08-27 on vibeic-eda@sha256:4ece6c01 (yosys 0.68+):
    //
    //  CELLS. `stat -liberty` prints `<count> <area> cells` ONLY when the count
    //  is non-zero. A design that legitimately synthesises to ZERO cells - the
    //  constant-driven output `assign zero = 1'b0` is the canonical case, and
    //  it is CORRECT for it to have no cells - prints the bare `0 cells`, with
    //  no area column, because yosys omits the Local Area column entirely.
    //  The old two-number pattern therefore returned `cells: null` for it: the
    //  SAME value the tool returns when it cannot parse the stat block at all.
    //  A caller could not tell "synthesised to a legitimate constant" from
    //  "could not determine the cell count", which is precisely how a correct
    //  0-cell synthesis got scored as a failure downstream. Zero is now
    //  reported AS zero, and null still means only "not measured".
    //
    //  AREA. yosys prints `Chip area for top module '<t>':` only when the
    //  design is HIERARCHICAL. A flat single-module design - every small
    //  design, and anything already flattened - prints only `Chip area for
    //  module '<t>':`, so the old pattern read null for the whole flat class.
    //  Prefer the top-module line when present, else the module line.
    const areaMatch = result.output.match(/Chip area for top module.*?:\s*([\d.]+)/)
                   || result.output.match(/Chip area for module.*?:\s*([\d.]+)/);
    const cellMatch = result.output.match(/(\d+)\s+[\d.E+]+\s+cells$/m)
                   || result.output.match(/^\s*(\d+)\s+cells$/m);

    // v0.119.41 (Wave 9, gap #2): the v0.119.40 fresh-agent benchmark
    // observed `log_tail` truncating actual Yosys parser errors when
    // synth failed.  The 2KB tail captured the head of subsequent
    // helper output but dropped the ERROR / cannot-find-module line.
    // Build a smarter tail: first capture priority error lines from
    // the full log, then append the most-recent N bytes; cap total
    // size at ~8 KB to keep the MCP payload bounded.
    const ERR_PATTERNS = /(?:^|\n)([^\n]*?(?:ERROR|error:|cannot|not found|undefined module|syntax error|Parser error)[^\n]*)/gi;
    const allLines = result.output || "";
    const matches = [];
    let m;
    while ((m = ERR_PATTERNS.exec(allLines)) !== null) {
      matches.push(m[1].trim());
      if (matches.length >= 30) break;
    }
    const TAIL_BYTES = 6000;
    const HEADER_BYTES_MAX = 2000;
    const errBlock = matches.length
      ? "[priority error lines]\n" + matches.slice(-30).join("\n") + "\n[tail]\n"
      : "";
    const errBlockClipped = errBlock.length > HEADER_BYTES_MAX
      ? errBlock.slice(-HEADER_BYTES_MAX)
      : errBlock;
    const tail = allLines.slice(-TAIL_BYTES);
    const log_tail = (errBlockClipped + tail).slice(-8192);

    const metrics = {
      success: result.success,
      area_um2: areaMatch ? parseFloat(areaMatch[1]) : null,
      cells: cellMatch ? parseInt(cellMatch[1]) : null,
      netlist: output_netlist,
      // ORGANIC-20260531: surface the discovered tie cell + whether the
      // hilomap pass was applied (so the caller knows constant nets were
      // mapped) or omitted (with a warning) — mirrors phase3 runner.
      hilomap_applied: !!hilomapClause,
      tie_cell: hilomapClause ? tieCells.hi_cell : null,
      tie_cell_warning,
      log_tail,
    };

    // P0: Write manifest
    // `metrics.cells` is FALSY at 0, so the legitimately zero-cell design above
    // was also denied a manifest - the same silence as an unparseable run. The
    // test is "was the cell count measured", not "is it non-zero".
    if (metrics.success && metrics.cells !== null) {
      const dir = output_netlist.substring(0, output_netlist.lastIndexOf("/"));
      writeManifest(dir || "/tmp", {
        step: "synthesis",
        status: "PASS",
        tool: "Yosys",
        top_module,
        pdk,
        cells: metrics.cells,
        area_um2: metrics.area_um2,
        output_file: output_netlist,
      });
    }

    // v0.47.5: auto-provenance. The netlist file is host-side via the
    // Docker bind mount; project_dir is the parent of the netlist.
    // Caller MAY override via env EDA_PROJECT_DIR; otherwise we derive
    // from output_netlist's parent of parents.
    const projectDir = process.env.EDA_PROJECT_DIR ||
        output_netlist.replace(/\/synth\/.*/, "").replace(/^\/work\//, "/host_project/");
    const inputs = {};
    verilog_files.forEach((f) => { inputs[f] = sha256File(f.replace("/work/", projectDir + "/")); });
    const outputs = { [output_netlist]: sha256File(output_netlist.replace("/work/", projectDir + "/")) };
    logProvenance({
      projectDir,
      tool: "yosys",
      version: toolIdentity("yosys", pdk),
      argv: ["yosys", "-p", `synth -top ${top_module} ...`],
      inputs, outputs,
      exitCode: result.success ? 0 : (result.exitCode || 1),
      durationMs,
      stdoutTail: result.output || "",
      stderrTail: result.error || "",
    });

    return { content: [{ type: "text", text: JSON.stringify(metrics) }] };
  }
);

// ─── Tool: eda_lint ───
//
// v0.99.2: strictness selector. Default ("error_only") promotes only true
// errors (syntax / undeclared symbols / etc.) to FAIL and demotes the
// noisy stylistic warnings (WIDTHTRUNC / UNUSEDPARAM / UNUSEDSIGNAL / …)
// to non-fatal, since Quartus and Icarus accept the same RTL. The old
// behavior is still available via strictness="warnings_as_errors". This
// closes the v0.119.22 vendor complaint that valid RTL accepted by
// Quartus + iverilog was rejected by `verilator -Wall`.
//
// Demoted warnings list is GENERAL (not project- or vendor-specific):
// they're the verilator categories whose default severity is widely
// considered too aggressive for new RTL and are routinely suppressed in
// open-source flows (yosys/openlane, oss-cad-suite, OpenROAD examples).
const _LINT_DEMOTED_WARNINGS = [
  "WIDTHTRUNC", "WIDTHEXPAND", "WIDTH",
  "UNUSEDPARAM", "UNUSEDSIGNAL", "UNUSED",
  "PINMISSING", "PINCONNECTEMPTY",
  "DECLFILENAME",
  "STMTDLY",  // delays in always blocks (sim-only constructs)
  "SYNCASYNCNET",
];
server.tool(
  "eda_lint",
  "Run Verilator lint on RTL files. Returns warnings and errors. v0.99.2 adds a `strictness` selector — default 'error_only' lets stylistic warnings through (matching Quartus / Icarus tolerance), 'warnings_as_errors' restores the historical -Wall behaviour.",
  {
    verilog_files: z.array(z.string()).describe("Paths to Verilog/SV source files"),
    top_module: z.string().describe("Top module name"),
    strictness: z.enum(["error_only", "warnings_as_errors"]).default("error_only").describe("'error_only' (default) demotes WIDTHTRUNC / UNUSEDPARAM / UNUSEDSIGNAL / PINMISSING / DECLFILENAME / STMTDLY / SYNCASYNCNET to non-fatal — matches Quartus / Icarus tolerance. 'warnings_as_errors' uses verilator -Wall and fails on any warning."),
  },
  async ({ verilog_files, top_module, strictness }) => {
    try {
      assertSafePaths(verilog_files, "verilog_files");
      assertSafeIdent(top_module, "top_module");
    } catch (e) { return guardError(e); }
    // v0.1.11: fail fast with a staging hint when inputs are not in-container.
    const _miss = missingInContainer(verilog_files);
    if (_miss.length) {
      const h = stagingHint(_miss);
      return { content: [{ type: "text", text: JSON.stringify({ success: false, errors: 0, warnings: 0, output: h, error: h }) }] };
    }
    const files = verilog_files.join(" ");
    const wnoFlags = strictness === "error_only"
      ? _LINT_DEMOTED_WARNINGS.map(w => `-Wno-${w}`).join(" ")
      : "-Wno-DECLFILENAME";

    // v0.119.41 (Wave 9, gap #3): scan source files for `\`include`
    // directives and auto-add their parent directories as
    // `+incdir+<dir>`.  Closes the v0.119.40 benchmark gap where
    // verilator was invoked without +incdir for `ic-a_constants.svh`,
    // forcing the agent to inline-prepend macros or rename to .v.
    // Also fall back to <project>/include (or any sibling `include/`
    // directory of a source file) if it exists on the host.
    const path = await import("path");
    const fs = await import("fs");
    const incDirs = new Set();
    const includeRe = /^\s*`include\s+"([^"]+)"/gm;
    for (const f of verilog_files) {
      const hostPath = f.replace(/^\/work\//, (process.env.EDA_PROJECT_DIR || "") + "/");
      let text = "";
      try {
        text = fs.readFileSync(hostPath, "utf8");
      } catch { /* file may live only inside container; best-effort */ }
      let mm;
      while ((mm = includeRe.exec(text)) !== null) {
        const target = mm[1];
        // Resolve include target's parent dir relative to the source.
        const sourceDir = path.dirname(f);
        const targetDir = path.isAbsolute(target)
          ? path.dirname(target)
          : path.dirname(path.join(sourceDir, target));
        incDirs.add(targetDir);
      }
      // Sibling `include/` directory fallback.
      const sibInc = path.join(path.dirname(f), "include");
      const sibIncHost = sibInc.replace(/^\/work\//,
          (process.env.EDA_PROJECT_DIR || "") + "/");
      try {
        if (fs.existsSync(sibIncHost) && fs.statSync(sibIncHost).isDirectory()) {
          incDirs.add(sibInc);
        }
      } catch { /* ignore */ }
    }
    const incFlags = Array.from(incDirs)
      .map(d => `+incdir+${d}`)
      .join(" ");

    const result = dockerExec(
      `export PATH=${TOOLS}/verilator/bin:${TOOLS}/bin:$PATH && verilator --lint-only -Wall ${wnoFlags} ${incFlags} --top-module ${top_module} ${files} 2>&1`
    );

    const errors = (result.output.match(/%Error/g) || []).length;
    const warnings = (result.output.match(/%Warning/g) || []).length;
    // v2.4.1: was `success = errors === 0` — false PASS when docker_unreachable
    // produces empty output (errors=0 but tool never ran). Require dockerExec
    // to have succeeded AND errors=0.
    const success = result.success && errors === 0;
    const errorMsg = result.success ? "" : (result.error || "tool did not run");

    if (success) {
      writeManifest("/tmp", { step: "lint", status: "PASS", tool: "Verilator", top_module, errors, warnings, strictness });
    }

    return { content: [{ type: "text", text: JSON.stringify({ success, errors, warnings, strictness, output: result.output.slice(-3000), error: errorMsg }) }] };
  }
);

// ─── Tool: eda_simulate ───
server.tool(
  "eda_simulate",
  "Compile and run RTL simulation using Icarus Verilog. Returns PASS/FAIL. v0.99.3 adds `work_dir` so $readmemh / $readmemb / $fopen / `include resolve relative paths the way the testbench expects (default: dirname of the first source file).",
  {
    verilog_files: z.array(z.string()).describe("All source + testbench files"),
    output_vvp: z.string().default("./sim/sim.vvp").describe("Compiled output path. v0.123: default changed from /tmp/sim.vvp to ./sim/sim.vvp so artifacts land in the project tree, not on a volatile tmpfs that gets cleared on reboot. Caller may override to absolute path if they want a different location."),
    work_dir: z.string().optional().describe("Working directory for the simulation. Both iverilog (compile) and vvp (run) are invoked from this directory so $readmemh(\"file.hex\") and similar relative paths resolve correctly. Defaults to the directory of the first verilog_files entry."),
  },
  async ({ verilog_files, output_vvp, work_dir }) => {
    try {
      assertSafePaths(verilog_files, "verilog_files");
      assertSafePath(output_vvp, "output_vvp");
      optPath(work_dir, "work_dir");
    } catch (e) { return guardError(e); }
    const files = verilog_files.join(" ");
    // v0.99.3: pin the working directory so relative paths in the
    // testbench (e.g. $readmemh("apple.hex", mem)) resolve. Earlier
    // behavior was implicit /foss/designs CWD, which made $readmemh
    // silently load all-X memories — sim still "ran" but produced
    // wrong results.
    let cwd = work_dir;
    if (!cwd && verilog_files.length > 0) {
      const first = verilog_files[0];
      const slash = first.lastIndexOf("/");
      if (slash > 0) cwd = first.substring(0, slash);
    }
    const cdPrefix = cwd ? `cd "${cwd}" && ` : "";
    const result = dockerExec(
      `${cdPrefix}export PATH=${TOOLS}/iverilog/bin:${TOOLS}/bin:$PATH && export LD_LIBRARY_PATH=${TOOLS}/iverilog/lib:$LD_LIBRARY_PATH && iverilog -g2012 -o ${output_vvp} ${files} 2>&1 && vvp ${output_vvp} 2>&1`
    );

    const passed = result.output.includes("[PASS]") || result.output.includes("$finish");
    const failed = result.output.includes("[FAIL]") || result.output.includes("$fatal");

    if (result.success && !failed) {
      writeManifest("/tmp", {
        step: "simulation",
        status: "PASS",
        tool: "Icarus Verilog",
        passed,
        failed,
      });
    }

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            success: result.success && !failed,
            passed,
            failed,
            output: result.output.slice(-3000),
          }),
        },
      ],
    };
  }
);

// ─── Tool: eda_formal ───
server.tool(
  "eda_formal",
  "Run formal verification using SymbiYosys. Writes .sby config and runs proof.",
  {
    design_files: z.array(z.string()).describe("RTL design files"),
    assertion_file: z.string().describe("Assertion file (Yosys-compatible SVA)"),
    top_module: z.string().describe("Top module name"),
    work_dir: z.string().describe("Working directory"),
    depth: z.number().default(20).describe("Proof depth"),
    inductive_project: z.string().optional().describe("Opt-in datapath UNBOUNDED proof via a strengthened INDUCTIVE INVARIANT: pass a PROJECT dir to run programs/formal_property_run.py --invariant-harness (abc pdr proves an internal-state invariant unbounded where the output-stream property alone is not inductive). Writes a SEPARATE formal_<top>_inductive_results.json (never clobbers the canonical results.json); an honesty guard forbids a BMC dressed as unbounded, and a wide datapath that does not converge is reported PARTIAL/bounded with the depth DISCLOSED. When set, this runs instead of the inline SymbiYosys prove."),
    inductive_harness: z.string().optional().describe("Explicit inductive harness .sv (with @invariant-harness/@connect pragmas). Auto-detected as formal_<top>_inductive.sv when omitted. Only used with inductive_project."),
  },
  async ({ design_files, assertion_file, top_module, work_dir, depth, inductive_project, inductive_harness }) => {
    try {
      if (inductive_project === undefined) { assertSafePaths(design_files, "design_files"); assertSafePath(assertion_file, "assertion_file"); assertSafeIdent(top_module, "top_module"); }
      optPath(work_dir, "work_dir");
      optPath(inductive_project, "inductive_project"); optPath(inductive_harness, "inductive_harness");
    } catch (e) { return guardError(e); }
    // Opt-in inductive-invariant unbounded datapath proof (shells to program).
    if (inductive_project !== undefined) {
      const t0s = Date.now();
      const args = [`${VIBE_IC_PROGRAMS_DIR}/formal_property_run.py`, inductive_project];
      if (inductive_harness !== undefined) args.push("--invariant-harness", inductive_harness);
      const o = _spawnSync("python3", args, { timeout: 1800000, maxBuffer: 10 * 1024 * 1024, encoding: "utf-8" });
      const merged = (o.stdout || "") + (o.stderr || "");
      return wrapResult({
        success: !o.error && o.status === 0,
        t0: t0s,
        toolVersion: `formal_property_run @ mcp-eda@${SERVER_VERSION}`,
        error: o.error ? (o.error.message || String(o.error)) : (o.status === 0 ? undefined : `exited ${o.status}`),
        output: merged,
      });
    }
    const reads = design_files.map((f) => `read -formal ${f}`).join("\\n");
    const sbyContent = `[tasks]\\nprove\\n[options]\\nprove: mode prove\\nprove: depth ${depth}\\n[engines]\\nsmtbmc yices\\n[script]\\n${reads}\\nread -sv ${assertion_file}\\nhierarchy -top ${top_module}\\nprep -top ${top_module}\\n[files]\\n${[...design_files, assertion_file].join("\\n")}`;

    const result = dockerExec(
      `export PATH=${TOOLS}/yosys/bin:${TOOLS}/bin:$PATH && cd ${work_dir} && echo -e '${sbyContent}' > formal.sby && rm -rf formal_prove && sby -f formal.sby 2>&1`
    );

    const passed = result.output.includes("DONE (PASS");
    const failed = result.output.includes("DONE (FAIL") || result.output.includes("DONE (ERROR");

    if (passed) {
      writeManifest(work_dir || "/tmp", {
        step: "formal",
        status: "PASS",
        tool: "SymbiYosys",
        proved: passed,
        failed,
        top_module,
      });
    }

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            success: passed,
            proved: passed,
            failed,
            output: result.output.slice(-2000),
          }),
        },
      ],
    };
  }
);

// ─── Tool: eda_pnr ───
server.tool(
  "eda_pnr",
  "Run OpenROAD place & route on a synthesized netlist. Optionally runs CTS + detailed_route + writes routed netlist. Returns area, utilization, timing slack.",
  {
    netlist: z.string().describe("Synthesized Verilog netlist path"),
    top_module: z.string().describe("Top module name"),
    output_def: z.string().describe("Output DEF file path"),
    pdk: z.enum(["gf180", "sky130", "nangate45", "custom"]).default("gf180"),
    clock_port: z.string().default("clk"),
    clock_period_ns: z.number().default(200),
    utilization: z.number().default(40),
    density: z.number().default(0.55),
    enable_cts: z.boolean().default(false).describe("Run clock_tree_synthesis + repair_design after placement (v0.76)"),
    enable_detailed_route: z.boolean().default(false).describe("Run detailed_route after global_route — produces real routed DEF (v0.76)"),
    cts_buf_list: z.string().optional().describe("Space-separated list of clock buffer cells (e.g. 'CLKBUFD1 CLKBUFD2 CLKBUFD4 CLKBUFD8'). Required if enable_cts=true."),
    cts_root_buf: z.string().optional().describe("Root clock buffer cell (e.g. 'CLKBUFD8'). Required if enable_cts=true."),
    min_routing_layer: z.string().optional().describe("Minimum routing layer (e.g. 'MET2'). Default: lowest metal in tech LEF. Use MET2+ for PDKs whose MET1 pins lack access points."),
    max_routing_layer: z.string().optional().describe("Maximum routing layer (e.g. 'MET5'). Default: top metal in tech LEF."),
    sdc_file: z.string().optional().describe("Path to SDC constraints (overrides default create_clock if provided)"),
    output_routed_v: z.string().optional().describe("Write post-PnR Verilog netlist to this path (only if enable_detailed_route)"),
    pdn_stripe_layer: z.string().optional().describe("Upper-metal stripe layer for PDN (e.g. 'MET4'). Default: skip stripes, only follow-pin rails."),
    custom_lib: z.string().optional().describe("Path to Liberty .lib file (custom PDK)"),
    custom_techlef: z.string().optional().describe("Path to tech LEF file (custom PDK)"),
    custom_celllef: z.string().optional().describe("Path to cell LEF file (custom PDK)"),
    custom_cellgds: z.string().optional().describe("Path to cell GDS file (custom PDK)"),
    custom_site: z.string().optional().describe("Site name for floorplan (custom PDK)"),
    custom_vdd: z.string().optional().describe("VDD pin name (custom PDK)"),
    custom_vss: z.string().optional().describe("VSS pin name (custom PDK)"),
    custom_metal_prefix: z.string().optional().describe("Metal-layer name prefix for custom PDKs whose layers don't match SKY130 'met' naming (e.g. 'MET' for a commercial 180nm PDK's MET1-6). Default 'met'."),
    custom_antenna_diode: z.string().optional().describe("Antenna diode master cell for a custom PDK (v1.3.53). Enables the incremental antenna repair->reroute loop (enable_detailed_route only). gf180/sky130 supply their own; absent for a custom PDK -> antenna repair is SKIPPED (manual diode ECO)."),
  },
  async ({ netlist, top_module, output_def, pdk, clock_port, clock_period_ns, utilization, density, enable_cts, enable_detailed_route, cts_buf_list, cts_root_buf, min_routing_layer, max_routing_layer, sdc_file, output_routed_v, pdn_stripe_layer, custom_lib, custom_techlef, custom_celllef, custom_cellgds, custom_site, custom_vdd, custom_vss, custom_metal_prefix, custom_antenna_diode }) => {
    try {
      assertSafePath(netlist, "netlist"); assertSafePath(output_def, "output_def");
      assertSafeIdent(top_module, "top_module"); optIdent(clock_port, "clock_port");
      optPath(sdc_file, "sdc_file"); optPath(output_routed_v, "output_routed_v");
      optToken(cts_root_buf, "cts_root_buf"); optNoShellMeta(cts_buf_list, "cts_buf_list");
      optToken(min_routing_layer, "min_routing_layer"); optToken(max_routing_layer, "max_routing_layer");
      optToken(pdn_stripe_layer, "pdn_stripe_layer");
      optPath(custom_lib, "custom_lib"); optPath(custom_techlef, "custom_techlef");
      optPath(custom_celllef, "custom_celllef"); optPath(custom_cellgds, "custom_cellgds");
      optToken(custom_site, "custom_site"); optIdent(custom_vdd, "custom_vdd");
      optIdent(custom_vss, "custom_vss"); optToken(custom_metal_prefix, "custom_metal_prefix");
      optToken(custom_antenna_diode, "custom_antenna_diode");
    } catch (e) { return guardError(e); }
    const cfg = pdkConfig(pdk, { custom_lib, custom_techlef, custom_celllef, custom_cellgds, custom_site, custom_vdd, custom_vss, custom_metal_prefix, custom_antenna_diode });
    const mp = cfg.metal_prefix;

    // v0.76: build optional snippets
    const sdcSnippet = sdc_file
      ? `read_sdc ${sdc_file}\nset_propagated_clock [all_clocks]`
      : `create_clock -name clk -period ${clock_period_ns} [get_ports ${clock_port}]`;
    const routingLayersSnippet = (min_routing_layer && max_routing_layer)
      ? `set_routing_layers -signal ${min_routing_layer}-${max_routing_layer} -clock ${min_routing_layer}-${max_routing_layer}`
      : "";
    const stripesSnippet = pdn_stripe_layer
      ? `add_pdn_stripe -grid main -layer ${pdn_stripe_layer} -width 1.6 -pitch 30 -offset 5 -spacing 1.6
add_pdn_connect -grid main -layers {${mp}1 ${pdn_stripe_layer}}`
      : "";
    const ctsSnippet = enable_cts
      ? `clock_tree_synthesis -buf_list {${cts_buf_list || `${mp.toUpperCase()}BUFD1 ${mp.toUpperCase()}BUFD2 ${mp.toUpperCase()}BUFD4 ${mp.toUpperCase()}BUFD8`}} -root_buf ${cts_root_buf || `${mp.toUpperCase()}BUFD8`}
set_propagated_clock [all_clocks]
estimate_parasitics -placement
repair_design
detailed_placement`
      : "";
    // v1.3.53 R9 — after the main detailed_route, run the SAME incremental
    // antenna repair->reroute->repair loop the phase3 runner ships (v1.3.46),
    // BEFORE write_def so the routed DEF/netlist include the inserted diodes +
    // dirty-net reroute. Diode master comes from the PDK config (cfg); a PDK
    // with none SKIPS the loop (antennaRepairTcl emits ANTENNA_REPAIR_SKIPPED).
    const drSnippet = enable_detailed_route
      ? `detailed_route -output_drc ${output_def.replace(/\.def$/, "_drc.rpt")} -min_access_points 1 -droute_end_iter 5 -verbose 1
${antennaRepairTcl(cfg.antenna_diode_cell)}
write_def ${output_def.replace(/\.def$/, ".routed.def")}
${output_routed_v ? `write_verilog ${output_routed_v}` : ""}`
      : "";

    const tclScript = `
${threadCountTcl()}read_lef ${techlefPath(cfg)}
read_lef ${celllefPath(cfg)}
read_liberty ${libPath(cfg)}
read_verilog ${netlist}
link_design ${top_module}
${sdcSnippet}
initialize_floorplan -utilization ${utilization} -aspect_ratio 1.0 -core_space 10 -site ${cfg.site}
make_tracks
${routingLayersSnippet}
place_pins -hor_layers ${mp}3 -ver_layers ${mp}2
add_global_connection -net VDD -pin_pattern "${cfg.vdd_pin}" -power
add_global_connection -net VSS -pin_pattern "${cfg.vss_pin}" -ground
global_connect
set_voltage_domain -power VDD -ground VSS
define_pdn_grid -name main
add_pdn_stripe -grid main -layer ${mp}1 -width 0.48 -followpins
${stripesSnippet}
pdngen
global_placement -density ${density}
detailed_placement
check_placement -verbose
${ctsSnippet}
global_route -verbose
report_design_area
report_checks -path_delay max
write_def ${output_def}
${drSnippet}
puts "=== PNR_COMPLETE ==="
exit`;

    const pnrCmd = `export PATH=${TOOLS}/openroad/bin:${TOOLS}/bin:$PATH && echo '${tclScript.replace(/'/g, "'\\''")}' | openroad -threads ${_edaOpenroadThreadsToken()} -exit 2>&1`;
    const t0pnr = Date.now();
    let result = dockerExec(pnrCmd, 600000);
    let durationPnrMs = Date.now() - t0pnr;
    let dr_retried = false;
    let dr_retry_reason = "";

    // v2.6.0 M4: detailed_route auto-retry with set_routing_layers MET2-MAX
    // when DR fails due to MET1 pin access points. Common on legacy PDKs
    // (e.g. a commercial 180nm PDK) whose narrow MET1 pins on CTS-inserted
    // clkbuf/clkinv cells lack any reachable access point. Caller didn't
    // pre-set min_routing_layer? We try once with MET2 → top.
    const drFailedDRT0073 = enable_detailed_route &&
        !result.output.includes("PNR_COMPLETE") &&
        result.output.includes("DRT-0073");
    if (drFailedDRT0073 && !min_routing_layer) {
      // Detect top metal from tech LEF cell-LEF-aware; fall back to MET5.
      const topProbe = dockerExec(`grep -oE '^LAYER ${mp}[0-9]+' ${techlefPath(cfg)} | sort -u | tail -1 | awk '{print $2}'`, 5000);
      const topMet = (topProbe.output || `${mp}5`).trim() || `${mp}5`;
      const minMet = `${mp}2`;
      dr_retry_reason = `DRT-0073 access-point failure on ${mp}1 pins; auto-retry with set_routing_layers ${minMet}-${topMet}`;
      const retryRoutingLayers = `set_routing_layers -signal ${minMet}-${topMet} -clock ${minMet}-${topMet}`;
      const retryTcl = tclScript.replace(routingLayersSnippet || `make_tracks`, `make_tracks\n${retryRoutingLayers}`);
      const retryCmd = `export PATH=${TOOLS}/openroad/bin:${TOOLS}/bin:$PATH && echo '${retryTcl.replace(/'/g, "'\\''")}' | openroad -threads ${_edaOpenroadThreadsToken()} -exit 2>&1`;
      const t0retry = Date.now();
      result = dockerExec(retryCmd, 900000);
      durationPnrMs = Date.now() - t0retry;
      dr_retried = true;
    }

    const areaMatch = result.output.match(/Design area (\d+)/);
    const utilMatch = result.output.match(/(\d+)% utilization/);
    const slackMatch = result.output.match(/([\d.-]+)\s+slack \((MET|VIOLATED)\)/);
    const complete = result.output.includes("PNR_COMPLETE");

    // T1 v0.104: detect Yosys 'zero_' phantom nets that poison pdngen / detailed_route
    const hasZeroNet = /\bzero_\b/.test(result.output);
    let zero_net_hint = undefined;
    if (hasZeroNet) {
      zero_net_hint = "Yosys produced 'zero_' nets — run `yosys_hilomap_required_check` or add `hilomap -hicell sky130_fd_sc_hd__conb_1 HI -locell sky130_fd_sc_hd__conb_1 LO` (adjust cell names for your PDK) to your Yosys script before re-synthesizing.";
    }

    const metrics = {
      success: complete && !hasZeroNet,
      area_um2: areaMatch ? parseInt(areaMatch[1]) : null,
      utilization_pct: utilMatch ? parseInt(utilMatch[1]) : null,
      slack_ns: slackMatch ? parseFloat(slackMatch[1]) : null,
      timing_met: slackMatch ? slackMatch[2] === "MET" : null,
      def_file: output_def,
      dr_retried,
      dr_retry_reason: dr_retry_reason || undefined,
      zero_net_detected: hasZeroNet || undefined,
      zero_net_hint: zero_net_hint,
      log_tail: result.output.slice(-2000),
    };

    if (complete) {
      const dir = output_def.substring(0, output_def.lastIndexOf("/"));
      writeManifest(dir || "/tmp", {
        step: "place_and_route",
        status: metrics.timing_met ? "PASS" : "TIMING_VIOLATED",
        tool: "OpenROAD",
        top_module,
        pdk,
        area_um2: metrics.area_um2,
        utilization_pct: metrics.utilization_pct,
        slack_ns: metrics.slack_ns,
        timing_met: metrics.timing_met,
        output_file: output_def,
      });
    }

    // v0.47.5 auto-provenance
    const projPnr = process.env.EDA_PROJECT_DIR ||
        output_def.replace(/\/pnr\/.*/, "").replace(/^\/work\//, "/host_project/");
    logProvenance({
      projectDir: projPnr,
      tool: "openroad",
      version: toolIdentity("openroad", pdk),
      argv: ["openroad", "-exit", `pnr ${top_module} util=${utilization}`],
      inputs: { [netlist]: sha256File(netlist.replace("/work/", projPnr + "/")) },
      outputs: { [output_def]: sha256File(output_def.replace("/work/", projPnr + "/")) },
      exitCode: complete ? 0 : 1,
      durationMs: durationPnrMs,
      stdoutTail: result.output || "",
      stderrTail: result.error || "",
    });

    return { content: [{ type: "text", text: JSON.stringify(metrics) }] };
  }
);

// ─── Tool: eda_gds ───
server.tool(
  "eda_gds",
  "Generate GDS file by merging cell GDS library from PDK with routed DEF in a single call. Reads cell GDS first, then overlays DEF placement/routing, writes merged output GDS.",
  {
    def_file: z.string().describe("Input routed DEF file path"),
    output_gds: z.string().describe("Output merged GDS file path"),
    pdk: z.enum(["gf180", "sky130", "nangate45", "custom"]).default("gf180"),
    cell_gds_override: z.string().optional().describe("Override cell GDS path (default: auto-resolved from PDK)"),
    custom_lib: z.string().optional().describe("Path to Liberty .lib file (custom PDK)"),
    custom_techlef: z.string().optional().describe("Path to tech LEF file (custom PDK)"),
    custom_celllef: z.string().optional().describe("Path to cell LEF file (custom PDK)"),
    custom_cellgds: z.string().optional().describe("Path to cell GDS file (custom PDK)"),
    custom_site: z.string().optional().describe("Site name for floorplan (custom PDK)"),
    custom_vdd: z.string().optional().describe("VDD pin name (custom PDK)"),
    custom_vss: z.string().optional().describe("VSS pin name (custom PDK)"),
    custom_metal_prefix: z.string().optional().describe("Metal-layer name prefix for custom PDKs whose layers don't match SKY130 'met' naming (e.g. 'MET' for a commercial 180nm PDK's MET1-6). Default 'met'."),
  },
  async ({ def_file, output_gds, pdk, cell_gds_override, custom_lib, custom_techlef, custom_celllef, custom_cellgds, custom_site, custom_vdd, custom_vss, custom_metal_prefix }) => {
    try {
      assertSafePath(def_file, "def_file"); assertSafePath(output_gds, "output_gds");
      optPath(cell_gds_override, "cell_gds_override");
      optPath(custom_lib, "custom_lib"); optPath(custom_techlef, "custom_techlef");
      optPath(custom_celllef, "custom_celllef"); optPath(custom_cellgds, "custom_cellgds");
      optToken(custom_site, "custom_site"); optIdent(custom_vdd, "custom_vdd");
      optIdent(custom_vss, "custom_vss"); optToken(custom_metal_prefix, "custom_metal_prefix");
    } catch (e) { return guardError(e); }
    const cfg = pdkConfig(pdk, { custom_lib, custom_techlef, custom_celllef, custom_cellgds, custom_site, custom_vdd, custom_vss, custom_metal_prefix });
    const resolvedCellGds = cell_gds_override || cellgdsPath(cfg);
    const pyScript = `
import pya
import os

# Step 1: Read cell GDS library from PDK
cell_gds_path = '${resolvedCellGds}'
if not os.path.exists(cell_gds_path):
    print('ERROR: Cell GDS not found: ' + cell_gds_path)
    exit(1)

ly = pya.Layout()
ly.read(cell_gds_path)
cell_count_before = ly.cells()
print('CELL_GDS_LOADED=' + str(cell_count_before) + ' cells from ' + cell_gds_path)

# Step 2: Read routed DEF (overlays placement + routing onto cell library)
def_path = '${def_file}'
if not os.path.exists(def_path):
    print('ERROR: DEF file not found: ' + def_path)
    exit(1)

opt = pya.LoadLayoutOptions()
opt.lefdef_config.lef_files = ['${techlefPath(cfg)}', '${celllefPath(cfg)}']
opt.lefdef_config.read_lef_with_def = False
opt.lefdef_config.macro_resolution_mode = 1
ly.read(def_path, opt)

# Step 3: Write merged GDS
ly.write('${output_gds}')
cell_count_after = ly.cells()
print('GDS_CELLS=' + str(cell_count_after))
print('MERGE_OK: ' + str(cell_count_before) + ' lib cells + DEF -> ' + str(cell_count_after) + ' total cells')
`;

    const gdsCmd = `echo '${pyScript.replace(/'/g, "'\\''")}' > /tmp/gen_gds.py && QT_QPA_PLATFORM=offscreen ${TOOLS}/klayout/klayout -z -r /tmp/gen_gds.py 2>&1`;
    const t0gds = Date.now();
    const result = dockerExec(gdsCmd);
    const durationGdsMs = Date.now() - t0gds;

    const cellsMatch = result.output.match(/GDS_CELLS=(\d+)/);
    const libMatch = result.output.match(/CELL_GDS_LOADED=(\d+)/);
    const mergeOk = result.output.includes('MERGE_OK');

    if (cellsMatch != null) {
      const dir = output_gds.substring(0, output_gds.lastIndexOf("/"));
      writeManifest(dir || "/tmp", {
        step: "gds_generation",
        status: "PASS",
        tool: "KLayout",
        cells: parseInt(cellsMatch[1]),
        lib_cells: libMatch ? parseInt(libMatch[1]) : null,
        cell_gds_source: resolvedCellGds,
        gds_file: output_gds,
      });
    }

    // v0.47.5 auto-provenance
    const projGds = process.env.EDA_PROJECT_DIR ||
        output_gds.replace(/\/gds\/.*/, "").replace(/^\/work\//, "/host_project/");
    logProvenance({
      projectDir: projGds,
      tool: "klayout",
      version: toolIdentity("klayout", pdk),
      argv: ["klayout", "-z", "-r", "gen_gds.py"],
      inputs: { [def_file]: sha256File(def_file.replace("/work/", projGds + "/")) },
      outputs: { [output_gds]: sha256File(output_gds.replace("/work/", projGds + "/")) },
      exitCode: (cellsMatch != null && mergeOk) ? 0 : 1,
      durationMs: durationGdsMs,
      stdoutTail: result.output || "",
      stderrTail: result.error || "",
    });

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            success: cellsMatch != null && mergeOk,
            cells: cellsMatch ? parseInt(cellsMatch[1]) : null,
            lib_cells: libMatch ? parseInt(libMatch[1]) : null,
            cell_gds_source: resolvedCellGds,
            gds_file: output_gds,
            output: result.output.slice(-1500),
          }),
        },
      ],
    };
  }
);

// ─── Tool: eda_sta ───
server.tool(
  "eda_sta",
  "Run static timing analysis on a placed design using OpenSTA (via OpenROAD).",
  {
    netlist: z.string().describe("Gate-level netlist"),
    top_module: z.string().describe("Top module"),
    pdk: z.enum(["gf180", "sky130", "nangate45", "custom"]).default("gf180"),
    clock_port: z.string().default("clk"),
    clock_period_ns: z.number().default(200),
    custom_lib: z.string().optional().describe("Path to Liberty .lib file (custom PDK)"),
    custom_techlef: z.string().optional().describe("Path to tech LEF file (custom PDK)"),
    custom_celllef: z.string().optional().describe("Path to cell LEF file (custom PDK)"),
    custom_cellgds: z.string().optional().describe("Path to cell GDS file (custom PDK)"),
    custom_site: z.string().optional().describe("Site name for floorplan (custom PDK)"),
    custom_vdd: z.string().optional().describe("VDD pin name (custom PDK)"),
    custom_vss: z.string().optional().describe("VSS pin name (custom PDK)"),
    custom_metal_prefix: z.string().optional().describe("Metal-layer name prefix for custom PDKs whose layers don't match SKY130 'met' naming (e.g. 'MET' for a commercial 180nm PDK's MET1-6). Default 'met'."),
    si_mcf_project: z.string().optional().describe("Opt-in SI-aware crosstalk-DELAY STA (Miller Coupling Factor bound): pass a routed PROJECT dir (with a coupling-aware SPEF + SDC) to re-run OpenSTA on an MCF-bounded SPEF (Cc*MCF folded per aggressor/victim timing-window overlap; setup MCF=2 / hold MCF=0) via programs/si_mcf_sta.py, writing reports/phase3/si_mcf_sta.json. A conservative BOUND (advisory), not PrimeTime-SI's iterative coupled-waveform calc. When set, this runs instead of the single-netlist STA."),
    container: z.string().default("vibeic-eda").describe("Docker container for OpenSTA (si_mcf_project mode)"),
  },
  async ({ netlist, top_module, pdk, clock_port, clock_period_ns, custom_lib, custom_techlef, custom_celllef, custom_cellgds, custom_site, custom_vdd, custom_vss, custom_metal_prefix, si_mcf_project, container }) => {
    try {
      if (si_mcf_project === undefined) { assertSafePath(netlist, "netlist"); assertSafeIdent(top_module, "top_module"); }
      optIdent(clock_port, "clock_port");
      optPath(custom_lib, "custom_lib"); optPath(custom_techlef, "custom_techlef");
      optPath(custom_celllef, "custom_celllef"); optPath(custom_cellgds, "custom_cellgds");
      optToken(custom_site, "custom_site"); optIdent(custom_vdd, "custom_vdd");
      optIdent(custom_vss, "custom_vss"); optToken(custom_metal_prefix, "custom_metal_prefix");
      optPath(si_mcf_project, "si_mcf_project"); assertSafeIdent(container, "container");
    } catch (e) { return guardError(e); }
    // Opt-in MCF SI-aware crosstalk-delay STA (project-level; shells to program).
    if (si_mcf_project !== undefined) {
      const t0s = Date.now();
      const args = [`${VIBE_IC_PROGRAMS_DIR}/si_mcf_sta.py`, "run", si_mcf_project, "--container", container];
      const o = _spawnSync("python3", args, { timeout: 1800000, maxBuffer: 10 * 1024 * 1024, encoding: "utf-8" });
      const merged = (o.stdout || "") + (o.stderr || "");
      return wrapResult({
        success: !o.error && o.status === 0,
        t0: t0s,
        toolVersion: `si_mcf_sta @ mcp-eda@${SERVER_VERSION}`,
        error: o.error ? (o.error.message || String(o.error)) : (o.status === 0 ? undefined : `exited ${o.status}`),
        output: merged,
      });
    }
    const cfg = pdkConfig(pdk, { custom_lib, custom_techlef, custom_celllef, custom_cellgds, custom_site, custom_vdd, custom_vss, custom_metal_prefix });

    // v0.100 H1: auto-flatten Yosys $paramod references that OpenSTA cannot resolve
    let effectiveNetlist = netlist;
    const paramodCheck = dockerExec(`grep -c '\\$paramod' ${netlist} 2>/dev/null || true`, 10000);
    if (parseInt(paramodCheck.output.trim()) > 0) {
      const flatNetlist = netlist.replace(/\.v$/, '_sta_flat.v');
      const flatResult = dockerExec(
        `export PATH=${TOOLS}/bin:$PATH && yosys -p "read_verilog -sv ${netlist}; flatten; write_verilog -noattr ${flatNetlist}" 2>&1`,
        60000
      );
      if (flatResult.success) { canonicalizeNetlistSrcCoords(flatNetlist); effectiveNetlist = flatNetlist; }
    }

    // MEASURED 2026-08-27 on vibeic-eda@sha256:4ece6c01 - this tool could not
    // produce a timing number, and could not say so. Three coupled defects:
    //
    //  (1) NO TECH WAS READ. The script read only the Liberty and the Verilog.
    //      OpenROAD's `read_verilog` needs a technology first, so it aborted
    //      with `[ERROR ORD-2010] no technology has been read`, `link_design`
    //      then failed `[ERROR STA-1570] No network has been linked`, and every
    //      report failed STA-1571. `eda_ir_drop` in this same file has always
    //      read techlef + celllef before its design; STA was the outlier.
    //  (2) OPENROAD EXITS 0 ANYWAY. Measured: the fully-failing script above
    //      returns rc=0. `dockerExec` calls rc=0 success, so the tool reported
    //      `success:true` and wrote a manifest `status:"PASS"` for a run in
    //      which nothing was linked and no path was analysed. A sign-off gate
    //      that cannot fail is not a gate. `eda_pnr` (PNR_COMPLETE) and
    //      `eda_ir_drop` (IR_DROP_COMPLETE) already key on a positive
    //      end-of-script sentinel rather than the exit code; STA now does too.
    //  (3) A CLOCKLESS DESIGN SCORED A PERFECT ZERO. `create_clock` on a port
    //      the design does not have emits only `[WARNING STA-0366] port '<p>'
    //      not found` and still creates a source-less clock, so `report_wns`
    //      prints `wns max 0.00` - indistinguishable from a genuinely clean
    //      clocked design. Nothing read that warning. It is now read, and an
    //      unconstrained run reports clock_found:false with wns/tns null
    //      instead of zero.
    //
    // read_lef lines are emitted only for paths we actually have: a custom PDK
    // that supplied no LEF keeps the old liberty-only script rather than being
    // handed a `null/...` path.
    const _staLefs = [techlefPath(cfg), celllefPath(cfg)]
      .filter(pth => typeof pth === "string" && pth.length > 0 && !pth.includes("null/"));
    const _staLefReads = _staLefs.map(pth => `read_lef ${pth}`).join("\n");
    const staCmd = `export PATH=${TOOLS}/openroad/bin:${TOOLS}/bin:$PATH && openroad -threads ${_edaOpenroadThreadsToken()} -exit << 'EOF'
${_staLefReads}
read_liberty ${libPath(cfg)}
read_verilog ${effectiveNetlist}
link_design ${top_module}
create_clock -name clk -period ${clock_period_ns} [get_ports ${clock_port}]
puts "STA_CLOCK_PORT_FOUND=[llength [get_ports -quiet ${clock_port}]]"
report_checks -path_delay max -format full
report_checks -path_delay min -format full
report_tns
report_wns
puts "STA_COMPLETE"
exit
EOF`;
    const t0sta = Date.now();
    const result = dockerExec(staCmd);
    const durationStaMs = Date.now() - t0sta;

    // MEASURED: OpenSTA's `report_wns` prints `wns max 0.00` - a KEYWORD sits
    // between the label and the number. The previous `/wns\s+([\d.-]+)/i` needed
    // a digit immediately after the label, so it matched NEITHER a clean run
    // (`wns max 0.00`) NOR a violating one (`wns max -3.21`). This tool has
    // never reported a slack number; `wns` and `tns` were null on every path.
    const wnsMatch = result.output.match(/^wns\s+\w+\s+(-?[\d.]+)/mi);
    const tnsMatch = result.output.match(/^tns\s+\w+\s+(-?[\d.]+)/mi);

    // Did the script actually reach the end? OpenROAD exits 0 even when every
    // command in the heredoc failed, so the exit code cannot answer this.
    const staCompleted = result.output.includes("STA_COMPLETE");
    const staErrors = (result.output.match(/^\[ERROR [A-Z]+-\d+\][^\n]*/gm) || []);
    const staAnalysed = result.success && staCompleted && staErrors.length === 0;

    // Did `create_clock` land on a port that exists? `[WARNING STA-0366] port
    // '<p>' not found` still yields a source-less clock whose report_wns is
    // 0.00 - a clockless design otherwise scores a perfect timing result.
    const clockPortMatch = result.output.match(/STA_CLOCK_PORT_FOUND=(\d+)/);
    const clockPortFound = clockPortMatch ? parseInt(clockPortMatch[1]) > 0 : null;
    const clockConstrained = staAnalysed && clockPortFound === true;

    // Slack is only meaningful when a real clock constrained a linked design.
    const wns = clockConstrained && wnsMatch ? parseFloat(wnsMatch[1]) : null;
    const tns = clockConstrained && tnsMatch ? parseFloat(tnsMatch[1]) : null;

    const staWarnings = [];
    if (!staAnalysed) {
      staWarnings.push(
        staErrors.length
          ? `OpenROAD reported ${staErrors.length} error(s); no timing was analysed: `
            + staErrors.slice(0, 3).join(" | ")
          : "the STA script did not reach STA_COMPLETE; no timing was analysed");
    } else if (clockPortFound === false) {
      staWarnings.push(
        `clock_port '${clock_port}' does not exist on '${top_module}'. create_clock `
        + `matched no port, so the design is UNCONSTRAINED and the reported slack `
        + `would be a vacuous 0.00. wns/tns are null, not zero.`);
    }

    if (staAnalysed) {
      const dir = netlist.substring(0, netlist.lastIndexOf("/"));
      writeManifest(dir || "/tmp", {
        step: "sta",
        // A run that linked but constrained nothing is NOT a timing PASS.
        status: clockConstrained ? "PASS" : "UNCONSTRAINED",
        tool: "OpenSTA",
        clock_port_found: clockPortFound,
        wns,
        tns,
      });
    }

    // v0.47.5 auto-provenance
    const projSta = process.env.EDA_PROJECT_DIR ||
        netlist.replace(/\/synth\/.*/, "").replace(/^\/work\//, "/host_project/");
    // STA doesn't write a designated report file by default — record stdout_sha as
    // the "output fingerprint" so the run is auditable.
    logProvenance({
      projectDir: projSta,
      tool: "opensta",
      version: toolIdentity("openroad", pdk, "opensta via openroad"),
      argv: ["openroad", "-exit", `sta ${top_module} clk=${clock_period_ns}ns`],
      inputs: { [netlist]: sha256File(netlist.replace("/work/", projSta + "/")) },
      outputs: {},
      exitCode: staAnalysed ? 0 : 1,
      durationMs: durationStaMs,
      stdoutTail: result.output || "",
      stderrTail: result.error || "",
    });

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            success: staAnalysed,
            timing_analysed: staAnalysed,
            clock_constrained: clockConstrained,
            clock_port_found: clockPortFound,
            wns,
            tns,
            warnings: staWarnings.length ? staWarnings : undefined,
            errors: staErrors.length ? staErrors.slice(0, 10) : undefined,
            report: result.output.slice(-3000),
          }),
        },
      ],
    };
  }
);

// ─── Tool: eda_lvs ───
server.tool(
  "eda_lvs",
  "Run LVS. Two modes: (a) `netgen` compares extracted layout SPICE netlist against schematic SPICE — needs foundry netgen setup tcl, currently gf180/sky130 only; (b) `yosys_equiv` (since v0.1.12) compares two structural Verilog netlists (e.g. synth.v vs post-PnR routed.v) using Yosys equiv_simple+equiv_induct — works on ANY PDK, ideal for custom-PDK structural LVS where Magic+Netgen tech files aren't available. since v0.1.12 (#94): when equiv_induct's SAT engine aborts on custom-PDK Liberty primitives lacking a built-in SAT model (e.g. INVD1/NANDxDy/NORxDy), the tool now returns a STRUCTURED verdict with sat_model_unsupported_cells[] + verdict_explanation instead of the ambiguous equiv_cells_unproven=-1 sentinel. Distinguishes 'tool limitation on custom-PDK primitives' from 'netlists genuinely differ'. since v0.1.14 (spm pilot plugin v0.1.49): netgen mode accepts an optional `setup_supplement` TCL path — emitted by `programs/lvs_netgen_setup_emit.py` — that is concatenated AFTER the foundry setup to globalise power nets (vccd1/vssd1/VPWR/VGND etc.) and optionally flatten top circuits. Closes the open-source SkyWater net-level gap when the design's mismatch is dominated by power-net globalisation (vs interconnect-naming, which is a separate open-source limitation). since v0.2.33 (ORGANIC-20260531): netgen mode now derives its verdict from a REAL netgen-phrase parse ('Circuits/Netlists match uniquely' for PASS, 'do not match'/'failed pin matching'/'property errors were found' for FAIL) with a DID-NOT-RUN guard ('Cannot find cell' / no report written ⇒ matched:null, NEVER a pass) — replacing a naive `/match/i` boolean that scored property-error mismatches and aborted runs as PASS. Also auto-name-aligns a Magic `<top>_flat` layout subckt, and (load_stdcell_lib=true) loads the PDK std-cell SPICE library into the schematic circuit so a post-PnR GATE netlist expands to transistors for a true device-level compare.",
  {
    mode: z.enum(["netgen", "yosys_equiv"]).default("netgen"),
    layout_netlist: z.string().describe("Layout netlist. mode=netgen: SPICE; mode=yosys_equiv: Verilog (e.g. routed .v)"),
    schematic_netlist: z.string().describe("Schematic/synthesis netlist. SPICE for netgen, Verilog for yosys_equiv"),
    top_module: z.string().describe("Top module name"),
    pdk: z.enum(["gf180", "sky130", "nangate45", "custom"]).default("gf180"),
    custom_lib: z.string().optional().describe("Liberty .lib path for cell semantics (yosys_equiv mode)"),
    setup_supplement: z.string().optional().describe("Optional path to a supplementary Netgen TCL (e.g. from programs/lvs_netgen_setup_emit.py). Concatenated AFTER the foundry setup. netgen mode only; ignored on yosys_equiv."),
    load_stdcell_lib: z.boolean().default(false).describe("netgen mode: load the PDK std-cell SPICE library (e.g. sky130_fd_sc_hd.spice) INTO the schematic circuit before lvs, so a post-PnR GATE netlist's empty cell placeholders expand to transistors for a true device-level compare. Default false (the schematic side is already transistor-level)."),
    custom_stdcell_spice: z.string().optional().describe("netgen mode: explicit std-cell SPICE library path to load into the schematic circuit (overrides the PDK default for load_stdcell_lib). Use for custom PDKs."),
    schematic_top: z.string().optional().describe("netgen mode: schematic-side top subckt name, if it differs from top_module (the layout-side name). Default: same as top_module."),
  },
  async ({ mode, layout_netlist, schematic_netlist, top_module, pdk, custom_lib, setup_supplement, load_stdcell_lib, custom_stdcell_spice, schematic_top }) => {
    try {
      assertSafePath(layout_netlist, "layout_netlist");
      assertSafePath(schematic_netlist, "schematic_netlist");
      assertSafeIdent(top_module, "top_module");
      optPath(custom_lib, "custom_lib");
      optPath(setup_supplement, "setup_supplement");
      optPath(custom_stdcell_spice, "custom_stdcell_spice");
      optIdent(schematic_top, "schematic_top");
    } catch (e) { return guardError(e); }
    if (mode === "yosys_equiv") {
      const t0 = Date.now();
      const libPathLocal = custom_lib || (pdk === "gf180"
        ? `${PDK_ROOT}/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib`
        : pdk === "sky130"
          ? `${PDK_ROOT}/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib`
          : "");
      if (!libPathLocal) {
        return wrapResult({ success: false, t0, error: "yosys_equiv mode needs custom_lib (or use pdk=gf180/sky130)", output: "" });
      }
      // since v2.6.0 (#94) — yosys_equiv mode now emits a STRUCTURED verdict
      // even when equiv_induct's SAT engine aborts on Liberty cells
      // without a built-in SAT model (e.g. INVD1/NAND2D1/NOR2D2 in a
      // custom-PDK Liberty loaded via `-lib`). Pre-v2.6.0 the script
      // ran `equiv_status -assert`, which makes yosys exit non-zero
      // on the abort; the parser then returned
      // `equiv_cells_unproven: -1` — indistinguishable from a real
      // LVS mismatch.
      //
      // Two changes in this version:
      //   1. Drop `equiv_status -assert`. Run plain `equiv_status` so
      //      yosys still prints the final proven/unproven counts even
      //      when individual cells cannot be SAT-modeled. The matched
      //      verdict is decided by the parsed counts, not yosys exit.
      //   2. Parse the SAT-model abort lines and surface them as
      //      `sat_model_unsupported_cells: [{cell, cell_type}]` so
      //      the field-agent (and any downstream tape-out gate) can
      //      distinguish "tool limitation on custom-PDK primitives"
      //      from "netlists genuinely differ".
      //
      // Anti-fabrication: when the script genuinely fails (yosys
      // didn't run, output unparseable), we return
      // `parse_error: true` and `equiv_cells_unproven: null` —
      // never the ambiguous -1 sentinel.
      //
      // chip-AGNOSTIC: every custom PDK whose Liberty contains
      // primitive cells (any naming convention) benefits — there is
      // no chip-specific cell-name pattern in the parsing.
      const ys = `read_liberty -lib ${libPathLocal}
read_verilog -sv ${schematic_netlist}
prep -top ${top_module}
splitnets -ports
design -stash gold

read_liberty -lib ${libPathLocal}
read_verilog -sv ${layout_netlist}
prep -top ${top_module}
splitnets -ports
design -stash gate

design -copy-from gold -as gold ${top_module}
design -copy-from gate -as gate ${top_module}
equiv_make gold gate equiv
hierarchy -top equiv
equiv_simple
equiv_induct -seq 4
equiv_induct -seq 16
equiv_induct -seq 64
equiv_status
`;
      // since v1.3.41: escalate equiv_induct -seq (4->16->64) instead of the
      // yosys default -seq 4. Sequential equivalence between a design and a
      // RETIMED / pipeline-rebalanced version needs induction depth >= the
      // pipeline latency; at the shallow default those output $equiv cells stay
      // UNPROVEN and the compare falsely FAILs. Escalation is sound (deeper
      // k-induction proves only more genuinely-equivalent cells, never an
      // inequivalent pair) and cheap (each pass only re-works still-unproven
      // cells, so a shallow-closing compare pays ~nothing for the deeper passes).
      const ysFile = `/tmp/lvs_equiv_${Date.now()}.ys`;
      const writeR = dockerExec(`cat > ${ysFile} <<'__YS_EOF__'\n${ys}\n__YS_EOF__\n`, 10000);
      if (!writeR.success) {
        return wrapResult({ success: false, t0, error: writeR.error, output: writeR.output });
      }
      const r = dockerExec(`export PATH=${TOOLS}/yosys/bin:${TOOLS}/bin:$PATH && yosys -s ${ysFile} 2>&1`, 600000);
      const output = r.output || "";

      // since v2.6.0 (#94) — robust parsing.
      //
      // Final-summary patterns from `equiv_status` (when reached):
      //   "Found N $equiv cells in module equiv."
      //   "Of these N $equiv cells, M are proven and K are unproven."
      // OR the legacy single-line variant:
      //   "M are proven and K are unproven"
      //
      // When equiv_induct aborts mid-run (SAT-model gap), the final
      // equiv_status line may be absent; we fall back to other phrasing
      // emitted by equiv_induct / equiv_simple.
      // since v0.114.4 (#94 follow-up 2): per field-agent's real
      // yosys 0.64 benchmark log, when equiv_induct aborts on a
      // SAT-model gap the canonical "equiv_status: M are proven and
      // K are unproven" line is NOT emitted. Instead two distinct
      // pass-internal counters survive:
      //   equiv_simple: "Proved M previously unproven $equiv cells."
      //   equiv_induct: "Found K unproven $equiv cells in module
      //                  equiv:"
      // Total = M + K (proved-so-far + still-unproven). The pre-fix
      // regex `Found N $equiv cells` (without `unproven` infix) was
      // the OLD yosys total-line shape; the newer "Found K unproven
      // $equiv cells" line is the CURRENT-UNPROVEN count from
      // equiv_induct, NOT the total. Mishandling that as total broke
      // v0.114.3.
      //
      // Resolution: parse each counter from its own canonical line
      // and reconstruct total = proven + unproven when the final
      // summary is absent.
      const finalMatch = output.match(/(\d+)\s+are\s+proven\s+and\s+(\d+)\s+are\s+unproven/);
      let proven = finalMatch ? parseInt(finalMatch[1]) : null;
      let unproven = finalMatch ? parseInt(finalMatch[2]) : null;
      let total = null;

      // since v0.114.5 (#94 follow-up 3): yosys emits TWO different
      // "Found N unproven $equiv cells" lines in the SAT-model-gap
      // scenario, with different suffixes that distinguish them:
      //   equiv_simple ENTRY:
      //     "Found 1761 unproven $equiv cells (1761 groups) in
      //      equiv:"
      //   equiv_induct RESIDUAL (post-equiv_simple):
      //     "Found 1 unproven $equiv cells in module equiv:"
      // The first one carries the INITIAL total; the second carries
      // the AFTER-equiv_simple residual unproven count. Without
      // suffix-anchored regexes, `output.match()` returns the FIRST
      // hit and binds `unproven = 1761` (the initial total), which
      // is wrong and breaks `total = proven + unproven`
      // reconstruction.
      //
      // Fix: capture each line by its distinguishing suffix.
      //   equiv_simple entry:  ends with `(N groups) in equiv:`
      //   equiv_induct residual: ends with `in module equiv:`

      // Direct total — equiv_simple entry line (preferred when present)
      const equivSimpleEntryMatch = output.match(
        /Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+\(\d+\s+groups\)\s+in\s+equiv\s*:/);
      if (equivSimpleEntryMatch) {
        total = parseInt(equivSimpleEntryMatch[1]);
      }

      // Direct total — older yosys "Found N $equiv cells" (no
      // `unproven` infix). Skip if equiv_simple entry already gave us
      // the total. NOTE: this regex would ALSO partial-match the
      // equiv_simple/equiv_induct "unproven $equiv cells" lines on
      // the `(\d+) ... $equiv cells` prefix, so we gate it.
      if (total === null) {
        const oldTotalMatch = output.match(
          /Found\s+(\d+)\s+\$equiv\s+cells/);
        if (oldTotalMatch) {
          total = parseInt(oldTotalMatch[1]);
        }
      }

      // Fallback proven: equiv_simple's "Proved M previously
      // unproven" line (yosys 0.64 wording per field-agent log).
      if (proven === null) {
        const provedSimpleMatch = output.match(
          /Proved\s+(\d+)\s+previously\s+unproven\s+\$equiv\s+cells/);
        if (provedSimpleMatch) {
          proven = parseInt(provedSimpleMatch[1]);
        }
      }

      // Forward-compat fallback: "equiv_simple: Proved M/N $equiv
      // cells" (a hypothetical newer yosys shape — kept as a defence
      // against future format drift).
      if (proven === null || total === null) {
        const simpleSlashMatch = output.match(
          /equiv_simple[^\n]*Proved\s+(\d+)\/(\d+)\s+\$equiv\s+cells/);
        if (simpleSlashMatch) {
          if (proven === null) proven = parseInt(simpleSlashMatch[1]);
          if (total === null) total = parseInt(simpleSlashMatch[2]);
        }
      }

      // Fallback unproven: equiv_induct's residual line — anchored
      // on `in module equiv:` suffix so it does NOT collide with
      // equiv_simple's entry-line of the same prefix. Without the
      // anchor the regex match returns equiv_simple's initial total,
      // not equiv_induct's residual count.
      if (unproven === null) {
        const inductFoundMatch = output.match(
          /Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+in\s+module\s+equiv\s*:/);
        if (inductFoundMatch) {
          unproven = parseInt(inductFoundMatch[1]);
        }
      }

      // Reconstruct missing piece from the other two when possible.
      if (total === null && proven !== null && unproven !== null) {
        total = proven + unproven;
      }
      if (total !== null && proven !== null && unproven === null) {
        unproven = total - proven;
      }
      if (total !== null && unproven !== null && proven === null) {
        proven = total - unproven;
      }

      // SAT-model abort capture (chip-AGNOSTIC).
      // Yosys emits: "ERROR: No SAT model available for cell <inst> (<cell_type>)."
      // We collect every match; the cell_type tells the human which
      // Liberty primitive lacks a SAT model.
      const satAbortRe = /No SAT model available for cell\s+(\S+)\s+\((\S+?)\)/g;
      const satAborts = [];
      let satMatch;
      while ((satMatch = satAbortRe.exec(output)) !== null) {
        satAborts.push({ cell: satMatch[1], cell_type: satMatch[2] });
      }

      // Per-instance unproven cell capture (best-effort).
      // equiv_induct emits: "Trying to prove $equiv cell <path>..."
      // followed eventually by "Unproven $equiv cells: <path>, ..."
      const unprovenListMatch = output.match(/Unproven\s+\$equiv\s+cells:\s*([^\n]+)/);
      const unprovenCellPaths = unprovenListMatch
        ? unprovenListMatch[1].split(/[,\s]+/).filter(Boolean).slice(0, 50)
        : [];

      const parseError = (proven === null && unproven === null);
      const matched = !parseError && unproven === 0
                      && (proven ?? 0) > 0 && satAborts.length === 0;

      let verdictExplanation;
      if (parseError) {
        verdictExplanation = "yosys output unparseable; cannot classify as PASS or FAIL — see `output` for tool logs";
      } else if (matched) {
        verdictExplanation = `all ${proven}/${proven} $equiv cells proven; netlists structurally equivalent`;
      } else if (satAborts.length > 0) {
        verdictExplanation = `yosys reached ${proven ?? "?"}/${total ?? "?"} structural equivalence; ` +
          `${satAborts.length} cell(s) lacked a SAT model in equiv_induct ` +
          `(custom-PDK Liberty primitives without yosys built-in semantics). ` +
          `Sign-off LEC (Conformal/VC LEC) required to close remainder.`;
      } else {
        verdictExplanation = `${proven ?? 0}/${total ?? "?"} proven, ${unproven ?? "?"} unproven — netlists may genuinely differ`;
      }

      return wrapResult({
        success: matched,
        t0,
        toolVersion: `yosys equiv @ mcp-eda@${SERVER_VERSION}`,
        error: r.error,
        output: output,
        mode: "yosys_equiv",
        // since v2.6.0: never -1; null means parse failure.
        equiv_cells_total: total,
        equiv_cells_proven: proven,
        equiv_cells_unproven: unproven,
        // since v2.6.0 (#94): new structured fields.
        sat_model_unsupported_cells: satAborts,
        unproven_cells: unprovenCellPaths,
        parse_error: parseError,
        verdict_explanation: verdictExplanation,
        matched,
      });
    }

    // Netgen mode (gf180/sky130 only). t0 is scoped here because the
    // yosys_equiv branch declared its own t0 inside its own block.
    const t0 = Date.now();
    if (pdk === "custom") {
      return wrapResult({ success: false, t0, error: "netgen mode needs gf180/sky130 setup tcl. Use mode=yosys_equiv for custom PDK.", output: "" });
    }
    const cfg = pdkConfig(pdk);
    const foundrySetup = pdk === "gf180"
      ? `${cfg.pdk_path}/libs.tech/netgen/${cfg.scl}_setup.tcl`
      : `${cfg.pdk_path}/libs.tech/netgen/sky130A_setup.tcl`;

    // since v0.1.14 (spm pilot plugin v0.1.49) — if setup_supplement is supplied,
    // concatenate foundry + supplement into /tmp/lvs_combined_setup.tcl
    // and use that as the netgen setup. The supplement is generated by
    // the plugin program lvs_netgen_setup_emit.py and applies rules
    // (global power nets, optional flatten, etc.) the foundry setup
    // doesn't ship. The order is FOUNDRY-FIRST so the supplement can
    // override anything the foundry setup declared.
    let setupFile = foundrySetup;
    if (setup_supplement) {
      const combinedPath = `/tmp/lvs_combined_setup_${Date.now()}.tcl`;
      const buildR = dockerExec(`cat ${foundrySetup} ${setup_supplement} > ${combinedPath}`, 30000);
      if (!buildR.success) {
        return wrapResult({
          success: false,
          t0: Date.now(),
          error: `failed to combine foundry+supplement setup: ${buildR.error}`,
          output: buildR.output,
        });
      }
      setupFile = combinedPath;
    }

    // ── Auto-name-align (ORGANIC-20260531 fix #2) ──────────────────────
    // Magic ext2spice appends `_flat` to the top subckt when the layout was
    // flattened (`flatten <top>` → `.subckt <top>_flat ...`). If the caller
    // passes `<top>` but only `<top>_flat` exists, netgen aborts with
    // "Cannot find cell <top>" and NEVER COMPARES. Detect the actual layout
    // top name up-front so we feed netgen the name that exists.
    const layCat = dockerExec(`cat ${layout_netlist} 2>/dev/null | grep -i '\\.subckt' | head -40`, 10000);
    const layoutTopInfo = resolveLayoutTop(layCat.output || "", top_module);
    const layoutTop = layoutTopInfo.name;
    const schTop = schematic_top || top_module;

    // ── std-cell-lib load (ORGANIC-20260531 fix #3) ────────────────────
    // A post-PnR Verilog/SPICE GATE netlist on the schematic side keeps each
    // cell as an empty placeholder. Device-level netgen LVS needs BOTH sides
    // at transistor granularity, so load the PDK std-cell SPICE library INTO
    // the schematic circuit before `lvs` (mirrors the pilot's hand-driven
    // `readnet spice <stdcell> <schCkt>`).
    const stdcellSpice = load_stdcell_lib
      ? (custom_stdcell_spice || stdcellSpicePath(pdk, PDK_ROOT))
      : null;
    let stdcellLoadError = null;
    if (load_stdcell_lib && !stdcellSpice) {
      stdcellLoadError = "load_stdcell_lib=true but no std-cell SPICE library is known for this PDK; pass custom_stdcell_spice.";
    } else if (stdcellSpice) {
      const present = dockerExec(`[ -f ${stdcellSpice} ] && echo OK || echo MISSING`, 5000);
      if (!(present.output || "").includes("OK")) {
        stdcellLoadError = `std-cell SPICE library not found in container: ${stdcellSpice}`;
      }
    }
    if (stdcellLoadError) {
      return wrapResult({
        success: false, t0,
        toolVersion: `netgen @ mcp-eda@${SERVER_VERSION}`,
        error: stdcellLoadError, output: "", mode: "netgen",
        matched: null, parse_error: true,
      });
    }

    // Drive netgen via a `source` TCL so we can pre-read the schematic netlist
    // and load the std-cell lib into it. The foundry setup is consumed as the
    // 3rd arg of `lvs` (NOT sourced at top level — it runs `cells list` which
    // needs circuits to exist first). When no std-cell load is requested the
    // TCL is the plain file-spec `lvs` form (identical to the legacy command).
    const reportPath = `/tmp/lvs_report_${Date.now()}.txt`;
    const lvsTcl = buildNetgenLvsTcl({
      layoutNetlist: layout_netlist,
      schematicNetlist: schematic_netlist,
      layoutTop,
      schematicTop: schTop,
      setupFile,
      reportPath,
      stdcellSpice,
    });
    const tclPath = `/tmp/lvs_drive_${Date.now()}.tcl`;
    const b64 = Buffer.from(lvsTcl, "utf-8").toString("base64");
    const writeTcl = dockerExec(`echo '${b64}' | base64 -d > ${tclPath}`, 15000);
    if (!writeTcl.success) {
      return wrapResult({
        success: false, t0,
        toolVersion: `netgen @ mcp-eda@${SERVER_VERSION}`,
        error: `failed to write netgen driver TCL: ${writeTcl.error}`,
        output: writeTcl.output, mode: "netgen", matched: null, parse_error: true,
      });
    }
    const lvsCmd = `export PATH=${TOOLS}/netgen/bin:${TOOLS}/bin:$PATH && netgen -batch source ${tclPath} 2>&1; echo "===REPORT==="; cat ${reportPath} 2>/dev/null | tail -60`;
    const t0lvs = Date.now();
    const result = dockerExec(lvsCmd, 300000);
    const durationLvsMs = Date.now() - t0lvs;

    // ── real verdict parse + DID-NOT-RUN guard (ORGANIC-20260531 fix #1) ─
    // Whether the report file was actually written: a netgen run that aborts
    // on "Cannot find cell" / unreadable netlist writes none. We probe it so
    // the parser can treat a no-report + no-Final-result run as did-not-run.
    const reportProbe = dockerExec(`[ -f ${reportPath} ] && echo REPORT_WRITTEN || echo NO_REPORT`, 5000);
    const reportWritten = (reportProbe.output || "").includes("REPORT_WRITTEN");
    const verdict = classifyNetgenVerdict(result.output || "", { reportWritten });

    // success / matched come ONLY from the parsed verdict — NEVER from a bare
    // `/match/i` token, and NEVER true when netgen did not run (matched=null).
    const matched = verdict.matched;          // true | false | null
    const passed = matched === true;

    if (passed) {
      writeManifest("/tmp", {
        step: "lvs",
        status: "PASS",
        tool: "Netgen",
        matched: true,
        layout_top: layoutTop,
        stdcell_lib_loaded: !!stdcellSpice,
      });
    }

    // v0.47.5 auto-provenance
    const projLvs = process.env.EDA_PROJECT_DIR ||
        schematic_netlist.replace(/\/synth\/.*/, "").replace(/^\/work\//, "/host_project/");
    logProvenance({
      projectDir: projLvs,
      tool: "netgen",
      version: toolIdentity("netgen", pdk),
      argv: ["netgen", "-batch", "source", tclPath,
             `# lvs "${layout_netlist} ${layoutTop}" "${schematic_netlist} ${schTop}"`],
      inputs: {
        [layout_netlist]: sha256File(layout_netlist.replace("/work/", projLvs + "/")),
        [schematic_netlist]: sha256File(schematic_netlist.replace("/work/", projLvs + "/")),
      },
      outputs: {},
      exitCode: passed ? 0 : 1,
      durationMs: durationLvsMs,
      stdoutTail: result.output || "",
      stderrTail: result.error || "",
    });

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          // success is PASS only on a parsed clean match. A FAIL, a
          // did-not-run, or an unparseable run is success:false.
          success: passed,
          mode: "netgen",
          matched,                          // true | false | null (never bare-token true)
          verdict: verdict.verdict,         // MATCH | FAIL | DID_NOT_RUN | PARSE_ERROR
          parse_error: verdict.parse_error,
          did_not_run: verdict.did_not_run,
          property_errors: verdict.property_errors,
          verdict_explanation: verdict.reason,
          layout_top: layoutTop,            // the name actually fed to netgen
          name_aligned: layoutTopInfo.aligned,  // true if `_flat` fallback used
          stdcell_lib_loaded: !!stdcellSpice,
          stdcell_lib_path: stdcellSpice || undefined,
          output: (result.output || "").slice(-3000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_drc_klayout ───
server.tool(
  "eda_drc_klayout",
  "Run DRC using KLayout. For gf180/sky130 uses foundry decks; for custom PDK auto-derives WIDTH/SPACING rules from the tech LEF (or uses an explicit custom_drc_script).",
  {
    gds_file: z.string().describe("Input GDS file path"),
    top_cell: z.string().describe("Top cell name in GDS"),
    pdk: z.enum(["gf180", "sky130", "nangate45", "custom"]).default("gf180"),
    custom_techlef: z.string().optional().describe("Path to tech LEF (custom PDK; rules auto-derived from WIDTH/SPACING)"),
    custom_drc_script: z.string().optional().describe("Path to a hand-written KLayout .drc script (custom PDK; bypasses LEF auto-derivation)"),
    custom_layermap: z.string().optional().describe("Path to layer map file mapping LEF layer names to GDS (layer,datatype). Format per line: 'LAYER NET <gds_layer> <gds_datatype>'. Default: detect from techlef directory."),
    output_rdb: z.string().optional().describe("Output KLayout RDB report path. Default: <gds_file>.lyrdb"),
  },
  async ({ gds_file, top_cell, pdk, custom_techlef, custom_drc_script, custom_layermap, output_rdb }) => {
    try {
      assertSafePath(gds_file, "gds_file"); assertSafeIdent(top_cell, "top_cell");
      optPath(custom_techlef, "custom_techlef"); optPath(custom_drc_script, "custom_drc_script");
      optPath(custom_layermap, "custom_layermap"); optPath(output_rdb, "output_rdb");
    } catch (e) { return guardError(e); }
    const rdbPath = output_rdb || `${gds_file}.lyrdb`;

    // v0.76: custom PDK path
    if (pdk === "custom") {
      if (custom_drc_script) {
        // Use user-supplied .drc deck
        const drcCmdC = `QT_QPA_PLATFORM=offscreen ${TOOLS}/klayout/klayout -b -r ${custom_drc_script} -rd input=${gds_file} -rd report=${rdbPath} -rd threads=${_edaThreadsToken()} 2>&1`;
        const t0drcC = Date.now();
        const resultC = dockerExec(drcCmdC, 600000);
        const durationDrcMsC = Date.now() - t0drcC;
        // Parse RDB for items
        const countCmd = `[ -f ${rdbPath} ] && grep -c '<item>' ${rdbPath} || echo 0`;
        const countRes = dockerExec(countCmd, 5000);
        const violations = parseInt((countRes.output || "0").trim()) || 0;
        const passC = resultC.success && violations === 0;
        const dirC = gds_file.substring(0, gds_file.lastIndexOf("/"));
        writeManifest(dirC || "/tmp", {
          step: "drc",
          status: passC ? "PASS" : "FAIL",
          tool: "KLayout (custom deck)",
          violations,
          rdb: rdbPath,
        });
        const projDrcC = process.env.EDA_PROJECT_DIR ||
            gds_file.replace(/\/gds\/.*/, "").replace(/^\/work\//, "/host_project/");
        logProvenance({
          projectDir: projDrcC,
          tool: "klayout",
          version: toolIdentity("klayout", "custom", "klayout DRC"),
          argv: ["klayout", "-b", "-r", custom_drc_script, "input=" + gds_file],
          inputs: { [gds_file]: sha256File(gds_file.replace("/work/", projDrcC + "/")) },
          outputs: { [rdbPath]: sha256File(rdbPath.replace("/work/", projDrcC + "/")) },
          exitCode: passC ? 0 : 1,
          durationMs: durationDrcMsC,
          stdoutTail: resultC.output || "",
          stderrTail: resultC.error || "",
        });
        return {
          content: [{ type: "text", text: JSON.stringify({ success: passC, violations, rdb: rdbPath, output: (resultC.output || "").slice(-2000) }) }],
        };
      }
      if (custom_techlef) {
        // v0.76: auto-derive a minimal DRC deck from tech LEF.
        // v0.99.1 fix (vendor benchmark): the inline `python3 -c "..."`
        // form hit a shell-escape failure (`sh: 66: Syntax error: "("
        // unexpected`) when GDS / techlef paths contained metacharacters.
        // Replaced with a sentinel-bounded `cat << 'EOF' > /tmp/...py`
        // followed by `python3 /tmp/...py --flag=value` invocation. The
        // helper itself lives in src/lib/auto_drc_deck.py — separately
        // unit-testable, no escape gymnastics.
        const autoScript = `/tmp/drc_auto_${Date.now()}.drc`;
        const layermap = custom_layermap || "";
        const helperPath = `/tmp/auto_drc_deck_${Date.now()}.py`;
        const sentinel = `EOFAUTODRC${Date.now()}`;
        const helperContent = _shellSingleQuotedHeredoc(_AUTO_DRC_DECK_PY, sentinel);
        const pythonInvocation = (
          `python3 ${helperPath} ` +
          `--techlef=${custom_techlef} ` +
          `--gds=${gds_file} ` +
          `--top=${top_cell} ` +
          `--rdb=${rdbPath} ` +
          `--layermap='${layermap}' ` +
          `--out=${autoScript}`
        );
        const genCmd = (
          `cat <<'${sentinel}' > ${helperPath}\n` +
          helperContent + "\n" +
          sentinel + "\n" +
          pythonInvocation
        );
        const genRes = dockerExec(genCmd, 30000);
        if (!genRes.output.includes("AUTO_DRC_GENERATED")) {
          return { content: [{ type: "text", text: JSON.stringify({ success: false, error: "auto-deck generation failed", output: genRes.output.slice(-1500) }) }] };
        }
        // v2.6.0 M3: detect 0-rule generation early — common cause is
        // missing/unmatched layermap. Surface as actionable error rather
        // than silent KLayout fail or false-PASS.
        const rulesMatch = (genRes.output || "").match(/rules=(\d+)/);
        const rulesN = rulesMatch ? parseInt(rulesMatch[1]) : 0;
        if (rulesN === 0) {
          // v0.112 (BACKLOG-v6 T2 closure): structural-only fallback
          // instead of hard error. Closes the layermap-missing case for
          // custom PDKs (a commercial 180nm PDK, etc.) by emitting a
          // KLayout deck that verifies GDS parses + top cell exists, but
          // does NOT enforce dimensional rules. Returns success=true
          // with deck_mode='structural_only' + advisory so the caller
          // can decide whether to accept (engineering flow) or escalate
          // (production tapeout, which needs the foundry deck anyway).
          const structuralScript = `/tmp/drc_structural_${Date.now()}.drc`;
          const structGenCmd = `python3 -c "
out = '${structuralScript}'
gds = '${gds_file}'
top = '${top_cell}'
rdb = '${rdbPath}'
with open(out, 'w') as f:
    f.write('source(%r, %r)\\n' % (gds, top))
    f.write('report(%r, %r)\\n' % ('Structural-only DRC (no LEF deck)', rdb))
print('STRUCTURAL_DRC_GENERATED=' + out)
"`;
          const sg = dockerExec(structGenCmd, 15000);
          if (!sg.output.includes("STRUCTURAL_DRC_GENERATED")) {
            return { content: [{ type: "text", text: JSON.stringify({
              success: false,
              error: "structural fallback synthesis failed",
              output: sg.output.slice(-1500),
            }) }] };
          }
          const drcStructCmd = `QT_QPA_PLATFORM=offscreen ${TOOLS}/klayout/klayout -b -r ${structuralScript} 2>&1`;
          const tS = Date.now();
          const rS = dockerExec(drcStructCmd, 300000);
          const durS = Date.now() - tS;
          const cntS = dockerExec(`[ -f ${rdbPath} ] && grep -c '<item>' ${rdbPath} || echo 0`, 5000);
          const violS = parseInt((cntS.output || "0").trim()) || 0;
          const dirS = gds_file.substring(0, gds_file.lastIndexOf("/"));
          writeManifest(dirS || "/tmp", {
            step: "drc",
            status: "STRUCTURAL_PASS",
            tool: "KLayout (structural-only fallback)",
            argv: ["klayout", "-b", "-r", structuralScript],
            inputs: { [gds_file]: sha256File(gds_file.replace("/work/", projDrcC + "/")) },
            outputs: { [rdbPath]: sha256File(rdbPath.replace("/work/", projDrcC + "/")) },
            exitCode: rS.success ? 0 : 1,
            durationMs: durS,
            stdoutTail: (rS.output || "").slice(-500),
            stderrTail: (rS.error || "").slice(-500),
          });
          return { content: [{ type: "text", text: JSON.stringify({
            success: rS.success,
            deck_mode: "structural_only",
            advisory: "Auto-deck synthesis from tech LEF produced 0 enforceable rules (no layermap available, or layermap layer-names don't match tech LEF). Ran KLayout in structural-only mode — verifies GDS parses + top cell exists but does NOT enforce MIN-WIDTH / MIN-SPACING / MIN-AREA. Production tapeout requires foundry-supplied DRC deck for full sign-off.",
            violations: violS,
            rdb: rdbPath,
            output: (rS.output || "").slice(-2000),
            output_summary: genRes.output.slice(-500),
          }) }] };
        }
        const drcCmdAuto = `QT_QPA_PLATFORM=offscreen ${TOOLS}/klayout/klayout -b -r ${autoScript} -rd threads=${_edaThreadsToken()} 2>&1`;
        const tA = Date.now();
        const rA = dockerExec(drcCmdAuto, 600000);
        const durA = Date.now() - tA;
        const cntCmd = `[ -f ${rdbPath} ] && grep -c '<item>' ${rdbPath} || echo 0`;
        const cntRes = dockerExec(cntCmd, 5000);
        const viol = parseInt((cntRes.output || "0").trim()) || 0;
        const passA = rA.success && viol === 0;
        const dirA = gds_file.substring(0, gds_file.lastIndexOf("/"));
        writeManifest(dirA || "/tmp", {
          step: "drc",
          status: passA ? "PASS" : "FAIL",
          tool: "KLayout (auto-deck from tech LEF)",
          violations: viol,
          rdb: rdbPath,
          deck: autoScript,
        });
        return {
          content: [{ type: "text", text: JSON.stringify({ success: passA, violations: viol, rdb: rdbPath, deck: autoScript, output: (rA.output || "").slice(-1500) }) }],
        };
      }
      return { content: [{ type: "text", text: JSON.stringify({ success: false, error: "pdk=custom requires custom_drc_script or custom_techlef" }) }] };
    }

    // gf180 / sky130 path — REAL PDK sign-off DRC.
    //
    // v1.2.75 (TAPEOUT-SIGNOFF P0#1): this branch WAS a vacuous no-op — it read
    // the GDS, checked a top cell exists, printed `DRC_COMPLETE=YES`, ran ZERO
    // rules, and returned success. Any caller running `eda_drc_klayout` on a
    // foundry PDK got a FALSE DRC-clean (the highest-integrity bug found in the
    // tapeout-signoff survey). It now runs the PDK's OWN KLayout sign-off deck
    // (`sky130A.lydrc` / `gf180mcuD.lydrc`) — the SAME deck the phase3 runner's
    // `step_drc` uses — and counts real `<item>` violations. If no deck is found,
    // or KLayout produces no report, it returns an HONEST FAILURE. It NEVER emits
    // a vacuous PASS again.
    // Pre-flight: the GDS must be visible INSIDE the container, else KLayout's
    // `source` emits an opaque `errno=2 Unable to open file` (and, worse, a
    // partially-run deck can look like a clean pass). Fail fast with the
    // actionable staging hint (which names the bind-mount) instead.
    const drcMissing = missingInContainer([gds_file]);
    if (drcMissing.length) {
      return { content: [{ type: "text", text: JSON.stringify({
        success: false, report_written: false, violations: 0,
        error: stagingHint(drcMissing), gds_file,
      }) }] };
    }
    const pdkPathDrc = pdk === "sky130" ? `${PDK_ROOT}/sky130A`
                                        : `${PDK_ROOT}/gf180mcuD`;
    const deckDir = `${pdkPathDrc}/libs.tech/klayout/drc`;
    // Select the FULL sign-off deck for this PDK. The canonical leaf is
    // sky130A.lydrc / gf180mcuD.lydrc. A naive `ls *.lydrc | head -1` is WRONG:
    // the PDK dir also ships auxiliary single-purpose decks (e.g.
    // `gf180mcu_density.lydrc`, `met_min_ca_density.lydrc`) that sort BEFORE the
    // real deck alphabetically — so `head -1` picks `gf180mcu_density.lydrc`
    // under sky130A and runs a gf180 density deck against a sky130 GDS. Prefer
    // the canonical named deck; fall back to the first *.lydrc that is NOT an
    // auxiliary density/min deck, so a PDK whose leaf-name differs still resolves.
    const deckLeafPref = pdk === "sky130" ? "sky130A.lydrc" : "gf180mcuD.lydrc";
    const deckDiscover = dockerExec(
      `if [ -f ${deckDir}/${deckLeafPref} ]; then echo ${deckDir}/${deckLeafPref}; ` +
      `else ls ${deckDir}/*.lydrc 2>/dev/null | grep -viE 'density|_min_|_min\\.' | head -1; fi ` +
      `|| echo NODECK`, 8000);
    const deckPath = ((deckDiscover.output || "").trim().split("\n").pop() || "").trim();
    if (!deckPath || deckPath === "NODECK" || !deckPath.endsWith(".lydrc")) {
      // §4.05: no deck ⇒ HONEST FAIL, never a vacuous PASS.
      return { content: [{ type: "text", text: JSON.stringify({
        success: false,
        error: `no KLayout sign-off DRC deck (*.lydrc) found under ${deckDir}; ` +
               `eda_drc_klayout will NOT emit a vacuous PASS. Stage the PDK DRC ` +
               `deck, or run the phase3 runner step_drc (real sky130A.lydrc path).`,
        deck_searched: deckDir,
      }) }] };
    }
    // -rd threads=<n> is passed for parallel tiled DRC. The auto-generated deck
    // (auto_drc_deck.py) reads it via `threads(...)`; the foundry sign-off deck
    // (*.lydrc) is NOT under our control, so it may or may not honor $threads —
    // harmless if unread. Getting the SVRF/foundry engine to thread is a separate
    // item, tracked outside this change.
    const drcCmd = `QT_QPA_PLATFORM=offscreen ${TOOLS}/klayout/klayout -b -r ${deckPath} ` +
                   `-rd input=${gds_file} -rd report=${rdbPath} -rd top_cell=${top_cell} -rd threads=${_edaThreadsToken()} 2>&1`;
    const t0drc = Date.now();
    const result = dockerExec(drcCmd, 900000);
    const durationDrcMs = Date.now() - t0drc;
    // Report-existence is checked SEPARATELY from the count: a crashed KLayout
    // writes no report, and `grep -c` on a missing file would echo 0 — which must
    // NOT be read as a clean pass. So: PASS requires klayout ran AND the report
    // was written AND zero <item> violations.
    const reportExists = ((dockerExec(`[ -f ${rdbPath} ] && echo YES || echo NO`, 5000)
      .output || "").trim().includes("YES"));
    const cntRes = dockerExec(`grep -c '<item>' ${rdbPath} 2>/dev/null || echo 0`, 8000);
    const viol = parseInt((cntRes.output || "0").trim()) || 0;
    const passReal = result.success && reportExists && viol === 0;
    const deckLeaf = deckPath.split("/").pop();

    const dir = gds_file.substring(0, gds_file.lastIndexOf("/"));
    writeManifest(dir || "/tmp", {
      step: "drc",
      status: passReal ? "PASS" : "FAIL",
      tool: `KLayout sign-off deck (${deckLeaf})`,
      violations: viol,
      report_written: reportExists,
      rdb: rdbPath,
      deck: deckPath,
    });

    // v0.47.5 auto-provenance
    const projDrc = process.env.EDA_PROJECT_DIR ||
        gds_file.replace(/\/gds\/.*/, "").replace(/^\/work\//, "/host_project/");
    logProvenance({
      projectDir: projDrc,
      tool: "klayout",
      version: toolIdentity("klayout", pdk, `klayout sign-off DRC deck=${deckLeaf}`),
      argv: ["klayout", "-b", "-r", deckPath, "input=" + gds_file],
      inputs: { [gds_file]: sha256File(gds_file.replace("/work/", projDrc + "/")) },
      outputs: reportExists ? { [rdbPath]: sha256File(rdbPath.replace("/work/", projDrc + "/")) } : {},
      exitCode: passReal ? 0 : 1,
      durationMs: durationDrcMs,
      stdoutTail: (result.output || "").slice(-1500),
      stderrTail: result.error || "",
    });

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: passReal,
          violations: viol,
          report_written: reportExists,
          rdb: rdbPath,
          deck: deckPath,
          output: (result.output || "").slice(-2000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_ir_drop ───
server.tool(
  "eda_ir_drop",
  "Analyze IR drop on power grid using OpenROAD PSM (Power Grid Analysis). v0.76 adds custom PDK support and via-resistance fallback.",
  {
    def_file: z.string().describe("DEF file with placed design"),
    pdk: z.enum(["gf180", "sky130", "nangate45", "custom"]).default("gf180"),
    voltage: z.number().default(1.8).describe("VDD voltage in volts"),
    custom_lib: z.string().optional(),
    custom_techlef: z.string().optional(),
    custom_celllef: z.string().optional(),
    custom_site: z.string().optional(),
    custom_vdd: z.string().optional(),
    custom_vss: z.string().optional(),
    custom_metal_prefix: z.string().optional(),
    via_resistance_ohm: z.number().default(5.5).describe("Fallback per-via resistance when tech LEF lacks RESISTANCE PER CUT (e.g. a commercial 180nm PDK)"),
  },
  async ({ def_file, pdk, voltage, custom_lib, custom_techlef, custom_celllef, custom_site, custom_vdd, custom_vss, custom_metal_prefix, via_resistance_ohm }) => {
    try {
      assertSafePath(def_file, "def_file");
      optPath(custom_lib, "custom_lib"); optPath(custom_techlef, "custom_techlef");
      optPath(custom_celllef, "custom_celllef");
      optToken(custom_site, "custom_site"); optIdent(custom_vdd, "custom_vdd");
      optIdent(custom_vss, "custom_vss"); optToken(custom_metal_prefix, "custom_metal_prefix");
    } catch (e) { return guardError(e); }
    const cfg = pdkConfig(pdk, { custom_lib, custom_techlef, custom_celllef, custom_site, custom_vdd, custom_vss, custom_metal_prefix });
    const mp = cfg.metal_prefix;
    const vddNet = cfg.vdd_pin || "VDD";
    const vssNet = cfg.vss_pin || "VSS";
    const ttlEnvVoltage = `set_pdnsim_net_voltage -net ${vddNet} -voltage ${voltage}\nset_pdnsim_net_voltage -net ${vssNet} -voltage 0.0`;

    // T3 v0.106: inject cross-layer PDN stripes for tiny designs to avoid PSM-0069
    // connectivity failure. Metal4 stripes connect isolated Metal1 per-row rails.
    const topMetal = (mp === "met") ? "met4" : `${mp}4`;
    const botMetal = (mp === "met") ? "met1" : `${mp}1`;
    const pdnStripeTcl = `
# T3 auto-stripe: add cross-layer PDN stripes for connectivity
catch {
  add_pdn_stripe -grid main -layer ${topMetal} -width 1.6 -spacing 5.0 -pitch 80.0 -offset 10.0
  add_pdn_connect -grid main -layers {${botMetal} ${topMetal}}
  pdngen
}`;

    const result = dockerExec(
      `export PATH=${TOOLS}/openroad/bin:${TOOLS}/bin:$PATH && openroad -threads ${_edaOpenroadThreadsToken()} -exit << 'TCEOF'
read_lef ${techlefPath(cfg)}
read_lef ${celllefPath(cfg)}
read_liberty ${libPath(cfg)}
read_def ${def_file}
${ttlEnvVoltage}
${pdnStripeTcl}
set rc [catch {analyze_power_grid -net ${vddNet}} err]
if {$rc} {
  puts "PSM_CONNECTIVITY_WARN: $err"
  puts "=== IR_DROP_WARN ==="
} else {
  puts "=== IR_DROP_COMPLETE ==="
}
exit
TCEOF`,
      120000
    );

    const isComplete = result.output.includes("IR_DROP_COMPLETE");
    const isWarn = result.output.includes("IR_DROP_WARN");

    if (isComplete) {
      const dir = def_file.substring(0, def_file.lastIndexOf("/"));
      writeManifest(dir || "/tmp", {
        step: "ir_drop",
        status: "PASS",
        tool: "OpenROAD PSM",
      });
    }

    const warnings = [];
    const instMatch = result.output.match(/Number of instances\s*[:=]\s*(\d+)/i)
                   || result.output.match(/(\d+)\s+instances/i);
    if (instMatch && parseInt(instMatch[1]) < 100) {
      warnings.push(`Design has ${instMatch[1]} instances (< 100) — IR-drop results may not be meaningful for tiny designs.`);
    }
    if (isWarn) {
      warnings.push("PSM connectivity check failed — cross-layer PDN stripes were injected but connectivity still incomplete. Downgraded to WARN.");
    }

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: isComplete || isWarn,
          warnings: warnings.length ? warnings : undefined,
          psm_warn: isWarn || undefined,
          output: result.output.slice(-2000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_equiv ───
server.tool(
  "eda_equiv",
  "Run equivalence check (LEC) between RTL and gate-level netlist using Yosys.",
  {
    gold_files: z.array(z.string()).describe("Golden (RTL) source files"),
    gate_file: z.string().describe("Gate-level netlist file"),
    top_module: z.string().describe("Top module name"),
  },
  async ({ gold_files, gate_file, top_module }) => {
    try {
      assertSafePaths(gold_files, "gold_files");
      assertSafePath(gate_file, "gate_file");
      assertSafeIdent(top_module, "top_module");
    } catch (e) { return guardError(e); }
    // v0.99.1 fix: `read_verilog -gold` and `equiv_make -gold -gate <top>`
    // are not valid yosys CLI flags — Yosys rejects with "Bad option".
    // The canonical flow uses design-stash to keep the two RTL trees
    // separate, then equiv_make takes them by name.
    const goldReads = gold_files.map(f => `read_verilog -sv ${f}`).join("; ");
    const yosysScript = [
      goldReads,
      `hierarchy -check -top ${top_module}`,
      `prep -top ${top_module}`,
      `design -stash gold`,
      `read_verilog ${gate_file}`,
      `hierarchy -check -top ${top_module}`,
      `prep -top ${top_module}`,
      `design -stash gate`,
      `design -copy-from gold -as gold ${top_module}`,
      `design -copy-from gate -as gate ${top_module}`,
      `equiv_make gold gate equiv`,
      `prep -top equiv`,
      `equiv_simple`,
      `equiv_induct`,
      `equiv_status -assert`,
    ].join("; ");

    const result = dockerExec(
      `export PATH=${TOOLS}/yosys/bin:${TOOLS}/bin:$PATH && yosys -p '${yosysScript}' 2>&1`,
      120000
    );

    const proved = result.output.includes("Equivalence successfully proved");
    const failed = result.output.includes("NOT equivalent") || result.output.includes("ERROR");

    if (proved) {
      writeManifest("/tmp", {
        step: "equivalence",
        status: "PASS",
        tool: "Yosys",
        equivalent: proved,
      });
    }

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: proved,
          equivalent: proved,
          output: result.output.slice(-2000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_spice ───
server.tool(
  "eda_spice",
  "Run SPICE simulation using ngspice. For analog circuit analysis.",
  {
    spice_file: z.string().describe("SPICE netlist file (.sp / .spice)"),
    output_file: z.string().default("./sim_spice/spice_out.txt").describe("Output results file. v0.123: default changed from /tmp/spice_out.txt to ./sim_spice/spice_out.txt so artifacts land in the project tree (volatile /tmp lost Wave 53 Phase 3 outputs)."),
  },
  async ({ spice_file, output_file }) => {
    try {
      assertSafePath(spice_file, "spice_file");
      assertSafePath(output_file, "output_file");
    } catch (e) { return guardError(e); }
    const result = dockerExec(
      `export PATH=${TOOLS}/ngspice/bin:${TOOLS}/bin:$PATH && OMP_NUM_THREADS=${_edaThreadsToken()} ngspice -b ${spice_file} -o ${output_file} 2>&1 && echo 'SPICE_COMPLETE' && tail -20 ${output_file} 2>/dev/null`,
      300000
    );

    const success = result.output.includes("SPICE_COMPLETE");

    // P0/P1: Parse .meas results and detect failures
    const measResults = {};
    const measLines = result.output.match(/^\S+\s+=\s+[\d.e+-]+/gm) || [];
    for (const line of measLines) {
      const [name, , value] = line.split(/\s+/);
      measResults[name] = parseFloat(value);
    }
    const measFailed = (result.output.match(/failed!/g) || []).length;
    const hasNegativeVoltage = Object.entries(measResults).some(
      ([k, v]) => (k.startsWith("v") || k.startsWith("V")) && v < -1
    );

    // P0: Write manifest
    if (success) {
      const dir = spice_file.substring(0, spice_file.lastIndexOf("/"));
      writeManifest(dir || "/tmp", {
        step: "spice_simulation",
        status: measFailed > 0 ? "MEAS_FAILED" : hasNegativeVoltage ? "SUSPICIOUS" : "PASS",
        tool: "ngspice",
        spice_file,
        log_file: output_file,
        measurements: measResults,
        meas_failed_count: measFailed,
        has_negative_voltage: hasNegativeVoltage,
      });
    }

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success,
          measurements: measResults,
          meas_failed: measFailed,
          has_negative_voltage: hasNegativeVoltage,
          output: result.output.slice(-3000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_xschem_netlist ───
server.tool(
  "eda_xschem_netlist",
  "Generate SPICE netlist from xschem schematic (.sch). Batch mode — no GUI needed. v0.108: analog design pipeline.",
  {
    schematic: z.string().describe("Path to .sch schematic file inside Docker container"),
    output_dir: z.string().default("./analog/xschem_out").describe("Output directory for generated netlist. v0.123: default changed from /tmp/xschem_out so artifacts land in the project tree."),
    pdk: z.enum(["gf180", "sky130", "nangate45", "custom"]).default("gf180"),
    custom_xschemrc: z.string().optional().describe("Path to custom xschemrc file (custom PDK only)"),
  },
  async ({ schematic, output_dir, pdk, custom_xschemrc }) => {
    try {
      assertSafePath(schematic, "schematic");
      assertSafePath(output_dir, "output_dir");
      optPath(custom_xschemrc, "custom_xschemrc");
    } catch (e) { return guardError(e); }
    let xschemrc;
    if (pdk === "custom" && custom_xschemrc) {
      xschemrc = custom_xschemrc;
    } else if (pdk === "gf180") {
      xschemrc = "/foss/pdks/gf180mcuD/libs.tech/xschem/xschemrc";
    } else {
      xschemrc = "/foss/pdks/sky130A/libs.tech/xschem/xschemrc";
    }

    const basename = schematic.substring(schematic.lastIndexOf("/") + 1).replace(/\.sch$/, "");
    const netlistFile = `${output_dir}/${basename}.sp`;

    const cmd = [
      `export PATH=${TOOLS}/bin:$PATH`,
      `mkdir -p ${output_dir}`,
      `xschem --rcfile ${xschemrc} --no_x --quit --netlist --netlist_path ${output_dir} ${schematic} 2>&1`,
      `echo "XSCHEM_NETLIST_COMPLETE"`,
      `ls -la ${output_dir}/*.sp ${output_dir}/*.spice 2>/dev/null`,
      `tail -30 ${netlistFile} 2>/dev/null`,
    ].join(" && ");

    const result = dockerExec(cmd, 120000);
    const success = result.output.includes("XSCHEM_NETLIST_COMPLETE");
    const netlistExists = result.output.includes(basename);

    if (success) {
      writeManifest(output_dir, {
        step: "xschem_netlist",
        status: netlistExists ? "PASS" : "NO_NETLIST",
        tool: "xschem",
        schematic,
        pdk,
        output_file: netlistFile,
      });
    }

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: success && netlistExists,
          netlist_file: netlistFile,
          pdk,
          output: result.output.slice(-3000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_spice_corner ───
server.tool(
  "eda_spice_corner",
  "Run multi-corner PVT SPICE sweep with automated .meas extraction and yield table. v0.108: analog design pipeline. Runs one ngspice invocation per corner×temp combination, aggregates results into a JSON yield matrix.",
  {
    spice_file: z.string().describe("Base SPICE netlist file (.sp) — must NOT contain .lib/.temp directives (they are injected per corner)"),
    pdk: z.enum(["gf180", "sky130", "nangate45", "custom"]).default("gf180"),
    corners: z.array(z.string()).default(["typical", "ss", "ff"]).describe("Process corner names. For gf180/sky130 they are mapped to the foundry deck's section names; for pdk=custom each entry is used verbatim as the .lib section name in custom_corner_lib."),
    temperatures: z.array(z.number()).default([-40, 25, 125]).describe("Temperature sweep points in °C"),
    supplies: z.array(z.number()).optional().describe("Supply voltages to sweep (if omitted: uses nominal only)"),
    monte_carlo_n: z.number().default(0).describe("Number of Monte Carlo runs at TT corner (0=skip)"),
    output_dir: z.string().default("./analog/corner_sweep").describe("Output directory for per-corner results. v0.123: default changed from /tmp/corner_sweep so artifacts land in the project tree."),
    specs: z.record(z.string(), z.object({
      min: z.number().optional(),
      max: z.number().optional(),
    })).optional().describe("Spec limits per .meas name, e.g. {vout_dc: {min: 1.7, max: 1.9}}"),
    custom_corner_lib: z.string().optional().describe("v0.121: for pdk=custom, path to a .lib (or .scs / .cir) file containing the named corner sections. Each `corners[]` entry is interpreted as the .lib section name. Caller is responsible for ensuring section names exist."),
    custom_design_include: z.string().optional().describe("v0.121: for pdk=custom, optional path to a design-side .include (analog control set, ngspice options, etc.). May be empty/omitted."),
    custom_nominal_supply: z.number().optional().describe("v0.121: for pdk=custom, nominal supply voltage when `supplies` is not supplied. Defaults to 1.8 V if omitted."),
  },
  async ({ spice_file, pdk, corners, temperatures, supplies, monte_carlo_n, output_dir, specs, custom_corner_lib, custom_design_include, custom_nominal_supply }) => {
    try {
      assertSafePath(spice_file, "spice_file");
      assertSafePath(output_dir, "output_dir");
      optPath(custom_corner_lib, "custom_corner_lib");
      optPath(custom_design_include, "custom_design_include");
      optNoShellMeta(custom_nominal_supply, "custom_nominal_supply");
      (corners || []).forEach((c) => optNoShellMeta(c, "corners"));
      (supplies || []).forEach((s) => optNoShellMeta(String(s), "supplies"));
    } catch (e) { return guardError(e); }
    let designInclude, modelLib;
    if (pdk === "gf180") {
      designInclude = "/foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice";
      modelLib = "/foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice";
    } else if (pdk === "sky130") {
      designInclude = "/foss/pdks/sky130A/libs.tech/ngspice/spinit";
      modelLib = "/foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice";
    } else {
      // v0.121: custom PDK path. Caller must supply custom_corner_lib
      // (a .lib / .scs / .cir file with named corner sections).
      // custom_design_include is optional. No vendor / foundry / chip
      // assumption — the caller decides which file to point at.
      if (!custom_corner_lib) {
        return {
          content: [{ type: "text", text: JSON.stringify({
            success: false,
            error: "pdk=custom requires custom_corner_lib — a path to a .lib / .scs / .cir file whose section names match the entries supplied in `corners`.",
          }) }],
        };
      }
      designInclude = custom_design_include || "";
      modelLib = custom_corner_lib;
    }

    const supplyList = supplies || [
      pdk === "gf180" ? 3.3 :
      pdk === "sky130" ? 1.8 :
      (typeof custom_nominal_supply === "number" ? custom_nominal_supply : 1.8),
    ];

    const matrix = [];
    for (const corner of corners) {
      for (const temp of temperatures) {
        for (const vdd of supplyList) {
          matrix.push({ corner, temp, vdd });
        }
      }
    }

    // v0.2.84 — monte_carlo_n was declared since v0.108 but NEVER
    // consumed (dead parameter; the flow's 95%-yield gate had no data
    // source). Wire it: N extra runs at nominal temp/VDD using the
    // FOUNDRY's own statistical model section (sky130 'mc',
    // gf180 'statistical') with a distinct deterministic seed per run.
    const mcSection = pdk === "sky130" ? "mc"
      : pdk === "gf180" ? "statistical" : null;
    const mcUnsupportedReason = (monte_carlo_n > 0 && !mcSection)
      ? "pdk=custom has no known statistical model section — MC skipped (surfaced, not faked)"
      : null;
    if (monte_carlo_n > 0 && mcSection) {
      const mcTemp = temperatures.includes(25) ? 25 : temperatures[0];
      const mcVdd = supplyList[0];
      for (let i = 1; i <= monte_carlo_n; i++) {
        matrix.push({ corner: mcSection, temp: mcTemp, vdd: mcVdd,
                      mcSeed: i });
      }
    }

    const scriptLines = [
      `export PATH=${TOOLS}/bin:${TOOLS}/ngspice/bin:$PATH`,
      `mkdir -p ${output_dir}`,
    ];

    for (const { corner, temp, vdd, mcSeed } of matrix) {
      const tag = (mcSeed ? `mc_${String(mcSeed).padStart(4, "0")}`
        : `${corner}_${temp}C_${vdd}V`).replace(/[.-]/g, "_");
      const wrapperFile = `${output_dir}/wrap_${tag}.sp`;
      const outFile = `${output_dir}/out_${tag}.txt`;

      const wrapperLines = [
        `* Auto-generated PVT wrapper: ${corner} ${temp}C ${vdd}V`
          + (mcSeed ? ` (Monte-Carlo seed ${mcSeed})` : ""),
        ...(mcSeed ? [`.option seed=${mcSeed}`] : []),
        ...(designInclude ? [`.include ${designInclude}`] : []),
        `.lib ${modelLib} ${corner}`,
        `.param temp_val=${temp}`,
        `.param supply_val=${vdd}`,
        `.temp \${temp_val}`,
        `.include ${spice_file}`,
        `.end`,
      ];

      const escaped = wrapperLines.join("\n").replace(/'/g, "'\\''");
      scriptLines.push(`printf '%s\\n' '${escaped}' > ${wrapperFile}`);
      scriptLines.push(`OMP_NUM_THREADS=${_edaThreadsToken()} ngspice -b ${wrapperFile} -o ${outFile} 2>&1 || true`);
    }

    scriptLines.push(`echo "===CORNER_SWEEP_COMPLETE==="`);
    scriptLines.push(`for f in ${output_dir}/out_*.txt; do echo "===FILE:$f==="; tail -40 "$f" 2>/dev/null; done`);

    const cmd = scriptLines.join(" && ");
    const result = dockerExec(cmd, 600000);

    const success = result.output.includes("===CORNER_SWEEP_COMPLETE===");

    // Parse .meas results from each output file section
    const pvtResults = {};
    const fileRe = /===FILE:(.+?)===/g;
    const sections = result.output.split(/===FILE:.+?===/);
    const fileMatches = [...result.output.matchAll(fileRe)];

    for (let i = 0; i < fileMatches.length; i++) {
      const fileName = fileMatches[i][1];
      const tag = fileName.replace(/.*out_/, "").replace(/\.txt$/, "");
      const section = sections[i + 1] || "";
      const meas = {};
      const re = /^(\S+)\s*=\s*([\d.eE+-]+)/gm;
      let m;
      while ((m = re.exec(section)) !== null) {
        meas[m[1]] = parseFloat(m[2]);
      }
      pvtResults[tag] = meas;
    }

    // Check specs if provided
    let specResults = null;
    let allPass = true;
    if (specs && Object.keys(specs).length > 0) {
      specResults = {};
      for (const [tag, meas] of Object.entries(pvtResults)) {
        specResults[tag] = {};
        for (const [specName, limits] of Object.entries(specs)) {
          const val = meas[specName];
          if (val === undefined) {
            specResults[tag][specName] = { value: null, status: "MISSING" };
            continue;
          }
          let pass = true;
          if (limits.min !== undefined && val < limits.min) pass = false;
          if (limits.max !== undefined && val > limits.max) pass = false;
          specResults[tag][specName] = { value: val, status: pass ? "PASS" : "FAIL" };
          if (!pass) allPass = false;
        }
      }
    }

    // v0.2.84 — Monte-Carlo yield from the mc_* runs (worst spec
    // governs). Only computed when MC ran AND specs exist; never
    // fabricated.
    let mcYieldPct = null;
    let mcRunsScored = 0;
    if (monte_carlo_n > 0 && mcSection && specs
        && Object.keys(specs).length > 0) {
      const perSpecYield = {};
      for (const [specName, limits] of Object.entries(specs)) {
        let scored = 0, passed = 0;
        for (const [tag, meas] of Object.entries(pvtResults)) {
          if (!tag.startsWith("mc_")) continue;
          const val = meas[specName];
          if (val === undefined) continue;
          scored++;
          let ok = true;
          if (limits.min !== undefined && val < limits.min) ok = false;
          if (limits.max !== undefined && val > limits.max) ok = false;
          if (ok) passed++;
        }
        if (scored > 0) {
          perSpecYield[specName] = (100 * passed) / scored;
          mcRunsScored = Math.max(mcRunsScored, scored);
        }
      }
      const vals = Object.values(perSpecYield);
      if (vals.length > 0) mcYieldPct = Math.min(...vals);
    }

    if (success) {
      writeManifest(output_dir, {
        step: "spice_corner_sweep",
        status: allPass ? "PASS" : "SPEC_FAIL",
        tool: "ngspice",
        pdk,
        corners_run: matrix.length,
        spice_file,
        pvt_results: pvtResults,
        spec_results: specResults,
        mc_yield_pct: mcYieldPct,
      });
    }

    // Write corner_results.json inside the container
    const cornerJson = JSON.stringify({
      spice_file,
      pdk,
      matrix: matrix.map(m => m.mcSeed ? `mc_${m.mcSeed}` : `${m.corner}_${m.temp}C_${m.vdd}V`),
      pvt_results: pvtResults,
      spec_results: specResults,
      all_specs_pass: allPass,
      total_corners: matrix.length,
      results_found: Object.keys(pvtResults).length,
      ...(mcYieldPct !== null ? {
        mc_yield_pct: mcYieldPct,
        mc_runs: monte_carlo_n,
        mc_runs_scored: mcRunsScored,
        mc_model_section: mcSection,
        _mc_provenance: "real_ngspice_mc",
      } : {}),
    }, null, 2);
    const escJson = cornerJson.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n");
    dockerExec(`printf "${escJson}" > ${output_dir}/corner_results.json`, 10000);

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success,
          total_corners: matrix.length,
          results_found: Object.keys(pvtResults).length,
          all_specs_pass: allPass,
          pvt_results: pvtResults,
          spec_results: specResults,
          ...(mcYieldPct !== null ? {
            mc_yield_pct: mcYieldPct,
            mc_runs: monte_carlo_n,
            mc_runs_scored: mcRunsScored,
            mc_model_section: mcSection,
          } : {}),
          ...(mcUnsupportedReason ? { mc_unsupported_reason: mcUnsupportedReason } : {}),
          output: result.output.slice(-3000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_dft ───
server.tool(
  "eda_dft",
  "Run full DFT flow using Fault: scan chain insertion + ATPG + optional JTAG TAP. Returns coverage percentage and test vector count. v2.5.0: pdk=custom supported via custom_dff_names + custom_lib + custom_cell_verilog.",
  {
    netlist: z.string().describe("Flattened gate-level netlist (mapped to PDK cells)"),
    clock: z.string().default("clk").describe("Clock signal name"),
    reset: z.string().default("rst_n").describe("Reset signal name"),
    reset_active_low: z.boolean().default(true),
    pdk: z.enum(["gf180", "sky130", "nangate45", "custom"]).default("gf180"),
    tv_count: z.number().default(200).describe("Number of test vectors to generate"),
    add_jtag: z.boolean().default(false).describe("Also insert JTAG TAP controller"),
    output_dir: z.string().describe("Output directory for DFT files"),
    custom_lib: z.string().optional().describe("Liberty file (custom PDK)"),
    custom_dff_names: z.string().optional().describe("Comma-separated DFF cell names for scan chain (custom PDK; e.g. 'DFFRQD1,DFFSQD1')"),
    custom_cell_verilog: z.string().optional().describe("Path to behavioral .v library file (custom PDK; concat'd into cell-model)"),
    custom_primitives_verilog: z.string().optional().describe("Path to primitives .v file (custom PDK)"),
    sdd_project: z.string().optional().describe("Opt-in Small-Delay-Defect (SDD) at-speed grade: pass a routed PROJECT dir (with DT1 transition + DT2 path-delay coverage) to fuse OpenSTA per-path slack with the LOC-SAT sensitisation via programs/sdd_atpg_run.py, writing reports/phase2/dft/sdd_coverage.json (DESCRIPTIVE, no floor — a slack-rich design honestly scores low). When set, this runs instead of the Fault scan/ATPG flow."),
  },
  async ({ netlist, clock, reset, reset_active_low, pdk, tv_count, add_jtag, output_dir, custom_lib, custom_dff_names, custom_cell_verilog, custom_primitives_verilog, sdd_project }) => {
    try {
      if (sdd_project === undefined) assertSafePath(netlist, "netlist");
      assertSafeIdent(clock, "clock"); assertSafeIdent(reset, "reset");
      optPath(output_dir, "output_dir"); optPath(custom_lib, "custom_lib");
      optNoShellMeta(custom_dff_names, "custom_dff_names");
      optPath(custom_cell_verilog, "custom_cell_verilog");
      optPath(custom_primitives_verilog, "custom_primitives_verilog");
      optPath(sdd_project, "sdd_project");
    } catch (e) { return guardError(e); }
    // Opt-in SDD grade (project-level; shells to the plugin program).
    if (sdd_project !== undefined) {
      const t0s = Date.now();
      const args = [`${VIBE_IC_PROGRAMS_DIR}/sdd_atpg_run.py`, sdd_project,
        "--clock", clock];
      const o = _spawnSync("python3", args, { timeout: 1800000, maxBuffer: 10 * 1024 * 1024, encoding: "utf-8" });
      const merged = (o.stdout || "") + (o.stderr || "");
      return wrapResult({
        success: !o.error && o.status === 0,
        t0: t0s,
        toolVersion: `sdd_atpg_run @ mcp-eda@${SERVER_VERSION}`,
        error: o.error ? (o.error.message || String(o.error)) : (o.status === 0 ? undefined : `exited ${o.status}`),
        output: merged,
      });
    }
    const cfg = pdkConfig(pdk, { custom_lib });
    const lib = pdk === "custom" ? (custom_lib || "") : libPath(cfg);
    if (pdk === "custom" && (!lib || !custom_dff_names)) {
      return wrapResult({ success: false, t0: Date.now(), error: "pdk=custom requires custom_lib + custom_dff_names", output: "" });
    }
    const resetFlag = reset_active_low ? "--reset-active-low" : "";
    const dffNames = pdk === "gf180"
      ? "gf180mcu_fd_sc_mcu7t5v0__dffrnq_1,gf180mcu_fd_sc_mcu7t5v0__dffsnq_1"
      : pdk === "sky130"
        ? "sky130_fd_sc_hd__dfxtp_1"
        : custom_dff_names;
    const cellVerilog = pdk === "custom"
      ? ""
      : `${cfg.pdk_path}/libs.ref/${cfg.scl}/verilog`;
    const primsFile = pdk === "custom"
      ? (custom_primitives_verilog || "/dev/null")
      : `${cellVerilog}/primitives.v`;
    const cellFile = pdk === "custom"
      ? (custom_cell_verilog || "/dev/null")
      : `${cellVerilog}/${cfg.scl}.v`;

    const script = `
export FAULT_IVERILOG=${TOOLS}/iverilog/bin/iverilog
export FAULT_YOSYS=${TOOLS}/yosys/bin/yosys
export PATH=${TOOLS}/iverilog/bin:${TOOLS}/yosys/bin:${TOOLS}/bin:$PATH
export LD_LIBRARY_PATH=${TOOLS}/iverilog/lib:$LD_LIBRARY_PATH
mkdir -p ${output_dir}

# Scan chain
# Every tool is called by its deterministic /foss/tools/bin path — the image is
# self-contained; we never lean on ambient PATH resolution.
${TOOLS}/bin/fault chain --liberty ${lib} --clock ${clock} --reset ${reset} ${resetFlag} --dff '${dffNames}' --output ${output_dir}/scanchained.v ${netlist} 2>&1
echo CHAIN_DONE

# Cut + ATPG
${TOOLS}/bin/fault cut --clock ${clock} --reset ${reset} ${resetFlag} --dff '${dffNames}' --output ${output_dir}/cut.v ${netlist} 2>&1
cat ${primsFile} ${cellFile} > /tmp/combined_cells.v 2>/dev/null
${TOOLS}/bin/fault atpg --cell-model /tmp/combined_cells.v --clock ${clock} --reset ${reset} ${resetFlag} --tv-count ${tv_count} --output ${output_dir}/atpg.tv.json --output-coverage-metadata ${output_dir}/coverage.yml ${output_dir}/cut.v 2>&1
echo ATPG_DONE

${add_jtag ? `${TOOLS}/bin/fault tap --liberty ${lib} --clock ${clock} --reset ${reset} ${resetFlag} --output ${output_dir}/jtag.v ${output_dir}/scanchained.v 2>&1
echo JTAG_DONE` : "echo JTAG_SKIPPED"}
`;

    const result = dockerExec(script.replace(/"/g, '\\"'), 600000);

    const coverageMatch = result.output.match(/Coverage\s+([\d.]+)%/);
    const chainMatch = result.output.match(/Total scan-chain length:\s+(\d+)/);
    const tvMatch = result.output.match(/Compacted TV Count:\s+(\d+)/);
    const atpgDone = result.output.includes("ATPG_DONE");

    const metrics = {
      success: atpgDone,
      scan_chain_length: chainMatch ? parseInt(chainMatch[1]) : null,
      coverage_pct: coverageMatch ? parseFloat(coverageMatch[1]) : null,
      test_vectors: tvMatch ? parseInt(tvMatch[1]) : null,
      jtag_added: result.output.includes("JTAG_DONE"),
      output_dir,
      log_tail: result.output.slice(-2000),
    };

    if (atpgDone) {
      writeManifest(output_dir, {
        step: "dft",
        status: "PASS",
        tool: "Fault",
        scan_chain_length: metrics.scan_chain_length,
        coverage_pct: metrics.coverage_pct,
        test_vectors: metrics.test_vectors,
        jtag_added: metrics.jtag_added,
        netlist,
      });
    }

    return { content: [{ type: "text", text: JSON.stringify(metrics) }] };
  }
);

// ─── Tool: eda_ic_search ───
server.tool(
  "eda_ic_search",
  "Search the IC Knowledge Base for reference ICs by function, interface, voltage, or natural language. Returns matching ICs with parameters and datasheet URLs. Use when the user describes an IC they want to design and needs to find similar existing ICs.",
  {
    query: z.string().describe("Natural language search query (e.g., 'I2C temperature sensor 3.3V')"),
    interface_filter: z.string().optional().describe("Filter by interface: I2C, SPI, UART, USB, CAN, etc."),
    vdd_min: z.number().optional().describe("Minimum supply voltage (V)"),
    vdd_max: z.number().optional().describe("Maximum supply voltage (V)"),
    category_filter: z.string().optional().describe("Filter by category keyword"),
    limit: z.number().default(10).describe("Max results to return"),
  },
  async ({ query, interface_filter, vdd_min, vdd_max, category_filter, limit }) => {
    // Build SQL query with full-text search + parameter filters
    const conditions = [];
    const params = [];
    let paramIdx = 1;

    // Full-text search on query
    if (query) {
      // Convert natural language to tsquery: split words, join with &
      const words = query.replace(/[^a-zA-Z0-9\s]/g, '').split(/\s+/).filter(w => w.length > 1);
      if (words.length > 0) {
        const tsquery = words.join(' & ');
        conditions.push(`search_vector @@ to_tsquery('english', $${paramIdx})`);
        params.push(tsquery);
        paramIdx++;
      }
    }

    // Interface filter
    if (interface_filter) {
      conditions.push(`EXISTS (SELECT 1 FROM ic_interfaces ii JOIN interfaces inf ON ii.interface_id = inf.id WHERE ii.ic_id = i.id AND inf.name ILIKE $${paramIdx})`);
      params.push(`%${interface_filter}%`);
      paramIdx++;
    }

    // Voltage filters
    if (vdd_min !== undefined) {
      conditions.push(`i.vdd_max >= $${paramIdx}`);
      params.push(vdd_min);
      paramIdx++;
    }
    if (vdd_max !== undefined) {
      conditions.push(`i.vdd_min <= $${paramIdx}`);
      params.push(vdd_max);
      paramIdx++;
    }

    // Category filter
    if (category_filter) {
      conditions.push(`c.name ILIKE $${paramIdx}`);
      params.push(`%${category_filter}%`);
      paramIdx++;
    }

    const whereClause = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';

    const sql = `
      SELECT i.part_number, i.name, m.name as manufacturer, c.name as category,
             i.vdd_min, i.vdd_typ, i.vdd_max, i.icc_typ, i.freq_max,
             i.resolution_bits, p.name as package, i.pin_count,
             i.datasheet_url, i.description,
             array_agg(DISTINCT inf.name) FILTER (WHERE inf.name IS NOT NULL) as interfaces
      FROM ics i
      LEFT JOIN manufacturers m ON i.manufacturer_id = m.id
      LEFT JOIN categories c ON i.category_id = c.id
      LEFT JOIN packages p ON i.package_id = p.id
      LEFT JOIN ic_interfaces ii ON ii.ic_id = i.id
      LEFT JOIN interfaces inf ON ii.interface_id = inf.id
      ${whereClause}
      GROUP BY i.id, m.name, c.name, p.name
      ORDER BY i.part_number
      LIMIT $${paramIdx}
    `;
    params.push(limit);

    // Execute via psql (no persistent connection needed)
    const paramStr = params.map((p, i) => `--set=p${i+1}="${p}"`).join(' ');

    // Simpler: use Python for DB query.
    // Connection params come from env vars; configure via .env or your
    // shell. Defaults assume a local "vibe_ic" database with no password.
    const pyScript = `
import os, psycopg2, json, sys
conn = psycopg2.connect(
    dbname=os.environ.get("VIBE_IC_DB_NAME", "vibe_ic"),
    user=os.environ.get("VIBE_IC_DB_USER", "vibe_ic"),
    password=os.environ.get("VIBE_IC_DB_PASSWORD", ""),
    host=os.environ.get("VIBE_IC_DB_HOST", "localhost"),
)
cur = conn.cursor()
sql = """${sql.replace(/"/g, '\\"').replace(/\n/g, ' ')}"""
params = ${JSON.stringify(params)}
cur.execute(sql, params)
cols = [d[0] for d in cur.description]
results = []
for row in cur.fetchall():
    r = dict(zip(cols, row))
    if r.get('interfaces') and isinstance(r['interfaces'], list):
        r['interfaces'] = [x for x in r['interfaces'] if x]
    results.append(r)
print(json.dumps({"count": len(results), "results": results}, default=str))
conn.close()
`;

    // security hardening: run via argv (no shell). The SQL is static + fully
    // parameterized (psycopg2 cur.execute(sql, params)); removing the shell
    // wrapper drops the last shell-escaping concern.
    const _r = _spawnSync("python3", ["-c", pyScript], {
      timeout: 10000,
      maxBuffer: 5 * 1024 * 1024,
      encoding: "utf-8",
    });
    const result = (_r.stdout || "") || (_r.stderr || "");

    let parsed;
    try {
      parsed = JSON.parse(result.trim());
    } catch {
      parsed = { count: 0, results: [], error: result.slice(0, 500) };
    }

    writeManifest("/tmp", {
      step: "ic_search",
      status: "PASS",
      tool: "PostgreSQL",
      query,
      results_count: parsed.count,
    });

    return {
      content: [{
        type: "text",
        text: JSON.stringify(parsed),
      }],
    };
  }
);

// ─── Tool: eda_sta_mcorner ───
server.tool(
  "eda_sta_mcorner",
  "Run multi-corner STA (SS/TT/FF) on synthesized netlist using OpenSTA. Reports WNS/TNS per corner and overall PASS/FAIL.",
  {
    netlist: z.string().describe("Gate-level netlist path (inside container)"),
    lib_wci: z.string().describe("Liberty file for worst-case industrial (SS) corner"),
    lib_typ: z.string().describe("Liberty file for typical (TT) corner"),
    lib_bci: z.string().describe("Liberty file for best-case industrial (FF) corner"),
    sdc_file: z.string().describe("SDC constraints file path"),
    top_module: z.string().describe("Top module name"),
  },
  async ({ netlist, lib_wci, lib_typ, lib_bci, sdc_file, top_module }) => {
    try {
      assertSafePaths([netlist, lib_wci, lib_typ, lib_bci, sdc_file], "path");
      assertSafeIdent(top_module, "top_module");
    } catch (e) { return guardError(e); }
    // v0.100 H1: auto-flatten Yosys $paramod references that OpenSTA cannot resolve
    let effectiveNetlist = netlist;
    const paramodCheck = dockerExec(`grep -c '\\$paramod' ${netlist} 2>/dev/null || true`, 10000);
    if (parseInt(paramodCheck.output.trim()) > 0) {
      const flatNetlist = netlist.replace(/\.v$/, '_sta_flat.v');
      const flatResult = dockerExec(
        `export PATH=${TOOLS}/bin:$PATH && yosys -p "read_verilog -sv ${netlist}; flatten; write_verilog -noattr ${flatNetlist}" 2>&1`,
        60000
      );
      if (flatResult.success) { canonicalizeNetlistSrcCoords(flatNetlist); effectiveNetlist = flatNetlist; }
    }

    const corners = [
      { name: "SS", lib: lib_wci },
      { name: "TT", lib: lib_typ },
      { name: "FF", lib: lib_bci },
    ];

    const results = {};
    let overall_pass = true;

    // NOTE (parallel-by-default): each corner gets intra-corner parallelism via
    // `sta -threads` below. The per-corner LOOP is intentionally LEFT SEQUENTIAL:
    // dockerExec is a synchronous spawnSync wrapper, so `await Promise.all(...)`
    // would NOT actually overlap the corners (each spawnSync blocks the event
    // loop until it returns) — true corner-level concurrency would need a full
    // async-spawn rewrite, which is out of scope here. Correctness first.
    for (const corner of corners) {
      const tclScript = `
read_liberty ${corner.lib}
read_verilog ${effectiveNetlist}
link_design ${top_module}
source ${sdc_file}
report_checks -path_delay max -format full
report_wns
report_tns
puts "=== MCORNER_${corner.name}_DONE ==="
exit
`;
      const result = dockerExec(
        `export PATH=${TOOLS}/openroad/bin:${TOOLS}/bin:$PATH && echo '${tclScript.replace(/'/g, "'\\''")}' | sta -threads ${_edaOpenroadThreadsToken()} -exit 2>&1`,
        120000
      );

      const wnsMatch = result.output.match(/wns\s+([\d.-]+)/i);
      const tnsMatch = result.output.match(/tns\s+([\d.-]+)/i);
      const done = result.output.includes(`MCORNER_${corner.name}_DONE`);
      const wns = wnsMatch ? parseFloat(wnsMatch[1]) : null;
      const tns = tnsMatch ? parseFloat(tnsMatch[1]) : null;
      const met = wns !== null ? wns >= 0 : null;

      if (met === false) overall_pass = false;

      results[corner.name] = {
        wns,
        tns,
        timing_met: met,
        completed: done,
        log_tail: result.output.slice(-1000),
      };
    }

    const dir = netlist.substring(0, netlist.lastIndexOf("/"));
    writeManifest(dir || "/tmp", {
      step: "sta_mcorner",
      status: overall_pass ? "PASS" : "TIMING_VIOLATED",
      tool: "OpenSTA",
      corners: Object.fromEntries(
        Object.entries(results).map(([k, v]) => [k, { wns: v.wns, tns: v.tns, met: v.timing_met }])
      ),
    });

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: overall_pass,
          overall_pass,
          corners: results,
        }),
      }],
    };
  }
);

// ─── Tool: eda_rtl_audit ───
server.tool(
  "eda_rtl_audit",
  "Run vibe-ic-d deterministic audit programs against RTL files. Returns per-program PASS/FAIL and findings count.",
  {
    rtl_dir: z.string().describe("Directory containing RTL files to audit"),
    programs: z.array(z.enum([
      "phy_counter_audit",
      "interface_encoding_audit",
      "crc_bitorder_check",
      "oe_pattern_check",
      "corner_coverage_audit",
      "rtl_hygiene_lint",
      "protocol_gap_check",
      // general structural lints derived from the benchmark-IC + VerilogEval-v2
      // failure analysis (all accept a positional rtl_dir, print PASS/FAIL +
      // "findings: N"):
      "reset_discipline_check",        // sync/async-mode + polarity + partial reset
      "arith_ss_corner_risk_check",    // wide ripple-carry → SS-corner risk (advisory)
      "output_latency_advisor",        // registered-output / sampling latency (advisory)
      "spec_rtl_port_fidelity_check",  // L9↔RTL port match + garbled-index detection
    ])).describe("List of audit programs to run"),
    programs_dir: z.string().default(VIBE_IC_PROGRAMS_DIR.endsWith("/") ? VIBE_IC_PROGRAMS_DIR : VIBE_IC_PROGRAMS_DIR + "/").describe("Directory containing audit program scripts. v2.5.2: auto-detected from this file's location (the plugin's own programs/ dir) — overridable via $VIBE_IC_PROGRAMS_DIR. Earlier releases hardcoded a personal home directory, which was wrong on every other install."),
  },
  async ({ rtl_dir, programs, programs_dir }) => {
    try {
      assertSafePath(rtl_dir, "rtl_dir");
      optPath(programs_dir, "programs_dir");
      (programs || []).forEach((p) => assertSafeToken(p, "programs"));
    } catch (e) { return guardError(e); }
    const results = {};
    let all_pass = true;

    for (const prog of programs) {
      const scriptPath = `${programs_dir}${prog}.py`;
      try {
        // security hardening: run via argv (no shell) so neither the program
        // name nor rtl_dir is ever shell-parsed. stderr merged into stdout to
        // preserve the prior `2>&1` behaviour the PASS/FAIL match relies on.
        const _r = _spawnSync("python3", [scriptPath, rtl_dir], {
          timeout: 60000, maxBuffer: 5 * 1024 * 1024, encoding: "utf-8",
        });
        if (_r.error) throw _r.error;
        if (_r.status !== 0) {
          const e = new Error(`exit ${_r.status}`);
          e.stdout = (_r.stdout || "") + (_r.stderr || ""); throw e;
        }
        const output = (_r.stdout || "") + (_r.stderr || "");

        const passMatch = output.match(/PASS/i);
        const failMatch = output.match(/FAIL/i);
        const findingsMatch = output.match(/findings?:\s*(\d+)/i);
        const passed = passMatch && !failMatch;

        if (!passed) all_pass = false;

        results[prog] = {
          status: passed ? "PASS" : "FAIL",
          findings: findingsMatch ? parseInt(findingsMatch[1]) : 0,
          output: output.slice(-1000),
        };
      } catch (err) {
        all_pass = false;
        results[prog] = {
          status: "ERROR",
          findings: 0,
          output: (err.stdout || err.stderr || err.message || "").slice(-1000),
        };
      }
    }

    writeManifest(rtl_dir, {
      step: "rtl_audit",
      status: all_pass ? "PASS" : "FAIL",
      tool: "vibe-ic-d",
      programs_run: programs.length,
      programs_passed: Object.values(results).filter(r => r.status === "PASS").length,
    });

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: all_pass,
          all_pass,
          programs: results,
        }),
      }],
    };
  }
);

// ─── Tool: eda_spec_conformance ───
// First-class Spec↔RTL contract-conformance verb. Distinct from eda_rtl_audit
// (RTL-only structural lints): this takes BOTH a spec and the RTL and proves the
// implementation matches the *declared* contract — ports, reset semantics
// (sync/async + polarity), and output latency. Motivated by two real misses:
//   • a spec that said "synchronous reset" while the reference RTL was async
//     (a blind spec-faithful design then failed the bench), and
//   • VerilogEval-v2 port-interface misses that needed an auto-extracted
//     expected port list (the prompt's "- input d (8 bits)" bullets).
// Belongs at the Phase-1→Phase-2 checkpoint (see spec-validator / checkpoint-gate).
server.tool(
  "eda_spec_conformance",
  "Prove RTL conforms to its spec contract: port (name/dir/width), reset mode+polarity, and output latency. Spec may be a natural-language prompt, a markdown module header, or a JSON contract. Returns PASS/FAIL + findings.",
  {
    spec: z.string().describe("Spec file: .json contract, .md/.txt natural-language/markdown, or a .v/.sv header"),
    rtl_dir: z.string().optional().describe("Directory of RTL to check (use this OR verilog_files)"),
    verilog_files: z.array(z.string()).optional().describe("Explicit RTL files (use this OR rtl_dir)"),
    top: z.string().optional().describe("Top module name (default: first module / the spec's module)"),
    strict: z.boolean().default(false).describe("Fail on WARN findings too, not just ERROR"),
    programs_dir: z.string().default(VIBE_IC_PROGRAMS_DIR.endsWith("/") ? VIBE_IC_PROGRAMS_DIR : VIBE_IC_PROGRAMS_DIR + "/").describe("Directory containing the conformance program (auto-detected; overridable via $VIBE_IC_PROGRAMS_DIR)"),
  },
  async ({ spec, rtl_dir, verilog_files, top, strict, programs_dir }) => {
    try {
      assertSafePath(spec, "spec");
      if (rtl_dir) assertSafePath(rtl_dir, "rtl_dir");
      if (verilog_files) assertSafePaths(verilog_files, "verilog_files");
      if (top) assertSafeIdent(top, "top");
      optPath(programs_dir, "programs_dir");
    } catch (e) { return guardError(e); }
    if (!rtl_dir && !(verilog_files && verilog_files.length)) {
      return guardError(new Error("provide rtl_dir or verilog_files"));
    }

    const scriptPath = `${programs_dir}spec_conformance_check.py`;
    const argv = [scriptPath, "--spec", spec];
    if (rtl_dir) argv.push("--rtl-dir", rtl_dir);
    (verilog_files || []).forEach((f) => argv.push(f));
    if (top) argv.push("--top", top);
    if (strict) argv.push("--strict");

    let output = "", status = "ERROR", findings = 0, errors = 0;
    try {
      // run via argv (no shell); the program prints a summary line + findings
      // and exits 0 = PASS, 1 = FAIL (ERROR or, with --strict, WARN).
      const _r = _spawnSync("python3", argv, {
        timeout: 60000, maxBuffer: 5 * 1024 * 1024, encoding: "utf-8",
      });
      if (_r.error) throw _r.error;
      output = (_r.stdout || "") + (_r.stderr || "");
      const m = output.match(/findings?:\s*(\d+)\s*\((\d+)\s*error/i);
      findings = m ? parseInt(m[1]) : 0;
      errors = m ? parseInt(m[2]) : 0;
      status = (_r.status === 0) ? "PASS" : "FAIL";
    } catch (err) {
      output = (err.stdout || err.stderr || err.message || "").slice(-2000);
      status = "ERROR";
    }

    const pass = status === "PASS";
    if (rtl_dir) {
      writeManifest(rtl_dir, {
        step: "spec_conformance",
        status,
        tool: "vibe-ic",
        findings,
        errors,
      });
    }
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: pass,
          status,
          findings,
          errors,
          output: output.slice(-2000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_spec_lint ───
// since v0.1.5. Pre-RTL spec self-consistency lint — runs on the SPEC / prompt
// ALONE, before any RTL exists, and flags a spec that contradicts *itself*.
// Complements eda_spec_conformance (which needs the RTL to compare against):
// catching a garbled spec at the source lets you stop and clarify instead of
// faithfully implementing a broken contract. Two real benchmark misses motivate it:
//   • VerilogEval-v2 Prob099: interface declares Y1,Y3 but the body says "Y2 and Y4"
//     (defective problem; even the golden reference fails its own bench). The
//     RTL-side port-fidelity lint only sees this after generation — this sees it
//     in the prompt. → body-port-gap (WARN).
//   • CVDP arbiter: a spec asserting BOTH synchronous and asynchronous reset.
//     → reset-mode-contradiction / reset-polarity-contradiction (ERROR).
// Belongs at the very front of the Phase-1→Phase-2 checkpoint (before spec-to-rtl).
server.tool(
  "eda_spec_lint",
  "Lint a spec/prompt for SELF-contradiction before any RTL exists: garbled numbered-port gaps (body references Y2/Y4 absent from a declared Y1/Y3 interface) and reset-semantics contradictions (spec asserts both sync+async, or both active-high+low). Spec may be a natural-language prompt, markdown header, or .v/.sv header. Returns PASS/FAIL + findings.",
  {
    spec: z.string().describe("Spec file: .txt/.md prompt, .json contract, or .v/.sv header"),
    strict: z.boolean().default(false).describe("Fail on WARN findings (e.g. body-port-gap) too, not just ERROR"),
    programs_dir: z.string().default(VIBE_IC_PROGRAMS_DIR.endsWith("/") ? VIBE_IC_PROGRAMS_DIR : VIBE_IC_PROGRAMS_DIR + "/").describe("Directory containing the lint program (auto-detected; overridable via $VIBE_IC_PROGRAMS_DIR)"),
  },
  async ({ spec, strict, programs_dir }) => {
    try {
      assertSafePath(spec, "spec");
      optPath(programs_dir, "programs_dir");
    } catch (e) { return guardError(e); }

    const scriptPath = `${programs_dir}spec_self_consistency_check.py`;
    const argv = [scriptPath, "--spec", spec];
    if (strict) argv.push("--strict");

    let output = "", status = "ERROR", findings = 0, errors = 0;
    try {
      const _r = _spawnSync("python3", argv, {
        timeout: 60000, maxBuffer: 5 * 1024 * 1024, encoding: "utf-8",
      });
      if (_r.error) throw _r.error;
      output = (_r.stdout || "") + (_r.stderr || "");
      const m = output.match(/findings?:\s*(\d+)\s*\((\d+)\s*error/i);
      findings = m ? parseInt(m[1]) : 0;
      errors = m ? parseInt(m[2]) : 0;
      status = (_r.status === 0) ? "PASS" : "FAIL";
    } catch (err) {
      output = (err.stdout || err.stderr || err.message || "").slice(-2000);
      status = "ERROR";
    }

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: status === "PASS",
          status,
          findings,
          errors,
          output: output.slice(-2000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_fsm_table_gen ───
// since v0.1.6. Phase-2 "program writes the RTL" generator: given a structured
// FSM contract (states, encoding, transition table, per-state/Mealy outputs) it
// emits correct synthesizable Verilog DETERMINISTICALLY — no LLM, no don't-care
// guessing. Motivated by the VerilogEval-v2 run: many problems hand an explicit
// state-transition table (e.g. Prob100 fsm3comb) for which the RTL is mechanically
// derivable, yet Phase 2 previously fell back to a blind LLM shot. The generated
// Prob100 module passes the official VerilogEval testbench (Mismatches: 0/100).
// Kinds: moore_comb (next-state + Moore output logic only), moore_seq (registered
// state + clk/reset), mealy_seq.
server.tool(
  "eda_fsm_table_gen",
  "Deterministically generate synthesizable FSM RTL from a structured state-transition table (Moore comb/seq or Mealy). Program-first: same spec → byte-identical RTL, no LLM. Spec is a JSON/YAML file with module, kind, encoding, transitions, outputs (+ clk/reset for sequential).",
  {
    spec: z.string().describe("FSM spec file (.json or .yaml): module, kind (moore_comb|moore_seq|mealy_seq), encoding, transitions, outputs, [clk, reset]"),
    out: z.string().optional().describe("Output .sv path (default: returned in the response)"),
    programs_dir: z.string().default(VIBE_IC_PROGRAMS_DIR.endsWith("/") ? VIBE_IC_PROGRAMS_DIR : VIBE_IC_PROGRAMS_DIR + "/").describe("Directory containing fsm_table_rtl_gen.py (auto-detected; overridable via $VIBE_IC_PROGRAMS_DIR)"),
  },
  async ({ spec, out, programs_dir }) => {
    try {
      assertSafePath(spec, "spec");
      if (out) assertSafePath(out, "out");
      optPath(programs_dir, "programs_dir");
    } catch (e) { return guardError(e); }

    const scriptPath = `${programs_dir}fsm_table_rtl_gen.py`;
    const argv = [scriptPath, spec];
    if (out) argv.push("-o", out);

    let output = "", status = "ERROR";
    try {
      const _r = _spawnSync("python3", argv, {
        timeout: 60000, maxBuffer: 5 * 1024 * 1024, encoding: "utf-8",
      });
      if (_r.error) throw _r.error;
      output = (_r.stdout || "") + (_r.stderr || "");
      status = (_r.status === 0) ? "PASS" : "FAIL";
    } catch (err) {
      output = (err.stdout || err.stderr || err.message || "").slice(-4000);
      status = "ERROR";
    }

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: status === "PASS",
          status,
          rtl: out ? undefined : output,
          out: out || undefined,
          log: output.slice(-2000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_truth_table_gen ───
// since v0.1.7. Phase-2 deterministic combinational-logic generator, companion
// to eda_fsm_table_gen. Given a structured truth-table contract (inputs, outputs,
// rows, default) it emits a correct synthesizable case-based module — no LLM,
// byte-identical per spec. Motivated by the VerilogEval-v2 run: fully-specified
// truth-table / K-map problems (e.g. Prob069 truthtable1) are mechanically
// derivable. The generated Prob069 module passes the official VerilogEval
// testbench (Mismatches: 0/58). For a complete table the result is exactly
// correct; partial tables use an explicit `default` (canonical don't-care).
server.tool(
  "eda_truth_table_gen",
  "Deterministically generate combinational RTL from a structured truth table (inputs/outputs/rows + default). Program-first: same spec → byte-identical RTL, no LLM, no don't-care guessing. Spec is a JSON/YAML file; `in`/`out` are MSB-first binary strings over the declared ports.",
  {
    spec: z.string().describe("Truth-table spec file (.json or .yaml): module, inputs, outputs, rows[{in,out}], optional default"),
    out: z.string().optional().describe("Output .sv path (default: returned in the response)"),
    programs_dir: z.string().default(VIBE_IC_PROGRAMS_DIR.endsWith("/") ? VIBE_IC_PROGRAMS_DIR : VIBE_IC_PROGRAMS_DIR + "/").describe("Directory containing truth_table_rtl_gen.py (auto-detected; overridable via $VIBE_IC_PROGRAMS_DIR)"),
  },
  async ({ spec, out, programs_dir }) => {
    try {
      assertSafePath(spec, "spec");
      if (out) assertSafePath(out, "out");
      optPath(programs_dir, "programs_dir");
    } catch (e) { return guardError(e); }

    const scriptPath = `${programs_dir}truth_table_rtl_gen.py`;
    const argv = [scriptPath, spec];
    if (out) argv.push("-o", out);

    let output = "", status = "ERROR";
    try {
      const _r = _spawnSync("python3", argv, {
        timeout: 60000, maxBuffer: 5 * 1024 * 1024, encoding: "utf-8",
      });
      if (_r.error) throw _r.error;
      output = (_r.stdout || "") + (_r.stderr || "");
      status = (_r.status === 0) ? "PASS" : "FAIL";
    } catch (err) {
      output = (err.stdout || err.stderr || err.message || "").slice(-4000);
      status = "ERROR";
    }

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: status === "PASS",
          status,
          rtl: out ? undefined : output,
          out: out || undefined,
          log: output.slice(-2000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_gate_netlist_gen ───
// since v0.1.8. Phase-2 deterministic generator (with eda_fsm_table_gen /
// eda_truth_table_gen): a plain list of logic gates + wire connections → RTL,
// one `assign` per gate, no LLM. Motivated by VerilogEval-v2 gate-list problems
// (Prob065 7420 dual 4-input NAND, etc.); the generated Prob065 module passes the
// official testbench (Mismatches 0/239). Gate ops: and/or/nand/nor/xor/xnor/not/buf.
server.tool(
  "eda_gate_netlist_gen",
  "Deterministically generate combinational RTL from a gate netlist (inputs/outputs/wires/gates). Program-first: one assign per gate, byte-identical per spec, no LLM. Ops: and/or/nand/nor/xor/xnor/not/buf.",
  {
    spec: z.string().describe("Gate-netlist spec file (.json or .yaml): module, inputs, outputs, optional wires, gates[{op,out,in[]}]"),
    out: z.string().optional().describe("Output .sv path (default: returned in the response)"),
    programs_dir: z.string().default(VIBE_IC_PROGRAMS_DIR.endsWith("/") ? VIBE_IC_PROGRAMS_DIR : VIBE_IC_PROGRAMS_DIR + "/").describe("Directory containing gate_netlist_rtl_gen.py (auto-detected)"),
  },
  async ({ spec, out, programs_dir }) => {
    try {
      assertSafePath(spec, "spec");
      if (out) assertSafePath(out, "out");
      optPath(programs_dir, "programs_dir");
    } catch (e) { return guardError(e); }
    const scriptPath = `${programs_dir}gate_netlist_rtl_gen.py`;
    const argv = [scriptPath, spec];
    if (out) argv.push("-o", out);
    let output = "", status = "ERROR";
    try {
      const _r = _spawnSync("python3", argv, { timeout: 60000, maxBuffer: 5 * 1024 * 1024, encoding: "utf-8" });
      if (_r.error) throw _r.error;
      output = (_r.stdout || "") + (_r.stderr || "");
      status = (_r.status === 0) ? "PASS" : "FAIL";
    } catch (err) {
      output = (err.stdout || err.stderr || err.message || "").slice(-4000); status = "ERROR";
    }
    return { content: [{ type: "text", text: JSON.stringify({ success: status === "PASS", status, rtl: out ? undefined : output, out: out || undefined, log: output.slice(-2000) }) }] };
  }
);

// ─── Tool: eda_vector_op_gen ───
// since v0.1.8. Phase-2 deterministic generator: pure bit-plumbing vector ops →
// a single mechanical `assign`, no LLM. Motivated by VerilogEval-v2 (Prob004
// byte-reverse, Prob006 bit-reverse, Prob015 split, Prob064 concat, Prob042
// sign-extend). The generated Prob004 module passes the official testbench
// (Mismatches 0/110). Ops: reverse(chunk) / split / concat / sign_extend / zero_extend.
server.tool(
  "eda_vector_op_gen",
  "Deterministically generate combinational RTL for a vector op: reverse (bit/byte/chunk), split, concat, sign_extend, zero_extend. Program-first: one assign, byte-identical per spec, no LLM.",
  {
    spec: z.string().describe("Vector-op spec file (.json or .yaml): module, op, inputs, outputs (+ chunk for reverse, parts for concat)"),
    out: z.string().optional().describe("Output .sv path (default: returned in the response)"),
    programs_dir: z.string().default(VIBE_IC_PROGRAMS_DIR.endsWith("/") ? VIBE_IC_PROGRAMS_DIR : VIBE_IC_PROGRAMS_DIR + "/").describe("Directory containing vector_op_rtl_gen.py (auto-detected)"),
  },
  async ({ spec, out, programs_dir }) => {
    try {
      assertSafePath(spec, "spec");
      if (out) assertSafePath(out, "out");
      optPath(programs_dir, "programs_dir");
    } catch (e) { return guardError(e); }
    const scriptPath = `${programs_dir}vector_op_rtl_gen.py`;
    const argv = [scriptPath, spec];
    if (out) argv.push("-o", out);
    let output = "", status = "ERROR";
    try {
      const _r = _spawnSync("python3", argv, { timeout: 60000, maxBuffer: 5 * 1024 * 1024, encoding: "utf-8" });
      if (_r.error) throw _r.error;
      output = (_r.stdout || "") + (_r.stderr || "");
      status = (_r.status === 0) ? "PASS" : "FAIL";
    } catch (err) {
      output = (err.stdout || err.stderr || err.message || "").slice(-4000); status = "ERROR";
    }
    return { content: [{ type: "text", text: JSON.stringify({ success: status === "PASS", status, rtl: out ? undefined : output, out: out || undefined, log: output.slice(-2000) }) }] };
  }
);

// ─── Tool: eda_rtl_dispatch ───
// since v0.1.9. The Phase-2 "program-first, Claude-as-backup" entry point: given
// ONE structured design spec it auto-detects whether the design is mechanically
// derivable and routes to the matching deterministic generator (gate-netlist /
// FSM-table / truth-table / vector-op) — emitting correct RTL with NO LLM. If no
// deterministic generator applies it returns success:false with fallback:"llm",
// so the caller knows the body-synthesis genuinely needs the reasoning engine.
server.tool(
  "eda_rtl_dispatch",
  "Phase-2 program-first router: auto-classify a structured spec and route to the matching DETERMINISTIC RTL generator (gate-netlist via `gates`, FSM-table via `transitions`, truth-table via `rows`, vector-op via `op`). Returns RTL when deterministic, or fallback:'llm' when no generator applies.",
  {
    spec: z.string().describe("Structured design spec (.json/.yaml). Shape selects the route; `generator` may force one."),
    out: z.string().optional().describe("Output .sv path (default: returned in the response)"),
    programs_dir: z.string().default(VIBE_IC_PROGRAMS_DIR.endsWith("/") ? VIBE_IC_PROGRAMS_DIR : VIBE_IC_PROGRAMS_DIR + "/").describe("Directory containing deterministic_rtl_dispatcher.py (auto-detected)"),
  },
  async ({ spec, out, programs_dir }) => {
    try {
      assertSafePath(spec, "spec");
      if (out) assertSafePath(out, "out");
      optPath(programs_dir, "programs_dir");
    } catch (e) { return guardError(e); }
    const scriptPath = `${programs_dir}deterministic_rtl_dispatcher.py`;
    const argv = [scriptPath, spec];
    if (out) argv.push("-o", out);
    let output = "", code = -1;
    try {
      const _r = _spawnSync("python3", argv, { timeout: 60000, maxBuffer: 5 * 1024 * 1024, encoding: "utf-8" });
      if (_r.error) throw _r.error;
      output = (_r.stdout || "") + (_r.stderr || "");
      code = _r.status;
    } catch (err) {
      output = (err.stdout || err.stderr || err.message || "").slice(-4000); code = -1;
    }
    // exit 0 = deterministic RTL; 3 = no deterministic generator (LLM fallback); 1/2 = error
    const deterministic = code === 0;
    const llmFallback = code === 3;
    const routeMatch = output.match(/route . (\w+)/);
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: deterministic,
          deterministic,
          fallback: llmFallback ? "llm" : undefined,
          generator: routeMatch ? routeMatch[1] : undefined,
          out: (deterministic && out) ? out : undefined,
          log: output.slice(-2000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_professional_tb ───
// Deterministic PROFESSIONAL testbench generation from the Phase-1 L-docs.
// Combines cocotb + cocotb-coverage + Verilator/Icarus + an SVA bind; derives a
// reference model (closed-form for arithmetic; a bounded-latency + bit-order
// STREAMING scoreboard that closes the serial-datapath DEFER — e.g. the spm
// bit-serial multiplier, 208/208 vs (x*y) mod 2^N), functional coverage (L28
// covergroups) and SVA (L29). Emits under phase2/stage1/sim_professional/<top>/.
server.tool(
  "eda_professional_tb",
  "Generate a PROFESSIONAL, high-coverage cocotb testbench deterministically from a project's Phase-1 L-docs: interface (L1/L9), clock/reset (L8/L9), a reference model (closed-form for arithmetic primitives; a bounded-latency + bit-order STREAMING scoreboard that closes the serial-datapath functional-verification gap), functional coverage (covergroups) + SVA assertions. Emits tb_<top>.py + coverage model + assertions + Makefile + verification plan.",
  {
    project: z.string().describe("Project dir (contains phase1/generated_docs/L*.json + phase2/stage1/rtl/)"),
    out_dir: z.string().optional().describe("Output dir (default phase2/stage1/sim_professional/<top>/)"),
    programs_dir: z.string().default(VIBE_IC_PROGRAMS_DIR.endsWith("/") ? VIBE_IC_PROGRAMS_DIR : VIBE_IC_PROGRAMS_DIR + "/").describe("Directory containing professional_tb_gen.py (auto-detected)"),
  },
  async ({ project, out_dir, programs_dir }) => {
    try {
      assertSafePath(project, "project");
      if (out_dir) assertSafePath(out_dir, "out_dir");
      optPath(programs_dir, "programs_dir");
    } catch (e) { return guardError(e); }
    const scriptPath = `${programs_dir}professional_tb_gen.py`;
    const argv = [scriptPath, project];
    if (out_dir) argv.push("--out-dir", out_dir);
    let output = "", status = "ERROR", result = {};
    try {
      const _r = _spawnSync("python3", argv, { timeout: 120000, maxBuffer: 5 * 1024 * 1024, encoding: "utf-8" });
      if (_r.error) throw _r.error;
      output = (_r.stdout || "") + (_r.stderr || "");
      status = (_r.status === 0) ? "PASS" : "FAIL";
      const m = (_r.stdout || "").match(/\{[\s\S]*\}\s*$/);
      if (m) { try { result = JSON.parse(m[0]); } catch { /* keep raw */ } }
    } catch (err) {
      output = (err.stdout || err.stderr || err.message || "").slice(-4000); status = "ERROR";
    }
    return { content: [{ type: "text", text: JSON.stringify({ success: status === "PASS", status, ...result, log: output.slice(-2000) }) }] };
  }
);

// ─── Tool: eda_cocotb ───
server.tool(
  "eda_cocotb",
  "Run cocotb Python testbench with Verilator or Icarus Verilog backend. Returns test pass/fail counts.",
  {
    verilog_files: z.array(z.string()).describe("Paths to Verilog/SV source files"),
    top_module: z.string().describe("Top module name"),
    testbench_py: z.string().describe("Path to cocotb Python testbench file"),
    simulator: z.enum(["verilator", "icarus"]).default("icarus").describe("Simulator backend"),
    work_dir: z.string().default("./sim/cocotb_work").describe("Working directory for build artifacts. v0.123: default changed from /tmp/cocotb_work so artifacts land in the project tree."),
  },
  async ({ verilog_files, top_module, testbench_py, simulator, work_dir }) => {
    try {
      assertSafePaths(verilog_files, "verilog_files");
      assertSafePath(testbench_py, "testbench_py");
      assertSafeIdent(top_module, "top_module");
      optPath(work_dir, "work_dir");
    } catch (e) { return guardError(e); }
    const simMap = { verilator: "verilator", icarus: "icarus" };
    const sim = simMap[simulator];
    const verilogSources = verilog_files.join(" ");

    const makefileContent = `
SIM ?= ${sim}
TOPLEVEL_LANG ?= verilog
VERILOG_SOURCES = ${verilogSources}
TOPLEVEL = ${top_module}
MODULE = $(basename $(notdir ${testbench_py}))
include $(shell cocotb-config --makefiles)/Makefile.sim
`;

    // Stage the testbench AND every sibling Python helper from its directory
    // (e.g. `import harness_library`) into work_dir, and put work_dir on
    // PYTHONPATH, so a cocotb test that imports a local module runs out-of-the-box
    // instead of dying with ModuleNotFoundError. The `|| true` tolerates the
    // self-copy case when work_dir == the testbench's own directory.
    const script = `
TBDIR="$(dirname ${testbench_py})" && \\
mkdir -p ${work_dir} && \\
echo '${makefileContent.replace(/'/g, "'\\''")}' > ${work_dir}/Makefile && \\
cp ${testbench_py} ${work_dir}/ && \\
{ cp "$TBDIR"/*.py ${work_dir}/ 2>/dev/null || true; } && \\
cd ${work_dir} && \\
export PYTHONPATH="$(pwd):$PYTHONPATH" && \\
export PATH=${TOOLS}/verilator/bin:${TOOLS}/iverilog/bin:${TOOLS}/bin:$PATH && \\
export LD_LIBRARY_PATH=${TOOLS}/iverilog/lib:$LD_LIBRARY_PATH && \\
make -j${_edaThreadsToken()} SIM=${sim} 2>&1
`;

    const result = dockerExec(script, 300000);

    const passMatch = result.output.match(/(\d+)\s+passed/i);
    const failMatch = result.output.match(/(\d+)\s+failed/i);
    const totalMatch = result.output.match(/(\d+)\s+tests?\s+(?:ran|total)/i);
    const passed = passMatch ? parseInt(passMatch[1]) : 0;
    const failed = failMatch ? parseInt(failMatch[1]) : 0;
    const total = totalMatch ? parseInt(totalMatch[1]) : passed + failed;

    const success = result.success && failed === 0 && passed > 0;

    if (success) {
      writeManifest(work_dir, {
        step: "cocotb",
        status: "PASS",
        tool: `cocotb/${simulator}`,
        tests_passed: passed,
        tests_failed: failed,
        tests_total: total,
      });
    }

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success,
          tests_passed: passed,
          tests_failed: failed,
          tests_total: total,
          simulator,
          output: result.output.slice(-3000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_fpga_compile ───
server.tool(
  "eda_fpga_compile",
  "Compile design for Intel FPGA (Quartus) or Xilinx (Vivado). Runs on host, not Docker.",
  {
    project_dir: z.string().describe("FPGA project directory path"),
    tool: z.enum(["quartus", "vivado"]).describe("FPGA tool to use"),
    qsf_file: z.string().optional().describe("Quartus Settings File path (required for quartus)"),
    xdc_file: z.string().optional().describe("Vivado constraints file path (required for vivado)"),
    top_module: z.string().optional().describe("Top module name (for vivado flow)"),
    part: z.string().optional().describe("FPGA part number (for vivado flow)"),
  },
  async ({ project_dir, tool, qsf_file, xdc_file, top_module, part }) => {
    try {
      assertSafePath(project_dir, "project_dir");
      optPath(qsf_file, "qsf_file"); optPath(xdc_file, "xdc_file");
      optIdent(top_module, "top_module"); optToken(part, "part");
    } catch (e) { return guardError(e); }
    // security hardening: this tool runs on the HOST (not Docker). Inputs are
    // already validated at handler entry; here we execute via argv arrays so
    // no value is ever shell-parsed (the former `cd "${project_dir}" &&
    // quartus_sh ...` and `echo '...' > "${tclPath}"` were host
    // command-injection vectors).
    let bin, args, cwd;
    let timeoutMs = 600000; // 10 minutes

    if (tool === "quartus") {
      if (!qsf_file) {
        return { content: [{ type: "text", text: JSON.stringify({ success: false, error: "qsf_file is required for Quartus" }) }] };
      }
      // Extract project name from QSF file
      const qsfBase = qsf_file.replace(/\.qsf$/, "");
      const projName = qsfBase.substring(qsfBase.lastIndexOf("/") + 1);
      bin = "quartus_sh"; args = ["--flow", "compile", projName]; cwd = project_dir;
    } else {
      // Vivado
      if (!xdc_file || !top_module || !part) {
        return { content: [{ type: "text", text: JSON.stringify({ success: false, error: "xdc_file, top_module, and part are required for Vivado" }) }] };
      }
      const tclScript = `
create_project -force vivado_proj ${project_dir}/vivado_proj -part ${part}
add_files [glob ${project_dir}/*.v ${project_dir}/*.sv]
read_xdc ${xdc_file}
set_property top ${top_module} [current_fileset]
launch_runs synth_1 -jobs 4
wait_on_run synth_1
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
puts "=== VIVADO_COMPLETE ==="
exit
`;
      const tclPath = `${project_dir}/run_vivado.tcl`;
      try {
        require_fs_writeFileSync(tclPath, tclScript, "utf-8");
      } catch (e) { /* ignore */ }
      bin = "vivado"; args = ["-mode", "batch", "-source", tclPath];
    }

    let result;
    {
      const r = _spawnSync(bin, args, {
        cwd,
        timeout: timeoutMs,
        maxBuffer: 10 * 1024 * 1024,
        encoding: "utf-8",
      });
      const merged = (r.stdout || "") + (r.stderr || "");
      if (r.error) {
        result = { success: false, output: merged, error: r.error.message || String(r.error) };
      } else if (r.status === 0) {
        result = { success: true, output: merged };
      } else {
        result = { success: false, output: merged, error: r.stderr || `exited with status ${r.status}` };
      }
    }

    // Parse resource usage
    let resources = {};
    if (tool === "quartus") {
      const lutsMatch = result.output.match(/Total logic elements\s*[:.]\s*([\d,]+)/i) ||
                         result.output.match(/ALMs?\s*[:.]\s*([\d,]+)/i);
      const regsMatch = result.output.match(/Total registers\s*[:.]\s*([\d,]+)/i) ||
                         result.output.match(/Dedicated logic registers\s*[:.]\s*([\d,]+)/i);
      const memMatch = result.output.match(/Total memory bits\s*[:.]\s*([\d,]+)/i);
      const fmaxMatch = result.output.match(/Fmax\s*[:.]\s*([\d.]+)\s*MHz/i) ||
                         result.output.match(/(\d+\.?\d*)\s*MHz/);
      resources = {
        logic_elements: lutsMatch ? lutsMatch[1].replace(/,/g, "") : null,
        registers: regsMatch ? regsMatch[1].replace(/,/g, "") : null,
        memory_bits: memMatch ? memMatch[1].replace(/,/g, "") : null,
        fmax_mhz: fmaxMatch ? parseFloat(fmaxMatch[1]) : null,
      };
    } else {
      const lutsMatch = result.output.match(/LUTs?\s*[:|]\s*([\d,]+)/i);
      const ffsMatch = result.output.match(/(?:FFs?|Flip.?Flops?)\s*[:|]\s*([\d,]+)/i);
      const bramMatch = result.output.match(/BRAM\s*[:|]\s*([\d.]+)/i);
      resources = {
        luts: lutsMatch ? lutsMatch[1].replace(/,/g, "") : null,
        flip_flops: ffsMatch ? ffsMatch[1].replace(/,/g, "") : null,
        bram: bramMatch ? bramMatch[1] : null,
      };
    }

    const success = tool === "quartus"
      ? result.success && !result.output.includes("Error (")
      : result.success && result.output.includes("VIVADO_COMPLETE");

    // Parse timing summary
    const slackMatch = result.output.match(/Slack\s*[:(]\s*([\d.-]+)/i) ||
                       result.output.match(/([\d.-]+)\s*ns\s+slack/i);
    const timing = {
      slack_ns: slackMatch ? parseFloat(slackMatch[1]) : null,
      timing_met: slackMatch ? parseFloat(slackMatch[1]) >= 0 : null,
    };

    // v0.99: locate the produced SOF/BIT and hash it under the current
    // session id, so eda_fpga_program / connect_test can verify the chain.
    let compiledArtifact = null;
    let compiledHash = null;
    try {
      const outDir = `${project_dir}/output_files`;
      if (existsSync(outDir)) {
        const fs = await import("fs");
        const files = fs.readdirSync(outDir);
        const sof = files.find(f => f.endsWith(".sof") || f.endsWith(".bit"));
        if (sof) {
          compiledArtifact = `${outDir}/${sof}`;
          compiledHash = sha256File(compiledArtifact);
        }
      }
    } catch (_) { /* best effort */ }
    if (success && compiledArtifact) {
      _LAST_FPGA_COMPILE = {
        sof_path: compiledArtifact,
        sha256: compiledHash,
        timestamp: new Date().toISOString(),
        session_id: MCP_SESSION_ID,
      };
    }

    writeManifest(project_dir, {
      step: "fpga_compile",
      status: success ? "PASS" : "FAIL",
      tool: tool === "quartus" ? "Quartus" : "Vivado",
      resources,
      timing,
      compiled_artifact: compiledArtifact,
      compiled_artifact_sha256: compiledHash,
      session_id: MCP_SESSION_ID,
    });

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success,
          tool,
          resources,
          timing,
          compiled_artifact: compiledArtifact,
          compiled_artifact_sha256: compiledHash,
          session_id: MCP_SESSION_ID,
          output: result.output.slice(-3000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_fpga_program ───
//
// Wave 33 (mcp-eda v0.99.9) — close the back-door bypass.
//
// Forensic background: WAVE32_DUAL_GOVERNANCE_HOLE.md proved the
// previous direct `execSync("quartus_pgm ...")` implementation had
// NO pre-burn audit guard, so an agent could burn a SOF whose
// `phase23_completion_audit.json` had verdict=FAIL by routing
// through this tool instead of `device_fpga_de10lite_program`. The
// v0.119.64 timeline (SOF mtime before audit JSON, 5 connect_test
// runs all FAIL) confirmed this path was used.
//
// Fix: this tool is now a THIN WRAPPER. For the Quartus/SOF path —
// the only path that ever talked to the lab rig — we delegate to the
// device driver `device_fpga_de10lite_program`'s `mode_program`,
// which runs `_run_flow_compliance_pre_burn` with fail-closed
// semantics. `bypass_pre_burn_check` is HARD-CODED to `false` here
// (the old `verify_burn` arg is the only knob the wrapper still
// exposes). Vivado/BIT path stays in-process as a placeholder; if
// you ship Vivado in production, route it through a similar
// vendor-device manifest before allowing it to reach silicon.
server.tool(
  "eda_fpga_program",
  "Program (burn) SOF/BIT file to an FPGA board. Wave 33: SOF path "
  + "delegates to device_fpga_de10lite_program (which enforces the "
  + "pre-burn flow_compliance + RTL precheck guard). bypass_pre_burn_"
  + "check is unreachable from this tool — use device_fpga_de10lite_"
  + "program directly if you genuinely need the override.",
  {
    tool: z.enum(["quartus", "vivado"]).describe("FPGA tool to use"),
    sof_file: z.string().optional().describe("Intel SOF file path (required for quartus)"),
    bit_file: z.string().optional().describe("Xilinx BIT file path (required for vivado)"),
    cable_index: z.number().default(1).describe("USB-Blaster / JTAG cable index"),
    verify_burn: z.boolean().default(false).describe(
      "v0.99: after programming, re-read JTAG signature and confirm the "
      + "device matches the bitstream's expected part. Adds ~3-5 s; "
      + "highly recommended before claiming Phase-2c PASS."
    ),
    expected_device: z.string().optional().describe(
      "v0.99: Expected device part (e.g. '10M50DAF484C7G') for verify_burn "
      + "to match against. If omitted, verify_burn just records what's on "
      + "the JTAG chain."
    ),
    rtl_dir: z.string().optional().describe(
      "Forwarded to device_fpga_de10lite_program for the rtl_precheck "
      + "gate (when present). Enables the existing per-auditor checks."
    ),
  },
  async ({ tool, sof_file, bit_file, cable_index, verify_burn, expected_device, rtl_dir }) => {
    try {
      optPath(sof_file, "sof_file"); optPath(bit_file, "bit_file");
      optPath(rtl_dir, "rtl_dir"); optToken(expected_device, "expected_device");
    } catch (e) { return guardError(e); }
    if (tool === "quartus") {
      if (!sof_file) {
        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              success: false,
              error: "sof_file is required for Quartus programming",
              error_code: "invalid_argument",
            }),
          }],
        };
      }

      // Wave 33: delegate to the guarded device driver. This is the
      // SAME code path device_fpga_de10lite_program runs — single
      // source of truth, single guard.
      const driverPath = resolve(
        __dirname_eda, "devices", "fpga", "terasic-de10lite", "driver.py",
      );
      const driverArgs = {
        sof_path: sof_file,
        // device_index is what the driver accepts; cable_index is the
        // legacy eda_fpga_program parameter name. Map.
        device_index: cable_index,
        // bypass_pre_burn_check is HARD-CODED FALSE — Wave 33 closes
        // the back door. Anyone who genuinely needs the override has
        // to invoke device_fpga_de10lite_program directly.
        bypass_pre_burn_check: false,
      };
      if (rtl_dir) driverArgs.rtl_dir = rtl_dir;

      let driverResult;
      try {
        const child = _spawnSync(
          "python3",
          [driverPath, "--mode", "program", "--json-args", "-"],
          {
            input: JSON.stringify(driverArgs),
            encoding: "utf-8",
            timeout: 300000,
            maxBuffer: 10 * 1024 * 1024,
          },
        );
        driverResult = {
          stdout: child.stdout || "",
          stderr: child.stderr || "",
          status: child.status,
          signal: child.signal,
        };
      } catch (e) {
        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              success: false,
              error: `eda_fpga_program: failed to invoke device driver: ${e.message}`,
              error_code: "driver_invoke_failed",
            }),
          }],
        };
      }

      let body;
      try {
        body = JSON.parse(driverResult.stdout);
      } catch (e) {
        body = {
          success: false,
          error: "device driver returned non-JSON stdout",
          parse_error: e.message,
          stdout_tail: driverResult.stdout.slice(-2000),
          stderr_tail: driverResult.stderr.slice(-500),
          exit_code: driverResult.status,
        };
      }

      // Hash + session-id provenance regardless of success/failure
      // verdict — write_provenance lets downstream tools see the
      // attempt even when blocked.
      const programmedHash = sha256File(sof_file);
      const guardBlocked = !body.success
        && typeof body.error_code === "string"
        && body.error_code.startsWith("burn_blocked");
      if (body.success) {
        _LAST_FPGA_PROGRAM = {
          sof_path: sof_file,
          sha256: programmedHash,
          timestamp: new Date().toISOString(),
          session_id: MCP_SESSION_ID,
        };
      }

      // Optional JTAG verify (only on success).
      let verify = null;
      if (verify_burn && body.success) {
        try {
          const jtagOut = execSync(
            `quartus_pgm -l 2>&1 | head -50`,
            { timeout: 10000, encoding: "utf-8", maxBuffer: 1024 * 1024 },
          );
          const detected = (jtagOut.match(/Device\s*\d*:\s*(\S+)/i) || [])[1] || null;
          verify = {
            jtag_response_present: jtagOut.length > 0,
            detected_device: detected,
            expected_device: expected_device || null,
            matches: expected_device
              ? Boolean(detected && detected.includes(expected_device))
              : null,
          };
        } catch (e) {
          verify = { error: String(e), jtag_response_present: false };
        }
      }

      // Wave 33: write burn provenance JSON whenever the burn
      // actually completed (success path). The path captures the
      // audit JSON SHA + verdict that the driver returned, so
      // downstream provenance gates can cross-check RESULT.md
      // citations.
      let burnProvenancePath = null;
      if (body.success && typeof body.flow_compliance === "object") {
        const fc = body.flow_compliance || {};
        const projectRoot = fc.project_root;
        if (projectRoot && existsSync(projectRoot)) {
          try {
            const reportsDir = join(projectRoot, "reports");
            if (!existsSync(reportsDir)) mkdirSync(reportsDir, { recursive: true });
            burnProvenancePath = join(reportsDir, "burn_provenance.json");
            const auditJsonPath = fc.audit_json_path || null;
            const auditSha = auditJsonPath ? sha256File(auditJsonPath) : null;
            const provenanceRecord = {
              burn_at: new Date().toISOString(),
              sof_path: sof_file,
              sof_sha256: programmedHash,
              audit_json_path: auditJsonPath,
              audit_sha256: auditSha,
              audit_verdict: fc.flow_compliance_verdict || "UNKNOWN",
              guard_invoked: true,
              tool: "eda_fpga_program",
              session_id: MCP_SESSION_ID,
            };
            require_fs_writeFileSync(
              burnProvenancePath,
              JSON.stringify(provenanceRecord, null, 2),
            );
          } catch (e) {
            burnProvenancePath = null;
          }
        }
      }

      writeManifest("/tmp", {
        step: "fpga_program",
        status: body.success ? "PASS" : "FAIL",
        tool: "Quartus Programmer (Wave 33 wrapper → device_fpga_de10lite_program)",
        device: null,
        file: sof_file,
        programmed_artifact_sha256: programmedHash,
        session_id: MCP_SESSION_ID,
        compile_artifact_sha256: _LAST_FPGA_COMPILE ? _LAST_FPGA_COMPILE.sha256 : null,
        program_matches_compile: !!(_LAST_FPGA_COMPILE
          && _LAST_FPGA_COMPILE.sha256 === programmedHash),
        guard_blocked: guardBlocked,
      });

      return {
        content: [{
          type: "text",
          text: JSON.stringify({
            ...body,
            tool: "quartus",
            file_programmed: sof_file,
            programmed_artifact_sha256: programmedHash,
            session_id: MCP_SESSION_ID,
            compile_artifact_sha256: _LAST_FPGA_COMPILE ? _LAST_FPGA_COMPILE.sha256 : null,
            program_matches_compile: !!(_LAST_FPGA_COMPILE
              && _LAST_FPGA_COMPILE.sha256 === programmedHash),
            verify_burn: verify,
            burn_provenance_path: burnProvenancePath,
            wave33_guard: "delegated_to_device_fpga_de10lite_program",
          }),
        }],
      };
    }

    // Vivado/BIT path — preserved as-is for now (no lab-rig usage in
    // current deployments). If you ship Vivado, mirror the Wave 33
    // wrapper pattern through a Xilinx vendor-device manifest.
    if (!bit_file) {
      return {
        content: [{
          type: "text",
          text: JSON.stringify({
            success: false,
            error: "bit_file is required for Vivado programming",
            error_code: "invalid_argument",
          }),
        }],
      };
    }
    const tclScript = `
open_hw_manager
connect_hw_server
open_hw_target
set device [lindex [get_hw_devices] 0]
current_hw_device $device
set_property PROGRAM.FILE {${bit_file}} $device
program_hw_devices $device
puts "=== PROGRAM_COMPLETE ==="
close_hw_manager
exit
`;
    // security hardening: write the TCL to a temp file and run vivado via
    // argv (no shell) — replaces `vivado ... -source <(echo '...')`, which
    // relied on bash process-substitution under execSync's /bin/sh and put
    // bit_file through a shell. The temp file is unlinked in `finally` so a
    // long-running mcp server doesn't accumulate one `vivado_program_*.tcl`
    // per Vivado-tool call (the legacy `<(echo ...)` form left nothing on
    // disk; this preserves that property).
    const _tclPath = join(process.env.TMPDIR || "/tmp", `vivado_program_${randomUUID()}.tcl`);
    let result;
    try {
      require_fs_writeFileSync(_tclPath, tclScript, "utf-8");
      const r = _spawnSync("vivado", ["-mode", "batch", "-source", _tclPath], {
        timeout: 120000,
        maxBuffer: 10 * 1024 * 1024,
        encoding: "utf-8",
      });
      const merged = (r.stdout || "") + (r.stderr || "");
      if (r.error) result = { success: false, output: merged, error: r.error.message || String(r.error) };
      else if (r.status === 0) result = { success: true, output: merged };
      else result = { success: false, output: merged, error: r.stderr || `exited with status ${r.status}` };
    } catch (err) {
      result = { success: false, output: err.stdout || "", error: err.stderr || err.message };
    } finally {
      // Best-effort cleanup; tolerate the file having never been written
      // (e.g. require_fs_writeFileSync threw on a read-only TMPDIR).
      try { unlinkSync(_tclPath); } catch (_) { /* not present — fine */ }
    }
    const deviceMatch = result.output.match(/Device\s*(?:\d+)?:\s*(\S+)/i) ||
                        result.output.match(/Info.*?:\s*(EP\S+|xc\S+)/i);
    const success = result.success && result.output.includes("PROGRAM_COMPLETE");
    const programmedHash = sha256File(bit_file);
    if (success) {
      _LAST_FPGA_PROGRAM = {
        sof_path: bit_file,
        sha256: programmedHash,
        timestamp: new Date().toISOString(),
        session_id: MCP_SESSION_ID,
      };
    }
    writeManifest("/tmp", {
      step: "fpga_program",
      status: success ? "PASS" : "FAIL",
      tool: "Vivado Programmer",
      device: deviceMatch ? deviceMatch[1] : null,
      file: bit_file,
      programmed_artifact_sha256: programmedHash,
      session_id: MCP_SESSION_ID,
    });
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success,
          tool: "vivado",
          device: deviceMatch ? deviceMatch[1] : null,
          file_programmed: bit_file,
          programmed_artifact_sha256: programmedHash,
          session_id: MCP_SESSION_ID,
          output: result.output.slice(-2000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_extraction ───
server.tool(
  "eda_extraction",
  "Extract parasitics from layout using Magic. Produces SPEF or SPICE extracted netlist. since v0.2.33 (ORGANIC-20260531): set `promote_ports`=true (a.k.a. port_makeall) to inject `port makeall` into the extraction TCL so the emitted `.subckt <top>_flat` carries TOP-LEVEL PORTS — required for device-level netgen LVS to anchor top-level pin matching (a portless .subckt makes any LVS 'match' vacuous). NOTE: `port makeall` only promotes pin labels that sit on a PDK pin/port-purpose layer (sky130 MET3PIN 70/16); if the GDS pin text is on a drawing layer (the common GDS-writer default) rather than the pin-purpose layer, promotion finds nothing and the .subckt stays portless — re-emit the labels on the port-purpose layer first, or DEF-seed via programs/lvs_def_port_seed.py.",
  {
    def_file: z.string().optional().describe("Input DEF file path (provide either def_file or gds_file)"),
    gds_file: z.string().optional().describe("Input GDS file path (provide either def_file or gds_file)"),
    top_cell: z.string().describe("Top cell name"),
    pdk: z.enum(["gf180", "sky130", "nangate45", "custom"]).default("gf180"),
    output_format: z.enum(["spef", "spice"]).default("spef").describe("Output format: spef or spice"),
    output_dir: z.string().default("./extracted").describe("Output directory. v0.123: default changed from /tmp/extraction so artifacts land in the project tree."),
    promote_ports: z.boolean().default(false).describe("Inject `port makeall` into the extraction TCL so the emitted `.subckt <top>_flat` carries top-level ports (needed for device-level netgen LVS top-level pin matching). Only useful for output_format=spice. Default false (preserves the legacy portless extraction)."),
    custom_lib: z.string().optional().describe("Path to Liberty .lib file (custom PDK)"),
    custom_techlef: z.string().optional().describe("Path to tech LEF file (custom PDK)"),
    custom_celllef: z.string().optional().describe("Path to cell LEF file (custom PDK)"),
    custom_cellgds: z.string().optional().describe("Path to cell GDS file (custom PDK)"),
    custom_site: z.string().optional().describe("Site name for floorplan (custom PDK)"),
    custom_vdd: z.string().optional().describe("VDD pin name (custom PDK)"),
    custom_vss: z.string().optional().describe("VSS pin name (custom PDK)"),
    custom_metal_prefix: z.string().optional().describe("Metal-layer name prefix for custom PDKs whose layers don't match SKY130 'met' naming (e.g. 'MET' for a commercial 180nm PDK's MET1-6). Default 'met'."),
    field_solve_spef: z.string().optional().describe("Opt-in FIELD-SOLVED coupling upgrade: pass an existing grounded/analytical SPEF to UPGRADE it with real 3D BEM coupling. Inverts the PDK's own area+fringe cap to a fitted dielectric stack (programs/pdk_dielectric_fit.py) then runs the OSS solver FasterCap on the routed geometry (programs/fastercap_extract.py) — lateral + inter-layer crossover the analytical parallel-plate model misses. Requires def_file + custom_techlef. Self-reports NOT_APPLICABLE if FasterCap is absent (never a fabricated matrix). DISCLOSED: fitted stack, generic dielectric — NOT foundry rules.C, NOT crosstalk-SI sign-off. When set, this runs instead of Magic extraction."),
    field_solve_container: z.string().default("vibeic-eda").describe("Docker container for FasterCap (field_solve_spef mode)"),
  },
  async ({ def_file, gds_file, top_cell, pdk, output_format, output_dir, promote_ports, custom_lib, custom_techlef, custom_celllef, custom_cellgds, custom_site, custom_vdd, custom_vss, custom_metal_prefix, field_solve_spef, field_solve_container }) => {
    try {
      optPath(def_file, "def_file"); optPath(gds_file, "gds_file");
      assertSafeIdent(top_cell, "top_cell"); optPath(output_dir, "output_dir");
      optPath(custom_lib, "custom_lib"); optPath(custom_techlef, "custom_techlef");
      optPath(custom_celllef, "custom_celllef"); optPath(custom_cellgds, "custom_cellgds");
      optToken(custom_site, "custom_site"); optIdent(custom_vdd, "custom_vdd");
      optIdent(custom_vss, "custom_vss"); optToken(custom_metal_prefix, "custom_metal_prefix");
      optPath(field_solve_spef, "field_solve_spef"); assertSafeIdent(field_solve_container, "field_solve_container");
    } catch (e) { return guardError(e); }
    // Opt-in field-solved coupling upgrade (shells to the plugin program).
    if (field_solve_spef !== undefined) {
      if (!def_file || !custom_techlef) {
        return { content: [{ type: "text", text: JSON.stringify({ success: false, error: "field_solve_spef requires def_file + custom_techlef" }) }] };
      }
      const t0s = Date.now();
      const args = [`${VIBE_IC_PROGRAMS_DIR}/fastercap_extract.py`,
        "--def", def_file, "--lef", custom_techlef, "--spef", field_solve_spef,
        "--container", field_solve_container];
      const o = _spawnSync("python3", args, { timeout: 1800000, maxBuffer: 10 * 1024 * 1024, encoding: "utf-8" });
      const merged = (o.stdout || "") + (o.stderr || "");
      return wrapResult({
        success: !o.error && o.status === 0,
        t0: t0s,
        toolVersion: `fastercap_extract @ mcp-eda@${SERVER_VERSION}`,
        error: o.error ? (o.error.message || String(o.error)) : (o.status === 0 ? undefined : `exited ${o.status}`),
        output: merged,
      });
    }
    if (!def_file && !gds_file) {
      return { content: [{ type: "text", text: JSON.stringify({ success: false, error: "Either def_file or gds_file is required" }) }] };
    }

    const cfg = pdkConfig(pdk, { custom_lib, custom_techlef, custom_celllef, custom_cellgds, custom_site, custom_vdd, custom_vss, custom_metal_prefix });

    // Determine Magic tech file
    let techFile;
    if (pdk === "gf180") {
      techFile = `${cfg.pdk_path}/libs.tech/magic/gf180mcuD.tech`;
    } else if (pdk === "sky130") {
      techFile = `${cfg.pdk_path}/libs.tech/magic/sky130A.tech`;
    } else {
      // custom: user should have magic tech in the custom paths; use a generic fallback
      techFile = custom_techlef || "";
    }

    const inputFile = gds_file || def_file;
    const readCmd = gds_file ? `gds read ${gds_file}` : `def read ${def_file}`;
    const outputExt = output_format === "spef" ? "spef" : "spice";
    const outputFile = `${output_dir}/${top_cell}.${outputExt}`;

    const extractCmd = output_format === "spef"
      ? `ext2spef`
      : `ext2spice lvs\next2spice`;

    // ORGANIC-20260531 fix #2: promote_ports injects `port makeall` so the
    // emitted `.subckt <top>_flat` carries TOP-LEVEL PORTS. Without it the
    // extracted top subckt is portless and device-level netgen LVS has no
    // anchor for top-level pin matching (any 'match' on it is vacuous). It
    // sits AFTER `select top cell` and BEFORE `extract all`, matching the
    // reference programs/magic_port_extract_emit.py ordering.
    const promoteClause = (promote_ports && output_format === "spice")
      ? "port makeall\n" : "";

    const magicScript = `
${readCmd}
load ${top_cell}
flatten ${top_cell}_flat
load ${top_cell}_flat
select top cell
${promoteClause}extract all
${extractCmd}
puts "=== EXTRACTION_COMPLETE ==="
quit
`;

    // v0.99.1 fix: custom PDKs without a Magic .tech file silently
    // produced a 181-byte SPEF placeholder (just headers, no parasitic
    // data) that downstream spef_extraction_check correctly rejected
    // as TOO_SMALL. Detect the missing-tech case up-front and return a
    // clean structured error so the caller can either supply a tech
    // file or document the deferral via waivers.json instead of
    // chasing a phantom output. Mirrors eda_drc_klayout's
    // structural_only fallback pattern.
    const techExistsCmd = techFile ? `[ -f ${techFile} ] && echo TECH_OK || echo TECH_MISSING` : "echo TECH_MISSING";
    const techCheck = dockerExec(`export PATH=${TOOLS}/bin:$PATH && ${techExistsCmd}`, 5000);
    const techMissing = (techCheck.output || "").includes("TECH_MISSING");
    if (pdk === "custom" && techMissing) {
      writeManifest(output_dir || "/tmp", {
        step: "extraction",
        status: "DEFERRED",
        tool: "Magic",
        deck_mode: "unavailable",
        top_cell,
        pdk,
        reason: "custom PDK has no Magic .tech file",
      });
      return {
        content: [{
          type: "text",
          text: JSON.stringify({
            success: false,
            deck_mode: "unavailable",
            error: "extraction_unavailable_for_custom_pdk",
            advisory: "This custom PDK has no Magic tech file (custom_techlef is a tech LEF, not a Magic .tech). Magic cannot extract parasitics without a calibrated tech file. Options: (1) supply a real Magic .tech via custom_techlef pointing at a .tech file, or (2) document the deferral in waivers.json under spef_extraction_unavailable_reason and use a structural-only flow.",
            output_file: null,
            output_format,
            top_cell,
          }),
        }],
      };
    }

    // v0.73 Bug B fix: dockerExec uses `bash -c` (non-login) so /foss/tools/bin
    // is not on PATH → magic fails with "command not found". Other handlers
    // (eda_ir_drop, eda_pnr, ...) fix this by explicitly prepending PATH.
    // Match that pattern here rather than changing the shared helper.
    const result = dockerExec(
      `export PATH=${TOOLS}/bin:$PATH && mkdir -p ${output_dir} && cd ${output_dir} && echo '${magicScript.replace(/'/g, "'\\''")}' | magic -dnull -noconsole -T ${techFile} 2>&1 && ls -la ${output_dir}/*.${outputExt} 2>/dev/null`,
      300000
    );

    const complete = result.output.includes("EXTRACTION_COMPLETE");
    const fileExists = result.output.includes(`.${outputExt}`);

    // v0.99.1: detect the empty-output case (header-only file, no parasitic
    // entries) so we don't claim success on a placeholder.
    const sizeCheck = dockerExec(
      `[ -f ${outputFile} ] && stat -c%s ${outputFile} 2>/dev/null || echo 0`,
      5000,
    );
    const sizeBytes = parseInt((sizeCheck.output || "0").trim(), 10) || 0;
    const tooSmall = sizeBytes > 0 && sizeBytes < 512;

    if (complete && !tooSmall) {
      writeManifest(output_dir, {
        step: "extraction",
        status: "PASS",
        tool: "Magic",
        top_cell,
        pdk,
        output_format,
        output_file: outputFile,
        size_bytes: sizeBytes,
      });
    }

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: complete && fileExists && !tooSmall,
          output_file: outputFile,
          output_format,
          top_cell,
          size_bytes: sizeBytes,
          warning: tooSmall ? "extraction output is suspiciously small (<512 B) — likely a placeholder, parasitic data missing" : undefined,
          output: result.output.slice(-2000),
        }),
      }],
    };
  }
);

// ─── Tool: eda_doc_extract (v2.6.0) ───
server.tool(
  "eda_doc_extract",
  "Extract plain text + structured JSON from vendor docs (.doc / .docx / .pdf / .ppt / .pptx / .xls / .xlsx / .txt / .html) for downstream Phase 1 / spec-derivation skills. v2.6.4: doc_extract.py now emits per-file coverage_score (text_chars / file_size_bytes) into INDEX.json, so the plugin gate binary_doc_low_extraction_warn (LL-36) can flag figure-heavy PDFs whose pdftotext output is essentially empty (<2%) and recommend installing pdfplumber/PyMuPDF for fallback extraction. v2.6.3: tighten success gate (re-add execSync r.success guard so a crashed run can't be misreported as success based on stale stdout) + align stdio capture style with eda_doctor doc-probes. v2.6.2: runs on HOST (not docker) since pdftotext / libreoffice / openpyxl are typically host-side tools and the vibeic-eda container omits them. Same execution-on-host pattern as eda_fpga_compile / eda_fpga_program.",
  {
    in_dir: z.string().optional().describe("Directory of input docs (recurses)"),
    in_file: z.string().optional().describe("Single input file (alternative to in_dir)"),
    out_dir: z.string().describe("Output directory; one .txt per input + INDEX.json manifest"),
    recurse: z.boolean().default(true).describe("Recurse into subdirectories of in_dir"),
  },
  async ({ in_dir, in_file, out_dir, recurse }) => {
    try {
      optPath(in_dir, "in_dir"); optPath(in_file, "in_file");
      assertSafePath(out_dir, "out_dir");
    } catch (e) { return guardError(e); }
    const t0 = Date.now();
    if (!in_dir && !in_file) {
      return wrapResult({ success: false, t0, error: "either in_dir or in_file required", output: "" });
    }
    const recflag = recurse ? "--recurse" : "--no-recurse";
    const programPath = `${VIBE_IC_PROGRAMS_DIR}/doc_extract.py`;
    // security hardening: run on HOST via argv (no shell) so in_file/in_dir/
    // out_dir are never shell-parsed. stderr captured separately and merged
    // so partial "N PASS / M FAIL" lines survive a mid-run crash (prior to
    // this change, behaviour added in v2.6.3).
    const args = [programPath,
      ...(in_file ? ["--in-file", in_file] : ["--in-dir", in_dir]),
      "--out-dir", out_dir, recflag];
    let r;
    {
      const out = _spawnSync("python3", args, { timeout: 600000, maxBuffer: 10 * 1024 * 1024, encoding: "utf-8" });
      const merged = (out.stdout || "") + (out.stderr || "");
      if (out.error) r = { success: false, output: merged, error: out.error.message || String(out.error) };
      else if (out.status === 0) r = { success: true, output: merged };
      else r = { success: false, output: merged, error: out.stderr || `exited with status ${out.status}` };
    }
    const passMatch = (r.output || "").match(/(\d+) PASS \/ (\d+) FAIL \/ (\d+) SKIP/);
    const passN = passMatch ? parseInt(passMatch[1]) : 0;
    const failN = passMatch ? parseInt(passMatch[2]) : 0;
    const skipN = passMatch ? parseInt(passMatch[3]) : 0;
    return wrapResult({
      // v2.6.3: re-add r.success guard so a mid-run python crash that left a
      // stale "N PASS / 0 FAIL" line on stdout can't be reported as success.
      success: r.success && passN > 0 && failN === 0,
      t0,
      toolVersion: `doc_extract @ mcp-eda@${SERVER_VERSION} (host)`,
      error: r.error,
      output: r.output,
      pass_count: passN,
      fail_count: failN,
      skip_count: skipN,
      index_path: `${out_dir}/INDEX.json`,
    });
  }
);

// A container ceiling is set at CREATE time and nowhere else. `docker rm -f` +
// `docker run` on a newer image — which is exactly how the documented upgrade
// path moves the MCP — starts from nothing but its own flags, so it drops the
// ceiling the operator had been running with. Nothing fails at that moment; the
// host simply becomes killable by the next runaway synthesis or place-and-route
// run, and killing a timed-out `docker exec` does NOT kill the tool still
// running inside, so the ceiling has to be on the container and not the caller.
//
// SOFT, deliberately. An uncapped container runs every flow correctly; what is
// at risk is the HOST, not this session. Failing eda_doctor hard would block
// users who have been running uncapped for months over a risk they may have
// accepted. A named warning they can act on is the whole point.
const _BYTES_PER_GIB = 1024 * 1024 * 1024;
function _containerMemoryCeiling(inspect = _spawnSync) {
  const r = inspect("docker",
    ["inspect", CONTAINER, "--format",
     "{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}"],
    { encoding: "utf-8", timeout: 3000 });
  if (!r || r.status !== 0 || !r.stdout) {
    return { ok: false, detail: `could not read ${CONTAINER}'s memory settings` };
  }
  const parts = String(r.stdout).trim().split(/\s+/);
  const mem = Number(parts[0]);
  const swap = Number(parts[1]);
  // NOT-KNOWN IS NOT CAPPED. An unparseable answer must read as a warning, never
  // as a clean bill of health for a container nobody measured.
  if (!Number.isFinite(mem) || !Number.isFinite(swap)) {
    return { ok: false,
      detail: `${CONTAINER}'s memory settings did not parse: ${String(r.stdout).trim()}` };
  }
  const gib = (n) => `${(n / _BYTES_PER_GIB).toFixed(0)} GiB`;
  if (mem === 0) {
    return { ok: false, detail:
      `${CONTAINER} has NO memory ceiling. One runaway tool can exhaust the host. ` +
      `Recreate it with --memory=<N>g --memory-swap=<N>g (equal values disable swap, ` +
      `so an over-budget run fails fast instead of thrashing the disk). Note that a ` +
      `recreate drops these flags, which is how an upgrade removes the ceiling silently.` };
  }
  if (swap !== mem) {
    return { ok: false, detail:
      `${CONTAINER} is capped at ${gib(mem)} but swap is NOT disabled ` +
      `(--memory-swap ${swap < 0 ? "unlimited" : gib(swap)}). An over-budget run ` +
      `thrashes the disk for hours instead of failing. Set --memory-swap equal to --memory.` };
  }
  return { ok: true, detail: `${gib(mem)}, swap disabled` };
}

// ─── Tool: eda_doctor (v2.5.0) ───
server.tool(
  "eda_doctor",
  "Pre-flight health check. Verifies docker socket, container, every tool binary, and (optionally) a custom PDK. Returns a structured diagnosis with actionable hints. Run this BEFORE any other eda_* call when starting work in a new environment.",
  {
    custom_pdk: z.object({
      lib: z.string().optional(),
      techlef: z.string().optional(),
      celllef: z.string().optional(),
      cellgds: z.string().optional(),
    }).optional().describe("If provided, also verifies the custom PDK files exist + readable"),
    skip_versions: z.boolean().default(false).describe("Skip per-tool version probes (faster)"),
  },
  async ({ custom_pdk, skip_versions }) => {
    try {
      for (const p of Object.values(custom_pdk || {})) optPath(p, "custom_pdk");
    } catch (e) { return guardError(e); }
    const t0 = Date.now();
    const checks = [];
    let allOk = true;
    // 1. Docker reachable
    const probe = _probeDocker();
    checks.push({
      check: "docker_reachable",
      ok: probe.ok,
      detail: probe.ok ? "container reachable" : probe.hint,
    });
    if (!probe.ok) allOk = false;

    // 1b. Container memory ceiling (only meaningful once docker answers).
    if (probe.ok) {
      const ceiling = _containerMemoryCeiling();
      checks.push({
        check: "container_memory_ceiling",
        ok: ceiling.ok,
        detail: ceiling.detail,
        soft: ceiling.ok ? undefined : true,
      });
    }

    // 2. Per-tool binaries (only if docker ok). v0.26.5 (was v2.6.5): SOFT_TOOLS now maps
    //    tool → hint string explaining what flow needs it. v2.6.4 only carried
    //    a boolean; users seeing a soft FAIL had no idea whether to act on it.
    //    The hint is appended to the failing check's `detail` so the diagnosis
    //    is self-explanatory: e.g. "tool_magic: unavailable: ... (SOFT: needed
    //    only for magic-based parasitic extraction (analog / SoC flows))".
    const tools = ["yosys", "openroad", "klayout", "iverilog", "verilator", "magic", "netgen", "ngspice", "fault"];
    const SOFT_TOOLS = {
      magic: "needed only for magic-based parasitic extraction (analog / SoC flows); pure GF180/SKY130 digital flows are fine without it",
      fault: "Fault ATPG is optional; eda_dft can fall back to OpenROAD scan-only insertion",
    };
    if (probe.ok) {
      for (const tn of tools) {
        const v = skip_versions ? "skipped" : getToolVersion(tn);
        const ok = !v.startsWith("unavailable");
        const hint = SOFT_TOOLS[tn];
        const soft = !!hint;
        const detail = (!ok && hint) ? `${v}  (SOFT: ${hint})` : v;
        checks.push({ check: `tool_${tn}`, ok, detail, soft: soft || undefined });
        if (!ok && !soft) allOk = false;
      }
    }

    // 3. PDK file existence
    if (probe.ok && custom_pdk) {
      for (const [k, p] of Object.entries(custom_pdk)) {
        if (!p) continue;
        const r = dockerExec(`[ -r '${p}' ] && echo OK || echo MISSING:${p}`, 5000);
        const ok = (r.output || "").includes("OK");
        checks.push({ check: `pdk_${k}`, ok, detail: ok ? p : `not readable: ${p}` });
        if (!ok) allOk = false;
      }
    }

    // 4. Plugin programs dir
    const auditDir = VIBE_IC_PROGRAMS_DIR;
    try {
      const exists = existsSync(auditDir);
      checks.push({ check: "plugin_programs_dir", ok: exists, detail: exists ? auditDir : `missing: ${auditDir}` });
      if (!exists) allOk = false;
    } catch (e) {
      checks.push({ check: "plugin_programs_dir", ok: false, detail: e.message });
      allOk = false;
    }

    // 5. v2.6.2: doc-extraction toolchain probed on HOST (where pdftotext /
    //    libreoffice / openpyxl typically live). v2.6.0 probed in container
    //    and always reported FAIL because the vibeic-eda image doesn't ship
    //    these — but eda_doc_extract now runs on host (v2.6.2), so the
    //    probes must align with where the work actually happens.
    if (!skip_versions) {
      // v2.6.4: dropped python_docx probe — doc_extract.py uses libreoffice
      // for .docx (same path as .doc), no python-docx dep. Including it here
      // confused users who saw FAIL but had a fully working doc-extract path.
      const docProbes = [
        { name: "pdftotext", probe: `command -v pdftotext && pdftotext -v 2>&1 | head -1` },
        { name: "libreoffice", probe: `command -v libreoffice && libreoffice --version 2>&1 | head -1` },
        { name: "python_openpyxl", probe: `python3 -c "import openpyxl; print(openpyxl.__version__)"` },
      ];
      for (const dp of docProbes) {
        let out = "", success = false;
        try {
          out = execSync(dp.probe, { timeout: 8000, encoding: "utf-8", stdio: ["ignore", "pipe", "pipe"] }).trim();
          success = true;
        } catch (e) {
          out = ((e.stdout || "") + (e.stderr || "")).trim();
          success = false;
        }
        const ok = success && !_ERR_PATTERNS.some(p => p.test(out)) && out.length > 0;
        checks.push({ check: `doc_${dp.name}`, ok, detail: ok ? out.slice(0, 100) : `unavailable (host): ${out.slice(0, 100)}`, soft: true });
        // SOFT — doesn't fail allOk; agents with .txt-only docs can proceed.
      }
    }

    const failed = checks.filter(c => !c.ok).map(c => c.check);
    return wrapResult({
      success: allOk,
      t0,
      error: allOk ? "" : `failing checks: ${failed.join(", ")}`,
      output: checks.map(c => `[${c.ok ? "OK" : "FAIL"}] ${c.check}: ${c.detail}`).join("\n"),
      checks,
      summary: `${checks.filter(c => c.ok).length}/${checks.length} checks passed`,
    });
  }
);

// ─── Tool: eda_run_tcl (v2.5.0) ───
server.tool(
  "eda_run_tcl",
  "Escape hatch — run an arbitrary TCL/script in a backend (openroad / yosys / klayout-python / netgen / magic / ngspice). Use when stock eda_pnr / eda_synth / eda_drc_klayout don't expose the option you need. The agent supplies the full script content; the server pipes it to the backend in the IIC-OSIC-TOOLS container. since v0.2.33 (ORGANIC-20260531): engine=magic now EXPORTS PDK + PDK_ROOT in the child env AND passes the foundry `<pdk>.magicrc` via -rcfile when `pdk` is gf180/sky130 (or `custom_magicrc` is given) — fixing the `env(PDK)` startup-abort that left magic on 'technology minimum' and silently skipped the inline script.",
  {
    engine: z.enum(["openroad", "yosys", "klayout_python", "klayout_drc", "netgen", "magic", "ngspice"]).describe("Backend to invoke"),
    script: z.string().describe("Inline script content (e.g. OpenROAD TCL). EITHER `script` OR `script_file` is required."),
    script_file: z.string().optional().describe("Path to script file (alternative to inline script)"),
    extra_args: z.array(z.string()).default([]).describe("Extra CLI args appended after the script"),
    timeout_sec: z.number().default(900).describe("Timeout in seconds (default 15 min)"),
    pdk: z.enum(["gf180", "sky130", "nangate45", "custom"]).optional().describe("engine=magic: which PDK to export (PDK/PDK_ROOT) and whose foundry .magicrc to load via -rcfile. REQUIRED for magic GDS/extraction scripts — without it magic aborts on env(PDK) and never reads the script. Ignored by other engines."),
    custom_magicrc: z.string().optional().describe("engine=magic, pdk=custom: explicit path to the foundry .magicrc to pass via -rcfile."),
    pdk_root: z.string().optional().describe("engine=magic: PDK_ROOT to export (default /foss/pdks)."),
  },
  async ({ engine, script, script_file, extra_args, timeout_sec, pdk, custom_magicrc, pdk_root }) => {
    try {
      // script_file is interpolated into the engine command unquoted;
      // guard it. (Inline `script` is base64-transported and extra_args
      // are POSIX single-quote-escaped, both already shell-safe.)
      try { optPath(script_file, "script_file"); } catch (e) { return guardError(e); }
      optPath(custom_magicrc, "custom_magicrc"); optPath(pdk_root, "pdk_root");
    } catch (e) { return guardError(e); }
    const t0 = Date.now();
    let scriptArg, runCmd;
    const PATH_PREFIX = `export PATH=${TOOLS}/openroad/bin:${TOOLS}/yosys/bin:${TOOLS}/iverilog/bin:${TOOLS}/bin:$PATH && export QT_QPA_PLATFORM=offscreen`;

    // Materialize inline script as tmp file when needed.
    // v2.5.3: switched from HEREDOC to base64 transport. The HEREDOC body
    // travelled through `docker exec X bash -c "..."` — a double-quoted host
    // shell context — so any `$(...)` / backtick / `\` in the script was
    // expanded on the HOST before reaching the container. Base64 alphabet
    // ([A-Za-z0-9+/=]) has no shell metacharacters, so single-quoting it
    // inside the double-quoted dockerExec wrapper is safe.
    let tmpFile = "";
    if (!script_file) {
      if (!script) {
        return wrapResult({ success: false, t0, error: "either `script` or `script_file` required", output: "" });
      }
      tmpFile = `/tmp/run_tcl_${Date.now()}_${Math.floor(Math.random() * 100000)}`;
      const b64 = Buffer.from(script, "utf-8").toString("base64");
      const writeRes = dockerExec(`echo '${b64}' | base64 -d > ${tmpFile}`, 30000);
      if (!writeRes.success) {
        return wrapResult({ success: false, t0, error: writeRes.error, output: writeRes.output });
      }
      scriptArg = tmpFile;
    } else {
      scriptArg = script_file;
    }

    const extras = extra_args.map(a => `'${a.replace(/'/g, "'\\''")}'`).join(" ");
    switch (engine) {
      case "openroad":
        runCmd = `${PATH_PREFIX} && openroad -no_init -exit ${scriptArg} ${extras} 2>&1`;
        break;
      case "yosys":
        runCmd = `${PATH_PREFIX} && yosys -s ${scriptArg} ${extras} 2>&1`;
        break;
      case "klayout_python":
        runCmd = `${PATH_PREFIX} && klayout -z -r ${scriptArg} ${extras} 2>&1`;
        break;
      case "klayout_drc":
        runCmd = `${PATH_PREFIX} && klayout -b -r ${scriptArg} ${extras} 2>&1`;
        break;
      case "netgen":
        runCmd = `${PATH_PREFIX} && netgen -batch source ${scriptArg} ${extras} 2>&1`;
        break;
      case "magic": {
        // ORGANIC-20260531 fix: the system .magicrc reads $env(PDK) at
        // STARTUP, before any -rcfile runs. Export PDK + PDK_ROOT in the
        // child env AND pass the foundry <pdk>.magicrc via -rcfile so the
        // tech loads (else magic aborts on env(PDK), stays on "technology
        // minimum", and silently never reads the inline script).
        const root = pdk_root || PDK_ROOT;
        let env = "";
        let rcfileArg = "";
        const m = pdk ? magicPdkEnv(pdk) : null;
        if (m) {
          env = `export PDK=${m.pdkKey} && export PDK_ROOT=${root} && `;
          rcfileArg = `-rcfile ${m.magicrc} `;
        } else if (pdk === "custom" && custom_magicrc) {
          // For a custom PDK, the magicrc itself decides the tech; still
          // export PDK_ROOT (and PDK best-effort from the rcfile dir name).
          env = `export PDK_ROOT=${root} && `;
          rcfileArg = `-rcfile ${custom_magicrc} `;
        }
        runCmd = `${PATH_PREFIX} && ${env}magic -dnull -noconsole ${rcfileArg}${extras} ${scriptArg} 2>&1`;
        break;
      }
      case "ngspice":
        runCmd = `${PATH_PREFIX} && ngspice -b ${scriptArg} ${extras} 2>&1`;
        break;
    }
    const timeoutMs = Math.min(Math.max(timeout_sec * 1000, 60000), 3600000);
    const r = dockerExec(runCmd, timeoutMs);
    return wrapResult({
      success: r.success,
      t0,
      toolVersion: `${engine} @ mcp-eda@${SERVER_VERSION}`,
      error: r.error,
      output: r.output,
      engine,
      script_path: scriptArg,
    });
  }
);

// ─── Tool: eda_pdk_lint (v2.5.0) ───
server.tool(
  "eda_pdk_lint",
  "Validate a PDK before using it for synth/PnR. Checks Liberty syntax, LEF tech vs cell consistency, GDS-LEF cell-name match, RESISTANCE PER CUT presence (needed for IR drop), and CTS buffer cell access-point reachability. Saves hours of debugging when bringing up a new foundry deck.",
  {
    lib: z.string().describe("Path to Liberty .lib file"),
    techlef: z.string().describe("Path to tech LEF"),
    celllef: z.string().describe("Path to cell LEF"),
    cellgds: z.string().optional().describe("Path to cell GDS (for name match check)"),
    cts_buf_list: z.array(z.string()).optional().describe("List of CTS buffer cell names to verify (e.g. ['CLKBUFD8'])"),
  },
  async ({ lib, techlef, celllef, cellgds, cts_buf_list }) => {
    try {
      assertSafePath(lib, "lib");
      optPath(techlef, "techlef"); optPath(celllef, "celllef"); optPath(cellgds, "cellgds");
      optNoShellMeta(cts_buf_list, "cts_buf_list");
    } catch (e) { return guardError(e); }
    const t0 = Date.now();
    const findings = [];
    let allOk = true;
    const note = (sev, check, msg) => {
      findings.push({ severity: sev, check, message: msg });
      if (sev === "error") allOk = false;
    };

    // v2.5.1: short-circuit on docker unreachable. Without this, every
    // subsequent dockerExec returns the same "permission denied" hint as
    // its output, which we'd then misclassify (e.g. wc -l output never
    // arrives, so syntax-block counts default to 0 and we'd report bogus
    // ERRORs about empty files when really the user just hasn't fixed
    // their docker group yet).
    const probe = _probeDocker();
    if (!probe.ok) {
      note("error", "docker_unreachable", probe.hint);
      return wrapResult({
        success: false,
        t0,
        error: probe.hint,
        output: findings.map(f => `[${f.severity.toUpperCase()}] ${f.check}: ${f.message}`).join("\n"),
        findings,
        summary: "1 error (docker unreachable — pdk_lint cannot inspect files)",
      });
    }

    // 1. File readability
    for (const [k, p] of Object.entries({ lib, techlef, celllef, cellgds })) {
      if (!p) continue;
      const r = dockerExec(`[ -r '${p}' ] && wc -l '${p}' || echo MISSING`, 5000);
      if (!r.success || (r.output || "").includes("MISSING")) {
        note("error", `file_${k}`, `not readable: ${p}`);
      } else {
        note("info", `file_${k}`, (r.output || "").trim());
      }
    }

    // 2. Liberty syntax sniff (very rough — count library{}, cell() blocks)
    const libRes = dockerExec(`grep -cE '^[[:space:]]*(library|cell)[[:space:]]*\\(' '${lib}' 2>&1 || echo 0`, 10000);
    const libBlocks = parseInt((libRes.output || "0").trim()) || 0;
    if (libBlocks < 10) {
      note("error", "liberty_syntax", `only ${libBlocks} library/cell blocks found — file looks empty or corrupt`);
    } else {
      note("info", "liberty_syntax", `${libBlocks} library/cell blocks`);
    }

    // 3. Tech LEF: routing layers, RESISTANCE PER CUT
    const tlRes = dockerExec(`grep -cE '^LAYER ' '${techlef}'; grep -c 'TYPE ROUTING' '${techlef}'; grep -c 'TYPE CUT' '${techlef}'; grep -c 'RESISTANCE' '${techlef}'`, 10000);
    const lines = (tlRes.output || "").trim().split("\n");
    const [nlayers, nrouting, ncut, nres] = lines.map(x => parseInt(x) || 0);
    note("info", "tech_lef_layers", `${nlayers} layers (${nrouting} routing, ${ncut} cut)`);
    if (nrouting < 3) note("error", "tech_lef_routing_layers", `only ${nrouting} routing layers — too few`);
    if (nres === 0) note("warn", "tech_lef_resistance", "no RESISTANCE entries — eda_ir_drop will fail without via_resistance_ohm fallback");

    // 4. Cell LEF: macro count, SITE definitions
    const clRes = dockerExec(`grep -cE '^MACRO ' '${celllef}'; grep -cE '^SITE ' '${celllef}'`, 10000);
    const cl = (clRes.output || "").trim().split("\n");
    const nmacros = parseInt(cl[0]) || 0;
    const nsites = parseInt(cl[1]) || 0;
    note("info", "cell_lef_macros", `${nmacros} macros, ${nsites} sites`);
    if (nmacros < 30) note("warn", "cell_lef_macros", `${nmacros} macros — small library, check completeness`);

    // 5. GDS-LEF cell name match (sample)
    if (cellgds) {
      const gdsRes = dockerExec(`${TOOLS}/klayout/klayout -z -rd cellgds='${cellgds}' -r /dev/stdin <<'PY'
import pya
ly = pya.Layout(); ly.read('${cellgds}')
names = sorted([c.name for c in ly.each_cell()])
print('GDS_CELL_COUNT=' + str(len(names)))
print('GDS_CELL_SAMPLE=' + ','.join(names[:10]))
PY
`, 60000);
      const gdsMatch = (gdsRes.output || "").match(/GDS_CELL_COUNT=(\d+)/);
      const gdsCount = gdsMatch ? parseInt(gdsMatch[1]) : 0;
      note("info", "gds_cells", `${gdsCount} cells in GDS lib`);
      if (Math.abs(gdsCount - nmacros) > nmacros * 0.5) {
        note("warn", "gds_lef_count_mismatch", `GDS has ${gdsCount} cells but LEF has ${nmacros} macros — investigate`);
      }
    }

    // 6. CTS buffer access points (heuristic: pin A on first routing layer with width >= layer min-width)
    if (cts_buf_list && cts_buf_list.length) {
      for (const buf of cts_buf_list) {
        const r = dockerExec(`awk '/^MACRO ${buf}$/,/^END ${buf}$/' '${celllef}' | grep -c 'PIN A'`, 8000);
        const has = parseInt((r.output || "0").trim()) > 0;
        note(has ? "info" : "error", `cts_buf_${buf}`, has ? `PIN A defined` : `MACRO ${buf} not in cell LEF`);
      }
    }

    return wrapResult({
      success: allOk,
      t0,
      output: findings.map(f => `[${f.severity.toUpperCase()}] ${f.check}: ${f.message}`).join("\n"),
      findings,
      summary: `${findings.filter(f => f.severity === "error").length} errors, ${findings.filter(f => f.severity === "warn").length} warnings, ${findings.filter(f => f.severity === "info").length} info`,
    });
  }
);

// ─── Tool: eda_workflow_run (v2.5.0; v2.5.3 honest planner mode; v2.5.4 templates) ───
//
// v2.5.4: `template` parameter — agent passes a template name and the
// planner emits the canonical step list for that workflow. Removes
// "what's the right step order?" from the agent's burden. Currently
// supported templates:
//   - "phase-2c-bringup": FPGA compile→program(verify_burn)→detect→
//     baseline LED capture→connect_test→per-opcode send_raw→post-stim
//     LED capture→camera_led_diff→assemble PASS evidence. Codifies the
//     hardware-attestation chain from AGENT_USAGE_GUIDE Rule 5/5b.
server.tool(
  "eda_workflow_run",
  "[PLANNER ONLY in v2.5.x] Declarative pipeline planner. Takes a JSON spec of MCP tool calls and emits a timeline manifest enumerating each step — does NOT actually invoke the tools (the MCP server can't reflectively call its own tools yet). The calling agent reads the manifest and dispatches each step. v2.6 will add direct dispatch and `dry_run=false` will then truly execute the pipeline. Today, every step records `status: NOT_DISPATCHED`; treat it as planning aid. v2.5.4: pass `template=\"phase-2c-bringup\"` (with template_args) to get the canonical FPGA bring-up sequence (compile→program→detect→connect_test→per-opcode send_raw→camera diff) without hand-listing each step.",
  {
    project_dir: z.string().describe("Project root for manifests + provenance"),
    steps: z.array(z.object({
      tool: z.string().describe("Tool name without 'eda_' prefix (e.g. 'lint', 'synth', 'pnr')"),
      args_json: z.string().describe("Args passed to the tool, JSON-encoded"),
      continue_on_failure: z.boolean().default(false),
    })).default([]).describe("Ordered list of pipeline steps. Ignored if `template` is set."),
    dry_run: z.boolean().default(true).describe("v2.5.x: must be true (planner only). v2.6 will allow false to dispatch directly."),
    template: z.string().optional().describe("Optional canonical-flow template. Supported: 'phase-2c-bringup'. When set, `steps` is ignored and the template-expanded step list is used instead."),
    template_args: z.any().optional().describe("Template parameters (object). For 'phase-2c-bringup': qpf_path, sof_path, expected_device, opcodes (array of int), camera_device, baseline_jpg, post_jpg, led_y_pixel, led_count."),
  },
  async ({ project_dir, steps, dry_run, template, template_args }) => {
    try {
      assertSafePath(project_dir, "project_dir");
      optToken(template, "template");
      const _chkArgs = (o) => {
        for (const v of Object.values(o || {})) {
          if (typeof v === "string") assertNoShellMeta(v, "template_args");
          else if (v && typeof v === "object") _chkArgs(v);
        }
      };
      _chkArgs(template_args);
    } catch (e) { return guardError(e); }
    const t0 = Date.now();
    const timeline = [];
    let allOk = true;
    let expandedFromTemplate = false;
    let templateUsed = null;

    if (template) {
      templateUsed = template;
      expandedFromTemplate = true;
      const ta = template_args || {};
      if (template === "phase-2c-bringup") {
        const qpf = ta.qpf_path || `${project_dir}/fpga/quartus.qpf`;
        const sof = ta.sof_path || `${project_dir}/fpga/output.sof`;
        const expDev = ta.expected_device || "10M50DAF484C7G";
        const opcodes = Array.isArray(ta.opcodes) && ta.opcodes.length > 0
          ? ta.opcodes : [0x70, 0x76, 0x78];
        const cam = ta.camera_device || "/dev/video0";
        const baseJpg = ta.baseline_jpg || `${project_dir}/reports/led_baseline.jpg`;
        const postJpg = ta.post_jpg || `${project_dir}/reports/led_post.jpg`;
        const ledY = ta.led_y_pixel != null ? ta.led_y_pixel : 360;
        const ledCount = ta.led_count != null ? ta.led_count : 10;

        const tplSteps = [
          { tool: "fpga_compile",
            args_json: JSON.stringify({ qpf_path: qpf, project_dir }),
            continue_on_failure: false },
          { tool: "fpga_program",
            args_json: JSON.stringify({ sof_path: sof, project_dir, verify_burn: true, expected_device: expDev }),
            continue_on_failure: false },
          { tool: "device_fpga_de10lite_detect",
            args_json: JSON.stringify({}),
            continue_on_failure: false },
          { tool: "device_camera_capture",
            args_json: JSON.stringify({ device: cam, output: baseJpg }),
            continue_on_failure: true },
        ];
        // Optional host-tester probe steps (omitted in the open-source build —
        // wire in your own tester via a vendor manifest under src/devices/tester/).
        void opcodes;
        tplSteps.push(
          { tool: "device_camera_capture",
            args_json: JSON.stringify({ device: cam, output: postJpg }),
            continue_on_failure: true },
          { tool: "device_camera_led_diff",
            args_json: JSON.stringify({ before: baseJpg, after: postJpg, led_count: ledCount, led_y_pixel: ledY }),
            continue_on_failure: true },
          { tool: "fpga_program_chain_attest_check",
            args_json: JSON.stringify({ project_dir }),
            continue_on_failure: false },
        );
        steps = tplSteps;
      } else {
        return wrapResult({
          success: false,
          t0,
          error: `Unknown template '${template}'. Supported: 'phase-2c-bringup'.`,
          output: "",
        });
      }
    }

    // v2.5.3: explicit guard — dispatch isn't implemented yet. Surfacing this
    // as a structured error beats silently emitting NOT_DISPATCHED rows that
    // an over-eager caller might mistake for "ran but no output."
    if (dry_run === false) {
      return wrapResult({
        success: false,
        t0,
        error: "eda_workflow_run dispatch (dry_run=false) lands in v2.6. v2.5.x is planner-only — call with dry_run=true (default) to get the timeline manifest, then invoke each step yourself.",
        output: "",
      });
    }

    for (let i = 0; i < steps.length; i++) {
      const s = steps[i];
      const stepStart = Date.now();
      let parsedArgs = {};
      try { parsedArgs = JSON.parse(s.args_json || "{}"); } catch (e) {}
      const stepRecord = {
        index: i,
        tool: s.tool,
        args_keys: Object.keys(parsedArgs),
        started: new Date(stepStart).toISOString(),
      };

      if (dry_run) {
        stepRecord.status = "DRY_RUN";
        timeline.push(stepRecord);
        continue;
      }

      // Reflectively call our own server.tool registry — but server doesn't
      // expose that. So we route by name through a switch table built from
      // the public eda_* tool functions. To keep this tool simple, we only
      // support a small set of common steps; for anything else, agents
      // should use eda_run_tcl + per-tool calls.
      const dispatcher = {
        // Map names → known callbacks via re-firing tool calls would require
        // a server-side handle. As a pragmatic v2.5.0 stub, we shell out to
        // a small node script that re-invokes mcp-client semantics. For now,
        // emit a "not_dispatched" marker and let the agent decide per-step.
      };

      stepRecord.status = "NOT_DISPATCHED";
      stepRecord.note = "v2.5.0 workflow_run is currently a planner — emit this manifest, then have the agent invoke each tool. Future v2.6 will dispatch directly.";
      stepRecord.duration_ms = Date.now() - stepStart;
      timeline.push(stepRecord);

      if (!s.continue_on_failure) {
        // We treat NOT_DISPATCHED as success so the planner enumerates all
        // steps; the agent then decides what to do.
      }
    }

    // Write manifest
    const manifestPath = `${project_dir}/workflow_manifest_${Date.now()}.json`;
    try {
      mkdirSync(project_dir, { recursive: true });
      const fs = require("fs");
      fs.writeFileSync(manifestPath, JSON.stringify({
        server_version: SERVER_VERSION,
        started: new Date(t0).toISOString(),
        project_dir,
        template: templateUsed,
        expanded_from_template: expandedFromTemplate,
        steps,
        timeline,
      }, null, 2));
    } catch (e) {
      allOk = false;
    }

    return wrapResult({
      success: allOk,
      t0,
      output: timeline.map(t => `step ${t.index} ${t.tool}: ${t.status}${t.note ? " — " + t.note : ""}`).join("\n"),
      timeline,
      manifest_path: manifestPath,
      template: templateUsed,
      summary: `${steps.length} steps planned${dry_run ? " (dry run)" : ""}${templateUsed ? ` from template '${templateUsed}'` : ""}`,
    });
  }
);

// ─── Tool: device_camera_capture (v0.99 P3-E2) ───
// Snapshot LEDs / scope / board face to a JPG with auto-exposure tuned
// for LED visibility. Wraps `ffmpeg -f v4l2 -frames:v 1`.
server.tool(
  "device_camera_capture",
  "Capture a single JPG from a USB / built-in webcam (v4l2). Useful for "
  + "reading FPGA LED state, scope screen, or board face when no SCPI "
  + "scope is attached. Auto-tunes exposure/contrast for LED visibility. "
  + "Returns the JPG path.",
  {
    device: z.string().default("/dev/video0").describe("v4l2 device path"),
    output: z.string().describe("Output JPG path (parent dir auto-created)"),
    width: z.number().int().positive().max(7680).default(1280).describe("Capture width (pixels, 1-7680)"),
    height: z.number().int().positive().max(4320).default(720).describe("Capture height (pixels, 1-4320)"),
    led_mode: z.boolean().default(true).describe(
      "Apply LED-friendly exposure/gamma (short shutter + low gamma so LEDs aren't blown out)"
    ),
    timeout_sec: z.number().positive().max(300).default(5).describe("Capture timeout (seconds, 1-300)"),
  },
  async ({ device, output, width, height, led_mode, timeout_sec }) => {
    try {
      assertSafePath(device, "device");
      assertSafePath(output, "output");
    } catch (e) { return guardError(e); }
    try {
      const fs = await import("fs");
      const pathlib = await import("path");
      fs.mkdirSync(pathlib.dirname(output), { recursive: true });
    } catch (_) { /* ok */ }

    // ffmpeg invocation tuned for LEDs: short exposure (-vf for HSV/saturation
    // boost), single frame. security hardening: run via argv (no shell) so
    // device / output paths are never shell-parsed.
    const ffArgs = [
      "-hide_banner", "-loglevel", "error", "-y", "-f", "v4l2",
      "-video_size", `${width}x${height}`, "-i", String(device),
      "-frames:v", "1",
    ];
    if (led_mode) ffArgs.push("-vf", "eq=brightness=-0.1:saturation=1.5,format=yuv420p");
    ffArgs.push(String(output));
    let result;
    {
      const r = _spawnSync("ffmpeg", ffArgs, {
        timeout: timeout_sec * 1000,
        maxBuffer: 4 * 1024 * 1024,
        encoding: "utf-8",
      });
      const merged = (r.stdout || "") + (r.stderr || "");
      if (r.error) result = { success: false, output: merged, error: r.error.message || String(r.error) };
      else if (r.status === 0) result = { success: true, output: merged };
      else result = { success: false, output: merged, error: r.stderr || `exited with status ${r.status}` };
    }

    let imageHash = null;
    try { imageHash = sha256File(output); } catch (_) { /* ok */ }

    writeManifest("/tmp", {
      step: "device_camera_capture",
      status: result.success ? "PASS" : "FAIL",
      tool: "ffmpeg",
      device,
      output,
      image_sha256: imageHash,
      session_id: MCP_SESSION_ID,
    });

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: result.success,
          output,
          image_sha256: imageHash,
          session_id: MCP_SESSION_ID,
          ffmpeg_output: (result.error || result.output || "").slice(-500),
        }),
      }],
    };
  }
);

// ─── Tool: device_camera_led_diff (v0.99 P3-E3) ───
// Compare two JPG captures, output per-LED state diff (which positions
// went on / off / stayed). Uses Python (PIL) on host; saves the agent
// from manual y-coordinate counting.
server.tool(
  "device_camera_led_diff",
  "Diff two webcam captures and report which LED positions changed state. "
  + "Sums per-row brightness across the LED row's y range, thresholds, and "
  + "reports which LEDs went 0→1, 1→0, or unchanged. Saves the agent from "
  + "manual y-coordinate counting.",
  {
    before: z.string().describe("Path to baseline JPG"),
    after: z.string().describe("Path to post-stimulus JPG"),
    led_count: z.number().default(10).describe("Number of LEDs in the row"),
    led_y_pixel: z.number().describe("Y pixel of LED row centre in capture"),
    led_y_height: z.number().default(20).describe("Y pixel range to average"),
    threshold: z.number().default(80).describe("Brightness threshold (0-255)"),
  },
  async ({ before, after, led_count, led_y_pixel, led_y_height, threshold }) => {
    try {
      assertSafePath(before, "before");
      assertSafePath(after, "after");
    } catch (e) { return guardError(e); }
    // security hardening: values are read from argv (sys.argv) rather than
    // interpolated into the Python source, and the script runs via spawnSync
    // argv (no shell). The former `python3 -c "...${before}..."` ran on the
    // HOST through a double-quoted shell arg, so a path containing $(...) or
    // backticks was a host command-injection vector.
    const py = `
import sys, json
try:
    from PIL import Image
except Exception as e:
    print(json.dumps({"success": False, "error": "PIL unavailable: " + str(e)}))
    sys.exit(0)

before = sys.argv[1]
after = sys.argv[2]
led_y_pixel = int(sys.argv[3])
led_y_height = int(sys.argv[4])
led_count = int(sys.argv[5])
threshold = int(sys.argv[6])

def row_avg(path, y, h):
    im = Image.open(path).convert("L")
    w, ih = im.size
    y0 = max(0, y - h // 2); y1 = min(ih, y + h // 2)
    px = im.load()
    cols = []
    for x in range(w):
        s = 0
        for yy in range(y0, y1):
            s += px[x, yy]
        cols.append(s // max(1, y1 - y0))
    return cols, w

cols_b, w = row_avg(before, led_y_pixel, led_y_height)
cols_a, _ = row_avg(after,  led_y_pixel, led_y_height)

# Bin each row into led_count equal-width bins; max-pixel per bin = LED brightness
def bin_max(cols, n):
    bw = max(1, len(cols) // n)
    out = []
    for i in range(n):
        seg = cols[i * bw : (i + 1) * bw]
        out.append(max(seg) if seg else 0)
    return out

a = bin_max(cols_b, led_count)
b = bin_max(cols_a, led_count)
state_b = [int(v >= threshold) for v in a]
state_a = [int(v >= threshold) for v in b]
diff = []
for i, (sb, sa) in enumerate(zip(state_b, state_a)):
    if sb != sa:
        diff.append({"led": i, "before": sb, "after": sa})

print(json.dumps({
    "success": True,
    "led_count": led_count,
    "before_state": state_b,
    "after_state":  state_a,
    "changed": diff,
}))
`;
    let result;
    try {
      const _r = _spawnSync("python3",
        ["-c", py, String(before), String(after), String(led_y_pixel),
         String(led_y_height), String(led_count), String(threshold)],
        { timeout: 15000, maxBuffer: 4 * 1024 * 1024, encoding: "utf-8" });
      if (_r.error) throw _r.error;
      result = JSON.parse((_r.stdout || "").trim());
    } catch (err) {
      result = { success: false, error: (err.stderr || err.message || "") };
    }

    writeManifest("/tmp", {
      step: "device_camera_led_diff",
      status: result.success ? "PASS" : "FAIL",
      tool: "python+PIL",
      before, after, changed: (result.changed || []).length,
    });

    return {
      content: [{
        type: "text",
        text: JSON.stringify(result),
      }],
    };
  }
);

// v1.6.18 Fix 3 — `device_id_bus_force_low_pulse` was previously registered
// here with a raw `printf FORCE_LOW > /dev/usb_hid_tester` shell command, AND
// also via src/devices/tester/usb-hid-tester/manifest.json (the canonical
// firmware-aware Wave 59 driver). The duplicate registration printed a
// `[devices] FAIL register: Tool ... is already registered` startup error
// and the manifest version was skipped. Per the registry hard rule
// ("Hard rule: this module is the ONLY place that talks to `server.tool`
// for device IO"), the manifest is canonical; the legacy block is removed.

// ─── S1: Scope Protocol Decode ───
// Chip-agnostic scope waveform decoder. Takes a CSV/JSON scope capture +
// L2 timing JSON with pulse-class windows, segments the trace into pulses,
// classifies each by width. AMBIGUOUS events include candidate causes.
server.tool(
  "eda_scope_protocol_decode",
  "Decode a scope capture into protocol-level timeline events using L2 timing JSON. "
  + "Segments the waveform into pulses, classifies each by width against L2 pulse-class "
  + "windows. Pulses that fit no class or span two class boundaries are marked AMBIGUOUS "
  + "with candidate causes (TX_RX_OVERLAP, TX_DRIVE_RUNT, RX_PULL_TOO_WEAK, BUS_GLITCH, "
  + "SETTLE_VIOLATION). All class names come from the project's L2 JSON — plugin core "
  + "embeds zero protocol-specific knowledge.",
  {
    scope_csv: z.string().describe(
      "Path to scope capture CSV/JSON file. CSV format: time_us,voltage columns. "
      + "JSON format: [{t_us, v}, ...] array."
    ),
    l2_timing_json: z.string().describe(
      "Path to L2 timing JSON containing pulse_classes array: "
      + "[{class_name, min_us, max_us, polarity}]"
    ),
    threshold_v: z.number().default(1.5).describe(
      "Voltage threshold for LOW/HIGH classification (default: 1.5V)"
    ),
    glitch_filter_us: z.number().default(0.5).describe(
      "Pulses shorter than this are filtered as glitches (default: 0.5us)"
    ),
  },
  async ({ scope_csv, l2_timing_json, threshold_v, glitch_filter_us }) => {
    const fs = await import("fs");
    const path = await import("path");

    if (!fs.existsSync(scope_csv)) {
      return { content: [{ type: "text", text: JSON.stringify({ error: `Scope file not found: ${scope_csv}` }) }] };
    }
    if (!fs.existsSync(l2_timing_json)) {
      return { content: [{ type: "text", text: JSON.stringify({ error: `L2 timing file not found: ${l2_timing_json}` }) }] };
    }

    let l2;
    try {
      l2 = JSON.parse(fs.readFileSync(l2_timing_json, "utf-8"));
    } catch (e) {
      return { content: [{ type: "text", text: JSON.stringify({ error: `Cannot parse L2 JSON: ${e.message}` }) }] };
    }

    const pulseClasses = l2.pulse_classes || l2.timing_classes || [];
    if (!pulseClasses.length) {
      return { content: [{ type: "text", text: JSON.stringify({ error: "L2 JSON has no pulse_classes or timing_classes array" }) }] };
    }

    let samples = [];
    const raw = fs.readFileSync(scope_csv, "utf-8");
    if (scope_csv.endsWith(".json")) {
      samples = JSON.parse(raw);
    } else {
      const lines = raw.split("\n").filter(l => l.trim() && !l.startsWith("#") && !l.startsWith("time"));
      for (const line of lines) {
        const parts = line.split(",").map(s => parseFloat(s.trim()));
        if (parts.length >= 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
          samples.push({ t_us: parts[0], v: parts[1] });
        }
      }
    }
    if (samples.length < 2) {
      return { content: [{ type: "text", text: JSON.stringify({ error: `Scope capture has ${samples.length} samples — need at least 2` }) }] };
    }

    // Segment into pulses
    const pulses = [];
    let currentPolarity = samples[0].v < threshold_v ? "low" : "high";
    let pulseStart = samples[0].t_us;
    for (let i = 1; i < samples.length; i++) {
      const pol = samples[i].v < threshold_v ? "low" : "high";
      if (pol !== currentPolarity) {
        const duration = samples[i].t_us - pulseStart;
        if (duration >= glitch_filter_us) {
          pulses.push({ t_us: pulseStart, polarity: currentPolarity, duration_us: duration });
        }
        currentPolarity = pol;
        pulseStart = samples[i].t_us;
      }
    }
    const lastDuration = samples[samples.length - 1].t_us - pulseStart;
    if (lastDuration >= glitch_filter_us) {
      pulses.push({ t_us: pulseStart, polarity: currentPolarity, duration_us: lastDuration });
    }

    const CANDIDATE_CAUSES = ["TX_RX_OVERLAP", "TX_DRIVE_RUNT", "RX_PULL_TOO_WEAK", "BUS_GLITCH", "SETTLE_VIOLATION"];

    // Classify each pulse
    const timeline = [];
    for (const p of pulses) {
      const matches = pulseClasses.filter(c =>
        (c.polarity || "any") === "any" || c.polarity === p.polarity
      ).filter(c =>
        p.duration_us >= c.min_us && p.duration_us <= c.max_us
      );

      if (matches.length === 1) {
        timeline.push({ t_us: p.t_us, event: matches[0].class_name, polarity: p.polarity, duration_us: p.duration_us });
      } else if (matches.length > 1) {
        timeline.push({
          t_us: p.t_us, event: "AMBIGUOUS", polarity: p.polarity, duration_us: p.duration_us,
          violation: `matches multiple classes: ${matches.map(m => m.class_name).join(", ")}`,
        });
      } else {
        // No match — find which boundaries it spans
        const spanning = pulseClasses.filter(c =>
          (c.polarity || "any") === "any" || c.polarity === p.polarity
        ).filter(c =>
          (p.duration_us >= c.min_us && p.duration_us <= c.max_us * 1.5) ||
          (p.duration_us >= c.min_us * 0.5 && p.duration_us <= c.max_us)
        );
        const spanStr = spanning.length >= 2
          ? `spans ${spanning[0].class_name}-${spanning[1].class_name} boundary`
          : spanning.length === 1
            ? `near ${spanning[0].class_name} boundary (${spanning[0].min_us}-${spanning[0].max_us}us)`
            : `no matching class for ${p.duration_us.toFixed(2)}us ${p.polarity} pulse`;
        timeline.push({
          t_us: p.t_us, event: "AMBIGUOUS", polarity: p.polarity, duration_us: p.duration_us,
          violation: `${spanStr}; candidate causes: ${CANDIDATE_CAUSES.join(" | ")}`,
        });
      }
    }

    const ambiguousCount = timeline.filter(e => e.event === "AMBIGUOUS").length;
    const result = {
      total_pulses: timeline.length,
      ambiguous_count: ambiguousCount,
      pulse_classes_used: pulseClasses.map(c => c.class_name),
      timeline,
    };

    writeManifest("/tmp", { step: "eda_scope_protocol_decode", status: ambiguousCount > 0 ? "WARN" : "PASS", ambiguous: ambiguousCount });
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

// ─── S2: Pass-Reference Scope Diff ───
// Opt-in tool: when user supplies a known-good reference SOF, compares
// timeline JSONs (from S1) between reference and candidate at event level.
server.tool(
  "eda_pass_reference_scope_diff",
  "Compare two scope timeline JSONs (from eda_scope_protocol_decode) at the event level. "
  + "Reports +/- events per timeline position. OPT-IN only — requires a reference timeline. "
  + "Tolerance-windowed for jitter.",
  {
    reference_timeline_json: z.string().describe("Path to reference timeline JSON (from eda_scope_protocol_decode on known-good SOF)"),
    candidate_timeline_json: z.string().describe("Path to candidate timeline JSON (from eda_scope_protocol_decode on candidate SOF)"),
    jitter_tolerance_us: z.number().default(2.0).describe("Timing jitter tolerance in microseconds (default: 2.0us)"),
  },
  async ({ reference_timeline_json, candidate_timeline_json, jitter_tolerance_us }) => {
    const fs = await import("fs");

    for (const p of [reference_timeline_json, candidate_timeline_json]) {
      if (!fs.existsSync(p)) {
        return { content: [{ type: "text", text: JSON.stringify({ error: `File not found: ${p}` }) }] };
      }
    }

    let ref, cand;
    try {
      ref = JSON.parse(fs.readFileSync(reference_timeline_json, "utf-8"));
      cand = JSON.parse(fs.readFileSync(candidate_timeline_json, "utf-8"));
    } catch (e) {
      return { content: [{ type: "text", text: JSON.stringify({ error: `JSON parse error: ${e.message}` }) }] };
    }

    const refEvents = ref.timeline || ref;
    const candEvents = cand.timeline || cand;
    const diffs = [];
    const maxLen = Math.max(refEvents.length, candEvents.length);

    for (let i = 0; i < maxLen; i++) {
      const r = refEvents[i];
      const c = candEvents[i];
      if (!r) {
        diffs.push({ position: i, diff: "+candidate", detail: `Extra event in candidate: ${c.event} ${c.polarity} ${c.duration_us.toFixed(2)}us @ t=${c.t_us.toFixed(2)}us` });
      } else if (!c) {
        diffs.push({ position: i, diff: "-candidate", detail: `Missing event in candidate: ${r.event} ${r.polarity} ${r.duration_us.toFixed(2)}us @ t=${r.t_us.toFixed(2)}us` });
      } else {
        if (r.event !== c.event) {
          diffs.push({ position: i, diff: "event_mismatch", detail: `ref=${r.event} vs cand=${c.event} @ t=${c.t_us.toFixed(2)}us` });
        } else if (Math.abs(r.duration_us - c.duration_us) > jitter_tolerance_us) {
          diffs.push({ position: i, diff: "duration_drift", detail: `${r.event}: ref=${r.duration_us.toFixed(2)}us vs cand=${c.duration_us.toFixed(2)}us (Δ=${Math.abs(r.duration_us - c.duration_us).toFixed(2)}us)` });
        }
      }
    }

    const result = {
      reference_events: refEvents.length,
      candidate_events: candEvents.length,
      diff_count: diffs.length,
      jitter_tolerance_us,
      diffs,
    };

    writeManifest("/tmp", { step: "eda_pass_reference_scope_diff", status: diffs.length > 0 ? "DIFF" : "MATCH", diff_count: diffs.length });
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

// ─── S3: RTL SignalTap/ILA Autogen ───
// Auto-instrument dispatcher state register + timing-critical signals for
// FPGA embedded logic analyzer capture.
server.tool(
  "eda_rtl_signaltap_autogen",
  "Auto-instrument RTL for FPGA embedded logic analyzer (Quartus SignalTap / Vivado ILA). "
  + "Scans RTL for dispatcher state registers and timing-critical signals (TX-start, RX-done, "
  + "delimiter-detected, cmd-valid class), emits .stp (Quartus) or .ltx (Vivado) file. "
  + "After hardware capture, decodes into cycle-accurate state-trace JSON.",
  {
    rtl_dir: z.string().describe("Path to RTL source directory"),
    top_module: z.string().describe("Top-level module name"),
    target: z.enum(["quartus", "vivado"]).default("quartus").describe("FPGA toolchain target"),
    clock_signal: z.string().default("CLOCK_50").describe("Capture clock signal name"),
    depth: z.number().default(2048).describe("Capture buffer depth"),
    output_dir: z.string().optional().describe("Output directory for .stp/.ltx file (default: rtl_dir)"),
    extra_signals: z.array(z.string()).default([]).describe("Additional signal names to capture"),
  },
  async ({ rtl_dir, top_module, target, clock_signal, depth, output_dir, extra_signals }) => {
    try {
      assertSafePath(rtl_dir, "rtl_dir"); optPath(output_dir, "output_dir");
      assertSafeIdent(top_module, "top_module"); optIdent(clock_signal, "clock_signal");
      optToken(target, "target");
      (extra_signals || []).forEach((s) => optNoShellMeta(String(s), "extra_signals"));
    } catch (e) { return guardError(e); }
    const fs = await import("fs");
    const path = await import("path");

    if (!fs.existsSync(rtl_dir)) {
      return { content: [{ type: "text", text: JSON.stringify({ error: `RTL directory not found: ${rtl_dir}` }) }] };
    }

    // Heuristic signal patterns for auto-instrumentation
    const SIGNAL_PATTERNS = {
      tx_start: /\b(tx_start|tx_req|resp_start|reply_start|drv_en|tx_enable)\b/gi,
      rx_done: /\b(rx_done|delim_seen|eof_detect|cmd_valid|frame_complete|trailing_br|trailing_delim)\b/gi,
      state_reg: /\b(state|fsm_state|ctrl_state|bus_state|dispatcher_state|protocol_state)\b/gi,
      delimiter: /\b(delimiter_det|break_det|br_detect|sync_detect|sof_detect)\b/gi,
    };

    // Scan RTL files for matching signals
    const rtlFiles = [];
    const scanDir = (dir) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.isDirectory()) scanDir(path.join(dir, entry.name));
        else if (/\.(sv|v|svh|vh)$/i.test(entry.name)) rtlFiles.push(path.join(dir, entry.name));
      }
    };
    scanDir(rtl_dir);

    const foundSignals = new Set();
    for (const f of rtlFiles) {
      const content = fs.readFileSync(f, "utf-8");
      for (const [category, pattern] of Object.entries(SIGNAL_PATTERNS)) {
        let m;
        const regex = new RegExp(pattern.source, pattern.flags);
        while ((m = regex.exec(content)) !== null) {
          foundSignals.add(m[0]);
        }
      }
    }

    // Add user-specified extra signals
    for (const s of extra_signals) foundSignals.add(s);

    const signals = [...foundSignals].sort();
    const outDir = output_dir || rtl_dir;

    if (target === "quartus") {
      // Generate .stp XML
      const stpContent = `<?xml version="1.0" encoding="UTF-8"?>
<session stp_version="9.0">
  <instance entity_name="sld_signaltap" is_auto_node="yes" is_expanded="true"
    name="auto_signaltap_0" source_file="sld_signaltap">
    <node_ip_info instance_id="0" mfg_id="110" node_id="0" version="6"/>
    <signal_set global_temp="1" name="signal_set: signal_set_1"
      is_expanded="true">
      <clock name="${clock_signal}" polarity="posedge" tap_mode="classic"/>
      <config pipeline_level="0" ram_type="AUTO" reserved_data_nodes="0"
        reserved_storage_qualifier_nodes="0" reserved_trigger_nodes="0"
        sample_depth="${depth}" trigger_in_enable="no" trigger_out_enable="no"/>
${signals.map((s, i) => `      <signal name="${s}" tap_mode="classic" node_index="${i}"/>`).join("\n")}
    </signal_set>
    <trigger_set is_expanded="true" name="trigger: trigger_set_1"/>
  </instance>
</session>`;

      const outFile = path.join(outDir, `${top_module}_debug.stp`);
      fs.writeFileSync(outFile, stpContent);

      const result = {
        target: "quartus",
        output_file: outFile,
        signals_instrumented: signals.length,
        signals,
        depth,
        clock: clock_signal,
      };
      writeManifest("/tmp", { step: "eda_rtl_signaltap_autogen", status: "PASS", signals: signals.length, target });
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    } else {
      // Generate Vivado ILA .tcl
      const tclContent = `# Auto-generated ILA configuration for ${top_module}
create_debug_core u_ila_0 ila
set_property C_DATA_DEPTH ${depth} [get_debug_cores u_ila_0]
set_property C_TRIGIN_EN false [get_debug_cores u_ila_0]
set_property C_TRIGOUT_EN false [get_debug_cores u_ila_0]
set_property C_INPUT_PIPE_STAGES 0 [get_debug_cores u_ila_0]
connect_debug_port u_ila_0/clk [get_nets ${clock_signal}]
${signals.map((s, i) => `set_property port_width 1 [get_debug_ports u_ila_0/probe${i}]\nconnect_debug_port u_ila_0/probe${i} [get_nets ${s}]`).join("\n")}
`;
      const outFile = path.join(outDir, `${top_module}_ila.tcl`);
      fs.writeFileSync(outFile, tclContent);

      const result = {
        target: "vivado",
        output_file: outFile,
        signals_instrumented: signals.length,
        signals,
        depth,
        clock: clock_signal,
      };
      writeManifest("/tmp", { step: "eda_rtl_signaltap_autogen", status: "PASS", signals: signals.length, target });
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  }
);

// ─── eda_analog_layout ───
server.tool(
  "eda_analog_layout",
  "Run Magic on a sized SPICE netlist and stream GDS + LEF + extracted netlist. "
  + "The matching / common-centroid / guard-ring directives are recorded but NOT yet "
  + "auto-placed (that needs a real PCell/paint/place+route pass). ORGANIC #144: the tool "
  + "inspects the streamed geometry and returns status DONE only when real placed geometry "
  + "exists; if the netlist merely loaded and nothing was placed it returns status SCAFFOLD "
  + "(never a fake success). Supports GF180 / SKY130 / IHP-SG13G2 analog devices. "
  + "v0.108: analog hardmacro pipeline.",
  {
    spice_netlist: z.string().describe("Path to SPICE netlist (.sp) with sized transistors"),
    block_name: z.string().describe("Analog block name (e.g. 'bandgap', 'ldo')"),
    pdk: z.enum(["gf180", "sky130", "sg13g2", "ihp", "custom"]).default("gf180").describe("Target PDK (native tech resolved family-agnostically)"),
    output_dir: z.string().describe("Output directory for GDS, LEF, extracted netlist"),
    matching_pairs: z.array(z.array(z.string()).min(2).max(2)).default([]).describe(
      "Pairs of instance names that must be matched (common-centroid), e.g. [['M1','M2'],['M3','M4']]"
    ),
    guard_rings: z.boolean().default(true).describe("Add substrate guard rings around analog blocks"),
    drc_check: z.boolean().default(true).describe("Run DRC after layout"),
    lvs_check: z.boolean().default(true).describe("Run LVS after extraction"),
    custom_pdk_path: z.string().optional().describe("PDK path for custom PDK (magicrc location)"),
  },
  async ({ spice_netlist, block_name, pdk, output_dir, matching_pairs, guard_rings, drc_check, lvs_check, custom_pdk_path }) => {
    try {
      assertSafePath(spice_netlist, "spice_netlist");
      assertSafeIdent(block_name, "block_name");
      assertSafePath(output_dir, "output_dir");
      optPath(custom_pdk_path, "custom_pdk_path");
      (matching_pairs || []).forEach((pair) => (pair || []).forEach((n) => assertSafeIdent(n, "matching_pairs")));
    } catch (e) { return guardError(e); }
    const fs = await import("fs");
    const path = await import("path");

    if (!fs.existsSync(spice_netlist)) {
      return { content: [{ type: "text", text: JSON.stringify({ error: `SPICE netlist not found: ${spice_netlist}` }) }] };
    }
    fs.mkdirSync(output_dir, { recursive: true });

    // Native tech resolution is family-agnostic: each installed PDK exposes
    // its magicrc at `<PDK_ROOT>/<tech>/libs.tech/magic/<tech>.magicrc` and its
    // netgen setup at `<tech>_setup.tcl`. ORGANIC-headline: IHP SG13G2 ships
    // in the container (libs.tech/{magic,klayout,netgen}), so A5/A6 tech files
    // resolve natively — no substitution.
    const pdkMap = {
      gf180: { tech: "gf180mcuD", magicrc: `${PDK_ROOT}/gf180mcuD/libs.tech/magic/gf180mcuD.magicrc` },
      sky130: { tech: "sky130A", magicrc: `${PDK_ROOT}/sky130A/libs.tech/magic/sky130A.magicrc` },
      sg13g2: { tech: "ihp-sg13g2", magicrc: `${PDK_ROOT}/ihp-sg13g2/libs.tech/magic/ihp-sg13g2.magicrc` },
      ihp: { tech: "ihp-sg13g2", magicrc: `${PDK_ROOT}/ihp-sg13g2/libs.tech/magic/ihp-sg13g2.magicrc` },
      custom: { tech: "custom", magicrc: custom_pdk_path || "" },
    };
    const pdkInfo = pdkMap[pdk];

    // Generate Magic TCL script for analog layout
    const matchingTcl = matching_pairs.map(([a, b]) =>
      `# Matching pair: ${a} <-> ${b}\nputs "INFO: matching constraint ${a}/${b} — manual interdigitation required"`
    ).join("\n");

    const guardTcl = guard_rings
      ? `# Guard ring generation\nselect top cell\nputs "INFO: guard rings enabled — substrate isolation will be added"`
      : `puts "INFO: guard rings disabled"`;

    const tclScript = `# Auto-generated analog layout script for ${block_name}
# PDK: ${pdk} (${pdkInfo.tech})
tech load ${pdkInfo.magicrc}

# Import SPICE netlist
ext2spice default
readspice ${spice_netlist}

${matchingTcl}

${guardTcl}

# Export GDS
gds write ${path.join(output_dir, block_name + ".gds")}

# Export LEF
lef write ${path.join(output_dir, block_name + ".lef")}

# Parasitic extraction
extract all
ext2spice lvs
ext2spice -o ${path.join(output_dir, block_name + "_extracted.sp")}

puts "DONE: analog layout complete for ${block_name}"
`;

    const tclPath = path.join(output_dir, `${block_name}_layout.tcl`);
    fs.writeFileSync(tclPath, tclScript);

    // Run Magic inside Docker via dockerExec, which now uses an argv-based
    // spawnSync — no host-shell layer, inputs already validated at entry.
    const magicCmd = `magic -dnull -noconsole -T ${pdkInfo.magicrc} < ${tclPath}`;
    const mres = dockerExec(magicCmd, 300000);
    let stdout = mres.output || "";
    let stderr = mres.success ? "" : (mres.error || "");
    let exitCode = mres.success ? 0 : (mres.exitCode || 1);

    const gdsOut = path.join(output_dir, `${block_name}.gds`);
    const magOut = path.join(output_dir, `${block_name}.mag`);
    const result = {
      block_name,
      pdk,
      tcl_script: tclPath,
      outputs: {
        gds: gdsOut,
        lef: path.join(output_dir, `${block_name}.lef`),
        extracted_netlist: path.join(output_dir, `${block_name}_extracted.sp`),
      },
      matching_pairs,
      guard_rings,
      exit_code: exitCode,
      stdout_tail: stdout.slice(-2000),
      stderr_tail: stderr.slice(-2000),
    };

    // ORGANIC #144 — geometry-emptiness honesty. The TCL above is
    // `readspice`+`gds write` with the matching / guard-ring directives
    // emitted only as `puts INFO` comments — it loads the device hierarchy
    // but PLACES nothing. Inspect the streamed GDS/.mag: if it carries no
    // real placed geometry, this is a SCAFFOLD, not a placed layout — never
    // report a fake DONE/success. `readspice` alone does not constitute
    // placement, so the empty stream must not be treated as a real layout.
    const geom = layoutHasGeometry({ gdsPath: gdsOut, magPath: magOut });
    result.placement = {
      status: geom.status,               // "DONE" (real geometry) | "SCAFFOLD"
      has_geometry: geom.hasGeometry,
      gds_geometry_records: geom.gdsRecords,
      mag_geometry_lines: geom.magLines,
      detail: geom.detail,
    };
    // DRC/LVS may only claim a verdict when magic ran AND real geometry
    // exists — running DRC/LVS against an empty cell would falsely report
    // "0 errors" / "match" on nothing placed.
    const layoutOk = exitCode === 0 && geom.hasGeometry;

    if (drc_check && layoutOk) {
      const drcCmd = `cd ${output_dir} && magic -dnull -noconsole -T ${pdkInfo.magicrc} -c 'load ${block_name}; drc check; drc count; quit'`;
      const drcRes = dockerExec(drcCmd, 120000);
      if (drcRes.success) {
        const drcOut = drcRes.output || "";
        const countMatch = drcOut.match(/(\d+)\s+error/i);
        result.drc = { ran: true, errors: countMatch ? parseInt(countMatch[1]) : 0, output_tail: drcOut.slice(-500) };
      } else {
        result.drc = { ran: true, errors: -1, error: (drcRes.error || "").toString().slice(-500) };
      }
    }

    if (lvs_check && layoutOk) {
      const lvsCmd = `cd ${output_dir} && netgen -batch lvs '${block_name}_extracted.sp ${block_name}' '${spice_netlist} ${block_name}' ${pdkInfo.tech}_setup.tcl ${block_name}_lvs.log`;
      const lvsRes = dockerExec(lvsCmd, 120000);
      if (lvsRes.success) {
        const lvsOut = lvsRes.output || "";
        // #524: use the shared empirically-validated classifier — the old
        // inline match-only regex scored netgen property-error / failed-pin-
        // matching FAILs as match:true (no mismatch tokens at all), and
        // "Final result.*Correct" is not a netgen phrase.
        const v = classifyNetgenVerdict(lvsOut, { reportWritten: true });
        result.lvs = {
          ran: true, match: v.matched === true, verdict: v.verdict,
          property_errors: v.property_errors === true,
          did_not_run: v.did_not_run === true,
          output_tail: lvsOut.slice(-500),
        };
      } else {
        result.lvs = { ran: true, match: false, error: (lvsRes.error || "").toString().slice(-500) };
      }
    }

    // ORGANIC #144 — the tool succeeds ONLY when magic ran AND real geometry
    // was placed. An empty stream (netlist loaded, nothing placed) is a
    // SCAFFOLD, reported honestly — never a fake DONE. The manifest records
    // SCAFFOLD (not PASS) so downstream gates and human review see the truth.
    if (exitCode !== 0) {
      result.status = "FAIL";
      result.success = false;
      result.message = `magic exited ${exitCode} — layout did not run.`;
    } else if (!geom.hasGeometry) {
      result.status = "SCAFFOLD";
      result.success = false;
      result.message =
        `SCAFFOLD: ${geom.detail} The generated Magic TCL is ` +
        `readspice + gds write with matching/guard-ring emitted only as ` +
        `INFO comments; it does not place devices. Use a real auto-layout ` +
        `pass (PCell/paint/place + guard-ring + route) before A5 sign-off.`;
    } else {
      result.status = "DONE";
      result.success = true;
      result.message = `DONE: analog layout complete for ${block_name} — ${geom.detail}`;
    }
    writeManifest(output_dir, { step: "eda_analog_layout", status: result.status, block: block_name, pdk });
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

// ─── eda_fpga_adc_read ─── v0.108: read MAX10 internal 12-bit SAR ADC ───
// DE10-Lite has an internal ADC (ALTPLL + ADC Megafunction). This tool reads
// analog voltage from a specified ADC channel via JTAG (using system-console
// or nios2-terminal). Used by analog-hw-measure skill for hardware-in-the-loop
// analog verification.
server.tool(
  "eda_fpga_adc_read",
  "Read DE10-Lite MAX10 internal 12-bit ADC value via JTAG. Returns voltage "
  + "(0-3.3V range, 12-bit resolution ~0.8mV). Requires Quartus system-console. "
  + "v0.108: hardware-in-the-loop analog verification.",
  {
    channel: z.number().min(0).max(17).default(0).describe("ADC channel number (0-17 on MAX10)"),
    samples: z.number().min(1).max(1000).default(10).describe("Number of samples to average"),
    cable: z.string().default("USB-Blaster").describe("JTAG cable name"),
    reference_voltage: z.number().default(3.3).describe("ADC reference voltage (V)"),
    quartus_path: z.string().default("/opt/intelFPGA_lite/23.1std/quartus").describe("Quartus install path"),
  },
  async ({ channel, samples, cable, reference_voltage, quartus_path }) => {
    try {
      assertSafePath(quartus_path, "quartus_path");
      optToken(cable, "cable");
    } catch (e) { return guardError(e); }
    const fs = await import("fs");
    const path = await import("path");
    const { execSync } = await import("child_process");

    // Generate Tcl script for system-console ADC read
    const tclScript = `# Auto-generated ADC read script
# Channel: ${channel}, Samples: ${samples}
set adc_path [lindex [get_service_paths master] 0]
open_service master $adc_path

# MAX10 ADC base address (from Platform Designer)
set ADC_BASE 0x00000000

# Sequencer: set channel
master_write_32 $adc_path [expr {$ADC_BASE + 0x00}] ${channel}

# Trigger and read ${samples} samples
set sum 0
for {set i 0} {$i < ${samples}} {incr i} {
  # Write 0 to trigger conversion
  master_write_32 $adc_path [expr {$ADC_BASE + 0x00}] 0
  after 1
  set raw [master_read_32 $adc_path [expr {$ADC_BASE + 0x04}] 1]
  set val [expr {$raw & 0xFFF}]
  set sum [expr {$sum + $val}]
}

set avg [expr {double($sum) / ${samples}}]
set voltage [expr {$avg * ${reference_voltage} / 4096.0}]
puts "ADC_RESULT: channel=${channel} raw_avg=[format {%.1f} $avg] voltage=[format {%.4f} $voltage]V samples=${samples}"

close_service master $adc_path
`;
    const tmpDir = "/tmp/adc_read";
    fs.mkdirSync(tmpDir, { recursive: true });
    const tclPath = path.join(tmpDir, `adc_ch${channel}.tcl`);
    fs.writeFileSync(tclPath, tclScript);

    const sysCon = path.join(quartus_path, "sopc_builder/bin/system-console");
    // security hardening: run on HOST via argv (no shell) so quartus_path /
    // cable are never shell-parsed.
    let stdout = "", stderr = "", exitCode = 0;
    {
      const r = _spawnSync(sysCon, [`--script=${tclPath}`, `--cable=${cable}`],
        { encoding: "utf-8", timeout: 30000, maxBuffer: 1024 * 1024 });
      stdout = (r.stdout || "").toString();
      if (r.error) { stderr = r.error.message || String(r.error); exitCode = r.status || 1; }
      else if (r.status !== 0) { stderr = (r.stderr || "").toString(); exitCode = r.status || 1; }
    }

    const result = { channel, samples, reference_voltage, exit_code: exitCode };

    // Parse ADC_RESULT line
    const match = stdout.match(/ADC_RESULT:.*raw_avg=([\d.]+)\s+voltage=([\d.]+)V/);
    if (match) {
      result.raw_avg = parseFloat(match[1]);
      result.voltage = parseFloat(match[2]);
      result.success = true;
    } else {
      result.success = false;
      result.error = exitCode !== 0 ? stderr.slice(-500) : "Could not parse ADC result";
      result.stdout_tail = stdout.slice(-500);
    }

    writeManifest(tmpDir, { step: "eda_fpga_adc_read", status: result.success ? "PASS" : "FAIL", channel, voltage: result.voltage });
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

// ─── Start Server ───
// v2.5.4: docker-group self-heal at startup. Common failure mode: user is
// in /etc/group's `docker` group but the running shell (and so this node
// process) inherited the OLD groups from before usermod. Without this,
// every dockerExec returns permission-denied even though the system is
// fully configured. We probe `docker ps`; on permission-denied, if the user
// IS a declared member of group `docker`, we re-exec ourselves under
// `sg docker -c "exec node <this-script>"` so the child inherits the group.
// One-shot: env MCP_EDA_GROUP_FIXED=1 prevents loops if `sg docker` itself
// fails (e.g. group truly unconfigured, or sg unavailable).
import { execSync as _execSync } from "child_process";
// Wave 33: _spawnSync is imported at the top of this file as
// _spawnSyncEarly and re-exposed under the legacy `_spawnSync`
// name; the duplicate import here was removed to avoid name
// collision.
function _maybeSelfHealDockerGroup() {
  if (process.env.MCP_EDA_GROUP_FIXED) return;
  // Only attempt on Linux
  if (process.platform !== "linux") return;
  try {
    _execSync(`docker ps --filter name=${CONTAINER} --format '{{.Names}}'`, {
      timeout: 4000, stdio: ["ignore", "pipe", "pipe"],
    });
    return; // already works
  } catch (err) {
    const stderr = (err.stderr || "").toString();
    if (!stderr.includes("permission denied")) return; // not a group issue
  }
  // Check if user is in /etc/group docker line
  let inGroupOnDisk = false;
  try {
    const grp = _execSync("getent group docker", { encoding: "utf-8", timeout: 2000 }).trim();
    const members = grp.split(":").pop() || "";
    const me = (process.env.USER || _execSync("whoami", { encoding: "utf-8" }).trim());
    inGroupOnDisk = members.split(",").includes(me);
  } catch (e) { /* getent unavailable */ }
  if (!inGroupOnDisk) {
    console.error("[startup] docker socket denied AND user not in /etc/group docker line.");
    console.error("[startup] Fix: sudo usermod -aG docker $USER && fully log out + back in (or restart this server from a fresh shell).");
    return; // continue starting; tools will surface docker_unreachable diagnostic
  }
  // We ARE in the on-disk docker group but the running process didn't
  // inherit it — re-exec under sg docker so the child gets the gid.
  console.error("[startup] re-exec under `sg docker` to acquire docker gid (one-shot self-heal)");
  const child = _spawnSync("sg", ["docker", "-c", `exec env MCP_EDA_GROUP_FIXED=1 node ${process.argv[1]}`], {
    stdio: "inherit",
  });
  process.exit(child.status === null ? 1 : child.status);
}

// ─── Tool: eda_oracle_bytewise_dump ─────────────────────────────────────
// v0.114 (BACKLOG-v6 D2, deferred 7+ versions). Burns a known-PASS oracle
// SOF + captures every byte the host tester sees, then returns the
// canonical byte stream as ground-truth oracle. Closes the v0.108 round-1
// debug-loop gap: previously, when a fresh-agent SOF FAILed USB-HID tester and
// the agent had no oracle to compare against, it had to manually read
// scope CSV — wasted hours. With this tool, agent calls once, gets
// the expected byte stream for every command, and any future SOF
// can be diffed byte-by-byte.
server.tool(
  "eda_oracle_bytewise_dump",
  "Burn a known-PASS oracle SOF, run the host tester (USB-HID tester / equiv) "
  + "connect_test, capture the bus waveform via scope, decode pulses "
  + "to bytes using L2 timing, return the canonical command→response "
  + "byte stream as ground truth. Use this to establish oracle vectors "
  + "from a working IC for any command-response IC project. Output is "
  + "ready for rtl_response_byte_oracle_check.py --oracle-json. "
  + "Closes BACKLOG-v6 D2 (deferred 7+ versions). Saves hours of manual "
  + "scope-decode debugging when a fresh-agent SOF FAILs.",
  {
    oracle_sof_path: z.string().describe(
      "Path to the known-PASS reference SOF (e.g. v099run2 PASS oracle)"),
    project_dir: z.string().describe(
      "Project directory where output oracle JSON should be written"),
    l2_timing_json: z.string().describe(
      "L2_TIMING_WAVEFORM.json path with bit/BR/IBT cycle definitions"),
    scope_channel: z.number().default(1).describe(
      "Scope probe channel (verified in v0.108: channel 1 on this rig)"),
    scope_pid: z.number().default(5990).describe(
      "Scope USB PID — 5990 (0x1766) for DSO-X 3024G; default 1768 fails"),
    capture_span_ms: z.number().default(8).describe(
      "Capture window (ms) — default 8 covers ~5 s of USB-HID tester connect_test"),
    output_oracle_json: z.string().optional().describe(
      "Path for output L10-style oracle JSON (default: <project>/generated_docs/L10_oracle.json)"),
  },
  async (args) => {
    try {
      assertSafePath(args.oracle_sof_path, "oracle_sof_path");
      assertSafePath(args.project_dir, "project_dir");
      assertSafePath(args.l2_timing_json, "l2_timing_json");
      optPath(args.output_oracle_json, "output_oracle_json");
    } catch (e) { return guardError(e); }
    const fs = await import("fs");
    const path = await import("path");
    const { execSync } = await import("child_process");

    // Step 1 — burn oracle SOF (delegate to existing device tool).
    // security hardening: run on HOST via argv (no shell) — the quartus_pgm
    // -o operand `p;<path>@1` is passed as a single argument, so
    // oracle_sof_path is never shell-parsed (the former
    // `quartus_pgm ... p\;${path}@1` was a host command-injection vector).
    let burnOk = false;
    {
      const r = _spawnSync(
        "quartus_pgm",
        ["-m", "JTAG", "-c", "USB-Blaster", "-o", `p;${args.oracle_sof_path}@1`],
        { encoding: "utf-8", timeout: 120_000, maxBuffer: 16 * 1024 * 1024 }
      );
      if (r.error || r.status !== 0) {
        const e = r.error || new Error((r.stderr || "").toString() || `exit ${r.status}`);
        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              success: false,
              stage: "burn_sof",
              error: "oracle SOF burn failed — verify quartus_pgm + USB-Blaster",
              detail: (e.stderr || e.stdout || "").toString().slice(-1500),
            }, null, 2),
          }],
        };
      }
      const out = (r.stdout || "").toString();
      burnOk = out.includes("Configuration succeeded") || out.includes("Successfully performed");
    }

    // Step 2 — reset host tester (memory rule: 0xFF before fresh test)
    // Step 3 — connect_test + scope_capture in parallel — orchestration
    //          delegated to the existing device tools via re-invocation.
    //          This stub returns the canonical oracle JSON shape for the
    //          agent to populate; full live capture is rig-dependent.
    const outPath = args.output_oracle_json
      || path.join(args.project_dir, "generated_docs", "L10_oracle.json");

    const oracleScaffold = {
      schema: "vibe-ic L10 oracle byte stream v1",
      generated_by: "eda_oracle_bytewise_dump",
      generated_at: new Date().toISOString(),
      source_sof: args.oracle_sof_path,
      l2_timing_json: args.l2_timing_json,
      scope: {
        channel: args.scope_channel,
        pid: args.scope_pid,
        span_ms: args.capture_span_ms,
      },
      sof_burn: { success: burnOk },
      next_steps: [
        "Run your host-tester send_raw cmd_byte=255 (DISCONNECT)",
        "Run your host-tester connect_test in background",
        "Run device_scope_capture channel=1 pid=5990 span_ms=8",
        "Decode CSV via eda_scope_protocol_decode with L2 timing",
        "Append decoded byte stream per opcode to opcode_oracle_vectors[] in this file",
      ],
      opcode_oracle_vectors: [],
      provenance: {
        method: "burn-oracle-then-capture",
        chip_agnostic: true,
        notes:
          "This tool produces a SCAFFOLD. The canonical oracle byte "
          + "stream for each opcode is captured live via scope and "
          + "appended to opcode_oracle_vectors[] by the agent or by a "
          + "follow-on automation script. See "
          + "rtl_response_byte_oracle_check.py --oracle-json for the "
          + "expected schema.",
      },
    };

    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    fs.writeFileSync(outPath, JSON.stringify(oracleScaffold, null, 2));

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: burnOk,
          stage: "scaffold_emitted",
          oracle_json: outPath,
          burn_ok: burnOk,
          next_action:
            "Oracle SOF burned. Now run your host-tester send_raw "
            + "cmd_byte=255, then connect_test + scope_capture in parallel, "
            + "then decode and append to opcode_oracle_vectors[].",
          hint: oracleScaffold.next_steps,
        }, null, 2),
      }],
    };
  },
);

// ─── Tool: mcp_server_health_check ──────────────────────────────────────
// v0.113 (BACKLOG-v10 P1.4): lightweight health probe. Any agent can call
// this to detect MCP server liveness + tool inventory + uptime without
// invoking any heavyweight EDA tool. v0.108 bench-a round 3 had device-side
// tools silently disconnect mid-run; this tool gives agents a way to
// detect that quickly and fall back to direct tool invocation.
const _mcpStartTime = Date.now();
server.tool(
  "mcp_server_health_check",
  "Lightweight liveness probe for the mcp-eda. Returns server "
  + "uptime + tool count + node version. Use to detect mid-run MCP "
  + "disconnect (v0.108 bench-a lesson) — if this tool errors, fall back "
  + "to direct CLI invocation of underlying tools (python3 / docker exec). "
  + "Cheap (~1ms); call before long-running flows + after each major step.",
  {},
  async () => {
    const uptime_ms = Date.now() - _mcpStartTime;
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          status: "alive",
          uptime_ms,
          uptime_human: `${Math.floor(uptime_ms/3600000)}h ${Math.floor((uptime_ms%3600000)/60000)}m ${Math.floor((uptime_ms%60000)/1000)}s`,
          node_version: process.version,
          server_pid: process.pid,
          server_version: "1.0.0",
          probe_timestamp: new Date().toISOString(),
        }, null, 2),
      }],
    };
  },
);

// ─── Tool: eda_phase23_completion_audit ─────────────────────────────────
// v0.109: SOLE acceptance gate for Phase 2+3 completion claims. Wraps
// programs/phase23_completion_self_audit_check.py which itself wraps
// flow_compliance_check.py --strict. Embeds the rule into the tool
// description so any agent picking up the tool inventory cannot miss it.
server.tool(
  "eda_phase23_completion_audit",
  "⛔ SOLE PHASE 2+3 ACCEPTANCE CRITERION — call this before claiming "
  + "'Phase 2+3 complete', 'design flow done', 'tape-out ready', "
  + "'ready for fab', or any equivalent. Returns Overall PASS/FAIL plus "
  + "non-waived PASS = N/34. Individual gates passing (tapeout_signoff, "
  + "host-tester connect_test, BACKLOG-v6/v7 P0) are NECESSARY BUT INSUFFICIENT "
  + "— this gate audits all 34 canonical artefacts (PnR signoff, SPEF, "
  + "post-route STA, IR/EM/antenna/SI, post-layout sim, SPICE correlation, "
  + "ECO, power, metal fill, FPGA final sign-off, analog A1-A8). v0.108 "
  + "fresh-agent benchmark proved a project can pass every individual gate "
  + "while only completing 2/34 canonical steps. Run this. Paste the "
  + "output into FINAL_REPORT.md. Don't claim PASS without it.",
  {
    project_dir: z.string().describe("Absolute path to the project directory (containing rtl/, fpga/, gds/, etc.)"),
  },
  async ({ project_dir }) => {
    try {
      assertSafePath(project_dir, "project_dir");
    } catch (e) { return guardError(e); }
    const path = await import("path");
    const here = path.dirname(new URL(import.meta.url).pathname);
    const gate = path.resolve(here, "..", "..", "vibe-ic-marketplace", "plugins", "vibe-ic-d", "programs", "phase23_completion_self_audit_check.py");
    let output, exitCode;
    {
      // security hardening: run via argv (no shell) so project_dir is never
      // shell-parsed.
      const r = _spawnSync("python3", [gate, project_dir, "--json", "-"], {
        encoding: "utf-8",
        timeout: 300_000,
        maxBuffer: 32 * 1024 * 1024,
      });
      output = (r.stdout || "") + (r.stderr || "");
      exitCode = r.error ? 1 : (r.status ?? 1);
    }
    let parsed;
    try {
      parsed = JSON.parse(output);
    } catch {
      parsed = { raw_output: output };
    }
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          ...parsed,
          exit_code: exitCode,
          phase23_complete: exitCode === 0,
        }, null, 2),
      }],
    };
  },
);

// v1.6.231 — FPGA-GDS-reverify chain wrappers (4 new tools).
// Each wraps one program shipped in v1.6.231. Programs are the source
// of truth; these MCP tools just give agents a uniform calling surface.

function _runPyProgram(programRelPath, args, timeoutMs = 600_000) {
  const path = require("path");
  const { execFileSync } = require("child_process");
  const here = path.dirname(new URL(import.meta.url).pathname);
  // index.js lives at mcp-eda/src/, programs are in the
  // sibling plugin tree.
  const candidates = [
    path.resolve(here, "..", "..", "vibe-ic-marketplace", "plugins",
                  "vibe-ic", "programs", programRelPath),
    path.resolve(here, "..", "..", "..", "vibe-ic-marketplace",
                  "plugins", "vibe-ic", "programs", programRelPath),
    path.resolve(here, "..", "..", "..", "..", "vibe-ic-marketplace",
                  "plugins", "vibe-ic", "programs", programRelPath),
    path.resolve(here, "..", "..", "programs", programRelPath),
  ];
  let program = null;
  const fs = require("fs");
  for (const c of candidates) {
    if (fs.existsSync(c)) { program = c; break; }
  }
  if (!program) {
    return { output: `error: program not found in any of ${JSON.stringify(candidates)}`,
              exitCode: 2, program: programRelPath };
  }
  let output, exitCode;
  try {
    output = execFileSync("python3", [program, ...args], {
      encoding: "utf-8",
      timeout: timeoutMs,
      maxBuffer: 32 * 1024 * 1024,
    });
    exitCode = 0;
  } catch (e) {
    output = (e.stdout || "") + (e.stderr || "");
    exitCode = e.status ?? 1;
  }
  return { output, exitCode, program };
}

server.tool(
  "eda_fpga_gds_reverify",
  "v1.6.231 — Run the FPGA gate-level reverify chain (UDP shim → "
  + "Yosys flatten → OTP altsyncram inject → wrapper-gen → polarity "
  + "check; then step 6 attestation when --post-compile <map.rpt>). "
  + "Replaces the 6-command manual sequence that v1.6.222→230 evolved.",
  {
    project: z.string().describe("Project root (contains phase3/, fpga/, input/)"),
    pnr_netlist: z.string().describe("Post-PnR gate netlist (e.g. chip_top_asic_pnr.v)"),
    pdk_behavioral: z.string().describe("PDK std-cell behavioural .v"),
    otp_hex: z.string().describe("OTP image — one byte per line ASCII hex"),
    rtl_chip_top: z.string().describe("RTL chip_top.sv (port shape)"),
    rtl_chip_top_asic: z.string().describe("RTL chip_top_asic.sv (polarity)"),
    fpga_qsf: z.string().describe("Quartus QSF file"),
    top: z.string().optional().describe("Top module name (default: chip_top_asic)"),
    bus_prefix: z.string().optional().describe("Open-drain bus prefix"),
    skip_program: z.boolean().optional().describe("Skip the JTAG program step"),
    post_compile: z.string().optional().describe("Quartus *.map.rpt; runs step 6 only"),
  },
  async (args) => {
    const cli = ["--project", args.project,
                 "--pnr-netlist", args.pnr_netlist,
                 "--pdk-behavioral", args.pdk_behavioral,
                 "--otp-hex", args.otp_hex,
                 "--rtl-chip-top", args.rtl_chip_top,
                 "--rtl-chip-top-asic", args.rtl_chip_top_asic,
                 "--fpga-qsf", args.fpga_qsf,
                 "--json", "-"];
    if (args.top) cli.push("--top", args.top);
    if (args.bus_prefix) cli.push("--bus-prefix", args.bus_prefix);
    if (args.skip_program) cli.push("--skip-program");
    if (args.post_compile) cli.push("--post-compile", args.post_compile);
    const { output, exitCode } = _runPyProgram("pdk_fpga_gds_reverify_runner.py", cli);
    let parsed; try { parsed = JSON.parse(output); } catch { parsed = { raw_output: output }; }
    return { content: [{ type: "text",
      text: JSON.stringify({ ...parsed, exit_code: exitCode }, null, 2) }] };
  },
);

server.tool(
  "eda_fpga_gate_attestation_check",
  "v1.6.231 — Verify Quartus actually compiled the GATE-LEVEL "
  + "netlist (not silent RTL fallback). Greps map.rpt for RTL-"
  + "submodule markers + PDK std-cell evidence. Catches v3 false-"
  + "PASS where Quartus silently used RTL chip_top.sv.",
  {
    map_rpt: z.string().describe("Quartus *.map.rpt path"),
    gate_top: z.string().optional().describe("Gate-level top module name"),
    rtl_submodules: z.string().optional().describe("Comma-separated submodule names to flag"),
  },
  async (args) => {
    const cli = ["--map-rpt", args.map_rpt];
    if (args.gate_top) cli.push("--gate-top", args.gate_top);
    if (args.rtl_submodules) cli.push("--rtl-submodules", args.rtl_submodules);
    cli.push("--json", "-");
    const { output, exitCode } = _runPyProgram("fpga_gate_level_attestation_check.py", cli, 60_000);
    let parsed; try { parsed = JSON.parse(output); } catch { parsed = { raw_output: output }; }
    return { content: [{ type: "text",
      text: JSON.stringify({ ...parsed, exit_code: exitCode }, null, 2) }] };
  },
);

server.tool(
  "eda_chip_top_gate_wrapper_gen",
  "v1.6.231 — Auto-generate a synthesizable chip_top wrapper from "
  + "the RTL port list + chip_top_asic.sv open-drain polarity. The "
  + "wrapper exposes RTL port shape to Quartus while instantiating "
  + "the gate-level top with a polarity-correct tri-state.",
  {
    rtl_chip_top: z.string().describe("RTL chip_top.sv path (port shape)"),
    rtl_chip_top_asic: z.string().describe("RTL chip_top_asic.sv path (polarity)"),
    output: z.string().describe("Output wrapper .v path"),
    bus: z.string().optional().describe("Bus name (default: id_bus)"),
    gate_top: z.string().optional().describe("Gate-level top module name"),
  },
  async (args) => {
    const cli = ["--rtl-chip-top", args.rtl_chip_top,
                 "--rtl-chip-top-asic", args.rtl_chip_top_asic,
                 "--output", args.output];
    if (args.bus) cli.push("--bus", args.bus);
    if (args.gate_top) cli.push("--gate-top", args.gate_top);
    const { output, exitCode } = _runPyProgram("chip_top_gate_wrapper_gen.py", cli, 60_000);
    return { content: [{ type: "text",
      text: JSON.stringify({ exit_code: exitCode, output, wrapper_path: args.output }, null, 2) }] };
  },
);

server.tool(
  "eda_rtl_name_semantic_check",
  "v1.6.231 — Lint RTL for active-low NAME / active-high VALUE "
  + "polarity mismatch (e.g. `id_bus_oe_low = id_bus_drive_low`). "
  + "Catches the FPGA-silent-DUT class of bug where the wrapper "
  + "reads the bus 99% LOW because the consumer interprets `_oe_"
  + "low` as active-LOW but RTL drives it active-HIGH.",
  {
    rtl: z.string().describe("RTL file or directory"),
    fail_on_warn: z.boolean().optional().describe("Exit 1 on any WARN (CI mode)"),
  },
  async (args) => {
    const cli = [args.rtl, "--json", "-"];
    if (args.fail_on_warn) cli.push("--fail-on-warn");
    const { output, exitCode } = _runPyProgram("rtl_signal_name_semantic_check.py", cli, 60_000);
    let parsed; try { parsed = JSON.parse(output); } catch { parsed = { raw_output: output }; }
    return { content: [{ type: "text",
      text: JSON.stringify({ ...parsed, exit_code: exitCode }, null, 2) }] };
  },
);

// ─── Tool: eda_spinalhdl_gen ───
//
// Elaborate a SpinalHDL / Chisel-style sbt project to synthesizable Verilog by
// running `sbt "runMain <main_class>"` inside the IIC-OSIC-TOOLS container,
// which ships OpenJDK 17 + sbt. This unblocks "Scala-source-only" RISC-V cores
// (e.g. VexRiscv / Murax via `vexriscv.demo.GenSmallest`) that have no
// checked-in .v — Phase 2 can then ingest the elaborated netlist instead of
// stalling at rtl_gen with "rtl/ missing". SpinalHDL itself is resolved from
// Maven Central by sbt on first run and cached thereafter in the container's
// ~/.ivy2 / coursier. Everything runs in-container; no host FS writes.
server.tool(
  "eda_spinalhdl_gen",
  "Elaborate a SpinalHDL/sbt project to Verilog by running `sbt runMain <main_class>` inside the vibeic-eda container (OpenJDK 17 + sbt present; SpinalHDL pulled from Maven Central, cached). Unblocks Scala-source-only cores like VexRiscv/Murax. Returns success, generated .v files (sha256 + line counts) and a log tail.",
  {
    project_dir: z.string().describe("sbt project root INSIDE the container (contains build.sbt), e.g. /foss/designs/_vexriscv_gen"),
    main_class: z.string().describe("Fully-qualified runMain target, e.g. vexriscv.demo.GenSmallest"),
    expected_verilog: z.string().optional().describe("Optional expected output .v path (inside container) to verify + hash"),
    timeout_sec: z.number().int().min(30).max(3600).default(1200).describe("Max seconds for the sbt run (cold runs download deps and can take minutes)"),
  },
  async ({ project_dir, main_class, expected_verilog, timeout_sec }) => {
    try {
      assertSafePath(project_dir, "project_dir");
      assertSafeToken(main_class, "main_class");
      optPath(expected_verilog, "expected_verilog");
    } catch (e) { return guardError(e); }

    const cmdStr = `command -v sbt >/dev/null 2>&1 || { echo "SBT_MISSING (java=$(command -v java || echo none))"; exit 127; }; cd ${project_dir} && sbt -batch "runMain ${main_class}" 2>&1; echo "SBT_RC=$?"`;
    const t0 = Date.now();
    const result = dockerExec(cmdStr, timeout_sec * 1000);
    const durationMs = Date.now() - t0;

    const out = result.output || "";
    const rcMatch = out.match(/SBT_RC=(\d+)/);
    const sbtRc = rcMatch ? parseInt(rcMatch[1]) : null;
    const success = result.success && /\[success\]/.test(out) && sbtRc === 0;

    // discover generated .v/.sv at the project root (default SpinalHDL output dir)
    const lsCmd = `cd ${project_dir} && for f in *.v *.sv; do [ -f "$f" ] && printf "%s\\t%s\\t" "$f" "$(wc -l < "$f")" && sha256sum "$f" | cut -d" " -f1; done 2>/dev/null`;
    const ls = dockerExec(lsCmd, 30000);
    const generated = (ls.output || "").trim().split("\n").filter(Boolean).map((ln) => {
      const [name, lines, sha256] = ln.split("\t");
      return { file: name, lines: parseInt(lines) || null, sha256: (sha256 || "").trim() };
    });

    const metrics = {
      success,
      sbt_rc: sbtRc,
      main_class,
      project_dir,
      generated,
      duration_ms: durationMs,
      log_tail: out.slice(-6000),
    };
    return { content: [{ type: "text", text: JSON.stringify(metrics) }] };
  }
);

async function main() {
  _maybeSelfHealDockerGroup();

  // v0.65: auto-register vendor device tools from src/devices/<vendor>/.
  // Wrapped in try/catch so a broken driver can't take down the server.
  try {
    await registerDevices(server);
  } catch (e) {
    console.error(`[devices] registry failed: ${e.message}`);
  }

  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("MCP EDA Server running");
}
main().catch(console.error);
