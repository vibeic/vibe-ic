"""`ic-expert operating map kept` — the routing table edited out of the agent.

THE MUTATION IS THE GATE'S OWN DOCUMENTED DEFECT, in its second instance. The
IC-EXPERT OPERATING MAP is the phase -> program -> gate -> skill table the agent
routes from; it is prose-and-table, it is the first thing a re-organisation
retitles, and an agent whose map has been retitled routes from nothing while the
document still looks complete. So the mutation retitles the section and leaves
the table itself in place — the shape a real edit takes.

BOTH ARMS SHIP THE SAME ONE DOCUMENT at the same path with the same single
marker demanded of it: one file, one marker, both directions. The red arm is red
because that marker's answer moved, not because the gate was handed an empty
tree.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "ic-expert operating map kept"

#: The document the declaration points at, relative to the subject root.
_DOC = "agents/ic-expert-agent.md"

_KEPT = """# IC Expert Agent

The agent does not improvise a route. It reads one table and follows it.

## IC-EXPERT OPERATING MAP

| phase | program | gate | skill |
|-------|---------|------|-------|
| 1 | doc ingest | layer coverage | spec-review |
| 2 | rtl emit | lint + conformance | spec-to-rtl |
| 3 | backend | drc / lvs / sta | tapeout-checklist |
"""

#: The same document after the edit the gate exists to catch: the section is
#: RETITLED. The table survives; the phrase every reader and every check keys
#: on does not.
_DROPPED = """# IC Expert Agent

The agent does not improvise a route. It reads one table and follows it.

## Routing reference

| phase | program | gate | skill |
|-------|---------|------|-------|
| 1 | doc ingest | layer coverage | spec-review |
| 2 | rtl emit | lint + conformance | spec-to-rtl |
| 3 | backend | drc / lvs / sta | tapeout-checklist |
"""


def _tree(work: Path, body: str) -> Path:
    root = F.git_init(work / "subject")
    doc = root / _DOC
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(body, encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """The operating-map heading still present."""
    return _tree(work, _KEPT)


def can_fail(work: Path):
    """The same document with the operating-map heading retitled away."""
    return _tree(work, _DROPPED), "missing doctrine marker"
