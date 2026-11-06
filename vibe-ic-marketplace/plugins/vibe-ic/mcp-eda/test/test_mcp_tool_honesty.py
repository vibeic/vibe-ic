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
from pathlib import Path

import pytest

import sys
for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402

INDEX_JS = Path(__file__).resolve().parent.parent / "src" / "index.js"
assert INDEX_JS.exists()
NODE = shutil.which("node")


def _invoke_registered_tool(name, params, gds_result=None):
    """Exercise the actual registered handler with controlled tool replies."""
    src = _src()
    marker = src.index('"' + name + '"')
    start = src.rfind('server.tool(', 0, marker)
    end = src.find('server.tool(', marker)
    block = src[start:end] if end >= 0 else src[start:]
    script = 'import {containerToolCommand} from ' + json.dumps((INDEX_JS.parent / 'lib/tool_path.mjs').as_uri()) + ';\n' + r'''
const calls = [];
let handler;
const chain = new Proxy(() => chain, { get: () => chain });
const server = {tool: (...args) => {handler = args.at(-1);}};
const z = chain;
const TOOLS = '/tools', PDK_ROOT = '/pdks', SERVER_VERSION = 'test';
const optPath = () => {}, assertSafePath = () => {}, optNoShellMeta = () => {};
const guardError = e => ({success:false,error:String(e)});
const wrapResult = x => x, _probeDocker = () => ({ok:true});
const magicPdkEnv = () => null;
const gdsResult = GDS_RESULT;
function dockerExec(cmd) {
  calls.push(cmd);
  if (cmd.includes('GDS_CELL_COUNT') || /klayout.* -r /.test(cmd))
    return gdsResult || {success:true,output:'INLINE_PYTHON_PROBE_COMPLETED'};
  if (cmd === "cat '/pdk/tech.lef'") return {success:true,output:'LAYER m1\nTYPE ROUTING ;\nEND m1\nLAYER m2\nTYPE ROUTING ;\nEND m2\nLAYER m3\nTYPE ROUTING ;\nEND m3'};
  if (cmd.includes('TYPE ROUTING')) return {success:true,output:'15\n6\n4\n20'};
  if (cmd.includes('^MACRO ')) return {success:true,output:'229\n1'};
  return {success:true,output:'240'};
}
TOOL_BLOCK
const result = await handler(PARAMS);
console.log(JSON.stringify({result,calls}));
'''.replace('GDS_RESULT', json.dumps(gds_result)).replace('TOOL_BLOCK', block).replace('PARAMS', json.dumps(params))
    r = _pr.run([NODE, '--input-type=module', '-e', script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _invoke_actual_dft_script(tmp_path, *, fail_stage=None, missing=False, missing_dependency=None):
    """Run the registered handler's assembled script with neutral tools.

    This checks quote transport and returned verdicts without running ATPG.
    PATH is restricted so a missing fixture tool cannot borrow a host binary.
    """
    native = tmp_path / "native"
    native.mkdir()
    tools = tmp_path / "tools"
    (tools / "bin").mkdir(parents=True)
    for name in ("mkdir", "cat"):
        (native / name).symlink_to(shutil.which(name))
    for name in ("iverilog", "yosys"):
        if name == missing_dependency:
            continue
        path = native / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    if not missing:
        path = tools / "bin/fault"
        path.write_text("#!/bin/sh\nprintf called > '" + str(tmp_path / "fault-called") + "'\n" + """
test -x "$FAULT_IVERILOG" && test -x "$FAULT_YOSYS" || exit 39
test "$1" != "$FAIL_STAGE" || { echo 'Error: requested Fault stage failed'; exit 42; }
case "$1" in
 chain) echo 'Total scan-chain length: 3';;
 atpg) echo 'Coverage 91.0%'; echo 'Compacted TV Count: 5';;
esac
""")
        path.chmod(0o755)
    src = _src()
    start = src.rfind("server.tool(", 0, src.index('"eda_dft"'))
    block = src[start:src.index("// ─── Tool: eda_ic_search", start)]
    script = r'''
import {spawnSync} from 'node:child_process';
import {containerToolCommand} from HELPER;
import * as safe from SAFETY;
let handler;
const chain = new Proxy(() => chain, {get: () => chain});
const z=chain, server={tool: (...args) => {handler=args.at(-1);}};
const {assertSafePath,assertSafeIdent,optPath,optNoShellMeta}=safe;
const guardError=e=>({success:false,error:String(e)});
const TOOLS=TOOLS_ROOT;
const pdkConfig=()=>({});
const manifests=[], calls=[];
const writeManifest=(dir,entry)=>manifests.push(entry);
function dockerExec(cmd) {
 calls.push(cmd);
 // Model the container's private /tmp with this test's own temporary root.
 const isolated=cmd.replaceAll('/tmp/combined_cells.v',COMBINED_CELLS);
 const r=spawnSync(BASH,['-c',isolated],{encoding:'utf8',env:{...process.env,PATH:NATIVE,FAIL_STAGE:FAIL_STAGE}});
 return {success:r.status===0,output:(r.stdout||'')+(r.stderr||'')};
}
BLOCK
const response=await handler(PARAMS);
console.log(JSON.stringify({metrics:JSON.parse(response.content[0].text),manifests,calls}));
'''
    values = {
        "HELPER": (INDEX_JS.parent / "lib/tool_path.mjs").as_uri(),
        "SAFETY": (INDEX_JS.parent / "lib/shell_safety.mjs").as_uri(),
        "TOOLS_ROOT": str(tools),
        "BASH": shutil.which("bash"), "NATIVE": str(native),
        "COMBINED_CELLS": str(tmp_path / "combined_cells.v"),
        "FAIL_STAGE": fail_stage or "",
        "PARAMS": {"netlist": "/neutral/netlist.v", "clock": "clk", "reset": "rst_n",
                   "reset_active_low": True, "pdk": "custom", "tv_count": 5,
                   "add_jtag": True, "output_dir": str(tmp_path / "dft"),
                   "custom_lib": "/neutral/cells.lib", "custom_dff_names": "NEUTRAL_DFF"},
    }
    # Substitute whole placeholders, so FAIL_STAGE in the JavaScript property
    # name and the literal fixture script remains intact.
    for key in ("HELPER", "SAFETY", "TOOLS_ROOT", "BASH", "NATIVE", "PARAMS", "COMBINED_CELLS"):
        script = script.replace(key, json.dumps(values[key]))
    script = script.replace("FAIL_STAGE:FAIL_STAGE", "FAIL_STAGE:" + json.dumps(values["FAIL_STAGE"]))
    script = script.replace("BLOCK", block)
    result = _pr.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_dft_actual_script_resolves_native_tools_and_preserves_shell_quotes(tmp_path):
    got = _invoke_actual_dft_script(tmp_path)
    assert got["metrics"]["success"] is True
    assert got["metrics"]["coverage_pct"] == 91.0
    assert got["metrics"]["jtag_added"] is True
    assert len(got["manifests"]) == 1


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("stage", ["chain", "cut", "atpg", "tap", None])
def test_dft_actual_script_missing_or_failed_fault_cannot_report_pass(tmp_path, stage):
    got = _invoke_actual_dft_script(tmp_path, fail_stage=stage, missing=stage is None)
    assert got["metrics"]["success"] is False
    assert got["manifests"] == []
    if stage != "tap":
        assert "ATPG_DONE" not in got["metrics"]["log_tail"]


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("dependency", ["iverilog", "yosys"])
def test_dft_missing_dependency_stops_before_fault_runs(tmp_path, dependency):
    got = _invoke_actual_dft_script(tmp_path, missing_dependency=dependency)
    assert got["metrics"]["success"] is False
    assert got["manifests"] == []
    assert not (tmp_path / "fault-called").exists()
    assert "tool unavailable in container: " + dependency in got["metrics"]["log_tail"]


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_operator_explicit_missing_path_is_not_replaced_by_native_path(tmp_path):
    native = tmp_path / "native"
    native.mkdir()
    marker = tmp_path / "native-called"
    path = native / "yosys"
    path.write_text("#!/bin/sh\nprintf called > '" + str(marker) + "'\n")
    path.chmod(0o755)
    command = "'" + str(tmp_path / "operator-missing/yosys") + "' -V"
    source = _src()
    start = source.index("function dockerExec(")
    consumer = source[start:source.index("\n}\n", start) + 3]
    script = "\n".join([
        "import {spawnSync} from 'node:child_process';",
        "const CONTAINER='neutral'; const _UNREACHABLE_HINTS=[]; const calls=[];",
        "const _probeDocker=()=>({ok:true}), _containerHasTimeout=()=>false;",
        "function _invalidateDockerProbe() {}",
        "function _spawnSync(bin,argv,opts) {calls.push(argv); return spawnSync(" + json.dumps(shutil.which("bash")) + ",['-c',argv.at(-1)],{...opts,env:{...process.env,PATH:" + json.dumps(str(native)) + "}});}",
        consumer,
        "const result=dockerExec(" + json.dumps(command) + "); console.log(JSON.stringify({result,calls}));",
    ])
    run = _pr.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got["calls"][0][-1] == command
    assert got["result"]["success"] is False
    assert got["result"]["exitCode"] == 127
    assert not marker.exists()


@pytest.mark.skipif(NODE is None, reason='node not installed')
@pytest.mark.parametrize('engine,suffix', [('klayout_python', '.py'), ('klayout_drc', '.drc')])
def test_inline_klayout_macro_has_native_interpreter_suffix(engine, suffix):
    result = _invoke_registered_tool('eda_run_tcl', {
        'engine': engine, 'script': 'print("INLINE_PYTHON_PROBE_COMPLETED")',
        'extra_args': [], 'timeout_sec': 30})
    assert result['result']['success'] is True
    assert result['result']['script_path'].endswith(suffix)
    assert result['result']['script_path'] in result['calls'][0]
    assert 'base64 -d' in result['calls'][0]


@pytest.mark.skipif(NODE is None, reason='node not installed')
@pytest.mark.parametrize('native', [
    {'success': False, 'output': 'macro interpreter unavailable'},
    {'success': False, 'output': 'GDS_CELL_COUNT=230'},
    {'success': True, 'output': 'parser emitted no measurement'},
])
def test_failed_gds_parser_never_reports_measured_zero(native):
    response = _invoke_registered_tool('eda_pdk_lint', {
        'lib': '/pdk/cells.lib', 'techlef': '/pdk/tech.lef',
        'celllef': '/pdk/cells.lef', 'cellgds': '/pdk/cells.gds',
        'cts_buf_list': []}, native)
    result = response['result']
    assert result['success'] is False
    assert any(r['check'] == 'gds_parse_unavailable' and r['severity'] == 'error'
               for r in result['findings'])
    assert not any(r['check'] == 'gds_cells' for r in result['findings'])


@pytest.mark.skipif(NODE is None, reason='node not installed')
@pytest.mark.parametrize('count', [0, 230])
def test_gds_parser_preserves_actual_counts_and_uses_python_macro(count):
    response = _invoke_registered_tool('eda_pdk_lint', {
        'lib': '/pdk/cells.lib', 'techlef': '/pdk/tech.lef',
        'celllef': '/pdk/cells.lef', 'cellgds': '/pdk/cells.gds',
        'cts_buf_list': []}, {'success': True, 'output': f'GDS_CELL_COUNT={count}\n'})
    assert response['result']['success'] is True
    assert any(r['check'] == 'gds_cells' and r['message'] == f'{count} cells in GDS lib'
               for r in response['result']['findings'])
    assert any('klayout' in c and '.py' in c and '/dev/stdin' not in c
               for c in response['calls'])

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
YOSYS_HIERARCHICAL = """=== hier_top ===
   Chip area for module '\\hier_top': 0.000000
=== leaf ===
   Chip area for module '\\leaf': 17.561600
=== design hierarchy ===
        2   35.123 hier_top
        2   35.123 cells
   Chip area for top module '\\hier_top': 35.123200
"""


def _src():
    return INDEX_JS.read_text()


def _eval_synth_stats(fixture, top):
    helper = INDEX_JS.parent / "lib" / "yosys_synth_stats.mjs"
    script = (
        "import {parseYosysSynthStats} from " + json.dumps(helper.as_uri()) + ";\n"
        + "console.log(JSON.stringify(parseYosysSynthStats("
        + json.dumps(fixture) + ", " + json.dumps(top) + ")));"
    )
    r = _pr.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ── eda_sta: the script must read a technology ───────────────────────────


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
        r = _pr.run([NODE, "--input-type=module", "-e", script],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    clean = _parse(STA_OK_CLOCKED)
    assert clean["wns"] == 0.0 and clean["tns"] == 0.0, clean
    bad = _parse(STA_OK_VIOLATING)
    assert bad["wns"] == -3.21 and bad["tns"] == -12.34, bad
    # the pole that matters: no such line at all is NOT MEASURED, never zero.
    assert _parse("nothing was analysed here") == {"wns": None, "tns": None}


# ── eda_synth: zero is a measurement, not an absence ─────────────────────
@pytest.mark.skipif(not NODE, reason="node not available")
def test_synth_reports_a_legitimate_zero_cell_count_as_zero():
    """`assign zero = 1'b0` is CORRECTLY zero cells. Reporting null there is
    indistinguishable from 'could not parse', which is how a correct synthesis
    got scored as a failure."""
    got = _eval_synth_stats(YOSYS_ZERO_CELLS, "zero_top")
    assert got["cells"] == 0, f"legitimate 0-cell design must report 0, got {got['cells']}"


@pytest.mark.skipif(not NODE, reason="node not available")
def test_synth_still_reports_real_cell_counts():
    """The zero fix must not blunt the normal path."""
    assert _eval_synth_stats(YOSYS_ONE_CELL, "comb_top")["cells"] == 1
    assert _eval_synth_stats(YOSYS_HIERARCHICAL, "hier_top")["cells"] == 2


@pytest.mark.skipif(not NODE, reason="node not available")
def test_synth_area_parses_flat_and_hierarchical_designs():
    """`Chip area for top module` appears only for a hierarchical design; a flat
    one prints `Chip area for module`, and used to read null."""
    assert _eval_synth_stats(YOSYS_ONE_CELL, "comb_top")["area_um2"] == 17.5616, "flat design area"
    # hierarchical: the top-module total must win over the per-module lines
    assert _eval_synth_stats(YOSYS_HIERARCHICAL, "hier_top")["area_um2"] == 35.1232, "top-module total"


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
