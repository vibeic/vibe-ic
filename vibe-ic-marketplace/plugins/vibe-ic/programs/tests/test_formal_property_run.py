"""Unit tests for formal_property_run.py pure helpers (Step 5 runner).

Covers the sby-log parse (proved / failed / depth / cex / engine), the .sby
config parse (per-task mode/depth/engine), the bounded-vs-unbounded strength
classifier, the results.json builder (all_proved / verdict logic), and the
harness/.sby emitters. The registered-alias controls also execute native
Yosys/SymbiYosys when available, with explicit resource bounds.

These are the parse/emit fixtures pinned to the REAL spm run transcript so a
regression in the parser is caught deterministically.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_named_default_container_uses_local_formal_tools(tmp_path, monkeypatch):
    """The normal runner supplies a container name even inside the EDA image.

    Probe and proof must both use the ambient toolchain, while preserving a
    measured failure. Transcripts are fixture data; no tool is invoked here.
    """
    formal_dir = FPR._pl.formal_dir(tmp_path)
    formal_dir.mkdir(parents=True)
    sby = formal_dir / "formal_spm_formal.sby"
    sby.write_text(_SPM_SBY)
    (formal_dir / "spm.v").write_text("module spm; endmodule\n")
    (formal_dir / "formal_spm.sv").write_text(
        "module formal_spm; always @* assert (1); endmodule\n")
    monkeypatch.setattr(FPR._ce, "local_exec_mode", lambda _tag: True)
    seen = []

    def probe(container):
        seen.append(("probe", container))
        assert container is None, "local tools were probed through Docker"
        return {"abc": True, "_env_reachable": True}

    monkeypatch.setattr(FPR, "detect_engines", probe)
    for transcript, expected in [
        (_REAL_SPM_LOG, "PASS"),
        (_FAIL_LOG.replace("t_bmc", "formal_spm_formal_bmc"), "FAIL"),
    ]:
        def proof(_sby, _dir, container, _timeout, **_kwargs):
            seen.append(("proof", container))
            assert container is None, "local proof was launched through Docker"
            return transcript

        monkeypatch.setattr(FPR, "_run_sby", proof)
        result = FPR.run(tmp_path, sby=sby, container="vibeic-eda")
        assert result["verdict"] == expected
        assert result["all_proved"] is (expected == "PASS")
    assert seen == [("probe", None), ("proof", None)] * 2


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
    import hashlib
    import json
    formal = tmp_path / "phase2" / "stage1" / "formal"
    formal.mkdir(parents=True)
    harness = formal / "formal_dut.sv"
    harness.write_text(
        "module formal_dut(input clk); always @(posedge clk) p_idle_transition: assert (1'b1); endmodule\n")
    requested = {"id": "L6.fsm_state.IDLE", "layer": "L6",
                 "description": "declared IDLE transition", "status": "UNAUTHORED"}
    (formal / "property_contract.json").write_text(json.dumps({
        "property_denominator": 1,
        "authored_property_count": 1,
        "unresolved_obligations": [],
    }))
    (formal / "formal_authoring_request.json").write_text(json.dumps({
        "property_denominator": 1,
        "fallback_skill": "formal-verify",
        "unresolved_obligations": [requested],
    }))
    (formal / "formal_expert_review.json").write_text(json.dumps({
        "invocation_status": "INVOKED", "fallback_skill": "formal-verify",
        "request_sha256": hashlib.sha256((formal / "formal_authoring_request.json").read_bytes()).hexdigest(),
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


def test_emit_sby_uses_wrapping_harness_as_yosys_top():
    # The output/report remains named for the DUT, but Yosys must elaborate
    # the wrapper that contains it (and owns observer paths).
    s = FPR.emit_sby(["leaf.sv"], "formal_leaf.sv", "leaf",
                     observers=[("observed_state", "dut.state_q")],
                     harness_top="formal_leaf")
    assert "hierarchy -top formal_leaf" in s
    assert "select -assert-any formal_leaf/w:dut.state_q" in s
    assert "prep -top formal_leaf" in s
    assert "prep -top leaf\n" not in s


def test_emit_sby_without_wrapper_override_keeps_dut_as_top():
    s = FPR.emit_sby(["a.v"], "formal_top.sv", "formal_top")
    assert "prep -top formal_top" in s


def test_direct_hierarchical_immediate_assert_uses_slang_frontend(tmp_path):
    # The shipped read_slang frontend resolves a direct hierarchy path while
    # read_verilog makes it an undriven wire. Drive the real emit-only path;
    # an assertion referring to the DUT register must select read_slang before
    # any proof can be credited. No engine is needed for this routing test.
    project = tmp_path / "design"
    rtl_dir = project / "phase2/stage1/rtl"
    rtl_dir.mkdir(parents=True)
    leaf = rtl_dir / "leaf.sv"
    leaf.write_text(
        "module leaf(input logic clk); logic state_q; "
        "always_ff @(posedge clk) state_q <= ~state_q; endmodule\n")
    harness = tmp_path / "formal_leaf.sv"
    harness.write_text(
        "module formal_leaf(input logic clk); leaf dut(.clk(clk));\n"
        "wire observed_state = dut.state_q;\n"
        "always @(posedge clk) p_toggles: assert (observed_state == "
        "~$past(observed_state)); endmodule\n")
    result = FPR.run(project, harness=harness, rtl=[leaf], top="leaf",
                     emit_only=True)
    assert result["verdict"] == "EMIT_ONLY"
    sby = (project / result["sby"]).read_text()
    assert "read_slang --single-unit" in sby
    assert "read_verilog" not in sby


def test_read_verilog_assignment_pattern_parse_abort_tries_slang():
    transcript = (
        "base: pkg.sv:19: ERROR: syntax error, unexpected ':'\n"
        "summary: engine_0 (abc pdr) did not return a status\n")
    assert FPR.frontend_aborted_the_read(transcript)
    assert not FPR.frontend_aborted_the_read(
        transcript.replace("did not return a status", "returned PASS"))


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
    assert "connect -nomap -set peek_s dut.s" in s
    assert "connect -nomap -set peek_c dut.c" in s
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
    assert "connect -nomap -set q u.q" in s
    assert "prove: mode prove" in s and "bmc: mode bmc" in s


def test_pragma_program_has_no_design_net_literal():
    # the MECHANISM must be design-independent: the program source carries no
    # per-design internal-net / placeholder literal — those live in the harness
    # (design INPUT). (The `-DSPM_*` define DEFAULTS in emit_sby are macro names
    # passed to a caller-supplied harness, not detection logic.)
    src = (Path(FPR.__file__)).read_text()
    for lit in ("dut.s", "dut.c", "peek_s", "peek_c"):
        assert lit not in src, f"design-net literal {lit!r} leaked into program"


# ── include-header staging (vibe-ic, opentitan_aes 2026-09-02) ─────────────
# MEASURED defect: sby copies only the `[files]` entries into its own `src/`
# working directory, so a source carrying `` `include "x.svh" `` reached yosys
# with the header absent and every task ERRORed before an engine started:
#     base: ERROR: Can't open include file `prim_assert_yosys_macros.svh'!
#     DONE (ERROR, rc=16)   ... summary: engine_0 did not return a status
# The step then reported a FORMAL capability gap the environment did not have.
# The header was staged in the run's OWN phase2/stage1/rtl/ the whole time.

def _write(p, text):
    p.write_text(text)
    return p


def test_resolve_include_headers_finds_the_included_header(tmp_path):
    """The POSITIVE control: an include directive resolves to the file."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    _write(rtl / "hdr.svh", "`define X 1\n")
    src = _write(rtl / "m.sv", '`include "hdr.svh"\nmodule m; endmodule\n')
    found = FPR.resolve_include_headers([src])
    assert [f.name for f in found] == ["hdr.svh"]


def test_resolve_include_headers_is_transitive(tmp_path):
    """A header that includes another header stages both."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    _write(rtl / "inner.svh", "`define Y 2\n")
    _write(rtl / "outer.svh", '`include "inner.svh"\n')
    src = _write(rtl / "m.sv", '`include "outer.svh"\nmodule m; endmodule\n')
    assert sorted(f.name for f in FPR.resolve_include_headers([src])) == [
        "inner.svh", "outer.svh"]


def test_resolve_include_headers_negative_control(tmp_path):
    """A source with NO include stages nothing — the header is not glob-swept.

    This is the direction that fails against a blind `*.svh` glob: a header
    nothing includes is not evidence, and staging it would be a claim the
    sources never made.
    """
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    _write(rtl / "unused.svh", "`define Z 3\n")
    src = _write(rtl / "m.sv", "module m; endmodule\n")
    assert FPR.resolve_include_headers([src]) == []


def test_resolve_include_headers_unresolvable_is_absent_not_fabricated(tmp_path):
    """An include naming a file that is not on disk yields no entry."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    src = _write(rtl / "m.sv", '`include "nowhere.svh"\nmodule m; endmodule\n')
    assert FPR.resolve_include_headers([src]) == []


def test_emit_sby_stages_headers_in_files_but_never_reads_them():
    """`[files]` carries the header; `read_verilog` must not.

    Handing a macro body to `read_verilog` elaborates it as a compilation
    unit; the header only has to EXIST in sby's src/ for the directive in the
    source that includes it to resolve.
    """
    text = FPR.emit_sby(["m.sv"], "formal_m.sv", "m",
                        include_files=["hdr.svh"])
    files_block = text.split("[files]", 1)[1]
    assert "hdr.svh" in files_block
    script_block = text.split("[script]", 1)[1].split("[files]", 1)[0]
    assert "hdr.svh" not in script_block


def test_emit_sby_without_headers_is_unchanged():
    """NEGATIVE control: the no-header call emits exactly what it always did.

    A fix that changed the .sby for every design would be a regression wearing
    a fix's clothes.
    """
    assert (FPR.emit_sby(["m.sv"], "formal_m.sv", "m")
            == FPR.emit_sby(["m.sv"], "formal_m.sv", "m", include_files=[]))


def test_emit_invariant_sby_stages_headers_in_files_only():
    text = FPR.emit_invariant_sby(["m.sv"], "formal_m.sv", "m", [], [],
                                  include_files=["hdr.svh"])
    files_block = text.split("[files]", 1)[1]
    assert "hdr.svh" in files_block
    script_block = text.split("[script]", 1)[1].split("[files]", 1)[0]
    assert "hdr.svh" not in script_block


def test_stage_include_headers_skips_names_already_staged(tmp_path):
    """A directive naming a SOURCE the file list already carries is skipped.

    MEASURED on opentitan_aes: `prim_assert.sv` is both a compiled source and
    an `` `include `` target. Listing it twice in `[files]` is a second claim
    about one file.
    """
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    _write(rtl / "prim_assert.sv", "// macros\n")
    _write(rtl / "hdr.svh", "`define X 1\n")
    src = _write(rtl / "m.sv",
                 '`include "prim_assert.sv"\n`include "hdr.svh"\n'
                 "module m; endmodule\n")
    formal = tmp_path / "formal"
    formal.mkdir()
    names = FPR._stage_include_headers(
        [src, rtl / "prim_assert.sv"], formal,
        already=["m.sv", "prim_assert.sv"])
    assert names == ["hdr.svh"]
    assert (formal / "hdr.svh").is_file()


def test_emit_sby_reads_systemverilog():
    """`read_verilog -formal` without `-sv` uses the Verilog-2005 frontend.

    MEASURED on opentitan_aes once the include headers were staged and the
    frontend finally reached the sources:
        aes.sv:10: ERROR: syntax error, unexpected TOK_ID,
                   expecting '#' or '(' or ';'
    from `module aes import aes_pkg::*; #( ... )`. Both tasks ERRORed at
    rc=16 before an engine started. `emit_invariant_sby` beside it already
    passed `-sv`; the two emitters disagreed and this one was wrong.
    """
    text = FPR.emit_sby(["m.sv"], "formal_m.sv", "m")
    script = text.split("[script]", 1)[1].split("[files]", 1)[0]
    reads = [ln for ln in script.splitlines() if "read_verilog" in ln]
    assert reads, script
    for ln in reads:
        assert " -sv " in ln, ln


def test_both_sby_emitters_agree_on_the_frontend():
    """The control that keeps them from drifting apart again."""
    a = FPR.emit_sby(["m.sv"], "formal_m.sv", "m")
    b = FPR.emit_invariant_sby(["m.sv"], "formal_m.sv", "m", [], [])
    for text in (a, b):
        script = text.split("[script]", 1)[1].split("[files]", 1)[0]
        for ln in script.splitlines():
            if "read_verilog" in ln:
                assert " -sv " in ln, ln


def test_frontend_retry_detects_assignment_pattern_parse_error_before_engine():
    log = ("SBY 00:00:01 [formal_aes_safety] base: "
           "aes_pkg.sv:579: ERROR: syntax error, unexpected ':'\n"
           "SBY 00:00:01 [formal_aes_safety] task failed. ERROR.\n"
           "SBY 00:00:01 [formal_aes_safety] DONE (ERROR, rc=16)\n")
    assert FPR.frontend_aborted_the_read(log)


def test_frontend_retry_does_not_mask_solver_inconclusive():
    log = ("SBY 00:00:01 [formal_aes_safety] engine_0: abc pdr\n"
           "SBY 00:00:02 [formal_aes_safety] DONE (UNKNOWN, rc=4)\n")
    assert not FPR.frontend_aborted_the_read(log)


# #3062: self-authored registered-state aliases, actual producer -> consumer.
# Keep the clock/reset/state assertions identical between binding variants.
def _registered_alias_fixture(project, shape="packed", mutation=None):
    rd = project / "phase2/stage1/rtl"
    rd.mkdir(parents=True)
    rtl = """module alias_cell(input clk, input rst, input [1:0] d);
  reg [1:0] left, right;
  wire flag = (left == right);
  always @(posedge clk) begin
    if (rst) begin left <= 0; right <= 0; end
    else begin left <= d; right <= left ^ 2'b11; end
  end
endmodule
"""
    edits = {
        "negedge": ("@(posedge clk)", "@(negedge clk)"),
        "async": ("@(posedge clk)", "@(posedge clk or posedge rst)"),
        "reset_inverted": ("if (rst)", "if (!rst)"),
        "wrong_state": ("right <= left ^ 2'b11", "right <= left ^ 2'b01"),
    }
    if mutation in edits:
        rtl = rtl.replace(*edits[mutation])
    source = rd / "alias_cell.v"
    source.write_text(rtl)
    expression = "packed_state" if shape == "packed" else "{view_left, view_right}"
    extra = ""
    if shape == "duplicate":
        extra = """// @observe duplicate_left = dut.left
(* keep *) wire [1:0] duplicate_left;
always @($global_clock) assert (duplicate_left == view_left);
"""
    elif shape == "equality":
        extra = """// @observe view_flag = dut.flag
(* keep *) wire view_flag;
wire literal_one = 1'b1;
wire equality_alias = (view_flag == literal_one);
always @($global_clock) assert (equality_alias == (view_left == view_right));
"""
    h = project / "formal_alias.sv"
    text = """module formal_alias(input clk);
(* anyseq *) reg rst;
(* anyseq *) reg [1:0] d;
alias_cell dut(clk, rst, d);
// @observe view_left = dut.left
// @observe view_right = dut.right
(* keep *) wire [1:0] view_left, view_right;
wire [3:0] packed_state = {view_left, view_right};
reg past_valid = 0;
always @($global_clock) begin
  past_valid <= 1;
  if (past_valid && !(!$past(clk) && clk)) assert (EXPRESSION == $past(EXPRESSION));
end
reg reference_valid = 0;
reg [1:0] reference_left, reference_right;
always @(posedge clk) begin
  if (rst) begin reference_left <= 0; reference_right <= 0; reference_valid <= 1; end
  else begin reference_left <= d; reference_right <= reference_left ^ 2'b11; end
  if (reference_valid) begin
    assert(view_left == reference_left);
    assert(view_right == reference_right);
  end
end
EXTRA
endmodule
""".replace("EXPRESSION", expression).replace("EXTRA", extra)
    if mutation == "missing_target":
        text = text.replace("= dut.left", "= dut.absent")
    h.write_text(text)
    return source, h


def _alias_native(project, shape="packed", mutation=None, reused=False):
    from not_verified_tier import skip_not_verified
    import formal_proof_evidence_check as consumer
    missing = [name for name in ("yosys", "sby") if shutil.which(name) is None]
    if missing:
        skip_not_verified(f"native registered-alias control needs {missing}",
                          "Run test_formal_property_run.py in the pinned EDA image")
    source, h = _registered_alias_fixture(project, shape, mutation)
    kwargs = dict(container=None, timeout=60, mem_limit_kb=4 * 1024 * 1024,
                  safety_depth=12, bmc_depth=12, prove_engines="direct")
    formal = project / "phase2/stage1/formal"
    if reused:
        emitted = FPR.run(project, harness=h, rtl=[source], top="alias_cell",
                          emit_only=True, **kwargs)
        sby = project / emitted["sby"]
        # Exercise migration of an already bound legacy task, not just a task
        # whose expert fragment added previously absent observers.
        sby.write_text(sby.read_text().replace("connect -nomap -set", "connect -set"))
        result = FPR.run(project, top="alias_cell", sby=sby, **kwargs)
    else:
        result = FPR.run(project, harness=h, rtl=[source], top="alias_cell", **kwargs)
        sby = project / result["sby"]
    checked = consumer.audit(project)
    (project / "native-receipt.json").write_text(json.dumps(
        {"producer": result, "consumer": checked}, indent=2))
    return result, checked, sby, formal


def _alias_postbind(sby, formal):
    # Use the producer's actual safety script and inspect immediately after
    # bindings, before prep/opt can remove a free assertion operand.
    script = sby.read_text().split("[script]", 1)[1].split("[files]", 1)[0]
    lines = []
    model_path = formal / "postbind.json"
    for line in script.splitlines():
        if line.startswith(("bmc:", "~safety:")):
            continue
        if line.startswith("safety:"):
            line = line[len("safety:"):].strip()
        if line.startswith("prep -top"):
            lines += [f"write_json {model_path}", "check -assert"]
            break
        if line.strip():
            lines.append(line)
    ys = formal / "postbind.ys"
    ys.write_text("\n".join(lines) + "\n")
    native = subprocess.run(["yosys", "-Q", "-T", "-s", str(ys)], cwd=formal,
                            text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=30)
    (formal / "postbind.log").write_text(native.stdout)
    assert native.returncode == 0, native.stdout
    model = json.loads(model_path.read_text())["modules"]["formal_alias"]
    nets = model["netnames"]
    drivers = {bit for cell in model["cells"].values()
               for port, bits in cell["connections"].items()
               if cell["port_directions"][port] == "output" for bit in bits}
    for name in ("dut.left", "dut.right", "view_left", "view_right", "packed_state"):
        assert set(nets[name]["bits"]) <= drivers, name
    assert nets["packed_state"]["bits"] == (
        nets["view_right"]["bits"] + nets["view_left"]["bits"])
    for alias, target in (("duplicate_left", "view_left"), ("equality_alias", "view_flag")):
        if alias in nets:
            assert nets[alias]["bits"] == nets[target]["bits"]
            assert set(nets[alias]["bits"]) <= drivers
    assert "used but has no driver" not in native.stdout


@pytest.mark.parametrize("shape", ["packed", "direct", "duplicate", "equality"])
def test_registered_alias_native_preserves_drivers_and_proves(tmp_path, shape):
    result, checked, sby, formal = _alias_native(tmp_path, shape)
    assert result["verdict"] == checked["verdict"] == "PASS", result
    assert result["rc"] == checked["rc"] == 0
    assert result["all_proved"] is True
    assert result["authored_property_count"] == (4 if shape in ("duplicate", "equality") else 3)
    assert result["property_denominator"] == result["authored_property_count"]
    assert {(p["mode"], p["status"]) for p in result["properties"]} == {
        ("prove", "PASS"), ("bmc", "PASS")}
    _alias_postbind(sby, formal)


def test_registered_alias_native_reused_legacy_binding_is_upgraded(tmp_path):
    result, checked, sby, formal = _alias_native(tmp_path, reused=True)
    assert result["verdict"] == checked["verdict"] == "PASS", result
    text = sby.read_text()
    assert "connect -set" not in text
    assert text.count("connect -nomap -set") == 2
    assert FPR._ensure_expert_observers_bound(sby, formal) is False
    _alias_postbind(sby, formal)


@pytest.mark.parametrize("mutation", ["negedge", "async", "reset_inverted", "wrong_state"])
def test_registered_alias_native_rejects_clock_reset_state_mutants(tmp_path, mutation):
    result, checked, sby, formal = _alias_native(tmp_path, mutation=mutation)
    assert result["verdict"] == checked["verdict"] == "FAIL", result
    assert result["all_proved"] is False
    assert result["authored_property_count"] == result["property_denominator"] == 3
    assert {p["status"] for p in result["properties"]} == {"FAIL"}
    assert all(p["cex_frame"] is not None for p in result["properties"])
    _alias_postbind(sby, formal)


def test_registered_alias_native_missing_target_is_error_not_proof(tmp_path):
    result, checked, _, _ = _alias_native(tmp_path, mutation="missing_target")
    assert result["all_proved"] is False
    assert checked["verdict"] == "FAIL"
    assert {p["status"] for p in result["properties"]} == {"ERROR"}
    assert result["authored_property_count"] == result["property_denominator"] == 3


@pytest.mark.parametrize("command", ["connect -set", "connect -nomap -set"])
def test_registered_alias_binding_parser_checks_exact_target_and_multiplicity(command):
    harness = "// @observe tap = dut.q\n"
    good = f"{command} tap dut.q\n"
    assert FPR.observer_binding_mismatches(harness, good) == []
    assert FPR.observer_binding_mismatches(harness, f"{command} tap dut.wrong\n")
    assert FPR.observer_binding_mismatches(harness, good + good)
    assert FPR.observer_binding_mismatches(harness, good + f"{command} other dut.q\n")
    assert FPR.observer_binding_mismatches(harness, good.replace(command, "connect -unknown -set"))


def test_registered_alias_native_invariant_connect_preserves_packed_drivers(tmp_path):
    from not_verified_tier import skip_not_verified
    if any(shutil.which(name) is None for name in ("yosys", "sby")):
        skip_not_verified("native invariant alias control needs yosys/sby",
                          "Run test_formal_property_run.py in the pinned EDA image")
    source, h = _registered_alias_fixture(tmp_path)
    text = h.read_text().replace("@observe", "@connect")
    # This independent, single-clock invariant compares the SAME registered
    # states with the same reference equations via the packed alias.
    start, end = text.index("reg past_valid"), text.index("reg reference_valid")
    text = text[:start] + text[end:]
    text = text.replace("assert(view_left == reference_left);\n    assert(view_right == reference_right);",
                        "assert(packed_state == {reference_left, reference_right});")
    text = text.replace("endmodule", """reg reset_past_valid = 0;
always @(posedge clk) begin
  reset_past_valid <= 1;
  if (reset_past_valid && $past(rst)) assert(packed_state == 4'b0);
end
endmodule""")
    h.write_text(text)
    result = FPR.run(tmp_path, invariant_harness=h, rtl=[source], top="formal_alias",
                     container=None, timeout=60, mem_limit_kb=4 * 1024 * 1024,
                     safety_depth=12, bmc_depth=12)
    (tmp_path / "native-receipt.json").write_text(json.dumps({"producer": result}, indent=2))
    assert result["all_proved"] is True, result
    assert result["verdict"] == "PASS"
    assert result["authored_property_count"] == result["property_denominator"] == 2
    assert {(p["mode"], p["status"]) for p in result["properties"]} == {
        ("prove", "PASS"), ("bmc", "PASS")}
    formal = tmp_path / "phase2/stage1/formal"
    assert not (formal / "results.json").exists()  # preserve supplementary scope
    sby = tmp_path / result["sby"]
    assert sby.read_text().count("connect -nomap -set") == 2
    for task in ("prove", "bmc"):
        log = formal / f"formal_alias_inductive_{task}/model/design.log"
        assert "used but has no driver" not in log.read_text()
