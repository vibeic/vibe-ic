"""tests/test_digital_hardmacro_check.py — step 37.5ip gate of record.

A GATE THAT CANNOT FAIL IS NOT A GATE. Every case below breaks exactly ONE
thing the gate defends, in a scratch copy of a kit that otherwise PASSes, and
asserts the gate goes red on it — so a future weakening of any single
predicate turns exactly one test.

The fixture is a four-view digital hardmacro kit under
`phase3/stage4/hardmacro/`, built here rather than imported: the GDSII stream
is CONSTRUCTED from record bytes by this file, so the test and the gate reach
the same bounding box from two independent directions. A builder shared with
the program under test would make them agree by construction.

Structure:
  PASS   — a complete, agreeing kit.
  REFUSE — the four the brief names (missing view / empty view / outline
           disagreement / a pin in one view and not another) plus identity,
           registration, hollow-GDS and interface-direction cases.
  HONEST — an absent kit is NOT_DETERMINED at rc 2, never a green.
  TIER   — an uncharacterised Liberty is disclosed on the verdict word.
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "digital_hardmacro_check.py"
sys.path.insert(0, str(PROG.parent))
import digital_hardmacro_check as mod  # noqa: E402


# ───────────────────────── GDSII stream builder ────────────────────────────

def _rec(rec_type: int, payload: bytes = b"") -> bytes:
    return struct.pack(">HH", 4 + len(payload), rec_type) + payload


def _real8(value: float) -> bytes:
    """GDSII 8-byte excess-64 real."""
    if value == 0:
        return b"\x00" * 8
    sign = 0x80 if value < 0 else 0x00
    v = abs(float(value))
    exp = 0
    while v >= 1.0:
        v /= 16.0
        exp += 1
    while v < 1.0 / 16.0:
        v *= 16.0
        exp -= 1
    mant = int(v * (1 << 56))
    return bytes([sign | (exp + 64)]) + mant.to_bytes(7, "big")


def build_gds(name: str = "macro_a", width_um: float = 100.0,
              height_um: float = 50.0, origin_um=(0.0, 0.0),
              dbu_per_um: float = 1000.0, with_header: bool = True,
              with_geometry: bool = True) -> bytes:
    """A minimal but VALID GDSII whose single boundary spans exactly
    width x height with its lower-left corner at `origin_um`."""
    out = b""
    if with_header:
        out += _rec(0x0002, struct.pack(">h", 600))              # HEADER
    out += _rec(0x0102, struct.pack(">12h", *([0] * 12)))        # BGNLIB
    out += _rec(0x0206, name.encode() + b"\x00")                 # LIBNAME
    out += _rec(0x0305, _real8(1.0 / dbu_per_um)
                + _real8(1e-6 / dbu_per_um))                     # UNITS
    out += _rec(0x0502, struct.pack(">12h", *([0] * 12)))        # BGNSTR
    nm = name.encode()
    out += _rec(0x0606, nm + (b"\x00" if len(nm) % 2 else b""))  # STRNAME
    if with_geometry:
        x0 = int(round(origin_um[0] * dbu_per_um))
        y0 = int(round(origin_um[1] * dbu_per_um))
        x1 = x0 + int(round(width_um * dbu_per_um))
        y1 = y0 + int(round(height_um * dbu_per_um))
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        out += _rec(0x0800)                                      # BOUNDARY
        out += _rec(0x0D02, struct.pack(">h", 1))                # LAYER
        out += _rec(0x0E02, struct.pack(">h", 0))                # DATATYPE
        out += _rec(0x1003, b"".join(struct.pack(">ii", x, y)
                                     for x, y in pts))           # XY
        out += _rec(0x1100)                                      # ENDEL
    out += _rec(0x0700)                                          # ENDSTR
    out += _rec(0x0400)                                          # ENDLIB
    return out


# ───────────────────────── the agreeing kit ────────────────────────────────

LEF_OK = """VERSION 5.8 ;
BUSBITCHARS "[]" ;
MACRO macro_a
  CLASS BLOCK ;
  ORIGIN 0 0 ;
  SIZE 100.0000 BY 50.0000 ;
  PIN clk
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER met2 ;
        RECT 0.0000 10.0000 0.4000 10.4000 ;
    END
  END clk
  PIN dout[0]
    DIRECTION OUTPUT ;
    USE SIGNAL ;
    PORT
      LAYER met2 ;
        RECT 99.6000 10.0000 100.0000 10.4000 ;
    END
  END dout[0]
  PIN dout[1]
    DIRECTION OUTPUT ;
    USE SIGNAL ;
    PORT
      LAYER met2 ;
        RECT 99.6000 12.0000 100.0000 12.4000 ;
    END
  END dout[1]
  PIN vpwr
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER met3 ;
        RECT 0.0000 48.0000 100.0000 50.0000 ;
    END
  END vpwr
  PIN vgnd
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER met3 ;
        RECT 0.0000 0.0000 100.0000 2.0000 ;
    END
  END vgnd
  OBS
    LAYER met1 ;
      RECT 2.0000 4.0000 98.0000 46.0000 ;
  END
END macro_a
END LIBRARY
"""

LIB_OK = """library (macro_a_lib) {
  time_unit : "1ns";
  cell (macro_a) {
    area : 5000.0 ;
    pg_pin (vpwr) { voltage_name : VPWR ; pg_type : primary_power ; }
    pg_pin (vgnd) { voltage_name : VGND ; pg_type : primary_ground ; }
    pin (clk) {
      direction : input ;
      capacitance : 0.004 ;
    }
    bus (dout) {
      direction : output ;
      timing () {
        related_pin : "clk" ;
        cell_rise (scalar) { values ( "0.235" ) ; }
        cell_fall (scalar) { values ( "0.211" ) ; }
      }
    }
  }
}
"""

V_OK = """// macro_a — simulation view
(* blackbox *)
module macro_a (
    input  wire       clk,
    output wire [1:0] dout
);
endmodule
"""


def make_kit(tmp_path: Path, lef: str = LEF_OK, lib: str = LIB_OK,
             v: str = V_OK, gds: bytes = None,
             name: str = "macro_a") -> Path:
    """A project root holding ONE complete, agreeing kit."""
    hm = tmp_path / "phase3" / "stage4" / "hardmacro"
    hm.mkdir(parents=True, exist_ok=True)
    if lef is not None:
        (hm / f"{name}.lef").write_text(lef)
    if lib is not None:
        (hm / f"{name}.lib").write_text(lib)
    if v is not None:
        (hm / f"{name}.v").write_text(v)
    if gds is None:
        gds = build_gds(name)
    if gds is not None:
        (hm / f"{name}.gds").write_bytes(gds)
    return tmp_path


def run(project: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project), *extra],
        capture_output=True, text=True)


def rules(project: Path, *extra) -> set:
    out = project / "r.json"
    run(project, "--json", str(out), *extra)
    data = json.loads(out.read_text())
    return {f["rule"] for f in data["findings"]}


# ───────────────────────────── PASS ────────────────────────────────────────

def test_agreeing_kit_passes(tmp_path):
    p = make_kit(tmp_path)
    r = run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS] digital_hardmacro_check" in r.stdout


def test_pass_report_records_every_axis(tmp_path):
    p = make_kit(tmp_path)
    out = tmp_path / "rep.json"
    assert run(p, "--json", str(out)).returncode == 0
    d = json.loads(out.read_text())
    pkg = d["summary"]["packages"][0]
    assert pkg["status"] == "PASS"
    assert pkg["lef_size_um"] == [100.0, 50.0]
    assert pkg["identity"]["lef.MACRO"] == "macro_a"
    assert pkg["identity"]["lib.cell"] == "macro_a"
    assert pkg["identity"]["v.module"] == "macro_a"
    assert pkg["identity"]["gds.top"] == "macro_a"
    # bus compared by base name, and the granularity limit is STATED
    assert pkg["interface"]["lef_signal"] == ["clk", "dout"]
    assert pkg["interface"]["lib_signal"] == ["clk", "dout"]
    assert "base-name" in pkg["interface"]["granularity"]


def test_non_ansi_verilog_view_is_read(tmp_path):
    """A legal non-ANSI blackbox view must not read as "no ports at all"."""
    p = make_kit(tmp_path, v="""module macro_a (clk, dout);
  input clk;
  output [1:0] dout;
endmodule
""")
    r = run(p)
    assert r.returncode == 0, r.stdout + r.stderr


def test_multi_name_port_declaration_is_read_whole(tmp_path):
    """`input a, b;` declares BOTH — a reader taking only the first name
    would report the second missing from the Verilog view."""
    lef = LEF_OK.replace(
        "  PIN dout[0]",
        "  PIN rst\n    DIRECTION INPUT ;\n    USE SIGNAL ;\n"
        "    PORT\n      LAYER met2 ;\n"
        "        RECT 0.0000 20.0000 0.4000 20.4000 ;\n    END\n"
        "  END rst\n  PIN dout[0]")
    lib = LIB_OK.replace("    pin (clk) {",
                         "    pin (rst) { direction : input ; }\n"
                         "    pin (clk) {")
    p = make_kit(tmp_path, lef=lef, lib=lib, v="""module macro_a (clk, rst, dout);
  input clk, rst;
  output [1:0] dout;
endmodule
""")
    r = run(p)
    assert r.returncode == 0, r.stdout + r.stderr


# ───────────────── REFUSE — the four the brief names ───────────────────────

@pytest.mark.parametrize("ext", [".lef", ".lib", ".gds", ".v"])
def test_missing_view_is_refused(tmp_path, ext):
    p = make_kit(tmp_path)
    (p / "phase3/stage4/hardmacro" / f"macro_a{ext}").unlink()
    r = run(p)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "VIEW_MISSING" in rules(p)


@pytest.mark.parametrize("ext", [".lef", ".lib", ".gds", ".v"])
def test_zero_byte_view_is_refused(tmp_path, ext):
    p = make_kit(tmp_path)
    (p / "phase3/stage4/hardmacro" / f"macro_a{ext}").write_bytes(b"")
    r = run(p)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "VIEW_EMPTY" in rules(p)


def test_lef_outline_disagreeing_with_gds_is_refused(tmp_path):
    """The documented defect: a LEF claiming an abstract the body overflows.
    The placer reserves the LEF outline; a wider body overlaps its
    neighbours."""
    p = make_kit(tmp_path, lef=LEF_OK.replace("SIZE 100.0000 BY 50.0000",
                                              "SIZE 100.0000 BY 20.0000"))
    r = run(p)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "OUTLINE_MISMATCH" in rules(p)


def test_outline_inside_tolerance_still_passes(tmp_path):
    """0.5% on a 2% band — the gate must not be a bare equality test.

    The GDS is varied rather than the LEF SIZE: shrinking the abstract also
    strands the pins sitting on the shrunken edge, which is a different (and
    correct) finding and would not isolate this axis."""
    p = make_kit(tmp_path, gds=build_gds("macro_a", width_um=99.5))
    r = run(p)
    assert r.returncode == 0, r.stdout + r.stderr


def test_tolerance_band_is_honoured(tmp_path):
    p = make_kit(tmp_path, gds=build_gds("macro_a", width_um=95.0))
    assert run(p).returncode == 1                  # 5% > 2% default
    assert run(p, "--tol-pct", "10").returncode == 0


def test_pin_in_lef_and_not_in_liberty_is_refused(tmp_path):
    p = make_kit(tmp_path, lib=LIB_OK.replace(
        "    pin (clk) {\n      direction : input ;\n"
        "      capacitance : 0.004 ;\n    }\n", ""))
    r = run(p)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "SIGNAL_PIN_DISAGREE" in rules(p)


def test_pin_in_liberty_and_not_in_lef_is_refused(tmp_path):
    p = make_kit(tmp_path, lib=LIB_OK.replace(
        "    pin (clk) {", "    pin (scan_en) { direction : input ; }\n"
                           "    pin (clk) {"))
    assert run(p).returncode == 1
    assert "SIGNAL_PIN_DISAGREE" in rules(p)


def test_pin_in_lef_and_not_in_verilog_is_refused(tmp_path):
    p = make_kit(tmp_path, v=V_OK.replace(
        "    input  wire       clk,\n", ""))
    r = run(p)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "V_MISSING_SIGNAL_PIN" in rules(p)


def test_port_in_verilog_and_not_in_lef_is_refused(tmp_path):
    p = make_kit(tmp_path, v=V_OK.replace(
        "    input  wire       clk,",
        "    input  wire       clk,\n    input  wire       scan_en,"))
    assert run(p).returncode == 1
    assert "V_PORT_NOT_IN_LEF" in rules(p)


def test_power_pin_disagreement_between_lef_and_liberty_is_refused(tmp_path):
    """The PG exception is narrow: it excuses the VERILOG view only."""
    p = make_kit(tmp_path, lib=LIB_OK.replace(
        "    pg_pin (vgnd) { voltage_name : VGND ; "
        "pg_type : primary_ground ; }\n", ""))
    assert run(p).returncode == 1
    assert "PG_PIN_DISAGREE" in rules(p)


def test_power_pins_absent_from_verilog_are_accepted_and_recorded(tmp_path):
    """The stated exception, and the record that keeps it from widening."""
    p = make_kit(tmp_path)
    out = tmp_path / "r.json"
    assert run(p, "--json", str(out)).returncode == 0
    d = json.loads(out.read_text())
    assert d["summary"]["packages"][0]["interface"]["v_pg_ports_absent"] == \
        ["vgnd", "vpwr"]
    assert "V_PG_PORTS_ABSENT" in {f["rule"] for f in d["findings"]}


# ───────────────── REFUSE — the axes beyond the minimum ────────────────────

def test_hollow_gds_is_refused(tmp_path):
    """Size is not evidence of a layout: the measured 500-bytes-of-noise
    case that passed the analog gate's `st_size != 0` predicate."""
    p = make_kit(tmp_path, gds=b"NOTAGDS!" * 64)
    r = run(p)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "GDS_NO_GEOMETRY" in rules(p)


def test_gds_with_header_but_no_geometry_is_refused(tmp_path):
    p = make_kit(tmp_path, gds=build_gds("macro_a", with_geometry=False))
    assert run(p).returncode == 1
    assert "GDS_NO_GEOMETRY" in rules(p)


def test_identity_disagreement_between_abstract_views_is_refused(tmp_path):
    p = make_kit(tmp_path, v=V_OK.replace("module macro_a",
                                          "module macro_a_wrapper"))
    r = run(p)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "IDENTITY_DISAGREE" in rules(p)


def test_identity_disagreement_with_the_gds_top_cell_is_refused(tmp_path):
    p = make_kit(tmp_path, gds=build_gds("some_other_cell"))
    r = run(p)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "IDENTITY_GDS_DISAGREE" in rules(p)


def test_registration_offset_is_refused(tmp_path):
    """Width and height are the two numbers a misregistered pair still
    agrees on — the measured 30 um defect."""
    p = make_kit(tmp_path, gds=build_gds("macro_a", origin_um=(0.0, -30.32)))
    r = run(p)
    assert r.returncode == 1, r.stdout + r.stderr
    found = rules(p)
    assert "REGISTRATION_MISMATCH" in found
    assert "OUTLINE_MISMATCH" not in found      # the pair AGREES on w and h


def test_registration_offset_declared_by_foreign_is_accepted(tmp_path):
    """A declared offset is an explanation, not a defect."""
    lef = LEF_OK.replace("  ORIGIN 0 0 ;",
                         "  ORIGIN 0 0 ;\n  FOREIGN macro_a 0 -30.32 ;")
    p = make_kit(tmp_path, lef=lef,
                 gds=build_gds("macro_a", origin_um=(0.0, -30.32)))
    r = run(p)
    assert r.returncode == 0, r.stdout + r.stderr


def test_lef_without_size_is_refused(tmp_path):
    p = make_kit(tmp_path, lef=LEF_OK.replace("  SIZE 100.0000 BY 50.0000 ;\n",
                                              ""))
    assert run(p).returncode == 1
    assert "LEF_NO_SIZE" in rules(p)


def test_lef_without_macro_is_refused(tmp_path):
    p = make_kit(tmp_path, lef=LEF_OK.replace("MACRO macro_a", "# MACRO-less"))
    assert run(p).returncode == 1
    assert "LEF_NO_MACRO" in rules(p)


def test_lef_without_any_pin_is_refused(tmp_path):
    lef = "\n".join(l for l in LEF_OK.splitlines()
                    if not l.startswith(("  PIN", "  END ", "    DIRECTION",
                                         "    USE", "    PORT", "      LAYER",
                                         "        RECT", "    END")))
    p = make_kit(tmp_path, lef=lef)
    assert run(p).returncode == 1
    assert "LEF_NO_PIN" in rules(p)


def test_liberty_cell_mentioned_only_in_a_comment_is_refused(tmp_path):
    """The measured substring defect: `cancelled` satisfying `"cell" in
    text`. Comments are stripped BEFORE the declaration is looked for."""
    p = make_kit(tmp_path, lib="/* the release was cancelled */\n")
    assert run(p).returncode == 1
    assert "LIB_NO_CELL" in rules(p)


def test_verilog_module_mentioned_only_in_a_comment_is_refused(tmp_path):
    p = make_kit(tmp_path,
                 v="// this is a submodule placeholder mentioning module\n"
                   "wire x;\nassign x = 1'b0;\n")
    assert run(p).returncode == 1
    assert "V_NO_MODULE" in rules(p)


# ─────────── REFUSE — the `-pinonly` reachability axis (upstream §3) ───────
# `librelane/scripts/magic/lef.tcl` writes `lef write … -hide [-pinonly]`.
# Upstream ships that knob and checks NOTHING about its result; these are the
# parts of the outcome a delivered LEF can be held to on its own.

def test_pin_with_no_routable_area_is_refused(tmp_path):
    """A pin name with no place. The router is told the pin exists and given
    nowhere to land on it."""
    lef = LEF_OK.replace("""    PORT
      LAYER met2 ;
        RECT 0.0000 10.0000 0.4000 10.4000 ;
    END
""", "")
    p = make_kit(tmp_path, lef=lef)
    r = run(p)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PIN_NO_ROUTABLE_AREA" in rules(p)
    out = tmp_path / "r.json"
    run(p, "--json", str(out))
    d = json.loads(out.read_text())
    assert d["summary"]["packages"][0]["interface"][
        "pins_without_routable_area"] == ["clk"]


def test_supply_pin_with_no_routable_area_is_refused_too(tmp_path):
    """`lef.tcl` runs `lef nocheck $VDD_NETS $GND_NETS` — Magic is explicitly
    told NOT to check the supply pins it is about to write. So they are
    exactly the pins nothing upstream verifies."""
    lef = LEF_OK.replace("""    PORT
      LAYER met3 ;
        RECT 0.0000 0.0000 100.0000 2.0000 ;
    END
""", "")
    p = make_kit(tmp_path, lef=lef)
    assert run(p).returncode == 1
    assert "PIN_NO_ROUTABLE_AREA" in rules(p)


def test_pin_geometry_outside_the_outline_is_refused(tmp_path):
    p = make_kit(tmp_path, lef=LEF_OK.replace(
        "        RECT 0.0000 10.0000 0.4000 10.4000 ;",
        "        RECT 140.0000 10.0000 140.4000 10.4000 ;"))
    r = run(p)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PIN_GEOMETRY_OUTSIDE_OUTLINE" in rules(p)


def test_pin_geometry_overhanging_the_edge_is_accepted(tmp_path):
    """Pins legitimately reach, and overhang, the macro edge. The refusal is
    "shares no area with the outline at all", never a tolerance test."""
    p = make_kit(tmp_path, lef=LEF_OK.replace(
        "        RECT 0.0000 10.0000 0.4000 10.4000 ;",
        "        RECT -0.2000 10.0000 0.4000 10.4000 ;"))
    assert run(p).returncode == 0


def test_polygon_pin_geometry_counts_as_routable_area(tmp_path):
    p = make_kit(tmp_path, lef=LEF_OK.replace(
        "        RECT 0.0000 10.0000 0.4000 10.4000 ;",
        "        POLYGON 0.0 10.0 0.4 10.0 0.4 10.4 0.0 10.4 ;"))
    assert run(p).returncode == 0


def test_absent_obstructions_are_not_determined_not_a_plain_pass(tmp_path):
    """ADVISORY on purpose: mapping a LEF layer name onto a GDS layer number
    needs the tech LEF, which a kit does not carry. So it is disclosed on the
    verdict word and never silently accepted."""
    lef = "\n".join(l for l in LEF_OK.splitlines()
                     if l.strip() not in ("OBS",)
                     and "RECT 2.0000 4.0000 98.0000 46.0000" not in l
                     and l.strip() != "LAYER met1 ;")
    p = make_kit(tmp_path, lef=lef)
    r = run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS_OBSTRUCTION_NOT_DETERMINED]" in r.stdout
    assert "[PASS] digital_hardmacro_check" not in r.stdout
    assert "OBSTRUCTION_POLICY_NOT_DETERMINED" in rules(p)


def test_pins_are_scoped_to_one_macro_block(tmp_path):
    """A second MACRO in the same LEF must not merge its interface into the
    kit's. Unscoped, `scan_ctl`'s pins would read as the kit's own."""
    extra = """
MACRO scan_ctl
  CLASS BLOCK ;
  SIZE 5.0000 BY 5.0000 ;
  PIN scan_en
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER met2 ;
        RECT 0.0000 0.0000 0.4000 0.4000 ;
    END
  END scan_en
END scan_ctl
"""
    p = make_kit(tmp_path, lef=LEF_OK.replace("END LIBRARY", extra + "END LIBRARY"))
    r = run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    out = tmp_path / "r.json"
    run(p, "--json", str(out))
    d = json.loads(out.read_text())
    iface = d["summary"]["packages"][0]["interface"]
    assert "scan_en" not in iface["lef_signal"]
    assert iface["lef_signal"] == ["clk", "dout"]


# ───────────────── HONEST — nothing to check is not a pass ─────────────────

def test_absent_kit_is_not_determined_at_nonzero_rc(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT a pass" in (r.stdout + r.stderr)


def test_empty_hardmacro_dir_is_not_determined(tmp_path):
    (tmp_path / "phase3/stage4/hardmacro").mkdir(parents=True)
    r = run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    out = tmp_path / "r.json"
    run(tmp_path, "--json", str(out))
    d = json.loads(out.read_text())
    assert d["summary"]["verdict_tier"] == "NOT_DETERMINED"
    assert d["summary"]["reason"] == "no_hardmacro_package"


def test_unrelated_files_do_not_count_as_a_kit(tmp_path):
    hm = tmp_path / "phase3/stage4/hardmacro"
    hm.mkdir(parents=True)
    (hm / "README.md").write_text("nothing was delivered here\n")
    assert run(tmp_path).returncode == 2


def test_a_project_dir_that_is_not_a_directory_is_rc2(tmp_path):
    f = tmp_path / "notadir"
    f.write_text("x")
    assert run(f).returncode == 2


# ───────────────── TIER — disclosure, not a plain PASS ─────────────────────

def test_uncharacterised_liberty_is_disclosed_on_the_verdict_word(tmp_path):
    p = make_kit(tmp_path, lib="""library (macro_a_lib) {
  cell (macro_a) {
    area : 5000.0 ;
    pg_pin (vpwr) { pg_type : primary_power ; }
    pg_pin (vgnd) { pg_type : primary_ground ; }
    pin (clk) { direction : input ; }
    bus (dout) { direction : output ; }
  }
}
""")
    r = run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS_TIMING_UNCHARACTERISED]" in r.stdout
    assert "[PASS] digital_hardmacro_check" not in r.stdout
    assert "LIB_TIMING_UNCHARACTERISED" in rules(p)


def test_all_zero_timing_is_uncharacterised_not_a_plain_pass(tmp_path):
    p = make_kit(tmp_path, lib=LIB_OK.replace('"0.235"', '"0.0"')
                                     .replace('"0.211"', '"0.0"'))
    r = run(p)
    assert r.returncode == 0
    assert "[PASS_TIMING_UNCHARACTERISED]" in r.stdout


# ───────────────── multi-kit and reporting hygiene ─────────────────────────

def test_one_bad_kit_fails_the_whole_delivery(tmp_path):
    p = make_kit(tmp_path)
    make_kit(tmp_path, name="macro_b",
             lef=LEF_OK.replace("macro_a", "macro_b"),
             lib=LIB_OK.replace("macro_a", "macro_b"),
             v=V_OK.replace("macro_a", "macro_b"),
             gds=build_gds("macro_b", width_um=999.0))
    r = run(p)
    assert r.returncode == 1
    out = tmp_path / "r.json"
    run(p, "--json", str(out))
    d = json.loads(out.read_text())
    assert d["summary"]["total_packages"] == 2
    assert d["summary"]["failed"] == ["macro_b"]


def test_json_report_is_written_where_the_flow_names_it(tmp_path):
    """The flow invokes this gate as
    `digital_hardmacro_check . --json reports/phase3/digital_hardmacro.json`
    with cwd == the project, so the nested report dir must be created."""
    p = make_kit(tmp_path)
    r = subprocess.run(
        [sys.executable, str(PROG), ".", "--json",
         "reports/phase3/digital_hardmacro.json"],
        cwd=p, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    d = json.loads((p / "reports/phase3/digital_hardmacro.json").read_text())
    assert d["program"] == "digital_hardmacro_check"
    assert d["summary"]["pass"] is True


def test_chip_agnostic_source(tmp_path):
    """No chip / vendor / SKU literal in the program.

    Asked through the repo's OWN guard rather than a token list re-typed
    here. A second list is a second definition of "chip-agnostic", and the
    two drift: the first draft of this test carried its own list, which
    called the program dirty for citing the PDK a MEASUREMENT was taken on
    while `source_chip_agnostic_check` — the guard of record, which the
    sibling `analog_lef_gds_outline_check` passes with the same citation —
    called the identical bytes clean.
    """
    sys.path.insert(0, str(PROG.parent))
    import source_chip_agnostic_check as guard  # noqa: E402

    staged = tmp_path / "programs"
    staged.mkdir()
    (staged / PROG.name).write_text(PROG.read_text())
    rc = guard.main([str(tmp_path), "--json", str(tmp_path / "agn.json")])
    findings = json.loads((tmp_path / "agn.json").read_text()).get(
        "findings", [])
    assert rc == 0 and not findings, findings


# ───────────────── unit level — the parsers this gate owns ─────────────────

def test_bus_base_name_uses_the_lefs_own_busbitchars():
    assert mod.lef_bus_chars('BUSBITCHARS "<>" ;') == "<>"
    assert mod.base_name("a<3>", "<>") == "a"
    assert mod.base_name("a[3]", "[]") == "a"
    assert mod.base_name("clk", "[]") == "clk"


def test_lef_pin_block_does_not_run_past_its_own_end():
    parsed = mod.parse_lef(LEF_OK)
    assert parsed["signal"] == {"clk", "dout"}
    assert parsed["pg"] == {"vpwr", "vgnd"}


def test_liberty_pin_kinds_are_separated():
    parsed = mod.parse_liberty(LIB_OK)
    assert parsed["cell"] == "macro_a"
    assert parsed["signal"] == {"clk", "dout"}
    assert parsed["pg"] == {"vpwr", "vgnd"}


def test_verilog_reader_handles_both_header_styles():
    ansi = mod.parse_verilog(V_OK)
    assert ansi["module"] == "macro_a" and ansi["style"] == "ansi"
    assert ansi["ports"] == {"clk", "dout"}
    non = mod.parse_verilog(
        "module macro_a (clk, dout);\n input clk;\n output [1:0] dout;\n"
        "endmodule\n")
    assert non["style"] == "non-ansi" and non["ports"] == {"clk", "dout"}


def test_gds_top_cell_is_the_unreferenced_structure():
    assert mod.gds_top_cells(build_gds("macro_a")) == ["macro_a"]
    assert mod.gds_top_cells(b"not a gds") == []


def test_pin_geometry_reader_handles_rect_and_polygon():
    assert mod.pin_geometry("RECT 1 2 3 4 ;") == [(1.0, 2.0, 3.0, 4.0)]
    assert mod.pin_geometry("RECT 3 4 1 2 ;") == [(1.0, 2.0, 3.0, 4.0)]
    assert mod.pin_geometry(
        "POLYGON 0 0 2 0 2 1 0 1 ;") == [(0.0, 0.0, 2.0, 1.0)]
    assert mod.pin_geometry("DIRECTION INPUT ; USE SIGNAL ;") == []


def test_lef_reader_reports_obstructions_and_macro_count():
    parsed = mod.parse_lef(LEF_OK, "macro_a")
    assert parsed["has_obs"] is True
    assert parsed["macro_count"] == 1
    assert sorted(parsed["geometry"]) == ["clk", "dout", "vgnd", "vpwr"]


# ───────── WHICH RAIL a supply pin is, not merely that it is one ───────────
# MEASURED on the first real kit this flow ever produced. A DEF declaring
# `VDD + USE POWER` and `VSS + USE GROUND` yielded a Magic-written LEF that
# carried both `USE` tokens correctly and a producer-written Liberty that
# declared BOTH as `primary_power`. The PG NAME sets agreed, so every clause
# in this gate was green over two supply domains merged into one, in the view
# integration STA reads. `scripts/magic/lef.tcl` carries
# `lef nocheck $VDD_NETS $GND_NETS`, so nothing upstream of this gate looks at
# these pins at all.

def test_ground_declared_as_a_power_rail_is_refused(tmp_path):
    p = make_kit(tmp_path, lib=LIB_OK.replace(
        "pg_pin (vgnd) { voltage_name : VGND ; pg_type : primary_ground ; }",
        "pg_pin (vgnd) { voltage_name : VGND ; pg_type : primary_power ; }"))
    assert run(p).returncode == 1
    assert "PG_TYPE_DISAGREE" in rules(p)
    assert "PG_PIN_DISAGREE" not in rules(p), \
        "the NAME sets agree; this must be caught on the RAIL axis alone"


def test_power_declared_as_a_ground_rail_is_refused(tmp_path):
    """Both directions, so the clause is not a one-sided string test."""
    p = make_kit(tmp_path, lib=LIB_OK.replace(
        "pg_pin (vpwr) { voltage_name : VPWR ; pg_type : primary_power ; }",
        "pg_pin (vpwr) { voltage_name : VPWR ; pg_type : primary_ground ; }"))
    assert run(p).returncode == 1
    assert "PG_TYPE_DISAGREE" in rules(p)


def test_pg_pin_without_a_pg_type_is_not_read_as_agreement(tmp_path):
    """NOTHING TO CHECK IS NOT A PASS, on this axis too: a `pg_pin` that does
    not say which rail it is has not agreed with the LEF — it has said
    nothing, and an unmodelled token must not pass by being unrecognised."""
    p = make_kit(tmp_path, lib=LIB_OK.replace(
        "pg_pin (vgnd) { voltage_name : VGND ; pg_type : primary_ground ; }",
        "pg_pin (vgnd) { voltage_name : VGND ; }"))
    assert run(p).returncode == 1
    assert "PG_TYPE_DISAGREE" in rules(p)


def test_unmodelled_pg_type_token_is_not_read_as_agreement(tmp_path):
    """And it is reported as UNDETERMINED, not as a conflict. A token this
    gate does not model does not license the claim that the Liberty said the
    opposite rail — it said something this gate cannot read, and the report
    has to say that and not more."""
    p = make_kit(tmp_path, lib=LIB_OK.replace(
        "pg_type : primary_ground ;", "pg_type : not_a_liberty_token ;"))
    out = tmp_path / "r.json"
    assert run(p, "--json", str(out)).returncode == 1
    msg = [f["message"] for f in json.loads(out.read_text())["findings"]
           if f["rule"] == "PG_TYPE_DISAGREE"]
    assert msg, "PG_TYPE_DISAGREE did not fire"
    assert "NOT established" in msg[0]
    assert "Liberty says pg_type not_a_liberty_token" not in msg[0]


def test_agreeing_rails_are_not_refused(tmp_path):
    """The negative control. The shipped fixture already declares vpwr as
    primary_power and vgnd as primary_ground; the clause must be silent."""
    p = make_kit(tmp_path)
    assert run(p).returncode == 0
    assert "PG_TYPE_DISAGREE" not in rules(p)


def test_a_kit_with_no_supply_pin_at_all_is_not_touched_by_the_rail_clause(
        tmp_path):
    """A kit whose LEF and Liberty both declare no supply pin has NOTHING for
    this clause to compare, and it must not invent a disagreement. Recorded
    because it is the shape of every real kit in this tree's corpus today."""
    lef = LEF_OK
    for pin in ("vpwr", "vgnd"):
        head = lef.index(f"  PIN {pin}")
        tail = lef.index(f"  END {pin}") + len(f"  END {pin}\n")
        lef = lef[:head] + lef[tail:]
    lib = LIB_OK
    for line in ("    pg_pin (vpwr) { voltage_name : VPWR ; "
                 "pg_type : primary_power ; }\n",
                 "    pg_pin (vgnd) { voltage_name : VGND ; "
                 "pg_type : primary_ground ; }\n"):
        lib = lib.replace(line, "")
    p = make_kit(tmp_path, lef=lef, lib=lib)
    assert run(p).returncode == 0
    assert "PG_TYPE_DISAGREE" not in rules(p)


def test_the_rail_axis_is_recorded_on_a_passing_report(tmp_path):
    """Both halves of the comparison in the record, so a reader can see the
    clause had something to look at and is not vacuously green."""
    p = make_kit(tmp_path)
    out = tmp_path / "r.json"
    assert run(p, "--json", str(out)).returncode == 0
    i = json.loads(out.read_text())["summary"]["packages"][0]["interface"]
    assert i["lef_pg_kind"] == {"vgnd": "ground", "vpwr": "power"}
    assert i["lib_pg_type"] == {"vgnd": "primary_ground",
                                "vpwr": "primary_power"}


def test_verdict_tier_never_reads_pass_on_a_refused_kit(tmp_path):
    """A consumer keying on `verdict_tier` alone read the word "PASS" out of
    a report whose `passed` was false, because the field defaulted to it and
    was only ever overwritten on the pass paths."""
    p = make_kit(tmp_path, v=V_OK.replace("clk", "clock"))
    out = tmp_path / "r.json"
    assert run(p, "--json", str(out)).returncode == 1
    d = json.loads(out.read_text())
    assert d["passed"] is False
    assert not d["verdict_tier"].startswith("PASS")
    assert d["summary"]["verdict_tier"] == d["verdict_tier"]
