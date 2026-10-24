#!/usr/bin/env python3
"""Default Step-34 tool fill and its existing Step-35 DFM consumer.

Step 34 in LibreLane's Chip-flow order
--------------------------------------
* ODB: `OpenROAD.FillInsertion` -- `filler_placement` over the PDK's own
  `DECAP_CELLS` then `FILL_CELLS`, and `write_views` re-applies the global
  connections, so every inserted cell's supply pins land on the supply nets
  (F24 / `pg_supply_pin_ownership_check` judges the DEF it wrote).  The cells
  it placed are recorded per master and per class (decap / fill) for the
  dynamic-IR decap (F20b).  A run that places nothing while the rows still
  have free sites is a NO-OP and refuses by name (#445).
* GDS, after the seal ring: `KLayout.Filler` (the PDK's own fill script) ->
  `KLayout.Density` (the PDK's density deck) -> `Checker.KLayoutDensity`.
  The density count is the step's measurement; the checker's refusal on a
  non-zero count is recorded beside it, never raised past it.

The direct arm (vibe-ic's three GDS fill passes) stays as the `dual` second
arm.  Both arms are measured by the SAME instrument (`KLayout.Density` with
the PDK deck), and `select_arms` picks the lower density-error count; a tie
keeps the direct arm, which the flow has always shipped.

Step 35
-------
`dfm_screen_check` stays an advisory vibe-ic gate.  Its CMP half reads the
density count recorded here (`tool_density`) instead of step 34's side files
whenever step 34 ran on the tool; its via half is cross-checked against the
router's own `route__vias__singlecut` / `route__vias__multicut`
(`via_agreement`).

chip-AGNOSTIC: every cell pattern, script, deck and die comes from the
PDK's LibreLane configuration as the installed tool resolved it, or from the
design's own files.
"""
from __future__ import annotations

import fnmatch
import json
import math
import re
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402
import _docker_memory as _dmem
from metal_fill_config_gen import (build_metal_fill_config,
                                   density_rule_layer_identifiers)
import die_level_deck_rule_attribution as _dla
import step_preflight as _spf
import librelane_contract as _lc
from librelane_contract import (PDK_GUEST_ROOT, PROBE_DEADLINE_S, Refusal, _load, digest,  # noqa: E402
                                DECLARATION_REL, declaration_config, resolve_step_configs,
                                run_chain, select_arms,
                                state_from_direct, run_container, config_file_hashes,
                                settled_floorplan_geometry, native_tool_command,
                                validate_step_receipt, _def_design_name, resolve_image)

ODB_FILL_STEP = 'OpenROAD.FillInsertion'
GDS_FILL_STEPS = ('KLayout.Filler', 'KLayout.Density', 'Checker.KLayoutDensity')
DENSITY_STEPS = ('KLayout.Density', 'Checker.KLayoutDensity')
DENSITY_METRIC = 'klayout__density_error__count'
#: The step-34 tool record (what dfm_screen_check reads for its CMP half).
RECORD_REL = 'reports/phase3/fill_librelane.json'
#: The cells step 34 placed, per master and class (F20b reads it).
CELLS_REL = 'reports/phase3/fill_cells_placed.json'
CONFIG_FOLDER = '34-config'
FILL_STREAM_STEP = 'Vibeic.FillAwareStreamOut'


def _mounts(pdk_root: Path, pdk: str) -> list:
    return [(pdk_root.resolve(), PDK_GUEST_ROOT)]


def _metrics(folder: Path) -> Dict[str, Any]:
    state = _load(folder / 'state_out.json')
    metrics = dict(state.get('metrics') or {})
    if (folder / 'metrics.json').is_file():
        metrics.update(_load(folder / 'metrics.json'))
    return metrics


def _count(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _finite_die_box(value: Any) -> Optional[tuple[float, float, float, float]]:
    """Normalize JSON numeric coordinates while refusing invalid geometry."""
    try:
        box = tuple(float(item) for item in value)
    except (TypeError, ValueError, OverflowError):
        return None
    if (len(box) != 4 or not all(math.isfinite(item) for item in box)
            or box[2] <= box[0] or box[3] <= box[1]):
        return None
    return box


def cell_patterns(config: Dict[str, Any]) -> Dict[str, List[str]]:
    """The decap and fill master patterns, exactly as `fill.tcl` strips them."""
    out = {}
    for cls, key in (('decap', 'DECAP_CELLS'), ('fill', 'FILL_CELLS')):
        raw = config.get(key) or []
        if isinstance(raw, str):
            raw = raw.split()
        out[cls] = [str(p).replace("'", '') for p in raw if str(p).strip()]
    return out


def _components(def_text: str) -> Dict[str, str]:
    """{instance: master} from a DEF COMPONENTS section."""
    match = re.search(r'^\s*COMPONENTS\s+\d+\s*;(.*?)^\s*END\s+COMPONENTS',
                      def_text, re.S | re.M)
    if not match:
        return {}
    return dict(re.findall(r'^\s*-\s+(\S+)\s+(\S+)', match.group(1), re.M))


def fill_census(before_def: str, after_def: str,
                patterns: Dict[str, List[str]]) -> Dict[str, Any]:
    """The instances `after_def` adds to `before_def`, per master and class.

    A class is the pattern family the master matches first (decap before fill,
    the order `fill.tcl` hands them to `filler_placement`).  An added instance
    that matches neither is counted as `other` and disclosed: fill insertion
    must add nothing else."""
    before = _components(before_def)
    after = _components(after_def)
    added = {inst: master for inst, master in after.items() if inst not in before}
    removed = sorted(inst for inst in before if inst not in after)
    per_master: Dict[str, int] = {}
    per_class: Dict[str, int] = {'decap': 0, 'fill': 0, 'other': 0}
    class_of: Dict[str, str] = {}
    for master in added.values():
        per_master[master] = per_master.get(master, 0) + 1
    for master, n in per_master.items():
        cls = next((c for c in ('decap', 'fill')
                    if any(fnmatch.fnmatchcase(master, p) for p in patterns.get(c, []))),
                   'other')
        class_of[master] = cls
        per_class[cls] += n
    return {'instances_before': len(before), 'instances_after': len(after),
            'added': len(added), 'removed': len(removed),
            'removed_examples': removed[:20],
            'per_master': dict(sorted(per_master.items())),
            'per_class': per_class, 'class_of_master': dict(sorted(class_of.items()))}


def chain_folder(project: Path, lane: str, steps, step: str) -> Path:
    """The run_chain folder of ``step`` inside ``lane``."""
    index = list(steps).index(step) + 1
    return project / 'phase3/librelane' / lane / f'{index:02d}-{step.lower().replace(".", "-")}'


def run_density(project: Path, image: str, pdk_root: Path, pdk: str, *,
                gds: Path, lane: str, configs: Optional[Dict[str, Path]] = None,
                steps=DENSITY_STEPS, placement: Optional[dict] = None,
                bridge_root: Optional[Path] = None) -> Dict[str, Any]:
    """The PDK density deck on ``gds`` (`KLayout.Density`), then the tool's own
    checker.  The count is the measurement; a checker refusal (count > 0) is
    recorded beside it, never raised past it.  ``steps`` may lead with
    `KLayout.Filler` (the tool arm fills first). Candidate callers supply
    ``placement`` and ``bridge_root``; the latter also selects run_chain's
    existing nested namespace instead of its flat lane grammar.
    """
    if not Path(gds).is_file():
        raise Refusal('LL_GDS_MISSING', f'no stream file at {Path(gds)}')
    configs = configs or resolve_step_configs(project, image, pdk, list(steps),
                                              pdk_root=pdk_root, folder=CONFIG_FOLDER)
    density_cfg = _load(configs['KLayout.Density'])
    if not density_cfg.get('KLAYOUT_DENSITY_RUNSET'):
        # The step would warn and skip: a skipped deck is not a clean die.
        raise Refusal('LL_DENSITY_RUNSET_UNDECLARED', f'{pdk}: KLAYOUT_DENSITY_RUNSET')
    if 'KLayout.Filler' in steps and not _load(configs['KLayout.Filler']).get('KLAYOUT_FILLER_SCRIPT'):
        raise Refusal('LL_FILLER_SCRIPT_UNDECLARED', f'{pdk}: KLAYOUT_FILLER_SCRIPT')
    mounts = _mounts(pdk_root, pdk)
    first = list(steps)[0]
    state = state_from_direct(project, image, configs[first], {'gds': gds},
                              (bridge_root / Path(lane).name if bridge_root else
                               project / 'phase3/librelane' / CONFIG_FOLDER / f'bridge-{lane}'),
                              chain=[configs[s] for s in list(steps)[1:]], mounts=mounts)
    checker_error = None
    try:
        run_chain(project, image, [(s, configs[s], state) for s in steps],
                  mounts=mounts, pdk_root=PDK_GUEST_ROOT,
                  **({'namespace': lane} if bridge_root is not None else {'lane': lane}))
    except Refusal as error:
        if not str(error).startswith('LL_STEP_FAILED: Checker.KLayoutDensity'):
            raise
        checker_error = str(error)
    folder = chain_folder(project, lane, steps, 'KLayout.Density')
    count = _count(_metrics(folder).get(DENSITY_METRIC))
    if count is None:
        raise Refusal('LL_DENSITY_NOT_MEASURED', f'{folder}: {DENSITY_METRIC}')
    report = folder / 'reports' / 'density.klayout.json'
    out = {'step': 'KLayout.Density', 'runset': density_cfg.get('KLAYOUT_DENSITY_RUNSET'),
           'options': density_cfg.get('KLAYOUT_DENSITY_OPTIONS'),
           'state': str(folder / 'state_out.json'),
           'state_sha256': digest(folder / 'state_out.json'),
           'subject': str(gds), 'subject_sha256': digest(Path(gds)),
           DENSITY_METRIC: count, 'checker_error': checker_error,
           'report': str(report) if report.is_file() else None,
           'rules': density_rules(report) if report.is_file() else None}
    if 'KLayout.Filler' in steps:
        filler = chain_folder(project, lane, steps, 'KLayout.Filler')
        filled = _load(filler / 'state_out.json').get('gds')
        if not filled or not Path(filled).is_file() or Path(filled).resolve() == Path(gds).resolve():
            raise Refusal('LL_FILLER_NO_OUTPUT', f'{filler}: state gds {filled!r}')
        if Path(str(_load(folder / 'state_out.json').get('gds'))).resolve() != Path(filled).resolve():
            raise Refusal('LL_DENSITY_SUBJECT_DRIFT', f'{folder} did not measure {filled}')
        cfg = _load(configs['KLayout.Filler'])
        out['filler'] = {'step': 'KLayout.Filler', 'script': cfg.get('KLAYOUT_FILLER_SCRIPT'),
                         'options': cfg.get('KLAYOUT_FILLER_OPTIONS'),
                         'state': str(filler / 'state_out.json'),
                         'state_sha256': digest(filler / 'state_out.json'),
                         'gds_in': str(gds), 'gds_in_sha256': digest(Path(gds)),
                         'filled_gds': str(filled), 'filled_sha256': digest(Path(filled))}
        out['subject'], out['subject_sha256'] = str(filled), digest(Path(filled))
        if count:
            topup = top_up_density(project, image, pdk_root, pdk, Path(filled),
                                   configs['KLayout.Density'], f'{lane}-topup',
                                   **({'placement': placement} if placement is not None else {}))
            again = run_density(project, image, pdk_root, pdk,
                                gds=Path(topup['gds']), lane=f'{lane}-topped',
                                configs=configs, steps=DENSITY_STEPS,
                                placement=placement, bridge_root=bridge_root)
            again['filler'] = out['filler']
            again['density_topup'] = topup
            again['pdk_density_before_topup'] = count
            return again
    out['ratios'] = measure_density_ratios(
        project, image, pdk_root, pdk, Path(out['subject']),
        configs['KLayout.Density'], f'{lane}-ratios')
    return out


def finish_candidate_gds(project: Path, image: str, pdk_root: Path, pdk: str, *,
                         gds: Path, state: Path, config: Path, lane: str) -> dict:
    """Finish one retained candidate without publishing any adopted views.

    ``state``/``config`` are the candidate repair producer's native packet,
    not its later RCX/STA State. All new files stay under a fresh ``lane``.
    A nonzero full PDK density count blocks the caller. The returned GDS must
    still undergo full DRC/LVS; this is not final electrical qualification.
    """
    project, gds, state, config = (Path(p).resolve() for p in (project, gds, state, config))
    lanes = project / 'phase3/librelane'
    root = (lanes / lane).resolve()
    if (not lane or Path(lane).is_absolute() or '..' in Path(lane).parts
            or not root.is_relative_to(lanes) or root == lanes
            or root.exists() or not state.is_relative_to(lanes)
            or state.name != 'state_out.json' or gds.is_relative_to(root)):
        raise Refusal('LL_CANDIDATE_FINISHING_LOCATION', lane)
    cfg = _load(config)
    step = cfg.get('meta', {}).get('step')
    if not step or not cfg.get('DESIGN_NAME'):
        raise Refusal('LL_CANDIDATE_FINISHING_CONFIG', str(config))
    receipt = validate_step_receipt(state.parent, step)
    if (receipt['input'].get('image') != image
            or receipt['input'].get('config') != digest(config)
            or receipt['input'].get('config_files') != config_file_hashes(cfg, _mounts(pdk_root, pdk))):
        raise Refusal('LL_CANDIDATE_FINISHING_CONFIG', str(config))
    current = _load(state)
    placement = {'config': cfg}
    for view in ('def', 'odb'):
        path = Path(current.get(view) or '').resolve()
        if (not path.is_relative_to(state.parent) or not path.is_file()
                or receipt['sha256'].get(str(path.relative_to(state.parent))) != digest(path)):
            raise Refusal('LL_CANDIDATE_FINISHING_VIEW', view)
        placement[view] = path
    if not gds.is_file():
        raise Refusal('LL_GDS_MISSING', str(gds))
    from librelane_contract import _def_die_area
    die = _def_die_area(placement['def'])
    if not die:
        raise Refusal('LL_CANDIDATE_FINISHING_CONFIG', 'candidate DEF die area absent')
    if _def_design_name(placement['def']) != cfg['DESIGN_NAME']:
        raise Refusal('LL_CANDIDATE_FINISHING_CONFIG', 'candidate DEF design differs')
    inputs = {str(p): digest(p) for p in (gds, state, config,
              state.parent / 'vibeic_receipt.json', placement['def'], placement['odb'])}
    root.mkdir(parents=True, exist_ok=False)
    overlay = {key: (cfg[key], f'candidate native config {config}')
               for key in ('DESIGN_NAME', 'TECH_LEFS') if key in cfg}
    overlay['DIE_AREA'] = (die, f'candidate DEF {placement["def"]}')
    configs = resolve_step_configs(project, image, pdk, list(GDS_FILL_STEPS),
        pdk_root=pdk_root, folder=f'{lane}/config', overlay=overlay)
    density = run_density(project, image, pdk_root, pdk, gds=gds,
        lane=f'{lane}/density', configs=configs, steps=GDS_FILL_STEPS,
        placement=placement, bridge_root=root / 'bridges')
    if density.get(DENSITY_METRIC) != 0 or density.get('checker_error'):
        raise Refusal('LL_CANDIDATE_FINISHING_DENSITY_FAILED', str(density))
    finished = Path(density['subject']).resolve()
    if (not finished.is_relative_to(root) or not finished.is_file()
            or digest(finished) != density['subject_sha256']):
        raise Refusal('LL_CANDIDATE_FINISHING_GDS_UNBOUND', str(finished))
    native = {}
    final_lane = str(Path(density['state']).parent.parent.relative_to(lanes))
    final_steps = DENSITY_STEPS if 'density_topup' in density else GDS_FILL_STEPS
    folders = [(Path(density['filler']['state']).parent, 'KLayout.Filler'),
               (Path(density['state']).parent, 'KLayout.Density'),
               (chain_folder(project, final_lane, final_steps, 'Checker.KLayoutDensity'),
                'Checker.KLayoutDensity')]
    for folder, producer in folders:
        if not folder.resolve().is_relative_to(root):
            raise Refusal('LL_CANDIDATE_FINISHING_GDS_UNBOUND', str(folder))
        validate_step_receipt(folder, producer)
        path = folder / 'vibeic_receipt.json'
        native[producer] = {'path': str(path), 'sha256': digest(path)}
    if any(not Path(p).is_file() or digest(Path(p)) != sha for p, sha in inputs.items()):
        raise Refusal('LL_CANDIDATE_FINISHING_INPUT_CHANGED', str(state))
    return {'gds': str(finished), 'gds_sha256': digest(finished),
            'density': density, 'inputs': inputs, 'native_receipts': native,
            'configs': {step: {'path': str(path), 'sha256': digest(path)}
                        for step, path in configs.items()},
            'scope': 'candidate-local finishing; full DRC/LVS still required; '
                     'prefill PPA only, fill-aware final electrical unproven'}


def resume_candidate_gds(project: Path, image: str, pdk_root: Path, pdk: str, *,
                         gds: Path, state: Path, config: Path, lane: str,
                         ratio_lane: str) -> dict:
    """Resume only the ratio consumer of a retained candidate finish.

    The finished GDS is derived from ``lane``, never supplied by the caller.
    All retained native fill/density receipts, configs, bridge subjects and
    placement-derived top-up provenance are validated before a new ratio
    consumer is started. Full DRC/LVS remain mandatory for the caller.
    """
    project, gds, state, config = (Path(p).resolve()
                                   for p in (project, gds, state, config))
    lanes = project / 'phase3/librelane'
    root = (lanes / lane).resolve()
    ratio_root = (lanes / ratio_lane).resolve()
    if (not lane or not ratio_lane or Path(lane).is_absolute()
            or Path(ratio_lane).is_absolute() or '..' in Path(lane).parts
            or '..' in Path(ratio_lane).parts or not root.is_relative_to(lanes)
            or not ratio_root.is_relative_to(lanes) or root == lanes
            or ratio_root == lanes or not root.is_dir() or ratio_root.exists()
            or not state.is_relative_to(lanes) or state.name != 'state_out.json'):
        raise Refusal('LL_CANDIDATE_FINISHING_LOCATION', f'{lane}: {ratio_lane}')

    cfg = _load(config)
    step = cfg.get('meta', {}).get('step')
    receipt = validate_step_receipt(state.parent, step) if step else None
    if (not receipt or not cfg.get('DESIGN_NAME')
            or receipt['input'].get('image') != image
            or receipt['input'].get('config') != digest(config)
            or receipt['input'].get('config_files') !=
               config_file_hashes(cfg, _mounts(pdk_root, pdk))):
        raise Refusal('LL_CANDIDATE_FINISHING_CONFIG', str(config))
    current = _load(state)
    placement = {'config': cfg}
    for view in ('def', 'odb'):
        path = Path(current.get(view) or '').resolve()
        if (not path.is_relative_to(state.parent) or not path.is_file()
                or receipt['sha256'].get(str(path.relative_to(state.parent))) != digest(path)):
            raise Refusal('LL_CANDIDATE_FINISHING_VIEW', view)
        placement[view] = path
    if not gds.is_file():
        raise Refusal('LL_GDS_MISSING', str(gds))

    from librelane_contract import _def_die_area
    die = _def_die_area(placement['def'])
    if not die or _def_design_name(placement['def']) != cfg['DESIGN_NAME']:
        raise Refusal('LL_CANDIDATE_FINISHING_CONFIG', 'candidate DEF identity differs')
    inputs = {str(p): digest(p) for p in (gds, state, config,
              state.parent / 'vibeic_receipt.json', placement['def'], placement['odb'])}

    configs = {name: root / 'config' / f'{name}.json' for name in GDS_FILL_STEPS}
    density_cfg = _load(configs['KLayout.Density'])
    if (density_cfg.get('DESIGN_NAME') != cfg['DESIGN_NAME']
            or _finite_die_box(density_cfg.get('DIE_AREA')) != _finite_die_box(die)
            or _finite_die_box(die) is None):
        raise Refusal('LL_CANDIDATE_FINISHING_CONFIG', str(configs['KLayout.Density']))

    def checked(folder: Path, producer: str) -> tuple[dict, dict]:
        native_receipt = validate_step_receipt(folder, producer)
        expected_cfg = configs[producer]
        if (native_receipt['input'].get('image') != image
                or native_receipt['input'].get('config') != digest(expected_cfg)
                or native_receipt['input'].get('config_files') !=
                   config_file_hashes(_load(expected_cfg), _mounts(pdk_root, pdk))):
            raise Refusal('LL_CANDIDATE_FINISHING_CONFIG', str(expected_cfg))
        return _load(folder / 'state_out.json'), native_receipt

    filler_dir = root / 'density/01-klayout-filler'
    density_dir = root / 'density/02-klayout-density'
    topped_density_dir = root / 'density-topped/01-klayout-density'
    topped_checker_dir = root / 'density-topped/02-checker-klayoutdensity'
    filler_state, filler_receipt = checked(filler_dir, 'KLayout.Filler')
    density_state, density_receipt = checked(density_dir, 'KLayout.Density')
    topped_state, topped_density_receipt = checked(
        topped_density_dir, 'KLayout.Density')
    _topped_checker_state, topped_checker_receipt = checked(
        topped_checker_dir, 'Checker.KLayoutDensity')

    filled = Path(filler_state.get('gds') or '').resolve()
    topped = Path(topped_state.get('gds') or '').resolve()
    before_count = _count((density_state.get('metrics') or {}).get(DENSITY_METRIC))
    after_count = _count((topped_state.get('metrics') or {}).get(DENSITY_METRIC))
    if (not filled.is_relative_to(root) or not filled.is_file()
            or not topped.is_relative_to(root) or not topped.is_file()
            or Path(_load(filler_dir / 'state_in.json').get('gds') or '').resolve() != gds
            or Path(density_state.get('gds') or '').resolve() != filled
            or Path(_load(topped_density_dir / 'state_in.json').get('gds') or '').resolve() != topped
            or before_count in (None, 0) or after_count != 0):
        raise Refusal('LL_CANDIDATE_FINISHING_GDS_UNBOUND', str(root))

    def bridge(name: str, producer: str, subject: Path, config_path: Path) -> None:
        doc = _load(root / 'bridges' / name / 'bridge_receipt.json')
        view = (doc.get('views') or {}).get('gds') or {}
        if (doc.get('step') != producer or doc.get('image') != image
                or doc.get('config_sha256') != digest(config_path)
                or Path(view.get('source') or '').resolve() != subject
                or view.get('sha256') != digest(subject)):
            raise Refusal('LL_CANDIDATE_FINISHING_GDS_UNBOUND', f'bridge {name}')
    bridge('density', 'KLayout.Filler', gds, configs['KLayout.Filler'])
    bridge('density-topped', 'KLayout.Density', topped,
           configs['KLayout.Density'])

    topup_dir = root / 'density-topup'
    topup_report = _load(topup_dir / 'fill_report.json')
    topup_config = _load(topup_dir / 'pdk_fill_config.json')
    derivation = topup_config.get('_derivation') or {}
    keepout = derivation.get('placed_instance_keepout') or {}
    if (topup_report.get('verdict') != 'PASS' or not topup_report.get('layers')
            or not (topup_report.get('keepout') or {}).get('declared')
            or Path(topup_report.get('gds_in') or '').resolve() != filled
            or Path(topup_report.get('gds_out') or '').resolve() != topped
            or Path(keepout.get('source') or '').resolve() != placement['odb']
            or keepout.get('source_sha256') != digest(placement['odb'])
            or digest(filled) == digest(topped)):
        raise Refusal('LL_CANDIDATE_FINISHING_TOPUP_UNBOUND', str(topup_dir))

    ratios = measure_density_ratios(project, image, pdk_root, pdk, topped,
                                    configs['KLayout.Density'], ratio_lane)
    if any(not Path(path).is_file() or digest(Path(path)) != sha
           for path, sha in inputs.items()):
        raise Refusal('LL_CANDIDATE_FINISHING_INPUT_CHANGED', str(state))
    native_rows = {
        'KLayout.Filler': (filler_dir, filler_receipt),
        'KLayout.Density.before_topup': (density_dir, density_receipt),
        'KLayout.Density': (topped_density_dir, topped_density_receipt),
        'Checker.KLayoutDensity': (topped_checker_dir, topped_checker_receipt),
    }
    native = {name: {'path': str(folder / 'vibeic_receipt.json'),
                     'sha256': digest(folder / 'vibeic_receipt.json')}
              for name, (folder, _receipt) in native_rows.items()}
    density_report = topped_density_dir / 'reports/density.klayout.json'
    density = {
        'step': 'KLayout.Density', 'state': str(topped_density_dir / 'state_out.json'),
        'state_sha256': digest(topped_density_dir / 'state_out.json'),
        'subject': str(topped), 'subject_sha256': digest(topped),
        DENSITY_METRIC: 0, 'checker_error': None,
        'report': str(density_report) if density_report.is_file() else None,
        'rules': density_rules(density_report) if density_report.is_file() else None,
        'pdk_density_before_topup': before_count,
        'density_topup': {'gds': str(topped), 'gds_sha256': digest(topped),
                          'input_sha256': digest(filled),
                          'report': str(topup_dir / 'fill_report.json'),
                          'report_sha256': digest(topup_dir / 'fill_report.json'),
                          'config': str(topup_dir / 'pdk_fill_config.json'),
                          'config_sha256': digest(topup_dir / 'pdk_fill_config.json'),
                          'layers': topup_report['layers']},
        'ratios': ratios,
    }
    return {'gds': str(topped), 'gds_sha256': digest(topped),
            'density': density, 'inputs': inputs, 'native_receipts': native,
            'configs': {name: {'path': str(path), 'sha256': digest(path)}
                        for name, path in configs.items()},
            'reuse': {'lane': lane, 'ratio_lane': ratio_lane,
                      'scope': 'validated filler/top-up/density receipts; ratio replay only'},
            'scope': 'candidate-local finishing; full DRC/LVS still required; '
                     'prefill PPA only, fill-aware final electrical unproven'}


def density_rules(report: Path) -> Optional[Dict[str, int]]:
    """{rule: violation count} from the deck's `density.klayout.json`."""
    try:
        doc = json.loads(report.read_text())
    except (OSError, ValueError):
        return None
    if isinstance(doc, dict):
        rows = doc.get('violations', doc)
        if isinstance(rows, dict):
            return {str(k): v for k, v in rows.items() if _count(v) is not None}
        if isinstance(rows, list):
            out: Dict[str, int] = {}
            for row in rows:
                if isinstance(row, dict):
                    name = str(row.get('rule') or row.get('category') or row.get('name') or '?')
                    out[name] = out.get(name, 0) + (_count(row.get('count')) or 1)
            return out
    return None


def _host_pdk_path(value: str, pdk_root: Path, pdk: str) -> Path:
    """Translate a resolved LibreLane /pdk path to its mounted host source."""
    path = Path(value)
    prefix = Path('/pdk') / pdk
    if path == prefix or prefix in path.parents:
        return pdk_root / pdk / path.relative_to(prefix)
    return path


def _density_source(pdk_root: Path, pdk: str,
                    density_config: Path) -> tuple[dict, str, str, str]:
    cfg = _load(density_config)
    layer_map = cfg.get('KLAYOUT_DEF_LAYER_MAP')
    tech_lefs = cfg.get('TECH_LEFS') or {}
    deck = cfg.get('KLAYOUT_DENSITY_RUNSET')
    if not (layer_map and tech_lefs and deck):
        raise Refusal('LL_DENSITY_FILL_PDK_INPUT_MISSING', str(density_config))
    map_path = _host_pdk_path(str(layer_map), pdk_root, pdk)
    lef_paths = [_host_pdk_path(str(p), pdk_root, pdk)
                 for p in tech_lefs.values()]
    deck_path = _host_pdk_path(str(deck), pdk_root, pdk)
    try:
        map_text = map_path.read_text()
        lef_text = '\n'.join(p.read_text() for p in lef_paths)
        # The master deck loads rule_decks/*.rb and generic_layers.rb.  Include
        # these declarations so the fill engine sees the same dummy datatypes,
        # spacing, density floor and exclusion markers as the foundry checker.
        deck_files = [deck_path, *sorted(deck_path.parent.rglob('*.rb'))]
        deck_text = '\n'.join(p.read_text() for p in deck_files)
    except OSError as exc:
        raise Refusal('LL_DENSITY_FILL_PDK_UNREADABLE', str(exc)) from exc
    return cfg, map_text, lef_text, deck_text


def _density_ratio_specs(deck_text: str, fill_cfg: dict) -> dict:
    """Resolve die-density identifiers to the PDK's drawn+dummy GDS pairs.

    Unknown aliases remain absent and are reported as NOT_MEASURED.  The
    foundry deck is still the only authority for the rule verdict.
    """
    # Ruby comments and quoted diagnostic messages are prose.  Read only the
    # deck's executable grammar; the rule-id parser uses the same filter.
    code = _dla.deck_code_only(deck_text)
    layers = {row['name']: row for row in fill_cfg['layers']}
    extracted = {name: [int(number), int(datatype)]
                 for name, number, datatype in re.findall(
                     r'extract_single_layer_from_design\.call\(:([A-Za-z]\w*),\s*(\d+),\s*(\d+)\)',
                     code)}
    unions = {name: (left, right) for name, left, right in re.findall(
        r'name:\s*:([A-Za-z]\w*),\s*calc:\s*->\(ctx\)\s*\{\s*ctx\[:([A-Za-z]\w*)\]\s*\+\s*ctx\[:([A-Za-z]\w*)\]',
        code)}
    top_aliases = {int(level): name for level, name in re.findall(
        r'(\d+)\s*=>\s*\{[^\n]*top_metal:\s*:([A-Za-z]\w*)', code)}
    highest = max((int(re.search(r'\d+$', name).group()) for name in layers
                   if re.search(r'\d+$', name)), default=None)
    out = {}
    for rule, identifiers in density_rule_layer_identifiers(deck_text).items():
        pairs = None
        for symbol in identifiers:
            resolved = symbol
            if symbol == 'top_metal' and highest in top_aliases:
                resolved = top_aliases[highest]
            if resolved in layers:
                row = layers[resolved]
                pairs = [row['layer'],
                         [row['layer'][0], row.get('fill_datatype', row['layer'][1])]]
            elif resolved in extracted:
                pairs = [extracted[resolved]]
            elif resolved in unions:
                pair_names = unions[resolved]
                if all(name in extracted for name in pair_names):
                    pairs = [extracted[name] for name in pair_names]
            if pairs:
                break
        out[rule] = {'status': 'MEASURED' if pairs else 'NOT_MEASURED',
                     'identifier': symbol if pairs else identifiers,
                     'layers': pairs}
    return out


def _core_edge_keepout(die: list, core: list) -> float:
    """Inset a whole-die fill region until it lies entirely inside the core."""
    if not (len(die) == len(core) == 4):
        raise Refusal('LL_DENSITY_FILL_CORE_UNDECLARED', repr(core))
    dx1, dy1, dx2, dy2 = map(float, die)
    cx1, cy1, cx2, cy2 = map(float, core)
    gaps = (cx1 - dx1, cy1 - dy1, dx2 - cx2, dy2 - cy2)
    if min(gaps) < 0 or not (dx1 < dx2 and dy1 < dy2 and cx1 < cx2 and cy1 < cy2):
        raise Refusal('LL_DENSITY_FILL_CORE_OUTSIDE_DIE', f'{core} vs {die}')
    return max(gaps)


def _run_logged(cmd: list, log: Path):
    """`run_container` writes `log` only when it salvages a stalled job; a
    refusal that names `log` must find the tool's own words there, so keep
    what it printed on every exit."""
    result = run_container(cmd, supervised=True, log=log)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f'{result.stdout or ""}\n{result.stderr or ""}')
    return result


def _placed_keepout_boxes(project: Path, image: str, pdk_root: Path, pdk: str,
                          cfg: dict, folder: Path, *, placement: Optional[dict] = None) -> dict:
    """Read every placed PAD/BLOCK footprint from OpenDB, never DEF text.

    Explicit candidate placement reads its own ODB and native core area.
    The routed DEF and all physical LEFs are required even when the resulting
    protected-instance set is empty.  An unreadable source must not turn into
    an empty mask and permit GDS promotion.
    """
    routed = (Path(placement['def']) if placement is not None else
              project / 'phase3/stage3/pnr/routed.def')
    odb = Path(placement['odb']) if placement is not None else None
    if odb is not None:
        cfg = placement['config']
        if not odb.is_file() or not odb.stat().st_size:
            raise Refusal('LL_DENSITY_FILL_PLACEMENT_UNREADABLE', str(odb))
    if not routed.is_file() or not routed.stat().st_size:
        raise Refusal('LL_DENSITY_FILL_PLACEMENT_UNREADABLE', str(routed))
    tech = cfg.get('TECH_LEFS') or {}
    tech_lef = (tech.get('nom_*') or next(iter(tech.values()), None)
                if isinstance(tech, dict) else next(iter(tech), None))
    lefs = [tech_lef] if tech_lef else []

    def lef_paths(value, *, strict=True):
        if isinstance(value, (str, Path)):
            yield str(value)
        elif isinstance(value, dict):
            for nested in value.values():
                yield from lef_paths(nested, strict=strict)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                yield from lef_paths(nested, strict=strict)
        elif value is not None and strict:
            raise Refusal('LL_DENSITY_FILL_PLACEMENT_UNREADABLE',
                          f'invalid physical LEF path: {value!r}')

    # A master is protected by its LEF CLASS (PAD / BLOCK) or, whatever its
    # class says, by the view that declared it: every master a PAD_LEFS file
    # defines is a pad-ring member (corner ENDCAPs, a classless pad) and every
    # master of a macro view is a macro (RING, COVER, no CLASS).
    ring_role: Dict[str, str] = {}
    for key in ('CELL_LEFS', 'PAD_LEFS', 'MACRO_LEFS', 'EXTRA_LEFS'):
        paths = list(lef_paths(cfg.get(key) or []))
        lefs.extend(paths)
        if key in ('PAD_LEFS', 'MACRO_LEFS'):
            for path in paths:
                ring_role.setdefault(str(path),
                                     'PAD' if key == 'PAD_LEFS' else 'BLOCK')
    for path in lef_paths(cfg.get('MACROS') or {}, strict=False):
        if path.lower().endswith(('.lef', '.lef.gz')):
            lefs.append(path)
            ring_role.setdefault(str(path), 'BLOCK')
    if not lefs:
        raise Refusal('LL_DENSITY_FILL_PLACEMENT_UNREADABLE',
                      f'{routed}: no physical LEF views')
    guest_lefs = []
    guest_roles: Dict[str, str] = {}
    extra_mounts = []
    pdk_dir = (pdk_root / pdk).resolve()
    project_dir = project.resolve()
    local = _lc._provider_for_image(image) is not None or _lc._provider_route(project)
    for value in dict.fromkeys(str(x) for x in lefs):
        host = _host_pdk_path(value, pdk_root, pdk)
        if not host.is_absolute():
            host = project / host
        if not host.is_file():
            raise Refusal('LL_DENSITY_FILL_PLACEMENT_UNREADABLE',
                          f'physical LEF unreadable: {host}')
        host = host.resolve()
        guest = (str(Path('/pdk') / pdk / host.relative_to(pdk_dir))
                 if not local and host.is_relative_to(pdk_dir) else str(host))
        guest_lefs.append(guest)
        if value in ring_role:
            guest_roles[guest] = ring_role[value]
        if not (host.is_relative_to(project_dir) or host.is_relative_to(pdk_dir)):
            extra_mounts.extend(['-v', f'{host}:{guest}:ro'])

    def word(value: Path | str) -> str:
        return '{' + str(value).replace('\\', '\\\\').replace('}', '\\}') + '}'

    folder.mkdir(parents=True, exist_ok=True)
    output = folder / 'placed_keepouts.txt'
    partial = folder / 'placed_keepouts.part'
    output.unlink(missing_ok=True)
    partial.unlink(missing_ok=True)
    script = folder / 'placed_keepouts.tcl'
    reads = ['set _role [dict create]']
    for path in guest_lefs:
        if path not in guest_roles:
            reads.append(f'read_lef {word(path)}')
            continue
        reads += [
            'set _nlib [llength [[ord::get_db] getLibs]]',
            f'read_lef {word(path)}',
            'foreach _lib [lrange [[ord::get_db] getLibs] $_nlib end] {',
            '  foreach _m [$_lib getMasters] { dict set _role [$_m getName] '
            f'{guest_roles[path]} }}',
            '}']
    script.write_text('\n'.join([
        *reads,
        (f'read_db {word(odb.resolve())}' if odb else f'read_def {word(routed.resolve())}'),
        'set _block [[[ord::get_db] getChip] getBlock]',
        'if {$_block eq "NULL"} { error "placed design has no OpenDB block" }',
        'set _dbu [$_block getDbUnitsPerMicron]',
        'if {$_dbu <= 0} { error "placed design has invalid DBU" }',
        f'set _out [open {word(partial.resolve())} w]',
        'puts $_out "DBU $_dbu"',
        'puts $_out "TOTAL [llength [$_block getInsts]]"',
        *(['set _core [$_block getCoreArea]',
           'puts $_out "CORE [$_core xMin] [$_core yMin] [$_core xMax] [$_core yMax]"']
          if placement is not None else []),
        'set _protected 0',
        'foreach _inst [$_block getInsts] {',
        '  set _master [$_inst getMaster]',
        '  if {[$_master isPad]} { set _kind PAD } elseif {[$_master isBlock]} { set _kind BLOCK } '
        'elseif {[dict exists $_role [$_master getName]]} { set _kind [dict get $_role [$_master getName]] } '
        'else { continue }',
        '  if {![$_inst isPlaced]} { error "unplaced protected instance: [$_inst getName]" }',
        '  set _box [$_inst getBBox]',
        '  if {[$_box xMin] >= [$_box xMax] || [$_box yMin] >= [$_box yMax]} { error "empty protected bbox: [$_inst getName]" }',
        '  puts $_out "BOX $_kind [$_master getName] [$_box xMin] [$_box yMin] [$_box xMax] [$_box yMax]"',
        '  incr _protected',
        '}',
        'puts $_out "END $_protected"',
        'close $_out',
        f'file rename -force {word(partial.resolve())} {word(output.resolve())}',
    ]) + '\n')
    network, command = native_tool_command(image, ['openroad', '-exit', str(script)])
    cmd = ['docker', 'run', '--rm', '--network', network,
           *_dmem.docker_memory_flags(),
           '-v', f'{project.resolve()}:{project.resolve()}',
           '-v', f'{(pdk_root / pdk).resolve()}:/pdk/{pdk}:ro',
           *extra_mounts, image, '--skip', *command]
    result = _run_logged(cmd, folder / 'placed_keepouts.log')
    if result.returncode != 0 or not output.is_file():
        raise Refusal('LL_DENSITY_FILL_PLACEMENT_UNREADABLE',
                      f'{routed}: OpenDB rc={result.returncode}; '
                      f'{folder / "placed_keepouts.log"}')
    try:
        lines = output.read_text().splitlines()
        if len(lines) < 3 or lines[0].split()[0] != 'DBU':
            raise ValueError('missing DBU header')
        dbu = int(lines[0].split()[1])
        total = int(lines[1].split()[1]) if lines[1].startswith('TOTAL ') else -1
        protected = int(lines[-1].split()[1]) if lines[-1].startswith('END ') else -1
        if dbu <= 0 or total < 0 or protected < 0 or protected > total:
            raise ValueError('invalid OpenDB census')
        boxes = []
        core = None
        if placement is not None:
            fields = lines[2].split()
            if len(fields) != 5 or fields[0] != 'CORE':
                raise ValueError('candidate OpenDB core area absent')
            core = [int(v) / dbu for v in fields[1:]]
            if core[0] >= core[2] or core[1] >= core[3]:
                raise ValueError('candidate OpenDB core area invalid')
        for line in lines[3 if placement is not None else 2:-1]:
            fields = line.split()
            if len(fields) != 7 or fields[0] != 'BOX' or fields[1] not in ('PAD', 'BLOCK'):
                raise ValueError(f'invalid OpenDB box: {line}')
            coords = tuple(int(x) for x in fields[3:])
            if coords[0] >= coords[2] or coords[1] >= coords[3]:
                raise ValueError(f'empty OpenDB box: {line}')
            boxes.append((fields[1], fields[2], coords))
        if len(boxes) != protected:
            raise ValueError('truncated OpenDB protected-instance census')
    except (OSError, ValueError, IndexError) as exc:
        raise Refusal('LL_DENSITY_FILL_PLACEMENT_UNREADABLE',
                      f'{output}: {exc}') from exc
    result = {'dbu': dbu, 'total': total, 'boxes': boxes, 'source': str(odb or routed)}
    if placement is not None:
        result['core_um'] = core
    return result


def top_up_density(project: Path, image: str, pdk_root: Path, pdk: str,
                   gds: Path, density_config: Path, lane: str, *,
                   placement: Optional[dict] = None) -> Dict[str, Any]:
    """Use the PDK-derived dummy-metal engine after the PDK's own filler."""
    cfg, map_text, lef_text, deck_text = _density_source(pdk_root, pdk,
                                                         density_config)
    fill_cfg = build_metal_fill_config(map_text, lef_text, deck_text)
    if not fill_cfg or not fill_cfg.get('layers'):
        raise Refusal('LL_DENSITY_FILL_NO_DERIVED_LAYERS', str(density_config))
    from die_finishing_gen import PROVIDER_TARGET_REL, provider_target
    profile = provider_target(project)
    if profile is not None and profile.get('provider') == 'wafer.space':
        # The selected operator's ReadLayout maps these dummy datatypes to
        # active metal/poly. Emit that same encoding before final sign-off,
        # preserving all PDK spacing, width, density and keepout parameters.
        mapped = {(30, 0), (34, 0), (36, 0), (42, 0), (46, 0), (81, 0)}
        changes = []
        for row in fill_cfg['layers']:
            if tuple(row['layer']) in mapped and row.get('fill_datatype') == 4:
                row['fill_datatype'] = 0
                changes.append({'layer': row['layer'][0], 'from': 4, 'to': 0})
        if changes:
            target = project / PROVIDER_TARGET_REL
            fill_cfg['_derivation']['provider_fill_encoding'] = {
                'source': str(target), 'sha256': digest(target),
                'basis': 'selected wafer.space ReadLayout dummy-to-active layer map',
                'changes': changes}
    root = project / 'phase3/librelane' / lane
    placed = _placed_keepout_boxes(project, image, pdk_root, pdk, cfg, root,
        **({'placement': placement} if placement is not None else {}))
    try:
        spacing = max(float(row['space_to_metal']) for row in fill_cfg['layers'])
        if not math.isfinite(spacing) or spacing <= 0:
            raise ValueError('nonpositive PDK spacing')
    except (KeyError, TypeError, ValueError) as exc:
        raise Refusal('LL_DENSITY_FILL_SPACING_UNREADABLE', str(exc)) from exc
    fill_cfg['keepout_boxes_um'] = sorted([
        [(box[0] / placed['dbu']) - spacing,
         (box[1] / placed['dbu']) - spacing,
         (box[2] / placed['dbu']) + spacing,
         (box[3] / placed['dbu']) + spacing]
        for _, _, box in placed['boxes']])
    fill_cfg['_derivation']['placed_instance_keepout'] = {
        'source': placed['source'], 'source_sha256': digest(Path(placed['source'])),
        'basis': 'OpenDB placed PAD/BLOCK instance getBBox',
        'instances_read': placed['total'],
        'protected_count': len(placed['boxes']), 'spacing_um': spacing}
    placed_pads = sorted({master for kind, master, _ in placed['boxes']
                          if kind == 'PAD'})
    if placed_pads:
        # CORE_AREA comes from the tape-out declaration, so a refusal names
        # that file and the reader's own reason; a declaration Refusal keeps
        # its own code.
        declaration = project / DECLARATION_REL
        try:
            if placement is not None:
                declared = {'CORE_AREA': placed['core_um']}
                sources = {'CORE_AREA': 'candidate OpenDB getCoreArea: ' + placed['source']}
            else:
                declared, sources = declaration_config(project)
        except (OSError, ValueError) as exc:
            raise Refusal('LL_DENSITY_FILL_CORE_UNDECLARED',
                          f'{declaration}: {type(exc).__name__}: {exc}') from exc
        core = declared.get('CORE_AREA')
        core_source = sources.get('CORE_AREA')
        record = project / 'reports/phase3/floorplan_rectangles.json'
        derived_die = derived_core = derived_source = None
        if placement is None and record.is_file():
            derived_die, derived_core, derived_source = settled_floorplan_geometry(project)
        if not core:
            if derived_core is not None:
                core, core_source = derived_core, derived_source
            else:
                raise Refusal('LL_DENSITY_FILL_CORE_UNDECLARED',
                              f'{declaration}: no core_area_um answer for the '
                              f'placed pads {placed_pads}')
        if core:
            configured_die = cfg.get('DIE_AREA')
            if configured_die and derived_die and any(
                    abs(float(a) - float(b)) > 1e-6
                    for a, b in zip(configured_die, derived_die)):
                raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                              f'{density_config}: DIE_AREA {configured_die} '
                              f'differs from settled {derived_die}')
            edge = _core_edge_keepout(configured_die or derived_die or [], core)
            fill_cfg['keepout_edge_um'] = max(
                float(fill_cfg.get('keepout_edge_um') or 0), edge)
            fill_cfg['_derivation']['pad_ring_exclusion'] = {
                'region': 'outside declared core', 'edge_um': edge,
                'core': core, 'source': core_source,
                'placed_pad_masters': placed_pads}
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / 'pdk_fill_config.json'
    out = root / (gds.stem + '.topped.gds')
    report = root / 'fill_report.json'
    write_json(config_path, fill_cfg)
    programs = Path(__file__).resolve().parent
    cmd = ['docker', 'run', '--rm', *_dmem.docker_memory_flags(),
           '-v', f'{project.resolve()}:{project.resolve()}',
           '-v', f'{programs.resolve()}:{programs.resolve()}:ro',
           image, '--skip', 'python3', str(programs / 'metal_fill_emit.py'),
           str(project), '--gds', str(gds), '--config', str(config_path),
           '--out', str(out), '--report', str(report),
           '--cell', str(cfg.get('DESIGN_NAME') or '')]
    result = _run_logged(cmd, root / 'fill.log')
    if result.returncode != 0 or not out.is_file() or not report.is_file():
        raise Refusal('LL_DENSITY_FILL_FAILED',
                      f'{root}: rc={result.returncode}; {root / "fill.log"}')
    measured = _load(report)
    if not (measured.get('verdict') == 'PASS' or
            (measured.get('verdict') == 'PARTIAL' and
             measured.get('promoted_on_foundry_floor'))) or not measured.get('layers'):
        raise Refusal('LL_DENSITY_FILL_NOT_MEASURED', str(report))
    if digest(out) == digest(gds):
        raise Refusal('LL_DENSITY_FILL_NO_CHANGE', str(report))
    return {'gds': str(out), 'gds_sha256': digest(out),
            'input_sha256': digest(gds), 'report': str(report),
            'report_sha256': digest(report), 'config': str(config_path),
            'config_sha256': digest(config_path),
            'layers': measured['layers']}


def measure_density_ratios(project: Path, image: str, pdk_root: Path, pdk: str,
                           gds: Path, density_config: Path, lane: str) -> Dict[str, Any]:
    """Emit drawn+dummy coverage for every resolvable PDK die-density rule."""
    cfg, map_text, lef_text, deck_text = _density_source(pdk_root, pdk,
                                                         density_config)
    fill_cfg = build_metal_fill_config(map_text, lef_text, deck_text)
    if not fill_cfg:
        raise Refusal('LL_DENSITY_RATIOS_UNRESOLVED', str(density_config))
    specs = _density_ratio_specs(deck_text, fill_cfg)
    die = cfg.get('DIE_AREA')
    if die is None:
        # Density's step config does not declare DIE_AREA in every tool
        # release. Read the current physical subject, never a GDS bbox.
        from librelane_contract import _def_die_area
        filled = project / 'phase3/stage3/pnr/filled.def'
        if filled.is_file():
            validate_fill_consumption(project)
            die = _def_die_area(filled)
    if not specs or not isinstance(die, list) or len(die) != 4:
        raise Refusal('LL_DENSITY_RATIOS_UNRESOLVED', str(density_config))
    root = project / 'phase3/librelane' / lane
    root.mkdir(parents=True, exist_ok=True)
    specs_path = root / 'density_specs.json'
    report = root / 'density_ratios.json'
    write_json(specs_path, specs)
    programs = Path(__file__).resolve().parent
    before = digest(gds)
    cmd = ['docker', 'run', '--rm', *_dmem.docker_memory_flags(),
           '-v', f'{project.resolve()}:{project.resolve()}',
           '-v', f'{programs.resolve()}:{programs.resolve()}:ro',
           image, '--skip', 'python3', str(programs / 'die_density_ratio_emit.py'),
           '--gds', str(gds), '--specs', str(specs_path),
           '--die', json.dumps(die), '--out', str(report),
           '--cell', str(cfg.get('DESIGN_NAME') or '')]
    # Match the same foundry instrument, rather than calling its extent a
    # DEF die. Other denominator grammars retain the strict equality check.
    if re.search(r'\bchip_area\s*=\s*extent(?:\.sized\(0(?:\.0)?\))?\.area\b',
                 _dla.deck_code_only(deck_text)):
        cmd.append('--extent-from-deck')
    result = _run_logged(cmd, root / 'density_ratios.log')
    if not report.is_file():
        raise Refusal('LL_DENSITY_RATIOS_NOT_MEASURED',
                      f'{root}: rc={result.returncode}; '
                      f'{root / "density_ratios.log"}')
    measured = _load(report)
    if (result.returncode != 0 or measured.get('status') != 'MEASURED' or
            digest(gds) != before or
            set(measured.get('layers') or {}) != set(specs) or
            any(not isinstance(row.get('ratio'), (int, float)) or
                isinstance(row.get('ratio'), bool) or
                not 0 <= row['ratio'] <= 1 for row in measured['layers'].values())):
        raise Refusal('LL_DENSITY_RATIOS_NOT_MEASURED', str(report))
    return {'report': str(report), 'report_sha256': digest(report),
            'subject': str(gds), 'subject_sha256': before,
            'denominator': {k: measured.get(k) for k in
                            ('die', 'declared_die', 'extent_from_deck', 'extent_matches_declared_die')},
            'layers': measured['layers']}


#: The ONE place a per-layer metal density of the stream that ships lives:
#: `reports/phase3/metal_density.json`. The runner's own KLayout emitter writes
#: it on the direct path, the tape-out precheck delegate
#: (`general_precheck` -> `metal_layer_density_check reports/phase3`), the
#: sign-off ladder and the tape-out checklist all read it there. The LibreLane
#: fill arms measured the shipped stream only into their tool lane
#: (`phase3/librelane/<lane>/density_ratios.json`), so on those arms the
#: precheck found no density report at all (measured on a subservient DIE
#: tree: Checker.KLayoutDensity NOT_DETERMINED, "no density report at
#: reports/phase3", beside a MEASURED `37-*-density-ratios` lane).
METAL_DENSITY_REL = 'reports/phase3/metal_density.json'


def publish_metal_density(project: Path, ratios: Dict[str, Any], gds: Path,
                          pdk: str) -> Optional[Path]:
    """Publish the shipped stream's per-layer density (``ratios`` from
    `measure_density_ratios`) at `METAL_DENSITY_REL`, bound to ``gds`` by
    sha256. Call it only once the shipped bytes are decided, with ``gds`` the
    stream that ships. Only rows whose deck identifier names a metal layer are
    carried (the reader's own layer grammar). A ratio measured on other bytes
    than ``gds``, or two rules giving one layer two values, publishes nothing
    AND removes any report already at `METAL_DENSITY_REL`: the precheck reader
    does not compare `gds_sha256`, so a report left behind would be judged as
    the shipped stream's. With no report there, the runner's own emitter
    measures the shipped GDS, or the reader says it found none."""
    import metal_layer_density_check as _mld
    gds = Path(gds)
    out = project / METAL_DENSITY_REL

    def declined() -> None:
        out.unlink(missing_ok=True)
        return None

    if not gds.is_file() or ratios.get('subject_sha256') != digest(gds):
        return declined()
    layers: Dict[str, float] = {}
    rules: Dict[str, str] = {}
    for rule, row in sorted((ratios.get('layers') or {}).items()):
        name = str(row.get('identifier') or '')
        value = row.get('ratio')
        if (row.get('status') != 'MEASURED' or not _mld._METAL_RE.match(name)
                or not isinstance(value, (int, float)) or isinstance(value, bool)):
            continue
        key = name.lower()
        if key in layers and layers[key] != value:
            return declined()
        layers[key], rules[key] = value, rule
    if not layers:
        return declined()
    report = Path(str(ratios.get('report') or ''))
    try:
        die_area = _load(report).get('die_area_um2') if report.is_file() else None
    except (OSError, ValueError):
        die_area = None
    try:
        gds_record = gds.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        gds_record = str(gds)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, {
        'tool': 'klayout', 'producer': 'librelane_fill_dfm.measure_density_ratios',
        'measurement': 'per_rule_drawn_plus_dummy_area_over_die_extent',
        'pdk': pdk, 'gds': gds_record, 'gds_sha256': digest(gds),
        'die_area_um2': die_area, 'layers': layers, 'layer_rules': rules,
        'source': {'report': str(report), 'report_sha256': ratios.get('report_sha256')}})
    return out


# --- row occupancy, from the DEF and the LEFs that define its masters -------

_LEF_MACRO = re.compile(r'^\s*MACRO\s+(\S+)(.*?)^\s*END\s+\1\b', re.S | re.M)
_LEF_SITE = re.compile(r'^\s*SITE\s+(\S+)(.*?)^\s*END\s+\1\b', re.S | re.M)
_LEF_SIZE = re.compile(r'^\s*SIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;', re.M)
_LEF_CLASS = re.compile(r'^\s*CLASS\s+(\S+)', re.M)
_DEF_UNITS = re.compile(r'^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;', re.M)
_DEF_ROW = re.compile(r'^\s*ROW\s+\S+\s+(\S+)\s+-?\d+\s+-?\d+\s+\S+'
                      r'(?:\s+DO\s+(\d+)\s+BY\s+(\d+))?', re.M)
_DEF_PLACED = re.compile(r'^\s*-\s+\S+\s+(\S+)[^;]*?\+\s+(?:PLACED|FIXED)\s', re.M | re.S)


def lef_geometry(lef_texts) -> Dict[str, Dict[str, Any]]:
    """{'macros': {name: (w, h, class)}, 'sites': {name: (w, h)}} in microns."""
    macros: Dict[str, Any] = {}
    sites: Dict[str, Any] = {}
    for text in lef_texts:
        for name, body in _LEF_SITE.findall(text):
            size = _LEF_SIZE.search(body)
            if size:
                sites[name] = (float(size.group(1)), float(size.group(2)))
        for name, body in _LEF_MACRO.findall(text):
            size = _LEF_SIZE.search(body)
            cls = _LEF_CLASS.search(body)
            if size:
                # LEF keywords are case-insensitive (the gf180 cell LEF writes
                # `CLASS core`, and OpenROAD reads it as CORE).
                macros[name] = (float(size.group(1)), float(size.group(2)),
                                cls.group(1).upper() if cls else '')
    return {'macros': macros, 'sites': sites}


def row_occupancy(def_text: str, lef_texts) -> Dict[str, Any]:
    """Row area and the CORE-class instance area placed in the DEF, in um^2.

    The same quantity the direct fill emitter's odb block measured: the
    area of every placed instance whose LEF class is CORE (logic, taps and
    fill together) over the rows' site area.  An instance or row site no LEF
    defines leaves the result NOT_MEASURED -- never a guess."""
    geo = lef_geometry(lef_texts)
    rows = _DEF_ROW.findall(def_text)
    row_area = 0.0
    unknown_sites = set()
    for site, nx, ny in rows:
        if site not in geo['sites']:
            unknown_sites.add(site)
            continue
        w, h = geo['sites'][site]
        row_area += int(nx or 1) * int(ny or 1) * w * h
    comps = re.search(r'^\s*COMPONENTS\s+\d+\s*;(.*?)^\s*END\s+COMPONENTS', def_text, re.S | re.M)
    core_area = 0.0
    unknown_masters: Dict[str, int] = {}
    for master in _DEF_PLACED.findall(comps.group(1) if comps else ''):
        row = geo['macros'].get(master)
        if row is None:
            unknown_masters[master] = unknown_masters.get(master, 0) + 1
            continue
        if row[2] == 'CORE':
            core_area += row[0] * row[1]
    measured = bool(rows) and not unknown_sites and not unknown_masters and row_area > 0
    return {'status': 'MEASURED' if measured else 'NOT_MEASURED',
            'row_area_um2': round(row_area, 4), 'core_class_area_um2': round(core_area, 4),
            'row_utilization_pct': round(100.0 * core_area / row_area, 4) if measured else None,
            'unknown_sites': sorted(unknown_sites),
            'unknown_masters': dict(sorted(unknown_masters.items())[:20])}


def _host_lefs(config: Dict[str, Any], pdk_root: Path, pdk: str) -> List[Path]:
    guest = f'/pdk/{pdk}'
    out = []
    for key in ('TECH_LEFS', 'CELL_LEFS', 'PAD_LEFS', 'MACRO_LEFS', 'EXTRA_LEFS'):
        value = config.get(key) or []
        items = list(value.values()) if isinstance(value, dict) else list(value)
        for item in items:
            text = str(item)
            path = Path(str(pdk_root / pdk) + text[len(guest):]) if text.startswith(guest) else Path(text)
            if path not in out:
                out.append(path)
    return out


def run_fill_insertion(project: Path, image: str, pdk_root: Path, pdk: str, *,
                       routed_def: Path, netlist, sdc: Path,
                       lane: str = '34') -> Dict[str, Any]:
    """`OpenROAD.FillInsertion` on the ODB of the route that ships.

    Returns the tool's DEF, the cells it placed (per master, per class), the
    row occupancy before and after, and the supply-ownership verdict of the
    DEF it wrote (F24).  Refuses by name when the step placed nothing while
    the rows still had room (#445): an empty fill must not claim success."""
    import pg_supply_pin_ownership_check as _pgo
    for source in (routed_def, sdc, *(netlist if isinstance(netlist, (list, tuple)) else [netlist])):
        if not Path(source).is_file():
            raise Refusal('LL_ROUTE_VIEW_MISSING', str(source))
    configs = resolve_step_configs(project, image, pdk, [ODB_FILL_STEP],
                                   pdk_root=pdk_root, folder=CONFIG_FOLDER)
    config = _load(configs[ODB_FILL_STEP])
    patterns = cell_patterns(config)
    if not (patterns['decap'] or patterns['fill']):
        raise Refusal('LL_FILL_CELLS_UNDECLARED', f'{pdk}: DECAP_CELLS / FILL_CELLS')
    mounts = _mounts(pdk_root, pdk)
    state = state_from_direct(project, image, configs[ODB_FILL_STEP],
                              {'def': routed_def, 'nl': netlist, 'sdc': sdc},
                              project / 'phase3/librelane' / CONFIG_FOLDER / 'bridge',
                              mounts=mounts)
    folder = run_chain(project, image, [(ODB_FILL_STEP, configs[ODB_FILL_STEP], state)],
                       mounts=mounts, lane=lane, pdk_root=PDK_GUEST_ROOT)[0]
    receipt = validate_step_receipt(folder, ODB_FILL_STEP)
    fp = receipt['input']
    current = {str(path): digest(path) for path in _walk_input_views(_load(state))}
    if (fp.get('image') != image or fp.get('config') != digest(configs[ODB_FILL_STEP])
            or fp.get('state') != digest(state) or fp.get('state_files') != current
            or fp.get('config_files') != config_file_hashes(config, mounts)):
        raise Refusal('LL_FILL_INPUT_CHANGED', str(folder))
    out_state = _load(folder / 'state_out.json')
    filled = Path(str(out_state.get('def') or ''))
    if not filled.is_file():
        raise Refusal('LL_FILL_NO_DEF', f'{folder}: state def {filled}')
    before_text = Path(routed_def).read_text(errors='replace')
    after_text = filled.read_text(errors='replace')
    census = fill_census(before_text, after_text, patterns)
    lefs = _host_lefs(config, pdk_root, pdk)
    lef_texts = [p.read_text(errors='replace') for p in lefs if p.is_file()]
    occupancy = {'before': row_occupancy(before_text, lef_texts),
                 'after': row_occupancy(after_text, lef_texts)}
    ownership = _pgo.judge(after_text, [t for p, t in zip([p for p in lefs if p.is_file()], lef_texts)
                                        if not p.name.endswith('.tlef')])
    record = {'step': ODB_FILL_STEP, 'state': str(folder / 'state_out.json'),
              'state_sha256': digest(folder / 'state_out.json'),
              'subject': str(routed_def), 'subject_sha256': digest(Path(routed_def)),
              'filled_def': str(filled), 'filled_def_sha256': digest(filled),
              'patterns': patterns, 'census': census, 'occupancy': occupancy,
              'metrics': {k: v for k, v in _metrics(folder).items()
                          if k.startswith('design__instance__count')},
              'supply_ownership': {k: ownership.get(k) for k in
                                   ('verdict', 'code', 'reason', 'instances',
                                    'supply_pins_checked', 'off_supply_pins')},
              'refusals': [],
              'binding': {'image': image, 'config': str(configs[ODB_FILL_STEP]),
                          'input_state': str(state),
                          'mounts': [[str(host), guest] for host, guest in mounts],
                          'receipt_sha256': digest(folder / 'vibeic_receipt.json')}}
    validate_fill_handoff(project, record, routed_def=routed_def)
    after_util = occupancy['after'].get('row_utilization_pct')
    if census['added'] == 0 and not (isinstance(after_util, (int, float)) and after_util >= 95.0):
        record['refusals'].append(
            'LL_FILL_NO_OP: OpenROAD.FillInsertion placed 0 cells and the rows are not '
            f"full (row utilisation {after_util}%)")
    if census['removed'] or census['per_class']['other']:
        record['refusals'].append(
            f"LL_FILL_NOT_FILL_ONLY: removed {census['removed']}, "
            f"added {census['per_class']['other']} non-fill instance(s)")
    if ownership.get('verdict') == 'FAIL':
        record['refusals'].append(f"LL_FILL_SUPPLY_OWNERSHIP: {ownership.get('reason')}")
    return record


def _walk_input_views(state: dict):
    from librelane_contract import _walk_paths
    return _walk_paths({k: v for k, v in state.items() if k != 'metrics'})


def _record_provider_binding(project: Path, fingerprint: dict) -> str:
    """Keep the producer identity while revalidating current LOCAL material."""
    if 'local_provider' in fingerprint:
        import librelane_signoff_evidence as native
        image = fingerprint.get('image')
        native._retained_local_provider(project, fingerprint['local_provider'], image)
        return image
    return resolve_image(project, record=False)


def validate_fill_handoff(project: Path, record: dict, *, routed_def: Path) -> dict:
    """Revalidate the actual fill producer and current inputs before consumption."""
    try:
        state_path = Path(record['state']).resolve()
        folder = state_path.parent
        if not folder.is_relative_to((project / 'phase3/librelane').resolve()) \
                or 'attempts' in folder.relative_to(project.resolve()).parts \
                or state_path.name != 'state_out.json' or record['step'] != ODB_FILL_STEP:
            raise ValueError('wrong producer stage/path')
        binding = record['binding']
        receipt = validate_step_receipt(folder, ODB_FILL_STEP)
        if digest(folder / 'vibeic_receipt.json') != binding['receipt_sha256']:
            raise ValueError('producer receipt changed')
        fp = receipt['input']
        import librelane_signoff_evidence as native
        switch_path = project / 'phase3/librelane_switch.json'
        switch = _load(switch_path) if switch_path.is_file() else {}
        image = _record_provider_binding(project, fp)
        mounts = native._pdk_mounts(project, switch, folder, image)
        if [[str(Path(host).resolve()), str(guest)] for host, guest in mounts] != \
                [[str(Path(host).resolve()), str(guest)] for host, guest in binding['mounts']]:
            raise ValueError('current PDK mount differs from producer')
        config_path, initial = Path(binding['config']), Path(binding['input_state'])
        if not all(p.resolve().is_relative_to(project.resolve()) for p in (config_path, initial)):
            raise ValueError('foreign config or input state')
        config, before, after = _load(config_path), _load(initial), _load(state_path)
        if (fp.get('image') != binding['image'] or binding['image'] != image
                or fp.get('config') != digest(config_path)
                or fp.get('state') != digest(initial)
                or fp.get('state_files') != {str(p): digest(p) for p in _walk_input_views(before)}
                or fp.get('config_files') != config_file_hashes(config, binding['mounts'])
                or config.get('meta', {}).get('step') != ODB_FILL_STEP):
            raise ValueError('current input/config/image differs from producer')
        subject, output = Path(record['subject']), Path(record['filled_def'])
        if (subject.resolve() != routed_def.resolve() or before.get('def') != str(subject.resolve())
                or digest(subject) != record['subject_sha256']
                or digest(state_path) != record['state_sha256']
                or Path(after['def']).resolve() != output.resolve()
                or not output.resolve().is_relative_to(folder)
                or digest(output) != record['filled_def_sha256']):
            raise ValueError('wrong or stale input/output DEF')
        name = config.get('DESIGN_NAME')
        if not name or any(_def_design_name(p) != name for p in (subject, output)):
            raise ValueError('wrong DEF design')
        return receipt
    except (OSError, ValueError, TypeError, KeyError, AttributeError, Refusal) as exc:
        raise Refusal('LL_FILL_HANDOFF_UNBOUND', str(exc)) from exc


def validate_fill_consumption(project: Path) -> None:
    """The existing Step-34 gate checks the DEF its downstream path consumed."""
    import _path_layout as pl
    doc = _load(project / RECORD_REL)['odb']
    if doc.get('shipped') != 'librelane':
        raise Refusal('LL_FILL_NOT_CONSUMED', 'no tool DEF shipped')
    tool = doc['tool']
    if Path(tool['subject']).resolve().parent != pl.pnr_dir(project).resolve() \
            or digest(pl.pnr_dir(project) / 'routed.def') != tool['subject_sha256']:
        raise Refusal('LL_FILL_HANDOFF_UNBOUND', 'fill did not consume current routed.def')
    validate_fill_handoff(project, tool, routed_def=Path(tool['subject']))
    handoff = _load(project / 'phase3/tool_arms/34/odb_handoff.json')
    row = handoff['views']['def']
    destination = pl.pnr_dir(project) / 'filled.def'
    if (handoff.get('state') != tool['state']
            or handoff.get('state_sha256') != tool['state_sha256']
            or Path(row['source']).resolve() != Path(tool['filled_def']).resolve()
            or Path(row['dest']).resolve() != destination.resolve()
            or row.get('source_sha256') != tool['filled_def_sha256']
            or row.get('dest_sha256') != tool['filled_def_sha256']
            or digest(destination) != tool['filled_def_sha256']):
        raise Refusal('LL_FILL_NOT_CONSUMED', 'handoff does not bind current filled.def')


def direct_schema_reports(record: Dict[str, Any], subject: Dict[str, Any],
                          subject_lines: str) -> tuple[str, dict, str]:
    """The existing DEF-fill writer's documents, also used for current adoption."""
    census = record.get('census') or {}
    after = (record.get('occupancy') or {}).get('after') or {}
    placed = int(census.get('added') or 0)
    row_util = after.get('row_utilization_pct')
    unit = '%' if row_util is not None else ''
    report = (subject_lines +
               '# Metal-fill / density report — LibreLane OpenROAD.FillInsertion\n'
               f'# filler instances placed: {placed}\n'
               f"# per class: {json.dumps(census.get('per_class'))}\n"
               '# row-area utilization (post-fill): '
               f"{row_util if row_util is not None else 'unresolved'}{unit}\n")
    document = {
        'tool': 'librelane:OpenROAD.FillInsertion', 'filler_instances': placed,
        'row_utilization_pct': row_util, 'core_utilization_pct': None,
        'utilization_below_report_precision': False,
        'note': ('row_utilization_pct = CORE-class instance area / row site area, '
                 "from the tool's DEF and the LEFs that define it; per-layer CMP "
                 'density is judged by the PDK density deck (KLayout.Density) at '
                 "step 34's GDS half"),
        'measured_subject': subject}
    marker = (
               'metal_fill_done\n'
               '# LibreLane OpenROAD.FillInsertion (step 34, mig104).\n'
               f'# fillers placed: {placed}\n'
               f"# state: {record.get('state')} sha256:{record.get('state_sha256')}\n")
    return report, document, marker


def write_direct_schema_reports(project: Path, record: Dict[str, Any],
                                subject: Dict[str, Any], subject_lines: str) -> None:
    """Publish the original fill report schema from the tool's current DEFs."""
    import _path_layout as _pl
    from _atomic_artefact import write_text
    report, document, marker = direct_schema_reports(record, subject, subject_lines)
    reports = project / 'reports'
    reports.mkdir(parents=True, exist_ok=True)
    write_text(reports / 'density.rpt', report)
    write_json(reports / 'density.json', document)
    write_text(_pl.pnr_dir(project) / 'metal_fill.done', marker)


def cells_placed_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """What F20b reads: which cells step 34 placed, per master and class, and
    the DEF (by sha256) whose COMPONENTS hold their positions."""
    census = record.get('census') or {}
    return {'step': '34', 'producer': record.get('step'),
            'def': record.get('filled_def'), 'def_sha256': record.get('filled_def_sha256'),
            'subject_def_sha256': record.get('subject_sha256'),
            'rule': 'placed = in COMPONENTS of `def`, not in COMPONENTS of the subject DEF',
            'per_class': census.get('per_class'), 'per_master': census.get('per_master'),
            'class_of_master': census.get('class_of_master'),
            'patterns': record.get('patterns')}


# --- the GDS arms: which fill ships ------------------------------------------

def select_gds_fill(project: Path, direct: Optional[Dict[str, Any]],
                    tool: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """`select_arms` over the two measured fills, the same deck on each.

    An arm the deck did not measure is not a candidate.  A tie (both at the
    same count) keeps the direct arm: it is what the flow has shipped, and
    the tool arm has nothing measured to recommend it over the direct one."""
    root = project / 'phase3/tool_arms/34'
    root.mkdir(parents=True, exist_ok=True)
    reports = {}
    scope = {'deck': 'KLayout.Density (PDK density deck)', 'metric': DENSITY_METRIC}
    for name, arm in (('direct', direct), ('librelane', tool)):
        count = _count((arm or {}).get(DENSITY_METRIC))
        report = root / f'{name}.selection.json'
        write_json(report, {'verdict': 'PASS' if count is not None else 'NOT_MEASURED',
                            'scope': scope,
                            'metrics': {DENSITY_METRIC: {'status': 'MEASURED', 'value': count}
                                        if count is not None else {'status': 'NOT_MEASURED'}},
                            'subject_sha256': (arm or {}).get('subject_sha256')})
        reports[name] = report
    selection = select_arms(reports, {DENSITY_METRIC: 'min'}, root / 'selection.json')
    winner = selection.get('selection')
    if winner == 'UNDETERMINED' and selection.get('reason') == 'LL_PARETO_TIE':
        selection['tie_break'] = 'direct: equal density-error counts; the shipped arm stands'
        winner = 'direct'
    selection['winner'] = winner if winner in ('direct', 'librelane') else None
    write_json(root / 'selection.json', selection)
    return selection


def update_record(project: Path, section: str, value: Dict[str, Any]) -> Path:
    """Write one half's evidence (`odb` or `gds`) into the step-34 record.

    The two halves run at different points of the flow (the GDS half inside
    stream-out, the ODB half in canonicalisation), so each replaces only its
    own section; the switch mode is stamped with it."""
    path = project / RECORD_REL
    try:
        doc = _load(path) if path.is_file() else {}
    except (OSError, ValueError, Refusal):
        doc = {}
    doc['step'] = '34'
    doc[section] = value
    write_json(path, doc)
    return path


def tool_density(project: Path) -> Optional[Dict[str, Any]]:
    """Step 35's CMP half: the density count step 34 recorded from the tool.

    None when step 34 did not run on the tool (no record, or a record with no
    measured GDS arm).  A record whose tool state no longer hashes to what it
    names is refused: a cross-reference to evidence that moved is not one."""
    project = project.resolve()
    path = project / RECORD_REL
    if not path.is_file():
        return None
    promotion = None
    try:
        doc = _load(path)
        if doc.get('default_stream') or (project / DEFAULT_STREAM_REL).is_file() \
                or (project / 'phase3/librelane' / CONFIG_FOLDER / 'KLayout.StreamOut.json').is_file():
            promotion = validate_default_stream(project)
    except (OSError, ValueError, Refusal, KeyError, TypeError):
        return {'status': 'UNREADABLE', 'source': RECORD_REL}
    arms = doc.get('gds') or {}
    shipped = arms.get('shipped')
    arm = arms.get(shipped) if shipped else None
    if not isinstance(arm, dict):
        return step37_density(project) if not arms else None
    state = Path(str(arm.get('state') or ''))
    if not state.is_file() or digest(state) != arm.get('state_sha256'):
        return {'status': 'STALE', 'source': RECORD_REL, 'state': str(state)}
    count = _count(arm.get(DENSITY_METRIC))
    if count is None:
        return {'status': 'NOT_MEASURED', 'source': RECORD_REL}
    row = validate_density_result(project, arm)
    if row.get('value') != count or row.get('value') == 'NOT_MEASURED':
        return {'status': 'NOT_MEASURED', 'source': RECORD_REL,
                'reason': row.get('reason') or 'density record differs from tool output'}
    result = {'status': 'MEASURED', 'errors': count, 'arm': shipped,
            'rules': arm.get('rules'), 'runset': arm.get('runset'),
            'source': RECORD_REL, 'state': str(state), 'state_sha256': arm.get('state_sha256'),
            'subject_sha256': arm.get('subject_sha256')}
    if promotion is not None:
        try:
            result['per_layer'] = current_metal_density(project, arm, promotion)
        except (OSError, ValueError, Refusal, KeyError, TypeError) as exc:
            result['per_layer'] = {'verdict': 'NOT_MEASURED', 'reason': str(exc),
                                   'consumer': 'metal_layer_density_check.check'}
    return result


DEFAULT_STREAM_REL = 'phase3/librelane/37-default-promotion.json'


def current_metal_density(project: Path, arm: dict, promotion: dict) -> dict:
    """Run the existing per-layer consumer on the adopted current stream.

    The native count, executed rules and per-rule area report remain separate
    facts. Neither a zero count nor a report's own GDS claim supplies adoption.
    No generic bounds or local-window results are passed to the consumer.
    """
    import metal_layer_density_check as mld
    import librelane_signoff_evidence as native
    canonical = Path(promotion['canonical'])
    sha = digest(canonical)
    ratios = arm['ratios']
    ratio_report = Path(ratios['report'])
    measured = _load(ratio_report)
    report = project / METAL_DENSITY_REL
    published = _load(report)
    if (sha != arm['subject_sha256'] or sha != ratios['subject_sha256']
            or digest(Path(measured['gds'])) != sha
            or digest(ratio_report) != ratios['report_sha256']
            or measured.get('status') != 'MEASURED'
            or measured.get('layers') != ratios['layers']
            or published.get('gds_sha256') != sha
            or (project / published['gds']).resolve() != canonical.resolve()
            or published.get('source') != {'report': str(ratio_report),
                                           'report_sha256': digest(ratio_report)}):
        raise Refusal('LL_METAL_DENSITY_SUBJECT_UNBOUND', str(report))
    state = Path(arm['state'])
    image = resolve_image(project, record=False)
    # Default finishing needs no step switch; the PDK declaration and root
    # receipt still bind its materials in _pdk_mounts, as at _current_stage.
    switch_path = project / 'phase3/librelane_switch.json'
    switch = _load(switch_path) if switch_path.is_file() else {}
    mounts = native._pdk_mounts(project, switch, state.parent, image)
    pdk = _load(project / 'phase3/librelane' / CONFIG_FOLDER / 'KLayout.Density.json')['PDK']
    root = next((Path(host) if guest == '/pdk' else Path(host).parent
                 for host, guest in mounts if guest in ('/pdk', f'/pdk/{pdk}')), None)
    if root is None:
        raise Refusal('LL_METAL_DENSITY_PDK_UNBOUND', str(mounts))
    cfg, map_text, lef_text, deck_text = _density_source(
        root, pdk, project / 'phase3/librelane' / CONFIG_FOLDER / 'KLayout.Density.json')
    if (published.get('pdk') != pdk or not measured.get('extent_from_deck')
            or not re.search(r'\bchip_area\s*=\s*extent(?:\.sized\(0(?:\.0)?\))?\.area\b',
                             _dla.deck_code_only(deck_text))):
        raise Refusal('LL_METAL_DENSITY_SCOPE_UNBOUND', str(report))
    specs = _density_ratio_specs(deck_text, build_metal_fill_config(map_text, lef_text, deck_text))
    required = {rule: row for rule, row in specs.items()
                if mld._METAL_RE.fullmatch(str(row.get('identifier') or ''))}
    executed = set(re.findall(r'\bExecuting rule\s+(\S+)',
                             (state.parent / 'invocation.log').read_text()))
    if not required or not set(required) <= executed:
        raise Refusal('LL_METAL_DENSITY_RULES_NOT_EXECUTED', str(sorted(set(required) - executed)))
    layers, rules = {}, {}
    for rule, spec in required.items():
        row = measured['layers'][rule]
        if (row.get('status') != 'MEASURED' or row.get('identifier') != spec['identifier']
                or row.get('layers') != spec['layers'] or not spec.get('layers')
                or type(row.get('ratio')) not in (int, float)
                or not math.isfinite(row['ratio']) or not 0 <= row['ratio'] <= 1):
            raise Refusal('LL_METAL_DENSITY_LAYER_NOT_MEASURED', rule)
        name = spec['identifier'].lower()
        if name in layers and layers[name] != row['ratio']:
            raise Refusal('LL_METAL_DENSITY_LAYER_CONFLICT', name)
        layers[name], rules[name] = row['ratio'], rule
    area = measured.get('die_area_um2')
    region = measured.get('die')
    if (type(area) not in (int, float) or not math.isfinite(area) or area <= 0
            or not isinstance(region, list) or len(region) != 4
            or not all(type(x) in (int, float) and math.isfinite(x) for x in region)
            or not (region[0] < region[2] and region[1] < region[3])
            or not math.isclose(area, (region[2] - region[0]) * (region[3] - region[1]))
            or published.get('die_area_um2') != area
            or published.get('layers') != layers or published.get('layer_rules') != rules
            or published.get('measurement') != 'per_rule_drawn_plus_dummy_area_over_die_extent'
            or any(k in published for k in ('windows', 'limits'))):
        raise Refusal('LL_METAL_DENSITY_POPULATION_UNBOUND', str(report))
    windows, provenance = mld.pdk_windows_for(pdk)
    if not str(provenance.get('scope', '')).lower().startswith(('whole-die', 'global (whole-die)')):
        raise Refusal('LL_METAL_DENSITY_WINDOW_SCOPE_UNBOUND', str(provenance))
    judged = mld.check(report, windows, None, None, provenance, set(windows))
    if set(judged.get('per_layer') or {}) != set(layers):
        raise Refusal('LL_METAL_DENSITY_CONSUMER_COVERAGE', str(judged))
    return dict(judged, consumer='metal_layer_density_check.check',
                generic_bounds={'minimum': None, 'maximum': None},
                report_sha256=digest(report), subject_sha256=sha,
                measurement_scope='whole-die extent', region_um=region,
                denominator_um2=area, executed_rules=sorted(executed),
                layer_rules=rules, layer_gds_map={r: required[r]['layers'] for r in required})


def _current_stage(project: Path, state: Path, step: str) -> tuple[dict, dict]:
    """Check the existing native packet against its current material inputs."""
    import librelane_signoff_evidence as native
    folder = state.resolve().parent
    if state.name != 'state_out.json' or not folder.is_relative_to(
            (project / 'phase3/librelane').resolve()) or 'attempts' in folder.parts:
        raise Refusal('LL_FINISHING_WRONG_STAGE', str(state))
    receipt = validate_step_receipt(folder, step)
    fp = receipt['input']
    image = _record_provider_binding(project, fp)
    switch_path = project / 'phase3/librelane_switch.json'
    switch = _load(switch_path) if switch_path.is_file() else {}
    mounts = native._pdk_mounts(project, switch, folder, image)
    config = project / 'phase3/librelane' / CONFIG_FOLDER / f'{step}.json'
    before = _load(folder / 'state_in.json')
    raw = _load(config)
    if (fp.get('image') != image or fp.get('config') != digest(config)
            or raw.get('meta', {}).get('step') != step
            or fp.get('config_files') != config_file_hashes(raw, mounts)
            or fp.get('state_files') != {str(p): digest(p) for p in _walk_input_views(before)}):
        raise Refusal('LL_FINISHING_INPUT_CHANGED', str(state))
    candidates = (project / 'phase3/librelane').rglob('*.json')
    if not any(p.name.endswith(('state.json', 'state_in.json', 'state_out.json'))
               and digest(p) == fp.get('state') for p in candidates):
        raise Refusal('LL_FINISHING_INPUT_STATE_MISSING', f"{project / 'phase3/librelane'}: recursive *.json search for state.json/state_in.json/state_out.json found no file with input.state={fp.get('state')!r}; consuming {state}")
    return before, _load(state)


def _retained_stream_step(record: dict) -> str:
    """An old self-consistent receipt cannot certify a lossy FILLS stream."""
    from librelane_fill_stream import fill_records
    step = record.get('stream_step', 'KLayout.StreamOut')
    if step not in ('KLayout.StreamOut', FILL_STREAM_STEP):
        raise Refusal('LL_STREAM_STEP_UNSUPPORTED', str(step))
    if fill_records(Path(record['filled_def']))['shapes'] and step != FILL_STREAM_STEP:
        raise Refusal('LL_FILL_STREAM_LEGACY_LOSSY_RECEIPT', str(record['filled_def']))
    return step


def validate_default_stream(project: Path) -> dict:
    """Bind the filled DEF, actual stream/filler, density and both publications.

    Called by the existing Step-34 gate and Step-35 CMP reader. A valid scalar
    density result from a different stream cannot replace this chain.
    """
    validate_fill_consumption(project)
    doc = _load(project / RECORD_REL)
    record = doc['default_stream']
    if _load(project / DEFAULT_STREAM_REL) != record:
        raise Refusal('LL_FINISHING_PROMOTION_CHANGED', DEFAULT_STREAM_REL)
    stream_step = _retained_stream_step(record)
    stream_fp = validate_step_receipt(
        Path(record['stream_state']).parent, stream_step)['input']
    if (record.get('image') != stream_fp.get('image')
            or record.get('image') != _record_provider_binding(project, stream_fp)):
        raise Refusal('LL_FINISHING_IMAGE_CHANGED', str(record.get('image')))
    gates = record['gates']
    if set(gates) != {'substance', 'port_labels'} or any(
            row.get('rc') != 0 or digest(Path(row['report'])) != row.get('sha256')
            or _load(Path(row['report'])).get('verdict') != 'PASS' for row in gates.values()):
        raise Refusal('LL_FINISHING_OUTPUT_GATE_CHANGED', str(gates))
    for key in ('filled_def', 'stream', 'sealed', 'prefill', 'source', 'pnr_gds', 'canonical'):
        path, sha = Path(record[key]), record[key + '_sha256']
        if not re.fullmatch('[0-9a-f]{64}', str(sha)) or digest(path) != sha:
            raise Refusal('LL_FINISHING_BYTES_CHANGED', key)
    pnr = project / 'phase3/stage3/pnr'
    filled = pnr / 'filled.def'
    top = record['file_top']
    if (Path(record['filled_def']).resolve() != filled.resolve()
            or record['filled_def_sha256'] != doc['odb']['tool']['filled_def_sha256']
            or Path(record['pnr_gds']).resolve() != (pnr / f'{top}.gds').resolve()
            or Path(record['canonical']).resolve() !=
            (project / 'phase3/stage4/gds' / f'{top}.gds').resolve()):
        raise Refusal('LL_FINISHING_WRONG_PUBLICATION', str(record))
    stream_state = Path(record['stream_state'])
    if digest(stream_state) != record['stream_state_sha256']:
        raise Refusal('LL_FINISHING_STATE_CHANGED', str(stream_state))
    before, after = _current_stage(project, stream_state, stream_step)
    config = _load(project / 'phase3/librelane' / CONFIG_FOLDER / (stream_step + '.json'))
    if (Path(before['def']).resolve() != filled.resolve()
            or _def_design_name(filled) != config.get('DESIGN_NAME')
            or config.get('DESIGN_NAME') != record['design_name']
            or Path(after['klayout_gds']).resolve() != Path(record['stream']).resolve()):
        raise Refusal('LL_FILLED_DEF_GDS_MISMATCH', str(stream_state))
    arm = doc['gds']['librelane']
    filler = arm['filler']
    filler_state = Path(filler['state'])
    if digest(filler_state) != filler['state_sha256']:
        raise Refusal('LL_FILLER_STATE_CHANGED', str(filler_state))
    fin, fout = _current_stage(project, filler_state, 'KLayout.Filler')
    if (Path(fin['gds']).resolve() != Path(record['prefill']).resolve()
            or record['prefill_sha256'] != record['sealed_sha256']
            or digest(Path(fin['gds'])) != filler['gds_in_sha256']
            or Path(fout['gds']).resolve() != Path(filler['filled_gds']).resolve()
            or digest(Path(fout['gds'])) != filler['filled_sha256']
            or doc['gds'].get('shipped') != 'librelane'
            or doc['gds'].get('shipped_sha256') != record['source_sha256']
            or record['source_sha256'] != arm['subject_sha256']
            or record['source_sha256'] != record['canonical_sha256']
            or record['source_sha256'] != record['pnr_gds_sha256']):
        raise Refusal('LL_FILLER_GDS_NOT_CONSUMED', str(filler_state))
    topup = arm.get('density_topup')
    if topup:
        for key in ('gds', 'config', 'report'):
            if digest(Path(topup[key])) != topup[key + '_sha256']:
                raise Refusal('LL_DENSITY_TOPUP_CHANGED', key)
        if topup['input_sha256'] != filler['filled_sha256']:
            raise Refusal('LL_DENSITY_TOPUP_WRONG_INPUT', str(topup))
    elif arm['subject_sha256'] != filler['filled_sha256']:
        raise Refusal('LL_DENSITY_NOT_FILLED_SUBJECT', str(arm))
    if record.get('finishing_status') == 'NOT_APPLICABLE':
        import _flow_yaml
        import flow_compliance_check as compliance
        row = next(row for row in _flow_yaml.load()['steps'] if str(row['id']) == '26.5ic')
        if (not compliance._delivery_declares_absence(project, row['condition']['delivery_declares'])
                or record['sealed_sha256'] != record['stream_sha256']):
            raise Refusal('LL_FINISHING_WRONG_APPLICABILITY', str(record))
    else:
        import die_finishing_check
        report = Path(record['finishing_report'])
        finishing = die_finishing_check._unwrap(_load(report))
        if (report.resolve() != (project / 'reports/phase3/die_finishing.json').resolve()
                or digest(report) != record['finishing_report_sha256']
                or record['finishing_stream_sha256'] != record['stream_sha256']
                or not finishing):
            raise Refusal('LL_SEAL_WRONG_STREAM', str(finishing))
        seal = finishing.get('seal_ring') or {}
        if (seal.get('state') != 'PASS'
                or seal.get('consumed_into') != str(Path(record['sealed']).relative_to(project))
                or seal.get('staged_sha256') != record['sealed_sha256']):
            raise Refusal('LL_SEAL_NOT_CONSUMED', str(seal))
    import _stream_input_record as sir
    inputs = sir.record_path(pnr / f'{top}.gds')
    if digest(inputs) != record['stream_inputs_sha256']:
        raise Refusal('LL_STREAM_INPUTS_CHANGED', str(inputs))
    readset, why = sir.read(inputs)
    if (readset is None or readset['engine'] != 'klayout'
            or readset['def'] != {'project_rel': str(filled.relative_to(project)),
                                  'sha256': digest(filled)}
            or readset['recipe']['sha256'] != digest(project / readset['recipe']['project_rel'])):
        raise Refusal('LL_STREAM_READSET_CHANGED', why or str(inputs))
    cli = readset.get('native_cli') or {}
    commands = Path(cli.get('commands') or '')
    argv = cli.get('argv') or []
    if (not commands.is_file() or digest(commands) != cli.get('commands_sha256')
            or argv not in [shlex.split(line) for line in commands.read_text().splitlines() if line.strip()]
            or len(argv) < 3 or Path(argv[2]).resolve() != filled.resolve()
            or not cli.get('inputs')):
        raise Refusal('LL_STREAM_COMMAND_UNBOUND', str(cli))
    native_receipt = validate_step_receipt(stream_state.parent, stream_step)
    if stream_step == FILL_STREAM_STEP:
        from librelane_fill_stream import validate_native_stage
        validate_native_stage(stream_state.parent, Path(record['filled_def']), Path(record['stream']))
        _validate_fill_stream_authority(project, record)
    # _current_stage already re-hashed these guest-side configuration paths
    # through its declared mounts; the CLI must name exactly those materials.
    for entry in cli['inputs']:
        if (not entry.get('sha256') or entry['argv_index'] >= len(argv)
                or argv[entry['argv_index']] != entry['path']
                or native_receipt['input']['config_files'].get(entry['path']) != entry['sha256']):
            raise Refusal('LL_STREAM_NATIVE_MATERIAL_CHANGED', entry['path'])
    current = validate_density_result(project, arm, layout=Path(record['canonical']))
    if current.get('value') != _count(arm.get(DENSITY_METRIC)) or current.get('value') == 'NOT_MEASURED':
        raise Refusal('LL_FINISHING_DENSITY_NOT_MEASURED', str(current))
    return record


def _default_stream_recipe(project: Path, image: str, root: Path,
                           step: str = 'KLayout.StreamOut') -> tuple[Path, str]:
    """Retain the actual image's native recipe before starting stream-out."""
    if step == FILL_STREAM_STEP:
        source = Path(__file__).parent / 'librelane_fill_stream_native.py'
        recipe = project / 'phase3/stage3/pnr/stream_out.py'
        recipe.write_bytes(source.read_bytes())
        return recipe, str(source.resolve())
    probe = ('import json; from pathlib import Path; '
             'from librelane.common import get_script_dir; '
             'p=Path(get_script_dir())/"klayout/stream_out.py"; '
             'print(json.dumps({"path":str(p),"text":p.read_text()}))')
    cp = run_container(['docker', 'run', '--rm', *_dmem.docker_memory_flags(),
                        image, '--skip', 'python3', '-c', probe],
                       probe_deadline_s=PROBE_DEADLINE_S)
    if cp.returncode:
        raise Refusal('LL_STREAM_RECIPE_UNAVAILABLE', cp.stderr)
    source = json.loads(cp.stdout)
    recipe = project / 'phase3/stage3/pnr/stream_out.py'
    recipe.write_text(source['text'])
    if not recipe.stat().st_size or not Path(source['path']).is_absolute():
        raise Refusal('LL_STREAM_RECIPE_INVALID', str(source))
    return recipe, source['path']


def _default_stream_inputs(project: Path, top: str, folder: Path, image: str,
                           root: Path, pdk: str, recipe: Path, native_script: str,
                           filled: Path, stream: Path) -> dict:
    """Bind the native COMMANDS readset, without reconstructing it from config."""
    import _stream_input_record as sir
    commands = [shlex.split(line) for line in (folder / 'COMMANDS').read_text().splitlines()
                if line.strip()]
    calls = [argv for argv in commands if len(argv) > 2 and argv[1] == native_script
             and Path(argv[2]).resolve() == filled.resolve()]
    if len(calls) != 1:
        raise Refusal('LL_STREAM_COMMAND_UNBOUND', str(commands))
    argv = calls[0]
    if Path(argv[2]).resolve() != filled.resolve():
        raise Refusal('LL_STREAM_DEF_UNBOUND', str(argv))
    file_flags = {'--input-lef', '--with-gds-file', '--lyp', '--lyt', '--lym', '--seal-gds-file'}
    value_flags = file_flags | {'--output', '--top', '--conflict-resolution'}
    paths = []
    scalars = {}
    for i in range(3, len(argv), 2):
        if i + 1 >= len(argv) or argv[i] not in value_flags:
            raise Refusal('LL_STREAM_COMMAND_UNSUPPORTED', str(argv[i:]))
        flag, value = argv[i:i + 2]
        if flag in file_flags:
            paths.append((i + 1, value))
        else:
            scalars[flag] = value
    if (scalars.get('--top') != _def_design_name(filled)
            or Path(scalars.get('--output', '')).resolve() != stream.resolve()
            or not all(any(argv[i] == flag for i in range(3, len(argv), 2))
                       for flag in ('--input-lef', '--lyt', '--lyp', '--lym'))):
        raise Refusal('LL_STREAM_READSET_INCOMPLETE', str(argv))
    probe = ('import hashlib,json,sys; from pathlib import Path; '
             'print(json.dumps({p:hashlib.sha256(Path(p).read_bytes()).hexdigest() '
             'for p in json.loads(sys.argv[1])}))')
    cp = run_container(['docker', 'run', '--rm', *_dmem.docker_memory_flags(),
                        '-v', f'{project}:{project}:ro', '-v', f'{root}:/pdk:ro',
                        '-v', f'{Path(__file__).parent}:{Path(__file__).parent}:ro',
                        image, '--skip', 'python3', '-c', probe,
                        json.dumps([native_script, *[p for _, p in paths]])],
                       probe_deadline_s=PROBE_DEADLINE_S)
    if cp.returncode:
        raise Refusal('LL_STREAM_INPUT_UNREADABLE', cp.stderr)
    hashes = json.loads(cp.stdout)
    if hashes.get(native_script) != digest(recipe):
        raise Refusal('LL_STREAM_RECIPE_CHANGED', native_script)
    record = sir.build(engine='klayout', output=stream, top=top,
                       project=project, project_c=str(project), recipe=recipe,
                       def_file=filled, files={}, scalars={}, rcfile=None, hashes={})
    record['native_cli'] = {'argv': argv, 'commands': str(folder / 'COMMANDS'),
                            'commands_sha256': digest(folder / 'COMMANDS'),
                            'inputs': [dict(sir._entry(path, str(project), hashes), argv_index=i)
                                       for i, path in paths]}
    sir.write(project / 'phase3/stage3/pnr' / f'{top}.gds', record)
    return record


def _select_fill_stream(project: Path, image: str, root: Path, pdk: str,
                        filled: Path, configs: dict) -> tuple[str, dict]:
    """Choose the explicit native fill producer only when actual FILLS exist."""
    from librelane_fill_stream import fill_records, derive_map, _record
    if not fill_records(filled)['shapes']:
        return 'KLayout.StreamOut', configs
    cfg = _load(configs['KLayout.StreamOut'])
    base = _host_pdk_path(cfg['KLAYOUT_DEF_LAYER_MAP'], root, pdk)
    target = project / 'phase3/librelane' / CONFIG_FOLDER / 'explicit-fill.map'
    rules = None
    receipt_ref = None
    try:
        derive_map(base, None, filled, target)
    except Refusal as exc:
        if exc.code != 'FILL_STREAM_RULE_AUTHORITY_ABSENT':
            raise
        # A genuine D62 producer receipt binds the actual rules AND this DEF.
        # An arbitrary manifest claiming a rule path is insufficient authority.
        import flow109_density_fill as density
        from librelane_fill_stream import _bound
        component = _load(project / 'reports/flow109/components/D62.json')
        receipt_ref = _record(project, project / component['receipt']['path'])
        density.validate_filled_odb(project, receipt_ref)
        receipt = _load(_bound(project, receipt_ref))
        if receipt['outputs']['filled.def']['sha256'] != digest(filled):
            raise Refusal('LL_FILL_STREAM_WRONG_D62_SUBJECT', str(filled))
        rules = _bound(project, receipt['inputs']['rules'])
        derive_map(base, rules, filled, target)
    authority = {'base_map': str(base), 'base_map_sha256': digest(base),
                 'rules': str(rules) if rules else None,
                 'rules_sha256': digest(rules) if rules else None,
                 'derived_map': str(target), 'derived_map_sha256': digest(target),
                 'filled_def_sha256': digest(filled), 'd62_receipt': receipt_ref}
    write_json(target.with_suffix('.authority.json'), authority)
    selected = resolve_step_configs(project, image, pdk, [FILL_STREAM_STEP],
        pdk_root=root, folder=CONFIG_FOLDER,
        overlay={'KLAYOUT_DEF_LAYER_MAP': (str(target), 'verified DEF FILL layer purposes')})
    return FILL_STREAM_STEP, selected


def _validate_fill_stream_authority(project: Path, record: dict) -> None:
    """A derived map does not sever its PDK/rule/producer source identity."""
    import tempfile
    from librelane_fill_stream import derive_map
    path = Path(record['fill_mapping_authority'])
    if digest(path) != record['fill_mapping_authority_sha256']:
        raise Refusal('LL_FILL_STREAM_AUTHORITY_CHANGED', str(path))
    authority = _load(path)
    for key in ('base_map', 'rules', 'derived_map'):
        if authority.get(key) is not None and digest(Path(authority[key])) != authority.get(key + '_sha256'):
            raise Refusal('LL_FILL_STREAM_AUTHORITY_CHANGED', key)
    filled = Path(record['filled_def'])
    if authority.get('filled_def_sha256') != digest(filled):
        raise Refusal('LL_FILL_STREAM_WRONG_D62_SUBJECT', str(filled))
    if authority.get('d62_receipt') is not None:
        import flow109_density_fill as density
        density.validate_filled_odb(project, authority['d62_receipt'])
    with tempfile.TemporaryDirectory(prefix='fill-map-proof-') as tmp:
        derived = Path(tmp) / 'fill.map'
        derive_map(Path(authority['base_map']), Path(authority['rules']) if authority.get('rules') else None,
                   filled, derived)
        if digest(derived) != authority['derived_map_sha256']:
            raise Refusal('LL_FILL_STREAM_AUTHORITY_CHANGED', 'derived mapping recipe')


@_spf.retained_step('37')
def default_stream(project: Path, top: str, pdk: Any, container: str) -> dict:
    """One Default KLayout stream of the current filled DEF, then real fill.

    This is the ordinary runner's primary route, without a Step-37 mode
    switch. The older multi-engine tool arm remains an explicit diagnostic.
    Signoff, whole-IC admission and shipping are separate obligations.
    """
    import phase3_one_shot_runner as runner
    import librelane_contract as contract
    project = project.resolve()
    # Adopt a retained current primary result before starting another producer.
    # Every ordinary consumer still rechecks its bytes and runs the per-layer
    # judge; the receipt alone is never sufficient for reuse.
    reuse_refusal = None
    if (project / DEFAULT_STREAM_REL).is_file():
        try:
            record = validate_default_stream(project)
            if record['file_top'] != top or record.get('pdk') != pdk.name:
                raise Refusal('LL_FINISHING_WRONG_DECLARATION', str(record))
            arm = _load(project / RECORD_REL)['gds']['librelane']
            judged = current_metal_density(project, arm, record)
            if arm.get(DENSITY_METRIC) == 0 and judged.get('verdict') == 'PASS':
                runner._step37_declare_streamout_gds_provenance(
                    project, top, default_finishing=True)
                return dict(record, receipt=str(project / DEFAULT_STREAM_REL))
            reuse_refusal = 'retained density consumer did not pass: ' + str(judged)
        except (Refusal, OSError, ValueError, KeyError, TypeError) as exc:
            reuse_refusal = f'{type(exc).__name__}: {exc}'
        # Keep the old promotion and its actual cited source closure in the
        # existing step-version snapshot before a new epoch changes any byte.
        import step_output_collector as versions
        pending = [project / DEFAULT_STREAM_REL, project / RECORD_REL,
                   project / f'phase3/stage3/pnr/{top}.stream_inputs.json',
                   project / 'reports/phase3/die_finishing.json']
        retained = set()
        while pending:
            path = pending.pop().resolve()
            try:
                present = path.is_file()
            except OSError:
                present = False
            if path in retained or not path.is_relative_to(project) or not present:
                continue
            retained.add(path)
            if path.name == 'state_out.json':
                pending.extend(path.parent / name for name in
                               ('vibeic_receipt.json', 'input_fingerprint.json', 'COMMANDS', 'invocation.log'))
            if path.suffix != '.json':
                continue
            try:
                doc = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            def cite(node):
                if isinstance(node, dict):
                    for value in node.values():
                        cite(value)
                elif isinstance(node, list):
                    for value in node:
                        cite(value)
                elif isinstance(node, str):
                    pending.append(Path(node) if Path(node).is_absolute() else project / node)
            cite(doc)
            if path.name == 'vibeic_receipt.json':
                pending.extend(path.parent / name for name in doc.get('sha256', {}))
        versions.retain_before(project, '37', sorted(retained))
    pnr = project / 'phase3/stage3/pnr'
    filled = pnr / 'filled.def'
    try:
        validate_fill_consumption(project)
    except (Refusal, OSError, ValueError, KeyError):
        notes = []
        if not runner._emit_metal_fill(project, top, pdk, container, filled, notes):
            raise Refusal('LL_FILL_ODB_NOT_READY', '; '.join(notes))
        validate_fill_consumption(project)
    image, root = runner._librelane_step_ctx(project, '34', pdk.name)
    configs = resolve_step_configs(project, image, pdk.name, ['KLayout.StreamOut'],
                                   pdk_root=root, folder=CONFIG_FOLDER)
    stream_step, configs = _select_fill_stream(project, image, root, pdk.name, filled, configs)
    odb = _load(project / RECORD_REL)['odb']['tool']
    state = _load(Path(odb['state']))
    state['def'] = str(filled)
    initial = project / 'phase3/librelane/37-default-state.json'
    write_json(initial, state)
    recipe, native_script = (_default_stream_recipe(project, image, root) if stream_step == 'KLayout.StreamOut'
                             else _default_stream_recipe(project, image, root, stream_step))
    folder = run_chain(project, image, [(stream_step, configs[stream_step], initial)],
                       mounts=_mounts(root, pdk.name), lane='37-default-stream',
                       pdk_root=PDK_GUEST_ROOT)[0]
    before, after = _current_stage(project, folder / 'state_out.json', stream_step)
    stream = Path(after['klayout_gds'])
    _default_stream_inputs(project, top, folder, image, root, pdk.name,
                           recipe, native_script, filled, stream)
    boundary = pnr / f'{top}.prefinish.gds'
    shutil.copyfile(stream, boundary)
    write_json(boundary.with_suffix('.gds.receipt.json'), {
        'program': 'phase3_one_shot_runner', 'artefact': boundary.name,
        'sha256': digest(boundary), 'size': boundary.stat().st_size,
        'mtime_ns': boundary.stat().st_mtime_ns, 'top': top,
        'streamed_from_def': filled.name, 'def_sha256': digest(filled),
        'engine': 'klayout'})
    pnr_gds = pnr / f'{top}.gds'
    # The raw native stream is immutable. Seal exactly once on a separate
    # subject; its retained consumer runs before any filler touches the die.
    sealed = project / 'phase3/tool_arms/26.5ic/default-stream/sealed.gds'
    sealed.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(stream, sealed)
    finishing = runner._die_finishing_record(project, top, pdk, sealed, container)
    if finishing.status not in ('PASS', 'NOT_APPLICABLE'):
        raise Refusal('LL_DIE_FINISHING_REFUSED', finishing.detail)
    shutil.copyfile(sealed, pnr_gds)
    ctx = runner._step34_gds_tool_arm(project, pdk, pnr_gds)
    if ctx is None:
        raise Refusal('LL_FILL_GDS_NOT_RUN', 'Default finishing requires the primary fill arm')
    ok, note = runner._step34_gds_ship(project, pnr_gds, ctx, (False, 'direct arm not run'))
    if not ok:
        raise Refusal('LL_FILL_GDS_REFUSED', note)
    arm = ctx['tool']
    canonical = project / 'phase3/stage4/gds' / f'{top}.gds'
    canonical.parent.mkdir(parents=True, exist_ok=True)
    # Existing output gates judge the actual filled subject, before promotion.
    from librelane_step37 import _vibeic_gds_gates
    gates = _vibeic_gds_gates(project, image, root, pdk.name, pnr_gds, filled,
                             'default', configs[stream_step])
    if any(row['rc'] != 0 or not row['sha256'] for row in gates.values()):
        raise Refusal('LL_FINISHED_GDS_GATE_FAILED', str(gates))
    shutil.copyfile(pnr_gds, canonical)
    record = {'file_top': top, 'design_name': _def_design_name(filled),
              'stream_step': stream_step,
              'image': image, 'pdk': pdk.name, 'gates': gates,
              'prior_promotion_refusal': reuse_refusal,
              'finishing_status': finishing.status,
              'finishing_stream_sha256': digest(stream),
              'stream_inputs_sha256': digest(pnr / f'{top}.stream_inputs.json'),
              'stream_state': str(folder / 'state_out.json'),
              'stream_state_sha256': digest(folder / 'state_out.json')}
    for key, path in {'filled_def': filled, 'stream': stream, 'sealed': sealed,
                      'prefill': project / 'phase3/tool_arms/34/prefill.gds',
                      'source': Path(arm['subject']), 'pnr_gds': pnr_gds,
                      'canonical': canonical}.items():
        record[key], record[key + '_sha256'] = str(path), digest(path)
    if stream_step == FILL_STREAM_STEP:
        authority = project / 'phase3/librelane' / CONFIG_FOLDER / 'explicit-fill.authority.json'
        record.update(fill_mapping_authority=str(authority),
                      fill_mapping_authority_sha256=digest(authority))
    if finishing.status == 'PASS':
        report = project / 'reports/phase3/die_finishing.json'
        record.update(finishing_report=str(report), finishing_report_sha256=digest(report))
    write_json(project / DEFAULT_STREAM_REL, record)
    update_record(project, 'default_stream', record)
    publish_metal_density(project, arm.get('ratios') or {}, canonical, pdk.name)
    validate_default_stream(project)
    per_layer = current_metal_density(project, arm, record)
    if per_layer.get('verdict') != 'PASS':
        raise Refusal('LL_METAL_DENSITY_CONSUMER_FAILED', str(per_layer))
    # Keep the engine-neutral transcript on the canonical caller boundary.
    shutil.copyfile(folder / 'invocation.log', pnr / 'stream_out.log')
    runner._step37_declare_streamout_gds_provenance(
        project, top, default_finishing=True)
    return dict(record, receipt=str(project / DEFAULT_STREAM_REL))


STEP37_PROMOTION_REL = 'phase3/librelane/37-promotion.json'


def validate_density_result(project: Path, arm: dict, *, layout: Path | None = None) -> dict:
    """Bind a density result before publication and at its existing consumers."""
    try:
        state = Path(arm['state'])
        subject = Path(arm['subject'])
        if digest(state) != arm['state_sha256'] or digest(subject) != arm['subject_sha256']:
            raise ValueError('density state or measured stream changed')
        row = _current_density_row(project, state, CONFIG_FOLDER, layout=layout)
        import librelane_signoff_evidence as native
        receipt = validate_step_receipt(state.parent, 'KLayout.Density')
        switch_path = project / 'phase3/librelane_switch.json'
        switch = _load(switch_path) if switch_path.is_file() else {}
        mounts = native._pdk_mounts(project, switch, state.parent, resolve_image(project, record=False))
        config = _load(project / 'phase3/librelane' / CONFIG_FOLDER / 'KLayout.Density.json')
        if receipt['input'].get('config_files') != config_file_hashes(config, mounts):
            raise ValueError('density PDK material population changed')
        if row.get('value') != _count(arm.get(DENSITY_METRIC)):
            raise ValueError(row.get('reason') or 'density record differs from tool output')
        return row
    except (OSError, ValueError, TypeError, KeyError, Refusal) as exc:
        return {'value': 'NOT_MEASURED', 'reason': str(exc)}


def _current_density_row(project: Path, state: Path, config_folder: str, *,
                         layout: Path | None = None) -> dict:
    """Reuse the current native signoff reader at the fill/DFM boundary."""
    try:
        import librelane_signoff_evidence as native
        folder = state.resolve().parent
        if not folder.is_relative_to((project / 'phase3/librelane').resolve()) \
                or 'attempts' in folder.relative_to(project.resolve()).parts \
                or state.name != 'state_out.json':
            raise ValueError('wrong density producer stage/path')
        validate_step_receipt(state.parent, 'KLayout.Density')
        return native.count_row(project, state.parent, 'KLayout.Density', DENSITY_METRIC,
                                layout if layout is not None else native.finished_layout(project),
                                project / 'phase3/librelane' / config_folder)
    except (OSError, ValueError, TypeError, KeyError, Refusal) as exc:
        return {'value': 'NOT_MEASURED', 'reason': str(exc)}


def step37_density(project: Path) -> Optional[Dict[str, Any]]:
    """When step 37 streamed on the tool, its own SealRing -> Filler ->
    Density chain is step 34's GDS half: the density judgement of the stream
    it promoted (`librelane_step37`'s `37-<arm>-density.json`), its state
    re-hashed.  None when step 37 promoted nothing."""
    promo = project / STEP37_PROMOTION_REL
    if not promo.is_file():
        return None
    try:
        arm = _load(promo).get('selection')
        report = project / 'phase3/librelane' / f'37-{arm}-density.json'
        judged = _load(report)
    except (OSError, ValueError, Refusal):
        return {'status': 'UNREADABLE', 'source': STEP37_PROMOTION_REL}
    state = Path(str(judged.get('source') or ''))
    if not state.is_file() or digest(state) != (judged.get('sha256') or {}).get('state_out.json'):
        return {'status': 'STALE', 'source': str(report.relative_to(project)), 'state': str(state)}
    row = (judged.get('metrics') or {}).get(DENSITY_METRIC) or {}
    count = _count(row.get('value')) if row.get('status') in ('MEASURED', 'FAIL') else None
    if count is None:
        return {'status': 'NOT_MEASURED', 'source': str(report.relative_to(project))}
    current = _current_density_row(project, state, '37-config')
    if current.get('value') != count or current.get('value') == 'NOT_MEASURED':
        return {'status': 'NOT_MEASURED', 'source': str(report.relative_to(project)),
                'reason': current.get('reason') or 'density judgment differs from tool output'}
    return {'status': 'MEASURED', 'errors': count, 'arm': f'step37:{arm}', 'rules': None,
            'source': str(report.relative_to(project)), 'state': str(state),
            'state_sha256': digest(state)}


def router_via_counts(metrics: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """The detailed router's own via counts from an OpenROAD `-metrics` JSON
    (`detailedroute__route__vias__*`) or a LibreLane state (`route__vias__*`)."""
    for prefix in ('route__vias', 'detailedroute__route__vias'):
        single = _count(metrics.get(f'{prefix}__singlecut'))
        multi = _count(metrics.get(f'{prefix}__multicut'))
        if single is not None and multi is not None:
            return {'singlecut': single, 'multicut': multi, 'key_prefix': prefix}
    return None


def via_agreement(def_single: int, def_resolved: int,
                  router: Optional[Dict[str, int]]) -> Dict[str, Any]:
    """The DEF recount against the router's own counts.

    The same route must give the same numbers: equal totals and an equal
    single-cut count AGREE, anything else on equal totals DISAGREE.  Unequal
    totals mean the two describe different routes (a post-route repair
    re-routed after the router wrote its metrics): SCOPE_DIFFERS, and neither
    number is used to excuse the other."""
    if not router:
        return {'verdict': 'NOT_MEASURED', 'reason': 'no router via metrics in this run'}
    total = router['singlecut'] + router['multicut']
    out = {'def': {'singlecut': def_single, 'resolved': def_resolved},
           'router': dict(router), 'router_total': total}
    if total != def_resolved:
        out['verdict'] = 'SCOPE_DIFFERS'
        out['reason'] = (f'the router counted {total} vias and the shipped DEF references '
                         f'{def_resolved}: the route changed after the router measured it')
    elif router['singlecut'] == def_single:
        out['verdict'] = 'AGREE'
    else:
        out['verdict'] = 'DISAGREE'
        out['reason'] = (f"router single-cut {router['singlecut']} != DEF recount "
                         f'{def_single} on the same {total} vias')
    return out
