"""`prepared checkout states the revision it hol` — a checkout that selects a
revision and never looks at what it got.

THE MUTATION IS THE MEASURED DEFECT ITSELF. The gate's docstring records
automation that prepared a checkout, never confirmed the revision, and then
published a complete and entirely confident verdict about the wrong commit.
The source arm's whole demand is that a site selecting a revision INSPECT the
outcome — `check=True`, an explicit returncode test, or a following
`rev-parse HEAD`. So the mutation is one site losing its inspection while
staying, byte for byte, the same checkout.

THE DENOMINATOR IS THE SAME IN BOTH ARMS
========================================
The gate prints the population it judged, and it does not move:

    examined 2 revision-selecting checkout site(s)      (both arms)

Both subjects hold the same two files and the same three `git checkout`
calls. The first site inspects in both arms. The second is the mutation: it
keeps its argv and drops `check=True`. Nothing is added and nothing is
removed, so `sites == 0` — the gate's rc 2 vacuity path, "no
revision-selecting checkout site was found, so nothing was judged" — is never
reached by either direction.

THE THIRD CALL IS THE DENOMINATOR'S OWN HONESTY, EXERCISED
==========================================================
`git checkout -- <path>` restores a file; it selects no revision, and the gate
excludes it on purpose so the rule's denominator is not inflated in the
flattering direction. The subject carries one such call, uninspected, in BOTH
arms. It is never counted and never reported — which is what keeps `examined
2` true with three checkout calls present, and would break this fixture's
can-pass arm loudly if that exclusion ever regressed.

WHY THE DECLARATION PASSES THE SUBJECT POSITIONALLY
===================================================
This program has two arms. `--root` selects the RUNTIME arm, which also
requires `--expect` — a revision name that no subject substitution can supply,
and rc 3 BAD INVOCATION without it. The landing gate is therefore the SOURCE
arm, whose subject is the positional `tree` argument, and that is the single
token the engine redirects.

chip-AGNOSTIC: no IC, vendor, SKU or process appears here.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "prepared checkout states the revision it hol"

#: Site 1 — inspected in both arms, so the corpus is never empty.
_PREPARE = '''\
"""Automation that prepares a checkout of a named revision."""
import subprocess


def prepare_primary(root, rev):
    subprocess.run(["git", "-C", str(root), "checkout", rev], check=True)


def restore_one_file(root, path):
    # `git checkout -- <path>` selects no revision: outside the population.
    subprocess.run(["git", "-C", str(root), "checkout", "--", path])
'''

#: Site 2 — the moving part. Same argv either way.
_INSPECTED = '''\
import subprocess


def prepare_secondary(root, rev):
    subprocess.run(["git", "-C", str(root), "checkout", rev], check=True)
'''

_UNINSPECTED = '''\
import subprocess


def prepare_secondary(root, rev):
    subprocess.run(["git", "-C", str(root), "checkout", rev])
'''


def _tree(work: Path, inspected: bool) -> Path:
    root = work / "subject"
    tools = root / "tools"
    tools.mkdir(parents=True)
    (tools / "prepare_checkout.py").write_text(_PREPARE, encoding="utf-8")
    (tools / "prepare_secondary.py").write_text(
        _INSPECTED if inspected else _UNINSPECTED, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Two revision-selecting sites, both inspecting what they got."""
    return _tree(work, inspected=True)


def can_fail(work: Path):
    """The same two sites; the second checks out a revision and walks on."""
    return _tree(work, inspected=False), "the outcome is never inspected"
