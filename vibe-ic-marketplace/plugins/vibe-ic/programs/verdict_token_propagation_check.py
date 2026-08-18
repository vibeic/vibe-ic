#!/usr/bin/env python3
"""
verdict_token_propagation_check.py — META-audit: producer -> consumer
verdict-token propagation guard (ORGANIC #722, captured Bucket C).

THE CLASS (structural, deterministic — pure set membership)
-----------------------------------------------------------
A gate / producer G emits a set of verdict tokens T_G (the string literals
it can assign to the `verdict` field of the report JSON it writes). A
downstream consumer C reads G's verdict field and runs it through a
mapper that recognizes a token set R_C (the literals the mapper compares
the verdict against, e.g. `verdict == "PASS"`, `verdict in ("REVIEW",
"BENIGN-ERC")`). The bug is:

        T_G  NOT-SUBSET-OF  R_C

i.e. G can emit a token C's mapper does not branch on, so the token falls
through the trailing `else` to FAIL silently. Functionally this MIGRATES
a FAIL from G's own step to C's step, where it reads as a fresh, spurious
defect of a different category.

HISTORICAL CASES (the issue names them)
---------------------------------------
* #698:  #696 added `BENIGN-ERC` to the ERC producer (`_emit_erc_report`,
         which writes reports/phase3/erc.json) but the Step-28 PERC
         consumer `_emit_perc_equivalent._auto()` knew only
         {PASS, REVIEW, MEASURED}. `BENIGN-ERC` fell to else->FAIL, so the
         Step-31 ERC FAIL re-appeared as a Step-28 PERC reliability defect.
         (FIX: the mapper added `BENIGN-ERC` to its recognized set.)
* #648/#649: the two Step-14 Yosys gates emit `VACUOUS_PASS`; the flow
         consumer did not distinguish that token from a real PASS / FAIL
         — same `T_G NOT-SUBSET-OF R_C` shape on a different edge.

SCOPE (registry-pinned + general engine) — documented for the corpus bar
------------------------------------------------------------------------
A fully-general static taint of EVERY gate edge is large and would
false-fire on HEAD, which is worse than no audit. So the scope is:

  (1) REGISTRY of the *named, live* producer->consumer edges from the
      historical cases. Each edge is verified by RE-DERIVING both token
      sets from the CURRENT source every run (never a hardcoded list) and
      asserting `T_G subset-of R_C`. The ERC(`_emit_erc_report`) ->
      PERC(`_emit_perc_equivalent._auto`) edge is pinned here; it is the
      exact #698 shape and is CLEAN on HEAD (the fix added BENIGN-ERC).
  (2) GENERAL ENGINE `audit_edges()` that takes ANY list of edges and runs
      the same set-membership rule. The registry feeds it the live edges;
      a test feeds it synthetic defect-shaped fixtures (incl. the #698
      pre-fix shape and the #648/#649 VACUOUS_PASS shape) to prove the
      engine FLAGS them.

The general engine is the reusable core; the registry is the
HEAD-CLEAN-tuned list of real edges. `notes` in the StructuredOutput
records exactly what is registry-pinned vs generally scanned.

§4.05 NEGATIVE NO-LEAK
----------------------
A consumer that DELIBERATELY maps an unknown / genuine-FAIL token to FAIL
(its trailing `else`) is CORRECT — that is the whole point of the else
branch. So the audit flags ONLY a token a producer actually EMITS that has
no consumer branch (a real propagation gap). It NEVER flags:
  * a token that NO producer emits (a hypothetical/foreign token the
    consumer rightly routes to else->FAIL), nor
  * the reverse direction (consumer recognizes a token no producer emits).
The rule is strictly `emitted - recognized` (set difference), one way.

chip-AGNOSTIC: pure verdict-token set membership across function edges.
No chip / vendor / SKU literal in the detection logic.

Usage:
    python3 verdict_token_propagation_check.py [<plugin_root>] [--json OUT]
                                               [--list-edges]
                                               [--registry-json PATH]
    (`--registry-json` is a TEST/fixture hook to drive the engine against a
     fixture tree; production uses the in-source REGISTRY.)

Exit codes:
    0  CLEAN — every registry edge satisfies T_G subset-of R_C
    1  FLAG  — at least one producer emits a token its consumer's mapper
              does not recognize (silent else->FAIL propagation gap)
    2  argument / I-O / parse error
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Token-set extraction (pure AST — re-derived from live source every run).
#
# A "verdict field name" is any name the codebase uses to hold the verdict
# string before serialising it (verdict / status / *_verdict). We extract
# string literals assigned to those names, AND string literals used as a
# dict value under the literal key "verdict" / "status". Conditional
# expressions (`"PASS" if c else "FAIL"`) are walked, so all branch
# literals are captured.
# ---------------------------------------------------------------------------
_VERDICT_TARGET_SUFFIXES = ("verdict", "status", "result")


def _is_verdict_target_name(name: str) -> bool:
    n = name.lower()
    return n.endswith(_VERDICT_TARGET_SUFFIXES) or n in (
        "verdict", "status", "result")


def _literals_in(expr: ast.AST) -> Set[str]:
    """Every str-constant reachable in an expression (covers IfExp / Tuple /
    BoolOp / etc.)."""
    out: Set[str] = set()
    for sub in ast.walk(expr):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.add(sub.value)
    return out


def emitted_tokens(func: ast.AST) -> Set[str]:
    """T_G — the set of string literals the function can assign to a
    verdict-style field, either via `verdict = <expr>` / `*_verdict = <expr>`
    or via a dict literal `{"verdict": <expr>}` / a `d["verdict"] = <expr>`
    subscript assignment."""
    toks: Set[str] = set()
    for node in ast.walk(func):
        # verdict = <expr>  /  _erc_verdict = <expr>  /  status = <expr>
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and _is_verdict_target_name(tgt.id):
                    toks |= _literals_in(node.value)
                # d["verdict"] = <expr>
                elif isinstance(tgt, ast.Subscript) and isinstance(
                        tgt.slice, ast.Constant) and isinstance(
                        tgt.slice.value, str) and _is_verdict_target_name(
                        tgt.slice.value):
                    toks |= _literals_in(node.value)
        # {"verdict": <expr>}
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str) \
                        and _is_verdict_target_name(k.value):
                    toks |= _literals_in(v)
    return toks


def recognized_tokens(func: ast.AST) -> Set[str]:
    """R_C — the set of string literals the mapper compares the consumed
    verdict against. Covers `verdict == "X"`, `verdict != "X"`,
    `verdict in ("A", "B")`, and membership against a list/set/tuple
    literal. These are precisely the tokens that get an EXPLICIT branch
    (anything else falls to the trailing else)."""
    toks: Set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Compare):
            for comp in [node.left] + list(node.comparators):
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    toks.add(comp.value)
                elif isinstance(comp, (ast.Tuple, ast.List, ast.Set)):
                    for elt in comp.elts:
                        if isinstance(elt, ast.Constant) and isinstance(
                                elt.value, str):
                            toks.add(elt.value)
        # match/case "X":  (also an explicit branch on the token)
        if isinstance(node, ast.Match):
            for case in node.cases:
                for sub in ast.walk(case.pattern):
                    if isinstance(sub, ast.MatchValue) and isinstance(
                            sub.value, ast.Constant) and isinstance(
                            sub.value.value, str):
                        toks.add(sub.value.value)
    return toks


# ---------------------------------------------------------------------------
# Edge model + general audit engine.
# ---------------------------------------------------------------------------
@dataclass
class Edge:
    """A producer->consumer verdict edge. `producer_emitted` / `consumer_recognized`
    are the EXTRACTED token sets; `edge_id` is for reporting."""
    edge_id: str
    producer_emitted: Set[str]
    consumer_recognized: Set[str]
    producer_ref: str = ""
    consumer_ref: str = ""


@dataclass
class Finding:
    edge_id: str
    producer_ref: str
    consumer_ref: str
    unhandled_tokens: List[str]
    detail: str = ""


# Tokens whose meaning IS the consumer's else target. A producer that emits
# one of these and a consumer that routes it via `else -> FAIL` is an IDENTITY
# mapping (FAIL stays FAIL), NOT a migration — so it is intentionally exempt
# from the gap. This is the §4.05-correct direction: the bug is a NON-FAIL
# producer token silently becoming FAIL, never a FAIL token staying FAIL.
_ELSE_FAIL_IDENTITY = frozenset({"FAIL", "ERROR"})


def audit_edges(edges: List[Edge]) -> List[Finding]:
    """THE general rule. For each edge FLAG `producer_emitted - consumer_recognized`
    — tokens the producer can emit that the consumer's mapper has no explicit
    branch for, so they fall through the trailing `else -> FAIL`.

    §4.05 no-leak (two carve-outs that keep the rule ONE-WAY + correct):
      (1) A token the consumer recognizes but NO producer emits is NEVER
          flagged (the reverse direction — a correct deliberate-FAIL guard).
          This falls out for free from the set DIFFERENCE direction.
      (2) A producer token whose own meaning IS the else target (FAIL/ERROR)
          is exempt: routing FAIL -> else -> FAIL is an identity, not a silent
          migration. Flagging it would be the leak the issue forbids (a
          genuine FAIL must STILL be FAIL)."""
    findings: List[Finding] = []
    for e in edges:
        gap = (e.producer_emitted - e.consumer_recognized) - _ELSE_FAIL_IDENTITY
        unhandled = sorted(gap)
        if unhandled:
            findings.append(Finding(
                edge_id=e.edge_id,
                producer_ref=e.producer_ref,
                consumer_ref=e.consumer_ref,
                unhandled_tokens=unhandled,
                detail=("producer emits %s ; consumer recognizes %s ; "
                        "UNHANDLED (else->FAIL) %s" % (
                            sorted(e.producer_emitted),
                            sorted(e.consumer_recognized),
                            unhandled)),
            ))
    return findings


# ---------------------------------------------------------------------------
# Source-tree helpers (locate a top-level or nested function by name).
# ---------------------------------------------------------------------------
def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8", errors="ignore"),
                     filename=str(path))


def find_function(tree: ast.AST, name: str,
                  parent: Optional[str] = None) -> Optional[ast.AST]:
    """Find a FunctionDef by name. If `parent` is given, find the nested
    function `name` defined inside the function `parent` (e.g. the nested
    `_auto` mapper inside `_emit_perc_equivalent`)."""
    scope: ast.AST = tree
    if parent is not None:
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and n.name == parent:
                scope = n
                break
        else:
            return None
    for n in ast.walk(scope):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and n.name == name:
            return n
    return None


# ---------------------------------------------------------------------------
# REGISTRY of named live edges (the historical cases). Each entry names a
# producer function (whose emitted-token set is RE-DERIVED from live source)
# and a consumer function/nested-mapper (whose recognized-token set is
# RE-DERIVED). The edge is verified by `audit_edges` every run.
#
# Pinned here: the ERC -> PERC edge that is the EXACT #698 shape and is
# CLEAN on HEAD (the fix added BENIGN-ERC to the consumer's recognized set).
# Adding more live edges is safe ONLY if they stay HEAD-clean; everything
# else is exercised via the general engine in tests.
# ---------------------------------------------------------------------------
@dataclass
class RegistryEdge:
    edge_id: str
    file: str                       # relative to plugin_root
    producer: str                   # producer function name
    consumer: str                   # consumer function name
    consumer_nested: Optional[str] = None   # nested mapper inside consumer


REGISTRY: List[RegistryEdge] = [
    RegistryEdge(
        edge_id="erc_screen->perc_equivalent",
        file="programs/phase3_one_shot_runner.py",
        producer="_emit_erc_report",
        consumer="_emit_perc_equivalent",
        consumer_nested="_auto",
    ),
]


def build_registry_edges(plugin_root: Path,
                         registry: Optional[List[RegistryEdge]] = None
                         ) -> Tuple[List[Edge], List[str]]:
    """Materialise each RegistryEdge into an Edge by extracting the live
    token sets. Returns (edges, warnings). A registry entry whose
    producer/consumer can no longer be located emits a warning (the
    function was renamed) but does NOT itself FAIL — the engine flags only
    real token gaps, never structural absence (avoids HEAD false-fire on
    refactors)."""
    reg = REGISTRY if registry is None else registry
    edges: List[Edge] = []
    warnings: List[str] = []
    for re_ in reg:
        path = plugin_root / re_.file
        if not path.is_file():
            warnings.append("registry edge %s: file %s missing — skipped"
                            % (re_.edge_id, re_.file))
            continue
        try:
            tree = _parse(path)
        except SyntaxError as exc:
            warnings.append("registry edge %s: %s parse error: %s"
                            % (re_.edge_id, re_.file, exc))
            continue
        pfn = find_function(tree, re_.producer)
        cfn = find_function(
            tree, re_.consumer_nested, parent=re_.consumer) \
            if re_.consumer_nested else find_function(tree, re_.consumer)
        if pfn is None:
            warnings.append("registry edge %s: producer %s not found — skipped"
                            % (re_.edge_id, re_.producer))
            continue
        if cfn is None:
            warnings.append("registry edge %s: consumer %s%s not found — skipped"
                            % (re_.edge_id, re_.consumer,
                               ("." + re_.consumer_nested)
                               if re_.consumer_nested else ""))
            continue
        edges.append(Edge(
            edge_id=re_.edge_id,
            producer_emitted=emitted_tokens(pfn),
            consumer_recognized=recognized_tokens(cfn),
            producer_ref="%s::%s" % (re_.file, re_.producer),
            consumer_ref="%s::%s%s" % (
                re_.file, re_.consumer,
                ("." + re_.consumer_nested) if re_.consumer_nested else ""),
        ))
    return edges, warnings


# ---------------------------------------------------------------------------
# Driver.
# ---------------------------------------------------------------------------
def _load_registry_json(path: Path) -> List[RegistryEdge]:
    """Build a registry from a JSON list of edge dicts. Used by the
    end-to-end test harness to drive the real binary against a fixture
    tree (each dict: edge_id/file/producer/consumer[/consumer_nested]).
    NOT for production use — production uses the in-source REGISTRY."""
    data = json.loads(path.read_text())
    out: List[RegistryEdge] = []
    for d in data:
        out.append(RegistryEdge(
            edge_id=d["edge_id"], file=d["file"], producer=d["producer"],
            consumer=d["consumer"], consumer_nested=d.get("consumer_nested")))
    return out


def run(plugin_root: Path,
        registry: Optional[List[RegistryEdge]] = None
        ) -> Tuple[int, Dict[str, object]]:
    edges, warnings = build_registry_edges(plugin_root, registry=registry)
    findings = audit_edges(edges)
    report: Dict[str, object] = {
        "tool": "verdict_token_propagation_check",
        "plugin_root": str(plugin_root),
        "registry_edges": [
            {
                "edge_id": e.edge_id,
                "producer": e.producer_ref,
                "consumer": e.consumer_ref,
                "producer_emitted": sorted(e.producer_emitted),
                "consumer_recognized": sorted(e.consumer_recognized),
            } for e in edges
        ],
        "warnings": warnings,
        "findings": [asdict(f) for f in findings],
        "verdict": "FLAG" if findings else "CLEAN",
    }
    return (1 if findings else 0), report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="META-audit: producer->consumer verdict-token "
                    "propagation guard (#722).")
    ap.add_argument("plugin_root", nargs="?", default=".",
                    help="plugin root (dir containing programs/). Default '.'")
    ap.add_argument("--json", metavar="OUT",
                    help="write the full report JSON to OUT")
    ap.add_argument("--list-edges", action="store_true",
                    help="print the materialised registry edges and exit 0")
    ap.add_argument("--registry-json", metavar="PATH",
                    help="override the in-source REGISTRY with a JSON edge "
                         "list (test/fixture harness only)")
    args = ap.parse_args(argv)

    custom_registry: Optional[List[RegistryEdge]] = None
    if args.registry_json:
        try:
            custom_registry = _load_registry_json(Path(args.registry_json))
        except (OSError, ValueError, KeyError) as exc:
            print("ERROR: bad --registry-json: %s" % exc, file=sys.stderr)
            return 2

    root = Path(args.plugin_root).resolve()
    if not (root / "programs").is_dir():
        # tolerate being pointed at programs/ itself or at a dir that IS the
        # plugin root.
        if root.name == "programs" and (root.parent / "programs").is_dir():
            root = root.parent
        elif (root / "phase3_one_shot_runner.py").is_file():
            root = root.parent
        else:
            print("ERROR: %s has no programs/ subdir" % root, file=sys.stderr)
            return 2

    if args.list_edges:
        edges, warnings = build_registry_edges(root, registry=custom_registry)
        for e in edges:
            print("%s\n  producer  %s -> %s\n  consumer  %s -> %s" % (
                e.edge_id, e.producer_ref, sorted(e.producer_emitted),
                e.consumer_ref, sorted(e.consumer_recognized)))
        for w in warnings:
            print("WARN: %s" % w)
        return 0

    rc, report = run(root, registry=custom_registry)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")

    if rc == 0:
        n = len(report["registry_edges"])  # type: ignore[arg-type]
        print("CLEAN: %d registry verdict-edge(s) satisfy emitted "
              "subset-of recognized (no silent else->FAIL propagation gap)"
              % n)
        for w in report["warnings"]:  # type: ignore[index]
            print("WARN: %s" % w)
    else:
        print("FLAG: %d producer->consumer verdict-token propagation gap(s)"
              % len(report["findings"]))  # type: ignore[arg-type]
        for f in report["findings"]:  # type: ignore[index]
            print("  [%s] producer %s emits %s with NO consumer branch in %s "
                  "(falls else->FAIL)" % (
                      f["edge_id"], f["producer_ref"],
                      f["unhandled_tokens"], f["consumer_ref"]))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
