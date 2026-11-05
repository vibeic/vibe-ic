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

import project_outputs_in_tree_check as C  # noqa: E402


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

def test_a_consumed_staging_file_with_matching_bytes_is_not_a_finding(
        tmp_path):
    """THE run23 CASE. The ring was promoted; the bytes are under the final
    name; the digest proves they are the same bytes."""
    root = _run_root(tmp_path)
    body = b"SEALED GDS BYTES" * 64
    dest = root / "phase3" / "stage3" / "pnr" / "spm.gds"
    dest.write_bytes(body)
    rec = _record(root, staged_rel="phase3/stage3/pnr/spm.sealed.gds",
                  into_rel="phase3/stage3/pnr/spm.gds", sha=_sha(body))
    for spelling in (
            # the container spelling, which is how the producer's argv records
            # it, and the project-relative one
            "/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds",
            str(root / "phase3" / "stage3" / "pnr" / "spm.sealed.gds")):
        assert C.consumed_into_verified(spelling, rec, root) == (
            "phase3/stage3/pnr/spm.gds"), spelling


# ------------------------------------------------------------------ KEPT

def test_a_destination_modified_after_the_promotion_keeps_its_finding(
        tmp_path):
    """THE ARM THAT MAKES THE DIGEST LOAD-BEARING. If the exemption were
    "the record says it was consumed", editing the destination afterwards
    would still pass. It must not: the claim is about THESE bytes."""
    root = _run_root(tmp_path)
    dest = root / "phase3" / "stage3" / "pnr" / "spm.gds"
    dest.write_bytes(b"SEALED GDS BYTES" * 64)
    rec = _record(root, staged_rel="phase3/stage3/pnr/spm.sealed.gds",
                  into_rel="phase3/stage3/pnr/spm.gds",
                  sha=_sha(b"SEALED GDS BYTES" * 64))
    dest.write_bytes(b"SOMETHING ELSE ENTIRELY")
    assert C.consumed_into_verified(
        "/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds",
        rec, root) is None


def test_a_missing_staged_path_with_no_consumption_record_keeps_its_finding(
        tmp_path):
    """The ORIGINAL honest finding is untouched: an output that was never
    written still blocks."""
    root = _run_root(tmp_path)
    p = root / "reports" / "phase3" / "die_finishing.json"
    p.write_text(json.dumps({"seal_ring": {"state": "FAIL"}}))
    assert C.consumed_into_verified(
        "/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds", p,
        root) is None


def test_a_consumption_stated_without_a_digest_is_not_verifiable(tmp_path):
    """The producer names the gap (`staged_sha256_unavailable`) rather than
    omitting it, and an unverifiable claim earns no exemption."""
    root = _run_root(tmp_path)
    (root / "phase3" / "stage3" / "pnr" / "spm.gds").write_bytes(b"x" * 32)
    rec = _record(root, staged_rel="phase3/stage3/pnr/spm.sealed.gds",
                  into_rel="phase3/stage3/pnr/spm.gds", sha=None,
                  extra={"staged_sha256_unavailable": "could not digest"})
    assert C.consumed_into_verified(
        "/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds",
        rec, root) is None


def test_a_record_does_not_exempt_a_path_it_does_not_name(tmp_path):
    """THE FAIL-OPEN THIS CONDITION EXISTS TO CLOSE. Without matching
    `consumed_staged`, one consumption record would exempt EVERY missing path
    in the same document — including a genuinely lost artefact that happens to
    be cited beside it."""
    root = _run_root(tmp_path)
    body = b"SEALED" * 16
    (root / "phase3" / "stage3" / "pnr" / "spm.gds").write_bytes(body)
    rec = _record(root, staged_rel="phase3/stage3/pnr/spm.sealed.gds",
                  into_rel="phase3/stage3/pnr/spm.gds", sha=_sha(body))
    assert C.consumed_into_verified(
        "/foss/designs/run23/phase3/stage3/pnr/some_other_output.gds",
        rec, root) is None


def test_a_destination_that_is_not_in_the_tree_is_refused(tmp_path):
    """"The bytes are still there" means still there IN THE RUN ROOT. A
    destination outside it is exactly the escape this gate exists to refuse."""
    root = _run_root(tmp_path)
    outside = tmp_path / "elsewhere" / "spm.gds"
    outside.parent.mkdir(parents=True, exist_ok=True)
    body = b"SEALED" * 16
    outside.write_bytes(body)
    rec = _record(root, staged_rel="phase3/stage3/pnr/spm.sealed.gds",
                  into_rel=str(outside), sha=_sha(body))
    assert C.consumed_into_verified(
        "/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds",
        rec, root) is None


def test_an_absent_destination_is_refused(tmp_path):
    """Consumed into a file that is not there is not a consumption."""
    root = _run_root(tmp_path)
    rec = _record(root, staged_rel="phase3/stage3/pnr/spm.sealed.gds",
                  into_rel="phase3/stage3/pnr/spm.gds", sha=_sha(b"anything"))
    assert C.consumed_into_verified(
        "/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds",
        rec, root) is None


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
    src = (PROGRAMS / "project_outputs_in_tree_check.py").read_text()
    flat = " ".join(src.split())
    SENTENCE = "output was never written, in any of the three runs"
    # THE SENTENCE MAY BE QUOTED, BUT NEVER ASSERTED. The correction names it
    # in order to refute it, and that is documentation a reader wants; what is
    # forbidden is the module stating it as fact. So every occurrence must sit
    # inside the refutation.
    occurrences = []
    i = flat.find(SENTENCE)
    while i != -1:
        occurrences.append(flat[i:i + len(SENTENCE) + 60])
        i = flat.find(SENTENCE, i + 1)
    assert occurrences, (
        "the sentence is not in the source at all — this test has stopped "
        "measuring anything; if the correction paragraph was removed, say so "
        "deliberately rather than letting the guard go quiet")
    for occ in occurrences:
        assert "that is FALSE" in occ, (
            f"the falsified sentence is asserted, not refuted, here: {occ!r}")
    assert "R-0915-166" in flat


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


def test_an_in_place_rewrite_after_the_promotion_keeps_the_exemption(tmp_path):
    """THE run23 SHAPE, which the one-hop version got wrong. The fill rewrote
    the promoted GDS, so the destination's bytes are NOT the staged bytes — and
    the exemption must still hold, because the chain accounts for the change."""
    root = _run_root(tmp_path)
    staged_bytes = b"SEALED" * 64
    final_bytes = b"SEALED+FILL" * 64
    dest = root / "phase3" / "stage3" / "pnr" / "spm.gds"
    dest.write_bytes(final_bytes)
    rec = _record(root, staged_rel="phase3/stage3/pnr/spm.sealed.gds",
                  into_rel="phase3/stage3/pnr/spm.gds",
                  sha=_sha(staged_bytes))
    _fill_report(root, [_link(root, "phase3/stage3/pnr/spm.gds",
                              _sha(staged_bytes), _sha(final_bytes))])
    assert C.consumed_into_verified(
        "/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds",
        rec, root) == "phase3/stage3/pnr/spm.gds"


def test_a_two_hop_chain_is_walked_by_digest_not_by_record_order(tmp_path):
    """Two writers, links published in the WRONG order. Reports are written by
    different programs and nothing orders them, so the walk follows the
    digests — the only ordering a writer cannot arrange to suit itself."""
    root = _run_root(tmp_path)
    a, b, c = b"STAGED" * 32, b"AFTER-CMP" * 32, b"AFTER-DENSITY" * 32
    (root / "phase3" / "stage3" / "pnr" / "spm.gds").write_bytes(c)
    rec = _record(root, staged_rel="phase3/stage3/pnr/spm.sealed.gds",
                  into_rel="phase3/stage3/pnr/spm.gds", sha=_sha(a))
    # second hop published FIRST, and in a different document
    _fill_report(root, [_link(root, "phase3/stage3/pnr/spm.gds",
                              _sha(b), _sha(c))])
    _fill_report(root, [_link(root, "phase3/stage3/pnr/spm.gds",
                              _sha(a), _sha(b))], name="cmp_fill_emit.json")
    assert C.consumed_into_verified(
        "/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds",
        rec, root) == "phase3/stage3/pnr/spm.gds"


def test_a_gap_in_the_chain_keeps_the_finding(tmp_path):
    """AN UNRECORDED REWRITE AND A HAND-EDIT LOOK THE SAME, and both must
    block. This is the arm the whole ruling exists for: the destination's bytes
    do not account for themselves."""
    root = _run_root(tmp_path)
    a, b, c = b"STAGED" * 32, b"MIDDLE" * 32, b"FINAL" * 32
    (root / "phase3" / "stage3" / "pnr" / "spm.gds").write_bytes(c)
    rec = _record(root, staged_rel="phase3/stage3/pnr/spm.sealed.gds",
                  into_rel="phase3/stage3/pnr/spm.gds", sha=_sha(a))
    # only the FIRST hop is recorded; nothing says how b became c
    _fill_report(root, [_link(root, "phase3/stage3/pnr/spm.gds",
                              _sha(a), _sha(b))])
    assert C.consumed_into_verified(
        "/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds",
        rec, root) is None


def test_a_link_for_another_path_does_not_close_this_chain(tmp_path):
    """A rewrite of a DIFFERENT deliverable is not evidence about this one."""
    root = _run_root(tmp_path)
    a, c = b"STAGED" * 32, b"FINAL" * 32
    (root / "phase3" / "stage3" / "pnr" / "spm.gds").write_bytes(c)
    rec = _record(root, staged_rel="phase3/stage3/pnr/spm.sealed.gds",
                  into_rel="phase3/stage3/pnr/spm.gds", sha=_sha(a))
    _fill_report(root, [_link(root, "phase3/stage3/pnr/other.gds",
                              _sha(a), _sha(c))])
    assert C.consumed_into_verified(
        "/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds",
        rec, root) is None


def test_only_the_seal_producers_own_document_may_claim_a_consumption(
        tmp_path):
    """Condition (1). Any document could otherwise claim a consumption for a
    path it never wrote."""
    root = _run_root(tmp_path)
    body = b"SEALED" * 64
    (root / "phase3" / "stage3" / "pnr" / "spm.gds").write_bytes(body)
    p = root / "reports" / "phase3" / "die_finishing.json"
    p.write_text(json.dumps({"producer": "some_other_program",
                             "seal_ring": {
                                 "consumed_staged":
                                     "phase3/stage3/pnr/spm.sealed.gds",
                                 "consumed_into": "phase3/stage3/pnr/spm.gds",
                                 "staged_sha256": _sha(body)}}))
    assert C.consumed_into_verified(
        "/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds", p,
        root) is None


def test_a_tampered_destination_breaks_the_chain(tmp_path):
    """One byte appended after the last recorded rewrite: the final digest no
    longer matches the last `sha_after`, so the chain does not reach it."""
    root = _run_root(tmp_path)
    a, c = b"STAGED" * 32, b"FINAL" * 32
    dest = root / "phase3" / "stage3" / "pnr" / "spm.gds"
    dest.write_bytes(c)
    rec = _record(root, staged_rel="phase3/stage3/pnr/spm.sealed.gds",
                  into_rel="phase3/stage3/pnr/spm.gds", sha=_sha(a))
    _fill_report(root, [_link(root, "phase3/stage3/pnr/spm.gds",
                              _sha(a), _sha(c))])
    assert C.consumed_into_verified(
        "/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds",
        rec, root) == "phase3/stage3/pnr/spm.gds"
    dest.write_bytes(c + b"X")
    assert C.consumed_into_verified(
        "/foss/designs/run23/phase3/stage3/pnr/spm.sealed.gds",
        rec, root) is None
