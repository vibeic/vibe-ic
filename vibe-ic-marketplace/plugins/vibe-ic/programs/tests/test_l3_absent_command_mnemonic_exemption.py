#!/usr/bin/env python3
"""Limb 3 of the L3 dispatch-key gate must not FAIL on a repeated mnemonic that
denotes the ABSENCE of a command.

THE DEFECT (chip-AGNOSTIC, reproduced here on synthetic tables only).
Limb 3 requires every mnemonic in `L3.opcodes` to be distinct, because the
L3<->L15 reconciliation in `opcode_field_width_consistency_check` indexes by
lowercased mnemonic and therefore keeps only ONE row per name. That reasoning is
sound for two DISTINCT commands: one of them loses its reconciliation silently.

It is NOT sound for a hole in the command space. A register map that documents
its unassigned code points as `reserved` / `unused` / `spare` repeats that word
once per hole BY CONSTRUCTION. There is no command row to lose, so nothing is
silently dropped — and the only way to satisfy the gate is to invent a distinct
name for each hole, i.e. to fabricate a dispatch entry per hole. That is
strictly worse than the ambiguity the limb exists to prevent: it turns a
correctly-documented gap into a manufactured command.

WHAT THIS FILE ALSO PINS, and why it is here rather than in a comment.
The limb's stated justification had gone STALE under it. The docstring and the
FAIL message both said the reconciliation "silently resolves to whichever row
came LAST". The consumer indexes with `out.setdefault(name.strip().lower(), ...)`,
so the row that survives is the FIRST. `test_reconciliation_keeps_the_first_row`
below measures the real behaviour against the real shipped function, so the
sentence this gate justifies itself with cannot go stale again without a red test.

DIRECTION OF RISK. This change RELAXES a limb, so the danger is UNDER-firing.
The negative set is therefore built from tables sitting just OUTSIDE the
exemption which must still FAIL, and every one of them was also run against the
pre-fix gate to prove the relaxation is the only thing that moved.

All fixtures are SYNTHESIZED neutral data — invented mnemonics and invented
opcode values on an invented protocol. No design, PDK, vendor or part number
appears, and no real command table is reproduced.
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
    (d / "L3_CMD_PROTOCOL.json").write_text(
        json.dumps(body, ensure_ascii=False), encoding="utf-8")


def _run(project: Path):
    out = project / "verdict.json"
    rc = mod.main([str(project), "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


def _kinds(rep):
    return {v["kind"] for v in rep["violations"]}


# ── POSITIVE: the defect. Repeated absent-command mnemonics must not FAIL ──

def test_repeated_reserved_holes_do_not_fail(tmp_path):
    """Three documented holes, three distinct dispatch keys, one word."""
    _write_l3(tmp_path, [
        {"name": "SYNTH_FETCH", "hex": "0x11"},
        {"name": "RESERVED", "hex": "0x12"},
        {"name": "RESERVED", "hex": "0x13"},
        {"name": "RESERVED", "hex": "0x14"},
    ])
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS", rep
    assert "mnemonic_collision" not in _kinds(rep), rep


def test_the_exemption_is_reported_not_hidden(tmp_path):
    """An exemption the reader cannot see is a check that never ran."""
    _write_l3(tmp_path, [
        {"name": "SYNTH_FETCH", "hex": "0x11"},
        {"name": "unused", "hex": "0x12"},
        {"name": "unused", "hex": "0x13"},
    ])
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    ex = rep.get("exempted_absent_command_mnemonics")
    assert ex, "the gate exempted a mnemonic and said nothing about it: %r" % rep
    assert ex[0]["mnemonic"] == "unused", ex
    assert len(ex[0]["entries"]) == 2, ex
    assert "unused" in rep["reason"], rep["reason"]


def test_an_indexed_hole_name_that_repeats_is_still_a_hole(tmp_path):
    """A hole word carrying an index/annotation suffix is still a hole word.

    NOTE ON WHAT THIS DOES AND DOES NOT MEASURE. The exemption is only ever
    consulted for a mnemonic that REPEATS, so a table spelling its holes
    `reserved_1` / `reserved_2` never reaches it — those are distinct strings
    and limb 3 never fires on them at all. The suffix tolerance therefore
    matters in exactly one situation: the SAME suffixed spelling appearing more
    than once, which is what this fixture builds. An earlier draft of this test
    used two DIFFERENT suffixed names and passed on the pre-fix gate as well as
    the fixed one — it could not fail, so it was not a control, and it is
    recorded here rather than quietly deleted.
    """
    for name in ("reserved_1", "reserved 2", "RESERVED(3)", "rsvd-4"):
        proj = tmp_path / ("case_" + name.replace(" ", "_")
                           .replace("(", "").replace(")", ""))
        _write_l3(proj, [
            {"name": "SYNTH_FETCH", "hex": "0x11"},
            {"name": name, "hex": "0x12"},
            {"name": name, "hex": "0x13"},
        ])
        rc, rep = _run(proj)
        assert rc == 0, (name, rep)
        assert "mnemonic_collision" not in _kinds(rep), (name, rep)
        assert rep.get("exempted_absent_command_mnemonics"), (name, rep)


# ── NEGATIVE CONTROLS: just outside the exemption, must STILL FAIL ─────────

def test_two_real_commands_sharing_a_mnemonic_still_fail(tmp_path):
    """The case limb 3 exists for. Must be untouched by the exemption."""
    _write_l3(tmp_path, [
        {"name": "SYNTH_FETCH", "hex": "0x11"},
        {"name": "SYNTH_FETCH", "hex": "0x12"},
    ])
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert "mnemonic_collision" in _kinds(rep), rep
    assert not rep.get("exempted_absent_command_mnemonics"), rep


def test_a_hole_word_used_as_a_prefix_is_not_a_hole(tmp_path):
    """`RESERVED_READ` is a real command name that merely starts with the
    hole word. Only a NUMERIC index suffix is tolerated, never an alphabetic
    one — otherwise any command whose name begins with `reserved` would be
    exempted and a genuine collision would go unreported."""
    _write_l3(tmp_path, [
        {"name": "RESERVED_READ", "hex": "0x11"},
        {"name": "RESERVED_READ", "hex": "0x12"},
    ])
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert "mnemonic_collision" in _kinds(rep), rep


def test_hole_rows_sharing_a_dispatch_key_still_fail(tmp_path):
    """The exemption is limb 3 ONLY. Two holes at the SAME code point is a
    limb-2 dispatch-key collision and must survive the relaxation."""
    _write_l3(tmp_path, [
        {"name": "SYNTH_FETCH", "hex": "0x11"},
        {"name": "reserved", "hex": "0x12"},
        {"name": "reserved", "hex": "0x12"},
    ])
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert "dispatch_key_collision" in _kinds(rep), rep


def test_a_hole_row_with_no_dispatch_key_still_fails(tmp_path):
    """Limb 1 too: being a hole does not excuse an unparseable hex."""
    _write_l3(tmp_path, [
        {"name": "SYNTH_FETCH", "hex": "0x11"},
        {"name": "reserved", "hex": None},
        {"name": "reserved", "hex": "0x13"},
    ])
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert "missing_dispatch_key" in _kinds(rep) or rep["violations"], rep


def test_a_single_hole_row_is_not_reported_as_exempt(tmp_path):
    """No repetition, nothing to exempt. The exemption list must stay empty
    rather than growing an entry for every hole in every design."""
    _write_l3(tmp_path, [
        {"name": "SYNTH_FETCH", "hex": "0x11"},
        {"name": "reserved", "hex": "0x12"},
    ])
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep.get("exempted_absent_command_mnemonics") == [], rep


# ── the sibling fact this limb justifies itself with ──────────────────────

def test_reconciliation_keeps_the_first_row(tmp_path):
    """Measured against the REAL shipped consumer, not asserted from a comment.

    Limb 3's whole reason for existing is what the reconciliation does with a
    repeated mnemonic. Pin it here so the justification cannot go stale again.
    """
    import importlib.util as _iu
    p = _HERE.parent / "opcode_field_width_consistency_check.py"
    s = _iu.spec_from_file_location("opcode_field_width_consistency_check", p)
    ofw = _iu.module_from_spec(s)
    s.loader.exec_module(ofw)

    idx = ofw._l3_name_hex({"opcodes": [
        {"name": "synth_alpha", "hex": "0x11"},
        {"name": "synth_hole", "hex": "0x22"},
        {"name": "synth_hole", "hex": "0x33"},
        {"name": "synth_hole", "hex": "0x44"},
    ]})
    # `setdefault` => the FIRST row survives. If this ever becomes 0x44 the
    # gate's docstring and FAIL message must be updated with it.
    assert idx["synth_hole"] == (0x22, "0x22"), idx
    assert len(idx) == 2, idx
