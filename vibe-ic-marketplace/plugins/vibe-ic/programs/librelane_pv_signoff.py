#!/usr/bin/env python3
"""Run native physical-verification chains and read their violation counts.

Each required tool must report a nonnegative integer count. Every violation
count retains the original clean limit of zero; absent results are NOT_MEASURED.
Magic and KLayout DRC remain independent required measurements.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _path_layout as _pl  # noqa: E402
from _atomic_artefact import write_json  # noqa: E402
from librelane_contract import (PDK_GUEST_ROOT, Refusal, _load, resolve_step_configs,  # noqa: E402
                                run_chain, state_from_direct)

NOT_MEASURED = 'NOT_MEASURED'

#: The metric keys each LibreLane step writes (LibreLane 3.1 steps: magic.py,
#: klayout.py, netgen.py; the plugin's signoff.py).  A key is credited to the
#: step that wrote it, never to a later step that carried it.
PRODUCED: dict[str, tuple[str, ...]] = {
    'Magic.DRC': ('magic__drc_error__count',),
    'KLayout.DRC': ('klayout__drc_error__count',),
    'KLayout.Density': ('klayout__density_error__count',),
    'Magic.SpiceExtraction': ('magic__illegal_overlap__count',),
    'KLayout.LVS': ('klayout__lvs_error__count',),
    'Netgen.LVS': ('design__lvs_error__count', 'design__lvs_unmatched_device__count',
                   'design__lvs_unmatched_net__count', 'design__lvs_unmatched_pin__count'),
    'KLayout.XOR': ('design__xor_difference__count',),
    'Vibeic.FinishingXOR': ('vibeic__finishing_xor__defect__count',
                            'vibeic__finishing_xor__removed__count',
                            'vibeic__finishing_xor__fill_on_design__count',
                            'vibeic__finishing_xor__added_in_core__count',
                            'vibeic__finishing_xor__added_touching__count'),
    'Vibeic.DatabaseUnit': ('vibeic__gds__database_unit_mismatch__count',),
}

#: Every produced count is a violation count: clean is exactly 0.
CLEAN = 0

DRC_CHAIN = ('Magic.DRC', 'KLayout.DRC', 'KLayout.Density')
DRC_ENGINES = (("KLayout.DRC", "klayout__drc_error__count", "drc.klayout.lyrdb"),
               ("Magic.DRC", "magic__drc_error__count", "drc.magic.lyrdb"))
LVS_CHAIN = ('Magic.SpiceExtraction', 'Netgen.LVS')
HALVES = {'drc': DRC_CHAIN, 'lvs': LVS_CHAIN}

#: Where each half's judgment is written (project-relative).
RECORD_REL = 'reports/phase3/librelane_pv_{half}.json'


def mode_for_half(project: Path, half: str, *, registry: dict | None = None) -> str:
    """Use full-GDS LibreLane, preserving registry-owned device extraction.

    The existing Step31 switch still selects DRC independently. For LVS,
    ``dual`` retains the additional direct diagnostic, while ``direct`` no
    longer authorizes a DEF/placeholder report as the canonical result. A
    complete native device route keeps its existing direct producer and
    current-evidence reader; it does not use the Magic/Netgen chain.
    """
    from librelane_contract import selected_mode
    mode = selected_mode(project, '31')
    if half != 'lvs' or mode != 'direct':
        return mode
    if registry is None:
        # Read-only consumers have the project's declared/run PDK rather
        # than the runner's resolved PdkConfig. Use the same registry facts.
        from tapeout_precheck import resolve_pdk
        name, _ = resolve_pdk(project)
        registry = next((row for row in _load(
            Path(__file__).with_name('pdk_registry.json')).get('pdks', [])
            if row.get('name') == name), {})
    if all(registry.get(key) for key in (
            'device_lvs_program', 'cdl_netlist', 'klayout_lvs_tech')):
        return 'direct'
    return 'librelane'


#: The flow's via-landing remediation record (`_stage_via_legalized_tech_lef`).
VIA_LEGALIZATION_REL = 'reports/pdk_via_patch_legalization.json'


def route_tech_lef(project: Path) -> tuple[Path, str] | None:
    """Resolve the derived technology LEF used by the route, when present."""
    path = project / VIA_LEGALIZATION_REL
    if not path.is_file():
        return None
    doc = _load(path)
    if doc.get('status') != 'APPLIED':
        return None
    derived = doc.get('derived_tech_lef')
    if not isinstance(derived, str) or not derived:
        raise Refusal('LL_ROUTE_TECH_LEF_MISSING', f'{path}: no derived_tech_lef')
    for candidate in (Path(derived), _pl.pnr_dir(project) / Path(derived).name):
        if candidate.is_file():
            return candidate.resolve(), f'{VIA_LEGALIZATION_REL}: derived_tech_lef'
    raise Refusal('LL_ROUTE_TECH_LEF_MISSING', f'{derived} is unavailable')


def tech_lef_overlay(project: Path) -> dict[str, tuple[Any, str]] | None:
    """``resolve_step_configs`` overlay: every corner reads the route's tech LEF."""
    found = route_tech_lef(project)
    return None if found is None else {'TECH_LEFS': ({'*': str(found[0])}, found[1])}


def _step_of(folder: Path) -> str | None:
    config = folder / 'config.json'
    if config.is_file():
        return _load(config).get('meta', {}).get('step')
    return None


def produced_metrics(folder: Path) -> dict[str, Any]:
    """Read the native metrics emitted by this step, including zero counts."""
    metrics = folder / 'metrics.json'
    if metrics.is_file():
        doc = _load(metrics)
        return doc.get('metrics', doc)
    state = folder / 'state_out.json'
    return (_load(state).get('metrics') or {}) if state.is_file() else {}


def judge_pv(folders: list[Path], required: tuple[str, ...], output: Path, *,
             scope: dict[str, str] | None = None) -> dict:
    """Judge a chain by THE ONE RULE (module docstring) and write the record.

    ``required`` names the LibreLane steps the chain must have run; each must
    have written every key in ``PRODUCED[step]``.  Verdict: FAIL when any
    produced count is nonzero or not an integer; else NOT_MEASURED when any
    required key is absent; else PASS.
    """
    by_step: dict[str, Path] = {}
    for folder in folders:
        step = _step_of(folder)
        if step:
            by_step[step] = folder
    rows: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    for step in required:
        folder = by_step.get(step)
        wrote = produced_metrics(folder) if folder else {}
        for key in PRODUCED.get(step, ()):
            row: dict[str, Any] = {'step': step, 'folder': str(folder) if folder else None}
            if folder is None:
                row['status'] = NOT_MEASURED
                row['reason'] = f'{step} did not run in this chain'
            elif key not in wrote:
                row['status'] = NOT_MEASURED
                out = folder / 'state_out.json'
                if not out.is_file():
                    row['reason'] = f'{step} left no state_out.json'
                else:
                    row['reason'] = f'{step} ran and did not write {key}'
            else:
                value = wrote[key]
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    row.update(status='INVALID', value=value)
                else:
                    row.update(status='MEASURED' if value == CLEAN else 'FAIL', value=value)
            rows[key] = row
    statuses = {row['status'] for row in rows.values()}
    verdict = ('FAIL' if statuses & {'FAIL', 'INVALID'} else
               NOT_MEASURED if (not rows or NOT_MEASURED in statuses) else 'PASS')
    drc = [rows.get(k) for k in ('magic__drc_error__count', 'klayout__drc_error__count')]
    if all(r and r.get('status') in ('MEASURED', 'FAIL') for r in drc) and \
            (drc[0]['value'] == CLEAN) != (drc[1]['value'] == CLEAN):
        reasons.append('LL_DRC_ENGINES_DISAGREE: magic={} klayout={}'.format(
            drc[0]['value'], drc[1]['value']))
    reasons += [f'{key}: {row["reason"]}' for key, row in rows.items()
                if row['status'] == NOT_MEASURED]
    reasons += [f'{key}={row["value"]} ({row["step"]})' for key, row in rows.items()
                if row['status'] in ('FAIL', 'INVALID')]
    record = {'verdict': verdict, 'required_steps': list(required), 'metrics': rows,
              'reasons': reasons, 'scope': scope or {}}
    write_json(output, record)
    return record


def bridge(project: Path, image: str, pdk_root: Path, pdk: str, configs: dict[str, Path],
           chain: tuple[str, ...], views: dict[str, Path], folder: str) -> Path:
    """One State for the chain from the shipped files (never a placeholder)."""
    missing = [f'{view}: {path}' for view, path in views.items() if not Path(path).is_file()]
    if missing:
        raise Refusal('LL_PV_VIEW_MISSING', '; '.join(missing))
    return state_from_direct(
        project, image, configs[chain[0]], dict(views),
        project / 'phase3/librelane' / folder / 'bridge',
        chain=[configs[step] for step in chain[1:]],
        mounts=[(pdk_root.resolve(), PDK_GUEST_ROOT)])


def run_half(project: Path, image: str, pdk_root: Path, pdk: str, half: str, *,
             gds: Path, routed_def: Path, netlist: Path, sdc: Path,
             powered_netlist: Path | None = None,
             physical_top: str | None = None,
             lane_prefix: str = '31', record: Path | None = None) -> dict:
    """Step 31, one half, on the shipped GDS and the routed DEF it came from.

    The halves run in separate lanes (``31-drc``, ``31-lvs``) so the runner's
    concurrent DRC and LVS dispatch never share a step folder.
    """
    if half not in HALVES:
        raise Refusal('LL_PV_HALF_UNKNOWN', half)
    chain = HALVES[half]
    options = dict(tech_lef_overlay(project) or {})
    if half == 'lvs':
        options.update({key: (value, 'Step31 verifies the actual final GDS')
                        for key, value in {'MAGIC_EXT_USE_GDS': True,
                                           'MAGIC_EXT_ABSTRACT': False}.items()})
    if physical_top:
        options['DESIGN_NAME'] = (physical_top, 'Current physical layout top')
    configs = resolve_step_configs(project, image, pdk, list(chain), pdk_root=pdk_root,
                                   folder=f'{lane_prefix}-{half}-config',
                                   overlay=options)
    views = {'def': routed_def, 'nl': netlist, 'sdc': sdc, 'gds': gds}
    if powered_netlist is not None:
        views['pnl'] = powered_netlist
    state = bridge(project, image, pdk_root, pdk, configs, chain,
                   views,
                   f'{lane_prefix}-{half}-config')
    folders = run_chain(project, image, [(step, configs[step], state) for step in chain],
                        mounts=[(pdk_root.resolve(), PDK_GUEST_ROOT)],
                        lane=f'{lane_prefix}-{half}', pdk_root=PDK_GUEST_ROOT)
    required = tuple(step for step in chain if step in PRODUCED)
    return judge_pv(folders, required,
                    record or project / RECORD_REL.format(half=half),
                    scope={'gds': str(gds), 'def': str(routed_def),
                           **({'magic_ext_use_gds': True} if half == 'lvs' else {})})


def run_mixed_top(project: Path, image: str, pdk_root: Path, pdk: str, half: str, *,
                  views: dict[str, Path], overlay: dict) -> dict:
    """Step31 on the merged mixed top, with its explicit powered/CDL pair.

    run_half derives powered logic from the digital DEF, which cannot describe
    the analog geometry M1 adds. This adapter supplies the declared paired
    views and extracts full devices from GDS. Independent engines continue
    after a refusal so an absent engine cannot erase a measured violation.
    All tools use the same native configurations and State handoffs.
    """
    chain = HALVES[half] + (('KLayout.LVS',) if half == 'lvs' else ())
    options = dict(tech_lef_overlay(project) or {})
    options.update(overlay)
    options.update({key: (value, 'M4 verifies the exact merged GDS, full devices')
                    for key, value in {'MAGIC_DRC_USE_GDS': True,
                                       'MAGIC_EXT_USE_GDS': True,
                                       'MAGIC_EXT_ABSTRACT': False}.items()})
    configs = resolve_step_configs(project, image, pdk, list(chain),
                                   pdk_root=pdk_root, folder=f'31-{half}-config',
                                   overlay=options)
    mounts = [(pdk_root.resolve(), PDK_GUEST_ROOT)]
    folders, errors = [], []
    extracted = None
    for step in chain:
        try:
            if step == 'Netgen.LVS':
                if extracted is None:
                    raise Refusal('LL_MIXED_TOP_EXTRACTION_MISSING', f"run_mixed_top.extracted is absent before {step}: requires the Magic.SpiceExtraction state_out.json handoff; Netgen.LVS not invoked")
                state = extracted
            else:
                state = state_from_direct(project, image, configs[step], views,
                                          project / 'phase3/librelane' /
                                          f'31-{half}-config' / f'bridge-{step}',
                                          mounts=mounts)
            made = run_chain(project, image, [(step, configs[step], state)],
                             mounts=mounts, lane=f'31-{half}', pdk_root=PDK_GUEST_ROOT)
            folders.extend(made)
            if step == 'Magic.SpiceExtraction':
                extracted = made[0] / 'state_out.json'
        except (Refusal, ValueError, OSError) as exc:
            errors.append(f'{step}: {exc}')
    scope = {'gds': str(views['gds']), 'def': str(views['def']),
             'magic_ext_use_gds': True}
    record = judge_pv(folders, chain, project / RECORD_REL.format(half=half), scope=scope)
    record['execution_refusals'] = errors
    write_json(project / RECORD_REL.format(half=half), record)
    return record


def run_finishing_xor(project: Path, image: str, pdk_root: Path, pdk: str, *,
                      pre: Path, sealed: Path | None, final: Path, core: list,
                      core_source: str, lane: str = '37.3-finishing',
                      record: Path | None = None) -> dict:
    """Step 37.3's finishing XOR on one lane's three streams."""
    if not (isinstance(core, (list, tuple)) and len(core) == 4):
        raise Refusal('LL_FINISHING_CORE_UNDECLARED', repr(core))
    overlay = {
        'VIBEIC_FINISHING_PRE_GDS': (str(pre.resolve()), 'the lane\'s StreamOut output'),
        'VIBEIC_FINISHING_CORE_AREA': (','.join(str(float(v)) for v in core), core_source),
    }
    if sealed is not None:
        overlay['VIBEIC_FINISHING_SEALED_GDS'] = (str(sealed.resolve()),
                                                  'the lane\'s KLayout.SealRing output')
    configs = resolve_step_configs(project, image, pdk, ['Vibeic.FinishingXOR'],
                                   pdk_root=pdk_root, folder=f'{lane}-config',
                                   overlay=overlay)
    state = state_from_direct(project, image, configs['Vibeic.FinishingXOR'],
                              {'gds': final},
                              project / 'phase3/librelane' / f'{lane}-config' / 'bridge')
    folders = run_chain(project, image, [('Vibeic.FinishingXOR',
                                          configs['Vibeic.FinishingXOR'], state)],
                        mounts=[(pdk_root.resolve(), PDK_GUEST_ROOT)], lane=lane, pdk_root=PDK_GUEST_ROOT)
    return judge_pv(folders, ('Vibeic.FinishingXOR',),
                    record or project / 'reports/phase3/librelane_finishing_xor.json',
                    scope={'pre': str(pre), 'final': str(final),
                           'sealed': str(sealed) if sealed else ''})


def run_database_unit(project: Path, image: str, pdk_root: Path, pdk: str, *,
                      gds: Path, declared_um: Any, declared_source: str,
                      lane: str = '37.5ic-dbu') -> dict:
    """Step 37.5ic's DatabaseUnit rung as a LibreLane custom step."""
    overlay = {}
    if isinstance(declared_um, (int, float)) and not isinstance(declared_um, bool):
        overlay['VIBEIC_DATABASE_UNIT_UM'] = (declared_um, declared_source)
    configs = resolve_step_configs(project, image, pdk, ['Vibeic.DatabaseUnit'],
                                   pdk_root=pdk_root, folder=f'{lane}-config',
                                   overlay=overlay or None)
    state = state_from_direct(project, image, configs['Vibeic.DatabaseUnit'], {'gds': gds},
                              project / 'phase3/librelane' / f'{lane}-config' / 'bridge')
    try:
        folders = run_chain(project, image, [('Vibeic.DatabaseUnit',
                                              configs['Vibeic.DatabaseUnit'], state)],
                            mounts=[(pdk_root.resolve(), PDK_GUEST_ROOT)], lane=lane, pdk_root=PDK_GUEST_ROOT)
    except Refusal as exc:
        # The step refuses an undeclared unit (NOT_MEASURED); its folder has
        # no state_out, and the judge says so rather than the refusal text.
        folders = sorted((project / 'phase3/librelane' / lane).glob('0*-vibeic-databaseunit'))
        if not folders:
            raise exc
    return judge_pv(folders, ('Vibeic.DatabaseUnit',),
                    project / 'reports/phase3/librelane_database_unit.json',
                    scope={'gds': str(gds)})


# ── step 37.4: the sign-off metrics record from LibreLane State ─────────────
#: The release-document keys a LibreLane chain measures, each with the flow
#: step whose switch selects that chain and the judged record that binds it.
#: With the step on ``librelane`` the key comes from that record and nowhere
#: else (one source of truth per metric); in ``dual`` and ``direct`` the direct
#: reports stay the record and the tool is a cross-check inside step 31.
STATE_KEYS: dict[str, tuple[str, str]] = {
    'magic__drc_error__count': ('31', RECORD_REL.format(half='drc')),
    'klayout__drc_error__count': ('31', RECORD_REL.format(half='drc')),
    'klayout__density_error__count': ('31', RECORD_REL.format(half='drc')),
    'design__lvs_error__count': ('31', RECORD_REL.format(half='lvs')),
    'design__lvs_unmatched_device__count': ('31', RECORD_REL.format(half='lvs')),
    'design__lvs_unmatched_net__count': ('31', RECORD_REL.format(half='lvs')),
    'design__lvs_unmatched_pin__count': ('31', RECORD_REL.format(half='lvs')),
}


def state_metric(project: Path, key: str, *, current: bool = False) -> dict[str, Any] | None:
    """The 37.4 row for ``key`` when its step runs on LibreLane, else None.

    None means "not this module's key in this run": the direct aggregator rule
    answers.  A switch that cannot be read is an answer (NOT_MEASURED), never a
    silent fall back to the direct reports.

    ``current=True`` reads the selected finished-layout native counts. The
    default reads the producer's ordinary State metrics.
    """
    from librelane_contract import selected_mode
    if current:
        import librelane_signoff_evidence as native
        if key == 'antenna__violation__count' and native.tool_selected(project, '26'):
            measured = native.obligation(project, 'antenna')
            # Net, pin and GDS-model counts are independent populations.
            # Their scalar union requires the root-owned producer API decision.
            return {'value': NOT_MEASURED,
                    'record': 'reports/phase3/antenna_librelane.json',
                    'reason': f"native antenna {measured['verdict']}: {measured['reason']}; "
                              'no accepted producer-owned total across the independent models'}
        final_drc = (any(key in keys for keys in native.COUNTS['drc'].values())
                     and native.tool_selected(project, '37'))
        density = (key == 'klayout__density_error__count'
                   and (native.tool_selected(project, '34') or native.tool_selected(project, '37')))
        if final_drc or density:
            measured = native.obligation(project, 'density' if density else 'drc')
            row = measured.get('rows', {}).get(key)
            if row is None:
                return {'value': NOT_MEASURED, 'reason': measured['reason']}
            return dict(row, source=str(_rel(project, Path(row['source'])))) if row.get('source') else row
    if key not in STATE_KEYS:
        return None
    step, rel = STATE_KEYS[key]
    try:
        mode = (mode_for_half(project, 'lvs') if rel == RECORD_REL.format(half='lvs')
                else selected_mode(project, step))
    except Refusal as exc:
        return {'value': NOT_MEASURED, 'reason': f'step {step}: {exc}'}
    if mode != 'librelane' and not (rel == RECORD_REL.format(half='lvs') and mode == 'dual'):
        return None
    if current:
        import librelane_signoff_evidence as native
        kind = 'lvs' if rel == RECORD_REL.format(half='lvs') else 'drc'
        measured = native.obligation(project, kind)
        row = (measured or {}).get('rows', {}).get(key)
        if row is None:
            return {'value': NOT_MEASURED, 'reason': (measured or {}).get(
                'reason', f'current producer missing for {key}')}
        return dict(row, source=str(_rel(project, Path(row['source'])))) if row.get('source') else row
    row = state_metrics(project, [project / rel]).get(key)
    if row is None:
        return {'value': NOT_MEASURED,
                'reason': f'step {step} runs on LibreLane and {rel} carries no '
                          f'judged {key} (absent record, or its chain never ran)'}
    return row

def state_metrics(project: Path, records: list[Path]) -> dict[str, dict[str, Any]]:
    """Read the actual native State counts referenced by each chain report."""
    rows: dict[str, dict[str, Any]] = {}
    for record_path in records:
        if not record_path.is_file():
            continue
        record = _load(record_path)
        for key, row in (record.get('metrics') or {}).items():
            from librelane_contract import project_path
            folder = project_path(project, row['folder']) if row.get('folder') else None
            out: dict[str, Any] = {'record': str(_rel(project, record_path))}
            value = produced_metrics(folder).get(key) if folder else None
            if type(value) is int and value >= 0:
                out.update(value=value, source=str(_rel(project, folder / 'state_out.json')))
            else:
                out.update(value=NOT_MEASURED,
                           reason=row.get('reason') or f'{key}: no native nonnegative count')
            rows[key] = out
    return rows


def _rel(project: Path, path: Path) -> Path:
    try:
        return path.resolve().relative_to(project.resolve())
    except ValueError:
        return path


def publish_report(folder: Path, name: str, destination: Path) -> dict:
    """Copy a native tool report to the public report path."""
    source = folder / name
    if not source.is_file():
        raise Refusal('LL_PV_REPORT_MISSING', str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return {'source': str(source), 'destination': str(destination)}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('record', nargs='+', type=Path,
                    help='judge_pv records to print as metrics rows')
    ap.add_argument('--project', type=Path, default=Path('.'))
    args = ap.parse_args(argv)
    print(json.dumps(state_metrics(args.project, args.record), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
