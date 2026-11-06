"""A gate whose subject only an MCP run produces is N/A on a program-only run.

MEASURED 2026-09-15 (lane icspm3, R-0915-15) on `spm` x gf180mcuD.
`fpga_program_chain_attest_check` audits the mcp-eda execution manifest and
answered::

    error: manifest not found: <project>/latest_results.jsonl

which P0 booked `EXECUTION_ERROR` — a fault the design did not commit and this
flow cannot fix, because **nothing in this flow writes that file**. Step 31
already declares the SAME artefact N/A for the SAME reason, in the flow yaml::

    condition_files_exist: ["latest_results.jsonl"]
    … "Scoped to a run that drove the MCP-EDA server: the manifest is written
    by the MCP tools themselves and by nothing in this flow, so a program-only
    run has no execution record to read and this gate would be reporting on an
    absence rather than judging one."

P0's equivalent channel is `_P0_GATE_REQUIRED_CONTEXT`, so the question is
asked there in the same terms.

BOTH DIRECTIONS: no manifest → SKIP with `reason_class=DESIGN_DECLARED_NA`; a
manifest present → the gate stays live and blocking, exactly as before.

AND THE EARLY RETURN THAT MADE THE ROSTER UNREACHABLE. `_p0_contract_na_reason`
returned `None` for any gate with no declared argv contract — i.e. for most of
the umbrella — so a gate-keyed requirement could never fire on one. The
requirement map is keyed by GATE because its question is about the gate's
subject, not its CLI shape; a gate with NEITHER a contract nor a requirement is
unchanged and still runs fail-closed.

chip-AGNOSTIC: the manifest path is derived from the project root.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

import _flow_reason_taxonomy as R  # noqa: E402

GATE = "fpga_program_chain_attest_check"


def _proj(tmp_path, manifest: bool):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text("module top(); endmodule\n")
    if manifest:
        (tmp_path / "latest_results.jsonl").write_text(
            '{"step":"fpga_compile","status":"PASS","session_id":"s1"}\n')
    return tmp_path, rtl


# ── direction 1: no manifest → declared N/A, not a fault ──────────────────


def test_that_disposition_is_skip_eligible():
    """The consequence: a SKIP booked DESIGN_DECLARED_NA lets P0 reach PASS,
    which an EXECUTION_ERROR never can."""
    assert R.DESIGN_DECLARED_NA in R.SKIP_ELIGIBLE
    assert R.record_verdict(R.DESIGN_DECLARED_NA) == "SKIP"


# ── direction 2: a run that DID drive the MCP server keeps the gate ───────


# ── the early return that made the roster unreachable ─────────────────────
