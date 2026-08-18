#!/usr/bin/env python3
"""Tests for _analog_a_check_common.py — shared A1-A8 gate helpers.

Pins the real shared logic the analog presence/substance gates rely on:
  * load_block_list parses the canonical
    phase3/analog/analog_block_list.json into a list of block names,
    tolerating string-list / list-of-dicts / bare-list / missing /
    garbage forms.
  * select_blocks honours the --block restriction.
  * The report emitters return the runner's exit-code contract:
    VACUOUS_PASS=0, PASS=0, FAIL=1, WAIVED(artefact-missing)=2, and
    write the matching verdict JSON.

logic-pinned.
"""
from __future__ import annotations

import json

import _analog_a_check_common as c


def _block_dir(project):
    d = project / "phase3" / "analog"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── load_block_list — all input shapes ───────────────────────────────
def test_load_block_list_missing_returns_none(tmp_path):
    # No file at all -> None means "no analog work declared".
    assert c.load_block_list(tmp_path) is None


def test_load_block_list_string_list(tmp_path):
    d = _block_dir(tmp_path)
    (d / "analog_block_list.json").write_text(
        json.dumps({"blocks": ["ldo", "bandgap"]}))
    assert c.load_block_list(tmp_path) == ["ldo", "bandgap"]


def test_load_block_list_dict_entries(tmp_path):
    d = _block_dir(tmp_path)
    (d / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "ldo"}, {"block": "pll"}, {}]}))
    # dict entries resolved via name/block; empty dict skipped
    assert c.load_block_list(tmp_path) == ["ldo", "pll"]


def test_load_block_list_bare_list(tmp_path):
    d = _block_dir(tmp_path)
    (d / "analog_block_list.json").write_text(json.dumps(["a", "b"]))
    assert c.load_block_list(tmp_path) == ["a", "b"]


def test_load_block_list_garbage_json_returns_empty(tmp_path):
    d = _block_dir(tmp_path)
    (d / "analog_block_list.json").write_text("{not valid json")
    # file present but unparseable -> [] (present, but no usable blocks)
    assert c.load_block_list(tmp_path) == []


def test_load_block_list_no_blocks_key_returns_empty(tmp_path):
    d = _block_dir(tmp_path)
    (d / "analog_block_list.json").write_text(json.dumps({"foo": 1}))
    assert c.load_block_list(tmp_path) == []


# ── select_blocks ────────────────────────────────────────────────────
def test_select_blocks_all_when_no_filter():
    assert c.select_blocks(["a", "b"], None) == ["a", "b"]


def test_select_blocks_filter_overrides_even_if_absent():
    # The runner may have created an out-of-list block dir on re-run.
    assert c.select_blocks(["a", "b"], "c") == ["c"]


# ── report emitters — exit-code contract ─────────────────────────────
def _args(tmp_path, block=None):
    ap = c.make_argparser("a_gate", "doc")
    argv = [str(tmp_path), "--json", str(tmp_path / "r.json")]
    if block:
        argv += ["--block", block]
    return ap.parse_args(argv)


def _verdict(tmp_path):
    return json.loads((tmp_path / "r.json").read_text())["verdict"]


def test_vacuous_pass_exit_0(tmp_path):
    rc = c.vacuous_pass("a_gate", _args(tmp_path), "no analog blocks declared")
    assert rc == 0
    assert _verdict(tmp_path) == "VACUOUS_PASS"


def test_emit_pass_exit_0(tmp_path):
    rc = c.emit_pass("a_gate", _args(tmp_path),
                     {"blocks_pass": 2, "blocks_checked": 2})
    assert rc == 0
    assert _verdict(tmp_path) == "PASS"


def test_emit_fail_exit_1(tmp_path):
    rc = c.emit_fail("a_gate", _args(tmp_path),
                     [{"block": "ldo", "rule": "STUB", "detail": "x"}],
                     {"blocks_checked": 1})
    assert rc == 1
    assert _verdict(tmp_path) == "FAIL"


def test_artefact_missing_for_block_exit_2(tmp_path):
    rc = c.artefact_missing_for_block(
        "a_gate", _args(tmp_path, block="ldo"), "ldo",
        "analog/ldo.sp", "analog-netlist-gen")
    assert rc == 2
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["verdict"] == "WAIVED"
    assert rep["suggested_skill"] == "analog-netlist-gen"


def test_write_report_noop_when_path_none(tmp_path):
    # write_report with no --json path must not raise and must not write.
    ap = c.make_argparser("a_gate", "doc")
    args = ap.parse_args([str(tmp_path)])
    c.write_report(args.json, {"x": 1})
    assert not (tmp_path / "r.json").exists()
