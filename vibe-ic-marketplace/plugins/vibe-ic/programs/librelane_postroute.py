#!/usr/bin/env python3
"""Steps 28, 29 and 33 read the post-route state the tool already produced.

T100 (steps 22/23) runs LibreLane `OpenROAD.STAPostPNR` for every STA corner
and records the step in `reports/phase3/sta_postpnr_signoff.json`. That step
writes, per corner, an SDF (`write_sdf -include_typ -divider . -corner <c>`)
and a `report_power -corner <c>` report. Steps 29 and 33 CONSUME that state;
they never re-run it:

* ``stapostpnr_state``: the recorded state, refused by name when step 23 did
  not run on the tool (`LL_STAPOSTPNR_STATE_ABSENT`) or when the state on disk
  is not the one step 23 recorded (`LL_STAPOSTPNR_STATE_DRIFT`).
* step 29: ``gate_level_sim`` runs the design's L10 suite against every corner
  SDF as the LibreLane custom step `Vibeic.GateLevelSim`, and
  ``sdf_gate_sim.judge_tool_arm`` judges it.
* step 33: the per-corner power is `_ppa.power.stapostpnr_corner_power`; this
  module only locates the state.
* step 28: ``tap_pitch`` reads `FP_TAPCELL_DIST` from a LibreLane-resolved step
  config (the PDK's own LibreLane declaration as the tool resolved it), and
  ``perc_tool_metrics`` reads antenna / PDN / IR metrics from the LibreLane
  step states the run holds. IR is a declared seam (`PERC_IR_TOOL_SEAM`)
  until step 24 lands on the tool.

chip-AGNOSTIC: no design, PDK or corner literal selects a branch.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402
from librelane_contract import (PDK_GUEST_ROOT, Refusal, _load, _state_step_id, digest,  # noqa: E402
                                resolve_step_configs, run_chain)

#: Where step 23 records the STAPostPNR run it signed off (T100).
STEP23_RECORD = 'reports/phase3/sta_postpnr_signoff.json'
GLS_STEP = 'Vibeic.GateLevelSim'


def stapostpnr_state(project: Path) -> Tuple[Path, dict]:
    """(step folder, state) of the STAPostPNR run step 23 recorded."""
    record = project / STEP23_RECORD
    if not record.is_file():
        raise Refusal('LL_STAPOSTPNR_STATE_ABSENT',
                      f'{record}: step 23 did not run on LibreLane')
    doc = _load(record)
    state_path = Path(str(doc.get('sta_state') or ''))
    if not state_path.is_file():
        raise Refusal('LL_STAPOSTPNR_STATE_ABSENT', f'{record}: sta_state {state_path}')
    if digest(state_path) != doc.get('sta_state_sha256'):
        raise Refusal('LL_STAPOSTPNR_STATE_DRIFT',
                      f'{state_path} is not the state step 23 recorded')
    if _state_step_id(state_path.parent) != 'OpenROAD.STAPostPNR':
        raise Refusal('LL_NOT_STAPOSTPNR', str(state_path.parent))
    return state_path.parent, _load(state_path)


def corner_sdfs(state: dict) -> Dict[str, Path]:
    """{corner: SDF} from the state; every named file must exist."""
    sdfs = state.get('sdf') or {}
    if not isinstance(sdfs, dict) or not sdfs:
        raise Refusal('LL_STAPOSTPNR_NO_SDF', 'the STAPostPNR state names no SDF')
    missing = [c for c, p in sdfs.items() if not Path(p).is_file()]
    if missing:
        raise Refusal('LL_STAPOSTPNR_SDF_MISSING', ', '.join(sorted(missing)))
    return {c: Path(p) for c, p in sdfs.items()}


_SDF_DESIGN = re.compile(r'\(\s*DESIGN\s+"([^"]+)"\s*\)')
_SDF_VERSION = re.compile(r'\(\s*SDFVERSION\s+"([^"]+)"\s*\)')
_SDF_TIMESCALE = re.compile(
    r'\(\s*TIMESCALE\s+(1|10|100)(?:\.0*)?\s*(s|ms|us|ns|ps|fs)\s*\)')
_VERILOG_MODULE = re.compile(
    r'(?m)^\s*module\s+(?:automatic\s+)?(?:\\([^\s]+)|([A-Za-z_$][\w$]*))')


def _balanced_sdf(text: str) -> bool:
    """Require one balanced S-expression while ignoring quoted parentheses."""
    depth = roots = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == '(':
            if depth == 0:
                roots += 1
            depth += 1
        elif char == ')':
            depth -= 1
            if depth < 0:
                return False
    return not quoted and depth == 0 and roots == 1


def sdf_export_census(path: Path, design: str) -> dict:
    """Read back one native SDF as structured producer output, not presence.

    D49 owns this export check. Simulator annotation and scenario execution
    remain D53's separate responsibility.
    """
    try:
        raw = Path(path).read_text(errors='strict')
    except (OSError, UnicodeError) as exc:
        raise Refusal('LL_STAPOSTPNR_SDF_INVALID', f'{path}: {exc}') from exc
    versions = _SDF_VERSION.findall(raw)
    designs = _SDF_DESIGN.findall(raw)
    timescales = _SDF_TIMESCALE.findall(raw)
    cells = len(re.findall(r'\(\s*CELL\s+\(', raw))
    delays = len(re.findall(r'\(\s*(?:INTERCONNECT|IOPATH)\b', raw))
    top_cell = re.search(
        r'\(\s*CELL\s+\(\s*CELLTYPE\s+"' + re.escape(design)
        + r'"\s*\)\s+\(\s*INSTANCE\s*\)', raw)
    if (not _balanced_sdf(raw) or versions != ['3.0'] or designs != [design]
            or len(timescales) != 1 or cells <= 0 or delays <= 0 or top_cell is None):
        raise Refusal('LL_STAPOSTPNR_SDF_INVALID',
                      f'{path}: malformed/incomplete SDF export for {design!r}')
    return {'path': str(Path(path).resolve()), 'sha256': digest(Path(path)),
            'design': design, 'version': versions[0],
            'timescale': ''.join(timescales[0]), 'cell_count': cells,
            'delay_record_count': delays}


def bind_stapostpnr_sdfs(folder: Path, state: dict, *,
                         required_items: Optional[List[dict]] = None,
                         expected_netlist: Optional[Path] = None) -> dict:
    """Bind complete native SDF exports to STAPostPNR's netlist and corners.

    This is the shared producer/consumer seam: D49 qualifies the export, and
    D53 calls the same function before launching ``Vibeic.GateLevelSim``.
    It intentionally proves no simulator annotation outcome.
    """
    from librelane_contract import validate_step_receipt
    folder = Path(folder).resolve()
    receipt = validate_step_receipt(folder, 'OpenROAD.STAPostPNR')
    try:
        disk_state = _load(folder / 'state_out.json')
        config = _load(folder / 'config.json')
        if state != disk_state:
            raise ValueError('caller state differs from current producer state')
        design = config.get('DESIGN_NAME')
        declared = config.get('STA_CORNERS')
        if (not isinstance(design, str) or not design
                or not isinstance(declared, list) or not declared
                or len(declared) != len(set(declared))
                or any(not isinstance(corner, str) or not corner for corner in declared)):
            raise ValueError('producer design/corner declaration is absent or ambiguous')
        sdfs = corner_sdfs(disk_state)
        if set(sdfs) != set(declared):
            raise Refusal('LL_STAPOSTPNR_SDF_CORNER_MISSING',
                          f'exported={sorted(sdfs)} declared={sorted(declared)}')
        netlist = Path(str(disk_state.get('nl') or '')).resolve()
        timed = (receipt.get('input') or {}).get('state_files') or {}
        if (not netlist.is_file() or timed.get(str(netlist)) != digest(netlist)):
            raise ValueError('SDF netlist is not the producer-bound timing input')
        netlist_text = re.sub(r'/\*.*?\*/|//[^\n]*', '',
                              netlist.read_text(errors='strict'), flags=re.S)
        modules = {left or right for left, right in _VERILOG_MODULE.findall(netlist_text)}
        if design not in modules:
            raise Refusal('LL_STAPOSTPNR_SDF_NETLIST_MISMATCH',
                          f'{design!r} is not a module in {netlist}')
        if (expected_netlist is not None
                and (not Path(expected_netlist).is_file()
                     or digest(Path(expected_netlist)) != digest(netlist))):
            raise Refusal('LL_STAPOSTPNR_SDF_NETLIST_MISMATCH',
                          f'{expected_netlist} differs from {netlist}')
        required = required_items if required_items is not None else [
            {'mode': 'functional', 'corner': corner} for corner in declared]
        if (not isinstance(required, list) or not required
                or any(not isinstance(item, dict)
                       or set(item) != {'mode', 'corner'}
                       or item.get('mode') != 'functional'
                       or not isinstance(item.get('corner'), str)
                       or not item['corner'] for item in required)
                or len({(item['mode'], item['corner']) for item in required}) != len(required)):
            raise Refusal('LL_STAPOSTPNR_SDF_REQUIREMENTS_INVALID', str(required))
        missing = sorted({item['corner'] for item in required} - set(sdfs))
        if missing:
            raise Refusal('LL_STAPOSTPNR_SDF_CORNER_MISSING', ', '.join(missing))
        exported = {}
        bound = receipt.get('sha256') or {}
        for corner, path in sorted(sdfs.items()):
            resolved = path.resolve()
            if not resolved.is_relative_to(folder):
                raise Refusal('LL_STAPOSTPNR_SDF_OUTPUT_UNBOUND', str(path))
            relative = str(resolved.relative_to(folder))
            if bound.get(relative) != digest(resolved):
                raise Refusal('LL_STAPOSTPNR_SDF_OUTPUT_UNBOUND', relative)
            exported[corner] = sdf_export_census(resolved, design)
        return {'producer': 'OpenROAD.STAPostPNR.write_sdf',
                'state': str(folder / 'state_out.json'),
                'state_sha256': digest(folder / 'state_out.json'),
                'receipt': str(folder / 'vibeic_receipt.json'),
                'receipt_sha256': digest(folder / 'vibeic_receipt.json'),
                'netlist': str(netlist), 'netlist_sha256': digest(netlist),
                'declared_corners': list(declared), 'required_items': list(required),
                'exports': exported}
    except Refusal:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise Refusal('LL_STAPOSTPNR_SDF_OUTPUT_UNBOUND', f'{folder}: {exc}') from exc


# --- step 29 -----------------------------------------------------------------

def gate_level_sim(project: Path, top: str, image: str, pdk_root: Path, pdk: str,
                   *, direct_sdfs: Optional[List[Path]] = None) -> dict:
    """Run the L10 suite against every STAPostPNR corner SDF (custom step),
    judge it, and write `reports/phase3/gls_corners.json`."""
    import sdf_gate_sim as sgs
    import librelane_contract as contract
    sta_folder, state = stapostpnr_state(project)
    sdf_binding = bind_stapostpnr_sdfs(sta_folder, state)
    sdfs = {corner: Path(row['path'])
            for corner, row in sdf_binding['exports'].items()}
    netlist = Path(str(state.get('nl') or ''))
    if not netlist.is_file():
        raise Refusal('LL_STATE_FILE_MISSING', f'nl: {netlist}')
    gls_dir = project / 'phase3/librelane/29-config/gls'
    configs = resolve_step_configs(
        project, image, pdk, [GLS_STEP], pdk_root=pdk_root, folder='29-config',
        overlay={'VIBEIC_GLS_MANIFEST': (str(gls_dir / 'gls_manifest.json'),
                                         'sdf_gate_sim.tool_arm_manifest (this run)')})
    config = _load(configs[GLS_STEP])
    if config.get('VIBEIC_GLS_MANIFEST') != str(gls_dir / 'gls_manifest.json'):
        raise Refusal('LL_STEP_CONFIG_MISSING', f'{GLS_STEP}: VIBEIC_GLS_MANIFEST not resolved')
    declared = [Path(str(p)) for key in ('CELL_VERILOG_MODELS', 'PAD_VERILOG_MODELS')
                for p in (config.get(key) or [])]
    host = {f'/pdk/{pdk}': str(pdk_root / pdk)}
    host_models = [Path(_map(str(p), host)) for p in declared]
    # Match run_chain's actual execution namespace for every closure member.
    local = contract._provider_for_image(image) is not None or contract._provider_route(project)
    # F21: the bench clock is the period of the SDC this STA state timed.
    manifest = sgs.tool_arm_manifest(project, top, netlist, host_models, gls_dir,
                                     sdc=Path(str(state.get('sdc') or '')),
                                     sdfs=[Path(p) for _, p in sorted(sdfs.items())],
                                     path_map={} if local else {v: k for k, v in host.items()})
    folder = run_chain(project, image, [(GLS_STEP, configs[GLS_STEP],
                                         sta_folder / 'state_out.json')],
                       mounts=[(pdk_root.resolve(), PDK_GUEST_ROOT)], lane='29', pdk_root=PDK_GUEST_ROOT)[0]
    judged = sgs.judge_tool_arm(folder, manifest)
    judged.update({
        'step': '29', 'arm': 'librelane:OpenROAD.STAPostPNR SDF x Vibeic.GateLevelSim',
        'sta_state': str(sta_folder / 'state_out.json'),
        'sta_state_sha256': digest(sta_folder / 'state_out.json'),
        'sdf_sha256': {c: digest(p) for c, p in sorted(sdfs.items())},
        'gls_step': str(folder),
        'coverage': {'tool_sdf_corners': len(sdfs),
                     'direct_sdf_corners': len(direct_sdfs or [])},
        'model_closure': manifest['model_closure'],
    })
    write_json(project / 'reports/phase3/gls_corners.json', judged)
    return judged


def _map(path: str, prefixes: Dict[str, str]) -> str:
    for guest, host in prefixes.items():
        if path.startswith(guest):
            return host + path[len(guest):]
    return path


# --- step 28 -----------------------------------------------------------------

#: The step-28 IR category's tool source is step 24 on LibreLane
#: (`OpenROAD.IRDropReport`, lane T101). Until that lane records its state the
#: IR category keeps the direct `ir_drop.json`: a named seam, not a guess.
PERC_IR_TOOL_SEAM = 'PERC_IR_TOOL_SEAM: step 24 has no LibreLane state in this run'

#: Metric -> PERC category. A category reads the tool metric only when EVERY
#: metric it names is present in one LibreLane state.
PERC_TOOL_METRICS = {
    'Antenna': ('antenna__violating__nets', 'antenna__violating__pins',
                'route__antenna_violation__count'),
    'PDN connectivity': ('design__power_grid_violation__count',),
}


def _librelane_states(project: Path) -> List[Path]:
    root = project / 'phase3/librelane'
    if not root.is_dir():
        return []
    return sorted((p for p in root.rglob('state_out.json') if 'attempts' not in p.parts),
                  key=lambda p: p.stat().st_mtime)


def perc_tool_metrics(project: Path) -> Dict[str, Any]:
    """Per PERC category, the newest LibreLane state carrying all its metrics:
    the values, the state path and its sha256. Absent -> not in the result."""
    out: Dict[str, Any] = {}
    for state_path in _librelane_states(project):
        metrics = _load(state_path).get('metrics') or {}
        for category, names in PERC_TOOL_METRICS.items():
            if all(isinstance(metrics.get(n), (int, float)) for n in names):
                out[category] = {'metrics': {n: metrics[n] for n in names},
                                 'state': str(state_path),
                                 'state_sha256': digest(state_path),
                                 'step': _state_step_id(state_path.parent)}
    return out


def tap_pitch(project: Path) -> Optional[Tuple[float, str]]:
    """`FP_TAPCELL_DIST` as LibreLane resolved it from the PDK's own config,
    from any resolved step config in the run, with the file it came from."""
    root = project / 'phase3/librelane'
    if not root.is_dir():
        return None
    for path in sorted(root.rglob('*.json')):
        if path.name.endswith(('.views.json', '.provenance.json')) or 'attempts' in path.parts:
            continue
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        value = doc.get('FP_TAPCELL_DIST') if isinstance(doc, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value), f'{path.relative_to(project)}:FP_TAPCELL_DIST'
    return None
