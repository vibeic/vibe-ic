#!/usr/bin/env python3
"""eco_trigger_decision.py — the SHARED ECO auto-trigger decision.

TAPEOUT-SIGNOFF gap (ibex-surfaced):
  The ECO auto-trigger used to read ONLY the single-corner (typical / tt)
  post-route STA. A large design can MEET timing at the tt corner yet carry a
  huge setup violation at the SLOW (ss) process corner because slews explode
  there (ibex: tt +6.02 ns MET, ss −88 ns VIOLATED). Gating the trigger on tt
  alone writes ``no_eco_needed.flag`` and the multi-corner-aware ECO
  (``_build_eco_repair_tcl`` with corner_libs, ss-first) NEVER fires for exactly
  the designs that need it — the ECO is emitted-but-dead.

This module is the ONE decision that BOTH ``no_eco_needed.flag`` sites consult:
  * ``phase3_one_shot_runner.step_canonicalize_artefacts`` (the primary site,
    which also FIRES the ECO), and
  * ``eco_status_gen.py`` (a derived-artefact generator that runs AFTER
    canonicalize and would otherwise re-write ``no_eco_needed.flag`` from the
    single-corner STA, clobbering the primary decision).
Sharing the decision means the two sites cannot drift.

§4.05 HONEST fallback: when multi-corner OCV sign-off is UNAVAILABLE (a
single-corner PDK exposing no distinct ss/ff process liberties), the decision
degrades to today's single-corner (tt) behavior — no regression and no
fabricated multi-corner claim. And it NEVER declares no-ECO-needed when a real
multi-corner violation exists.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union


def _load_stance(stance: Union["Path", str, dict, None]) -> Optional[dict]:
    """Return the parsed ``mcorner_ocv_stance.json`` dict, or None.

    Accepts an already-parsed dict (tests), a path/str to the JSON file, or
    None. Any read/parse failure degrades to None (honest single-corner
    fallback — never a crash, never a false multi-corner claim)."""
    if isinstance(stance, dict):
        return stance
    if stance is None:
        return None
    try:
        p = Path(stance)
    except TypeError:
        return None
    if not p.is_file():
        return None
    try:
        obj = json.loads(p.read_text(errors="ignore"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def decide(stance: Union["Path", str, dict, None],
           single_corner_clean: bool) -> Dict[str, Any]:
    """Return the ECO auto-trigger decision.

    Args:
      stance: path to (or already-parsed dict of) ``mcorner_ocv_stance.json``.
      single_corner_clean: True when the single-corner (tt) post-route STA has
        NO setup/hold violation (TNS=0 / no ``VIOLATED``). This is the ONLY
        signal the pre-fix trigger used.

    Returns a dict:
      basis:            "multi_corner_ocv" | "single_corner_tt"
      mc_ocv_available: multi-corner OCV genuinely ran (>=2 distinct process
                        corners) AND produced a report
      eco_needed:       True  ⇒ an ECO must FIRE (do NOT write no_eco_needed.flag)
                        False ⇒ no ECO needed (no_eco_needed.flag is honest)
      violated_corners: corner(s) with a real violation (multi-corner basis only)
      setup_worst_slack_ns / hold_worst_slack_ns: the REAL per-corner worst slack

    Decision logic:
      * multi-corner OCV authoritative (multi_process_corner True + a report):
        eco_needed = a real violation exists at ANY signed-off corner.
      * else (single-corner PDK / OCV unavailable): eco_needed = NOT clean at tt
        — today's behavior, no regression.
    """
    out: Dict[str, Any] = {
        "basis": "single_corner_tt",
        "mc_ocv_available": False,
        "eco_needed": not single_corner_clean,
        "violated_corners": [],
        "setup_worst_slack_ns": None,
        "hold_worst_slack_ns": None,
    }
    s = _load_stance(stance)
    if not s:
        return out
    # Authoritative ONLY when the multi-corner OCV sign-off genuinely ran across
    # >=2 distinct process corners AND produced a report. A single-corner stance
    # (multi_process_corner False, report None) is NOT authoritative — the honest
    # tt fallback stands (§4.05: no fabricated multi-corner claim).
    available = bool(s.get("multi_process_corner")) and bool(s.get("report"))
    if not available:
        return out
    viol = [str(c) for c in (s.get("violated_corners") or [])]
    out.update({
        "basis": "multi_corner_ocv",
        "mc_ocv_available": True,
        # A real ss/ff/any-corner setup/hold violation ⇒ the ECO MUST fire, even
        # when the single-corner tt STA is MET (the whole point of the fix).
        "eco_needed": bool(viol),
        "violated_corners": viol,
        "setup_worst_slack_ns": s.get("setup_worst_slack_ns"),
        "hold_worst_slack_ns": s.get("hold_worst_slack_ns"),
    })
    return out
