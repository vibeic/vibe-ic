#!/usr/bin/env python3
"""A registry that IS the population instead of a FILTER over one.

THIS GATE BLOCKS (rc=1) on a NEW one.

WHAT IT ASKS THE REPOSITORY
===========================
An enforcement check whose only finding-emitting loop iterates an opt-in
registry examines exactly the entries somebody volunteered. When that registry
is empty in the tree, the check reports a clean verdict over a population it
never looked at, and that verdict is byte-identical to one earned by
inspection.

A registry must be a FILTER applied to an independently derived population,
never the population itself. The two shapes are told apart by STRUCTURE alone,
which is why this is a rule and not a regression test:

    for row in ledger:            <- the registry is the iteration target
        if bad(row): findings.append(...)          THE DEFECT

    for cand in derived_population():              the correct filter
        if cand.id in registry: continue
        if bad(cand): findings.append(...)

The second shape names the registry too. Grepping for the registry cannot
separate them; asking which node the `for` iterates can.

WHY THIS IS NOT THE TWO WIRING AUDITS
=====================================
`gate_is_wired_check` asks whether anything invokes a gate.
`checker_execution_wiring_audit` asks whether anything but its own test does.
Both are SATISFIED by a gate with this defect: it is invoked, it runs, and it
returns. The uncovered question is what its verdict was computed over.

THE PREDICATE
=============
For every `programs/*.py` and `tools/**/*.py`:

  1. Collect the names bound from a `json.load`/`json.loads` whose argument
     traces to a `.json` path constant that EXISTS as a tracked file in this
     repository. A `.json` name that resolves to nothing on disk is not a
     registry, it is a filename this program writes.
  2. Follow one level of subscript and of `.get(...)`, so `led = data["rows"]`
     stays registry-derived.
  3. Find every `for` whose iteration target resolves to one of those names and
     whose body can EMIT A FINDING — an `.append`/`.extend`/`.add` onto a
     finding-shaped name, a `[FAIL]`/`[ERROR]` print, or a `return 1`.
  4. That `for` is a finding, named by file, line, registry path and loop var.

`in`-membership uses of the same name are NOT findings: that is the filter
shape and it is the remedy this gate asks for.

COVERAGE, MEASURED — the clause's reach, and what it cannot see
===============================================================
The "every finding-emitting loop" clause is what makes this rule usable: it is
the difference between 17 findings and 1, and it is what correctly clears
`checker_execution_wiring_audit`, whose registry loop is a STALENESS check over
a filter. It also bounds what the rule can see, and that bound is stated here
rather than left for a reader to discover.

RE-MEASURED on this tree: of 21 registry-reading enforcement modules, **20
already contain at least one appending loop over a derived population**, so a
registry-iterating finding loop added to any of them would be exculpated and
NOT flagged. The clause's reach is **1 of 21** — `gate_red_since_check` — and
the test pins that set BY NAME rather than by the number, because one leaving
as another entered would keep the count and change the set.

WHAT MOVED, AND WHY IT IS A DEPARTURE AND NOT A REGRESSION. The reach was 2 of
22 (`gate_red_since_check` and `spare_cell_coverage_check`) while
`spare_cell_coverage_check` still read `reports/spare_cell_coverage.json` as an
input. 4156444923 made that gate the single DECLARING PRODUCER of that path and
removed the read, so the module stopped reading a tracked registry at all: it
left the 22-module population, not just the reach. Nothing was exculpated and
no finding was lost.

That is a FALSE-NEGATIVE boundary, not a false-positive one: everything the
rule reports is real, and it under-reports by construction.

THE ALTERNATIVE WAS MEASURED, not assumed — on the 22-module population above,
and the figures below are quoted at that population, not re-derived here.
Requiring the exculpating loop to append to a FINDING-SHAPED collection raises
the reach to 10 of 22 — and
returns `checker_execution_wiring_audit:951` as a second finding, which is a
legitimate staleness check whose own docstring explains why it must go stale.
One measured false positive on a live blocking gate, for eight modules of
reach. It was not taken, and the numbers are here so the decision can be
revisited with evidence rather than re-argued.

A THIRD VARIANT WAS PROPOSED HERE AND HAS NOW BEEN MEASURED. It said: count a
derived loop as exculpating only when the collection it appends to REACHES THE
VERDICT — returned, printed, or passed on — so a local AST-walk worklist
(`stack.append`) would stop exculpating while a reported collection kept doing
so. It was written up as the principled fix and as a larger change than this
lane distils.

IT IS NOT AN IMPROVEMENT, and this paragraph replaces that claim rather than
sitting beside it. Implemented as a prototype and run over the same population:
reach **2 of 22**, findings **1** — identical to the shipped rule, to the
module. The reason is the useful part: in all 20 exculpated modules the derived
appending loops DO reach a verdict. They are real findings over a real derived
population, which is precisely what SHOULD exculpate. The verdict-reachability
test agrees with the permissive one because the permissive one was already
right.

That also retires the 10-of-22 variant properly. It reached further only by
requiring the exculpating collection to be NAMED like a finding, which excludes
genuine finding loops whose author picked another word — so its eight extra
modules were mis-exculpations, not coverage, and its second finding
(`checker_execution_wiring_audit:951`) was the false positive that shape
predicts.

CONCLUSION: the reach is not an artefact of a loose heuristic. It is the
measured structure of this population — 2 of 22 when the variants above were
run, 1 of 21 today, and in both cases only the registry-reading enforcement
modules that emit findings from nowhere else. A future lane should NOT spend
the dataflow change; it has been run.

The run prints the reach every time, so the bound is visible in the verdict and
not only in this docstring.

DENOMINATORS, because this gate is subject to its own rule
==========================================================
The verdict states three: modules parsed, registry-reading modules found, and
finding-emitting loops examined. A run that cannot state them is rc 2, not a
pass. `--json` dumps the census so the population can be re-derived rather than
argued about.

THE INVENTORY
=============
`registry_iteration_domain_inventory.json` records the sites that exist on the
tree this gate shipped with, each with a reason. It is a FILTER over the
derived population above — never the population — which is the shape this gate
exists to require. It MAY ONLY SHRINK: a new site is rc 1, and an inventory row
that no longer matches anything is ALSO rc 1, so it cannot rot into a
suppression list that outlives its own truth.

There is no `--write-baseline`. The inventory is hand-authored from `--json`
and reviewed as a diff.

EXIT
====
  0  no new finding-emitting loop iterates a registry
  1  a NEW one, or a stale inventory row
  2  cannot determine (no tree, unparseable inventory, walk failed)
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

_INVENTORY_NAME = "registry_iteration_domain_inventory.json"

#: A name a finding is collected onto. Deliberately a suffix/substring match on
#: the IDENTIFIER, never on the file text.
_FINDING_NAMES = (
    "finding", "failure", "fail", "viol", "offend", "error", "err",
    "bad", "problem", "issue", "hit", "miss", "breach", "defect",
    "unwired", "stale", "reject", "refus",
)

_EMIT_METHODS = ("append", "extend", "add", "update")


def _is_finding_name(name: str) -> bool:
    low = name.lower()
    return any(tok in low for tok in _FINDING_NAMES)


def _json_constants(tree: ast.AST) -> Set[str]:
    """Every string constant in the module that ends in `.json`."""
    out: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if n.value.endswith(".json"):
                out.add(n.value)
    return out


def _tracked_json_names(root: Path) -> Set[str]:
    """Basenames of `.json` files that EXIST in the tree.

    A `.json` string that resolves to no file on disk is an output name, not a
    registry, and counting it would make every report writer a registry
    reader.
    """
    names: Set[str] = set()
    for p in root.rglob("*.json"):
        parts = p.parts
        if ".git" in parts or "node_modules" in parts:
            continue
        names.add(p.name)
    return names


def _call_name(node: ast.AST) -> Optional[str]:
    """`json.load` / `json.loads` / `load` -> a dotted-ish name, else None."""
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    if isinstance(f, ast.Attribute):
        base = f.value
        if isinstance(base, ast.Name):
            return f"{base.id}.{f.attr}"
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _strings_under(node: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.add(n.value)
    return out


class _RegistryBindings(ast.NodeVisitor):
    """Names bound, directly or by one hop, to a parsed tracked registry."""

    def __init__(self, tracked: Set[str], module_registries: Set[str],
                 loaders: Set[str]) -> None:
        self.tracked = tracked
        self.module_registries = module_registries
        self.loaders = loaders
        #: name -> the registry path constant it came from
        self.bound: Dict[str, str] = {}
        #: name -> registry, for names holding the PATH rather than the rows
        self.path_names: Dict[str, str] = {}
        #: the loader functions that ACTUALLY produced a registry binding
        self.used_loaders: Set[str] = set()

    # ---- helpers -------------------------------------------------------
    def _registry_path_for(self, value: ast.AST) -> Optional[str]:
        """If `value` parses a tracked registry file, return that file name."""
        cn = _call_name(value)
        if cn in ("json.load", "json.loads", "load", "loads"):
            seen = _strings_under(value)
            for s in seen:
                base = s.rsplit("/", 1)[-1]
                if base.endswith(".json") and base in self.tracked:
                    return base
        # `ledger = load_ledger(ledger_path)` — a call to a LOCAL function
        # whose body parses JSON, with an ARGUMENT that traces to the registry
        # path. This is the shape the known instance ships, and a binder that
        # reads only its own scope cannot see it.
        #
        # Tracing the argument is load-bearing, not a refinement. Attributing
        # by "the module names exactly one registry" instead was measured at
        # FOUR false positives — an L-document collection bound from a
        # different loader in a module that happens to mention `waivers.json`
        # elsewhere. The registry a name came from is a dataflow question.
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id in self.loaders:
                for arg in list(value.args) + [k.value for k in value.keywords]:
                    reg = self._mentions_registry(arg)
                    if reg:
                        self.used_loaders.add(value.func.id)
                        return reg
        return None

    def _mentions_registry(self, node: ast.AST) -> Optional[str]:
        """The registry an expression names, directly or through one binding."""
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                base = sub.value.rsplit("/", 1)[-1]
                if base in self.module_registries:
                    return base
            if isinstance(sub, ast.Name):
                reg = self.path_names.get(sub.id)
                if reg:
                    return reg
        return None

    def _hop(self, value: ast.AST) -> Optional[str]:
        """One level of `reg[...]` / `reg.get(...)` stays registry-derived."""
        if isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name):
            return self.bound.get(value.value.id)
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
            if value.func.attr in ("get", "values", "keys", "items"):
                b = value.func.value
                if isinstance(b, ast.Name):
                    return self.bound.get(b.id)
        return None

    # ---- visits --------------------------------------------------------
    def visit_Assign(self, node: ast.Assign) -> None:
        reg = self._mentions_registry(node.value)
        if reg:
            for t in node.targets:
                if isinstance(t, ast.Name):
                    self.path_names.setdefault(t.id, reg)
        src = self._registry_path_for(node.value) or self._hop(node.value)
        if src:
            for t in node.targets:
                if isinstance(t, ast.Name):
                    self.bound[t.id] = src
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            src = self._registry_path_for(node.value) or self._hop(node.value)
            if src and isinstance(node.target, ast.Name):
                self.bound[node.target.id] = src
        self.generic_visit(node)


def _iter_target_name(node: ast.AST) -> Optional[str]:
    """The base Name a `for ... in <node>` ultimately iterates."""
    cur = node
    for _ in range(4):
        if isinstance(cur, ast.Name):
            return cur.id
        if isinstance(cur, ast.Subscript):
            cur = cur.value
            continue
        if isinstance(cur, ast.Call):
            f = cur.func
            if isinstance(f, ast.Attribute) and f.attr in (
                    "values", "keys", "items", "get"):
                cur = f.value
                continue
            if isinstance(f, ast.Name) and f.id in (
                    "sorted", "list", "reversed", "set", "tuple", "enumerate"):
                if cur.args:
                    cur = cur.args[0]
                    continue
            return None
        return None
    return None


def _emits_a_finding(body: List[ast.stmt], strict: bool = True) -> Optional[str]:
    """Why this loop body can emit a finding, or None.

    ASYMMETRIC ON PURPOSE. `strict` names a finding-SHAPED collection, and is
    what the accusation is built on. The permissive form — any collection at
    all — is used only to EXCULPATE: to ask whether the module also emits over
    a derived population. Being generous on the exculpatory side can only
    remove findings, never invent them, and a false accusation is the
    expensive error here.

    It is also the difference that separates the two live candidates:
    `gate_red_since_check` has exactly ONE appending loop and it iterates the
    ledger; `checker_execution_wiring_audit` has NINE, one of them over the
    checker population it audits, so its registry loop is a staleness check
    over a filter and not this defect.
    """
    for n in body:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                if sub.func.attr in _EMIT_METHODS and isinstance(
                        sub.func.value, ast.Name):
                    if not strict or _is_finding_name(sub.func.value.id):
                        return f"{sub.func.value.id}.{sub.func.attr}()"
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                    and sub.func.id == "print":
                for s in _strings_under(sub):
                    if "[FAIL]" in s or "[ERROR]" in s:
                        return "print of a [FAIL]/[ERROR] line"
            if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Constant):
                if sub.value.value == 1:
                    return "return 1"
    return None


def _registry_loader_funcs(tree: ast.AST) -> Set[str]:
    """Local functions whose body parses JSON — `load_ledger` and its kin."""
    out: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(n):
                if _call_name(sub) in ("json.load", "json.loads"):
                    out.add(n.name)
                    break
    return out


def _module_registries(tree: ast.AST, tracked: Set[str]) -> Set[str]:
    """The tracked registry file(s) this module names as a path constant."""
    out: Set[str] = set()
    for s in _json_constants(tree):
        base = s.rsplit("/", 1)[-1]
        if base in tracked:
            out.add(base)
    return out


#: How a module reaches a population that is NOT the registry.
_POPULATION_READS = ("rglob", "glob", "iterdir", "listdir", "walk",
                     "read_text", "read_bytes", "load", "loads",
                     "run", "check_output", "Popen")


def _independent_population(tree: ast.AST, registries: Set[str],
                            path_names: Set[str],
                            loaders: Set[str]) -> Optional[str]:
    """How this module reaches a population OTHER than its registry.

    Without one there is nothing the registry could have been a filter OVER:
    a check whose only artefact IS the registry is reading its SUBJECT, and
    iterating a subject is not this defect. `phase1_no_waivers_used_check`
    is exactly that shape and flagging it would flag a correct check.
    """
    # The registry loader's OWN read is not an independent population — it is
    # how the registry itself arrives. Counting it made every self-contained
    # registry check look like it had a second population.
    inside_loader = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and fn.name in loaders:
            inside_loader.update(id(x) for x in ast.walk(fn))

    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or id(n) in inside_loader:
            continue
        f = n.func
        attr = f.attr if isinstance(f, ast.Attribute) else (
            f.id if isinstance(f, ast.Name) else None)
        if attr not in _POPULATION_READS:
            continue
        names = {s.id for s in ast.walk(n) if isinstance(s, ast.Name)}
        strs = {s.value.rsplit("/", 1)[-1] for s in ast.walk(n)
                if isinstance(s, ast.Constant) and isinstance(s.value, str)}
        if names & path_names or strs & registries:
            continue
        return attr
    return None


def scan_module(path: Path, root: Path,
                tracked: Set[str]) -> Tuple[List[dict], bool, bool]:
    """Findings, whether it reads a registry, and whether it is IN REACH.

    "In reach" means the module has NO appending loop over a derived
    population, so the only-loop clause could still flag it. A module out of
    reach is one this rule cannot see the defect in — see COVERAGE above.

    A module is a FINDING only when EVERY finding-emitting loop it contains
    iterates a registry-derived name. One such loop beside a loop over a
    derived population is the FILTER shape — the remedy this gate asks for —
    and flagging it would flag the fix.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except (OSError, SyntaxError, ValueError):
        return [], False, False

    registries = _module_registries(tree, tracked)
    if not registries:
        return [], False, False

    loaders = _registry_loader_funcs(tree)
    binder = _RegistryBindings(tracked, registries, loaders)
    binder.visit(tree)
    if not binder.bound:
        return [], False, False

    rel = path.relative_to(root).as_posix()
    on_registry: List[dict] = []
    on_derived = 0
    for n in ast.walk(tree):
        if not isinstance(n, (ast.For, ast.AsyncFor)):
            continue
        base = _iter_target_name(n.iter)
        if base is None or base not in binder.bound:
            if _emits_a_finding(n.body, strict=False) is not None:
                on_derived += 1
            continue
        why = _emits_a_finding(n.body)
        if why is None:
            continue
        loopvar = n.target.id if isinstance(n.target, ast.Name) else \
            ast.unparse(n.target)
        on_registry.append({
            "file": rel,
            "line": n.lineno,
            "registry": binder.bound[base],
            "iterates": base,
            "loop_var": loopvar,
            "emits": why,
            "sibling_loops_over_a_derived_population": on_derived,
        })

    if not on_registry or on_derived:
        return [], True, not on_derived

    # Only the loader that ACTUALLY produced the registry binding is excluded.
    # Excluding every function that happens to parse JSON swallowed `main`
    # itself, and with it the second population the module plainly reads.
    other = _independent_population(tree, registries, set(binder.path_names),
                                    binder.used_loaders)
    if other is None:
        return [], True, True
    for f in on_registry:
        f["independent_population_reached_by"] = other
    for f in on_registry:
        f["sibling_loops_over_a_derived_population"] = 0
    return on_registry, True, True


def _key(f: dict) -> str:
    """Identity of a finding, WITHOUT the line number.

    A line number moves when unrelated prose above it grows; keying on it would
    make every reflow a NEW finding and every real fix invisible.
    """
    return f"{f['file']}::{f['registry']}::{f['iterates']}::{f['loop_var']}"


#: The population is ENFORCEMENT CHECKS. A generator, a normaliser or a test
#: that iterates a JSON document is reading its SUBJECT, not filtering a
#: population, and the rule has nothing to say about it.
_ENFORCEMENT_SUFFIXES = ("_check.py", "_audit.py", "_gate.py", "_scan.py",
                         "_gates.py", "_guard.py")


def _is_enforcement(p: Path) -> bool:
    if p.name.endswith(_ENFORCEMENT_SUFFIXES):
        return True
    return "ci" in p.parts and p.suffix == ".py"


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    tracked = _tracked_json_names(root)
    findings: List[dict] = []
    parsed = 0
    readers = 0
    in_reach = 0
    roots = [root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
             root / "tools"]
    for base in roots:
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "node_modules" in p.parts or "tests" in p.parts:
                continue
            if not _is_enforcement(p):
                continue
            parsed += 1
            f, is_reader, reachable = scan_module(p, root, tracked)
            readers += 1 if is_reader else 0
            in_reach += 1 if reachable else 0
            findings.extend(f)
    return findings, {"modules_parsed": parsed,
                      "registry_reading_modules": readers,
                      "registry_readers_within_the_clause_reach": in_reach,
                      "tracked_json_files": len(tracked),
                      "finding_emitting_registry_loops": len(findings)}


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="repository root (default: derived from this file)")
    ap.add_argument("--inventory", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3

    try:
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] registry_is_the_iteration_domain: no "
                  "repository root. NOT a pass.", file=sys.stderr)
            return 2

        findings, denom = scan(root)

        inv_path = Path(a.inventory) if a.inventory else \
            Path(__file__).resolve().parent / _INVENTORY_NAME
        inv_rows: List[dict] = []
        if inv_path.exists():
            inv = json.loads(inv_path.read_text(encoding="utf-8"))
            inv_rows = inv.get("known", [])
        known = {r["key"] for r in inv_rows}

        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings,
                 "inventory_rows": len(inv_rows)}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] registry_is_the_iteration_domain: the walk "
              f"did not complete ({type(exc).__name__}: {exc}). NOT a pass.",
              file=sys.stderr)
        return 2

    print(f"  modules parsed:                    {denom['modules_parsed']}")
    print(f"  modules reading a tracked registry:{denom['registry_reading_modules']:5d}")
    print(f"  of those, within the clause's reach:{denom['registry_readers_within_the_clause_reach']:5d}"
          f"   <- the rest cannot be seen; see COVERAGE in the docstring")
    print(f"  finding-emitting registry loops:   {denom['finding_emitting_registry_loops']}")
    print(f"  inventory rows applied:            {len(known)}")

    seen = {_key(f) for f in findings}
    new = sorted(k for k in seen if k not in known)
    stale = sorted(known - seen)

    rc = 0
    if new:
        rc = 1
        print(f"\n[FAIL] {len(new)} finding-emitting loop(s) iterate an opt-in "
              f"registry:")
        for f in findings:
            if _key(f) in new:
                print(f"   {f['file']}:{f['line']}  for {f['loop_var']} in "
                      f"{f['iterates']}  <- {f['registry']}   ({f['emits']})")
        print("\n  This loop can only see what somebody volunteered. Make the "
              "registry a\n  FILTER over an independently derived population, "
              "and state both\n  denominators in the verdict.")
    if stale:
        rc = 1
        print(f"\n[FAIL] {len(stale)} inventory row(s) match nothing on this "
              f"tree:")
        for k in stale:
            print(f"   {k}")
        print("\n  Remove them. An inventory that keeps suppressing after the "
              "name stops\n  describing anything is the register shape this "
              "gate exists to refuse.")
    if rc == 0:
        print("[PASS] registry_is_the_iteration_domain: no finding-emitting "
              "loop iterates a registry outside the inventory.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
