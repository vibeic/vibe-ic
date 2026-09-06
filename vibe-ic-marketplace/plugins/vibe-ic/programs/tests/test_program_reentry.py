"""ONE Program re-entry operation: re-run the FIXED Program on preserved signed input.

Issue #2047 merged the two operations that #2043 was implemented as -- the
v1.17.63 ``--program-regate`` and the v1.17.71 ``--program-retry`` -- into one.
This module is the merged module: it holds the tests of BOTH, re-pointed at
``--program-regate``, plus the tests the merge itself needs.

A deterministic gate can normalize a signed author candidate into different
bytes before freezing it, which correctly makes the author's final signature
stale.  When that transform is later FIXED the pending task is stuck: its
unchanged output is not re-gated, restoring the signed input reads as a new AI
edit needing a counterexample against the unwanted candidate, and re-signing
the unwanted output would attribute a PROGRAM mutation to the AI author.

These tests pin the third option -- an explicit, evidence-bound Program
re-entry -- and pin that it stays separate from every other permit: it never
accepts, never publishes, never supersedes a challenge, never grants a repair
permit, and never weakens the stale-signature refusal for a task that has no
verified re-entry record.

TWO fixtures, deliberately kept: ``_stuck`` reaches the operation from the
gate-normalization state the re-gate was written for, and ``_case`` from the
Program-transform state the retry was written for.  They are different entry
states into the same operation, so keeping both is coverage, not the
duplication the issue exists to remove.

RETIRED ids are declared in ``RETIRED`` below with their collision table, and
``test_every_pre_merge_id_is_re_pointed_or_retired`` refuses a silent drop.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_benchmark_program_first_ai_review as fx

bd = fx.bd
bio = fx.bio
pytestmark = fx._NEEDS_SIMULATOR

_SIGNED_RTL = "module dut(input wire a, output wire y); assign y = a; endmodule\n"
# The UNWANTED transform: the alias step added an unsolicited public reset
# port the author never asked for.  Different bytes, different frozen hash.
_UNWANTED = ("module dut(input wire a, input wire rst_n, output wire y); "
             "assign y = a; endmodule\n")
# A benign normalization a FIXED Program may still legitimately apply. It is
# semantically identical and produces a THIRD distinct hash, so the author's
# signature genuinely cannot cover it.
_BENIGN = "module dut(input wire a, output wire y);\n  assign y = a;\nendmodule\n"

_OLD_PROGRAM = "1.17.49"
_NEW_PROGRAM = "1.17.52"

_RATIONALE = (
    "The deterministic alias step added an unsolicited public reset "
    "port to the signed candidate before freezing it; that transform "
    "is fixed, so re-enter the fixed Program from the preserved input.")


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


_digest = _hash


def _running() -> str:
    """The running Program version; "" where the pre-fix tree has none."""
    return str(getattr(bd, "_program_version", lambda: "")())


def _source_identity():
    # The pre-fix control reaches the OLD coordinator; no missing API failure.
    helper = getattr(bd, "_program_source_identity", None) \
        or getattr(bd, "_program_retry_identity", None)
    return helper() if helper else {"source_sha256": "0" * 64}


def _has_regate() -> bool:
    return "program_regate" in inspect.signature(bd.cmd_resume).parameters


def _resume(run, request=None, *, regate=None, retry=None):
    """Run the REAL resume entry; pass the operation only where it exists.

    The pre-fix control therefore runs the same real coordinator and is graded
    on the state it leaves behind, not on a missing attribute.
    """
    target = request if request is not None else regate
    kwargs = {}
    if retry is not None:
        kwargs = ({"program_retry": str(retry)}
                  if "program_retry" in inspect.signature(bd.cmd_resume).parameters
                  else {})
    elif target is not None and _has_regate():
        kwargs = {"program_regate": str(target)}
    return bd.cmd_resume("rtllm", "/unused", str(run), worker_threads=1, **kwargs)


def _merged_identity_fields(run, task, signed, *, before=_OLD_PROGRAM, after=None,
                            rationale_key="rationale"):
    """The BOTH-identities half of every merged request.

    The version pair and the source-tree hash are neither necessary nor
    sufficient for each other, so the merged operation requires both; every
    request builder here therefore supplies both.
    """
    preserved = task.get("repair_input_candidate_snapshot") or {}
    manifest = preserved.get("manifest_path")
    fields = {
        "program_version_before": before,
        "program_version_after": after or _running(),
        "program_identity": _source_identity(),
        "author": {"kind": "AI", "model": "independent-test-reviewer"},
        "blind": {"oracle_accessed": False},
        rationale_key: _RATIONALE,
        "repair_record_sha256": _hash((task.get("repair_provenance") or {}).get("path")),
    }
    if manifest:
        fields.update(input_manifest_path=manifest,
                      input_manifest_sha256=_hash(manifest),
                      input_rtl_sha256=signed)
    return fields


def _gate(monkeypatch, produce: str):
    """Model the PROGRAM gates: normalize the work tree, then report PASS.

    The merged operation runs in a STAGED project, so the boundary takes the
    project from the runner argv rather than looking for a "projects" path.
    """
    real_run = bd.subprocess.run
    seen: list = []

    def fake_run(argv, *args, **kwargs):
        joined = " ".join(str(v) for v in argv)
        if "vibe_ic_one_shot_runner.py" not in joined:
            return real_run(argv, *args, **kwargs)
        seen.append(list(argv))
        project = Path(str(argv[2]))
        (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(produce)
        report = project / "reports" / "orchestrator" / "phase2_one_shot.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({
            "verdict": "PASS",
            "steps": [{"name": "rtl_gen", "status": "SKIPPED-BY-ENTRY",
                       "detail": "run declared --entry-step 2"}],
        }))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bd.subprocess, "run", fake_run)
    return seen


def _declare_exit(run, step="2"):
    """Bind the solve result's declared exit; the operation refuses without one."""
    solve_path = Path(run) / "solve_report.json"
    solve = json.loads(solve_path.read_text())
    solve["results"][0]["exit"] = step
    solve_path.write_text(json.dumps(solve))


def _stuck(tmp_path, monkeypatch):
    """The exact stuck state: signed input, unwanted gate output, stale sig.

    The whole stuck state is produced while the OLD Program is running, so the
    preserved input records the version that actually made the unwanted bytes
    and the later re-entry has a real version delta to name.
    """
    monkeypatch.setattr(bd, "_program_version", lambda: _OLD_PROGRAM,
                        raising=False)
    run, task, _ = fx._task(tmp_path)
    project = Path(task["project"])
    working = project / "phase2" / "stage1" / "rtl" / "dut.v"
    working.write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task("p1", project, got, fx.ROUTING, 0,
                                   run, "PROGRAM")
    fx._solve_report(run, task)
    _declare_exit(run)
    fx._write_review(task, fx._proven_fail_review(task))
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert bd._read_jsonl(run / bd._REPAIR_WORKLIST)[0]["status"] == \
        "AI_SEMANTIC_REPAIR_REQUIRED"

    # The author authors and SIGNS exactly these bytes.
    working.write_text(_SIGNED_RTL)
    signed = bd._sha256_text(bd._candidate_text(bd._rtl_files(project)))
    fx._write_ai_repair_record(
        run, task, bd._validate_ai_review(task)["verified_challenge"])
    record_path = bd._repair_record_path(run, task)
    signed_record = record_path.read_bytes()

    # The gates normalize those bytes into something the author never signed.
    _gate(monkeypatch, _UNWANTED)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    stuck = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    _declare_exit(run)
    # The Program is upgraded. Everything after this point runs on the fix.
    monkeypatch.undo()
    monkeypatch.setattr(bd, "_program_version", lambda: _NEW_PROGRAM,
                        raising=False)
    return run, stuck, signed, signed_record, record_path


def _request(run, task, signed, *, before=_OLD_PROGRAM, after=None, **over):
    request = {
        "schema": "vibeic.benchmark.program_regate.v1",
        "id": task["id"],
        "task_sha256": bd._sha256_text(
            json.dumps(task, ensure_ascii=False, sort_keys=True)),
        "prompt_sha256": task["prompt_sha256"],
        "signed_input_sha256": signed,
        "stale_output_sha256": task["rtl_sha256"],
        **_merged_identity_fields(run, task, signed, before=before, after=after),
    }
    request.update(over)
    path = Path(run) / f"regate_request_{len(list(Path(run).glob('regate_*')))}.json"
    path.write_text(json.dumps(request))
    return path, request


def _case(tmp_path, monkeypatch, *, reviewed=False, exit_step="2"):
    """The Program-transform entry state (the v1.17.71 fixture, re-pointed).

    Built under the OLD Program version so the merged operation's version-pair
    identity has a real delta to name, exactly as `_stuck` does.
    """
    monkeypatch.setattr(bd, "_program_version", lambda: _OLD_PROGRAM,
                        raising=False)
    run = tmp_path / "run"
    project = fx._project(tmp_path)
    rtl = project / "phase2/stage1/rtl/dut.v"
    rtl.write_text(rtl.read_text().replace("y = a", "y = ~a"))
    parent = bd._make_ai_review_task("p1", project,
        fx.bio.collect("rtllm", "p1", project), fx.ROUTING, 0, run, "PROGRAM")
    fx._write_review(parent, fx._proven_fail_review(parent))
    verdict = bd._validate_ai_review(parent)
    assert verdict["status"] == "REPAIR_REQUIRED"
    challenge = verdict["verified_challenge"]
    rtl.write_text(rtl.read_text().replace("y = ~a", "y = a"))
    signed = fx._write_ai_repair_record(run, parent, challenge)
    bd._archive_candidate("p1", project,
        {"id": "p1", "ok": True, "completion": rtl.read_text()}, run, "AI_REPAIR_INPUT")
    fx._solve_report(run, parent)
    _declare_exit(run, exit_step)
    state = {"mode": "old", "calls": [], "on_run": None, "rc": 0}
    real_run = bd.subprocess.run

    def boundary(argv, **kwargs):
        if not any(str(a).endswith("vibe_ic_one_shot_runner.py") for a in argv):
            return real_run(argv, **kwargs)
        state["calls"].append(list(argv))
        candidate = Path(argv[2])
        current = candidate / "phase2/stage1/rtl/dut.v"
        if state["mode"] == "interrupt":
            raise KeyboardInterrupt("controlled runner interruption")
        if state["mode"] == "failure":
            return SimpleNamespace(returncode=1)
        if state["mode"] in {"old", "still_transforms"}:
            current.write_text(current.read_text().replace("y = a", "y = 1'b0"))
        report = candidate / "reports/orchestrator/phase2_one_shot.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"verdict": "FAIL" if state["rc"] else "PASS",
            "steps": [{"name": "rtl_gen", "status": "SKIPPED-BY-ENTRY"}]}))
        if state["on_run"]:
            state["on_run"](candidate)
        assert kwargs["env"]["OMP_NUM_THREADS"] == "1"
        return SimpleNamespace(returncode=state["rc"])

    monkeypatch.setattr(bd.subprocess, "run", boundary)
    assert bd.cmd_resume("rtllm", "/unused", str(run), worker_threads=1) == 2
    task = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert task["candidate_origin"] == "AI_REPAIR"
    assert task["rtl_sha256"] != signed["repaired_rtl_sha256"]
    assert bd.cmd_resume("rtllm", "/unused", str(run), worker_threads=1) == 2
    repairs = bd._read_jsonl(run / bd._REPAIR_WORKLIST)
    assert "AI_REPAIR_FINAL_PROVENANCE_REQUIRED" in {r["status"] for r in repairs}
    _declare_exit(run, exit_step)
    if reviewed:
        fx._write_review(task, fx._proven_fail_review(task))
    # The Program is upgraded; everything after this point runs on the fix.
    monkeypatch.undo()
    monkeypatch.setattr(bd, "_program_version", lambda: _NEW_PROGRAM,
                        raising=False)
    monkeypatch.setattr(bd.subprocess, "run", boundary)
    request = {
        # The v1.17.71 request shape, deliberately: `reason` and `rtl_sha256`,
        # NOT their merged spellings. Emitting both would make this fixture
        # stop being the legacy caller it exists to prove still binds -- and
        # MEASURED, it also sent the stale-`reason` case to the alias
        # DISAGREEMENT guard instead of the rationale guard it names.
        "schema": "vibeic.benchmark.program_retry.v1", "id": task["id"],
        "task_sha256": bd._sha256_text(json.dumps(task, ensure_ascii=False, sort_keys=True)),
        "prompt_sha256": task["prompt_sha256"], "rtl_sha256": task["rtl_sha256"],
        **_merged_identity_fields(run, task, signed["repaired_rtl_sha256"],
                                  rationale_key="reason"),
    }
    if reviewed:
        request.update(review_sha256=_hash(task["review_path"]),
                       challenge_sha256=_hash(task["challenge_path"]))
    path = run / "program_reentry_request.json"
    path.write_text(json.dumps(request))
    state.update(mode="fixed", calls=[])
    return run, task, path, request, state


def _protected(run, task):
    paths = [run / bd._REVIEW_WORKLIST, run / "solve_report.json",
             Path(task["repair_provenance"]["path"]), Path(task["prompt_path"]),
             *map(Path, task["working_rtl_paths"]), *map(Path, task["rtl_paths"])]
    return {str(p): p.read_bytes() for p in paths}


def _refusal(capsys):
    err = capsys.readouterr().err
    assert "PROGRAM_REGATE_REFUSED" in err, err
    return err


# ── the stuck state itself, and the refusal that must NOT be weakened ──

def test_the_gate_boundary_records_the_signed_input_and_its_output(
        tmp_path, monkeypatch):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    binding = stuck.get("pre_gate_input") or {}
    assert binding.get("signed_input_sha256") == signed
    assert binding.get("gate_output_sha256") == stuck["rtl_sha256"]
    assert stuck["rtl_sha256"] != signed
    # The pair is a RECORDED FACT on disk, not something reconstructed later.
    manifest = json.loads(Path(binding["input_manifest_path"]).read_text())
    assert manifest["rtl_sha256"] == signed
    preserved = [Path(p) for p in manifest["rtl_paths"]]
    assert preserved and all(p.is_file() for p in preserved)
    assert bd._sha256_text(bd._candidate_text(preserved)) == signed
    assert Path(preserved[0]).read_text() == _SIGNED_RTL
    assert json.loads(Path(binding["binding_path"]).read_text())[
        "gate_output_sha256"] == stuck["rtl_sha256"]


def test_the_stale_signature_refusal_still_fires_without_a_regate_record(
        tmp_path, monkeypatch):
    """The installed refusal is CORRECT. It must survive this whole change."""
    run, stuck, _, _, _ = _stuck(tmp_path, monkeypatch)
    assert stuck.get("program_regate") is None
    rebound, reasons = bd._refresh_final_repair_provenance(stuck)
    assert rebound is None
    assert any("repaired_rtl_sha256 is stale or wrong" in r for r in reasons), reasons
    assert any("repaired hash is stale" in r
               for r in bd._validate_embedded_repair_provenance(stuck))
    # With a review present the stale signature is a REJECTION, not a pass.
    fx._write_review(stuck, fx._valid_review(stuck))
    assert bd._validate_ai_review(stuck)["status"] == "REJECTED"


# ── the happy path ────────────────────────────────────────────────────

@pytest.mark.parametrize("fixed_output, third_hash", [
    (_SIGNED_RTL, False),   # the fixed step preserves the exact signed bytes
    (_BENIGN, True),        # the fixed step still normalizes, benignly
])
def test_a_fixed_program_regates_from_the_preserved_signed_input(
        tmp_path, monkeypatch, capsys, fixed_output, third_hash):
    run, stuck, signed, signed_record, record_path = _stuck(tmp_path, monkeypatch)
    stale = stuck["rtl_sha256"]
    request_path, _ = _request(run, stuck, signed)
    _gate(monkeypatch, fixed_output)

    assert _resume(run, request_path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    regate = new.get("program_regate") or {}

    # A NEW output, from the preserved input, by the FIXED Program.
    assert new["rtl_sha256"] != stale
    assert (new["rtl_sha256"] != signed) is third_hash
    assert regate.get("new_output_sha256") == new["rtl_sha256"]
    assert regate.get("stale_output_sha256") == stale
    assert regate.get("signed_input_sha256") == signed
    assert regate.get("status") == "FRESH_REVIEW_REQUIRED"

    # BOTH identities are recorded, not just the one each old operation kept.
    assert regate.get("program_version_before") == _OLD_PROGRAM
    assert regate.get("program_version_after") == _NEW_PROGRAM
    assert regate.get("program_identity") == _source_identity()

    # The author's bytes did not change; the Program's did.
    assert record_path.read_bytes() == signed_record
    assert new["repair_provenance"]["repaired_rtl_sha256"] == signed
    assert regate.get("attributed_to") == "PROGRAM"
    assert regate.get("author_signature_unchanged") is True
    assert regate.get("repair_authorized") is False
    assert bd._validate_embedded_repair_provenance(new) == []

    # No acceptance, no publication, and a FRESH independent review is owed.
    outcome = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert outcome["accepted_ids"] == []
    assert outcome["review_outcomes"][0]["status"] == "PENDING", outcome
    assert new["review_path"] != stuck["review_path"]
    assert not Path(new["review_path"]).exists()
    assert not Path(new["challenge_path"]).exists()
    assert not Path(new["response_path"]).exists()
    # The old challenges are kept, and none was retired by the re-entry.
    assert {c["sha256"] for c in stuck["verification_challenges"]} <= \
        {c["sha256"] for c in new["verification_challenges"]}
    assert "PROGRAM_REGATE_APPLIED" in capsys.readouterr().out


def test_the_transition_is_reconstructable_from_records_alone(
        tmp_path, monkeypatch):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, request = _request(run, stuck, signed)
    _gate(monkeypatch, _BENIGN)
    assert _resume(run, request_path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    regate = new.get("program_regate") or {}
    assert regate.get("archive_path"), "no re-entry was recorded on the task"
    archive = Path(regate["archive_path"])
    transition = json.loads((archive / "transition.json").read_text())
    assert json.loads((archive / "request.json").read_text()) == request
    assert transition["prior_task"] == stuck
    # The merged archive preserves the ENTIRE prior project and worklist, not
    # just the prior gate-output manifest the re-gate alone archived.
    assert (archive / "prior_project").is_dir()
    assert bd._read_jsonl(archive / "prior_state" / bd._REVIEW_WORKLIST)[0] == stuck
    # Program version before/after, input sha, stale sha, new sha, signature.
    assert transition["new_task"]["program_regate"][
        "program_version_before"] == request["program_version_before"]
    assert transition["new_task"]["program_regate"][
        "program_version_after"] == _running()
    assert transition["prior_task"]["rtl_sha256"] == request[
        "stale_output_sha256"]
    assert transition["prior_task"]["repair_provenance"][
        "repaired_rtl_sha256"] == signed


def test_a_replayed_request_is_refused_not_silently_reapplied(
        tmp_path, monkeypatch, capsys):
    """Replaces the retired `test_regate_replay_is_idempotent`.

    The re-gate reported ALREADY_APPLIED and changed nothing. The merged
    operation refuses instead -- and the refusal that actually answers a
    BYTE-IDENTICAL replay is the staleness guard, MEASURED, not the archive
    guard: a successful re-entry rewrites the task, so the request's
    `task_sha256` no longer describes anything on disk. The message is
    asserted rather than the token, because this operation checks in a fixed
    order and "something was refused" would pass on any earlier guard.

    The other half of the old idempotence -- a second round with the request
    RE-BOUND to the new task -- is
    `test_a_second_re_entry_under_the_same_source_identity_is_refused`.
    """
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed)
    _gate(monkeypatch, _BENIGN)
    assert _resume(run, request_path) == 2
    first = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    capsys.readouterr()
    assert _resume(run, request_path) == 2
    assert "stale task_sha256" in _refusal(capsys)
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0] == first


# ── the refusals ──────────────────────────────────────────────────────

@pytest.mark.parametrize("field, value, needle", [
    ("schema", "vibeic.benchmark.program_regate.v2", "unsupported request schema"),
    ("id", "p9", "missing or duplicate review task"),
    ("task_sha256", "0" * 64, "stale task_sha256"),
    ("prompt_sha256", "0" * 64, "stale prompt_sha256"),
    ("stale_output_sha256", "0" * 64, "stale stale_output_sha256"),
    ("signed_input_sha256", "0" * 64, "not the hash the author signed"),
    ("author", {"kind": "HUMAN", "model": "x"}, "attributed blind AI"),
    ("blind", {"oracle_accessed": True}, "attributed blind AI"),
    ("rationale", "too short", "rationale needs 80 characters"),
    # A version that is neither the running Program nor the one the preserved
    # input was made under: the request names a lineage the archive denies.
    ("program_version_before", "0.9.9",
     "is not the Program that produced the preserved input"),
    # The SECOND identity half, contributed by the retry side.
    ("program_identity", {"source_sha256": "0" * 64}, "stale Program identity"),
    ("repair_record_sha256", "0" * 64, "stale repair record hash"),
])
def test_a_malformed_or_stale_request_is_refused(
        tmp_path, monkeypatch, capsys, field, value, needle):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    # Two fields have a second accepted spelling. Setting only one of them
    # would be answered by the alias-disagreement refusal, which is a
    # different guard; override BOTH so the input reaches the one under test.
    over = {field: value}
    for primary, legacy in (("stale_output_sha256", "rtl_sha256"),
                            ("signed_input_sha256", "input_rtl_sha256")):
        if field in (primary, legacy):
            over[primary] = over[legacy] = value
    request_path, _ = _request(run, stuck, signed, **over)
    before = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    assert _resume(run, request_path) == 2
    assert needle in _refusal(capsys)
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST) == before


def test_a_request_naming_no_source_identity_is_refused(
        tmp_path, monkeypatch, capsys):
    """The merged operation needs BOTH identities; a version pair alone is the
    v1.17.63 request, and it no longer establishes that the Program moved."""
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, request = _request(run, stuck, signed)
    request.pop("program_identity")
    request_path.write_text(json.dumps(request))
    before = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    assert _resume(run, request_path) == 2
    assert "names no Program source identity" in _refusal(capsys)
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST) == before


@pytest.mark.parametrize("primary, legacy", [
    ("stale_output_sha256", "rtl_sha256"),
    ("signed_input_sha256", "input_rtl_sha256"),
])
def test_the_two_spellings_of_one_field_may_not_disagree(
        tmp_path, monkeypatch, capsys, primary, legacy):
    """The merged operation accepts either front door's spelling of these two
    hashes so no caller breaks, but a request that supplies both under
    conflicting values has no identity at all and is refused, not ordered."""
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed, **{legacy: "f" * 64})
    before = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    assert _resume(run, request_path) == 2
    assert f"{primary} and {legacy} disagree" in _refusal(capsys)
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST) == before


def test_an_unchanged_program_version_is_a_loop_not_a_fix(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    same = _running()
    request_path, _ = _request(run, stuck, signed, before=same, after=same)
    before = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    assert _resume(run, request_path) == 2
    assert "is a loop, not a fix" in _refusal(capsys)
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST) == before


def test_a_program_version_that_is_not_the_running_one_is_refused(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed, after="99.99.99")
    assert _resume(run, request_path) == 2
    assert "is not the running Program" in _refusal(capsys)


@pytest.mark.parametrize("kind", ["deleted", "mutated", "unbound"])
def test_a_missing_or_drifted_preserved_input_is_refused(
        tmp_path, monkeypatch, capsys, kind):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    binding = stuck.get("pre_gate_input") or {}
    assert binding.get("input_manifest_path"), \
        "the signed pre-gate input was never preserved"
    manifest_path = Path(binding["input_manifest_path"])
    preserved = Path(json.loads(manifest_path.read_text())["rtl_paths"][0])
    if kind == "deleted":
        preserved.unlink()
        needle = "missing file"
    elif kind == "mutated":
        preserved.chmod(0o644)
        preserved.write_text(_UNWANTED)
        needle = "preserved signed input hash drift"
    else:
        tasks = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
        tasks[0]["pre_gate_input"] = None
        bd._write_jsonl(run / bd._REVIEW_WORKLIST, tasks)
        stuck = tasks[0]
        needle = "no preserved pre-gate input record"
    request_path, _ = _request(run, stuck, signed)
    assert _resume(run, request_path) == 2
    assert needle in _refusal(capsys)


def test_a_hand_edited_work_tree_cannot_be_smuggled_through_a_regate(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed)
    working = Path(stuck["working_rtl_paths"][0])
    working.write_text(
        "module dut(input wire a, output wire y); assign y = 1'b0; endmodule\n")
    assert _resume(run, request_path) == 2
    assert "working or frozen RTL drift" in _refusal(capsys)


@pytest.mark.parametrize("kind", ["accepted", "published"])
def test_an_accepted_or_published_candidate_cannot_be_regated(
        tmp_path, monkeypatch, capsys, kind):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed)
    if kind == "accepted":
        solve_path = run / "solve_report.json"
        solve = json.loads(solve_path.read_text())
        solve["results"][0]["accepted"] = True
        solve_path.write_text(json.dumps(solve))
        needle = "task must be unaccepted"
    else:
        response = Path(stuck["response_path"])
        response.parent.mkdir(parents=True, exist_ok=True)
        response.write_text("{}")
        needle = "candidate already published"
    assert _resume(run, request_path) == 2
    assert needle in _refusal(capsys)


def test_a_concurrent_coordinator_refuses_the_regate(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed)
    before = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    with bd._run_root_coordinator_lock(Path(run), "solve"):
        assert _resume(run, request_path) == 2
        assert bd._read_jsonl(run / bd._REVIEW_WORKLIST) == before
    # The lock DELAYS the operation; it does not permanently refuse it. The
    # identical request applies once the other coordinator lets go -- which is
    # what makes the assertion above a statement about the lock.
    _gate(monkeypatch, _BENIGN)
    assert _resume(run, request_path) == 2
    applied = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert (applied.get("program_regate") or {}).get(
        "status") == "FRESH_REVIEW_REQUIRED"
    assert applied["rtl_sha256"] != before[0]["rtl_sha256"]


def test_a_non_repair_candidate_cannot_be_regated(
        tmp_path, monkeypatch, capsys):
    run, task, _ = fx._task(tmp_path)
    fx._solve_report(run, task)
    _declare_exit(run)
    fx._write_review(task, fx._valid_review(task))
    request = {
        "schema": "vibeic.benchmark.program_regate.v1", "id": task["id"],
        "task_sha256": bd._sha256_text(
            json.dumps(task, ensure_ascii=False, sort_keys=True)),
        "prompt_sha256": task["prompt_sha256"],
        "signed_input_sha256": "a" * 64,
        "stale_output_sha256": task["rtl_sha256"],
        "program_version_before": _OLD_PROGRAM,
        "program_version_after": _running(),
        "program_identity": _source_identity(),
        "author": {"kind": "AI", "model": "independent-test-reviewer"},
        "blind": {"oracle_accessed": False},
        "rationale": _RATIONALE,
    }
    request_path = Path(run) / "regate_request_nonrepair.json"
    request_path.write_text(json.dumps(request))
    assert _resume(run, request_path) == 2
    assert "only an AI_REPAIR candidate can be re-gated" in _refusal(capsys)


def test_a_symlinked_request_is_refused_without_reading_its_target(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed)
    link = Path(run) / "linked_request.json"
    link.symlink_to(request_path)
    assert _resume(run, link) == 2
    assert "symlink path" in _refusal(capsys)


# ── the Program-transform entry state (the v1.17.71 tests, re-pointed) ──

def test_retry_replaces_frozen_output_from_signed_input_then_normal_review_accepts(tmp_path, monkeypatch):
    run, old, path, request, state = _case(tmp_path, monkeypatch, reviewed=True)
    old_signature = Path(old["repair_provenance"]["path"]).read_bytes()
    old_rtl = [Path(p).read_bytes() for p in old["rtl_paths"]]
    assert _resume(run, path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    # Non-vacuous pre-fix failure observes the old, transformed frozen hash.
    assert new["rtl_sha256"] == request["input_rtl_sha256"], new["rtl_sha256"]
    assert new["rtl_sha256"] != old["rtl_sha256"]
    assert bd._validate_ai_review(new)["status"] == "PENDING"
    assert not Path(new["review_path"]).exists()
    assert not Path(new["challenge_path"]).exists()
    assert not Path(new["response_path"]).exists()
    assert new["repair_provenance"] == old["repair_provenance"]
    assert Path(old["repair_provenance"]["path"]).read_bytes() == old_signature
    assert [Path(p).read_bytes() for p in old["rtl_paths"]] == old_rtl
    assert new["program_candidate_snapshot"] == old["program_candidate_snapshot"]
    assert new["repair_parent_candidate_snapshot"] == old["repair_parent_candidate_snapshot"]
    assert {c["sha256"] for c in old["verification_challenges"]} <= {c["sha256"] for c in new["verification_challenges"]}
    assert _hash(old["challenge_path"]) in {c["sha256"] for c in new["verification_challenges"]}
    archive = Path(new["program_regate"]["archive_path"])
    assert (archive / "prior_review.json").read_bytes() == Path(old["review_path"]).read_bytes()
    assert (archive / "prior_project/phase2/stage1/rtl/dut.v").read_bytes() == old_rtl[0]
    assert (archive / "staged_project/reports/orchestrator/phase2_one_shot.json").is_file()
    assert bd._read_jsonl(archive / "prior_state" / bd._REVIEW_WORKLIST)[0] == old
    argv = state["calls"][0]
    assert argv[argv.index("--entry-step") + 1] == "2"
    assert argv[argv.index("--exit-step") + 1] == "2"
    fx._write_review(new, fx._valid_review(new))
    assert bd.cmd_resume("rtllm", "/unused", str(run), worker_threads=1) == 0
    accepted = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert accepted["accepted_ids"] == [old["id"]]
    assert json.loads(Path(new["response_path"]).read_text())["completion"] == Path(new["rtl_paths"][0]).read_text()


def test_plain_resume_keeps_transformed_output_and_requires_real_final_signature(tmp_path, monkeypatch):
    run, old, _, _, state = _case(tmp_path, monkeypatch)
    assert bd.cmd_resume("rtllm", "/unused", str(run), worker_threads=1) == 2
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0] == old
    assert state["calls"] == []
    assert bd._refresh_final_repair_provenance(old)[0] is None


#: Each stale field and the guard that must ANSWER it. Naming the message is
#: what makes the case a test of that field: this operation checks in a fixed
#: order, so asserting only "the sources are intact" passes on whichever
#: earlier guard fired and keeps passing after the intended one is deleted.
#: MEASURED per case, not assumed.
_STALE_GUARD = {
    "task_sha256": "stale task_sha256",
    "prompt_sha256": "stale prompt_sha256",
    "rtl_sha256": "stale stale_output_sha256",
    "repair_record_sha256": "stale repair record hash",
    "input_manifest_sha256": "stale input manifest hash",
    # "stale" is not 64 hex, so the shape guard answers first -- still this
    # field's own guard, and named as the one that actually fires.
    "input_rtl_sha256": "malformed signed_input_sha256",
    "program_identity": "stale Program identity",
    "schema": "unsupported request schema",
    "reason": "rationale needs 80 characters",
}


@pytest.mark.parametrize("field", sorted(_STALE_GUARD))
def test_stale_request_refuses_before_mutation(tmp_path, monkeypatch, capsys, field):
    run, old, path, request, state = _case(tmp_path, monkeypatch)
    request[field] = "stale"
    path.write_text(json.dumps(request))
    before = _protected(run, old)
    assert _resume(run, path) == 2
    assert _STALE_GUARD[field] in _refusal(capsys)
    assert _protected(run, old) == before
    assert state["calls"] == []
    assert not (run / "program_regates").exists()


#: Each state drift and the guard that must ANSWER it, measured per case.
_DRIFT_GUARD = {
    "working": "working or frozen RTL drift",
    "signature": "stale repair record hash",
    # Appending to a frozen snapshot's own RTL breaks that snapshot's integrity
    # check, which is the guard that owns those bytes.
    "input": "candidate snapshot RTL bytes do not match completion",
    "parent": "candidate snapshot RTL bytes do not match completion",
    "prompt": "prompt drift",
    "challenge": "inherited challenge drift",
    "accepted": "task must be unaccepted",
    "accepted_ledger": "candidate already accepted",
    "published": "candidate already published",
    "occupied": "occupied re-entry archive or fresh review/test path",
    "occupied_review": "occupied re-entry archive or fresh review/test path",
    "external": "path outside run",
    "symlink": "symlink path",
}


@pytest.mark.parametrize("drift", sorted(_DRIFT_GUARD))
def test_evidence_and_state_refusals_preserve_sources(
        tmp_path, monkeypatch, capsys, drift):
    run, old, path, request, state = _case(tmp_path, monkeypatch)
    if drift in {"working", "signature", "prompt", "parent", "challenge", "input"}:
        target = {"working": old["working_rtl_paths"][0], "signature": old["repair_provenance"]["path"],
                  "prompt": old["prompt_path"], "parent": old["program_candidate_snapshot"]["rtl_paths"][0],
                  "challenge": old["verification_challenges"][0]["path"],
                  "input": json.loads(Path(request["input_manifest_path"]).read_text())["rtl_paths"][0]}[drift]
        with Path(target).open("a") as stream:
            stream.write("\nchanged\n")
    elif drift == "accepted":
        solve = json.loads((run / "solve_report.json").read_text())
        solve["results"][0]["accepted"] = True
        (run / "solve_report.json").write_text(json.dumps(solve))
    elif drift == "published":
        Path(old["response_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(old["response_path"]).write_text("published")
    elif drift == "accepted_ledger":
        acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
        acceptance["accepted_ids"] = [old["id"]]
        (run / bd._ACCEPTANCE_REPORT).write_text(json.dumps(acceptance))
    elif drift in {"occupied", "occupied_review"}:
        key = "program-regate-" + bd._sha256_text(path.read_text())
        occupied = (run / "ai_verification_challenges/p1" / key / "challenge_tb.sv"
                    if drift == "occupied" else run / "ai_reviews/p1" / (key + ".json"))
        occupied.parent.mkdir(parents=True, exist_ok=True)
        occupied.write_text("already authored")
    elif drift == "external":
        outside = tmp_path / "outside.json"
        outside.write_bytes(Path(request["input_manifest_path"]).read_bytes())
        request["input_manifest_path"] = str(outside)
        path.write_text(json.dumps(request))
    elif drift == "symlink":
        linked = run / "linked_request.json"
        linked.symlink_to(path)
        path = linked
    before = _protected(run, old)
    assert _resume(run, path) == 2
    assert _DRIFT_GUARD[drift] in _refusal(capsys)
    assert _protected(run, old) == before
    assert state["calls"] == []


@pytest.mark.parametrize("mode", ["failure", "source_drift", "program_drift", "output_symlink", "interrupt", "promotion_interrupt"])
def test_staged_failure_and_interruption_are_safe(tmp_path, monkeypatch, mode):
    run, old, path, _, state = _case(tmp_path, monkeypatch)
    before = _protected(run, old)
    if mode == "source_drift":
        def edit(_):
            Path(old["working_rtl_paths"][0]).write_text("owner edit\n")
        state["on_run"] = edit
    elif mode == "program_drift":
        def upgrade(_):
            monkeypatch.setattr(bd, "_program_source_identity", lambda: {"changed": True})
        state["on_run"] = upgrade
    elif mode == "output_symlink":
        def escape(staged):
            (staged / "escaped").symlink_to(tmp_path / "outside")
        state["on_run"] = escape
    elif mode == "promotion_interrupt":
        real = Path.rename
        def interrupted(src, target):
            if src.name == "promotion_project":
                raise OSError("controlled promotion interruption")
            return real(src, target)
        monkeypatch.setattr(Path, "rename", interrupted)
    else:
        state["mode"] = mode
    if mode == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            _resume(run, path)
    else:
        assert _resume(run, path) == 2
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0] == old
    assert not Path(old["response_path"]).exists()
    if mode == "source_drift":
        assert Path(old["working_rtl_paths"][0]).read_text() == "owner edit\n"
    elif mode != "promotion_interrupt":
        assert _protected(run, old) == before
    if mode in {"interrupt", "promotion_interrupt"}:
        task_bytes = (run / bd._REVIEW_WORKLIST).read_bytes()
        assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
        assert (run / bd._REVIEW_WORKLIST).read_bytes() == task_bytes


def test_still_transforming_program_keeps_original_final_provenance_refusal(tmp_path, monkeypatch):
    run, old, path, _, state = _case(tmp_path, monkeypatch)
    state["mode"] = "still_transforms"
    assert _resume(run, path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["rtl_sha256"] == old["rtl_sha256"]
    assert new["repair_provenance"] == old["repair_provenance"]
    assert bd._refresh_final_repair_provenance(new)[0] is None
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert "AI_REPAIR_FINAL_PROVENANCE_REQUIRED" in {r["status"] for r in bd._read_jsonl(run / bd._REPAIR_WORKLIST)}


def test_normal_internal_links_and_declared_exit_predicate_are_preserved(tmp_path, monkeypatch):
    run, old, path, _, state = _case(tmp_path, monkeypatch)
    steps = Path(old["project"]) / "steps"
    steps.mkdir()
    (steps / "report").symlink_to("../reports/orchestrator/phase2_one_shot.json")
    (steps / "optional").symlink_to("../reports/not-yet-emitted.json")
    state["rc"] = 1
    assert _resume(run, path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["rtl_sha256"] != old["rtl_sha256"]
    assert new["program_verification"]["runner_rc"] == 1
    assert new["program_verification"]["functional_confirmation_required"] is True
    assert os.readlink(steps / "optional") == "../reports/not-yet-emitted.json"
    assert bd._validate_ai_review(new)["status"] == "PENDING"


def test_coordinator_lock_prevents_program_retry(tmp_path, monkeypatch):
    run, old, path, _, state = _case(tmp_path, monkeypatch)
    before = _protected(run, old)
    with bd._run_root_coordinator_lock(run, "owner"):
        assert _resume(run, path) == 2
    assert _protected(run, old) == before
    assert state["calls"] == []


@pytest.mark.parametrize("malformed", [[], None, {"schema": "vibeic.benchmark.program_retry.v1", "id": []}])
def test_malformed_requests_refuse_without_traceback(tmp_path, monkeypatch, malformed):
    run, old, path, _, state = _case(tmp_path, monkeypatch)
    path.write_text(json.dumps(malformed))
    before = _protected(run, old)
    assert _resume(run, path) == 2
    assert _protected(run, old) == before
    assert state["calls"] == []


def test_program_retry_capture_routes_to_shared_coordinator():
    routing = json.loads((bd.HARNESS / "CAPTURE_ROUTING.json").read_text())
    assert routing["steps"]["benchmark.program_regate"]["bucket_A_program"] == "programs/benchmark_dispatch.py"
    # ONE routed step for ONE operation: the merged name replaced the sibling.
    assert "benchmark.program_retry" not in routing["steps"]


@pytest.mark.parametrize("marker", ["complete.json", "failed.json"])
def test_malformed_terminal_marker_cannot_hide_interruption(tmp_path, monkeypatch, marker):
    run, old, path, _, state = _case(tmp_path, monkeypatch)
    state["mode"] = "interrupt"
    with pytest.raises(KeyboardInterrupt):
        _resume(run, path)
    archive = next((run / "program_regates/p1").iterdir())
    (archive / marker).write_text("{}")
    before = _protected(run, old)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert _protected(run, old) == before


def test_automatic_input_snapshot_matches_signed_pre_gate_bytes(tmp_path, monkeypatch):
    run, old, _, request, _ = _case(tmp_path, monkeypatch)
    preserved = old["repair_input_candidate_snapshot"]
    assert bd._validate_candidate_snapshot(preserved, old["id"]) == []
    assert preserved["rtl_sha256"] == request["input_rtl_sha256"]
    assert preserved["rtl_sha256"] == old["repair_provenance"]["repaired_rtl_sha256"]


def test_unchanged_program_cannot_retry_again(tmp_path, monkeypatch):
    run, old, path, request, state = _case(tmp_path, monkeypatch)
    assert _resume(run, path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["rtl_sha256"] != old["rtl_sha256"]
    request.update(task_sha256=bd._sha256_text(json.dumps(new, ensure_ascii=False, sort_keys=True)),
                   rtl_sha256=new["rtl_sha256"], stale_output_sha256=new["rtl_sha256"],
                   reason="A second re-entry with unchanged installed Program sources is not an upgrade.")
    path.write_text(json.dumps(request))
    before = _protected(run, new)
    state["calls"] = []
    assert _resume(run, path) == 2
    assert _protected(run, new) == before
    assert state["calls"] == []


@pytest.mark.parametrize("malformed", ["response_alias", "input_file_count"])
def test_exact_path_and_file_mapping_preflight(tmp_path, monkeypatch, malformed):
    run, old, path, request, state = _case(tmp_path, monkeypatch)
    if malformed == "response_alias":
        published = Path(old["response_path"])
        published.parent.mkdir(parents=True, exist_ok=True)
        published.write_text("already published")
        old["response_path"] = str(run / "different_response.json")
    else:
        old.pop("repair_input_candidate_snapshot", None)  # legacy manifest path
        candidate = json.loads(Path(request["input_manifest_path"]).read_text())
        original = Path(candidate["rtl_paths"][0]).read_text()
        assert original.endswith("\n")
        split = run / "split_input"
        split.mkdir()
        (split / "first.v").write_text(original[:-1])
        (split / "second.v").write_text("")
        candidate["rtl_paths"] = [str(split / "first.v"), str(split / "second.v")]
        manifest = split / "manifest.json"
        candidate["manifest_path"] = str(manifest)
        manifest.write_text(json.dumps(candidate))
        assert bd._validate_candidate_snapshot(candidate, old["id"]) == []
        request.update(input_manifest_path=str(manifest), input_manifest_sha256=_hash(manifest))
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [old])
    request["task_sha256"] = bd._sha256_text(json.dumps(old, ensure_ascii=False, sort_keys=True))
    path.write_text(json.dumps(request))
    before = _protected(run, old)
    assert _resume(run, path) == 2
    assert _protected(run, old) == before
    assert state["calls"] == []
    assert not (run / "program_regates").exists()


# ── the operation stays separate from every other permit ──────────────

@pytest.mark.parametrize("marker", [
    "--program-regate",
    "--program-regate and --review-correction are separate",
    "--program-regate requires --resume alone",
])
def test_the_two_operations_are_declared_separate_at_the_front_door(marker):
    """`--program-regate` is its own operation, not a mode of the sibling.

    Re-pointed: the "two operations" are now the review correction and the ONE
    Program re-entry. `--program-retry` is no longer a second operation to be
    separate FROM -- it is this one's deprecated alias, pinned below.
    """
    assert marker in Path(bd.__file__).read_text()


def test_the_front_door_refuses_both_operations_in_one_resume(
        tmp_path, monkeypatch, capsys):
    """The separation must be REFUSED, not merely written down.

    The sibling test above reads the source, so it survives a front door whose
    check has been removed while its help text stays. This one runs the parser.
    Asserting the message -- not just the exit code -- keeps it red on a tree
    that has no `--program-regate` at all, where argparse answers
    "unrecognized arguments" with the same SystemExit(2).
    """
    monkeypatch.setattr(bd.sys, "argv", [
        "benchmark_dispatch.py", "rtllm", "--resume",
        "--run", str(tmp_path),
        "--program-regate", str(tmp_path / "regate.json"),
        "--review-correction", str(tmp_path / "correction.json")])
    with pytest.raises(SystemExit) as excinfo:
        bd.main()
    assert excinfo.value.code == 2
    assert "--program-regate and --review-correction are separate" in \
        capsys.readouterr().err


def test_a_regate_record_that_does_not_verify_changes_nothing():
    """Both directions, on a pure in-memory task: only a COMPLETE record binds.

    Every mutation below removes one binding.  Each must send the signature
    comparison back to the frozen candidate, which is what the installed
    refusal compares against -- so a forged record can never buy a signature.
    """
    signed, produced = "a" * 64, "b" * 64
    task = {"id": "p1", "rtl_sha256": produced}
    signed_hash = getattr(bd, "_signed_candidate_hash",
                          lambda t: str(t.get("rtl_sha256") or ""))
    assert signed_hash(task) == produced
    good = {
        "schema": "vibeic.benchmark.program_regate.v1",
        "signed_input_sha256": signed,
        "new_output_sha256": produced,
        "program_version_before": "1.0.0",
        "program_version_after": "1.0.1",
        "input_manifest_path": "/nonexistent/manifest.json",
    }
    # Even a WELL-FORMED record whose preserved input is unreadable binds
    # nothing: "could not read it" is never "read it and it matched".
    assert signed_hash({**task, "program_regate": good}) == produced
    for field, value in [
            ("schema", "vibeic.benchmark.program_regate.v2"),
            ("signed_input_sha256", "not-a-hash"),
            ("new_output_sha256", "c" * 64),
            ("program_version_before", "1.0.1"),
            ("program_version_after", ""),
    ]:
        broken = {**good, field: value}
        assert signed_hash({**task, "program_regate": broken}) == produced, field


def test_a_verified_regate_record_is_what_binds_the_signature(
        tmp_path, monkeypatch):
    """The positive half of the pair above, against real preserved bytes."""
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed)
    _gate(monkeypatch, _BENIGN)
    assert _resume(run, request_path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    signed_hash = getattr(bd, "_signed_candidate_hash",
                          lambda t: str(t.get("rtl_sha256") or ""))
    assert signed_hash(new) == signed != new["rtl_sha256"]
    # Break exactly one binding and the frozen candidate governs again.
    for field in ("new_output_sha256", "program_version_before",
                  "input_manifest_path"):
        broken = dict(new)
        broken["program_regate"] = {**new["program_regate"], field: "x" * 64}
        assert signed_hash(broken) == new["rtl_sha256"], field
        assert any("repaired hash is stale" in r for r in
                   bd._validate_embedded_repair_provenance(broken)), field


# ── the deprecated alias ──────────────────────────────────────────────

def test_the_deprecated_alias_runs_the_merged_operation_and_says_so(
        tmp_path, monkeypatch, capsys):
    """`--program-retry` must keep WORKING, and must say it is deprecated.

    A caller written against the v1.17.71 front door does not break silently:
    the same request reaches the same merged operation, and the deprecation is
    printed on stderr rather than left for the reader to discover.
    """
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed)
    _gate(monkeypatch, _BENIGN)
    assert _resume(run, retry=request_path) == 2
    captured = capsys.readouterr()
    assert "DEPRECATED: --program-retry" in captured.err, captured.err
    assert "--program-regate" in captured.err
    applied = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert (applied.get("program_regate") or {}).get(
        "status") == "FRESH_REVIEW_REQUIRED"
    assert "PROGRAM_REGATE_APPLIED" in captured.out


def test_the_alias_and_the_name_together_are_refused_not_ordered(
        tmp_path, monkeypatch, capsys):
    """Two spellings of one operation in one resume is an ambiguous order."""
    monkeypatch.setattr(bd.sys, "argv", [
        "benchmark_dispatch.py", "rtllm", "--resume",
        "--run", str(tmp_path), "--dataset", "/unused",
        "--program-regate", str(tmp_path / "a.json"),
        "--program-retry", str(tmp_path / "b.json")])
    with pytest.raises(SystemExit) as excinfo:
        bd.main()
    assert excinfo.value.code == 2
    assert "DEPRECATED alias of --program-regate" in capsys.readouterr().err


def test_the_alias_is_declared_deprecated_in_the_help_text():
    source = Path(bd.__file__).read_text()
    assert "DEPRECATED alias of --program-regate" in source
    assert bd._program_retry_deprecation().startswith("DEPRECATED: --program-retry")


#: The version this lane's author typed while the merge was being written. The
#: branch lands under a DIFFERENT number -- landing versions are assigned at
#: landing -- so any occurrence of this literal is a forward claim the plugin
#: itself can contradict.
_GUESSED_LANDING_VERSION = "1.17." + "75"

_SKILL = (Path(bd.__file__).resolve().parents[1]
          / "skills" / "open-benchmark-methodology" / "SKILL.md")


@pytest.mark.parametrize("name", ["program", "skill"])
def test_the_removal_window_carries_no_typed_version_literal(name):
    """The deprecation window is read, not typed.

    A literal here is a claim about a version nobody has assigned yet: the
    merge's landing number is decided at landing. Both surfaces must therefore
    be free of the guess, and the program's own line must come from the
    manifest instead.
    """
    path = Path(bd.__file__) if name == "program" else _SKILL
    text = path.read_text()
    assert _GUESSED_LANDING_VERSION not in text, (
        f"{path.name} still carries the guessed landing version "
        f"{_GUESSED_LANDING_VERSION}")


def test_the_removal_window_names_the_version_the_manifest_reports():
    """Read, and read from the RIGHT place: the running plugin's manifest."""
    running = bd._program_version()
    assert running, "NOT_MEASURED: this tree's plugin manifest has no version"
    clause = bd._program_retry_removal_clause()
    assert clause == f"removed one version after v{running}", clause
    assert clause in bd._program_retry_deprecation()


def test_an_unreadable_manifest_degrades_loudly(monkeypatch):
    """"Could not read it" is never a quoted number nobody measured."""
    monkeypatch.setattr(bd, "_program_version", lambda: "")
    clause = bd._program_retry_removal_clause()
    assert "UNREADABLE from the manifest" in clause, clause
    assert not re.search(r"v\d+\.\d+\.\d+", clause), clause


def test_the_help_text_and_the_deprecation_line_cannot_disagree(capsys):
    """One clause feeds both, so they cannot name different versions."""
    monkeypatch_argv = ["benchmark_dispatch.py", "--help"]
    import contextlib                                    # noqa: PLC0415
    saved = bd.sys.argv
    bd.sys.argv = monkeypatch_argv
    try:
        with contextlib.suppress(SystemExit):
            bd.main()
    finally:
        bd.sys.argv = saved
    help_text = " ".join(capsys.readouterr().out.split())
    clause = bd._program_retry_removal_clause()
    assert clause in help_text, (clause, help_text[-400:])


# ── the merge lost nothing: membership, not counts ────────────────────

#: Every test NAME the two pre-merge modules declared, at main 12a1681dc
#: (v1.17.75): 18 from ``test_program_regate.py`` (31 collected ids) and 14
#: from ``test_program_candidate_retry.py`` (43), 74 ids in all. The names are
#: the stable ids; the collected id also carries the module path, which the
#: merge necessarily changes.
PRE_MERGE_IDS = (
    # from test_program_regate.py (v1.17.63)
    "test_a_concurrent_coordinator_refuses_the_regate",
    "test_a_fixed_program_regates_from_the_preserved_signed_input",
    "test_a_hand_edited_work_tree_cannot_be_smuggled_through_a_regate",
    "test_a_malformed_or_stale_request_is_refused",
    "test_a_missing_or_drifted_preserved_input_is_refused",
    "test_a_non_repair_candidate_cannot_be_regated",
    "test_a_program_version_that_is_not_the_running_one_is_refused",
    "test_a_regate_record_that_does_not_verify_changes_nothing",
    "test_a_symlinked_request_is_refused_without_reading_its_target",
    "test_a_verified_regate_record_is_what_binds_the_signature",
    "test_an_accepted_or_published_candidate_cannot_be_regated",
    "test_an_unchanged_program_version_is_a_loop_not_a_fix",
    "test_regate_replay_is_idempotent",
    "test_the_front_door_refuses_both_operations_in_one_resume",
    "test_the_gate_boundary_records_the_signed_input_and_its_output",
    "test_the_stale_signature_refusal_still_fires_without_a_regate_record",
    "test_the_transition_is_reconstructable_from_records_alone",
    "test_the_two_operations_are_declared_separate_at_the_front_door",
    # from test_program_candidate_retry.py (v1.17.71)
    "test_automatic_input_snapshot_matches_signed_pre_gate_bytes",
    "test_coordinator_lock_prevents_program_retry",
    "test_evidence_and_state_refusals_preserve_sources",
    "test_exact_path_and_file_mapping_preflight",
    "test_malformed_requests_refuse_without_traceback",
    "test_malformed_terminal_marker_cannot_hide_interruption",
    "test_normal_internal_links_and_declared_exit_predicate_are_preserved",
    "test_plain_resume_keeps_transformed_output_and_requires_real_final_signature",
    "test_program_retry_capture_routes_to_shared_coordinator",
    "test_retry_replaces_frozen_output_from_signed_input_then_normal_review_accepts",
    "test_staged_failure_and_interruption_are_safe",
    "test_stale_request_refuses_before_mutation",
    "test_still_transforming_program_keeps_original_final_provenance_refusal",
    "test_unchanged_program_cannot_retry_again",
)

#: The ids the merge could NOT re-point, with the collision that retired each
#: and the test that carries the retired one's CONCERN forward (the #2039
#: precedent). A retirement is a recorded decision; a deletion is not.
RETIRED = {
    "test_regate_replay_is_idempotent": {
        "collision": (
            "--program-regate (v1.17.63) replayed a request IDEMPOTENTLY: a "
            "second identical request re-verified the transition archive, "
            "printed PROGRAM_REGATE_ALREADY_APPLIED and changed nothing. "
            "--program-retry (v1.17.71) REFUSED a second round on the same "
            "request -- 'occupied retry archive' -- because its immutable "
            "intent journal has already recorded one. Both cannot hold: one "
            "reports success on a re-run, the other refuses it."),
        "resolution": (
            "The merged operation takes the RETRY side: it refuses. The "
            "re-gate's idempotence was affordable only because it restored "
            "bytes and committed no run; the merged operation RUNS the Program "
            "in a staged project and promotes, so a second round is unknown "
            "state to reconcile, never a silent already-applied report. "
            "MEASURED, and worth stating exactly because it is not the guard "
            "one would guess: a BYTE-IDENTICAL replay is answered by the "
            "staleness guard ('stale task_sha256'), because a successful "
            "re-entry rewrites the task the request was bound to; the "
            "identity guard ('Program identity has not changed since the "
            "prior re-entry') is what answers a replay RE-BOUND to the new "
            "task, and the archive guard answers a foreign occupant. The five "
            "re-gate refusals that served the replay archive -- 'invalid "
            "transition archive', 'immutable archive drift', 'immutable "
            "archive missing', 'transition evidence drift' and 'current task "
            "drift' -- are superseded by the journal guard, not dropped."),
        "concern_carried_by": "test_a_replayed_request_is_refused_not_silently_reapplied",
    },
}


def _declared_here() -> set[str]:
    import ast                                          # noqa: PLC0415
    tree = ast.parse(Path(__file__).read_text())
    return {n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test")}


def test_every_pre_merge_id_is_re_pointed_or_retired():
    """MEMBERSHIP, not counts: a dropped id is caught by name, not by memory.

    "Same number of tests" is the one summary a substitution cannot disturb,
    so this compares the NAME SETS. Every pre-merge id must be either declared
    in this module (re-pointed at the merged operation) or listed in RETIRED
    with its collision table. Nothing may be both, and nothing may be neither.
    """
    here = _declared_here()
    retired = set(RETIRED)
    unaccounted = set(PRE_MERGE_IDS) - here - retired
    assert unaccounted == set(), \
        f"pre-merge ids silently dropped by the merge: {sorted(unaccounted)}"
    assert retired & here == set(), \
        f"retired ids are still declared: {sorted(retired & here)}"
    assert retired <= set(PRE_MERGE_IDS), \
        f"RETIRED names an id that never existed: {sorted(retired - set(PRE_MERGE_IDS))}"


def test_every_retirement_states_its_collision_and_who_carries_the_concern():
    """A retirement with no collision table is a deletion with a nicer name."""
    here = _declared_here()
    for name, record in RETIRED.items():
        assert set(record) == {"collision", "resolution", "concern_carried_by"}, name
        assert len(record["collision"].split()) >= 40, name
        assert len(record["resolution"].split()) >= 40, name
        # The successor must EXIST, or the concern went nowhere.
        assert record["concern_carried_by"] in here, \
            f"{name}: concern_carried_by names no test in this module"


def test_the_two_pre_merge_modules_are_gone():
    """One operation, one test module. Their content is here, not deleted."""
    for stale in ("test_program_regate.py", "test_program_candidate_retry.py"):
        assert not (Path(__file__).parent / stale).exists(), stale


# ── the refusal census: every refuse() site of the merged operation ────
#
# `_apply_program_regate` (plus `_regate_project_tree`,
# `_guard_program_regate_journals` and `_regate_request_field`) declares 66
# refusal sites: 62 `refuse()` calls and 4 direct `raise`.  That is the
# COMPLETE population -- the file defines exactly one `def refuse`, inside the
# operation itself, so no refusal hides behind a helper the enumerator does not
# follow.  Each is confirmed by DELETING its refusal and observing this module
# go red: an unreached refusal is not a bug today, it is a refusal that stops
# refusing silently on the first change that touches it with a green suite.
#
# THE FIGURE THIS COMMENT ORIGINALLY CARRIED WAS WRONG, and how it was wrong is
# the reason to state it here rather than quietly correct it.  It read "the
# tests above reach 38 of them; the 28 below reach the rest, so the census
# closes at ZERO unreached".  That came from a mutation sweep run FOUR-WAY
# PARALLEL at host load 20-30.  Re-run SEQUENTIALLY at load ~3, six of those
# REACHED verdicts do not reproduce: the real figure was 60/66, and these six
# were pinned by nothing --
#     unsupported project file, expected a JSON object, wrong task schema,
#     project is not the runner-owned project, Phase-1 provenance drift,
#     task lacks its AI repair provenance.
# In a mutation census the usual polarity is inverted: a test failing for ANY
# reason, load flake included, scores its site REACHED.  Noise therefore does
# not raise a false alarm, it MANUFACTURES coverage -- and "0 unreached" is the
# summary everyone downstream reads.  Measure a census SEQUENTIALLY, and re-run
# a candidate REACHED alone, not only a candidate red.
#
# The six are pinned at the end of this module and each is mutation-proven
# individually.  The census is now 66/66 with 0 unreached, measured that way.
#
# Every test here asserts the refusal by its OWN MESSAGE.  This operation
# checks in a fixed order, so a test that merely asserted "something was
# refused" would pass on whichever earlier guard happened to fire and would
# keep passing after its own guard was deleted.  Asserting the message means
# the input really did travel as far as the refusal under test.


def _rebind(run, task, request, request_path, **changes):
    """Change the live task and re-bind the request's digest to it.

    Without the recomputed `task_sha256` the staleness guard at the top of the
    operation answers first and nothing below it is measured. That is the same
    trap in test form.
    """
    task = dict(task, **changes)
    bd._write_jsonl(Path(run) / bd._REVIEW_WORKLIST, [task])
    request["task_sha256"] = bd._sha256_text(
        json.dumps(task, ensure_ascii=False, sort_keys=True))
    Path(request_path).write_text(json.dumps(request))
    return task


def _rewrite(request, request_path, **changes):
    request.update(changes)
    Path(request_path).write_text(json.dumps(request))
    return request


def _stuck_request(tmp_path, monkeypatch, **over):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    path, request = _request(run, stuck, signed, **over)
    return run, stuck, signed, path, request


# --- the signed input's own shape -------------------------------------

def test_a_malformed_signed_input_hash_is_refused(tmp_path, monkeypatch, capsys):
    run, stuck, signed, path, request = _stuck_request(
        tmp_path, monkeypatch,
        signed_input_sha256="not-a-hash", input_rtl_sha256="not-a-hash")
    assert _resume(run, path) == 2
    assert "malformed signed_input_sha256" in _refusal(capsys)


def test_a_signed_input_the_gates_never_changed_has_nothing_to_re_gate(
        tmp_path, monkeypatch, capsys):
    """If the frozen output IS the signed input the author's signature is not
    stale, so there is no stuck state and no third option to take."""
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    path, _ = _request(run, stuck, signed,
                       signed_input_sha256=stuck["rtl_sha256"],
                       input_rtl_sha256=stuck["rtl_sha256"])
    assert _resume(run, path) == 2
    assert "nothing to re-gate" in _refusal(capsys)


# --- the version-pair identity ----------------------------------------

def test_an_unnamed_program_version_is_refused(tmp_path, monkeypatch, capsys):
    run, stuck, signed, path, request = _stuck_request(
        tmp_path, monkeypatch, program_version_before="")
    assert _resume(run, path) == 2
    assert "both Program versions must be named" in _refusal(capsys)


def test_an_unreadable_running_program_version_is_refused(
        tmp_path, monkeypatch, capsys):
    """"Could not read it" is not "read it and it matched": with no readable
    running version the request's `_after` cannot be checked against anything."""
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    path, _ = _request(run, stuck, signed, after="1.17.52")
    monkeypatch.setattr(bd, "_program_version", lambda: "", raising=False)
    assert _resume(run, path) == 2
    assert "the running Program version is not readable" in _refusal(capsys)


def test_a_second_re_entry_under_the_same_source_identity_is_refused(
        tmp_path, monkeypatch, capsys):
    """The message half of `test_unchanged_program_cannot_retry_again`: the
    source tree must have moved again, not merely the declared version."""
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    _gate(monkeypatch, _BENIGN)
    assert _resume(run, path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    capsys.readouterr()
    path2, _ = _request(run, new, signed,
                        before=_OLD_PROGRAM, after=_running())
    assert _resume(run, path2) == 2
    assert "Program identity has not changed since the prior re-entry" in \
        _refusal(capsys)


# --- the solve report the operation reads its authority from -----------

def test_an_unsupported_solve_acceptance_policy_is_refused(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    solve_path = run / "solve_report.json"
    solve = json.loads(solve_path.read_text())
    solve["acceptance_policy"] = {"required": False}
    solve_path.write_text(json.dumps(solve))
    assert _resume(run, path) == 2
    assert "unsupported solve acceptance policy" in _refusal(capsys)


def test_a_missing_or_unsupported_declared_exit_is_refused(
        tmp_path, monkeypatch, capsys):
    """The re-entry re-runs the ORIGINAL declared route; an exit that is not a
    flow step is not a route this operation can re-enter."""
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    _declare_exit(run, "not-a-flow-step")
    assert _resume(run, path) == 2
    assert "missing or unsupported declared exit" in _refusal(capsys)


def test_a_benchmark_with_no_bound_io_adapter_is_refused(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    assert bd.cmd_resume("not-a-benchmark", "/unused", str(run),
                         worker_threads=1, program_regate=str(path)) == 2
    assert "no bound IO adapter" in _refusal(capsys)


# --- the preserved input, in both its records --------------------------

def test_a_pre_gate_binding_that_names_another_pair_is_refused(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    binding = dict(stuck["pre_gate_input"], gate_output_sha256="0" * 64)
    _rebind(run, stuck, request, path, pre_gate_input=binding)
    assert _resume(run, path) == 2
    assert "preserved pre-gate binding does not name this task's pair" in \
        _refusal(capsys)


def _repoint_pre_gate(run, stuck, request, path, **manifest_changes):
    """Point the task's pre-gate record at a REWRITTEN manifest inside the run."""
    original = Path(stuck["pre_gate_input"]["input_manifest_path"])
    manifest = dict(json.loads(original.read_text()), **manifest_changes)
    forged = Path(run) / f"forged_manifest_{len(list(Path(run).glob('forged_*')))}.json"
    manifest["manifest_path"] = str(forged)
    forged.write_text(json.dumps(manifest))
    binding = dict(stuck["pre_gate_input"], input_manifest_path=str(forged))
    return _rebind(run, stuck, request, path, pre_gate_input=binding)


def test_a_preserved_manifest_for_another_task_is_refused(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    _repoint_pre_gate(run, stuck, request, path, id="p9")
    assert _resume(run, path) == 2
    assert "preserved input manifest does not match the request" in _refusal(capsys)


def test_a_preserved_manifest_with_no_rtl_is_refused(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    _repoint_pre_gate(run, stuck, request, path, rtl_paths=[], source_rtl_paths=[])
    assert _resume(run, path) == 2
    assert "preserved input has no RTL" in _refusal(capsys)


def test_an_internally_inconsistent_preserved_manifest_is_refused(
        tmp_path, monkeypatch, capsys):
    """One frozen file per source file, or the manifest does not describe a
    file set anyone can map back onto the work tree."""
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    original = json.loads(
        Path(stuck["pre_gate_input"]["input_manifest_path"]).read_text())
    _repoint_pre_gate(run, stuck, request, path,
                      source_rtl_paths=original["source_rtl_paths"] * 2)
    assert _resume(run, path) == 2
    assert "preserved input manifest is internally inconsistent" in _refusal(capsys)


def test_a_preserved_input_that_does_not_cover_the_work_tree_is_refused(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    original = json.loads(
        Path(stuck["pre_gate_input"]["input_manifest_path"]).read_text())
    _repoint_pre_gate(run, stuck, request, path,
                      rtl_paths=original["rtl_paths"] * 2,
                      source_rtl_paths=original["source_rtl_paths"] * 2)
    assert _resume(run, path) == 2
    assert "preserved input does not cover the working RTL file set" in _refusal(capsys)


def test_a_request_input_differing_from_the_automatic_snapshot_is_refused(
        tmp_path, monkeypatch, capsys):
    """The repair boundary preserved the input automatically. A request that
    names a DIFFERENT record -- even a well-formed one -- is asking the
    operation to re-enter from bytes nobody froze at the gate boundary."""
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    original = Path(request["input_manifest_path"])
    candidate = json.loads(original.read_text())
    copied = Path(run) / "copied_candidate_manifest.json"
    candidate["manifest_path"] = str(copied)
    copied.write_text(json.dumps(candidate))
    _rewrite(request, path, input_manifest_path=str(copied),
             input_manifest_sha256=_hash(copied))
    assert _resume(run, path) == 2
    assert "request differs from automatically preserved input" in _refusal(capsys)


# --- the inherited proof obligations ----------------------------------

def test_a_task_with_no_inherited_challenges_is_refused(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    _rebind(run, stuck, request, path, verification_challenges=[])
    assert _resume(run, path) == 2
    assert "missing inherited challenges" in _refusal(capsys)


def test_a_signed_challenge_that_is_not_inherited_is_refused(
        tmp_path, monkeypatch, capsys):
    """The test the author's repair was signed against must travel with it."""
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    provenance = dict(stuck["repair_provenance"], challenge_sha256="0" * 64)
    _rebind(run, stuck, request, path, repair_provenance=provenance)
    assert _resume(run, path) == 2
    assert "signed challenge is not inherited" in _refusal(capsys)


def test_a_drifted_signed_input_provenance_is_refused(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    provenance = dict(stuck["repair_provenance"],
                      unexpected_field="not in the validated record")
    _rebind(run, stuck, request, path, repair_provenance=provenance)
    assert _resume(run, path) == 2
    assert "signed input provenance drift" in _refusal(capsys)


# --- the bound current review/test ------------------------------------

def test_a_current_review_that_is_not_exactly_bound_is_refused(
        tmp_path, monkeypatch, capsys):
    run, old, path, request, state = _case(tmp_path, monkeypatch, reviewed=True)
    _rewrite(request, path, review_sha256="0" * 64)
    assert _resume(run, path) == 2
    assert "current review/test is not exactly bound" in _refusal(capsys)


def test_an_invalid_current_challenge_is_refused(tmp_path, monkeypatch, capsys):
    """The proof being carried forward has to be a well-formed one; its own
    validation reasons are quoted rather than replaced by a summary."""
    run, old, path, request, state = _case(tmp_path, monkeypatch, reviewed=True)
    review = json.loads(Path(old["review_path"]).read_text())
    review["verification_test"]["rationale"] = "too short to explain anything"
    raw = json.dumps(review)
    Path(old["review_path"]).write_text(raw)
    _rewrite(request, path, review_sha256=bd._sha256_text(raw))
    assert _resume(run, path) == 2
    assert "invalid current challenge" in _refusal(capsys)


def test_a_request_binding_a_review_that_does_not_exist_is_refused(
        tmp_path, monkeypatch, capsys):
    """The stuck task has no current review. A request that binds one is
    describing evidence that is not there -- never treated as "no review"."""
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    assert not Path(stuck["review_path"]).exists()
    path, _ = _request(run, stuck, signed, review_sha256="0" * 64)
    assert _resume(run, path) == 2
    assert "bound current review/test is missing" in _refusal(capsys)


# --- occupied destinations --------------------------------------------

def test_an_occupied_re_entry_archive_is_refused(tmp_path, monkeypatch, capsys):
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    archive = (run / "program_regates" / "p1" / bd._sha256_text(path.read_text()))
    archive.mkdir(parents=True)
    assert _resume(run, path) == 2
    assert "occupied re-entry archive or fresh review/test path" in _refusal(capsys)


def test_a_task_that_also_has_a_pending_ai_backup_is_refused(
        tmp_path, monkeypatch, capsys):
    """Two open routes for one task is the ambiguity this operation refuses to
    resolve on the owner's behalf."""
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    bd._write_jsonl(run / bd._BACKUP_WORKLIST, [{"id": "p1"}])
    assert _resume(run, path) == 2
    assert "task also has a pending AI backup" in _refusal(capsys)


# --- the staged re-run, and the windows around its promotion ----------
#
# The last six refusals guard the staged run and the two TOCTOU windows around
# promotion.  A window guard is only reachable by something changing state
# INSIDE the window, so these model exactly that -- a concurrent writer, or a
# staged copy that did not come out as the signed input.  That is what the
# refusal is for; reaching it any other way would not be reaching it.

def _candidate_root(run, request_path, staged):
    """The fresh snapshot path the operation is about to claim."""
    key = "program-regate-" + bd._sha256_text(Path(request_path).read_text())
    got = fx.bio.collect("rtllm", "p1", Path(staged), supplied_rtl=True)
    return (Path(run) / "candidate_snapshots" / "p1"
            / f"{key}-{bd._sha256_text(str(got.get('completion') or ''))}")


def test_a_staged_copy_that_is_not_the_signed_input_is_refused(
        tmp_path, monkeypatch, capsys):
    """The whole operation is "re-run the Program on the bytes the author
    signed". If the staged tree does not hash to those bytes, whatever is
    about to be re-run is not the signed input."""
    run, old, path, request, state = _case(tmp_path, monkeypatch)
    real = bd._atomic_write_text

    def corrupt(target, text):
        if "staged_project" in str(target):
            text = text + "\n// a concurrent writer\n"
        return real(target, text)

    monkeypatch.setattr(bd, "_atomic_write_text", corrupt)
    before = _protected(run, old)
    assert _resume(run, path) == 2
    assert "staged work tree does not hash to the signed input" in _refusal(capsys)
    assert _protected(run, old) == before
    assert state["calls"] == []


def test_a_program_that_rewrites_the_bound_prompt_is_refused(
        tmp_path, monkeypatch, capsys):
    """The prompt and the Phase-1 inputs are the DESIGN INPUT. A Program that
    edits them has changed the question, not answered it."""
    run, old, path, request, state = _case(tmp_path, monkeypatch)

    def rewrite_prompt(staged):
        (staged / "input" / "phase1_prompt.md").write_text("a different design\n")

    state["on_run"] = rewrite_prompt
    before = _protected(run, old)
    assert _resume(run, path) == 2
    assert "Program changed bound prompt or Phase-1 inputs" in _refusal(capsys)
    assert _protected(run, old) == before


def test_an_occupied_fresh_candidate_snapshot_is_refused(
        tmp_path, monkeypatch, capsys):
    run, old, path, request, state = _case(tmp_path, monkeypatch)

    def occupy(staged):
        _candidate_root(run, path, staged).mkdir(parents=True, exist_ok=True)

    state["on_run"] = occupy
    before = _protected(run, old)
    assert _resume(run, path) == 2
    assert "occupied fresh candidate snapshot" in _refusal(capsys)
    assert _protected(run, old) == before


def test_a_publication_appearing_during_preparation_is_refused(
        tmp_path, monkeypatch, capsys):
    """The candidate was unpublished when the operation started. If it is
    published while the Program runs, promoting over it would silently
    supersede a published result."""
    run, old, path, request, state = _case(tmp_path, monkeypatch)

    def publish(_):
        response = Path(old["response_path"])
        response.parent.mkdir(parents=True, exist_ok=True)
        response.write_text("published by someone else")

    state["on_run"] = publish
    assert _resume(run, path) == 2
    assert "publication or fresh review/test path occupied during preparation" \
        in _refusal(capsys)
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0] == old


def test_a_staged_output_changing_while_promotion_is_prepared_is_refused(
        tmp_path, monkeypatch, capsys):
    """Between freezing the staged output and promoting a copy of it, the two
    must still be the same tree -- otherwise what gets promoted is not what
    was gated."""
    run, old, path, request, state = _case(tmp_path, monkeypatch)
    real = bd.shutil.copytree

    def copy_then_disturb(*args, **kwargs):
        # shutil recurses into copytree positionally, so take *args and act
        # only on OUR call, identified by the promotion copy's target name.
        result = real(*args, **kwargs)
        source, target = args[0], args[1]
        if Path(target).name == "promotion_project":
            (Path(source) / "phase2/stage1/rtl/dut.v").write_text(
                "module dut(); endmodule\n")
        return result

    monkeypatch.setattr(bd.shutil, "copytree", copy_then_disturb)
    before = _protected(run, old)
    assert _resume(run, path) == 2
    assert "staged output changed while preparing promotion" in _refusal(capsys)
    assert _protected(run, old) == before


def test_a_candidate_snapshot_claimed_during_preparation_is_refused(
        tmp_path, monkeypatch, capsys):
    """The snapshot path was free when it was first checked. Claiming it in
    the window before promotion must refuse, not overwrite."""
    run, old, path, request, state = _case(tmp_path, monkeypatch)
    real = bd.shutil.copytree

    def copy_then_claim(*args, **kwargs):
        # shutil recurses into copytree positionally, so take *args and act
        # only on OUR call, identified by the promotion copy's target name.
        result = real(*args, **kwargs)
        source, target = args[0], args[1]
        if Path(target).name == "promotion_project":
            _candidate_root(run, path, source).mkdir(parents=True, exist_ok=True)
        return result

    monkeypatch.setattr(bd.shutil, "copytree", copy_then_claim)
    before = _protected(run, old)
    assert _resume(run, path) == 2
    assert "fresh candidate snapshot occupied during preparation" in _refusal(capsys)
    assert _protected(run, old) == before


def test_a_task_missing_a_candidate_snapshot_is_refused(
        tmp_path, monkeypatch, capsys):
    """Three immutable candidate snapshots are read before anything is staged.
    An absent one is refused by NAME, not answered by the record validator's
    "candidate snapshot is absent" further in -- the operation must not get as
    far as validating a record that is not there."""
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    _rebind(run, stuck, request, path, program_candidate_snapshot=None)
    assert _resume(run, path) == 2
    assert "missing candidate snapshot" in _refusal(capsys)


def test_a_bound_source_changing_during_preparation_is_refused(
        tmp_path, monkeypatch, capsys):
    """The message half of `test_staged_failure_and_interruption_are_safe
    [source_drift]`: every file the operation bound is re-hashed before the
    one authoritative commit, and the refusal NAMES the file that moved."""
    run, old, path, request, state = _case(tmp_path, monkeypatch)
    working = Path(old["working_rtl_paths"][0])
    state["on_run"] = lambda _: working.write_text("owner edit during the run\n")
    assert _resume(run, path) == 2
    err = _refusal(capsys)
    assert "source changed during preparation" in err
    assert str(working) in err, err
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0] == old


# ── the six refusals a PARALLEL census wrongly reported as reached ─────
#
# The original mutation sweep ran 4-way parallel at load 20-30 and reported
# 66/66 sites reached. Re-run SEQUENTIALLY at load ~3 on the landed tree, six
# of those verdicts do not reproduce: the sites below are reached by no test.
# The brief's rule -- re-run a candidate red ALONE at low load -- had been
# applied to the UNREACHED direction only, and a false REACHED is just as
# damaging: it closes the census on a refusal nothing pins.
#
# Independently corroborated: these six are also exactly the sites whose
# message no test names, found by a separate ast scan of the module's string
# literals. Two methods, one answer.

def test_a_request_that_is_not_a_json_object_is_refused(
        tmp_path, monkeypatch, capsys):
    """A JSON list parses fine and has no fields. Deleting this refusal lets it
    through to an AttributeError, which the front door reports as "malformed
    evidence" -- still rc=2, still state-preserving, so a test that asserted
    only those would never notice."""
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    path.write_text(json.dumps(["not", "an", "object"]))
    assert _resume(run, path) == 2
    assert "expected a JSON object" in _refusal(capsys)


def test_a_task_with_the_wrong_schema_is_refused(tmp_path, monkeypatch, capsys):
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    _rebind(run, stuck, request, path, schema="vibeic.benchmark.review_task.v0")
    assert _resume(run, path) == 2
    assert "wrong task schema" in _refusal(capsys)


def test_a_task_without_its_repair_provenance_is_refused(
        tmp_path, monkeypatch, capsys):
    """The signed input's provenance is what the whole operation is about; a
    task that carries none has nothing to re-enter FROM."""
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    _rebind(run, stuck, request, path, repair_provenance=None)
    assert _resume(run, path) == 2
    assert "task lacks its AI repair provenance" in _refusal(capsys)


def test_a_project_that_is_not_the_runner_owned_one_is_refused(
        tmp_path, monkeypatch, capsys):
    """The operation re-runs the Program over the RUNNER's project. A task
    pointing at some other directory -- even one inside the run -- is naming a
    tree whose contents nothing in this run vouches for."""
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    elsewhere = Path(run) / "not_the_project"
    elsewhere.mkdir()
    _rebind(run, stuck, request, path, project=str(elsewhere))
    assert _resume(run, path) == 2
    assert "project is not the runner-owned project" in _refusal(capsys)


def test_drifted_phase1_provenance_is_refused(tmp_path, monkeypatch, capsys):
    """The prompt is bound separately; this is the REST of the Phase-1 input.
    A task whose recorded provenance no longer describes the project is
    describing a different design."""
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    _rebind(run, stuck, request, path,
            phase1_provenance={"schema": "forged", "inputs": []})
    assert _resume(run, path) == 2
    assert "Phase-1 provenance drift" in _refusal(capsys)


def test_a_project_holding_an_unsupported_file_kind_is_refused(
        tmp_path, monkeypatch, capsys):
    """The project tree is bound file by file. Something that is neither a
    regular file, a directory nor a symlink cannot be hashed, and a tree that
    cannot be hashed cannot be compared before and after the run."""
    run, stuck, signed, path, request = _stuck_request(tmp_path, monkeypatch)
    os.mkfifo(Path(stuck["project"]) / "a_named_pipe")
    assert _resume(run, path) == 2
    assert "unsupported project file" in _refusal(capsys)
