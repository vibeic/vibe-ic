"""vibe-ic#712 — a denied value must not be published as a declaration."""
from __future__ import annotations

import ast, json, random, re, sys, tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _prose_polarity as PP            # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── the shared vocabulary ───────────────────────────────────────────────────

def test_the_two_real_sentences_are_both_denials():
    """Verbatim from #706 and #711 — with the value itself neutralised, so no
    PDK, vendor or part number appears in this repo's tests."""
    assert PP.is_denied("This block is NOT targeted at <a process>.")
    assert PP.is_denied("has NO meaning here and is REMOVED, not translated")


def test_a_plain_declaration_is_not_a_denial():
    assert PP.is_denied("Targeted at <a process>, 250nm CMOS.") is None
    assert PP.is_denied("die area 1200 x 900 um") is None


def test_a_parenthetical_qualifier_does_not_read_as_a_denial():
    """#711's measurement: real die statements carry harmless negations inside
    brackets, so those are blanked before looking."""
    assert PP.is_denied("die area 1200 x 900 um (not including seal ring)") is None
    assert PP.is_denied("die area 1200 x 900 um, not applicable here") is not None


def test_the_bracket_fast_reject_is_sound_for_every_bracket_family():
    """`blank_bracketed` skips the regex when the text holds no opening bracket.
    That is only sound if EVERY alternative needs one, so each family is checked
    through the function itself rather than by reading the pattern."""
    for op, cl in (("(", ")"), ("[", "]"), ("{", "}")):
        t = f"die area 1200 x 900 um {op}not including seal ring{cl}"
        assert PP.blank_bracketed(t) == t[:23] + " " * (len(t) - 23)
        assert PP.is_denied(t) is None, t
        assert PP.is_denied(t, ignore_bracketed=False) is not None, t
    assert PP.blank_bracketed("no brackets here") == "no brackets here"


@pytest.mark.consistency
def test_the_no_caller_claim_in_the_docstring_matches_the_tree():
    """The module states that `sentence_scope` has no caller, and rests its
    whole containment argument on that. A claim a reader has to take on faith is
    the shape #712 exists to remove, so it is checked here rather than asserted.

    If a caller is added, this goes red: update the sentence, then this passes
    again. That is the point — the prose and the tree cannot drift apart."""
    claim = "HAS NO CALLER IN THIS TREE" in (PP.__doc__ or "")
    callers = []
    for p in sorted(PROGRAMS.glob("*.py")):
        if p.name == "_prose_polarity.py":
            continue
        tree = ast.parse(p.read_text(errors="replace"))
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and (n.module or "").endswith(
                    "_prose_polarity"):
                if any(a.name == "sentence_scope" for a in n.names):
                    callers.append(p.name)
            elif isinstance(n, ast.Attribute) and n.attr == "sentence_scope":
                callers.append(p.name)
    if claim:
        assert callers == [], (
            f"the docstring claims no caller, but {sorted(set(callers))} call it")
    else:
        assert callers, "the no-caller claim was dropped but there is still no caller"


def test_the_denial_word_is_returned_not_a_bare_bool():
    """A refusal that names its evidence is checkable; a bare False is not."""
    assert PP.is_denied("this is REMOVED").lower() == "removed"


def test_both_landed_extractors_now_share_one_vocabulary():
    """#706 and #711 each grew a private copy within a day of each other, and
    #711's own comment records why the second had to be written: the blindness
    'survived in the neighbouring field of the same document'."""
    for mod in ("phase1_doc_one_shot_runner", "floorplan_contract"):
        src = (PROGRAMS / f"{mod}.py").read_text()
        assert "_prose_polarity" in src, f"{mod} still carries its own copy"


# ── the SCOPE: how far a denial reaches (vibe-ic#790) ───────────────────────
#
# `sentence_scope` clamped its BACKWARD reach at a sentence break and let its
# FORWARD reach run to a flat character count that stopped at nothing. The two
# directions are two different defects and both are tested here:
#
#   OVER-reach   a denial retracts a value it does not deny -> a real number is
#                silently dropped. Nothing goes red; the extractor just reports
#                less than it read. This is the quiet direction.
#   UNDER-reach  the reach stops short of a denial that does govern the value ->
#                a denied value is published as a declaration, which is #706 and
#                #711 exactly.


def _scope(text, pat, **kw):
    m = re.search(pat, text)
    assert m, pat
    lo, hi = PP.sentence_scope(text, m.start(), m.end(), **kw)
    return text[lo:hi]


def _denied(text, pat, **kw):
    return PP.is_denied(_scope(text, pat, **kw))


# --- OVER-reach: a denial must not retract a value it does not deny ----------

def test_a_later_sentence_denial_does_not_retract_this_sentence_number():
    """The forward reach used to stop at nothing, so the NEXT statement's denial
    retracted this one's value."""
    t = "The die area is 1200 x 900 um. The previous revision is not applicable."
    assert _denied(t, r"1200 x 900 um") is None


def test_the_forward_reach_stops_at_every_break_the_backward_one_does():
    """The rule is the same rule in both directions, or it is not a rule. Each
    break is checked with the denial placed AFTER the value and again BEFORE
    it; the two answers must agree."""
    for brk in PP.SENTENCE_BREAKS:
        fwd = "die area 1200 x 900 um" + brk + "that plan is not applicable"
        bwd = "that plan is not applicable" + brk + "die area 1200 x 900 um"
        assert _denied(fwd, r"1200 x 900 um") is None, brk
        assert _denied(bwd, r"1200 x 900 um") is None, brk


def test_a_neighbouring_record_denial_does_not_retract_this_records_number():
    """The measured shape: a machine-generated report whose consecutive lines
    are unrelated RECORDS. `cells: 87` suppressed by a `no drc errors found`
    printed two records away — in EITHER direction."""
    after = "cells: 87\nshapes: 4211\nno drc errors found\n"
    before = "no drc errors found\nshapes: 4211\ncells: 87\n"
    for t in (after, before):
        assert _denied(t, r"cells: 87", extra_breaks=("\n",)) is None, t


def test_a_record_break_is_declared_by_the_caller_not_assumed():
    """A bare newline is a SOFT WRAP in prose and a RECORD END in a report. The
    helper cannot know which, so the caller says — and a caller that says
    nothing keeps prose behaviour."""
    t = "cells: 87\nno drc errors found\n"
    assert _denied(t, r"cells: 87") is not None
    assert _denied(t, r"cells: 87", extra_breaks=("\n",)) is None


def test_extra_breaks_cannot_switch_sentence_bounding_off():
    """They ADD. A caller must not be able to opt out of the sentence rule by
    declaring its own breaks."""
    t = "die area 1200 x 900 um. that plan is not applicable"
    assert _denied(t, r"1200 x 900 um", extra_breaks=("|",)) is None


def test_an_empty_extra_break_cannot_collapse_the_scope_onto_the_match():
    """An empty string is found everywhere: `rfind` returns the search end and
    `find` the search start, so an unguarded empty break clamps the window to
    the match itself and NOTHING is ever denied — the quiet direction, switched
    fully on by one bad element in a caller's tuple."""
    t = "The old floorplan is removed, the die area 1200 x 900 um."
    assert _denied(t, r"1200 x 900 um") == "removed"
    assert _denied(t, r"1200 x 900 um", extra_breaks=("",)) == "removed"
    assert _scope(t, r"1200 x 900 um", extra_breaks=("",)) != "1200 x 900 um"


# --- UNDER-reach: a denial that DOES govern the value must still retract it ---

def test_a_denial_across_a_comma_still_retracts():
    t = "The old floorplan is removed, the die area 1200 x 900 um."
    assert _denied(t, r"1200 x 900 um") == "removed"


def test_a_denial_across_a_semicolon_still_retracts():
    """A semicolon JOINS two independent clauses into ONE sentence. `; ` was in
    the original backward break set, so this denial was cut off from the number
    it governs."""
    t = "The old floorplan is removed; the die area 1200 x 900 um."
    assert _denied(t, r"1200 x 900 um") == "removed"
    fwd = "The die area 1200 x 900 um; that plan is removed."
    assert _denied(fwd, r"1200 x 900 um") == "removed"


def test_a_period_inside_a_parenthetical_does_not_end_the_sentence():
    """`(superseded by rev 2. see note)` is a qualifier, not two sentences.
    Cutting the scope at that '. ' loses the `not` that governs the number.
    Breaks are located on bracket-blanked text for exactly this."""
    t = ("This block is not applicable (superseded by rev 2. see note) "
         "for die area 1200 x 900 um.")
    assert _denied(t, r"1200 x 900 um") == "not"
    fwd = ("The die area 1200 x 900 um (rev 4. draft) does not apply.")
    assert _denied(fwd, r"1200 x 900 um") is not None


def test_the_backward_scan_does_not_accumulate_its_own_clamps():
    """Every break index is measured from ONE fixed base. Adding each hit onto
    an already-advanced `lo` overshot the real sentence start by the width of
    every earlier clamp, cutting into the sentence itself. It needs TWO breaks
    of different kinds behind the match to show, which is why it survived: the
    second clamp is displaced by exactly the width of the first."""
    t = "One thing. Two things! removed, die area 1200 x 900 um."
    assert _scope(t, r"1200 x 900 um") == "removed, die area 1200 x 900 um."
    assert _denied(t, r"1200 x 900 um") == "removed"


def test_the_budget_does_not_truncate_one_half_of_a_long_sentence():
    """`before`/`after` bound how much text is read at all. Unequal defaults
    reintroduce, as a character count, the asymmetry the break rule removes."""
    pad = "which the integration team reviewed at length " * 4
    t = "The die area 1200 x 900 um, " + pad + ", is not applicable."
    assert len(pad) > 120
    assert _denied(t, r"1200 x 900 um") == "not"


# --- the two directions, measured over the helper's own input space ----------

_DENY = ["the die area VAL{n} um is not applicable",
         "not applicable, the die area VAL{n} um",
         "the old floorplan is removed; the die area VAL{n} um",
         "the die area VAL{n} um; that plan is removed",
         "superseded (see rev 2. note) for die area VAL{n} um",
         "the die area VAL{n} um (rev 4. draft) does not apply",
         "there is no die area VAL{n} um here",
         "VAL{n} cells were never read",
         "die area VAL{n} um is n/a",
         "die area VAL{n} um 不适用"]
_CLEAN = ["the die area is VAL{n} um",
          "cells: VAL{n} read from the layout",
          "VAL{n} shapes were counted",
          "total area VAL{n} recorded (rev 4. draft)",
          "the run reports VAL{n} polygons; the layout was read",
          "checking rule m1.1 over VAL{n} shapes"]


def test_neither_direction_diverges_from_the_statement_that_owns_the_value():
    """ORACLE fuzz. The corpus is BUILT from statements whose polarity is known,
    so ground truth is not another implementation: a value is denied exactly
    when the STATEMENT it sits in denies it. Both separator families are swept —
    sentence breaks, and a declared record break."""
    for s in _CLEAN:
        assert PP.is_denied(s.format(n=1)) is None, s
    val = re.compile(r"\bVAL(\d+)\b")
    rng = random.Random(0x712790)
    over = under = total = 0
    for seps, extra in ((list(PP.SENTENCE_BREAKS), ()), (["\n"], ("\n",)),
                        (list(PP.SENTENCE_BREAKS) + ["\n"], ("\n",))):
        for _ in range(500):
            truth, parts = {}, []
            for i in range(rng.randint(2, 6)):
                deny = rng.random() < 0.5
                parts.append(rng.choice(_DENY if deny else _CLEAN).format(n=i + 1))
                truth[i + 1] = deny
            text = rng.choice(seps).join(parts)
            for m in val.finditer(text):
                lo, hi = PP.sentence_scope(text, m.start(), m.end(),
                                           extra_breaks=extra)
                got = PP.is_denied(text[lo:hi]) is not None
                want = truth[int(m.group(1))]
                total += 1
                over += got and not want
                under += want and not got
    assert total > 5000, total
    assert (over, under) == (0, 0), f"{over} over-reach, {under} under-reach"


# ── the gate ────────────────────────────────────────────────────────────────
















# ---------------------------------------------------------------------------
# NOT PROSE: an exemption, and the two ways it must be able to go wrong
#
# The set exists because a DEF/LEF production has no negation form — there is no
# way to write "this via does NOT connect MET1 and MET2" — so `_prose_polarity`
# on a VIAS entry would be an unreachable branch, and an unreachable branch is a
# green light rather than a check. That argument is only safe if the set cannot
# quietly become a waiver list, so it is fenced in both directions and both
# fences are exercised here.
# ---------------------------------------------------------------------------








#: The real tree, and ONE scan of it for the whole module.
#:
#: `G.scan(real)` walks every `programs/*.py` and costs 55-62s on a loaded host
#: — measured, it was the top two entries of `--durations` here. Two tests need
#: it and each used to pay separately, which put this module's slowest test at
#: 103s against the harness's 180s per-test ceiling. `scan` is deterministic and
#: read-only, and `exemption_audit` takes the RESULT as an argument rather than
#: re-deriving it, so one scan serves both. It is NOT cached across the
#: `_NOT_PROSE` mutation in the test below, and does not need to be: the scan
#: does not read that register.
_REAL = Path(__file__).resolve().parents[1].parent






# ── the PRECISION of "writes the matched value" (vibe-ic#712, second round) ──
#
# The gate went red on a file that landed after the baseline was written, with
# two names out of one module. Neither is an extractor:
#
#   `_names`      a word-boundary predicate. It searches prose and returns a
#                 bool; the only thing it writes into a dict is the compiled
#                 pattern it memoises.
#   `flip_source` a source mutator. It matches Python's own quote grammar at a
#                 recorded (line, column) and splices the CALLER'S replacement
#                 in, then hands the mutated source to pytest.
#
# One is fixed by narrowing the predicate, the other is exempted as formal
# grammar. Which of the two applies is not interchangeable: `_names` reads real
# English (docstrings and comments), so claiming NOT PROSE for it would be
# false, and `flip_source` genuinely writes a value out of the text it matched,
# so no narrowing reaches it honestly.
#
# The four tests below the first one are the CONTROL on the narrowing. Two
# wider narrowings were built and measured before this one, and both dropped a
# real finding off the register; those exact shapes are pinned here so the
# rejection cannot be quietly re-litigated.

_PATTERN_MEMO = '''
import re
_CACHE = {}
def names(text, token):
    """`token` in `text`, not glued to an identifier character."""
    pat = _CACHE.get(token)
    if pat is None:
        left = r"(?<![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", token) else ""
        right = r"(?![A-Za-z0-9_])" if re.search(r"[A-Za-z0-9_]$", token) else ""
        pat = re.compile(left + re.escape(token) + right)
        _CACHE[token] = pat
    return bool(pat.search(text))
'''




_COMPILE_AND_PUBLISH = '''
import re
def extract(text, rec):
    m = re.search(r"targets (\\w+)", text)
    if m:
        val = m.group(1)
        pat = re.compile(val)
        rec["probe"] = pat.pattern
        rec["pdk_target"] = val
    return rec
'''




_LITERAL_CHOSEN_BY_A_SEARCH = '''
import re
def extract(text):
    m = re.search(r"\\b(adder|multiplier)\\b", text)
    if not m:
        return None
    d = {"op": m.group(1)}
    sat = "saturate" if re.search(r"saturat", text) else None
    if sat:
        d["overflow"] = sat
    return d
'''




_COLUMN_FOUND_BY_A_HEADER_MATCH = '''
import re
_HDR = re.compile(r"resolution", re.I)
def extract(rows, rec):
    hdr = rows[0].split("|")
    res_c = next((k for k, h in enumerate(hdr) if _HDR.match(h)), None)
    cells = rows[1].split("|")
    rec["resolution"] = cells[res_c]
    return rec
'''














# ---------------------------------------------------------------------------
# vibe-ic#2010 item 6 — the two tech-LEF readers in pdk_via_patch_legalize are
# NOT PROSE. Both fences: the scan still FLAGS them (so the entries are live
# findings, not padding), and the audit accepts the exemption.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# vibe-ic#712 — the frame contract reads a denial SCOPED TO THE CLAUSE IT
# GOVERNS. Both directions, because a blanket sentence-wide check passes the
# first of these and FAILS the second, and the second is #2035's own fixture.
# ---------------------------------------------------------------------------
def _frame_latency(text, ins=("frame",), outs=("valid",)):
    import importlib
    fc = importlib.import_module("_frame_contract")
    return fc.extract_frame_contract(text, list(ins), list(outs), []).latency


def _frame_interframe(text, ins=("rx",), outs=("frame_done",)):
    import importlib
    fc = importlib.import_module("_frame_contract")
    return fc.extract_frame_contract(text, list(ins), list(outs), []).interframe


def test_a_denial_in_the_bounds_own_clause_publishes_no_bound():
    """DIRECTION 1. The denial is IN the clause that carries the number, so the
    clause states no bound and none may be published.

    MEASURED on e1814e28d, before this: all three of these returned the SAME
    `exactly 3 cycles, frame -> valid` as the affirmation, and
    `spec_conformance_check._frame_contract_findings` then reported an ERROR
    against RTL for violating a bound the document had denied.
    """
    assert _frame_latency(
        "The output valid is asserted exactly 3 cycles after the input frame "
        "is accepted.") is not None, "precondition: the affirmed form IS read"

    for denied in (
            "There is no 3 cycle latency between the input frame and the "
            "output valid.",
            "The output valid is NOT asserted 3 cycles after the input frame "
            "is accepted; it is combinational.",
            "The 3 cycle latency from frame to valid is removed; nothing "
            "replaces it.",
    ):
        assert _frame_latency(denied) is None, denied


def test_a_denial_qualifying_a_DIFFERENT_clause_keeps_the_stated_bound():
    """DIRECTION 2, and the one a blanket check gets wrong.

    This sentence is #2035's own fixture, verbatim. It STATES an interframe
    bound and then qualifies it in a semicolon-joined clause that happens to
    contain "is not". The denial governs the qualifier, not the number, so the
    bound stands. A sentence-wide denial check withdraws it and turns a false
    negative into a false positive — which is precisely what
    `_prose_polarity.concept_is_constitutive` warns a blanket check does.
    """
    kept = _frame_interframe(
        "Consecutive frames must be separated by at least 3 idle bit periods; "
        "a start bit seen sooner is not the start of a frame.")
    assert kept is not None, "the affirmed interframe bound must survive"
    assert kept.value == 3, kept

    # and the same shape for a latency, so the rule is not pinned to one field
    assert _frame_latency(
        "The output valid is asserted exactly 3 cycles after the input frame "
        "is accepted. No DRC errors were found.") is not None
