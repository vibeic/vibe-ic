#!/usr/bin/env python3
"""A register was emitted 8 bits wide while its own fields declared 32.

vibe-ic#377, found while answering "does OUR tooling repeat the failure the
SystemRDL PoC found in PeakRDL?". It does, and worse — it does not need a
placeholder to do it.

`phase2_scaffold_gen.derive_registers` resolved

    width = r.get("width") or r.get("width_bits") or 8

and never looked at the register's own `fields[].bits`. MEASURED over the
published corpus, strict bit-designation match:

    81 registers wide enough already
     8 emitted NARROWER than their own fields declare   (all in one design)

The widest declares a field spanning 32 bits and came out `reg [7:0]`. Twenty-
four bits of a DECLARED field are simply absent from the emitted RTL, and the
output is byte-identical to a register the design really did specify as 8 bits.
Nothing downstream can tell the two apart — the #404 silent-coercion class,
one layer over, on registers instead of ports.

    ibex/mtvec       fields need 32 bit  ->  reg [7:0]
    ibex/mie         fields need 31 bit  ->  reg [7:0]
    ibex/mstatus     fields need 22 bit  ->  reg [7:0]
    ibex/cpuctrlsts  fields need  9 bit  ->  reg [7:0]

THE FIX IS SCOPED TO ONE RECORD, and that is the load-bearing part. #404
measured that joining a width against a corpus-global `parameters[]` by bare
name let an L12 scan-chain count size a data bus. Nothing here leaves the
register: the bits are already integers inside it. The shape is the same as
the `layergate-2` fix directly above it in the source — the value was present
in the record the consumer was already holding, under a key it never read.

WHAT IT DELIBERATELY DOES NOT DO
================================
202 fields in the corpus are explicit `WHOLE_REG` placeholders meaning "this
document carries no field breakdown". They contribute NOTHING to the width.
#377 measured that feeding those to a standard register generator produced
3235 lines of SystemVerilog implementing a layout nobody ever specified,
looking exactly as authoritative as the 50 fields that were real. A
placeholder must not acquire a width by being read a second time.

50 more `bits` values are pin designations harvested from an address-pin table
(`A[15:13]`, `A8, A10, A[15:13]`). A substring search reads the first as bits
15:13 and sizes a register off a package pin — which is why the matcher is a
full match and not a search.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import phase2_scaffold_gen as P  # noqa: E402

_CORPUS = _PROGRAMS.parents[3] / "benchmark-data"


def _reg(fields, **kw):
    r = {"name": "r", "offset": "0x0", "fields": fields}
    r.update(kw)
    return P.derive_registers({"registers": [r]}, {})[0]


# ── the derivation ─────────────────────────────────────────────────────────
def test_a_32_bit_field_makes_a_32_bit_register(tmp_path):
    """THE LOAD-BEARING CASE — the real shape, and the one that shipped."""
    assert _reg([{"name": "a", "bits": "31:0"}])["width"] == 32


def test_the_widest_field_wins_across_several(tmp_path):
    assert _reg([{"name": "a", "bits": "7:0"},
                 {"name": "b", "bits": "21:16"}])["width"] == 22


def test_a_single_bit_designation_is_understood():
    assert _reg([{"name": "a", "bits": "12"}])["width"] == 13
    assert _reg([{"name": "a", "bits": "[3]"}])["width"] == 4


def test_bracketed_and_bare_forms_agree():
    assert (_reg([{"name": "a", "bits": "[31:0]"}])["width"]
            == _reg([{"name": "a", "bits": "31:0"}])["width"] == 32)


def test_an_explicit_register_width_still_wins():
    """The declared width outranks a derivation — a register may legitimately
    be wider than its documented fields."""
    assert _reg([{"name": "a", "bits": "7:0"}], width=32)["width"] == 32


# ── the paired halves: what must NOT acquire a width ───────────────────────
def test_a_WHOLE_REG_placeholder_contributes_nothing():
    """#377's central finding, defended. A field marked "this document has no
    breakdown" must not become a width by being read again."""
    r = _reg([{"name": "misa", "bits": "WHOLE_REG",
               "synthesised_whole_register_field": True}])
    assert r["width"] == P._REG_WIDTH_DEFAULT


def test_a_placeholder_beside_a_real_field_does_not_widen_it():
    """The mixed case: the real field decides, the placeholder is inert."""
    assert _reg([{"name": "a", "bits": "3:0"},
                 {"name": "p", "bits": "WHOLE_REG",
                  "synthesised_whole_register_field": True}])["width"] == 4


def test_an_address_pin_designation_is_not_a_bit_range():
    """PAIRED HALF, and the measurement that made the matcher a full match:
    50 corpus `bits` values are pin designations. `A[15:13]` read as a bit
    range sizes a register off a package pin."""
    assert _reg([{"name": "a", "bits": "A[15:13]"}])["width"] == \
        P._REG_WIDTH_DEFAULT
    assert _reg([{"name": "a", "bits": "A8, A10, A[15:13]"}])["width"] == \
        P._REG_WIDTH_DEFAULT


def test_a_register_with_no_fields_keeps_the_default():
    assert _reg([])["width"] == P._REG_WIDTH_DEFAULT


# ── the emitted RTL, which is what a reader actually gets ──────────────────
def test_the_emitted_declaration_is_as_wide_as_the_fields():
    regs = P.derive_registers(
        {"registers": [{"name": "mtvec", "offset": "0x305",
                        "fields": [{"name": "base", "bits": "31:2"},
                                   {"name": "mode", "bits": "1:0"}]}]}, {})
    v = P.emit_regs_v("dut", regs)
    assert "reg [31:0] mtvec" in v, v
    assert "reg [7:0] mtvec" not in v, v


# ── real data ──────────────────────────────────────────────────────────────
_STRICT = re.compile(r"^\s*\[?\s*(\d+)\s*(?::\s*(\d+)\s*)?\]?\s*$")


def _span(bits):
    m = _STRICT.match(str(bits or ""))
    if not m:
        return None
    hi = int(m.group(1))
    lo = int(m.group(2)) if m.group(2) else hi
    return max(hi, lo) + 1


def _corpus_l4():
    root = _PROGRAMS.parents[3]
    out = subprocess.run(["git", "-C", str(root), "ls-files", "benchmark-data"],
                         capture_output=True, text=True)
    return [root / p for p in out.stdout.split()
            if "L4_" in p and p.endswith(".json")]


def test_no_published_register_is_emitted_narrower_than_its_fields():
    """The measurement that justified the change, as a standing guard. It was
    8 before this landed; a zero baseline can only fire on a new instance."""
    files = _corpus_l4()
    if not files:
        pytest.skip("published corpus not checked out")
    narrow, checked = [], 0
    for p in files:
        try:
            body = json.loads(p.read_text())
        except Exception:
            continue
        f = body.get("fields") or body
        regs = f.get("registers")
        if not isinstance(regs, list) or not regs:
            continue
        try:
            derived = {r.get("name"): r for r in P.derive_registers(f, {})}
        except Exception:
            continue
        for r in regs:
            if not isinstance(r, dict):
                continue
            spans = [s for s in (_span(x.get("bits"))
                                 for x in (r.get("fields") or [])
                                 if isinstance(x, dict)) if s]
            if not spans:
                continue
            got = (derived.get(P._sanitize_id(str(r.get("name") or "REG")))
                   or {}).get("width")
            if got is None:
                continue
            checked += 1
            if int(got) < max(spans):
                narrow.append((p.name, r.get("name"), max(spans), int(got)))
    assert checked >= 50, f"only {checked} registers examined"
    assert narrow == [], narrow


def test_the_placeholder_registers_did_NOT_gain_a_width():
    """The other direction on real data. 202 corpus fields are placeholders;
    if this change had quietly given them a width, #377's finding would have
    been undone by the fix for its sibling."""
    files = _corpus_l4()
    if not files:
        pytest.skip("published corpus not checked out")
    placeholders, fabricated = 0, []
    for p in files:
        try:
            body = json.loads(p.read_text())
        except Exception:
            continue
        f = body.get("fields") or body
        regs = f.get("registers")
        if not isinstance(regs, list) or not regs:
            continue
        try:
            derived = {r.get("name"): r for r in P.derive_registers(f, {})}
        except Exception:
            continue
        for r in regs:
            if not isinstance(r, dict):
                continue
            flds = [x for x in (r.get("fields") or []) if isinstance(x, dict)]
            if any(_span(x.get("bits")) for x in flds):
                continue
            ph = [x for x in flds
                  if x.get("synthesised_whole_register_field")
                  or str(x.get("bits", "")).upper() == "WHOLE_REG"]
            if not ph or r.get("width") or r.get("width_bits"):
                continue
            placeholders += len(ph)
            got = (derived.get(P._sanitize_id(str(r.get("name") or "REG")))
                   or {}).get("width")
            if got is not None and int(got) != P._REG_WIDTH_DEFAULT:
                fabricated.append((p.name, r.get("name"), got))
    assert placeholders >= 150, f"only {placeholders} placeholders seen"
    assert fabricated == [], fabricated
