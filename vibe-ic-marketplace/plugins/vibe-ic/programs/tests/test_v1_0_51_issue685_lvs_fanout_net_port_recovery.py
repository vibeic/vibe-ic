#!/usr/bin/env python3
"""Regression tests for issue #685 — LVS top-port recovery must re-add a
dropped port when two top OUTPUT ports fan out from one shared INTERNAL net,
not only when a pin is aliased to ANOTHER PIN.

Root cause (caravel round-6, public tree v1.0.47): when two distinct top
OUTPUT ports share one internal net (e.g. `assign io_out=...count...` AND
`assign la_data_out=count`), OpenROAD writes BOTH DEF pins onto that net and
Magic ext2spice keeps only ONE, dropping the other from the .subckt → netgen
'failed pin matching' (it reported 382/382 devices + 407/407 nets identical,
"match uniquely with port errors"). The old detector filtered `n in pins`,
firing ONLY when the shared net is itself another top-pin name (the pin-to-pin
`assign o_a=o_b` case), so the internal-net fan-out was silently skipped.

Fix: GROUP DEF pins by NET; for any net carrying ≥2 top pins, keep the port
ext2spice retained (present in the extracted .subckt header) and re-add the
OTHER pins via a 0-ohm RWALIAS join. Subsumes the pin-to-pin case. NO
port-name allowlist (chip-AGNOSTIC).

§4.05 negative (no-leak): a net carrying exactly ONE top port must NOT get a
fabricated alias — covered by test_negative_single_port_net_not_aliased.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "phase3_one_shot_runner.py"
sys.path.insert(0, str(PROG.parent))
import phase3_one_shot_runner as r  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402


def _def(pin_net_pairs):
    body = "\n".join(f"  - {p} + NET {n} + DIRECTION OUTPUT ;"
                     for p, n in pin_net_pairs)
    return ("VERSION 5.8 ;\nDESIGN top ;\n"
            f"PINS {len(pin_net_pairs)} ;\n{body}\nEND PINS\nEND DESIGN\n")


# ── #685: fan-out to a shared INTERNAL net ─────────────────────────────
def test_fanout_internal_net_recovers_dropped_port():
    # io_out[0] and la_data_out[0] both fan out from internal net count[0].
    def_text = _def([
        ("io_out[0]", "mprj.count[0]"),
        ("la_data_out[0]", "mprj.count[0]"),
        ("io_out[1]", "mprj.count[1]"),
        ("la_data_out[1]", "mprj.count[1]"),
    ])
    # ext2spice kept io_out[*] (present in the extracted header) and DROPPED
    # la_data_out[*].
    kept_set = {"io_out[0]", "io_out[1]"}
    aliases = r._v0_3_14_detect_top_port_aliases(
        def_text, extracted_port_set=kept_set)
    pairs = set(aliases)
    assert ("la_data_out[0]", "io_out[0]") in pairs
    assert ("la_data_out[1]", "io_out[1]") in pairs
    # the KEPT ports are never re-added.
    assert all(d.startswith("la_data_out") for d, _k in aliases)


def test_fanout_recovery_patches_subckt_and_adds_zero_ohm():
    def_text = _def([
        ("io_out[0]", "mprj.count[0]"),
        ("la_data_out[0]", "mprj.count[0]"),
    ])
    sp = (".subckt top io_out[0] VPWR VGND\n"
          "X0 io_out[0] VPWR VGND inv\n"
          ".ends\n")
    kept = r._v0_3_14_extracted_top_port_set(sp, top="top")
    assert "io_out[0]" in kept and "la_data_out[0]" not in kept
    aliases = r._v0_3_14_detect_top_port_aliases(
        def_text, extracted_port_set=kept)
    patched = r._v0_3_14_apply_top_port_aliases(sp, aliases, top="top")
    new_kept = r._v0_3_14_extracted_top_port_set(patched, top="top")
    assert "la_data_out[0]" in new_kept  # dropped port recovered
    # 0-ohm join to the kept canonical port (netgen auto-removes it).
    assert "RWALIAS" in patched
    assert "io_out[0] la_data_out[0] 0" in patched


# ── §4.05 NEGATIVE no-leak — single-port nets untouched ────────────────
def test_negative_single_port_net_not_aliased():
    # Every net carries exactly one top port → NO alias may be fabricated.
    def_text = _def([
        ("io_out[0]", "mprj.netA"),
        ("io_out[1]", "mprj.netB"),
        ("clk", "mprj.clk_net"),
        ("rst", "mprj.rst_net"),
    ])
    aliases = r._v0_3_14_detect_top_port_aliases(
        def_text, extracted_port_set={"io_out[0]", "io_out[1]", "clk", "rst"})
    assert aliases == []


# ── backward compat: the original #509 pin-to-pin case still fires ─────
def test_pin_to_pin_alias_still_detected():
    # io_oeb[0] aliased to another PIN io_oeb[37] (shared net IS a top pin).
    def_text = _def([
        ("io_oeb[0]", "io_oeb[37]"),
        ("io_oeb[37]", "io_oeb[37]"),
    ])
    # With no extracted set, the net-named pin (io_oeb[37]) is canonical.
    aliases = r._v0_3_14_detect_top_port_aliases(def_text)
    assert ("io_oeb[0]", "io_oeb[37]") in set(aliases)
    # io_oeb[37] (the net-named, canonical pin) is not itself re-added.
    assert all(d == "io_oeb[0]" for d, _k in aliases)


def test_three_ports_on_one_net_recovers_two():
    def_text = _def([
        ("a", "n"),
        ("b", "n"),
        ("c", "n"),
    ])
    aliases = r._v0_3_14_detect_top_port_aliases(
        def_text, extracted_port_set={"a"})
    pairs = set(aliases)
    assert ("b", "a") in pairs and ("c", "a") in pairs
    assert ("a", "a") not in pairs  # kept port never aliases to itself
    assert len(aliases) == 2


def test_deterministic_kept_when_no_extracted_set():
    # No extracted set + net is internal (not a pin name) → first sorted pin.
    def_text = _def([
        ("z_port", "internal"),
        ("a_port", "internal"),
    ])
    aliases = r._v0_3_14_detect_top_port_aliases(def_text)
    # a_port sorts first → it is kept; z_port is re-added.
    assert ("z_port", "a_port") in set(aliases)
    assert ("a_port", "z_port") not in set(aliases)


# ── real caravel repro (only if the round-6 artifacts are present) ─────
_REPRO = corpus_path("_bench7_caravel_v1034_cleanroom/caravel_r6")


@pytest.mark.skipif(
    not ((_REPRO / "phase3/stage3/pnr/filled.def").is_file()
         and (_REPRO / "phase3/stage3/extracted/"
              "user_project_wrapper_extracted.sp").is_file()),
    reason="caravel_r6 repro artifacts not present; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_caravel_repro_recovers_16_la_data_out():
    def_text = (_REPRO / "phase3/stage3/pnr/filled.def").read_text(
        errors="replace")
    sp_text = (_REPRO / "phase3/stage3/extracted/"
               "user_project_wrapper_extracted.sp").read_text(errors="replace")
    top = "user_project_wrapper"
    kept = r._v0_3_14_extracted_top_port_set(sp_text, top=top)
    aliases = r._v0_3_14_detect_top_port_aliases(
        def_text, extracted_port_set=kept)
    la = sorted(d for d, _k in aliases if d.startswith("la_data_out"))
    # exactly the 16 counter-net-shared bits [0..15] were dropped.
    assert la == sorted(f"la_data_out[{i}]" for i in range(16))
    # no single-port net was aliased (no-leak on real data).
    patched = r._v0_3_14_apply_top_port_aliases(sp_text, aliases, top=top)
    new_kept = r._v0_3_14_extracted_top_port_set(patched, top=top)
    for i in range(16):
        assert f"la_data_out[{i}]" in new_kept
