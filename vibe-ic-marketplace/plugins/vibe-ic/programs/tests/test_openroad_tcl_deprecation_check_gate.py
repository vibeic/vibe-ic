#!/usr/bin/env python3
"""Tests for openroad_tcl_deprecation_check.py

This file used to be two lines: `--help` exits 0, and an empty `--search-dir`
exits 0.  Nothing here ever checked that the gate DETECTS a deprecation, so
every assertion would have held on a program whose scanner did nothing.  That
gap is covered — by the SIBLING file `test_openroad_tcl_deprecation_check.py`,
which carries the detection cases and is named in the program's `_self_exempt`
list precisely because a detector's tests must quote the tokens it detects.
This file deliberately does NOT quote one: it is not exempt, so a raw token here
makes the plugin self-check fail on its own test suite.

The empty-directory assertion was worse than absent.  What it meant to pin was
"an empty directory does not crash the program"; what it actually pinned was
`rc == 0`, and `rc == 0` is also how this gate says "clean".  So the test
forbade the program from ever reporting that it had examined nothing — the
proxy standing in for the property, with the proxy load-bearing in the wrong
direction.

It is now the other way round: examining zero files is `rc == 1`, because a
caller reading the exit code cannot otherwise distinguish a clean plugin tree
(3592 files, no hits) from a search directory that matched nothing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / "openroad_tcl_deprecation_check.py"

def _run(args, **kw):
    return _pr.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True,
                          # 45s, under the 60s ceiling: an inner bound that
                          # can outlive the 180s harness kills the SESSION
                          # rather than failing the test. The heaviest call
                          # here is the full-tree default scan, measured at
                          # 4.07s over 3592 files.
                          **kw)


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_empty_dir_is_not_reported_as_clean(tmp_path):
    """Zero files examined must not read as a pass, in message OR exit code."""
    r = _run(["--search-dir", str(tmp_path)])
    assert r.returncode == 1, (
        "an empty search directory exited 0; a caller reading the exit code "
        "cannot tell that from a clean scan")
    assert "NOTHING EXAMINED" in (r.stdout + r.stderr)


def test_empty_dir_does_not_crash(tmp_path):
    """The property the old rc==0 assertion was reaching for, checked directly."""
    r = _run(["--search-dir", str(tmp_path)])
    assert "Traceback" not in (r.stdout + r.stderr)
    assert r.returncode != 2, "rc=2 is the usage/error code, not a scan result"


def test_clean_non_empty_dir_passes_and_states_the_denominator(tmp_path):
    """A clean scan must be distinguishable from an empty one BY THE OUTPUT."""
    (tmp_path / "fine.tcl").write_text("set_routing_layers -signal met1-met4\n",
                                       encoding="utf-8")
    r = _run(["--search-dir", str(tmp_path)])
    assert r.returncode == 0
    assert "examined 1 file" in r.stdout, (
        f"clean run does not state how many files it looked at: {r.stdout!r}")


def test_json_report_carries_the_file_count(tmp_path):
    """`total: 0` alone cannot distinguish clean from unexamined."""
    (tmp_path / "fine.tcl").write_text("# nothing deprecated here\n",
                                       encoding="utf-8")
    out = tmp_path / "r.json"
    _run(["--search-dir", str(tmp_path), "--json", str(out)])
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["total"] == 0
    assert doc["files_examined"] == 1, (
        "the JSON report states total=0 without saying over how many files")


def test_default_scope_examines_the_plugin_tree():
    """The no-argument self-check must have a real denominator.

    Guards the case where a suffix/skip-list change quietly filters the whole
    tree away: the gate would then pass every land, having read nothing.
    """
    r = _run([])
    assert r.returncode == 0, (r.stdout + r.stderr)[:400]
    assert "NOTHING EXAMINED" not in (r.stdout + r.stderr)
    import re
    m = re.search(r"examined (\d+) file", r.stdout)
    assert m, f"default run does not state a denominator: {r.stdout!r}"
    assert int(m.group(1)) > 100, (
        f"default scope examined only {m.group(1)} files; the plugin tree is "
        f"thousands, so something is filtering it away")
