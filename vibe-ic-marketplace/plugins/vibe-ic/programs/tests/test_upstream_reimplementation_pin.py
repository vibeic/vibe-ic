"""A re-implementation must be pinned to the thing it re-implements.

Every test here was RED before `upstream_reimplementation_pin_check.py`
existed: the module it imports was not in the tree, so the file did not
collect. The reds that matter are the two behavioural ones — a lost anchor
must FAIL, and an unreadable upstream tree must REFUSE rather than pass.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "upstream_reimplementation_pin_check",
    PROGRAMS / "upstream_reimplementation_pin_check.py")
UP = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = UP
_spec.loader.exec_module(UP)

ANCHOR = "incr sum_of_cell_widths $width"
UPSTREAM_REL = "librelane/scripts/openroad/common/pad_cfg.tcl"


def _fake_upstream(root: Path, body: str) -> Path:
    f = root / UPSTREAM_REL
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    return f


def _module_declaring(dirpath: Path, pins_literal: str, name="prog_under_test.py") -> Path:
    p = dirpath / name
    p.write_text(f"UPSTREAM_PINS = {pins_literal}\n", encoding="utf-8")
    return p


def _pins(anchor=ANCHOR):
    return (f'[{{"upstream": {UPSTREAM_REL!r}, "anchor": {anchor!r}, '
            f'"quantity": "the along-the-row extent is the master width"}}]')


def test_a_present_anchor_is_a_pass(tmp_path):
    progs = tmp_path / "programs"
    progs.mkdir()
    _module_declaring(progs, _pins())
    up = tmp_path / "up"
    _fake_upstream(up, f"foo\n    {ANCHOR}\nbar\n")
    assert UP.main(["--programs-dir", str(progs),
                    "--upstream-root", str(up)]) == UP.RC_OK


def test_a_lost_anchor_fails_and_names_it(tmp_path, capsys):
    """THE RED. Upstream switches the quantity; ours is unchanged and now wrong.

    The mutation injected here is the historical one: the per-side fit sum
    computed over the master's HEIGHT instead of its WIDTH.
    """
    progs = tmp_path / "programs"
    progs.mkdir()
    _module_declaring(progs, _pins())
    up = tmp_path / "up"
    _fake_upstream(up, "foo\n    incr sum_of_cell_widths $height\nbar\n")
    rc = UP.main(["--programs-dir", str(progs), "--upstream-root", str(up)])
    assert rc == UP.RC_DRIFT
    err = capsys.readouterr().err
    assert "UPSTREAM_ANCHOR_ABSENT" in err
    assert ANCHOR in err, "a failure that does not name the anchor sends nobody anywhere"


def test_no_upstream_tree_refuses_and_never_passes(tmp_path, capsys):
    """The property the whole check turns on: it cannot answer 'they agree'
    after opening nothing. rc 2, with the missing input NAMED."""
    progs = tmp_path / "programs"
    progs.mkdir()
    _module_declaring(progs, _pins())
    empty = tmp_path / "nothing-here"
    empty.mkdir()
    # Point every default root at an empty tree so the host's real one, if any,
    # cannot answer for it: this test is about the ABSENT case.
    saved = UP.DEFAULT_UPSTREAM_ROOTS
    UP.DEFAULT_UPSTREAM_ROOTS = (str(empty),)
    try:
        rc = UP.main(["--programs-dir", str(progs), "--upstream-root", str(empty)])
    finally:
        UP.DEFAULT_UPSTREAM_ROOTS = saved
    assert rc == UP.RC_CANNOT_CHECK
    err = capsys.readouterr().err
    assert "NOT DETERMINED" in err
    assert "Missing input" in err


def test_a_tree_declaring_no_pin_refuses_rather_than_passing(tmp_path):
    """Zero pins is zero comparisons. Reporting that as rc 0 would be a pass
    manufactured out of an empty denominator."""
    progs = tmp_path / "programs"
    progs.mkdir()
    (progs / "unpinned.py").write_text("X = 1\n", encoding="utf-8")
    assert UP.main(["--programs-dir", str(progs)]) == UP.RC_CANNOT_CHECK


def test_the_container_flavour_is_not_a_finding(tmp_path):
    """A tuple is this repo's house style for a frozen constant. A check that
    demanded a list would be inventing a rule out of the first file it read."""
    progs = tmp_path / "programs"
    progs.mkdir()
    _module_declaring(progs, "(" + _pins()[1:-1] + ",)")
    up = tmp_path / "up"
    _fake_upstream(up, ANCHOR)
    assert UP.main(["--programs-dir", str(progs),
                    "--upstream-root", str(up)]) == UP.RC_OK


def test_a_malformed_declaration_is_a_finding_not_an_empty_list(tmp_path, capsys):
    """`UPSTREAM_PINS = something_unreadable` must not read as 'no pins'."""
    progs = tmp_path / "programs"
    progs.mkdir()
    (progs / "bad.py").write_text("UPSTREAM_PINS = compute_them()\n", encoding="utf-8")
    up = tmp_path / "up"
    _fake_upstream(up, ANCHOR)
    rc = UP.main(["--programs-dir", str(progs), "--upstream-root", str(up)])
    assert rc == UP.RC_DRIFT
    assert "PIN_UNREADABLE" in capsys.readouterr().err


def test_an_incomplete_pin_is_a_finding(tmp_path, capsys):
    progs = tmp_path / "programs"
    progs.mkdir()
    _module_declaring(progs, '[{"upstream": "librelane/x.tcl"}]')
    up = tmp_path / "up"
    _fake_upstream(up, ANCHOR)
    rc = UP.main(["--programs-dir", str(progs), "--upstream-root", str(up)])
    assert rc == UP.RC_DRIFT
    assert "PIN_INCOMPLETE" in capsys.readouterr().err


def test_the_census_counts_prose_citations_without_judging_them(tmp_path):
    """The unpinned set is a MEASURED number, and it is not a verdict."""
    progs = tmp_path / "programs"
    progs.mkdir()
    (progs / "cites_only.py").write_text(
        "# see librelane/scripts/openroad/common/io.tcl\n", encoding="utf-8")
    _module_declaring(progs, _pins())
    up = tmp_path / "up"
    _fake_upstream(up, ANCHOR)
    res = UP.check(progs, [up])
    names = [r["program"] for r in res["census_unpinned"]]
    assert names == ["cites_only.py"]
    assert res["findings"] == [], "a census entry must not become a finding"


# ---------------------------------------------------------------------------
# The SHIPPED pin, against the real upstream tree. Declines honestly when the
# tree is not on this host — the five skips are the check refusing, not passing.
# ---------------------------------------------------------------------------

def test_the_shipped_pins_resolve_against_the_installed_upstream_tree():
    roots = UP._roots([])
    res = UP.check(PROGRAMS, roots)
    read = [c for c in res["checked"] if c["status"] != "NOT_ON_HOST"]
    if not read:
        pytest.skip("no upstream tool tree on this host: the anchors were not "
                    "read, and this test declines rather than passing")
    absent = [c for c in read if c["status"] == "ABSENT"]
    assert not absent, f"upstream no longer carries: {absent}"
    assert res["pins_declared"] >= 1


def test_a_driver_positional_is_answered_not_rejected(tmp_path, capsys):
    """rc 2 must be THIS program's refusal, never argparse's usage error.

    THE RED without the fix is a `SystemExit`: the population drivers in this
    repo invoke every `*_check.py` as `<program> <project>`, argparse rejects
    the unknown positional and exits 2 — the same code this program uses for an
    honest "I could not look". The repo has had to route around that
    conflation at the umbrella and again in a gate's wiring; a check ADDING a
    third instance of it would be the defect it exists to catch, one level up.
    """
    progs = tmp_path / "programs"
    progs.mkdir()
    _module_declaring(progs, _pins())
    empty = tmp_path / "nothing-here"
    empty.mkdir()
    saved = UP.DEFAULT_UPSTREAM_ROOTS
    UP.DEFAULT_UPSTREAM_ROOTS = (str(empty),)
    try:
        rc = UP.main([str(tmp_path / "some-project"),
                      "--programs-dir", str(progs),
                      "--upstream-root", str(empty)])
    except SystemExit as exc:          # what argparse does with an unknown arg
        raise AssertionError(
            f"the driver positional was rejected as a usage error "
            f"(SystemExit {exc.code}) instead of being answered") from exc
    finally:
        UP.DEFAULT_UPSTREAM_ROOTS = saved
    assert rc == UP.RC_CANNOT_CHECK
    cap = capsys.readouterr()
    assert "NOT DETERMINED" in cap.err, "rc 2 must carry this program's words"
    assert "is NOT read" in cap.out, (
        "a project path that is accepted and ignored must be DISCLOSED, or the "
        "next reader believes it was examined")


def test_the_ignored_project_path_is_in_the_artefact_too(tmp_path):
    """On stdout is for a person; in the record is for whatever reads it next."""
    progs = tmp_path / "programs"
    progs.mkdir()
    _module_declaring(progs, _pins())
    up = tmp_path / "up"
    _fake_upstream(up, ANCHOR)
    out = tmp_path / "r.json"
    assert UP.main([str(tmp_path / "proj"), "--programs-dir", str(progs),
                    "--upstream-root", str(up), "--json", str(out)]) == UP.RC_OK
    import json as _json
    assert _json.loads(out.read_text())["project_argument_ignored"].endswith("proj")
