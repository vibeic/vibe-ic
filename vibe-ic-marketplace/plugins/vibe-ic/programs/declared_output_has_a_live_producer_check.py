#!/usr/bin/env python3
"""A file found in a committed corpus is not proof the flow still writes it.

WHAT THIS ASKS
==============
For every path `flow/phase1_phase2_phase3.yaml` declares in a step's
`required_outputs`: is there still something in this SOURCE TREE that writes
it? Three answers, kept apart on purpose:

  WRITE-SITE   a write call whose rendered destination matches the declared
               pattern -- the strong answer, and the only one that dies when
               the producer dies.
  TOKEN-TRACE  no resolvable write site, but the path's own name (or, for an
               extension-only glob, its directory) still appears in the source
               that runs. A producer very likely exists behind a computed
               name; this is a WEAK answer and is reported as one.
  NO-TRACE     the declared path appears nowhere the flow could write it.

WHY THIS EXISTS
===============
Matrix dimension D3 (`outputs_produced`) claims to check that declared
`required_outputs` are genuinely written. MEASURED (mutation probe, plugin
v1.12.33): 122 of its 166 entries -- 73% -- ask whether some run tree
committed into `benchmark-data` still carries a non-empty HEAD-tracked file
matching the glob. That is a question about a corpus repository's history, and
it is answered without executing one line of plugin code.

So the probe deleted the WRITER of step A8's declared `.gds`, surgically, and
D3 stayed GREEN in every configuration: 15 passed / 53 skipped shipped, the
same 4 and then the same 7 failures under `VIBE_IC_BENCHMARK_DATA` as the
clean tree, and both of A8's dedicated guards passed individually on the
mutated tree. The artefact was still in the corpus, so the dimension still
found it. Nothing asked whether anything still made it.

This program asks that, and only that. It says nothing about whether a
produced file is CORRECT -- `flow_output_substance` owns that, given a run --
and nothing about whether two steps write the same path, which is
`only_the_declaring_step_writes_its_output`'s question. Its write-site scan
reuses that gate's own helpers rather than growing a second, differently-wrong
copy of them.

WHY IT BLOCKS ONLY ON NO-TRACE
==============================
A producer that assembles its destination at runtime (`f"L{n}_{name}.json"`)
has no literal a scanner can match, and the flow is full of them: MEASURED,
only a minority of declared paths resolve to a write site. Blocking on the
weak answer would report the ordinary way this repo writes files. Blocking on
NO-TRACE reports the case where nothing in the running source mentions the
path at all -- which is what a deleted producer leaves behind.
"""
from __future__ import annotations

import argparse
import ast
import collections
import fnmatch
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import only_the_declaring_step_writes_its_output as OWNER   # noqa: E402

FLOW_REL = OWNER.FLOW_REL
VENUE_RELS: Tuple[str, ...] = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs",
    "vibe-ic-marketplace/plugins/vibe-ic/tools",
    "tools",
)
SOURCE_SUFFIXES = (".py", ".sh", ".yaml", ".yml", ".json", ".tcl")


# --------------------------------------------------------------- rendering --
def _rendered(node: ast.AST) -> Optional[str]:
    """The destination this expression names, with `*` for its holes."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            else:
                out.append("*")
        return "".join(out)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = _rendered(node.left), _rendered(node.right)
        if left is None and right is None:
            return None
        return f"{left or '*'}/{right or '*'}"
    if isinstance(node, ast.Call):
        # `p.with_suffix(".gds")`, `p.joinpath("x")`, `os.path.join(a, "x")`
        parts = [_rendered(a) for a in node.args]
        parts = [p for p in parts if p]
        if parts:
            return "*/" + "/".join(parts) if len(parts) > 1 else "*" + parts[0]
    return None


def write_destinations(text: str) -> List[str]:
    """Every destination this module would write, rendered."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dest = _write_dest(node)
        if dest is None:
            continue
        rendered = _rendered(dest)
        if rendered:
            out.append(rendered)
    return out


def _write_dest(node: ast.Call) -> Optional[ast.expr]:
    """The expression naming WHERE this call puts bytes, or None.

    Three shapes, matching how this repo actually writes: a method on a path
    object (`p.write_text(...)`, `p.open("w")` — the destination is the
    RECEIVER, not an argument), builtin `open(dest, "w")`, and a module-level
    dest call (`json.dump(obj, dest)`), for which the sibling gate's own
    `_dest_arg` is reused rather than re-derived.
    """
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr in OWNER.WRITE_ATTRS or func.attr in OWNER.PATH_DEST_ATTRS:
            return func.value
        if func.attr == "open" and _write_mode(node):
            return func.value
        if isinstance(func.value, ast.Name):
            arg = OWNER._dest_arg(node)
            if arg is not None:
                return arg
        return None
    if isinstance(func, ast.Name) and func.id == "open" and _write_mode(node):
        return node.args[0] if node.args else None
    return None


def _write_mode(node: ast.Call) -> bool:
    mode = ""
    for a in node.args:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            mode += a.value
    for k in node.keywords:
        if (k.arg == "mode" and isinstance(k.value, ast.Constant)
                and isinstance(k.value.value, str)):
            mode += k.value.value
    return any(m in mode for m in ("w", "a", "x"))


def _matches(dest: str, declared: str) -> bool:
    """Does a rendered destination satisfy a declared (possibly glob) path?

    Both sides carry `*`: the declaration because the flow declares families
    (`phase3/analog/hardmacro/*/*.gds`), the destination because the receiver
    of `.write_text()` is usually a variable this scanner cannot resolve
    (`*/netlist.v`). So the comparison is glob-vs-glob and runs in BOTH
    directions -- a `*` on either side stands for whatever the other side
    spells out.

    The basename must match, and every LITERAL parent segment the destination
    does spell must appear in the declaration. That is deliberately the
    strongest claim the source supports: "a write call in this tree puts bytes
    in a file of this name, under any directory it does name."
    """
    d = dest.replace("\\", "/").lstrip("./")
    d_base, decl_base = d.rsplit("/", 1)[-1], declared.rsplit("/", 1)[-1]
    # A destination whose basename is pure `*` names no file: it is an
    # unresolved variable. Matching it against everything would credit every
    # declaration with a producer and make this program answer "yes" always,
    # which is the failure mode it was written to correct.
    if not re.search(r"[A-Za-z0-9]", d_base.replace("*", "")):
        return False
    if not (fnmatch.fnmatch(d_base, decl_base)
            or fnmatch.fnmatch(decl_base, d_base)):
        return False
    decl_parents = [s for s in declared.split("/")[:-1] if "*" not in s]
    dest_parents = [s for s in d.split("/")[:-1] if "*" not in s and s]
    for seg in dest_parents:
        if decl_parents and seg not in decl_parents:
            return False
    return True


def _tokens(declared: str) -> Set[str]:
    """Names whose disappearance from the source would be visible."""
    base = declared.rsplit("/", 1)[-1]
    parents = [seg for seg in declared.split("/")[:-1] if "*" not in seg]
    out: Set[str] = set()
    if "*" not in base:
        out.add(base)
        stem = base.split(".")[0]
        if len(stem) > 3:
            out.add(stem)
    else:
        out |= {s for s in re.split(r"\*+", base) if len(s) > 3}
    if not out and parents:
        out.add(parents[-1])              # extension-only glob: the directory
    return out


def _venue_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for rel in VENUE_RELS:
        venue = root / rel
        if not venue.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(venue, followlinks=False):
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", "tests", ".git")]
            for name in sorted(filenames):
                if name.startswith("test_"):
                    continue
                if name.endswith(SOURCE_SUFFIXES):
                    files.append(Path(dirpath) / name)
    return files


def _flow_commands(flow_text: str) -> str:
    """The flow minus its own `required_outputs` — declarations are not writes.

    A step that declares `reports/phase3/perc_sweep.json` AND runs
    `sweep_reach_check --report reports/phase3/perc_sweep.json` does have a
    producer, named on the command line. Reading the declaration itself as the
    producer would let every declaration prove itself.
    """
    kept, skipping = [], False
    for line in flow_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("required_outputs:"):
            skipping = True
            continue
        if skipping:
            if stripped.startswith("- ") or not stripped:
                continue
            skipping = False
        kept.append(line)
    return "\n".join(kept)


def audit(root: Path, exclude_modules: Sequence[str] = ()) -> dict:
    """The producer state of every declared output.

    `exclude_modules` removes named files from BOTH the write-site scan and
    the token blob, which is how a caller asks the question this program
    exists for: if this producer were deleted, would anything still say the
    flow writes its output? A test that cannot delete a producer cannot show
    the gate would notice one being deleted.
    """
    flow = root / FLOW_REL
    if not flow.is_file():
        raise FileNotFoundError(f"{FLOW_REL} is not present under {root}")
    declared = OWNER.declared_outputs(flow)

    excluded = set(exclude_modules)
    dests: List[Tuple[str, str]] = []
    blob_parts: List[str] = []
    for path in _venue_files(root):
        if path.name in excluded:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        blob_parts.append(text)
        if path.suffix == ".py":
            dests.extend((path.name, d) for d in write_destinations(text))
    blob_parts.append(_flow_commands(flow.read_text(encoding="utf-8")))
    blob = "\n".join(blob_parts)

    rows: Dict[str, dict] = {}
    for decl, steps in sorted(declared.items()):
        site = next(((m, d) for m, d in dests if _matches(d, decl)), None)
        if site:
            rows[decl] = {"state": "WRITE-SITE", "steps": sorted(steps),
                          "evidence": f"{site[0]}: {site[1]}",
                          "producers": sorted({m for m, d in dests
                                               if _matches(d, decl)})}
            continue
        toks = _tokens(decl)
        hit = next((t for t in sorted(toks) if t in blob), None)
        rows[decl] = {
            "state": "TOKEN-TRACE" if hit else "NO-TRACE",
            "steps": sorted(steps),
            "evidence": hit or "",
            "producers": [],
        }
    counts = collections.Counter(r["state"] for r in rows.values())
    return {"declared": len(rows), "counts": dict(counts), "rows": rows}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when a declared output has NO trace of a producer")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        report = audit(root)
    except FileNotFoundError as exc:
        print(f"CANNOT CHECK: {exc}", file=sys.stderr)
        return 2

    no_trace = sorted(p for p, r in report["rows"].items()
                      if r["state"] == "NO-TRACE")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{report['declared']} declared required_output(s) under {root}")
        for state in sorted(report["counts"]):
            print(f"  {state:<12} {report['counts'][state]}")
        for path in no_trace:
            steps = ",".join(report["rows"][path]["steps"])
            print(f"  [NO-TRACE] {path}  (declared by step {steps}) — nothing "
                  f"in the running source writes or names it")
        print("PASS" if not no_trace
              else f"{len(no_trace)} declared output(s) have no producer in the source")

    if no_trace and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
