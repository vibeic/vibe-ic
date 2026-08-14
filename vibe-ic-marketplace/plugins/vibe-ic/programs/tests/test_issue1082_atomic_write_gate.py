#!/usr/bin/env python3
"""vibe-ic#1082 — the ratchet: a NEW non-atomic declared-report write is refused.

The gate ships with a 565-program residual, so the thing that has to be tested
is not "does it find offenders" (it finds hundreds) but the two edges that make
the residual a ratchet rather than an allow-list:

  * a program that is NOT in the baseline and writes non-atomically  -> FAIL
  * a program that IS in the baseline and is CONVERTED               -> PASS,
    and it is reported as converted so the number visibly moves.

Both are driven through `main()` with a real programs directory on disk.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import atomic_artifact_write_check as G  # noqa: E402

_OFFENDER = '''\
import argparse
from pathlib import Path
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    Path(a.json).write_text("{}")
'''

_ATOMIC = '''\
import argparse
from _atomic_artefact import write_text as atomic_write_text
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    atomic_write_text(a.json, "{}")
'''

_NO_DEST = '''\
from pathlib import Path
def helper(tmp):
    Path(tmp / "scratch.txt").write_text("not a declared report")
'''


def _tree(tmp_path, files: dict, baseline: list[str] | None = None):
    d = tmp_path / "programs"
    d.mkdir(exist_ok=True)
    for name, body in files.items():
        (d / name).write_text(body)
    bl = tmp_path / "baseline.json"
    bl.write_text(json.dumps({"offenders": baseline or []}))
    return d, bl


def test_a_new_offender_is_refused(tmp_path, capsys):
    d, bl = _tree(tmp_path, {"newbie.py": _OFFENDER}, baseline=[])
    rc = G.main([str(d), "--baseline", str(bl)])
    err = capsys.readouterr().err
    assert rc == 1, "a program that lands writing its report non-atomically must fail the gate"
    assert "newbie.py" in err and "_atomic_artefact" in err


def test_an_atomic_writer_passes(tmp_path, capsys):
    d, bl = _tree(tmp_path, {"good.py": _ATOMIC}, baseline=[])
    assert G.main([str(d), "--baseline", str(bl)]) == 0
    assert "[PASS]" in capsys.readouterr().out


def test_a_baselined_offender_does_not_fail_but_is_NAMED(tmp_path, capsys):
    """The residual may not go quiet — that is what turns an allow-list into a
    list somebody works down."""
    d, bl = _tree(tmp_path, {"old.py": _OFFENDER}, baseline=["old.py"])
    assert G.main([str(d), "--baseline", str(bl)]) == 0
    out = capsys.readouterr().out
    assert "residual, not yet converted (1)" in out and "old.py" in out


def test_converting_a_baselined_offender_is_reported(tmp_path, capsys):
    d, bl = _tree(tmp_path, {"old.py": _ATOMIC}, baseline=["old.py"])
    assert G.main([str(d), "--baseline", str(bl)]) == 0
    assert "converted since the baseline (1)" in capsys.readouterr().out


def test_a_write_that_is_not_a_declared_report_is_out_of_scope(tmp_path):
    """The narrow population, pinned. A scratch write is partial-safe by
    nature: no consumer resolves it and no step verdict rests on it."""
    d, bl = _tree(tmp_path, {"scratch.py": _NO_DEST}, baseline=[])
    assert G.main([str(d), "--baseline", str(bl)]) == 0


def test_an_empty_or_unreadable_tree_is_NOT_CHECKED_never_PASS(tmp_path):
    assert G.main([str(tmp_path / "nope")]) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert G.main([str(empty)]) == 2, (
        "a directory with no program must not read as a clean sweep")


def test_the_shipped_tree_has_no_new_offender():
    """The gate against the real tree, with the shipped residual."""
    rc = G.main([str(PROGRAMS)])
    assert rc == 0, (
        "a program in this tree writes its declared report destination "
        "non-atomically and is not in the residual baseline")


def test_the_shipped_residual_only_ever_shrinks():
    """The ratchet. `--strict` fails if the count grew since the baseline."""
    assert G.main([str(PROGRAMS), "--strict"]) == 0


def test_the_verdict_bearing_tranche_is_converted():
    """The 10 programs where a partial write flips the step's OWN
    `required_output` from absent to present — derived in the PR, pinned here
    so a later edit cannot quietly put one back."""
    tranche = [
        "rtl_hygiene_lint", "rom_init_lint", "sdc_syntax_check", "bsdl_emit",
        "sta_corner_record_completeness_check", "perc_signoff_check",
        "post_layout_sim_check", "erc_density_check",
        "foundry_handoff_package_check", "mixed_signal_merge_check",
    ]
    still = {s: G.scan_program(PROGRAMS / f"{s}.py") for s in tranche}
    assert not any(still.values()), {k: v for k, v in still.items() if v}
