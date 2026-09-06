"""`watchdog ceiling semantics` — a supervision primitive that kills on a clock.

THE MUTATION IS THE DEFECT THE GATE WAS RE-POINTED AT. Owner ruling 2026-09-07
(vibe-ic#2051): `hard_ceiling_s` is a RECORDED BUDGET and only the progress-stall
watchdog may stop a job. MEASURED the day before on 8HD-9, two LEC yosys runs
were live under `timeout --kill-after=5 86395`, one of them 5360 s into a proof
at 1374 points proved, 0 failed, 99.9 % CPU and still advancing — a converging
tool one clock tick from being SIGKILLed and booked as a verdict about the
design. The can-fail arm puts that kill back, in the exact line the ruling
removed:

    if now - start > hard_ceiling_s:
        kill_fn(proc, "ceiling")          # <- the mutation
        return "ceiling", None

WHY THE MUTATION IS APPLIED TO THE REAL PRIMITIVE AT RUN TIME
=============================================================
`_watchdog.py` is COPIED out of the tree under test and patched, never
reimplemented here. A hand-written stand-in would be a second private copy of
the supervision loop, and the first time the real loop moved, this fixture would
go on "proving" the gate against code that no longer ships. Patching the real
bytes also means the can-PASS arm is the shipped primitive verbatim: if the
landing ever puts a clock kill back, that arm fails on its own, before the
mutation is even applied.

The insertion point is asserted, not hoped for. If the anchor is not found the
fixture RAISES — a mutation that silently did nothing would leave a can-fail arm
that passes, which reads as "the gate is broken" when the truth is "the fixture
stopped mutating".

WHAT IS DELIBERATELY THE SAME IN BOTH ARMS
==========================================
The subject carries a third file, `toy_step.py`, with an ordinary supervised
call and a clean `_progress_run` call. It is byte-identical in both arms and it
is not the thing under test: it is there so the gate has a real population to
report on, and so the two arms cannot differ in how much there was to look at.
Both arms also carry `_docker_watchdog.py`, unmutated — the second class-(0)
shape, held still while the first one moves.

NOTHING IS DELETED. The stall kill sits two lines above the mutation and is
untouched in both arms, so the gate still has a supervision loop to read and
what changed is the ANSWER inside it — which is what MUTATION means here. A
can-fail that worked by removing `_watchdog.py` would prove only that the gate
noticed a hole, and this gate correctly declines to refuse on an absent
primitive at all.

WHY THIS FIXTURE SUPPLIES THE EXECUTABLE. The dispatcher declares the gate as

    run "watchdog ceiling semantics" "$PLUGIN" \
        python3 programs/watchdog_ceiling_semantics_check.py

— a RELATIVE program path and no `$PG`. The engine substitutes the subject for
`$PLUGIN` and runs with it as cwd, so for THIS declaration the file that executes
necessarily lives inside the subject tree, and the gate is built for it: with no
`--programs-dir` it scans the directory it sits in. Redirecting the subject IS
how this gate's input is chosen. The shipped program is copied byte for byte at
run time, so what executes is what lands.

chip-AGNOSTIC: one invented step module. No IC, vendor, PDK or process.
"""
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "watchdog ceiling semantics"

#: The gate and the two primitives its class-(0) scan reads. Copied, never
#: reimplemented — see the module docstring.
_SHIPPED = (
    "watchdog_ceiling_semantics_check.py",
    "_watchdog.py",
    "_docker_watchdog.py",
)

#: The line the ruling removed, and the anchor it is re-inserted at. The anchor
#: is the guard the fixed loop opens its budget branch with; the mutation turns
#: that branch back into a kill without touching the stall branch above it.
_ANCHOR = "        if not ceiling_recorded and now - start > hard_ceiling_s:\n"
_KILL = ('        if now - start > hard_ceiling_s:\n'
         '            kill_fn(proc, "ceiling")\n'
         '            return "ceiling", None\n')

#: A population for the gate to report on. Identical in both arms: a supervised
#: launch declaring a budget, and a clean call to the replacement primitive.
_TOY_STEP = '''"""A synthetic step — the gate's ordinary population, held still."""
import _progress_run as _pr
import _watchdog as _wd

_BUDGET = 7200


def run_tool(cmd):
    return _wd.run_supervised(cmd, stall_grace_s=1800,
                              hard_ceiling_s=_BUDGET)


def probe(cmd):
    return _pr.run(cmd, capture_output=True, text=True)
'''


def _tree(work: Path, name: str) -> Path:
    root = work / name
    programs = root / "programs"
    programs.mkdir(parents=True, exist_ok=True)
    for fname in _SHIPPED:
        shutil.copy2(F.PROGRAMS / fname, programs / fname)
    (programs / "toy_step.py").write_text(_TOY_STEP, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The shipped primitives, verbatim: the budget is recorded, never spent."""
    return _tree(work, "accepted")


def can_fail(work: Path):
    """The clock kill, put back into the real supervision loop."""
    root = _tree(work, "refused")
    target = root / "programs" / "_watchdog.py"
    src = target.read_text(encoding="utf-8")
    if src.count(_ANCHOR) != 1:
        raise AssertionError(
            "watchdog ceiling semantics fixture: the budget branch of "
            "`_watchdog.supervise` no longer matches its anchor, so the "
            "can-fail arm would ship an UNMUTATED primitive and pass. Re-read "
            "the loop and re-anchor rather than relaxing this check.")
    target.write_text(src.replace(_ANCHOR, _KILL + _ANCHOR), encoding="utf-8")
    # THE TOKEN MUST BE UNIQUE TO THE REFUSAL. "RECORDED BUDGET" is not: the
    # gate prints it in a HEADER LINE on every run, so a fixture declaring it
    # would be satisfied by an arm that had refused for any reason at all, or
    # for none — the pair would look green while checking nothing. This phrase
    # occurs only in the class-(0) offender detail.
    return root, "TERMINATES a job because a clock elapsed"
