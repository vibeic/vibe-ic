"""`every program is reachable` — a program no entry path reaches.

THE MUTATION IS THE DEFECT THE GATE EXISTS FOR, at its smallest. Both arms ship
the SAME three programs at the same paths: a runner, a checker it imports, and a
third that is reached by nothing. The only difference is one `import` line in
the runner.

  can_pass   runner_x imports BOTH widget_check and spare_check   -> 0 unreached
  can_fail   runner_x imports widget_check only                   -> 1 unreached

BOTH ARMS HAVE THE SAME DENOMINATOR — three programs, scanned in both. That
matters more here than usual: this gate's failure mode when handed a smaller
subject is a PASS, because a tree with no programs has nothing unreachable. Take
the corpus away instead of taking the EDGE away and the gate exits 0 over an
empty scan, which proves the vacuity path and nothing about the predicate. The
red arm is red because an edge moved, and the tier line reports the same
population on both sides so a reader can check that.

THE SUBJECT IS TINY ON PURPOSE. Against the real repo this audit reads 1291
programs and takes ~400 s. A fixture that copied the plugin would make the
mutation suite unaffordable and would couple this gate's arms to every future
wiring change in the tree. Three programs exercise the same code path: enumerate,
index, classify, verdict.

`runner_x` is the ENTRY POINT, and this audit has no notion of a root — it
reports every program nothing names, including the one at the top. So both arms
give it the venue a real runner has, an identical one-step flow yaml naming it
on a blocking clause. That yaml is the same on both sides; the mutation is
measured on `spare_check` alone, whose status is the only thing that differs.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "every program is reachable"

_RUNNER_BOTH = '''"""A runner that dispatches both checkers."""
import widget_check
import spare_check
'''

_RUNNER_ONE = '''"""A runner that dispatches one checker; the other is orphaned."""
import widget_check
'''

_WIDGET = '"""Reached by the runner\'s import."""\n'
_SPARE = '"""A capability program. Whether anything reaches it is the test."""\n'


def _tree(work: Path, runner_body: str) -> Path:
    root = F.git_init(work / "subject")
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    (progs / "runner_x.py").write_text(runner_body)
    (progs / "widget_check.py").write_text(_WIDGET)
    (progs / "spare_check.py").write_text(_SPARE)
    flow = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "flow"
    flow.mkdir(parents=True)
    # `runner_x` is the ENTRY POINT, and this audit has no notion of a root —
    # it reports every program nothing names, including the one at the top. So
    # the entry point is given the venue a real runner has: a flow clause. Both
    # arms carry the identical yaml, so it is not what the mutation moves.
    (flow / "phase1_phase2_phase3.yaml").write_text(
        "steps:\n"
        "  - id: 1\n"
        "    name: run\n"
        "    gate:\n"
        "      all_of:\n"
        '        - program_exit_zero: "runner_x ."\n')
    # NO COPY OF THE AUDITOR SHIPS WITH THE SUBJECT ANY MORE. It used to,
    # because the program derived its tree from `__file__` and the only way to
    # audit a subject was to run the subject's copy. That is the same coupling
    # that made the BASE arm of an A/B run the base tree's slow code and never
    # finish. With `--root` the gate runs the RUNTIME's program against this
    # tree, so the fixture supplies only the INPUT — which is what a fixture
    # subject is for.
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """Every program is reached: the runner imports both checkers."""
    return _tree(work, _RUNNER_BOTH)


def can_fail(work: Path):
    """`spare_check` loses its only edge; the same three programs are scanned."""
    return _tree(work, _RUNNER_ONE), "spare_check"
