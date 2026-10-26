#!/usr/bin/env python3
"""librelane_route.py — step 21 (global + detailed routing) on LibreLane (lane mig99).

Selected by `phase3/librelane_switch.json` `"21"` (`librelane` or `dual`)
through `librelane_contract.selected_mode`. With `direct` (switch absent, or
naming other steps) `phase3_one_shot_runner` runs its PnR session exactly as
before and nothing here is called.

Otherwise the deck's step-21 region -- `R._PNR_ROUTE_BEGIN` (after the
DRT-0305 PG-net cleanup) to `R._PNR_RESUME_ELIDE_END` (the route checkpoint)
-- runs on LibreLane instead:

1. a checkpoint session writes the pre-route ODB/DEF/netlist: the deck up to
   `_PNR_ROUTE_BEGIN` when steps 19/20 are direct, or, when they are on
   LibreLane too, the deck resumed from their handed-over `post_hold.odb` up
   to the same line (`librelane_cts_hold.execute(..., after_handoff=...)`);
2. the checkpoint is bridged (`state_from_direct`) into the image's own Chip
   segment `OpenROAD.GlobalRouting .. OpenROAD.FillInsertion` (global route,
   antenna check, post-GRT design and timing repair, antenna repair, detailed
   route with its own antenna loop, the route checkers), with
   `Vibeic.NamedViolationReroute` right after the detailed route; every step
   works on the ODB, so no routed state crosses a session as DEF;
3. with `dual`, the deck's own region runs on the same checkpoint (and each
   declared seed as one more LibreLane arm, `Vibeic.DetailedRoutingSeeded`);
   every arm is measured by one instrument and the selection follows review70's
   order (`select`);
4. the selected ODB/DEF go to `routed_preantenna.{odb,def}` and the router's
   own marker report to `routed_router.drc.rpt`, sha256-bound in
   `reports/phase3/librelane_route_handoff.json`; the tools' logs are appended
   to `openroad.log`, bracketed, so every log reader downstream reads what the
   router printed;
5. the deck resumes from the routed ODB after `_PNR_RESUME_ELIDE_END`: the same
   deck the fatal-signal resume runs (post-route repair, the antenna and PG
   residual stages, write_routed).

Like `librelane_cts_hold`, every function that needs the runner's machinery
takes the runner MODULE as `R` and never imports it.

chip-AGNOSTIC: no design, PDK, corner, layer or cell literal. Every LibreLane
config value carries its declared source.
"""
from __future__ import annotations

import json
import os as _os
import re
import sys as _sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import _atomic_artefact as _aa  # noqa: E402

STEP = "21"

#: The image's Chip-flow segment this step replaces, first and last step.
SEGMENT = ("OpenROAD.GlobalRouting", "OpenROAD.FillInsertion")
#: Steps of that segment that only MEASURE (the flow's mid-PnR STA); the
#: arms are measured after the route by one instrument instead (`measure_arm`).
MEASURE_ONLY = ("OpenROAD.STAMidPNR",)
DRT = "OpenROAD.DetailedRouting"
POST_GRT_REPAIR = "OpenROAD.RepairDesignPostGRT"
DRT_SEEDED = "Vibeic.DetailedRoutingSeeded"
NVR = "Vibeic.NamedViolationReroute"

#: The step-21 LibreLane knobs a PPA candidate may set, through
#: `phase3/librelane_switch.json` `"route_knobs"` (review70 ppa_layer_opportunity:
#: GRT_ADJUSTMENT / GRT_LAYER_ADJUSTMENTS / the DRT seed / iteration bounds).
#: `_ppa` writes one switch per candidate and reads the measured arm back; this
#: module never picks a value itself.
PPA_KNOBS = ("GRT_ADJUSTMENT", "GRT_LAYER_ADJUSTMENTS", "GRT_ANTENNA_REPAIR_ITERS",
             "GRT_ANTENNA_REPAIR_MARGIN", "DRT_OPT_ITERS", "DRT_ANTENNA_REPAIR_ITERS",
             "VIBEIC_DRT_OR_SEED",
             # the flow's own gates on post-GRT repair (off in the Chip flow's
             # defaults, which the t78 reference routed with)
             "RUN_POST_GRT_DESIGN_REPAIR", "RUN_POST_GRT_RESIZER_TIMING")

#: The metrics every arm is judged on, and the review's order of "better"
#: (review70 step 21 dual_tool_option): router DRC first; antenna nets must
#: be 0; then wirelength and vias; then worst-corner setup WNS and TNS.
OBJECTIVES = (("vibeic__route__drc_errors", "min"),
              ("vibeic__antenna__violating_nets", "min"),
              ("vibeic__route__wirelength_um", "min"),
              ("vibeic__route__vias", "min"),
              ("vibeic__setup__ws__worst_corner", "max"),
              ("vibeic__setup__tns__worst_corner", "max"))

#: The route checkers RECORD; vibe-ic's step-21 gates judge (drc_report_check,
#: def_stage_progression_check, provenance_check, ...). A checker that raised
#: would discard the route the gates are there to read.
CHECKER_RECORD_ONLY = {
    "ERROR_ON_TR_DRC": (False, "vibe-ic step-21 gate drc_report_check judges "
                               "the router's own report"),
    "ERROR_ON_DISCONNECTED_PINS": (False, "vibe-ic step-21 gates judge; the "
                                          "checker's metric is recorded"),
    "ERROR_ON_LONG_WIRE": (False, "vibe-ic step-21 gates judge; the checker's "
                                  "metric is recorded"),
}


def modes(project: Path) -> Dict[str, str]:
    """The contract switch for routing (21)."""
    import librelane_contract as _ll
    return {STEP: _ll.selected_mode(project, STEP)}


def _switch(project: Path) -> Dict[str, Any]:
    path = project / "phase3/librelane_switch.json"
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def switch_knobs(project: Path) -> Dict[str, Tuple[Any, str]]:
    """A PPA candidate's step-21 knobs, each with its source; an unknown knob
    refuses (never silently dropped)."""
    knobs = _switch(project).get("route_knobs") or {}
    if not isinstance(knobs, dict):
        raise ValueError(f"LL_ROUTE_KNOBS_INVALID: {knobs!r}")
    unknown = sorted(set(knobs) - set(PPA_KNOBS))
    if unknown:
        raise ValueError(f"LL_ROUTE_KNOB_UNKNOWN: {unknown}; allowed {list(PPA_KNOBS)}")
    return {k: (v, "phase3/librelane_switch.json route_knobs (PPA candidate)")
            for k, v in knobs.items()}


def seed_arms(project: Path) -> List[int]:
    """Extra `dual` arms, one per declared router seed
    (`"route_seeds"` in the switch)."""
    seeds = _switch(project).get("route_seeds") or []
    if not isinstance(seeds, list) or not all(
            isinstance(s, int) and not isinstance(s, bool) for s in seeds):
        raise ValueError(f"LL_ROUTE_SEEDS_INVALID: {seeds!r}")
    return list(dict.fromkeys(seeds))


def chain_ids(image: str, *, seeded: bool = False,
              flow_segment: Optional[Callable[..., List[str]]] = None,
              gated_off: Optional[Dict[str, List[str]]] = None,
              canonical_routing_only: bool = False) -> List[str]:
    """The image's own Chip-flow order for the segment, as step ids (a flow
    instance suffix such as `-1` dropped), the measure-only STA removed, every
    step the flow's own gates switch off (`gated_off`, from
    `librelane_contract.flow_gated_off`) removed, the named-violation reroute
    right after the detailed route."""
    import librelane_contract as _ll
    order = (flow_segment or _ll.flow_segment)(image, *SEGMENT)
    ids = [re.sub(r"-\d+$", "", s) for s in order]
    ids = [s for s in ids if s not in MEASURE_ONLY and s not in (gated_off or {})]
    if canonical_routing_only:
        # The reference segment includes full-flow electrical validation.
        # Vibe-IC's Step 31 owns ERC, including unused spare outputs and
        # floating-input checks. Step 21 retains its native router DRC checker.
        ids = [s for s in ids if s not in (
            'Odb.ReportDisconnectedPins', 'Checker.DisconnectedPins')]
    if DRT not in ids:
        raise ValueError(f"LL_ROUTE_SEGMENT_HAS_NO_DETAILED_ROUTE: {order}")
    at = ids.index(DRT)
    ids.insert(at + 1, NVR)
    if seeded:
        ids[at] = DRT_SEEDED
    return ids


def named_violation_config(R, *, project: Path, configs: Dict[str, Path],
                           ids: Sequence[str], lane: str, cfg_dir: Path,
                           reserved_instance_names=None) -> Path:
    """Bind the existing reroute pass to this chain's detailed-route report."""
    import librelane_contract as ll
    drt_index = next(i for i, sid in enumerate(ids) if sid in (DRT, DRT_SEEDED))
    drt_id = ids[drt_index]
    drt_folder = (project / 'phase3/librelane' / lane /
                  (f'{drt_index + 1:02d}-' + drt_id.lower().replace('.', '-')))
    design = json.loads(configs[DRT].read_text()).get('DESIGN_NAME')
    report = (cfg_dir / 'nvr' / lane / R.ROUTER_DRC_REPORT_NAME).resolve()
    body = cfg_dir / 'nvr' / lane / 'named_violation_reroute.body.tcl'
    report.parent.mkdir(parents=True, exist_ok=True)
    R._aa.write_text(body, R._named_violation_reroute_tcl(
        str(report), reserved_instance_names=reserved_instance_names))
    config = configs[NVR]
    return ll.derive_step_config(config, config.with_name(f'{NVR}@{lane}.json'), {
        'VIBEIC_NVR_TCL': (str(body.resolve()),
                          'phase3_one_shot_runner._named_violation_reroute_tcl'),
        'VIBEIC_NVR_REPORT_PATH': (str(report), "this chain's working router report"),
        'VIBEIC_NVR_DRC_REPORT': (
            str((drt_folder / f'{design}.drc').resolve()),
            f"{drt_id}'s own final -output_drc report"),
    })


def _cut(R, lines: List[str], marker: str) -> List[str]:
    """The deck up to the region's main `global_route`: the first command
    line after `marker` that starts with it. What precedes it inside the
    region (the DRT-0305 PG-net cleanup) is work the route needs, so it stays
    on the checkpoint side."""
    idx = [i for i, ln in enumerate(lines) if ln.strip() == marker]
    if len(idx) != 1:
        raise R.PnrResumeUnavailable(
            f"pnr.tcl carries {len(idx)} {marker!r} markers; the step-21 region "
            "cannot be located")
    route = next((i for i in range(idx[0] + 1, len(lines))
                  if re.match(r"global_route(\s|$)", lines[i])), None)
    if route is None:
        raise R.PnrResumeUnavailable("the step-21 region carries no global_route")
    head = lines[:idx[0]] + lines[idx[0] + 1:route]
    if _brace_depth(head) != 0:
        raise R.PnrResumeUnavailable("the step-21 region is not at the deck's top level")
    return head


def _brace_depth(lines: Sequence[str]) -> int:
    import librelane_cts_hold as _cts
    return _cts.tcl_brace_depth(lines)


def _checkpoint(R, *, odb_c: str, def_c: str, nl_c: str) -> List[str]:
    return [
        "# === Step 21 on LibreLane (mig99): stop before the route. The rest of",
        "# this deck resumes from the routed ODB LibreLane hands back",
        "# (tail_deck). ===",
        f'puts "{R._PNR_STAGE_MARKER} route_checkpoint"',
        f"write_db {odb_c}",
        f"write_def {def_c}",
        f"write_verilog {nl_c}",
        'puts "PNR_ROUTE_SPLIT: pre-route checkpoint written"',
        "exit 0",
    ]


def head_deck(R, deck: str, *, odb_c: str, def_c: str, nl_c: str) -> str:
    """pnr.tcl up to the step-21 region, then a checkpoint and a stop
    (steps 19/20 direct)."""
    head = _cut(R, deck.splitlines(), R._PNR_ROUTE_BEGIN)
    return "\n".join(head + _checkpoint(R, odb_c=odb_c, def_c=def_c, nl_c=nl_c)) + "\n"


def bridge_deck(R, deck: str, *, post_hold_odb_c: str, post_hold_def_c: str,
                after_restore_tcl: str, odb_c: str, def_c: str, nl_c: str) -> str:
    """pnr.tcl resumed from the step-19/20 handoff (`post_hold.odb`) up to the
    step-21 region: the routing constraints and the DRT-0305 PG-net cleanup
    the route needs, then the pre-route checkpoint (steps 19/20 on LibreLane)."""
    lines = R._pnr_deck_from_checkpoint(
        deck, checkpoint_def_c=post_hold_def_c, restore_odb_c=post_hold_odb_c,
        after_restore_tcl=after_restore_tcl, elide_end=R._PNR_CTS_HOLD_END)
    head = _cut(R, lines, R._PNR_ROUTE_BEGIN)
    return "\n".join(head + _checkpoint(R, odb_c=odb_c, def_c=def_c, nl_c=nl_c)) + "\n"


def tail_deck(R, deck: str, *, odb_c: str, def_c: str, after_restore_tcl: str) -> str:
    """pnr.tcl resumed from the routed ODB: everything after the route
    checkpoint, i.e. the fatal-signal resume deck."""
    return "\n".join(R._pnr_deck_from_checkpoint(
        deck, checkpoint_def_c=def_c, restore_odb_c=odb_c,
        after_restore_tcl=after_restore_tcl,
        elide_end=R._PNR_RESUME_ELIDE_END)) + "\n"


def direct_arm_deck(R, deck: str, *, pre_odb_c: str, pre_def_c: str, out_dir_c: str,
                    arm_c: str, after_restore_tcl: str) -> str:
    """The direct arm of a `dual` selection: the deck's own step-21 region,
    and only that, on the same pre-route checkpoint the LibreLane arm reads.
    Every path the region writes under the PnR directory goes to the arm's
    own directory, so no arm writes a shipped artefact."""
    lines = R._pnr_deck_from_checkpoint(
        deck, checkpoint_def_c=pre_def_c, restore_odb_c=pre_odb_c,
        after_restore_tcl=after_restore_tcl, elide_end=R._PNR_ROUTE_BEGIN)
    end = [i for i, ln in enumerate(lines) if ln.strip() == R._PNR_RESUME_ELIDE_END]
    if len(end) != 1:
        raise R.PnrResumeUnavailable(
            f"pnr.tcl carries {len(end)} {R._PNR_RESUME_ELIDE_END!r} markers")
    start = next(i for i, ln in enumerate(lines)
                 if ln.startswith("# --- floorplan..") and "elided" in ln)
    region = [ln.replace(out_dir_c + "/", arm_c + "/")
              for ln in lines[start + 1:end[0]]]
    return "\n".join(lines[:start + 1] + region + [
        f"write_db {arm_c}/routed.odb",
        f"write_verilog {arm_c}/routed.nl.v",
        'puts "PNR_ROUTE_DIRECT_ARM: done"',
        "exit 0",
    ]) + "\n"


def deck_sdc(R, deck: str, *, container: str, project: Path, out_dir: Path) -> Path:
    """The SDC the deck itself times with (its `read_sdc` line), on the host."""
    match = re.search(r"(?m)^read_sdc\s+(\S+)", deck)
    return (R._container_path_to_host(match.group(1), container, project)
            if match else out_dir / "constraint.sdc")


#: R-0929-POSTGRT: the DRV standard's required post-GRT repair stage runs.
#: LibreLane gates `OpenROAD.RepairDesignPostGRT` off by default, which left
#: the stage absent (section 1 FAIL) on every run.  Only the design (DRV)
#: repair is switched on; the post-GRT timing repair stays the flow's choice.
POST_GRT_DESIGN_REPAIR: Dict[str, Tuple[Any, str]] = {
    "RUN_POST_GRT_DESIGN_REPAIR": (
        True, "R-0929-POSTGRT: the DRV standard's required post_grt_repair stage")}

# The ordinary backend is strict about the timing population the design
# already declared.  These are native LibreLane keys, not replacement
# thresholds: every declared corner is loaded for repair and the native
# timing selectors remain all-corner.  ``bind_strict_timing_corners``
# supplies PNR_CORNERS after resolution, from that run's own STA_CORNERS.
STRICT_NATIVE_TIMING: Dict[str, Tuple[Any, str]] = {
    "RUN_POST_GRT_RESIZER_TIMING": (
        True, "issue3562 ordinary backend: run native post-GRT timing repair"),
    "TIMING_VIOLATION_CORNERS": (
        ["*"], "issue3562 ordinary backend: enforce every source-declared corner"),
    "SETUP_VIOLATION_CORNERS": (
        ["*"], "issue3562 ordinary backend: enforce setup at every declared corner"),
    "HOLD_VIOLATION_CORNERS": (
        ["*"], "issue3562 ordinary backend: enforce hold at every declared corner"),
}


def bind_strict_timing_corners(configs: Dict[str, Path]) -> Dict[str, Path]:
    """Bind post-GRT repair to the resolved run's complete corner population.

    The existing step config is the authority.  Missing, malformed or
    duplicate ``STA_CORNERS`` refuses before native execution; no DEFAULT
    corner or caller-authored fallback is manufactured.
    """
    import librelane_contract as _ll
    step = "OpenROAD.ResizerTimingPostGRT"
    source = configs.get(step)
    if source is None:
        raise _ll.Refusal("LL_STRICT_TIMING_STEP_ABSENT", step)
    try:
        doc = json.loads(Path(source).read_text())
    except (OSError, ValueError, TypeError) as exc:
        raise _ll.Refusal("LL_STRICT_TIMING_CONFIG_UNREADABLE", str(source)) from exc
    corners = doc.get("STA_CORNERS") if isinstance(doc, dict) else None
    if (not isinstance(corners, list) or not corners
            or any(not isinstance(corner, str) or not corner.strip()
                   or corner != corner.strip() for corner in corners)
            or len(set(corners)) != len(corners)):
        raise _ll.Refusal("LL_STRICT_TIMING_CORNERS_UNDECLARED", str(source))
    output = Path(source).with_name(Path(source).stem + "@strict-native.json")
    configs = dict(configs)
    configs[step] = _ll.derive_step_config(source, output, {
        **STRICT_NATIVE_TIMING,
        "PNR_CORNERS": (
            list(corners), "resolved STA_CORNERS from the same native step config"),
    })
    return configs


def overlay(R, project: Path, sdc: Path, scratch: Path) -> Dict[str, Tuple[Any, str]]:
    """Declared step-21 config for LibreLane, each value with its source.

    * `PNR_SDC_FILE`: the deck's SDC plus the sign-off STA's flat-OCV derate
      (`librelane_cts_hold.signoff_scene_sdc`): the post-GRT timing repair
      works in the scene the sign-off judges, as steps 19/20 do (T98).
    * the route checkers record only (`CHECKER_RECORD_ONLY`).
    * the post-GRT design and timing repairs run
      (`POST_GRT_DESIGN_REPAIR`, `STRICT_NATIVE_TIMING`).
    * a PPA candidate's non-timing `route_knobs` (`PPA_KNOBS`) apply; a
      conflicting timing override refuses rather than weakening the contract.
    """
    import librelane_cts_hold as _cts
    scene = _cts.signoff_scene_sdc(R, sdc, scratch)
    out: Dict[str, Tuple[Any, str]] = {
        "PNR_SDC_FILE": (str(scene.resolve()),
                         f"{sdc.name} + the sign-off STA's flat-OCV derate "
                         "(phase3_one_shot_runner._FLAT_OCV_DERATE_EARLY/LATE)")}
    out.update(CHECKER_RECORD_ONLY)
    out.update(POST_GRT_DESIGN_REPAIR)
    knobs = switch_knobs(project)
    conflicting = sorted(key for key in STRICT_NATIVE_TIMING
                         if key in knobs
                         and knobs[key][0] != STRICT_NATIVE_TIMING[key][0])
    if conflicting:
        raise ValueError(f"LL_STRICT_TIMING_OVERRIDE_FORBIDDEN: {conflicting}")
    out.update(knobs)
    # The source-required strict policy wins over an equivalent caller value,
    # so its provenance cannot be mislabeled as a PPA choice.
    out.update(STRICT_NATIVE_TIMING)
    return out


def route_log(folders: Sequence[Path], dest: Path, project: Path) -> Path:
    """One transcript of an arm's routing steps, in order, each bracketed by
    its step folder, for the one route reader (`_ppa.backends.openroad.parse_log`).
    The reader takes the LAST totals and the LAST violation count, which is
    the state the arm hands over."""
    parts = []
    for folder in folders:
        for tlog in sorted(Path(folder).glob("*.log")):
            if tlog.name == "invocation.log":
                continue
            parts.append(f"# >>> {tlog.relative_to(project)}\n"
                         + tlog.read_text(errors="replace")
                         + f"\n# <<< {tlog.relative_to(project)}\n")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _aa.write_text(dest, "".join(parts))
    return dest


def drt_runs(drt_folder: Path) -> List[Dict[str, Any]]:
    """Each detailed_route invocation of an `OpenROAD.DetailedRouting` step on
    its own (review70 step 21, correction): `drt.tcl` routes once and again
    inside its antenna loop, and every run logs `route__drc_errors__iter:N`
    into the same state, so the state's series mixes runs. Each `drt-run-N`
    directory holds that run's own marker report; this is read per run."""
    runs = []
    for run in sorted(drt_folder.glob("drt-run-*"),
                      key=lambda p: int(p.name.rsplit("-", 1)[-1])
                      if p.name.rsplit("-", 1)[-1].isdigit() else -1):
        reports = sorted(run.glob("*.drc"))
        count = None
        if reports:
            count = sum(1 for ln in reports[0].read_text(errors="replace").splitlines()
                        if "violation type:" in ln)
        runs.append({"run": run.name, "report": str(reports[0]) if reports else None,
                     "markers": count})
    return runs


def measure_arm(folder: Path, route_log_path: Path, measured_state: Path,
                corners: Sequence[str], scope: Dict[str, str],
                *, write: Callable[[Path, str], None]) -> Dict[str, Any]:
    """One arm's step-21 measurement in `librelane_contract.judge_step`'s shape.

    Route DRC, wirelength and vias: the arm's own router transcript, read by
    the one route reader (`_ppa.backends.openroad.parse_log`, the same reader
    the PPA layer uses). Antenna nets and per-corner setup: the same
    LibreLane `OpenROAD.CheckAntennas` + `OpenROAD.STAMidPNR`-per-corner chain
    run on every arm's routed ODB (`measured_state`)."""
    import librelane_contract as _ll
    from _ppa.backends import openroad as _orb
    folder.mkdir(parents=True, exist_ok=True)
    parsed = _orb.parse_log(route_log_path)
    derived: Dict[str, Any] = {}
    for metric, key in (("route.drc.violation.count", "vibeic__route__drc_errors"),
                        ("route.wirelength.um", "vibeic__route__wirelength_um"),
                        ("route.via.count", "vibeic__route__vias")):
        rows = [r for r in parsed.by_metric(metric) if r.get("status") == "MEASURED"]
        if rows:
            derived[key] = rows[-1]["value"]
    state = json.loads(measured_state.read_text())
    metrics = state.get("metrics") or {}
    ant = metrics.get("antenna__violating__nets")
    if isinstance(ant, (int, float)):
        derived["vibeic__antenna__violating_nets"] = ant
    for kind, name in (("ws", "ws"), ("tns", "tns")):
        values = [metrics.get(f"timing__setup__{kind}__corner:{c}") for c in corners]
        if values and all(isinstance(v, (int, float)) for v in values):
            derived[f"vibeic__setup__{name}__worst_corner"] = min(values)
    write(folder / "state_out.json", measured_state.read_text())
    write(folder / "metrics.json", json.dumps(derived, indent=2) + "\n")
    write(folder / "route_reader.json", json.dumps(
        {"log": str(route_log_path), "refusals": parsed.refusals,
         "records": [r for r in parsed.records if str(r.get("metric", "")).startswith(
             ("route.", "antenna."))]}, indent=2, default=str) + "\n")
    return _ll.judge_step(folder, [k for k, _ in OBJECTIVES], folder / "gate.json",
                          scope=scope)


def select(gates: Dict[str, Path], output: Path,
           *, write: Callable[[Path, str], None]) -> Dict[str, Any]:
    """The review's order of "better" (review70 step 21): an arm with router
    DRC 0 and antenna 0 is feasible and beats one that is not; among the
    feasible (or, when none is, among all), the Pareto frontier over every
    objective (`librelane_contract.select_arms`); a frontier tie is broken
    lexicographically in the review's order and recorded as such."""
    import librelane_contract as _ll
    docs = {n: json.loads(p.read_text()) for n, p in gates.items()}

    def _v(name: str, key: str) -> Any:
        return docs[name].get("metrics", {}).get(key, {}).get("value")

    feasible = [n for n in docs if docs[n].get("verdict") == "PASS"
                and _v(n, "vibeic__route__drc_errors") == 0
                and _v(n, "vibeic__antenna__violating_nets") == 0]
    pool = feasible or list(docs)
    selection = _ll.select_arms({n: gates[n] for n in pool}, dict(OBJECTIVES), output)
    selection = dict(selection, feasible=feasible, considered=pool)
    if selection.get("reason") == "LL_PARETO_TIE":
        def key(name: str) -> tuple:
            return tuple((v if sense == "min" else -v)
                         for v, sense in ((_v(name, k), s) for k, s in OBJECTIVES))
        selection = dict(selection, selection=min(selection["frontier"], key=key),
                         tie_break="review70 step 21 order: router DRC, antenna, "
                                   "wirelength, vias, worst-corner setup WNS, TNS")
    write(output, json.dumps(selection, indent=2) + "\n")
    return selection


def execute(
        R, *, project: Path, pdk: Any, container: str, out_dir: Path,
        out_dir_c: str, pnr_tcl: Path, mode: str, cmd: str,
        spare_plan: Optional[Dict[str, Any]], exec_kwargs: Dict[str, Any],
        cts_hold: Optional[Callable[..., Tuple[int, str, str]]] = None
) -> Tuple[int, str, str]:
    """Step 21 on LibreLane inside one PnR approach (see the module docstring).

    ``cts_hold`` is `librelane_cts_hold.execute` bound to its arguments when
    steps 19/20 are on LibreLane too: it runs up to and including their
    handoff and then calls back here (``after_handoff``) instead of resuming
    the deck itself. Returns `(rc, stdout, stderr)` like `R._docker_exec`. A
    refusal returns a nonzero rc with the refusal code in stdout and in the
    log; it never runs the direct region in its place."""
    import librelane_contract as _ll
    import shutil as _sh
    work = out_dir / "route_split"
    work.mkdir(parents=True, exist_ok=True)
    work_c = R._to_container_path(str(work), container)
    log_path = out_dir / "openroad.log"
    deck = pnr_tcl.read_text(errors="replace")
    pre = {k: work / f"pre_route.{k}" for k in ("odb", "def", "nl.v")}
    pnr_tcl_c = R._to_container_path(str(pnr_tcl), container)

    def _log(text: str) -> None:
        with log_path.open("a") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")

    def _refuse(code: str, detail: str, out: str = "") -> Tuple[int, str, str]:
        msg = f"{code}: {detail}"
        _log(f"PNR_ROUTE_REFUSED {msg}")
        # A tool the contract stopped answers with the session's own stop
        # code, which step_pnr books NOT_MEASURED; every other refusal is 1.
        return (_ll.tool_stop_session_rc(code) or 1,
                out + f"\nPNR_ROUTE_REFUSED {msg}\n", "")

    def _session(tcl_text: str, name: str, append: bool,
                 extra_outputs: Sequence[Path]) -> Tuple[int, str, str]:
        path = out_dir / name
        R._aa.write_text(path, tcl_text)
        path_c = R._to_container_path(str(path), container)
        run = cmd.replace(pnr_tcl_c, path_c)
        if append:
            run = run.replace(f"tee {out_dir_c}/openroad.log",
                              f"tee -a {out_dir_c}/openroad.log")
        return R._docker_exec(
            container, run, marker=path_c,
            outputs=[str(p) for p in R._pnr_session_products(out_dir, out_dir_c, tcl_text)]
            + [str(p) for p in extra_outputs], **exec_kwargs)

    for view in pre.values():
        view.unlink(missing_ok=True)
    ckpt = dict(odb_c=f"{work_c}/pre_route.odb", def_c=f"{work_c}/pre_route.def",
                nl_c=f"{work_c}/pre_route.nl.v")
    # The route region's `preroute_fill` stage ends with the PG re-connect and
    # its PG_NET_OWNERSHIP_AUDIT (the pnr gate's primary evidence); on the
    # tool path `OpenROAD.FillInsertion` placed the fillers, so the same block
    # (no re-route: the tool's route is final) runs on the restored database
    # before any post-route stage. MEASURED without it (spm, arm I2): the
    # post-route fill stage was skipped by an antenna rollback and pnr ended
    # NOT_MEASURED (PG_NET_OWNERSHIP_UNMEASURED).
    after_route = (R._after_restore_tcl(deck, spare_plan, reroutes_immediately=False)
                   + R._build_pg_reconnect_tcl(reroute=False))

    def _route_from_checkpoint(out: str, err: str) -> Tuple[int, str, str]:
        absent_paths = [str(v) for v in pre.values() if not (v.is_file() and v.stat().st_size)]
        if absent_paths:
            return _refuse("LL_ROUTE_CHECKPOINT_MISSING",
                           f"absent or empty pre-route checkpoint: {', '.join(absent_paths)}", out)
        return _route(out, err)

    def _route(out: str, err: str) -> Tuple[int, str, str]:
        image = _ll.resolve_image(project)
        # The contract's resolver for THIS design's PDK and image (F25): a
        # declared root, else the image's own PDK materialised on the host --
        # the same answer steps 15..20 and 32 get. MEASURED (T102 r4, spm
        # with no switch file): without the PDK and image the resolver has
        # only the declared sources, and the class-default route refused
        # LL_PDK_ROOT_NOT_DECLARED where the class-default 15..20 had run.
        pdk_root = _ll.resolve_pdk_root(project, str(pdk.name), image=image)
        if not pdk_root:
            return _refuse("LL_PDK_ROOT_NOT_DECLARED",
                           "phase3/librelane_switch.json pdk_root_host or "
                           "VIBEIC_LIBRELANE_PDK_ROOT", out)
        # This caller's steps name the PDK root itself (`--pdk-root /pdk`),
        # so the LOCAL route must be able to resolve that whole root on the
        # host too. A selected-PDK-only child mount leaves `/pdk` absent when
        # run_chain rewrites the CLI path for LOCAL execution.
        mounts = [(Path(pdk_root), _ll.PDK_GUEST_ROOT)]
        sdc = deck_sdc(R, deck, container=container, project=project, out_dir=out_dir)
        cfg_dir = project / "phase3/librelane/21-config"
        reserved = [i.get("name") for i in (spare_plan or {}).get("instances", [])
                    if i.get("name")] or None
        try:
            seeds = seed_arms(project) if mode == "dual" else []
            ov = overlay(R, project, sdc, cfg_dir)
            segment = chain_ids(image)
            all_ids = list(dict.fromkeys(segment + [DRT_SEEDED] * bool(seeds)
                                         + ["OpenROAD.CheckAntennas", "OpenROAD.STAMidPNR"]))
            configs = _ll.resolve_step_configs(
                project, image, str(pdk.name), all_ids, pdk_root=Path(pdk_root),
                folder="21-config", overlay=ov)
            gated_off = _ll.flow_gated_off(cfg_dir)
            ids = chain_ids(image, gated_off=gated_off)
            sta_cfg = json.loads(configs["OpenROAD.STAMidPNR"].read_text())
            corners = list(sta_cfg.get("STA_CORNERS") or [])
            if not corners:
                return _refuse("LL_STA_CORNERS_UNDECLARED",
                               str(configs["OpenROAD.STAMidPNR"]), out)
            measure = [("OpenROAD.CheckAntennas", configs["OpenROAD.CheckAntennas"])]
            for corner in corners:
                path = configs["OpenROAD.STAMidPNR"].with_name(
                    f"OpenROAD.STAMidPNR@{corner}.json")
                _ll.derive_step_config(
                    configs["OpenROAD.STAMidPNR"], path,
                    {"PNR_CORNERS": ([corner], "the resolved STA_CORNERS, one per "
                                               "run (STAMidPNR reports one corner)")})
                measure.append(("OpenROAD.STAMidPNR", path))
            state0 = _ll.state_from_direct(
                project, image, configs[ids[0]],
                {"odb": pre["odb"], "def": pre["def"], "nl": pre["nl.v"], "sdc": sdc},
                cfg_dir / "bridge", mounts=mounts,
                chain=[configs[s] for s in ids[1:]])
        except (_ll.Refusal, ValueError, OSError, R.PnrResumeUnavailable) as exc:
            return _refuse(getattr(exc, "code", "LL_ROUTE_CONFIG_REFUSED"), str(exc), out)

        def _ll_arm(lane: str, seed: Optional[int], *, configs=configs,
                    gated_off=gated_off, cfg_dir=cfg_dir) -> Dict[str, Any]:
            arm_ids = chain_ids(image, seeded=seed is not None, gated_off=gated_off)
            base = project / "phase3/librelane" / lane
            drt_index = next(i for i, s in enumerate(arm_ids) if s in (DRT, DRT_SEEDED))
            # run_chain names each step folder from its position; the reroute
            # reads the detailed route's own report from that folder.
            drt_folder = base / (f"{drt_index + 1:02d}-"
                                 + arm_ids[drt_index].lower().replace(".", "-"))
            nvr_config = named_violation_config(
                R, project=project, configs=configs, ids=arm_ids, lane=lane,
                cfg_dir=cfg_dir, reserved_instance_names=reserved)
            steps = []
            for sid in arm_ids:
                cfg = configs[sid]
                if sid == NVR:
                    cfg = nvr_config
                elif sid == DRT_SEEDED:
                    cfg = _ll.derive_step_config(cfg, cfg.with_name(f"{DRT_SEEDED}@{seed}.json"), {
                        "VIBEIC_DRT_OR_SEED": (seed, "phase3/librelane_switch.json "
                                                     "route_seeds (PPA seed arm)")})
                steps.append((sid, cfg))
            folders = _ll.run_chain(project, image, [(s, c, state0) for s, c in steps],
                                    mounts=mounts, lane=lane, pdk_root=_ll.PDK_GUEST_ROOT)
            if POST_GRT_REPAIR not in arm_ids:
                # DRV standard section 1: post-GRT repair is a required stage;
                # a chain the flow gated it out of records that it did not run.
                import drv_stage_receipts as _drv_stages
                _drv_stages.record_not_run(
                    project, "post_grt_repair",
                    f"{POST_GRT_REPAIR} is not in step 21's chain ({lane}); "
                    f"flow gates false: {gated_off.get(POST_GRT_REPAIR) or 'not requested'}")
            final = folders[-1] / "state_out.json"
            mfolders = _ll.run_chain(project, image, [(s, c, final) for s, c in measure],
                                     mounts=mounts, lane=f"{lane}-measure", pdk_root=_ll.PDK_GUEST_ROOT)
            return {"ids": arm_ids, "folders": folders, "final": final,
                    "drt": folders[drt_index], "nvr": folders[drt_index + 1],
                    "measured": mfolders[-1] / "state_out.json",
                    "antenna_state": mfolders[0] / "state_out.json"}

        arms_root = project / "phase3/tool_arms/21"
        scope = {"step": STEP, "design": _ll._def_design_name(pre["def"]) or "",
                 "corners": ",".join(corners),
                 "measured_by": "OpenROAD.CheckAntennas + OpenROAD.STAMidPNR per corner; "
                                "_ppa.backends.openroad.parse_log on the route transcript",
                 "input_odb_sha256": _ll.digest(pre["odb"])}

        def _judge(name: str, route_folders: Sequence[Path], measured: Path,
                   antenna_state: Path) -> Path:
            folder = arms_root / name
            rlog = route_log(route_folders, folder / "route.log", project)
            # antenna nets come from the arm's own CheckAntennas run; merge its
            # metric into the measured state the judge reads.
            mstate = json.loads(measured.read_text())
            ant = json.loads(antenna_state.read_text()).get("metrics", {}).get(
                "antenna__violating__nets")
            mstate.setdefault("metrics", {})["antenna__violating__nets"] = ant
            merged = folder / "measured_state.json"
            folder.mkdir(parents=True, exist_ok=True)
            R._aa.write_text(merged, json.dumps(mstate, indent=2) + "\n")
            measure_arm(folder, rlog, merged, corners, scope, write=R._aa.write_text)
            return folder / "gate.json"

        try:
            arms: Dict[str, Dict[str, Any]] = {"librelane": _ll_arm("21-route", None)}
            gates = {"librelane": _judge("librelane",
                                         [f for f in arms["librelane"]["folders"]
                                          if f in (arms["librelane"]["drt"],
                                                   arms["librelane"]["nvr"])],
                                         arms["librelane"]["measured"],
                                         arms["librelane"]["antenna_state"])}
            for seed in seeds:
                name = f"librelane_seed{seed}"
                arms[name] = _ll_arm(f"21-route-seed{seed}", seed)
                gates[name] = _judge(name, [arms[name]["drt"], arms[name]["nvr"]],
                                     arms[name]["measured"], arms[name]["antenna_state"])
        except (_ll.Refusal, ValueError, OSError, StopIteration) as exc:
            return _refuse(getattr(exc, "code", "LL_ROUTE_CHAIN_FAILED"), str(exc), out)
        selected = "librelane"
        selection: Dict[str, Any] = {"selection": "librelane", "mode": mode}
        views = {"odb": Path(json.loads(arms["librelane"]["final"].read_text())["odb"]),
                 "def": Path(json.loads(arms["librelane"]["final"].read_text())["def"]),
                 "drc": arms["librelane"]["nvr"] / "named_viol_after.drc"}
        if mode == "dual":
            arm = arms_root / "openroad"
            arm.mkdir(parents=True, exist_ok=True)
            arm_c = R._to_container_path(str(arm), container)
            try:
                arm_deck = direct_arm_deck(
                    R, deck, pre_odb_c=ckpt["odb_c"], pre_def_c=ckpt["def_c"],
                    out_dir_c=out_dir_c, arm_c=arm_c, after_restore_tcl=R._after_restore_tcl(
                        deck, spare_plan, reroutes_immediately=True))
            except R.PnrResumeUnavailable as exc:
                return _refuse("LL_ROUTE_DECK_UNSPLITTABLE", str(exc), out)
            arm_tcl = arm / "pnr_route_direct_arm.tcl"
            R._aa.write_text(arm_tcl, arm_deck)
            arm_tcl_c = R._to_container_path(str(arm_tcl), container)
            arm_cmd = (f"export PATH={R.TOOLS_IN_CONTAINER}/openroad/bin:"
                       f"{R.TOOLS_IN_CONTAINER}/bin:$PATH && openroad -no_init -exit "
                       f"{arm_tcl_c} > {arm_c}/openroad.log 2>&1")
            arc, _aout, _aerr = R._docker_exec(
                container, arm_cmd, marker=arm_tcl_c,
                **{k: v for k, v in exec_kwargs.items() if k == "hard_ceiling_s"})
            if arc != 0 or not (arm / "routed.odb").is_file():
                return _refuse("LL_DUAL_DIRECT_ARM_FAILED",
                               f"rc={arc}; {arm / 'openroad.log'}", out)
            try:
                mstate = _ll.state_from_direct(
                    project, image, measure[0][1],
                    {"odb": arm / "routed.odb", "def": arm / "routed_preantenna.def",
                     "nl": arm / "routed.nl.v", "sdc": sdc},
                    arm / "measure-bridge", mounts=mounts,
                    chain=[c for _, c in measure[1:]])
                mfolders = _ll.run_chain(project, image,
                                         [(s, c, mstate) for s, c in measure],
                                         mounts=mounts, lane="21-route-direct-measure", pdk_root=_ll.PDK_GUEST_ROOT)
            except (_ll.Refusal, OSError) as exc:
                return _refuse(getattr(exc, "code", "LL_ROUTE_CHAIN_FAILED"), str(exc), out)
            # The direct arm's transcript is a whole-session log; the judge
            # reads it through the same route reader.
            gates["openroad"] = _judge("openroad_judge", [arm],
                                       mfolders[-1] / "state_out.json",
                                       mfolders[0] / "state_out.json")
            selection = select(gates, arms_root / "selection.json", write=R._aa.write_text)
            if selection.get("selection") not in gates:
                return _refuse("LL_DUAL_UNDETERMINED",
                               json.dumps(selection, sort_keys=True), out)
            selected = selection["selection"]
            if selected == "openroad":
                views = {"odb": arm / "routed.odb", "def": arm / "routed_preantenna.def",
                         "drc": arm / R.ROUTER_DRC_REPORT_NAME}
            elif selected != "librelane":
                views = {"odb": Path(json.loads(arms[selected]["final"].read_text())["odb"]),
                         "def": Path(json.loads(arms[selected]["final"].read_text())["def"]),
                         "drc": arms[selected]["nvr"] / "named_viol_after.drc"}
        elif json.loads(gates["librelane"].read_text()).get("verdict") == "NOT_MEASURED":
            return _refuse("LL_ROUTE_NOT_MEASURED", str(gates["librelane"]), out)
        # The shipped route's post-GRT repair receipt is the SELECTED arm's
        # (seed arms and the step-32 pregrt arm rewrite it as they run).
        import drv_stage_receipts as _drv_stages
        _drv_stages.rebind_lane(
            project, list(zip(arms[selected]["ids"], arms[selected]["folders"]))
            if selected in arms else None,
            ("post_grt_repair",), selected)
        # Step 32 on LibreLane (T102 r2) runs HERE, on the routed database the
        # selection just chose, before the tail: LL21 -> Vibeic.PostRouteRepair
        # -> tail. `variant_arm` is this step's own LibreLane route with extra
        # declared config, which step 32's `dual` uses for its pre-DRT arm
        # (RUN_POST_GRT_*); nothing here selects between repair arms.
        step32 = getattr(R, "postroute_repair_after_route", None)
        post32: Optional[Dict[str, Any]] = None
        if step32 is not None:
            def _variant_arm(lane: str, extra: Dict[str, Tuple[Any, str]]) -> Dict[str, Any]:
                vdir = f"21-config-{lane}"
                vconfigs = _ll.resolve_step_configs(
                    project, image, str(pdk.name), all_ids, pdk_root=Path(pdk_root),
                    folder=vdir, overlay=dict(ov, **extra))
                vroot = project / "phase3/librelane" / vdir
                arm_ = _ll_arm(lane, None, configs=vconfigs,
                               gated_off=_ll.flow_gated_off(vroot), cfg_dir=vroot)
                arm_["route_drc"] = drt_runs(arm_["drt"])
                return arm_
            try:
                post32 = step32(project=project, pdk=pdk, image=image,
                                pdk_root=Path(pdk_root), sdc=sdc, deck=deck,
                                container=container,
                                route_state=(arms[selected]["final"]
                                             if selected in arms else None),
                                route_views={k: views[k] for k in ("odb", "def")},
                                route_drc=((drt_runs(arms[selected]["drt"]) or [{}])[-1]
                                           .get("markers") if selected in arms else None),
                                variant_arm=_variant_arm)
            except (_ll.Refusal, ValueError, OSError, StopIteration) as exc:
                return _refuse(getattr(exc, "code", "LL_PRR_REFUSED"), str(exc), out)
            if post32 is not None and post32.get("views"):
                views = dict(views, **post32["views"])
        targets = {"odb": out_dir / "routed_preantenna.odb",
                   "def": out_dir / "routed_preantenna.def",
                   "drc": out_dir / R.ROUTER_DRC_REPORT_NAME}
        receipt: Dict[str, Any] = {
            "program": "librelane_route.execute", "mode": mode, "selected": selected,
            "image": image, "corners": corners, "seeds": seeds,
            "flow_gated_off": gated_off,
            "arms": {n: {"steps": a["ids"],
                         "chain": [str(f.relative_to(project)) for f in a["folders"]],
                         "drt_runs": drt_runs(a["drt"])} for n, a in arms.items()},
            "gates": {n: str(p.relative_to(project)) for n, p in gates.items()},
            "pre_route": {k: {"path": str(v.relative_to(project)), "sha256": _ll.digest(v)}
                          for k, v in pre.items()},
            "selection": selection, "views": {},
            "postroute_repair": (post32 or {}).get("record")}
        for name in ("odb", "def", "drc"):
            src, dst = views[name], targets[name]
            if not src.is_file():
                return _refuse("LL_ROUTE_HANDOFF_VIEW_MISSING", f"{name}: {src}", out)
            replaced = _ll.digest(dst) if dst.is_file() else None
            _sh.copyfile(src, dst)
            receipt["views"][name] = {"source": str(src), "source_sha256": _ll.digest(src),
                                      "dest": str(dst.relative_to(project)),
                                      "dest_sha256": _ll.digest(dst), "replaced": replaced}
        handoff = project / "reports/phase3/librelane_route_handoff.json"
        handoff.parent.mkdir(parents=True, exist_ok=True)
        R._aa.write_text(handoff, json.dumps(receipt, indent=2) + "\n")
        # The tools' own transcripts go into the session log, bracketed, so the
        # log readers downstream (GRT-0273 disclosure, the DRT-0199 counts, the
        # stage attribution) read what the router printed.
        if selected != "openroad":
            _log(f"{R._PNR_STAGE_MARKER} global_route")
            for sid, folder in zip(arms[selected]["ids"], arms[selected]["folders"]):
                if sid == (DRT_SEEDED if selected.startswith("librelane_seed") else DRT):
                    _log(f"{R._PNR_STAGE_MARKER} detailed_route")
                for tlog in sorted(folder.glob("*.log")):
                    if tlog.name == "invocation.log":
                        continue
                    _log(f"# >>> LIBRELANE {sid} {tlog.relative_to(project)}")
                    _log(tlog.read_text(errors="replace"))
                    _log(f"# <<< LIBRELANE {sid}")
        else:
            _log(f"# >>> DIRECT ROUTE ARM {(arm / 'openroad.log').relative_to(project)}")
            _log((arm / "openroad.log").read_text(errors="replace"))
            _log("# <<< DIRECT ROUTE ARM")
        _log(f"PNR_ROUTE_HANDOFF: selected={selected} receipt="
             f"{handoff.relative_to(project)}")
        try:
            tail = tail_deck(R, deck, odb_c=f"{out_dir_c}/routed_preantenna.odb",
                             def_c=f"{out_dir_c}/routed_preantenna.def",
                             after_restore_tcl=after_route)
        except R.PnrResumeUnavailable as exc:
            return _refuse("LL_ROUTE_DECK_UNSPLITTABLE", str(exc), out)
        trc, tout, terr = _session(tail, "pnr_route_tail.tcl", True, [])
        summary = (f"\nPNR_ROUTE_HANDOFF: selected={selected} "
                   f"receipt={handoff.relative_to(project)}\n")
        # step_pnr's receipt writer checks THIS invocation's returned output,
        # not merely the on-disk log (which could belong to an older route).
        # Return only the selected arm's own route transcript, in the same
        # order in which it was spliced into openroad.log above.
        if selected == "openroad":
            selected_route = (arm / "openroad.log").read_text(errors="replace")
        else:
            selected_route = (arms_root / selected / "route.log").read_text(
                errors="replace")
        return (trc, (out or "") + "\n" + selected_route + summary + (tout or ""),
                (err or "") + (terr or ""))

    if cts_hold is not None:
        # Steps 19/20 on LibreLane: their split runs the head and the CTS/hold
        # chain, hands over post_hold.odb, then calls back here.
        def _after_handoff(post_hold_odb_c: str, post_hold_def_c: str,
                           after_restore_tcl: str, out: str, err: str) -> Tuple[int, str, str]:
            try:
                bridge = bridge_deck(R, deck, post_hold_odb_c=post_hold_odb_c,
                                     post_hold_def_c=post_hold_def_c,
                                     after_restore_tcl=after_restore_tcl, **ckpt)
            except R.PnrResumeUnavailable as exc:
                return _refuse("LL_ROUTE_DECK_UNSPLITTABLE", str(exc), out)
            brc, bout, berr = _session(bridge, "pnr_route_head.tcl", True, pre.values())
            if brc != 0:
                return brc, (out or "") + (bout or ""), (err or "") + (berr or "")
            return _route_from_checkpoint((out or "") + (bout or ""), (err or "") + (berr or ""))
        return cts_hold(after_handoff=_after_handoff)
    try:
        head = head_deck(R, deck, **ckpt)
    except R.PnrResumeUnavailable as exc:
        return _refuse("LL_ROUTE_DECK_UNSPLITTABLE", str(exc))
    rc, out, err = _session(head, "pnr_route_head.tcl", False, pre.values())
    if rc != 0 or not all(v.is_file() and v.stat().st_size for v in pre.values()):
        # The approach failed before the route (a placement failure, a GPL
        # divergence): the caller's retry ladder reads this session's log.
        return (rc or 1), out, err
    return _route_from_checkpoint(out, err)
