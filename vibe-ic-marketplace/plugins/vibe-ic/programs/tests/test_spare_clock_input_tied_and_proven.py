"""A spare cell's CLOCK-use input is an input: tie it, prove it, count it (U6).

MEASURED (2026-09-29):
  * spm IC run v5c, `phase3/stage3/pnr/spm_pnr.v:113595`
        gf180mcu_fd_sc_mcu7t5v0__dffq_2 spare_dff_0 (.D(spare_tielo_spare_dff_0));
    CLK has no net. subservient v4 `nl.v:60881`: the same shape.
  * the LEF says `PIN CLK ... USE CLOCK`; `Vibeic.InsertSpareCells` tied only
    `getSigType() == "SIGNAL"` pins, and logged `SPARE_TIEOFF_CONNECTED 12 of 12`
    -- complete over the 12 pins it had chosen to count.
  * `spare_cells.json` therefore said `tied_off: true`, and
    `spare_cell_coverage.json` read PASS ("measured 12/12 spare input(s) tied").
  * the spm tail run's Step-31 `erc.rpt` headline said `ERC floating nets: 0 /
    ERC clean: YES` and `erc.json` said verdict PASS, over a transcript in
    which OpenROAD listed `[WARNING RSZ-0095] found 1 floating pins.
    spare_dff_0/CLK`, classified "benign-ERC" because its owner is a spare.

Each layer is driven through the real code: the odbpy step (fake odb only),
the runner's log reader and ERC emitter (fake container only), and the three
gates on the run's own record, netlist line and transcript.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import spare_cell_coverage_check as cov  # noqa: E402


def _mig97():
    spec = importlib.util.spec_from_file_location(
        "_mig97_fakes", PROGRAMS / "tests" / "test_mig97_placement_spares.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- producer --

def test_insertion_ties_the_clock_use_input_and_enumerates_every_pin(
        monkeypatch, capsys):
    """The odbpy step on a spare flop whose CLK is `USE CLOCK`."""
    m = _mig97()
    # the gf180 7t dffq pin table (LEF: D INPUT, CLK INPUT USE CLOCK, Q OUTPUT)
    monkeypatch.setitem(m._PINS, "dffq", [
        ("D", "SIGNAL", "INPUT"), ("CLK", "CLOCK", "INPUT"),
        ("Q", "SIGNAL", "OUTPUT"), ("VDD", "POWER", "INOUT"),
        ("VSS", "GROUND", "INOUT")])
    monkeypatch.setitem(m._TYPES, "dffq", "CORE")
    # odb's own rule: dbITerm::isInputSignal is false for POWER/GROUND and
    # true for an INPUT of any other USE -- CLOCK included
    monkeypatch.setattr(m._ITerm, "isInputSignal", lambda self: (
        self.mterm.sig not in ("POWER", "GROUND")
        and self.mterm.io in ("INPUT", "INOUT")))
    mod, reader, _dpl, _tcl = m._odbpy(monkeypatch)
    plan = {"instances": [{"name": "spare_dff_0", "cell": "dffq",
                           "llx": 10, "lly": 20}]}
    measured = mod.insert(reader, {"VIBEIC_SPARE_TIELO_CELL": "tiel/ZN"}, plan)
    out = capsys.readouterr().out
    dff = reader.block.findInst("spare_dff_0")
    conns = {i.mterm.name: (i.getNet().getName() if i.getNet() else None)
             for i in dff.iterms}
    assert conns["CLK"] == "spare_tielo_spare_dff_0", conns
    assert conns["D"] == "spare_tielo_spare_dff_0"
    assert conns["Q"] is None                      # an output may float
    assert measured["tieoff_candidates"] == 2 == measured["tieoff_connected"]
    assert "SPARE_INPUT_PIN spare_dff_0 CLK CLOCK spare_tielo_spare_dff_0" in out
    assert "SPARE_INPUT_PIN spare_dff_0 D SIGNAL spare_tielo_spare_dff_0" in out
    assert "SPARE_INPUT_PIN spare_dff_0 Q" not in out


@pytest.mark.parametrize("with_tie_cell", [True, False])
def test_native_report_reaches_the_existing_coverage_gate(
        monkeypatch, tmp_path, with_tie_cell):
    """Read the actual native JSON, including a CLOCK input and an ODB count."""
    m = _mig97()
    monkeypatch.setitem(m._PINS, "dffq", [
        ("D", "SIGNAL", "INPUT"), ("CLK", "CLOCK", "INPUT"),
        ("Q", "SIGNAL", "OUTPUT"), ("VDD", "POWER", "INOUT"),
        ("VSS", "GROUND", "INOUT")])
    monkeypatch.setattr(m._ITerm, "isInputSignal", lambda self: self.mterm.io == "INPUT")
    mod, reader, _dpl, _tcl = m._odbpy(monkeypatch)
    for i in range(99):
        reader.block.insts[f"logic_{i}"] = m._Inst(
            reader.block, m._Master("nand2"), f"logic_{i}")
    plan = {
        "count": 2, "density": 0.02,
        # Deliberately wrong caller estimates must not replace ODB measurement.
        "placed_cells_est": 1, "actual_density": 2.0,
        "instances": [
            {"name": "spare_inv_0", "cell": "inv", "llx": 10, "lly": 20},
            {"name": "spare_dff_0", "cell": "dffq", "llx": 50, "lly": 20},
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    reader.config = {"VIBEIC_SPARE_PLAN": str(plan_path)}
    if with_tie_cell:
        reader.config["SYNTH_TIELO_CELL"] = "tiel/ZN"
    report = tmp_path / "spare_cells.json"
    mod.cli.callback(reader=reader, report_path=str(report),
                     output_nl="/o/nl.v", output_pnl="/o/pnl.v")
    doc = json.loads(report.read_text())
    assert doc["placed_cells_est"] == 100
    assert doc["actual_density"] == pytest.approx(0.02)
    assert doc["count"] == 2
    assert len(doc["tie_off"]["inputs"]) == 3
    clk = next(p for p in doc["tie_off"]["inputs"] if p["pin"] == "CLK")
    assert clk["use"] == "CLOCK"
    assert clk["net"] == ("spare_tielo_spare_dff_0" if with_tie_cell else None)
    verdict = cov.evaluate_coverage(doc)
    assert verdict["verdict"] == ("PASS" if with_tie_cell else "FAIL"), verdict
    assert doc["tied_off"] is with_tie_cell
    if not with_tie_cell:
        assert "spare_dff_0/CLK" in verdict["tie_off_inputs"]["without_net"]


# v5c's step log shape: the count over the pins the step chose, then (new)
# every input it has. spare_dff_0/CLK carries no net.
_V5C_LOG = """SPARE_TIEOFF_CONNECTED 12 of 12
SPARE_TIEOFF_DRIVERS 6
SPARE_INPUT_PIN spare_inverter_0 I SIGNAL spare_tielo_spare_inverter_0
SPARE_INPUT_PIN spare_dff_0 D SIGNAL spare_tielo_spare_dff_0
SPARE_INPUT_PIN spare_dff_0 CLK CLOCK -
SPARE_TIEOFF_DONE: nets spare_tielo_spare_inverter_0 spare_tielo_spare_dff_0
"""


def test_the_runner_reads_the_enumeration_not_just_the_count(tmp_path):
    import phase3_one_shot_runner as R
    log = tmp_path / "librelane_spare_cells.log"
    log.write_text(_V5C_LOG)
    got = R._spare_tieoff_measured_from_log(log)
    assert got["measured"] is True
    assert got["tied_off"] is False, got
    assert "spare_dff_0/CLK" in got["reason"]
    assert {"inst": "spare_dff_0", "pin": "CLK", "use": "CLOCK",
            "net": None} in got["inputs"]
    # the same log with the CLK tied is tied off
    log.write_text(_V5C_LOG.replace("CLK CLOCK -",
                                    "CLK CLOCK spare_tielo_spare_dff_0"))
    ok = R._spare_tieoff_measured_from_log(log)
    assert ok["tied_off"] is True and len(ok["inputs"]) == 3


def test_the_direct_deck_prints_the_same_enumeration():
    import phase3_one_shot_runner as R
    import inspect
    src = inspect.getsource(R)
    at = src.index("SPARE_TIEOFF_DRIVERS $_tie_drv")
    block = src[at:at + 2000]
    assert 'getIoType] ne \\"INPUT\\"' in block
    assert "SPARE_INPUT_PIN [$_si getName] [$_mt getName] [$_mt getSigType]" in block
    # only supply pins are skipped -- a CLOCK-use input is enumerated
    assert "[$_mt getSigType] in {POWER GROUND}} { continue }" in block
    assert "CLOCK" not in block.split("SPARE_INPUT_PIN")[0].split("foreach _sn")[-1]
    # the observation gate recognises the marker as insertion evidence
    assert "SPARE_INPUT_PIN" in R._STEP18_INSERTION_MARKERS


# ------------------------------------------------------------ step 18 gate --

# spm v5c `phase3/stage3/pnr/spare_cells.json`, the fields the gate reads.
_V5C_RECORD = {
    "count": 6, "density": 0.02, "tied_off": True,
    "placed_cells_est": 273, "target_density": 0.02,
    "actual_density": 0.021978,
    "instances": [
        {"name": "spare_inverter_0", "llx": 520.24, "lly": 517.44},
        {"name": "spare_nand2_0", "llx": 1226.96, "lly": 517.44},
        {"name": "spare_nor2_0", "llx": 1934.8, "lly": 517.44},
        {"name": "spare_mux2_0", "llx": 519.12, "lly": 1579.76},
        {"name": "spare_aoi_0", "llx": 1226.96, "lly": 1579.76},
        {"name": "spare_dff_0", "llx": 1932.56, "lly": 1579.76}],
    "tie_off": {"measured": True, "connected": 12, "candidates": 12,
                "tied_off": True,
                "reason": "measured 12/12 spare input(s) tied to their "
                          "per-spare tie-low net"},
}

_PINS_OF = {"spare_inverter_0": ["I"], "spare_nand2_0": ["A1", "A2"],
            "spare_nor2_0": ["A1", "A2"], "spare_mux2_0": ["I0", "I1", "S"],
            "spare_aoi_0": ["A1", "A2", "B"], "spare_dff_0": ["D", "CLK"]}


def _enumerated(clk_net):
    rec = json.loads(json.dumps(_V5C_RECORD))
    rows = []
    for inst, pins in _PINS_OF.items():
        for p in pins:
            net = f"spare_tielo_{inst}"
            if (inst, p) == ("spare_dff_0", "CLK"):
                net = clk_net
            rows.append({"inst": inst, "pin": p,
                         "use": "CLOCK" if p == "CLK" else "SIGNAL",
                         "net": net})
    rec["tie_off"]["inputs"] = rows
    return rec


def test_coverage_refuses_the_v5c_record():
    """A tie COUNT with no pin enumeration was PASS on main."""
    r = cov.evaluate_coverage(json.loads(json.dumps(_V5C_RECORD)))
    assert r["verdict"] == "FAIL", r
    assert r["tie_off_ok"] is False
    assert any("not proven per pin" in x for x in r["reasons"])


def test_coverage_refuses_an_enumerated_floating_clock():
    r = cov.evaluate_coverage(_enumerated(None))
    assert r["verdict"] == "FAIL"
    assert r["tie_off_inputs"]["without_net"] == ["spare_dff_0/CLK"]


def test_coverage_passes_when_every_input_has_a_net():
    r = cov.evaluate_coverage(_enumerated("spare_tielo_spare_dff_0"))
    assert r["verdict"] == "PASS", r["reasons"]
    assert r["tie_off_inputs"]["enumerated"] == 13


def test_coverage_refuses_a_spare_missing_from_the_enumeration():
    rec = _enumerated("spare_tielo_spare_dff_0")
    rec["tie_off"]["inputs"] = [x for x in rec["tie_off"]["inputs"]
                                if x["inst"] != "spare_mux2_0"]
    r = cov.evaluate_coverage(rec)
    assert r["verdict"] == "FAIL"
    assert r["tie_off_inputs"]["spares_not_enumerated"] == ["spare_mux2_0"]


# ------------------------------------------------------------ step 34 gate --

_CELL = {"spare_inverter_0": "inv_1", "spare_nand2_0": "nand2_2",
         "spare_nor2_0": "nor2_2", "spare_mux2_0": "mux2_1",
         "spare_aoi_0": "aoi21_2", "spare_dff_0": "dffq_2"}


def _shipped_netlist(clk_connected: bool) -> str:
    lines = ["module chip_top ();"]
    for inst, pins in _PINS_OF.items():
        conns = [f".{p}(spare_tielo_{inst})" for p in pins
                 if clk_connected or (inst, p) != ("spare_dff_0", "CLK")]
        lines.append(f" gf180mcu_fd_sc_mcu7t5v0__{_CELL[inst]} {inst} "
                     f"({', '.join(conns)});")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def test_v5c_netlist_line_is_what_the_fixture_writes():
    assert (" gf180mcu_fd_sc_mcu7t5v0__dffq_2 spare_dff_0 "
            "(.D(spare_tielo_spare_dff_0));") in _shipped_netlist(False)


def _project(tmp_path, record, netlist):
    pnr = tmp_path / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    (pnr / "spare_cells.json").write_text(json.dumps(record))
    (pnr / "spm_pnr.v").write_text(netlist)
    (pnr / "routed.def").write_text(
        "DESIGN chip_top ;\nCOMPONENTS 6 ;\n"
        + "".join(f"- {n} c + FIXED ( 0 0 ) N ;\n" for n in _PINS_OF)
        + "END COMPONENTS\nEND DESIGN\n")
    return tmp_path


# ------------------------------------------------------------------ ERC --

# The spm tail run's reports/phase3/erc.rpt, head and transcript.
_TAIL_ERC_RPT = """# Electrical Rule Check (ERC) — OpenROAD open-source path
#
ERC floating nets: 0
ERC clean: YES

# === report_floating_nets / report_erc_metrics stdout ===
=== ERC: floating nets ===
[WARNING RSZ-0095] found 1 floating pins.
 spare_dff_0/CLK
=== ERC metrics ===
"""


def test_the_erc_producer_counts_floating_pins(tmp_path, monkeypatch):
    """`_emit_erc_report` on the tail run's tool transcript (container faked)."""
    import phase3_one_shot_runner as R
    transcript = ("=== ERC: floating nets ===\n"
                  "[WARNING RSZ-0095] found 1 floating pins.\n"
                  " spare_dff_0/CLK\n=== ERC metrics ===\n")
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: p)
    monkeypatch.setattr(R, "_docker_exec",
                        lambda *a, **k: (0, transcript, ""))
    pnr = R._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True)
    (pnr / "chip_top.def").write_text("DESIGN chip_top ;\n")
    pdk = SimpleNamespace(tech_lef="t.lef", cell_lef="c.lef",
                          liberty="c.lib", macro_lefs=[])
    rpt = tmp_path / "reports" / "phase3" / "erc.rpt"
    assert R._emit_erc_report(tmp_path, "chip_top", pdk, "ctr", rpt, [])
    text = rpt.read_text()
    assert "ERC floating pins: 1" in text
    assert "ERC clean: YES" not in text
    rec = json.loads((rpt.parent / "erc.json").read_text())
    assert rec["clean"] is False and rec["verdict"] != "PASS", rec
    assert rec["float_classification"]["functional_count"] == 1
