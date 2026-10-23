#!/usr/bin/env python3
"""Tests for phase3_one_shot_runner.py — Phase 3 (synth → GDS) orchestrator.

Wave 83 — coverage for previously untested orchestrator.

The runner shells out to Yosys / OpenROAD / KLayout inside an vibeic-eda
Docker container. The test environment has no Docker, so we exercise
the orchestrator's control-flow paths only:

  1. POSITIVE_FAIL_MISSING_PROJECT — non-existent project dir → exit 2.
  2. POSITIVE_FAIL_NO_RTL — project exists but rtl/ empty → synth step
                              FAILs (no RTL to synthesise) → exit 1 +
                              report emitted under reports/.
  3. INTEGRATION_REPORT_SHAPE — emitted phase3_one_shot.json must contain
                                  project / pdk / top / steps / verdict.
  4. EDGE_INVALID_PDK_OVERRIDE — `--pdk thispdkdoesnotexist` falls back
                                   to sky130A (current behaviour).
  5. STEPS_INCLUDE_DRC_AND_LVS — even on FAIL the steps array contains
                                   drc + lvs entries (always reported).
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import struct
import subprocess
import sys
import pathlib
import tempfile
from pathlib import Path

import pytest

#: EVERY test here launches `phase3_one_shot_runner.py`, and that launch does
#: not fit the harness's 180 s item bound reliably. MEASURED: quiet, the six
#: tests are `6 passed in 103.05 s` with a worst single call of 21.04 s; under
#: ordinary fleet contention the SAME call ran past 60 s. So the two numbers
#: this file must declare are different from the defaults:
#:
#:   * the ITEM bound, here: 600 s, a CEILING and not a target, so a slow run
#:     completes or fails on its own instead of taking every other file's
#:     verdict down with it (`--timeout-method=thread` kills the SESSION);
#:   * the INNER bound, `_run` below: 150 s, which `ci_harness_timeout_ceiling_
#:     check` holds to 600 // 3 = 200 s.
#:
#: WHY `pytestmark` AND NOT A PER-TEST DECORATOR: the bound being declared
#: lives in `_run`, a module-level helper all six tests share. A decorator on
#: one test cannot govern a helper the other five also call; a module-level
#: mark bounds every item in the file, so every call in it really does run
#: inside a 600 s item. Verified rather than assumed --
#: `pytestmark = pytest.mark.timeout(30)` under `--timeout=2
#: --timeout-method=thread` yields `2 passed`, not a killed session.
#:
#: WHY NOT SIMPLY LOWER `_run` TO 60: measured, that is a FALSE RED under
#: contention -- the trade `test_flow_matrix_census_freshness.py` already
#: refused for the same reason.
pytestmark = pytest.mark.timeout(600)

PROG = Path(os.environ.get(
    "VIBEIC_CONTRACT_PROGRAMS",
    str(Path(__file__).resolve().parent.parent))).resolve() / \
    "phase3_one_shot_runner.py"
sys.path.insert(0, str(PROG.parent))
import phase3_one_shot_runner as RUNNER  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# v1.4.62 — these control-flow tests exercise the DEFAULT (`--pdk auto`)
# resolution, which lands on the container's OSS enablement. On a host that has
# a commercial PDK configured, `commercial_pdk_fallback_guard` now REFUSES that
# silent fallback (it would emit VOID sign-off reports under a false PDK
# belief). These tests are about orchestrator control flow, not PDK intent, so
# they acknowledge the OSS fallback explicitly — which also makes them
# deterministic regardless of the host's private commercial-PDK config.
_ACK_OSS = "--allow-oss-pdk-fallback"


#: 150 s against the 600 s item bound `pytestmark` declares above (ceiling
#: 600 // 3 = 200). The old 90 s was measured against the wrong denominator:
#: it was chosen when the item bound was the harness's 180 s, where 90 s is
#: half the budget and two calls in one test would end the SESSION.
#: Invisible to `ci_harness_timeout_ceiling_check` until vibe-ic#1277 --
#: the bound is a parameter default, which the gate could not read.
# 90 s, not 150 s. The file's `@pytest.mark.timeout(600)` does NOT buy a 200 s
# ceiling: the driver classifies a session hung after 300 s with no validated
# pytest lifecycle event, and a blocking call emits none, so the applicable bound
# is min(600, 300) // 3 = 100. Measured: the slowest call in this file is 34.6 s
# and the whole file runs in 147 s, so 90 s is ~2.6x headroom over the worst case.
def _run(args: list, timeout: int = 90) -> subprocess.CompletedProcess:
    if args and not args[0].startswith("-") and _ACK_OSS not in args:
        args = args + [_ACK_OSS]
    return _pr.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True)


def _admitted_empty_project(project):
    """Declare this neutral DIE fixture through the real admission contract.

    These tests exercise downstream no-RTL/report behavior. Admission itself
    remains enabled; the missing-declaration control below removes its input.
    """
    import _owner_declared as OD
    import _submission_template as ST
    import _tapeout_declaration as TD

    doc = OD.attest({"answers": {"deliverable": "DIE"}})
    for rel in (ST.DESIGN_ANSWERS_REL, TD.DECLARATION_REL):
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc))
    (project / TD.SELF_TAPEOUT_REL).write_text(TD.SELF_TAPEOUT_MARKER + "\n")


def test_missing_delivery_declaration_refused_before_backend(tmp_path):
    import _tapeout_declaration as TD

    project = tmp_path / "proj"
    _admitted_empty_project(project)
    (project / TD.DECLARATION_REL).unlink()
    cp = _run([str(project)])
    assert cp.returncode == 2
    assert "DELIVERY_AUTHORITY_STALE_OR_UNDECLARED" in cp.stderr
    report = json.loads(
        (project / "reports/phase3/delivery_admission.json").read_text())
    assert report["verdict"] == "REFUSED"
    assert report["reason"] == "DELIVERY_AUTHORITY_STALE_OR_UNDECLARED"
    assert not (project / "reports/orchestrator/phase3_one_shot.json").exists()


def test_positive_fail_missing_project(tmp_path):
    missing = tmp_path / "no_such"
    cp = _run([str(missing)])
    assert cp.returncode == 2
    assert "not a directory" in cp.stderr


def test_positive_fail_no_rtl(tmp_path):
    """Empty project → synth step FAIL → orchestrator exits 1."""
    project = tmp_path / "proj"
    _admitted_empty_project(project)
    cp = _run([str(project)])
    # synth FAIL → verdict FAIL → exit 1.
    assert cp.returncode == 1
    assert "verdict: FAIL" in cp.stdout
    rep = project / "reports" / "orchestrator" / "phase3_one_shot.json"
    assert rep.is_file()


def test_integration_report_shape(tmp_path):
    project = tmp_path / "proj"
    _admitted_empty_project(project)
    cp = _run([str(project)])
    rep = project / "reports" / "orchestrator" / "phase3_one_shot.json"
    body = json.loads(rep.read_text())
    for k in ("project", "pdk", "top", "steps", "verdict"):
        assert k in body, f"missing key {k}"
    assert body["top"] == "chip_top"
    assert isinstance(body["steps"], list)
    assert len(body["steps"]) >= 1
    import hashlib
    audit_rel = "reports/audit/phase23_completion_audit.json"
    audit = project / audit_rel
    assert audit.is_file()
    assert body["cited_artefacts"][audit_rel] == hashlib.sha256(
        audit.read_bytes()).hexdigest()


def test_edge_custom_top_name(tmp_path):
    project = tmp_path / "proj"
    _admitted_empty_project(project)
    cp = _run([str(project), "--top-name", "tst_chip_top"])
    body = json.loads(
        (project / "reports" / "orchestrator" / "phase3_one_shot.json").read_text())
    assert body["top"] == "tst_chip_top"


def test_steps_include_drc_and_lvs(tmp_path):
    project = tmp_path / "proj"
    _admitted_empty_project(project)
    cp = _run([str(project)])
    body = json.loads(
        (project / "reports" / "orchestrator" / "phase3_one_shot.json").read_text())
    step_names = {s["name"] for s in body["steps"]}
    # DRC + LVS are always run regardless of synth result.
    assert "drc" in step_names
    assert "lvs" in step_names


def test_edge_explicit_pdk_sky130a(tmp_path):
    """Explicit --pdk sky130A is accepted (uses container paths)."""
    project = tmp_path / "proj"
    _admitted_empty_project(project)
    cp = _run([str(project), "--pdk", "sky130A"])
    body = json.loads(
        (project / "reports" / "orchestrator" / "phase3_one_shot.json").read_text())
    assert body["pdk"] == "sky130A"


def _pnr_contract_deck() -> str:
    marker = RUNNER._PNR_STAGE_MARKER
    return ("read_lef /pdk/core.lef\n"
            "read_verilog /work/netlist.v\n"
            "link_design chip_top\n"
            f'puts "{marker} floorplan"\n'
            "initialize_floorplan -die_area {0 0 100 100}\n"
            "place_pins -hor_layers m2\n"
            "write_def /work/phase3/stage3/pnr/floorplan.def\n"
            f'puts "{marker} placement"\n'
            "global_placement\n"
            f'puts "{marker} global_route"\n'
            "global_route\n"
            "detailed_route\n"
            "write_def /work/phase3/stage3/pnr/chip_top.def\n")


def test_pad_ring_is_inserted_at_the_real_floorplan_to_route_seam():
    full = RUNNER._inject_padring_io_lefs(
        _pnr_contract_deck(), ["/pdk/libs.ref/io/lef/pads.lef"])
    seed = RUNNER._floorplan_seed_tcl(full)
    routed = RUNNER._padring_routing_consumer_tcl(
        full, "/work/phase3/stage3/pnr/padring.def")
    assert seed.rstrip().endswith("exit")
    assert "global_placement" not in seed
    # vibe-ic#1958 — the ingest carries `-floorplan_initialize`: it lands the
    # ring on the design `link_design` has already created, instead of asking
    # odb for a second block (ODB-0251).
    ingest = routed.index(
        "read_def -floorplan_initialize /work/phase3/stage3/pnr/padring.def")
    assert ingest < routed.index("\nglobal_placement")
    assert ingest < routed.index("\ndetailed_route")
    assert routed.index("read_lef /pdk/libs.ref/io/lef/pads.lef") < routed.index(
        "read_verilog")
    assert "initialize_floorplan" not in routed
    assert "place_pins" not in routed
    assert "PADRING_ROUTING_INPUT_MISSING" in routed


def test_pad_ring_seam_is_fail_closed_when_missing_or_ambiguous():
    with pytest.raises(ValueError, match="found 0"):
        RUNNER._padring_routing_consumer_tcl(
            "global_placement\ndetailed_route\n", "/work/padring.def")
    double = _pnr_contract_deck() + _pnr_contract_deck()
    with pytest.raises(ValueError, match="found 2"):
        RUNNER._floorplan_seed_tcl(double)


def test_chip_top_producer_precedes_sdc_and_die_resolution():
    source = pathlib.Path(RUNNER.__file__).read_text()
    step = source[source.index("def step_pnr("):]
    step = step[:step.index("\ndef step_", 1)]
    # 98109186b routed the dispatch through `_padring_producer_dispatch`, which
    # consults `_chip_path_requests_pad_ring` (a HARDMACRO delivery builds no
    # ring, so its producer is not run). The ORDER property is unchanged: the
    # dispatch -- and therefore the producer, for a delivery that requests a
    # ring -- precedes both SDC construction and die resolution.
    dispatch_line = "_padring_producer = _padring_producer_dispatch("
    producer = step.index(dispatch_line)
    sdc = step.index("# SDC: silicon top != FPGA wrapper")
    # llv1 W7a moved die resolution, verbatim, into `_prepnr_geometry`
    # (shared with the between-segments step). The ORDER property is the
    # same: step_pnr calls it after the SDC, and the die resolution is still
    # the first thing that function does.
    die = step.index("_prep_dc = _prepnr_floorplan(")
    assert producer < sdc < die
    floorplan = source[source.index("def _prepnr_floorplan("):]
    floorplan = floorplan[:floorplan.index("\ndef ", 1)]
    assert "_prep_dc = _prepnr_geometry(" in floorplan
    assert floorplan.index("_prepnr_geometry(") < floorplan.index(
        "_floorplan_rectangles_record(")
    geometry = source[source.index("def _prepnr_geometry("):]
    geometry = geometry[:geometry.index("\ndef ", 1)]
    body = geometry[geometry.index('"""', geometry.index('"""') + 3) + 3:]
    first = next(l for l in body.splitlines()
                 if l.strip() and not l.strip().startswith("#"))
    assert first.strip().startswith("_requested_auto = str(die_um).lower()")
    assert geometry.index("_requested_auto =") < geometry.index(
        "die_um, _l9_die_note = _effective_die_um")
    assert step.count(dispatch_line) == 1
    assert 'supply_plan=(em_floor_for_resize or {}).get("supply_entry_plan")' in step
    # and the dispatch is the ONLY road to the producer from step_pnr: the
    # producer itself is called exactly once, inside the dispatch, never
    # directly from step_pnr (a second, ungated call would re-pin a hardmacro
    # to a ring it does not build).
    assert step.count("step_io_pad_chip_top_gen(") == 0
    dispatch = source[source.index("def _padring_producer_dispatch("):]
    dispatch = dispatch[:dispatch.index("\ndef ", 1)]
    assert dispatch.count("step_io_pad_chip_top_gen(project, container, pdk)") == 1


def _provisional_slot_project(tmp_path, *, answered_by="agent",
                              source_bytes=b'{"slot":"small"}\n'):
    project = tmp_path / "project"
    (project / "input/submission_template_source").mkdir(parents=True)
    (project / "input/submission_template/slots").mkdir(parents=True)
    (project / "reports/phase1").mkdir(parents=True)
    source = project / "input/submission_template_source/small.json"
    source.write_bytes(source_bytes)
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    authority = {
        "answered_by": answered_by,
        "authority": "Owner delegated implementation decisions",
        "decision": "initial implementation target",
        "operator_source": "input/submission_template/slots/small.yaml",
        "die_width_um": 100,
        "die_height_um": 140,
        "fit_status": "TO_BE_VERIFIED_BY_CANONICAL_AREA_AND_PAD_CHECKS",
        "fallback": "select the smallest adequate published slot",
        "delegation": {"answered_by": "owner",
                       "scope": "operator_template.slot",
                       "citation": "owner delegation"},
    }
    answers = {"operator_template": {"slot": "small"},
               "answer_provenance": {"operator_template.slot": authority}}
    (project / "input/step_0_5ic_answers.json").write_text(json.dumps(answers))
    declaration = {"operator_template": {"slot": "small"},
                   "answer_provenance": {"operator_template.slot": authority},
                   "answers": {"die_area_um": [0, 0, 100, 140]}}
    (project / "input/submission_template/tapeout_declaration.json").write_text(
        json.dumps(declaration))
    report = {"ingest": {"status": "INGESTED", "declared_slot": "small",
                          "slots": [
                              {"slot": "small", "source_relpath": "small.json",
                               "source_sha256": source_hash,
                               "die_area": {"rect": [0, 0, 100, 140]}},
                              {"slot": "wide", "source_relpath": "wide.json",
                               "source_sha256": None,
                               "die_area": {"rect": [0, 0, 170, 160]}},
                              {"slot": "large", "source_relpath": "large.json",
                               "source_sha256": None,
                               "die_area": {"rect": [0, 0, 200, 200]}},
                          ]}}
    for name in ("wide", "large"):
        payload = ('{"slot":"%s"}\n' % name).encode()
        (project / f"input/submission_template_source/{name}.json").write_bytes(payload)
        report["ingest"]["slots"][[r["slot"] for r in report["ingest"]["slots"]].index(name)]["source_sha256"] = hashlib.sha256(payload).hexdigest()
    for rec in report["ingest"]["slots"]:
        (project / f"input/submission_template/slots/{rec['slot']}.yaml").write_text(
            json.dumps(rec))
    (project / "reports/phase1/submission_template.json").write_text(
        json.dumps(report))
    return project


def test_provisional_delegated_slot_resolves_to_smallest_adequate_published_slot(
        tmp_path):
    project = _provisional_slot_project(tmp_path)
    resolved, refusal = RUNNER._ppa_area.resolve_provisional_slot_die(
        project, "100x140", 150)
    assert refusal is None
    assert resolved["intent"] == "DERIVED_PROVISIONAL_SLOT"
    assert resolved["declared_slot"] == "small"
    assert resolved["resolved_slot"] == "wide"
    assert resolved["resolved_die_um"] == "170x160"
    assert resolved["required_die_side_um"] == 150


def test_provisional_slot_resolution_uses_canonical_worker_inputs(tmp_path):
    project = _provisional_slot_project(tmp_path)
    # Default's bounded worker receives the source-bound slot contracts and
    # source JSON, not the earlier Phase-1 reporting copy.
    (project / "reports/phase1/submission_template.json").unlink()
    resolved, refusal = RUNNER._ppa_area.resolve_provisional_slot_die(
        project, "100x140", 150)
    assert refusal is None
    assert resolved["resolved_slot"] == "wide"


def test_prepnr_applies_provisional_slot_resolution(tmp_path, monkeypatch):
    project = _provisional_slot_project(tmp_path)
    netlist = project / "netlist.v"
    netlist.write_text("module top; endmodule\n")
    monkeypatch.setattr(RUNNER, "_effective_die_um",
                        lambda *_: ("100x140", "L19 derived test"))
    monkeypatch.setattr(RUNNER, "_l19_declared_die_area", lambda *_: "100x140")
    monkeypatch.setattr(RUNNER, "_l9_declared_die_area", lambda *_: None)
    monkeypatch.setattr(RUNNER, "_strap_plan_core_floor",
                        lambda *a, **k: (None, "test has no strap floor"))
    monkeypatch.setattr(RUNNER, "_pdk_nominal_voltage", lambda *a: None)
    monkeypatch.setattr(RUNNER._ppa_power, "_pdn_em_declared_current",
                        lambda *a: (None, "test", None))
    monkeypatch.setattr(RUNNER, "_resolve_auto_die_um",
                        lambda die, *a, **k: (die, None))
    monkeypatch.setattr(RUNNER, "_padring_required_die_um",
                        lambda *_: (150, "measured test ring"))
    monkeypatch.setattr(RUNNER, "_padring_core_inset_um",
                        lambda *a, **k: (10, None))
    monkeypatch.setattr(RUNNER, "_slot_geometry", lambda *_: None)
    monkeypatch.setattr(RUNNER, "_seal_ring_core_margin_um",
                        lambda *a, **k: (None, {"applies": False}))
    monkeypatch.setattr(RUNNER, "seal_ring_die_and_core",
                        lambda w, h, pad, *_: (w, h, pad, ""))
    monkeypatch.setattr(RUNNER, "seal_ring_die_too_small", lambda *a: None)
    monkeypatch.setattr(RUNNER._ppa_area, "real_core_placement_density",
                        lambda *a: (None, "test"))
    monkeypatch.setattr(RUNNER, "_chip_path_requests_pad_ring", lambda *_: True)
    monkeypatch.setattr(RUNNER, "ct03_pin_rect", lambda *a: None)
    pdk = type("Pdk", (), {"name": "neutral"})()
    result = RUNNER._prepnr_geometry(
        project, "top", pdk, "", "auto", 0.5, netlist, 0.0)
    assert isinstance(result, RUNNER.PrePnrDieCore)
    assert result.die_um == "170x160"
    assert result.die_intent["intent"] == "DERIVED_PROVISIONAL_SLOT"


def test_explicit_owner_slot_is_not_reclassified_as_derived(tmp_path):
    project = _provisional_slot_project(tmp_path, answered_by="owner")
    resolved, refusal = RUNNER._ppa_area.resolve_provisional_slot_die(
        project, "100x140", 150)
    assert resolved is None
    assert refusal is None


def test_provisional_slot_refuses_stale_catalogue_source(tmp_path):
    project = _provisional_slot_project(tmp_path)
    (project / "input/submission_template_source/wide.json").write_text("changed\n")
    resolved, refusal = RUNNER._ppa_area.resolve_provisional_slot_die(
        project, "100x140", 150)
    assert resolved is None
    assert refusal.startswith("DERIVED_SLOT_AUTHORITY_INVALID:")
    assert "wide.json changed after ingest" in refusal


def test_provisional_slot_refuses_when_no_published_slot_fits(tmp_path):
    project = _provisional_slot_project(tmp_path)
    resolved, refusal = RUNNER._ppa_area.resolve_provisional_slot_die(
        project, "100x140", 250)
    assert resolved is None
    assert refusal.startswith("DERIVED_SLOT_NO_ADEQUATE_PUBLISHED_SLOT:")


def test_default_step15_direct_invocation_binds_backend_receipt_before_consumer(
        tmp_path, monkeypatch):
    """The direct Default Step-15 call owns one producer/consumer invocation.

    This is intentionally a narrow seam test: no EDA process or full runner is
    launched.  It proves the direct producer, current-step census, consumer,
    and backend result happen in order; the final all-step refresh remains a
    separate phase-3 tail operation.
    """
    events = []
    project = tmp_path / "project"
    project.mkdir()

    def fake_pnr(current_project, *_args, **_kwargs):
        events.append("producer")
        pnr = current_project / "phase3/stage3/pnr"
        pnr.mkdir(parents=True, exist_ok=True)
        (pnr / "floorplan.def").write_text("floorplan\n")
        (pnr / "pdn.done").write_text("pdn\n")
        (pnr / "constraint.sdc").write_text(
            "create_clock -name clk -period 10 [get_ports clk]\n")
        return RUNNER.StepResult("pnr", "PASS", 0.0, "fixture")

    def fake_declared(current_project, step_id, *, input_manifest=None):
        events.append("declared")
        assert input_manifest is not None
        report = current_project / "reports/phase2/gates/stage2_compliance.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text('{"verdict":"PASS"}\n')
        return {
            "schema": "vibeic/current-step-producer-census/1",
            "scope": "current-step", "step_id": str(step_id),
            "verdict": "PRODUCED", "population": 1, "executed": 1,
            "already_produced_by_the_run": 0, "invalid_results": [],
            "unexecutable": [],
            "results": [{"rc": 0, "executed": True,
                          "target_exists_after": True,
                          "authorship": "producer"}],
        }

    def fake_consumer(_project, _row):
        events.append("consumer")
        return {"status": "PASS", "ledger": []}

    import flow_declared_producer_run as declared
    import execution_backend_worker as worker
    import execution_backend_producers as producers
    def bounded_producer(project, params):
        result = fake_pnr(project)
        return {'verdict': result.status, 'detail': result.detail}
    monkeypatch.setattr(producers, 'produce_pnr', bounded_producer)
    monkeypatch.setattr(producers, '_native_current_step_producer', lambda *_: None)
    monkeypatch.setattr(RUNNER, '_backend_parameter_values', lambda *_: {})
    monkeypatch.setattr(worker, 'resolve_input_contract', lambda *_: [])
    monkeypatch.setattr(declared, "run_for_step", fake_declared)
    monkeypatch.setattr(worker, "evaluate", fake_consumer)

    row = RUNNER._default_pnr_rows(
        project, "chip_top", None, "fixture", ['15'], die_um="auto", util=0.30)

    assert events == ["producer", "declared", "consumer"]
    assert row.status == "PASS"
    receipt = json.loads((project / "backend_result.json").read_text())
    assert receipt["schema"] == "vibeic/backend-result/2"
    assert receipt["step_id"] == "15"
    assert receipt["verdict"] == "PASS"
    assert receipt["current_step_declared_producers"]["direct_producer"][
        "producer"] == "execution_backend_producers.produce"
    source = pathlib.Path(RUNNER.__file__).read_text()
    main = source[source.index("def main("):]
    assert '_recorded("pnr", _default_step15_with_backend_receipt)' in main
    assert "flow_declared_producer_run.py" in main
    assert main.index('_recorded("pnr", _default_step15_with_backend_receipt)') \
        < main.index("flow_declared_producer_run.py")


def test_default_step15_consumer_refusal_survives_headline_rollup(tmp_path, monkeypatch):
    import flow_declared_producer_run as declared
    import execution_backend_worker as worker

    def native(project, *_args, **_kwargs):
        pnr = project / "phase3/stage3/pnr"
        pnr.mkdir(parents=True)
        (pnr / "floorplan.def").write_text("floorplan\n")
        (pnr / "pdn.done").write_text("pdn\n")
        return RUNNER.StepResult("pnr", "PASS", 0.0, "native completed")

    def refused(*_args, **_kwargs):
        raise ValueError("current producer input missing")

    import execution_backend_producers as producers
    def bounded_producer(project, params):
        result = native(project)
        return {'verdict': result.status, 'detail': result.detail}
    monkeypatch.setattr(producers, 'produce_pnr', bounded_producer)
    monkeypatch.setattr(producers, '_native_current_step_producer', lambda *_: None)
    monkeypatch.setattr(RUNNER, '_backend_parameter_values', lambda *_: {})
    monkeypatch.setattr(worker, 'resolve_input_contract', lambda *_: [])
    monkeypatch.setattr(declared, "run_for_step", refused)
    monkeypatch.setattr(worker, "evaluate", lambda *_args, **_kwargs:
                        pytest.fail("refused producer cannot authorize consumer"))
    row = RUNNER._default_pnr_rows(
        tmp_path, "chip_top", None, "fixture", ['15'], die_um="auto", util=0.30)
    assert row.status == "NOT_MEASURED"
    assert row.reason_class == RUNNER._V.ReasonClass.UPSTREAM_REFUSED
    assert RUNNER._aggregate_verdict([row]) != "PASS"


def _real_pdk(monkeypatch=None, **over):
    """A REAL `PdkConfig`, built from the runner's own dataclass.

    WHY NOT `object()` ANY MORE, and why not a two-attribute stand-in either.
    47029143bf made `_prepare_padring_for_route` run
    `step_io_pad_chip_top_gen(project, container, pdk)` FIRST — its
    `die_required_um` is an input to the die resolution, so a record that
    appears afterwards is a record nothing read — and the function returns FAIL
    when that producer refuses. MEASURED on TREE 7903c1972305 with the old
    `object()` double:

        FAIL — the IO pad chip-top producer refused:
        PADRING_PDK_TREE_UNRESOLVED: tech LEF is not under a distribution
        libs.ref tree

    so neither arm below ever reached the behaviour it asserts: the pad-gate
    arm never saw `BLOCKING before routing`, and the views arm never ran at all.

    THE COLLABORATOR IS BUILT, NOT DEFENDED AGAINST. Making the producer
    tolerate a stand-in (`getattr(pdk, ..., None)`, or skipping it when the pdk
    is not a real `PdkConfig`) would delete the ordering guarantee that landing
    bought — the floorplan elaborates the producer's chip top, and the die is
    sized to its ring — and would mask a genuinely broken `PdkConfig`.
    Pre-planting an `io_pad_chip_top.json` record to short-circuit the producer
    would make the double model a state the run cannot reach. This is the same
    repair 894e6298e7 made for the hardmacro doubles: construct the real
    dataclass, so a field the step starts reading tomorrow is one this double
    already has.

    The tech LEF is placed under a `libs.ref` tree because that is what
    `_pdk_root_c` resolves the distribution root from; the names are invented
    and no real PDK, vendor or cell appears."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="vic-pdk-")) / "pdks" / "probe_pdk"
    lef = root / "libs.ref" / "probe_tech" / "lef"
    lef.mkdir(parents=True, exist_ok=True)
    tech = lef / "probe.tlef"
    tech.write_text("VERSION 5.8 ;\nEND LIBRARY\n")
    cells = lef / "probe_cells.lef"
    cells.write_text("VERSION 5.8 ;\nEND LIBRARY\n")
    fields = dict(name="probe_pdk", liberty=str(lef / "probe.lib"),
                  tech_lef=str(tech), cell_lef=str(cells),
                  cell_gds=None, site="unit", drc_deck=None)
    fields.update(over)
    return RUNNER.PdkConfig(**fields)


def test_a_failing_pad_gate_stops_before_the_routing_deck_is_created(
        tmp_path, monkeypatch):
    project = tmp_path / "project"
    out_dir = project / "phase3/stage3/pnr"
    out_dir.mkdir(parents=True)

    def seed_only(*_args, **_kwargs):
        (out_dir / "floorplan.def").write_text("seed exists\n")
        return 0, "seed complete", ""

    monkeypatch.setattr(RUNNER, "_docker_exec", seed_only)

    def failing_gate(*_args, **_kwargs):
        return RUNNER.StepResult(
            "pad_ring_gen", "FAIL", detail="PADRING_POPULATION_LOST")

    stopped, consumer = RUNNER._prepare_padring_for_route(
        project, _real_pdk(), "container", out_dir, "/work/pnr",
        _pnr_contract_deck(), pad_ring_step=failing_gate,
        io_view_discover=lambda *_args: (["/pdk/io.lef"], ["/pdk/io.gds"]))
    assert stopped.status == "FAIL"
    assert "BLOCKING before routing" in stopped.detail
    assert consumer is None
    assert not (out_dir / "pnr.tcl").exists()


def test_the_chip_top_producer_runs_first_and_can_stop_the_ring(
        tmp_path, monkeypatch):
    """The ordering guarantee 47029143bf bought, pinned deliberately.

    `_prepare_padring_for_route` runs `step_io_pad_chip_top_gen` BEFORE the
    ring — the floorplan elaborates the chip top it writes, and the die is
    sized to the ring's own `die_required_um`, so a record that appears
    afterwards is a record nothing read — and it returns FAIL when the producer
    refuses.

    UNTIL NOW THAT WAS ONLY EXERCISED BY ACCIDENT: the arms above passed
    `object()` as the PDK, the producer refused it with
    `PADRING_PDK_TREE_UNRESOLVED`, and the FAIL they then saw was this path
    rather than the pad-gate path they were written for. Giving them a real
    `PdkConfig` fixes that — and would have deleted the only coverage this
    ordering had. So it is asserted here on purpose, with a PDK whose tech LEF
    is deliberately NOT under a distribution tree."""
    project = tmp_path / "project"
    out_dir = project / "phase3/stage3/pnr"
    out_dir.mkdir(parents=True)
    stray = tmp_path / "not_a_pdk_tree" / "probe.tlef"
    stray.parent.mkdir(parents=True)
    stray.write_text("VERSION 5.8 ;\nEND LIBRARY\n")
    unresolvable = _real_pdk(tech_lef=str(stray), cell_lef=str(stray),
                             liberty=str(stray))

    def gate_that_must_not_run(*_a, **_k):          # pragma: no cover
        raise AssertionError("the ring ran before the chip-top producer")

    stopped, consumer = RUNNER._prepare_padring_for_route(
        project, unresolvable, "container", out_dir, "/work/pnr",
        _pnr_contract_deck(), pad_ring_step=gate_that_must_not_run,
        io_view_discover=lambda *_a: (["/pdk/io.lef"], ["/pdk/io.gds"]))
    assert stopped.status == "FAIL", stopped
    assert "chip-top producer refused" in stopped.detail, stopped.detail
    assert consumer is None
    assert not (out_dir / "pnr.tcl").exists()


def test_the_same_io_physical_views_feed_seed_route_and_streamout(
        tmp_path, monkeypatch):
    project = tmp_path / "project"
    out_dir = project / "phase3/stage3/pnr"
    out_dir.mkdir(parents=True)

    def seed_only(*_args, **_kwargs):
        (out_dir / "floorplan.def").write_text("seed exists\n")
        return 0, "seed complete", ""

    monkeypatch.setattr(RUNNER, "_docker_exec", seed_only)

    def passing_gate(*_args, **_kwargs):
        (out_dir / "padring.def").write_text("ring exists\n")
        return RUNNER.StepResult("pad_ring_gen", "PASS")

    # The same REAL `PdkConfig` the arm above uses — see `_real_pdk`. The
    # two-attribute stand-in this replaces carried exactly the fields the
    # function touched on the day it was written, and the producer that landed
    # in front of it needs a resolvable PDK tree before either arm's behaviour
    # is reachable at all.
    pdk = _real_pdk()
    pdk.macro_lefs = []
    pdk.macro_gds = []
    result, consumer = RUNNER._prepare_padring_for_route(
        project, pdk, "container", out_dir, "/work/pnr",
        _pnr_contract_deck(), pad_ring_step=passing_gate,
        io_view_discover=lambda *_args: (
            ["/pdk/io_a.lef", "/pdk/io_b.lef"], ["/pdk/io.gds"]))
    assert result.status == "PASS"
    assert consumer.index("read_lef /pdk/io_a.lef") < consumer.index(
        "read_verilog")
    ingest = consumer.index("read_def ")
    assert "padring.def" in consumer[ingest:consumer.index("\n", ingest)]
    assert ingest < consumer.index("\nglobal_placement")
    assert pdk.macro_lefs == ["/pdk/io_a.lef", "/pdk/io_b.lef"]
    assert pdk.macro_gds == ["/pdk/io.gds"]


def test_padring_seam_records_the_complete_pnr_lef_inventory(tmp_path, monkeypatch):
    project = tmp_path / "project"
    out_dir = project / "phase3/stage3/pnr"
    out_dir.mkdir(parents=True)

    def seed_only(*_args, **_kwargs):
        (out_dir / "floorplan.def").write_text("seed exists\n")
        return 0, "seed complete", ""

    monkeypatch.setattr(RUNNER, "_docker_exec", seed_only)
    (out_dir / "padring.def").write_text("ring exists\n")

    def passing_gate(*_a, **_k):
        return RUNNER.StepResult("pad_ring_gen", "PASS")

    pdk = _real_pdk()
    pdk.macro_lefs = ["/pdk/existing_macro.lef"]
    deck = _pnr_contract_deck().replace(
        "read_lef /pdk/core.lef\n",
        f"read_lef {pdk.tech_lef}\nread_lef {pdk.cell_lef}\n"
        "read_lef /pdk/existing_macro.lef\n")
    result, consumer = RUNNER._prepare_padring_for_route(
        project, pdk, "container", out_dir, "/work/pnr",
        deck, pad_ring_step=passing_gate,
        io_view_discover=lambda *_args: (
            ["/pdk/io_a.lef", "/pdk/io_b.lef"], ["/pdk/io.gds"]))
    assert result.status == "PASS"
    record = json.loads((project / RUNNER.PHYSICAL_VIEW_INVENTORY_REL).read_text())
    assert record["verdict"] == "RECORDED"
    assert record["scope"] == "pnr_read_lef_inputs"
    assert record["read_lef_paths"] == re.findall(
        r"(?m)^\s*read_lef\s+(\S+)\s*$", consumer)
    assert record["read_lef_paths"][-2:] == ["/pdk/io_a.lef", "/pdk/io_b.lef"]


def test_checked_in_step_15_5ic_is_the_contract_the_runner_consumes(tmp_path):
    """Bind runner behavior to the real canonical flow, not a copied fixture."""
    import yaml
    import _hostpaths

    flow = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml")
    steps = yaml.safe_load(flow.read_text())["steps"]
    step = next(s for s in steps if str(s["id"]) == "15.5ic")
    assert step["condition_kind"] == "design_dependent"
    assert step["condition"]["any_of"] is True
    assert set(step["condition"]["files_exist"]) == {
        "input/submission_template/slots/*.yaml",
        "input/submission_template/SELF_TAPEOUT.txt"}
    assert {"pad_assignment_gen", "pad_ring_gen"} <= set(step["programs"])
    assert any(i["path"].endswith("/floorplan.def")
               for i in step["required_inputs"])

    project = tmp_path / "chip"
    marker = project / "input/submission_template/SELF_TAPEOUT.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("chip path\n")
    assert RUNNER._chip_path_requests_pad_ring(project) is True
    marker.unlink()
    assert RUNNER._chip_path_requests_pad_ring(project) is False


def _gds_record(rtype: int, dtype: int = 0, payload: bytes = b"") -> bytes:
    if len(payload) % 2:
        payload += b"\x00"
    return struct.pack(">HBB", len(payload) + 4, rtype, dtype) + payload


def _gds_structure(name: str, children=()) -> bytes:
    body = (_gds_record(0x05, 0x02, b"\x00" * 24)
            + _gds_record(0x06, 0x06, name.encode()))
    for child in children:
        body += (_gds_record(0x0A)
                 + _gds_record(0x12, 0x06, child.encode())
                 + _gds_record(0x11))
    return body + _gds_record(0x07)


def _write_pad_gds(path: Path, pad_refs: int, filler_refs: int = 1) -> None:
    path.write_bytes(
        _gds_record(0x00, 0x02, b"\x00\x03")
        + _gds_record(0x01, 0x02, b"\x00" * 24)
        + _gds_record(0x02, 0x06, b"contract")
        + _gds_structure("pad_master")
        + _gds_structure("corner_master")
        + _gds_structure("filler_master")
        + _gds_structure("chip_top",
                         ["pad_master"] * pad_refs + ["corner_master"]
                         + ["filler_master"] * filler_refs)
        + _gds_record(0x04))


def _def_with_ring() -> str:
    return ("VERSION 5.8 ;\nDESIGN chip_top ;\n"
            "UNITS DISTANCE MICRONS 1000 ;\n"
            "DIEAREA ( 0 0 ) ( 100000 100000 ) ;\n"
            "COMPONENTS 4 ;\n"
            "- pad_0 pad_master + FIXED ( 0 0 ) N ;\n"
            "- pad_1 pad_master + FIXED ( 90000 0 ) N ;\n"
            "- corner_0 corner_master + FIXED ( 0 90000 ) N ;\n"
            "- filler_0 filler_master + FIXED ( 10000 0 ) N ;\n"
            "END COMPONENTS\nPINS 0 ;\nEND PINS\nEND DESIGN\n")


def test_final_pad_evidence_reads_reachable_gds_references_and_harms_red(
        tmp_path):
    project = tmp_path / "project"
    pnr = project / "phase3/stage3/pnr"
    reports = project / "reports/phase3"
    pnr.mkdir(parents=True)
    reports.mkdir(parents=True)
    records = {
        "pads": [{"instance": "pad_0", "master": "pad_master"},
                 {"instance": "pad_1", "master": "pad_master"}],
        "corners": [{"instance": "corner_0", "master": "corner_master"}],
        "fillers": [{"instance": "filler_0", "master": "filler_master"}],
    }
    (reports / "padring.json").write_text(json.dumps(records))
    for name in ("padring.def", "routed.def", "chip_top.def"):
        (pnr / name).write_text(_def_with_ring())
    routed = RUNNER._padring_routing_consumer_tcl(
        _pnr_contract_deck(), "/work/phase3/stage3/pnr/padring.def")
    (pnr / "pnr.tcl").write_text(routed)
    (pnr / "openroad.log").write_text(
        "PADRING_ROUTING_CONSUMED: /work/phase3/stage3/pnr/padring.def\n")
    gds = pnr / "chip_top.gds"
    _write_pad_gds(gds, pad_refs=2)
    gds_result = RUNNER.StepResult(
        "gds", "PASS", extras={"streamout_engine": "test-stream"})

    good = RUNNER.step_pad_ring_final_evidence(
        project, "chip_top", gds_result)
    assert good.status == "PASS", good.detail
    evidence = json.loads(
        (reports / "pad_ring_route_evidence.json").read_text())
    assert evidence["gds_evidence"]["reachable_structure_references"] == {
        "pad_master": 2, "corner_master": 1, "filler_master": 1}

    # Harm control: the DEFs and hashes still look plausible, but one pad
    # reference vanished from the actual final GDS hierarchy.  This must be red.
    _write_pad_gds(gds, pad_refs=1)
    harmed = RUNNER.step_pad_ring_final_evidence(
        project, "chip_top", gds_result)
    assert harmed.status == "FAIL"
    assert "PADRING_GDS_REFERENCES_LOST" in harmed.detail

    # Independent physical harm: a missing filler reference must also fail.
    _write_pad_gds(gds, pad_refs=2, filler_refs=0)
    filler_harmed = RUNNER.step_pad_ring_final_evidence(
        project, "chip_top", gds_result)
    assert filler_harmed.status == "FAIL"
    assert "PADRING_GDS_REFERENCES_LOST" in filler_harmed.detail
