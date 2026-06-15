#!/usr/bin/env python3
"""Regression for ORGANIC #708 (MED) — monotonicity-violating deferral in
flow_compliance_check.py.

Bug: reaching 100% doc completeness REVOKES the only deferral (the
``--allow-thin-input`` thin-input demotion, predicate ``_is_thin_input_eligible``,
keyed on doc-completeness BELOW 100%) for the NON-WAIVABLE L6 ≥2-fsm_states
floor of ``l_doc_structured_field_count_check``. Perverse: more-complete docs →
worse verdict. The trapped class is REUSED-IP whose control FSM is genuinely
RTL-only (states exist only in vendor RTL, not in any input doc): it cannot
claim the #462 ``no_fsm`` N/A escape (no_fsm_in_input=false is CORRECT), cannot
reach the floor (anti-fabrication forbids inventing a doc-traceable 2nd state),
cannot lift via the #706 ai_deep_review sidecar (no qualifying patch exists),
and now cannot defer (thin-input revoked at 100% completeness).

Fix: an ORTHOGONAL, fail-closed deferral cap ``cap:reused_ip_rtl_only_fsm`` at
the structural demotion site. When the FAILing gate is
``l_doc_structured_field_count_check``, its output names the FSM-states floor,
and ALL FOUR keys of ``_reused_ip_rtl_only_fsm_cap_eligible`` hold, the FAIL is
demoted to a WAIVED-DEFERRED entry (review_required, distinct ticket). The cap
is entirely separate from ``_is_thin_input_eligible`` and fires at 100%
completeness, the regime thin-input does NOT cover.

§4.05 NEGATIVE-NO-LEAK (LOAD-BEARING — the cap RELAXES a non-waivable floor):
  - all 4 keys → demoted to WAIVED-DEFERRED (review_required, ticket).
  - DOC-ENUMERATED-BUT-MISSED 2nd state (a 2nd state literal present in an
    input doc's FSM context but NOT extracted) → key (c) False → still FAIL.
    (the load-bearing leak test — surfaces a real walker bug rather than
    masking it.)
  - NOT reused-IP (from-scratch class OR no vendor RTL) → key (a) False → FAIL.
  - completeness < 100% → key (b) False → cap does NOT fire (the existing
    thin-input path owns it; no double-demote).
  - L6 no_fsm_in_input == true (honest no-FSM #462 N/A) → key (c) False → not
    this cap.
  - sidecar HAS a qualifying FSM patch → key (d) False → not deferred (must
    lift via #706).

chip-AGNOSTIC: synthetic generic fixtures only; keyed on
class(rtl_gen=null)+vendor-RTL+completeness+doc-scan+sidecar — never a
chip / vendor / SKU literal.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as F  # noqa: E402


# ── fixture builder ──────────────────────────────────────────────────────────
def _make_reused_ip_project(root: Path,
                            *,
                            ic_class: str = "processor_cpu",
                            no_fsm_in_input=False,
                            completeness_pct: float = 1.0,
                            total_raw_each: int = 400,
                            vendor_rtl: bool = True,
                            source_manifest_reused: bool = False,
                            doc_fsm_text: str | None = None,
                            sidecar_fsm_patch: bool = False) -> Path:
    """Build a reused-IP fixture: L6 with 1 typed FSM state (IDLE), a persisted
    ic_class, a 100% completeness report, vendor RTL, input docs whose FSM
    context names ONLY IDLE, and minimal digital RTL so the P0 umbrella runs."""
    (root / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "phase1").mkdir(parents=True, exist_ok=True)
    (root / "input" / "docs").mkdir(parents=True, exist_ok=True)
    (root / "phase2" / "stage1" / "rtl").mkdir(parents=True, exist_ok=True)

    # L6: ONE typed FSM state (IDLE) → fails the ≥2 floor; honest FSM presence.
    l6 = {
        "fsm_states": [
            {"name": "IDLE", "transitions": ["start"], "actions": ["hold"]},
        ],
        "description": ("The control unit idles waiting for a fetch; the "
                        "remaining sequencing lives in the vendor RTL core."),
        "module_name": "core_controller",
        "clock": "clk_i",
        "reset": "rst_ni",
    }
    if no_fsm_in_input is not None:
        l6["no_fsm_in_input"] = no_fsm_in_input
    (root / "phase1" / "generated_docs" / "L6_CONTROL_LOGIC.json").write_text(
        json.dumps(l6))

    # Persisted IC class (detect_ic_class returns the persisted result).
    (root / "reports" / "ic_class.json").write_text(
        json.dumps({"ic_class": ic_class}))

    # Completeness report: per-doc capture, plus a sub-100% REFERENCE doc that
    # must be ignored by key (b).
    per_doc = [
        {"doc": "datasheet.md", "raw_total": total_raw_each,
         "captured_pct": completeness_pct, "reference_doc": False,
         "verdict": "PASS"},
        {"doc": "isa.md", "raw_total": total_raw_each,
         "captured_pct": 1.0, "reference_doc": False, "verdict": "PASS"},
        {"doc": "ref_pinout.md", "raw_total": 50, "captured_pct": 0.4,
         "reference_doc": True, "verdict": "SKIP_REFERENCE"},
    ]
    (root / "reports" / "phase1"
     / "phase1_input_vs_generated_completeness.json").write_text(
        json.dumps({"gate": "phase1_input_vs_generated_completeness_check",
                    "verdict": "PASS", "per_doc": per_doc}))

    # Vendor / reused RTL provenance.
    (root / "input" / "vendor_rtl").mkdir(parents=True, exist_ok=True)
    if vendor_rtl:
        (root / "input" / "vendor_rtl" / "core.v").write_text(
            "module core; endmodule\n")
    if source_manifest_reused:
        (root / "phase2" / "stage1" / "rtl"
         / "SOURCE_MANIFEST.json").write_text(json.dumps({"reused_ip": True}))

    # Input docs: FSM context names ONLY IDLE (already extracted) by default.
    if doc_fsm_text is None:
        doc_fsm_text = (
            "The controller has a small control FSM. It starts in the IDLE "
            "state and transitions on a request. Internal pipeline sequencing "
            "is delegated to the vendor RTL core and is not enumerated here.")
    (root / "input" / "docs" / "datasheet.md").write_text(doc_fsm_text)

    # Minimal synthesizable RTL so _run_structural_rtl_gates finds a dir.
    (root / "phase2" / "stage1" / "rtl" / "core_controller.v").write_text(
        "module core_controller(input clk_i, input rst_ni,\n"
        "  output reg done_o);\n"
        "  always @(posedge clk_i) done_o <= 1'b1;\n"
        "endmodule\n")

    # Optional #706 sidecar carrying a qualifying L6 FSM patch.
    if sidecar_fsm_patch:
        (root / "phase1").mkdir(parents=True, exist_ok=True)
        (root / "phase1" / "ai_deep_review_patches.json").write_text(
            json.dumps({"patches": {"L6": [
                {"name": "WAIT_RESP", "transitions": ["resp"],
                 "actions": ["latch"],
                 "extraction_strategy": "ai_deep_review_patch"}]}}))
    return root


def _field_count_in(reasons_or_waivers, *, is_waiver=False):
    gate = "l_doc_structured_field_count_check"
    if is_waiver:
        return [w for w in reasons_or_waivers if w.get("gate") == gate]
    return [x for x in reasons_or_waivers if gate in x]


# ── end-state via the REAL _run_structural_rtl_gates demotion path ───────────
def test_all_four_keys_demote_fsm_floor_to_waiver(tmp_path):
    """All 4 keys hold → the L6 fsm_states FAIL is DEMOTED to a WAIVED-DEFERRED
    waiver (review_required, distinct ticket) at the structural demotion site,
    WITHOUT --allow-thin-input (the cap is orthogonal)."""
    proj = _make_reused_ip_project(tmp_path / "p")
    passed, fails, skips, waivers = F._run_structural_rtl_gates(
        proj, allow_thin_input=False, skip_analog=True)
    assert not _field_count_in(fails), (
        "field-count FSM floor must NOT be in FAILS when the cap fires")
    fc = _field_count_in(waivers, is_waiver=True)
    assert len(fc) == 1
    w = fc[0]
    assert w["review_required"] is True
    assert w["ticket"] == F._REUSED_IP_RTL_ONLY_FSM_CAP_TICKET
    assert w["ticket"] != F._THIN_INPUT_WAIVER_TICKET   # DISTINCT ticket
    assert "fsm_states" in w["first_line"].lower()
    assert "rtl-only" in w["reason"].lower() or "rtl-only" in w["evidence"].lower()


def test_load_bearing_leak_doc_enumerated_missed_state_still_FAILs(tmp_path):
    """LOAD-BEARING: a 2nd state name (WAIT_RESP) present in an input doc's FSM
    context but NOT extracted → key (c) False → field-count STILL FAILs (never
    waived). Surfaces the real walker bug instead of masking it."""
    proj = _make_reused_ip_project(
        tmp_path / "p",
        doc_fsm_text=("The controller has a control FSM. It starts in the IDLE "
                      "state and transitions to the WAIT_RESP state when a "
                      "request is pending, then returns to IDLE."))
    passed, fails, skips, waivers = F._run_structural_rtl_gates(
        proj, allow_thin_input=False, skip_analog=True)
    assert _field_count_in(fails), (
        "doc-enumerated-but-missed 2nd state MUST keep FAILing (no leak)")
    assert not _field_count_in(waivers, is_waiver=True)


def test_not_reused_ip_no_vendor_rtl_still_FAILs(tmp_path):
    """key (a) False — vendor RTL absent and no reused SOURCE_MANIFEST → the
    field-count FSM floor FAIL propagates unchanged."""
    proj = _make_reused_ip_project(
        tmp_path / "p", vendor_rtl=False, source_manifest_reused=False)
    passed, fails, skips, waivers = F._run_structural_rtl_gates(
        proj, allow_thin_input=False, skip_analog=True)
    assert _field_count_in(fails)
    assert not _field_count_in(waivers, is_waiver=True)


def test_subprocess_endstate_pass_with_waivers(tmp_path):
    """Faithful end-state: run flow_compliance_check as a subprocess on a
    fixture whose ONLY structural FAIL is the field-count FSM floor, and assert
    the cap demotes it to a WAIVED-DEFERRED entry carrying the distinct ticket
    (the verdict line surfaces the deferral, not a bare FAIL on that gate)."""
    proj = _make_reused_ip_project(tmp_path / "p")
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "flow_compliance_check.py"), ".",
         "--strict", "--phase", "2", "--strict-structural",
         "--skip-analog", "--skip-hardware"],
        cwd=proj, capture_output=True, text=True, timeout=300)
    out = r.stdout + r.stderr
    # The cap waiver line must appear with the distinct ticket, and the
    # field-count gate must NOT be listed as a hard structural FAIL.
    assert F._REUSED_IP_RTL_ONLY_FSM_CAP_TICKET in out, out[-2000:]
    assert "WAIVED-DEFERRED: l_doc_structured_field_count_check" in out, out[-2000:]
    # The fsm_states floor must not appear as a "FAILed" structural gate line.
    fail_section = out.split("structural gates FAILed", 1)
    if len(fail_section) > 1:
        assert "l_doc_structured_field_count_check" not in fail_section[1], (
            "field-count must be demoted, not in the FAILed structural list")


# ── unit tests of _reused_ip_rtl_only_fsm_cap_eligible: each key flips it ─────
def test_key_a_class_rtl_gen_null_plus_vendor_rtl(tmp_path):
    """key (a): rtl_gen=null class + vendor RTL → True; deterministic-rtl_gen
    class (aid_class_half_duplex_single_wire) → False even with vendor RTL."""
    proj = _make_reused_ip_project(tmp_path / "p")
    assert F._detected_class_rtl_gen_null_and_vendor_rtl(proj) is True
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is True

    # Deterministic-rtl_gen class → from-spec RTL, docs MUST specify the FSM.
    proj2 = _make_reused_ip_project(
        tmp_path / "p2", ic_class="aid_class_half_duplex_single_wire")
    assert F._detected_class_rtl_gen_null_and_vendor_rtl(proj2) is False
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj2) is False


def test_key_a_source_manifest_reused_ip_path(tmp_path):
    """key (a): NO vendor_rtl/ dir but a SOURCE_MANIFEST.json with
    reused_ip=true → still reused-IP."""
    proj = _make_reused_ip_project(
        tmp_path / "p", vendor_rtl=False, source_manifest_reused=True)
    assert F._detected_class_rtl_gen_null_and_vendor_rtl(proj) is True
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is True


def test_key_b_completeness_below_100_does_not_fire_cap(tmp_path):
    """key (b): completeness < 100% → cap does NOT fire (the EXISTING
    thin-input path owns that regime — no double-demote)."""
    proj = _make_reused_ip_project(tmp_path / "p", completeness_pct=0.95)
    assert F._completeness_is_full_and_not_tiny(proj) is False
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False
    # And the existing thin-input predicate DOES own the <100% regime.
    assert F._is_thin_input_eligible(proj) is True


def test_key_b_tiny_input_does_not_fire_cap(tmp_path):
    """key (b): even at 100% capture, a tiny input (sum raw_total <= threshold)
    is owned by the existing tiny-input thin path, not this cap."""
    proj = _make_reused_ip_project(tmp_path / "p", total_raw_each=10)
    assert F._completeness_is_full_and_not_tiny(proj) is False
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False


def test_key_b_missing_report_fails_closed(tmp_path):
    """key (b): a missing/malformed completeness report → False (fail-closed)."""
    proj = _make_reused_ip_project(tmp_path / "p")
    (proj / "reports" / "phase1"
     / "phase1_input_vs_generated_completeness.json").unlink()
    assert F._completeness_is_full_and_not_tiny(proj) is False
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False


def test_key_c_honest_no_fsm_true_is_462_escape_not_cap(tmp_path):
    """key (c): L6 no_fsm_in_input == true (honest no-FSM #462 N/A) → cap
    requires no_fsm_in_input==false, so it does NOT fire."""
    proj = _make_reused_ip_project(tmp_path / "p", no_fsm_in_input=True)
    ok, _l6 = F._l6_doc_records_fsm_present(proj)
    assert ok is False
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False


def test_key_c_doc_enumerated_missed_state_flips_predicate(tmp_path):
    """key (c) CRUX: a doc-enumerated 2nd state literal beyond the extracted
    set → predicate False (the leak guard at the predicate level)."""
    proj = _make_reused_ip_project(
        tmp_path / "p",
        doc_fsm_text=("Control FSM: starts IDLE, moves to WAIT_GNT on grant, "
                      "then DONE. Only IDLE is captured."))
    nff, l6 = F._l6_doc_records_fsm_present(proj)
    assert F._docs_name_no_further_fsm_states(proj, l6) is False
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False


def test_key_c_extracted_state_in_docs_is_allowed(tmp_path):
    """key (c): the EXTRACTED state name (IDLE) appearing in the docs does NOT
    flip the predicate — only literals BEYOND the extracted set do."""
    proj = _make_reused_ip_project(tmp_path / "p")
    nff, l6 = F._l6_doc_records_fsm_present(proj)
    assert F._docs_name_no_further_fsm_states(proj, l6) is True


def test_key_c_unreadable_docs_fail_closed(tmp_path):
    """key (c): if NO input docs can be read at all → False (fail-closed: a
    missing doc must never let the cap leak)."""
    proj = _make_reused_ip_project(tmp_path / "p")
    # Remove the L6 doc AND all input docs so nothing is readable.
    for p in (proj / "input" / "docs").glob("*"):
        p.unlink()
    (proj / "phase1" / "generated_docs" / "L6_CONTROL_LOGIC.json").unlink()
    nff, l6 = F._l6_doc_records_fsm_present(proj)
    assert F._docs_name_no_further_fsm_states(proj, {}) is False


def test_key_d_sidecar_fsm_patch_blocks_cap(tmp_path):
    """key (d): a qualifying #706 ai_deep_review FSM patch present → the cap
    does NOT fire (the recovered state must lift the count via #706 instead)."""
    proj = _make_reused_ip_project(tmp_path / "p", sidecar_fsm_patch=True)
    assert F._sidecar_has_qualifying_fsm_patch(proj) is True
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False


def test_key_d_no_sidecar_is_zero_patches(tmp_path):
    """key (d): no sidecar file → zero qualifying patches → cap may fire."""
    proj = _make_reused_ip_project(tmp_path / "p")
    assert F._sidecar_has_qualifying_fsm_patch(proj) is False


def test_cap_only_targets_fsm_states_floor_token(tmp_path):
    """The demotion branch is gated on the FSM-states floor token; a non-FSM
    field-count FAIL (e.g. a different layer's floor) is NOT demoted by this
    cap. Verified structurally: the gate constant + token list are specific."""
    assert F._REUSED_IP_RTL_ONLY_FSM_CAP_GATE == "l_doc_structured_field_count_check"
    assert any("fsm" in t for t in F._FSM_STATES_FLOOR_TOKENS)


# ════════════════════════════════════════════════════════════════════════════
# ORGANIC #708 ROUND-2 — adversarial-review leak fixtures (3 reproduced defects)
# Each below RELAXES a non-waivable floor, so a missed case is a real-defect-
# ships-as-PASS leak. All assert the cap predicate returns False (→ still FAIL).
# ════════════════════════════════════════════════════════════════════════════

# ── (1) HIGH — key-(c) FSM-state-literal detector must catch EVERY form ──────
# Each doc ENUMERATES a doc-traceable 2nd state (beyond the extracted IDLE) the
# original ALL-CAPS-only ±1-line scanner missed → cap MUST be False, and the
# field-count FSM floor MUST stay in `fails` (not `waivers`).
_LEAK_DOC_FORMS = {
    "lowercase_idle_active":
        "The FSM has two states: idle and active.",
    "mixedCase_WaitResp":
        "States are IDLE and WaitResp.",
    "capitalized_busy":
        "It transitions from IDLE to Busy.",
    "prose_no_marker_on_line_DONE":
        "The control unit has a small FSM.\n"
        "Once running, the machine advances to DONE.",
    "bullet_far_below_marker":
        "State table:\n"
        "  - the first row is idle\n"
        "  - the second entry is active\n"
        "  - the third is FLUSH",
    "table_row_block":
        "| State | Action |\n"
        "| idle  | wait   |\n"
        "| compute | run  |",
    "transition_arrow":
        "FSM diagram: IDLE -> RUN -> IDLE.",
    "states_are_enumeration":
        "The control logic states are fetch, decode and execute.",
    "the_X_state_adjective":
        "The control FSM. The busy state holds the bus until grant.",
    # additional adversarial forms found in the round-2 self-review: a
    # transition described WITHOUT the literal word "state"/"fsm" on the line.
    "enters_direct_object":
        "On grant the machine enters BUSY.",
    "goes_to_preposition":
        "After IDLE it goes to RUNNING.",
    "switches_to":
        "The control logic switches to STALL when full.",
    "reaches_direct_object":
        "The FSM reaches DONE after the burst.",
    "states_named":
        "There are two control states named idle and done.",
    "numbered_list":
        "States:\n  1. idle\n  2. compute\n  3. writeback",
    "S_short_form":
        "The FSM uses states S0, S1 and S2.",
    "pending_state_adjective":
        "The controller may sit in the PENDING state.",
    "moves_into":
        "The controller moves into the active state on request.",
}


@pytest.mark.parametrize("form", sorted(_LEAK_DOC_FORMS))
def test_key_c_leak_form_predicate_is_False(tmp_path, form):
    """LOAD-BEARING leak (1): a doc-enumerated 2nd state in this surface form
    → key (c) False → cap predicate False (the cap must NOT fire)."""
    proj = _make_reused_ip_project(
        tmp_path / "p", doc_fsm_text=_LEAK_DOC_FORMS[form])
    nff, l6 = F._l6_doc_records_fsm_present(proj)
    assert F._docs_name_no_further_fsm_states(proj, l6) is False, (
        f"form {form!r}: key (c) leaked (detector missed the 2nd state)")
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False


@pytest.mark.parametrize("form", sorted(_LEAK_DOC_FORMS))
def test_key_c_leak_form_field_count_stays_FAILed(tmp_path, form):
    """LOAD-BEARING leak (1) end-state: the field-count FSM floor FAIL stays in
    `fails` (never demoted to `waivers`) for every leak form."""
    proj = _make_reused_ip_project(
        tmp_path / "p", doc_fsm_text=_LEAK_DOC_FORMS[form])
    passed, fails, skips, waivers = F._run_structural_rtl_gates(
        proj, allow_thin_input=False, skip_analog=True)
    assert _field_count_in(fails), (
        f"form {form!r}: field-count must STILL FAIL (no leak)")
    assert not _field_count_in(waivers, is_waiver=True)


def test_key_c_motivating_case_still_fires(tmp_path):
    """Counterpart to the leak forms: the motivating reused-IP doc ("see RTL
    for FSM details", only IDLE, NO 2nd-state enumeration) must STILL yield
    key (c) True so the cap can legitimately fire."""
    proj = _make_reused_ip_project(
        tmp_path / "p",
        doc_fsm_text=("The control unit has a control FSM. It starts in the "
                      "IDLE state and transitions on a request; the remaining "
                      "states are implemented in the vendor RTL core and are "
                      "not enumerated here. See the vendor RTL for FSM "
                      "details."))
    nff, l6 = F._l6_doc_records_fsm_present(proj)
    assert F._docs_name_no_further_fsm_states(proj, l6) is True
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is True


def test_key_c_extracted_state_internals_not_false_positive(tmp_path):
    """Regression: the extracted IDLE state's own transition/action labels
    (e.g. `start`/`hold`) inside the L6 JSON must NOT be mistaken for further
    doc-enumerated states (they are extraction internals). Default fixture
    carries fsm_states:[{IDLE, transitions:[start], actions:[hold]}]."""
    proj = _make_reused_ip_project(tmp_path / "p")
    nff, l6 = F._l6_doc_records_fsm_present(proj)
    internals = F._extracted_state_internals(l6)
    assert "START" in internals and "HOLD" in internals
    assert F._docs_name_no_further_fsm_states(proj, l6) is True


# ── (2) MED-HIGH — demotion-site must not MASK a co-occurring non-FSM floor ──
def test_co_occurring_L9_floor_not_masked(tmp_path):
    """leak (2): when the field-count gate FAILs on BOTH the L6 FSM floor AND
    the L9 ≥3-typed-structural-fields floor, the cap must NOT demote the whole
    gate — the L9 failure must survive in `fails` (not be masked)."""
    proj = _make_reused_ip_project(tmp_path / "p")
    # L9 with only 2 typed structural fields → fails the ≥3 floor too.
    (proj / "phase1" / "generated_docs" / "L9_INTEGRATION.json").write_text(
        json.dumps({"top_module": "core",
                    "ports": [{"name": "clk", "dir": "in"},
                              {"name": "rst", "dir": "in"}]}))
    passed, fails, skips, waivers = F._run_structural_rtl_gates(
        proj, allow_thin_input=False, skip_analog=True)
    assert _field_count_in(fails), (
        "co-occurring L9 floor must keep the gate FAILed (not masked by cap)")
    assert not _field_count_in(waivers, is_waiver=True)


def test_solely_fsm_floor_helper():
    """Unit: _field_count_fail_is_solely_fsm_floor demotes only when EVERY
    detail line is the L6 FSM floor; the L9 line (which also contains the
    substring `fsm_states[]`) must NOT count as the FSM floor."""
    fsm_only = (
        "FAIL — Wave 31/32: 1 L doc(s):\n"
        "  - L6_CONTROL_LOGIC.json: L6 control_logic must carry >=2 typed FSM "
        "states in `fsm_states` (each with name/transitions/actions); have 1.")
    both = (
        "FAIL — Wave 31/32: 2 L doc(s):\n"
        "  - L6_CONTROL_LOGIC.json: L6 control_logic must carry >=2 typed FSM "
        "states in `fsm_states`; have 1.\n"
        "  - L9_INTEGRATION.json: L9 integration_spec must carry >=3 typed "
        "structural fields among (top_module string, fsm_states[], port list, "
        "submodules[]); have 2.")
    l9_only = (
        "FAIL — Wave 31/32: 1 L doc(s):\n"
        "  - L9_INTEGRATION.json: L9 integration_spec must carry >=3 typed "
        "structural fields among (top_module string, fsm_states[], port "
        "list); have 2.")
    assert F._field_count_fail_is_solely_fsm_floor(fsm_only) is True
    assert F._field_count_fail_is_solely_fsm_floor(both) is False
    assert F._field_count_fail_is_solely_fsm_floor(l9_only) is False
    assert F._field_count_fail_is_solely_fsm_floor("") is False


# ── (3) MED — key-(a) must fail-closed on unknown / unresolvable class ────────
def test_key_a_unknown_class_fails_closed(tmp_path):
    """leak (3): an `unknown` / unresolvable ic_class (which resolves via the
    registry synonym `unknown` → unknown_protocol_class, rtl_gen=null) plus a
    stray vendor .v must NOT make key (a) True — an unclassified design gets
    NO floor relaxation."""
    proj = _make_reused_ip_project(tmp_path / "p", ic_class="unknown")
    assert F._detected_class_rtl_gen_null_and_vendor_rtl(proj) is False
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False
    passed, fails, skips, waivers = F._run_structural_rtl_gates(
        proj, allow_thin_input=False, skip_analog=True)
    assert _field_count_in(fails)
    assert not _field_count_in(waivers, is_waiver=True)


def test_key_a_unknown_protocol_class_literal_fails_closed(tmp_path):
    """leak (3) variant: an explicit `unknown_protocol_class` ic_class literal
    is likewise fail-closed (never the cap's eligibility target)."""
    proj = _make_reused_ip_project(
        tmp_path / "p", ic_class="unknown_protocol_class")
    assert F._detected_class_rtl_gen_null_and_vendor_rtl(proj) is False
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False


def test_key_a_resolvable_rtl_gen_null_class_still_fires(tmp_path):
    """Counterpart: a RESOLVABLE rtl_gen=null class (crypto_accelerator) +
    vendor RTL keeps key (a) True (the unknown-class guard must not over-block
    legitimate reused-IP classes)."""
    proj = _make_reused_ip_project(tmp_path / "p", ic_class="crypto_accelerator")
    assert F._detected_class_rtl_gen_null_and_vendor_rtl(proj) is True
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is True


# ── chip-agnostic source guard (cap must name no chip/vendor/SKU literal) ─────
def test_chip_agnostic_guard():
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "source_chip_agnostic_check.py"), "."],
        cwd=_PROGRAMS, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
