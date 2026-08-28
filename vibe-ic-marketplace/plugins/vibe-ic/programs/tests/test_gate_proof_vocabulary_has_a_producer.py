"""The proof-vocabulary rule, driven in both directions.

GREEN on the tree it ships with, since 2026-08-25. It shipped RED on a verdict
measured FALSE from two directions (F15 in
`docs/findings/2026-08-22-two-capture-distillation-branches-verified.md`), and
THREE of this file's tests encoded that false verdict — one of them
(`test_the_consumer_is_excluded_...`) asserted the unprovable-axis list was
non-empty, which is the exact condition for the gate to exit 1, so NO tree on
which the gate passes could satisfy it. A wrong answer a test defends is harder
to remove than one that merely exists; all three are re-derived below.

The load-bearing test is still the one asserting that EXCLUDING THE CONSUMER
changes the answer — but it now asserts the property directly (the exclusion
REMOVES NAMES) instead of through an axis count that only held while the gate
was broken.
"""
from __future__ import annotations

import ast
import re
import tempfile
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parents[1]
        / "gate_proof_vocabulary_has_a_producer.py")
_PROGRAMS = PROG.parent

sys.path.insert(0, str(_PROGRAMS))
import gate_proof_vocabulary_has_a_producer as R          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


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

    THE ASSERTION IS THE EXCLUSION'S EFFECT ON THE NAME SET, not on the axis
    count. The previous version asserted that some axis stayed unprovable —
    i.e. that the gate stayed RED — so it could only pass on a tree where the
    gate fails. That is not a pin on the exclusion; it is a pin on the defect.
    Measured 2026-08-25: 192 names with the consumer excluded, 197 without, the
    five it alone contributes named below.
    """
    root = _repo_root()
    produced_correct, mods = R._produced(root, _PROGRAMS)
    assert mods > 5, mods

    saved = R._CONSUMERS
    try:
        R._CONSUMERS = frozenset()
        produced_naive, _ = R._produced(root, _PROGRAMS)
    finally:
        R._CONSUMERS = saved

    only_the_consumer = produced_naive - produced_correct
    assert only_the_consumer, (
        "excluding the consumer must change the answer, or the exclusion is "
        "doing nothing")
    assert produced_correct < produced_naive, (
        "the exclusion must only ever REMOVE names")


def test_the_drv_proof_names_are_produced_outside_programs():
    """The false red, pinned in the direction that is TRUE.

    This test asserted the opposite until 2026-08-25 — that the four
    `timing.drv.*` names were produced by nobody — on a docstring premise
    ("occurs in the consumer and in tests, nowhere else") that was untrue of
    the repository. Both producers are tracked files and declare the keys as
    plain literals; if either is removed, the gate goes red and this goes with
    it, which is what a pin is for.
    """
    root = _repo_root()
    for rel in ("ppa-crosslayer/tools/drv_records.py",
                "ppa-e2e/tools/signoff_records.py"):
        assert (root / rel).is_file(), f"the drv producer {rel} is gone"
    produced, _ = R._produced(root, _PROGRAMS)
    for m in ("timing.drv.violations", "timing.drv.max_tran_violations",
              "timing.drv.max_cap_violations", "timing.drv.max_fanout_violations"):
        assert m in produced, (
            f"{m} lost its producer — the drv axis is unprovable again")


def test_an_axis_with_a_produced_name_is_not_reported():
    produced, _ = R._produced(_repo_root(), _PROGRAMS)
    axes = R._axes(_PROGRAMS)
    for name in ("setup", "hold", "drc", "antenna"):
        assert any(m in produced for g in axes[name] for m in g), (
            f"{name} lost its produced name; the finding set has moved")


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = _pr.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = _pr.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_is_GREEN_and_the_population_is_not_empty():
    """rc 0 on this tree, over a population that was actually read.

    This asserted rc 1 until 2026-08-25 and named `timing.drv.violations` in
    the output as the proof. That made the false verdict a FIXTURE: repairing
    the rule turned the suite red, and the instruction beside it said not to
    weaken the gate. The green is pinned with its DENOMINATORS so it cannot be
    reached by a scan that read nothing — a vacuous 0 unprovable axes over 0
    modules is the failure mode a bare `rc == 0` would certify.
    """
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "[PASS]" in r.stdout
    assert _count(r.stdout, "axes with no produced name") == 0
    mods = re.search(r"^\s*emitting modules:\s+(\d+)\b", r.stdout, re.M)
    assert mods and int(mods.group(1)) > 20, r.stdout
    assert _count(r.stdout, "names they declare") > 100, r.stdout
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
    r = _pr.run([sys.executable, str(PROG), "--root",
                        str(_synthetic(produced=True))],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "[PASS]" in r.stdout
    assert _count(r.stdout, "axes with no produced name") == 0


def test_the_same_tree_with_the_name_UNPRODUCED_is_refused():
    """The other arm: same fixture, one string changed, so the rc 0 above is
    the PRODUCED-ness and not the shape of the tree."""
    r = _pr.run([sys.executable, str(PROG), "--root",
                        str(_synthetic(produced=False))],
                       capture_output=True, text=True)
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "alpha" in r.stdout
    assert _count(r.stdout, "axes with no produced name") == 1
