#!/usr/bin/env python3
"""emitter_population_pin_check.py — an emitter that PRINTS a population and a
test that PINS it are two statements of one fact, and they must move together.

THIS GATE BLOCKS (rc=1).

THE DEFECT, MEASURED 2026-08-21
===============================
A lane added a THIRD repair to a post-route block. It correctly moved the
emitter's own printed denominator from two to three:

    puts "SPEF_REPAIR_PARTIAL: $_prr_refused of 3 repairs refused"
    if {$_prr_refused >= 3} { ... }
    ... "($_prr_refused/3)" ...

and left the test asserting the OLD ratio. The population moved and the pin did
not, so the test failed for the right reason with the wrong message — a reader
meeting `2 != 3` learns nothing about the third repair.

It is the same shape as a stale census tripwire, and the remedy is the same one
this repository already applies there: a member arriving must force a human to
SAY THE NUMBER OUT LOUD.

TWO CHECKS, BECAUSE THE FACT IS STATED IN TWO PLACES
=====================================================
CHECK A — THE EMITTER AGAINST ITSELF. An emitted script that increments a
counter at K sites and then states a LITERAL denominator for that counter is
making two statements of one population. K is observable and so is the literal,
so they are compared. This is the half that catches the lane on the way in: add
a fourth repair, and `of 3` is wrong before any test runs.

    denominators recognised:  $X >= D    $X == D    $X/D    $X of D
    D < 2 is ignored: `$X > 0` is "any at all", not a population.

CHECK B — THE TEST AGAINST THE EMITTER. A test that names exactly one program
and quotes a population phrase (`... of N <tail>`) whose `<tail>` the emitter
also states must quote one of the emitter's OWN values for that tail. A pin
naming a number the emitter cannot produce is stale by construction.

WHAT IS READ: THE EMITTED SCRIPT, NOT THE FILE THAT PRINTS IT
=============================================================
Both checks read only the strings a program EMITS — never its docstrings, and
never its `#` comments, which do not reach the AST at all. Measured on this tree
before that exclusion existed for the phrase half: 3 findings, ALL THREE false,
and all three the same shape — a narrative sentence in a module or test docstring
("PR #862 is the subtler half. Its author reported \"4 of 4 behavioural\"")
matched against a different narrative sentence elsewhere. Prose recounting what
a number USED TO BE is not a pin, and a guard that reddens on the history a file
records would make recording history expensive. After the exclusion: 0 findings
over the same corpus.

CHECK A read the RAW FILE and so had none of that protection, which was a defect
and is fixed here: a docstring saying a repair is REMOVED and that there is no
`incr _n` left for it contributed a phantom MEMBER, and a sentence recounting a
retired `$_n >= 3` threshold contributed a phantom DENOMINATOR — so a truthful
emitter was refused for disagreeing with a number nobody had stated.

AND THE SCRIPT ITSELF IS ASKED FOR ITS POLARITY (vibe-ic#712)
=============================================================
Removing prose about the code does not remove prose: an emitted script carries
Tcl comments and `puts` messages, and English there denies as readily as it
declares — `# the retry path does not incr _n`, `# $_n >= 4 is no longer the
threshold`. A reader that matches the first and not the `not` in it counts a
DENIAL as a member. So every increment site and every literal denominator is
asked, through the ONE vocabulary in `_prose_polarity`, whether the statement it
sits in denies it; what that refuses is PRINTED, never quietly dropped.

`phrases` is not asked the same question, and the difference is structural, not
an oversight: it reads `of <N> <tail>`, a statement of how big a set IS. A
message that denies something else in the same breath ("no repair applied, 0 of 3
repairs refused") still states that population correctly, and suppressing the pin
comparison there would disarm CHECK B — the half that catches the measured defect
— in the silent direction.

WHAT WAS TRIED AND REJECTED — matching every `assert "<literal>" in <text>` in a
test against the verbatim source of the program it names. Measured over 1619
single-program test files: 6062 pins examined, 2345 "unsatisfied". Almost none
were defects. Emitters TEMPLATE their output (`f"{n} of {m} failures"`), so the
finished string a test asserts on is not, and must not be, a literal anywhere in
the emitter. A predicate that fires on 2345 legitimate pins is not a guard.

Narrowing to POPULATION phrases with a HARD-CODED denominator is what makes the
question answerable: those are the only ones where the emitter states the number
itself, and therefore the only ones where a test can disagree with it.

THE REACH IS PRINTED, ALWAYS
============================
This guard's population is small, and a verdict that does not say so would
overstate itself. Every run prints the counters and the pins it examined. A PASS
over zero of both is reported as VACUOUS, never as a pass.

EXIT CODES
==========
    0  every emitted population agrees with its own site count, and every test
       pin names a value its emitter states
    1  REFUSED — the emitter line, the test line and the two values are printed
    2  VACUOUS — no counter with a literal denominator and no paired pin was
       found, so nothing was compared (`_vacuous_exit`'s tier, announced)
    3  the command line was rejected (`_gate_usage_exit`)

USAGE
-----
    emitter_population_pin_check.py [--programs DIR] [--tests DIR] [--json OUT]

chip-AGNOSTIC: Python and Tcl text structure. No design, PDK, vendor or SKU.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import _atomic_artefact as _atomic
import _gate_usage_exit as _usage
import _vacuous_exit as _vac
from _prose_polarity import is_denied, sentence_scope

TOOL = "emitter_population_pin_check"

#: A population phrase in emitted prose: "<n> of <D> <tail>". The tail is one or
#: two identifier-ish words, which is what makes two statements of the SAME
#: population recognisable as such without a hand-written pairing list.
PHRASE = re.compile(
    r"\bof\s+(\d{1,5})\s+"
    r"([A-Za-z_][A-Za-z_()\[\]/-]*(?:\s+[A-Za-z_][A-Za-z_()\[\]/-]*)?)")

#: A Tcl counter increment. The emitted scripts in this tree are Tcl; the shape
#: is `incr <name>` and every site is one member of the population.
INCR = re.compile(r"\bincr\s+([A-Za-z_][A-Za-z0-9_]*)\b")

#: Denominators a counter may carry. `>` is absent on purpose: `$X > 0` is a
#: presence test, and `$X > 3` would mean "more than all of them".
_DEN_TEMPLATES = (
    ("comparison", r"\$%s\s*(?:>=|==)\s*(\d+)"),
    ("ratio", r"\$%s\s*/\s*(\d+)"),
    ("prose", r"\$%s\s+of\s+(\d+)"),
)

#: Below this a literal is a presence test, not a population.
MIN_POPULATION = 2

#: What ends a RECORD in the text `counters` reads. The subject is an emitted
#: SCRIPT, and a script is line-structured: a command and the line above it are
#: unrelated records, and a `#` comment ends at its own newline. `_prose_polarity`
#: owns the reach and takes this declaration, rather than this file growing a
#: private copy of "where does a statement end" -- which is the divergence that
#: module exists to end.
#:
#: WHICH WAY TO ERR, DECIDED BY WHICH FAILURE IS SILENT. Without a record break
#: the reach runs 240 characters through unrelated commands, so one
#: `puts "no repair applied"` retracts every denominator printed near it and this
#: BLOCKING gate quietly stops comparing anything. With it, a denial wrapped
#: across two emitted lines is missed and a phantom member is counted -- which is
#: a REFUSAL a reader sees, and answers. Loud beats silent, so the break is
#: declared. What polarity does refuse is printed on every run for the same
#: reason.
_RECORD_BREAKS = ("\n",)


def _emitted_strings(text: str) -> List[Tuple[int, int, str]]:
    """``[(lineno, col, value)]`` for every string in `text` that is EMITTED,
    in source order.

    PROSE ABOUT THE CODE IS NOT THE SCRIPT, AND THIS IS WHERE THAT IS DECIDED.
    A string that is an expression STATEMENT is never emitted: it is the module,
    class or function docstring, or a block comment written as a string. A `#`
    comment never reaches the AST at all, so it is gone by construction. Both
    are prose recounting what the code does, or what a number USED TO BE, and
    neither is a statement of the population the emitted script carries.

    An f-string docstring's PARTS are skipped with it. `ast.walk` reaches each
    inner `Constant` on its own, so skipping the `JoinedStr` node alone would let
    the same prose back in through the other door.

    Source order, not `ast.walk` order, because the caller joins these into one
    text and a script read out of order is not the script.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    skip: Set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Expr) and isinstance(n.value,
                                                  (ast.Constant, ast.JoinedStr)):
            for part in ast.walk(n.value):
                skip.add(id(part))
    out: List[Tuple[int, int, str]] = []
    for n in ast.walk(tree):
        if id(n) in skip:
            continue
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append((n.lineno, n.col_offset, n.value))
    out.sort()
    return out


def emitted_script(text: str) -> str:
    """The emitted strings of `text` as ONE flat text, one record per line.

    STILL FLAT, for the reason `counters` always gave: the emitted script is
    assembled from many adjacent string literals, and a block-aware reader would
    have to re-implement that assembly to answer a question the flat text already
    answers. What changed is WHICH text -- the script, not the file that prints
    it.

    JOINED WITH A NEWLINE rather than concatenated, so two literals that are not
    adjacent in the real script (anything assembled through a call between them)
    cannot fuse into one statement and lend each other a polarity. Nothing that
    was matchable stops being matchable: in the raw file those same two literals
    were already separated by a quote, a newline and the next line's indentation,
    so no pattern here could span the seam then either.
    """
    return "\n".join(v for _, _, v in _emitted_strings(text))


def phrases(text: str) -> Dict[str, Set[Tuple[str, int]]]:
    """``{tail: {(value, lineno)}}`` -- every population phrase the emitter CAN
    print.

    NOT ASKED FOR POLARITY, and the asymmetry with `pins` below is measured, not
    stylistic. This set is the answer to "what values does this emitter state?",
    and a value missing from it makes a CORRECT pin look stale. An emitter that
    prints `puts "no repair applied; 0 of 3 repairs refused"` does state
    `of 3 repairs refused`; suppressing it because the same message also says
    "no" would refuse a correct test -- the same false refusal `pins` exists to
    stop, pointed the other way.

    AND THE POLARITY GATE CLEARS THIS FUNCTION FOR A MECHANICAL REASON, NOT FOR
    THAT ARGUMENT. Recorded here because the two are easily confused and the
    argument is the load-bearing one. `prose_polarity_consulted_check` asks
    `_searches_prose and _writes_a_declared_value`; the second half returns
    False here for two reasons that are both about SPELLING:

      * `m` is bound by a `for` TARGET, and `_match_derived_names` walks only
        `ast.Assign`, so the match never enters `derived` and the predicate
        returns False before it looks at any write at all; and
      * the write is `out.setdefault(KEY, set()).add(VALUE)`, and the predicate
        reads `setdefault`'s DEFAULT (`args[1:]`) but neither its key nor the
        value pushed into the container it returns.

    MEASURED over this tree, by widening each in turn: the first alone reveals
    35 further polarity-blind extractors, the second alone 35, and both together
    80 (224 -> 304 findings). Only with BOTH closed does the scan reach this
    function. So the clearance is an artefact of how the write is spelled, and
    a reader must not take it as the gate having agreed with the paragraph
    above.

    IF THAT PREDICATE IS EVER WIDENED, this function will be flagged and NEITHER
    of the gate's two registers fits it. `_NOT_PROSE` is for input in a formal
    grammar with no negation form, and this is real English. The baseline is a
    debt register of extractors that SHOULD consult polarity and do not, and
    this one measurably should not. The honest resolution at that point is a
    third answer -- "reads prose, and correctly does not honour a denial" -- not
    a stretched entry in either.
    """
    out: Dict[str, Set[Tuple[str, int]]] = {}
    for lineno, _, value in _emitted_strings(text):
        for m in PHRASE.finditer(value):
            out.setdefault(m.group(2).strip(), set()).add((m.group(1), lineno))
    return out


def pins(text: str) -> Tuple[Dict[str, Set[Tuple[str, int]]],
                             List[Tuple[str, int, str]]]:
    """``({tail: {(value, lineno)}}, [(phrase, lineno, denial)])`` -- what a test
    PINS, and what it turned out to be DENYING instead.

    A pin is an ASSERTION that the emitter states the value. This is not one:

        assert "of 3 repairs refused" not in script()

    It asserts the opposite -- that the emitter no longer says it -- and it is
    how a test correctly records that a population MOVED. Read as a pin it is
    compared against an emitter that now says 4, and the guard refuses a correct
    test for "the population moved and the pin did not" when the test is
    asserting exactly that the population moved. MEASURED against a
    self-consistent 4-site emitter: rc=1, one finding, both files correct. Same
    shape as #706, on the pin side.

    THE DENIAL IS IN THE CODE, NOT IN THE STRING. `not in` is spelled outside
    the literal, so `is_denied` on the literal's own value cannot see it. The
    scope is taken over the SOURCE STATEMENT the literal begins in, anchored at
    the start of its line and bounded by `sentence_scope` with the same record
    break `counters` declares -- a Python statement is line-structured the way
    an emitted script is. Anchoring on the LINE rather than on the literal's
    column is deliberate: `col_offset` is measured in UTF-8 bytes, so a line
    carrying a multi-byte character ahead of the literal would push the anchor
    past the end of its own statement.

    WHAT IT REFUSES IS RETURNED, not dropped -- a pin the guard declined to
    compare is a pin it did not check, and this file prints its reach.
    """
    kept: Dict[str, Set[Tuple[str, int]]] = {}
    refused: List[Tuple[str, int, str]] = []
    starts, acc = [], 0
    for raw in text.splitlines(keepends=True):
        starts.append(acc)
        acc += len(raw)
    for lineno, _, value in _emitted_strings(text):
        anchor = starts[lineno - 1] if 0 < lineno <= len(starts) else 0
        lo, hi = sentence_scope(text, anchor, min(anchor + 1, len(text)),
                                extra_breaks=_RECORD_BREAKS)
        word = is_denied(text[lo:hi])
        for m in PHRASE.finditer(value):
            tail = m.group(2).strip()
            if word:
                refused.append((f"of {m.group(1)} {tail}", lineno, word))
                continue
            kept.setdefault(tail, set()).add((m.group(1), lineno))
    return kept, refused


def counters(text: str) -> Tuple[List[Tuple[str, int, List[Tuple[str, int]]]],
                                 List[Tuple[str, str, str]]]:
    """``([(name, increment_sites, [(kind, D)])], [(what, matched, denial)])``.

    THE SUBJECT IS THE EMITTED SCRIPT, not the file that prints it -- see
    `emitted_script`. Read flat, for the reason this function always gave.

    POLARITY (vibe-ic#712). The script is read for two claims -- a MEMBERSHIP
    (`incr X`) and a THRESHOLD (`$X >= D`) -- and a script states both in English
    as readily as it states them in Tcl:

        # the retry path does not incr _n; it re-issues the command
        # $_n >= 4 is no longer the threshold, the fourth repair was removed
        puts "no repair could be applied"

    A reader that matches the first line and not the word `not` in it counts a
    DENIAL as a member; the population it reports is then confidently wrong, and
    it refuses a truthful emitter for disagreeing with a number nobody stated.
    That is #706 (`pdk_target`) in the counting direction. So every match is
    asked, through the ONE vocabulary in `_prose_polarity`, whether the statement
    it sits in denies it.

    WHAT POLARITY REFUSED IS RETURNED, NOT DROPPED. This guard prints its reach
    on every run; a reach that shrank because a denial was believed is part of
    the reach, and a guard that quietly counts less than it read is the failure
    this file is built to catch one level up.
    """
    src = emitted_script(text)

    def denial(m: "re.Match[str]") -> Optional[str]:
        """The word by which the emitted statement around `m` DENIES it."""
        lo, hi = sentence_scope(src, m.start(), m.end(),
                                extra_breaks=_RECORD_BREAKS)
        return is_denied(src[lo:hi])

    refused: List[Tuple[str, str, str]] = []
    names: Dict[str, int] = {}
    for m in INCR.finditer(src):
        word = denial(m)
        if word:
            refused.append(("increment", m.group(0), word))
            continue
        names[m.group(1)] = names.get(m.group(1), 0) + 1
    rows = []
    for name, sites in sorted(names.items()):
        dens: List[Tuple[str, int]] = []
        for kind, tmpl in _DEN_TEMPLATES:
            for m in re.finditer(tmpl % re.escape(name), src):
                value = int(m.group(1))
                if value < MIN_POPULATION:
                    continue
                word = denial(m)
                if word:
                    refused.append((f"{kind} denominator", m.group(0), word))
                    continue
                if (kind, value) not in dens:
                    dens.append((kind, value))
        if dens:
            rows.append((name, sites, dens))
    return rows, refused


def named_program(text: str, stems: Set[str]) -> Optional[str]:
    """The single program a test file names, or None if it names 0 or >1.

    Taken from imports and from ``"<stem>.py"`` path literals — the two ways a
    test in this tree reaches a program. A test naming several programs is left
    alone: which emitter a phrase belongs to would be a guess.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    found: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                root = a.name.split(".")[-1]
                if root in stems:
                    found.add(root)
        elif isinstance(n, ast.ImportFrom) and n.module:
            root = n.module.split(".")[-1]
            if root in stems:
                found.add(root)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) \
                and n.value.endswith(".py"):
            root = n.value[:-3].split("/")[-1]
            if root in stems:
                found.add(root)
    return next(iter(found)) if len(found) == 1 else None


def main(argv: Optional[List[str]] = None) -> int:
    here = Path(__file__).resolve().parent
    ap = _usage.GateArgumentParser(
        prog=TOOL,
        description="refuse an emitted population and its test pin that "
                    "disagree")
    ap.add_argument("--programs", type=Path, default=here)
    ap.add_argument("--tests", type=Path, default=here / "tests")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    if not args.programs.is_dir():
        return _usage.usage_error(TOOL, f"--programs {args.programs} is not a "
                                        f"directory")
    if not args.tests.is_dir():
        return _usage.usage_error(TOOL, f"--tests {args.tests} is not a "
                                        f"directory")

    sources = {p.stem: p for p in sorted(args.programs.glob("*.py"))}
    findings: List[dict] = []
    denied: List[dict] = []
    counters_examined = 0
    pins_examined = 0

    # ── CHECK A — the emitter against itself ────────────────────────────────
    text_cache: Dict[str, str] = {}

    def body(stem: str) -> str:
        if stem not in text_cache:
            text_cache[stem] = sources[stem].read_text(errors="replace")
        return text_cache[stem]

    for stem in sources:
        src = body(stem)
        if "incr " not in src:
            continue
        rows, refused = counters(src)
        for what, matched, word in refused:
            denied.append({"where": sources[stem].name, "what": what,
                           "matched": matched, "denial": word})
        for name, sites, dens in rows:
            for kind, value in dens:
                counters_examined += 1
                if value != sites:
                    findings.append({
                        "check": "emitter-self",
                        "program": sources[stem].name, "counter": name,
                        "increment_sites": sites,
                        "denominator": value, "denominator_kind": kind,
                    })

    # ── CHECK B — the test pin against the emitter ──────────────────────────
    phrase_cache: Dict[str, Dict[str, Set[Tuple[str, int]]]] = {}

    def emitter_phrases(stem: str):
        if stem not in phrase_cache:
            phrase_cache[stem] = phrases(body(stem))
        return phrase_cache[stem]

    for test in sorted(args.tests.rglob("test_*.py")):
        text = test.read_text(errors="replace")
        stem = named_program(text, set(sources))
        if stem is None:
            continue
        em = emitter_phrases(stem)
        if not em:
            continue
        pinned, pin_refused = pins(text)
        for phrase, lineno, word in pin_refused:
            denied.append({"where": f"{test}:{lineno}", "what": "test pin",
                           "matched": phrase, "denial": word})
        for tail, values in pinned.items():
            if tail not in em:
                continue
            emitted = {v for v, _ in em[tail]}
            emitted_lines = sorted({ln for _, ln in em[tail]})
            for value, lineno in sorted(values):
                pins_examined += 1
                if value not in emitted:
                    findings.append({
                        "check": "pin-against-emitter",
                        "test": str(test), "test_line": lineno,
                        "program": sources[stem].name,
                        "program_lines": emitted_lines,
                        "phrase": tail,
                        "pinned": value, "emitted": sorted(emitted),
                    })

    head = (f"{counters_examined} emitted counter denominator(s) and "
            f"{pins_examined} test pin(s) examined; {len(denied)} match(es) "
            f"not counted because the statement DENIES them")
    report = {"tool": TOOL, "counters_examined": counters_examined,
              "pins_examined": pins_examined, "denied_by_polarity": denied,
              "findings": findings}
    if args.json:
        _atomic.write_json(args.json, report)

    for d in denied:
        print(f"  [POLARITY] {d['where']}: {d['what']} `{d['matched']}` sits "
              f"in a statement that DENIES it (\"{d['denial']}\") and is NOT "
              f"counted")

    if counters_examined == 0 and pins_examined == 0:
        _vac.announce_vacuous(TOOL, "no-population-stated-twice")
        print(f"[VACUOUS] {TOOL}: no emitted population is stated twice here, "
              f"so nothing was compared; this is NOT a pass")
        return _vac.RC_VACUOUS

    if findings:
        for f in findings:
            if f["check"] == "emitter-self":
                print(f"  [POPULATION] {f['program']}: counter ${f['counter']} "
                      f"is incremented at {f['increment_sites']} site(s) but "
                      f"its {f['denominator_kind']} denominator says "
                      f"{f['denominator']} — the emitter states one population "
                      f"twice and disagrees with itself")
            else:
                print(f"  [POPULATION] {f['test']}:{f['test_line']} pins "
                      f"\"of {f['pinned']} {f['phrase']}\", but "
                      f"{f['program']} (line(s) "
                      f"{', '.join(str(x) for x in f['program_lines'])}) states "
                      f"{', '.join(f['emitted'])} — the population moved and "
                      f"the pin did not")
        print(f"[FAIL] {TOOL}: {len(findings)} population(s) stated twice and "
              f"disagreeing [{head}]")
        return _vac.RC_FAIL

    print(f"[PASS] {TOOL}: every population stated twice agrees [{head}]")
    return _vac.RC_PASS


if __name__ == "__main__":
    sys.exit(main())
