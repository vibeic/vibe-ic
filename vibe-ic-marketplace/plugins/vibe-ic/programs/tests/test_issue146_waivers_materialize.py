"""#146 blocker-1 — materialize the machinery-sanctioned in-memory
ENV_UNAVAILABLE auto-waivers into waivers.json (no self-approval hole).

The materializer writes ONLY the flow's sanctioned synth waivers (pdk-substitution
/ fpga-board cap-gap), field-identical to what the audit applies in-memory, so the
strict audit's required-artifact slot is a real, schema-valid, review-required
file. No-leak: no sanctioned tier → no file; a human file is never touched; a
self-approver is rejected by waivers_schema_check.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))
import waivers_materialize as WM  # noqa: E402
import flow_compliance_check as fcc  # noqa: E402
import waivers_schema_check as WS  # noqa: E402


def _mk_fpga_skip(tmp: Path) -> Path:
    d = tmp / "proj"
    (d / "reports" / "phase2" / "fpga").mkdir(parents=True)
    (d / "reports" / "phase2" / "fpga" / "quartus_map_audit.json").write_text(
        json.dumps({"verdict": "SKIP", "sof_present": False}))
    return d


def test_materializes_sanctioned_fpga_skip(tmp_path):
    p = _mk_fpga_skip(tmp_path)
    n, ids = WM.materialize(p)
    assert n >= 1
    assert (p / "waivers.json").exists()
    data = json.loads((p / "waivers.json").read_text())
    entries = data["waived_steps"]
    assert entries and all(e["auto_synthesized"] is True for e in entries)
    assert all(e["review_required"] is True for e in entries)
    # sanctioned tier approver, never a self-approver
    assert all("field-agent-attest" in e["approver"] for e in entries)


def test_materialized_file_passes_schema(tmp_path):
    p = _mk_fpga_skip(tmp_path)
    WM.materialize(p)
    findings, _ = WS.validate(p)
    assert [f for f in findings if f.severity == "error"] == []


def test_materialization_preserves_inmemory_coverage(tmp_path):
    # behavioral equivalence: the step-keyed waivers _load_waivers derives FROM
    # THE FILE must match the in-memory synth coverage (materializing changes
    # nothing except that the deferral is now an auditable file).
    p = _mk_fpga_skip(tmp_path)
    in_memory = WM.sanctioned_auto_waivers(p)
    WM.materialize(p)
    from_file = fcc._load_waivers(p)
    assert sorted(str(k) for k in from_file) == sorted(str(k) for k in in_memory)
    assert all(from_file[k].get("_env_unavailable") for k in from_file)


# ── §4.05 no-leak ──────────────────────────────────────────────────────────
def test_no_sanctioned_tier_writes_nothing(tmp_path):
    d = tmp_path / "proj"
    (d / "reports").mkdir(parents=True)
    n, _ = WM.materialize(d)
    assert n == 0 and not (d / "waivers.json").exists()   # honest MISSING


def test_never_clobbers_human_waivers(tmp_path):
    p = _mk_fpga_skip(tmp_path)
    human = {"waived_steps": [{
        "id": 6, "reason": "human decided to defer this board step deliberately",
        "approver": "alice", "review_required": True, "ticket": "JIRA-1"}]}
    (p / "waivers.json").write_text(json.dumps(human))
    n, _ = WM.materialize(p)
    assert n == 0
    assert json.loads((p / "waivers.json").read_text()) == human   # untouched


def test_self_approver_rejected_by_schema(tmp_path):
    # defense: even in an auto file, a self-approver must be caught by the schema
    p = _mk_fpga_skip(tmp_path)
    WM.materialize(p)
    data = json.loads((p / "waivers.json").read_text())
    data["waived_steps"][0]["approver"] = "agent"
    (p / "waivers.json").write_text(json.dumps(data))
    findings, _ = WS.validate(p)
    assert any(f.severity == "error" for f in findings)


def test_merges_into_existing_auto_file_without_dup(tmp_path):
    # an auto file (all-auto entries) is merged into, never duplicated
    p = _mk_fpga_skip(tmp_path)
    WM.materialize(p)
    first = json.loads((p / "waivers.json").read_text())["waived_steps"]
    n2, _ = WM.materialize(p)          # re-run
    second = json.loads((p / "waivers.json").read_text())["waived_steps"]
    assert n2 == 0 and len(second) == len(first)   # idempotent, no dup
