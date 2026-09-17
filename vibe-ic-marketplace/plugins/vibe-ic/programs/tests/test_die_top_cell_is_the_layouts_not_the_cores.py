"""On a DIE the declared top cell must name the LAYOUT, not the core it wraps.

MEASURED on spm x gf180mcuD, DIE route (v1.22.10, run6): the design's answers
file says `top_cell = spm` — L8's RTL module name, and NOT owner-attested —
while the flow generated the physical wrapper `chip_top` around it, routed it,
streamed it, and wrote `DESIGN chip_top` in the final DEF. The declaration kept
`spm`, so `general_precheck.KLayout.CheckTopLevel` compared the streamed top
against the CORE's name and refused: "the top-level cell is 'chip_top'; the
declaration names 'spm'. This layout is not this design", and `tapeout_precheck`
FAILed on it in run3, run4, run5 and run6.

The publisher may now supersede that one answer, and only when every link of
the chain holds.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402
import _tapeout_declaration as TD  # noqa: E402

_FN = R._declared_answer_is_the_core_this_die_wraps


def _project(tmp_path: Path, *, deliverable=TD.DELIVERABLE_DIE,
             verdict="WROTE", core="spm", chip="chip_top") -> Path:
    answers = tmp_path / "input" / "step_0_5ic_answers.json"
    answers.parent.mkdir(parents=True, exist_ok=True)
    answers.write_text(json.dumps({"answers": {"deliverable": deliverable,
                                               "top_cell": core}}))
    decl = tmp_path / "input" / "submission_template" / "tapeout_declaration.json"
    decl.parent.mkdir(parents=True, exist_ok=True)
    doc, _ = TD.merge_answers(TD.blank_declaration(),
                              {"deliverable": deliverable, "top_cell": core})
    # `deliverable` is owner-answered (#2369): without the attestation the
    # declaration reads NOT_DETERMINED, which is the real staged shape.
    doc[TD.PROVENANCE_KEY] = {"deliverable": {
        "answered_by": TD.ANSWERED_BY_OWNER_VALUE,
        "citation": "R-0915-95 (2026-09-17) — fixture"}}
    decl.write_text(json.dumps(doc, indent=2))
    rec = tmp_path / "reports" / "phase3" / "io_pad_chip_top.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({"verdict": verdict, "chip_top_module": chip,
                               "core_module": core}))
    return tmp_path


def test_a_die_whose_wrapper_this_flow_wrote_publishes_the_layouts_top(tmp_path):
    ok, why = _FN(_project(tmp_path), "top_cell", "spm", "chip_top")
    assert ok, why
    assert "core_module='spm'" in why and "chip_top_module='chip_top'" in why


@pytest.mark.parametrize("kw,case", [
    ({"deliverable": TD.DELIVERABLE_HARDMACRO}, "a hardmacro owes no die top"),
    ({"verdict": "REFUSED"}, "the wrapper record is not a WROTE"),
    ({"core": "other_core"}, "the record wrapped a different core"),
    ({"chip": "other_top"}, "the record names a different physical top"),
])
def test_every_broken_link_keeps_the_declared_answer(tmp_path, kw, case):
    ok, why = _FN(_project(tmp_path, **kw), "top_cell", "spm", "chip_top")
    assert not ok, f"{case}: {why}"


def test_no_other_key_and_no_identical_answer_is_ever_superseded(tmp_path):
    project = _project(tmp_path)
    assert not _FN(project, "die_area_um", "spm", "chip_top")[0]
    assert not _FN(project, "top_cell", "chip_top", "chip_top")[0]
    assert not _FN(project, "top_cell", None, "chip_top")[0]


def test_an_unreadable_or_absent_record_keeps_the_declared_answer(tmp_path):
    project = _project(tmp_path)
    rec = project / "reports" / "phase3" / "io_pad_chip_top.json"
    rec.write_text("{not json")
    assert not _FN(project, "top_cell", "spm", "chip_top")[0]
    rec.unlink()
    assert not _FN(project, "top_cell", "spm", "chip_top")[0]


def test_the_publisher_consults_the_supersede_and_records_it():
    import inspect
    body = inspect.getsource(R.publish_tapeout_declarations)
    assert "_declared_answer_is_the_core_this_die_wraps(" in body
    assert 'rec["superseded"]' in body
    # and the old rule is still the default path
    assert "outranks this " in body   # the old rule, split across two f-string lines
