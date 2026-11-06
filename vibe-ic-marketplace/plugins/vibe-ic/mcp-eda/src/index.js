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
import { containerToolCommand } from "./lib/tool_path.mjs";
import { parseYosysSynthStats } from "./lib/yosys_synth_stats.mjs";
import { cocotbJunitScript, cocotbJunitResult } from "./lib/cocotb_results.mjs";
// Shell-safety validators (command-injection hardening). The argv-based
// _spawnSync used by dockerExec + host handlers is the existing legacy
// import declared further down (`spawnSync as _spawnSyncEarly`).
import {
  shq, assertSafeIdent, assertSafeToken, assertSafeContainer, assertNoShellMeta,
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
import { gateManifestEntry } from "./lib/manifest_metrics.mjs";
import { parseWns, parseTns } from "./lib/sta_slack.mjs";
import { parseIrReport, parseReportPower } from "./lib/psm_report.mjs";
import { evaluateStaEvidence, staEvidenceTcl, STA_EVIDENCE_TERMS } from "./lib/sta_evidence.mjs";

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

// Resolve the MCP execution target once. EDA_CONTAINER remains authoritative
// when both selectors are set; Python's selector is also accepted on its own.
const CONTAINER = (process.env.EDA_CONTAINER || "").trim()
  || (process.env.VIBEIC_EDA_CONTAINER || "").trim() || "vibeic-eda";
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
//
// A manifest may record `status:"PASS"` only when the metrics that prove the
// work happened are present. `gateManifestEntry` (src/lib/manifest_metrics.mjs)
// holds the per-step declaration of what those metrics are; a PASS whose
// required metrics are absent is rewritten to INCONCLUSIVE here, naming the
// metrics that are missing. INCONCLUSIVE is neither a pass nor a failure: it
// says we did not measure this. Every call site goes through this function, so
// the rule cannot be forgotten at a new one — a step with no declaration is
// simply not gated. Returns the entry as it was actually recorded.
function writeManifest(workDir, entry) {
  const manifest = {
    timestamp: new Date().toISOString(),
    ...gateManifestEntry(entry),
  };
  const quote = (value) => "'" + String(value).replace(/'/g, "'\\''") + "'";
  // Exactly one JSON object per physical line; the normal verifier reads JSONL.
  const manifestJson = JSON.stringify(manifest);
  const appendCmd = `printf '%s\\n' ${quote(manifestJson)} >> ${quote(`${workDir}/latest_results.jsonl`)}`;
  // A JSON document is also valid YAML. Keep the readable stream lossless for
  // strings, nested values and shell metacharacters; printf must not expand them.
  const yamlDocument = JSON.stringify(manifest, null, 2) + "\n---\n";
  const ymlCmd = `printf '%s' ${quote(yamlDocument)} >> ${quote(`${workDir}/latest_results.yml`)}`;
  dockerExec(`${appendCmd} && ${ymlCmd}`, 5000);
  return manifest;
}

// Helper: SHA-256 of a host-side file (used for provenance hashing)
import { createHash } from "crypto";
import { readFileSync, existsSync, appendFileSync, mkdirSync, writeFileSync as require_fs_writeFileSync, unlinkSync } from "fs";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";
// ESM/CJS bridge. package.json declares "type":"module", so this file is an
// ES module and `require` is NOT defined in its scope — yet five call sites
// below still reach for it, and every tool routed through them threw
// "require is not defined" on every invocation. Two of those failures were
// silent: canonicalizeNetlistSrcCoords is wrapped in `catch { return false }`,
// so synthesis quietly stopped canonicalizing netlist coordinates, and
// eda_workflow_run reported a manifest path it had not written.
// createRequire() gives this module a real CJS resolver anchored at its own
// URL. No identifier named `require` exists anywhere else in this file.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
server.tool(
  "eda_fpga_program",
  "Program a SOF or BIT file using the native FPGA programmer and optionally verify the JTAG device.",
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
  },
  async ({ tool, sof_file, bit_file, cable_index, verify_burn, expected_device }) => {
    try {
      optPath(sof_file, "sof_file"); optPath(bit_file, "bit_file");
      optToken(expected_device, "expected_device");
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

      const driverPath = resolve(
        __dirname_eda, "devices", "fpga", "terasic-de10lite", "driver.py",
      );
      const driverArgs = {
        sof_path: sof_file,
        // device_index is what the driver accepts; cable_index is the
        // legacy eda_fpga_program parameter name. Map.
        device_index: cable_index,
      };

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
      optPath(field_solve_spef, "field_solve_spef"); assertSafeContainer(field_solve_container, "field_solve_container");
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

    // N6: `-dotoplabels`. A bare Magic `flatten` copies every library cell's
    // pin labels into the flat cell under instance-prefixed names, and
    // `port makeall` then promotes each one to a top port. Measured in the
    // pinned image (magic 8.3.684) on a top with two labelled instances of
    // a foundry inverter cell: bare -> `.subckt chip_flat TOPPIN
    // <inst>_0.VSS <inst>_0.ZN ...` (11 library pins promoted);
    // -dotoplabels -> `.subckt chip_flat TOPPIN VSUBS`. The flat cell keeps
    // the top's own labels only; the library's stay with the library.
    const magicScript = `
${readCmd}
load ${top_cell}
flatten -dotoplabels ${top_cell}_flat
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


// The image a container runs is fixed at CREATE time. `docker pull` moves a TAG;
// it does not touch a container already created from the old bytes. So an
// operator who pulls, then runs, executes the whole flow — every tool version,
// every PDK, every sign-off number — on the older image.
//
// `container_image_provenance.py` already names this failure ("Stale-container
// substitution (silent)") and RECORDS the identity on every run. But it only
// ENFORCES under an explicit `--require-image`, which nothing in the flow
// passes, so an unpinned run records the stale digest and still reports
// `status: ok`. A fact nobody compares does not make the substitution visible.
//
// And `eda_doctor` — which `skills/loop2converge/SKILL.md` §1.0 tells every
// operator to read the toolchain back FROM, in the same table that catches the
// MCP-binding version of this same mistake:
//
//     | `eda_doctor` -> the EDA image digest/label | which fork build the tools come from |
//
// answered `docker_reachable: container reachable` and named no image at all.
// The documented read-back had nothing to read.
//
// MEASURED 2026-08-30 on 8hd-3, following that step literally. `docker pull`
// had been run and `ghcr.io/vibeic/vibeic-eda:latest` was 26 hours newer than
// the running container, which was still serving:
//
//     container `vibeic-eda`  image sha256:ddbf1e71… created 2026-08-28T09:22Z
//                             openroad -version -> 26Q3-1867-gfbdee51542
//     :latest on the SAME host image sha256:de6b0e0f… created 2026-08-29T11:42Z
//                             openroad -version -> 26Q3-1884-g80f878d28a
//
// `eda_doctor` reported "12/12 checks passed". Seventeen OpenROAD commits
// separated the toolchain the operator believed they had pulled from the one
// their run executed, and the gap was load-bearing: on 1867 `repair_timing
// -setup` died of SIGSEGV inside `postroute_drv_repair` and the run halted; on
// 1884, same design, same PDK, that stage completed four repair+reroute
// iterations. A tool bug was filed against a build that was already superseded
// on the very machine that filed it.
//
// LOCAL ONLY, deliberately. This never reaches the registry: `_eda_image.py`
// keeps that behind an explicit `allow_pull` so two callers cannot resolve a
// floating tag to different bytes a minute apart. A container older than an
// image ALREADY ON THIS HOST is a discrepancy that needs no network to see.
//
// SOFT, deliberately, and for the same reason as the memory ceiling above: an
// older image runs every flow correctly and an operator may be pinning one on
// purpose. What must never happen is that they cannot TELL.
const _EDA_IMAGE_REPO = "ghcr.io/vibeic/vibeic-eda";
const _SHORT = (s) => String(s || "").replace(/^sha256:/, "").slice(0, 12);

// `docker inspect` gives RFC3339 ("2026-08-29T11:42:34.1Z"); `docker images`
// gives "2026-08-29 19:42:34 +0800 CST". Date.parse takes the first as-is and
// the second only once the space before the offset is closed and the trailing
// zone NAME dropped. NaN on anything else — never a 0 that would sort oldest.
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
      const suffix = engine === "klayout_python" ? ".py" : engine === "klayout_drc" ? ".drc" : "";
      tmpFile = `/tmp/run_tcl_${Date.now()}_${Math.floor(Math.random() * 100000)}${suffix}`;
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
    const tlRes = dockerExec(`cat '${techlef}'`, 10000);
    if (!tlRes.success) {
      note("error", "tech_lef_parse_unavailable", `LEF declarations were not measured: ${tlRes.error || tlRes.output || "read failed"}`);
    } else {
      try {
        // LEF comments and quoted PROPERTY values are not declarations.
        // Keep statement boundaries: TYPE may span lines, but requires ';'.
        const tokens = ((tlRes.output || "").match(/"(?:\\.|[^"\\])*"|#[^\r\n]*|[^\s;"#]+|;/g) || [])
          .filter(t => !t.startsWith("#"));
        let nlayers = 0, nrouting = 0, ncut = 0, nres = 0;
        let layer = null, layerType = null;
        const endStatement = start => {
          let j = start;
          while (j < tokens.length && tokens[j] !== ";" && tokens[j].toUpperCase() !== "END") j++;
          if (tokens[j] !== ";") throw new Error("unterminated LEF statement");
          return j;
        };
        for (let i = 0; i < tokens.length; i++) {
          const t = tokens[i].toUpperCase();
          if (t === "PROPERTY") { i = endStatement(i + 1); continue; }
          if (!layer && ["VIA", "VIARULE", "MACRO", "SITE", "NONDEFAULTRULE", "PROPERTYDEFINITIONS"].includes(t)) {
            const name = t === "PROPERTYDEFINITIONS" ? t : tokens[++i];
            while (i < tokens.length && !(tokens[i].toUpperCase() === "END" && tokens[i + 1] === name)) i++;
            if (i >= tokens.length) throw new Error(`unterminated ${t} block`);
            i++;
          } else if (!layer && t === "LAYER") {
            layer = tokens[++i];
            if (!layer || layer === ";" || layer === "END") throw new Error("missing LAYER name");
            nlayers++; layerType = null;
          } else if (layer && t === "END") {
            if (tokens[++i] !== layer) throw new Error(`LAYER ${layer} END name mismatch: ${tokens[i]}`);
            if (!layerType) throw new Error("missing LAYER TYPE statement");
            layer = null;
          } else if (layer && t === "TYPE") {
            const kind = tokens[++i]?.toUpperCase();
            if (layerType || !["ROUTING", "CUT", "MASTERSLICE", "OVERLAP", "IMPLANT"].includes(kind)) throw new Error("invalid or duplicate LAYER TYPE");
            layerType = kind;
            if (tokens[++i] !== ";") throw new Error("malformed LAYER TYPE statement");
            if (kind === "ROUTING") nrouting++;
            if (kind === "CUT") ncut++;
          } else if (layer && t === "RESISTANCE") {
            i = endStatement(i + 1); nres++;
          }
        }
        if (layer) throw new Error("unterminated LAYER block");
        note("info", "tech_lef_layers", `${nlayers} layers (${nrouting} routing, ${ncut} cut)`);
        if (nrouting < 3) note("error", "tech_lef_routing_layers", `only ${nrouting} routing layers — too few`);
        if (nres === 0) note("warn", "tech_lef_resistance", "no RESISTANCE entries — eda_ir_drop will fail without via_resistance_ohm fallback");
      } catch (e) {
        note("error", "tech_lef_parse_unavailable", `LEF declarations were not measured: ${e.message}`);
      }
    }

    // 4. Cell LEF: macro count, SITE definitions
    const clRes = dockerExec(`grep -cE '^MACRO ' '${celllef}'; grep -cE '^SITE ' '${celllef}'`, 10000);
    const cl = (clRes.output || "").trim().split("\n");
    const nmacros = parseInt(cl[0]) || 0;
    const nsites = parseInt(cl[1]) || 0;
    note("info", "cell_lef_macros", `${nmacros} macros, ${nsites} sites`);
    if (nmacros < 30) note("warn", "cell_lef_macros", `${nmacros} macros — small library, check completeness`);

    // 5. GDS-LEF cell name match (sample)
    if (cellgds) {
      const gdsScript = `
import pya
ly = pya.Layout(); ly.read(${JSON.stringify(cellgds)})
names = sorted([c.name for c in ly.each_cell()])
print('GDS_CELL_COUNT=' + str(len(names)))
print('GDS_CELL_SAMPLE=' + ','.join(names[:10]))
`;
      const gdsTmp = `/tmp/pdk_lint_${Date.now()}_${Math.floor(Math.random() * 100000)}.py`;
      const gdsB64 = Buffer.from(gdsScript, "utf-8").toString("base64");
      const gdsWrite = dockerExec(`echo '${gdsB64}' | base64 -d > ${gdsTmp}`, 30000);
      const gdsRes = gdsWrite.success
        ? dockerExec(`${containerToolCommand("klayout", `${TOOLS}/klayout/klayout`)} -b -r ${gdsTmp} 2>&1`, 60000)
        : gdsWrite;
      const gdsMatch = (gdsRes.output || "").match(/^GDS_CELL_COUNT=(\d+)[ \t]*$/m);
      const gdsCount = gdsMatch ? Number(gdsMatch[1]) : null;
      if (!gdsRes.success || !Number.isSafeInteger(gdsCount)) {
        note("error", "gds_parse_unavailable", `GDS cell count was not measured: ${gdsRes.error || gdsRes.output || "missing parser output"}`);
      } else {
        note("info", "gds_cells", `${gdsCount} cells in GDS lib`);
        if (Math.abs(gdsCount - nmacros) > nmacros * 0.5) {
          note("warn", "gds_lef_count_mismatch", `GDS has ${gdsCount} cells but LEF has ${nmacros} macros — investigate`);
        }
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
// Retained compatibility wrapper for the pre-Flow109 Phase 2+3 diagnostic.
// The program still has value as a diagnostic, but this MCP entry accepts no
// Flow109 manifest or execution window.  Its result therefore cannot be
// published as current Flow109 authority.  Keep the legacy measurement under
// an explicitly scoped key and fail the current-flow claim closed.
//
// The gate used to be resolved under `vibe-ic-d`, the plugin Wave 82 retired.
// That path exists in NO layout — installed or checkout — so the tool never
// ran, and reported the miss as `phase23_complete:false`, which is the same
// shape a genuinely incomplete project produces. This file already calls
// vibe-ic-d "a plugin that no longer exists" where VIBE_IC_PROGRAMS_DIR is
// defined; that resolver (used by ~15 other program-backed tools) is correct
// in both layouts and is what the handler now uses.
//
// The host-side timeout is a BACKSTOP, not the budget. The gate's own budget
// is AUDIT_TIMEOUT_DEFAULT_S=900 .. AUDIT_TIMEOUT_CAP_S=3600
// (programs/_path_layout.py). The previous 300_000 ms was SHORTER than the
// inner budget, so the gate's own AUDIT_TIMEOUT branch could not be reached
// through this tool and a host-side kill surfaced as `exit_code:1` — again
// indistinguishable from a real FAIL verdict. 3_620_000 = AUDIT_TIMEOUT_CAP_S
// * 1000 + _INNER_TIMEOUT_GRACE_MS, so the inner kill always lands first —
// the same rule this file states for docker exec above.
server.tool(
  "eda_phase23_completion_audit",
  "Read the Router-selected native flow results and their original limits.",
  { project_dir: z.string().describe("Absolute project directory") },
  async ({ project_dir }) => {
    try {
      assertSafePath(project_dir, "project_dir");
      const reportPath = join(project_dir, "reports", "flow_engine.json");
      if (!existsSync(reportPath)) {
        return { content: [{ type: "text", text: JSON.stringify({
          status: "NOT_MEASURED", reason: "No native flow report", report_path: reportPath,
        }) }] };
      }
      const report = JSON.parse(readFileSync(reportPath, "utf-8"));
      return { content: [{ type: "text", text: JSON.stringify({
        report_path: reportPath, scope: "Router-selected window", ...report,
      }, null, 2) }] };
    } catch (e) { return guardError(e); }
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
