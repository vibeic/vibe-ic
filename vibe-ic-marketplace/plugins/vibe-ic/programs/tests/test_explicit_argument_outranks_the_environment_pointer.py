"""Whatever a gate scanned, it says so.

WHY
===
MEASURED: a checker handed an explicit two-path subject answered about a shared
tree of 8309 paths, because it read the corpus pointer after parsing its
location argument and let the pointer win. The caller could not tell.

WHAT IS NOT DECIDED HERE
========================
There is a live contract split: `_corpus_location` says the pointer replaces a
MISSING corpus only; three consumers deliberately let it win, each with an issue
reference. This rule takes neither side — it enforces the ANNOUNCEMENT, which
both sides already do, and which is the half that would have told the caller
which tree was walked. `test_a_pointer_that_wins_is_not_a_finding_if_announced`
pins that neutrality so the rule cannot drift into arbitration.

chip-AGNOSTIC: argument parsing and output text.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "explicit_argument_outranks_the_environment_pointer.py"

_spec = importlib.util.spec_from_file_location("eaotep", _TOOL)
eaotep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eaotep)

_SCOPE = "vibe-ic-marketplace/plugins/vibe-ic/programs"

_SILENT = (
    'import os\n'
    'CORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"\n'
    'def main(args):\n'
    '    tree = args.tree\n'
    '    env = os.environ.get(CORPUS_ENV)\n'
    '    if env:\n'
    '        tree = env\n'
    '    return scan(tree)\n')
_ANNOUNCED = _SILENT.replace(
    '    if env:\n        tree = env\n',
    '    if env:\n'
    '        print(f"note: {CORPUS_ENV} overrides --tree {tree} -> {env}")\n'
    '        tree = env\n')



def _count_in(text: str, phrase: str) -> bool:
    """`phrase` (which begins with a count) appears with NO digit before it.

    MEASURED: `assert "1 inexpressible" in out` is satisfied by an output saying
    `21 inexpressible`, and `"0 key(s) observed"` by `10 key(s) observed`. A
    substring assertion on a count is not a pin — every one of these tests would
    have passed against a tenfold-wrong number. Taken from the census lane's
    "a substring assertion on a count is not a pin — parse the number".
    """
    return re.search(r"(?<!\d)" + re.escape(phrase), text) is not None


def test_the_count_anchor_actually_fires():
    """PROVE THE PIN FIRES. `_count_in` exists because a substring assertion on a
    count is not a pin — `"1 inexpressible" in out` is satisfied by an output
    saying `21 inexpressible`. A helper that silently never rejects anything would
    reinstate exactly the defect it was added to remove, and nothing else in this
    file would notice, because every other use of it asserts the TRUE case.

    So: the true case passes, and a preceding digit is refused.
    """
    assert _count_in("examined 1 thing", "1 thing")
    assert not _count_in("examined 21 thing", "1 thing"), (
        "the anchor did not fire: a tenfold-wrong count still satisfies the pin")
    assert not _count_in("examined 10 thing", "0 thing")
    assert _count_in("a, 0 thing", "0 thing")

def _mk(tmp_path, body, name="gate.py", scope=_SCOPE):
    d = tmp_path / scope
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body)
    return d / name


def _run(root):
    cp = subprocess.run([sys.executable, str(_TOOL), str(root)],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# ------------------------------------------------------------ red control

def test_a_silent_pointer_reader_goes_red(tmp_path):
    """THE NEGATIVE CONTROL: the defect as measured — the pointer redirects the
    subject and nothing on the output says which tree was walked."""
    _mk(tmp_path, _SILENT)
    rc, out = _run(tmp_path)
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "cannot tell" in out


def test_the_same_reader_that_announces_passes(tmp_path):
    """BIDIRECTIONAL: add only the announcement and the identical redirect
    goes green."""
    _mk(tmp_path, _ANNOUNCED)
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_a_pointer_that_wins_is_not_a_finding_if_announced(tmp_path):
    """NEUTRALITY PIN. The three consumers let the pointer win outright and say
    so. This rule must not redden them — it does not arbitrate the split."""
    _mk(tmp_path, _ANNOUNCED.replace("if env:", "if env:  # pointer wins"))
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_an_accessor_whose_module_announces_elsewhere_passes(tmp_path):
    """`_corpus_location.env_pointer()` merely RETURNS the pointer; the
    announcement lives in `resolve()`. Module granularity, not function."""
    _mk(tmp_path,
        'import os\n'
        'CORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"\n'
        'def env_pointer():\n'
        '    return os.environ.get(CORPUS_ENV) or None\n'
        'def resolve(named):\n'
        '    p = env_pointer()\n'
        '    if p:\n'
        '        print(f"note: {CORPUS_ENV} is set -> {p}")\n'
        '    return p or named\n')
    rc, out = _run(tmp_path)
    assert rc == 0, out


# ---------------------------------------------------- scope is disclosed

def test_an_out_of_scope_reader_is_disclosed_not_refused(tmp_path):
    _mk(tmp_path, _ANNOUNCED)
    outside = tmp_path / "tools" / "ci"
    outside.mkdir(parents=True)
    (outside / "checkout.py").write_text(_SILENT)
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert "DISCLOSED" in out
    assert _count_in(out, "1 silent reader(s) outside the scope disclosed")


def test_the_disclosure_is_never_silently_zero(tmp_path):
    """A PASS whose scope hides offenders must state how many it hid."""
    _mk(tmp_path, _ANNOUNCED)
    rc, out = _run(tmp_path)
    assert _count_in(out, "0 silent reader(s) outside the scope disclosed")


# -------------------------------------------------------------- verdicts

def test_empty_population_is_not_checked(tmp_path):
    (tmp_path / "u.py").write_text("x = 1\n")
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_a_test_file_is_not_a_consumer(tmp_path):
    """A test may set the pointer to build a fixture; that is not a consumer."""
    d = tmp_path / _SCOPE / "tests"
    d.mkdir(parents=True)
    (d / "test_x.py").write_text(_SILENT)
    rc, out = _run(tmp_path)
    assert rc == 2, out


def test_unparseable_file_is_not_checked(tmp_path):
    _mk(tmp_path, 'import os\nCORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"\nx = ,,,\n')
    rc, out = _run(tmp_path)
    assert rc == 2, out


def test_absent_root_is_bad_invocation(tmp_path):
    rc, out = _run(tmp_path / "nope")
    assert rc == 3, out


def test_repository_itself_is_clean():
    rc, out = _run(_PROGRAMS.parents[3])
    assert rc == 0, out
