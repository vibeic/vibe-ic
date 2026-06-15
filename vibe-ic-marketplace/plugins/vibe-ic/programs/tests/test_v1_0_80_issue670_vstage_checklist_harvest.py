"""Regression for ORGANIC #670 round-12 REOPEN — the v1.0.44 DV-checklist
harvester (`_v1_0_44_harvest_dv_checklist_table`) walked ONLY the Design
Checklist stage tables (D1/D2/D2S/D3) and SKIPPED the Verification Checklist
stage tables (V1/V2/V2S/V3), so the V-stage milestone reference-link tokens
(FPV_MAIN_ASSERTIONS_PROVEN / SIM_NIGHTLY_REGRESSION_SETUP /
DV_DOC_TESTPLAN_REVIEWED / V2_CHECKLIST_SCOPED …) never reached an L-doc and
missed the 100% completeness gate.

現象 (round-12 binding repro): the canonical OpenTitan-style checklist doc
lists D-stage tables FIRST (D1+D2 alone exceed the harvester's internal 24-row
cap of `if len(out) >= 24: return out`), so the row-walk returned early in
D-stage and NEVER reached the Verification-stage tables below. End-state: a
checklist doc that should reach ~100% landed at 75% because the V-stage rows
were missing.

Fix (HARVEST-EXTEND, chip-AGNOSTIC, v1.0.80):
  - raise the premature 24-row cap so EVERY stage table is walked, and
  - add a reference-link LABEL-DEFINITION pass (`[TOKEN]: <anchor>`) gated on
    a `*checklist*` doc-family filename, so every milestone token defined in
    the doc lands regardless of stage section header / table position.

The binding acceptance is the round-12 repro: the V-stage token now lands.

chip-AGNOSTIC: pure markdown reference-link / pipe-table shape + `*checklist*`
doc-family filename; NO chip / vendor / SKU literal, NO specific checklist-item
literal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402


# ── round-12 binding fixture: D-stage tables FIRST (exceed the old 24-cap),
#    then a Verification V2 stage table with the FPV_MAIN_ASSERTIONS_PROVEN row.
#    Shaped VERBATIM like the OpenTitan checklist (NO chip literal). ───────────
DESIGN_THEN_VERIF_CHECKLIST = """## Design Checklist

### D1

Type          | Item                           | Resolution  | Note
--------------|--------------------------------|-------------|------
Documentation | [SPEC_COMPLETE][]              | Done        |
Documentation | [CSR_DEFINED][]                | Done        |
RTL           | [CLKRST_CONNECTED][]           | Done        |
RTL           | [IP_TOP][]                     | Done        |
RTL           | [IP_INSTANTIABLE][]            | Done        |
RTL           | [FUNC_IMPLEMENTED][]           | Done        |
RTL           | [ASSERT_KNOWN_ADDED][]         | Done        |
Code Quality  | [LINT_SETUP][]                 | Done        |

[SPEC_COMPLETE]:        ../README.md#spec_complete
[CSR_DEFINED]:          ../README.md#csr_defined
[CLKRST_CONNECTED]:     ../README.md#clkrst_connected
[IP_TOP]:               ../README.md#ip_top
[IP_INSTANTIABLE]:      ../README.md#ip_instantiable
[FUNC_IMPLEMENTED]:     ../README.md#func_implemented
[ASSERT_KNOWN_ADDED]:   ../README.md#assert_known_added
[LINT_SETUP]:           ../README.md#lint_setup

### D2

Type          | Item                      | Resolution  | Note
--------------|---------------------------|-------------|------
Documentation | [NEW_FEATURES][]          | Done        |
Documentation | [BLOCK_DIAGRAM][]         | Done        |
Documentation | [DOC_INTERFACE][]         | Done        |
Documentation | [MISSING_FUNC][]          | Done        |
Documentation | [FEATURE_FROZEN][]        | Done        |
RTL           | [FEATURE_COMPLETE][]      | Done        |
RTL           | [PORT_FROZEN][]           | Done        |
RTL           | [ARCHITECTURE_FROZEN][]   | Done        |
RTL           | [REVIEW_TODO][]           | Done        |
RTL           | [STYLE_X][]               | Done        |
RTL           | [CDC_SYNCMACRO][]         | Done        |
Code Quality  | [LINT_PASS][]             | Done        |
Code Quality  | [AREA_CHECK][]            | Done        |
Code Quality  | [TIMING_CHECK][]          | Done        |
Security      | [SEC_CM_DOCUMENTED][]     | Done        |

[NEW_FEATURES]:        ../README.md#new_features
[BLOCK_DIAGRAM]:       ../README.md#block_diagram
[DOC_INTERFACE]:       ../README.md#doc_interface
[MISSING_FUNC]:        ../README.md#missing_func
[FEATURE_FROZEN]:      ../README.md#feature_frozen
[FEATURE_COMPLETE]:    ../README.md#feature_complete
[PORT_FROZEN]:         ../README.md#port_frozen
[ARCHITECTURE_FROZEN]: ../README.md#architecture_frozen
[REVIEW_TODO]:         ../README.md#review_todo
[STYLE_X]:             ../README.md#style_x
[CDC_SYNCMACRO]:       ../README.md#cdc_syncmacro
[LINT_PASS]:           ../README.md#lint_pass
[AREA_CHECK]:          ../README.md#area_check
[TIMING_CHECK]:        ../README.md#timing_check
[SEC_CM_DOCUMENTED]:   ../README.md#sec_cm_documented

## Verification Checklist

### V1

 Type         | Item                                  | Resolution  | Note
--------------|---------------------------------------|-------------|------
Documentation | [DV_DOC_DRAFT_COMPLETED][]            | Done        |
Documentation | [TESTPLAN_COMPLETED][]                | Done        |
Tests         | [SIM_SMOKE_TEST_PASSING][]            | Done        |
Tests         | [FPV_MAIN_ASSERTIONS_PROVEN][]        | N/A         |
Regression    | [SIM_NIGHTLY_REGRESSION_SETUP][]      | Done        |
Coverage      | [SIM_COVERAGE_MODEL_ADDED][]          | Done        |
Review        | [V2_CHECKLIST_SCOPED][]               | Done        |

[DV_DOC_DRAFT_COMPLETED]:       ../README.md#dv_doc_draft_completed
[TESTPLAN_COMPLETED]:           ../README.md#testplan_completed
[SIM_SMOKE_TEST_PASSING]:       ../README.md#sim_smoke_test_passing
[FPV_MAIN_ASSERTIONS_PROVEN]:   ../README.md#fpv_main_assertions_proven
[SIM_NIGHTLY_REGRESSION_SETUP]: ../README.md#sim_nightly_regression_setup
[SIM_COVERAGE_MODEL_ADDED]:     ../README.md#sim_coverage_model_added
[V2_CHECKLIST_SCOPED]:          ../README.md#v2_checklist_scoped

### V2

 Type         | Item                          | Resolution  | Note
--------------|-------------------------------|-------------|------
Documentation | [DV_DOC_COMPLETED][]          | Done        |
Tests         | [SIM_ALL_TESTS_PASSING][]     | Done        |
Review        | [DV_DOC_TESTPLAN_REVIEWED][]  | Done        |

[DV_DOC_COMPLETED]:         ../README.md#dv_doc_completed
[SIM_ALL_TESTS_PASSING]:    ../README.md#sim_all_tests_passing
[DV_DOC_TESTPLAN_REVIEWED]: ../README.md#dv_doc_testplan_reviewed
"""


def _names(rows):
    return {r["name"] for r in rows}


# ── (1) BINDING REPRO: V-stage milestone tokens now land (were skipped) ──────

def test_v_stage_tokens_now_harvested():
    rows = R._v1_0_44_harvest_dv_checklist_table(
        {"aes_checklist.md": DESIGN_THEN_VERIF_CHECKLIST})
    names = _names(rows)
    # The four V-stage milestone tokens cited in the reopen MUST now be present.
    for tok in ("fpv_main_assertions_proven", "sim_nightly_regression_setup",
                "dv_doc_testplan_reviewed", "v2_checklist_scoped"):
        assert tok in names, f"V-stage token {tok} still skipped"


def test_d_stage_still_harvested_NOREGRESSION():
    """The D-stage tokens (round-1 behaviour) must STILL be harvested — the
    cap-raise + label pass must not drop the originally-working D-stage."""
    rows = R._v1_0_44_harvest_dv_checklist_table(
        {"aes_checklist.md": DESIGN_THEN_VERIF_CHECKLIST})
    names = _names(rows)
    for tok in ("spec_complete", "csr_defined", "lint_setup"):
        assert tok in names, f"D-stage token {tok} regressed"


def test_all_stages_present_no_premature_cap():
    """END-STATE: every token defined in the checklist doc is harvested (the
    old internal 24-row cap truncated at D-stage). Dedup invariant holds."""
    rows = R._v1_0_44_harvest_dv_checklist_table(
        {"aes_checklist.md": DESIGN_THEN_VERIF_CHECKLIST})
    names = _names(rows)
    assert len(names) == len(rows), "duplicate rows emitted"
    # 8 (D1) + 15 (D2) + 7 (V1) + 3 (V2) = 33 distinct tokens.
    assert len(rows) >= 33, (
        f"premature cap still truncates: only {len(rows)} rows "
        "(D1+D2 alone exceed the old 24-cap; V-stage was lost)")


# ── (2) the reference-link LABEL form lands even without a pipe table ─────────

def test_label_only_checklist_doc_harvested():
    """A `*checklist*` doc carrying ONLY reference-link label definitions (no
    pipe table) still harvests via the label-definition pass."""
    doc = {"my_checklist.md": (
        "[FPV_MAIN_ASSERTIONS_PROVEN]: ../README.md#fpv\n"
        "[SIM_NIGHTLY_REGRESSION_SETUP]: ../README.md#sim\n")}
    names = _names(R._v1_0_44_harvest_dv_checklist_table(doc))
    assert "fpv_main_assertions_proven" in names
    assert "sim_nightly_regression_setup" in names


# ── (3) NEGATIVE no-leak — the label pass is gated on `*checklist*` filename ──

def test_label_pass_gated_on_checklist_filename_NOLEAK():
    """A bare reference-link label in a NON-checklist doc must NOT be harvested
    (the label pass is filename-gated so a bibliography is never mis-read)."""
    biblio = {"references.md": (
        "[SOME_REF]: http://example.com\n"
        "[OTHER_REF]: http://example.org\n")}
    assert R._v1_0_44_harvest_dv_checklist_table(biblio) == []


def test_register_map_table_still_not_a_checklist_NOLEAK():
    """A register-map table (Field|Bits|Access) is not a DV checklist — even
    after the harvest-extend it must harvest ZERO entries."""
    regmap = {"regs.md": (
        "## Register Map\n\n| Field | Bits | Access |\n"
        "|-------|------|--------|\n| cfg | 7:0 | rw |\n| mode | 15:8 | rw |\n")}
    assert R._v1_0_44_harvest_dv_checklist_table(regmap) == []


def test_test_vector_table_still_not_a_checklist_NOLEAK():
    """A test-vector table (Test|Input|Expected) is handled by the test-vector
    harvester and must NOT be double-counted as a DV checklist."""
    tv = {"plan.md": (
        "## Test Plan\n\n| Test | Input | Expected |\n"
        "|------|-------|----------|\n| vec1 | 0x00 | 0xFF |\n")}
    assert R._v1_0_44_harvest_dv_checklist_table(tv) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
