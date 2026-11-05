"""Read native physical-tool State metrics against their original zero limits."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import librelane_pv_signoff as pv
from librelane_contract import Refusal, selected_mode

NM = pv.NOT_MEASURED
PROMOTION = 'phase3/librelane/37-promotion.json'
COUNTS = {
    'drc': {'Magic.DRC': ('magic__drc_error__count',),
            'KLayout.DRC': ('klayout__drc_error__count',)},
    'lvs': {'Magic.SpiceExtraction': ('magic__illegal_overlap__count',),
            'Netgen.LVS': ('design__lvs_error__count',
                           'design__lvs_unmatched_device__count',
                           'design__lvs_unmatched_net__count',
                           'design__lvs_unmatched_pin__count'),
            'KLayout.LVS': ('klayout__lvs_error__count',)},
    'density': {'KLayout.Density': ('klayout__density_error__count',)},
    'antenna': {'OpenROAD.CheckAntennas': ('antenna__violating__nets', 'antenna__violating__pins'),
                'KLayout.Antenna': ('klayout__antenna_error__count',)},
}


def _read(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f'not an object: {path}')
    return value


def _require(ok: Any, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def _member(doc: dict, key: str) -> dict:
    value = doc.get(key)
    if value is None:
        return {}
    _require(isinstance(value, dict), f'LL_MALFORMED_OBJECT: {key}')
    return value


def _path(project: Path, value: Any) -> Path:
    _require(isinstance(value, str) and value, 'missing path')
    path = Path(value)
    return path if path.is_absolute() else project / path


def tool_selected(project: Path, step: str = '31', *, kind: str | None = None) -> bool:
    try:
        if step == '31' and kind == 'lvs':
            return pv.mode_for_half(project, 'lvs') in ('librelane', 'dual')
        return selected_mode(project, step) == 'librelane'
    except (Refusal, OSError, ValueError, TypeError):
        return True


def finished_layout(project: Path, layout: Path | None = None, *, mixed_top: bool = False) -> Path:
    project = project.resolve()
    if mixed_top:
        canonical = project / 'phase3/mixed_signal/top_merged.gds'
        _require(layout is not None and layout.resolve() == canonical
                 and canonical.is_file(), 'LL_MIXED_TOP_SUBJECT_MISSING')
        return canonical
    promotion = project / PROMOTION
    if tool_selected(project, '37') and promotion.is_file():
        canonical = _path(project, _read(promotion).get('canonical'))
        _require(canonical.is_file(), 'LL_FINISHED_MATERIAL_MISSING')
        paths = [canonical]
    else:
        paths = sorted(p for p in (project / 'phase3/stage4/gds').glob('*')
                       if p.is_file() and p.suffix.lower() in ('.gds', '.gds2', '.gdsii', '.oas'))
    _require(paths, 'LL_FINISHED_GDS_MISSING')
    _require(len({path.read_bytes() for path in paths}) == 1, 'LL_FINISHED_GDS_AMBIGUOUS')
    if layout is not None:
        _require(layout.is_file() and layout.read_bytes() == paths[0].read_bytes(),
                 'LL_PRECHECK_SELECTED_GDS_MISMATCH')
    return paths[0]


def _image(project: Path, switch: dict) -> str:
    import librelane_contract as lc
    return (lc.local_runtime(project) or switch.get('image')
            or os.environ.get('VIBEIC_LIBRELANE_IMAGE') or lc.resolve_image(project))


def _pdk_mounts(project: Path, switch: dict, folder: Path, image: str) -> list:
    """Resolve the real host PDK paths named in a native tool configuration."""
    from tapeout_precheck import resolve_pdk
    declared, _ = resolve_pdk(project)
    pdk = declared or switch.get('pdk')
    _require(pdk and (not switch.get('pdk') or switch['pdk'] == pdk), 'LL_PDK_DECLARATION_MISMATCH')
    path = folder / 'pdk_root.json'
    mapping = _read(path) if path.is_file() else {}
    mounts = mapping.get('requested_mounts') or mapping.get('mounts_under_it')
    if isinstance(mounts, list) and mounts:
        _require(all(isinstance(row, (list, tuple)) and len(row) == 2
                     and Path(row[0]).is_dir() for row in mounts), 'LL_PDK_MATERIAL_MISSING')
        return mounts
    root = switch.get('pdk_root_host') or os.environ.get('VIBEIC_LIBRELANE_PDK_ROOT') or os.environ.get('PDK_ROOT')
    if not root and getattr(image, 'pdk_root', None):
        root = image.pdk_root
    if not root:
        locator = project / 'phase3/librelane_pdk_root.provenance.json'
        root = _read(locator).get('path') if locator.is_file() else None
    _require(root and Path(root).is_dir(), 'LL_PDK_MATERIAL_MISSING')
    return [(str(root), '/pdk')]


def _step(folder: Path) -> str | None:
    config = folder / 'config.json'
    return _member(_read(config), 'meta').get('step') if config.is_file() else None


def count_row(project: Path, folder: Path, step: str, key: str,
              layout: Path, config_root: Path, *, subject_view: str = 'gds') -> dict:
    """Read the metric produced by this native tool step."""
    source = folder / 'state_out.json'
    out = {'value': NM, 'source': str(source), 'step': step, 'key': key}
    try:
        _require(_step(folder) == step, 'LL_METRIC_WRONG_PRODUCER')
        before = _read(folder / 'state_in.json')
        config = _read(folder / 'config.json')
        subject = _path(project, before.get(subject_view))
        _require(subject.is_file() and layout.is_file()
                 and subject.read_bytes() == layout.read_bytes(), 'LL_SELECTED_LAYOUT_MISMATCH')
        if step == 'Magic.SpiceExtraction':
            _require(config.get('MAGIC_EXT_USE_GDS') is True
                     and config.get('MAGIC_EXT_ABSTRACT') is False,
                     'LL_EXTRACTION_NOT_SHIPPED_GDS')
        state = _read(source)
        metrics = _member(state, 'metrics')
        native_metrics = folder / 'metrics.json'
        if native_metrics.is_file():
            produced = _read(native_metrics)
            metrics = produced.get('metrics', produced)
        value = metrics.get(key)
        _require(type(value) is int and value >= 0, 'LL_COUNT_NOT_TYPED_NONNEGATIVE')
        _require(any(key in kinds.get(step, ()) for kinds in COUNTS.values())
                 or key in pv.PRODUCED.get(step, ()), 'LL_METRIC_NOT_OWNED')
        out['value'] = value
    except (OSError, ValueError, TypeError, KeyError, Refusal) as exc:
        out['reason'] = str(exc)
    return out


def _verdict(rows: dict) -> str:
    values = [row['value'] for row in rows.values()]
    return ('FAIL' if any(type(v) is int and v > 0 for v in values) else
            NM if not values or any(v == NM for v in values) else 'PASS')


def _producer_folder(lane: Path, producer: str) -> Path | None:
    folders = [folder for folder in lane.iterdir() if folder.is_dir() and _step(folder) == producer]
    return folders[0] if len(folders) == 1 else None


def obligation(project: Path, kind: str, layout: Path | None = None, *, mixed_top: bool = False) -> dict | None:
    step = {'density': '34', 'antenna': '26'}.get(kind, '31')
    final_stream = not mixed_top and kind in ('drc', 'density') and tool_selected(project, '37')
    if not final_stream and not tool_selected(project, step, kind=kind):
        return None
    rows = {}
    try:
        chosen = layout.resolve() if kind == 'lvs' and layout is not None and not mixed_top else finished_layout(project, layout, mixed_top=mixed_top)
        if kind == 'antenna':
            path = project / 'reports/phase3/antenna_librelane.json'
            record = _read(path)
            for model_name, producer, view in (('gds', 'KLayout.Antenna', 'gds'), ('router', 'OpenROAD.CheckAntennas', 'def')):
                model = _member(record, model_name)
                for key in COUNTS['antenna'][producer]:
                    row = {'value': NM, 'reason': f'LL_REQUIRED_PRODUCER_MISSING: {producer}'}
                    if model.get('state'):
                        subject = chosen if view == 'gds' else _path(project, model.get('subject'))
                        state = _path(project, model['state'])
                        row = count_row(project, state.parent, producer, key, subject,
                                        project / 'phase3/librelane/26-config', subject_view=view)
                    rows[key] = dict(row, record=str(path))
            for flag in ('routing_incomplete', 'route_modified_after_last_verification'):
                value = record.get(flag)
                rows[f'route:{flag}'] = {'value': int(value) if type(value) is bool else NM,
                                       'reason': f'{flag}={value!r}', 'record': str(path)}
        elif kind == 'drc' and final_stream:
            arm = _read(project / PROMOTION)['selection']
            lane = project / f'phase3/librelane/37-{arm}-final-drc'
            for producer, keys in COUNTS['drc'].items():
                folder = _producer_folder(lane, producer)
                for key in keys:
                    rows[key] = count_row(project, folder, producer, key, chosen,
                        project / 'phase3/librelane/37-config') if folder else {
                            'value': NM, 'reason': f'LL_REQUIRED_PRODUCER_MISSING: {producer}'}
        elif kind == 'density':
            if final_stream:
                arm = _read(project / PROMOTION)['selection']
                path = project / f'phase3/librelane/37-{arm}-density.json'
                folder = _path(project, _read(path).get('source')).parent
                config_root = project / 'phase3/librelane/37-config'
            else:
                path = project / 'reports/phase3/fill_librelane.json'
                arms = _member(_read(path), 'gds')
                arm = _member(arms, arms.get('shipped'))
                folder = _path(project, arm.get('state')).parent
                config_root = project / 'phase3/librelane/34-config'
            rows['klayout__density_error__count'] = count_row(project, folder, 'KLayout.Density',
                'klayout__density_error__count', chosen, config_root)
        else:
            path = project / pv.RECORD_REL.format(half=kind)
            record = _read(path)
            required = {producer: keys for producer, keys in COUNTS[kind].items() if producer in pv.HALVES[kind]}
            for producer in pv.HALVES[kind]:
                if producer in pv.PRODUCED:
                    required.setdefault(producer, pv.PRODUCED[producer])
            for producer in record.get('required_steps') or []:
                if producer not in pv.PRODUCED and producer not in required:
                    rows[f'producer:{producer}'] = {'value': NM, 'reason': f'LL_UNSUPPORTED_DECLARED_PRODUCER: {producer}'}
                else:
                    required.setdefault(producer, pv.PRODUCED.get(producer, ()))
            for producer, keys in required.items():
                for key in keys:
                    declared = _member(_member(record, 'metrics'), key)
                    folder = _path(project, declared['folder']) if declared.get('folder') else _producer_folder(
                        project / f'phase3/librelane/31-{kind}', producer)
                    rows[key] = count_row(project, folder, producer, key, chosen,
                        project / f'phase3/librelane/31-{kind}-config') if folder else {
                            'value': NM, 'step': producer, 'key': key,
                            'reason': f'LL_REQUIRED_PRODUCER_MISSING: {producer}'}
        return {'verdict': _verdict(rows), 'rows': rows, 'gds': str(chosen),
                'reason': '; '.join(f'{key}: {row.get("reason") or row["value"]}' for key, row in rows.items())}
    except (OSError, ValueError, TypeError, KeyError, Refusal) as exc:
        return {'verdict': 'FAIL' if _verdict(rows) == 'FAIL' else NM, 'rows': rows, 'reason': str(exc)}
