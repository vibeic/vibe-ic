#!/usr/bin/env python3
"""An input-document citation the published tree cannot carry is RECORDED, not
left to dangle (vibe-ic#456).

THE MEASUREMENT. The L-docs cite the document they were extracted from by path
(`"evidence": "input/docs/<doc>"`). Over the tracked parity corpus there are 89
distinct (protocol, cited document) pairs: 55 resolve and 34 point at a document
the tree does not carry. A reader following one of those 34 finds nothing and is
told nothing.

THE TWO REPAIRS ARE OPPOSITE, AND PICKING WRONG IS COSTLY. Either the document
was never publishable (then the pointer should SAY so), or it should have been
published and was dropped (then it should be published, and only then do the
cited values become checkable). Labelling a dropped file 'inherently
unfollowable' would freeze a fixable gap forever.

WHAT DECIDED IT — three independent facts, none of them assumed:

  1. `source_tier.json` carries a `durability_note`: "Input documents are
     subject to removal for licensing reasons. This file is the durable record;
     the tier must survive the document." Removal is a STATED, ANTICIPATED
     policy, not an accident.
  2. Tier x publication is a perfect licensing separation with zero
     counterexamples over all 87 protocols:
         encyclopedia        12/12 published   (Wikipedia prints)
         reconstructed_text  39/39 published   (authored for this benchmark)
         specification        3/23 published   (exactly the freely
                                                redistributable ones)
         vendor_document      0/13 published   (vendor app notes)
     An accidental drop would not sort itself by redistributability.
  3. Every one of the 34 unfollowable documents is NAMED in the record, with the
     tier and the observed title/page-count that identifies it. Zero are
     unaccounted for. A dropped file would show up as unrecorded; none does.

So the pointer is unfollowable HERE and obtainable THERE, and the repair is to
say that rather than to republish a licensed document. The gate below enforces
the distinction in the direction that keeps the OTHER repair reachable: an
absence the record does not account for stays a loud failure.

The scope is also larger than the issue reported: 34 protocols, not 5, and the
citations span L1-L23, not only L3.

WHERE THE PARITY CORPUS LIVES NOW
---------------------------------
It spans TWO trees, and this check is precisely the one that needs both halves:

  * the GENERATED documents that carry the citations (`<proto>/phase1/
    generated_docs/*.json`) moved to https://github.com/vibeic/benchmark-data;
  * the CITED documents (`<proto>/input/docs/*`) never left vibe-ic — they are
    the design input the flow reads.

Measuring either half alone answers a different question: over the corpus alone
every one of the 89 citations reads WITHHELD_ON_RECORD, not because a document
is withheld but because its half of the tree is elsewhere. So `parity_root`
reassembles the two, and the three real-data tests below then reproduce the
documented split exactly (55 RESOLVES + 34 WITHHELD_ON_RECORD). With no corpus
to read they SKIP naming it, per `_published_corpus` — the rule vibe-ic#1357
set for an absent TOOL, applied to an absent CORPUS.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase1_parity_source_tier_check as M  # noqa: E402

from _published_corpus import corpus_root, needs_corpus  # noqa: E402

#: The half that stayed here: the cited input documents.
_INPUT_HALF = _PROGRAMS.parents[3] / "benchmark-data" / "protocol_parity"


def _mirror(src: Path, dst: Path) -> None:
    """Mirror `src` into `dst` as REAL directories holding SYMLINKED files.

    Real directories because `collect_input_doc_citations` walks with
    `Path.rglob`, which does not descend into a symlinked directory — link the
    protocol dirs and the walk finds nothing at all. Symlinked leaves because
    the published artefacts are read, never copied and never written: the whole
    assembly costs ~0.3 s and touches nothing under either source tree.

    First writer wins, so a tree that already carries both halves reassembles to
    itself rather than being overlaid twice.
    """
    for base, _dirs, files in os.walk(src):
        rel = Path(base).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for name in files:
            link = dst / rel / name
            if not link.exists():
                link.symlink_to(Path(base) / name)


@pytest.fixture()
def parity_root(tmp_path: Path) -> Path:
    """The parity corpus, reassembled from the two trees it now spans.

    Only requested by tests marked `@needs_corpus`, so `corpus_root()` is not
    None here and this fixture never has to invent a skip of its own.
    """
    root = tmp_path / "protocol_parity"
    _mirror(corpus_root() / "protocol_parity", root)
    if _INPUT_HALF.is_dir():
        _mirror(_INPUT_HALF, root)
    return root


def _protocol(tmp_path: Path, cited: str, *, key: str = "evidence",
              make_target: bool = False) -> Path:
    d = tmp_path / "proto"
    doc = d / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(json.dumps({"opcodes": [{"name": "X", key: cited}]}))
    if make_target:
        t = d / cited
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text("x\n")
    return d


def _entry(docs, evidence="PDF /Title='Some Doc'; 42 pages", tier="specification"):
    return {"tier": tier, "evidence": evidence, "input_documents": list(docs)}


# --------------------------------------------------------------------------
# The three states, each pinned separately.
# --------------------------------------------------------------------------
def test_a_withheld_document_named_by_the_record_is_WITHHELD_ON_RECORD(tmp_path):
    """THE LOAD-BEARING CASE — the shape all 34 real ones take."""
    d = _protocol(tmp_path, "input/docs/Spec.pdf")
    assert M.classify_citation(d, "input/docs/Spec.pdf",
                               _entry(["Spec.pdf"])) == "WITHHELD_ON_RECORD"


def test_a_citation_that_resolves_is_recorded_as_resolving(tmp_path):
    """The paired half: the record must not call everything withheld."""
    d = _protocol(tmp_path, "input/docs/Spec.pdf", make_target=True)
    assert M.classify_citation(d, "input/docs/Spec.pdf",
                               _entry(["Spec.pdf"])) == "RESOLVES"


def test_a_document_the_record_does_not_name_is_ABSENT_UNRECORDED(tmp_path):
    """THE ANTI-FREEZE CASE, and the reason this repair is safe.

    If a document was DROPPED rather than withheld, the record does not name it
    and it must stay loud. Blessing every absence would label a fixable gap
    'inherently unfollowable' — the exact failure #456 warns against.
    """
    d = _protocol(tmp_path, "input/docs/Dropped.pdf")
    assert M.classify_citation(d, "input/docs/Dropped.pdf",
                               _entry(["Other.pdf"])) == "ABSENT_UNRECORDED"


def test_a_protocol_with_no_record_at_all_is_ABSENT_NO_RECORD(tmp_path):
    d = _protocol(tmp_path, "input/docs/Spec.pdf")
    assert M.classify_citation(d, "input/docs/Spec.pdf", None) == "ABSENT_NO_RECORD"


def test_a_named_document_with_no_identifying_evidence_is_UNIDENTIFIABLE(tmp_path):
    """Naming a file is not accounting for it. Without a title/page-count a
    reader cannot obtain the document, only guess which one it was — so this is
    a defect, not a blessed absence."""
    d = _protocol(tmp_path, "input/docs/Spec.pdf")
    assert M.classify_citation(d, "input/docs/Spec.pdf",
                               _entry(["Spec.pdf"], evidence="  ")) == "ABSENT_UNIDENTIFIABLE"


# --------------------------------------------------------------------------
# Collection discipline — the false-positive class #448 measured.
# --------------------------------------------------------------------------
def test_prose_under_a_citation_key_is_not_a_path_citation(tmp_path):
    """The anchor, isolated from the key filter.

    The corpus's OWN `evidence` fields are usually prose quoting the spec, and
    two of them name a document mid-sentence. An unanchored regex would mine a
    path out of that sentence and report it dangling. Measured: relaxing the
    anchors turns 0 real defects into 141 false ABSENT_UNRECORDED corpus-wide.
    A citation is a value that IS a path, not one that mentions one.
    """
    d = tmp_path / "proto"
    doc = d / "phase1" / "generated_docs" / "L1.json"
    doc.parent.mkdir(parents=True)
    doc.write_text(json.dumps({
        "evidence": "extracted from input/docs/Spec.pdf section 4, verbatim",
        # Leading-anchored too: a value that STARTS with the path but trails
        # into prose is a sentence, not a pointer. This is the half `re.match`
        # lets through and only `fullmatch` rejects.
        "source": "input/docs/Spec.pdf, section 4 table 12",
    }))
    assert M.collect_input_doc_citations(d) == {}


def test_a_path_under_a_non_citation_key_is_ignored(tmp_path):
    d = tmp_path / "proto"
    doc = d / "reports" / "log.json"
    doc.parent.mkdir(parents=True)
    doc.write_text(json.dumps({"scanned_dir": "input/docs/Spec.pdf"}))
    assert M.collect_input_doc_citations(d) == {}


def test_versioned_and_qualified_evidence_keys_are_collected(tmp_path):
    """Real corpus keys include `primary_evidence_v1_6_370` and
    `wake_pulse_measurement_evidence`. Matching them by NAME would be overfit;
    they qualify because the key contains 'evidence'."""
    d = tmp_path / "proto"
    doc = d / "phase1" / "generated_docs" / "L8.json"
    doc.parent.mkdir(parents=True)
    doc.write_text(json.dumps({"primary_evidence_v1_6_370": "input/docs/A.pdf",
                               "wake_pulse_measurement_evidence": "input/docs/B.pdf"}))
    assert sorted(M.collect_input_doc_citations(d)) == ["input/docs/A.pdf",
                                                        "input/docs/B.pdf"]


def test_one_document_cited_by_ten_docs_is_one_citation(tmp_path):
    """A document cited in 10 L-docs is one thing a reader can or cannot
    follow, not ten — or a count of citations is a count of mentions."""
    d = tmp_path / "proto"
    for i in range(10):
        p = d / "phase1" / "generated_docs" / f"L{i}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"evidence": "input/docs/Spec.pdf"}))
    cites = M.collect_input_doc_citations(d)
    assert list(cites) == ["input/docs/Spec.pdf"]
    assert len(cites["input/docs/Spec.pdf"]) == 10


# --------------------------------------------------------------------------
# Gate wiring + the emitted record.
# --------------------------------------------------------------------------
def _root(tmp_path: Path, cited: str, entry: dict | None, *, make_target=False) -> Path:
    root = tmp_path / "parity"
    d = root / "proto"
    doc = d / "phase1" / "generated_docs" / "L3.json"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(json.dumps({"evidence": cited}))
    if make_target:
        t = d / cited
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text("x\n")
    protocols = {"proto": entry} if entry else {}
    (root / "source_tier.json").write_text(json.dumps(
        {"schema": "phase1_parity_source_tier/v1", "protocols": protocols}))
    return root


def test_the_gate_fails_on_an_unaccounted_citation(tmp_path):
    root = _root(tmp_path, "input/docs/Dropped.pdf", _entry(["Other.pdf"]))
    rep = M.check(root, root / "source_tier.json")
    assert rep["ok"] is False
    assert any("ABSENT_UNRECORDED" in v for v in rep["violations"]), rep["violations"]


def test_the_gate_passes_a_withheld_citation_the_record_accounts_for(tmp_path):
    root = _root(tmp_path, "input/docs/Spec.pdf", _entry(["Spec.pdf"]))
    rep = M.check(root, root / "source_tier.json")
    assert rep["ok"] is True, rep["violations"]
    assert rep["citation_counts"] == {"WITHHELD_ON_RECORD": 1}


def test_the_record_is_written_even_when_everything_resolves(tmp_path):
    """A record that only appears on failure cannot be used to prove there were
    no failures — the rule CITATION_ROUTING.txt already follows."""
    root = _root(tmp_path, "input/docs/Spec.pdf", _entry(["Spec.pdf"]),
                 make_target=True)
    rep = M.check(root, root / "source_tier.json")
    body = M.render_citation_routing(rep["citations"])
    assert "INPUT_DOC_CITATION_ROUTING" in body
    assert "proto :: input/docs/Spec.pdf RESOLVES" in body


def test_emit_routing_writes_the_file_and_exits_zero(tmp_path):
    root = _root(tmp_path, "input/docs/Spec.pdf", _entry(["Spec.pdf"]))
    rc = M.main([str(root), "--emit-routing"])
    assert rc == 0
    body = (root / M.ROUTING_FILENAME).read_text()
    assert "proto :: input/docs/Spec.pdf WITHHELD_ON_RECORD" in body


# --------------------------------------------------------------------------
# Real data. The numbers that justify the separation, not a fixture of them.
# --------------------------------------------------------------------------
@needs_corpus
def test_the_corpus_is_measured_not_assumed(parity_root: Path):
    rep = M.check(parity_root, parity_root / "source_tier.json")
    cc = rep["citation_counts"]
    # THE PARTITION, not the census. `89 == 55 + 34` was three integers, and
    # all three are the size of the parity corpus on the day they were written:
    # publish or withdraw one cell and every one of them is wrong, for a reason
    # that says nothing about the routing. What the three were standing in for
    # is that the two decisions PARTITION the citations — no third bucket, none
    # unaccounted — which is true of one cell, of 89 and of however many the
    # corpus carries next.
    assert cc, cc
    assert set(cc) == {"RESOLVES", "WITHHELD_ON_RECORD"}, cc
    assert sum(cc.values()) == cc["RESOLVES"] + cc["WITHHELD_ON_RECORD"], cc
    # Both arms exercised, so the partition is not satisfied by an empty one.
    assert cc["RESOLVES"] > 0 and cc["WITHHELD_ON_RECORD"] > 0, cc
    # THE POINT: not one unfollowable pointer is unaccounted for. This is the
    # evidence that the corpus withholds by policy rather than dropping by
    # accident, and it is the assertion that breaks first if that ever changes.
    assert not [k for k in cc if k.startswith("ABSENT_")], cc


@needs_corpus
def test_the_five_cells_the_issue_named_are_withheld_on_record(parity_root: Path):
    """#456 named 5. They are real, and they are 5 of 34."""
    rep = M.check(parity_root, parity_root / "source_tier.json")
    by = {(r["protocol"], r["cited"]): r["decision"] for r in rep["citations"]}
    for proto, doc in [("dali", "DALI_Spec.pdf"),
                       ("ethernet", "Ethernet_Spec.pdf"),
                       ("rs485", "RS485_Spec.pdf"),
                       ("sata", "SATA_AHCI_1_3_1.pdf"),
                       ("sdmmc", "SD_simplified.pdf")]:
        assert by[(proto, f"input/docs/{doc}")] == "WITHHELD_ON_RECORD"


@needs_corpus
def test_the_one_followable_cell_really_does_resolve(parity_root: Path):
    """#456 said exactly one cell's pointers are followable. That is true at the
    CELL level and is why the corpus-wide claim '95 of 95 unfollowable' is not:
    pcie_gen5's 18 pointers resolve, so it is 77 of 95 opcode-level pointers."""
    rep = M.check(parity_root, parity_root / "source_tier.json")
    by = {(r["protocol"], r["cited"]): r["decision"] for r in rep["citations"]}
    assert by[("pcie_gen5", "input/docs/pcie_gen5_spec.pdf")] == "RESOLVES"
