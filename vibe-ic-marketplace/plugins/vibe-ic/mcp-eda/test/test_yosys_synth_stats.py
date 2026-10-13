"""Selected-top stat parsing and the real eda_synth response/manifest consumer.

All committed logs are neutral, authored fixtures. Tool output replay below
does not execute Docker/Yosys and is not a new synthesis measurement.
"""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

MCP = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node unavailable")


def flat(top="chip_top", cells=2, area="3.25", marker="1. Printing statistics."):
    area_line = "" if area is None else f"   Chip area for module '\\{top}': {area}\n"
    return f"{marker}\n=== {top} ===\n\n   {cells} cells\n" + area_line


def hierarchy(top="chip_top", cells=6, area="12.5", root_cells=None):
    root_cells = cells if root_cells is None else root_cells
    return (
        "=== leaf_a ===\n   2 4.25 cells\n"
        "   Chip area for module '\\leaf_a': 4.25\n"
        f"=== {top} ===\n   2 0 cells\n   2 0 submodules\n"
        "=== design hierarchy ===\n"
        "   +----------Count including submodules.\n"
        f"   {root_cells} 1.25E+01 {top}\n"
        "   2 4.25   leaf_a\n   4 8.25   leaf_b\n"
        f"   {cells} 1.25E+01 cells\n"
        f"   Chip area for top module '\\{top}': {area}\n"
    )


def parse(output, top="chip_top"):
    script = (
        f"import {{parseYosysSynthStats}} from {json.dumps((MCP/'src/lib/yosys_synth_stats.mjs').as_uri())};\n"
        f"console.log(JSON.stringify(parseYosysSynthStats({json.dumps(output)}, {json.dumps(top)})));"
    )
    r = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.parametrize("log,cells,area", [
    (flat(cells=0, area=None), 0, None),
    (flat(cells=0, area="0.000000"), 0, 0),
    (flat(cells=1, area="17.561600"), 1, 17.5616),
    (flat(area="3.31E+04"), 2, 33100),
    (flat(area="1.25e-03"), 2, .00125),
    (hierarchy(), 6, 12.5),
    (flat(cells=99, area="99") + "2. Printing statistics.\n" + hierarchy(), 6, 12.5),
    (hierarchy() + "2. Executing STAT pass.\n" + flat(cells=3, area="7", marker=""), 3, 7),
    (flat() + "=== unrelated ===\n   999 cells\n   Chip area for module '\\unrelated': 999\n", 2, 3.25),
    ("=== chip_top ===\n   Number of cells: 7\n   Chip area for module '\\chip_top': 1e+2\n", 7, 100),
    ("=== design hierarchy ===\n   chip_top 1\n      leaf 2\n   Number of cells: 4\n   Chip area for top module '\\chip_top': 8\n", 4, 8),
])
def test_selected_population_and_numeric_formats(log, cells, area):
    assert parse(log) == {"cells": cells, "area_um2": area}


@pytest.mark.parametrize("log", [
    "",
    "Yosys failed before statistics\n",
    flat(top="other_top"),
    hierarchy(top="other_top"),
    flat() + "2. Printing statistics.\n=== other_top ===\n   9 cells\n",
    flat() + "2. Printing statistics.\n=== chip_top ===\n   1 wires\n",
    "=== chip_top ===\n   2 0 cells\n   2 0 submodules\n",
    "=== design hierarchy ===\n   5 0 other_top\n   2 0   chip_top\n   5 0 cells\n",
])
def test_missing_incomplete_or_other_top_never_borrows_count(log):
    assert parse(log) == {"cells": None, "area_um2": None}


def test_hierarchy_count_mismatch_is_unmeasured():
    assert parse(hierarchy(root_cells=9))["cells"] is None


@pytest.mark.parametrize("summary", ["-1 cells", "1e2 cells", "9007199254740992 cells", "2 cells\n3 cells"])
def test_invalid_or_ambiguous_counts_are_unmeasured(summary):
    assert parse("=== chip_top ===\n" + summary)["cells"] is None


def invoke_handler(output, top="chip_top", success=True, source_path=None):
    """Run the actual registration callback with replayed tool output.

    The producer boundary is explicitly controlled; response, manifest, and
    measured/not-measured provenance all come from the unmodified consumer.
    """
    src = Path(source_path or MCP / "src/index.js").read_text()
    marker = src.index('"eda_synth"')
    start = src.rfind("server.tool(", 0, marker)
    block = src[start:src.index("server.tool(", marker)]
    script = f"import {{parseYosysSynthStats}} from {json.dumps((MCP/'src/lib/yosys_synth_stats.mjs').as_uri())};\n" + r'''
let handler;
const chain = new Proxy(() => chain, {get: () => chain});
const z = chain, server = {tool: (...args) => {handler = args.at(-1);}};
const TOOLS = '/tools';
const assertSafePaths = () => {}, assertSafePath = () => {}, assertSafeIdent = () => {};
const optPath = () => {}, optToken = () => {}, optIdent = () => {};
const guardError = e => ({success:false,error:String(e)});
const missingInContainer = () => [], pdkConfig = () => ({}), libPath = () => '/pdk/cells.lib';
const buildHilomapClause = () => ({clause:'',tie:{}});
const canonicalizeNetlistSrcCoords = () => {}, sha256File = () => null;
const getToolVersionSafe = () => 'replay', containerImageIdentity = () => ({image_ref:'replay'});
const toolIdentity = () => 'replay';
const manifests = [], provenance = [], calls = [];
const writeManifest = (dir, entry) => manifests.push(entry);
const measurementRecord = x => x, logProvenance = x => provenance.push(x);
const dockerExec = cmd => {calls.push(cmd); return TOOL_REPLY;};
TOOL_BLOCK
const response = await handler({verilog_files:['/input/chip.v'],top_module:TOP,
 output_netlist:'/output/chip.v',pdk:'custom',sv_mode:true});
console.log(JSON.stringify({metrics:JSON.parse(response.content[0].text),manifests,provenance,calls}));
'''.replace("TOOL_REPLY", json.dumps({"success": success, "output": output})).replace("TOOL_BLOCK", block).replace("TOP", json.dumps(top))
    r = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.parametrize("log,cells,area", [(hierarchy(), 6, 12.5), (flat(cells=0, area=None), 0, None)])
def test_actual_handler_response_and_manifest_use_selected_metrics(log, cells, area):
    got = invoke_handler(log)
    assert got["metrics"]["cells"] == cells
    assert got["metrics"]["area_um2"] == area
    assert got["manifests"][0]["cells"] == cells
    assert got["manifests"][0]["area_um2"] == area
    assert got["provenance"][0]["measurement"]["measured"] is True
    assert len(got["calls"]) == 1  # Replay only: no real EDA process is invoked.


@pytest.mark.parametrize("log,success", [(flat(top="other_top"), True), ("ERROR: failed", False)])
def test_actual_handler_refuses_measurement_and_manifest_without_selected_count(log, success):
    got = invoke_handler(log, success=success)
    assert got["metrics"]["cells"] is None
    assert got["manifests"] == []
    assert got["provenance"][0]["measurement"]["measured"] is False
