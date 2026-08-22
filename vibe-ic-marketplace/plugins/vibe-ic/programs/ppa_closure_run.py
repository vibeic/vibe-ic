#!/usr/bin/env python3
"""ppa_closure_run.py — execute one declared closed_loop edge, or report that
nothing can execute it.

THE QUESTION THIS PROGRAM PUTS
==============================
The canonical flow declares 22 `closed_loop:` blocks. `closed_loop_edge_check`
proves each DECLARATION is honest and says, in its own words, that nothing
executes them. This program is the executor, and its first duty is to say so
when there is nothing to execute:

    $ python3 programs/ppa_closure_run.py --list-edges
    22 declared edges, 0 BOUND, 22 DECLARED_ONLY

A DECLARED_ONLY edge exits 2 with `[CANNOT CHECK]`. It is never 0. An edge with
no controller has not been closed; reporting it green is the defect this whole
lane exists to prevent, and rc=0 is how a flow gate would learn to believe it.

EXIT CODES — docs/PPA_INTERFACES.md §1, and every one of them was chosen against
a case that has actually shipped wrong in this repository
=========================================================================
    0  the trigger did not fire (nothing was wrong), or the loop CONVERGED and
       no re-measured domain finished worse than it started
    1  the loop really ran and really left a violation standing: PLATEAU,
       BUDGET_EXHAUSTED, HANDOFF_REQUIRED, or a collateral regression. This is a
       claim about the DESIGN and it is only ever made after a real measurement
    2  NOT CHECKED: the registry is missing or unreadable, the edge is
       DECLARED_ONLY, or the baseline measurement itself refused. Printed with
       `[CANNOT CHECK]` on stderr so a 2 can never read as a silent skip
    3  BAD INVOCATION: an edge or controller name that is not declared, or an
       implementation root that is not a directory. Never a design FAIL

The distinction between 2 and 3 is the one that cost the most elsewhere: two
shipped gates refused with a bare `SystemExit("...")`, which exits 1, and 1 in
those files meant "the STA engines disagree". A run that never opened an image
reported a hard finding. Nothing here raises SystemExit with a string.

WHAT `--json` CONTAINS
======================
A `vibeic.ppa.closure_run.v1` record: the registry digest the run acted under,
the baseline for EVERY re-measured domain, every iteration with its states, its
exact argv, the tree digest before / after / restored, every re-measurement, the
promote-or-rollback decision and its reason, the residual violation, and the
flow steps a full re-run would additionally have to execute. It is written
through `_atomic_artefact`, so the file existing means the write finished.

chip-AGNOSTIC: no PDK, process, foundry, SKU or design token appears in this
file. Everything design-specific arrives as a path on the command line or as an
entry in the registry.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ppa import cli_exit  # PPA_INTERFACES §1: argparse exits 2; a bad invocation is 3
from _ppa import canonical_json as cj  # noqa: E402
from _ppa.closure import (  # noqa: E402
    Binding, ClosureController, Outcome, RegistryError, load_registry,
)

try:
    from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082
except ImportError:  # pragma: no cover - the helper ships beside this file
    atomic_write_text = None  # type: ignore

TOOL = "ppa_closure_run"
VERSION = "1.0.0"

RC_OK, RC_FINDING, RC_NOT_CHECKED, RC_BAD_INVOCATION = 0, 1, 2, 3


def _write_json(path: Path, obj) -> None:
    text = cj.dumps(obj)
    path.parent.mkdir(parents=True, exist_ok=True)
    if atomic_write_text is not None:
        atomic_write_text(path, text)
    else:  # pragma: no cover
        path.write_text(text, encoding="utf-8")


def _refuse(msg: str, marker: str = "[CANNOT CHECK]") -> int:
    """A refusal is printed with a marker and returns 2. It is never rc=1.

    The marker is not decoration. Without it, a 2 and a skipped step read the
    same in a log, and "I could not look" becomes indistinguishable from
    "I looked and it was clean" -- which has bitten three separate systems here.
    """
    print(f"{marker} {TOOL}: {msg}", file=sys.stderr)
    return RC_NOT_CHECKED


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog=TOOL,
        description="Execute one declared closed_loop edge, or say why nothing can.")
    ap.add_argument("impl_root", nargs="?", type=Path,
                    help="the implementation root the controller may change. "
                         "Snapshot and rollback are scoped to exactly this "
                         "directory, and no declared path may escape it.")
    ap.add_argument("--edge", help="flow step id declaring the closed_loop edge "
                                   "(RAW, as the flow writes it: 20, 1.6x, A7)")
    ap.add_argument("--controller", help="run a controller directly, for a "
                                         "controller that is bound to no edge")
    ap.add_argument("--registry", type=Path, default=None,
                    help="override config/ppa_actuator_registry.yaml")
    ap.add_argument("--workdir", type=Path, default=None,
                    help="where snapshots and measurement artefacts go "
                         "(default: a temporary directory)")
    ap.add_argument("--json", dest="json_out", type=Path,
                    help="write the vibeic.ppa.closure_run.v1 record here")
    ap.add_argument("--list-edges", action="store_true",
                    help="print every declared edge and its binding, then exit")
    ap.add_argument("--verify-registry", action="store_true",
                    help="check that every EXECUTABLE claim resolves, then exit")
    args, _rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        return _rc

    try:
        registry = load_registry(args.registry)
    except RegistryError as exc:
        # An unreadable registry is a question we could not put. Never a finding.
        return _refuse(str(exc))

    if args.verify_registry:
        problems = registry.verify_bindings()
        print(f"{TOOL}: registry {registry.path}")
        print(f"  digest      {registry.digest()}")
        print(f"  actuators   {len(registry.actuators)} "
              f"({sum(1 for a in registry.actuators.values() if a.binding is Binding.EXECUTABLE)} EXECUTABLE)")
        print(f"  domains     {len(registry.domains)} "
              f"({sum(1 for d in registry.domains.values() if d.binding is Binding.EXECUTABLE)} EXECUTABLE)")
        print(f"  controllers {len(registry.controllers)}")
        for p in problems:
            print(f"  UNRESOLVED CLAIM: {p}", file=sys.stderr)
        if problems:
            # A registry that claims an executability it does not have is a
            # broken authorisation, not a design finding.
            return _refuse(
                f"{len(problems)} EXECUTABLE claim(s) do not resolve; the "
                f"registry cannot be trusted to describe what may run",
                marker="[REFUSE]")
        print("  every EXECUTABLE claim resolves to a file in the tree")
        return RC_OK

    if args.list_edges:
        status = registry.edge_status()
        bound = sum(1 for v in status.values() if v == "BOUND")
        print(f"{TOOL}: {len(status)} declared edges, {bound} BOUND, "
              f"{len(status) - bound} DECLARED_ONLY")
        for edge_id in sorted(status, key=lambda k: (len(k), k)):
            cid = registry.edges.get(edge_id)
            print(f"  edge {edge_id:>5}  {status[edge_id]:<14} "
                  f"controller={cid or '-'}")
        if bound == 0:
            # rc=2, not 0. An inventory that always exits 0 is a listing today
            # and a false green the moment somebody wires it into a gate --
            # which is precisely how a check with no discriminating power gets
            # shipped. 22 declarations and 0 executors is NOT CHECKED.
            return _refuse(
                f"no declared edge has an executable controller. Every one of "
                f"the {len(status)} edges is DECLARED_ONLY and none may be "
                f"displayed as a closed-loop success.")
        return RC_OK

    if bool(args.edge) == bool(args.controller):
        ap.print_usage(sys.stderr)
        print(f"{TOOL}: give exactly one of --edge or --controller "
              f"(or --list-edges / --verify-registry)", file=sys.stderr)
        return RC_BAD_INVOCATION
    if args.impl_root is None:
        ap.print_usage(sys.stderr)
        print(f"{TOOL}: an implementation root is required to run a controller",
              file=sys.stderr)
        return RC_BAD_INVOCATION
    if args.edge is not None and str(args.edge) not in registry.edges:
        print(f"{TOOL}: edge {args.edge!r} is not declared in "
              f"{registry.path}. Declared: "
              f"{sorted(registry.edges)}", file=sys.stderr)
        return RC_BAD_INVOCATION
    if args.controller is not None and args.controller not in registry.controllers:
        print(f"{TOOL}: controller {args.controller!r} is not declared in "
              f"{registry.path}. Declared: "
              f"{sorted(registry.controllers)}", file=sys.stderr)
        return RC_BAD_INVOCATION

    impl_root = args.impl_root
    if not impl_root.is_dir():
        # A missing implementation root is a BAD INVOCATION, not a design FAIL
        # and not a silent pass. This is the vacuous case the four-fixture rule
        # names: it must not be 0 and it must not be 1.
        print(f"{TOOL}: implementation root {impl_root} is not a directory; "
              f"there is nothing to actuate on", file=sys.stderr)
        return RC_BAD_INVOCATION

    tmp: Optional[tempfile.TemporaryDirectory] = None
    if args.workdir is not None:
        workdir = args.workdir
    else:
        tmp = tempfile.TemporaryDirectory(prefix="ppa_closure_")
        workdir = Path(tmp.name)

    try:
        controller = ClosureController(registry, impl_root, workdir)
        if args.edge is not None:
            run = controller.run_edge(str(args.edge))
        else:
            run = controller.run_controller(str(args.controller))
        record = run.to_record()
        if args.json_out is not None:
            _write_json(args.json_out, record)

        rc = run.exit_code()
        head = (f"{TOOL}: edge={run.edge_id or '-'} "
                f"controller={run.controller_id or '-'} "
                f"outcome={run.outcome.value} "
                f"closed_loop_success={run.is_closed_loop_success()}")
        print(head)
        print(f"  {run.reason}")
        for it in run.iterations:
            print(f"  iteration {it.index}: {' -> '.join(it.states)}")
            print(f"    {it.decision}: {it.decision_reason}")
        # The NOT_MEASURED rows are PRINTED, never omitted -- a report that
        # drops them turns "nobody looked" into "nothing to see".
        for name, rec in sorted(run.final_all.items()):
            if "value" in rec:
                print(f"  {rec['metric']} = {rec['value']} {rec['unit']} "
                      f"[{rec['status']}]")
            else:
                print(f"  {rec['metric']} = NOT_MEASURED "
                      f"({rec.get('reason', '')[:120]})")
        for c in run.collateral:
            print(f"  COLLATERAL REGRESSION: {c['metric']} "
                  f"{c['from']} -> {c['to']} ({c['direction']})", file=sys.stderr)
        if run.residual is not None:
            print(f"  RESIDUAL: {run.residual['metric']} = "
                  f"{run.residual['value']} {run.residual['unit']}, target "
                  f"{run.residual['target']['op']} "
                  f"{run.residual['target']['value']} — NOT repaired, still open",
                  file=sys.stderr)
        marker = run.outcome.marker()
        if marker:
            print(f"{marker} {TOOL}: {run.reason}", file=sys.stderr)
        return rc
    finally:
        if tmp is not None:
            tmp.cleanup()


if __name__ == "__main__":
    sys.exit(main())
