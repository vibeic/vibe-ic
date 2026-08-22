"""`tools/ci/pytest_finding_delta.py` — the report that reaches inside a both-red test.

Every case here is a PAIR where it matters: the same two reports, one thing
changed, opposite answers. A reporter that said "something is new" for every
input would be as useless as one that never did, and both look identical from a
single green case.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process node.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pytest_finding_delta as D  # noqa: E402


def _report(name: str, findings: list) -> str:
    """A minimal pytest text report with one failing test and its `E ` lines."""
    body = "\n".join(f"E       {f}" for f in findings)
    return (
        "=================================== FAILURES ===================================\n"
        f"_________________________________ {name} _________________________________\n"
        f"{body}\n"
        "=========================== short test summary info ============================\n"
        f"FAILED tools/ci/test_thing.py::{name}\n"
        "1 failed in 0.10s\n"
    )


def _run(tmp_path, base_findings, cand_findings, capsys):
    b = tmp_path / "base.txt"
    c = tmp_path / "cand.txt"
    b.write_text(_report("test_thing", base_findings), encoding="utf-8")
    c.write_text(_report("test_thing", cand_findings), encoding="utf-8")
    rc = D.main(["--base", str(b), "--candidate", str(c)])
    return rc, capsys.readouterr().out


def test_a_finding_introduced_inside_an_already_red_test_is_reported(tmp_path, capsys):
    """The whole reason the program exists, in its smallest form."""
    rc, out = _run(tmp_path, ["boom: 1 problem", "- UNEXCUSED: 'alpha'"],
                   ["boom: 2 problems", "- UNEXCUSED: 'alpha'",
                    "- UNEXCUSED: 'beta'"], capsys)
    assert rc == 1
    assert "NEW FINDING INSIDE AN ALREADY-RED TEST: - UNEXCUSED: 'beta'" in out
    assert "tools/ci/test_thing.py::test_thing" in out, \
        "the banner name must be resolved to the fully qualified id"


def test_the_same_red_saying_the_same_thing_is_not_reported(tmp_path, capsys):
    """The pair. Identical failure text must be silent, or every batch is noise."""
    same = ["boom: 1 problem", "- UNEXCUSED: 'alpha'"]
    rc, out = _run(tmp_path, same, list(same), capsys)
    assert rc == 0
    assert "NEW FINDING" not in out
    assert "No finding was introduced" in out


def test_digits_are_not_normalised_away(tmp_path, capsys):
    """A normaliser that ate an enumerated count would be a false-green generator.

    This is the one normalisation rule whose ABSENCE is load-bearing, so it is
    pinned rather than left to the module docstring.
    """
    rc, out = _run(tmp_path, ["gate_check: 6 finding(s)"],
                   ["gate_check: 8 finding(s)"], capsys)
    assert rc == 1
    assert "8 finding(s)" in out


def test_run_to_run_noise_is_normalised_and_does_not_report(tmp_path, capsys):
    """The other half: temp paths, addresses and durations differ between two runs
    of the SAME tree. Reporting those would drown the signal above."""
    rc, out = _run(
        tmp_path,
        ["cannot open /tmp/synthetic_repo.aaaa111/x.py at 0x7f00deadbeef [12s]"],
        ["cannot open /tmp/synthetic_repo.bbbb222/x.py at 0x7f11cafef00d [47s]"],
        capsys)
    assert rc == 0, out
    assert "NEW FINDING" not in out


def test_a_report_with_no_failures_block_REFUSES_and_does_not_pass(tmp_path, capsys):
    """`-q` with no tracebacks yields no `E ` lines. Answering 0 there would be a
    manufactured pass: a comparison that could not look must never reach a reader
    as one that looked and was favourable."""
    b = tmp_path / "b.txt"
    c = tmp_path / "c.txt"
    b.write_text("1 failed in 0.10s\n", encoding="utf-8")
    c.write_text("1 failed in 0.10s\n", encoding="utf-8")
    rc = D.main(["--base", str(b), "--candidate", str(c)])
    out = capsys.readouterr().out
    assert rc == 2
    assert "CANNOT CHECK" in out
    assert "not a pass" in out


def test_a_test_red_on_only_one_side_is_left_to_the_id_differential(tmp_path, capsys):
    """Scope. A newly-red test is exactly what NEW_RED already reports; claiming it
    here would double-count it and blur which instrument found what."""
    b = tmp_path / "b.txt"
    c = tmp_path / "c.txt"
    b.write_text("no failures here\n=== 1 passed in 0.1s\n", encoding="utf-8")
    c.write_text(_report("test_thing", ["boom"]), encoding="utf-8")
    rc = D.main(["--base", str(b), "--candidate", str(c)])
    out = capsys.readouterr().out
    assert "sections RED ON BOTH SIDES: 0" in out
    assert rc == 0
    assert "NEW FINDING" not in out


def test_the_predicate_is_PRINTED_not_merely_applied(tmp_path, capsys):
    """A count whose predicate is printed can be reconciled against someone else's;
    one whose predicate is implicit gets reconciled by argument. Measured on this
    repo: two honest censuses of one fixture disagreed 6 vs 3 for exactly this
    reason."""
    _, out = _run(tmp_path, ["a"], ["a"], capsys)
    assert "finding predicate :=" in out
    assert "`E ` prefix" in out
    assert "digits are NOT normalised" in out
    for _, rep, _why in D.NORMALISERS:
        assert rep in out, f"normaliser {rep} is applied but never disclosed"


def test_it_is_wired_to_nothing_and_that_is_deliberate():
    """It must not become a landing gate without a decision nobody has made:
    failure text carries noise, and a landing gate that refuses on noise deadlocks
    main. If someone wires it, this test fails and they have to say so here."""
    repo = HERE.parent.parent
    for script in (repo / "tools" / "ci" / "repo_hygiene_gates.sh",
                   repo / "tools" / "gatekeeper-land-differential.sh",
                   repo / "tools" / "gatekeeper-land.sh"):
        if script.is_file():
            assert "pytest_finding_delta" not in script.read_text(encoding="utf-8"), (
                f"{script.name} now invokes pytest_finding_delta. It is a REPORT, "
                "not a gate — promoting it is a policy decision about deadlock vs "
                "false green. Make that decision explicitly and update this test.")
