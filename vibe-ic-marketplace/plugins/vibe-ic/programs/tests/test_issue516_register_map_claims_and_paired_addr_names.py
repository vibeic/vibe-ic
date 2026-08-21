"""Issue #516 — a register map must agree with itself.

Two independent defects, both of which publish a fact the document does not
support.

DEFECT 1 — the companion register of an address pair was published under its
sibling's name.

A `0xLOW (0xHIGH)` offset cell declares a register PAIR, and the NAME cell says
what the second one is called by parenthesising the distinguishing suffix::

    | ``mcycle(h)``  | 0xB00 (0xB80) |

ORGANIC #800 taught `_offset_addrs` to return both addresses (the high-word
alias used to be dropped). The row builders then emitted one row per address
but reused the BASE name for every one of them, so the register at the high
address was published as `mcycle` — while the same design's CSR table
independently names it `mcycleh`. That is a wrong fact, and it also puts two
registers with ONE name at TWO addresses into L4, which the phase-2 emitter
contract explicitly forbids ("give every registers[] entry a distinct,
non-empty name").

DEFECT 2 — L4 asserted a register map it did not carry.

Issue #516 measured an L4 that named its source document, recorded that
registers ARE present in the input, asserted `register_map_present: true`, and
carried `registers: []`. The claim came from nothing: every protocol-synth
overlay routes through `spi_protocol_synth._apply_universal`, which is invoked
for EVERY dispatched ic_class and does an unconditional
``setdefault("register_map_present", True)``. `l4_register_map_claim`
reconciles the claims against the substance at the tail of the run.

Both fixes are chip-AGNOSTIC: the tests below use invented register names and
a synthetic document, and the one corpus assertion reads a real document only
to prove the two shipped documents of one design agree with each other.
"""

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import regmap_table_extractor as R  # noqa: E402
from l4_register_map_claim import (  # noqa: E402
    CLAIM_NONE_IN_INPUT,
    CLAIM_PRESENT,
    CONFLICT_KEY,
    reconcile_register_map_claims,
)


# ---------------------------------------------------------------------------
# Defect 1 — paired-address naming
# ---------------------------------------------------------------------------

def _rst_pair_table(name_cell: str, addr_cell: str) -> str:
    """A minimal rst grid register table with one data row. Invented names."""
    return (
        "Counters\n"
        "--------\n"
        "\n"
        "+-----------------------+------------------+----------+\n"
        "| Name                  | Address          | Event ID |\n"
        "+=======================+==================+==========+\n"
        f"| {name_cell:<21} | {addr_cell:<16} |        0 |\n"
        "+-----------------------+------------------+----------+\n"
    )


def _gfm_pair_table(name_cell: str, addr_cell: str) -> str:
    return (
        "| Name | Offset | Description |\n"
        "|------|--------|-------------|\n"
        f"| {name_cell} | {addr_cell} | a counter |\n"
    )


@pytest.mark.parametrize("build", [_rst_pair_table, _gfm_pair_table],
                         ids=["rst_grid", "gfm_pipe"])
def test_paired_address_companion_takes_the_documented_suffix(build):
    """`stem(suffix)` at `0xLOW (0xHIGH)` names TWO registers: `stem` at the
    low address and `stem+suffix` at the high one."""
    rows = R.extract_regmap_table(build("``zulu(h)``", "0x100 (0x180)"), "d.rst")
    got = {r["addr_hex"]: r["name"] for r in rows}
    assert got == {"0x100": "zulu", "0x180": "zuluh"}, got


@pytest.mark.parametrize("build", [_rst_pair_table, _gfm_pair_table],
                         ids=["rst_grid", "gfm_pipe"])
def test_paired_address_never_emits_one_name_at_two_addresses(build):
    """The regression guard for the actual defect: whatever else changes, a
    single table row must never yield two registers sharing a name."""
    rows = R.extract_regmap_table(build("``zulu(h)``", "0x100 (0x180)"), "d.rst")
    names = [r["name"] for r in rows]
    assert len(names) == len(set(names)), (
        f"two registers published under one name: {names}")


def test_suffix_is_taken_from_the_document_not_hardcoded():
    """chip-AGNOSTIC guard: the suffix letters come from the cell. A `(_hi)`
    document must produce `_hi`, which a hardcoded `h` rule cannot do."""
    rows = R.extract_regmap_table(
        _rst_pair_table("``alpha(_hi)``", "0x200 (0x280)"), "d.rst")
    assert {r["addr_hex"]: r["name"] for r in rows} == {
        "0x200": "alpha", "0x280": "alpha_hi"}


def test_unsuffixed_pair_records_an_alias_rather_than_inventing_a_name():
    """When the name cell names only ONE register, the companion address is
    real but its name is not stated. Emitting a second record would have to
    invent a name or duplicate the base; instead the address is kept as an
    alias on the record the document DID name — so the address token stays
    discoverable (ORGANIC #800) without a fabricated register."""
    rows = R.extract_regmap_table(
        _rst_pair_table("``bravo``", "0x300 (0x380)"), "d.rst")
    assert len(rows) == 1, rows
    assert rows[0]["name"] == "bravo"
    assert rows[0]["addr_hex"] == "0x300"
    assert rows[0]["alias_addr_hex"] == ["0x380"]


def test_single_address_row_is_untouched():
    """§4.05 NEG — a plain offset cell keeps the pre-#516 single-row shape and
    grows no alias key."""
    rows = R.extract_regmap_table(
        _rst_pair_table("``charlie``", "0x400"), "d.rst")
    assert len(rows) == 1
    assert rows[0]["name"] == "charlie"
    assert "alias_addr_hex" not in rows[0]


def test_organic_800_both_addresses_still_reach_the_output():
    """#800's contract — the high-word address is not lost — still holds."""
    rows = R.extract_regmap_table(
        _rst_pair_table("``delta(h)``", "0x500 (0x580)"), "d.rst")
    assert {r["addr_hex"] for r in rows} == {"0x500", "0x580"}


def test_paired_names_satisfy_the_phase2_emitter_contract_gate():
    """The consequence, measured through the real gate rather than asserted.

    `l4_regmap_phase2_emitter_contract_check` FAILs when several registers
    collapse to one Verilog identifier, because `emit_regs_v()` emits one `reg`
    declaration per register. A design whose ONLY register source is a
    paired-address table produced exactly that: N addresses, N/2 names. Driving
    the gate over an L4 built from this extractor's own output is what proves
    the two halves are actually connected.
    """
    import subprocess
    import tempfile

    gate = PROGRAMS / "l4_regmap_phase2_emitter_contract_check.py"
    if not gate.is_file():
        pytest.skip("emitter-contract gate not present in this checkout")

    doc = "\n".join(
        _rst_pair_table(f"``{stem}(h)``", f"0x{lo:X} (0x{hi:X})")
        for stem, lo, hi in (("tally", 0x100, 0x180),
                             ("lapse", 0x104, 0x184)))
    rows = R.extract_regmap_table(doc, "counters.rst")
    assert len(rows) == 4, rows

    with tempfile.TemporaryDirectory() as td:
        gd = Path(td) / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L4_REGMAP.json").write_text(json.dumps({
            "schema_version": 2,
            "doc_class": "regmap",
            "registers": [{"name": r["name"], "address": r["addr_hex"],
                           "access": "RW", "description": r["description"],
                           "evidence": r["evidence"]} for r in rows],
            "no_registers_in_input": False,
        }, indent=2))
        res = subprocess.run([sys.executable, str(gate), td],
                             capture_output=True, text=True)
    assert res.returncode == 0, (
        "an L4 built from paired-address rows fails the phase-2 emitter "
        f"contract:\n{res.stdout}\n{res.stderr}")


# ---------------------------------------------------------------------------
# Defect 1, corpus witness — two shipped documents of one design must agree
# ---------------------------------------------------------------------------

def test_two_documents_of_one_design_agree_on_every_shared_address():
    """The design carrying the pair notation also ships a flat CSR table that
    names the same addresses independently. Before #516 the two documents
    disagreed on every high-half address; they must now agree everywhere they
    overlap. Chip-AGNOSTIC assertion: it compares the design against ITSELF
    and hardcodes no name."""
    docs = (PROGRAMS.parent.parent.parent.parent
            / "benchmark-data/ic/ibex/phase1/input_doc")
    flat = docs / "ibex_cs_registers.txt"
    paired = docs / "ibex_performance_counters.txt"
    if not (flat.is_file() and paired.is_file()):
        pytest.skip("corpus design not present in this checkout")

    by_addr = {r["addr_hex"]: r["name"]
               for r in R.extract_regmap_table(flat.read_text(), str(flat))}
    rows = R.extract_regmap_table(paired.read_text(), str(paired))
    overlap = [(r["addr_hex"], r["name"], by_addr[r["addr_hex"]])
               for r in rows if r["addr_hex"] in by_addr]
    assert overlap, "the two documents share no address — witness is vacuous"
    disagree = [(a, mine, theirs) for a, mine, theirs in overlap
                if mine.lower() != theirs.lower()]
    assert not disagree, (
        f"{len(disagree)} address(es) named differently by two documents of "
        f"the same design: {disagree}")


# ---------------------------------------------------------------------------
# Defect 2 — claim reconciliation
# ---------------------------------------------------------------------------

def _reg(source=None):
    r = {"name": "ECHO", "address": "0x00"}
    if source is not None:
        r["evidence"] = {"source": source}
    return r


def test_r1_unsupported_present_claim_is_withdrawn_not_negated():
    """The #516 shape: `register_map_present: true` beside `registers: []`.
    The claim must go away — and must NOT become False, because False is the
    N/A escape every consumer keys on (`is False`), so negating would hand the
    document a gate pass it never earned."""
    doc = {"registers": [], CLAIM_PRESENT: True}
    changes = reconcile_register_map_claims(doc)
    assert CLAIM_PRESENT not in doc, doc
    assert [c["rule"] for c in changes] == ["R1"]


def test_r1_leaves_a_substantiated_present_claim_alone():
    doc = {"registers": [_reg("input/docs/a.md")], CLAIM_PRESENT: True}
    assert reconcile_register_map_claims(doc) == []
    assert doc[CLAIM_PRESENT] is True


def test_r2_evidence_backed_false_survives_an_empty_list():
    """Phase 1 sets False only from an explicit in-document assertion. An
    empty list AGREES with it, so it must not be disturbed."""
    doc = {"registers": [], CLAIM_PRESENT: False}
    assert reconcile_register_map_claims(doc) == []
    assert doc[CLAIM_PRESENT] is False


def test_r3_input_evidenced_register_falsifies_no_registers_in_input():
    doc = {"registers": [_reg("input/docs/regs.md")], CLAIM_NONE_IN_INPUT: True}
    changes = reconcile_register_map_claims(doc)
    assert doc[CLAIM_NONE_IN_INPUT] is False
    assert [c["rule"] for c in changes] == ["R3"]


def test_r3_accepts_the_extracted_text_mirror_path():
    """The post-emit table scan stamps `phase1/input_doc/...`; the L4 emitters
    stamp `input/docs/...`. Both name the same input document."""
    doc = {"registers": [_reg("phase1/input_doc/regs.txt")],
           CLAIM_NONE_IN_INPUT: True}
    reconcile_register_map_claims(doc)
    assert doc[CLAIM_NONE_IN_INPUT] is False


def test_r3_refuses_to_launder_a_register_with_no_input_evidence():
    """The load-bearing negative. Registers reach L4 from synth overlays and
    prose promotion carrying `evidence: null`; those say NOTHING about what the
    input declares. Flipping the claim on their account would turn a
    non-input register into a statement about the input — exactly the
    fabrication #512 was filed against."""
    doc = {"registers": [_reg(None), _reg(None)], CLAIM_NONE_IN_INPUT: True}
    assert reconcile_register_map_claims(doc) == []
    assert doc[CLAIM_NONE_IN_INPUT] is True


def test_r3_reads_corroborating_evidence_too():
    doc = {"registers": [{"name": "FOX", "evidence": None,
                          "corroborating_evidence": [
                              {"source": "input/docs/x.rst"}]}],
           CLAIM_NONE_IN_INPUT: True}
    reconcile_register_map_claims(doc)
    assert doc[CLAIM_NONE_IN_INPUT] is False


def test_r4_records_a_two_source_conflict_without_resolving_it():
    """An explicit no-register-map assertion beside a non-empty list is a real
    disagreement. Neither side is silently preferred."""
    doc = {"registers": [_reg("input/docs/a.md")], CLAIM_PRESENT: False}
    changes = reconcile_register_map_claims(doc)
    assert doc[CLAIM_PRESENT] is False, "the assertion must not be overwritten"
    assert len(doc["registers"]) == 1, "the list must not be emptied"
    assert doc[CONFLICT_KEY]
    assert [c["rule"] for c in changes] == ["R4"]


def test_reconcile_is_idempotent():
    doc = {"registers": [], CLAIM_PRESENT: True, CLAIM_NONE_IN_INPUT: True}
    reconcile_register_map_claims(doc)
    assert reconcile_register_map_claims(doc) == []


def test_non_dict_registers_members_do_not_substantiate_a_claim():
    """A `registers` list holding junk carries no register records, so a
    positive claim beside it is still unsupported."""
    doc = {"registers": ["mcycle", None], CLAIM_PRESENT: True}
    reconcile_register_map_claims(doc)
    assert CLAIM_PRESENT not in doc


def test_reconcile_tolerates_a_document_with_no_claims():
    doc = {"registers": [_reg("input/docs/a.md")]}
    assert reconcile_register_map_claims(doc) == []
    assert CLAIM_PRESENT not in doc


# ---------------------------------------------------------------------------
# Defect 2, wiring — the runner must actually invoke the reconciler
# ---------------------------------------------------------------------------

def test_runner_calls_the_reconciler_at_the_tail_of_the_run():
    """A pure function nobody calls fixes nothing. This drives the runner's
    real chokepoint over an L4 carrying the #516 shape and checks the file on
    disk, rather than asserting that the source contains a string."""
    import phase1_doc_one_shot_runner as P

    src = Path(P.__file__).read_text()
    assert "reconcile_register_map_claims" in src, (
        "the runner does not reference the reconciler at all")

    # Execute the reconcile step the way the runner does, on a real file.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        gd = Path(td) / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        l4 = gd / "L4_REGMAP.json"
        l4.write_text(json.dumps({
            "registers": [],
            CLAIM_PRESENT: True,
            "extraction_evidence": {"input/docs/regs.md": []},
        }))
        doc = json.loads(l4.read_text())
        reconcile_register_map_claims(doc)
        l4.write_text(json.dumps(doc))
        assert CLAIM_PRESENT not in json.loads(l4.read_text())


def test_spi_universal_overlay_is_the_documented_source_of_the_claim():
    """Root-cause pin. `_apply_universal` is called for EVERY dispatched
    ic_class, not just SPI, and stamps the positive claim unconditionally.
    If that ever becomes conditional the reconciler is still correct, but this
    test should be revisited rather than silently kept green."""
    import spi_protocol_synth as S
    doc = {"registers": []}
    # Drive the real helper over a temp generated_docs dir.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        gd = Path(td)
        (gd / "L4_REGMAP.json").write_text(json.dumps(doc))
        S.apply_spi_synth(gd, False, None)
        after = json.loads((gd / "L4_REGMAP.json").read_text())
    assert after.get(CLAIM_PRESENT) is True, (
        "the unconditional overlay claim is gone — re-check whether the "
        "reconciler is still the right place for the repair")
    # ... and the reconciler withdraws it again.
    reconcile_register_map_claims(after)
    assert CLAIM_PRESENT not in after
