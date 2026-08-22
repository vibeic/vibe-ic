"""A shrink-only recording must be incapable of ADDING. Both directions.

THE THING BEING PROVEN, AND WHY A "IT SHRANK CORRECTLY" TEST IS NOT IT.
`--write-baseline` also shrinks correctly. What separates a recording of a paid
debt from an amnesty is the ADD direction, and that direction is the one nobody
exercises by accident: it only fires on the days a payment and a regression land
together, which is exactly when the operator is being told to run the flag.

So the ADD arm is first here, and it is asserted at three levels:

  * the pure expression (`shrunk`), which is a subset of `previous` for every
    possible pair of inputs and therefore cannot be talked into adding;
  * the WRITER (`write_shrunk`), which re-checks the finished document, so a
    call site that builds its register from something other than `shrunk()` is
    refused rather than trusted;
  * each of the three real gates, driven over fixture registers, so the wiring
    is proven and not just the helper.

MEASURED, and it is why this file exists: before this change
`prose_polarity_consulted_check --write-baseline` guarded itself with
`len(now) > len(prev)`, a COUNT. On the tree this test was written against the
population read 213 with the baseline at 213 while ONE entry had left and ONE
had joined, so the flag the gate had just recommended exited 0 and recorded the
brand-new offender as accepted debt at unchanged size. Nothing in the diff
looked wrong: the register was the same length it had always been.

NO SHIPPED RECORD IS TOUCHED BY THIS FILE. Every register here is a fixture
under `tmp_path`; the gates are pointed at it with `--baseline`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _ratchet_baseline as R  # noqa: E402


# ---------------------------------------------------------------------------
# THE ADD DIRECTION. The path must refuse, at every level.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("previous,current", [
    (["a", "b"], ["a", "b", "c"]),            # a straight arrival
    (["a", "b"], ["a", "c"]),                 # ONE OUT, ONE IN — constant size
    ([], ["a"]),                              # arriving into an empty register
    (["a"], ["b", "c", "d"]),                 # wholesale replacement
])
def test_the_expression_can_never_return_an_entry_previous_lacked(
        previous, current):
    """`shrunk` is `previous & current`, so this holds for every input, not
    just the four spelled out here. The one-out-one-in case is listed by name
    because it is the case the count guard let through."""
    assert set(R.shrunk(previous, current)) <= set(previous)


def test_the_swap_that_the_count_guard_passed_is_recorded_as_a_removal_only():
    """The measured defect, as a unit. Same size in and out, and the arrival
    does NOT enter the register."""
    previous, current = ["paid", "old"], ["new", "old"]
    assert len(previous) == len(current), "the fixture is not the swap"
    assert R.shrunk(previous, current) == ["old"]
    assert R.departed(previous, current) == ["paid"]


def test_the_writer_refuses_a_document_that_adds_and_writes_nothing(tmp_path):
    """The guard is on the DOCUMENT, so a call site that ignored `shrunk()` is
    caught here rather than trusted."""
    path = tmp_path / "reg.json"
    path.write_text(json.dumps({"known": ["a", "b"]}), encoding="utf-8")
    with pytest.raises(R.ShrinkRefused) as exc:
        R.write_shrunk(path, {"known": ["a", "c"]},
                       previous_by_register={"known": ["a", "b"]})
    assert "c" in str(exc.value)
    assert json.loads(path.read_text())["known"] == ["a", "b"], (
        "the refusal wrote a partial document — a refusal that mutates its "
        "subject is not a refusal")


def test_the_writer_refuses_a_register_that_vanished(tmp_path):
    """A register that disappears is not a register that shrank: every recorded
    entry would read as paid on the next run."""
    path = tmp_path / "reg.json"
    with pytest.raises(R.ShrinkRefused):
        R.write_shrunk(path, {"other": []},
                       previous_by_register={"known": ["a"]})
    assert not path.exists()


def test_a_second_register_cannot_be_smuggled_past_a_clean_first_one(tmp_path):
    """Two registers, one honest and one adding. NOTHING is written — not even
    the clean half, because a partial write leaves the file asserting a
    measurement that was never agreed."""
    path = tmp_path / "reg.json"
    path.write_text(json.dumps({"a": ["x"], "b": ["y"]}), encoding="utf-8")
    with pytest.raises(R.ShrinkRefused):
        R.write_shrunk(path, {"a": [], "b": ["y", "z"]},
                       previous_by_register={"a": ["x"], "b": ["y"]})
    assert json.loads(path.read_text()) == {"a": ["x"], "b": ["y"]}


# ---------------------------------------------------------------------------
# THE SHRINK DIRECTION. It must RECORD — otherwise the arm above is a rule
# that refuses everything, which proves nothing.
# ---------------------------------------------------------------------------

def test_a_measured_tightening_is_written(tmp_path):
    path = tmp_path / "reg.json"
    R.write_shrunk(path, {"known": R.shrunk(["a", "b"], ["b"])},
                   previous_by_register={"known": ["a", "b"]})
    assert json.loads(path.read_text())["known"] == ["b"]


def test_the_report_names_the_entries_and_the_size_change():
    """"The baseline shrank" on its own is a disclosure a reader cannot check."""
    line = R.report_line("known", ["a", "b"], 10, 8)
    assert "a" in line and "b" in line
    assert "10" in line and "8" in line


def test_the_recording_path_is_not_the_flag_that_erases_a_regression():
    """The one-line reason this is not `--write-baseline` renamed."""
    assert R.RECORD_FLAG != "--write-baseline"


# ---------------------------------------------------------------------------
# THE THREE GATES, WIRED. Fixture registers only.
# ---------------------------------------------------------------------------

def _run(program, *args):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / program), *args],
        capture_output=True, text=True)


#: (program, register key, the JSON document shape that program writes)
_GATES = [
    ("gate_is_wired_check.py", "unwired"),
    ("prose_polarity_consulted_check.py", "known"),
]


@pytest.mark.parametrize("program,key", _GATES)
def test_the_gate_refuses_to_write_a_register_holding_an_invented_entry(
        program, key, tmp_path):
    """A register seeded with entries the tree does not have would SHRINK on a
    real run — which is the direction that must work. So the ADD direction is
    put to the gate the only way it can be, through `--write-baseline` on a
    register that is MISSING what the tree really holds: an empty one.

    Any real tree has offenders, so `--write-baseline` against an empty
    register is an add of everything, and it must be refused rather than
    recorded. This is the same shape as the measured swap, without needing the
    tree to contain a swap at the moment the test runs.
    """
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({key: ["a name the tree does not carry"]}),
                   encoding="utf-8")
    before = reg.read_text(encoding="utf-8")
    out = _run(program, "--write-baseline", "--baseline", str(reg))
    if out.returncode == 2:
        pytest.skip(f"{program} could not measure this tree: {out.stderr[:200]}")
    assert out.returncode == 1, (out.returncode, out.stdout, out.stderr)
    assert "ADDS entries" in out.stderr, out.stderr
    assert reg.read_text(encoding="utf-8") == before, (
        "the refusal rewrote the register anyway")


@pytest.mark.parametrize("program,key", _GATES)
def test_the_gate_records_a_shrink_and_adds_nothing_while_doing_it(
        program, key, tmp_path):
    """The SHRINK arm on the real gates.

    The register is seeded with everything the tree really holds PLUS one
    invented entry, so the only legal move is to drop the invention. What must
    not happen is the register coming back with anything the seed lacked.
    """
    reg = tmp_path / "reg.json"
    probe = _run(program, "--json", str(tmp_path / "now.json"),
                 "--baseline", str(reg))
    if probe.returncode == 2 and not (tmp_path / "now.json").exists():
        pytest.skip(f"{program} could not measure this tree")
    measured = json.loads((tmp_path / "now.json").read_text())
    now = measured.get({"unwired": "unwired",
                        "known": "polarity_blind"}[key], [])
    assert now, f"{program} measured an empty population; nothing to shrink"
    seeded = sorted(set(now) | {"an entry the tree does not carry"})
    reg.write_text(json.dumps({key: seeded}), encoding="utf-8")

    out = _run(program, R.RECORD_FLAG, "--baseline", str(reg))
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    recorded = json.loads(reg.read_text())[key]
    assert set(recorded) <= set(seeded), (
        f"{program} added {sorted(set(recorded) - set(seeded))} through the "
        f"shrink path")
    assert "an entry the tree does not carry" not in recorded, (
        "the tightening was not recorded")


def test_flow_gate_enforcement_reports_a_paid_entry_instead_of_failing_on_it(
        tmp_path):
    """The third gate, whose read path FAILED on a shrink outright.

    A ratchet that fails when it tightens makes "fix nothing" the cheapest way
    to stay green. The register is seeded with an entry the audit does not
    measure — a debt that has been paid — and the audit must report it and
    exit 0.
    """
    reg = tmp_path / "reg.json"
    # SEEDED EMPTY FIRST, because an ABSENT register is rc 2 BEFORE the audit
    # runs — so `--json` would never be written and this test would report a
    # skip that reads like "the tree could not be measured". An empty register
    # is a readable measurement, which is what the report needs.
    reg.write_text(json.dumps({"known": [], "undeclared_known": []}),
                   encoding="utf-8")
    probe = _run("flow_gate_enforcement_audit.py", "--json",
                 str(tmp_path / "rep.json"), "--baseline", str(reg))
    if not (tmp_path / "rep.json").exists():
        pytest.skip(f"the audit could not read this tree: {probe.stderr[:200]}")
    rep = json.loads((tmp_path / "rep.json").read_text())
    now_u = sorted(f"undeclared::{u['gate']}"
                   for u in (rep.get("undeclared_audit_only") or []))
    reg.write_text(json.dumps({
        "known": [], "undeclared_known": now_u + ["undeclared::a_paid_debt"]}),
        encoding="utf-8")

    out = _run("flow_gate_enforcement_audit.py", "--baseline", str(reg))
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    assert "TIGHTENED" in out.stdout, out.stdout
    assert "a_paid_debt" in out.stdout
    assert "--write-baseline" not in out.stdout, (
        "the audit still points a reader at the flag that would ALSO record "
        "this run's new findings as accepted debt")

    # AND IT RECORDS, through the path that cannot add.
    rec = _run("flow_gate_enforcement_audit.py", R.RECORD_FLAG,
               "--baseline", str(reg))
    assert rec.returncode == 0, (rec.returncode, rec.stdout, rec.stderr)
    after = json.loads(reg.read_text())["undeclared_known"]
    assert "undeclared::a_paid_debt" not in after
    assert set(after) <= set(now_u + ["undeclared::a_paid_debt"])


def test_a_grown_register_still_fails_the_read_path(tmp_path):
    """The direction that must NOT have changed. A ratchet that stopped failing
    on growth would be no ratchet at all, and every assertion above would still
    pass."""
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"known": [], "undeclared_known": []}),
                   encoding="utf-8")
    out = _run("flow_gate_enforcement_audit.py", "--baseline", str(reg))
    assert out.returncode == 1, (out.returncode, out.stdout, out.stderr)
    assert "NEW" in out.stdout, out.stdout
