#!/usr/bin/env python3
"""upstream_contract_parity_check.py — a re-implementation must be pinned to
the thing it re-implements.

WHY THIS EXISTS
===============
This plugin re-implements pieces of upstream flows on purpose: a step wants a
deterministic Python answer where upstream has a TCL script driven by a tool.
That is a good trade and it has one cost, which nothing in the repository was
paying. A re-implementation DRIFTS, silently, in two directions, and both were
measured on the same module on the same night:

  AN INPUT WENT MISSING. The step read eleven of the twenty PDK-scoped
  variables the upstream flow declares. One of the nine it did not read is the
  one through which a distribution declares its pad sites when the abstract
  views carry no site record. So the step reported a site ABSENT that the
  distribution DECLARES, with its size, in a view the step never opened -- and
  one design's whole verdict was blocked by our own code looking in the wrong
  place. Nobody had ever written down that we do not read that variable.

  A COMPUTATION DIVERGED. The same module measured how much of a side one cell
  consumes from the ORIENTED footprint, so a vertical side summed the master's
  HEIGHT. Upstream measures a cell in exactly two places and both read its
  WIDTH, on all four sides. The divergence was more than a factor of four on
  the side it was measured on, it had been there from the start, and it
  surfaced only as an unrelated refusal about something else.

Neither is a pad defect. "Not found" and "not looked for" are different
verdicts, and a step that cannot find a declared thing must be able to say
which views it read. A re-implementation that nothing pins against its upstream
will diverge, and the divergence will not announce itself -- it will come out
as an unrelated refusal, months later, on somebody else's brief.

WHAT THIS CHECKS, AND WHAT IT DELIBERATELY DOES NOT
===================================================
The register (`upstream_contract_parity.json`) names each place where we
re-implement upstream. This program enforces ONE property over it:

    NO NAME INSIDE A REGISTERED ENTRY IS UNACCOUNTED FOR.

Every variable the upstream declaration carries is in exactly one of three
classes -- implemented, declared-unperformed, or a known gap with a reference.
Every registered computation names either a pin test or a known gap with a
reference. An upstream name that appears tomorrow and that nobody classifies is
a finding the day it lands.

IT DOES NOT DECIDE THAT THE REGISTER IS COMPLETE. Nothing can: a
re-implementation nobody registered is invisible to any program, because the
only evidence that a piece of code mirrors upstream is the intent of whoever
wrote it. That decision is a reader's, and this program does not pretend to
make it. What it removes is the OTHER failure -- the one that actually
happened -- where the re-implementation WAS known, its upstream WAS known, and
still no artefact anywhere said which parts of the contract we had left out.

IT DOES NOT DECIDE THAT AN IMPLEMENTATION IS CORRECT. `implemented` is checked
against the module's own source: the name must actually be there. That catches
a register claiming an implementation the code does not contain. It cannot
catch an implementation that reads the variable and does the wrong thing with
it -- that is what the pin test named on a computation entry is for, and the
program checks the test EXISTS, never that it is a good test.

THE CLASSES HAVE TEETH IN BOTH DIRECTIONS
=========================================
A `known_gap` name that DOES appear in the module's source is a finding, not a
pass. When the gap is closed, the register has to say so in the same change --
otherwise the count of what is still wrong keeps a name that is no longer
wrong, and every register that drifts that way drifts toward looking worse than
it is until somebody stops believing it.

ZERO DENOMINATOR
================
A register that cannot be read, an entry with no upstream names, or a
`--distribution-root` whose upstream file is unreadable: rc 2 NOT DETERMINED,
naming the input that is missing. Never rc 0. A check that could not look has
not passed, and this program's whole subject is the difference between not
finding a thing and not having looked for it.

EXIT CODES
==========
  0  every registered entry accounted for (the counts are printed regardless)
  1  a finding
  2  the question could not be put -- the missing input is named
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTER = Path(__file__).resolve().parent / "upstream_contract_parity.json"

_CLASS_KEYS = ("implemented", "declared_unperformed", "omitted_by_design",
               "known_gap")


class Undetermined(Exception):
    """The question could not be put. Carries the name of the missing input."""


def load_register(path: Path) -> list:
    if not path.is_file():
        raise Undetermined(f"register not readable at {path} — no entries to "
                           f"judge, so nothing was checked")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise Undetermined(f"register at {path} does not parse: {exc}")
    entries = doc.get("entries")
    if not isinstance(entries, list) or not entries:
        raise Undetermined(
            f"register at {path} declares no entries. An empty register "
            f"passes every property it states, which is the one verdict this "
            f"program must never return")
    return entries


def _module_text(entry: dict) -> str:
    rel = (entry.get("our_module") or "").strip()
    if not rel:
        raise Undetermined(f"entry {entry.get('id')!r} names no `our_module`")
    p = PLUGIN_ROOT / rel
    if not p.is_file():
        raise Undetermined(
            f"entry {entry.get('id')!r} names `our_module` {rel}, which is not "
            f"a file — the side of the comparison we own is missing")
    return p.read_text(encoding="utf-8", errors="replace")


def _string_literals(text: str) -> "list[str] | None":
    """Every string literal in the module that is not a docstring.

    `None` if the module does not parse — the caller then falls back to the
    textual test rather than reporting "not mentioned" from a parse failure,
    which would be a verdict about our parser dressed up as a verdict about
    the module.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]


def _mentions(text: str, name: str) -> bool:
    r"""The name occurs in the module INSIDE A STRING LITERAL THE CODE EVALUATES.

    The standard is unchanged and is the one the register was built on: prose
    does not count. A name that appears only in a comment or a docstring —
    including a comment saying we do NOT read it — is still not a mention,
    because that sentence is exactly what this register exists to replace.

    WHAT CHANGED, AND WHY IT IS A WIDENING OF THE EVIDENCE AND NOT OF THE
    STANDARD. This used to ask for the name as a BARE QUOTED LITERAL,
    `"NAME"` or `'NAME'`. That is one of the forms in which a module consumes
    a name, not all of them, and the form it misses is the one actually in
    use here: a name consumed through a PATTERN.

        _pad_ring.py:490
            r"^[^\S\n]*dict\s+set\s+::env\(\s*PAD_FAKE_SITES\s*\)\s+"

    That is a string literal the module evaluates and matches against a PDK
    file. It is a consumption of the name in every sense the register cares
    about, and the old predicate answered False on it. MEASURED CONSEQUENCE:
    the register went on classifying `PAD_FAKE_SITES` a `known_gap` while the
    change that closed that gap was on main, and the staleness rule below —
    written for precisely this — never fired, because it is guarded by this
    predicate. The check exited 0 over its own blind spot.

    So this reads string literals from the AST instead of matching quote
    characters in raw text. A comment is not a string literal and a docstring
    is excluded explicitly, so nothing prose-shaped becomes a mention. What
    becomes visible is the module's own evaluated strings, whatever quoting,
    prefix or concatenation they were written with.
    """
    lits = _string_literals(text)
    if lits is None:
        return (f'"{name}"' in text) or (f"'{name}'" in text)
    return any(name in lit for lit in lits)


def check_contract_entry(entry: dict) -> tuple[list, dict]:
    findings: list = []
    snap = entry.get("snapshot") or {}
    names = snap.get("names")
    if not isinstance(names, list) or not names:
        raise Undetermined(
            f"entry {entry.get('id')!r} carries no upstream names. A contract "
            f"entry with an empty upstream set would report every one of our "
            f"omissions as accounted for")
    upstream = set(names)
    text = _module_text(entry)
    cls = entry.get("classification") or {}

    claimed: dict = {}
    for key in _CLASS_KEYS:
        block = cls.get(key) or ([] if key in ("implemented",
                                               "declared_unperformed") else {})
        got = list(block) if isinstance(block, (list, dict)) else []
        for n in got:
            if n in claimed:
                findings.append(
                    f"{entry['id']}: {n} is classified twice "
                    f"({claimed[n]} and {key}). A name in two classes means "
                    f"neither reading is the one the register asserts.")
            claimed[n] = key

    for n in sorted(upstream - set(claimed)):
        findings.append(
            f"{entry['id']}: upstream declares {n} and the register places it "
            f"in no class. Classify it: implemented, declared_unperformed, "
            f"omitted_by_design with a reason, or known_gap with a reference.")

    for n in sorted(set(claimed) - upstream):
        findings.append(
            f"{entry['id']}: the register classifies {n} as "
            f"{claimed[n]}, and the upstream snapshot does not declare it. "
            f"Either the snapshot is stale or the classification names "
            f"something upstream dropped.")

    for n in cls.get("implemented") or []:
        if n in upstream and not _mentions(text, n):
            findings.append(
                f"{entry['id']}: {n} is classified implemented and does not "
                f"appear in {entry['our_module']}. The register claims an "
                f"implementation the module does not contain.")

    for n in cls.get("declared_unperformed") or []:
        if n in upstream and not _mentions(text, n):
            findings.append(
                f"{entry['id']}: {n} is classified declared_unperformed and "
                f"does not appear in {entry['our_module']}. The point of that "
                f"class is that the omission is recorded IN THE MODULE, where "
                f"a reader of the artefact meets it.")

    for n, reason in (cls.get("omitted_by_design") or {}).items():
        if not str(reason or "").strip():
            findings.append(
                f"{entry['id']}: {n} is omitted_by_design with no reason. An "
                f"omission with no reason is indistinguishable from an "
                f"oversight, which is what this register exists to tell apart.")

    for n, rec in (cls.get("known_gap") or {}).items():
        rec = rec if isinstance(rec, dict) else {}
        if not str(rec.get("reference") or "").strip():
            findings.append(
                f"{entry['id']}: {n} is a known_gap with no reference. "
                f"Without one the class is an excuse list.")
        if not str(rec.get("reason") or "").strip():
            findings.append(
                f"{entry['id']}: {n} is a known_gap with no reason.")
        if n in upstream and _mentions(text, n):
            findings.append(
                f"{entry['id']}: {n} is classified known_gap and DOES appear "
                f"in {entry['our_module']}. If the gap is closed, move it to "
                f"implemented in the same change that closed it — a count of "
                f"what is still wrong that keeps a name that is no longer "
                f"wrong stops being believed.")

    counts = {
        "upstream_names": len(upstream),
        "implemented": len(cls.get("implemented") or []),
        "declared_unperformed": len(cls.get("declared_unperformed") or []),
        "omitted_by_design": len(cls.get("omitted_by_design") or {}),
        "known_gap": len(cls.get("known_gap") or {}),
    }
    return findings, counts


def check_computation_entry(entry: dict) -> tuple[list, dict]:
    findings: list = []
    _module_text(entry)  # our side must exist
    anchors = (entry.get("upstream") or {}).get("anchors") or []
    if not anchors:
        raise Undetermined(
            f"entry {entry.get('id')!r} names no upstream anchors. With "
            f"nothing to point at, the entry asserts a parity it cannot even "
            f"describe")
    pin = entry.get("pin_test") or {}
    if isinstance(pin, str):
        pin = {"status": "test", "test": pin}
    status = (pin.get("status") or "").strip()

    if status == "test":
        ref = (pin.get("test") or "").strip()
        if "::" not in ref:
            findings.append(
                f"{entry['id']}: pin_test {ref!r} does not name a test as "
                f"<file>::<function>.")
        else:
            rel, func = ref.split("::", 1)
            tf = PLUGIN_ROOT / rel
            if not tf.is_file():
                findings.append(
                    f"{entry['id']}: pin_test names {rel}, which is not a "
                    f"file. The pin is the whole content of this entry.")
            elif f"def {func}" not in tf.read_text(encoding="utf-8",
                                                   errors="replace"):
                findings.append(
                    f"{entry['id']}: pin_test names {func} in {rel} and no "
                    f"such test is defined there.")
    elif status == "known_gap":
        if not str(pin.get("reference") or "").strip():
            findings.append(
                f"{entry['id']}: the pin is a known_gap with no reference.")
        if not str(pin.get("reason") or "").strip():
            findings.append(
                f"{entry['id']}: the pin is a known_gap with no reason.")
    else:
        findings.append(
            f"{entry['id']}: pin_test status {status!r} is neither 'test' nor "
            f"'known_gap'. An unregistered third state reads as covered.")

    return findings, {"anchors": len(anchors),
                      "pin": status or "unset"}


def verify_snapshot(entry: dict, root: Path) -> list:
    """Re-read upstream and compare it against what the register recorded.

    Only runs when a distribution root is supplied. Absent one, the register's
    snapshot is the denominator, and it says on its face when and where it was
    measured.
    """
    up = entry.get("upstream") or {}
    rel = (up.get("file") or "").strip()
    if not rel:
        raise Undetermined(f"entry {entry.get('id')!r} names no upstream file")
    path = root / rel
    if not path.is_file():
        raise Undetermined(
            f"entry {entry.get('id')!r}: upstream file {path} is not readable "
            f"under the supplied distribution root, so the snapshot could not "
            f"be re-measured")
    text = path.read_text(encoding="utf-8", errors="replace")
    findings: list = []
    snap = entry.get("snapshot") or {}

    recorded_sha = (snap.get("file_sha256") or "").strip()
    actual_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if recorded_sha and recorded_sha != actual_sha:
        findings.append(
            f"{entry['id']}: upstream {rel} has changed since the snapshot "
            f"was taken ({snap.get('measured_on')}). Recorded "
            f"{recorded_sha[:12]}, read {actual_sha[:12]}. Re-measure the "
            f"entry before trusting any class in it.")

    rx = (up.get("extract_regex") or "").strip()
    if rx:
        found = set(re.findall(rx, text))
        recorded = set(snap.get("names") or [])
        for n in sorted(found - recorded):
            findings.append(
                f"{entry['id']}: upstream declares {n} and the snapshot does "
                f"not carry it. A name we never recorded is a name nobody "
                f"classified.")
        for n in sorted(recorded - found):
            findings.append(
                f"{entry['id']}: the snapshot carries {n} and upstream no "
                f"longer declares it.")

    for anchor in (up.get("anchors") or []):
        if anchor not in text:
            findings.append(
                f"{entry['id']}: upstream anchor {anchor!r} is no longer "
                f"present in {rel}. The computation we mirror has moved, and "
                f"the entry points at nothing.")
    return findings


def _basis_line(basis: dict) -> str:
    """WHAT THIS VERDICT WAS MEASURED AGAINST, printed at every verdict.

    Without this the PASS reads as "our re-implementations agree with
    upstream" when what was actually compared, absent a distribution root, is
    our code against OUR OWN RECORD of upstream — the register's snapshot. Both
    print the same way and only one of them is a statement about upstream.

    This is the rule the whole register exists for, turned on the register's own
    verdict: an answer must say which sources it read. It was missing here until
    someone asked what the PASS was over.
    """
    total = basis.get("entries_total", 0)
    reread = basis.get("upstream_reread") or []
    root = basis.get("distribution_root")
    if not root:
        return (f"BASIS: the register's RECORDED SNAPSHOTS for all {total} "
                f"entry/entries. Upstream was NOT re-read on this run — pass "
                f"--distribution-root to compare against a live distribution. "
                f"This verdict is about our code against our own record.")
    return (f"BASIS: upstream re-read under {root} for {len(reread)} of "
            f"{total} entry/entries{'' if len(reread) == total else ' — the rest were not reached'}.")


def run(register: Path, distribution_root: Path | None) -> tuple[int, dict]:
    entries = load_register(register)
    findings: list = []
    undetermined: list = []
    per_entry: dict = {}
    reread: list = []          # entries whose upstream file was ACTUALLY re-read

    for entry in entries:
        eid = entry.get("id") or "<unnamed entry>"
        kind = (entry.get("kind") or "").strip()
        try:
            if kind == "contract":
                f, counts = check_contract_entry(entry)
            elif kind == "computation":
                f, counts = check_computation_entry(entry)
            else:
                raise Undetermined(
                    f"entry {eid!r} has kind {kind!r}; the register knows "
                    f"'contract' and 'computation'")
            if distribution_root is not None:
                f = f + verify_snapshot(entry, distribution_root)
                reread.append(eid)
            findings.extend(f)
            per_entry[eid] = counts
        except Undetermined as exc:
            undetermined.append(str(exc))
            per_entry[eid] = {"undetermined": str(exc)}

    basis = {"upstream_reread": sorted(reread),
             "entries_total": len(entries),
             "distribution_root": str(distribution_root) if distribution_root
                                  else None}
    if undetermined:
        return 2, {"verdict": "NOT_DETERMINED", "entries": len(entries),
                   "per_entry": per_entry, "undetermined": undetermined,
                   "findings": findings, "basis": basis}
    if findings:
        return 1, {"verdict": "FAIL", "entries": len(entries),
                   "per_entry": per_entry, "findings": findings,
                   "basis": basis}
    return 0, {"verdict": "PASS", "entries": len(entries),
               "per_entry": per_entry, "findings": [], "basis": basis}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    # THE POPULATION DRIVERS PASS A PROJECT PATH POSITIONALLY, AND THIS GATE
    # HAS NO USE FOR ONE. Its subject is the repository's own register, not a
    # design. Refusing the argument would answer an argparse usage error where
    # a verdict belongs; accepting it silently would make it exactly the kind
    # of knob this lane exists to capture -- one an author can set that
    # changes nothing. So it is accepted AND ANNOUNCED, every run that
    # supplies it, which is the same ruling applied to this program that the
    # register applies to the flow.
    ap.add_argument("project", nargs="?", default=None,
                    help="accepted for the population drivers and NOT READ: "
                         "this gate's subject is the repository's own "
                         "register. Supplying it prints a line saying so.")
    ap.add_argument("--register", default=str(DEFAULT_REGISTER),
                    help="the parity register to enforce")
    ap.add_argument("--distribution-root", default=None,
                    help="re-measure each entry's upstream under this root "
                         "(a checkout or an unpacked image path). Absent, the "
                         "register's recorded snapshot is the denominator.")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    if a.project is not None:
        # SAID IN THE WORDS THE REPO'S OWN DISCLOSURE PREDICATE READS.
        # `gate_discloses_denominator_check --population project` drives every
        # gate against a path that DOES NOT EXIST and requires the output to
        # say that nothing under it was opened. The old sentence said exactly
        # that in other words, so the gate was recorded as answering rc 0 over
        # an absent project without disclosing it — a true statement about the
        # wording and a false one about the gate.
        print(f"NOTE: the project path {a.project!r} is not read and is NOT "
              f"APPLICABLE to this gate, so nothing under it was opened — "
              f"this gate's subject is the repository's own re-implementation "
              f"register, and it judges the same way from any directory.")

    root = Path(a.distribution_root) if a.distribution_root else None
    try:
        rc, report = run(Path(a.register), root)
    except Undetermined as exc:
        print(f"NOT DETERMINED: {exc}", file=sys.stderr)
        if a.json:
            # ATOMIC (vibe-ic#1082). The NOT_DETERMINED artefact needs
            # this as much as the verdict one: a reader that finds a
            # truncated refusal cannot tell it from a refusal that was
            # never written.
            atomic_write_text(Path(a.json), json.dumps(
                {"gate": "upstream_contract_parity_check",
                 "verdict": "NOT_DETERMINED",
                 "undetermined": [str(exc)]}, indent=2) + "\n")
        return 2

    report["gate"] = "upstream_contract_parity_check"
    report["register"] = str(a.register)
    if a.json:
        # ATOMIC (vibe-ic#1082): this is the DECLARED report a later
        # reader resolves, so the final name must appear only once the
        # write is complete.
        atomic_write_text(Path(a.json),
                          json.dumps(report, indent=2) + "\n")

    # The denominator is printed on every run, at every verdict.
    for eid, counts in report["per_entry"].items():
        print(f"  {eid}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    print("  " + _basis_line(report.get("basis") or {}))

    if rc == 2:
        print(f"NOT DETERMINED: {len(report['undetermined'])} entry/entries "
              f"could not be judged:", file=sys.stderr)
        for u in report["undetermined"]:
            print(f"  - {u}", file=sys.stderr)
        return 2
    if rc == 1:
        print(f"FAIL: {len(report['findings'])} unaccounted name(s) across "
              f"{report['entries']} registered re-implementation(s):")
        for f in report["findings"]:
            print(f"  - {f}")
        return 1
    print(f"PASS: {report['entries']} registered re-implementation(s); every "
          f"upstream name and every registered computation is accounted for.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
