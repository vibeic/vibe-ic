"""ORGANIC — the negation guard's CLAUSE SCOPE over-reached, and the
over-reach silently DELETED genuine memories.

DEFECT
======
`_v0_1_62_analog_kw_negated` decides "is this keyword inside a denial?" by
searching the text from the CLAUSE START up to the keyword. It is shared by
`gen_l5_adi_spec` (analog blocks) and `_v1_6_426_extract_memories_from_text`
(the L9 memory prose walker). Its notion of "clause" was too coarse in two
ways, and each way suppressed hardware a design genuinely has.

(1) THE COMMA WAS NOT A SEPARATOR. Hard delimiters were only ``\\n 。！？； ;``
    and ``". "``. Neither ``,`` nor ``，`` split a clause, so "negate A, but
    specify B" written on ONE line lost B as well. Measured end-to-end
    through `extract_text_pipeline` -> `_v1_6_426_emit_memories`:

      A1  "There is no external DRAM, but the tile instantiates an on-chip
           single-port SRAM 1024x32 in `buf_sram.v`."
          -> {buf_sram, ram/SRAM, single, 1024x32, low_confidence: False}
             was DELETED.
      A2  "The datapath shall not stall on a write conflict, and the scratch
           register file 32x8 (2 read ports, 1 write port) in
           `regfile_scratch.v` feeds the MAC directly."
          -> {regfile_scratch, regfile, 32x8, low_confidence: False}
             was DELETED.

(2) A MARKER FIRED FROM A DIFFERENT TABLE COLUMN. A markdown row is not a
    sentence — each cell is its own scope. Specification documents are
    written as tables, so this is not an edge case:

      A4  | buf0 | N/A | single-port SRAM 1024x32 | `buf_sram.v` |
          the N/A is the value of an ECC column.
      A5  | acc0 | No  | register file 16x24      | `acc_regfile.v` |
          the No is the value of a SW-visible column.

    Both memories were DELETED by a marker belonging to a sibling cell.

THE REPAIR, AND WHY IT CANNOT SWING BACK
========================================
Both halves only ever move the clause START FORWARD, so the text handed to
`_RE_ANALOG_NEGATION` is always a SUBSET of what the pre-repair code searched.
``True -> False`` is reachable; ``False -> True`` is not. That monotonicity is
asserted directly by `test_clause_scope_repair_is_monotone_on_the_real_corpus`
over every benchmark document in the repo: the repair can never lose a row
that is harvested today, so the ONLY risk it carries is admitting a denial.
Every control below bounds exactly that risk.

  * COMMA — a comma opens a new clause only when what follows is a NEW
    PREDICATION (an adversative opener, or a finite verb: auxiliary / modal /
    copula / third-person ``-s`` form / zh predication verb). "no A, B, or C"
    is ONE denial with an elided list and must keep its reach over B and C.
    An unrecognised verb is NOT a boundary, so the rule fails closed onto the
    pre-repair behaviour.
  * TABLE — a line is a table row only when it carries >= 2 CELL-delimiting
    pipes (escaped ``\\|`` and pipes inside `` `a|b` `` do not delimit) and
    either starts with ``|`` or belongs to a pipe-bearing block containing an
    alignment row. Alignment rows are not data rows. A denial in the keyword's
    OWN cell still suppresses.

BIDIRECTIONAL
=============
FAIL-AGAINST-bcf9694ab (the defect direction — the four cases that refuted the
previous attempt, plus the shared-guard sibling):
  test_a1_comma_but_clause_still_harvests_the_sram
  test_a2_comma_and_clause_still_harvests_the_register_file
  test_a4_ecc_column_na_does_not_delete_the_sibling_memory_cell
  test_a5_sw_visible_column_no_does_not_delete_the_sibling_memory_cell
  test_fullwidth_comma_zh_adversative_clause_still_harvests
  test_borderless_gfm_table_row_is_cell_scoped
  test_escaped_pipe_in_a_sibling_cell_does_not_break_cell_scope
  test_analog_sibling_cell_no_column_still_detects_the_adc

CONTROLS (they pass on BOTH sides — the way to get this change wrong is to
over-split and start FABRICATING again, which no test can detect by failing
against the unfixed code; each is instead proven live by MUTATION, recorded
in the commit message):
  test_comma_does_not_oversplit_repeated_no_list
  test_comma_does_not_oversplit_elided_noun_list
  test_comma_does_not_oversplit_articled_denial_list
  test_zh_enumeration_denial_still_suppressed
  test_denial_inside_the_keywords_own_cell_still_suppresses
  test_pipe_in_prose_is_not_a_table_row
  test_pipe_inside_an_inline_code_span_does_not_delimit_a_cell
  test_alignment_row_is_not_a_data_row
  test_real_spm_denial_doc_still_yields_zero_memory_candidates
  test_analog_pure_digital_denials_still_suppressed
  test_real_analog_ic_blocks_unchanged
  test_clause_scope_repair_is_monotone_on_the_real_corpus
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _hostpaths import require_repo

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as P  # noqa: E402


_FM = ("---\n"
       "layer: L9\n"
       "ic: demo_scope\n"
       "status: applicable\n"
       "written_at: 2026-07-26\n"
       "---\n\n"
       "# L9 — Integration Spec\n\n")


def _project(tmp_path: Path, docs: dict) -> Path:
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True, exist_ok=True)
    for name, body in docs.items():
        (proj / "input" / "docs" / name).write_text(body, encoding="utf-8")
    return proj


def _walk(tmp_path: Path, body: str, fname: str = "L9_integration.md"):
    """REAL extractor + REAL emit driver -> (memories, memory_candidates)."""
    proj = _project(tmp_path, {fname: _FM + body})
    extracted = P.extract_text_pipeline(proj, force=True)
    assert extracted, "the real extractor produced nothing — premise broken"
    l9: dict = {}
    P._v1_6_426_emit_memories(l9, extracted)
    return (l9.get("memories") or [], l9.get("memory_candidates") or [])


def _l9_doc(tmp_path: Path, body: str, fname: str = "L9_integration.md"):
    """Drive the REAL L9 generator and return the JSON it wrote to disk."""
    proj = _project(tmp_path, {fname: _FM + body})
    extracted = P.extract_text_pipeline(proj, force=True)
    res = P.gen_l9_integration_spec(proj, extracted, {})
    out = Path(res.path)
    assert out.is_file(), f"L9 generator wrote nothing at {out}"
    return json.loads(out.read_text(encoding="utf-8"))


def _analog_classes(tmp_path: Path, body: str):
    """REAL analog L5 generator -> the list of analog_blocks it emitted."""
    proj = _project(
        tmp_path,
        {"L5_ANALOG_SPEC.md":
            "---\nlayer: L5\nic: demo_ams\nstatus: applicable\n---\n\n"
            "# L5 — Analog Spec\n\n" + body})
    extracted = P.extract_text_pipeline(proj, force=True)
    res = P.gen_l5_adi_spec(proj, extracted)
    doc = json.loads(Path(res.path).read_text(encoding="utf-8"))
    return doc.get("analog_blocks") or []


# ═══════════════════ defect direction — the four refuting cases ═══════════

def test_a1_comma_but_clause_still_harvests_the_sram(tmp_path):
    """A1. The denial governs the EXTERNAL DRAM; the on-chip SRAM is the
    object of a NEW predication after the comma. Pre-repair the comma was not
    a separator, so `no` reached across it and the SRAM was deleted."""
    mems, cands = _walk(
        tmp_path,
        "There is no external DRAM, but the tile instantiates an on-chip "
        "single-port SRAM 1024x32 in `buf_sram.v`.\n")
    assert cands == [], f"fabricated a candidate: {cands}"
    assert len(mems) == 1, (
        "the genuine on-chip SRAM was deleted by a denial that governs a "
        f"DIFFERENT noun; got {json.dumps(mems, ensure_ascii=False)}")
    m = mems[0]
    assert m["name"] == "buf_sram"
    assert m["kind"] == "ram" and m["type"].upper() == "SRAM"
    assert m["port_count"] == "single"
    assert m["depth"] == 1024 and m["width"] == 32
    assert m["low_confidence"] is False


def test_a2_comma_and_clause_still_harvests_the_register_file(tmp_path):
    """A2. The denial governs a BEHAVIOUR ("shall not stall"); the register
    file is the subject of the clause after the comma."""
    mems, cands = _walk(
        tmp_path,
        "The datapath shall not stall on a write conflict, and the scratch "
        "register file 32x8 (2 read ports, 1 write port) in "
        "`regfile_scratch.v` feeds the MAC directly.\n")
    assert cands == [], f"fabricated a candidate: {cands}"
    assert len(mems) == 1, (
        "the genuine scratch register file was deleted by a denial that "
        f"governs a behaviour; got {json.dumps(mems, ensure_ascii=False)}")
    m = mems[0]
    assert m["name"] == "regfile_scratch"
    assert m["kind"] == "regfile"
    assert m["depth"] == 32 and m["width"] == 8
    assert m["low_confidence"] is False


def test_a4_ecc_column_na_does_not_delete_the_sibling_memory_cell(tmp_path):
    """A4, END-TO-END on the JSON `gen_l9_integration_spec` actually writes.
    The `N/A` is the value of an ECC column and says nothing about the memory
    specified in the NEXT column."""
    doc = _l9_doc(
        tmp_path,
        "| Buffer | ECC | Memory | RTL |\n"
        "|--------|-----|--------|-----|\n"
        "| buf0 | N/A | single-port SRAM 1024x32 | `buf_sram.v` |\n")
    mems = doc.get("memories") or []
    assert doc.get("memory_candidates") == []
    assert len(mems) == 1, (
        "an N/A in the ECC COLUMN deleted the memory specified in a sibling "
        f"cell; got {json.dumps(mems, ensure_ascii=False)}")
    m = mems[0]
    assert m["name"] == "buf_sram"
    assert m["kind"] == "ram" and m["port_count"] == "single"
    assert m["depth"] == 1024 and m["width"] == 32
    assert m["low_confidence"] is False
    assert doc.get("no_memories_in_input") is False, (
        "the schema sentinel still claims the input carries no memory")


def test_a5_sw_visible_column_no_does_not_delete_the_sibling_memory_cell(
        tmp_path):
    """A5, END-TO-END on the JSON `gen_l9_integration_spec` actually writes.
    The `No` is the value of a SW-visible column."""
    doc = _l9_doc(
        tmp_path,
        "| Block | SW-visible | Memory | RTL |\n"
        "|-------|------------|--------|-----|\n"
        "| acc0 | No | register file 16x24 | `acc_regfile.v` |\n")
    mems = doc.get("memories") or []
    assert doc.get("memory_candidates") == []
    assert len(mems) == 1, (
        "a No in the SW-VISIBLE COLUMN deleted the memory specified in a "
        f"sibling cell; got {json.dumps(mems, ensure_ascii=False)}")
    m = mems[0]
    assert m["name"] == "acc_regfile"
    assert m["kind"] == "regfile"
    assert m["depth"] == 16 and m["width"] == 24
    assert m["low_confidence"] is False


def test_fullwidth_comma_zh_adversative_clause_still_harvests(tmp_path):
    """The full-width `，` must separate exactly as the ASCII `,` does."""
    mems, _ = _walk(
        tmp_path,
        "本設計不含外部 DRAM，但 tile 內含一顆 single-port SRAM 1024x32，"
        "見 `buf_sram.v`。\n")
    assert len(mems) == 1, (
        "the full-width comma is not a clause separator; got "
        f"{json.dumps(mems, ensure_ascii=False)}")
    assert mems[0]["depth"] == 1024 and mems[0]["width"] == 32
    assert mems[0]["low_confidence"] is False


def test_borderless_gfm_table_row_is_cell_scoped(tmp_path):
    """A GFM row without leading/trailing pipes is still a table row when the
    pipe-bearing block it belongs to carries an alignment row."""
    mems, _ = _walk(
        tmp_path,
        "Buffer | ECC | Memory | RTL\n"
        "-------|-----|--------|----\n"
        "buf0 | N/A | single-port SRAM 1024x32 | `buf_sram.v`\n")
    assert len(mems) == 1, (
        "a borderless table row was not cell-scoped; got "
        f"{json.dumps(mems, ensure_ascii=False)}")
    assert mems[0]["name"] == "buf_sram"
    assert mems[0]["depth"] == 1024 and mems[0]["width"] == 32


def test_escaped_pipe_in_a_sibling_cell_does_not_break_cell_scope(tmp_path):
    """`\\|` is the markdown way to put a literal pipe INSIDE a cell. It must
    not be counted as a cell delimiter, or the cell boundaries shift and the
    guard reads the wrong cell."""
    mems, _ = _walk(
        tmp_path,
        "| Buffer | ECC \\| parity | Memory | RTL |\n"
        "|--------|--------------|--------|-----|\n"
        "| buf0 | N/A \\| none | single-port SRAM 1024x32 | `buf_sram.v` |\n")
    assert len(mems) == 1, (
        "an escaped pipe broke cell scope; got "
        f"{json.dumps(mems, ensure_ascii=False)}")
    assert mems[0]["name"] == "buf_sram"
    assert mems[0]["depth"] == 1024 and mems[0]["width"] == 32


def test_analog_sibling_cell_no_column_still_detects_the_adc(tmp_path):
    """SHARED GUARD, defect direction. `_v0_1_62_analog_kw_negated` is also
    the analog path's predicate, so the table-cell repair must reach analog
    block detection too: a `No` in an EXTERNAL column must not delete the ADC
    specified in the next cell."""
    blocks = _analog_classes(
        tmp_path,
        "| Block | External | Spec |\n"
        "|-------|----------|------|\n"
        "| adc0 | No | 12-bit ADC, 1.8 V reference, 5 mV LSB |\n")
    names = [b.get("name") for b in blocks]
    assert "adc" in names, (
        "a No in a SIBLING COLUMN deleted the genuine ADC block; got "
        f"{json.dumps(blocks, ensure_ascii=False)}")


# ═══════════════════════ controls — the over-split direction ══════════════

def test_comma_does_not_oversplit_repeated_no_list(tmp_path):
    """The owner's own over-split control. Each item repeats its own `no`, so
    even a naive splitter survives this one — it is the floor, not the bar."""
    mems, cands = _walk(
        tmp_path,
        "The design requires no register file, no CSR decoder, and no "
        "memory-mapped interface.\n")
    assert mems == [] and cands == [], (
        "a denial that governs the whole sentence fabricated hardware: "
        f"{json.dumps(mems + cands, ensure_ascii=False)}")


def test_comma_does_not_oversplit_elided_noun_list(tmp_path):
    """THE REAL BAR. One `no` governing an ELIDED list — the later items carry
    no negation marker of their own. An unconditional comma split fabricates
    `cache` and `FIFO` here, which is the exact defect the guard exists to
    close, re-opened in a different document."""
    mems, cands = _walk(
        tmp_path,
        "There is no external DRAM, cache, or FIFO in this design.\n")
    assert mems == [] and cands == [], (
        "an elided denial list was over-split and fabricated hardware: "
        f"{json.dumps(mems + cands, ensure_ascii=False)}")


def test_comma_does_not_oversplit_articled_denial_list(tmp_path):
    """Same shape with articles, which is how the denial is normally written,
    and with the DIMENSIONED item in the middle so an over-split fabricates a
    fully populated `32x8` row. Proves the boundary test keys on a VERB, not
    on a determiner — `a` / `the` head both a denied list item and a genuine
    new clause, so a determiner-based splitter fabricates here."""
    mems, cands = _walk(
        tmp_path,
        "This design does not include a CSR decoder, a register file 32x8, "
        "or a memory-mapped interface.\n")
    assert mems == [] and cands == [], (
        "an articled denial list was over-split: "
        f"{json.dumps(mems + cands, ensure_ascii=False)}")


def test_zh_enumeration_denial_still_suppressed(tmp_path):
    """The `、` enumeration comma is NOT a separator, and must never become
    one: the analog defect #358 is literally
    `不需 Plugin 產生 calibration controller、OTP interface、analog trim DAC`.
    The DIMENSIONED item sits in the middle, so promoting `、` to a separator
    fabricates a fully populated `32x8` register file out of the denial."""
    mems, cands = _walk(
        tmp_path,
        "→ 不需 Plugin 產生 CSR decoder、register file 32x8、memory-mapped "
        "interface 等。\n")
    assert mems == [] and cands == [], (
        "the zh enumeration comma was treated as a clause separator: "
        f"{json.dumps(mems + cands, ensure_ascii=False)}")


def test_denial_inside_the_keywords_own_cell_still_suppresses(tmp_path):
    """Cell scope narrows, it does not blind: a marker in the keyword's OWN
    cell is still seen."""
    mems, cands = _walk(
        tmp_path,
        "| Block | Memory |\n|-------|--------|\n"
        "| acc0 | no register file 16x24 |\n")
    assert mems == [] and cands == [], (
        "a denial in the keyword's own cell stopped suppressing: "
        f"{json.dumps(mems + cands, ensure_ascii=False)}")


def test_pipe_in_prose_is_not_a_table_row(tmp_path):
    """A line that merely CONTAINS pipes is not a table row. Treating it as
    one would cut the denial off from its object: the keyword sits after two
    pipes here, so a naive "two pipes means table" rule scopes the guard to a
    phantom cell and fabricates the cache."""
    line = "sel = a | b | c;"
    assert P._neg_md_line_is_table_row(line, 0, len(line)) is False
    mems, cands = _walk(
        tmp_path,
        "There is no ECC | parity | cache in this tile.\n")
    assert mems == [] and cands == [], (
        "a prose line containing pipes was read as a table row: "
        f"{json.dumps(mems + cands, ensure_ascii=False)}")


def test_pipe_inside_an_inline_code_span_does_not_delimit_a_cell(tmp_path):
    """A pipe inside `` `a|b` `` is content, not a cell boundary. Counting it
    shifts every boundary to its right, so the guard reads a truncated cell
    and loses the denial that is standing right there in it."""
    line = "| sel | `a|b` | RAM 8x8 |"
    assert P._neg_md_row_pipe_positions(line) == [0, 6, 14, 24], (
        "the code-span pipe was counted as a cell delimiter: "
        f"{P._neg_md_row_pipe_positions(line)}")
    mems, cands = _walk(
        tmp_path,
        "| Block | Memory |\n|-------|--------|\n"
        "| acc0 | none `a|b` register file 16x24 |\n")
    assert mems == [] and cands == [], (
        "a code-span pipe shifted the cell boundary and lost the denial: "
        f"{json.dumps(mems + cands, ensure_ascii=False)}")


def test_alignment_row_is_not_a_data_row():
    """`|---|---|` delimits a table; it is not a row that can hold a keyword,
    and it must not be mistaken for the frontmatter `---` fence either."""
    assert P._neg_md_is_alignment_row("|---|---|") is True
    assert P._neg_md_is_alignment_row("|:---|---:|:--:|") is True
    assert P._neg_md_is_alignment_row("-------|-----|----") is True
    assert P._neg_md_is_alignment_row("---") is False          # frontmatter
    assert P._neg_md_is_alignment_row("| a | b |") is False
    assert P._neg_md_is_alignment_row("") is False


def test_real_spm_denial_doc_still_yields_zero_memory_candidates(tmp_path):
    """STEP 5 — THE ORIGINAL DEFECT MUST STAY CLOSED. The real benchmark doc,
    driven end-to-end. If the clause-scope repair swung back, the fabricated
    `register file` row returns and Step D1 goes WAIVED-DEFERRED again."""
    src = require_repo("benchmark-data", "ic", "spm", "input", "docs",
                       "L5_register_map.md")
    body = src.read_text(encoding="utf-8")
    assert "不需 Plugin 產生 register file" in body, (
        "premise broken: the real doc no longer carries the denial sentence")
    proj = _project(tmp_path, {"L5_register_map.md": body})
    extracted = P.extract_text_pipeline(proj, force=True)
    res = P.gen_l9_integration_spec(proj, extracted, {})
    doc = json.loads(Path(res.path).read_text(encoding="utf-8"))
    assert doc.get("memory_candidates") == [], (
        "the clause-scope repair re-opened the original defect: "
        f"{json.dumps(doc.get('memory_candidates'), ensure_ascii=False)}")
    assert doc.get("memories") == []
    blob = json.dumps(doc, ensure_ascii=False)
    assert blob.count('"low_confidence": true') == 0


def test_analog_pure_digital_denials_still_suppressed(tmp_path):
    """SHARED GUARD, control direction. The pure-digital negated document must
    stay suppressed on the analog path — including the comma-list forms the
    repair newly splits on."""
    for body in (
        "→ 不需 Plugin 產生 calibration controller、OTP interface、"
        "analog trim DAC 等。供電 1.8 V。\n",
        "本設計為純數位,不含 ADC, DAC, bandgap 參考。供電 1.8 V,無類比電路。\n",
        "The chip has no ADC, no DAC, and no bandgap reference. "
        "The 1.8 V supply is digital-only.\n",
        "The chip has no ADC, DAC, or bandgap reference on the 1.8 V "
        "supply rail.\n",
        "| Block | Note |\n|-------|------|\n"
        "| trim | no analog trim DAC, 1.8 V digital only |\n",
    ):
        blocks = _analog_classes(tmp_path, body)
        assert blocks == [], (
            "a pure-digital denial fabricated analog blocks: "
            f"{json.dumps(blocks, ensure_ascii=False)} from {body!r}")


def test_real_analog_ic_blocks_unchanged(tmp_path):
    """SHARED GUARD, no-leak. A genuine analog spec is still detected: the
    REAL analog benchmark IC's own docs still yield its analog blocks. The
    docs are copied into tmp_path so the generator never writes into the
    checkout."""
    docs = require_repo("benchmark-data", "ic", "u_hawaii_adc", "input",
                        "docs")
    bodies = {p.name: p.read_text(encoding="utf-8")
              for p in sorted(docs.iterdir()) if p.is_file()}
    assert bodies, "premise broken: the analog IC has no input docs"
    project = _project(tmp_path, bodies)
    extracted = P.extract_text_pipeline(project, force=True)
    assert extracted, "premise broken: the analog IC extracted nothing"
    res = P.gen_l5_adi_spec(project, extracted)
    doc = json.loads(Path(res.path).read_text(encoding="utf-8"))
    names = sorted(b.get("name") for b in (doc.get("analog_blocks") or []))
    assert names == ["delta_sigma", "ldo"], (
        "the clause-scope repair changed analog block detection on the real "
        f"analog IC; got {names}")


def test_clause_scope_repair_is_monotone_on_the_real_corpus():
    """THE INVARIANT that makes this repair safe to ship.

    Both halves only move the clause START forward, so the searched text is a
    SUBSET of the pre-repair clause. Therefore ``new_negated implies
    old_negated`` must hold for EVERY keyword occurrence in EVERY benchmark
    document in the repo. If it ever fails, the repair has started SUPPRESSING
    something the old code kept — the direction that loses hardware."""
    def old_negated(text: str, kw_start: int, kw_end: int) -> bool:
        s_start = 0
        for delim in ("\n", "。", "！", "？", "；", ";", ". "):
            d = text.rfind(delim, 0, kw_start)
            if d >= 0 and d + len(delim) > s_start:
                s_start = d + len(delim)
        return bool(P._RE_ANALOG_NEGATION.search(text[s_start:kw_end]))

    ic_root = require_repo("benchmark-data", "ic")
    checked = 0
    for doc in sorted(ic_root.glob("*/input/docs/*")):
        if not doc.is_file():
            continue
        try:
            text = doc.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in P._V1_6_426_RE_MEMORY_PROSE.finditer(text):
            checked += 1
            new = P._v0_1_62_analog_kw_negated(text, m.start(), m.end())
            if new:
                assert old_negated(text, m.start(), m.end()), (
                    f"NOT MONOTONE in {doc.name} at {m.start()}: the repair "
                    f"suppresses {m.group(0)!r} that the pre-repair guard "
                    "kept — this direction loses genuine hardware")
    assert checked > 100, (
        f"premise broken: only {checked} keyword occurrences scanned across "
        "the benchmark corpus")
