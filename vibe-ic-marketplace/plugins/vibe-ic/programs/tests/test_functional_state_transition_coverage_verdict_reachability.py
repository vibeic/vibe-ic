#!/usr/bin/env python3
"""functional_state_transition_coverage_check: BOTH verdicts must be reachable.

THE DEFECT
----------
`audit()` answered "I found no testbench under this target" with a WARN
finding and returned before the coverage loop ran. WARN never reaches the
verdict, which is computed as `"PASS" if not errors else "FAIL"`, so the
whole class of targets with zero discovered testbenches could emit only
one verdict: PASS, with `"errors": 0` — certifying "every opcode's
required state assertion appears in some TB" having read no TB at all.

That class was not exotic. Discovery matched only `tb_*.v`, `tb_*.sv`,
`*_tb.v` and `*_tb.sv`; the bare stems `tb.v` and `tb.sv` are the most
common testbench filenames written in this tree and match none of them.
A directory holding a real testbench named `tb.v` scored PASS unread.

HOW THIS FILE IS ORGANISED (and why)
------------------------------------
Verifying one direction is half the property, so the tests are split into
two groups whose behaviour against the UNFIXED program differs on purpose:

  GROUP A — the verdicts that were unreachable. Every test here FAILS
  against the program as it stands on origin/main. They are the mutation
  control: without the fix, the gate cannot produce these outcomes.

  GROUP B — the OTHER verdict. Every test here PASSES against BOTH the
  unfixed and the fixed program, and asserts only on fields that exist in
  both. That is what makes it evidence: if the fix had turned the gate
  into an always-fail gate, this group would go red, and a group that
  only ever ran against the fixed program could not show that.

Every assertion is on the process exit code or on the emitted JSON. No
assertion reads the program's source text.

chip-AGNOSTIC: synthetic Verilog, invented opcodes, no design name, no
PDK, no part number.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "functional_state_transition_coverage_check.py")

# Synthetic side-effect contract: an invented opcode and the register
# change it is required to produce. Nothing here names a real design.
OPCODE = "0x74"
ASSERTION = "awake_q == 1'b1"
COV = f"{OPCODE}:{ASSERTION}"

COVERING_TB = (
    "module tb;\n"
    "  initial begin\n"
    "    send_cmd(8'h74);\n"
    "    #10;\n"
    "    if (awake_q !== 1'b1) $fatal;\n"
    "    $finish;\n"
    "  end\n"
    "endmodule\n"
)


def _run(target: Path, out: Path, *cov_args: str):
    """Run the gate, returning (returncode, parsed JSON report)."""
    args = list(cov_args) or ["--cov", COV]
    r = subprocess.run(
        [sys.executable, str(PROG), str(target), *args, "--json", str(out)],
        capture_output=True, text=True,
    )
    report = json.loads(out.read_text()) if out.exists() else None
    return r.returncode, report


# ====================================================================
# GROUP A — verdicts that were structurally unreachable.
# EVERY test below FAILS against the unfixed program.
# ====================================================================

def test_empty_target_reaches_fail(tmp_path):
    """A target with no testbench at all must not certify coverage.

    Unfixed: WARN only, so errors == 0, verdict PASS, rc 0.
    """
    sim = tmp_path / "sim"
    sim.mkdir()

    rc, report = _run(sim, tmp_path / "a1.json")

    assert rc == 1, "an unmeasured corpus must exit 1, not 0"
    assert report["verdict"] == "FAIL"
    assert report["errors"] >= 1, "FAIL must be backed by at least one error"
    assert "no_tb_files" in {f["rule"] for f in report["findings"]}
    assert {f["severity"] for f in report["findings"]} == {"ERROR"}, (
        "the no-testbench finding must carry a severity the verdict reads; "
        "WARN is why this verdict was unreachable"
    )


def test_bare_stem_testbench_is_actually_read(tmp_path):
    """`tb.v` is a testbench. Not finding it must not read as PASS.

    The gate must either READ the file and score it honestly, or say it
    read nothing — never report a clean verdict over a corpus it silently
    skipped. Here the file is present but drives a DIFFERENT opcode, so
    the only honest verdict is FAIL.

    Unfixed: the four globs miss `tb.v`, zero files are scanned, and the
    gate reports verdict PASS with rc 0.
    """
    sim = tmp_path / "sim"
    sim.mkdir()
    (sim / "tb.v").write_text(
        "module tb;\n"
        "  initial begin\n"
        "    send_cmd(8'h70);\n"   # a DIFFERENT opcode
        "    $finish;\n"
        "  end\n"
        "endmodule\n"
    )

    rc, report = _run(sim, tmp_path / "a2.json")

    assert rc == 1
    assert report["verdict"] == "FAIL"
    rules = {f["rule"] for f in report["findings"]}
    assert "opcode_not_exercised" in rules, (
        "the gate must score the testbench it can see, not skip the "
        "directory as empty"
    )
    assert "no_tb_files" not in rules


def test_vacuous_coverage_entry_reaches_fail(tmp_path):
    """An entry demanding nothing could only ever be scored PASS.

    Same mechanism one level up, in the spec instead of the corpus: the
    gate returns a clean verdict for an opcode whose side-effect it never
    had anything to look for.

    Unfixed: verdict PASS, rc 0.
    """
    sim = tmp_path / "sim"
    sim.mkdir()
    (sim / "tb_top.v").write_text(COVERING_TB)
    cov = tmp_path / "cov.json"
    cov.write_text(json.dumps([{"opcode": OPCODE, "must_assert_set": []}]))

    rc, report = _run(sim, tmp_path / "a3.json", "--coverage", str(cov))

    assert rc == 1
    assert report["verdict"] == "FAIL"
    assert "coverage_entry_asserts_nothing" in {
        f["rule"] for f in report["findings"]}


def test_pass_must_report_the_corpus_it_was_measured_on(tmp_path):
    """A PASS has to say how many testbenches it read.

    This is what makes the repaired verdict auditable rather than
    trusted: `tb_files_scanned == 0` alongside `verdict: PASS` is the
    exact shape of the defect, and a reader can now see it.

    Unfixed: the report has no such field at all.
    """
    sim = tmp_path / "sim"
    sim.mkdir()
    (sim / "tb_top.v").write_text(COVERING_TB)

    rc, report = _run(sim, tmp_path / "a4.json")

    assert rc == 0
    assert report["verdict"] == "PASS"
    assert report["tb_files_scanned"] == 1
    assert report["opcodes_unverified"] == 0


def test_zero_padded_opcode_is_not_a_false_failure(tmp_path):
    """`0x0a` driven as `8'h0A` must PASS — this is a FAIL nobody earned.

    The old normaliser used `op.lower().lstrip("0x")`, which strips EVERY
    leading `0` and `x`: `0x0a` became `a`, and the pattern built from it
    could not match the `8'h0a` literal the TB actually writes. Making
    the FAIL verdict reachable is only safe if the FAILs are real, so
    this fake one is removed in the same change.

    Unfixed: rc 1 with `opcode_not_exercised` — the filename here is
    deliberately `tb_top.v`, which the OLD globs already matched, so the
    unfixed program genuinely scans the file and still gets it wrong.
    """
    sim = tmp_path / "sim"
    sim.mkdir()
    (sim / "tb_top.v").write_text(
        "module tb;\n"
        "  initial begin\n"
        "    send_cmd(8'h0A);\n"
        "    #10;\n"
        "    if (mode_q !== 2'd1) $fatal;\n"
        "    $finish;\n"
        "  end\n"
        "endmodule\n"
    )

    rc, report = _run(sim, tmp_path / "a5.json", "--cov", "0x0a:mode_q == 2'd1")

    assert rc == 0, (
        "an opcode whose hex body has a leading zero is still driven by "
        f"the TB; findings={report['findings']}"
    )
    assert report["verdict"] == "PASS"


# ====================================================================
# GROUP B — the OTHER verdict. Every test below PASSES against BOTH the
# unfixed and the fixed program. If the fix had made the gate
# always-fail, this group would go red.
# ====================================================================

def test_covered_testbench_still_reaches_pass(tmp_path):
    """A TB that drives the opcode and asserts the side-effect: PASS.

    `tb_top.v` matched the old globs too, so both versions really scan
    this file and both must agree it is covered.
    """
    sim = tmp_path / "sim"
    sim.mkdir()
    (sim / "tb_top.v").write_text(COVERING_TB)

    rc, report = _run(sim, tmp_path / "b1.json")

    assert rc == 0
    assert report["verdict"] == "PASS"
    assert report["errors"] == 0


def test_bare_stem_testbench_can_also_pass(tmp_path):
    """Widened discovery must not be a one-way street to FAIL.

    The same filename that FAILs in GROUP A when it drives the wrong
    opcode must reach PASS when it drives the right one.
    """
    sim = tmp_path / "sim"
    sim.mkdir()
    (sim / "tb.v").write_text(COVERING_TB)

    rc, report = _run(sim, tmp_path / "b2.json")

    assert rc == 0
    assert report["verdict"] == "PASS"
    assert report["errors"] == 0


def test_single_file_target_still_reaches_pass(tmp_path):
    """Pointing the gate straight at one file keeps working."""
    tb = tmp_path / "some_tb.sv"
    tb.write_text(COVERING_TB)

    rc, report = _run(tb, tmp_path / "b3.json")

    assert rc == 0
    assert report["verdict"] == "PASS"
    assert report["errors"] == 0


def test_multiple_opcodes_all_covered_reaches_pass(tmp_path):
    """Two opcodes, both driven and both asserted: still PASS."""
    sim = tmp_path / "sim"
    sim.mkdir()
    (sim / "tb_top.v").write_text(
        "module tb;\n"
        "  initial begin\n"
        "    send_cmd(8'h74);\n"
        "    if (awake_q !== 1'b1) $fatal;\n"
        "    send_cmd(8'h76);\n"
        "    if (wake_pulse_active !== 1'b0) $fatal;\n"
        "    $finish;\n"
        "  end\n"
        "endmodule\n"
    )

    rc, report = _run(sim, tmp_path / "b4.json",
                      "--cov", "0x74:awake_q == 1'b1",
                      "--cov", "0x76:wake_pulse_active == 1'b0")

    assert rc == 0
    assert report["verdict"] == "PASS"
    assert report["errors"] == 0


def test_uncovered_opcode_still_reaches_fail(tmp_path):
    """The gate's original FAIL path is untouched.

    Both versions scan `tb_top.v`, see the opcode driven, and see no
    assertion on the side-effect.
    """
    sim = tmp_path / "sim"
    sim.mkdir()
    (sim / "tb_top.v").write_text(
        "module tb;\n"
        "  initial begin\n"
        "    send_cmd(8'h74);\n"
        "    $finish;\n"
        "  end\n"
        "endmodule\n"
    )

    rc, report = _run(sim, tmp_path / "b5.json")

    assert rc == 1
    assert report["verdict"] == "FAIL"
    assert "assertion_missing" in {f["rule"] for f in report["findings"]}


def test_argument_error_is_still_distinct_from_fail(tmp_path):
    """No coverage spec is rc 2, not a manufactured FAIL."""
    sim = tmp_path / "sim"
    sim.mkdir()
    (sim / "tb_top.v").write_text(COVERING_TB)

    r = subprocess.run([sys.executable, str(PROG), str(sim)],
                       capture_output=True, text=True)
    assert r.returncode == 2
