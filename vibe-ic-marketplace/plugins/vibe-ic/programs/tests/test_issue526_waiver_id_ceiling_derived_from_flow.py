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

import waivers_schema_check as wsc  # noqa: E402

FCC = PROGRAMS / "flow_compliance_check.py"
WSC = PROGRAMS / "waivers_schema_check.py"
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


def _run_fcc(project, report):
    return subprocess.run(
        [sys.executable, str(FCC), str(project), "--json", str(report)],
        capture_output=True, text=True, timeout=60, cwd=str(project))


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
    assert wsc.flow_max_step() == expected
    # and it is NOT the number that was hand-typed — otherwise this test
    # would pass on the unfixed code by coincidence.
    assert expected != STALE_CEILING, (
        "the flow's maximum has become 40; this regression can no longer "
        "distinguish a derived ceiling from the hand-typed one, so the "
        "fixture-flow tests below are now the only guard")


def test_derived_id_set_is_the_flows_own_step_list():
    assert set(wsc.flow_step_ids()) == set(_declared_ids_independently())


def test_every_id_the_flow_declares_is_accepted(tmp_path):
    """The wide check. Nine of these failed at v1.7.85 — 41-44 plus the
    alphabetic D1/FS1/DT1-DT3 — and each failure deleted a whole report."""
    rejected = {}
    for n, sid in enumerate(_declared_ids_independently()):
        p = _project(tmp_path, _entry(sid), name=f"p{n}")
        findings, _ = wsc.validate(p)
        bad = [f.rule for f in findings
               if f.rule in ("id-range", "id-missing",
                             "id-noncanonical-spelling")]
        if bad:
            rejected[sid] = bad
    assert rejected == {}, f"flow-declared ids rejected by the validator: {rejected}"


def test_the_nine_ids_that_regressed_are_named_explicitly(tmp_path):
    """Belt-and-braces on the exact population #526 was measured over, so a
    future narrowing of the derivation cannot quietly re-break them."""
    for n, sid in enumerate([41, 42, 43, 44, "D1", "FS1", "DT1", "DT2", "DT3"]):
        p = _project(tmp_path, _entry(sid), name=f"n{n}")
        findings, _ = wsc.validate(p)
        assert _rules(findings, "error") == [], (
            f"id={sid!r} still rejected: {_rules(findings)}")


def test_alphabetic_flow_ids_are_matched_case_insensitively(tmp_path):
    p = _project(tmp_path, _entry("dt3"))
    findings, _ = wsc.validate(p)
    assert _rules(findings, "error") == []


# ----------------------------------------------------------------------
# 2. the ceiling MOVES with the flow — proven on a fixture, not the real flow
# ----------------------------------------------------------------------

def test_ceiling_moves_when_the_fixture_flow_gains_a_step(tmp_path):
    small = _write_fixture_flow(tmp_path / "small" / "flow.yaml", range(1, 11))
    grown = _write_fixture_flow(tmp_path / "grown" / "flow.yaml", range(1, 13))
    assert wsc.flow_max_step(small) == 10
    assert wsc.flow_max_step(grown) == 12

    p = _project(tmp_path, _entry(12))
    assert "id-range" in _rules(wsc.validate(p, flow_def=small)[0])
    assert "id-range" not in _rules(wsc.validate(p, flow_def=grown)[0])


def test_a_new_alphabetic_stage_id_is_picked_up_from_the_flow(tmp_path):
    """A scalar ceiling could never do this — which is why the derivation
    yields an id SET. `ZZ1` matches no pattern in the validator."""
    flow = tmp_path / "z" / "flow.yaml"
    flow.parent.mkdir(parents=True)
    flow.write_text(yaml.safe_dump({"steps": [
        {"id": 1, "name": "a"}, {"id": "ZZ1", "name": "b"}]}))
    p = _project(tmp_path, _entry("ZZ1"))
    assert "id-range" not in _rules(wsc.validate(p, flow_def=flow)[0])
    # ...and against the REAL flow, which declares no ZZ1, it is reported.
    assert "id-range" in _rules(wsc.validate(p)[0])


def test_unreadable_flow_degrades_to_the_documented_fallback(tmp_path):
    missing = tmp_path / "nope" / "flow.yaml"
    assert wsc.flow_step_ids(missing) == frozenset()
    assert wsc.flow_max_step(missing) is None
    p = _project(tmp_path, _entry(1))
    _, summary = wsc.validate(p, flow_def=missing)
    assert summary["max_step"] == wsc.FALLBACK_MAX_STEP
    assert summary["max_step_source"] == "fallback-flow-unreadable"


def test_summary_discloses_where_the_ceiling_came_from(tmp_path):
    p = _project(tmp_path, _entry(1))
    _, derived = wsc.validate(p)
    assert derived["max_step_source"] == "derived-from-flow"
    assert derived["max_step"] == wsc.flow_max_step()
    _, override = wsc.validate(p, max_step=77)
    assert override["max_step_source"] == "caller-override"
    assert override["max_step"] == 77


# ----------------------------------------------------------------------
# 3. --max-step survives as an OVERRIDE, but cannot un-declare a flow step
# ----------------------------------------------------------------------

def test_caller_supplied_stale_ceiling_cannot_reject_a_flow_step(tmp_path):
    """THE consumer-reaching property.

    `flow_compliance_check._load_waivers` has its own `max_step: int = 40`
    and passes it explicitly, so correcting only this module's DEFAULT would
    have fixed nothing where it mattered. Flow membership wins.
    """
    p = _project(tmp_path, _entry(44))
    findings, _ = wsc.validate(p, max_step=STALE_CEILING)
    assert _rules(findings) == [], (
        "a caller's stale ceiling still rejects a step the flow declares — "
        "the defect survives at exactly the call site that reported it")


def test_max_step_override_still_extends_beyond_the_flow(tmp_path):
    """`--max-step` keeps its job: reaching ids the flow does not declare.

    What it is no longer needed FOR is the flow's own steps — that is the
    #526 half of this test, and the reason it is one test: the override is
    for a flow this program cannot read, never a workaround for a ceiling
    that has drifted below the flow it validates against.
    """
    beyond = _project(tmp_path, _entry(50), name="beyond")
    assert "id-range" in _rules(wsc.validate(beyond)[0])
    assert "id-range" not in _rules(wsc.validate(beyond, max_step=60)[0])

    declared = _project(tmp_path, _entry(44), name="declared")
    assert _rules(wsc.validate(declared)[0]) == [], (
        "a step the flow declares still needs --max-step to be accepted")


# ----------------------------------------------------------------------
# 4. an id genuinely outside the flow is STILL reported
# ----------------------------------------------------------------------

@pytest.mark.parametrize("sid", [999, -1, 45, "banana", "A99", "M99"])
def test_id_that_names_no_flow_step_is_reported_but_is_not_fatal(tmp_path, sid):
    """Two halves, and BOTH are load-bearing.

    Reported — the derivation must not have turned the range check into a
    rubber stamp. Not fatal — such an id is inert in the consumer (it is
    filed under a key no flow step has), so an error would withhold nothing
    and delete the report that says so. Asserting the severity is what makes
    this a #526 regression rather than a guard that passes either way.
    """
    p = _project(tmp_path, _entry(sid))
    findings, _ = wsc.validate(p)
    assert "id-range" in _rules(findings), (
        f"id={sid!r} names no flow step and must not pass silently")
    assert "id-range" not in _rules(findings, "error"), (
        f"id={sid!r} is inert in the consumer, so reporting it must not cost "
        f"the reader the whole compliance report")
    assert "id-range" in _rules(findings, "warning")


def test_strict_ids_restores_the_hard_exit_for_standalone_gate_use(tmp_path):
    p = _project(tmp_path, _entry(999))
    lenient = subprocess.run([sys.executable, str(WSC), str(p)],
                             capture_output=True, text=True, timeout=60)
    strict = subprocess.run([sys.executable, str(WSC), str(p), "--strict-ids"],
                            capture_output=True, text=True, timeout=60)
    assert lenient.returncode == 0, lenient.stdout
    assert strict.returncode == 1, strict.stdout
    assert "id-range" in strict.stdout


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
    proc = _run_fcc(p, report)
    assert report.is_file(), (
        f"id={sid}: no compliance report was produced.\n{proc.stderr[-2000:]}")
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
        _run_fcc(proj, report)
        assert report.is_file(), f"{name}: no report"
        for st in json.loads(report.read_text())["steps"]:
            if st.get("id") == 44:
                return st.get("status")
        pytest.fail("step 44 absent from the report")

    assert build("bare", False) == "MISSING"
    assert build("waived", True) == "WAIVED"


# ----------------------------------------------------------------------
# 6. the hole a wholesale downgrade would have opened
# ----------------------------------------------------------------------

@pytest.mark.parametrize("sid", ["39", 39.5])
def test_an_id_the_consumer_coerces_onto_a_real_step_is_validated_in_full(
        tmp_path, sid):
    """`_load_waivers` parses ids with a looser `int(v)`, so these land on
    REAL step 39 there while being invalid here. Skipping the entry would
    grant an exemption this program never checked. The rubber-stamp bar must
    still bite."""
    p = _project(tmp_path, _entry(sid, approver="agent"))
    findings, _ = wsc.validate(p)
    assert "id-noncanonical-spelling" in _rules(findings)
    assert "approver-self" in _rules(findings, "error"), (
        "the entry was skipped instead of validated — the consumer would "
        "waive step 39 on a self-approved waiver nobody checked")


def test_a_well_formed_coerced_id_is_disclosed_but_not_fatal(tmp_path):
    p = _project(tmp_path, _entry("39"))
    findings, _ = wsc.validate(p)
    assert _rules(findings, "error") == []
    assert _rules(findings, "warning") == ["id-noncanonical-spelling"]
    report = tmp_path / "coerced.json"
    _run_fcc(p, report)
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
    predicted = wsc._consumer_coerced_id(sid)
    assert predicted == 39, "the restatement itself changed"

    bare = tmp_path / "bare"
    bare.mkdir()
    bare_report = tmp_path / "bare.json"
    _run_fcc(bare, bare_report)
    assert bare_report.is_file()
    before = [s for s in json.loads(bare_report.read_text())["steps"]
              if s.get("id") == 39][0]["status"]

    waived = _project(tmp_path, _entry(sid), name="waived")
    waived_report = tmp_path / "waived.json"
    _run_fcc(waived, waived_report)
    assert waived_report.is_file(), "the coerced id took the report down"
    after = [s for s in json.loads(waived_report.read_text())["steps"]
             if s.get("id") == 39][0]["status"]

    assert before == "MISSING"
    assert after == "WAIVED", (
        f"the real compliance reader did NOT bind id={sid!r} to step "
        f"{predicted} (step 39 is {after!r}); `_consumer_coerced_id` has "
        f"drifted from `_load_waivers._parse_id`, and the severity rule that "
        f"depends on it is now deciding on a false premise")


def test_missing_id_key_stays_fatal_and_says_why(tmp_path):
    """`_load_waivers` does `w["id"]` on every `waived_steps` entry, so this
    shape kills the run whatever severity is chosen here. Keeping it an ERROR
    keeps the PRECISE message instead of the caller's bare
    "cannot parse waivers.json: 'id'"."""
    p = tmp_path / "noid"
    p.mkdir()
    (p / "waivers.json").write_text(json.dumps({"waived_steps": [
        {"reason": GOOD_REASON, "approver": "Jane Doe",
         "approved_at": "2026-07-01", "review_required": True}]}))
    findings, _ = wsc.validate(p)
    assert "id-missing" in _rules(findings, "error")
    proc = _run_fcc(p, tmp_path / "noid.json")
    assert "id-missing" in proc.stderr
    assert "cannot parse" not in proc.stderr


def test_id_null_is_not_fatal_because_the_consumer_survives_it(tmp_path):
    """`{"id": null}` is distinguishable from a missing key: the consumer's
    `w["id"]` succeeds and `_parse_id(None)` files it under a non-step."""
    p = _project(tmp_path, _entry(None))
    findings, _ = wsc.validate(p)
    assert _rules(findings, "error") == []
    assert "id-range" in _rules(findings, "warning")
    report = tmp_path / "null.json"
    _run_fcc(p, report)
    assert report.is_file()


# ----------------------------------------------------------------------
# 7. cascades_to carried the identical ceiling
# ----------------------------------------------------------------------

def test_cascades_to_accepts_a_step_the_flow_declares(tmp_path):
    p = _project(tmp_path, _entry(43, cascades_to=[44, "DT1"]))
    findings, _ = wsc.validate(p)
    assert _rules(findings, "error") == []
    assert "cascades-id-invalid" not in _rules(findings)
    # and under the caller's stale ceiling, which is what the real consumer
    # passes — the same property as
    # `test_caller_supplied_stale_ceiling_cannot_reject_a_flow_step`, for the
    # cascade list that carried the identical hand-typed ceiling.
    stale, _ = wsc.validate(p, max_step=STALE_CEILING)
    assert "cascades-id-invalid" not in _rules(stale)


def test_cascades_to_still_reports_a_child_that_names_nothing(tmp_path):
    p = _project(tmp_path, _entry(43, cascades_to=[999]))
    findings, _ = wsc.validate(p)
    assert "cascades-id-invalid" in _rules(findings)
    assert _rules(findings, "error") == []


# ----------------------------------------------------------------------
# 8. the corpus measurement — is this latent, or is a project reportless?
# ----------------------------------------------------------------------

def test_no_tracked_corpus_waiver_sits_above_the_stale_ceiling():
    """#526 asks whether any corpus waiver is in 41-44. MEASURED: none is.

    Every tracked hand-authored id is 6, 36 or 39, and every attestation
    entry names `drc`/`lvs` (both -> Step 31), so no tracked project was
    running without a compliance report. The defect was LATENT, and this test
    is what turns "latent" from an assertion into a measurement — if a future
    corpus file lands a 41-44 id, this fails and the reviewer learns that a
    project's report is at stake.
    """
    offenders = {}
    for path in sorted(REPO_ROOT.glob("benchmark-data/**/waivers.json")):
        doc = json.loads(path.read_text())
        for key in ("waived_steps", "waivers"):
            for e in doc.get(key) or []:
                if not isinstance(e, dict):
                    continue
                sid = e.get("id")
                if isinstance(sid, int) and STALE_CEILING < sid:
                    offenders[str(path)] = sid
    assert offenders == {}, (
        f"a tracked project waives a step above the old ceiling {offenders} "
        f"— before #526 that project produced NO compliance report at all")


def _tracked_corpus_waivers():
    """The git-TRACKED `benchmark-data/**/waivers.json` set, or None when git
    cannot answer.

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
    r = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "benchmark-data"],
        # 10s, not the 120s this first carried. These tests run under a 180s
        # pytest-timeout harness, so an inner bound is a slice of THAT budget --
        # 120s was two thirds of it for a call measured at 0.00s (the whole item
        # is 0.23s). An over-wide inner bound is the #1241 session-killer shape:
        # enough of them and the harness dies without emitting a verdict at all,
        # which greps as zero failures. 10s is ~43x the measured item.
        capture_output=True, timeout=10)
    if r.returncode != 0:
        return None
    out = r.stdout.decode("utf-8", "replace")
    return sorted(p for p in out.split("\0")
                  if p and p.split("/")[-1] == "waivers.json")


def test_every_tracked_corpus_waiver_file_validates_without_an_id_error():
    """The consumer-scoped half: run the REAL validator over every tracked
    waivers.json and assert none of them trips an id finding."""
    tracked = _tracked_corpus_waivers()
    if tracked is None:
        pytest.skip("not a git checkout / git unavailable — 'tracked' is "
                    "undecidable here, and a filesystem glob is not a "
                    "substitute (see _tracked_corpus_waivers)")

    # Non-vacuity that cannot rot: the corpus may shrink, but a scan of NOTHING
    # has not validated anything.
    assert tracked, ("no tracked waivers.json under benchmark-data/ — this test "
                     "certifies the corpus and cannot do so over an empty one")

    scanned = []
    for rel in tracked:
        path = REPO_ROOT / rel
        assert path.is_file(), (
            f"{rel} is tracked but absent from this checkout; the corpus scan "
            f"must not silently skip a tracked member")
        scanned.append(rel)
        findings, _ = wsc.validate(path.parent)
        bad = [f.rule for f in findings
               if f.rule in ("id-range", "id-missing",
                             "id-noncanonical-spelling")]
        assert bad == [], f"{path}: {bad}"

    assert scanned == tracked, (
        f"scanned {len(scanned)} of {len(tracked)} tracked waiver files; every "
        f"tracked member must be validated (missing: "
        f"{sorted(set(tracked) - set(scanned))})")


# ----------------------------------------------------------------------
# 9. mutation control
# ----------------------------------------------------------------------

def test_MUTATION_CONTROL_unfixed_code_fails_these(tmp_path, monkeypatch):
    """Executed proof that the acceptance tests above are not vacuous.

    The mutation restores the pre-#526 rule — the id vocabulary is the
    hand-typed `1..40` range and nothing is derived — by emptying the derived
    id set and pinning the ceiling back to 40. Every assertion that the fix
    exists must fail under it.
    """
    monkeypatch.setattr(wsc, "flow_step_ids", lambda flow_def=None: frozenset())
    monkeypatch.setattr(wsc, "flow_max_step", lambda flow_def=None: None)
    monkeypatch.setattr(wsc, "FALLBACK_MAX_STEP", STALE_CEILING)

    # the four integer ids the issue names
    for n, sid in enumerate([41, 42, 43, 44]):
        p = _project(tmp_path, _entry(sid), name=f"m{n}")
        assert "id-range" in _rules(wsc.validate(p)[0]), (
            f"id={sid} is accepted even with the derivation removed — the "
            f"acceptance test for it proves nothing")

    # the five alphabetic ids only an id SET can accept
    for n, sid in enumerate(["D1", "FS1", "DT1", "DT2", "DT3"]):
        p = _project(tmp_path, _entry(sid), name=f"a{n}")
        assert "id-range" in _rules(wsc.validate(p)[0]), (
            f"id={sid!r} is accepted even with the derivation removed")

    # the consumer-reaching property
    p = _project(tmp_path, _entry(44), name="stale")
    assert "id-range" in _rules(wsc.validate(p, max_step=STALE_CEILING)[0])

    # and the derivation itself
    assert wsc.flow_max_step() is None


def test_MUTATION_CONTROL_skipping_a_coerced_entry_hides_the_rubber_stamp(
        tmp_path, monkeypatch):
    """The second mutation: make the coerced-id branch unreachable (as the
    pre-fix `continue` did) and confirm the self-approval finding vanishes.
    Without this, `test_an_id_the_consumer_coerces_onto_a_real_step_is_
    validated_in_full` could pass for the wrong reason."""
    monkeypatch.setattr(wsc, "_consumer_coerced_id", lambda raw: object())
    p = _project(tmp_path, _entry("39", approver="agent"))
    findings, _ = wsc.validate(p)
    assert "approver-self" not in _rules(findings), (
        "the approver check fires even when the entry is skipped — the "
        "coercion test is not measuring what it claims to")
    assert "id-range" in _rules(findings)
