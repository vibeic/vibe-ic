"""ORGANIC — a doc whose own frontmatter says `status: not-applicable` must
yield NO L9 memory.

THE DEFECT, measured on the REAL on-disk `benchmark-data/ic/spm/input/docs/
L5_register_map.md` (spm x ihp-sg13cmos5l). That file declares
`status: not-applicable` in its own frontmatter and its body reads::

    ## 適用性 — N/A
    `spm` **無 SW-visible registers**。
    → 不需 Plugin 產生 register file / CSR decoder / memory-mapped interface。

`_V1_6_426_RE_MEMORY_PROSE` matched the literal phrase "register file" INSIDE
THE SENTENCE INSTRUCTING THE PLUGIN NOT TO GENERATE ONE and emitted::

    {"name": null, "kind": "regfile", "type": "register file",
     "port_count": null, "depth": null, "width": null,
     "evidence_file": "L5_register_map.md",
     "extraction_strategy": "l9_memory_prose_walker_v1_6_426",
     "low_confidence": true}

Every field that would make it actionable is null. That single fabricated row
is the ONLY `low_confidence: true` entry in the spm `L9_INTEGRATION_SPEC.json`,
and the in-gate stub-backed rule (#434, review_required) reads low_confidence
evidence as DEFERRED work — so Step D1 (Phase 1 Doc Extraction) was downgraded
to WAIVED-DEFERRED on an ingestion that was otherwise clean.

Same defect class as #358 on the analog side: a keyword matcher firing on text
that DENIES the thing.

WHICH TESTS ARE DRIVEN BY A REAL IN-REPO ARTEFACT
=================================================
This split is stated explicitly because a change whose whole test suite is
synthetic fixtures authored alongside it cannot distinguish itself from its
own absence.

  REAL ARTEFACT (reads a checked-in benchmark document off disk):
    * test_real_spm_doc_end_to_end_yields_no_memory_candidate
        -> the motivating document, driven through the REAL
           `extract_text_pipeline` + the REAL `gen_l9_integration_spec`,
           asserting on the `L9_INTEGRATION_SPEC.json` the generator writes.
           FAILS without the fix.
    * test_no_not_applicable_doc_in_the_repo_carries_a_populated_memory
        -> the SAFETY invariant, asserted over EVERY not-applicable document
           in `benchmark-data/`: none of them specifies a memory with a
           populated depth / width / port_count, so this rule provably cannot
           delete real hardware anywhere in the corpus.
    * test_real_corpus_is_otherwise_untouched
        -> non-regression over every benchmark `input/docs/` document: the
           rule changes the walker's output on the not-applicable documents
           ONLY.

  SYNTHETIC (hand-typed fixtures — bounds and conservatism only):
    * test_status_tbd_is_not_not_applicable
    * test_no_frontmatter_is_not_not_applicable
    * test_frontmatter_without_status_is_not_not_applicable
    * test_not_applicable_file_does_not_suppress_a_sibling_file
    * test_declares_not_applicable_accepts_the_documented_spellings
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _hostpaths import require_repo
from _published_corpus import corpus_root

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as P  # noqa: E402


def _project(tmp_path: Path, docs: dict) -> Path:
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True, exist_ok=True)
    for name, body in docs.items():
        (proj / "input" / "docs" / name).write_text(body, encoding="utf-8")
    return proj


def _walk(tmp_path: Path, docs: dict) -> tuple:
    """The REAL extractor + the REAL emit driver -> (memories, candidates)."""
    proj = _project(tmp_path, docs)
    extracted = P.extract_text_pipeline(proj, force=True)
    assert extracted, "the real extractor produced nothing — premise broken"
    l9: dict = {}
    P._v1_6_426_emit_memories(l9, extracted)
    return (l9.get("memories") or [], l9.get("memory_candidates") or [])


def _l9_doc(tmp_path: Path, docs: dict) -> dict:
    """The REAL L9 generator, end to end, returning the JSON it wrote."""
    proj = _project(tmp_path, docs)
    extracted = P.extract_text_pipeline(proj, force=True)
    res = P.gen_l9_integration_spec(proj, extracted, {})
    out = Path(res.path)
    assert out.is_file(), f"L9 generator wrote nothing at {out}"
    return json.loads(out.read_text(encoding="utf-8"))


# ─────────────── REAL ARTEFACT — the defect direction ────────────────

def test_real_spm_doc_end_to_end_yields_no_memory_candidate(tmp_path):
    """THE DEFECT, on the REAL on-disk benchmark document, end to end.

    Pre-fix the written `L9_INTEGRATION_SPEC.json` carries exactly one
    `"low_confidence": true` — the fabricated regfile row — and that single
    row is what downgraded Step D1 to WAIVED-DEFERRED.
    """
    src = require_repo("benchmark-data", "ic", "spm", "input", "docs",
                       "L5_register_map.md")
    body = src.read_text(encoding="utf-8")
    # PREMISE — the signal this rule keys on is really in the file, and so is
    # the sentence that produced the fabricated row. If the benchmark document
    # is ever rewritten, fail loudly instead of passing vacuously.
    assert "status: not-applicable" in body, (
        "premise broken: the real doc no longer declares status: "
        "not-applicable")
    assert "不需 Plugin 產生 register file" in body, (
        "premise broken: the real doc no longer carries the denial sentence")

    doc = _l9_doc(tmp_path, {"L5_register_map.md": body})

    assert doc.get("memory_candidates") == [], (
        "the walker harvested a memory candidate out of a document whose own "
        "frontmatter declares the layer not applicable: "
        f"{json.dumps(doc.get('memory_candidates'), ensure_ascii=False)}")
    assert doc.get("memories") == []
    assert doc.get("no_memory_candidates_in_input") is True
    blob = json.dumps(doc, ensure_ascii=False)
    assert blob.count('"low_confidence": true') == 0, (
        "a low_confidence row survives in L9_INTEGRATION_SPEC.json — the "
        "in-gate stub-backed rule (#434) reads that as DEFERRED work and "
        "downgrades Step D1")


# ───────── REAL ARTEFACT — the safety direction (can it lose hardware?) ─────

def test_no_not_applicable_doc_in_the_repo_carries_a_populated_memory():
    """THE INVARIANT THAT MAKES THIS RULE SAFE TO SHIP.

    The rule drops EVERYTHING mined out of a not-applicable document, so the
    question that decides it is: does any such document in the repo actually
    specify a memory? Asserted over every checked-in `benchmark-data/`
    markdown document — every row the rule discards must be a null-everything
    row (no name, no depth, no width, no port count). A populated row here
    would mean the rule deletes hardware a design genuinely has.

    NOT A CORPUS TEST, and deliberately not marked as one — read the failure
    before assuming the cause. Every document this rule can fire on is a DESIGN
    INPUT (`ic/*/input/docs/L*.md`), and design inputs stay in vibe-ic; it is
    the RESULT cells that moved to `vibeic/benchmark-data` at the 2026-08
    split. Measured across that split: 9 documents declare
    `status: not-applicable`, all 9 under `input/docs/`, all 9 still here, and
    the published corpus contributes ZERO — 505 markdown documents in it, none
    with a not-applicable frontmatter. So the rule's exposure is unchanged and
    a skip keyed on the corpus would suppress a check that can still measure.

    What did break was the population floor `scanned > 100`, which counted the
    506 RESULT documents too and so measured a denominator this invariant never
    used. It is asked of both roots now — the inputs that stay, plus the
    published cells whenever they are readable — and the floor that decides the
    premise is on `na_docs`, the documents that actually exercise the rule.
    """
    roots = [require_repo("benchmark-data")]
    # When a published corpus IS readable, judge it too: before the split its
    # cells were in this walk, and this keeps them in it.
    corpus = corpus_root()
    if corpus is not None and corpus.resolve() not in {r.resolve()
                                                       for r in roots}:
        roots.append(corpus)
    scanned = 0
    na_docs = set()
    dropped = []
    for root in roots:
        for doc in sorted(root.rglob("*.md")):
            if not doc.is_file():
                continue
            try:
                text = doc.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            scanned += 1
            if not P._doc_declares_not_applicable(text):
                continue
            na_docs.add(doc.relative_to(root).as_posix())
            # Re-run the walker with the rule neutralised, to see exactly what
            # it is discarding on this document.
            real = P._doc_declares_not_applicable
            P._doc_declares_not_applicable = lambda _t: False
            try:
                rows = P._v1_6_426_extract_memories_from_text(text, doc.name)
            finally:
                P._doc_declares_not_applicable = real
            for r in rows:
                dropped.append((str(doc), r))
    assert scanned >= 90, (
        f"premise broken: only {scanned} markdown documents scanned. The "
        f"design INPUT documents do not leave this repository — 99 of them "
        f"here when this was measured — so a number below the floor means the "
        f"inputs went missing, not that the result cells moved")
    expected_na = {
        "ic/sha256/input/docs/L6_calibration.md",
        "ic/spm/input/docs/L4_command_protocol.md",
        "ic/spm/input/docs/L5_register_map.md",
        "ic/spm/input/docs/L6_calibration.md",
        "ic/subservient/input/docs/L4_command_protocol.md",
        "ic/subservient/input/docs/L5_register_map.md",
        "ic/subservient/input/docs/L6_calibration.md",
    }
    assert na_docs == expected_na, (
        "the frozen 8c4b608 not-applicable input population moved",
        sorted(na_docs - expected_na), sorted(expected_na - na_docs))

    # The two former members did not vanish: the SHA spec-review pass made L4
    # and L5 active, with a real memory-mapped command/register contract.  A
    # raw floor of nine treated that stronger specification as lost coverage.
    sha = next((r / "ic/sha256/input/docs" for r in roots
                if (r / "ic/sha256/input/docs").is_dir()), None)
    assert sha is not None, "the SHA input documents disappeared"
    active_markers = {
        "L4_command_protocol.md": (
            "# L4 — Command / Protocol Layer",
            "memory-mapped register file",
            "ADDR_CTRL",
        ),
        "L5_register_map.md": (
            "# L5 — Register Map",
            "`0x08` | `CTRL`",
            "`0x20-0x27` | `DIGEST0`",
        ),
    }
    for name, markers in active_markers.items():
        text = (sha / name).read_text(encoding="utf-8")
        assert not P._doc_declares_not_applicable(text), name
        assert "status: draft" in text, name
        assert all(marker in text for marker in markers), name
    populated = [(f, r) for f, r in dropped
                 if r.get("name") or r.get("depth") is not None
                 or r.get("width") is not None or r.get("port_count")]
    assert populated == [], (
        "this rule discards a POPULATED memory row from a not-applicable "
        "document — it is deleting hardware, not a hallucination: "
        f"{json.dumps(populated, ensure_ascii=False)}")


def test_real_corpus_is_otherwise_untouched():
    """NON-REGRESSION over every benchmark `input/docs/` document: the rule
    changes the walker's output on documents that declare themselves not
    applicable, and on NOTHING else."""
    root = require_repo("benchmark-data", "ic")
    checked = 0
    for doc in sorted(root.glob("*/input/docs/*")):
        if not doc.is_file():
            continue
        try:
            text = doc.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        checked += 1
        real = P._doc_declares_not_applicable
        P._doc_declares_not_applicable = lambda _t: False
        try:
            before = P._v1_6_426_extract_memories_from_text(text, doc.name)
        finally:
            P._doc_declares_not_applicable = real
        after = P._v1_6_426_extract_memories_from_text(text, doc.name)
        if P._doc_declares_not_applicable(text):
            assert after == [], f"{doc.name}: not-applicable doc still mined"
        else:
            assert after == before, (
                f"{doc.name}: the rule changed a document that does NOT "
                "declare itself not applicable")
    assert checked > 50, (
        f"premise broken: only {checked} benchmark documents scanned")


# ───────────────── SYNTHETIC — bounds and conservatism ──────────────────

_NA_DOC = """---
layer: L5
ic: demo_na
status: not-applicable
written_at: 2026-07-26
---

# L5 — Register Map

本層不適用於本設計。
The tile integrates a single-port SRAM 512x16 in `demo_sram.v`.
"""

_TBD_DOC = _NA_DOC.replace("status: not-applicable", "status: tbd")

_NO_FM_DOC = """# L9 — Integration

The tile integrates a single-port SRAM 512x16 in `demo_sram.v`.
"""

_FM_NO_STATUS_DOC = """---
layer: L9
ic: demo_ns
---

# L9 — Integration

The tile integrates a single-port SRAM 512x16 in `demo_sram.v`.
"""


def test_status_tbd_is_not_not_applicable(tmp_path):
    """`tbd` means NOT WRITTEN YET, not DOES NOT EXIST. A tbd document that
    already carries a real memory paragraph must still be harvested."""
    assert P._doc_declares_not_applicable(_TBD_DOC) is False
    mems, _ = _walk(tmp_path, {"L9_integration.md": _TBD_DOC})
    assert len(mems) == 1, (
        "a `status: tbd` document lost a genuine memory: "
        f"{json.dumps(mems, ensure_ascii=False)}")
    assert mems[0]["depth"] == 512 and mems[0]["width"] == 16


def test_no_frontmatter_is_not_not_applicable(tmp_path):
    assert P._doc_declares_not_applicable(_NO_FM_DOC) is False
    mems, _ = _walk(tmp_path, {"L9_integration.md": _NO_FM_DOC})
    assert len(mems) == 1


def test_frontmatter_without_status_is_not_not_applicable(tmp_path):
    assert P._doc_declares_not_applicable(_FM_NO_STATUS_DOC) is False
    mems, _ = _walk(tmp_path, {"L9_integration.md": _FM_NO_STATUS_DOC})
    assert len(mems) == 1


def test_not_applicable_file_does_not_suppress_a_sibling_file(tmp_path):
    """PER-FILE SCOPE. A not-applicable L5 must not silence a genuine L9 in
    the same corpus — the walker is called once per extracted document."""
    mems, _ = _walk(tmp_path, {
        "L5_register_map.md": _NA_DOC,
        "L9_integration.md": _NO_FM_DOC,
    })
    assert len(mems) == 1, (
        "the sibling L9's genuine SRAM was suppressed by a DIFFERENT file's "
        f"frontmatter: {json.dumps(mems, ensure_ascii=False)}")
    assert mems[0]["depth"] == 512 and mems[0]["width"] == 16


def test_declares_not_applicable_accepts_the_documented_spellings():
    for spelling in ("not-applicable", "not_applicable", "N/A", "n/a", "NA",
                     "不適用", "不适用", '"not-applicable"'):
        doc = f"---\nlayer: L5\nstatus: {spelling}\n---\n\nbody\n"
        assert P._doc_declares_not_applicable(doc) is True, spelling
    for spelling in ("final", "draft", "tbd", "todo", "pending", "unknown",
                     "applicable", "not-yet-written"):
        doc = f"---\nlayer: L5\nstatus: {spelling}\n---\n\nbody\n"
        assert P._doc_declares_not_applicable(doc) is False, spelling


def test_a_status_line_in_the_BODY_is_not_a_frontmatter_declaration():
    """GATEKEEPER-ADDED control (Step-2.7 adversarial review of #406).

    The change documents itself as "YAML frontmatter grammar only", and that
    scoping is what keeps it from deleting evidence: a doc that QUOTES another
    document's `status: not-applicable`, or carries it in a table row, has
    declared nothing about itself.

    Nothing tested it. Relaxing `_RE_DOC_FRONTMATTER_BLOCK` to `(.*)` — so the
    whole document counts as frontmatter — left all 8 tests green. A claim in a
    docstring that no control defends is a claim, not a property.
    """
    # The `status:` must be at LINE START to be a plausible frontmatter key —
    # an earlier version of this very test put it mid-sentence, where the
    # line-anchored key regex could never match, so it passed against the
    # relaxed block regex too and proved nothing. The fixture has to be shaped
    # like the thing it stands for.
    body_only = (
        "# L9 Integration Spec\n"
        "\n"
        "The upstream L5 doc records:\n"
        "\n"
        "status: not-applicable\n"
        "\n"
        "This design has a 512x32 single-port SRAM instance.\n"
    )
    assert P._doc_declares_not_applicable(body_only) is False

    # Frontmatter that does not START the file is not frontmatter either.
    late_block = (
        "# Title\n\n---\nstatus: not-applicable\n---\n\nbody\n"
    )
    assert P._doc_declares_not_applicable(late_block) is False

    # The paired half: the SAME token, this time in a real frontmatter block.
    real = "---\nstatus: not-applicable\n---\n\nbody mentioning a register file\n"
    assert P._doc_declares_not_applicable(real) is True
