"""Native final-State readers for prestream and physical signoff.

Ruling #62: steps chain through State; no publisher, historical stage probes,
placed.def alias or signed threshold authority is an input to this path.
"""
from __future__ import annotations

import filecmp
import fnmatch
import json
import math
import os
import re
import shlex
from decimal import Decimal
from pathlib import Path
from typing import Any



KINDS = ("max_slew", "max_capacitance", "max_fanout")


_TITLES = {"max slew": KINDS[0], "max capacitance": KINDS[1],
           "max fanout": KINDS[2]}


_VALUES = {"max_slew": ("max slew", "slew"),
           "max_capacitance": ("max capacitance", "capacitance"),
           "max_fanout": ("max fanout", "fanout")}


_NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"


_PIN = re.compile(r"^Pin\s+(\S+)(?:\s+([\^v]))?\s*$")


_METRIC = re.compile(rf"^(.+?)\s+({_NUM})(?:\s+\((?:VIOLATED|MET)\))?\s*$")


def _sdc_values(body: str, command: str, *, include_ports: bool = True,
                only_port: str | None = None) -> list[float]:
    # Tcl is not a line-oriented format.  A conflicting later assignment must
    # never be hidden by reading only the first matching line.
    # IO port constraints have their own domain. They are not the core
    # defaults the stage receipt and the core declaration must agree on.
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


def parse_check_types(body: str, *, scene: str, mode: str,
                      violators_only: bool) -> dict[str, list[dict]]:
    """Parse OpenSTA 3.1 verbose Pin blocks; preserve rise/fall and tool slack."""
    out: dict[str, list[dict]] = {kind: [] for kind in KINDS}
    kind = None
    row: dict[str, Any] | None = None
    for raw in body.splitlines():
        line = raw.strip()
        if line in _TITLES:
            kind = _TITLES[line]
            row = None
            continue
        pin = _PIN.fullmatch(line)
        if pin and kind:
            row = {"pin": pin.group(1), "direction":
                   {"^": "rise", "v": "fall"}.get(pin.group(2), "none"),
                   "scene": scene, "mode": mode}
            out[kind].append(row)
            continue
        if row is None or kind is None:
            continue
        status = re.fullmatch(r"Slack\s+\((VIOLATED|MET)\)", line)
        if status:
            # Native fanout reports can omit the numeric slack while retaining
            # an explicit verdict. Preserve that verdict without inventing slack.
            row["violated"] = status.group(1) == "VIOLATED"
            continue
        metric = _METRIC.fullmatch(line)
        if not metric:
            continue
        name = metric.group(1).strip().lower()
        limit_name, measured_name = _VALUES[kind]
        if name == limit_name:
            row["limit"] = float(metric.group(2))
        elif name == measured_name:
            row["measured"] = float(metric.group(2))
        elif name == "slack":
            row["slack"] = float(metric.group(2))
            row["violated"] = "(VIOLATED)" in line or row["slack"] < 0
    if violators_only:
        for rows in out.values():
            rows[:] = [r for r in rows if r.get("violated")]
    return out


def _attribute(block: str, key: str) -> float | None:
    hit = re.search(rf"\b{re.escape(key)}\s*:\s*({_NUM})\s*;", block)
    return float(hit.group(1)) if hit else None


def _balanced_block(text: str, start: int) -> str:
    opening = text.find("{", start)
    if opening < 0:
        return ""
    depth = 1
    # Liberty strings/comments may contain braces without opening a group.
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
    # PDK Liberty writers commonly split a unit declaration with a Tcl-style
    # backslash/newline (the linked gf180 IO library does exactly this).
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
            # Liberty permits pin attributes after timing/power tables. Keep
            # every direct attribute while discarding child-group bodies.
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
        # Only direct cell groups declare FF state; quoted descriptions,
        # comments and child-group bodies cannot supply model authority.
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


def load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def text(path: Path) -> str:
    try:
        return path.read_text(errors='replace')
    except OSError:
        return ''


def path(project: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else project / p


def same_def(a: Path, b: Path) -> bool:
    try:
        return a.is_file() and b.is_file() and filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


FLOW_ORDINAL = re.compile(r'^(\d+(?:\.\d+)?)(?:ic)?(?:-|$)')
FINISHING_RECORD_REL = 'phase3/librelane/37-default-promotion.json'


def final_state(project: Path, *, streamed: bool = False) -> Path | None:
    # Prefer the selected State. The existing signoff pointer is only a path;
    # its publisher, hashes and signatures are not admission requirements (#62).
    direct = project / 'state_out.json'
    if direct.is_file():
        state = load(direct)
        if (streamed or 'route__drc_errors_final' in (state.get('metrics') or {}) or
                state.get('odb') and state.get('def') and (state.get('spef') or
                same_def(path(project, state['def']), project / 'phase3/stage3/pnr/routed.def'))):
            return direct.resolve()
    if streamed:
        streams = []
        base = project / 'phase3/librelane'
        for candidate in sorted(base.glob('**/state_out.json')):
            meta = load(candidate.parent / 'config.json').get('meta')
            if isinstance(meta, dict) and meta.get('step') in (
                    'KLayout.StreamOut', 'Magic.StreamOut', 'Vibeic.FillAwareStreamOut'):
                parts = candidate.parent.relative_to(base).parts
                ordinal = tuple(Decimal(match.group(1)) for folder in parts
                                if (match := FLOW_ORDINAL.match(folder)))
                if not FLOW_ORDINAL.match(parts[0]):
                    raise ValueError(f'CURRENT_FINAL_STATE_UNORDERED: {candidate}')
                streams.append((ordinal, candidate))
        if not streams:
            return None
        latest = max(ordinal for ordinal, _ in streams)
        finals = [candidate for ordinal, candidate in streams if ordinal == latest]
        if len(finals) > 1:
            raise ValueError('CURRENT_FINAL_STATE_AMBIGUOUS: ' + ', '.join(map(str, finals)))
        return finals[0]
    selected = load(project / 'reports/phase3/sta_postpnr_signoff.json').get('sta_state')
    if isinstance(selected, str):
        p = path(project, selected)
        state = load(p)
        if state.get('odb') and state.get('def'):
            return p
    # A retained native route needs no publisher. Only States describing the
    # current routed DEF qualify; never pick a run by mtime or a design name.
    routed = project / 'phase3/stage3/pnr/routed.def'
    candidates = []
    for p in sorted((project / 'phase3/librelane').glob('**/state_out.json')):
        state = load(p)
        if (state.get('odb') and state.get('def')
                and ('route__drc_errors_final' in (state.get('metrics') or {}) or state.get('spef'))
                and same_def(path(project, state['def']), routed)):
            candidates.append((bool(list(p.parent.glob('*/vibeic_signoff.rpt'))), p))
    return max(candidates)[1] if candidates else None


def finished_gds(project: Path, selected: Path) -> Path:
    """Seal and fill run after the final State, so their publisher names the GDS."""
    record = load(project / FINISHING_RECORD_REL)
    if not record.get('canonical'):
        raise ValueError(f'CURRENT_FINISHED_GDS_RECORD_MISSING: {FINISHING_RECORD_REL}')
    if not isinstance(record['canonical'], str):
        raise ValueError('CURRENT_FINISHED_GDS_RECORD_INVALID: canonical must be a path string')
    if path(project, str(record.get('stream_state'))).resolve() != selected.resolve():
        raise ValueError(f"CURRENT_FINISHED_GDS_OTHER_STATE: {record.get('stream_state')} != {selected}")
    gds = path(project, record['canonical'])
    if not gds.is_file() or gds.stat().st_size == 0:
        raise ValueError(f'CURRENT_FINISHED_GDS_MISSING: {gds}')
    return gds


def signoff_inputs(project: Path, *roles: str) -> dict[str, Path]:
    """The finished GDS plus the caller's other views from one final LibreLane State."""
    project = Path(project).resolve()
    selected = final_state(project, streamed=True)
    if selected is None:
        raise ValueError('CURRENT_FINAL_STATE_MISSING: state_out.json')
    state = load(selected)
    views = {}
    for role in roles:
        if role == 'gds':
            views[role] = finished_gds(project, selected)
            continue
        name = 'nl' if role == 'netlist' else role
        value = state.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'CURRENT_FINAL_STATE_VIEW_MISSING: {name} in {selected}')
        view = path(project, value)
        if not view.is_file() or view.stat().st_size == 0:
            raise ValueError(f'CURRENT_FINAL_STATE_VIEW_MISSING: {name}: {view}')
        views[role] = view
    return views


def result(failures=(), missing=(), **values) -> dict:
    return dict(verdict='FAIL' if failures else 'NOT_MEASURED' if missing else 'PASS',
                failures=list(failures), not_measured=list(missing), **values)


def count(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0 and int(value) == value


def placement(project: Path, state_path: Path, *, container: str | None = None) -> dict:
    state = load(state_path)
    odb = path(project, str(state.get('odb', '')))
    import phase3_one_shot_runner as runner
    import _atomic_artefact as aa
    log = project / 'reports/phase3/prestream_placement.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    log.unlink(missing_ok=True)
    counts, failures = [], []
    missing = []
    # Ruling #62: a later writer may replace the routed ODB. Always check
    # the final State's database through the existing native launch route.
    if not odb.is_file():
        missing.append(f'final ODB absent: {odb}')
        aa.write_text(log, missing[-1] + '\n')
    else:
        route = container if container is not None else (
            os.environ.get('EDA_CONTAINER') or runner._pin.default_container_name())
        tcl = log.with_suffix('.tcl')
        odb_c = runner._to_container_path(str(odb), route)
        # One literal Tcl word, including paths containing whitespace/braces.
        odb_word = '"' + re.sub(r'([\\"$\[\]])', r'\\\1', odb_c) + '"'
        aa.write_text(tcl, f'read_db {odb_word}\n'
                      'set _plv [check_placement -no_abort]\n'
                      'puts "PRESTREAM_CHECK_PLACEMENT_VIOLATIONS $_plv"\n')
        tcl_c = runner._to_container_path(str(tcl), route)
        try:
            rc, out, err = runner._docker_exec(
                route, f'openroad -no_init -exit {shlex.quote(tcl_c)}',
                marker=tcl_c, inputs=[odb], transcript_path=log)
            body = (out or '') + '\n' + (err or '')
            aa.write_text(log, body)
            counts = [int(n) for n in re.findall(
                r'^PRESTREAM_CHECK_PLACEMENT_VIOLATIONS\s+(\d+)\s*$', body, re.M)]
            if rc or len(counts) != 1 or re.search(r'^\s*(?:\[ERROR\b|Error:)', body, re.M):
                missing.append(f'native check_placement incomplete: rc={rc}, counts={counts}; {log}')
        except Exception as exc:
            aa.write_text(log, f'native check_placement could not run: {exc}\n')
            missing.append(f'native check_placement could not run: {exc}; {log}')
    if any(counts):
        failures.append(f'native check_placement violations: {counts}')
    final_def = path(project, str(state.get('def', '')))
    if not odb.is_file() and not final_def.is_file():
        missing.append('final ODB/DEF absent')
    # Retain the existing structural and density bounds on the State's DEF.
    from placement_legality_check import (_split_components, _record_is_placed,
                                         _DENSITY_KEYS, _coerce_density_pct,
                                         _read_def_density_comment)
    structural_read = True
    try:
        declared, records = _split_components(final_def) if final_def.is_file() else (None, [])
    except OSError as exc:
        declared, records = None, []
        structural_read = False
        missing.append(f'final DEF unreadable: {exc}')
    unplaced = sum(not _record_is_placed(record) for record in records)
    if structural_read and final_def.is_file() and (not declared or declared != len(records) or unplaced):
        failures.append(f'final DEF components declared={declared}, parsed={len(records)}, unplaced={unplaced}')
    density, density_source = None, None
    for key in _DENSITY_KEYS:
        density = _coerce_density_pct((state.get('metrics') or {}).get(key))
        if density is not None:
            density_source = f'{state_path}: metrics[{key}]'
            break
    if density is None and final_def.is_file():
        density = _read_def_density_comment(final_def)
        density_source = str(final_def) if density is not None else None
    if density is not None and (density <= 0 or density > 100.0 + 1e-6):
        failures.append(f'native placement density {density}% outside (0, 100]%')
    return result(failures, missing, violations=counts,
                  native_count=counts[0] if len(counts) == 1 else None,
                  output_files=[str(log)], declared_components=declared,
                  parsed_components=len(records), unplaced=unplaced,
                  density_pct=density, density_source=density_source)


def padring(project: Path, state_path: Path, *, container: str | None = None) -> dict:
    """BLOCKING #99: compare assignment side/order with final-State ODB geometry."""
    import _atomic_artefact as aa
    import _pad_ring as pr
    import phase3_one_shot_runner as runner

    log = project / 'reports/phase3/padring_final_state.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    log.unlink(missing_ok=True)
    odb = path(project, str(load(state_path).get('odb', '')))
    evidence = dict(state=str(state_path), odb=str(odb), expected_pads=None,
                    output_files=[str(log)])
    if not odb.is_file():
        return result(missing=[f'PADRING_NATIVE_ODB_UNREADABLE:{odb}'], **evidence)
    route = container if container is not None else (
        os.environ.get('EDA_CONTAINER') or runner._pin.default_container_name())

    def word(value):
        return '"' + re.sub(r'([\\"$\[\]])', r'\\\1', str(value)) + '"'

    try:
        deck = [f'read_db {word(runner._to_container_path(str(odb), route))}',
                'set b [ord::get_db_block]', 'set die [$b getDieArea]',
                'set instances [$b getInsts]',
                'puts "PADRING_NATIVE_DIE [$b getDbUnitsPerMicron] '
                '[$die xMin] [$die yMin] [$die xMax] [$die yMax] [llength $instances]"',
                'set n 0', 'foreach inst $instances {',
                '  set master [$inst getMaster]', '  set box [$inst getBBox]',
                '  set name [binary encode hex [encoding convertto utf-8 [$inst getName]]]',
                '  set cell [binary encode hex [encoding convertto utf-8 [$master getName]]]',
                '  puts "PADRING_NATIVE_INST $n $name $cell [$master isPad] '
                '[$master getType] [$inst getPlacementStatus] '
                '[$box xMin] [$box yMin] [$box xMax] [$box yMax]"',
                '  incr n', '}', 'puts "PADRING_NATIVE_COMPLETE $n"']
        tcl = log.with_suffix('.tcl')
        aa.write_text(tcl, '\n'.join(deck) + '\n')
        tcl_c = runner._to_container_path(str(tcl), route)
        rc, out, err = runner._docker_exec(
            route, f'openroad -no_init -exit {shlex.quote(tcl_c)}',
            marker=tcl_c, inputs=[odb], transcript_path=log)
        body = (out or '') + '\n' + (err or '')
        aa.write_text(log, body)
        headers = re.findall(r'^PADRING_NATIVE_DIE (.*)$', body, re.M)
        rows = re.findall(r'^PADRING_NATIVE_INST (.*)$', body, re.M)
        complete = re.findall(r'^PADRING_NATIVE_COMPLETE (.*)$', body, re.M)
        if (rc or len(headers) != 1 or len(complete) != 1
                or re.search(r'^\s*(?:\[ERROR\b|Error:)', body, re.M)):
            return result(missing=[f'PADRING_NATIVE_CHECK_INCOMPLETE:rc={rc}; {log}'], **evidence)
        dbu, llx, lly, urx, ury, population = map(int, headers[0].split())
        if (dbu <= 0 or llx >= urx or lly >= ury or population < 0
                or len(rows) != population or int(complete[0]) != population):
            raise ValueError('native census dimensions/counts invalid')
        census = []
        for index, row in enumerate(rows):
            ordinal, name, master, is_pad, kind, status, *box = row.split()
            if (int(ordinal) != index or is_pad not in ('0', '1') or len(box) != 4):
                raise ValueError(f'native census row {index} invalid')
            census.append(dict(instance=bytes.fromhex(name).decode('utf-8'),
                               master=bytes.fromhex(master).decode('utf-8'),
                               is_pad=is_pad == '1', type=kind, status=status,
                               bbox=tuple(map(int, box))))
    except Exception as exc:
        missing = f'PADRING_NATIVE_CHECK_UNAVAILABLE:{exc}; {log}'
        if not log.is_file():
            aa.write_text(log, missing + '\n')
        return result(missing=[missing], **evidence)

    evidence.update(native_instances=len(census), dbu=dbu, die=[llx, lly, urx, ury])
    failures, declared = [], {}
    assignment_path = project / pr.ASSIGNMENT_REL
    try:
        assignment = json.loads(assignment_path.read_text())
    except OSError as exc:
        return result(missing=[f'PADRING_PAD_ASSIGNMENT_UNREADABLE:{assignment_path}:{exc}'], **evidence)
    except ValueError as exc:
        return result([f'PADRING_PAD_ASSIGNMENT_MALFORMED:{assignment_path}:{exc}'], **evidence)
    if not isinstance(assignment, dict):
        return result([f'PADRING_PAD_ASSIGNMENT_MALFORMED:{assignment_path}:not an object'], **evidence)
    for side in pr.SIDES:
        names = assignment.get(pr.SIDE_VAR[side])
        if not isinstance(names, list):
            failures.append(f'PADRING_PAD_ASSIGNMENT_MALFORMED:{pr.SIDE_VAR[side]}:{names!r}')
            continue
        for order, name in enumerate(names):
            if not isinstance(name, str) or not name.strip():
                failures.append(f'PADRING_PAD_ASSIGNMENT_MALFORMED:{pr.SIDE_VAR[side]}[{order}]:{name!r}')
            elif name in declared:
                failures.append(f'PADRING_DECLARED_PAD_DUPLICATED:{name}')
            else:
                declared[name] = (side, order)
    if not declared:
        failures.append('PADRING_DECLARED_PAD_POPULATION_EMPTY')
    evidence['expected_pads'] = len(declared)
    try:
        value = assignment.get('PAD_EDGE_SPACING')
        if type(value) not in (str, int, float):
            raise ValueError('not a number or numeric string')
        edge_um = float(value)
        scaled = edge_um * dbu
        if not math.isfinite(scaled) or edge_um < 0:
            raise ValueError('not finite and nonnegative')
        # Tcl round used by the native placer rounds halves away from zero.
        edge = math.floor(scaled)
        if scaled - edge >= 0.5:
            edge += 1
    except (ValueError, OverflowError) as exc:
        failures.append(f'PADRING_PAD_ASSIGNMENT_EDGE_INVALID:{value!r}:{exc}')
    fillers = assignment.get('PAD_FILLERS', [])
    corner = assignment.get('PAD_CORNER')
    if (not isinstance(fillers, list)
            or any(not isinstance(name, str) or not name.strip() for name in fillers)
            or corner is not None and (not isinstance(corner, str) or not corner.strip())):
        failures.append('PADRING_PAD_ASSIGNMENT_AUXILIARY_MASTERS_MALFORMED')
    if failures:
        return result(failures, **evidence)
    auxiliary = set(fillers)
    if corner is not None:
        auxiliary.add(corner)
    by_name = {}
    for inst in census:
        name = inst['instance']
        if name in by_name:
            failures.append(f'PADRING_NATIVE_PAD_DUPLICATED:{name}')
        by_name.setdefault(name, inst)
    for name in declared:
        inst = by_name.get(name)
        if inst is None:
            failures.append(f'PADRING_DECLARED_PAD_MISSING_FROM_NATIVE:{name}')
        elif not inst['is_pad'] or inst['master'] in auxiliary:
            failures.append(f'PADRING_DECLARED_PAD_ROLE_MISMATCH:{name}:master={inst["master"]}; type={inst["type"]}')
    pads = [inst for inst in census if inst['is_pad']
            and (inst['master'] not in auxiliary or inst['type'] not in ('PAD', 'PAD_SPACER'))]
    evidence['native_pads'] = len(pads)
    sides = {side: [] for side in pr.SIDES}
    for inst in pads:
        name = inst['instance']
        if name not in declared:
            failures.append(f'PADRING_NATIVE_PAD_UNDECLARED:{name}')
        if inst['status'] != 'FIRM':
            failures.append(f'PADRING_NATIVE_PAD_NOT_FIXED:{name}:{inst["status"]}')
        x0, y0, x1, y1 = inst['bbox']
        if not (llx <= x0 < x1 <= urx and lly <= y0 < y1 <= ury):
            failures.append(f'PADRING_NATIVE_PAD_OUTSIDE_DIE_OR_INVALID_BBOX:{name}:{inst["bbox"]}')
            continue
        gaps = dict(S=y0 - lly, E=urx - x1, N=ury - y1, W=x0 - llx)
        observed = [side for side, gap in gaps.items() if gap == edge]
        if len(observed) != 1:
            failures.append(f'PADRING_NATIVE_PAD_SIDE_AMBIGUOUS:{name}:edge={edge}; gaps={gaps}')
            continue
        side = observed[0]
        sides[side].append((x0 if side in ('S', 'N') else y0, name))
        if name in declared and declared[name][0] != side:
            failures.append(f'PADRING_NATIVE_PAD_SIDE_MISMATCH:{name}:expected={declared[name][0]}; observed={side}')
    for side, members in sides.items():
        members.sort(key=lambda member: member[0])
        for order, (coordinate, name) in enumerate(members):
            tied = (order > 0 and members[order - 1][0] == coordinate
                    or order + 1 < len(members) and members[order + 1][0] == coordinate)
            if tied:
                failures.append(f'PADRING_NATIVE_PAD_ORDER_AMBIGUOUS:{name}:side={side}; coordinate={coordinate}')
            elif name in declared and declared[name] != (side, order):
                failures.append(f'PADRING_NATIVE_PAD_ORDER_MISMATCH:{name}:expected={declared[name]}; observed={side}/{order}')
    return result(failures, **evidence)


def route(project: Path, state_path: Path) -> dict:
    state = load(state_path)
    final_def = path(project, str(state.get('def', '')))
    failures, missing, drc = [], [], []
    # A later STA State may have been bridged from the direct route. Read the
    # native router State for that same final DEF, not an earlier stage probe.
    states = [(state_path, state)]
    for p in sorted((project / 'phase3/librelane').glob('**/state_out.json')):
        d = load(p)
        if p != state_path and d.get('def') and same_def(path(project, d['def']), final_def):
            states.append((p, d))
    opens = []
    # Native final DRT-0702/0711 reports also cover scoped ECO routes; these
    # need not contain the legacy "Complete detail routing" sentence (#62).
    route_log = final_def.parent / 'openroad.log'
    body = text(route_log)
    for pattern in (r'DRT-0702\] Post-route verification: (\d+) violation',
                    r'DRT-0711\].*whole-design violations \d+ on entry, (\d+) on exit'):
        values = re.findall(pattern, body)
        if values:
            drc.append(int(values[-1]))
    for p, d in states:
        metrics = (d.get('metrics') or {})
        n = metrics.get('route__drc_errors_final')
        if count(n):
            drc.append(n)
        for key in ('route__opens', 'route__unrouted_nets'):
            if count(metrics.get(key)):
                opens.append(metrics[key])
    # Existing native OpenROAD census: no layout receipt/digest requirement.
    census = load(project / 'reports/phase3/prestream_route_census.json')
    source = census.get('source_def')
    if (isinstance(source, str) and same_def(path(project, source), final_def)
            and census.get('tool') == 'OpenROAD ODB'
            and census.get('status') == 'MEASURED' and count(census.get('unrouted_nets'))):
        opens.append(census['unrouted_nets'])
    if any(drc):
        failures.append(f'native final router DRC violations: {drc}')
    if any(opens):
        failures.append(f'native final route opens: {opens}')
    if not drc:
        missing.append('native detailed-route final DRC count absent')
    if not opens:
        missing.append('native final route opens count absent')
    if not final_def.is_file() or not path(project, str(state.get('odb', ''))).is_file():
        missing.append('final routed ODB/DEF absent')
    return result(failures, missing, drc=drc, opens=opens)


def drv(project: Path, state_path: Path) -> dict:
    state = load(state_path)
    folder = state_path.parent
    config = load(folder / 'config.json')
    declared = config.get('STA_CORNERS') or []
    metrics = (state.get('metrics') or {})
    kinds = {'max_slew': 'design__max_slew_violation__count',
             'max_capacitance': 'design__max_cap_violation__count',
             'max_fanout': 'design__max_fanout_violation__count'}
    corners = sorted({key.split('__corner:', 1)[1] for key in metrics if '__corner:' in key
                      and key.split('__corner:', 1)[0] in kinds.values()})
    missing, failures = [], []
    if not declared or not corners:
        missing.append('native signoff corner population absent')
    for pattern in declared:
        if not any(fnmatch.fnmatchcase(c, pattern) for c in corners):
            missing.append(f'unmeasured signoff corner {pattern}')
    # Native STA uses Liberty transition/cap limits and the declared fanout,
    # with the existing margins. Do not replace them with a looser default (#62).
    sdc = path(project, str(state.get('sdc', '')))
    body = text(sdc)
    parsed_libs = {}
    fanouts = _sdc_values(body, 'set_max_fanout', include_ports=False)
    if not fanouts or any(not math.isfinite(v) or v <= 0 for v in fanouts):
        missing.append('declared max_fanout in native signoff SDC absent/invalid')
    declared_fanout = config.get('MAX_FANOUT_CONSTRAINT')
    if (type(declared_fanout) in (int, float) and math.isfinite(declared_fanout)
            and any(v > declared_fanout for v in fanouts)):
        failures.append('native SDC max_fanout exceeds the existing declared constraint')
    for corner in corners:
        declared_libs = config.get('LIB', config.get('CELL_LIBS')) or {}
        libs = ([item for pattern, group in declared_libs.items()
                 if fnmatch.fnmatchcase(corner, pattern) for item in group]
                if isinstance(declared_libs, dict) else declared_libs)
        if not libs:
            missing.append(f'{corner}: native cell Liberty limits absent')
        for lib in libs:
            if lib not in parsed_libs:
                try:
                    parsed_libs[lib] = _liberty_limits(text(path(project, lib)))
                except ValueError:
                    parsed_libs[lib] = None
            limits = parsed_libs[lib]
            for kind in ('max_slew', 'max_capacitance'):
                values = ([limits['defaults'].get(kind)] +
                          [pin.get(kind) for cell in limits['cells'].values()
                           for pin in cell.values()]) if limits else []
                if not any(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in values):
                    missing.append(f'{corner}: native Liberty {kind} limit unavailable: {lib}')
        report = folder / corner / 'vibeic_signoff.rpt'
        body = text(report)
        for kind, metric in kinds.items():
            n = metrics.get(f'{metric}__corner:{corner}')
            native = [int(v) for v in re.findall(
                rf'(?m)^SIGNOFF_DRV_CENSUS {kind} violators=(\d+)\s*$', body)]
            if (count(n) and n > 0) or any(native):
                failures.append(f'{corner}: {kind} violations (State={n}, report={native})')
            if not count(n) or len(native) != 1:
                missing.append(f'{corner}: native {kind} census absent/invalid')
            elif n != native[0]:
                missing.append(f'{corner}: State/report {kind} counts disagree')
        if any(parse_check_types(body, scene=corner, mode='signoff', violators_only=True).values()):
            failures.append(f'{corner}: native DRV table has a violation')
    return result(failures, missing, corners=corners)


def sta_arm(project: Path, state_path: Path) -> dict:
    """The existing STA judges' input shape, read directly from native State.

    Ruling #62 removes publisher receipt/identity admission here. The judges
    still own their corner population, scope, DRV and slack thresholds.
    """
    import librelane_signoff as ls
    from librelane_contract import Refusal
    from _ppa.backends.opensta import parse_liberty_pvt
    state, folder = load(state_path), state_path.parent
    config = load(folder / 'config.json')
    declared = config.get('STA_CORNERS') or []
    if not declared:
        raise Refusal('LL_STA_NO_CORNER', str(folder / 'config.json'))
    corners = {}
    for name in declared:
        report = folder / name / ls.CORNER_REPORT
        if not report.is_file():
            raise Refusal('LL_STA_CORNER_ARTEFACT_MISSING', str(report))
        libraries = config.get('LIB', config.get('CELL_LIBS')) or {}
        libs = ([lib for pattern, group in libraries.items()
                 if fnmatch.fnmatchcase(name, pattern) for lib in group]
                if isinstance(libraries, dict) else libraries)
        lib = libs[0] if libs else None
        pvt = parse_liberty_pvt(lib) if lib else None
        gaps = dict(pvt.gaps) if pvt else {'process': 'cell Liberty absent'}
        if pvt and name.split('_', 2)[1].lower() != pvt.process:
            gaps['process'] = 'native scene and cell Liberty process disagree'
        header = ls._liberty_header_pvt(path(project, lib)) if lib else None
        if header is None:
            gaps['liberty_header_pvt'] = 'native Liberty header unavailable'
        elif pvt and (pvt.voltage_v != header['nom_voltage'] or
                      pvt.temperature_c != header['nom_temperature']):
            gaps['liberty_header_pvt'] = 'Liberty filename and native header PVT disagree'
        spefs = state.get('spef') or {}
        matched = [pattern for pattern in spefs if fnmatch.fnmatchcase(name, pattern)]
        rc = ls.rc_corner(matched[0]) if len(matched) == 1 else None
        spef = path(project, spefs[matched[0]]) if rc else None
        if rc is None or not name.startswith(rc + '_') or not spef.is_file():
            gaps['rc_corner'] = 'native RC corner/SPEF absent or inconsistent'
        roles = [(item, 'CELL_LIBS') for item in libs]
        for field in ('PAD_LIBS', 'EXTRA_LIBS'):
            extra = config.get(field) or {}
            selected = ([item for pattern, group in extra.items()
                         if fnmatch.fnmatchcase(name, pattern) for item in group]
                        if isinstance(extra, dict) else extra)
            roles.extend((item, field) for item in selected)
        liberty_views = []
        for item, role in roles:
            f = path(project, item)
            sha = ls.digest(f) if f.is_file() else None
            item_header = ls._liberty_header_pvt(f)
            item_pvt = parse_liberty_pvt(item)
            liberty_views.append({'path': item, 'sha256': sha, 'run_sha256': None,
                                  'header_pvt': item_header, 'role': role,
                                  'filename_pvt_gaps': dict(item_pvt.gaps)})
            if not sha:
                gaps['liberty'] = 'native configured Liberty unavailable'
            if role == 'CELL_LIBS' and (item_header is None or item_pvt.gaps or
                    item_pvt.voltage_v != item_header['nom_voltage'] or
                    item_pvt.temperature_c != item_header['nom_temperature'] or
                    not pvt or item_pvt.process != pvt.process or
                    item_pvt.voltage_v != pvt.voltage_v or
                    item_pvt.temperature_c != pvt.temperature_c):
                gaps['liberty_header_pvt'] = 'native cell Liberty PVT unavailable or inconsistent'
            if role != 'CELL_LIBS' and item_pvt.process and pvt and item_pvt.process != pvt.process:
                gaps['auxiliary_liberty_process'] = 'native auxiliary Liberty process disagrees'
        log = folder / name / 'sta.log'
        log_text = log.read_text(errors='replace') if log.is_file() else ''
        logged_libs = re.findall(
            r"(?m)^Reading cell library for the '([^']+)' corner at '([^']+)'", log_text)
        logged_spefs = re.findall(
            r"(?m)^Reading top-level design parasitics for the '([^']+)' corner at '([^']+)'", log_text)
        if not roles or sorted(logged_libs) != sorted((name, item) for item, _ in roles):
            gaps['liberty'] = 'native scene log and configured Liberty disagree'
        if spef is None or logged_spefs != [(name, str(spef))]:
            gaps['spef'] = 'native scene log and State SPEF disagree'
        corners[name] = {
            'rc_corner': rc, 'process': pvt.process if pvt else None,
            'voltage_v': pvt.voltage_v if pvt else None,
            'temperature_c': pvt.temperature_c if pvt else None,
            'liberty': lib, 'liberties': liberty_views,
            'liberty_sha256': liberty_views[0]['sha256'] if liberty_views else None,
            'liberty_header_pvt': header,
            'spef': str(spef) if spef else None,
            'spef_sha256': ls.digest(spef) if spef and spef.is_file() else None,
            'sta_log': str(log), 'sta_log_sha256': ls.digest(log) if log.is_file() else None,
            'metrics': {k: (state.get('metrics') or {}).get(f'{v}__corner:{name}')
                        for k, v in ls.TIMING_METRICS.items()},
            'scope_gaps': gaps,
            'files': {ls.CORNER_REPORT: {'path': str(report), 'sha256': ls.digest(report),
                                       'text': report.read_text(errors='replace')}}}
    return {'mode': 'librelane', 'record': str(state_path),
            'record_sha256': ls.digest(state_path), 'state_sha256': ls.digest(state_path),
            'folder': str(folder), 'corners': corners}


def sta(project: Path, state_path: Path, name: str) -> dict:
    from librelane_contract import Refusal
    try:
        arm = sta_arm(project, state_path)
        if name == 'hold_corner':
            import hold_corner_coverage_check as judge
            verdict, _, doc = judge.judge_tool(arm)
            return dict(doc, verdict=verdict)
        if name == 'sta_corner':
            import post_route_signoff_corner_check as judge
            return judge.evaluate_tool(arm, judge._DEFAULT_SLACK_TOL_NS)
        import sta_corner_record_completeness_check as judge
        return judge.evaluate_tool(project, arm)
    except (Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        return result(missing=[str(exc)])
