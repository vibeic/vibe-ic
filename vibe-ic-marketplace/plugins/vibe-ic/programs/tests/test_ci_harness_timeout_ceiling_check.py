"""Unit tests for ci_harness_timeout_ceiling_check.py (vibe-ic#542).

Pins, in the order the gate can be wrong:

  * the harness bound is READ from the workflows, ALL of them, and the binding
    one is the MINIMUM — the repo declares four and they disagree;
  * an unreadable bound is rc 2 with a "NOT a pass" sentence, never rc 0;
  * `ast`, not grep: a `def runner(cmd, timeout=3600)` signature and a
    `--timeout=900` inside a docstring are not bounds;
  * the callee allowlist: aliases and `from`-imports resolve, exception
    constructors do not count, same-file wrappers do, unresolvable callees are
    ADVISORY and are printed rather than silently dropped;
  * a bound spelled as a module constant is resolved — that shape hid the
    single largest offender in the tree from the report that opened the issue;
  * FALSIFIABILITY against the real tree: inject an offender, the shipped gate
    goes rc 1 and names it; remove it, rc 0.

Every bound in this file is `_T`, which the last test asserts is inside the
ceiling the gate itself computes — a test file that policed the corpus while
breaking the rule would be its own counter-example.
"""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import ci_harness_timeout_ceiling_check as C          # noqa: E402

_PROG = _PROGRAMS / "ci_harness_timeout_ceiling_check.py"

#: Inner bound for every subprocess this file launches. The gate under test is
#: a pure parse over a handful of files and measures in well under a second, so
#: 30 s is ~100x headroom and half the ceiling the gate itself publishes.
_T = 30


def _workflow(tmp_path: Path, *commands: str) -> Path:
    """A repo-shaped root with one workflow file carrying `commands`."""
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    body = "jobs:\n  t:\n    steps:\n      - run: |\n"
    body += "".join(f"          {c}\n" for c in commands)
    (wf / "ci.yml").write_text(body, encoding="utf-8")
    return tmp_path


# ── the bound is read, and all of it ─────────────────────────────────────────

def test_the_binding_bound_is_the_minimum_not_the_first(tmp_path):
    """Four invocations, two values. A resolver that returned the first match
    would answer with whichever the glob happened to yield first."""
    _workflow(tmp_path,
              "pytest -q --maxfail=10 --timeout=300 --timeout-method=thread",
              "pytest -q --timeout=180 --timeout-method=thread")
    bounds = C.harness_bounds(tmp_path)
    assert [b.seconds for b in bounds] == [300, 180]
    assert C.ci_harness_timeout_seconds(tmp_path) == 180


def test_a_bound_on_a_continuation_line_still_belongs_to_its_command(tmp_path):
    _workflow(tmp_path,
              "xargs pytest -q --maxfail=10 \\",
              "--timeout=180 --timeout-method=thread")
    assert C.ci_harness_timeout_seconds(tmp_path) == 180


def test_the_space_form_of_the_flag_is_read(tmp_path):
    _workflow(tmp_path, "pytest -q --timeout 90")
    assert C.ci_harness_timeout_seconds(tmp_path) == 90


def test_installing_the_plugin_is_not_a_bound(tmp_path):
    """`pip install pytest-timeout` names the plugin. It declares nothing."""
    _workflow(tmp_path, "python -m pip install pytest pyyaml pytest-timeout")
    assert C.harness_bounds(tmp_path) == []
    assert C.ci_harness_timeout_seconds(tmp_path) is None


def test_the_ceiling_is_a_fraction_of_the_bound(tmp_path):
    """Not a hair under it: a call bounded at 179 s under a 180 s harness still
    consumes the whole budget and starves everything scheduled after it."""
    _workflow(tmp_path, "pytest --timeout=180")
    assert C.inner_timeout_ceiling(tmp_path) == 180 // C.CEILING_DIVISOR
    assert C.CEILING_DIVISOR >= 3, (
        "a divisor of 2 still lets a two-call test reach 2 x 89 = 178 s, and "
        "19 test functions in this corpus make two bounded calls")


def test_the_shipped_workflows_declare_more_than_one_bound():
    """The measurement behind reading instead of restating: the repo really
    does declare several, and they really do disagree. If this ever collapses
    to one value the resolver is still right — but the ARGUMENT in the gate's
    docstring would be stale, and this is what would say so."""
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no .github/workflows in reach")
    bounds = C.harness_bounds(root)
    assert len(bounds) >= 2, [b.as_dict() for b in bounds]
    assert C.ci_harness_timeout_seconds(root) == min(b.seconds for b in bounds)


# ── an unreadable bound is not a pass ────────────────────────────────────────

def test_no_workflow_is_rc_2_and_says_it_is_not_a_pass(tmp_path):
    proc = subprocess.run([sys.executable, str(_PROG), str(tmp_path)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "CANNOT DETERMINE" in proc.stdout
    assert "NOT a" in proc.stdout


def test_an_empty_tree_discloses_that_it_examined_nothing(tmp_path):
    _workflow(tmp_path, "pytest --timeout=180")
    empty = tmp_path / "nothing"
    empty.mkdir()
    proc = subprocess.run(
        [sys.executable, str(_PROG), str(tmp_path), "--tests-root",
         str(empty)], capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "scanned 0 file(s)" in proc.stdout


# ── ast, not grep ────────────────────────────────────────────────────────────

_CEIL = 60


def _scan(src: str):
    return C.scan_source(textwrap.dedent(src), "f.py", _CEIL)


def test_a_test_doubles_signature_is_not_a_bound():
    """The reproduce command in the report was a grep, and this is the class it
    drowned in: a default in a function DEFINITION never blocks anything."""
    findings, unresolved, sites = _scan("""
        def runner(cmd, timeout=3600):
            return 0
    """)
    assert (findings, unresolved, sites) == ([], [], 0)


def test_a_bound_quoted_in_a_docstring_is_not_a_bound():
    findings, unresolved, sites = _scan('''
        """CI runs pytest --timeout=900 and timeout=1800 is mentioned here."""
    ''')
    assert (findings, unresolved, sites) == ([], [], 0)


def test_an_exception_constructor_records_a_bound_it_does_not_impose():
    findings, unresolved, sites = _scan("""
        import subprocess
        raise subprocess.TimeoutExpired("cmd", timeout=900)
    """)
    assert findings == [] and unresolved == []


# ── the callee allowlist ─────────────────────────────────────────────────────

@pytest.mark.parametrize("src,why", [
    ("import subprocess\nsubprocess.run(['x'], timeout=900)\n",
     "subprocess launcher"),
    ("import subprocess as sp\nsp.check_output(['x'], timeout=900)\n",
     "subprocess launcher"),
    ("from subprocess import run\nrun(['x'], timeout=900)\n",
     "subprocess launcher (imported by name)"),
    ("p = None\np.communicate(timeout=900)\n",
     "blocking child-process method"),
    ("p = None\np.wait(timeout=900)\n",
     "blocking child-process method"),
    ("_docker_exec('c', ['x'], timeout=900)\n", "container invocation"),
])
def test_the_blocking_surface_is_flagged(src, why):
    findings, unresolved, _n = _scan(src)
    assert len(findings) == 1 and not unresolved, (findings, unresolved)
    assert findings[0].resolved_via == why
    assert findings[0].seconds == 900


def test_a_same_file_wrapper_that_names_its_timeout_is_resolved():
    findings, _u, _n = _scan("""
        import subprocess
        def _launch(args, timeout):
            return subprocess.run(args, timeout=timeout)
        _launch(['x'], timeout=900)
    """)
    assert [f.line for f in findings] == [5]
    assert "forwarding" in findings[0].resolved_via


def test_a_same_file_wrapper_that_splats_kwargs_is_resolved():
    """The shape the first draft of this gate missed. The timeout never appears
    by name in the wrapper; the splat is the forwarding."""
    findings, unresolved, _n = _scan("""
        import subprocess
        def _run(args, **kw):
            return subprocess.run(args, **kw)
        _run(['x'], timeout=900)
    """)
    assert [f.line for f in findings] == [5], (findings, unresolved)


def test_a_chain_of_wrappers_resolves_to_a_fixed_point():
    findings, _u, _n = _scan("""
        import subprocess
        def _inner(args, **kw):
            return subprocess.run(args, **kw)
        def _outer(args, **kw):
            return _inner(args, **kw)
        _outer(['x'], timeout=900)
    """)
    assert [f.line for f in findings] == [7]


def test_an_unresolvable_callee_is_advisory_not_a_finding():
    """A double that is not defined here could be anything. The gate says so
    rather than guessing in either direction."""
    findings, unresolved, _n = _scan("mock_runner(['x'], timeout=900)\n")
    assert findings == []
    assert [u.line for u in unresolved] == [1]
    assert "not resolvable" in unresolved[0].resolved_via


def test_the_advisory_population_is_printed_with_its_denominator(tmp_path):
    """An exclusion a reader cannot see is indistinguishable from a clean
    result. This is the one thing the allowlist owes."""
    _workflow(tmp_path, "pytest --timeout=180")
    tests = tmp_path / "t"
    tests.mkdir()
    (tests / "test_x.py").write_text("mock_runner(['x'], timeout=900)\n",
                                     encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_PROG), str(tmp_path), "--tests-root",
         str(tests)], capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "NOT judged" in proc.stdout and ": 1" in proc.stdout
    assert "mock_runner" in proc.stdout


# ── a bound spelled as a constant ────────────────────────────────────────────

def test_a_module_constant_bound_is_resolved_to_its_value():
    """The shape that hid the largest offender in the tree: one declaration,
    five real launcher calls, and nothing at any call site to grep for."""
    findings, _u, _n = _scan("""
        import subprocess
        _SUBPROCESS_TIMEOUT_S = 900
        subprocess.run(['x'], timeout=_SUBPROCESS_TIMEOUT_S)
    """)
    assert len(findings) == 1
    assert findings[0].seconds == 900
    assert findings[0].constant == "_SUBPROCESS_TIMEOUT_S"
    assert findings[0].constant_line == 3
    assert "_SUBPROCESS_TIMEOUT_S" in str(findings[0])


def test_a_constant_assigned_inside_a_function_is_not_resolved():
    """It can be rebound on a branch, so a value picked here might be one the
    call never receives. Not judged beats judged wrong."""
    findings, unresolved, _n = _scan("""
        import subprocess
        def go():
            t = 900
            subprocess.run(['x'], timeout=t)
    """)
    assert findings == [] and unresolved == []


def test_the_ceiling_itself_is_allowed_and_one_second_over_is_not():
    at, _u, _n = _scan(f"import subprocess\n"
                       f"subprocess.run(['x'], timeout={_CEIL})\n")
    over, _u2, _n2 = _scan(f"import subprocess\n"
                           f"subprocess.run(['x'], timeout={_CEIL + 1})\n")
    assert at == []
    assert [f.seconds for f in over] == [_CEIL + 1]


# ── falsifiability against the real tree ─────────────────────────────────────

def test_the_shipped_tree_passes_and_an_injected_offender_fails(tmp_path):
    """A gate that has never failed has not been shown to work.

    Runs the SHIPPED program against the SHIPPED tree twice: clean, then with
    one offender written into the real scan root, then clean again. The file is
    removed in a finally so a failure cannot leave the tree dirty.
    """
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no .github/workflows in reach")
    tests_root = _PROGRAMS / "tests"
    argv = [sys.executable, str(_PROG), str(root)]

    before = subprocess.run(argv, capture_output=True, text=True, timeout=_T)
    assert before.returncode == 0, before.stdout[-4000:] + before.stderr[-2000:]

    victim = tests_root / "_ci_timeout_ceiling_injected_offender.py"
    try:
        victim.write_text("import subprocess\n"
                          "subprocess.run(['true'], timeout=900)\n",
                          encoding="utf-8")
        red = subprocess.run(argv, capture_output=True, text=True, timeout=_T)
    finally:
        victim.unlink(missing_ok=True)
    assert red.returncode == 1, red.stdout[-4000:]
    assert victim.name in red.stdout and "timeout=900" in red.stdout

    after = subprocess.run(argv, capture_output=True, text=True, timeout=_T)
    assert after.returncode == 0, after.stdout[-4000:]


def test_the_json_record_carries_what_the_text_says(tmp_path):
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no .github/workflows in reach")
    out = tmp_path / "r.json"
    proc = subprocess.run(
        [sys.executable, str(_PROG), str(root), "--json", str(out)],
        capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 0, proc.stdout[-4000:]
    doc = json.loads(out.read_text())
    assert doc["passed"] is True and doc["findings"] == []
    assert doc["ceiling_seconds"] == \
        doc["harness_seconds"] // doc["ceiling_divisor"]
    assert doc["files"] > 0 and doc["bounded_sites"] > 0
    assert len(doc["harness_bounds"]) >= 2


#: The advisory residual on the shipped tree at wiring time, after every entry
#: was opened and read. All ten are calls whose target is MONKEYPATCHED or does
#: not launch anything, so the number they carry is data rather than a bound:
#:
#:   * `tdf._build_batch_script(sat_timeout=...)` x3 — builds a solver script
#:     as a STRING; nothing runs at the call;
#:   * `lec_run.run_yosys_equiv(timeout=7200)` — `lec_run._docker` is patched to
#:     a fake process, and 7200 is the value the test ASSERTS about (the budget
#:     marker), so lowering it would change what the test means;
#:   * `dosr._sim_run_or_reuse` x3 and `R._sim_run_or_reuse` x3 — the launcher
#:     under them is patched out in every one of those tests.
#:
#: Three MORE were in this list and are not any more: two KLayout fixture runs
#: and one container yosys cut, all genuinely blocking, all lowered to the
#: ceiling. The count is a ratchet: it may shrink freely, and a rise means a new
#: unresolvable callee arrived and nobody has read it.
_REVIEWED_ADVISORY_RESIDUAL = 10


def test_the_advisory_residual_does_not_grow_unreviewed(tmp_path):
    """An allowlist earns its exclusions by having them read.

    A count, not a list of names: a hand-written list of the ten would be a
    second registry beside the code, free to drift from it (#527/#530/#534).
    """
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no .github/workflows in reach")
    out = tmp_path / "r.json"
    subprocess.run([sys.executable, str(_PROG), str(root), "--json", str(out)],
                   capture_output=True, text=True, timeout=_T)
    doc = json.loads(out.read_text())
    n = len(doc["unresolved_above_ceiling"])
    assert n <= _REVIEWED_ADVISORY_RESIDUAL, (
        f"{n} unresolvable bounds above the ceiling, "
        f"{_REVIEWED_ADVISORY_RESIDUAL} were reviewed — read the new ones and "
        "either lower them or record why they are not bounds:\n  "
        + "\n  ".join(f"{u['path']}:{u['line']} {u['callee']}"
                      f"({u['keyword']}={u['seconds']})"
                      for u in doc["unresolved_above_ceiling"]))


# ── the gate is dispatched, not merely present ───────────────────────────────

def test_the_gate_is_declared_in_the_hygiene_set():
    """#538 verbatim otherwise: a check that exists and is not dispatched.

    `--list` is the dispatcher's own record of what it wires, so this reads the
    DECLARATION rather than grepping the script — and both CI and the merge
    gate invoke that same script, so one appearance covers both paths.
    """
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no repo root in reach")
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    if not script.is_file():
        pytest.skip("hygiene script not shipped in this tree")
    proc = subprocess.run(["bash", str(script), "--list"], cwd=str(root),
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "inner timeouts fit the harness" in proc.stdout.splitlines()


def test_the_gate_reaches_the_merge_gate_through_the_same_script():
    """The merge gate INVOKES the hygiene script (#538) instead of re-listing
    it, so a gate declared there cannot be missing here. Pinned by reading the
    merge gate's own invocation rather than by trusting the comment."""
    src = (_PROGRAMS / "gatekeeper_review.py").read_text(errors="replace")
    assert "tools/ci/repo_hygiene_gates.sh" in src
    assert "--summary-json" in src


# ── this file obeys the rule it enforces ─────────────────────────────────────

def test_this_files_own_bounds_are_inside_the_ceiling():
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no .github/workflows in reach")
    ceiling = C.inner_timeout_ceiling(root)
    assert _T <= ceiling, (_T, ceiling)
    findings, unresolved, sites = C.scan_source(
        Path(__file__).read_text(), Path(__file__).name, ceiling)
    assert sites, "no bound was READ — has the scan stopped working?"
    assert not findings and not unresolved, "\n".join(
        str(x) for x in list(findings) + list(unresolved))
