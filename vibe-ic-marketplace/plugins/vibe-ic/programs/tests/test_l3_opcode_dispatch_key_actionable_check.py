#!/usr/bin/env python3
"""Smoke tests for l3_opcode_dispatch_key_actionable_check.py.

NEGATIVE CONTROL IS THE POINT OF THIS FILE. Every behaviour is asserted
in BOTH directions: an L3 gutted of the dispatch key the consumer
actually indexes on must FAIL (rc 1), and the same table with the key
restored must PASS (rc 0). A test that cannot fail proves nothing.

All fixtures are SYNTHESIZED neutral data — invented mnemonics and
opcode values on an invented protocol. No real design's files are
copied, and no vendor command table is reproduced.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "l3_opcode_dispatch_key_actionable_check.py"

_spec = importlib.util.spec_from_file_location(
    "l3_opcode_dispatch_key_actionable_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _write_l3(project: Path, opcodes, **extra):
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    body = {"ic_name": "synth_block", "opcodes": opcodes}
    body.update(extra)
    (d / "L3_CMD_PROTOCOL.json").write_text(json.dumps(body,
                                                       ensure_ascii=False),
                                            encoding="utf-8")


def _run(project: Path):
    out = project / "verdict.json"
    rc = mod.main([str(project), "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


_GOOD = [
    {"name": "FETCH_STATUS", "hex": "0x11"},
    {"name": "LOAD_CONFIG", "hex": "0x12"},
    {"name": "START_SEQ", "hex": "0x13"},
]


# -------------------------------------------------- POSITIVE: well-formed
def test_pass_well_formed_table(tmp_path):
    _write_l3(tmp_path, _GOOD)
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    assert rep["distinct_dispatch_keys"] == 3
    assert rep["violations"] == []


# ------------------------- NEGATIVE CONTROL: dispatch key not actionable
def test_fail_gutted_null_hex(tmp_path):
    """Real name, no hex.

    l3_opcode_name_coverage_check PASSes this (every name is real) and
    opcode_field_width_consistency_check skips it (not hex-bearing).
    The consumer's `startswith("0x")` filter drops the row entirely, so
    no case arm is emitted and the DUT is silent on that command.
    """
    gutted = [dict(o) for o in _GOOD]
    gutted[1] = {"name": "LOAD_CONFIG", "hex": None}
    _write_l3(tmp_path, gutted)
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert rep["verdict"] == "FAIL"
    kinds = {v["kind"] for v in rep["violations"]}
    assert kinds == {"dispatch_key_unparseable"}
    assert rep["violations"][0]["opcode"] == "LOAD_CONFIG"


def test_fail_gutted_todo_sentinel_hex(tmp_path):
    gutted = [dict(o) for o in _GOOD]
    gutted[2] = {"name": "START_SEQ", "hex": "__TODO__"}
    _write_l3(tmp_path, gutted)
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert rep["violations"][0]["kind"] == "dispatch_key_unparseable"


def test_fail_gutted_prose_hex(tmp_path):
    gutted = [dict(o) for o in _GOOD]
    gutted[0] = {"name": "FETCH_STATUS", "hex": "see command table"}
    _write_l3(tmp_path, gutted)
    assert _run(tmp_path)[0] == 1


def test_pass_once_the_dispatch_key_is_restored(tmp_path):
    """Direction 2 of the same control."""
    _write_l3(tmp_path, _GOOD)
    assert _run(tmp_path)[0] == 0


# ------------------------------- NEGATIVE CONTROL: silent overwrite path
def test_fail_hex_collision_overwrites_in_the_consumer(tmp_path):
    """Two opcodes on one key -> `l3_by_hex[h] = op` drops the first."""
    colliding = [
        {"name": "FETCH_STATUS", "hex": "0x11"},
        {"name": "FETCH_STATUS_ALT", "hex": "0X11"},   # case differs only
        {"name": "START_SEQ", "hex": "0x13"},
    ]
    _write_l3(tmp_path, colliding)
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    v = [x for x in rep["violations"]
         if x["kind"] == "dispatch_key_collision"]
    assert len(v) == 1
    assert v[0]["hex"] == "0x11"
    assert len(v[0]["opcodes"]) == 2


def test_pass_when_the_collision_is_resolved(tmp_path):
    resolved = [
        {"name": "FETCH_STATUS", "hex": "0x11"},
        {"name": "FETCH_STATUS_ALT", "hex": "0x14"},
        {"name": "START_SEQ", "hex": "0x13"},
    ]
    _write_l3(tmp_path, resolved)
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"


def test_fail_mnemonic_collision(tmp_path):
    """Repeated mnemonic -> L3<->L15 reconciliation silently keeps one."""
    dup = [
        {"name": "LOAD_CONFIG", "hex": "0x11"},
        {"name": "load_config", "hex": "0x12"},
    ]
    _write_l3(tmp_path, dup)
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert any(v["kind"] == "mnemonic_collision" for v in rep["violations"])


# ------------------------------------------- FALSE-POSITIVE regressions
def test_vacuous_pass_on_non_protocol_ip(tmp_path):
    """26/26 real Phase-1 runs on the fleet are this case."""
    _write_l3(tmp_path, [], no_opcodes_in_input=True)
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "VACUOUS_PASS"
    assert rep["total"] == 0


def test_integer_hex_is_actionable(tmp_path):
    """A JSON integer opcode is a perfectly valid dispatch key."""
    _write_l3(tmp_path, [{"name": "READ_ID", "hex": 17},
                         {"name": "WRITE_ID", "hex": 18}])
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"


def test_reserved_mnemonic_with_a_real_hex_passes(tmp_path):
    """RESERVED is a legitimate protocol mnemonic, not a placeholder."""
    _write_l3(tmp_path, [{"name": "RESERVED", "hex": "0x00"},
                         {"name": "START_SEQ", "hex": "0x13"}])
    assert _run(tmp_path)[0] == 0


def test_alternate_key_field_is_accepted(tmp_path):
    _write_l3(tmp_path, [{"name": "READ_ID", "opcode_hex": "0x21"},
                         {"name": "WRITE_ID", "opcode_hex": "0x22"}])
    rc, rep = _run(tmp_path)
    assert rc == 0, rep


# -------------------------------------------------------------- plumbing
def test_waiver_downgrades_fail(tmp_path):
    gutted = [dict(o) for o in _GOOD]
    gutted[1] = {"name": "LOAD_CONFIG", "hex": None}
    _write_l3(tmp_path, gutted)
    (tmp_path / "waivers.json").write_text(json.dumps({
        mod.WAIVER_KEY: "LOAD_CONFIG is documented without an encoding in "
                        "this revision and is intentionally undispatched."}))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS_WITH_WAIVER"


def test_rc2_when_l3_absent(tmp_path):
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    assert _run(tmp_path)[0] == 2


def test_rc2_when_project_dir_absent(tmp_path):
    assert mod.main([str(tmp_path / "nope")]) == 2
