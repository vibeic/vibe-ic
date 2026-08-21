#!/usr/bin/env python3
"""sizing_history_emit.py — fixed-schema validator/emitter for the
analog-sizing-loop output artefacts (rule 6).

The skill defines two output schemas:

  sizing_final.json:
    block_name (str), iterations (int), converged (bool),
    final_sizing ({device: {W,L,role}}), worst_corner (str),
    yield_pct (number)

  sizing_history.json:
    iterations: [ {iter:int, changes:str, ...,
                   tt_pass?:bool, all_corners_pass?:bool,
                   worst?:str, reason?:str, fingerprint?:str} ]

"Output-schema emission ... is structured-JSON authoring with a fixed
schema — deterministic serialization, not LLM." This program is the
deterministic gate: it VALIDATES that an emitted artefact conforms to
the fixed schema (so a malformed/half-authored sizing_final.json is
caught), and in `emit` mode it serialises a validated artefact.

The validator also enforces three cross-field invariants the schema
prose implies but a naive emitter can violate:
  * `iterations` in sizing_final.json must equal the number of records
    in sizing_history.json (when both are validated together).
  * `converged: true` requires the LAST history record to carry
    `all_corners_pass: true` (you cannot claim convergence without a
    full-corner pass on the final iteration).
  * `final_sizing` must be non-empty and every device must carry W & L.

HONEST FAIL (NO vacuous PASS):
  * Missing required field → exit 1 + MISSING_FIELD (named).
  * Wrong type for a required field → exit 1 + BAD_TYPE.
  * `converged: true` with no terminal all_corners_pass → exit 1 +
    UNSUPPORTED_CONVERGENCE.
  * Missing / unparsable input file → exit 2 (cannot validate).

Usage:
    # validate an already-emitted artefact
    python3 sizing_history_emit.py validate-final  sizing_final.json
    python3 sizing_history_emit.py validate-history sizing_history.json
    python3 sizing_history_emit.py validate-final sizing_final.json \
        --history sizing_history.json --json out.json

    # emit a validated sizing_final.json from a JSON spec on stdin/file
    python3 sizing_history_emit.py emit-final input.json --out sizing_final.json

Exit codes:
    0 = schema valid / emitted
    1 = FAIL (schema violation)
    2 = IO / argument error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

FINAL_REQUIRED = {
    "block_name": str,
    "iterations": int,
    "converged": bool,
    "final_sizing": dict,
    "worst_corner": str,
    "yield_pct": (int, float),
}


def _load(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    if not path.is_file():
        return None, f"{path} not found"
    try:
        return json.loads(path.read_text(errors="replace")), None
    except (json.JSONDecodeError, OSError) as e:
        return None, f"cannot parse {path}: {e}"


def validate_final(data: dict) -> List[dict]:
    """Return a list of violation dicts (empty = valid)."""
    out: List[dict] = []
    if not isinstance(data, dict):
        return [{"rule": "BAD_TYPE", "field": "<root>",
                 "message": "sizing_final must be a JSON object"}]
    for field, typ in FINAL_REQUIRED.items():
        if field not in data:
            out.append({"rule": "MISSING_FIELD", "field": field,
                        "message": f"sizing_final missing '{field}'"})
            continue
        # bool is a subclass of int — guard the int field explicitly.
        val = data[field]
        if typ is int and isinstance(val, bool):
            out.append({"rule": "BAD_TYPE", "field": field,
                        "message": f"'{field}' must be int, got bool"})
        elif not isinstance(val, typ):
            out.append({"rule": "BAD_TYPE", "field": field,
                        "message": (f"'{field}' must be {typ}, "
                                    f"got {type(val).__name__}")})
    # final_sizing substance: non-empty, every device carries W & L
    fs = data.get("final_sizing")
    if isinstance(fs, dict):
        if not fs:
            out.append({"rule": "EMPTY_FINAL_SIZING", "field": "final_sizing",
                        "message": "final_sizing is empty"})
        for dev, body in fs.items():
            if not isinstance(body, dict):
                out.append({"rule": "BAD_DEVICE", "field": f"final_sizing.{dev}",
                            "message": f"device '{dev}' must be an object"})
                continue
            for k in ("W", "L"):
                if k not in body:
                    out.append({"rule": "DEVICE_MISSING_DIM",
                                "field": f"final_sizing.{dev}.{k}",
                                "message": f"device '{dev}' missing '{k}'"})
    return out


def validate_history(data: dict) -> List[dict]:
    out: List[dict] = []
    if not isinstance(data, dict):
        return [{"rule": "BAD_TYPE", "field": "<root>",
                 "message": "sizing_history must be a JSON object"}]
    iters = data.get("iterations")
    if not isinstance(iters, list):
        return [{"rule": "MISSING_FIELD", "field": "iterations",
                 "message": "sizing_history missing 'iterations' list"}]
    if not iters:
        out.append({"rule": "EMPTY_HISTORY", "field": "iterations",
                    "message": "sizing_history has zero iterations"})
    for i, rec in enumerate(iters):
        if not isinstance(rec, dict):
            out.append({"rule": "BAD_RECORD", "field": f"iterations[{i}]",
                        "message": "iteration record must be an object"})
            continue
        if "iter" not in rec and "iteration" not in rec:
            out.append({"rule": "MISSING_FIELD", "field": f"iterations[{i}].iter",
                        "message": "iteration record missing 'iter'"})
        if "changes" not in rec:
            out.append({"rule": "MISSING_FIELD",
                        "field": f"iterations[{i}].changes",
                        "message": "iteration record missing 'changes'"})
        # v0.2.25 — the sizing loop's "do not make more than 2 simultaneous
        # changes per iteration" discipline, now a deterministic check (was
        # prose-only — D3 re-audit residual). Enforced structurally when the
        # iteration records a `changed_params` list: > 2 changed parameters in
        # one iteration breaks single-variable attribution (you cannot tell
        # which knob moved the metric). Legacy records that carry only the
        # free-text `changes` string are not counted (no schema regression);
        # to enforce, emit `changed_params: [<param>, ...]`.
        cp = rec.get("changed_params")
        if isinstance(cp, list) and len(cp) > 2:
            out.append({"rule": "TOO_MANY_SIMULTANEOUS_CHANGES",
                        "field": f"iterations[{i}].changed_params",
                        "message": (f"iteration changed {len(cp)} parameters "
                                    f"{cp} — the sizing loop must not make more "
                                    f"than 2 simultaneous changes per iteration "
                                    f"(single-variable attribution discipline).")})
    return out


def _cross_field(final: dict, history: dict) -> List[dict]:
    out: List[dict] = []
    iters = history.get("iterations")
    if isinstance(iters, list):
        declared = final.get("iterations")
        if isinstance(declared, int) and not isinstance(declared, bool):
            if declared != len(iters):
                out.append({"rule": "ITERATION_COUNT_MISMATCH",
                            "field": "iterations",
                            "message": (f"sizing_final.iterations={declared} "
                                        f"≠ {len(iters)} history records")})
        if final.get("converged") is True and iters:
            last = iters[-1]
            if not (isinstance(last, dict)
                    and last.get("all_corners_pass") is True):
                out.append({"rule": "UNSUPPORTED_CONVERGENCE",
                            "field": "converged",
                            "message": ("converged=true but final history "
                                        "record lacks all_corners_pass=true")})
    return out


def _report_and_exit(args, program_mode: str, violations: List[dict]) -> int:
    passed = not violations
    report = {
        "program": "sizing_history_emit",
        "mode": program_mode,
        "passed": passed,
        "violations": violations,
    }
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2,
                                               ensure_ascii=False))
    else:
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] sizing_history_emit {program_mode}")
        for v in violations:
            print(f"  [{v['rule']}] {v['field']}: {v['message']}")
    return 0 if passed else 1


def cmd_validate_final(args) -> int:
    data, err = _load(Path(args.path))
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    violations = validate_final(data)
    if args.history:
        hist, herr = _load(Path(args.history))
        if herr:
            print(f"ERROR: {herr}", file=sys.stderr)
            return 2
        violations += validate_history(hist)
        violations += _cross_field(data, hist)
    return _report_and_exit(args, "validate-final", violations)


def cmd_validate_history(args) -> int:
    data, err = _load(Path(args.path))
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    return _report_and_exit(args, "validate-history", validate_history(data))


def cmd_emit_final(args) -> int:
    data, err = _load(Path(args.path))
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    violations = validate_final(data)
    if violations:
        return _report_and_exit(args, "emit-final", violations)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"[PASS] emitted validated sizing_final → {args.out}")
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_vf = sub.add_parser("validate-final")
    p_vf.add_argument("path")
    p_vf.add_argument("--history", default=None,
                      help="also validate this sizing_history.json + cross-fields")
    p_vf.add_argument("--json", default=None)
    p_vf.set_defaults(func=cmd_validate_final)

    p_vh = sub.add_parser("validate-history")
    p_vh.add_argument("path")
    p_vh.add_argument("--json", default=None)
    p_vh.set_defaults(func=cmd_validate_history)

    p_ef = sub.add_parser("emit-final")
    p_ef.add_argument("path", help="input JSON to validate then emit")
    p_ef.add_argument("--out", required=True)
    p_ef.add_argument("--json", default=None)
    p_ef.set_defaults(func=cmd_emit_final)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
