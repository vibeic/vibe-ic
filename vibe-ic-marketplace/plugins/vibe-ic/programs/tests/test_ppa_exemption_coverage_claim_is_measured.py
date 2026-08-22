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

REPO = Path(__file__).resolve().parents[5]
PROGRAMS = REPO / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
WIRING = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"

#: "over 20 pairs", "over 1830 pairs", "over 61 contracts"
_CLAIM = re.compile(r"\bover\s+(\d+)\s+(pair|record|contract|set)s?\b")
#: what a corpus gate prints: "21 contract(s), 0 refused" / "210 pair(s) compared"
_REPORTED = re.compile(r"\b(\d+)\s+(pair|record|contract|set)\(s\)")


def _logical_lines(text: str):
    return re.sub(r"\\\n\s*", " ", text).splitlines()


def _rows():
    """(label, claimed_n, unit, argv) for every PPA --corpus row stating a number."""
    lines = _logical_lines(WIRING.read_text(encoding="utf-8"))
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
        claim = _CLAIM.search(lines[j])
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
                        int(claim.group(1)), claim.group(2), argv))
    return out


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
    wrong, noted = [], []
    for label, claimed, unit, argv in _rows():
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
