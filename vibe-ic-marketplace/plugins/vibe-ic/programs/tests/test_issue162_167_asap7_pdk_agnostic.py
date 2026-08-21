"""benchmark-spm-asap7 — regression pins for the ASAP7 / PDK-agnostic HIGH
cluster in phase3_one_shot_runner.py:

  * #162 A1 — named registry PDK resolution + B3 (#176) loud-warn on a
    registry-declared-but-unbranched name (never a silent sky130A fallback).
  * #163 A2 — merge the 5 split ASAP7 Liberty functional groups into one
    ``library{}`` (union of cells, dedup, renamed) so synth sees the DFFs.
  * #177 A3 — a cached synth netlist is reused ONLY when its masters exist in
    the ACTIVE PDK liberty (no wrong-PDK provenance laundering).
  * #164 A4 — SDC numerics scale into the liberty's declared time/cap units
    (ASAP7 ps/fF) while an ns/pF PDK (sky130) stays byte-identical.
  * #165 A5 — ``place_pins`` hor/ver layers derive from the tech LEF routing
    DIRECTIONs (ASAP7 M2=HOR/M3=VER, the OPPOSITE of sky130) with a legacy
    fallback.
  * #167 A7 — the staged tech LEF normalizes a negative routing-layer OFFSET
    to its non-negative pitch-equivalent (ASAP7 M2 OFFSET -0.27 ≡ 0).
  * #158 — the auto die-sizer floors the die side at the IO-pin perimeter.

chip/PDK-AGNOSTIC: synthetic Liberty / tech-LEF fixtures only; no chip/SKU
literal. Every fixture mirrors the real ASAP7 token shapes.
"""
import sys
from pathlib import Path

import pytest  # noqa: F401  (used by test_b3 refuse-contract check)

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# ---------------------------------------------------------------------------
# #162 A1 / #176 B3 — registry resolution, no silent sky130A fallback
# ---------------------------------------------------------------------------
def test_a1_registry_declares_asap7_assets():
    reg = R._pdk_registry_entry("asap7")
    assert reg is not None, "pdk_registry.json must declare an 'asap7' entry"
    assert reg["container_path"].endswith("/asap7")
    # the liberty glob is a MULTI-file group pattern (A2 depends on it)
    assert "*" in reg["liberty_glob"]
    assert reg.get("metal_prefix") == "M"


def test_b3_unbranched_registry_name_refuses_not_silent_sky130a(
        tmp_path, monkeypatch):
    """CONTRACT (updated for #211): a registry-declared name with NO named
    _detect_pdk branch (gf180mcuD) is now resolved GENERICALLY from the
    registry. The old contract was warn-then-fall-back-to-sky130A; that WARN +
    silent sky130A substitution is exactly the structural-wrong-sign-off defect
    #211 removed. The new, stronger contract: the named PDK either resolves to
    ITS OWN assets, or — when those assets cannot be resolved — REFUSES
    (SystemExit). It must NEVER silently masquerade as sky130A.

    Driven with a mocked container (no docker / no PDK install needed) whose
    gf180mcuD directory exists but whose asset globs match nothing but the
    login banner, so the outcome is deterministically the refuse branch."""
    root = R._pdk_registry_entry("gf180mcuD")["container_path"].rstrip("/")
    banner = "[INFO] Final PATH variable: /headless/.local/bin:/foss/tools/bin"

    def _fake_exec(container, cmd, timeout=1800):
        c = cmd.strip()
        # the PDK directory exists; nothing else does — and every login shell
        # prints the banner to stdout ahead of the command output.
        if c.startswith("test -d ") and root in c:
            return (0, banner + "\n", "")
        if c.startswith("ls -1d "):        # wildcard asset glob: no real match
            return (0, banner + "\n", "")
        if c.startswith("test -e "):       # nothing exists
            return (1, banner + "\n", "")
        return (0, banner + "\n", "")

    monkeypatch.setattr(R, "_docker_exec_raw", _fake_exec)
    with pytest.raises(SystemExit) as ei:
        R._detect_pdk(tmp_path, override="gf180mcuD")
    msg = str(ei.value)
    # loud + explicit about the PDK the operator named, and explicit that the
    # resolver REFUSES rather than continuing with a substituted PDK.
    assert "gf180mcuD" in msg
    assert "REFUS" in msg.upper()
    # any mention of sky130A here is the thing being refused, not the outcome.
    assert "fall back" in msg.lower()


# ---------------------------------------------------------------------------
# #163 A2 — merge split Liberty groups
# ---------------------------------------------------------------------------
_GRP_A = """\
library (asap7sc7p5t_SIMPLE) {
  time_unit : "1ps";
  cell (INVx1_ASAP7_75t_R) { area : 0.1 ; pin(Y){direction:output;} }
  cell (BUFx2_ASAP7_75t_R) { area : 0.2 ; pin(Y){direction:output;} }
}
"""
_GRP_B = """\
library (asap7sc7p5t_SEQ) {
  cell (DFFHQNx1_ASAP7_75t_R) { area : 0.5 ; ff(IQ,IQN){} }
  cell (BUFx2_ASAP7_75t_R) { area : 0.2 ; pin(Y){direction:output;} }
}
"""


def test_a2_merge_unions_cells_dedups_and_renames_library():
    merged = R._merge_liberty_texts(_GRP_A, [_GRP_B], lib_name="asap7_merged")
    # DFF from the SEQ group is now present (the whole point — synth sees FFs)
    assert "DFFHQNx1_ASAP7_75t_R" in merged
    assert "INVx1_ASAP7_75t_R" in merged
    # library renamed to the merged name
    assert "library (asap7_merged)" in merged
    # BUFx2 appears in BOTH groups but is deduped to a SINGLE cell block
    assert merged.count("cell (BUFx2_ASAP7_75t_R)") == 1


# ---------------------------------------------------------------------------
# #177 A3 — no wrong-PDK provenance laundering
# ---------------------------------------------------------------------------
_LIB_ASAP7 = ("library(x){\n cell (INVx1_ASAP7_75t_R){}\n"
              " cell (DFFHQNx1_ASAP7_75t_R){}\n}\n")


def test_a3_netlist_matches_liberty_true_when_masters_known(tmp_path):
    nl = tmp_path / "n.v"
    nl.write_text("module top(a, y);\n"
                  "  INVx1_ASAP7_75t_R u1 (.A(a), .Y(y));\n"
                  "  DFFHQNx1_ASAP7_75t_R u2 (.D(a), .QN(y));\n"
                  "endmodule\n")
    lib = tmp_path / "l.lib"
    lib.write_text(_LIB_ASAP7)
    assert R._netlist_matches_liberty(nl, str(lib)) is True


def test_a3_netlist_matches_liberty_false_when_master_is_foreign(tmp_path):
    # a sky130-mapped netlist reused under the ASAP7 liberty → foreign master
    nl = tmp_path / "n.v"
    nl.write_text("module top(a, y);\n"
                  "  sky130_fd_sc_hd__inv_2 u1 (.A(a), .Y(y));\n"
                  "endmodule\n")
    lib = tmp_path / "l.lib"
    lib.write_text(_LIB_ASAP7)
    assert R._netlist_matches_liberty(nl, str(lib)) is False


def test_a3_unreadable_inputs_default_to_trust(tmp_path):
    assert R._netlist_matches_liberty(tmp_path / "absent.v", "") is True


# ---------------------------------------------------------------------------
# #164 A4 — SDC unit scaling
# ---------------------------------------------------------------------------
def _lib(tmp, unit_time, unit_cap):
    p = tmp / f"lib_{unit_time}_{unit_cap}.lib"
    p.write_text(f'library(x){{\n time_unit : "{unit_time}";\n'
                 f' capacitive_load_unit ({unit_cap});\n}}\n')
    return p


def test_a4_scale_staged_sdc_ps_ff(tmp_path):
    lib = _lib(tmp_path, "1ps", "1,ff")
    staged = ("create_clock -name clk -period 10.0 [get_ports clk]\n"
              "set_max_transition 1.5 [current_design]\n"
              "set_max_capacitance 5 [current_design]\n")
    out = R._scale_sdc_to_liberty_units(staged, str(lib))
    assert "create_clock -name clk -period 10000" in out
    assert "set_max_transition 1500" in out
    assert "set_max_capacitance 5000" in out


def test_a4_scale_noop_for_ns_pf_pdk(tmp_path):
    lib = _lib(tmp_path, "1ns", '1.0,"pf"')
    staged = "create_clock -name clk -period 10.0 [get_ports clk]\n"
    # ns/pF → scale factor 1 → byte-identical (regression-safe for sky130)
    assert R._scale_sdc_to_liberty_units(staged, str(lib)) == staged


def test_a4_auto_sdc_period_scales_ps_but_byte_identical_ns(tmp_path):
    proj = tmp_path / "proj"
    (proj / "phase1").mkdir(parents=True)
    ps = R._build_auto_silicon_sdc(
        proj, liberty_path=str(_lib(tmp_path, "1ps", "1,ff")))
    ns = R._build_auto_silicon_sdc(
        proj, liberty_path=str(_lib(tmp_path, "1ns", '1.0,"pf"')))
    none = R._build_auto_silicon_sdc(proj)
    # default 20 ns → ASAP7 emits 20000 (ps); sky130 keeps 20.0 == the no-lib case
    assert "create_clock -name clk -period 20000 " in ps
    assert "create_clock -name clk -period 20.0 " in ns
    assert "create_clock -name clk -period 20.0 " in none
    assert "set_input_delay  2000 " in ps and "set_input_delay  2 " in ns


# ---------------------------------------------------------------------------
# #165 A5 — pin-layer direction resolution
# ---------------------------------------------------------------------------
_ASAP7_TLEF = """\
LAYER M1
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
LAYER M2
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
LAYER M3
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
"""
_SKY_TLEF = """\
LAYER met1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
LAYER met2
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
LAYER met3
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
"""


def test_a5_pin_layers_asap7_flips_convention():
    # ASAP7: M2=HOR / M3=VER → hor=M2, ver=M3 (opposite of sky130)
    assert R._pin_layers_from_techlef(_ASAP7_TLEF, "M") == ("M2", "M3")


def test_a5_pin_layers_sky130_legacy_unchanged():
    assert R._pin_layers_from_techlef(_SKY_TLEF, "met") == ("met3", "met2")


def test_a5_pin_layers_empty_falls_back_to_legacy():
    assert R._pin_layers_from_techlef("", "M") == ("M3", "M2")


# ---------------------------------------------------------------------------
# #167 A7 — negative-OFFSET normalization in the staged tech LEF
# ---------------------------------------------------------------------------
_TLEF_NEG_OFFSET = """\
LAYER M1
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
 OFFSET 0.0 ;
 PITCH 0.036 ;
LAYER M2
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
 OFFSET -0.27 ;
 PITCH 0.045 ;
"""


def test_a7_stage_normalized_techlef_zeroes_pitch_multiple_offset(
        tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_container_file_text",
                        lambda container, path: _TLEF_NEG_OFFSET)
    reg = {"container_path": "/foss/pdks/asap7",
           "tech_lef_glob": "techlef/asap7_tech.lef"}
    out = R._stage_normalized_techlef(tmp_path, "vibeic-eda", reg)
    txt = out.read_text()
    # -0.27 == -6 * 0.045 → normalized to 0; the negative offset is gone
    assert "OFFSET -0.27" not in txt
    assert "OFFSET 0" in txt
    # the legal non-negative offset is untouched
    assert "OFFSET 0.0" in txt or "OFFSET 0 ;" in txt


# ---------------------------------------------------------------------------
# #158 — pin-perimeter die floor
# ---------------------------------------------------------------------------
def test_158_pin_perimeter_side_grows_with_pin_count():
    small = R._pin_perimeter_die_side_um(4, 0.045)
    big = R._pin_perimeter_die_side_um(4000, 0.045)
    assert big > small
    # a non-positive pin count never over-fires (returns the floor, not junk)
    assert R._pin_perimeter_die_side_um(0, 0.045) == R._AUTO_DIE_MIN_SIDE_UM


def test_158_pin_perimeter_clamped_to_max():
    assert R._pin_perimeter_die_side_um(10 ** 9, 1.0) == R._DEFAULT_DIE_MAX_UM
