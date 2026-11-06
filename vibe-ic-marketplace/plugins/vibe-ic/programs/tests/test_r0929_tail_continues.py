"""Legacy diagnostic tail: measure a failed route without admitting release.

The single-project Default path now stops at the failed canonical row.
These controls retain the existing Ultra diagnostic tail's assertions;
test_default_pnr_row_boundaries exercises the Default stopping path.

MEASURED (IC_BLOCKER_AUDIT 2026-09-29, spm #2; subservient IC run
`subic_ic_20260928` on 8hd-3, read-only): `_chain_ok` in `main()` was
`row.status == "PASS"` for every Step-32 producer, and a pre-stream gate FAIL
set it False. On subservient the pre-stream gate measured FAIL (sta_signoff,
sta_corner, sta_record, em_authority, antenna), and then gds, drc, lvs and
canonicalize_artefacts all read NOT_MEASURED "sign-off skipped: pre-stream gate
failed". On spm a measured Step-32 DRV FAIL did the same. So no run has measured
the tail (GDS, DRC, LVS, fill, precheck, handoff), and the tail's own blockers
stay hidden. The flow also declared 32 `blocks_on [23..30]`, the reverse of the
runner's order, so the audit could never attribute a gap to 32.

The rule now:
  * a measured FAIL at Step 32 or at the pre-stream gate is RECORDED and keeps
    the run FAIL (rc != 0);
  * stream-out and the tail still run on the shipped route;
  * only a missing/unusable route stops them, NOT_MEASURED naming the upstream;
  * a stream after a non-PASS pre-stream gate is measurement-only: never
    admitted, never packaged, and its release receipt is not eligible.

chip-, PDK- and vendor-AGNOSTIC: synthetic fixtures; only EDA writes are faked.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import phase3_one_shot_runner as R

FLOW = Path(R.__file__).resolve().parent.parent / "flow" / "phase1_phase2_phase3.yaml"


@pytest.fixture(autouse=True)
def diagnostic_transport_mode(monkeypatch):
    """Exercise legacy native transport; candidate scheduling is out of scope."""
    import execution_policy
    original = execution_policy.request
    monkeypatch.setattr(execution_policy, 'request',
                        lambda: dict(original(), mode='ultra'))
    monkeypatch.setattr(execution_policy, 'bootstrap', lambda *a, **k: None)
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    monkeypatch.setattr(R, '_default_step15_with_backend_receipt',
                        lambda *a, **k: R.step_pnr(*a, **k))




# ── Step 32 ───────────────────────────────────────────────────────────────





# ── the pre-stream gate ───────────────────────────────────────────────────















# ── the admission predicate ───────────────────────────────────────────────

def _gate_record(project: Path, **doc) -> None:
    out = R._pl.reports_phase3_dir(project) / "prestream_gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc))


@pytest.mark.parametrize("doc, digest, streams", [
    ({"verdict": "PASS", "layout_digest": "a"}, "a", True),
    ({"verdict": "FAIL", "layout_digest": "a", "gates": [{"name": "x"}],
      "unmeasured_gates": ["si"]}, "a", True),
    ({"verdict": "NOT_MEASURED", "layout_digest": "a", "gates": [{"name": "x"}],
      "unmeasured_gates": ["si_mcf"]}, "a", True),
    # the receipt must bind THIS layout
    ({"verdict": "FAIL", "layout_digest": "b", "gates": [{"name": "x"}]}, "a", False),
    ({"verdict": "PASS", "layout_digest": "a"}, "", False),
    # a stub receipt measured nothing
    ({"verdict": "FAIL", "layout_digest": "a"}, "a", False),
    ({"verdict": "FAIL", "layout_digest": "a", "gates": []}, "a", False),
    # the route itself absent / unidentified
    ({"verdict": "NOT_MEASURED", "layout_digest": "a", "gates": [{"name": "x"}],
      "unmeasured_gates": ["layout_basis"]}, "a", False),
    ({"verdict": "NOT_MEASURED", "layout_digest": "a", "gates": [{"name": "x"}],
      "unmeasured_gates": ["route_evidence"]}, "a", False),
    # an owner-WAIVED gate is never PASS: it streams for measurement
    # (review wave 58), and `gate_passed` still refuses to admit it
    ({"verdict": "WAIVED", "layout_digest": "a", "gates": [{"name": "x"}]}, "a", True),
    ({"verdict": "PASS_WITH_WAIVERS", "layout_digest": "a",
      "gates": [{"name": "x"}]}, "a", False),
])
def test_stream_refusal(tmp_path, doc, digest, streams):
    _gate_record(tmp_path, **doc)
    assert (R._ga.stream_refusal(tmp_path, digest) == "") is streams


# ── the declared order matches the runner's data flow ─────────────────────

def _ancestors(sid, bo):
    out, stack = set(), [sid]
    while stack:
        for p in bo.get(stack.pop(), []):
            if p not in out:
                out.add(p)
                stack.append(p)
    return out


def test_signoff_steps_are_downstream_of_step32():
    """RED on main: 32 blocks_on [23, 24, 25, 26, 27, 29, 30]."""
    doc = yaml.safe_load(FLOW.read_text())
    bo = {str(s["id"]): [str(p) for p in (s.get("blocks_on") or [])]
          for s in doc["steps"] if isinstance(s, dict) and "id" in s}
    for sid in ("23", "24", "25", "26", "27", "28", "29", "30"):
        assert "32" in _ancestors(sid, bo), f"step {sid} is not downstream of 32"
        assert sid not in _ancestors("32", bo), f"32 still waits on {sid}"
    # Repair the routed checkpoint first, then extract its final parasitics.
    # The provisional repair estimate is not the final Step-22 product.
    assert "21" in _ancestors("32", bo)
    assert "32" in _ancestors("22", bo)
    assert "22" not in _ancestors("32", bo)


# ── review wave 58: the tape-out tail keeps sign-off 23-30 as ancestors ───

#: The tail as the flow declares it: 34 (fill, where stream-out enters) and
#: everything downstream of it. Measured with the audit's own
#: `flow_step_execution_coverage_check.analyze` on main 9dc7bb35e (before the
#: flip): a step-23 FAIL voided exactly these, plus 30/31/33/36 and 32.
_TAIL = ("34", "35", "37", "37.3", "37.4", "37.5ic", "37.5ip", "38", "39",
         "40", "41", "42", "43", "44", "M1", "M2", "M3", "M4")
_SIGNOFF = ("23", "24", "25", "26", "27", "29", "30")


def _graph_and_doc():
    import flow_step_execution_coverage_check as C
    graph, prov = C.load_blocks_on(FLOW)
    return C, graph, prov, yaml.safe_load(FLOW.read_text())


def test_every_tail_step_keeps_signoff_23_30_among_its_ancestors():
    """RED before the 34 edge: the flip had removed the only path."""
    doc = yaml.safe_load(FLOW.read_text())
    bo = {str(s["id"]): [str(p) for p in (s.get("blocks_on") or [])]
          for s in doc["steps"] if isinstance(s, dict) and "id" in s}
    for sid in _TAIL:
        assert sid in bo, f"tail step {sid} vanished from the flow"
        missing = [s for s in _SIGNOFF if s not in _ancestors(sid, bo)]
        assert not missing, f"tail step {sid} lost sign-off ancestors {missing}"


@pytest.mark.parametrize("bad", _SIGNOFF)
def test_a_signoff_fail_voids_the_whole_tail(bad):
    """The VOID cascade, through the audit's own call: every tail PASS resting
    on a FAILED sign-off step is out of order."""
    C, graph, prov, doc = _graph_and_doc()
    steps = [{"id": s["id"], "name": s.get("name", ""),
              "status": "FAIL" if str(s["id"]) == bad else "PASS"}
             for s in doc["steps"]]
    rep = C.analyze({"steps": steps}, graph, prov)
    voided = {str(v["terminal_id"]) for v in rep["ordering_violations"]
              if str(v["signoff_id"]) == bad}
    assert set(_TAIL) <= voided, sorted(set(_TAIL) - voided)
    assert "32" not in voided        # the flip: 32 now runs BEFORE sign-off


def test_a_missing_tail_output_behind_a_step23_fail_is_not_owed():
    """The not-owed cascade: with 23 FAIL and the GDS / handoff absent, 37 and
    38 read blocked-by-upstream(23) -- never an owed root of their own."""
    import flow_compliance_check as FCC
    doc = yaml.safe_load(FLOW.read_text())
    rows = []
    for s in doc["steps"]:
        sid = str(s["id"])
        status, rc = "PASS", ""
        if sid == "23":
            status = "FAIL"
        elif sid in ("37", "38"):
            status, rc = "FAIL", "missing_artefact"
        rows.append(FCC.StepResult(id=s["id"], name=s.get("name", ""),
                                   stage=s.get("stage", ""), status=status,
                                   reason_class=rc))
    FCC._demote_not_owed_rows(rows, rows, doc["steps"])
    by = {str(r.id): r for r in rows}
    for sid in ("37", "38"):
        assert by[sid].status == "NOT_MEASURED", (sid, by[sid].status)
        assert by[sid].cascade_note == "blocked-by-upstream(23)", \
            (sid, by[sid].cascade_note)
