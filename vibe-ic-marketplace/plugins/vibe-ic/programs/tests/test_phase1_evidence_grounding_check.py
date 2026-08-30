#!/usr/bin/env python3
"""vibe-ic — the Phase-1 ANTI-FABRICATION grounding gate, which had no test.

`gate_cli_mutation_probe` reported it SILENT with no test file at all. Its
subject is whether every evidence literal in the emitted L1-L24 JSON is
GROUNDED in the input documents — i.e. whether Phase 1 invented anything. A gate
about fabrication that nothing exercises is the sharpest form of the problem
this sweep is about.

The property under test is the exit code, because that is what the flow reads:

    rc 0   every literal grounded, OR the gate does not apply (SKIP)
    rc 1   an ungrounded literal — something was fabricated
    rc 2   the question could not be asked
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase1_evidence_grounding_check as G  # noqa: E402


def test_an_ungrounded_literal_exits_non_zero(tmp_path, monkeypatch):
    """The defect the gate exists for: a value in the output that is in no
    input document."""
    monkeypatch.setattr(G, "check", lambda project, strict=False: {
        "status": "FAIL", "checked_literals": 5,
        "ungrounded": [{"doc": "datasheet.md", "missing_identifiers": ["0xDEADBEEF"],
                        "literal": "0xDEADBEEF"}]})
    assert G.main([str(tmp_path)]) == 1


def test_all_grounded_exits_zero(tmp_path, monkeypatch):
    """The other direction, or the test above is met by a gate that always
    fails — which would block every Phase-1 run."""
    monkeypatch.setattr(G, "check", lambda project, strict=False: {
        "status": "PASS", "checked_literals": 5, "ungrounded": []})
    assert G.main([str(tmp_path)]) == 0


def test_an_inapplicable_project_is_a_skip_not_a_pass(tmp_path, monkeypatch,
                                                      capsys):
    """rc 0, and it must SAY it skipped. A zero with no reason is the shape
    this repo keeps retiring: nothing was checked, reported as clean."""
    monkeypatch.setattr(G, "check", lambda project, strict=False: {
        "status": "SKIP", "reason": "no input-doc text to ground against",
        "ungrounded": []})
    assert G.main([str(tmp_path)]) == 0
    out = capsys.readouterr()
    assert "SKIP" in (out.out + out.err)


def test_an_error_is_rc_2_not_a_verdict(tmp_path, monkeypatch):
    """"I could not look" must never share an exit code with "I looked and it
    was clean"."""
    def boom(project, strict=False):
        raise ValueError("unparsable layer JSON")
    monkeypatch.setattr(G, "check", boom)
    assert G.main([str(tmp_path)]) == 2


# ─────────────────────────────────────────────────────────────────────────────
# the input/derived partition has ONE definition
# ─────────────────────────────────────────────────────────────────────────────
#
# `stage_on_pass_review` carried a verbatim second copy of both regexes and of
# the one expression that combines them, under a comment saying it drew "the
# same partition `phase1_evidence_grounding_check` draws, for the same reason".
# Two copies of a premise are two premises. The reviewer that decides which
# evidence keys are input quotations must decide it the way the GATE decides
# it, or it is reviewing a run the gate never passed.
#
# `is_input_quotation` is not an HDL reader: `src` is a provenance KEY, never
# design source, so there is nothing in it to strip. That is stated here so a
# later reader does not "harden" it by stripping comments out of a filename.

import ast  # noqa: E402

_CONSUMERS = ("stage_on_pass_review.py",)


def test_the_partition_is_defined_once_in_the_tree():
    for name in _CONSUMERS:
        src = (PROGRAMS / name).read_text(encoding="utf-8")
        tree = ast.parse(src)
        assigned = {t.id for n in ast.walk(tree)
                    if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)}
        assert "_INPUT_SRC_RE" not in assigned, (
            f"{name} defines its own _INPUT_SRC_RE again -- the partition is "
            f"back in two places and free to drift")
        assert "_DERIVED_SRC_RE" not in assigned, (
            f"{name} defines its own _DERIVED_SRC_RE again")


def test_both_readers_answer_the_same_question():
    """The property the dedupe exists for, driven through both entry points."""
    import stage_on_pass_review as sopr

    quotes = ("input/docs/spec.md", "input_doc/datasheet.txt",
              "input\\docs\\spec.md", "notes.md", "table.csv")
    not_quotes = ("derived_from_L3", "cross_layer_rule_7", "L5",
                  "inferred_default", "derived_from_input/docs/spec.md")

    for key in quotes:
        assert G.is_input_quotation(key) is True, key
    for key in not_quotes:
        assert G.is_input_quotation(key) is False, key

    for key in quotes + not_quotes:
        doc = {"extraction_evidence": {key: ["a quoted literal"]}}
        seen = [r["source"] for r in sopr.cited_input_literals(doc)]
        assert bool(seen) is G.is_input_quotation(key), (
            f"the reviewer and the gate disagree about {key!r}: reviewer "
            f"kept={bool(seen)}, gate says={G.is_input_quotation(key)}")


def test_the_predicate_is_not_an_hdl_reader():
    """A key that LOOKS like HDL is still just a key, and a key naming a
    comment marker is not thereby a comment."""
    assert G.is_input_quotation("input/docs/module foo.md") is True
    assert G.is_input_quotation("input") is False
    assert G.is_input_quotation("// input/docs/spec.md") is True
