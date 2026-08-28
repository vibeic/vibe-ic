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

ENFORCEMENT: BLOCKING WHEN INVOKED. A finding returns rc 1 to the caller; an
unmeasurable input returns rc 2, never a clean rc 0. The canonical one-shot
runner does not currently invoke this census, so this statement does not claim
that the whole flow stops on it. Wiring that caller is a separate change.

THE FOUR CLASSES ARE NESTED TIERS, NOT A PALETTE
================================================
Each class subsumes the one before it. That is what makes the census cheap to
audit: to claim tier N you must produce the evidence of every tier below N, and
this program VERIFIES each citation against the tree rather than believing it.

    DECLARED_ONLY    the flow declares the edge and NOTHING re-enters the
                     fallback step when the trigger fires. The default, and the
                     value an edge gets by having no registry entry at all.
    EXECUTABLE       a named program re-enters the fallback step when the
                     trigger fires. Refusing a candidate is a blocking gate,
                     not execution of the declared fallback edge.
    REMEASURED       EXECUTABLE, and the same program re-measures the metric the
                     trigger names AFTER acting — so "it ran" and "it helped"
                     are different questions. (`postroute_timing_repair_audit` learned this the
                     expensive way: a repair that made setup 12x WORSE satisfied
                     every structural field and was recorded `pass`.)
    ROLLBACK_PROVEN  REMEASURED, and the program can UNDO its actuation when the
                     re-measurement is worse, AND a named test proves the undo.

MEASURED AT v1.12.30, AFTER THE ROLLBACK WAS PROVEN — the census this program
prints:

    21 declared edges
     18 DECLARED_ONLY
      0 EXECUTABLE
      1 REMEASURED       (4 -> 1)
      2 ROLLBACK_PROVEN  (23 -> 32 and 32 -> 32 share one actuator and one undo)

THE ZERO WAS THE LOAD-BEARING NUMBER, AND IT WAS EARNED AWAY. The step-32
repair always implemented a rollback — `timing_repair_reverted_regression`,
which retains the pre-repair artefacts — but

    grep -rn 'timing_repair_reverted_regression' programs/tests/   ->  no files

so nothing proved it worked, and an unproven rollback is exactly the thing this
census exists to keep out of a success report. (`test_postroute_timing_repair_
audit.py` tests the AUDIT of an already-regressed record, which is a different
claim.)

WHAT WAS MISSING WAS NOT THE ROLLBACK BUT AN ADDRESS FOR ITS DECISION. The undo
turned on an inline expression inside a 900-line step function, so no test could
reach it without re-implementing it — and a test that re-implements the thing it
checks proves only that two copies agree. That expression is now
`repair_result_is_a_regression`, and
`programs/tests/test_timing_repair_reverted_regression.py` exercises it: the 12x
regression that motivated the guard, the one-picosecond floor, both directions
of the adopt/revert choice, and the comparability guard that keeps a delta
measured across different parasitics from being charged to the repair.

SO EDGES 23 AND 32 CARRY `rollback` + `rollback_test` CITATIONS AND THE CENSUS
READS 2. The promotion is earned only while the proof exists: delete the proof
and the rollback_test citation stops resolving, which is an ERROR finding AND a
demotion back to REMEASURED. That was run, not assumed — see
`test_the_rollback_tier_is_earned_and_stays_earned`.

`rollback_test` is also the one role whose evidence CANNOT live in the runner,
because a runner that tests itself proves nothing. See `_tier_is_modelled` for
how a root that models only the runner tier is told apart from a tree where the
proof was deleted; the first is demoted in silence, the second is accused.

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
it, which is the failure mode this whole file is about. Promotion roles reject
mere `file_exists`/`defines` evidence, and an actuator call must match the
canonical runner entrypoint for the YAML edge's actual `fallback_to`. It must
also be controlled by the SOURCE step's own trigger result in the same live
retry path; a sibling edge that happens to share the fallback target cannot
lend its loop. Constant-false branches/loops, nested dead functions, and a
receiver method that merely shares the callee suffix are excluded. Guarded
actuators additionally pin the boolean trigger polarity, reject overwritten
trigger receipts (including aliases/method mutation), and stop at unconditional
path terminators. Loop retries pin the terminal status set. REMEASURED evidence
must occur after the fallback on the same guarded branch, or via a reachable
loop back-edge into the measurement. Thus a
registry label beside an unrelated call cannot promote itself to EXECUTABLE.

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
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

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
VERSION = "1.4.0"
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

#: Evidence that promotes a tier must prove executable structure.  Mere file or
#: symbol presence can be useful provenance, but it cannot prove that an
#: actuator, measurement, or undo is actually invoked.
ROLE_CITATION_KINDS: Dict[str, Tuple[str, ...]] = {
    "actuate": ("fallback_after_trigger_in_loop",
                "fallback_guarded_by_trigger"),
    "remeasure": ("remeasure_after_fallback_in_loop",
                  "remeasure_after_fallback_guarded_by_trigger"),
    "rollback": ("calls", "call_in_loop"),
    "rollback_test": ("calls", "call_in_loop"),
}

#: THE ONE EVIDENCE ROLE THAT CANNOT LIVE IN THE RUNNER.
#:
#: `actuate`, `remeasure` and `rollback` are all facts about the runner: the
#: runner calls the actuator, re-measures, and consults the undo decision. A
#: `rollback_test` is different in kind — a runner that tests itself proves
#: nothing, so this role's proof necessarily lives in the TEST tier, in a file
#: the runner never imports.
#:
#: That distinction is what kept this promotion from being a line edit. The
#: `--root` fixtures below model the RUNNER tier only: they write
#: `programs/*.py` stubs and no `programs/tests/` at all. Under such a root the
#: test-tier citation is not MISSING, it is UNASKED — and reporting "the proof
#: was deleted" about a tree that was never asked to carry one is the same
#: false-negative shape as a green from an empty denominator.
TEST_TIER_ROLES: FrozenSet[str] = frozenset({"rollback_test"})
TEST_TIER_DIR = "programs/tests"


def _tier_is_modelled(role: str, cit: Dict[str, Any], root: Path) -> bool:
    """Can THIS root be asked about this citation at all?

    False in exactly one case: a test-tier role, cited under `programs/tests/`,
    against a root that has no `programs/tests/` directory whatsoever.

    DELIBERATELY THE NARROWEST POSSIBLE HOLE, because this is the one rule in
    the file that can suppress a finding:

      * it never promotes. An unmodelled role is an UNSATISFIED role, so the
        edge falls to the highest tier whose evidence did resolve — the census
        reports REMEASURED, never ROLLBACK_PROVEN, under such a root;
      * it is keyed on the DIRECTORY, not the file. The moment a root carries a
        `programs/tests/` at all it is a tree that models the test tier, and a
        cited proof missing from it is rot, reported as CLC-EVIDENCE-MISSING
        exactly as before. Deleting the proof from the shipped tree therefore
        still reddens this census, which is the property that makes the
        promotion a ratchet rather than a one-way claim.
    """
    if role not in TEST_TIER_ROLES:
        return True
    rel = str(cit.get("file") or "")
    if not rel.startswith(TEST_TIER_DIR + "/"):
        # A test-tier role cited somewhere else is a registry bug, not an
        # unmodelled tier. Judge it normally so it surfaces.
        return True
    return (root / TEST_TIER_DIR).is_dir()


#: A remeasurement proof is only evidence for an edge when it extends one of
#: that edge's accepted actuation proofs.  Matching just the measurement call is
#: insufficient: a sibling retry path in the same caller must not lend its
#: trigger, actuator, or polarity to this edge.
REMEASURE_ACTUATION_KIND: Dict[str, str] = {
    "remeasure_after_fallback_in_loop": "fallback_after_trigger_in_loop",
    "remeasure_after_fallback_guarded_by_trigger":
        "fallback_guarded_by_trigger",
}

# Bounded structural proof, not a symbolic executor. Refuse promotion before
# independent branch facts can grow exponentially.
MAX_FLOW_STATES = 256

#: Canonical runner entrypoints for flow steps that a registered actuator may
#: re-enter.  The verifier compares the actuator's AST-proven callee with the
#: YAML edge's actual `fallback_to`; the registry cannot promote itself merely
#: by spelling `actuation_form: re_execute` beside an unrelated call.
STEP_EXECUTION_ENTRYPOINTS: Dict[str, Tuple[str, ...]] = {
    "1": ("step_rtl_gen",),
    "32": ("_run_postroute_timing_repair",),
}

#: Canonical observation/decision call for the SOURCE step.  A fallback call is
#: evidence for an edge only when the same control path first observes this
#: step's result.  This prevents `2 -> 1` from borrowing step 4's genuine
#: `step_reference_tb -> step_rtl_gen` retry merely because both edges target 1.
STEP_TRIGGER_ENTRYPOINTS: Dict[str, Tuple[str, ...]] = {
    "2": ("step_crosslayer_rewrite_fidelity",),
    "4": ("step_reference_tb",),
    "23": ("_repair_dec.decide",),
    "32": ("_repair_dec.decide",),
}


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
    # `--max-rtl-repair-retries`, and it detects a byte-identical regeneration and stops with
    # FAIL_RTL_REPAIR_INERT instead of burning the counter.
    "4": {
        "class": REMEASURED,
        "actuation_form": "re_execute",
        "why": ("design_one_shot_runner.main re-runs step_rtl_gen (flow step 1) "
                "on a reference-TB failure and re-runs the testbench afterwards"),
        "evidence": {
            "actuate": [
                {"kind": "fallback_after_trigger_in_loop",
                 "file": "programs/design_one_shot_runner.py",
                 "caller": "main", "trigger_callee": "step_reference_tb",
                 "trigger_field": "status",
                 "terminal_values": ["PASS", "SKIP", "WAIVED"],
                 "callee": "step_rtl_gen"},
            ],
            "remeasure": [
                {"kind": "remeasure_after_fallback_in_loop",
                 "file": "programs/design_one_shot_runner.py",
                 "caller": "main", "trigger_callee": "step_reference_tb",
                 "trigger_field": "status",
                 "terminal_values": ["PASS", "SKIP", "WAIVED"],
                 "actuator_callee": "step_rtl_gen",
                 "callee": "step_reference_tb"},
            ],
        },
        # The rollback tier is NOT claimed: the loop never reverts a
        # regeneration that made things worse, it only stops when the bytes stop
        # changing. Recorded so the absence is a decision, not an oversight.
        "not_claimed": {
            "rollback": ("the loop has no undo — a regeneration that makes the "
                         "design worse is kept; it stops on byte-identity "
                         "(FAIL_RTL_REPAIR_INERT), not on a worse measurement"),
        },
    },

    # Step 23 (post-route STA) -> step 32 (the repair pass). The auto-trigger in
    # `step_canonicalize_artefacts` fires on a multi-corner OCV violation — which
    # is step 23's own measurement — and runs the repair.
    "23": {
        "class": ROLLBACK_PROVEN,
        "actuation_form": "re_execute",
        "why": ("phase3_one_shot_runner.step_canonicalize_artefacts fires "
                "_run_postroute_timing_repair on a multi-corner OCV violation and re-measures "
                "the same OCV views on the repaired netlist"),
        "evidence": {
            "actuate": [
                {"kind": "fallback_guarded_by_trigger",
                 "file": "programs/phase3_one_shot_runner.py",
                 "caller": "step_canonicalize_artefacts",
                 "trigger_callee": "_repair_dec.decide",
                 "trigger_field": "repair_needed",
                 "trigger_value": True,
                 "callee": "_run_postroute_timing_repair"},
            ],
            "remeasure": [
                {"kind": "remeasure_after_fallback_guarded_by_trigger",
                 "file": "programs/phase3_one_shot_runner.py",
                 "caller": "step_canonicalize_artefacts",
                 "trigger_callee": "_repair_dec.decide",
                 "trigger_field": "repair_needed",
                 "trigger_value": True,
                 "actuator_callee": "_run_postroute_timing_repair",
                 "callee": "_measure_postrepair_mcorner_ocv"},
            ],
            # THE TOP TIER, EARNED. The undo is the `timing_repair_reverted_
            # regression` branch: on a measured setup regression the repair's
            # outputs are NOT adopted and the pre-repair artefacts are
            # retained. The decision it turns on used to be an inline
            # expression inside a 900-line step function, which is why this
            # entry read `not_claimed` for two tiers — an undo nothing can call
            # is an undo nothing can prove. It now has an address,
            # `repair_result_is_a_regression`, and the branch consults it.
            "rollback": [
                {"kind": "calls",
                 "file": "programs/phase3_one_shot_runner.py",
                 "caller": "step_canonicalize_artefacts",
                 "callee": "repair_result_is_a_regression"},
            ],
            # ...and the proof, in the TEST tier. This is the citation that
            # made this promotion its own change rather than a line edit: a
            # rollback proof is the one evidence role that CANNOT live in the
            # runner, because a runner that tests itself proves nothing. See
            # `_tier_is_modelled` for how a root that models only the runner
            # tier is told apart from a tree where the proof was deleted.
            "rollback_test": [
                {"kind": "calls",
                 "file": ("programs/tests/"
                          "test_timing_repair_reverted_regression.py"),
                 "caller": "_regressed",
                 "callee": "repair_result_is_a_regression"},
            ],
        },
    },

    # Step 32 -> 32, the aggregator's self-edge. Same actuator as 23; recorded
    # separately because the census is per-EDGE and a shared actuator is a fact
    # about the tree, not a reason to count one edge twice or drop one.
    "32": {
        "class": ROLLBACK_PROVEN,
        "actuation_form": "re_execute",
        "why": ("the same auto-trigger; step 32 is where it runs, so the edge "
                "re-enters the step that owns the actuator"),
        "shares_actuator_with": "23",
        "evidence": {
            "actuate": [
                {"kind": "fallback_guarded_by_trigger",
                 "file": "programs/phase3_one_shot_runner.py",
                 "caller": "step_canonicalize_artefacts",
                 "trigger_callee": "_repair_dec.decide",
                 "trigger_field": "repair_needed",
                 "trigger_value": True,
                 "callee": "_run_postroute_timing_repair"},
            ],
            "remeasure": [
                {"kind": "remeasure_after_fallback_guarded_by_trigger",
                 "file": "programs/phase3_one_shot_runner.py",
                 "caller": "step_canonicalize_artefacts",
                 "trigger_callee": "_repair_dec.decide",
                 "trigger_field": "repair_needed",
                 "trigger_value": True,
                 "actuator_callee": "_run_postroute_timing_repair",
                 "callee": "_measure_postrepair_mcorner_ocv"},
            ],
            # Same actuator, same undo, same proof — recorded again rather than
            # cross-referenced, because the census is per-EDGE and an edge that
            # borrows another's evidence by reference cannot be demoted alone.
            "rollback": [
                {"kind": "calls",
                 "file": "programs/phase3_one_shot_runner.py",
                 "caller": "step_canonicalize_artefacts",
                 "callee": "repair_result_is_a_regression"},
            ],
            "rollback_test": [
                {"kind": "calls",
                 "file": ("programs/tests/"
                          "test_timing_repair_reverted_regression.py"),
                 "caller": "_regressed",
                 "callee": "repair_result_is_a_regression"},
            ],
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
    """Return only the module-level runner entrypoint named *name*.

    A class method or nested helper is not callable as the runner entrypoint
    named by a citation.  "Outermost" was still too weak: when no module-level
    definition existed it selected a class/nested decoy at the shallowest
    available depth and promoted evidence that runtime could never enter.
    """
    return next((stmt for stmt in tree.body
                 if isinstance(stmt, (ast.FunctionDef,
                                      ast.AsyncFunctionDef))
                 and stmt.name == name), None)


def _qualified_name(node: ast.AST) -> Optional[str]:
    """Exact call target (`name` or `receiver.method`), never suffix-only."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _qualified_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _static_truth(node: ast.AST) -> Optional[bool]:
    """Truth of deliberately simple constants; `None` means runtime value."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = _static_truth(node.operand)
        return (not inner) if inner is not None else None
    if isinstance(node, ast.BoolOp):
        values = [_static_truth(value) for value in node.values]
        if isinstance(node.op, ast.Or):
            if any(value is True for value in values):
                return True
            return False if all(value is False for value in values) else None
        if isinstance(node.op, ast.And):
            if any(value is False for value in values):
                return False
            return True if all(value is True for value in values) else None
    if isinstance(node, ast.Compare) and len(node.ops) == 1 \
            and len(node.comparators) == 1 \
            and isinstance(node.left, ast.Constant) \
            and isinstance(node.comparators[0], ast.Constant):
        left, right = node.left.value, node.comparators[0].value
        op = node.ops[0]
        try:
            if isinstance(op, (ast.Eq, ast.Is)):
                return left == right
            if isinstance(op, (ast.NotEq, ast.IsNot)):
                return left != right
            if isinstance(op, ast.Lt):
                return left < right
            if isinstance(op, ast.LtE):
                return left <= right
            if isinstance(op, ast.Gt):
                return left > right
            if isinstance(op, ast.GtE):
                return left >= right
        except (TypeError, ValueError):
            return None
    return None


def _static_iterable_empty(node: ast.AST) -> Optional[bool]:
    """Whether a literal iterable is certainly empty/non-empty."""
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return len(node.elts) == 0
    if isinstance(node, ast.Dict):
        return len(node.keys) == 0
    if isinstance(node, (ast.Constant, ast.Str, ast.Bytes)):
        value = getattr(node, "value", None)
        if isinstance(value, (str, bytes, tuple)):
            return len(value) == 0
    return None


def _statement_has_current_loop_break(stmt: ast.stmt) -> bool:
    """A reachable ``break`` owned by the surrounding loop, not a nested one."""
    if isinstance(stmt, ast.Break):
        return True
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef,
                         ast.ClassDef, ast.Lambda,
                         ast.While, ast.For, ast.AsyncFor)):
        return False
    if isinstance(stmt, ast.If):
        truth = _static_truth(stmt.test)
        branches = ([stmt.body] if truth is True else [stmt.orelse]
                    if truth is False else [stmt.body, stmt.orelse])
        return any(_block_has_current_loop_break(list(branch))
                   for branch in branches)
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return _block_has_current_loop_break(list(stmt.body))
    if isinstance(stmt, ast.Try):
        blocks = [list(stmt.body), list(stmt.orelse), list(stmt.finalbody)]
        blocks.extend(list(handler.body) for handler in stmt.handlers)
        return any(_block_has_current_loop_break(block) for block in blocks)
    if isinstance(stmt, ast.Match):
        return any(_block_has_current_loop_break(list(case.body))
                   for case in stmt.cases)
    return False


def _block_has_current_loop_break(statements: List[ast.stmt]) -> bool:
    for stmt in statements:
        if _statement_has_current_loop_break(stmt):
            return True
        if _statement_always_terminates(stmt):
            break
    return False


def _statement_always_terminates(stmt: ast.stmt) -> bool:
    if isinstance(stmt, (ast.Break, ast.Continue, ast.Return, ast.Raise)):
        return True
    if isinstance(stmt, ast.Assert) and _static_truth(stmt.test) is False:
        return True
    if isinstance(stmt, ast.If):
        truth = _static_truth(stmt.test)
        if truth is True:
            return _block_always_terminates(stmt.body)
        if truth is False:
            return _block_always_terminates(stmt.orelse)
        return bool(stmt.body and stmt.orelse
                    and _block_always_terminates(stmt.body)
                    and _block_always_terminates(stmt.orelse))
    if isinstance(stmt, ast.While):
        return (_static_truth(stmt.test) is True
                and not _block_has_current_loop_break(list(stmt.body)))
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return _block_always_terminates(list(stmt.body))
    return False


def _block_always_terminates(statements: List[ast.stmt]) -> bool:
    """A bounded fall-through proof used to exclude calls after terminators."""
    for stmt in statements:
        if _statement_always_terminates(stmt):
            return True
    return False


def _reachable_prefix(statements: List[ast.stmt]) -> List[ast.stmt]:
    out: List[ast.stmt] = []
    for stmt in statements:
        out.append(stmt)
        if _statement_always_terminates(stmt):
            break
    return out


class _LiveScanner:
    """Walk executable structure without laundering obvious dead code.

    Nested function/class/lambda bodies do not execute merely because their
    definition is inside the caller.  Constant-false branches and loops are
    excluded.  This is intentionally a bounded structural proof, not a Python
    interpreter; anything it cannot decide is retained and must be challenged
    by the stronger trigger/control-path citation below.
    """

    def __init__(self) -> None:
        self.calls: List[Tuple[str, ast.Call]] = []
        self.loops: List[ast.AST] = []
        self.breaks = 0

    def statements(self, statements: List[ast.stmt]) -> None:
        for stmt in statements:
            self.node(stmt)
            if _statement_always_terminates(stmt):
                break

    def node(self, node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)):
            return
        if isinstance(node, ast.Call):
            target = _qualified_name(node.func)
            if target is not None:
                self.calls.append((target, node))
        if isinstance(node, ast.Break):
            self.breaks += 1
            return
        if isinstance(node, ast.If):
            self.node(node.test)
            truth = _static_truth(node.test)
            if truth is True:
                self.statements(node.body)
            elif truth is False:
                self.statements(node.orelse)
            else:
                self.statements(node.body)
                self.statements(node.orelse)
            return
        if isinstance(node, ast.While):
            self.node(node.test)
            truth = _static_truth(node.test)
            if truth is not False:
                self.loops.append(node)
                self.statements(node.body)
            if truth is not True:
                self.statements(node.orelse)
            return
        if isinstance(node, (ast.For, ast.AsyncFor)):
            self.node(node.target)
            self.node(node.iter)
            empty = _static_iterable_empty(node.iter)
            if empty is not True:
                self.loops.append(node)
                self.statements(node.body)
            if empty is not False:
                self.statements(node.orelse)
            return
        for child in ast.iter_child_nodes(node):
            self.node(child)


def _scan(node: ast.AST) -> _LiveScanner:
    scanner = _LiveScanner()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        scanner.statements(node.body)
    else:
        scanner.node(node)
    return scanner


def _scan_statements(statements: List[ast.stmt]) -> _LiveScanner:
    scanner = _LiveScanner()
    scanner.statements(statements)
    return scanner


def _called_names(node: ast.AST) -> List[str]:
    return [name for name, _ in _scan(node).calls]


def _calls_inside_loop(fn: ast.AST, callee: str) -> bool:
    """True when *callee* is called from within a `while`/`for` in *fn*.

    Scoped to the loop BODY (and its `orelse`), not the whole function, because
    the point of the citation is that the call repeats.
    """
    for loop in _scan(fn).loops:
        if callee in [name for name, _ in
                      _scan_statements(list(loop.body)).calls]:
            return True
    return False


def _assigned_call(stmt: ast.stmt,
                   callee: str) -> Optional[str]:
    """Name assigned directly from the exact call target, else `None`."""
    value: Optional[ast.AST] = None
    targets: List[ast.AST] = []
    if isinstance(stmt, ast.Assign):
        value, targets = stmt.value, list(stmt.targets)
    elif isinstance(stmt, ast.AnnAssign):
        value, targets = stmt.value, [stmt.target]
    if not isinstance(value, ast.Call) or _qualified_name(value.func) != callee:
        return None
    return next((t.id for t in targets if isinstance(t, ast.Name)), None)


def _test_reads_result(test: ast.AST, result: str,
                       field: Optional[str] = None) -> bool:
    """Whether a guard reads the trigger result (and optional exact field)."""
    if field is None:
        return any(isinstance(n, ast.Name) and n.id == result
                   for n in ast.walk(test))
    for n in ast.walk(test):
        if isinstance(n, ast.Attribute) and n.attr == field \
                and isinstance(n.value, ast.Name) and n.value.id == result:
            return True
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) \
                and n.value.id == result:
            sl = n.slice
            if isinstance(sl, ast.Constant) and sl.value == field:
                return True
    return False


def _field_ref(node: ast.AST, result: str, field: str) -> bool:
    if isinstance(node, ast.Attribute):
        return (node.attr == field and isinstance(node.value, ast.Name)
                and node.value.id == result)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
            and node.value.id == result:
        return isinstance(node.slice, ast.Constant) \
            and node.slice.value == field
    return False


def _field_truth_for_body(test: ast.AST, result: str,
                          field: str) -> Optional[bool]:
    """Exact field value that selects an `if` body; complex tests refuse."""
    if _field_ref(test, result, field):
        return True
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _field_truth_for_body(test.operand, result, field)
        return (not inner) if inner is not None else None
    if isinstance(test, ast.Compare) and len(test.ops) == 1 \
            and len(test.comparators) == 1 \
            and _field_ref(test.left, result, field) \
            and isinstance(test.comparators[0], ast.Constant) \
            and isinstance(test.comparators[0].value, bool):
        value = bool(test.comparators[0].value)
        if isinstance(test.ops[0], (ast.Eq, ast.Is)):
            return value
        if isinstance(test.ops[0], (ast.NotEq, ast.IsNot)):
            return not value
    return None


def _target_writes_result(target: ast.AST, result: str) -> bool:
    if isinstance(target, ast.Name):
        return target.id == result
    if isinstance(target, (ast.Attribute, ast.Subscript)):
        value = target.value
        return isinstance(value, ast.Name) and value.id == result
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_target_writes_result(elt, result) for elt in target.elts)
    return False


def _statement_writes_result(stmt: ast.AST, result: str) -> bool:
    """Reject a trigger receipt overwritten before the guard consumes it."""
    found = False

    def walk(node: ast.AST) -> None:
        nonlocal found
        if found or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.ClassDef, ast.Lambda)):
            return
        targets: List[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        elif isinstance(node, ast.NamedExpr):
            targets = [node.target]
        elif isinstance(node, ast.Delete):
            targets = list(node.targets)
        if any(_target_writes_result(t, result) for t in targets):
            found = True
            return
        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(stmt)
    return found


def _contains_name(node: ast.AST, name: str) -> bool:
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node))


def _statement_taints_result(stmt: ast.AST, result: str,
                             allowed_receivers: Tuple[str, ...] = ()) -> bool:
    """Conservative alias/effect check between trigger receipt and guard."""
    if _statement_writes_result(stmt, result):
        return True
    for node in ast.walk(stmt):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)) and node is not stmt:
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = (list(node.targets) if isinstance(node, ast.Assign)
                       else [node.target])
            if value is not None and _contains_name(value, result) \
                    and not any(_target_writes_result(t, result)
                                for t in targets):
                return True
        if not isinstance(node, ast.Call):
            continue
        target = _qualified_name(node.func) or ""
        if target.startswith(result + "."):
            return True
        if any(_contains_name(arg, result)
               for arg in list(node.args) + [kw.value for kw in node.keywords]) \
                and target not in allowed_receivers:
            return True
    return False


def _target_writes_fact(target: ast.AST, result: str, field: str) -> bool:
    if isinstance(target, ast.Name):
        return target.id == result
    if isinstance(target, ast.Attribute):
        return (target.attr == field and isinstance(target.value, ast.Name)
                and target.value.id == result)
    if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) \
            and target.value.id == result:
        return (isinstance(target.slice, ast.Constant)
                and target.slice.value == field)
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_target_writes_fact(elt, result, field)
                   for elt in target.elts)
    return False


def _contains_bare_result_reference(node: ast.AST, result: str) -> bool:
    """The receipt object itself is carried elsewhere, not merely a field."""
    if isinstance(node, ast.Name):
        return node.id == result
    if isinstance(node, (ast.Attribute, ast.Subscript)):
        return False
    return any(_contains_bare_result_reference(child, result)
               for child in ast.iter_child_nodes(node))


def _statement_taints_fact(stmt: ast.AST, result: str, field: str,
                           allowed_receivers: Tuple[str, ...] = ()) -> bool:
    """Invalidate one established receipt field without rejecting other fields."""
    tainted = False

    def walk(node: ast.AST) -> None:
        nonlocal tainted
        if tainted:
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definition_time = (list(node.decorator_list)
                               + list(node.args.defaults)
                               + [value for value in node.args.kw_defaults
                                  if value is not None])
            if node.returns is not None:
                definition_time.append(node.returns)
            for child in definition_time:
                walk(child)
            return
        if isinstance(node, ast.ClassDef):
            for child in (list(node.decorator_list) + list(node.bases)
                          + [keyword.value for keyword in node.keywords]):
                walk(child)
            return
        if isinstance(node, ast.Lambda):
            for child in (list(node.args.defaults)
                          + [value for value in node.args.kw_defaults
                             if value is not None]):
                walk(child)
            return
        targets: List[ast.AST] = []
        value: Optional[ast.AST] = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.AugAssign):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.NamedExpr):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Delete):
            targets = list(node.targets)
        if any(_target_writes_fact(target, result, field)
               for target in targets):
            tainted = True
            return
        if value is not None and _contains_bare_result_reference(value, result):
            tainted = True
            return
        if isinstance(node, ast.Call):
            target = _qualified_name(node.func) or ""
            if target.startswith(result + "."):
                tainted = True
                return
            if (any(_contains_bare_result_reference(arg, result)
                    for arg in list(node.args)
                    + [kw.value for kw in node.keywords])
                    and target not in allowed_receivers):
                tainted = True
                return
        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(stmt)
    return tainted


def _literal_collection(node: ast.AST) -> Optional[Tuple[Any, ...]]:
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return None
    values: List[Any] = []
    for elt in node.elts:
        if not isinstance(elt, ast.Constant):
            return None
        values.append(elt.value)
    return tuple(values)


def _positive_membership_guard(test: ast.AST, result: str, field: str,
                               terminal_values: Tuple[Any, ...]) -> bool:
    """The terminal set being true must be sufficient to select the body."""
    if isinstance(test, ast.Compare) and len(test.ops) == 1 \
            and len(test.comparators) == 1 \
            and isinstance(test.ops[0], ast.In) \
            and _field_ref(test.left, result, field):
        actual = _literal_collection(test.comparators[0])
        return actual is not None and set(actual) == set(terminal_values)
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        # `terminal OR retry_budget_exhausted`: terminal membership is enough
        # to exit.  A statically-true sibling would make fallback unreachable.
        if any(_static_truth(value) is True for value in test.values):
            return False
        return any(_positive_membership_guard(value, result, field,
                                               terminal_values)
                   for value in test.values)
    return False


def _known_test_truth(
        test: ast.AST,
        known_bool: Optional[Tuple[str, str, bool]],
        excluded_membership: Optional[Tuple[str, str, Tuple[Any, ...]]],
        ) -> Optional[bool]:
    """Evaluate a guard from facts established by the owning trigger branch."""
    truth = _static_truth(test)
    if truth is not None:
        return truth
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _known_test_truth(
            test.operand, known_bool, excluded_membership)
        return (not inner) if inner is not None else None
    if isinstance(test, ast.BoolOp):
        values = [_known_test_truth(
            value, known_bool, excluded_membership)
                  for value in test.values]
        if isinstance(test.op, ast.Or):
            if any(value is True for value in values):
                return True
            return False if all(value is False for value in values) else None
        if isinstance(test.op, ast.And):
            if any(value is False for value in values):
                return False
            return True if all(value is True for value in values) else None
    if known_bool is not None:
        result, field, value = known_bool
        body_value = _field_truth_for_body(test, result, field)
        if body_value is not None:
            return body_value == value
    if excluded_membership is not None \
            and isinstance(test, ast.Compare) \
            and len(test.ops) == 1 and len(test.comparators) == 1:
        result, field, excluded = excluded_membership
        if _field_ref(test.left, result, field):
            actual = _literal_collection(test.comparators[0])
            if actual is not None and set(actual) == set(excluded):
                if isinstance(test.ops[0], ast.In):
                    return False
                if isinstance(test.ops[0], ast.NotIn):
                    return True
    return None


def _expression_call_targets(node: Optional[ast.AST]) -> List[str]:
    """Call targets in evaluation order for straight-line expressions."""
    if node is None:
        return []
    if isinstance(node, (ast.Lambda, ast.BoolOp, ast.IfExp,
                         ast.ListComp, ast.SetComp, ast.DictComp,
                         ast.GeneratorExp)):
        # Short-circuit/comprehension control flow needs an explicit proof;
        # flattening it would recreate the mutually-exclusive-path bug.
        return []
    if isinstance(node, ast.Call):
        out: List[str] = []
        out.extend(_expression_call_targets(node.func))
        for arg in node.args:
            out.extend(_expression_call_targets(arg))
        for kw in node.keywords:
            out.extend(_expression_call_targets(kw.value))
        target = _qualified_name(node.func)
        if target is not None:
            out.append(target)
        return out
    out = []
    for child in ast.iter_child_nodes(node):
        out.extend(_expression_call_targets(child))
    return out


def _straight_statement_calls(stmt: ast.stmt) -> List[str]:
    if isinstance(stmt, ast.Assign):
        return _expression_call_targets(stmt.value)
    if isinstance(stmt, ast.AnnAssign):
        return _expression_call_targets(stmt.value)
    if isinstance(stmt, ast.AugAssign):
        return _expression_call_targets(stmt.value)
    if isinstance(stmt, ast.Expr):
        return _expression_call_targets(stmt.value)
    if isinstance(stmt, (ast.Return, ast.Raise)):
        value = stmt.value if isinstance(stmt, ast.Return) else stmt.exc
        return _expression_call_targets(value)
    return []


_EXPR_FACT_PREFIX = "@expr:"
_ALIAS_FACT_PREFIX = "@alias:"
_EXPR_FACT_SEPARATOR = "\0@"


def _value_predicate_key(node: ast.AST) -> Optional[str]:
    if isinstance(node, (ast.Name, ast.Attribute)):
        return _qualified_name(node)
    if isinstance(node, ast.Subscript):
        base = _qualified_name(node.value)
        item = node.slice
        if (base is not None
                and isinstance(item, ast.Constant)
                and isinstance(item.value, (str, int))):
            return f"{base}[{item.value!r}]"
    return None


def _expression_dependencies(node: ast.AST) -> List[str]:
    """Maximal value references whose writes invalidate an expression fact."""
    direct = _value_predicate_key(node)
    if direct is not None:
        return [direct]
    return sorted({dep for child in ast.iter_child_nodes(node)
                   for dep in _expression_dependencies(child)})


def _expression_fact_key(node: ast.AST, body: str) -> str:
    deps = "\0".join(_expression_dependencies(node))
    return f"{_EXPR_FACT_PREFIX}{deps}{_EXPR_FACT_SEPARATOR}{body}"


def _expression_fact_dependencies(key: str) -> List[str]:
    if not key.startswith(_EXPR_FACT_PREFIX) \
            or _EXPR_FACT_SEPARATOR not in key:
        return []
    encoded = key[len(_EXPR_FACT_PREFIX):].split(
        _EXPR_FACT_SEPARATOR, 1)[0]
    return encoded.split("\0") if encoded else []


def _predicate_ref(node: ast.AST) -> Optional[Tuple[str, bool]]:
    """Canonical bounded predicate identity plus its positive polarity.

    Complementary comparisons share one key with opposite polarity.  Compound
    boolean expressions also retain their whole-expression identity: a false
    ``a and b`` cannot be decomposed into one particular false operand, but it
    still contradicts a later true ``a and b``.
    """
    direct = _value_predicate_key(node)
    if direct is not None:
        return direct, True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        ref = _predicate_ref(node.operand)
        return (ref[0], not ref[1]) if ref is not None else None
    if (isinstance(node, ast.Compare)
            and len(node.ops) == 1 and len(node.comparators) == 1):
        pairs = {
            ast.Eq: ("eq", True), ast.NotEq: ("eq", False),
            ast.Is: ("is", True), ast.IsNot: ("is", False),
            ast.Lt: ("lt", True), ast.GtE: ("lt", False),
            ast.LtE: ("le", True), ast.Gt: ("le", False),
            ast.In: ("in", True), ast.NotIn: ("in", False),
        }
        pair = next((value for cls, value in pairs.items()
                     if isinstance(node.ops[0], cls)), None)
        if pair is not None:
            family, polarity = pair
            left = ast.dump(node.left, annotate_fields=True,
                            include_attributes=False)
            right = ast.dump(node.comparators[0], annotate_fields=True,
                             include_attributes=False)
            return _expression_fact_key(
                node, f"{family}:{left}:{right}"), polarity
    if isinstance(node, ast.BoolOp):
        return (_expression_fact_key(
            node, ast.dump(node, annotate_fields=True,
                           include_attributes=False)), True)
    return None


def _predicate_key(node: ast.AST) -> Optional[str]:
    ref = _predicate_ref(node)
    return ref[0] if ref is not None else None


def _fact_truth(node: ast.AST,
                facts: Dict[str, bool]) -> Optional[bool]:
    ref = _predicate_ref(node)
    if ref is None or ref[0] not in facts:
        return None
    value = facts[ref[0]]
    return value if ref[1] else not value


def _path_test_truth(test: ast.AST, facts: Dict[str, bool]) -> Optional[bool]:
    """Evaluate only predicates established on this concrete proof path."""
    truth = _static_truth(test)
    if truth is not None:
        return truth
    known = _fact_truth(test, facts)
    if known is not None:
        return known
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _path_test_truth(test.operand, facts)
        return (not inner) if inner is not None else None
    if isinstance(test, ast.BoolOp):
        values = [_path_test_truth(value, facts) for value in test.values]
        if isinstance(test.op, ast.And):
            if any(value is False for value in values):
                return False
            return True if all(value is True for value in values) else None
        if isinstance(test.op, ast.Or):
            if any(value is True for value in values):
                return True
            return False if all(value is False for value in values) else None
    if (isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and isinstance(test.comparators[0].value, bool)):
        key = _predicate_key(test.left)
        known = facts.get(key) if key is not None else None
        if known is not None:
            expected = test.comparators[0].value
            if isinstance(test.ops[0], (ast.Eq, ast.Is)):
                return known is expected
            if isinstance(test.ops[0], (ast.NotEq, ast.IsNot)):
                return known is not expected
    return None


def _combined_test_truth(
        test: ast.AST, facts: Dict[str, bool],
        known_bool: Optional[Tuple[str, str, bool]],
        excluded_membership: Optional[Tuple[str, str, Tuple[Any, ...]]],
        ) -> Optional[bool]:
    """Three-valued truth from trigger facts plus path-local predicates."""
    known = _known_test_truth(test, known_bool, excluded_membership)
    if known is not None:
        return known
    fact_truth = _fact_truth(test, facts)
    if fact_truth is not None:
        return fact_truth
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _combined_test_truth(
            test.operand, facts, known_bool, excluded_membership)
        return (not inner) if inner is not None else None
    if isinstance(test, ast.BoolOp):
        values = [_combined_test_truth(
            value, facts, known_bool, excluded_membership)
                  for value in test.values]
        if isinstance(test.op, ast.And):
            if any(value is False for value in values):
                return False
            return True if all(value is True for value in values) else None
        if isinstance(test.op, ast.Or):
            if any(value is True for value in values):
                return True
            return False if all(value is False for value in values) else None
    return _path_test_truth(test, facts)


def _path_facts_for_truth(test: ast.AST,
                          truth: bool) -> Dict[str, bool]:
    """Facts guaranteed by selecting one side of a bounded predicate."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _path_facts_for_truth(test.operand, not truth)
    ref = _predicate_ref(test)
    guaranteed: Dict[str, bool] = {}
    if ref is not None:
        guaranteed[ref[0]] = truth if ref[1] else not truth
    if isinstance(test, ast.BoolOp):
        selected = ((isinstance(test.op, ast.And) and truth)
                    or (isinstance(test.op, ast.Or) and not truth))
        if not selected:
            return guaranteed
        merged = dict(guaranteed)
        for value in test.values:
            for name, polarity in _path_facts_for_truth(value, truth).items():
                if name in merged and merged[name] is not polarity:
                    return {}
                merged[name] = polarity
        return merged
    if (isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and isinstance(test.comparators[0].value, bool)):
        key = _predicate_key(test.left)
        if key is not None:
            expected = test.comparators[0].value
            equal = isinstance(test.ops[0], (ast.Eq, ast.Is))
            unequal = isinstance(test.ops[0], (ast.NotEq, ast.IsNot))
            if equal or unequal:
                return {key: expected is (truth if equal else not truth)}
    return guaranteed


def _target_predicate_keys(target: ast.AST) -> List[str]:
    key = _predicate_key(target)
    if key is not None:
        return [key]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [key for elt in target.elts
                for key in _target_predicate_keys(elt)]
    return []


def _target_invalidates_fact(target_key: str, fact_key: str) -> bool:
    if (fact_key == target_key
            or fact_key.startswith(target_key + ".")
            or fact_key.startswith(target_key + "[")):
        return True
    if fact_key.startswith(_EXPR_FACT_PREFIX):
        return any(dep == target_key
                   or dep.startswith(target_key + ".")
                   or dep.startswith(target_key + "[")
                   for dep in _expression_fact_dependencies(fact_key))
    return False


def _alias_fact(left: str, right: str) -> str:
    first, second = sorted((left, right))
    return f"{_ALIAS_FACT_PREFIX}{first}\0{second}"


def _alias_pair(key: str) -> Optional[Tuple[str, str]]:
    if not key.startswith(_ALIAS_FACT_PREFIX):
        return None
    parts = key[len(_ALIAS_FACT_PREFIX):].split("\0", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else None


def _close_alias_facts(facts: Dict[str, bool]) -> Optional[Dict[str, bool]]:
    """Propagate equality/inversion aliases; reject contradictory closure."""
    out = dict(facts)
    changed = True
    while changed:
        changed = False
        for key, same_polarity in list(out.items()):
            pair = _alias_pair(key)
            if pair is None:
                continue
            left, right = pair
            if left in out and right in out:
                if out[right] is not (out[left] if same_polarity
                                      else not out[left]):
                    return None
            elif left in out:
                out[right] = out[left] if same_polarity else not out[left]
                changed = True
            elif right in out:
                out[left] = out[right] if same_polarity else not out[right]
                changed = True
    return out


def _normalise_flow_states(states: set) -> set:
    """Store first-seen plus simple predicate facts without merging paths."""
    out = set()
    for state in states:
        if isinstance(state, bool):
            out.add((state, frozenset()))
        else:
            seen, facts = state
            out.add((bool(seen), frozenset(facts)))
    return out


def _states_with_facts(states: set, updates: Dict[str, bool]) -> set:
    out = set()
    for seen, facts in _normalise_flow_states(states):
        merged = dict(facts)
        if any(name in merged and merged[name] is not value
               for name, value in updates.items()):
            continue
        merged.update(updates)
        closed = _close_alias_facts(merged)
        if closed is not None:
            out.add((seen, frozenset(closed.items())))
    return out


def _update_written_predicates(states: set, stmt: ast.stmt) -> set:
    targets: List[ast.AST] = []
    value: Optional[ast.AST] = None
    if isinstance(stmt, ast.Assign):
        targets, value = list(stmt.targets), stmt.value
    elif isinstance(stmt, ast.AnnAssign):
        targets, value = [stmt.target], stmt.value
    elif isinstance(stmt, ast.AugAssign):
        targets, value = [stmt.target], stmt.value
    elif isinstance(stmt, ast.Delete):
        targets = list(stmt.targets)
    target_keys = [key for target in targets
                   for key in _target_predicate_keys(target)]
    out = set()
    for seen, facts in _normalise_flow_states(states):
        old = dict(facts)
        constrained = any(
            any(_target_invalidates_fact(target, name)
                for target in target_keys)
            or any(
                _target_invalidates_fact(target, endpoint)
                for pair in [_alias_pair(name)] if pair is not None
                for endpoint in pair for target in target_keys)
            for name in old)
        updated = {
            name: polarity for name, polarity in facts
            if not any(_target_invalidates_fact(target, name)
                       for target in target_keys)
            and not any(
                _target_invalidates_fact(target, endpoint)
                for pair in [_alias_pair(name)] if pair is not None
                for endpoint in pair for target in target_keys)
        }
        learned = (_path_test_truth(value, old)
                   if value is not None else None)
        rhs_ref = (_predicate_ref(value)
                   if value is not None
                   and not isinstance(stmt, ast.AugAssign) else None)
        if isinstance(stmt, ast.AugAssign) and target_keys:
            prior = _fact_truth(stmt.target, old)
            operand = _path_test_truth(stmt.value, old)
            if isinstance(stmt.op, ast.BitOr) \
                    and (prior is True or operand is True):
                learned = True
            elif isinstance(stmt.op, ast.BitAnd) \
                    and (prior is False or operand is False):
                learned = False
            elif isinstance(stmt.op, ast.BitXor) \
                    and prior is not None and operand is not None:
                learned = prior is not operand
            else:
                learned = None
        if learned is None and constrained and rhs_ref is None:
            # A previously constrained predicate was rewritten in a way this
            # bounded proof cannot evaluate.  Exploring both values would
            # manufacture an existential path, so fail this path closed.
            continue
        if rhs_ref is not None:
            for target in target_keys:
                if target != rhs_ref[0]:
                    updated[_alias_fact(target, rhs_ref[0])] = rhs_ref[1]
        if learned is not None:
            for target in target_keys:
                updated[target] = learned
        closed = _close_alias_facts(updated)
        if closed is not None:
            out.add((seen, frozenset(closed.items())))
    return out


def _advance_call_states(states: set, calls: List[str], first: str,
                         second: str) -> Tuple[set, bool]:
    current = _normalise_flow_states(states)
    success = False
    for target in calls:
        if target == second and any(seen for seen, _ in current):
            success = True
        if target == first:
            current = {(True, facts) for _, facts in current}
    return current, success


def _flow_block(
        statements: List[ast.stmt], states: set, first: str, second: str,
        known_bool: Optional[Tuple[str, str, bool]] = None,
        excluded_membership: Optional[Tuple[str, str, Tuple[Any, ...]]] = None,
        ) -> Tuple[set, bool]:
    current = _normalise_flow_states(states)
    success = False
    for stmt in statements:
        if not current:
            break
        current, hit = _flow_statement(
            stmt, current, first, second, known_bool, excluded_membership)
        if len(current) > MAX_FLOW_STATES:
            return set(), False
        success = success or hit
    return current, success


def _flow_statement(
        stmt: ast.stmt, states: set, first: str, second: str,
        known_bool: Optional[Tuple[str, str, bool]] = None,
        excluded_membership: Optional[Tuple[str, str, Tuple[Any, ...]]] = None,
        ) -> Tuple[set, bool]:
    states = _normalise_flow_states(states)
    fact = (known_bool if known_bool is not None
            else excluded_membership if excluded_membership is not None
            else None)
    taint_node: Optional[ast.AST] = stmt
    if isinstance(stmt, (ast.If, ast.While)):
        taint_node = stmt.test
    elif isinstance(stmt, (ast.For, ast.AsyncFor)):
        taint_node = stmt.iter
    elif isinstance(stmt, (ast.With, ast.AsyncWith)):
        taint_node = None
        for item in stmt.items:
            if fact is not None and _statement_taints_fact(
                    item.context_expr, fact[0], fact[1]):
                return set(), False
    elif isinstance(stmt, (ast.Try, ast.Match)):
        taint_node = None
    if fact is not None and taint_node is not None \
            and _statement_taints_fact(
                taint_node, fact[0], fact[1],
                allowed_receivers=("plan.append",)):
        # Once the receipt (or anything aliased from/passed for mutation) is
        # changed, the established branch fact is no longer authoritative.
        # Refuse the rest of this proof path instead of carrying stale truth.
        return set(), False
    if isinstance(stmt, ast.If):
        # Evidence calls in a short-circuit predicate are deliberately not
        # accepted.  The branch bodies retain their path identity.
        out: set = set()
        success = False
        for state in states:
            _, frozen_facts = state
            truth = _combined_test_truth(
                stmt.test, dict(frozen_facts),
                known_bool, excluded_membership)
            branches = ([(stmt.body, True)] if truth is True
                        else [(stmt.orelse, False)] if truth is False
                        else [(stmt.body, True), (stmt.orelse, False)])
            for branch, test_truth in branches:
                branch_states = _states_with_facts(
                    {state}, _path_facts_for_truth(
                        stmt.test, test_truth))
                if not branch_states:
                    continue
                branch_out, hit = _flow_block(
                    list(branch), branch_states, first, second,
                    known_bool, excluded_membership)
                out.update(branch_out)
                if len(out) > MAX_FLOW_STATES:
                    return set(), False
                success = success or hit
        return out, success
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return _flow_block(list(stmt.body), set(states), first, second,
                           known_bool, excluded_membership)
    if isinstance(stmt, ast.Try):
        # Exceptions and finally control transfer can replace a return/break.
        # No registered shipped citation needs a try path, so refuse to use
        # calls in or beyond it rather than guess and manufacture execution.
        return set(), False
    if isinstance(stmt, ast.Match):
        # Pattern exhaustiveness/guards are likewise outside this bounded
        # proof.  A future shipped citation can add explicit semantics first.
        return set(), False
    if isinstance(stmt, ast.While):
        # Nested loop ordering/back-edges need their own citation.  Refuse to
        # compose them into an outer straight-line proof.  A statically-false
        # loop executes its else suite; a statically-true loop with no owned
        # break provably cannot fall through to later evidence.
        truth = _static_truth(stmt.test)
        if truth is False:
            return _flow_block(list(stmt.orelse), set(states), first, second,
                               known_bool, excluded_membership)
        return set(), False
    if isinstance(stmt, (ast.For, ast.AsyncFor)):
        # Iteration and iterator exceptions are outside this bounded proof.
        if _static_iterable_empty(stmt.iter) is True:
            return _flow_block(list(stmt.orelse), set(states), first, second,
                               known_bool, excluded_membership)
        return set(), False
    current, success = _advance_call_states(
        states, _straight_statement_calls(stmt), first, second)
    current = _update_written_predicates(current, stmt)
    if _statement_always_terminates(stmt):
        return set(), success
    return current, success


def _ordered_calls_on_a_path(statements: List[ast.stmt], first: str,
                             second: str, *, first_already: bool = False
                             , known_bool: Optional[Tuple[str, str, bool]] = None
                             , excluded_membership: Optional[
                                 Tuple[str, str, Tuple[Any, ...]]] = None
                             ) -> bool:
    _, success = _flow_block(
        statements, {(first_already, frozenset())}, first, second,
        known_bool, excluded_membership)
    return success


def _call_executes_on_a_path(
        statements: List[ast.stmt], callee: str,
        known_bool: Optional[Tuple[str, str, bool]] = None,
        excluded_membership: Optional[Tuple[str, str, Tuple[Any, ...]]] = None,
        ) -> bool:
    """Existential live-path call proof, using the same flow as ordering."""
    return _ordered_calls_on_a_path(
        statements, "<path-already-live>", callee, first_already=True,
        known_bool=known_bool, excluded_membership=excluded_membership)


def _call_path_falls_through(
        stmt: ast.stmt, callee: str,
        known_bool: Optional[Tuple[str, str, bool]] = None,
        excluded_membership: Optional[Tuple[str, str, Tuple[Any, ...]]] = None,
        ) -> bool:
    states, _ = _flow_statement(
        stmt, {False}, callee, "<never>",
        known_bool, excluded_membership)
    return any(seen for seen, _ in states)


def _loop_fallback_sites(fn: ast.AST, trigger: str, callee: str,
                         field: Optional[str],
                         terminal_values: Tuple[Any, ...]
                         ) -> List[Tuple[ast.AST, int, bool, str]]:
    """Fallback sites on the live complement of an exact terminal guard.

    The final flag records whether at least one path that actually executes the
    fallback also reaches the next top-level statement.  Keeping that path bit
    is essential: a call hidden under ``if retry: ...; break`` is an actuator,
    but it cannot borrow the loop's later back-edge as remeasurement evidence.
    """
    if field is None or not terminal_values:
        return []
    sites: List[Tuple[ast.AST, int, bool, str]] = []
    for loop in _scan(fn).loops:
        body = list(loop.body)
        for trigger_i, stmt in enumerate(body):
            result = _assigned_call(stmt, trigger)
            if result is None:
                continue
            for guard_i in range(trigger_i + 1, len(body)):
                guard = body[guard_i]
                if any(_statement_taints_result(
                           mid, result, allowed_receivers=("plan.append",))
                       for mid in body[trigger_i + 1:guard_i]):
                    break
                if not isinstance(guard, ast.If):
                    continue
                if _statement_taints_result(guard.test, result):
                    continue
                if not _positive_membership_guard(
                        guard.test, result, field, terminal_values):
                    continue
                if not _block_always_terminates(list(guard.body)):
                    continue
                later = body[guard_i + 1:]
                live_states: set = {False}
                excluded = (result, field, terminal_values)
                for offset, later_stmt in enumerate(later):
                    if not live_states:
                        break
                    if _call_executes_on_a_path(
                            [later_stmt], callee,
                            excluded_membership=excluded):
                        sites.append((
                            loop,
                            guard_i + 1 + offset,
                            _call_path_falls_through(
                                later_stmt, callee,
                                excluded_membership=excluded),
                            result,
                        ))
                    live_states, _ = _flow_statement(
                        later_stmt, live_states,
                        "<irrelevant-first>", "<irrelevant-second>",
                        excluded_membership=excluded)
    return sites


def _fallback_after_trigger_in_loop(fn: ast.AST, trigger: str, callee: str,
                                    field: Optional[str],
                                    terminal_values: Tuple[Any, ...]) -> bool:
    return bool(_loop_fallback_sites(
        fn, trigger, callee, field, terminal_values))


def _remeasure_after_fallback_in_loop(
        fn: ast.AST, trigger: str, actuator: str, measurement: str,
        field: Optional[str], terminal_values: Tuple[Any, ...]) -> bool:
    for loop, fallback_i, fallback_falls_through, result \
            in _loop_fallback_sites(
            fn, trigger, actuator, field, terminal_values):
        body = list(loop.body)
        fallback_stmt = body[fallback_i]
        after = body[fallback_i + 1:]
        excluded = (result, str(field), terminal_values)

        # The actuator and measurement may share a compound statement.  They
        # count only if one concrete branch orders actuator before measurement.
        if _ordered_calls_on_a_path(
                [fallback_stmt], actuator, measurement,
                excluded_membership=excluded):
            return True

        if not fallback_falls_through:
            continue

        # Or measurement may occur later, but only on a path continuing from
        # an actuator call that fell through the fallback statement.
        if _ordered_calls_on_a_path(
                after, actuator, measurement, first_already=True,
                excluded_membership=excluded):
            return True

        # Reaching the loop back-edge re-enters the trigger measurement on the
        # next iteration.  Use the SAME trigger fact here as explicit ordering:
        # a suffix whose known complement necessarily breaks must not be
        # mistaken for a live back-edge by the fact-free terminator helper.
        suffix_states, _ = _flow_block(
            after, {True}, actuator, "<never>",
            excluded_membership=excluded)
        if suffix_states:
            return True
    return False


def _guarded_fallback_branch(fn: ast.AST, trigger: str, callee: str,
                             field: Optional[str],
                             expected_value: Optional[bool]
                             ) -> Optional[
                                 Tuple[List[ast.stmt], str, str, bool]]:
    """Exact live trigger-polarity branch that owns the fallback."""
    body = _reachable_prefix(list(getattr(fn, "body", [])))
    for trigger_i, stmt in enumerate(body):
        result = _assigned_call(stmt, trigger)
        if result is None:
            continue
        for guard_i, guard in enumerate(body[trigger_i + 1:],
                                        start=trigger_i + 1):
            if any(_statement_taints_result(mid, result)
                   for mid in body[trigger_i + 1:guard_i]):
                break
            if not isinstance(guard, ast.If) \
                    or not _test_reads_result(guard.test, result, field):
                continue
            if _statement_taints_result(guard.test, result):
                continue
            if field is None or expected_value is None:
                continue
            body_value = _field_truth_for_body(guard.test, result, field)
            if body_value is None:
                continue
            selected = (list(guard.body) if body_value == expected_value
                        else list(guard.orelse))
            opposite = (list(guard.orelse) if body_value == expected_value
                        else list(guard.body))
            selected_fact = (result, field, expected_value)
            opposite_fact = (result, field, not expected_value)
            if (_call_executes_on_a_path(
                    selected, callee, known_bool=selected_fact)
                    and not _call_executes_on_a_path(
                        opposite, callee, known_bool=opposite_fact)):
                return selected, result, field, expected_value
    return None


def _fallback_guarded_by_trigger(fn: ast.AST, trigger: str, callee: str,
                                 field: Optional[str],
                                 expected_value: Optional[bool]) -> bool:
    """A live branch on a trigger result contains the exact fallback call."""
    return _guarded_fallback_branch(
        fn, trigger, callee, field, expected_value) is not None


def _remeasure_after_fallback_guarded_by_trigger(
        fn: ast.AST, trigger: str, actuator: str, measurement: str,
        field: Optional[str], expected_value: Optional[bool]) -> bool:
    branch_info = _guarded_fallback_branch(
        fn, trigger, actuator, field, expected_value)
    if branch_info is None:
        return False
    branch, result, exact_field, exact_value = branch_info
    return _ordered_calls_on_a_path(
        branch, actuator, measurement,
        known_bool=(result, exact_field, exact_value))


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

    if kind in ("calls", "call_in_loop", "defines",
                "fallback_after_trigger_in_loop",
                "fallback_guarded_by_trigger",
                "remeasure_after_fallback_in_loop",
                "remeasure_after_fallback_guarded_by_trigger"):
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
        if kind in ("fallback_after_trigger_in_loop",
                    "fallback_guarded_by_trigger",
                    "remeasure_after_fallback_in_loop",
                    "remeasure_after_fallback_guarded_by_trigger"):
            trigger = str(cit.get("trigger_callee") or "")
            field = cit.get("trigger_field")
            field_s = str(field) if field is not None else None
            if kind in ("fallback_after_trigger_in_loop",
                        "remeasure_after_fallback_in_loop"):
                raw_terminal = cit.get("terminal_values")
                if not isinstance(raw_terminal, (list, tuple)) \
                        or not raw_terminal:
                    return False, (f"{rel}:{caller} citation declares no "
                                   "terminal_values; loop polarity is unknown")
                terminal_values = tuple(raw_terminal)
                if kind == "fallback_after_trigger_in_loop":
                    ok = _fallback_after_trigger_in_loop(
                        fn, trigger, callee, field_s, terminal_values)
                else:
                    actuator = str(cit.get("actuator_callee") or "")
                    ok = _remeasure_after_fallback_in_loop(
                        fn, trigger, actuator, callee, field_s,
                        terminal_values)
                return ok, (
                    f"{rel}:{caller} proves {kind} for {trigger} -> {callee} "
                    f"when {field_s} is outside {list(terminal_values)}" if ok
                    else f"{rel}:{caller} has no live {kind} proof for "
                    f"{trigger} -> {callee} with terminal {field_s} values "
                    f"{list(terminal_values)}")
            expected_value = cit.get("trigger_value")
            if not isinstance(expected_value, bool):
                return False, (f"{rel}:{caller} citation declares no boolean "
                               "trigger_value; branch polarity is unknown")
            if kind == "fallback_guarded_by_trigger":
                ok = _fallback_guarded_by_trigger(
                    fn, trigger, callee, field_s, expected_value)
            else:
                actuator = str(cit.get("actuator_callee") or "")
                ok = _remeasure_after_fallback_guarded_by_trigger(
                    fn, trigger, actuator, callee, field_s, expected_value)
            return ok, (
                f"{rel}:{caller} proves {kind} on {trigger}'s "
                f"{field_s or 'result'}={expected_value} branch" if ok else
                f"{rel}:{caller} has no live {kind} proof on {trigger}'s "
                f"{field_s or 'result'}={expected_value} branch")
        if kind == "calls":
            ok = callee in _called_names(fn)
            return ok, (f"{rel}:{caller} calls {callee}" if ok
                        else f"{rel}:{caller} does not call {callee}")
        ok = _calls_inside_loop(fn, callee)
        return ok, (f"{rel}:{caller} calls {callee} inside a loop" if ok
                    else f"{rel}:{caller} does not call {callee} inside a loop")

    return False, f"unknown citation kind {kind!r} — this program cannot evaluate it"


def _remeasure_extends_actuation(remeasure: Dict[str, Any],
                                 actuation: Dict[str, Any]) -> bool:
    """Whether one remeasurement citation continues one accepted actuation."""
    expected_kind = REMEASURE_ACTUATION_KIND.get(str(remeasure.get("kind")))
    if expected_kind is None or actuation.get("kind") != expected_kind:
        return False
    if any(remeasure.get(field) != actuation.get(field) for field in (
            "file", "caller", "trigger_callee", "trigger_field")):
        return False
    if remeasure.get("actuator_callee") != actuation.get("callee"):
        return False
    if expected_kind == "fallback_after_trigger_in_loop":
        return tuple(remeasure.get("terminal_values") or ()) == tuple(
            actuation.get("terminal_values") or ())
    return (isinstance(remeasure.get("trigger_value"), bool)
            and remeasure.get("trigger_value")
            is actuation.get("trigger_value"))


def classify_edge(step_id: str, root: Path,
                  fallback_to: Optional[str] = None) -> Dict[str, Any]:
    """The class an edge EARNS, plus every citation and how it resolved."""
    entry = REGISTRY.get(step_id)
    rec: Dict[str, Any] = {
        "step": step_id,
        "registered": entry is not None,
        "declared_class": (entry or {}).get("class", DECLARED_ONLY),
        "actuation_form": (entry or {}).get("actuation_form"),
        "fallback_to": fallback_to,
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
    actuation_form = rec["actuation_form"]
    non_reexecution = actuation_form != "re_execute"
    if actuation_form is None:
        rec["problems"].append(
            f"CLC-ACTUATION-FORM-MISSING: edge {step_id} has a registry entry "
            "but does not explicitly declare actuation_form='re_execute'; "
            "an omitted field cannot prove that the fallback ran")
    elif non_reexecution:
        rec["problems"].append(
            f"CLC-NON-REEXECUTION-ACTUATION: edge {step_id} declares "
            f"actuation_form={actuation_form!r}; refusing or retaining a "
            "candidate does not re-enter the declared fallback step and "
            "cannot earn EXECUTABLE")

    expected_entrypoints = (STEP_EXECUTION_ENTRYPOINTS.get(fallback_to)
                            if fallback_to is not None else None)
    expected_triggers = STEP_TRIGGER_ENTRYPOINTS.get(step_id)
    if fallback_to is None:
        rec["problems"].append(
            f"CLC-FALLBACK-TARGET-MISSING: edge {step_id} has registered "
            "execution evidence but the flow declares no usable fallback_to")
    elif expected_entrypoints is None:
        rec["problems"].append(
            f"CLC-FALLBACK-ENTRYPOINT-UNKNOWN: edge {step_id} falls back to "
            f"step {fallback_to}, whose runner entrypoint is not registered; "
            "the actuator cannot be bound to the declared edge")
    if expected_triggers is None:
        rec["problems"].append(
            f"CLC-TRIGGER-ENTRYPOINT-UNKNOWN: edge {step_id} has no canonical "
            "source-step trigger entrypoint; a fallback call from another "
            "edge cannot be distinguished from this edge firing")

    satisfied: List[str] = []
    eligible_actuations: List[Dict[str, Any]] = []
    for role in EVIDENCE_ROLES:
        cits = evidence.get(role) or []
        if not cits:
            continue
        role_ok = True
        for cit in cits:
            ok, reason = _resolve_citation(cit, root)
            kind = cit.get("kind")
            structural = kind in ROLE_CITATION_KINDS[role]
            bound_to_fallback = True
            bound_to_trigger = True
            joined_to_actuation = True
            if role in ("actuate", "remeasure"):
                actuator = (cit.get("callee") if role == "actuate"
                            else cit.get("actuator_callee"))
                bound_to_fallback = bool(
                    expected_entrypoints
                    and str(actuator or "") in expected_entrypoints)
                bound_to_trigger = bool(
                    expected_triggers
                    and str(cit.get("trigger_callee") or "")
                    in expected_triggers)
            if role == "remeasure":
                joined_to_actuation = any(
                    _remeasure_extends_actuation(cit, actuation)
                    for actuation in eligible_actuations)
            tier_modelled = _tier_is_modelled(role, cit, root)
            eligible = (ok and structural and bound_to_fallback
                        and bound_to_trigger and joined_to_actuation
                        and tier_modelled)
            citation_record = {
                "role": role, "citation": cit, "resolved": ok,
                "structural": structural,
                "bound_to_fallback": bound_to_fallback,
                "bound_to_trigger": bound_to_trigger,
                "tier_modelled": tier_modelled,
                "eligible": eligible, "reason": reason,
            }
            if role == "remeasure":
                citation_record["joined_to_actuation"] = joined_to_actuation
            rec["citations"].append(citation_record)
            if role == "actuate" and eligible:
                eligible_actuations.append(cit)
            if not ok:
                role_ok = False
                if tier_modelled:
                    rec["problems"].append(
                        f"CLC-EVIDENCE-MISSING: edge {step_id} claims "
                        f"{entry.get('class')} on {role} evidence that no "
                        f"longer resolves — {reason}")
                else:
                    # NOT ASKED, NOT MISSING. The role stays unsatisfied, so
                    # the edge is demoted; it simply is not reported as rot.
                    rec["problems_not_raised"] = (
                        rec.get("problems_not_raised") or [])
                    rec["problems_not_raised"].append(
                        f"CLC-TIER-NOT-MODELLED: edge {step_id} cites {role} "
                        f"evidence in {TEST_TIER_DIR}/, which this root does "
                        f"not model at all — demoted, not reported as missing")
            if not structural:
                role_ok = False
                rec["problems"].append(
                    f"CLC-NONSTRUCTURAL-EVIDENCE: edge {step_id} claims "
                    f"{entry.get('class')} on {role} citation kind {kind!r}; "
                    "file/symbol presence does not prove execution")
            if role == "actuate" and not bound_to_fallback:
                role_ok = False
                callee = str(cit.get("callee") or "<none>")
                expected = (", ".join(expected_entrypoints)
                            if expected_entrypoints else "<unregistered>")
                rec["problems"].append(
                    f"CLC-ACTUATION-NOT-FALLBACK-REENTRY: edge {step_id} "
                    f"falls back to step {fallback_to}, but its actuator calls "
                    f"{callee}; expected one of [{expected}]")
            if role == "actuate" and not bound_to_trigger:
                role_ok = False
                trigger = str(cit.get("trigger_callee") or "<none>")
                expected = (", ".join(expected_triggers)
                            if expected_triggers else "<unregistered>")
                rec["problems"].append(
                    f"CLC-ACTUATION-NOT-EDGE-TRIGGERED: edge {step_id} cites "
                    f"source trigger {trigger}; expected one of [{expected}]. "
                    "A retry belonging to another edge cannot be borrowed")
            if role == "remeasure" and not bound_to_fallback:
                role_ok = False
                actuator = str(cit.get("actuator_callee") or "<none>")
                expected = (", ".join(expected_entrypoints)
                            if expected_entrypoints else "<unregistered>")
                rec["problems"].append(
                    f"CLC-REMEASURE-NOT-FALLBACK-REENTRY: edge {step_id} "
                    f"falls back to step {fallback_to}, but its remeasurement "
                    f"citation follows actuator {actuator}; expected one of "
                    f"[{expected}]")
            if role == "remeasure" and not bound_to_trigger:
                role_ok = False
                trigger = str(cit.get("trigger_callee") or "<none>")
                expected = (", ".join(expected_triggers)
                            if expected_triggers else "<unregistered>")
                rec["problems"].append(
                    f"CLC-REMEASURE-NOT-EDGE-TRIGGERED: edge {step_id} cites "
                    f"source trigger {trigger}; expected one of [{expected}]. "
                    "A sibling edge cannot lend its measurement")
            if role == "remeasure" and not joined_to_actuation:
                role_ok = False
                rec["problems"].append(
                    f"CLC-REMEASURE-NOT-ACTUATION-PATH: edge {step_id} has "
                    "remeasurement evidence that does not extend any eligible "
                    "actuation citation with the same file, caller, trigger, "
                    "polarity, and fallback actuator")
        # EXECUTABLE means the declared fallback EDGE runs.  A blocking judge
        # can be valuable, but it cannot satisfy the actuator role merely by
        # retaining the pre-existing candidate.  This is deliberately checked
        # after resolving citations so the report still shows that the cited
        # code exists while refusing the semantic overclaim.
        if role_ok and not (role == "actuate" and non_reexecution):
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
#: A repair_log verdict that PRESENTS the step-32 loop as having converged. The
#: other verdicts this repo writes — REPAIR_ATTEMPTED, REPAIR_REQUIRED,
#: REPAIR_BLIND_TO_VIOLATION, REPAIR_REVERTED_REGRESSION — are all honest non-successes
#: and are not claims.
_REPAIR_SUCCESS_VERDICTS = ("REPAIR_APPLIED",)
_REPAIR_LOG_REL = Path("phase3") / "stage3" / "postroute_timing_repair" / "repair_log.json"


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
    repair_log = project / _REPAIR_LOG_REL
    if repair_log.is_file():
        sources.append(str(_REPAIR_LOG_REL))
        try:
            rec = json.loads(repair_log.read_text(encoding="utf-8",
                                               errors="replace"))
        except (OSError, ValueError):
            rec = None
        if isinstance(rec, dict) and rec.get("verdict") in _REPAIR_SUCCESS_VERDICTS \
                and bool(rec.get("re_verified")):
            claims.append({
                "step": "32", "source": str(_REPAIR_LOG_REL),
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
        cl = s["closed_loop"]
        raw_fallback = cl.get("fallback_to")
        fallback_to = (_norm(raw_fallback)
                       if raw_fallback is not None else None)
        rec = classify_edge(sid, root, fallback_to)
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
            f"{_REPAIR_LOG_REL} under the project) — zero claims were EXAMINED, "
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
                 if e.get("actuation_form")
                 and e["actuation_form"] != "re_execute" else ""))
    if rep["claim_audit"] == "NOT_CHECKED":
        print(f"  claim audit: NOT_CHECKED — {rep['claim_audit_reason']}")
    else:
        print(f"  claim audit: CHECKED — {rep['claims_examined']} claim(s) from "
              + ", ".join(rep["claim_sources"]))
    return rc


if __name__ == "__main__":
    sys.exit(main())
