"""A6 native per-block PV addressed a container the run never named.

`analog_one_shot_runner` resolves an EDA container at eight sites derived
from the tree below (not from a hand-written list of line numbers, which is
what let this one sit outside the convention). Seven use three rungs — the
run's own `--container`, then `VIBEIC_ANALOG_CONTAINER`, then the literal
default. The A6 native-PV call used two: it consulted `args` and then jumped
to the literal, so an orchestrated run that names its container only through
the environment ran DRC/LVS inside `vibeic-eda` and reported the result as
this project's.

It is the same shape as the A4 defect fixed in v1.17.65, pointed the other
way: A4 reached the environment WITHOUT consulting `args`, and the test that
landed with it looks for exactly that. A site that consults `args` and never
reaches the environment is invisible to it — which is why this file measures
the container the runner actually HANDS OVER, not only the source shape.

MEASURED 2026-09-06, 8hd-3, before the fix: with `VIBEIC_ANALOG_CONTAINER`
set and no `--container`, `_try_native_a6_pv` received `vibeic-eda`.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import types
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
RUNNER = PROGRAMS / "analog_one_shot_runner.py"
assert RUNNER.exists(), f"runner not found: {RUNNER}"
import analog_one_shot_runner as R  # noqa: E402


# ── the container the runner HANDS OVER ────────────────────────────────────

@pytest.fixture()
def a6_project(tmp_path):
    """The smallest project that reaches the A6 native-PV call: a declared
    block with no PV evidence, so the A6 gate exits 1 rather than skipping."""
    (tmp_path / "phase3" / "analog" / "blk").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": ["blk"]}))
    return tmp_path


def _container_handed_over(monkeypatch, project, flag, env):
    seen = []
    monkeypatch.setattr(
        R, "_try_native_a6_pv",
        lambda project, block, container: seen.append(container))
    if env is None:
        monkeypatch.delenv("VIBEIC_ANALOG_CONTAINER", raising=False)
    else:
        monkeypatch.setenv("VIBEIC_ANALOG_CONTAINER", env)
    args = types.SimpleNamespace(
        container=flag, allow_deterministic_stubs=False, pdk=None)
    R.step_for_block(project, {"name": "blk", "type": "ldo"},
                     "A6_block_pv", args)
    assert seen, "the A6 native-PV call was never reached; this test measures nothing"
    return seen[-1]


def test_a6_native_pv_reaches_the_container_the_environment_names(
        monkeypatch, a6_project):
    """THE DEFECT. RED before the fix, where this returned `vibeic-eda`."""
    got = _container_handed_over(
        monkeypatch, a6_project, flag=None, env="czadc28_env_container")
    assert got == "czadc28_env_container"


def test_the_runs_own_flag_still_outranks_the_environment(
        monkeypatch, a6_project):
    """Control: precedence must not invert. Green on both arms."""
    got = _container_handed_over(
        monkeypatch, a6_project, flag="czadc28_flag_container",
        env="czadc28_env_container")
    assert got == "czadc28_flag_container"


def test_with_neither_the_default_is_unchanged(monkeypatch, a6_project):
    """Control: a run that names no container anywhere keeps the behaviour
    it has today. Green on both arms — if this moved, the fix would be a
    change of default dressed up as a bug fix."""
    got = _container_handed_over(monkeypatch, a6_project, flag=None, env=None)
    assert got == "vibeic-eda"


# ── every container-resolution site, DERIVED from the tree ─────────────────

def _container_resolution_sites(src: str):
    """Every expression in the module that resolves a container from
    `args.container`, with the source of the lines it spans.

    Derived by AST position: a hand-written list of sites is exactly the
    instrument that would miss the next one.
    """
    tree = ast.parse(src)
    lines = src.splitlines()
    sites = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "getattr"):
            continue
        if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant):
            continue
        if node.args[1].value != "container":
            continue
        lo = node.lineno
        hi = max(node.end_lineno or lo, lo)
        # the fallback chain can continue past the getattr() call itself
        sites[lo] = "\n".join(lines[lo - 1:hi + 3])
    return sites


def test_every_container_site_offers_all_three_rungs():
    """RED BEFORE THE FIX at exactly one site: the A6 native-PV call."""
    sites = _container_resolution_sites(RUNNER.read_text())
    assert len(sites) >= 8, (
        f"expected the runner's container-resolution sites, got {sorted(sites)}")
    offenders = [
        lineno for lineno, blob in sites.items()
        if "VIBEIC_ANALOG_CONTAINER" not in blob
    ]
    assert not offenders, (
        f"container site(s) at line(s) {offenders} consult --container and "
        f"then jump to a literal, skipping VIBEIC_ANALOG_CONTAINER; a run "
        f"that names its container only through the environment will be "
        f"measured inside a container it never asked for")


def test_the_enumeration_itself_can_fail():
    """The enumeration above is only worth its verdict if it can find an
    offender. Plant one and require it to be named."""
    planted = (
        "import os\n"
        "def f(args):\n"
        "    return getattr(args, 'container', None) or 'vibeic-eda'\n"
    )
    sites = _container_resolution_sites(planted)
    assert list(sites) == [3], sites
    assert "VIBEIC_ANALOG_CONTAINER" not in sites[3]
