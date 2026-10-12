"""R-0915-43 — step 30's declared correlation record exists, ran or refused.

THE GAP: step 30 declares two outputs —

    phase3/stage3/spice/*.sp OR *.spice OR sim_spice/*.sp
    phase3/stage3/spice/correlation.json OR reports/phase3/spice_correlation.json

and a run whose driver RAN produced the first and not the second: the deck and
the log were on disk, the correlation had been computed, and the record the
flow asks for was absent. The numbers existed and nothing published them.

The cause is a path that belongs to no list. `run_installed_pdk_path_correlation`
wrote `reports/phase3/spice_path_correlation.json` — not one of the two declared
outputs, and not one of the three this module's OWN loader
(`_check_spice_correlation_json`) reads. Four names, and the one written was in
neither list.

The other direction matters just as much. MEASURED on sha256 run11: the driver
reached a real conclusion — "Liberty grid tolerance could not be derived", an
implemented-capability failure rather than a capability gap — and the declared
record did not exist. A refusal that is only written under a name nobody
declares is silence to every reader of the declared one.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import spice_correlation_check as SCC  # noqa: E402
import _path_layout as _pl  # noqa: E402


# ------------------------------------------------- the record, when it RAN
import test_step30_r4_current_failures as current_fixture
_REASON = 'SOFTWARE_FIXTURE_ONLY current producer refused'


def _produced(tmp_path, monkeypatch):
    p, folder, lib = current_fixture.fixture.project(tmp_path)
    current_fixture.correlation_tool(p, folder, lib, monkeypatch,
                                     mismatch='CORRELATED', companion='success')
    result = SCC.run_installed_pdk_path_correlation(p, str(lib))
    assert result['status'] == 'RAN', result
    return p, result


def _refused(tmp_path, monkeypatch):
    p, _, lib = current_fixture.fixture.project(tmp_path)
    def refused(*args, **kwargs):
        raise RuntimeError(_REASON)
    monkeypatch.setattr(SCC, 'run_installed_pdk_path_correlation', refused)
    written, notes = [], []
    assert current_fixture.fixture.R._step30_tool_arm(
        p, current_fixture.fixture.pdk(lib), written, notes) is False
    gate = json.loads((p / 'reports/phase2/gates/spice_correlation.json').read_text())
    assert gate['passed'] is False and gate['summary']['current_binding'] == 'REFUSED'
    return p, written, notes


def test_the_driver_writes_the_path_the_step_declares(tmp_path, monkeypatch):
    import _flow_yaml
    from _hostpaths import require_repo
    flow = _flow_yaml.load(require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                                      'flow', 'phase1_phase2_phase3.yaml'))
    step = next(row for row in flow['steps'] if str(row['id']) == '30')
    assert 'phase3/stage3/spice/correlation.json OR reports/phase3/spice_correlation.json' in step['required_outputs']
    p, result = _produced(tmp_path, monkeypatch)
    assert (_pl.spice_dir(p) / 'correlation.json').is_file()
    assert (p / 'reports/phase3/spice_correlation.json').is_file()
    assert SCC.main([str(p), '--json', str(p / 'consumer.json')]) == 0
    assert result['status'] == 'RAN'


def test_it_is_the_same_dict_and_never_a_second_summary(tmp_path, monkeypatch):
    p, result = _produced(tmp_path, monkeypatch)
    declared = json.loads((_pl.spice_dir(p) / 'correlation.json').read_text())
    report = json.loads((p / 'reports/phase3/spice_correlation.json').read_text())
    assert declared == report == result['report']
    assert declared['current_subject']['stage'] == 'post_route_extracted'


def test_the_declared_path_is_the_first_one_this_modules_loader_reads(tmp_path):
    """The record must land where the consumer already looks, not beside it."""
    proj = tmp_path / "p"
    (proj / "phase3/stage3/spice").mkdir(parents=True)
    declared = _pl.spice_dir(proj) / "correlation.json"
    declared.write_text(json.dumps({"correlation": {"verdict": "PASS"}}))
    got = SCC._check_spice_correlation_json(proj)
    assert got is not None and got["correlation"]["verdict"] == "PASS"


def test_the_record_carries_what_was_correlated_the_numbers_and_a_verdict(tmp_path, monkeypatch):
    p, result = _produced(tmp_path, monkeypatch)
    report = SCC._check_spice_correlation_json(p)
    row = report['detail']['ngspice']['base']['paths'][0]
    assert row['status'] == 'MEASURED'
    assert row['sta_ns'] > 0 and row['spice_ns'] > 0 and row['tolerance_pct'] > 0
    assert row['error_pct'] == (row['spice_ns'] - row['sta_ns']) / row['sta_ns'] * 100
    assert row['verdict'] == SCC.path_correlation_verdict(row['error_pct'], row['tolerance_pct'])
    assert report['verdict'] == result['verdict'] == 'PASS'


# ------------------------------------------- the record, when it REFUSED

def test_the_runner_writes_a_named_refusal_at_the_declared_path(tmp_path, monkeypatch):
    p, written, _ = _refused(tmp_path, monkeypatch)
    for relative in ('phase3/stage3/spice/correlation.json', 'reports/phase3/spice_correlation.json',
                     'phase3/stage3/spice/spice_correlation_not_run.json'):
        path = p / relative
        assert path.is_file() and str(path) in written
        assert json.loads(path.read_text())['verdict'] == 'NOT_MEASURED'


def test_the_refusal_and_the_disclosure_are_the_same_payload(tmp_path, monkeypatch):
    p, _, _ = _refused(tmp_path, monkeypatch)
    paths = ['phase3/stage3/spice/correlation.json', 'reports/phase3/spice_correlation.json',
             'phase3/stage3/spice/spice_correlation_not_run.json']
    records = [json.loads((p / relative).read_text()) for relative in paths]
    assert records[0] == records[1] == records[2]


def test_the_refusal_carries_a_verdict_and_a_reason(tmp_path, monkeypatch):
    p, _, notes = _refused(tmp_path, monkeypatch)
    record = json.loads((_pl.spice_dir(p) / 'correlation.json').read_text())
    assert record['verdict'] == 'NOT_MEASURED' and record['correlation_ran'] is False
    assert record['status'] == 'ERROR' and record['reason_class'] == 'EXECUTION_ERROR'
    assert record['reason'] == _REASON
    assert any(_REASON in note for note in notes)


def test_a_record_the_run_already_produced_is_left_alone(tmp_path, monkeypatch):
    p, result = _produced(tmp_path, monkeypatch)
    path = _pl.spice_dir(p) / 'correlation.json'
    before = path.read_bytes()
    SCC._write_declared_correlation_refusal(p, 'ERROR', _REASON)
    assert path.read_bytes() == before
    assert json.loads(before) == result['report']
    assert json.loads((p / 'reports/phase3/spice_correlation.json').read_text()) == result['report']


def test_the_declared_refusal_is_only_written_when_the_correlation_did_not_run(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('A measured correlation must never become a refusal')
    monkeypatch.setattr(SCC, '_write_declared_correlation_refusal', unexpected)
    p, result = _produced(tmp_path, monkeypatch)
    assert result['status'] == 'RAN' and result['report']['verdict'] == 'PASS'
    assert not (_pl.spice_dir(p) / 'spice_correlation_not_run.json').exists()
    assert SCC.main([str(p), '--json', str(p / 'consumer.json')]) == 0
