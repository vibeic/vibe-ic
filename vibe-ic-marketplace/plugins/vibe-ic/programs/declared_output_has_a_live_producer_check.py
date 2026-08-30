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

(That is no longer the whole blocking condition. The DEMOTION recorded in the
write-site baseline is too -- see the block above `regressed` in `main`, and
the measurement that put it there. This heading survives because the reasoning
under it is still why NO-TRACE alone is not enough.)

WHERE THE BASELINE COMES FROM
=============================
`--root`, like every other input this program reads. The gate is declared as
`$PG/declared_output_has_a_live_producer_check.py --root "$ROOT" --strict`,
where `$PG` names the EXECUTABLE (pinned to the runtime tree) and `$ROOT`
names the INPUT (it follows `VIBEIC_SUBJECT_ROOT`). A baseline resolved beside
the program made those two trees disagree: the audit followed the redirect and
the record did not, so every path the RUNTIME tree had resolved was looked up
in the SUBJECT's flow, found absent, and reported as a lost write site.
MEASURED on ae4dbc091 against this gate's own fixture pair: BOTH directions
came back rc 1 carrying the same 18 `[LOST WRITE SITE]` lines, not one of
which is about the subject.

An ABSENT baseline under `--root` is REFUSED (rc 2), never read as "nothing to
compare against". Resolving the file correctly without that would trade a gate
that refused every redirected subject for one that accepted every redirected
subject -- the same defect wearing the other sign.
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

#: The baseline is an INPUT, not part of the executable, so it is resolved
#: under `--root` like every other input this program reads.
#:
#: IT USED TO BE RESOLVED BESIDE THE PROGRAM, and that made the gate answer
#: about two trees at once. `repo_hygiene_gates.sh` runs this as
#: `$PG/declared_output_has_a_live_producer_check.py --root "$ROOT"`, where
#: `$PG` is pinned to the RUNTIME tree (it names the executable) and `$ROOT`
#: follows `VIBEIC_SUBJECT_ROOT` (it names the input) — the split that lane
#: documents for `unanchored_process_kill_check` at line 533 of that script.
#: With the baseline beside the program, the audit followed the redirect and
#: the baseline did not: every path the RUNTIME tree had resolved to a write
#: site was looked up in the SUBJECT's flow, found absent, and reported as a
#: regression. MEASURED on ae4dbc091, against this gate's own fixture pair:
#: BOTH directions came back rc 1 with the same 18 `[LOST WRITE SITE]` lines,
#: none of which is about the subject. A gate that refuses every input is not
#: discriminating for the same reason one that accepts every input is not.
_INVENTORY_REL = ("vibe-ic-marketplace/plugins/vibe-ic/programs"
                  "/declared_output_write_site_baseline.json")

#: The baseline SHIPPED BESIDE THIS PROGRAM — the record of the tree the
#: EXECUTABLE came from. That is the right file for an in-process reader
#: already auditing that same tree (`test_matrix_d3_outputs_produced` audits
#: `F.PLUGIN_ROOT` and reads this, so a cell there and the shipped gate cannot
#: disagree about what a regression is), and the wrong file for `main()`, whose
#: subject is `--root`. The two are kept under two names so the distinction
#: cannot be quietly lost again.
SHIPPED_INVENTORY = (Path(__file__).resolve().parent
                     / "declared_output_write_site_baseline.json")


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


def venues_of(root: Path, plugin_root: Optional[Path] = None) -> List[Path]:
    """The directories whose source may credit a producer.

    A caller that already holds the PLUGIN root should pass it. The default
    derivation walks down from a repository root, which a caller inside a
    `cp -al` mirror of the plugin alone does not have -- MEASURED 2026-08-29:
    a test module deriving one as `PLUGIN_ROOT.parents[2]` climbed out of such
    a mirror to `/`, where this program raised an uncaught FileNotFoundError.
    """
    if plugin_root is not None:
        pr = Path(plugin_root)
        return [pr / "programs", pr / "tools", pr.parents[1] / "tools"
                if len(pr.parents) > 1 else pr / "tools"]
    return [root / rel for rel in VENUE_RELS]


def _venue_files(root: Path, plugin_root: Optional[Path] = None) -> List[Path]:
    files: List[Path] = []
    for venue in venues_of(root, plugin_root):
        if not venue.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(venue, followlinks=False):
            # `gate_fixtures` joins the excluded set for the same reason
            # `tests` is in it, and it was measured, not guessed: on
            # 2026-08-29 `tools/ci/gate_fixtures/report_basis_matches_its_
            # session_inputs.py` was the SOLE credited producer of 23 declared
            # flow outputs -- drc_signoff.rpt, lvs.rpt, erc.rpt, ir_drop.rpt
            # among them. A mutation fixture writes those paths to BUILD a
            # subject tree; nothing in the flow is thereby shown to write them.
            # Crediting it made 23 outputs read as produced by a file whose
            # whole purpose is to be synthetic.
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", "tests", ".git",
                                        "gate_fixtures")]
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


def audit(root: Path, exclude_modules: Sequence[str] = (),
          flow: Optional[Path] = None,
          plugin_root: Optional[Path] = None) -> dict:
    """The producer state of every declared output.

    `exclude_modules` removes named files from BOTH the write-site scan and
    the token blob, which is how a caller asks the question this program
    exists for: if this producer were deleted, would anything still say the
    flow writes its output? A test that cannot delete a producer cannot show
    the gate would notice one being deleted.
    """
    flow = Path(flow) if flow is not None else root / FLOW_REL
    if not flow.is_file():
        raise FileNotFoundError(f"{flow} is not a readable flow document")
    declared = OWNER.declared_outputs(flow)

    excluded = set(exclude_modules)
    dests: List[Tuple[str, str]] = []
    blob_parts: List[str] = []
    for path in _venue_files(root, plugin_root):
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
    ap.add_argument("--flow", help="the flow document to read (default: under --root)")
    ap.add_argument("--plugin-root", help="the plugin whose source may credit a producer")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on a NO-TRACE output or a lost write site")
    ap.add_argument("--inventory",
                    help="the shrink-only write-site baseline (default: under --root)")
    ap.add_argument("--record", action="store_true",
                    help="rewrite the baseline from this tree; never automatic")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        report = audit(root,
                       flow=Path(args.flow) if args.flow else None,
                       plugin_root=Path(args.plugin_root) if args.plugin_root else None)
    except FileNotFoundError as exc:
        print(f"CANNOT CHECK: {exc}", file=sys.stderr)
        return 2

    # The baseline is read from the SUBJECT (see `_INVENTORY_REL`), and its
    # ABSENCE IS REFUSED rather than read as "nothing to compare against".
    # That is the same rule the unreadable case already had, and it has to be
    # the same rule: the blocking condition of this gate is the DEMOTION, so a
    # run with no baseline checks nothing that can fire. Resolving the baseline
    # under `--root` without this would turn a gate that refused every
    # redirected subject into one that silently accepted every redirected
    # subject — the other half of the same defect.
    inv_path = Path(args.inventory) if args.inventory else root / _INVENTORY_REL
    inventory = None
    if not inv_path.is_file():
        if args.record:
            inventory = None          # --record writes it; see below
        else:
            print(f"CANNOT CHECK: no write-site baseline at {inv_path}. This "
                  f"gate blocks on a path LOSING its producer, which is a "
                  f"comparison against that file; with no baseline there is "
                  f"nothing to compare and a PASS would certify nothing. "
                  f"Point --inventory at one, or rebuild it with --record.",
                  file=sys.stderr)
            return 2
    else:
        try:
            inventory = json.loads(inv_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"CANNOT CHECK: {inv_path} is not readable JSON ({exc}). An "
                  f"unreadable baseline is refused, never treated as empty.",
                  file=sys.stderr)
            return 2

    no_trace = sorted(p for p, r in report["rows"].items()
                      if r["state"] == "NO-TRACE")

    # BLOCKING ON `NO-TRACE` ALONE IS BLOCKING ON NOTHING.
    #
    # MEASURED 2026-08-29, by deleting the sole producer of a real declared
    # output (`crc_vector_gen.py`'s `.sby` write) and then, using this
    # program's own `exclude_modules` hook, simulating the deletion of the
    # ENTIRE sole producer for all 34 single-producer paths: not one reached
    # NO-TRACE. Every one landed in TOKEN-TRACE, because the path's name still
    # appears in the source -- written there by its READERS. The strict verdict
    # stayed PASS while a real producer was gone.
    #
    # So the blocking condition is the DEMOTION, recorded shrink-only: a path
    # this repository has resolved to a write site must keep one. That is a
    # fact about THIS tree, which is why it lives in an inventory beside the
    # program rather than in a predicate that cannot fire.
    regressed = []
    if inventory is not None:
        was = set(inventory.get("write_site") or ())
        for path in sorted(was):
            row = report["rows"].get(path)
            if row is None:
                regressed.append((path, "no longer declared by the flow"))
            elif row["state"] != "WRITE-SITE":
                regressed.append((path, f"demoted to {row['state']}"))
    report["regressed"] = [{"path": p, "why": w} for p, w in regressed]
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
        for row in report["regressed"]:
            print(f"  [LOST WRITE SITE] {row['path']} — {row['why']}; this "
                  f"repository resolved it to a write site and no longer does")
        bad = len(no_trace) + len(report["regressed"])
        print("PASS" if not bad
              else f"{bad} declared output(s) lost or never had a producer")

    if args.record:
        inv_path.parent.mkdir(parents=True, exist_ok=True)
        inv_path.write_text(json.dumps({
            "_comment": ("Declared required_outputs this tree resolves to a real "
                         "write site. SHRINK-ONLY is the wrong word: this set may "
                         "GROW freely, and a path LEAVING it is the regression. "
                         "Rewrite only with --record, and only when the loss is "
                         "intended and explained in the commit."),
            "write_site": sorted(p for p, r in report["rows"].items()
                                 if r["state"] == "WRITE-SITE"),
        }, indent=2) + "\n", encoding="utf-8")
        print(f"recorded {inv_path}")
        return 0

    if (no_trace or report["regressed"]) and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
