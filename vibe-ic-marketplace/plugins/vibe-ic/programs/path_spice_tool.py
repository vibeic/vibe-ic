#!/usr/bin/env python3
"""Step 30's tool arm: OpenSTA `write_path_spice` on the STAPostPNR corner.

The deck is the TOOL's (T106). OpenSTA `write_path_spice` writes, for each of
the top-N setup paths, the path's cells as subckt instances, every net's SPEF
RC network, the side-input sensitisation and the stimulus, for ngspice or
Xyce. `spice_correlation_check`'s own deck builders never read the SPEF's RC
network (measured: scaling every `*D_NET` cap by 10 moved nothing,
RULINGS CT-08); this deck carries it.

What stays vibe-ic's (the gate), applied to the tool's result:

* the POST-ROUTE BASIS: the netlist, SDC, SPEF and liberties are exactly the
  ones `OpenROAD.STAPostPNR` timed this corner with
  (`librelane_contract.post_pnr_timing_inputs`), from the native step folder,
  or the arm refuses by name;
* the LIBERTY-GRID TOLERANCE: `spice_correlation_check.
  derive_liberty_path_tolerance` over the stages the STA path reports, at the
  slew and load STA used, with no fixed percentage;
* the SAME ARC: SPICE is measured from the start pin to the end pin at the
  transitions the STA path names, at the liberty's own thresholds;
* independent PDK references at every nonzero NLDM grid corner of that arc:
  native driver waveform, the same cell view/models/PVT and actual dcalc
  slew/Ceff. The expected design delay is their original bilinear sum plus
  the unchanged STA wire residual. Raw error, PDK gap and design residual
  are all retained. Incomplete references leave the raw comparison intact;
* the SPEF-MUTATION CONTROL: every `*CAP` (and `*D_NET` total) is scaled by
  ``MUTATION_FACTOR`` and the same start/end pins are re-timed and
  re-simulated. A SPICE delay that does not move is not a post-layout
  correlation (`SPEF_UNRESPONSIVE`).

Two things the installed OpenSTA needs from its inputs, both derived, never
typed:

* its subckt reader treats the LAST token of every `X` line as a subckt name,
  so a PDK whose devices are subckts called with parameters
  (`X_i_0 ZN I VSS VPW nfet_05v0 W=8.2e-07 L=6e-07`) fails with "missing
  definitions for L=6e-07"; and every subckt port that is neither a liberty
  pin nor the power/ground name is refused (error 1606). ``fold_subckts``
  writes a derived copy of the PDK's declared `CELL_SPICE_MODELS` /
  `PAD_SPICE_MODELS` where supply ports the liberties declare at the SAME
  voltage as the power (ground) name are folded into it, and parameterised
  device lines are indented so that reader skips them (ngspice reads them
  unchanged). The source fix is a fork PR on vibeic/OpenSTA.
* `write_path_spice` dereferences the operating conditions of the library the
  path's first liberty pin belongs to; a pad library without
  `default_operating_conditions` crashes it (SIGSEGV, measured). The arm sets
  the corner's first (cell) library's own operating conditions.

The CELL VIEW is the layout's, not the schematic's (F22). The PDK's declared
`CELL_SPICE_MODELS` are schematic netlists: device W/L only, `as=ad=ps=pd=0`
(no junction capacitance) and no wiring capacitance. The liberty was
characterised on the cells' LAYOUT. MEASURED on gf180mcuD ss_125C_4v50, one
cell per deck at liberty grid points driven by the liberty's own
`normalized_driver_waveform`: the schematic view reads -35..-50% at the
smallest load (nand2_1, buf_1) and still -5%/-18% at a mid grid point, while
the same cells extracted from the PDK's own GDS read -0.4%/-4.6% there; the
model corner, temperature and supply the arm uses are already the liberty's
(changing any of them moves the error away from zero). On spm max_ss that
schematic view alone put the register-to-register path at -29%. So
``extract_cells`` extracts every standard cell the routed netlist
instantiates from the declared `CELL_GDS`, with the PDK's declared `MAGICRC`
(`libs.tech/librelane/config.tcl`), and those subckts take the place of the
schematic ones. A cell the layout cannot stand in for (absent from the GDS,
or a different port set) keeps its schematic subckt and is named; a run
with no declared layout or rcfile simulates the schematic view and says so
(`cell_view`).

Dual: ngspice and Xyce. The device models are chosen from the PDK's
`libs.tech/<simulator>` tree by what the cells instantiate; a simulator tree
that defines none of those devices refuses by name
(`LL_SPICE_DEVICE_UNMODELLED`). Two CORRELATED arms are an AGREEMENT check,
never a pick (``step_verdict``): within 1% of each other they PASS with the
ngspice number reported, beyond it the step refuses `LL_SPICE_ARMS_DISAGREE`.

chip-AGNOSTIC: no design, PDK, cell or corner literal selects a branch.
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import time
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _docker_memory as _dmem  # noqa: E402 — every `docker run` carries the ceiling
from _atomic_artefact import write_json  # noqa: E402
from librelane_contract import Refusal, _load, digest, post_pnr_timing_inputs  # noqa: E402
import spice_correlation_check as _scc  # noqa: E402 — the gate's pure helpers
import magic_extract_spice_emit as _mx  # noqa: E402

SIMULATORS = ('ngspice', 'xyce')
#: Every capacitance doubled. The CT-08 lesson scaled by 10; MEASURED on spm
#: max_ss that pushed the register-to-register path from 12.8 ns to 49.5 ns in
#: STA, past the deck's own simulation window, so no SPICE edge was left to
#: compare. A control whose perturbed run cannot be measured controls nothing.
MUTATION_FACTOR = 2.0
#: The default subject: register-to-register setup paths, whose data path is
#: standard cells only. A path through an IO pad simulates the pad's full
#: transistor netlist and its external load (MEASURED on spm: > 29 min for one
#: output-pad path in ngspice) and its timing is set by the declared IO delays.
REG_TO_REG = '-path_delay max -from [all_registers -clock_pins] -to [all_registers -data_pins]'

_VOLTAGE_MAP_RE = re.compile(r'voltage_map\s*\(\s*"?(\w+)"?\s*,\s*([-\d.eE+]+)\s*\)')
_POWER_RAIL_RE = re.compile(r'power_rail\s*\(\s*"?(\w+)"?\s*,\s*([-\d.eE+]+)\s*\)')
_OPCOND_RE = re.compile(r'^\s*operating_conditions\s*\(\s*"?([\w.]+)"?\s*\)', re.M)
_LIBRARY_RE = re.compile(r'^\s*library\s*\(\s*"?([\w.]+)"?\s*\)', re.M)
_SUBCKT_RE = re.compile(r'^\s*\.subckt\s+(\S+)(.*)$', re.I)
_PARAM_TOKEN = re.compile(r'^\w+=\S*$')


def supply_voltages(liberty_texts: Sequence[str]) -> Dict[str, float]:
    """{supply pin: volts} as the liberties declare them (`voltage_map`, and
    the operating conditions' `power_rail`). First declaration wins."""
    out: Dict[str, float] = {}
    for text in liberty_texts:
        for name, value in _VOLTAGE_MAP_RE.findall(text) + _POWER_RAIL_RE.findall(text):
            out.setdefault(name, float(value))
    return out


def fold_subckts(sources: Sequence[Path], voltages: Dict[str, float],
                 power: str, ground: str, out: Path) -> Dict[str, Any]:
    """A copy of the declared cell SPICE the installed `write_path_spice` can
    read (see the module docstring). Only supply ports at the power (ground)
    name's declared voltage are folded; any other port is left as it is, so
    OpenSTA refuses it by name rather than this function guessing."""
    if power not in voltages or ground not in voltages:
        raise Refusal('LL_SPICE_SUPPLY_UNDECLARED',
                      f'{power}/{ground} have no declared voltage in the corner liberties')
    fold = {pin: (power if volts == voltages[power] else ground)
            for pin, volts in voltages.items()
            if pin not in (power, ground) and volts in (voltages[power], voltages[ground])}
    rails = {power, ground}
    lines: List[str] = []
    folded_cells = indented = dropped = 0
    defined: set = set()
    for source in sources:
        inside = shadowed = False
        statements: List[List[str]] = []
        for raw in Path(source).read_text(errors='replace').splitlines():
            if raw.startswith('+') and statements:
                statements[-1].append(raw)
            else:
                statements.append([raw])
        for statement in statements:
            head = statement[0]
            m = _SUBCKT_RE.match(head)
            if shadowed:
                # An earlier source already defines this cell: its first
                # definition is the one simulated (the extracted view is
                # passed ahead of the declared schematic one).
                shadowed = not head.strip().lower().startswith('.ends')
                continue
            if m and m.group(1).lower() in defined:
                shadowed = True
                continue
            if m:
                defined.add(m.group(1).lower())
                inside = True
                ports = m.group(2).split()
                kept = [p for p in ports if p not in fold]
                for p in ports:
                    if p in fold and fold[p] not in kept:
                        kept.append(fold[p])
                folded_cells += kept != ports
                lines.append(f'.subckt {m.group(1)} ' + ' '.join(kept))
                lines += statement[1:]
                continue
            if inside and head.strip().lower().startswith('.ends'):
                inside = False
                lines += statement
                continue
            kind = head[:1].lower()
            if not inside or kind not in 'xmdcr' or not head.strip():
                lines += statement
                continue
            tokens = [fold.get(t, t) for t in head.split()]
            words = [t for t in tokens[1:] + ' '.join(statement[1:]).replace('+', ' ').split()
                     if not _PARAM_TOKEN.match(t)]
            nodes = {'x': words[:-1], 'm': words[:4], 'd': words[:2],
                     'c': words[:2], 'r': words[:2]}[kind]
            if nodes and set(nodes) <= rails:
                # Every terminal on a supply the deck drives from an ideal
                # source: the element carries no signal (decoupling / ESD
                # capacitance and diodes between rails).
                dropped += 1
                continue
            body = ' '.join(tokens)
            if kind == 'x' and any(_PARAM_TOKEN.match(t) for t in tokens[1:]
                                   + ' '.join(statement[1:]).replace('+', ' ').split()):
                # A device call carries parameters; the installed reader would
                # take its last parameter for a subckt name.
                indented += 1
                body = ' ' + body
            lines.append(body)
            lines += statement[1:]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(lines) + '\n')
    return {'path': str(out), 'folded': fold, 'cells_folded': folded_cells,
            'device_lines_indented': indented, 'rail_only_elements_dropped': dropped,
            'sources': {str(s): digest(Path(s)) for s in sources}}


def device_names(subckt_text: str) -> set:
    """Devices the cells instantiate: the subckt an `X` line calls (its last
    non-parameter token) and the model an `M` or `D` line names."""
    out = set()
    statement = ''
    for raw in subckt_text.splitlines() + ['']:
        if raw.startswith('+'):
            statement += ' ' + raw[1:]
            continue
        tokens = statement.split()
        if tokens and tokens[0][:1] in 'Xx':
            names = [t for t in tokens[1:] if not _PARAM_TOKEN.match(t)]
            if names:
                out.add(names[-1].lower())
        elif tokens and tokens[0][:1] in 'Mm' and len(tokens) >= 6:
            out.add(tokens[5].lower())
        elif tokens and tokens[0][:1] in 'Dd' and len(tokens) >= 4:
            out.add(tokens[3].lower())
        statement = raw.strip()
    cells = {m.group(1).lower() for m in
             (_SUBCKT_RE.match(line) for line in subckt_text.splitlines()) if m}
    return out - cells


_LIB_OPEN_RE = re.compile(r"^\s*\.lib\s+([A-Za-z0-9_]+)\s*$", re.I)
_LIB_REF_RE = re.compile(r"^\s*\.lib\s+['\"]?([^'\"\s]+)['\"]?\s+([A-Za-z0-9_]+)\s*$", re.I)
_DEF_RE = re.compile(r"^\s*\.(?:subckt|model)\s+(\S+)", re.I)


def model_sections(tech_dir: Path, simulator: str) -> Dict[Tuple[str, str], set]:
    """{(file, section): every device name the section defines, following its
    `.lib <file> <section>` references}. Files carrying the simulator's own
    suffix are read when there are any (a PDK ships one tree per dialect)."""
    files = sorted(p for p in Path(tech_dir).glob('*') if p.is_file())
    own = [p for p in files if p.suffix.lstrip('.').lower() == simulator.lower()]
    files = own or files
    direct: Dict[Tuple[str, str], set] = {}
    refs: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
    for path in files:
        current = None
        for line in path.read_text(errors='replace').splitlines():
            if line.lstrip().lower().startswith('.endl'):
                current = None
                continue
            opened = _LIB_OPEN_RE.match(line)
            if opened and current is None:
                current = (str(path), opened.group(1))
                direct.setdefault(current, set())
                refs.setdefault(current, [])
                continue
            if current is None:
                continue
            ref = _LIB_REF_RE.match(line)
            if ref:
                target = Path(tech_dir) / Path(ref.group(1)).name
                target = target if target in files else path
                refs[current].append((str(target), ref.group(2)))
                continue
            defined = _DEF_RE.match(line)
            if defined:
                direct[current].add(defined.group(1).lower())
    closure: Dict[Tuple[str, str], set] = {}

    def resolve(key: Tuple[str, str], seen: set) -> set:
        if key in closure:
            return closure[key]
        out = set(direct.get(key, set()))
        for ref in refs.get(key, []):
            if ref not in seen:
                out |= resolve(ref, seen | {ref})
        closure[key] = out
        return out
    for key in direct:
        resolve(key, {key})
    return closure


def model_file(tech_dir: Path, guest_dir: str, simulator: str, liberty: str,
               devices: set, temperature: Optional[float], out: Path) -> Dict[str, Any]:
    """The `-model_file` for one corner: the PDK's parameter preludes, then, for
    every device the cells call, the library section `select_model_section`
    picks for the corner's liberty among the sections that define it."""
    sections = model_sections(tech_dir, simulator)
    chosen: List[Tuple[str, str]] = []
    covered: set = set()
    for device in sorted(devices):
        if device in covered:
            continue
        candidates = [key for key, defined in sections.items() if device in defined]
        pick = _scc.select_model_section(candidates, liberty)
        if pick is None:
            continue
        chosen.append(tuple(pick))
        covered |= sections[tuple(pick)]
    missing = sorted(devices - covered)
    if missing:
        raise Refusal('LL_SPICE_DEVICE_UNMODELLED',
                      f'{simulator}: no section under {tech_dir} defines {missing}')
    files = sorted(p for p in Path(tech_dir).glob('*') if p.is_file())
    own = [p for p in files if p.suffix.lstrip('.').lower() == simulator.lower()] or files
    preludes = [p for p in own
                if re.search(r'^\s*\.param\s', p.read_text(errors='replace'), re.M | re.I)
                and not re.search(r'^\s*\.lib\s', p.read_text(errors='replace'), re.M | re.I)]
    guest = lambda p: f'{guest_dir}/{Path(p).name}'  # noqa: E731
    lines = [f'* vibe-ic step 30: device models for {liberty} ({simulator})']
    lines += [f'.include {guest(p)}' for p in preludes]
    lines += [f'.lib {guest(f)} {s}' for f, s in chosen]
    if temperature is not None:
        lines.append(f'.temp {temperature:g}' if simulator == 'ngspice'
                     else f'.options device temp={temperature:g}')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(lines) + '\n')
    return {'path': str(out), 'sections': [list(c) for c in chosen],
            'preludes': [str(p) for p in preludes], 'temperature': temperature,
            'devices': sorted(devices)}


def declared_sta_late_derate(transcript: str) -> float:
    """Read uniform data-delay derating from evaluated native SDC commands."""
    factors = {}
    unbound = False
    for event in re.findall(r'^VIBEIC_STA_DERATE (.*)$', transcript, re.M):
        words = event.split()
        if not words:
            unbound = True
            continue
        command, *args = words
        if command == 'unset_timing_derate' and not args:
            factors, unbound = {}, False
            continue
        flags = {arg for arg in args if arg.startswith('-')}
        values = [arg for arg in args if not arg.startswith('-')]
        if (command != 'set_timing_derate'
                or not flags <= {'-early', '-late', '-clock', '-data', '-rise', '-fall',
                                 '-cell_delay', '-net_delay', '-cell_check'}):
            unbound = True
            continue
        if (('-early' in flags and '-late' not in flags)
                or ('-clock' in flags and '-data' not in flags)):
            continue
        kinds = {kind for kind in ('cell_delay', 'net_delay') if '-' + kind in flags}
        if not kinds:
            if '-cell_check' in flags:
                continue
            kinds = {'cell_delay', 'net_delay'}
        if len(values) != 1:
            unbound = True
            continue
        edges = {edge for edge in ('rise', 'fall') if '-' + edge in flags} or {'rise', 'fall'}
        try:
            factor = float(values[0])
        except ValueError:
            unbound = True
            continue
        if not math.isfinite(factor) or factor <= 0:
            unbound = True
            continue
        factors.update({(kind, edge): factor for kind in kinds for edge in edges})
    if unbound or len(factors) != 4 or len(set(factors.values())) != 1:
        raise Refusal('LL_STA_DERATE_UNDECLARED',
                      'native SDC declared no readable uniform late data-delay derate')
    return next(iter(factors.values()))


def arm_tcl(inputs: Dict[str, Any], project: Path, top: str, spef: str,
            opcond: Tuple[str, str], path_args: List[str], deck_dir: Path,
            cells: str, models: str, power: str, ground: str, simulator: str) -> str:
    """One `sta` session: the corner's own inputs, then for each path its
    `report_checks` and its `write_path_spice`."""
    lines = ['set_cmd_units -time ns -capacitance pF -current mA -voltage V '
             '-resistance kOhm -distance um']
    lines += [f'read_liberty {lib}' for lib in inputs['liberties']]
    lines += [f'read_verilog {project / inputs["sta_netlist"]}', f'link_design {top}',
              'proc _vibeic_sta_derate {command op} {',
              'puts [list VIBEIC_STA_DERATE [namespace tail [lindex $command 0]] {*}[lrange $command 1 end]]',
              '}',
              'trace add execution [namespace origin set_timing_derate] enter _vibeic_sta_derate',
              'trace add execution [namespace origin unset_timing_derate] enter _vibeic_sta_derate',
              f'read_sdc {project / inputs["sdc"]}',
              'trace remove execution [namespace origin set_timing_derate] enter _vibeic_sta_derate',
              'trace remove execution [namespace origin unset_timing_derate] enter _vibeic_sta_derate',
              'rename _vibeic_sta_derate {}',
              f'set_operating_conditions -library {opcond[0]} {opcond[1]}',
              'set_propagated_clock [all_clocks]', f'read_spef {spef}']
    lines += [f'set _cf [open {deck_dir}/reference_clocks.txt w]',
              'foreach _clock [all_clocks] { puts $_cf [get_property $_clock period] }',
              'close $_cf']
    for index, args in enumerate(path_args, 1):
        lines.append(f'report_checks {args} -fields {{slew cap input_pins}} -digits 6 '
                     f'-format full > {deck_dir}/path_{index}.rpt')
        lines.append(f'if {{[catch {{write_path_spice -path_args {{{args}}} '
                     f'-spice_file {deck_dir}/path_{index}.sp -lib_subckt_files {{{cells}}} '
                     f'-model_file {models} -power {power} -ground {ground} '
                     f'-simulator {simulator}}} _e]}} {{ puts "VIBEIC_WPS_FAIL {index} $_e" }} '
                     f'else {{ puts "VIBEIC_WPS_OK {index}" }}')
        # Total net capacitance in report_checks is not the effective load
        # used by the NLDM lookup. Ask this same native STA session, after
        # writing the original design deck, for each selected path's dcalc.
        lines += [f'set _pn 0; foreach _path [find_timing_paths {args}] {{',
                  'incr _pn; set _prev ""; set _an 0',
                  f'set _idx [open {deck_dir}/dcalc_{index}_$_pn.tsv w]',
                  'foreach _point [get_property $_path points] {',
                  'set _pin [get_full_name [get_property $_point pin]]',
                  'if {$_prev != "" && [file dirname $_prev] == [file dirname $_pin]} {',
                  f'incr _an; set _file {deck_dir}/dcalc_{index}_${{_pn}}_${{_an}}.rpt',
                  'if {![catch {report_dcalc -from $_prev -to $_pin -max -digits 9 > $_file} _err]} {',
                  'puts $_idx "$_prev\t$_pin\t$_file"',
                  '}', '}', 'set _prev $_pin', '}', 'close $_idx', '}']
    return '\n'.join(lines) + '\n'


def _docker(image: str, project: Path, mounts: List[Tuple[Path, str]], argv: List[str],
            cwd: Path, docker: str = 'docker', env: Optional[Dict[str, str]] = None
            ) -> subprocess.CompletedProcess:
    volumes = ['-v', f'{project.resolve()}:{project.resolve()}']
    for host, guest in mounts:
        volumes += ['-v', f'{Path(host).resolve()}:{guest}:ro']
    for key, value in (env or {}).items():
        volumes += ['-e', f'{key}={value}']
    import librelane_contract as ll
    network, native_argv = ll.native_tool_command(image, argv)
    command = [docker, 'run', '--rm', '--network', network,
               *_dmem.docker_memory_flags(), *volumes, '--workdir', str(cwd),
               '--entrypoint', native_argv[0], image, *native_argv[1:]]
    # The producer is called inside execution_resource_lease.native_boundary.
    # Calling the source-owned runner lets that boundary bind the issued
    # share, watchdog, CID, cancellation and terminal command record.
    started = time.monotonic_ns()
    result = ll.run_container(command, supervised=True)
    ended = time.monotonic_ns()
    result._vibeic_lifecycle = {'pid': os.getpid(), 'cid': None,
                                'rc': result.returncode,
                                'start_ns': started, 'end_ns': ended}
    return result


# --- the cell view: the layout the liberty was characterised on ------------

#: Where a PDK declares its Magic rcfile for its own flow.
_PDK_FLOW_CONFIGS = ('libs.tech/librelane/config.tcl', 'libs.tech/openlane/config.tcl')
_EXTRACTION_CORNERS = Path(__file__).with_name('magic_extraction_corners.json')
_MAGICRC_RE = re.compile(r'^\s*set\s+::env\(MAGICRC\)\s+"?([^"\s]+)"?', re.M)
_INSTANCE_RE = re.compile(r'^\s*([A-Za-z_][\w$]*)\s+(?:#\s*\(.*?\)\s*)?\\?\S+\s*\(', re.M)


def pdk_magicrc(pdk_dir: Path, guest_root: str, pdk: str) -> Optional[Tuple[str, str]]:
    """(guest path, source) of the Magic rcfile the PDK's own flow config
    declares, its `$::env(PDK_ROOT)`/`$::env(PDK)` resolved to the guest."""
    for rel in _PDK_FLOW_CONFIGS:
        path = Path(pdk_dir) / rel
        m = _MAGICRC_RE.search(path.read_text(errors='replace')) if path.is_file() else None
        if m:
            value = (m.group(1).replace('$::env(PDK_ROOT)', guest_root)
                     .replace('$::env(PDK)', pdk))
            if '$' not in value:
                return value, f'{rel}:MAGICRC'
    return None


_DEVICE_LINE_RE = re.compile(r'^\s*[xXmMdD]\S*\s')


def subckt_ports(text: str) -> Dict[str, List[str]]:
    """{subckt name: its ports in declaration order}."""
    return {name: ports for name, (ports, _) in subckt_devices(text).items()}


def subckt_devices(text: str) -> Dict[str, Tuple[List[str], int]]:
    """{subckt name: (its ports in declaration order, how many device lines
    -- transistor, diode or subckt call -- it holds)}. First definition wins."""
    out: Dict[str, Tuple[List[str], int]] = {}
    current = None
    from analog_a7_post_layout_emit import _joined_lines
    for line in _joined_lines(text):
        m = _SUBCKT_RE.match(line)
        if m:
            current = None if m.group(1) in out else m.group(1)
            if current:
                out[current] = ([p for p in m.group(2).split() if not _PARAM_TOKEN.match(p)], 0)
        elif line.strip().lower().startswith('.ends'):
            current = None
        elif current and _DEVICE_LINE_RE.match(line):
            ports, n = out[current]
            out[current] = (ports, n + 1)
    return out


def _resistive_internal_ports(body: str, extra: set, public: set) -> bool:
    """Magic may expose resistance-split contact nodes as extra ports.

    They can stay internal to the original public cell interface only when
    each has a positive-resistance path to exactly one public port. Keep
    the native node names and all resistor/device lines unchanged.
    """
    graph: Dict[str, set] = {}
    for line in body.splitlines():
        words = line.split()
        if len(words) != 4 or not words[0].lower().startswith('r'):
            continue
        try:
            value = float(words[3])
        except ValueError:
            continue
        if not math.isfinite(value) or value <= 0:
            continue
        a, b = words[1:3]
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)
    for node in extra:
        seen, pending = set(), [node]
        while pending:
            item = pending.pop()
            if item not in seen:
                seen.add(item)
                pending.extend(graph.get(item, set()) - seen)
        if len(seen & public) != 1:
            return False
    return True


def netlist_cells(netlist_text: str, known: Sequence[str]) -> List[str]:
    """The cells among `known` the structural netlist instantiates."""
    used = set(_INSTANCE_RE.findall(netlist_text))
    return sorted(c for c in known if c in used)


def extraction_tcl(gds: Sequence[str], cells: Sequence[str], out_dir: Path, *,
                   extract_style: Optional[str] = None) -> str:
    """One Magic session: the declared cell GDS read once, then each cell
    extracted with the existing full parasitic-RC recipe. An absent style
    leaves the PDK rcfile's selection intact; it does not assert a corner."""
    lines = ['gds readonly true', 'gds rescale false']
    lines += [f'gds read {g}' for g in gds]
    if (extract_style or '').strip():
        # Style selection reloads Magic's technology and global extraction
        # state. Select it once for this session, before extracting any cell.
        lines.append(f'extract style {extract_style.strip()}')
    for cell in cells:
        lines += [f'extract path {out_dir}', _mx.build_extraction_tcl(
            cell, str(out_dir / f'{cell}.spice'),
            _mx.MagicResimExtractOptions(extract_style=None))]
    return '\n'.join(lines + ['quit -noprompt']) + '\n'


def extraction_corner(pdk: str, pdk_dir: Path, liberty: str) -> dict:
    """Only the selected kit/library's cited PEX declaration selects a style.

    SS alone is not a parasitic corner. The registry carries the PDK's own
    library-corner mapping; its primary revision/hash are provenance, not a
    runtime revision-pinning gate.
    """
    registry = _load(_EXTRACTION_CORNERS)
    selected = next((row for row in registry.get('pdks', []) if row.get('name') == pdk), {})
    binding = selected.get('magic_extraction') or {}
    style = binding.get('liberties', {}).get(Path(liberty).name)
    if not style:
        return {'status': 'UNQUALIFIED', 'liberty': liberty, 'style': None,
                'reason': 'no declared PDK/library extraction-corner mapping'}
    # Reuse the existing technology reader; a declaration cannot select a
    # style absent from the installed technology.
    from analog_a7_post_layout_emit import extraction_styles
    tech = pdk_dir / binding['tech']
    if style not in extraction_styles(tech):
        raise Refusal('LL_SPICE_EXTRACTION_STYLE_UNDECLARED', f'{style}: {tech}')
    return {'status': 'QUALIFIED', 'liberty': liberty, 'style': style,
            'tech': str(tech), 'source': binding['source']}


def extract_cells(image: str, project: Path, mounts: List[Tuple[Path, str]], *,
                  gds: Sequence[str], magicrc: str, guest_root: str,
                  schematic: Dict[str, List[str]], cells: Sequence[str],
                  out_dir: Path, extract_style: Optional[str] = None) -> Dict[str, Any]:
    """The layout view of `cells`, one subckt per cell in the schematic's
    port order, written to `out_dir/cells_extracted.spice`. A cell whose
    extraction has no device, or whose ports are not the schematic's, is
    left to its schematic subckt and named in `kept_schematic`."""
    work = out_dir / 'extract'
    work.mkdir(parents=True, exist_ok=True)
    # These exports belong to this producer. Absence before Magic makes a
    # subsequently consumed export evidence of this invocation, not a retry's.
    for cell in cells:
        for suffix in ('.spice', '.ext', '.res.ext'):
            (work / (cell + suffix)).unlink(missing_ok=True)
    (out_dir / 'cells_extracted.spice').unlink(missing_ok=True)
    tcl = work / 'extract.tcl'
    tcl.write_text(extraction_tcl(gds, cells, work, extract_style=extract_style))
    run = _docker(image, project, mounts,
                  ['magic', '-dnull', '-noconsole', '-rcfile', magicrc, str(tcl)], work,
                  env={'PDK_ROOT': guest_root})
    (work / 'magic.log').write_text(run.stdout + '\n' + run.stderr)
    kept: Dict[str, str] = {}
    missing_exports = []
    body: List[str] = []
    for cell in cells:
        path = work / f'{cell}.spice'
        if not path.is_file() or not path.stat().st_size:
            missing_exports.append(cell)
        text = path.read_text(errors='replace') if path.is_file() else ''
        ports, devices = subckt_devices(text).get(cell, ([], 0))
        start = re.search(r'^\.subckt\s+' + re.escape(cell)
                          + r'\b[^\n]*(?:\n\+[^\n]*)*', text, re.M | re.I)
        end = re.search(r'^\.ends\b.*$', text[start.end():], re.M | re.I) if start else None
        inner = text[start.end():start.end() + end.start()].strip('\n') if end else ''
        if not ports or not devices:
            kept[cell] = 'no device extracted from the declared layout'
            continue
        public = set(schematic[cell])
        extra = set(ports) - public
        generated = not extra
        if extra:
            original = work / f'{cell}.ext'
            resistance = work / f'{cell}.res.ext'
            original_text = original.read_text(errors='replace') if original.is_file() else ''
            resistance_text = resistance.read_text(errors='replace') if resistance.is_file() else ''
            original_ports = set(re.findall(r'^port\s+"([^"]+)"', original_text, re.M))
            original_nodes = set(re.findall(r'^(?:port|node|substrate)\s+"([^"]+)"',
                                            original_text, re.M))
            split_nodes = set(re.findall(r'^rnode\s+"([^"]+)"', resistance_text, re.M))
            generated = original_ports == public and extra <= split_nodes - original_nodes
        if (not public <= set(ports)
                or not generated
                or not _resistive_internal_ports(inner, extra, public)):
            kept[cell] = f'layout ports {sorted(ports)} are not the schematic ports'
            continue
        body += [f'.subckt {cell} ' + ' '.join(schematic[cell]), inner, '.ends']
    out = out_dir / 'cells_extracted.spice'
    out.write_text('* vibe-ic step 30: cells extracted from the declared layout\n'
                   + '\n'.join(body) + '\n')
    return {'path': str(out), 'magic_rc': run.returncode, 'magicrc': magicrc,
            'magic_execution': {'tool': 'Magic', 'rc': run.returncode,
                'argv': ['magic', '-dnull', '-noconsole', '-rcfile', magicrc, str(tcl)],
                'script': str(tcl), 'log': str(work / 'magic.log')},
            'extracted': sorted(set(cells) - set(kept)), 'kept_schematic': kept,
            'missing_exports': missing_exports}


def cell_view(image: str, project: Path, mounts: List[Tuple[Path, str]], *, config: dict,
              pdk_dir: Path, guest_root: str, pdk: str, netlist: Path,
              cell_sources: Sequence[Path], out_dir: Path,
              liberty: str = '') -> Dict[str, Any]:
    """Which standard-cell netlists the deck simulates, and why (module
    docstring). `cell_sources` are the declared `CELL_SPICE_MODELS`; pads keep
    their declared netlists (the arm's subject is register to register)."""
    schematic: Dict[str, List[str]] = {}
    inert: set = set()
    for source in cell_sources:
        for name, (ports, devices) in subckt_devices(Path(source).read_text(errors='replace')).items():
            if name not in schematic:
                schematic[name] = ports
                if not devices:
                    # No device in the declared netlist (fill, tie-less
                    # spacers): nothing to simulate in either view.
                    inert.add(name)
    gds = list(config.get('CELL_GDS') or [])
    rc = pdk_magicrc(pdk_dir, guest_root, pdk)
    if not gds or rc is None:
        return {'view': 'schematic', 'sources': [],
                'reason': ('no CELL_GDS declared' if not gds else
                           'no MAGICRC declared in ' + ' or '.join(_PDK_FLOW_CONFIGS))}
    used = netlist_cells(Path(netlist).read_text(errors='replace'),
                         [c for c in schematic if c not in inert])
    corner = extraction_corner(pdk, pdk_dir, liberty)
    got = extract_cells(image, project, mounts, gds=gds, magicrc=rc[0], guest_root=guest_root,
                        schematic=schematic, cells=used, out_dir=out_dir,
                        extract_style=corner['style'])
    view = ('layout-extracted' if got['extracted'] and not got['kept_schematic'] else
            'mixed' if got['extracted'] else 'schematic')
    return {'view': view, 'sources': [Path(got['path'])] if got['extracted'] else [],
            'magicrc_source': rc[1], 'gds': gds, 'extraction_corner': corner, **got}


# --- waveform and measurement --------------------------------------------

def read_waveform(path: Path, simulator: str) -> Dict[str, List[Tuple[float, float]]]:
    """{node: [(t, v)]} from the simulator's table: ngspice `wrdata` with
    `wr_vecnames`/`wr_singlescale`, or Xyce's `.print` table (`.prn`, or the
    `format=csv` file the tool's deck names). Node names are keyed lowercase
    with `v(...)` and escapes removed."""
    raw = path.read_text(errors='replace').splitlines()
    split = (lambda line: line.split(',')) if raw and ',' in raw[0] else str.split  # noqa: E731
    lines = [[w.strip() for w in split(line)] for line in raw if line.split()]
    lines = [[w for w in line if w] for line in lines]
    head = lines[0]
    rows = [r for r in lines[1:] if len(r) == len(head)]
    key = lambda n: re.sub(r'^v\((.*)\)$', r'\1', n.lower()).replace('\\', '')  # noqa: E731
    t = next(i for i, n in enumerate(head) if n.lower() == 'time')
    skip = {t} | ({head.index('Index')} if simulator == 'xyce' and 'Index' in head else set())
    return {key(name): [(float(r[t]), float(r[i])) for r in rows]
            for i, name in enumerate(head) if i not in skip}


def crossings(wave: List[Tuple[float, float]], level: float, edge: str) -> List[float]:
    """Linear-interpolated times `wave` crosses `level` rising or falling."""
    out = []
    for (t0, v0), (t1, v1) in zip(wave, wave[1:]):
        if edge == 'rise' and v0 < level <= v1 or edge == 'fall' and v0 > level >= v1:
            out.append(t0 + (level - v0) * (t1 - t0) / (v1 - v0) if v1 != v0 else t1)
    return out


#: A `report_checks -fields {slew cap input_pins} -format full` data row:
#: `[cap] slew delay time <v|^> <pin> (<cell>)`. An input-pin row prints no
#: cap (three numbers), a driver row prints it (four).
_PATH_ROW_RE = re.compile(
    r"^\s*(?:(-?[\d.]+)\s+)?(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+([v^])\s+(\S+)\s+\(([^)]+)\)\s*$")


def parse_path_report(text: str) -> Optional[Dict[str, Any]]:
    """One path of `report_checks -format full` with `slew cap input_pins`:
    the data rows up to `data arrival time`, and the start and end the STA
    measures between (the start pin's row -- a launching flop's clock pin or
    an input port -- to the endpoint's)."""
    start = re.search(r"^Startpoint:\s+(\S+)", text, re.M)
    end = re.search(r"^Endpoint:\s+(\S+)", text, re.M)
    body = text.split('data arrival time')[0]
    rows = []
    for line in body.splitlines():
        m = _PATH_ROW_RE.match(line)
        if not m:
            continue
        cap, slew, incr, time_, tr, pin, cell = m.groups()
        rows.append({'cap_pf': float(cap) if cap is not None else None,
                     'slew_ns': float(slew), 'incr': float(incr), 'time': float(time_),
                     'tr': tr, 'pin': pin, 'cell': cell,
                     'inst': pin.rsplit('/', 1)[0] if '/' in pin else pin})
    if not (start and end and rows):
        return None
    first = next((r for r in rows if r['inst'] == start.group(1) or r['cell'] == 'in'), rows[0])
    if _scc.is_sequential_cell(first['cell']):
        # A launching register: the comparison is its combinational cone,
        # from its output pin, as the direct gate's is -- the flop's own
        # clock-to-output arc has no cell_rise/fall table on the related pin
        # `derive_liberty_path_tolerance` reads first.
        first = next((r for r in rows[rows.index(first) + 1:]
                      if r['inst'] == first['inst']), first)
    return {'startpoint': start.group(1), 'endpoint': end.group(1),
            'start_row': first, 'rows': rows[rows.index(first):],
            'start_time_ns': first['time'], 'end_time_ns': rows[-1]['time'],
            'path_delay_ns': round(rows[-1]['time'] - first['time'], 9),
            'endpoint_transition': 'fall' if rows[-1]['tr'] == 'v' else 'rise'}


def path_stages(rows: List[dict]) -> List[dict]:
    """Stages for the tolerance: each cell's input-pin row then output-pin row."""
    stages = []
    for prev, row in zip(rows, rows[1:]):
        if prev['inst'] == row['inst'] and '/' in prev['pin'] and '/' in row['pin'] \
                and row['cell'] not in ('in', 'out') and not _scc.is_sequential_cell(row['cell']):
            stages.append({'inst': row['inst'], 'cell': row['cell'],
                           'toggle_pin': prev['pin'].rsplit('/', 1)[1],
                           'out_pin': row['pin'].rsplit('/', 1)[1],
                           'input_transition': 'fall' if prev['tr'] == 'v' else 'rise',
                           'transition': 'fall' if row['tr'] == 'v' else 'rise',
                           'input_slew_ns': prev.get('slew_ns'),
                           'sta_load_pf': row.get('cap_pf'), 'sta_delay_ns': row['incr']})
    return stages


def _reference_sources(arm: dict, stages: List[dict], deck: Path) -> dict:
    """Selected Liberty/view and the *executed WPS* arc's literal side DC.

    Only the native gate block/instance/voltage-source grammar is read here.
    A dynamic side input or a different output/condition stays unqualified.
    """
    text, sources = deck.read_text().replace('\\/', '/'), {}
    cells = Path(arm['cells']['path']).read_text()
    ports = subckt_ports(cells)
    for index, stage in enumerate(stages):
        library = next((lib for lib in arm.get('liberty_sources', [])
                        if _scc.extract_cell_block(lib['text'], stage['cell'])), None)
        if library is None:
            continue
        gate = re.search(r'^\* Gate ' + re.escape(stage['inst']) + r' '
                         + re.escape(stage['toggle_pin']) + r' -> '
                         + re.escape(stage['out_pin']) + r'\s*\n(.*?)(?=^\*|^\.ends)',
                         text, re.M | re.S)
        if gate is None:
            continue
        lines = gate.group(1).splitlines()
        call = next((line.split() for line in lines if line.startswith('x' + stage['inst'] + ' ')), [])
        pins = ports.get(stage['cell'], [])
        if not call or call[-1] != stage['cell'] or len(call) != len(pins) + 2:
            continue
        nodes = dict(zip(pins, call[1:-1]))
        dc = {m[1]: float(m[2]) for line in lines
              if (m := re.fullmatch(r'v\d+\s+(\S+)\s+0\s+([-\d.eE+]+)', line))}
        header = _scc.parse_liberty_header(library['text'])
        lookup = stage.get('dcalc')
        if lookup and Path(lookup).is_file():
            dcalc = Path(lookup).read_text()
            name = _LIBRARY_RE.search(library['text'])
            if (not name or not re.search(r'^Library: ' + re.escape(name[1]) + r'\s*$', dcalc, re.M)
                    or not re.search(r'^Cell: ' + re.escape(stage['cell']) + r'\s*$', dcalc, re.M)):
                continue
            rf = lambda edge: 'v' if edge == 'fall' else '^'
            arc = re.compile(r'^' + re.escape(stage['toggle_pin']) + ' '
                             + re.escape(rf(stage['input_transition'])) + r' -> '
                             + re.escape(stage['out_pin']) + ' '
                             + re.escape(rf(stage['transition'])) + r'\s*$', re.M)
            candidates = set()
            for match in arc.finditer(dcalc):
                block = dcalc[match.end():].split('.............................................')[0]
                slew = re.search(r'input_net_transition =\s*([-\d.eE+]+)', block)
                cap = re.search(r'total_output_net_capacitance =\s*([-\d.eE+]+)', block)
                delay = re.search(r'^Delay =\s*([-\d.eE+]+)', block, re.M)
                # Match the same summed print + float codec as the grid
                # projection; isclose would take max and reject valid rows.
                if slew and cap and delay and abs(
                        float(delay[1]) * header['time_unit_ns'] - stage['sta_delay_ns']
                        ) <= .5e-6 + abs(stage['sta_delay_ns']) * 2 ** -21:
                    candidates.add((float(slew[1]) * header['time_unit_ns'],
                                    float(cap[1]) * header['cap_unit_pf']))
            if len(candidates) == 1:
                stage['lookup_input_slew_ns'], stage['lookup_cap_pf'] = candidates.pop()
        if 'lookup_cap_pf' not in stage:
            continue
        inputs, _ = _scc.liberty_pins(_scc.extract_cell_block(library['text'], stage['cell']))
        side = {}
        for pin in inputs:
            if pin == stage['toggle_pin']:
                continue
            voltage = dc.get(nodes.get(pin))
            if voltage == 0:
                side[pin] = 0
            elif voltage == header['nom_voltage']:
                side[pin] = 1
        stage['side_inputs'] = side
        block = _scc.extract_subckt(cells, stage['cell'], model_map={})
        if block is None:
            continue
        sources[index] = {**library, 'identity': {
            'liberty_sha256': library['sha256'], 'corner': arm['corner'],
            'voltage': header['nom_voltage'], 'temperature': header['nom_temperature'],
            'cell_view_sha256': hashlib.sha256(block[1].encode()).hexdigest(),
            'models_sha256': digest(Path(arm['models']['path']))}}
    return sources


def _native_grid_reference(arm: dict, directory: Path, source: dict, request: dict) -> dict:
    """One independent cell/grid point, native NDW + true Pi load, normal runner.

    No design netlist, SPEF, wire or measured delay enters this circuit.
    Native write_path_spice owns its stimulus and extracted-cell subckt.
    """
    directory.mkdir(parents=True, exist_ok=True)
    liberty, hdr = source['text'], _scc.parse_liberty_header(source['text'])
    opc, libname = _OPCOND_RE.search(liberty), _LIBRARY_RE.search(liberty)
    result = {'identity': request['identity'], 'status': 'NOT_MEASURED', 'executions': []}
    # Do not silently substitute the legacy linear reference for an absent NDW.
    if not opc or not libname or 'normalized_driver_waveform' not in liberty:
        return {**result, 'reason': 'selected Liberty has no native driver-waveform basis'}
    cell = _scc.extract_cell_block(liberty, request['cell'])
    inputs, _ = _scc.liberty_pins(cell)
    connection = {pin: ('I' if pin == request['toggle_pin'] else
                       f"1'b{request['side_inputs'][pin]}") for pin in inputs}
    connection[request['out_pin']] = 'Z'
    netlist, sdc, tcl = (directory / name for name in ('reference.v', 'reference.sdc', 'reference.tcl'))
    netlist.write_text('module pdk_ref(input I, output Z);\n ' + request['cell']
                       + ' u_ref(' + ', '.join(f'.{p}({n})' for p, n in connection.items())
                       + ');\nendmodule\n')
    # The virtual clock carries the original declared cycle, not a guessed
    # settling time. This reference's output load is a real native Pi model.
    periods = set(arm.get('clock_periods_ns') or [])
    if len(periods) != 1:
        return {**result, 'reason': 'reference clock period is not uniquely declared'}
    sdc.write_text(f'create_clock -name VREF -period {periods.pop():.17g}\n'
                   'set_input_delay 0 -clock VREF [get_ports I]\n'
                   'set_output_delay 0 -clock VREF [get_ports Z]\n'
                   f"set_input_transition -{request['input_transition']} "
                   f"{request['grid_input_slew_ns']:.17g} [get_ports I]\n")
    args = (f"-path_delay max -{request['input_transition']}_from I "
            f"-{request['transition']}_to Z -group_path_count 1")
    tcl.write_text('set_cmd_units -time ns -capacitance pF -current mA -voltage V '
                   '-resistance kOhm -distance um\n'
                   f"read_liberty {source['path']}\nread_verilog {netlist}\n"
                   f'link_design pdk_ref\nread_sdc {sdc}\n'
                   f'set_operating_conditions -library {libname[1]} {opc[1]}\n'
                   f"sta::set_pi_model u_ref/{request['out_pin']} "
                   f"{request['grid_output_load_pf']:.17g} 0 0\n"
                   f'report_checks {args} -fields {{slew cap input_pins}} -digits 9 '
                   f'-format full > {directory}/reference.rpt\n'
                   f'write_path_spice -path_args {{{args}}} -spice_file {directory}/reference.sp '
                   f"-lib_subckt_files {{{arm['cells']['path']}}} -model_file {arm['models']['path']} "
                   f"-power {arm['power']} -ground {arm['ground']} -simulator {arm['simulator']}\n")
    argv = ['sta', '-no_init', '-no_splash', '-exit', str(tcl)]
    sta = _docker(arm['image'], arm['project'], arm['mounts'], argv, directory)
    log = directory / 'sta.log'
    log.write_text(sta.stdout + '\n' + sta.stderr)
    result['executions'].append({'tool': 'OpenSTA', 'rc': sta.returncode, 'argv': argv,
                                 'script': str(tcl), 'log': str(log)})
    rpt, deck = directory / 'reference.rpt', directory / 'reference.sp_1.sp'
    parsed = parse_path_report(rpt.read_text()) if rpt.is_file() else None
    if sta.returncode != 0 or parsed is None or not deck.is_file():
        return {**result, 'reason': 'native reference STA/write_path_spice did not complete'}
    stages = path_stages(parsed['rows'])
    expected = request['liberty_grid_delay_ns']
    if (len(stages) != 1 or stages[0]['cell'] != request['cell']
            or any(stages[0][k] != request[k] for k in
                   ('toggle_pin', 'out_pin', 'input_transition', 'transition'))
            or not math.isclose(stages[0]['sta_delay_ns'], expected,
                                rel_tol=2 ** -21, abs_tol=.5e-9)):
        return {**result, 'reason': 'native reference does not reproduce the requested grid arc'}
    # Measure only the actual cell pins. The native ideal-port/Pi short is
    # not an extra cell contribution to be added to the design wire residual.
    cell_rows = [r for r in parsed['rows'] if r['inst'] == 'u_ref']
    parsed = {**parsed, 'rows': cell_rows, 'start_row': cell_rows[0]}
    step, _ = transient_step_s(deck, cell_rows)
    sim = _simulate(deck, arm['simulator'], arm['image'], arm['project'], arm['mounts'], step)
    log = deck.with_suffix('.log')
    log.write_text(sim.stdout + '\n' + sim.stderr)
    argv = (['ngspice', '-b'] if arm['simulator'] == 'ngspice' else ['Xyce']) + [str(deck.with_suffix('.run.sp'))]
    result['executions'].append({'tool': arm['simulator'], 'rc': sim.returncode,
                                 'argv': argv, 'script': str(deck.with_suffix('.run.sp')), 'log': str(log)})
    got = measure(deck, arm['simulator'], parsed, hdr)
    if sim.returncode != 0:
        got = {'status': 'NOT_MEASURED', 'reason': 'native reference simulator exited non-zero'}
    result.update(got, sta_ns=stages[0]['sta_delay_ns'], deck=str(deck))
    write_json(directory / 'result.json', result)
    return result


def measure(deck: Path, simulator: str, sta: dict, header: dict) -> Dict[str, Any]:
    """SPICE delay from the STA path's start pin to its end pin, same edges."""
    text = deck.read_text(errors='replace')
    supplies = [float(v) for v in re.findall(r'^v\d+\s+\S+\s+0\s+([-\d.eE+]+)\s*$', text, re.M)]
    vdd = max(supplies) if supplies else None
    wave_path = xyce_table(deck) if simulator == 'xyce' else deck.with_suffix('.wave')
    if vdd is None or not wave_path.is_file():
        return {'status': 'NOT_MEASURED', 'reason': 'no waveform or no supply in the deck'}
    wave = read_waveform(wave_path, simulator)
    start = sta.get('start_row') or sta['rows'][0]
    end = sta['rows'][-1]
    a = wave.get(start['pin'].lower().replace('\\', ''))
    b = wave.get(end['pin'].lower().replace('\\', ''))
    if not a or not b:
        return {'status': 'NOT_MEASURED', 'reason': f'no waveform for {start["pin"]} / {end["pin"]}'}
    s_edge = 'fall' if start['tr'] == 'v' else 'rise'
    e_edge = sta['endpoint_transition']
    s_level = vdd * header[f'input_threshold_{s_edge}'] / 100.0
    e_level = vdd * header[f'output_threshold_{e_edge}'] / 100.0
    starts = crossings(a, s_level, s_edge)
    for t_end in crossings(b, e_level, e_edge):
        before = [t for t in starts if t <= t_end]
        if before:
            return {'status': 'MEASURED', 'spice_ns': (t_end - before[-1]) * 1e9,
                    'start_pin': start['pin'], 'end_pin': end['pin'],
                    'edges': [s_edge, e_edge], 'vdd': vdd}
    return {'status': 'NOT_MEASURED', 'reason': 'the end pin never made the STA transition '
                                                 'after the start pin did'}


def transient_step_s(deck: Path, rows: List[dict]) -> Tuple[float, float]:
    """(step the run uses, step the tool's deck asked for), in seconds.

    The tool asks for its print step as the TMAX of a many-cycle window
    (MEASURED on spm: `.tran 1e-13 7.44e-08`, 744k forced points, > 11 min per
    register-to-register path on a loaded host). The run uses a twentieth of
    the fastest slew the STA path reports -- the resolution a threshold
    crossing needs -- and never less than the tool's own step. The adaptive
    integrator still refines every edge; both steps are recorded."""
    m = re.search(r'^\.tran\s+(\S+)\s+(\S+)', deck.read_text(errors='replace'), re.M | re.I)
    asked = float(m.group(1)) if m else 0.0
    slews = [r['slew_ns'] for r in rows if (r.get('slew_ns') or 0) > 0]
    derived = min(slews) * 1e-9 / 20.0 if slews else asked
    return max(asked, derived), asked


def xyce_table(deck: Path) -> Path:
    """The file Xyce writes the deck's `.print tran` to: the `file=` the
    tool's deck names (`format=csv`), else Xyce's default `<netlist>.prn`."""
    m = re.search(r'^\.print\s+tran\b[^\n]*?\bfile=(\S+)', deck.read_text(errors='replace'),
                  re.M | re.I)
    return Path(m.group(1)) if m else deck.with_suffix('.run.sp.prn')


def runnable_subckts(text: str, deck_dir: Path) -> str:
    """`text` with each `.include`d `.subckt` file the tool wrote replaced by a
    copy whose device lines start at column 0. ``fold_subckts`` indents the
    parameterised device calls so OpenSTA's subckt READER skips them; that
    indentation is for the reader only. Xyce reads a line that starts with
    white space as a continuation of the line before (MEASURED on spm: "Unrecognized
    fields for device D37", the pad diode followed by an indented X line), so
    both simulators read the same de-indented bytes."""
    def swap(m):
        source = deck_dir / m.group(2)
        if not source.is_file():
            return m.group(0)
        target = source.with_suffix('.run.subckt')
        target.write_text(re.sub(r'^[ \t]+(?=[A-Za-z])', '',
                                 source.read_text(errors='replace'), flags=re.M))
        return f'{m.group(1)}"{target.name}"'
    return re.sub(r'^(\.include\s+)"([^"/]+\.subckt)"', swap, text, flags=re.M | re.I)


def _simulate(deck: Path, simulator: str, image: str, project: Path,
              mounts: List[Tuple[Path, str]], step_s: Optional[float] = None
              ) -> subprocess.CompletedProcess:
    text = runnable_subckts(deck.read_text(), deck.parent)
    stop = re.search(r'^\.tran\s+\S+\s+(\S+)', text, re.M | re.I).group(1)
    runnable = deck.with_suffix('.run.sp')
    if simulator == 'ngspice':
        nodes = re.search(r'^\.print tran (.*)$', text, re.M).group(1).split()
        names = [n[2:-1] for n in nodes if n.lower().startswith('v(')]
        # ngspice keeps node names lowercase and its control language reads a
        # backslash as an escape; the header names each column (MEASURED:
        # `v(u_core\/a/CLK)` in a control line is "no such vector").
        vectors = ' '.join('v(' + n.lower().replace('\\', '\\\\') + ')' for n in names)
        run = f'tran {step_s:.6g} {stop}' if step_s else 'run'
        control = (f'.control\nset wr_vecnames\nset wr_singlescale\n{run}\n'
                   f'wrdata {deck.with_suffix(".wave")} {vectors}\nquit\n.endc\n')
        # `quit`: in batch mode ngspice otherwise runs the deck's own `.tran`
        # card after the control block (MEASURED on spm: the 1e-13 card took
        # 30-57 min after the control-block transient had finished in ~1 min).
        # A function, not a string: a replacement string would read the
        # doubled backslashes above as escapes and undo them.
        runnable.write_text(re.sub(r'^\.end\s*$', lambda _m: control + '.end', text,
                                   flags=re.M))
        return _docker(image, project, mounts, ['ngspice', '-b', str(runnable)], deck.parent)
    if step_s:
        text = re.sub(r'^\.tran\s+\S+', f'.tran {step_s:.6g}', text, count=1, flags=re.M | re.I)
    runnable.write_text(text)
    return _docker(image, project, mounts, ['Xyce', str(runnable)], deck.parent)


def mutate_spef(source: Path, factor: float, out: Path) -> Dict[str, Any]:
    """Every `*CAP` value and every `*D_NET` total scaled by `factor`."""
    lines = []
    section = None
    scaled = 0
    for raw in Path(source).read_text(errors='replace').splitlines():
        words = raw.split()
        head = words[0] if words else ''
        if head == '*D_NET' and len(words) >= 3:
            section = 'net'
            words[2] = f'{float(words[2]) * factor:.6g}'
            raw = ' '.join(words)
        elif head == '*CAP':
            section = 'cap'
        elif head.startswith('*') and head not in ('*CAP',):
            section = None if head == '*END' else ('net' if head in ('*CONN', '*RES') else section)
        elif section == 'cap' and head.isdigit() and len(words) in (3, 4):
            words[-1] = f'{float(words[-1]) * factor:.6g}'
            raw = ' '.join(words)
            scaled += 1
        lines.append(raw)
    out.write_text('\n'.join(lines) + '\n')
    return {'path': str(out), 'factor': factor, 'cap_rows_scaled': scaled,
            'source_sha256': digest(Path(source))}


def run_arm(project: Path, image: str, state_path: Path, corner: str, *,
            pdk_root: Path, pdk: str, out_dir: Path, simulator: str = 'ngspice',
            paths: int = 3, path_args: Optional[List[str]] = None,
            spef: Optional[Path] = None) -> Dict[str, Any]:
    """Top-N setup paths of `corner` through the tool's deck and `simulator`."""
    return simulate_arm(prepare_arm(project, image, state_path, corner, pdk_root=pdk_root,
                                    pdk=pdk, out_dir=out_dir, simulator=simulator,
                                    paths=paths, path_args=path_args, spef=spef))


def prepare_arm(project: Path, image: str, state_path: Path, corner: str, *,
                pdk_root: Path, pdk: str, out_dir: Path, simulator: str = 'ngspice',
                paths: int = 3, path_args: Optional[List[str]] = None,
                spef: Optional[Path] = None) -> Dict[str, Any]:
    """The STA session: each path's report and the tool's deck for it."""
    inputs = post_pnr_timing_inputs(project, state_path, corner)
    config = _load(state_path.parent / 'config.json')
    top, power, ground = config.get('DESIGN_NAME'), config.get('VDD_PIN'), config.get('GND_PIN')
    if not (top and power and ground):
        raise Refusal('LL_STA_CONFIG_UNREAD', str(state_path.parent / 'config.json'))
    guest = f'/pdk/{pdk}'
    host = lambda p: Path(str(p).replace(guest, str(pdk_root / pdk), 1))  # noqa: E731
    lib_texts = [host(p).read_text(errors='replace') for p in inputs['liberties']]
    header = _scc.parse_liberty_header(lib_texts[0])
    opc, libname = _OPCOND_RE.search(lib_texts[0]), _LIBRARY_RE.search(lib_texts[0])
    if not (opc and libname):
        raise Refusal('LL_LIBERTY_OPCOND_UNDECLARED', inputs['liberties'][0])
    out_dir.mkdir(parents=True, exist_ok=True)
    # These files belong only to this Step-30 invocation. A failed tool may
    # not reuse a deck or STA report left by its predecessor.
    for stale in out_dir.glob('path_*'):
        if stale.is_file():
            stale.unlink()
    import shutil
    if (out_dir / 'refs').exists():
        # Use the native-run attempts convention (run_chain) to preserve the
        # preceding invocation's raw references, outside current products.
        archive = out_dir.parent / 'attempts'
        archive.mkdir(exist_ok=True)
        number = 1
        while (archive / f'{out_dir.name}-refs-{number:04d}').exists():
            number += 1
        shutil.move(str(out_dir / 'refs'), str(archive / f'{out_dir.name}-refs-{number:04d}'))
    for stale in out_dir.glob('dcalc_*'):
        stale.unlink()
    (out_dir / 'reference_clocks.txt').unlink(missing_ok=True)
    cell_sources = [host(p) for p in (config.get('CELL_SPICE_MODELS') or [])]
    spice_sources = cell_sources + [host(p) for p in (config.get('PAD_SPICE_MODELS') or [])]
    import librelane_contract as lc
    local = lc._provider_for_image(image) is not None or lc._provider_route(project)
    execution_root = str(pdk_root) if local else str(Path(guest).parent)
    mounts = [(pdk_root / pdk, guest)]
    view = cell_view(image, project, mounts, config=config, pdk_dir=pdk_root / pdk,
                     guest_root=execution_root, pdk=pdk,
                     netlist=project / inputs['sta_netlist'], cell_sources=cell_sources,
                     out_dir=out_dir, liberty=inputs['liberties'][0])
    if view.get('missing_exports'):
        raise Refusal('LL_SPICE_CURRENT_CELL_EXPORT_MISSING', str(view['missing_exports']))
    cells = fold_subckts(view['sources'] + spice_sources, supply_voltages(lib_texts), power,
                         ground, out_dir / 'cells_folded.spice')
    cells['cell_view'] = {k: v for k, v in view.items() if k != 'sources'}
    model_root = str(Path(execution_root) / pdk)
    models = model_file(pdk_root / pdk / 'libs.tech' / simulator, f'{model_root}/libs.tech/{simulator}',
                        simulator, Path(inputs['liberties'][0]).name,
                        device_names(Path(cells['path']).read_text()),
                        header.get('nom_temperature'), out_dir / f'models_{simulator}.sp')
    # `-group_path_count N` writes N decks (`path_1.sp_<n>.sp`); the STA side
    # is one `report_checks` with the same arguments, split per path.
    args = path_args or [f'{REG_TO_REG} -group_path_count {paths}']
    spef_path = spef or (project / inputs['spef'])
    tcl = out_dir / 'arm.tcl'
    tcl.write_text(arm_tcl(inputs, project, top, str(spef_path), (libname.group(1), opc.group(1)),
                           args, out_dir, cells['path'], models['path'], power, ground, simulator))
    sta = _docker(image, project, mounts, ['sta', '-no_init', '-no_splash', '-exit', str(tcl)], out_dir)
    (out_dir / 'sta.log').write_text(sta.stdout + '\n' + sta.stderr)
    late_derate = declared_sta_late_derate(sta.stdout)
    failed = re.findall(r'^VIBEIC_WPS_FAIL (\d+) (.*)$', sta.stdout, re.M)
    # Report `path_<i>.rpt` block <n> is the path `write_path_spice` wrote to
    # `path_<i>.sp_<n>.sp` (the same `-path_args`, the same order).
    prepared = []
    for i in range(1, len(args) + 1):
        rpt = out_dir / f'path_{i}.rpt'
        blocks = (['Startpoint: ' + b for b in rpt.read_text(errors='replace')
                   .split('Startpoint: ')[1:]] if rpt.is_file() else [])
        for n, block in enumerate(blocks, 1):
            deck = out_dir / f'path_{i}.sp_{n}.sp'
            lookup = out_dir / f'dcalc_{i}_{n}.tsv'
            dcalc = {}
            if lookup.is_file():
                for line in lookup.read_text().splitlines():
                    source_pin, target_pin, report = line.split('\t')
                    dcalc[(source_pin, target_pin)] = report
            prepared.append({'path': len(prepared) + 1, 'parsed': parse_path_report(block), 'dcalc': dcalc,
                             'deck': deck if deck.is_file() else None,
                             'wps_fail': [f for k, f in failed if int(k) == i]})
    return {'corner': corner, 'simulator': simulator, 'inputs': inputs,
            'ocv_late_derate': late_derate,
            'spef': str(spef_path), 'spef_sha256': digest(spef_path), 'cells': cells,
            'models': models, 'sta_rc': sta.returncode, 'prepared': prepared,
            'sta_execution': {'tool': 'OpenSTA', 'rc': sta.returncode,
                'argv': ['sta', '-no_init', '-no_splash', '-exit', str(tcl)],
                'script': str(tcl), 'log': str(out_dir / 'sta.log')},
            'sta_lifecycle': getattr(sta, '_vibeic_lifecycle', None),
            'image': image, 'project': project, 'mounts': mounts, 'header': header,
            'power': power, 'ground': ground,
            'clock_periods_ns': ([float(value) for value in (out_dir / 'reference_clocks.txt').read_text().split()]
                                if (out_dir / 'reference_clocks.txt').is_file() else []),
            'liberty_sources': [{'path': str(host(path)), 'text': text, 'sha256': digest(host(path))}
                                for path, text in zip(inputs['liberties'], lib_texts)],
            'liberty_text': '\n'.join(lib_texts)}


def simulate_arm(arm: Dict[str, Any], *, workers: int = 1) -> Dict[str, Any]:
    """Every prepared deck through the simulator (concurrently), measured
    and compared with its STA path."""
    from concurrent.futures import ThreadPoolExecutor
    simulator, header = arm['simulator'], arm['header']

    def one(item: Dict[str, Any]) -> Dict[str, Any]:
        parsed, deck = item['parsed'], item['deck']
        row: Dict[str, Any] = {'path': item['path'], 'deck': str(deck) if deck else None}
        if arm.get('sta_rc') != 0 or parsed is None or deck is None or deck.stat().st_size == 0:
            row.update(status='NOT_MEASURED', reason='no STA path or no deck',
                       wps_fail=item['wps_fail'])
            return row
        reference_arm = (arm.get('reference_arms') or {}).get(item.get('arm'), arm)
        late_derate = reference_arm.get('ocv_late_derate')
        if type(late_derate) not in (int, float) or not math.isfinite(late_derate) or late_derate <= 0:
            raise Refusal('LL_STA_DERATE_UNDECLARED', 'prepared STA arm has no declared late derate')
        step, asked = transient_step_s(deck, parsed['rows'])
        sim = _simulate(deck, simulator, arm['image'], arm['project'], arm['mounts'],
                        step_s=step)
        deck.with_suffix('.log').write_text(sim.stdout + '\n' + sim.stderr)
        got = measure(deck, simulator, parsed, header)
        row.update(tran_step_ns=step * 1e9, deck_tran_step_ns=asked * 1e9,
                   simulator_execution={'tool': simulator, 'rc': sim.returncode,
                       'argv': (['ngspice', '-b'] if simulator == 'ngspice' else ['Xyce'])
                               + [str(deck.with_suffix('.run.sp'))],
                       'script': str(deck.with_suffix('.run.sp')),
                       'log': str(deck.with_suffix('.log'))})
        if sim.returncode != 0:
            got = {'status': 'NOT_MEASURED', 'reason': 'simulator exited non-zero'}
        sta_derated_ns = parsed['path_delay_ns']
        sta_ns = sta_derated_ns / late_derate
        stages = path_stages(parsed['rows'])
        for stage in stages:
            stage['dcalc'] = item.get('dcalc', {}).get(
                (stage['inst'] + '/' + stage['toggle_pin'], stage['inst'] + '/' + stage['out_pin']))
        tol = (_scc.derive_liberty_path_tolerance(arm['liberty_text'], stages, sta_derated_ns)
               if stages else None)
        stages = [dict(stage, sta_delay_ns=stage['sta_delay_ns'] / late_derate)
                  for stage in stages]
        row.update(startpoint=parsed['startpoint'], endpoint=parsed['endpoint'],
                   sta_ns=sta_ns, sta_derated_ns=sta_derated_ns, ocv_late_derate=late_derate,
                   stages=len(stages), sim_rc=sim.returncode, **got)
        if getattr(sim, '_vibeic_lifecycle', None):
            row['lifecycle'] = sim._vibeic_lifecycle
        if got.get('status') == 'MEASURED':
            err = (got['spice_ns'] - sta_ns) / sta_ns * 100.0 if sta_ns else None
            row.update(error_pct=err, abs_error_ns=abs(got['spice_ns'] - sta_ns),
                       tolerance_pct=tol['tolerance_pct'] if tol else None,
                       verdict=(_scc.path_correlation_verdict(err, tol['tolerance_pct'])
                                if tol and err is not None else 'TOLERANCE_UNDERIVABLE'))
            if tol and sta_ns:
                sources = _reference_sources(reference_arm, stages, deck)
                refs = deck.parent / 'refs' / f"path_{item['path']}"
                characterisation = _scc.measure_pdk_characterisation(
                    '', sources, {}, '', stages, refs, header,
                    reference_runner=lambda source, request, index: _native_grid_reference(
                        reference_arm, refs / str(index), source, request))
                row['pdk_characterisation'] = characterisation
                row.update(_scc.native_path_comparison(row))
        return row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, arm['prepared']))
    return {k: v for k, v in arm.items()
            if k not in ('prepared', 'image', 'project', 'mounts', 'header', 'liberty_text',
                         'liberty_sources', 'reference_arms')
            } | {'paths': rows}


def judge(arm: Dict[str, Any], mutated: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """CORRELATED only when every measured path is within its derived
    tolerance AND responds to the SPEF mutation."""
    rows = [r for r in arm['paths'] if r.get('status') == 'MEASURED']
    if not rows:
        return {'verdict': 'NOT_MEASURED', 'reason': 'no path was simulated'}
    response = []
    for row in rows:
        other = next((m for m in (mutated or {}).get('paths') or []
                      if m.get('startpoint') == row['startpoint']
                      and m.get('endpoint') == row['endpoint']
                      and m.get('status') == 'MEASURED'), None)
        if other is None:
            response.append({'path': row['path'], 'responds': None})
            continue
        step = row.get('tran_step_ns') or _tran_step_ns(row['deck'])
        delta = other['spice_ns'] - row['spice_ns']
        response.append({'path': row['path'], 'spice_delta_ns': delta,
                         'sta_delta_ns': other['sta_ns'] - row['sta_ns'],
                         'resolution_ns': 2 * step,
                         'responds': abs(delta) > 2 * step and delta > 0})
    unmeasured = [r for r in response if r['responds'] is None]
    unresponsive = [r for r in response if r['responds'] is False]
    worst = max(rows, key=lambda r: abs(r.get('error_pct') or 0.0))
    verdicts = {r.get('verdict') for r in rows}
    verdict = ('CRITICAL_MISMATCH' if 'CRITICAL_MISMATCH' in verdicts else
               'MISMATCH' if 'MISMATCH' in verdicts else
               'SPEF_UNRESPONSIVE' if unresponsive else
               'MUTATION_NOT_MEASURED' if unmeasured else
               'CORRELATED' if verdicts == {'CORRELATED'} else
               'TOLERANCE_UNDERIVABLE')
    return {'verdict': verdict, 'worst_path': worst['path'],
            'worst_error_pct': worst.get('error_pct'), 'mutation': response}


def _tran_step_ns(deck: Any) -> float:
    m = re.search(r'^\.tran\s+(\S+)', Path(deck).read_text(errors='replace'), re.M | re.I)
    return float(m.group(1)) * 1e9 if m else 0.0


#: Two simulators on the same deck are one instrument measured twice: their
#: SPICE delays must agree to within this fraction of the reported arm's
#: (orchestrator ruling, consistent with step 23's engine agreement).
AGREEMENT_FRACTION = 0.01
#: The arm whose number is reported when the arms agree.
REPORTED_ARM = 'ngspice'


def step_verdict(judgments: Dict[str, Dict[str, Any]],
                 paths: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Step 30's verdict from its simulator arms (pure).

    * Two or more CORRELATED arms are an AGREEMENT check, not a pick: every
      path measured by every one of them must give SPICE delays within
      ``AGREEMENT_FRACTION`` of the reported arm's, then PASS with
      `verdict_basis` AGREE and every arm recorded; otherwise REFUSED
      `LL_SPICE_ARMS_DISAGREE`. A pair with no path measured in common has
      not been compared, and refuses the same way.
    * One CORRELATED arm with every other arm NOT_MEASURED (refused, or its
      simulator unavailable): PASS on that arm, the others named.
    * One CORRELATED arm beside a MEASURED arm that is not CORRELATED is a
      disagreement between instruments: REFUSED, never a pick.
    * No CORRELATED arm: the measured arms' verdict (FAIL), or NOT_MEASURED.
    """
    verdicts = {s: (j or {}).get('verdict') for s, j in judgments.items()}
    correlated = sorted(s for s, v in verdicts.items() if v == 'CORRELATED')
    unmeasured = sorted(s for s, v in verdicts.items() if v in ('NOT_MEASURED', None))
    others = sorted(s for s in verdicts if s not in correlated and s not in unmeasured)
    if not correlated:
        if not others:
            return {'verdict': 'NOT_MEASURED', 'verdict_basis': 'NO_ARM_MEASURED',
                    'not_measured': unmeasured}
        return {'verdict': 'FAIL', 'verdict_basis': 'NO_ARM_CORRELATED',
                'arm_verdicts': {s: verdicts[s] for s in others}, 'not_measured': unmeasured}
    if others:
        return {'verdict': 'REFUSED', 'refusal': 'LL_SPICE_ARMS_DISAGREE',
                'verdict_basis': 'DISAGREE',
                'reason': (f'{correlated} CORRELATED, {others} '
                           f'{[verdicts[s] for s in others]}: the instruments disagree'),
                'arm_verdicts': {s: verdicts[s] for s in correlated + others},
                'not_measured': unmeasured}
    if len(correlated) == 1:
        return {'verdict': 'PASS', 'verdict_basis': 'SINGLE_ARM', 'reported_arm': correlated[0],
                'not_measured': unmeasured}
    reported = REPORTED_ARM if REPORTED_ARM in correlated else correlated[0]
    measured = {s: {(r.get('startpoint'), r.get('endpoint')): r['spice_ns']
                    for r in paths.get(s) or []
                    if r.get('status') == 'MEASURED' and r.get('spice_ns')}
                for s in correlated}
    common = set.intersection(*(set(m) for m in measured.values()))
    rows = []
    for key in sorted(common, key=str):
        ref = measured[reported][key]
        for s in correlated:
            if s != reported:
                delta = abs(measured[s][key] - ref) / abs(ref)
                rows.append({'startpoint': key[0], 'endpoint': key[1], 'arm': s,
                             'reported_ns': ref, 'arm_ns': measured[s][key],
                             'relative_delta': delta, 'agree': delta <= AGREEMENT_FRACTION})
    base = {'arms_compared': correlated, 'reported_arm': reported,
            'agreement_fraction': AGREEMENT_FRACTION, 'agreement': rows,
            'not_measured': unmeasured}
    if not rows:
        return dict(base, verdict='REFUSED', refusal='LL_SPICE_ARMS_DISAGREE',
                    verdict_basis='DISAGREE',
                    reason='the CORRELATED arms measured no path in common: not compared')
    if all(r['agree'] for r in rows):
        return dict(base, verdict='PASS', verdict_basis='AGREE')
    worst = max(rows, key=lambda r: r['relative_delta'])
    return dict(base, verdict='REFUSED', refusal='LL_SPICE_ARMS_DISAGREE',
                verdict_basis='DISAGREE',
                reason=(f"{worst['arm']} {worst['arm_ns']:.4g} ns vs {reported} "
                        f"{worst['reported_ns']:.4g} ns on {worst['startpoint']} -> "
                        f"{worst['endpoint']}: {worst['relative_delta'] * 100:.3g}% > "
                        f"{AGREEMENT_FRACTION * 100:g}%"))


def native_sta_folder(project: Path, sta_step_dir: Optional[Path] = None) -> Path:
    """Select one native STAPostPNR folder by its resolved configuration."""
    project = Path(project).resolve(strict=True)
    if sta_step_dir is None:
        candidates = []
        for path in project.rglob('config.json'):
            if any(path.is_relative_to(root) for root in
                   (project / 'steps', project / 'reports/step_versions')):
                continue
            try:
                config = _load(path)
            except (OSError, ValueError, Refusal):
                continue
            meta = config.get('meta')
            if isinstance(meta, dict) and meta.get('step') == 'OpenROAD.STAPostPNR':
                candidates.append(path.parent)
        if not candidates:
            raise Refusal('LL_STAPOSTPNR_STATE_ABSENT', str(project))
        if len(candidates) != 1:
            raise Refusal('LL_STAPOSTPNR_STATE_AMBIGUOUS', str(candidates))
        sta_step_dir = candidates[0]
    folder = Path(sta_step_dir).resolve(strict=True)
    if not folder.is_relative_to(project):
        raise Refusal('LL_STATE_OUTSIDE_PROJECT', str(folder))
    for name in ('config.json', 'state_out.json'):
        path = folder / name
        if not path.is_file() or not path.stat().st_size:
            raise Refusal('LL_STATE_FILE_MISSING', str(path))
        if not path.resolve().is_relative_to(folder):
            raise Refusal('LL_STATE_OUTSIDE_PROJECT', str(path))
    config = _load(folder / 'config.json')
    meta = config.get('meta')
    if not isinstance(meta, dict) or meta.get('step') != 'OpenROAD.STAPostPNR':
        raise Refusal('LL_NOT_STAPOSTPNR', str(folder))
    return folder


def worst_setup_corner(folder: Path) -> str:
    """Read the worst setup scene from native metrics or the native summary."""
    folder = Path(folder).resolve(strict=True)
    config = _load(folder / 'config.json')
    logs = {path.parent.name: path for path in folder.glob('*/sta.log') if path.is_file()}
    for path in logs.values():
        if not path.resolve().is_relative_to(folder):
            raise Refusal('LL_STATE_OUTSIDE_PROJECT', str(path))
    declared = config.get('STA_CORNERS')
    if declared is not None and (
            not isinstance(declared, list) or not declared
            or any(not isinstance(c, str) or not c for c in declared)
            or len(set(declared)) != len(declared) or not set(logs) <= set(declared)):
        raise Refusal('LL_CORNER_NOT_ANALYSED', str(folder))
    state = _load(folder / 'state_out.json')
    metrics = state.get('metrics') or {}
    if not isinstance(metrics, dict):
        raise Refusal('LL_STEP30_CORNER_UNDECLARED', str(folder / 'state_out.json'))
    metrics = dict(metrics)
    metrics_path = folder / 'metrics.json'
    if metrics_path.exists():
        if not metrics_path.resolve().is_relative_to(folder):
            raise Refusal('LL_STATE_OUTSIDE_PROJECT', str(metrics_path))
        metrics.update(_load(metrics_path))
    prefix = 'timing__setup__ws__corner:'
    setup = {name[len(prefix):]: value for name, value in metrics.items()
             if name.startswith(prefix)}
    if not setup:
        summary = folder / 'summary.rpt'
        if not summary.is_file():
            raise Refusal('LL_STEP30_CORNER_UNDECLARED', str(summary))
        if not summary.resolve().is_relative_to(folder):
            raise Refusal('LL_STATE_OUTSIDE_PROJECT', str(summary))
        for line in summary.read_text().splitlines():
            if not line.strip().startswith('│'):
                continue
            cells = [cell.strip() for cell in line.split('│')[1:-1]]
            if not cells or cells[0] == 'Overall':
                continue
            if len(cells) < 7 or cells[0] in setup:
                raise Refusal('LL_STEP30_CORNER_UNDECLARED', str(summary))
            try:
                setup[cells[0]] = float(cells[6])
            except ValueError as exc:
                raise Refusal('LL_STEP30_CORNER_UNDECLARED', str(summary)) from exc
    if (not logs or set(setup) != set(logs)
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for value in setup.values())):
        raise Refusal('LL_STEP30_CORNER_UNDECLARED', str(folder))
    return min(setup, key=lambda name: (setup[name], name))


def run_step30(project: Path, image: str, pdk_root: Path, pdk: str, *,
               corner: Optional[str] = None, paths: int = 3,
               simulators: Sequence[str] = SIMULATORS,
               sta_step_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Step 30's tool arm on a native STAPostPNR state: each
    simulator on the base SPEF and on the mutated one, judged, and written to
    `reports/phase3/spice_path_tool.json`. The corner is the native worst
    setup corner unless one is given. A simulator that cannot run this PDK
    is recorded by its refusal; nothing falls back."""
    project = Path(project).resolve(strict=True)
    folder = native_sta_folder(project, sta_step_dir)
    corner = corner or worst_setup_corner(folder)
    state_path = folder / 'state_out.json'
    root = project / 'phase3/tool_arms/30'
    arms: Dict[str, Any] = {}
    for simulator in simulators:
        try:
            base = prepare_arm(project, image, state_path, corner, pdk_root=pdk_root, pdk=pdk,
                               out_dir=root / simulator / 'base', simulator=simulator,
                               paths=paths)
            mutated_spef = mutate_spef(Path(base['spef']), MUTATION_FACTOR,
                                       root / simulator / 'mutated.spef')
            # The mutation re-times the SAME arc: start and end pin AND their
            # transitions. MEASURED on spm: `-from Q -to D` alone picked the
            # opposite edge after the mutation, and the tool's deck (no initial
            # state) cannot launch a falling Q from a flop that powers up at 0.
            edge = lambda row: 'rise' if row['tr'] == '^' else 'fall'  # noqa: E731
            pins = [f"-path_delay max -{edge(item['parsed']['start_row'])}_from "
                    f"{item['parsed']['start_row']['pin']} -{edge(item['parsed']['rows'][-1])}_to "
                    f"{item['parsed']['rows'][-1]['pin']}"
                    for item in base['prepared'] if item['parsed'] and item['deck']]
            mutated = (prepare_arm(project, image, state_path, corner, pdk_root=pdk_root,
                                   pdk=pdk, out_dir=root / simulator / 'mutated',
                                   simulator=simulator, path_args=pins,
                                   spef=Path(mutated_spef['path'])) if pins else None)
            # Every deck of both arms simulates at once; they are independent.
            base['prepared'] = [dict(i, arm='base') for i in base['prepared']]
            both = dict(base, prepared=base['prepared']
                        + [dict(i, arm='mutated') for i in (mutated or {}).get('prepared', [])],
                        reference_arms={'base': base, 'mutated': mutated})
            rows = simulate_arm(both)['paths']
            done_base = {k: v for k, v in simulate_arm(dict(base, prepared=[]))
                         .items()} | {'paths': rows[:len(base['prepared'])]}
            done_mut = (None if mutated is None else
                        {k: v for k, v in simulate_arm(dict(mutated, prepared=[])).items()}
                        | {'paths': rows[len(base['prepared']):]})
            # The cell view is part of the verdict: a schematic-view number
            # carries the PDK's missing layout parasitics (module docstring).
            arms[simulator] = {'judgment': dict(judge(done_base, done_mut),
                                                cell_view=base['cells']['cell_view']['view']),
                               'base': done_base,
                               'mutated': done_mut, 'mutation': mutated_spef}
        except Refusal as exc:
            arms[simulator] = {'judgment': {'verdict': 'NOT_MEASURED', 'reason': str(exc)}}
    document = {'step': '30', 'corner': corner, 'sta_state': str(state_path),
                'sta_state_sha256': digest(state_path),
                'deck': 'OpenSTA write_path_spice (SPEF-annotated)',
                'arms': {s: a['judgment'] for s, a in arms.items()},
                **step_verdict({s: a['judgment'] for s, a in arms.items()},
                               {s: (a.get('base') or {}).get('paths') or [] for s, a in arms.items()}),
                'rule': ('an arm is CORRELATED when |SPICE-STA| is within the Liberty-grid '
                         'tolerance AND the result responds to the SPEF mutation; two '
                         'CORRELATED arms are an agreement check, never a pick'),
                'detail': {s: {k: v for k, v in a.items() if k != 'judgment'}
                           for s, a in arms.items()}}
    write_json(project / 'reports/phase3/spice_path_tool.json', document)
    return document


def current_context(project: Path, image: str, pdk_root: Path, pdk: str, *,
                    sta_step_dir: Optional[Path] = None):
    """Current routed subject and the existing tool's extracted corner inputs."""
    import _opensta_current as current
    project = Path(project).resolve(strict=True)
    folder = native_sta_folder(project, sta_step_dir)
    corner = worst_setup_corner(folder)
    inputs = post_pnr_timing_inputs(project, folder / 'state_out.json', corner)
    config = _load(folder / 'config.json')
    top = config.get('DESIGN_NAME')
    pdk_root = Path(pdk_root).resolve()
    pdk_dir = (pdk_root / pdk).resolve()
    guest_pdk = Path(f'/pdk/{pdk}')
    def host(path):
        path = Path(path)
        return pdk_dir / path.relative_to(guest_pdk) if path.is_relative_to(guest_pdk) else path
    if (not isinstance(image, str) or not re.search(r'@sha256:[0-9a-f]{64}$', image)
            or config.get('PDK') != pdk or not pdk_dir.is_dir()):
        raise Refusal('CURRENT_STEP30_IMAGE_OR_PDK_MISMATCH', str(pdk_root))
    libs = [host(path).resolve(strict=True) for path in inputs['liberties']]
    if any(not path.is_relative_to(pdk_dir) for path in libs):
        raise Refusal('CURRENT_STEP30_PDK_PATH_MISMATCH', str(libs))
    subject = current.basis(project, top, libs, netlist=project / inputs['sta_netlist'],
                            sdc=project / inputs['sdc'], spef=project / inputs['spef'])
    subject['inputs'] += [current.file_record(path, role, project) for role, path in [
        ('sta_state', folder / 'state_out.json'), ('sta_config', folder / 'config.json'),
        *[(f'sta_corner_log:{path.parent.name}', path)
          for path in sorted(folder.glob('*/sta.log'))],
        *[(f'sta_selection:{name}', folder / name) for name in ('metrics.json', 'summary.rpt')
          if (folder / name).is_file()]]]
    sources = {str(path.resolve()): current.digest(path)
               for directory in ('ngspice', 'magic')
               for path in (pdk_root / pdk / 'libs.tech' / directory).rglob('*')
               if path.is_file()}
    for relative in _PDK_FLOW_CONFIGS:
        path = pdk_root / pdk / relative
        if path.is_file():
            sources[str(path.resolve())] = current.digest(path)
    for name in ('CELL_SPICE_MODELS', 'PAD_SPICE_MODELS', 'CELL_GDS'):
        for path in config.get(name) or []:
            source = host(path).resolve(strict=True)
            if not source.is_relative_to((pdk_root / pdk).resolve()):
                raise Refusal('CURRENT_STEP30_PDK_PATH_MISMATCH', str(source))
            sources[str(source)] = current.digest(source)
    if any(not Path(path).is_relative_to(pdk_dir) for path in sources):
        raise Refusal('CURRENT_STEP30_PDK_PATH_MISMATCH', str(pdk_root))
    if not sources:
        raise Refusal('CURRENT_STEP30_MODELS_MISSING', str(pdk_root))
    return subject, {'image': image, 'pdk_root': str(pdk_root), 'pdk': pdk,
                     'corner': corner, 'sta_step_dir': str(folder), 'sources': sources,
                     'extraction_corner': extraction_corner(pdk, pdk_root / pdk, inputs['liberties'][0])}


def _current_products(project: Path, tool: dict):
    """Bind native path reports, extracted subckts, models and waveforms too.

    These are the files the existing producer consumed to derive its result;
    a deck alone does not bind its included circuit or measured samples.
    """
    root = project / 'phase3/tool_arms/30'
    products = []
    for simulator, arm in tool['detail'].items():
        for variant in ('base', 'mutated'):
            data = arm.get(variant) or {}
            execution = data.get('sta_execution')
            if not execution:
                continue
            directory = root / simulator / variant
            if Path(execution['script']) != directory / 'arm.tcl':
                raise Refusal('CURRENT_STEP30_PATH_EXECUTION_MISMATCH', str(execution))
            products += [('product:' + str(path.relative_to(root)), path)
                         for path in sorted(directory.rglob('*')) if path.is_file()]
        mutation = arm.get('mutation') or {}
        if mutation.get('path'):
            path = root / simulator / 'mutated.spef'
            if Path(mutation['path']) != path:
                raise Refusal('CURRENT_STEP30_MUTATION_PATH_MISMATCH', str(mutation))
            products.append(('product:' + str(path.relative_to(root)), path))
    return products


def _current_executions(tool: dict):
    executions = []
    for arm in tool['detail'].values():
        for variant in ('base', 'mutated'):
            data = arm.get(variant) or {}
            extraction = ((data.get('cells') or {}).get('cell_view') or {}).get('magic_execution')
            if extraction:
                executions.append(extraction)
            if data.get('sta_execution'):
                executions.append(data['sta_execution'])
            executions += [row['simulator_execution'] for row in data.get('paths') or []
                           if row.get('simulator_execution')]
            # Preserve the original design NG first: the canonical wholepath
            # log must never be replaced by a single-cell reference log.
            for row in data.get('paths') or []:
                char = row.get('pdk_characterisation') or {}
                for ref in char.get('references') or []:
                    ran = ref.get('executions') or []
                    if ref.get('status') == 'MEASURED' and (
                            [ex.get('tool') for ex in ran] != ['OpenSTA', row['simulator_execution']['tool']]
                            or any(ex.get('rc') != 0 for ex in ran)):
                        raise Refusal('CURRENT_STEP30_REFERENCE_EXECUTION_MISSING', str(ref))
                    executions += [{**ex, 'purpose': 'pdk_reference'} for ex in ran]
    return executions


def _current_companion_errors(project: Path, tool: dict, subject: dict, context: dict):
    """Keep a bound base mismatch decisive when its companion is incomplete.

    This exception cannot admit PASS, a failed base execution, an unmeasured
    base, or a result from another state/corner/material subject. Every error's
    script/log and all measured products remain mandatory current byte bindings.
    """
    errors, incomplete = [], False
    for simulator, arm in tool['detail'].items():
        base, changed = arm.get('base') or {}, arm.get('mutated') or {}
        incomplete |= any(row.get('status') == 'MEASURED' and not any(
            other.get('status') == 'MEASURED'
            and other.get('startpoint') == row.get('startpoint')
            and other.get('endpoint') == row.get('endpoint')
            for other in changed.get('paths') or []) for row in base.get('paths') or [])
        for variant in ('base', 'mutated'):
            for execution in _current_executions({'detail': {simulator: {variant: arm.get(variant)}}}):
                if type(execution.get('rc')) is not int:
                    raise Refusal('CURRENT_STEP30_EXECUTION_FAILED', str(execution))
                # A failed independent reference keeps the original raw
                # comparison and explicitly incomplete separation. It does
                # not change the health of the primary design execution.
                if execution['rc'] != 0 and execution.get('purpose') != 'pdk_reference':
                    errors.append({'simulator': simulator, 'variant': variant, **execution})
    if not errors and not incomplete:
        return []
    if tool.get('verdict') != 'FAIL' or any(error['variant'] != 'mutated' for error in errors):
        raise Refusal('CURRENT_STEP30_EXECUTION_FAILED', str(errors))
    state = next(row for row in subject['inputs'] if row['role'] == 'sta_state')
    if (tool.get('sta_state') != state['path'] or tool.get('sta_state_sha256') != state['sha256']
            or tool.get('corner') != context['corner']):
        raise Refusal('CURRENT_STEP30_FAIL_SUBJECT_MISMATCH', str(state))
    inputs = post_pnr_timing_inputs(project, Path(state['path']), context['corner'])
    for simulator, arm in tool['detail'].items():
        base = arm.get('base') or {}
        if (base.get('inputs') != inputs or base.get('spef') != str(project / inputs['spef'])
                or base.get('spef_sha256') != inputs['sha256']['spef']):
            raise Refusal('CURRENT_STEP30_FAIL_SUBJECT_MISMATCH', str(base.get('inputs')))
        if (base.get('sta_execution') or {}).get('rc') != 0:
            continue
        for row in base.get('paths') or []:
            execution = row.get('simulator_execution') or {}
            values = [row.get(key) for key in ('sta_ns', 'spice_ns', 'tolerance_pct')]
            if (row.get('status') != 'MEASURED' or execution.get('rc') != 0
                    or execution.get('tool') != simulator
                    or not all(type(value) in (int, float) and math.isfinite(value) for value in values)
                    or values[0] <= 0 or values[1] < 0 or values[2] < 0):
                continue
            if 'pdk_characterisation' in row:
                try:
                    measured = _scc.native_path_comparison(row)['verdict']
                except (KeyError, TypeError, ValueError):
                    continue
            else:
                measured = _scc.path_correlation_verdict((values[1] - values[0]) / values[0] * 100, values[2])
            if measured == row.get('verdict') and measured in ('MISMATCH', 'CRITICAL_MISMATCH'):
                return errors
    raise Refusal('CURRENT_STEP30_MEASURED_FAILURE_MISSING',
                  f'inspected sta_state {state["path"]} and current base-path rows: ' +
                  ', '.join(f'tool.detail[{simulator}].base.paths' for simulator in tool['detail']) +
                  f'; companion execution errors: {errors}')


def run_current_step30(project: Path, image: str, pdk_root: Path, pdk: str, *, paths: int = 1,
                       sta_step_dir: Optional[Path] = None):
    """Ordinary Step 30: existing write_path_spice route, one native simulator.

    The existing tool owns its decks, local Liberty tolerance and SPEF-response
    control. This boundary owns current material and downstream result identity.
    """
    import _opensta_current as current
    project = Path(project).resolve(strict=True)
    report = project / 'reports/phase3/spice_correlation.json'
    receipt_path = report.with_suffix('.current.json')
    canonical_deck = project / 'phase3/stage3/spice/correlation.spice'
    canonical_log = canonical_deck.with_suffix('.log')
    for path in (report, receipt_path, canonical_deck, canonical_log,
                 canonical_deck.with_suffix('.json')):
        path.unlink(missing_ok=True)
    subject, context = current_context(project, image, pdk_root, pdk, sta_step_dir=sta_step_dir)
    folder = Path(context['sta_step_dir'])
    tool = run_step30(project, image, pdk_root, pdk, paths=paths, simulators=('ngspice',),
                      sta_step_dir=folder)
    if current_context(project, image, pdk_root, pdk, sta_step_dir=folder) != (subject, context):
        raise Refusal('CURRENT_STEP30_INPUT_CHANGED_DURING_RUN', str(project))
    companion_errors = _current_companion_errors(project, tool, subject, context)
    executions, outputs = _current_executions(tool), []
    for arm in tool['detail'].values():
        for variant in ('base', 'mutated'):
            data = arm.get(variant) or {}
            for row in data.get('paths') or []:
                if row.get('deck'):
                    outputs.append(('deck:' + variant, Path(row['deck'])))
    # A known measured FAIL remains a failed measurement; absence is named.
    if not executions:
        raise Refusal('CURRENT_STEP30_EXECUTION_MISSING', str(tool.get('arms')))
    execution_files = []
    for index, execution in enumerate(executions):
        if type(execution.get('rc')) is not int:
            raise Refusal('CURRENT_STEP30_EXECUTION_FAILED', str(execution))
        for role in ('script', 'log'):
            execution_files.append(current.file_record(execution[role], f'{role}:{index}', project))
    first_deck = next((path for role, path in outputs if role == 'deck:base'), None)
    first_sim = next((ex for ex in executions if ex['tool'] == 'ngspice'), None)
    if first_deck is None or first_sim is None:
        raise Refusal('CURRENT_STEP30_CORRELATION_PRODUCT_MISSING', str(project))
    canonical_deck.parent.mkdir(parents=True, exist_ok=True)
    canonical_deck.write_bytes(first_deck.read_bytes())
    canonical_log.write_bytes(Path(first_sim['log']).read_bytes())
    outputs += [('canonical_deck', canonical_deck), ('canonical_log', canonical_log)]
    doc = {**tool, 'program': 'spice_correlation_check.current_write_path_spice',
           'current_subject': subject, 'current_context': context}
    if companion_errors:
        doc['companion_errors'] = companion_errors
    write_json(report, doc)
    declared_result = canonical_deck.with_suffix('.json')
    write_json(declared_result, doc)
    outputs += [('declared_result', declared_result)]
    outputs += [('tool_result', project / 'reports/phase3/spice_path_tool.json'), ('correlation', report)]
    outputs += _current_products(project, tool)
    receipt = {**subject, 'schema': 'step30-current-v1', 'step': '30', 'context': context,
               'execution': executions, 'execution_files': execution_files,
               'outputs': [current.file_record(path, role, project) for role, path in outputs]}
    if companion_errors:
        receipt['companion_errors'] = companion_errors
    write_json(receipt_path, receipt)
    validate_current_step30(project)
    return doc


def validate_current_step30(project: Path):
    """Consumer verification, including the declared correlation result/decks."""
    import _opensta_current as current
    project = Path(project).resolve(strict=True)
    report = project / 'reports/phase3/spice_correlation.json'
    receipt = _load(report.with_suffix('.current.json'))
    if (receipt.get('schema') != 'step30-current-v1' or receipt.get('step') != '30'
            or receipt.get('project') != str(project) or receipt.get('stage') != 'post_route_extracted'):
        raise Refusal('CURRENT_STEP30_PROJECT_STAGE_MISMATCH', str(report))
    context = receipt['context']
    subject, now = current_context(project, context['image'], Path(context['pdk_root']), context['pdk'],
                                    sta_step_dir=Path(context['sta_step_dir']))
    if now != context or any(receipt.get(k) != subject[k] for k in subject):
        raise Refusal('CURRENT_STEP30_INPUT_BYTES_CHANGED', str(report))
    current.check_files(receipt['execution_files'], project)
    executions = receipt['execution']
    if not executions or not any(e.get('tool') == 'ngspice' for e in executions):
        raise Refusal('CURRENT_STEP30_SIMULATOR_NOT_RUN', str(report))
    if not any(e.get('tool') == 'OpenSTA' for e in executions):
        raise Refusal('CURRENT_STEP30_WRITE_PATH_SPICE_NOT_RUN', str(report))
    expected_files = {}
    for i, ex in enumerate(executions):
        if type(ex.get('rc')) is not int or not ex.get('argv'):
            raise Refusal('CURRENT_STEP30_EXECUTION_FAILED', str(ex))
        expected_files.update({f'{role}:{i}': ex[role] for role in ('script', 'log')})
    if {r['role']: r['path'] for r in receipt['execution_files']} != expected_files:
        raise Refusal('CURRENT_STEP30_EXECUTION_CONSUMPTION_MISSING', str(report))
    current.check_files(receipt['outputs'], project)
    outputs = {r['role']: r['path'] for r in receipt['outputs']}
    if outputs.get('correlation') != str(report) or outputs.get('tool_result') != str(project / 'reports/phase3/spice_path_tool.json'):
        raise Refusal('CURRENT_STEP30_RESULT_CONSUMPTION_MISSING', str(report))
    tool = _load(project / 'reports/phase3/spice_path_tool.json')
    if executions != _current_executions(tool):
        raise Refusal('CURRENT_STEP30_EXECUTION_ADOPTION_MISMATCH', str(report))
    products = {role: str(path) for role, path in _current_products(project, tool)}
    if {role: path for role, path in outputs.items() if role.startswith('product:')} != products:
        raise Refusal('CURRENT_STEP30_NATIVE_PRODUCTS_MISMATCH', str(report))
    doc = _load(report)
    if any(doc.get(k) != v for k, v in tool.items()):
        raise Refusal('CURRENT_STEP30_ADOPTION_MISMATCH', str(report))
    companion_errors = _current_companion_errors(project, tool, subject, context)
    if (doc.get('companion_errors', []) != companion_errors
            or receipt.get('companion_errors', []) != companion_errors):
        raise Refusal('CURRENT_STEP30_COMPANION_ERROR_ADOPTION_MISMATCH', str(report))
    decks = {r['path'] for r in receipt['outputs'] if r['role'].startswith('deck:')}
    named = {r['deck'] for arm in tool['detail'].values() for variant in ('base', 'mutated')
             for r in (arm.get(variant) or {}).get('paths') or [] if r.get('deck')}
    if not named or decks != named or not all(Path(p).is_relative_to(project / 'phase3/tool_arms/30') for p in decks):
        raise Refusal('CURRENT_STEP30_DECK_CONSUMPTION_MISSING', str(report))
    canonical = project / 'phase3/stage3/spice/correlation.spice'
    canonical_log = canonical.with_suffix('.log')
    declared_result = canonical.with_suffix('.json')
    if outputs.get('declared_result') != str(declared_result) or _load(declared_result) != doc:
        raise Refusal('CURRENT_STEP30_DECLARED_RESULT_CONSUMPTION_MISSING', str(report))
    if outputs.get('canonical_deck') != str(canonical) or outputs.get('canonical_log') != str(canonical_log):
        raise Refusal('CURRENT_STEP30_CANONICAL_CONSUMPTION_MISSING', str(report))
    first = next((r['deck'] for arm in tool['detail'].values()
                  for r in (arm.get('base') or {}).get('paths') or [] if r.get('deck')), None)
    first_sim = next((ex for ex in executions if ex['tool'] == 'ngspice'), None)
    if first is None or first_sim is None or digest(canonical) != digest(Path(first)) or digest(canonical_log) != digest(Path(first_sim['log'])):
        raise Refusal('CURRENT_STEP30_CANONICAL_ADOPTION_MISMATCH', str(report))
    return doc
