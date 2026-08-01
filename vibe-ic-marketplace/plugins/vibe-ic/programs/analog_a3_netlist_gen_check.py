#!/usr/bin/env python3
"""analog_a3_netlist_gen_check.py — A3 deterministic gate (v1.6.35).

Verifies that the upstream `analog-netlist-gen` skill has emitted the
canonical per-block A3 artefact:

    analog/<block>/<block>.sp

with substance:

  * file size ≥ 200 bytes (the v1.6.30 substance threshold for .sp;
    a placeholder `* netlist stub\\n.end\\n` is < 50 bytes).
  * contains a `.subckt` / `.SUBCKT` declaration (the canonical
    SPICE module wrapper). Without this, the file is at best a
    raw stimulus file, not a reusable analog block netlist.
  * instantiates at least ONE device card inside a `.subckt` body.
    A `.subckt`/`.ends` shell with a comment where the circuit should
    be is a placeholder, and it clears both rules above: pad it with
    header comments past 200 bytes and it used to PASS A3 outright.

Failure rules:
  A3_NETLIST_MISSING        — <block>.sp absent
  A3_NETLIST_TOO_SMALL      — < 200 bytes
  A3_NETLIST_NO_SUBCKT      — no .subckt declaration
  A3_NETLIST_NO_DEVICES     — .subckt body instantiates no device

Note: this is a thin wrapper aligned with
`analog_artefact_substance_check`'s .sp size rule, plus the additional
`.subckt` + device-instantiation semantic checks.

VACUOUS_PASS when no `analog_block_list.json` exists under
`phase3/analog/` (the analog runner's root) or `phase1/analog/` (the
root every A-step's flow `condition:` names), or it declares no blocks.

INCOMPLETE (rc=1) in project mode when SOME declared blocks have a
netlist and others have none.

Artefact resolution: `phase3/analog/<block>/<block>.sp` (what the analog
runner writes) OR `phase2/analog/<block>/<block>.sp` (what the flow
declares as A3's required_output).

chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    BLOCK_LIST_ABSENT_REASON,
    DESIGN_CONTENT_STRUCTURE_ONLY,
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail, emit_incomplete,
    resolve_block_artefact, structure_only_disclosure,
)
import _analog_producer_common as _pc

GATE = "analog_a3_netlist_gen_check"
#: The producer's sidecar. Present only for netlists the deterministic
#: producer wrote; a skill-authored netlist carries none and is exempt from
#: the two rules below rather than failed by them.
SIDECAR = "netlist_provenance.json"
SKILL = "analog-netlist-gen"
MIN_BYTES = 200
DECLARED_PHASE = 2

_SUBCKT_RE = re.compile(r"(?im)^\s*\.subckt\s+\S+")

_SUBCKT_START_RE = re.compile(r"(?i)^\.subckt\b")
_SUBCKT_END_RE = re.compile(r"(?i)^\.ends\b")
# SPICE element cards that constitute an actual circuit:
#   X sub-circuit instance   M MOSFET   R/C/L passives   D diode
#   Q BJT   J JFET   Z MESFET/HEMT
#   E/F/G/H controlled sources, B behavioural source (behavioural blocks)
# Deliberately EXCLUDES V and I: a body containing only independent
# sources is stimulus, not a block netlist.
_DEVICE_CARD_RE = re.compile(r"(?i)^[xmrcldqjzefghb]\S")


def _subckt_device_count(text: str) -> int:
    """Number of device cards instantiated inside `.subckt`/`.ends` bodies.

    Comment (`*`, `;`) and continuation (`+`) lines are skipped, as are
    dot-commands — so a `.subckt` shell wrapping nothing but comments
    counts zero. chip-AGNOSTIC: pure SPICE card grammar."""
    depth = 0
    count = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "*;+":
            continue
        if _SUBCKT_START_RE.match(line):
            depth += 1
            continue
        if _SUBCKT_END_RE.match(line):
            depth = max(0, depth - 1)
            continue
        if depth > 0 and _DEVICE_CARD_RE.match(line):
            count += 1
    return count


def _check_block(project: Path, block: str
                 ) -> tuple[Optional[str], List[dict]]:
    path, found = resolve_block_artefact(
        project, block, f"{block}.sp", DECLARED_PHASE)
    if not found:
        return "MISSING", [{
            "block": block, "rule": "A3_NETLIST_MISSING",
            "rel_path": str(path.relative_to(project)),
            "detail": f"{block}.sp not found",
        }]
    try:
        size = path.stat().st_size
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "FAIL", [{
            "block": block, "rule": "A3_NETLIST_TOO_SMALL",
            "rel_path": str(path.relative_to(project)),
            "detail": f"OSError: {exc}",
        }]
    if size < MIN_BYTES:
        return "FAIL", [{
            "block": block, "rule": "A3_NETLIST_TOO_SMALL",
            "rel_path": str(path.relative_to(project)),
            "detail": f"{size}B < min {MIN_BYTES}B (placeholder?)",
        }]
    if not _SUBCKT_RE.search(text):
        return "FAIL", [{
            "block": block, "rule": "A3_NETLIST_NO_SUBCKT",
            "rel_path": str(path.relative_to(project)),
            "detail": "no `.subckt <name>` declaration found",
        }]
    devices = _subckt_device_count(text)
    if devices == 0:
        return "FAIL", [{
            "block": block, "rule": "A3_NETLIST_NO_DEVICES",
            "rel_path": str(path.relative_to(project)),
            "detail": ("`.subckt` body instantiates 0 device cards — an "
                       "empty subcircuit shell is a placeholder, not a "
                       "netlist (a size + `.subckt` pair alone cannot tell "
                       "the two apart)"),
        }]
    ref = _provenance_ref_fail(project, block, path, text)
    if ref is not None:
        return "FAIL", [ref]
    return "PASS", []


def _sidecar(project: Path, block: str) -> Optional[dict]:
    """The producer's own record beside the netlist, or None."""
    path, found = resolve_block_artefact(
        project, block, SIDECAR, DECLARED_PHASE)
    if not found:
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    prov = doc.get("_provenance") if isinstance(doc, dict) else None
    return prov if isinstance(prov, dict) else None


def _provenance_ref_fail(project: Path, block: str, path: Path,
                         text: str) -> Optional[dict]:
    """The digest a report quotes must be recomputable, HERE, from THIS file.

    A digest published as proof is only proof if the reader can check it, and
    the digests this artefact used to publish could not be checked by anyone:
    they were taken over files carrying a wall-clock stamp and an absolute
    path, so they changed on every run of identical inputs and named neither
    the content nor the run. Five sibling run trees of the same inputs
    published five different digests and nothing said which tree each came
    from. `provenance_ref` names the run tree, the artefact and the content in
    one token; this rule recomputes all three and refuses a mismatch, so a
    digest quoted from a different run cannot survive a single gate run.

    Silent when the netlist carries no producer sidecar — a skill-authored
    netlist makes no such claim, and a rule that failed it would be punishing
    the absence of a claim rather than a false one."""
    prov = _sidecar(project, block)
    if prov is None or "provenance_ref" not in prov:
        return None
    rel = str(path.relative_to(project))
    problem = _pc.verify_provenance_ref(prov.get("provenance_ref"), rel, text)
    if problem is None:
        return None
    return {
        "block": block, "rule": "A3_PROVENANCE_REF_MISMATCH",
        "rel_path": rel,
        "detail": (f"{SIDECAR} publishes a provenance_ref that does not "
                   f"recompute against the artefact beside it: {problem}. A "
                   f"digest quoted as proof of a run must be reproducible "
                   f"from that run's own tree."),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = make_argparser(GATE, __doc__)
    args = ap.parse_args(argv)
    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 2

    blocks_all = load_block_list(project)
    if blocks_all is None or (not blocks_all and not args.block):
        return vacuous_pass(GATE, args,
                            BLOCK_LIST_ABSENT_REASON)

    blocks = select_blocks(blocks_all or [], args.block)
    if not blocks:
        return vacuous_pass(GATE, args, "no blocks selected.")

    findings: List[dict] = []
    blocks_pass = 0
    missing_seen: List[dict] = []
    for block in blocks:
        status, fs = _check_block(project, block)
        if status == "PASS":
            blocks_pass += 1
        elif status == "MISSING":
            missing_seen.extend(fs)
        else:
            findings.extend(fs)

    # WHAT the netlists contain, read from the producer's own record and
    # disclosed independently of this gate's verdict.
    structure_only = [b for b in blocks
                      if (_sidecar(project, b) or {}).get("design_content")
                      == DESIGN_CONTENT_STRUCTURE_ONLY]
    summary = {
        "blocks_checked": len(blocks),
        "blocks_pass": blocks_pass,
        "blocks_missing": len(missing_seen),
        "blocks_fail": len(findings),
        "blocks_structure_only": len(structure_only),
        "structure_only_blocks": structure_only,
    }
    rc = _verdict(args, findings, missing_seen, blocks_pass, summary)
    # LAST, and on every path — see `structure_only_disclosure` for why the
    # position is part of the contract.
    structure_only_disclosure(GATE, structure_only, "<block>.sp")
    return rc


def _verdict(args, findings: List[dict], missing_seen: List[dict],
             blocks_pass: int, summary: dict) -> int:
    if args.block:
        if findings:
            return emit_fail(GATE, args, findings, summary)
        if missing_seen:
            return artefact_missing_for_block(
                GATE, args, args.block,
                missing_seen[0]["rel_path"], SKILL)
        return emit_pass(GATE, args, summary)

    if findings:
        return emit_fail(GATE, args, findings, summary)
    if missing_seen and blocks_pass == 0:
        return vacuous_pass(GATE, args,
                            f"all {len(missing_seen)} block(s) missing "
                            f"<block>.sp; defer to skill `{SKILL}`.")
    if missing_seen:
        # Mixed PASS + missing. Until v1.7.36 this fell through to
        # emit_pass, certifying A3 done on partial block coverage.
        return emit_incomplete(GATE, args, missing_seen, summary, SKILL)
    return emit_pass(GATE, args, summary)


if __name__ == "__main__":
    sys.exit(main())
