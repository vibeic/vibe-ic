"""FX_STEP7_ASIC_SDC: the ASIC SDC is authored ONCE, at step 7, and step 15
reads it.

MEASURED (lane lls W23: spm x gf180mcuD, HARDMACRO, main 76a277544): step 7
FAILed on its own because its declared output `phase2/stage2/constraints/*.sdc`
was never produced. The ASIC SDC was authored inside `step_pnr` (and a second
copy of the same chain inside `step_prelayout_signoff`), and step 7's file was
written only when the design staged an SDC.

The split, with its evidence: every line of the SDC is design intent known at
step 7 (clock, I/O delays, the design's exceptions, the fanout ladder, liberty
units / DRV limits). ONE input is PnR-time -- the supply ports the pad-ring
producer (15.5ic) proves, excluded from the signal-only DRV scope -- and that
is a NAMED derivation `step_pnr` records, not a second author.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

TESTS = Path(__file__).resolve().parent
PROGRAMS = TESTS.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R                       # noqa: E402
from _ppa import timing as T                              # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "fx_step7_prelayout_fixtures", TESTS / "test_prelayout_signoff_before_pnr.py")
PL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PL)

TOP = "chip_top"
CONS = Path("phase2/stage2/constraints")


def _project(tmp_path: Path) -> Path:
    """A design with L8 clock data (25 ns on `clk`) and NO staged SDC."""
    proj = tmp_path / "proj"
    docs = proj / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "clock_domains": [{"name": "clk", "source_pin": "clk",
                           "role": "primary", "period_ns": 25.0}]}))
    return proj




@pytest.fixture(autouse=True)
def _complete_corner_fixture_contract(monkeypatch, tmp_path):
    # Some legacy cases call PL._corner_pdk directly to select another
    # Liberty. Complete that shared fixture edge, including those callers,
    # without changing their input setup or acceptance assertions.
    corner_pdk = PL._corner_pdk
    def complete(*args, **kwargs):
        pdk = corner_pdk(*args, **kwargs)
        if not Path(str(pdk.liberty)).is_file():
            material = tmp_path / "fixture_pdk" / Path(str(pdk.liberty)).name
            material.parent.mkdir(exist_ok=True)
            material.write_text('library(neutral) { time_unit : "1ns"; }\n')
            pdk.liberty = str(material)
        monkeypatch.setattr(R, "_emit_multi_corner_sta", _fixture_corner_sta)
        return pdk
    monkeypatch.setattr(PL, "_corner_pdk", complete)


def _fixture_corner_sta(project, top, pdk, container, libs, out, notes,
                        *, force_prelayout=False, setup_slack=0.4):
    """Native-edge test double; no simulator/STA qualification is claimed.

    Keep real report composition and the normal scoped audit subprocess.
    Two complete setup/hold paths supply the report contract naturally;
    neither the audit verdict nor StepResult is mocked.
    """
    assert force_prelayout is True
    assert len(libs) >= 2
    out.mkdir(parents=True, exist_ok=True)
    for corner in ("SS", "TT"):
        sections = ["# STA_BASIS: PRE_LAYOUT_ESTIMATE\n"
                    "# STA_TIME_UNIT: ns\n"
                    f"# corner: {corner}\nOpenSTA report_checks\n"]
        for kind, arrival, required, slack in (
                ("max", 2.5, 2.5 + setup_slack, setup_slack),
                ("min", 0.35, 0.10, 0.25)):
            sections.append(
                "Startpoint: source_reg (rising edge-triggered flip-flop clocked by clk)\n"
                "Endpoint: sink_reg (rising edge-triggered flip-flop clocked by clk)\n"
                f"Path Group: clk\nPath Type: {kind}\n\n"
                "  Delay    Time   Description\n"
                "---------------------------------------------------------\n"
                "   0.00    0.00   clock clk (rise edge)\n"
                "   0.00    0.00   clock network delay (ideal)\n"
                f"   {arrival:.2f}    {arrival:.2f}   source_reg/Q -> sink_reg/D\n"
                f"           {arrival:.2f}   data arrival time\n"
                f"           {required:.2f}   data required time\n"
                "---------------------------------------------------------\n"
                f"           {slack:.2f}   slack ({'MET' if slack >= 0 else 'VIOLATED'})\n\n")
        sections.append(f"wns max {setup_slack:.2f}\ntns max {min(setup_slack, 0):.2f}\n"
                        "wns min 0.25\ntns min 0.00\n")
        (out / f"sta_{corner}.rpt").write_text("".join(sections))
    notes.append("unit fixture supplied native-edge pre-layout reports; not a native run")
    return True






_DRV = {"max_transition_ns": 1.5, "max_capacitance_pf": 0.2}






# --------------------------------------------------------------------------- #
# RED on main: step 7's declared output is absent after step 7
# --------------------------------------------------------------------------- #






# --------------------------------------------------------------------------- #
# step 15 READS step 7's file; it does not author
# --------------------------------------------------------------------------- #


def test_step_pnr_itself_contains_no_sdc_author():
    """The inline author is gone from `step_pnr`: it calls
    `asic_sdc_for_pnr`, and none of the authoring builders."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    fn = next(n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "step_pnr")
    called = {n.func.id if isinstance(n.func, ast.Name) else n.func.attr
              for n in ast.walk(fn) if isinstance(n, ast.Call)
              and isinstance(n.func, (ast.Name, ast.Attribute))}
    assert "asic_sdc_for_pnr" in called
    assert not called & {"_build_auto_silicon_sdc", "_ensure_staged_sdc_drv",
                         "_scale_sdc_to_liberty_units", "author_asic_sdc"}


# --------------------------------------------------------------------------- #
# windows / old projects: regenerate through the SAME producer, and say so
# --------------------------------------------------------------------------- #




# --------------------------------------------------------------------------- #
# the honest split: design intent at step 7, the pad-ring supply ports at PnR
# --------------------------------------------------------------------------- #




# --------------------------------------------------------------------------- #
# the step-7 deck never feeds itself back as a clock source
# --------------------------------------------------------------------------- #



# --------------------------------------------------------------------------- #
# the fanout ladder reads the run's OWN standard-cell library at step 7
# --------------------------------------------------------------------------- #
_LIB = ("/foss/pdks/ciel/gf180mcu/gf180mcuD/libs.ref/"
        "gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib")
_L9_FANOUT_TABLE = """# L9 constraints

## Synthesis Fanout Limit

| library | `MAX_FANOUT_CONSTRAINT` |
|---|---|
| `sky130_fd_sc_ls` | 5 |
| `gf180mcu_*` | 4 |
| 其他 | 工具預設 |
"""








# =========================================================================== #
# review_wave7 (step 7)
# =========================================================================== #




























@pytest.mark.parametrize("escape", ["absolute", "symlink"])
def test_step7_reader_never_opens_a_record_path_outside_constraints(
        tmp_path, monkeypatch, escape):
    proj = _project(tmp_path)
    constraints = proj / CONS
    constraints.mkdir(parents=True)
    outside = tmp_path / "outside.sdc"
    outside.write_text("create_clock -period 1 [get_ports clk]\n")
    if escape == "absolute":
        record_path = str(outside)
    else:
        link = constraints / "escaped.sdc"
        link.symlink_to(outside)
        record_path = str(link.relative_to(proj))
    (constraints / T.ASIC_SDC_RECORD).write_text(json.dumps({
        "path": record_path, "sha256": "deliberately-wrong"}))
    opened = []
    original = Path.read_text

    def trace_read(path, *args, **kwargs):
        if path.resolve() == outside:
            opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", trace_read)
    rec, _ = T.read_step7_asic_sdc(
        R, proj, TOP, SimpleNamespace(name="test"))
    assert rec is None and not opened, opened


def test_step7_owned_ledger_never_hashes_a_symlink_outside_constraints(
        tmp_path, monkeypatch):
    proj = _project(tmp_path)
    constraints = proj / CONS
    constraints.mkdir(parents=True)
    outside = tmp_path / "outside.sdc"
    outside.write_text("external design input\n")
    link = constraints / "escaped.sdc"
    link.symlink_to(outside)
    rel = str(link.relative_to(proj))
    (constraints / T.ASIC_SDC_RECORD).write_text(json.dumps({
        "owned_outputs": {rel: hashlib.sha256(outside.read_bytes()).hexdigest()}}))
    opened = []
    original = Path.read_bytes

    def trace_read(path, *args, **kwargs):
        if path.resolve() == outside:
            opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", trace_read)
    assert T.owned_step7_outputs(R, proj) == {}
    assert not opened, opened


# --------------------------------------------------------------------------- #
# llv1 W7a's between-segments seam reads step 7's file through THIS reader
# --------------------------------------------------------------------------- #














# The migrated native-edge fixture must not bypass the current consumer.
