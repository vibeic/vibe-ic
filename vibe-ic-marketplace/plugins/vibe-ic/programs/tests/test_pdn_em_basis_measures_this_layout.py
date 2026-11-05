"""The PDN's supply current must describe the layout being sized, and a prior
EM resize binds only when its recorded strap floor reached the drawn DEF.

THE TWO DEFECTS THIS FILE DEFENDS AGAINST
=========================================
`step_pnr` derives the PDN strap-width floor from an EM measurement, but the EM
reports are written by `step_canonicalize_artefacts`, which runs AFTER PnR —
verified statically (enclosing defs) and from two real run logs. So the first
PnR of any run can only ever read a PREVIOUS run's measurement.

`_pdn_em_first_pass_resize` closes that gap inside a run by re-measuring and
re-dispatching PnR once. It was bounded by a sentinel written into the project
tree that NOTHING ever removes, so the bound retired the corrector for the life
of the tree. MEASURED on spm run23: a sentinel dated 2026-09-23 18:50 left two
later runs with no corrector, and the current the PDN was sized from drifted
2.900e-03 -> 2.600e-03 -> 2.860e-03 with the design unchanged. The control that
proves it is not the code: the SAME commit re-run on the drifted tree
reproduced the drifted number.

The sentinel records the DEF it measured and the floor it requested. A same-run
token blocks a third PnR even while the second pass has not applied that floor.
On a later run, the recorded DEF digest alone is insufficient: a failed second
pass can leave the same narrow DEF on disk. The drawn strap widths decide.

WHY NOT mtime, AND WHY NOT `measured_subject.def_sha256`. "Written during this
run" is not identity: a same-build re-run that cache-hits the PnR DEF holds a
measurement of exactly this layout, and refusing it by clock discards an
accurate number and republishes the sizing record as NOT_DERIVED for a DEF that
WAS drawn with the floor. And `_pdn_em_measured_subject` digests the DEF at
READ time, so comparing it to the DEF on disk compares the file with itself and
is true always — a check that cannot fail is not a check. The subject digest is
therefore RECORDED BY THE PRODUCER, and a measurement carrying none is declined.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402
from _ppa import power as PW  # noqa: E402




def _layout(project: Path, body: bytes = (
        b"VERSION 5.8 ;\nUNITS DISTANCE MICRONS 2000 ;\n"
        b"SPECIALNETS 1 ;\n- supply + USE POWER\n"
        b"+ ROUTED MetalA 3200 + SHAPE STRIPE ( 0 0 ) ( 1000 0 ) ;\n"
        b"END SPECIALNETS\nEND DESIGN\n")) -> str:
    pnr = R._pl.pnr_dir(project)
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / PW._PDN_EM_SUBJECT_DEF).write_bytes(body)
    return hashlib.sha256(body).hexdigest()


def _em_json(project: Path, subject: object, current: float = 0.00286) -> Path:
    rpt3 = R._pl.reports_phase3_dir(project)
    rpt3.mkdir(parents=True, exist_ok=True)
    doc = {"max_segment_current_A": current, "segments_analysed": 34778}
    if subject is not None:
        doc["subject_def_sha256"] = subject
    (rpt3 / "em.json").write_text(json.dumps(doc))
    return rpt3


# ---------------------------------------------------------------------------
# the bound is per DESIGN STATE
# ---------------------------------------------------------------------------






def test_the_key_tracks_the_layout(tmp_path):
    """A key that never changes is a tree key wearing a different name."""
    proj = tmp_path / "p"
    before = _layout(proj, b"DESIGN chip_top ; # pass 1\n")
    _layout(proj, b"DESIGN chip_top ; # pass 2 re-routed\n")
    assert PW._pdn_em_spent_on(proj) != before








def test_no_sentinel_does_not_bind(tmp_path):
    proj = tmp_path / "p"
    _layout(proj)
    binds, _ = PW._pdn_em_sentinel_binds(R._pl.pnr_dir(proj) / "absent", proj)
    assert binds is False


def test_the_writer_records_the_design_it_spent_the_resize_on():
    """A sentinel that does not name its design cannot bound one design rather
    than the tree, so the write site is part of the contract."""
    src = (PROGRAMS / "_ppa" / "power.py").read_text()
    i = src.find('"reason": "pdn_em_first_pass_resize"')
    assert i > 0, "the sentinel write site moved; this test must follow it"
    assert '"spent_on_def": _pdn_em_spent_on(project)' in src[i:i + 500], (
        "the sentinel is written without a design tag, so it will bound every "
        "future run in this tree")


# ---------------------------------------------------------------------------
# the measurement must describe the layout in front of us
# ---------------------------------------------------------------------------
def test_a_measurement_of_this_layout_is_accepted(tmp_path):
    """THE PAIRED HALF, and the one that keeps this from being a ban: a
    same-build re-run that cache-hits the DEF holds an ACCURATE measurement of
    exactly this layout and must keep using it."""
    proj = tmp_path / "p"
    sha = _layout(proj)
    rpt3 = _em_json(proj, sha)
    ok, why = PW._pdn_em_measures_this_layout(rpt3, proj)
    assert ok is True, why


def test_a_measurement_of_a_different_layout_is_declined(tmp_path):
    proj = tmp_path / "p"
    _layout(proj)
    rpt3 = _em_json(proj, "f" * 64)
    ok, why = PW._pdn_em_measures_this_layout(rpt3, proj)
    assert ok is False
    assert "different design state" in why


def test_a_measurement_recording_no_subject_is_declined(tmp_path):
    """The legacy artefact. It cannot be SHOWN to measure this layout, and the
    stale-basis case is exactly what that looks like."""
    proj = tmp_path / "p"
    _layout(proj)
    rpt3 = _em_json(proj, None)
    ok, why = PW._pdn_em_measures_this_layout(rpt3, proj)
    assert ok is False
    assert "records no subject_def_sha256" in why


def test_the_subject_check_is_not_vacuous(tmp_path):
    """THE TRAP THIS FILE EXISTS FOR. `_pdn_em_measured_subject` digests the
    DEF at READ time; a check built on it compares the file with itself and
    passes always. Prove ours moves when only the LAYOUT changes."""
    proj = tmp_path / "p"
    sha = _layout(proj)
    rpt3 = _em_json(proj, sha)
    assert PW._pdn_em_measures_this_layout(rpt3, proj)[0] is True
    _layout(proj, b"DESIGN chip_top ; # re-routed\n")     # measurement unchanged
    assert PW._pdn_em_measures_this_layout(rpt3, proj)[0] is False, (
        "the subject check did not notice the layout changing under a fixed "
        "measurement — it is comparing the DEF with itself")


def test_the_producer_records_the_subject_at_measurement_time():
    """The consumer can only check a digest the producer actually wrote."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert ('"subject_def_sha256": _ppa_power._pdn_em_subject_digest(project)'
            in src), (
        "em.json is emitted without a recorded subject, so every subject "
        "check downstream is unfalsifiable")


# ---------------------------------------------------------------------------
# the design-declared fallback, and the disclosure
# ---------------------------------------------------------------------------


def _l19(project: Path, fields: dict) -> Path:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({"fields": fields}))
    return project


def test_a_budget_uses_the_pdk_nominal_voltage(tmp_path):
    """THE RUNG MUST BE REACHABLE. The flow-produced L19 carries
    `fields.power_budget_uw` and NO voltage field at all (measured on run23),
    so a rung needing a declared voltage could never be climbed."""
    proj = _l19(tmp_path / "p", {"power_budget_uw": 5000.0})
    i, src, gap = PW._pdn_em_declared_current(proj, 5.0)
    assert i == pytest.approx(5000.0e-6 / 5.0)
    assert "nom_voltage" in src and gap == ""


def test_a_declared_voltage_overrides_the_pdk(tmp_path):
    proj = _l19(tmp_path / "p", {"power_budget_uw": 5000.0,
                                 "supply_voltage_v": 1.8})
    i, _src, _gap = PW._pdn_em_declared_current(proj, 5.0)
    assert i == pytest.approx(5000.0e-6 / 1.8)


def test_a_null_budget_says_so_precisely(tmp_path):
    """spm declares the FIELD and leaves it null: the design has not answered,
    and that must not become a fabricated number."""
    proj = _l19(tmp_path / "p", {"power_budget_uw": None})
    i, _s, gap = PW._pdn_em_declared_current(proj, 5.0)
    assert i is None
    assert "declares no power_budget_uw" in gap


def test_a_budget_with_no_voltage_anywhere_says_THAT_instead(tmp_path):
    """The two gaps are different facts. Reporting 'no budget declared' when a
    budget IS declared sends the reader to the wrong file."""
    proj = _l19(tmp_path / "p", {"power_budget_uw": 5000.0})
    i, _s, gap = PW._pdn_em_declared_current(proj, None)
    assert i is None
    assert "no supply voltage" in gap and "5000.0 uW" in gap




# ---------------------------------------------------------------------------
# r3 item 1 — a subject match is not enough when the subject is about to go
# ---------------------------------------------------------------------------




def test_step_pnr_passes_the_flag():
    """The flag only defends anything if the one caller that replaces the
    layout actually sets it."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert "layout_will_be_replaced=True" in src, (
        "step_pnr no longer tells the floor that it is about to re-route, so "
        "the previous layout's current is back in the basis")
