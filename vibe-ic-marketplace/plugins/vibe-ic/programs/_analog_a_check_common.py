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
  * `analog/analog_block_list.json` absent or empty → exit 0 +
    "VACUOUS_PASS: no analog blocks declared".
  * Per-block, when called WITHOUT `--block`: report verdict per
    project (combine all blocks).
  * Per-block, when called WITH `--block <name>` AND the block's
    canonical artefact is missing: exit 2 + stderr message naming
    the upstream skill, so analog_one_shot_runner emits WAIVED
    (back-compat with the v1.6.34 runner behaviour).
  * Per-block, when artefact is present but stub: exit 1 (FAIL).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional


def load_block_list(project: Path) -> Optional[List[str]]:
    """Return list of declared analog block names, or None when no
    analog block list exists. Empty list when file exists but no
    blocks are declared. Mirrors `analog_artefact_substance_check`.
    """
    path = project / "phase3" / "analog" / "analog_block_list.json"
    if not path.is_file():
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
    analog IC is still gated."""
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
