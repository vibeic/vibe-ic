#!/usr/bin/env python3
"""Tests for _analog_stub_marker.py — deterministic-stub recognition.

The analog one-shot runner tags minimal-substance artefacts with a
structural marker so downstream substance gates can downgrade
`passed=False` to a PASS_WITH_STUB tier instead of a hard FAIL. These
helpers are the predicates that detect that marker.

logic-pinned: each test exercises a real branch (text first-16-lines
window, JSON key/val match, path .json-vs-other dispatch, missing /
unparseable file -> False).
"""
from __future__ import annotations

import json

import _analog_stub_marker as m


# ── is_stub_text ─────────────────────────────────────────────────────
def test_stub_text_marker_in_head():
    assert m.is_stub_text(
        "* header\nfoo extraction_strategy=deterministic_stub bar")


def test_real_text_not_stub():
    assert m.is_stub_text("* header\nM1 vdd net1 net2 nmos w=1u") is False


def test_stub_text_none_is_false():
    assert m.is_stub_text(None) is False
    assert m.is_stub_text("") is False


def test_stub_marker_past_16th_line_not_detected():
    # The contract scans only the first 16 lines.
    body = "\n".join(["x"] * 20 + ["extraction_strategy=deterministic_stub"])
    assert m.is_stub_text(body) is False


# ── is_stub_json ─────────────────────────────────────────────────────
def test_stub_json_match():
    assert m.is_stub_json(
        {"extraction_strategy": "deterministic_stub", "blocks": []})


def test_real_json_not_stub():
    assert m.is_stub_json({"extraction_strategy": "real"}) is False


def test_non_dict_json_is_false():
    assert m.is_stub_json(["not", "a", "dict"]) is False
    assert m.is_stub_json(None) is False


# ── is_stub_path ─────────────────────────────────────────────────────
def test_stub_path_json_dispatch(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"extraction_strategy": "deterministic_stub"}))
    assert m.is_stub_path(p) is True


def test_stub_path_text_dispatch(tmp_path):
    p = tmp_path / "a.sp"
    p.write_text("* netlist\nextraction_strategy=deterministic_stub")
    assert m.is_stub_path(p) is True


def test_real_path_not_stub(tmp_path):
    p = tmp_path / "r.sp"
    p.write_text("* real netlist\nM1 vdd a b nmos")
    assert m.is_stub_path(p) is False


def test_missing_path_is_false(tmp_path):
    assert m.is_stub_path(tmp_path / "does_not_exist.json") is False


def test_unparseable_json_path_is_false(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    assert m.is_stub_path(p) is False
