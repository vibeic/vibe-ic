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
import step_preflight as spf              # noqa: E402
import vibe_ic_one_shot_runner as runner  # noqa: E402

PHASE12_STEPS = ['D1', '2', '4', '9', '11']
ELSEWHERE_STEPS = ['15', '31', '37', 'A1']


def help_text():
    out = subprocess.run([sys.executable, str(RUNNER), '--help'],
                         capture_output=True, text=True).stdout
    m = re.search(r'--entry-step ENTRY_STEP\n(.*?)(?=\n  --\w)', out, re.S)
    assert m, out
    return ' '.join(m.group(1).split())


def test_the_guard_and_the_help_read_the_same_named_constant():
    """The drift this file exists to prevent is only impossible while there is
    exactly one source of truth."""
    assert isinstance(runner.ENTRY_STEP_ENTERABLE_RUNNERS, tuple)
    src = RUNNER.read_text()
    assert '_entry_runner not in ENTRY_STEP_ENTERABLE_RUNNERS' in src, (
        'the guard must branch on the constant, not on its own literal copy')


def _observe(tmp_path, step):
    """Ask the CLI itself whether this step can be entered here."""
    (tmp_path / 'input').mkdir(exist_ok=True)
    res = subprocess.run(
        [sys.executable, str(RUNNER), str(tmp_path), '--entry-step', step,
         '--no-dashboard', '--skip-hardware'],
        capture_output=True, text=True)
    return 'cannot yet be entered at' not in res.stderr


def test_the_help_describes_the_entries_the_CLI_actually_accepts(tmp_path):
    """The load-bearing test, and it depends on NOTHING this fix introduced: it
    compares the shipped help text against the CLI's OBSERVED accept/refuse
    behaviour. On the pre-fix code the help says Phase-3 steps route here and
    the CLI refuses them, so this fails for exactly the reason the defect is a
    defect."""
    txt = help_text()
    refused = [s for s in ELSEWHERE_STEPS if not _observe(tmp_path, s)]
    accepted = [s for s in PHASE12_STEPS if _observe(tmp_path, s)]
    assert refused, 'expected the Phase-3/analog steps to be refused here'
    assert accepted, 'expected the Phase-1/2 steps to be accepted here'
    # Whatever the help says, it must not present a REFUSED step as one this
    # orchestrator routes.
    routes_claim = re.search(r'routes to that runner', txt)
    assert routes_claim is None or 'REFUSED' in txt, (
        f'help claims it routes to the owning runner but {refused} are refused '
        f'and no refusal is disclosed: {txt}')
    for step in refused:
        seg = re.search(r'(Phase-3[^.]*\.|analog[^.]*\.)', txt)
        assert 'REFUSED' in txt, (
            f'step {step} is refused by the CLI but the help does not say so: '
            f'{txt}')


def test_every_step_the_help_calls_enterable_really_is():
    for step in PHASE12_STEPS:
        owner = spf.runner_for_step(step)
        assert owner in runner.ENTRY_STEP_ENTERABLE_RUNNERS, (
            f'help presents step {step} as enterable here, but it is owned by '
            f'{owner}, which the guard refuses')


def test_a_step_this_orchestrator_refuses_is_disclosed_as_refused_in_the_help():
    unroutable = [s for s in ELSEWHERE_STEPS
                  if spf.runner_for_step(s) not in
                  runner.ENTRY_STEP_ENTERABLE_RUNNERS]
    assert unroutable, (
        'CONTROL for this test: if every step became enterable, the help would '
        'no longer need a refusal clause and this assertion should be revisited')
    assert 'REFUSED' in help_text(), (
        f'steps {unroutable} are refused by the guard, so the help must say so')


def test_the_help_does_not_promise_that_a_refused_step_routes():
    """The exact defect: the old help said the orchestrator 'routes to that
    runner' for 15/31/37 and A1..A9. It must not claim that for a step the
    guard rejects."""
    txt = help_text()
    m = re.search(r'Phase-3 \(([^)]*)\)', txt)
    assert m, f'the help must name the Phase-3 steps it refuses: {txt}'
    for step in re.findall(r'\d+', m.group(1)):
        assert spf.runner_for_step(step) not in \
            runner.ENTRY_STEP_ENTERABLE_RUNNERS, (
            f'step {step} is listed as refused but the guard accepts it')


def test_BEHAVIOUR_a_phase3_entry_is_refused_with_the_exact_code(tmp_path):
    (tmp_path / 'input').mkdir()
    res = subprocess.run(
        [sys.executable, str(RUNNER), str(tmp_path), '--entry-step', '15',
         '--no-dashboard', '--skip-hardware'],
        capture_output=True, text=True)
    assert res.returncode == 2, (res.stdout, res.stderr)
    assert 'REFUSED' in res.stderr


def test_CONTROL_a_phase1_entry_is_not_refused_by_this_guard(tmp_path):
    """The guard must reject the right thing and only the right thing: a Phase-1
    entry may fail later for its own reasons, but never with THIS refusal."""
    (tmp_path / 'input').mkdir()
    res = subprocess.run(
        [sys.executable, str(RUNNER), str(tmp_path), '--entry-step', 'D1',
         '--no-dashboard', '--skip-hardware'],
        capture_output=True, text=True)
    assert 'cannot yet be entered at' not in res.stderr, res.stderr
