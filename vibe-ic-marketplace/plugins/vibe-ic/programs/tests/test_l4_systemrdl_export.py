#!/usr/bin/env python3
"""Tests for l4_systemrdl_export.py (vibe-ic#377 item B, first increment).

TEST SHAPE
==========
Every behaviour is tested as a PAIR: an input that must produce the finding,
and a MUTATION of that same input — differing in exactly the one thing the
finding is about — that must NOT produce it. A test that only ever sees the
defective input cannot tell a working detector from one that always fires.

TWO TIERS
---------
Tier 1 (always runs) covers the deterministic half: the disposition table, the
per-instance ledger, and the exporter's refusal to emit what the standard
cannot hold. No third-party package is involved.

Tier 2 covers the ROUND TRIP, and needs a real SystemRDL compiler. It is
skipped where `systemrdl-compiler` is absent — which is the normal CI state,
and a skip is NOT a pass. These were executed against systemrdl-compiler 1.32.2
while the increment was authored; the results are recorded in the issue thread,
not asserted here from memory.

REAL-CORPUS COVERAGE
--------------------
`test_corpus_*` run the exporter over the published L4 documents rather than a
fixture. A checker that only ever meets an input its author wrote proves the
logic and nothing about the artefacts.

Those documents now live in https://github.com/vibeic/benchmark-data, not in
this checkout. They are resolved through `_published_corpus`, so the corpus
tests SKIP naming it when there is none to read and RUN unchanged against a
clone pointed at by `VIBE_IC_BENCHMARK_DATA`.

WHY THE OLD GUARD STOPPED GUARDING. They were skipped on
`(_repo_root() / "benchmark-data").is_dir()`. That directory still exists — it
carries the flow's design INPUTS — so the guard kept answering "the corpus is
here" over a tree holding zero L4 documents, `audit-corpus` returned its own
rc 2 SKIP, and the tests failed on the absence as though the disposition table
had a hole in it. Presence of the directory was never the question; presence of
a published CELL is, which is exactly what `_published_corpus` asks.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from _published_corpus import corpus_root, needs_corpus

PROG = Path(__file__).resolve().parent.parent / "l4_systemrdl_export.py"

_HAVE_RDL = True
try:  # noqa: SIM105
    import systemrdl  # type: ignore  # noqa: F401
except Exception:
    _HAVE_RDL = False

needs_rdl = pytest.mark.skipif(
    not _HAVE_RDL,
    reason="systemrdl-compiler not installed; a round-trip test that cannot "
           "parse must SKIP, never simulate a parse")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), *args],
                          capture_output=True, text=True)


def _export(tmp_path: Path, l4: dict, *extra: str):
    src = tmp_path / "L4_REGMAP.json"
    src.write_text(json.dumps(l4), encoding="utf-8")
    out = tmp_path / "out.rdl"
    led = tmp_path / "out.json"
    r = _run("export", str(src), "--out", str(out), "--ledger", str(led),
             "--workdir", str(tmp_path / "wd"), *extra)
    ledger = json.loads(led.read_text()) if led.exists() else None
    rdl = out.read_text() if out.exists() else ""
    return r, rdl, ledger


def _findings(ledger: dict) -> list:
    return [f["kind"] for f in ledger["findings"]]


def _base_l4(**over) -> dict:
    l4 = {
        "schema_version": 2, "doc_class": "regmap", "ic_name": "unit_under_test",
        "register_map_present": True,
        "registers": [{
            "name": "CTRL", "address": "0x00", "address_int": 0,
            "width_bits": 32, "access": "RW", "description": "control",
            "fields": [
                {"field_name": "EN", "bits": "0", "msb": 0, "lsb": 0,
                 "access": "RW", "description": "enable"},
                {"field_name": "MODE", "bits": "3:2", "msb": 3, "lsb": 2,
                 "access": "RO", "description": "mode"},
            ],
        }],
    }
    l4.update(over)
    return l4


# ---------------------------------------------------------------------------
# TIER 1 — the disposition table is TOTAL, and a gap is a failure
# ---------------------------------------------------------------------------
def test_export_succeeds_on_a_fully_classified_document(tmp_path):
    r, rdl, ledger = _export(tmp_path, _base_l4())
    assert r.returncode == 0, r.stdout + r.stderr
    assert "addrmap unit_under_test {" in rdl
    assert ledger["registers_emitted"] == 1
    assert ledger["fields_emitted"] == 2


def test_MUTATION_unknown_register_key_fails_instead_of_being_dropped(tmp_path):
    """The control for the whole design: a key nobody classified must STOP the
    export, because the alternative is a silent omission that the .rdl reads as
    a complete description."""
    l4 = _base_l4()
    l4["registers"][0]["a_key_no_one_has_classified"] = "value"
    r, _rdl, _ledger = _export(tmp_path, l4)
    assert r.returncode == 1
    assert "a_key_no_one_has_classified" in r.stdout
    assert "NO recorded SystemRDL disposition" in r.stdout


def test_MUTATION_unknown_field_key_fails_too(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["fields"][0]["some_new_field_attribute"] = 1
    r, _rdl, _ledger = _export(tmp_path, l4)
    assert r.returncode == 1
    assert "some_new_field_attribute" in r.stdout


def test_every_disposition_row_states_a_reason_for_non_native(tmp_path):
    """A row that says LOSSY/DROPPED without saying why is a label, not a
    finding."""
    sys.path.insert(0, str(PROG.parent))
    import l4_systemrdl_export as mod
    missing = [(s, k) for (s, k), (d, _t, note) in mod.DISPOSITION.items()
               if d in (mod.D_LOSSY, mod.D_DROPPED) and not note.strip()]
    assert missing == [], "dispositions with no stated reason: %r" % (missing,)


# ---------------------------------------------------------------------------
# TIER 1 — per-instance findings, each with its mutation control
# ---------------------------------------------------------------------------
def test_whole_reg_placeholder_is_reported_as_strengthened(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["fields"] = [{
        "bits": "WHOLE_REG", "field_name": "WHOLE_REG", "access": "RW",
        "description": "d", "synthesised_whole_register_field": True,
        "synthesised_source": "summary_table_only"}]
    _r, rdl, ledger = _export(tmp_path, l4)
    assert "placeholder_promoted_to_asserted_layout" in _findings(ledger)
    # the caveat still reaches a SystemRDL consumer, via a real UDP
    assert "l4_synthesised_whole_register_field = true" in rdl


def test_MUTATION_a_real_bit_range_is_not_reported_as_strengthened(tmp_path):
    """Same register, same names — only the bit range is real."""
    l4 = _base_l4()
    l4["registers"][0]["fields"] = [{
        "bits": "31:0", "msb": 31, "lsb": 0, "field_name": "WHOLE_REG",
        "access": "RW", "description": "d"}]
    _r, _rdl, ledger = _export(tmp_path, l4)
    assert "placeholder_promoted_to_asserted_layout" not in _findings(ledger)


def test_write_legality_access_reports_the_lost_constraint(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["fields"][0]["access"] = "WARL"
    _r, rdl, ledger = _export(tmp_path, l4)
    assert "write_legality_constraint_lost" in _findings(ledger)
    assert "sw = rw;" in rdl                    # nearest mode still emitted
    assert 'l4_access_literal = "WARL"' in rdl  # the literal is not lost


def test_MUTATION_a_plain_access_mode_reports_no_lost_constraint(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["fields"][0]["access"] = "RW"
    _r, _rdl, ledger = _export(tmp_path, l4)
    assert "write_legality_constraint_lost" not in _findings(ledger)


def test_duplicate_enum_mnemonic_is_reported_and_disambiguated(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["fields"][1]["encoding"] = [
        {"pattern": "01", "mnem": "SAME", "description": "first"},
        {"pattern": "10", "mnem": "SAME", "description": "second"},
    ]
    _r, rdl, ledger = _export(tmp_path, l4)
    assert "duplicate_enum_mnemonic" in _findings(ledger)
    assert "SAME = 2'b01" in rdl and "SAME_10 = 2'b10" in rdl


def test_MUTATION_distinct_mnemonics_produce_no_collision_finding(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["fields"][1]["encoding"] = [
        {"pattern": "01", "mnem": "FIRST", "description": "first"},
        {"pattern": "10", "mnem": "SECOND", "description": "second"},
    ]
    _r, rdl, ledger = _export(tmp_path, l4)
    assert "duplicate_enum_mnemonic" not in _findings(ledger)
    assert "FIRST = 2'b01" in rdl and "SECOND = 2'b10" in rdl


def test_register_with_no_expressible_field_is_dropped_with_a_reason(tmp_path):
    l4 = _base_l4()
    l4["registers"][0].pop("fields")
    _r, rdl, ledger = _export(tmp_path, l4)
    assert "register_with_no_expressible_field" in _findings(ledger)
    assert ledger["registers_emitted"] == 0
    assert "CTRL" not in rdl
    # dropped, but NAMED — the whole contract
    assert any(e["path"] == "CTRL" and e["disposition"] == "DROPPED"
               for e in ledger["not_expressible_in_systemrdl"])


def test_MUTATION_one_field_is_enough_to_keep_the_register(tmp_path):
    _r, rdl, ledger = _export(tmp_path, _base_l4())
    assert "register_with_no_expressible_field" not in _findings(ledger)
    assert ledger["registers_emitted"] == 1
    assert "CTRL" in rdl


def test_two_registers_claiming_one_address_is_reported(tmp_path):
    l4 = _base_l4()
    dup = json.loads(json.dumps(l4["registers"][0]))
    dup["name"] = "CTRL_ALIAS"
    l4["registers"].append(dup)
    _r, _rdl, ledger = _export(tmp_path, l4)
    assert "register_address_collision" in _findings(ledger)
    assert ledger["registers_emitted"] == 1


def test_MUTATION_distinct_addresses_do_not_collide(tmp_path):
    l4 = _base_l4()
    dup = json.loads(json.dumps(l4["registers"][0]))
    dup["name"] = "CTRL_ALIAS"
    dup["address"], dup["address_int"] = "0x04", 4
    l4["registers"].append(dup)
    _r, _rdl, ledger = _export(tmp_path, l4)
    assert "register_address_collision" not in _findings(ledger)
    assert ledger["registers_emitted"] == 2


def test_addressless_register_is_omitted_rather_than_placed_by_invention(tmp_path):
    l4 = _base_l4()
    for k in ("address", "address_int"):
        l4["registers"][0].pop(k)
    _r, _rdl, ledger = _export(tmp_path, l4)
    assert ledger["registers_emitted"] == 0
    assert any(e["l4_key"] == "address" and e["disposition"] == "DROPPED"
               for e in ledger["not_expressible_in_systemrdl"])


def test_MUTATION_an_address_under_offset_alone_is_enough(tmp_path):
    l4 = _base_l4()
    for k in ("address", "address_int"):
        l4["registers"][0].pop(k)
    l4["registers"][0]["offset"] = "0x10"
    _r, rdl, ledger = _export(tmp_path, l4)
    assert ledger["registers_emitted"] == 1
    assert "@ 0x10;" in rdl


def test_access_literal_outside_the_closed_vocabulary_is_named(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["fields"][0]["access"] = \
        "Read when the transfer completes; otherwise writes are ignored"
    _r, rdl, ledger = _export(tmp_path, l4)
    assert "access_literal_outside_closed_vocabulary" in _findings(ledger)
    # nothing invented: no `sw` is emitted for that field
    en_line = [ln for ln in rdl.splitlines() if " EN[" in ln][0]
    assert "sw =" not in en_line


def test_MUTATION_a_recognised_acronym_is_inside_the_vocabulary(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["fields"][0]["access"] = "W1C"
    _r, rdl, ledger = _export(tmp_path, l4)
    assert "access_literal_outside_closed_vocabulary" not in _findings(ledger)
    assert "onwrite = woclr;" in rdl


def test_symbolic_reset_emits_nothing_and_says_so(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["reset_value"] = "unspecified"
    l4["registers"][0]["reset_value_kind"] = "symbolic"
    _r, rdl, ledger = _export(tmp_path, l4)
    assert "reset =" not in rdl
    assert any(e["l4_key"] == "reset_value" and e["disposition"] == "DROPPED"
               for e in ledger["not_expressible_in_systemrdl"])


def test_MUTATION_a_numeric_reset_is_sliced_into_the_fields(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["reset_value"] = "0x0000_0009"   # EN=1, MODE=0b10
    _r, rdl, _ledger = _export(tmp_path, l4)
    assert "reset = 1'h1;" in rdl        # EN[0:0]  <- bit0 of 0x9
    assert "reset = 2'h2;" in rdl        # MODE[3:2] <- bits 3:2 of 0x9


def test_reset_bits_landing_outside_every_field_are_reported_lost(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["reset_value"] = "0x80000000"    # bit 31, no field there
    _r, _rdl, ledger = _export(tmp_path, l4)
    assert "reset_bits_outside_any_field" in _findings(ledger)


def test_MUTATION_a_reset_inside_the_fields_is_not_reported_lost(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["reset_value"] = "0x9"
    _r, _rdl, ledger = _export(tmp_path, l4)
    assert "reset_bits_outside_any_field" not in _findings(ledger)


def test_overlapping_fields_are_dropped_and_named(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["fields"].append(
        {"field_name": "CLASH", "bits": "3:0", "msb": 3, "lsb": 0,
         "access": "RW", "description": "overlaps EN and MODE"})
    _r, _rdl, ledger = _export(tmp_path, l4)
    assert "overlapping_fields" in _findings(ledger)
    assert ledger["fields_emitted"] == 2


def test_MUTATION_adjacent_fields_do_not_overlap(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["fields"].append(
        {"field_name": "NEXT", "bits": "7:4", "msb": 7, "lsb": 4,
         "access": "RW", "description": "adjacent"})
    _r, _rdl, ledger = _export(tmp_path, l4)
    assert "overlapping_fields" not in _findings(ledger)
    assert ledger["fields_emitted"] == 3


def test_rdl_header_declares_its_own_incompleteness(tmp_path):
    """A reader who has only the .rdl must not mistake it for the whole map."""
    l4 = _base_l4()
    l4["registers"][0]["fields"][0]["access"] = "WARL"
    _r, rdl, _ledger = _export(tmp_path, l4)
    assert "NOT A COMPLETE DESCRIPTION" in rdl
    assert "companion ledger" in rdl


def test_word_address_unit_is_recorded_as_a_caller_assertion(tmp_path):
    _r, rdl, ledger = _export(tmp_path, _base_l4(), "--address-unit", "word")
    assert ledger["assumptions"], "an address-unit change must be recorded"
    assert "CALLER ASSERTION" in rdl


def test_MUTATION_byte_address_unit_asserts_nothing(tmp_path):
    _r, rdl, ledger = _export(tmp_path, _base_l4())
    assert ledger["assumptions"] == []
    assert "as stated in L4" in rdl


def test_symbolic_reset_under_default_alone_is_still_reported(tmp_path):
    """Found by auditing this exporter against the corpus: the first version
    checked `reset_value` only, so a register whose `default` alone said
    "unspecified" lost it in silence. One real published register does that."""
    l4 = _base_l4()
    l4["registers"][0]["default"] = "unspecified"
    _r, rdl, ledger = _export(tmp_path, l4)
    assert "reset =" not in rdl
    assert any(e["l4_key"] == "default" and e["disposition"] == "DROPPED"
               for e in ledger["not_expressible_in_systemrdl"])


def test_MUTATION_a_numeric_default_is_carried_not_reported(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["default"] = "0x1"
    _r, rdl, ledger = _export(tmp_path, l4)
    assert "reset = 1'h1;" in rdl
    assert not any(e["l4_key"] == "default" and e["disposition"] == "DROPPED"
                   for e in ledger["not_expressible_in_systemrdl"])


def test_a_udp_value_that_cannot_be_rendered_is_reported_not_skipped(tmp_path):
    """The ledger must not claim a key was CARRIED when it was not. A boolean
    user-defined property handed a string renders to nothing."""
    l4 = _base_l4()
    l4["registers"][0]["is_counter"] = "yes"        # not a boolean
    _r, rdl, ledger = _export(tmp_path, l4)
    assert "l4_is_counter" not in rdl.split("addrmap")[1]
    assert any(e["l4_key"] == "is_counter" and e["disposition"] == "DROPPED"
               and "cannot be rendered" in e["reason"]
               for e in ledger["not_expressible_in_systemrdl"])


def test_MUTATION_a_real_boolean_is_carried_through_the_udp(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["is_counter"] = True
    _r, rdl, ledger = _export(tmp_path, l4)
    assert "l4_is_counter = true;" in rdl
    assert not any(e["l4_key"] == "is_counter" and e["disposition"] == "DROPPED"
                   for e in ledger["not_expressible_in_systemrdl"])


def test_expressible_but_out_of_scope_content_says_which_limit_it_hit(tmp_path):
    """`internal_registers` ARE registers. Reporting them as 'outside the
    object model' would blame the standard for a limit of this exporter."""
    l4 = _base_l4()
    l4["internal_registers"] = [{"name": "SHADOW"}]
    _r, _rdl, ledger = _export(tmp_path, l4)
    row = next(e for e in ledger["not_expressible_in_systemrdl"]
               if e["l4_key"] == "internal_registers")
    assert "limit of the exporter" in row["reason"]
    assert "outside SystemRDL's object model" not in row["reason"]


def test_MUTATION_a_genuine_sidecar_is_blamed_on_the_object_model(tmp_path):
    l4 = _base_l4()
    l4["some_prose_section"] = {"text": "narrative"}
    _r, _rdl, ledger = _export(tmp_path, l4)
    row = next(e for e in ledger["not_expressible_in_systemrdl"]
               if e["l4_key"] == "some_prose_section")
    assert "outside SystemRDL's object model" in row["reason"]


def test_gap_table_covers_both_directions():
    r = _run("gap-table")
    assert r.returncode == 0
    assert "SystemRDL properties NO L4 key sources" in r.stdout
    assert "hw" in r.stdout


def test_no_registers_is_not_applicable_not_a_rejection(tmp_path):
    """An L4 that never described a register map is not evidence about the
    standard, and must not be counted as one."""
    l4 = _base_l4(registers=[], no_registers_in_input=True)
    _r, _rdl, ledger = _export(tmp_path, l4, "--roundtrip")
    assert ledger["roundtrip"]["verdict"] == "NOT_APPLICABLE"


def test_registers_with_no_address_report_empty_export(tmp_path):
    l4 = _base_l4()
    for k in ("address", "address_int"):
        l4["registers"][0].pop(k)
    _r, _rdl, ledger = _export(tmp_path, l4, "--roundtrip")
    assert ledger["roundtrip"]["verdict"] == "EMPTY_EXPORT"


# ---------------------------------------------------------------------------
# TIER 1 — the corpus gate, run on the repo's OWN published artefacts
# ---------------------------------------------------------------------------
def _corpus_root() -> Path:
    """The tree the corpus tests walk: wherever the published cells actually are.

    Only ever called from a `@needs_corpus` test, so the assertion is a
    contract check on that marker rather than a second skip condition — there
    is exactly one skip reason for an absent corpus and it lives in
    `_published_corpus`.
    """
    root = corpus_root()
    assert root is not None, (
        "reached the corpus body with no corpus; @needs_corpus should have "
        "skipped this test")
    return root


@needs_corpus
def test_corpus_disposition_table_is_total():
    r = _run("audit-corpus", "--root", str(_corpus_root()))
    assert r.returncode == 0, r.stdout
    assert "every register/field key in the published corpus has a recorded " \
           "disposition" in r.stdout


@needs_corpus
def test_corpus_audit_reports_a_nonzero_scan(tmp_path):
    """A gate that scanned nothing reports PASS. Assert it saw real inputs."""
    out = tmp_path / "a.json"
    r = _run("audit-corpus", "--root", str(_corpus_root()), "--json", str(out))
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["l4_documents_scanned"] > 20
    assert rep["register_keys_seen"] > 10
    assert rep["field_keys_seen"] > 5


def test_corpus_audit_fails_on_an_unclassified_key(tmp_path):
    """MUTATION control for the gate itself: plant one unclassified key in a
    corpus of otherwise-classified documents and require the gate to go red."""
    root = tmp_path / "repo"
    d = root / "a" / "phase1" / "generated_docs"
    d.mkdir(parents=True)
    (d / "L4_REGMAP.json").write_text(json.dumps(_base_l4()))
    r = _run("audit-corpus", "--root", str(root))
    assert r.returncode == 0, r.stdout

    l4 = _base_l4()
    l4["registers"][0]["an_unclassified_key"] = 1
    (d / "L4_REGMAP.json").write_text(json.dumps(l4))
    r = _run("audit-corpus", "--root", str(root))
    assert r.returncode == 1
    assert "an_unclassified_key" in r.stdout
    assert "REMEDY" in r.stdout


def test_corpus_audit_skips_an_empty_tree(tmp_path):
    r = _run("audit-corpus", "--root", str(tmp_path))
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# TIER 2 — the ROUND TRIP. Needs a real compiler; skipped without one.
# ---------------------------------------------------------------------------
@needs_rdl
def test_roundtrip_is_clean_when_nothing_is_lost(tmp_path):
    l4 = _base_l4()
    _r, _rdl, ledger = _export(tmp_path, l4, "--roundtrip")
    rt = ledger["roundtrip"]
    assert rt["parser"]["available"] is True
    assert rt["verdict"] == "ROUNDTRIP_CLEAN", rt


@needs_rdl
def test_roundtrip_reports_the_weakened_write_legality_constraint(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["fields"][0]["access"] = "WARL"
    _r, _rdl, ledger = _export(tmp_path, l4, "--roundtrip")
    rt = ledger["roundtrip"]
    assert rt["verdict"] == "ROUNDTRIP_LOSSY"
    assert any(row["verdict"] == "WEAKENED" and row["field"] == "EN"
               for row in rt["field_differences"]), rt["field_differences"]


@needs_rdl
def test_roundtrip_reports_the_strengthened_placeholder(tmp_path):
    l4 = _base_l4()
    l4["registers"][0]["fields"] = [{
        "bits": "WHOLE_REG", "field_name": "WHOLE_REG", "access": "RW",
        "description": "d", "synthesised_whole_register_field": True}]
    _r, _rdl, ledger = _export(tmp_path, l4, "--roundtrip")
    assert any(row["verdict"] == "STRENGTHENED"
               for row in ledger["roundtrip"]["field_differences"])


@needs_rdl
def test_MUTATION_the_comparator_catches_a_perturbed_rdl(tmp_path):
    """The control for the round trip itself.

    A diff that always says CLEAN is worthless. Take an export that IS clean,
    change ONE bit range in the emitted SystemRDL, parse THAT back, and require
    the comparison to report the field ALTERED. This proves the comparator
    reads the parsed model rather than echoing the exporter.
    """
    sys.path.insert(0, str(PROG.parent))
    import l4_systemrdl_export as mod

    l4 = _base_l4()
    rdl, summary, _ledger = mod.export_rdl(l4, source_path="x")
    exp = mod.l4_expectation(l4)

    clean = mod.roundtrip(rdl, exp, address_unit="byte",
                          workdir=tmp_path / "a",
                          emitted_registers=summary["registers_emitted"])
    assert clean["verdict"] == "ROUNDTRIP_CLEAN", clean

    perturbed = rdl.replace("MODE[3:2]", "MODE[5:4]")
    assert perturbed != rdl, "the perturbation did not apply"
    dirty = mod.roundtrip(perturbed, exp, address_unit="byte",
                          workdir=tmp_path / "b",
                          emitted_registers=summary["registers_emitted"])
    assert dirty["verdict"] == "ROUNDTRIP_LOSSY"
    altered = [r for r in dirty["field_differences"]
               if r["field"] == "MODE" and r["verdict"] == "ALTERED"]
    assert {r["attribute"] for r in altered} == {"msb", "lsb"}, altered


@needs_rdl
def test_MUTATION_the_comparator_catches_a_deleted_field(tmp_path):
    sys.path.insert(0, str(PROG.parent))
    import l4_systemrdl_export as mod
    l4 = _base_l4()
    rdl, summary, _ledger = mod.export_rdl(l4, source_path="x")
    exp = mod.l4_expectation(l4)
    perturbed = "\n".join(ln for ln in rdl.splitlines() if " MODE[" not in ln)
    dirty = mod.roundtrip(perturbed, exp, address_unit="byte",
                          workdir=tmp_path / "c",
                          emitted_registers=summary["registers_emitted"])
    assert any(r["field"] == "MODE" and r["verdict"] == "LOST"
               for r in dirty["field_differences"]), dirty


@needs_rdl
def test_roundtrip_runs_on_a_real_published_l4(tmp_path):
    """Not a fixture. The richest real register map in the published corpus."""
    best, score = None, -1
    for p in _corpus_root().rglob("L4_REGMAP.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        n = sum(1 for r in (d.get("registers") or []) if isinstance(r, dict)
                for f in (r.get("fields") or [])
                if isinstance(f, dict) and isinstance(f.get("msb"), int))
        if n > score:
            best, score = p, n
    assert best is not None and score > 0, "no real L4 with placed fields"
    out, led = tmp_path / "o.rdl", tmp_path / "o.json"
    r = _run("export", str(best), "--out", str(out), "--ledger", str(led),
             "--roundtrip", "--address-unit", "word",
             "--workdir", str(tmp_path / "wd"))
    assert r.returncode == 0, r.stdout + r.stderr
    ledger = json.loads(led.read_text())
    assert ledger["roundtrip"]["verdict"] in (
        "ROUNDTRIP_CLEAN", "ROUNDTRIP_LOSSY"), ledger["roundtrip"]
    # a real map of this size cannot survive intact; if it ever does, the
    # comparator has stopped comparing.
    assert ledger["roundtrip"]["field_differences"] or \
        ledger["roundtrip"]["registers_lost"]


# ── gatekeeper, delivering #377's first-increment step 2 ───────────────────
def test_the_word_stride_is_UNIFORM_across_the_map():
    """A word/index address maps to a byte address by the MAP's addressing
    granularity. Scaling each register by ITS OWN inferred width gives a
    different multiplier per register.

    MEASURED on the published ibex L4 before this fix: 41 of 43 registers got
    x4 while `cpuctrlsts` (inferred 16-bit) got x2 and `mseccfg` (inferred
    8-bit) got x1. Those two landed at addresses that are not their index
    times anything the map declares — and they are exactly the registers
    PeakRDL then rejected as unaligned, which is how the defect surfaced:
    `--address-unit word` could not be compiled at all.
    """
    import json
    import l4_systemrdl_export as X

    l4 = {"registers": [
        {"name": "wide", "address": "0x100", "size": 32,
         "fields": [{"field_name": "a", "bits": "31:0"}]},
        {"name": "narrow", "address": "0x101", "size": 32,
         "fields": [{"field_name": "b", "bits": "2:0"}]},
    ]}
    rdl, _, _ = X.export_rdl(l4, address_unit="word")
    import re
    got = {m.group(1).rstrip("_"): int(m.group(2), 16)
           for m in re.finditer(r"\}\s*(\w+)\s*@\s*(0x[0-9A-Fa-f]+)", rdl)}
    assert got["wide"] == 0x100 * 4, got
    # the narrow register must use the SAME stride, not its own field width
    assert got["narrow"] == 0x101 * 4, got
    assert got["narrow"] - got["wide"] == 4, got


def test_byte_unit_still_emits_the_address_as_stated():
    """The paired half. `--address-unit byte` is the default precisely so a map
    whose addresses overlap under byte semantics is reported rather than
    silently rescaled; the stride fix must not reach it."""
    import re
    import l4_systemrdl_export as X

    l4 = {"registers": [
        {"name": "r", "address": "0x123", "size": 32,
         "fields": [{"field_name": "a", "bits": "2:0"}]},
    ]}
    rdl, _, _ = X.export_rdl(l4, address_unit="byte")
    # the emitter may suffix a name to avoid a SystemRDL keyword
    got = re.search(r"\}\s*r_?\s*@\s*(0x[0-9A-Fa-f]+)", rdl)
    assert int(got.group(1), 16) == 0x123
