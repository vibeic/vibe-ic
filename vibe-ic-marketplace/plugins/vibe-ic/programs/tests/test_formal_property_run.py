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
