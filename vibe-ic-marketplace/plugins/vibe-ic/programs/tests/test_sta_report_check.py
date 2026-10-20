#!/usr/bin/env python3
"""Tests for sta_report_check.py — wrapper for eda_report_audit --mode sta"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "sta_report_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_empty_project(tmp_path):
    r = _run([str(tmp_path)]); assert r.returncode == 1


@pytest.mark.parametrize('slack,unit,basis,prefix,at_head,expected_rc', [
    (0.5, 'ns', 'PRE_LAYOUT_ESTIMATE', '', False, 0),
    (-0.5, 'ps', 'PRE_LAYOUT_ESTIMATE', '\t#\t', False, 1),
    (-0.5, None, 'PRE_LAYOUT_ESTIMATE', '# ', False, 1),
    (0.5, 'ns', 'POST_ROUTE_SPEF', '# ', False, 1),
    (0.5, 'ns', 'PRE_LAYOUT_ESTIMATE', '\u2003#\u2003', True, 0),
])
def test_indented_report_keeps_unit_basis_and_negative_slack(
        tmp_path, slack, unit, basis, prefix, at_head, expected_rc):
    """Tail stamps, whitespace and unknown units cannot erase a violation."""
    import json
    folder = tmp_path / 'phase3/stage3/sta'
    folder.mkdir(parents=True)
    metadata = f'{prefix}STA_BASIS: {basis}\n'
    if unit:
        metadata += f'{prefix}STA_TIME_UNIT: {unit}\n'
    body = ('OpenSTA\nStartpoint: launch_q\nEndpoint: capture_d\nPath Type: max\n'
            + (' ' * 64 + '0.00 0.01 generic_net (net)\n') * 128
            + f'wns max {slack}\nwns min 0.25\ntns 0.00\n')
    report = folder / 'pre_pnr_timing.rpt'
    report.write_text(metadata + body if at_head else body + metadata)
    out = tmp_path / 'audit.json'
    r = _run([str(tmp_path), '--under', str(report.relative_to(tmp_path)),
              '--json', str(out)])
    assert r.returncode == expected_rc, r.stderr
    record = json.loads(out.read_text())
    rules = {row['rule'] for row in record['findings']}
    if slack < 0:
        assert 'STA_REAL_VIOLATION_FOUND' in rules
        if unit:
            assert record['summary']['setup_wns_ns'] == slack * (0.001 if unit == 'ps' else 1)
        else:
            assert 'setup_wns_ns' not in record['summary']
            assert record['summary']['setup_wns'] == slack
    if basis == 'POST_ROUTE_SPEF':
        assert 'STA_BASIS_CONTRADICTS_SCOPE' in rules


def test_time_unit_reader_has_no_quadratic_indent_cost():
    """Issue3342: CPU VALUE assertion, independent of scheduler wait time.

    The ns stamp is deliberately at EOF after ordinary indented report rows.
    This does not pass because a new output or helper is absent on the parent.
    """
    import time
    sys.path.insert(0, str(PROG.parent))
    import eda_report_audit as audit
    text = (' ' * 256 + '0.00 0.01 generic_net (net)\n') * 8192
    text += '# STA_TIME_UNIT: ns\n'
    start = time.process_time()
    match = audit._STA_TIME_UNIT_RE.search(text)
    elapsed_cpu = time.process_time() - start
    assert match and match.group('unit') == 'ns'
    assert elapsed_cpu < 1.0, f'time-unit reader CPU seconds: {elapsed_cpu:.6f}'
