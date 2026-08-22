#!/usr/bin/env python3
"""analog_pre_vs_post_layout_check.py — deterministic gate for pre/post-layout comparison

Validates that post-layout analog specs don't degrade beyond acceptable
limits compared to pre-layout SPICE results.

For each spec in pre_vs_post.json:
  - ≤20 % degradation → INFO (acceptable)
  - >20 % degradation → WARNING
  - >30 % degradation → ERROR (layout severely impacts performance)

Self-skips when:
  - No analog/ directory, or no analog/*/pre_vs_post.json files found

Usage:
    python3 analog_pre_vs_post_layout_check.py <project_dir>
    python3 analog_pre_vs_post_layout_check.py <project_dir> --json reports/gates/pre_vs_post.json

Exit codes:
    0 = PASS: a pre/post comparison was read, no spec degrades past the floor,
        and the artefact chain names what was compared. PASS_STRUCTURE_ONLY —
        also rc 0, in its own disclosed tier — when what was compared is a
        library default and the chain says so.
    1 = FAIL (severe degradation; or every compared spec compared a number
        against ITSELF and no post-layout artefact is named that resolves on
        disk — `PRE_VS_POST_ALL_ZERO_DELTA_UNEVIDENCED`, the rule and its
        deliberate limits live at `_analog_a_check_common
        .pre_vs_post_zero_delta`; or nothing anywhere names what was compared)
    2 = VACUOUS: nothing was examined — no analog/ directory, or no
        pre_vs_post.json at all, so no parasitic degradation was ever
        compared. #521: both used to be rc 0, on 199 of the 200 tracked
        project roots. Also rc 2 for an IO / parse error.

═══ WHY THIS GATE ASKS THE CONTENT QUESTION AT ALL ═══════════════════════
THE INVARIANT, with no tool, step or block name in it:

    Two gates that certify ONE artefact must not disagree about it.

THIS gate is the one `flow/phase1_phase2_phase3.yaml` DECLARES for the
post-layout step (`program_exit_zero: "analog_pre_vs_post_layout_check . --json
reports/phase2/gates/pre_vs_post.json"`). `analog_a7_post_layout_resim_check`
— the gate the A-track runner runs over the SAME
`phase3/analog/<block>/pre_vs_post.json` — appears ZERO times in that YAML.
Both are in `flow_compliance_check`'s program roster.

MEASURED, on three synthetic trees identical in every artefact except the one
recorded `design_content` value:

    analog_pre_vs_post_layout_check   rc 0 PASS / rc 0 PASS / rc 0 PASS
    analog_a7_post_layout_resim_check rc 0 PASS / rc 0 PASS_STRUCTURE_ONLY /
                                      rc 1 FAIL

byte-identical console AND byte-identical `--json` artefact from THIS gate on
all three. On the silent tree the two disagreed outright, and the one the flow
declares was the one that could not tell the trees apart.

WHY THE RULE WAS ADDED HERE RATHER THAN THE FLOW BEING REPOINTED AT THE OTHER
GATE. Re-pointing the declaration would have DELETED this gate's own value
rules from the step — the 20 %/30 % degradation tiers and
`PRE_VS_POST_ZERO_COMPARED` — and handed the step's declared
`--json reports/phase2/gates/pre_vs_post.json` contract to a program with a
different report schema. It would also not have established the invariant:
both gates stay in the compliance roster either way, so both still run and the
disagreement would merely have changed which of the two was labelled
"declared". The content rule is a property of the ARTEFACT, so every gate that
certifies that artefact asks it, through ONE shared site
(`_analog_a_check_common.pre_vs_post_content`) rather than a copied predicate.

ASKED LAST, after the degradation tiers and after the zero-compared rule, and
per block after that block's own value findings — each of those names a deeper
cause and answers this one as a side effect.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional
import _path_layout as _pl
import _vacuous_exit as _vx
import _analog_a_check_common as _acc
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


# ── accepted pre_vs_post.json schema ──────────────────────────────────────
# Single source of truth for the key names, mirrored in
# `skills/analog-extraction-resim/SKILL.md`. The two drifted once (the skill
# documented "comparison", singular; this gate has only ever read
# "comparisons"/"specs"), which made a result authored exactly per the skill's
# own example FAIL as if it contained no data.
#
# The CONTAINER key names were widened once for exactly that reason. The VALUE
# key names were not given the same treatment, and the identical defect was
# still live one level down: `analog_a7_post_layout_resim_check` reads the SAME
# `phase3/analog/<block>/pre_vs_post.json` and its documented schema spells the
# values `pre_value` / `post_value`. The two vocabularies were DISJOINT, so an
# author could satisfy at most one of the two gates. Measured on a file
# authored exactly to the A7 gate's own documented schema:
#
#   analog_a7_post_layout_resim_check   rc=0  PASS — 1/1 block(s) clean
#   analog_pre_vs_post_layout_check     rc=1  PRE_VS_POST_ZERO_COMPARED:
#       pre_vs_post.json present but 0 specs were compared
#
# Two gates reading one artefact must read it with one vocabulary, or the
# artefact has no satisfiable schema at all. `pre_value`/`post_value` are
# appended rather than substituted, so every file that satisfied this gate
# before still satisfies it byte-for-byte, and the earlier spellings keep
# priority.
_CONTAINER_KEYS: tuple = ("comparisons", "specs")
_PRE_KEYS: tuple = ("pre_layout", "pre", "pre_value")
_POST_KEYS: tuple = ("post_layout", "post", "post_value")
#: The artefact states the delta as well as the two values it is derived from,
#: so the document can be checked AGAINST ITSELF (vibe-ic D9, criterion 1:
#: self-consistency). Same disjoint-vocabulary hazard as the pair above, so the
#: spellings are listed rather than assumed.
_DELTA_KEYS: tuple = ("delta_pct", "delta_percent", "delta_pc", "change_pct")

#: Tolerance on the stated-vs-implied delta, in percentage POINTS. Wide on
#: purpose: this rule exists to catch a delta that does not describe its own
#: pair at all, never to police rounding. The published artefact states
#: `delta_pct` to 4 decimal places and agrees to ~1e-4, so 0.5 points is three
#: orders of magnitude of headroom.
_DELTA_TOLERANCE_PP = 0.5


def _first_key(item: dict, keys: tuple):
    for k in keys:
        if k in item:
            return item[k]
    return None


def _cite(path: Optional[Path], project: Path) -> Optional[str]:
    """Project-relative citation, never an exception. The FLOW invokes this
    gate as `analog_pre_vs_post_layout_check . --json ...`, so `project` is
    `.` and `Path("phase3/x").relative_to(Path("."))` raises — a citation
    string is not worth a traceback in the gate that certifies the step."""
    if path is None:
        return None
    try:
        return str(Path(path).relative_to(project))
    except ValueError:
        return str(path)


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "analog_pre_vs_post_layout_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    analog_dir = _pl.analog_dir(project)
    if not analog_dir.is_dir():
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG_DIR",
            severity="INFO",
            message="No analog/ directory; skipping pre-vs-post layout check",
        ))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    pvp_files = sorted(analog_dir.glob("*/pre_vs_post.json"))
    if not pvp_files:
        result.findings.append(Finding(
            rule="SKIP_NO_PRE_VS_POST",
            severity="INFO",
            message="No pre_vs_post.json files; post-layout comparison not performed",
        ))
        result.summary = {"skipped": True, "reason": "no_pre_vs_post_data"}
        return result

    total_specs = 0
    errors = 0
    max_degradation = 0.0
    structure_only: List[str] = []
    design_bound: List[str] = []
    undisclosed: List[str] = []
    # Blocks whose every compared spec compared a number against ITSELF, with
    # no post-layout artefact named that resolves on disk. See
    # `_analog_a_check_common.pre_vs_post_zero_delta` for the rule and for what
    # it deliberately does not catch.
    unevidenced_zero: List[str] = []
    # Blocks whose pre_vs_post.json parsed as JSON but exposed NO container
    # under a key this gate reads. Kept so the zero-compared verdict can name
    # the cause (schema drift) instead of implying the file held no data.
    unreadable_schema: List[str] = []

    for pvp_path in pvp_files:
        block = pvp_path.parent.name
        block_errors = 0
        block_specs = 0
        # The (pre, post) pairs THIS gate actually compared, handed to the
        # shared zero-delta rule so both gates over this artefact stay bounded
        # by the same reading of it.
        block_pairs: List[tuple] = []
        try:
            data = json.loads(pvp_path.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            result.findings.append(Finding(
                rule="PRE_VS_POST_PARSE_ERROR",
                severity="WARNING",
                message=f"Cannot parse pre_vs_post.json for block '{block}'",
                file=str(pvp_path),
            ))
            continue

        # ONLY these container keys are read. `skills/analog-extraction-resim`
        # documents the same list; when they drift, a spec-compliant result is
        # scored as zero comparisons, so the drift is named explicitly below
        # rather than surfacing as a bare "no numeric pre/post pairs".
        container_key = next(
            (k for k in _CONTAINER_KEYS if isinstance(data, dict) and k in data),
            None)
        comparisons = data.get(container_key) if container_key else None
        if isinstance(comparisons, list):
            comp_iter = comparisons
        elif isinstance(comparisons, dict):
            comp_iter = [{"name": k, **v} for k, v in comparisons.items()]
        else:
            if isinstance(data, dict):
                unreadable_schema.append(
                    f"{block}: top-level keys "
                    f"{sorted(str(k) for k in data)} — none of "
                    f"{list(_CONTAINER_KEYS)} present")
            continue

        for item in comp_iter:
            if isinstance(item, dict):
                name = item.get("name", item.get("spec", "?"))
                pre_val = _first_key(item, _PRE_KEYS)
                post_val = _first_key(item, _POST_KEYS)
            else:
                continue

            if pre_val is None or post_val is None:
                continue
            if not isinstance(pre_val, (int, float)) or not isinstance(post_val, (int, float)):
                continue
            if pre_val == 0:
                continue

            total_specs += 1
            block_specs += 1
            block_pairs.append((pre_val, post_val))
            pct = abs(post_val - pre_val) / abs(pre_val) * 100
            max_degradation = max(max_degradation, pct)

            # ── SELF-CONSISTENCY (D9). NO ORACLE, and that is the point ──
            # The document states `delta_pct` next to the two values it is
            # derived from. Nothing here knows what the delta OUGHT to be — a
            # real project ships no answer key — it only asks whether the
            # document agrees with itself. A stated delta that does not
            # describe its own (pre, post) pair means the three numbers did
            # not come from one measurement, and every degradation tier above
            # is then reasoning about a pair no one computed.
            #
            # Measured cause: this gate read `pre_value`/`post_value` and never
            # read `delta_pct` at all, so scaling every number in the artefact
            # left the verdict at PASS — the D9 census's EXISTENCE-ONLY verdict
            # for step A7.
            stated = _first_key(item, _DELTA_KEYS)
            if isinstance(stated, (int, float)) and not isinstance(stated, bool):
                if abs(abs(stated) - pct) > _DELTA_TOLERANCE_PP:
                    errors += 1
                    block_errors += 1
                    result.findings.append(Finding(
                        rule="PRE_VS_POST_DELTA_INCONSISTENT",
                        severity="ERROR",
                        message=(
                            f"Block '{block}' spec '{name}': the artefact states "
                            f"delta {stated} but pre={pre_val} and post={post_val} "
                            f"imply {pct:.4f} (tolerance "
                            f"{_DELTA_TOLERANCE_PP} points). The document does not "
                            f"agree with itself, so the three numbers did not come "
                            f"from one measurement"
                        ),
                        file=str(pvp_path),
                    ))

            if pct > 30:
                errors += 1
                block_errors += 1
                result.findings.append(Finding(
                    rule="LAYOUT_SEVERE_DEGRADATION",
                    severity="ERROR",
                    message=(
                        f"Block '{block}' spec '{name}': "
                        f"pre={pre_val}, post={post_val} "
                        f"({pct:.1f}% degradation — layout severely impacts performance)"
                    ),
                ))
            elif pct > 20:
                result.findings.append(Finding(
                    rule="LAYOUT_MODERATE_DEGRADATION",
                    severity="WARNING",
                    message=(
                        f"Block '{block}' spec '{name}': "
                        f"pre={pre_val}, post={post_val} "
                        f"({pct:.1f}% degradation)"
                    ),
                ))
            else:
                result.findings.append(Finding(
                    rule="LAYOUT_ACCEPTABLE",
                    severity="INFO",
                    message=(
                        f"Block '{block}' spec '{name}': "
                        f"pre={pre_val}, post={post_val} "
                        f"({pct:.1f}% — acceptable). OK."
                    ),
                ))

        # ── the certification question, asked LAST ────────────────────────
        # Only for a block that got this far: a block with a severe
        # degradation, or with nothing comparable in it at all, already has a
        # deeper finding of its own and that finding is the one to fix first.
        if block_errors or block_specs == 0:
            continue

        # ── did a SECOND measurement happen at all? ───────────────────────
        # Asked after the degradation tiers — a block whose specs really moved
        # cannot be degenerate, so the tiers and this rule never compete — and
        # BEFORE the content question, because it names the deeper cause: what
        # circuit was compared does not matter yet if the post column is the
        # pre column. A reader told "say what you compared" about a file that
        # compared nothing twice would fix the wrong thing first.
        zd = _acc.pre_vs_post_zero_delta(pvp_path.parent, block_pairs,
                                         project=project, doc=data)
        if not zd.certifies:
            unevidenced_zero.append(block)
            result.findings.append(Finding(
                rule="PRE_VS_POST_ALL_ZERO_DELTA_UNEVIDENCED",
                severity="ERROR",
                message=(f"Block '{block}': "
                         + _acc.zero_delta_refusal_detail(zd)),
                file=str(pvp_path),
            ))
            continue

        bounded = _acc.pre_vs_post_content(pvp_path.parent)
        cited = _cite(bounded.source, project)
        baseline = pvp_path.parent / _acc.CONTENT_GATE_OF_RECORD_ARTEFACT

        if bounded.klass == _acc.CONTENT_UNDISCLOSED:
            undisclosed.append(block)
            if bounded.refused is not None:
                said = (f"this artefact claims `{bounded.refused}` while the "
                        f"pre-layout corner result it is compared against "
                        f"records no answer at all — and a comparison cannot "
                        f"be more design-bound than its own baseline. Nothing "
                        f"deterministic writes this field into "
                        f"`{_acc.PRE_VS_POST_DERIVED_ARTEFACT}`; the record "
                        f"belongs to "
                        f"`{_acc.CONTENT_GATE_OF_RECORD_ARTEFACT}`, and that "
                        f"is where the fix belongs")
            elif not baseline.is_file():
                said = ("no corner artefact exists to say what circuit was "
                        "compared (`design_content`)")
            else:
                said = (f"`{_acc.CONTENT_GATE_OF_RECORD_ARTEFACT}` records no "
                        f"answer to what circuit was compared "
                        f"(`design_content`)")
            result.findings.append(Finding(
                rule="PRE_VS_POST_DESIGN_CONTENT_UNDECLARED",
                severity="ERROR",
                message=(
                    f"Block '{block}': every declared spec is within the "
                    f"degradation floor, and {said}. A pre/post comparison of "
                    f"a library topology and one of a design sized to its "
                    f"spec are indistinguishable in every other field of this "
                    f"file. Declaring "
                    f"`{_acc.CONTENT_STRUCTURE_ONLY}` is not a penalty — it "
                    f"certifies, in its own disclosed tier; declining to "
                    f"answer does not, or saying nothing would cost less than "
                    f"saying so."),
                file=str(pvp_path),
            ))
        elif bounded.klass == _acc.CONTENT_STRUCTURE_ONLY:
            structure_only.append(block)
            extra = ""
            if bounded.refused is not None:
                extra = (f" This artefact's own record claims "
                         f"`{bounded.refused}` and is BOUNDED to its "
                         f"baseline's answer.")
            result.findings.append(Finding(
                rule="PRE_VS_POST_STRUCTURE_ONLY",
                severity="WARNING",
                message=(
                    f"Block '{block}': the pre/post comparison is real and it "
                    f"is A LIBRARY DEFAULT's — `{cited}` records that the "
                    f"circuit came from a topology library with no bound "
                    f"input reaching any device parameter. Parasitic "
                    f"degradation measured on it is the default's, not this "
                    f"design's.{extra}"),
                file=str(pvp_path),
            ))
        else:
            design_bound.append(block)
            result.findings.append(Finding(
                rule="PRE_VS_POST_DESIGN_BOUND",
                severity="INFO",
                message=(f"Block '{block}': comparison is design-bound per "
                         f"`{cited}`."),
                file=str(pvp_path),
            ))

    if errors or undisclosed or unevidenced_zero:
        result.passed = False

    # ORGANIC-20260606 #438(c): pre_vs_post.json existed (past the
    # self-skip) but zero numeric pre/post pairs were comparable — a
    # comparison gate must FAIL, never PASS, with items_compared==0.
    if total_specs == 0:
        result.passed = False
        detail = ""
        if unreadable_schema:
            # Name the schema drift. Without this the message read as "the
            # file holds no data", which sent readers looking at the SPICE
            # run when the real cause was a container key this gate does not
            # read (measured: SKILL.md documented "comparison", singular).
            detail = (" — SCHEMA: " + "; ".join(unreadable_schema)
                      + f". Recognised container keys: {list(_CONTAINER_KEYS)};"
                        f" per-item value keys: {list(_PRE_KEYS)} /"
                        f" {list(_POST_KEYS)}")
        result.findings.append(Finding(
            rule="PRE_VS_POST_ZERO_COMPARED",
            severity="ERROR",
            message=("pre_vs_post.json present but 0 specs were "
                     "compared (no numeric pre/post pairs) — a "
                     "comparison gate must FAIL (or self-skip), never "
                     "PASS, with items_compared==0 (#438c)" + detail),
        ))

    # Same ranking as every sibling on this track: the tier reaches the verdict
    # word only when NO block was certified design-bound. A project with both
    # has a design-bound comparison to report and the structure-only subset is
    # named beside it.
    verdict_tier = ("PASS_STRUCTURE_ONLY"
                    if (result.passed and structure_only and not design_bound)
                    else "PASS")
    result.summary = {
        "skipped": False,
        "blocks_checked": len(pvp_files),
        "specs_compared": total_specs,
        "max_degradation_pct": max_degradation,
        "errors": errors,
        "design_bound_blocks": design_bound,
        "structure_only_blocks": structure_only,
        "undisclosed_blocks": undisclosed,
        "unevidenced_zero_delta_blocks": unevidenced_zero,
        "verdict_tier": verdict_tier,
        "pass": result.passed,
    }
    return result


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)
    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)

    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)

    so_blocks = (result.summary or {}).get("structure_only_blocks") or []
    if not args.json:
        # The tier travels on the verdict WORD — `pass_token` is the seam
        # `_vacuous_exit` already provides for it — so a reader of the one line
        # can tell a design-bound comparison from a library default's.
        print(_vx.verdict_line(
            "analog_pre_vs_post_layout_check", result.passed, skipped, reason,
            pass_token=((result.summary or {}).get("verdict_tier") or "PASS")))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    # LAST, SHORT, and on every path the gate can leave by — including the
    # `--json` path, which is the ONLY path the FLOW ever takes for this gate
    # (`... --json reports/phase2/gates/pre_vs_post.json`). A disclosure printed
    # only on the console path is a disclosure the flow auditor never sees,
    # which is the same defect one layer down. To stderr, for the same reason
    # `announce_vacuous` is.
    if so_blocks:
        names = ", ".join(str(b) for b in so_blocks)
        if len(names) > 60:
            names = f"{names[:57]}..."
        print(f"{_acc.STRUCTURE_ONLY_TOKEN} {len(so_blocks)} pre_vs_post.json "
              f"artefact(s) ({names}) compared a library default, not a bound "
              f"input [analog_pre_vs_post_layout_check]", file=sys.stderr)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
