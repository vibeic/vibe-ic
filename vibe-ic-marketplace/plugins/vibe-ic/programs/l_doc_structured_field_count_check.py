#!/usr/bin/env python3
"""
l_doc_structured_field_count_check.py — gate (Wave 31/32, v0.119.64).

Each L*.json doc in `<project>/generated_docs/` MUST carry a
minimum number of TYPED structured fields, not just raw text.

Why this gate exists
====================
SEMANTIC_AUDIT_v0119.57 (docs/design/SEMANTIC_AUDIT_v0119.57.md) showed
that even projects whose `extraction_coverage_check` reported a perfect
1094/1094 = 100% literal-token grep score had ~87 % of every literal
landing in a raw `all_input_literals_aggregated` blob field, with 9
of 13 L docs carrying ZERO typed structured fields. The 100% metric
was gameable: extraction skills can stuff one giant dump field, hit
100% by substring match, and ship downstream RTL with no real
schema content for L3 opcodes / L4 registers / L6 FSM states / etc.

Wave 31 — `extraction_coverage_check` excludes blob fields when
counting; this companion gate FAILs whenever any L doc carries fewer
typed structured fields than its semantic role demands.

A "typed structured field" is:
  - a dict-valued field (excluding the metadata field
    ``extraction_evidence``)
  - an array of dicts (e.g. ``opcodes: [{...}, {...}]``)
  - a scalar field whose name does NOT match the blob-field shape
    (``*_dump`` / ``*_blob`` / ``*_aggregated`` / ``raw_*`` /
    ``LX_DUMP`` / ``all_input_literals_*``).

Per-L-doc minimums (chip-AGNOSTIC, derived from semantic role):
  L1  (datasheet)            ≥10 typed fields
  L2  (FRS)                  ≥15 typed fields
  L3  (cmd protocol)         ≥5 typed opcodes  AND  ≥1 crc_parameters block
  L4  (regmap + otp_layout)  ≥5 typed fields counted across registers
                              and otp_layout sub-fields (Wave 32:
                              read_map / write_map / lockbits /
                              otp_ip_specs / trim_registers /
                              mask_sources). Either ≥5 typed register
                              entries OR ≥5 typed otp_layout sub-fields
                              satisfies.
  L5  (adi-spec)             ≥3 typed analog blocks  OR  no_analog == True
  L6  (control logic)        ≥5 typed FSM states
  L7  (test debug)           ≥3 typed test scenarios
  L8  (timing)               ≥10 timing constants typed
  L9  (integration)          ≥3 typed (top_module + fsm_states[]
                              + port list)
  L10 (test cases)           ≥5 typed test cases
  L11 (behavioral + cal)     ≥3 typed fields counted across
                              behavioral_sequences and calibration_tables
                              (Wave 32: jointly owned by
                              behavioral-sequences-gen + calibration-gen).
                              The legacy `sequences` / `otp_table`
                              forms remain accepted aliases.
  L12 (calibration legacy)   ≥1 typed  OR  no_calibration == True
  L13 (test cases / lab cal) ≥5 typed

Wave 23 forbids waivers in this family — there is no escape hatch.
The forbidden-waiver list in `phase1_no_waivers_used_check` is
extended in Wave 31 to include the prefix `l_doc_structured_*`.

Usage
-----
    python3 l_doc_structured_field_count_check.py <project_dir>

Returns 0 PASS, 1 FAIL, 2 input error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import _path_layout as _pl

# Wave 42 — ensure the programs/ dir is on sys.path so sibling
# imports work whether this module is invoked as a script or
# imported by tests / orchestrators.
_PROG_DIR = str(Path(__file__).resolve().parent)
if _PROG_DIR not in sys.path:
    sys.path.insert(0, _PROG_DIR)

import _reused_ip_predicate as _reused_ip  # noqa: E402
# Imported, never re-typed — a local copy of the key silently stops
# excluding it the day the key is renamed.
from l_doc_generator_stamp import STAMP_KEY as _GENERATOR_STAMP_KEY  # noqa: E402,E501

# Wave 36 (v0.119.68) — IC class profile lets us drop layer
# requirements that don't apply (e.g. L3 / L6 on a pure-analog
# PMIC). Imported lazily so the program still runs standalone.
try:
    from ic_class_profile import detect_ic_class
except Exception:  # pragma: no cover - defensive
    detect_ic_class = None  # type: ignore[assignment]


# Field names treated as RAW BLOB and therefore not counted as a
# typed structured field. chip-AGNOSTIC.
_BLOB_FIELD_NAMES = (
    "all_input_literals_aggregated",
    "raw_text",
    "evidence_text",
)
_BLOB_FIELD_SUFFIXES = ("_dump", "_blob", "_aggregated")
_BLOB_FIELD_PREFIXES = ("LX_DUMP", "all_input_literals_", "raw_", "RAW_")

# Metadata fields that exist on every L doc but do NOT count toward
# the typed-field tally.  schema_version + layer + source_files are
# bookkeeping; extraction_evidence is structured pointer metadata
# (legitimate but does not represent extracted design data on its
# own); `_generator` records which plugin release wrote the file, so it
# is present on EVERY document and carries no extracted design data at
# all — counting it would lift every layer's tally by exactly one and
# hand a thin document a floor it did not earn.
_BOOKKEEPING_FIELDS = frozenset({
    "schema_version", "layer", "source_files",
    "extraction_evidence",
    _GENERATOR_STAMP_KEY,
})


# ── ORGANIC #706 — ai_deep_review_patches sidecar merge (fail-closed) ─────────
# Sibling gate `phase1_doc_input_completeness_check` already merges the durable
# `phase1/ai_deep_review_patches.json` sidecar (the home of MANDATORY AI
# deep-review recoveries — generated_docs/L*.json is rewritten from scratch every
# Phase-1 run, so a recovered field can ONLY survive in the sidecar). This
# typed-field-COUNT gate read ONLY generated_docs/L*.json, so an AI-recovered,
# doc-traceable typed field credited by the completeness gate could not satisfy a
# count floor without hand-editing the regen-overwritten L*.json (which the
# phase-1 skill forbids) — a latent asymmetry. We mirror the sibling's sidecar
# channel here so EVERY count floor honours the same AI-recovery source.
#
# FAIL-CLOSED (§4.05 NO-LEAK): a sidecar entry is merged into a layer's primary
# typed list ONLY when it carries the typed SHAPE the floor requires — a name-like
# identifier AND ≥1 substantive shape key (fsm_states: transitions/actions; ports:
# dir/width; opcodes: encoding/bits; registers: offset/bits). A bare token can
# therefore never inflate a count floor, and a genuinely thin doc with no
# qualifying sidecar entry still FAILs/waives exactly as before. chip-AGNOSTIC.
_AI_PATCH_MARKER = "ai_deep_review_patch"

# layer → (primary-list aliases in `data`, name-like keys, substantive shape keys)
_SIDECAR_FLOOR_LAYERS = {
    3: (("opcodes", "commands"),
        ("name", "mnemonic", "opcode", "cmd"),
        ("code", "opcode", "encoding", "bits", "value", "fields")),
    4: (("registers", "regmap", "register_table", "register_map"),
        ("name", "register", "reg", "field"),
        ("offset", "address", "addr", "bits", "width", "fields", "reset")),
    6: (("fsm_states", "states", "state_table"),
        ("name", "state"),
        ("transitions", "actions", "next", "on", "outputs")),
    9: (("ports", "port_list", "top_ports"),
        ("name", "port", "signal"),
        ("dir", "direction", "width", "bits", "msb")),
}


def _is_ai_patch_entry(entry) -> bool:
    """A sidecar entry is an AI deep-review patch iff it is a dict carrying the
    `extraction_strategy/label/strategy == ai_deep_review_patch` marker — the
    same marker the sibling completeness gate keys on (so the two gates honour
    the SAME channel, never a looser one)."""
    if not isinstance(entry, dict):
        return False
    return any(entry.get(k) == _AI_PATCH_MARKER
               for k in ("extraction_strategy", "label", "strategy"))


def _typed_patch_ok(entry: dict, name_keys, shape_keys) -> bool:
    """FAIL-CLOSED typed-shape gate: the entry must carry a non-empty name-like
    identifier AND at least one non-empty substantive shape key, so a bare
    `{"name": "x"}` token (or a marker-only stub) can never satisfy a count
    floor."""
    has_name = any(isinstance(entry.get(k), str) and entry.get(k).strip()
                   for k in name_keys)
    has_shape = any(entry.get(k) not in (None, "", [], {})
                    for k in shape_keys)
    return has_name and has_shape


def _load_field_count_sidecar(project: "Path") -> dict:
    """Return {layer_number: [typed_patch_dict, ...]} from
    `phase1/ai_deep_review_patches.json` — mirrors
    phase1_doc_input_completeness_check._load_ai_patches_sidecar (same resolver,
    same `patches` schema). Only AI-patch-marked entries are returned; the
    per-layer typed-shape filter is applied at merge time. Any read/parse error
    → {} (the sidecar is purely additive; its absence never changes a verdict)."""
    try:
        canonical = _pl.phase1_ai_deep_review_patches_file(project)
    except Exception:
        return {}
    side = canonical if canonical.is_file() else None
    if side is None:
        # Defense-in-depth: a fresh agent following an older doc may have
        # written the sidecar to the PROJECT ROOT instead of phase1/. When
        # the canonical file is absent but a same-named ROOT copy exists,
        # emit a one-line WARNING and read it for backward-compat instead of
        # silently dropping the MANDATORY AI-recovery channel.
        root_legacy = project / "ai_deep_review_patches.json"
        if root_legacy.is_file():
            print(
                "WARNING — ai_deep_review_patches.json found at project "
                f"ROOT ({root_legacy}); canonical location is {canonical}. "
                "Reading the ROOT copy for backward-compat — please move it "
                "under phase1/.",
                file=sys.stderr,
            )
            side = root_legacy
        else:
            return {}
    try:
        data = json.loads(side.read_text(errors="replace"))
    except Exception:
        return {}
    patches = data.get("patches") if isinstance(data, dict) else None
    if not isinstance(patches, dict):
        return {}
    out: dict = {}
    for layer_key, lst in patches.items():
        if not isinstance(lst, list):
            continue
        layer_no = _detect_l_layer(str(layer_key))
        if layer_no is None:
            continue
        entries = [e for e in lst if _is_ai_patch_entry(e)]
        if entries:
            out.setdefault(layer_no, []).extend(entries)
    return out


def _merge_sidecar_for_layer(layer: int, data: dict,
                             sidecar: dict) -> None:
    """Append the layer's typed-shape-valid sidecar patches into the SAME
    primary-list alias `_check_l_doc` reads (the first NON-EMPTY alias, matching
    its `data.get(a) or data.get(b)` short-circuit; canonical alias when none is
    populated). Mutates `data` in place. No-op for layers without a count floor,
    or when no qualifying sidecar entry exists (preserving the verdict)."""
    spec = _SIDECAR_FLOOR_LAYERS.get(layer)
    if spec is None or not isinstance(data, dict):
        return
    aliases, name_keys, shape_keys = spec
    entries = sidecar.get(layer) or []
    valid = [e for e in entries if _typed_patch_ok(e, name_keys, shape_keys)]
    if not valid:
        return
    # Match _check_l_doc's `or`-chain: it reads the first NON-EMPTY alias list.
    target = None
    for a in aliases:
        v = data.get(a)
        if isinstance(v, list) and v:
            target = a
            break
    if target is None:
        target = aliases[0]
        data[target] = []
    if isinstance(data.get(target), list):
        data[target].extend(valid)


def _is_blob_field(name: str) -> bool:
    if not isinstance(name, str):
        return False
    if name in _BLOB_FIELD_NAMES:
        return True
    for s in _BLOB_FIELD_SUFFIXES:
        if name.endswith(s) or name.endswith(s.upper()):
            return True
    for p in _BLOB_FIELD_PREFIXES:
        if name.startswith(p):
            return True
    return False


def _count_typed_fields(data) -> int:
    """Count the number of TYPED structured top-level fields.

    A field counts when it is:
      - a dict (excluding `extraction_evidence` and bookkeeping)
      - a non-empty list of dicts
      - a non-empty list of non-blob scalars
      - a scalar field with a non-bookkeeping, non-blob name
    """
    if not isinstance(data, dict):
        return 0
    n = 0
    for k, v in data.items():
        if k in _BOOKKEEPING_FIELDS:
            continue
        if _is_blob_field(k):
            continue
        if isinstance(v, dict) and v:
            n += 1
        elif isinstance(v, list) and v:
            # Treat non-empty list-of-dict as one typed field.
            # Treat non-empty list-of-scalars as one typed field if
            # the list itself has at least one entry.
            n += 1
        elif v not in (None, "", [], {}):
            n += 1
    return n


def _list_len_of_dicts(value) -> int:
    if not isinstance(value, list):
        return 0
    return sum(1 for x in value if isinstance(x, dict))


# v0.2.16 — honest typed-N/A recognition (completing the set started by
# L5.no_analog / L12.no_calibration). A pure-digital protocol IC genuinely
# has NO CRC / NO OTP fuses / NO lab-calibration. The synth/runner already
# emit explicit honest declarations for these; the gate must ACCEPT them as
# satisfying the requirement instead of FAILing for a structurally absent
# field that the doc itself has truthfully declared N/A.
#
# HONESTY GUARDS (chip-AGNOSTIC, no waiver — this is the doc's OWN typed
# declaration, never a missing/empty field standing in for one):
#   (a) only an EXPLICIT boolean-True no_X flag (or explicit applicable=False)
#       counts — a bare missing/empty field does NOT;
#   (b) an explicit no_X == False (or otp_present == True / applicable == True)
#       leaves the requirement IN FORCE — a protocol that genuinely HAS the
#       feature must still populate it;
#   (c) these mirror the gate's own existing escapes, completing the set.

def _explicit_true(value) -> bool:
    """True only for an EXPLICIT boolean True. Strings, ints, None, missing
    keys, and False all return False — so a bare/absent/false field can NEVER
    masquerade as an honest N/A declaration (HONESTY GUARD (a)/(b))."""
    return value is True


def _explicit_false(value) -> bool:
    """True only for an EXPLICIT boolean False."""
    return value is False


def _has_honest_no_crc(data: dict) -> bool:
    """L3: doc explicitly declares it has NO CRC. Accept the existing
    `no_crc_parameters_in_input == true` (or a `no_crc == true`) flag, but
    ONLY when it is explicitly True. A genuinely-CRC protocol that left
    no_crc == False (or absent) keeps the crc_parameters requirement in
    force (HONESTY GUARD (b))."""
    return (_explicit_true(data.get("no_crc_parameters_in_input"))
            or _explicit_true(data.get("no_crc"))
            or _explicit_true(data.get("no_crc_in_input")))


def _has_honest_no_otp(data: dict) -> bool:
    """L11: doc explicitly declares it has NO OTP fuse content. Accept any of
    the honest signals the runner already emits: an explicit no_otp* True flag
    (e.g. `no_otp_fsm_in_input`), an explicit `otp_present == false`, or an
    explicit `applicable == false`. `otp_present` is sometimes a free-text
    string (functional description) — that does NOT count; only the explicit
    boolean False does, plus any explicit no_otp* True flag / applicable
    False (HONESTY GUARD (a))."""
    if _explicit_false(data.get("otp_present")):
        return True
    if _explicit_false(data.get("applicable")):
        return True
    for k, v in data.items():
        if not isinstance(k, str):
            continue
        kl = k.lower()
        if (kl.startswith("no_otp") or kl == "no_fuse"
                or kl.startswith("no_fuse")) and _explicit_true(v):
            return True
    return False


def _has_explicit_no_otp_flag(data: dict) -> bool:
    """L11 N/A escape — STRICTER than _has_honest_no_otp. L11 jointly owns
    behavioral_sequences + calibration_tables + OTP, so a bare
    `otp_present: false` (which only addresses the OTP sub-component) is NOT a
    sufficient escape — the doc could still be expected to carry behavioral /
    calibration content. Only an EXPLICIT layer-level declaration counts: an
    explicit no_otp* / no_fuse* True flag (e.g. `no_otp_fsm_in_input: true`,
    the runner's honest "no OTP FSM in the input doc" signal) OR an explicit
    `applicable == false` (whole layer N/A). Protocol controllers
    (mdio/espi/usb_pd) carry no_otp_fsm_in_input: true and pass; a doc with
    only otp_present:false + empty behavioral/calibration fails the ≥3 floor."""
    if _explicit_false(data.get("applicable")):
        return True
    for k, v in data.items():
        if not isinstance(k, str):
            continue
        kl = k.lower()
        if (kl.startswith("no_otp") or kl == "no_fuse"
                or kl.startswith("no_fuse")) and _explicit_true(v):
            return True
    return False


def _has_honest_no_lab(data: dict) -> bool:
    """L13: doc explicitly declares it has NO lab-bench calibration. Accept an
    explicit `lab_calibration_present == false`, an explicit `applicable ==
    false`, or an explicit no_lab* True flag (HONESTY GUARD (a))."""
    if _explicit_false(data.get("lab_calibration_present")):
        return True
    if _explicit_false(data.get("applicable")):
        return True
    for k, v in data.items():
        if not isinstance(k, str):
            continue
        kl = k.lower()
        if (kl.startswith("no_lab")
                or kl.startswith("no_calibration")) and _explicit_true(v):
            return True
    return False


def _has_honest_no_fsm(data: dict) -> bool:
    """L6 (#462): doc explicitly declares the input forbids / contains NO control
    FSM. Accept an explicit `no_fsm_in_input == true`, an explicit
    `no_fsm == true`, or any explicit no_fsm* True flag — but ONLY when it is
    explicitly True. A bare missing/empty flag, or `no_fsm == false` (a design
    that genuinely HAS an FSM), keeps the L6 floor in force (HONESTY GUARD
    (a)/(b)). This mirrors the existing L3 no-CRC / L11 no-OTP escapes and
    completes the set begun by L5.no_analog / L12.no_calibration."""
    if _explicit_true(data.get("no_fsm_in_input")):
        return True
    if _explicit_true(data.get("no_fsm")):
        return True
    for k, v in data.items():
        if not isinstance(k, str):
            continue
        if k.lower().startswith("no_fsm") and _explicit_true(v):
            return True
    return False


def _has_honest_no_test_debug(data: dict) -> bool:
    """L7 (#677): doc explicitly declares the input carries NO test/verification
    /debug surface for the IC. Accept any of the honest-absence signals the
    runner already emits for L7 — `no_test_scenarios_in_input`,
    `no_verification_strategy_in_input`, `no_test_modes_in_input`,
    `no_test_debug_in_input` — but ONLY when explicitly True. A bare
    missing/empty/false flag can NEVER masquerade (HONESTY GUARD (a)/(b)).

    This mirrors the L3 no-CRC / L6 no-FSM / L11 no-OTP / L13 no-lab escapes and
    completes the set begun by L5.no_analog / L12.no_calibration. A minimal
    register-mapped peripheral (bus_peripheral) genuinely has no chip-level test
    scenarios in its input spec (its verification lives in the integrator's DV
    env, not the IP datasheet); phase1 cannot synthesise scenarios the spec does
    not contain.  The L7 floor stays in force for any class/doc WITHOUT an
    explicit honest flag (corpus-sweep guard)."""
    for key in ("no_test_scenarios_in_input",
                "no_verification_strategy_in_input",
                "no_test_modes_in_input",
                "no_test_debug_in_input"):
        if _explicit_true(data.get(key)):
            return True
    return False


def _has_honest_no_test_cases(data: dict) -> bool:
    """L10 (#677): doc explicitly declares the input carries NO chip-level test
    cases AND no bring-up sequence to harvest. Accept the runner's honest-absence
    signals — `no_test_cases_in_input` (and, when present, an explicit
    `no_bring_up_sequence_in_input`) — but ONLY when explicitly True (HONESTY
    GUARD (a)/(b)).

    This is the ORTHOGONAL minimal-honest-absence case to the #641 harvest path:
    #641 fires only when there IS a bring_up_sequence to count; a genuinely
    minimal peripheral has nothing to harvest yet still honestly declares
    `no_test_cases_in_input: true`. Without this escape that honest minimal doc
    FAILs the floor. The floor stays in force for any class/doc WITHOUT an
    explicit honest flag (corpus-sweep guard)."""
    return _explicit_true(data.get("no_test_cases_in_input"))


def _has_honest_no_regmap(data: dict) -> bool:
    """L4 (#677): doc explicitly declares the input carries NO SW-visible
    register map. Accept the existing `register_map_present == False` /
    `no_register_map == True` escapes PLUS the runner's `no_*_in_input`
    honest-absence mirror (`no_register_map_in_input` /
    `no_regmap_in_input`), but ONLY when explicitly True/False (HONESTY GUARD
    (a)/(b)). A bare missing/empty/true register_map_present keeps the floor."""
    if _explicit_false(data.get("register_map_present")):
        return True
    if _explicit_true(data.get("no_register_map")):
        return True
    for k, v in data.items():
        if not isinstance(k, str):
            continue
        kl = k.lower()
        if (kl.startswith("no_register_map")
                or kl.startswith("no_regmap")) and _explicit_true(v):
            return True
    return False


_L4_OTP_REAL_SUBFIELDS = ("fields", "read_map", "write_map", "lockbits",
                          "otp_ip_specs", "trim_registers", "mask_sources")


def _l4_otp_layout_has_no_real_content(otp_layout) -> bool:
    """True when the L4 otp_layout carries NO real OTP content — every
    meaningful OTP sub-field (image fields / read_map / write_map / lockbits /
    otp_ip_specs / trim_registers / mask_sources) is empty/None. Bookkeeping
    defaults such as depth_bytes / width_bits do NOT count as content. Used to
    confirm the OTP alternative source is genuinely absent before crediting a
    complete minimal regmap (below the ≥5 floor)."""
    if not isinstance(otp_layout, dict):
        return True
    for k in _L4_OTP_REAL_SUBFIELDS:
        v = otp_layout.get(k)
        if v not in (None, "", [], {}):
            return False
    return True


_REGDOC_ADDR_COLS = ("offset", "address", "addr", "reg_addr", "base")
_REGDOC_NAME_COLS = ("name", "register", "reg", "field")


def _count_input_declared_registers(project) -> "int | None":
    """Count the registers DECLARED in the design's input docs by tallying the
    data rows of every GFM pipe-table that is clearly a register map (a header
    carrying BOTH an address-like column — offset/address/addr/… — AND a
    name/register column). Reads only staged INPUT docs (phase1/input_doc/ +
    input/docs/), never generated_docs / golden (§4.05).

    Returns the total declared-register count, or None when no register-map
    table is found (the caller then keeps the strict floor — fail-closed, so a
    doc whose register source cannot be located never rides the credit).

    chip-AGNOSTIC: identifies a register-map table by its column semantics, not
    by any chip/register name; a pin/port/signal table (no address column) is
    NOT counted."""
    if project is None:
        return None
    try:
        import re as _re
        from pathlib import Path as _P
        roots = [
            _P(project) / "phase1" / "input_doc",
            _P(project) / "input" / "docs",
            _P(project) / "input",
        ]
        files = []
        seen = set()
        seen_stems = set()
        for root in roots:
            if root.is_dir():
                for ext in ("*.txt", "*.md"):
                    for f in sorted(root.rglob(ext)):
                        if f in seen:
                            continue
                        seen.add(f)
                        # De-dupe STAGED COPIES of the same doc (e.g.
                        # phase1/input_doc/L5_register_map.txt vs
                        # input/docs/L5_register_map.md) by filename stem so a
                        # register table is not counted twice.
                        st = f.stem.lower()
                        if st in seen_stems:
                            continue
                        seen_stems.add(st)
                        files.append(f)
        if not files:
            return None
        total = None
        for f in files:
            try:
                lines = f.read_text(errors="replace").splitlines()
            except OSError:
                continue
            i = 0
            while i < len(lines):
                line = lines[i]
                if line.count("|") >= 2 and i + 1 < len(lines) \
                        and _re.match(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$",
                                      lines[i + 1]):
                    header = [c.strip().lower()
                              for c in line.strip().strip("|").split("|")]
                    has_addr = any(any(a in h for a in _REGDOC_ADDR_COLS)
                                   for h in header)
                    has_name = any(any(nm == h or nm in h.split()
                                       for nm in _REGDOC_NAME_COLS)
                                   for h in header)
                    if has_addr and has_name:
                        # Count contiguous data rows after the separator.
                        j = i + 2
                        rows = 0
                        while j < len(lines) and lines[j].count("|") >= 2 \
                                and lines[j].strip().startswith("|"):
                            cells = [c.strip() for c in
                                     lines[j].strip().strip("|").split("|")]
                            if any(cells):
                                rows += 1
                            j += 1
                        total = (total or 0) + rows
                        i = j
                        continue
                i += 1
        return total
    except Exception:
        return None


def _detect_l_layer(name: str) -> int | None:
    """Return the L layer integer (1..13) inferred from filename, or
    None if the file does not name an L doc."""
    if not name.startswith("L"):
        return None
    rest = name[1:].split("_", 1)[0].split(".", 1)[0]
    try:
        n = int(rest)
    except ValueError:
        return None
    if 1 <= n <= 13:
        return n
    return None


def _facts_yaml_escape_flags(project: Path) -> dict[str, bool]:
    """Wave 36 (v0.119.68) / Wave 42 (v0.119.70) — read facts.yaml for
    human-asserted escape booleans. Returned dict has keys
    `no_command_protocol`, `no_fsm`, `no_timing_classification`.

    Wave 42 / MF3 — substring grep replaced with a real YAML parser.
    Substring matching let attacks like commented-out flags
    (`# no_fsm: true`) or nested mappings
    (`metadata: { no_fsm: true }`) silence gates. Only TOP-LEVEL
    boolean keys count now.
    """
    out = {
        "no_command_protocol": False,
        "no_fsm": False,
        "no_timing_classification": False,
    }
    try:
        from _facts_yaml import (  # type: ignore
            read_facts_yaml,
            get_top_level_truthy,
        )
    except Exception:
        # PyYAML unavailable — fail-closed: no escape booleans.
        return out
    facts = read_facts_yaml(project)
    for key in list(out.keys()):
        out[key] = get_top_level_truthy(facts, key, default=False)
    return out


# v0.1.83 — datapath/compute + CPU classes. Their L1-L23 specs document the
# external contract and delegate internal micro-architecture (FSM depth, exact
# timing) to the implementation, so the protocol-chip-tuned L6 (≥5 FSM) / L8
# (≥10 timing) floors are relaxed for them (to ≥2 / ≥3) — a real floor, not a
# skip. NOT a command-driven or protocol class (those keep the strict default).
_DATAPATH_COMPUTE_CLASSES = frozenset({
    "digital_arithmetic_primitive", "processor_cpu",
})

# Wave 36 fail-closed classes: detection ambiguity must NOT relax minimums.
_NO_PROTOCOL_FAIL_CLOSED = frozenset({"bare_fpga", "unknown_protocol_class"})


def _class_no_cmd_protocol(ic_class: str) -> bool:
    """ORGANIC-20260606-structured-field-count-no-protocol-class (#428):
    classes the runner's OWN registry marks `command_protocol_applicable=
    False` AND that have no deterministic rtl_gen (pure datapath / compute
    transforms) have no source for opcodes / registers / OTP — phase1
    cannot synthesize protocol fields the spec does not contain, so the
    protocol-chip minimums switch to an N/A-SKIPPED-CONDITION for them
    (not a FAIL, not a waiver). Reuses the registry instead of a hardcoded
    class list; falls back to the legacy datapath list when the registry
    is unreadable. bare_fpga / unknown stay fail-closed per Wave 36."""
    if ic_class in _NO_PROTOCOL_FAIL_CLOSED:
        return False
    try:
        reg = json.loads(
            (Path(__file__).resolve().parent / "ic_class_registry.json")
            .read_text())
        for e in reg.get("classes", []):
            if (e.get("name") == ic_class
                    or ic_class in (e.get("synonyms") or [])):
                return (e.get("command_protocol_applicable") is False
                        and e.get("rtl_gen") is None)
    except (OSError, ValueError):
        pass
    return ic_class in _DATAPATH_COMPUTE_CLASSES


def _class_sparse_control_timing(ic_class: str) -> bool:
    """ORGANIC #605 — True iff the registry marks this class as having a
    SPARSE control+timing surface: pure datapath / compute / accelerator
    transforms that delegate the internal micro-architecture FSM to the
    implementation and document only a handful of timing facts (clock period,
    cycle count, latency). These get the relaxed L6 (≥2 FSM) / L8 (≥3 timing)
    floors instead of the strict protocol-genre ≥5 / ≥10.

    Distinct from `_class_no_cmd_protocol`: a bus / serial PROTOCOL class is
    ALSO `command_protocol_applicable==False` in the registry, but it carries a
    RICH protocol state machine + timing-waveform spec, so it must KEEP the
    strict 5/10 floors (v0.1.83 doctrine + test_protocol_stays_strict). The
    registry's `command_protocol_applicable` flag therefore cannot drive this
    relaxation — it does not separate sparse compute classes from rich protocol
    classes. A dedicated semantic registry flag (`sparse_control_timing`) does.

    bare_fpga / unknown_protocol_class stay fail-closed; falls back to the
    legacy `_DATAPATH_COMPUTE_CLASSES` literal when the registry is unreadable.
    Chip-AGNOSTIC: a registry semantic flag, no chip-name literal."""
    if ic_class in _NO_PROTOCOL_FAIL_CLOSED:
        return False
    try:
        reg = json.loads(
            (Path(__file__).resolve().parent / "ic_class_registry.json")
            .read_text())
        for e in reg.get("classes", []):
            if (e.get("name") == ic_class
                    or ic_class in (e.get("synonyms") or [])):
                return e.get("sparse_control_timing") is True
    except (OSError, ValueError):
        pass
    return ic_class in _DATAPATH_COMPUTE_CLASSES


def _class_sparse_analog_blocks(ic_class: str) -> bool:
    """ORGANIC #634 — True iff the registry marks this class as having a
    SPARSE analog-block set: a data-converter / mixed-signal class whose
    legitimate analog content is a small, fixed set of blocks (e.g. a
    delta-sigma ADC = modulator + on-chip regulator/reference), fewer than the
    ≥3-block default the L5 floor was tuned for (a multi-rail PMIC / analog
    front-end with several distinct blocks). These get the relaxed L5 (≥2
    typed analog blocks) floor instead of the strict ≥3 — a REAL floor, not a
    skip: an empty / 0-block / 1-block analog doc still FAILs, so an empty or
    under-populated doc can never pass.

    Registry-driven (a dedicated `sparse_analog_block_set` SEMANTIC flag),
    NOT keyed on `_class_no_cmd_protocol` or on `analog_applicable` — a
    multi-block analog system (PMIC / SerDes AFE) is also analog_applicable
    yet must KEEP the strict ≥3 floor, so neither of those flags can drive
    this relaxation. bare_fpga / unknown_protocol_class stay fail-closed.
    Chip-AGNOSTIC: a registry semantic flag + numeric floor, no chip-name
    literal."""
    if ic_class in _NO_PROTOCOL_FAIL_CLOSED:
        return False
    try:
        reg = json.loads(
            (Path(__file__).resolve().parent / "ic_class_registry.json")
            .read_text())
        for e in reg.get("classes", []):
            if (e.get("name") == ic_class
                    or ic_class in (e.get("synonyms") or [])):
                return e.get("sparse_analog_block_set") is True
    except (OSError, ValueError):
        pass
    return False


def _class_non_analog_phantom_only(ic_class: str, blocks) -> bool:
    """ORGANIC #676 PARITY for the L5 typed-analog-block floor.

    #676 established the doctrine for the 3 analog P0 gates
    (`_analog_a_check_common._ic_class_says_non_analog` +
    `_all_blocks_low_confidence`): a gate must not hard-FAIL a
    POSITIVELY non-analog IC over a PHANTOM `low_confidence` block that the
    Phase-1 keyword harvester fabricated from an analog token occurring in
    digital prose. The sibling analog gates already self-skip as N/A on such
    an IC; the ones that lacked class awareness were given this predicate.

    This L5 floor is a FOURTH gate in that family and never received it. Its
    only escapes were the doc's own `no_analog` flag and #634's
    `sparse_analog_block_set` (which means SPARSE analog, not NO analog) —
    neither keyed on `analog_applicable`. So a class the registry declares
    `analog_applicable: false` is held to a ≥3-analog-block floor it can never
    meet, with the `no_analog: true` escape unavailable precisely BECAUSE the
    harvester wrote `no_analog: false` off the phantom hit. The gate becomes
    unsatisfiable through no fault of the design.

    §4.05 no-leak — returns True (→ floor N/A) ONLY when BOTH hold:
      * the registry marks the detected class `analog_applicable is False`
        (explicitly; a missing/unknown class is fail-closed), AND
      * EVERY declared block is tagged `low_confidence: true` — a phantom
        keyword hit, never a spec-backed block.
    A real analog class keeps the strict floor. A spec-backed
    (high-confidence) block on a non-analog class still FAILs — that is a
    genuine class/doc contradiction and must stay visible. An EMPTY block
    list returns False so the existing floor still demands the honest
    `no_analog: true` declaration; this predicate never converts an
    under-populated doc into a pass.

    chip-AGNOSTIC: a registry semantic flag + the per-block confidence tag;
    no chip / vendor / PDK / class-name literal drives the decision."""
    if not ic_class or ic_class in _NO_PROTOCOL_FAIL_CLOSED:
        return False
    try:
        reg = json.loads(
            (Path(__file__).resolve().parent / "ic_class_registry.json")
            .read_text())
    except (OSError, ValueError):
        return False
    entry = None
    for e in reg.get("classes", []):
        if (e.get("name") == ic_class
                or ic_class in (e.get("synonyms") or [])):
            entry = e
            break
    # Fail-closed: unknown class, or a class that is not EXPLICITLY
    # non-analog, keeps the strict floor.
    if entry is None or entry.get("analog_applicable") is not False:
        return False
    # An empty / non-list block set is NOT this path.
    if not isinstance(blocks, list) or not blocks:
        return False
    for b in blocks:
        if not isinstance(b, dict) or b.get("low_confidence") is not True:
            return False
    return True


def _class_minimal_honest_absence(ic_class: str) -> bool:
    """ORGANIC #677 — True iff the registry marks this class as a genuinely
    MINIMAL register-mapped peripheral whose input spec legitimately carries
    FEW typed L4/L7/L10 entries and HONESTLY declares the absence via a
    `no_*_in_input: true` flag (no regmap / no test scenarios / no test cases).
    Such a class gets the L4/L7/L10 honest-absence N/A escapes.

    This is DELIBERATELY NARROWER than `_class_no_cmd_protocol`: a reused-IP
    processor_cpu / crypto_accelerator is ALSO command_protocol_applicable==
    False + rtl_gen==null, but ORGANIC #641 holds those classes to a POPULATED
    bring_up_sequence (an empty bring-up with no_test_cases_in_input==true must
    still FAIL — they carry harvestable verification intent). A minimal
    bus_peripheral / interconnect / serial peripheral spec genuinely has nothing
    to harvest, so it gets the pure honest-absence escape. The registry's
    `command_protocol_applicable` flag cannot drive this (it matches BOTH
    families); a dedicated semantic registry flag (`minimal_honest_absence_ok`)
    does.

    bare_fpga / unknown_protocol_class stay fail-closed. Chip-AGNOSTIC: a
    registry semantic flag, no chip-name literal. When the registry is
    unreadable this returns False (fail-closed — the strict floor is the safe
    default)."""
    if ic_class in _NO_PROTOCOL_FAIL_CLOSED:
        return False
    try:
        reg = json.loads(
            (Path(__file__).resolve().parent / "ic_class_registry.json")
            .read_text())
        for e in reg.get("classes", []):
            if (e.get("name") == ic_class
                    or ic_class in (e.get("synonyms") or [])):
                return e.get("minimal_honest_absence_ok") is True
    except (OSError, ValueError):
        pass
    return False


# ─── ORGANIC #748 — L6 reused-IP staged-RTL FSM harvest (n_states==1 dead zone) ─
# The L6 floor is `l6_min = 2 if sparse_control_timing else 5`. For a REUSED-IP
# processor_cpu (sparse_control_timing=True → l6_min=2) the real multi-state
# control FSMs live in STAGED vendor RTL (controller / LSU typedef-enum state
# machines), and the doc prose honestly names ≤1 state. That leaves a DEAD ZONE:
# the #462 `_has_honest_no_fsm` escape requires n_states==0, the ≥2 floor catches
# n_states>=2, and the legitimate n_states==1 reused-IP case has NO escape — yet
# the `l_doc_structured_*` forbidden-waiver prefix blocks any waiver. The FSM
# provably EXISTS in staged RTL; phase-1 prose just under-counts it.
#
# Fix (chip-AGNOSTIC, DOUBLE-KEYED per the #428/#419/#641/#708 doctrine):
# credit the FSM state count HARVESTED from the staged vendor RTL's
# `typedef enum {...} ..._e;` (for `*_fsm_cs` / `*_fsm_ns` / `*_state`-typed
# signals), but ONLY when (a) the IC class has rtl_gen=null in the registry
# (a from-spec / reused-IP class, NEVER a chip-name literal) AND (b) reused RTL
# is provably present — a staged `input/vendor_rtl/` directory with ≥1 .v/.sv,
# OR the doc carries an honest `fsm_in_staged_rtl: true` flag — AND (c) the
# harvested enum actually exists. §4.05 FAIL-CLOSED: bare_fpga / unknown_protocol
# _class stay strict (rejected before the registry lookup); a from-scratch
# class (deterministic rtl_gen) keeps the ≥2 floor; a reused-IP class with NO
# staged RTL and NO honest flag keeps the floor; n_states==0 with no harvest and
# no honest no-FSM flag still FAILs. No fabrication — the credited states are the
# ones the staged RTL literally enumerates.

# A signal whose type carries the FSM-state enum: a current/next state register.
# Signal-name tokens for a state register. STRONG tokens (the FSM-specific
# current/next-state convention) are accepted on their own; WEAK tokens (a bare
# `_state`/`_cs`/`_ns`, which a non-FSM data signal can also carry — e.g. an
# opcode `req_state`) additionally require a `case (<signal>)` transition before
# the enum is credited as an FSM (adversarial-review #748 hardening).
_FSM_SIGNAL_TOKENS_STRONG = ("_fsm_cs", "_fsm_ns", "_fsm_state", "_fsm")
_FSM_SIGNAL_TOKENS_WEAK = ("_state", "_state_q", "_state_d", "_cs", "_ns")
_FSM_SIGNAL_TOKENS = _FSM_SIGNAL_TOKENS_STRONG + _FSM_SIGNAL_TOKENS_WEAK

import re as _re  # noqa: E402  (module-level, used only by the harvest helper)

# `typedef enum [...] { A, B, C } name_e;` — capture the brace body and the
# typedef name. DOTALL so a multi-line enum body is captured.
_TYPEDEF_ENUM_RE = _re.compile(
    r"typedef\s+enum\b[^\{]*\{(?P<body>[^}]*)\}\s*(?P<tname>[A-Za-z_]\w*)\s*;",
    _re.DOTALL,
)


# Both halves of the reused-IP predicate used to be implemented here — the
# class-registry half as `_class_rtl_gen_null`, the staged-RTL half as
# `_staged_vendor_rtl_text`, whose docstring admitted it "mirrors
# flow_compliance_check._detected_class_rtl_gen_null_and_vendor_rtl's KEY-(a.2)
# vendor-RTL probe". #504 removed the mirror: the predicate lives once, in
# `_reused_ip_predicate`, and this gate reads it. The `bare_fpga` rejection this
# gate applies on top (its floors are PROTOCOL floors — a bare FPGA target has
# no protocol) travels as the explicit `fail_closed` argument, so the difference
# between this caller and the composite one is written at the call site instead
# of being buried in a second copy.
def _class_rtl_gen_null(ic_class: str) -> bool:
    """True iff the registry marks this class with rtl_gen=null (a from-spec /
    reused-IP class — processor_cpu / digital_arithmetic_primitive /
    crypto_accelerator / … — resolved by name OR synonym, NEVER a chip-name
    literal). bare_fpga / unknown_protocol_class are rejected up front
    (fail-closed): an unclassified design earns NO relaxation. Any read/parse
    error → False (fail-closed)."""
    return _reused_ip.class_rtl_gen_null(
        ic_class, fail_closed=_NO_PROTOCOL_FAIL_CLOSED)


#: The staged vendor/reused RTL text harvest — the shared prober, re-exported
#: under this gate's original name so the #748 harvest call sites below read
#: unchanged.
_staged_vendor_rtl_text = _reused_ip.staged_vendor_rtl_text


def _strip_v_comments(src: str) -> str:
    """Remove `//` line and `/* */` block comments (newlines preserved) so a
    commented-out FSM enum is not harvested. chip-AGNOSTIC."""
    src = _re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"),
                  src, flags=_re.S)
    src = _re.sub(r"//[^\n]*", "", src)
    return src


def _harvest_staged_fsm_state_count(rtl_text: str) -> int:
    """Count the FSM states an enum carries when that enum's typedef name is the
    declared type of an FSM-state signal (`*_fsm_cs` / `*_fsm_ns` / `*_state` /
    `*_cs` / `*_ns`). Returns the MAX state count across all such enums (the
    widest single FSM), 0 when no FSM-typed enum is found.

    Strategy (chip-AGNOSTIC grammar, no chip-name literal):
      1. parse every `typedef enum {...} <tname>;` → {tname: n_states};
      2. keep only those <tname> declared on a signal whose identifier matches
         an FSM-state token (so a generic non-FSM enum — e.g. a request-kind
         enum — never inflates the count);
      3. return the max state count among the kept enums.

    n_states for an enum body = number of comma-separated, non-empty members
    (each member may carry `= <value>`; we count the member identifiers).

    Hardening (adversarial-review #748): (a) `//` and `/* */` comments are
    stripped first, so a commented-out / dead FSM is NOT counted; (b) a WEAK
    state-signal name (`_state`/`_cs`/`_ns`) must additionally have a
    `case (<signal>)` transition to confirm it is a real FSM (a generic enum on a
    coincidentally-`_state`-named signal does not count); (c) only enums with
    >=2 states are credited (a degenerate 1-member enum is not a control FSM)."""
    if not isinstance(rtl_text, str) or not rtl_text:
        return 0
    rtl_text = _strip_v_comments(rtl_text)
    enums: dict[str, int] = {}
    for mobj in _TYPEDEF_ENUM_RE.finditer(rtl_text):
        body = mobj.group("body")
        tname = mobj.group("tname")
        members = [seg.strip() for seg in body.split(",")]
        n = sum(1 for seg in members if seg and seg.split("=", 1)[0].strip())
        if n > 0:
            enums[tname] = max(enums.get(tname, 0), n)
    if not enums:
        return 0
    best = 0
    for tname, n_states in enums.items():
        if n_states < 2:
            continue   # a 1-member enum is not a multi-state control FSM
        # Is `tname` declared on at least one FSM-state-named signal?
        # Grammar: `<tname> [#(...)] <ident1>[, <ident2> ...];`
        decl_re = _re.compile(
            r"\b" + _re.escape(tname) + r"\b\s+(?P<ids>[^;{}=]+);")
        fsm_typed = False
        for dm in decl_re.finditer(rtl_text):
            ids = dm.group("ids")
            for ident in _re.split(r"[,\s]+", ids):
                ident = ident.strip()
                low = ident.lower()
                if not ident:
                    continue
                if any(low.endswith(tok) for tok in _FSM_SIGNAL_TOKENS_STRONG):
                    fsm_typed = True       # strong state-register name
                    break
                if any(low.endswith(tok) for tok in _FSM_SIGNAL_TOKENS_WEAK):
                    # a weak name needs a `case (<signal>)` transition to confirm
                    # it really drives an FSM (not a coincidentally-named enum).
                    if _re.search(r"\bcase\s*\(\s*" + _re.escape(ident)
                                  + r"\s*\)", rtl_text, _re.I):
                        fsm_typed = True
                        break
            if fsm_typed:
                break
        if fsm_typed:
            best = max(best, n_states)
    return best


def _l6_staged_fsm_credit(data: dict, project, ic_class: str) -> int:
    """ORGANIC #748 — DOUBLE-KEYED L6 staged-RTL FSM credit. Returns the FSM
    state count harvested from staged vendor RTL (to be credited toward the L6
    floor), or 0 when the escape does not apply.

    Keys (ALL required, fail-closed):
      (a) ic_class has rtl_gen=null in the registry (reused-IP / from-spec
          class; bare_fpga / unknown rejected by _class_rtl_gen_null) AND is
          registry-flagged `sparse_control_timing` (a genuinely-sparse compute /
          CPU class — processor_cpu / digital_arithmetic_primitive /
          crypto_accelerator). #748-reopen §4.05: a non-sparse reused-IP PROTOCOL
          class (digital_cmd_driven / bus_interconnect_protocol /
          serial_peripheral_protocol / bus_peripheral — all rtl_gen=null but
          sparse_control_timing=False, strict l6_min=5) carries a RICH protocol
          state machine and MUST keep the strict floor, so the staged-RTL harvest
          credit must NEVER fire for it (mirrors the L6/L8 floor relaxation, which
          is keyed on _class_sparse_control_timing — NOT _class_rtl_gen_null);
      (b) reused RTL is provably present — a staged input/vendor_rtl/ dir with
          ≥1 .v/.sv file, OR the doc carries an honest `fsm_in_staged_rtl: true`
          flag (the runner's explicit "the FSM lives in staged RTL" signal);
      (c) the staged RTL actually enumerates an FSM-state typedef enum.

    When all hold, return the harvested state count (≥1). Otherwise 0 — the
    plain L6 floor stays in force (no leak: a class without rtl_gen=null or not
    sparse_control_timing, a project with no staged RTL and no honest flag, or
    staged RTL with no FSM-typed enum, earns nothing)."""
    if not (_class_rtl_gen_null(ic_class)
            and _class_sparse_control_timing(ic_class)):
        return 0
    rtl_text = _staged_vendor_rtl_text(project)
    honest_flag = _explicit_true(data.get("fsm_in_staged_rtl"))
    if rtl_text is None and not honest_flag:
        return 0
    if rtl_text is None:
        # honest flag set but no readable staged dir — nothing to harvest;
        # the floor relaxation below (≥1 with a prose state) still applies via
        # the caller, but there is no harvested count to credit here.
        return 0
    return _harvest_staged_fsm_state_count(rtl_text)


def _check_l_doc(layer: int, data: dict,
                 escapes: dict[str, bool] | None = None,
                 ic_class: str = "unknown",
                 project=None) -> tuple[bool, str]:
    """Return (passed, reason). reason is empty when passed.

    Wave 36 (v0.119.68): when `ic_class` indicates the layer is not
    applicable, return (True, "SKIP — not applicable to ic_class=...").
    `escapes` provides three boolean flags read from facts.yaml:
    `no_command_protocol`, `no_fsm`, `no_timing_classification`.
    """
    escapes = escapes or {}

    # Wave 36 — class / escape based SKIP rules.  Bare_fpga / unknown
    # MUST fail-closed (the legacy 13/13 requirement). Only pure_analog
    # auto-skips, and explicit facts.yaml escape booleans skip.
    if ic_class == "pure_analog" and layer in (3, 6, 7, 10):
        return True, ""
    # v0.2.55 — datapath/compute classes (digital_arithmetic_primitive,
    # processor_cpu) have NO command protocol (L3 opcodes) and NO control
    # FSM (L6 states): their behavior is a deterministic data transform whose
    # micro-architecture is delegated to the implementation. The runner's own
    # class config marks command_protocol_applicable=false for these, and
    # the compliance harness SKIPs every other protocol gate for them — so
    # the L3-opcode (≥5) and L6-FSM (≥2) typed-field floors are likewise N/A.
    # Without this, every pure-arithmetic IP (e.g. an spm multiplier) FAILs P0
    # on L3=0-opcodes / L6=0-FSM-states that it legitimately has no source
    # for. chip-AGNOSTIC: keyed on the datapath class, not on any chip.
    # #428 — registry-flag N/A for the OPCODE minimum, DOUBLE-KEYED per the
    # #419 doctrine (class flag AND L-doc evidence, fail-closed): a class
    # with command_protocol_applicable=False + rtl_gen=null has no source
    # for L3 opcodes, but the N/A additionally requires the doc's OWN
    # honest empty record (an explicit `opcodes: []`). A blob-only L3 with
    # NO opcodes key stays a FAIL — extraction failure can degrade class
    # detection toward datapath, and a missing key must never ride that
    # degradation into a silent N/A (the gameable chicken-egg). L6 stays a
    # class-appropriate FLOOR (l6_min=2 below) per the filing — not a skip.
    if _class_no_cmd_protocol(ic_class) and layer == 3:
        ops = data.get("opcodes")
        if isinstance(ops, list) and len(ops) == 0:
            return True, ""
    if escapes.get("no_command_protocol") and layer in (3, 10):
        return True, ""
    if escapes.get("no_fsm") and layer == 6:
        return True, ""
    if escapes.get("no_timing_classification") and layer == 8:
        return True, ""
    # v0.1.88 — L11 (behavioral_sequences + calibration_tables) is N/A when the
    # IC genuinely has NO source for any of them: no command protocol (so no
    # host→device command sequences), no OTP image, and no calibration. A
    # reused-IP CPU SoC (e.g. a RISC-V core whose behavior is firmware-defined,
    # not a chip command protocol; no fuses; no analog trim) meets all three.
    # Honest, narrow N/A — only when the doc itself asserts otp_present=False AND
    # the no_command_protocol escape is set AND no calibration content exists.
    if layer == 11 and escapes.get("no_command_protocol") \
            and data.get("otp_present") is False:
        _cal = (data.get("calibration_tables") or data.get("calibration")
                or data.get("tables"))
        if not (_list_len_of_dicts(_cal) or (isinstance(_cal, dict) and _cal)):
            return True, ""
    typed = _count_typed_fields(data)
    # Wave 35 (v0.119.67) — for layers L1 / L2 / L4 / L7 / L10 /
    # L11 / L13 that fail the simple typed-field count, also expand
    # any list-of-dicts top-level field by its entry count. Earlier
    # the gate counted a 50-entry `pins[]` list as ONE typed field;
    # now we count up to its length. Behavior-based: a richly typed
    # list-of-dict carries far more semantic content than a single
    # scalar.
    if typed < 10 or (layer == 2 and typed < 15):
        bonus = 0
        for k, v in data.items():
            if k in _BOOKKEEPING_FIELDS or _is_blob_field(k):
                continue
            if isinstance(v, list):
                n_entries = _list_len_of_dicts(v)
                if n_entries > 1:
                    bonus += min(n_entries - 1, 30)
        typed = typed + bonus
    if layer == 1:
        if typed < 10:
            return False, (
                f"L1 datasheet must carry ≥10 typed structured fields "
                f"(overview / electrical / pin / package / "
                f"package_dimensions / etc.); have {typed}.")
    elif layer == 2:
        if typed < 15:
            return False, (
                f"L2 FRS must carry ≥15 typed structured fields "
                f"(timing_parameters / clock / power / interface / "
                f"performance / etc.); have {typed}.")
    elif layer == 3:
        opcodes = data.get("opcodes") or data.get("commands")
        n_opcodes = _list_len_of_dicts(opcodes)
        crc_block = data.get("crc_parameters") or data.get("crc")
        crc_ok = isinstance(crc_block, dict) and crc_block
        # Wave 36 (v0.119.68): dynamic threshold — min(5, ceil(0.8 *
        # planned_count)). Reading planned_count from L2.command_count
        # if present, else from the actual list length itself.  This
        # lets a 3-command UART chip pass when it actually has 3
        # opcodes typed.
        import math as _math
        planned = None
        l2_cnt = data.get("command_count")
        if isinstance(l2_cnt, int) and l2_cnt > 0:
            planned = l2_cnt
        elif isinstance(opcodes, list):
            planned = len([x for x in opcodes if isinstance(x, dict)])
        threshold = 5
        if planned is not None and planned > 0:
            threshold = min(5, max(1, _math.ceil(0.8 * planned)))
        if n_opcodes < threshold:
            return False, (
                f"L3 cmd_protocol must carry ≥{threshold} typed opcode "
                f"entries in `opcodes`; have {n_opcodes}. Each entry "
                f"must be a dict (hex/name/payload_bytes/...). Threshold "
                f"is min(5, ceil(0.8 * planned_count)).")
        # v0.2.16 — honest no-CRC escape (completing the set begun by
        # L5.no_analog / L12.no_calibration). A pure-digital management /
        # serial protocol (MDIO, raw shift-register bus, ...) genuinely has
        # NO CRC. ACCEPT a filled crc_parameters OR the doc's OWN explicit
        # `no_crc_parameters_in_input == true` declaration. A bare missing
        # crc_parameters with no explicit no_crc flag still FAILs, and a
        # protocol that genuinely HAS CRC (no_crc==false / filled block)
        # keeps the requirement in force.
        if not crc_ok and not _has_honest_no_crc(data):
            return False, (
                "L3 cmd_protocol must carry a `crc_parameters` (or `crc`) "
                "dict block (polynomial_hex / init_hex / bit_order / ...), "
                "OR declare it has none via an explicit "
                "`no_crc_parameters_in_input: true` flag (the doc's own "
                "honest typed N/A — not a waiver, not a bare missing field).")
    elif layer == 4:
        # v0.1.82 — honest N/A escape, mirroring L5.no_analog /
        # L12.no_calibration. A CPU-core / SoC spec can explicitly declare it
        # has NO SW-visible chip-level register map (control via ISA/CSR or
        # firmware-defined memory-mapping, not a chip register file). When the
        # L4 doc carries `register_map_present: false` (set by phase1 only from
        # an explicit input N/A assertion), the ≥5-entry floor does not apply.
        if data.get("register_map_present") is False \
                or data.get("no_register_map") is True:
            return True, ""
        # #677 — honest-absence `no_*_in_input` MIRROR for the L4 regmap floor,
        # DOUBLE-KEYED per the #428/#419 doctrine (class flag AND the doc's OWN
        # honest declaration, fail-closed). A minimal register-mapped peripheral
        # whose input genuinely carries NO SW-visible register map honestly
        # emits `no_register_map_in_input: true`; combined with a registry-
        # flagged minimal-honest-absence class (bus_peripheral / interconnect /
        # serial peripheral — NARROWER than _class_no_cmd_protocol so a reused-IP
        # processor_cpu still obeys its #641 doctrine) the ≥5-entry floor does
        # not apply. A command/protocol/unknown class, or a doc with no explicit
        # flag, keeps the floor — an empty L4 can never ride this into a pass.
        # (The unconditional register_map_present:false / no_register_map:true
        # escapes above remain the doc's-own-typed-N/A path, like L5.no_analog.)
        if _class_minimal_honest_absence(ic_class) and _has_honest_no_regmap(data):
            return True, ""
        # Wave 32 — L4 owns registers + control_bits + otp_layout.
        # Either ≥5 typed register entries OR ≥5 populated otp_layout
        # sub-fields satisfies the minimum (chip-AGNOSTIC: regmap-only
        # ICs vs OTP-image-only L4 sidecars both PASS).
        # Wave 35 (v0.119.67) — accept `logical_regions[]` /
        # `regions[]` / `memory_map[]` aliases for the OTP-image
        # variant where L4 carries logical sections (ID / IMSN / ASN
        # / LK / ...) instead of registers[].
        regs = (data.get("registers") or data.get("regmap")
                or data.get("register_table") or data.get("register_entries")
                or data.get("logical_regions") or data.get("regions")
                or data.get("memory_map") or data.get("sections"))
        n_regs = _list_len_of_dicts(regs)
        # otp_layout may live at top-level OR nested under L4_REGMAP
        # (the otp-content-gen sidecar shape).
        otp_layout = data.get("otp_layout")
        if otp_layout is None:
            nested = data.get("L4_REGMAP")
            if isinstance(nested, dict):
                otp_layout = nested.get("otp_layout")
        n_otp_subfields = 0
        if isinstance(otp_layout, dict):
            for k, v in otp_layout.items():
                if v in (None, "", [], {}):
                    continue
                n_otp_subfields += 1
        # #428 double-keyed N/A (mirrors the #419 class-skip doctrine):
        # a no-protocol datapath class whose L4 doc HONESTLY records zero
        # registers AND zero otp content has no source for either — switch
        # the minimum to an N/A-SKIPPED-CONDITION. The honest-empty key
        # requirement (an EXPLICIT empty registers-alias list) keeps a
        # blob-only doc with no key at all failing; partial content (1-4
        # entries) keeps the floor — a source exists, so a shortfall is an
        # extraction defect.
        _honest_empty_regs = any(
            isinstance(data.get(k), list) and len(data.get(k)) == 0
            for k in ("registers", "regmap", "register_table",
                      "register_entries", "logical_regions", "regions",
                      "memory_map", "sections"))
        if (max(n_regs, n_otp_subfields) == 0 and _honest_empty_regs
                and _class_no_cmd_protocol(ic_class)):
            return True, ""
        # field (caravel L4 minimal regmap) — COMPLETE minimal-regmap credit,
        # DOUBLE-KEYED per the #428/#419/#677 doctrine (class flag AND a
        # per-doc completeness PROOF, fail-closed). The #677 honest-absence
        # escape (above) covers a peripheral with ZERO regmap; a genuinely
        # minimal peripheral with a COMPLETE-but-small regmap (e.g. a
        # Wishbone-mapped counter = 1 register) is neither zero nor ≥5, and the
        # "1-4 entries = extraction defect" doctrine would wrongly FAIL it.
        # Distinguish a COMPLETE minimal regmap from a dropped-registers
        # extraction defect by PROVING completeness against the INPUT register
        # doc: credit ONLY when (1) the class is a registry-flagged minimal
        # peripheral, (2) the typed regmap is non-empty AND captured EVERY
        # register declared in the input (n_regs ≥ declared ≥ 1), AND (3) the
        # doc carries no real OTP content (the ≥5-otp alternative source is
        # genuinely absent). A partial extraction (n_regs < declared), an empty
        # regmap, a class without the flag, or a doc with real OTP content all
        # keep the ≥5 floor — guard (d) (partial-content-still-FAILs) preserved.
        # chip-AGNOSTIC: registry semantic flag + input-completeness proof, no
        # chip/register-name literal; reads only staged input docs (§4.05).
        if (max(n_regs, n_otp_subfields) < 5
                and n_regs >= 1
                and _class_minimal_honest_absence(ic_class)
                and _l4_otp_layout_has_no_real_content(otp_layout)):
            _declared = _count_input_declared_registers(project)
            if (_declared is not None and _declared >= 1
                    and n_regs >= _declared):
                return True, (
                    f"SKIP — L4 complete minimal regmap: captured "
                    f"n_regs={n_regs} == {_declared} register(s) declared in "
                    f"the input register doc (minimal_honest_absence class, no "
                    f"OTP content); a complete minimal regmap is not an "
                    f"extraction defect.")
        if max(n_regs, n_otp_subfields) < 5:
            return False, (
                f"L4 regmap+otp_layout must carry ≥5 typed register "
                f"entries OR ≥5 populated otp_layout sub-fields "
                f"(read_map / write_map / lockbits / otp_ip_specs / "
                f"trim_registers / mask_sources); have "
                f"registers={n_regs}, otp_layout_subfields="
                f"{n_otp_subfields}.")
    elif layer == 5:
        # No-analog escape (digital-only chip): boolean field.
        if data.get("no_analog") is True:
            return True, ""
        blocks = (data.get("analog_blocks") or data.get("blocks")
                  or data.get("adi_blocks"))
        n_blocks = _list_len_of_dicts(blocks)
        # ORGANIC #676 PARITY — a POSITIVELY non-analog class whose only
        # declared blocks are phantom `low_confidence` keyword hits is N/A
        # here, exactly as it already is for the 3 analog P0 gates #676
        # covered. Without this the floor is unsatisfiable for such a class:
        # ≥3 analog blocks is impossible for a design with no analog, and the
        # `no_analog: true` escape is unavailable precisely BECAUSE the
        # harvester set it false off the phantom hit. Fail-closed and
        # no-leak — see `_class_non_analog_phantom_only`.
        if _class_non_analog_phantom_only(ic_class, blocks):
            return True, ""
        # ORGANIC #634 — IC-class-aware analog-block floor. The ≥3 default is
        # tuned for a multi-block analog SYSTEM (multi-rail PMIC / analog front-
        # end). A data-converter / mixed-signal class (delta-sigma / SAR /
        # pipeline ADC, DAC) legitimately carries a SMALL fixed block set — a
        # modulator + on-chip regulator/reference = 2 typed blocks — and would
        # otherwise FAIL with `no_analog` (which is FALSE — it IS analog) as the
        # only escape. Relax to ≥2 for classes the registry flags
        # `sparse_analog_block_set`. NOT a skip: a REAL floor — an empty /
        # 0-block / 1-block doc still FAILs, so an under-populated doc can never
        # ride this into a pass. Registry-driven semantic flag (chip-AGNOSTIC);
        # a multi-block analog system is NOT flagged and keeps the strict ≥3.
        l5_min = 2 if _class_sparse_analog_blocks(ic_class) else 3
        if n_blocks < l5_min:
            return False, (
                f"L5 adi_spec must carry ≥{l5_min} typed analog blocks (or "
                f"set `no_analog: true`); have {n_blocks}.")
    elif layer == 6:
        # v0.1.83 — IC-class-aware FSM floor. The ≥5 default is tuned for
        # command/protocol chips with explicit multi-state control FSMs. A pure
        # datapath/compute primitive (multiplier, hash, ALU) or a CPU-SoC
        # integration spec deliberately delegates the internal micro-
        # architecture FSM to the implementation ("round impl 由 Plugin 自選")
        # and realistically documents a minimal control FSM (idle/active/done).
        # Relax to ≥2 for those classes — a real floor, not a skip. Command-
        # driven / protocol / unknown classes keep ≥5 (fail-closed).
        # ORGANIC #605 — key the relaxation on the registry-driven
        # `sparse_control_timing` SEMANTIC flag (not the stale hardcoded
        # `_DATAPATH_COMPUTE_CLASSES` literal, which recognised only 2 of the
        # genuinely-sparse compute classes — a crypto_accelerator was wrongly
        # inheriting the strict 5/10 protocol-genre floor it has no source to
        # populate). NOTE: deliberately NOT `_class_no_cmd_protocol` — that
        # predicate also matches bus/serial PROTOCOL classes, which carry a
        # rich FSM/timing spec and must keep the strict floor
        # (test_protocol_stays_strict). bare_fpga / unknown stay fail-closed.
        l6_min = 2 if _class_sparse_control_timing(ic_class) else 5
        states = (data.get("fsm_states") or data.get("states")
                  or data.get("state_table"))
        n_states = _list_len_of_dicts(states)
        # #462 — honest no-FSM N/A escape (completing the set begun by
        # L5.no_analog / L12.no_calibration; same shape as the L3 no-CRC /
        # L11 no-OTP escapes). A pure datapath/compute primitive whose input
        # spec explicitly forbids a control FSM (fsm_states:[] AND an explicit
        # no_fsm_in_input:true / no_fsm:true declaration) has no source for FSM
        # states — phase1 cannot synthesise an FSM the spec does not contain.
        # DOUBLE-KEYED per the #428/#419 doctrine (class flag AND the doc's OWN
        # honest declaration, fail-closed): the N/A fires ONLY when (1) the IC
        # class is a no-command-protocol datapath/compute class AND (2) the doc
        # carries zero typed FSM states AND (3) the doc carries an explicit
        # honest no-FSM flag. A doc with a partial FSM (1+ states), or with no
        # explicit flag, or in a command/protocol/unknown class, keeps the
        # floor — a real FSM must still hit the L6 floor (corpus-sweep guard).
        if (n_states == 0
                and _class_no_cmd_protocol(ic_class)
                and _has_honest_no_fsm(data)):
            return True, ("SKIP — L6 FSM floor N/A: ic_class="
                          f"{ic_class} (no-command-protocol datapath/compute) "
                          "AND the doc honestly declares no_fsm_in_input with "
                          "zero typed FSM states (the spec forbids a control "
                          "FSM; no source to synthesise one).")
        # Wave 35 (v0.119.67) — accept `fsms: [{name, states[]}, ...]`
        # multi-FSM container schema. Sum total state count across
        # all enumerated FSMs.
        if n_states < l6_min:
            fsms = data.get("fsms")
            if isinstance(fsms, list):
                total_states = 0
                for f in fsms:
                    if isinstance(f, dict):
                        total_states += _list_len_of_dicts(f.get("states"))
                if total_states > n_states:
                    n_states = total_states
        # ORGANIC #748 — reused-IP staged-RTL FSM credit (n_states==1 dead
        # zone). For a reused-IP sparse_control_timing class (l6_min=2) whose
        # multi-state control FSM lives in STAGED vendor RTL, the doc prose
        # honestly names ≤1 state, leaving an unsatisfiable floor with no
        # escape (the #462 no-FSM escape needs n_states==0, the ≥2 floor needs
        # ≥2, and the `l_doc_structured_*` prefix forbids any waiver). When the
        # DOUBLE-KEY holds — (1) the doc HONESTLY extracts ≥1 prose FSM state
        # (its own structured signal that an FSM exists; an empty L6 with
        # n_states==0 does NOT take this path, it must FAIL or use the #462
        # no-FSM escape), AND (2) the class is registry rtl_gen=null, AND
        # (3) staged vendor RTL with an FSM-typed `typedef enum {...} ..._e;`
        # is present (or the doc carries an honest `fsm_in_staged_rtl: true`
        # flag) — credit the harvested state count. The FSM provably exists in
        # the staged RTL; phase-1 prose just under-counts it.
        # #748-reopen §4.05: ALSO key on _class_sparse_control_timing — a
        # non-sparse reused-IP PROTOCOL class (digital_cmd_driven /
        # bus_interconnect_protocol / serial_peripheral_protocol / bus_peripheral,
        # all rtl_gen=null but sparse_control_timing=False, strict l6_min=5) has a
        # RICH protocol FSM spec and MUST keep the strict floor; only genuinely-
        # sparse compute/CPU classes (processor_cpu / digital_arithmetic_primitive
        # / crypto_accelerator) earn the staged-RTL harvest credit. Mirrors the
        # l6_min/l8_min relaxation above, which is likewise keyed on
        # _class_sparse_control_timing — NOT _class_rtl_gen_null. Both keys are
        # ALSO enforced inside _l6_staged_fsm_credit (defense-in-depth) so neither
        # path leaks; the option-(ii) flag-only relaxation below is gated here.
        if (1 <= n_states < l6_min
                and _class_rtl_gen_null(ic_class)
                and _class_sparse_control_timing(ic_class)):
            harvested = _l6_staged_fsm_credit(data, project, ic_class)
            if harvested > n_states:
                n_states = harvested
            # Option (ii) — relax the floor to ≥1 when staged RTL CONFIRMS an
            # FSM exists but the harvester could not parse a typedef-enum out
            # of it (a one-hot localparam / non-enum FSM). "Confirms" means the
            # harvester credited ≥1 state OR the doc carries the explicit honest
            # `fsm_in_staged_rtl: true` flag — NOT the mere presence of a vendor
            # file (a generic non-FSM enum or an unrelated .sv must NOT relax
            # the floor). Combined with the n_states>=1 gate above this keeps an
            # empty L6 strict.
            if (n_states < l6_min
                    and (harvested >= 1
                         or _explicit_true(data.get("fsm_in_staged_rtl")))):
                l6_min = 1
        if n_states < l6_min:
            return False, (
                f"L6 control_logic must carry ≥{l6_min} typed FSM states in "
                f"`fsm_states` (each with name/transitions/actions); "
                f"have {n_states}.")
    elif layer == 7:
        scenarios = (data.get("test_scenarios") or data.get("scenarios")
                     or data.get("test_debug_cases"))
        n_scen = _list_len_of_dicts(scenarios)
        # Wave 35 (v0.119.67) — accept `test_modes[]` /
        # `debug_observability[]` / `verification_strategy[]` /
        # `debug_signals[]` aliases. L7 test+debug semantically
        # covers all of those buckets; sum the typed entries.
        if n_scen < 3:
            for k in ("test_modes", "debug_observability",
                     "verification_strategy", "debug_signals",
                     "debug_modes", "test_plans"):
                seq = data.get(k)
                if isinstance(seq, list):
                    n_scen += _list_len_of_dicts(seq)
        # Allow non-dict entry lists too (strings counted at 0.5).
        if n_scen < 3:
            extra = 0
            for k in ("test_modes", "debug_observability",
                     "verification_strategy", "test_scenarios"):
                seq = data.get(k)
                if isinstance(seq, list):
                    extra += sum(1 for x in seq if x)
            if extra >= 3:
                n_scen = extra
        # #677 — honest-absence N/A escape for L7 (completing the set begun by
        # L5.no_analog / L12.no_calibration; same shape as the L3 no-CRC / L6
        # no-FSM / L11 no-OTP / L13 no-lab escapes). A minimal register-mapped
        # peripheral (bus_peripheral) genuinely carries NO chip-level test /
        # verification / debug scenarios in its input spec — its verification is
        # the integrator's DV job, not the IP datasheet. DOUBLE-KEYED per the
        # #428/#419 doctrine (class flag AND the doc's OWN honest declaration,
        # fail-closed): the N/A fires ONLY when (1) the IC class is a registry-
        # flagged minimal-honest-absence class (NARROWER than
        # _class_no_cmd_protocol so a reused-IP processor_cpu / crypto class is
        # NOT silenced here; bare_fpga / unknown stay fail-closed via
        # _NO_PROTOCOL_FAIL_CLOSED) AND (2) the doc carries zero typed scenarios
        # AND (3) the doc carries an explicit honest no-test-debug flag
        # (no_test_scenarios_in_input / no_verification_strategy_in_input /
        # no_test_modes_in_input / no_test_debug_in_input == true). A doc with
        # ANY harvested content (n_scen ≥ 1), or no explicit flag, or in a
        # command/protocol/unknown class, keeps the floor — the #670/#641
        # harvesters still rescue docs that DO carry content, and a rich class
        # that SHOULD have scenarios but emits an empty list without an honest
        # flag still FAILs (field agent corpus-sweep guard).
        if (n_scen == 0
                and _class_minimal_honest_absence(ic_class)
                and _has_honest_no_test_debug(data)):
            return True, ("SKIP — L7 test/debug floor N/A: ic_class="
                          f"{ic_class} (no-command-protocol peripheral) AND the "
                          "doc honestly declares no test/verification scenarios "
                          "in the input with zero typed scenarios (verification "
                          "is the integrator's DV job; no source to synthesise).")
        if n_scen < 3:
            return False, (
                f"L7 test_debug must carry ≥3 typed test scenarios "
                f"(or test_modes / debug_observability / "
                f"verification_strategy entries); have {n_scen}.")
    elif layer == 8:
        # Timing constants — gather from common fields.
        n = 0
        tp = data.get("timing_parameters")
        if isinstance(tp, dict):
            n += sum(1 for v in tp.values() if v not in (None, "", [], {}))
        rct = data.get("rx_classifier_ticks")
        if isinstance(rct, dict):
            n += sum(1 for v in rct.values() if v not in (None, "", [], {}))
        # Wave 35 (v0.119.67) — accept the typed-list schema
        # `constants: [{"name": ..., "value": ..., "type": ...}, ...]`
        # as a canonical L8 form. This is the schema emitted by
        # rtl-constants-gen / timing-waveform-gen agents that prefer
        # a list-of-dicts over flat scalars; each entry counts as one
        # typed timing constant.
        # ORGANIC #641 — credit a populated typed waveform / clock-domain
        # list-of-dicts. The reused-IP CPU / datapath classes document
        # their timing as WaveDrom `waveforms[]` and a typed
        # `clock_domains[]` / `clocks[]` list (freq_hz / period_ns /
        # domain_kind) rather than the protocol-chip scalar/dict timing
        # forms. Each is a LIST, so the dict/scalar loop below skips it and
        # it is absent from the legacy gather set — the genuine timing
        # content was invisible and the doc scored only its doc_class +
        # ic_name strings. Count each populated entry as one typed timing
        # constant (chip-AGNOSTIC: keyed on the field NAME, not any chip).
        for list_key in ("constants", "timing_constants",
                         "rtl_constants", "tx_timing", "rx_timing",
                         "vectors", "crc_vectors",
                         "waveforms", "clock_domains", "clocks"):
            seq = data.get(list_key)
            if isinstance(seq, list):
                n += _list_len_of_dicts(seq)
        # Wave 35 (v0.119.67) — accept ANY typed dict-valued
        # top-level field (each sub-key inside the dict counts as one
        # constant). Catches the L8_TIMING_WAVEFORM sidecar which uses
        # `clock{}`, `rx_classifier{}`, `tx_widths_ticks{}`,
        # `tx_widths_us{}`, `turnaround_tSRS{}`, `wake_timing{}`
        # instead of the canonical timing_parameters/rx_classifier_ticks
        # field names.
        for k, v in data.items():
            if k in _BOOKKEEPING_FIELDS or _is_blob_field(k):
                continue
            if k in ("timing_parameters", "rx_classifier_ticks"):
                continue
            if isinstance(v, dict):
                n += sum(1 for vv in v.values()
                         if vv not in (None, "", [], {}))
            elif isinstance(v, (int, float, str)) and v not in (None, ""):
                n += 1
        # v0.1.83 — IC-class-aware timing floor. The ≥10 default suits a
        # protocol chip with a rich timing-waveform table (bit periods,
        # classifier ticks, turnaround windows). A datapath/compute primitive
        # or CPU-SoC documents a handful of timing facts (clock period, cycle
        # count, latency); relax to ≥3 for those classes. Protocol / command /
        # unknown classes keep ≥10 (fail-closed).
        # ORGANIC #605 — registry-driven `sparse_control_timing` flag (see the
        # L6 note above); NOT `_class_no_cmd_protocol` (protocol classes keep
        # the strict ≥10 floor). bare_fpga / unknown stay fail-closed.
        l8_min = 3 if _class_sparse_control_timing(ic_class) else 10
        # field (caravel L8 minimal timing) — a genuinely MINIMAL register-
        # mapped peripheral documents only a handful of timing facts (a single
        # clock + bus-ack latency), so the sparse ≥3 floor fits, not the
        # protocol-genre ≥10. Key this on an INSTANCE-level minimality PROOF —
        # a minimal_honest_absence_ok class whose INPUT declares a small,
        # COMPLETE register map (1-4 registers) — NOT on the class-wide
        # `sparse_control_timing` predicate (which stays False for bus_peripheral
        # per #748r2). This deliberately does NOT relax a wire-level
        # bus_interconnect_protocol (no register map → declared is None → stays
        # ≥10, so test_protocol_stays_strict holds) nor a rich (≥5-register)
        # peripheral (stays ≥10). Non-vacuous: ≥3 is a REAL floor (empty / <3
        # typed timing still FAILs). chip-AGNOSTIC: registry semantic flag +
        # input-completeness proof, no chip literal.
        if l8_min > 3 and _class_minimal_honest_absence(ic_class):
            _decl_regs = _count_input_declared_registers(project)
            if _decl_regs is not None and 1 <= _decl_regs < 5:
                l8_min = 3
        if n < l8_min:
            return False, (
                f"L8 timing_waveform must carry ≥{l8_min} typed timing "
                f"constants (timing_parameters dict + rx_classifier_ticks "
                f"dict + constants[] list-of-dicts + typed-dict sidecar "
                f"sections (clock{{}}/wake_timing{{}}/etc) + scalar "
                f"tSRS_min_us / wake_pulse_us / etc.); have {n}.")
    elif layer == 9:
        n = 0
        if isinstance(data.get("top_module"), str) and data["top_module"]:
            n += 1
        fsm_states = data.get("fsm_states") or data.get("states")
        if _list_len_of_dicts(fsm_states) > 0:
            n += 1
        ports = (data.get("ports") or data.get("port_list")
                 or data.get("top_ports"))
        if _list_len_of_dicts(ports) > 0 or (
                isinstance(ports, list) and ports):
            n += 1
        # Wave 35 (v0.119.67) — accept `submodules[]` /
        # `submodule_instances[]` / `instance_table[]` /
        # `top_internal_wires[]` as alternative typed structural
        # fields. Integration specs commonly enumerate submodules
        # rather than embed a full FSM duplication.
        for k in ("submodules", "submodule_instances",
                  "instance_table", "top_internal_wires",
                  "internal_wires"):
            v = data.get(k)
            if isinstance(v, list) and v:
                n += 1
        if n < 3:
            # #462 — flat single-module N/A on structural-fact grounds. A
            # legitimate flat primitive (e.g. a combinational/datapath block
            # with no internal hierarchy and no control FSM) has submodules=[]
            # by design: enumerating submodules / internal wires / a separate
            # FSM table would be a fabrication. Such a design's structure is
            # FULLY described by a named top_module + a complete top_ports list.
            # When the doc HONESTLY records (1) an explicit empty submodules
            # list AND (2) a complete top-module port list (≥2 ports, i.e. at
            # least one input and one output worth of structure) AND (3) a named
            # top_module, the L9 structural floor is satisfied on structural-
            # fact grounds — the floor is met by what the structure IS, not by
            # padding it with absent hierarchy. A MULTI-module design (non-empty
            # submodules) does NOT take this path and must still reach ≥3 typed
            # structural fields (corpus-sweep guard).
            _ports = (data.get("top_ports") or data.get("ports")
                      or data.get("port_list"))
            _n_ports = (_list_len_of_dicts(_ports)
                        if isinstance(_ports, list) else 0)
            if _n_ports == 0 and isinstance(_ports, list):
                # port entries may be plain scalars/strings, not dicts
                _n_ports = sum(1 for p in _ports if p not in (None, "", {}, []))
            _has_top = (isinstance(data.get("top_module"), str)
                        and bool(data.get("top_module")))
            _submods_explicit_empty = any(
                isinstance(data.get(k), list) and len(data.get(k)) == 0
                for k in ("submodules", "submodule_instances",
                          "instance_table"))
            if _has_top and _submods_explicit_empty and _n_ports >= 2:
                return True, (
                    "SKIP — L9 flat single-module structure: explicit empty "
                    "submodules[] AND a complete top_ports list "
                    f"({_n_ports} ports) AND a named top_module fully describe "
                    "the structure of a flat primitive; the structural floor "
                    "is met on structural-fact grounds (no internal hierarchy "
                    "to enumerate — padding would be a fabrication).")
            return False, (
                f"L9 integration_spec must carry ≥3 typed structural "
                f"fields among (top_module string, fsm_states[], "
                f"port list, submodules[], internal_wires[]); have {n}.")
    elif layer == 10:
        cases = (data.get("test_cases") or data.get("cases")
                 or data.get("vectors"))
        n_cases = _list_len_of_dicts(cases)
        # ORGANIC #641 — honest bring-up-sequence credit for reused-IP /
        # no-command-protocol classes. A reused-IP CPU core (RISC-V SoC,
        # firmware-defined behavior) carries NO chip-level command/test
        # vectors in its input spec — it honestly declares
        # `no_test_cases_in_input: true` and documents its power-on
        # bring-up as a typed `bring_up_sequence[]` instead. DOUBLE-KEYED
        # per the #428/#419 doctrine (class flag AND the doc's OWN honest
        # declaration, fail-closed): the bring-up entries count toward the
        # floor ONLY when (1) the IC class is a no-command-protocol class
        # (bare_fpga / unknown stay fail-closed via _NO_PROTOCOL_FAIL_CLOSED)
        # AND (2) the doc carries an EXPLICIT no_test_cases_in_input == true.
        # A doc with no_test_cases_in_input absent/false, or an empty
        # bring_up_sequence, or a command/protocol/unknown class, keeps the
        # plain floor — an empty doc can never ride this into a pass.
        if (n_cases < (2 if _class_no_cmd_protocol(ic_class) else 5)
                and _class_no_cmd_protocol(ic_class)
                and _explicit_true(data.get("no_test_cases_in_input"))):
            bus = (data.get("bring_up_sequence")
                   or data.get("bringup_sequence"))
            n_cases += _list_len_of_dicts(bus)
        # #677 — ORTHOGONAL minimal-honest-absence N/A escape for L10. The #641
        # path above HARVESTS a populated bring_up_sequence; a genuinely minimal
        # register-mapped peripheral (bus_peripheral) has NOTHING to harvest yet
        # honestly declares `no_test_cases_in_input: true` — that honest minimal
        # doc would still FAIL the floor. DOUBLE-KEYED per the #428/#419 doctrine
        # (class flag AND the doc's OWN honest declaration, fail-closed): fires
        # ONLY when (1) the IC class is a registry-flagged minimal-honest-absence
        # class — DELIBERATELY NARROWER than _class_no_cmd_protocol so a reused-IP
        # processor_cpu still obeys its #641 doctrine (empty bring-up + the flag
        # must still FAIL); bare_fpga / unknown stay fail-closed — AND (2) AFTER
        # the #641 harvest there are still zero typed cases AND (3) the doc
        # carries an explicit honest `no_test_cases_in_input: true`. A doc with
        # ANY harvested/typed case, or no explicit flag, or in a command/
        # protocol/unknown class, keeps the floor — an empty L10 in a rich class
        # without an honest flag still FAILs (field agent corpus-sweep guard).
        if (n_cases == 0
                and _class_minimal_honest_absence(ic_class)
                and _has_honest_no_test_cases(data)):
            return True, ("SKIP — L10 test-case floor N/A: ic_class="
                          f"{ic_class} (no-command-protocol peripheral) AND the "
                          "doc honestly declares no_test_cases_in_input with "
                          "zero typed cases and nothing to harvest (no chip-"
                          "level test vectors in the input spec).")
        # #428 — class-appropriate floor: a no-protocol datapath primitive
        # has no command sequences to enumerate, so its structured test-case
        # floor falls back to ≥2 (a real floor, not a skip).
        l10_min = 2 if _class_no_cmd_protocol(ic_class) else 5
        if n_cases < l10_min:
            return False, (
                f"L10 test_cases must carry ≥{l10_min} typed test cases; "
                f"have {n_cases}.")
    elif layer == 11:
        # Wave 32 — L11 jointly owns behavioral_sequences and
        # calibration_tables (calibration-gen + behavioral-sequences-gen).
        # Accept ≥3 typed entries across either field. Legacy aliases
        # (`sequences`, `otp_table`) preserved for backwards-compat.
        seqs = (data.get("behavioral_sequences")
                or data.get("sequences"))
        n_seqs = _list_len_of_dicts(seqs)
        cal = data.get("calibration_tables")
        if isinstance(cal, list):
            n_cal = _list_len_of_dicts(cal)
        elif isinstance(cal, dict):
            n_cal = sum(1 for v in cal.values()
                        if v not in (None, "", [], {}))
        else:
            n_cal = 0
        # Wave 32 — `tables` (legacy calibration shape from
        # calibration-gen v0.119.29) accepted as alias.
        if n_cal == 0:
            tables = data.get("tables")
            if isinstance(tables, dict):
                n_cal = sum(1 for v in tables.values()
                            if v not in (None, "", [], {}))
        # Legacy OTP-on-L11 corpus (pre-Wave 32) accepted as alias —
        # FAILing those projects retroactively would break v0.119.57
        # demo replays. Wave 32 going-forward decree is in SKILL.md.
        otp = data.get("otp_table")
        n_otp = _list_len_of_dicts(otp) if isinstance(otp, list) \
            else (sum(1 for v in (otp or {}).values()
                      if v not in (None, "", [], {}))
                  if isinstance(otp, dict) else 0)
        # Wave 35 (v0.119.67) — accept `fields{}` (OTP-fields
        # dict-by-region: ID/IMSN/ASN/...) as an alternative to
        # `otp_table[]`. Each populated region key counts as one
        # typed entry.
        otp_fields = data.get("fields")
        n_otp_fields = 0
        if isinstance(otp_fields, dict):
            n_otp_fields = sum(1 for v in otp_fields.values()
                               if v not in (None, "", [], {}))
        elif isinstance(otp_fields, list):
            n_otp_fields = _list_len_of_dicts(otp_fields)
        best = max(n_seqs, n_cal, n_otp, n_otp_fields)
        # v0.2.16 — honest no-OTP escape, TIGHTENED v0.2.19. The escape requires
        # an EXPLICIT typed no-OTP declaration (no_otp_fsm_in_input: true /
        # no_otp*: true / applicable: false) — a BARE `otp_present: false` is NOT
        # sufficient on its own, because L11 jointly owns behavioral_sequences +
        # calibration_tables too: a doc that merely lacks OTP but is otherwise
        # expected to carry behavioral/calibration content must still meet the
        # ≥3 floor. Protocol controllers (mdio/espi/usb_pd) carry an explicit
        # no_otp_fsm_in_input flag (their behavioral sequences live in L12), so
        # they pass; a bare otp_present:false with empty content fails.
        if best < 3 and not _has_explicit_no_otp_flag(data):
            return False, (
                f"L11 must carry ≥3 typed entries across "
                f"`behavioral_sequences` + `calibration_tables` "
                f"(Wave 32 joint ownership), OR declare it has no OTP fuse "
                f"content via an explicit honest signal (otp_present: false / "
                f"applicable: false / no_otp_fsm_in_input: true); have "
                f"behavioral_sequences={n_seqs}, "
                f"calibration_tables={n_cal} (legacy otp_table={n_otp}).")
    elif layer == 12:
        if data.get("no_calibration") is True:
            return True, ""
        # Wave 35 (v0.119.67) — accept `sequences[]` /
        # `behavioral_sequences[]` for projects that emit behavioral
        # sequences in L12 instead of L11 (or alongside). Each
        # populated typed entry counts.
        cal = (data.get("calibration_steps")
               or data.get("calibration_routine") or data.get("steps")
               or data.get("calibration") or data.get("sequences")
               or data.get("behavioral_sequences"))
        ok = (_list_len_of_dicts(cal) > 0
              or (isinstance(cal, dict) and cal))
        # ORGANIC #641 — honest no-behavioral / no-calibration escape for
        # reused-IP / no-command-protocol classes (mirrors the existing
        # L11 reused-IP-CPU N/A escape). A reused-IP CPU core honestly
        # carries NO behavioral/calibration content: it emits
        # `no_behavioral_sequences_in_input: true` (the runner's honest
        # "no behavioral sequences in the input doc" signal) with
        # `no_calibration: false`, so neither legacy escape fires. Treat
        # the explicit no-behavioral declaration + a genuinely EMPTY
        # calibration set as equivalent to no_calibration:true. DOUBLE-KEYED
        # per the #428/#419 doctrine (class flag AND the doc's OWN honest
        # declaration, fail-closed): fires ONLY when (1) the IC class is a
        # no-command-protocol class (bare_fpga / unknown stay fail-closed)
        # AND (2) the doc carries an EXPLICIT no_behavioral_sequences_in_input
        # == true AND (3) there is genuinely no calibration content. A doc
        # with calibration content present, or no explicit flag, or a
        # command/protocol/unknown class, keeps the ≥1 floor — no
        # fabrication, no empty-doc leak.
        if (not ok
                and _class_no_cmd_protocol(ic_class)
                and _explicit_true(
                    data.get("no_behavioral_sequences_in_input"))):
            return True, ""
        if not ok:
            return False, (
                "L12 calibration must carry ≥1 typed calibration field "
                "(or sequences[] / behavioral_sequences[]; or set "
                "`no_calibration: true`).")
    elif layer == 13:
        cases = (data.get("test_cases") or data.get("lab_cases")
                 or data.get("cases"))
        n_cases = _list_len_of_dicts(cases)
        # Wave 35 (v0.119.67) — accept `calibration_steps[]` /
        # `lab_equipment[]` / `rig_pin_assignments{}` aliases. L13 in
        # the lab_calibration form documents lab-bench setup +
        # calibration steps rather than abstract test_cases.
        if n_cases < 5:
            for k in ("calibration_steps", "calibration",
                     "calibration_routine", "lab_equipment",
                     "lab_steps"):
                seq = data.get(k)
                if isinstance(seq, list):
                    n_cases += _list_len_of_dicts(seq)
            rpa = data.get("rig_pin_assignments")
            if isinstance(rpa, dict):
                n_cases += sum(1 for v in rpa.values()
                               if v not in (None, "", [], {}))
        # v0.2.16 — honest no-lab-calibration escape (completing the set begun
        # by L5.no_analog / L12.no_calibration). A purely-digital protocol IC
        # genuinely has NO on-chip / lab-bench calibration. ACCEPT the typed
        # cases OR the doc's OWN explicit honest no-lab signal already emitted
        # by the runner (lab_calibration_present==false / applicable==false).
        # Guarded: only an explicit False / explicit True no_lab flag counts —
        # a bare missing/empty field never does.
        # #428 — same class-appropriate floor as L10 for no-protocol classes.
        l13_min = 2 if _class_no_cmd_protocol(ic_class) else 5
        if n_cases < l13_min and not _has_honest_no_lab(data):
            return False, (
                f"L13 lab_calibration / test_cases must carry ≥{l13_min} typed "
                f"cases (or calibration_steps[] / lab_equipment[] / "
                f"rig_pin_assignments{{}} entries), OR declare it has no lab "
                f"calibration via an explicit honest signal "
                f"(lab_calibration_present: false / applicable: false); "
                f"have {n_cases}.")
    else:
        return True, ""
    return True, ""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pos = [a for a in argv if not a.startswith("--")]
    if not pos:
        print("Usage: l_doc_structured_field_count_check.py <project_dir>")
        return 2
    project = Path(pos[0]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 2
    base = _pl.generated_docs_dir(project)
    if not base.is_dir():
        # Wave 31 — fail-closed when input/docs/ has vendor docs.
        in_docs = project / "input" / "docs"
        if in_docs.is_dir() and any(in_docs.iterdir()):
            print("FAIL — generated_docs/ is missing while input/docs/ "
                  "has vendor docs. Phase 1 (doc-extraction) was skipped.")
            return 1
        print("SKIP — no generated_docs/ and no input/docs/ "
              "(chip-agnostic silent-skip)")
        return 2
    l_files = sorted(base.glob("L*.json"))
    if not l_files:
        in_docs = project / "input" / "docs"
        if in_docs.is_dir() and any(in_docs.iterdir()):
            print("FAIL — no L*.json under generated_docs/ while "
                  "input/docs/ has vendor docs.")
            return 1
        print("SKIP — no L*.json under generated_docs/")
        return 2

    # Wave 36 (v0.119.68) — IC class + facts.yaml escape booleans.
    ic_class = "unknown"
    if detect_ic_class is not None:
        try:
            profile = detect_ic_class(project)
            ic_class = profile.get("ic_class", "unknown")
            # Wave 36 — auto-escapes ONLY for classes where the
            # absence of commands / FSM is *known* (pure_analog /
            # bare_fpga). For digital_cmd_driven / mixed_signal_otp /
            # aid_class_half_duplex / unknown we still require a
            # facts.yaml escape, otherwise we'd wrongly silence the
            # gate when L3 / L6 are simply missing-data bugs.
            if ic_class in ("pure_analog",):
                auto_escapes = {
                    "no_command_protocol": True,
                    "no_fsm": True,
                    "no_timing_classification": False,
                }
            else:
                auto_escapes = {}
        except Exception:
            auto_escapes = {}
    else:
        auto_escapes = {}
    user_escapes = _facts_yaml_escape_flags(project)
    escapes = {**auto_escapes, **{k: v for k, v in user_escapes.items() if v}}

    # ORGANIC #706 — load the AI deep-review patches sidecar ONCE (mirrors the
    # sibling completeness gate). Merged per-layer (fail-closed) before counting.
    sidecar = _load_field_count_sidecar(project)

    fails: list[str] = []
    passed: list[str] = []
    for lp in l_files:
        layer = _detect_l_layer(lp.name)
        if layer is None:
            continue
        try:
            data = json.loads(lp.read_text())
        except Exception as e:
            fails.append(f"{lp.name}: parse error: {e}")
            continue
        # ORGANIC #706 — credit AI-deep-review-recovered, doc-traceable typed
        # fields (sidecar) toward this layer's count floor, fail-closed.
        _merge_sidecar_for_layer(layer, data, sidecar)
        ok, reason = _check_l_doc(layer, data,
                                  escapes=escapes, ic_class=ic_class,
                                  project=project)
        if ok:
            passed.append(lp.name)
        else:
            fails.append(f"{lp.name}: {reason}")

    if not fails:
        print(f"PASS — all {len(passed)} L doc(s) carry the required "
              f"number of typed structured fields (Wave 31/32).")
        return 0
    print(f"FAIL — Wave 31/32 (v0.119.64): {len(fails)} L doc(s) "
          f"carry fewer typed structured fields than required:")
    for line in fails:
        print(f"  - {line}")
    print()
    print("Wave 31 — extraction MUST emit typed structured fields, "
          "not raw blobs. NO waiver allowed (forbidden-waiver list in "
          "phase1_no_waivers_used_check is extended to include the "
          "prefix `l_doc_structured_*`).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
