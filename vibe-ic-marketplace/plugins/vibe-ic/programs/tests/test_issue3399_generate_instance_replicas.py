"""Regression for #3399: one source generate template may own N native replicas."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import interface_encoding_audit as audit


def instance(name: str = "u_leaf") -> audit.InstanceInfo:
    return audit.InstanceInfo(
        inst_name=name, module_type="leaf", parent_module="top",
        connections={"a": "a", "z": "z"},
        connection_expressions={"a": "a[i]", "z": "z[i]"})


def bind(source_instances, children):
    audit._CONFIGURATION.clear()
    return audit._bind_native_instances(source_instances, children, "top")


def test_one_template_expands_to_every_native_replica():
    children = {
        "lane[0].u_leaf": "leaf$top.lane[0].u_leaf",
        "lane[1].u_leaf": "leaf$top.lane[1].u_leaf",
        "lane[2].u_leaf": "leaf$top.lane[2].u_leaf",
    }
    rows = bind([instance()], children)
    assert [row.inst_name for row in rows] == sorted(children)
    assert [row.module_type for row in rows] == [children[name] for name in sorted(children)]
    assert len({id(row.connections) for row in rows}) == 3


def test_one_to_one_instance_keeps_exact_native_identity():
    rows = bind([instance()], {"u_leaf": "leaf"})
    assert [(row.inst_name, row.module_type) for row in rows] == [("u_leaf", "leaf")]


def test_duplicate_source_templates_remain_ambiguous():
    children = {"left.u_leaf": "leaf$left", "right.u_leaf": "leaf$right"}
    with pytest.raises(ValueError, match="^unsupported source/native instance"):
        bind([instance(), instance()], children)


def test_unmatched_native_child_remains_incomplete():
    children = {"u_leaf": "leaf", "other": "other"}
    with pytest.raises(ValueError, match="^incomplete source/native child population"):
        bind([instance()], children)


def test_missing_native_candidate_remains_refused():
    with pytest.raises(ValueError, match="^unsupported source/native instance"):
        bind([instance()], {"different": "leaf"})
