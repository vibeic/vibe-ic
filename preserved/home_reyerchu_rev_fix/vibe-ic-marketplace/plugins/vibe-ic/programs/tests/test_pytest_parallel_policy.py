#!/usr/bin/env python3
"""#xdist — the corpus contains files that may not share a machine.

WHAT THIS PINS
==============
`pytest_per_file_junit._run_fallback_batch` launches every file in a wave
CONCURRENTLY against the SAME live tree — 8 wide by default, 32 in the
zero-record rescue. Two files in the shipped corpus PLANT a program into that
tree while they run, because the shipped resolvers they drive look up bare
program names in the real PROGRAMS directory and there is nowhere else to put
the fixture.

Measured 2026-08-17 on a 93-file selection under `pytest-xdist --dist
loadfile`, which is the same "N files at once over one tree" shape:

    n=8   2414 cases  verdict hash 09f2d3e7a8401e97   273.4 s
    n=16  2414 cases  verdict hash 35a6262dc8bd433a   367.8 s
    n=24  2414 cases  verdict hash d531e92ec6b7aa72   381.2 s

Same tree, same 2414 cases, same per-file case map, `git status --porcelain`
empty after each — and different verdicts. Two of the differences name their
own cause:

    test_issue833_analog_l5_vacuous_reaches_umbrella::
        test_the_gate_is_out_of_the_unrouted_inventory   FAIL at n=16, n=24
        AssertionError names Finding(gate='_i528_planted_unrouted_check', …)
    test_issue1130_wiring_population_parity::
        test_the_wiring_gates_state_their_denominator_on_a_clean_run[…]
                                                        FAIL at n=16, n=24

Both PASS serially and at n=8. A red produced by the SCHEDULE rather than by
the branch costs a whole landing round and says nothing true.

THE TESTS BELOW GO IN BOTH DIRECTIONS. The audit is driven over a corpus that
is clean (must PASS) and over one with a planted live-tree writer (must FAIL
and name it), and the scheduler is driven over a wave that reproduces the race
for real — with the roster empty it goes red, with the roster populated it does
not, same files, same widths, same machine.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = _PROGRAMS.parent
sys.path.insert(0, str(_PROGRAMS))

import pytest_parallel_policy as policy  # noqa: E402
import pytest_per_file_junit as driver  # noqa: E402


# ==========================================================================
# 1. THE ROSTER IS A DECLARATION WITH A REASON, NOT A LIST OF NAMES
# ==========================================================================
def test_every_rostered_file_exists_and_states_why():
    assert policy.SERIAL_ONLY, "an empty roster cannot isolate anything"
    for rel, reason in policy.SERIAL_ONLY.items():
        assert (_PLUGIN / rel).is_file(), (
            f"{rel} is on the serial roster but is not in the tree — a roster "
            f"that names files nobody runs protects nothing")
        assert len(reason.strip()) > 60, (
            f"{rel}: the roster entry must say what breaks, not just that "
            f"something does; got {reason!r}")


def test_the_two_measured_planters_are_rostered():
    """Named, because these two are why the roster exists."""
    for rel in ("programs/tests/test_gate_skip_routing_check.py",
                "programs/tests/test_flow_compliance_check_gate.py"):
        assert rel in policy.SERIAL_ONLY, (
            f"{rel} writes a program into the shipped tree while it runs; "
            f"removing it from the roster puts the n=16/n=24 false red back")


# ==========================================================================
# 2. THE AUDIT — driven both ways, so the roster cannot rot silently
# ==========================================================================
def _tree_with(tmp_path: Path, name: str, body: str) -> tuple[Path, list[str]]:
    """A miniature plugin tree carrying one test file."""
    tests = tmp_path / "programs" / "tests"
    tests.mkdir(parents=True)
    (tests / name).write_text(textwrap.dedent(body), encoding="utf-8")
    return tmp_path, [f"programs/tests/{name}"]


def test_the_shipped_corpus_matches_the_roster():
    """CAN-PASS. Every test file in the tree, audited for real."""
    corpus = sorted(
        str(p.relative_to(_PLUGIN))
        for p in (_PROGRAMS / "tests").glob("test_*.py"))
    assert len(corpus) > 100, (
        f"only {len(corpus)} test file(s) enumerated — the audit would be "
        f"passing over a population that is not the suite")
    ok, findings = policy.audit(_PLUGIN, corpus)
    assert ok, (
        "unrostered live-tree writer(s) in the shipped corpus:\n  - "
        + "\n  - ".join(findings))


def test_a_new_live_tree_writer_fails_the_audit(tmp_path):
    """CAN-FAIL. The planted defect the roster exists to catch."""
    root, corpus = _tree_with(tmp_path, "test_planted_writer.py", '''
        from pathlib import Path
        _PROGRAMS = Path(__file__).resolve().parent.parent

        def test_it():
            probe = _PROGRAMS / "_planted_probe.py"
            probe.write_text("# planted\\n")
            try:
                assert probe.exists()
            finally:
                probe.unlink()
        ''')
    ok, findings = policy.audit(root, corpus)
    assert not ok, "a test that writes into the shipped tree must be a finding"
    assert any("test_planted_writer.py" in f for f in findings), findings
    assert any("_planted_probe" in f or "probe.write_text" in f
               for f in findings), findings


def test_the_audit_does_not_fire_on_a_reader(tmp_path):
    """The false-positive control that the first scanner failed.

    `LIVE.read_text().replace(...)` is a READ. Twelve of the suite's files do
    exactly this, and the first version of the scanner called every one of them
    a tree writer — a gate that cries wolf about a read is a gate whose
    findings get skimmed.
    """
    root, corpus = _tree_with(tmp_path, "test_pure_reader.py", '''
        from pathlib import Path
        _PLUGIN = Path(__file__).resolve().parent.parent.parent

        def test_it():
            prose = (_PLUGIN / "README.md").read_text().replace("\\n", " ")
            assert isinstance(prose, str)
        ''')
    ok, findings = policy.audit(root, corpus)
    assert ok, findings


def test_the_audit_does_not_fire_on_tmp_path_reusing_a_live_name(tmp_path):
    """The second false-positive control: aliases are scoped to a function.

    The suite reuses `plugin`, `probe`, `d`, `p` for a shipped path in one test
    and a `tmp_path` child in the next. A file-wide alias set called eleven
    tmp_path writers tree writers.
    """
    root, corpus = _tree_with(tmp_path, "test_scoped_alias.py", '''
        from pathlib import Path
        _PLUGIN = Path(__file__).resolve().parent.parent.parent

        def test_reads_the_real_one():
            plugin = _PLUGIN / "programs"
            assert plugin.name == "programs"

        def test_writes_its_own(tmp_path):
            plugin = tmp_path / "plugins" / "vibe-ic"
            plugin.mkdir(parents=True)
            (plugin / "x.py").write_text("# scratch\\n")
        ''')
    ok, findings = policy.audit(root, corpus)
    assert ok, findings


def test_an_empty_corpus_is_not_a_pass(tmp_path):
    with pytest.raises(LookupError):
        policy.audit(tmp_path, [])


def test_the_cli_answers_both_ways(tmp_path):
    root, corpus = _tree_with(tmp_path, "test_planted_writer.py", '''
        from pathlib import Path
        _PROGRAMS = Path(__file__).resolve().parent.parent

        def test_it():
            (_PROGRAMS / "_planted_probe.py").write_text("# planted\\n")
        ''')
    sel = tmp_path / "sel.txt"
    sel.write_text("\n".join(corpus) + "\n", encoding="utf-8")
    red = subprocess.run(
        [sys.executable, str(_PROGRAMS / "pytest_parallel_policy.py"),
         "--audit", "--plugin-root", str(root), "--selection", str(sel)],
        capture_output=True, text=True, timeout=120)
    assert red.returncode == 1, red.stdout + red.stderr
    assert "[FAIL]" in red.stdout

    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    cannot = subprocess.run(
        [sys.executable, str(_PROGRAMS / "pytest_parallel_policy.py"),
         "--audit", "--plugin-root", str(root), "--selection", str(empty)],
        capture_output=True, text=True, timeout=120)
    assert cannot.returncode == 2, (
        "an empty corpus must be CANNOT-ASK, not a pass")


# ==========================================================================
# 3. THE PARTITION AND THE WAVE SPLIT — total, ordered, disjoint
# ==========================================================================
def test_partition_is_total_ordered_and_disjoint():
    selection = ["a.py", "programs/tests/test_gate_skip_routing_check.py",
                 "b.py", "c.py"]
    serial, parallel = policy.partition(selection)
    assert serial == ["programs/tests/test_gate_skip_routing_check.py"]
    assert parallel == ["a.py", "b.py", "c.py"]
    assert sorted(serial + parallel) == sorted(selection)
    assert not set(serial) & set(parallel)


def test_isolation_groups_never_seat_a_rostered_file_with_another():
    rostered = "programs/tests/test_gate_skip_routing_check.py"
    wave = [(1, "a.py"), (2, rostered), (3, "b.py"), (4, "c.py")]
    groups = driver._isolation_groups(wave)
    assert [g for g in groups if any(f in policy.SERIAL_ONLY for _i, f in g)] \
        == [[(2, rostered)]], groups
    # totality + order: concatenating the groups reproduces the wave exactly
    flat = [item for g in groups for item in g]
    assert flat == wave, (
        "the split must not drop, duplicate or reorder a single file — the "
        "caller merges by this order")


def test_isolation_groups_are_a_no_op_without_a_rostered_file():
    wave = [(1, "a.py"), (2, "b.py")]
    assert driver._isolation_groups(wave) == [wave], (
        "a wave with nothing rostered must stay ONE concurrent batch; "
        "serialising it would be pure lost time")


# ==========================================================================
# 4. THE RACE, RUN FOR REAL — the mutation fixture in both directions
# ==========================================================================
def _race_corpus(tmp_path: Path) -> tuple[Path, list[tuple[int, str]]]:
    """One planter that holds a marker in the shared tree, two scanners.

    This is the shipped shape in miniature: the planter must put its fixture
    where the subject looks, and the scanners' whole question is what is in
    that directory.
    """
    (tmp_path / "shared").mkdir(parents=True)
    (tmp_path / "test_planter.py").write_text(textwrap.dedent('''
        import time
        from pathlib import Path
        _SHARED = Path(__file__).resolve().parent / "shared"

        def test_plants_and_cleans_up():
            marker = _SHARED / "_planted_fixture.txt"
            marker.write_text("planted")
            try:
                time.sleep(3.0)
            finally:
                marker.unlink()
        '''), encoding="utf-8")
    for name in ("test_scanner_a.py", "test_scanner_b.py"):
        (tmp_path / name).write_text(textwrap.dedent('''
            import time
            from pathlib import Path
            _SHARED = Path(__file__).resolve().parent / "shared"

            def test_the_directory_holds_only_what_is_committed():
                deadline = time.monotonic() + 3.0
                seen = []
                while time.monotonic() < deadline:
                    seen = sorted(p.name for p in _SHARED.iterdir())
                    if seen:
                        break
                    time.sleep(0.05)
                assert seen == [], f"saw a foreign file: {seen}"
            '''), encoding="utf-8")
    wave = [(1, "test_planter.py"), (2, "test_scanner_a.py"),
            (3, "test_scanner_b.py")]
    return tmp_path, wave


def _run_wave(tmp_path: Path, wave, work: Path):
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    return driver._run_fallback_batch(
        argv, wave, work, 300.0, str(tmp_path))


def _reds(outcomes) -> int:
    return sum(o.result.red for o in outcomes)


@pytest.mark.timeout(300)
def test_the_race_is_real_when_nothing_is_rostered(tmp_path, monkeypatch):
    """CAN-FAIL: without the roster the wave manufactures a red.

    If this stops failing the guard below has stopped proving anything, so it
    is asserted rather than assumed.
    """
    root, wave = _race_corpus(tmp_path / "corpus")
    monkeypatch.setattr(policy, "SERIAL_ONLY", {})
    work = tmp_path / "w1"
    work.mkdir()
    outcomes = _run_wave(root, wave, work)
    assert all(o.result.has_record for o in outcomes), [
        o.log for o in outcomes]
    assert _reds(outcomes) > 0, (
        "the concurrent wave was supposed to let the scanners see the "
        "planted file; if it cannot, this fixture no longer models the "
        "measured n=16/n=24 failure and the guard below is vacuous")


@pytest.mark.timeout(300)
def test_the_roster_removes_the_red_without_removing_a_file(
        tmp_path, monkeypatch):
    """CAN-PASS: same files, same widths, same machine — no red, none skipped."""
    root, wave = _race_corpus(tmp_path / "corpus")
    monkeypatch.setattr(policy, "SERIAL_ONLY",
                        {"test_planter.py": "holds a marker in the shared dir"})
    work = tmp_path / "w2"
    work.mkdir()
    outcomes = _run_wave(root, wave, work)
    assert all(o.result.has_record for o in outcomes), [
        o.log for o in outcomes]
    assert _reds(outcomes) == 0, [o.log for o in outcomes]
    # EVERY FILE STILL RAN. Isolation must not be a quiet way to drop one.
    ran = {o.result.path for o in outcomes}
    assert ran == {f for _i, f in wave}, ran
    for outcome in outcomes:
        assert outcome.result.cases >= 1, (
            f"{outcome.result.path} produced no case — a file that stops "
            f"being measured is worse than a slow one")


@pytest.mark.timeout(300)
def test_the_isolated_file_still_carries_its_file_attribute(tmp_path,
                                                            monkeypatch):
    """The NORECORD machinery reads the `file` attribute; isolation keeps it."""
    root, wave = _race_corpus(tmp_path / "corpus")
    monkeypatch.setattr(policy, "SERIAL_ONLY",
                        {"test_planter.py": "holds a marker in the shared dir"})
    work = tmp_path / "w3"
    work.mkdir()
    outcomes = _run_wave(root, wave, work)
    merged = tmp_path / "merged.xml"
    driver.merge([o.result for o in outcomes], merged)
    files = {tc.get("file")
             for tc in ET.parse(merged).getroot().iter("testcase")}
    assert {"test_planter.py", "test_scanner_a.py", "test_scanner_b.py"} \
        <= files, files
