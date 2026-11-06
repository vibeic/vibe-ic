#!/usr/bin/env python3
"""T91 (review70 step 5) — a SECOND unbounded prove engine, and its honest fold.

The review row claimed, from `formal_property_run.py`'s own comment, that `abc
pdr` is the ONLY unbounded engine sby drives in `mode prove`. MEASURED false in
the released vibeic-eda 0.3.77 image: `mode prove` + `[engines] smtbmc yices`
completes a k-induction proof (`calibration/sby_prove_arms_pass.sby.log`). So
Step 5 can run both engines on the same claim and keep the better answer.

What this pins, on REAL transcripts of the .sby `emit_sby` writes:

  * a k-induction BASECASE pass is not a proof. The engine reports `returned
    pass for basecase` before the induction step; only `DONE (...)` is the task
    verdict. A transcript cut before `DONE` must not read as PASS.
  * the two prove arms are ONE claim: an induction step that did not close
    (UNKNOWN) does not turn a claim `abc pdr` PROVED into PARTIAL, a
    counterexample from either arm is FAIL, and one arm PASS + the other FAIL
    is recorded as disagreement and is never PASS.
  * the project's step-5 switch (`phase3/librelane_switch.json`,
    `{"steps":{"5":"dual"}}`) puts the second arm into the .sby the flow runs,
    and the real proof records both arms (in-image).

chip-AGNOSTIC: the design is a calibration counter, not a benchmark design.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import formal_property_run as fpr  # noqa: E402
from _tool_probes import skip_not_verified  # noqa: E402

CAL = PROGRAMS / "calibration"
STEM = "formal_ctr"


def _cfg():
    return fpr.parse_sby_config((CAL / "sby_prove_arms.sby").read_text())


def _log(name: str) -> str:
    return (CAL / f"sby_prove_arms_{name}.sby.log").read_text()


def _results(text: str) -> dict:
    cfg = _cfg()
    return fpr.build_results(STEM, cfg, fpr.parse_sby_log(text, STEM, cfg),
                             "e.log", "s.sby")


def test_the_calibration_sby_is_the_emitters_own_text():
    """The fixture transcripts were produced from what `emit_sby` writes."""
    fx = PROGRAMS / "tests/fixtures/sby_prove_arms/pass"
    assert (fx / "ctr.v").is_file() and (fx / "formal_ctr.sv").is_file()
    text = fpr.emit_sby(["ctr.v"], "formal_ctr.sv", STEM,
                        kind_engine=fpr.KIND_PROVE_ENGINE)
    assert text == (CAL / "sby_prove_arms.sby").read_text()
    assert fpr.KIND_PROVE_ENGINE == "smtbmc yices"


def test_without_a_second_engine_the_sby_is_byte_identical():
    base = fpr.emit_sby(["ctr.v"], "formal_ctr.sv", STEM)
    assert base == fpr.emit_sby(["ctr.v"], "formal_ctr.sv", STEM, kind_engine=None)
    assert "smtbmc" not in base and "~safety:" in base


def test_a_basecase_pass_with_no_done_line_is_not_a_proof():
    """RED on main: the summary fallback read `returned pass for basecase`."""
    real = _log("unknown")
    cut = "\n".join(l for l in real.splitlines()
                    if not ("[formal_ctr_safety_kind]" in l and "DONE" in l))
    assert "returned pass for basecase" in cut and "DONE (UNKNOWN" in real
    lp = fpr.parse_sby_log(cut, STEM, _cfg())
    assert lp.tasks["safety_kind"].status != "PASS", lp.tasks["safety_kind"]


def test_an_induction_that_did_not_close_leaves_the_pdr_proof_standing():
    """RED on main: the third task's UNKNOWN made a pdr-proved claim PARTIAL."""
    res = _results(_log("unknown"))
    assert res["verdict"] == "PASS" and res["all_proved"] is True, res
    assert res["unbounded_proved"] is True
    [safety] = [p for p in res["properties"] if p["task"] == "safety"]
    assert safety["engine"] == "abc pdr" and safety["bound"] == "unbounded"
    [rec] = res["prove_arms"]
    assert [(a["engine"], a["status"]) for a in rec["arms"]] == [
        ("abc pdr", "PASS"), ("smtbmc yices", "UNKNOWN")]
    assert rec["engines_disagree"] is False
    assert {p["task"] for p in res["properties"]} == {"safety", "bmc"}


def test_both_engines_prove_the_same_claim():
    res = _results(_log("pass"))
    assert res["verdict"] == "PASS" and res["all_proved"] is True
    [rec] = res["prove_arms"]
    assert [a["status"] for a in rec["arms"]] == ["PASS", "PASS"]
    assert "successful proof by k-induction" in _log("pass")


def test_a_counterexample_from_either_arm_is_a_fail():
    res = _results(_log("fail"))
    assert res["verdict"] == "FAIL" and res["all_proved"] is False
    [rec] = res["prove_arms"]
    assert rec["status"] == "FAIL" and rec["selected_engine"] == "abc pdr"


def _parse(safety: str, kind: str, t_safety=None, t_kind=None) -> fpr.LogParse:
    lp = fpr.LogParse()
    lp.tasks["safety"] = fpr.TaskResult("safety", safety, "abc pdr", "prove", 20,
                                        elapsed_s=t_safety)
    lp.tasks["safety_kind"] = fpr.TaskResult("safety_kind", kind, "smtbmc yices",
                                             "prove", 20, elapsed_s=t_kind)
    lp.tasks["bmc"] = fpr.TaskResult("bmc", "PASS", "abc bmc3", "bmc", 12)
    return lp


def test_the_second_engine_can_carry_a_claim_the_first_did_not_close():
    folded, [rec] = fpr.fold_prove_arms(_parse("UNKNOWN", "PASS"))
    assert folded.tasks["safety"].status == "PASS"
    assert folded.tasks["safety"].engine == "smtbmc yices"
    assert rec["selected_engine"] == "smtbmc yices"


def test_when_both_prove_the_faster_arm_is_selected():
    _, [rec] = fpr.fold_prove_arms(_parse("PASS", "PASS", t_safety=9, t_kind=2))
    assert rec["selected_engine"] == "smtbmc yices"
    _, [rec] = fpr.fold_prove_arms(_parse("PASS", "PASS", t_safety=2, t_kind=2))
    assert rec["selected_engine"] == "abc pdr"   # a tie keeps the first engine


def test_engines_that_disagree_are_never_a_pass():
    lp = _parse("PASS", "FAIL")
    res = fpr.build_results(STEM, {k: v for k, v in lp.tasks.items()}, lp, "e", "s")
    assert res["verdict"] == "FAIL" and res["all_proved"] is False
    assert res["prove_arms"][0]["engines_disagree"] is True
    assert any("DISAGREE" in d for d in res["bounded_vs_unbounded"])


def test_the_switch_puts_the_second_engine_into_the_real_proof():
    """In-image, through the real programs. RED on main: the switch is not read."""
    import formal_harness_gen as fhg
    import formal_proof_evidence_check as gate
    missing = [t for t in ("yosys", "sby", "yices-smt2") if shutil.which(t) is None]
    if missing:
        skip_not_verified(
            f"{missing} not on PATH, so no harness can be proved here",
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_t91_step5_second_prove_engine.py")
    project = Path(tempfile.mkdtemp(prefix="t91s5_"))
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L3_PROTOCOL.json").write_text(json.dumps({"no_opcodes_in_input": True}))
    (docs / "L6_FSM.json").write_text(json.dumps({"no_fsm_in_input": True}))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps(
        {"clock_and_reset_waveform": {"resets": [{"name": "rst"}]}}))
    rtl = project / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "ctr.v").write_text(
        "module ctr(input clk, input rst, input en, output reg [3:0] q);\n"
        "  always @(posedge clk) if (rst) q <= 4'd0; else if (en) q <= q + 4'd1;\n"
        "endmodule\n")
    (project / "phase3").mkdir()
    (project / "phase3/librelane_switch.json").write_text(
        json.dumps({"steps": {"5": "dual"}}))
    gen = fhg.generate(project=project, top="ctr")
    assert gen["verdict"] == "EMITTED", gen
    res = fpr.run(project, harness=Path(gen["harness_path"]),
                  rtl=[Path(p) for p in gen["rtl_files"]],
                  top=gen["harness_module"], container=None, timeout=300)
    sby = (project / res["sby"]).read_text()
    assert "safety_kind: smtbmc yices" in sby, sby
    arms = res.get("prove_arms") or []
    assert len(arms) == 1, res
    assert [a["engine"] for a in arms[0]["arms"]] == ["abc pdr", "smtbmc yices"]
    # both engines really ran: each arm's status is its own task's DONE line
    log = (project / res["evidence"]).read_text()
    assert "[ctr_formal_safety_kind] DONE (" in log or "_safety_kind] DONE (" in log, log[-2000:]
    assert arms[0]["arms"][0]["status"] == "PASS", arms
    assert arms[0]["arms"][1]["status"] in ("PASS", "UNKNOWN"), arms
    assert res["all_proved"] is True, res
    rep = gate.audit(project)
    assert rep["verdict"] == "PASS", rep["findings"]   # the name closes by binding
    # the direct arm stays exactly what it was
    (project / "phase3/librelane_switch.json").write_text(
        json.dumps({"steps": {"5": "direct"}}))
    res2 = fpr.run(project, harness=Path(gen["harness_path"]),
                   rtl=[Path(p) for p in gen["rtl_files"]],
                   top=gen["harness_module"], container=None, timeout=300)
    assert "smtbmc" not in (project / res2["sby"]).read_text()
    assert "prove_arms" not in res2
