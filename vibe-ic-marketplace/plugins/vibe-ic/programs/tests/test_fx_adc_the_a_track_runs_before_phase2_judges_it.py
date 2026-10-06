#!/usr/bin/env python3
"""FX_ADC_PHASE_ORDER (3) — the analog A-track is dispatched BEFORE phase 2,
because phase 2 judges it.

MEASURED on u_hawaii_adc (IC_STATUS_0928, front door on 7fac744e1). Phase 2's
final audit (`flow_compliance_check --phase 2`) judges A1..A9, which the flow
yaml declares `phase_scope: agnostic` (R-0915-158: in BOTH phase scopes, pinned
by test_r0915_158_phase_scope_is_declared_not_guessed). The front door
dispatched the A-track only AFTER phase 2, so the audit found nothing:

    ✗ [FAIL] Step A1: Analog Spec Extraction (stage_analog) (missing_artefact)
    … A2..A9 NOT_MEASURED (upstream_failed, A1)

and that FAIL made phase 2 -- and the whole run -- red regardless of what the
A-track then did. The A-track reads only phase-1 artefacts; A1 `blocks_on: [D1]`.
So the producer runs before its judge, and its plan ROW is still reported after
phase 2, so the run's reported phase order does not change.

Driven through the real `main()`; only the phase runners are stubbed (argv and
order recorded, a report written per phase). chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from programs.tests.test_execution_receipt_chain import real_entry, isolated_transport  # noqa: F401

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import vibe_ic_one_shot_runner as orch  # noqa: E402
import _owner_declared as OD  # noqa: E402
import _submission_template as ST  # noqa: E402


def _drive(tmp_path: Path, monkeypatch, *, need_analog: bool,
           verdicts: dict) -> dict:
    project = tmp_path / "proj"
    project.mkdir()
    answers = project / ST.DESIGN_ANSWERS_REL
    answers.parent.mkdir(parents=True)
    answers.write_text(json.dumps(OD.attest({"answers": {"deliverable": "DIE"}})))
    if need_analog:
        declaration = project / 'phase1/analog/analog_block_list.json'
        declaration.parent.mkdir(parents=True)
        declaration.write_text(json.dumps({'blocks': [{'name': 'neutral_analog'}]}))
    real_entry('IC', 'default', project)
    cap = {"order": []}

    def fake_run_phase(label, runner, args, env=None):
        cap["order"].append(Path(runner).name)
        stem = Path(runner).name.split("_")[0]
        return 0 if verdicts.get(stem, "PASS") != "FAIL" else 1

    def fake_read_report(_p):
        if not cap["order"]:
            return {"verdict": "PASS"}
        stem = cap["order"][-1].split("_")[0]
        return {"verdict": verdicts.get(stem, "PASS")}

    monkeypatch.setattr(orch, "_run_phase", fake_run_phase)
    monkeypatch.setattr(orch, "_read_report", fake_read_report)
    monkeypatch.setattr(orch, "_need_analog",
                        lambda _p, force_skip: False if force_skip
                        else need_analog)
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner.py",
                                      str(project), "--skip-phase1",
                                      "--skip-phase3", "--no-dashboard"])
    orch.main()
    doc = project / "reports" / "orchestrator" / "vibe_ic_one_shot.json"
    cap["doc"] = json.loads(doc.read_text()) if doc.is_file() else {}
    return cap


def _index(order, prefix):
    hits = [i for i, n in enumerate(order) if n.startswith(prefix)]
    return hits[0] if hits else None


def test_the_a_track_is_dispatched_before_phase2_judges_it(tmp_path,
                                                           monkeypatch):
    cap = _drive(tmp_path, monkeypatch, need_analog=True, verdicts={})
    a, p2 = _index(cap["order"], "analog_"), _index(cap["order"], "phase2")
    assert a is not None and p2 is not None, cap["order"]
    assert a < p2, (
        "the A-track ran after phase 2, whose final audit and Step-4 "
        f"acceptance judge its artefacts: {cap['order']}")


def test_it_still_runs_when_phase2_fails(tmp_path, monkeypatch):
    """GAP-ANALOG-1 is unchanged: a digital phase-2 FAIL never cancels the
    A-track (it has already run)."""
    cap = _drive(tmp_path, monkeypatch, need_analog=True,
                 verdicts={"phase2": "FAIL"})
    assert _index(cap["order"], "analog_") is not None, cap["order"]


def test_a_pure_digital_design_still_runs_no_a_track(tmp_path, monkeypatch):
    cap = _drive(tmp_path, monkeypatch, need_analog=False, verdicts={})
    assert _index(cap["order"], "analog_") is None, cap["order"]


@pytest.mark.parametrize("phase2", ["PASS", "FAIL"])
def test_the_reported_phase_order_is_unchanged(tmp_path, monkeypatch, phase2):
    """The dispatch moved; the record did not: phase2's row precedes analog's."""
    cap = _drive(tmp_path, monkeypatch, need_analog=True,
                 verdicts={"phase2": phase2})
    rows = [r.get("phase") or r.get("name")
            for r in cap["doc"].get("phases") or cap["doc"].get("plan") or []
            if isinstance(r, dict)]
    if not rows:
        pytest.fail(f"no phase rows in the front-door record: "
                    f"{sorted(cap['doc'])}")
    assert rows.index("phase2") < rows.index("analog"), rows
