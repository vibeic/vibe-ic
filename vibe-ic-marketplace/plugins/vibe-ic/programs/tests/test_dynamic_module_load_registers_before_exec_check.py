"""Tests for dynamic_module_load_registers_before_exec_check.py.

THE DEFECT UNDER TEST. A module loaded with
``spec_from_file_location`` → ``module_from_spec`` → ``exec_module`` is not in
``sys.modules``. When that module defines a module-level ``@dataclass`` whose
annotations are strings, the decorator asks the import table for the defining
module and gets ``None``::

    File ".../dataclasses.py", line 749, in _is_type
        ns = sys.modules.get(cls.__module__).__dict__
    AttributeError: 'NoneType' object has no attribute '__dict__'

The traceback names the standard library, never the loader, so the one-line
cause hides. Two shipped loaders in this tree carry a comment or a docstring
paragraph stating the rule, and a later author re-broke it anyway — which is
why the rule is a program now.

WHAT MAKES THIS FILE WORTH ANYTHING — three things.

(1) BOTH ARMS. The positive arm builds the defect and requires a FAIL naming
    the offending file and line; the control arm adds the one missing line and
    requires a PASS. Whole classes of not-a-finding get their own control too —
    a registered load, a dataclass-free load, a load whose path the syntax does
    not pin down — because a rule with only one of its halves would fire on
    hundreds of correct sites in this tree.

(2) EVERY CLAIM ABOUT CPython IS RUN, NOT ASSERTED. ``_runtime_ok`` executes
    the fixture loader in a subprocess. Each shape the checker calls harmless
    is proved harmless by the interpreter, and the headline defect's FAIL is
    tied to a real ``AttributeError`` in the same test.

(3) THE BUY-GREEN ARM. A gate is only as good as the edits it survives. The
    ``buy_green`` tests take the FAILING fixture and apply ONE line of the kind
    a person reaches for when a gate is in the way — a debug print, a
    registration under the wrong key, a comment that states the rule — and
    require the FAIL to stand while the runtime still crashes. The previous
    revision of this checker was disarmed by ``print("loading", mod)``; that
    exact edit is now a test. ONE such edit is NOT fully closed and is pinned
    at its exact width instead: a registration nested in a compound statement
    (``if cond: sys.modules[spec.name] = mod``) moves the site to an explicit
    no-verdict rather than a FAIL. ``test_the_nested_registration_softening_
    is_exactly_this_wide`` states that in runnable form, because the
    alternative — convicting it — convicts the 26 memoising loaders in this
    tree that are written the same way and work.

This file's own loader below registers before exec, deliberately: the checker
defines a dataclass under ``from __future__ import annotations``, so loading it
the wrong way raises the very AttributeError under test.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Sequence, Tuple

_PROGRAMS = Path(__file__).resolve().parents[1]
_CHECKER = _PROGRAMS / "dynamic_module_load_registers_before_exec_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("_dmlrbe_check", _CHECKER)
    mod = importlib.util.module_from_spec(spec)
    # The checker defines a @dataclass under `from __future__ import
    # annotations`. Registering it here is not ceremony: without this line the
    # exec below raises the AttributeError this whole file is about.
    sys.modules["_dmlrbe_check"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


# --------------------------------------------------------------------------
# Fixture text. Assembled from pieces so a test can vary ONE line.
# --------------------------------------------------------------------------
_TARGET_FATAL = """\
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict


@dataclass
class Row:
    inputs: Dict[str, int]
"""

_TARGET_LIVE_ANNOTATION = """\
from dataclasses import dataclass


@dataclass
class Row:
    name: str
"""

_TARGET_QUOTED_NO_FUTURE = """\
from dataclasses import dataclass


@dataclass
class Row:
    name: "str"
"""

_TARGET_QUOTED_UNDER_FUTURE = """\
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Row:
    name: "str"
"""

_TARGET_DOTTED = """\
from __future__ import annotations
import typing as t
from dataclasses import dataclass


@dataclass
class Row:
    a: t.List[int]
"""

_TARGET_NO_FIELDS = """\
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Marker:
    pass
"""

_TARGET_FUNC_LOCAL = """\
from __future__ import annotations
from dataclasses import dataclass


def make():
    @dataclass
    class Row:
        inputs: str
    return Row
"""

_TARGET_TYPE_CHECKING = """\
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    @dataclass
    class Row:
        inputs: str
"""

_TARGET_PLAIN = """\
VALUE = 1


def helper(x):
    return x + VALUE
"""

_LOADER_HEAD = """\
import importlib.util
import sys
from pathlib import Path

_T = Path(__file__).resolve().parent / "target.py"


def load():
    spec = importlib.util.spec_from_file_location("target", _T)
    mod = importlib.util.module_from_spec(spec)
"""

_LOADER_TAIL = """\
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    load()
    print("RUNTIME: OK")
"""

_REGISTER = "    sys.modules[spec.name] = mod\n"


def _runtime_ok(loader: Path) -> Tuple[bool, str]:
    """Run the fixture loader for real and report whether it survived.

    Every narrowing in this checker exists because a real interpreter
    disagreed with an earlier revision. A test that only asserted the new
    verdict would be asserting the same belief in a different place.
    """
    proc = subprocess.run([sys.executable, str(loader)],
                          capture_output=True, text=True)
    return proc.returncode == 0, proc.stdout + proc.stderr


def _write(d: Path, target: str, loader: str) -> Tuple[Path, Path]:
    (d / "target.py").write_text(target)
    p = d / "loader.py"
    p.write_text(loader)
    return d / "target.py", p


def _line_of(path: Path, needle: str) -> int:
    """1-based line number of ``needle`` — DERIVED, never written down.

    A hardcoded line number is a bet on the fixture's whitespace; this asserts
    the number the checker prints is the number the defect is on.
    """
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not in {path}")


def _run(capsys, roots: Sequence[Path]) -> Tuple[int, str]:
    capsys.readouterr()          # drain anything an earlier call printed
    rc = mod.main([str(r) for r in roots])
    cap = capsys.readouterr()
    return rc, cap.out + cap.err


# --------------------------------------------------------------------------
# POSITIVE ARM — the defect must FAIL, and the message must be actionable
# --------------------------------------------------------------------------
def test_unregistered_dataclass_load_fails(tmp_path, capsys):
    _write(tmp_path, _TARGET_FATAL, _LOADER_HEAD + _LOADER_TAIL)
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_FAIL, out


def test_the_failure_names_the_file_and_the_exec_line(tmp_path, capsys):
    _t, loader = _write(tmp_path, _TARGET_FATAL, _LOADER_HEAD + _LOADER_TAIL)
    exec_line = _line_of(loader, "exec_module(mod)")
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_FAIL
    assert f"{loader}:{exec_line}:" in out, out
    assert "target.py" in out, out


def test_the_failure_names_the_field_it_convicts(tmp_path, capsys):
    """The message must say WHICH dataclass field sends the decorator down the
    crashing branch — that is the whole claim, and a reader has to check it."""
    _write(tmp_path, _TARGET_FATAL, _LOADER_HEAD + _LOADER_TAIL)
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_FAIL
    assert "@dataclass Row" in out and "field inputs" in out, out


def test_a_quoted_annotation_with_no_future_import_is_out_of_scope(tmp_path, capsys):
    """Clause 4 requires the future import. This load DOES die, and the gate
    stays silent about it — a documented KNOWN CONSERVATISM, pinned here so it
    cannot be widened by accident."""
    _write(tmp_path, _TARGET_QUOTED_NO_FUTURE, _LOADER_HEAD + _LOADER_TAIL)
    ok, log = _runtime_ok(tmp_path / "loader.py")
    assert not ok and "dataclasses.py" in log, log
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_PASS, out


def test_the_prediction_is_the_crash(tmp_path, capsys):
    """Tie the FAIL to the interpreter: the fixture the gate convicts really
    raises, and the single line the gate asks for really fixes it."""
    _write(tmp_path, _TARGET_FATAL, _LOADER_HEAD + _LOADER_TAIL)
    ok, log = _runtime_ok(tmp_path / "loader.py")
    assert not ok, log
    assert "AttributeError" in log and "dataclasses.py" in log, log
    rc, _out = _run(capsys, [tmp_path])
    assert rc == mod.RC_FAIL

    (tmp_path / "loader.py").write_text(_LOADER_HEAD + _REGISTER + _LOADER_TAIL)
    ok, log = _runtime_ok(tmp_path / "loader.py")
    assert ok and "RUNTIME: OK" in log, log
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_PASS, out


# --------------------------------------------------------------------------
# BUY-GREEN ARM — a one-line edit must not turn the FAIL into a PASS
# --------------------------------------------------------------------------
def _still_fails(tmp_path, capsys, inserted: str) -> str:
    """Insert ONE line before the exec, then require FAIL and a real crash."""
    _write(tmp_path, _TARGET_FATAL, _LOADER_HEAD + inserted + _LOADER_TAIL)
    ok, log = _runtime_ok(tmp_path / "loader.py")
    assert not ok and "dataclasses.py" in log, ("the edit fixed the defect, so "
                                                "this is not a buy-green case:\n" + log)
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_FAIL, ("DISARMED by one line: " + inserted.strip() + "\n" + out)
    return out


def test_buy_green_a_debug_print_does_not_disarm(tmp_path, capsys):
    """The exact edit that disarmed the previous revision. It had an escape
    hatch keyed on "the module object is handed to some call", and a print
    opened it while the runtime still crashed."""
    _still_fails(tmp_path, capsys, '    print("loading", mod)\n')


def test_buy_green_a_registration_under_a_wrong_literal_key_does_not_count(tmp_path, capsys):
    """MEASURED: registering under a name the class does not carry crashes
    exactly like no registration at all, so it must not read as registered."""
    _still_fails(tmp_path, capsys, '    sys.modules["dummy"] = mod\n')


def test_buy_green_a_registration_under_a_foreign_key_expression_does_not_count(tmp_path, capsys):
    _still_fails(tmp_path, capsys, "    sys.modules[__name__] = mod\n")


def test_buy_green_writing_something_else_into_the_import_table_does_not_count(tmp_path, capsys):
    """``sys.modules[k] = <not the module object>`` is not a registration of
    this module. The previous revision accepted any write whose value was not
    a bare name, which laundered a whole scope."""
    _still_fails(tmp_path, capsys, '    sys.modules["target"] = None\n')


def test_buy_green_setdefault_under_a_wrong_key_does_not_count(tmp_path, capsys):
    _still_fails(tmp_path, capsys, '    sys.modules.setdefault("dummy", mod)\n')


def test_buy_green_a_comment_stating_the_rule_does_not_satisfy_it(tmp_path, capsys):
    _still_fails(tmp_path, capsys, "    # sys.modules[spec.name] = mod\n")


def test_buy_green_a_string_containing_the_fix_does_not_satisfy_it(tmp_path, capsys):
    _still_fails(tmp_path, capsys, '    _note = "sys.modules[spec.name] = mod"\n')


def test_buy_green_registering_after_the_exec_is_still_a_failure(tmp_path, capsys):
    """Order is the rule. The decorator has already run by then."""
    _write(tmp_path, _TARGET_FATAL, _LOADER_HEAD + _LOADER_TAIL.replace(
        "    return mod\n", "    sys.modules[spec.name] = mod\n    return mod\n"))
    ok, log = _runtime_ok(tmp_path / "loader.py")
    assert not ok and "dataclasses.py" in log, log
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_FAIL, out


def test_buy_green_renaming_the_module_variable_does_not_disarm(tmp_path, capsys):
    """The rule keys on the syntax's relationships, never on a chosen name."""
    loader = (_LOADER_HEAD + _LOADER_TAIL)
    loader = (loader.replace("    mod = importlib", "    m = importlib")
                    .replace("exec_module(mod)", "exec_module(m)")
                    .replace("    return mod", "    return m"))
    _write(tmp_path, _TARGET_FATAL, loader)
    ok, log = _runtime_ok(tmp_path / "loader.py")
    assert not ok and "dataclasses.py" in log, log
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_FAIL, out


def test_buy_green_the_skip_list_is_pinned(tmp_path, capsys):
    """Adding one token to ``_SKIP_DIRS`` would mute whole subtrees silently.
    The set is asserted EXACTLY, so widening it must be argued for in a diff.
    """
    assert mod._SKIP_DIRS == {".git", "__pycache__", ".pytest_cache",
                              "node_modules", ".mypy_cache", ".venv", "venv",
                              ".tox"}


def test_a_defect_in_a_nested_directory_is_still_found(tmp_path, capsys):
    """The sweep is recursive, and the fixture lives in a directory named
    ``tests`` — the single most tempting token to add to ``_SKIP_DIRS``."""
    nest = tmp_path / "pkg" / "tests"
    nest.mkdir(parents=True)
    _write(nest, _TARGET_FATAL, _LOADER_HEAD + _LOADER_TAIL)
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_FAIL, out
    assert str(nest / "loader.py") in out, out


# --------------------------------------------------------------------------
# CONTROL ARM — every one of these RUNS, so none of them may FAIL
# --------------------------------------------------------------------------
def _passes_and_runs(tmp_path, capsys, target: str, loader: str) -> str:
    _write(tmp_path, target, loader)
    ok, log = _runtime_ok(tmp_path / "loader.py")
    assert ok and "RUNTIME: OK" in log, ("the fixture does NOT run, so it is "
                                         "not a false-positive control:\n" + log)
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_PASS, ("FALSE POSITIVE: this code works\n" + out)
    return out


def test_registering_before_the_exec_passes(tmp_path, capsys):
    _passes_and_runs(tmp_path, capsys, _TARGET_FATAL,
                     _LOADER_HEAD + _REGISTER + _LOADER_TAIL)


def test_setdefault_counts_as_registration(tmp_path, capsys):
    _passes_and_runs(tmp_path, capsys, _TARGET_FATAL, _LOADER_HEAD
                     + "    sys.modules.setdefault(spec.name, mod)\n" + _LOADER_TAIL)


def test_an_aliased_sys_import_still_counts(tmp_path, capsys):
    loader = (_LOADER_HEAD.replace("import sys", "import sys as _s")
              + "    _s.modules[spec.name] = mod\n" + _LOADER_TAIL)
    _passes_and_runs(tmp_path, capsys, _TARGET_FATAL, loader)


def test_a_from_sys_import_modules_still_counts(tmp_path, capsys):
    loader = (_LOADER_HEAD.replace("import sys", "from sys import modules")
              + "    modules[spec.name] = mod\n" + _LOADER_TAIL)
    _passes_and_runs(tmp_path, capsys, _TARGET_FATAL, loader)


def test_the_key_may_be_the_same_expression_the_spec_name_came_from(tmp_path, capsys):
    """``spec_from_file_location(_NAME, …)`` + ``sys.modules[_NAME] = mod`` is
    the second of the two key shapes that ship in this tree."""
    head = _LOADER_HEAD.replace('spec_from_file_location("target", _T)',
                                "spec_from_file_location(_NAME, _T)")
    head = head.replace('_T = Path(__file__).resolve().parent / "target.py"',
                        '_T = Path(__file__).resolve().parent / "target.py"\n_NAME = "target"')
    _passes_and_runs(tmp_path, capsys, _TARGET_FATAL,
                     head + "    sys.modules[_NAME] = mod\n" + _LOADER_TAIL)


def test_a_dataclass_free_target_unregistered_is_not_a_finding(tmp_path, capsys):
    """Half the rule alone would fire on hundreds of correct loads here."""
    _passes_and_runs(tmp_path, capsys, _TARGET_PLAIN, _LOADER_HEAD + _LOADER_TAIL)


def test_live_annotations_are_not_fatal(tmp_path, capsys):
    """No future import, no quotes: the stored annotation is a live object and
    ``_is_type`` is never reached."""
    _passes_and_runs(tmp_path, capsys, _TARGET_LIVE_ANNOTATION,
                     _LOADER_HEAD + _LOADER_TAIL)


def test_a_module_prefixed_annotation_is_not_fatal(tmp_path, capsys):
    """``t.List[int]`` captures ``t`` as a module prefix and takes the guarded
    branch of ``_is_type``."""
    _passes_and_runs(tmp_path, capsys, _TARGET_DOTTED, _LOADER_HEAD + _LOADER_TAIL)


def test_a_quoted_annotation_under_the_future_import_is_not_fatal(tmp_path, capsys):
    """The compiler stores ``"'str'"`` — quotes included — and the regex does
    not match a leading quote."""
    _passes_and_runs(tmp_path, capsys, _TARGET_QUOTED_UNDER_FUTURE,
                     _LOADER_HEAD + _LOADER_TAIL)


def test_a_dataclass_with_no_annotated_field_is_not_fatal(tmp_path, capsys):
    _passes_and_runs(tmp_path, capsys, _TARGET_NO_FIELDS, _LOADER_HEAD + _LOADER_TAIL)


def test_a_dataclass_defined_inside_a_function_is_not_fatal(tmp_path, capsys):
    """The decorator does not run during ``exec_module``. Clause 4 reads
    ``tree.body``, never ``ast.walk``, which is why this passes."""
    _passes_and_runs(tmp_path, capsys, _TARGET_FUNC_LOCAL, _LOADER_HEAD + _LOADER_TAIL)


def test_a_dataclass_under_type_checking_is_not_fatal(tmp_path, capsys):
    _passes_and_runs(tmp_path, capsys, _TARGET_TYPE_CHECKING,
                     _LOADER_HEAD + _LOADER_TAIL)


def test_a_docstring_describing_the_loader_is_not_a_load_site(tmp_path, capsys):
    """973 files in this tree name ``spec_from_file_location`` in prose and
    only 481 call it. A text-keyed rule would be 492 files wrong."""
    prose = '''"""How to load a program by path:

    spec = importlib.util.spec_from_file_location("target", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
"""
VALUE = 1
'''
    (tmp_path / "target.py").write_text(_TARGET_FATAL)
    (tmp_path / "prose.py").write_text(prose)
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_PASS, out
    assert "0 load site(s)" in out, out


# --------------------------------------------------------------------------
# NO VERDICT — "I could not look" must never be spelled PASS
# --------------------------------------------------------------------------
def test_a_parameterised_path_is_unresolved_not_passed(tmp_path, capsys):
    (tmp_path / "target.py").write_text(_TARGET_FATAL)
    (tmp_path / "loader.py").write_text(
        "import importlib.util\n\n\ndef load(path):\n"
        '    spec = importlib.util.spec_from_file_location("t", path)\n'
        "    mod = importlib.util.module_from_spec(spec)\n"
        "    spec.loader.exec_module(mod)\n    return mod\n")
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_CANNOT_CHECK, out
    assert "cannot-check" in out and "loader.py:7" in out, out


def test_a_cwd_relative_path_is_unresolved(tmp_path, capsys):
    """A path relative to the process working directory names a different file
    per caller, so the syntax does not pin it down."""
    (tmp_path / "loader.py").write_text(
        "import importlib.util\n\n\ndef load():\n"
        '    spec = importlib.util.spec_from_file_location("t", "target.py")\n'
        "    mod = importlib.util.module_from_spec(spec)\n"
        "    spec.loader.exec_module(mod)\n    return mod\n")
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_CANNOT_CHECK, out
    assert "relative to the process working directory" in out, out


def test_one_unresolved_site_does_not_mask_a_real_one(tmp_path, capsys):
    (tmp_path / "vague.py").write_text(
        "import importlib.util\n\n\ndef load(path):\n"
        '    spec = importlib.util.spec_from_file_location("t", path)\n'
        "    mod = importlib.util.module_from_spec(spec)\n"
        "    spec.loader.exec_module(mod)\n    return mod\n")
    _write(tmp_path, _TARGET_FATAL, _LOADER_HEAD + _LOADER_TAIL)
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_FAIL, out
    assert "cannot-check" in out and str(tmp_path / "loader.py") in out, out


def test_a_vanished_target_is_a_cannot_check_not_a_pass(tmp_path, capsys):
    (tmp_path / "loader.py").write_text(_LOADER_HEAD + _LOADER_TAIL)
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_CANNOT_CHECK, out
    assert "no file at" in out, out


def test_an_unparseable_target_is_a_cannot_check_not_a_pass(tmp_path, capsys):
    _write(tmp_path, "def (:\n", _LOADER_HEAD + _LOADER_TAIL)
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_CANNOT_CHECK, out
    assert "does not parse" in out, out


# --------------------------------------------------------------------------
# THE RUN'S OWN PRECONDITIONS
# --------------------------------------------------------------------------
def test_absent_root_refuses(tmp_path, capsys):
    rc, out = _run(capsys, [tmp_path / "nope"])
    assert rc == mod.RC_CANNOT_CHECK, out
    assert "absent" in out, out


def test_a_partial_invocation_refuses_and_names_the_root_it_could_not_read(tmp_path, capsys):
    """One good root and one typo used to print a clean PASS that never
    mentioned the path it failed to open."""
    (tmp_path / "ok.py").write_text("VALUE = 1\n")
    rc, out = _run(capsys, [tmp_path, tmp_path / "typo"])
    assert rc == mod.RC_CANNOT_CHECK, out
    assert str(tmp_path / "typo") in out, out


def test_a_root_with_no_python_refuses(tmp_path, capsys):
    (tmp_path / "readme.md").write_text("no python here\n")
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_CANNOT_CHECK, out
    assert "read 0 Python file(s)" in out, out


def test_a_run_in_which_nothing_resolved_refuses(tmp_path, capsys):
    (tmp_path / "loader.py").write_text(
        "import importlib.util\n\n\ndef load(path):\n"
        '    spec = importlib.util.spec_from_file_location("t", path)\n'
        "    mod = importlib.util.module_from_spec(spec)\n"
        "    spec.loader.exec_module(mod)\n    return mod\n")
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_CANNOT_CHECK, out
    assert "NONE resolved" in out, out


# --------------------------------------------------------------------------
# SCOPE AND ARITHMETIC
# --------------------------------------------------------------------------
def test_a_load_inside_nested_blocks_is_counted_once(tmp_path, capsys):
    (tmp_path / "target.py").write_text(_TARGET_FATAL)
    (tmp_path / "loader.py").write_text(
        "import importlib.util\nfrom pathlib import Path\n\n"
        '_T = Path(__file__).resolve().parent / "target.py"\n\n\n'
        "def load(flag):\n    if flag:\n        try:\n"
        '            spec = importlib.util.spec_from_file_location("target", _T)\n'
        "            mod = importlib.util.module_from_spec(spec)\n"
        "            spec.loader.exec_module(mod)\n"
        "            return mod\n        except OSError:\n            return None\n")
    sites = mod.analyse_file(tmp_path / "loader.py")
    assert len(sites) == 1, [ (s.exec_line, s.verdict) for s in sites ]
    assert sites[0].verdict == "FAIL"


def test_a_nested_loader_function_is_its_own_scope(tmp_path, capsys):
    """An OUTER registration must not launder an INNER unregistered load."""
    (tmp_path / "target.py").write_text(_TARGET_FATAL)
    (tmp_path / "loader.py").write_text(
        "import importlib.util\nimport sys\nfrom pathlib import Path\n\n"
        '_T = Path(__file__).resolve().parent / "target.py"\n\n\n'
        "def outer():\n"
        '    spec = importlib.util.spec_from_file_location("target", _T)\n'
        "    mod = importlib.util.module_from_spec(spec)\n"
        "    sys.modules[spec.name] = mod\n"
        "    spec.loader.exec_module(mod)\n\n"
        "    def inner():\n"
        '        spec2 = importlib.util.spec_from_file_location("target", _T)\n'
        "        mod2 = importlib.util.module_from_spec(spec2)\n"
        "        spec2.loader.exec_module(mod2)\n"
        "        return mod2\n    return inner\n")
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_FAIL, out
    assert "exec_module(mod2)" in out, out


def test_resolved_plus_unresolved_equals_the_site_total(tmp_path, capsys):
    """A verdict line whose arithmetic does not close is one nobody can audit."""
    _write(tmp_path, _TARGET_FATAL, _LOADER_HEAD + _LOADER_TAIL)
    (tmp_path / "vague.py").write_text(
        "import importlib.util\n\n\ndef load(path):\n"
        '    spec = importlib.util.spec_from_file_location("t", path)\n'
        "    mod = importlib.util.module_from_spec(spec)\n"
        "    spec.loader.exec_module(mod)\n    return mod\n")
    sites, stats = mod.sweep([str(tmp_path)])
    judged = sum(stats[c.lower()] for c in mod._JUDGED)
    no_verdict = sum(stats[c.lower()] for c in mod._NO_VERDICT)
    assert judged + no_verdict == stats["sites_total"] == len(sites)
    assert judged and no_verdict


def test_every_site_lands_in_a_declared_classification(tmp_path):
    """A site that reached none of these is a bug in the classifier, not a
    clean site."""
    sites, _stats = mod.sweep([str(_PROGRAMS)])
    assert sites
    assert {s.verdict for s in sites} <= set(mod.CLASSIFICATIONS)


def test_the_verdict_states_what_it_read(tmp_path, capsys):
    (tmp_path / "ok.py").write_text("VALUE = 1\n")
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_PASS
    assert "file(s)" in out and "load site(s)" in out and "resolved" in out, out


def test_this_files_own_loader_is_seen_and_classified_registered():
    """The checker judges the file you are reading, and says the right thing
    about it: its ``_load()`` above registers before exec because the checker
    itself defines a dataclass under a future import."""
    sites = mod.analyse_file(Path(__file__))
    assert len(sites) == 1, [(s.exec_line, s.verdict) for s in sites]
    assert sites[0].verdict == "REGISTERED"
    assert sites[0].target == str(_CHECKER)


# --------------------------------------------------------------------------
# THE FIX HAS MORE THAN ONE MAINSTREAM SPELLING
# Each of these RUNS. An earlier revision convicted the first two, which is a
# gate telling a person their correct fix is the defect.
# --------------------------------------------------------------------------
def test_the_key_may_be_the_loaded_modules_own_dunder_name(tmp_path, capsys):
    """``module_from_spec`` assigns ``module.__name__ = spec.name`` as it
    builds the object, so ``sys.modules[mod.__name__] = mod`` registers under
    exactly the name the decorator will look for."""
    _passes_and_runs(tmp_path, capsys, _TARGET_FATAL,
                     _LOADER_HEAD + "    sys.modules[mod.__name__] = mod\n"
                     + _LOADER_TAIL)


def test_the_chained_assignment_form_registers(tmp_path, capsys):
    """``mod = sys.modules[spec.name] = module_from_spec(spec)``: both targets
    receive one object. The stored VALUE is a Call, and reading only bare-name
    values convicted this."""
    head = _LOADER_HEAD.replace(
        "    mod = importlib.util.module_from_spec(spec)\n",
        "    mod = sys.modules[spec.name] = importlib.util.module_from_spec(spec)\n")
    _passes_and_runs(tmp_path, capsys, _TARGET_FATAL, head + _LOADER_TAIL)


def test_buy_green_a_dunder_name_of_some_other_object_is_not_this_spec(tmp_path, capsys):
    """The ``__name__`` spelling is accepted for THIS site's module variable
    and for nothing else — otherwise it would be a second wrong-key hole."""
    _still_fails(tmp_path, capsys, '    other = type(sys)("dummy")\n'
                                   "    sys.modules[other.__name__] = mod\n")


# --------------------------------------------------------------------------
# A REGISTRATION THAT IS NOT A STATEMENT OF THE LOADER'S SCOPE
# Never credited, never convicted, always named.
# --------------------------------------------------------------------------
_OS_HEAD = _LOADER_HEAD.replace("import sys\n", "import os\nimport sys\n")


def _nested(tmp_path, capsys, inserted: str) -> str:
    _write(tmp_path, _TARGET_FATAL, _OS_HEAD + inserted + _LOADER_TAIL)
    rc, out = _run(capsys, [tmp_path])
    assert rc != mod.RC_FAIL, ("a nested registration may not convict:\n" + out)
    assert rc == mod.RC_CANNOT_CHECK, out
    assert "only inside a compound statement" in out, out
    assert [s.verdict for s in mod.analyse_file(tmp_path / "loader.py")] \
        == ["REGISTRATION_NOT_SCOPE_DIRECT"], out
    return out


def test_a_registration_under_an_if_is_not_credited(tmp_path, capsys):
    """The named blocker: one added line used to flip a live defect to
    REGISTERED. The runtime still crashes, so PASS would be a lie — and the
    syntax does not prove it runs, so FAIL would be one too."""
    out = _nested(tmp_path, capsys,
                  '    if os.environ.get("X"):\n'
                  "        sys.modules[spec.name] = mod\n")
    ok, log = _runtime_ok(tmp_path / "loader.py")
    assert not ok and "dataclasses.py" in log, log
    assert "fatal kind of dataclass" in out, out


def test_a_dead_branch_registration_is_not_credited(tmp_path, capsys):
    """``if 0:`` is what a person writes to get past a gate that reads line
    numbers. It buys silence here, never green."""
    _nested(tmp_path, capsys, "    if 0:\n        sys.modules[spec.name] = mod\n")
    ok, log = _runtime_ok(tmp_path / "loader.py")
    assert not ok and "dataclasses.py" in log, log


def test_a_registration_in_a_loop_or_a_try_is_not_credited(tmp_path, capsys):
    _nested(tmp_path, capsys, "    for _ in (1,):\n        sys.modules[spec.name] = mod\n")
    _nested(tmp_path, capsys, "    try:\n        sys.modules[spec.name] = mod\n"
                              "    except Exception:\n        pass\n")


def test_a_memoising_loader_nested_as_a_whole_is_never_convicted(tmp_path, capsys):
    """26 loaders in this tree are written exactly like this — spec,
    registration and exec all inside one ``if _cached is None:`` block — and
    every one of them RUNS. Declining to judge them is the price; calling them
    a defect is not on the table."""
    (tmp_path / "target.py").write_text(_TARGET_FATAL)
    loader = tmp_path / "loader.py"
    loader.write_text(
        "import importlib.util\nimport sys\nfrom pathlib import Path\n\n"
        '_T = Path(__file__).resolve().parent / "target.py"\n_CACHED = None\n\n\n'
        "def load():\n    global _CACHED\n    if _CACHED is None:\n"
        '        spec = importlib.util.spec_from_file_location("target", _T)\n'
        "        mod = importlib.util.module_from_spec(spec)\n"
        "        sys.modules[spec.name] = mod\n"
        "        spec.loader.exec_module(mod)\n        _CACHED = mod\n"
        "    return _CACHED\n\n\n"
        'if __name__ == "__main__":\n    load()\n    print("RUNTIME: OK")\n')
    ok, log = _runtime_ok(loader)
    assert ok and "RUNTIME: OK" in log, ("the fixture does not run, so it is "
                                         "not a false-positive control:\n" + log)
    rc, out = _run(capsys, [tmp_path])
    assert rc != mod.RC_FAIL, ("FALSE POSITIVE: this code works\n" + out)
    assert [s.verdict for s in mod.analyse_file(loader)] \
        == ["REGISTRATION_NOT_SCOPE_DIRECT"], out


def test_a_nested_registration_is_out_of_the_resolved_denominator(tmp_path, capsys):
    """No verdict means no verdict: it may not be counted as clean."""
    _write(tmp_path, _TARGET_FATAL, _OS_HEAD
           + '    if os.environ.get("X"):\n        sys.modules[spec.name] = mod\n'
           + _LOADER_TAIL)
    sites, stats = mod.sweep([str(tmp_path)])
    assert stats["registration_not_scope_direct"] == 1
    assert sum(stats[c.lower()] for c in mod._JUDGED) == 0
    assert len(sites) == 1


def test_the_nested_registration_softening_is_exactly_this_wide(tmp_path, capsys):
    """DOCUMENTED SOFTENING, pinned. The one-line edit
    ``if cond: sys.modules[spec.name] = mod`` does NOT leave a FAIL standing:
    with no other resolved site in the run it lands on rc 2, and with one it
    lands on rc 0 while printing the site by name. The tighter rule was
    measured and refused because it convicts the shape the test above runs.
    If someone closes this, this test goes red and should be deleted."""
    _write(tmp_path, _TARGET_FATAL, _OS_HEAD
           + '    if os.environ.get("X"):\n        sys.modules[spec.name] = mod\n'
           + _LOADER_TAIL)
    ok, log = _runtime_ok(tmp_path / "loader.py")
    assert not ok and "dataclasses.py" in log, log          # the defect is live
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_CANNOT_CHECK, out                   # alone: rc 2

    other = tmp_path / "clean"
    other.mkdir()
    _write(other, _TARGET_FATAL, _LOADER_HEAD + _REGISTER + _LOADER_TAIL)
    rc, out = _run(capsys, [tmp_path])
    assert rc == mod.RC_PASS, out                           # beside one: rc 0
    assert str(tmp_path / "loader.py") in out, out          # but never silent
    assert "only inside a compound statement" in out, out


def test_buy_green_the_judged_set_is_pinned(tmp_path):
    """Moving a no-verdict state into the denominator — or a judged one out of
    it — is a one-line edit that changes what PASS means without touching a
    predicate. It has to be argued for in a diff."""
    assert mod._JUDGED == ("REGISTERED", "NO_FATAL_DATACLASS", "FAIL")
    assert set(mod._NO_VERDICT) == {"UNRESOLVED", "TARGET_MISSING",
                                    "TARGET_UNPARSEABLE",
                                    "REGISTRATION_NOT_SCOPE_DIRECT"}


def test_the_chained_form_is_read_whatever_built_the_module(tmp_path, capsys):
    """The chained form is credited because BOTH TARGETS RECEIVE ONE OBJECT,
    not because the value is spelled ``module_from_spec``. A helper on the
    right-hand side is the same guarantee and RUNS (MEASURED) — and if the
    helper returned a module under some other name, the loader's own check
    raises ``ImportError: loader for target cannot handle other`` instead of
    this silent crash, which is why no narrowing is needed here."""
    head = _LOADER_HEAD.replace(
        "def load():", "def _prepared(m):\n    return m\n\n\ndef load():")
    _passes_and_runs(tmp_path, capsys, _TARGET_FATAL, head
                     + "    mod = sys.modules[spec.name] = _prepared(mod)\n"
                     + _LOADER_TAIL)
