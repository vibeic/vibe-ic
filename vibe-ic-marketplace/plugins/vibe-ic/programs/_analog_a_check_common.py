#!/usr/bin/env python3
"""_analog_a_check_common.py — v1.6.35 shared helpers for the
A1-A8 deterministic artefact-presence + substance gates.

Each gate (`analog_a{1..8}_*_check.py`) imports a small set of
helpers from here:
  * `load_block_list(project)`     → list[str] of declared block names,
                                       or `None` when no analog work.
  * `select_blocks(blocks, name?)` → restrict to a single block when
                                       `--block <name>` is given.
  * `iter_blocks(args, project)`   → yield (block, ...) per CLI options.
  * `emit_report(...)` / `cli_main(...)` are intentionally NOT here —
    each gate has its own audit logic and exit semantics.

VACUOUS_PASS contract (chip-AGNOSTIC):
  * the analog block list absent at EVERY location in
    `BLOCK_LIST_CANDIDATES` (`phase3/analog/`, `phase1/analog/`,
    legacy `analog/`), or present but empty → exit 0 +
    "VACUOUS_PASS: no analog blocks declared".
  * Per-block, when called WITHOUT `--block`: report verdict per
    project (combine all blocks).
  * Per-block, when called WITH `--block <name>` AND the block's
    canonical artefact is missing: exit 2 + stderr message naming
    the upstream skill, so analog_one_shot_runner emits WAIVED
    (back-compat with the v1.6.34 runner behaviour).
  * Per-block, when artefact is present but stub: exit 1 (FAIL).

INCOMPLETE contract (project mode only):
  * When SOME declared blocks carry the step's artefact and others
    carry none, the step is NOT done. `emit_incomplete` reports
    verdict INCOMPLETE, names every uncovered block, and exits 1.
    The all-blocks-missing case keeps its VACUOUS_PASS (the "the
    skill has not run yet, defer to it" contract) and `--block` mode
    keeps its exit-2 WAIVED deferral untouched.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional


# ── block-list location: three producers, three paths ─────────────────────
# The analog block list is written to a DIFFERENT path by each of its
# producers, and the A-gates used to read only one of them:
#   * `analog_one_shot_runner` materialises the canonical
#     `phase3/analog/analog_block_list.json` (`_pl.analog_dir`) so the
#     per-step gates see the same blocks it planned;
#   * `flow/phase1_phase2_phase3.yaml` keys the `condition:` of EVERY A-step
#     on `phase1/analog/analog_block_list.json`, and `migrate_to_layout_p.py`
#     moves a pre-v2 list to exactly that path (MEASURED: running the
#     production migrator on a pre-v2 project emits the single move
#     `analog/analog_block_list.json -> phase1/analog/analog_block_list.json`);
#   * pre-v2 projects still carry the legacy top-level `analog/` copy.
# Reading only the canonical path made every A-gate answer VACUOUS_PASS
# "gate inapplicable" on a project laid out exactly as its own flow declares
# — so the flow ACTIVATED A1-A4 (their `condition` reads the phase1 copy)
# and then let a gate that had loaded no block list certify the step.
# Sibling code already carries this tolerance:
# `analog_block_list_emit_check._PROJECT_GLOBS` probes three locations and
# `flow_compliance_check._has_canonical_analog_blocks` accepts more than one.
# chip-AGNOSTIC: pure path resolution.
BLOCK_LIST_CANDIDATES = (
    "phase3/analog/analog_block_list.json",   # canonical runner dir
    "phase1/analog/analog_block_list.json",   # what every A-step condition pins
    "analog/analog_block_list.json",          # pre-v2 legacy layout
)


def no_block_list_reason() -> str:
    """The VACUOUS_PASS reason a gate reports when no block list exists —
    naming every location actually probed, so the message cannot claim the
    gate looked somewhere it did not."""
    return (f"no analog block list at any of "
            f"{', '.join(BLOCK_LIST_CANDIDATES)}; gate inapplicable.")


def block_list_path(project: Path) -> Optional[Path]:
    """First EXISTING block-list file, in `BLOCK_LIST_CANDIDATES` order, or
    None. The first existing file wins even when it declares ZERO blocks: an
    explicit `[]` at the canonical path is the runner's documented
    "pure-digital, skip on purpose" signal (`_load_block_list_with_status`
    status=="empty") and a stale sibling copy must not override it."""
    for rel in BLOCK_LIST_CANDIDATES:
        cand = project / rel
        if cand.is_file():
            return cand
    return None


def load_block_list(project: Path) -> Optional[List[str]]:
    """Return list of declared analog block names, or None when no
    analog block list exists at ANY of `BLOCK_LIST_CANDIDATES`. Empty list
    when a file exists but no blocks are declared. Mirrors
    `analog_artefact_substance_check`.
    """
    path = block_list_path(project)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    blocks = data.get("blocks") if isinstance(data, dict) else data
    if not isinstance(blocks, list):
        return []
    out: List[str] = []
    for entry in blocks:
        if isinstance(entry, str) and entry:
            out.append(entry)
        elif isinstance(entry, dict):
            name = entry.get("name") or entry.get("block")
            if isinstance(name, str) and name:
                out.append(name)
    return out


# ── ORGANIC #676 — analog class-N/A predicate ──────────────────────────────
# The 3 analog P0 gates (analog_flow_compliance_check /
# analog_digital_interface_check / analog_a6_block_pv_check) used to hard-FAIL
# whenever analog_block_list.json carried ANY block — even a phantom
# `low_confidence` block fabricated from a digital keyword ("POR") on a
# pure-digital SoC classified `analog_applicable=false` /
# `verification_track=generic_full_stack`. The SIBLING analog gates already
# self-skip as N/A on a non-analog IC; these 3 lacked any class awareness.
# This shared predicate gives all three the SAME class-N/A read so a digital
# SoC SKIPs (N/A) instead of FAILing.
#
# §4.05 no-leak: returns True (→ N/A skip) ONLY when the IC is positively
# classified non-analog AND every declared block is low_confidence (a phantom
# keyword hit). A REAL analog IC (has_analog:true / analog_applicable:true) or
# a high-confidence (spec-backed) block returns False → still gated.
# chip-AGNOSTIC: reads the IC-class verdict + the per-block low_confidence tag;
# no chip / vendor / class literal.

def _ic_class_says_non_analog(project: Path) -> bool:
    """True iff the IC is positively classified as NON-analog, via
    reports/ic_class.json (`has_analog:false`) and/or the registry
    verification flags (`analog_applicable:false` /
    `verification_track=="generic_full_stack"`). Fail-closed: if no class
    verdict is available at all, returns False (the IC is NOT assumed
    non-analog — existing gating is never weakened)."""
    for rel in ("reports/ic_class.json",
                "reports/phase1/ic_class.json"):
        p = project / rel
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        # Direct, explicit non-analog signal.
        if data.get("has_analog") is False:
            return True
        if data.get("is_pure_analog") is True or data.get("is_mixed_signal") is True:
            return False
        # Registry-backed verification flags (analog_applicable /
        # verification_track) for the detected class.
        ic_class = data.get("ic_class")
        if isinstance(ic_class, str) and ic_class:
            try:
                import ic_class_profile as _icp
                flags = _icp.class_verification_flags(ic_class)
                if (flags.get("analog_applicable") is False
                        and flags.get("verification_track")
                        == "generic_full_stack"):
                    return True
            except Exception:
                pass
    return False


def _all_blocks_low_confidence(project: Path) -> bool:
    """True iff EVERY declared analog block is tagged `low_confidence:true`
    (a phantom keyword hit, never a spec-backed block). An empty list returns
    False here — the caller's existing empty-list VACUOUS path handles that.
    A list with ANY high-confidence (spec-backed) block returns False so a real
    analog IC is still gated.

    DELIBERATELY canonical-path-only, NOT `block_list_path()`: True here is a
    SKIP, so widening where this predicate looks would make the N/A escape
    hatch reachable on projects it is not reachable on today — a weakening.
    Fail-closed stays fail-closed; do not "align" this with
    `BLOCK_LIST_CANDIDATES` without an owner decision on the blast radius of
    the three P0 gates that consume it."""
    path = project / "phase3" / "analog" / "analog_block_list.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return False
    blocks = data.get("blocks") if isinstance(data, dict) else data
    if not isinstance(blocks, list) or not blocks:
        return False
    for entry in blocks:
        if not isinstance(entry, dict):
            return False  # bare-string block → treat as confident → gate it
        if entry.get("low_confidence") is not True:
            return False
    return True


def analog_class_is_na(project: Path) -> bool:
    """ORGANIC #676 — True iff the analog P0 gates should SKIP (N/A) on this
    IC: it is positively classified NON-analog AND every block declared in
    analog_block_list.json is a low_confidence (phantom) keyword hit. Both
    conditions are required so the skip is defence-in-depth, never a blanket
    bypass: a real analog IC fails (1), a confident analog block fails (2)."""
    return _ic_class_says_non_analog(project) and _all_blocks_low_confidence(project)


# ── per-block artefact resolution across the phase-distributed layout ──────
# `_path_layout` splits the analog block dirs by phase — A1's spec under
# `phase1/analog/<block>/`, A2-A4's frontend artefacts under
# `phase2/analog/<block>/`, A5-A9's backend artefacts under
# `phase3/analog/<block>/` — and `flow/phase1_phase2_phase3.yaml` declares each
# A-step's `required_outputs` at exactly those prefixes. The analog RUNNER,
# however, writes every block artefact under the single canonical
# `_pl.analog_dir` (== `phase3/analog/`); that is why `flow_compliance_check`
# carries an explicit canonical-analog-dir tolerance for its `files_exist`
# globs (`_glob_rel`, "v0.2.55 — canonical-analog-dir tolerance").
#
# The A1-A4 gates hardcoded `phase3/analog/` only, so a project laid out as
# its OWN flow declares reported every artefact MISSING and self-skipped,
# measuring nothing.
#
# `migrate_to_layout_p.py` does NOT reproduce the per-phase split the flow
# declares. MEASURED by running the production migrator on a pre-v2 project
# whose one block dir held spec.json + topology.md + <block>.sp +
# corners.json: it emitted exactly two moves —
#     analog/analog_block_list.json -> phase1/analog/analog_block_list.json
#     analog/<block>                -> phase2/analog/<block>
# `_classify_analog_block` picks ONE most-backend destination phase for the
# WHOLE block dir, so on a migrated project A1's spec.json lands under
# `phase2/analog/<block>/`, not under the `phase1/analog/` the flow declares
# as A1's required_output. A candidate list of {canonical, declared-phase}
# therefore still missed A1's spec on every migrated project.
#
# So probe EVERY analog root: the canonical runner dir FIRST (runner-produced
# projects resolve to byte-identical paths — guarded), then the flow-declared
# phase dir, then the remaining roots for the producer/declaration drift
# above. Widening resolution is monotone: an artefact that used to read
# MISSING can only start being MEASURED, never start being skipped.
# chip-AGNOSTIC: pure path resolution.
_DECLARED_ANALOG_ROOT = {
    1: "phase1/analog",
    2: "phase2/analog",
    3: "phase3/analog",
}
_CANONICAL_ANALOG_ROOT = "phase3/analog"
_ALL_ANALOG_ROOTS = ("phase3/analog", "phase1/analog", "phase2/analog",
                     "analog")


def block_artefact_candidates(project: Path, block: str, filename: str,
                              declared_phase: int) -> List[Path]:
    """Ordered candidate paths for one per-block A-step artefact: the
    canonical runner dir first, then the flow-declared phase dir, then every
    remaining analog root (a migrated project puts A1's spec under
    `phase2/analog/` — see the note above)."""
    order = [_CANONICAL_ANALOG_ROOT]
    declared = _DECLARED_ANALOG_ROOT.get(declared_phase)
    if declared and declared not in order:
        order.append(declared)
    for root in _ALL_ANALOG_ROOTS:
        if root not in order:
            order.append(root)
    return [project / root / block / filename for root in order]


def resolve_block_artefact(project: Path, block: str, filename: str,
                           declared_phase: int) -> tuple:
    """Return `(path, found)`. `path` is the first candidate that exists;
    when none exists it is the CANONICAL path, so a MISSING finding keeps
    naming the same `rel_path` these gates have always reported."""
    cands = block_artefact_candidates(project, block, filename,
                                      declared_phase)
    for cand in cands:
        if cand.is_file():
            return cand, True
    return cands[0], False


def select_blocks(blocks: List[str],
                  block_filter: Optional[str]) -> List[str]:
    """When `--block <name>` is given, restrict to that block (even
    if not in the list — the runner may have created an out-of-list
    block dir during a re-run). Otherwise return all declared blocks.
    """
    if block_filter:
        return [block_filter]
    return blocks


def make_argparser(gate_name: str, doc: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=gate_name, description=doc,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path,
                    help="project root (the dir holding analog/, reports/...)")
    ap.add_argument("--json", default=None,
                    help="write JSON verdict to this path")
    ap.add_argument("--block", default=None,
                    help="restrict check to a single block (used by "
                         "analog_one_shot_runner)")
    return ap


def write_report(json_path: Optional[str], report: dict) -> None:
    if not json_path:
        return
    out = Path(json_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


def vacuous_pass(gate_name: str, args, reason: str) -> int:
    """Print + emit JSON + return 0. Used when no analog blocks
    declared at all (project-level VACUOUS_PASS)."""
    report = {
        "gate": gate_name,
        "verdict": "VACUOUS_PASS",
        "reason": reason,
        "findings": [],
    }
    write_report(args.json, report)
    print(f"VACUOUS_PASS: {reason}")
    return 0


def artefact_missing_for_block(gate_name: str, args, block: str,
                               artefact_rel: str, skill: str) -> int:
    """Per-block --block mode: artefact not yet emitted. Exit 2 so
    analog_one_shot_runner translates this to WAIVED. stderr names
    the skill for the runner to surface to the caller. JSON report
    is still written when --json is given so a flow audit can pick
    up the deferred state.
    """
    report = {
        "gate": gate_name,
        "verdict": "WAIVED",
        "block": block,
        "missing_artefact": artefact_rel,
        "suggested_skill": skill,
        "reason": (f"artefact `{artefact_rel}` not yet emitted; caller "
                   f"should invoke skill `{skill}`"),
        "findings": [],
    }
    write_report(args.json, report)
    print(f"WAIVED: block={block} missing `{artefact_rel}` — "
          f"invoke skill `{skill}`", file=sys.stderr)
    return 2


def emit_pass(gate_name: str, args, summary: dict) -> int:
    report = {
        "gate": gate_name,
        "verdict": "PASS",
        **summary,
        "findings": [],
    }
    write_report(args.json, report)
    print(f"PASS: {gate_name} — "
          f"{summary.get('blocks_pass', 0)}/"
          f"{summary.get('blocks_checked', 0)} block(s) clean")
    return 0


def emit_incomplete(gate_name: str, args, missing: list, summary: dict,
                    skill: str) -> int:
    """Project mode, PARTIAL block coverage: some declared blocks carry the
    step's artefact, others carry none. Exit 1.

    Before this existed, the project-mode tail of every A1-A4 gate fell
    through to `emit_pass`, so a run in which the upstream skill produced an
    artefact for 1 of N declared blocks was certified `PASS` — the step was
    reported done while N-1 declared blocks had been measured on nothing.
    The flow declaration cannot catch this: each A-step declares a single
    GLOB (`phase2/analog/*/topology.md`) and `flow_compliance_check` satisfies
    a glob entry on its FIRST match, so per-block coverage is knowable only
    here.

    INCOMPLETE is deliberately distinct from FAIL: a block with NO artefact is
    unmeasured work, not a measured defect. Both are non-zero, so neither can
    certify the step done. The all-blocks-missing VACUOUS_PASS (defer to the
    skill) and the `--block` exit-2 WAIVED deferral are untouched.
    """
    blocks = []
    for f in missing:
        b = f.get("block")
        if b and b not in blocks:
            blocks.append(b)
    report = {
        "gate": gate_name,
        "verdict": "INCOMPLETE",
        **summary,
        "incomplete_blocks": blocks,
        "suggested_skill": skill,
        "reason": (f"{len(blocks)} of {summary.get('blocks_checked', 0)} "
                   f"declared analog block(s) produced no artefact for this "
                   f"step; invoke skill `{skill}` for them"),
        "findings": missing,
    }
    write_report(args.json, report)
    print(f"INCOMPLETE: {gate_name} — "
          f"{summary.get('blocks_pass', 0)}/"
          f"{summary.get('blocks_checked', 0)} declared block(s) covered; "
          f"no artefact for: {', '.join(blocks) or '?'} "
          f"(invoke skill `{skill}`)", file=sys.stderr)
    for f in missing[:8]:
        print(f"  [{f.get('block', '?')}] {f.get('rule', '?')}: "
              f"{f.get('detail', '')}", file=sys.stderr)
    if len(missing) > 8:
        print(f"  ... and {len(missing) - 8} more", file=sys.stderr)
    return 1


def emit_fail(gate_name: str, args, findings: list, summary: dict) -> int:
    report = {
        "gate": gate_name,
        "verdict": "FAIL",
        **summary,
        "findings": findings,
    }
    write_report(args.json, report)
    print(f"FAIL: {gate_name} — "
          f"{len(findings)} finding(s):", file=sys.stderr)
    for f in findings[:8]:
        block = f.get("block", "?")
        rule = f.get("rule", "?")
        detail = f.get("detail", "")
        print(f"  [{block}] {rule}: {detail}", file=sys.stderr)
    if len(findings) > 8:
        print(f"  ... and {len(findings) - 8} more", file=sys.stderr)
    return 1
