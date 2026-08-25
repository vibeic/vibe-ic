"""`changelog metric reproducibility` - a published number nothing computes.

THE MUTATION IS THE GATE'S OWN MEASURED DEFECT. A CHANGELOG once stated "IR
static peak 5.231 mV" where both numbers were literals hardcoded in an emitter
and no measurement had produced them; a reader diffing the CHANGELOG had no way
to trace the metric back to a computation.

Both arms carry the SAME one CHANGELOG line and the SAME one program. The
mutation changes only whether the plugin source can account for the number:
100.0 % is what `emit_rate(12, 12)` returns, 73.418 % is a value nothing in the
tree derives or contains.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "changelog metric reproducibility"


def _tree(work: Path, changelog: str, program: str) -> Path:
    """A minimal plugin subject. BOTH ARMS BUILD THE SAME SHAPE — one CHANGELOG
    with one stated fact and one program under `programs/`. Only the answer
    moves, never the denominator."""
    root = F.git_init(work / "subject")
    programs = root / "programs"
    programs.mkdir(parents=True)
    (programs / "emit_rate.py").write_text(program, encoding="utf-8")
    (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    F.git_commit(root)
    return root


#: A program that DERIVES the published figure, carrying the `# source:`
#: justification marker the sibling literal gate reads.
_HONEST = '''"""Compute the emit rate the CHANGELOG publishes."""


def emit_rate(emitted, attempted):
    if attempted <= 0:
        return 0.0
    return 100.0 * emitted / attempted


def published():
    # source: the fixture\'s own run - 12 of 12 attempts emitted.
    return emit_rate(12, 12)
'''


def can_pass(work: Path) -> Path:
    """The published claim and the tree agree."""
    return _tree(work, "# Changelog\n\n## v0.0.1\n\n- deterministic emit rate 100.0 %\n", _HONEST)


def can_fail(work: Path):
    """The same one claim, now with nothing behind it."""
    return _tree(work, "# Changelog\n\n## v0.0.1\n\n- deterministic emit rate 73.418 %\n", _HONEST), "unreproducible"
