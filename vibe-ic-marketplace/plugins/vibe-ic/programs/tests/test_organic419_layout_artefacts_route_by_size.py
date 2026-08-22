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

from _published_corpus import cell_dirs, needs_corpus

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import size_policy_drift_check as D  # noqa: E402
import tracked_blob_size_guard as G  # noqa: E402

_REPO = _PROGRAMS.parents[3]


def _tracked_blobs_at_head(repo: Path) -> int:
    """How many blobs git holds at HEAD, counted WITHOUT the guard.

    Deliberately not `git ls-files`: that reads the INDEX, which a staged edit
    moves independently of HEAD, and the guard weighs HEAD.
    """
    r = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--full-tree", "HEAD"],
        capture_output=True, text=True, check=True)
    return sum(1 for line in r.stdout.splitlines()
               if line.split("\t", 1)[0].split()[1:2] == ["blob"])


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
    ceiling did not start clean and the finding above is stale.

    NOT A CORPUS TEST, and deliberately not marked as one. Its subject is what
    THIS repository tracks, and every blob it weighs is still here — read the
    failure before assuming the cause: `big == []` never stopped holding. What
    broke at the 2026-08 split was the population floor `seen > 10000`, a
    constant measured when the published cells lived in this tree (21967 tracked
    entries then, 5298 now that the result cells are in `vibeic/benchmark-data`).
    Pointing `$VIBE_IC_BENCHMARK_DATA` at a clone does not put them back, so a
    skip keyed on the corpus would fire forever and the guard would never run
    again.

    The floor is asked of the tree instead of pinned to a number, which is also
    why it cannot go stale a second time: every blob git lists at HEAD must have
    been weighed. That is strictly stronger than a threshold — a guard that
    enumerated a subtree (the #416 bug) or dropped rows while parsing fails it,
    and those are the ways `big == []` becomes a lie.
    """
    big, seen = G.oversized(_REPO)
    assert big == [], big
    tracked = _tracked_blobs_at_head(_REPO)
    assert seen == tracked, (
        f"the guard weighed {seen} blob(s) but git holds {tracked} at HEAD — "
        f"it did not look at the whole tree, so `no oversized blob` is not a "
        f"result")
    assert tracked > 1000, (
        f"only {tracked} tracked blob(s): this is not a populated repository, "
        f"and a clean answer over it means nothing")


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

@needs_corpus
def test_the_reference_cells_pass_their_own_structure_check():
    """Every one of them FAILED on NO_RAW_GEOMETRY before #419, naming the
    .gds/.def/.spef the repository had already decided to accept.

    DRIVEN BY THE CORPUS RATHER THAN BY THREE HARD-CODED NAMES. This was
    `@parametrize("cell", ["v1.5.58_ihp-sg13g2", "v1.5.65_sky130A",
    "v1.9.96_gf180mcuD"])` with an inline `skip("published cell not present")`,
    which after the 2026-08 split skipped all three every run and said nothing
    about why or where the cells went. Worse, it would have gone on skipping
    per-name even with a corpus supplied: a published snapshot legitimately
    carries a different set (today's holds `v1.10.18_sky130A` where the issue
    measured `v1.5.65_sky130A`), and a name-keyed skip turns that into silence.

    So the population is whatever spm cells the corpus publishes, and it is
    asserted non-empty — the check runs on all of them or the test fails. The
    one skip left is `needs_corpus`: no corpus, no cells to check, said in the
    suite's single wording.
    """
    cells = [c for c in cell_dirs() if c.parent.name == "spm"]
    assert len(cells) >= 3, (
        f"the corpus publishes {len(cells)} spm cell(s); #419 was measured on "
        f"three reference cells and this is the population that carries the "
        f"raw geometry the old NO_RAW_GEOMETRY rule rejected: "
        f"{[str(c) for c in cells]}")
    for d in cells:
        r = subprocess.run(
            [sys.executable,
             str(_PROGRAMS / "benchmark_evidence_structure_check.py"), str(d)],
            capture_output=True, text=True)
        assert r.returncode == 0, (d, r.stdout)
