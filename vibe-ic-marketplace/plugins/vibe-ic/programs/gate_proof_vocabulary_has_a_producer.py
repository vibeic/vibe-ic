#!/usr/bin/env python3
"""An axis whose whole proof vocabulary is produced by nobody.

THIS GATE BLOCKS (rc=1). IT IS GREEN ON THIS TREE — see the 2026-08-25 section
below for the false red it shipped with and what was wrong with it.

WHAT IT ASKS THE REPOSITORY
===========================
Every measurement name a gate proves from must appear in at least one EMITTING
module's declared names. An axis whose whole proof vocabulary is unproduced is
not a strict gate; it is a gate that cannot be answered, and the flow reports
it as undetermined forever while looking healthy — every run says "not
determined", the overall verdict is never reached, and no candidate can ever be
promoted.

The check is a set difference between two tables that already exist.

WHAT IT FOUND, AND WHY THE ANSWER MOVED (2026-08-25)
====================================================
As shipped this gate reported ONE unprovable axis:

        drv   timing.drv.violations
              timing.drv.max_tran_violations
              timing.drv.max_cap_violations
              timing.drv.max_fanout_violations

THAT VERDICT WAS FALSE, and false in the blocking direction. It was measured
false twice from two directions — by the sibling lane's
`every_required_metric_key_has_a_producer` ("Swept, it declared the whole `drv`
axis STRUCTURALLY UNPROVABLE and named four keys as having no producer. That
verdict was FALSE") and by the cross-branch audit recorded as F15 in
`docs/findings/2026-08-22-two-capture-distillation-branches-verified.md`.

THE CAUSE WAS A SCAN-SCOPE BOUNDARY, not a format-built name. All four keys are
declared as PLAIN STRING LITERALS by live producers that this gate could not
see, because both of them live one directory outside its scan root:

    ppa-crosslayer/tools/drv_records.py   `_CHECKS` names max_tran / max_cap /
                                          max_fanout and emits them MEASURED
    ppa-e2e/tools/signoff_records.py:204  `emit("timing.drv.violations", ...)`

So the gate's premise was true of `programs/` and FALSE of the repository, and
its verdict sentence — "on any design, forever" — was a claim about the
repository drawn from a directory. A gate whose own docstring says "THE
POPULATION IS THE LAYER RELATION, NOT A DIRECTORY" had a second, larger
directory-shaped narrowing left in it.

THE REPAIR IS THE TWO-PART ONE THAT F15 MEASURED, and widening alone is only
half of it: with the root widened, three of the four keys resolve and
`timing.drv.violations` still does not, because the population is a RELATION —
"in the `_ppa` package or IMPORTS it" — and `signoff_records.py` mentions `_ppa`
only in prose. Package coupling was standing in for "is a producer". So the
producing side is now ALSO admitted by what a module EMITS (see
`_writes_metric_records`), and the whole repository is walked.

WHY "EMITS" IS THREE CONJUNCTS AND NOT A SCHEMA SUBSTRING. The obvious version
— search for the record schema id — re-admits the CONSUMER, which carries the
same string, and destroys the discrimination the consumer-exclusion exists for.
A producer CONSTRUCTS a record (a `"metric"` key or an `emit(...)` call), gives
it a MEASURED / NOT_MEASURED status, and WRITES it. The consumer does the first
two and never the third; that is the conjunct that separates them.

THE CLASS THIS RULE EXISTS FOR IS REAL, and is documented in the consumer's own
source, for a different axis, as a past defect:

    "both `timing.setup.wns_ns` and `timing.hold.wns_ns` are NOT_MEASURED on
     every view ... So the hold axis was STRUCTURALLY unprovable: no run of
     this flow could produce the evidence it proved from, on any design, ever."

That was repaired by adding a `worst_slack_ns` group to setup and hold — a
per-axis fix. Because it was a fix and not a RULE, nothing stopped the same
shape recurring. This program is the rule.

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
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082

# Parsing the whole repository reaches modules with a literal `\s` in a
# non-raw string. That is a fact about those files and not a finding of this
# gate; letting it onto stderr would make two runs of the same tree differ in
# output for a reason the verdict does not depend on.
warnings.filterwarnings("ignore", category=SyntaxWarning)

#: The gate side. A name declared here is a REQUIREMENT, never a production.
#: THIS FILE IS ON THE LIST. It reads `DEFAULT_AXES`, so it is a consumer of the
#: axis table by role, and with the walk widened to the repository it began
#: reading ITSELF as a producing module — a registry that is its own population,
#: which is the disease this gate is named after, applied to the gate. It
#: declared no axis name, so the verdict never moved; the denominator did, and a
#: denominator that includes the judge is not a denominator.
_CONSUMERS = frozenset({"feasibility.py", "search_feasibility.py", "pareto.py",
                        "gate_proof_vocabulary_has_a_producer.py"})

#: A canonical metric name: dotted, lower-case, at least two segments.
_METRIC_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+){1,4}$")

#: Directories that are not source of this repository. `benchmark-data` holds
#: RUN TREES — published records, not producers — and walking it would make the
#: population depend on which runs happen to be checked out.
#:
#: `gate_fixtures` is pruned for the SAME reason `tests` is, and it was measured
#: rather than assumed: those modules are synthetic SUBJECTS built to be fed to
#: a gate, and six of them satisfy the emits-predicate. One
#: (`ppa_frontier_recomputes`) declares fifteen metric-shaped names, and
#: `timing.setup.violations` had NO producer in this repository except a
#: fixture. The setup axis survives on `timing.setup.wns_ns` either way, so no
#: verdict moved — but an axis whose only producer is a test double is exactly
#: the unanswerable axis this gate exists to refuse, dressed as an answer.
_PRUNE = frozenset({".git", "__pycache__", ".pytest_cache", "node_modules",
                    ".venv", "venv", "benchmark-data", ".mypy_cache",
                    "gate_fixtures"})

#: The status vocabulary a metric record carries. A module that never names one
#: of these is not writing metric records whatever else it writes.
_STATUSES = frozenset({"MEASURED", "NOT_MEASURED"})

#: Attribute/function names that PUT a constructed record somewhere durable.
_WRITE_CALLS = frozenset({"write_text", "write_json", "write", "dump"})


def _walk(root: Path):
    """Every non-test `*.py` in the REPOSITORY, pruned of caches and run trees.

    THE ROOT IS THE REPOSITORY BECAUSE THE RULE IS ABOUT THE REPOSITORY. The
    previous root was `<root>/vibe-ic-marketplace/plugins/vibe-ic/programs`, and
    with it this gate concluded "on any design, forever" about a tree it had not
    read — the two live `timing.drv.*` producers sit in `ppa-crosslayer/tools`
    and `ppa-e2e/tools`. Naming those two directories would be the same mistake
    one directory wider, so the walk is the whole tree and the POPULATION is
    decided by the relation below, which is what the docstring always said.
    """
    import os
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _PRUNE)
        rel = Path(dirpath).relative_to(root).parts
        if "tests" in rel:
            dirnames[:] = []
            continue
        for f in sorted(filenames):
            if f.endswith(".py"):
                out.append(Path(dirpath) / f)
    return out


def _writes_metric_records(tree: ast.AST) -> bool:
    """The producing side, defined by what a module EMITS rather than by what it
    imports. THREE CONJUNCTS, and each one earns its place:

        1. it CONSTRUCTS a record — a dict literal with a `"metric"` key, or a
           call to an `emit(...)` helper;
        2. the record carries a MEASURED / NOT_MEASURED status;
        3. it WRITES the result somewhere.

    The consumer `_ppa/feasibility.py` satisfies 1 and 2 — it builds evidence
    dicts with a `"metric"` key and names both statuses — and never 3. That is
    the whole discrimination: a substring test for the record schema id admits
    the consumer as its own producer, which is the disease this gate is named
    after, one level up.
    """
    constructs = statuses = writes = False
    for n in ast.walk(tree):
        if not constructs:
            if isinstance(n, ast.Dict):
                for k in n.keys:
                    if (isinstance(k, ast.Constant) and k.value == "metric"):
                        constructs = True
                        break
            elif isinstance(n, ast.Call):
                fn = n.func
                nm = fn.id if isinstance(fn, ast.Name) else (
                    fn.attr if isinstance(fn, ast.Attribute) else "")
                if nm == "emit" and n.args:
                    constructs = True
        if not statuses and isinstance(n, ast.Constant) \
                and isinstance(n.value, str) and n.value in _STATUSES:
            statuses = True
        if not writes and isinstance(n, ast.Call):
            fn = n.func
            nm = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else "")
            if nm in _WRITE_CALLS:
                writes = True
        if constructs and statuses and writes:
            return True
    return False


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


def _produced(root: Path, programs: Path) -> Tuple[Set[str], int]:
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
    files = _walk(root)
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
        # THE THIRD ADMISSION PATH. Package coupling alone was standing in
        # for "is a producer", and `ppa-e2e/tools/signoff_records.py` — which
        # declares `timing.drv.violations` as a literal and writes it — names
        # `_ppa` only in its prose. A real producer stayed invisible however
        # wide the root, so the relation now also admits what a module EMITS.
        if not (imports_ppa or "_ppa" in f.parts
                or _writes_metric_records(tree)):
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
    produced, mods = _produced(root, programs)
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
