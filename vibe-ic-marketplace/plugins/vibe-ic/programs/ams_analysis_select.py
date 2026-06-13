#!/usr/bin/env python3
"""ams_analysis_select.py — deterministic spec -> SPICE-analysis selector.

Rule (from skill `ams-sim`, "Analysis matrix" + workflow step 1
"Pick the analysis subset needed for the spec"):

    The spec -> required-analysis mapping is a FROZEN table lookup, not
    agent judgment.  The same spec list must always yield the same
    analysis subset, so two agents can never (silently) pick two
    different / incomplete analysis sets for one block.

The frozen table (verbatim from the skill, no invented thresholds):

    | spec metric class                       | required analysis |
    |-----------------------------------------|-------------------|
    | gain / bandwidth / phase-margin / GBW   | .ac               |
    | input-referred noise / SNR / SNDR       | .noise            |
    | settling / slew / large-signal timing   | .tran             |
    | mismatch / process / yield (Monte Carlo)| .mc               |
    | RF / switched-cap periodic steady-state | .pss/.pac/.pnoise |
    | supply / input / parameter sweep        | .dc               |
    | bias / operating-point validation       | .op               |

`.op` (DC operating point, bias validation) is ALWAYS required — every
analog block needs a verified bias point before any other analysis is
trustworthy (the skill lists it first as "bias validation"), so it is
emitted unconditionally whenever >=1 measurable spec key is present.

This is a SELECTOR / GENERATOR, complementary to
`analog_meas_from_spec_gen.py` (which emits the `.meas` lines): this
program answers "which .ANALYSIS cards must the deck contain", including
the `.noise`, `.mc`, `.pss` and `.dc` cards that the .meas generator
does not decide.

Spec key classification (case-insensitive substring; longest/most
specific class wins so a key only ever maps to ONE analysis class):

    .noise : 'noise', 'snr', 'sndr', 'enob', 'nsd'
    .pss   : 'pss', 'pac', 'pnoise', 'switched_cap', 'switched-cap',
             'sc_', 'pll_pn', 'phase_noise', 'rf_'
    .ac    : 'gain', 'bandwidth', '_bw', 'ugbw', 'gbw', 'pm',
             'phase_margin', 'gm', 'psrr', 'cmrr', '_db', 'gain_db',
             'f3db', 'unity_gain'
    .tran  : 'slew', 'settling', 'tpd', '_tr', '_tf', 'rise', 'fall',
             'jitter', 'period', 'overshoot', 'glitch', 'startup',
             'tphl', 'tplh', 'delay', 'step_response'
    .dc    : 'sweep', 'line_reg', 'load_reg', 'vout_vs', 'transfer',
             'icmr', 'output_swing', 'dropout', 'dc_sweep'
    .op    : 'vout_dc', 'vref', 'vbias', 'iq', 'idd', 'isupply',
             'bias', 'op_point', 'quiescent', 'gm_id'

A Monte-Carlo (`.mc`) requirement is ADDITIVE — it is selected whenever
ANY spec key (or the spec object) declares a mismatch / process / yield
/ sigma concern ('mismatch', 'sigma', 'yield', 'monte', '3sigma',
'process_corner', 'offset' with a 'mc'/'sigma' qualifier).  `.mc` wraps
the other analyses; it does not replace them.

HONEST FAIL / SKIP (NO vacuous PASS):
  * missing spec.json                       -> exit 1 (spec_missing)
  * spec.json that is not valid JSON        -> exit 2 (json_error)
  * spec.json that is not a JSON object      -> exit 2 (spec_not_object)
  * spec.json with NO recognizable spec key -> exit 1 (no_measurable_keys);
    a PASS here would be vacuous (we'd emit only the always-on `.op`
    with nothing to justify it)
  * project dir with no analog/<block>/spec.json -> exit 0 + INFO skip
    (nothing to select for)

Usage:
    python3 ams_analysis_select.py <spec.json>
    python3 ams_analysis_select.py <project_dir>          # scans analog/*/spec.json
    python3 ams_analysis_select.py <spec.json> --json report.json

Exit codes:
    0 = PASS (>=1 analysis selected from real spec keys) or INFO skip
    1 = FAIL (missing spec / no recognizable keys)
    2 = IO / parse error

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

GATE = "ams_analysis_select"
VERSION = "1.0.0"

# Ordered most-specific-first; first matching class wins for a key.
# Each entry: (analysis_card, (token, token, ...))
_CLASS_TABLE: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    # .pss is checked BEFORE .noise so 'pnoise'/'pac'/'pss' route to the
    # periodic-steady-state card rather than matching the 'noise' substring.
    (".pss", ("pss", "pac", "pnoise", "switched_cap", "switched-cap",
              "sc_", "pll_pn", "phase_noise", "rf_")),
    (".noise", ("noise", "snr", "sndr", "enob", "nsd")),
    (".ac", ("gain", "bandwidth", "_bw", "ugbw", "gbw", "phase_margin",
             "_pm", "pm_", "psrr", "cmrr", "_db", "gain_db", "f3db",
             "unity_gain", "gm_db")),
    (".tran", ("slew", "settling", "tpd", "_tr", "_tf", "rise", "fall",
               "jitter", "period", "overshoot", "glitch", "startup",
               "tphl", "tplh", "delay", "step_response")),
    (".dc", ("sweep", "line_reg", "load_reg", "vout_vs", "transfer",
             "icmr", "output_swing", "dropout", "dc_sweep")),
    (".op", ("vout_dc", "vout", "vop", "vref", "vbias", "iq", "idd",
             "isupply", "bias", "op_point", "quiescent", "gm_id")),
)

# Monte-Carlo is additive — selected when any key/object declares a
# statistical concern.
_MC_TOKENS = ("mismatch", "sigma", "yield", "monte", "3sigma", "6sigma",
              "process_corner", "pelgrom")

# Canonical emit order for a stable, comparable analysis set.
_ORDER = (".op", ".dc", ".ac", ".tran", ".noise", ".pss", ".mc")


def _classify(key: str) -> Optional[str]:
    """Map a single spec key to its analysis card, or None."""
    k = key.lower()
    for card, tokens in _CLASS_TABLE:
        if any(t in k for t in tokens):
            return card
    return None


def _flatten_spec(spec: dict) -> Dict[str, object]:
    """Collect measurable keys from the top level and from nested
    'specs' / 'targets' containers.

    Two canonical analog spec.json shapes are supported:
      * map  : {"gain_db": 60, "vout_dc": 0.9, ...}
      * list : {"specs": [{"name": "line_reg", "value": 0.14, ...}, ...]}
               (the shape emitted by analog-spec-extract; each entry's
               'name' is the metric key)
    """
    out: Dict[str, object] = {}
    # top-level map keys (skip the reserved container names)
    for k, v in spec.items():
        if k in ("specs", "targets"):
            continue
        out[k] = v
    for container in (spec.get("specs"), spec.get("targets")):
        if isinstance(container, dict):
            for k, v in container.items():
                if k in ("specs", "targets"):
                    continue
                out[k] = v
        elif isinstance(container, list):
            for entry in container:
                if isinstance(entry, dict):
                    name = entry.get("name")
                    if isinstance(name, str) and name:
                        out[name] = entry
    return out


def _mc_requested(spec: dict, keys: Dict[str, object]) -> bool:
    """True if a Monte-Carlo run is required by spec content."""
    # 1) explicit mc directive object
    mc = spec.get("monte_carlo") or spec.get("mc")
    if isinstance(mc, dict) and (mc.get("n") or mc.get("runs") or
                                 mc.get("enabled")):
        return True
    if isinstance(mc, (int, float)) and mc:
        return True
    # 2) any key name carries a statistical concern
    blob = " ".join(str(k).lower() for k in keys)
    if any(t in blob for t in _MC_TOKENS):
        return True
    # 3) a key VALUE dict that declares sigma/mismatch metadata
    for v in keys.values():
        if isinstance(v, dict):
            vk = " ".join(str(x).lower() for x in v.keys())
            if any(t in vk for t in _MC_TOKENS):
                return True
    return False


def select(spec: dict) -> Tuple[List[str], List[Dict[str, str]]]:
    """Return (sorted_analysis_set, [{key, analysis}...]) for a spec."""
    keys = _flatten_spec(spec)
    mapped: List[Dict[str, str]] = []
    chosen = set()
    for key in sorted(keys):
        card = _classify(key)
        if card is None:
            continue
        mapped.append({"key": key, "analysis": card})
        chosen.add(card)
    if not mapped:
        return [], []
    # .op is always required once we have >=1 measurable spec.
    chosen.add(".op")
    if _mc_requested(spec, keys):
        chosen.add(".mc")
    ordered = [c for c in _ORDER if c in chosen]
    return ordered, mapped


def _load_spec(path: Path) -> Tuple[Optional[dict], int, str]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, 2, f"json_error: {exc}"
    except OSError as exc:
        return None, 2, f"io_error: {exc}"
    if not isinstance(spec, dict):
        return None, 2, "spec_not_object"
    return spec, 0, ""


def run_one(spec_path: Path) -> Tuple[int, dict]:
    if not spec_path.is_file():
        return 1, {"pass": False, "reason": "spec_missing",
                   "spec": str(spec_path)}
    spec, code, reason = _load_spec(spec_path)
    if spec is None:
        return code, {"pass": False, "reason": reason, "spec": str(spec_path)}
    analyses, mapped = select(spec)
    if not analyses:
        return 1, {"pass": False, "reason": "no_measurable_keys",
                   "spec": str(spec_path), "analyses": []}
    return 0, {"pass": True, "spec": str(spec_path),
               "analyses": analyses, "mapping": mapped}


def _find_block_specs(project_dir: Path) -> List[Path]:
    out: List[Path] = []
    adir = project_dir / "analog"
    if adir.is_dir():
        out.extend(sorted(adir.glob("*/spec.json")))
    return out


def run(target: Path) -> Tuple[int, dict]:
    # Single spec.json file
    if target.is_file():
        code, summary = run_one(target)
        return code, {"mode": "file", "blocks": [summary]}
    # Project dir: scan analog/*/spec.json
    if target.is_dir():
        specs = _find_block_specs(target)
        if not specs:
            return 0, {"mode": "project", "reason": "no_analog_specs",
                       "blocks": [], "info": "skip"}
        blocks = []
        worst = 0
        for sp in specs:
            code, summary = run_one(sp)
            summary["exit"] = code
            blocks.append(summary)
            worst = max(worst, code)
        return worst, {"mode": "project", "blocks": blocks}
    # A non-existent path that LOOKS like a spec file -> honest spec_missing
    # (exit 1), not a generic target-not-found error.
    if target.suffix == ".json":
        code, summary = run_one(target)
        return code, {"mode": "file", "blocks": [summary]}
    return 2, {"mode": "error", "reason": "target_not_found",
               "target": str(target)}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path,
                    help="path to <block>/spec.json OR a project dir")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    code, summary = run(args.target)
    report = {"program": GATE, "version": VERSION, "exit": code,
              "summary": summary}

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))

    return code


if __name__ == "__main__":
    sys.exit(main())
