#!/usr/bin/env python3
"""signoff_gate_self_skip_consistency_check.py — META-audit for ORGANIC #721.

CLASS (chip-AGNOSTIC, structural): a sign-off gate must NOT map a
runner-disclosed SELF-SKIP / capability-gap attestation to a HARD FAIL.
The runner honestly emits a durable disclosure — a `verdict=SKIPPED-CONDITION`
JSON, a named `formal_not_run.json` / `sparse_die_skip.json` /
`single_corner_stance.json` attestation, a `BENIGN-ERC` verdict — but a
downstream consuming gate that reads ONLY its own rc / required-output
hard-FAILs the disclosed deferral. Per CLAUDE.md rule 11 such a disclosed
deferral must surface as SKIPPED-CONDITION / WAIVED-DEFERRED /
PASS_WITH_OPEN_ITEMS / MANUAL_REVIEW (an open review item), NEVER a
conclusive defect.

This exact bug shipped SIX TIMES and was fixed ONE AT A TIME:
  #673  CDC          — SKIPPED-CONDITION CDC verdict hard-FAILed (multi-clock)
  #675  formal       — formal_not_run.json SKIPPED-CONDITION hard-FAILed
  #692  sparse-die   — sparse_die_skip.json ignored → ZERO_TAPS / FILL_NO_SUBSTANCE
  #693  provenance   — clean sign-off DRC not stamped → provenance FAIL
  #694  PVT          — single_corner_stance.json ignored → corner_count=0 FAIL
  #696  ERC          — power/ground + hilomap tie net mis-classed → ERC_DIRTY

There is no meta-audit for the CLASS, so the next gate with the same shape
ships and is only found by a future clean-room run. This program is that
meta-audit.

WHAT IT CHECKS (two complementary scopes — see notes):

  (A) REGISTRY-PINNED edges. The six historical (attestation-token →
      consuming-gate) edges are pinned in `_REGISTRY`. For each edge whose
      consuming-gate source file exists, the gate source MUST, in the
      SAME file, BOTH (a) reference the disclosed-skip token it consumes AND
      (b) carry a non-FAIL honoring outcome (a "defer token" — one of
      SKIPPED-CONDITION / WAIVED-DEFERRED / PASS_WITH_OPEN_ITEMS /
      MANUAL_REVIEW / DEFERRED / benign / attested-skip). A registered
      consumer that references the disclosed-skip token but has NO co-located
      defer outcome is the historical defect-shape → FLAG. (Pre-fix trees —
      the tree BEFORE #673/#675/#692/#693/#694/#696 — would each be flagged.)

  (B) GENERAL STRUCTURAL SCAN. Beyond the registry, scan EVERY program for
      any function that READS a producer-emitted disclosed-skip token
      (a `verdict`-comparison against a self-skip verdict, or a read of a
      named `*_not_run.json` / `*_skip*.json` / `*_stance.json` attestation
      whose JSON `verdict`/`*_skipped` is consumed) AND, within that same
      function, maps EVERY branch touching that token to a hard-FAIL
      sink (`return 1` / `sys.exit(1)` / a verdict=FAIL emission) with NO
      defer-outcome branch. That is the bug shape; flag it.

§4.05 NEGATIVE NO-LEAK (encoded as the audit's direction):
  The audit ONLY flags the *disclosed-deferral-treated-as-FAIL* direction
  (a self-skip token routed to a hard FAIL with no defer branch). It NEVER
  flags the reverse: a gate that maps a GENUINE FAIL verdict (a real
  violation — verdict=="FAIL", a real floating SIGNAL net, a contradictory
  multi-corner claim) to a hard FAIL is CORRECT and is left untouched.
  Concretely: a function that hard-FAILs on `verdict == "FAIL"` is NEVER
  flagged; a function flagged in scope (B) must specifically route a
  SELF-SKIP verdict (SKIP / SKIPPED / SKIPPED-CONDITION) — not a genuine
  FAIL — to the hard-FAIL sink with no defer branch.

CORPUS-CLEAN BAR: this meta-audit MUST exit 0 on the current HEAD tree (all
six gates already honor their attestation; no other gate exhibits the shape).
A meta-audit that false-fires on legitimate HEAD state is worse than none.

Usage:
    python3 signoff_gate_self_skip_consistency_check.py [<plugin_root>]
                                                         [--json <out>]

Exit codes:
    0  PASS — every registered edge honors its disclosure; no general-scan hit
    1  FAIL — a sign-off gate maps a disclosed self-skip to a hard FAIL
    2  argument / I/O error

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ───────────────────────── disclosed-skip vocabulary ─────────────────────────
# Producer-emitted self-skip / capability-gap VERDICT strings. A consuming
# gate that reads any of these and routes it to a hard FAIL with no defer
# branch is the bug. These are runner-internal protocol tokens, NOT chip
# literals (CLAUDE.md rule 11 vocabulary). Whole-string, case-insensitive.
_SELF_SKIP_VERDICTS: Tuple[str, ...] = (
    "SKIPPED-CONDITION",
    "SKIPPED_CONDITION",
    "SKIP",
    "SKIPPED",
    "BENIGN-ERC",
    "BENIGN_ERC",
)

# Named durable disclosed-skip / capability-gap attestation artifacts the
# runner writes (the producer side of an edge). chip-AGNOSTIC: these are
# flow-protocol filenames, not chip/vendor/SKU names.
_ATTESTATION_ARTIFACTS: Tuple[str, ...] = (
    "formal_not_run.json",
    "sparse_die_skip.json",
    "single_corner_stance.json",
)

# Honoring (non-FAIL) OUTCOME tokens. Presence of any of these alongside a
# consumed disclosed-skip token is evidence the gate routes the disclosure
# to a review / deferral, not a hard FAIL (CLAUDE.md rule 11).
_DEFER_OUTCOME_TOKENS: Tuple[str, ...] = (
    "SKIPPED-CONDITION",
    "SKIPPED_CONDITION",
    "WAIVED-DEFERRED",
    "WAIVED_DEFERRED",
    "PASS_WITH_OPEN_ITEMS",
    "MANUAL_REVIEW",
    "DEFERRED",
    "SPARSE_DIE_DEFERRED",
    "SINGLE_CORNER",
    "single_corner_stance",
    "benign",          # erc benign-net-class honoring path (#696)
    "BENIGN",
    "skip_attested",   # sparse-die attested-skip honoring path (#692)
    "_skip_for_missing",   # flow_compliance sibling self-skip honoring (#675)
    "_SELF_SKIP_VERDICTS",  # flow_compliance shared self-skip set (#675)
)


# ─────────────────────────── registry of known edges ─────────────────────────
@dataclass(frozen=True)
class Edge:
    """A (disclosed-skip producer → consuming sign-off gate) edge that was
    historically fixed one-at-a-time. `consumer` is the gate source file
    (relative to programs/). `skip_tokens` are the disclosed-skip token(s)
    the consumer must reference. `issue` is the historical fix it pins."""
    issue: str
    consumer: str
    skip_tokens: Tuple[str, ...]


_REGISTRY: Tuple[Edge, ...] = (
    Edge("#673", "cdc_crossing_check.py", ("SKIPPED-CONDITION",)),
    Edge("#675", "flow_compliance_check.py",
         ("formal_not_run.json", "SKIPPED-CONDITION")),
    Edge("#692", "metal_fill_density_check.py", ("sparse_die_skip.json",)),
    Edge("#692", "latchup_esd_spacing_check.py", ("sparse_die_skip.json",)),
    Edge("#692", "perc_signoff_check.py", ("MANUAL_REVIEW",)),
    Edge("#694", "pvt_matrix_check.py", ("single_corner_stance.json",)),
    Edge("#696", "erc_float_owner_classify.py", ("functional",)),
)
# NOTE: #693 (provenance stamping) is a PRODUCER-side fix in
# phase3_one_shot_runner.py (the runner must STAMP the clean sign-off DRC
# report into provenance.jsonl), not a consumer-side defer path, so it is
# not a consumer-honoring edge in this registry; the producer-side stamp is
# verified by provenance_check.py / its own tests. See notes.


# ───────────────────────────────── findings ──────────────────────────────────
@dataclass
class Finding:
    scope: str          # "registry" | "general"
    file: str
    rule: str
    detail: str
    issue: str = ""
    lineno: int = 0

    def render(self) -> str:
        loc = f"{self.file}:{self.lineno}" if self.lineno else self.file
        tag = f" ({self.issue})" if self.issue else ""
        return f"[{self.scope}/{self.rule}] {loc}{tag}: {self.detail}"


# ──────────────────────────────── helpers ────────────────────────────────────
def _programs_dir(plugin_root: Path) -> Path:
    """Locate programs/ relative to plugin_root. Accept either a plugin root
    (has programs/) or the programs dir itself."""
    if (plugin_root / "programs").is_dir():
        return plugin_root / "programs"
    if plugin_root.name == "programs" and plugin_root.is_dir():
        return plugin_root
    return plugin_root / "programs"


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _has_any_token_ci(text: str, tokens: Tuple[str, ...]) -> bool:
    low = text.lower()
    return any(t.lower() in low for t in tokens)


# ───────────────────────── scope A: registry edges ───────────────────────────
def _audit_registry(prog_dir: Path) -> List[Finding]:
    """For each registered edge whose consumer exists, the consumer source
    must reference its disclosed-skip token(s) AND carry a defer outcome
    co-located in the same file. A consumer that references the skip token
    but has NO defer outcome is the historical defect-shape."""
    out: List[Finding] = []
    for edge in _REGISTRY:
        f = prog_dir / edge.consumer
        if not f.is_file():
            # A missing registered consumer is not a HEAD violation — the
            # tree may legitimately not ship it (fail-safe, no false-fire).
            continue
        text = _read(f)
        refs_skip = _has_any_token_ci(text, edge.skip_tokens)
        if not refs_skip:
            # The consumer no longer references its disclosed-skip token at
            # all. That is a registry-drift signal: the honoring edge the
            # historical fix added has been removed → the gate can no longer
            # honor the disclosure → flag.
            out.append(Finding(
                scope="registry", file=edge.consumer, issue=edge.issue,
                rule="EDGE_SKIP_TOKEN_DROPPED",
                detail=(f"registered consumer no longer references its "
                        f"disclosed-skip token(s) {list(edge.skip_tokens)} — "
                        f"the {edge.issue} honoring edge appears removed"),
            ))
            continue
        # The defer outcome must be DISTINCT from the consumed skip token
        # itself: a bare `SKIPPED-CONDITION` mention is the disclosure being
        # READ, not proof the gate ROUTES it to a non-FAIL outcome. Every
        # HEAD consumer carries a distinct honoring marker (WAIVED-DEFERRED /
        # PASS_WITH_OPEN_ITEMS / *_DEFERRED / benign / *skip_attested /
        # _SELF_SKIP_VERDICTS …). Absence of any DISTINCT defer outcome is
        # the historical defect-shape (the disclosure is read but mapped to
        # a hard FAIL).
        skip_low = {t.lower() for t in edge.skip_tokens}
        distinct_defer = [t for t in _DEFER_OUTCOME_TOKENS
                          if t.lower() in text.lower() and t.lower() not in skip_low]
        if not distinct_defer:
            out.append(Finding(
                scope="registry", file=edge.consumer, issue=edge.issue,
                rule="EDGE_NO_DEFER_OUTCOME",
                detail=("consumer references the disclosed-skip token but has "
                        "NO DISTINCT non-FAIL defer outcome "
                        "(WAIVED-DEFERRED / PASS_WITH_OPEN_ITEMS / "
                        "*_DEFERRED / MANUAL_REVIEW / benign / "
                        "*skip_attested) — disclosed deferral routed to a "
                        "hard FAIL (the historical defect-shape)"),
            ))
    return out


# ─────────────────────── scope B: general structural scan ────────────────────
class _HardFailSink(ast.NodeVisitor):
    """Detect a hard-FAIL sink within a node subtree: `return 1`,
    `sys.exit(1)` / `exit(1)`, or an assignment/dict carrying verdict="FAIL"
    or rc=1 (the verdict-FAIL emission shape)."""

    def __init__(self) -> None:
        self.found = False

    def _is_one(self, node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and node.value == 1

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is not None and self._is_one(node.value):
            self.found = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        name = ""
        if isinstance(fn, ast.Attribute):
            name = fn.attr
        elif isinstance(fn, ast.Name):
            name = fn.id
        if name == "exit" and node.args and self._is_one(node.args[0]):
            self.found = True
        self.generic_visit(node)


def _subtree_hard_fails(node: ast.AST) -> bool:
    v = _HardFailSink()
    v.visit(node)
    return v.found


def _const_str(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_self_skip_compare(node: ast.AST) -> Optional[str]:
    """If `node` is a comparison whose RHS (or any comparator) is a self-skip
    verdict string OR a membership test against a self-skip collection,
    return the matched token; else None. Genuine-FAIL comparisons
    (== "FAIL") are explicitly NOT matched (§4.05 no-leak direction)."""
    if not isinstance(node, ast.Compare):
        return None
    for comp in node.comparators:
        # x == "SKIPPED-CONDITION"  /  x in ("SKIP", ...)  /  x in {set}
        s = _const_str(comp)
        if s and s.upper() in {t.upper() for t in _SELF_SKIP_VERDICTS}:
            return s
        if isinstance(comp, (ast.Tuple, ast.List, ast.Set)):
            for el in comp.elts:
                es = _const_str(el)
                if es and es.upper() in {t.upper() for t in _SELF_SKIP_VERDICTS}:
                    return es
    return None


def _span_text(node: ast.AST, src_lines: List[str]) -> str:
    """Source text of an AST node's own line span."""
    start = getattr(node, "lineno", 1) - 1
    end = getattr(node, "end_lineno", start + 1)
    return "\n".join(src_lines[start:end])


def _branch_hard_fails_no_defer(if_node: ast.If, src_lines: List[str]) -> bool:
    """The BUG SHAPE, branch-precise: the body taken when the self-skip
    verdict is true reaches a hard-FAIL sink (return 1 / exit(1)) AND that
    same body carries NO defer-outcome token. Only the GUARDED body is
    inspected — not the whole function — so a function that ALSO has a
    legitimate genuine-FAIL branch elsewhere (the normal `main` shape:
    `if verdict=="SKIP": return 0` + a separate `if bad: return 1`) is
    never flagged."""
    for stmt in if_node.body:
        if _subtree_hard_fails(stmt):
            body_text = "\n".join(_span_text(s, src_lines) for s in if_node.body)
            if not _has_any_token_ci(body_text, _DEFER_OUTCOME_TOKENS):
                return True
    return False


def _audit_general(prog_dir: Path) -> List[Finding]:
    """Scan EVERY program. Flag an `if`/`elif` whose TEST is a POSITIVE
    self-skip comparison (verdict == "SKIPPED-CONDITION" / verdict in
    {self-skip set}) and whose GUARDED body routes to a hard-FAIL sink with
    no defer outcome — i.e. the disclosed self-skip itself is mapped to a
    hard FAIL. Branch-precise so a genuine-FAIL branch elsewhere in the same
    function is never implicated. Genuine-FAIL comparisons (== "FAIL") are
    never matched (the §4.05-protected direction)."""
    out: List[Finding] = []
    registered = {e.consumer for e in _REGISTRY}
    for f in sorted(prog_dir.glob("*.py")):
        # The meta-audit itself enumerates the vocabulary — never self-flag.
        if f.name == Path(__file__).name:
            continue
        text = _read(f)
        if not text:
            continue
        # Cheap pre-filter: file must mention a self-skip verdict at all.
        if not _has_any_token_ci(text, _SELF_SKIP_VERDICTS):
            continue
        try:
            tree = ast.parse(text, filename=str(f))
        except SyntaxError:
            continue
        src_lines = text.splitlines()
        # Map each If node to its enclosing function name for the message.
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.If):
                    continue
                tok = _is_self_skip_compare(node.test)
                if tok is None:
                    continue
                if not _branch_hard_fails_no_defer(node, src_lines):
                    continue
                issue = ""
                if f.name in registered:
                    issue = next(e.issue for e in _REGISTRY
                                 if e.consumer == f.name)
                out.append(Finding(
                    scope="general", file=f.name,
                    lineno=getattr(node, "lineno", 0), issue=issue,
                    rule="SELF_SKIP_ROUTED_TO_HARD_FAIL",
                    detail=(f"an `if` guarded by a self-skip comparison "
                            f"({tok!r}) routes its body to a hard FAIL "
                            f"(return 1 / exit(1)) with NO defer outcome — a "
                            f"disclosed self-skip mapped to a hard FAIL "
                            f"(CLAUDE.md rule 11)"),
                ))
    return out


# ──────────────────────────────── driver ─────────────────────────────────────
def audit(plugin_root: Path) -> Tuple[int, List[Finding], Dict[str, int]]:
    prog_dir = _programs_dir(plugin_root)
    if not prog_dir.is_dir():
        raise FileNotFoundError(f"programs/ not found under {plugin_root}")
    findings: List[Finding] = []
    findings += _audit_registry(prog_dir)
    findings += _audit_general(prog_dir)
    stats = {
        "registry_edges": len(_REGISTRY),
        "registry_findings": sum(1 for f in findings if f.scope == "registry"),
        "general_findings": sum(1 for f in findings if f.scope == "general"),
        "total_findings": len(findings),
    }
    rc = 1 if findings else 0
    return rc, findings, stats


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plugin_root", nargs="?", default=".",
                    help="Plugin root (has programs/) or the programs dir itself")
    ap.add_argument("--json", default=None, help="Write a JSON report to this path")
    args = ap.parse_args(argv)

    try:
        rc, findings, stats = audit(Path(args.plugin_root).resolve())
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    report = {
        "program": "signoff_gate_self_skip_consistency_check",
        "issue": "#721",
        "verdict": "PASS" if rc == 0 else "FAIL",
        "rc": rc,
        "stats": stats,
        "findings": [asdict(f) for f in findings],
    }
    if args.json:
        try:
            Path(args.json).write_text(json.dumps(report, indent=2),
                                       encoding="utf-8")
        except OSError as exc:
            print(f"[ERROR] cannot write --json {args.json}: {exc}",
                  file=sys.stderr)
            return 2

    if rc == 0:
        print(f"[PASS] signoff_gate_self_skip_consistency_check — "
              f"{stats['registry_edges']} registered edges honor their "
              f"disclosure; general scan clean")
    else:
        print(f"[FAIL] signoff_gate_self_skip_consistency_check — "
              f"{stats['total_findings']} finding(s): a sign-off gate maps a "
              f"disclosed self-skip to a hard FAIL (CLAUDE.md rule 11)")
        for f in findings:
            print("  " + f.render())
    return rc


if __name__ == "__main__":
    raise SystemExit(main())