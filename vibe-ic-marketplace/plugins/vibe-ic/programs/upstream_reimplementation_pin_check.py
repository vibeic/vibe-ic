#!/usr/bin/env python3
"""upstream_reimplementation_pin_check.py — a re-implementation must be pinned
to the thing it re-implements.

WHY THIS EXISTS
===============
A step in this flow re-derived a geometric computation that an upstream flow
already performs. Ours took a cell's along-the-row extent from its ORIENTED
footprint; upstream takes it from the master's WIDTH, in both places it
measures, on all four sides. On a real ring that is 19 x 350 um summed against
a 1500 um side — a 4.4x error.

NOTHING COMPARED THE TWO. The re-derivation was self-consistent, its tests
asserted our constants against our constants, and the drift surfaced only as an
unrelated refusal, at a distance from the line that drifted. The upstream file
was CITED in a comment — prose a human reads, that no machine ever opens.

    a citation is a claim about a file.
    a pin is a claim a machine can lose.

WHAT A PIN IS
=============
A module-level ``UPSTREAM_PINS`` list or tuple beside the code it constrains. Each entry:

    {"upstream": "<path under the installed upstream package>",
     "anchor":   "<exact text in that file that fixes the quantity>",
     "quantity": "<what our code takes from it, in words>",
     "why":      "<why ours would be wrong without it>"}

``anchor`` is EXACT TEXT, not a line number. A line number published today
points ten lines above its subject tomorrow and still looks precise; the anchor
either is in the file or is not.

WHAT THIS PROGRAM CHECKS
========================
For every ``programs/*.py`` declaring ``UPSTREAM_PINS``, every anchor must be
present in its named upstream file, read from the upstream tree installed on
this host. A missing anchor means one of two things and both need a human: the
upstream computation changed, or the pin was written wrong. Either way our
re-derivation is no longer known to agree with anything.

The pin list is read STATICALLY (ast.literal_eval of the assignment). This
program never imports the modules it audits: importing a thousand programs to
read one constant is a cost and a side-effect this check has no business
taking.

WHAT IT DELIBERATELY DOES NOT DO
================================
It does not decide WHETHER a program should have a pin. That is the judgement
this program does not make and does not fake: a machine reading our source
cannot tell a re-derivation of an upstream computation from an ordinary
computation that merely resembles one. So the unpinned set is reported as a
CENSUS — printed on every run, never a verdict — and the number is measured
rather than assumed. A gate that guessed here would produce the
false-positive noise that teaches people to ignore the tool.

AND IT REFUSES RATHER THAN PASSES WHEN IT CANNOT LOOK
=====================================================
No upstream tree on this host means the anchors were not read. That is rc 2
NOT DETERMINED with the missing input named — never rc 0. A check that reports
"agrees" after opening nothing is the defect one level up from the one this
program exists to catch.

Exit: 0 = every declared anchor was read and found
      1 = at least one declared anchor is absent from its upstream file
      2 = could not look (no upstream tree, or no pin declared anywhere)
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

RC_OK = 0
RC_DRIFT = 1
RC_CANNOT_CHECK = 2

PIN_NAME = "UPSTREAM_PINS"

#: Where an upstream tool package may be installed. Ordered; first hit wins.
#: The list is data, not discovery: a root that does not exist costs one stat.
DEFAULT_UPSTREAM_ROOTS: Tuple[str, ...] = (
    "/usr/local/lib/python3.12/dist-packages",
    "/usr/local/lib/python3.11/dist-packages",
    "/usr/lib/python3/dist-packages",
    "/headless/.local/lib/python3.12/site-packages",
    "/foss/tools",
)

#: A source citation of an upstream flow file — the prose form a pin replaces.
#: Used ONLY for the census; it never contributes to the verdict.
CITATION_RE = re.compile(r"\b(librelane|openlane2?)/[A-Za-z0-9_./-]+")


def _roots(explicit: List[str]) -> List[Path]:
    out = [Path(p) for p in explicit]
    env = os.environ.get("VIBEIC_UPSTREAM_ROOT", "")
    out += [Path(p) for p in env.split(os.pathsep) if p]
    out += [Path(p) for p in DEFAULT_UPSTREAM_ROOTS]
    return out


def resolve_upstream(rel: str, roots: List[Path]) -> Optional[Path]:
    """The first root under which ``rel`` exists, or None.

    Returns the FILE, so a caller can say which root answered rather than
    reporting a bare boolean nobody can act on.
    """
    for r in roots:
        cand = r / rel
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


def probe_roots(roots: List[Path], declared: List[dict]) -> List[dict]:
    """What each probed root actually held, root by root.

    THE ROOT LIST WAS PRINTED AND NEVER MEASURED. `roots_probed` said which
    directories this check WOULD have looked under; it said nothing about
    whether any of them existed, and a reader of an rc 2 could not tell a host
    with no upstream tree at all from a host that has one which simply does not
    carry the pinned files. Those are different states and only the second is
    evidence about upstream.

    So each root is reported with two measured facts: whether the directory is
    there, and how many of the DECLARED upstream paths resolve under it. In the
    rc 2 case the second number is 0 for every root by construction, and saying
    so is the difference between a measurement with a stated gap and a shrug.
    """
    rels = sorted({str(pin.get("upstream") or "") for pin in declared
                   if pin.get("upstream")})
    out: List[dict] = []
    for r in roots:
        try:
            present = r.is_dir()
        except OSError:
            present = False
        hits = 0
        if present:
            for rel in rels:
                try:
                    if (r / rel).is_file():
                        hits += 1
                except OSError:
                    continue
        out.append({"root": str(r), "directory_present": present,
                    "declared_files_found": hits})
    return out


def _root_phrase(row: dict, total_rels: int) -> str:
    """One probed root, in words, for the refusal line."""
    if not row["directory_present"]:
        return f"{row['root']} (no such directory on this host)"
    return (f"{row['root']} (directory present; {row['declared_files_found']} "
            f"of {total_rels} declared upstream file(s) under it)")


def read_pins(path: Path) -> List[dict]:
    """The ``UPSTREAM_PINS`` declared by one module, read without importing it.

    A declaration this function cannot evaluate is NOT silently dropped: it is
    returned as a pin carrying ``unreadable``, so a malformed declaration
    becomes a finding instead of an empty list that reads like "no pins".
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError) as exc:
        return [{"unreadable": f"{type(exc).__name__}: {exc}"}]
    out: List[dict] = []
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == PIN_NAME for t in targets):
            continue
        try:
            pins = ast.literal_eval(value)
        except (ValueError, SyntaxError) as exc:
            return [{"unreadable": f"{PIN_NAME} is not a literal: {exc}"}]
        # list OR tuple: the container flavour is house style, not a
        # property of the pin. Judging it would be this check inventing a
        # requirement out of the first file it happened to read.
        if not isinstance(pins, (list, tuple)):
            return [{"unreadable": f"{PIN_NAME} is {type(pins).__name__}, "
                                   f"not a list or tuple"}]
        for p in pins:
            out.append(dict(p) if isinstance(p, dict) else
                       {"unreadable": f"pin entry is {type(p).__name__}, not a dict"})
    return out


def census_unpinned(programs: List[Path]) -> List[Tuple[str, List[str]]]:
    """Modules citing an upstream flow file in prose and declaring no pin.

    Reported, never judged — see the module docstring. The point of the number
    is that it is MEASURED: "some programs are unpinned" is not a fact anyone
    can act on, and "6 are, and here they are" is.
    """
    rows = []
    for p in programs:
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if PIN_NAME in txt:
            continue
        cites = sorted({m.group(0) for m in CITATION_RE.finditer(txt)})
        if cites:
            rows.append((p.name, cites))
    return rows


def check(programs_dir: Path, roots: List[Path]) -> dict:
    programs = sorted(programs_dir.glob("*.py"))
    declared: List[dict] = []
    for p in programs:
        for pin in read_pins(p):
            pin = dict(pin)
            pin["declared_by"] = p.name
            declared.append(pin)

    res: Dict[str, object] = {
        "programs_scanned": len(programs),
        "pins_declared": len(declared),
        "roots_probed": [str(r) for r in roots],
        "census_unpinned": [{"program": n, "citations": c}
                            for n, c in census_unpinned(programs)],
        "checked": [],
        "findings": [],
        # The leg that runs WITHOUT an upstream tree: a declaration this gate
        # can evaluate, carrying both `upstream` and `anchor`. Counted
        # separately from `checked` so an rc 2 can state what it DID decide
        # rather than only what it could not.
        "structurally_valid": 0,
        "declared_upstream_files": 0,
        "roots_state": [],
    }
    if not declared:
        res["cannot_check"] = (
            f"no module under {programs_dir} declares {PIN_NAME}, so no "
            f"re-implementation is pinned and none was compared")
        return res

    for pin in declared:
        if "unreadable" in pin:
            res["findings"].append({
                "kind": "PIN_UNREADABLE",
                "declared_by": pin["declared_by"],
                "detail": pin["unreadable"]})
            continue
        rel, anchor = pin.get("upstream"), pin.get("anchor")
        if not rel or not anchor:
            res["findings"].append({
                "kind": "PIN_INCOMPLETE",
                "declared_by": pin["declared_by"],
                "detail": "a pin needs both `upstream` and `anchor`; got "
                          f"{sorted(pin)}"})
            continue
        res["structurally_valid"] += 1
        found = resolve_upstream(rel, roots)
        if found is None:
            res["checked"].append({"declared_by": pin["declared_by"],
                                   "upstream": rel, "status": "NOT_ON_HOST"})
            continue
        text = found.read_text(encoding="utf-8", errors="replace")
        present = anchor in text
        res["checked"].append({
            "declared_by": pin["declared_by"], "upstream": rel,
            "resolved": str(found), "status": "PRESENT" if present else "ABSENT",
            "quantity": pin.get("quantity", "")})
        if not present:
            res["findings"].append({
                "kind": "UPSTREAM_ANCHOR_ABSENT",
                "declared_by": pin["declared_by"],
                "upstream": str(found),
                "anchor": anchor,
                "quantity": pin.get("quantity", ""),
                "detail": "the text this re-implementation is pinned to is not "
                          "in the file it names — upstream changed, or the pin "
                          "is wrong. Either way ours is no longer known to "
                          "agree with anything."})
    rels = sorted({str(pin.get("upstream") or "") for pin in declared
                   if pin.get("upstream")})
    res["declared_upstream_files"] = len(rels)
    res["roots_state"] = probe_roots(roots, declared)
    read = [c for c in res["checked"] if c["status"] != "NOT_ON_HOST"]
    if not read and not res["findings"]:
        # WHAT WAS DECIDED, THEN WHAT WAS NOT, THEN WHERE IT LOOKED. In that
        # order and never only the middle one: a refusal that names only its
        # missing input reads as a gate that checked nothing, and this one did
        # check something — the structural leg needs no upstream tree and it
        # ran over every declared pin.
        probed = "; ".join(_root_phrase(r, len(rels))
                           for r in res["roots_state"]) or "(no root to probe)"
        res["cannot_check"] = (
            f"{res['structurally_valid']} of {len(declared)} declared pin(s) "
            f"PASSED the structural check, which needs no upstream tree: each "
            f"declaration is a literal this gate could evaluate and each pin "
            f"carries both `upstream` and `anchor`. A pin failing either of "
            f"those is rc 1 here, on this same host. What was NOT done is the "
            f"comparison against upstream: none of the "
            f"{len(rels)} declared upstream file(s) is on this host, so no "
            f"anchor was read. Missing input: an installed upstream tool tree. "
            f"Roots probed, each with what it held: {probed}")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # ACCEPTED AND NOT READ, deliberately. This flow's population drivers
    # invoke every `*_check.py` as `<program> <project>`. Rejecting that
    # positional makes argparse exit 2 — THE SAME CODE this program uses for an
    # honest "I could not look", and the same conflation the repo has now had
    # to route around three times (#492 at the umbrella, #1347 in a gate's
    # wiring). A usage error must not wear a refusal's exit code, so the
    # argument is accepted and the program answers its own question about the
    # program tree, which is what it audits.
    ap.add_argument("project", nargs="?", default=None,
                    help="accepted for driver compatibility and NOT read: this "
                         "check audits the program tree, not a project")
    ap.add_argument("--programs-dir", default=str(Path(__file__).resolve().parent),
                    help="directory of programs to audit (default: this one)")
    ap.add_argument("--upstream-root", action="append", default=[],
                    help="root under which an upstream package is installed; "
                         "repeatable. Also read from VIBEIC_UPSTREAM_ROOT.")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    roots = _roots(a.upstream_root)
    res = check(Path(a.programs_dir), roots)
    if a.project is not None:
        # In the artefact as well as on stdout: a reader of the JSON must be
        # able to see that a project path was handed over and not consulted.
        res["project_argument_ignored"] = a.project
        # NOT APPLICABLE, in those words: see the same note in
        # `upstream_contract_parity_check`. The absent-project population reads
        # this line for a statement that nothing under the path was opened.
        print(f"[SCOPE] a project path ({a.project!r}) was passed and is NOT "
              f"read, because it is NOT APPLICABLE to this check and nothing "
              f"under it was opened: this check audits the program tree at "
              f"{a.programs_dir}")

    if a.json:
        # ATOMIC (vibe-ic#1082): this is the DECLARED report a later
        # reader resolves, so the final name must appear only once the
        # write is complete.
        atomic_write_text(Path(a.json),
                          json.dumps(res, indent=2) + "\n",
                          encoding="utf-8")

    cen = res["census_unpinned"]
    print(f"[CENSUS] {len(cen)} program(s) cite an upstream flow file BY PACKAGE PATH "
          f"in prose and declare no {PIN_NAME}. This is reported, not judged:")
    for row in cen:
        print(f"    {row['program']}: {', '.join(row['citations'][:4])}")
    print(f"[POPULATION] {res['pins_declared']} pin(s) declared across "
          f"{res['programs_scanned']} program(s); "
          f"{res['structurally_valid']} passed the structural check "
          f"(no upstream tree required)")
    for row in res.get("roots_state") or []:
        print(f"    root {_root_phrase(row, res['declared_upstream_files'])}")

    if res.get("cannot_check"):
        print(f"[NOT DETERMINED] {res['cannot_check']}. This is NOT 'the "
              f"re-implementations agree'.", file=sys.stderr)
        return RC_CANNOT_CHECK

    for c in res["checked"]:
        print(f"    {c['status']:11s} {c['declared_by']} -> {c['upstream']}")

    if res["findings"]:
        for f in res["findings"]:
            print(f"[FAIL] {f['kind']} in {f['declared_by']}: {f['detail']}",
                  file=sys.stderr)
            if f.get("anchor"):
                print(f"       anchor: {f['anchor']!r}", file=sys.stderr)
                print(f"       file:   {f['upstream']}", file=sys.stderr)
        return RC_DRIFT

    print(f"[PASS] {len(res['checked'])} pin(s) resolved; every anchor is "
          f"present in the upstream file it names")
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
