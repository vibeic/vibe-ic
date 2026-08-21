#!/usr/bin/env python3
"""ORGANIC #306 STRUCTURAL — a gate that FAILs but cannot block differs from no
gate at all only in that the failure is searchable later.

Field evidence: `cts_quality_check` exists, is wired into the flow definition,
has tests, and FAILed correctly on the SAME cell across three consecutive
plugin versions. The flow ran to completion every time (post_cts.def 44 MB,
routed.def 181 MB). It is the one gate that could have caught #300 at source.
It caught it three times and stopped nothing. Eleven gates FAILed in that run.

Root cause this program measures: the step runners invoke the flow's
`program_exit_zero` gates almost nowhere. They are evaluated by
`flow_compliance_check`, which the runner runs as `final_audit` — the LAST
step, after every artefact is already written.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import flow_gate_enforcement_audit as A  # noqa: E402

_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"


def test_306_audit_runs_on_the_real_flow_definition():
    """Non-vacuous: the real flow really does declare many gates."""
    rep = A.audit(_FLOW, _PROGRAMS)
    assert rep["total_gates"] > 50, rep["total_gates"]


def test_306_the_enforcement_gap_is_real_and_measured():
    """The finding itself, pinned: most gates cannot block. If someone later
    wires them up, this test tells them the number moved — it is a measurement,
    not a target."""
    rep = A.audit(_FLOW, _PROGRAMS)
    assert rep["enforced"] + rep["audit_only"] == rep["total_gates"]
    assert rep["audit_only"] > rep["enforced"], (
        "expected the measured gap; if this now fails, enforcement improved — "
        "update the recorded figure deliberately")


def test_306_cts_quality_check_is_the_documented_case():
    """The gate from the issue must be present and NOT enforced — that pairing
    is the whole defect."""
    rep = A.audit(_FLOW, _PROGRAMS)
    row = next((r for r in rep["gates"] if r["gate"].startswith("cts_quality")),
               None)
    assert row is not None, "cts_quality_check vanished from the flow definition"
    assert row["enforcement"] == "AUDIT_ONLY"


def test_306_declared_blocking_but_audit_only_is_a_contradiction(tmp_path):
    """A gate whose docstring says `ENFORCEMENT: blocking` while the wiring is
    audit-only must be reported, not silently tolerated."""
    (tmp_path / "faux_check.py").write_text(
        '"""x\n\nENFORCEMENT: blocking\n"""\n')
    flow = tmp_path / "flow.yaml"
    flow.write_text("      - program_exit_zero: \"faux_check . --json x.json\"\n")
    rep = A.audit(flow, tmp_path)
    assert [c["gate"] for c in rep["contradictions"]] == ["faux_check"]


def test_306_orphaned_gate_is_worse_than_audit_only(tmp_path):
    """A gate program that declares an intent but is absent from the flow
    definition is not reached even by the final audit. Two gates added earlier
    in this campaign were in exactly that state."""
    (tmp_path / "lonely_check.py").write_text(
        '"""x\n\nENFORCEMENT: blocking\n"""\n')
    flow = tmp_path / "flow.yaml"
    flow.write_text("      - program_exit_zero: \"other_check . --json x\"\n")
    rep = A.audit(flow, tmp_path)
    assert [o["gate"] for o in rep["orphaned"]] == ["lonely_check"]


def test_306_a_mention_in_a_comment_is_not_enforcement(tmp_path):
    """`cts_quality_check` appears in a runner COMMENT. That must not count as
    the runner invoking it — the false positive would hide the whole defect."""
    src = "# see cts_quality_check for why this marker exists\n"
    assert A._invoked(src, "cts_quality_check") is False
    assert A._invoked('_run(["python3", "cts_quality_check.py", p])', 
                      "cts_quality_check") is True


def test_306_undeclared_is_reported_not_assumed():
    """72 gates with no declared intent is how they became de-facto advisory
    without anyone deciding that. The audit must surface it as UNKNOWN."""
    rep = A.audit(_FLOW, _PROGRAMS)
    assert rep["undeclared"] > 0
    assert rep["declared"] + rep["undeclared"] == rep["total_gates"]
