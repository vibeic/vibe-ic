"""Unit tests for formal_property_run.py pure helpers (Step 5 runner).

Covers the sby-log parse (proved / failed / depth / cex / engine), the .sby
config parse (per-task mode/depth/engine), the bounded-vs-unbounded strength
classifier, the results.json builder (all_proved / verdict logic), and the
harness/.sby emitters. No docker, no SymbiYosys — pure-function tests only.

These are the parse/emit fixtures pinned to the REAL spm run transcript so a
regression in the parser is caught deterministically.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import formal_property_run as FPR  # noqa: E402

# A verbatim slice of the real spm SymbiYosys transcript (both tasks PASS).
_REAL_SPM_LOG = """\
SBY  8:39:51 [formal_spm_formal_safety] engine_0: abc pdr
SBY  8:39:53 [formal_spm_formal_safety] engine_0: Property proved.  Time = 1.82 sec
SBY  8:39:53 [formal_spm_formal_safety] engine_0: Status returned by engine: PASS
SBY  8:39:53 [formal_spm_formal_safety] summary: engine_0 (abc pdr) returned PASS
SBY  8:39:53 [formal_spm_formal_safety] DONE (PASS, rc=0)
SBY  8:39:54 [formal_spm_formal_bmc] engine_0: abc bmc3
SBY  8:39:55 [formal_spm_formal_bmc] engine_0: No output asserted in 12 frames. Time = 2.56 sec
SBY  8:39:55 [formal_spm_formal_bmc] engine_0: Status returned by engine: PASS
SBY  8:39:55 [formal_spm_formal_bmc] summary: engine_0 (abc bmc3) returned PASS
SBY  8:39:55 [formal_spm_formal_bmc] DONE (PASS, rc=0)
"""

_FAIL_LOG = """\
SBY  9:00:00 [t_bmc] engine_0: abc bmc3
SBY  9:00:00 [t_bmc] engine_0: Output 2 of miter "model/design_aiger" was asserted in frame 2. Time = 0.03 sec
SBY  9:00:00 [t_bmc] engine_0: Status returned by engine: FAIL
SBY  9:00:00 [t_bmc] DONE (FAIL, rc=2)
"""

_SPM_SBY = FPR.emit_sby(["spm.v"], "formal_spm.sv", "formal_spm",
                        safety_depth=20, bmc_depth=12)


# ── bound_kind ─────────────────────────────────────────────────────────────
def test_bound_kind_strength():
    assert FPR.bound_kind("prove", "PASS") == "unbounded"
    assert FPR.bound_kind("bmc", "PASS") == "bounded"
    assert FPR.bound_kind("cover", "PASS") == "reachable"
    assert FPR.bound_kind("bmc", "FAIL") == "cex"
    assert FPR.bound_kind("prove", "UNKNOWN") == "inconclusive"


# ── parse_sby_config ───────────────────────────────────────────────────────
def test_parse_sby_config_per_task():
    cfg = FPR.parse_sby_config(_SPM_SBY)
    assert set(cfg) == {"safety", "bmc"}
    assert cfg["safety"].mode == "prove" and cfg["safety"].depth == 20
    assert cfg["bmc"].mode == "bmc" and cfg["bmc"].depth == 12
    assert "pdr" in cfg["safety"].engine
    assert "bmc3" in cfg["bmc"].engine


def test_parse_sby_config_single_task():
    cfg = FPR.parse_sby_config(
        "[options]\nmode bmc\ndepth 30\n[engines]\nabc bmc3\n")
    assert set(cfg) == {""}
    assert cfg[""].mode == "bmc" and cfg[""].depth == 30


# ── parse_sby_log ──────────────────────────────────────────────────────────
def test_parse_sby_log_pass_multitask():
    cfg = FPR.parse_sby_config(_SPM_SBY)
    lp = FPR.parse_sby_log(_REAL_SPM_LOG, sby_stem="formal_spm_formal",
                           seed=cfg)
    assert set(lp.tasks) == {"safety", "bmc"}
    assert lp.tasks["safety"].status == "PASS"
    assert lp.tasks["bmc"].status == "PASS"
    assert lp.all_pass and not lp.any_fail
    # engine + mode/depth carried from seed
    assert lp.tasks["safety"].bound_kind == "unbounded"
    assert lp.tasks["bmc"].bound_kind == "bounded"
    assert lp.tasks["bmc"].depth == 12


def test_parse_sby_log_fail_captures_cex_frame():
    lp = FPR.parse_sby_log(_FAIL_LOG, sby_stem="t")
    assert lp.tasks["bmc"].status == "FAIL"
    assert lp.tasks["bmc"].cex_frame == 2
    assert lp.any_fail and not lp.all_pass


def test_parse_sby_log_empty_is_not_allpass():
    lp = FPR.parse_sby_log("", sby_stem="x")
    assert not lp.all_pass          # no tasks -> not proved


# ── build_results ──────────────────────────────────────────────────────────
def test_build_results_all_proved_true():
    cfg = FPR.parse_sby_config(_SPM_SBY)
    lp = FPR.parse_sby_log(_REAL_SPM_LOG, sby_stem="formal_spm_formal",
                           seed=cfg)
    r = FPR.build_results("formal_spm", cfg, lp,
                          "phase2/stage1/formal/x.sby.log",
                          "phase2/stage1/formal/x.sby")
    assert r["all_proved"] is True
    assert r["verdict"] == "PASS"
    assert r["property_count"] == 2 and r["proved"] == 2 and r["failed"] == 0
    # honest disclosure: BOTH an unbounded and a bounded line present
    joined = " ".join(r["bounded_vs_unbounded"]).lower()
    assert "unbounded" in joined and "bounded" in joined and "depth 12" in joined
    assert r["evidence"].endswith(".sby.log")


def test_build_results_one_fail_blocks_all_proved():
    cfg = FPR.parse_sby_config("[tasks]\nbmc bmc\n[options]\nbmc: mode bmc\n"
                               "bmc: depth 12\n[engines]\nbmc: abc bmc3\n")
    lp = FPR.parse_sby_log(_FAIL_LOG.replace("t_bmc", "cfg_bmc"),
                           sby_stem="cfg", seed=cfg)
    r = FPR.build_results("cfg", cfg, lp, "e/log", "e/sby")
    assert r["all_proved"] is False
    assert r["verdict"] == "FAIL"
    assert r["failed"] == 1
    # the failing task discloses its counterexample frame
    bmc = [p for p in r["properties"] if p["task"] == "bmc"][0]
    assert bmc["bound"] == "cex" and bmc["cex_frame"] == 2


def test_completed_result_cites_denominator_sby_transcript_and_scope(tmp_path):
    import json
    formal = tmp_path / "phase2" / "stage1" / "formal"
    formal.mkdir(parents=True)
    harness = formal / "formal_dut.sv"
    harness.write_text(
        "module formal_dut(input clk); always @(posedge clk) assert (1'b1); endmodule\n")
    (formal / "property_contract.json").write_text(json.dumps({
        "property_denominator": 1,
        "authored_property_count": 1,
        "unresolved_obligations": [],
    }))
    result = {
        "verdict": "PASS", "all_proved": True,
        "sby": "phase2/stage1/formal/dut.sby",
        "evidence": "phase2/stage1/formal/dut.sby.log",
        "bounded_vs_unbounded": ["property PROVED UNBOUNDED"],
    }
    FPR._attach_property_contract(result, formal, harness)
    assert result["property_denominator"] == 1
    assert result["authored_property_count"] == 1
    assert result["elaborated_sby"] == result["sby"]
    assert result["proof_transcript"] == result["evidence"]
    assert result["bounded_vs_unbounded_scope"] == [
        "property PROVED UNBOUNDED"]


def test_expert_request_without_invocation_receipt_stays_incomplete(tmp_path):
    import json
    formal = tmp_path / "phase2" / "stage1" / "formal"
    formal.mkdir(parents=True)
    harness = formal / "formal_dut.sv"
    harness.write_text(
        "module formal_dut(input clk); always @(posedge clk) assert (1'b1); endmodule\n")
    requested = {"id": "L6.fsm_state.IDLE", "layer": "L6",
                 "description": "declared IDLE transition", "status": "UNAUTHORED"}
    (formal / "property_contract.json").write_text(json.dumps({
        "property_denominator": 1,
        "authored_property_count": 1,
        "unresolved_obligations": [],
    }))
    (formal / "formal_authoring_request.json").write_text(json.dumps({
        "property_denominator": 1,
        "unresolved_obligations": [requested],
    }))
    result = {
        "verdict": "PASS", "all_proved": True,
        "sby": "phase2/stage1/formal/dut.sby",
        "evidence": "phase2/stage1/formal/dut.sby.log",
        "bounded_vs_unbounded": ["property PROVED UNBOUNDED"],
    }
    FPR._attach_property_contract(result, formal, harness)
    assert result["verdict"] == "INCOMPLETE"
    assert result["expert_fallback_required"] is True
    assert result["expert_fallback_invoked"] is False
    assert [row["id"] for row in result["unresolved_obligations"]] == [
        "L6.fsm_state.IDLE"]


def test_invoked_expert_receipt_closes_exact_request_id(tmp_path):
    import json
    formal = tmp_path / "phase2" / "stage1" / "formal"
    formal.mkdir(parents=True)
    harness = formal / "formal_dut.sv"
    harness.write_text(
        "module formal_dut(input clk); always @(posedge clk) assert (1'b1); endmodule\n")
    requested = {"id": "L6.fsm_state.IDLE", "layer": "L6",
                 "description": "declared IDLE transition", "status": "UNAUTHORED"}
    (formal / "property_contract.json").write_text(json.dumps({
        "property_denominator": 1,
        "authored_property_count": 1,
        "unresolved_obligations": [],
    }))
    (formal / "formal_authoring_request.json").write_text(json.dumps({
        "property_denominator": 1,
        "unresolved_obligations": [requested],
    }))
    (formal / "formal_expert_review.json").write_text(json.dumps({
        "invocation_status": "INVOKED", "fallback_skill": "formal-verify",
        "dispositions": [{"id": "L6.fsm_state.IDLE", "status": "AUTHORED",
                           "property": "p_idle_transition"}],
    }))
    result = {
        "verdict": "PASS", "all_proved": True,
        "sby": "phase2/stage1/formal/dut.sby",
        "evidence": "phase2/stage1/formal/dut.sby.log",
        "bounded_vs_unbounded": ["property PROVED UNBOUNDED"],
    }
    FPR._attach_property_contract(result, formal, harness)
    assert result["verdict"] == "PASS"
    assert result["expert_fallback_invoked"] is True
    assert result["expert_fallback_receipt"].endswith(
        "formal/formal_expert_review.json")
    assert result["unresolved_obligations"] == []


def test_build_results_no_tasks_is_skipped_condition():
    lp = FPR.LogParse()
    r = FPR.build_results("m", {}, lp, "e/log", "e/sby")
    assert r["all_proved"] is False
    assert r["verdict"] == "SKIPPED-CONDITION"


# ── emitters ───────────────────────────────────────────────────────────────
def test_emit_sby_shape():
    s = FPR.emit_sby(["a.v", "b.v"], "formal_top.sv", "formal_top",
                     safety_depth=15, bmc_depth=8)
    assert "[tasks]" in s and "safety   prove" in s and "bmc      bmc" in s
    assert "safety: depth 15" in s and "bmc:    depth 8" in s
    assert "aigsmt none" in s                 # standalone ABC (no ext SMT)
    assert "prep -top formal_top" in s
    # every source appears under [files] so the evidence gate can resolve it
    files_sec = s.split("[files]", 1)[1]
    for f in ("a.v", "b.v", "formal_top.sv"):
        assert f in files_sec


def test_emit_reset_safety_harness_general():
    h = FPR.emit_reset_safety_harness("mymod", clk="clk", rst="rst_n",
                                      out_port="q", out_known="1'b0",
                                      extra_ports=["din"])
    assert "module formal_mymod" in h
    assert "assert (q == 1'b0)" in h
    assert "(* anyseq *) wire rst_n;" in h
    assert ".din(din)" in h              # extra free input wired by name


def test_emit_reset_safety_harness_no_chip_literal():
    # general authoring aid must not bake any spm-specific token
    h = FPR.emit_reset_safety_harness("anyblk")
    assert "spm" not in h.lower()


# ── honesty guard: a BMC result is NEVER dressed as an unbounded proof ──────
def test_bound_kind_bmc_high_depth_is_still_bounded():
    # even a huge BMC depth is bounded, not unbounded
    assert FPR.bound_kind("bmc", "PASS") == "bounded"


def test_assert_bound_honesty_rejects_bmc_as_unbounded():
    import pytest
    bad = [{"task": "t", "mode": "bmc", "depth": 9999, "status": "PASS",
            "bound": "unbounded"}]
    with pytest.raises(AssertionError):
        FPR.assert_bound_honesty(bad)


def test_assert_bound_honesty_rejects_proved_not_unbounded():
    import pytest
    bad = [{"task": "t", "mode": "prove", "depth": None, "status": "PASS",
            "bound": "bounded"}]
    with pytest.raises(AssertionError):
        FPR.assert_bound_honesty(bad)


def test_assert_bound_honesty_accepts_honest_mix():
    ok = [{"task": "p", "mode": "prove", "status": "PASS", "bound": "unbounded"},
          {"task": "b", "mode": "bmc", "depth": 40, "status": "PASS",
           "bound": "bounded"}]
    assert FPR.assert_bound_honesty(ok) is True


def test_proof_strength_classifier():
    assert FPR.proof_strength(
        [{"bound": "unbounded"}, {"bound": "bounded"}]) == "unbounded"
    # a deep BMC alone is only 'bounded', never 'unbounded'
    assert FPR.proof_strength([{"bound": "bounded"}]) == "bounded"
    # a counterexample dominates
    assert FPR.proof_strength(
        [{"bound": "unbounded"}, {"bound": "cex"}]) == "cex"
    assert FPR.proof_strength([]) == "none"


def test_build_results_bmc_only_is_bounded_not_unbounded():
    # a run whose ONLY passing task is a deep BMC must report proof_strength
    # 'bounded' and unbounded_proved False — never a fake full proof.
    cfg = FPR.parse_sby_config("[tasks]\nbmc bmc\n[options]\nbmc: mode bmc\n"
                               "bmc: depth 200\n[engines]\nbmc: abc bmc3\n")
    log = ("SBY [b_bmc] engine_0: abc bmc3\n"
           "SBY [b_bmc] engine_0: No output asserted in 200 frames.\n"
           "SBY [b_bmc] engine_0: Status returned by engine: PASS\n"
           "SBY [b_bmc] DONE (PASS, rc=0)\n")
    lp = FPR.parse_sby_log(log, sby_stem="b", seed=cfg)
    r = FPR.build_results("b", cfg, lp, "e/log", "e/sby")
    assert r["all_proved"] is True            # the bmc DID pass...
    assert r["unbounded_proved"] is False     # ...but it is NOT unbounded
    assert r["proof_strength"] == "bounded"


def test_build_results_timeout_prove_is_partial_not_fail():
    # a prove that TIMED OUT (inconclusive) alongside a bmc that PASSED is a
    # PARTIAL result — NOT a counterexample FAIL and NOT a fabricated PASS.
    cfg = FPR.parse_sby_config(
        "[tasks]\nprv prove\nb bmc\n[options]\nprv: mode prove\n"
        "prv: depth 40\nb: mode bmc\nb: depth 12\n"
        "[engines]\nprv: abc pdr\nb: abc bmc3\n")
    log = ("SBY [x_prv] engine_0: abc pdr\n"
           "SBY [x_prv] DONE (TIMEOUT, rc=3)\n"
           "SBY [x_b] engine_0: abc bmc3\n"
           "SBY [x_b] engine_0: No output asserted in 12 frames.\n"
           "SBY [x_b] DONE (PASS, rc=0)\n")
    lp = FPR.parse_sby_log(log, sby_stem="x", seed=cfg)
    r = FPR.build_results("x", cfg, lp, "e/log", "e/sby")
    assert r["verdict"] == "PARTIAL"
    assert r["all_proved"] is False
    assert r["unbounded_proved"] is False       # the prove did NOT complete
    assert r["proof_strength"] == "bounded"      # only the bmc held
    # the timed-out prove is inconclusive, never dressed as unbounded
    prv = [p for p in r["properties"] if p["task"] == "prv"][0]
    assert prv["bound"] == "inconclusive"


def test_build_results_prove_pass_is_unbounded():
    cfg = FPR.parse_sby_config("[tasks]\nprv prove\n[options]\nprv: mode prove\n"
                               "prv: depth 40\n[engines]\nprv: abc pdr\n")
    log = ("SBY [p_prv] engine_0: abc pdr\n"
           "SBY [p_prv] engine_0: Property proved.\n"
           "SBY [p_prv] engine_0: Status returned by engine: PASS\n"
           "SBY [p_prv] DONE (PASS, rc=0)\n")
    lp = FPR.parse_sby_log(log, sby_stem="p", seed=cfg)
    r = FPR.build_results("p", cfg, lp, "e/log", "e/sby")
    assert r["unbounded_proved"] is True
    assert r["proof_strength"] == "unbounded"


# ── invariant-strengthened harness: pragma parse + sby emit ─────────────────
_INV_HARNESS = """// header
// @invariant-harness
// @connect peek_s = dut.s
// @connect peek_c = dut.c
// @chparam size = 32
// @task refeq       prove timeout=90 -- -DSPM_REFEQ -DSPM_NO_INV
// @task product     prove timeout=90 -- -DSPM_NO_FINAL
// @task product_bmc bmc   depth=48
module formal_top(input clk); endmodule
"""


def test_parse_harness_pragmas_full():
    p = FPR.parse_harness_pragmas(_INV_HARNESS)
    assert p["is_invariant"] is True
    assert ("peek_s", "dut.s") in p["connects"]
    assert ("peek_c", "dut.c") in p["connects"]
    assert ("size", "32") in p["chparams"]
    names = {t["name"]: t for t in p["tasks"]}
    assert set(names) == {"refeq", "product", "product_bmc"}
    assert names["refeq"]["mode"] == "prove"
    assert names["refeq"]["timeout"] == 90
    assert names["refeq"]["defines"] == "-DSPM_REFEQ -DSPM_NO_INV"
    assert names["product"]["defines"] == "-DSPM_NO_FINAL"
    assert names["product_bmc"]["mode"] == "bmc"
    assert names["product_bmc"]["depth"] == 48


def test_parse_harness_pragmas_plain_is_not_invariant():
    # a port-only harness with no @connect / @invariant-harness marker
    p = FPR.parse_harness_pragmas("module formal_x(input clk); endmodule\n")
    assert p["is_invariant"] is False
    assert p["connects"] == [] and p["tasks"] == []


def test_emit_invariant_sby_flatten_connect_and_task_defines():
    p = FPR.parse_harness_pragmas(_INV_HARNESS)
    s = FPR.emit_invariant_sby(["spm.v"], "formal_spm_inductive.sv",
                               "formal_spm", p["connects"], p["chparams"],
                               tasks=p["tasks"])
    # netlist-level wiring of internal state (no hierarchical ref needed)
    assert "flatten" in s
    assert "connect -set peek_s dut.s" in s
    assert "connect -set peek_c dut.c" in s
    assert "chparam -set size 32 formal_spm" in s
    # per-task read_verilog carries that task's own defines
    assert "refeq: read_verilog -formal -sv -DSPM_REFEQ -DSPM_NO_INV" in s
    assert "product: read_verilog -formal -sv -DSPM_NO_FINAL" in s
    # a prove task with a timeout is bounded so it cannot hang
    assert "refeq: timeout 90" in s
    # the bmc task is a bounded corroboration at its depth
    assert "product_bmc: mode bmc" in s and "product_bmc: depth 48" in s
    # all three tasks are declared
    for t in ("refeq", "product", "product_bmc"):
        assert t in s.split("[options]", 1)[0]


def test_emit_invariant_sby_prove_engine_is_sby_drivable():
    # REGRESSION: sby's `btor` backend is bmc/cover-ONLY. A prove task must use
    # an sby-prove-drivable engine (abc pdr) — never `btor btormc`, which would
    # make sby ERROR ("btormc only supported in bmc and cover modes").
    p = FPR.parse_harness_pragmas(_INV_HARNESS)
    s = FPR.emit_invariant_sby(["spm.v"], "h.sv", "formal_spm",
                               p["connects"], p["chparams"], tasks=p["tasks"],
                               prove_engine="abc pdr")
    eng = s.split("[engines]", 1)[1].split("[script]", 1)[0]
    for line in eng.splitlines():
        if ": abc pdr" in line or ": abc bmc3" in line:
            continue
        assert "btor" not in line, f"btor used as sby engine: {line!r}"
    assert "refeq: abc pdr" in eng and "product: abc pdr" in eng


def test_emit_invariant_sby_default_tasks():
    # no @task pragmas -> a default prove + bmc pair
    s = FPR.emit_invariant_sby(["a.v"], "h.sv", "top", [("q", "u.q")], [])
    assert "connect -set q u.q" in s
    assert "prove: mode prove" in s and "bmc: mode bmc" in s


def test_pragma_program_has_no_design_net_literal():
    # the MECHANISM must be design-independent: the program source carries no
    # per-design internal-net / placeholder literal — those live in the harness
    # (design INPUT). (The `-DSPM_*` define DEFAULTS in emit_sby are macro names
    # passed to a caller-supplied harness, not detection logic.)
    src = (Path(FPR.__file__)).read_text()
    for lit in ("dut.s", "dut.c", "peek_s", "peek_c"):
        assert lit not in src, f"design-net literal {lit!r} leaked into program"
