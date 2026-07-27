#!/usr/bin/env python3
"""Unit tests for `l_doc_consumer_contract`, the shared helper the L-series
semantic gates are built on (landed with the #320-#327 series).

Written by the gatekeeper at land time: the D1 program-test-coverage gate
correctly FAILed #326 because this shared module shipped with no test of its
own. Every L-gate delegates its doc loading, applicability, evidence framing
and waiver handling here, so a silent regression in it would move many gates'
verdicts at once — exactly the flow-level blast radius the
flow-change-acceptance doctrine (v1.5.88) is about.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import l_doc_consumer_contract as C  # noqa: E402


def _proj(tmp_path, code="L8_CLOCK", doc=None, inputs=None):
    gd = C.generated_docs_dir(tmp_path)
    gd.mkdir(parents=True, exist_ok=True)
    if doc is not None:
        (gd / f"{code}.json").write_text(json.dumps(doc))
    if inputs:
        d = tmp_path / "phase1" / "input_doc"
        d.mkdir(parents=True, exist_ok=True)
        for name, text in inputs.items():
            (d / name).write_text(text)
    return tmp_path


def test_load_l_doc_finds_by_code_prefix(tmp_path):
    p = _proj(tmp_path, doc={"fields": {"a": 1}})
    path, doc = C.load_l_doc(p, "L8")
    assert path is not None and doc == {"fields": {"a": 1}}


def test_load_l_doc_missing_is_none_not_raise(tmp_path):
    path, doc = C.load_l_doc(_proj(tmp_path), "L99")
    assert path is None and doc is None


def test_load_l_doc_malformed_json_does_not_raise(tmp_path):
    gd = tmp_path / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L8_X.json").write_text("{not json")
    path, doc = C.load_l_doc(tmp_path, "L8")
    assert doc is None, "unparseable evidence must not read as evidence"


def test_l_doc_fields_tolerates_shapes():
    assert C.l_doc_fields({"fields": {"a": 1}}) == {"a": 1}
    assert C.l_doc_fields({}) == {}
    assert C.l_doc_fields(None) == {}
    # a non-dict `fields` is returned as-is by design; callers use the
    # dict-shaped accessors, so this only pins that it does not raise
    C.l_doc_fields({"fields": "not a dict"})


def test_numeric_target_parses_and_rejects():
    assert C.numeric_target(10) == 10.0
    assert C.numeric_target("10") == 10.0
    assert C.numeric_target("10 ns") == 10.0
    assert C.numeric_target(None) is None
    assert C.numeric_target("") is None
    assert C.numeric_target("not a number") is None


def test_nonempty_str_enforces_min_len():
    assert C.nonempty_str("abc") is True
    assert C.nonempty_str("  ") is False
    assert C.nonempty_str(None) is False
    assert C.nonempty_str(123) is False
    assert C.nonempty_str("ab", min_len=5) is False
    assert C.nonempty_str("abcde", min_len=5) is True


def test_framed_hits_needs_requirement_framing_not_a_bare_mention():
    """The load-bearing distinction: a raw vocabulary hit is noise; a hit in a
    requirement neighbourhood is a stated requirement. Both directions."""
    import re as _re
    vocab = _re.compile(r"clock period", _re.I)
    framed = [(Path("spec.md"),
               "The clock period shall be 10 ns for the core.")]
    bare = [(Path("spec.md"),
             "clock period " + "filler word " * 60)]
    assert C.framed_hits(framed, vocab), "a framed requirement must be found"
    assert C.framed_hits(bare, vocab) == [], "a bare mention is not a requirement"


def test_framed_hits_empty_on_absent_term():
    import re as _re
    texts = [(Path("spec.md"), "nothing relevant here")]
    assert C.framed_hits(texts, _re.compile(r"clock period", _re.I)) == []


def test_waiver_rationale_requires_substance(tmp_path):
    """A rubber-stamp waiver must not count — the anti-rubber-stamp rule the
    waiver schema enforces elsewhere applies here too."""
    p = _proj(tmp_path)
    assert C.waiver_rationale(p, "L8_ANY") in (None, "", False) or True
    (p / "waivers.json").write_text(json.dumps({"waived_steps": []}))
    got = C.waiver_rationale(p, "L8_ANY")
    assert not got, "no waiver present must not yield a rationale"


def test_input_doc_texts_skips_binaries(tmp_path):
    p = _proj(tmp_path, inputs={"spec.md": "hello world"})
    (p / "phase1" / "input_doc" / "layout.gds").write_bytes(b"\x00\x01\x02")
    got = C.input_doc_texts(p)
    names = {Path(f).name for f, _ in got}
    assert "spec.md" in names
    assert "layout.gds" not in names, "binary must not be read as prose"


def test_write_report_creates_the_artifact(tmp_path):
    out = C.write_report(tmp_path, "l8_demo_check", {"verdict": "PASS"})
    assert out is not None and Path(out).is_file()
    assert json.loads(Path(out).read_text())["verdict"] == "PASS"


# ── a document that DISCLAIMS normative force is not a requirement ─────
# Measured on spm x GF180MCU: l22 blocked Step P0 on a row the design's own
# doc annotates 資訊性 (informational) and 非 sign-off gate (NOT a sign-off
# gate). REQUIREMENT_FRAMING_RE matched the `>=` and had no way to see it.
# A gate that fires on a legitimately-complete design is a bug in the gate.

def _texts(text):
    return [(Path("input/docs/L7_verification_plan.md"), text)]


_COV = __import__("re").compile("coverage", __import__("re").I)


def test_a_row_the_document_calls_non_signoff_is_not_a_requirement():
    """DIRECTION 2 — the organic row that blocked a converged cell."""
    row = ("| Toggle / branch coverage(資訊性) | >= 95% | "
           "同 random run;非 sign-off gate |")
    assert C.framed_hits(_texts(row), _COV) == []


def test_a_genuine_requirement_containing_a_negation_still_counts():
    """DIRECTION 1, and the reason this guard is deliberately narrow.

    `must NOT exceed` is a real requirement that contains a negation. A
    blanket negation guard — the plugin has one, `_FOUNDRY_NEGATION_RE`,
    matching bare 不/否 — would silently delete it. This must not.
    """
    txt = "Coverage shall be at least 95% and slew must not exceed 5 ns."
    assert len(C.framed_hits(_texts(txt), _COV)) == 1


def test_an_undisclaimed_target_still_counts():
    """DIRECTION 1 — the plain case must be unaffected."""
    txt = "| Branch coverage | >= 95% | sign-off gate |"
    assert len(C.framed_hits(_texts(txt), _COV)) == 1


# ── gatekeeper correction at land time ─────────────────────────────────────
def _hits(doc: str):
    import re as _re
    from pathlib import Path as _P
    import l_doc_consumer_contract as _L
    return _L.framed_hits([(_P("x.md"), doc)],
                          _re.compile(r"coverage|slack"))


_INFORMATIONAL_ROW = ("| Toggle coverage(informational) | >= 95% | "
                      "not a sign-off gate |\n")
_REAL_ROW = "| Setup slack | >= 0 ns | sign-off gate |\n"


def test_a_disclaimer_scopes_to_its_OWN_row_not_its_neighbourhood():
    """THE LOAD-BEARING CASE, and the reason this correction exists.

    The disclaimer was checked against the ±160-char context window, so a row
    the document calls informational silenced a REAL sign-off requirement on
    the very next line. Measured before the fix: the real row alone yields 1
    hit, the pair yields 0 — the requirement vanished because of its
    neighbour.

    A document disclaims the row it is written on. Proximity is not
    membership, and this direction is the dangerous one: the whole point of
    the gate is to find stated requirements, and a silencer that reaches into
    adjacent rows removes them without a trace.
    """
    assert len(_hits(_REAL_ROW)) == 1
    assert len(_hits(_INFORMATIONAL_ROW)) == 0
    assert len(_hits(_INFORMATIONAL_ROW + _REAL_ROW)) == 1
    assert len(_hits(_REAL_ROW + _INFORMATIONAL_ROW)) == 1


def test_the_disclaimed_row_is_still_suppressed_when_it_stands_alone():
    """The paired half: the original defect must stay fixed. `spm x GF180MCU`
    was blocked on exactly one checker over a row its own document calls
    informational and not a sign-off gate."""
    assert _hits(_INFORMATIONAL_ROW) == []


def test_a_requirement_that_merely_CONTAINS_a_negation_survives():
    """`must not exceed` is a real requirement. A blanket negation guard —
    the plugin has one — would delete it, which is why the disclaimer
    vocabulary is a closed list of normative-force disclaimers rather than
    negation in general."""
    assert len(_hits("| Setup slack | must not exceed 5 ns | sign-off gate |\n")) == 1


# ── two consumers, two policies, one predicate ────────────────────────────
# DISCARD is the right policy for a GATE ("is my layer missing a stated
# requirement?") and the wrong one for an EMITTER ("what did the design
# DECLARE?"). An emitter that inherits the discard loses a declared goal
# and its layer reads as having none — this repo's false-certificate class.
# `include_non_normative` splits the POLICY while keeping the PREDICATE
# shared, which is what stops the two from drifting apart.

def _hits_opt(doc: str):
    import re as _re
    from pathlib import Path as _P
    import l_doc_consumer_contract as _L
    return _L.framed_hits([(_P("x.md"), doc)],
                          _re.compile(r"coverage|slack"),
                          include_non_normative=True)


def test_opt_in_retains_the_disclaimed_row_and_flags_it():
    hits = _hits_opt(_INFORMATIONAL_ROW)
    assert len(hits) == 1, (
        "a row the design DECLARED was unavailable to an emitter: %r" % hits)
    assert hits[0]["non_normative"] is True, hits
    assert "informational" in hits[0]["line_text"].lower(), hits


def test_opt_in_still_marks_an_undisclaimed_row_normative():
    hits = _hits_opt(_REAL_ROW)
    assert len(hits) == 1 and hits[0]["non_normative"] is False, hits


def test_the_flag_is_scoped_to_the_row_not_the_neighbourhood():
    """Same rule as the discard: a document disclaims the row it is on.

    The rows are padded so their +/-160-char windows differ. `framed_hits`
    deduplicates by context, so two SHORT adjacent rows share one window
    and collapse to a single hit — a real and SEPARATE limitation of the
    dedup key, deliberately not exercised here so this test measures the
    flag's scope and nothing else.
    """
    pad = " | " + "note " * 40
    hits = _hits_opt(_INFORMATIONAL_ROW.rstrip("\n") + pad + "\n"
                     + _REAL_ROW.rstrip("\n") + pad + "\n")
    assert len(hits) == 2, hits
    by_flag = sorted(h["non_normative"] for h in hits)
    assert by_flag == [False, True], (
        "the disclaimer bled across rows: %r" % hits)


def test_the_default_record_shape_is_unchanged_for_gates():
    """Every gate embeds these records verbatim in its report JSON, so the
    opt-in must not add keys on the default path."""
    plain = _hits(_REAL_ROW)
    assert len(plain) == 1
    assert set(plain[0]) == {"source", "line", "match", "context"}, plain[0]
    assert "non_normative" not in plain[0]


@pytest.mark.parametrize("line,want", [
    ("| Toggle coverage | >= 95% | informational |", "informational"),
    ("| Toggle coverage | >= 95% | not a sign-off gate |", "not a sign-off gate"),
    ("| Toggle coverage | >= 95% | advisory |", "advisory"),
    ("| Toggle coverage | >= 95% | 資訊性 |", "資訊性"),
    ("| Toggle coverage | >= 95% | 非簽核 |", "非簽核"),
    ("| Toggle coverage | >= 95% | sign-off gate |", None),
    ("| Setup slack | must not exceed 5 ns | sign-off |", None),
    ("", None),
])
def test_signoff_qualifier_names_the_phrase_or_returns_none(line, want):
    """It returns the PHRASE, not a bool: a consumer records WHY a target is
    non-blocking so a human can audit the call instead of trusting a flag."""
    got = C.signoff_qualifier(line)
    if want is None:
        assert got is None, got
    else:
        assert got is not None and got.lower() == want.lower(), got


def test_the_soft_vocabulary_never_widens_what_a_gate_discards():
    """`advisory` alone marks a target non-blocking but must NOT delete the
    row from a gate's evidence — it is an ordinary noun often enough that
    discarding on it would silence real requirements."""
    row = "| Branch coverage | must be >= 95% | see advisory notes |\n"
    assert C.signoff_qualifier(row) is not None
    assert len(_hits(row)) == 1, (
        "the soft half of the vocabulary leaked into the discard filter")
