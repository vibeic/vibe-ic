"""CZT2-15/16 — the wall clocks a call-site census structurally cannot see.

v1.17.70 removed all 20 `subprocess.run(timeout=<literal>)` sites at >= 300 s
from the runners, and a shipped test asserts that population stays empty.  It
is the WRONG DENOMINATOR on its own, because a bound has three hiding places
where the literal is not at the call site:

  (a) a DATA TABLE the loop unpacks -- `for step, prog, argv, timeout_s in
      order:` with the seconds sitting in a tuple;
  (b) a PARAMETER DEFAULT that callers ride -- `def f(..., timeout=900)`;
  (c) a forward through a wrapper until it reaches `subprocess.run`.

MEASURED on v1.17.70 (`tools/effective_bounds.py`): SIX effective >= 300 s
bounds that the literal census reports as ZERO.  Three of them were the
at-speed ATPG outer wall IN A SECOND PLACE -- DT1/DT2/DT3 at 2400 / 2400 /
1800 s in `run_at_speed_atpg_producers` -- the same defect v1.17.70 removed
from `design_one_shot_runner`'s DT1 dispatch, sitting untouched because the
number was in a tuple.  A fourth was a 900 s default (600 at one caller) on
`_run_declared_signoff_gate`, which invokes a flow-declared sign-off gate and
BLOCKS ON ITS VERDICT.

WHY REMOVING THE AT-SPEED WALL CANNOT SHRINK THE FAULT SAMPLE, re-checked for
THESE producers rather than carried over: `cmd` carries --clock / --max-faults
/ --json / --pdk-dir and no wall, budget or timeout flag, so `timeout_s`
reached the producer nowhere; and of the three producers only
`transition_fault_atpg_run` has sample sizing at all.

WHAT IS DELIBERATELY LEFT, with the evidence: the two `_docker_exec_raw`
parameter defaults (600 in design, 1800 in phase3).  Every caller that rides
them was read -- 7 in phase3, 0 in design -- and all 7 run `cat`, `ls` or
`grep` inside the container.  A backstop on a filesystem read is a backstop,
not a clock on real work.  Asserted BY NAME below, so "left" is a decision on
the record rather than a population that quietly shrank.

chip-AGNOSTIC: a static read of the shipped tree plus a synthetic fixture.
"""
import ast
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

RUNNERS = ("phase3_one_shot_runner.py", "design_one_shot_runner.py",
           "analog_one_shot_runner.py", "phase1_doc_one_shot_runner.py")

#: The two bounds left in place, by the function that declares them. Naming
#: them is what makes this an EXEMPTION rather than a gap: a new one cannot
#: appear without this list failing.
ALLOWED = {("design_one_shot_runner.py", "_docker_exec_raw"),
           ("phase3_one_shot_runner.py", "_docker_exec_raw")}


def _callee(n):
    f, parts = n.func, []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr); f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
    return ".".join(reversed(parts))


def _data_table_bounds(tree):
    """(a) numeric literals >= 300 in a table a `for` unpacks into a name that
    looks like a bound."""
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.For) or not isinstance(n.target, ast.Tuple):
            continue
        names = [e.id for e in n.target.elts if isinstance(e, ast.Name)]
        if not any(("timeout" in x or "budget" in x or "wall" in x)
                   for x in names):
            continue
        src = n.iter
        if isinstance(src, ast.Name):
            # NEAREST PRECEDING assignment. Written as "the first one in the
            # file" it resolved an unrelated variable of the same name and
            # reported zero -- see test_the_reader_can_still_find_one.
            want, best = src.id, None
            for a in ast.walk(tree):
                if not isinstance(a, ast.Assign) or a.lineno > n.lineno:
                    continue
                if any(isinstance(t, ast.Name) and t.id == want
                       for t in a.targets):
                    if best is None or a.lineno > best.lineno:
                        best = a
            if best is not None:
                src = best.value
        for lit in ast.walk(src):
            if (isinstance(lit, ast.Constant)
                    and isinstance(lit.value, (int, float))
                    and not isinstance(lit.value, bool) and lit.value >= 300):
                out.append((lit.lineno, lit.value))
    return out


def _param_default_bounds(tree):
    """(b) parameter defaults >= 300 on a def that hands that parameter to
    `subprocess.run(timeout=...)`. The callee check is load-bearing: without
    it a mere FORWARD to another helper counted, and a forward is not a bound."""
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = fn.args.args + fn.args.kwonlyargs
        defs = ([None] * (len(fn.args.args) - len(fn.args.defaults))
                + list(fn.args.defaults) + list(fn.args.kw_defaults))
        for a, d in zip(args, defs):
            if d is None:
                continue
            try:
                v = ast.literal_eval(d)
            except Exception:
                continue
            if (not isinstance(v, (int, float)) or isinstance(v, bool)
                    or v < 300):
                continue
            for c in ast.walk(fn):
                if not isinstance(c, ast.Call) or _callee(c) != "subprocess.run":
                    continue
                if any(k.arg == "timeout" and isinstance(k.value, ast.Name)
                       and k.value.id == a.arg for k in c.keywords):
                    out.append((fn.name, a.arg, v))
    return out


# ---------------------------------------------------------------------------
# THE DEFECT
# ---------------------------------------------------------------------------
def test_no_runner_hides_a_wall_clock_in_a_data_table():
    """The hiding place the literal census cannot see at all."""
    offenders = []
    for name in RUNNERS:
        path = PROGRAMS / name
        assert path.is_file(), name
        offenders += [(name, ln, v) for ln, v in
                      _data_table_bounds(ast.parse(path.read_text()))]
    assert offenders == [], offenders


def test_every_parameter_default_bound_is_one_that_was_decided():
    """(b), with the exemptions NAMED rather than a population that shrank."""
    found = []
    for name in RUNNERS:
        path = PROGRAMS / name
        assert path.is_file(), name
        for fname, arg, v in _param_default_bounds(ast.parse(path.read_text())):
            found.append((name, fname, arg, v))
    unexpected = [f for f in found if (f[0], f[1]) not in ALLOWED]
    assert unexpected == [], unexpected
    # ...and the exemptions must still EXIST. An exemption list that has
    # quietly stopped matching anything is indistinguishable from a clean tree.
    still = {(f[0], f[1]) for f in found}
    assert still == ALLOWED, (sorted(ALLOWED - still), sorted(still - ALLOWED))


def test_the_at_speed_dispatch_imposes_no_outer_wall():
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "run_at_speed_atpg_producers")
    dispatches = [c for c in ast.walk(fn)
                  if isinstance(c, ast.Call) and c.args
                  and isinstance(c.args[0], ast.Name) and c.args[0].id == "cmd"]
    assert dispatches, "the producer dispatch is no longer cmd-shaped"
    for c in dispatches:
        bad = [k.arg for k in c.keywords
               if k.arg in ("timeout", "timeout_s", "hard_ceiling_s")]
        assert bad == [], (bad, ast.unparse(c)[:120])


def test_the_at_speed_argv_still_hands_the_producer_no_budget():
    """The reason removing the wall cannot move the fault sample. Read with
    `ast` so a COMMENT mentioning a budget cannot satisfy it -- exactly the
    over-match that had to be corrected while measuring this."""
    tree = ast.parse((PROGRAMS / "phase3_one_shot_runner.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "run_at_speed_atpg_producers")
    argv = [ast.unparse(a) for a in ast.walk(fn)
            if (isinstance(a, ast.Assign)
                and any(getattr(t, "id", "") == "cmd" for t in a.targets))
            or (isinstance(a, ast.AugAssign)
                and getattr(a.target, "id", "") == "cmd")]
    assert argv, "cmd is not built here any more — anchor is stale"
    joined = " ".join(argv)
    for flag in ("--timeout", "--wall", "--budget", "--wall-budget"):
        assert flag not in joined, (flag, joined)
    assert "timeout_s" not in joined


def test_the_declared_signoff_gate_takes_no_timeout_at_all():
    """A verdict-bearing dispatch: this function invokes a flow-declared
    sign-off gate and blocks on its verdict, so a clock decided whether a
    declared gate got to answer."""
    import phase3_one_shot_runner as R
    import inspect
    params = inspect.signature(R._run_declared_signoff_gate).parameters
    assert "timeout" not in params, sorted(params)
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    for c in ast.walk(tree):
        if (isinstance(c, ast.Call)
                and getattr(c.func, "id", "") == "_run_declared_signoff_gate"):
            assert [k.arg for k in c.keywords if k.arg == "timeout"] == [], \
                ast.unparse(c)[:140]


def test_a_stalled_signoff_gate_still_reaches_NOT_CHECKED(tmp_path,
                                                          monkeypatch):
    """THE TIER MUST NOT MOVE. It was already honest -- an expiry reached the
    reader as NOT_CHECKED, never as a verdict about the design -- and a stall
    must land in exactly the same place. Removing a kill must not also remove
    the honest word for the case that remains."""
    import phase3_one_shot_runner as R
    import _progress_run as _pr

    def stall(cmd, **kw):
        raise _pr.Stalled(cmd, looks=12, poll_s=30.0, elapsed_s=361.0,
                          signals={"output": True, "cpu": True, "io": True})

    monkeypatch.setattr(R._pr, "run", stall)
    res = R._run_declared_signoff_gate(
        tmp_path, "some_gate", "drv_promotion_corroboration_check.py",
        "reports/phase3/sta/x.json")
    assert res.status not in ("PASS", "FAIL"), (res.status, res.detail)
    assert "could not run" in res.detail or "NOT" in res.detail.upper()
    assert "STALLED" in res.detail


# ---------------------------------------------------------------------------
# THE READER ITSELF — it reported zero twice while it was being written
# ---------------------------------------------------------------------------
def test_the_reader_can_still_find_one(tmp_path):
    """A population reader that has silently stopped matching reports an empty
    offender list forever, and an empty answer from a broken reader is
    byte-identical to a clean tree.

    Both failures below really happened while measuring this: the data-table
    reader first walked the `for` header (where the constants are not), then
    resolved the table name to the FIRST assignment of that name anywhere in a
    50k-line file instead of the nearest preceding one. Each time it printed a
    confident zero.
    """
    f = tmp_path / "subject.py"
    f.write_text(
        "import subprocess\n"
        "def unrelated():\n"
        "    order = [('x', 1)]\n"          # a decoy of the same name, EARLIER
        "    return order\n"
        "def go():\n"
        "    order = (('DT1', 'p.py', [], 2400),\n"
        "             ('DT2', 'q.py', [], 120))\n"
        "    for step, prog, argv, timeout_s in order:\n"
        "        subprocess.run([prog], timeout=timeout_s)\n"
        "def helper(cmd, timeout=900):\n"
        "    return subprocess.run(cmd, timeout=timeout)\n"
        "def forwards(cmd, timeout=1200):\n"   # a FORWARD, not a bound
        "    return helper(cmd, timeout=timeout)\n")
    tree = ast.parse(f.read_text())
    assert _data_table_bounds(tree) == [(6, 2400)], _data_table_bounds(tree)
    assert _param_default_bounds(tree) == [("helper", "timeout", 900)], \
        _param_default_bounds(tree)
