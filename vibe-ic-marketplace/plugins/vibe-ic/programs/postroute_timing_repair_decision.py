#!/usr/bin/env python3
"""The shared Step 32 post-route timing-repair trigger decision.

TAPEOUT-SIGNOFF gap (ibex-surfaced):
  The trigger used to read ONLY the single-corner (typical / tt)
  post-route STA. A large design can MEET timing at the tt corner yet carry a
  huge setup violation at the SLOW (ss) process corner because slews explode
  there (ibex: tt +6.02 ns MET, ss −88 ns VIOLATED). Gating the trigger on tt
  alone writes ``no_repair_needed.flag`` and the multi-corner-aware repair
  (``_build_postroute_timing_repair_tcl`` with corner_libs, ss-first) NEVER fires for exactly
  the designs that need it — the repair deck is emitted but dead.

This module is the ONE decision that BOTH ``no_repair_needed.flag`` sites consult:
  * ``phase3_one_shot_runner.step_canonicalize_artefacts`` (the primary site,
    which also FIRES the repair), and
  * ``postroute_timing_repair_status_gen.py`` (a derived-artefact generator that runs AFTER
    canonicalize and would otherwise re-write ``no_repair_needed.flag`` from the
    single-corner STA, clobbering the primary decision).
Sharing the decision means the two sites cannot drift.

§4.05 HONEST fallback: when multi-corner OCV sign-off is UNAVAILABLE (a
single-corner PDK exposing no distinct ss/ff process liberties), the decision
degrades to today's single-corner (tt) behavior — no regression and no
fabricated multi-corner claim. It never declares no-repair-needed when a real
multi-corner violation exists.

v1.7.64 (Step 32 / d5) — NON-TIMING SIGN-OFF FAIL-CLOSE.
  The flow YAML declares Step 32 as "If any sign-off step (STA, PV, IR Drop,
  EM, SI, Post-Sim, SPICE) fails, a repair is required".
  `decide()` read STA and nothing else, so a run with a hard-failed IR-drop /
  EM / PV sign-off still wrote `no_repair_needed.flag` and `postroute_timing_repair_audit`
  short-circuited to a clean PASS. Measured: a project with
  `reports/phase3/ir_drop.json {"verdict": "FAIL"}` next to a clean STA
  produced `verdict: PASS, artefact: no_repair_needed.flag`, rc=0.

  The decision now ALSO reads the non-timing sign-off verdicts that the same
  run already wrote, and REFUSES to return repair_needed=False while any of them
  reports a HARD failure. This is deliberately a fail-close, not new repair
  capability: `timing_repair_needed` still gates the timing-repair TCL, so a
  non-timing failure never fires `postroute_timing_repair.tcl` and never fabricates
  a ``repair_log.json``. It withholds the no-repair-needed certificate and
  leaves the failing domain visible to the closed loop.

  Conservative by construction (a false repair demand would deadlock every run):
  only an EXPLICIT hard-failure signal counts. A missing artefact, an
  unparseable artefact, a warning/review verdict (e.g. ERC "REVIEW"), an
  advisory screen and a measurement-only verdict all count as NOT a failure.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


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


# ---------------------------------------------------------------------------
# v1.7.64 — non-timing sign-off inputs.
#
# An explicit, bounded table of the canonical sign-off verdict artefacts the
# same phase-3 run already writes. A table (not a glob) keeps the blast radius
# auditable and keeps an unrelated gate report from deadlocking Step 32.
# chip-AGNOSTIC: canonical relative paths only.
# ---------------------------------------------------------------------------
_NON_TIMING_SIGNOFF_ARTEFACTS = (
    ("ir_drop", "reports/phase3/ir_drop.json"),
    ("em", "reports/phase3/em.json"),
    ("si_crosstalk", "reports/phase3/si_crosstalk.json"),
    ("lvs", "reports/phase3/lvs.json"),
    ("lvs_verdict", "reports/phase3/lvs_verdict.json"),
    ("erc", "reports/phase3/erc.json"),
    ("antenna", "reports/phase3/antenna.json"),
    ("erc_density", "reports/phase2/gates/erc_density.json"),
    ("perc_signoff", "reports/phase2/gates/perc_signoff.json"),
)

# ONLY these verdict tokens are a hard failure. Deliberately excludes review /
# advisory / measurement tiers ("REVIEW", "BENIGN-ERC", "MEASURED",
# "ADVISORY_SCREEN_ONLY", "PASS_WITH_OPEN_ITEMS", …) — treating those as
# failures would demand repair on essentially every open-source run.
_HARD_FAIL_VERDICTS = frozenset({
    "FAIL", "FAILED", "FAILURE", "VIOLATED", "VIOLATION",
    "MISMATCH", "NO_MATCH", "NOT_CLEAN", "REJECTED", "ERROR",
})


def _hard_failure_signal(data: Any) -> Optional[str]:
    """Return a short description of the EXPLICIT hard-failure signal carried
    by a parsed sign-off artefact, or None when there is none.

    Recognised signals, in order:
      * ``verdict`` / ``status`` / ``result`` equal to a hard-fail token;
      * ``passed`` / ``pass`` exactly False;
      * ``summary.pass`` exactly False.

    Anything else — including a missing field, a warning tier, or a shape this
    function does not understand — returns None. Silence is NOT failure here:
    an absent or unreadable sign-off artefact is Step 21-31's problem, and
    reading it as failure would deadlock Step 32 on every run.
    """
    if not isinstance(data, dict):
        return None
    for key in ("verdict", "status", "result"):
        val = data.get(key)
        if isinstance(val, str) and val.strip().upper() in _HARD_FAIL_VERDICTS:
            return f"{key}={val.strip()}"
    for key in ("passed", "pass"):
        if data.get(key) is False:
            return f"{key}=false"
    summary = data.get("summary")
    if isinstance(summary, dict) and summary.get("pass") is False:
        return "summary.pass=false"
    return None


def collect_non_timing_failures(
    project: Union["Path", str, None],
    signoff_reports: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Return one record per non-timing sign-off domain that reports a HARD
    failure: ``[{"domain": ..., "path": ..., "signal": ...}, ...]``.

    ``signoff_reports`` lets a caller (tests, or a future in-memory producer)
    supply already-parsed artefacts as ``{domain: dict}`` instead of reading
    from disk. When both are given, the parsed override wins for the domains
    it names and the rest still come from disk.
    """
    out: List[Dict[str, str]] = []
    overrides = signoff_reports or {}
    root: Optional[Path] = None
    if project is not None:
        try:
            root = Path(project)
        except TypeError:
            root = None

    for domain, rel in _NON_TIMING_SIGNOFF_ARTEFACTS:
        if domain in overrides:
            signal = _hard_failure_signal(overrides[domain])
            if signal:
                out.append({"domain": domain, "path": rel, "signal": signal})
            continue
        if root is None:
            continue
        p = root / rel
        if not p.is_file():
            continue          # absent ⇒ not a failure (see docstring)
        try:
            data = json.loads(p.read_text(errors="ignore"))
        except Exception:
            continue          # unparseable ⇒ not a failure
        signal = _hard_failure_signal(data)
        if signal:
            out.append({"domain": domain, "path": rel, "signal": signal})

    # Domains supplied only as overrides (not in the canonical table) are
    # honoured too, so a caller can extend coverage without editing this file.
    for domain, data in overrides.items():
        if any(r["domain"] == domain for r in out):
            continue
        if any(domain == d for d, _ in _NON_TIMING_SIGNOFF_ARTEFACTS):
            continue
        signal = _hard_failure_signal(data)
        if signal:
            out.append({"domain": domain, "path": "(caller-supplied)",
                        "signal": signal})
    return out


def decide(stance: Union["Path", str, dict, None],
           single_corner_clean: bool,
           project: Union["Path", str, None] = None,
           signoff_reports: Optional[Dict[str, Any]] = None,
           ) -> Dict[str, Any]:
    """Return the post-route timing-repair trigger decision.

    Args:
      stance: path to (or already-parsed dict of) ``mcorner_ocv_stance.json``.
      single_corner_clean: True when the single-corner (tt) post-route STA has
        NO setup/hold violation (TNS=0 / no ``VIOLATED``). This is the ONLY
        signal the pre-fix trigger used.
      project: OPTIONAL project root. When given, the non-timing sign-off
        verdicts the same run already wrote are consulted (v1.7.64). Omitted ⇒
        exactly the pre-v1.7.64 timing-only behaviour.
      signoff_reports: OPTIONAL ``{domain: parsed_dict}`` override, so a caller
        can supply verdicts without touching the filesystem.

    Returns a dict:
      basis:            "multi_corner_ocv" | "single_corner_tt" — the TIMING
                        basis; unchanged by v1.7.64
      mc_ocv_available: multi-corner OCV genuinely ran (>=2 distinct process
                        corners) AND produced a report
      timing_repair_needed:True ⇒ a TIMING violation exists; this alone may fire
                        ``postroute_timing_repair.tcl`` (v1.7.64; pre-v1.7.64 this
                        was what ``repair_needed`` meant)
      repair_needed:       True  ⇒ a repair is required (do not write
                        ``no_repair_needed.flag``)
                        False ⇒ no repair is needed.
                        = timing_repair_needed OR any non-timing hard failure.
      nontiming_failures: [{"domain","path","signal"}] hard-failed sign-off
                        domains (empty when ``project``/``signoff_reports``
                        are not supplied)
      reason:           human-readable basis of the repair_needed value
      violated_corners: corner(s) with a real violation (multi-corner basis only)
      setup_worst_slack_ns / hold_worst_slack_ns: the REAL per-corner worst slack

    Decision logic:
      * multi-corner OCV authoritative (multi_process_corner True + a report):
        timing_repair_needed = a real violation exists at ANY signed-off corner.
      * else (single-corner PDK / OCV unavailable): timing_repair_needed = NOT
        clean at tt — today's behavior, no regression.
      * repair_needed = timing_repair_needed OR a hard failure in any non-timing
        sign-off domain. Step 32 may not certify "no post-route repair needed" over a failed
        IR-drop / EM / SI / PV sign-off (v1.7.64).
    """
    out: Dict[str, Any] = {
        "basis": "single_corner_tt",
        "mc_ocv_available": False,
        "timing_repair_needed": not single_corner_clean,
        "repair_needed": not single_corner_clean,
        "violated_corners": [],
        "setup_worst_slack_ns": None,
        "hold_worst_slack_ns": None,
        "nontiming_failures": [],
        "reason": "",
    }
    s = _load_stance(stance)
    if s:
        # Authoritative ONLY when the multi-corner OCV sign-off genuinely ran
        # across >=2 distinct process corners AND produced a report. A
        # single-corner stance (multi_process_corner False, report None) is NOT
        # authoritative — the honest tt fallback stands (§4.05: no fabricated
        # multi-corner claim).
        available = bool(s.get("multi_process_corner")) and bool(s.get("report"))
        if available:
            viol = [str(c) for c in (s.get("violated_corners") or [])]
            out.update({
                "basis": "multi_corner_ocv",
                "mc_ocv_available": True,
                # A real ss/ff/any-corner setup/hold violation means repair MUST
                # fire, even when the single-corner tt STA is MET (the whole
                # point of the fix).
                "timing_repair_needed": bool(viol),
                "repair_needed": bool(viol),
                "violated_corners": viol,
                "setup_worst_slack_ns": s.get("setup_worst_slack_ns"),
                "hold_worst_slack_ns": s.get("hold_worst_slack_ns"),
            })

    # v1.7.64 — fail-close over the non-timing sign-off domains. Purely
    # additive: it can only turn repair_needed from False to True, never the
    # other way, so a real timing violation can never be masked.
    if project is not None or signoff_reports is not None:
        out["nontiming_failures"] = collect_non_timing_failures(
            project, signoff_reports)
    if out["nontiming_failures"]:
        out["repair_needed"] = True

    if out["timing_repair_needed"]:
        out["reason"] = (
            f"timing violation at basis {out['basis']}"
            + (f" (corners: {','.join(out['violated_corners'])})"
               if out["violated_corners"] else ""))
        if out["nontiming_failures"]:
            out["reason"] += (
                "; also non-timing sign-off failure(s): "
                + ", ".join(f"{r['domain']}({r['signal']})"
                            for r in out["nontiming_failures"]))
    elif out["nontiming_failures"]:
        out["reason"] = (
            "no timing violation, but non-timing sign-off failure(s): "
            + ", ".join(f"{r['domain']}({r['signal']})"
                        for r in out["nontiming_failures"])
            + " — Step 32 may not certify 'no repair needed' over a failed "
              "sign-off domain")
    else:
        out["reason"] = (
            f"no setup/hold violation at basis {out['basis']}"
            + (" and no non-timing sign-off failure"
               if (project is not None or signoff_reports is not None) else ""))
    return out
