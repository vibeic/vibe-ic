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
import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as R   # noqa: E402
import regmap_table_extractor as E        # noqa: E402

_COMPLETENESS = PROGRAMS / "phase1_doc_input_completeness_check.py"

_DOC = ("+----+----+----+\n| CSR Address | Name | Description |\n"
        "+====+====+====+\n| 0xB00 | mcycle | cyc |\n+----+----+----+\n"
        "| 0xC00 (0xC80)| cycle | pair |\n+----+----+----+\n")


def _registers(class_path, doc):
    d = Path(tempfile.mkdtemp())
    (d / "phase1/input_doc").mkdir(parents=True)
    (d / "phase1/generated_docs").mkdir(parents=True)
    (d / "phase1/generated_docs/L1_DATASHEET.json").write_text(
        json.dumps({"class_path": class_path}))
    (d / "phase1/generated_docs/L4_REGMAP.json").write_text(
        json.dumps({"registers": [], "no_registers_in_input": True}))
    (d / "phase1/input_doc/csr.txt").write_text(doc)
    R._post_emit_pdf_regmap_table_rows(d)
    return json.loads(
        (d / "phase1/generated_docs/L4_REGMAP.json").read_text())["registers"]


def _run(class_path, doc):
    """Every address the capture landed in L4, whether it became a register's
    own address or an alias recorded on the register it belongs to.

    #516 changed WHERE the parenthetical high-word address of an UNNAMED pair
    lands, without changing WHETHER it lands — which is what #800 is about.
    Before #516 the `| 0xC00 (0xC80) | cycle |` row below emitted TWO registers
    both called `cycle`, and an L4 shaped that way is rejected by the sibling
    gate `l4_regmap_phase2_emitter_contract_check`: `emit_regs_v()` declares one
    `reg` per register, so two registers sharing an identifier are not
    buildable. Executed on this very fixture, pristine yields
    "1 Verilog identifier(s) are claimed by 2 different L4 registers" (rc=1).
    The name cell here says `cycle` and nothing else, so the companion
    register's NAME is simply not stated; #516 records its address as an alias
    on the register the document DID name rather than inventing a second name
    or duplicating the first. This helper therefore asserts #800's actual
    contract — no address token is lost — instead of the intermediate shape.
    """
    out = []
    for r in _registers(class_path, doc):
        if r.get("addr_hex"):
            out.append(r["addr_hex"])
        out.extend(r.get("alias_addr_hex") or [])
    return sorted(out)


def test_800_processor_cpu_csr_table_captured_with_high_word_alias():
    # processor_cpu is NOT in the old allow-list; content trigger captures it,
    # incl. the 0xc80 parenthetical high-word alias.
    assert _run("processor_cpu", _DOC) == ["0xb00", "0xc00", "0xc80"]


def test_800_existing_regmap_class_unaffected():
    assert _run("memory_controller", _DOC) == ["0xb00", "0xc00", "0xc80"]


def test_800_pair_capture_does_not_duplicate_a_register_name():
    """#516 regression guard on #800's own fixture: capturing the high-word
    address must not put two registers with one name into L4."""
    names = [r.get("name") for r in _registers("processor_cpu", _DOC)]
    assert len(names) == len(set(names)), names


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


# ── END-STATE: the P0 phase1_doc_input_completeness_check (the real program the
#    issue says FAILed on the un-captured tokens) now PASSes after the
#    content-trigger captures the processor_cpu CSR address tokens into L4. ──────
def _proc_cpu_project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "phase1/input_doc").mkdir(parents=True)
    (proj / "phase1/generated_docs").mkdir(parents=True)
    (proj / "phase1/generated_docs/L1_DATASHEET.json").write_text(
        json.dumps({"class_path": "processor_cpu"}))
    (proj / "phase1/generated_docs/L4_REGMAP.json").write_text(
        json.dumps({"registers": [], "no_registers_in_input": True}))
    (proj / "phase1/input_doc/csr.txt").write_text(_DOC)
    return proj


def test_800_endstate_completeness_check_passes_after_content_trigger(tmp_path):
    proj = _proc_cpu_project(tmp_path)
    R._post_emit_pdf_regmap_table_rows(proj)        # the content-trigger fix
    r = subprocess.run(
        [sys.executable, str(_COMPLETENESS), str(proj)],
        capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout + r.stderr)  # un-captured-tokens FAIL gone
    assert "PASS" in r.stdout
    # the captured CSR addresses are no longer reported uncaptured.
    assert "0xb00" not in r.stdout.lower()
    assert "0xc80" not in r.stdout.lower()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
