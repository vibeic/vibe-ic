#!/usr/bin/env python3
"""analog_meas_from_spec_gen.py — deterministic `.meas` statement generator
from an analog block spec.json.

Rule (from skill `analog-netlist-gen`):
    Each spec key maps to a templated ngspice `.meas` line:
      * a DC operating-point spec (vout_dc, vref, ...)  -> `.meas DC ...`
      * a small-signal AC spec (gain_db, ugbw, pm, ...)  -> `.meas AC  ...`
      * a transient timing spec (tpd, tr, tf, slew, ...) -> `.meas TRAN ...`
    Given spec.json this is DETERMINISTIC template emission, not authoring.

This program reads `<block>/spec.json` and emits the corresponding `.meas`
deck to stdout (or --out). It is a GENERATOR, so its "PASS" (exit 0) means
"emitted >= 1 .meas line from real spec keys"; it FAILs honestly when the
spec is missing/garbage/has no recognizable measurable keys.

Spec key classification (case-insensitive substring / suffix):
    DC   : '_dc', 'vout', 'vref', 'vbias', 'iq', 'idd', 'idd_', 'pwr_dc'
    AC   : 'gain', 'ugbw', 'gbw', 'bw', 'pm', 'phase_margin', 'gm', 'psrr',
           'cmrr', 'db'
    TRAN : 'tpd', 'tr', 'tf', 'slew', 'settling', 'rise', 'fall', 'jitter',
           'period', 'tphl', 'tplh'

Two input shapes are accepted:
  * map:  {"vout_dc": {"value": 1.2, "unit": "V"}, ...}
  * canonical list: {"specs": [{"name": "tpd", "target": 5.0,
                                "unit": "ns", ...}, ...]}

Targets, bounds, and units are copied verbatim into trailing comments.  They
are never converted, defaulted, or used as simulated values.  A canonical-list
row with no supported measurement template (notably ENOB/SNDR, which require a
coherent stimulus and an appropriate capture) makes the generator refuse the
whole deck.  It never emits a partial deck that could be mistaken for coverage
of every declared measurement.  Explicit measurement-window metadata is also
refused until a template can apply that window, rather than silently dropping
it.  Canonical-list DC and AC rows likewise refuse when the schema does not
declare the required sweep point or AC frequency; the legacy map interface is
left unchanged for its existing callers.

Explicit ``measurement`` bindings may instead declare OP/DC/AC, the native
expression, and the DC point or AC frequency. ``first``/``last`` selects the
actual endpoint sample without extrapolating beyond a numerical sweep.
They are callable through ``measurement_commands`` as well as canonical rows.

Honest-FAIL guarantees:
  * missing spec.json                       -> exit 1, no output
  * spec.json that is not valid JSON        -> exit 2
  * spec.json with no measurable keys       -> exit 1 (NO_MEASURABLE_KEYS)
  * a valid spec with >=1 measurable key    -> exit 0 + emitted deck

Usage:
    python3 analog_meas_from_spec_gen.py <spec.json>
    python3 analog_meas_from_spec_gen.py <spec.json> --out meas.inc
    python3 analog_meas_from_spec_gen.py <spec.json> --json report.json

Exit codes:
    0 = PASS (>=1 .meas line emitted)
    1 = FAIL (missing spec / no measurable keys)
    2 = IO / parse error

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

GATE = "analog_meas_from_spec_gen"

DC_TOKENS = ("_dc", "vout", "vref", "vbias", "iq", "idd", "pwr_dc", "vop")
AC_TOKENS = ("gain", "ugbw", "gbw", "_bw", "bandwidth", "pm", "phase_margin",
             "gm", "psrr", "cmrr", "_db", "gain_db")
TRAN_TOKENS = ("tpd", "_tr", "_tf", "slew", "settling", "rise", "fall",
               "jitter", "period", "tphl", "tplh", "delay")


def measurement_commands(key: str, binding: dict) -> Tuple[List[str], str]:
    """Emit controls for an explicitly bound native expression and point.

    Bindings are ordinary source/testbench inputs. No node, current branch,
    AC frequency, sweep point, or measured value is inferred from a label.
    """
    if not re.fullmatch(r"[A-Za-z_]\w*", key) or not isinstance(binding, dict):
        raise ValueError("measurement name/binding is invalid")
    analysis = str(binding.get("analysis", "")).upper()
    expression = binding.get("expression")
    if analysis not in ("OP", "DC", "AC") or not isinstance(expression, str) or not expression.strip():
        raise ValueError("explicit OP/DC/AC analysis and native expression required")
    if any(char in expression for char in "\r\n;"):
        raise ValueError("measurement expression must be a single native expression")
    vector = "bound_" + key
    lines = [f"let {vector} = {expression}"]
    if analysis == "OP":
        lines.append(f'echo "MEAS {key}=" $&{vector}')
    else:
        point = binding.get("frequency_hz" if analysis == "AC" else "at")
        if point in ("first", "last"):
            scalar = vector + "_sample"
            index = "0" if point == "first" else f"length({vector})-1"
            lines += [f"let {scalar} = {vector}[{index}]", f'echo "MEAS {key}=" $&{scalar}']
            return lines, analysis
        if isinstance(point, bool) or not isinstance(point, (int, float)) or not math.isfinite(point):
            raise ValueError("explicit finite AC frequency/DC sweep point required")
        if analysis == "AC" and point <= 0:
            raise ValueError("AC frequency must be positive")
        lines.append(f"meas {analysis} {key} FIND {vector} AT={point:.17g}")
    return lines, analysis


def _classify(key: str) -> Optional[str]:
    k = key.lower()
    # TRAN first (timing keys are most specific), then AC, then DC.
    if any(t in k for t in TRAN_TOKENS):
        return "TRAN"
    if any(t in k for t in AC_TOKENS):
        return "AC"
    if any(t in k for t in DC_TOKENS):
        return "DC"
    return None


def _value_comment(val) -> str:
    if isinstance(val, dict):
        fields = []
        for key in ("value", "target", "min", "max", "unit"):
            if val.get(key) is not None:
                fields.append(f"{key}={val[key]}")
        return "  $ " + " ".join(fields) if fields else ""
    if isinstance(val, (int, float, str)):
        return f"  $ target={val}"
    return ""


def _emit_line(key: str, kind: str, val) -> str:
    comment = _value_comment(val)
    if kind == "DC":
        return f".meas DC {key} FIND V(vout) AT=last{comment}"
    if kind == "AC":
        if "pm" in key.lower() or "phase" in key.lower():
            return f".meas AC {key} FIND VP(vout) WHEN VDB(vout)=0{comment}"
        return f".meas AC {key} FIND VDB(vout) AT=1k{comment}"
    # TRAN
    return (f".meas TRAN {key} TRIG V(in) VAL=vmid RISE=1 "
            f"TARG V(out) VAL=vmid FALL=1{comment}")


def _flatten_spec(spec: dict) -> Tuple[Dict[str, object], List[dict], List[dict]]:
    """Return candidates, canonical-list rows, and malformed row records.

    Map-shaped inputs retain their legacy behavior.  List-shaped inputs are
    consumed row-for-row so a declared but unsupported measurement cannot
    disappear while another row makes the overall generator look successful.
    """
    candidates: Dict[str, object] = {}
    declared: List[dict] = []
    malformed: List[dict] = []
    for key, value in spec.items():
        if key not in ("specs", "targets"):
            candidates[key] = value
    for container_name in ("specs", "targets"):
        container = spec.get(container_name)
        if isinstance(container, dict):
            for key, value in container.items():
                if key not in ("specs", "targets"):
                    candidates[key] = value
        elif isinstance(container, list):
            seen = set()
            for index, row in enumerate(container):
                if not isinstance(row, dict):
                    malformed.append({"container": container_name,
                                      "index": index,
                                      "reason": "row_not_object"})
                    continue
                name = row.get("name")
                if not isinstance(name, str) or not name.strip():
                    malformed.append({"container": container_name,
                                      "index": index,
                                      "reason": "name_missing"})
                    continue
                name = name.strip()
                if name in seen:
                    malformed.append({"container": container_name,
                                      "index": index, "name": name,
                                      "reason": "duplicate_name"})
                    continue
                seen.add(name)
                declared.append(row)
                candidates[name] = row
    return candidates, declared, malformed


def _unsupported_rows(rows: List[dict]) -> List[dict]:
    unsupported = []
    window_keys = ("window", "measurement_window", "from", "to",
                   "from_s", "to_s")
    for row in rows:
        name = str(row["name"]).strip()
        windows = {key: row[key] for key in window_keys if key in row}
        if "measurement" in row and not windows:
            try:
                measurement_commands(name, row["measurement"])
            except ValueError as exc:
                unsupported.append({"name": name, "reason": "invalid_measurement_binding", "detail": str(exc)})
            continue
        if windows:
            unsupported.append({"name": name,
                                "reason": "unsupported_measurement_window",
                                "window": windows})
        else:
            kind = _classify(name)
            if kind == "DC":
                unsupported.append({
                    "name": name,
                    "reason": "dc_sweep_binding_not_declared",
                    "unit": row.get("unit")})
            elif kind == "AC":
                unsupported.append({
                    "name": name,
                    "reason": "ac_frequency_binding_not_declared",
                    "unit": row.get("unit")})
            elif kind is None:
                unsupported.append({
                    "name": name,
                    "reason": "unsupported_measurement_template",
                    "unit": row.get("unit")})
    return unsupported


def generate(spec: dict) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Return (deck_lines, [(key, kind)...]) for the measurable keys."""
    lines: List[str] = ["* auto-generated .meas deck from spec.json"]
    emitted: List[Tuple[str, str]] = []
    candidates, declared, _ = _flatten_spec(spec)
    unsupported_names = {row["name"] for row in _unsupported_rows(declared)}
    for key in sorted(candidates):
        if key in ("specs", "targets"):
            continue
        if key in unsupported_names:
            continue
        if isinstance(candidates[key], dict) and "measurement" in candidates[key]:
            commands, kind = measurement_commands(key, candidates[key]["measurement"])
            lines.extend(commands)
            emitted.append((key, kind))
            continue
        kind = _classify(key)
        if kind is None:
            continue
        lines.append(_emit_line(key, kind, candidates[key]))
        emitted.append((key, kind))
    return lines, emitted


def run(spec_path: Path) -> Tuple[int, dict, str]:
    if not spec_path.is_file():
        return 1, {"pass": False, "reason": "spec_missing",
                   "spec": str(spec_path)}, ""
    try:
        raw = spec_path.read_text(encoding="utf-8", errors="replace")
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        return 2, {"pass": False, "reason": f"json_error: {exc}",
                   "spec": str(spec_path)}, ""
    except OSError as exc:
        return 2, {"pass": False, "reason": f"io_error: {exc}",
                   "spec": str(spec_path)}, ""
    if not isinstance(spec, dict):
        return 2, {"pass": False, "reason": "spec_not_object",
                   "spec": str(spec_path)}, ""

    _, declared, malformed = _flatten_spec(spec)
    if malformed:
        return 2, {"pass": False, "reason": "malformed_measurement_rows",
                   "spec": str(spec_path), "rows": malformed}, ""
    unsupported = _unsupported_rows(declared)
    deck_lines, emitted = generate(spec)
    if unsupported:
        return 1, {"pass": False, "reason": "unsupported_measurements",
                   "spec": str(spec_path), "meas_lines": 0,
                   "unsupported": unsupported}, ""
    if not emitted:
        return 1, {"pass": False, "reason": "no_measurable_keys",
                   "spec": str(spec_path), "meas_lines": 0}, ""

    deck = "\n".join(deck_lines) + "\n"
    summary = {
        "pass": True,
        "spec": str(spec_path),
        "meas_lines": len(emitted),
        "emitted": [{"key": k, "kind": kind} for k, kind in emitted],
        "schema": "canonical_list" if declared else "map",
    }
    return 0, summary, deck


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path, help="path to <block>/spec.json")
    ap.add_argument("--out", default=None, help="write .meas deck to this file")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    code, summary, deck = run(args.spec)

    report = {"program": GATE, "version": "1.1.0", "summary": summary}
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False))

    if code == 0:
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(deck)
        elif not args.json:
            sys.stdout.write(deck)
    else:
        if not args.json:
            print(f"[FAIL] {GATE}: {summary.get('reason')}", file=sys.stderr)

    return code


if __name__ == "__main__":
    sys.exit(main())
