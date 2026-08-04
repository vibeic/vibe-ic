"""vibe-ic#712 — a denied value must not be published as a declaration."""
from __future__ import annotations

import ast, json, random, re, subprocess, sys, tempfile
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _prose_polarity as PP            # noqa: E402
import prose_polarity_consulted_check as G  # noqa: E402


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

def _tree(tmp: Path, body: str) -> Path:
    (tmp / "programs").mkdir(parents=True, exist_ok=True)
    (tmp / "programs" / "some_extract.py").write_text(body)
    return tmp


_BLIND = '''
import re
RE = re.compile(r"targets (\\w+)")
def extract(text, rec):
    m = RE.search(text)
    if m:
        rec["pdk_target"] = m.group(1)
    return rec
'''

_AWARE = '''
import re
from _prose_polarity import is_denied
RE = re.compile(r"targets (\\w+)")
def extract(text, rec):
    m = RE.search(text)
    if m and not is_denied(text):
        rec["pdk_target"] = m.group(1)
    return rec
'''


def test_the_gate_sees_a_polarity_blind_extractor(tmp_path):
    assert G.scan(_tree(tmp_path, _BLIND)) == ["some_extract::extract"]


def test_the_gate_clears_one_that_consults_polarity(tmp_path):
    assert G.scan(_tree(tmp_path, _AWARE)) == []


def test_a_grep_that_does_not_write_the_matched_value_is_out_of_scope(tmp_path):
    """The narrowing that keeps the baseline meaningful. 'Any subscript
    assignment' caught 592 functions — every one that greps something and fills
    a dict. Both real defects write the value taken OUT of the prose IN as the
    declaration; that is the shape."""
    body = '''
import re
RE = re.compile(r"foo")
def count(text, rec):
    rec["n"] = len(RE.findall(text))
    rec["seen"] = True
    return rec
'''
    assert G.scan(_tree(tmp_path, body)) == []


def test_no_baseline_is_CANNOT_DETERMINE_not_a_pass(tmp_path):
    _tree(tmp_path, _BLIND)
    r = subprocess.run([sys.executable, str(PROGRAMS / "prose_polarity_consulted_check.py"),
                        "--root", str(tmp_path)],
                       capture_output=True, text=True, timeout=55)
    assert r.returncode == 2
    assert "NOT a pass" in (r.stdout + r.stderr)


def test_a_NEW_polarity_blind_extractor_FAILS(tmp_path):
    root = _tree(tmp_path, "")
    prog = str(PROGRAMS / "prose_polarity_consulted_check.py")
    assert subprocess.run([sys.executable, prog, "--root", str(root),
                           "--write-baseline"], capture_output=True,
                          text=True, timeout=55).returncode == 0
    (root / "programs" / "some_extract.py").write_text(_BLIND)
    r = subprocess.run([sys.executable, prog, "--root", str(root)],
                       capture_output=True, text=True, timeout=55)
    assert r.returncode == 1
    assert "some_extract::extract" in r.stdout
