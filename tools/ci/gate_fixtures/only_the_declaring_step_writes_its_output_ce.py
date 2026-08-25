"""`only the declaring step writes its output ce` — the census, and its control.

WHAT THIS PROGRAM WILL AND WILL NOT REFUSE, MEASURED BEFORE ANY FIXTURE WAS
WRITTEN. It is a CENSUS by ruling, and it says so in its own first paragraph:
"exit status here is INFORMATIONAL. The default is 0 whatever is found, because
a census that exits non-zero gets wired as a gate by the next person who reads
the exit code." So the two-writers finding — the defect in its title — is
reported at rc 0 and CANNOT be the mutation under any declaration this
repository is allowed to write. Measured on the shipped tree: 122 declared
paths, one with two writers, one stale inventory row, `rc=0`.

`--strict` would restore a refusing exit, and the program forbids it in the
same breath: "nothing in the flow should pass it". A fixture that got its red
from `--strict` would have proved a discrimination the landing gate does not
have — the `container exec deadlines` mistake `gate_mutation_fixtures` records,
one level up.

THE MUTATION IS THEREFORE THE NEGATIVE CONTROL, WHICH IS PART OF THE GATE AND
SAYS SO. From the program's header: "THE NEGATIVE CONTROL IS PART OF THE GATE,
and the record demanded it: a check whose declared-path set came back empty
would pass over nothing and read exactly like a clean tree. `--self-test`
asserts that known flow-owned paths are still recognised as declared." That is
the one question this program answers with a refusal, and it is the question
worth blocking a landing on: a flow document reshaped so the census's control
paths stop resolving leaves the census measuring something other than what it
claims, while still printing a green.

BOTH ARMS CARRY THE SAME POPULATION, and that is the point of building the
can-fail subject out of the can-pass one rather than out of less:

    declared concrete output paths      3   3     unchanged
    paths with a resolvable write       1   1     unchanged
    paths with more than one writer     1   1     unchanged
    control paths still flow-owned      2   0     <- the only thing that moves

Both flows declare THREE concrete paths and the same glob and ` OR `
alternation (which the program excludes, because "a set cannot have one
owner"); both program trees hold the same two modules writing the same declared
path, so the census's own finding is identical in both. What changes is the
SPELLING of the two control paths: the can-fail flow declares two other
concrete paths in their place, so the set the scan can see is no longer the set
it believes it is measuring, and `--self-test` refuses rather than passing.

An empty subject would also refuse — `no flow document`, or `the flow declares
no concrete required output` — and that is the vacuity path, not a check. It is
not used here.

THE CONTROL PATHS ARE READ OUT OF THE PROGRAM'S OWN SOURCE, never copied. They
are `_CONTROL_PATHS` in the module under test. Copying them would let the
fixture and the program drift apart, and the arm that then went green would be
the one nobody checked.

chip-AGNOSTIC / PDK-AGNOSTIC: no IC, vendor, foundry, process or product is
named here. The step ids and the third path describe the SHAPE of a
declaration, not any flow stage.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "only the declaring step writes its output ce"

_PROGRAM = F.PROGRAMS / "only_the_declaring_step_writes_its_output_census.py"
_PLUGIN_REL = Path("vibe-ic-marketplace/plugins/vibe-ic")
_FLOW_REL = _PLUGIN_REL / "flow" / "phase1_phase2_phase3.yaml"

#: One concrete path that is NOT a control path, declared identically by both
#: arms. It carries the census's own finding, so the finding count does not
#: move when the control paths do.
_SHARED = "reports/fixture_subject.json"

#: Two modules writing `_SHARED`. The program reads writes from the syntax
#: tree, not from the text — "NAMING IS NOT WRITING, and the difference is 88
#: versus 2" — so these have to be real `.write_text` calls on a `/`-join.
_WRITER_A = '''\
from pathlib import Path


def emit(project):
    (project / "reports" / "fixture_subject.json").write_text("{}")
'''

_WRITER_B = '''\
from pathlib import Path


def precheck(project):
    (project / "reports" / "fixture_subject.json").write_text("{}")
'''


def _control_paths():
    """`_CONTROL_PATHS` as the program under test declares it, read by parse.

    Read rather than imported: importing the program would execute its
    `sys.path` surgery and its `_atomic_artefact` import for no benefit, and
    read rather than copied so the fixture cannot drift from the program.
    """
    tree = ast.parse(_PROGRAM.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name) \
                and n.targets[0].id == "_CONTROL_PATHS":
            vals = [e.value for e in n.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if vals:
                return vals
    raise RuntimeError(
        "%s no longer declares _CONTROL_PATHS as a literal of strings; this "
        "fixture cannot know which paths the negative control asserts"
        % _PROGRAM.name)


def _flow_yaml(owned) -> str:
    """A flow declaring `owned` plus `_SHARED`, one glob and one alternation.

    The glob and the ` OR ` are in BOTH arms on purpose: they name a SET, the
    program excludes them, and keeping them identical means the concrete-path
    denominator is the same number on both sides for a reason a reader can
    check rather than take on trust.
    """
    steps = []
    for i, p in enumerate(owned):
        steps.append("  - id: \"%d\"\n    required_outputs:\n      - %s\n"
                     % (i + 1, p))
    steps.append(
        "  - id: \"%d\"\n    required_outputs:\n      - %s\n"
        "      - reports/*.log\n"
        "      - reports/a.json OR reports/b.json\n"
        % (len(owned) + 1, _SHARED))
    return "version: 2\nflow_name: fixture\nsteps:\n" + "".join(steps)


def _subject(work: Path, name: str, owned) -> Path:
    root = work / name
    (root / _FLOW_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / _FLOW_REL).write_text(_flow_yaml(owned), encoding="utf-8")
    programs = root / _PLUGIN_REL / "programs"
    programs.mkdir(parents=True, exist_ok=True)
    (programs / "emit_fixture_subject.py").write_text(_WRITER_A,
                                                      encoding="utf-8")
    (programs / "precheck_fixture_subject.py").write_text(_WRITER_B,
                                                          encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The flow still declares the control paths; the census reports and exits 0.

    It reports a real finding while doing so — two modules writing `_SHARED` —
    which is what a census does. rc 0 here is the ruling, not an absence.
    """
    return _subject(work, "subject_pass", _control_paths())


def can_fail(work: Path):
    """Same population, control paths spelled otherwise: the control fires.

    Each control path is replaced by a DIFFERENT concrete path, so the flow
    still declares exactly as many owned paths as the can-pass arm and the scan
    still has the same corpus to walk. What it no longer has is the set it
    asserts it is measuring.
    """
    renamed = [str(Path(p).with_name("not_" + Path(p).name))
               for p in _control_paths()]
    return _subject(work, "subject_fail", renamed), "no longer flow-owned"
