"""`shipped-path portability` — a personal absolute path in shipped source.

The mutation puts one developer's home directory into a shipped default. That
is the exact defect the gate is named for, and it is a CONTENT change to a file
the gate was already scanning: the clean arm and the mutated arm differ by one
string literal and nothing else.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "shipped-path portability"

_CLEAN = 'DEFAULT_WORKDIR = "./build"\n'
# Assembled rather than written whole so this fixture file does not itself
# carry a literal that the gate is meant to keep out of shipped source.
_DIRTY = 'DEFAULT_WORKDIR = "' + "/home/" + "avolta" + '/scratch"\n'


def _tree(work: Path, body: str) -> Path:
    root = F.git_init(work / "subject")
    (root / "programs").mkdir()
    (root / "programs" / "tool.py").write_text(
        "#!/usr/bin/env python3\n" + body)
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    return _tree(work, _CLEAN)


def can_fail(work: Path):
    return _tree(work, _DIRTY), "personal home path"
