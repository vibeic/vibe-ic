"""`tracked JSON/YAML parses` — a tracked config blob that does not parse.

The mutation is CONTENT, not absence: the file stays tracked and stays named
`.json`, and only its bytes stop being JSON. A fixture that deleted it would
drive the gate's empty-corpus refusal instead, which says nothing about
whether the gate can read.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "tracked JSON/YAML parses"


def _tree(work: Path) -> Path:
    root = F.git_init(work / "subject")
    (root / "settings.json").write_text('{"jobs": 4, "strict": true}\n')
    (root / "profile.yaml").write_text("name: fixture\nsteps:\n  - one\n")
    return root


def can_pass(work: Path) -> Path:
    root = _tree(work)
    F.git_commit(root)
    return root


def can_fail(work: Path):
    root = _tree(work)
    F.git_commit(root)
    # Truncated mid-object: still tracked, still .json, no longer parseable.
    (root / "settings.json").write_text('{"jobs": 4, "strict":\n')
    F.git_commit(root, "mutate")
    return root, "do not parse"
