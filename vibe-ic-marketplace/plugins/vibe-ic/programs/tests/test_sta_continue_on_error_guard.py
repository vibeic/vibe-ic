#!/usr/bin/env python3
"""`sta_continue_on_error` must stay at its default of 0, tree-wide.

OpenSTA's `tcl/Util.tcl:563` declares the variable and `tcl/Util.tcl:637-645`
uses it: at 0 an error raises, and on a FILE script `-exit` turns that into a
non-zero process exit. At any other value the error prints and execution
CONTINUES, so a run that linked no design still ends rc=0.

Measured on openroad 26Q3-1797-g1c09d62b96 (image digest
sha256:4ece6c01cddc99903af4f027326f7624b069311f2073a5a0b565d5a9cf649a16):

    default value in the shipped tool                    -> 0
    FILE script, read_verilog fails, variable at default -> rc=1   (caught)
    FILE script, same failure, variable set to 1         -> rc=0   (NOT caught)

That last line is the whole reason for the guard: with the variable raised,
even a correct `-exit` on a correct file script reports success on a run that
analysed nothing, and the exit-code term of `sta_evidence.mjs` is disarmed with
it. Nothing downstream can recover, so it is guarded at the source text.

Both poles are exercised here: an injected setting in each dialect must go RED,
and the tree as it stands must be GREEN. The two CONTROLS matter as much — a
guard that fires on every mention of the name would be useless, so an explicit
`0` and ordinary prose naming the variable must both stay green.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

GUARD = Path(__file__).resolve().parents[1] / "sta_continue_on_error_guard.py"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]

# Assembled from fragments for the same reason the guard is: so this test file
# never itself contains a flagged literal and the sweep over the real tree
# below stays green.
VAR = "sta" + "_continue_on_error"


def _run(*paths) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(GUARD), *[str(p) for p in paths]],
                          capture_output=True, text=True)


# ─────────────────────────────── RED pole ────────────────────────────────────

RED_CASES = {
    "tcl_plain":       ("bad.tcl", f"read_liberty a.lib\nset {VAR} 1\nlink_design top\n"),
    "tcl_global":      ("bad.tcl", f"set ::{VAR} 1\n"),
    "tcl_namespaced":  ("bad.tcl", f"set ::sta::{VAR} true\n"),
    "tcl_nonzero_int": ("bad.tcl", f"set ::{VAR} 2\n"),
    "shell_export":    ("bad.sh",  f"#!/bin/sh\nexport {VAR.upper()}=1\n"),
    "shell_inline":    ("bad.sh",  f"{VAR.upper()}=1 openroad -exit s.tcl\n"),
    "python_assign":   ("bad.py",  f"{VAR} = 1\n"),
    "json_config":     ("bad.json", '{"' + VAR + '": 1}\n'),
    "js_object":       ("bad.js",  f"const cfg = {{ {VAR}: 1 }};\n"),
}


@pytest.mark.parametrize("name", sorted(RED_CASES))
def test_guard_is_red_on_an_injected_setting(tmp_path, name):
    fname, body = RED_CASES[name]
    (tmp_path / fname).write_text(body)
    got = _run(tmp_path)
    assert got.returncode == 1, (
        f"the guard did not fire on dialect {name!r}. A tree carrying this line "
        f"reports rc=0 on a run that linked nothing.\n"
        f"stdout={got.stdout}\nstderr={got.stderr}")
    assert "VIOLATION" in got.stdout


# ───────────────────────────── GREEN controls ────────────────────────────────

GREEN_CASES = {
    # An explicit zero is a restatement of the default and is the one safe
    # thing to write. A guard that banned the NAME would reject it.
    "tcl_explicit_zero":  ("ok.tcl", f"set ::{VAR} 0\n"),
    "shell_explicit_zero": ("ok.sh", f"export {VAR.upper()}=0\n"),
    "json_explicit_zero": ("ok.json", '{"' + VAR + '": 0}\n'),
    # Prose that names the variable, e.g. this docstring or a design note.
    "prose":              ("note.md", f"We must never raise {VAR} above its default.\n"),
    "comment":            ("ok.tcl",  f"# never touch {VAR} here\nlink_design top\n"),
    # A tree that does not mention it at all.
    "unrelated":          ("plain.tcl", "read_liberty a.lib\nlink_design top\n"),
}


@pytest.mark.parametrize("name", sorted(GREEN_CASES))
def test_guard_is_green_on_the_safe_forms(tmp_path, name):
    fname, body = GREEN_CASES[name]
    (tmp_path / fname).write_text(body)
    got = _run(tmp_path)
    assert got.returncode == 0, (
        f"the guard fired on the SAFE form {name!r}. A guard that flags every "
        f"mention of the name fires on everything and is no guard at all.\n"
        f"stdout={got.stdout}")


def test_the_red_and_green_poles_are_distinguished_in_the_same_tree(tmp_path):
    """One directory holding both a safe and an unsafe line must be RED, and
    the message must point at the unsafe line only."""
    (tmp_path / "ok.tcl").write_text(f"set ::{VAR} 0\n")
    (tmp_path / "bad.tcl").write_text(f"set ::{VAR} 1\n")
    got = _run(tmp_path)
    assert got.returncode == 1
    assert "bad.tcl" in got.stdout and "ok.tcl" not in got.stdout


# ───────────────────────── the current tree is clean ─────────────────────────

def test_the_shipped_plugin_tree_is_green():
    """The sweep that makes this guard live rather than dormant: it runs over
    the real shipping boundary on every suite run, not only over fixtures."""
    got = _run(PLUGIN_ROOT)
    assert got.returncode == 0, (
        f"something in the shipped tree raises {VAR}. Every timing gate above it "
        f"reports success on a run that analysed nothing.\n{got.stdout}")


def test_the_whole_repository_is_green_when_it_can_be_located():
    """The plugin is the shipping boundary, but a Tcl or wrapper anywhere in
    the checkout can reach the same interpreter, so sweep the repo too when the
    test is running from inside one."""
    root = PLUGIN_ROOT
    for candidate in PLUGIN_ROOT.parents:
        if (candidate / ".git").exists():
            root = candidate
            break
    else:
        pytest.skip("not running from inside a git checkout")
    got = _run(root)
    assert got.returncode == 0, got.stdout


def test_the_guard_is_clean_on_its_own_source():
    """The guard builds its pattern from fragments precisely so that it needs no
    self-exclusion. If it ever flags itself, someone wrote a flagged literal
    into it and the temptation will be to add an exemption instead."""
    got = _run(GUARD)
    assert got.returncode == 0, got.stdout


def test_missing_root_is_reported_not_silently_clean():
    got = _run(Path("/nonexistent-root-for-the-guard-test"))
    assert got.returncode == 2, (
        "an unreadable root returned a clean verdict — a sweep that cannot read "
        "its target must say so, not report zero violations")
