"""Unit tests for retired_pytest_plugin_request_check.py.

THE MEASUREMENT THIS GATE WAS BUILT FROM, 2026-08-20 at `9cc09b863` (v1.11.5):
the same 90 cases, from the same tree, in two lanes --

    image ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2...d01ff   90 cases  30 red
    host                                                      90 cases   3 red
    per-test set difference: 28 image-only reds, every one of them caused by
    a `-p <retired plugin>` request the anchored runtime cannot satisfy.

The doctrine was already settled and already written down FIVE times -- but each
of the five was scoped to one named file, and a file-by-file rule cannot see the
sixth file. Four live requests survived in files nobody had pinned. This gate is
the tree-wide form, and these tests pin BOTH directions of it: what it must
catch, and -- at least as important, because the tree is full of prose about the
retirement -- what it must NOT call a hit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import retired_pytest_plugin_request_check as R                  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROG = PROGRAMS / "retired_pytest_plugin_request_check.py"
_NAME = "pytest" + "_timeout"     # never a literal here; see the module doc


def _tree(tmp_path: Path, files: dict, name: str = "tree") -> Path:
    root = tmp_path / name
    root.mkdir(exist_ok=True)
    for name, body in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


def _run(root: Path, *extra):
    return _pr.run([sys.executable, str(_PROG), str(root), *extra],
                          capture_output=True, text=True)


# ── what it MUST catch ───────────────────────────────────────────────────────

def test_a_plugin_request_in_a_python_argv_literal_is_a_hit(tmp_path):
    root = _tree(tmp_path, {"mod.py":
        'import sys, subprocess\n'
        'subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", '
        f'"{_NAME}", "x.py"])\n'})
    p = _run(root)
    assert p.returncode == R.RC_FAIL, p.stdout + p.stderr
    assert "mod.py:2" in p.stdout, p.stdout
    assert _NAME in p.stdout, p.stdout
    # the remedy travels with the refusal
    assert "use instead:" in p.stdout, p.stdout


def test_an_fstring_timeout_option_in_a_pytest_argv_is_a_hit(tmp_path):
    """THE REAL SHAPE. `programs/tests/test_pytest_per_file_junit.py:390` wrote
    the option as `f"--timeout={_INNER_TIMEOUT}"`, which is a `JoinedStr` and
    not a `Constant` — a scanner that only reads plain constants walks straight
    past it."""
    root = _tree(tmp_path, {"mod.py":
        'import sys\nN = 4\n'
        'CMD = [sys.executable, "-m", "pytest", f"--timeout={N}",\n'
        '       "--timeout-method=thread"]\n'})
    p = _run(root)
    assert p.returncode == R.RC_FAIL, p.stdout + p.stderr
    assert "--timeout=" in p.stdout, p.stdout
    assert "--timeout-method" in p.stdout, p.stdout


def test_a_shell_line_that_requests_the_plugin_is_a_hit(tmp_path):
    root = _tree(tmp_path, {"g.sh":
        "#!/usr/bin/env bash\n"
        f"python3 -m pytest -q -p {_NAME} --timeout=180 t.py\n"})
    p = _run(root)
    assert p.returncode == R.RC_FAIL, p.stdout + p.stderr
    assert "g.sh:2" in p.stdout, p.stdout


# ── what it MUST NOT call a hit (the tree is full of all four shapes) ────────

def test_prose_in_a_comment_or_docstring_is_not_a_request(tmp_path):
    root = _tree(tmp_path, {"mod.py":
        f'"""Why `-p {_NAME}` was retired: it is a hard import."""\n'
        f'# do not reintroduce `-p {_NAME} --timeout=180`\n'
        'VALUE = 1\n'})
    p = _run(root)
    assert p.returncode == R.RC_PASS, p.stdout + p.stderr


def test_an_assertion_forbidding_the_idiom_is_not_a_request(tmp_path):
    """`assert "-p <name>" not in body` is ONE string constant, never a
    two-element sequence. Four live tests in this repo are written that way and
    a gate that flagged them would be unlandable."""
    root = _tree(tmp_path, {"t.py":
        'def test_it(body="x"):\n'
        f'    assert "-p {_NAME}" not in body\n'
        f'    assert "{_NAME}" not in body\n'})
    p = _run(root)
    assert p.returncode == R.RC_PASS, p.stdout + p.stderr


def test_a_timeout_marker_is_not_a_plugin_request(tmp_path):
    root = _tree(tmp_path, {"t.py":
        'import pytest\n'
        '@pytest.mark.timeout(30)\n'
        'def test_slow():\n    assert True\n'})
    p = _run(root)
    assert p.returncode == R.RC_PASS, p.stdout + p.stderr


def test_a_timeout_option_outside_a_pytest_argv_is_not_a_request(tmp_path):
    """`--timeout=` is an ordinary option for other tools in this tree."""
    root = _tree(tmp_path, {"mod.py":
        'CMD = ["docker", "run", "--timeout=30", "img"]\n'
        'CURL = ["curl", "--timeout-method=thread", "http://x"]\n'})
    p = _run(root)
    assert p.returncode == R.RC_PASS, p.stdout + p.stderr


def test_a_shell_comment_is_not_a_request(tmp_path):
    root = _tree(tmp_path, {"g.sh":
        "#!/usr/bin/env bash\n"
        f"# the `-p {_NAME} --timeout=180` session bound this line used to\n"
        "# carry is gone.\n"
        "python3 -m pytest -q t.py\n"})
    p = _run(root)
    assert p.returncode == R.RC_PASS, p.stdout + p.stderr


# ── "I could not look" is never "I looked and it was clean" ─────────────────

def test_an_unparseable_python_file_is_REFUSED_not_passed(tmp_path):
    root = _tree(tmp_path, {"broken.py": "def (((\n"})
    p = _run(root)
    assert p.returncode == R.RC_REFUSED, p.stdout + p.stderr
    assert "REFUSED" in p.stdout, p.stdout
    assert "broken.py" in p.stdout, p.stdout
    assert "PASS —" not in p.stdout, p.stdout


def test_an_undecodable_file_is_REFUSED_not_passed(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "bad.py").write_bytes(b"\xff\xfe\x00 not utf-8 \xc3\x28\n")
    p = _run(root)
    assert p.returncode == R.RC_REFUSED, p.stdout + p.stderr
    assert "cannot read" in p.stdout, p.stdout


def test_a_tree_with_nothing_to_examine_is_VACUOUS_not_PASS(tmp_path):
    """A mis-rooted invocation must go RED under `repo_hygiene_gates.sh`, whose
    `run` helper fails the suite on any non-zero rc."""
    root = tmp_path / "empty"
    root.mkdir()
    p = _run(root)
    assert p.returncode == R.RC_REFUSED, p.stdout + p.stderr
    assert "VACUOUS_PASS" in p.stdout, p.stdout
    assert "VACUOUS_PASS" in p.stderr, p.stderr


def test_a_real_hit_outranks_a_refusal_in_the_listing(tmp_path):
    """Both must be NAMED; the rc says the run could not be trusted either way."""
    root = _tree(tmp_path, {
        "broken.py": "def (((\n",
        "mod.py": 'import sys\nCMD = [sys.executable, "-m", "pytest", "-p", '
                  f'"{_NAME}"]\n'})
    p = _run(root)
    assert p.returncode == R.RC_REFUSED, p.stdout + p.stderr
    assert "broken.py" in p.stdout and "mod.py" in p.stdout, p.stdout


# ── the verdict must not move with the host ─────────────────────────────────

def test_probe_is_diagnostic_and_never_changes_the_verdict(tmp_path):
    """THE WHOLE REASON THE DRIFT SURVIVED: every developer host carried an
    ambient `pip install` of the plugin, so every developer lane was green. A
    gate whose answer moves with the host is the defect, not the fix."""
    root = _tree(tmp_path, {"mod.py":
        'import sys\nCMD = [sys.executable, "-m", "pytest", "-p", '
        f'"{_NAME}"]\n'})
    plain = _run(root)
    probed = _run(root, "--probe")
    assert plain.returncode == probed.returncode == R.RC_FAIL
    assert "[probe] this interpreter" in probed.stdout, probed.stdout
    assert "diagnostic only" in probed.stdout, probed.stdout
    # and on a clean tree the probe likewise decides nothing
    clean = _tree(tmp_path, {"ok.py": "VALUE = 1\n"}, name="clean")
    assert _run(clean).returncode == _run(clean, "--probe").returncode == R.RC_PASS


def test_the_enumeration_method_is_named_in_every_verdict(tmp_path):
    """A `git ls-files` sweep and a disk walk can disagree; a reader who cannot
    see which one ran cannot tell a shrinking denominator from a clean tree."""
    root = _tree(tmp_path, {"ok.py": "VALUE = 1\n"})
    p = _run(root)
    assert "[disk-walk]" in p.stdout, p.stdout
    assert "examined 1 " in p.stdout, p.stdout


# ── the live regression pin ─────────────────────────────────────────────────

def test_this_repository_requests_no_retired_pytest_plugin():
    """The pin itself. If this goes red, some file has re-entered the tree
    asking the anchored runtime for a plugin it does not carry — which arrives
    as red cells on the landing gate that say nothing about the code."""
    root = PROGRAMS.parents[3]
    if not (root / ".git").exists():
        pytest.skip("not a repository checkout")
    hits, refusals, stats = R.scan(root)
    assert refusals == [], refusals
    assert stats["examined"] > 0, stats
    assert hits == [], hits
