"""Ordinary M4's narrow native-PV binding; existing native readers grade it.

The request contains paths/hashes, never a verdict. Native results use the
existing Step31/26/34 records and run_chain receipts. Verification is read-only.
"""
# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------
from pathlib import Path
import re

from _atomic_artefact import write_json
import mixed_signal_m3_run as m3
import librelane_contract as ll
import librelane_pv_signoff as pv
import librelane_signoff_evidence as evidence
import librelane_fill_dfm as fill
import librelane_ir_antenna as antenna

REQUEST = 'input/mixed_signal/top_pv.json'
OUTPUT = m3.DIR + '/top_pv_run.json'
SCHEMA = 'vibeic.mixed_signal.top_pv_run.v1'
INPUT_SCHEMA = 'vibeic.mixed_signal.top_pv_inputs.v1'
LAYOUT = 'phase3/mixed_signal/top_merged.gds'
KINDS = ('drc', 'lvs', 'antenna', 'density')
RECORDS = tuple(pv.RECORD_REL.format(half=h) for h in ('drc', 'lvs')) + (
    'reports/phase3/antenna_librelane.json', fill.RECORD_REL,
    'phase3/librelane_pdk_root.provenance.json')


def local(project, rel):
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or '..' in Path(rel).parts:
        raise m3.Refusal('FOREIGN_PV_PATH', str(rel))
    path = project / rel
    if not path.resolve().is_relative_to(project):
        raise m3.Refusal('FOREIGN_PV_PATH', rel)
    return path


def request(project, top):
    m3.subject(project, top)
    spec = m3.read(local(project, REQUEST))
    fields = {'schema', 'top', 'scope', 'pdk', 'image', 'layout', 'logical',
              'powered_netlist', 'cdl', 'routed_def', 'sdc', 'spice_models',
              'cdl_models', 'input_sha256'}
    if (set(spec) != fields or spec.get('schema') != INPUT_SCHEMA
            or spec.get('scope') != 'merged_top_native_pv'):
        raise m3.Refusal('PV_DECLARATION_INVALID', REQUEST)
    if spec.get('top') != top or spec.get('layout') != LAYOUT:
        raise m3.Refusal('WRONG_PV_SUBJECT', 'declared top/layout differs from M4')
    switch = m3.read(local(project, 'phase3/librelane_switch.json'))
    try:
        selected = all(ll.selected_mode(project, s) == 'librelane' for s in ('31', '26', '34'))
    except ll.Refusal as exc:
        raise m3.Refusal('PV_TOOL_IDENTITY_UNBOUND', str(exc)) from exc
    if not (spec.get('image') == evidence._image(project, switch)
            and spec.get('pdk') == switch.get('pdk') and selected):
        raise m3.Refusal('PV_TOOL_IDENTITY_UNBOUND', 'PDK/image/native obligations must be declared')
    from tapeout_precheck import resolve_pdk
    if resolve_pdk(project)[0] != spec['pdk']:
        raise m3.Refusal('PV_PDK_MISMATCH', 'design PDK differs from native request')
    required = {REQUEST, LAYOUT, 'phase3/librelane_switch.json',
                m3.DIR + '/merge.json', m3.DIR + '/top_lvs.json',
                'input/submission_template/tapeout_declaration.json'}
    for key in ('logical', 'powered_netlist', 'cdl', 'routed_def', 'sdc'):
        local(project, spec.get(key))
        required.add(spec[key])
    for key in ('spice_models', 'cdl_models'):
        if not isinstance(spec.get(key), list) or not spec[key]:
            raise m3.Refusal('PV_MODELS_UNDECLARED', key)
        required.update(str(local(project, p).relative_to(project)) for p in spec[key])
    for pattern in ('phase1/generated_docs/L8*.json', 'phase1/generated_docs/L9*.json',
                    'phase1/generated_docs/L19*.json', 'phase3/analog/**/*.gds'):
        required.update(str(p.relative_to(project)) for p in project.glob(pattern) if p.is_file())
    merge = m3.read(project / (m3.DIR + '/merge.json'))
    lvs = m3.read(project / (m3.DIR + '/top_lvs.json'))
    if not (merge.get('verdict') == lvs.get('verdict') == 'PASS'
            and merge.get('merged_gds') == lvs.get('layout') == LAYOUT
            and lvs.get('program') == 'mixed_signal_top_lvs_run'
            and lvs.get('layout_top') == top
            and spec['logical'] in lvs.get('schematic', [])):
        raise m3.Refusal('PV_M1_IDENTITY_UNBOUND', 'current M1 merge/LVS must describe the declared pair')
    required.update(lvs.get('schematic', []))
    required.update(merge.get('macros_merged', []))
    required.update(lvs.get(k) for k in ('extracted_netlist', 'lvs_report'))
    hashes = spec.get('input_sha256')
    if not isinstance(hashes, dict) or not (required - {REQUEST}).issubset(hashes):
        raise m3.Refusal('PV_INPUT_HASHES_INCOMPLETE', 'all material design/M1 inputs need hashes')
    current = {REQUEST: m3.digest(project / REQUEST)}
    for rel, sha in hashes.items():
        path = local(project, rel)
        if not path.is_file() or m3.digest(path) != sha:
            raise m3.Refusal('PV_INPUT_CHANGED_OR_MISSING', rel)
        current[rel] = sha
    for key in ('logical', 'powered_netlist'):
        source = (project / spec[key]).read_text()
        if '`include' in source:
            raise m3.Refusal('PV_UNBOUND_MODEL_DEPENDENCY', key)
        if not re.search(r'\bmodule\s+' + re.escape(top) + r'\b', source):
            raise m3.Refusal('WRONG_PV_LOGICAL_DESIGN', key)
    for rel in [spec['cdl'], *spec['spice_models'], *spec['cdl_models']]:
        if re.search(r'^\s*\.(?:include|inc|lib)\b', (project / rel).read_text(), re.I | re.M):
            raise m3.Refusal('PV_UNBOUND_MODEL_DEPENDENCY', rel)
    return spec, current


def outputs(project):
    paths = set(RECORDS)
    for lane in ('31-drc', '31-lvs', '31-drc-config', '31-lvs-config',
                 '26-config', '26', '26-gds', '34-config', 'm4-density'):
        paths.update(str(p.relative_to(project)) for p in
                     (project / 'phase3/librelane' / lane).rglob('*') if p.is_file())
    return {rel: m3.digest(local(project, rel)) if local(project, rel).is_file() else None
            for rel in sorted(paths)}


def verify(project, top):
    """Prove current execution bytes; never resolve a PDK or invoke a tool."""
    data = m3.read(local(project, OUTPUT))
    spec, inputs = request(project, top)
    if not (data.get('schema') == SCHEMA and data.get('program') == 'mixed_signal_signoff_run'
            and data.get('project') == str(project) and data.get('top') == top
            and data.get('inputs') == inputs and data.get('outputs') == outputs(project)
            and data.get('image') == spec['image'] and data.get('pdk') == spec['pdk']):
        raise m3.Refusal('STALE_OR_MISMATCHED_PV_PRODUCTION', OUTPUT)
    current = {kind: evidence.obligation(project, kind, layout=project / LAYOUT, mixed_top=True)
               for kind in KINDS}
    if current != data.get('native'):
        raise m3.Refusal('PV_NATIVE_DERIVATION_CHANGED', OUTPUT)
    return data


def produce(project, top):
    """Run applicable existing producers sequentially; retain honest refusals."""
    project = project.resolve()
    who = m3.subject(project, top)
    destination = local(project, OUTPUT)
    destination.unlink(missing_ok=True)
    report = {'program': 'mixed_signal_signoff_run', 'schema': SCHEMA, **who,
              'inputs': None, 'outputs': None, 'native': {}, 'refusals': []}
    try:
        spec, inputs = request(project, top)
        report.update(inputs=inputs, image=spec['image'], pdk=spec['pdk'])
        # Withdraw previous summary records before this invocation. Exact
        # native snapshots may be reused only by run_chain's material contract.
        for rel in RECORDS:
            local(project, rel).unlink(missing_ok=True)
        root = Path(ll.pdk_root_resolution(project, spec['pdk'], image=spec['image'])['path'])
        overlay = {'DESIGN_NAME': (top, REQUEST + ': top'),
                   'VERILOG_FILES': ([str(project / spec['logical'])], REQUEST + ': logical'),
                   'FALLBACK_SDC': (str(project / spec['sdc']), REQUEST + ': current SDC'),
                   'EXTRA_SPICE_MODELS': ([str(project / p) for p in spec['spice_models']], REQUEST),
                   'EXTRA_CDLS': ([str(project / p) for p in spec['cdl_models']], REQUEST)}
        views = {key: project / spec[field] for key, field in {
            'gds': 'layout', 'def': 'routed_def', 'nl': 'logical', 'pnl': 'powered_netlist',
            'cdl': 'cdl', 'sdc': 'sdc'}.items()}
        for half in ('drc', 'lvs'):
            try:
                pv.run_mixed_top(project, spec['image'], root, spec['pdk'], half,
                                 views=views, overlay=overlay)
            except (ll.Refusal, ValueError, OSError, KeyError, TypeError) as exc:
                report['refusals'].append(f'{half}: {exc}')
        try:
            configs = ll.resolve_step_configs(project, spec['image'], spec['pdk'],
                list(fill.DENSITY_STEPS), pdk_root=root, folder='34-config', overlay=overlay)
            measured = fill.run_density(project, spec['image'], root, spec['pdk'],
                                       gds=views['gds'], lane='m4-density', configs=configs)
            fill.update_record(project, 'gds', {'shipped': 'mixed_top', 'mixed_top': measured})
        except (ll.Refusal, ValueError, OSError, KeyError, TypeError) as exc:
            report['refusals'].append(f'density: {exc}')
        models = {'step': '26', 'def_sha256': m3.digest(views['def'])}
        for model in ('router', 'gds'):
            try:
                if model == 'gds':
                    value = antenna.run_antenna_gds(project, spec['image'], root, spec['pdk'],
                                                  gds=views['gds'], overlay=overlay)
                else:
                    value = antenna.run_antenna_router(project, spec['image'], root, spec['pdk'],
                        routed_def=views['def'], netlist=views['nl'], sdc=views['sdc'], overlay=overlay)
                models[model] = value
            except (ll.Refusal, ValueError, OSError, KeyError, TypeError) as exc:
                report['refusals'].append(f'antenna {model}: {exc}')
        # No affirmative route-completeness flags are inferred from a small
        # PV fixture or from a zero antenna count.
        write_json(local(project, 'reports/phase3/antenna_librelane.json'), models)
        if request(project, top)[1] != inputs:
            raise m3.Refusal('PV_INPUT_CHANGED_DURING_RUN', REQUEST)
        report['native'] = {kind: evidence.obligation(project, kind, layout=views['gds'], mixed_top=True)
                            for kind in KINDS}
        report['outputs'] = outputs(project)
    except (ll.Refusal, ValueError, OSError, KeyError, TypeError) as exc:
        report['refusals'].append(f'{getattr(exc, "rule", "INVALID_PV_INPUT")}: {exc}')
    write_json(destination, report)
    return report
