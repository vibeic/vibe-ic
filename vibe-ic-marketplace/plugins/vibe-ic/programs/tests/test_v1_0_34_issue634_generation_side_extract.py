#!/usr/bin/env python3
"""Generation-side residual of ORGANIC #634 — the data-converter / mixed-signal
typed-field gate (l_doc_structured_field_count_check) was already relaxed
gate-side (facets b + c, v1.0.32: data_converter gets L5 ≥2 / L8 ≥3 via
`sparse_analog_block_set` + `sparse_control_timing`). But a sparse converter
spec still FAILed END-TO-END because the phase-1 GENERATORS never POPULATED the
relaxed-floor docs from a spec-table + a Verification-intent bullet section.

This change ships the three GENERATION-side extraction facets (a / d / e) in
phase1_doc_one_shot_runner so a content-rich converter doc clears the gate
end-to-end:

  (a) L8 spec-table timing harvest — a converter documents its timing surface
      in a markdown spec table whose NAME / VALUE / UNIT live in SEPARATE cells
      (`| fclk | 1.0 | 0.1-10 | MHz |`) plus unitless converter scalars
      (`OSR = 256` / `Order = 2`). The existing clock regex needs the literal
      word `clock` before the number and the inline / SATA pickers need
      value+unit adjacency, so NONE of them reach a spec-table fclk row. A new
      chip-AGNOSTIC harvester (`_v634_harvest_converter_timing`) reads those
      shapes into typed `timing_constants` in BOTH L8 docs (L8_RTL_CONSTANTS +
      the L8_TIMING_WAVEFORM sidecar, the one that FAILed at 2 < 3).

  (d) L7 / L10 verification-intent harvest — a converter spec carries its
      verification plan as a literal `## Verification intent (drives L7 /
      Pillar 5)` bullet section (DC op-point / line-load regulation /
      SNDR-ENOB / multi-corner), NOT a numbered `phase N:` template nor a
      verification-plan TABLE, so the existing L7/L10 harvesters miss it. A new
      chip-AGNOSTIC harvester (`_v634_harvest_verification_intent`) mines those
      bullets into typed `verification_strategy` (L7) and `test_cases` (L10),
      bounded to the section body (stops at the next heading).

  (e) L12 `no_calibration` auto-set — when the input carries NO calibration /
      trim / OTP-cal SOURCE and no behavioral sequences were harvested,
      `gen_l12_behavioral` auto-sets `no_calibration: true` (absence-based,
      mirroring the L5.no_analog auto-detection). The gate already accepts
      `no_calibration: true`.

This test builds the defect-artifact converter fixture shaped like the issue's
現象 and invokes the REAL generators + the REAL gate to assert the END-STATE
PASS — not mere file existence. The NEGATIVE no-leak half is load-bearing:

  * an EMPTY converter doc (no spec table, no Verification-intent section, no
    cal source) still emits 0 verification_strategy / 0 timing_constants / 0
    test_cases and still FAILs the gate — never fabricates;
  * a doc that DOES document a calibration source keeps `no_calibration` False
    (the honest-N/A is not handed to a part that genuinely has calibration);
  * the converter-scalar harvest ignores generic digital scalars
    (`width = 32` / `bits = 8`) and the verification-intent harvest ignores a
    generic `## Test plan` heading.

chip-AGNOSTIC: spec-table SHAPE + open data-converter vocabulary + a generic
section-heading + bullet SHAPE; no chip / vendor / SKU literal anywhere.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import ic_class_profile as ICP                       # noqa: E402
import l_doc_structured_field_count_check as G       # noqa: E402
import phase1_doc_one_shot_runner as R               # noqa: E402


# ── input-doc fixtures (shape the 現象) ───────────────────────────────────────

_L1_TEXT = (
    "class: mixed_signal_adc\n"
    "Multi-channel 2nd-order sigma-delta converter front-end.\n"
    "Digital serial outputs OUT1..OUT6 (+ dout serial) — a digital "
    "bitstream per channel.\n")

_L5_RICH = """# L5 Analog Spec — delta-sigma ADC

## Analog blocks

| Block | Type | Spec |
| --- | --- | --- |
| modulator | delta_sigma | 2nd-order, SNR 90 dB |
| ldo | ldo | 3.3 V on-chip regulator |

## Modulator timing

| Param | Typ | Range | Unit | Note |
| --- | --- | --- | --- | --- |
| fclk | 1.0 | 0.1-10 | MHz | modulator clock (CK4/5/6) (est) |

OSR = 256
Order = 2

The analog modulator output is a 1-bit serial (OUTn / dout) digital bitstream
per channel.

## Verification intent (drives L7 / Pillar 5)

- DC operating-point check across the analog front-end (bias, common-mode).
- Line and load regulation of the on-chip LDO over the supply range.
- SNDR / ENOB transient with an input sine sweep at multiple amplitudes.
- Multi-corner (TT/SS/FF, temperature) re-simulation of the modulator.
"""

# An EMPTY converter doc — analog prose only, NO spec table, NO Verification
# intent section, NO calibration source. The no-leak fixture.
_L5_EMPTY = (
    "# L5 Analog Spec\n"
    "A delta-sigma modulator and an on-chip LDO. No further detail.\n"
    "Digital serial outputs OUT1..OUT6 (+ dout serial).\n")


def _gd(proj: Path) -> Path:
    return ICP._pl.generated_docs_dir(proj)


def _load(proj: Path, name: str) -> dict:
    p = _gd(proj) / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _build_converter_project(root: Path, l5_text: str,
                             rich_l1: bool = True) -> Path:
    """Run the REAL phase-1 generators on a converter input set and persist a
    data_converter ic_class. `rich_l1` writes a ≥10-field L1 stub so the L1
    floor (not under test here) does not mask the L5/L7/L8/L10/L12 verdicts."""
    proj = root
    indocs = proj / "input" / "docs"
    indocs.mkdir(parents=True, exist_ok=True)
    (indocs / "L1_DATASHEET.md").write_text(_L1_TEXT, encoding="utf-8")
    (indocs / "L5_ANALOG_SPEC.md").write_text(l5_text, encoding="utf-8")
    extracted = {"L1_DATASHEET.md": _L1_TEXT, "L5_ANALOG_SPEC.md": l5_text}

    gd = _gd(proj)
    gd.mkdir(parents=True, exist_ok=True)
    # L1 scaffolding (≥10 typed fields) — NOT part of facets a/d/e.
    l1_doc = {
        "schema_version": "1.0", "doc_class": "L1_DATASHEET",
        "ic_name": "generic_converter", "class": "mixed_signal_adc",
        "description": ("sigma-delta converter; Digital serial outputs "
                        "OUT1..OUT6 (+ dout serial)."),
    }
    if rich_l1:
        l1_doc.update({
            "overview": "delta-sigma ADC", "supply_v": 3.3,
            "temp_range_c": "-40..125", "package": "QFN-24",
            "channels": 6, "resolution_bits": 16,
            "interface": "serial bitstream", "vendor": "generic",
            "pin_count": 24, "process_node": "180nm",
        })
    (gd / "L1_DATASHEET.json").write_text(json.dumps(l1_doc), encoding="utf-8")

    R.gen_l5_adi_spec(proj, extracted)
    l3 = {"opcodes": []}
    R.gen_l7_test_debug(proj, extracted)
    R.gen_l8_timing_waveform(proj, extracted)
    R.gen_l8_timing_waveform_doc(proj, extracted)
    R.gen_l10_test_cases(proj, extracted, l3)
    R.gen_l12_behavioral(proj, extracted, l3)
    ICP.detect_ic_class(proj, refresh=True)
    return proj


# ── (A) END-TO-END: the rich converter spec now clears the gate ──────────────

def test_rich_converter_clears_gate_end_to_end(tmp_path):
    proj = _build_converter_project(tmp_path / "rich", _L5_RICH)
    # The persisted class is data_converter (drives the relaxed floors).
    prof = json.loads(
        (proj / "reports" / "ic_class.json").read_text(encoding="utf-8"))
    assert prof["ic_class"] == "data_converter"

    rc = G.main([str(proj)])
    assert rc == 0, "rich data-converter spec must clear the gate end-to-end"


# ── (B) per-facet END-STATES on the REAL generated docs ──────────────────────

def test_facet_a_l8_spec_table_timing_harvested(tmp_path):
    """L8 — fclk (spec-table name/value/unit) + OSR + Order (converter
    scalars) land as typed timing_constants in BOTH L8 docs, clearing the
    relaxed ≥3 floor (the L8_TIMING_WAVEFORM sidecar FAILed at 2 pre-fix)."""
    proj = _build_converter_project(tmp_path / "a", _L5_RICH)
    for fn in ("L8_RTL_CONSTANTS.json", "L8_TIMING_WAVEFORM.json"):
        doc = _load(proj, fn)
        names = {tc.get("name") for tc in (doc.get("timing_constants") or [])}
        assert {"fclk", "OSR", "Order"} <= names, (
            f"{fn} missing converter timing constants; have {names}")
        ok, msg = G._check_l_doc(8, doc, ic_class="data_converter")
        assert ok is True, f"{fn}: {msg}"


def test_facet_d_l7_l10_verification_intent_harvested(tmp_path):
    """L7 / L10 — the 4 Verification-intent bullets populate
    verification_strategy (L7) and test_cases (L10)."""
    proj = _build_converter_project(tmp_path / "d", _L5_RICH)
    l7 = _load(proj, "L7_TEST_DEBUG.json")
    vstrat = l7.get("verification_strategy") or []
    assert len(vstrat) >= 3, f"L7 verification_strategy={len(vstrat)} (<3)"
    assert any(v.get("extraction_strategy") ==
               "verification_intent_bullet_v634" for v in vstrat)
    ok, msg = G._check_l_doc(7, l7, ic_class="data_converter")
    assert ok is True, msg

    l10 = _load(proj, "L10_TEST_CASES.json")
    cases = l10.get("test_cases") or []
    assert any(c.get("kind") == "verification_intent" for c in cases)
    ok, msg = G._check_l_doc(10, l10, ic_class="data_converter")
    assert ok is True, msg


def test_facet_e_l12_no_calibration_auto_set(tmp_path):
    """L12 — no calibration source in the input → no_calibration auto-set
    True (absence-based, mirroring L5.no_analog)."""
    proj = _build_converter_project(tmp_path / "e", _L5_RICH)
    l12 = _load(proj, "L12_BEHAVIORAL_SEQUENCES.json")
    assert l12.get("no_calibration") is True
    ok, msg = G._check_l_doc(12, l12, ic_class="data_converter")
    assert ok is True, msg


# ── (C) NEGATIVE no-leak — the load-bearing half ─────────────────────────────

def test_empty_converter_doc_still_fails_NOLEAK(tmp_path):
    """An EMPTY converter doc (no spec table, no Verification-intent section,
    no cal source) must still FAIL — the harvesters fabricate nothing."""
    proj = _build_converter_project(tmp_path / "empty", _L5_EMPTY)
    # The generation side produced NO content for the relaxed-floor docs.
    l7 = _load(proj, "L7_TEST_DEBUG.json")
    assert (l7.get("verification_strategy") or []) == []
    l8t = _load(proj, "L8_TIMING_WAVEFORM.json")
    assert (l8t.get("timing_constants") or []) == []
    l10 = _load(proj, "L10_TEST_CASES.json")
    assert (l10.get("test_cases") or []) == []
    # … and each relaxed-floor doc still FAILs the gate.
    for layer, doc in ((7, l7), (10, l10), (8, l8t)):
        ok, _ = G._check_l_doc(layer, doc, ic_class="data_converter")
        assert ok is False, f"L{layer} leaked a pass on an empty converter doc"


def test_calibration_source_keeps_no_calibration_false_NOLEAK(tmp_path):
    """A doc that DOES document a calibration source must keep
    no_calibration False — the honest-N/A is never handed to a part that
    genuinely carries calibration content."""
    proj = tmp_path / "cal"
    extracted = {"L5.md": (
        "# Analog spec\nThe device requires a one-time trim code written to "
        "the OTP calibration register at wafer test.\n")}
    R.gen_l12_behavioral(proj, extracted, {"opcodes": []})
    l12 = _load(proj, "L12_BEHAVIORAL_SEQUENCES.json")
    assert l12.get("no_calibration") is False


def test_explicit_no_calibration_still_true_REGRESSION(tmp_path):
    """The pre-existing v0.1.82 explicit-no-cal path is preserved."""
    proj = tmp_path / "nocal"
    extracted = {"L5.md": (
        "# Analog spec\nNo calibration / trimming required; pure datapath "
        "converter.\n")}
    R.gen_l12_behavioral(proj, extracted, {"opcodes": []})
    l12 = _load(proj, "L12_BEHAVIORAL_SEQUENCES.json")
    assert l12.get("no_calibration") is True


# ── (D) harvester-unit no-leak granularity ───────────────────────────────────

def test_converter_timing_harvester_granularity():
    """fclk / OSR / Order harvested; generic digital scalars + a unit-less
    port table ignored."""
    rich = R._v634_harvest_converter_timing({"x": _L5_RICH})
    names = {d["name"] for d in rich}
    assert {"fclk", "OSR", "Order"} <= names
    # generic digital prose scalars are NOT converter timing.
    assert R._v634_harvest_converter_timing(
        {"x": "width = 32\nbits = 8\ndepth = 1024\nlatency = 3\n"}) == []
    # a unit-less port table yields nothing (no recognised unit cell).
    assert R._v634_harvest_converter_timing(
        {"x": "| Signal | Width | Dir |\n|---|---|---|\n| data | 8 | in |\n"}
    ) == []
    # empty input → empty.
    assert R._v634_harvest_converter_timing({"x": ""}) == []


def test_verification_intent_harvester_granularity():
    """The `## Verification intent` section's bullets are harvested, bounded
    to the section; a generic `## Test plan` heading harvests nothing."""
    out = R._v634_harvest_verification_intent({"x": _L5_RICH})
    assert len(out) == 4
    # the harvest stops at the next heading — no foreign bullet leaks in.
    bounded = R._v634_harvest_verification_intent(
        {"x": "## Verification intent\n- check A op point\n\n"
              "## Other section\n- this must not be harvested\n"})
    assert len(bounded) == 1
    # a generic heading is NOT a verification-intent section.
    assert R._v634_harvest_verification_intent(
        {"x": "## Test plan\n- run sims\n- check coverage\n"}) == []
    assert R._v634_harvest_verification_intent({"x": ""}) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
