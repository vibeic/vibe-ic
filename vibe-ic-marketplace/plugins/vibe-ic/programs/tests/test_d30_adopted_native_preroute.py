"""Existing actual preroute readers reuse qualified proof/STA, never replay them."""
import json
import os
from pathlib import Path
import sys

import pytest
import flow109
import flow109_metric_acceptance as metrics


_ACTIVE = False
_NORMALIZATIONS = []


def no_replay(event, args):
    if not _ACTIVE or event != 'subprocess.Popen':
        return
    argv = list(map(str, args[1]))
    # Existing structural byte normalizer only: no synthesis, EQY, STA,
    # qualification or global preflight. The recipe is producer-owned.
    if (Path(argv[0]).name == 'yosys' and argv[1:4] == ['-Q', '-T', '-p']
            and len(argv) == 5 and argv[4].startswith('read_verilog ')
            and argv[4].count(';') == 2
            and '; hierarchy -top ' in argv[4]
            and '; write_verilog -noattr ' in argv[4]):
        _NORMALIZATIONS.append(argv)
        return
    raise AssertionError('proof/STA/preflight replay attempted: ' + str(argv))


sys.addaudithook(no_replay)


@pytest.fixture
def actual():
    raw = os.environ.get('FLOW109_D30_NATIVE_PREROUTE_PROJECT')
    if not raw:
        pytest.skip('genuine independently adopted native37 and canonical38 required')
    project = Path(raw)
    manifest = json.loads(Path(os.environ['FLOW109_D30_NATIVE_PREROUTE_MANIFEST']).read_text())
    context = flow109.execution_context(flow109.resolve_plan(manifest['features']), 'D30', 'D30')
    import librelane_eqy
    librelane_eqy.d25_sources()
    return project, context


def invoke(project, context):
    global _ACTIVE
    _ACTIVE = True
    try:
        return flow109.dft_preroute_admission(project, context)
    finally:
        _ACTIVE = False


def test_actual_preroute_reopens_adopted_native_subject_and_all_timing_libraries(actual):
    project, context = actual
    old = {name: (project / name).read_bytes() for name in
           ['reports/lec.json', 'reports/lec.rpt', 'reports/lec_eqy_execution.json']}
    try:
        admission = invoke(project, context)
        observed = admission['functional_equivalence']['path']
    except flow109.Flow109Error as exc:
        observed = exc.code
    assert observed == 'reports/lec_eqy_execution.json', observed
    chain = admission['normalized_preroute_chain']
    assert chain['reason'] == 'D30_DELIVERY_ARTIFACT_UNBOUND'
    assert {p['input']['sha256'] for p in chain['points'].values()} == {
        admission['adopted_netlist']['sha256']}
    timing = metrics.d30_consumed_timing(project, admission)
    assert timing['status'] == 'MEASURED', timing
    assert len(timing['value']) == 3
    assert all(len(c['libraries']) == 2 for c in timing['value'])
    assert {name: (project / name).read_bytes() for name in old} == old
    output = os.environ.get('FLOW109_D30_NATIVE_PREROUTE_OBSERVATION')
    if output:
        Path(output).write_text(json.dumps({'admission': admission, 'timing': timing,
            'structural_normalizations_only': _NORMALIZATIONS}, indent=2) + '\n')


def test_named_native_refusal_cannot_use_legacy_proof(actual, monkeypatch):
    """Explicit failed-consumer boundary double, not a proof/approval fixture."""
    project, context = actual
    monkeypatch.setattr(metrics, 'accept_d25', lambda *_: {
        'status': 'NOT_MEASURED', 'reason': 'EXPLICIT_NATIVE_UNQUALIFIED_CONTROL'})
    with pytest.raises(flow109.Flow109Error, match='FLOW109_D25_PROOF_NOT_ACCEPTED'):
        invoke(project, context)


def test_native_proof_never_substitutes_foreign_delivery(actual, monkeypatch, tmp_path):
    import lec_gate_netlist_select as selector
    project, context = actual
    foreign = tmp_path / 'foreign.v'
    foreign.write_text('module foreign; endmodule\n')
    monkeypatch.setattr(selector, 'pnr_consumed_netlist', lambda *_: (foreign, 'foreign delivery', False))
    with pytest.raises(flow109.Flow109Error, match='FLOW109_D30_NETLIST_FOREIGN'):
        invoke(project, context)


def test_LIB_alias_still_requires_every_native_read(tmp_path, monkeypatch):
    """Existing explicit neutral STA/scan fixture; no native qualification."""
    from test_flow109_d30_metric_acceptance import _case, _write, _reseal_native
    context, _, timing_path, _ = _case(tmp_path, monkeypatch)
    timing = json.loads(timing_path.read_text())
    for arm in timing['post_scan_arms'].values():
        folder = tmp_path / arm['native']['folder']
        config = json.loads((folder / 'config.json').read_text())
        config['LIB'] = config.pop('CELL_LIBS')
        _write(folder / 'config.json', config)
        (folder / 'tt/sta.log').write_text(''.join(line for line in
            (folder / 'tt/sta.log').read_text().splitlines(True)
            if not line.startswith('Reading cell library')))
    _reseal_native(tmp_path, timing_path)  # fresh neutral fixture only
    admission = flow109.dft_preroute_admission(tmp_path, context)
    observed = metrics.d30_consumed_timing(tmp_path, admission)
    assert observed['status'] == 'NOT_MEASURED'
    assert observed['reason'] == 'D30_NATIVE_READSET_UNPROVEN'
