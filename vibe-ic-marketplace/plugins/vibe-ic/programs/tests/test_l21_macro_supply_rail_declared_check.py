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

# THE SAME MACRO, written by a tool instead of by hand (vibe-ic#774). `magic`'s
# `lef write` emits neither DIRECTION nor USE on any PIN, so an HONESTLY
# regenerated abstract looks like this. Identical pin names, identical
# geometry — only the typing is gone.
MAGIC_WRITTEN_LEF = """VERSION 5.7 ;
MACRO NEUTRAL_BLOCK_A
  CLASS BLOCK ;
  FOREIGN NEUTRAL_BLOCK_A ;
  ORIGIN 0.000 0.000 ;
  SIZE 40.0 BY 20.0 ;
  PIN DATA_Q0
    PORT
      LAYER MX1 ;
        RECT 1.0 1.0 1.4 1.4 ;
    END
  END DATA_Q0
  PIN SUPPLY_HI_A
    PORT
      LAYER MX1 ;
        RECT 0.0 0.0 40.0 0.5 ;
    END
  END SUPPLY_HI_A
  PIN SUPPLY_LO_A
    PORT
      LAYER MX1 ;
        RECT 0.0 19.5 40.0 20.0 ;
    END
  END SUPPLY_LO_A
END NEUTRAL_BLOCK_A
END LIBRARY
"""

# An abstract that DOES type its pins and declares no supply terminal. That is
# an affirmative statement, not missing evidence — it must stay a SKIP.
SIGNAL_ONLY_LEF = """VERSION 5.8 ;
MACRO NEUTRAL_BLOCK_A
  CLASS BLOCK ;
  SIZE 40.0 BY 20.0 ;
  PIN DATA_Q0
    DIRECTION OUTPUT ;
    USE SIGNAL ;
  END DATA_Q0
  PIN CLK_A
    DIRECTION INPUT ;
    USE CLOCK ;
  END CLK_A
END NEUTRAL_BLOCK_A
END LIBRARY
"""

# The macro's OWN Liberty view, staged beside its abstract. `pg_pin`/`pg_type`
# survive a `lef write` that drops the LEF `USE` records, so this is the
# independent corroboration the gate recovers the typing from.
MACRO_LIB = """library (neutral_block_a) {
  technology (cmos) ;
  delay_model : table_lookup ;
  cell (NEUTRAL_BLOCK_A) {
    area : 800 ;
    pg_pin (SUPPLY_HI_A) { pg_type : primary_power ; voltage_name : "VIN_A" ; }
    pg_pin (SUPPLY_LO_A) { pg_type : primary_ground ; voltage_name : "VGND_A" ; }
    pin (DATA_Q0) { direction : output ; max_capacitance : 10.0 ; }
  }
}
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
           extra_lef: str | None = None, macro_lef: str | None = None,
           macro_lib: str | None = None) -> Path:
    project = tmp_path / "proj"
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    (project / "phase1" / "generated_docs" / "L21_POWER_INTENT.json").write_text(
        json.dumps(l21, indent=1))
    if with_macro:
        d = project / "input" / "pdk_local" / "neutral_vendor"
        d.mkdir(parents=True, exist_ok=True)
        (d / "neutral_block_a.lef").write_text(
            MACRO_LEF if macro_lef is None else macro_lef)
        if extra_lef is not None:
            (d / "neutral_core_cells.lef").write_text(extra_lef)
        if macro_lib is not None:
            (d / "neutral_block_a.lib").write_text(macro_lib)
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


# --------------------------------------------------------------------------- #
# vibe-ic#774 — absence of evidence is not evidence of non-applicability.
#
# All three fixtures below are the SAME macro with the SAME pin names. Only the
# ABSTRACT changes, and the three outcomes have to stay three outcomes.
# --------------------------------------------------------------------------- #
def test_the_three_absences_are_three_different_verdicts(tmp_path):
    """THE REGRESSION. Before #774 (b) printed a verdict byte-identical to (c).

      (a) hand-authored abstract, typed  -> FAIL on the rail (L21-1)
      (b) tool-written abstract, untyped -> FAIL on the abstract (L21-5)
      (c) no macro LEF staged at all     -> SKIP
    """
    typed = _build(tmp_path / "a", GUTTED_L21)
    rc_typed, out_typed = _run(typed)
    assert rc_typed == 1, f"typed abstract MUST FAIL. rc={rc_typed}\n{out_typed}"
    assert "L21-1" in out_typed

    untyped = _build(tmp_path / "b", GUTTED_L21, macro_lef=MAGIC_WRITTEN_LEF)
    rc_untyped, out_untyped = _run(untyped)
    assert rc_untyped != 2, (
        "an abstract that types NO pin must NOT be read as a design with no "
        f"supply pin to declare — that is the #774 defect. rc={rc_untyped}\n"
        f"{out_untyped}")
    assert rc_untyped == 1, f"rc={rc_untyped}\n{out_untyped}"
    assert "L21-5" in out_untyped, out_untyped
    assert "NEUTRAL_BLOCK_A" in out_untyped

    none = _build(tmp_path / "c", GUTTED_L21, with_macro=False)
    rc_none, out_none = _run(none)
    assert rc_none == 2, f"no macro LEF MUST still SKIP. rc={rc_none}\n{out_none}"

    assert out_untyped != out_none, (
        "the untyped-abstract verdict and the no-abstract verdict must be "
        "distinguishable; before #774 they were the same string")
    assert "no macro LEF at all" in out_none, out_none


def test_untyped_abstract_degrades_to_a_partial_check_not_a_louder_skip(
        tmp_path):
    """The macro's OWN Liberty view types the pins the abstract does not, so
    the gate recovers the typing and still runs the real L21-1 clause."""
    project = _build(tmp_path, GUTTED_L21, macro_lef=MAGIC_WRITTEN_LEF,
                     macro_lib=MACRO_LIB)
    out_json = tmp_path / "rep.json"
    proc = subprocess.run(
        [sys.executable, str(GATE), str(project), "--json", str(out_json)],
        capture_output=True, text=True, timeout=60)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, f"rc={proc.returncode}\n{out}"

    doc = json.loads(out_json.read_text())
    rules = {f["rule"] for f in doc["findings"]}
    assert "L21-1" in rules, (
        "an untyped abstract with a Liberty view must still produce the RAIL "
        f"finding, not only a complaint about the abstract\n{out}")
    assert "L21-5" in rules, out
    recovered = doc["recovered_pg_pins"]["NEUTRAL_BLOCK_A"]
    assert {(r["pin"], r["use"]) for r in recovered} == {
        ("SUPPLY_HI_A", "POWER"), ("SUPPLY_LO_A", "GROUND")}, recovered
    for f in doc["findings"]:
        if f["rule"] == "L21-1":
            assert f["typing_source"] != "lef_use", (
                "the typing came from the Liberty view, and the finding must "
                f"say so: {f}")
    assert "SUPPLY_HI_A" in out and "SUPPLY_LO_A" in out
    assert "TritonRoute" in out, "the rail finding must name the consequence"


def test_untyped_abstract_is_reported_even_when_L21_is_correct(tmp_path):
    """NOT SILENTLY GREEN. The rails ARE declared, so L21-1 is satisfied — but
    the binder reads the LEF's `USE`, not L21, so the untyped abstract is still
    a finding. A gate that passed here would be back to the #774 silence."""
    project = _build(tmp_path, WELLFORMED_L21, macro_lef=MAGIC_WRITTEN_LEF)
    rc, out = _run(project)
    assert rc == 1, (
        "a correct L21 does not repair an abstract the backend cannot read. "
        f"rc={rc}\n{out}")
    assert "L21-5" in out and "L21-1" not in out, out
    assert "CORROBORATED" in out, (
        "L21 declares rails of exactly these pin names — that corroborates the "
        f"pins are supply terminals and the message must say so\n{out}")

    # ...and the SAME design with the typing restored is clean.
    good = _build(tmp_path / "restored", WELLFORMED_L21)
    rc_ok, out_ok = _run(good)
    assert rc_ok == 0, f"restoring the typing must clear the gate\n{out_ok}"


def test_an_abstract_that_types_its_pins_and_has_no_supply_still_skips(
        tmp_path):
    """THE FALSE-POSITIVE CONTROL. `USE SIGNAL`/`USE CLOCK` on every pin is an
    AFFIRMATIVE declaration that the macro has no supply terminal. It is
    evidence, and it must keep SKIPping — otherwise 'everything now FAILs'."""
    project = _build(tmp_path, GUTTED_L21, macro_lef=SIGNAL_ONLY_LEF)
    out_json = tmp_path / "rep.json"
    proc = subprocess.run(
        [sys.executable, str(GATE), str(project), "--json", str(out_json)],
        capture_output=True, text=True, timeout=60)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 2, (
        f"an affirmatively-typed abstract MUST SKIP. rc={proc.returncode}\n{out}")
    doc = json.loads(out_json.read_text())
    # It SKIPped having READ the abstract, not for want of finding one — that
    # is the whole distinction #774 is about.
    assert doc["staged_macro_lefs"], doc
    assert "AFFIRMATIVE" in doc["skip_reason"], doc["skip_reason"]


def test_the_rail_waiver_does_not_absorb_the_untyped_abstract(tmp_path):
    """A waiver excuses the defect class it NAMES. The rail-absence waiver
    predates L21-5 and must not silently swallow it."""
    project = _build(tmp_path, GUTTED_L21, macro_lef=MAGIC_WRITTEN_LEF)
    (project / "waivers.json").write_text(json.dumps({
        "l21_macro_supply_rail_absent_disclosed":
            "This synthesized fixture deliberately provides no rail for the "
            "macro's dedicated supply; the gap is disclosed for review."}))
    rc, out = _run(project)
    assert rc == 1, (
        "the rail-absence waiver must NOT suppress a finding about the "
        f"abstract's missing typing. rc={rc}\n{out}")
    assert "L21-5" in out

    # The waiver that DOES name it works, and still discloses.
    (project / "waivers.json").write_text(json.dumps({
        "l21_macro_lef_pin_use_absent_disclosed":
            "This synthesized fixture's abstract is deliberately untyped; the "
            "producer defect is disclosed for review rather than hidden."}))
    rc_ok, out_ok = _run(project)
    assert rc_ok == 0, f"the named waiver must pass. rc={rc_ok}\n{out_ok}"
    assert "PASS_WITH_WAIVERS" in out_ok
    assert "L21-5" in out_ok, "a waiver must disclose, not hide"

    # ...and a too-short one must not.
    (project / "waivers.json").write_text(json.dumps({
        "l21_macro_lef_pin_use_absent_disclosed": "nope"}))
    rc_short, _ = _run(project)
    assert rc_short == 1, "a <40-char waiver must not suppress the finding"


def test_the_consumer_is_measurably_blind_to_an_untyped_abstract():
    """The load-bearing claim in the L21-5 message, RUN rather than asserted.

    `_macro_supply_gc_plan` is the backend function the gate speaks for. On the
    untyped abstract it returns ([], []) — no global connection AND no
    HARDMACRO_SUPPLY_UNCONNECTED finding — so the macro is invisible to the
    binder and to the binder's own honesty report at the same time."""
    sys.path.insert(0, str(PROGRAMS))
    import importlib
    runner = importlib.import_module("phase3_one_shot_runner")

    connect_t, unconn_t = runner._macro_supply_gc_plan([MACRO_LEF], [], [])
    assert unconn_t, (
        "control: the TYPED abstract must reach the consumer's honesty report")
    assert {(u["pin"], u["use"]) for u in unconn_t} == {
        ("SUPPLY_HI_A", "POWER"), ("SUPPLY_LO_A", "GROUND")}, unconn_t

    connect_m, unconn_m = runner._macro_supply_gc_plan(
        [MAGIC_WRITTEN_LEF], [], [])
    assert (connect_m, unconn_m) == ([], []), (
        "the untyped abstract is expected to be INVISIBLE to the consumer — if "
        "this ever stops being true the L21-5 message must be rewritten, not "
        f"the test. got {connect_m!r} {unconn_m!r}")


def test_the_shared_parser_separates_untyped_from_typed():
    """One parse answers both questions, so they can never disagree."""
    sys.path.insert(0, str(PROGRAMS))
    import importlib
    hmsi = importlib.import_module("hardmacro_supply_intent")

    magic = hmsi.lef_all_pins(MAGIC_WRITTEN_LEF)
    assert [p["pin"] for p in magic] == [
        "DATA_Q0", "SUPPLY_HI_A", "SUPPLY_LO_A"], magic
    assert all(p["uses"] == [] for p in magic), (
        f"magic `lef write` types no pin: {magic}")
    assert hmsi.lef_pg_pins(MAGIC_WRITTEN_LEF) == []

    # The PG walk is UNCHANGED by becoming a filter over the full walk.
    assert hmsi.lef_pg_pins(MACRO_LEF) == [
        {"master": "NEUTRAL_BLOCK_A", "pin": "SUPPLY_HI_A", "use": "POWER"},
        {"master": "NEUTRAL_BLOCK_A", "pin": "SUPPLY_LO_A", "use": "GROUND"}]
    signal_only = hmsi.lef_all_pins(SIGNAL_ONLY_LEF)
    assert [p["use"] for p in signal_only] == ["SIGNAL", "CLOCK"], signal_only


def test_no_L21_still_skips_but_names_the_untyped_abstract(tmp_path):
    """A missing L21 is a different fact and keeps its SKIP — but the abstract
    finding must not vanish along with the layer it would be compared to."""
    project = _build(tmp_path, GUTTED_L21, macro_lef=MAGIC_WRITTEN_LEF)
    (project / "phase1" / "generated_docs"
     / "L21_POWER_INTENT.json").unlink()
    rc, out = _run(project)
    assert rc == 2, f"no L21 must still SKIP. rc={rc}\n{out}"
    assert "NEUTRAL_BLOCK_A" in out and "USE" in out, out


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
