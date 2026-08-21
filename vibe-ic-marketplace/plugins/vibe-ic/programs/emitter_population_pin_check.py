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

WHY DOCSTRINGS ARE EXCLUDED ON BOTH SIDES, AND WHAT IT COSTS
=============================================================
Measured on this tree before the exclusion: 3 findings, ALL THREE false, and all
three the same shape — a narrative sentence in a module or test docstring
("PR #862 is the subtler half. Its author reported \"4 of 4 behavioural\"")
matched against a different narrative sentence elsewhere. Prose recounting what
a number USED TO BE is not a pin, and a guard that reddens on the history a file
records would make recording history expensive. After the exclusion: 0 findings
over the same corpus.

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
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import _gate_usage_exit as _usage
import _vacuous_exit as _vac

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


def _docstring_nodes(tree: ast.AST) -> Set[int]:
    """``id()`` of every string node that is a docstring or a bare block string.

    A string that is an expression STATEMENT is never emitted: it is the module,
    class or function docstring, or a block comment written as a string. Both
    are prose about the code, and prose recounting an old number is not a pin.
    """
    return {id(n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Expr)
            and isinstance(n.value, (ast.Constant, ast.JoinedStr))}


def phrases(text: str) -> Dict[str, Set[Tuple[str, int]]]:
    """``{tail: {(value, lineno)}}`` from every EMITTED string in `text`."""
    out: Dict[str, Set[Tuple[str, int]]] = {}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    skip = _docstring_nodes(tree)

    def take(value: str, lineno: int) -> None:
        for m in PHRASE.finditer(value):
            out.setdefault(m.group(2).strip(), set()).add((m.group(1), lineno))

    for n in ast.walk(tree):
        if id(n) in skip:
            continue
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            take(n.value, n.lineno)
        elif isinstance(n, ast.JoinedStr):
            for v in n.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    take(v.value, n.lineno)
    return out


def counters(text: str) -> List[Tuple[str, int, List[Tuple[str, int]]]]:
    """``[(name, increment_sites, [(kind, D)])]`` for counters with a literal D.

    Read over the whole source rather than per emitted block: the emitted script
    is assembled from many adjacent string literals, and a block-aware reader
    would have to re-implement that assembly to answer a question the flat text
    already answers.
    """
    names: Dict[str, int] = {}
    for m in INCR.finditer(text):
        names[m.group(1)] = names.get(m.group(1), 0) + 1
    rows = []
    for name, sites in sorted(names.items()):
        dens: List[Tuple[str, int]] = []
        for kind, tmpl in _DEN_TEMPLATES:
            for m in re.finditer(tmpl % re.escape(name), text):
                value = int(m.group(1))
                if value >= MIN_POPULATION and (kind, value) not in dens:
                    dens.append((kind, value))
        if dens:
            rows.append((name, sites, dens))
    return rows


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
        for name, sites, dens in counters(src):
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
        for tail, values in phrases(text).items():
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
            f"{pins_examined} test pin(s) examined")
    report = {"tool": TOOL, "counters_examined": counters_examined,
              "pins_examined": pins_examined, "findings": findings}
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n",
                             encoding="utf-8")

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
