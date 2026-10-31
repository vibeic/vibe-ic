"""Actual retained EQY reader boundary; no execution adoption or tool replay.

The independently adopted execution is not yet available. Exercise the existing
post-launch reader block verbatim, with real approved mode/model inputs and an
immutable native packet. Authority/launch admission remains outside this test;
no approval is manufactured. Mutations affect private artifact copies only.
"""
import ast
import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import pytest
import flow109_metric_acceptance as metrics
import librelane_eqy as native_reader


pytestmark = pytest.mark.skipif(not os.environ.get('FLOW109_D25_EXTERNAL_CENSUS_PROJECT'),
                                reason='sealed native subject and approved mode required')
_ACTIVE = False


def _no_tools(event, args):
    if _ACTIVE and event == 'subprocess.Popen':
        raise AssertionError('reader control attempted a native tool replay: ' + str(args[1]))


sys.addaudithook(_no_tools)


@pytest.fixture(scope='module')
def retained():
    project = Path(os.environ['FLOW109_D25_EXTERNAL_CENSUS_PROJECT'])
    prepared = metrics._d25_inputs(project)
    path = project / 'reports/lec_eqy_execution.json'
    doc = json.loads(path.read_text())
    before = {r['path']: (native_reader.digest(project / r['path']),
                          (project / r['path']).stat().st_mtime_ns) for r in doc['files']}
    assert all(before[r['path']][0] == r['sha256'] for r in doc['files'])
    # Verbatim actual consumer, from full partition judgement through stable
    # input checks. Only its final packaging is replaced with a test return.
    tree = ast.parse(inspect.getsource(native_reader.d25_reopen)).body[0]
    start = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.With))
    block = ast.Module(body=tree.body[start:-1], type_ignores=[])
    code = compile(ast.fix_missing_locations(block), inspect.getfile(native_reader), 'exec')
    yield project, prepared, doc, code
    after = {r['path']: (native_reader.digest(project / r['path']),
                         (project / r['path']).stat().st_mtime_ns) for r in doc['files']}
    assert after == before, 'control changed immutable native proof artifacts'


@pytest.fixture
def subject(retained, tmp_path):
    original, prepared, doc, code = retained
    project = tmp_path / 'private-subject'
    for record in doc['files']:
        target = project / record['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original / record['path'], target)
    prepared = {**prepared, 'mode': copy.deepcopy(prepared['mode']),
                'qualification': copy.deepcopy(prepared['qualification'])}
    return project, prepared, copy.deepcopy(doc), code


def read_boundary(subject):
    global _ACTIVE
    project, prepared, doc, code = subject
    path = project / 'reports/lec_eqy_execution.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(doc).encode()
    path.write_bytes(raw)
    namespace = {**vars(native_reader), 'metrics': metrics, 'tempfile': tempfile,
                 'hashlib': hashlib, 'project': project, 'prepared': prepared,
                 'doc': doc, 'path': path, 'raw': raw,
                 'native': project / doc['native_directory'],
                 'reader_sources': native_reader.d25_sources()}
    _ACTIVE = True
    try:
        exec(code, namespace)
    finally:
        _ACTIVE = False
    return namespace['proof'], namespace['output_bits']


def partition(subject):
    project, _, doc, _ = subject
    root = project / doc['native_directory'] / 'scratch/partitions'
    paths = list(root.glob('*.json'))
    assert len(paths) == 1  # actual retained group-all population
    return paths[0], json.loads(paths[0].read_text())


def test_real_cutpoints_preserve_complete_proof_and_external_coverage(subject):
    _, prepared, _, _ = subject
    _, part = partition(subject)
    assert len(part['partition']['outbits']) > len(prepared['mode']['outputs'])
    try:
        proof, outputs = read_boundary(subject)
        observed = proof['verdict'], outputs
    except metrics.MetricRefusal as exc:
        observed = str(exc)
    assert observed == ('PASS', prepared['mode']['outputs']), observed
    assert proof['compared_points'] == proof['proven_points'] == 1
    assert proof['partitions'] == {'spm.c.0': {'pdr': 'PASS', 'sat': 'UNKNOWN'}}


@pytest.mark.parametrize('damage', ['missing-external', 'foreign-outbit',
                                   'foreign-external-roster', 'unqualified-cell'])
def test_actual_reader_refuses_changed_population(subject, damage):
    project, prepared, doc, _ = subject
    path, part = partition(subject)
    output = next(iter(prepared['mode']['outputs']))
    if damage == 'missing-external':
        del part['partition']['outbits'][output]
    elif damage == 'foreign-outbit':
        part['partition']['outbits']['foreign_output_not_in_either_native_view'] = [0]
    elif damage == 'unqualified-cell':
        prepared['qualification']['qualified_cell_types'].remove(doc['live_cells'][0])
    else:
        # Both actual native views gain an external bit, while the original
        # required mode stays unchanged. Rehash only this private test packet.
        part['partition']['outbits']['foreign_external'] = [0]
        for side in ('gold', 'gate'):
            for filename in ('census.json', 'after.json'):
                target = project / doc['native_directory']
                target = target.parent / side / filename
                value = json.loads(target.read_text())
                module = value['modules'][prepared['mode']['top']]
                module['ports']['foreign_external'] = {'direction': 'output', 'bits': [37]}
                module['netnames']['foreign_external'] = {'bits': [37]}
                target.write_text(json.dumps(value))
                relative = str(target.relative_to(project))
                for records in (doc['files'], doc['derivation'][side]['files']):
                    for record in records:
                        if record['path'] == relative:
                            record['sha256'] = native_reader.digest(target)
    path.write_text(json.dumps(part))
    with pytest.raises(metrics.MetricRefusal, match='D25_PARTITION_CENSUS_UNBOUND'):
        read_boundary(subject)


def test_internal_cutpoint_partition_unknown_cannot_become_pass(subject):
    project, _, doc, _ = subject
    native = project / doc['native_directory']
    statuses = list((native / 'scratch/strategies').glob('*/pdr/status'))
    assert len(statuses) == 1
    statuses[0].write_text('UNKNOWN\n')
    proof, _ = read_boundary(subject)
    assert proof['verdict'] == 'INCONCLUSIVE'
    assert proof['partitions'] == {'spm.c.0': {'pdr': 'UNKNOWN', 'sat': 'UNKNOWN'}}
