"""The local hygiene DAG must be faster without becoming a smaller gate."""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import sys
import time
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
spec = importlib.util.spec_from_file_location(
    "_repo_hygiene_parallel", PROGRAMS / "repo_hygiene_parallel.py")
assert spec and spec.loader
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

host_spec = importlib.util.spec_from_file_location(
    "_host_independence_pipeline",
    PROGRAMS / "gate_host_independence_check.py")
assert host_spec and host_spec.loader
H = importlib.util.module_from_spec(host_spec)
host_spec.loader.exec_module(H)
from gate_process_attestation import process_attestation


def gate(label, state):
    return {"label": label, "state": state, "seconds": 1,
            "exempt_until": None, "exempt_reason": None,
            "exemption_expired": False}


def fixture():
    reference = {
        "gates": [gate("ordinary", "LISTED"),
                  gate(P.HOST_LABEL, "LISTED")],
        "corpora": [], "undisclosed_loops": [], "today": "2026-08-16",
    }
    a = {"listed_only": False, "shard": "0/2", "gates": [
        gate("ordinary", "PASS"), gate(P.HOST_LABEL, "OTHER_SHARD")],
         "corpora": [], "undisclosed_loops": [], "today": "2026-08-16",
         "wiring_errors": []}
    b = {"listed_only": False, "shard": "1/2", "gates": [
        gate("ordinary", "OTHER_SHARD"), gate(P.HOST_LABEL, "PASS")],
         "corpora": [], "undisclosed_loops": [], "today": "2026-08-16",
         "wiring_errors": []}
    attest = [{"label": "ordinary", "complete": True},
              {"label": P.HOST_LABEL, "complete": True}]
    return reference, a, b, attest


def test_complete_dag_preserves_full_dispatch_summary():
    reference, a, b, attest = fixture()
    problems = []
    doc = P.merge_records(reference, [(Path("a"), a), (Path("b"), b)],
                          attest, 12, problems)
    assert problems == []
    assert doc["declared"] == doc["decided"] == doc["passed"] == 2
    assert doc["other_shard"] == 0
    assert doc["parallel"]["complete"] is True
    assert P._summary_rc(doc) == 0
    assert P._completion_message(doc, 12).startswith("[PASS]")


def test_complete_coverage_with_a_red_gate_is_reported_as_fail():
    reference, a, b, attest = fixture()
    a["gates"][0] = gate("ordinary", "FAIL")
    problems = []
    doc = P.merge_records(reference, [(Path("a"), a), (Path("b"), b)],
                          attest, 12, problems)
    assert problems == []
    assert P._summary_rc(doc) == 1
    assert P._completion_message(doc, 12).startswith("[FAIL]")
    assert "failed=1" in P._completion_message(doc, 12)


def test_missing_shard_gate_is_named_and_refused():
    reference, a, _, attest = fixture()
    problems = []
    doc = P.merge_records(reference, [(Path("a"), a)], attest, 12, problems)
    assert any(P.HOST_LABEL in problem for problem in problems)
    assert doc["parallel"]["complete"] is False
    assert P._summary_rc(doc) == 2


def test_duplicate_owner_is_named_and_refused():
    reference, a, b, attest = fixture()
    duplicate = dict(b)
    duplicate["gates"] = [gate("ordinary", "PASS"),
                          gate(P.HOST_LABEL, "PASS")]
    problems = []
    doc = P.merge_records(reference,
                          [(Path("a"), a), (Path("b"), duplicate)],
                          attest, 12, problems)
    assert any("ordinary" in problem and "got 2" in problem
               for problem in problems)
    assert P._summary_rc(doc) == 2


def test_missing_process_attestation_cannot_become_green():
    reference, a, b, attest = fixture()
    problems = []
    doc = P.merge_records(reference, [(Path("a"), a), (Path("b"), b)],
                          attest[:1], 12, problems)
    assert any(P.HOST_LABEL in problem and "attestation" in problem
               for problem in problems)
    assert P._summary_rc(doc) == 2


def test_empty_corpus_record_needs_one_owner_but_no_process_attestation():
    """A measured empty expansion is evidence, not an invented process.

    The dispatcher owns the synthetic NOT_CHECKED row.  It must be covered by
    exactly one shard, while the process ledger must remain silent because no
    checker process ran.  Treating absence of that impossible process as loss
    made every post-split landing refuse before host comparison could start.
    """
    empty = 'corpus "published cells" is EMPTY — nothing was checked over it'
    empty_ref = gate(empty, "NOT_CHECKED")
    empty_ref.update(corpus="published cells", corpus_item=0, corpus_items=0,
                     execution="PRECOMPUTED_CORPUS",
                     reason_code="EMPTY_CORPUS")
    reference, a, b, attest = fixture()
    reference["gates"].insert(1, empty_ref)
    reference["corpora"] = [{"name": "published cells", "items": 0,
                              "gates": 1, "expansion": "EXPANDED"}]
    a_empty = dict(empty_ref)
    a_empty["state"] = "NOT_CHECKED"
    b_empty = dict(empty_ref)
    b_empty["state"] = "OTHER_SHARD"
    a["gates"].insert(1, a_empty)
    b["gates"].insert(1, b_empty)
    a["corpora"] = b["corpora"] = reference["corpora"]

    problems = []
    doc = P.merge_records(reference, [(Path("a"), a), (Path("b"), b)],
                          attest, 12, problems)
    assert problems == [], problems
    assert doc["gates"][1]["state"] == "NOT_CHECKED"
    assert not any(row.get("label") == empty
                   for row in doc["process_attestations"])
    assert doc["parallel"]["complete"] is True
    assert doc["not_checked_unexempted"] == [empty]
    assert P._summary_rc(doc) == 2


def test_precomputed_corpus_evidence_must_match_between_arms():
    empty = 'corpus "published cells" is EMPTY — nothing was checked over it'
    template = gate(empty, "LISTED")
    template.update(corpus="published cells", corpus_item=0, corpus_items=0,
                    execution="PRECOMPUTED_CORPUS",
                    reason_code="EMPTY_CORPUS")
    reference = {"gates": [template]}
    a_row = dict(template, state="NOT_CHECKED")
    b_row = dict(a_row, reason_code="DIFFERENT")
    a = [(Path("a"), {"gates": [a_row]})]
    b = [(Path("b"), {"gates": [b_row]})]
    problems = []
    a_record = P._precomputed_arm_records(reference, a, "A", problems)
    b_record = P._precomputed_arm_records(reference, b, "B", problems)
    if a_record != b_record:
        problems.append("Arm A/B precomputed corpus records differ")
    assert any("reason_code differs" in problem for problem in problems)
    assert any("Arm A/B" in problem for problem in problems)


def test_worker_waits_for_completion_while_progress_events_keep_advancing(
        tmp_path, monkeypatch):
    """A slow run is not killed for exceeding an estimated runtime.

    It emits no stdout; only the owner progress file advances.  The total run
    intentionally lasts several stall windows, proving each measured event
    resets supervision until the process exits naturally.
    """
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.05)
    progress = tmp_path / "live.jsonl"
    child = (
        "import pathlib,sys,time\n"
        "p=pathlib.Path(sys.argv[1])\n"
        "for i in range(8):\n"
        " p.open('a').write(str(i)+'\\n')\n"
        " time.sleep(0.12)\n"
    )
    started = time.monotonic()
    rc, out, problem = P._run(
        [sys.executable, "-c", child, str(progress)], tmp_path,
        os.environ.copy(), progress_path=progress, stall_grace_s=0.3)
    assert time.monotonic() - started > 0.8
    assert (rc, problem) == (0, None), (rc, out, problem)
    assert progress.read_text().splitlines()[-1] == "7"


def test_worker_classifies_silent_idle_process_as_stalled_not_timed_out(
        tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.05)
    rc, out, problem = P._run(
        [sys.executable, "-c", "import time; time.sleep(30)"], tmp_path,
        os.environ.copy(), stall_grace_s=0.3)
    assert rc == P._wd.RC_STALLED
    assert "WATCHDOG_STALLED" in out
    assert problem and "outcome=stalled" in problem


def test_stall_kills_a_term_ignoring_descendant_not_only_its_wrapper(
        tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.05)
    grandchild = (
        "import os,signal,time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('GRANDCHILD='+str(os.getpid()), flush=True)\n"
        "time.sleep(30)\n"
    )
    parent = (
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
        "time.sleep(30)\n"
    )
    rc, out, problem = P._run(
        [sys.executable, "-c", parent], tmp_path, os.environ.copy(),
        stall_grace_s=0.3)
    assert rc == P._wd.RC_STALLED and problem, (rc, out, problem)
    line = next(line for line in out.splitlines()
                if line.startswith("GRANDCHILD="))
    child_pid = int(line.split("=", 1)[1])
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        os.kill(child_pid, signal.SIGKILL)
        raise AssertionError(f"TERM-ignoring descendant {child_pid} survived")


def _attest(path: Path, output: str = "[PASS] same"):
    row = process_attestation("ordinary", output, 0, ["python3", "gate.py"])
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def test_pipelined_host_comparison_accepts_matching_machine_records(
        tmp_path, monkeypatch):
    monkeypatch.setattr(H, "corpus_gates", lambda _script: [
        H.Gate("ordinary", "$ROOT", "python3 gate.py", None)])
    monkeypatch.setattr(H, "checkout_dirt", lambda _root, _timeout:
                        H.Dirt([], ["?? stimulus"], [], True))
    monkeypatch.setattr(H, "inert_exclusions", lambda _script: [])
    monkeypatch.setattr(H, "sweep_abandoned_scratch", lambda _root: {})
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _attest(a)
    _attest(b)
    result = H.precomputed_audit(tmp_path, a, b)
    assert result.verdict == "PASS"
    assert result.declared == result.probed == 1


def test_pipelined_host_comparison_refuses_a_semantic_mismatch(
        tmp_path, monkeypatch):
    monkeypatch.setattr(H, "corpus_gates", lambda _script: [
        H.Gate("ordinary", "$ROOT", "python3 gate.py", None)])
    monkeypatch.setattr(H, "checkout_dirt", lambda _root, _timeout:
                        H.Dirt([], ["?? stimulus"], [], True))
    monkeypatch.setattr(H, "inert_exclusions", lambda _script: [])
    monkeypatch.setattr(H, "sweep_abandoned_scratch", lambda _root: {})
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _attest(a, "[PASS] same")
    _attest(b, "[FAIL] changed")
    result = H.precomputed_audit(tmp_path, a, b)
    assert result.verdict == "FAIL"
    assert result.findings[0]["kind"] == "HOST_OR_NONDETERMINISTIC_VERDICT"
