"""AI route choice must precede the ordinary design runner for every input."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import benchmark_dispatch as bd  # noqa: E402
import benchmark_io_adapter as bio  # noqa: E402
import route_decision as rd  # noqa: E402
import task_nature_route as tnr  # noqa: E402
import _path_layout as path_layout  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _runtime_pair_fixture as runtime_pair  # noqa: E402
from _hostpaths import require_repo  # noqa: E402


@pytest.fixture(autouse=True)
def _matching_pair(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBE_IC_DELIVERY_AUTHORITY_ROOT", str(tmp_path.parent / (tmp_path.name + "-authority")))
    runtime_pair.assume_matching_runtime_pair(monkeypatch)


PROMPT = ("Design a pulse stretcher named top_module. Its input pulse_in "
          "must be reflected at pulse_out for two clock cycles.")


def _dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "generic_pulse_prompt.txt").write_text(PROMPT)
    return dataset


def _task(run: Path) -> dict:
    rows = bd._read_jsonl(run / bd._ROUTE_WORKLIST)
    assert len(rows) == 1
    return rows[0]


def _answer(task: dict, nature: str, disposition: str = "CONFIRM") -> dict:
    return {
        "schema": bd._AI_ROUTE_SCHEMA,
        "id": task["id"],
        "task_sha256": task["task_sha256"],
        "prompt_sha256": task["prompt_sha256"],
        "source_sha256": task["public_original_input"].get("source_sha256"),
        "routing_contract_sha256": task["routing_contract_sha256"],
        "disposition": disposition,
        "ai_nature": nature,
        "author": {"kind": "AI", "model": "general-review-model"},
        "blind": {"oracle_accessed": False},
        "rationale": "The supplied words describe the requested design task.",
        "prompt_evidence": [{
            "excerpt": "Design a pulse stretcher named top_module",
            "supports": "The user requests a new pulse-stretcher module.",
        }],
    }


def _write_answer(task: dict, answer: dict) -> None:
    # Nature tests use a separately collected synthetic delivery fixture.
    # Genuine model-action controls are exercised outside this unit suite.
    from _delivery_review_fixture import accept_review
    import delivery_intent
    try:
        current = delivery_intent.resolve_project_delivery(Path(task['project']))
    except delivery_intent.DeliveryRefusal:
        current = None  # Mutation tests retain the original controller authority.
    if current is not None and current.outcome == 'unresolved':
        accept_review(Path(task['project']))
    path = Path(task["response_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(answer))


def _write_raw_answer(task: dict, raw: str) -> None:
    path = Path(task["response_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw)


def _route_response_run(tmp_path, monkeypatch, *, prompt: str = PROMPT):
    dataset, run = _dataset(tmp_path), tmp_path / "run"
    (dataset / "generic_pulse_prompt.txt").write_text(prompt)
    calls = []
    _record_canonical_frontdoor(monkeypatch, calls)
    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    return dataset, run, calls, _task(run)


def _typed_d1_runner(calls):
    """Fixture runner that emits the same bound artifacts as canonical D1."""
    def run(argv, *args, **kwargs):
        calls.append(argv)
        if argv[argv.index("--exit-step") + 1] != "D1":
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        context = json.loads(kwargs["env"][bd._RUNNER_CONTEXT_ENV])
        project = Path(context["project"])
        generated_docs = project / "phase1" / "generated_docs"
        generated_docs.mkdir(parents=True, exist_ok=True)
        (generated_docs / "L1.json").write_text(json.dumps({
            "schema": "fixture.phase1.ldoc.v1",
            "invocation_id": context["invocation_id"],
        }, sort_keys=True))
        producer = Path(context["source"]["runner"]["path"])
        report = {
            "schema": "fixture.phase1.report.v1",
            "verdict": "PASS",
            "runner_binding": {
                "schema": "vibeic.runner_report_binding.v1",
                "invocation_id": context["invocation_id"],
                "project": context["project"],
                "argv": context["argv"],
                "source": context["source"],
                "report_name": "phase1_one_shot.json",
                "producer": {
                    "path": str(producer),
                    "sha256": hashlib.sha256(producer.read_bytes()).hexdigest(),
                },
                "material": bd._runner_material_snapshot(project),
            },
        }
        report_path = path_layout.report_path(project, "phase1_one_shot.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, sort_keys=True))
        return SimpleNamespace(returncode=1, stdout="", stderr="")
    return run


def _record_canonical_frontdoor(monkeypatch, calls):
    frontdoors = []
    original = bd._ensure_phase1_frontdoor

    def wrapped(*args, **kwargs):
        frontdoors.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(bd, "_ensure_phase1_frontdoor", wrapped)
    monkeypatch.setattr(bd.subprocess, "run", _typed_d1_runner(calls))
    return frontdoors


def test_no_ai_route_means_no_design_runner(tmp_path, monkeypatch):
    dataset, run = _dataset(tmp_path), tmp_path / "run"
    calls = []
    monkeypatch.setattr(bd._RunnerBudget, "run",
                        lambda *_args: calls.append(1) or bd._ProcessOutcome(rc=1))

    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []  # pre-fix control fails by value: a runner was called.
    task = _task(run)
    assert task["program_proposal"]["needs_ai_parse"] is True
    assert bd._read_jsonl(run / bd._BACKUP_WORKLIST) == []
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST) == []
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []
    assert json.loads((run / "solve_report.json").read_text())["routing_phase"] == "PENDING"


@pytest.mark.parametrize("tamper", ["prompt_hash", "model", "oracle", "nature"])
def test_invalid_ai_route_still_launches_no_runner(tmp_path, monkeypatch, tamper):
    dataset, run = _dataset(tmp_path), tmp_path / "run"
    calls = []
    monkeypatch.setattr(bd._RunnerBudget, "run", lambda *_args: calls.append(1))
    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    task = _task(run)
    answer = _answer(task, task["program_proposal"]["entry_nature"])
    if tamper == "prompt_hash":
        answer["prompt_sha256"] = "0" * 64
    elif tamper == "model":
        answer["author"]["model"] = "unknown"
    elif tamper == "oracle":
        answer["blind"]["oracle_accessed"] = True
    else:
        answer["ai_nature"] = "not_a_product_route"
    _write_answer(task, answer)
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []
    assert json.loads((run / "solve_report.json").read_text())["routing_phase"] == "PENDING"


@pytest.mark.parametrize("prompt", [
    pytest.param(PROMPT, id="program-default"),
    pytest.param("Please use ultra mode.", id="user-explicit-ultra"),
])
def test_duplicate_top_level_disposition_is_rejected_by_public_frontdoors(
        tmp_path, monkeypatch, prompt):
    dataset, run, calls, task = _route_response_run(
        tmp_path, monkeypatch, prompt=prompt)
    raw = json.dumps(_answer(task, "spec_generation"), separators=(",", ":"))
    raw = raw.replace(
        '"disposition":"CONFIRM"',
        '"disposition":"NEEDS_CLARIFICATION","disposition":"CONFIRM"',
        1)
    _write_raw_answer(task, raw)
    decision, reasons = bd._validate_ai_route(task, run)
    assert decision is None
    assert any("duplicate JSON key: 'disposition'" in reason
               for reason in reasons)
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []
    assert json.loads((run / "solve_report.json").read_text())[
        "routing_phase"] == "PENDING"


@pytest.mark.parametrize(
    ("field", "needle", "replacement"),
    [
        pytest.param(
            "metadata",
            '"model":"general-review-model"',
            '"model":"general-review-model","model":"forged-model"',
            id="nested-metadata",
        ),
        pytest.param(
            "evidence",
            '"excerpt":"Design a pulse stretcher named top_module"',
            '"excerpt":"Design a pulse stretcher named top_module",'
            '"excerpt":"forged excerpt"',
            id="nested-evidence",
        ),
    ],
)
def test_duplicate_nested_route_evidence_is_rejected_before_decision(
        tmp_path, monkeypatch, field, needle, replacement):
    dataset, run, calls, task = _route_response_run(tmp_path, monkeypatch)
    raw = json.dumps(_answer(task, "spec_generation"), separators=(",", ":"))
    assert needle in raw
    _write_raw_answer(task, raw.replace(needle, replacement, 1))
    decision, reasons = bd._validate_ai_route(task, run)
    assert decision is None
    key = "model" if field == "metadata" else "excerpt"
    assert any(f"duplicate JSON key: '{key}'" in reason
               for reason in reasons)
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []
    assert json.loads((run / "solve_report.json").read_text())[
        "routing_phase"] == "PENDING"


@pytest.mark.parametrize("prompt,expected_authority", [
    pytest.param(PROMPT, "PROGRAM_DEFAULT", id="default-control"),
    pytest.param("Please use ultra mode.",
                 "USER_EXPLICIT_ULTRA", id="ultra-control"),
])
def test_unique_byte_equivalent_route_control_reaches_public_frontdoor(
        tmp_path, monkeypatch, prompt, expected_authority):
    dataset, run, calls, task = _route_response_run(
        tmp_path, monkeypatch, prompt=prompt)
    answer = _answer(task, "spec_generation")
    if expected_authority == "USER_EXPLICIT_ULTRA":
        answer["prompt_evidence"] = [{
            "excerpt": prompt,
            "supports": "The user explicitly selects Ultra execution mode.",
        }]
    raw = json.dumps(answer, separators=(",", ":"))
    _write_raw_answer(task, raw)
    assert json.loads(raw) == answer
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert len(calls) == 2
    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["routing_verdict"]["route_receipt"]["mode_intent"][
        "authority"] == expected_authority


def test_confirmed_ai_route_enters_only_its_derived_product_path(tmp_path,
                                                                   monkeypatch):
    dataset, run = _dataset(tmp_path), tmp_path / "run"
    calls = []
    _record_canonical_frontdoor(monkeypatch, calls)
    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    task = _task(run)
    _write_answer(task, _answer(task, "spec_generation"))
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert len(calls) == 2
    assert "--entry-step" not in calls[0]  # D1 is the normal front door.
    assert calls[0][calls[0].index("--exit-step") + 1] == "D1"
    assert calls[1][calls[1].index("--exit-step") + 1] == "2"
    assert bd._read_jsonl(run / bd._BACKUP_WORKLIST)[0]["skill"] == "spec-to-rtl"
    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["routing_verdict"]["source"] == "ai_confirmed"
    assert result["accepted"] is False


def test_changed_staged_prompt_invalidates_ai_route(tmp_path, monkeypatch):
    dataset, run = _dataset(tmp_path), tmp_path / "run"
    calls = []
    monkeypatch.setattr(bd._RunnerBudget, "run", lambda *_args: calls.append(1))
    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    task = _task(run)
    _write_answer(task, _answer(task, "spec_generation"))
    Path(task["prompt_path"]).write_text(PROMPT + " changed")
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []


def test_ai_override_selects_derived_midflow_entry(tmp_path, monkeypatch):
    dataset, run = _dataset(tmp_path), tmp_path / "run"
    (dataset / "generic_pulse_prompt.txt").write_text(
        "Fix the incorrect output inversion in this supplied module: "
        "module top_module(input wire a, output wire y); "
        "assign y = ~a; endmodule")
    original = tnr.classify_task_nature
    monkeypatch.setattr(tnr, "classify_task_nature", lambda *_a: {
        **original(PROMPT, False, "spec_generation"),
        "source": "synthetic_misroute_control"})
    calls = []
    frontdoors = _record_canonical_frontdoor(monkeypatch, calls)
    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    task = _task(run)
    answer = _answer(task, "debug", "OVERRIDE")
    answer["rationale"] = (
        "The visible prompt supplies a complete module and asks to fix its "
        "incorrect inversion. Debugging that supplied RTL is the correct "
        "existing-design route, not generation from an absent design. " * 2)
    # The OVERRIDE is grounded in THIS prompt (the generic helper's excerpt
    # is from PROMPT, which this dataset replaced); length alone never was.
    answer["prompt_evidence"] = [{
        "excerpt": "Fix the incorrect output inversion in this supplied module",
        "supports": "Repairing the supplied module is the debug route.",
    }]
    _write_answer(task, answer)
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert frontdoors == [1]
    assert len(calls) == 2
    assert calls[0][calls[0].index("--exit-step") + 1] == "D1"
    assert calls[1][calls[1].index("--entry-step") + 1] == "4"
    assert calls[1][calls[1].index("--exit-step") + 1] == "4"
    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["routing_verdict"]["source"] == "ai_override"
    assert result["routing_verdict"]["nature"] == "debug"


def test_route_table_drift_refuses_before_runner(tmp_path, monkeypatch):
    dataset, run = _dataset(tmp_path), tmp_path / "run"
    calls = []
    monkeypatch.setattr(bd._RunnerBudget, "run", lambda *_a: calls.append(1))
    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    task = _task(run)
    _write_answer(task, _answer(task, "spec_generation"))
    monkeypatch.setitem(tnr.NATURE_ENTRY["spec_generation"],
                        "entry_step", "2")
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []


def test_route_confirmation_does_not_unlock_score(tmp_path, monkeypatch):
    dataset, run = _dataset(tmp_path), tmp_path / "run"
    monkeypatch.setattr(bd.subprocess, "run",
                        lambda *_a, **_k: SimpleNamespace(returncode=1))
    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    task = _task(run)
    _write_answer(task, _answer(task, "spec_generation"))
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    with pytest.raises(SystemExit, match="acceptance status"):
        bd._require_program_first_ai_acceptance(run)


def test_batch_waits_for_every_route_then_resumes_without_restaging(
        tmp_path, monkeypatch):
    dataset, run = _dataset(tmp_path), tmp_path / "run"
    (dataset / "generic_second_prompt.txt").write_text(
        "Design a second generic output buffer with one input and one output.")
    calls = []

    def fake_runner(argv, *args, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(bd.subprocess, "run", fake_runner)
    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    tasks = bd._read_jsonl(run / bd._ROUTE_WORKLIST)
    assert len(tasks) == 2
    staged = {task["id"]: Path(task["prompt_path"]).read_bytes()
              for task in tasks}
    _write_answer(tasks[0], _answer(tasks[0], "spec_generation"))
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []
    assert json.loads((run / "solve_report.json").read_text())["routing_phase"] == "PENDING"
    second = _answer(tasks[1], "spec_generation")
    second["prompt_evidence"] = []
    second["rationale"] = "This input requests a new buffer implementation. " * 4
    _write_answer(tasks[1], second)
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert len(calls) == 2
    assert {task["id"]: Path(task["prompt_path"]).read_bytes()
            for task in tasks} == staged
    report = json.loads((run / "solve_report.json").read_text())
    assert report["routing_phase"] == "COMPLETE"
    assert report["route_confirmed"] == 2


def test_checked_in_prompt_reaches_runner_only_after_ai_route(tmp_path,
                                                                monkeypatch):
    # This is a real checked-in benchmark input, not prose authored alongside
    # the route implementation. It exercises the consumer's staged prompt.
    prompt = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "real_benchmark",
        "directional_bump_fall_moore_prompt.md").read_text()
    assert "module TopModule" in prompt
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "real_fsm_prompt.txt").write_text(prompt)
    run = tmp_path / "run"
    calls = []
    monkeypatch.setattr(
        bd.subprocess, "run",
        lambda argv, **_kwargs: calls.append(argv) or SimpleNamespace(returncode=1))

    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []
    task = _task(run)
    assert task["prompt_sha256"] == bd._sha256_text(prompt)
    response = _answer(task, "spec_generation")
    response["prompt_evidence"] = [{
        "excerpt": "Create a Moore state machine for a creature that walks and falls.",
        "supports": "The input requests a new Moore FSM from prose.",
    }]
    _write_answer(task, response)
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert len(calls) == 1
    report = json.loads((run / "solve_report.json").read_text())
    assert report["routing_phase"] == "COMPLETE"
    assert report["results"][0]["routing_verdict"]["source"] == "ai_confirmed"


_FIX_PROMPT = ("Fix the incorrect output inversion in this supplied module: "
               "module top_module(input wire a, output wire y); "
               "assign y = ~a; endmodule")
_LONG_GENERIC = ("The route was selected after careful consideration of the "
                 "visible input and the general product flow table. " * 4)


def _override_run(tmp_path, monkeypatch, prompt: str):
    dataset, run = _dataset(tmp_path), tmp_path / "run"
    (dataset / "generic_pulse_prompt.txt").write_text(prompt)
    calls = []
    _record_canonical_frontdoor(monkeypatch, calls)
    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    return dataset, run, calls, _task(run)


@pytest.mark.parametrize("evidence", [
    pytest.param([], id="no_evidence"),
    pytest.param([{"excerpt": "Fix the supplied module's broken output",
                   "supports": "The user asks to debug an existing module."}],
                 id="excerpt_not_in_prompt"),
    pytest.param([{"excerpt": "pulse_in",
                   "supports": "x"}], id="claim_too_short"),
])
def test_override_without_verified_evidence_stays_pending(
        tmp_path, monkeypatch, evidence):
    # Review wave 52 (both lenses, MAJOR): a 160-character generic rationale
    # was accepted in place of any checked prompt excerpt, and a generation
    # prompt was routed to debug (entry 4).  Length is not grounding.
    dataset, run, calls, task = _override_run(tmp_path, monkeypatch, PROMPT)
    answer = _answer(task, "debug", "OVERRIDE")
    answer["prompt_evidence"] = evidence
    answer["rationale"] = _LONG_GENERIC
    assert len(answer["rationale"]) >= 160
    _write_answer(task, answer)
    decision, reasons = bd._validate_ai_route(task, run)
    assert decision is None
    assert any("OVERRIDE requires verified prompt evidence" in r
               for r in reasons), reasons
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []
    assert json.loads((run / "solve_report.json").read_text())[
        "routing_phase"] == "PENDING"


def test_override_evidence_must_be_cited_for_the_selected_nature(
        tmp_path, monkeypatch):
    # A real excerpt whose claim argues for some other route does not ground
    # the nature the response selects.
    dataset, run, calls, task = _override_run(tmp_path, monkeypatch, PROMPT)
    answer = _answer(task, "debug", "OVERRIDE")
    answer["prompt_evidence"] = [{
        "excerpt": "Design a pulse stretcher named top_module",
        "supports": "The user requests a brand-new module from prose.",
    }]
    answer["rationale"] = _LONG_GENERIC
    _write_answer(task, answer)
    decision, reasons = bd._validate_ai_route(task, run)
    assert decision is None
    assert any("no verified evidence claim names the selected ai_nature 'debug'" in r
               for r in reasons), reasons
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []


def test_grounded_override_with_short_rationale_is_accepted(tmp_path,
                                                             monkeypatch):
    # Sibling arm: evidence, not length, is what grounds an OVERRIDE.
    original = tnr.classify_task_nature
    monkeypatch.setattr(tnr, "classify_task_nature", lambda *_a: {
        **original(PROMPT, False, "spec_generation"),
        "source": "synthetic_misroute_control"})
    dataset, run, calls, task = _override_run(tmp_path, monkeypatch,
                                              _FIX_PROMPT)
    answer = _answer(task, "debug", "OVERRIDE")
    answer["rationale"] = "Supplied RTL must be repaired."
    answer["prompt_evidence"] = [{
        "excerpt": "Fix the incorrect output inversion in this supplied module",
        "supports": "Repairing supplied RTL is the debug route.",
    }]
    _write_answer(task, answer)
    decision, reasons = bd._validate_ai_route(task, run)
    assert reasons == [] and decision["source"] == "ai_override"
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert len(calls) == 2
    assert calls[0][calls[0].index("--exit-step") + 1] == "D1"
    assert calls[1][calls[1].index("--entry-step") + 1] == "4"


def test_untyped_legacy_frontdoor_cannot_activate_d1(tmp_path, monkeypatch):
    dataset, run = _dataset(tmp_path), tmp_path / "run"
    calls = []
    monkeypatch.setattr(
        bd, "_ensure_phase1_frontdoor",
        lambda *_args, **_kwargs: {
            "status": "GENERATED",
            "provenance": {"ran": True, "digest": "a" * 64},
        })
    monkeypatch.setattr(bd.subprocess, "run", _typed_d1_runner(calls))
    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    task = _task(run)
    _write_answer(task, _answer(task, "spec_generation"))
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []
    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert "current D1 gate receipt missing" in result["worker_error"]


def _rewrite_issued_route_task(run: Path, task: dict) -> dict:
    """Co-mutate the mutable worklist and the self-hashed sibling for a probe."""
    body = dict(task)
    body.pop("task_sha256", None)
    body["task_sha256"] = bd._sha256_text(json.dumps(body, sort_keys=True))
    (run / bd._ROUTE_WORKLIST).write_text(json.dumps(body) + "\n")
    (run / "ai_route_tasks" / f"{body['task_sha256']}.json").write_text(
        json.dumps(body, sort_keys=True))
    return body


def test_prompt_delivery_floor_inherits_shippable_gds_and_ic_route(
        tmp_path, monkeypatch):
    prompt = ("Complete a DIE and produce a shippable GDS with a tape-out "
              "precheck for this pulse stretcher.")
    dataset, run, calls, task = _route_response_run(
        tmp_path, monkeypatch, prompt=prompt)
    answer = _answer(task, "spec_generation")
    answer["prompt_evidence"] = [{
        "excerpt": "Complete a DIE and produce a shippable GDS with a tape-out precheck",
        "supports": "The user requests a DIE shippable GDS delivery.",
    }]
    _write_answer(task, answer)
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert len(calls) == 2
    assert "--route" in calls[0] and calls[0][calls[0].index("--route") + 1] == "ic"
    assert calls[1][calls[1].index("--route") + 1] == "ic"
    assert calls[1][calls[1].index("--exit-step") + 1] == "37.5ic"


@pytest.mark.parametrize("target", ["rtl", "ip_hardmacro"])
def test_prompt_delivery_conflict_refuses_downgrade_or_route_flip(
        tmp_path, monkeypatch, target):
    prompt = ("Complete a DIE and produce a shippable GDS with a tape-out "
              "precheck for this pulse stretcher.")
    dataset, run, calls, task = _route_response_run(
        tmp_path, monkeypatch, prompt=prompt)
    answer = _answer(task, "spec_generation")
    answer["semantic_decision"] = {
        "nature": "spec_generation",
        "delivery_target": target,
        "semantic_payload_sha256": task["semantic_payload_sha256"],
    }
    answer["prompt_evidence"] = [{
        "excerpt": "Complete a DIE and produce a shippable GDS with a tape-out precheck",
        "supports": "The user requests a DIE shippable GDS delivery.",
    }]
    _write_answer(task, answer)
    decision, reasons = bd._validate_ai_route(task, run)
    assert decision is None
    assert any("delivery" in reason.lower() or "route" in reason.lower()
               for reason in reasons), reasons
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []


def test_prompt_delivery_explicit_compatible_target_is_accepted(
        tmp_path, monkeypatch):
    prompt = ("Complete a DIE and produce a shippable GDS with a tape-out "
              "precheck for this pulse stretcher.")
    dataset, run, calls, task = _route_response_run(
        tmp_path, monkeypatch, prompt=prompt)
    answer = _answer(task, "spec_generation")
    answer["semantic_decision"] = {
        "nature": "spec_generation",
        "delivery_target": "shippable_gds",
        "semantic_payload_sha256": task["semantic_payload_sha256"],
    }
    answer["prompt_evidence"] = [{
        "excerpt": "Complete a DIE and produce a shippable GDS with a tape-out precheck",
        "supports": "The user requests a DIE shippable GDS delivery.",
    }]
    _write_answer(task, answer)
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert len(calls) == 2
    assert calls[1][calls[1].index("--route") + 1] == "ic"
    assert calls[1][calls[1].index("--exit-step") + 1] == "37.5ic"


def test_route_resume_rejects_co_mutated_run_root_even_when_self_hashes_match(
        tmp_path, monkeypatch):
    dataset, run, calls, task = _route_response_run(tmp_path, monkeypatch)
    original_prompt = Path(task["prompt_path"]).read_text()
    forged_prompt = "Please use ultra mode and replace the staged task."
    forged = dict(task)
    forged["prompt_sha256"] = bd._sha256_text(forged_prompt)
    forged["prompt_chars"] = len(forged_prompt)
    forged["semantic_payload"] = tnr.semantic_routing_payload(forged_prompt)
    forged["semantic_payload_sha256"] = forged["semantic_payload"][
        "semantic_payload_sha256"]
    public_input = dict(forged["public_original_input"])
    public_input["prompt_sha256"] = forged["prompt_sha256"]
    public_input["source_sha256"] = bio._public_source_hash(public_input)
    forged["public_original_input"] = public_input
    forged["prompt_delivery_requirements"] = tnr.prompt_delivery_requirements(
        forged_prompt)
    forged["response_path"] = str(
        run / "ai_routes" / task["id"] / f"{forged['prompt_sha256']}.json")
    forged["coordinator_binding"] = rd.build_coordinator_binding(
        benchmark="verilogeval-human", problem_id=forged["id"],
        project_path=forged["project"], prompt_path=forged["prompt_path"],
        response_path=forged["response_path"], dataset_path=str(dataset.resolve()),
        semantic_payload_sha256=forged["semantic_payload_sha256"],
        harness_digest=None, golden_digest=None, expected_digest=None)
    # The run-root copies, including the staged public-input manifest, are
    # deliberately co-mutated; only the coordinator-owned anchor remains.
    Path(forged["prompt_path"]).write_text(forged_prompt)
    manifest = Path(forged["project"]) / "input" / "public_original" / "manifest.json"
    manifest.write_text(json.dumps(public_input, sort_keys=True, indent=2) + "\n")
    forged = _rewrite_issued_route_task(run, forged)
    response = _answer(forged, "spec_generation")
    response["prompt_sha256"] = forged["prompt_sha256"]
    response["prompt_evidence"] = [{
        "excerpt": forged_prompt,
        "supports": "The user explicitly selects Ultra execution mode.",
    }]
    _write_answer(forged, response)
    legacy_decision, legacy_reasons = bd._validate_ai_route(forged, run)
    assert legacy_decision is None
    assert any('DELIVERY_REVIEW_STALE' in reason for reason in legacy_reasons)
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []
    assert original_prompt != forged_prompt


def test_nonfinite_author_model_is_rejected_before_route_decision(
        tmp_path, monkeypatch):
    dataset, run, calls, task = _route_response_run(tmp_path, monkeypatch)
    raw = json.dumps(_answer(task, "spec_generation"), separators=(",", ":"))
    raw = raw.replace('"model":"general-review-model"', '"model":NaN')
    _write_raw_answer(task, raw)
    decision, reasons = bd._validate_ai_route(task, run)
    assert decision is None
    assert any("non-finite" in reason.lower() for reason in reasons), reasons
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []
