"""`tracked-symlink target present` — a tracked pointer into nothing.

The corpus stays: two tracked paths under `benchmark-data`, one of them a
symlink, in both arms. The mutation repoints that symlink at a relative path
that exists in neither the tree nor on the host, which is the "points at a file
that exists nowhere" class the gate reports — as distinct from the LOCAL class
it deliberately discloses without failing.
"""
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "tracked-symlink target present"


def _tree(work: Path, target: str) -> Path:
    root = F.git_init(work / "subject")
    corpus = root / "benchmark-data"
    corpus.mkdir()
    (corpus / "real.txt").write_text("published artefact\n")
    os.symlink(target, corpus / "pointer.txt")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    return _tree(work, "real.txt")


def can_fail(work: Path):
    return _tree(work, "absent.txt"), "exists nowhere"
