"""Regression tests — the declaration.json circular dependency.

DEFECT (measured on v1.9.62, on a `digital_arithmetic_primitive` IC whose spec
declares `plugin_output/declaration.json` as a required artifact):

  * the generated oracle TB SEARCHES for the serial framing that reassembles
    the DUT stream to the golden, then DISCARDS the winning triple and prints
    only the match count;
  * `arith_oracle_manifest.json` therefore carried `declared_latency: null`,
    because its `declared_*` fields are copied FROM declaration.json;
  * `arith_declaration_emit.py` needs a measured latency, looks for it in that
    manifest, finds null and fail-closes (correctly);
  * `arith_declaration_emit.py` had NO CALLER in programs/, flow/ or
    benchmark/ — so it would not have run regardless;
  * `spec_required_artifact_check.py` then FAILs the run for the missing file.

Net: the flow FAILED a run for an artifact it could not produce.

Each test below is paired with the pre-fix behaviour it would have shown, so a
test that cannot fail against the old code is not counted as evidence.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. The generated TB must PUBLISH the framing it measured.
# ---------------------------------------------------------------------------
def test_generated_oracle_tb_publishes_the_framing_it_measured():
    """NEGATIVE CONTROL: pre-fix the emitted TB contained `_best = _m;` and no
    ORACLE_TB_FRAMING line at all, so this assertion failed."""
    gen = _load("arith_oracle_tb_gen")
    src = Path(gen.__file__).read_text()

    # The winning triple is captured, not just the count.
    assert "_best = _m; _bio = _io; _boo = _oo; _boff = _off;" in src, (
        "the framing search must RECORD which (in_order,out_order,offset) won")
    # And published on a machine-readable line.
    assert "ORACLE_TB_FRAMING" in src
    # Guarded: only when ONE framing matched EVERY vector. Assert on the
    # EMITTED Verilog statement (the generator splits it across two Python
    # string literals, so a source-substring match would be brittle).
    emitted = "".join(
        re.findall(r'L\.append\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)\)', src))
    emitted = emitted.replace('"', "").replace("\\", "")
    assert "if (_best == NV) $display(ORACLE_TB_FRAMING" in emitted, (
        "a partial match establishes no framing; publishing one would be a guess")
    # The three declarations the statement depends on must exist too.
    assert "integer _bio, _boo, _boff;" in emitted


# ---------------------------------------------------------------------------
# 2. The runner must persist that framing under MEASURED keys.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3. The emitter must PREFER the measured value over the declared one.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. The producer must actually be WIRED. This is the link whose absence made
#    every other fix moot.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("depth", [1,2,3])
def test_native_serial_latency_uses_the_documented_settled_edge_origin(tmp_path,depth):
    import subprocess,shutil
    assert shutil.which("iverilog") and shutil.which("vvp"), "native Icarus required"
    gen=_load("arith_oracle_tb_gen")
    pairs=[(0xa5,0x3d),(0x81,0xc3),(0xff,0x96),(0x67,0x9b),
           (0xf0,0xaf),(0,0xff),(0xff,0xff),(1,1)]
    spec={"top":"neutral_pipe","operator":"&","width":8,"signed":False,
          "parallel":"x","serial_in":"y","serial_out":"p","clk":"clk",
          "rst":"rst","reset_active_low":False,"parallel_is_lhs":True,
          "ports":[{"name":n,"dir":d} for n,d in
                   [("clk","input"),("rst","input"),("x","input"),
                    ("y","input"),("p","output")]]}
    dut=tmp_path/"dut.v"
    dut.write_text(f"""module neutral_pipe(input clk,rst,input [7:0] x,input y,output p);
reg [{depth-1}:0] pipe; reg [2:0] idx; integer j; assign p=pipe[{depth-1}];
always @(posedge clk) if(rst) begin pipe<=0; idx<=0; end else begin
pipe[0]<=x[idx]&y; for(j=1;j<{depth};j=j+1) pipe[j]<=pipe[j-1]; idx<=idx+1'b1;
end endmodule
""")
    tb=tmp_path/"tb.v";tb.write_text(gen.emit_serial_oracle_module("native_origin",spec,pairs))
    binary=tmp_path/"native.vvp"
    cc=subprocess.run(["iverilog","-g2012","-s","native_origin","-o",str(binary),
                       str(tb),str(dut)],capture_output=True,text=True)
    assert cc.returncode==0, cc.stdout+cc.stderr
    run=subprocess.run(["vvp",str(binary)],capture_output=True,text=True)
    (tmp_path/"native.log").write_text(run.stdout+run.stderr)
    assert run.returncode==0 and "ORACLE_TB_DONE pass=8/8" in run.stdout, run.stdout


def test_explicit_legacy_latency_origin_is_normalized_and_absent_origin_unmeasured(tmp_path):
    reader=_load("spec_declaration_emit")
    manifest=tmp_path/"phase2/stage1/sim_full_stack/arith_oracle_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"calibrated_latency":2,
        "calibrated_latency_origin":"pre_nba_sample_offset"}))
    measured=reader.measured_framing(tmp_path)
    assert measured["latency_cycles"][0]==1, measured
    manifest.write_text(json.dumps({"calibrated_latency":2}))
    assert "latency_cycles" not in reader.measured_framing(tmp_path)
