"""LVS verdict wording-gate — the false-clean guard.

THE DEFECT (measured on the pre-fix module): `lvs_verdict_tokens.classify()`
decided MATCH / MISMATCH purely by regexing netgen's English. A mismatch
worded outside the enumerated phrase list, sitting next to any `match
uniquely` line (per-subcell lines print by the hundreds), returned **MATCH**:

    Circuits match uniquely.
    Result: Netlists are NOT equivalent.
    Final result: Netlist comparison FAILED (2 discrepancies).
        -> pre-fix classify() == "MATCH"      <-- A FALSE LVS CLEAN

An LVS false-clean ships a broken chip as verified. It is the defect class
that reaches silicon, so the NEGATIVE assertions below are load-bearing: this
file is a guard, and a guard that only proves the happy path proves nothing.

THE FIX: the E1 structured netgen report (`{"verdict": ...}`, derived from
netgen's OWN numeric verify() result) is AUTHORITATIVE when present; the text
path is a fail-safe FALLBACK in which MATCH requires POSITIVE evidence and
ambiguity resolves to INCOMPLETE/MISMATCH, never to MATCH.

chip-AGNOSTIC: synthetic generic-device transcripts only; no PDK content.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
T = importlib.import_module("lvs_verdict_tokens")


# ── fixtures — all synthetic, generic-device ───────────────────────────────
def e1(verdict, **summary_over):
    """A minimal well-formed E1 structured report (netgen fork `-json`)."""
    summary = {
        "devices": {"ckt1": 4, "ckt2": 4},
        "nets": {"ckt1": 3, "ckt2": 3},
        "unmatched_nets": {"ckt1": 0, "ckt2": 0},
        "unmatched_devices": {"ckt1": 0, "ckt2": 0},
        "property_error_count": 0,
        "property_error_cells": [],
        "failed_subcells": [],
    }
    summary.update(summary_over)
    return {"verdict": verdict, "verdict_reason": "synthetic",
            "summary": summary, "cells": []}


# The exact transcript that produced the false MATCH before the fix.
REWORDED_MISMATCH = (
    "Circuits match uniquely.\n"
    "Result: Netlists are NOT equivalent.\n"
    "Netlist mismatch detected at top level cell.\n"
    "Final result: Netlist comparison FAILED (2 discrepancies).\n"
)
GARBAGE = ("qqq unparseable nonsense; Circuits match uniquely maybe? "
           "Final result: ???\n")
CLEAN = "Netlists match uniquely.\nFinal result: Circuits match uniquely.\n"
POWER_ONLY = (
    "Final result: Top level cell failed pin matching.\n"
    "VGND                          |(no matching pin)\n"
    "VPWR                          |(no matching pin)\n"
)
SIGNAL_NET = (
    "Final result: Top level cell failed pin matching.\n"
    "VGND                          |(no matching pin)\n"
    "(no pin, node is o_data[7])   |o_wdata[7]\n"
)


# ── POSITIVE: a genuinely matching design still classifies MATCH ───────────
def test_positive_json_match_is_match():
    assert T.classify(CLEAN, json_report=e1("match")) == "MATCH"


def test_positive_text_only_clean_report_is_match():
    """No JSON (older netgen) — the fail-safe fallback must NOT false-alarm."""
    assert T.classify(CLEAN) == "MATCH"


def test_positive_embedded_json_is_found_and_used():
    blob = CLEAN + "\n" + json.dumps(e1("match"))
    assert T.classify(blob) == "MATCH"


def test_positive_clean_match_has_no_mismatch_subclass():
    assert T.mismatch_class(CLEAN) == "NONE"


def test_positive_benign_power_artifact_still_waiver_candidate():
    """The known power-unaware-netlist artifact must stay disclosable."""
    assert T.mismatch_class(POWER_ONLY) == "POWER_PIN_ONLY"


# ── PROVEN-NEGATIVE (a): the reworded mismatch is no longer a MATCH ────────
def test_negative_a_reworded_mismatch_is_never_match():
    verdict = T.classify(REWORDED_MISMATCH)
    assert verdict != "MATCH", (
        f"FALSE LVS CLEAN: a transcript reading 'Netlists are NOT equivalent' "
        f"/ 'comparison FAILED' classified {verdict!r}")
    assert verdict == "MISMATCH"


# ── PROVEN-NEGATIVE (b): garbage is never a MATCH ─────────────────────────
def test_negative_b_garbage_transcript_is_never_match():
    assert T.classify(GARBAGE) != "MATCH"
    assert T.classify(GARBAGE) == "INCOMPLETE"


@pytest.mark.parametrize("blob", [
    "", "   \n\n  ",
    "Final result:",                       # terminal marker, no verdict text
    "Circuits match uniquely.",            # match line, compare never finished
    "Final result: something we have never seen before",
])
def test_negative_b_unrecognised_shapes_are_never_match(blob):
    """MATCH requires POSITIVE evidence — absence of a known failure phrase is
    NOT evidence of a pass."""
    assert T.classify(blob) != "MATCH"


def test_negative_b_match_phrase_before_final_result_does_not_carry_verdict():
    """A `match uniquely` printed BEFORE the colon must not be read as the
    top-level verdict (this regressed an earlier draft of the fix)."""
    assert T.classify(
        "Circuits match uniquely on subcell. Final result: ???") != "MATCH"


# ── PROVEN-NEGATIVE (c): a real net mismatch is never demoted to benign ────
def test_negative_c_signal_net_mismatch_not_demoted_to_power_pin_only():
    assert T.mismatch_class(SIGNAL_NET) == "SIGNAL_NET_MISMATCH"


def test_negative_c_reworded_failure_with_power_rows_stays_real():
    """The benign bucket must be EARNED, not reached by elimination: a failure
    we cannot positively recognise as the pin-correspondence artifact stays
    real even when power rows are present."""
    blob = ("Final result: Netlists are NOT equivalent.\n"
            "VGND                          |(no matching pin)\n")
    assert T.mismatch_class(blob) == "SIGNAL_NET_MISMATCH"


def test_negative_c_json_property_errors_override_power_looking_text():
    assert T.mismatch_class(
        POWER_ONLY,
        json_report=e1("mismatch", property_error_count=3),
    ) == "SIGNAL_NET_MISMATCH"


@pytest.mark.parametrize("over", [
    {"unmatched_nets": {"ckt1": 2, "ckt2": 0}},
    {"unmatched_devices": {"ckt1": 0, "ckt2": 1}},
])
def test_negative_c_json_unmatched_counts_keep_mismatch_real(over):
    assert T.mismatch_class(
        POWER_ONLY, json_report=e1("mismatch", **over)) == "SIGNAL_NET_MISMATCH"


def test_negative_c_corrupt_json_summary_is_never_benign():
    """An unreadable summary must not buy the benign class — we never infer
    'benign' from a field we failed to parse."""
    bad = {"verdict": "mismatch", "verdict_reason": "r",
           "summary": "CORRUPT", "cells": []}
    assert T.mismatch_class(POWER_ONLY, json_report=bad) == "SIGNAL_NET_MISMATCH"


# ── PROVEN-NEGATIVE (d): JSON wins over matchy-looking text ───────────────
def test_negative_d_json_mismatch_beats_matchy_text():
    assert T.classify(CLEAN, json_report=e1("mismatch")) == "MISMATCH"


def test_negative_d_embedded_json_mismatch_beats_matchy_text():
    assert T.classify(CLEAN + "\n" + json.dumps(e1("mismatch"))) == "MISMATCH"


def test_negative_d_json_match_may_never_upgrade_a_failing_text():
    """The ONE exception to JSON authority runs in the SAFE direction only."""
    assert T.classify("Final result: Netlists do not match.",
                      json_report=e1("match")) == "MISMATCH"


@pytest.mark.parametrize("verdict", ["unknown", "", "MATCHED", "pass", "42"])
def test_negative_d_unrecognised_json_verdict_is_never_match(verdict):
    """A verdict string a future fork adds must not read as a pass."""
    assert T.classify(CLEAN, json_report=e1(verdict)) != "MATCH"


# ── report resolution is fail-safe: unreadable == absent, never a pass ─────
def test_malformed_json_file_falls_back_to_text_never_raises(tmp_path):
    p = tmp_path / "lvs.json"
    p.write_text("{ this is not json")
    assert T.load_json_report(p) is None
    assert T.classify(REWORDED_MISMATCH, json_report=p) != "MATCH"


def test_non_e1_json_is_ignored_not_trusted(tmp_path):
    """A stray `verdict` key from some other tool is not the authority."""
    p = tmp_path / "other.json"
    p.write_text(json.dumps({"verdict": "match"}))
    assert T.load_json_report(p) is None
    assert T.classify(REWORDED_MISMATCH, json_report=p) == "MISMATCH"


def test_missing_json_path_falls_back_to_text(tmp_path):
    assert T.load_json_report(tmp_path / "nope.json") is None
    assert T.classify(CLEAN, json_report=tmp_path / "nope.json") == "MATCH"


def test_json_report_directory_is_searched(tmp_path):
    (tmp_path / "lvs.json").write_text(json.dumps(e1("mismatch")))
    assert T.classify(CLEAN, json_report=tmp_path) == "MISMATCH"


# ── DESIGN-CHOSEN DATA may not impersonate the verdict token ──────────────
# Slicing after the `Final result:` marker is not sufficient on its own: the
# sliced region still carries tool- and design-supplied DATA (paths, cell and
# net names), and a token inside that data can impersonate the structural token.
# Both of these returned a FALSE MATCH before the verdict phrase was anchored.
@pytest.mark.parametrize("blob", [
    # A SystemVerilog ESCAPED identifier legally contains spaces, so a
    # design-chosen name can spell the verdict phrase exactly.
    r"Final result: comparison ended for cell \circuits match uniquely ",
    # Same, via an environment-chosen path.
    "Final result: read from /work/circuits match uniquely/top.spice",
    # And in the pin table rather than the terminal line.
    "Final result: ???\n" + r"\circuits match uniquely  |(no matching pin)",
])
def test_design_chosen_names_cannot_spell_their_way_to_a_pass(blob):
    """The design names its own nets; it must never name its way to a pass."""
    assert T.classify(blob) != "MATCH"


@pytest.mark.parametrize("line", [
    "Final result: Circuits match uniquely.",
    "Final result: Netlists match uniquely.",
    "Final result:Circuits match uniquely.",
    "Final result:   Netlists match uniquely.",
])
def test_anchoring_preserves_genuine_netgen_terminal_wording(line):
    """Anchoring must not cost us real passes — netgen's own spacing variants."""
    assert T.classify(line) == "MATCH"


# ── terminal lines are judged by UNANIMITY, not first/last occurrence ──────
@pytest.mark.parametrize("blob", [
    "Final result: Circuits match uniquely.\nFinal result: ???",
    "Final result: ???\nFinal result: Circuits match uniquely.",
])
def test_every_terminal_line_must_read_clean_regardless_of_order(blob):
    """Tools re-enter passes and print terminal lines more than once, so any
    'take the first/last occurrence' rule is one re-entry away from reading the
    wrong verdict. Every terminal line must agree."""
    assert T.classify(blob) != "MATCH"


# ── embedded-report scanning is itself fail-safe ──────────────────────────
def test_worst_verdict_wins_when_several_reports_are_embedded():
    """A guard never averages: the most adverse embedded verdict decides."""
    blob = (CLEAN + json.dumps(e1("match")) + "\n" + json.dumps(e1("mismatch")))
    assert T.classify(blob) == "MISMATCH"


def test_non_e1_decoy_does_not_end_the_search():
    """Another tool's `verdict` key earlier in the log must not shadow the
    real E1 report further down."""
    blob = ('{"verdict": "match"}\n' + CLEAN + json.dumps(e1("mismatch")))
    assert T.classify(blob) == "MISMATCH"


# ── call-site guard: the generic analog parser yields to the classifier ────
def test_analog_a6_generic_parser_cannot_match_a_refused_netgen_report():
    a6 = importlib.import_module("analog_a6_block_pv_check")
    assert a6._parse_lvs_match(REWORDED_MISMATCH) is False
    assert a6._parse_lvs_match(GARBAGE) is None
    assert a6._parse_lvs_match(CLEAN) is True
