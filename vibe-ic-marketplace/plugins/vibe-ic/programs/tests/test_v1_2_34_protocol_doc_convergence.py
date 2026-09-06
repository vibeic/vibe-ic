"""Phase-1 protocol RECOGNIZER/EXTRACTOR convergence over every available
protocol design doc — all cases at once.

Runs each available protocol spec (the committed synthetic per-protocol fixtures
+ the real descriptive specs interlaken / lpc / mdio) through the full Phase-1
chain and pins two convergence properties:

  RECOGNIZER (the 86 `is_<proto>` detectors) — for every available doc, that
    protocol's OWN detector fires AND no FOREIGN detector misfires on it. This is
    the load-bearing Phase-1 ic_class/protocol recognition.

  EXTRACTOR boundary (program-first vs LLM-fallback) — the deterministic L14-L18
    protocol extractor fires on FORMAL spec format (tabular `Table N-N` + normative
    `shall/must` + version-history rows — proven on AMBA AXI / USB / PCIe in
    test_v1_2_32/33), and correctly DEFERS on a DESCRIPTIVE-PROSE design doc (no
    such structures), where the IC-Expert LLM fills the L-docs. This test documents
    + guards that boundary so a future change that silently starts FABRICATING
    protocol facts from prose (a §4.05 leak) is caught.

WHY no mass "fixes": a sweep of all 11 docs found the recognizer fully converged
(11/11 own-fire) and the extractor behaving correctly for each doc's format — the
descriptive-prose docs legitimately carry no tabular/normative structure to
deterministically extract (e.g. interlaken's only encoding is a 1-bit flag
`1 = Control Word, 0 = Data Word`, below the >=3-code enum floor). So the honest
deliverable is this regression harness, not manufactured extractor changes.
"""
from __future__ import annotations

import atexit
import glob
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import phase1_protocol_spec_extract as P                 # noqa: E402
import protocol_detector_no_misfire_matrix as M          # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_FIX = Path(__file__).resolve().parent / "fixtures" / "synthetic_benchmark_phase1"
_REAL = {
    "interlaken": str(corpus_path("interlaken_p3/phase1/input_doc")),
    "lpc": str(corpus_path("lpc_phase3/phase1/input_doc")),
    "mdio": str(corpus_path("mdio_phase1_p3/phase1/input_doc")),
}


#: The synthetic corpus, BUILT HERE rather than borrowed from whoever ran first.
#:
#: `_DOCS` is a module-level constant and it is the parametrize argument, so the
#: number of nodes this file CONTRIBUTES is decided at import time. The synthetic
#: half used to come only from `_FIX`, a gitignored path that
#: `test_protocol_detector_no_misfire.py` materialises at ITS module level — so
#: this file's population depended on whether that file had been imported first.
#:
#: MEASURED 2026-09-07 on 8HD-9 at 18cb660e3b01:
#:     whole-suite session         19 nodes   (3 plain + 2 parametrized x 8 docs)
#:     this file on its own         5 nodes   (3 plain + 2 EMPTY-parameter-set
#:                                             placeholders; `_DOCS` was {})
#: The per-file driver is the one the landing gate uses, so FOURTEEN nodes never
#: ran where it counts, and nothing said so — an empty parameter set collects as
#: a skip, which reads like a run that found nothing to do.
#:
#: Building into a PRIVATE temp directory, not into `_FIX`: a test that reads a
#: tree must not write to it, and the population is the generator's either way
#: because `build_synthetic_benchmark_phase1` is idempotent and names each
#: directory after its protocol stem.
_SYNTH_ROOT = Path(tempfile.mkdtemp(prefix="protoconv_synth_"))
atexit.register(shutil.rmtree, str(_SYNTH_ROOT), True)


def _synthetic_names():
    """The stems the generator ships, or () when it cannot be imported.

    Returned as a SET so the membership test below can name what is missing.
    Never silently empty: an empty set makes that test fail by name.
    """
    fixtures = str(Path(__file__).resolve().parent / "fixtures")
    if fixtures not in sys.path:
        sys.path.insert(0, fixtures)
    from synthetic_protocol_blobs import (               # noqa: PLC0415
        SYNTHETIC_BLOBS, build_synthetic_benchmark_phase1)
    build_synthetic_benchmark_phase1(_SYNTH_ROOT)
    return set(SYNTHETIC_BLOBS)


_SYNTH_EXPECTED = _synthetic_names()


def _available_docs():
    docs = {}
    for root in (_SYNTH_ROOT, _FIX):
        for sp in glob.glob(str(Path(root) / "*" / "phase1" / "input_doc" / "*.txt")):
            name = Path(sp).parents[2].name
            docs[name] = open(sp, errors="ignore").read()
    for name, d in _REAL.items():
        g = glob.glob(os.path.join(d, "*"))
        if g:
            docs[name] = open(g[0], errors="ignore").read()
    return docs


_DOCS = _available_docs()


def test_the_population_does_not_depend_on_what_else_was_imported():
    """This file contributes the same NODES however it is driven.

    Membership, not a count: a count cannot tell "eight docs" from "eight
    different docs", and the defect this guards against is a population that
    silently shrinks to zero when the file is run on its own.
    """
    missing = sorted(_SYNTH_EXPECTED - set(_DOCS))
    assert not missing, (
        f"the synthetic corpus is short of {missing}. Every one of these is "
        f"built by this module at import time, so a gap here means the builder "
        f"changed under the test rather than that the environment is thin — "
        f"the parametrized checks below would silently contribute "
        f"{2 * len(missing)} fewer nodes.")
# detector-name aliases: the fixture dir name vs the is_<stem> detector stem.
_ALIAS = {"interlaken": "interlaken", "lpc": "lpc", "mdio": "mdio"}


def test_corpus_present():
    # the committed synthetic fixtures must always be there (the real ones are
    # optional — skipped per-doc when the private corpus is absent).
    # The bulk of the corpus is the author-local synthetic_benchmark_phase1
    # fixture set (NOT git-tracked); only the _REAL docs ship. On a clean
    # checkout / CI the fixtures are absent, so SKIP below the full threshold
    # rather than hard-fail — the convergence checks parametrize over whatever
    # docs ARE present.
    n = len([k for k in _DOCS])
    if n < 8:
        import pytest
        pytest.skip(f"protocol-doc corpus partial ({n} present); the "
                    "synthetic_benchmark_phase1 fixtures are author-local / "
                    "uncommitted")
    assert n >= 8


@pytest.mark.parametrize("proto", sorted(_DOCS))
def test_own_detector_fires(proto):
    dets = M.discover_detectors()
    stem = _ALIAS.get(proto, proto)
    if stem not in dets:
        pytest.skip(f"no detector stem for {proto}")
    assert dets[stem](_DOCS[proto]), f"{proto}: own detector did not fire"


@pytest.mark.parametrize("proto", sorted(_DOCS))
def test_no_foreign_detector_misfire(proto):
    # no OTHER protocol's detector may claim this doc (recognizer precision). The
    # matrix's gold allowlist covers the few faithful sub-clause fires.
    dets = M.discover_detectors()
    stem = _ALIAS.get(proto, proto)
    allow = {b for (a, b) in M.ACCEPTABLE_GOLD_SUBCLAUSE_FIRES if a == stem}
    foreign = [k for k, fn in dets.items()
               if k != stem and k not in allow and fn(_DOCS[proto])]
    assert not foreign, f"{proto}: foreign detectors misfired: {foreign}"


def test_extractor_defers_on_descriptive_prose_no_fabrication():
    # §4.05 boundary: a descriptive-prose protocol doc with no tabular/normative
    # structure must NOT have protocol facts fabricated from prose. (interlaken is
    # the richest real prose doc; it carries no `Table N-N` / `shall|must` rows.)
    if "interlaken" not in _DOCS:
        pytest.skip("interlaken corpus absent")
    doc = _DOCS["interlaken"]
    assert P.extract_l15_encoding_tables(doc)["fields"]["tables"] == []
    assert P.extract_l17_channels(doc)["evidence"] == []
    # L16 fires ONLY on real normative sentences; a descriptive doc has ~none.
    assert len(P.extract_l16_compliance(doc)["evidence"]) <= 1


def test_formal_spec_still_extracts_all_layers():
    # the converged side: a formal AMBA-format excerpt still yields every layer
    # (guards against a regression that breaks formal extraction while loosening
    # prose handling).
    amba = (
        "Date Issue Confidentiality Change\n"
        "19 March 2010 C Non-Confidential First release of AXI4\n"
        "Table A3-2 AWBURST encoding\n0b00 FIXED\n0b01 INCR\n"
        "AWVALID Master Write address valid.\n"
        "AWREADY Slave Write address ready.\n"
        "The master must not wait for AWREADY before asserting AWVALID.\n"
        "AWID Output Optional All zeros\n")
    assert P.extract_l14_versioning(amba)["extraction_status"] == "EXTRACTED"
    assert P.extract_l15_encoding_tables(amba)["extraction_status"] == "EXTRACTED"
    assert P.extract_l16_compliance(amba)["extraction_status"] == "EXTRACTED"
    assert P.extract_l17_channels(amba)["extraction_status"] == "EXTRACTED"
    assert P.extract_l18_interconnect(amba)["extraction_status"] == "EXTRACTED"
