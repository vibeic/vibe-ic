"""A01--A05 Default execution using the existing analog producers and consumers.

Failures are blocking for the named step. Missing inputs or unavailable native
execution are NOT_MEASURED, never a fabricated qualification or performance
PASS. In particular A05's operating point proves convergence only; converter
accuracy still belongs to the later transient/performance consumers.

``run(program, args, cwd=..., outputs=...)`` is supplied by the native runner.
The @ngspice program invokes the installed simulator in its admitted container.
Per-block overrides live in config.blocks[<declared name>]; existing A02 smoke
declarations may also be read directly, without the Flow109 admission machinery.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import sys
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(project: Path, value: Any) -> Path:
    raw = value.get('path') if isinstance(value, dict) else value
    if not isinstance(raw, (str, Path)) or not str(raw):
        raise ValueError('file path is absent')
    path = Path(raw)
    path = path if path.is_absolute() else project / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if isinstance(value, dict) and value.get('sha256') and _sha(path) != value['sha256']:
        raise ValueError('stale input digest: ' + str(path))
    return path


def _stale(project: Path, body: dict) -> list[str]:
    prov = body.get('_provenance', {})
    if not isinstance(prov, dict):
        return []
    rows = list(prov.get('inputs') or [])
    if isinstance(prov.get('input'), dict):
        rows.append(prov['input'])
    if isinstance(prov.get('rendered_from'), dict):
        rows.extend(prov['rendered_from'].values())
    stale = []
    for row in rows:
        if not isinstance(row, dict) or not row.get('path') or not row.get('sha256'):
            continue
        try:
            _file(project, row)
        except (OSError, ValueError):
            stale.append(str(row['path']))
    return stale


def _op_deck(text: str) -> str:
    """Keep the circuit/stimulus, replacing analysis commands in a NEW deck."""
    lines, control, dropped_card = [], False, False
    for line in text.splitlines():
        token = line.strip().split(maxsplit=1)[0].lower() if line.strip() else ''
        if line.lstrip().startswith('+') and dropped_card:
            continue
        if token == '.control':
            if control:
                raise ValueError('nested .control block')
            control = True
            continue
        if token == '.endc':
            if not control:
                raise ValueError('unmatched .endc')
            control = False
            continue
        if control:
            continue
        if token in {'.tran', '.ac', '.dc', '.noise', '.op', '.pz', '.tf', '.sens',
                     '.meas', '.measure', '.save', '.print', '.plot', '.end'}:
            dropped_card = True
            continue
        if line.strip() and not line.lstrip().startswith('*'):
            dropped_card = False
        lines.append(line)
    if control:
        raise ValueError('unterminated .control block')
    return '\n'.join(lines) + '\n.op\n.end\n'


def _op_values(text: str) -> dict[str, float]:
    # ngspice's .op batch table uses two columns; branch currents retain their
    # #branch suffix and are recorded separately from the node-voltage table.
    values = {}
    table = False
    for line in text.splitlines():
        if re.fullmatch(r'(?i)\s*(?:Node\s+Voltage|Source\s+Current)\s*', line):
            table = True
            continue
        if not table:
            continue
        match = re.fullmatch(r'\s*([^\s=]+)\s+([-+]?(?:\d*\.?\d+(?:[eE][-+]?\d+)?|nan|inf(?:inity)?))\s*', line, re.I)
        if match:
            value = float(match[2])
            if not math.isfinite(value):
                raise ValueError('nonfinite operating-point value: ' + match[1])
            values[match[1]] = value
        elif line.strip() and not set(line.strip()) <= {'-', '=', ' ', '\t'}:
            table = False
    return values


def run_step(step_id: str, project: Path, block: dict, options: dict,
             run: Callable) -> dict:
    """Execute one front-end responsibility; never substitute an approval file."""
    project = Path(project).resolve()
    name = str(block.get('name') or block.get('block') or '')
    if not name or Path(name).name != name or name in {'.', '..'}:
        return {'status': 'FAIL', 'detail': 'ANALOG_BLOCK_NAME_INVALID', 'outputs': []}
    config = options.get('config') or {}
    cfg = (config.get('blocks') or {}).get(name) or {}
    bdir = project / 'phase3/analog' / name
    base = Path(options['attempt_dir']) if options.get('attempt_dir') else project / 'reports/analog_native'
    outdir = base / step_id / name
    outdir.mkdir(parents=True, exist_ok=True)
    executions: list[dict] = []
    outputs: list[str] = []

    def finish(status: str, detail: str, **extra: Any) -> dict:
        return {'status': status, 'detail': detail, 'outputs': list(dict.fromkeys(outputs)),
                'executions': executions, **extra}

    def call(program: str, args: list, *, cwd: Path | None = None,
             artefacts: list[Path] | None = None) -> dict:
        try:
            result = run(program, [str(v) for v in args], cwd=cwd,
                         outputs=[str(p) for p in artefacts or []])
        except OSError as exc:
            result = {'returncode': 127, 'stdout': '', 'stderr': str(exc)}
        executions.append({'program': program, 'args': [str(v) for v in args], **result})
        outputs.extend(str(p) for p in artefacts or [] if p.is_file())
        return result

    def failed(result: dict, label: str) -> dict | None:
        rc = result.get('returncode')
        text = str(result.get('stdout', '')) + '\n' + str(result.get('stderr', ''))
        if rc == 0 and not re.search(r'VACUOUS_PASS|\[SKIP\]|PASS_WITH_WAIVER', text):
            return None
        unavailable = rc in {2, 64, 69, 75, 124, 125, 126, 127, 137, 143} or (
            isinstance(rc, int) and rc < 0)
        status = 'NOT_MEASURED' if unavailable or rc == 0 else 'FAIL'
        return finish(status, label + ': ' + (text.strip()[-1500:] or f'rc={rc}'))

    def check(program: str, *, per_block: bool = True) -> dict | None:
        report = outdir / (Path(program).stem + '.json')
        args = [project]
        if per_block:
            args.extend(['--block', name])
        args.extend(['--json', report])
        return failed(call(program, args, artefacts=[report]), Path(program).stem)

    if step_id == 'A01':
        path = bdir / 'spec.json'
        if not path.is_file() or _stale(project, _read(path)):
            result = call('analog_a1_spec_emit.py', [project, '--block', name])
            failure = failed(result, 'A01_SPEC_PRODUCER')
            if failure:
                return failure
        if not path.is_file():
            return finish('NOT_MEASURED', 'A01_SPEC_ABSENT: no block-attributed specifications')
        if _stale(project, _read(path)):
            return finish('NOT_MEASURED', 'A01_SPEC_INPUT_CHANGED: retained author-owned specification requires reconciliation')
        failure = check('analog_a1_spec_extract_check.py')
        if failure:
            return failure
        outputs.append(str(path))
        return finish('PASS', 'A01_SPEC_CONSUMER_PASS: current attributed specifications checked')

    if step_id == 'A02':
        inventory = call('pdk_analog_completeness_check.py', [project])
        failure = failed(inventory, 'A02_PDK_INVENTORY')
        if failure:
            return failure
        smokes = cfg.get('model_smokes', config.get('model_smokes'))
        if smokes is None:
            smokes = _read(project / 'input/flow109/A02.json').get('smokes')
        if not isinstance(smokes, list) or not smokes:
            return finish('NOT_MEASURED', 'A02_MODEL_SMOKE_DECKS_ABSENT: provide existing model_smokes decks and their measurements')
        from flow109_analog_model_check import consume
        needs, rows = [], []
        ids: set[str] = set()
        for smoke in smokes:
            if not isinstance(smoke, dict):
                return finish('FAIL', 'A02_MODEL_SMOKE_INVALID: expected a deck declaration')
            ident = str(smoke.get('id') or '')
            measures = smoke.get('required_measurements')
            if (not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', ident) or ident in ids
                    or not isinstance(measures, list) or not measures
                    or not all(isinstance(m, str) and re.fullmatch(r'[A-Za-z_]\w*', m) for m in measures)
                    or not smoke.get('device') or not smoke.get('corner')):
                return finish('FAIL', 'A02_MODEL_SMOKE_INVALID: id/device/corner/measurement declarations required')
            ids.add(ident)
            try:
                model = _file(project, smoke.get('model'))
                deck = _file(project, smoke.get('deck'))
                # The existing consumer rebinds logs and deck/model bytes to
                # this actual project. No launch registry or approval is read.
                need = {'id': ident, 'device': smoke['device'], 'corner': smoke['corner'],
                        'required_measurements': measures,
                        'model': {'path': str(model.relative_to(project)), 'sha256': _sha(model)},
                        'deck': {'path': str(deck.relative_to(project)), 'sha256': _sha(deck)}}
            except FileNotFoundError as exc:
                return finish('NOT_MEASURED', 'A02_MODEL_SMOKE_INPUT_ABSENT: ' + str(exc))
            except ValueError as exc:
                return finish('FAIL', 'A02_MODEL_SMOKE_INPUT_INVALID: ' + str(exc))
            # A unique log prevents an earlier successful run from supplying
            # evidence when a new invocation fails before it opens its log.
            import tempfile
            with tempfile.NamedTemporaryFile(prefix=ident + '-', suffix='.log',
                                             dir=outdir, delete=False) as handle:
                log = Path(handle.name)
            result = call('@ngspice', ['-b', '-o', log, deck], cwd=project, artefacts=[log])
            failure = failed(result, 'A02_NATIVE_MODEL_SMOKE')
            if failure:
                return failure
            if not log.is_file() or not log.stat().st_size:
                return finish('NOT_MEASURED', 'A02_NATIVE_MODEL_LOG_ABSENT: ' + ident)
            needs.append(need)
            rows.append({**need, 'returncode': result['returncode'],
                         'log': {'path': str(log.relative_to(project)), 'sha256': _sha(log)}})
        checked = consume(project, {'required_smokes': needs}, {'smokes': rows})
        if checked['verdict'] != 'PASS':
            return finish('FAIL', checked['reason'], metrics=checked.get('smokes', []))
        return finish('PASS', 'A02_NATIVE_MODEL_SMOKES_PASS: declared devices/corners only',
                      metrics=checked['smokes'])

    if step_id == 'A03':
        features = {**(options.get('features') or {}), **(config.get('features') or {})}
        testability = cfg.get('analog_testability', features.get('analog_testability'))
        trim = cfg.get('analog_trim', features.get('analog_trim'))
        if testability is False and trim is False:
            return finish('NOT_APPLICABLE', 'A03_TESTABILITY_AND_TRIM_EXPLICITLY_NOT_SELECTED')
        return finish('NOT_MEASURED', 'A03_TESTABILITY_IMPLEMENTATION_ABSENT: '
                      + ('applicable declarations require a real producer/consumer'
                         if testability is True or trim is True else 'applicability is undeclared'))

    if step_id == 'A04':
        topology = bdir / 'topology.json'
        markdown = bdir / 'topology.md'
        if not markdown.is_file() or _stale(project, _read(topology)):
            args = [project, '--block', name]
            if options.get('pdk'):
                args.extend(['--pdk', options['pdk']])
            failure = failed(call('analog_a2_topology_emit.py', args), 'A04_TOPOLOGY_PRODUCER')
            if failure:
                return failure
        if not markdown.is_file():
            return finish('NOT_MEASURED', 'A04_TOPOLOGY_ABSENT: no supported source-bound topology')
        if _stale(project, _read(topology)):
            return finish('NOT_MEASURED', 'A04_TOPOLOGY_INPUT_CHANGED: retained design requires reconciliation')
        failure = check('analog_a2_topology_select_check.py')
        if failure:
            return failure
        outputs.extend(str(p) for p in (markdown, topology) if p.is_file())
        return finish('PASS', 'A04_TOPOLOGY_CONSUMER_PASS: performance remains for native analysis')

    if step_id == 'A05':
        netlist = bdir / (name + '.sp')
        testbench = bdir / ('tb_' + name + '.sp')
        provenance = bdir / 'netlist_provenance.json'
        if not netlist.is_file() or _stale(project, _read(provenance)):
            args = [project, '--block', name]
            if options.get('pdk'):
                args.extend(['--pdk', options['pdk']])
            if options.get('container'):
                args.extend(['--container', options['container']])
            failure = failed(call('analog_a3_netlist_emit.py', args), 'A05_NETLIST_PRODUCER')
            if failure:
                return failure
        if not netlist.is_file():
            return finish('NOT_MEASURED', 'A05_NETLIST_ABSENT')
        if _stale(project, _read(provenance)):
            return finish('NOT_MEASURED', 'A05_NETLIST_INPUT_CHANGED: retained design requires reconciliation')
        if not provenance.is_file() and (bdir / 'topology.json').is_file():
            # A sized, delivered circuit can predate this runner's emission
            # sidecar. Validate its actual cards; do not manufacture history
            # or regenerate bytes consumed by an ongoing native analysis.
            from analog_existing_design_validate import RECEIPT
            validation = bdir / RECEIPT
            args = [project, '--block', name, '--pdk', options.get('pdk', '')]
            if options.get('container'):
                args.extend(['--container', options['container']])
            failure = failed(call('analog_existing_design_validate.py', args,
                                  artefacts=[validation]),
                             'A05_EXISTING_DESIGN_VALIDATION')
            if failure:
                return failure
        failure = check('analog_a3_netlist_gen_check.py')
        if failure:
            return failure
        for checker in ('analog_netlist_pdk_check.py', 'analog_netlist_connectivity_check.py',
                        'analog_netlist_include_order_check.py', 'analog_netlist_path_lint.py'):
            failure = check(checker)
            if failure:
                return failure
        try:
            if cfg.get('op_deck'):
                deck = _file(project, cfg['op_deck'])
                text = deck.read_text()
                if re.search(r'(?im)^\s*\.(?:tran|ac|dc|noise)\b|^\s*(?:tran|ac|dc|noise)\s', text):
                    return finish('FAIL', 'A05_OP_DECK_HAS_OTHER_ANALYSIS: choose a dedicated OP deck')
            else:
                if not testbench.is_file():
                    return finish('NOT_MEASURED', 'A05_OP_STIMULUS_ABSENT: provide op_deck or existing testbench')
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', prefix='native-op-', suffix='.sp',
                                                 dir=bdir, delete=False) as handle:
                    handle.write(_op_deck(testbench.read_text()))
                    deck = Path(handle.name)
        except FileNotFoundError as exc:
            return finish('NOT_MEASURED', 'A05_OP_INPUT_ABSENT: ' + str(exc))
        except (OSError, ValueError) as exc:
            return finish('FAIL', 'A05_OP_DECK_INVALID: ' + str(exc))
        outputs.append(str(deck))
        # Reuse the simulation consumer's path/lexical readers, without its
        # later performance-measurement requirements: OP is not accuracy.
        from analog_native_sim import _included_paths, _deck_text
        if netlist.resolve() not in _included_paths(deck.resolve()):
            return finish('FAIL', 'A05_OP_DUT_NOT_INCLUDED: ' + str(netlist))
        subckt = str(cfg.get('dut_subckt') or name).casefold()
        declared_subckts = {token.casefold() for token in re.findall(
            r'(?im)^\s*\.subckt\s+(\S+)', _deck_text(netlist))}
        if subckt not in declared_subckts:
            return finish('FAIL', 'A05_OP_DUT_SUBCIRCUIT_ABSENT: ' + subckt)
        top = re.sub(r'(?ims)^\s*\.subckt\b.*?^\s*\.ends\b[^\n]*', '', _deck_text(deck))
        instantiated = False
        for line in top.splitlines():
            if not re.match(r'(?i)^\s*x\S+\s', line):
                continue
            try:
                tokens = shlex.split(line)
            except ValueError:
                continue
            positional = []
            for token in tokens:
                if '=' in token or token.casefold() == 'params:':
                    break
                positional.append(token)
            if positional and positional[-1].casefold() == subckt:
                instantiated = True
                break
        if not instantiated:
            return finish('FAIL', 'A05_OP_DUT_NOT_INSTANTIATED: ' + subckt)
        import tempfile
        with tempfile.NamedTemporaryFile(prefix='native-op-', suffix='.log',
                                         dir=outdir, delete=False) as handle:
            log = Path(handle.name)
        result = call('@ngspice', ['-b', '-o', log, deck], cwd=bdir, artefacts=[deck, log])
        failure = failed(result, 'A05_NATIVE_OP')
        if failure:
            return failure
        text = log.read_text(errors='replace') if log.is_file() else ''
        from flow109_analog_model_check import _fatal_diagnostic
        import _prose_polarity
        fatal = _fatal_diagnostic(text, _prose_polarity)
        if fatal or re.search(r'(?i)doAnalyses: iteration limit reached|singular matrix|too few parameters|aborted', text):
            return finish('FAIL', 'A05_NATIVE_OP_FAILED: ' + str(fatal or 'native convergence diagnostic'))
        try:
            values = _op_values(text)
        except ValueError as exc:
            return finish('FAIL', 'A05_NATIVE_OP_NONFINITE: ' + str(exc))
        if not values:
            return finish('NOT_MEASURED', 'A05_NATIVE_OP_VALUES_ABSENT: successful exit alone is not convergence evidence')
        from analog_a3_netlist_emit import dc_op_rail_excursions
        supply = cfg.get('supply_v')
        if supply is None:
            tb_record = _read(provenance).get('testbench', {})
            if isinstance(tb_record, dict):
                for condition in tb_record.get('conditions') or []:
                    match = re.fullmatch(r'supply\s*=.*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s+V', str(condition))
                    if match:
                        supply = float(match[1])
                        break
        rails = dc_op_rail_excursions(text, supply)
        if rails:
            return finish('FAIL', 'A05_NATIVE_OP_RAIL_EXCURSION', metrics={'rail_excursions': rails})
        outputs.extend(str(p) for p in (netlist, testbench, provenance) if p.is_file())
        return finish('PASS', 'A05_NETLIST_AND_NATIVE_OP_PASS: operating point only; '
                      'transient/performance acceptance NOT_MEASURED',
                      metrics={'operating_point': values, 'performance_acceptance': 'NOT_MEASURED',
                               'rail_invariant': 'CHECKED' if supply is not None else 'NOT_MEASURED'})

    return finish('NOT_MEASURED', 'ANALOG_FRONT_STEP_UNSUPPORTED: ' + str(step_id))
