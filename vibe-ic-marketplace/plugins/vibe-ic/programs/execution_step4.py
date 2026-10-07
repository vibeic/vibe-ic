"""Step 4 simulator arms over one frozen professional cocotb bundle.

Functional simulation is arm-local. Verilator code coverage is a disclosed
complementary measurement, rerun inside each arm; it is never borrowed from
the other candidate. Canonical gates, rather than a simulator rc, qualify it.
"""
import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import _atomic_artefact as atomic
import _sim_results_bridge as results
import verilator_coverage_measure as coverage


def _dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_text(path, json.dumps(data, indent=2, sort_keys=True) + '\n')


def stage(project, output):
    """Copy issued source inputs, never prior simulator measurements/builds."""
    from execution_frontend_worker import _verify_manifest
    manifest = _verify_manifest(project, '4')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for rel, expected in manifest['files'].items():
        if Path(rel).is_absolute() or '..' in Path(rel).parts:
            raise ValueError('4: frozen source outside project')
        path = Path(project) / rel
        if path.is_symlink() or not path.is_file():
            raise ValueError('4: frozen source missing or nonregular: ' + rel)
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError('4: frozen source changed: ' + rel)
        # The manifest may include an existing bundle directory. Admit its
        # sources/configuration, but not a previous measurement or binary.
        if not (rel.startswith(('input/', 'phase1/', 'phase2/stage1/rtl/')) or
                ('/sim_professional/' in rel and
                 (path.suffix in ('.py', '.json', '.sva') or path.name == 'Makefile') and
                 not any(part.startswith('sim_build') for part in path.parts))):
            continue
        target = output / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(content)
    return output, manifest['parameters']


def _simulate(bundle, simulator, *, instrument=False, jobs=4, rtl=None):
    if simulator not in ('icarus', 'verilator'):
        raise ValueError('4: unsupported simulator')
    if not 1 <= jobs <= 4:
        raise ValueError('4: build_jobs must be between 1 and 4')
    build = Path(tempfile.mkdtemp(prefix='sim_build_' + simulator + '_', dir=bundle))
    junit = bundle / ('coverage_results.xml' if instrument else 'results.xml')
    dat = bundle / 'coverage.dat'
    junit.unlink(missing_ok=True)
    if instrument:
        dat.unlink(missing_ok=True)
    argv = ['make', '-j' + str(jobs), 'SIM=' + simulator,
            'SIM_BUILD=' + str(build), 'COCOTB_RESULTS_FILE=' + str(junit)]
    if rtl:
        argv += ['VERILOG_SOURCES=' + ' '.join(str(path) for path in rtl)]
    environment = {**os.environ, 'RANDOM_SEED': '1'}
    if instrument:
        environment['COMPILE_ARGS'] = '--coverage --coverage-line --coverage-toggle'
        argv += ['SIM_ARGS=+verilator+coverage+file+' + str(dat)]
    cp = subprocess.run(argv, cwd=bundle, capture_output=True, text=True,
                        env=environment, timeout=1200)
    log = bundle / ('coverage_run.log' if instrument else 'cocotb_run.log')
    atomic.write_text(log, cp.stdout + '\n' + cp.stderr)
    summary = results.parse_junit(junit)
    if summary:
        # Empty JUnit outcome elements are still outcomes. Element truthiness
        # can otherwise let an all-skipped result look like a passing test.
        tree = ET.parse(junit)
        for key, tag in (('failures', 'failure'), ('errors', 'error'), ('skipped', 'skipped')):
            summary[key] = max(summary[key], len(tree.findall('.//' + tag)))
    clean = bool(cp.returncode == 0 and summary and summary['tests'] > 0 and
                 summary['passed'] > 0 and summary['failures'] == 0 and
                 summary['errors'] == 0 and summary['skipped'] == 0 and
                 'PROFESSIONAL_TB PASS' in cp.stdout + cp.stderr)
    return dict(argv=argv, rc=cp.returncode, junit=str(junit), log=str(log),
                summary=summary, verdict='PASS' if clean else 'FAIL')


def measure_bundle(project, bundle, rtl, *, jobs=4):
    """Use the canonical parser and RTL scope on fresh native coverage bytes."""
    destination = project / 'reports/phase2' / coverage.COVERAGE_MEASUREMENT_REL
    destination.unlink(missing_ok=True)
    run = _simulate(bundle, 'verilator', instrument=True, jobs=jobs, rtl=rtl)
    dat = bundle / 'coverage.dat'
    if run['verdict'] != 'PASS' or not dat.is_file() or not dat.stat().st_size:
        return dict(verdict='FAIL', reason='STEP4_COVERAGE_RUN_FAILED', run=run)
    parsed = coverage.parse_coverage_dat(str(dat))
    scoped = coverage.scope_totals(parsed, [str(p) for p in rtl])
    if scoped is None:
        return dict(verdict='FAIL', reason='STEP4_COVERAGE_RTL_SCOPE_EMPTY', run=run)
    tb = bundle / ('tb_' + bundle.name + '.py')
    payload = dict(tool='verilator', measurement_mode='measure-cocotb',
                   coverage_dat=str(dat), coverage_dat_sha256=coverage_hash(dat),
                   testbench=str(tb), testbenches=[str(tb)],
                   rtl_sources=[str(p) for p in rtl], totals=scoped['totals'],
                   scope_files=scoped['scope_files'], per_file=parsed['per_file'],
                   format_detected=parsed['format_detected'],
                   path_namespace=parsed['path_namespace'],
                   simulator_run=run)
    _dump(destination, payload)
    # Apply the existing thresholds, with no arm-specific relaxation.
    check = coverage.cmd_check(coverage.build_parser().parse_args(
        ['check', '--coverage-json', str(destination)]))
    return dict(verdict='PASS' if check == 0 else 'FAIL',
                reason='STEP4_CANONICAL_COVERAGE_CHECK', run=run)


def coverage_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def produce(project, output, simulator, **parameters):
    project, bound = stage(Path(project), Path(output))
    top = bound.get('top') or parameters.get('top')
    if not top or Path(top).name != top:
        raise ValueError('4: a safe top is required')
    bundle = project / 'phase2/stage1/sim_professional' / top
    if not (bundle / 'Makefile').is_file():
        import professional_tb_gen
        generated = professional_tb_gen.generate(project)
        if generated.get('status') != 'PASS':
            raise ValueError('4: professional bundle unavailable')
    rtl = sorted((project / 'phase2/stage1/rtl').rglob('*.v'))
    rtl += sorted((project / 'phase2/stage1/rtl').rglob('*.sv'))
    functional = _simulate(bundle, simulator)
    # Publish the same arm's actual JUnit bytes at the normal consumer seam.
    # A view is not a second measurement; the source transcript remains bound.
    primary_junit = Path(functional['junit'])
    if primary_junit.is_file():
        sim = project / 'phase2/stage1/sim'
        sim.mkdir(parents=True, exist_ok=True)
        atomic.write_bytes(sim / 'results.xml', primary_junit.read_bytes())
    measured = measure_bundle(project, bundle, rtl)
    summary = functional['summary'] or {}
    _dump(project / 'reports/phase2/gates/professional_tb.json',
          dict(status=functional['verdict'], out_dir=str(bundle),
               ran_cocotb=True, cocotb_rc=functional['rc'],
               cocotb_pass_marker=functional['verdict'] == 'PASS',
               functional_mismatch=functional['verdict'] != 'PASS',
               cocotb_test_denominator=summary, simulator=simulator))
    evidence = str(Path(functional['junit']).relative_to(project))
    _dump(project / 'reports/phase2/coverage/coverage_actual.json',
          dict(verdict=functional['verdict'], verification_track='professional_tb',
               evidence=evidence, evidence_sha256=coverage_hash(Path(functional['junit']))
               if Path(functional['junit']).is_file() else None,
               simulator=simulator, tests=summary.get('tests', 0)))
    _dump(project / 'step4_execution.json', dict(schema='execution_step4/1',
          simulator=simulator, functional=functional, coverage=measured,
          shared_checker='cocotb + verilator code coverage',
          qualification='CANONICAL_CONSUMER_REQUIRED'))
    from execution_frontend_providers import _concrete_outputs, CANONICAL_ROWS
    paths = _concrete_outputs(project, CANONICAL_ROWS['4'])
    folder = 'phase2/stage1/4_simulation'
    _dump(project / 'steps' / folder / 'written.json', dict(id='4',
          n_required_outputs=len(CANONICAL_ROWS['4']), n_produced=len(paths),
          produced=[dict(rel=rel, spec=spec, kind='file',
                         size=(project / rel).stat().st_size,
                         mtime=(project / rel).stat().st_mtime)
                    for rel, spec in sorted(paths.items())], findings=[]))
    _dump(project / 'steps/index.json', dict(steps=[dict(id='4',
          name='Simulation', folder=folder)]))
    return project / 'step4_execution.json'


def main(simulator):
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--outputs', required=True)
    args = parser.parse_args()
    produce(args.inputs, args.outputs, simulator)


def gate_commands(contract):
    """Use the declared tool-arm consumer interface, including advisories."""
    commands = {}
    def collect(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ('program_exit_zero', 'optional_program_exit_zero', 'advisory_program_exit_zero'):
                    command = value if isinstance(value, str) else value['command']
                    commands[command.split()[0]] = command
                else:
                    collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)
    collect(contract.get('gate', {}))
    return commands


def validate(project, facts, gate_names):
    """BLOCKING: canonical Step4 and every mandatory consumer must pass."""
    import _flow_yaml
    import flow_compliance_check as flow
    import execution_modes as em
    from execution_frontend_providers import _concrete_outputs
    root = Path(project)
    contract = next(row for row in _flow_yaml.load()['steps'] if str(row['id']) == '4')
    canonical = flow.check_step(root, contract, {}, strict_step_binding=True)
    commands = gate_commands(contract)
    gates = {}
    for name in gate_names:
        command = commands.get(name)
        if command is None:
            gates[name] = 'NOT_MEASURED'
            continue
        outcome = flow.__check_program_exit_zero(root, command)
        structured = flow._report_verdict(flow._command_json_report(root, command))
        if structured in ('NOT_APPLICABLE', 'NOT_MEASURED', 'SKIP', 'SKIPPED'):
            gates[name] = 'NOT_MEASURED'
        elif outcome.passed and outcome.exit_code == 0:
            gates[name] = 'PASS'
        elif outcome.exit_code == 1 or structured == 'FAIL':
            gates[name] = 'FAIL'
        else:
            gates[name] = 'NOT_MEASURED'
    required = tuple(contract.get('required_outputs') or ())
    concrete = _concrete_outputs(root, required)
    outputs = {rel: em.digest(root / rel) for rel in concrete}
    for path in root.glob('phase2/stage1/sim_professional/*/*'):
        if path.is_file() and not path.is_symlink() and path.suffix in ('.dat', '.log'):
            outputs[str(path.relative_to(root))] = em.digest(path)
    record = root / 'step4_execution.json'
    if record.is_file():
        outputs['step4_execution.json'] = em.digest(record)
    complete = all(any(fnmatch.fnmatch(rel, alt.strip()) for rel in concrete
                      for alt in str(spec).split(' OR ')) for spec in required)
    if canonical.status == 'FAIL' or 'FAIL' in gates.values():
        verdict = 'FAIL'
    elif canonical.status == 'PASS' and complete and gates and all(v == 'PASS' for v in gates.values()):
        verdict = 'PASS'
    else:
        verdict = 'NOT_MEASURED'
    return em.Evidence(facts, verdict, gates, outputs, metrics={'source_boundary': 1.0},
                       detail='Step4 canonical consumers: ' + '; '.join(canonical.reasons))
