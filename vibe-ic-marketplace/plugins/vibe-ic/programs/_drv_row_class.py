"""Class a sign-off DRV violator row the way the DRV standard judges it.

OpenSTA holds one design-wide `set_max_capacitance` / `set_max_transition`
margin for every driver, top-level ports and IO-cell pins included: its checker
reads the top-cell, port and Liberty limits only (a pin-scoped limit is never
read) and a port can only be tightened below the design limit. On a pad-ring
(DIE) top that puts the std-cell margin on nets no std cell drives:

* a bond-pad PORT whose net reaches only IO-cell pins (the port-to-PAD net).
  Its "load" is the pad's own PAD-pin capacitance (2.9-3.1 pF on gf180) and its
  "slew" is the off-chip drive. R-0928-DRV-IC: such a net is judged by the IO
  Liberty T1 on the IO-cell pin (that row stays in the table under its own name)
  and by the declared or PDK set_load -- never by the std-cell margin;
* an IO-cell pin whose tool limit is the std-cell margin while its measured
  value is within the IO Liberty limit (DRV standard section 4: listed apart,
  not a gate, pending the owner). Above the IO Liberty limit it stays T1.

Every other row counts, including every IO-cell row at its Liberty limit (the
IO library's default_max_fanout 1 is fix-only). A row is taken out of the count
only on structural netlist connectivity and the configured IO Liberty;
anything unprovable counts, and an unreadable input raises `Unavailable`.

chip-AGNOSTIC: an IO cell is a cell the run's own PAD_LIBS Liberty marks
`pad_cell : true` -- the DRV judge's definition, read by the native Liberty reader.
"""
from __future__ import annotations

import fnmatch
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

KINDS = ("max_slew", "max_capacitance", "max_fanout")

_NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"

def _sdc_values(body: str, command: str, *, include_ports: bool = True,
                only_port: str | None = None) -> list[float]:
    values = []
    for match in re.finditer(
            rf"(?m)^\s*{re.escape(command)}\s+({_NUM})(?=\s|$)([^\n;]*)", body):
        target = match.group(2).strip()
        if only_port is not None:
            listed = re.fullmatch(r"\[get_ports\s+\[list\s+((?:\{[^{}]+\}\s*)+)\]\]", target)
            literal = re.fullmatch(r"\[get_ports\s+\{([^{}]+)\}\]", target)
            names = (re.findall(r"\{([^{}]+)\}", listed[1]) if listed else
                     [literal[1]] if literal else
                     ["*"] if target == "[get_ports *]" else [])
            if only_port not in names and "*" not in names:
                continue
        elif not include_ports and re.search(
                r"\[(?:get_ports|all_inputs|all_outputs)\b", target):
            continue
        values.append(float(match.group(1)))
    return values

def _attribute(block: str, key: str) -> float | None:
    hit = re.search(rf"\b{re.escape(key)}\s*:\s*({_NUM})\s*;", block)
    return float(hit.group(1)) if hit else None

def _balanced_block(text: str, start: int) -> str:
    opening = text.find("{", start)
    if opening < 0:
        return ""
    depth = 1
    for token in re.finditer(r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*|[{}]',
                             text[opening + 1:], flags=re.S):
        if token[0] == "{":
            depth += 1
        elif token[0] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1:opening + 1 + token.start()]
    return ""

def _liberty_limits(body: str) -> dict:
    """Read direct pin attributes in any order, excluding nested groups."""
    body = re.sub(r"\\\s*\n\s*", " ", body)
    time_match = re.search(r'time_unit\s*:\s*"?(' + _NUM +
                           r')\s*(fs|ps|ns|us|ms|s)"?', body, re.I)
    cap_match = re.search(r'capacitive_load_unit\s*\(\s*(' + _NUM +
                          r')\s*,\s*"?(ff|pf|nf|uf)"?\s*\)', body, re.I)
    if not time_match or not cap_match:
        raise ValueError("Liberty time/capacitance units absent")
    time_scale = float(time_match.group(1)) * {
        "fs": 1e-6, "ps": 1e-3, "ns": 1, "us": 1e3,
        "ms": 1e6, "s": 1e9}[time_match.group(2).lower()]
    cap_scale = float(cap_match.group(1)) * {
        "ff": 1e-3, "pf": 1, "nf": 1e3, "uf": 1e6}[cap_match.group(2).lower()]
    scales = {"max_slew": time_scale, "max_capacitance": cap_scale,
              "max_fanout": 1}
    def scaled(block: str, kind: str, prefix: str = "") -> float | None:
        value = _attribute(block, prefix + kind.replace("max_slew", "max_transition"))
        return value * scales[kind] if value is not None else None
    first_cell = re.search(r"\bcell\s*\(", body)
    header = body[:first_cell.start()] if first_cell else body
    defaults = {kind: scaled(header, kind, "default_")
                for kind in KINDS}
    default_fanout_load = _attribute(header, "default_fanout_load")
    cells: dict[str, dict] = {}
    ff_states: dict[str, set[str]] = {}
    pad_cells: set[str] = set()
    for cell in re.finditer(r'\bcell\s*\(\s*"?([^"\)]+)"?\s*\)\s*\{', body):
        cell_body = _balanced_block(body, cell.start())
        if re.search(r"\bpad_cell\s*:\s*true\s*;", cell_body, re.I):
            pad_cells.add(cell.group(1).strip())
        pins = {}
        for pin in re.finditer(r'\bpin\s*\(\s*"?([^"\)]+)"?\s*\)\s*\{', cell_body):
            pin_body = _balanced_block(cell_body, pin.start())
            direct_chars = []
            depth = 0
            for char in pin_body:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                elif depth == 0:
                    direct_chars.append(char)
            direct = "".join(direct_chars)
            pins[pin.group(1).strip()] = {
                kind: scaled(direct, kind)
                for kind in KINDS}
            pins[pin.group(1).strip()]["fanout_load"] = _attribute(direct, "fanout_load")
            pin_name = pin.group(1).strip()
            related = re.findall(r'\brelated_pin\s*:\s*"?([^";]+)"?\s*;', cell_body)
            pins[pin_name]["has_timing_arc"] = (
                bool(re.search(r"\btiming\s*\(", pin_body)) or
                any(pin_name in value.split() for value in related))
        cells[cell.group(1).strip()] = pins
        states = set()
        depth = 0
        tokens = re.finditer(
            r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*'
            r'|(?P<ff>\bff\s*\((?P<names>[^()]+)\)\s*\{)'
            r'|[A-Za-z_][\w.-]*|(?P<brace>[{}])', cell_body, flags=re.S)
        for token in tokens:
            if token["ff"] is not None:
                names = [re.fullmatch(r'\s*(?:"([A-Za-z_]\w*)"|([A-Za-z_]\w*))\s*', part)
                         for part in token["names"].split(",")]
                if depth == 0 and len(names) in (1, 2) and all(names):
                    states.update(name[1] or name[2] for name in names)
                depth += 1
            elif token["brace"] == "{":
                depth += 1
            elif token["brace"] == "}":
                depth -= 1
        ff_states[cell.group(1).strip()] = states
    return {"defaults": defaults, "cells": cells, "pad_cells": pad_cells,
            "default_fanout_load": default_fanout_load, "ff_states": ff_states}

def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0

def io_margin_scope(kind: str, cell_class: str | None, explicit_limit,
                    tool_limit, cap_margin) -> bool:
    """An IO-cell pin whose tool limit IS the design-scope std-cell cap margin
    (R-0929-CAP-MARGIN-SCOPE): the known inheritance, not an instrument
    disagreement."""
    return (kind == "max_capacitance" and cell_class == "IO" and
            explicit_limit is None and tool_limit is not None and
            _positive_number(cap_margin) and tool_limit == cap_margin)

def io_margin_disclosure(kind: str, cell_class: str | None, explicit_limit,
                         tool_limit, measured, io_limit, cap_margin) -> bool:
    """Section 4: an IO-cell row the tool FLAGGED against the std-cell margin
    while within its own IO Liberty limit is listed apart, not gated."""
    return (io_margin_scope(kind, cell_class, explicit_limit, tool_limit, cap_margin)
            and measured is not None and _positive_number(io_limit) and
            tool_limit < measured <= io_limit)

_SECTION_RE = re.compile(r"===\s*(SETUP|HOLD)\b", re.IGNORECASE)

_DRV_KINDS = {
    "max slew": "max_slew",
    "max transition": "max_slew",
    "max capacitance": "max_capacitance",
    "max cap": "max_capacitance",
    "max fanout": "max_fanout",
}

_DRV_TITLE_RE = re.compile(
    r"^(max\s+(?:slew|transition|capacitance|cap|fanout))\s*$", re.IGNORECASE)

_OTHER_TITLE_RE = re.compile(
    r"^(min\s+pulse\s+width|recovery|removal|setup|hold|clock\s+gating|"
    r"data\s+check|latch\s+check|unconstrained)\b.*$", re.IGNORECASE)

_VIOLATED_RE = re.compile(r"\(VIOLATED\)", re.IGNORECASE)

_TRAILING_NEG_RE = re.compile(r"(-\d+(?:\.\d+)?)\s*$")

_CHECK_TYPES_OK_RE = re.compile(
    r"SIGNOFF_CHECK_TYPES_REPORTED\b(.*)$", re.IGNORECASE)

_CHECK_TYPES_FAIL_RE = re.compile(
    r"SIGNOFF_CHECK_TYPES_FAILED\s+reason=(.*)$", re.IGNORECASE)

def _row_instance(line: str) -> str:
    """The INSTANCE a DRV row belongs to.

    OpenSTA prints `<instance>/<pin>` in the first column:

        _07014_/A2                              1.50   27.34  -25.84 (VIOLATED)

    Hierarchical names contain `/` too, so the PIN is the last segment and the
    instance is everything before it. Returns "" when the row has no leading
    identifier, which is not the same as an instance named "".
    """
    tok = line.split()[0] if line.split() else ""
    if "/" not in tok:
        return ""
    return tok.rsplit("/", 1)[0]

_DRV_CENSUS_RE = re.compile(
    r"^SIGNOFF_DRV_CENSUS\s+(\S+)\s+violators=(\d+)\s*$", re.M)

def _row_values(line: str) -> Dict[str, object]:
    """`{pin, limit, value}` of one violator row (`pin limit value slack ...`);
    a column that is not a number is None, never a guessed zero."""
    parts = line.split()

    def num(i: int) -> Optional[float]:
        try:
            return float(parts[i])
        except (IndexError, ValueError):
            return None
    return {"pin": parts[0], "limit": num(1), "value": num(2)}

def extract_drv(text: str) -> Dict[str, object]:
    """DRV evidence from one STA report body: was OpenSTA ASKED for max_slew /
    max_capacitance / max_fanout, and what did it answer?

    Returns `queried` (the check-types marker, or a real DRV table, is present),
    `violations` (per-kind counts) and `total`. `queried` False means the run
    never asked — which this gate treats as a failure, not as a clean result,
    because an unqueried limit and a met limit look identical downstream."""
    counts: Dict[str, int] = {}
    rows: Dict[str, List[str]] = {}
    pin_rows: Dict[str, List[str]] = {}
    pin_values: Dict[str, List[Dict[str, object]]] = {}
    queried = False
    query_error: Optional[str] = None
    kinds_seen: List[str] = []
    kind: Optional[str] = None
    state = "IDLE"

    for raw in text.splitlines():
        line = raw.strip()

        mok = _CHECK_TYPES_OK_RE.search(line)
        if mok:
            queried = True
            for token, canon in _DRV_KINDS.items():
                if token.replace(" ", "_") in mok.group(1).lower() \
                        and canon not in kinds_seen:
                    kinds_seen.append(canon)
            continue
        merr = _CHECK_TYPES_FAIL_RE.search(line)
        if merr:
            query_error = merr.group(1).strip()
            continue

        if _SECTION_RE.search(line):
            kind, state = None, "IDLE"
            continue

        mt = _DRV_TITLE_RE.match(line)
        if mt:
            kind = _DRV_KINDS[re.sub(r"\s+", " ", mt.group(1).strip().lower())]
            queried = True
            state = "HEADER"
            if kind not in kinds_seen:
                kinds_seen.append(kind)
            counts.setdefault(kind, 0)
            continue
        if _OTHER_TITLE_RE.match(line):
            kind, state = None, "IDLE"
            continue
        if kind is None or state == "IDLE":
            continue

        dashes = bool(line) and set(line) <= set("-=")
        if state == "HEADER":
            if dashes or _VIOLATED_RE.search(line):
                state = "ROWS"
            if not _VIOLATED_RE.search(line):
                continue
        elif dashes:
            continue

        if not line:
            state = "ROWS_BLANK"
            continue
        if not any(ch.isdigit() for ch in line):
            kind, state = None, "IDLE"
            continue
        if state == "ROWS_BLANK":
            state = "ROWS"
        if _VIOLATED_RE.search(line):
            counts[kind] = counts.get(kind, 0) + 1
            rows.setdefault(kind, []).append(_row_instance(line))
            pin_rows.setdefault(kind, []).append(line.split()[0])
            pin_values.setdefault(kind, []).append(_row_values(line))
            continue
        mneg = _TRAILING_NEG_RE.search(line)
        if mneg and len(line.split()) >= 3:
            counts[kind] = counts.get(kind, 0) + 1
            rows.setdefault(kind, []).append(_row_instance(line))
            pin_rows.setdefault(kind, []).append(line.split()[0])

    violations = {k: v for k, v in counts.items() if v > 0}
    _rows = {k: v for k, v in rows.items() if v}
    silent = [k for k in kinds_seen if k not in counts]
    census: Dict[str, int] = {}
    for m in _DRV_CENSUS_RE.finditer(text):
        try:
            census[m.group(1)] = int(m.group(2))
        except ValueError:
            continue
    if census:
        silent = [k for k in silent if k not in census]
    return {
        "queried": queried,
        "query_error": query_error,
        "kinds_queried": kinds_seen,
        "kinds_without_table": silent,
        "census": census,
        "violations": violations,
        "total": sum(violations.values()),
        "rows": _rows,
        "pin_rows": {k: v for k, v in pin_rows.items() if v},
        "pin_values": {k: v for k, v in pin_values.items() if v},
    }


IO_MARGIN = "IO_STD_CELL_MARGIN_DISCLOSURE"
OFFCHIP_PORT = "OFFCHIP_PORT_TO_PAD_NET"

COUNTED = "DRV"


class Unavailable(RuntimeError):
    """The netlist or an IO Liberty the classes need could not be read."""


def _name(token: str) -> str:
    token = token.strip()
    return token[1:].strip() if token.startswith("\\") else token


def netlist_nets(text: str) -> Dict[str, List[Tuple[str, str, str]]]:
    """{net: [(instance, master, pin)]} from a flat or hierarchical-name
    structural Verilog netlist (named port connections only).

    Used only to identify instance masters for IO Liberty margin disclosure.
    This partial reader NEVER proves connectivity or a port exclusion.
    """
    nets: Dict[str, List[Tuple[str, str, str]]] = {}
    body = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    body = re.sub(r"//[^\n]*", " ", body)
    for m in re.finditer(r"(?m)^\s*(\\?[A-Za-z_][\w$]*)\s+(\\\S+\s|[A-Za-z_][\w$\[\]]*)\s*"
                         r"\((.*?)\)\s*;", body, re.S):
        master, inst = m.group(1), _name(m.group(2))
        if master in ("module", "input", "output", "inout", "wire", "assign", "reg"):
            continue
        for c in re.finditer(r"\.(\w+)\s*\(\s*(\\\S+\s|[^()\s]+)\s*\)", m.group(3)):
            nets.setdefault(_name(c.group(2)), []).append((inst, master, c.group(1)))
    return nets


class Classifier:
    """Classes of (corner, kind, pin, limit, value) rows for one sign-off run."""

    def __init__(self, netlist: Path, pad_libs: Mapping[str, Sequence[Path]],
                 cap_margin: Optional[float] = None):
        """`cap_margin`: the design-scope std-cell cap margin the run's
        sign-off SDC applied (None: the IO-margin class never applies)."""
        self._cap_margin = cap_margin
        try:
            text = Path(netlist).read_text(errors="replace")
            self._nets = netlist_nets(text)
        except OSError as exc:
            raise Unavailable(f"netlist {netlist} unreadable: {exc}") from exc
        if not self._nets:
            raise Unavailable(f"netlist {netlist} names no instance connection")
        self._inst_master = {inst: master for conns in self._nets.values()
                             for inst, master, _ in conns}
        self._libs: Dict[str, List[dict]] = {}
        for corner, paths in pad_libs.items():
            parsed = []
            for path in paths:
                try:
                    parsed.append(_liberty_limits(Path(path).read_text(errors="replace")))
                except (OSError, ValueError) as exc:
                    raise Unavailable(f"IO Liberty {path} unreadable: {exc}") from exc
            self._libs[corner] = parsed
        self._ports: Dict[str, set] = {}
        self.connectivity_evidence = {"state": "UNAVAILABLE", "netlist": str(netlist)}
        self._connectivity(text)

    def _connectivity(self, text: str) -> None:
        """Class ports using the structural netlist consumed by native STA.

        Reuse the LVS reader's bus and assignment-alias normalization. An
        unsupported expression or incomplete structural connection cannot
        establish that a port has no core load.
        """
        from gate_verilog_to_spice import parse_verilog, norm
        body = re.sub(r"/\*.*?\*/|//[^\n]*", " ", text, flags=re.S)
        try:
            if len(re.findall(r"\bmodule\b", body)) != 1:
                raise ValueError("port classification needs one structural module")
            if re.search(r"\b(always|initial|generate|function)\b|#\s*\(", body):
                raise ValueError("port classification has unsupported Verilog syntax")
            assignments = re.findall(r"\bassign\s+([^=;]+?)\s*=\s*([^;]+?)\s*;", body)
            if any(not re.fullmatch(r"[A-Za-z_$][\w$.]*", _name(norm(side)))
                   for pair in assignments for side in pair):
                raise ValueError("port classification has nonstructural assignment")
            rhs = [norm(right) for _, right in assignments]
            if len(rhs) != len(set(rhs)):
                raise ValueError("port classification has branching aliases")
            _, canonical, instances = parse_verilog(body, preserve_supply_ports=True)
            _, original, _ = parse_verilog(
                re.sub(r"\bassign\s+[^;]+;", "", body), preserve_supply_ports=True)
            if not original or len(original) != len(canonical):
                raise ValueError("structural port declarations unavailable")
            if not instances or any(not pins for _, _, pins in instances):
                raise ValueError("structural instance connections unavailable")
            nets = {}
            for cell, instance, pins in instances:
                for pin, net in pins.items():
                    if net is None or re.search(r"[{},:()&|^~+*/]", net):
                        raise ValueError("port classification has unresolved pin expression")
                    nets.setdefault(_name(net), []).append(cell)
            ports = {}
            for corner, libs in self._libs.items():
                pads = set().union(*(lib["pad_cells"] for lib in libs))
                ports[corner] = {
                    re.sub(r"\.(\d+)$", r"[\1]", _name(port))
                    for port, net in zip(original, canonical)
                    if nets.get(_name(net)) and all(cell in pads for cell in nets[_name(net)])}
            self._ports = ports
            self.connectivity_evidence = {"state": "NATIVE_NETLIST"}
        except (AttributeError, ValueError, IndexError) as exc:
            self.connectivity_evidence = {"state": "UNAVAILABLE", "reason": str(exc)}

    def _io(self, corner: str) -> List[dict]:
        if corner not in self._libs:
            raise Unavailable(f"no IO Liberty for corner {corner}")
        return self._libs[corner]

    def _pad(self, corner: str, master: Optional[str]) -> Optional[dict]:
        """The IO Liberty that declares `master` a pad cell (the judge's IO
        class: `pad_cell : true`), or None."""
        for lib in self._io(corner):
            if master in lib["pad_cells"]:
                return lib
        return None

    def io_limit(self, corner: str, master: str, pin: str, kind: str) -> Optional[float]:
        """The tightest IO Liberty limit over every linked library that
        declares `master` a pad cell (one per corner in a scene; all of them
        when a report spans corners)."""
        limits = []
        for lib in self._io(corner):
            if master not in lib["pad_cells"]:
                continue
            value = (lib["cells"].get(master, {}).get(pin) or {}).get(kind)
            value = value if value is not None else lib["defaults"].get(kind)
            if value is not None:
                limits.append(value)
        return min(limits) if limits else None

    def classify(self, corner: str, kind: str, pin: str,
                 limit: Optional[float], value: Optional[float]) -> str:
        if "/" not in pin:
            return OFFCHIP_PORT if pin in self._ports.get(corner, set()) else COUNTED
        inst, _, lib_pin = pin.rpartition("/")
        master = self._inst_master.get(inst)
        if self._pad(corner, master) is None:
            return COUNTED
        return (IO_MARGIN if io_margin_disclosure(
            kind, "IO", None, limit, value,
            self.io_limit(corner, master, lib_pin, kind), self._cap_margin)
            else COUNTED)


def sdc_cap_margin(sdc_text: str) -> Optional[float]:
    """The one design-scope `set_max_capacitance <v> [current_design]` value
    the sign-off SDC applies, or None when absent or ambiguous."""
    values = {v for v in _sdc_values(sdc_text, "set_max_capacitance", include_ports=False)}
    return values.pop() if len(values) == 1 else None


def pad_libs_by_corner(pad_libs: object, corners: Iterable[str]) -> Dict[str, List[str]]:
    """LibreLane PAD_LIBS (a corner-glob map, or one list for every corner)."""
    out: Dict[str, List[str]] = {}
    for corner in corners:
        if isinstance(pad_libs, dict):
            hits = [p for glob, paths in pad_libs.items()
                    if fnmatch.fnmatch(corner, glob)
                    for p in ([paths] if isinstance(paths, str) else paths)]
        else:
            hits = [pad_libs] if isinstance(pad_libs, str) else list(pad_libs or [])
        if hits:
            out[corner] = hits
    return out
