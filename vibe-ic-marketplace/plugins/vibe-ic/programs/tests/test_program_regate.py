"""A fixed Program re-enters from the preserved signed input, never by re-signing.

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
"""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_benchmark_program_first_ai_review as fixtures

bd = fixtures.bd
bio = fixtures.bio

_SIGNED_RTL = "module dut(input wire a, output wire y); assign y = a; endmodule\n"
# The UNWANTED transform: the alias step added an unsolicited public reset
# port the author never asked for.  Different bytes, different frozen hash.
_UNWANTED = ("module dut(input wire a, input wire rst_n, output wire y); "
             "assign y = a; endmodule\n")
# A benign normalization a FIXED Program may still legitimately apply. It is
# semantically identical and produces a THIRD distinct hash, so the author's
# signature genuinely cannot cover it.
_BENIGN = "module dut(input wire a, output wire y);\n  assign y = a;\nendmodule\n"


def _running() -> str:
    """The running Program version; "" where the pre-fix tree has none."""
    return str(getattr(bd, "_program_version", lambda: "")())


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _has_regate() -> bool:
    return "program_regate" in inspect.signature(bd.cmd_resume).parameters


def _resume(run, *, regate=None):
    """Run the REAL resume entry; pass the operation only where it exists.

    The pre-fix control therefore runs the same real coordinator and is graded
    on the state it leaves behind, not on a missing attribute.
    """
    kwargs = {"program_regate": str(regate)} if (regate and _has_regate()) else {}
    return bd.cmd_resume("rtllm", "/unused", str(run), **kwargs)


def _gate(monkeypatch, produce: str):
    """Model the PROGRAM gates: normalize the work tree, then report PASS."""
    real_run = bd.subprocess.run
    seen: list = []

    def fake_run(argv, *args, **kwargs):
        joined = " ".join(str(v) for v in argv)
        if "vibe_ic_one_shot_runner.py" not in joined:
            return real_run(argv, *args, **kwargs)
        seen.append(argv)
        project = next(Path(str(v)) for v in argv if "projects" in str(v))
        (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(produce)
        report = project / "reports" / "orchestrator" / "phase2_one_shot.json"
        report.write_text(json.dumps({
            "verdict": "PASS",
            "steps": [{"name": "rtl_gen", "status": "SKIPPED-BY-ENTRY",
                       "detail": "run declared --entry-step 2"}],
        }))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    return seen


_OLD_PROGRAM = "1.17.49"
_NEW_PROGRAM = "1.17.52"


def _stuck(tmp_path, monkeypatch):
    """The exact stuck state: signed input, unwanted gate output, stale sig.

    The whole stuck state is produced while the OLD Program is running, so the
    preserved input records the version that actually made the unwanted bytes
    and the later re-entry has a real version delta to name.
    """
    monkeypatch.setattr(bd, "_program_version", lambda: _OLD_PROGRAM,
                        raising=False)
    run, task, _ = fixtures._task(tmp_path)
    project = Path(task["project"])
    working = project / "phase2" / "stage1" / "rtl" / "dut.v"
    working.write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task("p1", project, got, fixtures.ROUTING, 0,
                                   run, "PROGRAM")
    fixtures._solve_report(run, task)
    fixtures._write_review(task, fixtures._proven_fail_review(task))
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert bd._read_jsonl(run / bd._REPAIR_WORKLIST)[0]["status"] == \
        "AI_SEMANTIC_REPAIR_REQUIRED"

    # The author authors and SIGNS exactly these bytes.
    working.write_text(_SIGNED_RTL)
    signed = bd._sha256_text(bd._candidate_text(bd._rtl_files(project)))
    fixtures._write_ai_repair_record(
        run, task, bd._validate_ai_review(task)["verified_challenge"])
    record_path = bd._repair_record_path(run, task)
    signed_record = record_path.read_bytes()

    # The gates normalize those bytes into something the author never signed.
    _gate(monkeypatch, _UNWANTED)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    stuck = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
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
        "program_version_before": before,
        "program_version_after": after or _running(),
        "author": {"kind": "AI", "model": "independent-test-reviewer"},
        "blind": {"oracle_accessed": False},
        "rationale": (
            "The deterministic alias step added an unsolicited public reset "
            "port to the signed candidate before freezing it; that transform "
            "is fixed, so re-enter the fixed Program from the preserved input."),
    }
    request.update(over)
    path = Path(run) / f"regate_request_{len(list(Path(run).glob('regate_*')))}.json"
    path.write_text(json.dumps(request))
    return path, request


# ── the stuck state itself, and the refusal that must NOT be weakened ──

@fixtures._NEEDS_SIMULATOR
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


@fixtures._NEEDS_SIMULATOR
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
    fixtures._write_review(stuck, fixtures._valid_review(stuck))
    assert bd._validate_ai_review(stuck)["status"] == "REJECTED"


# ── the happy path ────────────────────────────────────────────────────

@fixtures._NEEDS_SIMULATOR
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

    assert _resume(run, regate=request_path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    regate = new.get("program_regate") or {}

    # A NEW output, from the preserved input, by the FIXED Program.
    assert new["rtl_sha256"] != stale
    assert (new["rtl_sha256"] != signed) is third_hash
    assert regate.get("new_output_sha256") == new["rtl_sha256"]
    assert regate.get("stale_output_sha256") == stale
    assert regate.get("signed_input_sha256") == signed
    assert regate.get("status") == "FRESH_REVIEW_REQUIRED"

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
    assert [c["sha256"] for c in new["verification_challenges"]] == \
        [c["sha256"] for c in stuck["verification_challenges"]]
    assert "PROGRAM_REGATE_APPLIED" in capsys.readouterr().out


@fixtures._NEEDS_SIMULATOR
def test_the_transition_is_reconstructable_from_records_alone(
        tmp_path, monkeypatch):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, request = _request(run, stuck, signed)
    _gate(monkeypatch, _BENIGN)
    assert _resume(run, regate=request_path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    regate = new.get("program_regate") or {}
    assert regate.get("archive_path"), "no re-entry was recorded on the task"
    archive = Path(regate["archive_path"])
    transition = json.loads((archive / "transition.json").read_text())
    assert json.loads((archive / "request.json").read_text()) == request
    assert transition["prior_task"] == stuck
    assert (archive / "prior_gate_output_manifest.json").exists()
    # Program version before/after, input sha, stale sha, new sha, signature.
    assert transition["new_task"]["program_regate"][
        "program_version_before"] == request["program_version_before"]
    assert transition["new_task"]["program_regate"][
        "program_version_after"] == _running()
    assert transition["prior_task"]["rtl_sha256"] == request[
        "stale_output_sha256"]
    assert transition["prior_task"]["repair_provenance"][
        "repaired_rtl_sha256"] == signed


@fixtures._NEEDS_SIMULATOR
def test_regate_replay_is_idempotent(tmp_path, monkeypatch, capsys):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed)
    _gate(monkeypatch, _BENIGN)
    assert _resume(run, regate=request_path) == 2
    first = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    capsys.readouterr()
    assert _resume(run, regate=request_path) == 2
    assert "PROGRAM_REGATE_" in capsys.readouterr().out
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]["rtl_sha256"] == \
        first["rtl_sha256"]


# ── the refusals ──────────────────────────────────────────────────────

def _refusal(capsys):
    err = capsys.readouterr().err
    assert "PROGRAM_REGATE_REFUSED" in err, err
    return err


@fixtures._NEEDS_SIMULATOR
@pytest.mark.parametrize("field, value, needle", [
    ("schema", "vibeic.benchmark.program_regate.v2", "wrong request schema"),
    ("id", "p9", "missing or duplicate task id"),
    ("task_sha256", "0" * 64, "stale task_sha256"),
    ("prompt_sha256", "0" * 64, "stale prompt_sha256"),
    ("stale_output_sha256", "0" * 64, "stale stale_output_sha256"),
    ("signed_input_sha256", "0" * 64, "not the hash the author signed"),
    ("author", {"kind": "HUMAN", "model": "x"}, "attributed blind AI"),
    ("blind", {"oracle_accessed": True}, "attributed blind AI"),
    ("rationale", "too short", "rationale needs 80 characters"),
])
def test_a_malformed_or_stale_request_is_refused(
        tmp_path, monkeypatch, capsys, field, value, needle):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed, **{field: value})
    before = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    assert _resume(run, regate=request_path) == 2
    assert needle in _refusal(capsys)
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST) == before


@fixtures._NEEDS_SIMULATOR
def test_an_unchanged_program_version_is_a_loop_not_a_fix(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    same = _running()
    request_path, _ = _request(run, stuck, signed, before=same, after=same)
    before = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    assert _resume(run, regate=request_path) == 2
    assert "is a loop, not a fix" in _refusal(capsys)
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST) == before


@fixtures._NEEDS_SIMULATOR
def test_a_program_version_that_is_not_the_running_one_is_refused(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed, after="99.99.99")
    assert _resume(run, regate=request_path) == 2
    assert "is not the running Program" in _refusal(capsys)


@fixtures._NEEDS_SIMULATOR
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
    assert _resume(run, regate=request_path) == 2
    assert needle in _refusal(capsys)


@fixtures._NEEDS_SIMULATOR
def test_a_hand_edited_work_tree_cannot_be_smuggled_through_a_regate(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed)
    working = Path(stuck["working_rtl_paths"][0])
    working.write_text(
        "module dut(input wire a, output wire y); assign y = 1'b0; endmodule\n")
    assert _resume(run, regate=request_path) == 2
    assert "working RTL drifted from the frozen gate output" in _refusal(capsys)


@fixtures._NEEDS_SIMULATOR
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
    assert _resume(run, regate=request_path) == 2
    assert needle in _refusal(capsys)


@fixtures._NEEDS_SIMULATOR
def test_a_concurrent_coordinator_refuses_the_regate(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed)
    before = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    with bd._run_root_coordinator_lock(Path(run), "solve"):
        assert _resume(run, regate=request_path) == 2
        assert bd._read_jsonl(run / bd._REVIEW_WORKLIST) == before
    # The lock DELAYS the operation; it does not permanently refuse it. The
    # identical request applies once the other coordinator lets go -- which is
    # what makes the assertion above a statement about the lock.
    _gate(monkeypatch, _BENIGN)
    assert _resume(run, regate=request_path) == 2
    applied = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert (applied.get("program_regate") or {}).get(
        "status") == "FRESH_REVIEW_REQUIRED"
    assert applied["rtl_sha256"] != before[0]["rtl_sha256"]


@fixtures._NEEDS_SIMULATOR
def test_a_non_repair_candidate_cannot_be_regated(
        tmp_path, monkeypatch, capsys):
    run, task, _ = fixtures._task(tmp_path)
    fixtures._solve_report(run, task)
    fixtures._write_review(task, fixtures._valid_review(task))
    request_path, _ = _request(run, task, "a" * 64)
    assert _resume(run, regate=request_path) == 2
    assert "only an AI_REPAIR candidate can be re-gated" in _refusal(capsys)


@fixtures._NEEDS_SIMULATOR
def test_a_symlinked_request_is_refused_without_reading_its_target(
        tmp_path, monkeypatch, capsys):
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed)
    link = Path(run) / "linked_request.json"
    link.symlink_to(request_path)
    assert _resume(run, regate=link) == 2
    assert "symlink path" in _refusal(capsys)


# ── the operation stays separate from every other permit ──────────────

def test_the_two_operations_are_declared_separate_at_the_front_door():
    """`--program-regate` is its own operation, not a mode of the sibling."""
    source = Path(bd.__file__).read_text()
    assert "--program-regate" in source
    assert "--program-regate and --review-correction are separate" in source
    assert "--program-regate requires --resume alone" in source


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


@fixtures._NEEDS_SIMULATOR
def test_a_verified_regate_record_is_what_binds_the_signature(
        tmp_path, monkeypatch):
    """The positive half of the pair above, against real preserved bytes."""
    run, stuck, signed, _, _ = _stuck(tmp_path, monkeypatch)
    request_path, _ = _request(run, stuck, signed)
    _gate(monkeypatch, _BENIGN)
    assert _resume(run, regate=request_path) == 2
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
