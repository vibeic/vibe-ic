#!/usr/bin/env python3
"""Tests for the 2026-08-27 MCP-EDA tool-honesty sweep.

Every fixture in this file is VERBATIM output captured from
`ghcr.io/vibeic/vibeic-eda@sha256:4ece6c01cddc99903af4f027326f7624b069311f2073a5a0b565d5a9cf649a16`
on 2026-08-27, not invented. What was measured:

  eda_sta could not produce a timing number and could not say so.
    * It read only the Liberty and the Verilog. OpenROAD needs a technology
      first, so `read_verilog` aborted ORD-2010, `link_design` failed STA-1570
      and every report failed STA-1571 -- on a perfectly good netlist.
    * openroad still exited 0. The verdict keyed on the exit code, so the tool
      reported success and wrote a manifest status "PASS" for a run in which
      nothing was linked.
    * `create_clock` on a port the design lacks only WARNs (STA-0366) and still
      makes a source-less clock, so a clockless design printed `wns max 0.00` --
      a perfect score for a design nothing constrained.
    * `report_wns` prints `wns max 0.00`; the old `/wns\\s+([\\d.-]+)/i` needed a
      digit straight after the label, so it matched neither a clean run nor a
      violating one. wns/tns were null on every path.

  eda_synth could not tell zero from unknown.
    * `stat -liberty` prints `<count> <area> cells` only when the count is
      non-zero; a legitimately constant design prints the bare `0 cells`, so the
      two-number pattern returned cells:null -- the same value as an unparseable
      run. `assign zero = 1'b0` is correctly zero cells, and got scored as if
      the count could not be read.
    * `Chip area for top module` is printed only for a HIERARCHICAL design; a
      flat one prints `Chip area for module`, so area_um2 was null for the whole
      flat class.

The behavioural tests pull the ACTUAL regex literals out of src/index.js and run
them under node against these fixtures, so reverting the fix in index.js turns
them red rather than leaving a comment-only assertion behind.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

INDEX_JS = Path(__file__).resolve().parent.parent / "src" / "index.js"
assert INDEX_JS.exists()
NODE = shutil.which("node")

# ── verbatim captures ────────────────────────────────────────────────────
# openroad, current-shape STA script (liberty + verilog, no LEF), rc=0
STA_NO_TECH = """[INFO ORD-0030] Using 4 thread(s).
[ERROR ORD-2010] no technology has been read.
ORD-2010
[ERROR STA-1570] No network has been linked.
STA-1570
[ERROR STA-1571] No network has been linked.
STA-1571
"""
# openroad, with the tech LEF + cell LEF read first, clocked design
STA_OK_CLOCKED = """[INFO ODB-0227] LEF file: .../gf180mcu_fd_sc_mcu7t5v0__nom.tlef, created 15 layers, 56 vias
STA_CLOCK_PORT_FOUND=1
tns max 0.00
wns max 0.00
STA_COMPLETE
"""
# same, but the design has NO clk port: create_clock matched nothing
STA_OK_CLOCKLESS = """[WARNING STA-0366] port 'clk' not found.
STA_CLOCK_PORT_FOUND=0
tns max 0.00
wns max 0.00
STA_COMPLETE
"""
STA_OK_VIOLATING = """STA_CLOCK_PORT_FOUND=1
tns max -12.34
wns max -3.21
STA_COMPLETE
"""

# yosys 0.68+ `stat -liberty` final blocks
YOSYS_ZERO_CELLS = """=== zero_top ===

        +----------Local Count, excluding submodules.
        | 
        1 wires
        1 ports
        0 cells
"""
YOSYS_ONE_CELL = """=== comb_top ===

        +----------Local Count, excluding submodules.
        |        +-Local Area, excluding submodules.
        |        | 
        4        - wires
        1   17.562 cells
        1   17.562   gf180mcu_fd_sc_mcu7t5v0__and2_1

   Chip area for module '\\comb_top': 17.561600
"""
YOSYS_HIERARCHICAL = """   Chip area for module '\\hier_top': 0.000000
   Chip area for module '\\leaf': 17.561600
   Chip area for top module '\\hier_top': 35.123200
        2   35.123 cells
"""


def _src():
    return INDEX_JS.read_text()


def _eval_match(expr_decls, fixture):
    """Run the real regex declarations from index.js against a fixture."""
    script = (
        "const result = { output: " + json.dumps(fixture) + " };\n"
        + expr_decls
        + "\nconsole.log(JSON.stringify({"
          "cells: (typeof cellMatch !== 'undefined' && cellMatch) ? parseInt(cellMatch[1]) : null,"
          "area: (typeof areaMatch !== 'undefined' && areaMatch) ? parseFloat(areaMatch[1]) : null,"
          "wns: (typeof wnsMatch !== 'undefined' && wnsMatch) ? parseFloat(wnsMatch[1]) : null,"
          "tns: (typeof tnsMatch !== 'undefined' && tnsMatch) ? parseFloat(tnsMatch[1]) : null"
          "}));"
    )
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed: {r.stderr}\n{script}"
    return json.loads(r.stdout)


def _extract(decl_start):
    """Pull a `const <name> = ...;` declaration (possibly multi-line) verbatim."""
    src = _src()
    i = src.index(decl_start)
    j = src.index(";\n", i)
    return src[i:j + 1]


# ── eda_sta: the script must read a technology ───────────────────────────
def test_sta_script_reads_a_technology():
    """Without a LEF, OpenROAD aborts ORD-2010 and links nothing. eda_ir_drop in
    this same file has always read techlef + celllef; STA was the outlier."""
    src = _src()
    assert "_staLefReads" in src, "eda_sta must read a technology before read_verilog"
    assert "const _staLefs = [techlefPath(cfg), celllefPath(cfg)]" in src


def test_sta_script_emits_completion_and_clock_sentinels():
    """openroad exits 0 even when every command failed, so the exit code cannot
    say whether the script ran. A positive end-of-script sentinel can."""
    src = _src()
    assert 'puts "STA_COMPLETE"' in src
    assert 'puts "STA_CLOCK_PORT_FOUND=[llength [get_ports -quiet ${clock_port}]]"' in src


def test_sta_verdict_is_not_the_exit_code():
    """`success` must come from staAnalysed (sentinel + no ORD/STA errors), and
    a run that linked nothing must not be able to write a PASS manifest."""
    src = _src()
    assert "const staAnalysed = result.success && staCompleted && staErrors.length === 0;" in src
    assert "success: staAnalysed," in src
    assert 'status: clockConstrained ? "PASS" : "UNCONSTRAINED",' in src


@pytest.mark.skipif(not NODE, reason="node not available")
def test_sta_error_regex_catches_openroad_errors():
    """The measured failure prints `[ERROR ORD-2010] ...` -- bracketed, no colon.
    The pre-existing _ERR_PATTERNS entry /^(?:Error|ERROR):/m does NOT match it."""
    decl = _extract("const staErrors = ")
    script = ("const result = { output: " + json.dumps(STA_NO_TECH) + " };\n"
              + decl + "\nconsole.log(staErrors.length);")
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert int(r.stdout.strip()) == 3, \
        f"must see all three ORD-2010/STA-1570/STA-1571 errors, saw {r.stdout.strip()}"

    clean = ("const result = { output: " + json.dumps(STA_OK_CLOCKED) + " };\n"
             + decl + "\nconsole.log(staErrors.length);")
    r2 = subprocess.run([NODE, "-e", clean], capture_output=True, text=True, timeout=30)
    assert int(r2.stdout.strip()) == 0, "a healthy run must report zero errors"


@pytest.mark.skipif(not NODE, reason="node not available")
def test_sta_slack_regex_matches_real_opensta_output():
    """`report_wns` prints `wns max 0.00`. The old pattern matched no run at all."""
    decls = _extract("const wnsMatch = ") + "\n" + _extract("const tnsMatch = ")
    clean = _eval_match(decls, STA_OK_CLOCKED)
    assert clean["wns"] == 0.0 and clean["tns"] == 0.0, clean
    bad = _eval_match(decls, STA_OK_VIOLATING)
    assert bad["wns"] == -3.21 and bad["tns"] == -12.34, bad


def test_sta_clockless_is_not_reported_as_zero_slack():
    """A design with no clk port still yields `wns max 0.00` from a source-less
    clock. That vacuous zero must not be handed back as a timing result."""
    src = _src()
    assert "const clockConstrained = staAnalysed && clockPortFound === true;" in src
    assert "const wns = clockConstrained && wnsMatch ? parseFloat(wnsMatch[1]) : null;" in src
    assert "const tns = clockConstrained && tnsMatch ? parseFloat(tnsMatch[1]) : null;" in src


@pytest.mark.skipif(not NODE, reason="node not available")
def test_sta_clockless_fixture_parses_as_unconstrained():
    """End-to-end on the clockless capture: the port count is 0, so no slack."""
    script = (
        "const result = { output: " + json.dumps(STA_OK_CLOCKLESS) + " };\n"
        + _extract("const clockPortMatch = ") + "\n"
        + "const clockPortFound = clockPortMatch ? parseInt(clockPortMatch[1]) > 0 : null;\n"
        + "console.log(JSON.stringify({found: clockPortFound}));"
    )
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["found"] is False, \
        "clockless capture must resolve clock_port_found=false"


# ── eda_synth: zero is a measurement, not an absence ─────────────────────
@pytest.mark.skipif(not NODE, reason="node not available")
def test_synth_reports_a_legitimate_zero_cell_count_as_zero():
    """`assign zero = 1'b0` is CORRECTLY zero cells. Reporting null there is
    indistinguishable from 'could not parse', which is how a correct synthesis
    got scored as a failure."""
    decl = _extract("const cellMatch = ")
    got = _eval_match(decl, YOSYS_ZERO_CELLS)
    assert got["cells"] == 0, f"legitimate 0-cell design must report 0, got {got['cells']}"


@pytest.mark.skipif(not NODE, reason="node not available")
def test_synth_still_reports_real_cell_counts():
    """The zero fix must not blunt the normal path."""
    decl = _extract("const cellMatch = ")
    assert _eval_match(decl, YOSYS_ONE_CELL)["cells"] == 1
    assert _eval_match(decl, YOSYS_HIERARCHICAL)["cells"] == 2


@pytest.mark.skipif(not NODE, reason="node not available")
def test_synth_area_parses_flat_and_hierarchical_designs():
    """`Chip area for top module` appears only for a hierarchical design; a flat
    one prints `Chip area for module`, and used to read null."""
    decl = _extract("const areaMatch = ")
    assert _eval_match(decl, YOSYS_ONE_CELL)["area"] == 17.5616, "flat design area"
    # hierarchical: the top-module total must win over the per-module lines
    assert _eval_match(decl, YOSYS_HIERARCHICAL)["area"] == 35.1232, "top-module total"


def test_synth_manifest_written_for_a_measured_zero():
    """`metrics.cells` is falsy at 0, so a legitimately zero-cell design was
    denied a manifest exactly like an unparseable one."""
    src = _src()
    assert "if (metrics.success && metrics.cells !== null) {" in src, \
        "synthesis manifest must gate on 'was it measured', not 'is it non-zero'"


# ── provenance identity: a version string is not identity, a digest is ───
def test_provenance_records_a_rederivable_tool_identity():
    """Every logProvenance call used to pass a HARDCODED literal - "yosys
    (mcp-eda) pdk=gf180" and six more - naming a tool but carrying no version
    and no image, so the record read identically across two different images
    holding two different builds. A tag was measured on 2026-08-27 naming two
    different images on two hosts; only a digest re-derives."""
    src = _src()
    assert "function containerImageIdentity()" in src
    assert "function toolIdentity(" in src
    # the repo digest is preferred over the local image id
    assert '"--format", "{{json .RepoDigests}}"' in src, \
        "identity must prefer the repo digest, which re-derives on another host"
    assert "ident = { image_ref: digest || imageId, image_id: imageId };" in src


def test_no_provenance_call_site_still_hardcodes_its_version():
    """A hardcoded `version:` literal cannot change when the tool or the image
    changes, so it can only ever drift away from what it names."""
    src = _src()
    import re as _re
    hardcoded = _re.findall(r"version: `[a-z][^`]*\(mcp-eda\)[^`]*`", src)
    assert not hardcoded, f"provenance call sites still hardcoding a version: {hardcoded}"
    # all seven sites go through the helper
    assert src.count("version: toolIdentity(") == 7, \
        f"expected 7 toolIdentity provenance sites, found {src.count('version: toolIdentity(')}"


def test_identity_cannot_silently_report_a_blank():
    """If docker cannot answer, the record must SAY so rather than carry a
    confident-looking empty string."""
    src = _src()
    assert 'image_ref: "unavailable (docker inspect failed)"' in src
    assert "ver = `unavailable (${e.message})`" in src


# ── the probe-locus guard: ask the environment the tool will RUN in ──────
# Swept 2026-08-27 across all of src/index.js: the MCP layer was CLEAN of the
# `shutil.which("magic")` shape (a host probe answering for a container tool),
# which was fixed plugin-side as 0d63fc4254. This guard keeps it clean.
#
# Container-resident tools, all probed via dockerExec at ${TOOLS}/...:
#   fault iverilog klayout magic netgen ngspice openroad verilator yosys
# Host-executed sites are lab hardware bolted to the host (a board programmer,
# an FPGA toolchain, a scope, ffmpeg), host-side document converters that
# eda_doc_extract genuinely runs on the host, or questions about the host's own
# docker group. None of them answers for a container tool.
_CONTAINER_TOOLS = ("yosys", "openroad", "klayout", "iverilog",
                    "verilator", "magic", "netgen", "ngspice", "fault")


def _host_exec_lines(src):
    """Lines that shell out on the HOST: argv[0] is neither docker nor python3."""
    import re
    out = []
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        m = re.search(r'(?:^|[^_\w])(?:_?execSync|_spawnSync)\(\s*"([^"]+)"', line)
        if m and m.group(1) not in ("docker", "python3"):
            out.append((i, line))
    return out


def test_no_host_probe_answers_for_a_container_tool():
    """A probe must ask the environment the tool will actually run in.

    `shutil.which("magic")` asked the HOST whether magic exists while magic
    lives in the CONTAINER, so the answer was about the wrong machine and a
    present tool read as absent. This asserts the MCP layer has no host-side
    exec naming any container-resident EDA tool."""
    import re
    src = _src()
    offenders = []
    for lineno, line in _host_exec_lines(src):
        for tool in _CONTAINER_TOOLS:
            if re.search(r"\b" + re.escape(tool) + r"\b", line):
                offenders.append(f"line {lineno}: host exec names container tool "
                                 f"'{tool}': {line.strip()[:110]}")
    assert not offenders, (
        "host-side probe answering for a container-resident tool:\n  "
        + "\n  ".join(offenders)
        + "\nProbe the environment the tool RUNS in (dockerExec), not this process.")


def test_container_tool_version_probes_run_in_the_container():
    """getToolVersion's probe table must reach the tools through the container,
    at the deterministic ${TOOLS} path -- never via an ambient host PATH."""
    src = _src()
    i = src.index("function getToolVersion(")
    table = src[i:src.index("const probe = probes[name];", i)]
    for tool in _CONTAINER_TOOLS:
        assert f"{tool}:" in table, f"{tool} missing from the version probe table"
    assert "${TOOLS}/" in table, "version probes must use the deterministic container path"
    # and the probe must be executed through dockerExec, not on the host
    body = src[i:src.index("_versionCache.set(name, v);", i)]
    assert "dockerExec(probe" in body, \
        "getToolVersion must run its probe inside the container"
