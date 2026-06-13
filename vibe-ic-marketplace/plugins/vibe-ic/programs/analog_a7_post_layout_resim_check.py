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
  A7_POSTSIM_NO_A4_SIM      — A4 says SPICE never ran (escape link)

VACUOUS_PASS when `analog/analog_block_list.json` is missing or empty.
chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail,
)

GATE = "analog_a7_post_layout_resim_check"
SKILL = "analog-extraction-resim"
DEFAULT_MAX_DELTA_PCT = 10.0


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


def _check_specs(specs: list) -> list[float]:
    """Return list of |delta_pct| values for entries that carry both
    pre_value and post_value. Skips ill-formed entries."""
    deltas: list[float] = []
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
    return deltas


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
    if isinstance(specs, list) and specs:
        deltas = _check_specs(specs)
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
            deltas = _check_specs(built)
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
                            "phase3/analog/analog_block_list.json missing or "
                            "empty; gate inapplicable.")

    blocks = select_blocks(blocks_all or [], args.block)
    if not blocks:
        return vacuous_pass(GATE, args, "no blocks selected.")

    findings: List[dict] = []
    blocks_pass = 0
    missing_seen: List[dict] = []
    for block in blocks:
        status, fs = _check_block(project, block, args.max_delta_pct)
        if status == "PASS":
            blocks_pass += 1
        elif status == "MISSING":
            missing_seen.extend(fs)
        else:
            findings.extend(fs)

    summary = {
        "blocks_checked": len(blocks),
        "blocks_pass": blocks_pass,
        "blocks_missing": len(missing_seen),
        "blocks_fail": len(findings),
        "max_delta_pct": args.max_delta_pct,
    }

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
                            f"pre_vs_post.json; defer to skill `{SKILL}`.")
    return emit_pass(GATE, args, summary)


if __name__ == "__main__":
    sys.exit(main())
