"""Current post-route OpenSTA evidence for SI and power.

These receipts bind material bytes, execution and the files the next reader
actually opens. They certify source identity, not physical qualification.
An absent or invalid receipt is NOT_MEASURED; a measured failure stays FAIL.
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
import uuid
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


def basis(project, top, liberties, *, coupling=False, extra_inputs=(), physical_top=None):
    """Bind logical artifact paths and the module those bytes actually describe.

    A distinct physical top is supplied by the validated tool configuration;
    receipt validation re-derives it from that authority, never from filenames.
    """
    project = Path(project).resolve(strict=True)
    physical_top = top if physical_top is None else physical_top
    if any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][\w$]*', name)
           for name in (top, physical_top)):
        raise Refusal("CURRENT_DESIGN_NAME_INVALID")
    paths = {"netlist": pl.pnr_dir(project) / f"{top}_pnr.v",
             "spef": pl.extracted_dir(project) / f"{top}.spef",
             "sdc": pl.pnr_dir(project) / "constraint.sdc"}
    inputs = [file_record(p, role, project) for role, p in paths.items()]
    if not re.search(r'\bmodule\s+' + re.escape(physical_top) + r'\b', paths['netlist'].read_text()):
        raise Refusal("CURRENT_NETLIST_DESIGN_MISMATCH")
    text = paths['spef'].read_text()
    design = re.search(r'^\*DESIGN\s+"?([^"\s]+)', text, re.M)
    if design is None or design[1] != physical_top:
        raise Refusal("CURRENT_SPEF_DESIGN_MISMATCH")
    if not re.search(r'^\*D_NET\s', text, re.M):
        raise Refusal("CURRENT_SPEF_EXTRACTION_MISSING")
    if coupling:
        import si_mcf_sta as si
        if not si.coupling_pairs(text):
            raise Refusal("CURRENT_SPEF_COUPLING_MISSING")
    libs = [Path(p) for p in liberties]
    if not libs:
        raise Refusal("CURRENT_LIBERTY_MISSING")
    inputs += [file_record(p, f"liberty:{i}") for i, p in enumerate(libs)]
    inputs += [file_record(p, role, project) for role, p in extra_inputs]
    subject = {"project": str(project), "top": top, "stage": "post_route_extracted",
               "corner": corner_identity(libs), "inputs": inputs}
    if physical_top != top:
        subject['physical_top'] = physical_top
    return subject


def check_files(records, project):
    if not isinstance(records, list) or not records:
        raise Refusal("CURRENT_FILE_BINDINGS_MISSING")
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get("role"), str):
            raise Refusal("CURRENT_FILE_BINDING_TYPE")
        role = row['role']
        now = file_record(row['path'], role, None if role.startswith('liberty:') else project)
        if row != now:
            raise Refusal(f"CURRENT_{role.upper()}_BYTES_CHANGED")


def new_execution(subject, step, script, log, argv):
    return {"schema": "opensta-current-v1", "step": str(step), **subject,
            "execution": {"run_id": uuid.uuid4().hex, "tool": "OpenSTA",
                          "argv": argv, "rc": None,
                          "script": str(script), "log": str(log)}}


def marker(receipt):
    return "VIBEIC_CURRENT_DONE " + receipt['execution']['run_id']


def finish(receipt, rc, outputs, receipt_path):
    project = Path(receipt['project'])
    check_files(receipt['inputs'], project)
    execution = receipt['execution']
    log = Path(execution['log'])
    text = log.read_text()
    if type(rc) is not int or rc != 0 or marker(receipt) not in text:
        raise Refusal("CURRENT_TOOL_EXECUTION_MISSING_OR_FAILED")
    if re.search(r'(?mi)^\s*(?:Error:|ERROR\b|REPORT_POWER_FAIL:)', text):
        raise Refusal("CURRENT_TOOL_REPORTED_ERROR")
    execution['rc'] = rc
    execution['files'] = [file_record(execution[k], k, project) for k in ('script', 'log')]
    receipt['outputs'] = [file_record(path, role, project) for role, path in outputs]
    write_json(Path(receipt_path), receipt)
    return receipt


def validate(project, receipt_path, step, outputs):
    project = Path(project).resolve(strict=True)
    receipt_path = Path(receipt_path)
    if not receipt_path.resolve(strict=True).is_relative_to(project):
        raise Refusal("CURRENT_RECEIPT_FOREIGN_PATH")
    doc = json.loads(receipt_path.read_text())
    if (doc.get('schema') != 'opensta-current-v1' or doc.get('step') != str(step)
            or doc.get('project') != str(project) or doc.get('stage') != 'post_route_extracted'):
        raise Refusal("CURRENT_PROJECT_STAGE_OR_STEP_MISMATCH")
    check_files(doc['inputs'], project)
    roles = {r['role']: Path(r['path']) for r in doc['inputs']}
    libs = [roles[f'liberty:{i}'] for i in range(sum(k.startswith('liberty:') for k in roles))]
    # A receipt cannot authorize its own alternate module name. Resolve the
    # current canonical producer first, then compare both identities below.
    tool_current = None
    if 'tool_state' in roles:
        tool_current, _ = tool_subject(project, doc['top'], corner=doc.get('tool_corner'),
                                       coupling=str(step) == '27')
    physical_top = (tool_current or {}).get('physical_top', doc['top'])
    if doc.get('physical_top', doc['top']) != physical_top:
        raise Refusal('CURRENT_TOOL_DESIGN_MISMATCH')
    current = basis(project, doc['top'], libs, coupling=str(step) == '27',
                    physical_top=physical_top)
    # These roles have exactly one ordinary location. A perfectly hashed file
    # from a sibling stage or design still cannot stand in for that location.
    expected = {r['role']: r for r in current['inputs']}
    observed = {r['role']: r for r in doc['inputs']}
    if len(observed) != len(doc['inputs']) or any(observed.get(k) != v for k, v in expected.items()):
        raise Refusal("CURRENT_INPUT_PATH_MISMATCH")
    if doc['corner'] != current['corner']:
        raise Refusal("CURRENT_LIBERTY_CORNER_MISMATCH")
    if tool_current is not None:
        if any(doc.get(k) != v for k, v in tool_current.items() if k != 'inputs'):
            raise Refusal('CURRENT_TOOL_CORNER_SUBJECT_MISMATCH')
        if any(observed.get(row['role']) != row for row in tool_current['inputs']):
            raise Refusal('CURRENT_TOOL_INPUT_HANDOFF_MISMATCH')
    ex = doc['execution']
    if (ex.get('tool') != 'OpenSTA' or type(ex.get('rc')) is not int or ex['rc'] != 0
            or not isinstance(ex.get('argv'), list) or not ex['argv']):
        raise Refusal("CURRENT_TOOL_EXECUTION_MISSING_OR_FAILED")
    check_files(ex['files'], project)
    ex_files = {r['role']: r['path'] for r in ex['files']}
    if ex_files != {k: ex[k] for k in ('script', 'log')}:
        raise Refusal("CURRENT_EXECUTION_PATH_MISMATCH")
    if marker(doc) not in Path(ex['log']).read_text() or marker(doc) not in Path(ex['script']).read_text():
        raise Refusal("CURRENT_TOOL_COMPLETION_MISSING")
    check_files(doc['outputs'], project)
    expected_outputs = {role: str(Path(path).absolute()) for role, path in outputs}
    got = {r['role']: r['path'] for r in doc['outputs']}
    if got != expected_outputs or len(got) != len(doc['outputs']):
        raise Refusal("CURRENT_DOWNSTREAM_CONSUMPTION_MISSING")
    return doc


def timing_has_windows(path):
    data = json.loads(Path(path).read_text())
    pins = data.get('pins')
    if not isinstance(pins, dict) or not pins:
        raise Refusal("CURRENT_TIMING_WINDOWS_MISSING")
    if not any(isinstance(row, dict) and any(type(row.get(k)) in (int, float)
               and math.isfinite(row[k]) for k in ('arr_rise_min', 'arr_rise_max',
               'arr_fall_min', 'arr_fall_max')) for row in pins.values()):
        raise Refusal("CURRENT_TIMING_WINDOWS_UNMEASURED")
    return data


def power_binding(project):
    project = Path(project)
    rpt = pl.reports_phase3_dir(project) / 'power.rpt'
    receipt = json.loads(rpt.with_suffix('.current.json').read_text())
    subject, tool = tool_subject(project, receipt['top'], corner=receipt['tool_corner'])
    if receipt.get('schema') != 'stapostpnr-power-current-v1' or receipt.get('step') != '33':
        raise Refusal('CURRENT_POWER_RECEIPT_TYPE')
    if any(receipt.get(k) != v for k, v in subject.items()):
        raise Refusal('CURRENT_POWER_SUBJECT_CHANGED')
    if receipt.get('tool_state') != str(tool['state']):
        raise Refusal('CURRENT_POWER_TOOL_STAGE_MISMATCH')
    check_files(receipt['outputs'], project)
    if {r['role']: r['path'] for r in receipt['outputs']} != {'power_report': str(rpt.absolute())}:
        raise Refusal('CURRENT_POWER_CONSUMPTION_MISSING')
    source = tool['state'].parent / tool['corner'] / 'power.rpt'
    if receipt.get('source_report') != file_record(source, 'source_power', project):
        raise Refusal('CURRENT_POWER_SOURCE_REPORT_CHANGED')
    from _ppa import power
    corners = power.stapostpnr_corner_power(tool['state'].parent)
    if not corners or any(r['status'] != 'MEASURED' for r in corners.values()):
        raise Refusal('CURRENT_POWER_CORNERS_UNMEASURED')
    worst = max(corners, key=lambda c: corners[c]['total_w'])
    if worst != tool['corner']:
        raise Refusal('CURRENT_POWER_WRONG_CORNER')
    expected = power.current_tool_power_text(worst, corners[worst], source.read_text(), digest(tool['state']), subject)
    if rpt.read_text() != expected:
        raise Refusal('CURRENT_POWER_REPORT_ADOPTION_MISMATCH')
    return receipt


def si_binding(project):
    project = Path(project)
    rpt = pl.reports_phase3_dir(project) / 'si_crosstalk.rpt'
    doc = json.loads(rpt.with_suffix('.json').read_text())
    timing = Path(doc['timing_aware_advisory']['timing_json'])
    validate(project, timing.with_suffix('.current.json'), '27', [('timing_windows', timing)])
    timing_has_windows(timing)
    receipt = validate(project, rpt.with_suffix('.current.json'), '27',
                       [('si_report', rpt), ('si_result', rpt.with_suffix('.json'))])
    named = {r['role']: r['path'] for r in receipt['inputs']}
    if named.get('timing_windows') != str(timing) or named.get('timing_receipt') != str(timing.with_suffix('.current.json')):
        raise Refusal("CURRENT_SI_TIMING_CONSUMPTION_MISSING")
    return receipt


def _tool_subject(project, top, *, corner=None, coupling=False):
    """Reuse Step 23's native current state; no producer or mode selection.

    The retained run_chain fingerprint, not recomputed State hashes, binds the
    original material files. The ordinary route's copies must match those bytes.
    """
    import librelane_contract as lc
    import librelane_postroute as lp
    import librelane_signoff_evidence as evidence
    project = Path(project).resolve(strict=True)
    folder, state = lp.stapostpnr_state(project)
    if not folder.resolve().is_relative_to(project / 'phase3/librelane'):
        raise Refusal('CURRENT_STAPOSTPNR_STAGE_MISMATCH')
    receipt = lc.validate_step_receipt(folder, 'OpenROAD.STAPostPNR')
    switch_path = project / 'phase3/librelane_switch.json'
    switch = json.loads(switch_path.read_text()) if switch_path.is_file() else {}
    image = evidence._image(project, switch)
    fp = receipt['input']
    if fp.get('image') != image:
        raise Refusal('CURRENT_STAPOSTPNR_IMAGE_CHANGED')
    mounts = evidence._pdk_mounts(project, switch, folder, image)
    evidence._hashes(fp.get('state_files'))
    evidence._hashes(fp.get('config_files'), mounts)
    evidence._hashes(fp.get('liberty_files'), mounts)
    if not fp.get('liberty_files'):
        raise Refusal('CURRENT_STAPOSTPNR_LIBERTY_BINDING_MISSING')
    if any(not Path(p).resolve().is_relative_to(project) for p in fp['state_files']):
        raise Refusal('CURRENT_STAPOSTPNR_FOREIGN_INPUT')
    config = json.loads((folder / 'config.json').read_text())
    original_config = project / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    if (digest(original_config) != fp.get('config')
            or receipt['sha256'].get('config.json') != digest(folder / 'config.json')
            or config.get('DESIGN_NAME') != json.loads(original_config.read_text()).get('DESIGN_NAME')):
        raise Refusal('CURRENT_STAPOSTPNR_CONFIG_OR_DESIGN_CHANGED')
    physical_top = config.get('DESIGN_NAME')
    if not isinstance(physical_top, str) or not re.fullmatch(r'[A-Za-z_][\w$]*', physical_top):
        raise Refusal('CURRENT_DESIGN_NAME_INVALID')
    record = json.loads((project / lp.STEP23_RECORD).read_text())
    corner = corner or ((record.get('judgment') or {}).get('worst_setup') or {}).get('corner')
    if not corner:
        raise Refusal('CURRENT_STAPOSTPNR_CORNER_MISSING')
    inputs = lc.post_pnr_timing_inputs(project, folder / 'state_out.json', corner)
    def host(path):
        path = Path(path)
        for source, guest in sorted(mounts, key=lambda m: -len(str(m[1]))):
            if path.is_relative_to(guest):
                return Path(source) / path.relative_to(guest)
        return path
    libs = [host(p) for p in inputs['liberties']]
    if any(str(p) not in fp['liberty_files'] and str(host(p)) not in fp['liberty_files']
           for p in inputs['liberties']):
        raise Refusal('CURRENT_STAPOSTPNR_CORNER_LIBRARY_UNBOUND')
    subject = basis(project, top, libs, coupling=coupling, physical_top=physical_top)
    roles = {r['role']: r for r in subject['inputs']}
    for role, key in [('netlist', 'sta_netlist'), ('sdc', 'sdc'), ('spef', 'spef')]:
        if digest(project / inputs[key]) != roles[role]['sha256']:
            raise Refusal(f'CURRENT_STAPOSTPNR_{role.upper()}_HANDOFF_MISMATCH')
    subject['inputs'] += [file_record(path, role, project) for role, path in [
        ('tool_state', folder / 'state_out.json'), ('tool_config', folder / 'config.json'),
        ('tool_receipt', folder / 'vibeic_receipt.json'),
        ('tool_corner_log', folder / corner / 'sta.log'),
        ('step23_record', project / lp.STEP23_RECORD), ('tool_source_config', original_config)]]
    if switch_path.is_file():
        subject['inputs'].append(file_record(switch_path, 'tool_declaration', project))
    subject['tool_image'] = image
    subject['tool_corner'] = corner
    return subject, {'state': folder / 'state_out.json', 'corner': corner,
                     'liberties': inputs['liberties'], 'image': image,
                     'mounts': [(Path(host), guest) for host, guest in mounts]}


def tool_subject(project, top, *, corner=None, coupling=False):
    try:
        return _tool_subject(project, top, corner=corner, coupling=coupling)
    except ToolRefusal as exc:
        raise Refusal(str(exc)) from exc
