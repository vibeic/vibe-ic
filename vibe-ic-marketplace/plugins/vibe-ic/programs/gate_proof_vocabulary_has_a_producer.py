#!/usr/bin/env python3
"""An axis whose whole proof vocabulary is produced by nobody.

THIS GATE BLOCKS (rc=1), AND IT IS RED ON THE TREE IT SHIPPED WITH.

WHAT IT ASKS THE REPOSITORY
===========================
Every measurement name a gate proves from must appear in at least one EMITTING
module's declared names. An axis whose whole proof vocabulary is unproduced is
not a strict gate; it is a gate that cannot be answered, and the flow reports
it as undetermined forever while looking healthy — every run says "not
determined", the overall verdict is never reached, and no candidate can ever be
promoted.

The check is a set difference between two tables that already exist.

WHAT IT FINDS, AND WHY IT IS NOT INVENTORIED
============================================
    10 feasibility axes, 38 emitting modules, 143 declared names
    ONE axis has NOT ONE of its proof names produced:

        drv   timing.drv.violations
              timing.drv.max_tran_violations
              timing.drv.max_cap_violations
              timing.drv.max_fanout_violations

`timing.drv.*` occurs in exactly two places in this tree: the CONSUMER
(`_ppa/feasibility.py`, where the axis is declared) and the tests. No producer
emits any of the four. The drv axis is structurally unprovable — no run of this
flow can produce the evidence it proves from, on any design, ever.

THIS EXACT CLASS IS ALREADY DOCUMENTED IN THE CONSUMER'S OWN SOURCE, for a
different axis, as a past defect:

    "both `timing.setup.wns_ns` and `timing.hold.wns_ns` are NOT_MEASURED on
     every view ... So the hold axis was STRUCTURALLY unprovable: no run of
     this flow could produce the evidence it proved from, on any design, ever."

That was repaired by adding a `worst_slack_ns` group to setup and hold — a
per-axis fix. Because it was a fix and not a RULE, the same shape survived on
drv and nobody noticed. This program is the rule.

There is no inventory. A waiver would restore precisely the state the comment
above describes: an axis that reads healthy and can never be answered.

EXCLUDING THE CONSUMER IS THE WHOLE PREDICATE
=============================================
The gate declares its proof names as string constants, and the gate lives in
the same package as the producers. Build the "produced" union over the whole
package and every proof name is trivially present — MEASURED: 9 axes, 0
unprovable, a check that cannot fail. Excluding the consumer modules
(`feasibility.py`, `search_feasibility.py`, `pareto.py`) changes the answer to
1 of 9. A vocabulary check that reads the consumer as a producer is
self-satisfying, which is the same disease as a registry that is its own
population.

EXIT
====
  0  every axis has at least one produced proof name
  1  an axis whose whole proof vocabulary is unproduced
  2  cannot determine — the axis table or the producer set is unreadable
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

#: The gate side. A name declared here is a REQUIREMENT, never a production.
_CONSUMERS = frozenset({"feasibility.py", "search_feasibility.py", "pareto.py"})

#: A canonical metric name: dotted, lower-case, at least two segments.
_METRIC_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+){1,4}$")


def _axes(programs: Path) -> Optional[Dict[str, List[List[str]]]]:
    sys.path.insert(0, str(programs))
    try:
        import _ppa.feasibility as F                       # noqa: PLC0415
    except Exception:                                      # noqa: BLE001
        return None
    axes = getattr(F, "DEFAULT_AXES", None)
    if not axes:
        return None
    out: Dict[str, List[List[str]]] = {}
    for a in axes:
        try:
            out[a.name] = [[p.metric for p in g] for g in a.groups]
        except Exception:                                  # noqa: BLE001
            return None
    return out


def _const_table(files) -> Dict[Tuple[str, str], str]:
    """`NAME = "a.b.c"` at module level, over EVERY module including the
    consumers. A producer may name a metric through the consumer's own
    constant (`M.measured(feas.ECO_M_COUNT, ...)`); excluding the consumer as
    a PRODUCER must not also hide where the string is defined."""
    out: Dict[Tuple[str, str], str] = {}
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for n in tree.body:
            if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str)
                    and _METRIC_NAME.match(n.value.value)):
                for tg in n.targets:
                    if isinstance(tg, ast.Name):
                        out[(f.stem, tg.id)] = n.value.value
    return out


def _produced(programs: Path) -> Tuple[Set[str], int]:
    """Names mentioned by the PRODUCING side of the ppa layer.

    THE POPULATION IS THE LAYER RELATION, NOT A DIRECTORY. An earlier version
    of this gate scanned `programs/_ppa/` only. That is a filename-shaped
    population and it MISSED the real producers, which are top-level programs:
    `ppa_eco_spare_records.py` emits `design_for_eco.spares.count` and does not
    live under `_ppa/`. Measured on the merged tree, the directory population
    reported the eco_readiness axis unprovable when it is produced -- a FALSE
    POSITIVE, and against a name landed after this gate was written.

    So the population is every non-test module that is IN the `_ppa` package
    or IMPORTS it, minus the consumers. That is the same relation this branch's
    `layer_membership_is_declared_not_inferred_from_a_filename_prefix` gate
    tells the ppa layer to use, applied to itself.

    A mention is a metric-shaped string literal OR an attribute reference that
    resolves through `_const_table`. This is deliberately a NECESSARY
    condition, not a sufficient one: production here is partly dynamic, so the
    gate cannot prove a name IS produced. It can only prove a name is mentioned
    NOWHERE on the producing side, and an axis all of whose proof names are
    absent from every producer is unprovable whatever the runtime does.
    """
    files = [f for f in sorted(programs.rglob("*.py")) if "tests" not in f.parts]
    consts = _const_table(files)
    names: Set[str] = set()
    mods = 0
    for f in files:
        if f.name in _CONSUMERS:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        alias: Dict[str, str] = {}
        imports_ppa = False
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                if n.module and n.module.split(".")[0] == "_ppa":
                    imports_ppa = True
                for a in n.names:
                    alias[a.asname or a.name] = a.name
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.split(".")[0] == "_ppa":
                        imports_ppa = True
                    alias[a.asname or a.name.split(".")[0]] = a.name.split(".")[-1]
        # The population is the UNION of the package's own modules and the
        # layer's importers. A module inside `_ppa/` need not import `_ppa`
        # (it uses relative imports); restricting to importers alone dropped
        # the extractor tables and made setup/hold/ir/lvs/equivalence look
        # unprovable -- five false positives, caught by re-running.
        if not (imports_ppa or "_ppa" in f.parts):
            continue
        got: Set[str] = set()
        for n in ast.walk(tree):
            if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and _METRIC_NAME.match(n.value)):
                got.add(n.value)
            elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                key = (alias.get(n.value.id, n.value.id), n.attr)
                if key in consts:
                    got.add(consts[key])
        if got:
            mods += 1
            names |= got
    return names, mods


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    programs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    axes = _axes(programs)
    if axes is None:
        raise RuntimeError("the axis table could not be read")
    produced, mods = _produced(programs)
    findings: List[dict] = []
    for name, groups in sorted(axes.items()):
        every = [m for g in groups for m in g]
        hit = [m for m in every if m in produced]
        if not hit:
            findings.append({"axis": name, "proof_names": every})
    return findings, {"axes": len(axes), "emitting_modules": mods,
                      "declared_names": len(produced),
                      "unprovable_axes": len(findings)}


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    try:
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] gate_proof_vocabulary_has_a_producer: no "
                  "repository root. NOT a pass.", file=sys.stderr)
            return 2
        findings, denom = scan(root)
        if denom["axes"] == 0 or denom["declared_names"] == 0:
            print("[CANNOT DETERMINE] gate_proof_vocabulary_has_a_producer: an "
                  "empty axis table or an empty producer set. A verdict over "
                  "nothing is NOT a pass.", file=sys.stderr)
            return 2
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] gate_proof_vocabulary_has_a_producer: the "
              f"comparison did not complete ({type(exc).__name__}: {exc}). NOT "
              f"a pass.", file=sys.stderr)
        return 2

    print(f"  feasibility axes:          {denom['axes']}")
    print(f"  emitting modules:          {denom['emitting_modules']}"
          f"   (the consumer is excluded — see the docstring)")
    print(f"  names they declare:        {denom['declared_names']}")
    print(f"  axes with no produced name:{denom['unprovable_axes']:4d}")

    if findings:
        print(f"\n[FAIL] {len(findings)} axis/axes prove from names nobody "
              f"produces:")
        for f in findings:
            print(f"   {f['axis']}:")
            for m in f["proof_names"]:
                print(f"       {m}")
        print("\n  Such an axis is not a strict gate; it is a gate that cannot "
              "be answered.\n  Every run reports it undetermined, the overall "
              "verdict is never reached, and\n  no candidate can be promoted. "
              "Either a producer must emit one of these\n  names, or the axis "
              "must prove from a name that is produced.")
        return 1

    print("[PASS] gate_proof_vocabulary_has_a_producer: every axis proves from "
          "at least one produced name.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
