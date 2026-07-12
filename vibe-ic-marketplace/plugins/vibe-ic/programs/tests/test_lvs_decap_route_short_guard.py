"""Unit tests for `decap_route_short_guard.py`.

Pin the deterministic DEF+LEF half of the post-route decap-under-signal-route
SHORT guard: LEF SIZE parsing, signal-MET1 path-walking (with the `*` wildcard
and SPECIALNETS exclusion), plate-region conflict detection, and the 1:1
same-width `DECAPn -> FILLn` swap that clears the short while preserving the
COMPONENTS count. Pure text in/out — no KLayout, no PDK, chip-AGNOSTIC synthetic
fixtures (generic `guardtest` top, generic nets/cells).
"""
import importlib

import pytest

mod = importlib.import_module("decap_route_short_guard")


# A chip-agnostic std-cell LEF: a decap + its same-width plain FILL twin + one
# ordinary logic cell. Only SIZE matters to the guard (DECAP8 <-> FILL8 width).
LEF = """\
MACRO DECAP8
  CLASS CORE ;
  SIZE 5.28 BY 5.04 ;
  PIN VDD
    DIRECTION INOUT ; USE POWER ;
  END VDD
END DECAP8
MACRO FILL8
  CLASS CORE SPACER ;
  SIZE 5.28 BY 5.04 ;
END FILL8
MACRO NAND2D1
  CLASS CORE ;
  SIZE 2.64 BY 5.04 ;
END NAND2D1
"""

# A routed DEF: D1 (DECAP8) sits under a signal MET1 wire (CONFLICT); D2
# (DECAP8) is far away (clean); F1 (FILL8) is not a decap (ignored). A VSS
# FOLLOWPIN rail crosses D1 in SPECIALNETS — it MUST NOT count (a rail over a
# decap is expected; only a SIGNAL wire over the plate is a short).
CONFLICT_DEF = """\
VERSION 5.8 ;
DESIGN guardtest ;
UNITS DISTANCE MICRONS 1000 ;

COMPONENTS 3 ;
    - D1 DECAP8 + PLACED ( 5000 20000 ) N ;
    - D2 DECAP8 + PLACED ( 40000 20000 ) N ;
    - F1 FILL8 + PLACED ( 60000 20000 ) N ;
END COMPONENTS

SPECIALNETS 1 ;
    - VSS ( * VGND )
      + ROUTED MET1 480 + SHAPE FOLLOWPIN ( 0 20200 ) ( 90000 * )
      + USE GROUND ;
END SPECIALNETS

NETS 1 ;
    - sig1 ( D1 A ) ( D2 B )
      + ROUTED MET1 ( 6000 22000 ) ( 9000 22000 ) ;
END NETS

END DESIGN
"""

# Same placements, but the signal wire is nowhere near either decap.
CLEAN_DEF = CONFLICT_DEF.replace(
    "( 6000 22000 ) ( 9000 22000 )", "( 6000 90000 ) ( 9000 90000 )")


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_parse_lef_master_widths():
    w = mod.parse_lef_master_widths([LEF])
    assert w["DECAP8"] == pytest.approx(5.28)
    assert w["FILL8"] == pytest.approx(5.28)
    assert w["NAND2D1"] == pytest.approx(2.64)


def test_parse_master_heights():
    h = mod.parse_master_heights([LEF])
    assert h["DECAP8"] == pytest.approx(5.04)
    assert h["FILL8"] == pytest.approx(5.04)


def test_fill_for_decap_exact_and_unknown():
    w = mod.parse_lef_master_widths([LEF])
    assert mod._fill_for_decap("DECAP8", w) == ["FILL8"]
    # a non-decap master -> None
    assert mod._fill_for_decap("NAND2D1", w) is None


def test_parse_components_finds_decaps_only_via_re():
    comps = mod.parse_components(CONFLICT_DEF)
    names = {c["name"]: c["master"] for c in comps}
    assert names == {"D1": "DECAP8", "D2": "DECAP8", "F1": "FILL8"}
    d1 = next(c for c in comps if c["name"] == "D1")
    assert (d1["x"], d1["y"], d1["orient"]) == (5000, 20000, "N")


def test_parse_signal_m1_wires_excludes_specialnets():
    # 1000 dbu/µm. Only the NETS MET1 segment is a signal wire; the SPECIALNETS
    # FOLLOWPIN rail is NOT parsed (parse only reads the `\\nNETS ` block).
    wires = mod.parse_signal_m1_wires(CONFLICT_DEF, 1000.0)
    assert len(wires) == 1
    x1, y1, x2, y2 = wires[0]
    # half-width 0.14 expansion around (6,22)-(9,22)
    assert x1 == pytest.approx(6.0 - 0.14)
    assert x2 == pytest.approx(9.0 + 0.14)
    assert y1 == pytest.approx(22.0 - 0.14)
    assert y2 == pytest.approx(22.0 + 0.14)


def test_find_conflicts_one_hit():
    comps = mod.parse_components(CONFLICT_DEF)
    heights = mod.parse_master_heights([LEF])
    for c in comps:
        c["h"] = heights.get(c["master"])
    widths = mod.parse_lef_master_widths([LEF])
    wires = mod.parse_signal_m1_wires(CONFLICT_DEF, 1000.0)
    conflicts = mod.find_conflicts(comps, widths, wires, 1000.0, 0.8)
    assert len(conflicts) == 1
    assert conflicts[0][0]["name"] == "D1"


def test_find_conflicts_clean_zero():
    comps = mod.parse_components(CLEAN_DEF)
    heights = mod.parse_master_heights([LEF])
    for c in comps:
        c["h"] = heights.get(c["master"])
    widths = mod.parse_lef_master_widths([LEF])
    wires = mod.parse_signal_m1_wires(CLEAN_DEF, 1000.0)
    assert mod.find_conflicts(comps, widths, wires, 1000.0, 0.8) == []


def test_build_fixed_def_swaps_only_the_conflict():
    comps = mod.parse_components(CONFLICT_DEF)
    heights = mod.parse_master_heights([LEF])
    for c in comps:
        c["h"] = heights.get(c["master"])
    widths = mod.parse_lef_master_widths([LEF])
    wires = mod.parse_signal_m1_wires(CONFLICT_DEF, 1000.0)
    conflicts = mod.find_conflicts(comps, widths, wires, 1000.0, 0.8)
    fixed, repl, removed = mod.build_fixed_def(CONFLICT_DEF, conflicts, widths)
    assert removed == []
    assert len(repl) == 1 and repl[0]["inst"] == "D1"
    assert repl[0]["from"] == "DECAP8" and repl[0]["to"] == "FILL8"
    # D1 became FILL8; D2 stays DECAP8; component count unchanged (1:1 swap).
    fc = mod.parse_components(fixed)
    fnames = {c["name"]: c["master"] for c in fc}
    assert fnames == {"D1": "FILL8", "D2": "DECAP8", "F1": "FILL8"}
    assert "COMPONENTS 3 ;" in fixed


def test_run_check_exit3_on_conflict(tmp_path):
    d = _write(tmp_path, "in.def", CONFLICT_DEF)
    lf = _write(tmp_path, "cells.lef", LEF)
    rc = mod.run(str(d), [str(lf)], None,
                 str(tmp_path / "r.json"), 0.8, check_only=True)
    assert rc == 3


def test_run_check_exit0_on_clean(tmp_path):
    d = _write(tmp_path, "in.def", CLEAN_DEF)
    lf = _write(tmp_path, "cells.lef", LEF)
    rc = mod.run(str(d), [str(lf)], None,
                 str(tmp_path / "r.json"), 0.8, check_only=True)
    assert rc == 0


def test_run_repair_writes_fixed_def(tmp_path):
    d = _write(tmp_path, "in.def", CONFLICT_DEF)
    lf = _write(tmp_path, "cells.lef", LEF)
    out = tmp_path / "fixed.def"
    rc = mod.run(str(d), [str(lf)], str(out),
                 str(tmp_path / "r.json"), 0.8, check_only=False)
    assert rc == 0
    fixed = out.read_text()
    fnames = {c["name"]: c["master"] for c in mod.parse_components(fixed)}
    assert fnames["D1"] == "FILL8"     # the conflicting decap was swapped
    assert fnames["D2"] == "DECAP8"    # the clean decap is preserved


def test_run_repair_clean_is_noop_swap(tmp_path):
    d = _write(tmp_path, "in.def", CLEAN_DEF)
    lf = _write(tmp_path, "cells.lef", LEF)
    out = tmp_path / "fixed.def"
    rc = mod.run(str(d), [str(lf)], str(out),
                 str(tmp_path / "r.json"), 0.8, check_only=False)
    assert rc == 0
    fnames = {c["name"]: c["master"] for c in mod.parse_components(out.read_text())}
    assert fnames == {"D1": "DECAP8", "D2": "DECAP8", "F1": "FILL8"}
