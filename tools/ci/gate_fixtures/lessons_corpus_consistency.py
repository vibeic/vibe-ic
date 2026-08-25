"""`lessons corpus consistency` — a convention section that steers to a FAILING choice.

THE MUTATION IS THE GATE'S OWN DOCUMENTED DEFECT. `lessons_corpus_consistency_
check`'s header names the instance it was written for: an async-FIFO section
that directed the author to "make the RAM read COMBINATIONAL", hard-coding one
pole of a decision the SPEC owns and inverting the golden's registered read. The
durable rule it ships is that a `### Skill:` section may not prescribe a fixed
pole on a spec-governed axis unless it defers to the spec — so the mutation here
strips the deference clause off exactly such a directive and leaves the
prescription standing. That is the shape a harmful convention actually takes: it
reads like advice.

BOTH ARMS SHIP THE SAME CORPUS at the same path — two `### Skill:` sections,
the same two genres (fifo, shifter), the same headings, the same Pattern blocks.
The only difference is the tail of ONE directive sentence. The red arm is red
because the ANSWER on the read-timing axis moved from "follow the spec" to a
hard-coded pole, not because the gate was handed a smaller corpus: strip the
subject instead and the gate exits 2 (`corpus not found`), which is the vacuity
path and proves nothing about the predicate.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "lessons corpus consistency"

#: The corpus the declaration points at, relative to the subject root. The
#: program's OWN default resolves beside its source file — i.e. inside the real
#: plugin — so the declaration names this path explicitly and the fixture can
#: own the input without touching `$PG`.
_CORPUS = "agents/ic-expert-agent.md"

_HEAD = """# IC Expert Agent — captured lessons (corpus)

Sections below are the general, chip-AGNOSTIC patterns a blind author reads
before authoring. Each one is rendered into that run's `lessons.md`.

### Skill: async FIFO read-timing convention

**Pattern**: classic FIFO templates default to a REGISTERED read of the RAM,
and a design that wants the first word on the same cycle does not.

**What to do**: Make the RAM read COMBINATIONAL """

_TAIL = """

### Skill: barrel shifter fill convention

**Pattern**: a shift-amount port says nothing about what enters the vacated
bit positions, and two correct designs disagree about it.

**What to do**: Use a logical shift with zero-fill unless the spec asks for a
rotate.
"""

#: DEFERS to the spec on the contested axis — the section still gives the
#: author a direction, and conditions it on what the spec declares.
_GOOD = _HEAD + "when the spec declares a zero-latency read port." + _TAIL

#: The same sentence with the deference clause removed: one pole, hard-coded,
#: for every design. This is the #741 instance.
_BAD = _HEAD + "on every FIFO you author." + _TAIL


def _tree(work: Path, body: str) -> Path:
    root = F.git_init(work / "subject")
    doc = root / _CORPUS
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(body, encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """Two sections, two genres, and the read-timing directive defers to the spec."""
    return _tree(work, _GOOD)


def can_fail(work: Path):
    """The same two sections; the read-timing directive now hard-codes a pole."""
    return _tree(work, _BAD), "axis=read-timing genre=fifo"
