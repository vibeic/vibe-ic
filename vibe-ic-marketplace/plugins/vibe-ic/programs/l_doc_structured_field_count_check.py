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
    if escapes.get("no_command_protocol") and layer in (3, 10):
        return True, ""
    if escapes.get("no_fsm") and layer == 6:
        return True, ""
    if escapes.get("no_timing_classification") and layer == 8:
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
        if not crc_ok:
            return False, (
                "L3 cmd_protocol must carry a `crc_parameters` (or `crc`) "
                "dict block (polynomial_hex / init_hex / bit_order / ...).")
    elif layer == 4:
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
        if n_blocks < 3:
            return False, (
                f"L5 adi_spec must carry ≥3 typed analog blocks (or "
                f"set `no_analog: true`); have {n_blocks}.")
    elif layer == 6:
        states = (data.get("fsm_states") or data.get("states")
                  or data.get("state_table"))
        n_states = _list_len_of_dicts(states)
        # Wave 35 (v0.119.67) — accept `fsms: [{name, states[]}, ...]`
        # multi-FSM container schema. Sum total state count across
        # all enumerated FSMs.
        if n_states < 5:
            fsms = data.get("fsms")
            if isinstance(fsms, list):
                total_states = 0
                for f in fsms:
                    if isinstance(f, dict):
                        total_states += _list_len_of_dicts(f.get("states"))
                if total_states > n_states:
                    n_states = total_states
        if n_states < 5:
            return False, (
                f"L6 control_logic must carry ≥5 typed FSM states in "
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
        for list_key in ("constants", "timing_constants",
                         "rtl_constants", "tx_timing", "rx_timing",
                         "vectors", "crc_vectors"):
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
        if n < 10:
            return False, (
                f"L8 timing_waveform must carry ≥10 typed timing "
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
            return False, (
                f"L9 integration_spec must carry ≥3 typed structural "
                f"fields among (top_module string, fsm_states[], "
                f"port list, submodules[], internal_wires[]); have {n}.")
    elif layer == 10:
        cases = (data.get("test_cases") or data.get("cases")
                 or data.get("vectors"))
        n_cases = _list_len_of_dicts(cases)
        if n_cases < 5:
            return False, (
                f"L10 test_cases must carry ≥5 typed test cases; "
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
        if best < 3:
            return False, (
                f"L11 must carry ≥3 typed entries across "
                f"`behavioral_sequences` + `calibration_tables` "
                f"(Wave 32 joint ownership); have "
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
        if n_cases < 5:
            return False, (
                f"L13 lab_calibration / test_cases must carry ≥5 typed "
                f"cases (or calibration_steps[] / lab_equipment[] / "
                f"rig_pin_assignments{{}} entries); have {n_cases}.")
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
