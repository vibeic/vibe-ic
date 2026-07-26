#!/usr/bin/env python3
"""#362 — PSM-0079 on gf180mcuD: the voltage is in the library, nothing
selects it.

MEASURED with OpenSTA's own API on a real gf180 standard-cell liberty inside
`vibeic-eda:0.2.30`:

    $lib default_operating_conditions   -> NULL
    $lib find_operating_conditions <n>  -> exists, voltage = 5.0

and 30 of 30 gf180mcuD standard-cell liberties define an
`operating_conditions(<name>) { ... }` block while NONE carry the
`default_operating_conditions` line naming one.

WHY A NAME, NOT A VOLTAGE. The rejected alternative parsed `nom_voltage` and
fed it to `set_pdnsim_net_voltage`: that overrides the 926 of 956 liberties
where the tool was already right, puts one core voltage on EVERY power net
(3.3 V rails included), and is only as good as its regex. Selecting the OC by
NAME hands the tool a pointer and lets it read its own authoritative voltage —
and fixes STA / power / derate at the same time, not just PSM.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402

_NO_CONTAINER = "no-such-container-for-tests"


def _lib(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "x.lib"
    p.write_text(body)
    return p


def test_362_the_block_name_is_extracted(tmp_path):
    lib = _lib(tmp_path, "library (foo) {\n"
                         "  nom_voltage : 5 ;\n"
                         "  operating_conditions(gf180mcu__tt_025C_5v00) {\n"
                         "    voltage : 5.0 ;\n  }\n}\n")
    assert p3._liberty_operating_condition(lib, _NO_CONTAINER) == \
        "gf180mcu__tt_025C_5v00"


def test_362_no_block_means_no_emission(tmp_path):
    """A liberty without the block gets nothing — the prior behaviour stays
    byte-identical, so this cannot regress the PDKs that already work."""
    lib = _lib(tmp_path, "library (bar) {\n  nom_voltage : 1.8 ;\n}\n")
    assert p3._liberty_operating_condition(lib, _NO_CONTAINER) == ""


def test_362_unreadable_liberty_is_not_guessed(tmp_path):
    """No liberty, no name. Inventing one would assert a condition the design
    never declared."""
    assert p3._liberty_operating_condition(None, _NO_CONTAINER) == ""
    assert p3._liberty_operating_condition(
        tmp_path / "absent.lib", _NO_CONTAINER) == ""


def test_362_the_name_comes_from_the_library_not_a_pdk_table():
    """chip/PDK-AGNOSTIC: no known-PDK list may drive the choice, or a PDK
    this plugin has never seen stays broken."""
    import inspect
    src = inspect.getsource(p3._liberty_operating_condition)
    body = src.split('"""')[-1]        # code after the docstring
    for token in ("gf180", "sky130", "asap7", "ihp", "sg13"):
        assert token not in body.lower(), f"{token!r} drives the extraction"


def test_362_first_block_wins_deterministically(tmp_path):
    """A multi-corner liberty must yield ONE stable answer rather than an
    order-dependent one."""
    lib = _lib(tmp_path, "library (m) {\n"
                         "  operating_conditions(first_tt) { voltage : 5.0 ; }\n"
                         "  operating_conditions(second_ss) { voltage : 4.5 ; }\n"
                         "}\n")
    assert p3._liberty_operating_condition(lib, _NO_CONTAINER) == "first_tt"


def test_362_the_emitter_selects_the_condition_and_asserts_no_voltage():
    """Wiring pin + the anti-fabrication boundary: the emitted Tcl must call
    `set_operating_conditions` and must NOT assert a per-net voltage."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    i = src.index("def _emit_ir_em_reports(")
    j = src.index("\ndef ", i + 1)
    body = src[i:j]
    assert "set_operating_conditions" in body
    assert "_liberty_operating_condition(" in body
    assert "set_pdnsim_net_voltage" not in body, (
        "the rejected fix asserts a parsed voltage on every power net")
