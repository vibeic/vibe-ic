#!/usr/bin/env python3
"""A source-naming field filled from a path typed into the emitter.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. The sentence below says the same thing, and prose
is not a decision: until the intent is stated where that audit looks, "wired
where it cannot block" and "nobody decided" are one record.

THIS IS A CENSUS, NOT A GATE. IT MUST NOT BE WIRED AS A BLOCKING CHECK.
=======================================================================
The gate for this rule is
`programs/provenance_value_is_resolved_not_constant.py`.
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



CENSUS — informational. The gate is `programs/provenance_value_is_resolved_not_constant.py`.

WHAT IT ASKS THE REPOSITORY
===========================
A field that states where an artefact's numbers came from must hold a value the
emitter RESOLVED, never a path typed into its own source. A constant reports
the path the author intended to read rather than the path that was read, so it
stays correct-looking when the read failed, when the layout moved, and when the
artefact is about something else entirely.

MEASURED: a published antenna report was 487 bytes byte-identical across two
different designs on two different open process kits, citing a source path the
cell does not contain. Every run of every design published the same source
claim, and the auditor's extractor reported that all four compared artefacts
declared nothing.

THE PREDICATE
=============
A finding is a write of a SOURCE-NAMING key — `source`, `source_path`,
`provenance`, `derived_from`, `read_from`, `input_path`, `origin` and kin —
whose value is a STRING CONSTANT shaped like a file path: no whitespace, and a
known artefact extension.

WHAT IS NOT A FINDING, and it is most of them
==============================================
A SPEC CITATION. `{"source": "A3.2.1 / C3.6 / C3.7"}` names a section of a
document, not a file, and a protocol synthesiser citing its specification is
correct. The first version of this predicate keyed on "contains a slash" and
returned 32 hits of which 20 were citations of exactly that shape. Requiring no
whitespace AND a known artefact extension separates them: a citation carries
spaces around its separators and ends in a section number, a path does neither.

A resolved value — `str(p)`, `p.name`, an f-string over a variable — is the
remedy and is never flagged. The rule is about the CONSTANT, not about the
field.

WHAT THE REMEDY IS
==================
Render the line from the resolved value the emitter actually opened. Where an
input was named but could not be read, record it as UNREADABLE rather than
omitting the line, so that an absent input and an unexamined one stay different
facts.

EXIT
====
  0  no source-naming field is filled from a path constant
  1  a NEW one, or a stale inventory row
  2  cannot determine
  3  bad invocation
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082

_INVENTORY_NAME = "provenance_constant_inventory.json"

_SOURCE_KEY = re.compile(
    r"^(source|source_path|source_file|provenance|derived_from|read_from"
    r"|input_path|from_file|origin|src_path)$")

_ARTEFACT_EXT = (r"(?:json|rpt|log|txt|def|gds|lef|lib|v|sv|sp|spef|sdc"
                 r"|yaml|yml|md|tcl|csv)")

#: No whitespace, and a known artefact extension. A spec citation has spaces
#: around its separators and no extension; a path has neither.
_PATH_LITERAL = re.compile(rf"^(?!.*\s)[\w./_-]+\.{_ARTEFACT_EXT}$")


def _pairs(node: ast.AST) -> List[Tuple[ast.Constant, ast.AST]]:
    if isinstance(node, ast.Dict):
        return [(k, v) for k, v in zip(node.keys, node.values)
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        t = node.targets[0]
        if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) \
                and isinstance(t.slice.value, str):
            return [(t.slice, node.value)]
    return []


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    findings: List[dict] = []
    parsed = 0
    written = 0
    base = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    if not base.is_dir():
        return findings, {"modules_parsed": 0, "source_naming_writes": 0,
                          "filled_from_a_path_constant": 0}
    for f in sorted(base.rglob("*.py")):
        if "tests" in f.parts:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        parsed += 1
        rel = f.relative_to(root).as_posix()
        for n in ast.walk(tree):
            for k, v in _pairs(n):
                if not _SOURCE_KEY.match(k.value):
                    continue
                written += 1
                if isinstance(v, ast.Constant) and isinstance(v.value, str) \
                        and _PATH_LITERAL.match(v.value.strip()):
                    findings.append({"file": rel,
                                     "line": getattr(n, "lineno", 0),
                                     "key": k.value,
                                     "constant": v.value.strip()})
    return findings, {"modules_parsed": parsed,
                      "source_naming_writes": written,
                      "filled_from_a_path_constant": len(findings)}


def _key(f: dict) -> str:
    return f"{f['file']}::{f['key']}::{f['constant']}"


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--inventory", default=None)
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
            print("[CANNOT DETERMINE] provenance_value_is_resolved_not_constant:"
                  " no repository root. NOT a pass.", file=sys.stderr)
            return 2
        findings, denom = scan(root)
        if denom["modules_parsed"] == 0:
            print("[CANNOT DETERMINE] provenance_value_is_resolved_not_constant:"
                  " no programs/ under that root. NOT a pass.", file=sys.stderr)
            return 2
        inv_path = Path(a.inventory) if a.inventory else \
            Path(__file__).resolve().parent / _INVENTORY_NAME
        rows = json.loads(inv_path.read_text(encoding="utf-8")).get("known", []) \
            if inv_path.exists() else []
        known = {r["key"] for r in rows}
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] provenance_value_is_resolved_not_constant: "
              f"the walk did not complete ({type(exc).__name__}: {exc}). NOT a "
              f"pass.", file=sys.stderr)
        return 2

    print(f"  modules parsed:              {denom['modules_parsed']}")
    print(f"  source-naming field writes:  {denom['source_naming_writes']}")
    print(f"  filled from a path constant: "
          f"{denom['filled_from_a_path_constant']}")
    print(f"  inventory rows applied:      {len(known)}")

    seen = {_key(f) for f in findings}
    new = sorted(seen - known)
    stale = sorted(known - seen)
    rc = 0
    if new:
        rc = 1
        print(f"\n[CENSUS] {len(new)} source-naming field(s) report a path the "
              f"emitter never resolved:")
        for f in findings:
            if _key(f) in new:
                print(f"   {f['file']}:{f['line']}  {f['key']} = "
                      f"{f['constant']!r}")
        print("\n  This publishes the path the author INTENDED to read. It "
              "stays correct-looking\n  when the read failed, when the layout "
              "moved, and when the artefact is about\n  another design "
              "entirely. Render it from the value actually opened, and record "
              "an\n  input named but unreadable as UNREADABLE rather than "
              "omitting the line.")
    if stale:
        rc = 1
        print(f"\n[CENSUS] {len(stale)} inventory row(s) match nothing:")
        for k in stale:
            print(f"   {k}")
    if rc == 0:
        print(f"[CENSUS] {len(findings)} site(s) classified, "
              f"{len(known)} recorded as known debt, "
              f"{len(new)} unrecorded. This is a count, not a "
              f"verdict — the gate is programs/provenance_value_is_resolved_not_constant.py.")
    if rc and not a.strict:
        print("\n  CENSUS: reported, not refused. The gate for this rule is\n"
              "  programs/provenance_value_is_resolved_not_constant.py — run that for a verdict.")
        return 0
    return rc


if __name__ == "__main__":
    sys.exit(main())
