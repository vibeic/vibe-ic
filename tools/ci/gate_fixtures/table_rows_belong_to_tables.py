"""`table rows belong to tables` — a table fragment pasted into running prose.

The mutation is PLACEMENT, and only placement. Both trees state the SAME count
in the SAME words; the can-fail tree has merely lost the delimiter row that made
those two lines a table, so they land in the middle of a sentence and the clause
they replaced is gone. That is the defect this gate exists for, and it is the one
an agreement gate cannot see: the number is still correct, so a checker that
reads numbers finds nothing to say.

The mutation does NOT delete the document. Absence would drive the gate's
empty-corpus refusal (`_vacuous_exit`'s tier), which proves only that the gate
notices an empty corpus and says nothing about whether it can read placement.

No version-shaped string appears here on purpose: this tree is scanned by other
gates too, and a fixture should not hand any of them a claim to adjudicate.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "table rows belong to tables"

#: Header, DELIMITER, body — a table by the rule the gate states.
_GOOD = """# Fixture notes

The subject tree states one count, in a table, so a reader does not have to
count the entries by hand.

| Stage   | Entries |
| ------- | ------- |
| collect | 12      |

Every run advances the row above.
"""

#: The same two lines, mid-paragraph, with the dashes left behind by the paste.
_PASTED = """# Fixture notes

The subject tree states one count, in a table, so a reader does not have to
| Stage   | Entries |
| collect | 12      |
count the entries by hand.

Every run advances the row above.
"""


def _tree(work: Path) -> Path:
    root = F.git_init(work / "subject")
    (root / "NOTES.md").write_text(_GOOD)
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    return _tree(work)


def can_fail(work: Path):
    root = _tree(work)
    (root / "NOTES.md").write_text(_PASTED)
    F.git_commit(root, "mutate")
    return root, "[ORPHAN TABLE ROW]"
