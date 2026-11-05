"""CZT-11 — the literal wall clocks on PRODUCER dispatches, and what they did.

Every site in this class wrote `subprocess.run(cmd, timeout=N)` with N a
literal 300..1800 s, and caught `(OSError, subprocess.TimeoutExpired)` into ONE
arm.  That single arm collapses two facts a reader needs apart:

  * the producer could not be LAUNCHED  -- the environment really is missing
    something, and ENV_UNAVAILABLE (a waiver tier) is the right word;
  * the producer WAS launched and the CLOCK ran out -- which says nothing about
    the environment and everything about the host.  Reported as
    ENV_UNAVAILABLE, a busy machine silently converted a step that owes an
    answer into an excused one.

`_progress_run` is the replacement primitive: it watches the child's output,
CPU and I/O (and its live descendants'), so a child that is PROGRESSING is
never stopped however long it legitimately takes, and only a child with
NOTHING moving across N consecutive looks raises `Stalled` -- a finding about
the child, which an expiry never was.

A stall becomes BLOCKED, not ENV_UNAVAILABLE.  That is STRICTER, not looser:
`_aggregate_verdict` groups BLOCKED with FAIL while ENV_UNAVAILABLE is a waiver
tier, so this conversion can only refuse a green it used to grant.

WHY THERE IS NO "RUN IT FOR 1800 SECONDS" TEST.  The claim is not "the bound
is bigger"; it is that there is NO bound, and a test that waited out any
particular number would only demonstrate a bigger one.  The claim is proved
where it lives instead: the argument cannot be passed (`_pr.run` has no
`timeout` parameter, asserted from its signature), the call site passes no
bound (asserted from the actual kwargs), and a genuinely hung child IS still
stopped (driven for real, below, at a scaled-down look cadence).

chip-AGNOSTIC: a synthetic child process; no chip / vendor / PDK literal.
"""
import ast
import inspect
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent

#: The population this lane converts, and the ONLY reason it is a literal list:
#: a glob would silently shrink if a file were renamed, and "no offenders" over
#: an empty population is the vacuous pass this repo keeps re-finding.
RUNNERS = ("phase3_one_shot_runner.py", "design_one_shot_runner.py",
           "analog_one_shot_runner.py", "phase1_doc_one_shot_runner.py")


# ---------------------------------------------------------------------------
# The bound cannot be passed, and is not passed
# ---------------------------------------------------------------------------
def test_the_replacement_primitive_has_no_timeout_parameter():
    """The smallest guarantee, and the one that cannot rot: the argument the
    defect was written with does not exist on the replacement, so a converted
    site cannot quietly acquire it back."""
    params = inspect.signature(_pr.run).parameters
    assert "timeout" not in params, sorted(params)




# ---------------------------------------------------------------------------
# The two outcomes, told apart
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Driven for real, both directions
# ---------------------------------------------------------------------------


def test_a_genuinely_hung_child_is_still_stopped_as_STALLED():
    """The check must be able to FIRE.  A supervisor that never stops anything
    is not a supervisor, and removing a clock without proving this would have
    replaced a wrong kill with no kill at all.

    Driven at a scaled-down look cadence (`stall_looks`/`poll_s` are the
    primitive's own parameters, not a time bound): the child sleeps, so no
    signal -- output, CPU or I/O -- can advance, which is exactly the state the
    shipped 12-look cadence detects after ~360 s.
    """
    t0 = time.time()
    try:
        _pr.run([sys.executable, "-c", "import time; time.sleep(600)"],
                stall_looks=2, poll_s=0.25)
    except _pr.Stalled as exc:
        assert exc.looks == 2, exc.looks
        assert "no forward progress" in str(exc)
    else:
        raise AssertionError("a child that moved nothing was not stopped")
    assert time.time() - t0 < 30, "the stall was not detected promptly"


# ---------------------------------------------------------------------------
# POPULATION — membership, not counts
# ---------------------------------------------------------------------------
def _literal_wall_clocks(path: Path):
    """Every `subprocess.run(timeout=<literal seconds>)` in a file, as
    `[(line, value)]`.  A literal is the only shape a reader can judge from the
    call site, and it is the shape this lane converts."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        parts = []
        while isinstance(f, ast.Attribute):
            parts.append(f.attr); f = f.value
        if isinstance(f, ast.Name):
            parts.append(f.id)
        if ".".join(reversed(parts)) != "subprocess.run":
            continue
        for k in n.keywords:
            if k.arg != "timeout":
                continue
            try:
                v = ast.literal_eval(k.value)
            except Exception:
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append((n.lineno, v))
    return out


def test_the_converted_steps_carry_no_literal_wall_clock():
    """The five phase-3 producer dispatches this batch converts, BY NAME.

    Named rather than counted: a count cannot tell a converted site from a
    deleted one, and "the number went down" is the one summary a substitution
    would not disturb.
    """
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    converted = {"step_digital_hardmacro_gen", "step_ip_release_docs_gen",
                 "step_signoff_metrics_aggregate", "step_ic_release_docs_gen"}
    seen = set()
    offenders = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.FunctionDef) or n.name not in converted:
            continue
        seen.add(n.name)
        for c in ast.walk(n):
            if not isinstance(c, ast.Call):
                continue
            f = c.func
            parts = []
            while isinstance(f, ast.Attribute):
                parts.append(f.attr); f = f.value
            if isinstance(f, ast.Name):
                parts.append(f.id)
            if ".".join(reversed(parts)) != "subprocess.run":
                continue
            for k in c.keywords:
                if k.arg == "timeout":
                    offenders.append((n.name, c.lineno,
                                      ast.unparse(k.value)))
    # THE DENOMINATOR IS ASSERTED. "No offenders" over a population of zero is
    # the vacuous pass this repo keeps re-finding; if a step is renamed this
    # test says so instead of quietly passing.
    assert seen == converted, sorted(converted - seen)
    assert offenders == [], offenders


def test_no_runner_carries_a_literal_wall_clock_at_all():
    """THE WHOLE POPULATION, by file, not a named subset.

    MEASURED on this lane's base (`origin/next/cztimeout` @ fa88faa424): 20
    `subprocess.run(timeout=<literal>)` sites at >= 300 s across these four
    files -- phase3 10, design 3, analog 5, phase1_doc 2. (The lane brief says
    25, distributed 11/7/5/2; this census reproduces the previous lane's own
    published table exactly at 20, and the measurement is what is used.)

    All 20 are gone. Asserted over the FILES so a new one cannot be added
    quietly, and reported by (file, line, value) so a failure says WHICH rather
    than how many. The denominator is asserted too: every file must be present
    and parse, or "no offenders" is a statement about a population that was
    never read.
    """
    offenders, seen = [], []
    for name in RUNNERS:
        path = PROGRAMS / name
        assert path.is_file(), name
        seen.append(name)
        offenders += [(name, ln, v) for ln, v in _literal_wall_clocks(path)
                      if v >= 300]
    assert sorted(seen) == sorted(RUNNERS), seen
    assert offenders == [], offenders


def test_the_literal_census_can_still_see_one():
    """THE CENSUS ITSELF, PROVED ABLE TO FIRE. A population reader that has
    quietly stopped matching reports an empty offender list forever, and an
    empty answer from a broken reader is byte-identical to a clean tree."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "planted.py"
        f.write_text(
            "import subprocess\n"
            "subprocess.run(['x'], timeout=600)\n"
            "subprocess.run(['y'], timeout=10)\n")
        found = _literal_wall_clocks(f)
    assert found == [(2, 600), (3, 10)], found
    assert [(ln, v) for ln, v in found if v >= 300] == [(2, 600)], found
