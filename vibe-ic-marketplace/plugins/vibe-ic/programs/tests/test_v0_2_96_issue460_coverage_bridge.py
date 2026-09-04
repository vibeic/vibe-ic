#!/usr/bin/env python3
"""v0.2.96 — ORGANIC-20260606 #460 (REOPENED with field counter-evidence).

The first #460 fix (_emit_oracle_sim_bridge) wrote the Step-4 *simulation*
artifacts (phase2/stage1/sim/{results.xml,pass.flag}) from a genuine oracle
PASS. But its tests only asserted those bridge files exist — they never ran
the real flow_compliance_check, so they missed that Step 4 is an `all_of`
gate whose COVERAGE sub-input (reports/phase2/coverage/coverage_actual.json)
STAYED `SKIPPED-CONDITION`: the coverage-manifest block only rglob'd
`ref_tb.log`, and the oracle track only ever produces `oracle.log`. A
SKIPPED-CONDITION coverage required-output is read by the evidence-integrity
scan and propagates to the WHOLE step → Step 4 = SKIPPED-CONDITION, NOT
counted in executed-PASS, Overall FAIL.

This fix makes the coverage-manifest block treat the oracle track the SAME
way _emit_oracle_sim_bridge does: when the genuine-oracle-PASS conditions
hold (functional_verified, vectors_passed==vectors_total>0, oracle.log
present non-empty), extract the scenario / vector evidence FROM oracle.log
(ORACLE_VECTOR/ORACLE_TB_DONE lines — the SOLE evidence source, no canned
content) and write a coverage PASS pointing back at oracle.log. A
skeleton-WAIVED / FAILed run still gets SKIPPED-CONDITION.

Tests below:
  (A) the coverage-manifest block: oracle-PASS → coverage PASS citing
      oracle.log with REAL per-vector scenarios; FAIL/WAIVED/no-log → SKIP.
  (B) END-TO-END self-verification: build an oracle-track replica project,
      run the REAL flow_compliance_check --stage 1, assert Step 4 is lifted
      out of SKIPPED-CONDITION. (This is the gap the prior fix missed.)
      CORRECTED by the coverage-credit split: these used to assert Step 4 ==
      PASS and +1 executed-PASS. An oracle functional PASS is not Verilator
      coverage, and this replica measures none, so the honest tier is a
      disclosed WAIVED-DEFERRED (review_required, NOT executed-PASS) — and a
      plain FAIL on a host that HAS the toolchain. See the corrected tests'
      own docstrings for the old expectation and why it was wrong.
  (C) regression guards for the prior CORRECT behaviour (ref_tb path,
      negative SKIP self-reports) + anti-canned source guard.
  (D) incidental legacy stale-SKIP top-level sim/results.xml replacement.

chip-AGNOSTIC: synthetic generic fixtures only (datacore / no chip/SKU).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import design_one_shot_runner as P  # noqa: E402
import _path_layout as PL  # noqa: E402

RUNNER_SRC = (PROG_DIR / "design_one_shot_runner.py").read_text()

DUT = ("module datacore(input clk, input d, output reg q);\n"
       "  always @(posedge clk) q <= d;\nendmodule\n")


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _with_rtl(project: Path) -> None:
    rtl = PL.rtl_dir(project)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "datacore.v").write_text(DUT)


def _oracle_log(project: Path, body: str) -> Path:
    run = PL.sim_full_stack_dir(project) / "oracle_run"
    run.mkdir(parents=True, exist_ok=True)
    t = run / "oracle.log"
    t.write_text(body)
    return t


def _oracle_step(status: str, vp: int, vt: int,
                 fv: bool) -> "P.StepResult":
    return P.StepResult(
        name="reference_tb", status=status, duration_s=0.1,
        detail=f"oracle {vp}/{vt}",
        extras={"verification_track": "oracle_tb",
                "functional_verified": fv,
                "vectors_passed": vp, "vectors_total": vt})


def _cov(project: Path) -> dict:
    return json.loads(
        PL.report_path(project, "coverage/coverage_actual.json").read_text())


# ===========================================================================
# (helper) _oracle_coverage_evidence parses ONLY what the log carries
# ===========================================================================
def test_oracle_coverage_evidence_parses_real_lines():
    log = ("ORACLE_VECTOR alpha PASS\n"
           "ORACLE_VECTOR beta PASS\n"
           "ORACLE_VECTOR gamma FAIL (expected q=1)\n"
           "ORACLE_TB_DONE pass=2/3\n")
    scen, n_pass, n_total = P._oracle_coverage_evidence(log)
    # only the PASSing vectors are listed (gamma FAILed → not a covered scen)
    assert scen == ["alpha", "beta"]
    # the real summary counts are read verbatim from the log
    assert (n_pass, n_total) == (2, 3)


def test_oracle_coverage_evidence_no_summary_line():
    scen, n_pass, n_total = P._oracle_coverage_evidence("garbage\n")
    assert scen == []
    assert n_pass is None and n_total is None


def test_oracle_coverage_evidence_no_canned_names():
    # whatever names the log carries are exactly what comes back — nothing
    # is invented when the log is empty of vector lines.
    scen, _, _ = P._oracle_coverage_evidence("ORACLE_TB_DONE pass=5/5\n")
    assert scen == []


# ===========================================================================
# (A) coverage-manifest block — oracle track
# ===========================================================================
def test_coverage_pass_on_genuine_oracle(tmp_path):
    _with_rtl(tmp_path)
    log = _oracle_log(
        tmp_path,
        "ORACLE_VECTOR vec0 PASS\nORACLE_VECTOR vec1 PASS\n"
        "ORACLE_VECTOR vec2 PASS\nORACLE_TB_DONE pass=3/3\n")
    assert P._emit_oracle_sim_bridge(tmp_path, log, 3, 3)
    P.step_emit_phase2_manifests(tmp_path, [_oracle_step("PASS", 3, 3, True)])

    cov = _cov(tmp_path)
    assert cov["verdict"] == "PASS"
    assert cov["verification_track"] == "oracle_tb"
    # evidence backlinks to the REAL oracle.log (relative to project)
    assert cov["evidence"].endswith("oracle_run/oracle.log")
    assert (tmp_path / cov["evidence"]).is_file()
    # scenarios are the REAL per-vector names from THIS log — no canned list
    assert cov["scenarios_covered"] == ["vec0", "vec1", "vec2"]
    assert cov["vectors_passed"] == 3 and cov["vectors_total"] == 3


def test_coverage_skip_on_oracle_fail(tmp_path):
    _with_rtl(tmp_path)
    _oracle_log(tmp_path, "ORACLE_VECTOR vec0 PASS\nORACLE_TB_DONE pass=3/8\n")
    P.step_emit_phase2_manifests(tmp_path, [_oracle_step("FAIL", 3, 8, False)])
    cov = _cov(tmp_path)
    assert cov["verdict"] == "SKIPPED-CONDITION"
    assert "scenarios_covered" not in cov


def test_coverage_skip_on_oracle_waived_zero_vectors(tmp_path):
    _with_rtl(tmp_path)
    _oracle_log(tmp_path, "ORACLE_TB_DONE pass=0/0\n")
    P.step_emit_phase2_manifests(
        tmp_path, [_oracle_step("WAIVED", 0, 0, False)])
    assert _cov(tmp_path)["verdict"] == "SKIPPED-CONDITION"


def test_coverage_skip_when_oracle_log_absent(tmp_path):
    # extras CLAIM a PASS but no oracle.log on disk (tampered plan) → SKIP,
    # never a manufactured coverage PASS.
    _with_rtl(tmp_path)
    P.step_emit_phase2_manifests(tmp_path, [_oracle_step("PASS", 5, 5, True)])
    assert _cov(tmp_path)["verdict"] == "SKIPPED-CONDITION"


def test_coverage_scenarios_capped_and_real(tmp_path):
    _with_rtl(tmp_path)
    lines = "".join(f"ORACLE_VECTOR v{i} PASS\n" for i in range(40))
    _oracle_log(tmp_path, lines + "ORACLE_TB_DONE pass=40/40\n")
    P.step_emit_phase2_manifests(
        tmp_path, [_oracle_step("PASS", 40, 40, True)])
    cov = _cov(tmp_path)
    assert cov["verdict"] == "PASS"
    # capped at 24 like the ref_tb path, and every listed name is real
    assert len(cov["scenarios_covered"]) == 24
    assert all(re.fullmatch(r"v\d+", s) for s in cov["scenarios_covered"])


# ===========================================================================
# (B) END-TO-END — the gap the prior fix missed
# ===========================================================================
def _build_oracle_replica(project: Path, vp: int, vt: int,
                          status: str = "PASS") -> None:
    """Build a Step-4 oracle-track replica using ONLY the real runner
    emitters (no hand-written coverage_actual.json), then satisfy the rest
    of Step 4's required_outputs (*.log)."""
    _with_rtl(project)
    docs = PL.generated_docs_dir(project)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "doc_class": "integration_spec",
        "module_name": "datacore",
        "ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "d", "direction": "input", "width": 1},
            {"name": "q", "direction": "output", "width": 1},
        ],
    }) + "\n")
    body = ("".join(f"ORACLE_VECTOR vec{i} PASS\n" for i in range(vp))
            + f"ORACLE_TB_DONE pass={vp}/{vt}\n")
    log = _oracle_log(project, body)
    fv = (status == "PASS" and vp == vt and vt > 0)
    if fv:
        # the runner calls this on a genuine PASS
        assert P._emit_oracle_sim_bridge(project, log, vp, vt)
    # Step-4 required_outputs also needs a phase2/stage1/sim/*.log
    sim = PL.sim_dir(project)
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "sim.log").write_text("oracle run transcript\n")
    P.step_emit_phase2_manifests(project, [_oracle_step(status, vp, vt, fv)])


#: Pin the Verilator-capability decision so these end-to-end assertions are a
#: property of the FLOW, not of whatever the CI host happens to have
#: installed. `verilator_coverage_measure check` reads this env var to decide
#: whether an absent coverage measurement is a disclosed capability gap
#: (rc=3 -> WAIVED-DEFERRED) or a defect (rc=1 -> FAIL).
_NO_VERILATOR = "__vibeic_no_such_verilator__"


def _run_compliance_stage1(project: Path,
                           verilator_bin: str = _NO_VERILATOR) -> str:
    import os as _os
    env = dict(_os.environ)
    env["VIBE_IC_VERILATOR_BIN"] = verilator_bin
    r = subprocess.run(
        [sys.executable, str(PROG_DIR / "flow_compliance_check.py"),
         str(project), "--stage", "1"],
        capture_output=True, text=True, env=env)
    return r.stdout + r.stderr


def _executed_pass(out: str) -> int:
    m = re.search(r"\((\d+)/(\d+) executed PASS", out)
    assert m, out
    return int(m.group(1))


def _waived(out: str) -> int:
    m = re.search(r"WAIVED-DEFERRED=(\d+)", out)
    assert m, out
    return int(m.group(1))


def _step4_line(out: str) -> str:
    for ln in out.splitlines():
        if "Step  4" in ln or re.search(r"\bStep\s+4\b", ln):
            return ln
    return ""


def _step4_block(out: str) -> str:
    """The Step-4 line AND the reasons printed under it.

    The step's TIER is one word; its DISCLOSURES are the `└─` lines beneath.
    A test that reads only the word cannot tell "not measured, and here is the
    named reason" from "not measured, and nothing said".
    """
    lines = out.splitlines()
    for i, ln in enumerate(lines):
        if re.search(r"\bStep\s+4\b", ln):
            blk = [ln]
            for nxt in lines[i + 1:]:
                if nxt.lstrip().startswith("\u2514\u2500"):
                    blk.append(nxt)
                elif nxt.strip():
                    break
            return "\n".join(blk)
    return ""


# --- CORRECTED (coverage-credit split) -------------------------------------
# The two tests below used to assert that an oracle-track PASS makes Step 4
# a PASS and ADDS ONE to the headline "x/y executed PASS". They ENCODED THE
# DEFECT this file's own fix introduced at the flow level:
#
#   #460 resolved a Step-4 SKIPPED-CONDITION by having design_one_shot_runner
#   write a FUNCTIONAL-verification verdict payload (verdict / evidence /
#   verification_track=oracle_tb / scenarios_covered — no `totals` container)
#   to reports/phase2/coverage/coverage_actual.json, the path the flow
#   declares as the Verilator coverage artefact. Step 4's own gate then runs
#   `verilator_coverage_measure check` against that path. No line / toggle /
#   branch coverage exists anywhere in these replicas, and none was measured.
#
# An oracle functional PASS is a real verification result, but it is not
# coverage, and Step 4 is "Simulation (testbench-based + L10/L12 coverage +
# Verilator coverage)". A gate may EXPLAIN an absent artefact; it may not
# CERTIFY the step done without one. So the corrected requirement is:
#   * an oracle PASS still LIFTS Step 4 out of SKIPPED-CONDITION — that was
#     #460's actual complaint and it still holds;
#   * an oracle PASS is still DISTINGUISHABLE from an oracle FAIL;
#   * but it is a DISCLOSED, review_required deferral, NOT executed-PASS.
# The assertions are corrected to a stricter verdict, not relaxed.


def test_e2e_oracle_pass_lifts_step4_out_of_skipped_condition(tmp_path):
    """WAS `assert "PASS" in line`. #460's real complaint — Step 4 stuck at
    SKIPPED-CONDITION for a genuine oracle PASS — is still fixed.

    THE BUCKET NAME MOVED, THE REQUIREMENT DID NOT. This used to require the
    WAIVED-DEFERRED tier ON THE STEP LINE. Bisected, one variable: green at
    2a9d21368, red at bf6292fa32 (v1.15.6, #1978), which classified two of
    this step's self-skips as INCOMPLETE — and the INCOMPLETE branch outranks
    the waiver branch ON PURPOSE, in that branch's own words: "a declared N/A
    sibling or a waiver must not launder the incomplete clause into
    SKIPPED-CONDITION / WAIVED". INCOMPLETE then demotes to MISSING on the
    unproduced `coverage_verilator.json`. Both tiers sit OUTSIDE the
    executed-PASS numerator and both are stricter than WAIVED, so pinning the
    softer word would be asking the flow to grade this replica more kindly
    than it does.

    What must not be lost is the DISCLOSURE, and it was: `waiver_hints` were
    surfaced on the WAIVED branch only, so every other tier dropped the
    capability gap from the step entirely. That is fixed at the producer in
    this same change, and asserted here on the step's own reasons rather than
    on its tier word.
    """
    _build_oracle_replica(tmp_path, 3, 3, "PASS")
    out = _run_compliance_stage1(tmp_path)
    line = _step4_line(out)
    block = _step4_block(out)
    assert line, f"Step 4 not in output:\n{out}"
    assert "SKIPPED-CONDITION" not in line, f"Step 4 back to #460's bug:\n{line}"
    assert "[PASS" not in line, (
        f"an oracle PASS with no coverage measurement is not a Step-4 PASS:"
        f"\n{line}")
    assert "PASS_WITH_WAIVERS" in block, (
        f"the verilator capability gap that made this step non-PASS is not "
        f"disclosed on the step at all:\n{block}")
    assert "coverage_verilator.json" in block, (
        f"the unmeasured coverage artefact must be named:\n{block}")


def test_e2e_oracle_pass_is_deferred_not_counted_without_coverage(tmp_path):
    """WAS `assert good_pass == base_pass + 1` — i.e. it demanded that an
    oracle PASS with NO coverage measurement be counted into the headline
    executed-PASS numerator. It must not be. It must instead appear in the
    WAIVED-DEFERRED bucket, which is reviewable and leaves the required
    denominator alone."""
    base = tmp_path / "base"
    _build_oracle_replica(base, 3, 8, "FAIL")
    base_out = _run_compliance_stage1(base)

    good = tmp_path / "good"
    _build_oracle_replica(good, 3, 3, "PASS")
    good_out = _run_compliance_stage1(good)

    # Still DISTINGUISHABLE from a failing oracle (the honesty #460 bought).
    assert "FAIL" in _step4_line(base_out), _step4_line(base_out)
    assert "FAIL" not in _step4_line(good_out), _step4_line(good_out)
    assert _step4_line(good_out).split("]")[0] \
        != _step4_line(base_out).split("]")[0], (
        f"an oracle PASS and an oracle FAIL resolved to the same Step-4 tier\n"
        f"--- base ---\n{_step4_line(base_out)}\n"
        f"--- good ---\n{_step4_line(good_out)}")

    # But NOT certified: no coverage was measured, so the executed-PASS
    # numerator must not grow, and the deferral must be visible.
    assert _executed_pass(good_out) == _executed_pass(base_out), (
        f"an unmeasured coverage step was counted as executed PASS\n"
        f"--- base ---\n{base_out}\n--- good ---\n{good_out}")
    # VISIBLE — on the step, not merely in the ledger at the foot of the
    # report. WAS `_waived(good) == _waived(base) + 1`, a count of steps whose
    # TIER is WAIVED; the tier is now the stricter INCOMPLETE/MISSING (see the
    # sibling test above), and the tally correctly does not count it. The
    # obligation the old assertion stood for — "production tapeout review must
    # still close it" — is what is asserted, at the place a reviewer reads it.
    good_block = _step4_block(good_out)
    assert "PASS_WITH_WAIVERS" in good_block, (
        f"the deferral was not disclosed on the step at all\n{good_block}")
    assert "production tapeout review" in good_block, (
        f"the disclosure does not carry the review obligation\n{good_block}")
    assert "PASS_WITH_WAIVERS" not in _step4_block(base_out), (
        f"a FAILing oracle must not acquire a waiver disclosure\n"
        f"{_step4_block(base_out)}")


def test_e2e_oracle_pass_is_a_hard_fail_when_verilator_is_installed(tmp_path):
    """The deferral is a CAPABILITY gap, not a standing exemption: on a host
    that HAS the toolchain, an oracle PASS with no coverage measurement is a
    plain Step-4 FAIL."""
    _build_oracle_replica(tmp_path, 3, 3, "PASS")
    out = _run_compliance_stage1(tmp_path, verilator_bin="sh")
    line = _step4_line(out)
    assert line, out
    assert "FAIL" in line, f"toolchain present but step 4 not red:\n{line}"


def test_e2e_oracle_fail_step4_not_pass(tmp_path):
    # honesty regression: a FAILing oracle must NOT yield a Step-4 PASS.
    _build_oracle_replica(tmp_path, 3, 8, "FAIL")
    out = _run_compliance_stage1(tmp_path)
    line = _step4_line(out)
    assert line and "PASS" not in line, f"Step 4 wrongly PASS:\n{line}"


# ===========================================================================
# (C) regression guards — prior CORRECT behaviour preserved
# ===========================================================================
def test_ref_tb_path_still_pass(tmp_path):
    # the original ref_tb (non-oracle) path must remain a coverage PASS.
    _with_rtl(tmp_path)
    sim = PL.sim_dir(tmp_path)
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "ref_tb.log").write_text("SCENARIO foo PASS\nTEST bar PASS\n")
    step = P.StepResult(name="reference_tb", status="PASS",
                        duration_s=0.1, detail="ref tb", extras={})
    P.step_emit_phase2_manifests(tmp_path, [step])
    cov = _cov(tmp_path)
    assert cov["verdict"] == "PASS"
    assert sorted(cov["scenarios_covered"]) == ["bar", "foo"]
    # ref_tb path does NOT mislabel itself as the oracle track
    assert cov.get("verification_track") != "oracle_tb"


def test_no_rtl_no_log_still_skip(tmp_path):
    # pure shape with neither ref_tb.log nor a genuine oracle → SKIP.
    (PL.rtl_dir(tmp_path)).mkdir(parents=True, exist_ok=True)
    step = P.StepResult(name="reference_tb", status="SKIP",
                        duration_s=0.1, detail="nothing", extras={})
    P.step_emit_phase2_manifests(tmp_path, [step])
    assert _cov(tmp_path)["verdict"] == "SKIPPED-CONDITION"


def test_source_has_no_canned_scenarios():
    # the oracle coverage branch must extract from the log, never hardcode
    # scenario / vector names.
    assert '"GET_ID"' not in RUNNER_SRC
    assert '"GET_STATE"' not in RUNNER_SRC
    # the oracle branch cites #460 and delegates scenario extraction to the
    # helper (parsing lives there, not as an inline canned scenario list).
    i = RUNNER_SRC.index("Coverage manifest (#436)")
    window = RUNNER_SRC[i:i + 3200]
    assert "_oracle_coverage_evidence" in window
    assert "#460" in window
    # the vector-name parse is a regex over the log, not a hardcoded list
    helper = RUNNER_SRC[RUNNER_SRC.index("def _oracle_coverage_evidence"):]
    helper = helper[:helper.index("def _run_oracle_tb")]
    assert "re.findall" in helper and "ORACLE_VECTOR" in helper
    # no literal scenario-name list is assigned in the helper
    assert "scenarios_covered = [" not in helper


# ===========================================================================
# (D) incidental — legacy stale top-level sim/results.xml replacement
# ===========================================================================
def test_legacy_stale_skip_json_replaced(tmp_path):
    leg = tmp_path / "sim"
    leg.mkdir(parents=True)
    (leg / "results.xml").write_text(
        json.dumps({"verdict": "SKIP", "reason": "old #433 skip"}) + "\n")
    log = _oracle_log(tmp_path, "ORACLE_VECTOR a PASS\nORACLE_TB_DONE pass=4/4\n")
    assert P._emit_oracle_sim_bridge(tmp_path, log, 4, 4)
    txt = (leg / "results.xml").read_text()
    assert "<verdict>PASS</verdict>" in txt
    assert "oracle_tb" in txt


def test_legacy_stale_skip_xml_replaced(tmp_path):
    leg = tmp_path / "sim"
    leg.mkdir(parents=True)
    (leg / "results.xml").write_text(
        "<results><verdict>SKIP</verdict><reason>old</reason></results>\n")
    log = _oracle_log(tmp_path, "ORACLE_TB_DONE pass=2/2\n")
    assert P._emit_oracle_sim_bridge(tmp_path, log, 2, 2)
    assert "<verdict>PASS</verdict>" in (leg / "results.xml").read_text()


def test_legacy_real_pass_left_untouched(tmp_path):
    leg = tmp_path / "sim"
    leg.mkdir(parents=True)
    real = ("<results><verdict>PASS</verdict>"
            "<source>some other real run</source></results>\n")
    (leg / "results.xml").write_text(real)
    log = _oracle_log(tmp_path, "ORACLE_TB_DONE pass=2/2\n")
    assert P._emit_oracle_sim_bridge(tmp_path, log, 2, 2)
    # a non-SKIP legacy file is NOT overwritten — nothing is destroyed
    assert (leg / "results.xml").read_text() == real


def test_no_legacy_file_no_crash(tmp_path):
    # no project-root sim/ at all → bridge still emits canonical artifacts.
    log = _oracle_log(tmp_path, "ORACLE_TB_DONE pass=1/1\n")
    assert P._emit_oracle_sim_bridge(tmp_path, log, 1, 1)
    assert not (tmp_path / "sim" / "results.xml").exists()
    assert (PL.sim_dir(tmp_path) / "results.xml").is_file()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
