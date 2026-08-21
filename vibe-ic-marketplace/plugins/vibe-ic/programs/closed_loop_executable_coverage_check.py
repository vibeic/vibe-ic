#!/usr/bin/env python3
"""closed_loop_executable_coverage_check.py — a line of YAML is not a loop.

WHAT THIS ANSWERS, AND WHY IT IS NOT THE QUESTION `closed_loop_edge_check` ASKS
==============================================================================
`closed_loop_edge_check` asks whether a declared edge is WELL-FORMED: it has a
`fallback_to`, the target resolves, the edge re-enters the step, the step has a
gate. It says so itself, and it names the boundary it stops at:

    It does not verify that a runner ACTUALLY re-executes the fallback step. No
    runner reads `closed_loop` today; making one do so is a separate change and
    a larger one.

This check crosses that boundary from the other side. It does not ask a runner
to read the flow. It asks the repository a question it can answer today:

    for each declared edge, is there CODE that takes it, and what does that
    code prove?

and it refuses to let an edge that nothing can take be reported as a closed-loop
success.

THE FOUR CLASSES ARE NESTED TIERS, NOT A PALETTE
================================================
Each class subsumes the one before it. That is what makes the census cheap to
audit: to claim tier N you must produce the evidence of every tier below N, and
this program VERIFIES each citation against the tree rather than believing it.

    DECLARED_ONLY    the flow declares the edge and NOTHING re-enters the
                     fallback step when the trigger fires. The default, and the
                     value an edge gets by having no registry entry at all.
    EXECUTABLE       a named program re-enters the fallback step, or refuses the
                     candidate the fallback exists to reject, when the trigger
                     fires.
    REMEASURED       EXECUTABLE, and the same program re-measures the metric the
                     trigger names AFTER acting — so "it ran" and "it helped"
                     are different questions. (`eco_loop_audit` learned this the
                     expensive way: an ECO that made setup 12x WORSE satisfied
                     every structural field and was recorded `pass`.)
    ROLLBACK_PROVEN  REMEASURED, and the program can UNDO its actuation when the
                     re-measurement is worse, AND a named test proves the undo.

MEASURED AT 867de4289 (v1.11.18) — the census this program printed on main:

    22 declared edges
     18 DECLARED_ONLY
      1 EXECUTABLE      (1.6x -> 1, by refusal: the candidate is discarded)
      3 REMEASURED      (4 -> 1; 23 -> 32 and 32 -> 32 share one actuator)
      0 ROLLBACK_PROVEN

ZERO is the load-bearing number. The step-32 ECO DOES implement a rollback —
`eco_fired_reverted_regression`, which retains the pre-ECO artefacts — and

    grep -rn 'eco_fired_reverted_regression' programs/tests/   ->  no files

so nothing proves it works. `test_eco_loop_audit.py` tests the AUDIT of an
already-regressed record, which is a different claim. An unproven rollback is
exactly the thing this census exists to keep out of a success report.

WHY THE REGISTRY IS CODE AND NOT A JSON SIDECAR
===============================================
A register that lives in a data file beside the thing it vouches for can be
replaced by a sibling file, and this repository has measured that laundering.
The registry here is a module constant: it is reviewed with the check, it moves
with the check, and — the part that matters — **every citation in it is
verified against the tree on every run**. A citation that stops resolving is an
ERROR finding AND demotes the edge to DECLARED_ONLY, so deleting an actuator can
never leave a stale promotion behind.

Citations are STRUCTURAL, not textual. `call_in_loop` asks the AST whether the
callee is called from inside a loop in the named caller; `calls` asks whether it
is called at all. A substring match would survive the loop being deleted around
it, which is the failure mode this whole file is about.

AN EDGE WITH NO ENTRY IS DECLARED_ONLY, DELIBERATELY
====================================================
The flow grew from 19 `closed_loop` blocks to 22 in eleven versions. A new edge
must land at the bottom tier and be promoted by evidence, never inherit a class
by resembling its neighbours.

A ZERO DENOMINATOR IS A REFUSAL, NOT A PASS
===========================================
No flow, an unreadable flow, or zero declarations -> rc 2 with `[CANNOT CHECK]`.
"I could not read it" and "I read it and it was clean" must never produce the
same verdict. The denominator is printed on every run, pass or fail.

AND A CLAIM AUDIT THAT FOUND NOTHING SAYS SO
============================================
When no claim source is present the report carries `claim_audit: NOT_CHECKED`
and `claims_examined: 0`. It is never rendered as a passed audit: an unmeasured
thing must not read as a measured zero.

chip-AGNOSTIC: it reads the flow document's own structure and this repository's
own source. No design, foundry, process, chip token or SKU appears anywhere.

Exit codes (docs/PPA_INTERFACES.md §1):
  0  every citation resolves and no claim overstates an edge
  1  a finding: a citation no longer resolves, or a DECLARED_ONLY edge is
     presented as a closed-loop success
  2  the question could not be put (no/unreadable flow, zero declarations,
     unreadable claim document) — printed as [CANNOT CHECK] / [REFUSE]
  3  bad invocation
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a hard dep of the plugin
    yaml = None  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports
try:
    from _atomic_artefact import write_json as _atomic_write_json  # noqa: E402
except Exception:  # pragma: no cover - defensive; never silently skip the write
    _atomic_write_json = None  # type: ignore

TOOL = "closed_loop_executable_coverage_check"
VERSION = "1.0.0"
SCHEMA = "vibeic.ppa.closed_loop_coverage.v1"

RC_OK, RC_FINDINGS, RC_NOT_MEASURED, RC_BAD_INVOCATION = 0, 1, 2, 3

PLUGIN_ROOT: Path = Path(__file__).resolve().parent.parent
FLOW_REL = Path("flow") / "phase1_phase2_phase3.yaml"
#: The same override the eight dimension modules and `closed_loop_edge_check`
#: honour, so a falsifiability replay that repoints the substrate is read here too.
FLOW_YAML_ENV = "VIBE_IC_MATRIX_FLOW_YAML"

DECLARED_ONLY = "DECLARED_ONLY"
EXECUTABLE = "EXECUTABLE"
REMEASURED = "REMEASURED"
ROLLBACK_PROVEN = "ROLLBACK_PROVEN"

#: Tier order. Index is the tier number; a class requires the evidence of every
#: tier at or below it.
CLASS_ORDER: Tuple[str, ...] = (DECLARED_ONLY, EXECUTABLE, REMEASURED,
                                ROLLBACK_PROVEN)

#: Which evidence role a tier requires. DECLARED_ONLY requires none — that is
#: what makes it the safe default for an unregistered edge.
TIER_EVIDENCE: Dict[str, Tuple[str, ...]] = {
    DECLARED_ONLY: (),
    EXECUTABLE: ("actuate",),
    REMEASURED: ("actuate", "remeasure"),
    ROLLBACK_PROVEN: ("actuate", "remeasure", "rollback", "rollback_test"),
}

EVIDENCE_ROLES: Tuple[str, ...] = ("actuate", "remeasure", "rollback",
                                   "rollback_test")


# ─────────────────────────────────────────────────────────────────────────────
# THE REGISTRY
#
# Keyed on the flow step id, NORMALISED to a string — `closed_loop_edge_check`
# records why raw ids are a trap (`"9"` vs `9`), and a registry keyed on the raw
# id would silently miss an edge the day the yaml author writes the other one.
#
# Every entry was measured at 867de4289 by reading the cited code. An entry
# claims a CLASS and supplies the citations that tier requires; the verifier
# below re-derives the class from the citations that actually resolve, so the
# declared class is a claim this program CHECKS, not one it trusts.
# ─────────────────────────────────────────────────────────────────────────────
REGISTRY: Dict[str, Dict[str, Any]] = {
    # Step 4 (Simulation) -> step 1 (Spec-to-RTL). `design_one_shot_runner.main`
    # runs `step_reference_tb`; on FAIL it re-runs `step_rtl_gen` (that IS step
    # 1) and loops back to `step_reference_tb`, which re-measures. Bounded by
    # `--max-eco`, and it detects a byte-identical regeneration and stops with
    # FAIL_ECO_INERT instead of burning the counter.
    "4": {
        "class": REMEASURED,
        "why": ("design_one_shot_runner.main re-runs step_rtl_gen (flow step 1) "
                "on a reference-TB failure and re-runs the testbench afterwards"),
        "evidence": {
            "actuate": [
                {"kind": "call_in_loop",
                 "file": "programs/design_one_shot_runner.py",
                 "caller": "main", "callee": "step_rtl_gen"},
            ],
            "remeasure": [
                {"kind": "call_in_loop",
                 "file": "programs/design_one_shot_runner.py",
                 "caller": "main", "callee": "step_reference_tb"},
            ],
        },
        # The rollback tier is NOT claimed: the loop never reverts a
        # regeneration that made things worse, it only stops when the bytes stop
        # changing. Recorded so the absence is a decision, not an oversight.
        "not_claimed": {
            "rollback": ("the loop has no undo — a regeneration that makes the "
                         "design worse is kept; it stops on byte-identity "
                         "(FAIL_ECO_INERT), not on a worse measurement"),
        },
    },

    # Step 23 (post-route STA) -> step 32 (the repair pass). The auto-trigger in
    # `step_canonicalize_artefacts` fires on a multi-corner OCV violation — which
    # is step 23's own measurement — and runs the repair.
    "23": {
        "class": REMEASURED,
        "why": ("phase3_one_shot_runner.step_canonicalize_artefacts fires "
                "_run_eco_repair on a multi-corner OCV violation and re-measures "
                "the same OCV views on the repaired netlist"),
        "evidence": {
            "actuate": [
                {"kind": "calls",
                 "file": "programs/phase3_one_shot_runner.py",
                 "caller": "step_canonicalize_artefacts",
                 "callee": "_run_eco_repair"},
            ],
            "remeasure": [
                {"kind": "calls",
                 "file": "programs/phase3_one_shot_runner.py",
                 "caller": "step_canonicalize_artefacts",
                 "callee": "_measure_posteco_mcorner_ocv"},
            ],
        },
        "not_claimed": {
            "rollback_test": ("the runner DOES retain the pre-ECO artefacts on a "
                              "measured regression (`eco_fired_reverted_regression`), "
                              "but no test in programs/tests exercises that branch, "
                              "so the undo is unproven"),
        },
    },

    # Step 32 -> 32, the aggregator's self-edge. Same actuator as 23; recorded
    # separately because the census is per-EDGE and a shared actuator is a fact
    # about the tree, not a reason to count one edge twice or drop one.
    "32": {
        "class": REMEASURED,
        "why": ("the same auto-trigger; step 32 is where it runs, so the edge "
                "re-enters the step that owns the actuator"),
        "shares_actuator_with": "23",
        "evidence": {
            "actuate": [
                {"kind": "calls",
                 "file": "programs/phase3_one_shot_runner.py",
                 "caller": "step_canonicalize_artefacts",
                 "callee": "_run_eco_repair"},
            ],
            "remeasure": [
                {"kind": "calls",
                 "file": "programs/phase3_one_shot_runner.py",
                 "caller": "step_canonicalize_artefacts",
                 "callee": "_measure_posteco_mcorner_ocv"},
            ],
        },
        "not_claimed": {
            "rollback_test": ("see edge 23 — the undo exists and nothing proves it"),
        },
    },

    # Step 1.6x -> 1. The actuation form here is REFUSAL, not re-execution: the
    # trigger says the candidate is DISCARDED and step 1's RTL stands, so
    # "taking the edge" means declining to adopt the rewrite. The judge runs
    # UNCONDITIONALLY (its own docstring explains why a conditional version was
    # rejected) and its non-zero exit is what leaves the baseline in place.
    "1.6x": {
        "class": EXECUTABLE,
        "actuation_form": "refuse_candidate",
        "why": ("design_one_shot_runner.step_crosslayer_rewrite_fidelity runs "
                "crosslayer_rewrite_equivalence_check and FAILs the step, which "
                "is how the candidate is discarded and step 1's RTL stands"),
        "evidence": {
            "actuate": [
                {"kind": "defines",
                 "file": "programs/design_one_shot_runner.py",
                 "symbol": "step_crosslayer_rewrite_fidelity"},
                {"kind": "file_exists",
                 "file": "programs/crosslayer_rewrite_equivalence_check.py"},
            ],
        },
        "not_claimed": {
            "remeasure": ("nothing re-measures rewrite fidelity after the "
                          "refusal — there is nothing to re-measure, the "
                          "candidate is simply not adopted"),
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Flow reading — deliberately the same shape as closed_loop_edge_check so the
# two cannot disagree about what a declaration is.
# ─────────────────────────────────────────────────────────────────────────────
def flow_yaml_path(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit)
    override = os.environ.get(FLOW_YAML_ENV)
    return Path(override) if override else PLUGIN_ROOT / FLOW_REL


def load_steps(path: Path) -> List[Dict[str, Any]]:
    if yaml is None:  # pragma: no cover - defensive
        raise RuntimeError("PyYAML is required to read the flow")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path} does not parse to a mapping")
    steps = doc.get("steps")
    if not isinstance(steps, list):
        raise ValueError(f"{path} declares no `steps` list")
    return [s for s in steps if isinstance(s, dict) and "id" in s]


def _norm(v: Any) -> str:
    return str(v).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Citation verification — structural, against the AST.
# ─────────────────────────────────────────────────────────────────────────────
_AST_CACHE: Dict[Path, Optional[ast.Module]] = {}


def _parse(path: Path) -> Optional[ast.Module]:
    if path in _AST_CACHE:
        return _AST_CACHE[path]
    tree: Optional[ast.Module]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"),
                         filename=str(path))
    except (OSError, SyntaxError, ValueError):
        tree = None
    _AST_CACHE[path] = tree
    return tree


def _find_function(tree: ast.Module, name: str) -> Optional[ast.AST]:
    """The OUTERMOST def of *name*.

    Outermost on purpose: a nested helper that happens to share the name of a
    module-level function would otherwise satisfy a citation aimed at the real
    one. Walk depth-first from the module body and take the first match at the
    shallowest depth.
    """
    best: Optional[ast.AST] = None
    best_depth = 1 << 30

    def walk(node: ast.AST, depth: int) -> None:
        nonlocal best, best_depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if child.name == name and depth < best_depth:
                    best, best_depth = child, depth
            walk(child, depth + 1)

    walk(tree, 0)
    return best


def _called_names(node: ast.AST) -> List[str]:
    out: List[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.append(f.id)
            elif isinstance(f, ast.Attribute):
                out.append(f.attr)
    return out


def _calls_inside_loop(fn: ast.AST, callee: str) -> bool:
    """True when *callee* is called from within a `while`/`for` in *fn*.

    Scoped to the loop BODY (and its `orelse`), not the whole function, because
    the point of the citation is that the call repeats.
    """
    for n in ast.walk(fn):
        if isinstance(n, (ast.While, ast.For, ast.AsyncFor)):
            for stmt in list(n.body) + list(n.orelse):
                if callee in _called_names(stmt):
                    return True
    return False


def _resolve_citation(cit: Dict[str, Any], root: Path
                      ) -> Tuple[bool, str]:
    """`(resolved, human reason)`. A citation this program cannot EVALUATE is
    never reported as resolved — an unknown kind is a registry bug, and it
    surfaces as an unresolved citation rather than a silent pass."""
    kind = cit.get("kind")
    rel = cit.get("file")
    if not isinstance(rel, str) or not rel:
        return False, "citation names no file"
    path = root / rel
    if not path.is_file():
        return False, f"{rel} does not exist"

    if kind == "file_exists":
        return True, f"{rel} exists"

    if kind in ("calls", "call_in_loop", "defines"):
        tree = _parse(path)
        if tree is None:
            return False, f"{rel} could not be parsed"
        if kind == "defines":
            sym = str(cit.get("symbol") or "")
            return ((_find_function(tree, sym) is not None),
                    (f"{rel} defines {sym}" if _find_function(tree, sym)
                     else f"{rel} does not define {sym}"))
        caller = str(cit.get("caller") or "")
        callee = str(cit.get("callee") or "")
        fn = _find_function(tree, caller)
        if fn is None:
            return False, f"{rel} does not define {caller}"
        if kind == "calls":
            ok = callee in _called_names(fn)
            return ok, (f"{rel}:{caller} calls {callee}" if ok
                        else f"{rel}:{caller} does not call {callee}")
        ok = _calls_inside_loop(fn, callee)
        return ok, (f"{rel}:{caller} calls {callee} inside a loop" if ok
                    else f"{rel}:{caller} does not call {callee} inside a loop")

    return False, f"unknown citation kind {kind!r} — this program cannot evaluate it"


def classify_edge(step_id: str, root: Path) -> Dict[str, Any]:
    """The class an edge EARNS, plus every citation and how it resolved."""
    entry = REGISTRY.get(step_id)
    rec: Dict[str, Any] = {
        "step": step_id,
        "registered": entry is not None,
        "declared_class": (entry or {}).get("class", DECLARED_ONLY),
        "actuation_form": (entry or {}).get("actuation_form", "re_execute"),
        "why": (entry or {}).get("why"),
        "not_claimed": (entry or {}).get("not_claimed") or {},
        "citations": [],
        "roles_satisfied": [],
        "problems": [],
    }
    if entry is None:
        # The safe default: no entry, no promotion, no finding. A new edge in
        # the flow lands here and has to be promoted by evidence.
        rec["class"] = DECLARED_ONLY
        rec["why"] = ("no actuator registered — nothing in this repository "
                      "re-enters the fallback step when the trigger fires")
        return rec

    evidence = entry.get("evidence") or {}
    satisfied: List[str] = []
    for role in EVIDENCE_ROLES:
        cits = evidence.get(role) or []
        if not cits:
            continue
        role_ok = True
        for cit in cits:
            ok, reason = _resolve_citation(cit, root)
            rec["citations"].append({"role": role, "citation": cit,
                                     "resolved": ok, "reason": reason})
            if not ok:
                role_ok = False
                rec["problems"].append(
                    f"CLC-EVIDENCE-MISSING: edge {step_id} claims "
                    f"{entry.get('class')} on {role} evidence that no longer "
                    f"resolves — {reason}")
        if role_ok:
            satisfied.append(role)
    rec["roles_satisfied"] = satisfied

    # The class it EARNS: the highest tier all of whose required roles resolved.
    earned = DECLARED_ONLY
    for cls in CLASS_ORDER:
        if all(r in satisfied for r in TIER_EVIDENCE[cls]):
            earned = cls
    rec["class"] = earned

    declared = entry.get("class", DECLARED_ONLY)
    if declared not in CLASS_ORDER:
        rec["problems"].append(
            f"CLC-BAD-REGISTRY: edge {step_id} declares an unknown class "
            f"{declared!r}")
    elif CLASS_ORDER.index(earned) < CLASS_ORDER.index(declared):
        # Already reported per-citation above unless the registry itself is
        # internally inconsistent (a tier claimed with no citations at all).
        missing = [r for r in TIER_EVIDENCE[declared] if r not in satisfied
                   and not (evidence.get(r) or [])]
        if missing:
            rec["problems"].append(
                f"CLC-TIER-INCOMPLETE: edge {step_id} declares {declared} but "
                f"supplies no {'/'.join(missing)} evidence at all")
    return rec


# ─────────────────────────────────────────────────────────────────────────────
# The claim audit.
# ─────────────────────────────────────────────────────────────────────────────
#: An eco_log verdict that PRESENTS the step-32 loop as having converged. The
#: other verdicts this repo writes — ECO_ATTEMPTED, ECO_REQUIRED,
#: ECO_BLIND_TO_VIOLATION, ECO_REVERTED_REGRESSION — are all honest non-successes
#: and are not claims.
_ECO_SUCCESS_VERDICTS = ("ECO_APPLIED",)
_ECO_LOG_REL = Path("phase3") / "stage3" / "eco" / "eco_log.json"


def _claims_from_document(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """`(claims, reason)`. `None` means the document could not be read — which
    is rc 2 territory, never an empty list."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        return None, f"{path} could not be read as JSON: {exc}"
    if isinstance(doc, dict):
        raw = doc.get("closed_loop_successes")
        if raw is None:
            return None, (f"{path} carries no `closed_loop_successes` key — this "
                          f"program cannot tell an empty claim set apart from the "
                          f"wrong document")
    elif isinstance(doc, list):
        raw = doc
    else:
        return None, f"{path} is neither an object nor a list"
    if not isinstance(raw, list):
        return None, f"{path}: `closed_loop_successes` is not a list"
    out: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and "step" in item:
            out.append({"step": _norm(item["step"]),
                        "source": str(path), "detail": item})
        elif isinstance(item, (str, int)):
            out.append({"step": _norm(item), "source": str(path),
                        "detail": None})
    return out, f"{path}: {len(out)} claim(s)"


def _claims_from_project(project: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The claim shapes this repository ALREADY writes. Sources are listed even
    when they yield nothing, so `0 claims` can be told apart from `not looked`."""
    claims: List[Dict[str, Any]] = []
    sources: List[str] = []
    eco_log = project / _ECO_LOG_REL
    if eco_log.is_file():
        sources.append(str(_ECO_LOG_REL))
        try:
            rec = json.loads(eco_log.read_text(encoding="utf-8",
                                               errors="replace"))
        except (OSError, ValueError):
            rec = None
        if isinstance(rec, dict) and rec.get("verdict") in _ECO_SUCCESS_VERDICTS \
                and bool(rec.get("re_verified")):
            claims.append({
                "step": "32", "source": str(_ECO_LOG_REL),
                "detail": {"verdict": rec.get("verdict"),
                           "re_verified": rec.get("re_verified")}})
    return claims, sources


# ─────────────────────────────────────────────────────────────────────────────
def evaluate(flow: Path, project: Optional[Path],
             claims_doc: Optional[Path],
             root: Path = PLUGIN_ROOT) -> Tuple[str, Dict[str, Any], int]:
    rep: Dict[str, Any] = {
        "schema": SCHEMA, "program": TOOL, "version": VERSION,
        "flow": str(flow), "project": (str(project) if project else None),
        "findings": [], "edges": [],
        "census": {c: 0 for c in CLASS_ORDER},
        "claims_examined": 0, "claim_sources": [], "claims": [],
        "claim_audit": "NOT_CHECKED",
    }

    try:
        steps = load_steps(flow)
    except (OSError, ValueError, RuntimeError) as exc:
        rep["verdict"] = "NOT_MEASURED"
        rep["declarations"] = 0
        rep["missing_authority"] = f"the flow document could not be read: {exc}"
        return "NOT_MEASURED", rep, RC_NOT_MEASURED

    declaring = [s for s in steps if isinstance(s.get("closed_loop"), dict)]
    rep["steps_read"] = len(steps)
    rep["declarations"] = len(declaring)
    if not declaring:
        rep["verdict"] = "NOT_MEASURED"
        rep["missing_authority"] = (
            f"the flow declares {len(steps)} step(s) and ZERO `closed_loop` "
            f"blocks, so this census has an empty denominator; a green over "
            f"nothing is not a measurement")
        return "NOT_MEASURED", rep, RC_NOT_MEASURED

    for s in declaring:
        sid = _norm(s["id"])
        rec = classify_edge(sid, root)
        cl = s["closed_loop"]
        rec["fallback_to"] = cl.get("fallback_to")
        rec["trigger"] = cl.get("trigger")
        rep["edges"].append(rec)
        rep["census"][rec["class"]] = rep["census"].get(rec["class"], 0) + 1
        for p in rec["problems"]:
            rep["findings"].append({"severity": "ERROR", "step": sid,
                                    "rule": p.split(":", 1)[0], "message": p})

    by_step = {e["step"]: e for e in rep["edges"]}

    # ── the claim audit ────────────────────────────────────────────────────
    claims: List[Dict[str, Any]] = []
    sources: List[str] = []
    if claims_doc is not None:
        got, reason = _claims_from_document(claims_doc)
        if got is None:
            rep["verdict"] = "NOT_MEASURED"
            rep["missing_authority"] = reason
            return "NOT_MEASURED", rep, RC_NOT_MEASURED
        claims.extend(got)
        sources.append(str(claims_doc))
    if project is not None:
        got2, src2 = _claims_from_project(project)
        claims.extend(got2)
        sources.extend(src2)

    rep["claims"] = claims
    rep["claim_sources"] = sources
    rep["claims_examined"] = len(claims)
    if not sources:
        rep["claim_audit"] = "NOT_CHECKED"
        rep["claim_audit_reason"] = (
            "no claim source was present (no --claims document and no "
            f"{_ECO_LOG_REL} under the project) — zero claims were EXAMINED, "
            "which is not the same as zero claims being clean")
    else:
        rep["claim_audit"] = "CHECKED"
        for c in claims:
            edge = by_step.get(c["step"])
            if edge is None:
                rep["findings"].append({
                    "severity": "ERROR", "step": c["step"],
                    "rule": "CLC-CLAIM-UNDECLARED-EDGE",
                    "message": (f"CLC-CLAIM-UNDECLARED-EDGE: {c['source']} "
                                f"presents step {c['step']} as a closed-loop "
                                f"success, and the flow declares no "
                                f"`closed_loop` on that step at all")})
                continue
            if edge["class"] == DECLARED_ONLY:
                rep["findings"].append({
                    "severity": "ERROR", "step": c["step"],
                    "rule": "CLC-DECLARED-ONLY-PRESENTED-AS-SUCCESS",
                    "message": (
                        f"CLC-DECLARED-ONLY-PRESENTED-AS-SUCCESS: "
                        f"{c['source']} presents step {c['step']} "
                        f"(-> {edge.get('fallback_to')!r}) as a closed-loop "
                        f"success, but that edge is {DECLARED_ONLY}: "
                        f"{edge.get('why')}")})

    rep["verdict"] = "FAIL" if rep["findings"] else "PASS"
    return rep["verdict"], rep, (RC_FINDINGS if rep["findings"] else RC_OK)


def _write_report(out: Path, rep: Dict[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if _atomic_write_json is not None:
        _atomic_write_json(out, rep, indent=2, ensure_ascii=False)
    else:  # pragma: no cover - only when the sibling helper is unavailable
        out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", nargs="?", default=None,
                    help="a run tree to audit for closed-loop success claims "
                         "(optional; the census does not need one)")
    ap.add_argument("--flow", default=None,
                    help="the flow yaml (default: the plugin's canonical flow, "
                         f"or ${FLOW_YAML_ENV} when set)")
    ap.add_argument("--claims", default=None,
                    help="a JSON document carrying `closed_loop_successes`")
    ap.add_argument("--root", default=None,
                    help="the plugin root the citations are resolved against "
                         "(default: this file's plugin)")
    ap.add_argument("--json", default=None, help="JSON report output path")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        # `--help` is SystemExit(0) and is not a bad invocation. Only argparse's
        # own error path (code 2) becomes rc 3; mapping both would make `--help`
        # report an internal error, which is the same class of lie as a refusal
        # exiting 1.
        return RC_OK if not exc.code else RC_BAD_INVOCATION

    flow = flow_yaml_path(args.flow)
    project = Path(args.project) if args.project else None
    claims_doc = Path(args.claims) if args.claims else None
    root = Path(args.root) if args.root else PLUGIN_ROOT

    def _refuse(reason: str) -> int:
        """A refusal that leaves the SAME artefact a run leaves.

        Returning before the report is written would make "I could not look"
        and "no report was requested" indistinguishable on disk, which is the
        defect this check is about, one level up.
        """
        print(f"[CANNOT CHECK] {TOOL}: {reason}", file=sys.stderr)
        if args.json:
            _write_report(Path(args.json), {
                "schema": SCHEMA, "program": TOOL, "version": VERSION,
                "verdict": "NOT_MEASURED", "missing_authority": reason,
                "declarations": 0, "edges": [], "findings": [],
                "claim_audit": "NOT_CHECKED", "claims_examined": 0})
        return RC_NOT_MEASURED

    if claims_doc is not None and not claims_doc.is_file():
        return _refuse(f"--claims {claims_doc} does not exist; a claim "
                       f"document that is not there is not an empty claim set")
    if project is not None and not project.is_dir():
        return _refuse(f"project {project} is not a directory")

    verdict, rep, rc = evaluate(flow, project, claims_doc, root)

    if args.json:
        _write_report(Path(args.json), rep)

    n = rep.get("declarations", 0)
    if verdict == "NOT_MEASURED":
        print(f"{TOOL}: {rep['flow']}")
        print(f"[CANNOT CHECK] {rep['missing_authority']}", file=sys.stderr)
        return rc

    census = rep["census"]
    head = (f"{n} declared closed_loop edge(s) over {rep['steps_read']} step(s); "
            + ", ".join(f"{c}={census.get(c, 0)}" for c in CLASS_ORDER))
    if verdict == "FAIL":
        print(f"[FAIL] {TOOL}: {head}")
        for f in rep["findings"]:
            print(f"  - {f['message']}")
    else:
        print(f"[PASS] {TOOL}: {head}")
    for e in rep["edges"]:
        print(f"  {e['step']:>5} -> {str(e['fallback_to']):<5} {e['class']}"
              + (f"  ({e['actuation_form']})"
                 if e["actuation_form"] != "re_execute" else ""))
    if rep["claim_audit"] == "NOT_CHECKED":
        print(f"  claim audit: NOT_CHECKED — {rep['claim_audit_reason']}")
    else:
        print(f"  claim audit: CHECKED — {rep['claims_examined']} claim(s) from "
              + ", ".join(rep["claim_sources"]))
    return rc


if __name__ == "__main__":
    sys.exit(main())
