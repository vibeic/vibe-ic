"""The consistency tier: bookkeeping tests are deselected unless asked for.

Owner ruling 2026-09-26: tests whose subject is that INFORMATION matches the
code (stated counts, inventories, registers, order, README/website figures) run
only at the x.y.0 FULL cadence or on the owner's request. `consistency_tier.py`
deselects them otherwise; `tools/gatekeeper-land.sh` exports the variable at
FULL. Every behaviour below is driven through a real pytest session, the real
landing script text, or the real resync entry point.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import consistency_tier as ct

_PLUGIN = Path(__file__).resolve().parents[2]
_REPO = _PLUGIN.parents[2]
_LAND = _REPO / "tools" / "gatekeeper-land.sh"


def _env(**over):
    env = {k: v for k, v in os.environ.items()
           if k not in (ct.ENV, "PYTEST_ADDOPTS")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(over)
    return env


def _pytest(args, cwd, **env):
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
                           *args], cwd=str(cwd), env=_env(**env),
                          capture_output=True, text=True, timeout=600)


@pytest.fixture
def sandbox():
    """A two-test project that loads the tier the way the plugin conftest does.

    mkdtemp, not tmp_path: tmp_path carries a newline in the EDA image.
    """
    d = Path(tempfile.mkdtemp(prefix="ct_"))
    (d / "pytest.ini").write_text("[pytest]\n")
    (d / "conftest.py").write_text(
        f"import sys\nsys.path.insert(0, {str(_PLUGIN / 'programs')!r})\n"
        "pytest_plugins = ('consistency_tier',)\n")
    (d / "test_pair.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.consistency\n"
        "def test_bookkeeping():\n    pass\n\n"
        "def test_behaviour():\n    pass\n\n"
        "@pytest.mark.consistency\n"
        "@pytest.mark.parametrize('v', ['a b', 'a c'])\n"
        "def test_spaced(v):\n    pass\n")
    yield d
    subprocess.run(["rm", "-rf", "--", str(d)], check=False)


def test_routine_session_deselects_and_discloses(sandbox):
    r = _pytest(["-q", "-W", "error::pytest.PytestUnknownMarkWarning"], sandbox)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 passed, 3 deselected" in r.stdout, r.stdout
    assert "consistency tier: 3 bookkeeping test(s) DESELECTED" in r.stdout


def test_the_variable_includes_them(sandbox):
    r = _pytest(["-q", "-rA"], sandbox, **{ct.ENV: "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "4 passed" in r.stdout and "deselected" not in r.stdout, r.stdout
    assert "PASSED test_pair.py::test_bookkeeping" in r.stdout


@pytest.mark.parametrize("value", ["", "0", "true", "yes", " 1"])
def test_only_the_exact_value_one_includes_them(sandbox, value):
    r = _pytest(["-q"], sandbox, **{ct.ENV: value})
    assert "1 passed, 3 deselected" in r.stdout, (value, r.stdout)


def test_the_marker_is_registered_so_strict_markers_accepts_it(sandbox):
    r = _pytest(["-q", "--strict-markers", "--markers"], sandbox)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "@pytest.mark.consistency" in r.stdout


def test_a_real_bookkeeping_test_is_out_of_routine_collection():
    nodeid = ("programs/tests/test_v0_2_83_flow_v230_renumber.py::"
              "test_file_order_is_numeric")
    sibling = ("programs/tests/test_v0_2_83_flow_v230_renumber.py::"
               "test_flow_is_contiguous_1_to_44")
    routine = _pytest(["--collect-only", "-q",
                       "programs/tests/test_v0_2_83_flow_v230_renumber.py"], _PLUGIN)
    full = _pytest(["--collect-only", "-q",
                    "programs/tests/test_v0_2_83_flow_v230_renumber.py"], _PLUGIN,
                   **{ct.ENV: "1"})
    assert nodeid not in routine.stdout and nodeid in full.stdout, (
        routine.stdout[-2000:], full.stdout[-2000:])
    # the behavioural neighbour in the same file is collected either way
    assert sibling in routine.stdout and sibling in full.stdout


def test_the_repo_tools_tree_honours_the_same_tier():
    """`run_repo_tools_pytest` runs from the repo root, outside the plugin conftest."""
    rel = "tools/tests/test_gen_flow_gate_d9_premise.py"
    marked = rel + "::test_the_shipped_report_describes_a_smaller_flow"
    routine = _pytest(["--collect-only", "-q", rel], _REPO)
    full = _pytest(["--collect-only", "-q", rel], _REPO, **{ct.ENV: "1"})
    assert marked not in routine.stdout and marked in full.stdout, (
        routine.stdout[-2000:], full.stdout[-2000:])
    assert "PytestUnknownMarkWarning" not in routine.stdout + routine.stderr


def _cadence_wire() -> str:
    """The landing script's cadence block, from its first line to the next statement."""
    text = _LAND.read_text(encoding="utf-8")
    start = text.index('LANDING_CADENCE="$(python3 "$PROGRAMS/landing_cadence.py"')
    end = text.index("CHEAP_ONLY=0", start)
    return text[start:end]


@pytest.mark.parametrize("answer,inherited,expect", [
    ("FULL", "", "1"),
    ("TARGETED", "", "<unset>"),
    ("TARGETED", "1", "<unset>"),   # a caller cannot make a patch landing bookkeep
    ("NONE", "1", "<unset>"),
    ("", "", "1"),                  # an unreadable cadence is FULL, and so is this
])
def test_the_landing_exports_the_variable_exactly_at_full(answer, inherited, expect):
    d = Path(tempfile.mkdtemp(prefix="ct_land_"))
    try:
        (d / "landing_cadence.py").write_text(
            f"print('LANDING_CADENCE={answer}')\n" if answer else
            "raise SystemExit(3)\n")
        script = ("set -u\nPROGRAMS=" + str(d) + "\nROOT=/nonexistent\nBASE=x\n"
                  + _cadence_wire()
                  + f'\necho "VAR=${{{ct.ENV}-<unset>}}"\n')
        env = _env()
        if inherited:
            env[ct.ENV] = inherited
        r = subprocess.run(["bash", "-c", script], env=env,
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert f"VAR={expect}" in r.stdout, (answer, inherited, r.stdout, r.stderr)
    finally:
        subprocess.run(["rm", "-rf", "--", str(d)], check=False)


def test_tiers_are_the_runners_own_answer():
    """`_tiers` reports what run_tests.sh --list-tiers prints, nothing else."""
    tiers = ct._tiers()
    assert "programs/tests" in tiers
    assert all((_PLUGIN / t).is_dir() for t in tiers), tiers


def test_tiers_refuses_a_runner_that_does_not_answer(monkeypatch, tmp_path):
    (tmp_path / "programs").mkdir()
    (tmp_path / "run_tests.sh").write_text(
        "#!/bin/bash\n# --list-tiers\necho 'no such tier' >&2\nexit 3\n")
    monkeypatch.setattr(ct, "_PLUGIN", tmp_path)
    with pytest.raises(RuntimeError, match="gave no tiers"):
        ct._tiers()




def test_resync_sorts_reds_into_regenerate_and_hand_edit(monkeypatch, capsys):
    regen = next(iter(ct.REGENERATORS))
    monkeypatch.setattr(ct, "_tiers", lambda: ["programs/tests"])
    monkeypatch.setattr(ct, "_tools_test_files", lambda: [])
    monkeypatch.setattr(ct, "_run_consistency", lambda cwd, targets, extra=(): (
        1, {f"{regen}::test_a": "FAILED",
            "programs/tests/test_hand.py::test_b": "FAILED",
            "programs/tests/test_ok.py::test_c": "PASSED"}, ""))
    rc = ct.resync(apply=False, site=None)
    out = capsys.readouterr().out
    assert rc == 1
    assert "3 test(s), 1 passed, 2 red, 0 skipped" in out
    reg, hand = out.split("EDIT BY HAND", 1)
    assert f"RED {regen}" in reg and "not applied" in reg
    assert "programs/tests/test_hand.py::test_b" in hand
    assert f"{regen}::test_a" not in hand
    assert "WEBSITE (vibeic/vibeic.ai)" in out


def test_resync_refuses_an_empty_run(monkeypatch, capsys):
    monkeypatch.setattr(ct, "_tiers", lambda: ["programs/tests"])
    monkeypatch.setattr(ct, "_tools_test_files", lambda: [])
    monkeypatch.setattr(ct, "_run_consistency", lambda *a, **k: (5, {}, ""))
    assert ct.resync(apply=False, site=None) == 2
    assert "NOT_MEASURED" in capsys.readouterr().out


def test_resync_runs_the_real_session_with_the_variable_set(sandbox):
    rc, results, out = ct._run_consistency(sandbox, ["test_pair.py"])
    assert rc == 0, out
    # every node is its own key — a parametrized id with a space included
    assert results == {"test_pair.py::test_bookkeeping": "PASSED",
                       "test_pair.py::test_spaced[a b]": "PASSED",
                       "test_pair.py::test_spaced[a c]": "PASSED"}, out


def test_every_website_fact_names_a_live_source_and_the_readable_ones_resolve():
    for page, anchor, fact, key in ct.WEBSITE_FACTS:
        assert key in ct.LIVE, (page, fact, key)
    for key, (where, derive) in ct.LIVE.items():
        assert where, key
        if derive is not None:
            assert derive() not in (None, "", [], {}), key


def test_every_regenerator_names_a_shipped_generator():
    for test_file, cmd in ct.REGENERATORS.items():
        assert (_PLUGIN / test_file).is_file(), test_file
        base = _REPO if cmd[1].startswith("tools/") else _PLUGIN
        assert (base / cmd[1]).is_file(), cmd
