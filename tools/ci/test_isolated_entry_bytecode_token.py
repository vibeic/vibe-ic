"""`python3 -I` DISCARDS `PYTHONDONTWRITEBYTECODE`, so the variable alone never
reached the child that imports the tests.

THE DEFECT, MEASURED ON A PRISTINE CLONE OF MAIN
================================================
A landing run in the pinned image, on a `git clean -xdfq` checkout with
`dirty=0` and `PYTHONDONTWRITEBYTECODE=1` exported into the container, refused
at `tools/ci/repo_hygiene_gates.sh:117`::

    [FAIL] attestation_preflight_check: this checkout would make the attestation
    measure itself [7259 file(s) under 1 declared root(s)].

The declared root there is `$ROOT` -- the landing checkout itself -- so the
gate's subject is the tree the run lives in. Sampled from outside the container
while that same run was live, the tree it had been handed clean grew::

    00:22:53  launch                       7221 files    0 .pyc
    00:25:50                               7725 files  500 .pyc
    00:32:11                               7816 files  535 .pyc

with `tracked_drift=0` throughout. Nothing the operator did or failed to do
moved those numbers: the run was writing bytecode into the root it was about to
attest, and the same commit therefore refused with a different count every time
it was asked. A verdict that is a stopwatch reading is not a verdict.

WHY THE VARIABLE COULD NOT WORK, AND WHY THAT WAS NOT A GUESS
=============================================================
Every lane already carried `PYTHONDONTWRITEBYTECODE=1`, and
`tools/test_gatekeeper_land_lanes.py` asserted that it did. Both were true and
the bytecode was written anyway, because the token was supplied on the side of
`-I` that `-I` throws away. MEASURED in the pinned image, the variable exported
in the environment for all three::

    python3        -c 'import sys; print(sys.dont_write_bytecode)'  ->  True
    python3 -I     -c 'import sys; print(sys.dont_write_bytecode)'  ->  False
    python3 -I -B  -c 'import sys; print(sys.dont_write_bytecode)'  ->  True

`-I` implies `-E`, and `-E` discards every `PYTHON*` name. The driver
(`pytest_per_file_junit.py`, no `-I`) honoured the variable; the isolated entry
it spawns -- the process that actually imports the test files -- never saw it.

These tests are BIDIRECTIONAL: `test_an_isolated_child_writes_bytecode_without_B`
is the negative control, and it must FAIL to be a control at all -- it asserts
that the un-fixed shape really does write, so that its sibling asserting the
fixed shape does not is evidence rather than a tautology.

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tools/ci/<this file>
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: The environment a child inherits, and the one `-I` refuses to look at.
ENV_FLAG = "PYTHONDONTWRITEBYTECODE"

_PROBE = "import sys; sys.stdout.write(str(sys.dont_write_bytecode))"


def _dont_write_bytecode(*flags: str) -> str:
    """What a child with these flags reports, with the variable EXPORTED."""
    proc = subprocess.run(
        [sys.executable, *flags, "-c", _PROBE],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", ENV_FLAG: "1"}, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


# ── the mechanism, stated as three measurements ─────────────────────────────

def test_a_plain_child_honours_the_exported_variable():
    assert _dont_write_bytecode() == "True"


def test_isolated_mode_discards_the_exported_variable():
    """THE NEGATIVE CONTROL. If this ever reports True the premise is gone and
    the `-B` flags added for it are cargo; the fix would need re-deriving, not
    keeping."""
    assert _dont_write_bytecode("-I") == "False", (
        "`python3 -I` no longer discards the environment; the reason `-B` was "
        "added to every isolated entry no longer holds and must be re-measured")


def test_the_B_flag_reaches_the_isolated_child():
    assert _dont_write_bytecode("-I", "-B") == "True"


# ── the mechanism, end to end, on a real import ─────────────────────────────

def _import_and_count_pycache(tmp_path: Path, *flags: str) -> int:
    subject = tmp_path / "subject"
    subject.mkdir()
    (subject / "m.py").write_text("VALUE = 1\n", encoding="utf-8")
    # `-I` implies `-P` as well, so the script directory is not on `sys.path`
    # and a bare `import m` would fail for a reason that is not the subject.
    (subject / "go.py").write_text(
        "import sys, pathlib\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).parent))\n"
        "import m\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, *flags, "go.py"], cwd=subject,
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", ENV_FLAG: "1"}, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return len(list(subject.rglob("*.pyc")))


def test_an_isolated_child_writes_bytecode_without_B(tmp_path):
    """The control that must not move. With the variable exported, the
    un-fixed shape writes into the tree it was pointed at."""
    assert _import_and_count_pycache(tmp_path, "-I") >= 1, (
        "the un-fixed shape no longer writes bytecode, so the sibling test "
        "below proves nothing")


def test_an_isolated_child_with_B_writes_nothing(tmp_path):
    assert _import_and_count_pycache(tmp_path, "-I", "-B") == 0


# ── no caller may spawn an isolated child without the flag ──────────────────

#: `python3 -I` in a SHELL command position. The flags that follow are walked
#: as TOKENS rather than matched with a lookahead: a lookahead placed after an
#: optional group lets the group backtrack to empty and succeed anyway, which
#: reported `python3 -I -B <path>` as an offender the first time this was
#: written.
_SH_CALL = re.compile(r"python3 -I(?![A-Za-z])")
#: The argv-list form, `[..., "-I", <next>]`. The comma and the spacing live
#: INSIDE the lookahead for the same backtracking reason.
_PY_CALL = re.compile(r"""["']-I["'](?!\s*,\s*["']-B["'])""")


def _isolated_call_lacks_B(line: str, start: int) -> bool:
    """True when the `python3 -I` at `start` runs something without `-B`.

    Prose is excluded by requiring a real argument after the flags: a sentence
    about the hazard ends the phrase at a backtick or a full stop, never at a
    path, a quote, a `$` or a `-c`.
    """
    tokens = line[start:].split()[1:]          # drop `python3`
    flags: list[str] = []
    for token in tokens:
        if token.startswith("-") and len(token) <= 2 and token[1:].isalpha():
            flags.append(token)
            continue
        break
    else:
        return False                            # flags only: not a call
    rest = tokens[len(flags):]
    if not rest or not rest[0][:1] in {'"', "'", "/", "$", "-"}:
        return False                            # no argument: prose, not a call
    return "-B" not in flags


def _shell_callers() -> list[Path]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.sh"],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return [ROOT / line for line in out.stdout.split() if line]


def _python_callers() -> list[Path]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.py"],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return [ROOT / line for line in out.stdout.split()
            if line and "/tests/" not in line
            and not Path(line).name.startswith("test_")]


def test_no_shell_caller_spawns_an_isolated_child_without_B():
    offenders: list[str] = []
    for path in _shell_callers():
        for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue          # prose about the hazard is not the hazard
            for match in _SH_CALL.finditer(line):
                if _isolated_call_lacks_B(line, match.start()):
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert offenders == [], (
        "`python3 -I` implies `-E`, which DISCARDS PYTHONDONTWRITEBYTECODE, so "
        "these children write bytecode into the tree the landing gates attest "
        "no matter what the environment says. Pass `-B` on the command line:\n"
        + "\n".join(offenders))


def test_no_python_caller_spawns_an_isolated_child_without_B():
    offenders: list[str] = []
    for path in _python_callers():
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _PY_CALL.finditer(text):
            number = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == [], (
        "an isolated child built from an argv list must carry \"-B\" "
        "immediately after \"-I\"; `-I` implies `-E` and discards "
        f"{ENV_FLAG}:\n" + "\n".join(offenders))
