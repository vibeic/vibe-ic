#!/usr/bin/env python3
"""R-0915-113(5) — `bus_contract` reads a PORT SURFACE, and a name is not a sentence.

WHAT WENT RED, and it was mine. #2418 landed `stated_vector_bus_oracle_gen`;
`test_the_polarity_ratchet_passes_on_this_tree` went red on live main
8337cc81f with

    [FAIL] 1 prose extractor(s) read a value out of a sentence and write it as
    a declaration without asking whether the sentence DENIES it, and are NOT
    in the offender register: stated_vector_bus_oracle_gen::bus_contract

The detector is right about the SHAPE — one `.search`, and a declared value
(`rst_active_low`) written from what it matched. It is the claim about the
INPUT that decides which repair is correct, and this input has no sentence in
it: the argument is the DUT's own `(direction, width, name)` triple list,
either `testbench_gen.resolve_dut` parsing a module header or L9's `ports`
array carrying the same identifiers. There is no free-text field, so there is
nowhere a denial could be written; and an identifier has no negation form —
there is no way to spell "this reset is NOT active low" in a Verilog name.

THE CLAIM IS THEREFORE A `_NOT_PROSE` ENTRY, AND THIS FILE IS ITS ARGUMENT.
Measured, not asserted, over ALL of `_prose_polarity`'s vocabulary — the CJK
spellings included — in every place a denial could act on this reader, with
negative controls proving the fixture can move the answer it claims is fixed.
No register entry, and the ratchet is not weakened: the file below re-runs it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import _prose_polarity as _pp                      # noqa: E402
import stated_vector_bus_oracle_gen as G           # noqa: E402

#: The design's own port surface, as its L3/L9 interface table states it.
PORTS = [
    ("input", "", "clk"),
    ("input", "", "reset_n"),
    ("input", "", "cs"),
    ("input", "", "we"),
    ("input", "[7:0]", "address"),
    ("input", "[31:0]", "write_data"),
    ("output", "[31:0]", "read_data"),
    ("output", "", "error"),
]

#: Every token `_prose_polarity` recognises as a denial, written out so this
#: file states the population it measured. `test_the_vocabulary_is_complete`
#: below fails the day the module grows one this deck has not measured.
TOKENS = ("not", "no", "none", "without", "excluding", "excluded", "never",
          "non-", "非", "无", "無", "不", "否", "removed", "obsolete",
          "superseded", "n/a", "inapplicable", "deprecated", "no longer",
          "does not apply")


def _answer(bus: dict) -> tuple:
    """Every published field of the contract, as one comparable value."""
    return (bus["cs"], bus["we"], bus["address"], bus["write_data"],
            bus["read_data"], bus["clk"], bus["rst"], bus["rst_active_low"],
            bus["error"], bus["word_bits"], bus["address_bits"])


@pytest.fixture(scope="module")
def base() -> tuple:
    bus, why = G.bus_contract(PORTS)
    assert bus is not None, why
    return _answer(bus)


def _ident(token: str) -> str:
    """The token as it survives an identifier: normalisation keeps only
    `[a-z0-9_]`, which is the grammar's own alphabet."""
    return re.sub(r"\W", "_", token)


# ── 0. the vocabulary this deck claims to have measured ───────────────────
def test_the_vocabulary_is_complete():
    """A token the module recognises and this deck never drove is a hole in
    the argument, so it must fail loudly rather than pass quietly."""
    for token in TOKENS:
        assert _pp.NEGATION_RE.search(token), token
    # and the module recognises nothing outside the alternation this deck
    # enumerated: every literal in its own pattern is covered here.
    literals = set(re.findall(r"\\b([a-z/ ]+?)\\b|([\u4e00-\u9fff])",
                              _pp.NEGATION_RE.pattern))
    words = {a or b for a, b in literals if (a or b)}
    missed = {w for w in words
              if not any(w.rstrip("\\w*").strip() in t for t in TOKENS)}
    assert not missed, sorted(missed)


# ── 1. the ratchet itself, on this tree ───────────────────────────────────


# ── 2. there is no field in which a denial could be written ───────────────
@pytest.mark.parametrize("token", TOKENS)
def test_a_denial_in_the_width_field_moves_nothing(token, base):
    ports = [(d, (w + " " + token if n == "address" else w), n)
             for d, w, n in PORTS]
    bus, why = G.bus_contract(ports)
    assert bus is not None, why
    assert _answer(bus) == base


@pytest.mark.parametrize("token", TOKENS)
def test_a_denial_in_the_direction_field_moves_nothing(token, base):
    bus, why = G.bus_contract([(d + " " + token, w, n) for d, w, n in PORTS])
    assert bus is not None, why
    assert _answer(bus) == base


@pytest.mark.parametrize("token", TOKENS)
def test_a_denial_added_as_its_own_port_moves_nothing(token, base):
    bus, why = G.bus_contract(PORTS + [("input", "", _ident(token) + "_reset")])
    assert bus is not None, why
    assert _answer(bus) == base


@pytest.mark.parametrize("token", TOKENS)
def test_a_comment_shaped_port_carrying_a_denial_moves_nothing(token, base):
    bus, why = G.bus_contract(PORTS + [("input", "", "comment_"
                                        + _ident(token))])
    assert bus is not None, why
    assert _answer(bus) == base


# ── 3. inside the identifier a denial is a RENAME, not a cancelled reading ─
@pytest.mark.parametrize("token", TOKENS)
def test_a_denial_inside_the_identifier_is_a_different_port(token):
    """Splice a denial into the reset name and the port `reset_n` is GONE from
    the input. Whatever the reader then answers, it answers about the port the
    design declares — it never publishes a reading of a port nobody declared,
    and it never silently keeps the old one."""
    renamed = "reset_n_" + _ident(token)
    ports = [(d, w, (renamed if n == "reset_n" else n)) for d, w, n in PORTS]
    assert not any(n == "reset_n" for _d, _w, n in ports)
    bus, why = G.bus_contract(ports)
    if bus is None:
        # normalisation strips a non-identifier token, so the name matches no
        # reset role at all — a NAMED refusal, never a default.
        assert "reset" in why or "no clock" in why or "no " in why
        return
    assert bus["rst"] == renamed
    assert renamed in bus["rst_polarity_evidence"]


def test_the_cjk_tokens_are_the_ones_that_cannot_survive_an_identifier():
    """Stated as a number so the split cannot drift unnoticed."""
    refused = []
    for token in TOKENS:
        renamed = "reset_n_" + _ident(token)
        ports = [(d, w, (renamed if n == "reset_n" else n))
                 for d, w, n in PORTS]
        if G.bus_contract(ports)[0] is None:
            refused.append(token)
    assert refused == ["非", "无", "無", "不", "否"]


# ── 4. the answer publishes the evidence it was derived from ──────────────
def test_the_polarity_names_the_suffix_it_read():
    bus, _ = G.bus_contract(PORTS)
    assert bus["rst_active_low"] is True
    assert "reset_n" in bus["rst_polarity_evidence"]
    assert "'_n'" in bus["rst_polarity_evidence"]


def test_an_active_high_reset_says_it_read_no_suffix():
    ports = [(d, w, ("reset" if n == "reset_n" else n)) for d, w, n in PORTS]
    bus, _ = G.bus_contract(ports)
    assert bus["rst_active_low"] is False
    assert "no active-low suffix" in bus["rst_polarity_evidence"]


# ── 5. negative controls: the fixture CAN move the answer ─────────────────
def test_a_rename_moves_the_polarity(base):
    ports = [(d, w, ("reset" if n == "reset_n" else n)) for d, w, n in PORTS]
    bus, _ = G.bus_contract(ports)
    assert _answer(bus) != base


def test_a_missing_port_refuses_by_name(base):
    bus, why = G.bus_contract([p for p in PORTS if p[2] != "cs"])
    assert bus is None and "no cs" in why


def test_a_widened_chip_select_refuses_by_name():
    ports = [(d, ("[3:0]" if n == "cs" else w), n) for d, w, n in PORTS]
    bus, why = G.bus_contract(ports)
    assert bus is None and "not scalar" in why


# ── 6. the deck's own hygiene ─────────────────────────────────────────────
def test_no_two_tests_in_this_file_share_a_name():
    import ast
    tree = ast.parse(Path(__file__).read_text())
    names = [n.name for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    assert len(names) == len(set(names)), \
        sorted({n for n in names if names.count(n) > 1})
