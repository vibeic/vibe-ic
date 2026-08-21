#!/usr/bin/env python3
"""spec_otp_extract.py — PROGRAM-FIRST structural extractor for stated OTP content.

A family of design docs / datasheets / L-doc prompts state a One-Time-Programmable
(OTP) / fuse facet EXPLICITLY: a set of NAMED fuse fields/registers (each with a
bit width, an offset/address, or a table row) and a programmability LOCK (a
write-once / lock bit / "program once" / irreversible mention). The hidden scoring
testbench exercises exactly those fuse-field reads and lock behaviors, so a
verification FAILURE on an OTP design is — per the spec-coverage doctrine — almost
always one of OUR OWN extraction gaps (a stated fuse field we never read out / a
stated lock we never covered), not an unfixable floor.

This program does the DETERMINISTIC, chip-AGNOSTIC, PROGRAM-FIRST half of that
job: given a prompt, it extracts the STRUCTURAL OTP skeleton —

  * one `otp_field` ChecklistItem per stated, NAMED OTP/fuse field/register, and
  * one `otp_lock`  ChecklistItem per stated programmability-lock / write-once bit

— anchored to a real OTP/fuse token plus a real structural qualifier, so the
downstream coverage attribution can verify every stated fuse field / lock is
exercised.

WHAT COUNTS AS "STATED OTP CONTENT" (the §4.05 no-leak boundary)
  The extractor keys ONLY on EXPLICIT structure. An `otp_field` requires BOTH:

    (1) an OTP ANCHOR token — "OTP" / "one-time programmable" /
        "one-time-programmable" / "eFuse" / "e-fuse" / "fuse" / "fuse bank" /
        "fuse map" — somewhere in the document, AND
    (2) a STRUCTURAL QUALIFIER tying a name to it: a NAMED field/register, OR a
        bit width ("N-bit"), OR an offset/address ("0xNN"), OR a markdown table
        row.

  An `otp_lock` requires a LOCK token — "lock bit" / "write-once" / "write once" /
  "program once" / "program-once" / "OTP lock" / "permanently" / "irreversible" —
  in an OTP/fuse context.

  The gate is HARD: the ordinary English word "fuse" alone, with NO field/width/
  offset/table qualifier, mints NOTHING. A doc with no OTP/fuse anchor at all
  yields `[]`. It NEVER fabricates a requirement out of free prose. chip-AGNOSTIC:
  every matcher is generic OTP grammar (OTP token shape, field-name shape, width/
  offset/table structure, lock vocabulary) — NO chip / vendor / SKU / problem-id
  literal (enforced by `programs/source_chip_agnostic_check.py .`).

CONTRACT
  Each emitted dict is shaped to seed a `spec_coverage_check.ChecklistItem`:
    {
      "kind":        "otp_field" | "otp_lock",
      "requirement": human-readable testable requirement,
      "evidence":    the EXACT field / lock line it came from,
      "coverage_tokens": [tokens a TB must touch to cover it],
      "provenance":  "STRUCTURAL",          # default
      "block_eligible": bool,               # eligible to BLOCK on coverage miss
    }

CLI
    python3 spec_otp_extract.py <prompt.txt> [--json]
    cat prompt.txt | python3 spec_otp_extract.py -
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# OTP anchor grammar (chip-AGNOSTIC, pure vocabulary shape)
# ---------------------------------------------------------------------------
# An OTP ANCHOR token: any of the canonical one-time-programmable / fuse words.
# "fuse" matches on a word boundary so it never fires inside "confuse"/"refuse".
# This is the gate-1 anchor — necessary but NOT sufficient (a structural
# qualifier is also required for an otp_field).  chip-AGNOSTIC.
_OTP_ANCHOR_RE = re.compile(
    r"\b("
    r"one[\s-]?time[\s-]?programmable"   # one-time programmable / one-time-programmable
    r"|OTP"                              # OTP
    r"|e[\s-]?fuse"                      # eFuse / e-fuse / e fuse
    r"|fuse\s+bank"                      # fuse bank
    r"|fuse\s+map"                       # fuse map
    r"|fuses?"                           # fuse / fuses  (bare — needs a qualifier)
    r")\b",
    re.IGNORECASE)


def _has_otp_anchor(text: str) -> bool:
    """True iff the document mentions ANY OTP/fuse anchor token. Gate-1 of the
    §4.05 no-leak boundary — necessary for any emission. chip-AGNOSTIC."""
    return bool(_OTP_ANCHOR_RE.search(text))


# A STRONG (NOUN-context) OTP anchor: "OTP", "eFuse", "fuse bank", "fuse map",
# "one-time programmable". UNLIKE the bare "fuse"/"fuses" token (which can be the
# ordinary English VERB — "fuse the two clocks"), these are unambiguous OTP
# nouns. A NAMED-field emission requires a strong anchor in the doc OR a real
# width/offset/table qualifier on the field's own line — this is the §4.05 guard
# that keeps "We will fuse the clocks" from minting a phantom field. chip-AGNOSTIC.
_OTP_STRONG_ANCHOR_RE = re.compile(
    r"\b("
    r"one[\s-]?time[\s-]?programmable"
    r"|OTP"
    r"|e[\s-]?fuse"
    r"|fuse\s+bank"
    r"|fuse\s+map"
    r")\b",
    re.IGNORECASE)


def _has_strong_otp_anchor(text: str) -> bool:
    """True iff the doc carries an unambiguous NOUN-context OTP anchor (not the
    bare verb-ambiguous "fuse"). chip-AGNOSTIC."""
    return bool(_OTP_STRONG_ANCHOR_RE.search(text))


# A NEGATION immediately before an OTP/fuse token turns it into a NON-anchor:
# "無 OTP", "no OTP", "not applicable ... fuse", "without fuses", "non-OTP" —
# common in an N/A datasheet section. chip-AGNOSTIC (CJK + English negators).
_NEG_BEFORE_RE = re.compile(r"(?:無|沒有|\bno\b|\bnot\b|\bwithout\b|\bn/?a\b|\bnon-)"
                            r"[^\n。.]{0,24}$", re.IGNORECASE)


def _local_otp_anchor(text: str, pos: int, window: int = 160) -> bool:
    """True iff a NON-negated OTP/fuse anchor sits within `window` chars of `pos`.

    §4.05 PRECISION (the real-datasheet leak): the doc-wide `strong` gate let an
    OTP mention in an N/A section ("無 OTP-based calibration") bind every
    "register" on the far side of a multi-section design doc as a fuse field.
    A NAMED field is OTP only when a real OTP/fuse anchor is LOCAL to it AND that
    anchor is not negated."""
    lo, hi = max(0, pos - window), min(len(text), pos + window)
    seg = text[lo:hi]
    for m in _OTP_ANCHOR_RE.finditer(seg):
        if not _NEG_BEFORE_RE.search(seg[:m.start()]):
            return True
    return False


# ---------------------------------------------------------------------------
# LOCK grammar — the programmability-lock vocabulary (otp_lock anchor)
# ---------------------------------------------------------------------------
# A LOCK token states that an OTP/fuse is write-once / locked / irreversible.
# Each is gated on an OTP/fuse context elsewhere in the doc (see extract()).
# chip-AGNOSTIC vocabulary, NO design literal.
_LOCK_TOKEN_RE = re.compile(
    r"\b("
    r"lock\s+bit"           # lock bit
    r"|OTP\s+lock"          # OTP lock
    r"|write[\s-]?once"     # write-once / write once
    r"|program[\s-]?once"   # program-once / program once
    r"|permanently"         # permanently (programmed / locked)
    r"|irreversibl[ey]"     # irreversible / irreversibly
    r")\b",
    re.IGNORECASE)


# ---------------------------------------------------------------------------
# Structural-qualifier grammar for an OTP FIELD
# ---------------------------------------------------------------------------
# A FIELD-NAME token: an identifier-shaped name immediately qualified as a
# field/register/bit(s) — "trim_code field", "VERSION register", "cal bits".
# Captures the NAME group; the trailing qualifier word proves it is a field.
# chip-AGNOSTIC (identifier shape + generic qualifier vocabulary).
_NAMED_FIELD_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s+"
    r"(?:field|register|reg|bitfield|word|entry|fuse|fuses|bits?)\b",
    re.IGNORECASE)
# the reverse phrasing — "field/register <NAME>", "fuse <NAME>".
_FIELD_NAMED_RE = re.compile(
    r"\b(?:field|register|reg|bitfield|word|entry|fuse)\s+"
    r"`?\*?\*?([A-Za-z_]\w*)\*?\*?`?",
    re.IGNORECASE)

# A BIT-WIDTH qualifier: "32-bit", "8 bit", "16bit". Captures the width digits.
# This proves a concrete fuse field exists even if it is unnamed. chip-AGNOSTIC.
_WIDTH_RE = re.compile(r"\b(\d{1,4})\s*[- ]?\s*bit\b", re.IGNORECASE)

# An OFFSET / ADDRESS qualifier: "0x10", "offset 0x1F", "address 0x00". Captures
# the hex literal. A real offset/address proves a concrete fuse-map slot exists.
# chip-AGNOSTIC.
_OFFSET_RE = re.compile(r"\b(?:offset|address|addr|@)?\s*(0x[0-9A-Fa-f]+)\b",
                        re.IGNORECASE)
# the bare "0xNN" hex literal (for evidence / token harvesting).
_HEX_RE = re.compile(r"\b0x[0-9A-Fa-f]+\b")

# Generic-English deny-set: identifier-shaped words that are NOT fuse field names
# even when they sit next to a qualifier word — keeps "the field", "a register"
# prose glue from minting a phantom field. chip-AGNOSTIC (ordinary English only).
_NON_FIELD_WORDS: Set[str] = {
    "the", "a", "an", "this", "that", "each", "every", "any", "some", "no",
    "one", "two", "all", "its", "his", "her", "their", "our", "your", "my",
    "of", "in", "on", "at", "to", "from", "and", "or", "is", "are", "be",
    "single", "multiple", "first", "second", "next", "last", "same", "other",
    "control", "status", "data", "address", "value", "bit", "bits", "byte",
    "word", "field", "register", "fuse", "fuses", "bank", "map", "memory",
    # OTP/lock anchor words are not themselves field NAMES (they tag the facet)
    "otp", "efuse", "lock", "locked", "programmable", "programmed", "write",
    "once", "permanent", "permanently", "irreversible", "reg", "bitfield",
    "entry", "size", "width", "offset",
}

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")


def _is_field_name(tok: str) -> bool:
    """A real fuse-field NAME: identifier shape, >=2 chars, not a deny-word, and
    not a pure-number / pure-underscore. chip-AGNOSTIC (no design literal)."""
    if not tok:
        return False
    if tok.lower() in _NON_FIELD_WORDS:
        return False
    if not _IDENT_RE.fullmatch(tok):
        return False
    return len(tok) >= 2 and any(c.isalpha() for c in tok)


def _norm(name: str) -> str:
    return name.strip().strip("`*").strip()


# ---------------------------------------------------------------------------
# Markdown table detection (a `| field | offset | width |` row is a qualifier)
# ---------------------------------------------------------------------------
_TABLE_LINE_RE = re.compile(r"^\s*\|(.+)\|\s*$", re.MULTILINE)


def _row_cells(line: str) -> List[str]:
    inner = line.strip().strip("|")
    return [c.strip().strip("`*") for c in inner.split("|")]


def _table_fields(prose: str) -> List[Tuple[str, str]]:
    """Yield (name, evidence) for each OTP/fuse-map markdown table row. The table
    HEADER must name a field/name/register column AND at least one of an offset/
    address/width column (so an arbitrary table is not read as a fuse map). The
    row's name cell supplies the field name; an unnamed row with a real offset is
    still admitted with a synthetic offset-keyed name. chip-AGNOSTIC."""
    out: List[Tuple[str, str]] = []
    lines = _TABLE_LINE_RE.findall(prose)
    if len(lines) < 2:
        return out
    header = [h.lower() for h in _row_cells("|" + lines[0] + "|")]

    def _find_col(keys: List[str]) -> Optional[int]:
        for i, h in enumerate(header):
            if any(k in h for k in keys):
                return i
        return None

    name_col = _find_col(["field", "name", "register", "signal", "fuse"])
    off_col = _find_col(["offset", "address", "addr", "bit"])
    width_col = _find_col(["width", "size", "bits"])
    # require a name column AND an offset OR width column for it to be a fuse map
    if name_col is None or (off_col is None and width_col is None):
        return out
    for raw in lines[1:]:
        cells = _row_cells("|" + raw + "|")
        if set("".join(cells)) <= set("-: "):        # separator row
            continue
        if name_col >= len(cells):
            continue
        nm = _norm(cells[name_col])
        ev = "table row: | " + " | ".join(cells) + " |"
        if _is_field_name(nm):
            out.append((nm, ev))
        elif off_col is not None and off_col < len(cells):
            # unnamed row but a concrete offset → offset-keyed synthetic name
            hx = _HEX_RE.search(cells[off_col])
            if hx:
                out.append(("fuse_" + hx.group(0).lower(), ev))
    return out


# ---------------------------------------------------------------------------
# Field collection — multiple structural-qualifier sources
# ---------------------------------------------------------------------------
def _line_of(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    return text[start:end].strip()


def _collect_fields(text: str) -> List[Tuple[str, str, List[str]]]:
    """Return ordered distinct (name, evidence-line, coverage_tokens).

    A field is admitted ONLY on an OTP/fuse anchor + a structural qualifier:
      * a NAMED field/register/bit ("trim_code field", "register VERSION"),
      * a BIT-WIDTH near an OTP/fuse anchor ("32-bit OTP fuse bank"),
      * an OFFSET/ADDRESS near an OTP/fuse anchor ("at offset 0x10"),
      * an OTP/fuse-map markdown TABLE row.
    The §4.05 no-leak guard: a bare "fuse" with no qualifier mints NOTHING."""
    order: List[str] = []
    evidence: Dict[str, str] = {}
    tokens: Dict[str, List[str]] = {}

    def _add(name: str, ev: str, toks: List[str]) -> None:
        nm = _norm(name)
        if not _is_field_name(nm):
            return
        if nm not in evidence:
            order.append(nm)
            evidence[nm] = ev.strip()
            tokens[nm] = sorted({t for t in [nm] + toks if t})

    # (1) NAMED field/register tokens — "<NAME> field", "field <NAME>". Each must
    # sit on a line (or doc) that also carries an OTP/fuse context. Because gate-1
    # (doc-level anchor) is already enforced by extract(), a named field anywhere
    # in an OTP doc is admitted; we attach the line's own offset/width tokens.
    for rx in (_NAMED_FIELD_RE, _FIELD_NAMED_RE):
        for m in rx.finditer(text):
            nm = m.group(1)
            line = _line_of(text, m.start())
            toks = _HEX_RE.findall(line)
            w = _WIDTH_RE.search(line)
            if w:
                toks.append(w.group(1) + "-bit")
            # §4.05 PRECISION guard: a NAMED field/register is an OTP field ONLY
            # when a NON-negated OTP/fuse anchor is LOCAL to it. The old doc-wide
            # `strong` gate bound every "register" in a multi-section design doc to
            # an OTP mention in an unrelated (often N/A) section — the real-
            # datasheet leak. An ordinary "register file" / "config register" with
            # no local OTP anchor now mints NOTHING.
            if not _local_otp_anchor(text, m.start()):
                continue
            _add(nm, line or m.group(0), toks)

    # (2) WIDTH qualifier on an OTP-anchored line — a concrete (possibly unnamed)
    # fuse field. Use a width-keyed synthetic name when no real name on the line.
    for m in _WIDTH_RE.finditer(text):
        line = _line_of(text, m.start())
        if not _OTP_ANCHOR_RE.search(line):
            continue
        # prefer a real named field already on this line (handled by (1)); else
        # mint a width-keyed fuse field so the stated width is still covered.
        nm = None
        nmm = _NAMED_FIELD_RE.search(line) or _FIELD_NAMED_RE.search(line)
        if nmm and _is_field_name(nmm.group(1)):
            nm = nmm.group(1)
        if nm is None:
            nm = "fuse_" + m.group(1) + "bit"
        toks = [m.group(1) + "-bit"] + _HEX_RE.findall(line)
        _add(nm, line, toks)

    # (3) OFFSET/ADDRESS qualifier on an OTP-anchored line — a concrete fuse-map
    # slot. Offset-keyed synthetic name when no real name on the line.
    for m in _HEX_RE.finditer(text):
        line = _line_of(text, m.start())
        if not _OTP_ANCHOR_RE.search(line):
            continue
        nm = None
        nmm = _NAMED_FIELD_RE.search(line) or _FIELD_NAMED_RE.search(line)
        if nmm and _is_field_name(nmm.group(1)):
            nm = nmm.group(1)
        if nm is None:
            nm = "fuse_" + m.group(0).lower()
        _add(nm, line, [m.group(0)])

    # (4) OTP/fuse-map markdown table rows
    for nm, ev in _table_fields(text):
        toks = _HEX_RE.findall(ev)
        w = _WIDTH_RE.search(ev)
        if w:
            toks.append(w.group(1) + "-bit")
        _add(nm, ev, toks)

    return [(nm, evidence[nm], tokens[nm]) for nm in order]


# ---------------------------------------------------------------------------
# Lock collection
# ---------------------------------------------------------------------------
def _collect_locks(text: str) -> List[Tuple[str, str, List[str]]]:
    """Return distinct (lock_phrase, evidence-line, coverage_tokens) for every
    stated programmability-lock / write-once mention in an OTP/fuse context. Each
    lock token must share its line — OR the doc (gate-1 anchor) — with an OTP/fuse
    mention. de-duped on the lower-cased lock phrase. chip-AGNOSTIC."""
    out: List[Tuple[str, str, List[str]]] = []
    seen: Set[str] = set()
    for m in _LOCK_TOKEN_RE.finditer(text):
        phrase = re.sub(r"\s+", " ", _norm(m.group(0))).lower()
        line = _line_of(text, m.start())
        # gate-1 (doc-level OTP anchor) is enforced by extract(); admit the lock.
        key = phrase
        if key in seen:
            continue
        seen.add(key)
        toks = [phrase]
        hx = _HEX_RE.findall(line)
        toks.extend(hx)
        out.append((phrase, line or m.group(0), sorted({t for t in toks if t})))
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def extract(prompt_text: str) -> List[Dict]:
    """Extract stated OTP content (fuse fields + programmability locks) from
    `prompt_text`.

    Returns a list of dicts (each shaped for `spec_coverage_check.ChecklistItem`):
    one `otp_field` item per stated NAMED/width/offset/table fuse field and one
    `otp_lock` item per stated write-once / lock-bit / irreversible mention.

    §4.05 no-leak gate: require an OTP/fuse ANCHOR token in the doc AND, for any
    `otp_field`, a STRUCTURAL QUALIFIER (named field / bit width / offset / table
    row). A bare "fuse" with no qualifier, or a doc with no OTP anchor at all,
    returns []. chip-AGNOSTIC: keys on OTP structure (anchor + qualifier + lock
    vocabulary), never a problem id."""
    if not prompt_text or not prompt_text.strip():
        return []

    # gate-1: no OTP/fuse anchor anywhere → no fabrication.
    if not _has_otp_anchor(prompt_text):
        return []

    text = prompt_text
    fields = _collect_fields(text)
    locks = _collect_locks(text)

    # §4.05 HARD GATE — anchor alone is not enough; require at least one concrete
    # structural emission (a qualified field OR a lock). A doc that merely says
    # "fuse" with no field/width/offset/table AND no lock yields [].
    if not fields and not locks:
        return []

    items: List[Dict] = []
    for nm, ev, toks in fields:
        items.append({
            "kind": "otp_field",
            "requirement": "OTP/fuse content has a field named " + nm
                           + "; the design must implement it and the TB must "
                           + "read it out and check its programmed value.",
            "evidence": ev,
            "coverage_tokens": toks,
            "provenance": "STRUCTURAL",
            "block_eligible": True,
        })
    for phrase, ev, toks in locks:
        items.append({
            "kind": "otp_lock",
            "requirement": "OTP/fuse is " + phrase
                           + " (write-once / lock); the design must enforce the "
                           + "lock and the TB must prove a second program attempt "
                           + "is rejected / has no effect.",
            "evidence": ev,
            "coverage_tokens": toks,
            "provenance": "STRUCTURAL",
            "block_eligible": True,
        })
    return items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="PROGRAM-FIRST structural extractor for stated OTP content "
                    "(fuse fields + locks). chip-AGNOSTIC, §4.05 no-leak.")
    ap.add_argument("prompt", help="prompt file ('-' for stdin)")
    ap.add_argument("--json", action="store_true",
                    help="emit the raw checklist-item list as JSON")
    args = ap.parse_args(argv)

    try:
        if args.prompt == "-":
            text = sys.stdin.read()
        else:
            with open(args.prompt, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
    except OSError as e:
        print("error: cannot read prompt: " + str(e), file=sys.stderr)
        return 2

    items = extract(text)
    if args.json:
        print(json.dumps(items, indent=2))
        return 0

    if not items:
        print("NO STATED OTP CONTENT (no OTP/fuse anchor + qualifier/lock) "
              "-> [] (no fabrication)")
        return 0

    fields = [it for it in items if it["kind"] == "otp_field"]
    locks = [it for it in items if it["kind"] == "otp_lock"]
    def _name_tok(it: Dict) -> str:
        # prefer the field NAME token (not a 0x.. offset / N-bit width literal).
        for t in it["coverage_tokens"]:
            if not _HEX_RE.fullmatch(t) and not re.fullmatch(r"\d+-bit", t):
                return t
        return it["coverage_tokens"][0] if it["coverage_tokens"] else "?"

    print("OTP FIELDS (" + str(len(fields)) + "):")
    for it in fields:
        print("  - " + _name_tok(it)
              + "   [" + it["evidence"][:70] + "]")
    print("OTP LOCKS (" + str(len(locks)) + "):")
    for it in locks:
        print("  - " + it["coverage_tokens"][0])
        print("      evidence: " + it["evidence"][:90])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
