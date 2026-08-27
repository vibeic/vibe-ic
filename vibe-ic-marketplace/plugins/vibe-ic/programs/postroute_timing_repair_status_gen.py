#!/usr/bin/env python3
"""Emit the Step 32 post-route timing-repair status artefact.

The flow expects exactly one of
``phase3/stage3/postroute_timing_repair/no_repair_needed.flag`` or
``phase3/stage3/postroute_timing_repair/repair_log.json``. This generator
inspects the authoritative post-route STA result and emits the appropriate
artefact.

  * post-route TNS == 0 (or no slack violations) → `no_repair_needed.flag`
  * else → `repair_log.json` with a structured summary of remaining violations

chip-AGNOSTIC: works with any OpenROAD-style sta.rpt format.

Exit codes:
    0 = wrote the appropriate artefact (PASS or PASS_WITH_NOTE)
    2 = VACUOUS_PASS (no STA report yet — phase3 hasn't run)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402
import postroute_timing_repair_decision as _repair_dec  # noqa: E402
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


def _parse_sta_for_violations(sta_text: str) -> dict:
    """Return dict with WNS/TNS approximation and violation list.

    Detection priority:
      1. Explicit `tns <value>` / `wns <value>` lines (OpenSTA report_tns).
      2. Per-path "slack (MET)" lines with no "VIOLATED" anywhere.
      3. Fall through: assume TNS!=0 (conservative).
    """
    out = {
        "tns_zero": False,
        "wns_negative": False,
        "violation_paths": [],
        "raw_lines_inspected": 0,
    }
    out["raw_lines_inspected"] = len(sta_text.splitlines())
    # OpenROAD/OpenSTA style: "tns 0.00" or "wns 0.00"
    tns_m = re.search(r"\btns\s+([+\-]?\d+(?:\.\d+)?)", sta_text, re.I)
    wns_m = re.search(r"\bwns\s+([+\-]?\d+(?:\.\d+)?)", sta_text, re.I)
    if tns_m:
        out["tns_zero"] = float(tns_m.group(1)) >= 0
    if wns_m:
        out["wns_negative"] = float(wns_m.group(1)) < 0

    upper = sta_text.upper()
    has_violated = "VIOLATED" in upper
    # Per-path MET-only OpenROAD report_checks output
    if not tns_m and not wns_m:
        # Heuristic: if every reported "slack (...)" is MET, design is clean.
        slack_lines = re.findall(r"slack \(([^)]+)\)", sta_text, re.I)
        if slack_lines and all("MET" in s.upper() for s in slack_lines) \
           and not has_violated:
            out["tns_zero"] = True
            out["wns_negative"] = False
        elif has_violated:
            out["wns_negative"] = True
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("project", type=Path)
    p.add_argument("--json", default=None,
                   help="Write a structured summary to this path "
                        "(in addition to the canonical artefacts)")
    args = p.parse_args(argv)

    project = args.project.resolve()
    if not project.is_dir():
        print(f"VACUOUS_PASS: project dir missing: {project}",
              file=sys.stderr)
        return 2

    postroute_timing_repair_dir = _pl.postroute_timing_repair_dir(project)
    postroute_timing_repair_dir.mkdir(parents=True, exist_ok=True)

    # Discover STA report — try canonical sta_dir first, then pnr.
    sta_candidates = [
        # #527 — the SPEF-based post-route STA is the sign-off-grade basis;
        # it must outrank post_route_timing.rpt too: on a RESUMED project
        # the alias can be a stale estimate-based copy (written before the
        # SPEF run existed) and would otherwise shadow a VIOLATED SPEF
        # verdict with a stale MET (adversarial-review reproduction).
        _pl.sta_dir(project) / "sta_spef_based.rpt",
        project / "reports/phase3/sta_spef_based.rpt",
        _pl.sta_dir(project) / "post_route_timing.rpt",
        _pl.pnr_dir(project) / "sta.rpt",
        project / "phase3/reports/sta.rpt",
    ]
    sta_rpt = next((p for p in sta_candidates if p.is_file()), None)
    if sta_rpt is None:
        print("VACUOUS_PASS: no STA report found — phase3 not yet run.",
              file=sys.stderr)
        return 2

    text = sta_rpt.read_text(errors="ignore")
    info = _parse_sta_for_violations(text)
    # TAPEOUT-SIGNOFF (ibex-surfaced) — gate on the MULTI-CORNER OCV sign-off, not
    # just this single-corner (tt) STA. This generator runs AFTER
    # phase3_one_shot_runner.step_canonicalize_artefacts (which already fired the
    # repair when a multi-corner violation exists); consulting the SAME shared
    # decision means we do NOT re-write no_repair_needed.flag and clobber the primary
    # decision. §4.05: single-corner PDK ⇒ honest tt fallback (no regression).
    single_corner_clean = (not info["wns_negative"]) and info["tns_zero"]
    stance_path = _pl.reports_phase3_dir(project) / "mcorner_ocv_stance.json"
    # v1.7.64 (Step 32 / d5) — passing `project` lets the shared decision also
    # read the NON-TIMING sign-off verdicts this run already wrote (IR drop /
    # EM / SI / LVS / ERC / antenna / density / PERC). Step 32's own YAML text
    # says "if any sign-off step ... fails, repair applies"; before this the
    # decision read STA and nothing else, so a hard-failed IR-drop sign-off
    # still produced `no_repair_needed.flag` and a clean postroute_timing_repair_audit.
    decision = _repair_dec.decide(stance_path, single_corner_clean,
                               project=project)
    summary = {
        "program": "postroute_timing_repair_status_gen",
        "version": "1.1.0",
        "project": str(project),
        "sta_source": str(sta_rpt.relative_to(project)),
        "wns_negative": info["wns_negative"],
        "tns_zero": info["tns_zero"],
        "repair_trigger_basis": decision["basis"],
        "mc_ocv_available": decision["mc_ocv_available"],
    }
    if decision["violated_corners"]:
        summary["violated_corners"] = decision["violated_corners"]
    summary["timing_repair_needed"] = decision["timing_repair_needed"]
    if decision["nontiming_failures"]:
        summary["nontiming_failures"] = decision["nontiming_failures"]

    if not decision["repair_needed"]:
        flag = postroute_timing_repair_dir / "no_repair_needed.flag"
        flag.write_text(
            "no_repair_needed\n"
            f"# Generated by {_pmd.emitted_by('postroute_timing_repair_status_gen')} from "
            f"{sta_rpt.relative_to(project)}\n"
            f"# Basis: {decision['basis']} "
            f"(mc_ocv_available={decision['mc_ocv_available']}).\n"
            "# Reason: no setup/hold violation at the authoritative timing basis\n"
            "# (multi-corner OCV when available, else single-corner tt STA),\n"
            "# and no hard failure in the non-timing sign-off domains\n"
            "# (IR drop / EM / SI / LVS / ERC / antenna / density / PERC).\n"
        )
        summary["verdict"] = "PASS"
        summary["artefact"] = str(flag.relative_to(project))
        # Also emit JSON for tools that prefer structured form
        (postroute_timing_repair_dir / "no_repair_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n")
    else:
        log_path = postroute_timing_repair_dir / "repair_log.json"
        minimal = {
            "program": "postroute_timing_repair_status_gen",
            "verdict": "REPAIR_REQUIRED",
            "sta_source": str(sta_rpt.relative_to(project)),
            "wns_negative": info["wns_negative"],
            "tns_zero": info["tns_zero"],
            "raw_lines_inspected": info["raw_lines_inspected"],
            # v1.7.64 — name WHY repair is required. `changes` stays absent
            # and `re_verified` stays false, so postroute_timing_repair_audit still reports
            # EMPTY_CHANGES / NOT_REVERIFIED: this record demands repair; it
            # does not fabricate one.
            "trigger_basis": decision["basis"],
            "timing_repair_needed": decision["timing_repair_needed"],
            "nontiming_failures": decision["nontiming_failures"],
            "trigger_reason": decision["reason"],
            "remediation": ("Run the post-route timing repair pass, then "
                            "re-run phase3_one_shot_runner "
                            "to refresh STA and overwrite this log."
                            if decision["timing_repair_needed"] else
                            "A non-timing sign-off domain FAILED; the "
                            "timing-repair pass does not apply. Triage the "
                            "named domain(s) (IR drop / "
                            "EM / SI / PV) and re-run the failing sign-off "
                            "step, then re-run phase3_one_shot_runner."),
        }
        # ORGANIC #564 — do NOT clobber a schema-complete repair record an
        # agent or prior repair pass already wrote. A real repair_log.json carries the
        # remediation provenance (changes / re_verified / affected_steps)
        # that postroute_timing_repair_audit checks for NOT_REVERIFIED; blindly rewriting
        # the minimal "REPAIR_REQUIRED" shape erased it and failed the audit
        # even though re-verification WAS done. Merge the fresh measured
        # values into the existing record instead, preserving those fields.
        _PRESERVE = ("changes", "re_verified", "reverified",
                     "affected_steps", "repair_changes", "verification")
        existing = None
        if log_path.is_file():
            try:
                _e = json.loads(log_path.read_text(errors="ignore"))
                if isinstance(_e, dict) and any(
                        _e.get(k) for k in _PRESERVE):
                    existing = _e
            except Exception:
                existing = None
        if existing is not None:
            merged = dict(existing)
            # refresh only the freshly-measured / provenance fields; keep the
            # agent's richer remediation record intact.
            merged["sta_source"] = minimal["sta_source"]
            merged["wns_negative"] = info["wns_negative"]
            merged["tns_zero"] = info["tns_zero"]
            merged["raw_lines_inspected"] = info["raw_lines_inspected"]
            merged.setdefault("verdict", "REPAIR_REQUIRED")
            merged["status_refreshed_by"] = "postroute_timing_repair_status_gen (merge; "
            merged["status_refreshed_by"] += "preserved existing repair record)"
            log_path.write_text(json.dumps(merged, indent=2) + "\n")
            summary["verdict"] = merged.get("verdict", "REPAIR_REQUIRED")
            summary["preserved_existing_repair_log"] = True
        else:
            log_path.write_text(json.dumps(minimal, indent=2) + "\n")
            summary["verdict"] = "REPAIR_REQUIRED"
        summary["artefact"] = str(log_path.relative_to(project))

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
