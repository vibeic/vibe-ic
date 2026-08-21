#!/usr/bin/env python3
"""corner_yield_vs_spec_check.py — independent yield-vs-spec.json gate
+ worst-corner identification (analog-sizing-loop rules 2 & 4).

The analog-sizing-loop skill mandated two coupled deterministic steps:

  (rule 2) "Parse yield table vs spec.json limits; if all PASS done."
  (rule 4) "Worst-corner identification ('SS @ -40C', worst_corner
            field in sizing_final.json) is the argmin of yield over
            the PVT matrix — deterministic."

`analog_corner_sweep_check.py` already gates *that a pre-computed
`spec_results[].status` field is all PASS*. This gate does something
DIFFERENT and non-overlapping: it re-derives PASS/FAIL **from the
spec.json min/max limits** (so a corner_results.json that silently
records a wrong `status` is caught), and it reports the **worst
corner** (the corner with the smallest margin to its tightest spec
limit). The worst corner is what the loop re-sizes against.

Per analog block it reads:
  * `spec.json`            — performance targets, each spec a dict with
                             a `min` and/or `max` numeric limit (the
                             canonical analog spec.json shape).
  * `corner_results.json`  — `corners[]`, each corner a dict carrying a
                             `name` plus per-spec measured values
                             (`measured`/`values` map, OR top-level
                             numeric fields keyed by spec name).

A corner FAILS a spec when its measured value violates the spec's
min/max limit. The block FAILS when any corner violates any spec.
The worst corner is the one with the smallest (most negative) margin,
where margin = signed distance into the spec band normalised by the
band / limit magnitude.

HONEST FAIL / SKIP (NO vacuous PASS):
  * No analog/ dir, or no block carries BOTH spec.json AND
    corner_results.json → rc 2 VACUOUS (nothing to check).
  * spec.json present but corner_results.json missing for a block that
    HAS a spec.json → FAIL (you declared specs but produced no corner
    evidence) unless the whole project has no corner data at all.
  * spec.json has NO numeric min/max limit on ANY spec → that block is
    reported as NO_NUMERIC_LIMITS (can't earn a PASS) → FAIL, because a
    yield-vs-spec PASS would otherwise be vacuous.
  * Unparsable JSON → ERROR + FAIL for that block.
  * deterministic-stub corner data → skipped (PASS_WITH_STUB), never
    FAILed on real PVT thresholds.

Usage:
    python3 corner_yield_vs_spec_check.py <project_dir>
    python3 corner_yield_vs_spec_check.py <project_dir> \
        --json reports/gates/corner_yield_vs_spec.json

Exit codes:
    0 = PASS: at least one block's spec.json + corner_results.json pair was
        re-derived and every corner satisfies its limits
    1 = FAIL (a corner violates a spec, or a spec block has no limits)
    2 = VACUOUS: nothing was examined — no analog/ directory, or no block
        carries BOTH spec.json and corner_results.json, so no yield was
        re-derived against any limit. #521: both used to be rc 0, on 197 of
        the 200 tracked project roots — the whole-gate counterpart of the
        "NO vacuous PASS" rules above. Also rc 2 for an IO / argument error.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

import _vacuous_exit as _vx
from _analog_a_check_common import (
    CONTENT_DESIGN_BOUND, CONTENT_STRUCTURE_ONLY, CONTENT_UNDISCLOSED,
    STRUCTURE_ONLY_TOKEN, classify_design_content,
)


_STUB_KEY = "extraction_strategy"
_STUB_VAL = "deterministic_stub"

# ── WHAT THE YIELD WAS RE-DERIVED OVER ────────────────────────────────────
# THE RULE, with no tool or block name in it:
#
#   A gate that re-derives a verdict from an artefact's numbers is making a
#   claim about the thing those numbers describe. It must read what that thing
#   is, and it must not report a measurement of a library default as a
#   measurement of the design — nor certify at all from an artefact that will
#   not say which of the two it holds.
#
# Measured before this: on a project whose every corner artefact RECORDS that
# its circuit came from a topology library and that no bound input reached any
# device parameter, this gate re-derived the yield, found every corner inside
# the spec band, and answered `[PASS]` rc 0. Nine real corners on a library
# nominal is a self-test of the topology library; the spec it satisfied is the
# design's, and the circuit that satisfied it is not.
#
# THREE OUTCOMES, ranked so that disclosure is never the expensive answer:
#   design-bound  -> PASS, unchanged.
#   structure-only-> PASS_STRUCTURE_ONLY. It certifies, in its own tier, and
#                    leaves the design-bound pass count. Not a FAIL: the
#                    bounded inputs did not determine the content, and failing
#                    an honest ceiling teaches the next run to stop being
#                    honest.
#   undisclosed   -> does not certify. The gate cannot say what it graded, and
#                    an artefact that will not say what it contains must not
#                    be the evidence for a step.


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str = "corner_yield_vs_spec_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _analog_dir(project: Path) -> Path:
    """Mirror _path_layout.analog_dir without importing it (keeps the
    program self-contained / parallel-conflict-free)."""
    p3 = project / "phase3" / "analog"
    if p3.is_dir():
        return p3
    return project / "analog"


def _load_json(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _is_stub(data: dict) -> bool:
    return isinstance(data, dict) and data.get(_STUB_KEY) == _STUB_VAL


def _spec_limits(spec_json: dict) -> Dict[str, dict]:
    """Return {spec_name: {"min": float|None, "max": float|None}} for
    every spec that carries at least one numeric limit. Accepts the
    canonical shapes:
      {"specs": {"gain_db": {"min": 55}, ...}}
      {"specs": [{"name":"gain_db","min":55}, ...]}
      {"gain_db": {"min": 55}, ...}   (flat)
    """
    specs = spec_json.get("specs", spec_json)
    out: Dict[str, dict] = {}
    items = []
    if isinstance(specs, dict):
        items = list(specs.items())
    elif isinstance(specs, list):
        for e in specs:
            if isinstance(e, dict):
                nm = e.get("name") or e.get("spec")
                if isinstance(nm, str):
                    items.append((nm, e))
    for name, body in items:
        if name in ("name", "spec"):
            continue
        if not isinstance(body, dict):
            continue
        lo = body.get("min")
        hi = body.get("max")
        lo = float(lo) if isinstance(lo, (int, float)) else None
        hi = float(hi) if isinstance(hi, (int, float)) else None
        if lo is not None or hi is not None:
            out[name] = {"min": lo, "max": hi}
    return out


def _corner_measured(corner: dict) -> Dict[str, float]:
    """Pull {spec_name: measured_value} from one corner dict."""
    if not isinstance(corner, dict):
        return {}
    meas = corner.get("measured")
    if not isinstance(meas, dict):
        meas = corner.get("values")
    out: Dict[str, float] = {}
    if isinstance(meas, dict):
        for k, v in meas.items():
            if isinstance(v, (int, float)):
                out[k] = float(v)
    # also accept top-level numeric fields keyed by spec name
    for k, v in corner.items():
        if k in ("name", "corner", "measured", "values"):
            continue
        if isinstance(v, (int, float)) and k not in out:
            out[k] = float(v)
    return out


def _signed_margin(value: float, lo: Optional[float],
                   hi: Optional[float]) -> float:
    """Normalised signed margin: positive = inside spec band,
    negative = violation. The smaller, the worse. Normalised by the
    band width (two-sided) or by |limit| (one-sided) so margins from
    different specs are comparable."""
    if lo is not None and hi is not None and hi > lo:
        band = hi - lo
        # distance to nearer edge, as a fraction of band
        return min(value - lo, hi - value) / band
    if lo is not None:
        denom = abs(lo) if lo != 0 else 1.0
        return (value - lo) / denom
    if hi is not None:
        denom = abs(hi) if hi != 0 else 1.0
        return (hi - value) / denom
    return float("inf")


def _violates(value: float, lo: Optional[float], hi: Optional[float]) -> bool:
    if lo is not None and value < lo:
        return True
    if hi is not None and value > hi:
        return True
    return False


def _check_block(project: Path, bdir: Path, result: AuditResult) -> Optional[dict]:
    name = bdir.name
    spec_path = bdir / "spec.json"
    corner_path = bdir / "corner_results.json"
    has_spec = spec_path.is_file()
    has_corner = corner_path.is_file()
    if not has_spec and not has_corner:
        return None  # block unrelated to this gate

    if not has_spec:
        return None  # no spec.json → nothing to compare against here

    spec_json = _load_json(spec_path)
    if spec_json is None:
        result.findings.append(Finding(
            "SPEC_PARSE_ERROR", "ERROR",
            f"Block '{name}': cannot parse spec.json",
            str(spec_path.relative_to(project))))
        result.passed = False
        return {"block": name, "pass": False, "reason": "spec_parse_error"}

    limits = _spec_limits(spec_json)
    if not limits:
        result.findings.append(Finding(
            "NO_NUMERIC_LIMITS", "ERROR",
            f"Block '{name}': spec.json declares no numeric min/max limit "
            f"on any spec — a yield-vs-spec PASS would be vacuous",
            str(spec_path.relative_to(project))))
        result.passed = False
        return {"block": name, "pass": False, "reason": "no_numeric_limits"}

    if not has_corner:
        result.findings.append(Finding(
            "MISSING_CORNER_EVIDENCE", "ERROR",
            f"Block '{name}': spec.json declares {len(limits)} spec limit(s) "
            f"but no corner_results.json was produced",
            str(spec_path.relative_to(project))))
        result.passed = False
        return {"block": name, "pass": False, "reason": "missing_corner_evidence"}

    corner_json = _load_json(corner_path)
    if corner_json is None:
        result.findings.append(Finding(
            "CORNER_PARSE_ERROR", "ERROR",
            f"Block '{name}': cannot parse corner_results.json",
            str(corner_path.relative_to(project))))
        result.passed = False
        return {"block": name, "pass": False, "reason": "corner_parse_error"}

    if _is_stub(corner_json):
        result.findings.append(Finding(
            "YIELD_STUB_SKIPPED", "INFO",
            f"Block '{name}': deterministic-stub corner data — "
            f"yield-vs-spec gate skipped (PASS_WITH_STUB)",
            str(corner_path.relative_to(project))))
        return {"block": name, "pass": True, "stub": True,
                "content": CONTENT_UNDISCLOSED}

    # READ, here, alongside the numbers it describes; ACTED ON at the end.
    # The certification question ("may this be reported as this design's
    # yield?") is asked LAST, so it never displaces the diagnosis of a block
    # that is already failing for a value reason — a reader told "say what it
    # contains" about a corner that violates its own spec limit would fix the
    # wrong thing first.
    content = classify_design_content(corner_json.get("design_content"))

    corners = corner_json.get("corners")
    if not isinstance(corners, list) or not corners:
        result.findings.append(Finding(
            "NO_CORNERS", "ERROR",
            f"Block '{name}': corner_results.json carries no corners[]",
            str(corner_path.relative_to(project))))
        result.passed = False
        return {"block": name, "pass": False, "reason": "no_corners"}

    block_ok = True
    violations = 0
    corners_with_data = 0
    worst_corner = None
    worst_margin = float("inf")
    for idx, corner in enumerate(corners):
        cname = (corner.get("name") if isinstance(corner, dict) else None) \
            or f"#{idx}"
        measured = _corner_measured(corner if isinstance(corner, dict) else {})
        if not measured:
            continue
        for spec_name, lim in limits.items():
            if spec_name not in measured:
                continue
            corners_with_data += 1
            val = measured[spec_name]
            margin = _signed_margin(val, lim["min"], lim["max"])
            if margin < worst_margin:
                worst_margin = margin
                worst_corner = cname
            if _violates(val, lim["min"], lim["max"]):
                violations += 1
                block_ok = False
                result.findings.append(Finding(
                    "SPEC_VIOLATED_AT_CORNER", "ERROR",
                    f"Block '{name}': spec '{spec_name}'={val:g} violates "
                    f"limit(min={lim['min']},max={lim['max']}) at corner "
                    f"'{cname}'",
                    str(corner_path.relative_to(project))))

    if corners_with_data == 0:
        result.findings.append(Finding(
            "NO_OVERLAP", "ERROR",
            f"Block '{name}': no corner measured value matches any spec.json "
            f"limit name — cannot earn a yield PASS",
            str(corner_path.relative_to(project))))
        result.passed = False
        return {"block": name, "pass": False, "reason": "no_spec_overlap"}

    if not block_ok:
        result.passed = False

    detail = {
        "block": name,
        "pass": block_ok,
        "content": content,
        "specs_with_limits": len(limits),
        "checked_corners": len(corners),
        "violations": violations,
        "worst_corner": worst_corner,
        "worst_margin": (None if worst_margin == float("inf")
                         else round(worst_margin, 6)),
    }
    if block_ok and content == CONTENT_UNDISCLOSED:
        detail["pass"] = False
        detail["reason"] = "design_content_undeclared"
        result.findings.append(Finding(
            "YIELD_SUBJECT_UNDECLARED", "ERROR",
            f"Block '{name}': every corner satisfies every limit, and the "
            f"corner artefact records no answer to what its circuit contains "
            f"(`design_content` {corner_json.get('design_content')!r}) — so "
            f"the yield re-derived here cannot be reported as this design's. "
            f"A record that names a library default "
            f"(`{CONTENT_STRUCTURE_ONLY}`) certifies in its own tier; "
            f"declining to answer does not, or saying nothing would cost "
            f"less than saying so.",
            str(corner_path.relative_to(project))))
        result.passed = False
    elif block_ok and content == CONTENT_STRUCTURE_ONLY:
        # Disclosed as a library default. The margins above are real and they
        # are margins OF THAT TOPOLOGY — reported, never as this design's.
        result.findings.append(Finding(
            "YIELD_STRUCTURE_ONLY", "WARNING",
            f"Block '{name}': {len(corners)} corners satisfy all "
            f"{len(limits)} spec limit(s), and the corner artefact records "
            f"that its circuit came from a topology library with no bound "
            f"input reaching any device parameter. The yield re-derived here "
            f"is the LIBRARY DEFAULT's yield against this spec, not the "
            f"design's; worst corner '{worst_corner}' margin "
            f"{worst_margin:.3f}",
            str(corner_path.relative_to(project))))
    elif block_ok:
        result.findings.append(Finding(
            "YIELD_OK", "INFO",
            f"Block '{name}': {len(corners)} corners satisfy all "
            f"{len(limits)} spec limit(s); worst corner '{worst_corner}' "
            f"margin {worst_margin:.3f}",
            str(corner_path.relative_to(project))))
    return detail


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()
    adir = _analog_dir(project)
    if not adir.is_dir():
        result.findings.append(Finding(
            "SKIP_NO_ANALOG_DIR", "INFO",
            "No analog/ directory; skipping yield-vs-spec check"))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    details = []
    for bdir in sorted(d for d in adir.iterdir() if d.is_dir()):
        d = _check_block(project, bdir, result)
        if d is not None:
            details.append(d)

    if not details:
        result.findings.append(Finding(
            "SKIP_NO_SPEC_DATA", "INFO",
            "No block carries spec.json; nothing to compare"))
        result.summary = {"skipped": True, "reason": "no_spec_data"}
        return result

    so = [x["block"] for x in details
          if x.get("pass") and x.get("content") == CONTENT_STRUCTURE_ONLY]
    result.summary = {
        "skipped": False,
        "blocks_checked": len(details),
        "blocks_pass": sum(1 for x in details if x.get("pass")),
        # The design-bound pass count is the one a reader wants when asking
        # "did this design's yield close" — `blocks_pass` answers a different
        # question and is kept for back-compat.
        "blocks_design_bound_pass": sum(
            1 for x in details
            if x.get("pass") and x.get("content") == CONTENT_DESIGN_BOUND),
        "blocks_structure_only": len(so),
        "structure_only_blocks": so,
        "blocks_fail": sum(1 for x in details if not x.get("pass")),
        "details": details,
        "pass": result.passed,
    }
    return result


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)
    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)
    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)

    # The tier travels on the verdict WORD, so a reader of the one line can
    # tell a design-bound yield from a library default's without opening the
    # JSON. `pass_token` is the seam `_vacuous_exit` already provides for
    # exactly this (it is how PASS_WITH_WAIVERS reaches the line), and it
    # applies only to a genuine pass — a failing run still reads FAIL.
    so_blocks = result.summary.get("structure_only_blocks") or []
    design_bound = result.summary.get("blocks_design_bound_pass", 0)
    pass_token = ("PASS_STRUCTURE_ONLY"
                  if (so_blocks and not design_bound) else "PASS")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    else:
        print(_vx.verdict_line("corner_yield_vs_spec_check", result.passed,
                               skipped, reason, pass_token=pass_token))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    # LAST, SHORT, and on every path — the disclosure the flow auditor reads
    # from a fixed-width tail of this stream, whatever the verdict was. Written
    # to stderr for the same reason `announce_vacuous` is: `--json` puts a
    # document on stdout and a sentinel mixed into it would not parse.
    if so_blocks:
        names = ", ".join(str(b) for b in so_blocks)
        if len(names) > 60:
            names = f"{names[:57]}..."
        print(f"{STRUCTURE_ONLY_TOKEN} {len(so_blocks)} corner_results.json "
              f"artefact(s) ({names}) came from a library default, not a "
              f"bound input [corner_yield_vs_spec_check]", file=sys.stderr)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
