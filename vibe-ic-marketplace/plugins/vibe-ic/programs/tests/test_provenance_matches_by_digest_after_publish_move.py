#!/usr/bin/env python3
"""A published artefact that MOVED is still the artefact the run declared.

`provenance_check` matched an output to its log entry by PATH only. The
publisher relocates artefacts, so a path-only match calls a published GDS
undeclared the moment it is copied out of the run directory.

MEASURED on the published corpus, three cells:

    provenance.jsonl records   phase3/stage3/pnr/<top>.gds
    the tree ships             phase3/stage4/gds/<top>.gds
    sha256                     BYTE-IDENTICAL in both places

The run declared exactly this artefact; only its address changed. Wiring
`provenance_check` into Step 37 without this would have turned three published
cells FAIL for a move, and a reader would have gone looking for a tampered GDS
that does not exist.

THIS IS #448's ROUTED_AWAY DISTINCTION applied to provenance instead of
citations: "stored elsewhere" is not "never produced". The digest is the
stronger key anyway — a path match carrying a DIFFERENT digest is a different
file wearing the right name, and the pair of tests below pins that it is still
rejected.

CAUGHT BY MUTATION, not by design: neutering the digest branch reddened ZERO
existing tests while visibly changing behaviour on real data. This file is why
that can no longer happen.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import provenance_check as PC  # noqa: E402

_CORPUS = _PROGRAMS.parents[3] / "benchmark-data" / "ic"
_PROG = _PROGRAMS / "provenance_check.py"


def _entry(path: str, digest: str, tool: str = "magic") -> dict:
    return {"tool": tool, "exit_code": 0, "timestamp": "2026-01-01T00:00:00Z",
            "outputs": {path: digest}}


# ── the predicate ──────────────────────────────────────────────────────────
def test_a_moved_artefact_is_declared_by_its_digest():
    """THE LOAD-BEARING CASE — the published shape."""
    d = "sha256:" + "a" * 64
    e = _entry("phase3/stage3/pnr/top.gds", d)
    assert PC._declares(e, "phase3/stage4/gds/top.gds", d) is True


def test_the_same_path_still_matches():
    """The path route must keep working; the digest is an addition."""
    d = "sha256:" + "b" * 64
    e = _entry("phase3/stage4/gds/top.gds", d)
    assert PC._declares(e, "phase3/stage4/gds/top.gds", d) is True


def test_a_different_digest_at_a_different_path_is_NOT_declared():
    """PAIRED HALF #1 — the whole point. A move is forgiven; a substitution
    is not."""
    e = _entry("phase3/stage3/pnr/top.gds", "sha256:" + "a" * 64)
    assert PC._declares(e, "phase3/stage4/gds/top.gds",
                        "sha256:" + "c" * 64) is False


def test_no_digest_available_falls_back_to_path_only():
    """When the caller cannot supply a digest, the check must not silently
    accept anything — it degrades to the old path rule, not to True."""
    e = _entry("phase3/stage3/pnr/top.gds", "sha256:" + "a" * 64)
    assert PC._declares(e, "phase3/stage4/gds/top.gds", None) is False


def test_both_sides_are_normalised():
    """`_sha256_file` emits `sha256:<hex>` and the log records the same, so a
    one-sided strip compares a bare digest against a prefixed one and never
    matches. This cost me a debugging round; it is pinned here."""
    bare = "d" * 64
    e = _entry("other/path.gds", "sha256:" + bare)
    assert PC._declares(e, "published/path.gds", bare) is True
    assert PC._declares(e, "published/path.gds", "sha256:" + bare) is True


def test_bare_digest_helper_is_idempotent():
    assert PC._bare_digest("sha256:" + "e" * 64) == "e" * 64
    assert PC._bare_digest("e" * 64) == "e" * 64
    assert PC._bare_digest(None) == ""


# ── end to end, because the predicate passing is not the whole path ───────
def _project(tmp_path: Path, logged_path: str, ship_bytes: bytes,
             logged_digest: str) -> Path:
    d = tmp_path / "proj"
    (d / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (d / "phase3" / "stage4" / "gds" / "top.gds").write_bytes(ship_bytes)
    (d / "provenance.jsonl").write_text(
        json.dumps(_entry(logged_path, logged_digest)) + "\n")
    return d


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(_PROG), str(project),
         "--output=phase3/stage4/gds/*.gds", "--tool=magic"],
        capture_output=True, text=True)


def test_end_to_end_a_moved_artefact_passes(tmp_path):
    """The KeyError I introduced and caught: the predicate matched, then the
    downstream lookup still indexed `outputs[out_rel]` and crashed. A
    successful match must not become a traceback."""
    body = b"GDS BYTES\n"
    import hashlib
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    p = _project(tmp_path, "phase3/stage3/pnr/top.gds", body, digest)
    r = _run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_end_to_end_a_tampered_artefact_still_fails(tmp_path):
    """PAIRED HALF #2, end to end. Same logged path, different bytes."""
    import hashlib
    digest = "sha256:" + hashlib.sha256(b"THE REAL BYTES\n").hexdigest()
    p = _project(tmp_path, "phase3/stage3/pnr/top.gds", b"TAMPERED\n", digest)
    r = _run(p)
    assert r.returncode == 1, r.stdout + r.stderr


# ── real data ──────────────────────────────────────────────────────────────
def test_the_published_cells_that_moved_their_gds_resolve():
    """The three cells that motivated this. Without the digest route they
    report the GDS as undeclared — a FAIL for a publish-time move."""
    cells = ["spm/v1.5.58_ihp-sg13g2", "spm/v1.10.18_sky130A",
             "spm/v1.9.96_gf180mcuD"]
    seen, absent = 0, []
    for name in cells:
        d = _CORPUS / name
        if not (d / "provenance.jsonl").is_file():
            absent.append(name)
            continue
        gds = list((d / "phase3" / "stage4" / "gds").glob("*.gds"))
        if not gds:
            absent.append(f"{name} (no GDS)")
            continue
        seen += 1
        r = subprocess.run(
            [sys.executable, str(_PROG), str(d),
             "--output=phase3/stage4/gds/*.gds",
             "--tool=klayout,magic,openroad"],
            capture_output=True, text=True)
        assert r.returncode == 0, (name, r.stdout + r.stderr)
    if seen == 0:
        pytest.skip("published corpus not checked out")
    # DERIVED FROM THE ROSTER ABOVE, not typed beside it. The literal `3` was
    # `len(cells)` written a second time, so editing the roster silently made
    # the two disagree — and when a cell was withdrawn the message said "only 2
    # of 3" without naming which. The claim is unchanged: this test names
    # specific cells and a missing one is a real finding, not a smaller run.
    assert seen == len(cells), (
        f"{len(absent)} of the {len(cells)} cell(s) this test names are no "
        f"longer published: {absent}. Either they were withdrawn — in which "
        f"case pick their successors — or the roster is stale.")
