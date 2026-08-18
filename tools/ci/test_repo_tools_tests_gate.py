"""The landing gate must actually RUN the repo-level tests under `tools/`.

The targeted selector is plugin-scoped by construction (`_SOURCE_DIRS`,
`_TESTS_REL`) and `gatekeeper-land.sh` invokes it with cwd=$PLUGIN, so nothing
under `tools/` can ever reach a selection. Measured on a38902d16: 28 files /
552 tests gating nothing.

This file lives under `tools/` on purpose — it is covered by the very gate it
tests, so if that gate is ever removed, this test stops being run BY it and
starts failing IN it.

The assertions here EXECUTE the gate function against real corpora rather than
grepping the script for reassuring words. A text match proves the script says
"find"; it does not prove the gate goes red when a repo test fails, which is
the only claim worth making.
"""
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_LAND = _ROOT / "tools" / "gatekeeper-land.sh"
_FN = "run_repo_tools_pytest"


def _extract_fn(name):
    """Pull `name() { ... }` out of the script, brace-matched at column 0."""
    src = _LAND.read_text().splitlines()
    start = next(i for i, l in enumerate(src) if l.startswith(f"{name}() {{"))
    end = next(i for i in range(start + 1, len(src)) if src[i] == "}")
    return "\n".join(src[start:end + 1])


def _run_fn_against(tmp_path, test_body, name="test_probe.py", *,
                    extra_files=None):
    """Execute the extracted gate function with ROOT=<a throwaway git repo>.

    Returns (FAILED, combined_output).
    """
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    # The throwaway repo must ignore bytecode the way the real one does
    # (`.gitignore:2` is `__pycache__/`). Without it, pytest's own bytecode
    # lands as UNTRACKED rather than IGNORED, and `suite_write_guard` blocks on
    # it — correctly. An unfaithful fixture reads exactly like a bug in the
    # thing under test: the first version of this file had me most of the way
    # to filing one against the write guard.
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    if test_body is not None:
        (root / "tools" / name).write_text(textwrap.dedent(test_body))
    for extra_name, extra_body in (extra_files or {}).items():
        (root / "tools" / extra_name).write_text(
            textwrap.dedent(extra_body), encoding="utf-8")
    # commit so `git status --porcelain` starts clean
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-qm", "seed", "--allow-empty"],
                   cwd=root, check=True)

    script = (
        "set -uo pipefail\n"
        f'ROOT="{root}"\n'
        f'PROGRAMS="{_ROOT}/vibe-ic-marketplace/plugins/vibe-ic/programs"\n'
        "FAILED=0\n"
        + _extract_fn(_FN) + "\n"
        + f"{_FN}\n"
        'echo "FAILED=$FAILED"\n'
    )
    env = dict(os.environ)
    env.pop("PYTEST_CURRENT_TEST", None)
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       cwd=root, env=env)
    out = p.stdout + p.stderr
    m = re.search(r"FAILED=(\d+)\s*$", out.strip())
    assert m, f"function did not report FAILED=\n{out}"
    return int(m.group(1)), out


# ── WIRING ────────────────────────────────────────────────────────────────

def test_the_gate_function_exists_and_is_called():
    """A function nobody calls is a comment with syntax."""
    src = _LAND.read_text()
    assert f"{_FN}() {{" in src, f"{_FN} is not defined in gatekeeper-land.sh"
    # a bare call at column 0, not merely the definition
    assert re.search(rf"^{_FN}$", src, re.M), (
        f"{_FN} is defined but never invoked — the repo tests would still "
        f"gate nothing")


def test_the_gate_runs_before_the_verdict_is_read():
    """It must sit inside the gate body, above the FAILED verdict."""
    src = _LAND.read_text().splitlines()
    call = next(i for i, l in enumerate(src) if l == _FN)
    verdict = [i for i, l in enumerate(src) if re.search(r"exit .*FAILED|"
                                                         r"if .*FAILED", l)]
    assert verdict, "no FAILED verdict found to order against"
    assert call < max(verdict), (
        "the repo-tools gate runs after the verdict is decided")


# ── BEHAVIOUR: the three states ───────────────────────────────────────────

def test_a_passing_repo_test_is_a_pass(tmp_path):
    failed, out = _run_fn_against(tmp_path, "def test_ok():\n    assert True\n")
    assert failed == 0, out
    assert "PASS  repo tools tests" in out, out


def test_a_FAILING_repo_test_turns_the_gate_red(tmp_path):
    """The load-bearing assertion. If this passes green, the gate is decorative.

    Everything else in this file could hold while the gate silently swallowed
    a red — this is the one that proves it does not.
    """
    failed, out = _run_fn_against(tmp_path,
                                  "def test_bad():\n    assert False\n")
    assert failed == 1, f"a FAILING repo test did not fail the gate:\n{out}"
    assert "FAIL  repo tools tests" in out, out


def test_a_selected_empty_test_file_cannot_shrink_the_repo_tools_denominator(
        tmp_path):
    failed, out = _run_fn_against(
        tmp_path, "def test_ok():\n    assert True\n",
        extra_files={"test_empty_selected.py":
                     "# selected by discovery but has no pytest item\n"})
    assert failed == 1, (
        "a selected file disappeared from aggregate JUnit and landed green:\n"
        + out)
    assert "FAIL  repo tools tests" in out, out


def test_an_empty_corpus_is_refused_rather_than_reported_as_a_pass(tmp_path):
    """Zero discovered files must be FAIL, not a silent green.

    A gate that reports success over an empty population is indistinguishable
    from one that works, and is worse than none: it occupies the slot.
    """
    failed, out = _run_fn_against(tmp_path, None)
    assert failed == 1, f"an empty corpus reported success:\n{out}"
    assert "empty corpus" in out or "matched NO files" in out, out


def test_a_repo_test_that_writes_to_the_tree_turns_the_gate_red(tmp_path):
    """The plugin's in-process write guard is not loaded here, so the property
    it asserts is asserted from outside — and must actually bite."""
    failed, out = _run_fn_against(tmp_path, """
        import pathlib
        def test_writes():
            pathlib.Path("tools/scribble.txt").write_text("x")
        """)
    assert failed == 1, f"a tree-writing repo test did not fail the gate:\n{out}"
    assert "wrote to the tree" in out, out


# ── DISCOVERY, not a roster ───────────────────────────────────────────────

def test_a_newly_added_repo_test_is_picked_up_without_editing_the_gate(tmp_path):
    """Discovery, never a list: the defect being avoided is the recorded
    register that goes stale silently and in the safe-looking direction."""
    failed, out = _run_fn_against(
        tmp_path, "def test_bad():\n    assert False\n",
        name="test_brand_new_never_registered_anywhere.py")
    assert failed == 1, (
        "a repo test that no roster mentions was not discovered — the gate is "
        f"list-driven, not discovery-driven:\n{out}")


def test_the_gate_names_its_denominator(tmp_path):
    """A gate that will not say how many things it checked cannot be audited."""
    failed, out = _run_fn_against(tmp_path, "def test_ok():\n    assert True\n")
    assert failed == 0, out
    assert re.search(r"repo tools tests \(\d+ file\(s\)\)", out), (
        f"the gate did not report its file count:\n{out}")


def test_pytest_is_progress_supervised_without_an_elapsed_verdict():
    """Autoload pinning and semantic supervision apply to this lane too.

    A fixed pytest timeout kills the session and loses its JUnit; it must never
    be reintroduced as a quick substitute for the driver's lifecycle record.
    """
    body = _extract_fn(_FN)
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in body
    assert "pytest_per_file_junit.py" in body
    assert "--aggregate-check" in body
    assert "-p pytest_timeout" not in body
    assert "--timeout" not in body


def test_discovery_is_not_hardcoded():
    body = _extract_fn(_FN)
    assert "find tools" in body, "discovery must be a find over tools/"
    assert not re.search(r"tools/test_\w+\.py", body), (
        "a literal test path appears in the gate — that is a roster")
