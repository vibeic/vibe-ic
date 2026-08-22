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
  * …and so is a bound spelled as a PARAMETER DEFAULT (vibe-ic#1277), which
    was worse than unjudged: the call left the findings, the advisories AND
    the readable-bound denominator, so two spellings of one 1800 s bound gave
    `1 readable bound / FAIL` and `0 readable bounds / 0 not judged / PASS`;
  * a call inside a test carrying `@pytest.mark.timeout(N)` is judged against
    `N // 3`, because N is the bound pytest-timeout really applies to that
    item — and a marker BELOW the harness bound tightens the ceiling, so it is
    a model rather than an escape hatch;
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
_LAND = _PROGRAMS.parents[3] / "tools" / "gatekeeper-land.sh"

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


def _stall(tmp_path: Path, seconds: int) -> Path:
    """Declare the driver's stall window in a root, where the gate reads it.

    The gate CAPS every marker-derived ceiling at this value, because a marker is
    written by the same person whose bound is being judged and is therefore a
    dial rather than a constraint. A root without this declaration cannot judge a
    marked item at all, and the gate answers rc=2 there rather than guessing --
    so every test that exercises a marker must state the window explicitly.
    """
    p = tmp_path / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    p.mkdir(parents=True, exist_ok=True)
    (p / "pytest_per_file_junit.py").write_text(
        f"DEFAULT_STALL_AFTER = {seconds}\n", encoding="utf-8")
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


# ── the resolver must not climb out of the checkout it was handed ────────────

def _checkout(root: Path) -> Path:
    """The minimum that makes a directory look like a checkout of this repo."""
    (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic").mkdir(parents=True)
    # A FILE, as in a `git worktree` — which is what every agent here works in.
    (root / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    return root


def test_the_resolver_stops_at_its_own_checkout_root(tmp_path):
    """THE NESTING DEFECT, reproduced.

    Every subagent in this repo works in `.claude/worktrees/agent-*` under the
    main checkout. The rule was "nearest ancestor holding `.github/workflows`",
    and since #550 retired Actions no such directory exists in the repository —
    only a stale empty one left behind in the outer checkout. So the walk left
    the worktree, resolved the OUTER root, and answered PASS about a tree it had
    never been pointed at: the outer `tools/` and the outer `programs/tests`.
    """
    outer = _workflow(tmp_path / "outer", "pytest --timeout=999")
    inner = _checkout(outer / ".claude" / "worktrees" / "agent-x")
    (inner / "tools").mkdir()
    (inner / "tools" / "gatekeeper-land.sh").write_text(
        "pytest -q --timeout=180\n", encoding="utf-8")

    got = C.find_repo_root(inner / "vibe-ic-marketplace" / "plugins" /
                           "vibe-ic")
    assert got == inner, (
        f"the resolver climbed out of its own checkout and answered about "
        f"{got} — the outer tree it was never handed")
    assert C.ci_harness_timeout_seconds(inner) == 180, (
        "the bound came from the OUTER checkout's workflow")


def test_a_checkout_with_no_harness_source_refuses_the_outer_ones(tmp_path):
    """The other half, and it must NOT be repaired by climbing.

    A checkout that declares no harness bound is CANNOT DETERMINE — an honest
    rc 2 that names the missing input. Borrowing the enclosing checkout's bound
    would produce a verdict about a number this tree does not have.
    """
    outer = _workflow(tmp_path / "outer", "pytest --timeout=999")
    inner = _checkout(outer / "nested")
    assert C.find_repo_root(inner) == inner
    assert C.ci_harness_timeout_seconds(inner) is None
    proc = subprocess.run([sys.executable, str(_PROG), str(inner)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "CANNOT DETERMINE" in proc.stdout


def test_the_landing_script_alone_is_enough_to_resolve_the_bound(tmp_path):
    """Actions is disabled at the account level (#550) and the harness that
    really runs pytest is the local landing script. A fresh clone has no
    `.github/workflows` at all, and before v1.9.78 that made the resolver
    return None — so every test that depends on it SKIPPED, silently, on
    exactly the tree a clean-room run uses."""
    root = tmp_path / "clone"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "gatekeeper-land.sh").write_text(
        "xargs -a /tmp/sel.txt pytest -q --maxfail=10 --timeout=180\n",
        encoding="utf-8")
    assert C.find_repo_root(root) == root
    assert C.ci_harness_timeout_seconds(root) == 180


def _semantic_checkout(tmp_path: Path, *, lane_suffix: str = "",
                       driver_suffix: str = "") -> Path:
    root = tmp_path / "semantic"
    programs = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" /
                "programs")
    tests = programs / "tests"
    tests.mkdir(parents=True)
    (root / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    (root / "tools").mkdir()
    lanes = _LAND.read_text(encoding="utf-8")
    if lane_suffix:
        lanes = lanes.replace(
            '-- python3 -I "$PROGRAMS/trusted_pytest_entry.py" -q',
            '-- python3 -I "$PROGRAMS/trusted_pytest_entry.py" -q '
            + lane_suffix)
    (root / "tools" / "gatekeeper-land.sh").write_text(
        lanes, encoding="utf-8")
    shipped_driver = (_PROGRAMS / "pytest_per_file_junit.py").read_text(
        encoding="utf-8")
    (programs / "pytest_per_file_junit.py").write_text(
        shipped_driver + driver_suffix, encoding="utf-8")
    (tests / "test_one.py").write_text(
        "def test_one():\n    assert True\n", encoding="utf-8")
    return root


def test_semantic_landing_harness_has_no_elapsed_ceiling(tmp_path):
    root = _semantic_checkout(tmp_path)
    out = tmp_path / "semantic.json"
    proc = subprocess.run(
        [sys.executable, str(_PROG), str(root), "--json", str(out)],
        capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["mode"] == "semantic_progress"
    assert doc["harness_seconds"] is None
    assert doc["ceiling_seconds"] is None
    assert len(doc["semantic_lanes"]) == 3
    assert "elapsed time is not a test verdict" in proc.stdout


def test_half_migrated_semantic_lane_is_a_failure(tmp_path):
    root = _semantic_checkout(tmp_path, lane_suffix="--timeout=180")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "fixed pytest elapsed-time verdict" in proc.stdout


def test_semantic_driver_must_disable_output_and_total_ceiling(tmp_path):
    root = _semantic_checkout(tmp_path)
    driver = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" /
              "programs" / "pytest_per_file_junit.py")
    driver.write_text(
        "def _run_progress_supervised():\n"
        "    return run_supervised(output_progress=True, "
        "domain_progress_probe=_progress_sample, hard_ceiling_s=300)\n",
        encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "output bytes are not progress" in proc.stdout
    assert "no whole-run elapsed ceiling" in proc.stdout


def test_an_extra_direct_pytest_lane_cannot_bypass_semantic_supervision(
        tmp_path):
    root = _semantic_checkout(tmp_path)
    land = root / "tools" / "gatekeeper-land.sh"
    land.write_text(land.read_text(encoding="utf-8")
                    + "python3 -m pytest -q test_unowned.py\n",
                    encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "outside the semantic aggregate driver" in proc.stdout


@pytest.mark.parametrize("bypass", [
    "env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q",
    "run_it=(python3 -m pytest); \"${run_it[@]}\"",
    "run_pytest_alias() { python3 -m pytest -q; }; run_pytest_alias",
])
def test_alias_forms_cannot_hide_a_direct_pytest_lane(tmp_path, bypass):
    root = _semantic_checkout(tmp_path)
    land = root / "tools" / "gatekeeper-land.sh"
    land.write_text(land.read_text(encoding="utf-8") + bypass + "\n",
                    encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "outside the semantic aggregate driver" in proc.stdout


def test_echoed_driver_words_and_comment_only_contract_are_not_execution(
        tmp_path):
    root = _semantic_checkout(tmp_path)
    land = root / "tools" / "gatekeeper-land.sh"
    land.write_text("\n".join(
        f"{name}() {{\n"
        "echo 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 "
        "\"$PROGRAMS/pytest_per_file_junit.py\" --aggregate-check -- "
        "python3 -m pytest -q'\n"
        "cmd=(python3 -m pytest); \"${cmd[@]}\"\n"
        "}"
        for name in ("run_pytest", "run_repo_tools_pytest",
                     "run_unselectable_pytest")) + "\n", encoding="utf-8")
    driver = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" /
              "programs" / "pytest_per_file_junit.py")
    driver.write_text(
        "# output_progress=False\n"
        "# domain_progress_probe=_progress_sample\n"
        "# hard_ceiling_s=float('inf')\n",
        encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "exactly one semantic aggregate lane" in proc.stdout
    assert "must define _run_progress_supervised" in proc.stdout


def test_removing_every_semantic_lane_is_not_legacy_success(tmp_path):
    root = _semantic_checkout(tmp_path)
    (root / "tools" / "gatekeeper-land.sh").write_text(
        "echo no-test-lanes\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "exactly one semantic aggregate lane" in proc.stdout


@pytest.mark.parametrize("dead_prefix", [
    "false && ",
    "if false; then ",
])
def test_a_driver_command_in_dead_control_flow_is_not_a_lane(
        tmp_path, dead_prefix):
    root = _semantic_checkout(tmp_path)
    land = root / "tools" / "gatekeeper-land.sh"
    text = land.read_text(encoding="utf-8")
    if dead_prefix.startswith("false"):
        text = text.replace(
            'out="$( cd "$ROOT" && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1',
            'false && out="$( cd "$ROOT" && '
            'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1', 1)
    else:
        text = text.replace(
            'out="$( cd "$ROOT" && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1',
            'if false; then\n'
            'out="$( cd "$ROOT" && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1', 1)
        start = text.index("run_repo_tools_pytest() {")
        end = text.index("\n}", start)
        text = text[:end] + "\nfi" + text[end:]
    land.write_text(text, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert ("canonical executable lane" in proc.stdout
            or "conditional control" in proc.stdout)


def test_an_unconditional_early_return_before_the_lane_is_refused(tmp_path):
    root = _semantic_checkout(tmp_path)
    land = root / "tools" / "gatekeeper-land.sh"
    land.write_text(land.read_text(encoding="utf-8").replace(
        "run_repo_tools_pytest() {\n",
        "run_repo_tools_pytest() {\nreturn 0\n", 1), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "can leave run_repo_tools_pytest before" in proc.stdout


@pytest.mark.parametrize("population", [
    "run_pytest", "run_repo_tools_pytest", "run_unselectable_pytest",
])
def test_an_exact_lane_call_cannot_be_made_dead(tmp_path, population):
    root = _semantic_checkout(tmp_path)
    land = root / "tools" / "gatekeeper-land.sh"
    text = land.read_text(encoding="utf-8")
    needle = ("  run_pytest\n" if population == "run_pytest"
              else f"if {population}; then\n")
    replacement = ("false && run_pytest\n"
                   if population == "run_pytest"
                   else f"if false && {population}; then\n")
    text = text.replace(needle, replacement, 1)
    land.write_text(text, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert ("execution prefix" in proc.stdout
            or "reviewed top-level call site" in proc.stdout)


def test_a_top_level_early_exit_cannot_skip_every_lane(tmp_path):
    root = _semantic_checkout(tmp_path)
    land = root / "tools" / "gatekeeper-land.sh"
    text = land.read_text(encoding="utf-8")
    land.write_text(text.replace("#!/usr/bin/env bash\n",
                                 "#!/usr/bin/env bash\nexit 0\n", 1),
                    encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "execution prefix" in proc.stdout


def test_a_post_lane_success_exit_cannot_launder_a_red_lane(tmp_path):
    root = _semantic_checkout(tmp_path)
    land = root / "tools" / "gatekeeper-land.sh"
    text = land.read_text(encoding="utf-8")
    marker = "if run_unselectable_pytest; then\n"
    land.write_text(text.replace(marker, marker + "  exit 0\n", 1),
                    encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "complete reviewed executable" in proc.stdout


@pytest.mark.parametrize("population", [
    "run_pytest", "run_repo_tools_pytest", "run_unselectable_pytest",
])
def test_a_lane_cannot_be_redefined_before_its_reviewed_call(
        tmp_path, population):
    root = _semantic_checkout(tmp_path)
    land = root / "tools" / "gatekeeper-land.sh"
    text = land.read_text(encoding="utf-8")
    call = ("  run_pytest\n" if population == "run_pytest"
            else f"if {population}; then\n")
    text = text.replace(call,
                        f"function {population} {{ :; }}\n" + call, 1)
    land.write_text(text, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "execution prefix" in proc.stdout


def test_an_unused_well_shaped_driver_helper_is_not_execution(tmp_path):
    root = _semantic_checkout(tmp_path)
    driver = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" /
              "programs" / "pytest_per_file_junit.py")
    driver.write_text(
        "def run_supervised(**kwargs):\n    return 0\n"
        "def _progress_sample():\n    return None\n"
        "def _run_progress_supervised():\n"
        "    return run_supervised(output_progress=False, "
        "domain_progress_probe=_progress_sample, "
        "hard_ceiling_s=float('inf'))\n"
        "if __name__ == '__main__':\n"
        "    print('AGGREGATE_COMPLETE cases=1')\n",
        encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "not the exact reviewed executable" in proc.stdout


def test_a_shell_comment_cannot_supply_the_aggregate_subject_command(tmp_path):
    root = _semantic_checkout(tmp_path)
    land = root / "tools" / "gatekeeper-land.sh"
    text = land.read_text(encoding="utf-8")
    text = text.replace("--aggregate-check", "# --aggregate-check")
    land.write_text(text, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "does not require the aggregate" in proc.stdout
    assert "subject-command boundary" in proc.stdout


def test_shell_comment_stripping_preserves_quoted_hashes():
    assert C._strip_shell_comment("echo '# kept' # removed") == "echo '# kept' "
    assert C._strip_shell_comment('echo "# kept" # removed') == 'echo "# kept" '
    assert C._strip_shell_comment(r"echo \\#kept # removed") == r"echo \\#kept "
    assert C._strip_shell_comment("value=${x#prefix}") == "value=${x#prefix}"
    assert C._strip_shell_comment(
        'out="$( printf \'# kept\' # removed') == 'out="$( printf \'# kept\' '


@pytest.mark.parametrize("declaration", [
    "never_called() {",
    "function never_called {",
])
def test_a_never_called_nested_function_cannot_own_the_lane(
        tmp_path, declaration):
    root = _semantic_checkout(tmp_path)
    land = root / "tools" / "gatekeeper-land.sh"
    text = land.read_text(encoding="utf-8")
    start = text.index("run_repo_tools_pytest() {")
    end = text.index("\n}", start)
    body = text[start:end]
    body = body.replace("run_repo_tools_pytest() {\n",
                        "run_repo_tools_pytest() {\n" + declaration + "\n")
    body += "\n}"
    text = text[:start] + body + text[end:]
    land.write_text(text, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "nests a function" in proc.stdout


def test_the_shipped_tree_resolves_to_the_checkout_this_file_is_in():
    """No fixture can prove this one: the resolver has to answer about the tree
    the test file actually lives in, which is what went wrong."""
    mine = Path(__file__).resolve().parents[5]   # …/<root>/vibe-ic-marketplace
    root = C.find_repo_root()                    # /plugins/vibe-ic/programs
    assert root == mine, (root, mine)            # /tests/<this file>
    # …and the trees it then scans are inside it, not an enclosing checkout's.
    for scanned, _glob, _anchor in C._scan_roots(root, None):
        assert str(scanned).startswith(str(mine)), scanned


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
    _stall(tmp_path, 300)
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
    _stall(tmp_path, 300)
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


# ── the population is every tree a pytest lane runs ──────────────────────────

def test_both_pytest_trees_are_scanned():
    """The report named one tree; the workflows run two. A gate that scanned
    only the first would be silent about a lane CI really executes."""
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no .github/workflows in reach")
    roots = C._scan_roots(root, None)
    names = [Path(r).name for r, _g, _a in roots]
    assert "tests" in names and C.TOOLS_DIR_REL in names, roots


def test_the_two_trees_use_different_globs_for_a_measured_reason():
    """`programs/tests` is scanned whole because everything in it exists to be
    run by pytest — which caught a 90 s bound in a non-`test_` helper. `tools`
    mixes production entry points with tests, and a tool's own timeout is
    runtime behaviour, not a bound the harness imposes.

    Asserted by MEASURING the difference the glob makes, not by reading the
    comment that explains it: widening `tools` to `*.py` produces findings, and
    every one of them is in a file pytest never executes as a test."""
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no .github/workflows in reach")
    by_name = {Path(r).name: g for r, g, _a in C._scan_roots(root, None)}
    assert by_name["tests"] == "*.py"
    assert by_name[C.TOOLS_DIR_REL] == C.TOOLS_GLOB

    ceiling = C.inner_timeout_ceiling(root)
    tools = root / C.TOOLS_DIR_REL
    narrow = C.scan_tree(tools, ceiling, C.TOOLS_GLOB, root)
    wide = C.scan_tree(tools, ceiling, "*.py", root)
    assert narrow["findings"] == [], [str(f) for f in narrow["findings"]]
    assert wide["findings"], (
        "widening the glob no longer changes the answer — if `tools` now holds "
        "only tests, scan it whole and delete this distinction")
    for f in wide["findings"]:
        assert not Path(f.path).name.startswith("test_"), str(f)


def test_an_explicit_tests_root_replaces_the_set_and_does_not_add_to_it(
        tmp_path):
    """A caller that narrowed the scan and silently also got the default would
    read the result as covering something it does not."""
    (tmp_path / "only").mkdir()
    roots = C._scan_roots(C.find_repo_root(), str(tmp_path / "only"))
    assert [r for r, _g, _a in roots] == [tmp_path / "only"]


def test_each_root_prints_its_own_file_count(tmp_path):
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no .github/workflows in reach")
    out = tmp_path / "r.json"
    subprocess.run([sys.executable, str(_PROG), str(root), "--json", str(out)],
                   capture_output=True, text=True, timeout=_T)
    doc = json.loads(out.read_text())
    assert len(doc["roots"]) == 2
    assert sum(r["files"] for r in doc["roots"]) == doc["files"]
    assert all(r["files"] > 0 for r in doc["roots"])


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


# ── a bound spelled as a PARAMETER DEFAULT (vibe-ic#1277) ────────────────────

def test_a_bound_that_arrives_as_a_parameter_default_is_resolved():
    """The shape that killed real sessions on main: the bound is neither a
    literal at the call site nor a module constant, so it was DROPPED."""
    findings, unresolved, sites = _scan("""
        import subprocess
        def _r(cmd, timeout=1800):
            return subprocess.run(cmd, timeout=timeout)
    """)
    assert [f.seconds for f in findings] == [1800], (findings, unresolved)
    assert sites == 1, "the site must also be COUNTED, not merely judged"
    assert findings[0].constant == "timeout"
    assert findings[0].owner == "_r"
    assert findings[0].constant_kind == C.VIA_PARAMETER_DEFAULT
    assert "parameter default" in str(findings[0])


def test_the_two_spellings_of_one_bound_produce_the_same_verdict():
    """The falsifiable control from the report, as a pinned test.

    Same 1800 s bound, two spellings. Before #1277 the second produced `0
    readable bound(s)` AND `0 not judged` — a report that tells the reader
    nothing was skipped. Equality here is the property; the numbers are the
    evidence for it.
    """
    literal = _scan("""
        import subprocess
        def test_a():
            subprocess.run(['true'], timeout=1800)
    """)
    param = _scan("""
        import subprocess
        def _r(cmd, timeout=1800):
            return subprocess.run(cmd, timeout=timeout)
        def test_b():
            _r(['true'])
    """)
    assert [f.seconds for f in literal[0]] == [f.seconds for f in param[0]]
    assert literal[2] == param[2] == 1


def test_a_parameter_default_the_body_rebinds_is_not_resolved():
    """`module_constants`'s rule, applied to the same question: a name the body
    can reassign on a branch would have this gate reporting a number the call
    may never receive. Not judged beats judged wrong."""
    findings, unresolved, sites = _scan("""
        import subprocess
        def _r(cmd, timeout=1800):
            timeout = min(timeout, 30)
            return subprocess.run(cmd, timeout=timeout)
    """)
    assert (findings, unresolved, sites) == ([], [], 0)


def test_a_doubles_parameter_default_that_reaches_no_launcher_is_still_safe():
    """The class the report's grep drowned in, restated for #1277: resolving
    defaults must NOT reintroduce it.

    The signature is byte-identical to the one the gate has always ignored;
    what decides is the body, and this body launches nothing. A default that
    reaches no call at all is not a bound and is not even a site.
    """
    findings, unresolved, sites = _scan("""
        def runner(cmd, timeout=3600):
            return 0
        def use():
            return runner(['x'])
    """)
    assert (findings, unresolved, sites) == ([], [], 0)


def test_a_default_forwarded_into_an_UNRESOLVABLE_callee_is_advisory():
    """…and when the default does reach a call whose body this file cannot
    see, the answer is the one the allowlist has always given: advisory, with
    the file and line, rather than a guess in either direction."""
    findings, unresolved, sites = _scan("""
        def other(cmd, timeout=3600):
            return mock_runner(cmd, timeout=timeout)
    """)
    assert findings == []
    assert [u.seconds for u in unresolved] == [3600]
    assert sites == 1, "still COUNTED — an exclusion needs a denominator"


def test_the_innermost_binding_of_the_name_wins():
    """An inner function's own parameter shadows the outer one, so the value
    reported must be the inner one."""
    findings, _u, _n = _scan("""
        import subprocess
        def outer(timeout=1800):
            def inner(timeout=900):
                return subprocess.run(['x'], timeout=timeout)
            return inner
    """)
    assert [f.seconds for f in findings] == [900]
    assert findings[0].owner == "inner"


def test_a_parameter_with_no_default_stays_unresolved():
    findings, unresolved, sites = _scan("""
        import subprocess
        def _r(cmd, timeout):
            return subprocess.run(cmd, timeout=timeout)
    """)
    assert (findings, unresolved, sites) == ([], [], 0)


# ── the bound that will REALLY apply to the call ─────────────────────────────

def test_a_marked_item_is_judged_against_its_own_bound():
    """`@pytest.mark.timeout(N)` IS pytest-timeout's per-item bound, so a call
    inside such a test cannot kill the session at the harness bound. Judging it
    against `harness // 3` reports a risk that provably cannot occur."""
    src = """
        import subprocess, pytest
        @pytest.mark.timeout(600)
        def test_slow():
            subprocess.run(['x'], timeout=200)
    """
    findings, _u, sites = _scan(src)
    assert findings == [] and sites == 1, findings
    over = C.scan_source_report(textwrap.dedent(src).replace("timeout=200",
                                                             "timeout=201"),
                                "f.py", _CEIL)
    assert [f.seconds for f in over["findings"]] == [201], (
        "600 // 3 = 200 must still be a CEILING, not a waiver")


def test_a_marker_below_the_harness_bound_tightens_the_ceiling():
    """It cuts both ways, or it is an escape hatch rather than a model."""
    findings, _u, _n = _scan("""
        import subprocess, pytest
        @pytest.mark.timeout(60)
        def test_quick():
            subprocess.run(['x'], timeout=45)
    """)
    assert [f.seconds for f in findings] == [45], findings


def test_an_unmarked_test_beside_a_marked_one_keeps_the_harness_ceiling():
    """The raised ceiling belongs to the item that declares it and to nothing
    else — otherwise one marker would quietly re-bound a whole file."""
    rep = C.scan_source_report(textwrap.dedent("""
        import subprocess, pytest
        @pytest.mark.timeout(600)
        def test_slow():
            subprocess.run(['x'], timeout=200)
        def test_neighbour():
            subprocess.run(['x'], timeout=200)
    """), "f.py", _CEIL)
    assert [f.line for f in rep["findings"]] == [7], rep["findings"]
    assert [(m.test, m.seconds, m.ceiling) for m in rep["marked_items"]] == [
        ("test_slow", 600, 200)]


def test_a_marker_on_a_helper_does_not_raise_the_callers_item_bound():
    """pytest does not collect the helper, so its decorator governs nothing."""
    rep = C.scan_source_report(textwrap.dedent("""
        import subprocess, pytest
        @pytest.mark.timeout(600)
        def _run():
            subprocess.run(['x'], timeout=200)
        def test_calls_helper():
            _run()
    """), "f.py", _CEIL)
    assert [f.seconds for f in rep["findings"]] == [200], rep
    assert rep["marked_items"] == []


def test_a_marker_on_a_fixture_does_not_raise_the_callers_item_bound():
    """A fixture named like a test is still a fixture, not a collected item."""
    rep = C.scan_source_report(textwrap.dedent("""
        import subprocess, pytest
        @pytest.fixture
        @pytest.mark.timeout(600)
        def test_environment():
            subprocess.run(['x'], timeout=200)
        def test_uses_environment(test_environment):
            pass
    """), "f.py", _CEIL)
    assert [f.seconds for f in rep["findings"]] == [200], rep
    assert rep["marked_items"] == []


def test_a_module_level_pytestmark_bounds_every_call_in_the_file():
    """The case a per-test decorator cannot reach: the launcher call lives in a
    module-level helper every test in the file shares, so no decorator governs
    it. `pytestmark` bounds every ITEM in the module, so it does."""
    rep = C.scan_source_report(textwrap.dedent("""
        import subprocess, pytest
        pytestmark = pytest.mark.timeout(600)
        def _run(args, timeout=150):
            return subprocess.run(args, timeout=timeout)
        def test_a():
            return _run(['x'])
    """), "f.py", _CEIL)
    assert rep["findings"] == [], rep["findings"]
    assert rep["sites"] == 1
    assert [(m.seconds, m.ceiling) for m in rep["marked_items"]] == [(600, 200)]
    # …and it is still a CEILING: 201 is over 600 // 3.
    over = C.scan_source_report(textwrap.dedent("""
        import subprocess, pytest
        pytestmark = pytest.mark.timeout(600)
        def _run(args, timeout=201):
            return subprocess.run(args, timeout=timeout)
    """), "f.py", _CEIL)
    assert [f.seconds for f in over["findings"]] == [201]


def test_a_pytestmark_list_is_read_and_the_smallest_timeout_wins():
    """`pytestmark` is usually a list. A ceiling argued from the widest of
    several declarations would be the one number here nobody could check."""
    rep = C.scan_source_report(textwrap.dedent("""
        import subprocess, pytest
        pytestmark = [pytest.mark.usefixtures('x'),
                      pytest.mark.timeout(600),
                      pytest.mark.timeout(300)]
        def test_a():
            subprocess.run(['x'], timeout=150)
    """), "f.py", _CEIL)
    assert [(m.seconds, m.ceiling) for m in rep["marked_items"]] == [(300, 100)]
    assert [f.seconds for f in rep["findings"]] == [150], rep["findings"]


def test_the_marked_population_is_printed_with_its_value(tmp_path):
    """Raising a ceiling must be a visible act, for the reason the advisory
    list is printed: an exclusion a reader cannot see reads as a clean run."""
    _workflow(tmp_path, "pytest --timeout=180")
    _stall(tmp_path, 900)
    tests = tmp_path / "t"
    tests.mkdir()
    (tests / "test_x.py").write_text(
        "import subprocess, pytest\n"
        "@pytest.mark.timeout(600)\n"
        "def test_slow():\n"
        "    subprocess.run(['x'], timeout=200)\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_PROG), str(tmp_path), "--tests-root",
         str(tests)], capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "@pytest.mark.timeout(600)" in proc.stdout
    assert "judged against 200s" in proc.stdout


def test_the_ceiling_itself_is_allowed_and_one_second_over_is_not():
    at, _u, _n = _scan(f"import subprocess\n"
                       f"subprocess.run(['x'], timeout={_CEIL})\n")
    over, _u2, _n2 = _scan(f"import subprocess\n"
                           f"subprocess.run(['x'], timeout={_CEIL + 1})\n")
    assert at == []
    assert [f.seconds for f in over] == [_CEIL + 1]


# ── falsifiability against the real tree ─────────────────────────────────────

def test_the_shipped_tree_is_clean(tmp_path):
    """Half one of falsifiability, and the ratchet: the shipped program over
    the shipped roots, READ-ONLY."""
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no .github/workflows in reach")
    proc = subprocess.run([sys.executable, str(_PROG), str(root)],
                          capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
    assert "[PASS]" in proc.stdout


def test_an_injected_offender_makes_the_shipped_program_fail(tmp_path):
    """Half two: a gate that has never failed has not been shown to work.

    The offender goes into a THROWAWAY scan root, never into the shipped tree.
    Writing it into `programs/tests` would be a defect of its own: this repo is
    worked by several agents at once, so for the length of the run every other
    session's gate would see a FAIL that is not theirs, and two copies of this
    test would delete each other's file. `--tests-root` gives the same
    demonstration — the same shipped program, the same resolver reading the
    same real workflows — with nothing shared to corrupt.
    """
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no .github/workflows in reach")
    victim = tmp_path / "test_injected_offender.py"
    victim.write_text("import subprocess\n"
                      "subprocess.run(['true'], timeout=900)\n",
                      encoding="utf-8")
    red = subprocess.run(
        [sys.executable, str(_PROG), str(root), "--tests-root", str(tmp_path)],
        capture_output=True, text=True, timeout=_T)
    assert red.returncode == 1, red.stdout[-4000:]
    assert victim.name in red.stdout and "timeout=900" in red.stdout
    assert "[FAIL]" in red.stdout

    victim.unlink()
    green = subprocess.run(
        [sys.executable, str(_PROG), str(root), "--tests-root", str(tmp_path)],
        capture_output=True, text=True, timeout=_T)
    assert green.returncode == 0, green.stdout[-4000:]


def test_an_injected_offender_SPELLED_AS_A_PARAMETER_also_fails(tmp_path):
    """The same falsifiability, through the shipped program, for #1277's shape.

    The unit tests above prove the resolver; this proves the GATE — same
    binary, same resolver reading the same real workflows — because the defect
    #1277 reports is not that the value was mis-parsed, it is that the whole
    call left the report. Both arms carry the identical 900 s bound, so a
    difference between them can only be the spelling.
    """
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no .github/workflows in reach")

    def _rc(body: str):
        victim = tmp_path / "test_injected_param_offender.py"
        victim.write_text(body, encoding="utf-8")
        p = subprocess.run(
            [sys.executable, str(_PROG), str(root), "--tests-root",
             str(tmp_path)], capture_output=True, text=True, timeout=_T)
        victim.unlink()
        return p

    red = _rc("import subprocess\n"
              "def _r(cmd, timeout=900):\n"
              "    return subprocess.run(cmd, timeout=timeout)\n")
    assert red.returncode == 1, red.stdout[-4000:]
    assert "[FAIL]" in red.stdout and "timeout=900" in red.stdout
    assert "1 readable bound(s)" in red.stdout, (
        "the site must enter the DENOMINATOR too — being uncounted is the "
        f"half of #1277 that tells a reader nothing was skipped:\n{red.stdout}")

    # …and the gate goes green again once the bound fits, so the red above is
    # the bound and not the fixture.
    green = _rc("import subprocess\n"
                "def _r(cmd, timeout=30):\n"
                "    return subprocess.run(cmd, timeout=timeout)\n")
    assert green.returncode == 0, green.stdout[-4000:]


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
    if doc.get("mode") == "semantic_progress":
        assert doc["harness_seconds"] is None
        assert doc["ceiling_seconds"] is None
        assert len(doc["semantic_lanes"]) >= 3
    else:
        assert doc["ceiling_seconds"] == \
            doc["harness_seconds"] // doc["ceiling_divisor"]
    assert doc["files"] > 0 and doc["bounded_sites"] > 0
    if doc.get("mode") != "semantic_progress":
        assert len(doc["harness_bounds"]) >= 2


#: The advisory residual on the shipped tree: ZERO, and the number is no longer
#: a baseline anybody has to maintain.
#:
#: THE RESIDUAL WAS A DRIFTING COUNT AND THAT IS WHY IT WENT RED. It landed at
#: 10 with a prose note explaining each entry, and it was 11 before this change
#: — the eleventh (`S._bounded_vvp(timeout=120)`) arrived with a test that had
#: no reason to know a count in a different file governed it. A count baseline
#: cannot say WHICH entry is new, so the only way to answer that question was to
#: re-read all of them; and "raise it to 11" is available at every step and
#: never fails loudly. That is the shape #527/#530/#534 each spent a version
#: removing from a waiver registry, reintroduced as a single integer.
#:
#: So the eleven were read and every one was LOWERED to the ceiling instead,
#: measured rather than argued: at each of those call sites the callee is
#: monkeypatched (`R._run`, `dosr._run`/`_docker_exec`, `lec_run._docker`,
#: `S.subprocess.run`) or builds a STRING and launches nothing
#: (`tdf._build_batch_script`), so the worst case is microseconds and 60 s is
#: not a constraint on any of them. Nothing was suppressed and no exemption
#: survives: the population is unchanged and the numerator is empty.
#:
#: At zero the assertion below is also the strongest it can be. A NEW
#: unresolvable bound above the ceiling turns it red with the file, line and
#: callee named — which is the report the count could never produce.
#:
#: ── AND THEN ONE ENTRY WOULD NOT LOWER (vibe-ic#1022) ────────────────────────
#: The count above went red at 2, and re-reading both showed they are not the
#: same kind of entry. One was the eleven's kind and was LOWERED
#: (`test_matrix_artefact_mutation_channel.py`, worst single replay MEASURED at
#: 1.55 s under a 900 s bound — 60 s constrains nothing). The other is the first
#: entry in this corpus where the bound is REAL and the ceiling is genuinely too
#: low for it: `test_matrix_mutation_ledger.py::REPLAY_TIMEOUT` reaches one
#: `subprocess.run` per pytest cell whose worst case MEASURED over the full
#: 24-pair witness plan is 42.61 s at `jobs=8` / 26.8 s uncontended, so 60 s is
#: 1.41x the contended worst case and would fire on work that passes today.
#:
#: THE FIX FOR THE COUNT IS NOT A BIGGER COUNT — it is to stop being a count.
#: Everything the note above says against `10 -> 11` is true of `0 -> 1`: it is
#: available at every step, it never fails loudly, and it cannot say WHICH entry
#: is new. A NAMED set says all three. It keeps the property that made zero
#: strong (anything unrecorded fails, by name), and it adds the one zero could
#: not have: the recorded entry carries its measurement and its reason, so the
#: next reader inherits the evidence instead of an integer.
#:
#: The entry below is recorded, NOT waived. It is reachable in the 180 s lane
#: (verified: `ci_targeted_test_select.py --base HEAD` emits 15 files at the
#: smoke floor and 17 once `programs/matrix_mutation_ledger.py` is touched, the
#: two extra being this entry's file and the artefact channel's). Its correct
#: remedy is the checker's SECOND one — move the two replay-driven tests out of
#: the 180 s lane — which needs a lane that does not exist in this tree yet.
#: When it does, delete this entry and the set is empty again.
#: ── AND THE ENTRY HAD TO CARRY WHAT THE EXPIRY COSTS (vibe-ic#1654) ─────────
#: The recording below was honest and its measurement is sound, and it was still
#: only half the fact. It reasons about the call's DURATION — how long the bound
#: permits — and a reader of it learns "this test is slow". What it did not say
#: is what happens to the EVIDENCE when the bound is reached, and those are
#: different properties.
#:
#: MEASURED at 1adbf3444 with three files, one of them hanging in this entry's
#: exact shape (`Future.result` -> `Condition.wait` -> `waiter.acquire`):
#: `--timeout-method=thread` cannot interrupt a blocking `waiter.acquire()`, so
#: pytest-timeout dumps the stacks and takes the PROCESS down, and a process
#: that dies never writes its `--junitxml`. The green file that had already
#: PASSED lost its record with it, and `ls` on the junit target reported
#: `No such file or directory`. In the 91-file selection that opened #1654 the
#: blast radius was the other 90 files, on BOTH arms — which is the permissive
#: direction, because the merge gate's failed-set differential reads both arms
#: from junit and an absent record must never be read as a clean one.
#:
#: So the consequence is recorded HERE, beside the duration, and the fix is not
#: a re-bound: `programs/pytest_per_file_junit.py` gives each selected file its
#: own session and its own report, so this entry's expiry now costs THIS file's
#: record and names it (`NORECORD`) instead of the run's. The relocation the
#: entry asks for is still the right remedy for the DURATION half and is still
#: owed.
_REVIEWED_ADVISORY_RESIDUAL = {
    ("programs/tests/test_matrix_mutation_ledger.py", "L.replay_many"): (
        "REPLAY_TIMEOUT=900 bounds one `_run_cell` pytest-cell subprocess. "
        "MEASURED 24-pair witness plan, 32 cores, instrumented at `_run_cell`: "
        "32 invocations, worst single call 42.61 s at jobs=8 / 26.8 s "
        "uncontended (dimension-7 cell). 60 s is 1.41x that and would fire on "
        "passing work. Needs relocation out of the 180 s lane, not a re-bound. "
        "RECORD-LOSS CONSEQUENCE (vibe-ic#1654): when this bound is reached the "
        "180 s harness has already killed the SESSION, and a killed session "
        "writes no junit — so the expiry used to cost the whole run's "
        "machine-readable record, not just this file's result (measured: 1 "
        "hanging file of 91 selected, both arms, neither junit written). "
        "`programs/pytest_per_file_junit.py` now confines that loss to this "
        "file and NAMES it; the relocation is still owed for the duration."
    ),
}


def test_the_advisory_residual_does_not_grow_unreviewed(tmp_path):
    """An allowlist earns its exclusions by having them read.

    The failure message NAMES each entry, because the one question a reader has
    — which one is new — is the one a bare count cannot answer.
    """
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no repo root in reach")
    out = tmp_path / "r.json"
    subprocess.run([sys.executable, str(_PROG), str(root), "--json", str(out)],
                   capture_output=True, text=True, timeout=_T)
    doc = json.loads(out.read_text())
    unresolved = doc["unresolved_above_ceiling"]
    if doc.get("mode") == "semantic_progress":
        assert unresolved == []
        return
    unrecorded = [u for u in unresolved
                  if (u["path"], u["callee"]) not in _REVIEWED_ADVISORY_RESIDUAL]
    assert not unrecorded, (
        f"{len(unrecorded)} unresolvable bound(s) above the ceiling that nobody "
        "has read — lower them, or record each one BY NAME in "
        "_REVIEWED_ADVISORY_RESIDUAL with the measurement that says it cannot "
        "be lowered:\n  "
        + "\n  ".join(f"{u['path']}:{u['line']} {u['callee']}"
                      f"({u['keyword']}={u['seconds']})"
                      for u in unrecorded))


def test_a_recorded_advisory_that_stopped_existing_is_deleted(tmp_path):
    """The other direction, which is how a named set avoids the count's fate.

    A count only ever grows: nothing forces `11` back down to `10` when an entry
    is lowered, so the baseline outlives the thing it described and quietly
    permits a NEW entry in the retired one's slot. A named set cannot do that —
    a recording whose call site is gone is itself the failure, and the fix is to
    delete the line rather than to notice it.
    """
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no repo root in reach")
    out = tmp_path / "r.json"
    subprocess.run([sys.executable, str(_PROG), str(root), "--json", str(out)],
                   capture_output=True, text=True, timeout=_T)
    doc = json.loads(out.read_text())
    if doc.get("mode") == "semantic_progress":
        assert doc["unresolved_above_ceiling"] == []
        return
    live = {(u["path"], u["callee"])
            for u in doc["unresolved_above_ceiling"]}
    stale = sorted(k for k in _REVIEWED_ADVISORY_RESIDUAL if k not in live)
    assert not stale, (
        "recorded advisory entries the checker no longer reports — the bound "
        "was lowered or the call site moved, so delete the recording instead of "
        "leaving a slot a future entry can land in unread:\n  "
        + "\n  ".join(f"{p} {c}" for p, c in stale))


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


# ── the marker is a DIAL, so it is capped (vibe-ic#1734) ─────────────────────
#
# One case per DOOR, not per number. The withheld v1.10.62 fix closed `0` and left
# `2700`, and its own self-check advertised coverage of `timeout(0)` BY NAME while
# a 900 s bound walked through the positive-marker door. Each test below is a door.

def test_a_marker_cannot_raise_the_ceiling_past_the_driver_stall_window(tmp_path):
    """THE DIAL. `timeout(2700)` used to buy a 900 s ceiling.

    A marker is written by the same contributor whose inner bound is being
    judged, so on its own it is not a constraint. The driver's stall window is
    the bound they cannot also supply: it is how long the per-file driver
    tolerates NO validated pytest lifecycle event before calling the session
    hung, and a blocking call emits none.
    """
    _workflow(tmp_path, "pytest --timeout=180")
    _stall(tmp_path, 300)
    tests = tmp_path / "t"
    tests.mkdir()
    (tests / "test_x.py").write_text(
        "import subprocess, pytest\n"
        "pytestmark = pytest.mark.timeout(2700)\n"
        "def test_slow():\n"
        "    subprocess.run(['x'], timeout=900)\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_PROG), str(tmp_path), "--tests-root", str(tests)],
        capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 1, (
        "a 900 s bound under a 2700 s marker was accepted -- the marker is being "
        "used as a ceiling a contributor can set for themselves.\n" + proc.stdout)
    assert "timeout=900" in proc.stdout
    assert "judged against 100s" in proc.stdout, proc.stdout


def test_a_zero_marker_is_no_item_bound_not_a_bound_of_zero(tmp_path):
    """THE OTHER DOOR, and it must not become an exemption.

    pytest-timeout treats 0 as DISABLED. Reading it as a bound of zero gives a
    ceiling of `0 // 3 == 0`, which makes EVERY inner timeout in the file a
    violation -- that is what reported `test_matrix_63x8_coverage.py:305
    subprocess.run(timeout=60)` as a session risk and blocked landing on main.
    Reading it as "unbounded" is the opposite error and installs a one-line
    silencer. It is neither: with no item clock the stall window is what ends the
    call, so that is what the call is judged against.
    """
    _workflow(tmp_path, "pytest --timeout=180")
    _stall(tmp_path, 300)
    tests = tmp_path / "t"
    tests.mkdir()
    (tests / "test_x.py").write_text(
        "import subprocess, pytest\n"
        "pytestmark = pytest.mark.timeout(0)\n"
        "def test_ok():\n"
        "    subprocess.run(['x'], timeout=60)\n"
        "def test_too_slow():\n"
        "    subprocess.run(['y'], timeout=150)\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_PROG), str(tmp_path), "--tests-root", str(tests)],
        capture_output=True, text=True, timeout=_T)
    # 60 is fine under 300 // 3; 150 is not. Both halves matter: the first says
    # zero is not a silencer's opposite, the second says it is not a silencer.
    assert proc.returncode == 1, proc.stdout
    assert "timeout=150" in proc.stdout, proc.stdout
    assert "timeout=60" not in proc.stdout.split("[FAIL]")[-1], (
        "a 60 s bound was reported under a disabled item clock whose stall "
        "window is 300 s\n" + proc.stdout)


def test_an_unreadable_stall_window_refuses_rather_than_passes(tmp_path):
    """No cap read means a marked item cannot be judged. That is rc 2.

    Falling back to the harness bound was tried and is wrong in its own way: the
    marker exists to REPLACE the harness item bound, so capping at it makes every
    marker inert and turns "this test genuinely needs longer" into a finding.
    """
    _workflow(tmp_path, "pytest --timeout=180")          # deliberately no _stall
    tests = tmp_path / "t"
    tests.mkdir()
    (tests / "test_x.py").write_text(
        "import subprocess\n"
        "def test_ok():\n"
        "    subprocess.run(['x'], timeout=10)\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_PROG), str(tmp_path), "--tests-root", str(tests)],
        capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 2, proc.stdout
    assert "CANNOT DETERMINE" in proc.stdout
    assert "NOT a pass" in proc.stdout


def test_the_pass_sentence_does_not_outrun_what_was_checked(tmp_path):
    """vibe-ic#1734 defect 2: the verdict became literally false.

    `every resolvable blocking call is bounded at or under 60s` was safe while the
    only exclusions were UNRESOLVABLE callees -- which is why the word "resolvable"
    is in it. Once a marked item is judged against a larger ceiling, a run can
    print that sentence two lines under its own counterexample.
    """
    _workflow(tmp_path, "pytest --timeout=180")
    _stall(tmp_path, 300)
    tests = tmp_path / "t"
    tests.mkdir()
    (tests / "test_x.py").write_text(
        "import subprocess, pytest\n"
        "pytestmark = pytest.mark.timeout(300)\n"
        "def test_ok():\n"
        "    subprocess.run(['x'], timeout=90)\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_PROG), str(tmp_path), "--tests-root", str(tests)],
        capture_output=True, text=True, timeout=_T)
    assert proc.returncode == 0, proc.stdout
    # 90 > the default 60 s ceiling and is still a PASS, so the sentence may not
    # claim everything is under 60 s.
    assert "judged against 100s" in proc.stdout, proc.stdout
    assert "bounded at or under 60s" not in proc.stdout, (
        "the PASS sentence claims a bound this very run printed a "
        "counterexample to\n" + proc.stdout)
    assert "300s driver stall window" in proc.stdout, proc.stdout
