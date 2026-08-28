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
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "lec_run.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import lec_run  # noqa: E402
import lec_equivalence_check as gate  # noqa: E402  (downstream consumer)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


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
# #155 follow-up — a post-memory_map memory-inclusive proof that exceeds the LEC
# wall budget leaves no equiv_status (parse_error) but carries the timeout
# marker. That is a DISCLOSED budget gap → SKIPPED-CONDITION, NEVER a regression
# to FAIL (before #155 the same design fast-skipped on the $mem_v2 SAT-model gap).
# ---------------------------------------------------------------------------
def test_parse_timeout_is_skipped_condition_not_fail():
    txt = ("14. Executing EQUIV_INDUCT pass.\n"
           "Trying to prove $equiv for \\state[3]: ...\n"
           + lec_run._TIMEOUT_MARKER + " after 1800s\n")
    p = lec_run.parse_equiv_output(txt)
    assert p["parse_error"] is True
    assert p["verdict"] == "SKIPPED-CONDITION"     # NOT FAIL (pure resource skip)
    assert p["equivalent"] is False                # never a fake pass
    assert "budget" in p["verdict_explanation"].lower()


def test_parse_garbage_without_timeout_still_fails():
    # NO timeout marker → the unparseable case is still an honest FAIL (the
    # SKIPPED reclassification must not swallow genuine no-output failures).
    p = lec_run.parse_equiv_output("random tool noise, no equiv verdict here")
    assert p["parse_error"] is True
    assert p["verdict"] == "FAIL"


def test_parse_unproven_with_timeout_is_still_fail():
    # A REAL mismatch (unproven $equiv found) that also happens to time out is
    # NOT parse_error → stays FAIL: the timeout SKIP only covers no-verdict runs.
    txt = ("Found 8 $equiv cells in equiv:\n"
           "  Of those cells 0 are proven and 8 are unproven.\n"
           "[lec_run] ERROR: yosys equiv timed out\n")
    p = lec_run.parse_equiv_output(txt)
    assert p["parse_error"] is False
    assert p["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# CONTAINER-side budget kill (run_yosys_equiv): the `timeout` that _docker wraps
# every call in fires BEFORE the host subprocess.run deadline, so a genuine
# wall-budget kill returns NORMALLY with GNU-`timeout`'s exit code (124 / 137)
# and NEVER raises subprocess.TimeoutExpired. run_yosys_equiv must re-attach the
# budget marker so the parser classifies it as a disclosed budget gap, not a
# hard FAIL. Regression from opentitan_aes × sky130A (27904 $equiv cells killed
# at 7200s, misbooked verdict=FAIL "may genuinely differ").
# ---------------------------------------------------------------------------
class _FakeProc:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


# The exact shape the opentitan_aes run produced: only the INITIAL $equiv total
# banner leaked (equiv_simple was still churning when SIGKILL landed) — no
# `N proven / M unproven` completion line, no counterexample.
_KILLED_MID_PROOF = (
    "Yosys 0.67+\n"
    "Found 27904 unproven $equiv cells (27904 groups) in equiv:\n"
    "  Trying to prove $equiv for \\u_aes.ctr_i[82]: ezsat\nezsat\n failed.\n"
    "  Trying "
)


@pytest.mark.parametrize("rc", [137, 124])
def test_container_timeout_rc_reattaches_budget_marker(monkeypatch, rc):
    # yosys killed by the container-side `timeout` (137=SIGKILL after
    # --kill-after, 124=SIGTERM expiry) arrives via the NORMAL return path.
    monkeypatch.setattr(lec_run, "_docker",
                        lambda *a, **k: _FakeProc(rc, _KILLED_MID_PROOF))
    # 60 and not the 7200 s production LEC budget: `lec_run._docker` is
    # monkeypatched above, so this call launches nothing and the number never
    # bounds anything — it was on `ci_harness_timeout_ceiling_check`'s advisory
    # list as the largest unresolvable "bound" in the tree. What the test is
    # about is the marker re-attachment on rc 137/124, which the value below
    # does not enter.
    launched, out = lec_run.run_yosys_equiv("c", "/x.ys", timeout=60)
    assert launched is True
    assert lec_run._TIMEOUT_MARKER in out          # marker re-attached
    # …and the parser now correctly classifies it, NOT a false FAIL:
    p = lec_run.parse_equiv_output(out)
    assert p["verdict"] == "INCONCLUSIVE"
    assert p["equivalent"] is False                # never a fake pass


def test_container_clean_rc_does_not_fabricate_marker(monkeypatch):
    # NEGATIVE CONTROL: a normal completed run (rc=0) with a REAL mismatch must
    # NOT get a budget marker — the genuine FAIL has to survive.
    done_fail = ("Yosys 0.67+\n"
                 "Found 8 $equiv cells in equiv:\n"
                 "  Of those cells 0 are proven and 8 are unproven.\n")
    monkeypatch.setattr(lec_run, "_docker",
                        lambda *a, **k: _FakeProc(0, done_fail))
    _, out = lec_run.run_yosys_equiv("c", "/x.ys", timeout=10)
    assert lec_run._TIMEOUT_MARKER not in out
    assert lec_run.parse_equiv_output(out)["verdict"] == "FAIL"


def test_container_tool_error_rc1_does_not_fabricate_marker(monkeypatch):
    # NEGATIVE CONTROL: an ordinary yosys error exit (rc=1) is not a budget
    # kill — no marker, so a genuine no-verdict crash stays a FAIL.
    monkeypatch.setattr(lec_run, "_docker",
                        lambda *a, **k: _FakeProc(1, "Yosys 0.67+\nERROR: boom\n"))
    _, out = lec_run.run_yosys_equiv("c", "/x.ys", timeout=10)
    assert lec_run._TIMEOUT_MARKER not in out


def test_container_timeout_rc_with_recorded_mismatch_still_fails(monkeypatch):
    # A timeout that ALSO recorded a completed mismatch (proven+unproven parsed)
    # keeps its real FAIL even though rc=137 re-attaches the marker — the marker
    # only redirects a NO-VERDICT run, it can never hide a proven difference.
    done_then_killed = ("Yosys 0.67+\n"
                        "Found 8 $equiv cells in equiv:\n"
                        "  Of those cells 0 are proven and 8 are unproven.\n")
    monkeypatch.setattr(lec_run, "_docker",
                        lambda *a, **k: _FakeProc(137, done_then_killed))
    _, out = lec_run.run_yosys_equiv("c", "/x.ys", timeout=10)
    assert lec_run._TIMEOUT_MARKER in out          # marker re-attached…
    assert lec_run.parse_equiv_output(out)["verdict"] == "FAIL"  # …but FAIL stands


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


def test_skip_report_is_honest_waived_deferred_not_vacuous_pass(tmp_path):
    p = lec_run.parse_equiv_output(SAT_LIMITED_OUTPUT)
    r = lec_run.build_report(p, "chip_top", "chip_top_synth.v", None)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "lec.json").write_text(json.dumps(r))
    (tmp_path / "reports" / "lec.rpt").write_text(SAT_LIMITED_OUTPUT)
    res = gate.audit(tmp_path)
    # A SAT-model-unsupported SKIPPED-CONDITION is a DISCLOSED capability gap:
    # lec_run built no deciding miter and recorded NO counterexample
    # (non_equivalent_points == 0). The gate must NOT pass it, and must NOT pass
    # it vacuously either — `passed` stays False. But it is NOT a hard
    # LEC_NOT_EQUIVALENT that cascade-marks every downstream physical step MISSING
    # off a netlist nothing proved non-equivalent; it is the non-blocking
    # WAIVED-DEFERRED tier (inconclusive=True, its own honest LEC_SKIPPED_CONDITION
    # finding), the SAME evidence class the #208 INCONCLUSIVE sibling is booked as.
    # NO-LEAK: a genuine mismatch lands non_equivalent_points>0 (or verdict FAIL)
    # and still hard-FAILs at the substance verdict — covered by
    # test_skipped_condition_with_counterexample_still_hard_fails.
    assert res.passed is False
    assert res.inconclusive is True
    rules = {f.rule for f in res.findings}
    assert rules == {"LEC_SKIPPED_CONDITION"}, rules


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
# equiv_struct SAT-free pre-reduction — the deck must run structural hashing
# BEFORE spending any SAT, so equiv_simple decides only the cones that are
# genuinely restructured, not every trivially-identical key-point.
#
# MEASURED motivation (a large AES miter, container yosys 0.67+): after
# equiv_make the miter had 31 850 unproven $equiv cells; a single equiv_struct
# pass collapsed 28 517 of them structurally (28 403 merges), leaving 3 333 for
# SAT — a 10x cut. Without equiv_struct the deck SAT-hammered all 31 850,
# exhausted the wall clock mid-equiv_simple, and reported a FALSE INCONCLUSIVE.
# ---------------------------------------------------------------------------
def test_build_equiv_script_runs_equiv_struct_before_sat():
    # FORWARD negative control: FAILS against the byte-identical pre-fix deck
    # (which had no equiv_struct), PASSES after the pre-reduction is inserted.
    s = lec_run.build_equiv_script(
        ["/p/rtl/a.v"], "/p/synth/netlist.v", "top", None)
    assert "equiv_struct" in s, "SAT-free structural pre-reduction is missing"
    # It must sit AFTER key-point mapping and BEFORE the first SAT proof, so the
    # SAT stages see the reduced set — not before equiv_make (nothing to merge),
    # not after equiv_simple (the saving is already spent).
    assert (s.index("equiv_make gold gate equiv")
            < s.index("equiv_struct")
            < s.index("equiv_simple")), "equiv_struct out of order"


def test_build_equiv_script_keeps_full_sat_ladder():
    # REVERSE control — a STABLE INVARIANT that MUST PASS both before AND after
    # the equiv_struct fix. equiv_struct is SOUND but only proves STRUCTURAL
    # identity; it can never witness functional equivalence of a restructured
    # cone. So the fix must AUGMENT, never REPLACE, the SAT proof ladder. This
    # pins the exact cheat the prompt warns of: "greening" convergence by
    # DELETING equiv_simple/equiv_induct (trivially fast AND blind). It makes NO
    # reference to equiv_struct, so it holds on the pre-fix deck too — its only
    # job is to fail the moment any SAT stage disappears or the ladder reorders.
    s = lec_run.build_equiv_script(
        ["/p/rtl/a.v"], "/p/synth/netlist.v", "top", None)
    for stage in ("equiv_simple", "equiv_induct -seq 4",
                  "equiv_induct -seq 16", "equiv_induct -seq 64",
                  "equiv_status"):
        assert stage in s, f"SAT verification stage {stage!r} was removed"
    assert (s.index("equiv_simple")
            < s.index("equiv_induct -seq 4")
            < s.index("equiv_induct -seq 16")
            < s.index("equiv_induct -seq 64")
            < s.index("equiv_status")), "SAT ladder order broken"


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
    # commercial PDK path against regression from the new generic branch.
    s = lec_run.build_equiv_script(
        ["/p/rtl/a.v", "/p/rtl/b.v"], "/p/synth/netlist.v", "chip_top",
        lec_run.DEFAULT_LIBERTY)
    assert "-icells" not in s
    assert f"read_liberty -ignore_miss_func {lec_run.DEFAULT_LIBERTY}" in s


# ---------------------------------------------------------------------------
# #155 — a `memory_map` PASS on each side (PRE-flatten) legalizes $mem/$mem_v2
# so a memory-bearing design proves instead of the satgen `No SAT model … $mem_v2`
# abort. Plain stock yosys 1042b3f55 — no fork flag, no capability probe. Order
# is load-bearing: PRE-flatten (a post-flatten memory_map leaves it unproven,
# 0/8 vs 136/0 in-container). No-op for a non-memory design.
# ---------------------------------------------------------------------------
def test_build_equiv_script_emits_memory_map_pre_flatten_both_sides():
    s = lec_run.build_equiv_script(
        ["/p/rtl/a.v"], "/p/synth/netlist.v", "top", None)
    # bare equiv_make (the fork -memory_map FLAG approach is dropped).
    assert "equiv_make gold gate equiv" in s
    assert "-memory_map" not in s
    # a `memory_map` pass appears on BOTH sides (gold after prep, gate after
    # hierarchy) — exactly twice.
    assert s.count("\nmemory_map\n") == 2
    # LOAD-BEARING ordering: each memory_map precedes its side's flatten.
    gold = s.split("design -stash gold")[0]
    assert gold.index("prep -top top") < gold.index("memory_map") < gold.index("flatten")


def test_build_equiv_script_memory_map_precedes_flatten_generic_gate():
    # generic ($_-primitive) gate path: memory_map still emitted pre-flatten on
    # both sides; recipe otherwise intact.
    s = lec_run.build_equiv_script(
        ["/p/rtl/a.v"], "/p/synth/netlist.v", "spm",
        lec_run.DEFAULT_LIBERTY, gate_is_generic=True)
    assert s.count("\nmemory_map\n") == 2
    assert "read_verilog -icells /p/synth/netlist.v" in s
    assert "equiv_make gold gate equiv" in s
    assert "equiv_induct -seq 64" in s


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


# ---------------------------------------------------------------------------
# (c) SLANG gold-read fallback — build_equiv_script gold_frontend param.
# The built-in `read_verilog -sv` gold read parse-aborts on a real SV closure
# (package-scope refs, unpacked-array ports); the gold must then be read with
# the SAME `read_slang` SV-2017 frontend the synth step auto-uses.
# ---------------------------------------------------------------------------
def test_gold_frontend_default_is_read_verilog():
    s = lec_run.build_equiv_script(["/p/rtl/a.sv"], "/p/synth/n.v", "top", None)
    assert "read_verilog -sv /p/rtl/a.sv" in s        # default gold read
    assert "read_slang" not in s


def test_gold_frontend_slang_emits_read_slang_with_top_and_defines():
    s = lec_run.build_equiv_script(
        ["/p/rtl/a.sv", "/p/rtl/b.sv"], "/p/synth/n.v", "top", None,
        gold_frontend="slang")
    assert ("read_slang --single-unit /p/rtl/a.sv /p/rtl/b.sv --top top "
            "-DSIMULATION -DYOSYS") in s
    assert "read_verilog -sv /p/rtl/a.sv" not in s     # gold is slang now
    # gate side unchanged (plain read_verilog for a mapped netlist)
    assert "read_verilog" in s
    # no plugin load when read_slang is built-in (default slang_prefix "")
    assert "plugin -i slang" not in s


def test_gold_frontend_slang_emits_plugin_load_when_needed():
    s = lec_run.build_equiv_script(
        ["/p/rtl/a.sv"], "/p/synth/n.v", "top", None,
        gold_frontend="slang", slang_prefix="plugin -i slang; ")
    assert "plugin -i slang\n" in s                    # own command line
    assert s.index("plugin -i slang") < s.index("read_slang")


# ---------------------------------------------------------------------------
# (d) parse-abort → INCONCLUSIVE, never a false FAIL. A frontend parse-abort
# built NO miter (0 compared points) → not classifiable as PASS or FAIL. A
# genuine miter that runs and leaves unproven points still FAILs.
# ---------------------------------------------------------------------------
_FRONTEND_ABORT_OUTPUT = """\
-- Running command `read_verilog -sv /p/rtl/ibex_alu.sv' --

1. Executing Verilog-2005 frontend: /p/rtl/ibex_alu.sv
/p/rtl/ibex_alu.sv:10: ERROR: syntax error, unexpected TOK_PACKAGE
"""


def test_is_frontend_parse_abort_detector():
    assert lec_run.is_frontend_parse_abort(_FRONTEND_ABORT_OUTPUT) is True
    assert lec_run.is_frontend_parse_abort("Can't open input file `x.v'") is True
    # a genuine mismatch log (miter ran) is NOT a frontend parse-abort
    assert lec_run.is_frontend_parse_abort(MISMATCH_OUTPUT) is False
    assert lec_run.is_frontend_parse_abort("") is False


def test_parse_frontend_abort_is_inconclusive_not_fail():
    p = lec_run.parse_equiv_output(_FRONTEND_ABORT_OUTPUT)
    assert p["verdict"] == "INCONCLUSIVE"       # NOT "FAIL"
    assert p["equivalent"] is False
    assert p["parse_error"] is True
    assert p["proven"] is None and p["unproven"] is None


def test_parse_empty_stays_fail_not_inconclusive():
    # empty output carries NO frontend parse-abort signature → still FAIL
    # (a genuine could-not-run-the-tool, not a truthful INCONCLUSIVE).
    p = lec_run.parse_equiv_output("")
    assert p["verdict"] == "FAIL"


def test_genuine_mismatch_still_fails_not_inconclusive():
    # §4.05-safe: a miter that RAN and left unproven points is a real FAIL —
    # the INCONCLUSIVE reclassification is only for a ZERO-miter parse-abort.
    p = lec_run.parse_equiv_output(MISMATCH_OUTPUT)
    assert p["verdict"] == "FAIL"


def test_build_report_marks_inconclusive():
    p = lec_run.parse_equiv_output(_FRONTEND_ABORT_OUTPUT)
    r = lec_run.build_report(p, "chip_top", "netlist.v", None)
    assert r["inconclusive"] is True
    assert r["verdict"] == "INCONCLUSIVE"
    # a normal PASS report is not inconclusive
    r2 = lec_run.build_report(lec_run.parse_equiv_output(PASS_OUTPUT),
                              "chip_top", "netlist.v", None)
    assert r2["inconclusive"] is False


# ---------------------------------------------------------------------------
# (d, consumer) the downstream gate treats an INCONCLUSIVE report as a
# non-blocking SKIPPED-CONDITION (rc 3 + PASS_WITH_WAIVERS => WAIVED-DEFERRED),
# never a hard FAIL, never a vacuous PASS, and never a bare PASS.
# ---------------------------------------------------------------------------
def test_inconclusive_report_is_non_blocking_in_gate(tmp_path):
    p = lec_run.parse_equiv_output(_FRONTEND_ABORT_OUTPUT)
    r = lec_run.build_report(p, "chip_top", "netlist.v", None)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "lec.json").write_text(json.dumps(r))
    (tmp_path / "reports" / "lec.rpt").write_text(_FRONTEND_ABORT_OUTPUT)
    res = gate.audit(tmp_path)
    assert res.inconclusive is True
    assert res.passed is False                  # never a vacuous PASS
    rules = {f.rule for f in res.findings}
    assert "LEC_INCONCLUSIVE_PARSE_ABORT" in rules
    assert "LEC_NOT_EQUIVALENT" not in rules     # not the hard-FAIL path
  # #208 follow-up: still NON-BLOCKING (flow_compliance resolves rc=3 +
    # the PASS_WITH_WAIVERS sentinel to WAIVED-DEFERRED, so the step does
    # not fail and nothing cascades to MISSING) but no longer a BARE PASS,
    # which rc=0 silently was at the `program_exit_zero` gate.
    assert gate.main([str(tmp_path)]) == 3   # non-blocking, not a PASS


def test_inconclusive_label_with_real_counterexample_still_fails(tmp_path):
    # §4.05 NO-LEAK (post-#208): the discriminator for a PROVEN mismatch is a
    # COUNTEREXAMPLE (non_equivalent_points > 0), not merely unproven points.
    # A report LABELED inconclusive but carrying a real counterexample must NOT
    # get the free pass — it still FAILs.
    doc = {"verdict": "INCONCLUSIVE", "inconclusive": True,
           "equivalent": False, "compared_points": 33,
           "unproven_points": 7, "non_equivalent_points": 2}
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "lec.json").write_text(json.dumps(doc))
    res = gate.audit(tmp_path)
    assert res.inconclusive is False
    assert res.passed is False
    assert gate.main([str(tmp_path)]) == 1       # real counterexample → hard FAIL


def test_inconclusive_label_unproven_without_counterexample_is_inconclusive(tmp_path):
    # #208 — a COMPLETED miter that left points unproven but recorded NO
    # counterexample (non_equivalent_points == 0) is equiv_induct NON-CONVERGENCE,
    # not non-equivalence. It is INCONCLUSIVE (non-blocking), NOT NOT_EQUIVALENT.
    doc = {"verdict": "INCONCLUSIVE", "inconclusive": True,
           "equivalent": False, "compared_points": 6350,
           "unproven_points": 909, "non_equivalent_points": 0,
           "non_convergence": True}
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "lec.json").write_text(json.dumps(doc))
    res = gate.audit(tmp_path)
    assert res.inconclusive is True
    assert res.passed is False                   # visible non-PASS, not vacuous
    rules = {f.rule for f in res.findings}
    assert "LEC_INCONCLUSIVE_NONCONVERGENCE" in rules
    assert "LEC_NOT_EQUIVALENT" not in rules
  # #208 follow-up: still NON-BLOCKING (flow_compliance resolves rc=3 +
    # the PASS_WITH_WAIVERS sentinel to WAIVED-DEFERRED, so the step does
    # not fail and nothing cascades to MISSING) but no longer a BARE PASS,
    # which rc=0 silently was at the `program_exit_zero` gate.
    assert gate.main([str(tmp_path)]) == 3   # non-blocking, not a PASS


# ---------------------------------------------------------------------------
# ELABORATION-abort trigger widening (rv-ibex2 coverage gap): the built-in
# read_verilog -sv PARSES fine but aborts at ELABORATION on an SV package/enum
# constant used as a parameter value ("Parameter … with non-constant value!").
# The slang retry must FIRE for that signature too, not just parse/syntax aborts.
# The abort string below is the REAL ibex field output quoted from the rv-ibex2
# run (authentic, not hand-written).
# ---------------------------------------------------------------------------
_IBEX_ELAB_ABORT = (
    "-- Running command `read_verilog -sv /p/rtl/chip_top.sv' --\n"
    "\n"
    "1. Executing Verilog-2005 frontend: /p/rtl/chip_top.sv\n"
    "chip_top.sv:85: ERROR: Parameter u_ibex_core.RV32M with non-constant "
    "value!\n")


def test_elaboration_abort_triggers_the_slang_retry():
    # POSITIVE: the ibex elaboration abort must be recognised as a frontend
    # abort so the `parse_error and is_frontend_parse_abort` retry gate fires.
    assert lec_run.is_frontend_parse_abort(_IBEX_ELAB_ABORT) is True
    p = lec_run.parse_equiv_output(_IBEX_ELAB_ABORT)
    assert p["parse_error"] is True
    # the exact condition main() uses to fire the read_slang gold-read retry:
    assert p["parse_error"] and lec_run.is_frontend_parse_abort(_IBEX_ELAB_ABORT)
    # provisional (pre-retry) verdict is INCONCLUSIVE, never a false FAIL.
    assert p["verdict"] == "INCONCLUSIVE"


def test_non_constant_matcher_does_not_fire_on_a_real_miter_mismatch():
    # NEGATIVE (no false-pass / no spurious retry): a real mismatch ran a miter
    # (parse_error False), so is_frontend_parse_abort can't fire the retry and
    # the verdict stays FAIL — even the word never appears here.
    assert lec_run.is_frontend_parse_abort(MISMATCH_OUTPUT) is False
    p = lec_run.parse_equiv_output(MISMATCH_OUTPUT)
    assert p["parse_error"] is False and p["verdict"] == "FAIL"


def test_slang_succeeds_but_unequal_still_fails():
    # NEGATIVE (no false-pass): after the retry, slang built a REAL miter that
    # left points unproven → FAIL (the retry only changed the frontend, not the
    # equivalence verdict). finalize_after_slang_retry is a no-op on a real FAIL.
    p = lec_run.parse_equiv_output(MISMATCH_OUTPUT)
    assert lec_run.finalize_after_slang_retry(p, slang_retry_failed=False) is p
    assert p["verdict"] == "FAIL"


def test_slang_also_fails_downgrades_inconclusive_to_fail():
    # NEGATIVE (no vacuous non-blocking pass): the built-in aborted, the slang
    # retry was attempted, and slang ALSO could not elaborate → the provisional
    # INCONCLUSIVE is downgraded to a hard FAIL (never a free pass).
    prov = lec_run.parse_equiv_output(_IBEX_ELAB_ABORT)
    assert prov["verdict"] == "INCONCLUSIVE"
    fin = lec_run.finalize_after_slang_retry(prov, slang_retry_failed=True)
    assert fin["verdict"] == "FAIL"
    assert fin["equivalent"] is False
    r = lec_run.build_report(fin, "top", "n.v", None)
    assert r["inconclusive"] is False            # NOT the non-blocking path
    # and when slang was NOT the failing frontend (succeeded / not attempted),
    # the INCONCLUSIVE provisional is preserved.
    assert lec_run.finalize_after_slang_retry(
        prov, slang_retry_failed=False)["verdict"] == "INCONCLUSIVE"


def test_slang_also_fails_report_is_hard_fail_in_gate(tmp_path):
    # end-to-end §4.05: a slang-also-fails report is a BLOCKING FAIL at the gate,
    # not the non-blocking INCONCLUSIVE skip.
    prov = lec_run.parse_equiv_output(_IBEX_ELAB_ABORT)
    fin = lec_run.finalize_after_slang_retry(prov, slang_retry_failed=True)
    r = lec_run.build_report(fin, "top", "n.v", None)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "lec.json").write_text(json.dumps(r))
    res = gate.audit(tmp_path)
    assert res.inconclusive is False
    assert res.passed is False
    assert gate.main([str(tmp_path)]) == 1


# ---------------------------------------------------------------------------
# ASYNC-FF LEGALIZATION on BOTH read paths (rv-ibex2 residual #2): an async-
# reset/-set FF maps to $_DFF_PN0_ which equiv_induct's SAT engine can't model
# ("No SAT model available for async FF … consider async2sync/clk2fflogic").
# async2sync must be emitted on BOTH sides, AFTER flatten, regardless of which
# frontend read the gold — so the read_slang gold-read retry path (the SV-package
# CPUs like ibex, which are exactly the async-reset designs) is covered too.
# ---------------------------------------------------------------------------
def test_async2sync_emitted_on_both_sides_and_frontends():
    for frontend in ("verilog", "slang"):
        s = lec_run.build_equiv_script(
            ["/p/rtl/a.sv"], "/p/synth/n.v", "top", lec_run.DEFAULT_LIBERTY,
            gold_frontend=frontend)
        # exactly one async2sync per side (gold + gate).
        assert s.count("\nasync2sync\n") == 2, (frontend, s)
        # AFTER flatten on each side (async2sync legalizes the flattened FF cells).
        assert s.index("flatten") < s.index("async2sync")
        # gold-side async2sync sits before `design -stash gold`.
        gold = s.split("design -stash gold")[0]
        assert "async2sync" in gold and gold.index("flatten") < gold.index("async2sync")


def test_async2sync_applies_to_the_slang_retry_path():
    # the SLANG gold-read path (fired by the elaboration-abort retry) gets the
    # SAME async-FF legalization as the default verilog path — not bypassed.
    v = lec_run.build_equiv_script(["/p/a.sv"], "/p/n.v", "top", None,
                                   gold_frontend="verilog")
    sl = lec_run.build_equiv_script(["/p/a.sv"], "/p/n.v", "top", None,
                                    gold_frontend="slang")
    assert v.count("\nasync2sync\n") == sl.count("\nasync2sync\n") == 2
    assert "read_slang" in sl and "async2sync" in sl


# --- REAL in-container async-reset proof (fork-safe, NDA-clean, sky130) -------
# The strongest gate: synth an async-reset DFF to sky130 (→ dfrtp → $_DFF_PN0_),
# then run the ACTUAL lec_run recipe on the SLANG gold-read path and assert equiv
# REACHES a proven verdict — not the "No SAT model available for async FF" stop.
# Skips when no path-visible container is available.
_ASYNC_RTL = (
    "module dff_ar(input clk, input rst_n, input [3:0] d, output reg [3:0] q);\n"
    "  always @(posedge clk or negedge rst_n)\n"
    "    if (!rst_n) q <= 4'b0; else q <= d + 4'd1;\n"
    "endmodule\n")
_SKY130_HD_LIB = ("/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
                  "sky130_fd_sc_hd__tt_025C_1v80.lib")


def _mounted_workdir(tmp_path):
    """Container-visible work dir + cleanup (tmp_path if bind-mounted, else a
    self-cleaning $HOME tempdir). (None, noop) when no container path exists."""
    def _sees(root):
        try:
            p = root / ".probe"
            p.write_text("ok")
            r = _pr.run(
                ["docker", "exec", "vibeic-eda", "bash", "-lc", f"cat {p}"],
                capture_output=True, text=True)
            p.unlink(missing_ok=True)
            return r.returncode == 0 and "ok" in (r.stdout or "")
        except (subprocess.SubprocessError, OSError):
            return False
    if _sees(tmp_path):
        return tmp_path, (lambda: None)
    import tempfile
    import shutil
    d = Path(tempfile.mkdtemp(prefix=".lec_async_it_", dir=str(Path.home())))
    if _sees(d):
        return d, (lambda: shutil.rmtree(d, ignore_errors=True))
    shutil.rmtree(d, ignore_errors=True)
    return None, (lambda: None)


def _yosys(script_path):
    cmd = (f"export PATH=/foss/tools/yosys/bin:$PATH && "
           f"yosys -s {script_path} 2>&1")
    return _pr.run(["docker", "exec", "vibeic-eda", "bash", "-lc", cmd],
                          capture_output=True, text=True).stdout or ""


# ---------------------------------------------------------------------------
# DEFINE-SET MIRROR (rv-aes): the slang gold-read must mirror the synth
# invocation's define set, not read_slang alone. synth reads -DSIMULATION -DYOSYS
# primary and retries -DSYNTHESIS -DYOSYS when a sim-only construct ($urandom /
# std::randomize / $value$plusargs in a dead `ifdef SIMULATION arm) breaks it.
# The LEC gold-read must do the same so the gold matches how synth built the gate
# (else the miter aborts on $urandom).
# ---------------------------------------------------------------------------
def test_slang_gold_read_define_set_is_parameterised_not_hardcoded():
    # default = synth PRIMARY (-DSIMULATION -DYOSYS); the -DSYNTHESIS retry set
    # flows through, dropping -DSIMULATION so the dead sim-only arm is excluded.
    d = lec_run.build_equiv_script(["/g.sv"], "/n.v", "top", None,
                                   gold_frontend="slang")
    # --single-unit: all gold files share ONE compilation unit so a cross-file
    # `define resolves (mirrors successive read_verilog's shared macro scope).
    assert "read_slang --single-unit /g.sv --top top -DSIMULATION -DYOSYS" in d
    s = lec_run.build_equiv_script(["/g.sv"], "/n.v", "top", None,
                                   gold_frontend="slang",
                                   gold_defines="-DSYNTHESIS -DYOSYS")
    slang_line = s.split("read_slang", 1)[1].splitlines()[0]
    assert "-DSYNTHESIS -DYOSYS" in slang_line
    assert "-DSIMULATION" not in slang_line   # sim-only arm excluded


def test_define_retry_reuses_the_synth_frontend_decision():
    # the LEC define-set retry uses the SAME decision the synth path uses (read
    # from the synth invocation, not hardcoded): a $urandom / std::randomize /
    # $value$plusargs signature triggers the -DSYNTHESIS retry; a non-sim-only
    # failure does not.
    import synth_frontend
    # v1.4.x — the decision is the OBSERVABLE (the slang gold read built no
    # miter) + the DESIGN PROPERTY (the gold source branches on the define set),
    # NOT slang's phrasing. Supply the gold RTL that makes the flip meaningful.
    gold_rtl = ("module dut;\n`ifdef SIMULATION\n  initial x = $urandom;\n"
                "`else\n  wire x = 1'b0;\n`endif\nendmodule\n")
    for sig in ("error: unsupported system task '$urandom'",
                "std::randomize", "$value$plusargs",
                # …and a REWORDED abort the old allow-list would have missed:
                "error: system function 'urandom_range' cannot be used in a "
                "constant expression"):
        assert synth_frontend.synth_frontend_should_retry_under_synthesis(
            sig, rtl_text_blob=gold_rtl)[0], sig
    # a genuine failure in a design with NO define-conditional arm must NOT
    # trigger a define retry — the retry would re-read identical source (no leak).
    assert not synth_frontend.synth_frontend_should_retry_under_synthesis(
        "ERROR: Module foo not found",
        rtl_text_blob="module dut; wire x = 1'b0; endmodule\n")[0]


# REAL in-container: the FULL-SoC combo — an async-reset FF AND a $urandom in an
# `ifdef SIMULATION block — reaches a clean verdict via the slang-retry path with
# the -DSYNTHESIS define set + async2sync (no $urandom abort, no async SAT stop).
_AES_LIKE_RTL = (
    "module dut(input clk, input rst_n, input [3:0] d, output reg [3:0] q);\n"
    "`ifdef SIMULATION\n"
    "  initial q = $urandom;   // sim-only, non-synthesizable\n"
    "`endif\n"
    "  always @(posedge clk or negedge rst_n)\n"
    "    if (!rst_n) q <= 4'b0; else q <= d + 4'd1;\n"
    "endmodule\n")


def test_urandom_simblock_plus_async_reaches_verdict_via_synthesis_define(tmp_path):
    work, cleanup = _mounted_workdir(tmp_path)
    if work is None:
        pytest.skip("vibeic-eda container not available / path not bind-mounted")
    try:
        chk = _pr.run(
            ["docker", "exec", "vibeic-eda", "bash", "-lc",
             f"test -f {_SKY130_HD_LIB} && echo ok"],
            capture_output=True, text=True)
        if "ok" not in (chk.stdout or ""):
            pytest.skip("sky130_hd Liberty not present in container")
        (work / "dut.sv").write_text(_AES_LIKE_RTL)
        # sanity: -DSIMULATION slang read DOES die on $urandom (the abort we fix).
        sim_probe = work / "sim_probe.ys"
        sim_probe.write_text(
            f"read_slang {work/'dut.sv'} --top dut -DSIMULATION -DYOSYS\n")
        sim_log = _yosys(sim_probe)
        assert "$urandom" in sim_log, "expected the -DSIMULATION $urandom abort"
        import synth_frontend
        assert synth_frontend.synth_frontend_should_retry_under_synthesis(
            sim_log,
            rtl_text_blob=_AES_LIKE_RTL)[0], \
            "the synth #668 decision must fire on this abort"

        # gate = synth under -DSYNTHESIS (the arm the gate is built from) → dfrtp.
        map_ys = work / "map.ys"
        map_ys.write_text(
            f"read_slang {work/'dut.sv'} --top dut -DSYNTHESIS -DYOSYS\n"
            f"synth -top dut\n"
            f"dfflibmap -liberty {_SKY130_HD_LIB}\n"
            f"abc -liberty {_SKY130_HD_LIB}\n"
            f"write_verilog {work/'gate.v'}\n")
        _yosys(map_ys)
        assert (work / "gate.v").is_file()

        # the recipe main() emits on the -DSYNTHESIS define-retry (slang + async2sync).
        script = lec_run.build_equiv_script(
            [str(work / "dut.sv")], str(work / "gate.v"), "dut",
            _SKY130_HD_LIB, gold_frontend="slang",
            gold_defines="-DSYNTHESIS -DYOSYS")
        eq_ys = work / "equiv.ys"
        eq_ys.write_text(script)
        log = _yosys(eq_ys)
        parsed = lec_run.parse_equiv_output(log)

        assert "unsupported system task '$urandom'" not in log, (
            "the -DSYNTHESIS define set must exclude the sim-only $urandom arm")
        assert "No SAT model available for async" not in log, (
            "async2sync must legalize the async-reset FF")
        assert parsed["verdict"] == "PASS", (parsed, log[-600:])
        assert (parsed["proven"] or 0) > 0 and parsed["unproven"] == 0
    finally:
        cleanup()


def test_async_reset_reaches_verdict_on_slang_path_in_container(tmp_path):
    work, cleanup = _mounted_workdir(tmp_path)
    if work is None:
        pytest.skip("vibeic-eda container not available / path not bind-mounted")
    try:
        (work / "dff_ar.v").write_text(_ASYNC_RTL)
        # is the sky130_hd lib present in the container?
        chk = _pr.run(
            ["docker", "exec", "vibeic-eda", "bash", "-lc",
             f"test -f {_SKY130_HD_LIB} && echo ok"],
            capture_output=True, text=True)
        if "ok" not in (chk.stdout or ""):
            pytest.skip("sky130_hd Liberty not present in container")
        # synth+map the async-reset RTL to sky130 → a dfrtp ($_DFF_PN0_) gate.
        map_ys = work / "map.ys"
        map_ys.write_text(
            f"read_verilog -sv {work/'dff_ar.v'}\n"
            f"synth -top dff_ar\n"
            f"dfflibmap -liberty {_SKY130_HD_LIB}\n"
            f"abc -liberty {_SKY130_HD_LIB}\n"
            f"write_verilog {work/'gate.v'}\n")
        _yosys(map_ys)
        assert (work / "gate.v").is_file(), "mapping did not produce a gate netlist"

        # the ACTUAL lec_run recipe on the SLANG gold-read path.
        script = lec_run.build_equiv_script(
            [str(work / "dff_ar.v")], str(work / "gate.v"), "dff_ar",
            _SKY130_HD_LIB, gold_frontend="slang")
        eq_ys = work / "equiv.ys"
        eq_ys.write_text(script)
        log = _yosys(eq_ys)
        parsed = lec_run.parse_equiv_output(log)

        # MUST reach a real verdict, NOT the async-FF SAT stop.
        assert "No SAT model available for async" not in log, (
            "async2sync should have legalized the async FF; got the SAT stop:\n"
            + log[-600:])
        assert parsed["verdict"] == "PASS", (parsed, log[-600:])
        assert (parsed["proven"] or 0) > 0 and parsed["unproven"] == 0
    finally:
        cleanup()


# ---------------------------------------------------------------------------
# GOLD-FRONTEND SELECTION RULE (v1.4.33) — the slang gold-read must be selected
# by the OBSERVABLE "the built-in reader built no miter", not by an allow-list of
# yosys error PHRASINGS. The old phrasing allow-list silently skipped the capable
# SV-2017 frontend whenever an abort was worded differently, and the verdict fell
# through to a FALSE FAIL with compared_points=0 (ibex, run_v1432int: the
# "Parameter ... with non-constant value" elaboration abort was not in the list).
# ---------------------------------------------------------------------------
_ZERO_MITER = {"parse_error": True, "proven": None, "unproven": None,
               "total": None, "sat_model_unsupported_cells": []}


def test_slang_retry_fires_on_any_zero_miter_even_with_unknown_wording():
    # a zero-miter abort whose wording matches NO signature in
    # _FRONTEND_PARSE_ABORT_RE must STILL select the slang gold read.
    log = "ERROR: something the allow-list has never seen before.\n"
    assert not lec_run.is_frontend_parse_abort(log), (
        "fixture must be an UNKNOWN wording for this test to mean anything")
    retry, why = lec_run.should_retry_gold_with_slang(
        dict(_ZERO_MITER), log, requires_sv2017=False)
    assert retry is True
    assert "no miter" in why           # the observable, not the wording


def test_slang_retry_never_fires_when_a_miter_actually_ran():
    # §4.05 NO-LEAK: a real mismatch (miter ran, points unproven) must never be
    # re-read with a different frontend — that would be verdict shopping.
    parsed = lec_run.parse_equiv_output(MISMATCH_OUTPUT)
    assert parsed["parse_error"] is False and parsed["verdict"] == "FAIL"
    retry, why = lec_run.should_retry_gold_with_slang(
        parsed, MISMATCH_OUTPUT, requires_sv2017=True)
    assert retry is False and why == ""


def test_sv2017_gold_property_is_design_driven(tmp_path):
    # the SV-2017 signal is a property of the RTL TEXT — package / import /
    # package-scope ref / typedef — never a chip name or a path.
    plain = tmp_path / "plain.v"
    plain.write_text("module m(input a, output b); assign b = ~a; endmodule\n")
    assert lec_run.gold_requires_sv2017([str(plain)]) is False

    for src in ("package p; endpackage\n",
                "import p::*;\n",
                "typedef enum {A, B} e_t;\n",
                "module m #(parameter p::e_t X = p::A) (); endmodule\n"):
        f = tmp_path / "sv.sv"
        f.write_text(src)
        assert lec_run.gold_requires_sv2017([str(f)]) is True, src


def test_zero_miter_reason_names_the_sv2017_property_when_present():
    retry, why = lec_run.should_retry_gold_with_slang(
        dict(_ZERO_MITER), "ERROR: unrecognised\n", requires_sv2017=True)
    assert retry is True and "SV-2017" in why


def test_widened_trigger_does_not_widen_the_inconclusive_classification():
    # §4.05: the VERDICT classifier keeps the NARROW signature. A zero-miter run
    # with no frontend-abort evidence (e.g. a yosys crash) stays a hard FAIL and
    # is NOT excused as the non-blocking INCONCLUSIVE.
    log = "ERROR: something the allow-list has never seen before.\n"
    parsed = lec_run.parse_equiv_output(log)
    assert parsed["parse_error"] is True
    assert parsed["verdict"] == "FAIL"
    assert parsed["equivalent"] is False


def test_slang_also_failing_after_the_widened_retry_stays_fail():
    # the widened trigger buys an EXTRA ATTEMPT, never a free pass: if slang also
    # builds no miter the verdict is finalized to FAIL.
    prov = {"verdict": "INCONCLUSIVE", "equivalent": False}
    fin = lec_run.finalize_after_slang_retry(prov, slang_retry_failed=True)
    assert fin["verdict"] == "FAIL" and fin["equivalent"] is False


# ---------------------------------------------------------------------------
# PROVEN-NEGATIVE for the widened gold-frontend trigger (container-backed).
#
# The fix gives the slang gold read MORE chances to run. The load-bearing risk
# is therefore a LEAK: that "try harder to elaborate the gold" quietly turns a
# genuinely NON-EQUIVALENT design into a pass. This test builds an SV-2017 gold
# that ONLY the slang frontend can elaborate (an enum constant from a package
# used as a parameter value — the exact ibex construct), synthesizes the gate
# from the CORRECT source, then CORRUPTS one output bit of the gold and asserts
# the LEC still reports NOT-equivalent through the very same slang path.
# ---------------------------------------------------------------------------
_SV_PKG_GOLD = """\
package op_pkg;
  typedef enum logic [1:0] {OP_AND, OP_OR, OP_XOR} op_e;
endpackage

module sv_alu import op_pkg::*; #(
    parameter op_e MODE = OP_XOR
) (
    input  logic       clk,
    input  logic [3:0] a,
    input  logic [3:0] b,
    output logic [3:0] y
);
  logic [3:0] comb;
  always_comb begin
    unique case (MODE)
      OP_AND:  comb = a & b;
      OP_OR:   comb = a | b;
      default: comb = a ^ b;
    endcase
  end
  always_ff @(posedge clk) y <= {CORRUPT};
endmodule
"""


def _write_sv_gold(path: Path, corrupt: bool) -> None:
    # CORRUPTION = invert bit 0 of the registered output. A real functional
    # difference, invisible to any structural/parse-level check.
    body = "{comb[3:1], ~comb[0]}" if corrupt else "comb"
    path.write_text(_SV_PKG_GOLD.replace("{CORRUPT}", body))


def test_widened_trigger_still_reports_a_corrupted_sv_design_as_not_equivalent(
        tmp_path):
    work, cleanup = _mounted_workdir(tmp_path)
    if work is None:
        pytest.skip("vibeic-eda container not available / path not bind-mounted")
    try:
        chk = _pr.run(
            ["docker", "exec", "vibeic-eda", "bash", "-lc",
             f"test -f {_SKY130_HD_LIB} && echo ok"],
            capture_output=True, text=True)
        if "ok" not in (chk.stdout or ""):
            pytest.skip("sky130_hd Liberty not present in container")

        good = work / "sv_alu.sv"
        _write_sv_gold(good, corrupt=False)

        # PRECONDITION 1: this gold is exactly the class the fix targets.
        assert lec_run.gold_requires_sv2017([str(good)]) is True

        # PRECONDITION 2: the yosys BUILT-IN reader cannot elaborate it (the enum
        # constant from a package used as a parameter value — the ibex
        # construct), so the slang fallback is what decides the verdict below.
        probe = work / "probe.ys"
        probe.write_text(f"read_verilog -sv {good}\nhierarchy -top sv_alu\n")
        probe_log = _yosys(probe)
        assert "ERROR" in probe_log, (
            "fixture no longer defeats the built-in reader — the test would "
            "stop exercising the slang path:\n" + probe_log[-600:])
        # PRECONDITION 3: and that abort is what the trigger keys on.
        assert lec_run.should_retry_gold_with_slang(
            {"parse_error": True}, probe_log,
            requires_sv2017=True)[0] is True

        # gate netlist built from the CORRECT source, mapped to real cells.
        map_ys = work / "map.ys"
        map_ys.write_text(
            f"read_slang {good} --top sv_alu\n"
            f"synth -top sv_alu\n"
            f"dfflibmap -liberty {_SKY130_HD_LIB}\n"
            f"abc -liberty {_SKY130_HD_LIB}\n"
            f"write_verilog {work/'gate.v'}\n")
        _yosys(map_ys)
        assert (work / "gate.v").is_file(), "slang synth produced no gate netlist"

        def _verdict(gold: Path, ys_name: str) -> dict:
            script = lec_run.build_equiv_script(
                [str(gold)], str(work / "gate.v"), "sv_alu", _SKY130_HD_LIB,
                gold_frontend="slang")
            ys = work / ys_name
            ys.write_text(script)
            return lec_run.parse_equiv_output(_yosys(ys))

        # POSITIVE: the honest gold proves equivalent through the slang path.
        ok = _verdict(good, "equiv_ok.ys")
        assert ok["verdict"] == "PASS", ok
        assert (ok["proven"] or 0) > 0 and ok["unproven"] == 0

        # NEGATIVE (load-bearing): one inverted output bit must NOT pass.
        bad = work / "sv_alu_bad.sv"
        _write_sv_gold(bad, corrupt=True)
        broken = _verdict(bad, "equiv_bad.ys")
        assert broken["verdict"] != "PASS", (
            "LEAK: a functionally corrupted design passed LEC through the "
            "widened slang gold-read path: " + repr(broken))
        assert broken["equivalent"] is False
        assert (broken["unproven"] or 0) > 0
    finally:
        cleanup()


# ---------------------------------------------------------------------------
# BUDGET EXHAUSTION (#155 merge — EVIDENCE-BASED split). A killed equiv run
# compared 0 points, so a PURE timeout carries NO mismatch evidence → a DISCLOSED
# budget skip (SKIPPED-CONDITION): a VISIBLE non-PASS, never a spurious FAIL
# (origin #155: don't fail sha256's >1200s proof) and never a silent free pass
# (local: a resource limit is never a free pass — equivalent stays False). BUT a
# timeout log that RECORDED a mismatch/counterexample before the kill is a real
# FAIL (a proven non-equivalence is a fail regardless of the wall clock).
# ---------------------------------------------------------------------------
def test_pure_timeout_is_skipped_condition_visible_non_pass():
    log = "Yosys 0.67\n" + lec_run._TIMEOUT_MARKER + " after 1800s"
    parsed = lec_run.parse_equiv_output(log)
    assert parsed["parse_error"] is True
    assert parsed["verdict"] == "SKIPPED-CONDITION"  # origin #155: not a spurious FAIL
    assert parsed["equivalent"] is False             # local: never a free pass
    assert "budget" in parsed["verdict_explanation"].lower()
    assert "never a silent free pass" in parsed["verdict_explanation"]


def test_timeout_with_recorded_mismatch_is_a_real_fail():
    # a counterexample RECORDED before the wall-clock kill escalates to FAIL —
    # a proven non-equivalence is a real fail regardless of the timeout.
    log = ("Yosys 0.67\n"
           "equiv_simple found a counterexample for \\out[3]\n"
           + lec_run._TIMEOUT_MARKER + " after 1800s")
    parsed = lec_run.parse_equiv_output(log)
    assert parsed["parse_error"] is True
    assert parsed["verdict"] == "FAIL"               # real mismatch beats the timeout
    assert parsed["equivalent"] is False
    assert "mismatch" in parsed["verdict_explanation"].lower()


def test_timeout_wording_does_not_leak_into_a_real_mismatch():
    # a miter that RAN keeps the mismatch wording even if the text is noisy.
    parsed = lec_run.parse_equiv_output(MISMATCH_OUTPUT)
    assert parsed["verdict"] == "FAIL"
    assert "time budget" not in parsed["verdict_explanation"]


def test_yosys_budget_is_tunable_and_defaults_above_the_runner_observed_need():
    # ibex's slang miter exceeded 1800s; the default must leave real headroom
    # and must be overridable per invocation.
    assert lec_run.DEFAULT_YOSYS_TIMEOUT_S >= 3600
    import inspect
    sig = inspect.signature(lec_run.run_yosys_equiv)
    assert sig.parameters["timeout"].default == lec_run.DEFAULT_YOSYS_TIMEOUT_S


# ---------------------------------------------------------------------------
# RUNNER/PRODUCER TIMEOUT INVARIANT. design_one_shot_runner wraps lec_run in a
# subprocess timeout. When that OUTER budget is smaller than the producer's own
# INNER budget, the runner kills lec_run mid-miter and the LEC verdict falls
# through to a disclosed-skip — the enhancement runs but never lands a verdict.
# The two were hard-coded independently (outer 1200s vs inner 1800s) and drifted.
# ---------------------------------------------------------------------------
def test_runner_outer_timeout_exceeds_the_producer_worst_case():
    import design_one_shot_runner as runner
    inner = runner.lec_producer_yosys_timeout_s()
    assert inner == lec_run.DEFAULT_YOSYS_TIMEOUT_S, (
        "the runner must READ the producer's budget, not restate it")
    # lec_run makes up to three yosys invocations (built-in gold read, slang
    # gold read, slang -DSYNTHESIS define retry).
    src = (Path(runner.__file__).read_text()).split(
        "Step 13 — LEC (RTL ≡ handoff netlist)", 1)[1]
    assert "3 * lec_producer_yosys_timeout_s()" in src
    assert "timeout=1200" not in src


# ---------------------------------------------------------------------------
# NO-COMPLETED-COMPARISON KILL (measured: opentitan_aes × sky130A, this run).
#
# A miter WAS built (`Found N unproven $equiv cells (N groups) in equiv:` →
# total known → not parse_error) but the proof was CUT OFF mid-equiv_simple:
# NO `N proven / M unproven` completion line, NO `Proved N` line, NO
# counterexample — and NO wall-budget marker (the kill did NOT route through
# run_yosys_equiv's rc 124/137 / TimeoutExpired paths; e.g. an external SIGKILL
# that left a stale artifact, a docker-daemon restart, an OOM with a different
# rc). Before this fix the parser fell through to the final `else` and booked
# it FAIL "may genuinely differ" — a fabricated non-equivalence from a run that
# decided ZERO points. The real opentitan_aes Step-13 lec.json was exactly this
# (only ~1720/31850 cells attempted, no equiv_status), and that false FAIL
# blocked 24 downstream steps. This is the OBSERVABLE-keyed safety net behind
# the marker path: no decided points + no counterexample = no evidence in
# EITHER direction → INCONCLUSIVE, never FAIL, never PASS.
# ---------------------------------------------------------------------------
def test_killed_mid_proof_no_marker_is_inconclusive_not_fail():
    # POSITIVE control (FAILS against the byte-identical pre-fix file, PASSES
    # after): the killed-mid-equiv_simple shape with NO marker is INCONCLUSIVE.
    p = lec_run.parse_equiv_output(_KILLED_MID_PROOF)
    assert p["parse_error"] is False            # a miter WAS built (total known)
    assert p["total"] == 27904
    assert p["proven"] is None and p["unproven"] is None   # nothing decided
    assert p["verdict"] == "INCONCLUSIVE"       # NOT the fabricated FAIL
    assert p["equivalent"] is False             # never a fake pass
    expl = p["verdict_explanation"].lower()
    assert "no decided points" in expl or "cut off" in expl


def test_killed_mid_proof_no_marker_gate_is_non_blocking(tmp_path):
    # END-TO-END: the downstream gate resolves the INCONCLUSIVE report to a
    # non-blocking WAIVED-DEFERRED (rc 3), NOT the LEC_NOT_EQUIVALENT hard FAIL
    # that cascade-marked 24 downstream steps MISSING.
    p = lec_run.parse_equiv_output(_KILLED_MID_PROOF)
    r = lec_run.build_report(p, "chip_top", "netlist.v", None)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "lec.json").write_text(json.dumps(r))
    (tmp_path / "reports" / "lec.rpt").write_text(_KILLED_MID_PROOF)
    res = gate.audit(tmp_path)
    assert res.inconclusive is True
    assert res.passed is False                  # never a vacuous PASS
    assert "LEC_NOT_EQUIVALENT" not in {f.rule for f in res.findings}
    assert gate.main([str(tmp_path)]) == 3      # non-blocking, not a PASS


def test_completed_unproven_no_marker_no_ctrex_still_fails():
    # REVERSE control (must STILL pass — this is what catches a fix that
    # "tightened the filter until the count hit zero"): a COMPLETED miter that
    # left points unproven is a genuine non-equivalence and must STAY FAIL even
    # with NO marker and NO explicit counterexample phrase. The discriminator
    # is a decided per-point verdict (proven parsed), which _no_completed_
    # comparison is False for — so the softening can NEVER reach a real mismatch.
    done_fail = ("Yosys 0.67+\n"
                 "Found 8 $equiv cells (8 groups) in equiv:\n"
                 "  Of those cells 0 are proven and 8 are unproven.\n")
    p = lec_run.parse_equiv_output(done_fail)
    assert p["parse_error"] is False
    assert p["proven"] == 0 and p["unproven"] == 8   # a DECIDED verdict exists
    assert p["verdict"] == "FAIL"                     # NOT laundered to INCONCLUSIVE


def test_killed_mid_proof_with_counterexample_still_fails():
    # NO-LEAK: if a killed-mid-proof log ALSO recorded a counterexample, the
    # proven difference stands regardless of the missing completion line.
    txt = (_KILLED_MID_PROOF
           + "\nequiv_induct: proved the designs are non-equivalent\n")
    p = lec_run.parse_equiv_output(txt)
    assert p["proven"] is None and p["unproven"] is None
    assert p["verdict"] == "FAIL"               # counterexample overrides


# ---------------------------------------------------------------------------
# A DEADLINE THAT A RETRY RE-ARMS IS NOT A DEADLINE (measured 2026-08-27).
# ---------------------------------------------------------------------------
# Live evidence, VerilogEval-Human sweep `_vehuman_clean156` on a 156-problem
# run whose MEDIAN problem takes ~30s: `Prob030_popcount255` (a 255-bit popcount
# whose `equiv_induct` is combinatorially explosive) ground for the full 7195s
# gold-read budget, was killed, and then STARTED OVER — `reports/lec_equiv.ys`
# was rewritten 2h later with `read_slang`, proving the slang gold-read retry
# fired on a TIMEOUT and was handed a FRESH full budget. Two independent
# defects, and both are guarded below:
#   (1) the retry fired on a failure class it was not written for (a killed run,
#       not a failed gold read);
#   (2) every attempt was handed the same constant `args.timeout`, so the real
#       bound was `timeout x attempts` and nothing counted total elapsed.
# ---------------------------------------------------------------------------
_BUDGET_KILLED_GOLD = (
    "equiv_make: Creating equivalence miter.\n"
    "equiv_induct: Proving $equiv cells in module equiv.\n"
    + lec_run._TIMEOUT_MARKER + " after 7195s\n"
)


class _FakeClock:
    """Injectable monotonic clock, so the ceiling is tested without spending it."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, d: float) -> None:
        self.t += d


def test_a_retry_cannot_rearm_the_step_deadline():
    # POLE A — the ceiling is the TOTAL across attempts, measured from the
    # FIRST. After attempt 1 grinds to the deadline there is NOTHING left, so
    # the sweep moves on instead of starting the same problem over.
    clk = _FakeClock()
    b = lec_run.StepBudget(7195, clock=clk)
    assert b.next_attempt_budget() == 7195      # attempt 1: the full budget
    clk.advance(7195)                           # ...ground to the deadline
    b.record("verilog", "-DSIMULATION -DYOSYS", 7195, 7195.0, True, True)
    assert b.next_attempt_budget() == 0, (
        "a second attempt must NOT be handed a fresh budget — that is the "
        "defect: total time became `deadline x attempts`")
    assert b.exhausted() is True


def test_each_attempt_draws_down_the_same_deadline():
    # The budget is strictly non-increasing: a retry can only ever SHRINK it.
    clk = _FakeClock()
    b = lec_run.StepBudget(600, clock=clk)
    seen = []
    for spend in (100, 200, 280):
        seen.append(b.next_attempt_budget())
        clk.advance(spend)
        b.record("verilog", "-DSIMULATION -DYOSYS", seen[-1], spend, True,
                 False)
    assert seen == [600, 500, 300]
    assert all(seen[i] > seen[i + 1] for i in range(len(seen) - 1))
    assert b.next_attempt_budget() == 0     # 580 spent, 20 left < floor


def test_budget_floor_refuses_a_pointless_sliver():
    clk = _FakeClock()
    b = lec_run.StepBudget(600, floor_s=30, clock=clk)
    clk.advance(571)
    b.record("verilog", "-DSIMULATION -DYOSYS", 600, 571.0, True, False)
    assert b.remaining_s() == 29
    assert b.next_attempt_budget() == 0, (
        "0 must mean DO NOT LAUNCH, never launch-with-no-limit")


def test_the_floor_never_blocks_the_first_attempt():
    # The floor refuses a pointless RETRY. A tight operator --timeout must
    # still RUN — turning it into "no run at all" would produce no evidence.
    b = lec_run.StepBudget(5, floor_s=30, clock=_FakeClock())
    assert b.next_attempt_budget() == 5


def test_slang_retry_does_not_fire_on_a_wall_budget_kill():
    # FINDING 2 — the retry is for a gold read that FAILED. This gold read did
    # not fail: it succeeded and the RUN was killed at its deadline, mid-proof.
    # Re-reading the gold with a different frontend cannot make a
    # combinatorially explosive proof cheap, and costs another full budget.
    parsed = lec_run.parse_equiv_output(_BUDGET_KILLED_GOLD)
    assert parsed["parse_error"] is True, (
        "a mid-proof kill leaves no equiv_status, so it looks exactly like a "
        "zero-miter gold-read abort to the parser — that is why it fired")
    retry, why = lec_run.should_retry_gold_with_slang(
        parsed, _BUDGET_KILLED_GOLD, requires_sv2017=True)
    assert retry is False, (
        "a budget kill must not select the slang gold-read retry")
    # THE REASON IS PUBLISHED, so it may not be empty. This function's second
    # return value reaches reports/lec.json through `gold_frontend_reason`
    # (lec_run.py: `report["gold_frontend_reason"] = gold_frontend_reason or
    # None`) and is printed on the operator-facing decline line. An empty string
    # there renders a decline that HAD a reason byte-identically to a run in
    # which nothing happened -- the absent-measurement-rendered-as-a-real-one
    # defect this file exists to refuse.
    #
    # `why == ""` was an OVER-SPECIFICATION: it held only while the path had no
    # voice, and it was never what this test is about -- the failure message
    # above names the decline and nothing else. The behavioural claim is
    # unchanged and still fully asserted; what is added is that the decline must
    # say why. See test_lec_bounded_proof.py::BudgetKillIsNotAFrontendFailure::
    # test_budget_killed_log_blocks_the_retry, which asserts the same reason
    # from the other side.
    assert why and "was NOT the failure" in why, (
        "a budget-kill decline must carry its reason; an empty one is "
        "indistinguishable from a run in which nothing happened")


def test_the_budget_kill_verdict_is_neither_pass_nor_fail():
    # (c) A timed-out proof gets the honest outcome. Both mislabels are
    # available and both are wrong: PASS would record an unfinished equivalence
    # proof as proven; FAIL would call designs different that may well be
    # equivalent. The verdict must be the disclosed non-PASS tier.
    parsed = lec_run.parse_equiv_output(_BUDGET_KILLED_GOLD)
    assert parsed["verdict"] in ("SKIPPED-CONDITION", "INCONCLUSIVE")
    assert parsed["equivalent"] is False


def test_budget_annotation_carries_attempts_elapsed_and_the_resource():
    # (c) the outcome must SAY what was attempted, which resource ran out, and
    # how many attempts were made — the evidence whose absence made a re-armed
    # deadline indistinguishable from progress.
    clk = _FakeClock()
    b = lec_run.StepBudget(600, clock=clk)
    b.record("verilog", "-DSIMULATION -DYOSYS", 600, 600.0, True, True)
    clk.advance(600)
    rep = {"verdict": "SKIPPED-CONDITION", "equivalent": False,
           "verdict_explanation": "Yosys equiv exceeded its time budget."}
    out = lec_run.annotate_step_budget(rep, b)
    # ADDITIVE — the verdict itself is never rewritten.
    assert out["verdict"] == "SKIPPED-CONDITION"
    assert out["equivalent"] is False
    assert out["lec_attempts"] == 1
    assert out["step_budget_sec"] == 600
    assert out["step_budget_exhausted"] is True
    assert out["exhausted_resource"] == "wall_clock_seconds"
    assert "1 attempt(s)" in out["verdict_explanation"]
    assert out["lec_attempts_detail"][0]["killed_by_budget"] is True


def test_budget_annotation_names_no_resource_when_nothing_ran_out():
    clk = _FakeClock()
    b = lec_run.StepBudget(600, clock=clk)
    b.record("verilog", "-DSIMULATION -DYOSYS", 600, 30.0, True, False)
    clk.advance(30)
    out = lec_run.annotate_step_budget({"verdict": "PASS", "equivalent": True,
                                        "verdict_explanation": "ok"}, b)
    assert out["verdict"] == "PASS" and out["equivalent"] is True
    assert out["step_budget_exhausted"] is False
    assert out["exhausted_resource"] is None
    assert out["verdict_explanation"] == "ok"   # untouched


def test_a_skipped_retry_is_recorded_not_silently_dropped():
    b = lec_run.StepBudget(600, clock=_FakeClock())
    b.record("verilog", "-DSIMULATION -DYOSYS", 600, 600.0, True, True)
    b.skipped("slang", "-DSIMULATION -DYOSYS", "step wall budget exhausted")
    assert b.count_launched() == 1              # the skipped one is not an attempt
    assert len(b.attempts) == 2                 # ...but it IS on the record
    assert b.attempts[1]["not_launched_reason"] == "step wall budget exhausted"


# --- CONTROLS: the recovery must survive, and normal problems must not move ---

def test_a_genuine_gold_read_failure_still_retries_with_slang():
    # POLE B — the control proving the loop was BOUNDED, not DELETED. A real
    # gold-read failure (the reason this retry exists) carries no budget-kill
    # marker, so it still selects the capable SV-2017 frontend and recovers.
    for log in (_FRONTEND_ABORT_OUTPUT, _IBEX_ELAB_ABORT, GARBAGE_OUTPUT):
        assert lec_run._TIMEOUT_RE.search(log) is None, (
            "fixture must be a genuine READ failure, not a budget kill")
        retry, why = lec_run.should_retry_gold_with_slang(
            dict(_ZERO_MITER), log, requires_sv2017=True)
        assert retry is True and why, (
            f"the gold-read recovery must still fire on: {log[:60]!r}")


def test_a_normal_problem_is_unchanged_by_the_budget():
    # POLE C — the control proving the benchmark still measures what it did.
    # A median (~30s) problem runs ONE attempt, gets the full budget, passes,
    # and selects no retry.
    parsed = lec_run.parse_equiv_output(PASS_OUTPUT)
    assert parsed["verdict"] == "PASS" and parsed["equivalent"] is True
    assert lec_run.should_retry_gold_with_slang(
        parsed, PASS_OUTPUT, requires_sv2017=True) == (False, "")
    clk = _FakeClock()
    b = lec_run.StepBudget(7195, clock=clk)
    assert b.next_attempt_budget() == 7195, (
        "attempt 1 must get exactly the budget it got before the fix")
    clk.advance(30)
    b.record("verilog", "-DSIMULATION -DYOSYS", 7195, 30.0, True, False)
    rep = lec_run.annotate_step_budget(dict(parsed), b)
    assert rep["verdict"] == "PASS" and rep["equivalent"] is True
    assert rep["lec_attempts"] == 1 and rep["step_budget_exhausted"] is False


def test_a_real_mismatch_still_fails_and_never_retries():
    # §4.05 NO-LEAK regression: bounding the retry must not let a genuine
    # non-equivalence become anything other than FAIL.
    parsed = lec_run.parse_equiv_output(MISMATCH_OUTPUT)
    assert parsed["verdict"] == "FAIL"
    assert lec_run.should_retry_gold_with_slang(
        parsed, MISMATCH_OUTPUT, requires_sv2017=True) == (False, "")


# --- THE RATCHET: fails if a future change lets a retry re-arm a deadline ---

def test_no_yosys_attempt_may_be_handed_a_fresh_full_budget():
    """RATCHET. The defect was `timeout=args.timeout` inside the closure that
    drives the gold-read retries: a CONSTANT, re-armed on every attempt. Every
    attempt must draw from the shared StepBudget deadline instead.

    This test FAILS if a future change reintroduces a per-attempt deadline."""
    src = SCRIPT.read_text(encoding="utf-8")
    body = src[src.index("def main("):]
    assert "timeout=args.timeout" not in body, (
        "a yosys attempt is being handed the raw --timeout again: that is a "
        "PER-ATTEMPT deadline, which a retry re-arms. Draw from "
        "StepBudget.next_attempt_budget() so the ceiling is the TOTAL.")
    assert "budget.next_attempt_budget()" in body, (
        "the attempt budget must come from the shared StepBudget deadline")
    # every retry decision must consult the ceiling before launching
    assert body.count("budget.next_attempt_budget() == 0") >= 2, (
        "each retry site must refuse to launch on a spent budget")


def test_the_retry_decision_still_guards_the_budget_kill_class():
    """RATCHET. Fails if the budget-kill guard is removed from the retry
    decision, letting a timeout select the gold-read retry again."""
    src = SCRIPT.read_text(encoding="utf-8")
    fn = src[src.index("def should_retry_gold_with_slang("):]
    fn = fn[:fn.index("\ndef ")]
    assert "_TIMEOUT_RE.search(gold_log)" in fn, (
        "a wall-budget kill must not select the gold-read retry")


# ---------------------------------------------------------------------------
# END-TO-END through the REAL main(), with a fast stub and an injected clock.
# Reproduces the measured stall in milliseconds instead of four hours.
# On the code as it stood 2026-08-27 the first case launched TWO attempts,
# EACH handed the full budget: [('verilog', 1), ('slang', 1)] — verilog then
# slang, exactly the transition the live run's rewritten `lec_equiv.ys` showed.
# ---------------------------------------------------------------------------
_E2E_RTL = "module m(input a, input b, output y); assign y = a & b; endmodule\n"
_E2E_GATE = ("module m(input a, input b, output y);\n"
             "  AND2X1 u0 (.A(a), .B(b), .Y(y));\n"
             "endmodule\n")
_E2E_GRIND = ("equiv_make: Creating equivalence miter.\n"
              "equiv_induct: Proving $equiv cells in module equiv.\n")
_E2E_PASS = ("equiv_status: Found 4 $equiv cells in equiv:\n"
             "  of which 4 are proven and 0 are unproven.\n"
             "  Equivalence successfully proven!\n")
_E2E_READ_FAIL = "ERROR: syntax error, unexpected TOK_PACKAGE\n"


def _drive_lec(monkeypatch, tmp_path, stub, timeout_s, spend_per_attempt=0.0):
    """Run the REAL lec_run.main() with yosys stubbed and a fake clock."""
    clk = _FakeClock()
    calls = []

    class _ClockedBudget(lec_run.StepBudget):
        def __init__(self, total_s, floor_s=lec_run._MIN_ATTEMPT_BUDGET_S,
                     clock=None):
            super().__init__(total_s, floor_s=floor_s, clock=clk)

    def _fake_yosys(container, ys, timeout=None, workdir=None):
        script = Path(ys).read_text(encoding="utf-8")
        frontend = "slang" if "read_slang" in script else "verilog"
        calls.append({"budget": timeout, "frontend": frontend})
        clk.advance(spend_per_attempt)
        return stub(len(calls), frontend)

    monkeypatch.setattr(lec_run, "StepBudget", _ClockedBudget)
    monkeypatch.setattr(lec_run, "run_yosys_equiv", _fake_yosys)
    monkeypatch.setattr(lec_run, "_container_available", lambda c: True)

    proj = tmp_path / "proj"
    (proj / "phase2/stage1/rtl").mkdir(parents=True)
    (proj / "phase2/stage2/synth").mkdir(parents=True)
    (proj / "reports").mkdir(parents=True)
    (proj / "phase2/stage1/rtl/m.v").write_text(_E2E_RTL, encoding="utf-8")
    (proj / "phase2/stage2/synth/netlist.v").write_text(_E2E_GATE,
                                                        encoding="utf-8")
    rc = lec_run.main([str(proj), "--top", "m", "--timeout", str(timeout_s),
                       "--container", "none", "--liberty", "/nonexistent"])
    rep = json.loads((proj / "reports/lec.json").read_text(encoding="utf-8"))
    return rc, rep, calls


def test_e2e_a_ground_out_proof_stops_instead_of_starting_over(monkeypatch,
                                                               tmp_path):
    """POLE A. The measured stall: attempt 1 grinds to the deadline. The step
    must STOP and report, not re-arm the deadline and start the same problem
    over. On the unfixed code this launched a second full-budget attempt."""
    rc, rep, calls = _drive_lec(
        monkeypatch, tmp_path,
        lambda n, fe: (True, _E2E_GRIND + lec_run._TIMEOUT_MARKER + " after 600s\n"),
        timeout_s=600, spend_per_attempt=600.0)

    assert len(calls) == 1, f"a SECOND attempt was launched: {calls}"
    assert rep["lec_attempts"] == 1
    assert rep["step_budget_exhausted"] is True
    assert rep["exhausted_resource"] == "wall_clock_seconds"
    # the honest outcome: NOT proven, NOT disproven
    assert rep["verdict"] in ("SKIPPED-CONDITION", "INCONCLUSIVE")
    assert rep["equivalent"] is False
    assert "1 attempt(s)" in rep["verdict_explanation"]
    assert rep["lec_attempts_detail"][0]["killed_by_budget"] is True
    assert rc == 0          # a truthful verdict was written; the sweep moves on


def test_e2e_b_a_real_gold_read_failure_still_recovers(monkeypatch, tmp_path):
    """POLE B. The control proving the loop was BOUNDED, not DELETED: a genuine
    gold-read failure still selects slang and still recovers to PASS. A real
    read failure aborts in SECONDS, so the total budget is still nearly whole —
    which is exactly why bounding the total does not cost this recovery."""
    rc, rep, calls = _drive_lec(
        monkeypatch, tmp_path,
        lambda n, fe: (True, _E2E_READ_FAIL) if fe == "verilog"
        else (True, _E2E_PASS),
        timeout_s=600, spend_per_attempt=2.0)

    assert len(calls) == 2, f"the slang recovery did NOT fire: {calls}"
    assert calls[1]["frontend"] == "slang"
    assert rep["verdict"] == "PASS" and rep["equivalent"] is True
    assert rep["gold_frontend"] == "slang"
    assert rep["lec_attempts"] == 2
    # the deadline was DRAWN DOWN, never re-armed
    assert calls[1]["budget"] < calls[0]["budget"], (
        f"the retry re-armed the deadline: {calls}")


def test_e2e_c_a_normal_problem_is_unchanged(monkeypatch, tmp_path):
    """POLE C. The control proving the benchmark still measures what it did:
    one attempt, the FULL budget, the same PASS with the same evidence."""
    rc, rep, calls = _drive_lec(
        monkeypatch, tmp_path, lambda n, fe: (True, _E2E_PASS),
        timeout_s=7195, spend_per_attempt=30.0)

    assert len(calls) == 1
    assert calls[0]["budget"] == 7195, (
        "attempt 1 must receive exactly the budget it received before the fix")
    assert rep["verdict"] == "PASS" and rep["equivalent"] is True
    assert rep["compared_points"] == 4 and rep["unproven_points"] == 0
    assert rep["step_budget_exhausted"] is False
    assert rep["exhausted_resource"] is None
    assert rc == 0


def test_e2e_a_tight_operator_budget_still_runs_once(monkeypatch, tmp_path):
    """A `--timeout` SMALLER than the retry floor must still run the first
    attempt. The floor refuses a pointless RETRY; it must never turn a tight
    budget into a step that produces no evidence at all."""
    rc, rep, calls = _drive_lec(
        monkeypatch, tmp_path, lambda n, fe: (True, _E2E_PASS),
        timeout_s=5, spend_per_attempt=1.0)
    assert len(calls) == 1 and calls[0]["budget"] == 5
    assert rep["verdict"] == "PASS"
