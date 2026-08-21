#!/usr/bin/env python3
"""L8 must declare exactly one period per clock name — or say it cannot.

A converged run shipped ``L8_TIMING_WAVEFORM.json`` carrying::

    clocks[0]         name=clk  freq_mhz=100.0   -> 10 ns
    clock_domains[0]  name=clk  freq_mhz=100.0   -> 10 ns
    clock_domains[1]  name=clk  freq_mhz=125.0   ->  8 ns

One clock, two periods. Two independent phase-1 extraction strategies wrote
into the same list and nothing compared them, so ``sdc_validator_check``
correctly refused to validate an SDC against the document — and every other
consumer quietly picked a period by list position instead.

These tests are about the PRODUCER. They assert observable properties of the
emitted document, never a source substring or a private symbol, so any
correct fix satisfies them:

  * a document phase 1 emits never declares two different periods for one
    clock name (measured with ``sdc_validator_check``'s own reader, so the
    producer and the consumer cannot disagree about what a contradiction is);
  * when a frequency mention is folded away it is still IN the document —
    reconciliation must not be silent deletion;
  * when the contradiction is NOT reconcilable, the producer REFUSES: it
    records the conflict, keeps BOTH records, and blocks — it never picks.

All inputs are synthetic, with frequencies (62.5 / 80 / 25 MHz, 6.25 ns,
3.125 ns) and port names deliberately unlike any real design, so a fix that
hardcodes a number or a chip name cannot pass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as P1     # noqa: E402
import sdc_validator_check as SDCV          # noqa: E402

#: Public document field the producer stamps when it REFUSES to reconcile.
CONFLICT_KEY = "clock_contract_conflicts"


# ---------------------------------------------------------------------------
# helpers — all property-level, none of them reach into the fix
# ---------------------------------------------------------------------------
def _project(tmp_path: Path, clock_port: str = "sysclk") -> Path:
    """A project with just enough on disk for the L8 emitter to run."""
    proj = tmp_path / "proj"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(
        json.dumps({"pin_table": [{"name": clock_port, "mode": "input"}]}),
        encoding="utf-8")
    return proj


def _load(proj: Path, doc: str) -> dict:
    return json.loads(
        (proj / "phase1" / "generated_docs" / f"{doc}.json").read_text())


def _periods_by_name(doc: dict) -> dict:
    """``{clock_name: [distinct periods in ns]}`` as the CONSUMER sees it.

    Deliberately routed through ``sdc_validator_check`` so this test measures
    the same thing the gate does; a fix that satisfies the test by teaching
    the producer a different notion of "same period" would not pass.
    """
    return {name: SDCV._distinct_periods(slot["periods"])
            for name, slot in SDCV.l8_clock_periods(doc).items()}


def _all_numbers(blob) -> set:
    """Every float appearing anywhere in a JSON-ish structure."""
    out = set()
    if isinstance(blob, dict):
        for v in blob.values():
            out |= _all_numbers(v)
    elif isinstance(blob, list):
        for v in blob:
            out |= _all_numbers(v)
    elif isinstance(blob, (int, float)) and not isinstance(blob, bool):
        out.add(round(float(blob), 6))
    return out


#: A design doc that states ONE clock at several library-conditional target
#: periods — the shape that produced the real defect. The first stated
#: frequency is the design's headline target.
_MULTI_TARGET_DOC = """\
# Product metadata

## Tapeout targets

| Field | Value |
|---|---|
| Target clock period — baseline library | 16 ns (62.5 MHz) |
| Target clock period — high-speed library | 12.5 ns (80 MHz) |
| Target clock period — low-power library | 40 ns (25 MHz) |

The core clock is a single external clock input; the three rows above are the
same clock constrained differently per standard-cell library.
"""


# ===========================================================================
# 1. the producer, driven from a design's own text
# ===========================================================================
def test_emitted_l8_never_declares_two_periods_for_one_clock(tmp_path):
    """The defect, at the producer, from the input that causes it."""
    proj = _project(tmp_path)
    P1.gen_l8_timing_waveform(proj, {"product_overview.md": _MULTI_TARGET_DOC})
    doc = _load(proj, "L8_RTL_CONSTANTS")

    periods = _periods_by_name(doc)
    assert periods, "the emitter produced no clock record at all"
    for name, distinct in periods.items():
        assert len(distinct) <= 1, (
            f"clock {name!r} was emitted with {len(distinct)} periods "
            f"{distinct} — one clock name must declare one period")


def test_emitted_l8_passes_the_gate_that_reads_it(tmp_path):
    """The consumer's own verdict on the producer's output."""
    proj = _project(tmp_path)
    P1.gen_l8_timing_waveform(proj, {"product_overview.md": _MULTI_TARGET_DOC})
    doc = _load(proj, "L8_RTL_CONSTANTS")

    assert SDCV.l8_self_issues(doc, None) == [], (
        "phase 1 emitted a document its own SDC validator refuses")


def test_the_headline_target_is_the_one_that_survives(tmp_path):
    """Reconciliation follows a stated rule, not list order.

    The record that OWNS the clock name — the design's headline target, read
    with file/line evidence — is the contract. 80 MHz and 25 MHz were bare
    frequency literals that had a clock name stapled onto them.
    """
    proj = _project(tmp_path)
    P1.gen_l8_timing_waveform(proj, {"product_overview.md": _MULTI_TARGET_DOC})
    doc = _load(proj, "L8_RTL_CONSTANTS")

    periods = _periods_by_name(doc)
    surviving = {p for ps in periods.values() for p in ps}
    assert surviving == {16.0}, (
        f"expected the 62.5 MHz headline target (16 ns) to be the contract, "
        f"got {sorted(surviving)}")


def test_the_folded_frequencies_are_still_in_the_document(tmp_path):
    """Reconciling is not deleting.

    A number the extractor read out of the design's own doc must not vanish
    because it lost a precedence rule; a reviewer has to be able to see that
    the doc also mentioned 80 MHz and 25 MHz.
    """
    proj = _project(tmp_path)
    P1.gen_l8_timing_waveform(proj, {"product_overview.md": _MULTI_TARGET_DOC})
    doc = _load(proj, "L8_RTL_CONSTANTS")

    present = _all_numbers(doc.get("clock_domains"))
    assert 80.0 in present and 25.0 in present, (
        "the frequencies that lost the precedence rule were dropped from the "
        "document instead of being kept as evidence")


# ===========================================================================
# 2. the guard — a contradiction must not be able to reach a document
# ===========================================================================
def _two_owner_conflict() -> dict:
    """Two records that each OWN the name and pin different periods.

    Neither carries a borrowed-name marker, so no stated rule ranks one over
    the other. This is the case the producer must refuse.
    """
    return {
        "schema_version": "1",
        "doc_class": "timing_waveform",
        "ic_name": "synthetic_block",
        "clock_domains": [
            {"name": "core_ck", "role": "primary", "domain_kind": "primary",
             "period_ns": 6.25, "extraction_strategy": "strategy_a"},
            {"name": "core_ck", "role": "primary", "domain_kind": "primary",
             "period_ns": 3.125, "extraction_strategy": "strategy_b"},
        ],
    }


def test_write_chokepoint_refuses_a_self_contradictory_contract(tmp_path):
    """Written through the emitter chokepoint, the document says so."""
    proj = _project(tmp_path)
    P1._write_l_doc(proj, "L8_TIMING_WAVEFORM", _two_owner_conflict(), {})
    doc = _load(proj, "L8_TIMING_WAVEFORM")

    conflicts = doc.get(CONFLICT_KEY)
    assert isinstance(conflicts, list) and conflicts, (
        "a document declaring one clock at two periods was written with no "
        f"{CONFLICT_KEY} record — the contradiction shipped silently")
    assert any(c.get("clock") == "core_ck" for c in conflicts)


def test_refusing_keeps_both_periods_rather_than_picking_one(tmp_path):
    """Refusal, not a quiet choice.

    Dropping one of the two records would make every downstream gate green
    while inventing a timing contract nobody stated. Both must survive.
    """
    proj = _project(tmp_path)
    P1._write_l_doc(proj, "L8_TIMING_WAVEFORM", _two_owner_conflict(), {})
    doc = _load(proj, "L8_TIMING_WAVEFORM")

    periods = _periods_by_name(doc)
    assert sorted(periods.get("core_ck", [])) == [3.125, 6.25], (
        "the producer silently picked one of two contradictory periods")
    assert SDCV.l8_self_issues(doc, None), (
        "the consumer gate must still see the contradiction it is there to "
        "catch — the producer must not mask it")


def test_the_run_blocks_on_a_conflict_it_cannot_reconcile(tmp_path):
    """Fail-closed: the runner's post-pass reports it, so the run exits 1."""
    proj = _project(tmp_path)
    gd = proj / "phase1" / "generated_docs"
    (gd / "L8_TIMING_WAVEFORM.json").write_text(
        json.dumps(_two_owner_conflict(), indent=2), encoding="utf-8")

    messages = P1._post_emit_enforce_clock_contract(proj)
    assert messages, ("an unreconcilable clock contradiction on disk did not "
                      "block the run")
    assert any("core_ck" in m for m in messages)


def test_a_reconcilable_document_does_not_block_the_run(tmp_path):
    """The guard blocks contradictions, not merely duplicate rows."""
    proj = _project(tmp_path)
    gd = proj / "phase1" / "generated_docs"
    (gd / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "schema_version": "1", "doc_class": "timing_waveform",
        "ic_name": "synthetic_block",
        "clock_domains": [
            {"name": "core_ck", "role": "primary", "domain_kind": "primary",
             "period_ns": 6.25, "extraction_strategy": "strategy_a",
             "evidence": {"file": "input/docs/x.md", "line": 3}},
            # borrowed name: a bare literal that took the canonical port name
            {"name": "core_ck", "derived_from": "core_ck",
             "role": "extracted_from_doc_freq_mention", "freq_mhz": 320.0,
             "extraction_strategy": "doc_freq_mention_keyword_window"},
        ],
    }, indent=2), encoding="utf-8")

    assert P1._post_emit_enforce_clock_contract(proj) == []
    doc = _load(proj, "L8_TIMING_WAVEFORM")
    assert _periods_by_name(doc)["core_ck"] == [6.25]
    assert 320.0 in _all_numbers(doc["clock_domains"]), (
        "the borrowed record's frequency was deleted rather than kept as "
        "evidence")


def test_a_genuinely_derived_clock_is_not_a_conflict(tmp_path):
    """Do not over-block: a generated clock legitimately runs at its own
    period and is constrained by create_generated_clock, not create_clock."""
    proj = _project(tmp_path)
    gd = proj / "phase1" / "generated_docs"
    (gd / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "schema_version": "1", "doc_class": "timing_waveform",
        "ic_name": "synthetic_block",
        "clock_domains": [
            {"name": "core_ck", "role": "primary", "domain_kind": "primary",
             "period_ns": 6.25},
            {"name": "div_ck", "role": "derived", "domain_kind": "derived",
             "derived_from": "core_ck", "period_ns": 25.0},
        ],
    }, indent=2), encoding="utf-8")

    assert P1._post_emit_enforce_clock_contract(proj) == []
    doc = _load(proj, "L8_TIMING_WAVEFORM")
    assert len(doc["clock_domains"]) == 2, (
        "a derived clock was folded into its parent")


def test_enforcement_is_idempotent(tmp_path):
    """Running the producer's guard twice must not change its verdict."""
    proj = _project(tmp_path)
    gd = proj / "phase1" / "generated_docs"
    (gd / "L8_TIMING_WAVEFORM.json").write_text(
        json.dumps(_two_owner_conflict(), indent=2), encoding="utf-8")

    first = P1._post_emit_enforce_clock_contract(proj)
    doc_a = _load(proj, "L8_TIMING_WAVEFORM")
    second = P1._post_emit_enforce_clock_contract(proj)
    doc_b = _load(proj, "L8_TIMING_WAVEFORM")
    assert first == second
    assert doc_a == doc_b


def test_a_resolved_conflict_record_does_not_linger(tmp_path):
    """A stale conflict must not fail a document that is now consistent."""
    proj = _project(tmp_path)
    gd = proj / "phase1" / "generated_docs"
    (gd / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "schema_version": "1", "doc_class": "timing_waveform",
        "ic_name": "synthetic_block",
        "clock_domains": [
            {"name": "core_ck", "role": "primary", "period_ns": 6.25},
        ],
        CONFLICT_KEY: [{"clock": "core_ck", "periods_ns": [3.125, 6.25]}],
    }, indent=2), encoding="utf-8")

    assert P1._post_emit_enforce_clock_contract(proj) == []
    assert CONFLICT_KEY not in _load(proj, "L8_TIMING_WAVEFORM")


# ===========================================================================
# 3. the real converged artifact this job was opened on
# ===========================================================================
# programs/ -> vibe-ic -> plugins -> vibe-ic-marketplace -> repo root
_SPM_L8 = (_PROGRAMS.parents[3] / "benchmark-data" / "ic" / "spm"
           / "v1.5.58_ihp-sg13g2" / "phase1" / "generated_docs"
           / "L8_TIMING_WAVEFORM.json")


@pytest.mark.skipif(not _SPM_L8.is_file(),
                    reason="checked-in converged artifact not present")
def test_the_shipped_artifact_shape_is_reconciled_not_refused(tmp_path):
    """The measured defect, replayed through the producer's guard.

    The shipped document's two `clk` records are the borrowed-name shape, so
    the guard reconciles them by the stated rule and the SDC validator's
    complaint goes away for the right reason: the document now declares the
    one period the SDC was actually built to.
    """
    proj = _project(tmp_path)
    gd = proj / "phase1" / "generated_docs"
    (gd / "L8_TIMING_WAVEFORM.json").write_text(
        _SPM_L8.read_text(), encoding="utf-8")

    assert P1._post_emit_enforce_clock_contract(proj) == []
    doc = _load(proj, "L8_TIMING_WAVEFORM")
    assert SDCV.l8_self_issues(doc, None) == []
    assert _periods_by_name(doc) == {"clk": [10.0]}
    assert 125.0 in _all_numbers(doc["clock_domains"]), (
        "the 125 MHz mention was deleted instead of kept as evidence")
