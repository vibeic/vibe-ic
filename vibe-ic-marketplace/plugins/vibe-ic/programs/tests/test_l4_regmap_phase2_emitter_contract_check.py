#!/usr/bin/env python3
"""Smoke tests for l4_regmap_phase2_emitter_contract_check.py.

NEGATIVE CONTROL IS THE POINT. Every requirement is asserted in BOTH
directions: a deliberately-gutted L4 must FAIL and the well-formed
sibling must PASS.

All fixtures are SYNTHESIZED neutral data — invented register names
(``reg_alpha``/``reg_beta``) and invented addresses. No real design's
files, no vendor register names, no PDK names.

Several tests additionally assert against the EMITTER'S REAL OUTPUT
(``phase2_scaffold_gen.emit_regs_v``) rather than only the gate's
verdict, so the tests prove the defect the gate claims exists actually
exists.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "l4_regmap_phase2_emitter_contract_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _mk(tmp_path: Path, l4: dict, name: str = "p") -> Path:
    proj = tmp_path / name
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L4_REGMAP.json").write_text(json.dumps(l4), encoding="utf-8")
    (gd / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "synth_part", "interface": "spi"}),
        encoding="utf-8")
    (gd / "L3_CMD_PROTOCOL.json").write_text(
        json.dumps({"opcodes": [{"name": "OP_RD", "code": "0x01"}]}),
        encoding="utf-8")
    return proj


def _good_l4() -> dict:
    return {
        "register_map_present": True,
        "no_registers_in_input": False,
        "registers": [
            {"name": "reg_alpha", "offset": "0x00", "width": 8,
             "access": "rw", "fields": []},
            {"name": "reg_beta", "offset": "0x04", "width": 8,
             "access": "ro", "fields": []},
            {"name": "reg_gamma", "address": "0x08", "width": 8,
             "access": "rw", "fields": []},
        ],
    }


def _emit(l4: dict) -> str:
    """Run the REAL emitter over this L4 and return the Verilog."""
    sys.path.insert(0, str(PROG.parent))
    import phase2_scaffold_gen as psg  # type: ignore
    regs = psg.derive_registers(psg._unwrap_fields(l4), {})
    return psg.emit_regs_v("synth_top", regs)


def _reg_decl_ids(verilog: str) -> list:
    out = []
    for line in verilog.splitlines():
        s = line.strip()
        if s.startswith("reg ") and ";" in s:
            out.append(s.split(";")[0].split()[-1])
    return out


# ---------------------------------------------------------------------------
# POSITIVE CONTROL.
# ---------------------------------------------------------------------------

def test_positive_control_wellformed_l4_passes(tmp_path):
    l4 = _good_l4()
    r = _run(_mk(tmp_path, l4))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    # And the emitter really does produce distinct declarations.
    ids = _reg_decl_ids(_emit(l4))
    assert len(ids) == len(set(ids)) == 3


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS.
# ---------------------------------------------------------------------------

def test_negative_control_duplicate_identifier_fails(tmp_path):
    """Two registers that sanitize to the same Verilog identifier make
    emit_regs_v() declare the same reg twice — uncompilable, and the
    error surfaces at lint/synth with no pointer back to L4."""
    l4 = _good_l4()
    l4["registers"][1]["name"] = "reg_alpha"      # collide with [0]
    proj = _mk(tmp_path, l4)
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NOT COMPILE" in r.stdout

    # Prove the defect is real, not just asserted by the gate.
    ids = _reg_decl_ids(_emit(l4))
    assert len(ids) != len(set(ids)), \
        "emitter should have produced a duplicate reg declaration"


def test_negative_control_address_under_unread_key_fails(tmp_path):
    """THE motivating shape: the address IS in the register's own L4
    record — under a key derive_registers() does not read. The layer
    looks populated; the emitter sees an empty offset and scaffolds no
    decode.

    ``base_address_hex`` is used here rather than ``addr_hex``: the
    latter is now READ by the emitter (see the regression test below),
    so it no longer demonstrates the defect. The gate must keep catching
    the general case, because any future extractor can invent a new key.
    """
    l4 = _good_l4()
    reg = l4["registers"][0]
    reg.pop("offset")
    reg["base_address_hex"] = "0x00"              # present, but invisible
    proj = _mk(tmp_path, l4)
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "base_address_hex" in r.stdout
    assert "not in the form the layer's consumer reads" in r.stdout

    # Prove the emitter really loses it.
    sys.path.insert(0, str(PROG.parent))
    import phase2_scaffold_gen as psg  # type: ignore
    emitted = psg.derive_registers(psg._unwrap_fields(l4), {})
    assert emitted[0]["offset"].strip() == "", \
        "emitter should not have seen the address"


def test_regression_addr_hex_is_now_read_by_the_emitter(tmp_path):
    """DISTILLED FIX, locked in.

    This plugin's own L4 register-table extractors emit a register's
    address as ``addr_hex`` while ``derive_registers()`` read only
    ``offset``/``address`` — two programs in the same plugin disagreeing
    on one key. Measured across the fleet, 49 of 139 real Phase-1
    outputs lost their entire address decode to it. The fix is central
    (teach the emitter the sibling key), not per-design, so this test
    asserts the emitter now SEES it and the gate goes quiet."""
    sys.path.insert(0, str(PROG.parent))
    import phase2_scaffold_gen as psg  # type: ignore

    l4 = _good_l4()
    for reg in l4["registers"]:
        if "offset" in reg:
            reg["addr_hex"] = reg.pop("offset")
        elif "address" in reg:
            reg["addr_hex"] = reg.pop("address")

    emitted = psg.derive_registers(psg._unwrap_fields(l4), {})
    assert all(r["offset"].strip() for r in emitted), \
        "addr_hex must reach the emitter after the distilled fix"

    r = _run(_mk(tmp_path, l4))
    assert r.returncode == 0, r.stdout + r.stderr


def test_negative_control_duplicate_address_fails(tmp_path):
    """Two registers claiming one address is an ambiguous decode."""
    l4 = _good_l4()
    l4["registers"][1]["offset"] = "0x00"          # same as [0]
    r = _run(_mk(tmp_path, l4))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "more than one register" in r.stdout


def test_duplicate_address_detected_across_radix_forms(tmp_path):
    """0x08 and 8 are the same address; the collision check normalises."""
    l4 = _good_l4()
    l4["registers"][1]["offset"] = "8"             # == 0x08 of reg_gamma
    r = _run(_mk(tmp_path, l4))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "more than one register" in r.stdout


# ---------------------------------------------------------------------------
# NO-FALSE-POSITIVE controls.
# ---------------------------------------------------------------------------

def test_no_register_map_skips(tmp_path):
    r = _run(_mk(tmp_path, {
        "registers": [],
        "no_registers_in_input": True,
        "register_map_present": False,
    }))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[SKIP]" in r.stdout


def test_missing_l4_skips(tmp_path):
    proj = tmp_path / "empty"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr


def test_honest_silence_no_address_anywhere_warns_not_fails(tmp_path):
    """A register whose record carries NO address at all is an honest
    extraction gap. Inventing an address would be far worse, so this
    WARNs and does not block."""
    l4 = _good_l4()
    l4["registers"][0].pop("offset")
    r = _run(_mk(tmp_path, l4))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[WARN]" in r.stdout
    assert "honest extraction gap" in r.stdout


def test_width_field_not_mistaken_for_hidden_address(tmp_path):
    """A numeric ``width``/``reset_value`` must not be read as a hidden
    address — otherwise the honest-silence path would false-FAIL."""
    l4 = _good_l4()
    reg = l4["registers"][0]
    reg.pop("offset")
    reg["width"] = 32
    reg["reset_value"] = "0x0"
    r = _run(_mk(tmp_path, l4))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[WARN]" in r.stdout


def test_waiver_suppresses_fail(tmp_path):
    l4 = _good_l4()
    l4["registers"][1]["name"] = "reg_alpha"
    proj = _mk(tmp_path, l4)
    (proj / "waivers.json").write_text(json.dumps({
        "l4_regmap_emitter_contract_intentional":
            "This synthesized fixture intentionally collides two register "
            "names so the documented waiver path is exercised in test.",
    }), encoding="utf-8")
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "waived" in r.stdout


# ---------------------------------------------------------------------------
# Both directions on one edit.
# ---------------------------------------------------------------------------

def test_both_directions_on_one_edit(tmp_path):
    """Move one address to a key the emitter does not read. Same value,
    same register, same everything else — verdict must flip."""
    good = _good_l4()
    bad = _good_l4()
    bad["registers"][0]["base_address_hex"] = bad["registers"][0].pop("offset")

    r_good = _run(_mk(tmp_path, good, name="good"))
    r_bad = _run(_mk(tmp_path, bad, name="bad"))
    assert r_good.returncode == 0, r_good.stdout
    assert r_bad.returncode == 1, r_bad.stdout
    assert r_good.returncode != r_bad.returncode
