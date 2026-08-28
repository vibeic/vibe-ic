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
import re
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


def _eda_sta_region(src):
    """Just the eda_sta tool body, so an unrelated tool's line cannot satisfy
    or violate an assertion about STA."""
    i = src.index('"eda_sta"')
    j = src.index('"eda_lvs"', i)
    return src[i:j]


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
    # The declaration existing is not the fix. It must be INTERPOLATED INTO the
    # STA script, AHEAD of read_liberty/read_verilog -- deleting the
    # interpolation restores ORD-2010 while leaving the declaration in place,
    # and that mutation used to pass this test.
    # Scope to the emitted STA script itself: the tool body contains other
    # read_verilog occurrences, and comparing against those would compare the
    # wrong two things.
    region = _eda_sta_region(src)
    # The Tcl is a FILE ARGUMENT now, so the script body is the `staTcl`
    # template literal rather than a heredoc ending in ``EOF`;``. Same region,
    # same property.
    a = region.index("const staTcl = ")
    script = region[a:region.index("`;", a)]
    assert "${_staLefReads}" in script, \
        "the LEF reads are declared but never interpolated into the STA script; " \
        "that is ORD-2010 with the evidence of a fix still in the file"
    assert script.index("${_staLefReads}") < script.index("read_verilog "), \
        "the technology must be read BEFORE read_verilog, or ORD-2010 returns"
    assert script.index("${_staLefReads}") < script.index("read_liberty "), \
        "read_lef must precede read_liberty in the emitted script"


def test_sta_script_emits_completion_and_clock_sentinels():
    """openroad exits 0 even when every command failed, so the exit code cannot
    say whether the script ran. A positive end-of-script sentinel can."""
    src = _src()
    assert 'puts "STA_COMPLETE"' in src
    assert 'puts "STA_CLOCK_PORT_FOUND=[llength [get_ports -quiet ${clock_port}]]"' in src


def _sta_verdict_terms() -> str:
    """The four declarations that decide `staAnalysed`, verbatim from index.js."""
    return "\n".join([
        _extract("const staCompleted = "),
        _extract("const staFailed = "),
        _extract("const staAnalysed = "),
    ])


def _openroad_run_failed() -> str:
    src = _src()
    i = src.index("function openroadRunFailed(")
    return src[i:src.index("\n}\n", i) + 3]


@pytest.mark.skipif(not NODE, reason="node not available")
def test_sta_verdict_is_not_the_exit_code():
    """A run in which no timing was analysed must not come back analysed.

    THIS TEST ASSERTS THE PROPERTY, NOT THE SPELLING. It used to pin the exact
    source text of `staAnalysed`, and two independently correct fixes to this
    same tool then became unlandable together purely because one pinned a
    literal the other had to delete. The literal is gone; what is checked here
    is behaviour, by lifting the real declarations out of index.js and running
    them under node against captured shapes. Any rewrite that keeps the meaning
    passes; any rewrite that drops a channel goes red.

    TWO MACHINE CHANNELS, MEASURED WRONG IN OPPOSITE DIRECTIONS, SO NEITHER
    MAY STAND ALONE. Measured 2026-08-27 in the pinned eda image
    (b8ac631e48b6, openroad 26Q3-1830-g0ac0d5ba44):

        script                    mode   rc  sentinel  flow__errors__count
        read_verilog, no tech     file    1     no             1
        read_verilog, no tech     stdin   0    YES             3
        utl::error inside a catch file    0    YES             1
        set x [expr {1/0}]        file    1     no             0
        set x [expr {1/0}]        stdin   0    YES             0

    Row 4 is seen by the exit code alone; rows 2 and 3 are seen by the counter
    alone. Row 5 is the reason the Tcl must be a file argument at all -- on
    stdin a script that died at its first command exits 0, prints the
    end-of-script sentinel, and reports zero errors. The end-of-script sentinel
    is corroboration only: it may subtract, never add.
    """
    cases = [
        # name, output, rc, errorCount, expected staAnalysed
        ("the original bug: nothing linked, rc 0, sentinel printed, 3 errors",
         STA_NO_TECH + 'STA_COMPLETE\n', 0, 3, False),
        ("a Tcl error the counter cannot see: rc 1 with a count of 0",
         "", 1, 0, False),
        ("an abort the exit code and the counter both see",
         STA_NO_TECH, 1, 1, False),
        ("utl::error inside a catch: rc 0 and the sentinel, but the count moved",
         "[ERROR STA-1570] No network has been linked.\nSTA_COMPLETE\n", 0, 1, False),
        ("clean rc and counter, but the script never reached the end",
         "tns max 0.00\nwns max 0.00\n", 0, 0, False),
        ("a healthy clocked run", STA_OK_CLOCKED, 0, 0, True),
        # THE CONTROL. A gate that refused this would be a refusal machine, not
        # a fix: a real timing violation raises nothing and completes normally.
        ("a genuine timing VIOLATION is analysed, not refused",
         STA_OK_VIOLATING, 0, 0, True),
        # No sidecar at all (the standalone `sta` binary has no -metrics flag):
        # UNKNOWN must not fail this channel on its own -- lib/sta_evidence.mjs
        # is what records an absent sidecar as UNMEASURED, and staPass ANDs it.
        ("no metrics sidecar: unknown count does not decide here",
         STA_OK_CLOCKED, 0, None, True),
    ]
    script = (
        _openroad_run_failed()
        + "\nfunction verdict(output, rc, errorCount) {\n"
        + "  const result = { output };\n"
        + "  const staRun = { rc, errorCount };\n"
        + _sta_verdict_terms()
        + "\n  return staAnalysed;\n}\n"
        + "const cases = " + json.dumps([[c[1], c[2], c[3]] for c in cases]) + ";\n"
        + "console.log(JSON.stringify(cases.map(c => verdict(c[0], c[1], c[2]))));"
    )
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed: {r.stderr}\n{script}"
    got = json.loads(r.stdout)
    for (name, _out, _rc, _n, want), actual in zip(cases, got):
        assert actual is want, (
            f"staAnalysed for {name!r} was {actual}, expected {want}. "
            "A channel was dropped from the verdict, or one refuses work it "
            "should let through.")


def test_the_sta_verdict_is_the_conjunction_of_both_channels():
    """`staAnalysed` is ONE term. The reported success is it ANDed with the
    independent metrics-sidecar conjunction from lib/sta_evidence.mjs, and the
    raw dockerExec exit status is not read by this tool at all."""
    src = _src()
    region = _eda_sta_region(src)
    assert "const staPass = staAnalysed && staEvidence.pass;" in src, \
        "the conjunction was demoted to a single channel"
    assert "success: staPass," in src
    # The ORIGINAL BUG was reporting dockerExec's own view of the exit status as
    # this tool's verdict. Stated as a property rather than as a banned literal:
    # eda_sta does not read that field ANYWHERE. `staRun.rc` -- the status the
    # tool really returned, parsed back out of the container -- is what it reads.
    assert "result.success" not in region, \
        "eda_sta is reading dockerExec's own exit status again; that field was " \
        "a constant 0 while the Tcl went in on stdin, and it is the original bug"
    # The exit code and the error tally are conjoined; neither decides alone.
    assert 'return rc !== 0 || (typeof errorCount === "number" && errorCount > 0);' in src


@pytest.mark.skipif(not NODE, reason="node not available")
def test_the_sta_manifest_status_distinguishes_pass_violation_and_unconstrained():
    """The manifest is what downstream flow steps read, so all three outcomes
    have to reach it. MEASURED 2026-08-27: a 40-deep chain at 0.5 ns returned
    wns -12.10 ns and was still manifested PASS, because the status keyed only
    on whether a clock had been found."""
    region = _eda_sta_region(_src())
    m = re.search(r'status: (clockConstrained[\s\S]*?),\n\s*tool: "OpenSTA"', region)
    assert m, "the eda_sta manifest no longer has a clockConstrained-gated status"
    expr = m.group(1)
    # A FOURTH ARM, 2026-08-28. The measurement contract adds one outcome the
    # three above cannot express: a run that legitimately had NOTHING to
    # measure. It is not a PASS (no slack was measured) and it is not
    # UNCONSTRAINED (nothing was left unconstrained -- there was never anything
    # to constrain). Collapsing it into UNCONSTRAINED makes this gate refuse
    # every purely combinational design, and a gate that refuses everything
    # gets bypassed. This asserts all FOUR arms, so it is strictly harder to
    # satisfy than the three-arm form it replaces.
    script = (
        'const NOT_MEASURED_BENIGN = "NOTHING_TO_MEASURE";\n'
        "const f = (clockConstrained, wns, staClass) => (" + expr + ");\n"
        "console.log(JSON.stringify(["
        "f(true, 8.43, null), f(true, -12.10, null),"
        ' f(false, null, "UNCONSTRAINED"),'
        ' f(false, null, "NOTHING_TO_MEASURE")]));'
    )
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed: {r.stderr}\n{script}"
    assert json.loads(r.stdout) == ["PASS", "TIMING_VIOLATED", "UNCONSTRAINED",
                                    "NOTHING_TO_MEASURE"], \
        "the manifest status lost an arm: a missed slack, an unconstrained " \
        "run, or a run with nothing to measure is being written as PASS — or " \
        "the last two have been collapsed into one another, which is wrong in " \
        "both directions"


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
    # ASSEMBLY: the inline regex was superseded by lib/sta_slack.mjs, which is
    # anchored at both ends, accepts the bare `wns <n>` form and scientific
    # notation, and prefers the `max` (setup) corner. Exercise the module that
    # actually ships, on the same real captures.
    import os
    lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "src", "lib", "sta_slack.mjs")
    assert os.path.exists(lib), lib

    def _parse(fixture):
        script = ("import { parseWns, parseTns } from " + json.dumps(lib) + ";\n"
                  "const out = " + json.dumps(fixture) + ";\n"
                  "console.log(JSON.stringify({wns: parseWns(out), tns: parseTns(out)}));")
        r = subprocess.run([NODE, "--input-type=module", "-e", script],
                           capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    clean = _parse(STA_OK_CLOCKED)
    assert clean["wns"] == 0.0 and clean["tns"] == 0.0, clean
    bad = _parse(STA_OK_VIOLATING)
    assert bad["wns"] == -3.21 and bad["tns"] == -12.34, bad
    # the pole that matters: no such line at all is NOT MEASURED, never zero.
    assert _parse("nothing was analysed here") == {"wns": None, "tns": None}


def test_sta_clockless_is_not_reported_as_zero_slack():
    """A design with no clk port still yields `wns max 0.00` from a source-less
    clock. That vacuous zero must not be handed back as a timing result.

    2026-08-27: constrainedness is no longer inferred from a printed port
    count. MEASURED on a clockless netlist, the clock `create_clock` invents is
    genuinely VIRTUAL, so `is_virtual` over `all_clocks` is a direct truth we
    can ask the timer for instead of reading a warning out of the log. Same
    property, asked of the design database rather than of prose."""
    src = _src()
    assert "const clockConstrained = staAnalysed && constrained === true;" in src
    # constrainedness = real paths AND at least one clock AND none of them virtual
    assert "facts.timing_paths > 0 && facts.clocks > 0 && facts.virtual_clocks === 0" in src
    # A vacuous zero must never reach `wns`/`tns`: both stay gated on
    # clockConstrained. The number itself is read by lib/sta_slack.mjs, whose
    # whole-line parser supersedes the inline regex — see
    # test_sta_slack_regex_matches_real_opensta_output.
    assert "const wns = clockConstrained" in src
    assert "const tns = clockConstrained ? parseTns(result.output) : null;" in src


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


def test_the_verdict_does_not_borrow_evidence_a_run_never_produced():
    """ASSEMBLY. Two evidence channels were merged onto this tool. If the script
    never reached STA_COMPLETE it produced no timing evidence at all, so the
    reported verdict must NOT be whatever the metrics channel happened to say --
    the metrics file can be present and clean on a run that linked nothing.
    Collapsing this to `staEvidence.verdict` is the mutation this pins."""
    src = _src()
    region = _eda_sta_region(src)
    assert "const staVerdict = staAnalysed" in region, \
        "the verdict is not conditioned on the script having run"
    assert '(staErrors.length ? "FAIL" : "UNMEASURED")' in region, \
        "a run that produced no evidence must report FAIL or UNMEASURED, " \
        "never a verdict inherited from the other channel"
    assert "const staVerdict = staEvidence.verdict;" not in region
    # and the verdict that is written and returned must be that one.
    assert "status: staVerdict," in region
    assert "sta_verdict: staVerdict," in region
