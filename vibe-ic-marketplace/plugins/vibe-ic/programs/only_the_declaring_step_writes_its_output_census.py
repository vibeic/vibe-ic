#!/usr/bin/env python3
"""Two writers for one path the flow declares as a step's required output.

THIS IS A CENSUS, NOT A GATE. IT MUST NOT BE WIRED AS A BLOCKING CHECK.
=======================================================================
The gate for this rule is
`programs/only_the_declaring_step_writes_its_output.py`.
That one REFUSES: it runs a narrow population with no inventory and goes red
on a live defect. This
file does something different and complementary — it reports the WIDE
population, the classification, and the debt recorded against it.

Both were written independently from the same capture record, by two lanes that
could not see each other's tree, and on this tree they returned opposite
verdicts. That is not a bug in either: a wide population with recorded waivers
PASSES today with the debt written down, and a narrow population with no
inventory FAILS today because the debt refuses. Only one of those is a gate.
The ruling (2026-08-22) gave the NAME to the refusing one, and gave this one the
job it was actually doing.

So: exit status here is INFORMATIONAL. The default is 0 whatever is found,
because a census that exits non-zero gets wired as a gate by the next person who
reads the exit code. `--strict` restores a refusing exit for a caller who
deliberately wants one; nothing in the flow should pass it.



CENSUS — informational. The gate is `programs/only_the_declaring_step_writes_its_output.py`.

WHAT IT ASKS THE REPOSITORY
===========================
A path one step declares as its own required output may be written only by that
step's producer. A helper that runs the same checker with fewer arguments
leaves a strictly weaker verdict wearing the declared filename, and a
release-gating tier then grades the weaker file with no indication that a
stronger one ever existed.

MEASURED: run at one path, the declaring step's argument form produced 811
bytes with two findings and the scoping key populated; the delegate's reduced
form produced 308 bytes with one finding and no scope keys at all. The writer
that dropped the sign-off scoping wins by running last.

THE PREDICATE
=============
Read `required_outputs` from the flow document and keep the CONCRETE paths — a
glob or an ` OR ` alternation names a set, not a path, and cannot have a single
owner. Then parse every module under `programs/` and find the WRITES:

    <expr>.write_text(...) / .write_bytes(...) / .writelines(...)
    open(<expr>, "w"...)

resolving `<expr>` through `/`-join chains (`project / "reports" / "x.json"`)
and through one hop of local binding. A path with more than one writing module
is a finding.

NAMING IS NOT WRITING, and the difference is 88 versus 2. Matching modules that
merely mention a declared path returns 88 of 121 paths with "two writers" —
almost all of them CHECKERS that READ the artefact. That is exactly the defect
`invocation_proved_by_parse_not_by_text` describes, so the write must be read
from the syntax tree and not from the text.

COVERAGE, MEASURED — and this rule cannot see most of its population
====================================================================
    declared concrete output paths                  121
    of those, with a write this scan can resolve      23
    of those, with more than one writing module        2

98 of 121 have no resolvable write here: they are written through a path built
in a way this reconstruction does not follow, or by a tool outside `programs/`.
So the rule sees 23 of 121 and says so on every run. It under-reports by
construction; everything it reports is real.

THE NEGATIVE CONTROL IS PART OF THE GATE, and the record demanded it: a check
whose declared-path set came back empty would pass over nothing and read
exactly like a clean tree. `--self-test` asserts that known flow-owned paths
are still recognised as declared, and the test suite drives it.

EXIT
====
  0  every declared output path has at most one writer, or is inventoried
  1  a NEW second writer, or a stale inventory row
  2  cannot determine — no flow document, unreadable, or it declares nothing
  3  bad invocation
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082

_INVENTORY_NAME = "declared_output_writer_inventory.json"
_FLOW_REL = "flow/phase1_phase2_phase3.yaml"

_WRITE_ATTRS = ("write_text", "write_bytes", "writelines")

#: Write forms the first version of this enumeration MISSED, added 2026-08-22
#: by an audit of this file's own lists against what the tree actually uses:
#:
#:     shutil.copy2   67 uses      path.open("w")   the ATTRIBUTE form
#:     shutil.copytree 43          shutil.copy      20
#:
#: The bare-`open(p, "w")` branch below catches `open()` as a NAME; it does not
#: catch `p.open("w")`, which is an Attribute call and is how a Path writes.
#: MEASURED: widening changes no finding today — the same two paths have two
#: writers either way — so this closes a LATENT gap. A second writer arriving
#: through `shutil.copy2(src, declared_path)` would have been invisible.
_SHUTIL_WRITES = ("copy", "copy2", "copyfile", "copytree", "move")

#: Paths that must still be recognised as flow-owned. If the flow document is
#: reshaped and these stop resolving, the scan is measuring nothing and says so
#: rather than passing.
_CONTROL_PATHS = ("reports/spare_cell_coverage.json",
                  "phase2/stage2/synth/netlist.v")


def _declared(flow: Path) -> Dict[str, Set[str]]:
    import yaml
    doc = yaml.safe_load(flow.read_text(encoding="utf-8"))
    out: Dict[str, Set[str]] = {}
    steps: List[Tuple[str, List[str]]] = []

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and ("required_outputs" in o or "outputs" in o):
                ro = o.get("required_outputs") or o.get("outputs") or []
                if isinstance(ro, str):
                    ro = [ro]
                steps.append((str(o.get("id")),
                              [p.strip() for p in ro if isinstance(p, str)]))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    for sid, ro in steps:
        for p in ro:
            # A glob or an alternation names a SET, which cannot have one owner.
            if "*" in p or " OR " in p:
                continue
            out.setdefault(p, set()).add(sid)
    return out


def _joined_suffix(node: ast.AST) -> Optional[str]:
    """The constant tail of `x / "a" / "b"`, as `a/b`."""
    parts: List[str] = []
    cur = node
    while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Div):
        r = cur.right
        if isinstance(r, ast.Constant) and isinstance(r.value, str):
            parts.append(r.value)
        else:
            return None
        cur = cur.left
    if isinstance(cur, ast.Constant) and isinstance(cur.value, str):
        parts.append(cur.value)
    if not parts:
        return None
    return "/".join(reversed(parts))


def _match(sfx: Optional[str], declared: Dict[str, Set[str]]) -> Optional[str]:
    if not sfx:
        return None
    for p in declared:
        if p == sfx or p.endswith("/" + sfx) or sfx.endswith("/" + p) \
                or sfx.endswith(p):
            return p
    return None


def scan(root: Path) -> Tuple[List[dict], Dict[str, int], Dict[str, Set[str]]]:
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    declared = _declared(plugin / _FLOW_REL)
    writers: Dict[str, Set[str]] = {}
    for f in sorted((plugin / "programs").rglob("*.py")):
        if "tests" in f.parts:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        bound: Dict[str, str] = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                    and isinstance(n.targets[0], ast.Name):
                s = _joined_suffix(n.value)
                if s:
                    bound[n.targets[0].id] = s
                elif isinstance(n.value, ast.Constant) \
                        and isinstance(n.value.value, str):
                    bound[n.targets[0].id] = n.value.value
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            tgt = None
            if isinstance(fn, ast.Attribute) and fn.attr in _WRITE_ATTRS:
                tgt = fn.value
            elif isinstance(fn, ast.Attribute) and fn.attr == "open" and n.args \
                    and isinstance(n.args[0], ast.Constant) \
                    and "w" in str(n.args[0].value):
                tgt = fn.value                      # p.open("w")
            elif isinstance(fn, ast.Attribute) and fn.attr in _SHUTIL_WRITES \
                    and len(n.args) >= 2:
                tgt = n.args[1]                     # shutil.copy2(src, DEST)
            elif isinstance(fn, ast.Name) and fn.id == "open" and len(n.args) >= 2:
                m = n.args[1]
                if isinstance(m, ast.Constant) and "w" in str(m.value):
                    tgt = n.args[0]
            if tgt is None:
                continue
            p = _match(_joined_suffix(tgt), declared)
            if p is None and isinstance(tgt, ast.Name):
                p = _match(bound.get(tgt.id), declared)
            if p:
                writers.setdefault(p, set()).add(f.name)

    findings = [{"path": p, "writers": sorted(w),
                 "declaring_steps": sorted(declared[p])}
                for p, w in sorted(writers.items()) if len(w) > 1]
    return findings, {"declared_concrete_paths": len(declared),
                      "paths_with_a_resolvable_write": len(writers),
                      "paths_with_more_than_one_writer": len(findings)}, declared


def _key(f: dict) -> str:
    return f"{f['path']}::{','.join(f['writers'])}"


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--inventory", default=None)
    ap.add_argument("--self-test", action="store_true",
                    help="assert the control paths are still flow-owned")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="restore a refusing exit; a census "
                         "is informational by default")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    try:
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] only_the_declaring_step_writes_its_output: "
                  "no repository root. NOT a pass.", file=sys.stderr)
            return 2
        flow = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / _FLOW_REL
        if not flow.is_file():
            print(f"[CANNOT DETERMINE] only_the_declaring_step_writes_its_output:"
                  f" no flow document at {flow}. NOT a pass.", file=sys.stderr)
            return 2
        findings, denom, declared = scan(root)
        if denom["declared_concrete_paths"] == 0:
            print("[CANNOT DETERMINE] only_the_declaring_step_writes_its_output: "
                  "the flow declares no concrete required output. A verdict over "
                  "an empty set is NOT a pass.", file=sys.stderr)
            return 2
        if a.self_test:
            missing = [p for p in _CONTROL_PATHS if p not in declared]
            if missing:
                print(f"[CANNOT DETERMINE] only_the_declaring_step_writes_its_"
                      f"output: control path(s) no longer flow-owned: {missing}."
                      f" The scan would pass over a set it cannot see. NOT a "
                      f"pass.", file=sys.stderr)
                return 2
            print(f"[PASS] self-test: {len(_CONTROL_PATHS)} control path(s) "
                  f"still recognised as flow-owned.")
        inv_path = Path(a.inventory) if a.inventory else \
            Path(__file__).resolve().parent / _INVENTORY_NAME
        rows = json.loads(inv_path.read_text(encoding="utf-8")).get("known", []) \
            if inv_path.exists() else []
        known = {r["key"] for r in rows}
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] only_the_declaring_step_writes_its_output: the "
              f"walk did not complete ({type(exc).__name__}: {exc}). NOT a pass.",
              file=sys.stderr)
        return 2

    print(f"  declared concrete output paths:  {denom['declared_concrete_paths']}")
    print(f"  with a write this scan resolves: "
          f"{denom['paths_with_a_resolvable_write']}"
          f"   <- the rest cannot be seen; see COVERAGE")
    print(f"  with more than one writer:       "
          f"{denom['paths_with_more_than_one_writer']}")
    print(f"  inventory rows applied:          {len(known)}")

    seen = {_key(f) for f in findings}
    new = sorted(seen - known)
    stale = sorted(known - seen)
    rc = 0
    if new:
        rc = 1
        print(f"\n[CENSUS] {len(new)} declared output path(s) have two writers:")
        for f in findings:
            if _key(f) in new:
                print(f"   {f['path']}  declared by step(s) "
                      f"{', '.join(f['declaring_steps'])}\n"
                      f"      written by: {', '.join(f['writers'])}")
        print("\n  The writer that runs last wins, and a reduced argument form "
              "leaves a\n  strictly weaker verdict wearing the declared "
              "filename. A non-declaring\n  writer must use BOTH a private "
              "directory and a different basename —\n  discovery here is a "
              "recursive glob, so a private directory alone is\n  still found.")
    if stale:
        rc = 1
        print(f"\n[CENSUS] {len(stale)} inventory row(s) match nothing:")
        for k in stale:
            print(f"   {k}")
    if rc == 0:
        print(f"[CENSUS] {len(findings)} site(s) classified, "
              f"{len(known)} recorded as known debt, "
              f"{len(new)} unrecorded. This is a count, not a "
              f"verdict — the gate is programs/only_the_declaring_step_writes_its_output.py.")
    if rc and not a.strict:
        # ONE UNBROKEN PHRASE. The rc-0 line below already says "the gate is
        # programs/<rule>.py"; this branch said the same thing in other words
        # and split the program name onto a second line, so the sentence that
        # names the refusing gate was absent from every run that found
        # something — which is exactly the run a reader needs it on.
        print("\n  CENSUS: reported, not refused. For this rule\n"
              "  the gate is programs/only_the_declaring_step_writes_its_output.py"
              " — run that for a verdict.")
        return 0
    return rc


if __name__ == "__main__":
    sys.exit(main())
