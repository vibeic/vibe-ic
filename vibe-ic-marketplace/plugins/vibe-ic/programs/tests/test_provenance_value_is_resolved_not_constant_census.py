"""The provenance-constant rule, driven in both directions.

The spec-citation case is a test in its own right: it is the input on which the
first version of this predicate returned 20 of its 32 hits, and the reason the
path test requires an extension and forbids whitespace.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_RULE = "provenance_value_is_resolved_not_constant"
PROG = (Path(__file__).resolve().parents[1]
        / "provenance_value_is_resolved_not_constant_census.py")

#: THE DEFECT: the source claim is typed into the emitter.
_DEFECT = '''\
import json


def emit(project, numbers):
    (project / "reports" / "antenna.json").write_text(json.dumps({
        "source": "reports/phase3/antenna.rpt",
        "violations": numbers,
    }))
'''

#: THE REMEDY: rendered from the path actually opened.
_REPAIRED = '''\
import json


def emit(project, numbers, opened):
    (project / "reports" / "antenna.json").write_text(json.dumps({
        "source": str(opened),
        "violations": numbers,
    }))
'''

#: An input named but unreadable stays a DIFFERENT fact from an absent one.
_UNREADABLE = '''\
import json


def emit(project, numbers, opened, ok):
    (project / "reports" / "antenna.json").write_text(json.dumps({
        "source": str(opened) if ok else "UNREADABLE",
        "violations": numbers,
    }))
'''

#: A SPEC CITATION is not a path. 20 of the first version's 32 hits were these.
_CITATION = '''\
FIELDS = [
    {"name": "AWCACHE", "source": "A3.2.1 / C3.6 / C3.7 / C3.8"},
    {"name": "AWPROT", "source": "C3.1.3 / C4"},
    {"name": "AWQOS", "source": "C3.9 / Figure C3-1"},
]
'''

#: A subscript write is the same shape as a dict literal.
_SUBSCRIPT = '''\
def emit(rec):
    rec["provenance"] = "phase1/generated_docs/L1_DATASHEET.json"
    return rec
'''


def _tree(body: str, inventory=None, name="sample_emit.py") -> Path:
    root = Path(tempfile.mkdtemp(prefix="pvc_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    (progs / name).write_text(body)
    (root / "inventory.json").write_text(
        json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, *extra, inventory: Path = None):
    return _pr.run(
        [sys.executable, str(PROG), "--root", str(root), "--inventory",
         str(inventory or (root / "inventory.json")), *extra],
        capture_output=True, text=True)


def test_a_source_field_filled_from_a_path_constant_is_refused():
    """NEGATIVE CONTROL."""
    r = _run(_tree(_DEFECT), "--strict")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "reports/phase3/antenna.rpt" in r.stdout


def test_a_subscript_write_is_the_same_shape():
    r = _run(_tree(_SUBSCRIPT), "--strict")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "provenance" in r.stdout


def test_a_resolved_value_is_not_refused():
    r = _run(_tree(_REPAIRED))
    assert r.returncode == 0, (
        f"the remedy was refused (rc={r.returncode})\n{r.stdout}\n{r.stderr}")


def test_an_unreadable_marker_is_not_a_path_constant():
    """An absent input and an unexamined one must stay different facts."""
    r = _run(_tree(_UNREADABLE))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_spec_citation_is_not_a_path():
    """20 of the first predicate's 32 hits were citations of this shape."""
    r = _run(_tree(_CITATION, name="ace_protocol_synth.py"))
    assert r.returncode == 0, (
        f"a specification citation was read as a path (rc={r.returncode})\n"
        f"{r.stdout}\n{r.stderr}")


def test_the_population_is_stated_even_when_clean():
    r = _run(_tree(_REPAIRED))
    assert "source-naming field writes:" in r.stdout


def test_a_stale_inventory_row_is_a_failure():
    r = _run(_tree(_REPAIRED, inventory=[
        {"key": "programs/gone.py::source::x.json", "reason": "stale"}]), "--strict")
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


def test_the_census_never_blocks_by_default():
    """The ruling: this is a census and must not be wired as a blocking check.

    A census that exits non-zero gets wired as a gate by the next person who
    reads the exit code, so the default is 0 whatever is found — and the
    output says so and names the gate that does refuse.
    """
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        f"the census refused by default (rc={r.returncode}); it must report\n"
        f"{r.stdout}\n{r.stderr}")
    assert "[CENSUS]" in r.stdout
    assert "the gate is programs/%s.py" % _RULE in r.stdout, (
        "the census must name the gate that does the refusing")
