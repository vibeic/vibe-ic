"""`changelog command reproducibility` - a quoted command that cannot be run.

A document that quotes `$ python3 some_tool.py` is making a promise: that a
reader can run it. When the file moved or was never there, the promise is a
citation to nothing, and the reader discovers it only by trying.

Both arms quote exactly ONE command in the same CHANGELOG. In can_pass it names
`programs/emit_rate.py`, which the subject ships; in can_fail it names a program
the subject does not contain. Same denominator, one changed answer.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "changelog command reproducibility"


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
    return _tree(work, "# Changelog\n\n## v0.0.1\n\n- reproduce with:\n\n```\n$ python3 programs/emit_rate.py\n```\n", _HONEST)


def can_fail(work: Path):
    """The same one claim, now with nothing behind it."""
    return _tree(work, "# Changelog\n\n## v0.0.1\n\n- reproduce with:\n\n```\n$ python3 programs/not_shipped_here.py\n```\n", _HONEST), "MISSING_SCRIPT"
