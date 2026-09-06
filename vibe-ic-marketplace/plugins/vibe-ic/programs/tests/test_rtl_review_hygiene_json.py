"""Exercise the real producer/consumer boundary; never substitute benchmark RTL."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import rtl_review_aggregate as aggregate
from _hostpaths import require_repo


def test_real_producer_empty_array_does_not_crash_cli(tmp_path):
    rtl = tmp_path / 'rtl'
    rtl.mkdir()
    (rtl / 'register_slice.sv').write_text(
        'module register_slice(input clk, rst_n, d, output reg q);\n'
        'always @(posedge clk or negedge rst_n)\n'
        'if (!rst_n) q <= 0; else q <= d;\nendmodule\n')
    report = tmp_path / 'report.json'
    proc = subprocess.run(
        [sys.executable, str(Path(aggregate.__file__)), '--rtl-dir', str(rtl),
         '--out-json', str(report)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads((rtl / '.review/hygiene.json').read_text()) == []
    assert json.loads(report.read_text())['total_errors'] == 0


def test_checked_in_rtl_producer_round_trip(tmp_path):
    # Existing published example, resolved from this checkout, not an oracle.
    source = require_repo('vibe-ic-marketplace', 'reference-plugins',
                          'example-ip', 'files', 'tiny_uart.v')
    report = tmp_path / 'hygiene.json'
    proc = subprocess.run(
        [sys.executable, str(aggregate.PROGRAMS_DIR / 'rtl_hygiene_lint.py'),
         str(source), '--json', str(report)], capture_output=True, text=True)
    assert proc.returncode in (0, 1), proc.stderr
    raw = json.loads(report.read_text())
    assert isinstance(raw, list)
    loaded = aggregate._load_hygiene_findings(report)
    assert [(f.rule_id, f.severity, f.file, f.line, f.message) for f in loaded] == [
        (f['rule'], f['severity'], f['file'], f['line'], f['message']) for f in raw]


@pytest.mark.parametrize('wrapped', [False, True])
def test_real_findings_preserve_rules_severity_and_counts(tmp_path, wrapped):
    items = [dict(rule='blocking_in_seq', severity='WARN', file='logic.sv',
                  line=4, message='use nonblocking assignment'),
             dict(rule='multiple_drivers', severity='ERROR', file='logic.sv',
                  line=8, message='multiple writers')]
    path = tmp_path / 'hygiene.json'
    path.write_text(json.dumps({'findings': items} if wrapped else items))
    findings = aggregate._load_hygiene_findings(path)
    assert [(f.rule_id, f.severity, f.line) for f in findings] == [
        ('blocking_in_seq', 'WARN', 4), ('multiple_drivers', 'ERROR', 8)]
    report = aggregate.aggregate(findings)
    assert (report.total_errors, report.total_warns, report.verdict) == (1, 1, 'FAIL')


@pytest.mark.parametrize('content', [None, 'broken json', '{}', 'null', '7',
    '{"findings":{}}', '[null]', '[{"severity":"surprise"}]', '[{}]',
    '[{"rule":"x","file":"logic.sv","line":1,"message":"absent severity"}]'])
def test_unreadable_or_invalid_report_is_not_clean(tmp_path, content):
    path = tmp_path / 'hygiene.json'
    if content is not None:
        path.write_text(content)
    findings = aggregate._load_hygiene_findings(path)
    report = aggregate.aggregate(findings)
    assert report.verdict == 'FAIL'
    assert any(f.rule_id == 'hygiene_report_invalid' and f.severity == 'ERROR'
               for f in findings)


def test_strict_cli_blocks_invalid_hygiene_report(tmp_path, monkeypatch):
    rtl = tmp_path / 'rtl'
    rtl.mkdir()
    (rtl / 'logic.sv').write_text('module logic_unit; endmodule\n')
    def malformed_report(program, args, output):
        output.write_text('null' if program == 'rtl_hygiene_lint.py' else '{}')
        return 0, '', ''
    monkeypatch.setattr(aggregate, '_run_program_json', malformed_report)
    report = tmp_path / 'report.json'
    monkeypatch.setattr(sys, 'argv', ['rtl_review_aggregate', '--rtl-dir',
        str(rtl), '--out-json', str(report), '--strict'])
    assert aggregate._cli() == 1
    assert json.loads(report.read_text())['verdict'] == 'FAIL'


@pytest.mark.parametrize('wrapped', [False, True])
def test_reset_array_or_envelope_preserves_severity(tmp_path, wrapped):
    records = [dict(rule='flop_no_reset', severity='WARN', file='slice.sv',
                    line=3, symbol='q', message='reset absent')]
    path = tmp_path / 'reset.json'
    path.write_text(json.dumps({'findings': records} if wrapped else records))
    findings = aggregate._load_reset_findings(path)
    assert [(f.rule_id, f.severity, f.category) for f in findings] == [
        ('flop_no_reset', 'WARN', 'reset_clock_hygiene')]


def test_precheck_array_preserves_failed_and_unmeasured_results(tmp_path):
    path = tmp_path / 'precheck.json'
    path.write_text(json.dumps({'auditors': [
        dict(name='valid_logic', passed=True, exit_code=0),
        dict(name='invalid_logic', passed=False, exit_code=1, stdout_tail='bad driver'),
        dict(name='optional_check', passed=True, exit_code=0, skipped=True,
             skip_reason='missing optional contract')]}))
    findings = aggregate._load_precheck_findings(path)
    assert [(f.rule_id, f.severity) for f in findings] == [
        ('invalid_logic', 'ERROR'), ('optional_check_not_measured', 'INFO')]
    assert 'bad driver' in findings[0].message
    assert 'NOT_MEASURED' in findings[1].message
    assert aggregate.aggregate(findings).verdict == 'FAIL'


def test_precheck_legacy_mapping_remains_readable(tmp_path):
    """RETIRED REQUIREMENT, REPLACED BY THE MEASURED ONE — see the decision doc.

    PR #2039 asserted here that `{"auditors": {name: {"findings": [...]}}}`
    is read back as its nested findings, under the heading "historical valid
    envelopes remain readable". MEASURED, this envelope has never existed:

      * `rtl_precheck_gate.py` appears in 4 commits reachable from `--all`, and
        in every one of them the emission line is byte-identical:
        `"auditors": [r.as_dict() for r in results]` — a LIST, never a mapping;
      * `AuditorResult` has never carried a `findings` field in any of those
        commits (the only `findings` token in that file sits inside a docstring
        describing the FPGA burn tool's own error payload, not the report);
      * the only other reader of the key in this tree, the DE10-Lite driver,
        iterates it as a list.

    So "remains readable" was a requirement about a producer that does not and
    did not exist. Implementing it would also make the dict envelope ambiguous:
    the landed consumer already accepts `{name: AuditorResult-fields}` (pinned
    by `test_precheck_object_envelope_is_also_accepted`), and a value carrying
    BOTH `passed` and `findings` would then have two readings.

    The requirement is retired. The node ID is kept and this is what replaces
    it, because the property that actually matters survives either way: an
    envelope whose values are not auditor results is named as untrustworthy
    evidence and can never be read as a clean review.
    """
    path = tmp_path / 'precheck.json'
    path.write_text(json.dumps({'auditors': {'port_check': {'findings': [
        dict(rule='missing_port', severity='ERROR', message='missing output')]}}}))
    findings = aggregate._load_precheck_findings(path)
    assert [(f.rule_id, f.severity) for f in findings] == [
        ('precheck_report_invalid', 'ERROR')]
    assert 'port_check' not in [f.rule_id for f in findings]
    assert aggregate.aggregate(findings).verdict == 'FAIL'


@pytest.mark.parametrize('content', ['null', '{}', '{"auditors":null}',
                                    '{"auditors":[{}]}', '{"auditors":[]}'])
def test_invalid_precheck_is_not_clean(tmp_path, content):
    path = tmp_path / 'precheck.json'
    path.write_text(content)
    assert aggregate.aggregate(aggregate._load_precheck_findings(path)).verdict == 'FAIL'
