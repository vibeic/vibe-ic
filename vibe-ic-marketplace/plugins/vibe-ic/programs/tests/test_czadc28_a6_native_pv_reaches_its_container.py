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
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
RUNNER = PROGRAMS / "analog_one_shot_runner.py"
assert RUNNER.exists(), f"runner not found: {RUNNER}"


# ── the container the runner HANDS OVER ────────────────────────────────────













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
