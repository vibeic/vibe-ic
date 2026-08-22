"""The absence-claim rule, driven in both directions.

This gate is GREEN on the tree it ships with, so the POSITIVE CONTROL is the
load-bearing test: it proves the predicate can fire at all. A gate returning
zero because its predicate is blind is indistinguishable from a clean tree.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parents[1]
        / "published_absence_claim_is_rechecked_against_the_tree.py")

sys.path.insert(0, str(PROG.parent))
import published_absence_claim_is_rechecked_against_the_tree as R  # noqa: E402


# ------------------------------------------------- the POSITIVE CONTROL
def test_the_predicate_fires_on_every_canonical_shape():
    """If this goes red, every zero this gate has ever reported is worthless."""
    shapes = [
        "no verdict: programs/ppa_pareto_check.py is not yet present in this tree",
        "cannot answer because programs/em_report_check.py does not exist",
        "skipped - docs/PPA_INTERFACES.md has not landed",
        "tools/ci/repo_hygiene_gates.sh is absent, so nothing was measured",
    ]
    for s in shapes:
        got = R.claims_in(s)
        assert got, f"the predicate did not fire on {s!r}"


def test_an_unattached_verb_and_path_do_not_make_a_claim():
    """78 -> 5 -> 0. The 73 were docstrings whose verb and path are unrelated."""
    far = ("This module does not exist to judge anything. " + "x " * 60
           + "See docs/PPA_INTERFACES.md for the contract.")
    assert R.claims_in(far) == []


# ------------------------------------------------------------ end to end
def _tree(body: str, make_named: bool) -> Path:
    root = Path(tempfile.mkdtemp(prefix="pac_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    (progs / "placeholder.py").write_text(body)
    if make_named:
        (progs / "em_report_check.py").write_text("# it landed\n")
    return root


def _run(root: Path):
    return subprocess.run([sys.executable, str(PROG), "--root", str(root)],
                          capture_output=True, text=True, timeout=300)


_CLAIM = '''\
def verdict():
    return {"status": "NOT_MEASURED",
            "reason": "programs/em_report_check.py does not exist yet"}
'''

_RUNTIME = '''\
def verdict(p):
    return {"status": "NOT_MEASURED", "reason": f"no such file: {p}"}
'''

_DOCSTRING_ONLY = '''\
"""A module that does not exist to judge anything.

See programs/em_report_check.py for the real comparison.
"""


def verdict():
    return {}
'''


def test_a_false_absence_claim_is_refused():
    """NEGATIVE CONTROL: the named path landed, the string never revisited."""
    r = _run(_tree(_CLAIM, make_named=True))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "em_report_check.py" in r.stdout


def test_a_true_absence_claim_is_not_refused():
    """The rule is about a claim the TREE contradicts, not about the wording."""
    r = _run(_tree(_CLAIM, make_named=False))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_runtime_interpolated_path_is_the_correct_pattern():
    """328 absence-shaped strings in the real tree, 0 with a literal path."""
    r = _run(_tree(_RUNTIME, make_named=True))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_docstring_is_not_a_published_reason():
    r = _run(_tree(_DOCSTRING_ONLY, make_named=True))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = subprocess.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = subprocess.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_is_green_over_a_NON_EMPTY_population():
    """Green is only meaningful beside the denominator that produced it."""
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = subprocess.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    line = [l for l in r.stdout.splitlines() if "absence-shaped strings" in l]
    assert line, r.stdout
    n = int(line[0].split(":")[1].split()[0])
    assert n > 50, (
        f"the population collapsed to {n}; a zero finding over a near-empty "
        f"population is NOT OBSERVED, not a pass")
