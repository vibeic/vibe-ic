"""A8's retained source-bound optional characterization helper.

No mixed-signal factories or native authority are supplied by this module.
"""
from __future__ import annotations
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
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import _progress_run
import execution_modes as em
from _prose_polarity import is_denied, sentence_scope
from execution_adapters_analog import PROGRAMS, write_json
from execution_analog_worker import checked_json

def _path(project: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        old = Path(json.loads(os.environ['VIBEIC_EXECUTION_BINDING'])['objective']['original_project'])
        if path.is_relative_to(old):
            path = project / path.relative_to(old)
        else:
            pdk = old / json.loads(os.environ['VIBEIC_EXECUTION_BINDING'])['objective']['parameters']['pdk_root']
            if not path.is_relative_to(pdk):
                raise em.Refusal('ANALOG_EXTERNAL_NATIVE_INPUT_UNBOUND', str(path))
    else:
        path = project / em._relative(value)
    if not path.is_file() or path.is_symlink():
        raise em.Refusal('ANALOG_NATIVE_INPUT_MISSING', str(path))
    return path

def _run(argv: list[str], directory: Path, label: str, timeout_s: int, env=None) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    out, err = directory / (label + '.stdout'), directory / (label + '.stderr')
    import shlex
    import _container_exec as ce
    completed = ce.run_in_container('host', shlex.join(argv))
    rc = completed.returncode
    out.write_text(completed.stdout or '')
    err.write_text(completed.stderr or '')
    receipt = {'argv': argv, 'observer_pid': os.getpid(), 'rc': rc,
               'stdout_sha256': em.digest(out), 'stderr_sha256': em.digest(err)}
    write_json(directory / (label + '.receipt.json'), receipt)
    if rc != 0:
        raise em.Refusal('ANALOG_NATIVE_PROCESS_FAILED', label + ':' + str(rc))
    return receipt

def characterize(project: Path, block: str, params: dict, records: Path) -> dict:
    """Generate Liberty from exact declared decks and measured timing arcs."""
    planfile = project / f'phase3/analog/{block}/characterization_plan.json'
    plan = checked_json(planfile)
    if not plan.get('pins') or not plan.get('arcs') or plan.get('block') != block:
        raise em.Refusal('ANALOG_CHARACTERIZATION_PLAN_REQUIRED', block)
    measurements, receipts, arcs = {}, [], []
    for index, arc in enumerate(plan['arcs']):
        deck = _path(project, arc['deck'])
        receipt = _run(['ngspice', '-b', str(deck)], records, f'characterize-{block}-{index}', params['timeout_s'])
        text = (records / f'characterize-{block}-{index}.stdout').read_text()
        if re.search(r'(?:\.meas|measure).*failed|failed.*(?:\.meas|measure)|timestep too small', text, re.I):
            raise em.Refusal('ANALOG_CHARACTERIZATION_MEASURE_FAILED', str(deck))
        values = {}
        for match in re.finditer(r'^\s*(\w+)\s*=\s*([-+0-9.eE]+)', text, re.M):
            lo, hi = sentence_scope(text, match.start(1), match.end(2), extra_breaks=('\n',))
            if is_denied(text[lo:hi]):
                raise em.Refusal('ANALOG_CHARACTERIZATION_MEASURE_FAILED', str(deck))
            values[match.group(1)] = float(match.group(2))
        row = {}
        for quantity in ('cell_rise', 'cell_fall', 'rise_transition', 'fall_transition'):
            name = arc['measurements'].get(quantity)
            if not name or name not in values or not math.isfinite(values[name]) or values[name] < 0:
                raise em.Refusal('ANALOG_CHARACTERIZATION_MEASUREMENT_MISSING', quantity)
            row[quantity] = values[name]
        if arc.get('unit') != 's':
            raise em.Refusal('ANALOG_CHARACTERIZATION_UNIT_REQUIRED', block)
        if arc['from'] not in plan['pins'] or arc['to'] not in plan['pins']:
            raise em.Refusal('ANALOG_CHARACTERIZATION_PIN_UNBOUND', block)
        arcs.append((arc, row))
        measurements[str(index)] = {'deck_sha256': em.digest(deck), 'values': row}
        receipts.append(receipt)
    # This deliberately represents only the declared scalar characterization
    # point. It never invents a slew/load grid or unmeasured voltage/temperature.
    hdir = project / f'phase3/analog/hardmacro/{block}'
    original = (hdir / f'{block}.lib').read_text()
    # Preserve the established supply/ground PG declarations and all macro
    # header fields. Characterization may replace only declared signal pins;
    # a measured timing arc must never erase the A8 supply HARVEST contract.
    original_pins = re.findall(r'(?m)^\s*pin\s*\(\s*([^()]+)\s*\)\s*\{', original)
    if set(original_pins) != set(plan['pins']):
        raise em.Refusal('ANALOG_CHARACTERIZATION_PIN_POPULATION_CHANGED', block)
    replacement = {}
    for pin, definition in plan['pins'].items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', pin) or definition.get('direction') not in ('input', 'output', 'inout'):
            raise em.Refusal('ANALOG_CHARACTERIZATION_INTERFACE_INVALID', pin)
        lines = [f'pin ({pin}) {{', f'direction : {definition["direction"]};', 'is_analog : true;']
        for arc, row in arcs:
            if arc['to'] != pin:
                continue
            if arc.get('timing_sense') not in ('positive_unate', 'negative_unate', 'non_unate'):
                raise em.Refusal('ANALOG_CHARACTERIZATION_SENSE_REQUIRED', pin)
            lines += ['timing () {', f'related_pin : "{arc["from"]}";',
                      f'timing_sense : {arc["timing_sense"]};']
            for name, value in row.items():
                lines.append(f'{name} (scalar) {{ values ("{value:.17g}"); }}')
            lines.append('}')
        lines.append('}')
        replacement[pin] = '\n'.join(lines)
    spans = []
    for match in re.finditer(r'(?m)^\s*pin\s*\(\s*([^()]+)\s*\)\s*\{', original):
        depth, end = 1, match.end()
        while end < len(original) and depth:
            depth += (original[end] == '{') - (original[end] == '}')
            end += 1
        if depth:
            raise em.Refusal('ANALOG_LIBERTY_MALFORMED', block)
        spans.append((match.start(), end, replacement[match.group(1)]))
    for begin, end, text in reversed(spans):
        original = original[:begin] + text + original[end:]
    original = re.sub(r'time_unit\s*:\s*"[^"]+";', 'time_unit : "1s";', original)
    original = original.replace('interface_timing : false;', 'interface_timing : true;')
    (hdir / f'{block}.lib').write_text(original)
    result = {'native_engine': 'ngspice', 'plan_sha256': em.digest(planfile),
              'measurements': measurements, 'native_receipts': receipts,
              'scope': 'declared scalar timing arcs only; not full PVT/library acceptance'}
    write_json(hdir / 'characterization.json', result)
    return {'entrypoint': 'execution_analog_mixed_worker.characterize', 'native_receipts': receipts}
