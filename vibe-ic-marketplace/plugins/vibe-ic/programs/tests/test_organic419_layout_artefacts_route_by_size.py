#!/usr/bin/env python3
"""ORGANIC #419 — five mechanisms disagreed about which layout artefacts ship.

Each was locally reasonable and no two agreed:

  1. `.gitignore` ignored `*.gds`/`*.def` at the root and NEGATED them back
     for `benchmark-data/ic/**`; `*.spef`/`*.oas` were never ignored at all.
  2. The comment beside that negation said a size guard in
     `benchmark_evidence_structure_check` would stop files over 50 MB. No such
     guard existed — the sentence was the entire implementation.
  3. `benchmark_evidence_publish` dropped all four by EXTENSION, so a cell
     published by the program carried LESS evidence than the hand-staged
     cells it replaced.
  4. Its docstring justified that as gitignored-or-too-large, false by then
     on both counts.
  5. `NO_RAW_GEOMETRY` failed any cell carrying one — and so failed ALL THREE
     reference cells, the most complete evidence this repository publishes.

MEASURED before choosing a ceiling: the largest tracked blob is 26.75 MB and
exactly one exceeds 20 MB, so 50 MB starts with zero debt and needs no
baseline. Ten UNTRACKED `.gds` under `benchmark-data/ic` are 74–105 MB and are
accepted by the negation; two exceed GitHub's 100 MB hard limit.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import size_policy_drift_check as D  # noqa: E402
import tracked_blob_size_guard as G  # noqa: E402

_REPO = _PROGRAMS.parents[3]


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    return tmp_path


def _add(repo: Path, rel: str, size: int):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as fh:
        fh.truncate(size)                    # sparse: st_size without the disk
    subprocess.run(["git", "-C", str(repo), "add", "-f", rel], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"], check=True)


# ── the size guard that was promised and never written ──────────────────────

def test_an_oversized_tracked_blob_fails(tmp_path):
    r = _repo(tmp_path)
    _add(r, "big.gds", 51 * 1000 * 1000)
    big, seen = G.oversized(r)
    assert [p for p, _ in big] == ["big.gds"]
    assert seen == 1


def test_a_blob_under_the_ceiling_passes(tmp_path):
    """The paired half — without it, "reports nothing" is satisfied by a gate
    that looks at nothing."""
    r = _repo(tmp_path)
    _add(r, "small.gds", 1000 * 1000)
    big, seen = G.oversized(r)
    assert big == [] and seen == 1


def test_the_hard_limit_is_called_out_separately(tmp_path, capsys):
    """Over 100 MB the push is REJECTED, not warned about. A reader needs to
    know which side of that line they are on."""
    r = _repo(tmp_path)
    _add(r, "huge.gds", 105 * 1000 * 1000)
    assert G.main(["--repo", str(r)]) == 1
    out = capsys.readouterr().out
    assert "HARD LIMIT" in out and "git-lfs" in out


def test_git_refusing_to_list_is_an_ERROR_not_a_PASS(tmp_path, capsys):
    """An empty list reads as "nothing is oversized" — the #416 lesson."""
    (tmp_path / "not_a_repo").mkdir()
    assert G.main(["--repo", str(tmp_path / "not_a_repo")]) == 2
    out = capsys.readouterr().out
    assert "NOT a clean result" in out and "[PASS]" not in out


def test_the_guard_runs_from_any_directory(tmp_path):
    """#416 again: `git ls-tree` honours the cwd prefix, so a guard anchored
    to `.` silently checks a subtree."""
    r = _repo(tmp_path)
    _add(r, "sub/deep/big.gds", 51 * 1000 * 1000)
    assert G.oversized(r)[0] == G.oversized(r / "sub")[0]


def test_this_repo_is_under_the_ceiling_today():
    """The measurement the ceiling was chosen from. If this ever fails, the
    ceiling did not start clean and the finding above is stale."""
    big, seen = G.oversized(_REPO)
    assert big == [], big
    assert seen > 10000, seen


# ── the drift check ─────────────────────────────────────────────────────────

def test_the_shipped_policy_is_self_consistent():
    rep = D.audit(_PROGRAMS, _REPO / ".gitignore")
    assert rep["verdict"] == "PASS", rep["findings"]
    assert len(rep["ceilings"]) == 3


def test_a_ceiling_that_disagrees_is_caught(tmp_path):
    for name in ("tracked_blob_size_guard.py", "benchmark_evidence_publish.py",
                 "benchmark_evidence_structure_check.py"):
        (tmp_path / name).write_text(
            (_PROGRAMS / name).read_text(errors="replace"))
    p = tmp_path / "benchmark_evidence_publish.py"
    p.write_text(p.read_text().replace(
        "_SIZE_CEILING = 50 * 1000 * 1000", "_SIZE_CEILING = 9 * 1000 * 1000"))
    rep = D.audit(tmp_path, _REPO / ".gitignore")
    assert any(f.startswith("CEILING_DISAGREEMENT") for f in rep["findings"]), \
        rep["findings"]


def test_losing_the_gitignore_negation_is_caught(tmp_path):
    gi = tmp_path / ".gitignore"
    gi.write_text("*.gds\n*.def\n")
    rep = D.audit(_PROGRAMS, gi)
    assert sum(f.startswith("GITIGNORE_REVERTED") for f in rep["findings"]) == 2


def test_reverting_to_an_extension_only_rule_is_caught(tmp_path):
    """The specific regression: someone deletes the size ceiling and puts the
    extension drop back, which is what the code did before #419."""
    for name in ("tracked_blob_size_guard.py", "benchmark_evidence_publish.py",
                 "benchmark_evidence_structure_check.py"):
        (tmp_path / name).write_text(
            (_PROGRAMS / name).read_text(errors="replace"))
    p = tmp_path / "benchmark_evidence_structure_check.py"
    p.write_text(p.read_text().replace("_SIZE_CEILING = 50 * 1000 * 1000", ""))
    rep = D.audit(tmp_path, _REPO / ".gitignore")
    assert any(f.startswith("NO_CEILING") for f in rep["findings"]), \
        rep["findings"]


# ── the reference cells, which the old rule rejected ────────────────────────

@pytest.mark.parametrize("cell", ["v1.5.58_ihp-sg13g2", "v1.5.65_sky130A",
                                  "v1.5.66_gf180mcuD"])
def test_the_three_reference_cells_pass_their_own_structure_check(cell):
    """Every one of them FAILED on NO_RAW_GEOMETRY before #419, naming the
    .gds/.def/.spef the repository had already decided to accept."""
    d = _REPO / "benchmark-data" / "ic" / "spm" / cell
    if not d.is_dir():
        pytest.skip("published cell not present")
    r = subprocess.run(
        [sys.executable,
         str(_PROGRAMS / "benchmark_evidence_structure_check.py"), str(d)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
