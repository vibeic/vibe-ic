"""`no retired pytest plugin request` — an argv the anchored runtime cannot run.

The corpus stays: one tracked, committed Python module that builds a pytest
command line, in both arms. The mutation changes only what is INSIDE that argv
-- it inserts the request for a plugin the anchored runner image does not carry
-- so the gate is given the same corpus to look at in both directions and only
the ANSWER moves.

WHY THIS PARTICULAR MUTATION. MEASURED 2026-08-20 at 9cc09b863 (v1.11.5): the
same 90 test cases from the same tree gave 30 red inside the anchored image and
3 on a developer host, a 28-test set difference whose entire content was that
`-p <name>` is a HARD import and the image does not carry the module. Nothing in
the tree looked for that shape, because the retirement had been enforced five
times and every one of the five was scoped to ONE named file.

The mutated argv is written as TEXT into the subject tree rather than built as a
literal here, so this fixture -- which is itself a tracked file the gate scans on
every real run -- can never be its own finding.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "no retired pytest plugin request"

_CLEAN = (
    "import sys\n"
    "\n"
    "CMD = [sys.executable, \"-m\", \"pytest\", \"-q\", \"-p\",\n"
    "       \"no:cacheprovider\", \"t.py\"]\n"
)

#: The SAME argv with the retired plugin requested. Assembled from fragments so
#: the token never appears as one adjacent pair in this file's own source.
_DIRTY = (
    "import sys\n"
    "\n"
    "CMD = [sys.executable, \"-m\", \"pytest\", \"-q\", \"-p\",\n"
    "       \"pytest" + "_timeout\", \"--timeout=180\", \"t.py\"]\n"
)


def _tree(work: Path, body: str) -> Path:
    root = F.git_init(work / "subject")
    pkg = root / "tools"
    pkg.mkdir()
    (pkg / "runner.py").write_text(body, encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    return _tree(work, _CLEAN)


def can_fail(work: Path):
    return _tree(work, _DIRTY), "retired pytest-plugin request"
