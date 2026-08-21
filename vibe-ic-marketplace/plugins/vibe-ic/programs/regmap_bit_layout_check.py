#!/usr/bin/env python3
"""
regmap_bit_layout_check.py — gate that catches L4_REGMAP.json registers
that don't specify explicit bit positions for their fields.

Why this gate exists
====================
A common Category-A residual: regmap-gen describes registers in prose
("REG[0] holds PH, PT, RD_DIS, GPM bits") without saying which bit is
which. Fresh-agent RTL then guesses the layout — often producing
{PH at bit 0, PT at bit 1, ...} when the silicon actually uses
{PH at bit 7, PT at bit 6, ...}. The chip RTL passes BFM (since BFM
echoes the agent's own bit layout) but real-silicon connect_test
returns wrong REG[0] readback bytes.

Rule
----
For every register in `L4_REGMAP.json.registers` that carries a non-empty
field list, every entry must place itself:

    {"name": "PH", "bit": 7}                 single-bit field
    {"name": "MODE", "bits": [4, 5]}         contiguous multi-bit
    {"name": "MODE", "msb": 5, "lsb": 4}     msb/lsb form
    {"name": "RES",  "bit_range": "5:4"}     verilog range string
    {"name": "RES",  "bits": "5:4"}          the same range as a STRING,
                                             which is what this plugin's own
                                             harvesters emit

**Forbidden** (gate FAILs):

    {"name": "PH"}                  no bit position
    {"name": "PH", "bit": null}     null position
    {"name": "PH", "position": "?"} placeholder

Two vocabulary alignments, both MEASURED (vibe-ic#377)
------------------------------------------------------
This gate was inert. It read the field list under `bit_fields` (list schema)
or `bits` (dict schema) and NOTHING under `fields` — which is the key this
plugin's own L4 harvesters write. Over the git-tracked published corpus:

    L4 documents declaring registers            71
    gate verdict PASS                           71
    gate verdict FAIL                            0
    registers the gate iterated a field for       0  of 702

Zero. The gate that exists to catch an unplaced field had never examined one.
The container-key half is the `layergate-2` shape a third time: the value was
in the record the consumer already held, under a key it never read. It is also
a gate left behind rather than a schema ambiguity — the sibling gate on this
same layer already resolves `fields or bit_fields or subfields`, and carries
the note "without <name resolution> this gate is vacuous on production L4".

Reading the right key alone would have been WRONG, and that is the second
half. The int-only schema above rejects `{"bits": "7:0"}`, and 184 corpus
fields are exactly that — a designation this plugin's own register emitter
accepts and places. Flipping the container key without the encoding would have
raised 184 failures that are not defects.

STRICTNESS IS LOAD-BEARING, not defensive. 115 corpus `bits`/`bit` values are
package-pin designations harvested from an address-pin table, of the shape
`A[15:13]` / `A8, A10`. A substring search reads the first as bits 15:13 and
places a register field off a package pin. The designation matcher is
therefore anchored and imported from the CONSUMER, so a field this gate calls
placed is a field the emitter can actually place — the gate cannot drift from
the code it speaks for.

An explicitly marked unknown is REPORTED, not fatal
---------------------------------------------------
A field may carry an explicit whole-register placeholder meaning "the source
document carries no field breakdown". That is a declaration of absence, not a
silent guess, and the register emitter is already pinned to derive NOTHING
from it. Failing it would punish the marker and push harvesters back toward
inventing a layout — the outcome #377 measured when an unmarked placeholder
was handed to a standard register generator and became authoritative-looking
RTL for a layout nobody specified.

So the two populations are separated:

    unplaced and UNMARKED   -> FAIL. Nothing anywhere places it and nothing
                               says so; downstream guesses invisibly.
    unplaced and MARKED     -> counted and PRINTED, exit code unaffected.

Printing the count is the anti-gaming guard. The marker silences a failure, so
a marker that starts multiplying has to become visible somewhere; before this
gate reported it, 202 corpus instances were visible to no consumer at all.

Usage
-----
python3 regmap_bit_layout_check.py <project_dir>

Honors waivers.json["regmap_bit_layout_unresolved"].
Returns 0 on PASS, 1 on FAIL.
"""

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl

# ---------------------------------------------------------------------------
# Consumer import — a field this gate calls "placed" must be a field the
# register emitter can actually place. Importing its matcher instead of
# copying the pattern is what stops the two from drifting apart again.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))

_CONSUMER_IMPORT_ERROR: str | None = None
try:  # pragma: no cover - exercised implicitly by every run
    import phase2_scaffold_gen as _consumer  # noqa: E402
except Exception as exc:  # pragma: no cover
    _consumer = None
    _CONSUMER_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

# Fallback only for the case where the consumer cannot be imported at all.
# Anchored at both ends on purpose: an unanchored search reads a pin
# designation as a bit range.
_FALLBACK_BITS_RE = re.compile(r"^\s*\[?\s*(\d+)\s*(?::\s*(\d+)\s*)?\]?\s*$")


def _designation_places_a_field(text: str) -> bool:
    """True when `text` is a bit designation and nothing else."""
    if _consumer is not None:
        return bool(_consumer._REG_FIELD_BITS_RE.match(text))
    return bool(_FALLBACK_BITS_RE.match(text))


# Resolved in this order, matching the sibling gate on this layer so the two
# cannot disagree about which list is a register's field list.
_FIELD_CONTAINER_KEYS = ("fields", "bit_fields", "subfields")

# The marker a harvester sets when the source document names a register but
# carries no breakdown of it. Chip-AGNOSTIC: a structural property of the
# record, not a name.
_WHOLE_REGISTER_PLACEHOLDER = "WHOLE_REG"


def field_is_marked_unknown(field: dict) -> bool:
    """True when the record explicitly declares its own layout absent."""
    if not isinstance(field, dict):
        return False
    if field.get("synthesised_whole_register_field") is True:
        return True
    for key in ("bits", "bit"):
        v = field.get(key)
        if isinstance(v, str) and v.strip() == _WHOLE_REGISTER_PLACEHOLDER:
            return True
    return False


def find_doc(project_dir: Path, name: str) -> Path | None:
    for base in (project_dir, project_dir / "phase1/generated_docs", _pl.generated_docs_dir(project_dir)):
        p = base / name
        if p.exists():
            return p
    return None


def field_has_explicit_bits(field: dict) -> bool:
    if not isinstance(field, dict):
        return False
    if isinstance(field.get("bit"), int):
        return True
    if isinstance(field.get("bits"), list) and \
       all(isinstance(b, int) for b in field["bits"]):
        return True
    if isinstance(field.get("msb"), int) and isinstance(field.get("lsb"), int):
        return True
    if isinstance(field.get("bit_range"), str) and ":" in field["bit_range"]:
        return True
    # STRING designations. This plugin's harvesters write the range as text
    # (`"7:0"`, `"[31:0]"`, `"3"`) and its register emitter places it; an
    # int-only schema called 184 corpus fields unplaced that are not.
    # `_designation_places_a_field` is anchored, so a package-pin designation
    # is still refused — 115 corpus values are of that shape.
    for key in ("bits", "bit"):
        v = field.get(key)
        if isinstance(v, str) and _designation_places_a_field(v):
            return True
    return False


def iter_register_fields(reg: dict) -> list:
    """The register's field list, under whichever key wrote it.

    Reading only `bit_fields` here is what made this gate inert on every
    document this plugin produces. Resolution order matches the sibling gate
    on this layer; first non-empty list wins rather than a union, so a record
    carrying two spellings is counted once."""
    for key in _FIELD_CONTAINER_KEYS:
        v = reg.get(key)
        if isinstance(v, list) and v:
            return v
    return []


# Same resolution order as the sibling gate on this layer. The placeholder
# records write `field_name`, so resolving only `name` would report every one
# of them as `<reg>.None` and make the printed count unreadable.
_FIELD_NAME_KEYS = ("name", "field", "bit_field", "field_name",
                    "bit_field_name", "fieldname")


def _field_name(field: dict) -> str:
    for k in _FIELD_NAME_KEYS:
        v = field.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "<unnamed>"


def _report_marked_unknown(marked: list) -> None:
    """Print the explicitly-marked-unknown population.

    Not fatal, but never silent. Until this gate reported it the marker was
    visible to no consumer at all, which is how 202 corpus instances of it
    accumulated unexamined."""
    if not marked:
        return
    print(f"NOTE — {len(marked)} field(s) explicitly declare their own layout "
          f"absent (whole-register placeholder).")
    print("  These are NOT counted as failures: the record says the source")
    print("  document carries no breakdown, and the register emitter is")
    print("  pinned to derive no width from them. They are reported because a")
    print("  marker that silences a check has to stay countable.")
    for f in marked[:10]:
        print(f"  · {f}")
    if len(marked) > 10:
        print(f"  ... and {len(marked) - 10} more")
    print()


def waived(project_dir: Path, name: str) -> bool:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        unresolved = d.get("regmap_bit_layout_unresolved", [])
        if isinstance(unresolved, list):
            return any(name in str(item) for item in unresolved)
        return name in str(unresolved)
    except Exception:
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: regmap_bit_layout_check.py <project_dir>")
        sys.exit(2)
    project_dir = Path(sys.argv[1]).resolve()
    l4_path = find_doc(project_dir, "L4_REGMAP.json")
    if not l4_path:
        print("PASS — no L4_REGMAP.json (gate not applicable)")
        sys.exit(0)
    try:
        l4 = json.loads(l4_path.read_text())
    except Exception as e:
        print(f"FAIL — cannot parse L4: {e}")
        sys.exit(1)

    # L4_REGMAP.json `registers` may be either:
    #   list of dicts: [{"name":"REG0", "bit_fields":[{"name":"PH","bit":7}]}]
    #   dict of dicts: {"REG0": {"bits": {"PH": {"bit":7}}}}
    # Both schemas have appeared in regmap-gen output; accept both.
    raw = l4.get("registers")
    if isinstance(raw, dict):
        reg_iter = [
            {"name": rname, **(rdef if isinstance(rdef, dict) else {})}
            for rname, rdef in raw.items()
        ]
    elif isinstance(raw, list):
        reg_iter = [r for r in raw if isinstance(r, dict)]
    else:
        reg_iter = []

    failures = []
    marked_unknown = []
    n_fields_examined = 0
    for reg in reg_iter:
        rname = reg.get("name") or reg.get("addr") or "<unnamed>"
        # The list schema names the field list under one of several keys; the
        # dict schema hangs it off `bits`. Resolve the list schema through the
        # shared key set — reading only `bit_fields` here is what left this
        # gate iterating nothing on every document this plugin writes.
        field_list = iter_register_fields(reg)
        bits = reg.get("bits")
        field_iter = []
        if field_list:
            field_iter = [(_field_name(f) if isinstance(f, dict) else str(f), f)
                          for f in field_list]
        elif isinstance(bits, dict):
            field_iter = [(fname, fdef if isinstance(fdef, dict) else {})
                          for fname, fdef in bits.items()]
        for fname, field in field_iter:
            n_fields_examined += 1
            if field_has_explicit_bits(field):
                continue
            if waived(project_dir, f"{rname}.{fname}"):
                continue
            # A declaration of absence is not a silent guess. Counted and
            # printed below, but it does not fail the gate — see the module
            # docstring for why failing it would push harvesters back toward
            # inventing a layout.
            if field_is_marked_unknown(field):
                marked_unknown.append(f"{rname}.{fname}")
                continue
            failures.append(f"{rname}.{fname}")

    if not failures and n_fields_examined == 0:
        # An L4 doc that declares no register fields is not a register map this
        # gate verified. "every field has explicit bit positions" is vacuously
        # true over zero fields, and rc 0 is what the umbrella aggregates.
        #
        # Measured over 106 corpus projects (#564):
        #   77  no L4 doc at all        -> already "not applicable"
        #   24  L4 present, 0 fields    -> THIS branch; was PASS, now rc 2
        #    5  L4 present, 7..84 fields-> unaffected, still PASS
        #
        # So 24 projects move from a pass that examined nothing to an explicit
        # "could not check". None of the 5 real register maps is touched.
        print("VACUOUS_PASS: regmap_bit_layout_check examined nothing "
              "(reason: L4 declares 0 register field(s)) — the bit-position "
              "rule is vacuously true over an empty field set", file=sys.stderr)
        # sys.exit, not return: this module's `main()` is called bare at the
        # bottom (`main()`, not `sys.exit(main())`), so a returned value is
        # discarded and every other exit here uses sys.exit too. My first
        # version used `return 2` and the message printed while rc stayed 0 —
        # the exact split between message and exit code this fix is about,
        # committed inside the fix for it.
        sys.exit(2)

    if not failures:
        print(f"PASS — every L4 register field has explicit bit position(s) "
              f"({n_fields_examined} field(s) examined)")
        _report_marked_unknown(marked_unknown)
        sys.exit(0)

    print(f"FAIL — {len(failures)} register field(s) lack explicit bit position:")
    for f in failures[:15]:
        print(f"  • {f}")
    if len(failures) > 15:
        print(f"  ... and {len(failures) - 15} more")
    print()
    _report_marked_unknown(marked_unknown)
    print("Why this matters:")
    print("  Without explicit bit positions, fresh-agent RTL guesses the")
    print("  layout. BFM echoes the agent's own ordering and passes; real")
    print("  silicon returns differently-laid-out bytes and connect_test")
    print("  FAILs on 0x72 GET_STATE / 0x70 SET_STATE byte mismatch.")
    print()
    print("Fix: regmap-gen must emit each bit_fields entry as one of:")
    print('    {"name": "PH",   "bit": 7}')
    print('    {"name": "MODE", "msb": 5, "lsb": 4}')
    print('    {"name": "RES",  "bit_range": "5:4"}')
    print()
    print('Or document unresolvable layout in waivers.json:')
    print('    {"regmap_bit_layout_unresolved": ["REG0.PH — vendor doc')
    print('       names but does not place; needs silicon decode."]}')
    sys.exit(1)


if __name__ == "__main__":
    main()
