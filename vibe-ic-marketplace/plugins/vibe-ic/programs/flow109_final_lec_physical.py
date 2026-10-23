"""Blocking, source-bound physical-chip proof-view preparation for D44.

Reuses the 70-flow's exact wrapper and DEF-proven supply restoration. Native
functional elaboration retains every functional port and cell; only unmatched
producer-declared power ports proven unused or equal to their declared powered
level by the native model may be projected.
This writes separate proof views, never an adopted netlist, DEF, or LEC verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from _atomic_artefact import write_json, write_text

SCHEMA = 'vibeic.flow109.final-lec-physical-inputs.v1'
KIND = 'def_bound_powered_chip_functional_views_v1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f'object required: {path}')
    return value


def bound(project, record):
    if not isinstance(record, dict) or not record.get('path') or not record.get('sha256'):
        raise ValueError('physical input is not path/digest bound')
    path = (project / record['path']).resolve()
    if not path.is_file() or sha(path) != record['sha256']:
        raise ValueError(f'physical input is stale or absent: {path}')
    return path


def record(path):
    return {'path': str(path), 'sha256': sha(path)}


def _word(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def _interface(model):
    return {name: (value['direction'], len(value['bits']))
            for name, value in model['ports'].items()}


def unused_supply_projection(model, candidates, declared_supplies):
    """Require an inert rail or a native constant matching its powered level."""
    projected = []
    used = {bit for cell in model.get('cells', {}).values()
            for bits in cell.get('connections', {}).values() for bit in bits}
    for name in candidates:
        port = model['ports'].get(name)
        if name not in declared_supplies or not port or port['direction'] != 'inout':
            raise ValueError(f'non-supply interface projection refused: {name}')
        other = {bit for key, item in model['ports'].items() if key != name
                 for bit in item['bits']}
        bits = set(port['bits'])
        # JSON's constant tokens are global values, not shared wire identities.
        # A native supply-pad model can already resolve the rail to its powered
        # value. Require that exact producer-declared value; X/Z and reversed
        # rail models refuse. Do not treat other cells' literal zeros as aliases.
        expected = declared_supplies[name]
        if (len(port['bits']) == 1 and expected in (0, 1)
                and port['bits'] == [str(expected)]):
            projected.append(name)
            continue
        if not all(isinstance(bit, int) for bit in bits) or bits & (used | other):
            raise ValueError(f'supply remains functionally connected: {name}')
        projected.append(name)
    return projected


def native_fill_inputs(paths):
    """Select an existing native FillInsertion view through its owning consumer.

    The route-adoption schema remains unchanged. A fill view is authoritative
    only when the original fill owner revalidates its native input/output chain.
    """
    adopted = read(paths['adopted_receipt'])
    tool = (adopted.get('odb') or {}).get('tool')
    if not isinstance(tool, dict):
        return {}
    import librelane_fill_dfm as fill
    if tool.get('step') != fill.ODB_FILL_STEP:
        raise ValueError('unsupported native adopted-view producer')
    state_path = paths['adopted_state'].resolve()
    parts = state_path.parts
    indices = [i for i in range(len(parts) - 1)
               if parts[i:i + 2] == ('phase3', 'librelane')]
    if len(indices) != 1:
        raise ValueError('native fill state has no unique project owner')
    owner = Path(*parts[:indices[0]])
    if (paths['adopted_receipt'].resolve() != (owner / fill.RECORD_REL).resolve()
            or Path(tool['state']).resolve() != state_path
            or sha(state_path) != tool['state_sha256']):
        raise ValueError('native fill adopted state/owner differs')
    receipt = fill.validate_fill_handoff(owner, tool, routed_def=Path(tool['subject']))
    state = read(state_path)
    if (Path(state['nl']).resolve() != paths['adopted_netlist'].resolve()
            or Path(state['def']).resolve() != paths['final_def'].resolve()
            or sha(paths['final_def']) != tool['filled_def_sha256']):
        raise ValueError('native fill final netlist/DEF selection differs')
    binding = tool['binding']
    dependencies = [state_path, state_path.parent / 'vibeic_receipt.json',
                    Path(binding['input_state']), Path(binding['config'])]
    dependencies += [Path(name) for field in ('state_files', 'config_files')
                     for name in receipt['input'].get(field, {})]
    if any(not path.is_file() for path in dependencies):
        raise ValueError('native fill dependency absent')
    expected = {**receipt['input'].get('state_files', {}),
                **receipt['input'].get('config_files', {}),
                str(state_path): tool['state_sha256'],
                str(state_path.parent / 'vibeic_receipt.json'): binding['receipt_sha256'],
                str(Path(binding['input_state'])): receipt['input']['state'],
                str(Path(binding['config'])): receipt['input']['config']}
    if any(sha(path) != expected[str(path)] for path in dependencies):
        raise ValueError('native fill input/output dependency changed')
    return {str(path.resolve()): expected[str(path)] for path in dependencies}


def produce(project, manifest_path, output, *, before=None):
    import phase3_one_shot_runner as phase3
    import lec_post_layout_check as legacy
    project, output = Path(project).resolve(), Path(output).resolve()
    manifest_path = Path(manifest_path).resolve()
    manifest = read(manifest_path)
    if manifest.get('schema') != SCHEMA:
        raise ValueError('physical input schema differs')
    top, logical = manifest.get('top'), manifest.get('logical_top')
    if not all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', str(x)) for x in (top, logical)):
        raise ValueError('explicit physical and logical tops required')
    names = ('rtl', 'adopted_netlist', 'adopted_state', 'adopted_receipt',
             'final_def', 'wrapper', 'wrapper_record', 'liberty', 'io_liberty')
    paths = {name: bound(project, manifest.get(name)) for name in names}
    if paths['wrapper_record'] != project / 'reports/phase3/io_pad_chip_top.json':
        raise ValueError('canonical wrapper producer receipt required')
    wrapper = read(paths['wrapper_record'])
    if (project / wrapper.get('chip_top_verilog', '')).resolve() != paths['wrapper']:
        raise ValueError('wrapper differs from producer receipt')
    native_inputs = native_fill_inputs(paths)
    adopted, state = read(paths['adopted_receipt']), read(paths['adopted_state'])
    if not native_inputs and (adopted.get('verdict') != 'PASS' or not adopted.get('adopted')
            or sha(adopted['adopted_state']) != sha(paths['adopted_state'])
            or sha(state['nl']) != sha(paths['adopted_netlist'])
            or sha(state['def']) != sha(paths['final_def'])):
        raise ValueError('adopted route/netlist/DEF source chain differs')
    physical = phase3._streamout_top(paths['final_def'], logical)[0]
    if physical != top:
        raise ValueError('physical top differs from adopted DEF')
    plan = wrapper.get('power_pad_plan', {})
    if plan.get('domain_topology') != 'single_domain':
        raise ValueError('only producer-declared single-domain powered mode supported')
    supplies = {plan.get('power_net'): 1, plan.get('ground_net'): 0}
    if len(supplies) != 2 or not all(isinstance(x, str) and x for x in supplies):
        raise ValueError('power/ground authority incomplete')
    output.mkdir(parents=True, exist_ok=False)
    gold, gold_chain = phase3._lec_physical_top_gold(
        project, logical, top, paths['rtl'], output)
    gate, gate_chain, constants = phase3._lec_restore_aux_connections(
        project, top, paths['adopted_netlist'], paths['final_def'], output, legacy)
    if constants and (set(constants) != set(supplies)
                      or constants[plan['power_net']] != 1
                      or constants[plan['ground_net']] != 0):
        raise ValueError('restored power conditions differ from producer authority')
    yosys = Path(shutil.which('yosys')).resolve()
    inputs = {str(manifest_path): sha(manifest_path),
              **{str(path): sha(path) for path in paths.values()}, **native_inputs}
    models, projections, outputs, commands = {}, {}, {}, []
    for side, source in [('gold', gold), ('gate', gate)]:
        model_path = output / f'{side}.elaborated.json'
        script = output / f'{side}.elaborate.ys'
        write_text(script, ''.join('read_liberty -ignore_miss_func ' + _word(paths[k]) + '\n'
                                  for k in ('liberty', 'io_liberty'))
                          + 'read_verilog -formal -sv -icells ' + _word(source) + '\n'
                          + f'hierarchy -check -top {top}\nproc\n'
                          + f'prep -top {top} -flatten\ntribuf -formal\nopt_clean -purge\n'
                          + 'write_json ' + _word(model_path) + '\n')
        command = [str(yosys), '-Q', '-T', '-s', str(script)]
        if before:
            before()
        result = subprocess.run(command, capture_output=True, text=True)
        log = output / f'{side}.elaborate.log'
        write_text(log, result.stdout + result.stderr)
        commands.append({'argv': command, 'exit': result.returncode,
                         'script': record(script), 'log': record(log)})
        if result.returncode or not model_path.is_file():
            raise ValueError(f'native {side} functional elaboration failed')
        data = read(model_path)
        module = data['modules'][top]
        # Flattened proof views must have only Yosys-modelled primitives. A
        # surviving macro/blackbox is not a physical-only deletion candidate.
        if any(not cell['type'].startswith('$') for cell in module.get('cells', {}).values()):
            raise ValueError(f'unmodelled cell survives {side} functional elaboration')
        models[side] = module
    gold_ports, gate_ports = set(models['gold']['ports']), set(models['gate']['ports'])
    for side, absent in [('gold', gold_ports - gate_ports), ('gate', gate_ports - gold_ports)]:
        projections[side] = unused_supply_projection(models[side], sorted(absent), supplies)
        final = output / f'{side}.functional.v'
        script = output / f'{side}.project.ys'
        write_text(script, 'read_json ' + _word(output / f'{side}.elaborated.json') + '\n'
                          + ''.join(f'delete {top}/w:{name}\n' for name in projections[side])
                          + 'write_verilog -noattr ' + _word(final) + '\n')
        command = [str(yosys), '-Q', '-T', '-s', str(script)]
        if before:
            before()
        result = subprocess.run(command, capture_output=True, text=True)
        log = output / f'{side}.project.log'
        write_text(log, result.stdout + result.stderr)
        commands.append({'argv': command, 'exit': result.returncode,
                         'script': record(script), 'log': record(log)})
        if result.returncode or not final.is_file():
            raise ValueError(f'native {side} supply projection failed')
        outputs[side] = record(final)
    interfaces = {side: {k: v for k, v in _interface(model).items()
                         if k not in projections[side]} for side, model in models.items()}
    if interfaces['gold'] != interfaces['gate']:
        raise ValueError('functional interfaces differ after unused-supply projection')
    if any(sha(path) != digest for path, digest in inputs.items()):
        raise ValueError('physical proof source changed during preparation')
    result = {'schema': SCHEMA, 'producer': 'flow109_final_lec_physical',
              'status': 'PREPARED_NOT_EQUIVALENCE_PROVEN', 'kind': KIND,
              'inputs': inputs, 'top': top, 'logical_top': logical,
              'raw_adopted_netlist': record(paths['adopted_netlist']),
              'wrapper_chain': gold_chain, 'def_supply_chain': gate_chain,
              'powered_mode': supplies, 'projected_supply_ports': projections,
              'projected_native_bits': {side: {name: models[side]['ports'][name]['bits']
                                              for name in names}
                                        for side, names in projections.items()},
              'functional_interfaces': interfaces, 'outputs': outputs,
              'tool': record(yosys), 'commands': commands}
    write_json(output / 'preparation.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('project', type=Path)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = produce(args.project, args.input, args.output)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        write_json(args.output / 'refusal.json', {'status': 'NOT_MEASURED',
                   'reason': 'D44_PHYSICAL_PROOF_INPUT_REFUSED', 'detail': str(exc)})
        print(f'REFUSED: {exc}')
        return 2
    print(result['status'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
