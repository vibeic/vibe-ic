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


#: PR #2039 parametrized ONE test over ten inputs, and the ten do not ask one
#: question. Three are a RECORD inside a readable array that is not a usable
#: finding; seven are the array itself being absent, unparseable, or a shape
#: this consumer does not understand. v1.17.43 already ruled on the second
#: group -- it RAISES and the CLI exits 3 writing nothing -- and pinned that in
#: `test_rtl_review_aggregate.py::TestUnreadableIsNotEmpty`. Rebasing onto that
#: tree means the two groups separate here, and each is asserted where it
#: belongs. Neither group loses an input.
_MALFORMED_RECORDS = ['[{"severity":"surprise"}]', '[{}]',
    '[{"rule":"x","file":"logic.sv","line":1,"message":"absent severity"}]']

#: The seven PR #2039 asserted must come back as a named ERROR record and which
#: the landed contract REFUSES instead. THIS IS AN OPEN DISAGREEMENT, not a
#: settled one: PR #2039 is still open and still asserts the opposite for these
#: exact inputs. See docs/decisions/2026-09-06-rtl-review-producer-json.md § 1.
_NO_EVIDENCE_AT_ALL = [None, 'broken json', '{}', 'null', '7',
                       '{"findings":{}}', '[null]']


@pytest.mark.parametrize('content', _MALFORMED_RECORDS)
def test_unreadable_or_invalid_report_is_not_clean(tmp_path, content):
    path = tmp_path / 'hygiene.json'
    if content is not None:
        path.write_text(content)
    findings = aggregate._load_hygiene_findings(path)
    report = aggregate.aggregate(findings)
    assert report.verdict == 'FAIL'
    assert any(f.rule_id == 'hygiene_report_invalid' and f.severity == 'ERROR'
               for f in findings)


@pytest.mark.parametrize('content', _NO_EVIDENCE_AT_ALL)
def test_unreadable_hygiene_report_refuses_instead_of_reporting(tmp_path, content):
    """The landed contract for evidence that never arrived, on PR #2039's inputs.

    These seven literals are PR #2039's, and none of them is covered by
    `TestUnreadableIsNotEmpty`, which uses different ones (`{not json`,
    `{"summary": "all good"}`, `["blocking_in_seq"]`) and does not exercise a
    bare `null`, a bare `7` or `{"findings": {}}` at all. So the inputs the PR
    contributed keep testing something after the rebase.

    What they assert is the LANDED claim: nothing readable arrived, so there is
    no report to put a record into, and a scored FAIL report over evidence that
    never came is a measured number about an unmeasured thing. The CLI exits 3
    and writes neither artifact.

    PR #2039 asserts the OPPOSITE for these same inputs -- a named ERROR record
    inside an emitted FAIL report. That is a live contract question and it is
    the owner's, not this lane's: reversing it here would have reddened three
    landed node IDs. Reverse this test and `_load_hygiene_findings` together if
    it is ruled the PR's way.
    """
    path = tmp_path / 'hygiene.json'
    if content is not None:
        path.write_text(content)
    with pytest.raises(aggregate.ProducerOutputError) as exc:
        aggregate._load_hygiene_findings(path)
    assert 'rtl_hygiene_lint' in str(exc.value)


def test_strict_cli_refuses_an_unreadable_hygiene_report(tmp_path, monkeypatch):
    """PR #2039's CLI case, driven to the landed contract's answer.

    The PR asserted exit 1 with a FAIL report written. The landed contract says
    a producer whose output cannot be read yields NO report at all and exit 3 --
    a code distinct from 1 (reviewed, verdict not PASS) and 2 (usage) precisely
    so nothing downstream can mistake a refusal for a score. Same stimulus, same
    monkeypatched producer; the expectation follows §1 of the decision doc.

    `--strict` is passed and is deliberately NOT what decides this: a refusal
    outranks the strict/advisory choice, so the exit code is 3 either way.
    """
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
    assert aggregate._cli() == 3
    assert not report.exists(), 'a refusal must write no report to be quoted'


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
    # THE ONE STRING THIS LANE COULD NOT SETTLE. PR #2039 names a skipped
    # auditor's record `<name>_not_measured`; v1.17.43 landed and pinned the
    # bare auditor NAME (`TestProducerArraySchema::test_precheck_real_auditor_
    # list_shape` asserts `set(by_rule) == {...,"reset_discipline_check"}`).
    # Greening either reddens the other, 1-for-1, and it is red under BOTH of
    # the two candidate contract lines, so it is a separate ruling. The landed
    # name is used here because a rebase conforms to main until told otherwise.
    assert [(f.rule_id, f.severity) for f in findings] == [
        ('invalid_logic', 'ERROR'), ('optional_check', 'INFO')]
    assert 'bad driver' in findings[0].message
    # both vocabularies survive in the message, which is where they cost nothing
    assert 'NOT_MEASURED' in findings[1].message
    assert 'did not run' in findings[1].message
    assert aggregate.aggregate(findings).verdict == 'FAIL'
    # RULING F2036-H: it is an absence, so it is not counted, and it is named
    assert [a['auditor'] for a in
            aggregate.aggregate(findings).auditors_not_run] == ['optional_check']


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


#: Readable report, untrustworthy CONTENT -> a named ERROR record. `[{}]` is an
#: auditor entry that is not a result; `[]` is the purest form of #2036 --
#: nothing ran at all, and it used to score 10/10 PASS.
@pytest.mark.parametrize('content', ['{"auditors":[{}]}', '{"auditors":[]}'])
def test_invalid_precheck_is_not_clean(tmp_path, content):
    path = tmp_path / 'precheck.json'
    path.write_text(content)
    assert aggregate.aggregate(aggregate._load_precheck_findings(path)).verdict == 'FAIL'


@pytest.mark.parametrize('content', ['null', '{}', '{"auditors":null}'])
def test_unreadable_precheck_report_refuses_instead_of_reporting(tmp_path, content):
    """Same split as the hygiene loader, on PR #2039's precheck inputs.

    None of these three is an `auditors` collection at all, so there is no
    execution list to report about; `TestUnreadableIsNotEmpty::
    test_reset_and_precheck_refuse_too` already pins that class with a
    different literal (`{"summary": {}}`). PR #2039 asserts a named ERROR record
    here instead; that is the same open contract question as the hygiene half
    and it is reversed together with it, or not at all.
    """
    path = tmp_path / 'precheck.json'
    path.write_text(content)
    with pytest.raises(aggregate.ProducerOutputError) as exc:
        aggregate._load_precheck_findings(path)
    assert 'rtl_precheck_gate' in str(exc.value)
