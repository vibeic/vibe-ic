"""#564 — a gate that looks for something ABSENT printed the same thing either way.

    PASS — 0 waveform artifact(s)     over a clean tree
    PASS — 0 waveform artifact(s)     over a path that does not exist
    rc=0 for both

`audit()` walked `rglob("*")` and returned only the hits, so nothing anywhere
knew how many files it had looked at. That matters more here than for the gates
fixed earlier in this issue, not less: this one is looking for something that
SHOULD be absent, so zero is the expected answer — which is exactly why "I
walked 3000 files and found none" and "I walked nothing" must not be the same
sentence.

Measured over 40 corpus projects before landing, and unchanged by the fix:

    rc 0   38   real tree, no artefacts
    rc 1    2   real finding

so no real project reaches the new refusal.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "waveform_artifact_hygiene_check.py"


def _run(root) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(root)],
                          capture_output=True, text=True, timeout=45)


def test_absent_tree_refuses(tmp_path):
    proc = _run(tmp_path / "no-such-tree")
    assert proc.returncode == 2, (
        f"an absent tree exited {proc.returncode}; a caller reading the exit "
        f"code cannot tell it from a clean shipped tree")
    assert "VACUOUS_PASS" in proc.stderr


def test_empty_tree_refuses(tmp_path):
    """The directory exists and holds no files — still nothing examined."""
    proc = _run(tmp_path)
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_a_clean_tree_passes_and_states_its_denominator(tmp_path):
    """The accept case, and the disclosure that makes it meaningful.

    The count is on its OWN line, before the verdict.
    `gate_host_independence_check` compares the LAST non-empty line, and this
    gate walks the repo root, so its count legitimately differs between a
    working checkout and a fresh worktree (measured 3753 vs 3693 — run leftovers
    under benchmark-data/). Putting the count on the verdict line turned an
    honest disclosure into a host-dependent verdict.
    """
    (tmp_path / "a.v").write_text("module m; endmodule\n", encoding="utf-8")
    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "examined 1 file(s)" in proc.stdout, proc.stdout
    assert "VACUOUS_PASS" not in proc.stderr


def test_a_real_artefact_still_fails(tmp_path):
    """The reject case.

    Every change here makes the gate refuse more, so without this a program
    that refused everything would satisfy the tests above — and the 2 corpus
    projects with a genuine finding would be indistinguishable from the 38
    clean ones.
    """
    (tmp_path / "a.v").write_text("module m; endmodule\n", encoding="utf-8")
    (tmp_path / "w.vcd").write_text("$date $end\n", encoding="utf-8")
    proc = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "w.vcd" in proc.stdout


def test_the_count_tracks_the_tree(tmp_path):
    """A denominator that reports a constant discloses nothing.

    It also has to count what it WALKED, not what it FOUND — this gate's hit
    count is normally zero, so a count wired to the hits would read as zero on
    every clean tree and the refusal would fire on all 38 corpus projects.
    """
    (tmp_path / "a.v").write_text("module m; endmodule\n", encoding="utf-8")
    one = _run(tmp_path)
    (tmp_path / "b.v").write_text("module n; endmodule\n", encoding="utf-8")
    (tmp_path / "c.v").write_text("module o; endmodule\n", encoding="utf-8")
    three = _run(tmp_path)

    def count(proc):
        m = re.search(r"examined (\d+) file\(s\)", proc.stdout)
        assert m, f"no denominator in output: {proc.stdout!r}"
        return int(m.group(1))

    assert count(one) == 1, one.stdout
    assert count(three) == 3, three.stdout


def test_the_verdict_line_carries_no_count(tmp_path):
    """The last line is what the aggregator compares — it must be host-stable.

    Without this, moving the count back onto the verdict line passes every
    other test here and reintroduces the HOST_DEPENDENT_VERDICT finding.
    """
    (tmp_path / "a.v").write_text("module m; endmodule\n", encoding="utf-8")
    proc = _run(tmp_path)
    last = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1]
    assert last.startswith(("PASS", "FAIL")), last
    # The FINDING count may stay — it is a property of the tree's content and is
    # host-stable (a waveform artefact is either committed or it is not). What
    # must not appear is the DENOMINATOR, which counts every walked file and so
    # differs between a working checkout and a fresh worktree.
    assert "examined" not in last, (
        f"the verdict line carries the denominator: {last!r} — that line is "
        f"compared across trees and this gate walks the repo root")
    assert not re.search(r"\b\d{3,}\b", last), (
        f"the verdict line carries a large count: {last!r}")


def test_skipped_directories_are_not_counted(tmp_path):
    """`_SKIP_DIRS` content must not inflate the denominator.

    A count that included skipped trees would let an empty project with a
    `.git` directory look examined.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("waveform_probe", PROG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    skip = next(iter(mod._SKIP_DIRS))
    (tmp_path / skip).mkdir(parents=True)
    (tmp_path / skip / "x.v").write_text("module m; endmodule\n", encoding="utf-8")
    proc = _run(tmp_path)
    assert proc.returncode == 2, (
        f"a tree holding only skipped directories reported as examined: "
        f"{proc.stdout!r} {proc.stderr!r}")
