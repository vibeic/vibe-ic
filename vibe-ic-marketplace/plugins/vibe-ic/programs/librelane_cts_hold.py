#!/usr/bin/env python3
"""librelane_cts_hold.py — steps 19 (CTS) and 20 (post-CTS hold repair) on LibreLane (T98).

Selected by `phase3/librelane_switch.json` (`"19"`/`"20"`: `librelane` or
`dual`, both the same) through `librelane_contract.selected_mode`. With both
`direct` (switch absent, or naming other steps) `phase3_one_shot_runner` runs
its single PnR session exactly as before and nothing here is called.

Otherwise one PnR approach is split at the deck's step-19/20 region
(`_PNR_CTS_HOLD_BEGIN`..`_PNR_CTS_HOLD_END`, emitted by the runner's deck
builder): the direct deck runs up to the region and checkpoints; the
checkpoint is bridged into LibreLane `OpenROAD.CTS` ->
`Vibeic.ClockPathDriveSizing` (#2160, a plugin step, `librelane_plugins/`) ->
`OpenROAD.ResizerTimingPostCTS`, then `OpenROAD.STAMidPNR` once per STA corner;
the selected views are handed to the paths the direct route reads, and the
deck resumes from the handed-over ODB after the region.

Every function that needs the runner's own machinery (its docker dispatch,
its deck surgery, its restore-time session state) takes the runner MODULE as
`R`: this module never imports the runner, because the runner is usually
`__main__` and importing it by name would load a second copy whose patched
names nobody reads.

chip-AGNOSTIC: no design, PDK, corner or cell literal. Every LibreLane config
value carries its declared source (MIGRATION_COMMON `librelane_config`).
"""
from __future__ import annotations

import json
import os as _os
import re
import sys as _sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))


def modes(project: Path) -> Dict[str, str]:
    """The contract switch for CTS (19) and post-CTS hold repair (20)."""
    import librelane_contract as _ll
    return {step: _ll.selected_mode(project, step) for step in ("19", "20")}


def refusal(modes: Dict[str, str]) -> Optional[str]:
    """Why a 19/20 selection cannot run, or None.

    Both steps live in one region of the deck (`R._PNR_CTS_HOLD_BEGIN`..`END`)
    and LibreLane's `OpenROAD.CTS` -> `OpenROAD.ResizerTimingPostCTS` is one
    chain, so they move together: `librelane` or `dual` for both."""
    if set(modes.values()) == {"direct"}:
        return None
    if modes["19"] != modes["20"]:
        return ("LL_CTS_HOLD_SPLIT_UNSUPPORTED: steps 19 and 20 share one deck "
                f"region and one LibreLane chain; select both the same ({modes})")
    return None


def tcl_brace_depth(lines: Sequence[str]) -> int:
    depth = 0
    for ln in lines:
        esc = False
        for ch in ln:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
    return depth


def head_deck(R, deck: str, *, odb_c: str, def_c: str, nl_c: str,
                            insts_c: str) -> str:
    """pnr.tcl up to the step-19/20 region, then a checkpoint and a stop.

    The checkpoint is the CTS input: the ODB (design + tech + libraries), the
    DEF and netlist beside it, and its instance names (the pre-CTS snapshot
    `Vibeic.ClockPathDriveSizing` needs to tell a CTS buffer from a cell no
    stage owns). The region must start at the top level of the deck, or
    cutting there would leave an open brace."""
    lines = deck.splitlines()
    cut = [i for i, ln in enumerate(lines) if ln.strip() == R._PNR_CTS_HOLD_BEGIN]
    if len(cut) != 1:
        raise R.PnrResumeUnavailable(
            f"pnr.tcl carries {len(cut)} {R._PNR_CTS_HOLD_BEGIN!r} markers; the "
            "step-19/20 region cannot be located")
    head = lines[:cut[0]]
    if tcl_brace_depth(head) != 0:
        raise R.PnrResumeUnavailable(
            "the step-19/20 region is not at the deck's top level")
    return "\n".join(head + [
        "# === Steps 19/20 on LibreLane (T98): stop before CTS. The rest of",
        "# this deck resumes from the ODB LibreLane hands back",
        "# (tail_deck). ===",
        f'puts "{R._PNR_STAGE_MARKER} cts_hold_checkpoint"',
        f"write_db {odb_c}",
        f"write_def {def_c}",
        f"write_verilog {nl_c}",
        f"set _vic_ci_fh [open {insts_c} w]",
        "foreach _vic_ci [[ord::get_db_block] getInsts] "
        "{ puts $_vic_ci_fh [$_vic_ci getName] }",
        "close $_vic_ci_fh",
        'puts "PNR_CTS_HOLD_SPLIT: pre-CTS checkpoint written"',
        "exit 0",
    ]) + "\n"


def tail_deck(R, deck: str, *, odb_c: str, def_c: str,
                            after_restore_tcl: str) -> str:
    """pnr.tcl resumed from the post-hold ODB: everything after the region.

    The same line surgery as the fatal-signal resume and the SDR child
    (`R._pnr_deck_from_checkpoint`), stopping the elision at
    `R._PNR_CTS_HOLD_END` instead of the route. `after_restore_tcl` re-asserts
    the session state an ODB does not carry (the spare pool's dont_touch, the
    PDN global-connect rules)."""
    return "\n".join(R._pnr_deck_from_checkpoint(
        deck, checkpoint_def_c=def_c, restore_odb_c=odb_c,
        after_restore_tcl=after_restore_tcl,
        elide_end=R._PNR_CTS_HOLD_END)) + "\n"


def direct_arm_deck(R, deck: str, *, pre_odb_c: str, pre_def_c: str,
                                  out_dir_c: str, arm_c: str,
                                  after_restore_tcl: str) -> str:
    """The direct arm of a `dual` 19/20 selection: the deck's own region, and
    only that, on the same pre-CTS checkpoint the LibreLane arm reads.

    Every path the region writes under the PnR directory is redirected into
    the arm's own directory, so neither arm writes a shipped artefact; the
    selected arm's views are handed over afterwards."""
    lines = R._pnr_deck_from_checkpoint(
        deck, checkpoint_def_c=pre_def_c, restore_odb_c=pre_odb_c,
        after_restore_tcl=after_restore_tcl, elide_end=R._PNR_CTS_HOLD_BEGIN)
    end = [i for i, ln in enumerate(lines) if ln.strip() == R._PNR_CTS_HOLD_END]
    if len(end) != 1:
        raise R.PnrResumeUnavailable(
            f"pnr.tcl carries {len(end)} {R._PNR_CTS_HOLD_END!r} markers")
    start = next(i for i, ln in enumerate(lines)
                 if ln.startswith("# --- floorplan..") and "elided" in ln)
    region = [ln.replace(out_dir_c + "/", arm_c + "/")
              for ln in lines[start + 1:end[0]]]
    return "\n".join(lines[:start + 1] + region + [
        f"write_db {arm_c}/post_hold.odb",
        'puts "PNR_CTS_HOLD_DIRECT_ARM: done"',
        "exit 0",
    ]) + "\n"


#: The hold-fix skill's area guardrail (skills/hold-fix/SKILL.md, guardrail
#: #2), the one budget the flow declares for hold buffering.  OpenROAD's
#: `-max_buffer_percent` bounds the COUNT of inserted buffers as a percentage
#: of instances; the same percentage is its declared ceiling.
HOLD_BUFFER_BUDGET_SOURCE = (
    "skills/hold-fix/SKILL.md guardrail #2 (hold buffers <= 5% of cell area); "
    "hold_area_budget_check.AREA_BUDGET_PCT")


#: The step-19/20 LibreLane knobs a PPA candidate may set, through
#: `phase3/librelane_switch.json` `"knobs"` (review70 ppa_layer_opportunity:
#: sweep clustering, buffer distance, NDR and the hold-repair margins, keep
#: the Pareto set).  `_ppa` writes one switch per candidate and reads the
#: measured arm back; this module never chooses a value itself.  The fanout
#: cap below still applies to a candidate's clustering size.
PPA_KNOBS = ("CTS_SINK_CLUSTERING_SIZE", "CTS_SINK_CLUSTERING_MAX_DIAMETER",
             "CTS_DISTANCE_BETWEEN_BUFFERS", "CTS_APPLY_NDR",
             "PL_RESIZER_HOLD_SLACK_MARGIN", "PL_RESIZER_HOLD_MAX_BUFFER_PCT",
             "PL_RESIZER_FIX_HOLD_FIRST")


def _switch_knobs(project: Path) -> Dict[str, Tuple[Any, str]]:
    path = project / "phase3/librelane_switch.json"
    try:
        knobs = json.loads(path.read_text()).get("knobs") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    unknown = sorted(set(knobs) - set(PPA_KNOBS))
    if unknown:
        raise ValueError(f"LL_CTS_HOLD_KNOB_UNKNOWN: {unknown}; allowed {list(PPA_KNOBS)}")
    return {k: (v, "phase3/librelane_switch.json knobs (PPA candidate)")
            for k, v in knobs.items()}


def overlay(R, project: Path, pdk_name: str, knobs: Dict[str, Any],
            fanout_target: Optional[int], fanout_source: str,
            scratch: Path, excluded_cells: Optional[Sequence[str]] = ()
            ) -> Dict[str, Tuple[Any, str]]:
    """Declared step-19/20 config for LibreLane, each value with its source.

    * `CTS_SINK_CLUSTERING_SIZE`: a reference-flow `CTS_CLUSTER_SIZE` (the
      operator's choice) wins, as in the direct deck; else the L19
      `MAX_FANOUT_CONSTRAINT` (emit_config); else the runner's own fanout cap
      (the SDC / sign-off `set_max_fanout`).  Never above the declared cap.
    * `CTS_DISTANCE_BETWEEN_BUFFERS`: never 0 (LibreLane's default, which
      skips the flag).  The reference-flow knob, else the direct deck's own
      policy value: at 0 TritonCTS collapsed spm x ihp-sg13g2 to a two-level
      tree whose root drove every leaf (MEASURED; 10 um and 40 um both cured it).
    * `PL_RESIZER_HOLD_MAX_BUFFER_PCT`: the hold-fix guardrail (5 %).
    * a PPA candidate's `"knobs"` in the switch (`PPA_KNOBS`) win over all of
      the above; the fanout cap is checked on the result.
    """
    import librelane_contract as _ll
    import hold_area_budget_check as _hab
    scratch.mkdir(parents=True, exist_ok=True)
    emitted = _ll.emit_config(project, pdk_name, scratch / "emitted_probe.json")
    overlay: Dict[str, Tuple[Any, str]] = {}
    # Step 19's hold resizer inserts ordinary cells. Apply the SAME run policy
    # as direct PnR and the placement arm, including delay-family masters.
    # Keep exclusions the PDK/design already supplied to LibreLane.
    inherited = emitted.get("EXTRA_EXCLUDED_CELLS") or []
    if not isinstance(inherited, list):
        raise ValueError("LL_CTS_EXCLUSION_POLICY_INVALID: EXTRA_EXCLUDED_CELLS")
    if excluded_cells is not None:
        overlay["EXTRA_EXCLUDED_CELLS"] = (
            sorted(set(inherited) | set(excluded_cells)),
            "resolved EXTRA_EXCLUDED_CELLS plus "
            "phase3_one_shot_runner._DONT_USE_FAMILY_PATTERNS over the run liberty")
    declared_cap = emitted.get("MAX_FANOUT_CONSTRAINT")
    candidate = _switch_knobs(project)
    if "CTS_SINK_CLUSTERING_SIZE" in candidate:
        overlay["CTS_SINK_CLUSTERING_SIZE"] = candidate["CTS_SINK_CLUSTERING_SIZE"]
    elif knobs.get("cts_cluster_size") is not None:
        overlay["CTS_SINK_CLUSTERING_SIZE"] = (
            int(knobs["cts_cluster_size"]),
            "input/reference_flow CTS_CLUSTER_SIZE (reference_flow_knobs.json)")
    elif "CTS_SINK_CLUSTERING_SIZE" not in emitted and fanout_target:
        overlay["CTS_SINK_CLUSTERING_SIZE"] = (int(fanout_target), fanout_source)
    size = (overlay.get("CTS_SINK_CLUSTERING_SIZE", (None,))[0]
            or emitted.get("CTS_SINK_CLUSTERING_SIZE"))
    if declared_cap is not None and size is not None and size > declared_cap:
        raise ValueError(
            f"LL_CTS_CLUSTER_EXCEEDS_FANOUT: CTS_SINK_CLUSTERING_SIZE {size} > "
            f"declared MAX_FANOUT_CONSTRAINT {declared_cap}")
    if knobs.get("cts_cluster_diameter") is not None:
        overlay["CTS_SINK_CLUSTERING_MAX_DIAMETER"] = (
            float(knobs["cts_cluster_diameter"]),
            "input/reference_flow CTS_CLUSTER_DIAMETER (reference_flow_knobs.json)")
    distance = knobs.get("cts_distance_between_buffers")
    overlay["CTS_DISTANCE_BETWEEN_BUFFERS"] = (
        (float(distance), "input/reference_flow CTS_DISTANCE_BETWEEN_BUFFERS "
                          "(reference_flow_knobs.json)")
        if distance is not None else
        (R._CTS_DEFAULT_DISTANCE_BETWEEN_BUFFERS_UM,
         "phase3_one_shot_runner._CTS_DEFAULT_DISTANCE_BETWEEN_BUFFERS_UM (the "
         "direct deck's policy; measured two-level collapse at 0)"))
    overlay["PL_RESIZER_HOLD_MAX_BUFFER_PCT"] = (
        _hab.AREA_BUDGET_PCT, HOLD_BUFFER_BUDGET_SOURCE)
    overlay.update(candidate)
    return overlay


def signoff_scene_sdc(R, sdc: Path, folder: Path) -> Path:
    """The deck's SDC plus the derate the sign-off STA applies.

    MEASURED (spm x gf180mcuD, 0.3.79, T98 arm A): ResizerTimingPostCTS
    repaired hold at every STA corner with no derate (SS +0.152 ns), and the
    runner's sign-off -- the same SPEF-free question asked with flat OCV
    early/late -- then found SS hold -0.35 ns on an input-port -> pad -> flop
    path whose capture clock carries 7.09 ns of insertion delay: the late
    derate on that clock alone is ~0.35 ns. A repair that does not see the
    sign-off's derate cannot close the sign-off's hold (review70 step 20: the
    repair scene must be the sign-off scene). LibreLane reads the SDC from
    `PNR_SDC_FILE` in every OpenROAD step, so the derate goes there, and the
    per-corner `STAMidPNR` measurement is taken in the same scene."""
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "signoff_scene.sdc"
    R._aa.write_text(out, sdc.read_text(errors="replace").rstrip("\n") + "\n"
                     "# vibe-ic T98: the sign-off STA's flat OCV "
                     "(phase3_one_shot_runner._FLAT_OCV_DERATE_EARLY/LATE)\n"
                     f"set_timing_derate -early {R._FLAT_OCV_DERATE_EARLY}\n"
                     f"set_timing_derate -late {R._FLAT_OCV_DERATE_LATE}\n")
    return out


def judge_arm(R, folder: Path, final_state: Path, corners: Sequence[str],
                        scope: Dict[str, str]) -> Dict[str, Any]:
    """One arm's step-19/20 measurement, in `librelane_contract.judge_step`'s
    shape: worst hold / setup slack over every STA corner (each measured by
    `OpenROAD.STAMidPNR` at that corner) and the hold-buffer count."""
    import librelane_contract as _ll
    folder.mkdir(parents=True, exist_ok=True)
    state = json.loads(final_state.read_text())
    metrics = state.get("metrics") or {}
    derived: Dict[str, Any] = {}
    for kind in ("hold", "setup"):
        values = [metrics.get(f"timing__{kind}__ws__corner:{c}") for c in corners]
        if values and all(isinstance(v, (int, float)) for v in values):
            derived[f"vibeic__{kind}__ws__worst_corner"] = min(values)
    for key in ("design__instance__count__hold_buffer",
                "design__instance__count__setup_buffer",
                "design__instance__count__class:clock_buffer"):
        if isinstance(metrics.get(key), (int, float)):
            derived[key] = metrics[key]
    R._aa.write_text(folder / "state_out.json", final_state.read_text())
    R._aa.write_text(folder / "metrics.json", json.dumps(derived, indent=2) + "\n")
    return _ll.judge_step(
        folder, ["vibeic__hold__ws__worst_corner", "vibeic__setup__ws__worst_corner"],
        folder / "gate.json", scope=scope)


def execute(
        R, *, project: Path, pdk: Any, container: str, out_dir: Path,
        out_dir_c: str, pnr_tcl: Path, modes: Dict[str, str], cmd: str,
        spare_plan: Optional[Dict[str, Any]], overlay: Dict[str, Tuple[Any, str]],
        exec_kwargs: Dict[str, Any],
        after_handoff: Optional[Callable[..., Tuple[int, str, str]]] = None
) -> Tuple[int, str, str]:
    """Steps 19/20 on LibreLane inside one PnR approach (T98).

    1. the direct deck runs up to `R._PNR_CTS_HOLD_BEGIN` and checkpoints;
    2. the checkpoint is bridged (`state_from_direct`) into LibreLane
       `OpenROAD.CTS` -> `Vibeic.ClockPathDriveSizing` (#2160) ->
       `Vibeic.ExternalCaptureLaunchRetap` ->
       `OpenROAD.ResizerTimingPostCTS`, then `OpenROAD.STAMidPNR` once per STA
       corner (the step measures one corner per run);
    3. with `dual`, the deck's own region runs on the same checkpoint and both
       arms are judged by the same STA; `select_arms` picks;
    4. the selected views go to `post_cts.def` / `post_hold.def` /
       `post_hold.odb` and the tool's `cts.rpt` to `cts/clock_tree.rpt`,
       all sha256-bound (`reports/phase3/librelane_cts_hold_handoff.json`);
    5. the deck resumes from `post_hold.odb` after `R._PNR_CTS_HOLD_END`;
       or, when step 21 is on LibreLane too (`librelane_route.execute`),
       ``after_handoff(post_hold_odb_c, post_hold_def_c, after_restore_tcl,
       out, err)`` continues from the handoff instead.

    Returns `(rc, stdout, stderr)` like `R._docker_exec`. A refusal returns a
    nonzero rc with the refusal code in stdout and in the log; it never runs
    the direct region in its place."""
    import librelane_contract as _ll
    import shutil as _sh
    work = out_dir / "cts_hold_split"
    work.mkdir(parents=True, exist_ok=True)
    work_c = R._to_container_path(str(work), container)
    log_path = out_dir / "openroad.log"
    deck = pnr_tcl.read_text(errors="replace")
    pre = {k: work / f"pre_cts.{k}" for k in ("odb", "def", "nl.v", "insts")}

    def _log(text: str) -> None:
        with log_path.open("a") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")

    def _refuse(code: str, detail: str, out: str = "") -> Tuple[int, str, str]:
        msg = f"{code}: {detail}"
        _log(f"PNR_CTS_HOLD_REFUSED {msg}")
        # A tool the contract stopped answers with the session's own stop
        # code, which step_pnr books NOT_MEASURED; every other refusal is 1.
        return (_ll.tool_stop_session_rc(code) or 1,
                out + f"\nPNR_CTS_HOLD_REFUSED {msg}\n", "")

    try:
        head = head_deck(
            R, deck, odb_c=f"{work_c}/pre_cts.odb", def_c=f"{work_c}/pre_cts.def",
            nl_c=f"{work_c}/pre_cts.nl.v", insts_c=f"{work_c}/pre_cts.insts")
        after = R._after_restore_tcl(deck, spare_plan, reroutes_immediately=True)
        tail = tail_deck(
            R, deck, odb_c=f"{out_dir_c}/post_hold.odb",
            def_c=f"{out_dir_c}/post_hold.def", after_restore_tcl=after)
    except R.PnrResumeUnavailable as exc:
        return _refuse("LL_CTS_HOLD_DECK_UNSPLITTABLE", str(exc))
    for view in pre.values():
        view.unlink(missing_ok=True)
    head_tcl = out_dir / "pnr_cts_head.tcl"
    tail_tcl = out_dir / "pnr_cts_tail.tcl"
    R._aa.write_text(head_tcl, head)
    R._aa.write_text(tail_tcl, tail)
    pnr_tcl_c = R._to_container_path(str(pnr_tcl), container)
    head_cmd = cmd.replace(pnr_tcl_c, R._to_container_path(str(head_tcl), container))
    rc, out, err = R._docker_exec(
        container, head_cmd, marker=R._to_container_path(str(head_tcl), container),
        outputs=[str(p) for p in R._pnr_session_products(out_dir, out_dir_c, head)]
        + [str(v) for v in pre.values()], **exec_kwargs)
    if rc != 0 or not all(v.is_file() and v.stat().st_size for v in pre.values()):
        # The approach failed before CTS (a placement failure, a GPL
        # divergence): the caller's retry ladder reads this session's log.
        return (rc or 1), out, err
    image = _ll.resolve_image(project)
    try:        # the contract's resolver, for the design's PDK (F25)
        pdk_root = _ll.pdk_root_resolution(project, str(pdk.name), image=image)["path"]
    except _ll.Refusal as exc:
        return _refuse("LL_PDK_ROOT_NOT_DECLARED", str(exc), out)
    # LibreLane's CLI receives the PDK_ROOT, not only the selected process
    # directory. Keep the same root at the same /pdk namespace used by the
    # placement chain; a child-only mount cannot resolve --pdk-root /pdk on
    # the LOCAL route and the CLI fails before CTS starts.
    mounts = [(Path(pdk_root), _ll.PDK_GUEST_ROOT)]
    sizing_tcl = work / "clock_path_drive_sizing.body.tcl"
    R._aa.write_text(sizing_tcl, R._clock_path_drive_sizing_tcl())
    ids = ["OpenROAD.CTS", "Vibeic.ClockPathDriveSizing",
           "Vibeic.ExternalCaptureLaunchRetap",
           "OpenROAD.ResizerTimingPostCTS", "OpenROAD.STAMidPNR"]
    # The SDC the deck itself reads, mapped back to the host.
    _sdc_m = re.search(r"(?m)^read_sdc\s+(\S+)", deck)
    sdc = (R._container_path_to_host(_sdc_m.group(1), container, project)
           if _sdc_m else out_dir / "constraint.sdc")
    try:
        scene_sdc = signoff_scene_sdc(R, sdc, project / "phase3/librelane/19-config")
        configs = _ll.resolve_step_configs(
            project, image, str(pdk.name), ids, pdk_root=Path(pdk_root),
            folder="19-config", overlay=dict(overlay, PNR_SDC_FILE=(
                str(scene_sdc.resolve()),
                f"{sdc.name} + the sign-off STA's flat-OCV derate "
                "(phase3_one_shot_runner._FLAT_OCV_DERATE_EARLY/LATE)")))
        configs, policy_steps = R._resolved_cell_policy(
            configs, Path(pdk_root), str(pdk.name),
            required=("OpenROAD.CTS", "OpenROAD.ResizerTimingPostCTS"))
        sta_cfg = json.loads(configs["OpenROAD.STAMidPNR"].read_text())
        corners = list(sta_cfg.get("STA_CORNERS") or [])
        if not corners:
            return _refuse("LL_STA_CORNERS_UNDECLARED",
                           str(configs["OpenROAD.STAMidPNR"]), out)
        configs["Vibeic.ClockPathDriveSizing"] = _ll.derive_step_config(
            configs["Vibeic.ClockPathDriveSizing"],
            configs["Vibeic.ClockPathDriveSizing"],
            {"PNR_CORNERS": (
                 corners, "resolved STA_CORNERS for external capture setup and hold"),
             "VIBEIC_CLKPATH_PRECTS_INSTANCES": (
                str(pre["insts"].resolve()),
                "instance names of the ODB OpenROAD.CTS reads (pre-CTS snapshot)"),
             "VIBEIC_CLKPATH_SIZING_TCL": (
                 str(sizing_tcl.resolve()),
                 "phase3_one_shot_runner._clock_path_drive_sizing_tcl"),
             "VIBEIC_CLKPATH_MAX_FANOUT": (
                 overlay.get("MAX_FANOUT_CONSTRAINT", (None,))[0]
                 if "MAX_FANOUT_CONSTRAINT" in overlay
                 else _ll.emit_config(
                     project, str(pdk.name), work / "emitted_fanout.json"
                 ).get("MAX_FANOUT_CONSTRAINT"),
                 "resolved MAX_FANOUT_CONSTRAINT; no value means no internal "
                 "CTS-tree fanout repair"),
             "VIBEIC_CLKPATH_CTS_BUFFERS": (
                 list(dict.fromkeys(x for x in (
                     list(json.loads(configs["OpenROAD.CTS"].read_text()).get(
                         "CTS_CLK_BUFFERS") or [])
                     + [json.loads(configs["OpenROAD.CTS"].read_text()).get(
                         "CTS_ROOT_BUFFER")]
                 ) if x)),
                 "resolved OpenROAD.CTS CTS_CLK_BUFFERS plus CTS_ROOT_BUFFER")})
        configs["Vibeic.ExternalCaptureLaunchRetap"] = _ll.derive_step_config(
            configs["Vibeic.ExternalCaptureLaunchRetap"],
            configs["Vibeic.ExternalCaptureLaunchRetap"],
            {"PNR_CORNERS": (
                 corners, "resolved STA_CORNERS for measured retap setup and hold"),
             "VIBEIC_CLKPATH_PRECTS_INSTANCES": (
                 str(pre["insts"].resolve()),
                 "instance names of the ODB OpenROAD.CTS reads (pre-CTS snapshot)")})
        sta_steps = []
        for corner in corners:
            path = configs["OpenROAD.STAMidPNR"].with_name(
                f"OpenROAD.STAMidPNR@{corner}.json")
            _ll.derive_step_config(
                configs["OpenROAD.STAMidPNR"], path,
                {"PNR_CORNERS": ([corner], "the resolved STA_CORNERS, one per "
                                           "run (STAMidPNR reports one corner)")})
            sta_steps.append(("OpenROAD.STAMidPNR", path))
        chain = [("OpenROAD.CTS", configs["OpenROAD.CTS"]),
                 ("Vibeic.ClockPathDriveSizing",
                  configs["Vibeic.ClockPathDriveSizing"]),
                 ("Vibeic.ExternalCaptureLaunchRetap",
                  configs["Vibeic.ExternalCaptureLaunchRetap"]),
                 ("OpenROAD.ResizerTimingPostCTS",
                  configs["OpenROAD.ResizerTimingPostCTS"])] + sta_steps
        state0 = _ll.state_from_direct(
            project, image, configs["OpenROAD.CTS"],
            {"odb": pre["odb"], "def": pre["def"], "nl": pre["nl.v"], "sdc": sdc},
            project / "phase3/librelane/19-config/bridge", mounts=mounts,
            chain=[c for _, c in chain[1:]])
        folders = _ll.run_chain(project, image, [(s, c, state0) for s, c in chain],
                                mounts=mounts, lane="19-cts-hold", pdk_root=_ll.PDK_GUEST_ROOT)
    except (_ll.Refusal, ValueError, OSError) as exc:
        return _refuse(getattr(exc, "code", "LL_CTS_HOLD_CHAIN_FAILED"), str(exc), out)
    cts_folder, sizing_folder, retap_folder, rsz_folder = folders[:4]
    import excluded_master_census_check as _emc
    excluded_census = {
        step: _emc.write_audit(config, folder / "state_out.json", step,
                               folder / "excluded_master_census.json",
                               policy_complete=step in policy_steps)
        for (step, config), folder in zip(chain, folders)
        if step in ("OpenROAD.CTS", "OpenROAD.ResizerTimingPostCTS")}
    arms_root = project / "phase3/tool_arms/19"
    scope = {"steps": "19,20", "design": _ll._def_design_name(pre["def"]) or "",
             "corners": ",".join(corners), "measured_by": "OpenROAD.STAMidPNR",
             "input_odb_sha256": _ll.digest(pre["odb"])}
    ll_gate = judge_arm(R, arms_root / "librelane", folders[-1] / "state_out.json",
                        corners, scope)
    selected = "librelane"
    selection: Dict[str, Any] = {"selection": "librelane", "mode": modes["19"]}
    measured_state = folders[-1] / "state_out.json"
    views = {"post_cts_def": Path(json.loads((retap_folder / "state_out.json")
                                             .read_text())["def"]),
             "post_hold_def": Path(json.loads((rsz_folder / "state_out.json")
                                              .read_text())["def"]),
             "post_hold_odb": Path(json.loads((rsz_folder / "state_out.json")
                                              .read_text())["odb"]),
             "cts_rpt": cts_folder / "cts.rpt"}
    if modes["19"] == "dual":
        arm = arms_root / "openroad"
        arm.mkdir(parents=True, exist_ok=True)
        arm_c = R._to_container_path(str(arm), container)
        try:
            arm_deck = direct_arm_deck(
                R, deck, pre_odb_c=f"{work_c}/pre_cts.odb",
                pre_def_c=f"{work_c}/pre_cts.def", out_dir_c=out_dir_c,
                arm_c=arm_c, after_restore_tcl=after)
        except R.PnrResumeUnavailable as exc:
            return _refuse("LL_CTS_HOLD_DECK_UNSPLITTABLE", str(exc), out)
        arm_tcl = arm / "pnr_cts_direct_arm.tcl"
        R._aa.write_text(arm_tcl, arm_deck)
        arm_tcl_c = R._to_container_path(str(arm_tcl), container)
        arm_cmd = (f"export PATH={R.TOOLS_IN_CONTAINER}/openroad/bin:"
                   f"{R.TOOLS_IN_CONTAINER}/bin:$PATH && openroad -no_init -exit "
                   f"{arm_tcl_c} > {arm_c}/openroad.log 2>&1")
        arc, aout, aerr = R._docker_exec(container, arm_cmd, marker=arm_tcl_c,
                                       **{k: v for k, v in exec_kwargs.items()
                                          if k == "hard_ceiling_s"})
        if arc != 0 or not (arm / "post_hold.odb").is_file():
            return _refuse("LL_DUAL_DIRECT_ARM_FAILED",
                           f"rc={arc}; {arm / 'openroad.log'}", out)
        try:
            arm_state = _ll.state_from_direct(
                project, image, sta_steps[0][1],
                {"odb": arm / "post_hold.odb", "def": arm / "post_hold.def",
                 "nl": pre["nl.v"], "sdc": sdc},
                arm / "bridge", mounts=mounts,
                chain=[c for _, c in sta_steps[1:]])
            arm_folders = _ll.run_chain(project, image,
                                        [(s, c, arm_state) for s, c in sta_steps],
                                        mounts=mounts, lane="19-cts-hold-direct-arm", pdk_root=_ll.PDK_GUEST_ROOT)
        except (_ll.Refusal, OSError) as exc:
            return _refuse(getattr(exc, "code", "LL_CTS_HOLD_CHAIN_FAILED"), str(exc), out)
        judge_arm(R, arm / "judge", arm_folders[-1] / "state_out.json",
                  corners, scope)
        selection = _ll.select_arms(
            {"librelane": arms_root / "librelane/gate.json",
             "openroad": arm / "judge/gate.json"},
            {"vibeic__hold__ws__worst_corner": "max",
             "vibeic__setup__ws__worst_corner": "max"},
            arms_root / "selection.json")
        if selection.get("reason") == "LL_PARETO_TIE":
            # The review's order of "better" (review70 step 19/20): hold WNS
            # at every corner first, then setup.  Recorded as the tie-break.
            gates = {n: json.loads(p.read_text()) for n, p in (
                ("librelane", arms_root / "librelane/gate.json"),
                ("openroad", arm / "judge/gate.json"))}
            key = lambda n: tuple(  # noqa: E731
                gates[n]["metrics"][k]["value"] for k in (
                    "vibeic__hold__ws__worst_corner",
                    "vibeic__setup__ws__worst_corner"))
            selection = dict(selection, selection=max(selection["frontier"], key=key),
                             tie_break="review70 order: worst-corner hold, then setup")
            R._aa.write_text(arms_root / "selection.json",
                           json.dumps(selection, indent=2) + "\n")
        if selection.get("selection") not in ("librelane", "openroad"):
            return _refuse("LL_DUAL_UNDETERMINED",
                           json.dumps(selection, sort_keys=True), out)
        selected = selection["selection"]
        if selected == "openroad":
            measured_state = arm_folders[-1] / "state_out.json"
            views = {"post_cts_def": arm / "post_cts.def",
                     "post_hold_def": arm / "post_hold.def",
                     "post_hold_odb": arm / "post_hold.odb",
                     "cts_rpt": None}
    elif ll_gate.get("verdict") == "NOT_MEASURED":
        return _refuse("LL_CTS_HOLD_NOT_MEASURED",
                       f"{arms_root / 'librelane/gate.json'}", out)
    targets = {"post_cts_def": out_dir / "post_cts.def",
               "post_hold_def": out_dir / "post_hold.def",
               "post_hold_odb": out_dir / "post_hold.odb",
               "cts_rpt": R._pl.cts_dir(project) / "clock_tree.rpt"}
    receipt: Dict[str, Any] = {
        "program": "phase3_one_shot_runner.execute",
        "modes": modes, "selected": selected, "image": image,
        "steps": [s for s, _ in chain], "corners": corners,
        "chain": {s: str(f.relative_to(project)) for (s, _), f in zip(chain, folders)},
        "pre_cts": {k: {"path": str(v.relative_to(project)), "sha256": _ll.digest(v)}
                    for k, v in pre.items()},
        "gate": str((arms_root / "librelane/gate.json").relative_to(project)),
        "measured_state": str(measured_state.relative_to(project)),
        "measured_state_sha256": _ll.digest(measured_state),
        "selection": selection, "views": {}}
    receipt["excluded_master_census"] = excluded_census
    # Written in this order so every report is newer than the DEF it
    # describes (the #519 emitter keys on that).
    for name in ("post_cts_def", "post_hold_def", "post_hold_odb", "cts_rpt"):
        src = views[name]
        dst = targets[name]
        if src is None:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        replaced = _ll.digest(dst) if dst.is_file() else None
        _sh.copyfile(src, dst)
        receipt["views"][name] = {"source": str(src), "source_sha256": _ll.digest(src),
                                  "dest": str(dst.relative_to(project)),
                                  "dest_sha256": _ll.digest(dst), "replaced": replaced}
    handoff = project / "reports/phase3/librelane_cts_hold_handoff.json"
    handoff.parent.mkdir(parents=True, exist_ok=True)
    R._aa.write_text(handoff, json.dumps(receipt, indent=2) + "\n")
    # Step19 owns CTS evidence independently of the later hold handoff. Use
    # the selected arm's real pre-hold state, never the post-hold measurement.
    cts_receipt = dict(receipt, views={name: view for name, view in receipt['views'].items()
                                     if name in ('post_cts_def', 'cts_rpt')})
    if selected == 'librelane':
        cts_state = retap_folder / 'state_out.json'
        cts_receipt['steps'] = [step for step, _ in chain[:3]]
        cts_receipt['chain'] = {step: str(folder.relative_to(project))
                                for (step, _), folder in zip(chain[:3], folders[:3])}
        cts_receipt['measured_state'] = str(cts_state.relative_to(project))
        cts_receipt['measured_state_sha256'] = _ll.digest(cts_state)
    else:
        # The direct deck records CTS in its DEF/report, not a structured
        # pre-hold state. Its existing direct readers judge those actual files.
        cts_receipt.pop('measured_state', None)
        cts_receipt.pop('measured_state_sha256', None)
        cts_receipt['steps'] = []
        cts_receipt['chain'] = {}
    R._aa.write_text(handoff.with_name('librelane_cts_handoff.json'),
                    json.dumps(cts_receipt, indent=2) + "\n")
    if selected == "librelane":
        # hold_area_budget_check's producer (#1980): the resizer step's own
        # standard-cell area metric before and after it ran.  The step repairs setup
        # AND hold, so the delta is an upper bound on the hold-buffer area.
        def _area(folder: Path) -> Any:
            return json.loads((folder / "state_out.json").read_text()).get(
                "metrics", {}).get("design__instance__area__stdcell")
        rsz_metrics = json.loads((rsz_folder / "state_out.json").read_text()
                                 ).get("metrics", {})
        area_doc = {
            "program": "phase3_one_shot_runner.execute",
            "before_total_area": _area(retap_folder),
            "after_total_area": _area(rsz_folder),
            "hold_buffer_count": rsz_metrics.get(
                "design__instance__count__hold_buffer"),
            "setup_buffer_count": rsz_metrics.get(
                "design__instance__count__setup_buffer"),
            "numerator_basis": (
                "OpenROAD.ResizerTimingPostCTS design__instance__area__stdcell "
                "after - before (pad cells excluded: on spm x gf180mcuD they "
                "are 3.36 of 4.05 mm2 of instance area and would dilute the "
                "guardrail 6x); the step repairs setup and hold, so this "
                "bounds the hold-buffer area from above"),
            "sources": {"before": str((retap_folder / "state_out.json")
                                      .relative_to(project)),
                        "after": str((rsz_folder / "state_out.json")
                                     .relative_to(project))}}
        area_path = project / "reports/phase3/pnr/hold_area.json"
        area_path.parent.mkdir(parents=True, exist_ok=True)
        R._aa.write_text(area_path, json.dumps(area_doc, indent=2) + "\n")
    # The tools' own transcripts go into the session log, bracketed, so every
    # log reader downstream (stage attribution, CTS-0018, the #519 emitter)
    # reads what TritonCTS and the resizer printed, not a relabelled summary.
    _log(f"{R._PNR_STAGE_MARKER} cts")
    for label, folder in (("OpenROAD.CTS", cts_folder),
                          ("Vibeic.ClockPathDriveSizing", sizing_folder),
                          ("Vibeic.ExternalCaptureLaunchRetap", retap_folder),
                          ("OpenROAD.ResizerTimingPostCTS", rsz_folder)):
        if label == "OpenROAD.ResizerTimingPostCTS":
            _log(f"{R._PNR_STAGE_MARKER} hold_repair")
        for tlog in sorted(folder.glob("*.log")):
            if tlog.name == "invocation.log":
                continue
            _log(f"# >>> LIBRELANE {label} {tlog.relative_to(project)}")
            _log(tlog.read_text(errors="replace"))
            _log(f"# <<< LIBRELANE {label}")
    _log(f"PNR_CTS_HOLD_HANDOFF: selected={selected} receipt="
         f"{handoff.relative_to(project)}")
    if after_handoff is not None:
        return after_handoff(f"{out_dir_c}/post_hold.odb", f"{out_dir_c}/post_hold.def",
                             after, out, err)
    tail_cmd = cmd.replace(pnr_tcl_c, R._to_container_path(str(tail_tcl), container)
                           ).replace(f"tee {out_dir_c}/openroad.log",
                                     f"tee -a {out_dir_c}/openroad.log")
    trc, tout, terr = R._docker_exec(
        container, tail_cmd, marker=R._to_container_path(str(tail_tcl), container),
        outputs=[str(p) for p in R._pnr_session_products(out_dir, out_dir_c, tail)],
        **exec_kwargs)
    summary = (f"\nPNR_CTS_HOLD_HANDOFF: selected={selected} "
               f"receipt={handoff.relative_to(project)}\n")
    return trc, (out or "") + summary + (tout or ""), (err or "") + (terr or "")
