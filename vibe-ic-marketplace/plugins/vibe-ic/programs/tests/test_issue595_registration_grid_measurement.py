"""#595 — the offset was measured; the fact that CHOOSES a remedy was not.

The A8 frame gate (#594) already detects that the LEF abstract and the GDS body
are in different coordinate frames and names both remedies:

  * stream the GDS in the LEF's frame — a rigid translation;
  * declare `FOREIGN <cell> <llx> <lly> ;`.

The issue filed rather than fixed, correctly, because the two are NOT
equivalent and picking wrong "converts a loud FAIL into a silent misplacement in
the other direction, which is worse than today".

WHAT DECIDES IT, and what was not being measured: whether the offset is a whole
number of MANUFACTURING GRID steps.

  * DRC and LVS are translation-INVARIANT, so a rigid move cannot change either
    verdict. What it CAN do is put every coordinate off-grid — and this repo has
    already paid for an off-grid streamout once.
  * If the offset IS an exact multiple, translating is grid-preserving and the
    objection to it does not apply.
  * If it is NOT, translating is the unsafe one and FOREIGN is the remedy.

So the gate now measures it and SAYS it. It still does not choose — that stays a
flow-owner call, which is what the issue asked for.

A GUESSED GRID WOULD DECIDE THE QUESTION, so it is never guessed.
`def_manufacturing_grid_check.read_mfg_grid_um` falls back to a PDK default when
the tech LEF is unreadable, which is right for its own purpose and wrong here;
this reads `None` and the finding says the answer is unknown.

NOT REPRODUCIBLE FROM THE CORPUS, and stated rather than implied: the tracked
`u_hawaii_adc` hardmacro pair is not one pair. Measured —

    delta_sigma.lef   SIZE 120.000 BY 120.000, and it HAS a FOREIGN statement
    delta_sigma.gds   bbox (-2.03,-2.03)-(20.03,9.03), 22.06 x 11.06

different generations of artefact, and the LEF is a round-numbered placeholder.
The issue's numbers came from a live IHP SG13G2 run whose artefacts were never
committed. The fixtures below carry this.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load("analog_lef_gds_outline_check")


# ── the grid is read, never assumed ─────────────────────────────────────────
def test_the_grid_is_read_from_a_tech_lef(tmp_path):
    t = tmp_path / "t.tlef"
    t.write_text("VERSION 5.7 ;\nMANUFACTURINGGRID 0.005 ;\nEND LIBRARY\n",
                 encoding="utf-8")
    assert M.manufacturing_grid_um(tmp_path, str(t)) == 0.005


def test_an_unreadable_tech_lef_is_not_a_default(tmp_path):
    """LOAD-BEARING. A guessed grid decides between the two remedies, and the
    whole point of measuring is that neither should be guessed."""
    assert M.manufacturing_grid_um(tmp_path, str(tmp_path / "nope.tlef")) is None


def test_a_tech_lef_without_the_token_is_not_a_default(tmp_path):
    t = tmp_path / "t.tlef"
    t.write_text("VERSION 5.7 ;\nEND LIBRARY\n", encoding="utf-8")
    assert M.manufacturing_grid_um(tmp_path, str(t)) is None


def test_a_project_with_no_tech_lef_answers_none(tmp_path):
    assert M.manufacturing_grid_um(tmp_path) is None


def test_it_is_auto_located_under_the_project(tmp_path):
    d = tmp_path / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "sky.tlef").write_text("MANUFACTURINGGRID 0.01 ;\n", encoding="utf-8")
    assert M.manufacturing_grid_um(tmp_path) == 0.01


# ── the decision fact ───────────────────────────────────────────────────────
def test_a_whole_number_of_grid_steps_is_recognised():
    ok, detail = M.offset_on_grid(-0.620, -30.320, 0.005)
    assert ok is True
    assert "exact multiple" in detail


def test_a_fractional_offset_is_recognised():
    ok, detail = M.offset_on_grid(-0.6205, -30.320, 0.005)
    assert ok is False
    assert "NOT an exact multiple" in detail


def test_one_axis_off_grid_is_enough_to_refuse():
    """Both coordinates move, so both must land on the grid."""
    assert M.offset_on_grid(-0.620, -30.3225, 0.005)[0] is False


def test_an_unknown_grid_is_never_reported_as_on_grid():
    """"I could not read the grid" and "the offset is aligned" would license
    opposite remedies. `None`, never True."""
    for grid in (None, 0, -1):
        ok, detail = M.offset_on_grid(-0.620, -30.320, grid)
        assert ok is None, grid
        assert "UNKNOWN" in detail


def test_a_zero_offset_is_trivially_on_grid():
    assert M.offset_on_grid(0.0, 0.0, 0.005)[0] is True


# ── it reaches the record and the finding ───────────────────────────────────
def test_the_record_and_the_finding_carry_it():
    src = (_PROGRAMS / "analog_lef_gds_outline_check.py").read_text(
        encoding="utf-8")
    assert '"manufacturing_grid_um": grid_um' in src, "not in the JSON record"
    assert '"offset_is_grid_multiple": on_grid' in src
    assert "grid_detail" in src[src.index("A8_LEF_GDS_REGISTRATION_MISMATCH"):
                                src.index("A8_LEF_GDS_REGISTRATION_MISMATCH")
                                + 2200], (
        "the finding text does not say which remedy the measurement licenses")


def test_the_gate_still_does_not_choose_for_the_flow_owner():
    """The issue asked for the choice to stay a flow-owner call. Both remedies
    must still be named in every branch."""
    src = (_PROGRAMS / "analog_lef_gds_outline_check.py").read_text(
        encoding="utf-8")
    seg = src[src.index("A8_LEF_GDS_REGISTRATION_MISMATCH"):][:2600]
    assert "FOREIGN <cell>" in seg
    assert "stream the GDS in the LEF's frame" in seg
