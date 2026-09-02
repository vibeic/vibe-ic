#!/usr/bin/env python3
"""l4_systemrdl_export.py — export an L4 register map as SystemRDL 2.0, and
MEASURE what the standard cannot say.

vibe-ic#377 item B, first increment. The issue's argument is that a ratified
standard would have lowered our defect rate in exactly the domains where we
keep finding bugs in hand-written harvesters. That argument is testable, and
this program is the test: emit SystemRDL from a REAL published L4, compile the
result with a REAL SystemRDL compiler, read the model back, and diff it against
the L4 it came from. Everything that does not survive is the finding.

WHY THE LEDGER IS THE DELIVERABLE AND THE .rdl IS NOT
=====================================================
A clean export proves nothing. Any exporter can be made to produce
syntactically valid SystemRDL by writing out only the fields that happen to
fit and saying nothing about the rest — and the resulting file then reads as a
complete description of the register map when it is not. That is the same
false-certificate shape this repo has spent considerable effort removing: an
artefact whose silence is indistinguishable from a clean result.

So the contract here is inverted. Every L4 key this program meets must have a
RECORDED DISPOSITION, and a key with no disposition is a hard FAILURE, not a
default-drop. The dispositions are:

    NATIVE      a SystemRDL 2.0 property carries this exactly.
    UDP         SystemRDL has no property for it, but it is carried verbatim
                through a declared user-defined property. Still machine-
                readable to a conforming SystemRDL consumer; a real language
                feature, not a comment.
    LOSSY       a SystemRDL construct carries PART of it, and what lands is
                weaker than, stronger than, or simply different from what L4
                said. The per-instance reason is recorded.
    DROPPED     no SystemRDL construct at all. The .rdl says nothing, the
                ledger names every instance, and the .rdl HEADER names the
                count so a reader of the .rdl alone cannot mistake it for
                complete.
    STRUCTURAL  consumed to build the addrmap/reg/field tree.

    (no entry)  -> UNCLASSIFIED -> exit 1. This is the property that makes the
                ledger trustworthy: the program cannot silently meet something
                new, because meeting something new is a failure.

THE OTHER HALF OF THE GAP TABLE
-------------------------------
The issue asks for both directions. `--gap-table` also prints the SystemRDL
properties that NO L4 key sources — the things the standard requires (or
defaults) that our layer never states. A defaulted `hw` access is the clearest
one: SystemRDL gives every field a hardware access mode, L4 never mentions one,
so a conforming consumer reads an assertion we never made.

ADDRESS UNITS
-------------
L4's `address` carries no unit. SystemRDL's `@` is unambiguously a BYTE
address. The default here is `--address-unit byte` (emit as stated) precisely
BECAUSE it is the honest reading, even when it makes the map fail to compile —
a register map whose addresses overlap under byte semantics is a real defect
and the compiler saying so is the point. `--address-unit word` multiplies by
regwidth/8 and records that as an EXPLICIT ASSUMPTION in the ledger; it is
never applied on its own initiative.

WHAT THIS PROGRAM IS NOT
------------------------
Not a migration. L4 is not modified, not read for anything but its own
contents, and nothing downstream consumes the .rdl. This measures the distance
between our schema and the standard; deciding whether to close it is a separate
question the issue explicitly defers.

chip-AGNOSTIC: no vendor / SKU / IC / PDK literal appears here. The access-type
vocabulary is the generic register-access acronym set, not any part's names.
Reads design INPUT only (an L4 document) and writes only its own outputs.

USAGE
-----
    # export + real round trip against one L4
    python3 l4_systemrdl_export.py export <L4_REGMAP.json> \\
        [--out OUT.rdl] [--ledger OUT.json] \\
        [--address-unit byte|word] [--roundtrip]

    # the gap table, both directions
    python3 l4_systemrdl_export.py gap-table [--json OUT]

    # the CI gate: is the disposition table still TOTAL over the real corpus?
    python3 l4_systemrdl_export.py audit-corpus [--root DIR] [--json OUT]

EXIT CODES
----------
    0 = PASS / export produced
    1 = FAIL (an UNCLASSIFIED L4 key, or a round trip that was asked for and
        did not survive when --strict-roundtrip is set)
    2 = input missing / not applicable (skip)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# The standard this targets.
# --------------------------------------------------------------------------
STANDARD = "SystemRDL 2.0 (Accellera, 2018)"

# SystemRDL 2.0 software-access enumeration. SIX values. The measured L4
# register-level `access` vocabulary over the published corpus is 113 distinct
# strings, most of them free prose. That ratio IS the gap this program exists
# to report, so the mapping below is deliberately CONSERVATIVE: a literal that
# is not a recognised access acronym is NOT guessed at, it is reported.
_SW_LEGAL = ("rw", "r", "w", "rw1", "w1", "na")

# Generic register-access acronyms -> (sw, onread, onwrite, note)
# `None` for onread/onwrite means "no side-effect property emitted".
_ACCESS_MAP: Dict[str, Tuple[str, Optional[str], Optional[str]]] = {
    "RW": ("rw", None, None),
    "R/W": ("rw", None, None),
    "READ/WRITE": ("rw", None, None),
    "READ / WRITE": ("rw", None, None),
    "RO": ("r", None, None),
    "R": ("r", None, None),
    "READ": ("r", None, None),
    "READ-ONLY": ("r", None, None),
    "WO": ("w", None, None),
    "W": ("w", None, None),
    "WRITE": ("w", None, None),
    "WRITE-ONLY": ("w", None, None),
    "W1C": ("rw", None, "woclr"),
    "RW1C": ("rw", None, "woclr"),
    "R/W1C": ("rw", None, "woclr"),
    "W1S": ("rw", None, "woset"),
    "RW1S": ("rw", None, "woset"),
    "W1T": ("rw", None, "wot"),
    "RC": ("r", "rclr", None),
    "RS": ("r", "rset", None),
    "WC": ("rw", None, "wclr"),
    "RWC": ("rw", None, "wclr"),
    "WS": ("rw", None, "wset"),
    "RWS": ("rw", None, "wset"),
    "NA": ("na", None, None),
    "RSVD": ("na", None, None),
    "RESERVED": ("na", None, None),
}

# Access literals that name a WRITE-LEGALITY CONSTRAINT rather than an access
# mode. SystemRDL 2.0 has no construct for "an illegal write is coerced to a
# legal value": `sw`/`onwrite` describe WHAT a write does, never WHICH values
# are admissible. These map to the nearest access mode and the constraint half
# is reported LOST, per instance.
_LEGALITY_CONSTRAINT_ACCESS: Dict[str, str] = {
    "WARL": "rw",   # write any, read legal
    "WLRL": "rw",   # write legal, read legal
}

# --------------------------------------------------------------------------
# THE DISPOSITION TABLE.
#
# Keys are (scope, l4_key). Values are (disposition, systemrdl_target, note).
# Derived by measuring the published L4 corpus, not by reading the emitter:
# every key below was observed in at least one tracked L4_REGMAP.json.
#
# TO ADD A KEY: add one row. That is the entire remedy when `audit-corpus`
# fails. The gate exists so that a new L4 key cannot pass through this exporter
# unexamined — the closed vocabulary the issue argues for, enforced.
# --------------------------------------------------------------------------
D_NATIVE, D_UDP, D_LOSSY, D_DROPPED, D_STRUCTURAL = (
    "NATIVE", "UDP", "LOSSY", "DROPPED", "STRUCTURAL")

DISPOSITION: Dict[Tuple[str, str], Tuple[str, str, str]] = {
    # ---- register scope -------------------------------------------------
    ("register", "name"): (
        D_NATIVE, "component instance name",
        "sanitised to a SystemRDL identifier; a name that CHANGES is recorded "
        "LOSSY per instance"),
    ("register", "long_name"): (
        D_NATIVE, "name", "SystemRDL `name` is the human-readable title"),
    ("register", "description"): (D_NATIVE, "desc", ""),
    ("register", "desc"): (D_NATIVE, "desc", "alias of `description`"),
    ("register", "notes"): (
        D_NATIVE, "desc", "appended to `desc`; SystemRDL has no second prose slot"),
    ("register", "purpose"): (
        D_UDP, "l4_purpose",
        "SystemRDL text properties are `name` and `desc` only"),
    ("register", "structure_summary"): (D_UDP, "l4_structure_summary", ""),
    ("register", "address"): (
        D_NATIVE, "@ <address>",
        "SystemRDL `@` is a BYTE address; L4 states no unit (see --address-unit)"),
    ("register", "address_int"): (
        D_NATIVE, "@ <address>", "same address, pre-parsed"),
    ("register", "addr_hex"): (
        D_NATIVE, "@ <address>",
        "the same address as a hex STRING ('0x0000'); SystemRDL `@` takes a "
        "numeric literal and prints its own radix, so the text form carries "
        "nothing `address`/`address_int` does not already export"),
    ("register", "offset"): (D_NATIVE, "@ <address>", ""),
    ("register", "offset_h"): (D_NATIVE, "@ <address>", ""),
    ("register", "sub_address_hex"): (
        D_UDP, "l4_sub_address_hex",
        "a second address axis; SystemRDL addresses one space per addrmap"),
    ("register", "width_bits"): (D_NATIVE, "regwidth", ""),
    ("register", "access"): (
        D_LOSSY, "sw (pushed down to every field)",
        "SystemRDL has NO register-scope access property — `sw` is a FIELD "
        "property. A register-level access is therefore distributed, and any "
        "part of the literal that is not an access mode is LOST"),
    ("register", "default"): (
        D_LOSSY, "field reset",
        "SystemRDL has no register-scope reset; the value is sliced per field "
        "and any bit not covered by a field is LOST"),
    ("register", "reset_value"): (
        D_LOSSY, "field reset", "same register-scope-reset limitation"),
    ("register", "reset_hex"): (D_LOSSY, "field reset", "same"),
    ("register", "reset_value_kind"): (
        D_UDP, "l4_reset_value_kind",
        "records whether the reset was numeric or symbolic; SystemRDL `reset` "
        "admits only a value or a reference, never `unspecified`"),
    ("register", "reset_value_source"): (D_UDP, "l4_reset_value_source", "provenance"),
    ("register", "is_counter"): (
        D_LOSSY, "l4_is_counter (NOT the SystemRDL `counter` property)",
        "SystemRDL HAS a `counter` field property, and that is exactly why "
        "this is not mapped to it: `counter` ASSERTS increment hardware, while "
        "L4's flag is derived from prose. Emitting `counter` would turn an "
        "observation about wording into a hardware claim"),
    ("register", "fields"): (D_STRUCTURAL, "field instances", ""),
    ("register", "field_map"): (
        D_STRUCTURAL, "field instances", "alternate field container"),
    ("register", "bits"): (
        D_LOSSY, "(nothing)",
        "a bit range at REGISTER scope has no SystemRDL meaning; only fields "
        "occupy bits"),
    ("register", "kind"): (D_UDP, "l4_kind", ""),
    ("register", "endpoint"): (
        D_UDP, "l4_endpoint",
        "marks a memory-map RANGE endpoint that L4 records as a register"),
    ("register", "range"): (
        D_LOSSY, "l4_range",
        "an address RANGE is a `mem` or an addrmap span in SystemRDL, not a "
        "`reg`. Exporting it as a register asserts a single addressable "
        "location where L4 recorded an interval"),
    ("register", "evidence"): (D_UDP, "l4_evidence", "provenance"),
    ("register", "evidence_line"): (D_UDP, "l4_evidence_line", "provenance"),
    ("register", "extraction_strategy"): (D_UDP, "l4_extraction_strategy", "provenance"),
    ("register", "low_confidence"): (
        D_UDP, "l4_low_confidence",
        "SystemRDL has no confidence notion; every property is asserted flatly"),
    ("register", "role"): (D_UDP, "l4_role", ""),
    ("register", "scope"): (D_UDP, "l4_scope", ""),
    ("register", "ap_or_dp"): (D_UDP, "l4_ap_or_dp", "debug-port side classification"),
    ("register", "regad"): (D_UDP, "l4_regad", ""),
    ("register", "dlab"): (
        D_LOSSY, "l4_dlab",
        "a bank-select qualifier: two registers share an address and are told "
        "apart by a bit of a THIRD register. SystemRDL `alias` requires the "
        "same address AND an explicit alias target, and models no selector, so "
        "the selection rule is LOST"),
    ("register", "capture_value_in_CaptureIR"): (D_UDP, "l4_capture_value", ""),
    ("register", "compute_rule"): (
        D_UDP, "l4_compute_rule",
        "a derivation rule for the value; SystemRDL models storage, not "
        "computation"),
    ("register", "common_values_hex"): (D_UDP, "l4_common_values_hex", ""),
    ("register", "common_values_hex_lsb_byte_first"): (
        D_UDP, "l4_common_values_hex_lsb_first", ""),
    ("register", "fields_csd_v1"): (
        D_DROPPED, "(nothing)",
        "a VERSIONED alternate field decomposition — the same register laid "
        "out two ways depending on a revision. SystemRDL has one layout per "
        "component; `alias` shares an address but not a conditional layout"),
    ("register", "fields_csd_v2"): (
        D_DROPPED, "(nothing)", "second versioned alternate layout; see above"),

    # ---- field scope -----------------------------------------------------
    ("field", "name"): (
        D_NATIVE, "component instance name",
        "sanitised; a name that CHANGES is recorded LOSSY per instance"),
    ("field", "field_name"): (D_NATIVE, "component instance name", "alias of `name`"),
    ("field", "long_name"): (D_NATIVE, "name", ""),
    ("field", "description"): (D_NATIVE, "desc", ""),
    ("field", "bits"): (D_NATIVE, "[msb:lsb]", ""),
    ("field", "msb"): (D_NATIVE, "[msb:lsb]", ""),
    ("field", "lsb"): (D_NATIVE, "[msb:lsb]", ""),
    ("field", "bit"): (D_NATIVE, "[n:n]", "single-bit form"),
    ("field", "size_bits"): (
        D_LOSSY, "[msb:lsb]",
        "a WIDTH without a position; SystemRDL fields are placed, so a width "
        "alone cannot be emitted without inventing an offset"),
    ("field", "byte"): (
        D_LOSSY, "[msb:lsb]",
        "a BYTE index inside a multi-byte payload, not a bit range in a "
        "register; converting it would assert a bit position L4 never gave"),
    ("field", "bytes"): (D_LOSSY, "[msb:lsb]", "byte SPAN; same limitation as `byte`"),
    ("field", "access"): (
        D_NATIVE, "sw / onread / onwrite",
        "NATIVE only for the recognised access acronyms; anything else is "
        "reported per instance"),
    ("field", "encoding"): (
        D_NATIVE, "encode = <enum>",
        "SystemRDL enum MEMBER NAMES must be unique within the enum; a "
        "duplicate mnemonic is reported and disambiguated, never silently kept"),
    ("field", "access_inherited_from_register"): (
        D_UDP, "l4_access_inherited", "provenance"),
    ("field", "synthesised_whole_register_field"): (
        D_LOSSY, "l4_synthesised_whole_register_field",
        "THE LOAD-BEARING ONE. This flag means L4 found no field decomposition "
        "in the source document and stood in a placeholder. SystemRDL has no "
        "placeholder construct: the export must emit a field spanning the full "
        "register width, which ASSERTS a layout the source never stated. The "
        "UDP preserves the caveat for a consumer that looks; a consumer that "
        "reads only the field list sees a claim strengthened in transit"),
    ("field", "synthesised_source"): (D_UDP, "l4_synthesised_source", "provenance"),
    ("field", "extraction_strategy"): (D_UDP, "l4_extraction_strategy", "provenance"),
    ("field", "feature_address"): (
        D_UDP, "l4_feature_address",
        "a second address axis at field scope; SystemRDL addresses registers"),
}

# SystemRDL 2.0 properties a conforming consumer will read out of the emitted
# model that NO L4 key sources. The issue asks for this direction of the gap
# table explicitly. Each entry is (property, component, what a consumer sees).
SYSTEMRDL_NOT_SOURCED_BY_L4: Tuple[Tuple[str, str, str], ...] = (
    ("hw", "field",
     "hardware access mode. SystemRDL DEFAULTS it to `rw`, so a consumer reads "
     "'hardware may read and write this field' — an assertion L4 never makes."),
    ("accesswidth", "reg",
     "the narrowest legal software access. Defaults to `regwidth`, so a "
     "byte-addressable sub-access is silently ruled out."),
    ("addressing", "addrmap",
     "how unspecified addresses are assigned. L4 records no packing rule."),
    ("alignment", "addrmap", "address alignment; L4 records none."),
    ("bigendian / littleendian", "addrmap",
     "byte order of the map. L4 records none, so the model carries the "
     "compiler default."),
    ("counter / incr / decr / threshold", "field",
     "counter hardware. L4's `is_counter` is prose-derived and is deliberately "
     "NOT mapped here, so a real counter declaration is absent even where the "
     "part has one."),
    ("intr / enable / mask / haltenable", "field",
     "interrupt structure. SystemRDL models interrupt aggregation directly; L4 "
     "carries interrupt semantics only as prose in `description`."),
    ("swmod / swacc", "field",
     "software-access strobes. No L4 equivalent."),
    ("singlepulse", "field", "self-clearing write. No L4 equivalent."),
    ("precedence", "field",
     "who wins when hardware and software write the same cycle. No L4 "
     "equivalent, and no default that is obviously right."),
    ("regwidth (when absent from L4)", "reg",
     "L4 often omits `width_bits`; the export must infer one, and the inferred "
     "value becomes an assertion in the model."),
)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RDL_KEYWORDS = frozenset("""
addrmap alias all boolean bothedge compact constraint default encode enum external
false field fullalign hw inside internal level mem na negedge nonsticky number
posedge property r ref reg regalign regfile rset ruser rw rw1 signal string struct
sw swmod this true type unsigned w w1 wr abstract accesstype addressingtype
alternate bit inside onreadtype onwritetype
""".split())


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
import _corpus_location            # sibling program, one seam for all gates
import _published_tree

#: Where a published L4 cell lives, RELATIVE TO THE TREE THAT PUBLISHES IT.
#: The same relative path `l_doc_field_producer_check` and
#: `evidence_citation_resolves_check` resolve through
#: `_corpus_location.default_named`, and the one `benchmark_evidence_index`
#: spells as `IC_SUBDIR`. Derived from the canonical corpus name so the four of
#: them cannot drift to different answers about where the corpus is.
_DEFAULT_CORPUS_REL = _corpus_location.CANONICAL_CORPUS_NAME + "/ic"
import _semantic_child_progress as _semantic_progress

PROGRESS_SCOPE = "issue1710:l4-systemrdl-audit-corpus"
_ACTIVE_PROGRESS = None


def _checkpoint(unit: str) -> None:
    if _ACTIVE_PROGRESS is not None:
        _ACTIVE_PROGRESS.checkpoint(unit)

def _sanitise_ident(raw: str, fallback: str) -> Tuple[str, bool]:
    """Return (identifier, changed). SystemRDL identifiers are C-like."""
    s = (raw or "").strip()
    if not s:
        return fallback, True
    out = re.sub(r"[^A-Za-z0-9_]", "_", s)
    if out and out[0].isdigit():
        out = "_" + out
    if not _IDENT_RE.match(out):
        return fallback, True
    if out.lower() in _RDL_KEYWORDS:
        out = out + "_"
    return out, (out != s)


def _esc(s: str) -> str:
    """Escape a Python string for a SystemRDL double-quoted string literal."""
    return (str(s).replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", " ").replace("\r", " ").replace("\t", " "))


def _parse_int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if not isinstance(v, str):
        return None
    s = v.strip().replace("_", "")
    if not s:
        return None
    try:
        if s.lower().startswith("0x"):
            return int(s, 16)
        if re.fullmatch(r"[0-9]+", s):
            return int(s, 10)
        if re.fullmatch(r"[0-9A-Fa-f]+", s) and re.search(r"[A-Fa-f]", s):
            return int(s, 16)
        return int(s, 0)
    except ValueError:
        return None


def _parse_bits(field: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """Return (msb, lsb) or None. Never guesses."""
    msb, lsb = field.get("msb"), field.get("lsb")
    if isinstance(msb, int) and isinstance(lsb, int) and not isinstance(msb, bool):
        return (max(msb, lsb), min(msb, lsb))
    b = field.get("bits")
    if isinstance(b, int) and not isinstance(b, bool):
        return (b, b)
    single = field.get("bit")
    if isinstance(single, int) and not isinstance(single, bool):
        return (single, single)
    if isinstance(single, str):
        n = _parse_int(single)
        if n is not None:
            return (n, n)
    if isinstance(b, str):
        s = b.strip().strip("[]").replace(" ", "")
        if not s or s.upper() == "WHOLE_REG":
            return None
        m = re.fullmatch(r"(\d+)[:\-](\d+)", s)
        if m:
            hi, lo = int(m.group(1)), int(m.group(2))
            return (max(hi, lo), min(hi, lo))
        if re.fullmatch(r"\d+", s):
            return (int(s), int(s))
    return None


def _is_whole_reg(field: Dict[str, Any]) -> bool:
    b = field.get("bits")
    return (isinstance(b, str) and b.strip().upper() == "WHOLE_REG") or bool(
        field.get("synthesised_whole_register_field"))


def _reg_fields(reg: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key in ("fields", "field_map"):
        v = reg.get(key)
        if isinstance(v, list):
            out.extend([f for f in v if isinstance(f, dict)])
        elif isinstance(v, dict):
            for name, sub in v.items():
                if isinstance(sub, dict):
                    d = dict(sub)
                    d.setdefault("name", name)
                    out.append(d)
    return out


def _reg_address(reg: Dict[str, Any]) -> Optional[int]:
    for key in ("address_int", "address", "offset", "offset_h"):
        if key in reg:
            n = _parse_int(reg.get(key))
            if n is not None:
                return n
    return None


def _norm_access(literal: Any) -> Optional[str]:
    if not isinstance(literal, str):
        return None
    return re.sub(r"\s+", " ", literal.strip()).upper()


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------
class Ledger:
    """Records one entry per NON-NATIVE outcome, with a path to the instance.

    Nothing is ever dropped without an entry here: `note_key` is called for
    EVERY key of every register and field record the exporter meets, and a key
    with no disposition raises.
    """

    def __init__(self) -> None:
        self.entries: List[Dict[str, Any]] = []
        self.unclassified: List[Dict[str, Any]] = []
        self.findings: List[Dict[str, Any]] = []
        self.assumptions: List[Dict[str, Any]] = []
        self.seen_keys: Dict[str, set] = {"register": set(), "field": set()}

    def note_key(self, scope: str, path: str, key: str, value: Any) -> Optional[
            Tuple[str, str, str]]:
        self.seen_keys.setdefault(scope, set()).add(key)
        row = DISPOSITION.get((scope, key))
        if row is None:
            self.unclassified.append({"scope": scope, "path": path, "key": key})
            return None
        disp, target, note = row
        if disp != D_NATIVE and disp != D_STRUCTURAL:
            self.entries.append({
                "scope": scope, "path": path, "l4_key": key,
                "l4_value": _short(value), "disposition": disp,
                "systemrdl": target, "reason": note,
            })
        return row

    def event(self, scope: str, path: str, key: str, disposition: str,
              systemrdl: str, reason: str, value: Any = None) -> None:
        """A per-INSTANCE outcome that the static table cannot state."""
        self.entries.append({
            "scope": scope, "path": path, "l4_key": key,
            "l4_value": _short(value), "disposition": disposition,
            "systemrdl": systemrdl, "reason": reason, "per_instance": True,
        })

    def finding(self, kind: str, path: str, detail: str) -> None:
        self.findings.append({"kind": kind, "path": path, "detail": detail})

    def assume(self, what: str, why: str) -> None:
        self.assumptions.append({"assumption": what, "basis": why})


def _short(v: Any, n: int = 160) -> Any:
    if isinstance(v, (list, dict)):
        s = json.dumps(v, ensure_ascii=False)
    elif v is None or isinstance(v, (int, float, bool)):
        return v
    else:
        s = str(v)
    return s if len(s) <= n else s[: n - 3] + "..."


# --------------------------------------------------------------------------
# the L4 expectation model — built from L4 ALONE, never from the emitter.
#
# The round-trip diff compares the compiled-back SystemRDL model against THIS,
# so a bug shared by the emitter and the comparator cannot cancel out.
# --------------------------------------------------------------------------
def l4_expectation(l4: Dict[str, Any]) -> Dict[str, Any]:
    regs: List[Dict[str, Any]] = []
    for reg in l4.get("registers") or []:
        if not isinstance(reg, dict):
            continue
        name = str(reg.get("name") or reg.get("long_name") or "").strip()
        flds = []
        for f in _reg_fields(reg):
            fname = str(f.get("field_name") or f.get("name") or "").strip()
            span = _parse_bits(f)
            enc = []
            if isinstance(f.get("encoding"), list):
                for e in f["encoding"]:
                    if isinstance(e, dict):
                        enc.append({"pattern": str(e.get("pattern", "")),
                                    "mnem": str(e.get("mnem", ""))})
            flds.append({
                "name": fname,
                "msb": span[0] if span else None,
                "lsb": span[1] if span else None,
                "whole_reg": _is_whole_reg(f),
                "access_literal": f.get("access"),
                "encoding": enc,
            })
        regs.append({
            "name": name,
            "address": _reg_address(reg),
            "width_bits": _parse_int(reg.get("width_bits")),
            "access_literal": reg.get("access"),
            "reset_literal": reg.get("reset_value") or reg.get("reset_hex")
            or reg.get("default") or None,
            "fields": flds,
        })
    return {"ic_name": l4.get("ic_name"), "registers": regs}


# --------------------------------------------------------------------------
# the exporter
# --------------------------------------------------------------------------
_UDP_DECLS: Tuple[Tuple[str, str, str], ...] = (
    # (property name, type, component list)
    ("l4_purpose", "string", "reg"),
    ("l4_structure_summary", "string", "reg"),
    ("l4_sub_address_hex", "string", "reg"),
    ("l4_reset_value_kind", "string", "reg"),
    ("l4_reset_value_source", "string", "reg"),
    ("l4_is_counter", "boolean", "reg"),
    ("l4_kind", "string", "reg"),
    ("l4_endpoint", "string", "reg"),
    ("l4_range", "string", "reg"),
    ("l4_low_confidence", "boolean", "reg"),
    ("l4_role", "string", "reg"),
    ("l4_scope", "string", "reg"),
    ("l4_ap_or_dp", "string", "reg"),
    ("l4_regad", "string", "reg"),
    ("l4_dlab", "string", "reg"),
    ("l4_capture_value", "string", "reg"),
    ("l4_compute_rule", "string", "reg"),
    ("l4_common_values_hex", "string", "reg"),
    ("l4_common_values_hex_lsb_first", "string", "reg"),
    ("l4_evidence", "string", "reg | field"),
    ("l4_evidence_line", "string", "reg | field"),
    ("l4_extraction_strategy", "string", "reg | field"),
    ("l4_access_literal", "string", "reg | field"),
    ("l4_access_inherited", "boolean", "field"),
    ("l4_synthesised_whole_register_field", "boolean", "field"),
    ("l4_synthesised_source", "string", "field"),
    ("l4_feature_address", "string", "field"),
)

# l4 key -> UDP name, for the keys carried verbatim.
_UDP_FOR_KEY: Dict[Tuple[str, str], str] = {
    ("register", "purpose"): "l4_purpose",
    ("register", "structure_summary"): "l4_structure_summary",
    ("register", "sub_address_hex"): "l4_sub_address_hex",
    ("register", "reset_value_kind"): "l4_reset_value_kind",
    ("register", "reset_value_source"): "l4_reset_value_source",
    ("register", "is_counter"): "l4_is_counter",
    ("register", "kind"): "l4_kind",
    ("register", "endpoint"): "l4_endpoint",
    ("register", "range"): "l4_range",
    ("register", "low_confidence"): "l4_low_confidence",
    ("register", "role"): "l4_role",
    ("register", "scope"): "l4_scope",
    ("register", "ap_or_dp"): "l4_ap_or_dp",
    ("register", "regad"): "l4_regad",
    ("register", "dlab"): "l4_dlab",
    ("register", "capture_value_in_CaptureIR"): "l4_capture_value",
    ("register", "compute_rule"): "l4_compute_rule",
    ("register", "common_values_hex"): "l4_common_values_hex",
    ("register", "common_values_hex_lsb_byte_first"): "l4_common_values_hex_lsb_first",
    ("register", "evidence"): "l4_evidence",
    ("register", "evidence_line"): "l4_evidence_line",
    ("register", "extraction_strategy"): "l4_extraction_strategy",
    ("field", "evidence"): "l4_evidence",
    ("field", "extraction_strategy"): "l4_extraction_strategy",
    ("field", "access_inherited_from_register"): "l4_access_inherited",
    ("field", "synthesised_whole_register_field"): "l4_synthesised_whole_register_field",
    ("field", "synthesised_source"): "l4_synthesised_source",
    ("field", "feature_address"): "l4_feature_address",
}


def _udp_literal(kind: str, value: Any) -> Optional[str]:
    if kind == "boolean":
        if isinstance(value, bool):
            return "true" if value else "false"
        return None
    if value is None:
        return None
    return '"%s"' % _esc(value)


def _infer_regwidth(reg: Dict[str, Any], spans: List[Tuple[int, int]],
                    ledger: Ledger, path: str) -> int:
    w = _parse_int(reg.get("width_bits"))
    if w and w > 0:
        return w
    top = max((s[0] for s in spans), default=-1)
    if top < 0:
        ledger.event("register", path, "width_bits", D_LOSSY, "regwidth",
                     "L4 states no width and no field reaches a bit position; "
                     "SystemRDL requires a regwidth, so 32 is ASSERTED here and "
                     "the model carries a width the source never gave")
        return 32
    for cand in (8, 16, 32, 64, 128):
        if top < cand:
            if cand != top + 1:
                ledger.event(
                    "register", path, "width_bits", D_LOSSY, "regwidth",
                    "L4 states no width; inferred %d from the highest field bit "
                    "(%d). SystemRDL has no 'width unknown', so the inference "
                    "becomes an assertion" % (cand, top))
            return cand
    return top + 1


def export_rdl(l4: Dict[str, Any], *, address_unit: str = "byte",
               source_path: str = "") -> Tuple[str, Dict[str, Any], Ledger]:
    """Emit SystemRDL 2.0 text + the expressibility ledger."""
    ledger = Ledger()
    if address_unit == "word":
        ledger.assume(
            "L4 `address` is a WORD/INDEX, multiplied by regwidth/8 to obtain "
            "the SystemRDL byte address",
            "requested explicitly via --address-unit word; L4 itself states no "
            "unit, so this is the CALLER's assertion, not a fact read from L4")

    # The ADDRESSING GRANULARITY of the whole map, decided once. Derived from
    # the widest register the map declares, because that is the unit an index
    # must step by for the registers to be non-overlapping; 32-bit when the
    # map declares nothing.
    _word_stride_bytes = 4
    if address_unit == "word":
        _widths = []
        for _r in (l4.get("registers") or []):
            _w = _r.get("size") or _r.get("width") or _r.get("regwidth")
            _wi = _parse_int(_w)
            if _wi and _wi > 0:
                _widths.append(_wi)
        _word_stride_bytes = max(1, (max(_widths) if _widths else 32) // 8)

    # top-level keys the exporter consumes structurally; everything else at
    # top level is an L4 sidecar that is outside SystemRDL's object model and
    # is NAMED (never silently ignored).
    structural_top = {
        "registers", "ic_name", "base_address", "notes", "schema_version",
        "doc_class", "register_map_present", "no_registers_in_input",
    }
    # A few top-level keys ARE register content and would be expressible; they
    # are dropped because this increment exports one addrmap from `registers[]`
    # alone. Saying "outside the object model" about them would be false.
    _EXPRESSIBLE_BUT_OUT_OF_SCOPE = {
        "internal_registers":
            "these ARE registers and SystemRDL could hold them — as a second "
            "addrmap, or as components marked non-`external`. They are dropped "
            "because this increment exports `registers[]` only, which is a "
            "scope limit of the exporter, NOT a limit of the standard",
        "otp_layout":
            "a one-time-programmable array is a `mem` in SystemRDL, which this "
            "increment does not emit. A limit of the exporter, not the standard",
        "otp_ip_macro":
            "macro identity/parameters; SystemRDL models the programming "
            "interface, not the macro instance behind it",
    }
    for key in sorted(l4.keys()):
        if key in structural_top:
            continue
        value = l4.get(key)
        special = _EXPRESSIBLE_BUT_OUT_OF_SCOPE.get(key)
        if special is not None:
            empty = value in (None, [], {}, "")
            ledger.event(
                "addrmap", "<root>", key, D_DROPPED, "(nothing)",
                special + ("; EMPTY in this document, so nothing was actually "
                           "lost here" if empty else ""), value)
            continue
        ledger.event(
            "addrmap", "<root>", key, D_DROPPED, "(nothing)",
            "outside SystemRDL's object model: an addrmap carries components "
            "and properties, not free-form document sections", value)

    ic_name, _ = _sanitise_ident(str(l4.get("ic_name") or "regmap"), "regmap")

    enums: List[str] = []
    body: List[str] = []
    emitted_regs = 0
    emitted_fields = 0
    # byte spans already claimed, so a collision is reported HERE with the L4
    # record that caused it rather than discovered later as a compiler error
    # naming only the emitted identifier.
    claimed: List[Tuple[int, int, str]] = []

    for idx, reg in enumerate(l4.get("registers") or []):
        if not isinstance(reg, dict):
            ledger.event("register", "registers[%d]" % idx, "<record>", D_DROPPED,
                         "(nothing)", "register record is not an object")
            continue
        raw_name = str(reg.get("name") or reg.get("long_name") or "")
        path = "%s" % (raw_name or "registers[%d]" % idx)

        # ---- disposition sweep over EVERY key of this record -------------
        # Runs BEFORE any decision to omit the register, so a record that is
        # dropped for some other reason still has each of its keys classified.
        for key in reg.keys():
            ledger.note_key("register", path, key, reg.get(key))
        flds = _reg_fields(reg)
        for f in flds:
            fpath = "%s.%s" % (path, f.get("field_name") or f.get("name") or "?")
            for key in f.keys():
                ledger.note_key("field", fpath, key, f.get(key))

        reg_ident, changed = _sanitise_ident(raw_name, "REG_%d" % idx)
        if changed:
            ledger.event("register", path, "name", D_LOSSY,
                         "component instance name",
                         "L4 name %r is not a SystemRDL identifier; emitted as "
                         "%r" % (raw_name, reg_ident), raw_name)

        addr = _reg_address(reg)
        if addr is None:
            ledger.event(
                "register", path, "address", D_DROPPED, "(register omitted)",
                "L4 records no address for this register. SystemRDL would place "
                "it at the next free offset, INVENTING an address the source "
                "never gave, so the register is omitted from the export instead")
            continue

        spans: List[Tuple[int, int]] = []
        for f in flds:
            s = _parse_bits(f)
            if s:
                spans.append(s)
        regwidth = _infer_regwidth(reg, spans, ledger, path)
        if address_unit == "word":
            # UNIFORM stride, not this register's own width. A word/index
            # address maps to a byte address by the MAP's addressing
            # granularity; scaling each register by its own inferred width
            # gives a different multiplier per register and produces a map
            # whose addresses no longer reflect the source order.
            #
            # MEASURED on the published ibex L4: 41 of 43 registers got x4
            # while `cpuctrlsts` (inferred 16-bit) got x2 and `mseccfg`
            # (inferred 8-bit) got x1 — two registers landing at addresses
            # that are not their index times anything the map declares.
            addr = addr * _word_stride_bytes
        

        reg_access = _norm_access(reg.get("access"))
        reg_reset = _parse_int(reg.get("reset_value") or reg.get("reset_hex")
                               or reg.get("default"))
        if reg_reset is None:
            # Every key that could have carried a reset gets its own entry.
            # Checking only `reset_value` left a real case unreported: a
            # register whose `default` alone said "unspecified".
            for rk in ("reset_value", "reset_hex", "default"):
                rv = reg.get(rk)
                if rv is None or (isinstance(rv, str) and not rv.strip()):
                    continue
                ledger.event(
                    "register", path, rk, D_DROPPED, "(nothing)",
                    "SystemRDL `reset` admits a value or a reference only; this "
                    "one is not numeric so NOTHING is emitted, and a consumer "
                    "reads a field with no reset — a different statement from "
                    "'the document did not say'", rv)

        # register-level access literal that is not an access mode at all
        if reg_access is not None and reg_access not in _ACCESS_MAP \
                and reg_access not in _LEGALITY_CONSTRAINT_ACCESS and reg_access:
            ledger.event(
                "register", path, "access", D_DROPPED, "(nothing)",
                "L4 access literal is not a register-access mode; SystemRDL "
                "`sw` admits exactly %s" % (", ".join(_SW_LEGAL),),
                reg.get("access"))
            ledger.finding(
                "access_literal_outside_closed_vocabulary", path,
                "register access %r has no SystemRDL `sw` equivalent"
                % (reg.get("access"),))

        lines: List[str] = []
        lines.append("    reg {")
        lines.append("        regwidth = %d;" % regwidth)
        long_name = reg.get("long_name")
        if isinstance(long_name, str) and long_name.strip():
            lines.append('        name = "%s";' % _esc(long_name))
        desc_parts = [str(reg.get(k)) for k in ("description", "desc", "notes")
                      if isinstance(reg.get(k), str) and reg.get(k).strip()]
        if desc_parts:
            lines.append('        desc = "%s";' % _esc(" — ".join(desc_parts)))
        for key, value in sorted(reg.items()):
            udp = _UDP_FOR_KEY.get(("register", key))
            if not udp:
                continue
            kind = next((t for n, t, _c in _UDP_DECLS if n == udp), "string")
            lit = _udp_literal(kind, value)
            if lit is not None:
                lines.append("        %s = %s;" % (udp, lit))
            elif value is not None:
                # The static table promised this key was CARRIED. It was not.
                # Leaving the promise standing would make the ledger itself the
                # false certificate.
                ledger.event(
                    "register", path, key, D_DROPPED, "(nothing)",
                    "the user-defined property %s is typed `%s` and this value "
                    "cannot be rendered as one, so the key is NOT carried "
                    "despite its disposition" % (udp, kind), value)
        if reg.get("access") is not None:
            lines.append('        l4_access_literal = "%s";'
                         % _esc(reg.get("access")))

        # ---- fields -----------------------------------------------------
        used: List[Tuple[int, int, str]] = []
        field_lines: List[str] = []
        for fi, f in enumerate(flds):
            fname_raw = str(f.get("field_name") or f.get("name") or "")
            fpath = "%s.%s" % (path, fname_raw or "fields[%d]" % fi)
            span = _parse_bits(f)
            if span is None:
                if _is_whole_reg(f):
                    span = (regwidth - 1, 0)
                    ledger.event(
                        "field", fpath, "bits", D_LOSSY, "[%d:0]" % (regwidth - 1),
                        "L4 marks this a synthesised WHOLE_REG placeholder — the "
                        "source document had no field decomposition. SystemRDL "
                        "has no placeholder, so the export ASSERTS one field "
                        "spanning the whole register: a claim the source never "
                        "made", f.get("bits"))
                    ledger.finding(
                        "placeholder_promoted_to_asserted_layout", fpath,
                        "synthesised WHOLE_REG placeholder becomes an asserted "
                        "[%d:0] field in SystemRDL" % (regwidth - 1))
                else:
                    ledger.event(
                        "field", fpath, "bits", D_DROPPED, "(field omitted)",
                        "no bit position is derivable from L4 and SystemRDL "
                        "fields must be placed; inventing one would be worse "
                        "than omitting the field", f.get("bits"))
                    continue
            msb, lsb = span
            if msb >= regwidth:
                ledger.event(
                    "field", fpath, "bits", D_DROPPED, "(field omitted)",
                    "field bit %d lies outside the %d-bit register; SystemRDL "
                    "rejects it" % (msb, regwidth), f.get("bits"))
                ledger.finding("field_outside_register_width", fpath,
                               "msb=%d regwidth=%d" % (msb, regwidth))
                continue
            clash = next((u for u in used if not (msb < u[1] or lsb > u[0])), None)
            if clash is not None:
                ledger.event(
                    "field", fpath, "bits", D_DROPPED, "(field omitted)",
                    "bits [%d:%d] overlap field %r at [%d:%d]; SystemRDL "
                    "forbids overlapping fields, our schema does not"
                    % (msb, lsb, clash[2], clash[0], clash[1]), f.get("bits"))
                ledger.finding("overlapping_fields", fpath,
                               "[%d:%d] overlaps %s[%d:%d]"
                               % (msb, lsb, clash[2], clash[0], clash[1]))
                continue

            fident, fchanged = _sanitise_ident(fname_raw, "FIELD_%d_%d" % (msb, lsb))
            if fchanged:
                ledger.event("field", fpath, "name", D_LOSSY,
                             "component instance name",
                             "L4 field name %r is not a SystemRDL identifier; "
                             "emitted as %r" % (fname_raw, fident), fname_raw)
            if any(u[2] == fident for u in used):
                ledger.event(
                    "field", fpath, "name", D_DROPPED, "(field omitted)",
                    "a sibling field already uses the identifier %r; SystemRDL "
                    "instance names must be unique within a register"
                    % (fident,), fname_raw)
                ledger.finding("duplicate_field_identifier", fpath, fident)
                continue
            used.append((msb, lsb, fident))

            fl: List[str] = []
            acc_literal = f.get("access") if f.get("access") is not None \
                else reg.get("access")
            acc = _norm_access(acc_literal)
            sw = onread = onwrite = None
            if acc in _ACCESS_MAP:
                sw, onread, onwrite = _ACCESS_MAP[acc]
            elif acc in _LEGALITY_CONSTRAINT_ACCESS:
                sw = _LEGALITY_CONSTRAINT_ACCESS[acc]
                ledger.event(
                    "field", fpath, "access", D_LOSSY, "sw = %s" % sw,
                    "%r names a WRITE-LEGALITY constraint, not an access mode. "
                    "SystemRDL `sw`/`onwrite` say what a write DOES, never "
                    "which values are admissible, so the legality half is LOST"
                    % (acc_literal,), acc_literal)
                ledger.finding("write_legality_constraint_lost", fpath,
                               str(acc_literal))
            elif acc:
                ledger.event(
                    "field", fpath, "access", D_DROPPED, "(no sw emitted)",
                    "L4 access literal %r is not an access mode; SystemRDL `sw` "
                    "admits exactly %s" % (acc_literal, ", ".join(_SW_LEGAL)),
                    acc_literal)
                ledger.finding("access_literal_outside_closed_vocabulary",
                               fpath, str(acc_literal))
            if sw:
                fl.append("sw = %s;" % sw)
            if onread:
                fl.append("onread = %s;" % onread)
            if onwrite:
                fl.append("onwrite = %s;" % onwrite)

            # reset: sliced out of the register-scope value
            if reg_reset is not None:
                width = msb - lsb + 1
                slice_val = (reg_reset >> lsb) & ((1 << width) - 1)
                fl.append("reset = %d'h%X;" % (width, slice_val))

            fdesc = f.get("description") or f.get("desc")
            if isinstance(fdesc, str) and fdesc.strip():
                fl.append('desc = "%s";' % _esc(fdesc))
            fln = f.get("long_name")
            if isinstance(fln, str) and fln.strip():
                fl.append('name = "%s";' % _esc(fln))

            # encoding -> SystemRDL enum
            enc = f.get("encoding")
            if isinstance(enc, list) and enc:
                enum_name = "%s_%s_e" % (reg_ident, fident)
                members: List[str] = []
                seen_names: Dict[str, int] = {}
                width = msb - lsb + 1
                for e in enc:
                    if not isinstance(e, dict):
                        continue
                    pat = str(e.get("pattern", "")).strip()
                    val = None
                    if re.fullmatch(r"[01]+", pat):
                        val = int(pat, 2)
                    else:
                        val = _parse_int(pat)
                    if val is None or val >= (1 << width):
                        ledger.event(
                            "field", fpath, "encoding", D_DROPPED,
                            "(enum member omitted)",
                            "encoding pattern %r is not a value representable "
                            "in the %d-bit field" % (pat, width), e)
                        continue
                    mnem_raw = str(e.get("mnem", "")).strip()
                    mname, mchanged = _sanitise_ident(
                        mnem_raw, "VAL_%d" % val)
                    if mname in seen_names:
                        newname = "%s_%s" % (mname, format(val, "b").zfill(width))
                        ledger.event(
                            "field", fpath, "encoding", D_LOSSY,
                            "enum member %s" % newname,
                            "L4 gives two distinct encodings the SAME mnemonic "
                            "%r; SystemRDL enum member names must be unique, so "
                            "the second is disambiguated. Our schema accepts the "
                            "collision silently" % (mnem_raw,), e)
                        ledger.finding("duplicate_enum_mnemonic", fpath,
                                       "mnemonic %r reused" % (mnem_raw,))
                        mname = newname
                    elif mchanged:
                        ledger.event(
                            "field", fpath, "encoding", D_LOSSY,
                            "enum member %s" % mname,
                            "L4 mnemonic %r is not a SystemRDL identifier"
                            % (mnem_raw,), e)
                    seen_names[mname] = val
                    edesc = str(e.get("description") or mnem_raw)
                    members.append('    %s = %d\'b%s { desc = "%s"; };'
                                   % (mname, width,
                                      format(val, "b").zfill(width), _esc(edesc)))
                    for extra in e.keys():
                        if extra in ("pattern", "mnem", "description"):
                            continue
                        ledger.event(
                            "field", fpath, "encoding.%s" % extra, D_DROPPED,
                            "(nothing)",
                            "SystemRDL enum members carry `name` and `desc` "
                            "only", e.get(extra))
                if members:
                    enums.append("enum %s {\n%s\n};" % (enum_name,
                                                        "\n".join(members)))
                    fl.append("encode = %s;" % enum_name)

            for key, value in sorted(f.items()):
                udp = _UDP_FOR_KEY.get(("field", key))
                if not udp:
                    continue
                kind = next((t for n, t, _c in _UDP_DECLS if n == udp), "string")
                lit = _udp_literal(kind, value)
                if lit is not None:
                    fl.append("%s = %s;" % (udp, lit))
                elif value is not None:
                    ledger.event(
                        "field", fpath, key, D_DROPPED, "(nothing)",
                        "the user-defined property %s is typed `%s` and this "
                        "value cannot be rendered as one, so the key is NOT "
                        "carried despite its disposition" % (udp, kind), value)
            if acc_literal is not None:
                fl.append('l4_access_literal = "%s";' % _esc(acc_literal))

            field_lines.append("        field { %s } %s[%d:%d];"
                               % (" ".join(fl), fident, msb, lsb))

        if reg_reset is not None and used:
            covered = 0
            for m, l, _n in used:
                covered |= ((1 << (m - l + 1)) - 1) << l
            lost = reg_reset & ~covered
            if lost:
                ledger.event(
                    "register", path, "reset_value", D_LOSSY,
                    "per-field reset", "SystemRDL has no register-scope reset; "
                    "the value was sliced per field and the bits set in 0x%X "
                    "fall outside every field, so they are LOST" % lost,
                    reg.get("reset_value"))
                ledger.finding("reset_bits_outside_any_field", path, hex(lost))

        # SystemRDL 2.0: a `reg` must contain at least one field. Our schema
        # admits a register that describes nothing, and 5 of them appear in a
        # single published document.
        if not field_lines:
            ledger.event(
                "register", path, "fields", D_DROPPED, "(register omitted)",
                "SystemRDL requires a `reg` to contain at least one field; this "
                "L4 record carries none that could be placed, so there is "
                "nothing for the standard to hold")
            ledger.finding("register_with_no_expressible_field", path,
                           "%d L4 field record(s), 0 placeable" % len(flds))
            continue

        span_lo = addr
        span_hi = addr + max(1, regwidth // 8) - 1
        hit = next((c for c in claimed
                    if not (span_hi < c[0] or span_lo > c[1])), None)
        if hit is not None:
            ledger.event(
                "register", path, "address", D_DROPPED, "(register omitted)",
                "bytes 0x%X-0x%X are already claimed by register %r at "
                "0x%X-0x%X. SystemRDL forbids overlapping instances in an "
                "addrmap; L4 admits two records claiming one address"
                % (span_lo, span_hi, hit[2], hit[0], hit[1]), reg.get("address"))
            ledger.finding("register_address_collision", path,
                           "0x%X-0x%X collides with %s"
                           % (span_lo, span_hi, hit[2]))
            continue
        claimed.append((span_lo, span_hi, reg_ident))

        lines.extend(field_lines)
        lines.append("    } %s @ 0x%X;" % (reg_ident, addr))
        body.append("\n".join(lines))
        emitted_regs += 1
        emitted_fields += len(field_lines)

    # ---- assemble ------------------------------------------------------
    dropped = sum(1 for e in ledger.entries if e["disposition"] == D_DROPPED)
    lossy = sum(1 for e in ledger.entries if e["disposition"] == D_LOSSY)
    udps = sum(1 for e in ledger.entries if e["disposition"] == D_UDP)

    header = [
        "// SystemRDL 2.0 — generated by l4_systemrdl_export.py (vibe-ic#377 B).",
        "// SOURCE: %s" % (source_path or "<stdin>"),
        "//",
        "// THIS FILE IS NOT A COMPLETE DESCRIPTION OF THE SOURCE REGISTER MAP.",
        "//   %4d L4 statements had NO SystemRDL construct and are absent here"
        % dropped,
        "//   %4d landed WEAKER, STRONGER or DIFFERENT than the source said"
        % lossy,
        "//   %4d are carried only through user-defined properties" % udps,
        "// Every one is named, with a reason, in the companion ledger JSON.",
        "// Reading this file without the ledger will overstate what is known.",
        "//",
        "// address unit: %s%s" % (
            address_unit,
            " (CALLER ASSERTION — L4 states no unit)"
            if address_unit == "word" else " (as stated in L4)"),
        "",
    ]
    decls = ["property %s { type = %s; component = %s; };" % (n, t, c)
             for n, t, c in _UDP_DECLS]
    rdl = "\n".join(header + decls + [""] + enums + [""]
                    + ["addrmap %s {" % ic_name]
                    + ([ '    desc = "%s";' % _esc(l4["notes"]) ]
                       if isinstance(l4.get("notes"), str) and l4["notes"].strip()
                       else [])
                    + body + ["};", ""])

    summary = {
        "tool": "l4_systemrdl_export",
        "standard": STANDARD,
        "source_l4": source_path,
        "ic_name": l4.get("ic_name"),
        "address_unit": address_unit,
        "registers_in_l4": len(l4.get("registers") or []),
        "registers_emitted": emitted_regs,
        "fields_emitted": emitted_fields,
        "disposition_counts": {
            D_DROPPED: dropped, D_LOSSY: lossy, D_UDP: udps,
        },
    }
    return rdl, summary, ledger


# --------------------------------------------------------------------------
# round trip — a REAL parse or an explicit refusal. Never a simulated one.
# --------------------------------------------------------------------------
def _import_systemrdl():
    try:
        from systemrdl import RDLCompiler, RDLCompileError  # type: ignore
        return RDLCompiler, RDLCompileError, None
    except Exception as exc:                                # pragma: no cover
        return None, None, "%s: %s" % (type(exc).__name__, exc)


def _collecting_printer():
    """A MessagePrinter that CAPTURES compiler diagnostics instead of printing.

    Without this the compiler's own stderr is all a caller gets, and it ends
    at 'Elaborate aborted due to previous errors' — a summary that names no
    defect. The individual messages ARE the finding, so they are captured and
    written into the ledger rather than left on a terminal.
    """
    from systemrdl.messages import MessagePrinter, Severity  # type: ignore

    collected: List[Dict[str, str]] = []

    class _Collector(MessagePrinter):
        def print_message(self, severity, text, src_ref):   # type: ignore
            collected.append({"severity": severity.name.lower(),
                              "text": str(text)})

    return _Collector(), collected, Severity


def roundtrip(rdl_text: str, expectation: Dict[str, Any], *,
              address_unit: str, workdir: Path,
              emitted_registers: Optional[int] = None) -> Dict[str, Any]:
    """Compile the emitted RDL with a REAL SystemRDL compiler and diff back.

    If no compiler is importable the verdict is PARSER_UNAVAILABLE. That is
    NOT a pass and is never reported as one: a structural self-check runs in
    its place and says so in its own name.
    """
    # An L4 with no registers, or none the export could place, produces an
    # EMPTY addrmap. A conforming compiler rejects an empty addrmap, and
    # reporting that as COMPILE_REJECTED would count a document that never
    # described a register map as evidence against the standard. It is not:
    # it is a different fact and gets a different verdict.
    if not expectation["registers"]:
        return {
            "verdict": "NOT_APPLICABLE",
            "reason": "the L4 document declares no registers[], so there is no "
                      "register map to express. No parse was attempted and this "
                      "is NOT evidence about SystemRDL either way.",
        }
    if emitted_registers == 0:
        return {
            "verdict": "EMPTY_EXPORT",
            "reason": "the L4 declares %d register(s) but NOT ONE could be "
                      "placed: no record states an address under a key that "
                      "carries one. SystemRDL requires an addrmap to contain at "
                      "least one component, so there is nothing to compile. The "
                      "finding is about the source layer, not the standard."
                      % len(expectation["registers"]),
            "registers_in_l4": len(expectation["registers"]),
        }

    RDLCompiler, RDLCompileError, why = _import_systemrdl()
    if RDLCompiler is None:
        return {
            "verdict": "PARSER_UNAVAILABLE",
            "parser": {"available": False, "package": "systemrdl-compiler",
                       "reason": why},
            "note": "No SystemRDL parse was performed. The export was NOT "
                    "validated against the standard's grammar or elaboration "
                    "rules; only the structural self-check below ran.",
            "structural_self_check": _structural_self_check(rdl_text),
        }

    workdir.mkdir(parents=True, exist_ok=True)
    src = workdir / "export.rdl"
    src.write_text(rdl_text, encoding="utf-8")

    printer, messages, _sev = _collecting_printer()
    c = RDLCompiler(message_printer=printer)
    try:
        c.compile_file(str(src))
        root = c.elaborate()
    except Exception as exc:                     # RDLCompileError and friends
        errors = [m for m in messages if m["severity"] == "error"]
        return {
            "verdict": "COMPILE_REJECTED",
            "parser": {"available": True, "package": "systemrdl-compiler",
                       "version": _rdl_version()},
            "error": str(exc),
            "error_count": len(errors),
            "compiler_messages": errors[:200],
            "note": "A conforming SystemRDL compiler REFUSED the export. Each "
                    "message below is a statement the standard's elaboration "
                    "rules make about the SOURCE register map, not only about "
                    "this exporter.",
        }

    # ---- walk the elaborated model back into a comparable shape ---------
    got: Dict[str, Dict[str, Any]] = {}
    for node in root.descendants():
        cls = type(node).__name__
        if cls != "RegNode":
            continue
        rfields = {}
        for fnode in node.fields():
            enc = []
            try:
                e = fnode.get_property("encode", default=None)
            except Exception:
                e = None
            if e is not None:
                for m in e:
                    enc.append({"mnem": m.name, "value": int(m.value)})
            try:
                rst = fnode.get_property("reset", default=None)
            except Exception:
                rst = None
            rfields[fnode.inst_name] = {
                "msb": fnode.msb, "lsb": fnode.lsb,
                "sw": str(fnode.get_property("sw", default=None)),
                "reset": int(rst) if isinstance(rst, int) else None,
                "encoding": enc,
                "l4_access_literal": fnode.get_property(
                    "l4_access_literal", default=None),
            }
        got[node.inst_name] = {
            "address": node.absolute_address,
            "regwidth": node.get_property("regwidth", default=None),
            "fields": rfields,
        }

    # ---- diff against the L4 expectation --------------------------------
    lost_regs: List[Dict[str, Any]] = []
    field_rows: List[Dict[str, Any]] = []
    stride = 1
    for reg in expectation["registers"]:
        ident, _ = _sanitise_ident(reg["name"], "")
        rt = got.get(ident)
        if rt is None:
            lost_regs.append({"l4_name": reg["name"],
                              "why": "not present in the parsed-back model"})
            continue
        if reg["address"] is not None:
            expected_addr = reg["address"]
            if address_unit == "word":
                expected_addr *= max(1, (rt["regwidth"] or 32) // 8)
            if rt["address"] != expected_addr:
                field_rows.append({
                    "register": reg["name"], "field": "(register address)",
                    "attribute": "address", "l4": hex(reg["address"]),
                    "systemrdl": hex(rt["address"]), "verdict": "ALTERED"})
        for f in reg["fields"]:
            fident, _ = _sanitise_ident(f["name"], "")
            g = rt["fields"].get(fident)
            if g is None:
                field_rows.append({
                    "register": reg["name"], "field": f["name"],
                    "attribute": "(whole field)", "l4": "present",
                    "systemrdl": "absent", "verdict": "LOST"})
                continue
            if f["msb"] is not None and g["msb"] != f["msb"]:
                field_rows.append({
                    "register": reg["name"], "field": f["name"],
                    "attribute": "msb", "l4": f["msb"],
                    "systemrdl": g["msb"], "verdict": "ALTERED"})
            if f["lsb"] is not None and g["lsb"] != f["lsb"]:
                field_rows.append({
                    "register": reg["name"], "field": f["name"],
                    "attribute": "lsb", "l4": f["lsb"],
                    "systemrdl": g["lsb"], "verdict": "ALTERED"})
            if f["whole_reg"] and f["msb"] is None:
                field_rows.append({
                    "register": reg["name"], "field": f["name"],
                    "attribute": "bit range", "l4": "WHOLE_REG (placeholder)",
                    "systemrdl": "[%d:%d] (asserted)" % (g["msb"], g["lsb"]),
                    "verdict": "STRENGTHENED"})
            if f["access_literal"] is not None:
                if g["l4_access_literal"] != f["access_literal"]:
                    field_rows.append({
                        "register": reg["name"], "field": f["name"],
                        "attribute": "access literal", "l4": f["access_literal"],
                        "systemrdl": g["l4_access_literal"], "verdict": "ALTERED"})
                elif _norm_access(f["access_literal"]) in _LEGALITY_CONSTRAINT_ACCESS:
                    field_rows.append({
                        "register": reg["name"], "field": f["name"],
                        "attribute": "access semantics",
                        "l4": f["access_literal"],
                        "systemrdl": "sw=%s (write-legality constraint absent)"
                                     % g["sw"], "verdict": "WEAKENED"})
            l4_mnems = [e["mnem"] for e in f["encoding"]]
            rt_mnems = [e["mnem"] for e in g["encoding"]]
            if l4_mnems and sorted(l4_mnems) != sorted(rt_mnems):
                field_rows.append({
                    "register": reg["name"], "field": f["name"],
                    "attribute": "encoding mnemonics", "l4": l4_mnems,
                    "systemrdl": rt_mnems, "verdict": "ALTERED"})

    survived = not lost_regs and not field_rows
    return {
        "verdict": "ROUNDTRIP_CLEAN" if survived else "ROUNDTRIP_LOSSY",
        "parser": {"available": True, "package": "systemrdl-compiler",
                   "version": _rdl_version()},
        "registers_parsed_back": len(got),
        "registers_lost": lost_regs,
        "field_differences": field_rows,
        "compiler_messages": messages[:200],
        "stride": stride,
    }


def _rdl_version() -> str:
    try:
        import systemrdl.__about__ as about       # type: ignore
        return str(about.__version__)
    except Exception:
        return "unknown"


def _structural_self_check(rdl_text: str) -> Dict[str, Any]:
    """Balance/shape check ONLY. Named so it cannot be mistaken for a parse."""
    return {
        "what_this_is": "brace/paren balance and instance counting on the "
                        "emitted text. It is NOT a SystemRDL parse and proves "
                        "nothing about conformance.",
        "braces_balanced": rdl_text.count("{") == rdl_text.count("}"),
        "reg_instances": len(re.findall(r"^\s*\}\s+\w+\s*@", rdl_text, re.M)),
        "field_instances": len(re.findall(r"^\s*field\s*\{", rdl_text, re.M)),
    }


# --------------------------------------------------------------------------
# corpus audit — the CI gate
# --------------------------------------------------------------------------
_L4_GLOB = "L4_REGMAP.json"


def _l4_documents(root: Path, *,
                  semantic_strict: bool = False) -> Tuple[List[Path], int, bool]:
    """`(published documents, raw hits on disk, root is a published tree)`.

    The two numbers are returned together because the DIFFERENCE between them is
    the thing this program has already been wrong about once: `audit-corpus`
    found "0 of 201 documents" and printed PASS. A caller that receives only the
    kept list cannot tell "there are none" from "I dropped them all".

    `root is a published tree` is False when git cannot answer for `root` — a
    tarball fetch, an archive export or a loose directory. `_published_tree`
    rules that presence on disk is then the honest answer (nothing has been
    published there, so tracked-ness is not a question that applies), and this
    function returns the raw walk with the flag saying so, rather than silently
    presenting a disk walk as a statement about a published corpus.
    """
    hits = list(_iter_l4(root))
    if semantic_strict:
        # A loose run directory is an explicitly supported population: there
        # is no published index, so its disk is the only possible answer.  A
        # semantic caller first classifies that state with an unbounded Git
        # probe.  Only a real checkout reaches strict index enumeration; probe
        # launch/stall/protocol failure raises and becomes NORECORD instead of
        # silently selecting the loose-directory branch.
        loose = _corpus_location.not_a_checkout_reason(
            root, f"published {_L4_GLOB} paths", timeout=None, strict=True)
        if loose:
            return hits, len(hits), False
    published = _published_tree.published_paths(
        root, timeout=None if semantic_strict else 180,
        strict=semantic_strict)
    if published is None:
        return hits, len(hits), False
    # The filter itself stays in `_published_tree`: a second copy of "is this
    # path in the published set" here would be a predicate that looks
    # authoritative and tracks nothing.
    return _published_tree.filter_to_published(
        root, hits, published=published), len(hits), True


#: THIS PLUGIN'S OWN TEST DATA IS NOT A PUBLISHED CORPUS DOCUMENT, and the
#: exclusion is anchored to the ABSOLUTE directory rather than to the name
#: `tests`, so a real corpus that happens to carry a `tests/` directory keeps
#: every document it publishes.
#:
#: WHAT IT COST TO LEARN THIS, TWICE. `registry_is_the_iteration_domain`
#: records the first instance: while its census counted fixtures, three JSON
#: basenames existed ONLY under `programs/tests/fixtures/**`, and their
#: presence alone moved a shipped gate's pinned reach from 1 to 3 — a landed
#: test FIXTURE had moved a boundary in a gate nobody had touched since v1.0.0.
#:
#: The second instance is this one, MEASURED at 20031834c1 with no corpus
#: pointer bound: `audit-corpus --root <repo>` reported `7 on disk, 7
#: published` and `[PASS] every register/field key in the published corpus has
#: a recorded disposition`. All seven were the hand-written L4 documents
#: `4ce74e03b` (v1.13.37, PR #1845) added under
#: `programs/tests/fixtures/stage_phase1_on_pass_review/**`, seven months after
#: the corpus itself left this repository in v1.10.56. Two consequences, and
#: the second is the worse one:
#:
#:   * NO_CORPUS could never fire. With `--corpus-may-be-absent` and no
#:     pointer, the program is supposed to STATE that it scanned nothing;
#:     instead it certified seven fixtures. Without the flag it is supposed to
#:     exit 2 UNDETERMINED; it exited 0.
#:   * A CORPUS OF ENTIRELY UNREADABLE DOCUMENTS WAS CERTIFIED. Point the
#:     pointer at a tree whose only L4 document is unparseable and the seven
#:     fixtures supply the keys, every one of them has a disposition, and the
#:     program prints PASS — the exact `0 of 201 documents -> PASS` shape its
#:     own docstring records it having been wrong about once.
_TEST_DATA_DIR = Path(__file__).resolve().parent / "tests"


def corpus_root_of(tree: Path) -> Path:
    """The corpus `tree` publishes when `tree` is a REPOSITORY; `tree` itself
    when it is already a corpus.

    `--root` has always meant both, and that is the ambiguity a fixture walked
    through. `test_corpus_audit_fails_on_an_unclassified_key` points it at a
    bare directory holding `a/phase1/generated_docs/L4_REGMAP.json` and
    requires the gate to redden — `--root` NAMES A CORPUS there. The CI call
    site points it at the checkout — `--root` NAMES A REPOSITORY there, and
    the corpus it publishes is `benchmark-data/ic`. Reading the second as the
    first is what let seven pytest fixtures be certified as a published corpus.

    The two are told apart BY BEHAVIOUR, not by a flag or a name: a repository
    root is the directory carrying `vibe-ic-marketplace/`, which is what
    `_corpus_location.repo_root` already answers and what its `_REPO_MARKER`
    comment already justifies (present in a tarball export and a worktree, not
    only in a `.git` checkout).

    WHAT THIS ADDS TO `_TEST_DATA_DIR` ABOVE. v1.16.32 (37a46c00ca) closed the
    measured instance — the seven documents 4ce74e03b (v1.13.37, PR #1845)
    landed under `programs/tests/fixtures/stage_phase1_on_pass_review/**`,
    seven months after the corpus left in v1.10.56. That exclusion is correct
    and is KEPT: it is `_iter_l4`'s own contract about this plugin's test data
    and it carries the recorded reason for it.

    It is anchored at `programs/tests/`, so it answers for the documents that
    were there. It does not answer for one somewhere else. MEASURED at
    bcedcdf25d9c in the real checkout, one cell-shaped document planted at
    `docs/campaigns/<run>/phase1/generated_docs/L4_REGMAP.json`::

        root <repo>: 1 on disk, 1 published
        [FAIL] 1 L4 key(s) have NO recorded SystemRDL disposition.
           register an_unclassified_key  first seen: docs/campaigns/...

    `docs/campaigns/` is not a hypothetical address: v1.15.79 is where the
    campaign trees were MOVED TO. An exclusion answers "is this directory known
    not to be corpus", and every directory nobody has thought of yet answers
    no; asking where a cell is PUBLISHED answers for all of them at once.

    THE STANDING PROMISE IS UNCHANGED. `audit_corpus` promises a document that
    comes home to this repository does not stop being audited. It comes home to
    the corpus, which is what this resolves — asserted by
    `test_a_document_that_comes_home_is_audited_again`.

    NO ANCESTOR WALK. `_corpus_location.default_named` resolves the same path
    for a repository root, but it CLIMBS to find one, and climbing out of the
    tree that was named is the host-dependence vibe-ic#1710 exists to have
    removed. The equality below is the bounded form of the same question.

    ONE SEAM, BOTH SIDES. `audit_corpus` and `semantic_progress_units` both
    resolve through here, because a trusted parent computes its finite manifest
    with the second while the child does the work with the first: resolving in
    `main` instead — which I wrote first — makes the parent plan documents the
    child never opens, and that surfaces as a progress-protocol violation
    rather than as anything about the corpus.
    """
    tree = Path(tree).resolve()
    if _corpus_location.repo_root(tree) != tree:
        return tree                      # already a corpus; walk it as given
    return tree / _DEFAULT_CORPUS_REL    # a repository; audit what it publishes


def _iter_l4(root: Path) -> Iterable[Path]:
    """Walk the L4 documents on disk under `root`.

    The skip set is matched against the path RELATIVE TO ROOT, never against
    the absolute path. Matching absolutely is the bug this repo has already
    documented once: a checkout that itself lives under a skipped directory
    name matches every entry, the walk returns nothing, and an empty result
    reports as a clean one. Measured here — the first version found 0 of 201
    documents when run from inside a git worktree.

    `_TEST_DATA_DIR` is the one exclusion that IS absolute, and it is absolute
    for the same reason: it names this plugin's own `programs/tests/`, so it
    can never match a directory inside a corpus checkout. See its comment.
    """
    skip = {".git", "node_modules", ".claude", "worktrees", "__pycache__"}
    root = root.resolve()
    hits = []
    for p in root.rglob(_L4_GLOB):
        try:
            resolved = p.resolve()
            rel = resolved.relative_to(root)
        except ValueError:
            continue
        if any(part in skip for part in rel.parts):
            continue
        if resolved.is_relative_to(_TEST_DATA_DIR):
            continue
        hits.append(p)
    # The corpus is what the tree PUBLISHES, not what this machine has run.
    # 299 L4 documents on disk here vs 201 tracked; the docstring's own "0 of
    # 201" is a worktree count, which is why audit-corpus passed there and
    # fails in a working checkout. See `_published_tree` and `_l4_documents`,
    # which is where the tracked filter is now applied so the DROPPED count
    # survives to the report.
    yield from hits


def _progress_document_unit(path: Path, roots: Sequence[Path]) -> str:
    for index, root in enumerate(roots, 1):
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        return f"document:{index}:{rel}"
    raise ValueError(f"L4 progress document is outside every declared root: {path}")


def semantic_progress_units(root: Path,
                            extra_roots: Sequence[Path] = ()) -> List[str]:
    """Exact finite work manifest for a trusted audit-corpus parent."""
    roots: List[Path] = []
    for candidate in [corpus_root_of(root), *extra_roots]:
        candidate = candidate.resolve()
        if candidate not in roots:
            roots.append(candidate)
    units: List[str] = []
    files: List[Path] = []
    for index, candidate in enumerate(roots, 1):
        kept, _found, _published = _l4_documents(
            candidate, semantic_strict=True)
        units.append(f"root:{index}")
        files.extend(kept)
    for path in sorted(set(files)):
        units.extend(_semantic_progress.file_progress_units(
            path, _progress_document_unit(path, roots)))
    return units


def audit_corpus(root: Path,
                 extra_roots: Sequence[Path] = ()) -> Tuple[int, Dict[str, Any]]:
    """Is the disposition table still TOTAL over the published L4 corpus?

    `root` is a TREE, and the corpus it publishes is resolved from it by
    `corpus_root_of` — the repository is not the corpus.

    `extra_roots` is where a corpus that no longer lives in `root` is ADDED —
    $VIBE_IC_BENCHMARK_DATA after v1.10.56 moved the published cells out. Added,
    never swapped in: an L4 document that comes home to this repository must not
    stop being audited because a pointer is set.
    """
    roots: List[Path] = []
    for r in [corpus_root_of(root), *extra_roots]:
        r = r.resolve()
        if r not in roots:
            roots.append(r)

    files: List[Path] = []
    per_root: List[Dict[str, Any]] = []
    for index, r in enumerate(roots, 1):
        kept, found, is_published = _l4_documents(
            r, semantic_strict=(_ACTIVE_PROGRESS is not None
                                and _ACTIVE_PROGRESS.enabled))
        per_root.append({"root": str(r), "documents_on_disk": found,
                         "documents_published": len(kept),
                         "published_tree": is_published})
        files.extend(kept)
        _checkpoint(f"root:{index}")
    files = sorted(set(files))

    if not files:
        # WHY IT IS EMPTY IS THE CALLER'S DECISION, and it needs the numbers to
        # make it: "no L4 document anywhere" and "N on disk, none of them
        # tracked" are different facts and only the second is a defect in the
        # tree. `main` maps this to NO_CORPUS or UNDETERMINED; it is never a PASS.
        return 2, {"verdict": "NO_DOCUMENTS",
                   "reason": "no %s under %s" % (
                       _L4_GLOB, ", ".join(str(r) for r in roots)),
                   "roots": per_root,
                   "l4_documents_on_disk": sum(p["documents_on_disk"]
                                               for p in per_root),
                   "l4_documents_published": 0}
    def _rel(p: Path) -> str:
        """`p` relative to whichever root it came from — a document from the
        pointed-at corpus is not under `root`, and `relative_to` would raise."""
        for r in roots:
            try:
                return str(p.relative_to(r))
            except ValueError:
                continue
        return str(p)

    unclassified: Dict[str, Dict[str, Any]] = {}
    seen = {"register": set(), "field": set()}
    parsed = 0
    unreadable: List[str] = []
    for p in files:
        identity = _progress_document_unit(p, roots)
        try:
            text = _semantic_progress.read_text_chunks(
                p, identity, _ACTIVE_PROGRESS)
        except OSError:
            if (_ACTIVE_PROGRESS is not None
                    and _ACTIVE_PROGRESS.enabled):
                raise
            unreadable.append(_rel(p))
            continue
        try:
            d = json.loads(text)
        except Exception:
            unreadable.append(_rel(p))
            _checkpoint(_semantic_progress.file_judged_unit(p, identity))
            continue
        if not isinstance(d, dict):
            unreadable.append(_rel(p))
            _checkpoint(_semantic_progress.file_judged_unit(p, identity))
            continue
        parsed += 1
        for reg in d.get("registers") or []:
            if not isinstance(reg, dict):
                continue
            for k in reg.keys():
                seen["register"].add(k)
                if ("register", k) not in DISPOSITION:
                    unclassified.setdefault("register:%s" % k, {
                        "scope": "register", "key": k,
                        "first_seen": _rel(p)})
            for f in _reg_fields(reg):
                for k in f.keys():
                    seen["field"].add(k)
                    if ("field", k) not in DISPOSITION:
                        unclassified.setdefault("field:%s" % k, {
                            "scope": "field", "key": k,
                            "first_seen": _rel(p)})
        _checkpoint(_semantic_progress.file_judged_unit(p, identity))
    report = {
        "verdict": "FAIL" if unclassified else "PASS",
        "l4_documents_scanned": parsed,
        # THE POPULATION, beside what was read out of it. `l4_documents_scanned`
        # alone cannot distinguish an empty corpus from an unreadable one, and
        # this program's own history is exactly that confusion ("0 of 201 -> PASS").
        "l4_documents_published": len(files),
        "l4_documents_unreadable": len(unreadable),
        "unreadable": sorted(unreadable)[:20],
        "roots": per_root,
        "register_keys_seen": len(seen["register"]),
        "field_keys_seen": len(seen["field"]),
        "disposition_rows": len(DISPOSITION),
        "unclassified": sorted(unclassified.values(),
                               key=lambda r: (r["scope"], r["key"])),
    }
    if parsed == 0:
        # EVERY DOCUMENT FOUND, NONE OF THEM READ. Before this the loop simply
        # `continue`d past each one, `seen` stayed empty, nothing was
        # unclassified, and the program printed "[PASS] every register/field key
        # in the published corpus has a recorded disposition" over a corpus it
        # had not parsed a single byte of. An empty result is not a zero.
        report["verdict"] = "UNREADABLE"
        report["reason"] = (
            "%d published %s found and NONE of them parsed as a JSON object, "
            "so 0 register/field keys were examined. That is 'I could not read "
            "the corpus', not 'the disposition table covers it'."
            % (len(files), _L4_GLOB))
        return 2, report
    return (1 if unclassified else 0), report


# --------------------------------------------------------------------------
# gap table
# --------------------------------------------------------------------------
def gap_table() -> Dict[str, Any]:
    rows = []
    for (scope, key), (disp, target, note) in sorted(DISPOSITION.items()):
        rows.append({"scope": scope, "l4_key": key, "disposition": disp,
                     "systemrdl": target, "note": note})
    return {
        "standard": STANDARD,
        "direction_l4_to_systemrdl": rows,
        "direction_systemrdl_to_l4": [
            {"systemrdl_property": p, "component": c, "consequence": w}
            for p, c, w in SYSTEMRDL_NOT_SOURCED_BY_L4],
        "software_access_vocabulary_size": {
            "systemrdl_sw": len(_SW_LEGAL),
            "note": "SystemRDL `sw` is a CLOSED enumeration of %d values; L4's "
                    "`access` is an open string." % len(_SW_LEGAL),
        },
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _repo_root(start: Path) -> Path:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() or (p / "benchmark-data").is_dir():
            return p
    return start


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export", help="emit SystemRDL from one L4 document")
    e.add_argument("l4", type=Path)
    e.add_argument("--out", type=Path)
    e.add_argument("--ledger", type=Path)
    e.add_argument("--address-unit", choices=("byte", "word"), default="byte")
    e.add_argument("--roundtrip", action="store_true")
    e.add_argument("--strict-roundtrip", action="store_true",
                   help="exit 1 unless the round trip is CLEAN")
    e.add_argument("--workdir", type=Path)

    g = sub.add_parser("gap-table", help="both directions of the gap table")
    g.add_argument("--json", dest="json_out", type=Path)

    a = sub.add_parser("audit-corpus",
                       help="is the disposition table still TOTAL over the "
                            "published L4 corpus?")
    a.add_argument("--root", type=Path)
    a.add_argument("--json", dest="json_out", type=Path)
    a.add_argument("--corpus-may-be-absent", action="store_true",
                   help="the caller asserts this repo need not carry the "
                        "published corpus. Turns 'no L4 document anywhere' from "
                        "UNDETERMINED into NO_CORPUS (rc 0), which STATES that "
                        "nothing was scanned. It does NOT excuse a pointer that "
                        "is set and broken: $%s aimed at something unreadable, "
                        "or at a tree carrying no %s, stays UNDETERMINED."
                        % (_corpus_location.CORPUS_ENV, _L4_GLOB))

    args = ap.parse_args(argv)

    if args.cmd == "gap-table":
        rep = gap_table()
        if args.json_out:
            args.json_out.write_text(json.dumps(rep, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
        print("=== L4 -> %s gap table ===" % STANDARD)
        for r in rep["direction_l4_to_systemrdl"]:
            print("  %-9s %-38s %-10s %s"
                  % (r["scope"], r["l4_key"], r["disposition"], r["systemrdl"]))
        print("\n=== SystemRDL properties NO L4 key sources ===")
        for r in rep["direction_systemrdl_to_l4"]:
            print("  %-38s (%s)\n      %s"
                  % (r["systemrdl_property"], r["component"], r["consequence"]))
        return 0

    if args.cmd == "audit-corpus":
        root = args.root or _repo_root(Path(__file__).resolve())
        # What was ACTUALLY walked on the tree side, named in the messages
        # below: saying "no L4 document under <repo>" while having scanned
        # <repo>/benchmark-data/ic sends the reader to the wrong place.
        scanned = corpus_root_of(root)

        # THE CORPUS IS ADDED, NOT SWAPPED IN, AND THE POINTER IS ANNOUNCED
        # (#1710). All 199 tracked `L4_REGMAP.json` lived under `benchmark-data/`
        # and left with it in v1.10.56, so `--root <repo>` — what the CI call
        # site passes — now finds none and the gate refused on every landing.
        # `_corpus_location.resolve` cannot decide this one: it answers "the
        # NAMED path is missing, may I use the pointer instead?", and the named
        # path here is the repository, which always exists. So the pointer
        # supplies an ADDITIONAL root, and a document that comes home to this
        # repo keeps being audited.
        extra: List[Path] = []
        env_tree = _corpus_location.env_pointer()
        if env_tree:
            print("note: %s adds a corpus to audit -> %s"
                  % (_corpus_location.CORPUS_ENV, env_tree), file=sys.stderr)
            corpus = Path(env_tree)
            if not corpus.is_dir():
                # SET AND WRONG IS NOT ABSENT: a mistyped path, a failed clone
                # or a no-op CI fetch step must never come out green.
                print("UNDETERMINED: %s=%s is set and is not a readable "
                      "directory, so no L4 document was read there. A pointer "
                      "that is set and wrong is a broken configuration, not an "
                      "absent corpus, and --corpus-may-be-absent does not "
                      "excuse it." % (_corpus_location.CORPUS_ENV, env_tree),
                      file=sys.stderr)
                return 2
            extra.append(corpus)

        rc, rep = audit_corpus(root, extra)
        if args.json_out:
            args.json_out.write_text(json.dumps(rep, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
        if rep.get("verdict") == "NO_DOCUMENTS":
            on_disk = rep.get("l4_documents_on_disk", 0)
            if env_tree:
                # The pointer was SET and led somewhere carrying none of this
                # gate's subject. The opt-in must not reach that.
                print("UNDETERMINED: %s and %s=%s together carry no %s (%d found "
                      "on disk, %d of them published). A corpus that was NAMED "
                      "and carries none of this gate's subject is a wrong "
                      "pointer, not an absent one."
                      % (scanned, _corpus_location.CORPUS_ENV, env_tree,
                         _L4_GLOB, on_disk, 0), file=sys.stderr)
                return 2
            if args.corpus_may_be_absent:
                # rc 0, and it must never read as an audit that happened.
                print("NO_CORPUS: no %s under %s and %s is unset. The published "
                      "L4 corpus moved to its own repository in v1.10.56 and "
                      "this repo is not required to carry it. NOTHING WAS "
                      "SCANNED — 0 L4 document(s) parsed, 0 register/field "
                      "key(s) examined and the disposition table was NOT "
                      "exercised. Point %s at a clone to make this gate check "
                      "something."
                      % (_L4_GLOB, scanned, _corpus_location.CORPUS_ENV,
                         _corpus_location.CORPUS_ENV), file=sys.stderr)
                return 0
            print("[NOT CHECKED] %s — nothing was audited, which is not a clean "
                  "result. Point %s at a clone, or pass --corpus-may-be-absent "
                  "if this repo need not carry one."
                  % (rep["reason"], _corpus_location.CORPUS_ENV),
                  file=sys.stderr)
            return 2
        if rep.get("verdict") == "UNREADABLE":
            print("[NOT CHECKED] %s" % rep["reason"], file=sys.stderr)
            for u in rep.get("unreadable", [])[:10]:
                print("   unreadable: %s" % u, file=sys.stderr)
            return 2
        print("=== L4 -> SystemRDL disposition coverage ===")
        for r in rep.get("roots", []):
            print("  root %s: %d on disk, %d published%s"
                  % (r["root"], r["documents_on_disk"], r["documents_published"],
                     "" if r["published_tree"] else
                     "  (NOT a git checkout — the disk walk IS the answer here, "
                     "nothing has been published in it)"))
        print("  L4 documents scanned : %d of %d published (%d unreadable)"
              % (rep["l4_documents_scanned"], rep["l4_documents_published"],
                 rep["l4_documents_unreadable"]))
        print("  register keys seen   : %d" % rep["register_keys_seen"])
        print("  field keys seen      : %d" % rep["field_keys_seen"])
        print("  disposition rows     : %d" % rep["disposition_rows"])
        if rep["unclassified"]:
            print("\n[FAIL] %d L4 key(s) have NO recorded SystemRDL disposition."
                  % len(rep["unclassified"]))
            for u in rep["unclassified"]:
                print("   %-9s %-40s first seen: %s"
                      % (u["scope"], u["key"], u["first_seen"]))
            print("\n  REMEDY: add one row to DISPOSITION in %s stating what "
                  "SystemRDL can\n  say about this key — NATIVE / UDP / LOSSY / "
                  "DROPPED — and why. A key with\n  no row would otherwise be "
                  "dropped from every export in silence, which is\n  the exact "
                  "shape this gate exists to prevent." % Path(__file__).name)
            return 1
        print("\n[PASS] every register/field key in the published corpus has a "
              "recorded disposition.")
        return 0

    # ---- export ---------------------------------------------------------
    if not args.l4.is_file():
        print("[SKIP] no such L4 document: %s" % args.l4)
        return 2
    try:
        l4 = json.loads(args.l4.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        print("[SKIP] L4 is not readable JSON: %s" % exc)
        return 2
    if not isinstance(l4, dict):
        print("[SKIP] L4 root is not an object")
        return 2

    rdl, summary, ledger = export_rdl(l4, address_unit=args.address_unit,
                                      source_path=str(args.l4))
    if ledger.unclassified:
        print("[FAIL] %d L4 key(s) have NO recorded SystemRDL disposition:"
              % len(ledger.unclassified))
        for u in ledger.unclassified:
            print("   %-9s %-30s at %s" % (u["scope"], u["key"], u["path"]))
        print("  Add a row to DISPOSITION rather than letting the export drop "
              "it in silence.")
        return 1

    rt: Dict[str, Any] = {"verdict": "NOT_REQUESTED"}
    if args.roundtrip:
        wd = args.workdir or (args.out.parent if args.out
                              else Path.cwd()) / "_systemrdl_roundtrip"
        rt = roundtrip(rdl, l4_expectation(l4),
                       address_unit=args.address_unit, workdir=wd,
                       emitted_registers=summary["registers_emitted"])

    out_ledger = dict(summary)
    out_ledger["assumptions"] = ledger.assumptions
    out_ledger["findings"] = ledger.findings
    out_ledger["not_expressible_in_systemrdl"] = ledger.entries
    out_ledger["systemrdl_properties_not_sourced_from_l4"] = [
        {"systemrdl_property": p, "component": c, "consequence": w}
        for p, c, w in SYSTEMRDL_NOT_SOURCED_BY_L4]
    out_ledger["roundtrip"] = rt

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rdl, encoding="utf-8")
    else:
        print(rdl)
    if args.ledger:
        args.ledger.parent.mkdir(parents=True, exist_ok=True)
        args.ledger.write_text(
            json.dumps(out_ledger, indent=2, ensure_ascii=False), encoding="utf-8")

    print("── L4 -> %s" % STANDARD, file=sys.stderr)
    print("   registers %d/%d  fields %d"
          % (summary["registers_emitted"], summary["registers_in_l4"],
             summary["fields_emitted"]), file=sys.stderr)
    print("   DROPPED %d  LOSSY %d  UDP %d"
          % (summary["disposition_counts"][D_DROPPED],
             summary["disposition_counts"][D_LOSSY],
             summary["disposition_counts"][D_UDP]), file=sys.stderr)
    print("   roundtrip: %s" % rt["verdict"], file=sys.stderr)

    if args.strict_roundtrip and rt["verdict"] != "ROUNDTRIP_CLEAN":
        return 1
    return 0


def _entrypoint() -> int:
    global _ACTIVE_PROGRESS
    with _semantic_progress.child_progress(PROGRESS_SCOPE) as progress:
        _ACTIVE_PROGRESS = progress
        try:
            return main()
        finally:
            _ACTIVE_PROGRESS = None


if __name__ == "__main__":
    sys.exit(_entrypoint())
