#!/usr/bin/env python3
"""ORGANIC #887 — a scan that examined ZERO files must not be a plain PASS.

MEASURED DEFECT (origin/main @ dee025059, 159 flow-gate clauses run against one
EMPTY directory):

    27 clauses exit 0. 24 of them DISCLOSE why — `VACUOUS_PASS:`,
    `NOT_APPLICABLE`, "skipped: no L7 document". Exactly two exit 0 with ZERO
    bytes of output on either stream:

        step 3  program_exit_zero: cdc_async_input_check    rc=0, 0 bytes
        step 3  program_exit_zero: reset_dependency_check   rc=0, 0 bytes

    Their JSON recorded `"files_scanned": 0` directly beside `"passed": true`.
    Emitting no sentinel, they were scored a plain PASS and stayed in the
    published "X/Y executed PASS" numerator — while their two siblings on the
    SAME `all_of` answered the same empty tree with rc 1 (`cdc_crossing_check`)
    and rc 2 (`clock_domain_reg_crossing_check`). Four gates, one tree, two
    different answers.

WHAT THIS TEST PINS

  1. An empty tree produces the repo's EXISTING `VACUOUS_PASS:` disclosure at
     line start, and the JSON says `verdict == "VACUOUS_PASS"`.
  2. The exit code STAYS 0 — the gates are unconditional `program_exit_zero`
     clauses and a project that has not authored RTL yet is not a defect. This
     is the whole reason the sentinel exists rather than a new exit code.
  3. `flow_compliance_check`'s OWN reader promotes the step out of plain PASS.
     Pinning the sentinel alone would pass even if the consumer never read it.
  4. A tree WITH real RTL is still a plain PASS — the disclosure must not
     over-fire, or every honest run would be downgraded.

Chip-AGNOSTIC: the fixture RTL names no design, PDK, vendor or cell.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent

#: The two gates that certified an empty tree in silence, with the gate-output
#: JSON path step 3 actually gives each one.
GATES = [
    ("cdc_async_input_check", "reports/phase2/gates/cdc_async_input.json"),
    ("reset_dependency_check", "reports/phase2/gates/cdc_reset_dep.json"),
]

#: Minimal, correctly-synchronised RTL. Its only job is to be a NON-empty
#: authoritative scan corpus that both gates pass cleanly.
CLEAN_RTL = """\
module top(input clk, input rst_n, input data_pad);
  reg sync1, sync2;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin sync1 <= 0; sync2 <= 0; end
    else begin sync1 <= data_pad; sync2 <= sync1; end
  wire safe = sync2;
endmodule
"""


def _run(gate: str, json_rel: str, root: Path) -> subprocess.CompletedProcess:
    """Invoke the gate exactly as step 3's `program_exit_zero` clause does:
    cwd = project dir, positional `.`, and `--json <path>` so the report goes
    to a FILE and stdout is left free."""
    return subprocess.run(
        [sys.executable, str(PROGRAMS / f"{gate}.py"), ".", "--json", json_rel],
        cwd=root, capture_output=True, text=True,
    )


def _emitted_vacuous_sentinel(proc: subprocess.CompletedProcess) -> bool:
    """The repo's convention: a line beginning `VACUOUS_PASS`, on either
    stream. `flow_compliance_check.output_snippet` concatenates stdout and
    stderr before reading, so the gate may use either."""
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return any(line.lstrip().startswith("VACUOUS_PASS")
               for line in blob.splitlines())


@pytest.mark.parametrize("gate,json_rel", GATES)
def test_empty_tree_is_disclosed_not_silently_passed(gate, json_rel, tmp_path):
    """THE REGRESSION. Zero files scanned => VACUOUS_PASS, never a bare PASS."""
    proc = _run(gate, json_rel, tmp_path)

    # The exit code is deliberately unchanged — see module docstring.
    assert proc.returncode == 0, (
        f"{gate} should still exit 0 on a project with no RTL yet; "
        f"got rc={proc.returncode}"
    )

    # (a) It must not be SILENT. This is the byte-count the finding measured.
    blob = (proc.stdout or "") + (proc.stderr or "")
    assert blob.strip(), (
        f"{gate} produced ZERO bytes of output on an empty tree — a gate that "
        f"says nothing is scored a plain PASS and stays in the published "
        f"executed-PASS numerator"
    )

    # (b) It must disclose using the EXISTING convention, not new prose.
    assert _emitted_vacuous_sentinel(proc), (
        f"{gate} produced output but no line-start `VACUOUS_PASS` sentinel; "
        f"the flow's `_stdout_signals_vacuous` reads that token and nothing "
        f"else, so undisclosed prose is still scored a plain PASS.\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )

    # (c) The written report must agree with what was printed.
    report = json.loads((tmp_path / json_rel).read_text())
    assert report["summary"]["files_scanned"] == 0
    assert report.get("verdict") == "VACUOUS_PASS", (
        f"{gate} report records files_scanned=0 beside passed="
        f"{report.get('passed')!r} with verdict={report.get('verdict')!r} — "
        f"the JSON must not certify a scan that never happened"
    )


@pytest.mark.parametrize("gate,json_rel", GATES)
def test_real_rtl_is_still_a_plain_pass(gate, json_rel, tmp_path):
    """The disclosure must NOT over-fire. A gate that cried vacuous on every
    run would be exactly as uninformative as one that never did."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(CLEAN_RTL)

    proc = _run(gate, json_rel, tmp_path)
    assert proc.returncode == 0
    assert not _emitted_vacuous_sentinel(proc), (
        f"{gate} disclosed VACUOUS_PASS on a tree that HAS authoritative RTL"
    )

    report = json.loads((tmp_path / json_rel).read_text())
    assert report["summary"]["files_scanned"] >= 1
    assert report.get("verdict") == "PASS"


@pytest.mark.parametrize("gate,json_rel", GATES)
def test_flow_consumer_promotes_the_step_out_of_plain_pass(
        gate, json_rel, tmp_path):
    """END-TO-END. The sentinel is worth nothing if the consumer never reads
    it — that is the defect class under review. Ask the real reader, on the
    real snippet shape, whether the step leaves the executed-PASS numerator."""
    sys.path.insert(0, str(PROGRAMS))
    import flow_compliance_check as F  # noqa: E402

    proc = _run(gate, json_rel, tmp_path)
    snippet = F.output_snippet(proc.stdout, proc.stderr)
    assert F._stdout_signals_vacuous(snippet), (
        f"{gate} exited 0 on an empty tree and "
        f"flow_compliance_check._stdout_signals_vacuous() did NOT see a "
        f"disclosure, so the step is counted as an executed PASS"
    )
