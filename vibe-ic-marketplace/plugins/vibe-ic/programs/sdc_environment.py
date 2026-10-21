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


_LIBERTY_GAP = r"(?:\s|/\*.*?\*/|//[^\r\n]*(?:\r?\n|$))*"
_LIBERTY_HEADER_SCAN = re.compile(
    r'(?P<block>/\*.*?\*/)|(?P<line>//[^\r\n]*)|'
    r'(?P<string>"(?:\\.|[^"\\])*")|'
    r'(?P<header>\bcell' + _LIBERTY_GAP + r'\(' + _LIBERTY_GAP
    + r'(?:(?:"(?P<quoted>(?:\\.|[^"\\])*)")|'
      r'(?P<bare>[A-Za-z_][A-Za-z0-9_.$/:+-]*))'
    + _LIBERTY_GAP + r'\)' + _LIBERTY_GAP + r'\{)', re.S)


def _liberty_offset_is_code(text: str, stop: int) -> bool:
    """Whether ``stop`` is outside a Liberty comment or quoted string."""
    state, i = "code", 0
    while i < stop:
        pair = text[i:i + 2]
        if state == "code":
            if pair == "/*":
                state, i = "block", i + 2
                continue
            if pair == "//":
                state, i = "line", i + 2
                continue
            if text[i] == '"':
                state = "string"
        elif state == "block":
            if pair == "*/":
                state, i = "code", i + 2
                continue
        elif state == "line":
            if text[i] in "\r\n":
                state = "code"
        elif text[i] == "\\":
            i += 2
            continue
        elif text[i] == '"':
            state = "code"
        i += 1
    return state == "code"


def _liberty_may_have_selected_cell(text: str, masters: set[str]) -> bool:
    """Cheap conservative prefilter for exact Liberty ``cell`` headers.

    The scan runs in the regex engine and ignores complete comments and
    unrelated quoted strings.  Quoted/unquoted headers and comments between
    their tokens are supported.  Other attributes and longer cell names do not
    count: only the exact finite producer-selected master set can admit a deep
    structural parse.
    """
    if not masters:
        return False
    # Most linked PDK views cannot contain a producer-selected master at all.
    # Reject those bytes with the string engine before the grammar scanner
    # walks every quoted attribute and comment in a potentially large Liberty
    # file.  This is conservative: any exact quoted/bare header, and any
    # escaped spelling that could contain a selected master, necessarily
    # contains the master's literal bytes.  A comment/string-only occurrence
    # still reaches the grammar scan below and cannot fabricate a cell header.
    name_chars = r"A-Za-z0-9_.$/:+\-"
    may_name_exact = any(re.search(
        rf"(?<![{name_chars}]){re.escape(master)}(?![{name_chars}])", text)
        for master in masters)
    if not may_name_exact:
        return False
    names = "|".join(re.escape(master) for master in sorted(masters, key=len,
                                                            reverse=True))
    exact_header = re.compile(
        r"\bcell" + _LIBERTY_GAP + r"\(" + _LIBERTY_GAP
        + rf'(?:"(?:{names})"|(?:{names}))'
        + _LIBERTY_GAP + r"\)" + _LIBERTY_GAP + r"\{", re.S)
    for hit in exact_header.finditer(text):
        if _liberty_offset_is_code(text, hit.start()):
            return True
    # Preserve the prior conservative handling for unusual escaped cell names.
    # This slow fallback is unreachable for ordinary exact headers above.
    if not any("\\" + master in text for master in masters):
        return False
    for hit in _LIBERTY_HEADER_SCAN.finditer(text):
        if hit.group("header") is not None:
            name = hit.group("quoted")
            if name is None:
                name = hit.group("bare")
            if name in masters:
                return True
            # An escaped selected header is outside the exact supported name
            # grammar; deep-parse it rather than proving absence.
            if name and "\\" in name and any(master in name for master in masters):
                return True
    return False


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
    library default) and the table bracket is the intersection of every
    ``input_net_transition`` axis whose ``related_pin`` is that pad (inline
    index, else the table template's). Where both exist the slow end is capped
    at the intersected tables' upper end, so it is never an extrapolation. The
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
            axis_ranges: List[Tuple[float, float]] = []
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
                                if vals:
                                    axis_ranges.append((min(vals) * scale,
                                                        max(vals) * scale))
            if bound is None and not axis_ranges:
                view["pins_without_bound"] = int(view["pins_without_bound"]) + 1
                continue
            # One external stimulus reaches every simultaneously applicable
            # receiver table.  Its legal bracket is therefore the
            # INTERSECTION of their input_net_transition axes, not the union
            # of every sampled index.  A pin/library max_transition is an
            # additional upper bound; receiver-output limits are unrelated.
            table_slow = min((hi for _lo, hi in axis_ranges), default=None)
            slow = min(x for x in (bound, table_slow) if x is not None)
            fast = max((lo for lo, _hi in axis_ranges), default=None)
            if fast is None:
                view["pins_without_fast_index"] = int(view["pins_without_fast_index"]) + 1
            pins.append({"pin": f"{cell}/{pin}", "slow_ns": slow,
                         "fast_ns": fast})
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


def _liberty_capacitance_unit_pf(text: str) -> Optional[float]:
    """Return the pF represented by one Liberty capacitance unit."""
    match = re.search(
        r"\bcapacitive_load_unit\s*\(\s*([0-9.eE+-]+)\s*,\s*([fpnu]f)\s*\)",
        text, re.I)
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None
    scale = {"ff": 1e-3, "pf": 1.0, "nf": 1e3, "uf": 1e6}.get(
        match.group(2).lower())
    return number * scale if scale is not None and number > 0 else None


def _core_pad_models(project: Path, container: str = "",
                     to_container_path: Optional[Callable[[str, str], str]] = None
                     ) -> Tuple[Optional[Dict[str, Dict[str, object]]], Dict[str, object]]:
    """Resolve the producer-selected pad cells at their core-facing pins.

    Input ports need a real PAD -> core-output timing arc.  Output ports need
    the core-facing input capacitance from every linked view that contains the
    selected master.  The result is bound to the producer record and Liberty
    bytes; a name-only pad guess is never admitted.
    """
    import hashlib
    import json

    basis: Dict[str, object] = {"record": IO_PAD_RECORD}
    try:
        raw = (Path(project) / IO_PAD_RECORD).read_bytes()
        record = json.loads(raw)
    except (OSError, ValueError, TypeError):
        basis["why"] = "pad producer record is absent or unreadable"
        return None, basis
    basis["record_sha256"] = hashlib.sha256(raw).hexdigest()
    pads = _signal_pad_instances(record) if isinstance(record, dict) else {}
    basis["signal_pad_instance_count"] = len(pads)
    required = ("port", "master", "terminal", "core_pin", "direction")
    incomplete = [name for name, pad in pads.items()
                  if any(not isinstance(pad.get(key), str) or not pad.get(key)
                         for key in required)]
    if not pads or incomplete:
        basis["why"] = ("no signal pad instances" if not pads else
                        "incomplete signal pad instances: " + ", ".join(incomplete))
        return None, basis
    libs = record.get("io_library_liberty")
    if not isinstance(libs, list) or not libs:
        basis["why"] = "pad producer names no linked IO Liberty"
        return None, basis

    views: List[Dict[str, object]] = []
    cell_views: Dict[str, List[Tuple[str, str, float]]] = {}
    selected = {str(pad["master"]) for pad in pads.values()}
    read_views = 0
    deep_parsed = 0
    for path in sorted(str(item) for item in libs if isinstance(item, str)):
        text, where = _read_pdk_file(path, container, to_container_path)
        if text is None:
            views.append({"liberty": path, "why": "NOT_READ"})
            continue
        read_views += 1
        sha = hashlib.sha256(text.encode()).hexdigest()
        unit_pf = _liberty_capacitance_unit_pf(text)
        found = []
        may_have_selected = _liberty_may_have_selected_cell(text, selected)
        if may_have_selected:
            deep_parsed += 1
            for cell, body in _liberty_blocks(text, "cell"):
                if cell in selected:
                    cell_views.setdefault(cell, []).append((path, body, unit_pf or 0.0))
                    found.append(cell)
        views.append({"liberty": path, "read_from": where, "sha256": sha,
                      "capacitance_unit_pf": unit_pf,
                      "deep_parsed": may_have_selected,
                      "selected_masters": sorted(found)})
    basis["views"] = views
    basis["read_view_count"] = read_views
    basis["deep_parsed_view_count"] = deep_parsed
    basis["prefilter_skipped_view_count"] = read_views - deep_parsed

    models: Dict[str, Dict[str, object]] = {}
    errors: List[str] = []
    resolved_signatures: Dict[Tuple[str, str, str, str],
                              Tuple[Dict[str, object], List[str]]] = {}
    for name, pad in sorted(pads.items()):
        master = str(pad["master"])
        terminal = str(pad["terminal"])
        core_pin = str(pad["core_pin"])
        direction = str(pad["direction"])
        model: Dict[str, object] = {
            "instance": name, "port": str(pad["port"]), "master": master,
            "terminal": terminal, "core_pin": core_pin, "direction": direction,
        }
        signature = (master, terminal, core_pin, direction)
        if signature not in resolved_signatures:
            resolved: Dict[str, object] = {}
            signature_errors: List[str] = []
            present = cell_views.get(master, [])
            if not present:
                signature_errors.append(
                    f"master {master} absent from linked IO Liberty")
            if present and direction in ("input", "inout"):
                missing_arc = []
                for path, cell_body, _unit_pf in present:
                    pin_bodies = dict(_liberty_blocks(cell_body, "pin"))
                    core_body = pin_bodies.get(core_pin)
                    terminal_body = pin_bodies.get(terminal)
                    core_dir = (re.search(r"\bdirection\s*:\s*\"?(\w+)",
                                          _own_attrs(core_body or "")))
                    terminal_dir = (re.search(r"\bdirection\s*:\s*\"?(\w+)",
                                              _own_attrs(terminal_body or "")))
                    has_arc = any(
                        (lambda rel: bool(rel and rel.group(1) == terminal))(
                            re.search(r"\brelated_pin\s*:\s*\"?([^\";\s]+)",
                                      _own_attrs(timing)))
                        for _unused, timing in
                        _liberty_blocks(core_body or "", "timing"))
                    if (not core_dir or core_dir.group(1) != "output"
                            or not terminal_dir
                            or terminal_dir.group(1) not in ("input", "inout")
                            or not has_arc):
                        missing_arc.append(path)
                if missing_arc:
                    signature_errors.append(
                        f"no {terminal}->{core_pin} input-pad arc in "
                        + ", ".join(missing_arc))
                else:
                    resolved["input_arc"] = f"{terminal}->{core_pin}"
            if present and direction in ("output", "inout"):
                caps: List[float] = []
                missing_cap = []
                for path, cell_body, unit_pf in present:
                    pin_body = dict(_liberty_blocks(cell_body, "pin")).get(core_pin)
                    cap = re.search(r"\bcapacitance\s*:\s*([0-9.eE+-]+)",
                                    _own_attrs(pin_body or ""))
                    if not cap or unit_pf <= 0:
                        missing_cap.append(path)
                        continue
                    try:
                        value = float(cap.group(1)) * unit_pf
                    except ValueError:
                        value = -1.0
                    if not math.isfinite(value) or value < 0:
                        missing_cap.append(path)
                    else:
                        caps.append(value)
                if missing_cap or not caps:
                    signature_errors.append(
                        f"no sourced {core_pin} capacitance in "
                        + ", ".join(missing_cap
                                    or [p for p, _b, _u in present]))
                else:
                    resolved["core_load_pf"] = {
                        "min": min(caps), "max": max(caps)}
            resolved_signatures[signature] = (resolved, signature_errors)
        resolved, signature_errors = resolved_signatures[signature]
        model.update(resolved)
        errors.extend(f"{name}: {reason}" for reason in signature_errors)
        models[str(pad["port"])] = model
    if errors:
        basis["why"] = "; ".join(errors)
        return None, basis
    return models, basis


def _selector_pad_ports(selector: str, models: Dict[str, Dict[str, object]],
                        direction: str) -> List[str]:
    """Resolve the small SDC selector subset emitted by our Step-7 author."""
    import fnmatch

    eligible = sorted(port for port, model in models.items()
                      if model.get("direction") in
                      (("input", "inout") if direction == "input"
                       else ("output", "inout")))
    compact = selector.strip()
    if compact == "[all_inputs]" and direction == "input":
        return eligible
    if compact == "[all_outputs]" and direction == "output":
        return eligible
    match = re.fullmatch(r"\[get_ports(?:\s+-quiet)?\s+(.+)\]", compact)
    if not match:
        return []
    body = match.group(1).strip()
    if body.startswith("{") and body.endswith("}"):
        body = body[1:-1]
    patterns = body.split()
    return [port for port in eligible
            if any(port == pattern or fnmatch.fnmatchcase(port, pattern)
                   for pattern in patterns)]


def _core_pad_translate_line(line: str, models: Dict[str, Dict[str, object]]
                             ) -> Tuple[Optional[List[str]], Optional[Dict[str, object]]]:
    """Translate one external pad command to the corresponding core model."""
    match = re.fullmatch(
        r"\s*(set_input_transition|set_load)\s+(.+?)\s+"
        r"(\[(?:all_inputs|all_outputs|get_ports\b.*)\])\s*", line)
    if not match:
        return None, None
    command, arg_text, selector = match.groups()
    tokens = arg_text.split()
    flags = [token for token in tokens if token.startswith("-")]
    allowed = {"-max", "-min", "-rise", "-fall"}
    numbers = []
    for token in tokens:
        if token.startswith("-"):
            continue
        try:
            numbers.append(float(token))
        except ValueError:
            return [], {"line": line.strip(), "why": f"unsupported argument {token!r}"}
    if set(flags) - allowed or len(numbers) != 1 or not math.isfinite(numbers[0]):
        return [], {"line": line.strip(), "why": "unsupported option/value shape"}
    direction = "input" if command == "set_input_transition" else "output"
    ports = _selector_pad_ports(selector, models, direction)
    if not ports:
        return [], {"line": line.strip(), "why": "selector resolves no producer pad port"}
    groups: Dict[Tuple[str, ...], List[str]] = {}
    for port in ports:
        model = models[port]
        if command == "set_input_transition":
            key = (str(model["master"]), str(model["terminal"]),
                   str(model["core_pin"]))
        else:
            loads = model.get("core_load_pf")
            if not isinstance(loads, dict):
                return [], {"line": line.strip(), "why": f"{port} has no core load"}
            sense = "min" if "-min" in flags else "max"
            key = (f"{float(loads[sense]):g}", sense)
        groups.setdefault(key, []).append(port)
    out = []
    for key, selected in sorted(groups.items()):
        target = "[get_ports {" + " ".join(sorted(selected)) + "}]"
        if command == "set_input_transition":
            master, terminal, pin = key
            edge_flags = " ".join(flag for flag in flags if flag in ("-min", "-max"))
            value = numbers[0]
            out.append(
                f"set_driving_cell -lib_cell {master} "
                f"-from_pin {terminal} -pin {pin} "
                f"-input_transition_rise {value:g} -input_transition_fall {value:g} "
                f"{edge_flags} {target}".replace("  ", " "))
        else:
            load, _sense = key
            option_flags = " ".join(flags)
            out.append(f"set_load {option_flags} {load} {target}".replace("  ", " "))
    return out, {"line": line.strip(), "ports": sorted(ports),
                 "external_value": numbers[0], "translated_lines": out}


def _translate_core_pad_boundary(project: Path, text: str, staged_rel: str,
                                 record: Dict[str, object], container: str,
                                 to_container_path: Optional[Callable[[str, str], str]]
                                 ) -> Tuple[str, Dict[str, object]]:
    """Keep package obligations as evidence and execute their core-side model."""
    models, basis = _core_pad_models(project, container, to_container_path)
    if models is None:
        # Older/sparse producer records carry boundary identity only.  They do
        # not assert a wrapper model, so retain the pre-existing CORE / N/A
        # behavior; translation begins only with an actual signal-pad map.
        if not basis.get("signal_pad_instance_count"):
            return text, record
        if not any(re.match(r"\s*(set_input_transition|set_load)\b", line)
                   for line in text.splitlines()):
            return text, record
        refused: List[str] = []
        inert: List[str] = []
        continuing = False
        for raw in text.splitlines(keepends=True):
            line = raw[:-1] if raw.endswith("\n") else raw
            selected = continuing or bool(re.match(
                r"\s*(set_input_transition|set_load)\b", line))
            if selected:
                refused.append(line.strip())
                ending = "\n" if raw.endswith("\n") else ""
                inert.append(f"# R-0929-CORE-PAD-TRANSLATION REFUSED: "
                             f"{line} [disabled]{ending}")
                continuing = line.rstrip().endswith("\\")
            else:
                inert.append(raw)
        identity = {key: record[key] for key in ("analysis_top", "boundary")
                    if key in record}
        reason = ("pad-facing constraints cannot be executed on the core and "
                  f"the recorded wrapper model is incomplete: {basis.get('why')}")
        inert.append(f"# NOT_MEASURED: CORE_PAD_BOUNDARY_TRANSLATION; {reason}\n")
        return "".join(inert), {
            "schema": PAD_INPUT_DRIVE_SCHEMA, "applies": True,
            "verdict": "NOT_MEASURED",
            "model": "producer-bound pad wrapper core translation",
            "source": f"design-staged SDC {staged_rel}",
            "reason": reason, "refused_staged_sdc_lines": refused,
            "sdc_lines": [], "pad_model_basis": basis, **identity,
        }
    external: List[Dict[str, object]] = []
    generated: List[str] = []
    errors: List[Dict[str, object]] = []
    out: List[str] = []
    covered_inputs, covered_outputs = set(), set()
    for raw in text.splitlines(keepends=True):
        line = raw[:-1] if raw.endswith("\n") else raw
        translated, obligation = _core_pad_translate_line(line, models)
        if obligation is None:
            out.append(raw)
            continue
        ending = "\n" if raw.endswith("\n") else ""
        out.append(f"# R-0929-CORE-PAD-TRANSLATION EXTERNAL: {line.strip()} [bond-pad only]{ending}")
        if translated:
            external.append(obligation)
            generated.extend(translated)
            for port in obligation.get("ports") or []:
                direction = models[str(port)].get("direction")
                if line.lstrip().startswith("set_input_transition"):
                    covered_inputs.add(str(port))
                elif direction in ("output", "inout"):
                    covered_outputs.add(str(port))
            out.extend(item + "\n" for item in translated)
        else:
            errors.append(obligation)
    if not external and not errors:
        return text, record
    required_inputs = {port for port, model in models.items()
                       if model.get("direction") in ("input", "inout")}
    required_outputs = {port for port, model in models.items()
                        if model.get("direction") in ("output", "inout")}
    missing = {"input_transition": sorted(required_inputs - covered_inputs),
               "output_load": sorted(required_outputs - covered_outputs)}
    incomplete = bool(errors or missing["input_transition"] or missing["output_load"])
    identity = {key: record[key] for key in ("analysis_top", "boundary") if key in record}
    translated_record: Dict[str, object] = {
        "schema": PAD_INPUT_DRIVE_SCHEMA,
        "applies": True,
        "verdict": "NOT_MEASURED" if incomplete else "PAD_TRANSLATED",
        "model": "producer-bound pad wrapper core translation",
        "source": f"design-staged SDC {staged_rel}",
        "external_pad_obligations": external,
        "translated_core_sdc_lines": generated,
        "sdc_lines": generated,
        "pad_models": models,
        "pad_model_basis": basis,
        "missing": missing,
        **identity,
    }
    if incomplete:
        translated_record["reason"] = (
            "pad-facing constraints could not be completely translated to the "
            f"recorded core boundary: errors={errors}; missing={missing}")
        out.append("# NOT_MEASURED: CORE_PAD_BOUNDARY_TRANSLATION; "
                   + str(translated_record["reason"]) + "\n")
    return "".join(out), translated_record


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


# Existing report wrapper; exports preserve these exact bytes.
PAD_OPERATING_SCENE_TCL = r'''if {[llength [info commands ::vibeic_native_report_check_types]] == 0} {
  rename ::report_check_types ::vibeic_native_report_check_types
  rename ::sta::max_slew_violation_count ::vibeic_native_max_slew_violation_count
  proc ::vibeic_with_pad_mode {command args} {
    worst_slack -max
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
    scope = f"set ::vibeic_scene_pads [list {selector}]\n" + PAD_OPERATING_SCENE_TCL
    return {"tcl": render_pad_scene_sdc(scope), "scope_tcl": scope,
            "core_cells": sorted({name for name, _ in _liberty_blocks(core_text or "", "cell")}),
            "core_liberty_sha256": hashlib.sha256(core_text.encode()).hexdigest() if core_text else None,
            "port_slew_limits": ports if complete else {},
            "liberty_sha256": sources, "complete_pin_limits": complete}


def _pad_analysis_boundary(project: Path, analysis_top: str
                           ) -> Tuple[str, Dict[str, object]]:
    """Classify ``analysis_top`` against the pad producer's two boundaries.

    The project may request a future DIE while the current netlist is still
    the core.  Only the producer's explicit ``core_module`` /
    ``chip_top_module`` identity can move the SDC boundary to the bond pads.
    """
    basis: Dict[str, object] = {"record": IO_PAD_RECORD,
                                "analysis_top": analysis_top}

    def classified(kind: str) -> Tuple[str, Dict[str, object]]:
        basis["classification"] = kind
        return kind, basis

    try:
        import hashlib
        import json
        raw = (Path(project) / IO_PAD_RECORD).read_bytes()
        record = json.loads(raw)
        basis["record_sha256"] = hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, AttributeError):
        if analysis_top:
            basis["why"] = "pad producer record is absent or unreadable"
        return classified("UNSPECIFIED" if not analysis_top else "UNRECORDED")
    if not analysis_top:
        return classified("UNSPECIFIED")
    if not isinstance(record, dict) or record.get("verdict") != "WROTE":
        basis["why"] = "pad producer record is not a successful current publication"
        return classified("UNRECORDED")
    core = record.get("core_module") if isinstance(record, dict) else None
    chip = record.get("chip_top_module") if isinstance(record, dict) else None
    if not core and not chip:
        basis["why"] = "pad producer boundary identity is absent"
        return classified("UNRECORDED")
    basis.update(core_module=core, chip_top_module=chip)
    if not isinstance(core, str) or not core or not isinstance(chip, str) or not chip:
        basis["why"] = "pad producer boundary identity is incomplete"
        return classified("UNKNOWN")
    if core == chip:
        basis["why"] = "pad producer names the same core and chip top"
        return classified("UNKNOWN")
    if analysis_top == core:
        return classified("CORE")
    if analysis_top == chip:
        return classified("CHIP")
    basis["why"] = (f"analysis top {analysis_top!r} matches neither recorded "
                    f"core {core!r} nor chip top {chip!r}")
    return classified("UNKNOWN")


def _pad_input_drive(project: Path, values: Dict[str, Tuple[str, str]],
                     container: str = "",
                     to_container_path: Optional[Callable[[str, str], str]] = None,
                     analysis_top: str = ""
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
    boundary_kind, boundary = _pad_analysis_boundary(project, analysis_top)
    identity = {"boundary": boundary}
    if analysis_top:
        identity["analysis_top"] = analysis_top
    if not die or boundary_kind == "CORE":
        reason = (f"current analysis top {analysis_top!r} is the recorded core "
                  f"boundary; future chip top {boundary.get('chip_top_module')!r} "
                  "does not move its inputs to the bond pads"
                  if boundary_kind == "CORE" else
                  "not a pad-ring (DIE) top; the synthesis driving cell models "
                  "on-chip drive")
        return values, {"schema": PAD_INPUT_DRIVE_SCHEMA, "applies": False,
                        "verdict": "NOT_APPLICABLE", "reason": reason,
                        **identity}
    out = dict(values)
    cell = out.pop("set_driving_cell", None)
    record: Dict[str, object] = {"schema": PAD_INPUT_DRIVE_SCHEMA,
                                 "applies": True, **identity}
    if boundary_kind in ("UNKNOWN", "UNRECORDED"):
        if cell:
            record["refused_core_driving_cell"] = {"value": cell[0],
                                                   "source": cell[1]}
        record.update(verdict="NOT_MEASURED", reason=(
            f"analysis boundary is stale or undetermined: {boundary.get('why')}; "
            "neither a core driving cell nor a bond-pad transition is assumed"))
        return out, record
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


def _disable_refused_staged_drive(text: str) -> str:
    """Make each refused physical drive command inert in the consumer deck.

    The exact original line remains visible in the comment and in
    ``refused_staged_sdc_lines``.  Executing a line after recording that it was
    not admitted makes the record and its consumer contradict one another.
    The NOT_MEASURED record remains authoritative downstream; disabling the
    command does not turn the unresolved boundary into a timing PASS.
    """
    out: List[str] = []
    continuing = False
    for raw in text.splitlines(keepends=True):
        refused = continuing or bool(re.match(
            r"\s*(set_input_transition|set_driving_cell)\b", raw))
        if refused:
            ending = "\n" if raw.endswith("\n") else ""
            line = raw[:-1] if ending else raw
            out.append(
                f"# R-0929-PAD-INPUT-DRIVE REFUSED: {line} [disabled]{ending}")
            continuing = line.rstrip().endswith("\\")
        else:
            out.append(raw)
    return "".join(out)


def staged_sdc_pad_input_drive(project: Path, text: str, staged_rel: str,
                               container: str = "",
                               to_container_path: Optional[Callable[[str, str], str]] = None,
                               time_scale: float = 1.0,
                               analysis_top: str = ""
                               ) -> Tuple[str, Dict[str, object]]:
    """The same ladder for a design-staged SDC on a DIE top.

    At a known DIE boundary, a staged deck that itself sets
    ``set_input_transition`` or ``set_driving_cell`` has DECLARED the drive
    (its own lines are the evidence). An absent, incomplete, stale, or unknown
    analysis boundary stays NOT_MEASURED even if the staged deck carries such a
    command: an SDC command cannot prove whether it applies to core pins or
    bond pads. One that sets neither gets the L9 declaration, else the PDK IO
    bracket, else NOT_MEASURED, appended to the deck; the record is written
    either way, so a record from an earlier run can never stand for this deck.
    """
    _, record = _pad_input_drive(project, {}, container, to_container_path,
                                 analysis_top=analysis_top)
    if not record.get("applies"):
        boundary = record.get("boundary")
        if (isinstance(boundary, dict)
                and boundary.get("classification") == "CORE"):
            return _translate_core_pad_boundary(
                project, text, staged_rel, record, container, to_container_path)
        return text, record
    own = [ln.strip() for ln in text.splitlines()
           if re.match(r"\s*(set_input_transition|set_driving_cell)\b", ln)]
    boundary = record.get("boundary")
    if (isinstance(boundary, dict)
            and boundary.get("classification") in ("UNKNOWN", "UNRECORDED")):
        if own:
            record["refused_staged_sdc_lines"] = own
            text = _disable_refused_staged_drive(text)
        lines = render_pad_input_drive(record, time_scale)
        record["sdc_lines"] = pad_drive_sdc_lines(record, time_scale)
        if lines:
            text = text.rstrip("\n") + ("\n# R-0929-PAD-INPUT-DRIVE "
                                        "(stale analysis boundary; staged input "
                                        "drive not admitted)\n") + "\n".join(lines) + "\n"
        return text, record
    if own:
        identity = {k: record[k] for k in ("analysis_top", "boundary")
                    if k in record}
        record = {"schema": PAD_INPUT_DRIVE_SCHEMA, "applies": True,
                  "verdict": "DECLARED", "model": "design-staged SDC",
                  "source": f"design-staged SDC {staged_rel}", "sdc_lines": own,
                  **identity}
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
