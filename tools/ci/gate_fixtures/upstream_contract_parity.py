"""`upstream contract parity` — an upstream name nobody classified.

THE PROPERTY, in the gate's own words: NO NAME INSIDE A REGISTERED ENTRY IS
UNACCOUNTED FOR. It is the property whose absence let one upstream variable go
unread, unmentioned and unrecorded for the whole life of a step, and surface
weeks later as an unrelated refusal about something else.

THE SUBJECT OF THIS GATE IS THE REGISTER, so that is what the fixture builds.
`our_module` is deliberately a REAL module of the shipped plugin: the gate
resolves that side against its own installation root and no fixture may move it,
which is exactly right — the register is the input under test and our source is
not. The names in both directions are synthetic and appear in no module, so they
are classified in the two classes that make no claim about our source
(`omitted_by_design`, which the gate checks for a REASON rather than for a
mention).

THE MUTATION ADDS ONE NAME TO THE UPSTREAM SNAPSHOT AND CLASSIFIES NOTHING —
the shape of a variable that appears upstream tomorrow and that nobody triages.
The register is otherwise byte-identical, so the entry, the module and the two
classified names are all still judged; what changes is that one name now falls
in no class. Emptying the register instead would reach rc 2 by this gate's own
rule ("an empty register passes every property it states"), which is the verdict
it exists never to return and proves nothing about the predicate.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "upstream contract parity"

_REGISTER_REL = "programs/upstream_contract_parity.json"

#: A module of the SHIPPED plugin. The gate reads our side from its own
#: installation, never from the subject tree, so this must name something real.
_OUR_MODULE = "programs/_pad_ring.py"

_CLASSIFIED = {
    "SYNTHETIC_FIXTURE_ALPHA":
        "a view list the upstream flow is HANDED and this step discovers for "
        "itself; the information is obtained by another route, not unread",
    "SYNTHETIC_FIXTURE_BETA":
        "a device-model list for stages that solve circuits; this step emits a "
        "placement and solves nothing",
}

#: The name the mutation adds to upstream and to no class.
_UNCLASSIFIED = "SYNTHETIC_FIXTURE_GAMMA"


def _register(names) -> dict:
    return {
        "_comment": [
            "A synthetic register built by tools/ci/gate_fixtures/ to drive "
            "one gate in both directions. It describes nothing real."],
        "entries": [
            {
                "id": "synthetic.fixture_contract",
                "kind": "contract",
                "our_module": _OUR_MODULE,
                "what_we_reimplement":
                    "a synthetic configuration contract, for the sole purpose "
                    "of exercising this gate's classification rule",
                "upstream": {
                    "distribution": "synthetic",
                    "file": "synthetic/config/flow.py",
                    "extract_regex": "Variable\\(\\s*\"(SYNTHETIC_[A-Z0-9_]+)\"",
                    "note": "no distribution is read on this run; the snapshot "
                            "below is the denominator",
                },
                "snapshot": {
                    "measured_on": "2026-08-22",
                    "measured_in": "the fixture that wrote this file",
                    "distribution_version": "0.0.0",
                    "names": list(names),
                },
                "classification": {
                    "implemented": [],
                    "declared_unperformed": [],
                    "omitted_by_design": dict(_CLASSIFIED),
                    "known_gap": {},
                },
            },
        ],
    }


def _tree(work: Path, names) -> Path:
    root = work / "subject"
    reg = root / _REGISTER_REL
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps(_register(names), indent=2) + "\n",
                   encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Every upstream name the snapshot carries is in exactly one class."""
    return _tree(work, sorted(_CLASSIFIED))


def can_fail(work: Path):
    """The same register, plus one upstream name in no class at all."""
    root = _tree(work, sorted(_CLASSIFIED) + [_UNCLASSIFIED])
    return root, "unaccounted name(s)"
