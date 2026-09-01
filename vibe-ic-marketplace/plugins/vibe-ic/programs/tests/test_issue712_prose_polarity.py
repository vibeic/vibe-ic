"""vibe-ic#712 — a denied value must not be published as a declaration."""
from __future__ import annotations

import ast, json, random, re, sys, tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _prose_polarity as PP            # noqa: E402
import prose_polarity_consulted_check as G  # noqa: E402

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
    r = _pr.run([sys.executable, str(PROGRAMS / "prose_polarity_consulted_check.py"),
                        "--root", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 2
    assert "NOT a pass" in (r.stdout + r.stderr)


def test_a_NEW_polarity_blind_extractor_FAILS(tmp_path):
    root = _tree(tmp_path, "")
    prog = str(PROGRAMS / "prose_polarity_consulted_check.py")
    assert _pr.run([sys.executable, prog, "--root", str(root),
                           "--write-baseline"], capture_output=True,
                          text=True).returncode == 0
    (root / "programs" / "some_extract.py").write_text(_BLIND)
    r = _pr.run([sys.executable, prog, "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "some_extract::extract" in r.stdout


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
def test_an_exemption_removes_the_name_without_touching_the_baseline(tmp_path):
    """The property the whole design turns on: an exemption may NOT be a way of
    raising the register. The count printed against the baseline must be the
    count with the exempted name taken OUT, not a bigger baseline."""
    root = _tree(tmp_path, "")
    (root / "programs" / "some_extract.py").write_text(_BLIND)
    prog = str(PROGRAMS / "prose_polarity_consulted_check.py")
    assert _pr.run([sys.executable, prog, "--root", str(root),
                           "--write-baseline"], capture_output=True,
                          text=True).returncode == 0
    before = json.loads((root / "programs"
                         / "prose_polarity_baseline.json").read_text())
    assert before["known"] == ["some_extract::extract"]

    saved = dict(G._NOT_PROSE)
    try:
        G._NOT_PROSE["some_extract::extract"] = "x" * G._EXEMPT_REASON_MIN
        assert G.exemptions_in_scope(root) == ["some_extract::extract"]
        assert G.exemption_audit(G.scan(root), root) == []
    finally:
        G._NOT_PROSE.clear()
        G._NOT_PROSE.update(saved)
    # and the baseline file on disk is untouched by any of it
    after = json.loads((root / "programs"
                        / "prose_polarity_baseline.json").read_text())
    assert after == before


def test_an_exemption_whose_function_stopped_being_a_finding_FAILS(tmp_path):
    """REVERSE CASE. An entry that names something the scan no longer flags is
    dead weight: it makes the set look larger than the argument behind it, and
    the next reader cannot tell a live exemption from a fossil."""
    root = _tree(tmp_path, "")
    (root / "programs" / "some_extract.py").write_text(_AWARE)   # not blind
    saved = dict(G._NOT_PROSE)
    try:
        G._NOT_PROSE["some_extract::extract"] = "y" * G._EXEMPT_REASON_MIN
        problems = G.exemption_audit(G.scan(root), root)
    finally:
        G._NOT_PROSE.clear()
        G._NOT_PROSE.update(saved)
    assert len(problems) == 1, problems
    assert "Delete the entry" in problems[0]


def test_an_exemption_with_no_real_argument_FAILS(tmp_path):
    """The other fence. A one-word reason is how a register becomes a waiver
    list; the entry has to carry the argument, not a gesture at one."""
    root = _tree(tmp_path, "")
    (root / "programs" / "some_extract.py").write_text(_BLIND)
    saved = dict(G._NOT_PROSE)
    try:
        G._NOT_PROSE["some_extract::extract"] = "n/a"
        problems = G.exemption_audit(G.scan(root), root)
    finally:
        G._NOT_PROSE.clear()
        G._NOT_PROSE.update(saved)
    assert len(problems) == 1, problems
    assert "chars" in problems[0]


def test_an_exemption_for_a_module_this_tree_does_not_have_is_out_of_scope(
        tmp_path):
    """`--root` is aimed at synthetic trees by this file and could be aimed at
    any checkout. An exemption whose module is simply absent is out of scope,
    not stale — judging it would make the verdict depend on which tree the gate
    was pointed at."""
    root = _tree(tmp_path, _BLIND)
    assert G.exemptions_in_scope(root) == []
    assert G.exemption_audit(G.scan(root), root) == []


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


@pytest.fixture(scope="module")
def real_scan():
    return G.scan(_REAL)


def test_the_shipped_exemption_is_live_and_argued(real_scan):
    """Not a fixture — the entry that actually ships. If it ever stops being a
    finding, or its argument is trimmed, this says so."""
    real = _REAL
    assert G.exemption_audit(real_scan, real) == []
    assert G.exemptions_in_scope(real) == sorted(G._NOT_PROSE)
    for reason in G._NOT_PROSE.values():
        assert len(reason.strip()) >= G._EXEMPT_REASON_MIN


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


def test_a_memoised_compiled_pattern_is_not_a_declared_value(tmp_path):
    """A `re.Pattern` is the INSTRUMENT that reads prose, not a value read out
    of prose, and no sentence can deny one. Caching the searcher under the
    needle is keeping a tool; both real defects wrote the matched TEXT."""
    assert G.scan(_tree(tmp_path, _PATTERN_MEMO)) == []


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


def test_the_text_that_goes_into_a_pattern_is_still_tracked(tmp_path):
    """The narrowing is about the OBJECT, not about laundering its input. An
    extractor that compiles the matched text AND publishes it is #706 with an
    extra line, and stays a finding."""
    assert G.scan(_tree(tmp_path, _COMPILE_AND_PUBLISH)) == ["some_extract::extract"]


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


def test_a_literal_chosen_by_a_search_is_still_a_finding(tmp_path):
    """REJECTED NARROWING #1, pinned. Dropping the TEST of a conditional
    expression would have cleared the red name — and would also have cleared
    this, which is #706 itself: the value published is a literal, but WHICH
    literal is decided by a search over prose that was never asked whether it
    denies. 'does NOT saturate' publishes `overflow: saturate`."""
    assert G.scan(_tree(tmp_path, _LITERAL_CHOSEN_BY_A_SEARCH)) == [
        "some_extract::extract"]


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


def test_a_column_located_by_a_match_is_still_a_finding(tmp_path):
    """REJECTED NARROWING #2, pinned. Excluding names used only as SLICE bounds
    would have cleared the source mutator — and would also have cleared this,
    which publishes a document's own resolution column verbatim."""
    assert G.scan(_tree(tmp_path, _COLUMN_FOUND_BY_A_HEADER_MATCH)) == [
        "some_extract::extract"]


def test_the_source_mutator_needs_NO_exemption_because_it_publishes_nothing(
        real_scan):
    """The other half, and it is NOT the exemption this test used to assert.

    THIS TEST DEMANDED A CONTRADICTION, and demanding it is what made it red on
    `origin/main`. It required `policy_direction_pin_check::flip_source` to sit
    in `_NOT_PROSE` **and**, two lines later, to still be a finding of
    `scan(real)`. It is not a finding, so the exemption cannot be added:
    `exemption_audit` rejects an entry whose name the scan does not flag, in its
    own words *"exempted, but the scan does not flag it — the function is gone,
    renamed, or now consults polarity. Delete the entry."*

    MEASURED, by doing exactly what the old test asked and running the module:

        1 failed, 34 passed        origin/main
        3 failed, 32 passed        after adding the exemption it demanded
          + test_the_shipped_exemption_is_live_and_argued
          + test_the_gate_is_GREEN_on_the_tree_that_ships
          + this test, STILL red on its own second assertion

    Satisfying it takes the shipped gate red. So the register is right and the
    assertion was stale.

    WHY IT IS NOT A FINDING, which is the fact worth pinning and is asserted
    below rather than described. The rule is
    `_searches_prose(fn) and _writes_a_declared_value(fn)`, and `flip_source`
    fails BOTH halves:

        _names          searches_prose=True   writes_a_declared_value=False
        _literal_span   searches_prose=True   writes_a_declared_value=False
        flip_source     searches_prose=False  writes_a_declared_value=False

    `flip_source` performs a VERIFIED in-place substitution — it re-reads the
    literal at the recorded `(line, col)` and raises unless it equals the value
    already recorded — and returns rewritten source. It publishes no value read
    out of a document, so there is no extracted claim that a surrounding
    sentence could deny, and nothing for `_prose_polarity` to be consulted
    about. An exemption would be a reasoned argument for a question that is
    never asked.

    AND THE SCANNER WAS NOT NARROWED TO GET HERE. That is the failure mode this
    file is built around, so it is proved and not assumed: the two REJECTED
    NARROWING tests immediately above still fire, and the last assertion here
    re-plants `_literal_span`'s own shape — an `re` match plus a slice, in ONE
    function, publishing the slice — and requires it to still be caught.
    """
    name = "policy_direction_pin_check::flip_source"
    real = Path(__file__).resolve().parents[1].parent

    # 1. it is not a finding, and the reason is mechanical, not a name list
    tree = ast.parse((PROGRAMS / "policy_direction_pin_check.py").read_text())
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not G._writes_a_declared_value(fns["flip_source"]), (
        "flip_source now publishes a declared value — it is a prose extractor "
        "again and needs adjudicating, not this test relaxing")
    # The module's ONE scan of the real tree, via the fixture. It costs 55-62s
    # on a loaded host and `exemption_audit` takes the scan RESULT as its
    # argument, so re-deriving it per assertion would be three times the wall
    # clock for the same answer — and a single test drifting toward the
    # harness's 180s ceiling is the #1263 shape, a bound that is legal and
    # unreliable.
    live = real_scan
    assert name not in live

    # 2. so it must NOT be exempted; an exemption would be REJECTED, and the
    #    audit saying so is what stops `_NOT_PROSE` rotting into a waiver list
    assert name not in G._NOT_PROSE
    assert G.exemption_audit(live, real) == []
    original = G._NOT_PROSE
    stale = dict(original)
    stale[name] = "x" * (G._EXEMPT_REASON_MIN + 10)   # a long-enough reason
    try:
        G._NOT_PROSE = stale
        problems = G.exemption_audit(live, real)
    finally:
        G._NOT_PROSE = original
    # MATCHED ON THE DIAGNOSIS, NOT ON ONE PHRASING OF IT. This asserted the
    # literal `"does not flag it"`, which is main's exact wording — and #1572
    # improves that message for the refactor case, to "the scan no longer flags
    # it: the search moved out of this body into `_literal_span` ... Do NOT
    # delete the entry". Measured: #1602 alone 35 passed, #1572 alone 1 failed
    # / 37 passed (main's red, inherited), BOTH TOGETHER 1 failed / 37 passed —
    # and the one failure was THIS assertion, on a substring, while the property
    # it exists to check was intact and BETTER reported than before.
    #
    # `"exempted, but the scan"` is the stem both messages share and is still
    # specific to the LIVENESS diagnosis: it is the only branch of
    # `exemption_audit` that opens that way, so a message about a short reason
    # or an out-of-scope module does not satisfy it. Two tests must not disagree
    # about behaviour because one of them pinned the other's prose.
    assert any(name in p and "exempted, but the scan" in p
               for p in problems), (
        "an exemption for a non-finding was accepted; the liveness half of "
        f"exemption_audit has stopped working: {problems}")

    # 3. nor is it a debt: the baseline is for extractors that SHOULD consult
    #    polarity and do not, which this is not
    baseline = json.loads(
        (PROGRAMS / "prose_polarity_baseline.json").read_text())["known"]
    assert name not in baseline
    assert "policy_direction_pin_check::_names" not in baseline

    # 4. and none of the above was bought by narrowing the scanner: the shape
    #    `_literal_span` uses, in one function and publishing its slice, is
    #    still a finding
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        planted = Path(td)
        (planted / "programs").mkdir()
        (planted / "programs" / "some_extract.py").write_text(
            "import re\n"
            "def extract(line, col, rec):\n"
            "    m = re.match(r\"(?P<q>'|\\\")\", line[col:])\n"
            "    start = col + m.end()\n"
            "    end = line.find(m.group('q'), start)\n"
            "    rec['value'] = line[start:end]\n"
            "    return rec\n")
        assert G.scan(planted) == ["some_extract::extract"], (
            "the scanner no longer catches a match-located slice that IS "
            "published — this test's green would then be a narrowing")


def test_the_gate_is_GREEN_on_the_tree_that_ships():
    """The end of it. Read on the pristine base this exits 1 naming two
    functions of `policy_direction_pin_check`; a verdict nobody can reproduce
    green is the thing this repo is closing."""
    r = _pr.run(
        [sys.executable, str(PROGRAMS / "prose_polarity_consulted_check.py")],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


# ---------------------------------------------------------------------------
# vibe-ic#2010 item 6 — the two tech-LEF readers in pdk_via_patch_legalize are
# NOT PROSE. Both fences: the scan still FLAGS them (so the entries are live
# findings, not padding), and the audit accepts the exemption.
# ---------------------------------------------------------------------------
def test_the_via_legalizer_lef_readers_are_flagged_and_exempted_as_formal_grammar(tmp_path):
    root = _tree(tmp_path, "")
    src = PROGRAMS / "pdk_via_patch_legalize.py"
    (root / "programs" / "pdk_via_patch_legalize.py").write_text(src.read_text())
    names = {"pdk_via_patch_legalize::_routing_rules",
             "pdk_via_patch_legalize::_legalize_generate_rules"}
    flagged = set(G.scan(root))
    assert names <= flagged, flagged            # still findings by shape
    assert names <= set(G.exemptions_in_scope(root))
    assert G.exemption_audit(sorted(flagged), root) == []
    for n in names:
        assert len(G._NOT_PROSE[n]) >= G._EXEMPT_REASON_MIN
        assert "LEF" in G._NOT_PROSE[n]        # the argument names the grammar
