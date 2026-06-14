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
# own).
_BOOKKEEPING_FIELDS = frozenset({
    "schema_version", "layer", "source_files",
    "extraction_evidence",
})


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


def _check_l_doc(layer: int, data: dict,
                 escapes: dict[str, bool] | None = None,
                 ic_class: str = "unknown") -> tuple[bool, str]:
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
        ok, reason = _check_l_doc(layer, data,
                                  escapes=escapes, ic_class=ic_class)
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
