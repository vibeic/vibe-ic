"""The proof-vocabulary rule, driven in both directions.

RED on the tree it ships with. The load-bearing test is the one asserting that
EXCLUDING THE CONSUMER changes the answer — without it the check is
self-satisfying and reports a clean 9 of 9.
"""
from __future__ import annotations

import ast
import re
import subprocess
import tempfile
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parents[1]
        / "gate_proof_vocabulary_has_a_producer.py")
_PROGRAMS = PROG.parent

sys.path.insert(0, str(_PROGRAMS))
import gate_proof_vocabulary_has_a_producer as R          # noqa: E402

def _count(out: str, label: str) -> int:
    """The integer on the population line `label`, or -1 if absent.

    A SUBSTRING assertion on a count is not a pin. `"axes examined:        1"`
    is a PREFIX of `"axes examined:        14"`, so it passes for 1, 14, 19 and
    100 -- and fails for 2 -- which pins nothing and refuses arbitrarily. This
    reads the number and lets the caller state the relation it actually means.
    """
    m = re.search(rf"^\s*{re.escape(label)}:\s+(\d+)\s*$", out, re.M)
    return int(m.group(1)) if m else -1



def test_the_consumer_is_excluded_and_that_is_what_makes_it_discriminate():
    """Counting the consumer as a producer is a check that cannot fail.

    The gate declares its proof names as string constants and lives in the same
    package as the producers, so a union over the whole package contains every
    proof name trivially.
    """
    produced_correct, mods = R._produced(_PROGRAMS)
    assert mods > 5, mods

    # the same union WITHOUT the exclusion
    names = set()
    for f in sorted((_PROGRAMS / "_ppa").rglob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        names |= {c.value for c in ast.walk(tree)
                  if isinstance(c, ast.Constant) and isinstance(c.value, str)
                  and R._METRIC_NAME.match(c.value)}

    axes = R._axes(_PROGRAMS)
    assert axes, "the axis table could not be read"
    unprovable_correct = [n for n, g in axes.items()
                          if not any(m in produced_correct
                                     for grp in g for m in grp)]
    unprovable_naive = [n for n, g in axes.items()
                        if not any(m in names for grp in g for m in grp)]

    assert unprovable_naive == [], (
        "the naive union was expected to be self-satisfying")
    assert unprovable_correct, (
        "excluding the consumer must change the answer, or the exclusion is "
        "doing nothing")


def test_a_proof_name_only_the_consumer_declares_is_not_produced():
    """`timing.drv.*` occurs in the consumer and in tests, nowhere else."""
    produced, _ = R._produced(_PROGRAMS)
    for m in ("timing.drv.violations", "timing.drv.max_tran_violations",
              "timing.drv.max_cap_violations", "timing.drv.max_fanout_violations"):
        assert m not in produced, f"{m} is now produced — re-derive the finding"


def test_an_axis_with_a_produced_name_is_not_reported():
    produced, _ = R._produced(_PROGRAMS)
    axes = R._axes(_PROGRAMS)
    for name in ("setup", "hold", "drc", "antenna"):
        assert any(m in produced for g in axes[name] for m in g), (
            f"{name} lost its produced name; the finding set has moved")


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = subprocess.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = subprocess.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_is_RED_on_drv():
    """Red by design and un-inventoried.

    The consumer's own source documents this exact class for setup/hold as a
    past defect, repaired per-axis. Because that was a fix and not a rule, the
    shape survived on drv. When a producer emits a drv name, or the axis proves
    from one that is produced, this becomes rc 0 — the gate is not weakened.
    """
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = subprocess.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"
    assert "drv" in r.stdout
    assert "timing.drv.violations" in r.stdout
    # RE-DERIVED 2026-08-22 on the composed tree: 9 -> 10. A sibling lane in
    # the same batch adds an `eco_readiness` axis to `_ppa/search_feasibility`
    # DEFAULT_AXES, and this figure is the population the finding below is
    # measured against, so it moves with it. The finding itself is unchanged in
    # kind: `drv` still proves from names nobody produces. `eco_readiness` now
    # joins it, and its missing name is `design_for_eco.spares.count` — whose
    # producer is the open flow-ownership question on
    # `reports/spare_cell_coverage.json`, NOT something to waive here.
    assert _count(r.stdout, "feasibility axes") == 10, (
        f"the axis population moved; re-derive the finding\n{r.stdout}")


_FEASIBILITY = """\
class Proof:
    def __init__(self, metric, kind=None):
        self.metric = metric


class Axis:
    def __init__(self, name, groups):
        self.name = name
        self.groups = groups


DEFAULT_AXES = (Axis("alpha", ((Proof("timing.alpha.value"),),)),)
"""


def _synthetic(*, produced: bool) -> Path:
    """A tree with ONE axis, whose proof name is or is not emitted.

    `tempfile.mkdtemp`, not pytest's `tmp_path`: in this image that fixture's
    path contains a newline.
    """
    root = Path(tempfile.mkdtemp(prefix="gpv_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    ppa = progs / "_ppa"
    ppa.mkdir(parents=True)
    (ppa / "__init__.py").write_text("")
    (ppa / "feasibility.py").write_text(_FEASIBILITY)          # the CONSUMER
    name = "timing.alpha.value" if produced else "timing.unrelated.value"
    (ppa / "emitter.py").write_text(f'NAME = "{name}"\n')      # a PRODUCER
    return root


def test_a_tree_whose_axis_is_produced_EXITS_ZERO():
    """THE PASS PATH, END TO END. rc 1, 2 and 3 each had a test; rc 0 did not.

    This gate is red by design on the tree it ships with, so the pass branch is
    never reached there -- meaning the reward for REPAIRING the defect was the
    one outcome nobody exercised. If `[PASS]` cannot render, the discovery
    would arrive only once someone had already done the work.
    """
    r = subprocess.run([sys.executable, str(PROG), "--root",
                        str(_synthetic(produced=True))],
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "[PASS]" in r.stdout
    assert _count(r.stdout, "axes with no produced name") == 0


def test_the_same_tree_with_the_name_UNPRODUCED_is_refused():
    """The other arm: same fixture, one string changed, so the rc 0 above is
    the PRODUCED-ness and not the shape of the tree."""
    r = subprocess.run([sys.executable, str(PROG), "--root",
                        str(_synthetic(produced=False))],
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "alpha" in r.stdout
    assert _count(r.stdout, "axes with no produced name") == 1
