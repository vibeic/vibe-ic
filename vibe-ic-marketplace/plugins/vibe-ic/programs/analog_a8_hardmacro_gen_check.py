#!/usr/bin/env python3
"""analog_a8_hardmacro_gen_check.py — A8 deterministic gate.

Verifies that the upstream `analog-hardmacro-gen` skill has emitted
the canonical per-block A8 artefact triple (LEF + Liberty + Verilog):

    analog/hardmacro/<block>/<block>.lef
    analog/hardmacro/<block>/<block>.lib
    analog/hardmacro/<block>/<block>.v

with substance (matching the v1.6.30 thresholds enforced by
`analog_artefact_substance_check`):

  * .lef ≥ 250 bytes
  * .lib ≥ 200 bytes
  * .v   ≥ 150 bytes
  * none of the three contains a v1.6.30 stub-marker phrase.

Failure rules:
  A8_HARDMACRO_LEF_MISSING    — analog/hardmacro/<block>/<block>.lef absent
  A8_HARDMACRO_LIB_MISSING    — .lib absent
  A8_HARDMACRO_V_MISSING      — .v absent
  A8_HARDMACRO_TOO_SMALL      — present but below per-ext threshold
  A8_HARDMACRO_STUB_MARKER    — file matches stub-marker panel
                                  (`ai_authored_methodology_stub`,
                                  `behavioral stub`, `placeholder
                                  hardmacro`, `do not tape out`, ...)

Project-level verdicts (no `--block`):
  VACUOUS_PASS — no `analog_block_list.json` under `phase3/analog/` or
                 `phase1/analog/`, or it declares no blocks; or EVERY
                 declared block is still missing the whole hardmacro triple
                 (the step has not run at all → defer to
                 `analog-hardmacro-gen`).
  INCOMPLETE   — SOME declared blocks were packaged and others produced no
                 hardmacro at all (exit 1). Step 14 (floorplan) consumes
                 these LEF abstracts, so an unpackaged declared block is a
                 macro the digital floorplan cannot reserve area for; the
                 gate names it instead of certifying the step.
  PASS         — every declared block cleared every check.
  PASS_STRUCTURE_ONLY
               — every certified block's package models a LIBRARY TOPOLOGY,
                 and the artefact chain says so. It certifies, in its own
                 tier, never as a design-bound pass.
chip-AGNOSTIC.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    BLOCK_LIST_ABSENT_REASON, CONTENT_GATE_OF_RECORD_ARTEFACT,
    CONTENT_STRUCTURE_ONLY, CONTENT_UNDISCLOSED, STRUCTURE_ONLY_TOKEN,
    hardmacro_content,
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail,
    emit_incomplete,
)

GATE = "analog_a8_hardmacro_gen_check"
SKILL = "analog-hardmacro-gen"

# ── A PACKAGE IS A PACKAGE OF SOMETHING ───────────────────────────────────
# THE RULE, with no tool, step or block name in it, and it is the same rule
# the sibling gates on this track already apply:
#
#   A gate that certifies an artefact for downstream consumption is certifying
#   a claim about what that artefact contains. An artefact chain that declines
#   to say what it contains must not certify the step it is the evidence for.
#
# WHY IT REACHES THIS GATE. The hardmacro is what digital PnR INSTANTIATES and
# what integration STA CLOSES ON. MEASURED, over one complete synthetic package
# (.gds + .lef + .lib + .v) on three trees identical in every artefact except
# the one recorded `design_content` value:
#
#   analog_a8_hardmacro_gen_check      PASS / PASS / PASS
#   analog_hardmacro_check             PASS / PASS / PASS
#   analog_liberty_nonzero_delay_check PASS / PASS_STRUCTURE_ONLY / FAIL
#
# Three gates over ONE package; the two that answer for the STEP could not tell
# the trees apart and the one that reads the field could. (The pair does NOT
# reproduce on a `.lib`-only fixture: both A8 gates exit 1 on the missing
# `.lef`/`.v`/`.gds` first and the disagreement is masked. It needs a complete
# package, which is what `test_two_gates_over_one_hardmacro_agree` builds.)
#
# WHERE THE ANSWER IS READ. Nothing writes `design_content` into a LEF, a
# Liberty, a GDS or a behavioural Verilog, so the whole answer is the corner
# artefact's — the gate of record's own subject. One shared site,
# `_analog_a_check_common.hardmacro_content`, for every gate over this package.
#
# ASKED LAST, after every deliverable and substance rule (missing / too small /
# stub marker), each of which names a deeper cause and answers this one as a
# side effect.
_CONTENT_BASELINE = CONTENT_GATE_OF_RECORD_ARTEFACT

# Per-ext thresholds (aligned with v1.6.30
# analog_artefact_substance_check defaults).
_MIN_BYTES = {".lef": 250, ".lib": 200, ".v": 150}

# Substring markers (lower-cased) — chip-AGNOSTIC. Mirrors the panel
# in `analog_artefact_substance_check._STUB_MARKERS_DEFAULT`.
_STUB_MARKERS = (
    "ai_authored_methodology_stub", "ai_authored_stub",
    "methodology_stub", "methodology placeholder",
    "behavioral stub", "behavioural stub",
    "placeholder netlist", "placeholder layout",
    "placeholder hardmacro",
    "stub: do not tape out", "do not tape out",
    "todo implement", "todo: implement",
    "__stub__", "@stub",
)


def _check_block(project: Path, block: str
                 ) -> tuple[Optional[str], List[dict]]:
    hdir = project / "phase3" / "analog" / "hardmacro" / block
    triples = (
        (".lef", hdir / f"{block}.lef", "A8_HARDMACRO_LEF_MISSING"),
        (".lib", hdir / f"{block}.lib", "A8_HARDMACRO_LIB_MISSING"),
        (".v",   hdir / f"{block}.v",   "A8_HARDMACRO_V_MISSING"),
    )
    findings: List[dict] = []
    missing_count = 0
    for ext, path, missing_rule in triples:
        if not path.is_file():
            findings.append({
                "block": block, "rule": missing_rule,
                "rel_path": str(path.relative_to(project))
                            if path.exists()
                            else f"analog/hardmacro/{block}/{block}{ext}",
                "detail": f"hardmacro {ext} not found",
            })
            missing_count += 1
            continue
        try:
            size = path.stat().st_size
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError as exc:
            findings.append({
                "block": block, "rule": "A8_HARDMACRO_TOO_SMALL",
                "rel_path": str(path.relative_to(project)),
                "detail": f"OSError: {exc}",
            })
            continue
        if size < _MIN_BYTES[ext]:
            findings.append({
                "block": block, "rule": "A8_HARDMACRO_TOO_SMALL",
                "rel_path": str(path.relative_to(project)),
                "detail": f"{size}B < min {_MIN_BYTES[ext]}B for {ext}",
            })
        hits = [m for m in _STUB_MARKERS if m in text]
        if hits:
            findings.append({
                "block": block, "rule": "A8_HARDMACRO_STUB_MARKER",
                "rel_path": str(path.relative_to(project)),
                "detail": f"file matches stub marker(s): "
                          f"{', '.join(hits)}",
            })
    # All three missing → MISSING (per-block --block mode → WAIVED).
    if missing_count == 3:
        return "MISSING", findings
    if findings:
        return "FAIL", findings

    # ── the certification question, asked LAST ────────────────────────────
    adir = project / "phase3" / "analog" / block
    bounded = hardmacro_content(adir)
    if bounded.klass == CONTENT_UNDISCLOSED:
        # `ceiling_source is None` covers BOTH "the artefact is absent" and
        # "the artefact is present and silent". Those send a reader to two
        # different places, so the message asks the filesystem rather than
        # inferring from a None.
        said = (f"`{_CONTENT_BASELINE}` records no answer to"
                if (adir / _CONTENT_BASELINE).is_file()
                else "no corner artefact exists to say")
        return "FAIL", [{
            "block": block, "rule": "A8_DESIGN_CONTENT_UNDECLARED",
            "rel_path": f"phase3/analog/hardmacro/{block}/",
            "detail": (f"the LEF / Liberty / Verilog triple is complete and "
                       f"substantive, and {said} what circuit this package "
                       f"models (`design_content`). Digital PnR will "
                       f"instantiate this macro as this design's and "
                       f"integration STA will close on its timing; a package "
                       f"that will not name its subject must not be signed "
                       f"off for it. Declaring `{CONTENT_STRUCTURE_ONLY}` is "
                       f"not a penalty — it certifies, in its own disclosed "
                       f"tier; declining to answer does not, or saying "
                       f"nothing would cost less than saying so."),
        }]
    if bounded.klass == CONTENT_STRUCTURE_ONLY:
        return "PASS_STRUCTURE_ONLY", [{
            "block": block, "rule": "A8_HARDMACRO_STRUCTURE_ONLY",
            "rel_path": f"phase3/analog/hardmacro/{block}/",
            "content_source": (str(bounded.source)
                               if bounded.source is not None else None),
            "detail": ("the triple is complete and substantive, and the "
                       "artefact chain records that the packaged circuit came "
                       "from a topology library with no bound input reaching "
                       "any device parameter — the package is real and it is "
                       "the default's, not this design's"),
        }]
    return "PASS", []


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
    structure_only: List[str] = []
    design_bound: List[str] = []
    disclosures: List[dict] = []
    for block in blocks:
        status, fs = _check_block(project, block)
        if status == "PASS":
            blocks_pass += 1
            design_bound.append(block)
        elif status == "PASS_STRUCTURE_ONLY":
            # Certified, in its own tier: the block cleared every deliverable
            # and substance rule, and it is named separately because the
            # package it cleared them with is a library default's.
            blocks_pass += 1
            structure_only.append(block)
            disclosures.extend(fs)
        elif status == "MISSING":
            missing_seen.extend(fs)
        else:
            findings.extend(fs)

    # Same ranking as every sibling on this track: the tier reaches the verdict
    # word only when NO block was certified design-bound.
    pass_token = ("PASS_STRUCTURE_ONLY"
                  if (structure_only and not design_bound) else "PASS")
    summary = {
        "blocks_checked": len(blocks),
        "blocks_pass": blocks_pass,
        "blocks_design_bound_pass": len(design_bound),
        "blocks_structure_only": len(structure_only),
        "structure_only_blocks": structure_only,
        "blocks_missing": len(missing_seen),
        "blocks_fail": len({f["block"] for f in findings}),
    }
    if disclosures:
        summary["structure_only_findings"] = disclosures

    def _disclose() -> None:
        """LAST, SHORT, and on every path the gate can leave by — the
        disclosure the A-track runner and the flow auditor read from a
        fixed-width TAIL of this stream, whatever the verdict was."""
        if not structure_only:
            return
        names = ", ".join(structure_only)
        if len(names) > 60:
            names = f"{names[:57]}..."
        print(f"{STRUCTURE_ONLY_TOKEN} {len(structure_only)} hardmacro "
              f"package(s) ({names}) model a library default, not a bound "
              f"input [{GATE}]")

    if args.block:
        if findings:
            rc = emit_fail(GATE, args, findings, summary)
            _disclose()
            return rc
        if missing_seen:
            return artefact_missing_for_block(
                GATE, args, args.block,
                missing_seen[0]["rel_path"], SKILL)
        rc = emit_pass(GATE, args, summary, pass_token=pass_token)
        _disclose()
        return rc

    if findings:
        rc = emit_fail(GATE, args, findings, summary)
        _disclose()
        return rc
    if missing_seen and blocks_pass == 0:
        return vacuous_pass(GATE, args,
                            f"all blocks missing hardmacro triple; "
                            f"defer to skill `{SKILL}`.")
    if missing_seen:
        # PARTIAL block coverage — see the A7 note. A8's declared outputs are
        # the globs `phase3/analog/hardmacro/*/*.lef|lib|gds|v`, each satisfied
        # by its FIRST match, so one packaged block used to certify the step
        # for every declared block. That matters more at A8 than anywhere
        # else on this track: Step 14 (floorplan) consumes the LEF abstracts,
        # and a declared block with no LEF is a macro the digital floorplan
        # cannot reserve area for.
        rc = emit_incomplete(GATE, args, missing_seen, summary, SKILL)
        _disclose()
        return rc
    rc = emit_pass(GATE, args, summary, pass_token=pass_token)
    _disclose()
    return rc


if __name__ == "__main__":
    sys.exit(main())
