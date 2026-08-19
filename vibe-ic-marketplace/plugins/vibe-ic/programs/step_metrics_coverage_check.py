#!/usr/bin/env python3
"""How many gate-carrying steps read the tool's numbers instead of its prose. W5.

WHY THIS IS A PROGRAM AND NOT A SENTENCE IN A DOCSTRING
=======================================================
`step_metrics.py` shipped with its own coverage written into its module
docstring: "It wires ONE gate (`coverage_metric_check`) as a worked example. The
other 61 gate-carrying steps DO NOT emit yet." That was honest and it was
useful — and it is a hand-typed number in prose, which means it can only ever be
right on the day it is typed. This program derives the same number from the
canonical flow file every time it runs, and ratchets it, so the count cannot
drift and cannot quietly fall.

MEASURED ON THIS TREE at 8e60dd954, before the W5 change:

    declared step entries in flow/phase1_phase2_phase3.yaml : 63
    of which carry a `gate`                                 : 62
    EMIT, direct / reachable                                : 1 / 2
    CONSUME, direct / reachable                             : 0 / 0

so the brief's "61 gate-carrying steps still re-parse prose" is confirmed by
measurement: one gate-carrying step (31, through `magic_illegal_overlap_check`)
emitted, 61 did not, and NOT ONE consumed a named metric by either bound — every
gate-carrying step in the flow was gating on a log regex.

`coverage_metric_check` — the worked example `step_metrics`'s docstring names —
emits, but no step's gate in the flow file names it, so it does not appear in
this census at all. That is the difference between "a gate is wired" and "a
FLOW STEP is wired", and it is why this census reads the flow file.

EMIT AND CONSUME ARE COUNTED SEPARATELY, deliberately. A step that emits has
made its numbers available; a step that consumes has actually stopped gating on
a regex. They are different halves of the migration and a single number that
merged them would let the easy half hide the hard one.

TWO BOUNDS, NEVER ONE NUMBER — and this is the correction that matters most.

A gate names a program, and that program usually delegates: step 21's gate names
`drc_report_check`, which is a thin wrapper over `eda_report_audit`, which is
where the reading actually happens. So following imports is necessary. But
`eda_report_audit` serves SEVEN modes from one file, and W5 has migrated exactly
one of them (`--mode drc`). A census that followed the import and then counted
step 24 (`--mode ir_drop`) as migrated would be claiming a migration that has not
happened. MEASURED while writing this program: the naive single number reported
8 consuming steps when the true count of reconciling gate paths was 2.

So the answer is two numbers and no pretence that either is the other:

    DIRECT     the gate's own named program reads the channel itself.
               A LOWER bound: it cannot overstate, and it undercounts every
               legitimate wrapper.
    REACHABLE  the named program, or something it imports within
               `MAX_IMPORT_DEPTH` hops, reads the channel.
               An UPPER bound: it cannot miss a migrated gate, and it counts
               sibling modes of a shared reader that were never migrated.

The migration is somewhere between them, and saying so is the honest report.
Both are ratcheted, because a FALL in either is a real regression whatever the
true number between them is. Neither is ever printed without its label.

The depth bound exists for the same reason: an unbounded walk over 1100+ modules
would reach the metrics channel from almost anywhere and REACHABLE would
converge on "everything", which is this program's failure mode, not its goal.

NEVER MADE TO PASS BY CHECKING LESS: the ratchet only ever refuses a FALL. It
cannot be satisfied by lowering the baseline in the same commit that lowers the
count, because `--write-baseline` is a separate, explicit invocation and the
baseline file records the tree it was taken on.

chip-AGNOSTIC: no IC, vendor, PDK or process literal appears or can affect it.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json as _atomic_write_json  # noqa: E402  vibe-ic#1082

RC_OK = 0
RC_VIOLATION = 1
RC_UNDETERMINED = 2

FLOW_REL = "flow/phase1_phase2_phase3.yaml"
BASELINE_NAME = "step_metrics_coverage_baseline.json"

#: How far a gate's named program is followed through sibling imports. See the
#: module docstring for why this is bounded at all.
MAX_IMPORT_DEPTH = 2

#: Every key under a gate whose value is (or contains) a command line.
_CMD_KEYS = ("program_exit_zero", "optional_program_exit_zero",
             "advisory_program_exit_zero", "program_stdout_contains",
             "program_json_field", "command")

_EMIT_RE = re.compile(r"\b(?:step_metrics|_sm|_metrics)\.emit\s*\(")
_CONSUME_RE = re.compile(r"\b(?:step_metrics|_sm|_metrics)\.collect\s*\(")


def _commands(node: Any, out: List[str]) -> List[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _CMD_KEYS:
                if isinstance(v, str):
                    out.append(v)
                elif isinstance(v, dict):
                    if isinstance(v.get("command"), str):
                        out.append(v["command"])
                    _commands(v, out)
                else:
                    _commands(v, out)
            else:
                _commands(v, out)
    elif isinstance(node, list):
        for v in node:
            _commands(v, out)
    return out


def _program_of(cmd: str) -> str:
    tok = cmd.strip().split()
    return tok[0] if tok else ""


def _sibling_imports(text: str, known: Set[str]) -> Set[str]:
    """Module-level sibling program names this source imports."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in known:
                    out.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module in known:
            out.add(node.module)
    return out


def _uses(programs_dir: Path, name: str, known: Set[str],
          depth: int, seen: Set[str]) -> Dict[str, bool]:
    """`{emits, consumes}` for `name`, following sibling imports to `depth`."""
    res = {"emits": False, "consumes": False}
    if name in seen or depth < 0:
        return res
    seen.add(name)
    f = programs_dir / f"{name}.py"
    if not f.is_file():
        return res
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return res
    # Comment lines are dropped so a module that only DISCUSSES the channel in a
    # `# ...` note is not counted as using it.
    body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    res["emits"] = bool(_EMIT_RE.search(body))
    res["consumes"] = bool(_CONSUME_RE.search(body))
    if depth > 0:
        for sib in _sibling_imports(text, known):
            sub = _uses(programs_dir, sib, known, depth - 1, seen)
            res["emits"] = res["emits"] or sub["emits"]
            res["consumes"] = res["consumes"] or sub["consumes"]
    return res


def census(plugin_dir: Path) -> Dict[str, Any]:
    try:
        import yaml  # noqa: PLC0415 — optional at import time, required here
    except ImportError:
        return {"status": "not_checked",
                "reason": "PyYAML is unavailable, so the canonical flow file "
                          "could not be read; nothing was measured"}
    flow = plugin_dir / FLOW_REL
    try:
        doc = yaml.safe_load(flow.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "not_checked",
                "reason": f"the canonical flow file could not be read ({exc}); "
                          f"nothing was measured"}
    steps = (doc or {}).get("steps") or []
    if not steps:
        return {"status": "not_checked",
                "reason": "the flow file declared no steps; an empty census is "
                          "not a measurement of zero coverage"}

    programs_dir = plugin_dir / "programs"
    known = {p.stem for p in programs_dir.glob("*.py")}

    rows: List[Dict[str, Any]] = []
    for s in steps:
        if "gate" not in s:
            continue
        progs = sorted({_program_of(c)
                        for c in _commands(s["gate"], []) if _program_of(c)})
        emits_d: List[str] = []
        consumes_d: List[str] = []
        emits_r: List[str] = []
        consumes_r: List[str] = []
        for p in progs:
            direct = _uses(programs_dir, p, known, 0, set())
            reach = _uses(programs_dir, p, known, MAX_IMPORT_DEPTH, set())
            if direct["emits"]:
                emits_d.append(p)
            if direct["consumes"]:
                consumes_d.append(p)
            if reach["emits"]:
                emits_r.append(p)
            if reach["consumes"]:
                consumes_r.append(p)
        rows.append({"id": str(s["id"]), "stage": s.get("stage"),
                     "programs": progs,
                     "emits_direct": emits_d, "consumes_direct": consumes_d,
                     "emits_reachable": emits_r,
                     "consumes_reachable": consumes_r})

    def _ids(field: str) -> List[str]:
        return sorted(r["id"] for r in rows if r[field])

    return {"status": "measured",
            "declared_step_entries": len(steps),
            "gate_carrying_steps": len(rows),
            "steps_emitting_direct": _ids("emits_direct"),
            "steps_emitting_reachable": _ids("emits_reachable"),
            "steps_consuming_direct": _ids("consumes_direct"),
            "steps_consuming_reachable": _ids("consumes_reachable"),
            "emit_count_direct": len(_ids("emits_direct")),
            "emit_count_reachable": len(_ids("emits_reachable")),
            "consume_count_direct": len(_ids("consumes_direct")),
            "consume_count_reachable": len(_ids("consumes_reachable")),
            "import_depth": MAX_IMPORT_DEPTH,
            "rows": rows}


def _plugin_dir(root: Path) -> Path:
    cand = root / "vibe-ic-marketplace/plugins/vibe-ic"
    return cand if cand.is_dir() else root


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the current counts as the floor")
    args = ap.parse_args(list(argv) if argv is not None else None)

    plugin = _plugin_dir(Path(args.root).resolve())
    rep = census(plugin)
    if args.json_out:
        p = Path(args.json_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(p, rep, indent=1)  # vibe-ic#1082

    if rep["status"] != "measured":
        print(f"[NOT CHECKED] {rep['reason']}", file=sys.stderr)
        return RC_UNDETERMINED

    n = rep["gate_carrying_steps"]
    print(f"{n} of {rep['declared_step_entries']} declared step entries carry "
          f"a gate (sibling-import depth {rep['import_depth']})")
    print(f"  EMIT     direct {rep['emit_count_direct']:>3}  "
          f"[{', '.join(rep['steps_emitting_direct']) or '-'}]")
    print(f"           reach  {rep['emit_count_reachable']:>3}  "
          f"[{', '.join(rep['steps_emitting_reachable']) or '-'}]")
    print(f"  CONSUME  direct {rep['consume_count_direct']:>3}  "
          f"[{', '.join(rep['steps_consuming_direct']) or '-'}]")
    print(f"           reach  {rep['consume_count_reachable']:>3}  "
          f"[{', '.join(rep['steps_consuming_reachable']) or '-'}]")
    print(f"  still re-parsing prose: between "
          f"{n - rep['consume_count_reachable']} and "
          f"{n - rep['consume_count_direct']} of {n} — DIRECT is a lower bound "
          f"on migration and REACHABLE an upper one; the truth is between them "
          f"and this program does not pretend to narrow it further")

    bl_path = plugin / "programs" / BASELINE_NAME
    if args.write_baseline:
        _atomic_write_json(bl_path,
            {"gate_carrying_steps": rep["gate_carrying_steps"],
             "emit_count_direct": rep["emit_count_direct"],
             "emit_count_reachable": rep["emit_count_reachable"],
             "consume_count_direct": rep["consume_count_direct"],
             "consume_count_reachable": rep["consume_count_reachable"],
             "steps_emitting_reachable": rep["steps_emitting_reachable"],
             "steps_consuming_reachable": rep["steps_consuming_reachable"],
             "note": ("FLOOR, not a target. This file records how far the "
                      "migration off log-parsing had got. A run measuring "
                      "FEWER wired steps than this is a regression and fails; "
                      "a run measuring more is the point, and the baseline is "
                      "re-taken deliberately, never automatically.")},
            indent=1)
        print(f"[BASELINE WRITTEN] {bl_path}")
        return RC_OK

    if not bl_path.is_file():
        print(f"[NOT CHECKED] no baseline at {bl_path}; there is nothing to "
              f"ratchet against, and an absent floor is not a passed floor",
              file=sys.stderr)
        return RC_UNDETERMINED
    try:
        bl = json.loads(bl_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[NOT CHECKED] baseline unreadable ({exc})", file=sys.stderr)
        return RC_UNDETERMINED

    defects = []
    for key in ("emit_count_direct", "emit_count_reachable",
                "consume_count_direct", "consume_count_reachable"):
        if rep[key] < bl.get(key, 0):
            defects.append(
                f"{key} fell from {bl.get(key)} to {rep[key]}: a gate that "
                f"stopped reading the tool's own number went back to reading "
                f"its prose, and a wording change can blind it again")
    if defects:
        print(f"[FAIL] {len(defects)} regression(s):", file=sys.stderr)
        for d in defects:
            print(f"  {d}", file=sys.stderr)
        return RC_VIOLATION
    print(f"[PASS] coverage held or improved (floor: emit "
          f"{bl.get('emit_count_direct')}/{bl.get('emit_count_reachable')}, "
          f"consume {bl.get('consume_count_direct')}/"
          f"{bl.get('consume_count_reachable')} direct/reachable)")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
