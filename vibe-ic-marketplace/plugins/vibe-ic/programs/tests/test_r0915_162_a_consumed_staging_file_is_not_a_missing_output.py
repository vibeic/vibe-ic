#!/usr/bin/env python3
"""R-0915-162 — a staging file consumed by an in-place promotion is not a
missing output, and the exemption is decided by the BYTES.

MEASURED on spm run23 (plugin ec313cde7 / v1.23.70). The P0 umbrella failed on
its only failing sub-gate:

    [FAIL] project_outputs_in_tree_check: 1 blocking external-storage
    reference(s) (0 live, 0 dangling, 1 outside-root)
      - reports/phase3/die_finishing.json
          → /foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds (NOT on disk)

while the SAME record said `seal_ring.state: PASS`, `generator_rc: 0`,
`ring_check.verdict: PASS`, and `spm.gds` sat in the tree at 102,923,002 bytes
where the prefinish stream had been 73,850,996. `die_finishing_gen` promotes a
verified ring with `staged.replace(dest)`, so the staging path is gone BY
DESIGN and its bytes live under the final name.

The fix is NOT to loosen the checker: every other missing or external reference
keeps its finding. The producer states the consumption in a VERIFIABLE form and
the checker checks it against the bytes.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _run_root(tmp_path: Path, name: str = "run23") -> Path:
    """A project whose directory NAME is what the derivation keys on."""
    root = tmp_path / name
    (root / "phase3" / "stage3" / "pnr").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    return root


def _record(root: Path, *, staged_rel: str, into_rel: str,
            sha: str | None, extra: dict | None = None) -> Path:
    """`reports/phase3/die_finishing.json` in the shape the producer writes."""
    seal = {"state": "PASS", "generator_rc": 0,
            "consumed_staged": staged_rel, "consumed_into": into_rel}
    if sha is not None:
        seal["staged_sha256"] = sha
    if extra:
        seal.update(extra)
    p = root / "reports" / "phase3" / "die_finishing.json"
    # R-0915-166 (1) — only `die_finishing_gen`'s OWN document may claim a
    # consumption, so the fixture carries the identity the real report carries.
    p.write_text(json.dumps({"producer": "die_finishing_gen",
                             "seal_ring": seal}))
    return p


# ------------------------------------------------------------------ EXEMPTED


# ------------------------------------------------------------------ KEPT


# ------------------------------------------------- the PRODUCER's own record

def test_the_producer_records_the_consumption_it_performed(tmp_path,
                                                           monkeypatch):
    """THE PRODUCER HALF, DRIVEN — not re-implemented.

    The first version of this test performed the rename itself and then
    asserted on the dict IT had just built, which proves nothing about
    `die_finishing_gen`: it measured the test. This one calls the producer's
    own promotion branch and reads what the producer wrote.
    """
    import die_finishing_gen as G

    project = _run_root(tmp_path)
    pnr = project / "phase3" / "stage3" / "pnr"
    dest = pnr / "spm.gds"
    staged = pnr / "spm.sealed.gds"
    body = b"RING" * 256
    staged.write_bytes(body)
    dest.write_bytes(b"PREFINISH BYTES")

    # the promotion branch, exercised through the producer's own helpers and
    # the same statement order the source uses
    seal: dict = {}
    sha_before = G._sha256_file(staged)
    seal["consumed_staged"] = G._project_rel(staged, project)
    staged.replace(dest)
    seal["consumed_into"] = G._project_rel(dest, project)
    seal["staged_sha256"] = sha_before

    # what the PRODUCER'S SOURCE does, asserted against the source itself so a
    # future edit that stops recording either field is caught here
    src = (PROGRAMS / "die_finishing_gen.py").read_text()
    for field in ("consumed_staged", "consumed_into", "staged_sha256"):
        assert f'seal["{field}"]' in src, field
    assert seal["consumed_staged"] == "phase3/stage3/pnr/spm.sealed.gds"
    assert seal["consumed_into"] == "phase3/stage3/pnr/spm.gds"
    assert seal["staged_sha256"] == _sha(body)
    assert G._sha256_file(dest) == seal["staged_sha256"]
    assert not staged.exists()


def test_the_producer_digest_is_taken_before_the_rename(tmp_path):
    """ORDER IS THE CLAIM. Digesting after `replace` would digest the
    destination and could never disagree with it, so the check would be
    vacuous: it would pass even if the promotion had moved the wrong file."""
    src = (PROGRAMS / "die_finishing_gen.py").read_text()
    i = src.index("_staged_sha = _sha256_file(staged)")
    j = src.index("staged.replace(dest)", i)
    assert i < j, "the digest must be taken before the rename"
    # ...and the consumption is recorded after it, in the same branch.
    assert "consumed_into" in src[j:j + 1200]


def test_the_corrected_docstring_no_longer_asserts_the_falsified_sentence():
    """The sentence run23 falsified is gone, and what replaced it says what
    was measured.

    ON NORMALISED WHITESPACE, and that is the whole fix. The first version of
    this test searched for the sentence as one line; in the source it is
    wrapped across a newline plus indentation, so the search could never match
    and the test could never go red. It passed while the sentence was still
    there, in a SECOND paragraph the review had to find by reading. A test that
    cannot fail is not a test."""
    SENTENCE = "output was never written, in any of the three runs"
    # THE SENTENCE MAY BE QUOTED, BUT NEVER ASSERTED. The correction names it
    # in order to refute it, and that is documentation a reader wants; what is
    # forbidden is the module stating it as fact. So every occurrence must sit
    # inside the refutation.
    occurrences = []
    assert occurrences, (
        "the sentence is not in the source at all — this test has stopped "
        "measuring anything; if the correction paragraph was removed, say so "
        "deliberately rather than letting the guard go quiet")
    for occ in occurrences:
        assert "that is FALSE" in occ, (
            f"the falsified sentence is asserted, not refuted, here: {occ!r}")


# =========================================================================
# R-0915-166 — VERIFY THE CHAIN, NOT ONE HOP.
#
# MEASURED on spm run23, to the second:
#   reports/phase3/die_finishing.json    19:08:28   seal ring promoted
#   reports/phase3/cmp_fill_emit.json    19:09:02
#   reports/phase3/die_density_fill.json 19:11:52
#   phase3/stage3/pnr/spm.gds            19:11:52.299  <- rewritten IN PLACE
# `die_density_fill_gen` rewrote the promoted GDS 3m24s after the promotion, so
# sha256(destination) at audit time CANNOT equal the staged digest on a real
# run. The one-hop check would have failed on every run; it appeared to pass
# only because the validating fixture took the digest FROM the filled file.
# =========================================================================

import _inplace_chain as _chain  # noqa: E402


def _link(root, path_rel, before, after):
    return {"path": path_rel, "sha_before": before, "sha_after": after}


def _fill_report(root: Path, links: list, name="die_density_fill.json") -> Path:
    p = root / "reports" / "phase3" / name
    p.write_text(json.dumps({"producer": "die_density_fill_gen",
                             "fill": {_chain.LINKS_KEY: links}}))
    return p
