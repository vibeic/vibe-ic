"""SOURCE_ONLY native-report reader/completion controls, no native row credit.

Real checked-in RDB/log calibration bytes back the parser controls. Synthetic
GDS hash headers test the parser protocol only; they do not claim that these
reports measured that GDS. Completion controls inject at the observation seam,
exercise the actual consumer and never create qualification/native receipts.
"""
import re
import shutil

import pytest
import gds_antenna_deck_check as owner
from _hostpaths import require_repo


@pytest.fixture
def native_report(tmp_path, request):
    if not hasattr(owner, '_d43_metric_readback'):
        pytest.skip('metric reader absent on exact main; canonical controls still execute')
    kind = getattr(request, 'param', 'violation')
    source = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'calibration')
    rdb, log = tmp_path / 'native.lyrdb', tmp_path / 'native.log'
    shutil.copyfile(source / ('native_antenna_' + kind + '.lyrdb'), rdb)
    text = (source / ('native_antenna_' + kind + '.log')).read_text()
    gds = tmp_path / 'source_only_protocol_subject.gds'
    gds.write_text('SOURCE_ONLY hash-protocol subject; no geometry/native credit\n')
    log.write_text(owner._BIND_PREFIX + owner._sha(gds) + '\n' + text)
    parent = owner._GENERATOR_RE.search(rdb.read_text()).group(1)
    decks = owner._executed_native_decks(text)
    assert len(decks) == 1, 'actual calibrated report must identify its single source rule file'
    return gds, rdb, log, {'parent': parent, 'rule': next(iter(decks))}


@pytest.mark.parametrize('native_report', ['clean', 'violation'], indirect=True)
def test_actual_calibration_RDB_is_regraded_without_self_approving_population(native_report):
    gds, rdb, log, deck = native_report
    observed = owner._d43_metric_readback(gds, rdb, log, owner._sha(gds), deck)
    assert observed['violations'] == (0 if 'SUCCESS (0' in log.read_text() else 1)
    assert observed['observed_rules']
    assert observed['required_rules'] is None and observed['checked_gate_nets'] is None
    assert observed['population_status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('damage', ['changed_gds', 'changed_parent', 'wrong_rule', 'wrong_tally', 'missing_rdb'])
def test_native_identity_and_completion_damage_refuses(native_report, damage):
    gds, rdb, log, deck = native_report
    original = owner._sha(gds)
    if damage == 'changed_gds':
        gds.write_text('changed source-only subject')
    elif damage == 'changed_parent':
        deck['parent'] += '-foreign'
    elif damage == 'wrong_rule':
        deck['rule'] += '-foreign'
    elif damage == 'wrong_tally':
        log.write_text(re.sub(r'DRC RESULT: FAILURE \(1 violation\(s\)\)',
                             'DRC RESULT: FAILURE (2 violation(s))', log.read_text()))
    else:
        rdb.unlink()
    with pytest.raises(ValueError, match='D43_NATIVE_METRIC_UNBOUND'):
        owner._d43_metric_readback(gds, rdb, log, original, deck)
