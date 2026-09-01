"""#497 step 1 — the P0 umbrella's structured per-gate payload.

WHAT #497 IS ABOUT.  ``StepResult.reasons`` is an untyped prose list carrying
six distinct line shapes, and four independent consumers in
``flow_compliance_check`` re-derive its grammar from prefixes. Two of those
consumers are ``all(...)`` predicates, so a mis-parse changes a VERDICT, not a
report. Three production defects have come out of that one mechanism:

  1. the audit-JSON builder matched Form 1 only, so ``failed_gates`` came out
     EMPTY exactly when two or more gates failed;
  2. the #492 NOT-INVOKED disclosure was scraped as failing gate names — 76
     reported failures against 2 real ones;
  3. ``passed_gate_count`` scanned for ``PASS: <gate>`` lines the umbrella has
     never emitted, so it was structurally pinned at 0 for its whole existence.

Each was closed by adding another grammar rule. This step adds the replacement
instead: the umbrella states each gate's outcome ONCE, in a typed record, with
``NOT_INVOCABLE`` a first-class verdict rather than a phrase inside a skip
line. It is deliberately ADDITIVE — no consumer is cut over here, ``reasons``
is untouched, and no existing field changes value.

Issue #1968 subsequently closed the measured parser-silence population. The
enum retains ``NOT_INVOCABLE`` as the fail-closed outcome for a future drift,
while an ordinary real run must now contain none.

WHAT THESE TESTS ARE FOR.  The payload is only worth anything if it cannot
quietly disagree with the prose beside it. The load-bearing test here is
``test_prose_is_fully_regenerable_from_the_records``: it rebuilds all three
prose buckets FROM the records and requires them to equal, element for element,
the buckets the producer actually returned. A seventh line shape added without
a matching record — or a record whose message drifts from its line — fails it.
That round trip is what step 2 (cutting the consumers over) leans on: the
derivation in this test is the projection that will move into the module.

The tests drive the real umbrella (real argv construction, real dispatch, real
composition, real ``main()``) and read observable outputs — the returned
buckets, the published ``--json`` artefact, the printed operator listing. None
of them asserts on source text.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
sys.path.insert(0, str(PROGRAMS))
import _gate_invocation as _gi  # noqa: E402
import flow_compliance_check as F  # noqa: E402
import _spawn_stub  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _project_with_rtl(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "rtl").mkdir(parents=True)
    (proj / "rtl" / "top.v").write_text(
        "module top(input a, output b); assign b = a; endmodule\n")
    return proj


def _buckets_from_records(records):
    """Rebuild (fails, skips, waiver_gates) from the structured records ONLY.

    WHAT THIS MEANT AT STEP 1, AND WHAT IT MEANS NOW. When it was written the
    umbrella AUTHORED its prose buckets in the branch that decided each
    outcome, and this derivation existed to prove the records could reproduce
    them — the seam where a drift would have been a production defect. Step 3
    inverted the umbrella: the buckets are now themselves projected from the
    records, by ``_p0_buckets_from_records``. So the comparison below is no
    longer producer-versus-derivation; it is a SECOND, independently written
    implementation of the same projection, kept deliberately as a cross-check
    on the shipped one. The line shapes themselves are pinned as golden text in
    ``test_issue497_step3_reasons_is_a_derived_view``.
    """
    fails, skips, waived = [], [], []
    for r in records:
        v, name, msg, ev = (r["verdict"], r["name"], r["message"],
                            r["evidence"])
        if v == "FAIL":
            # Mirrors `_p0_fail_line_body`: a gate the umbrella KILLED gets a
            # sentence it wrote itself, with no em-dash. Two kill keys —
            # `stall_grace_s` today, `timeout_s` for records published when the
            # bound was a fixed wall clock.
            if "timeout_s" in ev:
                fails.append(f"FAIL: {name} timed out")
            elif "stall_grace_s" in ev:
                fails.append(f"FAIL: {name} {msg}")
            else:
                fails.append(f"FAIL: {name} — {msg}")
        elif v == "NOT_INVOCABLE":
            skips.append(_gi.format_not_invocable_entry(name, msg))
        elif v == "SKIP":
            # An input-missing skip renders as the bare gate name ONLY when
            # the gate exited 2 in silence. Where it stated a reason, that
            # reason travels beside the name exactly as every other skip
            # kind's does — a bare name cannot distinguish "this design has
            # no such layer" from "a producer never wrote the input".
            skips.append(name if (ev.get("skip_kind") == "input-missing"
                                  and not msg.strip())
                         else f"{name} (SKIP: {msg})")
        elif v in {"BLOCKED", "INCOMPLETE"}:
            skips.append(
                f"{name} ({v}: reason_class={r['reason_class']}: {msg})")
        elif v == "WAIVED":
            waived.append(name)
    return fails, skips, waived


@pytest.fixture(scope="module")
def real_run(tmp_path_factory):
    """ONE real dispatch of the whole registry, shared by several assertions.

    Real subprocesses, real exit codes, real classification — the anchor that
    keeps the rest of this file from being a test of a mock.
    """
    proj = _project_with_rtl(tmp_path_factory.mktemp("i497real"))
    records: list = []
    passed, fails, skips, waivers = F._run_structural_rtl_gates(
        proj, records_out=records)
    return types.SimpleNamespace(project=proj, passed=passed, fails=fails,
                                 skips=skips, waivers=waivers,
                                 records=records)


# ---------------------------------------------------------------------------
# 1. the payload exists, and is an exact partition of the registry
# ---------------------------------------------------------------------------
def test_one_record_per_registered_gate_in_registry_order(real_run):
    """Every registered gate states an outcome — including the ones that PASS.

    A passing gate contributes nothing to any of the three prose buckets, by
    construction. That is why ``passed_gate_count`` could never be recovered by
    reading ``reasons`` and reported 0 on every run in the artifact's history.
    """
    assert [r["name"] for r in real_run.records] == list(
        F._STRUCTURAL_RTL_GATES)


def test_verdicts_come_from_a_closed_enum(real_run):
    """A new outcome kind must be a change to an enum every consumer handles.

    Under the prose contract it was a new sentence every consumer ignored.
    """
    seen = {r["verdict"] for r in real_run.records}
    assert seen <= set(F.P0_GATE_VERDICTS)
    # the run must be non-trivial or the assertion above is vacuous
    assert {"PASS", "FAIL", "SKIP"} <= seen, seen
    assert "NOT_INVOCABLE" not in seen, seen


def test_issue1968_replaces_not_invocable_with_declared_na(real_run):
    """The old verdict remains reserved, but normal dispatch reaches zero."""
    ni = [r for r in real_run.records if r["verdict"] == "NOT_INVOCABLE"]
    assert ni == []
    derived_na = [r for r in real_run.records
                  if r["evidence"].get("skip_kind") ==
                  "declaration-not-present"]
    assert derived_na, "fixture must exercise declaration-derived N/A"
    assert all(r["verdict"] == "SKIP" and
               r["evidence"].get("invocation_contract") and
               "N/A" in r["message"] for r in derived_na)


def test_the_pass_population_is_the_registry_minus_the_other_outcomes(
        real_run):
    """The record partition and the registry subtraction must agree.

    Two independent derivations of the same number; if they ever disagree the
    partition has a hole. The subtraction used to be a shipped function
    (`_p0_passed_gate_count`) — the closest a bucket-only world could get to
    asking the gates. It is gone since step 4, and the arithmetic is kept here
    because it is still an honest second opinion on the count.
    """
    n_pass = sum(1 for r in real_run.records if r["verdict"] == "PASS")
    assert n_pass == (len(F._STRUCTURAL_RTL_GATES)
                      - len(real_run.fails) - len(real_run.skips)
                      - len(real_run.waivers))
    assert n_pass == F._p0_passed_count(real_run.records)
    assert n_pass > 0, "fixture must reach the passing population"


# ---------------------------------------------------------------------------
# 2. THE DRIFT TEST — prose and payload cannot disagree
# ---------------------------------------------------------------------------
def test_prose_is_fully_regenerable_from_the_records(real_run):
    """Every prose line the umbrella emits is reconstructible from a record.

    Element for element, in order. This is the seam #497 exists to protect: it
    fails if a new line shape is added without a record, if a record's message
    stops matching the line it stands for, or if the two orders drift.

    Since step 3 the shipped umbrella derives its buckets the same way, so this
    now cross-checks the shipped projection against a second implementation
    written from the record fields alone (see ``_buckets_from_records``).
    """
    d_fails, d_skips, d_waived = _buckets_from_records(real_run.records)
    assert d_fails == real_run.fails
    assert d_skips == real_run.skips
    assert d_waived == [w["gate"] for w in real_run.waivers]


def test_composed_reasons_name_exactly_the_non_passing_records(real_run):
    """Drive the real composer and check the two sides agree on WHO.

    ``_compose_p0_reasons`` is the producer every scraper parses. Each non-PASS
    record must be named somewhere in what it writes, and no PASS record may be
    (a passing gate has no line — the fact that made ``passed_gate_count``
    unrecoverable).
    """
    reasons = F._compose_p0_reasons(real_run.fails, real_run.skips,
                                    real_run.waivers)
    blob = "\n".join(reasons)
    for r in real_run.records:
        named = any(_line_names(line, r["name"]) for line in reasons)
        if r["verdict"] == "PASS":
            assert not named, (
                f"{r['name']} PASSed but is named in the reasons prose")
        else:
            assert named, (
                f"{r['name']} is recorded {r['verdict']} but appears nowhere "
                f"in the operator-facing prose")
    assert blob  # composition produced something


def _line_names(line: str, gate: str) -> bool:
    """Does this reason line name this gate, as a whole token?

    Gate names overlap by prefix (``self_rx_mask_check`` is a substring of
    ``tristate_self_rx_mask_check``), so a bare ``in`` test would over-match.
    """
    import re
    return bool(re.search(r"(?<![\w.])" + re.escape(gate) + r"(?![\w.])",
                          line))


def test_round_trip_covers_the_waived_shape(tmp_path, monkeypatch):
    """The WAIVED branch, reached through the real umbrella.

    The four thin-input waiver gates are made to FAIL and the project is
    thin-input eligible, so the umbrella converts them; the record must
    reproduce the waiver entry it stands for, ticket and all.
    """
    monkeypatch.setenv("VIBE_IC_COMPLIANCE_WORKERS", "1")
    proj = _project_with_rtl(tmp_path)
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES",
                        tuple(F._THIN_INPUT_WAIVER_GATES))
    # Anchored at the SPAWN (`subprocess.Popen`) rather than on
    # `F.subprocess.run`, so the stub survives the umbrella's launch moving
    # between helpers — see `_spawn_stub`.
    _spawn_stub.stub_spawn(
        monkeypatch, lambda _s: (1, "some gate said this first\n"))

    records: list = []
    passed, fails, skips, waivers = F._run_structural_rtl_gates(
        proj, allow_thin_input=True, records_out=records)

    assert waivers, "fixture must reach the waiver branch"
    assert not fails
    waived = [r for r in records if r["verdict"] == "WAIVED"]
    assert [r["name"] for r in waived] == [w["gate"] for w in waivers]
    for r, w in zip(waived, waivers):
        assert r["message"] == w["first_line"]
        assert r["evidence"]["ticket"] == w["ticket"]
        assert r["evidence"]["review_required"] is True
    assert _buckets_from_records(records) == (
        fails, skips, [w["gate"] for w in waivers])


def test_round_trip_covers_the_no_progress_and_missing_program_shapes(
        tmp_path, monkeypatch):
    """Two rarely-hit branches whose prose does NOT follow the common shape.

    A gate that made no forward progress writes ``FAIL: <gate> made no forward
    progress …`` with no em-dash, and a registry entry with no backing program
    writes a SKIP naming a file. Both are exactly the sort of one-off line that
    a prefix scraper mangles; both must round trip.

    THIS BRANCH CHANGED SHAPE, and the test follows it rather than being
    relaxed to accept either. The umbrella used to kill a gate on a fixed 60 s
    WALL CLOCK and record ``FAIL: <gate> timed out`` — a claim about the clock,
    written as a verdict about the design. It now bounds NO PROGRESS: a gate
    still moving is never killed, and one whose whole process tree is flat is
    killed and still FAILs, with a reason that says what was observed. So the
    stimulus is a stalled `SupervisedResult` — the shipped type, from the
    shipped module — and not a `TimeoutExpired` that this code can no longer
    raise.
    """
    monkeypatch.setenv("VIBE_IC_COMPLIANCE_WORKERS", "1")
    proj = _project_with_rtl(tmp_path)
    phantom = "zzz_never_authored_gate_check"
    assert not (PROGRAMS / f"{phantom}.py").exists()
    real_gate = F._STRUCTURAL_RTL_GATES[0]
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES", (real_gate, phantom))

    import _watchdog as _wd

    def _stalled(cmd, **kw):
        return _wd.SupervisedResult(_wd.RC_STALLED, "", "WATCHDOG_STALLED",
                                    "stalled", 61.0)

    monkeypatch.setattr(F._watchdog, "run_host_supervised", _stalled)

    records: list = []
    passed, fails, skips, waivers = F._run_structural_rtl_gates(
        proj, records_out=records)

    assert [r["name"] for r in records] == [real_gate, phantom]
    assert records[0]["verdict"] == "FAIL"
    assert records[1]["evidence"]["skip_kind"] == "no-backing-program"
    assert _buckets_from_records(records) == (fails, skips, [])


# ---------------------------------------------------------------------------
# 3. what the published artefacts and the operator see
# ---------------------------------------------------------------------------
def _run_main(tmp_path, extra=()):
    proj = _project_with_rtl(tmp_path)
    out = tmp_path / "report.json"
    rc = F.main([str(proj), "--json", str(out), "--lenient", *extra])
    return rc, json.loads(out.read_text()), proj


def test_json_report_publishes_the_payload_on_P0_and_null_elsewhere(
        tmp_path, capsys):
    """The serialised schema: one uniform key, explicitly null where unused.

    ``StepResult`` is shared by ~56 flow steps plus the A/M tracks and is
    serialised wholesale, so the field lands on every step. A key that were
    sometimes absent would make each consumer decide for itself what its
    absence means — the same re-derive-the-contract failure in a new place.
    """
    _rc, report, _proj = _run_main(tmp_path)
    capsys.readouterr()
    steps = {s["id"]: s for s in report["steps"]}
    p0 = steps["P0"]
    assert isinstance(p0["gate_records"], list) and p0["gate_records"]
    assert [r["name"] for r in p0["gate_records"]] == list(
        F._STRUCTURAL_RTL_GATES)
    others = [s for s in report["steps"] if s["id"] != "P0"]
    assert others, "fixture must contain non-P0 steps"
    assert all(s["gate_records"] is None for s in others), (
        "a step that publishes no structured records must say so as null, "
        "not as an empty list that reads as 'considered, and nothing found'")


def test_reasons_still_carries_the_whole_operator_facing_story(
        tmp_path, capsys):
    """`reasons` is untouched, and is still what the per-step listing renders.

    The disclosure moving out of ``reasons`` into a field of its own would undo
    #492, whose entire point was that unrun gates stop being invisible. Every
    reason line must still appear under P0 in the printed listing.
    """
    _rc, report, _proj = _run_main(tmp_path)
    printed = capsys.readouterr().out
    p0 = next(s for s in report["steps"] if s["id"] == "P0")
    assert p0["reasons"], "P0 must still explain itself in prose"
    for line in p0["reasons"]:
        assert f"└─ {line}" in printed, (
            f"reason line vanished from the operator listing: {line[:70]!r}")
    # #1968 replaces parser-silence disclosure with per-gate derived N/A.
    assert not any(_gi.is_not_invocable_heading(x.strip())
                   for x in p0["reasons"])
    assert _gi.NOT_INVOCABLE_HEADING_SENTINEL not in printed
    assert any("N/A from the design declaration roster" in x
               for x in p0["reasons"])


def test_records_are_empty_not_null_when_no_gate_was_considered(tmp_path):
    """Three states, and the difference between two of them is real.

    A project with no RTL dispatches nothing: the umbrella reports
    SKIPPED-CONDITION and its single reason line names no gate. That is
    "published, and no gate was considered" — ``[]`` — which is a different
    fact from a step that publishes no records at all (``None``).
    """
    proj = tmp_path / "nortl"
    (proj / "docs").mkdir(parents=True)
    (proj / "docs" / "readme.txt").write_text("no RTL here\n")
    out = tmp_path / "report.json"
    F.main([str(proj), "--json", str(out), "--lenient"])
    report = json.loads(out.read_text())
    p0 = next(s for s in report["steps"] if s["id"] == "P0")
    assert p0["status"] == "SKIPPED-CONDITION"
    assert p0["gate_records"] == []
    for line in p0["reasons"]:
        assert not any(_line_names(line, g)
                       for g in F._STRUCTURAL_RTL_GATES), (
            f"a no-gate line names a gate: {line!r}")


def test_the_audit_artifact_is_not_disturbed_by_the_addition(tmp_path):
    """phase23_completion_audit.json does NOT serialise StepResult.

    It projects its own keys, so adding a field to the dataclass leaves it
    untouched. Asserted so a later step that DOES change it has to do so
    deliberately.
    """
    _rc, _report, proj = _run_main(tmp_path)
    audit = json.loads(
        (proj / "reports" / "audit" /
         "phase23_completion_audit.json").read_text())
    assert "gate_records" not in audit
    assert "gate_records" not in json.dumps(audit.get("gates", []))
