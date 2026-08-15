"""A run leaving the corpus must not be read as debt somebody paid.

vibe-ic#1202. `step_internal_fail_bubble_up_check --corpus` ratchets a single
scalar. On any fall it said, verbatim on `75776dbbb`::

    [FAIL] the recorded baseline claims 3 unacknowledged step-internal FAIL(s)
    and the sweep measures 2: 1 of them are PAID and still on the register.
    ... Re-record it with --write-baseline

and the re-record it prescribes dropped the missing run out of `per_run`
entirely. So the sequence the gate itself instructs an operator to run turns an
unexamined FAIL into a smaller number with nothing left in the file to say what
happened. MEASURED end to end against the pre-fix gate, synthetic corpus, two
designs::

    baseline: {"findings_total": 3,
               "per_run": {"alpha/clean_run_A": 2, "beta/clean_run_B": 1}}
    $ rm -rf <corpus>/beta          # beta's report still reads verdict=FAIL
    [FAIL] ... 1 of them are PAID and still on the register
    $ ...--write-baseline           # exactly what the gate told you to do
    {"findings_total": 2, "per_run": {"alpha/clean_run_A": 2}}
    [PASS] no NEW unacknowledged step-internal FAIL (2 recorded)

One finding nobody read, described as paid, then erased, then green.

THIS IS NOT HYPOTHETICAL AND IT ALREADY HAPPENED HERE. `94c7572aa` moved the
shipped baseline 7 -> 5::

    sha256/clean_run_v1422_20260715        2 -> 2   unchanged
    sha256/clean_run_v1427_20260715        3 -> 3   unchanged
    u_hawaii_adc/clean_run_v1422_20260715  1 -> gone
    u_hawaii_adc/clean_run_v1427_20260715  1 -> gone

Zero repaired, two withdrawn. `u_hawaii_adc/clean_run_v1422_20260715` is still
a published run tree at `75776dbbb` and still carries `input/docs/`; what it
stopped carrying is `reports/`, so the sweep walks past it. Because the ratchet
may only ever go down, that credited a publishing decision as engineering and
lowered the bar permanently.

WHY EVERY CASE BELOW IS BIDIRECTIONAL. A guard that shouts WITHDRAWN at every
shrink would pass the first test here and destroy the gate's ability to
recognise real work — which is the shape #1202 argues against, pointed the
other way. So each property is asserted with its opposite beside it: a
withdrawal must be named withdrawn AND a genuine repair must be named
repaired, over the same fixture builder and the same gate.

NOTHING HERE TOUCHES THE REPO'S BASELINE OR CORPUS. Every case builds its own
tree under `tmp_path` and passes `--baseline` explicitly.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN_ROOT / "programs"
GATE = PROGRAMS / "step_internal_fail_bubble_up_check.py"

#: vibe-ic#1241 — the inner ceiling is 60s, below the harness's 180s, so this
#: call's own timeout fires before the harness kills the SESSION. MEASURED, not
#: snapped to the ceiling: the slowest case here builds 3 run trees and makes 4
#: gate calls, 0.5s wall total. 60s is ~100x that.
_GATE_TIMEOUT_S = 60


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GATE), *args],
                          capture_output=True, text=True,
                          timeout=_GATE_TIMEOUT_S)


def _mk_run(corpus: Path, rel: str, n_findings: int) -> Path:
    """A published run tree carrying `n_findings` unacknowledged FAILs.

    Unacknowledged is the default state here by construction: no
    `waivers.json`, and no `reports/orchestrator/` or `reports/audit/` record
    naming these reports, so nothing can grant them (a) or (b) of the gate's
    own acknowledgment rule. `n_findings == 0` builds a run that IS examined —
    it carries a `reports/` tree — and has nothing to report, which is the
    fixture the repaired-to-zero case turns on.
    """
    d = corpus / rel / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, n_findings + 1):
        (d / f"gate_{i}.json").write_text(json.dumps(
            {"verdict": "FAIL", "detail": f"synthetic unacknowledged fail {i}"}))
    return corpus / rel


def _write_baseline(corpus: Path, bl: Path) -> dict:
    r = _run("--corpus", str(corpus), "--baseline", str(bl), "--write-baseline")
    assert r.returncode == 0, f"fixture: baseline write failed\n{r.stdout}{r.stderr}"
    return json.loads(bl.read_text())


def _withdraw_reports(run: Path) -> None:
    """Stop publishing a run's reports WITHOUT examining them.

    Deletes only `reports/`, which is the shape the repo actually produced:
    `u_hawaii_adc/clean_run_v1422_20260715` is still a published run tree and
    still carries `input/`, and it left the count anyway. The whole-tree
    removal is covered separately so both spellings of a withdrawal are pinned.
    """
    for p in sorted((run / "reports").rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    (run / "reports").rmdir()


# ---------------------------------------------------------------- the defect

def test_a_withdrawn_run_is_not_reported_as_a_paid_debt(tmp_path):
    """The headline property, in the gate's own words.

    Asserted on what the operator READS, not on an rc: the rc is deliberately
    unchanged (1) by this fix, so an rc-only assertion could not tell the
    fixed gate from the broken one.
    """
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 2)
    beta = _mk_run(corpus, "beta/clean_run_B", 1)
    _write_baseline(corpus, bl)

    assert json.loads((beta / "reports" / "phase3" / "gate_1.json")
                      .read_text())["verdict"] == "FAIL", (
        "fixture premise: the withdrawn run's report must still DECLARE FAIL, "
        "otherwise this is a repair and there is nothing to catch")
    _withdraw_reports(beta)

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    out = r.stdout + r.stderr

    assert r.returncode == 1, (
        f"the ratchet must still come down on a shrink — this fix does not "
        f"relax that\n{out}")
    assert "WITHDRAWN" in out and "beta/clean_run_B" in out, (
        f"the gate did not name the withdrawn run. Without it the operator is "
        f"told a number fell and cannot find out why\n{out}")
    assert "NONE of it is repair" in out, (
        f"a shrink composed ENTIRELY of withdrawals was not disclosed as such"
        f"\n{out}")
    assert "are PAID" not in out, (
        f"the gate still calls an unexamined finding PAID. That is the #1202 "
        f"defect verbatim: nobody read beta's report, it still says FAIL, and "
        f"it is only unpublished\n{out}")


def test_the_prescribed_re_record_preserves_the_withdrawal(tmp_path):
    """The erasure, closed. The gate's own instruction must not destroy it.

    The fall being *described* correctly is worth nothing if the very next
    command wipes the evidence — which is what `--write-baseline` did.
    """
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 2)
    beta = _mk_run(corpus, "beta/clean_run_B", 1)
    _write_baseline(corpus, bl)
    _withdraw_reports(beta)

    after = _write_baseline(corpus, bl)

    assert after["findings_total"] == 2, after
    assert after["withdrawn_unexamined"] == {"beta/clean_run_B": 1}, (
        f"the re-record dropped the withdrawn run without trace. The next "
        f"reader sees only a smaller number, indistinguishable from work\n"
        f"{json.dumps(after, indent=2)}")


def test_the_ledger_is_disclosed_on_an_ordinary_green_sweep(tmp_path):
    """A register only ever written and never read is not a record.

    After the re-record the gate returns to PASS. If the ledger is invisible
    there, the withdrawal is preserved in a file nobody opens and #1202 is
    closed on paper only.
    """
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 2)
    beta = _mk_run(corpus, "beta/clean_run_B", 1)
    _write_baseline(corpus, bl)
    _withdraw_reports(beta)
    _write_baseline(corpus, bl)

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "withdrawn_unexamined" in out and "beta/clean_run_B" in out, (
        f"the green sweep says nothing about the finding that left "
        f"unexamined\n{out}")


# ------------------------------------------------- the paired other direction

def test_a_genuine_repair_is_still_credited_as_a_repair(tmp_path):
    """The guard must not answer WITHDRAWN to everything.

    `beta` keeps its `reports/` tree and loses its FAIL — somebody looked and
    it is better. A fix that cannot tell this from a withdrawal has merely
    moved the mislabelling to the other population.
    """
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 2)
    beta = _mk_run(corpus, "beta/clean_run_B", 2)
    _write_baseline(corpus, bl)

    (beta / "reports" / "phase3" / "gate_2.json").unlink()   # one FAIL repaired

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "REPAIRED  beta/clean_run_B: 2 -> 1" in out, (
        f"a real repair was not credited as one\n{out}")
    assert "WITHDRAWN" not in out, (
        f"a run that kept its reports/ tree and got BETTER was called "
        f"withdrawn — the negative control for this whole change\n{out}")
    assert "are PAID" in out, (
        f"a shrink that is entirely repair must keep the original wording; "
        f"this fix narrows that claim, it does not delete it\n{out}")


def test_repaired_to_zero_is_a_repair_not_a_withdrawal(tmp_path):
    """The case `per_run` alone provably cannot decide.

    `check_corpus` writes a `per_run` entry only for runs WITH findings, so a
    run repaired to zero and a run nobody read are both simply absent from the
    map. Deciding on absence alone would call this a withdrawal. It is not:
    the run is still swept, still carries `reports/`, and the sweep read it
    and found nothing. This is what `examined_runs` exists for.
    """
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 2)
    beta = _mk_run(corpus, "beta/clean_run_B", 1)
    _write_baseline(corpus, bl)

    (beta / "reports" / "phase3" / "gate_1.json").unlink()   # zero findings left
    assert (beta / "reports").is_dir(), "fixture: the run is still examinable"

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    out = r.stdout + r.stderr
    assert "REPAIRED  beta/clean_run_B: 1 -> 0" in out, (
        f"a run examined and found clean was not credited\n{out}")
    assert "WITHDRAWN" not in out, (
        f"absence from per_run was read as a withdrawal; the sweep DID look "
        f"at this run\n{out}")

    after = _write_baseline(corpus, bl)
    assert after["withdrawn_unexamined"] == {}, (
        f"a repair was written into the withdrawal ledger, which would inflate "
        f"it forever with debt that was actually paid\n{after}")


def test_a_mixed_shrink_names_both_and_credits_only_the_repair(tmp_path):
    """Real shrinks are rarely pure. The two must not be summed into one word."""
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 3)
    beta = _mk_run(corpus, "beta/clean_run_B", 2)
    _write_baseline(corpus, bl)

    (beta / "reports" / "phase3" / "gate_2.json").unlink()          # 1 repaired
    _withdraw_reports(_mk_run(corpus, "alpha/clean_run_A", 0))      # 3 withdrawn

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "REPAIRED  beta/clean_run_B: 2 -> 1" in out, out
    assert "WITHDRAWN alpha/clean_run_A: 3" in out, out
    assert "1 repaired and 3 withdrawn without being examined" in out, (
        f"the two populations were collapsed into one number\n{out}")
    assert "only the first is debt paid" in out, out


# ------------------------------------------------------ the ledger's own rules

def test_the_ledger_accumulates_across_successive_withdrawals(tmp_path):
    """A run withdrawn while another is already on the ledger keeps both.

    If the write started from the live sweep instead of the previous record,
    each re-record would forget everything before it and the ledger would only
    ever hold the most recent withdrawal.
    """
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 2)
    beta = _mk_run(corpus, "beta/clean_run_B", 1)
    gamma = _mk_run(corpus, "gamma/clean_run_C", 4)
    _write_baseline(corpus, bl)

    _withdraw_reports(beta)
    _write_baseline(corpus, bl)
    _withdraw_reports(gamma)
    after = _write_baseline(corpus, bl)

    assert after["withdrawn_unexamined"] == {"beta/clean_run_B": 1,
                                             "gamma/clean_run_C": 4}, (
        f"the second re-record forgot the first withdrawal\n{after}")
    assert after["findings_total"] == 2, after


def test_a_run_that_comes_back_leaves_the_ledger(tmp_path):
    """Otherwise the same findings are counted in both registers at once.

    A returning run is swept and counted in `per_run` again. Leaving it in the
    ledger too would double-count it and turn the ledger into the ghost-entry
    defect vibe-ic#1025 part 3 removed from `per_run`.
    """
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 2)
    beta = _mk_run(corpus, "beta/clean_run_B", 1)
    _write_baseline(corpus, bl)

    _withdraw_reports(beta)
    mid = _write_baseline(corpus, bl)
    assert mid["withdrawn_unexamined"] == {"beta/clean_run_B": 1}, mid

    _mk_run(corpus, "beta/clean_run_B", 1)                  # republished
    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert r.returncode == 1, (
        f"the count GREW back — that must still be rc 1\n{r.stdout}{r.stderr}")

    after = _write_baseline(corpus, bl)
    assert after["per_run"].get("beta/clean_run_B") == 1, after
    assert after["withdrawn_unexamined"] == {}, (
        f"a republished run stayed on the withdrawal ledger while also being "
        f"counted in per_run — the same finding recorded twice\n{after}")


def test_the_ledger_is_not_folded_into_the_ratchet_ceiling(tmp_path):
    """`findings_total` must stay the sum of `per_run`, and only that.

    The tempting move is to keep the withdrawn findings inside the total so
    they still gate. That would hold the ceiling high on runs the sweep cannot
    reach — the stale-entry defect #1025 part 3 removed, and it would break
    `test_issue1025_baseline_names_runs_that_exist`'s sum invariant. The
    ledger discloses; it does not gate.
    """
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 2)
    beta = _mk_run(corpus, "beta/clean_run_B", 5)
    _write_baseline(corpus, bl)
    _withdraw_reports(beta)
    after = _write_baseline(corpus, bl)

    assert after["findings_total"] == sum(after["per_run"].values()), (
        f"findings_total drifted from per_run\n{after}")
    assert sum(after["withdrawn_unexamined"].values()) == 5, after
    assert not set(after["withdrawn_unexamined"]) & set(after["per_run"]), (
        f"a run appears in both registers\n{after}")

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert r.returncode == 0, (
        f"the ledger made a clean sweep red. It records; it does not gate\n"
        f"{r.stdout}{r.stderr}")


# --------------------------------------------------- the key-spelling hazard

def test_the_two_corpus_spellings_do_not_fake_a_mass_withdrawal(tmp_path):
    """A baseline recorded from `<root>` vs a sweep of `<root>/ic`.

    This is live in the repo, not invented for the test. At `75776dbbb` the
    shipped baseline keys read `ic/sha256/clean_run_v1422_20260715` (recorded
    from `benchmark-data` in `94c7572aa`) while `tools/ci/repo_hygiene_gates.sh`
    sweeps `--corpus "$ROOT/benchmark-data/ic"` and emits
    `sha256/clean_run_v1422_20260715`. Compared verbatim, every baseline run is
    absent from every CI sweep, so the moment anything reads `per_run` back it
    would report a total withdrawal of runs that are sitting right there with
    unchanged counts.
    """
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "ic/alpha/clean_run_A", 2)
    beta = _mk_run(corpus, "ic/beta/clean_run_B", 1)

    _write_baseline(corpus, bl)                       # keys: ic/alpha/..., ic/beta/...
    assert "ic/alpha/clean_run_A" in json.loads(bl.read_text())["per_run"]

    _withdraw_reports(beta)
    r = _run("--corpus", str(corpus / "ic"), "--baseline", str(bl))  # keys: alpha/...
    out = r.stdout + r.stderr

    assert "WITHDRAWN beta/clean_run_B" in out, (
        f"the run that really was withdrawn went unreported\n{out}")
    assert "WITHDRAWN alpha/clean_run_A" not in out, (
        f"a run present in BOTH spellings with an unchanged count was reported "
        f"withdrawn, purely because the caller named a different corpus root"
        f"\n{out}")
    assert "NONE of it is repair" in out, out
    assert "1 finding(s) left" in out, (
        f"the withdrawal total is wrong; unreconciled keys would make it 3 "
        f"(alpha's 2 plus beta's 1) instead of beta's 1\n{out}")


# ------------------------------------------- the gate is not otherwise weakened

def test_growth_is_still_rc_1(tmp_path):
    """The one thing this gate exists to block, re-asserted.

    Every case above is about a FALL. A change that reasoned only about falls
    could relax the rise without any of them noticing.
    """
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 2)
    _write_baseline(corpus, bl)
    _mk_run(corpus, "beta/clean_run_B", 1)

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert r.returncode == 1, f"a NEW unacknowledged FAIL did not redden\n{r.stdout}{r.stderr}"
    assert "GREW" in (r.stdout + r.stderr)


def test_an_unchanged_corpus_is_still_a_plain_pass(tmp_path):
    """No decomposition, no ledger noise, rc 0 — the steady state."""
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 2)
    _write_baseline(corpus, bl)

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "WITHDRAWN" not in out and "REPAIRED" not in out, out


def test_a_vacuous_sweep_still_refuses_to_write(tmp_path):
    """vibe-ic#1025's refusal must survive the rewritten write branch.

    That branch is edited by this change, and it is the one whose failure mode
    is destroying the record. Re-pinned here rather than trusted to be
    untouched.
    """
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 2)
    before = _write_baseline(corpus, bl)
    empty = tmp_path / "empty"
    (empty / "ic").mkdir(parents=True)

    r = _run("--corpus", str(empty), "--baseline", str(bl), "--write-baseline")
    assert r.returncode == 2, f"{r.stdout}{r.stderr}"
    assert "REFUSED" in (r.stdout + r.stderr)
    assert json.loads(bl.read_text()) == before, (
        "a zero-reach sweep rewrote the baseline through the new write path")


def test_a_pre_ledger_baseline_is_unknown_not_repaired(tmp_path):
    """Backward compatibility, resolved in the safe direction.

    Baselines recorded before this change carry no `examined_runs` on the
    report side and no ledger. A fall against one cannot be attributed — and
    the reading that does NOT hand out credit is the correct one, because
    absent evidence of examination is not evidence of examination.
    """
    corpus, bl = tmp_path / "c", tmp_path / "bl.json"
    _mk_run(corpus, "alpha/clean_run_A", 2)
    beta = _mk_run(corpus, "beta/clean_run_B", 1)
    _write_baseline(corpus, bl)
    _withdraw_reports(beta)

    sys.path.insert(0, str(PROGRAMS))
    import step_internal_fail_bubble_up_check as SIFBU     # noqa: PLC0415

    base = json.loads(bl.read_text())
    base.setdefault("withdrawn_unexamined", {})
    rep = SIFBU.check_corpus(corpus)
    rep.pop("examined_runs")                    # a report from the old gate

    split = SIFBU._decompose_shrink(base, rep)
    assert split["unknown"] == {"beta/clean_run_B": 1}, split
    assert split["repaired_total"] == 0 and split["withdrawn_total"] == 0, (
        f"an unattributable fall was assigned to a population anyway\n{split}")


if __name__ == "__main__":                                  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
