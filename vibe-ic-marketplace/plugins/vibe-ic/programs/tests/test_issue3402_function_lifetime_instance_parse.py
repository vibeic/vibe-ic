"""Regression for #3402: function lifetimes are not module types."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import interface_encoding_audit as audit


@pytest.mark.parametrize("lifetime", ["", "automatic ", "static "])
def test_function_lifetime_does_not_create_an_instance(lifetime):
    body = (f"function {lifetime}equal_bits(input logic [2:0] value);\n"
            "  equal_bits = &value;\nendfunction\n"
            "assign z = equal_bits(value);\n")
    audit._DISCOVERY_ISSUES.clear()
    assert audit.parse_instances(body, "top") == []
    assert audit._DISCOVERY_ISSUES == []


def test_named_child_remains_supported():
    audit._DISCOVERY_ISSUES.clear()
    rows = audit.parse_instances("leaf u_leaf(.a(a), .z(z));", "top")
    assert [(row.module_type, row.inst_name) for row in rows] == [("leaf", "u_leaf")]
    assert audit._DISCOVERY_ISSUES == []


def test_true_positional_child_remains_refused():
    audit._DISCOVERY_ISSUES.clear()
    rows = audit.parse_instances("leaf u_leaf(a, z);", "top")
    assert [(row.module_type, row.inst_name) for row in rows] == [("leaf", "u_leaf")]
    assert audit._DISCOVERY_ISSUES == ["positional instance connections in top.u_leaf"]
