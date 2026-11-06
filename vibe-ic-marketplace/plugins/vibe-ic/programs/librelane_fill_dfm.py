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

import vibeic_temp as _vtmp

import fnmatch
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402
import _docker_memory as _dmem
from metal_fill_config_gen import (build_metal_fill_config,
                                   density_rule_layer_identifiers)
import die_level_deck_rule_attribution as _dla
import librelane_contract as _lc
from librelane_contract import (PDK_GUEST_ROOT, Refusal, _load,  # noqa: E402
                                DECLARATION_REL, declaration_config, resolve_step_configs,
                                run_chain, select_arms,
                                state_from_direct, run_container,
                                settled_floorplan_geometry, native_tool_command,
                                _def_design_name)

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
           'subject': str(gds),
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
                         'gds_in': str(gds),
                         'filled_gds': str(filled)}
        out['subject'] = str(filled)
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
    local = isinstance(image, _lc.LocalRuntime) or _lc._provider_route(project)
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
    cmd = ['docker', 'run', *_vtmp.docker_mounts(), '--rm', '--network', network,
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
                'source': str(target),
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
        'source': placed['source'],
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
    cmd = ['docker', 'run', *_vtmp.docker_mounts(), '--rm', *_dmem.docker_memory_flags(),
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
    if out.read_bytes() == gds.read_bytes():
        raise Refusal('LL_DENSITY_FILL_NO_CHANGE', str(report))
    return {'gds': str(out), 'report': str(report), 'config': str(config_path),
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
    cmd = ['docker', 'run', *_vtmp.docker_mounts(), '--rm', *_dmem.docker_memory_flags(),
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
            set(measured.get('layers') or {}) != set(specs) or
            any(not isinstance(row.get('ratio'), (int, float)) or
                isinstance(row.get('ratio'), bool) or
                not 0 <= row['ratio'] <= 1 for row in measured['layers'].values())):
        raise Refusal('LL_DENSITY_RATIOS_NOT_MEASURED', str(report))
    return {'report': str(report), 'subject': str(gds),
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
    """Publish measured metal ratios for the actual native GDS subject.

    Conflicting measurements for one metal layer remain unmeasured.
    """
    import metal_layer_density_check as _mld
    gds = Path(gds)
    out = project / METAL_DENSITY_REL

    def declined() -> None:
        out.unlink(missing_ok=True)
        return None

    subject = Path(str(ratios.get('subject') or ''))
    if (not gds.is_file() or not subject.is_file()
            or subject.read_bytes() != gds.read_bytes()):
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
        'pdk': pdk, 'gds': gds_record,
        'die_area_um2': die_area, 'layers': layers, 'layer_rules': rules,
        'source': {'report': str(report)}})
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
                 'subject': str(routed_def),
              'filled_def': str(filled),
              'patterns': patterns, 'census': census, 'occupancy': occupancy,
              'metrics': {k: v for k, v in _metrics(folder).items()
                          if k.startswith('design__instance__count')},
              'supply_ownership': {k: ownership.get(k) for k in
                                   ('verdict', 'code', 'reason', 'instances',
                                    'supply_pins_checked', 'off_supply_pins')},
              'refusals': [],
              'binding': {'config': str(configs[ODB_FILL_STEP]),
                          'input_state': str(state),
                          'mounts': [[str(host), guest] for host, guest in mounts]}}
    name = config.get('DESIGN_NAME')
    if not name or any(_def_design_name(path) != name for path in (Path(routed_def), filled)):
        raise Refusal('LL_FILL_WRONG_DESIGN', str(filled))
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








def validate_fill_consumption(project: Path) -> None:
    """Read the native fill State and the actual DEF consumed downstream."""
    import _path_layout as pl
    doc = _load(project / RECORD_REL)['odb']
    if doc.get('shipped') != 'librelane':
        raise Refusal('LL_FILL_NOT_CONSUMED', 'no tool DEF shipped')
    tool = doc['tool']
    state = _lc.project_path(project, tool['state'])
    before = _load(state.parent / 'state_in.json')
    after = _load(state)
    config = _load(state.parent / 'config.json')
    routed = pl.pnr_dir(project) / 'routed.def'
    subject = _lc.project_path(project, before['def'])
    output = _lc.project_path(project, after['def'])
    destination = pl.pnr_dir(project) / 'filled.def'
    if not subject.is_file() or subject.read_bytes() != routed.read_bytes():
        raise Refusal('LL_FILL_WRONG_SUBJECT', str(subject))
    if (config.get('meta', {}).get('step') != ODB_FILL_STEP
            or not config.get('DESIGN_NAME')
            or any(_def_design_name(path) != config['DESIGN_NAME'] for path in (subject, output))):
        raise Refusal('LL_FILL_WRONG_DESIGN', str(output))
    if not output.is_file() or output.read_bytes() != destination.read_bytes():
        raise Refusal('LL_FILL_NOT_CONSUMED', 'filled.def differs from the native fill output')


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
               f"# state: {record.get('state')}\n")
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
    the DEF whose COMPONENTS hold their positions."""
    census = record.get('census') or {}
    return {'step': '34', 'producer': record.get('step'),
            'def': record.get('filled_def'),
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
                            'subject': (arm or {}).get('subject')})
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

    None when step 34 has no measured GDS arm. The native State supplies the
    count; a changed measured GDS needs a new run."""
    project = project.resolve()
    path = project / RECORD_REL
    if not path.is_file():
        return None
    try:
        doc = _load(path)
    except (OSError, ValueError, Refusal, KeyError, TypeError):
        return {'status': 'UNREADABLE', 'source': RECORD_REL}
    arms = doc.get('gds') or {}
    shipped = arms.get('shipped')
    arm = arms.get(shipped) if shipped else None
    if not isinstance(arm, dict):
        return step37_density(project) if not arms else None
    state = _lc.project_path(project, arm.get('state') or '')
    if not state.is_file():
        return {'status': 'STALE', 'source': RECORD_REL, 'state': str(state)}
    row = validate_density_result(project, arm)
    count = _count(row.get('value'))
    if count is None:
        return {'status': 'NOT_MEASURED', 'source': RECORD_REL,
                'reason': row.get('reason') or 'density record differs from tool output'}
    result = {'status': 'MEASURED', 'errors': count, 'arm': shipped,
            'rules': arm.get('rules'), 'runset': arm.get('runset'),
            'source': RECORD_REL, 'state': str(state)}
    result['per_layer'] = current_metal_density(project, arm)
    return result


def current_metal_density(project: Path, arm: dict) -> dict:
    """The PDK deck checks each density rule against its own original limit."""
    row = validate_density_result(project, arm)
    count = _count(row.get('value'))
    return {'verdict': 'NOT_MEASURED' if count is None else 'PASS' if count == 0 else 'FAIL',
            'errors': count, 'source': row.get('source'), 'reason': row.get('reason'),
            'consumer': 'KLayout.Density / Checker.KLayoutDensity'}


def _current_stage(project: Path, state: Path, step: str) -> tuple[dict, dict]:
    """Read the actual native configuration and input/output States."""
    state = _lc.project_path(project, state)
    config = _load(state.parent / 'config.json')
    if config.get('meta', {}).get('step') != step:
        raise Refusal('LL_NATIVE_STEP_MISMATCH', str(state.parent))
    before, after = _load(state.parent / 'state_in.json'), _load(state)
    if after.get('metrics', {}).get('flow__errors__count', 0):
        raise Refusal('LL_STEP_FAILED', step)
    return before, after



def validate_density_result(project: Path, arm: dict, *, layout: Path | None = None) -> dict:
    """Read the native PDK density count for the selected physical subject."""
    try:
        state = _lc.project_path(project, arm['state'])
        subject = _lc.project_path(project, arm['subject'])
        return _current_density_row(project, state, CONFIG_FOLDER,
                                    layout=layout if layout is not None else subject)
    except (OSError, ValueError, TypeError, KeyError, Refusal) as exc:
        return {'value': 'NOT_MEASURED', 'reason': str(exc)}


def _current_density_row(project: Path, state: Path, config_folder: str, *,
                         layout: Path | None = None) -> dict:
    """The native density State is shared by fill and the DFM consumer."""
    try:
        before, after = _current_stage(project, state, 'KLayout.Density')
        subject = _lc.project_path(project, before['gds'])
        if layout is not None and subject.read_bytes() != layout.read_bytes():
            raise ValueError('density measured a different GDS')
        value = _count(after.get('metrics', {}).get(DENSITY_METRIC))
        if value is None:
            raise ValueError('native density count absent')
        return {'value': value, 'status': 'MEASURED' if value == 0 else 'FAIL',
                'source': str(state), 'subject': str(subject)}
    except (OSError, ValueError, TypeError, KeyError, Refusal) as exc:
        return {'value': 'NOT_MEASURED', 'reason': str(exc)}


STEP37_PROMOTION_REL = 'phase3/librelane/37-promotion.json'


def step37_density(project: Path) -> Optional[Dict[str, Any]]:
    """When step 37 streamed on the tool, its own SealRing -> Filler ->
    Density chain is step 34's GDS half: the density judgement of the stream
    it promoted (`librelane_step37`'s `37-<arm>-density.json`).
    None when step 37 promoted nothing."""
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
    if not state.is_file():
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
            'source': str(report.relative_to(project)), 'state': str(state)}


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
