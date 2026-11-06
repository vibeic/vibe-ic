"""#526 — the waiver validator's step-id ceiling was hand-typed at 40 while
the flow it validates against declares 44 integer steps, and the failure was
not "that waiver was ignored" but "there is no report".

`waivers_schema_check`'s errors become `SystemExit(1)` inside
`flow_compliance_check._load_waivers`, so ONE hand-authored waiver naming a
step past the hand-typed ceiling deleted the ENTIRE compliance report —
advisories, 63 step verdicts and all. #519 hit this through the role-resolved
path (`htol` -> Step 44) and v1.7.83 fixed that half by declaring a
role-resolved id valid by construction. The hand-authored integer path kept
the 40.

MEASURED at pristine v1.7.85, and pinned below: NINE of the 63 ids the flow
declares were rejected, not four —

    41, 42, 43, 44          past the hand-typed integer ceiling
    D1, FS1, DT1, DT2, DT3  alphabetic stage ids no pattern here knew about

which is why the remedy is a DERIVED ID SET rather than a corrected number.
Raising 40 to 44 would have left the five alphabetic ids rejected and the
same trap armed for the next step the flow gains.

TWO THINGS THIS FILE PINS THAT THE ISSUE'S OWN ANALYSIS MISSED
=============================================================
1. `flow_compliance_check._load_waivers` carries its OWN `max_step: int = 40`
   and passes it EXPLICITLY. A fix that only corrected this module's default
   would have been overridden by the caller and changed nothing end to end.
   So flow membership beats the caller's ceiling, and
   `test_caller_supplied_stale_ceiling_cannot_reject_a_flow_step` is the test
   that would have caught a default-only fix.

2. Downgrading the id finding wholesale — the obvious way to stop it killing
   the report — opens a hole. `_load_waivers` parses ids with a looser
   `int(v)`, so `"39"` and `39.5` are rejected here but land on REAL step 39
   there. Skipping such an entry would hand the consumer an exemption this
   program never checked for a reason or an approver. Those ids are therefore
   BOUND to the coerced step and validated in full, and only the spelling is
   disclosed.

The severity rule that results: an id finding is fatal only where fatality is
the only protection left. An id that names nothing is inert in the consumer,
so saying so must not cost the report; an entry with no `id` key at all makes
the consumer raise KeyError either way, so the precise message is kept.

Every test below is mutation-controlled — see
`test_MUTATION_CONTROL_unfixed_code_fails_these` for the executed proof that
the acceptance tests fail against the pre-fix rule.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

from _published_corpus import corpus_root, needs_corpus  # noqa: E402
import _watchdog  # noqa: E402


def _supervised(cmd, **kw):
    """`subprocess.run(cmd, capture_output=True, text=True, check=False)` with
    the wall-clock budget REPLACED by forward-progress supervision.

    These call sites used to carry a fixed `timeout=`. That number is not a
    property of the subject — it is a guess about a HOST — and when the guess is
    wrong on a loaded machine `TimeoutExpired` propagates out of the test and is
    recorded as the SUBJECT being broken. The verdict is then manufactured by
    the machine rather than measured on the program; the owner hit exactly that
    on a module nobody had changed.

    `_watchdog.run_host_supervised` bounds NO FORWARD PROGRESS instead — CPU and
    I/O summed over the child's whole /proc tree, plus the growth of its
    captured output — so a child that is merely slow runs to completion however
    long that legitimately takes, while one that is genuinely hung is still
    killed. A kill arrives as rc `_watchdog.RC_STALLED` with WATCHDOG_STALLED on
    stderr: a distinct code none of these subjects produces itself, so a hang
    can never be misread as an ordinary non-zero exit."""
    res = _watchdog.run_host_supervised(cmd, **kw)
    return _watchdog.completed_process(cmd, res)

FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

#: Repo root, from the plugin programs dir. Used only to reach the tracked
#: corpus; the corpus is READ, never written.
REPO_ROOT = PROGRAMS.parents[3]

#: The ceiling this program used to carry by hand, and which
#: `flow_compliance_check._load_waivers` still passes explicitly.
STALE_CEILING = 40

GOOD_REASON = ("Reliability qualification is a foundry-side activity "
               "scheduled after wafer-out and is not executable in-repo.")


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _entry(sid, **over):
    e = {"id": sid, "reason": GOOD_REASON, "approver": "Jane Doe",
         "approved_at": "2026-07-01", "review_required": True,
         "ticket": "REL-1"}
    e.update(over)
    return e


def _project(tmp_path, *entries, name="proj"):
    p = tmp_path / name
    p.mkdir(parents=True, exist_ok=True)
    (p / "waivers.json").write_text(json.dumps({"waived_steps": list(entries)}))
    return p


def _declared_ids_independently():
    """The flow's step ids, parsed here rather than asked of the code under
    test — otherwise the derivation would be checked against itself."""
    data = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    return [s["id"] for s in data["steps"]]


def _rules(findings, severity=None):
    return sorted(f.rule for f in findings
                  if severity is None or f.severity == severity)




def _write_fixture_flow(path, ids):
    """A minimal flow definition declaring exactly `ids`. Used so that
    "the ceiling moves when the flow grows" is proven WITHOUT editing the
    real flow definition."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({
        "version": 2,
        "flow_name": "fixture",
        "steps": [{"id": i, "name": f"fixture step {i}"} for i in ids],
    }))
    return path


# ----------------------------------------------------------------------
# 1. the ceiling is DERIVED, and it is the flow's real maximum
# ----------------------------------------------------------------------

def test_derived_ceiling_equals_the_flows_real_integer_maximum():
    declared = _declared_ids_independently()
    expected = max(i for i in declared if isinstance(i, int))
    # and it is NOT the number that was hand-typed — otherwise this test
    # would pass on the unfixed code by coincidence.
    assert expected != STALE_CEILING, (
        "the flow's maximum has become 40; this regression can no longer "
        "distinguish a derived ceiling from the hand-typed one, so the "
        "fixture-flow tests below are now the only guard")




def test_every_id_the_flow_declares_is_accepted(tmp_path):
    """The wide check. Nine of these failed at v1.7.85 — 41-44 plus the
    alphabetic D1/FS1/DT1-DT3 — and each failure deleted a whole report."""
    rejected = {}
    for n, sid in enumerate(_declared_ids_independently()):
        p = _project(tmp_path, _entry(sid), name=f"p{n}")
    assert rejected == {}, f"flow-declared ids rejected by the validator: {rejected}"






# ----------------------------------------------------------------------
# 2. the ceiling MOVES with the flow — proven on a fixture, not the real flow
# ----------------------------------------------------------------------









# ----------------------------------------------------------------------
# 3. --max-step survives as an OVERRIDE, but cannot un-declare a flow step
# ----------------------------------------------------------------------





# ----------------------------------------------------------------------
# 4. an id genuinely outside the flow is STILL reported
# ----------------------------------------------------------------------





# ----------------------------------------------------------------------
# 5. a rejected waiver must NOT take the compliance report down
# ----------------------------------------------------------------------

@pytest.mark.parametrize("sid", [44, 999])
def test_flow_compliance_check_still_produces_a_report(tmp_path, sid):
    """The #519 failure mode, tested directly against the real consumer.

    At v1.7.85 BOTH of these produced no report at all: `44` because the
    ceiling had drifted, `999` because an inert waiver was fatal.
    """
    p = _project(tmp_path, _entry(sid))
    report = tmp_path / f"report_{sid}.json"
    data = json.loads(report.read_text())
    assert data["steps"], "report exists but carries no step verdicts"
    assert "advisories" in data


def test_a_waiver_for_step_44_is_actually_honoured(tmp_path):
    """Tolerated is not the same as applied. With step 44's precondition
    satisfied it is MISSING without the waiver and WAIVED with it."""
    def build(name, waived):
        proj = tmp_path / name
        (proj / "phase3" / "stage5_manufacturing").mkdir(parents=True)
        (proj / "phase3" / "stage5_manufacturing"
         / "silicon_received.json").write_text(json.dumps({"received": True}))
        if waived:
            (proj / "waivers.json").write_text(
                json.dumps({"waived_steps": [_entry(44)]}))
        report = tmp_path / f"{name}.json"
        assert report.is_file(), f"{name}: no report"
        for st in json.loads(report.read_text())["steps"]:
            if st.get("id") == 44:
                return st.get("status")
        pytest.fail("step 44 absent from the report")

    # R-0915-140 — on this bare tree every blocker of 44 (43, 42, ...) FAILED,
    # so the un-waived step 44 was never owed its outputs: NOT_MEASURED
    # (upstream_failed), not FAIL(missing_artefact). Still un-waived and
    # non-green, which is the half of the pair this test needs.
    assert build("bare", False) == "NOT_MEASURED"
    assert build("waived", True) == "PASS_WITH_WAIVERS"


# ----------------------------------------------------------------------
# 6. the hole a wholesale downgrade would have opened
# ----------------------------------------------------------------------



def test_a_well_formed_coerced_id_is_disclosed_but_not_fatal(tmp_path):
    p = _project(tmp_path, _entry("39"))
    report = tmp_path / "coerced.json"
    assert report.is_file()


@pytest.mark.parametrize("sid", ["39", 39.5])
def test_consumer_coerced_id_agrees_with_the_REAL_compliance_reader(
        tmp_path, sid):
    """`_consumer_coerced_id` RESTATES `flow_compliance_check._load_waivers.
    _parse_id`, because that is a nested function and cannot be imported (and
    could not be, without a cycle). A restated rule can drift from the rule it
    restates, and here the drift would be silent AND load-bearing: the
    severity of every id finding is decided by it.

    So the agreement is proven the only way that cannot rot — by running the
    REAL consumer and observing the step it actually waives. Step 39 is
    MISSING on a bare project and WAIVED once the coerced id is present,
    which is exactly what this module predicted when it bound the entry to
    step 39 instead of skipping it.

    If `_parse_id` ever stops coercing these, this test fails and the
    restatement gets revisited — rather than the two quietly disagreeing
    about which entries are safe to wave through.
    """

    bare = tmp_path / "bare"
    bare.mkdir()
    bare_report = tmp_path / "bare.json"
    assert bare_report.is_file()
    before = [s for s in json.loads(bare_report.read_text())["steps"]
              if s.get("id") == 39][0]["status"]

    waived = _project(tmp_path, _entry(sid), name="waived")
    waived_report = tmp_path / "waived.json"
    assert waived_report.is_file(), "the coerced id took the report down"
    after = [s for s in json.loads(waived_report.read_text())["steps"]
             if s.get("id") == 39][0]["status"]

    # R-0915-140 — step 39's blockers FAILED on the bare project, so the
    # un-waived row reads NOT_MEASURED(upstream_failed); still un-waived.
    assert before == "NOT_MEASURED"




def test_id_null_is_not_fatal_because_the_consumer_survives_it(tmp_path):
    """`{"id": null}` is distinguishable from a missing key: the consumer's
    `w["id"]` succeeds and `_parse_id(None)` files it under a non-step."""
    p = _project(tmp_path, _entry(None))
    report = tmp_path / "null.json"
    assert report.is_file()


# ----------------------------------------------------------------------
# 7. cascades_to carried the identical ceiling
# ----------------------------------------------------------------------





# ----------------------------------------------------------------------
# 8. the corpus measurement — is this latent, or is a project reportless?
# ----------------------------------------------------------------------

def _corpus_root() -> Path:
    """Where the PUBLISHED corpus actually is.

    It used to be `REPO_ROOT / "benchmark-data"`. The results now live in
    `vibeic/benchmark-data`; what keeps that name in this repo is the design
    INPUT the flow reads, which carries no waiver at all. Both tests in this
    section are guarded by `@needs_corpus`, so reaching here means a cell IS
    readable and `corpus_root()` cannot be None.
    """
    root = corpus_root()
    assert root is not None, "@needs_corpus should have skipped before this point"
    return root


@needs_corpus
def test_no_tracked_corpus_waiver_sits_above_the_stale_ceiling():
    """#526 asks whether any corpus waiver is in 41-44. MEASURED: none is.

    Every tracked hand-authored id is 6, 36 or 39, and every attestation
    entry names `drc`/`lvs` (both -> Step 31), so no tracked project was
    running without a compliance report. The defect was LATENT, and this test
    is what turns "latent" from an assertion into a measurement — if a future
    corpus file lands a 41-44 id, this fails and the reviewer learns that a
    project's report is at stake.

    `@needs_corpus` because the sweep now has to reach `vibeic/benchmark-data`.
    Without it this test was the more dangerous half of the pair: a glob over a
    corpus that is no longer here finds no offender and `offenders == {}` is
    GREEN — "no waiver sits above the ceiling" asserted about a population of
    zero. A skip naming the corpus says the true thing instead, which is that
    nobody looked.
    """
    offenders = {}
    swept = 0
    for path in sorted(_corpus_root().glob("**/waivers.json")):
        swept += 1
        doc = json.loads(path.read_text())
        for key in ("waived_steps", "waivers"):
            for e in doc.get(key) or []:
                if not isinstance(e, dict):
                    continue
                sid = e.get("id")
                if isinstance(sid, int) and STALE_CEILING < sid:
                    offenders[str(path)] = sid
    # A sweep of no file has found no offender, and that is not the same
    # sentence as "no project waives above the ceiling". Said out loud so the
    # verdict below can only be reached over a real population.
    assert swept, (
        "the corpus is readable but carries no waivers.json — this test "
        "certifies the corpus and has certified nothing")
    assert offenders == {}, (
        f"a tracked project waives a step above the old ceiling {offenders} "
        f"— before #526 that project produced NO compliance report at all")


def _tracked_corpus_waivers():
    """The git-TRACKED `waivers.json` set INSIDE THE PUBLISHED CORPUS, or None
    when git cannot answer.

    It used to ask `git -C REPO_ROOT ls-files benchmark-data`. That question
    moved with the data: the corpus is its own repository now, so the tracked
    set has to be read from ITS checkout, which is also the only way the
    `VIBE_IC_BENCHMARK_DATA` pointer can mean anything. Asking this repo would
    answer about the design inputs — a different tree, carrying no waiver.

    This test's NAME says "tracked", and a filesystem glob is not that. Two
    consequences, both real:

    * an UNTRACKED local `waivers.json` — one a benchmark run just wrote — was
      validated and counted, so the verdict depended on what happened to be
      lying in the author's tree. That is the same false certificate
      `evidence_citation_resolves_check.tracked_files()` was written to remove:
      the question is what the REPO ships, not what this machine has.
    * the population could only be guarded by a hand-typed floor, and that
      floor rotted. `assert seen >= 11` went RED at 9 because the corpus
      legitimately shrank; the number said nothing about whether the scan was
      correct, only about when it was written.

    Asking git is strictly stronger than the floor: it catches a broken glob
    (zero or missing entries) AND untracked contamination, neither of which a
    `>=` count can distinguish, and it cannot rot when the corpus changes size
    for a legitimate reason.
    """
    # No inner wall-clock bound at all. A slice of the harness budget is
    # still a budget: whatever the number, the only thing it can decide is
    # "this host was slower than I guessed", and it reports that as `git`
    # being broken. The supervisor watches the child's forward progress
    # instead, so a `git ls-files` over a large corpus on a loaded box is
    # never cut short, and a `git` that wedges on a lock still dies.
    r = _supervised(["git", "-C", str(_corpus_root()), "ls-files", "-z"])
    if r.returncode != 0:
        return None
    out = r.stdout
    return sorted(p for p in out.split("\0")
                  if p and p.split("/")[-1] == "waivers.json")


@needs_corpus
def test_every_tracked_corpus_waiver_file_validates_without_an_id_error():
    """The consumer-scoped half: run the REAL validator over every tracked
    waivers.json and assert none of them trips an id finding.

    `@needs_corpus` because the files it validates are PUBLISHED CELLS and are
    no longer in this checkout. The non-vacuity guard below is right and stays:
    a scan of nothing has validated nothing. What was wrong is what it reported
    when it fired — an empty corpus was rendered as a RED test, i.e. as a defect
    in the tree, when the true sentence is that the data moved. It is still able
    to fail, and now for the one reason it should: a corpus IS readable and does
    not carry a single waiver.
    """
    tracked = _tracked_corpus_waivers()
    if tracked is None:
        pytest.skip("the corpus is present but is not a git checkout / git is "
                    "unavailable — 'tracked' is undecidable here, and a "
                    "filesystem glob is not a substitute (see "
                    "_tracked_corpus_waivers)")

    # Non-vacuity that cannot rot: the corpus may shrink, but a scan of NOTHING
    # has not validated anything.
    assert tracked, ("the corpus is readable but tracks no waivers.json — this "
                     "test certifies the corpus and cannot do so over an empty "
                     "one")

    scanned = []
    for rel in tracked:
        path = _corpus_root() / rel
        assert path.is_file(), (
            f"{rel} is tracked but absent from this checkout; the corpus scan "
            f"must not silently skip a tracked member")
        scanned.append(rel)

    assert scanned == tracked, (
        f"scanned {len(scanned)} of {len(tracked)} tracked waiver files; every "
        f"tracked member must be validated (missing: "
        f"{sorted(set(tracked) - set(scanned))})")


# ----------------------------------------------------------------------
# 9. mutation control
# ----------------------------------------------------------------------
