#!/usr/bin/env python3
"""Tests for _facts_yaml.py — Wave 42 shared YAML reader.

Import-only helper module (no CLI).  Tests directly invoke the public
API:
  - read_facts_yaml(project_dir)  on missing / empty / malformed / normal YAML
  - get_top_level_bool(facts, key, default)  on comment-only / nested /
    true / false / non-bool inputs (Wave 42 attack vectors that the
    helper is meant to defeat).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Inject programs/ into sys.path so we can `import _facts_yaml`.
_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import _facts_yaml  # noqa: E402


# -- read_facts_yaml ---------------------------------------------------

def test_read_facts_yaml_missing_file(tmp_path):
    """Missing facts.yaml → empty dict (never raises)."""
    out = _facts_yaml.read_facts_yaml(tmp_path)
    assert out == {}
    assert isinstance(out, dict)


def test_read_facts_yaml_empty_file(tmp_path):
    """Empty file → empty dict (yaml.safe_load returns None)."""
    (tmp_path / "facts.yaml").write_text("")
    out = _facts_yaml.read_facts_yaml(tmp_path)
    assert out == {}


def test_read_facts_yaml_malformed(tmp_path):
    """Malformed YAML → empty dict (fail-closed, never raises)."""
    (tmp_path / "facts.yaml").write_text(
        "key: value\n  bad: indentation: foo: bar\n: : :\n"
    )
    out = _facts_yaml.read_facts_yaml(tmp_path)
    # Could be empty (parse fail) — must be a dict.
    assert isinstance(out, dict)


def test_read_facts_yaml_normal(tmp_path):
    """Normal YAML → mapping of top-level keys."""
    (tmp_path / "facts.yaml").write_text(
        "ic_name: TEST_IC\nno_fsm: true\nclock_mhz: 50\n"
    )
    out = _facts_yaml.read_facts_yaml(tmp_path)
    assert out["ic_name"] == "TEST_IC"
    assert out["no_fsm"] is True
    assert out["clock_mhz"] == 50


def test_read_facts_yaml_root_not_a_mapping(tmp_path):
    """When the YAML root is a list / scalar → empty dict."""
    (tmp_path / "facts.yaml").write_text("- item1\n- item2\n")
    out = _facts_yaml.read_facts_yaml(tmp_path)
    assert out == {}


# -- get_top_level_bool: Wave 42 attack vectors ------------------------

def test_get_top_level_bool_comment_only(tmp_path):
    """`# no_fsm: true` is a comment — must NOT be treated as set."""
    (tmp_path / "facts.yaml").write_text(
        "# no_fsm: true\nic_name: TEST\n"
    )
    facts = _facts_yaml.read_facts_yaml(tmp_path)
    assert _facts_yaml.get_top_level_bool(facts, "no_fsm") is False


def test_get_top_level_bool_nested(tmp_path):
    """Nested `metadata.no_fsm: true` is NOT top level → returns
    default (False)."""
    (tmp_path / "facts.yaml").write_text(
        "metadata:\n  no_fsm: true\n"
    )
    facts = _facts_yaml.read_facts_yaml(tmp_path)
    assert _facts_yaml.get_top_level_bool(facts, "no_fsm") is False


def test_get_top_level_bool_true(tmp_path):
    """Top-level true → True."""
    (tmp_path / "facts.yaml").write_text("no_fsm: true\n")
    facts = _facts_yaml.read_facts_yaml(tmp_path)
    assert _facts_yaml.get_top_level_bool(facts, "no_fsm") is True


def test_get_top_level_bool_false(tmp_path):
    """Top-level false → False."""
    (tmp_path / "facts.yaml").write_text("no_fsm: false\n")
    facts = _facts_yaml.read_facts_yaml(tmp_path)
    assert _facts_yaml.get_top_level_bool(facts, "no_fsm") is False


def test_get_top_level_bool_string_true_is_not_a_bool(tmp_path):
    """`no_fsm: "true"` (string) must NOT count — Wave 42 attack."""
    (tmp_path / "facts.yaml").write_text('no_fsm: "true"\n')
    facts = _facts_yaml.read_facts_yaml(tmp_path)
    assert _facts_yaml.get_top_level_bool(facts, "no_fsm") is False


def test_get_top_level_bool_int_is_not_a_bool(tmp_path):
    """`no_fsm: 1` (int) must NOT count under strict bool helper."""
    (tmp_path / "facts.yaml").write_text("no_fsm: 1\n")
    facts = _facts_yaml.read_facts_yaml(tmp_path)
    assert _facts_yaml.get_top_level_bool(facts, "no_fsm") is False


def test_get_top_level_bool_default(tmp_path):
    """Missing key returns default."""
    facts = {"unrelated": True}
    assert _facts_yaml.get_top_level_bool(facts, "no_fsm") is False
    assert _facts_yaml.get_top_level_bool(facts, "no_fsm", True) is True


def test_get_top_level_bool_non_dict_input():
    """Non-dict facts → default."""
    assert _facts_yaml.get_top_level_bool(None, "key", True) is True
    assert _facts_yaml.get_top_level_bool([], "key", False) is False
    assert _facts_yaml.get_top_level_bool("string", "key") is False


# -- get_top_level_truthy ----------------------------------------------

def test_get_top_level_truthy_string_true(tmp_path):
    """Truthy helper accepts the canonical truthy string spellings."""
    (tmp_path / "facts.yaml").write_text('no_fsm: "true"\n')
    facts = _facts_yaml.read_facts_yaml(tmp_path)
    assert _facts_yaml.get_top_level_truthy(facts, "no_fsm") is True


def test_get_top_level_truthy_yes_on_1():
    facts = {"a": "yes", "b": "on", "c": "1", "d": "no", "e": ""}
    assert _facts_yaml.get_top_level_truthy(facts, "a") is True
    assert _facts_yaml.get_top_level_truthy(facts, "b") is True
    assert _facts_yaml.get_top_level_truthy(facts, "c") is True
    assert _facts_yaml.get_top_level_truthy(facts, "d") is False
    assert _facts_yaml.get_top_level_truthy(facts, "e") is False


def test_get_top_level_truthy_int():
    """Numeric > 0 → truthy.  Bool already handled separately."""
    facts = {"x": 5, "y": 0}
    assert _facts_yaml.get_top_level_truthy(facts, "x") is True
    assert _facts_yaml.get_top_level_truthy(facts, "y") is False


# -- get_top_level (raw) -----------------------------------------------

def test_get_top_level_raw():
    facts = {"x": [1, 2], "y": "hello", "z": {"k": "v"}}
    assert _facts_yaml.get_top_level(facts, "x") == [1, 2]
    assert _facts_yaml.get_top_level(facts, "y") == "hello"
    assert _facts_yaml.get_top_level(facts, "z") == {"k": "v"}
    assert _facts_yaml.get_top_level(facts, "missing") is None
    assert _facts_yaml.get_top_level(facts, "missing", "default") == \
        "default"
