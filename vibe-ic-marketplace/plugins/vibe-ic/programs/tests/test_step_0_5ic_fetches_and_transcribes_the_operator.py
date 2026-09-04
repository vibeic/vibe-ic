#!/usr/bin/env python3
"""Step 0.5ic's chain: fetch -> ingest -> answers -> declaration.

WHAT WAS BROKEN. The step declared its input `from: external, check: none` —
"fetched, not produced, and the flow must be able to say it was never fetched" —
and nothing fetched it. Measured 2026-09-04 across every published corpus tree:
`input/submission_template_source` existed for ZERO designs, `slots/*.yaml` for
ZERO designs, and every one of the 18 `tapeout_declaration.json` fields read
`NOT_DETERMINED`. Both arms of step 37.5ic were starved by that — ours as much
as the operator's, because `general_precheck` compares a layout against a
declaration nobody could fill.

THE PROPERTY THAT MAKES THE CHECK MEAN ANYTHING. Every value that reaches the
declaration must come from the OPERATOR, never from this design's own
artefacts. A die size derived from the floorplan and then used to check that
floorplan is self-certification. So these tests care less about "a number
arrived" than about WHERE it is allowed to come from, and most of them are
about refusing.

WHAT WOULD DEFEAT EACH TEST:
  * the wiring tests    — dropping a program from step 0.5ic's list;
  * the split tests     — letting the operator answer a question about the
                          inside of the die (pads, core area, deliverable);
  * the no-guess tests  — picking a slot when several are on offer, or
                          substituting an offered slot for one the design named;
  * the hash test       — reading a fetched record that changed after ingestion;
  * the absence tests   — turning "this PDK has no operator" into a defect, or
                          "we could not read this operator" into a skip.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import submission_template_answers as ans                      # noqa: E402
import submission_template_fetch as fetch                      # noqa: E402
import _submission_template as _st                             # noqa: E402
import _tapeout_declaration as _decl                           # noqa: E402


# --------------------------------------------------------------------------- #
# 1. The chain is wired into the step that declares it
# --------------------------------------------------------------------------- #
def _step_0_5ic() -> dict:
    import yaml
    doc = yaml.safe_load((_PLUGIN / "flow" / "phase1_phase2_phase3.yaml")
                         .read_text())

    def walk(o):
        if isinstance(o, dict):
            if o.get("id") == "0.5ic":
                return o
            for v in o.values():
                r = walk(v)
                if r:
                    return r
        if isinstance(o, list):
            for v in o:
                r = walk(v)
                if r:
                    return r
        return None
    step = walk(doc)
    assert step is not None, "step 0.5ic is not in the flow"
    return step


def test_the_step_fetches_before_it_ingests():
    """An ingest with nothing to ingest is the state this chain existed to end."""
    progs = _step_0_5ic()["programs"]
    assert "submission_template_fetch" in progs, (
        "step 0.5ic ingests a template nothing fetches, so `slots/*.yaml` can "
        "never exist and every declaration field stays NOT_DETERMINED.")
    assert progs.index("submission_template_fetch") < \
        progs.index("submission_template_ingest"), progs


def test_the_operators_terms_are_transcribed_before_the_declaration_is_built():
    progs = _step_0_5ic()["programs"]
    assert "submission_template_answers" in progs, (
        "`tapeout_declaration_gen` refuses to infer — correctly — so without "
        "this link nothing can ever answer a field.")
    assert progs.index("submission_template_answers") < \
        progs.index("tapeout_declaration_gen"), progs


# --------------------------------------------------------------------------- #
# 2. The split: the operator answers its terms, never the design's
# --------------------------------------------------------------------------- #
_SLOT = {
    "slot": "0p5x0p5",
    "die_area": {"key": "DIE_AREA", "raw": "0 0 1936.0 2531.0",
                 "rect": ["0", "0", "1936.0", "2531.0"]},
    "ring": {"key": "SEAL_RING_WIDTH", "raw": 26, "value": "26"},
}
_SOURCE = {
    "SLOT": "0p5x0p5", "TOP_CELL": "chip_top", "DATABASE_UNIT_UM": 0.001,
    "REQUIRED_MARKER_LAYERS": [
        {"name": "GUARD_RING_MK", "layer": 167, "datatype": 5}],
}


def test_the_operator_answers_only_its_own_terms():
    got, _ = ans.answers_from_slot(_SLOT, _SOURCE)
    assert set(got) <= set(ans.OPERATOR_ANSWERABLE), sorted(got)


def test_the_design_questions_are_never_answered_from_a_template():
    """The inside of the die is not the operator's to state.

    `deliverable`, `core_area_um` and every `pad_*` are choices this design
    makes; answering them from a template would invent an answer it never gave
    — the same defect as inferring a die size from the floorplan, one layer up.
    """
    got, _ = ans.answers_from_slot(_SLOT, _SOURCE)
    for key in ("deliverable", "core_area_um", "pad_order_by_side",
                "pad_site_name", "pad_signal_map", "seal_ring_script"):
        assert key not in got, (
            f"{key} was answered from the operator's template; it is the "
            f"design's to state")


def test_every_operator_answerable_key_is_a_real_declaration_question():
    """An allow-list that drifts from the declaration answers nothing."""
    keys = {q.key for q in _decl.QUESTIONS}
    stray = sorted(set(ans.OPERATOR_ANSWERABLE) - keys)
    assert not stray, f"OPERATOR_ANSWERABLE names non-questions: {stray}"


def test_the_die_rectangle_and_its_origin_come_from_the_template():
    got, _ = ans.answers_from_slot(_SLOT, _SOURCE)
    assert got["die_area_um"] == [0.0, 0.0, 1936.0, 2531.0]
    assert got["die_origin_um"] == [0.0, 0.0]
    assert got["fp_sizing"] == ans._absolute_sizing(), (
        "a relative sizing would make the die a consequence of this design's "
        "own utilisation — the number it is then checked against")


def test_a_template_that_states_nothing_answers_nothing():
    """Absent is omitted, never defaulted: an emitted default reads downstream
    exactly like a term the operator stated."""
    got, _ = ans.answers_from_slot({"slot": "x"}, {})
    assert got == {}


def test_several_required_markers_do_not_elect_a_seal_ring_layer():
    src = dict(_SOURCE, REQUIRED_MARKER_LAYERS=[
        {"name": "GUARD_RING_MK", "layer": 167, "datatype": 5},
        {"name": "OTHER_MK", "layer": 1, "datatype": 2}])
    got, notes = ans.answers_from_slot(_SLOT, src)
    assert got["seal_ring_required"] is True
    assert "seal_ring_marker_layer" not in got, (
        "which of several required markers is the SEAL RING's was not stated; "
        "picking one is a guess wearing an operator's authority")
    assert any("NOT_DETERMINED" in n for n in notes)


# --------------------------------------------------------------------------- #
# 3. Refusals — the part that makes the rest trustworthy
# --------------------------------------------------------------------------- #
def _ingested(tmp: Path, slots: dict) -> Path:
    src = tmp / fetch.SOURCE_REL
    src.mkdir(parents=True, exist_ok=True)
    d = tmp / _st.SLOTS_DIR_REL
    d.mkdir(parents=True, exist_ok=True)
    import hashlib
    for name in slots:
        raw = json.dumps(dict(_SOURCE, SLOT=name))
        (src / f"{name}.json").write_text(raw)
        (d / f"{name}.yaml").write_text(json.dumps(dict(
            _SLOT, slot=name,
            source_file=str(src / f"{name}.json"),
            source_sha256=hashlib.sha256(raw.encode()).hexdigest())))
    return tmp


def test_several_slots_and_no_declared_slot_transcribes_nothing(tmp_path):
    """AN OPEN QUESTION, NOT A MALFUNCTION, and the distinction is load-bearing.

    The design has not said which slot it bought, so there is nothing to
    transcribe — but `tapeout_declaration_gen` is built to CARRY an unanswered
    question, and step 37.5ic refuses later with the layout in hand. Failing
    phase 1 here would make every design hostage to a question that only
    matters at tape-out, and a step that cannot be got past gets worked around.
    """
    _ingested(tmp_path, {"0p5x0p5": 1, "1x1": 1})
    rep = ans.build(tmp_path)
    assert rep["verdict"] == ans.NOT_DETERMINED
    assert rep["answers"] == {}
    assert "has not said which" in rep["reason"]


def test_a_slot_the_operator_does_not_sell_transcribes_nothing(tmp_path):
    """And it must NOT substitute one that is on offer."""
    _ingested(tmp_path, {"0p5x0p5": 1, "1x1": 1})
    rep = ans.build(tmp_path, "9x9")
    assert rep["verdict"] == ans.NOT_DETERMINED
    assert rep["answers"] == {}


def test_a_source_edited_after_ingestion_is_refused_not_read(tmp_path):
    """The hash the ingest recorded is the binding between the two files.

    Without this, an edit to the fetched record after ingestion would put a
    number the operator never published into the design's own declaration.
    """
    _ingested(tmp_path, {"0p5x0p5": 1})
    tampered = tmp_path / fetch.SOURCE_REL / "0p5x0p5.json"
    tampered.write_text(json.dumps(dict(_SOURCE, TOP_CELL="not_chip_top")))
    rep = ans.build(tmp_path, "0p5x0p5")
    assert "top_cell" not in rep["answers"], (
        "a tampered source was read; the declaration would carry a term the "
        "operator never published")
    assert any("changed since it was ingested" in n for n in rep["notes"])


def test_no_slots_at_all_is_not_applicable_not_a_defect(tmp_path):
    """A PDK with no operator has nobody to transcribe — that is legitimate."""
    rep = ans.build(tmp_path)
    assert rep["verdict"] == ans.NOT_APPLICABLE
    assert rep["answers"] == {}


def test_a_pdk_with_no_live_shuttle_fetches_nothing_and_says_so(tmp_path):
    rep = fetch.fetch(tmp_path, pdk="a_pdk_no_operator_serves")
    assert rep["verdict"] == fetch.NOT_APPLICABLE
    assert rep["slots_written"] == []


def test_an_undeclared_pdk_is_not_reported_as_having_no_operator(tmp_path):
    """Not knowing the process is not the same as there being no operator.

    NOT_DETERMINED, never NOT_APPLICABLE: the second would say "there was
    nothing to look at" about a design nobody looked for. It is rc 0 because
    the refusal belongs at 37.5ic with the layout in hand, but the two states
    must stay distinguishable in the record.
    """
    rep = fetch.fetch(tmp_path, pdk="")
    assert rep["verdict"] == fetch.NOT_DETERMINED
    assert rep["verdict"] != fetch.NOT_APPLICABLE
    assert "declares no PDK" in rep["reason"]


def test_every_adapter_is_keyed_by_a_shuttle_the_registry_knows():
    """An adapter for a shuttle nobody lists can never run, and hides that it
    was written for a counterparty that no longer exists."""
    import tapeout_readiness_check as _theirs
    reg = getattr(_theirs, "SHUTTLES", None)
    items = list(reg.values()) if isinstance(reg, dict) else list(reg or ())
    known = {getattr(s, "shuttle_id", None) for s in items} - {None}
    if not known:
        pytest.skip("NOT_VERIFIED: the registry did not enumerate any shuttle, "
                    "so the adapter keys were not cross-checked")
    stray = sorted(set(fetch.ADAPTERS) - known)
    assert not stray, f"adapters for unknown shuttles: {stray}"


def test_a_floating_tag_is_not_accepted_as_provenance(monkeypatch):
    """`:latest` names different bytes next week; a submission record cannot
    rest on it."""
    monkeypatch.setattr(fetch, "_run",
                        lambda *a, **k: (0, "some/image:latest\n", ""))
    digest, why = fetch.resolve_image_digest("some/image:latest", False)
    assert digest is None
    assert "digest" in why
