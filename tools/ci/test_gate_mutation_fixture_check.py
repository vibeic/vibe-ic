"""The meta-gate must REFUSE, not merely report.

Every assertion here drives the real `gate_mutation_fixture_check.main` over a
scratch declaration site and a scratch fixture directory. Nothing greps the
source for reassuring words: a text match proves the file SAYS "refuse", and
this file exists because saying it is not the property worth having.

The two ACCEPT scenarios the requirement was written against are
`test_deleting_a_can_fail_fixture_is_refused` and
`test_a_new_gate_with_no_fixtures_is_refused`.
"""
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import gate_mutation_fixture_check as CHECK  # noqa: E402
import gate_mutation_fixtures as F  # noqa: E402

_REAL_SCRIPT = _HERE / "repo_hygiene_gates.sh"
_REAL_FIXTURES = _HERE / "gate_fixtures"
_REAL_DEBT = _HERE / "gate_fixture_debt.json"


# --- scratch world ----------------------------------------------------------
def _fixture_module(dirpath: Path, slug: str, gate: str,
                    can_pass: bool = True, can_fail: bool = True) -> Path:
    body = [f'GATE = {gate!r}', "from pathlib import Path"]
    if can_pass:
        body.append("def can_pass(work):\n    return Path(work)")
    if can_fail:
        body.append("def can_fail(work):\n    return Path(work), 'boom'")
    p = dirpath / f"{slug}.py"
    p.write_text("\n\n".join(body) + "\n")
    return p


def _script(dirpath: Path, labels) -> Path:
    lines = ["#!/usr/bin/env bash", 'ROOT=/x', 'PLUGIN=/x', 'PG=/x']
    for lb in labels:
        lines.append(f'run "{lb}"        "$ROOT" python3 "$PG/{F.slug(lb)}.py"')
    p = dirpath / "scratch_gates.sh"
    p.write_text("\n".join(lines) + "\n")
    return p


def _debt(dirpath: Path, entries) -> Path:
    p = dirpath / "debt.json"
    p.write_text(json.dumps(
        {"schema": 1,
         "entries": [{"gate": g, "why": w} for g, w in entries]}) + "\n")
    return p


def _run(script, fixtures, debt, capsys):
    rc = CHECK.main(["--script", str(script), "--fixtures", str(fixtures),
                     "--debt", str(debt)])
    cap = capsys.readouterr()
    return rc, cap.out + cap.err


@pytest.fixture
def world(tmp_path):
    """Two gates, both fully fixtured, an empty baseline: a clean world."""
    fx = tmp_path / "fixtures"
    fx.mkdir()
    labels = ["alpha gate", "bravo gate"]
    for lb in labels:
        _fixture_module(fx, F.slug(lb), lb)
    return _script(tmp_path, labels), fx, _debt(tmp_path, []), labels


# --- the clean world must be clean, or nothing below means anything ---------
def test_a_fully_fixtured_world_passes(world, capsys):
    script, fx, debt, _ = world
    rc, out = _run(script, fx, debt, capsys)
    assert rc == 0, out
    assert "2 gate(s) declared" in out
    assert "2 carry a CAN-FAIL fixture" in out
    assert "2 carry BOTH" in out


# --- ACCEPT 1 ---------------------------------------------------------------
def test_deleting_a_can_fail_fixture_is_refused(world, capsys):
    """Delete ONE gate's can-fail direction. The meta-gate must refuse."""
    script, fx, debt, labels = world
    victim = labels[0]
    _fixture_module(fx, F.slug(victim), victim, can_pass=True, can_fail=False)

    rc, out = _run(script, fx, debt, capsys)
    assert rc == 1, out
    assert "HALF" in out
    assert repr(victim) in out
    assert "has not been shown to discriminate" in out
    # and it is counted, not merely mentioned
    assert "1 carry a CAN-FAIL fixture" in out
    assert "1 carry BOTH" in out


def test_deleting_the_can_pass_half_is_refused_too(world, capsys):
    """The other direction is not optional either."""
    script, fx, debt, labels = world
    victim = labels[1]
    _fixture_module(fx, F.slug(victim), victim, can_pass=False, can_fail=True)
    rc, out = _run(script, fx, debt, capsys)
    assert rc == 1, out
    assert "HALF" in out and repr(victim) in out
    assert "quiet on a clean tree" in out


def test_deleting_the_whole_fixture_file_is_refused(world, capsys):
    script, fx, debt, labels = world
    (fx / f"{F.slug(labels[0])}.py").unlink()
    rc, out = _run(script, fx, debt, capsys)
    assert rc == 1, out
    assert "NEW-OR-UNEXCUSED" in out and repr(labels[0]) in out


# --- ACCEPT 2 ---------------------------------------------------------------
def test_a_new_gate_with_no_fixtures_is_refused(world, capsys):
    """Add a gate to the dispatcher and write it no fixtures at all."""
    script, fx, debt, labels = world
    newcomer = "charlie gate"
    _script(script.parent, labels + [newcomer])

    rc, out = _run(script, fx, debt, capsys)
    assert rc == 1, out
    assert "NEW-OR-UNEXCUSED" in out
    assert repr(newcomer) in out
    assert "lands with both directions or it does not land" in out
    assert "3 gate(s) declared" in out


def test_a_new_gate_cannot_buy_its_way_in_with_one_fixture(world, capsys):
    script, fx, debt, labels = world
    newcomer = "charlie gate"
    _script(script.parent, labels + [newcomer])
    _fixture_module(fx, F.slug(newcomer), newcomer, can_fail=False)
    rc, out = _run(script, fx, debt, capsys)
    assert rc == 1, out
    assert "HALF" in out and repr(newcomer) in out


# --- the baseline may only shrink -------------------------------------------
def test_a_baselined_gate_without_fixtures_passes(world, capsys):
    """That is what the baseline is FOR, and it must say so out loud."""
    script, fx, debt, labels = world
    (fx / f"{F.slug(labels[0])}.py").unlink()
    debt = _debt(script.parent, [(labels[0], "SUBJECT_FIXED — measured")])
    rc, out = _run(script, fx, debt, capsys)
    assert rc == 0, out
    assert "excuses 1 gate(s); it may only shrink" in out


def test_a_baseline_entry_that_outlived_its_reason_is_refused(world, capsys):
    """The gate now HAS both fixtures. The excuse must be deleted."""
    script, fx, debt, labels = world
    debt = _debt(script.parent, [(labels[0], "SUBJECT_FIXED — measured")])
    rc, out = _run(script, fx, debt, capsys)
    assert rc == 1, out
    assert "STALE BASELINE" in out
    assert "list of excuses nobody re-reads" in out


def test_a_baseline_entry_for_a_deleted_gate_is_refused(world, capsys):
    script, fx, debt, _ = world
    debt = _debt(script.parent, [("a gate nobody declares", "why")])
    rc, out = _run(script, fx, debt, capsys)
    assert rc == 1, out
    assert "STALE BASELINE" in out
    assert "no longer declares it" in out


def test_an_unreasoned_baseline_entry_is_refused(world, capsys):
    script, fx, debt, labels = world
    (fx / f"{F.slug(labels[0])}.py").unlink()
    debt = _debt(script.parent, [(labels[0], "   ")])
    rc, out = _run(script, fx, debt, capsys)
    assert rc == 1, out
    assert "UNREASONED BASELINE" in out


# --- drift the register cannot absorb ---------------------------------------
def test_a_renamed_gate_loses_its_fixture_loudly(world, capsys):
    """A rename must not silently carry the old evidence forward."""
    script, fx, debt, labels = world
    renamed = labels[:1] + ["bravo gate, renamed"]
    _script(script.parent, renamed)
    rc, out = _run(script, fx, debt, capsys)
    assert rc == 1, out
    assert "NEW-OR-UNEXCUSED" in out and "'bravo gate, renamed'" in out
    assert "fixture for no gate the dispatcher declares" in out


def test_a_fixture_whose_GATE_constant_disagrees_is_refused(world, capsys):
    """The filename says one gate and the module says another."""
    script, fx, debt, labels = world
    _fixture_module(fx, F.slug(labels[0]), "some other gate entirely")
    rc, out = _run(script, fx, debt, capsys)
    assert rc == 1, out
    assert "but the gate at" in out


def test_two_gates_that_slug_alike_are_refused(tmp_path, capsys):
    fx = tmp_path / "fixtures"
    fx.mkdir()
    labels = ["a/b gate", "a-b gate"]
    assert F.slug(labels[0]) == F.slug(labels[1])
    script = _script(tmp_path, labels)
    rc, out = _run(script, fx, _debt(tmp_path, []), capsys)
    assert rc == 1, out
    assert "share the fixture slug" in out
    assert "refused rather than resolved by guessing" in out


# --- "could not look" is never "looked and it was clean" --------------------
def test_a_missing_declaration_site_is_NOT_CHECKED_not_a_pass(tmp_path, capsys):
    fx = tmp_path / "fixtures"
    fx.mkdir()
    rc = CHECK.main(["--script", str(tmp_path / "absent.sh"),
                     "--fixtures", str(fx), "--debt", str(_debt(tmp_path, []))])
    out = capsys.readouterr().err
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_a_declaration_site_with_no_gates_is_NOT_CHECKED(tmp_path, capsys):
    fx = tmp_path / "fixtures"
    fx.mkdir()
    empty = tmp_path / "empty.sh"
    empty.write_text("#!/usr/bin/env bash\necho nothing\n")
    rc = CHECK.main(["--script", str(empty), "--fixtures", str(fx),
                     "--debt", str(_debt(tmp_path, []))])
    out = capsys.readouterr().err
    assert rc == 2, out
    assert "declares NO gate" in out
    assert "neither is a pass" in out


# --- the real repository ----------------------------------------------------
def test_the_real_repo_is_clean_under_this_gate(capsys):
    """This is the assertion that blocks a landing."""
    rc = CHECK.main([])
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err


def test_the_real_census_denominator_is_the_declaration_site(capsys):
    """The three published numbers come from the dispatcher, not from a list."""
    c = CHECK.census()
    assert c["declared"] == len(F.declarations()), c["declared"]
    assert c["declared"] > 0
    assert c["with_both"] == len(c["both"])
    assert c["with_can_fail"] >= c["with_both"]


def test_every_real_baseline_entry_carries_a_reason():
    debt = F.load_debt(_REAL_DEBT)
    assert debt.get("entries"), "an empty baseline over an unfixtured tree " \
                                "would be a silently generous census"
    for e in debt["entries"]:
        assert e.get("why", "").strip(), e


def test_every_real_fixture_declares_the_gate_it_is_named_for():
    declared = {d.label for d in F.declarations()}
    for slug_, fx in F.load_fixtures(_REAL_FIXTURES).items():
        assert fx.gate in declared, f"{fx.path.name} names {fx.gate!r}"
        assert F.slug(fx.gate) == slug_, fx.path.name
        assert fx.has_can_pass and fx.has_can_fail, fx.path.name
