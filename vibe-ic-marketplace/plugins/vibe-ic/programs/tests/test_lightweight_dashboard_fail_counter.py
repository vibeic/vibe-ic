"""A mode that cannot compute a verdict must not print one.

`flow_dashboard_data._lightweight_status` classifies a step purely by output-file
presence; it has no branch that can return "fail" or "missing". The summary line
nevertheless rendered "fail 0" — a verdict the mode never computed — directly
beneath an `overall verdict: FAIL` printed by the runner, so a reader of the step
map saw a FAIL that pointed at nothing.

These tests pin the OBSERVABLE behaviour (the collected dict and the rendered
frame). They never grep the source, so they stay honest if the implementation is
rewritten. Everything here is chip-AGNOSTIC: generic step names, no design,
vendor, IC or PDK identifiers.
"""
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import flow_dashboard_data as fdd  # noqa: E402


def _project(tmp_path: Path, steps) -> Path:
    """A minimal project carrying only the orchestrator report."""
    odir = tmp_path / "reports" / "orchestrator"
    odir.mkdir(parents=True)
    (odir / "phase_alpha_one_shot.json").write_text(
        json.dumps({"verdict": "FAIL", "steps": steps}), encoding="utf-8"
    )
    return tmp_path


# The shape that motivated this: a step whose remediation tier is distinct from
# a plain FAIL, plus a byte-identical-artifact inert loop. Names are generic.
_STEPS = [
    {"name": "alpha_stage", "status": "PASS", "detail": "ok"},
    {"name": "beta_stage", "status": "FAIL", "detail": "tool rc=1"},
    {"name": "gamma_loop", "status": "FAIL_RTL_REPAIR_INERT",
     "detail": "iteration produced byte-identical output (sha256=deadbeefcafe0001)"},
]


def test_lightweight_declares_fail_and_missing_inexpressible(tmp_path):
    data = fdd.collect(_project(tmp_path, _STEPS))
    assert data["mode"] == "lightweight"
    assert set(data["summary_unavailable"]) == {"fail", "missing"}






def test_no_join_is_invented_onto_step_rows(tmp_path):
    """A runner step name must never be attached to a flow step row.

    The two vocabularies have no mapping; painting one onto the other sends the
    reader somewhere specific and wrong.
    """
    data = fdd.collect(_project(tmp_path, _STEPS))
    for phase in data["phases"]:
        for st in phase["steps"]:
            assert st["status"] != "fail"
            blob = json.dumps(st)
            assert "beta_stage" not in blob
            assert "gamma_loop" not in blob




def test_absent_or_corrupt_orchestrator_report_is_tolerated(tmp_path):
    """Never raise on a partial tree — the dashboard is a read-only observer."""
    (tmp_path / "reports" / "orchestrator").mkdir(parents=True)
    (tmp_path / "reports" / "orchestrator" / "truncated.json").write_text(
        '{"steps": [', encoding="utf-8"
    )
    data = fdd.collect(tmp_path)
    assert data["orchestrator_failures"] == []

    bare = tmp_path / "bare"
    bare.mkdir()
    assert fdd.collect(bare)["orchestrator_failures"] == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
