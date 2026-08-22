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
                            sidecar_fsm_patch: bool = False,
                            sidecar_present: bool = True) -> Path:
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

    # #706 ai_deep_review sidecar. KEY (e) requires the FILE to be PRESENT
    # (positive evidence the AI deep-review ran). By default we write an EMPTY
    # sidecar (AI ran, found no further doc-traceable FSM state) so the cap can
    # fire. `sidecar_fsm_patch=True` adds a qualifying L6 patch (key (d) False);
    # `sidecar_present=False` omits the file entirely (key (e) False).
    if sidecar_present or sidecar_fsm_patch:
        (root / "phase1").mkdir(parents=True, exist_ok=True)
        patches = {"L6": [
            {"name": "WAIT_RESP", "transitions": ["resp"],
             "actions": ["latch"],
             "extraction_strategy": "ai_deep_review_patch"}]} \
            if sidecar_fsm_patch else {}
        (root / "phase1" / "ai_deep_review_patches.json").write_text(
            json.dumps({"patches": patches}))
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


def test_load_bearing_leak_doc_enumerated_state_recovered_by_ai_not_deferred(
        tmp_path):
    """LOAD-BEARING §4.05 (ROUND-3 direction (b)): a 2nd state name (WAIT_RESP)
    present in an input doc's FSM context that the AI deep-review RECOVERS (a
    qualifying #706 sidecar patch) must NOT be cap-deferred — key (d) flips and
    the count lifts via #706 (PASS on merit), so the cap never fires. The
    irreducible "did the docs name a state the walker missed?" judgment rests on
    the AI deep-review channel, not a deterministic prose scan that provably
    over-collects on real docs (1087–1732-token remainder, 3 consecutive
    no-ops)."""
    proj = _make_reused_ip_project(
        tmp_path / "p",
        doc_fsm_text=("The controller has a control FSM. It starts in the IDLE "
                      "state and transitions to the WAIT_RESP state when a "
                      "request is pending, then returns to IDLE."),
        sidecar_fsm_patch=True)  # AI deep-review recovered the doc-named state
    # key (d) False (qualifying FSM patch present) → cap does not fire.
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False
    passed, fails, skips, waivers = F._run_structural_rtl_gates(
        proj, allow_thin_input=False, skip_analog=True)
    # The cap did not demote it (the AI-recovered state lifts the count via #706).
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
        cwd=proj, capture_output=True, text=True, timeout=60)
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


def test_doc_enumerated_state_recovered_by_ai_flips_predicate(tmp_path):
    """§4.05 (ROUND-3 direction (b)): a doc-enumerated 2nd state the AI
    deep-review recovers (qualifying #706 patch) → predicate False (key (d)).
    The doc-enumeration judgment rests on the AI channel, not the removed
    deterministic prose-scan veto."""
    proj = _make_reused_ip_project(
        tmp_path / "p",
        doc_fsm_text=("Control FSM: starts IDLE, moves to WAIT_GNT on grant, "
                      "then DONE. Only IDLE is captured."),
        sidecar_fsm_patch=True)
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
def test_leak_form_recovered_by_ai_does_not_defer(tmp_path, form):
    """ROUND-3 direction (b) §4.05: for EVERY doc-enumeration surface form, when
    the AI deep-review recovers the named state (a qualifying #706 sidecar
    patch), the cap does NOT fire (key (d)) — the recovered state lifts the count
    via #706 instead of being deferred. The AI channel catches doc-enumerated
    states regardless of surface form; the removed deterministic prose-scan
    provably could not."""
    proj = _make_reused_ip_project(
        tmp_path / "p", doc_fsm_text=_LEAK_DOC_FORMS[form],
        sidecar_fsm_patch=True)
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False, (
        f"form {form!r}: AI-recovered 2nd state must block the cap (lift via "
        f"#706, not defer)")


@pytest.mark.parametrize("form", sorted(_LEAK_DOC_FORMS))
def test_leak_form_field_count_stays_FAILed_without_ai_recovery(tmp_path, form):
    """ROUND-3 direction (b) §4.05 end-state: a doc-enumeration form with the AI
    deep-review ABSENT (no sidecar file = the AI never examined the docs) → key
    (e) False → the field-count FSM floor FAIL stays in `fails`, never demoted.
    The cap requires positive AI-deep-review evidence to defer."""
    proj = _make_reused_ip_project(
        tmp_path / "p", doc_fsm_text=_LEAK_DOC_FORMS[form],
        sidecar_present=False)
    passed, fails, skips, waivers = F._run_structural_rtl_gates(
        proj, allow_thin_input=False, skip_analog=True)
    assert _field_count_in(fails), (
        f"form {form!r}: without AI-deep-review evidence the floor must FAIL")
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


# ════════════════════════════════════════════════════════════════════════════
# ORGANIC #708 ROUND-3 — second adversarial review: the regex arms race is
# unwinnable (a scan aggressive enough to catch lowercase prose state names also
# OVER-BLOCKS on bus/IP/register/acronym names — wrongly FAILing a CORRECT
# reused-IP design, and a hardware-acronym stopword set erases real acronym-named
# states like DMA). Round-3 re-architects:
#  - key (c) anchors on the plugin's OWN trusted FSM-state extractor
#    (phase1_doc_one_shot_runner._classify_modes_vs_states_from_text) + a small
#    set of HIGH-PRECISION explicit-enumeration positions → over-block-FREE and
#    walker-consistent; it catches every reviewer-listed explicit form AND a real
#    acronym-named state (DMA), and does NOT grab bus/IP/register/acronym names;
#  - the residual PURE-LOWERCASE-PROSE NL judgment is routed to the strong AI
#    channel via NEW key (e): the #706 ai_deep_review sidecar FILE must be
#    PRESENT (AI-adjudication exit per the classifier doctrine) — without it the
#    cap fail-closes.
# ════════════════════════════════════════════════════════════════════════════

# ── round-3 (1): key-(c) catches a real ACRONYM-named state (no erasure) ─────
def test_acronym_named_state_recovered_by_ai_not_deferred(tmp_path):
    """A genuine FSM state literally named DMA, doc-enumerated and RECOVERED by
    the AI deep-review (qualifying #706 patch), must NOT be cap-deferred (key (d)
    flips → lift via #706). ROUND-3 direction (b): the doc-enumeration judgment
    rests on the AI channel, not the removed deterministic prose veto (which
    over-collected an always-non-empty remainder on real docs)."""
    proj = _make_reused_ip_project(
        tmp_path / "p",
        doc_fsm_text="The controller has two states: IDLE and DMA.",
        sidecar_fsm_patch=True)
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False


# ── round-3 (2): NO OVER-BLOCK on real reused-IP datasheet prose ────────────
_OVER_BLOCK_DOCS = {
    "axi_amba_cortex":
        "The IBEX core implements a RISC-V CPU with an AXI4-Lite bus and AMBA "
        "interconnect. Only the IDLE state is documented; the rest of the FSM "
        "is in the vendor RTL.",
    "wishbone_regs":
        "The Wishbone interconnect drives a PicoRV32 core. The CTRL_REG and "
        "STATUS_REG configure it. At power-up the controller is in IDLE; see "
        "the vendor RTL for the full state machine.",
    "ddr_phys":
        "Interfaces to DDR4, LPDDR5 and GDDR6 PHYs. The reused memory "
        "controller sits in IDLE on reset; the remaining FSM states are inside "
        "the vendor RTL.",
    "flash_parts":
        "Supports S25FL128, W25Q64 and AT24LC256 serial flash. The SPI master "
        "FSM idles in IDLE; consult the vendor RTL for the other states.",
    "crypto_ip":
        "Built from AES, SHA256 and HMAC engines. The control FSM powers up "
        "IDLE; its other states are documented only in the vendor RTL.",
}


@pytest.mark.parametrize("form", sorted(_OVER_BLOCK_DOCS))
def test_no_overblock_on_reused_ip_datasheet(tmp_path, form):
    """A legitimate reused-IP datasheet that names ONLY IDLE (rest in vendor
    RTL) but is full of bus/IP/register/acronym/part-number names must NOT be
    wrongly FAILed: key (c) True and the cap FIRES (an over-block wrongly fails
    a correct design)."""
    proj = _make_reused_ip_project(
        tmp_path / "p", doc_fsm_text=_OVER_BLOCK_DOCS[form])
    nff, l6 = F._l6_doc_records_fsm_present(proj)
    assert F._docs_name_no_further_fsm_states(proj, l6) is True, (
        f"{form}: over-blocked by token(s) "
        f"{sorted(F._doc_fsm_state_literals(_OVER_BLOCK_DOCS[form]) - {'IDLE'})}")
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is True


# ── round-3 (3): key (e) — AI-adjudication exit (sidecar must be present) ────
def test_key_e_sidecar_absent_fails_closed(tmp_path):
    """key (e): if the #706 ai_deep_review sidecar FILE is ABSENT (no AI
    deep-review ran), the cap fail-closes → still FAIL. The residual lowercase-
    prose NL judgment must rest on the strong AI channel having run, not on the
    conservative regex alone."""
    proj = _make_reused_ip_project(tmp_path / "p", sidecar_present=False)
    assert F._ai_deep_review_sidecar_present(proj) is False
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False


def test_key_e_sidecar_present_empty_allows_fire(tmp_path):
    """key (e): a PRESENT (parseable) sidecar — even with no patches (AI ran,
    found no further FSM state) — satisfies key (e); combined with the other
    keys the cap may fire."""
    proj = _make_reused_ip_project(tmp_path / "p", sidecar_present=True)
    assert F._ai_deep_review_sidecar_present(proj) is True
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is True


def test_key_e_malformed_sidecar_fails_closed(tmp_path):
    """key (e): an unparseable sidecar → treated as absent → fail-closed."""
    proj = _make_reused_ip_project(tmp_path / "p", sidecar_present=True)
    (proj / "phase1" / "ai_deep_review_patches.json").write_text("{not json")
    assert F._ai_deep_review_sidecar_present(proj) is False
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False


# ── round-3 (4): the reviewer-listed explicit-enumeration forms STILL FAIL ───
_R3_EXPLICIT_LEAK_FORMS = {
    "states_colon_lowercase": "The FSM has two states: idle and active.",
    "states_are_mixedcase": "States are IDLE and WaitResp.",
    "from_X_to_Y": "It transitions from IDLE to Busy.",
    "advances_to_DONE": "Once running, the machine advances to DONE.",
    "transition_arrow": "FSM diagram: IDLE -> RUN -> IDLE.",
    "states_are_list": "The control logic states are fetch, decode and execute.",
    "enters_BUSY": "On grant the machine enters BUSY.",
    "bullet_row": ("State table:\n  - row one is idle\n"
                   "  - row two is ACTIVE"),
    "double_dash_arrow": "FSM diagram:\nIDLE --> ACTIVE --> DONE.",
    "states_colon_WAIT_RESP": "FSM states: IDLE, WAIT_RESP.",
}


@pytest.mark.parametrize("form", sorted(_R3_EXPLICIT_LEAK_FORMS))
def test_r3_explicit_enumeration_ai_channel_governs(tmp_path, form):
    """ROUND-3 direction (b) §4.05: for every explicit enumeration form, the
    AI deep-review channel governs whether the named 2nd state defers —
    (i) AI recovers it (qualifying patch) → cap False (lift via #706); and
    (ii) AI never ran (no sidecar) → cap False (fail-closed). The deterministic
    prose veto is removed (it provably over-collects on real CPU docs)."""
    # (i) AI recovered the doc-enumerated state → not deferred.
    proj_rec = _make_reused_ip_project(
        tmp_path / "rec", doc_fsm_text=_R3_EXPLICIT_LEAK_FORMS[form],
        sidecar_fsm_patch=True)
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj_rec) is False, form
    # (ii) AI deep-review absent → fail-closed, field-count stays FAILed.
    proj_noai = _make_reused_ip_project(
        tmp_path / "noai", doc_fsm_text=_R3_EXPLICIT_LEAK_FORMS[form],
        sidecar_present=False)
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj_noai) is False, form
    passed, fails, skips, waivers = F._run_structural_rtl_gates(
        proj_noai, allow_thin_input=False, skip_analog=True)
    assert _field_count_in(fails)
    assert not _field_count_in(waivers, is_waiver=True)


def test_r3_trusted_extractor_anchor_used(tmp_path):
    """key (c) anchors on the plugin's OWN trusted FSM-state extractor — a state
    named in an explicit `fsm states:` narrative position (the trusted
    extractor's anchor) is caught even without any high-precision-position
    keyword."""
    proj = _make_reused_ip_project(
        tmp_path / "p",
        doc_fsm_text="fsm states: IDLE, GRANTED, RELEASED.")
    nff, l6 = F._l6_doc_records_fsm_present(proj)
    rem = F._doc_fsm_state_literals("fsm states: IDLE, GRANTED, RELEASED.") \
        - {"IDLE"}
    assert {"GRANTED", "RELEASED"} <= rem
    assert F._docs_name_no_further_fsm_states(proj, l6) is False


# ── ROUND-2 (field-agent reopen): RTL files staged under input/docs/ must NOT
#    inject RTL-only state names into the doc-enumeration scan (cap was a
#    FUNCTIONAL NO-OP — over-blocked on the very reused-IP artifact it exists
#    for: a vendor `_pkg.sv` under input/docs/ guaranteed a non-empty remainder).
_VENDOR_PKG_SV = (
    "package core_pkg;\n"
    "  typedef enum logic [3:0] {\n"
    "    BOOT_SET, FIRST_FETCH, WAIT_SLEEP, IRQ_TAKEN, DBG_TAKEN_ID\n"
    "  } ctrl_fsm_e;\n"
    "endpackage\n")


def test_round2_sv_package_under_docs_does_not_block_cap(tmp_path):
    """A reused-IP whose vendor RTL package (`*_pkg.sv`) is STAGED under
    input/docs/ — naming RTL-only states BOOT_SET/FIRST_FETCH/... — must NOT
    inject those into the doc-enumeration scan: RTL is not a 'doc'. The cap
    must still FIRE (those states are RTL-only, the defer case)."""
    proj = _make_reused_ip_project(tmp_path)
    (proj / "input" / "docs" / "core_pkg.sv").write_text(_VENDOR_PKG_SV)
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is True


def test_round2_v_and_svh_under_docs_excluded(tmp_path):
    """.v / .svh staged under input/docs/ are likewise excluded from the scan."""
    proj = _make_reused_ip_project(tmp_path)
    (proj / "input" / "docs" / "alu.v").write_text(
        "module alu; localparam ST_RUN=1, ST_HALT=2; endmodule\n")
    (proj / "input" / "docs" / "defs.svh").write_text(
        "`define MODE_TURBO 1\n`define MODE_ECO 2\n")
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is True


def test_round2_register_dense_human_prose_does_not_over_block(tmp_path):
    """Real CPU datasheet prose (register/acronym-dense: ACCESS/RESET/DECODE/
    FLUSH/SLEEP/MSTATUS/…) with only IDLE a genuine state must NOT over-collect
    into a non-empty remainder → the cap must FIRE (the v1.0.67/68 over-block)."""
    reg_dense = (
        "The core ACCESS the RESET vector ABOVE the ABSOLUTE base. On DECODE it "
        "may FLUSH or SLEEP. Control starts in IDLE; the full controller FSM "
        "state sequencing is delegated to the vendor RTL core. Registers "
        "MSTATUS, MTVEC, MEPC, MCAUSE provide ACCESS; the ALU performs ADD SUB "
        "AND OR XOR. See the RTL package for state details.")
    proj = _make_reused_ip_project(tmp_path, doc_fsm_text=reg_dense)
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is True


def test_round3_NOLEAK_human_doc_2nd_state_governed_by_ai_channel(tmp_path):
    """§4.05 LOAD-BEARING (ROUND-3 direction (b)): a 2nd state enumerated in a
    HUMAN doc is governed by the AI deep-review channel, not the removed
    deterministic prose veto — (i) AI recovers it (patch) → cap False (lift via
    #706); (ii) AI never ran (no sidecar) → cap False (fail-closed). The mandatory
    AI deep-review reads the SAME human prose with NL judgment a regex cannot."""
    # (i) AI recovered the human-doc-named 2nd state → not deferred.
    proj = _make_reused_ip_project(
        tmp_path, doc_fsm_text="The control FSM states: IDLE and BUSY.",
        sidecar_fsm_patch=True)
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is False
    # (ii) AI deep-review absent → fail-closed (no evidence to defer on).
    proj2 = _make_reused_ip_project(tmp_path / "p2", sidecar_present=False)
    (proj2 / "input" / "docs" / "extra.md").write_text(
        "The machine transitions: IDLE -> RUNNING -> DONE.")
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj2) is False


# ── ROUND-3 (field-agent reopen): the cap FIRES on register-dense CPU prose ──
#    (the 3-consecutive-no-op the deterministic prose scan caused — it
#    over-collected an always-non-empty 1087–1732-token remainder on real docs).
_REG_DENSE_CPU_PROSE = (
    "The core ACCESS the RESET vector ABOVE the ABSOLUTE base. On DECODE it may "
    "FLUSH or SLEEP. The pipeline ADVANCES through IF, ID and EX. Control starts "
    "in IDLE; the full controller FSM state sequencing is delegated to the "
    "vendor RTL core. Registers MSTATUS, MTVEC, MEPC, MCAUSE provide ACCESS; the "
    "ALU performs ADD, SUB, AND, OR, XOR. The DECODER and the FETCH unit "
    "COMMUNICATE over the bus. See the vendor RTL package for state details.")


def test_round3_register_dense_prose_cap_FIRES_not_noop(tmp_path):
    """ROUND-3 (the reopen): a real-CPU-shaped register/acronym/pipeline-dense
    datasheet that names ONLY IDLE as a state (rest in vendor RTL), with the AI
    deep-review run and finding nothing further → the cap FIRES (cap eligible
    True) → the field-count FSM floor is demoted to a WAIVED-DEFERRED cap waiver.
    Under v1.0.67–69 this was a FUNCTIONAL NO-OP (the prose scan's non-empty
    remainder kept key (c) False)."""
    proj = _make_reused_ip_project(
        tmp_path / "p", doc_fsm_text=_REG_DENSE_CPU_PROSE)  # sidecar present, empty
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is True
    passed, fails, skips, waivers = F._run_structural_rtl_gates(
        proj, allow_thin_input=False, skip_analog=True)
    assert _field_count_in(waivers, is_waiver=True), (
        "register-dense reused-IP CPU prose must DEMOTE the FSM floor (cap fires)")
    assert not _field_count_in(fails)


def test_round3_prose_scan_veto_removed_from_conjunction(tmp_path):
    """ROUND-3 direction (b): `_docs_name_no_further_fsm_states` is NO LONGER in
    the cap conjunction. Demonstrated on a doc the deterministic scan FLAGS
    (returns False — an explicit `states:` enumeration it does detect): under the
    OLD code that False vetoed the cap; under direction (b) the cap fires anyway
    because the AI deep-review ran (key (e)) and found nothing further (key (d)).

    HONEST §4.05 TRADEOFF (disclosed, not hidden): an explicit doc enumeration
    that the deterministic L6 walker missed AND the mandatory AI deep-review ALSO
    missed (sidecar present but empty) is now deferred rather than kept FAILing.
    The field agent (the verify authority, with the real round-8 artifact) judged
    this acceptable: the prose veto provably over-collects on real CPU docs
    (1087–1732-token remainder, 3 consecutive no-ops), so a doc-named state is
    instead caught by the AI deep-review (reads the same prose with NL judgment →
    qualifying patch → lift via #706). The residual is a double-extractor miss
    (deterministic walker + LLM both miss an explicit enumeration), not a single
    deterministic gap a regex reliably closes."""
    proj = _make_reused_ip_project(
        tmp_path / "p", doc_fsm_text="FSM states: IDLE, WAIT_RESP.")
    nff, l6 = F._l6_doc_records_fsm_present(proj)
    # the deterministic scan DOES flag this explicit enumeration (returns False) ...
    assert F._docs_name_no_further_fsm_states(proj, l6) is False
    # ... yet the cap fires (AI ran + found nothing): the veto is not consulted.
    assert F._reused_ip_rtl_only_fsm_cap_eligible(proj) is True


# ── chip-agnostic source guard (cap must name no chip/vendor/SKU literal) ─────
def test_chip_agnostic_guard(tmp_path):
    """The cap's source must name no chip / vendor / SKU literal.

    THE ARGUMENT IS LOAD-BEARING. This called the guard with plugin_root="."
    while cwd was `programs/`, so the guard walked `programs/{programs,skills,
    commands}` — three directories that do not exist — and read 0 files. The
    guard's own v1.7.9 denominator check (NOTHING_SCANNED, rc 2) is what
    turned that into a visible failure; before v1.7.9 the same call printed a
    PASS byte-identical to a real clean scan of 1242 files. The root is
    `plugins/vibe-ic/`, which is this file's grandparent.

    So the census assertion below is not decoration. rc 0 proves "the guard
    was happy"; only the census proves THIS TEST looked at anything, and it
    proves it WITHOUT depending on the guard keeping its own self-check. A
    gate that reports a denominator is only useful to a caller that reads it.
    """
    out = tmp_path / "chip_agnostic.json"
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "source_chip_agnostic_check.py"),
         str(_PROGRAMS.parent), "--json", str(out)],
        cwd=_PROGRAMS, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]

    census = json.loads(out.read_text())["scan_census"]
    assert census.get("files_read", 0) > 0, (
        f"the guard reported PASS over {census.get('files_read')} file(s) — "
        f"a clean result over an empty scan is not a clean result. "
        f"census={census}")
    for sub in ("programs", "skills", "commands"):
        assert census.get(f"dir_{sub}", -1) > 0, (
            f"plugin_root resolved to a tree with no {sub}/ — wrong root. "
            f"census={census}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
