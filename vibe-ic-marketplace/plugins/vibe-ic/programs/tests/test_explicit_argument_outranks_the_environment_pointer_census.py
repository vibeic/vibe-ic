"""The environment-pointer rule, driven in both directions.

The discriminator is GUARD POLARITY, and the live instance's own file carries
both shapes four lines apart. Both are fixtures here.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_RULE = "explicit_argument_outranks_the_environment_pointer"
PROG = (Path(__file__).resolve().parents[1]
        / "explicit_argument_outranks_the_environment_pointer_census.py")

#: THE DEFECT: the guard fires because the caller NAMED the location.
_DEFECT = '''\
import os


def resolve(args):
    _env_tree = os.environ.get("VIBE_IC_BENCHMARK_DATA")
    if _env_tree and args.tree:
        print(f"note: overrides --tree {args.tree} -> {_env_tree}")
        args.tree = _env_tree
    return args
'''

#: THE REMEDY: the pointer fills an ABSENT location only.
_REPAIRED = '''\
import os


def resolve(args):
    _env_tree = os.environ.get("VIBE_IC_BENCHMARK_DATA")
    if _env_tree and not args.tree:
        print(f"note: scanning {_env_tree}")
        args.tree = _env_tree
    elif _env_tree and args.tree:
        print(f"note: {_env_tree} set and NOT followed; scanning {args.tree}")
    return args
'''

#: `is None` is the same absent test, spelled differently.
_REPAIRED_IS_NONE = '''\
import os


def resolve(args):
    env = os.environ.get("VIBE_IC_BENCHMARK_DATA")
    if env and args.tree is None:
        args.tree = env
    return args
'''

#: An unguarded default at parse time is a different thing: argparse applies it
#: only when the caller supplies nothing.
_ARGPARSE_DEFAULT = '''\
import argparse
import os


def build():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root", default=os.environ.get("PDK_ROOT", ""))
    return ap
'''


def _tree(body: str, inventory=None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="eap_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    (progs / "sample_structure_check.py").write_text(body)
    (root / "inventory.json").write_text(
        json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, *extra, inventory: Path = None):
    return subprocess.run(
        [sys.executable, str(PROG), "--root", str(root), "--inventory",
         str(inventory or (root / "inventory.json")), *extra],
        capture_output=True, text=True, timeout=300)


def test_a_pointer_that_overrules_a_named_location_is_refused():
    """NEGATIVE CONTROL — the live instance's shape, reintroduced."""
    r = _run(_tree(_DEFECT), "--strict")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "--tree" in r.stdout
    assert "args.tree" in r.stdout


def test_filling_an_absent_location_is_not_refused():
    r = _run(_tree(_REPAIRED))
    assert r.returncode == 0, (
        f"the remedy was refused (rc={r.returncode}) — note this fixture also "
        f"CONTAINS an `elif ... and args.tree` branch, which must not fire "
        f"because it only ANNOUNCES.\n{r.stdout}\n{r.stderr}")


def test_the_is_none_spelling_is_also_the_absent_form():
    r = _run(_tree(_REPAIRED_IS_NONE))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_an_argparse_default_is_not_an_override():
    """argparse applies a default only when the caller supplied nothing."""
    r = _run(_tree(_ARGPARSE_DEFAULT))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_announcing_the_override_does_not_make_it_correct():
    """The live instance prints `note: ... overrides --tree ...` and is still
    the defect: the verdict is about the wrong tree either way."""
    r = _run(_tree(_DEFECT), "--strict")
    assert r.returncode == 1
    assert "note:" in _DEFECT and "print" in _DEFECT


def test_a_stale_inventory_row_is_a_failure():
    r = _run(_tree(_REPAIRED, inventory=[
        {"key": "programs/gone.py::tree", "reason": "stale"}]), "--strict")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = subprocess.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = subprocess.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_passes_its_own_rule():
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = subprocess.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_census_never_blocks_by_default():
    """The ruling: this is a census and must not be wired as a blocking check.

    A census that exits non-zero gets wired as a gate by the next person who
    reads the exit code, so the default is 0 whatever is found — and the
    output says so and names the gate that does refuse.
    """
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = subprocess.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, (
        f"the census refused by default (rc={r.returncode}); it must report\n"
        f"{r.stdout}\n{r.stderr}")
    assert "[CENSUS]" in r.stdout
    assert "the gate is programs/%s.py" % _RULE in r.stdout, (
        "the census must name the gate that does the refusing")
