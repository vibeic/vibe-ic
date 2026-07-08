#!/usr/bin/env python3
"""TAPEOUT-SIGNOFF P1 — lec_post_layout_check.py (post-layout LEC gate).

Step 13 proves RTL==synth. This gate re-proves the FINAL routed/ECO netlist ==
synth/RTL after CTS/PnR/ECO/fill. §4.05: a non-proof / vacuous match is a FAIL,
never a pass; an absent routed netlist is an HONEST SKIP.

Covered:
  * build_yosys_equiv_script: emits equiv_make/equiv_simple/equiv_induct/
    equiv_status + reads the PDK blackbox verilog for physical-only cells.
  * parse_equiv_log: proven/unproven counts + verdict from real yosys phrasing.
  * evaluate_report: PASS (real non-vacuous proof) / FAIL (unproven, vacuous,
    non-equivalent, run-error) / SKIP (no routed netlist).
  * CLI: SKIP when the artefact is absent (exit 0, honest not-applicable);
    FAIL when the artefact proves nothing; PASS on a real proof.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import lec_post_layout_check as L  # noqa: E402


# ---- recipe ---------------------------------------------------------------
def test_recipe_has_equiv_engine_and_blackbox():
    ys = L.build_yosys_equiv_script(
        "gold.v", "gate.v", "lib.lib", "top",
        blackbox_v=["/pdk/sc__blackbox.v"])
    for cmd in ("equiv_make gold gate equiv", "equiv_simple", "equiv_induct",
                "equiv_status", "read_liberty -lib lib.lib"):
        assert cmd in ys, cmd
    # the physical-cell blackbox is read as -lib (inert modules)
    assert "read_verilog -lib /pdk/sc__blackbox.v" in ys
    assert "read_verilog -sv gold.v" in ys and "read_verilog -sv gate.v" in ys


def test_recipe_no_blackbox_ok():
    ys = L.build_yosys_equiv_script("gold.v", "gate.v", "lib.lib", "top")
    assert "equiv_status" in ys
    assert "read_verilog -lib" not in ys  # none supplied


# ---- auto-escalating sequential-induction depth ---------------------------
def test_recipe_default_escalates_seq_depth():
    # Default must emit escalating equiv_induct -seq passes (retiming/pipeline
    # equivalence needs induction depth >= latency; the shallow yosys default
    # -seq 4 falsely reports UNPROVEN). Escalation is sound: deeper only proves
    # more genuinely-equivalent cells, never an inequivalent pair.
    ys = L.build_yosys_equiv_script("gold.v", "gate.v", "lib.lib", "top")
    for d in L.DEFAULT_SEQ_DEPTHS:
        assert f"equiv_induct -seq {d}" in ys, d
    # ascending order (shallow first keeps the common case cheap)
    idxs = [ys.index(f"equiv_induct -seq {d}") for d in (4, 16, 64)]
    assert idxs == sorted(idxs)
    # deepest induct comes before the final status readout
    assert ys.index("equiv_induct -seq 64") < ys.index("equiv_status")


def test_recipe_custom_seq_depths_sorted_deduped():
    ys = L.build_yosys_equiv_script(
        "gold.v", "gate.v", "lib.lib", "top", seq_depths=[32, 8, 8, 0, -1])
    # positives only, de-duplicated, ascending
    assert "equiv_induct -seq 8" in ys and "equiv_induct -seq 32" in ys
    assert "equiv_induct -seq 0" not in ys and "equiv_induct -seq -1" not in ys
    assert ys.index("equiv_induct -seq 8") < ys.index("equiv_induct -seq 32")
    assert ys.count("equiv_induct -seq 8") == 1  # de-duplicated


# ---- parser ---------------------------------------------------------------
def test_parse_clean_pass():
    log = ("Found 128 $equiv cells in equiv:\n"
           "  Of those cells 128 are proven and 0 are unproven.\n"
           "Equivalence successfully proven!\n")
    r = L.parse_equiv_log(log)
    assert r["verdict"] == L.V_PASS
    assert r["proven"] == 128 and r["unproven"] == 0 and r["total"] == 128
    assert r["equivalent"] is True


def test_parse_unproven_is_not_pass():
    # the REAL spm RTL-vs-routed shape: 32 proven / 32 unproven -> UNPROVEN.
    log = ("Found 64 $equiv cells in equiv:\n"
           "  Of those cells 32 are proven and 32 are unproven.\n")
    r = L.parse_equiv_log(log)
    assert r["verdict"] == L.V_UNPROVEN
    assert r["unproven"] == 32 and r["proven"] == 32 and r["total"] == 64
    assert r["equivalent"] is False


def test_parse_vacuous_zero_cells():
    log = "Found 0 $equiv cells in equiv:\nEquivalence successfully proven!\n"
    r = L.parse_equiv_log(log)
    assert r["verdict"] == L.V_VACUOUS
    assert r["equivalent"] is False


def test_parse_run_error_empty():
    assert L.parse_equiv_log("")["verdict"] == L.V_RUN_ERROR
    assert L.parse_equiv_log("ERROR: Module foo not found\n")["verdict"] \
        == L.V_RUN_ERROR


def test_parse_sat_gap_cells_surfaced():
    log = ("Warning: Failed to import cell INVD1: has no model for cell type "
           "`INVD1'\n"
           "Found 10 $equiv cells in equiv:\n"
           "  Of those cells 8 are proven and 2 are unproven.\n")
    r = L.parse_equiv_log(log)
    assert "INVD1" in r["sat_unsupported_cells"]
    assert r["verdict"] == L.V_UNPROVEN  # 2 unproven -> not a clean pass


# ---- gate over the artefact ----------------------------------------------
def test_gate_pass_on_real_proof():
    doc = {"verdict": L.V_PASS, "total_points": 286, "proven_points": 286,
           "unproven_points": 0, "equivalent": True}
    assert L.evaluate_report(doc)["result"] == "PASS"


def test_gate_fail_on_unproven():
    doc = {"verdict": L.V_UNPROVEN, "total": 64, "proven": 32, "unproven": 32,
           "equivalent": False}
    res = L.evaluate_report(doc)
    assert res["result"] == "FAIL"
    assert any("UNPROVEN" in f for f in res["findings"])


def test_gate_fail_on_vacuous_true():
    # §4.05: equivalent==true with 0 points compared is NOT a pass.
    doc = {"verdict": L.V_PASS, "total_points": 0, "equivalent": True}
    assert L.evaluate_report(doc)["result"] == "FAIL"


def test_gate_fail_on_non_equivalent():
    doc = {"verdict": L.V_NONEQUIV, "total_points": 10, "proven_points": 8,
           "non_equivalent_points": 2, "equivalent": False}
    res = L.evaluate_report(doc)
    assert res["result"] == "FAIL"


def test_gate_skip_when_no_routed_netlist():
    res = L.evaluate_report({"verdict": L.V_SKIP, "skipped": True,
                             "skip_reason": "not placed-and-routed"})
    assert res["result"] == "SKIP"


# ---- CLI ------------------------------------------------------------------
def _write(project: Path, doc: dict) -> Path:
    p = project / "reports" / "phase3" / "lec_post_layout.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc))
    return p


def test_cli_skip_when_absent(tmp_path):
    # No artefact => honest SKIP => exit 0 (not a FAIL of a check that could not
    # apply, and never a vacuous pass).
    assert L.main([str(tmp_path)]) == 0


def test_cli_pass(tmp_path):
    _write(tmp_path, {"verdict": L.V_PASS, "total_points": 100,
                      "proven_points": 100, "unproven_points": 0,
                      "equivalent": True})
    assert L.main([str(tmp_path)]) == 0


def test_cli_fail_on_unproven(tmp_path):
    _write(tmp_path, {"verdict": L.V_UNPROVEN, "total": 64, "proven": 32,
                      "unproven": 32, "equivalent": False})
    assert L.main([str(tmp_path)]) == 1


def test_cli_fail_on_unparseable(tmp_path):
    p = tmp_path / "reports" / "phase3" / "lec_post_layout.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json")
    assert L.main([str(tmp_path)]) == 1
