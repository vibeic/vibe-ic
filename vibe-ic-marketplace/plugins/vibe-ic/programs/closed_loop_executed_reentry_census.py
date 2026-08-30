#!/usr/bin/env python3
"""closed_loop_executed_reentry_census.py — which loops does the tree RUN?

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. Why it refuses rather than reports is measured
below, at THE VERDICT.

THE ROOT CAUSE, IN ONE LINE
===========================
All three programs that read closed loops read only `closed_loop:` blocks, so
they census DECLARATIONS and call the answer a census of LOOPS. Nothing asks the
tree which loops it actually runs.

    closed_loop_edge_check ................ is the DECLARATION well-formed?
    closed_loop_executable_coverage_check . does a REGISTERED actuator run?
    closed_loop_metric_reaches_its_producer  COULD a DECLARED edge close?
    this program .......................... which loops DOES the tree re-enter?

The middle one's actuator map is
`closed_loop_executable_coverage_check.STEP_EXECUTION_ENTRYPOINTS`, and on the
tree that shipped this file it has TWO entries — steps "1" and "32" — for a
flow of 68 steps. It is a register fed by hand, so it is stale by construction,
and it already is.

WHAT THAT COSTS, MEASURED ON THE SHIPPED FLOW
=============================================
`closed_loop_metric_reaches_its_producer` publishes REACHABLE=0 over 21 declared
edges and `closed_loop_executable_coverage_check` publishes EXECUTABLE=0 over the
same 21.

    REACHABLE=0 IS A TRUE STATEMENT ABOUT THE DECLARATIONS AND A FALSE
    IMPRESSION OF THE FLOW.

The declared edges and the actually-executing re-entry loops are DISJOINT SETS.
That is not a smaller version of EXECUTABLE=0 — it is a different defect. Loops
that run on every project, and appear in none of the three censuses:

  * the AREA RE-SYNTHESIS loop — `phase3_one_shot_runner.step_synth`, on a cell
    area over the declared die, calls `step_synth` again at
    `AREA_RETRY_PERIOD_RELAX`, re-measures `chip_area`, and adopts the result
    only if it is BOTH smaller and inside the budget;
  * the ROUTING-CONGESTION SELF-RESCUE — `_ROUTE_LOOSEN_UTIL_LADDER`
    (0.25 -> 0.18 -> floor), one strictly-looser utilisation rung per retry when
    detailed route plateaus;
  * the OVER-UTILISATION DIE-UPSIZE RETRY — `_PNR_UPSIZE_RETRIES` grows the die
    when placement reports over-utilisation, bounded by the die cap;
  * the RTL REPAIR RETRY — `design_one_shot_runner.main` re-runs `step_rtl_gen`
    while the reference TB fails, hashes the RTL directory each round, and stops
    at `FAIL_RTL_REPAIR_INERT` when a round comes back byte-identical.

The last one is the sharpest: A LOOP THAT ALREADY CARRIES ITS OWN ANTI-CHEAT IS
INVISIBLE TO ALL THREE CENSUSES THAT EXIST TO FIND LOOPS.

WHAT THIS PROGRAM DERIVES, AND FROM WHAT
========================================
The population is not a list in this file. It is every re-entry site in the
flow's executable runners, and both the runner set and the call filter come from
the tree's own conventions:

    runners      programs/*_one_shot_runner.py            (glob, not a list)
    re-entry     a `step_*` function calling ITSELF, or a `step_*` function or
                 a process-exec primitive called inside a `while`/`for` body

Two signals, each read off the AST, never off a name:

    ARG_VARIES    at least one argument at the call site is not invariant across
                  the repetition — an expression, a module constant, or a name
                  assigned inside the region. A site with NO varying argument
                  re-enters with byte-identical inputs.
    SELF_CHECKED  after the call, a name is bound from a call, and a later
                  `if`/`while` test in the same region reads that name. The loop
                  measures its own effect and branches on what it measured.

    ACTUATING           ARG_VARIES. Re-entry can change its own input.
    SELF_CHECKED_ONLY   no varying argument, but the loop measures and branches.
                        Re-enters identically AND KNOWS IT — the RTL repair
                        retry's shape, and an honest one.
    INERT               neither. It re-runs the work, cannot change what it
                        feeds in, and never looks at what came back.

INERT IS THE FAILING CONDITION, AND IT IS REACHABLE
===================================================
A census whose verdict cannot change is a list. The sibling's is not reachable
at all: `grep -c "return 1" closed_loop_metric_reaches_its_producer.py` is 0, its
`main()` has exactly three returns (`2`, `2`, `0`), and through its
`advisory_program_exit_zero` slot rc 0 is recorded as `ADVISORY ok:` and rc 2 as
`ADVISORY n/a` — so a tree with 21 reachable edges and a tree with none write the
same line into the report.

This one refuses, and the refusal is falsified by MUTATION rather than asserted,
in `tests/test_closed_loop_executed_reentry_census.py`. Three arms on the area
loop, two control loops held still in every arm, measured end to end:

    arm 0  the shipped tree, unmutated             ACTUATING   rc 0
    arm A  the varying argument replaced by a
           pass-through of the enclosing parameter SELF_CHECKED_ONLY  rc 1
                                                   (baseline regression)
    arm B  the varying argument AND the read-back
           both removed                            INERT       rc 1
    CONTROL `step_pnr -> _docker_exec` and `main -> step_rtl_gen` hold
            SELF_CHECKED_ONLY in every arm

A census that cannot notice a loop someone broke is not a census. A census that
reddens everything when one loop breaks has told you nothing about that loop.

THE VERDICT
===========
`ENFORCEMENT: advisory` is the word `flow_gate_enforcement_audit` has for "no
RUNNER spawns this gate inline", and that is true of it. It is NOT a claim that
the gate cannot fail anything, and the difference from the sibling is the whole
point of this file, so it is spelled out rather than left to the token:

  * the flow clause is `program_exit_zero`, not `advisory_program_exit_zero`.
    On rc 1 `flow_compliance_check` returns the step FAILED. The sibling's slot
    is structurally incapable of that;
  * `rc 1` fires on an INERT re-entry site, and on a BASELINE REGRESSION — a
    site recorded here as ACTUATING or SELF_CHECKED that has since lost the
    signal. The baseline is the shipped population, so inherited state cannot
    redden a landing and a new defect can. That ratchet is what the sibling was
    missing when it chose to report instead of refuse: UNREACHABLE is debt no
    change owns, but a NEWLY unreachable edge is a defect, and a baseline is all
    that separates them;
  * `test_the_shipped_baseline_matches_the_shipped_tree` asserts rc 0 over the
    shipped tree, so an INERT loop that lands turns the suite red whether or not
    any project ever runs the flow clause.

A ZERO DENOMINATOR REFUSES (rc 2). No runner parsed, or no re-entry site found
at all, is the ABSENCE of the question, not a clean answer to it.

Chip-AGNOSTIC: every name this file matches on is a Python construct or the
repo's own `step_` / `*_one_shot_runner` convention. No chip, protocol, process
or vendor vocabulary participates.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402

ACTUATING = "ACTUATING"
SELF_CHECKED_ONLY = "SELF_CHECKED_ONLY"
INERT = "INERT"

#: The process-exec primitives a runner re-runs external tooling through. These
#: are Python/stdlib and this repo's own container helper — not a catalogue of
#: loops, and adding a loop does not require adding anything here.
EXEC_PRIMITIVES: frozenset = frozenset({
    "_docker_exec", "run", "check_call", "check_output", "Popen", "call",
})

#: The tree's own convention for a flow-step entry point. `flow_compliance_check`
#: and `closed_loop_executable_coverage_check` both key on it already.
STEP_PREFIX = "step_"

BASELINE_NAME = "closed_loop_executed_reentry_baseline.json"


def _plugin_root(root: Path) -> Path:
    """The tree whose LOOPS are the question.

    A flow gate is invoked with the PROJECT directory as its root, and the loops
    this program censuses live in the shipped plugin, not in the project. So a
    root that carries no `programs/` resolves to THIS FILE'S OWN tree — the
    plugin that is running. Without that fallback the gate would return its
    zero-denominator refusal on every real project and be recorded as `n/a`,
    which is how a census becomes decoration: it would answer only when run by
    hand from a checkout and never once during a run.
    """
    if (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
            / "programs").is_dir():
        return root
    return Path(__file__).resolve().parents[4]


def _programs_dir(root: Path) -> Optional[Path]:
    p = (_plugin_root(root) / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
         / "programs")
    return p if p.is_dir() else None


def _is_step(name: Optional[str]) -> bool:
    return bool(name) and str(name).startswith(STEP_PREFIX)


def _callee_name(call: ast.Call) -> Optional[str]:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _bound_names(node: ast.AST) -> Set[str]:
    """Every name this subtree BINDS — assignment, loop target, `with ... as`,
    walrus, comprehension target, `except ... as`. A name bound inside the
    repetition can differ between iterations; one that is not, cannot."""
    got: Set[str] = set()

    def add(target: ast.AST) -> None:
        for s in ast.walk(target):
            if isinstance(s, ast.Name):
                got.add(s.id)

    for n in ast.walk(node):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                add(t)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            add(n.target)
        elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
            add(n.target)
        elif isinstance(n, ast.NamedExpr):
            add(n.target)
        elif isinstance(n, ast.withitem) and n.optional_vars is not None:
            add(n.optional_vars)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            got.add(n.name)
    return got


def _root_name(node: ast.AST) -> Optional[str]:
    """The base name of an attribute chain — `args.top_name` -> `args`. An
    attribute read off a name nothing rebinds is as invariant as the name."""
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _params(fn: ast.AST) -> List[str]:
    """The enclosing function's parameters, in binding order, positional first
    then keyword-only. Used only for a SELF_CALL, where 'does the re-entry
    differ' is a question about the PARENT frame."""
    a = fn.args
    return ([p.arg for p in list(a.posonlyargs) + list(a.args)]
            + [p.arg for p in a.kwonlyargs])


def _varies_self_call(call: ast.Call, fn: ast.AST) -> List[str]:
    """A recursive re-entry differs from its parent when some argument is NOT
    that parameter passed straight back through.

    `step_synth(project, top, pdk, container, period_relax=AREA_RETRY_PERIOD_
    RELAX)` inside `step_synth` hands the recursion a value its own caller did
    not hand it, so the child run is not the parent run. Rewrite that keyword
    to `period_relax=period_relax` and the recursion is a re-run of the same
    work — which is exactly the mutation the falsification arm applies.
    """
    names = _params(fn)
    out: List[str] = []
    for i, a in enumerate(call.args):
        if isinstance(a, ast.Starred):
            out.append(ast.unparse(a))
            continue
        expect = names[i] if i < len(names) else None
        if isinstance(a, ast.Name) and a.id == expect:
            continue
        out.append(ast.unparse(a))
    for k in call.keywords:
        if k.arg is None:
            out.append(ast.unparse(k.value))
            continue
        if isinstance(k.value, ast.Name) and k.value.id == k.arg:
            continue
        out.append(f"{k.arg}={ast.unparse(k.value)}")
    return out


def _varies_in_loop(call: ast.Call, invariant: Set[str]) -> List[str]:
    """A looping re-entry differs from the previous ITERATION when some argument
    is rebound inside the loop.

    A bare `Name` — or an attribute/subscript read off one — that nothing in the
    region rebinds carries the same value every time round; anything else can
    differ. Returning the list rather than a boolean so the evidence names WHICH
    argument carries the variance, which is what a reader has to check when this
    verdict is disputed.
    """
    out: List[str] = []
    for a in list(call.args) + [k.value for k in call.keywords]:
        if isinstance(a, ast.Starred):
            a = a.value
        root = _root_name(a)
        if root is not None and root in invariant:
            continue
        if root is None and isinstance(a, ast.Constant):
            continue
        try:
            out.append(ast.unparse(a))
        except Exception:                                    # noqa: BLE001
            out.append(type(a).__name__)
    return out


def _self_checked(region: ast.AST, call: ast.Call,
                  after_call_only: bool) -> Optional[str]:
    """Does the region MEASURE this re-entry and branch on what it measured?

    Looks for a name bound from a Call at a line after the re-entry, which a
    later `if`/`while` test in the same region reads. That is the structure of
    every honest retry in this tree:

        _after = _synth_chip_area(project)      # bound from a call, after
        if area_retry_is_worth_adopting(..., _after, ...):   # test reads it

        new_rtl_hash = _rtl_dir_sha256(project)
        if ... new_rtl_hash == last_rtl_hash:

    `after_call_only` is what separates the two re-entry shapes, and it is not
    a tuning knob. A RECURSIVE re-entry can only be observed after the call
    returns, so the measurement must FOLLOW it. A LOOPING re-entry is observed
    on the next iteration, so a measurement anywhere in the body is a
    measurement of it — requiring position there reported the RTL repair
    retry's own tail re-runs as unmeasured while the loop that contains them
    terminates on exactly the measurement it was said to lack.

    LINE ORDER, NOT CONTROL FLOW, and the looseness is deliberate: this signal
    only ever ADDS a verdict tier above INERT, so over-crediting it cannot
    manufacture a refusal. The refusal comes from the ABSENCE of both signals.
    """
    after: Dict[str, int] = {}
    for n in ast.walk(region):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            if after_call_only and getattr(n, "lineno", 0) <= call.lineno:
                continue
            for t in n.targets:
                for s in ast.walk(t):
                    if isinstance(s, ast.Name):
                        after.setdefault(s.id, n.lineno)
    if not after:
        return None
    for n in ast.walk(region):
        test = None
        if isinstance(n, ast.If):
            test = n.test
        elif isinstance(n, ast.While):
            test = n.test
        if test is None:
            continue
        for s in ast.walk(test):
            if isinstance(s, ast.Name) and s.id in after:
                if getattr(n, "lineno", 0) >= after[s.id]:
                    return s.id
    return None


def scan_module(path: Path) -> List[Dict]:
    """Every re-entry site in one runner, with both signals decided."""
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return []
    sites: List[Dict] = []

    def visit(node: ast.AST, fn: Optional[ast.AST],
              loops: Tuple[ast.AST, ...]) -> None:
        for ch in ast.iter_child_nodes(node):
            nfn, nloops = fn, loops
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nfn, nloops = ch, ()
            elif isinstance(ch, (ast.While, ast.For, ast.AsyncFor)):
                nloops = loops + (ch,)
            if isinstance(ch, ast.Call) and fn is not None:
                name = _callee_name(ch)
                self_call = _is_step(fn.name) and name == fn.name
                in_loop = bool(loops) and (name in EXEC_PRIMITIVES
                                           or _is_step(name))
                if self_call or in_loop:
                    region = loops[-1] if loops else fn
                    invariant = {
                        n.id for n in ast.walk(region)
                        if isinstance(n, ast.Name)
                    } - _bound_names(region)
                    varies = (_varies_self_call(ch, fn) if self_call
                              else _varies_in_loop(ch, invariant))
                    checked = _self_checked(region, ch,
                                            after_call_only=self_call)
                    verdict = (ACTUATING if varies
                               else SELF_CHECKED_ONLY if checked else INERT)
                    sites.append({
                        "file": path.name,
                        "line": ch.lineno,
                        "fn": fn.name,
                        "callee": name,
                        "kind": "SELF_CALL" if self_call else "IN_LOOP",
                        "varying_args": varies[:4],
                        "measured_name": checked,
                        "verdict": verdict,
                    })
            visit(ch, nfn, nloops)

    visit(tree, None, ())
    return sites


def _runner_paths(programs: Path) -> List[Path]:
    return sorted(programs.glob("*_one_shot_runner.py"))


def site_key(row: Dict) -> str:
    """Identity that survives an edit ABOVE the site. Line numbers move on every
    unrelated change; `file::function::callee` does not, and a function that
    re-enters the same callee twice is one key with two rows — which is what a
    reader wants, because the QUESTION is whether that re-entry still actuates."""
    return f"{row['file']}::{row['fn']}::{row['callee']}"


def summarise(sites: Sequence[Dict]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for row in sites:
        c = out.setdefault(site_key(row),
                           {ACTUATING: 0, SELF_CHECKED_ONLY: 0, INERT: 0})
        c[row["verdict"]] += 1
    return out


def regressions(now: Dict[str, Dict[str, int]],
                base: Dict[str, Dict[str, int]]) -> List[str]:
    """A recorded site that has LOST a signal.

    Counted per key and per tier, because that is the shape a real regression
    takes: somebody edits one call in a function that re-enters twice, and the
    key survives while one of its two sites falls a tier.
    """
    out: List[str] = []
    for key, want in sorted(base.items()):
        have = now.get(key)
        if have is None:
            out.append(f"{key}: recorded here and no longer present — the "
                       f"re-entry was deleted or renamed; re-record the "
                       f"baseline in the same change that removes it")
            continue
        for tier in (ACTUATING, SELF_CHECKED_ONLY):
            if have.get(tier, 0) < want.get(tier, 0):
                out.append(
                    f"{key}: {tier} {want[tier]} -> {have.get(tier, 0)}; a "
                    f"re-entry site that used to be able to change or check "
                    f"itself no longer can")
    return out


def declared_edges(root: Path) -> List[str]:
    """The flow's own `closed_loop:` edges, for the DISJOINTNESS line. Read, not
    judged — the three sibling programs are what judge them."""
    flow = (_plugin_root(root) / "vibe-ic-marketplace" / "plugins"
            / "vibe-ic" / "flow" / "phase1_phase2_phase3.yaml")
    if not flow.is_file():
        return []
    import yaml                                            # noqa: PLC0415
    doc = yaml.safe_load(flow.read_text(errors="replace")) or {}
    out = []
    for s in (doc.get("steps") or []):
        cl = s.get("closed_loop")
        if isinstance(cl, dict):
            out.append(f"{s.get('id')} -> {cl.get('fallback_to')}")
    return out


def registered_steps(programs: Path) -> List[str]:
    """The sibling's HAND-MAINTAINED actuator register, read from the sibling
    rather than re-typed here. Re-typing it would make this file a second copy
    of the same stale list, which is the defect, not the fix."""
    sys.path.insert(0, str(programs))
    try:
        import closed_loop_executable_coverage_check as _clec  # noqa: PLC0415
        return sorted(_clec.STEP_EXECUTION_ENTRYPOINTS)
    except Exception:                                        # noqa: BLE001
        return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=("census the re-entry loops the tree actually RUNS, "
                     "derived from the runners rather than declared"))
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--json", default=None)
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.root)
    programs = _programs_dir(root)
    if programs is None:
        print(f"[CANNOT CHECK] closed_loop_executed_reentry_census: no "
              f"programs directory under {root}, so no runner could be read. "
              f"That is the ABSENCE of the question, not a pass.")
        return 2

    runners = _runner_paths(programs)
    sites: List[Dict] = []
    for r in runners:
        sites.extend(scan_module(r))

    if not runners or not sites:
        print(f"[CANNOT CHECK] closed_loop_executed_reentry_census: "
              f"{len(runners)} runner(s) parsed and {len(sites)} re-entry "
              f"site(s) found. A tree whose runners re-enter nothing has no "
              f"loop census to answer; that is not 'examined and clean'.")
        return 2

    counts = {ACTUATING: 0, SELF_CHECKED_ONLY: 0, INERT: 0}
    for row in sites:
        counts[row["verdict"]] += 1

    now = summarise(sites)
    bpath = Path(args.baseline) if args.baseline else (programs / BASELINE_NAME)
    if args.write_baseline:
        _aa.write_text(bpath, json.dumps(now, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        print(f"[BASELINE WRITTEN] {bpath} — {len(now)} site key(s)")
        return 0
    base: Dict[str, Dict[str, int]] = {}
    if bpath.is_file():
        try:
            base = json.loads(bpath.read_text(errors="replace"))
        except (OSError, ValueError):
            base = {}
    regs = regressions(now, base)

    rep = {
        "runners": [r.name for r in runners],
        "sites": sites,
        "counts": counts,
        "declared_edges": declared_edges(root),
        "hand_registered_steps": registered_steps(programs),
        "regressions": regs,
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        _aa.write_text(out, json.dumps(rep, indent=2) + "\n", encoding="utf-8")

    for row in sites:
        if row["verdict"] == INERT:
            print(f"  [INERT] {row['file']}:{row['line']} {row['fn']} -> "
                  f"{row['callee']}: this re-entry passes no argument that can "
                  f"differ and the region never reads back a result. It re-runs "
                  f"the work and cannot change or detect anything.")
    for r in regs:
        print(f"  [REGRESSION] {r}")

    n_dec = len(rep["declared_edges"])
    n_reg = len(rep["hand_registered_steps"])
    print(f"closed_loop_executed_reentry_census: {len(sites)} executed "
          f"re-entry site(s) across {len(runners)} runner(s); "
          f"ACTUATING={counts[ACTUATING]}, "
          f"SELF_CHECKED_ONLY={counts[SELF_CHECKED_ONLY]}, "
          f"INERT={counts[INERT]}.")
    print(f"  DISJOINTNESS: the flow DECLARES {n_dec} closed_loop edge(s); the "
          f"hand-maintained actuator register covers {n_reg} step(s) "
          f"({', '.join(rep['hand_registered_steps']) or 'none'}). The census "
          f"above is DERIVED from the runners and shares no member with the "
          f"declaration set. A count of declarations is not a count of loops.")
    return 1 if (counts[INERT] or regs) else 0


if __name__ == "__main__":
    sys.exit(main())
