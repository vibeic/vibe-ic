"""`gate proof vocabulary has a producer` — an axis whose whole proof
vocabulary is emitted by nobody, so no run of the flow can ever answer it.

THE MUTATION IS THE GATE'S OWN DOCUMENTED DEFECT, in its own words: "an axis
whose whole proof vocabulary is unproduced is not a strict gate; it is a gate
that cannot be answered, and the flow reports it as undetermined forever while
looking healthy". Both arms carry the SAME consumer declaring the SAME single
axis and the SAME single producer module writing the SAME single metric record.
What the mutation changes is the NAME inside that record — the answer, not the
corpus.

THE PRODUCER SITS OUTSIDE `programs/`, AND THAT IS THE POINT. Until 2026-08-25
this gate walked `<root>/vibe-ic-marketplace/plugins/vibe-ic/programs` only,
and concluded "on any design, forever" about a repository it had not read: the
two live `timing.drv.*` producers are in `ppa-crosslayer/tools` and
`ppa-e2e/tools`. A fixture whose producer lived inside `programs/` would pass
under the OLD population too and would certify nothing about the repair. This
one is admitted only by the widened walk AND by the emits-predicate — the
module never imports `_ppa`, exactly like `ppa-e2e/tools/signoff_records.py`,
which is the second half of the same defect.

THE DENOMINATORS THE GATE PRINTS ARE IDENTICAL IN BOTH DIRECTIONS. Measured:

    feasibility axes             1   ->   1
    emitting modules             1   ->   1
    names they declare           2   ->   2
    axes with no produced name   0   ->   1      <- the answer

Both arms declare the same TWO names (the record's schema id, which is
metric-shaped, and the one metric name), so the corpus size does not move with
the verdict. An empty subject makes the gate exit 2 with "an empty axis table
or an empty producer set", which is the vacuity path this fixture must not
take — and would be refused if it did.

THE CONSUMER IS PRESENT IN BOTH ARMS AND IS NEVER THE PRODUCER. It declares
`"metric"`-keyed evidence dicts and both status constants, exactly like the
real `_ppa/feasibility.py`, and writes nothing — so it satisfies two of the
three conjuncts and is excluded on the third. A fixture whose consumer also
wrote records would prove the gate green for the self-satisfying reason the
consumer exclusion exists to refuse.

chip-AGNOSTIC: no IC, vendor, SKU or process appears here.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402,F401 — the protocol's home

GATE = "gate proof vocabulary has a producer"

_PROGRAMS = ("vibe-ic-marketplace", "plugins", "vibe-ic", "programs")

#: The CONSUMER, in the shape the gate reads: `DEFAULT_AXES` of Axis(name,
#: groups) with Proof(metric). It also carries the two status constants and a
#: `"metric"`-keyed record so that the third conjunct — writing — is the only
#: thing separating it from a producer.
_FEASIBILITY = '''\
"""The axis table. Declares proof names; never emits one."""

STATUS = ("MEASURED", "NOT_MEASURED")


class Proof:
    def __init__(self, metric, kind=None):
        self.metric = metric
        self.kind = kind


class Axis:
    def __init__(self, name, groups):
        self.name = name
        self.groups = groups


DEFAULT_AXES = (Axis("alpha", ((Proof("timing.alpha.value"),),)),)


def evidence_for(proof, status):
    """Reads records and builds evidence. Writes nothing, ever."""
    return {"metric": proof.metric, "status": status}
'''

#: The PRODUCER. Outside `programs/`, never imports `_ppa`, and satisfies all
#: three conjuncts: constructs a `"metric"`-keyed record, gives it a MEASURED /
#: NOT_MEASURED status, and writes it.
_PRODUCER = '''\
"""A caller-side records bridge, outside the plugin tree."""
import json
from pathlib import Path


def records(value):
    return [{"schema": "vibeic.ppa.metric.v1", "metric": "%s",
             "status": "MEASURED" if value is not None else "NOT_MEASURED",
             "unit": "count", "value": value}]


def main(out, value):
    Path(out).write_text(json.dumps(records(value), indent=1) + "\\n")
    return 0
'''


def _tree(work: Path, metric: str) -> Path:
    root = work / "subject"
    (root / ".git").mkdir(parents=True)
    ppa = root.joinpath(*_PROGRAMS) / "_ppa"
    ppa.mkdir(parents=True)
    (ppa / "__init__.py").write_text("", encoding="utf-8")
    (ppa / "feasibility.py").write_text(_FEASIBILITY, encoding="utf-8")
    tools = root / "ppa-bridge" / "tools"
    tools.mkdir(parents=True)
    (tools / "records.py").write_text(_PRODUCER % metric, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The axis proves from `timing.alpha.value`, and the bridge emits it."""
    return _tree(work, "timing.alpha.value")


def can_fail(work: Path):
    """The same consumer, the same bridge, the same one record written — and
    the name inside it is no longer one the axis proves from, so `alpha` is
    unprovable on any run of this flow, forever."""
    return (_tree(work, "timing.beta.value"),
            "prove from names nobody produces")
