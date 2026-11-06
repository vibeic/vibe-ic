"""Focused reverse controls for the LAND6-D receipt/parser repairs."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import rtl_hygiene_lint as hygiene  # noqa: E402
import skill_compliance_check as compliance  # noqa: E402




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
