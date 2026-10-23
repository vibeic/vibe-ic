#!/usr/bin/env python3
"""librelane_postroute_repair.py — step 32 (post-route repair) on LibreLane (T102).

Selected by `phase3/librelane_switch.json` (`"32": "librelane"`) through
`librelane_contract.selected_mode`. With `direct` (switch absent, or naming
other steps) `phase3_one_shot_runner` runs `step_signoff_spef_repair` and the
DRV wire-length escalation exactly as before and nothing here is called.

WHAT RUNS INSTEAD
=================
The routed database is bridged into a LibreLane State
(`librelane_contract.state_from_direct`) and the repair is the plugin step
`Vibeic.PostRouteRepair` (`librelane_plugins/librelane_plugin_vibeic/
postroute_repair.py`): fork `estimate_parasitics -detailed_routing` on the
router's own extracted wires, `repair_design`, `repair_timing -setup`, then
`-hold`, legalization of the changed cells only, supply connection, ECO
`detailed_route -nets` of the touched nets, re-verify. One run of it is one
CANDIDATE. Every candidate, and the input, is measured the same way:
`OpenROAD.RCX` then `OpenROAD.STAPostPNR` (every STA corner) in the sign-off
scene (the deck's SDC plus the sign-off STA's flat-OCV derate).

WHO DECIDES
===========
`_ppa/closure.py`. The actuator `timing.repair_setup` (config/
ppa_actuator_registry.yaml) is EXECUTABLE: its wrapper is this program's
`actuate` subcommand, its parameters (setup/hold margin, buffer budgets,
repair_tns) are a declared ladder, and the domains it re-measures —
`timing.setup`, `timing.hold`, `timing.drv`, `antenna.violations` — are this
program's `measure` subcommand over the ADOPTED candidate. The input route is
measured on the same instruments: the plugin step in census-only mode
(`VIBEIC_PRR_CENSUS_ONLY`, `check_antennas`), then RCX + STAPostPNR. The controller
promotes a candidate only on a measured improvement of its objective with no
regression in any re-measured domain, and rolls back otherwise. T98's finding
(a DRV repair that took SS setup from +3.33 to +0.14 because it was the first
candidate that passed DRV) cannot recur: setup is re-measured on every
candidate and a setup regression rolls the candidate back.

THE IMPLEMENTATION ROOT IS A POINTER
====================================
The closure snapshots and restores its implementation root, so the root holds
exactly two small files: `context.json` (how to run a candidate: project,
image, PDK mount, resolved configs) and `current.json` (the adopted State and
its measurement, bound by sha256). Candidate States live in LibreLane's own
step directories, which are never overwritten, so a rollback is keeping the
previous pointer: nothing is re-read or re-routed to undo a candidate. The
ledger of every candidate (adopted or not, and why) lives outside the root.

HARD REFUSALS, BEFORE A CANDIDATE CAN BE ADOPTED
================================================
* supply ownership (F24): `pg_supply_pin_ownership_check` on the candidate's
  own DEF. A proven off-supply pin keeps the pointer where it was;
* antenna, by the step-26 instrument (`OpenROAD.CheckAntennas`): a candidate
  with more violating nets OR pins than the state it was built from, or an
  uncounted dimension, keeps the pointer where it was;
* the repair step's own `check_placement` (it fails the step);
* router DRC: the fork's scoped `detailed_route -nets` refuses a route with
  more whole-design violations than it was given (DRT-0712), which fails the
  candidate's step; the ledger records it as TOOL_REFUSED.

A step failure is TOOL_REFUSED (rc 0, the pointer stays, the next rung runs)
only when its log carries one of the step's own named refusals
(`[VIBEIC_]PRR_*_REFUSED` / `_RESIDUE`, check_placement's included, and
`LL_PRR_FANOUT_LIMIT_BROKEN`) and no crash. A signal, a stall, or an unexplained failure is
ACTUATOR_FAILED / NOT_MEASURED (rc 2); a step failure of that kind gets one
retry in the `hold_first` move order.

chip-AGNOSTIC: no design, PDK, corner, cell or net literal. Every value comes
from the resolved LibreLane config, the direct deck's own files or the
registry's declared ladder.
"""
from __future__ import annotations

import math

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json, write_text  # noqa: E402
import _docker_memory as _dmem  # noqa: E402 — every `docker run` carries the ceiling

STEP = "32"
REPAIR_STEP = "Vibeic.PostRouteRepair"
#: Every candidate, and the input, is measured by the same three steps: the
#: step-26 router-model antenna instrument (`OpenROAD.CheckAntennas`, whose
#: `antenna__violating__nets` `librelane_ir_antenna` judges), then RCX, then
#: STAPostPNR at every corner.
MEASURE_STEPS = ("OpenROAD.CheckAntennas", "OpenROAD.RCX", "OpenROAD.STAPostPNR")
ANTENNA_METRICS = ("antenna__violating__nets", "antenna__violating__pins")
ARM_REL = "phase3/tool_arms/32"
IMPL_DIR = "impl"
CONTEXT = "context.json"
CURRENT = "current.json"
LEDGER = "candidates.json"
REPORT_REL = "reports/phase3/librelane_postroute_repair.json"
DECLARED_REPAIR_REL = "phase3/stage3/postroute_timing_repair"
#: The controllers this step runs, in order: setup, then hold (hold after
#: setup), then design rules. Each is declared in the actuator registry.
CONTROLLERS = ("postroute.repair_setup", "postroute.repair_hold",
               "postroute.repair_drv")

#: The actuator's parameters -> the plugin step's variables.
PARAM_VARS = {
    "setup_margin_ns": "VIBEIC_PRR_SETUP_MARGIN",
    "setup_sequence": "VIBEIC_PRR_SETUP_SEQUENCE",
    "hold_margin_ns": "VIBEIC_PRR_HOLD_MARGIN",
    "setup_max_buffer_pct": "VIBEIC_PRR_SETUP_MAX_BUFFER_PCT",
    "hold_max_buffer_pct": "VIBEIC_PRR_HOLD_MAX_BUFFER_PCT",
    "repair_tns_pct": "VIBEIC_PRR_SETUP_REPAIR_TNS_PCT",
    "bounded_drive_strength": "VIBEIC_PRR_BOUNDED_DRIVE_STRENGTH",
    "cap_margin_pct": "VIBEIC_PRR_CAP_MARGIN_PCT",
}

#: `measure` exits with this when the adopted state cannot answer; the
#: registry declares it UNDETERMINED, so it is NOT_MEASURED, never a number.
RC_UNDETERMINED = 3


def mode(project: Path) -> str:
    """The contract switch for step 32."""
    import librelane_contract as _ll
    return _ll.selected_mode(project, STEP)


def refusal(selected: str, route_mode: str = "direct") -> Optional[str]:
    """Why a step-32 selection cannot run, or None. `dual` needs step 21 on
    LibreLane: its second arm is the pre-detailed-route repair
    (RepairDesignPostGRT + ResizerTimingPostGRT) inside step 21's chain."""
    if selected == "dual" and route_mode == "direct":
        return ("LL_PRR_DUAL_NEEDS_LL21: step 32's second tool path is the "
                "pre-detailed-route repair inside step 21's LibreLane chain; "
                "select 21 `librelane` or `dual`, or 32 `librelane`")
    return None


# --- the fork capability -------------------------------------------------------

#: Our own markers around the two probe answers (not a tool grammar).
_PROBE_REAL = "VIBEIC_PRR_PROBE_REAL:"
_PROBE_CTRL = "VIBEIC_PRR_PROBE_CTRL:"
_REAL_FLAG = "-detailed_routing"
_CTRL_FLAG = "-vibeic_probe_unknown_control_flag"


def flag_accepted_vs_control(transcript: str) -> Optional[bool]:
    """Did `estimate_parasitics` treat the real flag differently from a flag
    we know is invalid? True/False, or None when either answer is absent.

    No diagnostic wording is read: an OpenROAD that does not know the flag
    answers the real flag exactly as it answers the bogus one (the flag name
    aside), whatever that answer says."""
    answers: Dict[str, str] = {}
    for line in transcript.splitlines():
        for key in (_PROBE_REAL, _PROBE_CTRL):
            at = line.find(key)
            if at >= 0:
                answers[key] = line[at + len(key):].strip()
    if len(answers) != 2:
        return None
    return (answers[_PROBE_REAL]
            != answers[_PROBE_CTRL].replace(_CTRL_FLAG, _REAL_FLAG))


def fork_capability(image: str, docker: str = "docker") -> Dict[str, Any]:
    """Probe the image's OpenROAD for the fork's `-detailed_routing` flag."""
    tcl = (f"if {{[catch {{estimate_parasitics {_REAL_FLAG}}} e]}} "
           f"{{ puts \"{_PROBE_REAL} $e\" }} else {{ puts \"{_PROBE_REAL} <accepted>\" }}\n"
           f"if {{[catch {{estimate_parasitics {_CTRL_FLAG}}} e]}} "
           f"{{ puts \"{_PROBE_CTRL} $e\" }} else {{ puts \"{_PROBE_CTRL} <accepted>\" }}\n")
    import librelane_contract as _ll
    network, command = _ll.native_tool_command(image, [
        "bash", "-c", "set -o pipefail; printf '%s' \"$1\" | openroad -no_init "
        "-no_splash -exit /dev/stdin 2>&1", "vibeic-probe", tcl])
    cmd = [docker, "run", "--rm", "--network", network, *_dmem.docker_memory_flags(),
           image, "--skip", *command]
    try:
        from librelane_contract import PROBE_DEADLINE_S
        done = _ll.run_container(cmd, probe_deadline_s=PROBE_DEADLINE_S)
        transcript = (done.stdout or "") + "\n" + (done.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return {"capable": None, "image": image,
                "code": "LL_PRR_PROBE_UNAVAILABLE",
                "reason": f"probe could not run: {exc}"}
    except RuntimeError as exc:
        # run_container reports an expired probe deadline as Refusal, which
        # inherits RuntimeError. Capability then remains unmeasured; a probe
        # timeout cannot establish that the image lacks this fork feature.
        if getattr(exc, "code", None) != "LL_TOOL_DEADLINE":
            raise
        return {"capable": None, "image": image,
                "code": "LL_TOOL_DEADLINE", "reason": str(exc)}
    capable = flag_accepted_vs_control(transcript)
    result = {"capable": capable, "image": image,
              "transcript_tail": transcript.strip()[-600:]}
    if capable is None:
        result.update(code="LL_PRR_CAPABILITY_INCONCLUSIVE",
                      reason="fork capability probe transcript was inconclusive")
    return result


# --- measurement ---------------------------------------------------------------

def _load(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text())


def summarize(metrics: Dict[str, Any], corners: Sequence[str]) -> Dict[str, Any]:
    """Worst slack and design-rule counts over EVERY declared STA corner, from
    `OpenROAD.STAPostPNR`'s own per-corner metrics. A corner the step did not
    report leaves the summary unmeasured (`None`), never optimistic."""
    def per_corner(prefix: str) -> Dict[str, Any]:
        return {c: metrics.get(f"{prefix}__corner:{c}") for c in corners}

    setup = per_corner("timing__setup__ws")
    hold = per_corner("timing__hold__ws")
    drv = {kind: per_corner(f"design__max_{kind}_violation__count")
           for kind in ("slew", "cap", "fanout")}
    missing = sorted({c for c in corners
                      if not isinstance(setup[c], (int, float))
                      or not isinstance(hold[c], (int, float))
                      or any(not isinstance(drv[k][c], int) for k in drv)})
    out: Dict[str, Any] = {"corners": list(corners), "setup_ws": setup,
                           "hold_ws": hold, "drv": drv, "unmeasured_corners": missing}
    if missing or not corners:
        out.update(setup_ws_min=None, hold_ws_min=None, drv_count=None)
    else:
        out["setup_ws_min"] = min(float(v) for v in setup.values())
        out["hold_ws_min"] = min(float(v) for v in hold.values())
        out["drv_count"] = sum(int(v) for k in drv for v in drv[k].values())
    return out


def drv_pin_census(sta_folder: Path, summary: Dict[str, Any],
                   corners: Sequence[str],
                   classifier: Optional[Callable[..., str]] = None) -> Dict[str, Any]:
    """Bind distinct violating (pin, check) pairs to STAPostPNR's own logs.

    The State counters confirm that every table row was captured.  A missing
    log, count, or row makes admission unmeasured; counts alone cannot tell if
    the same pin moved between scenes or a new pin became a violator.
    """
    import sta_corner_record_completeness_check as _sta
    import librelane_contract as _ll
    pairs = set()
    sources = {}
    missing = [] if corners else ["no declared STA corners"]
    excluded: List[Dict[str, Any]] = []
    for corner in corners:
        log = sta_folder / corner / "sta.log"
        if not log.is_file():
            missing.append(f"{corner}: sta.log absent")
            continue
        body = log.read_text(errors="replace")
        parsed = _sta.extract_drv(body)
        sources[corner] = {"path": str(log), "sha256": _ll.digest(log)}
        for kind, title in (("slew", "max_slew"), ("cap", "max_capacitance"),
                            ("fanout", "max_fanout")):
            expected = ((summary.get("drv") or {}).get(kind) or {}).get(corner)
            pins = (parsed.get("pin_rows") or {}).get(title) or []
            marker = re.search(rf"^max {kind} violation count (\d+)\s*$",
                               body, re.M | re.I)
            if (type(expected) is not int or expected < 0 or
                    marker is None or int(marker.group(1)) != expected or
                    len(pins) != expected or len(set(pins)) != expected):
                missing.append(f"{corner}: {kind} row/counter mismatch")
            elif classifier is None:
                pairs.update((pin, kind) for pin in pins)
            else:
                # The DRV standard's classes (R-0928-DRV-IC): a bond-pad port
                # and an IO-cell pin under the std-cell margin are listed, not
                # counted; everything else counts. Proof comes from the run's
                # complete source-bound OpenSTA census and IO Liberty.
                values = (parsed.get("pin_values") or {}).get(title) or []
                if [v.get("pin") for v in values] != pins:
                    missing.append(f"{corner}: {kind} row values unreadable")
                    continue
                for row in values:
                    try:
                        cls = classifier(corner, title, row["pin"],
                                         row.get("limit"), row.get("value"))
                    except Exception as exc:  # noqa: BLE001 — never a silent exclusion
                        missing.append(f"{corner}: {kind} row class unmeasured: {exc}")
                        continue
                    if cls == "DRV":
                        pairs.add((row["pin"], kind))
                    else:
                        excluded.append({"corner": corner, "check": kind,
                                         "class": cls, **row})
    return {"drv_pin_checks_state": "NOT_MEASURED" if missing else "PASS",
            "drv_pin_checks": None if missing else [list(pair) for pair in sorted(pairs)],
            "drv_pin_checks_missing": missing,
            "drv_pin_checks_excluded": excluded,
            "drv_pin_checks_connectivity": (getattr(getattr(classifier, "__self__", None),
                                                   "connectivity_evidence", None)),
            "drv_pin_checks_sources": sources}


def fanout_residue(measurement: Dict[str, Any], corners: Sequence[str]) -> Dict[str, Any]:
    """BLOCKING: judge routed fanout from STAPostPNR's separate corner runs.

    The repair session is multi-corner; its OpenSTA fanout counter has crashed
    inside CheckFanouts.  STAPostPNR owns a fresh, single-corner process for
    each declared corner.  A missing count is never interpreted as zero.
    """
    if measurement.get("drv_pin_checks_state") == "NOT_MEASURED":
        return {"verdict": "NOT_MEASURED", "violations": None,
                "reason": "STAPostPNR fanout pin census absent or inconsistent"}
    if measurement.get("drv_pin_checks_state") == "PASS":
        pairs = measurement.get("drv_pin_checks") or []
        count = sum(check == "fanout" for _, check in pairs)
        return {"verdict": "FAIL" if count else "PASS", "violations": count,
                "source": "distinct (pin, check) across STAPostPNR scenes"}
    values = (measurement.get("drv") or {}).get("fanout") or {}
    missing = [c for c in corners if not isinstance(values.get(c), int)
               or isinstance(values.get(c), bool) or values[c] < 0]
    if not corners or missing:
        return {"verdict": "NOT_MEASURED", "violations": None,
                "reason": f"STAPostPNR fanout count absent in corners: {missing or ['<none declared>']}"}
    count = sum(values[c] for c in corners)
    return {"verdict": "FAIL" if count else "PASS", "violations": count,
            "source": "OpenROAD.STAPostPNR per-corner routed State metrics"}


def _set_final_fanout_verdict(report: Dict[str, Any]) -> None:
    """Repair-actuator fanout filter, not the IC DRV sign-off verdict."""
    fanout = fanout_residue(report.get("final") or {}, report.get("corners") or [])
    report["final_fanout"] = fanout
    report["verdict"] = fanout["verdict"]
    report["verdict_scope"] = "repair_candidate_fanout_only"
    if fanout["verdict"] != "PASS":
        report["code"] = ("LL_PRR_FANOUT_VIOLATION" if fanout["verdict"] == "FAIL"
                          else "LL_PRR_FANOUT_NOT_MEASURED")
        report["reason"] = (f"declared postroute max fanout has "
                            f"{fanout['violations']} residual violations"
            if fanout["verdict"] == "FAIL" else fanout["reason"])


def _set_final_drv_verdict(report: Dict[str, Any]) -> None:
    count = (report.get("final") or {}).get("drv_count")
    valid = type(count) is int and count >= 0
    report["final_drv"] = {"verdict": ("NOT_MEASURED" if not valid else
                                       "FAIL" if count else "PASS"),
                           "violations": count if valid else None}
    if not valid:
        report.update(verdict="NOT_MEASURED", code="LL_PRR_DRV_NOT_MEASURED",
                      reason="final routed DRV pin/check census is unmeasured")
    elif count and report["verdict"] == "PASS":
        report.update(verdict="FAIL", code="LL_PRR_DRV_VIOLATION",
                      reason=f"declared postroute DRV has {count} residual pin/check violations")


def _step32_drv_signoff(project: Path, report: Dict[str, Any]) -> None:
    """Rejudge the final candidate with the one DRV judge after late repair.

    A missing or stale bundle is named NOT_MEASURED.  The repair actuator's
    own verdict remains a candidate-selection record, never sign-off evidence.
    """
    import drv_signoff_judge as _drv
    import drv_capture_plan as _drv_plan
    source = project / "reports/phase3/sta/drv_signoff_bundle.json"
    result: Dict[str, Any]
    try:
        # The candidate's own final STA state is available before this step's
        # report is published. Capture from it; an older bundle cannot grade
        # a newly adopted layout.
        source.unlink(missing_ok=True)
        if not report.get("final", {}).get("sta_state"):
            raise ValueError("final STAPostPNR state absent")
        # The sign-off STA and post-route repair receipts are the final
        # state's, not whichever candidate's chain happened to run last.
        import drv_stage_receipts as _drv_stages
        _drv_stages.record_step32(project, report)
        _drv_plan.capture_and_publish(project, final_state=report)
        bundle = json.loads(source.read_text())
        result = _drv.judge(bundle, project=project)
        state_path = report.get("adopted_state")
        state = _load(Path(state_path)) if state_path else {}
        final = _drv.def_identity(
            bundle, Path(str(state["def"])) if state.get("def") else None)
        if final is not None:
            result.setdefault("not_measured", []).append(
                f"step 32 final routed DEF {'absent' if final == 'absent' else 'differs from judged layout identity'}")
            result["verdict"] = ("FAIL" if result.get("failures") else
                                 "NOT_MEASURED")
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        result = {"name": "DRV(tran/cap/fanout)", "verdict": "NOT_MEASURED",
                  "not_measured": [f"step 32 DRV evidence unavailable: {exc}"]}
    report["drv_signoff"] = result
    # R-0929-DRV-IDENTITY / R-0929-STEP32-ADOPT: the DRV judgement is Step
    # 32's own verdict (residual DRV keeps the step FAIL), recorded apart from
    # the actuator verdict.  It never gates the handoff of the adopted
    # candidate and never makes the pre-repair route ship; the sign-off DRV
    # verdict of the handed-off route is the step-23 / pre-stream capture's.
    report["drv_signoff_verdict"] = result["verdict"] if source.is_file() else "NOT_MEASURED"
    output = project / "reports/phase3/sta/drv_signoff_step32.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, result)


def _drv_classifier(ctx: Dict[str, Any], sta_folder: Path) -> Optional[Callable[..., str]]:
    """The DRV standard's row classes for a run whose STA links IO Liberty
    (PAD_LIBS): None for a padless run, where every row is a std-cell row.
    An unreadable netlist or IO Liberty yields a classifier that raises, so
    the census is NOT_MEASURED rather than silently counting or excluding."""
    import _drv_row_class as _cls
    try:
        cfg = _load(sta_folder / "config.json")
    except (OSError, ValueError):
        return None
    pad_libs = cfg.get("PAD_LIBS")
    if not pad_libs:
        return None
    try:
        netlist = _host_path(ctx, str(_load(sta_folder / "state_in.json")["nl"]))
        libs = {c: [_host_path(ctx, p) for p in paths] for c, paths in
                _cls.pad_libs_by_corner(pad_libs, ctx["corners"]).items()}
        sdc = cfg.get("SIGNOFF_SDC_FILE")
        margin = (_cls.sdc_cap_margin(_host_path(ctx, str(sdc)).read_text())
                  if sdc else None)
        return _cls.Classifier(netlist, libs, margin,
                               project=Path(ctx["project"]) if ctx.get("project") else None,
                               sdc=_host_path(ctx, str(sdc)) if sdc else None).classify
    except (OSError, ValueError, KeyError, TypeError, _cls.Unavailable) as exc:
        reason = f"{type(exc).__name__}: {exc}"

        def unavailable(*_args: Any) -> str:
            raise _cls.Unavailable(reason)
        return unavailable


def _candidate(ctx: Dict[str, Any], config: Path, state: Path,
               lane: str) -> Tuple[Path, Dict[str, Any]]:
    """The repair step (a candidate, or the census) then RCX + STAPostPNR:
    the repair step's folder and the measurement of what it handed on."""
    import librelane_contract as _ll
    project = Path(ctx["project"])
    folders = _ll.run_chain(
        project, ctx["image"],
        [(REPAIR_STEP, config, state)]
        + [(step, Path(ctx["configs"][step]), state) for step in MEASURE_STEPS],
        mounts=[(Path(h), g) for h, g in ctx["mounts"]],
        lane=lane, pdk_root=_ll.PDK_GUEST_ROOT)
    import excluded_master_census_check as _emc
    excluded_census = _emc.write_audit(
        config, folders[0] / "state_out.json", REPAIR_STEP,
        folders[0] / "excluded_master_census.json")
    sta_state = folders[-1] / "state_out.json"
    summary = summarize(_load(sta_state).get("metrics") or {}, ctx["corners"])
    pin_census = drv_pin_census(folders[-1], summary, ctx["corners"],
                                classifier=_drv_classifier(ctx, folders[-1]))
    summary.update(pin_census)
    summary["drv_count"] = (len(pin_census["drv_pin_checks"])
                            if pin_census["drv_pin_checks_state"] == "PASS" else None)
    # The closure's timing.drv collateral compares these members (a list, or
    # None when the census could not be completed).
    summary["drv_members"] = pin_census["drv_pin_checks"]
    summary["drv_members_reason"] = "; ".join(pin_census["drv_pin_checks_missing"])
    # One extraction authority for this candidate and step 22: native RCX.
    # Keep signoff-scene STA until its AOCV/serialized-SDC HARVEST has a
    # merged destination, but consume these exact SPEFs without re-extracting.
    import _native_postroute_timing as _native
    rcx_state = folders[2] / "state_out.json"
    native_ctx = {**ctx, "rcx_state": str(rcx_state),
                  "rcx_state_sha256": _ll.digest(rcx_state)}
    native = _native.measure(native_ctx, folders[0] / "state_out.json",
                             folders[0] / "native_signoff")
    antenna = antenna_census(folders[1])
    return folders[0], {"sta_state": str(sta_state),
                        "sta_state_sha256": _ll.digest(sta_state),
                        "librelane_setup_ws": summary["setup_ws"],
                        "librelane_hold_ws": summary["hold_ws"],
                        **summary, **native,
                        "excluded_master_census": excluded_census,
                        "antenna_nets": antenna["antenna__violating__nets"],
                        "antenna_pins": antenna["antenna__violating__pins"],
                        "antenna_state": str(folders[1] / "state_out.json")}


def antenna_census(folder: Path) -> Dict[str, Optional[int]]:
    """`OpenROAD.CheckAntennas`' own counts from its step folder (the step-26
    router-model instrument); a count the step did not write is None."""
    metrics = _load(folder / "state_out.json").get("metrics") or {}
    return {k: (metrics.get(k) if isinstance(metrics.get(k), int)
                and not isinstance(metrics.get(k), bool) else None)
            for k in ANTENNA_METRICS}


def _antenna_counts(measurement: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """Both step-26 dimensions must be measured nonnegative integer counts."""
    nets, pins = (measurement.get("antenna_nets"),
                  measurement.get("antenna_pins"))
    if any(type(v) is not int or v < 0 for v in (nets, pins)):
        return None
    return nets, pins


def _has_sta_digest(measurement: Dict[str, Any]) -> bool:
    value = measurement.get("sta_state_sha256")
    return (isinstance(value, str) and len(value) == 64 and
            all(c in "0123456789abcdef" for c in value))


DOMAIN_VALUE = {
    "setup": lambda cur: cur["measurement"].get("setup_ws_min"),
    "hold": lambda cur: cur["measurement"].get("hold_ws_min"),
    "drv": lambda cur: cur["measurement"].get("drv_count"),
    "antenna": lambda cur: cur["measurement"].get("antenna_nets"),
}


def measured_repair_trigger(measurement: Dict[str, Any]) -> Dict[str, Any]:
    """Start a late repair only for a violation measured on its input route."""
    needed = ("setup_ws_min", "hold_ws_min", "drv_count")
    missing = []
    for key in needed:
        value = measurement.get(key)
        if key == "drv_count":
            valid = isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else:
            valid = (isinstance(value, (int, float))
                     and not isinstance(value, bool) and math.isfinite(value))
        if not valid:
            missing.append(key)
    violated = [key for key in needed if key not in missing and
                (measurement[key] > 0 if key == "drv_count"
                 else measurement[key] < 0)]
    action = ("RUN" if violated else "NOT_MEASURED" if missing else "SKIP")
    return {"action": action, "basis": "input route STAPostPNR per-corner metrics",
            "violated": violated, "missing": missing,
            "values": {key: measurement.get(key) for key in needed}}


def trigger_disclosure(trigger: Dict[str, Any]) -> str:
    """One line naming what the repair trigger measured and decided."""
    values = trigger.get("values") or {}
    return (f"repair trigger {trigger.get('action')} on {trigger.get('basis')}: "
            f"violated={', '.join(trigger.get('violated') or []) or 'none'}; "
            f"missing={', '.join(trigger.get('missing') or []) or 'none'}; "
            "values " + ", ".join(f"{k}={values.get(k)!r}" for k in sorted(values)))


def _stamp_verdict(report: Dict[str, Any]) -> None:
    """PASS only when the trigger measured its input. A NOT_MEASURED trigger
    ran no closure because it could not tell a clean route from a violated
    one, and that is reported as such -- not as a repair step that passed."""
    baseline = report.get("input_baseline") or report.get("baseline") or {}
    _set_census_verdict(report, baseline, report.get("final") or {})
    trigger = report.get("repair_trigger") or {}
    if trigger.get("action") == "NOT_MEASURED":
        reason = (trigger_disclosure(trigger) + " -- the input route's census "
                  "did not measure every metric the trigger needs, so the "
                  "closure did not run and the input route was kept")
        prior = report.get("reason") if report["verdict"] != "PASS" else None
        report.update(verdict="NOT_MEASURED", code="LL_PRR_TRIGGER_NOT_MEASURED",
                      reason="; ".join(filter(None, (reason, prior))))


def measure(impl: Path, domain: str, json_out: Path) -> int:
    """The closure's measurement: one number about the ADOPTED candidate."""
    import librelane_contract as _ll
    try:
        cur = _load(impl / CURRENT)
        sta = Path(cur["measurement"]["sta_state"])
        if _ll.digest(sta) != cur["measurement"]["sta_state_sha256"]:
            print(f"{sta}: not the state {CURRENT} adopted", file=sys.stderr)
            return RC_UNDETERMINED
        native_hash = cur["measurement"].get("native_odb_sha256")
        if native_hash is not None:
            odb = Path(_load(Path(cur["repair_state"]))["odb"])
            if _ll.digest(odb) != native_hash:
                print(f"{odb}: not the ODB native timing measured", file=sys.stderr)
                return RC_UNDETERMINED
    except (OSError, ValueError, KeyError) as exc:
        print(f"no adopted candidate to measure: {exc}", file=sys.stderr)
        return RC_UNDETERMINED
    value = DOMAIN_VALUE[domain](cur)
    if domain == "drv" and not isinstance(cur["measurement"].get("drv_members"), list):
        print(f"drv: distinct violating members NOT_MEASURED: "
              f"{cur['measurement'].get('drv_members_reason')}", file=sys.stderr)
        return RC_UNDETERMINED
    if value is None:
        print(f"{domain}: the adopted candidate does not carry it", file=sys.stderr)
        return RC_UNDETERMINED
    doc = {"domain": domain, "value": value, "candidate": cur.get("candidate"),
           "sta_state": str(sta)}
    if domain == "drv":
        doc["violating_members"] = cur["measurement"]["drv_members"]
    try:
        floor = (_load(impl / CONTEXT).get("floors") or {}).get(domain)
    except (OSError, ValueError):
        floor = None
    if floor:
        doc["floor"], doc["floor_source"] = floor
    write_json(json_out, doc)
    return 0


# --- the actuator ---------------------------------------------------------------

def _ledger_path(impl: Path) -> Path:
    return impl.parent / LEDGER


def _ledger_append(impl: Path, row: Dict[str, Any]) -> None:
    path = _ledger_path(impl)
    rows = _load(path)["candidates"] if path.is_file() else []
    rows.append(row)
    write_json(path, {"candidates": rows})


#: The repair step's own named candidate refusals (postroute_repair.tcl: the
#: scoped route, the lost route, the fanout limit, check_placement): the step
#: measured THIS candidate and said no. Each ends the step with exit 1 after
#: printing the line, so run_chain books it LL_STEP_FAILED exactly like a
#: crash; the line, which the step itself prints, is what tells them apart.
_STEP_REFUSAL = re.compile(r"^(?:(?:VIBEIC_)?PRR_[A-Z_]+_(?:REFUSED|RESIDUE):|"
                           r"LL_PRR_FANOUT_LIMIT_BROKEN:)")
_CRASH_SIGNATURE = re.compile(r"\bSignal\s+\d+\b|\bSIGSEGV\b|Segmentation fault")


def _actuator_failure(exc: Exception) -> Dict[str, Any]:
    """Book one refused candidate from the step's failure.

    A crash signature (a signal line), a refusal that is not a step failure
    (a stall, a missing state), or a step failure with no named refusal is a
    native failure: ACTUATOR_FAILED, NOT_MEASURED. A step failure whose log
    carries one of the step's own named refusals, and no crash, is the tool's
    measured "no" for this candidate: TOOL_REFUSED, the pointer stays and the
    controller goes on to its next rung.
    """
    reason = str(exc)
    match = re.search(r"(/[^;\s]+/invocation\.log)", reason)
    signature = refusal = None
    if match:
        try:
            for line in Path(match.group(1)).read_text(errors="replace").splitlines():
                if _CRASH_SIGNATURE.search(line):
                    signature = line.strip()[:500]
                elif refusal is None and _STEP_REFUSAL.match(line.strip()):
                    refusal = line.strip()[:500]
        except OSError:
            pass
    if (getattr(exc, "code", None) == "LL_STEP_FAILED" and refusal is not None
            and signature is None and not re.search(r"\brc=-\d+", reason)):
        return {"decision": "TOOL_REFUSED", "measurement_status": "MEASURED",
                "reason": reason, "tool_refusal": refusal}
    return {"decision": "ACTUATOR_FAILED", "measurement_status": "NOT_MEASURED",
            "reason": reason, "tool_crash_signature": signature}


def _host_path(ctx: Dict[str, Any], value: str) -> Path:
    """A config path as the host sees it (the PDK is mounted at a guest path)."""
    for host, guest in ctx["mounts"]:
        if value.startswith(guest.rstrip("/") + "/"):
            return Path(host) / value[len(guest.rstrip("/")) + 1:]
    return Path(value)


def supply_ownership(ctx: Dict[str, Any], def_path: Path) -> Dict[str, Any]:
    """F24: every supply pin of every instance of the candidate DEF on a
    declared supply net of its kind (`pg_supply_pin_ownership_check`)."""
    import pg_supply_pin_ownership_check as _pgo
    cfg = _load(Path(ctx["configs"][REPAIR_STEP]))
    lefs = [_host_path(ctx, str(p)) for key in ("CELL_LEFS", "PAD_LEFS",
                                                  "MACRO_LEFS", "EXTRA_LEFS")
            for p in (cfg.get(key) or [])]
    try:
        return _pgo.judge_files(def_path, [p for p in lefs if p.is_file()])
    except Exception as exc:  # noqa: BLE001 — recorded, never read as clean
        return {"gate": _pgo.GATE, "verdict": "NOT_MEASURED",
                "code": _pgo.UNMEASURED_CODE, "reason": f"{type(exc).__name__}: {exc}"}


def actuate(impl: Path, params: Dict[str, Any]) -> int:
    """One candidate from the ADOPTED state, measured; adopted only as far as
    the pointer goes — the closure decides whether it stays."""
    import librelane_contract as _ll
    ctx = _load(impl / CONTEXT)
    cur = _load(impl / CURRENT)
    project = Path(ctx["project"])
    ledger = _load(_ledger_path(impl))["candidates"] if _ledger_path(impl).is_file() else []
    index = len(ledger) + 1
    lane = f"{ctx.get('lane', '32')}-cand{index:02d}"
    updates = {PARAM_VARS[k]: (v, f"actuator timing.repair_setup parameter {k}")
               for k, v in params.items() if v is not None}
    base_cfg = Path(ctx["configs"][REPAIR_STEP])
    cfg = _ll.derive_step_config(base_cfg, base_cfg.with_name(f"{REPAIR_STEP}@{lane}.json"),
                                 updates)
    row: Dict[str, Any] = {"candidate": lane, "params": params,
                           "from": cur.get("candidate"), "config": str(cfg)}
    try:
        folder, measurement = _candidate(ctx, cfg, Path(cur["repair_input"]), lane)
        repaired = folder / "state_out.json"
    except _ll.Refusal as exc:
        row.update(_actuator_failure(exc))
        _ledger_append(impl, row)
        if row["decision"] == "TOOL_REFUSED":
            # The tool refused THIS candidate (e.g. the fork's scoped route
            # refuses a route that adds a whole-design violation, DRT-0712). The
            # pointer stays on the adopted state, so the controller sees no
            # improvement and moves to the next rung; the reason is in the ledger.
            print(f"candidate {lane}: {row['tool_refusal']}")
            return 0
        if exc.code != "LL_STEP_FAILED":
            print(f"candidate {lane}: {row['reason']}", file=sys.stderr)
            return 2
        # One bounded retry changes the operation order while retaining every
        # limit, margin and candidate acceptance rule. Failed invocations do
        # not spend the controller's measured-iteration budget.
        lane = f"{lane}-retry"
        retry_updates = dict(updates)
        retry_updates["VIBEIC_PRR_MOVE_SEQUENCE"] = (
            "hold_first", "one retry after a native actuator failure")
        cfg = _ll.derive_step_config(
            base_cfg, base_cfg.with_name(f"{REPAIR_STEP}@{lane}.json"), retry_updates)
        row = {"candidate": lane, "retry_of": f"{ctx.get('lane', '32')}-cand{index:02d}",
               "params": params, "from": cur.get("candidate"), "config": str(cfg),
               "move_sequence": "hold_first"}
        try:
            folder, measurement = _candidate(ctx, cfg, Path(cur["repair_input"]), lane)
            repaired = folder / "state_out.json"
        except _ll.Refusal as retry_exc:
            row.update(_actuator_failure(retry_exc))
            _ledger_append(impl, row)
            print(f"candidate {lane}: {row['reason']}", file=sys.stderr)
            return 2
    state = _load(repaired)
    metrics = state.get("metrics") or {}
    row.update(repair_state=str(repaired), measurement=measurement,
               repair_metrics={k: v for k, v in metrics.items()
                               if k.startswith("vibeic__prr__")})
    # Existing published cells have not yet had the corpus sweep required to
    # promote aggregate DRV to a candidate admission rule. Record its exact
    # verdict; Step 23 still judges the final route.
    drv_count = measurement.get("drv_count")
    row["drv_advisory"] = {
        "verdict": ("NOT_MEASURED" if not isinstance(drv_count, int)
                    or isinstance(drv_count, bool) else
                    "PASS" if drv_count == 0 else "FAIL"),
        "severity": "ADVISORY", "count": drv_count,
        "basis": "candidate STAPostPNR under sign-off SDC"}
    # Residual fanout is a final Step-32 failure, not a reason to discard a
    # measured improvement.  Admission rejects missing or regressing DRV.
    row["fanout"] = fanout_residue(measurement, ctx["corners"])
    before = cur.get("measurement") or {}
    old_pin_state = before.get("drv_pin_checks_state")
    new_pin_state = measurement.get("drv_pin_checks_state")
    if "NOT_MEASURED" in (old_pin_state, new_pin_state) or (
            "PASS" in (old_pin_state, new_pin_state) and
            old_pin_state != new_pin_state):
        row.update(decision="REFUSED", reason="routed DRV pin census unmeasured")
        _ledger_append(impl, row)
        return 0
    if old_pin_state == new_pin_state == "PASS":
        old_pairs = {tuple(pair) for pair in before["drv_pin_checks"]}
        new_pairs = {tuple(pair) for pair in measurement["drv_pin_checks"]}
        added = sorted(new_pairs - old_pairs)
        row["drv_pin_comparison"] = {"added": added,
                                      "removed": sorted(old_pairs - new_pairs)}
        if added:
            row.update(decision="REFUSED", reason=f"new routed DRV (pin, check): {added}")
            _ledger_append(impl, row)
            return 0
    drv_regressions = []
    drv_missing = []
    for kind in ("slew", "cap", "fanout"):
        for corner in ctx["corners"]:
            old = ((before.get("drv") or {}).get(kind) or {}).get(corner)
            new = ((measurement.get("drv") or {}).get(kind) or {}).get(corner)
            if (type(old) is not int or old < 0 or
                    type(new) is not int or new < 0):
                drv_missing.append((kind, corner))
            elif new > old and old_pin_state != "PASS":
                # When the producer supplied pin identities, the union of
                # (pin, check) pairs above is the admission rule.  The same
                # violator appearing in a second scene is not a new check.
                drv_regressions.append((kind, corner, old, new))
    row["drv_comparison"] = {"missing": drv_missing,
                             "regressions": drv_regressions}
    if drv_missing or drv_regressions:
        row.update(decision="REFUSED", reason=(
            f"routed DRV unmeasured: {drv_missing}" if drv_missing else
            f"routed DRV regressed: {drv_regressions}"))
        _ledger_append(impl, row)
        print(f"candidate {lane} refused: {row['reason']}")
        return 0
    pg = (supply_ownership(ctx, Path(state["def"]))
          if metrics.get("vibeic__prr__changed") != 0 else
          {"verdict": "NOT_APPLICABLE", "reason": "no instance changed; the input DEF"})
    row["supply_ownership"] = {k: pg.get(k) for k in ("verdict", "code", "reason")}
    if pg.get("verdict") == "FAIL":
        row.update(decision="REFUSED", reason=f"supply ownership: {pg.get('reason')}")
        _ledger_append(impl, row)
        print(f"candidate {lane} refused: {row['reason']}")
        return 0
    # Antenna, by the step-26 instrument, on the candidate and on what it was
    # built from: a candidate that creates an antenna violation (or cannot be
    # counted) never moves the pointer, whatever it did for timing or DRV.
    row["antenna"] = {"before": before.get("antenna_nets"),
                      "after": measurement.get("antenna_nets"),
                      "before_pins": before.get("antenna_pins"),
                      "after_pins": measurement.get("antenna_pins")}
    before_counts = _antenna_counts(before)
    after_counts = _antenna_counts(measurement)
    if (before_counts is None or after_counts is None or
            any(a > b for b, a in zip(before_counts, after_counts))):
        row.update(decision="REFUSED",
                   reason=("antenna (OpenROAD.CheckAntennas): violating "
                           f"nets {row['antenna']['before']} -> {row['antenna']['after']}; "
                           f"pins {row['antenna']['before_pins']} -> "
                           f"{row['antenna']['after_pins']}"))
        _ledger_append(impl, row)
        print(f"candidate {lane} refused: {row['reason']}")
        return 0
    route_before = metrics.get("vibeic__prr__before__unrouted__count")
    route_after = metrics.get("vibeic__prr__after__unrouted__count")
    route_added = metrics.get("vibeic__prr__unrouted__added")
    row["route_census"] = {"before": route_before, "after": route_after,
                           "added": route_added,
                           "source": str(repaired)}
    if (any(type(v) is not int or v < 0 for v in
            (route_before, route_after, route_added)) or
            route_added != max(0, route_after - route_before)):
        row.update(decision="REFUSED", reason="repair route census unmeasured or inconsistent")
        _ledger_append(impl, row)
        return 0
    if route_added:
        row.update(decision="REFUSED", reason=f"repair added {route_added} unrouted nets")
        _ledger_append(impl, row)
        return 0
    # A candidate with no measured improvement has no objective to promote;
    # do not pass a pure slack loss to the controller as a proposed repair.
    if (measurement.get("drv_count") == before.get("drv_count") and
            measurement.get("setup_ws_min") is not None and
            measurement.get("hold_ws_min") is not None and
            before.get("setup_ws_min") is not None and
            before.get("hold_ws_min") is not None and
            measurement["setup_ws_min"] <= before["setup_ws_min"] and
            measurement["hold_ws_min"] <= before["hold_ws_min"] and
            after_counts == before_counts and route_after == route_before):
        row.update(decision="REFUSED", reason="no measured timing, DRV, antenna, or route improvement")
        _ledger_append(impl, row)
        print(f"candidate {lane} refused: {row['reason']}")
        return 0
    # An unmeasured DRV census cannot be promoted. Measured residue remains a
    # step failure, but the closure may adopt a strictly improving route and
    # must not keep a worse input solely because both routes still have DRV.
    drv = measurement.get("drv_count")
    if type(drv) is not int:
        row.update(decision="REFUSED",
                   reason=("post-route DRV was not measured "
                           f"(OpenROAD.STAPostPNR count={drv!r})"))
        _ledger_append(impl, row)
        print(f"candidate {lane} refused: {row['reason']}")
        return 0
    write_json(impl / CURRENT, {
        "candidate": lane, "repair_input": str(repaired),
        "repair_state": str(repaired), "repair_folder": str(folder),
        "measurement": measurement,
        "supply_ownership": row["supply_ownership"]})
    row.update(decision="PROPOSED")
    _ledger_append(impl, row)
    print(f"candidate {lane}: setup {measurement.get('setup_ws_min')} "
          f"hold {measurement.get('hold_ws_min')} drv {measurement.get('drv_count')}")
    return 0


# --- the step --------------------------------------------------------------------

def signoff_scene_sdc(sdc: Path, out: Path, derate_early: float,
                      derate_late: float) -> Path:
    """The deck's SDC plus the sign-off STA's flat-OCV derate: the repair
    scene is the sign-off scene (T98's lesson: a repair that does not see the
    sign-off's derate cannot close the sign-off's hold)."""
    from _atomic_artefact import write_text
    write_text(out, sdc.read_text(errors="replace").rstrip("\n") + "\n"
               "# vibe-ic T102: the sign-off STA's flat OCV\n"
               f"set_timing_derate -early {derate_early}\n"
               f"set_timing_derate -late {derate_late}\n")
    return out


#: The spec's declared timing margins (structured L-doc fields, ns).
SPEC_MARGIN_KEYS = {"setup": ("setup_margin_ns",), "hold": ("hold_margin_ns",)}
SPEC_MARGIN_LDOCS = ("L8_TIMING_WAVEFORM.json", "L19_CONSTRAINTS_PDK.json")


def _walk_numbers(node: Any, keys: Sequence[str]) -> List[float]:
    found: List[float] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in keys and isinstance(v, (int, float)) and not isinstance(v, bool):
                found.append(float(v))
            else:
                found.extend(_walk_numbers(v, keys))
    elif isinstance(node, list):
        for v in node:
            found.extend(_walk_numbers(v, keys))
    return found


def sdc_clock_uncertainty(sdc_text: str) -> Dict[str, List[float]]:
    """`set_clock_uncertainty` values the SDC declares, by check. A command
    with neither -setup nor -hold applies to both (the SDC standard)."""
    out: Dict[str, List[float]] = {"setup": [], "hold": []}
    for line in sdc_text.splitlines():
        words = line.split("#", 1)[0].split()
        if not words or words[0] != "set_clock_uncertainty":
            continue
        value = None
        for word in words[1:]:
            try:
                value = float(word)
                break
            except ValueError:
                continue
        if value is None:
            continue
        checks = [c for c in ("setup", "hold") if f"-{c}" in words[1:]] or ["setup", "hold"]
        for check in checks:
            out[check].append(value)
    return out


def declared_timing_floor(project: Path, sdc: Path) -> Dict[str, Tuple[float, str]]:
    """The floor a HARD-violation repair may spend setup/hold slack down to,
    from the design's DECLARED inputs only (owner ruling, T102 r3): the spec's
    declared margin, else the SDC's own clock uncertainty, else 0 (WNS >= 0 on
    the sign-off scene). Never a typed number."""
    docs = project / "phase1/generated_docs"
    floors: Dict[str, Tuple[float, str]] = {}
    try:
        unc = sdc_clock_uncertainty(sdc.read_text(errors="replace"))
    except OSError:
        unc = {"setup": [], "hold": []}
    for check, keys in SPEC_MARGIN_KEYS.items():
        spec = []
        for name in SPEC_MARGIN_LDOCS:
            path = docs / name
            try:
                spec += [(v, f"{name} {'/'.join(keys)}")
                         for v in _walk_numbers(json.loads(path.read_text()), keys)]
            except (OSError, ValueError):
                continue
        if spec:
            floors[check] = max(spec)
        elif unc[check]:
            floors[check] = (max(unc[check]),
                             f"{sdc.name} set_clock_uncertainty ({check})")
        else:
            floors[check] = (0.0, "no declared margin or uncertainty: "
                                  "WNS >= 0 on the sign-off scene")
    return floors


def _refused_by_tool(report: Dict[str, Any], cap: Dict[str, Any], out: Path) -> bool:
    report["fork_capability"] = cap
    if cap.get("capable") is True:
        return False
    if cap.get("capable") is None:
        code = cap.get("code") or "LL_PRR_CAPABILITY_INCONCLUSIVE"
        report.update(verdict="NOT_MEASURED", code=code,
                      reason=cap.get("reason") or "fork capability probe did not answer",
                      reason_class=("inconclusive" if code == "LL_PRR_CAPABILITY_INCONCLUSIVE"
                                    else "execution_error"))
        write_json(out, report)
        return True
    report.update(verdict="NOT_MEASURED", code="LL_PRR_TOOL_INCAPABLE",
                  reason="the image's OpenROAD does not accept the fork's "
                         "estimate_parasitics -detailed_routing")
    write_json(out, report)
    return True


def repair_dont_use(config: Path, pdk_root: Path, pdk: str,
                    rule: Callable[[str], List[str]]) -> List[str]:
    """The cells this step's resizer may not insert: `rule` (the direct deck's
    dont_use families, supplied by the runner) over the step's own resolved
    CELL_LIBS, read through the PDK mount the step runs with.

    cmp3 D14, MEASURED on spm x gf180mcuD (32-cand01): with no exclusion,
    repair_design split high-fanout nets with `dlya_1`/`dlyb_1` delay cells
    (setup 5.15 -> 3.07 ns), and a second fanout round on a delay cell took
    setup to -0.015 ns. The direct deck and the LL placement chain exclude
    that family; step 32 now does too. A library the step names that cannot
    be read refuses: an exclusion computed over part of the library is not
    the exclusion. The PDK may give each corner a different Liberty file, so
    every corner's file is read; a step that declares no CELL_LIBS at all is
    an undeclared population and refuses (CR4), never an empty policy."""
    import librelane_contract as _ll
    doc = _load(config)
    libs = doc.get("LIB", doc.get("CELL_LIBS")) or {}
    paths = sorted({str(p) for v in (libs.values() if isinstance(libs, dict) else [libs])
                    for p in (v if isinstance(v, list) else [v])})
    if not paths:
        raise _ll.Refusal("LL_PRR_LIBERTY_UNDECLARED", str(config))
    guest = f"/pdk/{pdk}/"
    excluded: set = set()
    for value in paths:
        host = (pdk_root / pdk / value[len(guest):] if value.startswith(guest)
                else Path(value))
        try:
            excluded.update(rule(host.read_text(errors="replace")))
        except OSError as exc:
            raise _ll.Refusal("LL_PRR_LIBERTY_UNREADABLE",
                              f"{value} ({host}): {exc}") from exc
    return sorted(excluded)


def _prepare(project: Path, *, image: str, pdk: str, pdk_root: Path, sdc: Path,
             derate: Tuple[float, float], pg_rules_tcl: Optional[Path],
             refill_tcl: Optional[Path], docker: str,
             dont_use: Optional[Tuple[Callable[[str], List[str]], str]] = None,
             max_fanout: Optional[Tuple[int, str]] = None,
             ) -> Tuple[Dict[str, Path], List[str], List[Tuple[Path, str]]]:
    """The resolved configs (repair step + the three measuring steps) in the
    sign-off scene, the STA corners, and the PDK mount."""
    import librelane_contract as _ll
    folder = project / "phase3/librelane/32-config"
    scene = signoff_scene_sdc(sdc, folder / "signoff_scene.sdc", *derate)
    source = "the deck's SDC + the sign-off STA's flat-OCV derate"
    overlay = {"PNR_SDC_FILE": (str(scene.resolve()), source),
               "SIGNOFF_SDC_FILE": (str(scene.resolve()), source)}
    # T105: every LibreLane geometry step reads the tech LEF the route read
    # (the flow's via-legalized LEF, bound by sha256), never the PDK's own.
    # Here that is OpenROAD.RCX (DEF + RCX_LEF) and the direct-route bridge's
    # DEF -> ODB; an APPLIED record whose file is not found by its hash
    # refuses LL_ROUTE_TECH_LEF_UNBOUND.
    import librelane_pv_signoff as _pv
    overlay.update(_pv.tech_lef_overlay(project) or {})
    ids = [REPAIR_STEP, *MEASURE_STEPS]
    configs = _ll.resolve_step_configs(project, image, pdk, ids, pdk_root=pdk_root,
                                       folder="32-config", overlay=overlay, docker=docker)
    extra = {}
    if pg_rules_tcl is not None:
        extra["VIBEIC_PRR_PG_RULES_TCL"] = (str(pg_rules_tcl.resolve()),
                                            "the direct deck's add_global_connection rules")
    if refill_tcl is not None:
        extra["VIBEIC_PRR_REFILL_TCL"] = (str(refill_tcl.resolve()),
                                          "the direct deck's own filler policy")
    if max_fanout is not None:
        extra["VIBEIC_PRR_MAX_FANOUT"] = max_fanout
    if dont_use is not None:
        # CR4: EXTRA_EXCLUDED_CELLS is a set of forbidden masters, not a
        # replacement value -- the PDK/design exclusions the resolved config
        # already carries are kept, and the family rule is added to them.
        config = configs[REPAIR_STEP]
        inherited = _load(config).get("EXTRA_EXCLUDED_CELLS") or []
        if not isinstance(inherited, list) or any(
                not isinstance(name, str) for name in inherited):
            raise _ll.Refusal("LL_PRR_EXCLUSION_POLICY_INVALID", str(config))
        excluded = repair_dont_use(config, pdk_root, pdk, dont_use[0])
        source = dont_use[1]
        if not excluded:
            source += "; no cell matched in the resolved CELL_LIBS"
            print(f"LL_PRR_DONT_USE_EMPTY: {source}")
        if inherited:
            source += "; union with declared/PDK exclusions"
        extra["EXTRA_EXCLUDED_CELLS"] = (sorted(set(inherited) | set(excluded)), source)
    if extra:
        configs[REPAIR_STEP] = _ll.derive_step_config(configs[REPAIR_STEP],
                                                      configs[REPAIR_STEP], extra)
    corners = list(_load(configs["OpenROAD.STAPostPNR"]).get("STA_CORNERS") or [])
    return configs, corners, [(pdk_root.resolve(), _ll.PDK_GUEST_ROOT)]


def close_arm(project: Path, name: str, state0: Path, *, image: str, pdk: str,
              configs: Dict[str, Path], corners: List[str],
              mounts: List[Tuple[Path, str]], derate: Tuple[float, float],
              aocv_table: Optional[str] = None,
              controllers: Sequence[str] = CONTROLLERS,
              registry: Optional[Path] = None,
              programs_dir: Optional[Path] = None,
              floors: Optional[Dict[str, Tuple[float, str]]] = None) -> Dict[str, Any]:
    """One repair arm from `state0`: the census baseline (same instruments as
    every candidate), then the closure's controllers in order. With no
    controllers it is the measurement of `state0` alone (a route that is its
    own arm, e.g. the pre-DRT repair's). `name == "librelane"` keeps the
    single-arm layout (`ARM_REL/impl`, lanes `32-*`)."""
    import librelane_contract as _ll
    from _ppa import closure as _cl
    arm = project / ARM_REL if name == "librelane" else project / ARM_REL / name
    impl = arm / IMPL_DIR
    impl.mkdir(parents=True, exist_ok=True)
    lane = "32" if name == "librelane" else f"32-{name}"
    ctx = {"project": str(project.resolve()), "image": image, "pdk": pdk,
           "mounts": [(str(h.resolve()), g) for h, g in mounts],
           "configs": {k: str(v.resolve()) for k, v in configs.items()},
           "corners": corners, "lane": lane, "arm": name,
           "derate": list(derate), "aocv_table": aocv_table,
           "floors": {k: list(v) for k, v in (floors or {}).items()}}
    write_json(impl / CONTEXT, ctx)
    ledger = _ledger_path(impl)
    if ledger.is_file():
        ledger.unlink()
    census = _ll.derive_step_config(
        configs[REPAIR_STEP], configs[REPAIR_STEP].with_name(f"{REPAIR_STEP}@census.json"),
        {"VIBEIC_PRR_CENSUS_ONLY": (True, "the input route's census: repair nothing")})
    folder0, baseline = _candidate(ctx, census, state0, f"{lane}-base")
    write_json(impl / CURRENT, {"candidate": None, "repair_input": str(state0),
                                "repair_state": str(state0), "repair_folder": str(folder0),
                                "measurement": baseline})
    report: Dict[str, Any] = {"arm": name, "input_state": str(state0), "corners": corners,
                              "floors": ctx["floors"],
                              "baseline": baseline,
                              "baseline_antenna": baseline.get("antenna_nets"),
                              # The census step's own metrics on the arm's input
                              # route (its unrouted census): what a promoter of
                              # THIS route, with no candidate, measured.
                              "baseline_repair_metrics": {
                                  k: v for k, v in (_load(folder0 / "state_out.json")
                                                    .get("metrics") or {}).items()
                                  if k.startswith("vibeic__prr__")}}
    trigger = measured_repair_trigger(baseline)
    report["repair_trigger"] = trigger
    runs = []
    # Which ledger rows each controller's actuations wrote: the ledger's length
    # before and after that controller ran. A row is never attributed across
    # a controller boundary, whatever the rows before it were.
    spans: List[Tuple[int, int]] = []

    def _ledger_len() -> int:
        return len(_load(ledger)["candidates"]) if ledger.is_file() else 0
    if controllers and trigger["action"] == "RUN":
        reg = _cl.load_registry(registry, programs_dir=programs_dir)
        controller = _cl.ClosureController(reg, impl, arm / "closure")
        for cid in controllers:
            start = _ledger_len()
            runs.append(controller.run_controller(cid).to_record())
            spans.append((start, _ledger_len()))
    report["closure"] = runs
    candidates = _load(ledger)["candidates"] if ledger.is_file() else []
    for closure_run, (start, end) in zip(runs, spans):
        cid = closure_run.get("controller")
        # One actuation = one candidate row plus, after a native failure, its
        # retry row (`retry_of` names the candidate). The closure's verdict on
        # an actuation goes to the row that was measured; a row the actuator
        # itself booked ACTUATOR_FAILED keeps that verdict.
        groups: List[List[Dict[str, Any]]] = []
        for row in candidates[start:end]:
            if row.get("retry_of") and groups and \
                    groups[-1][0].get("candidate") == row["retry_of"]:
                groups[-1].append(row)
            else:
                groups.append([row])
        actuated = [it for it in closure_run.get("iterations") or [] if it.get("argv")]
        for index, group in enumerate(groups):
            it = actuated[index] if index < len(actuated) else {}
            for row in group:
                row["controller"] = cid
                if row.get("decision") == "ACTUATOR_FAILED":
                    row["closure_decision"] = "ACTUATOR_FAILED"
                    row["closure_reason"] = row.get("reason")
                else:
                    row["closure_decision"] = it.get("decision")
                    row["closure_reason"] = it.get("decision_reason")
    for closure_run in runs:
        cid = closure_run.get("controller")
        final_all = closure_run.get("final_all") or {}
        retained = {name: (final_all.get(domain) or {}).get("value")
                    for name, domain in (("drv_count", "timing.drv"),
                                         ("setup_ws_min", "timing.setup"),
                                         ("hold_ws_min", "timing.hold"))}
        closure_run["refused_candidates"] = [
            {"candidate": row.get("candidate"),
             "decision": row.get("closure_decision"),
             "measurement_status": ("MEASURED" if row.get("measurement")
                                    else "NOT_MEASURED"),
             "measured": {key: (row.get("measurement") or {}).get(key)
                          for key in retained},
             "retained": retained,
             "tool_crash_signature": row.get("tool_crash_signature")}
            for row in candidates if row.get("controller") == cid and
            row.get("closure_decision") != "PROMOTED"]
    report["candidates"] = candidates
    final = _load(impl / CURRENT)
    report["adopted"] = final.get("candidate")
    report["final"] = final.get("measurement")
    report["final_antenna"] = (final.get("measurement") or {}).get("antenna_nets")
    report["final_supply_ownership"] = final.get("supply_ownership")
    report["adopted_state"] = final.get("repair_state")
    return report


def _clear_declared_repair(project: Path) -> None:
    """A new step-32 attempt invalidates any prior decision and outcome,
    including the previous attempt's step-32 report: the in-step DRV judge
    must never read another round's adoption record (review wave 57)."""
    (project / REPORT_REL).unlink(missing_ok=True)
    out = project / DECLARED_REPAIR_REL
    for name in ("postroute_timing_repair_decision.json", "repair_log.json",
                 "no_repair_needed.flag"):
        (out / name).unlink(missing_ok=True)


def _set_census_verdict(report: Dict[str, Any], *measurements: Dict[str, Any]) -> None:
    antenna_measured = all(_antenna_counts(m) is not None for m in measurements)
    sta_digest_measured = all(_has_sta_digest(m) for m in measurements)
    report["antenna_census"] = {"verdict": "PASS" if antenna_measured else "NOT_MEASURED"}
    report["sta_digest_census"] = {"verdict": "PASS" if sta_digest_measured else "NOT_MEASURED"}
    _set_final_fanout_verdict(report)
    _set_final_drv_verdict(report)
    missing = []
    if not antenna_measured:
        missing.append("input or final antenna net/pin census is absent")
    if not sta_digest_measured:
        missing.append("input or final STAPostPNR state digest is absent")
    if missing:
        if report["verdict"] == "PASS":
            report.update(verdict="NOT_MEASURED",
                          code=("LL_PRR_ANTENNA_NOT_MEASURED" if not antenna_measured
                                else "LL_PRR_STA_DIGEST_NOT_MEASURED"),
                          reason="; ".join(missing))
        else:
            report["reason"] = "; ".join(filter(None, (report.get("reason"), *missing)))
    elif report["verdict"] == "PASS":
        report.pop("code", None)


def adopted_candidate_measured(report: Dict[str, Any]) -> bool:
    """R-0929-STEP32-ADOPT: a step-32 report whose route may be handed off and
    declared -- PASS, or a FAIL whose only cause is a MEASURED residual
    (fanout / DRV) with its antenna and STA-digest census measured.  Anything
    unmeasured (LL_PRR_*_NOT_MEASURED, ...) is refused: an adopted candidate
    nobody fully measured never ships (review wave 58)."""
    return (report.get("verdict") == "PASS" or
            (report.get("verdict") == "FAIL" and
             report.get("code") in ("LL_PRR_FANOUT_VIOLATION",
                                    "LL_PRR_DRV_VIOLATION") and
             report.get("antenna_census", {}).get("verdict") == "PASS" and
             report.get("sta_digest_census", {}).get("verdict") == "PASS"))


def _publish_declared_repair(project: Path, report: Dict[str, Any], source: Path) -> None:
    """Publish step 32's measured decision before the pre-stream gate.

    The later canonicalize pass cannot write this declaration when pre-stream
    blocks it. A missing or malformed STAPostPNR census leaves no fresh output,
    so the declared-output check refuses it instead of accepting a marker.
    """
    def refuse(reason: str) -> None:
        report["declared_repair_publication"] = {
            "status": "NOT_MEASURED", "reason": reason}
        write_json(source, report)

    # A measured fanout residue leaves Step 32 FAIL, while its declaration
    # must still reach the pre-stream audit so the adopted route and residual
    # are visible.  Other incomplete/failing reports cannot publish.
    if not adopted_candidate_measured(report):
        reason = ("the input/final OpenROAD.CheckAntennas net and pin census "
                  "is missing" if report.get("code") == "LL_PRR_ANTENNA_NOT_MEASURED"
                  else "the input/final STAPostPNR state digest is missing"
                  if report.get("code") == "LL_PRR_STA_DIGEST_NOT_MEASURED"
                  else f"step 32 verdict {report.get('verdict')!r} is not PASS")
        refuse(reason)
        return
    baseline = report.get("input_baseline") or report.get("baseline") or {}
    final = report.get("final") or {}
    floors = report.get("floors") or {}
    before = [baseline.get(k) for k in ("drv_count", "setup_ws_min", "hold_ws_min")]
    after = [final.get(k) for k in ("drv_count", "setup_ws_min", "hold_ws_min")]
    setup_floor = (floors.get("setup") or [None])[0]
    hold_floor = (floors.get("hold") or [None])[0]
    if (any(type(v) is not int for v in (before[0], after[0])) or
            any(type(v) not in (int, float) or not math.isfinite(v)
                for v in (*before[1:], *after[1:], setup_floor, hold_floor))):
        refuse("the input/final STAPostPNR census or timing floors are missing")
        return
    input_antenna = _antenna_counts(baseline)
    final_antenna = _antenna_counts(final)
    if input_antenna is None or final_antenna is None:
        refuse("the input/final OpenROAD.CheckAntennas net and pin census is missing")
        return
    if not _has_sta_digest(baseline) or not _has_sta_digest(final):
        refuse("the input/final STAPostPNR state digest is missing")
        return
    import librelane_contract as _ll
    # The trigger describes the INPUT route; a successfully repaired output
    # does not retroactively make its repair unnecessary.
    adopted = report.get("adopted")
    route_changed = bool(report.get("route_state") and report.get("adopted_state")
                         and Path(report["adopted_state"]) != Path(report["route_state"]))
    needed = bool(before[0] or before[1] < setup_floor or
                  before[2] < hold_floor or route_changed or adopted or
                  any(input_antenna) or any(final_antenna))
    candidates = report.get("candidates") or []
    adopted_row = next((row for row in candidates
                        if row.get("candidate") == adopted and
                        row.get("closure_decision") == "PROMOTED"), None)
    changed = ((adopted_row.get("repair_metrics") or {}).get("vibeic__prr__changed")
               if adopted_row else None)
    changes = ([{"candidate": adopted,
                 "changed_instances": changed,
                 "sta_state_sha256": after_state}]
               if (type(changed) is int and changed > 0 and
                   (after_state := final.get("sta_state_sha256")) and
                   after_state == (adopted_row.get("measurement") or {}).get(
                       "sta_state_sha256")) else [])
    if not changes and route_changed and report.get("selected_arm") != "postdrt":
        after_state = final.get("sta_state_sha256")
        if after_state:
            changes = [{"selected_arm": report.get("selected_arm"),
                        "route_state": report.get("adopted_state"),
                        "sta_state_sha256": after_state}]
    re_verified = bool(changes and after[0] == 0 and
                       after[1] >= setup_floor and after[2] >= hold_floor and
                       final_antenna == (0, 0))
    out = project / DECLARED_REPAIR_REL
    action = ("candidate_adopted" if adopted else
              "alternate_route_selected" if route_changed else "input_route_kept")
    refused = [str(row.get("reason") or row.get("closure_reason"))
               for row in candidates if row.get("decision") == "REFUSED"
               or row.get("closure_decision") == "ROLLED_BACK"]
    residual = {"drv_count": after[0],
                "setup_below_floor": after[1] < setup_floor,
                "hold_below_floor": after[2] < hold_floor,
                "refused_candidates": refused}
    write_json(out / "postroute_timing_repair_decision.json", {
        "repair_needed": needed,
        "action": action,
        "candidate": adopted,
        "baseline": dict(zip(("drv_count", "setup_ws_min", "hold_ws_min"), before)),
        "final": dict(zip(("drv_count", "setup_ws_min", "hold_ws_min"), after)),
        "floors": floors,
        "residual": residual,
        "source_report": str(source.relative_to(project)),
        "source_report_sha256": _ll.digest(source),
        "measured_by": "OpenROAD.STAPostPNR at every declared corner",
    })
    flag = out / "no_repair_needed.flag"
    log = out / "repair_log.json"
    if needed:
        if flag.is_file():
            flag.unlink()
        write_json(log, {
            "source_report": str(source.relative_to(project)),
            "source_report_sha256": _ll.digest(source),
            "candidates": candidates,
            "adopted": adopted,
            "changes": changes,
            "re_verified": re_verified,
            "baseline": baseline,
            "final": final,
        })
    else:
        if log.is_file():
            log.unlink()
        write_text(flag, "STAPostPNR: declared timing floors and DRV are met\n")


def run(project: Path, *, image: str, pdk: str, pdk_root: Path,
        views: Dict[str, Path], sdc: Path, derate: Tuple[float, float],
        aocv_table: Optional[str] = None,
        pg_rules_tcl: Optional[Path] = None, refill_tcl: Optional[Path] = None,
        registry: Optional[Path] = None, programs_dir: Optional[Path] = None,
        docker: str = "docker",
        dont_use: Optional[Tuple[Callable[[str], List[str]], str]] = None,
        max_fanout: Optional[Tuple[int, str]] = None) -> Dict[str, Any]:
    """Step 32 on LibreLane after a DIRECT route: bridge the routed views,
    then one closure arm. Returns the report (also written to `REPORT_REL`).
    `adopted` is the candidate the closure left adopted (`None`: the input
    route stays)."""
    import librelane_contract as _ll
    report: Dict[str, Any] = {"step": STEP, "mode": "librelane", "image": image,
                              "site": "after_direct_route"}
    out = project / REPORT_REL
    _clear_declared_repair(project)
    if _refused_by_tool(report, fork_capability(image, docker), out):
        return report
    configs, corners, mounts = _prepare(
        project, image=image, pdk=pdk, pdk_root=pdk_root, sdc=sdc, derate=derate,
        pg_rules_tcl=pg_rules_tcl, refill_tcl=refill_tcl, docker=docker,
        dont_use=dont_use, max_fanout=max_fanout)
    state0 = _ll.state_from_direct(project, image, configs[REPAIR_STEP], views,
                                   project / "phase3/librelane/32-config/bridge",
                                   mounts=mounts,
                                   chain=[configs[s] for s in MEASURE_STEPS],
                                   docker=docker)
    report.update(close_arm(project, "librelane", state0, image=image, pdk=pdk,
                            configs=configs, corners=corners, mounts=mounts,
                            derate=derate, aocv_table=aocv_table,
                            registry=registry, programs_dir=programs_dir,
                            floors=declared_timing_floor(project, sdc)))
    _stamp_verdict(report)
    _step32_drv_signoff(project, report)
    write_json(out, report)
    _publish_declared_repair(project, report, out)
    return report


#: review70 step 32, dual_tool_option: arm A is the repair BEFORE detailed
#: routing (LibreLane RepairDesignPostGRT + ResizerTimingPostGRT, switched on
#: by the flow's own gates), arm B is this step's repair AFTER it, and the two
#: can be chained. The variables are LibreLane's own flow gates.
PREGRT_GATES = ("RUN_POST_GRT_DESIGN_REPAIR", "RUN_POST_GRT_RESIZER_TIMING")
DUAL_ARMS = ("postdrt", "pregrt", "pregrt_postdrt")
#: The review's "better": per-corner hold and setup worst slack (STAPostPNR),
#: with router DRC and antenna held at 0 (feasibility) and DRV too.
DUAL_OBJECTIVES = {"hold_ws_min": "max", "setup_ws_min": "max"}


def _arm_gate(folder: Path, arm: Dict[str, Any], route_drc: Optional[int],
              scope: Dict[str, str]) -> Path:
    final = arm.get("final") or {}
    rows = {k: ({"status": "MEASURED", "value": final.get(k)}
                if isinstance(final.get(k), (int, float)) else {"status": "NOT_MEASURED"})
            for k in (*DUAL_OBJECTIVES, "drv_count", "antenna_nets", "antenna_pins")}
    rows["route_drc"] = ({"status": "MEASURED", "value": route_drc}
                         if isinstance(route_drc, int) else {"status": "NOT_MEASURED"})
    verdict = "PASS" if all(r["status"] == "MEASURED" for r in rows.values()) else "NOT_MEASURED"
    path = folder / "gate.json"
    write_json(path, {"verdict": verdict, "metrics": rows, "scope": scope})
    return path


def select_dual(project: Path, arms: Dict[str, Dict[str, Any]],
                route_drc: Dict[str, Optional[int]], scope: Dict[str, str]) -> Dict[str, Any]:
    """Feasible first (route DRC 0, antenna 0, DRV 0, all measured), then the
    Pareto frontier on worst hold and setup slack (`select_arms`); a frontier
    tie goes to hold, then setup, then the arm order of `DUAL_ARMS` (the
    cheaper arm first: no extra route)."""
    import librelane_contract as _ll
    root = project / ARM_REL
    gates = {n: _arm_gate(root / "gates" / n, a, route_drc.get(n), scope)
             for n, a in arms.items()}
    docs = {n: _load(p) for n, p in gates.items()}

    def value(n: str, k: str) -> Any:
        return docs[n]["metrics"][k].get("value")

    feasible = [n for n in arms if docs[n]["verdict"] == "PASS"
                and value(n, "route_drc") == 0 and value(n, "antenna_nets") == 0
                and value(n, "antenna_pins") == 0
                and value(n, "drv_count") == 0]
    pool = feasible or [n for n in arms if docs[n]["verdict"] == "PASS"]
    if not pool:
        sel = {"selection": "UNDETERMINED", "reason": "LL_PRR_DUAL_NOT_MEASURED",
               "arms": list(arms)}
        write_json(root / "selection.json", sel)
        return sel
    sel = _ll.select_arms({n: gates[n] for n in pool}, DUAL_OBJECTIVES,
                          root / "selection.json")
    sel = dict(sel, feasible=feasible, considered=pool)
    if sel.get("selection") not in pool:
        frontier = sel.get("frontier") or pool
        order = {n: i for i, n in enumerate(DUAL_ARMS)}
        sel = dict(sel, selection=min(frontier, key=lambda n: (
            -value(n, "hold_ws_min"), -value(n, "setup_ws_min"), order.get(n, 99))),
                   tie_break="review70 step 32: hold, then setup, then the arm "
                             "without an extra route")
    write_json(root / "selection.json", sel)
    return sel


def run_in_chain(project: Path, *, mode: str, image: str, pdk: str, pdk_root: Path,
                 sdc: Path, derate: Tuple[float, float], route_state: Path,
                 route_drc: Optional[int],
                 aocv_table: Optional[str] = None,
                 variant_arm: Optional[Callable[[str, Dict[str, Tuple[Any, str]]],
                                                Dict[str, Any]]] = None,
                 pg_rules_tcl: Optional[Path] = None,
                 registry: Optional[Path] = None, programs_dir: Optional[Path] = None,
                 docker: str = "docker",
                 dont_use: Optional[Tuple[Callable[[str], List[str]], str]] = None,
        max_fanout: Optional[Tuple[int, str]] = None,
                 ) -> Dict[str, Any]:
    """Step 32 on LibreLane INSIDE the step-21 LibreLane chain
    (LL21 -> Vibeic.PostRouteRepair -> tail): the routed State is the
    selected route arm's own (no DEF crosses a session), and the route's
    fillers are LibreLane's (`OpenROAD.FillInsertion`), so the refill is
    LibreLane's too.

    `dual`: arm `postdrt` (this repair on the route), arm `pregrt` (step 21's
    LibreLane route again with the flow's post-GRT repair gates on, measured
    by the same instruments), and arm `pregrt_postdrt` (this repair on that
    route); `select_dual` picks."""
    report: Dict[str, Any] = {"step": STEP, "mode": mode, "image": image,
                              "site": "after_route", "route_state": str(route_state)}
    out = project / REPORT_REL
    _clear_declared_repair(project)
    if _refused_by_tool(report, fork_capability(image, docker), out):
        return report
    configs, corners, mounts = _prepare(
        project, image=image, pdk=pdk, pdk_root=pdk_root, sdc=sdc, derate=derate,
        pg_rules_tcl=pg_rules_tcl, refill_tcl=None, docker=docker,
        dont_use=dont_use, max_fanout=max_fanout)
    common = dict(image=image, pdk=pdk, configs=configs, corners=corners, mounts=mounts,
                  derate=derate, aocv_table=aocv_table,
                  registry=registry, programs_dir=programs_dir,
                  floors=declared_timing_floor(project, sdc))
    if mode != "dual":
        report.update(close_arm(project, "librelane", route_state, **common))
        _stamp_verdict(report)
        _step32_drv_signoff(project, report)
        write_json(out, report)
        _publish_declared_repair(project, report, out)
        return report
    if variant_arm is None:
        raise ValueError("LL_PRR_DUAL_NEEDS_LL21: the pre-DRT arm is step 21's "
                         "LibreLane route; select 21 librelane or dual")
    arms: Dict[str, Dict[str, Any]] = {}
    drcs: Dict[str, Optional[int]] = {}
    arms["postdrt"] = close_arm(project, "postdrt", route_state, **common)
    drcs["postdrt"] = route_drc
    pre = variant_arm("21-route-pregrt", {
        g: (True, "review70 step 32 dual arm A: the flow's own post-GRT repair")
        for g in PREGRT_GATES})
    runs = pre.get("route_drc") or []
    pre_drc = runs[-1].get("markers") if runs else None
    arms["pregrt"] = close_arm(project, "pregrt", Path(pre["final"]), controllers=(),
                               **common)
    drcs["pregrt"] = pre_drc
    arms["pregrt_postdrt"] = close_arm(project, "pregrt_postdrt", Path(pre["final"]),
                                       **common)
    drcs["pregrt_postdrt"] = pre_drc
    scope = {"step": STEP, "corners": ",".join(corners),
             "measured_by": "OpenROAD.CheckAntennas + RCX + STAPostPNR (sign-off scene)"}
    sel = select_dual(project, arms, drcs, scope)
    report.update(arms=arms, route_drc=drcs, selection=sel, corners=corners)
    chosen = arms.get(sel.get("selection"))
    if chosen is None:
        report.update(verdict="NOT_MEASURED", code="LL_PRR_DUAL_UNDETERMINED")
        write_json(out, report)
        return report
    report.update({k: chosen[k] for k in ("baseline", "final", "adopted", "adopted_state",
                                           "final_antenna", "baseline_antenna",
                                           "final_supply_ownership", "candidates",
                                           "closure", "baseline_repair_metrics", "floors")
                   if k in chosen})
    report["input_baseline"] = arms["postdrt"]["baseline"]
    report["repair_trigger"] = chosen.get("repair_trigger")
    report["selected_arm"] = sel["selection"]
    # The pregrt arm re-ran step 21's chain and rewrote the post-GRT receipt:
    # bind the route the selected arm stands on before the step-32 capture.
    import drv_stage_receipts as _drv_stages
    _lane = ((list(zip(pre["ids"], pre["folders"])) if pre.get("folders")
              else Path(pre["final"]).parent.parent)
             if sel["selection"] in ("pregrt", "pregrt_postdrt")
             else Path(route_state).parent.parent if route_state else None)
    _drv_stages.rebind_lane(project, _lane, ("post_grt_repair",), sel["selection"])
    _stamp_verdict(report)
    _step32_drv_signoff(project, report)
    write_json(out, report)
    _publish_declared_repair(project, report, out)
    return report


def handoff(project: Path, report: Dict[str, Any], targets: Dict[str, Path]) -> Dict[str, Any]:
    """The adopted candidate's views onto the paths the direct flow reads."""
    import librelane_contract as _ll
    return _ll.handoff_to_direct(Path(report["adopted_state"]), targets,
                                 project / "reports/phase3/librelane_postroute_repair_handoff.json")


def _resume_host_path(project: Path, ctx: Dict[str, Any], value: str) -> Path:
    path = Path(value)
    declared_project = Path(ctx["project"])
    try:
        return project / path.relative_to(declared_project)
    except ValueError:
        pass
    for host, guest in sorted(ctx.get("mounts") or [],
                              key=lambda item: len(str(item[1])), reverse=True):
        try:
            return Path(host) / path.relative_to(Path(guest))
        except ValueError:
            continue
    return path


def _validate_resume_subject(project: Path, current: Dict[str, Any],
                             ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Bind the live route to the immutable adopted State before actuation."""
    import librelane_contract as _ll
    try:
        state_path = _resume_host_path(project, ctx, current["repair_state"])
        state = _load(state_path)
        handoff_path = project / "reports/phase3/librelane_postroute_repair_handoff.json"
        handoff = _load(handoff_path)
        if (_resume_host_path(project, ctx, handoff["state"]) != state_path or
                handoff["state_sha256"] != _ll.digest(state_path)):
            raise ValueError("handoff state does not name the adopted State bytes")
        checked: Dict[str, str] = {}
        for view in ("def", "nl"):
            row = handoff["views"][view]
            source = _resume_host_path(project, ctx, row["source"])
            dest = _resume_host_path(project, ctx, row["dest"])
            if source != _resume_host_path(project, ctx, state[view]):
                raise ValueError(f"{view}: handoff source is not adopted State")
            source_sha, dest_sha = _ll.digest(source), _ll.digest(dest)
            if not (source_sha == row["source_sha256"] ==
                    row["dest_sha256"] == dest_sha):
                raise ValueError(f"{view}: live handoff bytes changed")
            checked[f"live_{view}_sha256"] = dest_sha
        for view in ("sdc", "odb"):
            path = _resume_host_path(project, ctx, state[view])
            checked[f"adopted_{view}_sha256"] = _ll.digest(path)
        measured = current["measurement"]
        sta_state = _resume_host_path(project, ctx, measured["sta_state"])
        if _ll.digest(sta_state) != measured["sta_state_sha256"]:
            raise ValueError("adopted STAPostPNR State bytes changed")
        sta_fp = _load(sta_state.parent / "input_fingerprint.json")
        recorded_inputs = sta_fp.get("state_files")
        if not isinstance(recorded_inputs, dict):
            raise ValueError("STAPostPNR input readset is missing")
        for view in ("sdc", "odb"):
            declared = state[view]
            if recorded_inputs.get(declared) != checked[f"adopted_{view}_sha256"]:
                raise ValueError(f"adopted {view.upper()} differs from measured input")
        if checked["adopted_odb_sha256"] != measured["native_odb_sha256"]:
            raise ValueError("adopted native ODB differs from measured ODB")
        return checked
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise _ll.Refusal("LL_PRR_RESUME_SUBJECT_STALE", str(exc)) from exc


def _validate_resume_readset(project: Path, current: Dict[str, Any],
                             ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Re-hash the retained native chain's configs, models, PDK and tool."""
    import librelane_contract as _ll
    try:
        repair_folder = _resume_host_path(project, ctx, current["repair_folder"])
        lane = repair_folder.parent
        by_step: Dict[str, Path] = {}
        for folder in lane.iterdir():
            receipt_path = folder / "vibeic_receipt.json"
            if receipt_path.is_file():
                step = _load(receipt_path).get("input", {}).get("step")
                if isinstance(step, str):
                    by_step[step] = folder
        required = (REPAIR_STEP, *MEASURE_STEPS)
        if any(step not in by_step for step in required):
            raise ValueError(f"retained native chain incomplete: {sorted(by_step)}")
        ledger = _load(project / ARM_REL / LEDGER).get("candidates") or []
        adopted_row = next((row for row in ledger
                            if row.get("candidate") == current.get("candidate")), None)
        if not isinstance(adopted_row, dict):
            raise ValueError("adopted candidate has no ledger authority")
        handoff = _load(project / "reports/phase3/librelane_postroute_repair_handoff.json")
        promoted_destinations = {
            str(_resume_host_path(project, ctx, row["dest"]))
            for row in (handoff.get("views") or {}).values()
            if isinstance(row, dict) and isinstance(row.get("dest"), str)}

        recorded_image = None
        for step in required:
            folder = by_step[step]
            receipt = _ll.validate_step_receipt(folder, step)
            fp = receipt["input"]
            if fp.get("image") != ctx.get("image"):
                raise ValueError(f"{step}: image identity changed")
            config_source = (adopted_row.get("config") if step == REPAIR_STEP
                             else (ctx.get("configs") or {}).get(step))
            if not isinstance(config_source, str):
                raise ValueError(f"{step}: resolved config authority missing")
            if fp.get("config") != _ll.digest(
                    _resume_host_path(project, ctx, config_source)):
                raise ValueError(f"{step}: resolved config source changed")
            if not re.fullmatch(r"[0-9a-f]{64}", str(fp.get("state") or "")):
                raise ValueError(f"{step}: input State authority missing")
            for field in ("state_files", "config_files"):
                values = fp.get(field)
                if not isinstance(values, dict):
                    raise ValueError(f"{step}: {field} authority missing")
                for path, expected in values.items():
                    actual = _resume_host_path(project, ctx, path)
                    if field == "state_files" and str(actual) in promoted_destinations:
                        # The accepted handoff legitimately replaced the route
                        # and netlist that the first candidate consumed. Their
                        # current bytes were bound above to the adopted output.
                        continue
                    if not isinstance(expected, str) or _ll.digest(actual) != expected:
                        raise ValueError(f"{step}: {field} changed: {path}")
            if step == REPAIR_STEP:
                plugins = fp.get("plugin")
                if not isinstance(plugins, dict) or plugins != _ll._plugin_digests(step):
                    raise ValueError(f"{step}: plugin/tool readset changed")
            for field in (("rcx_pdk_files",) if step == "OpenROAD.RCX" else
                          ("liberty_files",) if step == "OpenROAD.STAPostPNR" else ()):
                values = fp.get(field)
                if not isinstance(values, dict) or not values:
                    raise ValueError(f"{step}: {field} authority missing")
                for path, expected in values.items():
                    actual = _resume_host_path(project, ctx, path)
                    if not isinstance(expected, str) or _ll.digest(actual) != expected:
                        raise ValueError(f"{step}: {field} changed: {path}")
            pdk_record = _load(folder / "pdk_root.json")
            expected_mounts = [[str(Path(host).resolve()), guest]
                               for host, guest in ctx.get("mounts") or []]
            if pdk_record.get("requested_mounts") != expected_mounts:
                raise ValueError(f"{step}: PDK mount identity changed")
            image_identity = fp.get("local_image")
            if not isinstance(image_identity, dict):
                raise ValueError(f"{step}: native tool identity missing")
            stable = {key: value for key, value in image_identity.items()
                      if key not in ("cid", "attestation_path", "attestation_sha256")}
            if recorded_image is None:
                live = _ll.local_image_attestation(ctx["image"])
                recorded_image = {key: value for key, value in live.items()
                                  if key not in ("cid", "attestation_path",
                                                 "attestation_sha256")}
            if stable != recorded_image:
                raise ValueError(f"{step}: native tool identity changed")
        return {"verdict": "PASS", "steps": list(required),
                "image": ctx["image"]}
    except _ll.Refusal as exc:
        raise _ll.Refusal("LL_PRR_RESUME_READSET_STALE", str(exc)) from exc
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise _ll.Refusal("LL_PRR_RESUME_READSET_STALE", str(exc)) from exc


def resume_drv(project: Path, *, registry: Optional[Path] = None,
               programs_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Continue only the DRV controller from a measured residual report.

    Unlike :func:`close_arm`, this does not rebuild the census, delete the
    candidate ledger, or replay setup/hold candidates.  It is deliberately
    admissible only when the canonical report and the adopted pointer name the
    same measured STA state and the report's sole step verdict is residual DRV.
    """
    import librelane_contract as _ll
    from _ppa import closure as _cl

    source = project / REPORT_REL
    try:
        report = _load(source)
        arm = project / ARM_REL
        impl = arm / IMPL_DIR
        current = _load(impl / CURRENT)
        ctx = _load(impl / CONTEXT)
        ledger_path = _ledger_path(impl)
        candidates = _load(ledger_path)["candidates"]
    except (OSError, ValueError, KeyError) as exc:
        raise _ll.Refusal("LL_PRR_RESUME_STATE_ABSENT", str(exc)) from exc
    if report.get("verdict") != "FAIL" or report.get("code") != "LL_PRR_DRV_VIOLATION":
        raise _ll.Refusal("LL_PRR_RESUME_NOT_DRV_RESIDUE",
                          f"{report.get('verdict')} {report.get('code')}")
    final = report.get("final") or {}
    measured = current.get("measurement") or {}
    identity = ("sta_state_sha256", "native_odb_sha256", "drv_count",
                "drv_pin_checks_state", "drv_pin_checks")
    mismatch = [key for key in identity if final.get(key) != measured.get(key)]
    if mismatch or report.get("adopted") != current.get("candidate"):
        raise _ll.Refusal(
            "LL_PRR_RESUME_CURRENT_MISMATCH",
            f"fields={mismatch}; report adopted={report.get('adopted')!r}; "
            f"current candidate={current.get('candidate')!r}")
    if type(measured.get("drv_count")) is not int or measured["drv_count"] <= 0:
        raise _ll.Refusal("LL_PRR_RESUME_DRV_NOT_VIOLATED",
                          f"drv_count={measured.get('drv_count')!r}")

    subject_freshness = _validate_resume_subject(project, current, ctx)
    readset_freshness = _validate_resume_readset(project, current, ctx)

    before = len(candidates)
    reg = _cl.load_registry(registry, programs_dir=programs_dir)
    run = _cl.ClosureController(reg, impl, arm / "closure").run_controller(
        "postroute.repair_drv")
    run_record = run.to_record()
    candidates = _load(ledger_path)["candidates"]
    new_rows = candidates[before:]
    groups: List[List[Dict[str, Any]]] = []
    for row in new_rows:
        if row.get("retry_of") and groups and groups[-1][0].get("candidate") == row["retry_of"]:
            groups[-1].append(row)
        else:
            groups.append([row])
    actuated = [it for it in run_record.get("iterations") or [] if it.get("argv")]
    for index, group in enumerate(groups):
        iteration = actuated[index] if index < len(actuated) else {}
        for row in group:
            row["controller"] = "postroute.repair_drv"
            if row.get("decision") == "ACTUATOR_FAILED":
                row["closure_decision"] = "ACTUATOR_FAILED"
                row["closure_reason"] = row.get("reason")
            else:
                row["closure_decision"] = iteration.get("decision")
                row["closure_reason"] = iteration.get("decision_reason")
    write_json(ledger_path, {"candidates": candidates})

    current = _load(impl / CURRENT)
    report.setdefault("continuations", []).append({
        "kind": "postroute.repair_drv", "candidate_ledger_start": before,
        "input_sta_state_sha256": final.get("sta_state_sha256"),
        "subject_freshness": subject_freshness,
        "readset_freshness": readset_freshness,
        "run": run_record})
    report.setdefault("closure", []).append(run_record)
    report["candidates"] = candidates
    report["adopted"] = current.get("candidate")
    report["final"] = current.get("measurement")
    report["final_antenna"] = measured_antenna = (
        current.get("measurement") or {}).get("antenna_nets")
    report["final_supply_ownership"] = current.get("supply_ownership")
    report["adopted_state"] = current.get("repair_state")
    report["resume"] = {"controller": "postroute.repair_drv",
                        "outcome": run_record.get("outcome"),
                        "candidate_ledger_start": before,
                        "candidate_ledger_end": len(candidates),
                        "final_antenna_nets": measured_antenna}
    _stamp_verdict(report)
    _step32_drv_signoff(project, report)
    write_json(source, report)
    _publish_declared_repair(project, report, source)
    return report


def _bool_arg(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise argparse.ArgumentTypeError(f"expected true/false, got {value!r}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("measure", help="closure measurement over the adopted candidate")
    m.add_argument("--domain", choices=sorted(DOMAIN_VALUE), required=True)
    m.add_argument("--json", type=Path, required=True)
    a = sub.add_parser("actuate", help="one repair candidate from the adopted state")
    for name in PARAM_VARS:
        a.add_argument("--" + name.replace("_", "-"),
                       type=(str if name == "setup_sequence" else
                             _bool_arg if name == "bounded_drive_strength" else float),
                       default=None)
    args = parser.parse_args(argv)
    impl = Path.cwd()
    if args.command == "measure":
        return measure(impl, args.domain, args.json)
    params = {k: getattr(args, k) for k in PARAM_VARS}
    return actuate(impl, params)


if __name__ == "__main__":
    sys.exit(main())
