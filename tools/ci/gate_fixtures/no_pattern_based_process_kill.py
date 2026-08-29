"""`no pattern-based process kill` — a reaper that picks its victim by name.

THE DEFECT THE GATE EXISTS FOR, in its own measurement: two runs of the same
tool on the same design carry the SAME argv, and on this fleet both live in one
shared PID namespace, so `pkill -f <marker>` reaps a STRANGER at least as
readily as its own child. It was seen three times in one night; once the stray
SIGTERM fell through to a hard FAIL and a healthy design was published as a
proven non-equivalence.

THE MUTATION IS THE SELECTION, NOT THE KILL. Both arms ship a reaper at the same
path that terminates a supervised job and reports the same thing. The can-pass
arm selects by IDENTITY — the `(pid, /proc starttime)` pair the gate's own
"WHAT TO DO INSTEAD" names — and the can-fail arm selects the victim by matching
a command-line pattern instead. Only the selection moves, so the refusal is
about the predicate and not about "a reaper appeared".

WHY THE CAN-PASS ARM STILL KILLS SOMETHING. A can-pass that simply contained no
kill at all would leave the gate's PASS resting on the absence of its subject,
which proves nothing about a tree that does reap processes; and the gate routes
a file-less root to NOT CHECKED rather than to a pass, so a thin arm would not
even reach the predicate. The arm ships a real `os.kill` on a real pid so the
gate has to decide that identity-based selection is ALLOWED, which is the branch
under test.

THE BANNED PRIMITIVE IS ASSEMBLED FROM FRAGMENTS in the can-fail source, and the
mutation is written into the SUBJECT tree at run time rather than spelled here,
because this file lives inside the tree the gate scans when it runs for real.
Executable code is what the gate reads — it blanks docstrings first — so a
literal in this prose is safe and a literal in this module's code would not be.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "no pattern-based process kill"

#: Selection by identity: the pid plus the /proc start time that makes the pid
#: unambiguous across reuse. This is the shape the gate points authors at.
_BY_IDENTITY = '''#!/usr/bin/env python3
"""Fixture-only job reaper. Describes nothing real."""
import os
import signal
from pathlib import Path


def _starttime(pid):
    fields = Path("/proc/%d/stat" % pid).read_text().rsplit(") ", 1)[1].split()
    return fields[19]


def reap(pid, stamped_starttime):
    if _starttime(pid) != stamped_starttime:
        return False
    os.kill(pid, signal.SIGTERM)
    return True
'''

#: The same reaper, selecting by a command-line pattern instead. `_BANNED` is
#: assembled so this fixture module never spells the primitive in its own code.
_BY_PATTERN = '''#!/usr/bin/env python3
"""Fixture-only job reaper. Describes nothing real."""
import subprocess


def reap(pid, stamped_starttime):
    subprocess.run(["{banned}", "-TERM", "-f", "vibeic-job-marker"], check=False)
    return True
'''

_BANNED = "pk" + "ill"


def _tree(work: Path, body: str) -> Path:
    root = F.git_init(work / "subject")
    (root / "programs").mkdir(parents=True, exist_ok=True)
    (root / "programs" / "job_reaper.py").write_text(body, encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """A reaper that selects by `(pid, /proc starttime)` and must be accepted."""
    return _tree(work, _BY_IDENTITY)


def can_fail(work: Path):
    """The same reaper, selecting its victim by a command-line pattern."""
    return (_tree(work, _BY_PATTERN.format(banned=_BANNED)),
            "a process is being selected")
