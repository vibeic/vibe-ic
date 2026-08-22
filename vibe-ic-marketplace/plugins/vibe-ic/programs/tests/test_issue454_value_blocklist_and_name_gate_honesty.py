"""Regression tests for the two findings #454 (v1.7.42) RECORDED but did
not fix.

DEFECT A — a hard-coded hex VALUE blocklist
-------------------------------------------
`phase1_post_process.HALLUC_PATTERNS` carried
`opcode_from_two_digit_decimal_page_number`, an alternation of eight
literal encodings (`0x16|17|23|24|47|48|55|56`) that deleted those values
out of ANY design's L3. It existed because the Strategy-1 walker reads a
row as `<rx_len> <tx_len> <tx_addr> <opcode_hex>`, and a bus-protocol
figure that draws a data word as adjacent bit fields prints its axis in
the identical 4-column shape:

    31           24 23           16 15            8 7             0

so the DECIMAL bit index 16 became opcode `0x16`.

MEASURED, over the 62 benchmark designs that ship their extracted input
document, with the blocklist ON versus OFF: the emitted opcode set is
IDENTICAL (26 either way). Its only live effect was to overwrite the
`hex` field of four Strategy-2 REFUSAL RECORDS with the scrub sentinel —
it corrupted the audit trail v1.7.42 had just added, because
`affected_keys` matched the bare leaf key `hex` anywhere in the document.

It was NOT, however, redundant: the artefact it was built for is
reproducible at HEAD (Strategy 1 was never touched by v1.7.42, which only
guarded Strategy 2). So it is replaced, not deleted — by
`_i454_bit_position_ruler_row`, a value-free row-shape predicate. Measured
over six ruler offsets of the identical shape: the eight-value list
stopped four and let two through (`0x32`, `0x40`); the shape predicate
stops all six.

DEFECT B — a gate that measures name PRESENCE
---------------------------------------------
`l3_opcode_name_coverage_check` reported `PASS — 0/18 opcode(s) carry
placeholder names` over 18 scraped pin names, because a scraped signal
name reads as a good name. MEASURED over the committed corpus: 12 designs
verdict PASS, blessing 188 opcodes, of which at least 18 are that
artefact.

The gate cannot tell a command from a pin row — that decision belongs to
the emitter, which now makes it and COUNTS it. What the gate must not do
is state an absence or an endorsement its own input contradicts. It now
reads `non_command_row_refusal_count` and discloses it. It does NOT gain a
new FAIL: measured over the same 62 designs, ZERO have both a non-empty
`opcodes[]` and a non-zero refusal count, so a FAIL-on-refusal rule has no
measured true positive, and a document carrying both a command table and a
pinout chapter is an ordinary correct design.

The `31 24 23 16` / `63 56 55 48` figure rows below are the byte-lane axis
shape of a 32-bit and a 64-bit data word; they reproduce, byte for byte,
the `opcode (rx_len=31 tx_len=24 tx_addr=23)` extraction-evidence record
committed in the benchmark corpus.
"""
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

mod = importlib.import_module("phase1_doc_one_shot_runner")
pp = importlib.import_module("phase1_post_process")

PROGRAMS = Path(mod.__file__).resolve().parent
COV_GATE = PROGRAMS / "l3_opcode_name_coverage_check.py"

# The eight encodings the removed blocklist deleted out of any design.
FORMERLY_BLOCKLISTED = ["0x16", "0x17", "0x23", "0x24",
                        "0x47", "0x48", "0x55", "0x56"]


def _run_l3(tmp_path, docs, l2=None):
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    mod.gen_l3_cmd_protocol(proj, docs, l2 or {})
    return json.loads(
        (proj / "phase1" / "generated_docs" /
         "L3_CMD_PROTOCOL.json").read_text())


def _run_cov_gate(tmp_path, l3_doc):
    proj = tmp_path / "gate_proj"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(
        json.dumps(l3_doc, ensure_ascii=False), encoding="utf-8")
    out = proj / "verdict.json"
    cp = subprocess.run(
        [sys.executable, str(COV_GATE), str(proj), "--json", str(out)],
        capture_output=True, text=True, timeout=60)
    return cp.returncode, json.loads(out.read_text())


# ---------------------------------------------------------------------------
# DEFECT A, unit level — the row-shape predicate
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("row", [
    # 32-bit data word drawn as four byte lanes
    "31           24 23           16 15            8 7             0",
    # upper half of a 64-bit data word
    "63           56 55           48 47           40 39           32",
    # the same shape at offsets the eight-value blocklist did NOT cover
    "47           40 39           32 31           24 23           16",
    "55           48 47           40 39           32 31           24",
    # nibble-wide fields
    "31    28 27    24 23    20 19    16",
    # a bare four-column ruler
    "31 24 23 16",
])
def test_bit_position_ruler_rows_are_refused(row):
    assert mod._i454_bit_position_ruler_row(row) is True


@pytest.mark.parametrize("row", [
    # a command row: the opcode is followed by content a ruler never has
    "8   4   2E  01  AA BB   read the status register",
    "  0x00  PUT_PC   Put a posted Peripheral Channel transaction",
    "70     SET_STATE       set the operating state",
    # spreadsheet byte-data row (sheet tag first, hex bytes after)
    "10  30  4C  43  4D  0A",
    # descending decimals, but the fields are not equal width
    "8 4 3 01 AA BB",
    # descending, equal width, adjacent — but content follows the run, so
    # it is a data row and not an axis
    "9 5 4 00 AA",
    # width-1 fields: a degenerate run, refusing it would be guesswork
    "3 2 1 0",
    # too few columns to be a partition
    "1 0",
])
def test_command_and_data_rows_are_not_refused(row):
    assert mod._i454_bit_position_ruler_row(row) is False


def test_ruler_predicate_is_total_on_degenerate_input():
    for bad in ("", "   ", "\n", None, 17, [], {}):
        assert mod._i454_bit_position_ruler_row(bad) is False


def test_ruler_predicate_carries_no_value_literal():
    """The predicate must describe the SHAPE. If it ever grows a literal
    encoding it has become the blocklist again."""
    src = Path(mod.__file__).read_text(encoding="utf-8")
    start = src.index("def _i454_bit_position_ruler_row")
    body = src[start:src.index("\ndef ", start + 1)]
    assert "0x" not in body.lower(), (
        "the row-shape predicate must not key on any hex encoding")


# ---------------------------------------------------------------------------
# DEFECT A, end to end — the artefact is refused at SOURCE, and counted
# ---------------------------------------------------------------------------
_FIGURE_DOC = """Data bus byte lanes

The figure below shows the byte lanes for a 32-bit data bus.

31           24 23           16 15            8 7             0

The figure below shows the byte lanes for a 64-bit data bus.

63           56 55           48 47           40 39           32
"""


def test_figure_axis_rows_do_not_become_opcodes(tmp_path):
    doc = _run_l3(tmp_path, {"bus_protocol_spec.txt": _FIGURE_DOC})
    assert doc["opcodes"] == [], doc["opcodes"]
    assert doc["no_opcodes_in_input"] is True


def test_the_refusal_is_counted_not_silent(tmp_path):
    doc = _run_l3(tmp_path, {"bus_protocol_spec.txt": _FIGURE_DOC})
    assert doc["non_command_row_refusal_count"] == 2, doc
    reasons = {r["reason"] for r in doc["non_command_row_refusals"]}
    assert reasons == {"bit_position_ruler_row"}, doc
    assert {r["hex"] for r in doc["non_command_row_refusals"]} == {
        "0x16", "0x48"}


@pytest.mark.parametrize("row,expect_hex", [
    # offsets the removed eight-value blocklist did NOT cover — the value
    # list let these through, the shape predicate stops them
    ("47           40 39           32 31           24 23           16",
     "0x32"),
    ("55           48 47           40 39           32 31           24",
     "0x40"),
])
def test_ruler_offsets_outside_the_old_value_list_are_refused(
        tmp_path, row, expect_hex):
    text = "Byte lanes of the data word\n\n" + row + "\n"
    doc = _run_l3(tmp_path, {"bus_protocol_spec.txt": text})
    assert doc["opcodes"] == [], (
        f"{expect_hex} still emitted: {doc['opcodes']}")
    assert doc["non_command_row_refusal_count"] == 1
    assert doc["non_command_row_refusals"][0]["hex"] == expect_hex


def test_a_genuine_command_row_at_a_ruler_offset_still_extracts(tmp_path):
    """ANTI-FALSE-REFUSAL: the artefact is the row's shape, not the value.
    A real command table row landing on one of those encodings must survive
    — this is what the value blocklist could not do."""
    text = (
        "Command table\n\n"
        "RxLen\tTxLen\tTxAddr\tOpcode\tDescription\n"
        "4\t2\t00\t16\tVOUT_MAX     set the output ceiling\n"
        "4\t2\t00\t24\tVOUT_MIN     set the output floor\n"
    )
    doc = _run_l3(tmp_path, {"device_command_spec.txt": text})
    hexes = [o["hex"] for o in doc["opcodes"]]
    assert "0x16" in hexes and "0x24" in hexes, doc["opcodes"]
    assert doc["non_command_row_refusal_count"] == 0


def test_a_refused_encoding_is_not_burnt_for_the_rest_of_the_document(
        tmp_path):
    """A refusal must not consume the encoding. The same document may draw
    a figure axis AND declare a command at the encoding the axis happened
    to land on; the command still has to come through."""
    text = (
        "Byte lanes of the data word\n\n"
        "31           24 23           16 15            8 7             0\n\n"
        "Command table\n\n"
        "RxLen\tTxLen\tTxAddr\tOpcode\tDescription\n"
        "4\t2\t00\t16\tVOUT_MAX     set the output ceiling\n"
    )
    doc = _run_l3(tmp_path, {"device_command_spec.txt": text})
    assert [o["hex"] for o in doc["opcodes"]] == ["0x16"], doc["opcodes"]
    assert doc["opcodes"][0]["name"] == "VOUT_MAX"
    assert doc["non_command_row_refusal_count"] == 1


# ---------------------------------------------------------------------------
# DEFECT A — the blocklist is gone, and cannot come back
# ---------------------------------------------------------------------------
def test_the_hex_value_blocklist_is_gone():
    names = {p.name for p in pp.HALLUC_PATTERNS}
    assert "opcode_from_two_digit_decimal_page_number" not in names
    assert "opcode_hex_in_test_case_value" not in names


@pytest.mark.parametrize("hex_value", FORMERLY_BLOCKLISTED)
def test_no_surviving_scrub_pattern_deletes_a_command_encoding(hex_value):
    doc = {"opcodes": [{"hex": hex_value, "name": "READ_STATUS"}]}
    assert pp.scrub_l_doc(doc, "L3_CMD_PROTOCOL") == []
    assert doc["opcodes"][0]["hex"] == hex_value


def test_the_scrub_cannot_overwrite_a_refusal_record(tmp_path):
    """End to end through the emitter's write chokepoint (which is where
    the scrubber runs): the refusal records must reach disk with their
    encodings intact."""
    doc = _run_l3(tmp_path, {"bus_protocol_spec.txt": _FIGURE_DOC})
    assert len(doc["non_command_row_refusals"]) == 2, doc
    for rec in doc["non_command_row_refusals"]:
        assert rec["hex"].startswith("0x"), rec
    assert "hallucination_scrub_v0_1_60" not in (
        doc.get("extraction_strategy") or {})


# ---------------------------------------------------------------------------
# DEFECT B — the name gate discloses what it cannot measure
# ---------------------------------------------------------------------------
def test_empty_opcodes_with_refusals_is_not_reported_as_an_absence(tmp_path):
    rc, rep = _run_cov_gate(tmp_path, {
        "opcodes": [],
        "no_opcodes_in_input": True,
        "non_command_row_refusal_count": 22,
    })
    assert rc == 0
    assert rep["verdict"] == "VACUOUS_PASS"
    assert rep["non_command_rows_refused"] == 22
    assert "22 candidate row(s)" in rep["reason"]
    assert "NOT AN ABSENCE" in rep["reason"]


def test_named_opcodes_alongside_refusals_are_not_reported_as_endorsed(
        tmp_path):
    rc, rep = _run_cov_gate(tmp_path, {
        "opcodes": [{"hex": "0x10", "name": "WAKE"},
                    {"hex": "0x11", "name": "CLKREQ"}],
        "non_command_row_refusal_count": 7,
    })
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    assert rep["non_command_rows_refused"] == 7
    assert "DISCLOSURE" in rep["reason"]
    assert "not evidence that its row is a command" in rep["reason"]


def test_a_clean_document_gets_no_disclosure_noise(tmp_path):
    """ANTI-FALSE-POSITIVE: a design whose walker refused nothing must read
    exactly as it did before."""
    rc, rep = _run_cov_gate(tmp_path, {
        "opcodes": [{"hex": "0x00", "name": "PUT_PC"},
                    {"hex": "0x01", "name": "GET_PC"}],
        "non_command_row_refusal_count": 0,
    })
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["non_command_rows_refused"] == 0
    assert "DISCLOSURE" not in rep["reason"]
    assert rep["reason"].strip() == (
        "0/2 opcode(s) carry placeholder names (threshold 0%).")


def test_a_document_without_the_counter_reports_unknown_not_zero(tmp_path):
    """An L3 emitted before the counter existed must not be read as if it
    had refused nothing."""
    rc, rep = _run_cov_gate(tmp_path, {
        "opcodes": [{"hex": "0x00", "name": "PUT_PC"}],
    })
    assert rc == 0
    assert rep["non_command_rows_refused"] is None
    assert "UNKNOWN" in rep["reason"]


@pytest.mark.parametrize("bad", [-1, "22", True, None, 3.5])
def test_a_malformed_counter_is_treated_as_unknown(tmp_path, bad):
    rc, rep = _run_cov_gate(tmp_path, {
        "opcodes": [{"hex": "0x00", "name": "PUT_PC"}],
        "non_command_row_refusal_count": bad,
    })
    assert rc == 0
    assert rep["non_command_rows_refused"] is None


def test_refusals_do_not_turn_a_pass_into_a_failure(tmp_path):
    """MEASURED: zero corpus designs have both a non-empty opcodes[] and a
    non-zero refusal count, so there is no evidence for a new FAIL, and a
    spec that carries both a command table and a pinout chapter is an
    ordinary correct design."""
    rc, rep = _run_cov_gate(tmp_path, {
        "opcodes": [{"hex": "0x%02X" % i, "name": f"CMD_{i}"}
                    for i in range(20)],
        "non_command_row_refusal_count": 64,
    })
    assert rc == 0
    assert rep["verdict"] == "PASS"


def test_placeholder_names_still_fail_with_the_disclosure_attached(tmp_path):
    """The pre-existing verdict is untouched; the disclosure rides along."""
    rc, rep = _run_cov_gate(tmp_path, {
        "opcodes": [{"hex": "0x00", "name": "PUT_PC"},
                    {"hex": "0x01", "name": "OPCODE_NAME_UNKNOWN"}],
        "non_command_row_refusal_count": 4,
    })
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert rep["non_command_rows_refused"] == 4


def test_the_gate_states_what_it_does_not_measure(tmp_path):
    rc, rep = _run_cov_gate(tmp_path, {
        "opcodes": [{"hex": "0x00", "name": "PUT_PC"}],
        "non_command_row_refusal_count": 0,
    })
    assert rep["measures"] == "opcode NAME placeholder-ness only"
    assert rep["does_not_measure"] == (
        "whether the source row was a command row at all")


def test_no_design_or_vendor_literal_in_the_gate():
    """The gate body describes the SHAPE, never a design."""
    import re as _re
    src = COV_GATE.read_text(encoding="utf-8").lower()
    for literal in ("pcie", "espi", "usb_pd", "sdmmc", "sata", "amba",
                    "axi", "intel", "arm", "wake", "clkreq", "hsop"):
        assert not _re.search(rf"\b{_re.escape(literal)}\b", src), (
            f"design / vendor literal {literal!r} leaked into the gate")
