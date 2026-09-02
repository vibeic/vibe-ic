"""`gate fixtures discriminate` — a fixture pair whose can_fail subject its own
gate ACCEPTS.

THE MUTATION IS THE DEFECT THIS ROW WAS ADDED FOR, in miniature. v1.15.79 moved
the PPA campaign trees and eleven fixtures went on planting at the old path, so
can_pass and can_fail landed on the same empty corpus and the gate answered the
same thing to both. That is not "a fixture that is a bit weak" — it is a pair
that has stopped being evidence, while every file it is made of is still
present and the existence census still says so.

THE SUBJECT IS A MINIATURE REPOSITORY, and it has to be, because this gate's
input IS a set of declarations and a set of fixtures. Both arms carry the SAME
three things — a `repo_hygiene_gates.sh` declaring one toy gate, that toy gate's
program, and one fixture module for it — and both arms' pairs BUILD and RUN.
What differs is one line inside the toy fixture's `can_fail`: in `can_pass` it
plants the sentinel the toy gate refuses on, in `can_fail` it does not. So the
mutated arm is a pair that executes cleanly and discriminates nothing, which is
the state under test and not a broken file.

WHAT IS DELIBERATELY THE SAME IN BOTH ARMS. The denominator: one declared gate,
one fixture module, `can_pass` and `can_fail` both defined and both callable.
The cheap ways to redden this row — delete the fixture, name an undeclared gate,
hand it an empty `gate_fixtures/` — are all reachable and none of them is this
question: the first two are `gate_mutation_fixture_check`'s verdict, and the
third is rc 2 NOT CHECKED, which this program refuses to print as a pass.

THE ENGINE IS NOT COPIED IN. The declaration spells the program
`$RUNTIME_ROOT/tools/ci/gate_fixture_discrimination_check.py` and the subject
`--root "$ROOT"`, so `gate_mutation_fixtures.run_pair`, the declaration parser
and their import closure are the REAL ones and only the judged tree is
synthetic. A `$ROOT`-anchored program would need that closure vendored here —
measured while trying it: 208 modules, and still failing on two suite
self-tests pinned by name to a real fixture. The subject therefore carries no
copy of anything that could drift.

chip-AGNOSTIC: one invented gate name and a sentinel file. No IC, vendor, PDK
or process.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "gate fixtures discriminate"

#: The toy gate: refuses exactly when the subject carries this file. Small on
#: purpose — what is under test is the PAIR, not the gate, and a toy gate with
#: a rich predicate would let an arm fail for a reason nobody chose.
_SENTINEL = "REFUSE_ME"

_TOY_GATE = '''#!/usr/bin/env python3
"""toy_probe_check — synthetic gate, reachable only from a fixture subject."""
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
if (root / "{sentinel}").is_file():
    print("toy_probe_check: REFUSED — the subject carries {sentinel}")
    sys.exit(1)
print("toy_probe_check: clean — no {sentinel} under", root)
sys.exit(0)
'''.format(sentinel=_SENTINEL)

#: A `repo_hygiene_gates.sh` that DECLARES one gate. It is parsed, never
#: executed, so it needs the declaration line and nothing else — but it is
#: written in the real dispatcher's shape so the parser sees what it sees in
#: production.
_TOY_SCRIPT = '''#!/usr/bin/env bash
# Synthetic declaration script — a fixture subject, not a runnable sweep.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_ROOT="$(cd "$HERE/../.." && pwd)"
ROOT="${VIBEIC_SUBJECT_ROOT:-$RUNTIME_ROOT}"
. "$HERE/_gate_dispatch.sh"
gate_dispatch_init "$@"
run "toy probe" "$ROOT" python3 "$ROOT/toy_probe_check.py" "$ROOT"
'''

#: The toy FIXTURE. `plants` decides whether its can_fail subject carries the
#: sentinel — i.e. whether the pair discriminates. Stdlib only: this module is
#: imported by `load_fixtures` out of the SUBJECT, where nothing else exists.
_TOY_FIXTURE = '''"""Synthetic fixture for the toy gate."""
from pathlib import Path

GATE = "toy probe"

_PROGRAM = {program!r}


def _tree(work: Path, leaf: str, sentinel: bool) -> Path:
    root = work / leaf
    root.mkdir(parents=True, exist_ok=True)
    (root / "toy_probe_check.py").write_text(_PROGRAM, encoding="utf-8")
    if sentinel:
        (root / "{sentinel}").write_text("x", encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """No sentinel: the toy gate accepts. rc 0 in both arms of this module."""
    return _tree(work, "accepted", sentinel=False)


def can_fail(work: Path):
    """The mutated subject. `plants` is what this fixture is varied by."""
    return _tree(work, "refused", sentinel={plants}), "REFUSED"
'''


def _tree(work: Path, leaf: str, plants: bool) -> Path:
    root = work / leaf
    ci = root / "tools" / "ci"
    (ci / "gate_fixtures").mkdir(parents=True)
    (ci / "repo_hygiene_gates.sh").write_text(_TOY_SCRIPT, encoding="utf-8")
    (ci / "gate_fixtures" / "toy_probe.py").write_text(
        _TOY_FIXTURE.format(program=_TOY_GATE, sentinel=_SENTINEL,
                            plants=plants),
        encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The toy pair DISCRIMINATES: its can_fail subject carries the sentinel,
    the toy gate refuses it, and the row reports 1 of 1 executed, 0 bad."""
    return _tree(work, "accepted", plants=True)


def can_fail(work: Path):
    """The toy pair does NOT discriminate: its can_fail subject omits the
    sentinel, so the toy gate ACCEPTS the input the fixture calls bad. Both
    arms build, both run, both return rc 0 — and this row must refuse."""
    return _tree(work, "refused", plants=False), "do not discriminate"
