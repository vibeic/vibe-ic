"""Unit tests for lec_run.py — the Step 13 LEC PRODUCER.

SYNTHETIC-only: every test drives the pure parser `parse_equiv_output` and
the report shaper `build_report` with captured Yosys text. NO test requires
Docker / a container.

The two fixture blobs are REAL Yosys 0.66 output captured from spm:
  - CLEAN PASS  : generic $_-primitive netlist   -> 71/71 proven
  - SAT-LIMITED : sky130_fd_sc_hd-mapped netlist -> equiv_induct aborts on a
                  cell with no SAT model -> honest SKIPPED-CONDITION
"""
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "lec_run.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import lec_run  # noqa: E402
import lec_equivalence_check as gate  # noqa: E402  (downstream consumer)


# ---------------------------------------------------------------------------
# Captured real Yosys 0.66 output (tails; the parser only needs these lines).
# ---------------------------------------------------------------------------
PASS_OUTPUT = """\
equiv_simple: Starting.
Found 71 unproven $equiv cells (71 groups) in equiv:
Proved 67 previously unproven $equiv cells.
equiv_induct: Proving $equiv cells in module equiv.
Found 4 unproven $equiv cells in module equiv:
  Proof for induction step holds. Entire workset of 4 cells proven!
Proved 4 previously unproven $equiv cells.
No selected unproven $equiv cells found in equiv.
Proved 0 previously unproven $equiv cells.
equiv_status: Found 71 $equiv cells in equiv:
  Of those cells 71 are proven and 0 are unproven.
  Equivalence successfully proven!
"""

SAT_LIMITED_OUTPUT = """\
equiv_simple: Starting.
Found 70 unproven $equiv cells (70 groups) in equiv:
Proved 35 previously unproven $equiv cells.
equiv_induct: Proving $equiv cells in module equiv.
Found 35 unproven $equiv cells in module equiv:
ERROR: No SAT model available for cell _204__gate (sky130_fd_sc_hd__lpflow_isobufsrc_1).
"""

MISMATCH_OUTPUT = """\
equiv_simple: Starting.
Found 40 unproven $equiv cells (40 groups) in equiv:
Proved 33 previously unproven $equiv cells.
equiv_induct: Proving $equiv cells in module equiv.
Found 7 unproven $equiv cells in module equiv:
equiv_status: Found 40 $equiv cells in equiv:
  Of those cells 33 are proven and 7 are unproven.
  Unproven $equiv cells: \\p[3] \\p[4]
"""

GARBAGE_OUTPUT = "ERROR: syntax error in read_verilog\n"


# ---------------------------------------------------------------------------
# parse_equiv_output — clean PASS
# ---------------------------------------------------------------------------
def test_parse_clean_pass_counts():
    p = lec_run.parse_equiv_output(PASS_OUTPUT)
    assert p["proven"] == 71
    assert p["unproven"] == 0
    assert p["total"] == 71
    assert p["sat_model_unsupported_cells"] == []
    assert p["parse_error"] is False


def test_parse_clean_pass_verdict():
    p = lec_run.parse_equiv_output(PASS_OUTPUT)
    assert p["equivalent"] is True
    assert p["verdict"] == "PASS"
    assert p["success_line"] is True


# ---------------------------------------------------------------------------
# parse_equiv_output — SAT-model-limited -> SKIPPED-CONDITION (NOT a fake pass)
# ---------------------------------------------------------------------------
def test_parse_sat_limited_is_skipped_condition_not_pass():
    p = lec_run.parse_equiv_output(SAT_LIMITED_OUTPUT)
    assert p["verdict"] == "SKIPPED-CONDITION"
    assert p["equivalent"] is False, "MUST NOT fake a pass on a SAT-model gap"
    assert p["parse_error"] is False


def test_parse_sat_limited_captures_unsupported_cells():
    p = lec_run.parse_equiv_output(SAT_LIMITED_OUTPUT)
    cells = p["sat_model_unsupported_cells"]
    assert len(cells) == 1
    assert cells[0]["cell"] == "_204__gate"
    assert cells[0]["cell_type"] == "sky130_fd_sc_hd__lpflow_isobufsrc_1"
    # proven/unproven reconstructed from the pass-internal counters.
    assert p["proven"] == 35
    assert p["unproven"] == 35
    assert p["total"] == 70
    assert "lpflow_isobufsrc_1" in p["verdict_explanation"]


# ---------------------------------------------------------------------------
# parse_equiv_output — genuine mismatch (unproven>0, no SAT abort) -> FAIL
# ---------------------------------------------------------------------------
def test_parse_genuine_mismatch_is_fail():
    p = lec_run.parse_equiv_output(MISMATCH_OUTPUT)
    assert p["verdict"] == "FAIL"
    assert p["equivalent"] is False
    assert p["proven"] == 33
    assert p["unproven"] == 7
    assert p["parse_error"] is False


# ---------------------------------------------------------------------------
# parse_equiv_output — unparseable -> parse_error, never a -1 sentinel
# ---------------------------------------------------------------------------
def test_parse_garbage_is_parse_error_not_fake():
    p = lec_run.parse_equiv_output(GARBAGE_OUTPUT)
    assert p["parse_error"] is True
    assert p["equivalent"] is False
    assert p["proven"] is None and p["unproven"] is None
    # never the ambiguous -1 sentinel the pre-fix MCP used
    assert p["proven"] != -1 and p["unproven"] != -1


def test_parse_empty_is_parse_error():
    p = lec_run.parse_equiv_output("")
    assert p["parse_error"] is True
    assert p["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# build_report — JSON schema keys the downstream gate reads
# ---------------------------------------------------------------------------
def test_build_report_schema_keys():
    p = lec_run.parse_equiv_output(PASS_OUTPUT)
    r = lec_run.build_report(p, "chip_top",
                             "phase2/stage2/synth/netlist.v", lec_run.DEFAULT_LIBERTY)
    for k in ("equivalent", "compared_points", "non_equivalent_points",
              "unproven_points", "gold", "gate", "tool", "verdict",
              "sat_model_unsupported_cells", "verdict_explanation"):
        assert k in r, f"missing schema key: {k}"
    assert r["equivalent"] is True
    assert r["compared_points"] == 71
    assert r["non_equivalent_points"] == 0
    assert r["unproven_points"] == 0
    assert r["gold"] == "chip_top (RTL)"
    assert r["gate"] == "netlist.v (synth)"
    assert r["verdict"] == "PASS"
    assert r["tool"].startswith("yosys equiv")


def test_build_report_skip_has_unsupported_cells_and_false_equiv():
    p = lec_run.parse_equiv_output(SAT_LIMITED_OUTPUT)
    r = lec_run.build_report(p, "chip_top", "chip_top_synth.v", None)
    assert r["equivalent"] is False
    assert r["verdict"] == "SKIPPED-CONDITION"
    assert len(r["sat_model_unsupported_cells"]) == 1
    # compared_points reflects what WAS proven — never a fabricated count.
    assert r["compared_points"] == 35


# ---------------------------------------------------------------------------
# End-to-end schema contract: our PASS report must PASS the real gate,
# and our SKIPPED-CONDITION report must be an honest gate FAIL (not vacuous).
# ---------------------------------------------------------------------------
def test_pass_report_is_accepted_by_the_real_gate(tmp_path):
    p = lec_run.parse_equiv_output(PASS_OUTPUT)
    r = lec_run.build_report(p, "chip_top", "netlist.v", None)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "lec.json").write_text(json.dumps(r))
    (tmp_path / "reports" / "lec.rpt").write_text(PASS_OUTPUT)
    res = gate.audit(tmp_path)
    assert res.passed is True, [f.rule for f in res.findings]


def test_skip_report_is_honest_gate_fail_not_vacuous_pass(tmp_path):
    p = lec_run.parse_equiv_output(SAT_LIMITED_OUTPUT)
    r = lec_run.build_report(p, "chip_top", "chip_top_synth.v", None)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "lec.json").write_text(json.dumps(r))
    (tmp_path / "reports" / "lec.rpt").write_text(SAT_LIMITED_OUTPUT)
    res = gate.audit(tmp_path)
    # SKIPPED-CONDITION is equivalent:false -> the gate must NOT pass it, and
    # must not pass it vacuously either.
    assert res.passed is False
    rules = {f.rule for f in res.findings}
    assert "LEC_NOT_EQUIVALENT" in rules


# ---------------------------------------------------------------------------
# build_equiv_script — the proven recipe shape (deterministic, no container)
# ---------------------------------------------------------------------------
def test_build_equiv_script_has_recipe_steps():
    # APPROACH C — with a Liberty, the GATE side reads the Liberty WITHOUT -lib
    # and with -ignore_miss_func (functions/ff groups EXPAND to $_-primitives the
    # SAT engine can model), then flattens them in; the GOLD stays RTL. This is
    # what makes RTL≡synth provable where the -lib blackbox recipe aborted
    # "No SAT model available for cell … (NAND2D1)".
    s = lec_run.build_equiv_script(
        ["/p/rtl/a.v", "/p/rtl/b.v"], "/p/synth/netlist.v", "chip_top",
        lec_run.DEFAULT_LIBERTY)
    assert "read_verilog -sv /p/rtl/a.v /p/rtl/b.v" in s
    assert "-icells" not in s          # the flatten-breaking flag is gone
    # the SAT-modelable expansion (NOT a -lib blackbox) on the gate side:
    assert f"read_liberty -ignore_miss_func {lec_run.DEFAULT_LIBERTY}" in s
    assert "read_liberty -lib" not in s
    assert "flatten" in s              # inline the expanded cell logic
    assert "equiv_make gold gate equiv" in s
    assert "equiv_simple" in s
    assert "equiv_induct -seq 4" in s
    assert "equiv_induct -seq 64" in s
    assert "equiv_status" in s
    assert "prep -top chip_top" in s   # gold prep
    assert lec_run.DEFAULT_LIBERTY in s


def test_build_equiv_script_omits_liberty_when_none():
    # No Liberty → a generic $_-primitive netlist is already satgen-modelable, so
    # no read_liberty at all (gold + gate both plain read_verilog).
    s = lec_run.build_equiv_script(
        ["/p/rtl/a.v"], "/p/synth/netlist.v", "top", None)
    assert "read_liberty" not in s
    assert "read_verilog -sv /p/rtl/a.v" in s
    assert "-icells" not in s
    assert "equiv_make gold gate equiv" in s


# ---------------------------------------------------------------------------
# v1.4.21 REGRESSION — a GENERIC pre-techmap `$_`-primitive gate netlist must be
# read with `read_verilog -icells` (no Liberty), else `hierarchy -check` aborts
# on an undefined `\$_DFF_P_` module before any $equiv point is built and the
# LEC reports a FALSE compared_points=0 FAIL (spm clean-run: RTL was 208/208
# functionally correct yet Step-13 "FAILed" without ever checking equivalence).
# ---------------------------------------------------------------------------
def test_netlist_generic_detection(tmp_path):
    generic = tmp_path / "netlist.v"
    generic.write_text(
        "module spm(input clk, output p);\n"
        "  \\$_DFF_P_ _u0_ (.C(clk), .D(1'b0), .Q(p));\n"
        "  \\$_NAND_ _u1_ (.A(clk), .B(clk), .Y());\n"
        "endmodule\n")
    assert lec_run._netlist_uses_generic_primitives(str(generic)) is True

    mapped = tmp_path / "spm_synth.v"
    mapped.write_text(
        "module spm(input clk, output p);\n"
        "  sky130_fd_sc_hd__dfxtp_1 _u0_ (.CLK(clk), .D(1'b0), .Q(p));\n"
        "endmodule\n")
    assert lec_run._netlist_uses_generic_primitives(str(mapped)) is False
    # a plain RTL wire named `$foo` (no backslash-escaped `\$_` prefix) must NOT
    # be mistaken for a generic-primitive netlist.
    rtl = tmp_path / "rtl.v"
    rtl.write_text("module m(input a); wire x; assign x = a; endmodule\n")
    assert lec_run._netlist_uses_generic_primitives(str(rtl)) is False


def test_build_equiv_script_generic_uses_icells_no_liberty():
    # gate_is_generic=True → gate read is `read_verilog -icells`, NO read_liberty,
    # even though a Liberty arg is supplied; the equiv recipe is otherwise intact.
    s = lec_run.build_equiv_script(
        ["/p/rtl/a.v"], "/p/synth/netlist.v", "spm",
        lec_run.DEFAULT_LIBERTY, gate_is_generic=True)
    assert "read_verilog -icells /p/synth/netlist.v" in s
    assert "read_liberty" not in s            # generic gate needs no Liberty
    assert "read_verilog -sv /p/rtl/a.v" in s  # gold still plain -sv
    assert "equiv_make gold gate equiv" in s
    assert "equiv_induct -seq 64" in s
    assert "equiv_status" in s


def test_build_equiv_script_default_is_unchanged_by_new_param():
    # The Liberty-mapped APPROACH-C path (gate_is_generic defaults False) is
    # byte-for-byte what it was — no -icells, Liberty expanded. Guards the proven
    # HP18E80 path against regression from the new generic branch.
    s = lec_run.build_equiv_script(
        ["/p/rtl/a.v", "/p/rtl/b.v"], "/p/synth/netlist.v", "chip_top",
        lec_run.DEFAULT_LIBERTY)
    assert "-icells" not in s
    assert f"read_liberty -ignore_miss_func {lec_run.DEFAULT_LIBERTY}" in s


# ---------------------------------------------------------------------------
# #155 — equiv_make -memory_map (fork yosys 64286d02b): the flag is emitted
# ONLY when the capability probe says the running yosys supports it. On the
# pre-rebake vibeic-eda:0.2.17 image the probe returns False → bare equiv_make,
# a memory-bearing design stays an honest SKIPPED-CONDITION (no false pass).
# ---------------------------------------------------------------------------
def test_build_equiv_script_memory_map_off_by_default():
    # Default (probe-negative / pre-rebake) → bare equiv_make, byte-identical
    # to the historical recipe.
    s = lec_run.build_equiv_script(
        ["/p/rtl/a.v"], "/p/synth/netlist.v", "top", None)
    assert "equiv_make gold gate equiv" in s
    assert "-memory_map" not in s


def test_build_equiv_script_memory_map_on_emits_flag():
    # Probe-positive → `equiv_make -memory_map gold gate equiv`.
    s = lec_run.build_equiv_script(
        ["/p/rtl/a.v"], "/p/synth/netlist.v", "top", None, memory_map=True)
    assert "equiv_make -memory_map gold gate equiv" in s
    # the rest of the proven recipe is intact.
    assert "equiv_simple" in s
    assert "equiv_induct -seq 64" in s
    assert "equiv_status" in s


def test_yosys_supports_equiv_memory_map_probe(monkeypatch):
    # The probe greps `yosys -p "help equiv_make"` for the `-memory_map` token
    # and caches per container. Fail-safe: absence / error → False.
    calls = {"n": 0}

    class _R:
        def __init__(self, out):
            self.stdout, self.stderr, self.returncode = out, "", 0

    # (a) fork help text advertising the flag → True (and cached: one _docker call).
    def _fake_docker_yes(container, cmd, timeout=120):
        calls["n"] += 1
        return _R("[INFO] banner\n    equiv_make [options] gold_top gate_top\n"
                  "        -memory_map\n            legalize $mem/$mem_v2 …\n")
    monkeypatch.setattr(lec_run, "_docker", _fake_docker_yes)
    lec_run._EQUIV_MEMORY_MAP_CACHE.clear()
    assert lec_run._yosys_supports_equiv_memory_map("c-yes") is True
    assert lec_run._yosys_supports_equiv_memory_map("c-yes") is True
    assert calls["n"] == 1  # cached — probed at most once

    # (b) pre-fork help text WITHOUT the flag → False (bare equiv_make fallback).
    def _fake_docker_no(container, cmd, timeout=120):
        return _R("    equiv_make [options] gold_top gate_top\n"
                  "        -inames\n        -blackbox\n")
    monkeypatch.setattr(lec_run, "_docker", _fake_docker_no)
    lec_run._EQUIV_MEMORY_MAP_CACHE.clear()
    assert lec_run._yosys_supports_equiv_memory_map("c-no") is False

    # (c) Docker/Yosys error → fail-safe False (never speculatively enables).
    def _fake_docker_err(container, cmd, timeout=120):
        raise OSError("docker not reachable")
    monkeypatch.setattr(lec_run, "_docker", _fake_docker_err)
    lec_run._EQUIV_MEMORY_MAP_CACHE.clear()
    assert lec_run._yosys_supports_equiv_memory_map("c-err") is False


# ---------------------------------------------------------------------------
# _discover_project_liberty — the auto-discovery pure helper (no container).
# The Step-13 runner passes no --liberty, so the producer must find the
# design's OWN PDK Liberty or it falls back to the sky130 default (useless for
# a commercial-PDK design whose cells are only modelable from its Liberty).
# ---------------------------------------------------------------------------
def test_discover_liberty_prefers_canonical_pdk_dir_and_typ_corner(tmp_path):
    libdir = tmp_path / "input" / "pdk" / "liberty"
    libdir.mkdir(parents=True)
    # Three corners present; the typ/nominal one must win.
    (libdir / "foo_wci.lib").write_text("/* worst corner */")
    (libdir / "foo_typ.lib").write_text("/* typical corner */")
    (libdir / "foo_bci.lib").write_text("/* best corner */")
    got = lec_run._discover_project_liberty(tmp_path)
    assert got is not None
    assert got.name == "foo_typ.lib", got


def test_discover_liberty_bounded_fallback_under_input(tmp_path):
    # No canonical input/pdk/liberty dir, but a .lib elsewhere under input/.
    alt = tmp_path / "input" / "libs" / "ref"
    alt.mkdir(parents=True)
    (alt / "cells_tt.lib").write_text("/* tt corner */")
    got = lec_run._discover_project_liberty(tmp_path)
    assert got is not None and got.name == "cells_tt.lib"


def test_discover_liberty_none_when_project_ships_no_lib(tmp_path):
    (tmp_path / "input").mkdir()
    assert lec_run._discover_project_liberty(tmp_path) is None
