#!/usr/bin/env python3
"""analog_a7_post_layout_resim_check.py — A7 deterministic gate.

Verifies that the upstream `analog-extraction-resim` skill has emitted
the canonical per-block A7 artefact:

    analog/<block>/pre_vs_post.json

with substance:

  * file is JSON-parsable
  * declares a `specs[]` list (each entry carries `pre_value` /
    `post_value` and a numeric delta), OR a flat
    `pre` / `post` dict keyed by spec name
  * post-vs-pre delta ≤ `--max-delta-pct` (default 10%) for every
    declared spec
  * if the upstream A4 corner_results.json says
    `simulator_run: false` for every corner, A7 is forced to FAIL
    pointing back at A4 (you cannot have a credible post-layout
    re-sim if pre-layout SPICE never ran).

Failure rules:
  A7_POSTSIM_MISSING        — pre_vs_post.json absent
  A7_POSTSIM_INVALID_JSON   — present but unparsable
  A7_POSTSIM_NO_SPECS       — neither specs[] nor pre/post dict
  A7_POSTSIM_DELTA_TOO_BIG  — abs(delta_pct) > --max-delta-pct
  A7_POSTSIM_ALL_ZERO_DELTA_UNEVIDENCED
                            — every compared spec's post value is IDENTICAL to
                              its pre value and no post-layout artefact is
                              named that resolves on disk. The rule, and what
                              it deliberately does not catch, live at
                              `_analog_a_check_common.pre_vs_post_zero_delta`.
  A7_POSTSIM_NO_A4_SIM      — A4 says SPICE never ran (escape link)
  A7_DESIGN_CONTENT_UNDECLARED
                            — nothing says what circuit was re-simulated

Project-level verdicts (no `--block`):
  VACUOUS_PASS — no `analog_block_list.json` under `phase3/analog/` or
                 `phase1/analog/`, or it declares no blocks; or EVERY
                 declared block is still missing `pre_vs_post.json` (the
                 step has not run at all → defer to `analog-extraction-resim`).
  INCOMPLETE   — SOME declared blocks produced a pre-vs-post comparison and
                 others produced none (exit 1). A7's requirement was never
                 met for the uncovered blocks, so the gate names them
                 instead of certifying the step.
  PASS         — every declared block cleared every check.
  PASS_STRUCTURE_ONLY
               — every certified block's re-simulation was a re-simulation
                 of a LIBRARY TOPOLOGY, and the artefact chain says so. It
                 certifies, in its own tier, never as a design-bound pass.
chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    BLOCK_LIST_ABSENT_REASON, CONTENT_GATE_OF_RECORD_ARTEFACT,
    CONTENT_STRUCTURE_ONLY,
    CONTENT_UNDISCLOSED, PRE_VS_POST_DERIVED_ARTEFACT, STRUCTURE_ONLY_TOKEN,
    pre_vs_post_content, pre_vs_post_zero_delta, zero_delta_refusal_detail,
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail,
    emit_incomplete,
)

GATE = "analog_a7_post_layout_resim_check"
SKILL = "analog-extraction-resim"
DEFAULT_MAX_DELTA_PCT = 10.0

# ── A RE-SIMULATION IS A RE-SIMULATION OF SOMETHING ───────────────────────
# THE RULE, with no tool, step or block name in it:
#
#   A gate that certifies a comparison is certifying a claim about the thing
#   compared. It must read what that thing is, and an artefact that declines
#   to say what it contains must not certify the step it is the evidence for.
#
# MEASURED, on three synthetic trees identical in every artefact except the
# one recorded `design_content` value: this gate answered
# `PASS: 2/2 block(s) clean` rc 0 with a byte-identical `--json` on all three,
# certifying a post-layout re-simulation of a library topology as if it were a
# design's. This gate is LOAD-BEARING — it is a step of the A-track runner —
# so that certification is what the run record inherits.
#
# WHERE THE ANSWER IS READ — and this is the half the previous round got
# WRONG. It read `pre_vs_post.json` FIRST and `corner_results.json` second,
# "ordered nearest-first", on the reasoning that an artefact's own statement
# about itself outranks anything it inherits. That reasoning does not hold for
# THIS artefact, for two independent reasons:
#
#   * NOTHING DETERMINISTIC WRITES THE FIELD INTO IT. `pre_vs_post.json` is
#     authored by the `analog-extraction-resim` SKILL — an AI step. Ordering it
#     first put an AI-authored claim ABOVE the record a deterministic producer
#     wrote, which is the inversion this whole track exists to remove.
#   * IT IS SEMANTICALLY IMPOSSIBLE. This file is a COMPARISON against the
#     pre-layout corner result. If the corner sweep simulated a library
#     topology, the baseline half of every row in this file IS that library
#     topology's. A comparison cannot be more design-bound than the thing it is
#     compared against.
#
# So the corner artefact is not the second link in an ordered chain — it is the
# CEILING. `pre_vs_post.json`'s own record may CONFIRM it or LOWER it and can
# never RAISE it. MEASURED, with the corner artefact SILENT and this artefact
# carrying the design-bound token: `analog_a4_corner_sweep_check` rc 1 FAIL
# while this gate read rc 0 plain PASS with no sentinel — this gate certifying
# a tree its own gate of record refuses, which is exactly what the nearest-first
# comment claimed was impossible. Stopping at the gate of record's artefact is
# not the same as being bounded by it.
#
# The rule itself lives at ONE site, `_analog_a_check_common.pre_vs_post_content`
# — shared with the gate the FLOW declares for this step, so the two cannot
# drift into disagreeing about this one file again.
#
# THREE OUTCOMES, ranked so that disclosure is never the expensive answer:
#   design-bound   -> PASS, unchanged.
#   structure-only -> PASS_STRUCTURE_ONLY plus the disclosure sentinel. It
#                     certifies, in its own tier. Not a FAIL: nothing is
#                     wrong, and failing an honest ceiling teaches the next
#                     run to stop being honest.
#   undisclosed    -> does not certify.
#
# ASKED LAST, after MISSING, after INVALID_JSON, after the A4-never-simulated
# escape link, after NO_SPECS and after DELTA_TOO_BIG — every one of which
# names a deeper cause and answers this one as a side effect. A reader told
# "say what you re-simulated" about a comparison whose drift is 16 % would fix
# the wrong thing first.
#
# MEASURED HERE AND NOT CHASED, recorded at the site rather than left to be
# rediscovered: the A1-A9 matrix in `analog_flow_compliance_check` renders
# this step's cell from PRESENCE ALONE (`_check_step` -> `_any_file(...
# pre_vs_post.json)`). On the three trees above its A7 cell reads
# `PASS / PASS / PASS` while this gate reads `PASS / PASS_STRUCTURE_ONLY /
# FAIL`, so on the silent tree a matrix cell signs off a step the gate of
# record refuses. That is NOT new and it is NOT specific to content: A1, A2,
# A3, A5 and A8 cells are presence-only in exactly the same way, and each has
# substance rules its cell does not replicate. A4 is the single cell that
# delegates, because A4 is where the certification lived. Giving A7 the same
# delegation is a change to the matrix's meaning for one step out of nine,
# with its own blast radius on real per-block counts and its own evidence
# obligation — it is filed as itself, not smuggled in beside this one.
#
# The two artefact names are re-exported here only so a reader of THIS file can
# see what the rule reads without opening the shared one. They are the shared
# module's constants, not copies of them — a copy is how the last drift
# started.
_CONTENT_BASELINE = CONTENT_GATE_OF_RECORD_ARTEFACT   # the ceiling
_CONTENT_DERIVED = PRE_VS_POST_DERIVED_ARTEFACT       # may lower it, never raise


def _a4_simulator_ran(project: Path, block: str) -> Optional[bool]:
    """Returns True when at least one A4 corner has simulator_run !=
    false; False when every corner says simulator_run: false; None
    when A4 file is absent / unparsable / makes no claim either way.
    """
    cf = project / "phase3" / "analog" / block / "corner_results.json"
    if not cf.is_file():
        return None
    try:
        data = json.loads(cf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    corners = data.get("corners")
    if not isinstance(corners, list) or not corners:
        return None
    flags = [c.get("simulator_run") for c in corners
             if isinstance(c, dict) and c.get("simulator_run") is not None]
    if not flags:
        return None
    return any(f is not False for f in flags)


def _check_specs(specs: list) -> tuple[list[float], list[tuple]]:
    """``(deltas, pairs)`` for entries that carry both pre_value and
    post_value. Skips ill-formed entries.

    `deltas` keeps this gate's historical reading, which PREFERS a `delta_pct`
    the artefact declares about itself over the one the values imply. `pairs`
    is the raw ``(pre, post)`` sequence, carried separately because the shared
    zero-delta rule must read the VALUES: a rule reading the declared field
    would let an author write a non-zero `delta_pct` beside a copied pair and
    put this gate back into disagreement with the gate the flow declares over
    the same file.
    """
    deltas: list[float] = []
    pairs: list[tuple] = []
    for s in specs:
        if not isinstance(s, dict):
            continue
        pre = s.get("pre_value")
        post = s.get("post_value")
        if pre is None or post is None:
            continue
        try:
            pre_f = float(pre)
            post_f = float(post)
        except (TypeError, ValueError):
            continue
        if pre_f != 0:
            pairs.append((pre_f, post_f))
        if "delta_pct" in s:
            try:
                deltas.append(abs(float(s["delta_pct"])))
            except (TypeError, ValueError):
                pass
            continue
        if pre_f == 0:
            deltas.append(float("inf"))
            continue
        deltas.append(abs(100.0 * (post_f - pre_f) / pre_f))
    return deltas, pairs


def _check_block(project: Path, block: str, max_delta_pct: float
                 ) -> tuple[Optional[str], List[dict]]:
    path = project / "phase3" / "analog" / block / "pre_vs_post.json"
    rel = str(path.relative_to(project)) if path.exists() \
        else f"analog/{block}/pre_vs_post.json"
    if not path.is_file():
        return "MISSING", [{
            "block": block, "rule": "A7_POSTSIM_MISSING",
            "rel_path": rel, "detail": "pre_vs_post.json not found",
        }]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return "FAIL", [{
            "block": block, "rule": "A7_POSTSIM_INVALID_JSON",
            "rel_path": rel, "detail": f"unparsable: {exc}",
        }]
    if not isinstance(data, dict):
        return "FAIL", [{
            "block": block, "rule": "A7_POSTSIM_INVALID_JSON",
            "rel_path": rel, "detail": "top-level not a JSON object",
        }]

    # Force-fail when A4 says SPICE never ran for this block.
    if _a4_simulator_ran(project, block) is False:
        return "FAIL", [{
            "block": block, "rule": "A7_POSTSIM_NO_A4_SIM",
            "rel_path": rel,
            "detail": ("A4 corner_results.json says every corner has "
                       "`simulator_run: false`; post-layout resim is "
                       "vacuous without a pre-layout SPICE baseline"),
        }]

    specs = data.get("specs")
    deltas: list[float]
    pairs: list[tuple]
    if isinstance(specs, list) and specs:
        deltas, pairs = _check_specs(specs)
    else:
        # Flat pre/post layout: {"pre": {...}, "post": {...}}
        pre = data.get("pre")
        post = data.get("post")
        if (isinstance(pre, dict) and isinstance(post, dict)
                and pre and post):
            built = []
            for k in pre.keys() & post.keys():
                try:
                    built.append({"name": k,
                                  "pre_value": float(pre[k]),
                                  "post_value": float(post[k])})
                except (TypeError, ValueError):
                    continue
            deltas, pairs = _check_specs(built)
            if not built:
                return "FAIL", [{
                    "block": block, "rule": "A7_POSTSIM_NO_SPECS",
                    "rel_path": rel,
                    "detail": ("`pre` / `post` dicts share no numeric "
                               "spec keys"),
                }]
        else:
            return "FAIL", [{
                "block": block, "rule": "A7_POSTSIM_NO_SPECS",
                "rel_path": rel,
                "detail": ("neither `specs[]` nor `pre`/`post` dicts "
                           "present"),
            }]

    if not deltas:
        return "FAIL", [{
            "block": block, "rule": "A7_POSTSIM_NO_SPECS",
            "rel_path": rel,
            "detail": "no parseable pre_value/post_value entries",
        }]
    bad = [d for d in deltas if d > max_delta_pct]
    if bad:
        return "FAIL", [{
            "block": block, "rule": "A7_POSTSIM_DELTA_TOO_BIG",
            "rel_path": rel,
            "detail": (f"{len(bad)}/{len(deltas)} spec(s) drift > "
                       f"{max_delta_pct}% (max={max(deltas):.2f}%)"),
        }]

    # ── did a SECOND simulation happen at all? ────────────────────────────
    # Asked after every value rule above — a comparison whose specs really
    # moved cannot be degenerate, so none of them compete with this one — and
    # BEFORE the content question, which names a shallower cause: what circuit
    # was re-simulated does not matter yet if the post column is the pre
    # column. The rule itself lives at ONE site, shared with the gate the FLOW
    # declares for this step, so the two cannot drift into disagreeing about
    # this one file.
    zd = pre_vs_post_zero_delta(path.parent, pairs, project=project,
                                doc=data)
    if not zd.certifies:
        return "FAIL", [{
            "block": block, "rule": "A7_POSTSIM_ALL_ZERO_DELTA_UNEVIDENCED",
            "rel_path": rel,
            "detail": zero_delta_refusal_detail(zd),
        }]

    # ── the certification question, asked LAST ────────────────────────────
    bounded = pre_vs_post_content(path.parent)
    content, src = bounded.klass, bounded.source
    if content == CONTENT_UNDISCLOSED:
        if bounded.refused is not None:
            # The derived artefact DID answer, and its answer outranks what its
            # own baseline supports. Say that, rather than "nothing records an
            # answer" — a reader who can see the token on disk would read the
            # generic message as a bug in the gate and go looking in the wrong
            # place.
            said = (f"this artefact claims `{bounded.refused}` while the "
                    f"pre-layout corner result it is compared against records "
                    f"no answer at all. The comparison cannot be more "
                    f"design-bound than its own baseline: if the baseline is "
                    f"undeclared, so is the comparison. Nothing deterministic "
                    f"writes this field into `{_CONTENT_DERIVED}` — the record "
                    f"belongs to `{_CONTENT_BASELINE}`, and that is where the "
                    f"fix belongs")
        else:
            said = ("neither this artefact nor the pre-layout corner result "
                    "it is compared against records any answer to what "
                    "circuit was re-simulated (`design_content`)")
        return "FAIL", [{
            "block": block, "rule": "A7_DESIGN_CONTENT_UNDECLARED",
            "rel_path": rel,
            "detail": ("every declared spec drifts within "
                       f"{max_delta_pct}% post-layout, and {said}. A "
                       "post-layout "
                       "comparison of a library topology and one of a design "
                       "sized to its spec are indistinguishable in every "
                       "other field of this file. Declaring "
                       f"`{CONTENT_STRUCTURE_ONLY}` is not a penalty — it "
                       "certifies, in its own disclosed tier; declining to "
                       "answer does not, or saying nothing would cost less "
                       "than saying so."),
        }]
    if content == CONTENT_STRUCTURE_ONLY:
        extra = ""
        if bounded.refused is not None:
            extra = (f"; this artefact's own record claims "
                     f"`{bounded.refused}` and is BOUNDED to its baseline's "
                     f"answer — a comparison cannot be more design-bound than "
                     f"the pre-layout result it is compared against")
        return "PASS_STRUCTURE_ONLY", [{
            "block": block, "rule": "A7_POSTSIM_STRUCTURE_ONLY",
            "rel_path": rel,
            "content_source": (str(src) if src is not None else None),
            "detail": ("post-layout drift is within budget for every "
                       "declared spec, and the artefact chain records that "
                       "the re-simulated circuit came from a topology "
                       "library with no bound input reaching any device "
                       "parameter — the comparison is real and it is the "
                       "default's, not this design's" + extra),
        }]
    return "PASS", []


def main(argv: Optional[List[str]] = None) -> int:
    ap = make_argparser(GATE, __doc__)
    ap.add_argument("--max-delta-pct", type=float,
                    default=DEFAULT_MAX_DELTA_PCT,
                    help=f"max |post-pre|/pre %% (default "
                         f"{DEFAULT_MAX_DELTA_PCT})")
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
        status, fs = _check_block(project, block, args.max_delta_pct)
        if status == "PASS":
            blocks_pass += 1
            design_bound.append(block)
        elif status == "PASS_STRUCTURE_ONLY":
            # Certified, in its own tier: it stays in `blocks_pass` because
            # the block cleared every value rule, and it is named separately
            # because the comparison it cleared them with is a library
            # default's. Its disclosure is carried, never dropped.
            blocks_pass += 1
            structure_only.append(block)
            disclosures.extend(fs)
        elif status == "MISSING":
            missing_seen.extend(fs)
        else:
            findings.extend(fs)

    # Same ranking as the sibling corner gates: the tier reaches the verdict
    # word only when NO block was certified design-bound.
    pass_token = ("PASS_STRUCTURE_ONLY"
                  if (structure_only and not design_bound) else "PASS")
    summary = {
        "blocks_checked": len(blocks),
        "blocks_pass": blocks_pass,
        # The design-bound count is the one a reader wants when asking "did
        # THIS DESIGN's post-layout re-sim close" — `blocks_pass` answers a
        # different question and is kept unchanged for back-compat.
        "blocks_design_bound_pass": len(design_bound),
        "blocks_structure_only": len(structure_only),
        "structure_only_blocks": structure_only,
        "blocks_missing": len(missing_seen),
        "blocks_fail": len(findings),
        "max_delta_pct": args.max_delta_pct,
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
        print(f"{STRUCTURE_ONLY_TOKEN} {len(structure_only)} pre_vs_post.json "
              f"artefact(s) ({names}) re-simulated a library default, not a "
              f"bound input [{GATE}]")

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
                            f"all {len(missing_seen)} block(s) missing "
                            f"pre_vs_post.json; defer to skill `{SKILL}`.")
    if missing_seen:
        # PARTIAL block coverage. Until this change it fell through to
        # emit_pass, so a run in which `analog-extraction-resim` produced a
        # pre-vs-post comparison for 1 of N declared blocks certified A7 done
        # while N-1 declared blocks had been measured on nothing. The flow
        # declaration cannot catch it: A7's `required_outputs` is the single
        # glob `phase3/analog/*/pre_vs_post.json`, which is satisfied by its
        # FIRST match. Per-block coverage is knowable only here.
        # A1-A5 already emit INCOMPLETE for exactly this shape; A7 did not,
        # so the same partially-covered project read red at A1-A5 and green
        # at A7. Same shared emitter, same verdict, same exit code.
        rc = emit_incomplete(GATE, args, missing_seen, summary, SKILL)
        _disclose()
        return rc
    rc = emit_pass(GATE, args, summary, pass_token=pass_token)
    _disclose()
    return rc


if __name__ == "__main__":
    sys.exit(main())
