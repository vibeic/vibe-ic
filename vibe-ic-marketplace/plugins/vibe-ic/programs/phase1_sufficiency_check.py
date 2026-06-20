#!/usr/bin/env python3
"""phase1_sufficiency_check.py — the SUFFICIENCY GATE of the Phase-1 dialogue
dual-track convergence (owner directive 2026-06-20).

After the program track + IC-Expert AI track converge on an L1-L24 JSON (see
programs/phase1_json_converge.py), the IC Expert Agent must confirm the JSON is
actually SUFFICIENT TO DESIGN THE IC before handing off to Phase 2. If a
required design fact is missing, the agent does NOT guess — it asks the user a
PLAIN-LANGUAGE question (its external user-facing register) and re-ingests.

This program is the DETERMINISTIC half of that gate: it inspects the converged
layer JSON and reports, structurally, which minimum design facts are present
and which are missing — and for each missing REQUIRED fact it emits a ready-to-
ask plain-language question (no silicon jargon), so the user is never shown
`CRC`/`opcode`/`reset`/`V_DD`.

Severity model (conservative — avoid false "insufficient" loop-backs):
  REQUIRED   : block (a design genuinely cannot be authored without it)
                 - a module / chip name
                 - at least one external port (signal)
  CONDITIONAL: required ONLY when the design is sequential (a clock port, OR
               an FSM/control-logic layer, OR stated timing) implies it needs
                 - a clock signal
                 - a reset signal
  ADVISORY   : warn only (helps but not blocking)
                 - parameters, a register map / protocol when indicated

chip-AGNOSTIC: structural inspection of the layer JSON only; no chip-specific
strings; the plain-language questions are generic product language.

Usage:
    phase1_sufficiency_check.py <L*.json dir | merged.json> [--json OUT] [--strict]
    # exit 0 unless --strict and a REQUIRED fact is missing (then exit 1)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_CLOCK_RE = re.compile(r"\b(clk|clock|sclk|hclk|pclk|aclk)\b", re.I)
_RESET_RE = re.compile(r"\b(rst|reset|resetn|rst_n|nreset|areset|sreset)\b",
                       re.I)
_PORTISH_KEYS = ("name", "signal", "port", "pin")


def _load_layers(path: Path) -> Dict[str, Any]:
    """Return {layer_code: parsed_json}. Accepts a dir of L*.json or a single
    merged/structured JSON file (then keyed by its top-level L<N> keys)."""
    out: Dict[str, Any] = {}
    if path.is_dir():
        for f in sorted(path.glob("L*.json")):
            stem = f.stem
            code = stem
            for i in range(len(stem), 0, -1):
                head = stem[:i]
                if head and head[0] == "L" and head[1:].rstrip("R").isdigit():
                    code = head
                    break
            try:
                out[code] = json.loads(f.read_text())
            except Exception:  # noqa: BLE001
                continue
    elif path.is_file():
        try:
            data = json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            return out
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(k, str) and k and k[0] == "L" \
                        and k[1:].rstrip("R").isdigit():
                    out[k] = v
            if not out:                 # a single L*.json's bare body
                out["L1"] = data
    return out


def _iter_strings(node: Any) -> List[str]:
    acc: List[str] = []
    if isinstance(node, dict):
        for v in node.values():
            acc.extend(_iter_strings(v))
    elif isinstance(node, list):
        for v in node:
            acc.extend(_iter_strings(v))
    elif isinstance(node, str):
        acc.append(node)
    return acc


def _collect_port_names(layers: Dict[str, Any]) -> List[str]:
    """Pull port/signal names from the port-bearing layers (L1 pinout, L8R)."""
    names: List[str] = []

    def _scan(node: Any) -> None:
        if isinstance(node, dict):
            nm = None
            for k in _PORTISH_KEYS:
                for kk, vv in node.items():
                    if str(kk).lower() == k and isinstance(vv, (str, int)):
                        nm = str(vv)
                        break
                if nm:
                    break
            if nm:
                names.append(nm)
            for v in node.values():
                _scan(v)
        elif isinstance(node, list):
            for v in node:
                _scan(v)

    for code in ("L1", "L8R", "L5", "L17"):
        if code in layers:
            _scan(layers[code])
    return names


def _name_present(layers: Dict[str, Any]) -> bool:
    for code in ("L1", "L9"):
        blob = layers.get(code)
        if not isinstance(blob, dict):
            continue
        for key in ("chip_name", "ic_name", "module_name", "top_module",
                    "name", "top"):
            v = blob.get(key)
            if isinstance(v, str) and v.strip() and \
                    v.strip().upper() not in ("UNNAMED_CHIP", "__UNKNOWN__"):
                return True
    return False


def _is_sequential(layers: Dict[str, Any], port_names: List[str]) -> bool:
    """Sequential iff a clock OR reset port is actually present.

    NOTE: we deliberately do NOT infer 'sequential' from the mere existence
    of an L6/L8/L12 layer body — every project emits a 24-layer SKELETON whose
    extraction-hint strings ("Look for scan / DFT …") are present even when the
    layer extracted nothing, so a string-presence test fired on EVERY design
    and over-demanded a clock/reset on purely combinational parts (a known
    false-'insufficient' class). The clock/reset gap is ADVISORY anyway (see
    check()); the prose-level "this runs on each clock" judgment is the
    IC-Expert AI track's job, not this structural gate's."""
    return (any(_CLOCK_RE.search(n) for n in port_names)
            or any(_RESET_RE.search(n) for n in port_names))


# plain-language (no-jargon) question per missing fact — the IC Expert Agent's
# external user-facing register reads these out verbatim.
_QUESTIONS = {
    "name": "What should we call this chip / part?",
    "ports": "What signals does this part use to connect to the outside "
             "world — what information goes in, and what comes out?",
    "clock": "Does this part work in steps driven by a regular timing beat "
             "(does it need a clock)? If so, what should it be called?",
    "reset": "Is there a way to put this part back to a known starting state "
             "(a reset)? Should it start fresh when the signal is on, or off?",
}


def check(path: Path) -> Dict[str, Any]:
    layers = _load_layers(path)
    port_names = _collect_port_names(layers)
    has_name = _name_present(layers)
    has_ports = len(port_names) >= 1
    sequential = _is_sequential(layers, port_names)
    has_clock = any(_CLOCK_RE.search(n) for n in port_names)
    has_reset = any(_RESET_RE.search(n) for n in port_names)

    required: List[Dict[str, Any]] = []
    conditional: List[Dict[str, Any]] = []

    def _item(key: str, present: bool) -> Dict[str, Any]:
        return {"fact": key, "present": present,
                "question": None if present else _QUESTIONS.get(key)}

    required.append(_item("name", has_name))
    required.append(_item("ports", has_ports))
    # clock/reset are ADVISORY, never blocking. A sequential design that omits
    # a reset is legal, and 'sequential' itself is only inferred from a real
    # clock/reset port — so this can surface a genuine gap (a reset port but no
    # clock) without the over-demand that flips a combinational part to
    # 'insufficient'. The IC-Expert Agent decides whether an advisory is worth
    # a user question; the gate never forces it.
    if sequential:
        conditional.append(_item("clock", has_clock))
        conditional.append(_item("reset", has_reset))

    missing_required = [i for i in required if not i["present"]]
    missing_conditional = [i for i in conditional if not i["present"]]
    # VERDICT blocks on REQUIRED facts only (name + at least one port). The
    # advisory gaps are reported for the agent's judgment, not auto-blocked.
    sufficient = not missing_required
    questions = [i["question"] for i in missing_required if i["question"]]
    advisories = [i["question"] for i in missing_conditional if i["question"]]
    return {
        "verdict": "sufficient" if sufficient else "insufficient",
        "sequential": sequential,
        "layers_seen": sorted(layers.keys()),
        "port_count": len(port_names),
        "required": required,
        "conditional": conditional,
        "missing_required": [i["fact"] for i in missing_required],
        "missing_conditional": [i["fact"] for i in missing_conditional],
        "questions_for_user": questions,
        "advisories_for_agent": advisories,
    }


def _fmt(rep: Dict[str, Any]) -> str:
    lines = [f"sufficiency verdict: {rep['verdict']}",
             f"  layers={','.join(rep['layers_seen']) or '(none)'} "
             f"ports={rep['port_count']} sequential={rep['sequential']}"]
    if rep["missing_required"]:
        lines.append(f"  MISSING required: {rep['missing_required']}")
    if rep["missing_conditional"]:
        lines.append(f"  MISSING conditional: {rep['missing_conditional']}")
    for q in rep["questions_for_user"]:
        lines.append(f"  ask user > {q}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("layers", type=Path,
                    help="converged L*.json dir or merged.json")
    ap.add_argument("--json", type=Path, default=None,
                    help="write the full sufficiency report here")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when a REQUIRED fact is missing (block)")
    args = ap.parse_args(argv)
    if not (args.layers.is_dir() or args.layers.is_file()):
        print(f"ERROR: not found: {args.layers}", file=sys.stderr)
        return 2
    rep = check(args.layers)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    print(_fmt(rep))
    if args.strict and rep["missing_required"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
