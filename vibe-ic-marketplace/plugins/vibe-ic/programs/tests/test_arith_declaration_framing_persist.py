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
def test_runner_persists_measured_framing_not_declared(tmp_path):
    d = _load("design_one_shot_runner")
    sim = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True)
    manifest = sim / "arith_oracle_manifest.json"
    manifest.write_text(json.dumps({
        "program": "arith_oracle_tb_gen",
        "declared_bit_order": None,      # the pre-fix state
        "declared_latency": None,
    }))

    d._persist_oracle_calibrated_framing(
        tmp_path,
        "ORACLE_TB_DONE pass=28/28\n"
        "ORACLE_TB_FRAMING in_order=0 out_order=0 latency_cycles=2\n")

    got = json.loads(manifest.read_text())
    assert got["calibrated_bit_order"] == "LSB_first"
    assert got["calibrated_out_bit_order"] == "LSB_first"
    assert got["calibrated_latency"] == 2
    # The measured value must NOT be written into the declared_* keys: those
    # mean "what declaration.json said", and conflating them would recreate the
    # cycle in the opposite direction.
    assert got["declared_latency"] is None
    assert "NOT copied from declaration.json" in got["calibrated_source"]


def test_persist_is_a_noop_without_the_marker(tmp_path):
    """MSB-first / no-single-framing runs must not acquire a fabricated value."""
    d = _load("design_one_shot_runner")
    sim = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True)
    manifest = sim / "arith_oracle_manifest.json"
    manifest.write_text(json.dumps({"declared_latency": None}))

    # A run whose TB found no consistent framing prints no ORACLE_TB_FRAMING.
    d._persist_oracle_calibrated_framing(tmp_path, "ORACLE_TB_DONE pass=11/28\n")

    got = json.loads(manifest.read_text())
    assert "calibrated_latency" not in got
    assert "calibrated_bit_order" not in got


def test_persist_round_trips_msb_first(tmp_path):
    d = _load("design_one_shot_runner")
    sim = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True)
    (sim / "arith_oracle_manifest.json").write_text("{}")
    d._persist_oracle_calibrated_framing(
        tmp_path, "ORACLE_TB_FRAMING in_order=1 out_order=1 latency_cycles=7\n")
    got = json.loads((sim / "arith_oracle_manifest.json").read_text())
    assert got["calibrated_bit_order"] == "MSB_first"
    assert got["calibrated_out_bit_order"] == "MSB_first"
    assert got["calibrated_latency"] == 7


# ---------------------------------------------------------------------------
# 3. The emitter must PREFER the measured value over the declared one.
# ---------------------------------------------------------------------------
def test_emitter_prefers_calibrated_over_declared(tmp_path):
    """NEGATIVE CONTROL: pre-fix `_derive_latency_from_oracle_manifest` only
    read `declared_latency`, so a manifest carrying ONLY `calibrated_latency`
    returned None and the emitter fail-closed."""
    em = _load("arith_declaration_emit")
    sim = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True)
    (sim / "arith_oracle_manifest.json").write_text(json.dumps({
        "calibrated_bit_order": "LSB_first",
        "calibrated_latency": 2,
        "calibrated_latency_origin": "settled_edge_offset",
        "declared_latency": None,
    }))
    assert em._derive_latency_from_oracle_manifest(tmp_path) == 2
    assert em._derive_bit_order_from_oracle_manifest(tmp_path) == "LSB_first"


def test_emitter_bit_order_ignores_a_bogus_calibrated_value(tmp_path):
    em = _load("arith_declaration_emit")
    sim = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True)
    (sim / "arith_oracle_manifest.json").write_text(
        json.dumps({"calibrated_bit_order": "sideways"}))
    assert em._derive_bit_order_from_oracle_manifest(tmp_path) is None


# ---------------------------------------------------------------------------
# 4. The producer must actually be WIRED. This is the link whose absence made
#    every other fix moot.
# ---------------------------------------------------------------------------
def test_declaration_emitter_is_wired_into_the_runner():
    """NEGATIVE CONTROL: pre-fix, grepping the whole plugin for
    `arith_declaration_emit` matched only the program's own file."""
    d = _load("design_one_shot_runner")
    assert hasattr(d, "step_arith_declaration_emit")
    src = Path(d.__file__).read_text()
    assert "plan.append(step_arith_declaration_emit(project))" in src, (
        "the step must be appended to the phase-2 plan, not merely defined")


def test_wired_step_is_non_blocking_when_the_emitter_fail_closes(tmp_path):
    """Wiring a producer in must not newly FAIL an IC that was passing: the
    emitter is fail-closed by design, and whether the absent file MATTERS is
    spec_required_artifact_check's call, not this producer's."""
    d = _load("design_one_shot_runner")
    # An empty project: no RTL, so the emitter cannot derive anything.
    res = d.step_arith_declaration_emit(tmp_path)
    assert res.status == "NOT_MEASURED", f"expected SKIP, got {res.status}"
    assert not (tmp_path / "plugin_output" / "declaration.json").exists()


@pytest.mark.parametrize("depth", [1,2,3])
def test_native_serial_latency_uses_the_documented_settled_edge_origin(tmp_path,depth):
    import subprocess,shutil
    assert shutil.which("iverilog") and shutil.which("vvp"), "native Icarus required"
    gen=_load("arith_oracle_tb_gen"); reader=_load("spec_declaration_emit")
    runner=_load("design_one_shot_runner")
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
    sim=tmp_path/"phase2/stage1/sim_full_stack";sim.mkdir(parents=True)
    manifest=sim/"arith_oracle_manifest.json"
    manifest.write_text(json.dumps({"program":"arith_oracle_tb_gen"}))
    runner._persist_oracle_calibrated_framing(tmp_path,run.stdout)
    measured=reader.measured_framing(tmp_path)
    assert measured["latency_cycles"][0]==depth-1, measured
    assert reader.same_framing("latency_cycles",depth-1,measured["latency_cycles"][0])
    assert not reader.same_framing("latency_cycles",depth,measured["latency_cycles"][0])
    assert json.loads(manifest.read_text())["calibrated_latency_origin"]=="settled_edge_offset"


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
