"""`gitignore scratch guard` — the root ignore rule this repo's scratch files need.

The mutation removes the RULE while leaving the `.gitignore` in place, so the
gate is still handed a file to read and still has a tracked tree to judge. The
answer inside it changes; the corpus does not disappear.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "gitignore scratch guard"

_RULE = "/_*.js"


def _tree(work: Path, rule: str) -> Path:
    root = F.git_init(work / "subject")
    (root / ".gitignore").write_text(rule + "\n" if rule else "*.log\n")
    (root / "README.md").write_text("fixture\n")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    return _tree(work, _RULE)


def can_fail(work: Path):
    return _tree(work, ""), "does not carry the literal line"
