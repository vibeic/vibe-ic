"""Current post-route OpenSTA evidence for SI and power.

Read the actual native State, configuration, reports and their original numbers.
Missing measurements remain NOT_MEASURED and measured failures remain FAIL.
"""
from __future__ import annotations


# `programs/` is a flat directory whose modules import each other by bare name
# (vibe-ic#2104): restore the condition a by-path load does not provide.
import os as _os
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import hashlib
import json
import math
import re
from pathlib import Path

from librelane_contract import Refusal as ToolRefusal

import _path_layout as pl
from _atomic_artefact import write_json


class Refusal(ToolRefusal, ValueError):
    def __init__(self, message):
        ValueError.__init__(self, message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_record(path, role, project=None):
    path = Path(path).absolute()
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise Refusal(f"CURRENT_{role.upper()}_MISSING: {path}")
    if project is not None and not resolved.is_relative_to(project.resolve()):
        raise Refusal(f"CURRENT_{role.upper()}_FOREIGN_PATH: {path}")
    return {"role": role, "path": str(path), "resolved": str(resolved),
            "sha256": digest(resolved)}


def corner_identity(liberties):
    # The corner is the library's declaration plus exact bytes, never a guessed
    # 'typical' label. Macro libraries remain distinct members of this list.
    out = []
    for path in liberties:
        text = Path(path).read_text()
        name = re.search(r'\blibrary\s*\(\s*"?([^\s"\)]+)', text)
        if name is None:
            raise Refusal(f"CURRENT_LIBERTY_UNDECLARED: {path}")
        op = re.search(r'\bdefault_operating_conditions\s*:\s*([^;]+);', text)
        out.append({"library": name[1], "operating_conditions":
                    op[1].strip().strip('"') if op else None,
                    "sha256": digest(path)})
    return out


def basis(project, top, liberties, *, coupling=False, extra_inputs=(), physical_top=None,
          spef=None, netlist=None, sdc=None, allowed_external=()):
    """Read the selected circuit files and their declared module and corner.

    The native configuration supplies the physical top. Native State supplies
    the netlist, SDC and SPEF paths.
    """
    project = Path(project).resolve(strict=True)
    physical_top = top if physical_top is None else physical_top
    if any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][\w$]*', name)
           for name in (top, physical_top)):
        raise Refusal("CURRENT_DESIGN_NAME_INVALID")
    paths = {"netlist": Path(netlist) if netlist is not None else pl.pnr_dir(project) / f"{top}_pnr.v",
             "spef": Path(spef) if spef is not None else pl.extracted_dir(project) / f"{top}.spef",
             "sdc": Path(sdc) if sdc is not None else pl.pnr_dir(project) / "constraint.sdc"}
    allowed_external = set(allowed_external)
    inputs = [file_record(p, role, None if role in allowed_external else project)
              for role, p in paths.items()]
    if not re.search(r'\bmodule\s+' + re.escape(physical_top) + r'\b', paths['netlist'].read_text()):
        raise Refusal("CURRENT_NETLIST_DESIGN_MISMATCH")
    text = paths['spef'].read_text()
    design = re.search(r'^\*DESIGN\s+"?([^"\s]+)', text, re.M)
    if design is None or design[1] != physical_top:
        raise Refusal("CURRENT_SPEF_DESIGN_MISMATCH")
    if not re.search(r'^\*D_NET\s', text, re.M):
        raise Refusal('CURRENT_SPEF_EXTRACTION_MISSING' + f": {paths['spef']}: SPEF requires a *D_NET extraction section")
    if coupling:
        import si_mcf_sta as si
        if not si.coupling_pairs(text):
            raise Refusal('CURRENT_SPEF_COUPLING_MISSING' + f": {paths['spef']}: SPEF requires inter-net coupling capacitance pairs")
    libs = [Path(p) for p in liberties]
    if not libs:
        raise Refusal('CURRENT_LIBERTY_MISSING' + f": basis.liberties argument={liberties!r}: no Liberty files selected; no library search performed")
    inputs += [file_record(p, f"liberty:{i}") for i, p in enumerate(libs)]
    inputs += [file_record(p, role, project) for role, p in extra_inputs]
    subject = {"project": str(project), "top": top, "stage": "post_route_extracted",
               "corner": corner_identity(libs), "inputs": inputs}
    if physical_top != top:
        subject['physical_top'] = physical_top
    return subject


def check_files(records, project, *, allowed_external=()):
    """Require the actual inputs and measured outputs to be readable."""
    if not isinstance(records, list) or not records:
        raise Refusal("CURRENT_FILES_MISSING")
    allowed_external = set(allowed_external)
    for row in records:
        role = row['role']
        file_record(row['path'], role, None if role.startswith('liberty:')
                    or role in allowed_external else project)










def timing_has_windows(path):
    data = json.loads(Path(path).read_text())
    pins = data.get('pins')
    if not isinstance(pins, dict) or not pins:
        raise Refusal('CURRENT_TIMING_WINDOWS_MISSING' + f": {path}: timing JSON pins must be a nonempty object")
    if not any(isinstance(row, dict) and any(type(row.get(k)) in (int, float)
               and math.isfinite(row[k]) for k in ('arr_rise_min', 'arr_rise_max',
               'arr_fall_min', 'arr_fall_max')) for row in pins.values()):
        raise Refusal("CURRENT_TIMING_WINDOWS_UNMEASURED")
    return data


def power_binding(project):
    """Read the native measured power corners and the normal power report."""
    import librelane_postroute as lp
    from _ppa import power
    project = Path(project)
    folder, _ = lp.stapostpnr_state(project)
    corners = power.stapostpnr_corner_power(folder)
    if not corners or any(row['status'] != 'MEASURED' for row in corners.values()):
        raise Refusal('CURRENT_POWER_CORNERS_UNMEASURED')
    worst = max(corners, key=lambda corner: corners[corner]['total_w'])
    rpt = pl.reports_phase3_dir(project) / 'power.rpt'
    parsed = power.read_power_report(rpt)
    measured = power.signoff_record(parsed, source='reports/phase3/power.rpt')
    if measured.get('power_measurement') != 'MEASURED':
        raise Refusal('CURRENT_POWER_REPORT_UNMEASURED')
    if parsed['total_row']['total_w'] != corners[worst]['total_w']:
        raise Refusal('CURRENT_POWER_WORST_CORNER_MISMATCH')
    return {'corners': corners, 'tool_corner': worst, 'report': str(rpt)}






def _tool_common(project, top):
    """Read the native post-route State, configuration and tool environment."""
    import librelane_postroute as lp
    import librelane_signoff_evidence as evidence
    project = Path(project).resolve(strict=True)
    folder, state = lp.stapostpnr_state(project)
    config = json.loads((folder / 'config.json').read_text())
    physical_top = config.get('DESIGN_NAME')
    if not isinstance(physical_top, str) or not re.fullmatch(r'[A-Za-z_][\w$]*', physical_top):
        raise Refusal('CURRENT_DESIGN_NAME_INVALID')
    switch_path = project / 'phase3/librelane_switch.json'
    switch = json.loads(switch_path.read_text()) if switch_path.is_file() else {}
    runtime = evidence._image(project, switch)
    mounts = evidence._pdk_mounts(project, switch, folder, runtime)
    record_path = project / lp.STEP23_RECORD
    record = json.loads(record_path.read_text()) if record_path.is_file() else {}
    selected_corner = ((record.get('judgment') or {}).get('worst_setup') or {}).get('corner')
    return {'project': project, 'top': top, 'folder': folder,
            'image': runtime, 'runtime': runtime, 'mounts': mounts,
            'physical_top': physical_top, 'selected_corner': selected_corner,
            'switch_path': switch_path, 'record_path': record_path}


def _tool_subject_from_common(common, *, corner=None, coupling=False):
    """Select the actual netlist, SDC, SPEF and Liberty files for a corner."""
    import librelane_contract as lc
    project, top, folder = (common[name] for name in ('project', 'top', 'folder'))
    mounts = common['mounts']
    selected_corner = common['selected_corner']
    if coupling and corner is not None and corner != selected_corner:
        raise Refusal('CURRENT_SI_CORNER_MISMATCH')
    corner = corner or selected_corner
    if not corner:
        raise Refusal('CURRENT_STAPOSTPNR_CORNER_MISSING')
    inputs = lc.post_pnr_timing_inputs(project, folder / 'state_out.json', corner)
    def host(value):
        path = Path(value)
        for source, guest in sorted(mounts, key=lambda m: -len(str(m[1]))):
            if path.is_relative_to(guest):
                return Path(source) / path.relative_to(guest)
        return path
    libs = [host(p) for p in inputs['liberties']]
    paths = {'netlist': project / inputs['sta_netlist'],
             'sdc': project / inputs['sdc'], 'spef': project / inputs['spef']}
    allowed_external = {role for role, path in paths.items()
                        if not path.resolve().is_relative_to(project)}
    subject = basis(project, top, libs, coupling=coupling,
                    physical_top=common['physical_top'],
                    netlist=paths['netlist'], sdc=paths['sdc'], spef=paths['spef'],
                    allowed_external=allowed_external)
    subject['inputs'] += [file_record(path, role, project) for role, path in [
        ('tool_state', folder / 'state_out.json'), ('tool_config', folder / 'config.json'),
        ('tool_corner_log', folder / corner / 'sta.log')]]
    subject['tool_image'] = common['image']
    subject['tool_corner'] = corner
    return subject, {'state': folder / 'state_out.json', 'corner': corner,
                     'liberties': inputs['liberties'], 'image': common['runtime'],
                     'mounts': [(Path(source), guest) for source, guest in mounts]}


def _tool_subject(project, top, *, corner=None, coupling=False):
    """Read the requested corner from the native post-route State."""
    return _tool_subject_from_common(
        _tool_common(project, top), corner=corner, coupling=coupling)


def tool_subject(project, top, *, corner=None, coupling=False):
    try:
        return _tool_subject(project, top, corner=corner, coupling=coupling)
    except ToolRefusal as exc:
        raise Refusal(str(exc)) from exc


def tool_subject_batch(project, top, corners):
    """Read every requested power corner using the native tool configuration."""
    corners = list(corners)
    if (not corners or any(not isinstance(corner, str) or not corner for corner in corners)
            or len(set(corners)) != len(corners)):
        raise Refusal('CURRENT_STAPOSTPNR_CORNER_BATCH_INVALID')
    try:
        common = _tool_common(project, top)
        return {corner: _tool_subject_from_common(common, corner=corner)
                for corner in corners}
    except ToolRefusal as exc:
        raise Refusal(str(exc)) from exc
