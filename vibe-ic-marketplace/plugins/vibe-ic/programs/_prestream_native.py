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
from pathlib import Path


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


def final_state(project: Path, *, streamed: bool = False) -> Path | None:
    # Prefer the selected State. The existing signoff pointer is only a path;
    # its publisher, hashes and signatures are not admission requirements (#62).
    direct = project / 'state_out.json'
    if direct.is_file():
        return direct.resolve()
    if streamed:
        streams = []
        for candidate in sorted((project / 'phase3/librelane').glob('**/state_out.json')):
            meta = load(candidate.parent / 'config.json').get('meta')
            if isinstance(meta, dict) and meta.get('step') in (
                    'KLayout.StreamOut', 'Magic.StreamOut', 'Vibeic.FillAwareStreamOut'):
                streams.append(candidate)
        if len(streams) > 1:
            raise ValueError('CURRENT_FINAL_STATE_AMBIGUOUS: ' + ', '.join(map(str, streams)))
        if streams:
            return streams[0]
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


def signoff_inputs(project: Path, *roles: str) -> dict[str, Path]:
    """Require the caller's views from one selected final LibreLane State."""
    project = Path(project).resolve()
    selected = final_state(project, streamed=True)
    if selected is None:
        raise ValueError('CURRENT_FINAL_STATE_MISSING: state_out.json')
    state = load(selected)
    views = {}
    for role in roles:
        name = 'nl' if role == 'netlist' else role
        if role == 'gds' and state.get('gds') in (None, ''):
            name = 'klayout_gds' if 'klayout_gds' in state else 'gds'
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
    from drv_signoff_judge import _sdc_values, _liberty_limits, parse_check_types
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
