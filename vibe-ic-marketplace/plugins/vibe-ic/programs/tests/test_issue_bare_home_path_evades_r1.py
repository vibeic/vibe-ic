"""
A bare home directory — `/home/<name>` with no trailing separator — evaded R1.

MEASURED on 82345bfda (v1.12.76), the shipped tree:

    shipped_path_portability_check: PASS (4967 file(s) scanned, git-tracked)

while `programs/signoff_cell_aware_feol_cfg.py:349` carried a personal home
directory in a shipped comment. `_HOME_PAT` required a separator AFTER the
username::

    r"/home/(?P<u1>" + _USER_CHARS + r")/"
                                      ^ mandatory

so the leak — the username followed by a SPACE — did not match, and the one
personal path inside the shipped plugin sat green.

A bare home directory names one account on one machine exactly as much as
`/home/<name>/some/file` does, so R1 must reach both. The greedy username class
supplies the boundary on its own, which is why making the separator optional
does not widen the rule onto detector patterns (`"/home/"` followed by a quote
or a paren still has no name character after the slash).

Falsified BOTH ways below: `test_r1_*` reddens under the pre-fix pattern and
greens under the shipped one; `test_control_*` must not move in either
direction.

Fixture personal paths are ASSEMBLED AT RUNTIME, never written as literals —
the same rule `test_shipped_path_portability_check.py` follows, and for the same
reason: this file must itself pass the guard it tests, and adding the fixture
name to the guard's allow-list would gut the proof.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROGRAMS.parent
CHECKER = PROGRAMS / "shipped_path_portability_check.py"

sys.path.insert(0, str(PROGRAMS))
import shipped_path_portability_check as spc  # noqa: E402

# Assembled, never literal. Neither name is on the guard's allow-list, which is
# what makes the negative proof real.
_FAKE_USER = "a" + "developer"
_H = "/" + "home" + "/"
_U = "/" + "Users" + "/"
_W = "C:" + "\\" + "Users" + "\\"

# The exact pattern main shipped before the fix, written out literally rather
# than rebuilt from `spc._USER_CHARS` — the fix touches that constant too, so a
# reconstruction would silently track the fix instead of falsifying it.
_PRE_FIX_USER_CHARS = r"[A-Za-z0-9._-]+"          # separator MANDATORY, greedy
_PRE_FIX_PAT = re.compile(
    r"(?:/home/(?P<u1>" + _PRE_FIX_USER_CHARS + r")/"
    r"|/Users/(?P<u2>" + _PRE_FIX_USER_CHARS + r")/"
    r"|[Cc]:\\+Users\\+(?P<u3>" + _PRE_FIX_USER_CHARS + r")\\+)"
)

# The shape that leaked, reproduced with an assembled username: a home directory
# followed by a SPACE inside a comment.
_LEAKED_SHAPE = "# image mounts " + _H + _FAKE_USER + " identically, so a path resolves as-is;"

# Bare home directories R1 must reach: a username terminated by something that
# is not a path separator.
_BARE = [
    _H + _FAKE_USER,                                  # end of string
    "# mounts " + _H + _FAKE_USER + " identically",   # followed by a space
    "see " + _H + _FAKE_USER + ".",                   # sentence-ending period
    "(" + _H + _FAKE_USER + ")",                      # followed by a paren
    _U + _FAKE_USER,                                  # macOS form
    _W + _FAKE_USER,                                  # Windows form
]

# CONTROL (a): paths R1 already caught before the fix — widening must not lose
# them.
_CONTROL_STILL_CAUGHT = [
    _H + _FAKE_USER + "/vibe-ic",
    _U + _FAKE_USER + "/work",
    _W + _FAKE_USER + "\\work",
]

# CONTROL (b): shapes R1 must NEVER claim — detector patterns, placeholders,
# allow-listed names, and a home root with no username at all.
_CONTROL_NEVER_CAUGHT = [
    'r"' + _H + '(?P<u1>"',        # this checker's own detector pattern
    '"' + _H + '" + _USER_CHARS',  # a pattern built by concatenation
    _H + "<your-user>/x",          # angle-bracket placeholder
    _H + "$USER/x",                # shell expansion
    _H + "runner/work",            # allow-listed CI home
    _H,                            # no username at all
]


def _r1_users(text: str, pat) -> set:
    """Usernames R1 would REPORT from `text` under pattern `pat`."""
    out = set()
    for m in pat.finditer(text):
        name = m.group("u1") or m.group("u2") or m.group("u3")
        if not spc._user_allowed(name):
            out.add(name)
    return out


# ---------------------------------------------------------------- the defect
def test_r1_reaches_the_bare_home_directory():
    """SHIPPED pattern: every bare form is reported, with the name intact."""
    for text in _BARE:
        assert _r1_users(text, spc._HOME_PAT) == {_FAKE_USER}, text


def test_r1_pre_fix_pattern_misses_every_bare_form():
    """FALSIFICATION (remove the fix): the pre-fix pattern reports nothing."""
    for text in _BARE:
        assert _r1_users(text, _PRE_FIX_PAT) == set(), text


def test_the_leaked_shape_is_the_defect():
    """The real shape: green before, red after — same string, both directions."""
    assert _r1_users(_LEAKED_SHAPE, _PRE_FIX_PAT) == set()
    assert _r1_users(_LEAKED_SHAPE, spc._HOME_PAT) == {_FAKE_USER}


def test_a_username_may_not_end_on_a_dot():
    """The greedy class must not swallow a sentence-ending period and report a
    name the account does not have."""
    assert _r1_users("see " + _H + _FAKE_USER + ".", spc._HOME_PAT) == {_FAKE_USER}
    assert _FAKE_USER + "." not in _r1_users("see " + _H + _FAKE_USER + ".", spc._HOME_PAT)


# -------------------------------------------------------------------- control
@pytest.mark.parametrize("text", _CONTROL_STILL_CAUGHT)
def test_control_paths_caught_before_are_still_caught(text):
    """CONTROL: widening must not lose what R1 already reported."""
    assert _r1_users(text, _PRE_FIX_PAT) == {_FAKE_USER}
    assert _r1_users(text, spc._HOME_PAT) == {_FAKE_USER}


@pytest.mark.parametrize("text", _CONTROL_NEVER_CAUGHT)
def test_control_shapes_r1_must_never_claim(text):
    """CONTROL: no new false positive — identical verdict on both patterns."""
    assert _r1_users(text, _PRE_FIX_PAT) == set(), text
    assert _r1_users(text, spc._HOME_PAT) == set(), text


# ------------------------------------------------------- end-to-end, exit code
def test_shipped_tree_is_clean_under_the_widened_rule():
    """The whole shipped plugin passes: EXACT exit code 0.

    This file is inside that tree, so it also proves the fixtures above are
    assembled rather than literal.
    """
    p = subprocess.run(
        [sys.executable, str(CHECKER), str(PLUGIN_ROOT)],
        capture_output=True, text=True,
    )
    assert p.returncode == 0, p.stdout + p.stderr


def test_reintroducing_the_bare_path_fails_the_gate(tmp_path):
    """A bare home path anywhere in shipped source FAILs with EXACT exit 1."""
    root = tmp_path / "plugin"
    (root / "programs").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "programs" / "leak.py").write_text(
        "# the image mounts " + _H + _FAKE_USER + " identically\nX = 1\n")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)

    p = subprocess.run(
        [sys.executable, str(CHECKER), str(root)],
        capture_output=True, text=True,
    )
    assert p.returncode == 1, p.stdout + p.stderr
    assert "[R1] " + _H + _FAKE_USER in p.stdout
    assert "programs/leak.py" in p.stdout
