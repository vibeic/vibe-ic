#!/usr/bin/env python3
"""Regression for ORGANIC-20260722 #784 — `l9_rtl_pin_consistency_check`
reported a design's supply pins as "missing from RTL top" whenever they use the
universal ```ifdef USE_POWER_PINS`` convention.

Root cause pinned: #704 made the RTL-top port parser preprocessor-aware and
BLANKS not-taken ``ifdef`` arms, resolving the define-set to ``{SIMULATION}`` or
``{SYNTHESIS}``. ``USE_POWER_PINS`` is in NEITHER set, so every port declared
behind that guard disappears from the RTL side of the diff — while L9 still
declares them, because every PDK datasheet lists the supply pins. Result: a
permanent false FAIL

    L9 declares pins missing from RTL top: ['vccd1', 'vssd1']

on any design following the sky130 / Caravel / OpenLane power-pin convention —
including designs whose supplies are demonstrably present in the source.

Why "just take the arm" is NOT the fix (test_negctl_taking_arm_flips_the_lie):
the hardened face legitimately carries supplies the functional pin table never
enumerates (unused-domain rails: vdda*/vssa*/vccd2/vssd2). Compiling the arm
turns the false "missing" into an equally false "RTL top has ports not in L9".

Fix: strip the RTL top's OWN ``ifdef USE_POWER_PINS`` face from BOTH sides of
the diff. Supply pins are owned by the power-intent / PDN layer (L21), not by
this gate — whose stated purpose is QSF/SDC pin ASSIGNMENT correctness, and a
supply rail is never pin-assigned. The exemption is SYMMETRIC and derived from
the DUT's own source, so only names literally declared inside that module's
power arm are exempt: a dropped FUNCTIONAL pin can never hide behind it
(test_functional_pin_drop_still_fails, test_extra_functional_pin_still_fails).
A top with no power arm yields an empty set → byte-identical (test_noleak_*).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import l9_rtl_pin_consistency_check as G  # noqa: E402

TOP = "caravel_user_project"

_TOP_TMPL = """\
`default_nettype none
module {top} (
{power}
    input  wb_clk_i,
    input  wb_rst_i,
    input  [31:0] wbs_dat_i,
    output [31:0] wbs_dat_o,
    output wbs_ack_o,
{extra}\
    inout  [28:0] analog_io,
    input  user_clock2,
    output [2:0] user_irq
);
endmodule
`default_nettype wire
"""

# The full harness supply face: only vccd1/vssd1 are documented in L9; the
# unused-domain rails are present on the RTL face but absent from the pin table.
_POWER = """\
`ifdef USE_POWER_PINS
    inout vdda1,
    inout vssa1,
    inout vccd1,
    inout vccd2,
    inout vssd1,
    inout vssd2,
`endif
"""

_L9_PORTS = [
    ("wb_clk_i", "input"), ("wb_rst_i", "input"),
    ("wbs_dat_i", "input"), ("wbs_dat_o", "output"),
    ("wbs_ack_o", "output"), ("analog_io", "inout"),
    ("user_clock2", "input"), ("user_irq", "output"),
    ("vccd1", "inout"), ("vssd1", "inout"),
]


def _mk(tmp_path: Path, *, power: str = _POWER, extra: str = "",
        l9_ports=None, drop_from_rtl: str = "") -> Path:
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    text = _TOP_TMPL.format(top=TOP, power=power, extra=extra)
    if drop_from_rtl:
        text = "\n".join(ln for ln in text.splitlines()
                         if drop_from_rtl not in ln) + "\n"
    (rtl / f"{TOP}.v").write_text(text)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": TOP,
        "top_ports": [{"name": n, "direction": d, "mode": d}
                      for n, d in (l9_ports or _L9_PORTS)],
    }))
    return proj


def _run(proj: Path) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(PROG_DIR / "l9_rtl_pin_consistency_check.py"),
         str(proj)], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# ── the defect ──────────────────────────────────────────────────────────
def test_use_power_pins_face_no_longer_reported_missing():
    """This is the exact caravel_user_project x sky130A residual."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rc, out = _run(_mk(Path(td)))
    assert rc == 0, out
    assert "PASS" in out
    assert "vccd1" not in out and "vssd1" not in out


def test_negctl_taking_arm_flips_the_lie(tmp_path):
    """Pins WHY compiling the arm is not the fix: with the arm TAKEN the
    undocumented rails become RTL-only ports. The gate's own parser, handed a
    define-set that includes USE_POWER_PINS, sees all six rails — of which four
    are absent from L9. The symmetric strip is what makes both directions
    correct at once."""
    proj = _mk(tmp_path)
    rtl_top = proj / "phase2" / "stage1" / "rtl" / f"{TOP}.v"
    taken = {p["name"] for p in G.parse_rtl_top_ports(
        rtl_top, TOP, {"SIMULATION", "USE_POWER_PINS"})}
    l9 = {n for n, _ in _L9_PORTS}
    assert {"vdda1", "vssa1", "vccd2", "vssd2"} <= (taken - l9), (
        "taking the arm exposes undocumented rails as RTL-only ports")


# ── the gate must still catch REAL gaps ─────────────────────────────────
def test_functional_pin_drop_still_fails(tmp_path):
    """A functional pin missing from the RTL top must still FAIL — the power
    exemption covers ONLY names in the DUT's own USE_POWER_PINS arm."""
    rc, out = _run(_mk(tmp_path, drop_from_rtl="analog_io"))
    assert rc != 0 and "analog_io" in out


def test_extra_functional_pin_still_fails(tmp_path):
    """An RTL port absent from L9 must still FAIL."""
    rc, out = _run(_mk(tmp_path, extra="    output [2:0] irq,\n"))
    assert rc != 0 and "irq" in out


def test_supply_named_pin_outside_the_arm_is_not_exempt(tmp_path):
    """A pin merely NAMED like a rail but declared OUTSIDE the guard is a
    normal functional port and stays subject to the diff — the exemption is
    structural (declared in the arm), never name-based."""
    rc, out = _run(_mk(tmp_path, power="", extra="    inout vccd1,\n",
                       l9_ports=[p for p in _L9_PORTS
                                 if p[0] not in ("vccd1", "vssd1")]))
    assert rc != 0 and "vccd1" in out


# ── no-leak ─────────────────────────────────────────────────────────────
def test_noleak_top_without_power_arm_unchanged(tmp_path):
    """No USE_POWER_PINS arm → empty power face → historical exact-name diff."""
    rc, out = _run(_mk(tmp_path, power="",
                       l9_ports=[p for p in _L9_PORTS
                                 if p[0] not in ("vccd1", "vssd1")]))
    assert rc == 0 and "PASS" in out


def test_power_face_helper_reads_only_the_guarded_arm(tmp_path):
    proj = _mk(tmp_path)
    face = G._rtl_power_pin_face(
        proj / "phase2" / "stage1" / "rtl" / f"{TOP}.v", TOP)
    assert face == {"vdda1", "vssa1", "vccd1", "vccd2", "vssd1", "vssd2"}
    assert "analog_io" not in face and "wb_clk_i" not in face


def test_power_face_helper_empty_without_arm(tmp_path):
    proj = _mk(tmp_path, power="",
               l9_ports=[p for p in _L9_PORTS
                         if p[0] not in ("vccd1", "vssd1")])
    assert G._rtl_power_pin_face(
        proj / "phase2" / "stage1" / "rtl" / f"{TOP}.v", TOP) == set()


def test_power_face_helper_degrades_on_missing_file(tmp_path):
    assert G._rtl_power_pin_face(tmp_path / "nope.v", TOP) == set()
