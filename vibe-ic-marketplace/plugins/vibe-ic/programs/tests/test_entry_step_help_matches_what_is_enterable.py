"""`--entry-step`'s help must describe the entries the guard actually accepts.

MEASURED (plugin 1.12.58, vibe_ic_one_shot_runner on a real project): the help
advertised "D1 is Phase 1, 2/4/1/9/11 are Phase 2, 15/31/37 Phase 3, A1..A9
analog — so the orchestrator routes to that runner and skips the phases before
it", and the guard then refused EVERY Phase-3 and analog step:

    D1 -> accepted   2 -> accepted   4 -> accepted   9 -> accepted  11 -> accepted
    15 -> REFUSED   31 -> REFUSED   37 -> REFUSED    A1 -> REFUSED   A5 -> REFUSED

Five of the ten advertised entry classes did not exist. The refusal itself was
honest and actionable ("Run that runner directly"); only the help was wrong, and
a reader had no way to tell which half was lying.

The fix is not a reworded string: the accepted set is now ONE named constant
that the guard branches on, and these tests hold the help to it.
"""
import re
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
RUNNER = PROGRAMS / 'vibe_ic_one_shot_runner.py'
assert RUNNER.exists()

sys.path.insert(0, str(PROGRAMS))

PHASE12_STEPS = ['D1', '2', '4', '9', '11']
PHASE3_STEPS = [str(sid) for sid in range(15, 23)] + ['31', '37']
ELSEWHERE_STEPS = ['A1']


def help_text():
    out = subprocess.run([sys.executable, str(RUNNER), '--help'],
                         capture_output=True, text=True).stdout
    m = re.search(r'--entry-step ENTRY_STEP\n(.*?)(?=\n  --\w)', out, re.S)
    assert m, out
    return ' '.join(m.group(1).split())




def _observe(tmp_path, step):
    """Ask the CLI itself whether this step can be entered here."""
    (tmp_path / 'input').mkdir(exist_ok=True)
    # owner route rule 2026-09-28 (ICROUTE)
    from _route_fixture import stage_owner_route
    stage_owner_route(tmp_path, "ic")
    res = subprocess.run(
        [sys.executable, str(RUNNER), str(tmp_path), '--entry-step', step,
         '--route', 'ic', '--no-dashboard', '--skip-hardware'],
        capture_output=True, text=True)
    return 'cannot yet be entered at' not in res.stderr


def test_the_help_describes_the_entries_the_CLI_actually_accepts(tmp_path):
    """The load-bearing test, and it depends on NOTHING this fix introduced: it
    compares the shipped help text against the CLI's OBSERVED accept/refuse
    behaviour for each runner class."""
    txt = help_text()
    refused = [s for s in ELSEWHERE_STEPS if not _observe(tmp_path, s)]
    accepted = [s for s in PHASE12_STEPS if _observe(tmp_path, s)]
    assert refused, 'expected analog steps to be refused here'
    assert accepted, 'expected the Phase-1/2 steps to be accepted here'
    assert re.search(r'Analog \(A1\.\.A9\).*?REFUSED', txt), txt
    for step in PHASE3_STEPS:
        assert _observe(tmp_path, step), f'Phase-3 step {step} was refused'
    assert re.search(r'Phase-3 \(15\.\.22/31/37\).*?--exit-step', txt), txt








def test_BEHAVIOUR_a_phase3_entry_requires_a_bounded_exit(tmp_path):
    (tmp_path / 'input').mkdir()
    # owner route rule 2026-09-28 (ICROUTE)
    from _route_fixture import stage_owner_route
    stage_owner_route(tmp_path, "ic")
    res = subprocess.run(
        [sys.executable, str(RUNNER), str(tmp_path), '--entry-step', '15',
         '--route', 'ic', '--no-dashboard', '--skip-hardware'],
        capture_output=True, text=True)
    assert res.returncode == 2, (res.stdout, res.stderr)
    assert 'needs --exit-step' in res.stderr


def test_CONTROL_a_phase1_entry_is_not_refused_by_this_guard(tmp_path):
    """The guard must reject the right thing and only the right thing: a Phase-1
    entry may fail later for its own reasons, but never with THIS refusal."""
    (tmp_path / 'input').mkdir()
    res = subprocess.run(
        [sys.executable, str(RUNNER), str(tmp_path), '--entry-step', 'D1',
         '--route', 'ic', '--no-dashboard', '--skip-hardware'],
        capture_output=True, text=True)
    assert 'cannot yet be entered at' not in res.stderr, res.stderr
