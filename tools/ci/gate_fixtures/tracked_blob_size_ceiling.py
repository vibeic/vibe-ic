"""`tracked blob size ceiling` — a tracked blob over the 50 MB commit ceiling.

The mutation ADDS an oversized blob rather than removing anything, so the clean
arm's two blobs are still there and still scanned. What changes is the answer
about one more of them.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "tracked blob size ceiling"

#: The gate's ceiling is 50 MB decimal. One megabyte over is enough to cross it
#: and is the cheapest mutation that does; a bigger file would only make the
#: fixture slower without making the evidence stronger.
_OVER = 51 * 1000 * 1000


def _tree(work: Path) -> Path:
    root = F.git_init(work / "subject")
    (root / "README.md").write_text("fixture\n")
    (root / "small.bin").write_bytes(b"\0" * 1024)
    return root


def can_pass(work: Path) -> Path:
    root = _tree(work)
    F.git_commit(root)
    return root


def can_fail(work: Path):
    root = _tree(work)
    (root / "big.bin").write_bytes(b"\0" * _OVER)
    F.git_commit(root)
    return root, "exceed the 50 MB commit ceiling"
