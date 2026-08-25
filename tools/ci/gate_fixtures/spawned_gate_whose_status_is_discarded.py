"""`spawned gate whose status is discarded` — a spawn that looks blocking and
decides nothing.

THE MUTATION IS THE MEASURED DEFECT ITSELF, and it is clause A of the two the
gate carries: a `subprocess` call naming a checking program where ALL THREE of
the conjunction hold — the result is UNBOUND, `check=` is off, and the call
sits inside a handler that swallows every exception. The gate's own words: "a
comment beside the call can describe it as blocking with no reader noticing the
contradiction".

Both subjects carry the SAME caller, spawning the SAME checker, from inside the
SAME swallow-all handler. The mutation drops `check=True` and nothing else. The
call still happens; the process still runs; what changes is whether its verdict
can reach anything.

THE DENOMINATORS THE GATE PRINTS ARE IDENTICAL IN BOTH DIRECTIONS. Measured:

    modules parsed                 2   ->   2
    clause A population            1   ->   1     (modules with a swallow-all handler)
    discarded gate spawns (A)      0   ->   1     <- the answer
    clause B population            1   ->   1
    run-subject, cannot run (B)    1   ->   1
    inventory rows applied         1   ->   1

The clause A POPULATION is the line worth naming: it counts modules that
contain a swallow-all handler, and `fixture_gate_runner` is in it in BOTH arms
because the handler is what the mutation leaves alone. A can-fail that reached
red by ADDING the try/except, or by adding a second module, would have moved a
printed population as well as the verdict. An empty subject prints `modules
parsed: 0` and is the vacuity path this fixture must not take.

THE SHIPPED INVENTORY IS PART OF THE SUBJECT'S CONTRACT. `$PG` stays the real
programs tree, so the gate reads its REAL `spawned_gate_status_inventory.json`,
whose single row is the clause B instance
`B::…/programs/full_suite_run_check.py::full_suite_run_check.py`. A row that
matches nothing is rc 1 by this gate's design, so the subject reproduces that
row in BOTH arms — a program whose SUBJECT is whether something ran, carrying
none of the tokens (`subprocess`, `Popen`, `os.system`, `returncode`,
`check_output`, `check_call`) that would let it start a process or read a
status. Omitting it would turn the green arm red for STALENESS, which proves
nothing about either clause's predicate.

chip-AGNOSTIC: nothing here names any IC, vendor, SKU or process.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402,F401 — the protocol's home

GATE = "spawned gate whose status is discarded"

_PROGRAMS_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"

#: CLAUSE B, and the row the shipped inventory already names. Its subject is
#: whether the suite RAN; it decides by matching a command line as TEXT. Held
#: identical across both arms so the inventory row is never stale.
#:
#: Written to carry NONE of the six tokens the gate looks for — that absence is
#: the whole finding, so a stray one here would silently un-make the green arm.
_CLAUSE_B = '''#!/usr/bin/env python3
"""Decides whether the full suite ran, by matching a recorded command line."""
from pathlib import Path

_EXPECTED = "python3 -m pytest tools/ci"


def suite_was_run(record_path):
    line = Path(record_path).read_text(encoding="utf-8").strip()
    if _EXPECTED in line:
        return "[PASS] the full suite ran"
    return "[FAIL] the full suite did not run"
'''

#: CLAUSE A, in the shape the gate ACCEPTS: the spawn raises on failure, so the
#: checker's exit status decides something. The swallow-all handler around it
#: is retained — it is the clause A population, and it must not move.
_SPAWN_CHECKED = '''#!/usr/bin/env python3
"""A caller that spawns a gate and lets that gate's exit status decide."""
import subprocess
import sys


def enforce(programs):
    try:
        subprocess.run(["python3", programs + "/some_thing_check.py"],
                       check=True)
    except Exception as exc:
        sys.stderr.write("the gate did not complete: %s\\n" % exc)
        return 2
    return 0
'''

#: THE MUTATION. `check=True` goes; everything else stays byte for byte. The
#: result is now unbound, the status is off, and the enclosing handler eats
#: whatever the call raises — the conjunction the gate names.
_SPAWN_DISCARDED = _SPAWN_CHECKED.replace(
    '        subprocess.run(["python3", programs + "/some_thing_check.py"],\n'
    '                       check=True)\n',
    '        subprocess.run(["python3", programs + "/some_thing_check.py"])\n',
)
assert _SPAWN_DISCARDED != _SPAWN_CHECKED, "the mutation did not apply"


def _tree(work: Path, caller: str) -> Path:
    root = work / "subject"
    programs = root / _PROGRAMS_REL
    programs.mkdir(parents=True, exist_ok=True)
    (programs / "full_suite_run_check.py").write_text(_CLAUSE_B,
                                                      encoding="utf-8")
    (programs / "fixture_gate_runner.py").write_text(caller, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The spawn raises on failure, so its verdict reaches the caller."""
    return _tree(work, _SPAWN_CHECKED)


def can_fail(work: Path):
    """`check=` off, result unbound, handler swallows: the status reaches nothing."""
    return _tree(work, _SPAWN_DISCARDED), \
        "gate spawn(s) whose verdict reaches nothing"
