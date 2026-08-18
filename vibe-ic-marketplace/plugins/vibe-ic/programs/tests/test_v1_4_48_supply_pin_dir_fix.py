"""FLOOR-PNR-BUFFER — supply-pin DIRECTION hygiene (ibex CPU-scale commercial PDK).

MEASURED root cause (proven in-container on the running image, NOT assumed):
a commercial std-cell LEF omits `DIRECTION` on its `USE POWER`/`USE GROUND`
pins. ODB defaults a direction-less PIN to IoType INPUT, and OpenROAD's ODB
buffer-input counter (`dbInsertBuffer::checkAndCreateBuffer`) filters by IoType
ONLY (not SigType), so every buffer master looks like it has >=3 inputs
(A + VDD + VSS) and is rejected (ODB-1207). ALL buffer insertion in
`repair_design`/`repair_timing` then fails (ODB-1205) -> high-fanout nets stay
unbuffered -> detailed route cannot legalize the flat monster net -> systematic
same-layer shorts even at 30.9% util (ibex stand-in: 6253 MET2 shorts,
non-converging). In-container A/B on the real `repair_design` command: stock
cell LEF -> 0 buffers inserted (ODB-1207/1205); the SAME LEF with `DIRECTION
INOUT` injected on supply pins -> 10 buffers inserted, 1 net repaired.

Fix: `_discover_supply_pin_dir_fix` stages a corrected cell LEF under
phase3/pdk_stage/ with `DIRECTION INOUT` on every USE POWER/GROUND pin that
lacked a direction (the real PDK LEF is untouched). chip/PDK-AGNOSTIC: keyed
purely on `USE POWER`/`USE GROUND` + absent DIRECTION, no cell/vendor/metal
literal. These tests use a SYNTHETIC LEF with different cell/pin names than the
real PDK's to prove genericity.
"""
import re
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# supply pins WITHOUT a DIRECTION (the failing shape) — arbitrary cell/pin names
_LEF_NO_DIR = """\
MACRO ZZBUF
  CLASS CORE ;
  SIZE 1.0 BY 5.0 ;
  PIN IN
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER MET1 ;
        RECT 0 0 0.1 0.1 ;
    END
  END IN
  PIN OUT
    DIRECTION OUTPUT ;
    USE SIGNAL ;
    PORT
      LAYER MET1 ;
        RECT 0.2 0 0.3 0.1 ;
    END
  END OUT
  PIN VPWR
    USE POWER ;
    PORT
      LAYER MET1 ;
        RECT 0 0.9 1.0 1.1 ;
    END
  END VPWR
  PIN VGND
    USE GROUND ;
    PORT
      LAYER MET1 ;
        RECT 0 -0.1 1.0 0.1 ;
    END
  END VGND
END ZZBUF
"""

# supply pins that ALREADY carry a direction (sky130-like) — must be a no-op
_LEF_WITH_DIR = """\
MACRO QQBUF
  CLASS CORE ;
  PIN IN
    DIRECTION INPUT ;
    USE SIGNAL ;
  END IN
  PIN OUT
    DIRECTION OUTPUT ;
    USE SIGNAL ;
  END OUT
  PIN VPWR
    DIRECTION INOUT ;
    USE POWER ;
  END VPWR
  PIN VGND
    DIRECTION INOUT ;
    USE GROUND ;
  END VGND
END QQBUF
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def _supply_pin_input_count(lef_text: str, master: str) -> int:
    """Mirror ODB's IoType-only input counter over one MACRO. A direction-less
    PIN counts as INPUT (ODB default); a supply pin with USE POWER/GROUND and no
    DIRECTION is exactly the mis-count the fix removes."""
    mblk = re.search(r"(?ms)^MACRO\s+" + re.escape(master) +
                     r"\s*\n(.*?)^END\s+" + re.escape(master) + r"\s*$", lef_text)
    assert mblk, f"macro {master} not found"
    body = mblk.group(1)
    n_in = 0
    for pm in re.finditer(r"(?ms)^\s*PIN\s+(\S+)\s*\n(.*?)^\s*END\s+\1\s*$", body):
        dirm = re.search(r"(?m)^\s*DIRECTION\s+(\S+)", pm.group(2))
        io = dirm.group(1).upper() if dirm else "INPUT"   # ODB default
        if io == "INPUT":                                 # checkAndCreateBuffer test
            n_in += 1
    return n_in


def test_injects_direction_on_directionless_supply_pins(tmp_path):
    lef = _write(tmp_path, "cell.lef", _LEF_NO_DIR)
    out, notes = R._discover_supply_pin_dir_fix(tmp_path, lef)
    assert out != lef, "expected a staged corrected LEF"
    assert notes and "supply-pin-dir-fix" in notes[0]
    txt = out.read_text()
    # both supply pins now carry DIRECTION INOUT
    vpwr = re.search(r"(?ms)^\s*PIN\s+VPWR\s*\n(.*?)^\s*END\s+VPWR", txt).group(1)
    vgnd = re.search(r"(?ms)^\s*PIN\s+VGND\s*\n(.*?)^\s*END\s+VGND", txt).group(1)
    assert re.search(r"(?m)^\s*DIRECTION\s+INOUT\s*;", vpwr)
    assert re.search(r"(?m)^\s*DIRECTION\s+INOUT\s*;", vgnd)


def test_before_fix_miscounts_inputs_after_fix_counts_one(tmp_path):
    # BEFORE: A + VDD + VSS all read as INPUT -> 3 (buffer rejected by ODB)
    assert _supply_pin_input_count(_LEF_NO_DIR, "ZZBUF") == 3
    lef = _write(tmp_path, "cell.lef", _LEF_NO_DIR)
    out, _ = R._discover_supply_pin_dir_fix(tmp_path, lef)
    # AFTER: supply pins are INOUT, only the true signal input remains -> 1
    assert _supply_pin_input_count(out.read_text(), "ZZBUF") == 1


def test_signal_pins_untouched(tmp_path):
    lef = _write(tmp_path, "cell.lef", _LEF_NO_DIR)
    out, _ = R._discover_supply_pin_dir_fix(tmp_path, lef)
    txt = out.read_text()
    # the signal pins keep their ORIGINAL single direction (no duplicate injected)
    inb = re.search(r"(?ms)^\s*PIN\s+IN\s*\n(.*?)^\s*END\s+IN", txt).group(1)
    outb = re.search(r"(?ms)^\s*PIN\s+OUT\s*\n(.*?)^\s*END\s+OUT", txt).group(1)
    assert len(re.findall(r"(?m)^\s*DIRECTION\s", inb)) == 1
    assert re.search(r"DIRECTION\s+INPUT", inb)
    assert len(re.findall(r"(?m)^\s*DIRECTION\s", outb)) == 1
    assert re.search(r"DIRECTION\s+OUTPUT", outb)


def test_noop_when_supply_pins_already_have_direction(tmp_path):
    # sky130-like: supply pins declare DIRECTION INOUT -> nothing to fix.
    lef = _write(tmp_path, "cell.lef", _LEF_WITH_DIR)
    out, notes = R._discover_supply_pin_dir_fix(tmp_path, lef)
    assert out == lef, "must return the ORIGINAL path (byte-identical no-op)"
    assert notes == []


def test_noop_when_no_supply_pins(tmp_path):
    lef = _write(tmp_path, "cell.lef",
                 "MACRO L\n  PIN A\n    DIRECTION INPUT ;\n    USE SIGNAL ;\n"
                 "  END A\nEND L\n")
    out, notes = R._discover_supply_pin_dir_fix(tmp_path, lef)
    assert out == lef
    assert notes == []


def test_staged_under_pdk_stage_with_lef_ext(tmp_path):
    lef = _write(tmp_path, "cell.lef", _LEF_NO_DIR)
    out, _ = R._discover_supply_pin_dir_fix(tmp_path, lef)
    assert out.suffix == ".lef"
    assert out.parent == tmp_path / "phase3" / "pdk_stage"


def test_idempotent(tmp_path):
    lef = _write(tmp_path, "cell.lef", _LEF_NO_DIR)
    out1, notes1 = R._discover_supply_pin_dir_fix(tmp_path, lef)
    assert notes1
    # re-running on the already-corrected LEF is a no-op
    out2, notes2 = R._discover_supply_pin_dir_fix(tmp_path, out1)
    assert out2 == out1
    assert notes2 == []


def test_missing_or_none_cell_lef_is_safe(tmp_path):
    assert R._discover_supply_pin_dir_fix(tmp_path, None) == (None, [])
    ghost = tmp_path / "nope.lef"
    assert R._discover_supply_pin_dir_fix(tmp_path, ghost) == (ghost, [])
