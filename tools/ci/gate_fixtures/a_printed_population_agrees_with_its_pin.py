"""`a printed population agrees with its pin` — an emitter that grew a fourth
increment site and kept saying `of 3`.

THE MUTATION IS THE MEASURED DEFECT ITSELF. The gate's docstring records a lane
that added a THIRD repair to a post-route block, moved the emitted denominator,
and left the pin behind. This fixture applies that shape in the emitter-against-
itself direction: one more `incr` in the emitted script, with the literal
denominator left exactly where it was. Nothing is removed, so the gate still has
a counter and a denominator to compare — what changes is the ANSWER inside them,
which is what `MUTATION` means here.

WHY THIS FIXTURE SUPPLIES THE EXECUTABLE, AND WHY IT IS STILL THE GATE THAT LANDS
=================================================================================
The dispatcher declares this gate as

    run "a printed population agrees with its pin" "$PLUGIN" \
        python3 programs/emitter_population_pin_check.py

— a RELATIVE program path and no `$PG`. The engine substitutes the subject for
`$PLUGIN` and runs with that as cwd, so for THIS declaration the file that
executes necessarily lives inside the subject tree. That is not the fixture
reaching for the argv; it is the argv the dispatcher really uses, and the gate
is built for it: `--programs` defaults to the directory the program itself sits
in, so redirecting the subject IS how this gate's input is chosen.

The consequence is handled the strict way rather than the convenient one: the
shipped program and its private imports are COPIED OUT OF THE REAL TREE AT RUN
TIME, byte for byte. They are never stubbed and never vendored into this
directory. So the bytes executed are the bytes that land, and there is no copy
here that could drift from the program — drifting would require editing the real
one, which is the thing the gate would then be checking.
"""
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "a printed population agrees with its pin"

#: The gate and the private helpers it imports. Copied, never reimplemented.
_SHIPPED = (
    "emitter_population_pin_check.py",
    "_atomic_artefact.py",
    "_gate_usage_exit.py",
    "_vacuous_exit.py",
    "_prose_polarity.py",
)


def _emitter_source(sites: int) -> str:
    """A program that EMITS a Tcl block incrementing one counter at `sites`
    sites and then stating the literal denominator 3 for it.

    The Tcl is returned, not printed at import, and it is a plain `return` of a
    string constant rather than a module docstring — the gate deliberately skips
    docstrings, because prose recounting what a number USED TO BE is not a pin.
    """
    incrs = "\n".join(
        "    if {[repair_%d $db] == 0} { incr _prr_refused }" % (i + 1)
        for i in range(sites))
    return (
        "def emit_post_route_repairs():\n"
        "    return '''\n"
        "proc post_route_repairs {db} {\n"
        "    set _prr_refused 0\n"
        + incrs + "\n"
        "    if {$_prr_refused >= 3} { puts \"SPEF_REPAIR_PARTIAL\" }\n"
        "}\n"
        "'''\n"
    )


def _tree(work: Path, sites: int) -> Path:
    root = work / "subject"
    programs = root / "programs"
    programs.mkdir(parents=True)
    # The gate's own code, taken from the tree under test at run time.
    for name in _SHIPPED:
        shutil.copy2(F.PROGRAMS / name, programs / name)
    (programs / "post_route_emitter.py").write_text(_emitter_source(sites))
    # `--tests` defaults to <programs>/tests; give it a real, empty directory
    # rather than a missing one, so the corpus is chosen and not stumbled into.
    (programs / "tests").mkdir()
    return root


def can_pass(work: Path) -> Path:
    """Three increment sites, denominator 3. The two statements agree."""
    return _tree(work, 3)


def can_fail(work: Path):
    """A fourth repair arrives; `>= 3` is now a population the emitter cannot
    produce. The emitter states one population twice and disagrees with itself.
    """
    return _tree(work, 4), "disagrees with itself"
