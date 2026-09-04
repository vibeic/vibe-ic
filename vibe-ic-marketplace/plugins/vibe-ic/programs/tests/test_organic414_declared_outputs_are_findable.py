#!/usr/bin/env python3
"""ORGANIC #414 — a reader following a ledger's own paths could not find most
of what it declares.

Measured on the three published spm deliverables, identical in each:

    declared 17 | at declared path 7 | hash mismatches 0 | not found 10

Corpus-wide it was worse than the issue reported, which only measured spm:
102 of 156 declared outputs across 21 tracked ledgers were unfollowable.

Splitting the missing ones BY DIGEST rather than by name — hashing every
tracked blob in the deliverable and looking for the declared digest — gives
two populations: 12 RELOCATED (the file ships, hashes exactly as declared,
under a name the ledger never mentions) and 90 that ship nowhere.

THREE THINGS THIS TEST FILE EXISTS TO PIN, each of which was a real bug in
the first version of the repair or the check:

  1. `outputs` IS NEVER MUTATED. Rewriting a relocated key to its new path
     dropped the corpus from 156 declared outputs to 153: three rows declare
     BOTH names (spm's row carries `spm.def` AND `routed.def`), so the
     rewrite collided and silently deleted a declaration. Repairing a ledger
     by deleting three of its entries is worse than the dangling pointer.
  2. PRESENCE MEANS TRACKED, judged from the INDEXED BLOB. Reading the
     working tree reported five HASH_MISMATCHes in
     `benchmark-data/ic/subservient` — "the file at the declared path is not
     the one the run recorded" — about a PUBLISHED deliverable. All five were
     UNTRACKED files a later local run had left behind. A clone has none of
     them.
  3. A RELOCATION IS ONLY EVER RECORDED WHEN A SHIPPED DIGEST EQUALS THE
     DECLARED ONE. The declared hash is never rewritten, so the repair cannot
     launder a changed file into a passing one.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _corpus_repo_view import corpus_repo
from _published_corpus import needs_corpus

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import provenance_declared_output_check as C  # noqa: E402

_H = "sha256:" + "0" * 64

_FROZEN_CELLS = {
    "ic/spm/v1.10.18_sky130A",
    "ic/spm/v1.14.88_gf180mcuD",
    "ic/spm/v1.5.65_sky130A",
    "protocol_parity/espi",
    "protocol_parity/interlaken",
    "protocol_parity/lpc",
    "protocol_parity/mdio",
    "protocol_parity/sgmii",
    "protocol_parity/usb_pd",
}


def _sha(b: bytes) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _cell(tmp_path: Path, files: dict, rows: list, track=True) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    cell = tmp_path / "benchmark-data" / "ic" / "x"
    cell.mkdir(parents=True)
    for rel, data in files.items():
        p = cell / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (cell / "provenance.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n")
    if track:
        subprocess.run(["git", "-C", str(tmp_path), "add", "-f",
                        "benchmark-data"], check=True)
    else:
        subprocess.run(["git", "-C", str(tmp_path), "add", "-f",
                        "benchmark-data/ic/x/provenance.jsonl"], check=True)
    return tmp_path


def test_a_present_output_that_hashes_as_declared_passes(tmp_path):
    repo = _cell(tmp_path, {"a.v": b"module a; endmodule\n"},
                 [{"outputs": {"a.v": _sha(b"module a; endmodule\n")}}])
    rep = C.audit(repo)
    assert rep["verdict"] == "PASS", rep["findings"]
    assert rep["cells"][0]["present"] == 1


def test_a_dangling_output_fails(tmp_path):
    repo = _cell(tmp_path, {}, [{"outputs": {"gone.v": _H}}])
    rep = C.audit(repo)
    assert any("DANGLING_OUTPUT" in f for f in rep["findings"]), rep["findings"]


def test_a_changed_file_at_the_declared_path_is_a_mismatch(tmp_path):
    repo = _cell(tmp_path, {"a.v": b"CHANGED\n"},
                 [{"outputs": {"a.v": _sha(b"original\n")}}])
    rep = C.audit(repo)
    assert any("HASH_MISMATCH" in f for f in rep["findings"]), rep["findings"]


def test_an_earlier_same_path_write_is_superseded_by_the_shipped_final_write(
        tmp_path):
    """An append-only ledger records both writes; a checkout holds the last.

    This is the real setup-STA then hold-STA shape.  No hash or row is erased:
    the earlier declaration is accounted for separately, and only because the
    indexed blob exactly matches the later declaration.
    """
    old, final = b"setup report\n", b"hold report\n"
    repo = _cell(tmp_path, {"sta.rpt": final}, [
        {"outputs": {"sta.rpt": _sha(old)}},
        {"outputs": {"sta.rpt": _sha(final)}},
    ])
    rep = C.audit(repo)
    assert rep["verdict"] == "PASS", rep["findings"]
    assert rep["cells"][0]["declared"] == 2
    assert rep["cells"][0]["present"] == 1
    assert rep["cells"][0]["superseded"] == ["sta.rpt"]


def test_a_later_same_path_row_cannot_hide_an_unmatched_shipped_blob(tmp_path):
    """A later declaration is proof only when its digest is what ships."""
    repo = _cell(tmp_path, {"sta.rpt": b"third unknown report\n"}, [
        {"outputs": {"sta.rpt": _sha(b"setup report\n")}},
        {"outputs": {"sta.rpt": _sha(b"hold report\n")}},
    ])
    rep = C.audit(repo)
    assert rep["verdict"] == "FAIL"
    assert len(rep["cells"][0]["hash_mismatch"]) == 2
    assert rep["cells"][0]["superseded"] == []


# ── the three bugs the first version had ────────────────────────────────────

def test_reconcile_never_mutates_outputs(tmp_path):
    """BUG 1. The row declares BOTH names, as spm's really does. Rewriting the
    relocated key collided and dropped a declaration — 156 -> 153 corpus-wide.
    """
    body = b"DEF CONTENT\n"
    rows = [{"outputs": {"pnr/routed.def": _sha(body),
                         "pnr/old.def": _sha(body)}}]
    repo = _cell(tmp_path, {"pnr/routed.def": body}, rows)
    before = json.loads(
        (repo / "benchmark-data/ic/x/provenance.jsonl").read_text())["outputs"]
    C.audit(repo, reconcile=True)
    after = json.loads(
        (repo / "benchmark-data/ic/x/provenance.jsonl").read_text())
    assert after["outputs"] == before, "the run's own record was rewritten"
    assert after["outputs_relocated_at_publish"] == {
        "pnr/old.def": "pnr/routed.def"}
    assert len(after["outputs"]) == 2, "a declaration was dropped"


def test_an_untracked_file_is_absent_not_mismatched(tmp_path):
    """BUG 2. Five PUBLISHED outputs in `subservient` were reported
    HASH_MISMATCH because a later local run had left untracked files at those
    paths. A clone has none of them; from the repository they are absent."""
    repo = _cell(tmp_path, {}, [{"outputs": {"a.v": _sha(b"declared\n")}}],
                 track=False)
    (repo / "benchmark-data/ic/x/a.v").write_bytes(b"local leftover\n")
    rep = C.audit(repo)
    assert not any("HASH_MISMATCH" in f for f in rep["findings"]), \
        rep["findings"]
    assert any("DANGLING_OUTPUT" in f for f in rep["findings"])


def test_reconcile_will_not_repoint_at_a_file_whose_digest_differs(tmp_path):
    """BUG 3, as a standing guard. A same-NAMED file elsewhere must not
    satisfy a declaration — only an equal DIGEST may, or the repair becomes a
    way to launder a changed artefact into a passing one."""
    repo = _cell(tmp_path, {"elsewhere/a.v": b"DIFFERENT\n"},
                 [{"outputs": {"pnr/a.v": _sha(b"original\n")}}])
    C.audit(repo, reconcile=True)
    row = json.loads(
        (repo / "benchmark-data/ic/x/provenance.jsonl").read_text())
    assert "outputs_relocated_at_publish" not in row
    assert row["outputs_pruned_at_publish"] == ["pnr/a.v"]
    assert row["outputs"]["pnr/a.v"] == _sha(b"original\n")


# ── the disclosure has to be load-bearing, not decorative ───────────────────

def test_a_relocation_marker_pointing_at_the_wrong_file_still_fails(tmp_path):
    """A disclosure nobody checks is a waiver. If the target does not ship
    with the declared digest, the marker must not rescue the row."""
    repo = _cell(tmp_path, {"b.v": b"OTHER\n"},
                 [{"outputs": {"a.v": _sha(b"declared\n")},
                   "outputs_relocated_at_publish": {"a.v": "b.v"}}])
    rep = C.audit(repo)
    assert rep["verdict"] == "FAIL"
    assert any("does not ship with that digest" in f for f in rep["findings"])


def test_a_pruned_marker_satisfies_the_gate(tmp_path):
    repo = _cell(tmp_path, {}, [{"outputs": {"a.v": _H},
                                 "outputs_pruned_at_publish": ["a.v"]}])
    assert C.audit(repo)["verdict"] == "PASS"


def test_git_refusing_to_list_is_an_ERROR_not_a_PASS(tmp_path, capsys):
    (tmp_path / "nope").mkdir()
    assert C.main(["--repo", str(tmp_path / "nope")]) == 2
    assert "NOT a clean result" in capsys.readouterr().out


# ── the published corpus ────────────────────────────────────────────────────
#
# WHERE THESE TWO READ FROM (the 2026-08 split). A declared output is a claim
# made by a PUBLISHED cell, and the cells moved to `vibeic/benchmark-data`.
# `C.audit` enumerates with `git ls-files benchmark-data` and judges the INDEXED
# blob, so it can only be aimed at a repository that TRACKS the cells under that
# prefix; `corpus_repo` supplies one — this checkout when it still carries them,
# otherwise a zero-copy view of the clone named by `$VIBE_IC_BENCHMARK_DATA`.
#
# Aimed at this checkout after the split, the first failed on `declared == 0`
# ("the corpus lost 156 declarations") and the second passed VACUOUSLY, because
# `0 + 0 == 0` satisfies it over an empty population — a green report from a
# check that read nothing, which is the exact shape this whole file is against.
# Frozen benchmark-data 8c4b608 carries 9 ledgers and 93 declarations:
# 53 present + 38 pruned + 2 superseded.  The former 156 floor described
# withdrawn failing result cells and could only be satisfied by republishing
# them.  The current population is pinned as the exact five-part tuple; unlike
# a lowered floor it cannot absorb a deletion, addition or substitution by
# count, and the accounting equality below still forbids deleting a declaration
# to buy a pass.

@needs_corpus
def test_the_published_corpus_is_followable_today(tmp_path):
    rep = C.audit(corpus_repo(tmp_path))
    assert rep["verdict"] == "PASS", rep["findings"][:8]
    decl = sum(c["declared"] for c in rep["cells"])
    pres = sum(c["present"] for c in rep["cells"])
    pruned = sum(len(c["pruned"]) for c in rep["cells"])
    superseded = sum(len(c["superseded"]) for c in rep["cells"])
    cells = {c["cell"].split("/benchmark-data/", 1)[-1]
             for c in rep["cells"]}
    assert cells == _FROZEN_CELLS, (
        sorted(cells - _FROZEN_CELLS), sorted(_FROZEN_CELLS - cells))
    assert (len(rep["cells"]), decl, pres, pruned, superseded) == (
        9, 93, 53, 38, 2), (
            len(rep["cells"]), decl, pres, pruned, superseded)


@needs_corpus
def test_no_declaration_was_lost_in_the_repair(tmp_path):
    """The count is the witness for BUG 1 on the real data: 156 before the
    repair, 156 after. A repair that improves a gate by deleting rows is the
    failure this whole family is about."""
    rep = C.audit(corpus_repo(tmp_path))
    decl = sum(c["declared"] for c in rep["cells"])
    pres = sum(c["present"] for c in rep["cells"])
    pruned = sum(len(c["pruned"]) for c in rep["cells"])
    superseded = sum(len(c["superseded"]) for c in rep["cells"])
    assert pres + pruned + superseded == decl, (
        pres, pruned, superseded, decl)
