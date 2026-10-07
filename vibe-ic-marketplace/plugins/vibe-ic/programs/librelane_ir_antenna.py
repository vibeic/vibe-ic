#!/usr/bin/env python3
"""Opt-in steps 24, 26 and 26.5ic through LibreLane tool steps.

Step 24, static IR (`OpenROAD.IRDropReport` + `Vibeic.IRDropChecker`)
--------------------------------------------------------------------
The tool is the producer.  It reads the routed ODB, the SDC and the SPEF the
flow already has (step 22's, whichever path produced it; never re-extracted),
reads every corner library, and runs OpenROAD PSM on every VDD and GND net.
vibe-ic's own PSM session survives as the cross-check ARM ON THE SAME BASIS:
same ODB, SDC (clocks propagated when the SDC does not say), SPEF, libraries in
the order the tool's own log says it read them, the same net voltage and the
declared voltage sources.  It is the same solver, so the per-net worst drops
must agree to PSM's print precision; a disagreement is a refusal, not a pick.

What the tool path needed, each MEASURED on spm (gf180mcuD, 0.3.79):

* RC source.  LibreLane gives PSM the PDK's `LAYERS_RC`, an ORFS signal-wire
  fit.  PSM turns a per-length R into sheet R by multiplying by the layer's
  minimum width (`IRSolver::getResistanceMap`); in this session the fit's
  numbers are read in the first library's unit (1 ohm), and PSM's own debug
  print showed Metal2 1.08e-4 ohm/sq against the tech LEF's RPERSQ 0.090 --
  833x low.  `VIAS_R` is misapplied too: `openroad.py` filters its corner
  wildcards with `Filter(corner_wildcard)` (a bare string, so `*` matches every
  corner) and the nom corner got the max corner's 16.845 ohm vias.  So the IR
  step takes its resistance from the tech LEF -- the foundry's declaration and
  the direct deck's source -- by clearing both overrides in its step config,
  and `rc_model` proves it from PSM's own print (`set_debug_level PSM
  resistance 2`, through the contract's OpenROAD init file).
* Voltage sources.  Generated from the declared supply pads
  (`reports/phase3/io_pad_chip_top.json.power_pad_plan.instances`): each pad
  hosts its net's BTerm, whose shape becomes one PSM source.  When every
  declared net's BTerms lie on declared pads, PSM's default (BTerm) sources ARE
  the declared model, and the tool runs without `VSRC_LOC_FILES`: LibreLane's
  VSRC branch never calls `set_pdnsim_net_voltage`, and on this PDK's
  libraries (no default operating condition) PSM then dies `PSM-0079`
  (measured).  The cross-check reads the VSRC files explicitly, so agreement
  proves that equivalence rather than assuming it.
* Coverage.  LibreLane's `ir__drop__worst` is the FIRST net's drop (measured:
  VDD 0.869 mV listed first, VSS 1.19 mV worst).  The verdict reads the per-net
  keys (`librelane_plugins/librelane_plugin_vibeic/ir_rules`), for every declared net.

Step 26, antenna (`OpenROAD.CheckAntennas`; `KLayout.Antenna` +
`Checker.KLayoutAntenna`)
----------------------------------------------------------------
The router model runs on the ODB of the route that SHIPS (the canonical routed
DEF, bridged), never a re-read plus `global_route`.  The GDS model runs the
PDK's antenna deck on the shipped stream.  vibe-ic keeps two rules: the two
models disagreeing (one clean, one not) is a FAIL, and every count is bound by
sha256 to the layout that ships.

Step 26.5ic, seal ring (`KLayout.SealRing`)
------------------------------------------
The same PDK generator through the tool step, fed the declared DIE_AREA.  The
tool neither checks its output nor emits a metric (fork PR), so its output
goes through `die_finishing_gen --sealed-by`: the declaration (HARDMACRO skip,
required ring), the annulus verification, the band and die-id reporting are
unchanged.  The released image computes the die spans as x1/y1; a die whose
origin is not (0, 0) is refused until the fork fix ships (as step 37 does).

chip-AGNOSTIC: nets, pads, layers, corners and rules come from the design's
declarations, the PDK's own files and the tool's own records.
"""
from __future__ import annotations

import fnmatch
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402
import _docker_memory as _dmem  # noqa: E402 — every `docker run` carries the ceiling
import _psm_source_model as _psm_sm  # noqa: E402
from librelane_contract import (PDK_GUEST_ROOT, PLUGIN_ROOT, Refusal, _load, digest,  # noqa: E402
                                resolve_step_configs, run_chain, state_from_direct,
                                run_container, PROBE_DEADLINE_S)


def _plugin_module(name: str):
    """A pure module of the LibreLane plugin, loaded by path: the package's
    `__init__` imports LibreLane, which only the image has."""
    import importlib.util
    key = f'_vibeic_llplugin_{name}'
    if key not in sys.modules:
        path = PLUGIN_ROOT / 'librelane_plugin_vibeic' / f'{name}.py'
        spec = importlib.util.spec_from_file_location(key, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


ir_findings = _plugin_module('ir_rules').ir_findings
per_net_worst = _plugin_module('ir_rules').per_net_worst
transient_findings = _plugin_module('transient').transient_findings
#: The static solve, the fork's transient solve on the same basis, then the
#: gate.  The measurements come before the gate so a static FAIL still
#: leaves a dynamic number.
IR_STEPS = ('OpenROAD.IRDropReport', 'Vibeic.TransientIR', 'Vibeic.IRDropChecker')
OPENROAD_IR_STEPS = ('OpenROAD.IRDropReport', 'Vibeic.TransientIR')
ANTENNA_ROUTER_STEPS = ('OpenROAD.CheckAntennas',)
ANTENNA_GDS_STEPS = ('KLayout.Antenna', 'Checker.KLayoutAntenna')
SEALRING_STEPS = ('KLayout.SealRing',)
#: PSM prints the resistance map it solves with (`IRSolver::getResistanceMap`).
PSM_RESISTANCE_DEBUG = ['set_debug_level PSM resistance 2']
PAD_PLAN_REL = 'reports/phase3/io_pad_chip_top.json'
RC_SOURCE = ("tech LEF (RESISTANCE RPERSQ / cut RESISTANCE) through LibreLane's "
             "own set_layers_default_rc / set_vias_default_r: the step config's "
             "LAYERS_RC and VIAS_R are cleared (measured on gf180mcuD: LAYERS_RC "
             "gave PSM 1.08e-4 ohm/sq on Metal2 vs RPERSQ 0.090; VIAS_R applied "
             "the max_* 16.845 ohm to the nom corner, openroad.py Filter(str))")


def _run_openroad(project: Path, image: str, tcl: Path, log: Path,
                  mounts: List[tuple], metrics: Optional[Path] = None) -> int:
    """One OpenROAD session in the image; the project at its own path."""
    volumes = ['-v', f'{project.resolve()}:{project.resolve()}']
    for host, guest in mounts:
        volumes += ['-v', f'{Path(host).resolve()}:{guest}:ro']
    extra = f'-metrics {metrics} ' if metrics else ''
    log.parent.mkdir(parents=True, exist_ok=True)
    completed = run_container(
        ['docker', 'run', '--rm', '--network', 'none', *_dmem.docker_memory_flags(),
         *volumes, '--entrypoint', 'bash', image, '-c',
         'LD_LIBRARY_PATH=/opt/or-tools/lib /foss/tools/openroad/bin/openroad '
         f'-no_init -no_splash {extra}-exit {tcl}'],
        supervised=True, log=log)
    log.write_text(completed.stdout + '\n' + completed.stderr)
    return completed.returncode


def _config(path: Path) -> Dict[str, Any]:
    return _load(path)


def _pattern_for(corner: str, patterns) -> Optional[str]:
    """The one wildcard in `patterns` that matches `corner`, else None."""
    hits = [p for p in patterns if fnmatch.fnmatch(corner, p)]
    return hits[0] if len(hits) == 1 else None


def _host_path(guest: str, mounts: List[tuple]) -> Path:
    for host, prefix in mounts:
        prefix = str(prefix).rstrip('/')
        if guest == prefix or guest.startswith(prefix + '/'):
            return Path(host) / guest[len(prefix):].lstrip('/')
    return Path(guest)


# --- step 24: declared voltage sources ---------------------------------------

def declared_supply_pads(project: Path) -> Dict[str, Any]:
    """The chip-top producer's power-pad plan: nets and pad instances."""
    path = project / PAD_PLAN_REL
    plan = _load(path).get('power_pad_plan') if path.is_file() else None
    if not isinstance(plan, dict):
        return {'declared': False, 'source': f'{PAD_PLAN_REL} (no power_pad_plan)'}
    instances = [x for x in plan.get('instances') or [] if isinstance(x, str) and x]
    return {'declared': bool(instances), 'instances': instances,
            'source': f'{PAD_PLAN_REL}.power_pad_plan.instances',
            'sha256': digest(path)}


_GEOMETRY_TCL = r'''
read_db {__ODB__}
set _b [ord::get_db_block]
set _u [$_b getDbUnitsPerMicron]
foreach _n {__PADS__} {
  set _i [$_b findInst $_n]
  if {$_i eq "NULL"} { puts "VIBEIC_PAD_MISSING $_n"; continue }
  set _bb [$_i getBBox]
  puts "VIBEIC_PAD $_n [expr {double([$_bb xMin])/$_u}] [expr {double([$_bb yMin])/$_u}] [expr {double([$_bb xMax])/$_u}] [expr {double([$_bb yMax])/$_u}]"
}
foreach _n {__NETS__} {
  set _net [$_b findNet $_n]
  if {$_net eq "NULL"} { puts "VIBEIC_NET_MISSING $_n"; continue }
  foreach _t [$_net getBTerms] {
    foreach _p [$_t getBPins] {
      foreach _x [$_p getBoxes] {
        puts "VIBEIC_BTERM $_n [$_t getName] [[$_x getTechLayer] getName] [expr {double([$_x xMin])/$_u}] [expr {double([$_x yMin])/$_u}] [expr {double([$_x xMax])/$_u}] [expr {double([$_x yMax])/$_u}]"
      }
    }
  }
}
'''


def supply_geometry(project: Path, image: str, odb: Path, nets: List[str],
                    pads: List[str], folder: Path, mounts: List[tuple]) -> Dict[str, Any]:
    """Pad bounding boxes and the nets' BTerm shapes, in um, from the ODB."""
    folder.mkdir(parents=True, exist_ok=True)
    tcl = folder / 'supply_geometry.tcl'
    tcl.write_text(_GEOMETRY_TCL.replace('__ODB__', str(odb))
                   .replace('__PADS__', ' '.join(pads) or '{}')
                   .replace('__NETS__', ' '.join(nets) or '{}') + 'exit\n')
    log = folder / 'supply_geometry.log'
    if _run_openroad(project, image, tcl, log, mounts):
        raise Refusal('LL_VSRC_GEOMETRY_FAILED', str(log))
    out: Dict[str, Any] = {'pads': {}, 'bterms': [], 'missing_pads': [], 'missing_nets': [],
                           'searched': f'{odb} (probe log {log})'}
    for line in log.read_text(errors='replace').splitlines():
        words = line.split()
        if not words:
            continue
        if words[0] == 'VIBEIC_PAD' and len(words) == 6:
            out['pads'][words[1]] = [float(v) for v in words[2:]]
        elif words[0] == 'VIBEIC_BTERM' and len(words) == 8:
            out['bterms'].append({'net': words[1], 'bterm': words[2], 'layer': words[3],
                                  'box': [float(v) for v in words[4:]]})
        elif words[0] == 'VIBEIC_PAD_MISSING' and len(words) == 2:
            out['missing_pads'].append(words[1])
        elif words[0] == 'VIBEIC_NET_MISSING' and len(words) == 2:
            out['missing_nets'].append(words[1])
    return out


def _inside(box: List[float], outer: List[float]) -> bool:
    return (box[0] >= outer[0] and box[1] >= outer[1]
            and box[2] <= outer[2] and box[3] <= outer[3])


def declared_sources(geometry: Dict[str, Any], vdd_nets: List[str],
                     gnd_nets: List[str]) -> Dict[str, Any]:
    """PSM source rows from the declared pads' BTerms, and whether PSM's own
    BTerm default is that same model (`coincident`)."""
    nets = list(dict.fromkeys([*vdd_nets, *gnd_nets]))
    searched = geometry.get('searched') or 'the supply geometry passed in'
    if geometry.get('missing_pads'):
        raise Refusal('LL_VSRC_PAD_MISSING',
                      f"declared supply pad instance(s) {', '.join(geometry['missing_pads'])} "
                      f'not in the block of {searched}')
    rows: Dict[str, List[Dict[str, Any]]] = {net: [] for net in nets}
    outside: List[str] = []
    hosting = {pad: 0 for pad in geometry.get('pads', {})}
    for term in geometry.get('bterms', []):
        pads = [p for p, box in geometry['pads'].items() if _inside(term['box'], box)]
        if not pads:
            outside.append(f"{term['net']}:{term['bterm']}")
            continue
        hosting[pads[0]] += 1
        x0, y0, x1, y1 = term['box']
        rows.setdefault(term['net'], []).append({
            'pad': pads[0], 'bterm': term['bterm'], 'layer': term['layer'],
            'x': (x0 + x1) / 2.0, 'y': (y0 + y1) / 2.0, 'size': min(x1 - x0, y1 - y0)})
    unsourced = [net for net in nets if not rows.get(net)]
    idle = sorted(p for p, n in hosting.items() if not n)
    if unsourced:
        raise Refusal('LL_VSRC_NET_UNSOURCED',
                      f'declared supply net(s) with no BTerm on a declared pad: {unsourced}')
    if idle:
        raise Refusal('LL_VSRC_PAD_TERMINAL_MISSING',
                      f'declared supply pad(s) hosting no BTerm of {nets} in {searched}: {idle}')
    return {'sources': rows, 'bterms_outside_declared_pads': outside,
            'coincident': not outside}


def write_vsrc(sources: Dict[str, List[Dict[str, Any]]], voltages: Dict[str, float],
               folder: Path) -> Dict[str, Path]:
    """One PSM location file per net: `x,y,size,voltage` in um, one row per
    source (`IRSolver::generateSourceNodesFromSourceFile`)."""
    folder.mkdir(parents=True, exist_ok=True)
    files: Dict[str, Path] = {}
    for net, rows in sources.items():
        path = folder / f'{net}.vsrc'
        path.write_text(''.join(f"{r['x']:.4f},{r['y']:.4f},{r['size']:.4f},{voltages[net]:g}\n"
                                for r in rows))
        files[net] = path
    return files


# --- step 24: the tool's own records -----------------------------------------

_LIB_VOLTAGE_RE = re.compile(r'^set ::env\(LIB_VOLTAGE\) (\S+)\s*$', re.M)
#: LibreLane's `read_pnr_libs` names each library it read, per corner.
_LIB_READ_RE = re.compile(r"^Reading timing library for the '([^']+)' corner at '([^']+)'", re.M)
#: PSM's `getResistanceMap` debug print: the estimate, then (only when that is
#: 0) the database value.  The last line per layer is the value PSM solves with.
_PSM_RES_RE = re.compile(
    r'^\[DEBUG PSM-resistance\] (?:Estimate parasitics|Database) resistance for (\S+) = (\S+)', re.M)


def lib_voltage(folder: Path) -> Optional[float]:
    """The `LIB_VOLTAGE` IRDropReport set for its run (its `_env.tcl`)."""
    env = folder / '_env.tcl'
    match = _LIB_VOLTAGE_RE.search(env.read_text(errors='replace')) if env.is_file() else None
    try:
        return float(match.group(1)) if match else None
    except ValueError:
        return None


def _step_log(folder: Path) -> str:
    return '\n'.join(p.read_text(errors='replace')
                     for p in sorted(folder.glob('openroad-*.log')))


def libraries_read(folder: Path, corner: str) -> List[str]:
    return [path for name, path in _LIB_READ_RE.findall(_step_log(folder)) if name == corner]


def resistance_map(folder: Path) -> Dict[str, float]:
    """Per layer, the resistance PSM solved the first net with."""
    out: Dict[str, float] = {}
    for layer, value in _PSM_RES_RE.findall(_step_log(folder)):
        try:
            out[layer] = float(value)
        except ValueError:
            continue
    return out


def lef_resistance(text: str) -> Dict[str, Dict[str, Any]]:
    """`{layer: {type, value}}` from a tech LEF's LAYER blocks: RPERSQ for a
    ROUTING layer, the per-cut RESISTANCE for a CUT layer."""
    out: Dict[str, Dict[str, Any]] = {}
    layer = kind = None
    # The PROPERTYDEFINITIONS block declares `LAYER <property> STRING ;`,
    # which is not a layer (measured: gf180mcuD's LEF58_EOLENCLOSURE).
    text = re.sub(r'^\s*PROPERTYDEFINITIONS\b.*?^\s*END\s+PROPERTYDEFINITIONS\b', '',
                  text, flags=re.S | re.M)
    for raw in text.splitlines():
        words = raw.split('#', 1)[0].replace(';', ' ').split()
        if not words:
            continue
        if words[0] == 'LAYER' and len(words) >= 2 and layer is None:
            layer, kind = words[1], None
        elif layer and words[0] == 'END' and len(words) >= 2 and words[1] == layer:
            layer = kind = None
        elif layer and words[0] == 'TYPE' and len(words) >= 2:
            kind = words[1]
        elif layer and words[0] == 'RESISTANCE' and kind in ('ROUTING', 'CUT'):
            value = words[2] if len(words) >= 3 and words[1] == 'RPERSQ' else words[1]
            try:
                out[layer] = {'type': kind, 'value': float(value)}
            except ValueError:
                pass
    return out


def rc_model(psm: Dict[str, float], lef: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """PSM's solved resistance per ROUTING/CUT layer against the tech LEF."""
    if not psm:
        return {'verdict': 'NOT_MEASURED', 'reason': 'PSM printed no resistance map'}
    rows = {}
    for layer, decl in sorted(lef.items()):
        if layer not in psm:
            rows[layer] = {'lef': decl['value'], 'psm': None, 'status': 'NOT_MEASURED'}
            continue
        agree = math.isclose(psm[layer], decl['value'], rel_tol=1e-6, abs_tol=1e-12)
        rows[layer] = {'type': decl['type'], 'lef': decl['value'], 'psm': psm[layer],
                       'status': 'AGREE' if agree else 'DISAGREE'}
    bad = [layer for layer, row in rows.items() if row['status'] == 'DISAGREE']
    unseen = [layer for layer, row in rows.items() if row['status'] == 'NOT_MEASURED']
    verdict = 'DISAGREE' if bad else 'NOT_MEASURED' if unseen or not rows else 'AGREE'
    return {'verdict': verdict, 'layers': rows, 'disagreeing': bad}


# --- step 24: the cross-check arm ---------------------------------------------

def cross_check(project: Path, image: str, folder: Path, config: Dict[str, Any],
                vsrc: Dict[str, Path], voltage: float, vdd_nets: List[str],
                gnd_nets: List[str], mounts: List[tuple], out_dir: Path) -> Dict[str, Any]:
    """vibe-ic's PSM session on the tool's basis: the step's own input state
    (ODB, SDC, SPEF), the libraries its log says it read for the default
    corner (in that order), the tech LEF's resistance (never set here, so PSM
    falls back to it), the same net voltages, and the declared sources."""
    state = _load(folder / 'state_in.json')
    corner = config.get('DEFAULT_CORNER') or ''
    libs = libraries_read(folder, corner)
    if not libs:
        raise Refusal('LL_IR_LIBRARIES_UNREAD', f'{folder}: no library read for {corner!r}')
    tech = config.get('TECH_LEFS') or {}
    pattern = _pattern_for(corner, tech)
    if pattern is None:
        raise Refusal('LL_IR_TECH_LEF_UNRESOLVED', f'{corner}: {sorted(tech)}')
    spefs = state.get('spef') or {}
    spef_pattern = _pattern_for(corner, spefs)
    if spef_pattern is None:
        raise Refusal('LL_IR_SPEF_UNRESOLVED', f'{corner}: {sorted(spefs)}')
    lefs = [tech[pattern], *(config.get('CELL_LEFS') or []), *(config.get('PAD_LEFS') or []),
            *(config.get('MACRO_LEFS') or []), *(config.get('EXTRA_LEFS') or [])]
    sdc = state.get('sdc')
    lines = [f'read_lef {{{p}}}' for p in dict.fromkeys(lefs)]
    lines += [f'read_liberty {{{p}}}' for p in libs]
    lines += [f"read_db {{{state['odb']}}}"]
    if sdc:
        lines.append(f'read_sdc {{{sdc}}}')
        text = Path(sdc).read_text(errors='replace')
        if 'set_propagated_clock' not in text:
            # Post-route basis; the tool's `read_current_sdc` does the same.
            lines.append('set_propagated_clock [all_clocks]')
    lines.append(f'read_spef {{{spefs[spef_pattern]}}}')
    for net in dict.fromkeys([*vdd_nets, *gnd_nets]):
        volts = voltage if net in vdd_nets else 0.0
        lines.append(f'set_pdnsim_net_voltage -net {net} -voltage {volts:g}')
        source = f' -vsrc {{{vsrc[net]}}}' if net in vsrc else ''
        lines.append(f'if {{[catch {{analyze_power_grid -net {net}{source}}} _e]}} '
                     f'{{ puts "PSM_NONFATAL {net}: $_e" }}')
    out_dir.mkdir(parents=True, exist_ok=True)
    tcl = out_dir / 'ir_cross_check.tcl'
    tcl.write_text('\n'.join(lines) + '\nexit\n')
    metrics = out_dir / 'ir_cross_check.metrics.json'
    metrics.unlink(missing_ok=True)
    log = out_dir / 'ir_cross_check.log'
    rc = _run_openroad(project, image, tcl, log, mounts, metrics)
    if rc or not metrics.is_file():
        return {'verdict': 'NOT_MEASURED', 'reason': f'cross-check rc={rc}', 'log': str(log)}
    raw = _load(metrics)
    worst = {}
    for key, value in raw.items():
        head, _, tail = key.partition('__corner:')
        if head.startswith('design_powergrid__drop__worst__net:') and tail:
            worst[head.split(':', 1)[1]] = float(value)
    return {'verdict': 'MEASURED', 'per_net_worst_drop_v': dict(sorted(worst.items())),
            'libraries': libs, 'vsrc': {n: str(p) for n, p in vsrc.items()},
            'voltage_v': voltage, 'log': str(log), 'metrics': str(metrics),
            'metrics_sha256': digest(metrics)}


def ir_agreement(tool: Dict[str, float], deck: Dict[str, float]) -> Dict[str, Any]:
    """Same solver, same basis: every net agrees to PSM's metric precision
    (6 significant digits), or the arms disagree."""
    if not tool or not deck:
        return {'verdict': 'NOT_COMPARABLE', 'reason': 'an arm measured no net'}
    if set(tool) != set(deck):
        return {'verdict': 'DISAGREE', 'reason': 'different nets analysed',
                'tool_nets': sorted(tool), 'deck_nets': sorted(deck)}
    rows = {net: {'tool_v': tool[net], 'deck_v': deck[net],
                  'agree': math.isclose(tool[net], deck[net], rel_tol=1e-5, abs_tol=1e-12)}
            for net in sorted(tool)}
    bad = [net for net, row in rows.items() if not row['agree']]
    return {'verdict': 'DISAGREE' if bad else 'AGREE', 'nets': rows, 'disagreeing': bad}


# --- step 24: the run ----------------------------------------------------------

def chain_folder(project: Path, lane: str, steps, step: str) -> Path:
    """The folder `run_chain` gives `step` in this chain (`NN-<step id>`),
    by name: a lane can still hold folders an earlier, different chain left."""
    index = list(steps).index(step) + 1
    return project / 'phase3/librelane' / lane / f"{index:02d}-{step.lower().replace('.', '-')}"


def require_safe_default_sources(project: Path, image: str, state: Path,
                                 mounts: List[tuple]) -> Dict[str, int]:
    """Refuse a bridge whose promoted BPin shapes would become PSM sources.

    This probes the exact ODB all three step-24 arms would consume. Until the
    LibreLane plugin can apply PSM_DISCONNECT to that ODB, a padless block with
    such pins cannot publish an IR result. The probe's properties live only in
    its own OpenROAD process and never alter the shipped route or bridge.
    """
    odb = Path(_load(state)['odb'])
    folder = state.parent
    tcl = folder / 'psm_source_probe.tcl'
    log = folder / 'psm_source_probe.log'
    tcl.write_text(f'read_db {{{odb}}}\n'
                   + _psm_sm.exclude_promoted_pins_tcl()
                   + 'set _vibeic_psm_bpins 0\n'
                   + 'foreach _n [[ord::get_db_block] getNets] {\n'
                   + '  if {[$_n getSigType] ni {POWER GROUND}} { continue }\n'
                   + '  foreach _t [$_n getBTerms] {\n'
                   + '    if {![$_t isSpecial]} { continue }\n'
                   + '    incr _vibeic_psm_bpins [llength [$_t getBPins]]\n'
                   + '  }\n'
                   + '}\n'
                   + 'puts "PSM_PROMOTED_PIN_PROBE: supply_bpins=$_vibeic_psm_bpins"\nexit\n')
    rc = _run_openroad(project, image, tcl, log, mounts)
    output = log.read_text(errors='replace') if log.is_file() else ''
    marker = _psm_sm.read(output)
    count = re.search(r'^PSM_PROMOTED_PIN_PROBE: supply_bpins=(\d+)\s*$', output, re.M)
    if rc or marker is None or count is None:
        raise Refusal('LL_IR_SOURCE_PROBE_UNMEASURED',
                      f'bridge={odb} probe_rc={rc} log={log}')
    result = {**marker, 'supply_bpins': int(count.group(1))}
    if (result['placed_pads'] == 0
            and result['promoted_supply_pins_excluded'] != result['supply_bpins']):
        raise Refusal('LL_IR_SOURCE_PROBE_INCONSISTENT',
                      f'bridge={odb} marker={result} log={log}')
    if result['placed_pads'] == 0 and result['promoted_supply_pins_excluded']:
        raise Refusal('LL_IR_PROMOTED_PIN_SOURCES_UNSAFE',
                      f"bridge={odb} has {result['promoted_supply_pins_excluded']} "
                      'special supply BPins and no placed pad master; LibreLane '
                      'PSM would use their strap shapes as ideal sources')
    return result


def run_ir(project: Path, image: str, pdk_root: Path, pdk: str, *, routed_def: Path,
           netlist: Path, sdc: Path, spef: Path, budget_pct: Optional[float],
           budget_source: str, lane: str = '24', decap_f: Optional[float] = None,
           decap_source: Optional[str] = None,
           supply_nets: Optional[Dict[str, List[str]]] = None,
           tech_lef: Optional[Path] = None) -> Dict[str, Any]:
    """Bridge the shipped route, run IRDropReport + Vibeic.IRDropChecker, then
    the cross-check.  Returns the record `judge_ir` reads.

    `decap_f` (farads, with its declared `decap_source`) is the on-die decap
    `Vibeic.TransientIR` models; the step converts it to the session's unit,
    reads it back and measures its effect.  None: quasi-static.

    `tech_lef` is the active routed authority shared with the EM producer.
    Bind it into the selected IR corner before building the ODB; an absent
    file or ambiguous corner refuses rather than substituting the kit default.
    None retains the resolved PDK authority for standalone callers."""
    # A sign-off checkpoint already supplies the routed netlist. The config
    # resolver still requires VERILOG_FILES even though this chain consumes
    # its bridged ODB; it must not require the original RTL tree to be copied.
    overlay = {'VERILOG_FILES': ([str(Path(netlist).resolve())],
                                'current routed netlist supplied to the IR bridge')}
    overlay.update({key: (value, 'current routed DEF SPECIALNETS USE POWER/GROUND')
                    for key, value in (supply_nets or {}).items()})
    configs = resolve_step_configs(project, image, pdk, list(IR_STEPS), pdk_root=pdk_root,
                                   folder='24-config', overlay=overlay)
    # The budget is the checker's own variable, which the Chip flow's resolver
    # does not know; it is written into the checker's resolved config with its
    # source beside it.  None stays None: the checker then refuses, never passes.
    checker_cfg = configs['Vibeic.IRDropChecker']
    checker = _config(checker_cfg)
    checker['VIBEIC_IR_BUDGET_PCT'] = budget_pct
    write_json(checker_cfg, checker)
    write_json(checker_cfg.with_name(checker_cfg.stem + '.overrides.json'),
               {'VIBEIC_IR_BUDGET_PCT': budget_pct, 'source': budget_source})
    ir_cfg = configs['OpenROAD.IRDropReport']
    cfg = _config(ir_cfg)
    cleared = {key: cfg.get(key) for key in ('LAYERS_RC', 'VIAS_R')}
    active_tech = None
    if tech_lef is not None:
        active_tech = _host_path(str(tech_lef), [(pdk_root.resolve(), PDK_GUEST_ROOT)])
        if not active_tech.is_file():
            raise Refusal('LL_IR_TECH_LEF_MISSING', str(active_tech))
        active_tech = active_tech.resolve()
    for step in OPENROAD_IR_STEPS:
        step_cfg = _config(configs[step])
        step_cfg.update({'LAYERS_RC': None, 'VIAS_R': None})
        overrides = {'cleared': cleared, 'source': RC_SOURCE}
        if active_tech is not None:
            techs = dict(step_cfg.get('TECH_LEFS') or {})
            pattern = _pattern_for(step_cfg.get('DEFAULT_CORNER') or '', techs)
            if pattern is None:
                raise Refusal('LL_IR_TECH_LEF_CORNER_UNRESOLVED', step)
            overrides['TECH_LEFS'] = {
                'pattern': pattern, 'previous': techs,
                'path': str(active_tech), 'sha256': digest(active_tech),
                'source': 'active routed PDK tech LEF supplied by the IR/EM producer'}
            # IR solves one selected corner. A single authority also makes
            # the DEF-to-ODB bridge (which otherwise prefers the nominal
            # entry) read exactly the LEF the solver and EM will consume.
            step_cfg['TECH_LEFS'] = {pattern: str(active_tech)}
        write_json(configs[step], step_cfg)
        write_json(configs[step].with_name(configs[step].stem + '.overrides.json'),
                   overrides)
    if decap_f is not None:
        if not decap_source:
            raise Refusal('LL_DECAP_SOURCE_UNDECLARED',
                          f'a decap of {decap_f!r} F needs a declared source')
        transient_cfg = configs['Vibeic.TransientIR']
        step_cfg = _config(transient_cfg)
        step_cfg['VIBEIC_DECAP_CAP'] = decap_f
        write_json(transient_cfg, step_cfg)
        overrides = transient_cfg.with_name(transient_cfg.stem + '.overrides.json')
        record = _load(overrides) if overrides.is_file() else {}
        record['VIBEIC_DECAP_CAP'] = {'value': decap_f, 'unit': 'F', 'source': decap_source}
        write_json(overrides, record)
    cfg = _config(ir_cfg)
    mounts = [(pdk_root.resolve(), PDK_GUEST_ROOT)]
    if active_tech is not None and not active_tech.is_relative_to(project.resolve()):
        mounts.append((active_tech.parent, str(active_tech.parent)))
    for source in (routed_def, netlist, sdc, spef):
        if not Path(source).is_file():
            raise Refusal('LL_ROUTE_VIEW_MISSING', str(source))
    corner = cfg.get('DEFAULT_CORNER') or ''
    patterns = cfg.get('TECH_LEFS') or {}
    spef_key = _pattern_for(corner, patterns) or '*'
    state = state_from_direct(project, image, ir_cfg,
                              {'def': routed_def, 'nl': netlist, 'sdc': sdc,
                               'spef': {spef_key: spef}},
                              project / 'phase3/librelane/24-config/bridge',
                              chain=[configs['Vibeic.IRDropChecker']], mounts=mounts)
    source_probe = require_safe_default_sources(project, image, state, mounts)
    vdd, gnd = list(cfg.get('VDD_NETS') or []), list(cfg.get('GND_NETS') or [])
    pads = declared_supply_pads(project)
    record: Dict[str, Any] = {'image': image, 'rc_source': RC_SOURCE, 'rc_cleared': cleared,
                              'vdd_nets': vdd, 'gnd_nets': gnd, 'pad_plan': pads,
                              'spef': str(spef), 'spef_sha256': digest(spef),
                              'routed_def': str(routed_def), 'def_sha256': digest(routed_def),
                              'budget_pct': budget_pct, 'budget_source': budget_source,
                              'source_probe': source_probe}
    sources = None
    if pads['declared']:
        geometry = supply_geometry(project, image, Path(_load(state)['odb']), vdd + gnd,
                                   pads['instances'], project / 'phase3/librelane/24-config/vsrc',
                                   mounts)
        sources = declared_sources(geometry, vdd, gnd)
        record['source_model'] = ('declared supply pads; PSM default BTerm sources are the '
                                  'same shapes' if sources['coincident'] else
                                  'declared supply pads through VSRC_LOC_FILES')
        record['sources'] = sources
    steps = [(s, configs[s], state) for s in IR_STEPS]
    checker_error = None
    try:
        folders = run_chain(project, image, steps, mounts=mounts, lane=lane,
                            openroad_init=PSM_RESISTANCE_DEBUG, pdk_root=PDK_GUEST_ROOT)
    except Refusal as error:
        if not (chain_folder(project, lane, IR_STEPS, IR_STEPS[0]) / 'state_out.json').is_file():
            raise
        checker_error = str(error)
    tool = chain_folder(project, lane, IR_STEPS, IR_STEPS[0])
    voltage = lib_voltage(tool)
    if sources is not None and voltage is not None:
        volts = {net: (voltage if net in vdd else 0.0) for net in sources['sources']}
        vsrc = write_vsrc(sources['sources'], volts, project / 'phase3/librelane/24-config/vsrc')
        if not sources['coincident']:
            # The BTerm default is NOT the declared model: hand the tool the
            # declared sources.  An image without the fork's VSRC voltage fix
            # fails here by name (PSM-0079), never with the wrong sources.
            cfg['VSRC_LOC_FILES'] = {net: str(path) for net, path in vsrc.items()}
            for step in OPENROAD_IR_STEPS:
                step_cfg = _config(configs[step])
                step_cfg['VSRC_LOC_FILES'] = cfg['VSRC_LOC_FILES']
                write_json(configs[step], step_cfg)
            run_chain(project, image, steps, mounts=mounts, lane=lane,
                      openroad_init=PSM_RESISTANCE_DEBUG, pdk_root=PDK_GUEST_ROOT)
    else:
        vsrc = {}
    probe_log = (state.parent / 'psm_source_probe.log').read_text(errors='replace')
    observed_source = _psm_sm.describe(probe_log + '\n' + _step_log(tool))
    if observed_source['model'].startswith('NOT_MEASURED'):
        raise Refusal('LL_IR_SOURCE_MODEL_UNMEASURED', observed_source['model'])
    if (sources is None and source_probe['placed_pads'] == 0
            and source_probe['supply_bpins'] == 0
            and observed_source['psm_0073'] is None):
        raise Refusal('LL_IR_SOURCE_MODEL_UNRESOLVED',
                      'padless ODB has no supply BPin source and the tool log has no PSM-0073')
    record['psm_source_model'] = observed_source
    if sources is None:
        record['source_model'] = observed_source['model']
    elif sources['coincident']:
        record['source_model'] += f"; PSM log: {observed_source['model']}"
    else:
        record['source_model'] += ('; PSM-0073 observed in tool log' if
                                   observed_source['psm_0073'] else
                                   '; PSM-0073 absent in tool log')
    transient = chain_folder(project, lane, IR_STEPS, 'Vibeic.TransientIR')
    record['transient'] = (_load(transient / 'transient_ir.json')
                           if transient and (transient / 'transient_ir.json').is_file() else
                           {'verdict': 'NOT_MEASURED',
                            'reason': checker_error or 'the transient step wrote no record'})
    if transient and (transient / 'transient_ir.json').is_file():
        record['transient']['record'] = str(transient / 'transient_ir.json')
        record['transient']['record_sha256'] = digest(transient / 'transient_ir.json')
    record['tool_state'] = str(tool / 'state_out.json')
    record['tool_state_sha256'] = digest(tool / 'state_out.json')
    record['checker_error'] = checker_error
    record['lib_voltage_v'] = voltage
    tlef = _host_path((cfg.get('TECH_LEFS') or {}).get(_pattern_for(corner, patterns) or '', ''), mounts)
    lef = lef_resistance(tlef.read_text(errors='replace')) if tlef.is_file() else {}
    record['rc_model'] = rc_model(resistance_map(tool), lef)
    record['cross_check'] = (cross_check(project, image, tool, cfg, vsrc, voltage, vdd, gnd,
                                         mounts, project / 'phase3/tool_arms/24')
                             if voltage is not None else
                             {'verdict': 'NOT_MEASURED', 'reason': 'LIB_VOLTAGE unrecorded'})
    return record


def judge_ir(record: Dict[str, Any]) -> Dict[str, Any]:
    """The step-24 verdict from the tool's state plus the three instruments.

    FAIL: the rule (coverage/budget) fails, or the arms DISAGREE, or PSM's
    resistance map disagrees with the tech LEF, or a PSM connectivity witness
    fires.  NOT_MEASURED: any instrument could not measure.  PASS otherwise.
    """
    from psm_analysis_coverage import analysis_coverage
    state = _load(Path(record['tool_state']))
    metrics = dict(state.get('metrics') or {})
    findings = ir_findings(metrics, record['vdd_nets'], record['gnd_nets'],
                           record.get('lib_voltage_v'), record.get('budget_pct'))
    tool_folder = Path(record['tool_state']).parent
    coverage = analysis_coverage(_step_log(tool_folder),
                                 [*record['vdd_nets'], *record['gnd_nets']])
    deck = record.get('cross_check') or {}
    agreement = (ir_agreement(per_net_worst(metrics), deck.get('per_net_worst_drop_v') or {})
                 if deck.get('verdict') == 'MEASURED' else
                 {'verdict': 'NOT_COMPARABLE', 'reason': deck.get('reason')})
    rc = record.get('rc_model') or {'verdict': 'NOT_MEASURED'}
    reasons = []
    if findings['verdict'] == 'FAIL':
        reasons.append(f"IR rule: {findings.get('reason')}")
    if coverage['analysis_failed'] or coverage['unconnected_instances']:
        reasons.append(f"PSM connectivity: failed={coverage['analysis_failed']} "
                       f"unreached={coverage['unconnected_instances'][:6]}")
    if agreement['verdict'] == 'DISAGREE':
        reasons.append(f"LL_IR_ARMS_DISAGREE: {agreement.get('disagreeing') or agreement.get('reason')}")
    if rc['verdict'] == 'DISAGREE':
        reasons.append(f"LL_IR_RC_MODEL_INCONSISTENT: {rc.get('disagreeing')}")
    if reasons:
        verdict = 'FAIL'
    elif ('NOT_MEASURED' in (findings['verdict'], rc['verdict'])
          or agreement['verdict'] != 'AGREE'):
        verdict = 'NOT_MEASURED'
    else:
        verdict = 'PASS'
    return {'verdict': verdict, 'reasons': reasons, 'rule': findings,
            'psm_coverage': coverage, 'agreement': agreement, 'rc_model': rc}


# --- step 26: antenna, router model and GDS model -----------------------------

#: The router model's counts, as `OpenROAD.CheckAntennas` records them.
ROUTER_METRICS = ('antenna__violating__nets', 'antenna__violating__pins')
#: The GDS model's count (`KLayout.Antenna`, judged by `Checker.KLayoutAntenna`).
GDS_METRIC = 'klayout__antenna_error__count'


def _metrics(folder: Path) -> Dict[str, Any]:
    state = _load(folder / 'state_out.json')
    metrics = dict(state.get('metrics') or {})
    if (folder / 'metrics.json').is_file():
        metrics.update(_load(folder / 'metrics.json'))
    return metrics


def run_antenna_router(project: Path, image: str, pdk_root: Path, pdk: str, *,
                       routed_def: Path, netlist: Path, sdc: Path,
                       lane: str = '26', overlay: Optional[dict] = None) -> Dict[str, Any]:
    """`OpenROAD.CheckAntennas` on the ODB of the route that ships.

    The bridge reads the canonical routed DEF once, with the step config's own
    LEFs; there is no `global_route` (the direct re-read needed one and threw
    the antenna jumpers away, ANT-0008)."""
    configs = resolve_step_configs(project, image, pdk, list(ANTENNA_ROUTER_STEPS),
                                   pdk_root=pdk_root, folder='26-config', overlay=overlay)
    mounts = [(pdk_root.resolve(), PDK_GUEST_ROOT)]
    for source in (routed_def, netlist, sdc):
        if not Path(source).is_file():
            raise Refusal('LL_ROUTE_VIEW_MISSING', str(source))
    step = ANTENNA_ROUTER_STEPS[0]
    state = state_from_direct(project, image, configs[step],
                              {'def': routed_def, 'nl': netlist, 'sdc': sdc},
                              project / 'phase3/librelane/26-config/bridge', mounts=mounts)
    folder = run_chain(project, image, [(step, configs[step], state)],
                       mounts=mounts, lane=lane, pdk_root=PDK_GUEST_ROOT)[0]
    metrics = _metrics(folder)
    return {'model': 'router', 'step': step, 'state': str(folder / 'state_out.json'),
            'state_sha256': digest(folder / 'state_out.json'),
            'subject': str(routed_def), 'subject_sha256': digest(routed_def),
            'counts': {k: metrics.get(k) for k in ROUTER_METRICS}}


def run_antenna_gds(project: Path, image: str, pdk_root: Path, pdk: str, *,
                    gds: Path, lane: str = '26-gds', overlay: Optional[dict] = None) -> Dict[str, Any]:
    """The PDK's antenna deck on the shipped stream (`KLayout.Antenna`), then
    the tool's own checker.  A checker refusal (count > 0) is recorded, not
    raised: the count is the evidence."""
    configs = resolve_step_configs(project, image, pdk, list(ANTENNA_GDS_STEPS),
                                   pdk_root=pdk_root, folder='26-config', overlay=overlay)
    runset = _config(configs['KLayout.Antenna']).get('KLAYOUT_ANTENNA_RUNSET')
    if not runset:
        raise Refusal('LL_ANTENNA_RUNSET_UNDECLARED', f'{pdk}: KLAYOUT_ANTENNA_RUNSET')
    if not Path(gds).is_file():
        raise Refusal('LL_GDS_MISSING', f'no stream file at {Path(gds)}')
    mounts = [(pdk_root.resolve(), PDK_GUEST_ROOT)]
    state = state_from_direct(project, image, configs['KLayout.Antenna'], {'gds': gds},
                              project / 'phase3/librelane/26-config/bridge-gds',
                              chain=[configs['Checker.KLayoutAntenna']], mounts=mounts)
    checker_error = None
    try:
        run_chain(project, image, [(s, configs[s], state) for s in ANTENNA_GDS_STEPS],
                  mounts=mounts, lane=lane, pdk_root=PDK_GUEST_ROOT)
    except Refusal as error:
        if not str(error).startswith('LL_STEP_FAILED: Checker.KLayoutAntenna'):
            raise
        checker_error = str(error)
    folder = chain_folder(project, lane, ANTENNA_GDS_STEPS, 'KLayout.Antenna')
    return {'model': 'gds', 'step': 'KLayout.Antenna', 'runset': runset,
            'state': str(folder / 'state_out.json'),
            'state_sha256': digest(folder / 'state_out.json'),
            'subject': str(gds), 'subject_sha256': digest(gds),
            'counts': {GDS_METRIC: _metrics(folder).get(GDS_METRIC)},
            'checker_error': checker_error}


def _total(counts: Dict[str, Any]) -> Optional[int]:
    values = list(counts.values())
    if not values or any(not isinstance(v, int) or isinstance(v, bool) for v in values):
        return None
    return sum(values)


def judge_antenna(router: Optional[Dict[str, Any]], gds: Optional[Dict[str, Any]],
                  shipped: Dict[str, Optional[str]]) -> Dict[str, Any]:
    """vibe-ic's two rules over the tools' counts.

    * EVIDENCE BOUND TO WHAT SHIPS: a model's count is evidence only about the
      layout whose sha256 it recorded; a count about any other state of the
      design (a pre-promotion DEF, an earlier stream) is a FAIL, the defect
      G-SHIP-ANTENNA measured (0/0 on the PnR DEF, 7 ANT.16_ii_ANT.4 on the
      shipped GDS).
    * THE MODELS MUST AGREE: the router says clean and the deck does not (or
      the reverse) is a FAIL -- one of them is wrong about this layout.

    ``shipped`` maps ``def``/``gds`` to the shipped file's sha256 (None when
    that layout does not exist yet: the router model runs before stream-out).
    """
    reasons: List[str] = []
    rows: Dict[str, Any] = {}
    for name, model, key in (('router', router, 'def'), ('gds', gds, 'gds')):
        if model is None:
            rows[name] = {'status': 'NOT_MEASURED'}
            continue
        total = _total(model['counts'])
        bound = shipped.get(key) is not None and model['subject_sha256'] == shipped.get(key)
        rows[name] = {'status': 'MEASURED' if total is not None else 'NOT_MEASURED',
                      'violations': total, 'counts': model['counts'],
                      'subject_sha256': model['subject_sha256'], 'shipped_sha256': shipped.get(key),
                      'bound_to_shipped': bound}
        if total is not None and total > 0:
            reasons.append(f'{name} model: {total} antenna violation(s)')
        if shipped.get(key) is not None and not bound:
            reasons.append(f'LL_ANTENNA_EVIDENCE_STALE: the {name} model measured '
                           f"{model['subject_sha256'][:12]}, the shipped {key} is "
                           f'{str(shipped.get(key))[:12]}')
    measured = [rows[n]['violations'] for n in ('router', 'gds') if rows[n]['status'] == 'MEASURED']
    if len(measured) == 2 and (measured[0] == 0) != (measured[1] == 0):
        reasons.append(f'LL_ANTENNA_MODELS_DISAGREE: router {measured[0]} vs GDS deck {measured[1]}')
    if reasons:
        verdict = 'FAIL'
    elif len(measured) == 2:
        verdict = 'PASS'
    else:
        verdict = 'NOT_MEASURED'
    return {'verdict': verdict, 'reasons': reasons, 'models': rows}


# --- step 26.5ic: seal ring through KLayout.SealRing --------------------------

_SEALRING_SPANS_PROBE = ('from librelane.steps.klayout import SealRing;'
                         'print(hasattr(SealRing, "die_dimensions"))')


def sealring_spans_capable(image: str) -> bool:
    """Does this image's KLayout.SealRing size the ring from x1-x0/y1-y0?
    (vibeic/librelane #3; the released 0.3.79 passes x1/y1.)"""
    completed = run_container(
        ['docker', 'run', '--rm', '--network', 'none',
         *_dmem.docker_memory_flags(), '--entrypoint', 'python3',
         image, '-c', _SEALRING_SPANS_PROBE],
        probe_deadline_s=PROBE_DEADLINE_S)
    return completed.returncode == 0 and completed.stdout.strip() == 'True'


def run_sealring(project: Path, image: str, pdk_root: Path, pdk: str, *,
                 gds_in: Path, die_rect: List[float], die_source: str,
                 lane: str = '26.5ic') -> Dict[str, Any]:
    """The PDK generator through `KLayout.SealRing`, on the declared die.

    Returns the sealed GDS the tool wrote; it is NOT verified here -- the
    caller hands it to `die_finishing_gen --sealed-by`, which measures it."""
    if len(die_rect) != 4 or die_rect[2] <= die_rect[0] or die_rect[3] <= die_rect[1]:
        raise Refusal('LL_SEALRING_DIE_INVALID', str(die_rect))
    if (die_rect[0], die_rect[1]) != (0, 0) and not sealring_spans_capable(image):
        raise Refusal('LL_SEALRING_ORIGIN_UNSUPPORTED',
                      f'{die_rect}: this image sizes the ring from x1/y1')
    configs = resolve_step_configs(project, image, pdk, list(SEALRING_STEPS),
                                   pdk_root=pdk_root, folder='26.5ic-config')
    config_path = configs['KLayout.SealRing']
    cfg = _config(config_path)
    if not cfg.get('KLAYOUT_SEALRING_SCRIPT'):
        raise Refusal('LL_SEALRING_SCRIPT_UNDECLARED', f'{pdk}: KLAYOUT_SEALRING_SCRIPT')
    replaced = cfg.get('DIE_AREA')
    cfg['DIE_AREA'] = [float(v) for v in die_rect]
    write_json(config_path, cfg)
    write_json(config_path.with_name(config_path.stem + '.overrides.json'),
               {'DIE_AREA': cfg['DIE_AREA'], 'replaced': replaced, 'source': die_source})
    mounts = [(pdk_root.resolve(), PDK_GUEST_ROOT)]
    state = state_from_direct(project, image, config_path, {'gds': gds_in},
                              project / 'phase3/librelane/26.5ic-config/bridge', mounts=mounts)
    folder = run_chain(project, image, [('KLayout.SealRing', config_path, state)],
                       mounts=mounts, lane=lane, pdk_root=PDK_GUEST_ROOT)[0]
    out = _load(folder / 'state_out.json').get('gds')
    if not out or not Path(out).is_file() or Path(out).resolve() == Path(gds_in).resolve():
        raise Refusal('LL_SEALRING_NO_OUTPUT', f'{folder}: state gds {out!r}')
    return {'step': 'KLayout.SealRing', 'state': str(folder / 'state_out.json'),
            'state_sha256': digest(folder / 'state_out.json'),
            'gds_in': str(gds_in), 'gds_in_sha256': digest(gds_in),
            'sealed_gds': str(out), 'sealed_sha256': digest(Path(out)),
            'die_area': cfg['DIE_AREA'], 'die_source': die_source,
            'script': cfg.get('KLAYOUT_SEALRING_SCRIPT')}


def xor_sealed(project: Path, image: str, pdk_root: Path, pdk: str, *,
               direct_gds: Path, tool_gds: Path, lane: str = '26.5ic-xor') -> Dict[str, Any]:
    """The dual for 26.5ic is an agreement check: both arms called the same PDK
    generator on the same die, so `KLayout.XOR` of the two sealed streams must
    be 0; anything else is a refusal."""
    configs = resolve_step_configs(project, image, pdk, ['KLayout.XOR'],
                                   pdk_root=pdk_root, folder='26.5ic-config')
    mounts = [(pdk_root.resolve(), PDK_GUEST_ROOT)]
    state = state_from_direct(project, image, configs['KLayout.XOR'],
                              {'mag_gds': direct_gds, 'klayout_gds': tool_gds},
                              project / 'phase3/librelane/26.5ic-config/bridge-xor', mounts=mounts)
    folder = run_chain(project, image, [('KLayout.XOR', configs['KLayout.XOR'], state)],
                       mounts=mounts, lane=lane, pdk_root=PDK_GUEST_ROOT)[0]
    count = _metrics(folder).get('design__xor_difference__count')
    verdict = ('NOT_MEASURED' if not isinstance(count, int) else
               'AGREE' if count == 0 else 'DISAGREE')
    return {'verdict': verdict, 'xor_difference_count': count,
            'direct_sha256': digest(direct_gds), 'tool_sha256': digest(tool_gds),
            'state': str(folder / 'state_out.json')}
