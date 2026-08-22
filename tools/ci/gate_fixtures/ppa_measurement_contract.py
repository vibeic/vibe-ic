"""`PPA measurement contract` — a contract that no longer hashes to itself.

THE DOCUMENT IS BUILT BY THE REPOSITORY'S OWN PRODUCER, `_ppa.contract.build`,
rather than assembled here. That is the whole design of this fixture: a
hand-written contract is a second, private statement of a schema that already
has one, and the head-to-head fixture beside this file went dark precisely by
drifting five generations behind its checker while looking fine. `build` is a
pure function of the declaration and the BYTES under the root, so the record
this produces is exactly what the real producer would produce for that tree,
and it cannot fall behind a schema change that the producer follows.

THE MUTATION IS PPA-C-001, the first clause: the stated `contract_digest` is
altered by ONE character and nothing else. The document still parses, still
validates against the schema, still declares five MEASURED identities and still
reads like a complete contract — and every identity in it now describes a
document that no longer exists. That is the direction worth guarding, because
it is the one an editor produces by accident and a reader cannot see.

The tree and the record are SYNTHETIC and say so. No PPA run stands behind
them; a fixture must never be mistaken for evidence of a measurement.

chip-AGNOSTIC / PDK-AGNOSTIC: the artefacts are three placeholder files and the
facts name no process, no foundry, no tool and no product.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
                       / "programs"))
from _ppa import contract as C  # noqa: E402

GATE = "PPA measurement contract"

#: The corpus directory THIS row's declaration names. The same checker is wired
#: three times over three corpora; the campaign variants are sibling modules
#: that reuse everything here and move only this string.
CORPUS = "benchmark-data"
_RECORD_REL = "records/synthetic_contract.json"

#: Three placeholder artefacts, one per identity kind that owns files. Their
#: CONTENT is irrelevant and their PRESENCE is not: `build` hashes the bytes
#: under the root, and an identity with no members at all derives NOT_MEASURED
#: (PPA-C-007) — which is CANNOT CHECK, and a can-pass fixture that reaches
#: CANNOT CHECK proves only that the gate noticed it could not look.
_FILES = {
    "spec/spec.json": '{"synthetic": true}\n',
    "impl/netlist.txt": "synthetic netlist, not a design\n",
    "reports/analysis.json": '{"synthetic": true}\n',
}

#: EVERY identity kind carries at least one member. `toolchain` and
#: `agent_execution` own no artefacts here, so they carry a declared fact —
#: measured while writing this: with an empty toolchain block the document was
#: otherwise perfect and still answered rc 2, `identity 'toolchain' is
#: NOT_MEASURED: no members were declared, so there is nothing to identify`.
_DECLARATION = {
    "root_label": "synthetic_fixture",
    "run_label": "synthetic_fixture",
    "policy": {
        "missing_power_basis": "REFUSE",
        "mutation_allow_list": ["pnr.*"],
        "mutation_forbidden": ["spec.*"],
    },
    "problem": {
        "artefacts": [{"role": "spec", "path": "spec/spec.json"}],
        "facts": [{"key": "problem.id", "value": "synthetic",
                   "source": "declared"}],
    },
    "implementation": {
        "artefacts": [{"role": "netlist", "path": "impl/netlist.txt"}],
        "facts": [],
    },
    "analysis": {
        "artefacts": [{"role": "analysis", "path": "reports/analysis.json"}],
        "facts": [],
    },
    "toolchain": {
        "artefacts": [],
        "facts": [{"key": "toolchain.declared",
                   "value": "synthetic_fixture_no_tools",
                   "source": "declared"}],
    },
    "agent_execution": {
        "artefacts": [],
        "facts": [{"key": "agent.role", "value": "synthetic gate fixture",
                   "source": "declared"}],
    },
    "candidate": {"mutations": []},
    "metrics": [],
}


def _record_path(root: Path, corpus: str) -> Path:
    return root / corpus / _RECORD_REL


def _tree(work: Path, corpus: str) -> Path:
    root = F.git_init(work / "subject")
    for rel, text in _FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    doc = C.build(_DECLARATION, root)
    out = _record_path(root, corpus)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    return root


def build_can_pass(work: Path, corpus: str) -> Path:
    """A contract this gate must ACCEPT, at the corpus the row names."""
    root = _tree(work, corpus)
    F.git_commit(root)
    return root


def build_can_fail(work: Path, corpus: str):
    """The same contract with its stated identity no longer its identity."""
    root = _tree(work, corpus)
    F.git_commit(root)
    p = _record_path(root, corpus)
    doc = json.loads(p.read_text(encoding="utf-8"))
    stated = str(doc["contract_digest"])
    # ONE character, chosen so the result is still a well-formed sha256 string:
    # the point is a digest that is VALID and WRONG, not one that is malformed.
    # A malformed digest would be refused for its shape and would never reach
    # the comparison this clause exists to make.
    doc["contract_digest"] = stated[:-1] + ("0" if stated[-1] != "0" else "1")
    p.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                 encoding="utf-8")
    F.git_commit(root, "mutate")
    # THE TOKEN MUST APPEAR IN THE REFUSAL, which is what proves the gate
    # refused for THIS mutation and not by coincidence. `contract_digest` is the
    # field moved but the clause never spells it: the message reads "the
    # contract does not hash to its own stated digest". The clause CODE is the
    # identifier the checker actually emits, and `_ppa.contract.FINDING_CODES`
    # is the registry it must be in, so it cannot quietly stop meaning this.
    return root, "PPA-C-001"


def can_pass(work: Path) -> Path:
    return build_can_pass(work, CORPUS)


def can_fail(work: Path):
    return build_can_fail(work, CORPUS)
