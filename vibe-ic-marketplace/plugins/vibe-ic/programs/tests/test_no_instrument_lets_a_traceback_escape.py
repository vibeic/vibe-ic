"""No instrument may let a traceback escape and become a verdict.

THE RULE, NOT A RESULT. The rc contract is 0 PASS / 1 a finding about the
subject / 2 UNDETERMINED, NOT CHECKED / 3 bad invocation. A traceback that
escapes and is reported as rc 1 is a claim about the subject that was never
earned: the scan died, and the tree is told it has a defect.

Every instrument was swept against a hostile tree by hand once and all were
clean. A one-time sweep decays -- it is a claim taken at a sha, and nothing
re-runs it. This is that sweep as a standing guard.

THE POPULATION IS DERIVED FROM THE TREE, not listed here: every top-level
program that defines `scan()` and accepts `--root`. A program added tomorrow is
covered the moment it lands, and a hand-written list would omit exactly the
ones nobody thought about. Measured at the time of writing: 22, of which 20 are
this branch's instruments and two are `hdl_declaration_scan_strips_comments_check`
and `prose_polarity_consulted_check`, which the rule reaches for free.

THE FIXTURE IS CHECKED TO BE HOSTILE before anything is concluded from it. A
tree of files that turn out to be readable and parseable measures nothing, and
would report a serene green forever.
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]


def _population() -> list[Path]:
    """Top-level programs defining `scan()` and taking `--root`."""
    out = []
    for f in sorted(_PROGRAMS.glob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        if not any(isinstance(n, ast.FunctionDef) and n.name == "scan"
                   for n in tree.body):
            continue
        if '"--root"' in f.read_text(encoding="utf-8", errors="replace"):
            out.append(f)
    return out


def _hostile() -> Path:
    """A tree whose files cannot be read, decoded or parsed.

    `tempfile.mkdtemp`, not pytest's `tmp_path`: that fixture's path carries a
    newline in this image.
    """
    root = Path(tempfile.mkdtemp(prefix="tbesc_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    (progs / "tests").mkdir(parents=True)
    (progs / "_ppa").mkdir()
    (progs / "_ppa" / "__init__.py").write_text("")
    (progs / "broken_syntax.py").write_text("def f(:\n  pass\n")
    (progs / "bad_bytes.py").write_bytes(b"x = '\xff\xfe not utf8'\n")
    (progs / "empty.py").write_text("")
    (progs / "tests" / "test_nothing.py").write_text(
        "def test_x():\n    assert True\n")
    unreadable = progs / "unreadable.py"
    unreadable.write_text("x = 1\n")
    os.chmod(unreadable, 0o000)
    return root


def test_the_population_is_not_empty():
    """A GREEN FROM AN EMPTY DENOMINATOR IS NOT A PASS.

    If the derivation stops matching -- a renamed entry point, a changed flag
    -- this file would sweep nothing and report success for every program in
    the repository.
    """
    pop = _population()
    assert len(pop) >= 20, (
        f"the derivation matched {len(pop)} program(s); it is supposed to find "
        f"every top-level program with scan() and --root. A shrunken "
        f"population here makes every other test in this file vacuous.")


def test_the_fixture_is_actually_hostile():
    """Otherwise the sweep below proves nothing at all."""
    root = _hostile()
    try:
        progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
        with pytest.raises(SyntaxError):
            ast.parse((progs / "broken_syntax.py").read_text(encoding="utf-8"))
        with pytest.raises(UnicodeDecodeError):
            (progs / "bad_bytes.py").read_text(encoding="utf-8")
        with pytest.raises(PermissionError):
            (progs / "unreadable.py").read_text(encoding="utf-8")
    finally:
        _cleanup(root)


def _cleanup(root: Path) -> None:
    for p in root.rglob("*"):
        try:
            os.chmod(p, 0o700)
        except OSError:
            pass
    shutil.rmtree(root, ignore_errors=True)


@pytest.mark.parametrize("prog", _population(), ids=lambda p: p.stem)
def test_no_traceback_escapes_on_a_hostile_tree(prog: Path):
    """Whatever it decides, it must decide it -- not die and be read as rc 1."""
    root = _hostile()
    try:
        plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
        # Two shapes are in use for --root: the repository root and the plugin
        # root. Try both so every program is given the one it understands.
        for candidate in (root, plugin):
            r = _pr.run(
                [sys.executable, str(prog), "--root", str(candidate)],
                capture_output=True, text=True)
            blob = r.stdout + r.stderr
            assert "Traceback (most recent call last)" not in blob, (
                f"{prog.name} let a traceback escape on a hostile tree "
                f"(--root {candidate}); rc={r.returncode}\n{blob[-2000:]}")
            assert r.returncode in (0, 1, 2, 3), (
                f"{prog.name} returned rc={r.returncode}, which is outside the "
                f"contract 0/1/2/3\n{blob[-2000:]}")
            # A REAL VERDICT OWES A DENOMINATOR. rc 0 and rc 1 are claims about
            # a population; rc 2 is "not checked" and owes nothing, which is
            # why it is exempt rather than excused. Measured on this fixture:
            # every rc 0/1 program prints at least THREE population lines and
            # every rc 2 program prints none -- a clean split, so 2 is a
            # threshold with margin rather than a number tuned to today.
            if r.returncode in (0, 1):
                denom = len(re.findall(r"^ +[A-Za-z][^:\n]*: +\d+ *$",
                                       r.stdout, re.M))
                assert denom >= 2, (
                    f"{prog.name} returned rc={r.returncode} -- a claim about a "
                    f"population -- while disclosing {denom} population "
                    f"count(s). A verdict must state what it examined.\n"
                    f"{r.stdout[-2000:]}")
    finally:
        _cleanup(root)
