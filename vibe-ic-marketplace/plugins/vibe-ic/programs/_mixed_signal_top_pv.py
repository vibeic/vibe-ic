"""Run existing native merged-top physical checks and read their measurements."""

# `programs/` is a flat directory whose modules import each other by bare name
# (vibe-ic#2104): restore the condition a by-path load does not provide.
import os as _os
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
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
)


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
    if spec.get("top") != top or spec.get("layout") != LAYOUT:
        raise m3.Refusal("WRONG_PV_SUBJECT", "declared top/layout differs from the native subject")
    from tapeout_precheck import resolve_pdk
    if resolve_pdk(project)[0] != spec["pdk"]:
        raise m3.Refusal("PV_PDK_MISMATCH", "design PDK differs from native request")
    for key in ("logical", "powered_netlist", "cdl", "routed_def", "sdc"):
        path = local(project, spec[key])
        if not path.is_file():
            raise m3.Refusal("PV_INPUT_MISSING", spec[key])
    for key in ("spice_models", "cdl_models"):
        if not isinstance(spec.get(key), list) or not spec[key]:
            raise m3.Refusal("PV_MODELS_UNDECLARED", key)
        for relative in spec[key]:
            if not local(project, relative).is_file():
                raise m3.Refusal("PV_INPUT_MISSING", relative)
    merge = m3.read(project / (m3.DIR + "/merge.json"))
    lvs = m3.read(project / (m3.DIR + "/top_lvs.json"))
    if not (merge.get("verdict") == lvs.get("verdict") == "PASS"
            and merge.get("merged_gds") == lvs.get("layout") == LAYOUT
            and lvs.get("layout_top") == top
            and spec["logical"] in lvs.get("schematic", [])):
        raise m3.Refusal("PV_M1_UNAVAILABLE", "native M1 merge/LVS must describe the declared pair")
    for key in ("logical", "powered_netlist"):
        source = (project / spec[key]).read_text()
        if not re.search(r"\bmodule\s+" + re.escape(top) + r"\b", source):
            raise m3.Refusal("WRONG_PV_LOGICAL_DESIGN", key)
    return spec




def verify(project, top):
    """Read the native physical checks for the declared merged layout."""
    spec = request(project, top)
    return {"pdk": spec["pdk"], "native": {
        kind: evidence.obligation(project, kind, layout=project / LAYOUT, mixed_top=True)
        for kind in KINDS}}


def produce(project, top):
    """Run applicable existing producers sequentially; retain honest refusals."""
    project = project.resolve()
    who = m3.subject(project, top)
    destination = local(project, OUTPUT)
    destination.unlink(missing_ok=True)
    report = {'program': 'mixed_signal_signoff_run', 'schema': SCHEMA, **who,
              'native': {}, 'refusals': []}
    try:
        spec = request(project, top)
        image = evidence._image(project, spec)
        report.update(image=str(image), pdk=spec['pdk'])
        # Each native producer writes the result of its own tool invocation.
        for rel in RECORDS:
            local(project, rel).unlink(missing_ok=True)
        root = Path(ll.pdk_root_resolution(project, spec['pdk'], image=image)['path'])
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
                pv.run_mixed_top(project, image, root, spec['pdk'], half,
                                 views=views, overlay=overlay)
            except (ll.Refusal, ValueError, OSError, KeyError, TypeError) as exc:
                report['refusals'].append(f'{half}: {exc}')
        try:
            configs = ll.resolve_step_configs(project, image, spec['pdk'],
                list(fill.DENSITY_STEPS), pdk_root=root, folder='34-config', overlay=overlay)
            measured = fill.run_density(project, image, root, spec['pdk'],
                                       gds=views['gds'], lane='m4-density', configs=configs)
            fill.update_record(project, 'gds', {'shipped': 'mixed_top', 'mixed_top': measured})
        except (ll.Refusal, ValueError, OSError, KeyError, TypeError) as exc:
            report['refusals'].append(f'density: {exc}')
        models = {'step': '26'}
        for model in ('router', 'gds'):
            try:
                if model == 'gds':
                    value = antenna.run_antenna_gds(project, image, root, spec['pdk'],
                                                  gds=views['gds'], overlay=overlay)
                else:
                    value = antenna.run_antenna_router(project, image, root, spec['pdk'],
                        routed_def=views['def'], netlist=views['nl'], sdc=views['sdc'], overlay=overlay)
                models[model] = value
            except (ll.Refusal, ValueError, OSError, KeyError, TypeError) as exc:
                report['refusals'].append(f'antenna {model}: {exc}')
        # No affirmative route-completeness flags are inferred from a small
        # PV fixture or from a zero antenna count.
        write_json(local(project, 'reports/phase3/antenna_librelane.json'), models)
        report['native'] = {kind: evidence.obligation(project, kind, layout=views['gds'], mixed_top=True)
                            for kind in KINDS}
    except (ll.Refusal, ValueError, OSError, KeyError, TypeError) as exc:
        report['refusals'].append(f'{getattr(exc, "rule", "INVALID_PV_INPUT")}: {exc}')
    write_json(destination, report)
    return report
