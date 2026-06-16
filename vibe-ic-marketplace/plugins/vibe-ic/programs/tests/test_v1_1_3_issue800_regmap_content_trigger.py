"""ORGANIC #800 (gapJ, P0) — phase1_doc_one_shot_runner._post_emit_pdf_regmap_
table_rows gated the register-table extractor on a CLASS ALLOW-LIST
(_REGMAP_TABLE_CLASSES), a proxy for "this IC's docs have a 0x.. address table".
That under-fired: a `processor_cpu` whose CSR/memory-map doc IS such a table was
hard-excluded by an early return, so its hex address tokens never reached
extract_regmap_table() and never landed in any L*.json → the P0
phase1_doc_input_completeness_check FAILed.

FIX 1 (content trigger): run the picker for ANY class; the structurally-strict
extractor decides per-doc (emits rows only for genuine 0x.. tables, [] for prose).
FIX 2 (extractor): a `0xLOW (0xHIGH)` CSR offset cell carries TWO addresses (the
low-word + the parenthetical upper-32b companion of a 64b counter pair) — emit a
row for each (the high-word alias was silently dropped).

§4.05 no-leak: a class whose docs contain no address table appends NOTHING (no
spurious rows); `_offset_addrs` on a prose cell returns []. chip-AGNOSTIC.
"""
import json
import sys
import tempfile
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as R   # noqa: E402
import regmap_table_extractor as E        # noqa: E402

_DOC = ("+----+----+----+\n| CSR Address | Name | Description |\n"
        "+====+====+====+\n| 0xB00 | mcycle | cyc |\n+----+----+----+\n"
        "| 0xC00 (0xC80)| cycle | pair |\n+----+----+----+\n")


def _run(class_path, doc):
    d = Path(tempfile.mkdtemp())
    (d / "phase1/input_doc").mkdir(parents=True)
    (d / "phase1/generated_docs").mkdir(parents=True)
    (d / "phase1/generated_docs/L1_DATASHEET.json").write_text(
        json.dumps({"class_path": class_path}))
    (d / "phase1/generated_docs/L4_REGMAP.json").write_text(
        json.dumps({"registers": [], "no_registers_in_input": True}))
    (d / "phase1/input_doc/csr.txt").write_text(doc)
    R._post_emit_pdf_regmap_table_rows(d)
    regs = json.loads(
        (d / "phase1/generated_docs/L4_REGMAP.json").read_text())["registers"]
    return sorted(r["addr_hex"] for r in regs)


def test_800_processor_cpu_csr_table_captured_with_high_word_alias():
    # processor_cpu is NOT in the old allow-list; content trigger captures it,
    # incl. the 0xc80 parenthetical high-word alias.
    assert _run("processor_cpu", _DOC) == ["0xb00", "0xc00", "0xc80"]


def test_800_existing_regmap_class_unaffected():
    assert _run("memory_controller", _DOC) == ["0xb00", "0xc00", "0xc80"]


def test_800_noleak_no_address_table_yields_no_rows():
    prose = ("This core has registers. The mcycle counter increments each "
             "cycle. See the manual section about 0x10 offsets in passing.\n")
    assert _run("processor_cpu", prose) == []


def test_800_offset_addrs_parenthetical_pair():
    assert E._offset_addrs("0xC00 (0xC80)") == ["0xc00", "0xc80"]


def test_800_offset_addrs_plain_single():
    assert E._offset_addrs("0xC00") == ["0xc00"]


def test_800_offset_addrs_prose_cell_empty():
    assert E._offset_addrs("see 0x10 in the notes") == []


def test_800_offset_addrs_dedups_identical_pair():
    assert E._offset_addrs("0xC00 (0xC00)") == ["0xc00"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
