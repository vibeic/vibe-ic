"""Retained signoff-scene STA consumer of the shared OpenROAD.RCX output.

LibreLane's RCX uses ``-lef_res``.  The direct Phase-3 signoff extracts with
``-corner_cnt 1 -max_res 50 -coupling_threshold 0.1``; on a routed candidate
those recipes can disagree at a zero-slack boundary.  This module measures the
same routed ODB at every declared RC/process scene before a controller accepts
setup or hold closure. It never changes a route or a constraint. The
production step-32 caller supplies its own native RCX state; that path never
extracts again. The legacy extraction entry remains for the explicit direct
arm until its HARVEST destinations have merged. AOCV-or-flat scene handling
and normalized serialized SDC are still owned here pending that migration.
"""
from __future__ import annotations

import vibeic_temp as _vtmp

import fnmatch
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _docker_memory as _dmem

_SLACK = re.compile(r"^worst slack (max|min)\s+([-+]?\d+(?:\.\d+)?)\s*$", re.M)
_DERATE = re.compile(r"^\s*set_timing_derate\s+-(early|late)\s+"
                     r"([-+]?\d+(?:\.\d+)?)\s*(?:#.*)?$", re.I)
_OCV_BASIS = re.compile(r"^OCV_BASIS (flat_ocv|flat_ocv_fallback|aocv_table)$", re.M)


def _one(mapping: dict[str, Any], corner: str, what: str) -> Any:
    values = [value for pattern, value in mapping.items() if fnmatch.fnmatch(corner, pattern)]
    if len(values) != 1:
        raise ValueError(f"{what}: {corner} matches {len(values)} entries")
    return values[0]


def _q(path: Any) -> str:
    """Quote a resolved, generated Tcl path without evaluating Tcl syntax."""
    value = str(path)
    if any(ch in value for ch in "{}\n\r"):
        raise ValueError(f"unsafe Tcl path: {value!r}")
    return "{" + value + "}"


def _run(ctx: dict[str, Any], script: Path, output: Path) -> None:
    import librelane_contract as ll
    project = Path(ctx["project"]).resolve()
    volumes = ["-v", f"{project}:{project}"]
    for host, guest in ctx["mounts"]:
        volumes.extend(["-v", f"{Path(host).resolve()}:{guest}:ro"])
    network, command = ll.native_tool_command(
        ctx["image"], ["openroad", "-no_init", "-exit", str(script)])
    network_args = (["--network", network]
                    if ll._provider_for_image(ctx["image"]) is not None else [])
    argv = ["docker", "run", *_vtmp.docker_mounts(), *_dmem.docker_memory_flags(), "--rm", *network_args, *volumes,
            "--entrypoint", command[0], ctx["image"], *command[1:]]
    output.unlink(missing_ok=True)
    result = ll.run_container(argv, supervised=True, log=script.with_suffix(".log"))
    script.with_suffix(".log").write_text((result.stdout or "") + "\n" + (result.stderr or ""))
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        raise ll.Refusal("NATIVE_POSTROUTE_STA_FAILED",
                         f"{script}: rc={result.returncode}; output={output.is_file()}")


def _measurement_sdc(ctx: dict[str, Any], source: Path, out_dir: Path) -> tuple[Path, float, float]:
    """Remove the bridge's flat OCV so the direct signoff recipe runs once.

    LibreLane's ``write_sdc`` carries the flat derate from ``signoff_scene``.
    A direct signoff deck starts from the design SDC and emits its OCV commands
    after ``read_sdc``.  Refuse an unknown derate instead of silently stacking
    a design-specific policy with the direct recipe.
    """
    import librelane_contract as ll
    values = ctx.get("derate")
    if (not isinstance(values, (list, tuple)) or len(values) != 2
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   for value in values)):
        raise ll.Refusal("NATIVE_POSTROUTE_OCV_UNDECLARED", str(values))
    early, late = map(float, values)
    if not all(math.isfinite(v) for v in (early, late)) or not 0 < early <= 1 <= late:
        raise ll.Refusal("NATIVE_POSTROUTE_OCV_INVALID", str(values))
    found: dict[str, float] = {}
    clean: list[str] = []
    for line in source.read_text().splitlines():
        if not re.match(r"^\s*set_timing_derate\b", line, re.I):
            clean.append(line)
            continue
        match = _DERATE.fullmatch(line)
        if match is None or match.group(1).lower() in found:
            raise ll.Refusal("NATIVE_POSTROUTE_OCV_AMBIGUOUS", f"{source}: {line}")
        kind = match.group(1).lower()
        actual = float(match.group(2))
        expected = early if kind == "early" else late
        if not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-6):
            raise ll.Refusal("NATIVE_POSTROUTE_OCV_MISMATCH",
                             f"{source}: {kind}={actual} expected={expected}")
        found[kind] = actual
    if found and set(found) != {"early", "late"}:
        raise ll.Refusal("NATIVE_POSTROUTE_OCV_INCOMPLETE", f"{source}: {found}")
    target = out_dir / "measurement_scene.sdc"
    target.write_text("\n".join(clean) + "\n")
    return target, early, late


def _ocv_tcl(report: Path, early: float, late: float,
             aocv_table: str | None) -> list[str]:
    """Use the direct signoff's AOCV-or-flat order before either WNS query."""
    flat = [f"set_timing_derate -early {early}",
            f"set_timing_derate -late {late}"]
    if aocv_table:
        lines = [f"if {{[catch {{read_aocv {_q(aocv_table)}}} _aocv_err]}} {{",
                 *("  " + line for line in flat),
                 "  set _vibeic_ocv_basis flat_ocv_fallback",
                 "} else {", "  set _vibeic_ocv_basis aocv_table", "}"]
    else:
        lines = [*flat, "set _vibeic_ocv_basis flat_ocv"]
    return [*lines, f"set _vibeic_ocv [open {_q(report)} w]",
            'puts $_vibeic_ocv "OCV_BASIS $_vibeic_ocv_basis"',
            "close $_vibeic_ocv"]


def measure(ctx: dict[str, Any], repair_state: Path, out_dir: Path) -> dict[str, Any]:
    """Return WNS for all declared scenes, refusing any missing/ambiguous view."""
    import librelane_contract as ll
    state = json.loads(repair_state.read_text())
    odb = Path(state["odb"])
    sdc = Path(state["sdc"])
    if not odb.is_file() or not sdc.is_file():
        raise ll.Refusal("NATIVE_POSTROUTE_INPUT_MISSING", f"{odb}; {sdc}")
    cfg = json.loads(Path(ctx["configs"]["OpenROAD.RCX"]).read_text())
    corners = ctx["corners"]
    rulesets = cfg["RCX_RULESETS"]
    cell_libs = cfg.get("LIB", cfg.get("CELL_LIBS"))
    pad_libs = cfg.get("PAD_LIBS") or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    measured_sdc, early, late = _measurement_sdc(ctx, sdc, out_dir)
    aocv_table = ctx.get("aocv_table")
    if aocv_table is not None and (not isinstance(aocv_table, str) or not aocv_table):
        raise ll.Refusal("NATIVE_POSTROUTE_AOCV_INVALID", repr(aocv_table))
    default_libs = _one(cell_libs, cfg["DEFAULT_CORNER"], "default cell liberty")
    # Reuse one SPEF per RC ruleset.  The direct signoff's three parasitic
    # scenes (nom/min/max) can each serve every matching process library.
    parasitics: dict[str, Path] = {}
    rcx_binding = None
    if ctx.get('rcx_state'):
        import librelane_signoff as signoff
        rcx_state = Path(ctx['rcx_state'])
        if ll.digest(rcx_state) != ctx.get('rcx_state_sha256'):
            raise ll.Refusal('NATIVE_POSTROUTE_RCX_STATE_DRIFT', str(rcx_state))
        rcx_binding = signoff.bind_rcx_spefs(rcx_state.parent, repair_state, list(corners))
    setup: dict[str, float] = {}
    hold: dict[str, float] = {}
    applied: dict[str, str] = {}
    for corner in corners:
        rules = _one(rulesets, corner, "RCX ruleset")
        if rcx_binding is not None:
            spef = Path(rcx_binding['scenes'][corner]['path'])
            parasitics[corner] = spef
        elif rules not in parasitics:
            index = len(parasitics)
            spef = out_dir / f"rc_{index}.spef"
            script = out_dir / f"extract_{index}.tcl"
            lines = [f"read_db {_q(odb)}"]
            lines += [f"read_liberty {_q(lib)}" for lib in default_libs]
            lines += ["if {[catch {set_wire_rc -signal -layer Metal1} _s]} { catch {set_wire_rc -layer Metal1} }",
                      "catch {set_wire_rc -clock -layer Metal5}",
                      "catch {define_process_corner -ext_model_index 0 X}",
                      f"extract_parasitics -ext_model_file {_q(rules)} -corner_cnt 1 -max_res 50 -coupling_threshold 0.1",
                      f"write_spef {_q(spef)}", "exit"]
            script.write_text("\n".join(lines) + "\n")
            _run(ctx, script, spef)
            parasitics[rules] = spef
        spef = parasitics[corner] if rcx_binding is not None else parasitics[rules]
        report = out_dir / f"sta_{corner}.rpt"
        script = out_dir / f"sta_{corner}.tcl"
        libs = _one(cell_libs, corner, "cell liberty")
        pads = _one(pad_libs, corner, "pad liberty") if pad_libs else []
        lines = [f"read_db {_q(odb)}"]
        lines += [f"read_liberty {_q(lib)}" for lib in [*libs, *pads]]
        lines += [f"read_sdc {_q(measured_sdc)}", f"read_spef {_q(spef)}",
                  "set_propagated_clock [all_clocks]",
                  *_ocv_tcl(report, early, late, aocv_table),
                  f"report_worst_slack -max -digits 6 >> {_q(report)}",
                  f"report_worst_slack -min -digits 6 >> {_q(report)}", "exit"]
        script.write_text("\n".join(lines) + "\n")
        _run(ctx, script, report)
        report_text = report.read_text()
        bases = _OCV_BASIS.findall(report_text)
        if len(bases) != 1:
            raise ll.Refusal("NATIVE_POSTROUTE_OCV_UNVERIFIED", f"{corner}: {report}")
        applied[corner] = bases[0]
        slacks = {kind: float(value) for kind, value in _SLACK.findall(report_text)}
        if set(slacks) != {"max", "min"}:
            raise ll.Refusal("NATIVE_POSTROUTE_SLACK_MISSING", f"{corner}: {report}")
        setup[corner] = slacks["max"]
        hold[corner] = slacks["min"]
    if not setup or set(setup) != set(corners) or set(hold) != set(corners):
        raise ll.Refusal("NATIVE_POSTROUTE_SCENE_MISSING", str(out_dir))
    if len(set(applied.values())) != 1:
        raise ll.Refusal("NATIVE_POSTROUTE_OCV_INCONSISTENT", str(applied))
    mode = next(iter(applied.values()))
    ocv = {"mode": mode, **({"table": aocv_table} if aocv_table else {})}
    if mode != "aocv_table":
        ocv.update(early=early, late=late)
    return {"setup_ws": setup, "hold_ws": hold,
            "setup_ws_min": min(setup.values()), "hold_ws_min": min(hold.values()),
            "native_timing_dir": str(out_dir),
            "native_odb_sha256": ll.digest(odb), "native_sdc_sha256": ll.digest(sdc),
            "native_measurement_sdc_sha256": ll.digest(measured_sdc),
            "native_spef_sha256": {rules: ll.digest(path) for rules, path in parasitics.items()},
            "ocv_applied": ocv,
            "rcx_binding": rcx_binding,
            "retained_dual_gap": "SIGNOFF_SCENE_STA_HARVEST_PENDING_MERGE",
            "measurement_basis": (("OpenROAD.RCX" if rcx_binding else "direct_phase3_rcx_recipe")
                                  + f"+post_route_spef+{mode}")}
