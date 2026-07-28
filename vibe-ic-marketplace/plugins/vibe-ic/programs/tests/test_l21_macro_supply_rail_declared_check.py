#!/usr/bin/env python3
"""Smoke tests for l21_macro_supply_rail_declared_check.

EXPLICIT NEGATIVE CONTROL. Every behavioural test asserts BOTH directions:
a deliberately-gutted L21 must FAIL (rc=1) and the well-formed sibling must
PASS (rc=0). A test that cannot fail proves nothing.

All fixtures are SYNTHESIZED neutral data — invented macro names, invented pin
names, invented net names. No real design's files are copied and no PDK, vendor
or part number appears anywhere.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
GATE = PROGRAMS / "l21_macro_supply_rail_declared_check.py"

# --- SYNTHESIZED neutral fixtures ------------------------------------------ #
# A hard macro (CLASS BLOCK) with one USE POWER and one USE GROUND pin, plus a
# signal pin so the parse has to discriminate. Names are invented.
MACRO_LEF = """VERSION 5.7 ;
MACRO NEUTRAL_BLOCK_A
  CLASS BLOCK ;
  SIZE 40.0 BY 20.0 ;
  PIN DATA_Q0
    DIRECTION OUTPUT ;
    USE SIGNAL ;
    PORT
      LAYER MX1 ;
        RECT 1.0 1.0 1.4 1.4 ;
    END
  END DATA_Q0
  PIN SUPPLY_HI_A
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER MX1 ;
        RECT 0.0 0.0 40.0 0.5 ;
    END
  END SUPPLY_HI_A
  PIN SUPPLY_LO_A
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER MX1 ;
        RECT 0.0 19.5 40.0 20.0 ;
    END
  END SUPPLY_LO_A
END NEUTRAL_BLOCK_A
END LIBRARY
"""

# A std-cell-shaped LEF (CLASS CORE) that ALSO types PG pins. It must be
# ignored: gating on it would make every design with a std-cell LEF fail.
STDCELL_LEF = """VERSION 5.7 ;
MACRO NEUTRAL_CORE_CELL
  CLASS CORE ;
  SIZE 1.0 BY 2.0 ;
  PIN CORE_SUPPLY_HI
    DIRECTION INOUT ;
    USE POWER ;
  END CORE_SUPPLY_HI
  PIN CORE_SUPPLY_LO
    DIRECTION INOUT ;
    USE GROUND ;
  END CORE_SUPPLY_LO
END NEUTRAL_CORE_CELL
END LIBRARY
"""

RTL_INSTANTIATING_MACRO = """module neutral_top (
  input  wire clk_a,
  input  wire rst_na,
  output wire [3:0] q_a
);
  NEUTRAL_BLOCK_A u_block_a (
    .DATA_Q0 (q_a[0])
  );
  assign q_a[3:1] = 3'b000;
endmodule
"""

GUTTED_L21 = {
    "doc_id": "L21",
    "doc_name": "L21_POWER_INTENT",
    "fields": {
        "power_domains": [],
        "isolation_cells": [],
        "level_shifters": [],
        "upf_path": None,
    },
    "extraction_status": "NOT_YET_EXTRACTED",
    "emitted_by": "test_fixture.skeleton",
}

WELLFORMED_L21 = {
    "doc_id": "L21",
    "doc_name": "L21_POWER_INTENT",
    "fields": {
        "power_domains": [
            {
                "name": "PD_MAIN_A",
                "power_net": "SUPPLY_HI_A",
                "ground_net": "SUPPLY_LO_A",
                "switchable": False,
                "retention": False,
            }
        ],
        "isolation_cells": [],
        "level_shifters": [],
        "upf_path": "phase1/generated_docs/neutral_top.upf",
    },
    "extraction_status": "EXTRACTED",
    "emitted_by": "test_fixture.wellformed",
}


def _run(project: Path):
    proc = subprocess.run(
        [sys.executable, str(GATE), str(project)],
        capture_output=True, text=True, timeout=60)
    return proc.returncode, (proc.stdout + proc.stderr)


def _build(tmp_path: Path, l21: dict, *, with_macro=True, with_rtl=True,
           extra_lef: str | None = None) -> Path:
    project = tmp_path / "proj"
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    (project / "phase1" / "generated_docs" / "L21_POWER_INTENT.json").write_text(
        json.dumps(l21, indent=1))
    if with_macro:
        d = project / "input" / "pdk_local" / "neutral_vendor"
        d.mkdir(parents=True, exist_ok=True)
        (d / "neutral_block_a.lef").write_text(MACRO_LEF)
        if extra_lef is not None:
            (d / "neutral_core_cells.lef").write_text(extra_lef)
    if with_rtl:
        r = project / "phase2" / "stage1" / "rtl"
        r.mkdir(parents=True, exist_ok=True)
        (r / "neutral_top.v").write_text(RTL_INSTANTIATING_MACRO)
    return project


# --------------------------------------------------------------------------- #
# THE NEGATIVE CONTROL PAIR — both directions asserted explicitly.
# --------------------------------------------------------------------------- #
def test_gutted_l21_fails_and_wellformed_l21_passes(tmp_path):
    """NEGATIVE CONTROL: identical design, only L21 differs."""
    gutted = _build(tmp_path / "a", GUTTED_L21)
    rc_bad, out_bad = _run(gutted)
    assert rc_bad == 1, (
        "gutted L21 (power_domains=[]) MUST FAIL — the design's own macro LEF "
        f"types SUPPLY_HI_A/SUPPLY_LO_A as USE POWER/GROUND. got rc={rc_bad}\n"
        f"{out_bad}")
    assert "L21-1" in out_bad
    assert "SUPPLY_HI_A" in out_bad and "SUPPLY_LO_A" in out_bad
    assert "TritonRoute" in out_bad, "the finding must name the real consequence"

    good = _build(tmp_path / "b", WELLFORMED_L21)
    rc_ok, out_ok = _run(good)
    assert rc_ok == 0, (
        "well-formed L21 declaring both rails MUST PASS. "
        f"got rc={rc_ok}\n{out_ok}")
    assert "[PASS]" in out_ok


def test_partial_l21_still_fails_on_the_missing_rail(tmp_path):
    """Declaring only the POWER rail must still FAIL on the GROUND pin —
    the gate matches per-pin, per-use, not 'any rail declared'."""
    partial = json.loads(json.dumps(WELLFORMED_L21))
    partial["fields"]["power_domains"][0].pop("ground_net")
    project = _build(tmp_path, partial)
    rc, out = _run(project)
    assert rc == 1, f"half-declared L21 MUST FAIL. got rc={rc}\n{out}"
    assert "SUPPLY_LO_A" in out
    assert "SUPPLY_HI_A" not in out.split("L21-1")[-1].split("\n")[0]


def test_wrong_use_class_does_not_satisfy_the_pin(tmp_path):
    """A rail declared with the WRONG use must not satisfy the pin — this
    mirrors _macro_supply_gc_plan's same-use name-equality match."""
    swapped = json.loads(json.dumps(WELLFORMED_L21))
    swapped["fields"]["power_domains"][0]["power_net"] = "SUPPLY_LO_A"
    swapped["fields"]["power_domains"][0]["ground_net"] = "SUPPLY_HI_A"
    project = _build(tmp_path, swapped)
    rc, out = _run(project)
    assert rc == 1, f"use-swapped rails MUST FAIL. got rc={rc}\n{out}"


def test_stdcell_class_core_lef_is_not_treated_as_a_hard_macro(tmp_path):
    """NEGATIVE CONTROL for the discriminator: a CLASS CORE cell that types PG
    pins must NOT make a well-formed L21 fail."""
    project = _build(tmp_path, WELLFORMED_L21, extra_lef=STDCELL_LEF)
    rc, out = _run(project)
    assert rc == 0, (
        "a CLASS CORE std cell's PG pins must not be demanded of L21. "
        f"got rc={rc}\n{out}")
    assert "CORE_SUPPLY_HI" not in out


def test_design_with_no_hard_macro_skips(tmp_path):
    """A pure-digital design with no hard macro must SKIP (rc=2), never fail —
    this is what keeps the gate at zero false positives on the fleet."""
    project = _build(tmp_path, GUTTED_L21, with_macro=False)
    rc, out = _run(project)
    assert rc == 2, f"no-macro design MUST SKIP. got rc={rc}\n{out}"
    assert "SKIP" in out


def test_uninstantiated_macro_skips(tmp_path):
    """A staged macro that the design never instantiates is out of scope."""
    rtl_without_macro = "module neutral_top(input wire clk_a); endmodule\n"
    project = _build(tmp_path, GUTTED_L21)
    (project / "phase2" / "stage1" / "rtl" / "neutral_top.v").write_text(
        rtl_without_macro)
    rc, out = _run(project)
    assert rc == 2, f"uninstantiated macro MUST SKIP. got rc={rc}\n{out}"


def test_waiver_discloses_instead_of_hiding(tmp_path):
    """The waiver converts FAIL -> PASS_WITH_WAIVERS but must still PRINT the
    finding. Disclosed beats invisible."""
    project = _build(tmp_path, GUTTED_L21)
    (project / "waivers.json").write_text(json.dumps({
        "l21_macro_supply_rail_absent_disclosed":
            "This synthesized fixture deliberately provides no rail for the "
            "macro's dedicated supply; the gap is disclosed for review."}))
    rc, out = _run(project)
    assert rc == 0, f"waived run must pass. got rc={rc}\n{out}"
    assert "PASS_WITH_WAIVERS" in out
    assert "SUPPLY_HI_A" in out, "a waiver must disclose, not hide"

    # ...and a too-short waiver must NOT work (the negative control of the
    # waiver itself).
    (project / "waivers.json").write_text(json.dumps({
        "l21_macro_supply_rail_absent_disclosed": "nope"}))
    rc2, _out2 = _run(project)
    assert rc2 == 1, "a <40-char waiver must not suppress the finding"


def test_isolation_and_level_shifter_typed_shape(tmp_path):
    """L21-3: declared isolation/level-shifter entries must be actionable.
    Both directions asserted."""
    bad = json.loads(json.dumps(WELLFORMED_L21))
    bad["fields"]["isolation_cells"] = [{"cell": "NEUTRAL_ISO_A"}]
    project_bad = _build(tmp_path / "bad", bad)
    rc_bad, out_bad = _run(project_bad)
    assert rc_bad == 1, f"untyped isolation cell MUST FAIL. got {rc_bad}\n{out_bad}"
    assert "clamp_value" in out_bad

    good = json.loads(json.dumps(WELLFORMED_L21))
    good["fields"]["isolation_cells"] = [
        {"cell": "NEUTRAL_ISO_A", "domain": "PD_MAIN_A", "clamp_value": 0}]
    good["fields"]["level_shifters"] = [
        {"cell": "NEUTRAL_LS_A", "from_domain": "PD_MAIN_A",
         "to_domain": "PD_MAIN_A"}]
    project_good = _build(tmp_path / "good", good)
    rc_ok, out_ok = _run(project_good)
    assert rc_ok == 0, f"typed isolation/LS MUST PASS. got {rc_ok}\n{out_ok}"


def test_json_report_is_written(tmp_path):
    project = _build(tmp_path, GUTTED_L21)
    out_json = tmp_path / "rep.json"
    proc = subprocess.run(
        [sys.executable, str(GATE), str(project), "--json", str(out_json)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    doc = json.loads(out_json.read_text())
    assert doc["verdict"] == "FAIL"
    assert any(f["rule"] == "L21-1" for f in doc["findings"])
    assert doc["macro_pg_pins"]["NEUTRAL_BLOCK_A"]


def test_gate_reuses_the_consumers_own_lef_parser():
    """Emitter/checker doctrine: the gate must delegate to the backend's own
    _parse_macro_supply_pins so the two can never drift."""
    sys.path.insert(0, str(PROGRAMS))
    import importlib
    mod = importlib.import_module("l21_macro_supply_rail_declared_check")
    assert mod._consumer_parse_macro_supply_pins is not None, (
        "the gate must import phase3_one_shot_runner._parse_macro_supply_pins")
    parsed = mod._parse_macro_supply_pins(MACRO_LEF)
    assert parsed["NEUTRAL_BLOCK_A"] == [
        ("SUPPLY_HI_A", "POWER"), ("SUPPLY_LO_A", "GROUND")]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
