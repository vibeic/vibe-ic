"""`attestation preflight` — a checkout that would make the attestation measure
itself.

THE DEFECT THE GATE EXISTS FOR, in its own measurement: three gates that
snapshot a tree, re-derive it from HEAD and compare the two were all defeated on
one day by something present in the CHECKOUT and absent from the COMMIT — one
returned UNDETERMINED on uncommitted tracked edits, one flipped red/green run to
run, one failed 13 of 39 naming a single stray bytecode artefact. Every refusal
was correct; the cost was that each was paid at the END of an hour-long run.

THE MUTATION IS TRACKED DRIFT, and it is chosen over the residue arm on purpose.
Both arms ship the same committed subject; the can-fail arm then edits a file
that is ALREADY TRACKED and leaves the edit uncommitted. That is the first of
the three measured shapes, it needs no ignored-file machinery to set up, and it
is deterministic — `git status --porcelain` answers the same way on every host,
whereas a `__pycache__` arm would depend on whether some earlier step in the
same process had already written one.

WHY THE MUTATION IS NOT A DELETION. Removing the subject would reach a refusal
through the roots-hold-no-file path, which this gate routes to VACUOUS (a rc of
its own) and not to FAIL. The fixture protocol forbids that shape, and here it
would also prove the wrong branch: the expected fragment below is the FAIL text,
so a vacuous refusal fails this fixture rather than satisfying it.

THE ENVIRONMENT IS PART OF THE DECLARATION, NOT PART OF THE INPUT.
`repo_hygiene_gates.sh:52` exports `PYTHONDONTWRITEBYTECODE=1` for every gate it
declares, and this gate READS that variable: unset, it reports a problem about
the children the attestation would spawn, and BOTH arms would then refuse for a
reason that has nothing to do with the subject. Reproducing the dispatcher's
export is therefore what makes the arms differ only in the tree — it is not the
fixture choosing the argv, which stays exactly as declared. It is asserted below
rather than assumed, so if the dispatcher ever stops exporting it this fixture
says so instead of quietly testing something else.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "attestation preflight"

_ENV_FLAG = "PYTHONDONTWRITEBYTECODE"
_TRACKED = "programs/attestable.py"
_COMMITTED = '#!/usr/bin/env python3\n"""Fixture-only. Describes nothing real."""\nVALUE = 1\n'
_EDITED = '#!/usr/bin/env python3\n"""Fixture-only. Describes nothing real."""\nVALUE = 2\n'


def _dispatcher_environment() -> None:
    """Reproduce `repo_hygiene_gates.sh:52` — see the module docstring."""
    script = (Path(__file__).resolve().parents[1] / "repo_hygiene_gates.sh")
    assert f"export {_ENV_FLAG}=1" in script.read_text(encoding="utf-8"), (
        f"{script.name} no longer exports {_ENV_FLAG}, so this gate's declared "
        f"environment has changed and this fixture is reproducing a dispatcher "
        f"that no longer exists")
    os.environ[_ENV_FLAG] = "1"


def _tree(work: Path) -> Path:
    _dispatcher_environment()
    root = F.git_init(work / "subject")
    (root / "programs").mkdir(parents=True, exist_ok=True)
    (root / _TRACKED).write_text(_COMMITTED, encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """A committed subject with no residue and no drift: attestable."""
    return _tree(work)


def can_fail(work: Path):
    """The same subject, with one TRACKED file edited and left uncommitted."""
    root = _tree(work)
    (root / _TRACKED).write_text(_EDITED, encoding="utf-8")
    return root, "TRACKED path(s) under the declared roots differ from HEAD"
