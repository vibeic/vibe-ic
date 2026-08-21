"""ORGANIC — the L9 memory prose walker must not harvest a candidate out of a
DENIAL.

DEFECT (measured on spm x ihp-sg13cmos5l, plugin 1.6.1)
=======================================================
Step D1 (Phase 1 Doc Extraction) was downgraded to WAIVED-DEFERRED by exactly
ONE hallucinated row — the only `low_confidence: true` entry in the whole of
`L9_INTEGRATION_SPEC.json`::

    "memory_candidates[0]": {
      "name": null, "kind": "regfile", "type": "register file",
      "port_count": null, "depth": null, "width": null,
      "evidence_file": "L5_register_map.md",
      "extraction_strategy": "l9_memory_prose_walker_v1_6_426",
      "low_confidence": true }

Every field that would make it actionable is null. The evidence file it cites,
`input/docs/L5_register_map.md`, declares `status: not-applicable` in its own
frontmatter and its body says::

    ## 適用性 — N/A
    `spm` **無 SW-visible registers**。
    → 不需 Plugin 產生 register file / CSR decoder / memory-mapped interface。

`_V1_6_426_RE_MEMORY_PROSE` matched the literal phrase "register file" INSIDE
THE SENTENCE INSTRUCTING THE PLUGIN NOT TO GENERATE ONE. Ingestion itself was
clean (`extraction_skipped: []`, 9/9 extracted); the sole cause of the deferral
was this fabricated candidate, because the in-gate stub-backed rule (#434,
review_required) reads `low_confidence` evidence as DEFERRED work.

SAME DEFECT CLASS AS #358, which closed the analog sibling: the plugin's own L5
heading matched `_ANALOG_KEYWORDS["adc"]` and fabricated two analog blocks plus
28 files of analog sign-off evidence for hardware that does not exist. A keyword
matcher firing on text that DENIES the thing.

THE FIX reuses the analog path's OWN negation predicate
(`_v0_1_62_analog_kw_negated`) rather than inventing a second, differently
shaped notion of "negated" in the same module, and honours TWO signals:

  1. FILE level  — `_doc_declares_not_applicable`: the cited evidence doc's own
     YAML frontmatter says `status: not-applicable`.
  2. SENTENCE level — the shared negation predicate over the match span, with
     its vocabulary widened by bare `無` (structurally bounded so CJK compounds
     stay readable) and `N/A`.

BIDIRECTIONAL
=============
FAIL-AGAINST-UNFIXED (the defect direction):
  * test_real_spm_doc_end_to_end_emits_no_memory_candidate — the REAL on-disk
    benchmark doc, driven through the REAL `extract_text_pipeline` +
    `gen_l9_integration_spec`, asserting on the `L9_INTEGRATION_SPEC.json`
    the generator actually writes. Pre-fix the doc carries the row above and
    exactly one `"low_confidence": true`; this test FAILS.
  * test_denial_prose_yields_no_candidate — the same proof, self-contained so
    it runs on the installed plugin cache too. FAILS pre-fix.
  * test_frontmatter_not_applicable_alone_suppresses — isolates signal 1: an
    N/A doc whose memory sentence carries NO negation marker. The sentence
    guard cannot see this one, so it proves the frontmatter signal really is
    wired. FAILS pre-fix.
  * test_negated_sentence_in_same_file_yields_no_candidate — the candidate
    half of the mixed document. FAILS pre-fix.
  * test_shared_negation_predicate_sees_zh_and_na — the two markers the
    vocabulary could not previously see (bare `無`, `N/A`). FAILS pre-fix.

TRUE-POSITIVE CONTROLS (this change makes the walker harvest LESS; the way to
get it wrong is to suppress genuine memories):
  * test_genuine_register_file_still_harvested — a real
    "register file 32x8 ... 2 read ports, 1 write port" spec is STILL harvested
    into `memories[]` with depth/width/name populated.
  * test_negated_sentence_does_not_shadow_real_spec_in_same_file — a doc that
    denies a register file in one sentence and SPECIFIES one in another still
    yields the real one.
  * test_not_applicable_file_does_not_suppress_sibling_file — a
    not-applicable frontmatter must not suppress a DIFFERENT file's genuine
    evidence.
  * test_status_tbd_is_not_not_applicable — `tbd`/`todo`/`draft` mean "not
    written yet", NOT "does not exist". Guards against widening the
    applicability-denial set into a general no-information set.
  * test_cjk_compound_wu_is_not_a_negation — 無線 (wireless) / 無源 (passive) /
    無限 / 無論 are COMPOUND WORDS carrying real design content. Bare `無` is a
    negator only when it precedes a Latin/ASCII term. Guards the widened
    vocabulary against eating genuine analog + memory prose.

All controls are proven by RUNNING the real extraction + emit path, not by
asserting on hand-typed fixtures.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _hostpaths import require_repo

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as P  # noqa: E402


# ── the real defect input, verbatim (kept in sync by
#    test_real_spm_doc_end_to_end_emits_no_memory_candidate, which reads the
#    on-disk original and re-checks the two sentences this copy relies on) ──
DENIAL_DOC = """---
layer: L5
ic: spm
status: not-applicable
written_at: 2026-05-22
---

# L5 — Register Map

## 適用性 — N/A

`spm` **無 SW-visible registers**。

- 無 control register
- 無 status register
- 無 configuration register
- 無 interrupt enable / status

設計為純資料路徑(datapath)+ 同步狀態(僅內部 pipeline / accumulator 狀態,對外不可見)。

→ 不需 Plugin 產生 register file / CSR decoder / memory-mapped interface。
"""


def _project(tmp_path: Path, docs: dict) -> Path:
    """Materialise a project whose `input/docs/` holds `docs`."""
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True, exist_ok=True)
    for name, body in docs.items():
        (proj / "input" / "docs" / name).write_text(body, encoding="utf-8")
    return proj


def _walk(tmp_path: Path, docs: dict) -> tuple:
    """Run the REAL extractor + the REAL emit driver. Returns
    (memories, memory_candidates)."""
    proj = _project(tmp_path, docs)
    extracted = P.extract_text_pipeline(proj, force=True)
    assert extracted, "the real extractor produced nothing — premise broken"
    l9: dict = {}
    P._v1_6_426_emit_memories(l9, extracted)
    return (l9.get("memories") or [], l9.get("memory_candidates") or [])


def _l9_doc(tmp_path: Path, docs: dict) -> dict:
    """Drive the REAL L9 generator end-to-end and return the
    `L9_INTEGRATION_SPEC.json` it writes to disk."""
    proj = _project(tmp_path, docs)
    extracted = P.extract_text_pipeline(proj, force=True)
    res = P.gen_l9_integration_spec(proj, extracted, {})
    out = Path(res.path)
    assert out.is_file(), f"L9 generator wrote nothing at {out}"
    return json.loads(out.read_text(encoding="utf-8"))


# ───────────────────────── defect direction ──────────────────────────

def test_real_spm_doc_end_to_end_emits_no_memory_candidate(tmp_path):
    """THE DEFECT, on the REAL on-disk benchmark doc, end-to-end.

    Pre-fix `L9_INTEGRATION_SPEC.json` carries exactly one
    `"low_confidence": true` — the fabricated regfile row — and that single
    row is what downgraded Step D1 to WAIVED-DEFERRED.
    """
    src = require_repo("benchmark-data", "ic", "spm", "input", "docs",
                       "L5_register_map.md")
    body = src.read_text(encoding="utf-8")
    # PREMISE — the two signals this fix keys on are really in the file. If
    # the benchmark doc is ever rewritten, fail loudly instead of passing
    # vacuously on an input that no longer carries the defect.
    assert "status: not-applicable" in body, (
        "premise broken: the real doc no longer declares status: "
        "not-applicable")
    assert "不需 Plugin 產生 register file" in body, (
        "premise broken: the real doc no longer carries the denial sentence")

    doc = _l9_doc(tmp_path, {"L5_register_map.md": body})

    assert doc.get("memory_candidates") == [], (
        "the walker harvested a memory candidate out of the sentence "
        "instructing it NOT to generate one: "
        f"{json.dumps(doc.get('memory_candidates'), ensure_ascii=False)}")
    assert doc.get("memories") == []
    assert doc.get("no_memory_candidates_in_input") is True
    blob = json.dumps(doc, ensure_ascii=False)
    assert blob.count('"low_confidence": true') == 0, (
        "a low_confidence row survives in L9_INTEGRATION_SPEC.json — the "
        "in-gate stub-backed rule (#434) reads that as DEFERRED work and "
        "downgrades Step D1")


def test_denial_prose_yields_no_candidate(tmp_path):
    """Same proof, self-contained so it also runs on the installed cache."""
    mems, cands = _walk(tmp_path, {"L5_register_map.md": DENIAL_DOC})
    assert mems == []
    assert cands == [], (
        f"denial prose fabricated {len(cands)} memory candidate(s): "
        f"{json.dumps(cands, ensure_ascii=False)}")


def test_frontmatter_not_applicable_alone_suppresses(tmp_path):
    """SIGNAL 1 IN ISOLATION. The memory sentence here carries NO negation
    marker, so the sentence-level guard cannot see it — only the doc's own
    `status: not-applicable` frontmatter can. Without the frontmatter signal
    this row is harvested with depth/width/name fully populated."""
    doc = """---
layer: L5
ic: demo_na
status: not-applicable
written_at: 2026-07-26
---

# L5 — Register Map

## 適用性 — N/A

本層不適用於本設計。

以下段落沿用文件樣板,僅供排版參考:
The template example shows a register file 32x8 in `example_regfile.v`.
"""
    mems, cands = _walk(tmp_path, {"L5_register_map.md": doc})
    assert mems == [], (
        "a doc that declares its own status: not-applicable still yielded "
        f"memories: {json.dumps(mems, ensure_ascii=False)}")
    assert cands == []


def test_negated_sentence_in_same_file_yields_no_candidate(tmp_path):
    """The denial half of the mixed document must produce no candidate."""
    doc = """---
layer: L5
ic: demo_mixed
status: applicable
written_at: 2026-07-26
---

# L5 — Register Map

本設計不需 Plugin 產生 register file / CSR decoder / memory-mapped interface。

However the datapath DOES carry its own private storage: the accumulator
register file 16x24 is implemented in `acc_regfile.v` and is not SW-visible.
"""
    _mems, cands = _walk(tmp_path, {"L5_register_map.md": doc})
    assert cands == [], (
        "the denial sentence still fabricated a candidate: "
        f"{json.dumps(cands, ensure_ascii=False)}")


def test_shared_negation_predicate_sees_zh_and_na(tmp_path):
    """The two markers the shared vocabulary could not previously see."""
    def negated(text, kw):
        i = text.find(kw)
        assert i >= 0, f"{kw!r} not in fixture"
        return P._v0_1_62_analog_kw_negated(text, i, i + len(kw))

    assert negated("`spm` **無 SW-visible registers**。", "registers"), (
        "bare 無 before a Latin term is a denial")
    assert negated("- 無 control register", "register")
    assert negated("| Register file | N/A — no SW-visible state |", "N/A")
    assert negated("Register file: n/a for this block.", "n/a")


# ───────────────────── true-positive controls ────────────────────────

def test_genuine_register_file_still_harvested(tmp_path):
    """A real register-file spec must STILL be harvested, fields populated."""
    doc = """---
layer: L5
ic: demo_dsp
status: applicable
written_at: 2026-07-26
---

# L5 — Register Map

`demo_dsp` exposes a SW-visible register block.

The scratch register file 32x8 (2 read ports, 1 write port) is implemented in
`regfile_scratch.v` and feeds the MAC datapath directly.

A dual-port SRAM 1024x16 holds the coefficient bank, see `coeff_sram.v`.
"""
    mems, _cands = _walk(tmp_path, {"L5_register_map.md": doc})
    by_kind = {m["kind"]: m for m in mems}
    assert "regfile" in by_kind, (
        f"the genuine register file was suppressed; got {mems}")
    rf = by_kind["regfile"]
    assert rf["depth"] == 32 and rf["width"] == 8
    assert rf["name"], "the genuine register file lost its name"
    assert rf["low_confidence"] is False
    assert "ram" in by_kind, f"the genuine SRAM was suppressed; got {mems}"
    sram = by_kind["ram"]
    assert sram["depth"] == 1024 and sram["width"] == 16
    assert sram["port_count"] == "dual"


def test_negated_sentence_does_not_shadow_real_spec_in_same_file(tmp_path):
    """A doc that DENIES a register file in one sentence and SPECIFIES one in
    another must still yield the real one — the guard skips the MATCH, never
    the rest of the document."""
    doc = """---
layer: L5
ic: demo_mixed
status: applicable
written_at: 2026-07-26
---

# L5 — Register Map

本設計不需 Plugin 產生 register file / CSR decoder / memory-mapped interface。

However the datapath DOES carry its own private storage: the accumulator
register file 16x24 is implemented in `acc_regfile.v` and is not SW-visible.
"""
    mems, _cands = _walk(tmp_path, {"L5_register_map.md": doc})
    assert len(mems) == 1, f"expected exactly the real regfile, got {mems}"
    rf = mems[0]
    assert rf["kind"] == "regfile"
    assert rf["depth"] == 16 and rf["width"] == 24
    assert rf["name"] == "acc_regfile"


def test_not_applicable_file_does_not_suppress_sibling_file(tmp_path):
    """A not-applicable frontmatter is scoped to ITS OWN file."""
    sibling = """---
layer: L9
ic: demo_two_file
status: applicable
written_at: 2026-07-26
---

# L9 — Integration Spec

The tile instantiates a single-port SRAM 512x32 implemented in `tile_sram.v`,
plus a register file 8x32 in `tile_regfile.v` for the local scoreboard.
"""
    mems, cands = _walk(tmp_path, {
        "L5_register_map.md": DENIAL_DOC,      # status: not-applicable
        "L9_integration.md": sibling,          # genuine evidence
    })
    kinds = {m["kind"] for m in mems}
    assert kinds == {"ram", "regfile"}, (
        "the not-applicable L5 suppressed the genuine L9 evidence; "
        f"got {json.dumps(mems, ensure_ascii=False)}")
    assert all(m["evidence_file"] == "L9_integration.md" for m in mems)
    assert cands == []


def test_status_tbd_is_not_not_applicable(tmp_path):
    """`tbd` / `todo` / `draft` mean NOT WRITTEN YET, not DOES NOT EXIST. A
    doc that already carries a real memory paragraph must still be harvested,
    so the applicability-denial set can never be widened into a general
    no-information set."""
    for status in ("tbd", "todo", "draft", "pending", "unknown"):
        doc = f"""---
layer: L9
ic: demo_tbd
status: {status}
written_at: 2026-07-26
---

# L9 — Integration Spec

The fetch unit owns a single-port ROM 4096x32 in `boot_rom.v`.
"""
        mems, _ = _walk(tmp_path / status, {"L9_integration.md": doc})
        assert len(mems) == 1, (
            f"status: {status} must NOT suppress genuine evidence; got {mems}")
        assert mems[0]["depth"] == 4096 and mems[0]["width"] == 32


def test_cjk_compound_wu_is_not_a_negation():
    """NO-LEAK on the widened vocabulary. Bare `無` negates only when it
    precedes a Latin/ASCII term. Glued to a CJK character it is a COMPOUND
    WORD — 無線 (wireless), 無源 (passive), 無限 (unlimited), 無論
    (regardless) — all of which carry real design content. Reading those as
    denials would silently drop genuine analog and memory evidence."""
    def negated(text, kw):
        i = text.find(kw)
        assert i >= 0, f"{kw!r} not in fixture"
        return P._v0_1_62_analog_kw_negated(text, i, i + len(kw))

    assert not negated("無線收發器內含一顆 12-bit DAC。", "DAC")
    assert not negated("無源濾波器後接 bandgap 基準。", "bandgap")
    assert not negated("無限深度佇列由 FIFO 實作。", "FIFO")
    assert not negated("無論組態為何,RAM 皆為單埠。", "RAM")


def test_doc_declares_not_applicable_is_conservative():
    """The frontmatter reader fails OPEN — a guard that guesses drops real
    evidence."""
    assert P._doc_declares_not_applicable(
        "---\nlayer: L5\nstatus: not-applicable\n---\n\nbody") is True
    assert P._doc_declares_not_applicable(
        "---\nlayer: L5\nstatus: N/A\n---\n\nbody") is True
    assert P._doc_declares_not_applicable(
        "---\nlayer: L5\nstatus: 不適用\n---\n\nbody") is True
    # no frontmatter / no status key / other status / junk → keep harvesting
    assert P._doc_declares_not_applicable("# L5\n\nstatus: not-applicable") is False
    assert P._doc_declares_not_applicable("---\nlayer: L5\n---\n\nbody") is False
    assert P._doc_declares_not_applicable(
        "---\nstatus: applicable\n---\n\nbody") is False
    assert P._doc_declares_not_applicable("") is False
    assert P._doc_declares_not_applicable(None) is False
