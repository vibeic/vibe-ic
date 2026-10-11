#!/usr/bin/env python3
"""R8 SDC environment derivation from design, pinned PDK, and Liberty."""
from __future__ import annotations

import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import _container_exec as _cex
import _path_layout as _pl
_SDC_ENV_KEYS = {
    "set_clock_uncertainty": "CLOCK_UNCERTAINTY_CONSTRAINT",
    "set_clock_transition": "CLOCK_TRANSITION_CONSTRAINT",
    "set_driving_cell": "SYNTH_DRIVING_CELL",
    "set_load": "OUTPUT_CAP_LOAD",
    "set_max_transition": "MAX_TRANSITION_CONSTRAINT",
    "set_max_capacitance": "MAX_CAPACITANCE_CONSTRAINT",
}
_SDC_ENV_NUMERIC = frozenset(_SDC_ENV_KEYS) - {"set_driving_cell"}
_PDK_KEYS = {**_SDC_ENV_KEYS, "set_max_fanout": "MAX_FANOUT_CONSTRAINT"}
_PDK_NUMERIC = _SDC_ENV_NUMERIC | {"set_max_fanout"}


def _sdc_environment_design_values(project: Path) -> Tuple[Dict[str, Tuple[str, str]], List[str]]:
    """Read strict L9 key/value rows; prose and unrelated tables are ignored."""
    values: Dict[str, Tuple[str, str]] = {}
    unread: List[str] = []
    aliases = {name: name for name in _SDC_ENV_KEYS}
    aliases.update({key: name for name, key in _SDC_ENV_KEYS.items()})
    for root in (project / "input" / "docs", _pl.generated_docs_dir(project)):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("L9*")):
            try:
                lines = path.read_text(errors="replace").splitlines()
            except OSError:
                unread.append(f"NOT_READ: design doc {path}")
                continue
            for lineno, line in enumerate(lines, 1):
                match = re.match(r"\s*\|\s*`?([A-Za-z_]+)`?\s*\|\s*\*{0,2}\s*([^|]+?)\s*\*{0,2}\s*\|", line)
                if not match:
                    continue
                name = aliases.get(match.group(1))
                if name is None or name in values:
                    continue
                raw = match.group(2).strip().strip("*` ")
                if name in _SDC_ENV_NUMERIC:
                    try:
                        number = float(raw)
                    except ValueError:
                        continue
                    if not math.isfinite(number) or number <= 0:
                        continue
                    # A literal SDC `set_load` is pF; the flow key
                    # OUTPUT_CAP_LOAD is fF. Store both internally as fF.
                    if name == "set_load" and match.group(1) == "set_load":
                        number *= 1000.0
                    raw = f"{number:g}"
                elif not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$]*/[A-Za-z_][A-Za-z0-9_]*", raw):
                    continue
                values[name] = (raw, f"design doc {path}:{lineno}")
    return values, unread


def _sdc_environment_pdk_values(liberty_path: str, container: str,
                                to_container_path: Optional[Callable[[str, str], str]] = None
                                ) -> Tuple[Dict[str, Tuple[str, str]], List[str]]:
    """Read the active PDK and cell-library LibreLane configs in the pinned image."""
    values: Dict[str, Tuple[str, str]] = {}
    unread: List[str] = []
    path = str(liberty_path or "")
    match = re.search(r"^(.*)/libs\.ref/([^/]+)/lib/", path)
    local = _cex.no_container_route()
    if not match or (not container and not local):
        return values, ["NOT_READ: pinned PDK SDC config path or container identity"]
    pdk_root, library = match.groups()
    root = f"{pdk_root}/libs.tech/librelane"
    for config in (f"{root}/config.tcl", f"{root}/{library}/config.tcl"):
        config_c = (to_container_path(config, container)
                    if to_container_path is not None else config)
        try:
            if local:
                body = Path(config_c).read_text(errors="replace")
            else:
                run = subprocess.run(_cex.docker_exec_argv(container, "cat", config_c),
                                     capture_output=True, text=True, timeout=60)
                if run.returncode != 0:
                    unread.append(f"NOT_READ: pinned PDK config {config_c}")
                    continue
                body = run.stdout
        except (OSError, subprocess.TimeoutExpired,
                _cex.ContainerImageMismatch):
            unread.append(f"NOT_READ: pinned PDK config {config_c}")
            continue
        for line in body.splitlines():
            found = re.match(r"\s*set\s+::env\(([A-Z_]+)\)\s+(\"[^\"]*\"|\S+)", line)
            if not found:
                continue
            key, raw = found.groups()
            name = next((name for name, var in _PDK_KEYS.items() if var == key), None)
            if name is None:
                continue
            raw = raw.strip('"').replace("$::env(STD_CELL_LIBRARY)", library)
            if name in _PDK_NUMERIC:
                try:
                    number = float(raw)
                except ValueError:
                    continue
                if not math.isfinite(number) or number <= 0:
                    continue
                raw = f"{number:g}"
            elif not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$]*/[A-Za-z_][A-Za-z0-9_]*", raw):
                continue
            values[name] = (raw, f"pinned PDK default {config_c}:{key}")
    return values, unread


def _sdc_environment_values(project: Path, liberty_path: str, container: str,
                            liberty_slew: Optional[float],
                            liberty_cap: Optional[float],
                            to_container_path: Optional[Callable[[str, str], str]] = None
                            ) -> Tuple[Dict[str, Tuple[str, str]], List[str]]:
    """Resolve each R8 command: design > pinned PDK > Liberty default."""
    design, unread_design = _sdc_environment_design_values(project)
    pdk, unread_pdk = _sdc_environment_pdk_values(
        liberty_path, container, to_container_path)
    liberty: Dict[str, Tuple[str, str]] = {}
    if liberty_slew is not None:
        liberty["set_max_transition"] = (f"{liberty_slew:g}",
                                         f"liberty default {liberty_path}:default_max_transition")
    if liberty_cap is not None:
        liberty["set_max_capacitance"] = (f"{liberty_cap:g}",
                                          f"liberty default {liberty_path}:default_max_capacitance")
    return {name: next((tier[name] for tier in (design, pdk, liberty) if name in tier))
            for name in _SDC_ENV_KEYS if any(name in tier for tier in (design, pdk, liberty))}, \
        unread_design + unread_pdk


#: R-0929-PAD-INPUT-DRIVE. The record of how a DIE top's bond-pad inputs are
#: driven, read by the Step-23 STA verdict (a NOT_MEASURED drive cannot PASS).
PAD_INPUT_DRIVE_REPORT = "reports/phase3/pad_input_drive.json"
PAD_INPUT_DRIVE_SCHEMA = "vibeic.pad_input_drive.v1"
_DESIGN_TIER = "design doc "


def _design_input_transition(project: Path) -> Optional[Tuple[str, str]]:
    """A design-declared off-chip input transition (ns): a strict L9 key/value
    row `set_input_transition | <ns>`, the same grammar as every R8 key."""
    for root in (project / "input" / "docs", _pl.generated_docs_dir(project)):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("L9*")):
            try:
                lines = path.read_text(errors="replace").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, 1):
                m = re.match(r"\s*\|\s*`?set_input_transition`?\s*\|"
                             r"\s*\*{0,2}\s*([^|]+?)\s*\*{0,2}\s*\|", line)
                if not m:
                    continue
                try:
                    number = float(m.group(1).strip().strip("*` "))
                except ValueError:
                    continue
                if math.isfinite(number) and number > 0:
                    return f"{number:g}", f"{_DESIGN_TIER}{path}:{lineno}"
    return None


#: The pad-ring producer's record; it names every IO Liberty it linked.
IO_PAD_RECORD = "reports/phase3/io_pad_chip_top.json"
_LIB_TIME_UNIT_NS = {"1ps": 1e-3, "10ps": 1e-2, "100ps": 1e-1, "1ns": 1.0,
                     "10ns": 10.0, "100ns": 100.0, "1us": 1e3}


def _liberty_blocks(text: str, kind: str) -> List[Tuple[str, str]]:
    """Every ``kind ("name") { ... }`` group directly inside ``text``, with its
    body, found by brace matching (Liberty groups nest; a regex cannot)."""
    out: List[Tuple[str, str]] = []
    for m in re.finditer(r"\b%s\s*\(\s*\"?([^\"()]*?)\"?\s*\)\s*\{" % kind, text):
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        out.append((m.group(1).strip(), text[m.end():i - 1]))
    return out


def _own_attrs(body: str) -> str:
    """A group's own simple attributes: its body with every nested group cut."""
    out, depth = [], 0
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


_PAD_ARC_TABLES = ("cell_rise", "cell_fall", "rise_transition", "fall_transition")


def _index_values(body: str, n: int) -> Optional[List[float]]:
    m = re.search(r"\bindex_%d\s*\(\s*\"([^\"]*)\"\s*\)" % n, body)
    if not m:
        return None
    try:
        vals = [float(x) for x in m.group(1).replace(",", " ").split()]
    except ValueError:
        return None
    return vals or None


def _io_pad_view(text: str, masters: Optional[set[str]] = None) -> Dict[str, object]:
    """The off-chip input-edge bracket one IO Liberty view characterises.

    For every bond-pad pin that receives an off-chip signal (``is_pad : true``,
    direction input/inout) the SLOW end is its ``max_transition`` (pin, else
    library default) and the FAST end is the smallest ``input_net_transition``
    index of the delay/transition tables whose ``related_pin`` is that pad
    (inline index, else the table template's). Where both exist the slow end is
    capped at the tables' largest index, so it is never an extrapolation. The
    view's bracket is the part common to all its pad pins (the slowest end
    that no pin's tables exceed, the fastest end every pin characterises): one
    SDC value reaches every pad port, and none of them may be extrapolated."""
    unit = re.search(r"\btime_unit\s*:\s*\"?\s*([0-9]+\s*[pnu]s)\"?", text)
    scale = _LIB_TIME_UNIT_NS.get((unit.group(1) if unit else "1ns").replace(" ", ""))
    lib = re.search(r"\blibrary\s*\(\s*\"?([^\"()]+?)\"?\s*\)", text)
    view: Dict[str, object] = {"library": lib.group(1).strip() if lib else None,
                               "pins": [], "pins_without_bound": 0,
                               "pins_without_fast_index": 0}
    if scale is None:
        view["why"] = "unrecognised time_unit"
        return view
    templates: Dict[str, Dict[int, str]] = {}
    for name, body in _liberty_blocks(text, "lu_table_template"):
        own = _own_attrs(body)
        templates[name] = {n: v.group(1) for n in (1, 2, 3)
                           for v in [re.search(r"\bvariable_%d\s*:\s*\"?(\w+)" % n, own)]
                           if v}
    template_index = {name: body for name, body in
                      _liberty_blocks(text, "lu_table_template")}
    lib_default = re.search(r"\bdefault_max_transition\s*:\s*([0-9.eE+-]+)", text)
    pins: List[Dict[str, object]] = []
    selected_cells = 0
    for cell, cell_body in _liberty_blocks(text, "cell"):
        if masters is not None and cell not in masters:
            continue
        selected_cells += 1
        cell_pins = _liberty_blocks(cell_body, "pin")
        for pin, pin_body in cell_pins:
            own = _own_attrs(pin_body)
            if not re.search(r"\bis_pad\s*:\s*true\b", own):
                continue
            direction = re.search(r"\bdirection\s*:\s*\"?(\w+)", own)
            if not direction or direction.group(1) not in ("input", "inout"):
                continue
            bound_m = (re.search(r"\bmax_transition\s*:\s*([0-9.eE+-]+)", own)
                       or lib_default)
            try:
                bound = float(bound_m.group(1)) * scale if bound_m else None
            except ValueError:
                bound = None
            axis: List[float] = []
            for _other, other_body in cell_pins:
                for _t, tbody in _liberty_blocks(other_body, "timing"):
                    rel = re.search(r"\brelated_pin\s*:\s*\"?(\w+)", _own_attrs(tbody))
                    if not rel or rel.group(1) != pin:
                        continue
                    for kind in _PAD_ARC_TABLES:
                        for tmpl, table in _liberty_blocks(tbody, kind):
                            for n, var in templates.get(tmpl, {}).items():
                                if var != "input_net_transition":
                                    continue
                                vals = (_index_values(table, n)
                                        or _index_values(template_index.get(tmpl, ""), n))
                                axis.extend(v * scale for v in vals or ())
            if bound is None and not axis:
                view["pins_without_bound"] = int(view["pins_without_bound"]) + 1
                continue
            slow = min([x for x in (bound, max(axis) if axis else None) if x is not None])
            fast = min(axis) if axis else None
            if fast is None:
                view["pins_without_fast_index"] = int(view["pins_without_fast_index"]) + 1
            pins.append({"pin": f"{cell}/{pin}", "slow_ns": slow, "fast_ns": fast})
    view["pins"] = pins
    view["selected_cells_present"] = bool(selected_cells)
    slows = [float(x["slow_ns"]) for x in pins]
    fasts = [float(x["fast_ns"]) for x in pins if x["fast_ns"] is not None]
    if not pins:
        view["why"] = "no bond-pad input pin with a documented bound"
    elif view["pins_without_fast_index"]:
        view["why"] = ("a bond-pad input pin has no characterised input_net_"
                       "transition index (no fastest edge)")
    elif min(slows) <= 0 or max(fasts) <= 0 or min(slows) < max(fasts):
        view["why"] = "the pad pins' characterised ranges do not overlap"
    else:
        view["slow_ns"], view["fast_ns"] = min(slows), max(fasts)
    return view


def _read_pdk_file(path: str, container: str,
                   to_container_path: Optional[Callable[[str, str], str]]
                   ) -> Tuple[Optional[str], str]:
    """(text, where) of a pinned-PDK file: from the container when one is
    named (the record's paths are container paths), else from this host."""
    if container:
        path_c = (to_container_path(path, container)
                  if to_container_path is not None else path)
        try:
            run = subprocess.run(_cex.docker_exec_argv(container, "cat", path_c),
                                 capture_output=True, text=True, timeout=120)
            if run.returncode == 0:
                return run.stdout, f"container {container}"
        except (OSError, subprocess.TimeoutExpired, _cex.ContainerImageMismatch):
            pass
    try:
        return Path(path).read_text(errors="replace"), "host"
    except OSError:
        return None, ""


def _signal_pad_instances(record: Dict[str, object]) -> Dict[str, object]:
    """The producer marks supply/connector records with ``kind``; they are
    not off-chip signal inputs or output timing paths."""
    return {name: pad for name, pad in (record.get("pad_instances") or {}).items()
            if not pad.get("kind")}


def _pdk_io_input_transition(project: Path, container: str = "",
                             to_container_path: Optional[Callable[[str, str], str]] = None
                             ) -> Tuple[Optional[Dict[str, object]], Dict[str, object]]:
    """The PDK IO-tier off-chip input-edge bracket, per linked IO view.

    R-0929-IO-INPUT-TRANSITION(-2): the IO views are those the pad-ring
    producer linked (``io_library_liberty``), each bound by sha256. Each view
    gives its own bracket (``_io_pad_view``): late analysis uses the slowest
    characterised pad edge, early/hold analysis the fastest one. Returns
    (None, why) when a view is unread or brackets nothing."""
    import hashlib
    import json
    basis: Dict[str, object] = {"record": IO_PAD_RECORD}
    rec_path = Path(project) / IO_PAD_RECORD
    try:
        raw = rec_path.read_bytes()
        record = json.loads(raw)
        libs = record.get("io_library_liberty")
        basis["record_sha256"] = hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, AttributeError):
        libs, record = None, {}
    if not isinstance(libs, list) or not any(isinstance(x, str) for x in libs):
        basis["why"] = (f"no IO Liberty recorded by the pad-ring producer "
                        f"({IO_PAD_RECORD} absent or without io_library_liberty)")
        return None, basis
    views: List[Dict[str, object]] = []
    masters = {p["master"] for p in _signal_pad_instances(record).values()
               if p.get("direction") in ("input", "inout") and p.get("master")}
    if masters:
        basis["input_pad_masters"] = sorted(masters)
    for lib in sorted(str(x) for x in libs if isinstance(x, str)):
        text, where = _read_pdk_file(lib, container, to_container_path)
        if text is None:
            views.append({"liberty": lib, "why": "NOT_READ"})
            continue
        view = _io_pad_view(text, masters or None)
        if masters and not view.get("selected_cells_present", True):
            continue  # This view models no input pad instantiated by the producer.
        view.update(liberty=lib, read_from=where,
                    sha256=hashlib.sha256(text.encode()).hexdigest())
        views.append(view)
    basis["views"] = views
    covered = {p["pin"].split("/", 1)[0] for v in views for p in v.get("pins", [])}
    if not views or masters - covered:
        basis["why"] = "no characterised IO input view for " + ", ".join(sorted(masters - covered))
        return None, basis
    bad = [f"{v['liberty']}: {v['why']}" for v in views if v.get("why")]
    if bad:
        basis["why"] = "IO Liberty " + "; ".join(bad)
        return None, basis
    bracket = {"views": [{"library": v["library"], "liberty": v["liberty"],
                          "sha256": v["sha256"], "max_ns": v["slow_ns"],
                          "min_ns": v["fast_ns"]} for v in views]}
    # Several views linked in one analysis (a multi-corner PnR): the part of
    # the bracket every linked view characterises, so none is extrapolated.
    bracket["common_max_ns"] = min(float(v["slow_ns"]) for v in views)
    bracket["common_min_ns"] = max(float(v["fast_ns"]) for v in views)
    if bracket["common_max_ns"] < bracket["common_min_ns"]:
        basis["why"] = "the linked IO views' characterised ranges do not overlap"
        return None, basis
    return bracket, basis


def render_pad_scene_sdc(scope: str) -> str:
    """Keep the same scene when a native tool exports and reloads its SDC."""
    return "set ::vibeic_scene_sdc {" + scope + "}\n" + scope


def pad_operating_scene(project: Path, core_liberty: str, container: str = "",
                        to_container_path=None) -> Dict[str, object]:
    """A generated pad wrapper's static timing mode and native IO pin limits.

    OpenSTA excludes constant-disabled arcs from path search, but its delay
    calculator still includes conditional arcs in the output slew. Apply only
    those already-disabled conditional edges for reports and counts, then restore
    them before any database edit or export. Active and unknown-mode edges
    remain. No user timing exception or limit is changed.
    """
    import json
    import hashlib
    try:
        record = json.loads((Path(project) / IO_PAD_RECORD).read_text())
    except (OSError, ValueError):
        return {}
    pads = _signal_pad_instances(record)
    if record.get("verdict") != "WROTE" or not pads:
        return {}
    selected = {p["master"] for p in pads.values() if p.get("master")}
    limits: Dict[Tuple[str, str], List[float]] = {}
    sources = {}
    for path in record.get("io_library_liberty") or []:
        text, _ = _read_pdk_file(path, container, to_container_path)
        if text is None:
            continue
        unit = re.search(r'\btime_unit\s*:\s*"\s*([0-9]+\s*[pnu]s)"', text)
        scale = _LIB_TIME_UNIT_NS.get(unit.group(1).replace(" ", "") if unit else "1ns")
        if scale is None:
            continue
        found = False
        for cell, body in _liberty_blocks(text, "cell"):
            if cell not in selected:
                continue
            for pin, pin_body in _liberty_blocks(body, "pin"):
                value = re.search(r'\bmax_transition\s*:\s*([0-9.eE+-]+)', _own_attrs(pin_body))
                if value:
                    limits.setdefault((cell, pin), []).append(float(value.group(1)) * scale)
                    found = True
        if found:
            sources[path] = hashlib.sha256(text.encode()).hexdigest()
    core_text, _ = _read_pdk_file(core_liberty, container, to_container_path)
    unit = re.search(r'\btime_unit\s*:\s*"\s*([0-9]+\s*[pnu]s)"', core_text or "")
    core_scale = _LIB_TIME_UNIT_NS.get(unit.group(1).replace(" ", "")) if unit else None
    ports = {p["port"]: min(limits[(p["master"], p["terminal"])]) / core_scale
             for p in pads.values() if core_scale and p.get("port")
             and (p.get("master"), p.get("terminal")) in limits}
    complete = bool(core_scale) and all(p.get("port") in ports for p in pads.values())
    # Both OpenROAD and the SDK's standalone OpenSTA resolve exact instance
    # names. Their regexp selectors differ; use the producer's actual names.
    selector = " ".join("{" + n + "}" for n in sorted(pads))
    # Edge objects cannot survive OpenDB edits: keep them only while the
    # immutable timing measurement runs, then remove those temporary constraints.
    # Preserve the procedure in native SDC exports for the next fixed row.
    scope = f"set ::vibeic_scene_pads [list {selector}]\n" + r'''if {[llength [info commands ::vibeic_native_report_check_types]] == 0} {
  rename ::report_check_types ::vibeic_native_report_check_types
  rename ::sta::max_slew_violation_count ::vibeic_native_max_slew_violation_count
  proc ::vibeic_with_pad_mode {command args} {
    report_worst_slack -max > /dev/null
    set removed {}
    foreach edge [concat {*}[get_timing_edges -of_objects [get_cells $::vibeic_scene_pads]]] {
      if {[$edge is_disabled_constant] && [$edge cond] ne "" && ![$edge is_disabled_constraint]} {
        set_disable_timing $edge
        lappend removed $edge
      }
    }
    try {
      puts "VIBEIC_PAD_STATIC_MODE [llength $removed] already-disabled conditional edges"
      uplevel 1 [linsert $args 0 $command]
    } finally {
      foreach edge $removed {unset_disable_timing $edge}
    }
  }
  proc ::report_check_types {args} {
    uplevel 1 [linsert $args 0 ::vibeic_with_pad_mode ::vibeic_native_report_check_types]
  }
  proc ::sta::max_slew_violation_count {args} {
    uplevel 1 [linsert $args 0 ::vibeic_with_pad_mode ::vibeic_native_max_slew_violation_count]
  }
}
if {[llength [info commands ::vibeic_native_write_sdc]] == 0} {
  rename ::write_sdc ::vibeic_native_write_sdc
  proc ::write_sdc {args} {
    uplevel 1 [linsert $args 0 ::vibeic_native_write_sdc]
    set handle [open [lindex $args end] a]
    try {
      puts $handle "set ::vibeic_scene_sdc [list $::vibeic_scene_sdc]"
      puts $handle $::vibeic_scene_sdc
    } finally {
      close $handle
    }
  }
}
'''
    return {"tcl": render_pad_scene_sdc(scope), "scope_tcl": scope,
            "core_cells": sorted({name for name, _ in _liberty_blocks(core_text or "", "cell")}),
            "core_liberty_sha256": hashlib.sha256(core_text.encode()).hexdigest() if core_text else None,
            "port_slew_limits": ports if complete else {},
            "liberty_sha256": sources, "complete_pin_limits": complete}


def _pad_input_drive(project: Path, values: Dict[str, Tuple[str, str]],
                     container: str = "",
                     to_container_path: Optional[Callable[[str, str], str]] = None
                     ) -> Tuple[Dict[str, Tuple[str, str]], Dict[str, object]]:
    """R-0929-PAD-INPUT-DRIVE: resolve the off-chip drive of a DIE's inputs.

    On a pad-ring (DIE) top every input is a bond-pad port. The core library's
    synthesis driving cell (a tiny inverter from the pinned PDK's LibreLane
    config) "driving" a pad's input capacitance is not a model of anything:
    measured on a routed gf180 die it put 50.8 ns on the clock port and turned
    9/9 positive scenes into -55.9 ns. The ladder is the design's declared
    driver or input transition, then the PDK IO-tier bracket; with neither the
    drive is NOT_MEASURED, and the STA verdict consumers must not read the
    ideal edge the deck is then left with as a sign-off PASS. HARDMACRO / core
    runs keep the synthesis driving cell (their inputs ARE driven on chip).
    The drive is rendered by ``render_pad_input_drive``; ``values`` loses the
    core driving cell on a DIE top.
    """
    try:
        import _tapeout_declaration as _td
        die = bool(_td.requests_pad_ring(project))
    except Exception as exc:  # noqa: BLE001 — an unreadable route is not a core route
        return values, {"schema": PAD_INPUT_DRIVE_SCHEMA, "applies": None,
                        "verdict": "NOT_MEASURED",
                        "reason": f"route undeterminable: {exc!r}"}
    if not die:
        return values, {"schema": PAD_INPUT_DRIVE_SCHEMA, "applies": False,
                        "verdict": "NOT_APPLICABLE",
                        "reason": "not a pad-ring (DIE) top; the synthesis "
                                  "driving cell models on-chip drive"}
    out = dict(values)
    cell = out.pop("set_driving_cell", None)
    record: Dict[str, object] = {"schema": PAD_INPUT_DRIVE_SCHEMA,
                                 "applies": True}
    if cell and cell[1].startswith(_DESIGN_TIER):
        record.update(verdict="DECLARED", model="set_driving_cell",
                      value=cell[0], source=cell[1])
        return out, record
    if cell:
        record["refused_core_driving_cell"] = {"value": cell[0],
                                               "source": cell[1]}
    return out, _resolve_undeclared_drive(project, record, container,
                                          to_container_path)


def _resolve_undeclared_drive(project: Path, record: Dict[str, object],
                              container: str,
                              to_container_path: Optional[Callable[[str, str], str]]
                              ) -> Dict[str, object]:
    found = _design_input_transition(project)
    if found:
        record.update(verdict="DECLARED", model="set_input_transition",
                      value=found[0], source=found[1])
        return record
    bracket, io_basis = _pdk_io_input_transition(project, container,
                                                 to_container_path)
    record["pdk_io_tier"] = io_basis
    if bracket:
        record.update(verdict="PDK_IO_TIER", model="set_input_transition -max/-min",
                      bracket=bracket,
                      source=f"PDK IO tier: {len(bracket['views'])} linked IO "
                             f"Liberty view(s) of {IO_PAD_RECORD}",
                      basis=("per scene, the linked IO view's slowest (late) "
                             "and fastest (early) characterised bond-pad input "
                             "edge; with several views linked, the range every "
                             "one of them characterises"))
        return record
    record.update(verdict="NOT_MEASURED", reason=(
        "no design-declared off-chip input driver/transition and no PDK "
        f"IO-tier value ({io_basis.get('why')}); the core synthesis driving "
        "cell never drives a bond pad (R-0929-PAD-INPUT-DRIVE), so "
        "input-launched and clock-latency timing is NOT_MEASURED"))
    return record


def render_pad_input_drive(record: Optional[Dict[str, object]],
                           time_scale: float = 1.0) -> List[str]:
    """The SDC lines of a resolved DIE drive (comments included). The command
    lines are also stored in the record (``sdc_lines``) so a gate can prove the
    sign-off deck carries them."""
    if not isinstance(record, dict) or not record.get("applies"):
        return []
    lines: List[str] = []
    refused = record.get("refused_core_driving_cell")
    if isinstance(refused, dict):
        lines.append(f"# R-0929-PAD-INPUT-DRIVE: core synthesis driving cell "
                     f"{refused.get('value')} ({refused.get('source')}) NOT "
                     f"applied: every input of this DIE top is a bond pad")
    verdict = record.get("verdict")
    if verdict == "NOT_MEASURED":
        lines.append(f"# NOT_MEASURED: OFFCHIP_INPUT_DRIVE; {record.get('reason')}")
        return lines
    source = record.get("source")
    if record.get("model") == "set_driving_cell":
        cell, pin = str(record.get("value")).split("/", 1)
        lines += [f"# R8 source: {source}",
                  f"set_driving_cell -lib_cell {cell} -pin {pin} [all_inputs]"]
    elif verdict == "DECLARED":
        lines += [f"# R8 source: {source}",
                  f"set_input_transition {float(record['value']) * time_scale:g} [all_inputs]"]
    elif verdict == "PDK_IO_TIER":
        b = record["bracket"]
        views = " ".join("{%s %g %g}" % (v["library"], float(v["max_ns"]) * time_scale,
                                         float(v["min_ns"]) * time_scale)
                         for v in b["views"])
        lines.append(f"# R8 source: {source} (R-0929-IO-INPUT-TRANSITION: "
                     "-max = slowest, -min = fastest characterised bond-pad edge "
                     "of the IO view linked in this scene)")
        for v in b["views"]:
            lines.append(f"#   {v['library']}: {v['liberty']} sha256 {v['sha256']} "
                         f"max {float(v['max_ns']):g} ns min {float(v['min_ns']):g} ns")
        lines += [
            f"set _vibeic_pad_views {{{views}}}",
            "set _vibeic_pad_linked {}",
            "foreach _vibeic_pad_v $_vibeic_pad_views { if {[llength [get_libs -quiet "
            "[lindex $_vibeic_pad_v 0]]]} { lappend _vibeic_pad_linked $_vibeic_pad_v } }",
            f"set _vibeic_pad_max {float(b['common_max_ns']) * time_scale:g}",
            f"set _vibeic_pad_min {float(b['common_min_ns']) * time_scale:g}",
            "if {[llength $_vibeic_pad_linked]} { set _vibeic_pad_max [lindex [lsort -real "
            "[lmap _vibeic_pad_v $_vibeic_pad_linked {lindex $_vibeic_pad_v 1}]] 0]; "
            "set _vibeic_pad_min [lindex [lsort -real -decreasing [lmap _vibeic_pad_v "
            "$_vibeic_pad_linked {lindex $_vibeic_pad_v 2}]] 0] }",
            "puts \"\\[INFO\\] R-0929-IO-INPUT-TRANSITION bond-pad input edge -max "
            "$_vibeic_pad_max -min $_vibeic_pad_min ([llength $_vibeic_pad_linked] IO "
            "view(s) linked)\"",
            "set_input_transition -max $_vibeic_pad_max [all_inputs]",
            "set_input_transition -min $_vibeic_pad_min [all_inputs]",
        ]
    return lines


def pad_drive_sdc_lines(record: Optional[Dict[str, object]],
                        time_scale: float = 1.0) -> List[str]:
    """The command (non-comment) lines the sign-off deck must carry."""
    return [ln for ln in render_pad_input_drive(record, time_scale)
            if ln and not ln.startswith("#")]


def staged_sdc_pad_input_drive(project: Path, text: str, staged_rel: str,
                               container: str = "",
                               to_container_path: Optional[Callable[[str, str], str]] = None,
                               time_scale: float = 1.0
                               ) -> Tuple[str, Dict[str, object]]:
    """The same ladder for a design-staged SDC on a DIE top.

    A staged deck that itself sets ``set_input_transition`` or
    ``set_driving_cell`` has DECLARED the drive (its own lines are the
    evidence). One that sets neither gets the L9 declaration, else the PDK IO
    bracket, else NOT_MEASURED, appended to the deck; the record is written
    either way, so a record from an earlier run can never stand for this deck.
    """
    _, record = _pad_input_drive(project, {}, container, to_container_path)
    if not record.get("applies"):
        return text, record
    own = [ln.strip() for ln in text.splitlines()
           if re.match(r"\s*(set_input_transition|set_driving_cell)\b", ln)]
    if own:
        record = {"schema": PAD_INPUT_DRIVE_SCHEMA, "applies": True,
                  "verdict": "DECLARED", "model": "design-staged SDC",
                  "source": f"design-staged SDC {staged_rel}", "sdc_lines": own}
        return text, record
    lines = render_pad_input_drive(record, time_scale)
    record["sdc_lines"] = pad_drive_sdc_lines(record, time_scale)
    if lines:
        text = text.rstrip("\n") + "\n# R-0929-PAD-INPUT-DRIVE (design-staged SDC "\
            "declares no input drive)\n" + "\n".join(lines) + "\n"
    return text, record


def liberty_time_scale(liberty_path: str) -> float:
    """Liberty time units per ns (the SDC's numbers are read in them)."""
    try:
        head = Path(liberty_path).read_text(errors="ignore")[:200000]
    except OSError:
        return 1.0
    head = re.sub(r"/\*.*?\*/|//[^\n]*", " ", head, flags=re.S)
    m = re.search(r'\btime_unit\s*:\s*"(\d+(?:\.\d+)?)\s*([pnum]?s)"', head)
    if not m:
        return 1.0
    return 1.0 / (float(m.group(1)) * {"ps": 1e-3, "ns": 1.0, "us": 1e3,
                                       "ms": 1e6}[m.group(2)])


def write_pad_input_drive_record(project: Path, record: Dict[str, object]) -> Path:
    import _atomic_artefact as _aa
    return _aa.write_json(Path(project) / PAD_INPUT_DRIVE_REPORT, record)


def pad_input_drive_not_measured(project: Path) -> Optional[str]:
    """The reason a sign-off STA verdict cannot PASS, or None.

    On a DIE top an absent or unreadable record is itself NOT_MEASURED: the
    drive was never resolved for the deck that was used."""
    import json
    try:
        doc = json.loads((Path(project) / PAD_INPUT_DRIVE_REPORT).read_text())
    except (OSError, ValueError):
        doc = None
    if isinstance(doc, dict):
        if doc.get("verdict") == "NOT_MEASURED":
            return str(doc.get("reason") or "pad input drive NOT_MEASURED")
        return None
    try:
        import _tapeout_declaration as _td
        die = bool(_td.requests_pad_ring(project))
    except Exception:  # noqa: BLE001
        die = False
    return (f"no {PAD_INPUT_DRIVE_REPORT} for this DIE top: the off-chip input "
            "drive was never resolved" if die else None)


def _sdc_environment_prefix(values: Dict[str, Tuple[str, str]],
                            unread: Sequence[str], time_scale: float = 1.0,
                            pad_drive: Optional[Dict[str, object]] = None) -> str:
    """Emit sourced commands and name every command that could not be emitted.

    Time-valued declarations are in ns; OpenSTA reads the active Liberty unit.
    ``NOT_READ`` names an inaccessible tier; ``NOT_MEASURED`` names each
    command it leaves unresolved. Readable tiers with no declaration use
    ``UNDECLARED`` instead.
    """
    lines = [f"# {item}" for item in unread]
    pad = pad_drive if isinstance(pad_drive, dict) and pad_drive.get("applies") else None
    lines += render_pad_input_drive(pad, time_scale)
    for name in _SDC_ENV_KEYS:
        if pad is not None and name == "set_driving_cell":
            continue
        if name not in values:
            status = "NOT_MEASURED" if unread else "UNDECLARED"
            reason = ("at least one source tier NOT_READ" if unread else
                      "no value in design, pinned PDK, or Liberty")
            lines.append(f"# {status}: {_SDC_ENV_KEYS[name]}; {reason}")
    for name in ("set_clock_uncertainty", "set_clock_transition",
                 "set_driving_cell", "set_load"):
        if name not in values or (pad is not None and name == "set_driving_cell"):
            continue
        raw, source = values[name]
        if name.startswith("set_clock_"):
            command = f"{name} {float(raw) * time_scale:g} [all_clocks]"
        elif name == "set_driving_cell":
            cell, pin = raw.split("/", 1)
            command = f"set_driving_cell -lib_cell {cell} -pin {pin} [all_inputs]"
        else:
            # LibreLane OUTPUT_CAP_LOAD is fF; OpenSTA set_load takes pF.
            command = f"set_load {float(raw) / 1000:g} [all_outputs]"
        lines.extend((f"# R8 source: {source}", command))
    return "\n".join(lines) + ("\n" if lines else "")
