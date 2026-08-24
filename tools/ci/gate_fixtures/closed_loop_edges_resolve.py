"""`closed-loop edges resolve` — an edge pointing at a step that is not declared.

THE GATE'S OWN CLAIM is that a declared `closed_loop` must be "an edge something
can actually take, or the declaration is decoration". It checks four conditions
per edge: the target resolves to a declared step, the edge closes a loop, a
trigger states when it is taken, and the declaring step has a gate that can
produce the verdict the trigger reads.

THE MUTATION BREAKS EXACTLY ONE OF THE FOUR — the target — and leaves the other
three intact. `fallback_to: 99` names a step this flow does not declare, so the
edge resolves to nothing and `CL-FALLBACK-UNRESOLVED` is the finding. The other
three conditions still hold in the mutant, which is what makes the refusal
attributable: a subject that broke all four would refuse for a reason the
fixture cannot pin.

WHY NOT THE `CL-NO-TRIGGER` MUTATION HERE. Its sibling fixture
`closed_loop_executable_census` uses that one. The two gates read the same file
and share their edge-problem code, so giving them the SAME mutation would leave
one of the two pairs proving nothing the other did not already prove.

chip-AGNOSTIC / PDK-AGNOSTIC: the subject flow names no process, foundry,
vendor, tool or product; see `_flow_subject`.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _flow_subject as FS  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "closed-loop edges resolve"


def _tree(work: Path, name: str, **kw) -> Path:
    root = F.git_init(work / name)
    FS.write(root, **kw)
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """`2 -> 1`: declared, closes a loop, triggered, and step 2 is gated."""
    return _tree(work, "subject_pass")


def can_fail(work: Path):
    """`2 -> 99`: no step 99 is declared, so the edge resolves to nothing."""
    root = _tree(work, "subject_fail", fallback_to="99")
    return root, "CL-FALLBACK-UNRESOLVED"
