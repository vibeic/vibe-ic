"""The dual-selector rule, driven in both directions."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (Path(__file__).resolve().parents[1]
        / "two_input_selectors_given_together_must_refuse.py")

#: THE DEFECT: a positional target and a collection flag, wired independently.
_DEFECT = '''\
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("record")
    ap.add_argument("--corpus", default=None)
    a = ap.parse_args()
    if a.corpus:
        return adjudicate_many(a.corpus)
    return adjudicate_one(a.record)
'''

#: REMEDY A: the parser itself refuses both.
_MUTEX = '''\
import argparse


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("record", nargs="?")
    g.add_argument("--corpus", default=None)
    a = ap.parse_args()
    return adjudicate(a)
'''

#: REMEDY B: the program decides the both-given case, as the tree already does.
_DECIDES = '''\
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("record")
    ap.add_argument("--corpus", default=None)
    a = ap.parse_args()
    if a.corpus and a.record:
        print("[REFUSED] --corpus and a record were both given; name one")
        return 3
    return adjudicate(a)
'''

#: `--json` names OUTPUT here, not an input. Counting it added four false
#: candidates.
_JSON_IS_OUTPUT = '''\
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--corpus", default=None)
    return ap.parse_args()
'''

#: Only one way to name the input: out of population.
_SINGLE_ONLY = '''\
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("record")
    return ap.parse_args()
'''


def _tree(body: str, inventory=None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="dis_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    (progs / "sample_check.py").write_text(body)
    (root / "inventory.json").write_text(
        json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, inventory: Path = None):
    return _pr.run(
        [sys.executable, str(PROG), "--root", str(root), "--inventory",
         str(inventory or (root / "inventory.json"))],
        capture_output=True, text=True)


def test_two_independent_selectors_are_refused():
    """NEGATIVE CONTROL."""
    r = _run(_tree(_DEFECT))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "record" in r.stdout and "corpus" in r.stdout


def test_a_mutually_exclusive_group_is_not_refused():
    r = _run(_tree(_MUTEX))
    assert r.returncode == 0, (
        f"the parser-level remedy was refused (rc={r.returncode})\n{r.stdout}")


def test_deciding_the_both_given_case_is_not_refused():
    """The shape already in the tree at step_internal_fail_bubble_up_check."""
    r = _run(_tree(_DECIDES))
    assert r.returncode == 0, (
        f"the explicit-refusal remedy was refused (rc={r.returncode})\n"
        f"{r.stdout}")


def test_json_is_an_output_not_an_input_selector():
    r = _run(_tree(_JSON_IS_OUTPUT))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_single_selector_is_out_of_population():
    r = _run(_tree(_SINGLE_ONLY))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_population_is_stated_even_when_clean():
    r = _run(_tree(_MUTEX))
    assert "dual-selector parsers:" in r.stdout


def test_a_stale_inventory_row_is_a_failure():
    r = _run(_tree(_MUTEX, inventory=[
        {"key": "programs/gone.py::record::corpus", "reason": "stale"}]))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = _pr.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = _pr.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_passes_its_own_rule():
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
