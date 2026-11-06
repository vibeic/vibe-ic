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

_NO_CONTAINER = "no-such-container-for-tests"














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


# ── the DYNAMIC half (#362's own listed damage: ERROR_NO_PSM_IR) ────────────
# `dynamic_ir_vectored_emit` read the liberty straight into `read_def` with no
# operating condition, so `analyze_power_grid -transient` hit the same
# PSM-0079 and the transient run produced nothing. Same root cause, same fix.

import dynamic_ir_vectored_emit as dyn  # noqa: E402


def _tcl(tmp_path: Path, lib_body: str) -> str:
    lib = tmp_path / "l.lib"
    lib.write_text(lib_body)
    return dyn._build_transient_tcl(
        tmp_path / "d.def", tmp_path / "t.lef", tmp_path / "c.lef", lib,
        [], None, "VDD", 10.0, 20, None, {}, "met")


def test_362_dynamic_selects_the_condition_when_the_library_declares_one(tmp_path):
    tcl = _tcl(tmp_path, "library (g) {\n"
                         "  operating_conditions(gf180_tt_5v00) "
                         "{ voltage : 5.0 ; }\n}\n")
    assert "set_operating_conditions gf180_tt_5v00" in tcl
    # ORDER is load-bearing: the condition must be selected AFTER the library
    # is read and BEFORE the design, or the solver never sees it.
    assert (tcl.index("read_liberty") < tcl.index("set_operating_conditions")
            < tcl.index("read_def"))


def test_362_dynamic_emits_nothing_without_a_block(tmp_path):
    """Zero regression on a PDK that already declares a default."""
    tcl = _tcl(tmp_path, "library (n) { }\n")
    assert "set_operating_conditions" not in tcl


def test_362_dynamic_asserts_no_voltage_either(tmp_path):
    """The same anti-fabrication boundary as the static path: select by NAME,
    never assert a parsed value on a net."""
    tcl = _tcl(tmp_path, "library (g) {\n  nom_voltage : 5 ;\n"
                         "  operating_conditions(tt) { voltage : 5.0 ; }\n}\n")
    assert "set_pdnsim_net_voltage" not in tcl


def test_362_dynamic_helper_never_raises_on_an_unreadable_liberty(tmp_path):
    assert dyn.liberty_operating_condition(tmp_path / "absent.lib") == ""
    assert dyn.liberty_operating_condition(None) == ""
