"""The constant-axis rule, driven in both directions.

RED on the tree it ships with, deliberately and with no inventory, so the
shipped-tree test asserts rc 1 and names what closes it.
"""
from __future__ import annotations

import re
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

def _count(out: str, label: str) -> int:
    """The integer on the population line `label`, or -1 if absent.

    A SUBSTRING assertion on a count is not a pin. `"axes examined:        1"`
    is a PREFIX of `"axes examined:        14"`, so it passes for 1, 14, 19 and
    100 -- and fails for 2 -- which pins nothing and refuses arbitrarily. This
    reads the number and lets the caller state the relation it actually means.
    """
    m = re.search(rf"^\s*{re.escape(label)}:\s+(\d+)\s*$", out, re.M)
    return int(m.group(1)) if m else -1


PROG = (Path(__file__).resolve().parents[1]
        / "metric_constant_across_differing_arms_is_not_measured.py")


def _rec(metric, value=None, status="MEASURED"):
    r = {"metric": metric, "schema": "vibeic.ppa.metric.v1", "status": status}
    if value is not None:
        r["value"] = value
    return r


def _tree(rows) -> Path:
    root = Path(tempfile.mkdtemp(prefix="mca_"))
    (root / ".git").mkdir()
    (root / "vibe-ic-marketplace").mkdir()
    d = root / "ppa-e2e" / "search"
    d.mkdir(parents=True)
    (d / "trials.json").write_text(json.dumps(rows))
    return root


def _run(root: Path):
    return _pr.run([sys.executable, str(PROG), "--root", str(root)],
                          capture_output=True, text=True)


def test_a_constant_axis_over_differing_arms_is_refused():
    """NEGATIVE CONTROL."""
    rows = [{"knobs": {"density": d},
             "metrics": [_rec("power.total_w", 0.000306),
                         _rec("area.um2", 100 + d)]}
            for d in range(4)]
    r = _run(_tree(rows))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "power.total_w" in r.stdout
    assert "area.um2" not in r.stdout, "an axis that MOVES must not be reported"


def test_an_axis_that_moves_is_not_refused():
    rows = [{"knobs": {"density": d},
             "metrics": [_rec("power.total_w", 0.001 * d)]} for d in range(4)]
    r = _run(_tree(rows))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_arms_that_do_not_differ_are_undetermined_not_a_pass():
    """A constant over identical arms says nothing; refusing to judge is right."""
    rows = [{"knobs": {"density": 1},
             "metrics": [_rec("power.total_w", 0.000306)]} for _ in range(4)]
    r = _run(_tree(rows))
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "NOT a pass" in r.stderr


def test_a_record_with_no_value_is_not_measured_and_contributes_nothing():
    """The schema's own invariant: 0, -1 and "" never mean 'not measured'."""
    rows = [{"knobs": {"d": d},
             "metrics": [_rec("route.via.count", status="INVALID")]}
            for d in range(4)]
    r = _run(_tree(rows))
    assert r.returncode == 0, (
        f"an axis with no measured value was treated as constant\n{r.stdout}")


def test_the_metric_names_live_in_a_field_not_a_key():
    """A dict-flattener returns ZERO axes over this shape — measured.

    That zero is indistinguishable from a clean result, which is why the
    extractor reads the `metric` field of each record in the list.
    """
    rows = [{"knobs": {"d": d},
             "metrics": [_rec("power.total_w", 0.000306)]} for d in range(3)]
    r = _run(_tree(rows))
    assert r.returncode == 1
    assert _count(r.stdout, "axes examined") >= 1, (
        f"the extractor found no axis in a metric-record list\n{r.stdout}")


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = _pr.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = _pr.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_is_RED_and_names_the_corroborated_axis():
    """Red by design, no inventory: a waiver would hide seven open questions.

    Closes when the axes are re-measured per arm, or published as NOT MEASURED
    UNDER THIS LEVER. Then this assertion becomes rc 0 — the gate is not
    weakened.
    """
    root = Path(__file__).resolve().parents[5]
    if not (root / "ppa-e2e" / "search" / "trials.json").is_file():
        pytest.skip("no committed arm set in this checkout")
    r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"
    assert "power.total_w" in r.stdout
    assert "0.000306" in r.stdout, (
        "0.000306 W is 0.306 mW — the same figure the chip capture names as a "
        "pre-layout number published under a post-layout header. If it has "
        "changed, both captures need re-deriving.")
    assert "area.design_report" not in r.stdout, (
        "an axis taking 59 distinct values was reported as constant; the "
        "instrument has stopped discriminating")
