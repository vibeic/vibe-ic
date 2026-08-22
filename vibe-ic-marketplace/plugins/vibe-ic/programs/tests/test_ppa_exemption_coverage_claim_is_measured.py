#!/usr/bin/env python3
"""An exemption that states a COVERAGE NUMBER must state the one the gate reports.

WHY THIS FILE EXISTS, and it is a defect this lane introduced itself.

The PPA record rows were re-aimed at the in-tree campaigns and their
`uncheckable_until` declarations were written to say what each had bought:
"PASSES today over 20 pairs", "over 60 pairs". True for the form the rows had
then — one baseline compared against each other contract.

A later change made `ppa_problem_integrity_check --corpus` GROUP contracts by
`problem` and compare every pair inside the group. That is the stronger
question, the gate was correctly rewired to it, and the COMMENT above the rows
was updated to record 210 and 1830. The `uncheckable_until` DECLARATIONS were
not. MEASURED before this file was written:

    PPA arms solved one problem (cross-layer)   claimed 20 pairs, compared 210
    PPA arms solved one problem (end-to-end)    claimed 60 pairs, compared 1830

The comment is read by whoever opens the file. The DECLARATION is what reaches
the roll-up, beside the row, where a reader decides what a NOT CHECKED or a PASS
was worth. A declaration understating its own coverage by 30x is the same shape
as a stale ledger row: indistinguishable from a live one, and it is the one that
gets believed.

WHAT THIS ASSERTS. For every PPA gate wired over a `--corpus` whose exemption
states "over N <units>", run the gate and require the count it prints to be N.
Nothing here decides whether the number should be large; only that the sentence
and the program agree.

WHAT KEEPS IT FROM PASSING VACUOUSLY. A guard that finds no rows would pass in
silence. So the population is asserted first, in its own test: if the parse
finds no number-stating PPA corpus row at all, that is a FAILURE — the rows
exist, so a parser that stopped matching them has gone dark, not gone clean.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
PROGRAMS = REPO / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
WIRING = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"

#: The units a coverage claim can be stated in.
_UNITS = ("pair", "record", "contract", "set", "candidate")
#: A claim opens with "over N" and the unit noun may sit behind adjectives:
#: "over 1830 pairs", but also "over 21 adjudicated candidate sets".
_CLAIM_OPEN = re.compile(r"\bover\s+(\d+)\s+((?:[a-z]+\s*){0,4})")


def _claim(text):
    """(N, unit) for a coverage claim, or None.

    THE UNIT IS THE LAST ONE IN THE TAIL, NOT THE FIRST WORD AFTER THE NUMBER.
    An earlier version of this file took the word immediately following, which
    matched "over 1830 pairs" and silently did not match "over 21 adjudicated
    candidate sets" -- so the guard skipped one of the five numbered rows while
    reading as though it covered them all. That is the defect this whole file
    is about, committed by the file itself.
    """
    m = _CLAIM_OPEN.search(text)
    if not m:
        return None
    unit = None
    for w in m.group(2).split():
        w = w[:-1] if w.endswith("s") else w
        if w in _UNITS:
            unit = w
    return (int(m.group(1)), unit) if unit else None
#: what a corpus gate prints: "21 contract(s), 0 refused" / "210 pair(s) compared"
_REPORTED = re.compile(r"\b(\d+)\s+(pair|record|contract|set)\(s\)")


def _logical_lines(text: str):
    return re.sub(r"\\\n\s*", " ", text).splitlines()


def _rows():
    """(label, claimed_n, unit, argv) for every PPA --corpus row stating a number."""
    lines = _logical_lines(_wiring_text())
    out = []
    for i, line in enumerate(lines):
        if not line.startswith(("run ", "run_tolerating_uncheckable ")):
            continue
        if "$PG/ppa_" not in line or "--corpus" not in line:
            continue
        label = re.search(r'"([^"]*)"', line)
        j = i - 1
        while j >= 0 and (lines[j].lstrip().startswith("#") or not lines[j].strip()):
            j -= 1
        if j < 0 or not lines[j].startswith("uncheckable_until"):
            continue
        claim = _claim(lines[j])
        if not claim:
            continue
        argv, want_corpus = [], False
        for tok in line.split():
            t = tok.strip('"')
            if t.startswith("$PG/"):
                argv.append(str(PROGRAMS / t[len("$PG/"):]))
            elif t == "--corpus":
                argv.append(t); want_corpus = True
            elif want_corpus:
                argv.append(str(REPO / t.replace("$ROOT/", ""))); want_corpus = False
        if len(argv) >= 3:
            out.append((label.group(1) if label else "?",
                        claim[0], claim[1], argv, lines[j]))
    return out


def _numbered_exemptions():
    """Every exemption that states a number at all, however it is worded.

    Deliberately LOOSER than `_claim`: this is the population the guard must
    cover, and it is measured from the file rather than from the guard's own
    parser, so the two can be compared.
    """
    lines = _logical_lines(_wiring_text())
    out = []
    for i, l in enumerate(lines):
        if not l.startswith("uncheckable_until"):
            continue
        if not re.search(r"\bover\s+\d+\s+[a-z]", l):
            continue
        j = i + 1
        while j < len(lines) and (lines[j].lstrip().startswith("#")
                                  or not lines[j].strip()):
            j += 1
        nxt = lines[j] if j < len(lines) else ""
        lab = re.search(r'"([^"]*)"', nxt)
        out.append(lab.group(1) if lab else nxt[:60])
    return out


def _wiring_text() -> str:
    """The wiring file, or an explicit SKIP naming what could not be read.

    `programs/tests/` SHIPS WITH THE PLUGIN and `tools/ci/` does not. Run the
    plugin's suite anywhere but a full checkout of this repository and
    `WIRING.read_text()` raises FileNotFoundError — a hard ERROR, which is this
    guard becoming blocking-because-unreadable. MEASURED by moving the file
    aside: every test in this file errored on the traceback below, none of them
    on anything about exemptions.

    "I could not look" is not a finding and it is not a pass. It is a skip that
    NAMES the thing it could not read. The same rule this file already applies
    to an absent corpus, applied to its own subject — it was left out here on
    the first pass, which is why it is written down rather than quietly added.
    """
    if not WIRING.is_file():
        pytest.skip(f"{WIRING} is not in this checkout — the plugin's tests "
                    "ship without tools/ci/, so this guard has no subject to "
                    "read here. NOT a pass and NOT a finding.")
    return WIRING.read_text(encoding="utf-8")


def _corpus_of(argv):
    """The directory a row was aimed at, or None."""
    if "--corpus" not in argv:
        return None
    i = argv.index("--corpus")
    return Path(argv[i + 1]) if i + 1 < len(argv) else None


def _split_readable(rows):
    """(rows whose corpus is there, [named paths that are not]).

    WHY THIS EXISTS. Every assertion below runs a gate and reads a count out of
    its output. A gate whose corpus is ABSENT exits 2 having looked at nothing
    and prints no count -- and the first version of this file reported that as
    "claims N and printed no count", i.e. as a false declaration. That is "I
    could not look" laundered into a finding about the tree, inside a file whose
    whole subject is that substitution.

    `ppa-crosslayer/` and `ppa-e2e/` are tracked, so a complete checkout always
    has them; a sparse or partial one need not, and this repository already
    carries a gate about exactly that state. So the two are kept apart here: an
    unreadable corpus is NAMED and disclosed, never counted as a lie.
    """
    ok, missing = [], []
    for row in rows:
        c = _corpus_of(row[3])
        (ok if (c and c.is_dir()) else missing).append(
            row if (c and c.is_dir()) else f"{row[0]}: {c}")
    return ok, [m for m in missing if isinstance(m, str)]


def test_the_parser_still_finds_the_rows_it_is_about():
    """THE DENOMINATOR, asserted before anything is compared.

    The other test iterates a list. A list that became empty — the wiring
    reformatted, a flag renamed, the claim reworded — would let it pass while
    checking nothing.
    """
    rows = _rows()
    assert rows, (
        f"no PPA --corpus row with a numbered exemption was found in {WIRING}; "
        "the rows exist, so this parser has gone dark")


def test_every_stated_coverage_number_is_the_one_the_gate_reports():
    """RED BEFORE THE FIX: cross-layer claimed 20 and compared 210; end-to-end
    claimed 60 and compared 1830.

    THE UNIT NOUN IS NOT THE ASSERTION, and an earlier draft of this file made
    it one. It required the exemption's noun to equal the gate's, and reported
    `PPA measurement contract` as wrong because the declaration says "21
    contracts" while the gate prints "21 published contract record(s) selected".
    The NUMBER agreed; only the word differed. That was the guard being wrong,
    not the wiring, and the construction was fixed rather than the bound
    loosened: the claim is now matched against the counts the gate reports ON
    ITS OWN ROLL-UP LINE, preferring the claimed unit when the gate uses that
    noun and falling back to any count on that line when it does not.

    It is still not vacuous. The roll-up line is the gate's own statement of the
    population it examined, so a claim of 20 against a line reporting 21 and 210
    is red, which is exactly the defect this file was written for.
    """
    rows, missing = _split_readable(_rows())
    if not rows:
        pytest.skip("no PPA corpus is readable in this checkout, so nothing "
                    "could be measured — NOT a pass: " + "; ".join(missing))
    wrong, noted = [], list(f"corpus not in this checkout, not checked: {m}"
                            for m in missing)
    for label, claimed, unit, argv, _ex in rows:
        proc = subprocess.run([sys.executable] + argv, capture_output=True,
                              text=True, timeout=600)
        # The roll-up line names the corpus it walked; per-record chatter does
        # not. Anchoring here keeps an incidental number in a finding from
        # standing in for the population.
        rollup = [ln for ln in (proc.stdout + proc.stderr).splitlines()
                  if "--corpus" in ln]
        if not rollup:
            wrong.append(f"{label}: printed no --corpus roll-up line, so this "
                         f"guard could not read a population at all")
            continue
        pairs = [(int(n), u) for ln in rollup for n, u in _REPORTED.findall(ln)]
        if not pairs:
            wrong.append(f"{label}: roll-up line carries no count this guard "
                         f"could read: {rollup[0][:120]}")
            continue
        same_unit = [n for n, u in pairs if u == unit]
        if same_unit:
            if claimed not in same_unit:
                wrong.append(f"{label}: exemption claims {claimed} {unit}(s), "
                             f"gate reports {sorted(set(same_unit))}")
        else:
            allc = [n for n, _ in pairs]
            if claimed not in allc:
                wrong.append(f"{label}: exemption claims {claimed} {unit}(s), "
                             f"gate roll-up reports {sorted(set(allc))}")
            else:
                noted.append(f"{label}: number {claimed} agrees; gate calls the "
                             f"unit {sorted({u for _, u in pairs})} not {unit!r}")
    for n in noted:
        print("[NOTE] " + n)
    assert wrong == [], (
        "an exemption states a coverage its gate does not:\n  "
        + "\n  ".join(wrong))


def test_the_guard_covers_every_exemption_that_states_a_number():
    """THE GUARD'S OWN BLIND SPOT, closed the same way the gates' were.

    RED BEFORE THIS TEST: the claim parser took the word immediately after the
    number, so "over 21 adjudicated candidate sets" did not match and
    `PPA promotion feasibility` was skipped in silence. Four of five rows were
    checked by a file that reads as though it checks all of them.

    A numbered claim this guard cannot verify is a FAILURE, not a skip. If a
    coverage figure is worth stating in a declaration a reader will trust, it is
    worth being machine-checkable; and a guard that quietly narrows its own
    population is the exact shape every gate in this family exists to refuse.
    """
    declared = set(_numbered_exemptions())
    covered = {label for label, _, _, _, _ in _rows()}
    missed = sorted(declared - covered)
    assert not missed, (
        "an exemption states a coverage number this guard does not verify:\n  "
        + "\n  ".join(missed)
        + "\n(either make the claim parseable, or make the row runnable here — "
          "silently skipping it is what this file exists to prevent)")
    assert declared, "no numbered exemption found at all; the parser has gone dark"


def test_a_declaration_that_says_it_passes_is_on_a_gate_that_passes():
    """The other claim these declarations make, and it is not a number.

    Four of the five say "PASSES today". That is a statement about the gate's
    CURRENT verdict, sitting in the line a reader meets beside the row, and it
    drifts exactly the way the figures did — a gate that starts failing does not
    rewrite the sentence that says it passes.

    MEASURED when this was written: all four "PASSES today" rows exit 0, and the
    three rows that do not pass (two head-to-head at rc 1, feasibility at rc 2)
    make no such claim. So this guard protects a property that currently holds
    rather than reporting a defect — which is why it is written now, while the
    agreement is cheap to pin, instead of after it breaks.

    ONE DIRECTION ONLY, deliberately. A declaration describing rc 2 whose gate
    has started PASSING is PROGRESS, not a defect, and failing on it would
    punish a gate for improving. That case is disclosed as a NOTE so the stale
    sentence is still visible to a reader.
    """
    rows, missing = _split_readable(_rows())
    if not rows:
        pytest.skip("no PPA corpus is readable in this checkout, so no verdict "
                    "could be measured — NOT a pass: " + "; ".join(missing))
    wrong, noted = [], list(f"corpus not in this checkout, not checked: {m}"
                            for m in missing)
    for label, _claimed, _unit, argv, exemption in rows:
        rc = subprocess.run([sys.executable] + argv, capture_output=True,
                            text=True, timeout=600).returncode
        says_pass = "PASSES today" in exemption
        if says_pass and rc != 0:
            wrong.append(f"{label}: declaration says 'PASSES today', gate exits {rc}")
        elif not says_pass and rc == 0:
            noted.append(f"{label}: gate now exits 0 and the declaration does not "
                         f"say so — progress, but the sentence is stale")
    for n in noted:
        print("[NOTE] " + n)
    assert wrong == [], (
        "a declaration claims a verdict its gate does not reach:\n  "
        + "\n  ".join(wrong))
