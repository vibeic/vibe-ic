#!/usr/bin/env python3
"""
l4_regmap_enumerated_values_typed_check.py — Wave 38 / B3

Audit item (PHASE2A_FULL_AUDIT_v0119.67.md, line 67): vendor
register tables routinely encode multi-state fields like 4-state
debounce filter (``OCP_DLY[1:0]``) or filter-mode selectors
(``RES_DLY[1:0]``) with a per-bit-pattern -> meaning mapping.
spec-to-rtl needs the typed enum to instantiate a valid filter
state machine; without it the field collapses to a numeric value
with no interpretation.

Trigger: L4_REGMAP.json has any register with a ``fields[]`` list
where at least one field has multi-bit width (>=2 bits) AND the
field's name suggests an enumerated meaning (matches keywords
``DLY``, ``MODE``, ``SEL``, ``CFG``, ``CTRL``, ``FILTER``,
``DEBOUNCE``, ``GAIN``, ``RANGE``, ``CLK``, ``DIV``, ``TRIM``,
``OPT``, ``STATE``).

Required typed shape: each such field MUST have an
``enumerated_values`` array (or ``enum``, ``encoding``,
``values``, ``state_table``) with at least 2 entries, each entry
being a dict with ``code`` (e.g. ``2'b00`` / ``0`` / ``"00"``) +
``meaning`` (free string) + optional ``evidence``.

The gate is chip-AGNOSTIC: it only checks shape; the bit width
threshold and field-name keyword list are protocol-/IC-class
generic.

BLOCKS (exit 1) — an un-enumerated selector field silently collapses
to an opaque numeric in every downstream consumer, and no later step
can tell the difference between "this field has no meanings" and
"the meanings were never captured". Blocking is the only way that
distinction survives.

Layer-gate strengthening (batch: layergate-2)
=============================================
Three defects were measured in the original shape and are fixed here.
All three are instances of the same principle:

    A layer is complete when the requirement is present IN THE LAYER
    THAT CONSUMES IT, in an ACTIONABLE FORM — not when a token appears
    somewhere.

S1. VACUITY (the gate could not fail on production data). The field
    name was looked up as ``name``/``field``/``bit_field`` only, but
    the Phase-1 L4 emitter writes it as ``field_name``. On a real
    80-register Phase-1 output the gate collected 84 fields, resolved
    every name to ``""``, matched the keyword regex zero times and
    reported ``[SKIP] no multi-bit enum-eligible fields detected`` —
    including for a 2-bit ``MODE`` selector whose own description
    declares a code binding. A gate that cannot fire on the emitter's
    actual output proves nothing. ``field_name`` and the other real
    aliases are now resolved.

S2. TOKEN-PRESENCE ``_has_enum``. The old test accepted ANY list or
    dict with >= 2 members, so ``enumerated_values: ["a", "b"]`` — two
    bare strings with no code and no meaning — passed. The consumer
    needs a code -> meaning BINDING to build a decoder; a list of
    tokens is not one. Entries must now bind a code to a meaning.

S3. HARDCODED CARDINALITY forced fabrication. The flat ">= 2 entries"
    rule is wrong whenever the design's own input declares exactly one
    legal code (e.g. a description stating "always set to 2'b01"):
    satisfying the gate would require INVENTING a second code. The
    requirement is now DERIVED from the field's own text — count the
    distinct code literals the field itself declares, and require the
    enum to capture at least that many. The flat >= 2 rule is retained
    only for the keyword-triggered case where the field declares no
    codes at all and there is nothing to derive from.

Usage:
    python3 l4_regmap_enumerated_values_typed_check.py <project_dir>

Exit codes:
    0 = PASS (no enum-eligible fields OR each has typed enum)
    1 = FAIL (enum-eligible fields exist but lack enumerated_values)
    2 = input-missing (skip)

Honors waiver ``l4_regmap_enum_intentional_simplification`` (>=40
chars).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402


# Wave 43 (v0.119.75) — explicit ic_class_profile guard.
# L4 regmap with enumerated multi-bit fields is mandatory for digital
# command-driven ICs (UART / SPI / I2C / AID-class). Pure-analog
# parts have no command register file; bare-FPGA scaffolds have no
# fab-side regmap to characterise.
_SKIP_CLASSES = ("pure_analog", "bare_fpga")


_L4_GLOBS = (
    "phase1/generated_docs/L4_REGMAP.json",
    "phase1/generated_docs/L4*.json",
    "**/L4_REGMAP.json",
)

_REG_KEYS = ("registers", "regmap", "register_table", "regs")

# The docstring has promised this waiver since Wave 38 but no code ever
# read it — a documented escape hatch that did not exist. Implemented
# here so the promise and the behaviour agree.
WAIVER_KEY = "l4_regmap_enum_intentional_simplification"
WAIVER_MIN_LEN = 40


def _waived(project: Path) -> Tuple[bool, str]:
    p = project / "waivers.json"
    if not p.is_file():
        return False, ""
    try:
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return False, ""
    raw = d.get(WAIVER_KEY)
    if isinstance(raw, str) and len(raw.strip()) >= WAIVER_MIN_LEN:
        return True, raw.strip()
    if isinstance(raw, dict):
        r = raw.get("rationale") or raw.get("reason") or ""
        if isinstance(r, str) and len(r.strip()) >= WAIVER_MIN_LEN:
            return True, r.strip()
    return False, ""

_ENUM_KEYS = ("enumerated_values", "enum", "encoding", "values",
              "state_table", "value_map", "encodings", "bit_pattern_table")

_ENUM_NAME_KEYWORDS = re.compile(
    r"(?:^|[^A-Za-z0-9])"
    r"(DLY|MODE|SEL|CFG|CTRL|FILTER|DEBOUNCE|GAIN|RANGE|"
    r"DIV|TRIM|OPT|STATE|TEST|FUNC|TYP)"
    r"(?:[^A-Za-z0-9]|$)",
    re.IGNORECASE,
)

# S1 — every key the Phase-1 L4 emitters actually use for a field's
# name. ``field_name`` is what the production rst/asciidoc register
# walkers write; omitting it made this gate vacuous on real output.
_FIELD_NAME_KEYS = ("name", "field", "bit_field", "field_name",
                    "bit_field_name", "fieldname")

# Free-text keys carrying the field's own documentation. S3 derives the
# required enum cardinality from these — the design's own input — so the
# gate can never demand a code the input does not declare.
_FIELD_TEXT_KEYS = ("description", "meaning", "notes", "note", "comment",
                    "detail", "details", "evidence", "doc")

# A literal code binding as vendor docs write it. Value-shaped and
# radix-explicit so ordinary prose numbers are not mistaken for codes.
_CODE_LITERAL_RE = re.compile(
    r"""(?:
        \b\d+'[bBhHdDoO][0-9a-fA-FxXzZ_]+      # 2'b01, 4'hF
      | \b0[xX][0-9a-fA-F]+\b                   # 0x3
      | \b0[bB][01_]+\b                         # 0b01
      | (?<![\w'])[01]{2,8}(?=\s*(?:=|:|->|=>|—|--)\s*\S)  # 00 = idle
    )""",
    re.VERBOSE,
)

# Keys an enum entry may use for the two halves of a code -> meaning
# binding. S2 requires BOTH halves; a bare token list is not a binding.
_ENTRY_CODE_KEYS = ("code", "value", "encoding", "bits", "pattern",
                    "bit_pattern", "key", "val", "code_value")
_ENTRY_MEANING_KEYS = ("meaning", "description", "name", "label",
                       "state", "text", "definition", "desc", "semantics")


def _find_l4(project: Path) -> Optional[Path]:
    for pat in _L4_GLOBS:
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _bit_width(field: dict) -> int:
    bits = field.get("bits") or field.get("bit_range") or field.get("range")
    if isinstance(bits, str):
        m = re.search(r"\[?(\d+)\s*[:\-]\s*(\d+)\]?", bits)
        if m:
            hi, lo = int(m.group(1)), int(m.group(2))
            return abs(hi - lo) + 1
        if bits.isdigit():
            return 1
    if isinstance(bits, list) and len(bits) == 2:
        try:
            return abs(int(bits[0]) - int(bits[1])) + 1
        except Exception:
            return 0
    width = field.get("width")
    if isinstance(width, int):
        return width
    if isinstance(width, str) and width.isdigit():
        return int(width)
    return 0


def _collect_register_fields(node,
                              out: List[Tuple[str, dict]]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _REG_KEYS and isinstance(v, list):
                for reg in v:
                    if not isinstance(reg, dict):
                        continue
                    reg_name = (reg.get("name")
                                or reg.get("register")
                                or reg.get("address") or "REG?")
                    fields = (reg.get("fields") or reg.get("bit_fields")
                              or reg.get("subfields") or [])
                    if isinstance(fields, list):
                        for f in fields:
                            if isinstance(f, dict):
                                out.append((str(reg_name), f))
            else:
                _collect_register_fields(v, out)
    elif isinstance(node, list):
        for it in node:
            _collect_register_fields(it, out)


def _field_name(field: dict) -> str:
    """S1 — resolve the field's name across every key the real emitters
    use. Without ``field_name`` this gate is vacuous on production L4."""
    for k in _FIELD_NAME_KEYS:
        v = field.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _field_text(field: dict) -> str:
    """The field's own documentation text, from the design's own input."""
    parts = []
    for k in _FIELD_TEXT_KEYS:
        v = field.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v)
        elif isinstance(v, dict):
            for vv in v.values():
                if isinstance(vv, str) and vv.strip():
                    parts.append(vv)
    return " ".join(parts)


def _declared_codes(field: dict) -> List[str]:
    """S3 — distinct code literals the FIELD ITSELF declares.

    Derived from the design's own input text, never from a hardcoded
    expectation. The gate requires the enum to capture at least this
    many codes, so it can never force the invention of a code the
    input does not state."""
    text = _field_text(field)
    if not text:
        return []
    seen: List[str] = []
    for m in _CODE_LITERAL_RE.findall(text):
        tok = str(m).strip()
        if tok and tok not in seen:
            seen.append(tok)
    return seen


def _binding_entries(field: dict) -> int:
    """S2 — count enum entries that actually BIND a code to a meaning.

    A decoder cannot be built from a bare token list: the emitter needs
    to know which bit pattern means what. ``["a", "b"]`` used to pass;
    it no longer does."""
    best = 0
    for k in _ENUM_KEYS:
        v = field.get(k)
        n = 0
        if isinstance(v, list):
            for e in v:
                if not isinstance(e, dict):
                    continue
                has_code = any(
                    e.get(ck) is not None and str(e.get(ck)).strip() != ""
                    for ck in _ENTRY_CODE_KEYS)
                has_meaning = any(
                    isinstance(e.get(mk), str) and e.get(mk).strip()
                    for mk in _ENTRY_MEANING_KEYS)
                if has_code and has_meaning:
                    n += 1
        elif isinstance(v, dict):
            # Mapping form: {"00": "idle", "01": "wait"} — the key is
            # the code, the value the meaning.
            for ck, mv in v.items():
                if str(ck).strip() and isinstance(mv, str) and mv.strip():
                    n += 1
        best = max(best, n)
    return best


def _has_enum(field: dict, required: int = 2) -> bool:
    """True when the field carries at least ``required`` code -> meaning
    bindings in any of the accepted enum keys."""
    return _binding_entries(field) >= max(1, required)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: l4_regmap_enumerated_values_typed_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    profile = detect_ic_class(project)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class in _SKIP_CLASSES:
        print(f"[SKIP] l4_regmap_enumerated_values_typed_check: "
              f"ic_class={ic_class} (no command-driven regmap for "
              f"this IC class; gate not applicable)")
        return 2

    l4 = _find_l4(project)
    if l4 is None:
        print("[SKIP] l4_regmap_enumerated_values_typed_check: "
              "L4_REGMAP.json not found")
        return 2

    try:
        data = json.loads(l4.read_text())
    except Exception as exc:
        print(f"[FAIL] l4_regmap_enumerated_values_typed_check: "
              f"cannot parse {l4.relative_to(project)}: {exc}")
        return 1

    pairs: List[Tuple[str, dict]] = []
    _collect_register_fields(data, pairs)

    if not pairs:
        print("[SKIP] l4_regmap_enumerated_values_typed_check: "
              "no registers[]/fields[] in L4 (gate not applicable)")
        return 2

    eligible: List[Tuple[str, str]] = []
    missing: List[str] = []
    for reg_name, field in pairs:
        fname = _field_name(field)          # S1 — includes `field_name`
        width = _bit_width(field)
        if width < 2:
            continue

        codes = _declared_codes(field)      # S3 — from the field's own text
        by_name = bool(_ENUM_NAME_KEYWORDS.search(fname or ""))
        if not (by_name or codes):
            continue

        # Required cardinality is DERIVED whenever the field declares
        # codes; only a keyword-triggered field that declares none falls
        # back to the flat >= 2 rule. This is what stops the gate from
        # ever demanding a code the input does not state.
        required = len(codes) if codes else 2
        eligible.append((reg_name, fname))
        have = _binding_entries(field)      # S2 — code -> meaning bindings
        if have < required:
            why = (f"declares {len(codes)} code literal(s) "
                   f"{codes[:4]} in its own description"
                   if codes else "is a multi-bit selector by name")
            missing.append(
                f"{reg_name}.{fname or '<unnamed>'} (width={width}) — "
                f"{why}, but L4 carries {have} code->meaning binding(s) "
                f"(need {required})")

    if not eligible:
        print("[SKIP] l4_regmap_enumerated_values_typed_check: "
              "no multi-bit enum-eligible fields detected")
        return 2

    if missing:
        waived, rationale = _waived(project)
        if waived:
            print("[PASS] l4_regmap_enumerated_values_typed_check: "
                  f"waived by waivers.{WAIVER_KEY} "
                  f"({len(missing)} suppressed): {rationale[:70]}…")
            for msg in missing[:5]:
                print(f"  • {msg}")
            return 0
        print(f"[FAIL] l4_regmap_enumerated_values_typed_check: "
              f"{len(missing)}/{len(eligible)} multi-bit enum-eligible "
              f"fields lack an actionable enumerated_values[] "
              f"(code -> meaning bindings). Without it the register-block "
              f"emitter collapses the field to an opaque numeric and "
              f"cannot instantiate the decoder the spec describes.")
        for msg in missing[:6]:
            print(f"  • {msg}")
        print()
        print("  Capture ONLY the codes the input already states:")
        print('    "enumerated_values": [{"code": "2\'b01", '
              '"meaning": "<what the doc says it means>"}]')
        print(f"  Or document the alternative in waivers.json under "
              f'"{WAIVER_KEY}" (>={WAIVER_MIN_LEN} chars).')
        return 1

    print(f"[PASS] l4_regmap_enumerated_values_typed_check: "
          f"{len(eligible)} multi-bit enum-eligible fields all carry "
          f"typed code->meaning enumerated_values")
    return 0


if __name__ == "__main__":
    sys.exit(main())
