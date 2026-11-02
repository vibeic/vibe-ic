#!/usr/bin/env python3
"""lvs_tapeout_signoff_check.py — the TAPEOUT-tier LVS gate.

The tapeout-signoff survey found the load-bearing LVS gap: the phase3 runner's
`_run_extraction_lvs` converts a netgen `failed pin matching` POWER_PIN_ONLY
mismatch into an `LVS_MATCH_POWER_AWARE` PASS. That is a REASONED WAIVER (the yosys
gate netlist has no VPWR/VGND ports while the extracted layout carries per-cell power
pins — a universal power-unaware-netlist SETUP artifact), and it is fine for TRIAGE.
But a foundry tape-out is DEFINED by a genuine LVS MATCH — "Circuits match uniquely,
zero mismatch." A POWER_PIN_ONLY waiver is NOT that.

This gate is the TAPEOUT tier: it refuses to credit a power-pin-only waiver as a
genuine sign-off match, so a "tapeout-ready" claim stays honest until the design
reaches a REAL match (via a power-aware gate netlist — the root fix, tracked as the
immediate follow-up).

Tapeout verdicts (from `lvs_verdict_tokens.classify` + `.mismatch_class`):
  GENUINE_MATCH        — netgen "Circuits match uniquely" + Final result → PASS (rc 0)
  GATE_LEVEL_BLACKBOX  — a unique match, but netgen reports one or more cells as
                         "a placeholder, treated as a black box": the layout side
                         carried EMPTY cell views, so only cell-to-cell wiring was
                         compared and no transistor inside those cells was. NOT a
                         tapeout pass — re-run LVS on a full-GDS device extraction.
                         rc 1. (Primitive-device classes that netgen reports as
                         "Circuit 1 cell X and Circuit 2 cell X are black boxes" in a
                         full extraction are NOT this case and still pass.)
  WAIVED_PENDING_PWR   — MISMATCH whose evidence is EXCLUSIVELY power/tie nets
                         (POWER_PIN_ONLY). NOT a tapeout pass — a documented waiver
                         that requires a power-aware gate netlist to reach a genuine
                         match. rc 1 (does NOT release the tapeout tier).
  SIGNAL_NET_MISMATCH  — real signal-net evidence (e.g. aes 517 `(no pin, node is …)`
                         rows) → FAIL, an open connectivity defect. rc 1.
  INCOMPLETE / absent  — the run did not reach a top-level compare, or no report →
                         FAIL (missing evidence, never a pass). rc 1 (rc 2 if the
                         path itself is absent).

§4.05 (the whole point): POWER_PIN_ONLY is NO LONGER a pass at the tapeout tier, and
a SIGNAL_NET_MISMATCH is NEVER waved through. The triage-tier POWER_PIN_ONLY waiver
in _run_extraction_lvs is untouched — this gate is a STRICTER, tapeout-only overlay.

chip-AGNOSTIC: reads only the generic netgen transcript; no design/PDK literal.

Usage:
    python3 lvs_tapeout_signoff_check.py <lvs_report_or_dir> [--json OUT]
    main(argv) -> int : 0 PASS / 1 FAIL(incl waived-pending) / 2 IO-or-arg error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

_PROGRAMS = Path(__file__).resolve().parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import lvs_verdict_tokens as _lvt  # noqa: E402


def _find_report(target: Path) -> Optional[Path]:
    if target.is_file():
        return target
    if not target.is_dir():
        return None
    # v1.3.94 — PREFER the canonical sign-off report. A bare recursive glob
    # sorts an in-tree backup ('_known_good_snapshot_*/reports_phase3/lvs.rpt')
    # BEFORE the live 'reports/phase3/lvs.rpt' (underscore < 'r'), so hits[0]
    # picked the STALE snapshot's netgen mismatch and FALSE-FAILed a clean
    # sign-off. Take the canonical path first, then glob with backup/snapshot
    # dirs excluded (same #525/v1.3.94 doctrine as eda_report_audit).
    canonical = target / "reports" / "phase3" / "lvs.rpt"
    if canonical.is_file():
        return canonical
    try:
        from eda_report_audit import _is_backup_path as _isbak
    except Exception:
        def _isbak(p, r):  # fail-open: no exclusion if the helper is unavailable
            return False
    for pat in ("*lvs*.rpt", "*lvs*.out", "*netgen*.rpt", "*.lvs.report",
                "comp.out", "*.rpt"):
        hits = sorted(p for p in target.rglob(pat) if not _isbak(p, target))
        if hits:
            return hits[0]
    return None


#: netgen's own wording when a cell has no contents on one side and is compared
#: only by its pin list. Distinct from the full-extraction primitive line
#: "Circuit 1 cell X and Circuit 2 cell X are black boxes", which names device
#: models (e.g. a PDK MOSFET subcircuit), not an emptied standard/IO cell.
_PLACEHOLDER_RE = re.compile(r"cell\s+(\S+)\s+is a placeholder,\s*treated as a black box")


def placeholder_cells(blob: str) -> List[str]:
    """Cells netgen compared as empty placeholders (sorted, de-duplicated)."""
    return sorted(set(_PLACEHOLDER_RE.findall(blob)))


def evaluate(blob: str) -> Dict[str, object]:
    """Pure evaluator over a netgen LVS transcript+report blob → tapeout verdict."""
    base = _lvt.classify(blob)          # MATCH / MISMATCH / INCOMPLETE
    if base == "MATCH":
        blackboxed = placeholder_cells(blob)
        if blackboxed:
            return {
                "tapeout_verdict": "GATE_LEVEL_BLACKBOX", "passed": False,
                "base_verdict": base,
                "detail": f"netgen matched only cell-to-cell wiring: {len(blackboxed)} "
                          "cell(s) were empty placeholders treated as black boxes, so "
                          "no transistor inside them was compared. Re-run LVS on a "
                          "full-GDS device extraction before release.",
                "placeholder_cells": blackboxed,
            }
        return {"tapeout_verdict": "GENUINE_MATCH", "passed": True,
                "base_verdict": base,
                "detail": "netgen reports a unique match with a Final result line"}
    if base == "INCOMPLETE":
        return {"tapeout_verdict": "INCOMPLETE", "passed": False,
                "base_verdict": base,
                "detail": "no top-level compare reached — missing-evidence FAIL, "
                          "never a tapeout pass"}
    # base == MISMATCH → sub-classify.
    sub = _lvt.mismatch_class(blob)     # POWER_PIN_ONLY / SIGNAL_NET_MISMATCH
    if sub == "POWER_PIN_ONLY":
        return {
            "tapeout_verdict": "WAIVED_PENDING_POWER_AWARE", "passed": False,
            "base_verdict": base, "mismatch_class": sub,
            "detail": "power-pin-only mismatch — a reasoned TRIAGE waiver, but NOT a "
                      "tapeout MATCH. Reach a genuine match with a power-aware gate "
                      "netlist (VPWR/VGND top ports + PG connectivity) before release.",
            "evidence": _lvt.pin_mismatch_evidence(blob),
        }
    return {
        "tapeout_verdict": "SIGNAL_NET_MISMATCH", "passed": False,
        "base_verdict": base, "mismatch_class": sub,
        "detail": "real signal-net mismatch — an open connectivity defect that MUST "
                  "be resolved (never waved through).",
        "evidence": _lvt.pin_mismatch_evidence(blob),
    }


def native_project_verdict(project: Path):
    """Consume the existing Step-31 native record against the current final GDS."""
    path = project / "reports/phase3/lvs_verdict.json"
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"LVS_VERDICT_UNREADABLE: {path}: {exc}") from exc
    if not isinstance(record, dict):
        raise ValueError(f"LVS_VERDICT_NOT_AN_OBJECT: {path}")
    if record.get("schema") != "vibeic.native_gds_lvs/1":
        return None
    from _prestream_native import signoff_inputs
    import klayout_pdk_lvs as native
    selected = signoff_inputs(project, "gds")
    return native.read_current_verdict(project, path, selected["gds"])


def check(target: Path) -> Dict[str, object]:
    if target.is_dir():
        try:
            native = native_project_verdict(target)
        except (OSError, ValueError, KeyError) as exc:
            return {"tapeout_verdict": "INCOMPLETE", "passed": False, "error": str(exc)}
        if native is not None:
            return {"tapeout_verdict": "GENUINE_MATCH" if native["status"] == "PASS" else "SIGNAL_NET_MISMATCH",
                    "passed": native["status"] == "PASS", "base_verdict": native["status"],
                    "detail": "official PDK final-GDS LVS machine circuit/pin comparison",
                    "native": native}
    rpt = _find_report(target)
    if rpt is None:
        return {"tapeout_verdict": "IO_ERROR", "passed": False,
                "error": f"no LVS report found at {target}"}
    try:
        blob = rpt.read_text(errors="replace")
    except OSError as e:
        return {"tapeout_verdict": "IO_ERROR", "passed": False,
                "error": f"cannot read {rpt}: {e}"}
    res = evaluate(blob)
    res["report"] = str(rpt)
    return res


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Tapeout-tier LVS gate: POWER_PIN_ONLY is NOT a genuine match.")
    ap.add_argument("target", help="LVS report file or directory to search")
    ap.add_argument("--json", dest="json_out", default=None)
    ns = ap.parse_args(argv)
    res = check(Path(ns.target))
    out = json.dumps(res, indent=2)
    if ns.json_out:
        Path(ns.json_out).write_text(out)
    print(out)
    if res["tapeout_verdict"] == "IO_ERROR":
        return 2
    return 0 if res.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
