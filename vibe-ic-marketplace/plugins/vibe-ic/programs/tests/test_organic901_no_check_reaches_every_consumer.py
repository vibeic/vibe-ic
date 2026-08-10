#!/usr/bin/env python3
"""vibe-ic#901, second half — EVERY consumer of a gate verdict, not the first one.

THE DEFECT, RESTATED AT THE RIGHT LAYER. A gate may exit 0 having written
`{"verdict": "NOT_APPLICABLE"}` into the report the caller itself named with
`--json`. Six gates did exactly that on an empty project. The first fix taught
`flow_compliance_check` to open that file — correct, and not enough:

  * a SEVENTH producer (`post_route_signoff_corner_check`, the `sta_corner`
    step) writes the same disclosure and was not among the six; and
  * a SECOND consumer, `phase3_one_shot_runner`'s declared-sign-off roll-up,
    maps rc 0 straight to `PASS`. On a run where `sta_corner` reported
    NOT_APPLICABLE the roll-up counted it in `passed`, left `not_checked`
    EMPTY, and the headline read `4 of 5 declared sign-off gate(s) PASSED` —
    the one field that exists to carry "this gate checked nothing" staying
    empty precisely when a gate checked nothing.

Two producers and two consumers is a CONTRACT, not a bug in whichever consumer
was found first. So the predicate lives once in `_gate_report_verdict` and this
file is the enumeration the issue asks for.

HOW THIS FILE ENUMERATES — BY RUNNING, NOT BY READING. Each consumer is driven
end to end over a synthetic project whose gate really is a separate process that
really writes a report and really exits 0, and every assertion reads the value
the consumer EMITS: a `StepResult` as `dataclasses.asdict` gives it, and the
roll-up dict that lands in `reports/orchestrator/phase3_one_shot.json`. Nothing
here greps a source file for a call — a consumer wired to the contract and then
broken downstream would still pass such a check, and that is the failure mode
this issue is made of.

BOTH DIRECTIONS, FOR EVERY CONSUMER. A gate whose report says `PASS` must still
be counted as passing, with no disclosure attached. A rule that could only ever
answer "not a pass" would make the passing verdict unreachable, which is the
same defect with its sign flipped — and it is the shape that got the first
attempt at #901 withdrawn (v1.10.14 → v1.10.18), so it is pinned rather than
assumed.

chip/PDK-AGNOSTIC: the fixture is a generated Python file and a directory tree.
No design name, no vendor, no part number, no PDK.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _gate_report_verdict as GRV          # noqa: E402
import flow_compliance_check as FCC         # noqa: E402
import phase3_one_shot_runner as P3         # noqa: E402

#: A gate, as a real program: it writes the verdict it was told to write into
#: the `--json` path its caller chose, prints nothing that could be mistaken for
#: a disclosure, and exits 0. Every channel EXCEPT the report is deliberately
#: silent — that is the exact shape #901 is about.
_GATE_TEMPLATE = '''#!/usr/bin/env python3
import json, sys
from pathlib import Path
argv = sys.argv[1:]
out = None
for i, a in enumerate(argv):
    if a == "--json" and i + 1 < len(argv):
        out = argv[i + 1]
    elif a.startswith("--json="):
        out = a.split("=", 1)[1]
project = Path(argv[0]) if argv and not argv[0].startswith("-") else Path(".")
if out:
    p = Path(out)
    if not p.is_absolute():
        p = project / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"verdict": %(verdict)r,
                             "reasons": ["synthetic fixture"]}))
print("gate ran")
sys.exit(0)
'''

#: The name the phase-3 roll-up must be driven under. It has to be one the
#: roll-up DECLARES, because a name it does not declare is filtered out before
#: any counting happens — driving it with an invented name would produce a
#: green test over an empty denominator.
_DECLARED_NAME = "sta_corner"


def _write_gate(programs_dir: Path, verdict: str) -> str:
    """Materialise the synthetic gate; return its module name."""
    programs_dir.mkdir(parents=True, exist_ok=True)
    name = "organic901_synthetic_gate"
    (programs_dir / f"{name}.py").write_text(_GATE_TEMPLATE % {"verdict": verdict})
    return name


# ── consumer drivers ─────────────────────────────────────────────────────────
# Each returns (counted_as_passing, disclosure_text, emitted_object).
#
# `counted_as_passing` is each consumer's OWN notion of an unqualified pass,
# because the two speak different vocabularies: a step tier for
# `flow_compliance_check`, membership of the `passed` list for the roll-up.
# Forcing one word on both is what `_aggregate_verdict`'s own comment records
# having tried and rejected.

def _drive_flow_compliance(tmp_path: Path, verdict: str, monkeypatch):
    programs = tmp_path / "programs"
    gate = _write_gate(programs, verdict)
    monkeypatch.setattr(FCC, "PROGRAMS_DIR", programs)
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    step = {
        "id": 900,
        "name": "synthetic step",
        "stage": "stage3",
        "gate": {"program_exit_zero":
                 f"{gate} . --json reports/organic901.json"},
    }
    result = FCC.check_step(project, step, {}, None)
    emitted = dataclasses.asdict(result)
    reasons = [str(r) for r in emitted.get("reasons") or []]
    disclosure = "; ".join(r for r in reasons if "vacuous" in r.lower())
    counted_as_passing = (emitted.get("status") == "PASS" and not disclosure)
    return counted_as_passing, disclosure, emitted


def _drive_phase3_signoff_rollup(tmp_path: Path, verdict: str, monkeypatch):
    programs = tmp_path / "programs"
    gate = _write_gate(programs, verdict)
    monkeypatch.setattr(P3, "PROGRAMS_DIR", programs)
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    row = P3._run_declared_signoff_gate(
        project, _DECLARED_NAME, f"{gate}.py",
        "reports/phase3/organic901.json")
    plan = [row] + [P3.StepResult(n, "PASS", 0.0, "")
                    for n in P3.DECLARED_SIGNOFF_STEP_NAMES
                    if n != _DECLARED_NAME]
    rollup = P3.declared_signoff_rollup(plan)
    counted_as_passing = _DECLARED_NAME in rollup["passed"]
    disclosure = ""
    if _DECLARED_NAME in rollup["not_checked"]:
        disclosure = rollup["line"]
    return counted_as_passing, disclosure, rollup


#: THE ENUMERATION. Adding a consumer of a gate verdict without adding it here
#: is how #901 came to be fixed in one place and open in another.
CONSUMERS = (
    ("flow_compliance_check.check_step", _drive_flow_compliance),
    ("phase3_one_shot_runner.declared_signoff_rollup",
     _drive_phase3_signoff_rollup),
)


# ── direction 1: a disclosed no-check is never counted as a pass ─────────────

@pytest.mark.parametrize("consumer,drive", CONSUMERS,
                         ids=[c for c, _ in CONSUMERS])
def test_no_consumer_counts_a_disclosed_no_check_as_passing(
        tmp_path, monkeypatch, consumer, drive):
    """The defect, per consumer, read off the value the consumer emits."""
    passing, disclosure, emitted = drive(tmp_path, "NOT_APPLICABLE", monkeypatch)
    assert passing is False, (consumer, emitted)
    assert disclosure, (consumer, emitted)
    # and the disclosure must survive into the MACHINE-READABLE channel, since
    # that is what the run's report JSON is built from. A disclosure that only
    # ever reached a terminal is the same defect one layer down.
    assert disclosure in json.dumps(emitted), (consumer, emitted)


@pytest.mark.parametrize("verdict", sorted(GRV.NO_CHECK_VERDICTS))
@pytest.mark.parametrize("consumer,drive", CONSUMERS,
                         ids=[c for c, _ in CONSUMERS])
def test_every_no_check_word_is_honoured_by_every_consumer(
        tmp_path, monkeypatch, consumer, drive, verdict):
    """The contract is a SET, and a word honoured by one consumer and not the
    other is the two-consumer disagreement this module exists to prevent."""
    passing, disclosure, emitted = drive(tmp_path, verdict, monkeypatch)
    assert passing is False, (consumer, verdict, emitted)
    assert disclosure, (consumer, verdict, emitted)


# ── direction 2: the OPPOSITE verdict is still reachable ────────────────────

@pytest.mark.parametrize("consumer,drive", CONSUMERS,
                         ids=[c for c, _ in CONSUMERS])
def test_every_consumer_still_reaches_an_unqualified_pass(
        tmp_path, monkeypatch, consumer, drive):
    """A gate that really checked something must still be counted as passing,
    with NO disclosure attached. Without this, "not a pass" would be the only
    answer the rule can give and the rule would be worthless."""
    passing, disclosure, emitted = drive(tmp_path, "PASS", monkeypatch)
    assert passing is True, (consumer, emitted)
    assert disclosure == "", (consumer, emitted)


@pytest.mark.parametrize("consumer,drive", CONSUMERS,
                         ids=[c for c, _ in CONSUMERS])
def test_an_unrecognised_verdict_word_is_not_read_as_a_disclosure(
        tmp_path, monkeypatch, consumer, drive):
    """DIRECTION 2, sharper: the rule keys on the CONTRACT's words, not on the
    presence of a report. A gate writing a verdict nobody registered must be
    treated as substantive, or every new gate would silently downgrade."""
    passing, disclosure, emitted = drive(tmp_path, "GREEN", monkeypatch)
    assert passing is True, (consumer, emitted)
    assert disclosure == "", (consumer, emitted)


# ── the contract itself ─────────────────────────────────────────────────────

def test_the_enumeration_covers_both_known_consumers():
    names = {c for c, _ in CONSUMERS}
    assert len(CONSUMERS) >= 2, names
    assert "flow_compliance_check.check_step" in names, names
    assert "phase3_one_shot_runner.declared_signoff_rollup" in names, names


def test_both_consumers_read_one_definition_not_two():
    """Identity, not equality: two sets that happen to match today are two
    places to edit tomorrow, which is how the same report came to be read two
    ways in the first place."""
    assert FCC._VACUOUS_JSON_VERDICTS is GRV.NO_CHECK_VERDICTS
    assert P3._grv is GRV
    assert FCC._grv is GRV


def test_an_unreadable_report_is_not_a_disclosure(tmp_path):
    """A report that is absent, empty or unparseable must NOT be read as "the
    gate examined nothing" — that would convert every write failure into a
    silent downgrade. Asserted on the predicate's return value."""
    missing = tmp_path / "nope.json"
    empty = tmp_path / "empty.json"
    empty.write_text("")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    listy = tmp_path / "list.json"
    listy.write_text("[1, 2, 3]")
    for p in (missing, empty, broken, listy):
        assert GRV.report_declares_no_check(p) is False, p
    assert GRV.report_declares_no_check(None) is False
