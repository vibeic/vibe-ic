"""`backlog items are tracked` — a backlog item a fresh clone never receives.

Both arms carry the SAME one backlog file on disk, so the gate's denominator is
1 in each and its "0 backlog file(s) — nothing to certify" refusal is never the
thing being measured. The mutation adds a `.gitignore` rule that excludes the
directory, which is the IGNORED_BACKLOG class: present here, absent in a clone,
and indistinguishable from a live item to anyone reading this machine.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "backlog items are tracked"

_REL = "vibe-ic-marketplace/community/backlogs"


def _tree(work: Path, ignore: str) -> Path:
    root = F.git_init(work / "subject")
    backlogs = root / _REL
    backlogs.mkdir(parents=True)
    (backlogs / "item.yaml").write_text(
        "id: BL-1\ntitle: a fixture backlog item\nstatus: open\n")
    (root / ".gitignore").write_text(ignore)
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    return _tree(work, "*.log\n")


def can_fail(work: Path):
    return _tree(work, _REL + "/\n"), "EXCLUDED by a .gitignore rule"
