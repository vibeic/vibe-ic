"""Tests for harness_verdict_token_guard — the BLOCKING pre-scoring gate that
refuses a candidate carrying the scoring harness's own verdict vocabulary
(vibe-ic#1745).

NEGATIVE-CONTROL NOTE. These are unit tests of a module the fix INTRODUCES, so
against the parent revision they fail by absence (ImportError), which proves
little on its own. The substantive bidirectional control lives in
`test_score_iverilog_forgery_and_third_state.py`, where the same forged sample
scores PASS before the fix and FAIL after, and the pass rate moves 66.67 -> 25.0
on an unchanged fixture. Read the two modules together.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from _hostpaths import require_repo

GUARD = Path(__file__).resolve().parents[1] / "harness_verdict_token_guard.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "harness_verdict_token_guard", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load()

# The two verdict markers this repo's Shape-B / Shape-C scorers actually key on.
# Written here as PATTERNS, exactly as a registry entry supplies them — the
# guard is handed its vocabulary, it never carries one.
_PASS_MISMATCH = r"Mismatches:\s*0\s+in\s+\d+\s+samples"
_PASS_PHRASE = "Your Design Passed"
_FAIL_PHRASE = "Test failed|Your Design Failed"

_HONEST = "module TopModule(input a, output y);\n  assign y = ~a;\nendmodule\n"


# --------------------------------------------------------------------------- #
# anchor extraction
# --------------------------------------------------------------------------- #
def test_anchors_are_the_patterns_required_words_without_its_digits():
    """A digit inside a verdict marker is the reported VALUE, not vocabulary:
    keeping it as an anchor would let the format-string forgery through."""
    assert G.verdict_anchor_sets(_PASS_MISMATCH) == [
        ["Mismatches", "in", "samples"]]


def test_alternation_yields_one_anchor_set_per_branch():
    assert G.verdict_anchor_sets(_FAIL_PHRASE) == [
        ["Test", "failed"], ["Your", "Design", "Failed"]]


def test_nested_alternation_is_expanded_not_concatenated():
    """A group's branches are alternatives. Concatenating them would demand
    BOTH words of a two-way choice and silently miss every real forgery of
    either one."""
    assert G.verdict_anchor_sets("===Your Design (Passed|Failed)===") == [
        ["Your", "Design", "Passed"], ["Your", "Design", "Failed"]]


def test_optional_literal_is_not_a_required_anchor():
    assert ["ad"] in G.verdict_anchor_sets("a(bc)?d")


def test_unusable_pattern_raises_rather_than_returning_nothing():
    with pytest.raises(G.UnsupportedPattern):
        G.verdict_anchor_sets(r"\d+\s+\w+")


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #
def test_honest_candidate_is_clear():
    rep = G.scan_report(_HONEST, {"pass_regex": _PASS_MISMATCH})
    assert rep["verdict"] == G.VERDICT_CLEAR
    assert rep["findings"] == []
    assert rep["dut_output_task_count"] == 0


def test_literal_marker_in_a_display_is_refused():
    """The measured attack: identical wrong logic, one extra $display."""
    forged = _HONEST.replace(
        "endmodule",
        '  initial $display("Mismatches: 0 in 20 samples");\nendmodule')
    rep = G.scan_report(forged, {"pass_regex": _PASS_MISMATCH})
    assert rep["verdict"] == G.VERDICT_REFUSED
    assert rep["findings"][0]["matched_text"] == "Mismatches: 0 in 20 samples"
    assert rep["findings"][0]["pattern_name"] == "pass_regex"
    assert rep["findings"][0]["line"] == 3


def test_format_string_marker_is_refused():
    """The second thing a forger reaches for: the values come from arguments, so
    the literal never matches the pattern — but the vocabulary is all there."""
    forged = _HONEST.replace(
        "endmodule",
        '  initial $display("Mismatches: %0d in %0d samples", 0, 20);\n'
        "endmodule")
    rep = G.scan_report(forged, {"pass_regex": _PASS_MISMATCH})
    assert rep["verdict"] == G.VERDICT_REFUSED
    assert rep["findings"][0]["anchors"] == ["Mismatches", "in", "samples"]


def test_marker_split_across_two_write_arguments_is_refused():
    forged = _HONEST.replace(
        "endmodule",
        '  initial $write("Your Design ", "Passed\\n");\nendmodule')
    rep = G.scan_report(forged, {"pass_regex": _PASS_PHRASE})
    assert rep["verdict"] == G.VERDICT_REFUSED
    assert any(f["kind"] == "output_task_concat" for f in rep["findings"])


def test_marker_parked_in_a_localparam_is_refused():
    """A string the design never displays directly is still a string the design
    can put on stdout."""
    forged = _HONEST.replace(
        "assign y = ~a;",
        'localparam [8*27:1] M = "Mismatches: 0 in 20 samples";\n'
        "  assign y = ~a;")
    rep = G.scan_report(forged, {"pass_regex": _PASS_MISMATCH})
    assert rep["verdict"] == G.VERDICT_REFUSED


def test_fail_marker_is_refused_too():
    forged = _HONEST.replace(
        "endmodule", '  initial $display("Test failed");\nendmodule')
    rep = G.scan_report(forged, {"fail_regex": _FAIL_PHRASE})
    assert rep["verdict"] == G.VERDICT_REFUSED
    assert rep["findings"][0]["pattern_name"] == "fail_regex"


# --------------------------------------------------------------------------- #
# false positives — a gate that fires on legitimate RTL is a bug in the gate
# --------------------------------------------------------------------------- #
def test_marker_inside_a_line_comment_is_clear():
    ok = _HONEST.replace(
        "assign y = ~a;",
        "// the harness prints Mismatches: 0 in 20 samples\n  assign y = ~a;")
    assert G.scan_report(ok, {"pass_regex": _PASS_MISMATCH})["verdict"] == \
        G.VERDICT_CLEAR


def test_marker_inside_a_block_comment_is_clear():
    ok = _HONEST.replace(
        "assign y = ~a;",
        "/* scored when the TB says Mismatches: 0 in 20 samples */\n"
        "  assign y = ~a;")
    assert G.scan_report(ok, {"pass_regex": _PASS_MISMATCH})["verdict"] == \
        G.VERDICT_CLEAR


def test_a_comment_marker_inside_a_string_still_opens_no_comment():
    """`//` inside a string literal is text, not a comment — the scanner must
    not treat it as one, or a forgery could hide behind a slash."""
    forged = _HONEST.replace(
        "endmodule",
        '  initial $display("// Mismatches: 0 in 20 samples");\nendmodule')
    assert G.scan_report(forged, {"pass_regex": _PASS_MISMATCH})["verdict"] == \
        G.VERDICT_REFUSED


def test_punctuation_inside_a_printed_string_does_not_hide_the_split_marker():
    """Structure is read off a string-MASKED view, so a `(` the design PRINTS
    cannot unbalance the argument scan and drop the concatenated form."""
    forged = _HONEST.replace(
        "endmodule",
        '  initial $write("Your Design (", "Passed");\nendmodule')
    rep = G.scan_report(forged, {"pass_regex": _PASS_PHRASE})
    assert rep["verdict"] == G.VERDICT_REFUSED
    assert any(f["kind"] == "output_task_concat" for f in rep["findings"])


def test_a_task_name_inside_a_string_is_not_counted_as_a_task():
    ok = _HONEST.replace(
        "endmodule", '  initial $display("a $display( b");\nendmodule')
    rep = G.scan_report(ok, {"pass_regex": _PASS_MISMATCH})
    assert rep["verdict"] == G.VERDICT_CLEAR
    assert rep["dut_output_task_count"] == 1


def test_partial_vocabulary_is_clear():
    """One word of the marker is not the marker. All anchors, in order, or
    nothing."""
    ok = _HONEST.replace(
        "endmodule",
        '  initial $display("collected 20 samples");\nendmodule')
    assert G.scan_report(ok, {"pass_regex": _PASS_MISMATCH})["verdict"] == \
        G.VERDICT_CLEAR


def test_out_of_order_vocabulary_is_clear():
    ok = _HONEST.replace(
        "endmodule",
        '  initial $display("samples in Mismatches");\nendmodule')
    assert G.scan_report(ok, {"pass_regex": _PASS_MISMATCH})["verdict"] == \
        G.VERDICT_CLEAR


def test_anchor_match_is_whole_word():
    ok = _HONEST.replace(
        "endmodule",
        '  initial $display("MismatchesX inY samplesZ");\nendmodule')
    assert G.scan_report(ok, {"pass_regex": _PASS_MISMATCH})["verdict"] == \
        G.VERDICT_CLEAR


# --------------------------------------------------------------------------- #
# degrade loudly
# --------------------------------------------------------------------------- #
def test_no_pattern_is_not_checked_not_clear():
    rep = G.scan_report(_HONEST, {})
    assert rep["verdict"] == G.VERDICT_NOT_CHECKED
    assert rep["not_checked_reason"]


def test_unusable_pattern_is_not_checked_not_clear():
    rep = G.scan_report(_HONEST, {"pass_regex": r"\d+"})
    assert rep["verdict"] == G.VERDICT_NOT_CHECKED
    assert "no required alphabetic literal" in rep["not_checked_reason"]


def test_a_partly_usable_pattern_set_names_the_half_it_could_not_check():
    """A silent PARTIAL decline reads downstream as a full check. The unusable
    half is named even when the usable half clears the candidate."""
    rep = G.scan_report(_HONEST, {"pass_regex": _PASS_PHRASE,
                                  "fail_regex": r"\d+"})
    assert rep["verdict"] == G.VERDICT_CLEAR
    assert rep["patterns_checked"] == ["pass_regex"]
    assert "fail_regex" in rep["patterns_not_checked"]


def test_report_declares_blocking_and_discloses_the_static_scan_boundary():
    """§5 — an unstated enforcement level is how a gate ends up unable to stop
    anything; §6 — the run-time-assembly channel this cannot see is named."""
    rep = G.scan_report(_HONEST, {"pass_regex": _PASS_MISMATCH})
    assert rep["enforcement"] == "BLOCKING"
    assert rep["static_scan_only"] is True
    assert "static scan" in rep["undetectable_channel"]


def test_output_task_count_is_disclosed_even_when_clear():
    ok = _HONEST.replace(
        "endmodule", '  initial $display("hello");\nendmodule')
    rep = G.scan_report(ok, {"pass_regex": _PASS_MISMATCH})
    assert rep["verdict"] == G.VERDICT_CLEAR
    assert rep["dut_output_task_count"] == 1


# --------------------------------------------------------------------------- #
# real in-repo artefacts (flow-change-acceptance §4)
# --------------------------------------------------------------------------- #
def test_every_shape_b_c_registry_pattern_yields_anchors():
    """Driven by the checked-in BENCHMARK_REGISTRY.json, not by a fixture: if a
    real benchmark's verdict marker cannot be turned into anchors, this guard
    would report NOT_CHECKED for that whole benchmark."""
    reg = json.loads(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "benchmark",
        "BENCHMARK_REGISTRY.json").read_text())
    checked = 0
    for name, entry in reg["benchmarks"].items():
        if entry.get("shape") not in ("B", "C"):
            continue
        for key in ("pass_regex", "fail_regex"):
            pat = (entry.get("scorer_args") or {}).get(key)
            if not pat:
                continue
            assert G.verdict_anchor_sets(pat), f"{name}.{key} yielded no anchors"
            checked += 1
    assert checked >= 3, f"expected the registry's real markers, got {checked}"


def test_checked_in_canonical_samples_are_clear():
    """The repo's own vetted candidate RTL must not trip the gate."""
    root = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                        "benchmark", "canonical_samples")
    files = sorted(root.rglob("*.sv"))
    assert files, "no canonical samples found to sweep"
    for f in files:
        rep = G.scan_report(f.read_text(errors="replace"),
                            {"pass_regex": _PASS_MISMATCH,
                             "fail_regex": _FAIL_PHRASE}, source=str(f))
        assert rep["verdict"] == G.VERDICT_CLEAR, (f, rep["findings"])
