#!/usr/bin/env python3
"""Three findings from the opentitan_aes close-loop, each with its control.

1. The full-stack testbench asserted NOTHING. It instantiated the DUT, clocked
   it, printed a byte/bit tally and finished; `testbench_exists_check.
   count_test_cases` scored it 0 in every run tree measured on this host. It
   now checks one property — every DUT output resolvable after reset release —
   and the connectivity bridge REFUSES on a failure, so the check can block.

2. A JSON-emitting gate's refusal reached the P0 record as `"message": "{"`.
   MEASURED on `reports/audit/phase23_completion_audit.json`: the whole stated
   reason `testbench_exists_check` FAILed was the first byte of its report.

3. Three `advisory_reason` strings in the canonical flow claimed a refusal was
   being "swallowed" by the advisory slot, for gates whose refusal already
   FAILS the step. Prose that contradicts the code sends the next reader to
   patch the enforcement layer, which is correct.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as DOSR  # noqa: E402
import flow_compliance_check as FCC  # noqa: E402
import testbench_exists_check as TBC  # noqa: E402


# --------------------------------------------------------------------------
# 1. the full-stack testbench now checks something
# --------------------------------------------------------------------------
def _tb_text() -> str:
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    return src


def test_the_generator_emits_one_check_per_dut_output():
    src = _tb_text()
    assert "post_reset_resolvable" in src
    assert "FULL_STACK_TB_CHECKS pass=%0d fail=%0d" in src
    # The X-reduction is the width-safe form, so a bus is covered by the same
    # line as a scalar.
    assert "=== 1'bx" in src


def test_the_generator_says_so_when_there_is_nothing_to_check():
    """A silent absence of check lines is indistinguishable from the
    pre-v1.15.51 testbench that checked nothing on purpose."""
    assert "no observable output" in _tb_text()


def _bridge(tmp_path: Path, transcript_text: str) -> bool:
    proj = tmp_path / "p"
    log = proj / "phase2" / "stage1" / "sim_full_stack" / "full_stack.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(transcript_text)
    return DOSR._emit_connectivity_sim_bridge(
        proj, log, "chip_top", "generic_full_stack track")


DONE = "FULL_STACK_TB_DONE bytes=0 bits=0\n"


def test_the_connectivity_bridge_is_written_when_the_checks_pass(tmp_path):
    assert _bridge(tmp_path, "CHECK PASS post_reset_resolvable q\n"
                             "FULL_STACK_TB_CHECKS pass=4 fail=0\n" + DONE)


def test_the_connectivity_bridge_is_REFUSED_when_a_check_fails(tmp_path):
    """The teeth. Reaching the end with an unresolved output is not
    CONNECTIVITY_PASS, and without this the new check is a printed opinion."""
    assert not _bridge(tmp_path, "CHECK FAIL post_reset_resolvable q\n"
                                 "FULL_STACK_TB_CHECKS pass=3 fail=1\n" + DONE)


def test_a_transcript_without_the_completion_marker_is_still_refused(tmp_path):
    assert not _bridge(tmp_path, "FULL_STACK_TB_CHECKS pass=4 fail=0\n")


def test_an_older_transcript_with_no_check_line_is_unaffected(tmp_path):
    """NEGATIVE CONTROL for the new clause: a transcript from before the checks
    existed must keep its historical verdict, not fail closed on absence."""
    assert _bridge(tmp_path, DONE)


# --------------------------------------------------------------------------
# 2. a JSON gate's refusal says why
# --------------------------------------------------------------------------
def test_a_json_report_yields_the_deciding_finding(tmp_path):
    (tmp_path / "top.v").write_text("module top; endmodule\n")
    run = subprocess.run(
        [sys.executable, str(PROGRAMS / "testbench_exists_check.py"),
         "--rtl-dir", str(tmp_path)],
        capture_output=True, text=True)
    assert run.returncode == 1
    line = FCC._p0_first_line(run.stdout.strip())
    assert line.startswith("NO_TESTBENCH: ")
    assert line != "{"


def test_an_error_finding_outranks_a_warning():
    report = json.dumps({"findings": [
        {"severity": "WARNING", "category": "W", "message": "a warning"},
        {"severity": "ERROR", "category": "E", "message": "the reason"},
    ]})
    assert FCC._p0_first_line(report) == "E: the reason"


def test_plain_text_and_malformed_output_keep_the_historical_first_line():
    """NEGATIVE CONTROL: every gate that was already legible must say exactly
    what it said before."""
    assert FCC._p0_first_line("[FAIL] x: y\nmore") == "[FAIL] x: y"
    assert FCC._p0_first_line("{not json") == "{not json"
    assert FCC._p0_first_line('{"summary": {}}') == '{"summary": {}}'
    assert FCC._p0_first_line("") == ""


def test_the_gate_stdout_is_still_pure_json(tmp_path):
    """The fix is on the READER. A verdict line prepended to stdout would break
    every consumer that parses it, and there is one."""
    (tmp_path / "top.v").write_text("module top; endmodule\n")
    run = subprocess.run(
        [sys.executable, str(PROGRAMS / "testbench_exists_check.py"),
         "--rtl-dir", str(tmp_path)],
        capture_output=True, text=True)
    assert json.loads(run.stdout)["program"] == "testbench_exists_check"


# --------------------------------------------------------------------------
# 3. the flow's own prose may not contradict its own enforcement
# --------------------------------------------------------------------------
_SWALLOW = "swallowing a live finding"


def test_no_advisory_reason_claims_a_swallowed_refusal_it_cannot_have():
    """A gate whose module does NOT declare `ENFORCEMENT: advisory` is not
    exempted by `_gate_is_two_source_advisory`, so its refusal maps to
    enforcement=BLOCKING and FAILS the step. Three rows said the opposite."""
    lines = (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text(
    ).splitlines()
    offenders = []
    for i, line in enumerate(lines):
        if _SWALLOW not in line:
            continue
        m = re.search(r'command: "([A-Za-z0-9_]+)', lines[i - 1])
        gate = m.group(1) if m else ""
        if not gate or not FCC._gate_is_two_source_advisory(gate):
            offenders.append((i + 1, gate))
    assert offenders == [], (
        "these rows claim the advisory slot swallows their refusal, but the "
        f"refusal already fails the step: {offenders}")


def test_the_claim_is_still_made_where_it_is_true():
    """VACUITY CONTROL. If the phrase were simply deleted everywhere the test
    above would pass while asserting nothing."""
    text = (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text()
    assert text.count(_SWALLOW) >= 5
