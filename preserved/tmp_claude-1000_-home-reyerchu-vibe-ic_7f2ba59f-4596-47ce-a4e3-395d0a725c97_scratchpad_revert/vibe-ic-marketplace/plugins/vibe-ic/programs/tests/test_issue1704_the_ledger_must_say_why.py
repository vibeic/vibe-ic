"""vibe-ic#1704 — the withdrawal ledger recorded WHAT left and never WHY.

THE MEASUREMENT THAT OPENED THE ISSUE. The published corpus moved to its own
repository in v1.10.56, and pointing the suite at a clone of it
(`VIBE_IC_BENCHMARK_DATA=<clone>`) made the recorded register say so::

    the ratchet baseline cites 3 run tree(s) that are not in the corpus
    recorded findings_total=22 but the corpus now carries 1
    recorded denominator (16, 16) != live (4, 4)

The register was not wrong to be red. What it could not do — with or without a
corpus — is say why the numbers moved. `withdrawn_unexamined` (vibe-ic#1202)
already refuses to let a fall be read as debt somebody paid: it names WHICH
runs left the swept population and how many findings went with them. It cannot
distinguish

    nine run trees a publishing filter declined to carry   debt that moved
    nine run trees deleted because somebody judged them    work
    settled

and both spell `22 -> 1`. The second reading lowers a shrink-only bar
permanently on a decision nobody stated, and a bar that comes down never goes
back up.

WHY A MECHANISM AND NOT ONLY THE DATA. Re-deriving today's baseline fixes
today's number and nothing else; the next withdrawal re-opens the same gap in
silence. That argument is this repo's own — the module one file over makes it
about the number, and this makes it about the reason.

WHY EVERY PROPERTY BELOW IS BIDIRECTIONAL. A writer that refused every shrink
would satisfy the first case here and destroy the gate: a ban is easy to
mistake for rigour. So each refusal is asserted beside the write it must NOT
obstruct — a re-record that withdraws nothing new is never asked to renew
anything, and a legitimate reason produces a green register on both read paths.

NOTHING HERE TOUCHES THE REPO'S BASELINE OR CORPUS, with one deliberate
exception: the last case reads the SHIPPED register through the shipped
validator, because a rule whose only subject is a fixture is a rule the
repository has not adopted.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN_ROOT / "programs"
GATE = PROGRAMS / "step_internal_fail_bubble_up_check.py"
SHIPPED_BASELINE = PROGRAMS / "step_internal_fail_bubble_up_baseline.json"

#: vibe-ic#1241 — bounded well under the session timeout so a hang fails ONE
#: case instead of killing the run. MEASURED: the slowest case here builds two
#: run trees and makes four gate calls, well under a second of wall time.
_GATE_TIMEOUT_S = 60

#: Long enough to clear `WITHDRAWAL_REASON_MIN_CHARS`, and it says something.
_WHY = ("the publishing filter declined to carry this run tree; its reports "
        "still declare FAIL and nobody examined them")


def _load_gate():
    """The shipped module, imported rather than reimplemented.

    Deliberately not guarded by a skip: if the entry point moves, this file
    measures nothing, and a green that means "I could not ask" is the shape
    this repository keeps having to remove.
    """
    spec = importlib.util.spec_from_file_location("_sifbu_1704", GATE)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_sifbu_1704"] = m
    spec.loader.exec_module(m)
    return m


#: The environment every case here runs the gate in.
#:
#: `$VIBE_IC_BENCHMARK_DATA` IS SCRUBBED, and that is not tidiness. Every
#: fixture below names its own corpus on the command line, and the gate's
#: resolver falls back to the pointer whenever a named root is absent — which
#: is exactly what the "no corpus" cases below construct. MEASURED: with the
#: pointer set to a real clone, two of these cases stopped exercising the
#: NO_CORPUS register arm and swept the clone instead, so they failed for a
#: reason that had nothing to do with what they assert. A test whose subject
#: changes with the developer's shell is not measuring the program.
_ENV = {k: v for k, v in os.environ.items() if k != "VIBE_IC_BENCHMARK_DATA"}


def _run(*args: str) -> subprocess.CompletedProcess:
    """One real invocation of the shipped entry point, argv and rc included."""
    return subprocess.run([sys.executable, str(GATE), *args],
                          capture_output=True, text=True,
                          timeout=_GATE_TIMEOUT_S, env=_ENV)


def _out(r: subprocess.CompletedProcess) -> str:
    return r.stdout + r.stderr


def _mk_run(corpus: Path, rel: str, n_findings: int) -> Path:
    """A published run tree carrying `n_findings` UNACKNOWLEDGED FAILs.

    Unacknowledged by construction: no `waivers.json` and no
    `reports/orchestrator/` or `reports/audit/` record naming these files, so
    neither arm of the gate's acknowledgment rule can grant them.
    """
    d = corpus / rel / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, n_findings + 1):
        (d / f"gate_{i}.json").write_text(json.dumps(
            {"verdict": "FAIL", "detail": f"synthetic unacknowledged fail {i}"}))
    return corpus / rel


def _withdraw_reports(run: Path) -> None:
    """Stop publishing a run's reports WITHOUT examining them.

    Only `reports/` is removed, which is the shape the repository actually
    produced: a run tree that keeps its place and its `input/` and simply stops
    carrying reports leaves the count with nobody having read a line of it.
    """
    for p in sorted((run / "reports").rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    (run / "reports").rmdir()


def _tamper(bl: Path, mutate) -> None:
    doc = json.loads(bl.read_text())
    mutate(doc)
    bl.write_text(json.dumps(doc, indent=2) + "\n")


def _write(corpus: Path, bl: Path, *extra: str) -> subprocess.CompletedProcess:
    return _run("--corpus", str(corpus), "--baseline", str(bl),
                "--write-baseline", *extra)


def _seed(tmp_path):
    """A corpus of three run trees and a first baseline over it.

    THREE, not two, and the third is load-bearing. `--write-baseline` refuses a
    sweep that reached nothing at all (vibe-ic#1025), so a fixture that can be
    emptied would meet that refusal first and the case below would pass for a
    reason it is not about. `gamma` is never withdrawn and keeps the sweep
    non-vacuous throughout.

    The first write withdraws nothing, so it needs no reason — which is itself
    one of the properties asserted below.
    """
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 2)
    beta = _mk_run(corpus, "beta/clean_run_B", 1)
    _mk_run(corpus, "gamma/clean_run_C", 1)
    r = _write(corpus, bl)
    assert r.returncode == 0, f"fixture: first write failed\n{_out(r)}"
    assert json.loads(bl.read_text())["withdrawn_unexamined"] == {}, (
        "fixture premise: the first write must leave an EMPTY ledger, or the "
        "cases below are not measuring the transition they name")
    return corpus, bl, beta


# --------------------------------------------------------------- the defect

def test_a_withdrawal_with_no_stated_reason_is_refused_and_writes_nothing(
        tmp_path):
    """The headline property.

    Asserted on the FILE as well as the rc: a refusal that had already
    rewritten the register would have destroyed the reference point it was
    protecting, which is the vibe-ic#1025 shape one branch over.
    """
    corpus, bl, beta = _seed(tmp_path)
    before = bl.read_text()

    assert json.loads((beta / "reports" / "phase3" / "gate_1.json")
                      .read_text())["verdict"] == "FAIL", (
        "fixture premise: the withdrawn run's report must still DECLARE FAIL, "
        "otherwise this is a repair and there is nothing to explain")
    _withdraw_reports(beta)

    r = _write(corpus, bl)
    out = _out(r)
    assert r.returncode == 2, (
        f"a write that puts an unexamined finding on the ledger without "
        f"saying why must be refused\n{out}")
    assert "--shrink-reason" in out and "beta/clean_run_B" in out, (
        f"the refusal named neither the missing input nor the run it is "
        f"about, so the operator cannot act on it\n{out}")
    assert bl.read_text() == before, (
        f"the refusal REWROTE the register. Nothing may be written on a "
        f"refusal — a half-written record is a state --write-baseline cannot "
        f"produce\n{out}")


def test_the_same_withdrawal_with_a_reason_is_recorded(tmp_path):
    """The other half, and without it the case above is satisfied by a ban.

    The reason must land as DATA — scoped to the runs it was written about and
    beside the denominator it explains — not as a sentence in a log nobody
    reads back.
    """
    corpus, bl, beta = _seed(tmp_path)
    _withdraw_reports(beta)

    r = _write(corpus, bl, "--shrink-reason", _WHY)
    assert r.returncode == 0, f"a stated reason must let the write through\n{_out(r)}"
    doc = json.loads(bl.read_text())
    prov = doc["withdrawal_provenance"]
    assert prov["reason"] == _WHY
    assert set(prov["covers_runs"]) == set(doc["withdrawn_unexamined"]), (
        "the recorded sentence must be scoped to exactly the ledger it "
        "explains; a set that does not match is a sentence about other runs")
    assert prov["denominator_before"] == {"runs_swept": 3,
                                          "runs_with_reports": 3}, (
        f"the denominator the withdrawal moved away from was not recorded, so "
        f"the file cannot show that the POPULATION shrank rather than the "
        f"findings being fixed: {prov['denominator_before']!r}")
    assert doc["findings_total"] == 3 and doc["runs_swept"] == 2


def test_a_reason_too_short_to_be_one_is_refused(tmp_path):
    """The floor, with its own negative control.

    Without it the requirement is satisfied by `--shrink-reason n/a` and the
    mechanism is ceremony. The constant is read from the module so the test
    cannot drift away from what the program enforces.
    """
    m = _load_gate()
    corpus, bl, beta = _seed(tmp_path)
    _withdraw_reports(beta)
    before = bl.read_text()

    short = "x" * (m.WITHDRAWAL_REASON_MIN_CHARS - 1)
    r = _write(corpus, bl, "--shrink-reason", short)
    assert r.returncode == 2, f"a {len(short)}-char 'reason' was accepted\n{_out(r)}"
    assert bl.read_text() == before

    ok = "x" * m.WITHDRAWAL_REASON_MIN_CHARS
    assert _write(corpus, bl, "--shrink-reason", ok).returncode == 0, (
        "the floor rejected a reason of exactly the declared length, so the "
        "writer and the constant disagree")


def test_a_re_record_that_withdraws_nothing_new_is_not_asked_to_renew(tmp_path):
    """A legitimate no-op write must stay a no-op.

    This is the arm a blanket refusal fails. The standing sentence still covers
    exactly the runs it was written about, so demanding a new one would train
    operators to retype a reason they have not re-examined — which is how a
    required field becomes a rubber stamp.
    """
    corpus, bl, beta = _seed(tmp_path)
    _withdraw_reports(beta)
    assert _write(corpus, bl, "--shrink-reason", _WHY).returncode == 0

    r = _write(corpus, bl)
    assert r.returncode == 0, (
        f"a re-record that adds nothing to the ledger was refused\n{_out(r)}")
    assert json.loads(bl.read_text())["withdrawal_provenance"]["reason"] == _WHY


def test_a_ledger_inherited_with_no_reason_is_refused_not_carried_forward(
        tmp_path):
    """The register vibe-ic#1704 was filed about, re-recorded.

    A ledger written before this key existed carries entries and no
    explanation. Re-recording it adds nothing, so the "did you add a run?"
    question answers no — and passing on that answer alone would carry the
    unexplained ledger forward one more version, which is the state the issue
    describes rather than a fix for it.

    Its opposite is a line below: with a reason supplied, the same write is
    accepted, so this refuses an unexplained ledger and not a re-record.
    """
    corpus, bl, beta = _seed(tmp_path)
    _withdraw_reports(beta)
    assert _write(corpus, bl, "--shrink-reason", _WHY).returncode == 0
    _tamper(bl, lambda d: d.pop("withdrawal_provenance"))   # a pre-#1704 file
    before = bl.read_text()

    r = _write(corpus, bl)
    assert r.returncode == 2, (
        f"an inherited ledger with no reason was re-recorded unchanged\n"
        f"{_out(r)}")
    assert "nothing, here or on record, says" in _out(r), _out(r)
    assert bl.read_text() == before

    assert _write(corpus, bl, "--shrink-reason", _WHY).returncode == 0, (
        "the same write with a reason must be accepted")


def test_a_second_withdrawal_may_not_ride_on_the_first_sentence(tmp_path):
    """The scope arm (vibe-ic#922's lesson, in this register).

    A sentence written about `beta` is not a reason for `alpha`. Without this
    the standing reason becomes a pre-written authorisation and the only thing
    a later author has to move is an integer.
    """
    corpus, bl, beta = _seed(tmp_path)
    _withdraw_reports(beta)
    assert _write(corpus, bl, "--shrink-reason", _WHY).returncode == 0

    _withdraw_reports(corpus / "alpha/clean_run_A")
    before = bl.read_text()
    r = _write(corpus, bl)
    out = _out(r)
    assert r.returncode == 2, (
        f"a NEW withdrawal was admitted under the sentence written about the "
        f"previous one\n{out}")
    assert "alpha/clean_run_A" in out
    assert bl.read_text() == before

    assert _write(corpus, bl, "--shrink-reason",
                  _WHY + " (both run trees)").returncode == 0, (
        "a renewed sentence covering both must be accepted")


def test_the_denominator_before_is_pinned_to_the_withdrawal_not_the_write(
        tmp_path):
    """`(2, 2) -> (1, 1)` must survive every later no-change re-record.

    Recomputed per write it would decay to `(1, 1) -> (1, 1)` and the file
    would stop showing that the population moved at all — which is the exact
    fact vibe-ic#1704 was filed about, erased by the tool rather than by a
    person.
    """
    corpus, bl, beta = _seed(tmp_path)
    _withdraw_reports(beta)
    assert _write(corpus, bl, "--shrink-reason", _WHY).returncode == 0
    first = json.loads(bl.read_text())["withdrawal_provenance"]["denominator_before"]

    for _ in range(2):
        assert _write(corpus, bl).returncode == 0
    assert json.loads(bl.read_text())["withdrawal_provenance"][
        "denominator_before"] == first == {"runs_swept": 3,
                                           "runs_with_reports": 3}


def test_a_reason_with_nothing_to_explain_is_announced_not_stored(tmp_path):
    """Two failures at once, and they pull in opposite directions.

    STORED, it becomes a standing authorisation over an empty ledger — refused
    on read below. DROPPED IN SILENCE, an operator who typed a reason is left
    believing it landed. So it is dropped and said out loud.
    """
    corpus, bl, _beta = _seed(tmp_path)
    r = _write(corpus, bl, "--shrink-reason", _WHY)
    assert r.returncode == 0
    assert "withdrawal_provenance" not in json.loads(bl.read_text())
    assert "NOT recorded" in _out(r), (
        f"the reason was dropped without a word\n{_out(r)}")


def test_a_reason_without_a_write_is_refused(tmp_path):
    """An input that goes nowhere. This program's own history is the argument:
    `--write-baseline <scratch.json>` silently dropped the operator's path and
    zeroed the real record (vibe-ic#1025)."""
    corpus, bl, _beta = _seed(tmp_path)
    r = _run("--corpus", str(corpus), "--baseline", str(bl),
             "--shrink-reason", _WHY)
    # The MESSAGE, not only the rc. argparse answers 2 for an option it does
    # not recognise at all, and its usage line names `--write-baseline` — so an
    # rc-and-substring assertion here passes just as happily against a build
    # that has never heard of this flag. Measured: it did.
    assert r.returncode == 2, _out(r)
    assert "no write for it to authorise" in _out(r), _out(r)


# ------------------------------------------------------- the two read paths

def test_the_corpus_sweep_refuses_a_ledger_whose_sentence_was_edited_away(
        tmp_path):
    """A register is not only what the writer produces; it is a file on disk.

    Both directions: the untouched register PASSES the same sweep, so the
    refusal is discriminating between two registers rather than rejecting the
    sweep.
    """
    corpus, bl, beta = _seed(tmp_path)
    _withdraw_reports(beta)
    assert _write(corpus, bl, "--shrink-reason", _WHY).returncode == 0

    good = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert good.returncode == 0, (
        f"the honest register did not pass its own sweep\n{_out(good)}")
    assert "why they left" in _out(good), (
        f"the reason is never printed, so it is a field nobody reads\n"
        f"{_out(good)}")

    _tamper(bl, lambda d: d.pop("withdrawal_provenance"))
    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert r.returncode == 1, f"the stripped register passed\n{_out(r)}"
    assert "does not say WHY" in _out(r)


def test_the_no_corpus_register_arm_checks_the_reason_too(tmp_path):
    """The arm that actually runs on every landing.

    CI sweeps `--corpus <repo>/benchmark-data/ic --corpus-may-be-absent`
    against a checkout that no longer carries the corpus, so a requirement
    enforced only where a corpus happens to be present is a requirement that
    never fires here.
    """
    corpus, bl, beta = _seed(tmp_path)
    _withdraw_reports(beta)
    assert _write(corpus, bl, "--shrink-reason", _WHY).returncode == 0
    absent = tmp_path / "nowhere"

    ok = _run("--corpus", str(absent), "--baseline", str(bl),
              "--corpus-may-be-absent")
    assert ok.returncode == 0, f"the honest register was refused\n{_out(ok)}"

    _tamper(bl, lambda d: d["withdrawal_provenance"].update(
        {"covers_runs": ["some/other/run"]}))
    r = _run("--corpus", str(absent), "--baseline", str(bl),
             "--corpus-may-be-absent")
    assert r.returncode == 1, (
        f"a sentence scoped to a run that is not on the ledger passed\n"
        f"{_out(r)}")
    assert "different set than the ledger holds" in _out(r)


def test_a_reason_left_standing_over_an_empty_ledger_is_refused(tmp_path):
    """The other direction of the same rule, and it is not symmetry for its own
    sake: an unspent sentence pre-authorises the NEXT withdrawal."""
    corpus, bl, _beta = _seed(tmp_path)
    _tamper(bl, lambda d: d.update({"withdrawal_provenance": {
        "reason": _WHY, "covers_runs": [],
        "denominator_before": {"runs_swept": 3, "runs_with_reports": 3}}}))
    r = _run("--corpus", str(tmp_path / "nowhere"), "--baseline", str(bl),
             "--corpus-may-be-absent")
    assert r.returncode == 1, f"a standing sentence over an empty ledger passed\n{_out(r)}"
    assert "standing authorisation" in _out(r)


# ------------------------------------------------- the repository's own record

def test_the_shipped_register_states_why_its_ledger_holds_what_it_holds():
    """A rule whose only subject is a fixture is a rule the repo has not
    adopted. This reads the SHIPPED baseline through the SHIPPED validator."""
    m = _load_gate()
    doc = json.loads(SHIPPED_BASELINE.read_text(encoding="utf-8"))
    assert doc["withdrawn_unexamined"], (
        "fixture premise: the shipped ledger is empty, so this case asserts "
        "nothing — it must be re-pointed rather than left passing")
    defects = m._provenance_defects(doc)
    assert defects == [], "\n".join(defects)
    prov = doc["withdrawal_provenance"]
    assert prov["denominator_before"] != {
        "runs_swept": doc["runs_swept"],
        "runs_with_reports": doc["runs_with_reports"]}, (
        "the shipped record shows no denominator move, so the sentence beside "
        "it explains a shrink the file does not evidence")
