"""`closed-loop executable census` — a flow with nothing to count.

WHAT THIS GATE REFUSES, MEASURED RATHER THAN ASSUMED. The census sorts every
declared `closed_loop` into the four nested tiers
`DECLARED_ONLY < EXECUTABLE < REMEASURED < ROLLBACK_PROVEN`, and a census on its
own never refuses: the live flow reports `DECLARED_ONLY=18, EXECUTABLE=0` and
returns 0, honestly. So most mutations of an edge do not move its verdict.

TWO THAT DO NOT, AND THEY WERE TRIED FIRST — recorded because "a mutation that
looks like it should work" is exactly how a fixture ends up proving nothing:

  * REMOVING THE TRIGGER. Measured: rc 0, `DECLARED_ONLY=1`. The edge is still
    classifiable, so it is classified. `gate_fixture_runner` caught this as
    `CAN-FAIL fixture was ACCEPTED`. Its sibling gate `closed-loop edges
    resolve` DOES refuse that input, which is why that mutation lives there.
  * AN UNKNOWN DECLARED CLASS (`CLC-BAD-REGISTRY`). Unreachable from a subject
    tree at all: the registry is a dict in the program's own source, not a
    sidecar a fixture could write, and the program says so in its own header
    ("WHY THE REGISTRY IS CODE AND NOT A JSON SIDECAR").

THE MUTATION THAT DOES: a flow with steps and ZERO `closed_loop` blocks. The
gate returns `NOT_MEASURED` (rc 2) rather than a green, saying the census has an
"empty denominator" and that "a green over nothing is not a measurement".

THAT IS THE PROPERTY WORTH PINNING HERE, not a consolation prize for the two
above. A census whose population is empty is the exact shape this repository
keeps finding: a gate that reports success over zero items is indistinguishable
from one that works, and is worse, because it is believed. The CAN-PASS arm
carries one declared edge, so the pair separates "there was nothing to count"
from "I counted, and it was fine".

NOT THE CLAIM AUDIT, deliberately. The dispatcher passes neither `--claims` nor
a project, so the claim audit reports `NOT_CHECKED` on both arms and a fixture
aimed at it would mutate a path this declaration never enters.

chip-AGNOSTIC / PDK-AGNOSTIC: see `_flow_subject`.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _flow_subject as FS  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "closed-loop executable census"


def _tree(work: Path, name: str, **kw) -> Path:
    root = F.git_init(work / name)
    FS.write(root, **kw)
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """One declared edge: the census has a population and reports it."""
    return _tree(work, "subject_pass")


def can_fail(work: Path):
    """Three steps, no `closed_loop` anywhere — a green here would be over nothing."""
    root = _tree(work, "subject_fail", declare_closed_loop=False)
    return root, "empty denominator"
