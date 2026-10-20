"""Focused reverse controls for the LAND6-D receipt/parser repairs."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import _rtl_audit_applicability as applicability  # noqa: E402
import _interface_encoding_population as encoding_population  # noqa: E402
import interface_encoding_audit as interface_audit  # noqa: E402
import rtl_hygiene_lint as hygiene  # noqa: E402
import skill_compliance_check as compliance  # noqa: E402


def _interface_report(rtl: Path, *, status="MATCH", verdict="PASS",
                      producer_rc=0, discovery_complete=True):
    source = applicability.source_census(rtl)
    mismatch = int(status == "MISMATCH")
    unknown = int(status == "UNKNOWN")
    payload = {
        "report_schema": "vibeic.interface_encoding_audit.v2",
        "producer_returncode": producer_rc,
        "summary": {"total_interfaces": 1, "mismatches": mismatch,
                    "matches": int(status == "MATCH"), "unknowns": unknown,
                    "top_module": "top", "rtl_dir": str(rtl),
                    "verdict": verdict},
        "interfaces": [{"wire_name": "bus", "status": status}],
        "discovery": {"complete": discovery_complete,
                      "issues": [] if discovery_complete else ["incomplete"]},
        "source": source,
    }
    payload['interface_population'] = encoding_population.binding(
        payload['interfaces'])
    return payload


def _consume(tmp_path, payload, rtl):
    tmp_path.mkdir(parents=True, exist_ok=True)
    evidence = tmp_path / "evidence"
    evidence.mkdir(exist_ok=True)
    (evidence / "encoding_audit_report.json").write_text(json.dumps(payload))
    review = tmp_path / "review.md"
    review.write_text("review")
    spec = {"id": "X_probe", "auditor": "interface_encoding_audit",
            "receipt_dir": str(evidence)}
    return compliance._cc_audit_receipt_evidence(
        spec, review.read_text(), compliance.CheckContext(
            output_path=review, rtl_source_root=rtl))


def test_consumer_rc2_inconclusive_and_unknown_are_not_measured(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.sv").write_text("module top; endmodule\n")
    for payload in (
            _interface_report(rtl, verdict="INCONCLUSIVE", producer_rc=2,
                              discovery_complete=False),
            _interface_report(rtl, status="UNKNOWN", producer_rc=0),):
        findings = _consume(tmp_path / f"case{len(list(tmp_path.iterdir()))}",
                            payload, rtl)
        assert findings[0].state == compliance.STATE_NOT_MEASURED


def test_measured_failure_has_precedence_over_stale_source(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    source = rtl / "top.sv"
    source.write_text("module top; endmodule\n")
    payload = _interface_report(rtl, status="MISMATCH", verdict="FAIL",
                                producer_rc=1)
    source.write_text("module top; wire changed; endmodule\n")
    findings = _consume(tmp_path, payload, rtl)
    assert findings[0].state == compliance.STATE_FAIL


def test_clean_receipt_with_stale_source_is_not_measured(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    source = rtl / "top.sv"
    source.write_text("module top; endmodule\n")
    payload = _interface_report(rtl)
    source.write_text("module top; wire changed; endmodule\n")
    findings = _consume(tmp_path, payload, rtl)
    assert findings[0].state == compliance.STATE_NOT_MEASURED


def test_fixture_label_cannot_bypass_evidence_contract(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.sv").write_text("module top; endmodule\n")
    payload = _interface_report(rtl, producer_rc=2, discovery_complete=False)
    payload['_fixture'] = 'SYNTHETIC'
    assert _consume(tmp_path, payload, rtl)[0].state == compliance.STATE_NOT_MEASURED


@pytest.mark.parametrize('mutation', ['rc2', 'inconclusive', 'discovery', 'unknown',
                                     'added_source', 'deleted_source', 'digest'])
def test_complete_receipt_passes_and_each_bad_evidence_arm_refuses(tmp_path, mutation):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    source = rtl / "top.sv"
    source.write_text("module top; endmodule\n")
    payload = _interface_report(rtl)
    assert _consume(tmp_path / 'before', payload, rtl)[0].state == compliance.STATE_PASS
    if mutation == 'rc2':
        payload['producer_returncode'] = 2
    elif mutation == 'inconclusive':
        payload['summary']['verdict'] = 'INCONCLUSIVE'
    elif mutation == 'discovery':
        payload['discovery']['complete'] = False
    elif mutation == 'unknown':
        payload['summary'].update(matches=0, unknowns=1)
        payload['interfaces'][0]['status'] = 'UNKNOWN'
    elif mutation == 'added_source':
        (rtl / 'added.sv').write_text('module added; endmodule\n')
    elif mutation == 'deleted_source':
        source.unlink()
    else:
        payload['source']['sha256'] = '0' * 64
    assert _consume(tmp_path / 'after', payload, rtl)[0].state == compliance.STATE_NOT_MEASURED


def test_measured_failure_has_precedence_over_incomplete_discovery(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.sv").write_text("module top; endmodule\n")
    payload = _interface_report(rtl, status="MISMATCH", verdict="INCONCLUSIVE",
                                producer_rc=2, discovery_complete=False)
    assert _consume(tmp_path, payload, rtl)[0].state == compliance.STATE_FAIL


def test_string_endmodule_does_not_truncate_module_population(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "design.sv").write_text(
        'module producer(input clk, output reg [5:0] count);\n'
        'initial $display("fake endmodule;");\n'
        'always @(posedge clk) count <= count + 1; endmodule\n'
        'module consumer(input [5:0] count, output valid);\n'
        "assign valid = count == 6'b11_0000; endmodule\n"
        'module top(input clk, output valid); wire [5:0] bus;\n'
        'producer p(.clk(clk), .count(bus)); consumer c(.count(bus), .valid(valid));\n'
        'endmodule\n')
    results = interface_audit.run_audit(str(rtl), "top")
    assert any(row.status == "MISMATCH" for row in results)


def test_nonansi_and_attribute_ports_keep_directions(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "design.sv").write_text(
        'module producer(clk, count); input clk; output reg [5:0] count;\n'
        'always @(posedge clk) count <= count + 1; endmodule\n'
        'module consumer(count, valid); input [5:0] count; '
        '(* keep = "true" *) output valid; '
        "assign valid = count == 6'b11_0000; endmodule\n"
        'module top(clk, valid); input clk; output valid; wire [5:0] x;\n'
        'producer p(.clk(clk), .count(x)); consumer c(.count(x), .valid(valid)); '
        'endmodule\n')
    results = interface_audit.run_audit(str(rtl), "top")
    assert any(row.status == "MISMATCH" for row in results)


def test_duplicate_named_output_binding_does_not_credit_actuals():
    source = ('module leaf(input a, output b); assign b=a; endmodule\n'
              'module top(input a, output y); wire r1; wire r2; '
              'leaf u(.a(a), .b(r1), .b(r2)); assign y=r1; endmodule\n')
    findings = hygiene.rule_undriven_and_unread(
        hygiene.strip_comments(source), "duplicate.sv")
    assert sorted(f.symbol for f in findings if f.rule == "undriven-wire") == ["r1", "r2"]


@pytest.mark.parametrize('binding', ['.a(a), .b(r1), .b(r2)',
                                    'a, .b(r1)', '.a(a), .b(r1)(r2)'])
def test_duplicate_mixed_and_malformed_instances_have_zero_driver_credit(binding):
    source = ('module leaf(input a, output b); assign b=a; endmodule\n'
              'module top(input a, output y); wire r1; wire r2; '
              f'leaf u({binding}); assign y=r1; endmodule\n')
    assert hygiene.collect_instance_connections(source) == {}


def test_ansi_attribute_output_keeps_mismatch_population(tmp_path):
    rtl = tmp_path / 'rtl'
    rtl.mkdir()
    (rtl / 'design.sv').write_text(
        'module producer(input clk, (* keep = "true" *) output reg [5:0] count); '
        'always @(posedge clk) count <= count + 1; endmodule\n'
        'module consumer(input [5:0] count, output valid); '
        "assign valid = count == 6'b11_0000; endmodule\n"
        'module top(input clk, output valid); wire [5:0] bus; '
        'producer p(.clk(clk), .count(bus)); '
        'consumer c(.count(bus), .valid(valid)); endmodule\n')
    assert any(row.status == 'MISMATCH'
               for row in interface_audit.run_audit(str(rtl), 'top'))


@pytest.mark.parametrize('property_name', ['consumer', 'stale', 'string',
                                          'nonansi', 'attribute', 'duplicate'])
def test_reverse_mutations_make_each_property_control_red(tmp_path, monkeypatch,
                                                         property_name):
    """Reintroduce each rejected mechanism and demand its positive test fail."""
    if property_name == 'consumer':
        def zero_mismatches_pass(spec, text, ctx=None):
            return [compliance.Finding(spec['id'], 'INFO', 'mutant zero mismatches',
                                       state=compliance.STATE_PASS)]
        monkeypatch.setattr(compliance, '_cc_audit_receipt_evidence', zero_mismatches_pass)
        control = test_consumer_rc2_inconclusive_and_unknown_are_not_measured
    elif property_name == 'stale':
        census = applicability.source_census
        cached = []
        def no_freshness_remeasurement(root, **kwargs):
            if not cached:
                cached.append(census(root, **kwargs))
            return cached[0]
        monkeypatch.setattr(applicability, 'source_census', no_freshness_remeasurement)
        control = test_clean_receipt_with_stale_source_is_not_measured
    elif property_name == 'string':
        def raw_module_regions(src, issues=None):
            for match in re.finditer(r'\bmodule\s+(\w+)[^;]*;', src):
                end = re.search(r'\bendmodule\b', src[match.end():])
                if end:
                    yield match.group(1), match.start(), match.end(), match.end() + end.start()
        monkeypatch.setattr(interface_audit, 'module_regions', raw_module_regions)
        monkeypatch.setattr(interface_audit, 'lexical_mask', lambda src, **kwargs: src)
        monkeypatch.setitem(interface_audit.parse_non_ansi_ports.__globals__,
                            'lexical_mask', lambda src, **kwargs: src)
        control = test_string_endmodule_does_not_truncate_module_population
    elif property_name == 'nonansi':
        monkeypatch.setattr(interface_audit, 'parse_non_ansi_ports', lambda *args: {})
        control = test_nonansi_and_attribute_ports_keep_directions
    elif property_name == 'attribute':
        monkeypatch.setattr(interface_audit, 'lexical_mask', lambda src, **kwargs: src)
        monkeypatch.setitem(interface_audit.parse_port_list_ansi.__globals__,
                            'mask_attributes_only', lambda src: src)
        control = test_ansi_attribute_output_keeps_mismatch_population
    else:
        def bare_named_driver_regex(src, uncertain=None):
            return {match.group(2): match.group(1) for match in re.finditer(
                r'\.(\w+)\s*\(\s*(\w+)\s*\)', src)}
        monkeypatch.setattr(hygiene, 'collect_instance_connections', bare_named_driver_regex)
        with pytest.raises(AssertionError):
            test_duplicate_named_output_binding_does_not_credit_actuals()
        return
    with pytest.raises(AssertionError):
        control(tmp_path)
