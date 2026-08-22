"""`table rows belong to tables` — a table-shaped line with no table.

WHY THIS ONE MATTERS MORE THAN IT LOOKS, in the checker's own words: a version
or population claim placed in an orphan row still AGREES with the shipped value,
so no agreement gate can see it — and the sentence it replaced is gone. A stray
`| x | y |` renders as literal text, so the fact it carries is published as
prose while being maintained as if it were a table.

THE CAN-PASS CARRIES A REAL TABLE, not merely an absence of one. A document with
no table-shaped lines at all would pass this gate without ever exercising it —
the checker's own summary counts `table-shaped line(s) examined`, and a fixture
that drives that count to zero is the empty-corpus pass this family refuses
everywhere else. The CAN-PASS examines three such lines and accepts them.

THE MUTATION ADDS ONE LINE AND CHANGES NOTHING ELSE. The good table stays intact
and keeps passing; the appended row has no delimiter beneath it, so it is a
fragment sitting outside any table. That is the difference between a document
that has no tables and one whose table broke.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "table rows belong to tables"

_DOC_REL = "docs/synthetic_table.md"

#: A well-formed table: header, delimiter, one body row. Three table-shaped
#: lines, all of which belong to a table.
_GOOD = (
    "# Synthetic fixture document\n"
    "\n"
    "This file exists to drive one gate and describes nothing real.\n"
    "\n"
    "| column a | column b |\n"
    "| --- | --- |\n"
    "| value | value |\n"
    "\n"
    "Ordinary prose after the table.\n"
)

#: The fragment. Table-shaped, and no delimiter row anywhere beneath it, so it
#: renders as literal text rather than as a table.
_ORPHAN = (
    "\n"
    "A row with no table under it follows:\n"
    "\n"
    "| orphan a | orphan b |\n"
)


def _tree(work: Path, with_orphan: bool) -> Path:
    root = F.git_init(work / "subject")
    p = root / _DOC_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_GOOD + (_ORPHAN if with_orphan else ""), encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """A real table the gate must accept — three table-shaped lines examined."""
    root = _tree(work, with_orphan=False)
    F.git_commit(root)
    return root


def can_fail(work: Path):
    """The same document with one table-shaped line outside any table."""
    root = _tree(work, with_orphan=False)
    F.git_commit(root)
    (root / _DOC_REL).write_text(_GOOD + _ORPHAN, encoding="utf-8")
    F.git_commit(root, "mutate")
    # The token has to appear in the refusal, which is how the pair test knows
    # the gate refused for THIS mutation rather than by coincidence.
    return root, "ORPHAN TABLE ROW"
