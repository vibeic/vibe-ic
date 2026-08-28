"""The census of verdict-emitting programs the wiring audit cannot see.

Driven in both directions on synthetic trees, plus the rc contract and the
shipped tree. The load-bearing test is the one proving the NARROW predicate
sees `rc = 1; return rc` -- a literal-only match found 8 of this branch's 20
instruments while all twenty refuse, and that undercount is the reason this
program reports a range at all.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (Path(__file__).resolve().parents[1]
        / "checker_population_is_structural_not_filename_shaped_census.py")

_AUDIT = '_CHECKER_SUFFIXES = ("*_check.py", "*_audit.py")\n'

_LITERAL_REFUSER = '''\
import sys
def main():
    print("[FAIL] nope")
    return 1
if __name__ == "__main__":
    sys.exit(main())
'''

_ASSIGNED_REFUSER = '''\
import sys
def main():
    rc = 0
    if True:
        print("[FAIL] nope")
        rc = 1
    return rc
if __name__ == "__main__":
    sys.exit(main())
'''

_NON_REFUSER = '''\
import sys
def main():
    print("[PASS] fine")
    return 0
if __name__ == "__main__":
    sys.exit(main())
'''

_NOT_A_CHECKER = '''\
def helper():
    return 42
'''


def _tree(files: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="cps_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    (progs / "checker_execution_wiring_audit.py").write_text(_AUDIT)
    for name, body in files.items():
        (progs / name).write_text(body)
    return root


def _run(root: Path, *args):
    return _pr.run([sys.executable, str(PROG), "--root", str(root),
                           *args], capture_output=True, text=True)


def _count(out: str, label: str) -> int:
    m = re.search(rf"^ +{re.escape(label)}: +(\d+) *$", out, re.M)
    return int(m.group(1)) if m else -1


def test_a_suffix_named_program_is_visible_and_not_reported():
    root = _tree({"zz_thing_check.py": _LITERAL_REFUSER})
    try:
        r = _run(root)
        assert r.returncode == 0, r.stdout
        assert _count(r.stdout, "outside and emitting a verdict") == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_verdict_program_outside_the_suffixes_is_counted():
    root = _tree({"zz_thing.py": _LITERAL_REFUSER})
    try:
        r = _run(root)
        assert _count(r.stdout, "outside and emitting a verdict") == 1
        assert _count(r.stdout, "outside and also refusing") == 1
        assert "zz_thing.py" in r.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_assigned_rc_form_is_seen_as_refusing():
    """THE LOAD-BEARING ONE.

    `rc = 1; return rc` is how this repository's checkers refuse. A literal-only
    predicate found 8 of this branch's 20 instruments while all 20 refuse; that
    is the undercount this test pins.
    """
    root = _tree({"zz_assigned.py": _ASSIGNED_REFUSER})
    try:
        r = _run(root)
        assert _count(r.stdout, "outside and emitting a verdict") == 1
        assert _count(r.stdout, "outside and also refusing") == 1, (
            f"the assigned-rc refusal was not seen\n{r.stdout}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_verdict_program_that_cannot_refuse_is_counted_wide_only():
    root = _tree({"zz_quiet.py": _NON_REFUSER})
    try:
        r = _run(root)
        assert _count(r.stdout, "outside and emitting a verdict") == 1
        assert _count(r.stdout, "outside and also refusing") == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_module_that_emits_no_verdict_is_not_counted():
    root = _tree({"zz_helper.py": _NOT_A_CHECKER})
    try:
        r = _run(root)
        assert _count(r.stdout, "outside and emitting a verdict") == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_suffix_tuple_is_read_from_the_audit_not_re_typed():
    """Widening the audit's tuple must shrink this census with no edit here."""
    root = _tree({"zz_thing_probe.py": _LITERAL_REFUSER})
    try:
        before = _run(root)
        assert _count(before.stdout, "outside and emitting a verdict") == 1
        audit = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
                 / "programs" / "checker_execution_wiring_audit.py")
        audit.write_text('_CHECKER_SUFFIXES = ("*_check.py", "*_probe.py")\n')
        after = _run(root)
        assert _count(after.stdout, "suffix patterns") == 2
        assert _count(after.stdout, "outside and emitting a verdict") == 0, (
            f"the tuple was not re-read from the audit\n{after.stdout}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_it_is_a_census_and_exits_zero_with_findings():
    root = _tree({"zz_thing.py": _LITERAL_REFUSER})
    try:
        assert _run(root).returncode == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_strict_restores_the_refusal():
    root = _tree({"zz_thing.py": _LITERAL_REFUSER})
    try:
        assert _run(root, "--strict").returncode == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_strict_is_zero_when_nothing_is_invisible():
    root = _tree({"zz_thing_check.py": _LITERAL_REFUSER})
    try:
        assert _run(root, "--strict").returncode == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_unreadable_audit_is_undetermined_not_a_pass():
    root = _tree({"zz_thing.py": _LITERAL_REFUSER})
    try:
        (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
         / "checker_execution_wiring_audit.py").unlink()
        r = _run(root)
        assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}"
        assert "NOT a pass" in r.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = _pr.run([sys.executable, str(PROG), "--root", "/nonexistent/cps"],
                       capture_output=True, text=True)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}"


def test_a_bad_invocation_is_rc_3():
    r = _pr.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}"


def test_the_shipped_tree_runs_and_discloses_its_population():
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}"
    for label in ("top level programs", "visible to the audit",
                  "outside and emitting a verdict"):
        assert _count(r.stdout, label) >= 0, (
            f"{label} not disclosed\n{r.stdout}")
    assert _count(r.stdout, "visible to the audit") > 0


_COMPOSED_BANNER = '''\
import sys
def main():
    head = "[FAIL] composed" if True else "[PASS] composed"
    print(head)
    return 1
if __name__ == "__main__":
    sys.exit(main())
'''

_DOCSTRING_ONLY = '''\
"""This module merely DESCRIBES a [PASS] / [FAIL] banner."""
import sys
def main():
    print("[CENSUS] nothing to report")
    return 0
if __name__ == "__main__":
    sys.exit(main())
'''


def test_a_composed_banner_counts_wide_but_not_as_a_literal():
    """THE FALSE-NEGATIVE THE STRICT PREDICATE WOULD CAUSE.

    `landing_merge_verdict.py:1803` assigns the banner to a name and prints the
    name; `coverage_closure.py:105` returns it in a list. Both are real verdict
    emitters that a literal-in-print match never sees, which is why the wide
    figure is the one reported and the literal figure only sits beside it.
    """
    root = _tree({"zz_composed.py": _COMPOSED_BANNER})
    try:
        r = _run(root)
        assert _count(r.stdout, "outside and emitting a verdict") == 1
        assert _count(r.stdout, "of those with a literal banner in a print") == 0
        assert _count(r.stdout, "outside and also refusing") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_module_that_only_describes_a_banner_is_the_wide_overcount():
    """The other side of the same coin, and it includes this census itself."""
    root = _tree({"zz_doc.py": _DOCSTRING_ONLY})
    try:
        r = _run(root)
        assert _count(r.stdout, "outside and emitting a verdict") == 1
        assert _count(r.stdout, "of those with a literal banner in a print") == 0
        assert _count(r.stdout, "outside and also refusing") == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_literal_banner_is_counted_as_one():
    root = _tree({"zz_literal.py": _LITERAL_REFUSER})
    try:
        r = _run(root)
        assert _count(r.stdout, "of those with a literal banner in a print") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)
