"""tests/test_ic_class_analog_low_confidence.py

Regression for ORGANIC-20260528-analog-ic-misclassified-digital-low-confidence
(v0.2.30).

Bug: `ic_class_profile._l5_has_analog` dropped EVERY block flagged
`low_confidence:true`.  The Phase-1 L5 ingester tags every block
low_confidence when an analog datasheet publishes its numeric specs as
figures (the canonical ΔΣ / SAR teaching-chip pattern → spec fields
null).  So has_analog=False → the IC fell through to the
`digital_arithmetic_primitive` catch-all and the analog A1..A9 track was
never reached.

Fix: low_confidence now means "specs are figure-only", NOT "maybe not
analog".  A low_confidence block with a concrete extracted instance
count (count / multiplicity) is a genuine analog marker; parity-stub
artifacts (extraction_strategy == l5_parity_stub*, or a bare token-only
low_confidence block with no instance count) are still suppressed so a
digital chip whose datasheet merely *mentions* a DAC/ESD in N/A context
does not get flipped to analog.  L1 may also declare an analog class
directly.

Three required cases:
  * PASS path        — synthetic mixed-signal / ADC doc (figure-only
                       low_confidence blocks) routes to the analog track.
  * real FAIL path   — synthetic digital doc whose L5 carries ONLY a
                       spurious token-only low_confidence stub stays
                       digital (the misfire the fix must NOT cause).
  * missing-data     — no L docs at all → unknown / fail-closed, never a
                       vacuous analog PASS.
"""
from __future__ import annotations

import json
from pathlib import Path

from ic_class_profile import (
    detect_ic_class,
    _l5_has_analog,
    _block_is_analog_marker,
    _l1_declares_analog_class,
)


def _write_l_docs(project: Path, docs: dict) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    for fname, data in docs.items():
        (gd / fname).write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------
# PASS path — figure-only ΔΣ ADC routes to the analog track.
# Mirrors the real University-of-Hawaii incremental ΔΣ ADC L5 doc:
# every block low_confidence (specs are figures), but a concrete
# extracted instance count is present.
# ---------------------------------------------------------------------
def test_figure_only_adc_routes_to_analog(tmp_path: Path) -> None:
    project = tmp_path / "synth_adc"
    project.mkdir(parents=True, exist_ok=True)
    _write_l_docs(project, {
        "L1_DATASHEET.json": {
            "ic_name": "SYNTH-ADC",
            "doc_class": "datasheet",
            "description": ("This chip contains six copies of an "
                            "incremental delta-sigma modulator (one of "
                            "them is powered by an LDO)."),
        },
        "L5_ADI_SPEC.json": {
            "analog_blocks_detected": True,
            "no_analog": False,
            "analog_blocks": [
                {"name": "ldo", "type": "ldo", "spec": None,
                 "low_confidence": True, "count": 1, "multiplicity": 1,
                 "evidence_paragraph": "powered by an LDO"},
                {"name": "delta_sigma", "type": "delta_sigma",
                 "spec": None, "low_confidence": True,
                 "count": 6, "multiplicity": 6,
                 "evidence_paragraph": ("six copies of an incremental "
                                        "delta-sigma modulator")},
            ],
        },
    })
    profile = detect_ic_class(project)
    assert profile["has_analog"] is True, (
        "figure-only low_confidence ADC blocks with a real instance "
        "count must count as analog markers")
    assert profile["is_pure_analog"] is True
    # The whole point: it must NOT fall to the digital catch-all.
    assert profile["ic_class"] == "pure_analog"
    assert profile["ic_class"] != "digital_arithmetic_primitive"


def test_l1_declared_mixed_signal_class_forces_analog(tmp_path: Path) -> None:
    """L1 declares a mixed-signal class explicitly — analog regardless of
    whether any L5 block survived the figure-only filter."""
    project = tmp_path / "synth_l1_mixed"
    project.mkdir(parents=True, exist_ok=True)
    _write_l_docs(project, {
        "L1_DATASHEET.json": {
            "ic_name": "SYNTH-MS",
            "class": "mixed_signal_adc",
        },
        # L5 carries ONLY token-only low_confidence stubs (would NOT pass
        # the L5 filter on their own) — L1 class must still win.
        "L5_ADI_SPEC.json": {
            "analog_blocks_detected": True,
            "analog_blocks": [
                {"name": "adc", "type": "adc", "spec": None,
                 "low_confidence": True},
            ],
        },
    })
    profile = detect_ic_class(project)
    assert _l1_declares_analog_class(
        {"class": "mixed_signal_adc"}) is True
    assert profile["has_analog"] is True
    assert profile["ic_class"] == "pure_analog"


def test_l1_class_path_pure_analog_forces_analog() -> None:
    """Real Path-B README detector writes the class into `class_path`."""
    assert _l1_declares_analog_class({"class_path": "pure_analog"}) is True
    assert _l1_declares_analog_class({"class_path": "sar_adc"}) is True


# ---------------------------------------------------------------------
# real FAIL path — a digital chip whose L5 carries ONLY a spurious
# token-only low_confidence stub (no instance count, N/A context) must
# stay digital.  This is the misfire the fix must NOT introduce — it is
# the exact shape of the sha256 / spdif / ethernet stub blocks in the
# real corpus.
# ---------------------------------------------------------------------
def test_digital_chip_with_spurious_stub_stays_digital(tmp_path: Path) -> None:
    project = tmp_path / "synth_digital"
    project.mkdir(parents=True, exist_ok=True)
    _write_l_docs(project, {
        "L1_DATASHEET.json": {
            "ic_name": "SYNTH-HASH",
            "class_path": "digital_arithmetic_primitive",
            "description": "A combinational SHA-256 message-digest core.",
        },
        "L5_ADI_SPEC.json": {
            "analog_blocks_detected": True,
            "no_analog": False,
            "analog_blocks": [
                # parity-stub: token seen only in negative / N/A context
                {"name": "dac", "type": "dac", "spec": None,
                 "low_confidence": True,
                 "evidence_paragraph": ("→ Plugin 不需產生 calibration "
                                        "controller、analog trim DAC 等。")},
                # explicit v1.6.269 parity stub marker
                {"name": "esd", "type": "esd", "spec": None,
                 "low_confidence": True,
                 "extraction_strategy": "l5_parity_stub_v1_6_269",
                 "evidence_paragraph": "low-confidence stub emitted ..."},
            ],
        },
    })
    profile = detect_ic_class(project)
    assert profile["has_analog"] is False, (
        "token-only low_confidence stubs with no instance count must NOT "
        "flip a digital chip to analog")
    assert profile["ic_class"] == "digital_arithmetic_primitive"


def test_block_marker_helper_discriminates() -> None:
    # high-confidence block: always a marker
    assert _block_is_analog_marker(
        {"name": "pll", "low_confidence": False}) is True
    # figure-only low_confidence WITH instance count: marker
    assert _block_is_analog_marker(
        {"name": "delta_sigma", "low_confidence": True, "count": 6}) is True
    assert _block_is_analog_marker(
        {"name": "ldo", "low_confidence": True, "multiplicity": 1}) is True
    # token-only low_confidence, NO count: NOT a marker
    assert _block_is_analog_marker(
        {"name": "dac", "low_confidence": True}) is False
    # explicit parity stub, even if it somehow carried a count: NOT a marker
    assert _block_is_analog_marker(
        {"name": "esd", "low_confidence": True, "count": 3,
         "extraction_strategy": "l5_parity_stub_v1_6_269"}) is False
    # count must be a positive int, not a bool / zero / string
    assert _block_is_analog_marker(
        {"name": "x", "low_confidence": True, "count": 0}) is False
    assert _block_is_analog_marker(
        {"name": "x", "low_confidence": True, "count": True}) is False


# ---------------------------------------------------------------------
# missing-data honesty — no L docs → unknown / fail-closed.  A check on
# absent data must NOT vacuously PASS as analog.
# ---------------------------------------------------------------------
def test_missing_l_docs_is_fail_closed(tmp_path: Path) -> None:
    project = tmp_path / "empty"
    project.mkdir(parents=True, exist_ok=True)
    profile = detect_ic_class(project)
    assert profile["has_analog"] is False
    assert profile["is_pure_analog"] is False
    assert profile["ic_class"] == "unknown"


def test_l5_has_analog_on_none_and_no_analog() -> None:
    assert _l5_has_analog(None) is False
    assert _l5_has_analog({}) is False
    # explicit no_analog wins over any block list
    assert _l5_has_analog(
        {"no_analog": True,
         "analog_blocks": [{"name": "pll", "low_confidence": False}]}
    ) is False
    # an L doc with no analog_blocks at all → False (not vacuous True)
    assert _l5_has_analog({"analog_blocks_detected": True}) is False


# ---------------------------------------------------------------------
# corpus anchor — the live reproduction must route to the analog track
# and the real digital benchmarks must stay digital, if the corpus is
# present in this checkout.  Skips cleanly when run outside the repo.
# ---------------------------------------------------------------------
def _repo_benchmark(rel: str) -> Path | None:
    here = Path(__file__).resolve()
    for anc in here.parents:
        cand = anc / rel
        if (cand / "phase1" / "generated_docs").is_dir():
            return cand
    return None


def test_corpus_real_adc_routes_analog_and_digital_stays_digital() -> None:
    adc = _repo_benchmark("benchmark_ic/4th__U_Hawaii_DeltaSigma_ADC")
    if adc is not None:
        prof = detect_ic_class(adc)
        assert prof["has_analog"] is True
        assert prof["ic_class"] == "pure_analog"
    for rel in ("benchmark_ic/4th__sha256_v2", "benchmark_ic/4th__spm",
                "benchmark_phase1/spdif", "benchmark_phase1/ethernet"):
        d = _repo_benchmark(rel)
        if d is None:
            continue
        prof = detect_ic_class(d)
        assert prof["has_analog"] is False, (
            f"{rel} must NOT be flipped to analog by the fix")
