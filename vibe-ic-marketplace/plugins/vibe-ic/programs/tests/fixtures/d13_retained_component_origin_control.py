"""Actual readonly retained bytes; authority hook is TEST_ONLY, never row adoption."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, os.environ.get('VIBEIC_D13_COMPONENT_PROGRAMS', str(Path(__file__).resolve().parents[1])))
import flow109_metric_acceptance as metrics


@pytest.fixture
def retained(tmp_path, monkeypatch):
    proposal = Path(os.environ['VIBEIC_D13_COMPONENT_PROPOSAL'])
    source = json.loads(proposal.read_text())
    project = Path(source['project'])
    marker = '__test_only_unadopted_source__'
    authority_source = tmp_path / 'unadopted-source.json'
    safe = metrics._safe_project_file
    monkeypatch.setattr(metrics, '_safe_project_file',
        lambda p, rel: authority_source if rel == marker else safe(p, rel))
    approved = metrics._approved_document
    def control(current):
        authority_source.write_text(json.dumps(current))
        monkeypatch.setattr(metrics, '_approved_document', lambda p, rel, **k:
            ({'source': {'path': marker}}, {'reference': current['execution']})
            if rel == 'adopted/base_07/simulation_execution.json' else approved(p, rel, **k))
        return metrics._d13_execution(project, current)
    return source, control


def test_current_interrupted_collector_can_supply_retained_components(retained):
    source, consume = retained
    before = copy.deepcopy(source['execution'])
    observed = consume(source)
    assert observed == before
    assert observed['parent_exit_code'] == 1
    owner = json.loads((Path(source['project']) / observed['original_owner']['path']).read_text())
    assert owner['status'] == 'INTERRUPTED' and owner['canonical_pass'] is False


def test_parent_failure_cannot_be_relabelled_success(retained):
    source, consume = retained
    source['execution']['parent_exit_code'] = 0
    with pytest.raises(metrics.MetricRefusal, match='actual original CID/image/failed terminal'):
        consume(source)


def test_missing_native_coverage_population_refuses(retained):
    source, consume = retained
    coverage = source['execution']['coverage_report']['path']
    source['execution']['artifacts'] = [r for r in source['execution']['artifacts'] if r['path'] != coverage]
    with pytest.raises(metrics.MetricRefusal, match=coverage):
        consume(source)


def test_wrong_original_producer_refuses(retained):
    source, consume = retained
    entries = json.loads(Path(source['execution']['original_source_readset']['path']).read_text())['files']
    source['execution']['original_producer'] = next(r for r in entries if Path(r['path']).name == 'testbench_gen.py')
    with pytest.raises(metrics.MetricRefusal, match='original ordinary producer invocation'):
        consume(source)


def test_changed_native_record_hash_refuses(retained):
    source, consume = retained
    source['execution']['unit_junit']['sha256'] = '0' * 64
    with pytest.raises(metrics.MetricRefusal):
        consume(source)


def test_unknown_retained_origin_refuses(retained):
    source, consume = retained
    source['execution']['origin'] = 'unreviewed-origin'
    with pytest.raises(metrics.MetricRefusal, match='D13_EXECUTION_ORIGIN_INVALID'):
        consume(source)


def test_substitute_entry_script_cannot_claim_original_launch(retained, tmp_path):
    source, consume = retained
    original = Path(source['execution']['original_entry_script']['path'])
    substitute = tmp_path / 'substitute-entry.sh'
    substitute.write_bytes(original.read_bytes())
    source['execution']['original_entry_script'] = {
        'path': str(substitute), 'sha256': hashlib.sha256(substitute.read_bytes()).hexdigest()}
    with pytest.raises(metrics.MetricRefusal, match='original launched entry script'):
        consume(source)
