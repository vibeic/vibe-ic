"""`benchmark doctrine sections kept` — a later edit drops a captured lesson.

THE MUTATION IS THE GATE'S OWN DOCUMENTED DEFECT. `skill_doc_section_present_
check` exists "so a future edit cannot silently drop a captured lesson": the
doctrine it guards is PROSE, prose is what a re-write quietly loses, and the
loss is invisible because the file still parses, still reads well, and still
says something. So the mutation is exactly that edit — the section heading the
gate names is reworded, and everything else about the document stays.

BOTH ARMS SHIP THE SAME ONE DOCUMENT at the same path with the same two markers
demanded of it. The denominator the gate walks is one file and two markers
either way; the red arm is red because ONE marker's answer moved from found to
missing, never because the corpus went away. (A can_fail that deleted the file
would reach rc=2 — the gate's not-found refusal — and would prove only that it
notices an absent input.)
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "benchmark doctrine sections kept"

#: The document the declaration points at, relative to the subject root.
_DOC = "skills/open-benchmark-methodology/SKILL.md"

_KEPT = """# Open Benchmark Methodology

## RULE 0 — a benchmark enters through the general flow

A benchmark is run through the flow every design is run through. A
benchmark-only harness is not a run of this plugin, it is a run of the harness.

## GENERAL-CORE / THIN-ADAPTER

A benchmark-named file may hold the IO shell and nothing else. Every judgement
lives in the general core, which no benchmark name reaches.
"""

#: The same document after the edit the gate exists to catch: the second
#: heading is REWORDED — the section is still there, still says roughly the
#: same thing, and the captured phrase the tree keys on is gone.
_DROPPED = """# Open Benchmark Methodology

## RULE 0 — a benchmark enters through the general flow

A benchmark is run through the flow every design is run through. A
benchmark-only harness is not a run of this plugin, it is a run of the harness.

## Shared core, thin per-benchmark adapters

A benchmark-named file may hold the IO shell and nothing else. Every judgement
lives in the general core, which no benchmark name reaches.
"""


def _tree(work: Path, body: str) -> Path:
    root = F.git_init(work / "subject")
    doc = root / _DOC
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(body, encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """Both captured markers still present in the document."""
    return _tree(work, _KEPT)


def can_fail(work: Path):
    """The same document, one captured marker reworded out of it."""
    return _tree(work, _DROPPED), "missing doctrine marker"
