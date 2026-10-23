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


def basis(project, top, liberties, *, coupling=False, extra_inputs=(), physical_top=None,
          spef=None, netlist=None, sdc=None, allowed_external=()):
    """Bind logical artifact paths and the module those bytes actually describe.

    A distinct physical top is supplied by the validated tool configuration;
    receipt validation re-derives it from that authority, never from filenames.
    Tool-selected netlist, SDC and SPEF paths are re-derived from the validated
    corner State; the artifact alias need not name those material files.
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
    if not isinstance(records, list) or not records:
        raise Refusal('CURRENT_FILE_BINDINGS_MISSING' + (": " + "check_files.records argument: expected a nonempty list of role/path/resolved/sha256 bindings; no files opened"))
    allowed_external = set(allowed_external)
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get("role"), str):
            raise Refusal("CURRENT_FILE_BINDING_TYPE")
        role = row['role']
        now = file_record(row['path'], role, None if (role.startswith('liberty:')
                          or role in allowed_external) else project)
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
    transport = receipt.get('input_transport') or {}
    check_files(receipt['inputs'], project,
                allowed_external=transport.get('roles') or ())
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
    roles = {r['role']: Path(r['path']) for r in doc['inputs']}
    libs = [roles[f'liberty:{i}'] for i in range(sum(k.startswith('liberty:') for k in roles))]
    # A receipt cannot authorize its own alternate module name. Resolve the
    # current canonical producer first, then compare both identities below.
    tool_current = None
    if 'tool_state' in roles:
        tool_current, _ = tool_subject(project, doc['top'], corner=doc.get('tool_corner'),
                                       coupling=str(step) == '27')
    transport = (tool_current or {}).get('input_transport') or {}
    check_files(doc['inputs'], project,
                allowed_external=transport.get('roles') or ())
    physical_top = (tool_current or {}).get('physical_top', doc['top'])
    if doc.get('physical_top', doc['top']) != physical_top:
        raise Refusal('CURRENT_TOOL_DESIGN_MISMATCH')
    current = tool_current or basis(project, doc['top'], libs, coupling=str(step) == '27',
                                    physical_top=physical_top)
    # Ordinary locations or the exact validated tool scene own these roles.
    # A hashed sibling SPEF cannot stand in for the corner the producer selected.
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
        raise Refusal('CURRENT_TOOL_COMPLETION_MISSING' + f": {receipt_path}: execution.log={ex['log']}, execution.script={ex['script']} require completion marker {marker(doc)!r}")
    check_files(doc['outputs'], project)
    expected_outputs = {role: str(Path(path).absolute()) for role, path in outputs}
    got = {r['role']: r['path'] for r in doc['outputs']}
    if got != expected_outputs or len(got) != len(doc['outputs']):
        raise Refusal('CURRENT_DOWNSTREAM_CONSUMPTION_MISSING' + f": {receipt_path}: outputs role/path bindings={got!r}; downstream requires {expected_outputs!r}")
    return doc


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
        raise Refusal('CURRENT_POWER_CONSUMPTION_MISSING' + f": {rpt.with_suffix('.current.json')}: outputs role/path must bind power_report={str(rpt.absolute())!r}")
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
    timing_receipt = validate(project, timing.with_suffix('.current.json'), '27',
                              [('timing_windows', timing)])
    timing_has_windows(timing)
    receipt = validate(project, rpt.with_suffix('.current.json'), '27',
                       [('si_report', rpt), ('si_result', rpt.with_suffix('.json'))])
    named = {r['role']: r['path'] for r in receipt['inputs']}
    if named.get('timing_windows') != str(timing) or named.get('timing_receipt') != str(timing.with_suffix('.current.json')):
        raise Refusal('CURRENT_SI_TIMING_CONSUMPTION_MISSING' + f": {rpt.with_suffix('.current.json')}: inputs timing_windows={named.get('timing_windows')!r}, timing_receipt={named.get('timing_receipt')!r}; require {timing} and {timing.with_suffix('.current.json')}")
    if (doc.get('spef') != named.get('spef')
            or doc['timing_aware_advisory'].get('spef') != named.get('spef')):
        raise Refusal('CURRENT_SI_SPEF_CONSUMPTION_MISMATCH')
    report_inputs = {r['role']: r for r in receipt['inputs']
                     if r['role'] not in ('timing_windows', 'timing_receipt')}
    if (report_inputs != {r['role']: r for r in timing_receipt['inputs']}
            or any(receipt.get(key) != timing_receipt.get(key) for key in
                   ('top', 'physical_top', 'corner', 'tool_corner', 'tool_image'))):
        raise Refusal('CURRENT_SI_TIMING_SUBJECT_MISMATCH')
    return receipt


def _validated_original_state_transport(project, state_files, image):
    """Authorize only exact inputs of one retained Default fill owner.

    A Flow-109 component may live in an isolated transport project while its
    immutable final-fill ODB/DEF/netlist/SDC remain at the original Default
    owner's paths.  The executed STAPostPNR readset already hashes those
    objects.  Reopen the existing fill/stream and signoff owners as the second
    authority; an arbitrary outside pathname in the readset is never enough.
    """
    import _physical_current as physical
    import librelane_contract as lc
    import librelane_fill_dfm as fill

    project = Path(project).resolve()
    if not isinstance(state_files, dict) or not state_files:
        raise Refusal('CURRENT_STAPOSTPNR_STATE_READSET_MISSING')
    paths = []
    recorded_by_path = {}
    for name, recorded in state_files.items():
        path = Path(name)
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise Refusal(f'CURRENT_STAPOSTPNR_ORIGINAL_INPUT_MISSING: {path}') from exc
        if (path.is_symlink() or not resolved.is_file()
                or not isinstance(recorded, str) or recorded != digest(resolved)):
            raise Refusal(f'CURRENT_STAPOSTPNR_ORIGINAL_INPUT_CHANGED: {path}')
        paths.append(resolved)
        recorded_by_path[resolved] = recorded
    foreign = {path for path in paths if not path.is_relative_to(project)}
    if not foreign:
        return None

    roots = None
    for path in foreign:
        owned = {parent for parent in path.parents
                 if (parent / fill.RECORD_REL).is_file()}
        roots = owned if roots is None else roots & owned
    if not roots or len(roots) != 1:
        raise Refusal('CURRENT_STAPOSTPNR_FOREIGN_INPUT')
    owner = next(iter(roots)).resolve()
    try:
        stream = fill.validate_default_stream(owner)
        selected = physical.default_signoff_inputs(owner)
        doc = json.loads((owner / fill.RECORD_REL).read_text())
        tool = doc['odb']['tool']
        state_path = Path(tool['state']).resolve(strict=True)
        lc.validate_step_receipt(state_path.parent, fill.ODB_FILL_STEP)
        if (digest(state_path) != tool['state_sha256']
                or stream.get('image') != image
                or not isinstance(selected, dict)):
            raise ValueError('owner State/image/signoff mapping changed')
        state = json.loads(state_path.read_text())
        odb, routed_def = (Path(state[name]).resolve(strict=True)
                           for name in ('odb', 'def'))
        if (not odb.is_relative_to(state_path.parent.resolve())
                or digest(routed_def) != tool['filled_def_sha256']):
            raise ValueError('owner ODB/DEF binding changed')
        expected = {odb, routed_def, Path(selected['netlist']).resolve(strict=True),
                    Path(selected['sdc']).resolve(strict=True)}
    except (OSError, ValueError, KeyError, TypeError, lc.Refusal) as exc:
        raise Refusal(f'CURRENT_STAPOSTPNR_ORIGINAL_OWNER_INVALID: {exc}') from exc
    if not foreign <= expected:
        raise Refusal('CURRENT_STAPOSTPNR_FOREIGN_INPUT')
    return {'kind': 'validated_default_fill_original',
            'source_project': str(owner),
            'source_record': {'path': str((owner / fill.RECORD_REL).resolve()),
                              'sha256': digest(owner / fill.RECORD_REL)},
            'paths': {str(path): recorded_by_path[path] for path in sorted(foreign)}}


def _tool_common(project, top):
    """Validate the immutable Step23/owner inputs once for one caller attempt.

    The retained run_chain fingerprint, not recomputed State hashes, binds the
    original material files. Netlist/SDC copies must match those bytes; the
    selected corner's SPEF is consumed directly, without rewriting a nominal alias.
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
    fp = receipt['input']
    # An explicit image still declares the producer. Without one, use the
    # validated receipt rather than the current consumer's ambient image.
    image = evidence._image(project, {**switch, 'image': switch.get('image') or fp.get('image')})
    if fp.get('image') != image:
        raise Refusal('CURRENT_STAPOSTPNR_IMAGE_CHANGED')
    mounts = evidence._pdk_mounts(project, switch, folder, image)
    runtime = image
    if str(image).startswith(lc.LOCAL_PROVIDER_IDENTITY_PREFIX):
        evidence._retained_local_provider(project, fp.get('local_provider'), image)
        runtime = lc.resolve_image(project, record=False)
    evidence._hashes(fp.get('state_files'))
    evidence._hashes(fp.get('config_files'), mounts)
    evidence._hashes(fp.get('liberty_files'), mounts)
    if not fp.get('liberty_files'):
        raise Refusal('CURRENT_STAPOSTPNR_LIBERTY_BINDING_MISSING' + f": {folder / 'vibeic_receipt.json'}: input.liberty_files requires nonempty executed Liberty bindings")
    transport = _validated_original_state_transport(project, fp['state_files'], image)
    config = json.loads((folder / 'config.json').read_text())
    original_config = project / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    if (digest(original_config) != fp.get('config')
            or receipt['sha256'].get('config.json') != digest(folder / 'config.json')
            or config.get('DESIGN_NAME') != json.loads(original_config.read_text()).get('DESIGN_NAME')):
        raise Refusal('CURRENT_STAPOSTPNR_CONFIG_OR_DESIGN_CHANGED')
    physical_top = config.get('DESIGN_NAME')
    if not isinstance(physical_top, str) or not re.fullmatch(r'[A-Za-z_][\w$]*', physical_top):
        raise Refusal('CURRENT_DESIGN_NAME_INVALID')
    record_path = project / lp.STEP23_RECORD
    record = json.loads(record_path.read_text())
    selected_corner = ((record.get('judgment') or {}).get('worst_setup') or {}).get('corner')
    return {'project': project, 'top': top, 'folder': folder, 'fp': fp,
            'image': image, 'runtime': runtime, 'mounts': mounts,
            'transport': transport, 'physical_top': physical_top,
            'selected_corner': selected_corner, 'switch_path': switch_path,
            'original_config': original_config, 'record_path': record_path}


def _tool_subject_from_common(common, *, corner=None, coupling=False):
    """Validate one corner against a call-local, already validated snapshot."""
    import librelane_contract as lc

    project, top, folder = (common[name] for name in ('project', 'top', 'folder'))
    fp, image, runtime = (common[name] for name in ('fp', 'image', 'runtime'))
    mounts, transport = common['mounts'], common['transport']
    physical_top, selected_corner = common['physical_top'], common['selected_corner']
    switch_path, original_config = common['switch_path'], common['original_config']
    if coupling and corner is not None and corner != selected_corner:
        raise Refusal('CURRENT_SI_CORNER_MISMATCH')
    corner = corner or selected_corner
    if not corner:
        raise Refusal('CURRENT_STAPOSTPNR_CORNER_MISSING' + f": {common['record_path']}: judgment.worst_setup.corner and _tool_subject.corner argument are empty")
    allowed_paths = set(Path(path) for path in (transport or {}).get('paths', {}))
    inputs = lc.post_pnr_timing_inputs(
        project, folder / 'state_out.json', corner,
        allowed_external=allowed_paths)
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
    selected_spef = project / inputs['spef']
    # STAPostPNR carries extraction inputs; a State pathname alone cannot
    # authorize new bytes. Keep the original executed input fingerprint binding.
    if fp['state_files'].get(str(selected_spef)) != digest(selected_spef):
        raise Refusal('CURRENT_STAPOSTPNR_SPEF_HANDOFF_MISMATCH')
    selected_paths = {'netlist': project / inputs['sta_netlist'],
                      'sdc': project / inputs['sdc'],
                      'spef': selected_spef}
    allowed_external = {role for role, path in selected_paths.items()
                        if not path.resolve().is_relative_to(project)}
    subject = basis(project, top, libs, coupling=coupling, physical_top=physical_top,
                    spef=selected_spef, netlist=project / inputs['sta_netlist'],
                    sdc=project / inputs['sdc'], allowed_external=allowed_external)
    roles = {r['role']: r for r in subject['inputs']}
    for role, key in [('netlist', 'sta_netlist'), ('sdc', 'sdc')]:
        if (digest(project / inputs[key]) != roles[role]['sha256']
                or fp['state_files'].get(str(project / inputs[key])) != roles[role]['sha256']):
            raise Refusal(f'CURRENT_STAPOSTPNR_{role.upper()}_HANDOFF_MISMATCH')
    subject['inputs'] += [file_record(path, role, project) for role, path in [
        ('tool_state', folder / 'state_out.json'), ('tool_config', folder / 'config.json'),
        ('tool_receipt', folder / 'vibeic_receipt.json'),
        ('tool_corner_log', folder / corner / 'sta.log'),
        ('step23_record', common['record_path']), ('tool_source_config', original_config)]]
    if switch_path.is_file():
        subject['inputs'].append(file_record(switch_path, 'tool_declaration', project))
    if transport is not None:
        subject['input_transport'] = {**transport,
                                      'roles': sorted(allowed_external)}
    subject['tool_image'] = image
    subject['tool_corner'] = corner
    return subject, {'state': folder / 'state_out.json', 'corner': corner,
                     'liberties': inputs['liberties'], 'image': runtime,
                     'mounts': [(Path(host), guest) for host, guest in mounts]}


def _tool_subject(project, top, *, corner=None, coupling=False):
    """Reuse Step 23's native current state; no producer or mode selection.

    The retained run_chain fingerprint, not recomputed State hashes, binds the
    original material files. Netlist/SDC copies must match those bytes; the
    selected corner's SPEF is consumed directly, without rewriting a nominal alias.
    """
    return _tool_subject_from_common(
        _tool_common(project, top), corner=corner, coupling=coupling)


def tool_subject(project, top, *, corner=None, coupling=False):
    try:
        return _tool_subject(project, top, corner=corner, coupling=coupling)
    except ToolRefusal as exc:
        raise Refusal(str(exc)) from exc


def tool_subject_batch(project, top, corners):
    """Validate all power corners with one attempt-scoped common snapshot.

    This is not a cache: the returned mapping never escapes the caller that
    requested it. Each corner still resolves and hashes its own executed
    Liberty/SPEF/log mapping. The publishing consumer must call its ordinary
    binding validator afterwards, which reopens every common input.
    """
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
