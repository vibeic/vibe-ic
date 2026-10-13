"""Selected-top stat parsing and the real eda_synth response/manifest consumer.

Replay fixtures do not execute Docker/Yosys. The separate native controls run
the original callback's command with image-local Yosys and authored RTL/Liberty.
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


@pytest.mark.parametrize('mutation', ['incomplete','extra_table','duplicate_summary'])
def test_native_hierarchy_tables_do_not_borrow_or_choose_an_ambiguous_summary(mutation):
    columns = '        +----------Count including submodules.\n        |        +-Area including submodules.\n'
    first = '=== cells ===\n   0 cells\n=== design hierarchy ===\n'+columns+'        2        3 cells\n        2        3 leaf_unit\n'
    second = columns+'        2        3 cells\n        1        3 submodules\n        1        3   leaf_unit\n'
    if mutation=='incomplete':
        output = first
    elif mutation=='extra_table':
        output = first+second+columns+'        2        3 cells\n'
    else:
        output = first+second+'        2        3 cells\n'
    output += "   Chip area for top module '\\cells': 3\n"
    got = invoke_handler(output,top='cells')
    assert got['provenance'][0]['measurement']['measured'] is False
    assert got['metrics']['cells'] is None
    assert got['manifests']==[]


def invoke_handler(output, top="chip_top", success=True, source_path=None, native=None):
    """Run the actual registration callback with replay or native providers.

    The producer boundary is explicitly controlled; response, manifest, and
    measured/not-measured provenance all come from the unmodified consumer.
    """
    src = Path(source_path or MCP / "src/index.js").read_text()
    marker = src.index('"eda_synth"')
    start = src.rfind("server.tool(", 0, marker)
    block = src[start:src.index("server.tool(", marker)]
    script = f"import {{parseYosysSynthStats}} from {json.dumps((MCP/'src/lib/yosys_synth_stats.mjs').as_uri())};\n" \
        + f"import * as safe from {json.dumps((MCP/'src/lib/shell_safety.mjs').as_uri())};\n" + r'''
import {spawnSync} from 'child_process';
import fs from 'fs';
let handler;
const native = NATIVE;
const chain = new Proxy(() => chain, {get: () => chain});
const z = chain, server = {tool: (...args) => {handler = args.at(-1);}};
const TOOLS = native ? '/foss/tools' : '/tools';
const {assertSafePaths,assertSafePath,assertSafeIdent,optPath,optToken,optIdent} = safe;
const guardError = e => ({success:false,error:String(e)});
const missingInContainer = files => native ? files.filter(f => !fs.existsSync(f)) : [];
const pdkConfig = () => ({}), libPath = () => native ? native.lib : '/pdk/cells.lib';
const buildHilomapClause = () => ({clause:'',tie:{}});
const canonicalizeNetlistSrcCoords = () => {}, sha256File = () => null;
const getToolVersionSafe = () => native ? spawnSync('yosys',['-V'],{encoding:'utf8'}).stdout.trim() : 'replay';
const containerImageIdentity = () => ({image_ref:native ? (process.env.VIBEIC_EDA_IMAGE || 'image-local-native') : 'replay'});
const toolIdentity = () => getToolVersionSafe();
const manifests = [], provenance = [], calls = [], native_execution = [];
const writeManifest = (dir, entry) => manifests.push(entry);
const measurementRecord = x => x, logProvenance = x => provenance.push(x);
const dockerExec = cmd => {
  calls.push(cmd);
  if (!native) return TOOL_REPLY;
  const run = spawnSync('bash',['-lc',cmd],{encoding:'utf8',timeout:60000});
  const output = (run.stdout || '') + (run.stderr || '');
  fs.writeFileSync(native.log, output);
  native_execution.push({argv:['bash','-lc',cmd],returncode:run.status});
  return {success:run.status === 0,output};
};
TOOL_BLOCK
const response = await handler({verilog_files:[native ? native.source : '/input/chip.v'],top_module:TOP,
 output_netlist:native ? native.netlist : '/output/chip.v',pdk:'custom',sv_mode:true,
 custom_lib:native ? native.lib : undefined});
console.log(JSON.stringify({metrics:JSON.parse(response.content[0].text),manifests,provenance,calls,native_execution}));
'''.replace("TOOL_REPLY", json.dumps({"success": success, "output": output})).replace("TOOL_BLOCK", block).replace("TOP", json.dumps(top)).replace("NATIVE", json.dumps(native))
    if native:
        Path(native['log']).with_name('callback.mjs').write_text(script)
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


NEUTRAL_LIB = '''library(neutral) {
 delay_model : table_lookup;
 time_unit : "1ns"; voltage_unit : "1V"; current_unit : "1mA";
 capacitive_load_unit(1,pf);
 cell(INV) { area:1; pin(A) {direction:input; capacitance:1;} pin(Y) {direction:output; function:"!A";} }
 cell(BUF) { area:0.5; pin(A) {direction:input; capacitance:1;} pin(Y) {direction:output; function:"A";} }
 cell(AND2) { area:2; pin(A) {direction:input; capacitance:1;} pin(B) {direction:input; capacitance:1;} pin(Y) {direction:output; function:"A & B";} }
 cell(NAND2) { area:1.5; pin(A) {direction:input; capacitance:1;} pin(B) {direction:input; capacitance:1;} pin(Y) {direction:output; function:"!(A & B)";} }
 cell(OR2) { area:2; pin(A) {direction:input; capacitance:1;} pin(B) {direction:input; capacitance:1;} pin(Y) {direction:output; function:"A | B";} }
}'''


@pytest.mark.skipif(shutil.which('yosys') is None, reason='native Yosys unavailable')
@pytest.mark.parametrize('case,top,leaf', [
    ('hierarchy','chosen_top','leaf_unit'),
    ('top_cells','cells','leaf_unit'),
    ('leaf_cells','chosen_top','cells'),
    ('flat_zero','zero_top',None),
], ids=['hierarchy','top_cells','leaf_cells','flat_zero'])
def test_native_callback_matches_selected_mapped_population(tmp_path, case, top, leaf):
    source, lib, netlist = tmp_path/f'{case}.v', tmp_path/'neutral.lib', tmp_path/'mapped.v'
    if leaf:
        source.write_text(f'module {leaf}(input a,b,output [1:0] y); assign y[0]=a&b; assign y[1]=~a; endmodule\n'
                          f'module {top}(input a,b,output [1:0] y); {leaf} unit(a,b,y); endmodule\n')
    else:
        source.write_text(f'module {top}(output y); assign y=1\'b0; endmodule\n')
    lib.write_text(NEUTRAL_LIB)
    got = invoke_handler('',top=top,native={
        'source':str(source),'lib':str(lib),'netlist':str(netlist),'log':str(tmp_path/'native.log')})
    assert got['native_execution'][0]['returncode']==0, got
    commands = f'read_liberty -lib {lib}; read_verilog {netlist}; hierarchy -top {top}; flatten; write_json {tmp_path/"mapped.json"}'
    reference = subprocess.run(['yosys','-p',commands],capture_output=True,text=True,timeout=60)
    (tmp_path/'reference.log').write_text(reference.stdout+reference.stderr)
    assert reference.returncode==0, reference.stderr
    mapped = json.loads((tmp_path/'mapped.json').read_text())['modules'][top]['cells']
    areas = {'INV':1,'BUF':.5,'AND2':2,'NAND2':1.5,'OR2':2}
    assert all(cell['type'] in {*areas,'$scopeinfo'} for cell in mapped.values())
    # Flatten's source metadata cell has no hardware population or Liberty area.
    mapped = {name:cell for name,cell in mapped.items() if cell['type']!='$scopeinfo'}
    expected_cells = len(mapped)
    expected_area = sum(areas[cell['type']] for cell in mapped.values())
    (tmp_path/'native-values.json').write_text(json.dumps({
        **got,'reference_cells':expected_cells,'reference_area':expected_area},indent=2)+'\n')
    assert expected_cells==(2 if leaf else 0)
    assert got['metrics']['success'] is True
    assert got['provenance'][0]['measurement']['measured'] is True
    assert got['metrics']['cells']==expected_cells, got
    if leaf:
        assert got['metrics']['area_um2']==expected_area==3
    else:
        assert got['metrics']['area_um2'] is None
    assert len(got['manifests'])==1, got
    assert got['manifests'][0]['cells']==got['metrics']['cells']
    assert got['manifests'][0]['area_um2']==got['metrics']['area_um2']
    assert got['manifests'][0]['status']=='PASS'
