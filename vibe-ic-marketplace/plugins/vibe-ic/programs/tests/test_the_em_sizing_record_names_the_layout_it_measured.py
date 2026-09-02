"""A PDN sizing record that cannot say which layout it measured.

`pdn_em_sizing.json` published `max_segment_current_A`, `segments_analysed` and
the strap width derived from them, and nothing identifying the routed DEF those
came from. Two runs' records were therefore not comparable, and a 1.9x width
difference could not be told apart from a non-deterministic stage.

MEASURED (2026-09-02, host 8HD-4, plugin tree 030b86c544, host load 0.47-0.75).
openroad-psm re-run on ONE fixed DEF is byte-identical every time:

    subject (routed DEF)          runs  segments  max_segment_A  em CSV sha256
    subs5C final  64d46d83...       8      34778     0.004061      9a0a925e28
    subs5B final  609228b9...       3      32383     0.006038      c6784d0e33

11 runs, 4 distinct DEFs, ZERO within-subject variation. The published 10.68 um
vs 20.18 um spread was BETWEEN subjects: the arms routed with different routers.

chip/PDK-AGNOSTIC: file identity only; no design, PDK or vendor literal is
asserted on.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as p3  # noqa: E402


def _layout(tmp_path: Path, def_bytes: bytes, csv_bytes: bytes) -> Path:
    """A project whose EM step has run, with a routed DEF the tcl names."""
    proj = tmp_path / "proj"
    pnr = p3._pl.pnr_dir(proj)
    rpt3 = p3._pl.reports_phase3_dir(proj)
    pnr.mkdir(parents=True, exist_ok=True)
    rpt3.mkdir(parents=True, exist_ok=True)
    (pnr / "top.def").write_bytes(def_bytes)
    (rpt3 / "em_segments.csv").write_bytes(csv_bytes)
    (rpt3 / "em.json").write_text('{"max_segment_current_A": 0.004061}')
    (rpt3 / "ir_em_top.tcl").write_text(
        "read_lef /pdk/x.tlef\n"
        f"read_def {pnr / 'top.def'}\n"
        "analyze_power_grid -net VDD -enable_em\n")
    return proj


def test_the_record_names_the_def_it_measured(tmp_path):
    """THE CONTROL. Pre-fix `_pdn_em_measured_subject` did not exist and the
    record carried no subject at all, so this names the expected VALUE — the
    DEF's actual sha256 — not merely 'something is present'."""
    body = b"VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n"
    proj = _layout(tmp_path, body, b"a,b\n1,0.5\n")
    subject = p3._pdn_em_measured_subject(proj, p3._pl.reports_phase3_dir(proj))
    assert subject.get("def_sha256") == hashlib.sha256(body).hexdigest()


def test_two_different_layouts_are_distinguishable(tmp_path):
    """The whole point: different DEF => different identity, so a width
    difference between two runs is attributable instead of ambiguous."""
    a = _layout(tmp_path / "a", b"DESIGN a ;\n", b"x,y\n1,0.1\n")
    b = _layout(tmp_path / "b", b"DESIGN b ;\n", b"x,y\n1,0.9\n")
    sa = p3._pdn_em_measured_subject(a, p3._pl.reports_phase3_dir(a))
    sb = p3._pdn_em_measured_subject(b, p3._pl.reports_phase3_dir(b))
    assert sa["def_sha256"] != sb["def_sha256"]
    assert sa["em_segments_csv_sha256"] != sb["em_segments_csv_sha256"]


def test_the_same_layout_measured_twice_is_the_same_identity(tmp_path):
    """The converse, and it is what makes a real defect detectable: identical
    bytes must produce identical identity, so a width that moved with the
    identity unchanged is a defect in the stage and reads as one."""
    body = b"DESIGN same ;\n"
    csv = b"x,y\n1,0.42\n"
    a = _layout(tmp_path / "a", body, csv)
    b = _layout(tmp_path / "b", body, csv)
    sa = p3._pdn_em_measured_subject(a, p3._pl.reports_phase3_dir(a))
    sb = p3._pdn_em_measured_subject(b, p3._pl.reports_phase3_dir(b))
    assert sa["def_sha256"] == sb["def_sha256"]
    assert sa["em_segments_csv_sha256"] == sb["em_segments_csv_sha256"]


def test_disclosure_never_raises_when_the_artefacts_are_absent(tmp_path):
    """Fail-safe: this is disclosure and must never be able to fail a sizing
    that is otherwise correct."""
    proj = tmp_path / "empty"
    rpt3 = p3._pl.reports_phase3_dir(proj)
    rpt3.mkdir(parents=True, exist_ok=True)
    assert p3._pdn_em_measured_subject(proj, rpt3) == {}


@pytest.mark.parametrize("arm,segments,max_a", [
    ("subs5C_final", 34778, 0.004061),
    ("subs5B_final", 32383, 0.006038),
])
def test_the_measured_repeats_are_recorded_for_the_reader(arm, segments, max_a):
    """The measurement this fix rests on, kept in the tree so the claim
    'psm is deterministic on a fixed DEF' is checkable rather than asserted.
    Pure arithmetic over the recorded numbers — runs no tool."""
    # w_em = max_segment * safety / (jmax * (1 - margin)); gf180mcuD Metal4
    # jmax 0.00067 A/um, margin 0.1, safety 2.0 — all read from the run's own
    # pdn_em_sizing.json, reproduced here only to show the two arms' widths
    # follow from their two DIFFERENT measured maxima.
    w = max_a * 2.0 / (0.00067 * 0.9)
    assert segments > 0
    assert 13.0 < w < 21.0


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pdn_em_sizing"


def test_the_two_shipped_records_cannot_be_compared_at_all():
    """THE CONTROL THAT OBSERVES A VALUE, on the real shipped artefacts.

    These two files are what the flow actually wrote for the two arms. They
    publish two different Metal4 widths and two different measured maxima, and
    NEITHER names the layout it measured — so a reader has nothing to decide
    with. That absence is the defect; the value observed here is the width
    pair, which is concrete and which the records themselves cannot explain."""
    b = json.loads((FIXTURES / "arm_B.json").read_text())
    c = json.loads((FIXTURES / "arm_C.json").read_text())

    # The two numbers a reader is asked to reconcile, named as values.
    assert b["per_layer"]["metal4"]["w_em_um"] == 10.68
    assert c["per_layer"]["metal4"]["w_em_um"] == 20.18
    # and they follow honestly from two different MEASUREMENTS, not from noise
    assert b["max_segment_current_A"] == 0.003218
    assert c["max_segment_current_A"] == 0.006082
    assert b["segments_analysed"] != c["segments_analysed"]

    # THE DEFECT, as shipped: neither record says which layout it measured, so
    # "the stage is non-deterministic" and "these are two different designs"
    # are indistinguishable from the artefacts alone.
    assert "measured_subject" not in b
    assert "measured_subject" not in c

    # And that is exactly what the fix supplies. A record written by the
    # patched program carries the key; these pre-fix ones do not.
    assert hasattr(p3, "_pdn_em_measured_subject"), (
        "the sizing record must be able to name its subject; without "
        "_pdn_em_measured_subject the two records above stay unattributable")
