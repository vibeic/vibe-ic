#!/usr/bin/env python3
"""Emit the Step 32 post-route timing-repair status artefact.

For a measured decision the flow expects exactly one of
``phase3/stage3/postroute_timing_repair/no_repair_needed.flag`` or
``phase3/stage3/postroute_timing_repair/repair_log.json``. This generator
inspects the authoritative post-route STA result and emits the appropriate
artefact. An unreadable timing basis emits ``measurement_not_available.json``
and a non-success exit, without claiming a repair or a clean sign-off.

  * measured timing clean (TNS / WNS / worst slack >= 0, every path MET)
    → `no_repair_needed.flag`
  * else → `repair_log.json` with a structured summary of remaining violations

DRV and minimum-pulse-width violator rows are not timing paths: they are
disclosed as ``non_path_violations`` beside the verdict and do not decide it.

chip-AGNOSTIC: works with any OpenROAD-style sta.rpt format.

Exit codes:
    0 = wrote the appropriate artefact (PASS or PASS_WITH_NOTE)
    2 = NOT_MEASURED (no STA report or no usable timing measurement)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402
import _atomic_artefact as _aa  # noqa: E402
import postroute_timing_repair_decision as _repair_dec  # noqa: E402
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


#: A signed number as OpenSTA prints it.
_NUM = r"[+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?"
#: The summary lines: `tns 0.00` / `tns max 0.00` (report_tns), `wns max -0.1`
#: (report_wns), `worst slack max 0.38` (report_worst_slack). Older builds omit
#: the max/min token; this image prints it. Both spellings are one measurement.
_SUMMARY_RE = re.compile(
    rf"\b(tns|wns|worst[ \t]+slack)(?:[ \t]+(?:max|min))?[ \t]+({_NUM})(?![\w.])",
    re.IGNORECASE)
#: A report_checks path end: `0.38   slack (MET)` / `-0.05 slack (VIOLATED)`.
_PATH_SLACK_RE = re.compile(
    r"\bslack[ \t]*(?:\([ \t]*(MET|VIOLATED)[ \t]*\)|(MET|VIOLATED)\b)",
    re.IGNORECASE)
#: report_check_types' path-group table (recovery/removal and the sign-off
#: worst-path listing): a `Group  Slack` header, then `<group>  <slack>` rows.
_GROUP_HEADER_RE = re.compile(r"^\s*Group\s+Slack\s*$", re.IGNORECASE)
_GROUP_ROW_RE = re.compile(
    rf"^\s*\S+\s+({_NUM})(?:\s+\((MET|VIOLATED)\))?\s*$", re.IGNORECASE)
#: Tables whose rows carry a `(VIOLATED)` tag but are NOT a timing path: the
#: DRV limits and the minimum pulse width. Same titles `extract_drv`
#: (sta_corner_record_completeness_check) recognises.
_NON_PATH_TITLES = {
    "max slew": "max_slew", "max transition": "max_slew",
    "max capacitance": "max_capacitance", "max cap": "max_capacitance",
    "max fanout": "max_fanout", "min pulse width": "min_pulse_width",
}
_NON_PATH_TITLE_RE = re.compile(
    r"^\s*(max\s+(?:slew|transition|capacitance|cap|fanout)|min\s+pulse\s+width)\s*$",
    re.IGNORECASE)
#: A limit table's column header, for a build that prints no title line.
_LIMIT_HEADER_RE = re.compile(
    r"^\s*Pin\s+Limit\s+(Slew|Transition|Cap(?:acitance)?|Fanout)\s+Slack\s*$",
    re.IGNORECASE)
_PULSE_HEADER_RE = re.compile(r"^\s*Pin\s+Width\s+Width\s+Slack\s*$",
                              re.IGNORECASE)
#: Any other check title opens a table that is not one of the above.
_OTHER_TITLE_RE = re.compile(
    r"^\s*(recovery|removal|setup|hold|clock\s+gating|data\s+check|"
    r"latch\s+check|max\s+skew|unconstrained)\b.*$", re.IGNORECASE)
#: Lines that end any open table: section banners, emitter stamps, a path.
_TABLE_END_RE = re.compile(
    r"^\s*(===|SIGNOFF_|STA_|OCV_|Startpoint:|Endpoint:)")
_ROW_TAG_RE = re.compile(r"\((VIOLATED)\)", re.IGNORECASE)
_TRAILING_NEG_RE = re.compile(rf"\s(-(?:\d+(?:\.\d*)?|\.\d+))\s*$")
_MAX_ROWS = 20


def _revoke_stale_outcomes(repair_dir: Path) -> None:
    """An unmeasured run cannot retain a prior clean or repaired certificate."""
    for name in ("no_repair_needed.flag", "no_repair_summary.json",
                 "repair_log.json"):
        (repair_dir / name).unlink(missing_ok=True)


def _parse_sta_for_violations(sta_text: str) -> dict:
    """Classify one STA report into a timing measurement and the rest.

    ``timing_measurement``:
      * VIOLATED -- a negative TNS / WNS / worst slack, a ``slack (VIOLATED)``
        path, a negative path-group slack, or a ``(VIOLATED)`` row that no
        known non-path table owns (never silently cleared);
      * CLEAN -- at least one timing number (TNS / WNS / worst slack, a path
        slack or a path-group slack) and none of the above;
      * NOT_MEASURED -- no timing number at all.

    ``(VIOLATED)`` rows in the DRV (max slew / capacitance / fanout) and
    minimum-pulse-width tables are not path slacks. They are reported in
    ``non_path_violations`` and do not decide the timing measurement; the
    sign-off DRV verdict belongs to Step 23's record gate.
    """
    out = {
        "tns_zero": False,
        "wns_negative": False,
        "timing_measurement": "NOT_MEASURED",
        "violation_paths": [],
        "non_path_violations": {"count": 0, "by_check": {}, "rows": []},
        "raw_lines_inspected": 0,
    }
    lines = sta_text.splitlines()
    out["raw_lines_inspected"] = len(lines)
    tns: list = []
    wns: list = []
    evidence = 0
    violated = False
    unowned: list = []
    table = None        # None | "group" | "other" | a _NON_PATH_TITLES value
    npv = out["non_path_violations"]

    for raw in lines:
        line = raw.strip()
        for kind, num in _SUMMARY_RE.findall(raw):
            value = float(num)
            evidence += 1
            violated = violated or value < 0
            (tns if kind.lower() == "tns" else wns).append(value)
        path = _PATH_SLACK_RE.search(raw)
        if path:
            evidence += 1
            if (path.group(1) or path.group(2)).upper() == "VIOLATED":
                violated = True
                if len(out["violation_paths"]) < _MAX_ROWS:
                    out["violation_paths"].append(line)
            continue
        if _TABLE_END_RE.match(raw):
            table = None
            continue
        title = _NON_PATH_TITLE_RE.match(raw)
        header = _LIMIT_HEADER_RE.match(raw)
        if title:
            table = _NON_PATH_TITLES[re.sub(r"\s+", " ", title.group(1).lower())]
            continue
        if header:
            word = header.group(1).lower()
            table = ("max_slew" if word in ("slew", "transition") else
                     "max_fanout" if word == "fanout" else "max_capacitance")
            continue
        if _PULSE_HEADER_RE.match(raw):
            table = "min_pulse_width"
            continue
        if _GROUP_HEADER_RE.match(raw):
            table = "group"
            continue
        if _OTHER_TITLE_RE.match(raw):
            table = "other"
            continue
        tagged = bool(_ROW_TAG_RE.search(raw))
        row = _GROUP_ROW_RE.match(raw) if table == "group" else None
        if row:
            evidence += 1
            if float(row.group(1)) < 0 or (row.group(2) or "").upper() == "VIOLATED":
                violated = True
                if len(out["violation_paths"]) < _MAX_ROWS:
                    out["violation_paths"].append(line)
            continue
        if table in _NON_PATH_TITLES.values():
            if tagged or (_TRAILING_NEG_RE.search(raw) and len(line.split()) >= 3):
                npv["count"] += 1
                npv["by_check"][table] = npv["by_check"].get(table, 0) + 1
                if len(npv["rows"]) < _MAX_ROWS:
                    npv["rows"].append(line)
            continue
        if tagged:
            # A violator row whose table this parser cannot name. Refusing to
            # read it as clean is the conservative direction.
            unowned.append(line)

    if unowned:
        violated = True
        out["violation_paths"].extend(unowned[:max(0, _MAX_ROWS - len(out["violation_paths"]))])
    if violated:
        out["timing_measurement"] = "VIOLATED"
    elif evidence:
        out["timing_measurement"] = "CLEAN"
    measured = out["timing_measurement"]
    out["tns_zero"] = all(v >= 0 for v in tns) if tns else measured == "CLEAN"
    out["wns_negative"] = any(v < 0 for v in wns) if wns else measured == "VIOLATED"
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
        _revoke_stale_outcomes(postroute_timing_repair_dir)
        status_path = postroute_timing_repair_dir / "measurement_not_available.json"
        remediation = ("Re-run post-route STA and confirm it reports measured "
                       "timing slack or TNS/WNS before deciding whether repair "
                       "is needed.")
        status = {
            "program": "postroute_timing_repair_status_gen",
            "verdict": "NOT_MEASURED",
            "reason_class": "missing_sta_report",
            "sta_source": None,
            "sta_candidates": [str(path.relative_to(project)) for path in sta_candidates],
            "timing_basis_status": "NOT_MEASURED",
            "timing_repair_needed": False,
            "nontiming_failures": [],
            "nontiming_not_determined": [],
            "trigger_reason": "No candidate post-route STA report exists.",
            "remediation": remediation,
        }
        _aa.write_json(status_path, status)
        summary = {**status, "project": str(project),
                   "artefact": str(status_path.relative_to(project))}
        if args.json:
            _aa.write_json(Path(args.json), summary)
        print(json.dumps(summary, indent=2))
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
    decision = _repair_dec.decide(
        stance_path, single_corner_clean, project=project,
        single_corner_evidence=info["timing_measurement"])
    # R-0929-STEP32-RECORD — the recorded Step-32 decision is read only when
    # it is bound to the bytes it was decided from; an unbound or stale
    # record certifies nothing, so the no-repair flag is withdrawn. A bound
    # repair_needed=true (the producer's receipt, or the canonical record of
    # an adopted repair) is ORed in: this generator never flips it to false.
    record_path = postroute_timing_repair_dir / "postroute_timing_repair_decision.json"
    measured_step32 = None
    if record_path.is_file():
        try:
            measured_step32 = _repair_dec.verify_receipt(
                project, json.loads(record_path.read_text(errors="replace")))
        except (OSError, ValueError, TypeError) as exc:
            (postroute_timing_repair_dir / "no_repair_needed.flag").unlink(missing_ok=True)
            print(f"NOT_MEASURED: Step-32 decision invalid: {exc}", file=sys.stderr)
            return 2
    if measured_step32 and measured_step32["repair_needed"] and not decision["repair_needed"]:
        decision["repair_needed"] = True
        decision["basis"] += "+measured_step32"
        decision["reason"] += (
            f"; the recorded Step-32 decision says repair_needed=true "
            f"(action={measured_step32.get('action')})")
    summary = {
        "program": "postroute_timing_repair_status_gen",
        "version": "1.1.0",
        "project": str(project),
        "sta_source": str(sta_rpt.relative_to(project)),
        "wns_negative": info["wns_negative"],
        "tns_zero": info["tns_zero"],
        "repair_trigger_basis": decision["basis"],
        "mc_ocv_available": decision["mc_ocv_available"],
        "timing_basis_status": decision["timing_basis_status"],
    }
    if decision["violated_corners"]:
        summary["violated_corners"] = decision["violated_corners"]
    summary["timing_repair_needed"] = decision["timing_repair_needed"]
    if decision["nontiming_failures"]:
        summary["nontiming_failures"] = decision["nontiming_failures"]
    if measured_step32 is not None:
        summary["measured_step32_repair_needed"] = measured_step32["repair_needed"]
    if info["non_path_violations"]["count"]:
        # Disclosed, not judged here: Step 23's STA record gate owns the DRV
        # verdict. Folding these rows into the timing verdict would call a
        # slew limit a setup/hold violation (or, with no timing number,
        # a measurement of timing).
        summary["non_path_violations"] = info["non_path_violations"]
    _rerun_sta = ("Re-run post-route STA and confirm it reports measured timing "
                  "slack or TNS/WNS before deciding whether repair is needed.")

    # A readable report header is not a timing measurement. Keep this state
    # separate from a measured repair demand and from a non-timing failure.
    # A previous run's flag or repair log must not certify this new run.
    no_measurement = (not decision["timing_repair_needed"]
                      and not decision["nontiming_failures"]
                      and (decision["timing_basis_status"] == "NOT_MEASURED"
                           or decision["nontiming_not_determined"]))
    if no_measurement:
        _revoke_stale_outcomes(postroute_timing_repair_dir)
        status_path = postroute_timing_repair_dir / "measurement_not_available.json"
        remediation = (
            _rerun_sta
            if decision["timing_basis_status"] == "NOT_MEASURED" else
            "Re-run the incomplete non-timing sign-off domain(s) before "
            "deciding whether repair is needed.")
        status = {
            "program": "postroute_timing_repair_status_gen",
            "verdict": "NOT_MEASURED",
            "sta_source": str(sta_rpt.relative_to(project)),
            "timing_basis_status": decision["timing_basis_status"],
            "timing_repair_needed": False,
            "nontiming_failures": [],
            "nontiming_not_determined": decision["nontiming_not_determined"],
            "trigger_reason": decision["reason"],
            "remediation": remediation,
        }
        if info["non_path_violations"]["count"]:
            status["non_path_violations"] = info["non_path_violations"]
        _aa.write_json(status_path, status)
        summary.update(verdict="NOT_MEASURED",
                       artefact=str(status_path.relative_to(project)),
                       remediation=remediation)
        if args.json:
            _aa.write_json(Path(args.json), summary)
        print(json.dumps(summary, indent=2))
        return 2

    (postroute_timing_repair_dir / "measurement_not_available.json").unlink(
        missing_ok=True)

    if not decision["repair_needed"]:
        flag = postroute_timing_repair_dir / "no_repair_needed.flag"
        npv = info["non_path_violations"]
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
            + (f"# Disclosed, not judged here: {npv['count']} non-path violator "
               "row(s) in the same report ("
               + ", ".join(f"{k} x{v}" for k, v in sorted(npv["by_check"].items()))
               + "); the sign-off DRV verdict belongs to Step 23's STA record "
               "gate.\n" if npv["count"] else "")
        )
        summary["verdict"] = "PASS"
        summary["artefact"] = str(flag.relative_to(project))
        # Also emit JSON for tools that prefer structured form
        (postroute_timing_repair_dir / "no_repair_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n")
    else:
        (postroute_timing_repair_dir / "no_repair_needed.flag").unlink(
            missing_ok=True)
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
            "timing_basis_status": decision["timing_basis_status"],
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
                            "step, then re-run phase3_one_shot_runner."
                            + (" Timing is also NOT_MEASURED at "
                               f"{sta_rpt.relative_to(project)}: " + _rerun_sta
                               if decision["timing_basis_status"] == "NOT_MEASURED"
                               else "")),
        }
        if info["non_path_violations"]["count"]:
            minimal["non_path_violations"] = info["non_path_violations"]
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
            merged["timing_basis_status"] = decision["timing_basis_status"]
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
