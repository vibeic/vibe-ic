#!/usr/bin/env python3
"""Tests for sta_report_check.py — wrapper for eda_report_audit --mode sta"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "sta_report_check.py"


@pytest.mark.parametrize('reader', ['unit', 'missing_unit', 'liberty', 'basis',
                                    'corner_basis', 'ppa', 'session', 'rigor'])
def test_indented_tail_metadata_is_bounded(tmp_path, reader):
    """#3342: native-shaped indented rows must not hide legal tail stamps.

    The original portable probes keep their 10s guard. This separate owner
    control uses a larger indentation to expose each dependent reader within
    3s, without running an EDA producer or relying on a timing ratio.
    """
    indent, rows = (2048, 2048) if reader == 'ppa' else (1024, 8192)
    body = (' ' * indent + '0.00 0.01 generic_net (net)\n') * rows
    lib = tmp_path / 'neutral.lib'
    lib.write_text('library(neutral) { time_unit : "1ps"; }\n')
    script = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import eda_report_audit as audit
import _sta_basis as basis
import sta_corner_record_completeness_check as corners
from _ppa.backends import opensta
import sta_signoff_rigor_check as rigor
text = Path(sys.argv[2]).read_text()
reader = sys.argv[3]
if reader == 'unit':
    assert audit._sta_time_unit(text)[0] == 'ns'
elif reader == 'missing_unit':
    unit, why = audit._sta_time_unit(text)
    assert unit is None and 'native gap' in why
elif reader == 'liberty':
    assert audit._sta_time_unit(text)[0] == 'ps'
elif reader == 'basis':
    assert basis.declared_basis(text) == 'PRE_LAYOUT'
elif reader == 'corner_basis':
    assert corners.report_basis(text) == corners.BASIS_PRE_LAYOUT
elif reader == 'ppa':
    parsed = opensta.parse_report(text)
    assert parsed.basis_stamp == 'PRE_LAYOUT_ESTIMATE'
    assert parsed.basis_liberty == sys.argv[4]
    assert parsed.basis_sdc == 'constraints.sdc'
    assert parsed.basis_spef == 'neutral.spef'
    assert parsed.signoff_corner == 'SS' and parsed.signoff_corner_count == 2
elif reader == 'session':
    assert 'PNR_SESSION_UNVERIFIED' in audit._sta_in_session_evidence(text)
elif reader == 'rigor':
    assert 'STA_CORNER_BINDING_REFUSED' in str(rigor.evaluate(text))
'''
    metadata = ('STA_BASIS: PRE_LAYOUT_ESTIMATE\n'
                'STA_SIGNOFF_CORNER: SS\nSTA_SIGNOFF_CORNER_COUNT: 2\n'
                'STA_BASIS_SDC: constraints.sdc\nSTA_BASIS_SPEF: neutral.spef\n')
    if reader == 'unit':
        metadata += 'STA_TIME_UNIT: ns\n'
    if reader == 'missing_unit':
        metadata += 'STA_TIME_UNIT_NOT_STATED: native gap\n'
    if reader in ('liberty', 'ppa'):
        metadata += f'STA_BASIS_LIBERTY: {lib}\n'
    if reader == 'session':
        metadata += ('STA_ALIAS_BASIS: sta.rpt\n'
                     'STA_PARASITICS_PROVENANCE: PNR_SESSION_UNVERIFIED\n')
    if reader == 'rigor':
        metadata += 'STA_CORNER_BINDING_REFUSED: unresolved\n'
    report = tmp_path / 'sta.rpt'
    report.write_text('OpenSTA\nPath Type: max\n' + body +
                      'wns max -0.50\nwns min 0.25\ntns 0.00\n' + metadata)
    result = subprocess.run([sys.executable, '-B', '-c', script, str(PROG.parent),
                             str(report), reader, str(lib)],
                            capture_output=True, text=True, timeout=3)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('prefix', ['', '# ', ' \t#\t', '\t'])
def test_tail_marker_grammar_and_unit_conversion(prefix, tmp_path):
    import eda_report_audit as audit
    import _sta_basis
    text = ('OpenSTA\n' + (' ' * 32 + '0.01 generic_net (net)\n') * 64 +
            prefix + 'STA_TIME_UNIT: ps\n' +
            prefix + 'STA_BASIS: POST_ROUTE_SPEF\n')
    row = audit._slack_row('sta.rpt', {'setup_wns_ns': -500.0,
                          'hold_wns_ns': 250.0, 'tns_ns': -1000.0}, text)
    assert row['setup_wns_ns'] == -0.5 and row['hold_wns_ns'] == 0.25
    assert row['tns_ns'] == -1.0
    assert _sta_basis.declared_basis(text) == 'POST_ROUTE'


@pytest.mark.parametrize('stamp', ['STA_TIME_UNIT: zs',
                                  'STA_TIME_UNIT_NOT_STATED: native gap'])
def test_unknown_unit_preserves_negative_reading(stamp):
    import eda_report_audit as audit
    row = audit._slack_row('sta.rpt', {'setup_wns_ns': -0.5,
                          'hold_wns_ns': 0.25, 'tns_ns': -1.0}, stamp + '\n')
    assert row['time_unit'] is None and row['setup_wns'] == -0.5
    assert row['tns'] == -1.0 and row['setup_wns_ns'] is None


def test_marker_values_do_not_cross_lines():
    import eda_report_audit as audit
    import _sta_basis
    assert _sta_basis.declared_basis('STA_BASIS:\nPOST_ROUTE_SPEF\n') is None
    assert audit._sta_time_unit('STA_TIME_UNIT:\nns\n')[0] is None
    assert audit._STA_BASIS_LIBERTY_RE.search('STA_BASIS_LIBERTY:\nforeign.lib\n') is None
