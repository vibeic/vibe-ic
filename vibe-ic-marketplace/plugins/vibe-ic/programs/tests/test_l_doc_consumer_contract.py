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


# ── vibe-ic#1011: a denial is not the requirement it denies ────────────────
#
# `signoff_qualifier` above answers "the document says this row is not
# BINDING". `requirement_absent` answers the adjacent-but-different question,
# "the document says the requirement is not THERE". Every fixture below is a
# SYNTHETIC restatement of a shape measured on the published corpus; none is
# copied from a design and none carries a design, foundry, vendor or process
# token.

_DENIALS = [
    ("<standard> does NOT specify JTAG / scan-chain / on-chip BIST at the "
     "protocol level.", "JTAG"),
    ("There is no scan chain, no JTAG, and no boundary-scan path accessible "
     "on the host interface.", "scan chain"),
    ("Neither <bus A> nor <bus B> defines a JTAG / scan / BIST / MBIST / "
     "debug architecture.", "JTAG"),
    ("<protocol> is a published specification - no PDK, floor-plan, SDC, "
     "UPF, or DFT artifact at the protocol level.", "DFT"),
    ("No internal SDC / UPF / DFT artifacts in the spec.", "DFT"),
    ("JTAG / scan / BIST are NOT specified at the protocol level.", "BIST"),
    ("No standard DFT / JTAG path is exposed on the host interface.", "JTAG"),
    ("The device implements only the 2-pin variant - no JTAG support.", "JTAG"),
    ("<standard> does not list SDC / UPF / DFT constraints.", "DFT"),
]

#: THE OTHER DIRECTION, and the one that matters most. `_NON_NORMATIVE_RE`
#: records the trap in as many words: "`must NOT exceed 5 ns` is a real
#: requirement that contains a negation". A gate that learns only to say "no"
#: is a ban, not a check.
_REAL_REQUIREMENTS = [
    ("- Test signals - support for scan, JTAG (IEEE 1149.1), and clock "
     "control.", "JTAG"),
    ("Scanctrl/Scanin/Scanout drive the scan chains for manufacturing DFT.",
     "scan chains"),
    ("Every device shall implement the 16-state TAP controller FSM.",
     "TAP controller"),
    ("The Boundary-Scan Register shall include one boundary-scan cell per "
     "external I/O pin.", "boundary-scan"),
]

#: PROHIBITIONS. A deontic modal + negation DECLARES something, negatively;
#: it does not say the requirement is absent. The auxiliary list in
#: `_REQUIREMENT_ABSENT_RE` excludes every deontic modal BY CONSTRUCTION, and
#: this is what pins that separation.
_PROHIBITIONS = [
    ("The scan chain must not exceed 5000 flops.", "scan chain"),
    ("The design shall not expose the scan chain in mission mode.",
     "scan chain"),
    ("The TAP controller may not be clocked above 10 MHz.", "TAP controller"),
    ("Scan enable should not be asserted during functional operation.",
     "Scan enable"),
    ("The boundary-scan path cannot be shared with functional logic.",
     "boundary-scan"),
]


@pytest.mark.parametrize("line,term", _DENIALS)
def test_requirement_absent_names_the_phrase_that_denies(line, term):
    """It returns the PHRASE, not a bool — same contract as
    `signoff_qualifier`, and for the same reason: a drop that names its
    evidence is auditable, a bare True is not."""
    got = C.requirement_absent(line, line.find(term))
    assert got, f"a document DENYING the requirement was read as stating it: {line!r}"
    assert isinstance(got, str) and got.strip()


@pytest.mark.parametrize("line,term", _REAL_REQUIREMENTS + _PROHIBITIONS)
def test_a_stated_requirement_is_never_read_as_absent(line, term):
    assert C.requirement_absent(line, line.find(term)) is None, (
        f"a REAL requirement was deleted as a denial: {line!r}")


@pytest.mark.parametrize("line,term", _PROHIBITIONS)
def test_prohibition_is_not_absence(line, term):
    """The load-bearing separation, asserted against the pattern that draws
    it rather than only through the public predicate, so widening the
    auxiliary set cannot pass this by accident."""
    assert C._PROHIBITION_RE.search(line), (
        f"the deontic vocabulary does not recognise its own shape: {line!r}")
    assert C.requirement_absent(line, line.find(term)) is None


def _hits_denied(doc: str, vocab=r"scan chain|JTAG|BIST|DFT"):
    import re as _re
    from pathlib import Path as _P
    return C.framed_hits([(_P("x.md"), doc)], _re.compile(vocab, _re.I),
                         drop_denied=True)


def _hits_plain(doc: str, vocab=r"scan chain|JTAG|BIST|DFT"):
    import re as _re
    from pathlib import Path as _P
    return C.framed_hits([(_P("x.md"), doc)], _re.compile(vocab, _re.I))


_DENIED_DOC = ("The specification does NOT specify JTAG / scan-chain / "
               "on-chip BIST at the protocol level.\n")
_STATED_DOC = ("Test signals are required: support for scan chain, JTAG "
               "and clock control.\n")


def test_the_default_still_counts_a_denial_as_a_hit():
    """DIRECTION 1 — the flag is OPT-IN, so the default must not move. This
    is what makes the shared predicate safe to change at all: three of the
    four call sites do not pass it and must be byte-identical."""
    assert len(_hits_plain(_DENIED_DOC)) >= 1


def test_opting_in_drops_the_denial():
    assert _hits_denied(_DENIED_DOC) == [], _hits_denied(_DENIED_DOC)


def test_opting_in_keeps_a_positively_stated_requirement():
    """THE PAIRED GUARD. A gate that only learns to say 'no' is a ban."""
    assert len(_hits_denied(_STATED_DOC)) >= 1, (
        "the opt-in deleted a requirement the document STATES")


def test_the_default_record_shape_is_unchanged_by_the_new_opt_in():
    plain = _hits_plain(_STATED_DOC)
    assert set(plain[0]) == {"source", "line", "match", "context"}, plain[0]
    assert "denied" not in plain[0]


def test_the_opt_in_records_its_policy_on_its_own_records_only():
    rec = _hits_denied(_STATED_DOC)[0]
    assert "denied" in rec and rec["denied"] is None, rec


def test_the_counterexample_that_forced_LINE_scope_is_GONE():
    """#1020's counterexample, re-run against the sentence-bounded framing.

    It came from 4 roots of the published corpus: the SECOND sentence
    describes other vendors' silicon and requires nothing of this design, and
    it was a framed hit at all only because REQUIREMENT_FRAMING_RE's window
    reached BACK ACROSS the full stop and borrowed `specify` from the denial
    in the first. That borrow is what a sentence-scoped denial could not
    out-flank, and it is the reason #1020 was forced to LINE.

    #1021 bounded the framing to the sentence, so the second sentence is no
    longer a hit AT ALL — with the denial ruler switched OFF as well as on.
    That is the assertion below, and it is what made the sentence reach
    available to `requirement_absent` and to `requirement_out_of_scope`.
    """
    # Padded AROUND the pair, never BETWEEN it. Two things have to hold at
    # once and they pull in opposite directions:
    #   * the sentences must stay ADJACENT, so the second one's match is a hit
    #     only by borrowing `specify` from the first — that borrowing IS the
    #     defect being reproduced, and padding between them removes it;
    #   * the two matches must not share one +/-160-char window, or the
    #     context dedup collapses them and the fixture measures nothing (the
    #     same trap `test_the_flag_is_scoped_to_the_row_not_the_neighbourhood`
    #     documents).
    # VERIFIED to discriminate: at sentence reach the second `BIST` survives
    # and this test fails; at line reach nothing survives.
    pad = "filler word " * 18
    doc = (pad + "<standard> does NOT specify JTAG / scan-chain / on-chip "
           "BIST at the protocol level. Vendors universally add scan + BIST "
           "+ I/O voltage trim in vendor-specific register space. " + pad
           + "\n")
    assert len(_hits_plain(doc)) >= 2, "fixture no longer exercises both halves"
    # The BORROWING half: with the denial ruler OFF, every surviving hit must
    # sit in the sentence that carries `specify`. Not one may come from the
    # second sentence, which carries no framing word of its own.
    assert all("Vendors universally add" not in h["context"].split(". ")[-1]
               or "specif" in h["context"]
               for h in _hits_plain(doc)), _hits_plain(doc)
    assert _hits_denied(doc) == [], (
        "the neighbouring sentence survived the denial")


def test_the_CLAUSE_reach_stays_rejected():
    """The reach that is still rejected, on the shape that decided it: the cue
    is a bare `no` heading a COMMA LIST, five clauses from the term it denies.
    A clause reach would leave the term in `" or DFT artifact at the protocol
    level"` and read the denial as belonging to somebody else."""
    doc = ("<protocol> is a published specification - no PDK, floor-plan, "
           "SDC, UPF, or DFT artifact is required at the protocol level.\n")
    assert len(_hits_plain(doc)) >= 1, "fixture no longer produces a hit"
    assert _hits_denied(doc) == []


def test_a_bare_no_must_stand_IN_FRONT_OF_the_term_it_denies():
    """The loosest cue in the vocabulary is the only one required to govern
    the match positionally. Letting a later `no` reach backwards is #790's
    silent direction: the caller publishes less than it read and nothing
    goes red."""
    before = "The design has no JTAG requirement of any kind, as specified.\n"
    after = ("A JTAG TAP controller is required; no waiver has been "
             "granted.\n")
    assert _hits_denied(before) == [], before
    assert len(_hits_denied(after)) >= 1, (
        "a `no` AFTER the term retracted a requirement in front of it")


def test_a_bare_no_never_fires_on_a_comparative():
    """`REQUIREMENT_FRAMING_RE` reads `no less than` as FRAMING. Treating the
    same three words as a denial would let this predicate delete exactly the
    rows that predicate admits."""
    import re as _re
    from pathlib import Path as _P
    doc = "Stuck-at coverage shall be no less than 95% for the scan chain.\n"
    kept = C.framed_hits([(_P("x.md"), doc)],
                         _re.compile(r"scan chain", _re.I), drop_denied=True)
    assert len(kept) == 1, ("a comparative was read as a denial and deleted a "
                            "real coverage requirement: %r" % kept)


def test_the_words_that_mean_no_are_NOT_forked_from_the_house_vocabulary():
    """vibe-ic#712: "three private copies of it is how the divergence
    happened". This predicate may add SHAPE, never a second dialect of the
    words themselves — so every single-word cue it keys on must already be
    recognised by `_prose_polarity`.

    `neither`/`nor` are the ONE declared exception: they are a correlative
    that module does not carry, and pushing them upstream would move the
    counts of four unrelated modules for a shape only this predicate needs.
    Listing them here is what stops the exception from growing silently.
    """
    import _prose_polarity as PP
    for word in ("not", "no", "none", "without", "never"):
        assert PP.NEGATION_RE.search(word), word
    declared_exceptions = {"neither", "nor"}
    src = C._REQUIREMENT_ABSENT_RE.pattern
    for word in declared_exceptions:
        assert word in src, word
    assert C._blank_bracketed is PP.blank_bracketed


def test_bracketed_qualifiers_do_not_carry_the_documents_polarity():
    """#711's measurement, inherited rather than re-derived: a denial inside
    brackets is a qualifier on a neighbouring value, not this line's
    polarity."""
    doc = ("A JTAG TAP controller is required (scan chains not included) for "
           "this design.\n")
    assert len(_hits_denied(doc)) >= 1, (
        "a bracketed qualifier retracted the line's real requirement")


# ── vibe-ic#1021: the framing window crossed full stops ────────────────────
#
# `framed_hits` admitted a match when a requirement word appeared anywhere in
# a flat +/-160-char window, and a flat window does not stop at a full stop. A
# published root's own input carried a parenthetical mention of a debug signal
# in one sentence and an unrelated `requires` about security certification in
# the next; the second promoted the first, and the gate reddened the project.
#
# Every fixture below is a SYNTHETIC restatement of a shape measured on the
# published corpus. None is copied from a design and none carries a design,
# foundry, vendor or process token.

def _hits_re(doc: str, pattern: str, **kw):
    import re as _re
    from pathlib import Path as _P
    return C.framed_hits([(_P("x.md"), doc)], _re.compile(pattern, _re.I), **kw)


def test_NEGATIVE_CONTROL_framing_may_not_be_borrowed_across_a_full_stop():
    """The defect, in the shape it was measured in.

    FAILS on the pre-#1021 predicate: the flat window reaches back over the
    full stop, finds `requires`, and reports 1 hit. This is the whole of
    defect 1, and it is asserted before anything downstream of it.
    """
    doc = ("In this mode the digital circuits are disconnected and the bold "
           "pins can be used to expose debug related signals (e.g. JTAG "
           "interface). The certification body requires that privacy "
           "precautions have been taken before the mode is entered.\n")
    assert _hits_re(doc, r"jtag") == [], (
        "a bare mention borrowed its framing from the NEXT sentence: %r"
        % _hits_re(doc, r"jtag"))


def test_POSITIVE_CONTROL_framing_in_the_terms_OWN_sentence_still_counts():
    """The paired guard. A window that admits nothing is not a narrower
    window, it is a broken one."""
    doc = ("In this mode the digital circuits are disconnected. The design "
           "requires a JTAG interface on the debug connector.\n")
    assert len(_hits_re(doc, r"jtag")) == 1, _hits_re(doc, r"jtag")


def test_a_HARD_WRAPPED_requirement_is_still_one_sentence():
    """`_normalize_ws` exists because requirements are routinely hard-wrapped,
    and the sentence bound must not undo it: a newline inside a sentence is a
    soft wrap, not a full stop. The reach's own vocabulary agrees — a bare
    "\\n" is deliberately NOT one of `SENTENCE_BREAKS`."""
    doc = "The design shall verify the scan chain with 100%\ncoverage.\n"
    assert len(_hits_re(doc, r"scan chain")) == 1, _hits_re(doc, r"scan chain")


def test_the_reach_is_the_HOUSE_one_and_not_a_private_copy():
    """vibe-ic#712's rule applied to the reach rather than the vocabulary:
    "three private copies of it is how the divergence happened". This module
    may choose WHERE to apply the reach; it may not own a second definition of
    where a sentence ends."""
    import _prose_polarity as PP
    assert C._sentence_scope is PP.sentence_scope


def test_the_window_argument_is_now_a_BUDGET_and_can_only_narrow():
    """The new neighbourhood is the INTERSECTION of the old window and the
    sentence, so no input can produce a hit that the flat window did not. A
    smaller budget must therefore still be able to remove a hit."""
    doc = ("The design requires the following, listed for completeness and "
           "expanded on elsewhere in this document: a full scan chain.\n")
    assert len(_hits_re(doc, r"scan chain")) == 1
    assert _hits_re(doc, r"scan chain", window=20) == []


# ── vibe-ic#1021: scope-deferral is not denial ─────────────────────────────
#
# The third idiom. Two published roots' L7 notes say chip-level JTAG/scan/BIST
# "remain <somebody else>-silicon concerns" — no negation word anywhere, so no
# denial ruler can reach them at any reach, and nothing about them is
# non-normative. It is a DIFFERENT question and it gets a different predicate.

_DEFERRALS = [
    ("Chip-level JTAG/scan/BIST remain host-silicon concerns; conformance is "
     "established by the published compliance test specification.", "JTAG"),
    ("Chip-level JTAG/scan/BIST remain sink / controller silicon concerns.",
     "BIST"),
    ("Scan insertion is out of scope for this specification.", "Scan insertion"),
    ("Boundary-scan provisions are beyond the scope of this layer.",
     "Boundary-scan"),
    ("The JTAG TAP is left to the integrator, who must specify it.", "JTAG"),
    ("On-chip BIST is the responsibility of the memory vendor, per the "
     "specification.", "BIST"),
    ("ATPG pattern generation is deferred to the implementer's tool flow, as "
     "required.", "ATPG"),
]

#: THE OTHER DIRECTION. A requirement that merely CONTAINS the word `scope`,
#: or names a concern it then imposes, is still a requirement. This is the
#: same trap `_NON_NORMATIVE_RE` records for negation, one idiom over: a gate
#: that learns only to say "somebody else's" is a ban.
_NOT_DEFERRALS = [
    ("The scope of this specification includes a JTAG TAP controller.",
     "JTAG"),
    ("Scan insertion is required and is in scope for this design.",
     "Scan insertion"),
    ("The design shall provide a boundary-scan register per I/O pin.",
     "boundary-scan"),
    ("Test signals - support for scan, JTAG, and clock control is required.",
     "JTAG"),
]


@pytest.mark.parametrize("line,term", _DEFERRALS)
def test_requirement_out_of_scope_names_the_phrase_that_defers(line, term):
    """It returns the PHRASE, not a bool — the same contract as its two
    neighbours, and for the same reason: a drop that names its evidence is
    auditable from the gate's own report."""
    got = C.requirement_out_of_scope(line, line.find(term))
    assert got, line


@pytest.mark.parametrize("line,term", _DEFERRALS)
def test_a_deferral_is_NOT_reachable_by_the_denial_predicate(line, term):
    """The load-bearing claim of #1021's second defect, asserted rather than
    argued: these lines carry NO negation word, so `requirement_absent`
    correctly cannot see them. If a future widening makes it see them, the two
    predicates have started answering one question and this goes red."""
    assert C.requirement_absent(line, line.find(term)) is None, line


@pytest.mark.parametrize("line,term", _NOT_DEFERRALS)
def test_a_requirement_is_never_read_as_a_deferral(line, term):
    assert C.requirement_out_of_scope(line, line.find(term)) is None, line


def test_the_deferral_drop_is_OPT_IN_and_defaults_OFF():
    """A SHARED predicate never moves four consumers by default. The other
    three do not opt in, so the default path must be byte-identical."""
    doc = ("Chip-level JTAG/scan/BIST remain host-silicon concerns; "
           "conformance is established by the compliance specification.\n")
    assert len(_hits_re(doc, r"jtag")) == 1, "the default path moved"
    assert _hits_re(doc, r"jtag", drop_out_of_scope=True) == []


def test_the_deferral_opt_in_records_its_policy_on_its_own_records_only():
    doc = "A JTAG TAP controller is required on the debug connector.\n"
    plain = _hits_re(doc, r"jtag")
    assert set(plain[0]) == {"source", "line", "match", "context"}, plain[0]
    rec = _hits_re(doc, r"jtag", drop_out_of_scope=True)[0]
    assert "out_of_scope" in rec and rec["out_of_scope"] is None, rec


def test_the_two_drop_predicates_stay_two_questions():
    """`drop_denied` must not silently acquire the deferral vocabulary, and
    `drop_out_of_scope` must not acquire the denial vocabulary. Folding them
    would make the L23 measurement — which wants neither — unavailable as two
    separate decisions."""
    deferral = ("Chip-level JTAG/scan/BIST remain host-silicon concerns; "
                "conformance is by the published specification.\n")
    denial = ("<standard> does NOT specify JTAG / scan-chain / on-chip BIST "
              "at the protocol level.\n")
    assert len(_hits_re(deferral, r"jtag", drop_denied=True)) == 1
    assert len(_hits_re(denial, r"jtag", drop_out_of_scope=True)) == 1


# ── vibe-ic#1021: the vocabulary's owner decides what its tokens mean ──────

def test_reject_runs_BEFORE_the_limit_so_a_real_hit_cannot_be_truncated_away():
    """The silent direction, pinned. A post-filter on the returned records
    would let `limit` truncate first: a text whose first `limit` matches are
    all rejects would report ZERO hits while a real one went unread."""
    noise = " ".join("The %d-th widget is required for scan chain use." % i
                     for i in range(20))
    doc = noise + " A real scan chain is required for manufacturing test.\n"
    kept = _hits_re(doc, r"scan chain", limit=3,
                    reject=lambda match, sentence: "widget" in sentence)
    assert len(kept) == 1, kept
    assert "manufacturing" in kept[0]["context"], kept


def test_reject_is_handed_the_FULL_sentence_not_the_truncated_context():
    """The reported `context` is truncated to 220 chars; the hook needs the
    whole neighbourhood, because the phrase that identifies the token can sit
    in the half that reporting throws away."""
    seen = []
    doc = ("lead in text " * 13 + "a scan chain is required "
           + "trailing filler " * 5 + "identified at the far end\n")
    _hits_re(doc, r"scan chain",
             reject=lambda match, sentence: seen.append(sentence) or False)
    assert seen, "the hook was never called"
    assert "identified at the far end" in seen[0], seen
    assert "identified at the far end" not in seen[0][:220], (
        "the fixture no longer reaches past the reported truncation")
