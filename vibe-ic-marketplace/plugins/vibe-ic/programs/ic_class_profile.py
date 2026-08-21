#!/usr/bin/env python3
"""
ic_class_profile.py — IC class detection helper (Wave 36, v0.119.68).

Wave 36 introduces an IC class profile so other gates can decide
"is this gate applicable to this IC" before running their existing
FAIL logic.  The motivation: every Phase 1 (doc-extraction) / Phase 2 gate so far
hard-coded the assumption that the IC is an AID-class half-duplex
single-wire device with OTP / calibration / 13 L docs.  Running
those gates against e.g. a pure-analog PMIC, a SPI EEPROM, or a
bare FPGA project produced false-positive FAILs that cost the
fresh-agent benchmark loop time on non-existent bugs.

Wave 36 design principle
========================
- All existing FAIL logic is preserved.
- Each gate calls `detect_ic_class(project_dir)` at the top of its
  inspect() function and short-circuits to SKIP iff the gate is
  NOT applicable to the detected class.
- If detection fails (no L1/L2 yet, or the docs are too sparse),
  the class is `unknown` and we FAIL CLOSED — i.e. the existing
  FAIL logic still runs.  We only open new escape paths when we
  have positive evidence.

Class taxonomy
==============
  * `aid_class_half_duplex` — Apple ID Bus / <half-duplex-tester> / <chip-class> family
    (single-wire half-duplex open-drain, BR/IBT/CRC8 framing).
    All 13 L docs mandatory.
  * `digital_cmd_driven`    — UART / SPI / I2C / parallel cmd-driven
    digital chip with no analog block.  L1/L2/L3/L4/L6/L7/L8/L9/L10
    mandatory; L5/L11/L12/L13 conditional on has_analog /
    has_otp / has_calibration / has_lab_calibration flags.
  * `mixed_signal_otp`      — analog + digital + OTP (e.g. a sensor
    with on-chip trim & cmd interface).  Like digital_cmd_driven
    but L5/L11 are forced mandatory.
  * `pure_analog`           — PMIC / LDO / amplifier / pure-analog
    block with no command protocol.  L1/L2/L5/L8/L13 mandatory;
    L3/L6/L7/L10 conditional.
  * `bare_fpga`             — eval kit / bare FPGA scaffold.  NOT a
    fabbed IC — we do not gate Phase 1 (doc-extraction) coverage at all (no vendor
    docs to extract from).  Maintain the legacy 13/13 path.
  * `unknown`               — could not infer; fail-closed default.

Usage
-----
    from ic_class_profile import detect_ic_class
    profile = detect_ic_class(project_dir)
    if not profile["has_command_protocol"]:
        return SKIP

The returned dict is intentionally JSON-serialisable so gates can
embed it in their result blob for forensic auditing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import _path_layout as _pl
# Imported, never re-typed: the emitter's bookkeeping key must be excluded
# from every string harvest here, and a local copy of the literal is how the
# exclusion silently stops matching when the key is renamed.
from l_doc_generator_stamp import STAMP_KEY as _GENERATOR_STAMP_KEY


# Generic single-wire half-duplex protocol nomenclature. Chip-AGNOSTIC.
_AID_CLASS_PROTOCOL_TOKENS: tuple[str, ...] = (
    "aid",
    "apple id bus",
    "id_bus",
    "single_wire_half_duplex",
    "half_duplex_single_wire",
    "open_drain_single_wire",
)
_HALF_DUPLEX_PROTOCOL_TOKENS: tuple[str, ...] = (
    "single_wire_half_duplex",
    "half_duplex_single_wire",
    "k_line",
    "k-line",
    "kwp2000",
    "kwp_2000",
    "iso14230",
    "iso_14230",
    "iso9141",
    "iso_9141",
    "lin",
    "fast_init",
    "5_baud_init",
    "owire",
    "1-wire",
    "1_wire",
    "one_wire",
)

# Inout id-bus regex — re-used across gates. Kept here so other
# helpers stay in sync if naming ever changes.
_INOUT_ID_BUS_RE = re.compile(
    r"\binout\b[^,;)]*\b(id_bus|id_io|idbus|id_data)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------
def _try_load(p: Path) -> Optional[dict]:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(errors="ignore"))
    except Exception:
        return None


def _generated_docs_dir(project: Path) -> Optional[Path]:
    d = _pl.generated_docs_dir(project)
    return d if d.is_dir() else None


def _first_l_doc(project: Path, prefix: str) -> Optional[dict]:
    d = _generated_docs_dir(project)
    if d is None:
        return None
    for cand in sorted(d.glob(f"{prefix}*.json")):
        j = _try_load(cand)
        if isinstance(j, dict):
            return j
    return None


def _has_inout_id_bus(project: Path) -> bool:
    rtl = _pl.rtl_dir(project)
    if not rtl.is_dir():
        return False
    for ext in (".v", ".sv"):
        for p in rtl.rglob(f"*{ext}"):
            try:
                txt = p.read_text(errors="ignore")
            except OSError:
                continue
            if _INOUT_ID_BUS_RE.search(txt):
                return True
    return False


# Wave 42 (v0.119.70) / SF5 — patterns that betray a command-driven
# digital design even if the L docs claim pure_analog. Used to
# detect fault-injection where ic_class is mis-asserted.
_CMD_DRIVEN_RTL_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bcmd_buf\b|\bpayload_buf\b|\bopcode\b|\bcmd_decoder\b",
               re.IGNORECASE),
    re.compile(r"\bcase\s*\(\s*opcode", re.IGNORECASE),
    re.compile(r"\bS_CMD_|\bS_OP_|\bopcode_dispatch\b", re.IGNORECASE),
    re.compile(r"\bcmd_buffer\b|\bcommand_decode\b", re.IGNORECASE),
)


def _has_cmd_driven_rtl_evidence(project: Path) -> bool:
    """Wave 42 / SF5 — True iff RTL contains tell-tale cmd-driven
    digital constructs.  Used to downgrade a faked `pure_analog`
    ic_class to `unknown` (fail-closed)."""
    rtl = _pl.rtl_dir(project)
    if not rtl.is_dir():
        return False
    for ext in (".v", ".sv"):
        for p in rtl.rglob(f"*{ext}"):
            try:
                txt = p.read_text(errors="ignore")
            except OSError:
                continue
            # Comments are stripped lightly to avoid false positives
            # from doc-comments mentioning "opcode" etc.
            txt_no_line_cmt = re.sub(r"//[^\n]*", "", txt)
            txt_clean = re.sub(
                r"/\*.*?\*/", "", txt_no_line_cmt, flags=re.DOTALL)
            for pat in _CMD_DRIVEN_RTL_PATTERNS:
                if pat.search(txt_clean):
                    return True
    return False


def _l2_protocol_type(l2: Optional[dict]) -> Optional[str]:
    """Return a normalised protocol string from L2 or None."""
    if not isinstance(l2, dict):
        return None
    # Direct field
    for path in (
        ("protocol_type",),
        ("protocol",),
        ("frs_doc", "protocol_type"),
        ("frs_doc", "interface"),
        ("interface_type",),
        ("physical_layer", "interface"),
    ):
        cur: Any = l2
        ok = True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok and isinstance(cur, str) and cur.strip():
            return cur.strip().lower()
    return None


def _l3_has_commands(l3: Optional[dict]) -> bool:
    if not isinstance(l3, dict):
        return False
    for k in ("commands", "command_table", "opcodes",
             "opcodes_supported", "opcode_set"):
        v = l3.get(k)
        # v0.1.62: when every list entry is a hallucination-scrubbed opcode
        # (hex == '<HALLUCINATION_SCRUBBED>'), treat the list as empty so a
        # bus-protocol spec (which has no real opcodes) doesn't get
        # mis-classified as digital_cmd_driven on the strength of placeholder
        # OTP-template opcodes the runner emitted before scrubbing.
        if isinstance(v, list) and v:
            real = [op for op in v
                    if not (isinstance(op, dict)
                             and op.get("hex") == "<HALLUCINATION_SCRUBBED>")]
            if real:
                return True
        if isinstance(v, dict) and v:
            return True
    return False


def _l3_physical_layer_text(l3: Optional[dict]) -> str:
    if not isinstance(l3, dict):
        return ""
    out: list[str] = []
    for k in ("physical_layer", "interface", "transport"):
        v = l3.get(k)
        if isinstance(v, dict):
            out.append(json.dumps(v).lower())
        elif isinstance(v, str):
            out.append(v.lower())
    return " ".join(out)


def _l4_has_otp(l4: Optional[dict], l11: Optional[dict],
                l14_otp: Optional[dict]) -> bool:
    """Return True iff any L doc encodes OTP image / lockbits / etc.

    Wave 42 (v0.119.70) / SF7 — key set widened to cover the
    additional OTP field names emitted by Phase 1 (doc-extraction) generators across
    different ICs (otp_field_table, otp_image_hex, otp_registers,
    otp_bytes, otp_program_table, otp_section_layout, otp_dump,
    otp_macro).

    ORGANIC-20260614 (#653) — the Phase-1 L4 generator emits an
    ``otp_layout`` SKELETON dict (default depth/width geometry, all
    content lists empty: fields/read_map/write_map/lockbits/
    trim_registers/mask_sources=[]) for NO-OTP ICs.  A non-empty dict
    is truthy, so the old ``if v: return True`` reported has_otp=True
    even for ICs that explicitly declare ``otp_present: false`` /
    ``no_otp_layout_in_input: true``.  Fix is two-fold and chip-AGNOSTIC:
      (1) an explicit absence veto (L11 ``otp_present == False`` OR
          L4/L11 ``no_otp_layout_in_input``/``no_otp_in_input``) is a
          HARD short-circuit to False; and
      (2) a dict-valued OTP key only counts as evidence when at least
          one CONTENT sub-field is non-empty — geometry-only skeletons
          do not.  Non-dict OTP values (e.g. a populated ``lockbits``
          list or ``otp_bytes`` blob) keep their plain truthiness.
    """
    otp_keys = (
        "otp_layout", "otp_table", "otp_image",
        "otp_content", "otp_ip_specs", "lockbits",
        "otp_field_table", "otp_image_hex", "otp_registers",
        "otp_bytes", "otp_program_table",
        "otp_section_layout", "otp_dump", "otp_macro",
    )
    nested_otp_keys = (
        "otp_layout", "otp_table", "otp_image",
        "otp_field_table", "otp_image_hex", "otp_registers",
        "otp_bytes", "otp_program_table", "otp_content",
    )
    # Content sub-fields that distinguish a POPULATED OTP-layout dict from
    # a geometry-only skeleton (which carries only depth/width defaults).
    otp_content_subkeys = (
        "fields", "read_map", "write_map", "lockbits",
        "otp_bytes", "trim_registers", "mask_sources",
        "registers", "image", "image_hex", "program_table",
        "entries", "rows",
    )

    def _dict_has_content(d: dict) -> bool:
        """True iff a dict-valued OTP key holds real content, not just
        a geometry-only skeleton (all content sub-fields empty)."""
        for ck in otp_content_subkeys:
            if d.get(ck):
                return True
        return False

    def _otp_value_is_evidence(v: Any) -> bool:
        if isinstance(v, dict):
            return _dict_has_content(v)
        return bool(v)

    def _doc_has_otp_content(j: Any) -> bool:
        """True iff this L doc carries POPULATED OTP content (not a
        geometry-only skeleton), at the top level or nested."""
        if not isinstance(j, dict):
            return False
        for k in otp_keys:
            if _otp_value_is_evidence(j.get(k)):
                return True
        for nested_key in ("L4_REGMAP", "L11_OTP_CONTENT", "L14_OTP_CONTENT"):
            nv = j.get(nested_key)
            if isinstance(nv, dict):
                for k in nested_otp_keys:
                    if _otp_value_is_evidence(nv.get(k)):
                        return True
        return False

    # (1) Explicit absence veto — hard short-circuit to False.  A no-OTP
    #     IC may carry a truthy-but-empty skeleton AND an honest negative
    #     declaration; the declaration wins.
    #
    #     ...but ONLY over a skeleton.  #653 added this veto to beat a
    #     truthy-but-EMPTY otp_layout, and its own docstring says so.  As an
    #     UNCONDITIONAL short-circuit it also beat POPULATED content, which
    #     turns the declaration from a tie-breaker into an override: a doc
    #     carrying a real OTP image was reported has_otp=False because some
    #     other pass had left an `otp_present: False` beside it.  The
    #     declaration is a PROXY for "this design has no OTP"; the property
    #     is "is there OTP content".  So the veto is now scoped to the case
    #     #653 describes — no populated OTP content anywhere in L4/L11/L14.
    #     When content IS present the content wins and the stale/foreign
    #     declaration is ignored.
    if not any(_doc_has_otp_content(j) for j in (l4, l11, l14_otp)):
        for j in (l4, l11, l14_otp):
            if not isinstance(j, dict):
                continue
            if j.get("otp_present") is False:
                return False
            for veto_key in ("no_otp_layout_in_input", "no_otp_in_input"):
                if j.get(veto_key) is True:
                    return False

    for j in (l4, l11, l14_otp):
        if not isinstance(j, dict):
            continue
        for k in otp_keys:
            v = j.get(k)
            if _otp_value_is_evidence(v):
                return True
        # Nested under L4_REGMAP / L11_OTP_CONTENT structure
        for nested_key in (
            "L4_REGMAP", "L11_OTP_CONTENT", "L14_OTP_CONTENT",
        ):
            nv = j.get(nested_key)
            if isinstance(nv, dict):
                # Same scoping as the top-level veto above: a negative
                # declaration only wins when the nested doc carries no
                # populated content of its own.
                nested_has_content = any(
                    _otp_value_is_evidence(nv.get(k))
                    for k in nested_otp_keys
                )
                if not nested_has_content:
                    if nv.get("otp_present") is False:
                        return False
                    for veto_key in (
                        "no_otp_layout_in_input", "no_otp_in_input",
                    ):
                        if nv.get(veto_key) is True:
                            return False
                if nested_has_content:
                    return True
    return False


def _l11_has_calibration(l11: Optional[dict], l12: Optional[dict]) -> bool:
    for j in (l11, l12):
        if not isinstance(j, dict):
            continue
        if j.get("no_calibration") is True:
            return False  # explicitly marked absent
        for k in ("calibration_targets", "calibration_tables",
                 "calibration_steps", "calibration_routine",
                 "tables", "production_burn_recipe", "trim_recipes"):
            if j.get(k):
                return True
    return False


def _l13_has_lab_calibration(l13: Optional[dict]) -> bool:
    if not isinstance(l13, dict):
        return False
    for k in ("lab_traces_present", "scope_capture_summary",
             "calibration_observations", "lab_equipment",
             "lab_steps", "rig_pin_assignments", "calibration_steps"):
        v = l13.get(k)
        if v in (None, False, "", [], {}):
            continue
        return True
    return False


# ORGANIC-20260528 (v0.2.30) — analog/mixed-signal misclassification fix.
# The Phase-1 L5 ingester emits two structurally-different kinds of
# low_confidence block:
#   (a) GENUINE figure-only analog blocks — the canonical ΔΣ/SAR
#       teaching-chip pattern where the datasheet publishes its numeric
#       specs as figures, so `spec` is null and the block is flagged
#       low_confidence, BUT a concrete extracted instance count
#       (`count` / `multiplicity` from a "N copies of X" statement) is
#       present.  e.g. the University-of-Hawaii incremental ΔΣ ADC:
#       {name: delta_sigma, count: 6, low_confidence: true}.
#   (b) PARITY STUBS — emitted by the v1.6.269 parity gate when a token
#       like "DAC"/"ESD" is seen only in N/A / negative context
#       ("Plugin 不需產生 ... analog trim DAC", "ESD by PDK default") or
#       when the analog-context window guard rejected it.  These carry
#       `extraction_strategy` == "l5_parity_stub*" and NO instance count.
# The legacy v1.6.523 rule dropped EVERY low_confidence block, which
# correctly suppressed (b) but ALSO zeroed out (a) — so an analog
# datasheet whose specs are figure-only was misclassified
# digital_arithmetic_primitive (has_analog=False) and never reached the
# analog A1..A9 track.  We now keep the stub suppression but recover the
# genuine figure-only blocks: low_confidence is treated as "specs are
# figure-only", NOT "maybe not analog".
def _is_parity_stub(b: Any) -> bool:
    """True iff the L5 block is a v1.6.269 parity-stub artifact (token
    seen only in N/A / negative context), NOT a real analog block."""
    if not isinstance(b, dict):
        return False
    return str(b.get("extraction_strategy") or "").startswith(
        "l5_parity_stub")


def _pos_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _block_is_analog_marker(b: Any) -> bool:
    """True iff an L5 block is a positive analog marker.

    A parity stub is never a marker.  A high-confidence block is always
    a marker (legacy behavior preserved).  A low_confidence block counts
    ONLY when it carries a concrete extracted instance count (count /
    multiplicity) — i.e. the ingester found a real "N copies of <block>"
    statement in the doc, distinguishing a genuine figure-only analog
    block (specs published as figures) from a spurious token match whose
    surrounding context is unrelated to an actual analog block.
    """
    if not isinstance(b, dict):
        return False
    if _is_parity_stub(b):
        return False
    if not b.get("low_confidence", False):
        return True
    return _pos_int(b.get("count")) or _pos_int(b.get("multiplicity"))


def _l5_has_analog(l5: Optional[dict]) -> bool:
    """v0.2.30 (ORGANIC-20260528) — recover figure-only analog blocks.

    Keeps the v1.6.523 parity-stub suppression (so docs that mention
    'no DAC needed' / 'ESD by PDK default' as N/A context don't falsely
    classify the chip as analog) but no longer drops a low_confidence
    block merely because its specs are figure-only: a low_confidence
    block with a concrete extracted instance count is a genuine analog
    marker.  High-confidence analog blocks count as before.
    """
    if not isinstance(l5, dict):
        return False
    if l5.get("no_analog") is True:
        return False
    for k in ("analog_blocks", "blocks", "adi_blocks", "topology",
             "wake_modes", "rx_event_pipeline_summary"):
        v = l5.get(k)
        if isinstance(v, list) and v:
            if any(_block_is_analog_marker(b) for b in v):
                return True
        elif v and not isinstance(v, list):
            return True
    return False


# ORGANIC-20260528 (v0.2.30) — L1-declared analog/mixed-signal class.
# Independent of L5: when L1 itself declares an analog/mixed-signal class
# (canonical taxonomy token, NOT a chip/vendor name), the IC is analog
# regardless of whether L5 blocks survived the figure-only filter.  The
# Phase-1 ingester writes the class into `class` (synthetic / Path-A
# skeleton) or `class_path` (Path-B README detector).  Chip-AGNOSTIC:
# only generic class-taxonomy substrings.
_L1_ANALOG_CLASS_TOKENS: tuple[str, ...] = (
    "mixed_signal",
    "mixed-signal",
    "pure_analog",
    "pure-analog",
    "analog_block",
    "sar_adc",
    "delta_sigma",
    "delta-sigma",
    "sigma_delta",
    "adc",
    "dac",
    "ldo",
    "bandgap",
    "pll",
)


def _l1_declares_analog_class(l1: Optional[dict]) -> bool:
    """True iff L1 explicitly declares an analog / mixed-signal class.

    Reads the canonical class field(s) only (`class`, `class_path`,
    `ic_class`, `device_class`) — never the free-text description, so a
    digital chip whose datasheet merely *mentions* an ADC does not get
    flipped.  Matches generic taxonomy tokens with word-ish boundaries to
    avoid e.g. 'adc' inside an unrelated identifier."""
    if not isinstance(l1, dict):
        return False
    raw_parts: list[str] = []
    for key in ("class", "class_path", "ic_class", "device_class",
                "product_class"):
        v = l1.get(key)
        if isinstance(v, str) and v.strip():
            raw_parts.append(v.strip().lower())
    if not raw_parts:
        return False
    blob = " ".join(raw_parts).replace("-", "_")
    for tok in _L1_ANALOG_CLASS_TOKENS:
        t = tok.replace("-", "_")
        # word-boundary match so 'adc' does not hit inside 'roadcaster'
        if re.search(r"(?:^|[^a-z0-9])" + re.escape(t) + r"(?:$|[^a-z0-9])",
                     blob):
            return True
    return False


# ORGANIC #613 — digital serial-readout signature of a data converter's
# analog→digital interface. A data converter (sigma-delta / SAR / pipeline ADC,
# or DAC) emits a DIGITAL serial bitstream (1-bit serial outputs / dout-style
# pins) — the digital half that a pure-analog PMIC/LDO/amplifier never has.
# Generic data-converter readout vocabulary only; NO chip / vendor / SKU name.
_V1_6_613_SERIAL_READOUT_RE = re.compile(
    r"(?:digital\s+serial\s+output"        # "Digital serial outputs OUT1..OUT6"
    r"|serial\s+bitstream"                  # "serial bitstream"
    r"|digital\s+bitstream"                 # "digital bitstream per channel"
    r"|1[\s\-]?bit\s+serial"                # "1-bit serial (OUTn / dout)"
    r"|bitstream\s+per\s+channel"           # "digital bitstream per channel"
    r"|\bdout\w*\s+serial|serial\s+\w*dout" # "dout serial"
    r"|serial\s+readout"                    # "serial readout"
    r")",
    re.IGNORECASE)


def _v1_6_613_has_digital_serial_readout(l1: Optional[dict],
                                         l5: Optional[dict]) -> bool:
    """ORGANIC #613 — True iff the design exposes a DIGITAL serial readout (a
    1-bit serial output / dout-style digital bitstream). This is the
    discriminator that separates a data_converter (analog content AND a digital
    serial readout) from a pure_analog IC (analog content, NO digital readout) —
    a pure-analog PMIC/LDO/amplifier never emits a digital bitstream, so it does
    NOT match and stays pure_analog. Harvests L1+L5 string leaves; chip-AGNOSTIC
    (generic serial-bitstream vocabulary, no chip name)."""
    sink: List[str] = []
    for d in (l1, l5):
        if isinstance(d, dict):
            _harvest_strings(d, sink)
    return bool(_V1_6_613_SERIAL_READOUT_RE.search(" ".join(sink)))


def _l6_has_fsm(l6: Optional[dict]) -> bool:
    if not isinstance(l6, dict):
        return False
    for k in ("fsm_states", "states", "state_table", "fsms"):
        v = l6.get(k)
        if isinstance(v, list) and v:
            return True
        if isinstance(v, dict) and v:
            return True
    return False


def _normalise_protocol_class(raw: Optional[str], l3_phys: str,
                              has_inout_id_bus: bool) -> str:
    """Map an arbitrary protocol_type string to a canonical class."""
    if raw:
        r = raw.lower().replace("-", "_").replace(" ", "_")
        for tok in _AID_CLASS_PROTOCOL_TOKENS:
            if tok in r:
                return "aid_class"
        if "lin" in r and "kline" not in r and "k_line" not in r:
            return "lin"
        if "k_line" in r or "kline" in r or "5_baud" in r or "fast_init" in r:
            return "k_line"
        if "kwp" in r or "iso14230" in r or "iso_14230" in r:
            return "kwp2000"
        if "spi" in r:
            return "spi"
        if "i2c" in r or "smbus" in r:
            return "i2c"
        if "uart" in r or "rs232" in r or "rs_232" in r:
            return "uart"
        if "owire" in r or "1_wire" in r or "one_wire" in r:
            return "single_wire_half_duplex"
        if "half_duplex" in r:
            return "single_wire_half_duplex"

    blob = (l3_phys or "").lower()
    if has_inout_id_bus:
        return "aid_class"
    for tok in _AID_CLASS_PROTOCOL_TOKENS:
        if tok in blob:
            return "aid_class"
    for tok in _HALF_DUPLEX_PROTOCOL_TOKENS:
        if tok in blob:
            if "lin" in tok:
                return "lin"
            if "k_line" in tok or "kline" in tok or "kwp" in tok or \
               "iso14230" in tok or "fast_init" in tok or "iso_9141" in tok or \
               "iso9141" in tok:
                return "k_line"
            if "owire" in tok or "1_wire" in tok or "one_wire" in tok:
                return "single_wire_half_duplex"
            return "single_wire_half_duplex"
    if "spi" in blob:
        return "spi"
    if "i2c" in blob:
        return "i2c"
    if "uart" in blob:
        return "uart"
    return "none"


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------
def detect_ic_class(project_dir: Path,
                    refresh: bool = False) -> Dict[str, Any]:
    """Return an IC class profile dict for the given project.

    See module docstring for the full contract.  Falls back to
    `class="unknown"` on missing input — gates must treat this as
    fail-closed (run their existing FAIL logic).

    ORGANIC-20260606-ic-class-detector-disagreement (#435): the detected
    class is PERSISTED once at `<project>/reports/ic_class.json` and every
    later call returns that persisted result — never a second inference.
    Two inferences at different times see different L-doc states (later
    steps augment the docs), which forked class-gated behavior (rtl_gen
    WAIVE target, structured-field minimums, no-protocol N/A escapes)
    between enforced and N/A on the SAME project. `refresh=True` forces a
    re-inference AND re-persists (the runner's detect step uses it so the
    persisted truth is the run's own detection). An `unknown` inference is
    never persisted (fail-closed must stay re-inferable once docs land).
    """
    project = Path(project_dir)
    persisted = project / "reports" / "ic_class.json"
    if not refresh and persisted.is_file():
        try:
            d = json.loads(persisted.read_text())
            if isinstance(d, dict) and d.get("ic_class"):
                return d
        except (OSError, ValueError):
            pass  # unreadable persistence → fall through to inference
    profile = _detect_ic_class_infer(project)
    if project.is_dir() and profile.get("ic_class") not in (None, "",
                                                            "unknown"):
        try:
            persisted.parent.mkdir(parents=True, exist_ok=True)
            persisted.write_text(
                json.dumps(profile, indent=2, ensure_ascii=False) + "\n")
        except OSError:
            pass
    return profile


def infer_ic_class_uncached(project_dir: Path) -> Dict[str, Any]:
    """Run the classifier NOW and return the profile WITHOUT reading OR
    writing ``<project>/reports/ic_class.json``.

    re #495 Stage 1 — there are THREE layers of ``ic_class`` in a project and
    only two of them had a name:

      layer 1  the per-L-doc ``ic_class`` stamp   frozen at phase-1 emit time
      layer 2  ``reports/ic_class.json``          frozen at the last
                                                  ``refresh=True`` run
      layer 3  what the classifier says TODAY

    ``detect_ic_class(p)`` returns layer 2 whenever the file exists (the #435
    persist-once contract) and ``detect_ic_class(p, refresh=True)`` is the only
    way to reach layer 3 — but it PERSISTS, so a read-only consumer such as a
    gate cannot use it without mutating the project it is auditing. Layer 3 was
    therefore unreachable from any gate, and layer-2 staleness was invisible:
    measured over the 103 tracked projects that carry a persisted profile,
    layer 2 and layer 3 disagree on 24 of them.

    This is the read-only door to layer 3. It is deliberately NOT wired into
    any pass/fail verdict — see ``ic_class_consistency_check``, which uses it
    to DISCLOSE staleness, not to fail on it. chip-AGNOSTIC.
    """
    return _detect_ic_class_infer(Path(project_dir))


def _detect_ic_class_infer(project_dir: Path) -> Dict[str, Any]:
    """The actual single-pass inference (see detect_ic_class)."""
    project = Path(project_dir)
    profile: Dict[str, Any] = {
        "protocol_class": "none",
        "has_inout_id_bus": False,
        "has_command_protocol": False,
        "has_otp": False,
        "has_calibration": False,
        "has_lab_calibration": False,
        "has_analog": False,
        "has_fsm": False,
        "is_pure_analog": False,
        "is_pure_digital": False,
        "is_mixed_signal": False,
        "is_data_converter": False,  # ORGANIC #613
        "ic_class": "unknown",
        # ORGANIC-20260607 #495 — the rule/feature(s) that DECIDED the
        # class. Recorded for drift diagnosis: when two plugin versions
        # disagree on the class for IDENTICAL input docs, this field names
        # the branch each version took so the regression is traceable
        # rather than silent. Set at every classification return point.
        "decisive_evidence": "no_project_dir",
    }

    if not project.is_dir():
        return profile

    l1 = _first_l_doc(project, "L1_")
    l2 = _first_l_doc(project, "L2_")
    l3 = _first_l_doc(project, "L3_")
    l4 = _first_l_doc(project, "L4_")
    l5 = _first_l_doc(project, "L5_")
    l6 = _first_l_doc(project, "L6_")
    l11 = _first_l_doc(project, "L11_")
    l12 = _first_l_doc(project, "L12_")
    l13 = _first_l_doc(project, "L13_")
    l14_otp = _first_l_doc(project, "L14_")  # OTP in some schemas

    profile["has_inout_id_bus"] = _has_inout_id_bus(project)
    profile["has_command_protocol"] = _l3_has_commands(l3)
    profile["has_otp"] = _l4_has_otp(l4, l11, l14_otp)
    profile["has_calibration"] = _l11_has_calibration(l11, l12)
    profile["has_lab_calibration"] = _l13_has_lab_calibration(l13)
    # ORGANIC-20260528 (v0.2.30) — analog iff L5 has a genuine analog
    # marker (figure-only blocks recovered, parity stubs suppressed) OR
    # L1 explicitly declares an analog/mixed-signal class. low_confidence
    # in L5 means "specs are figure-only", NOT "maybe not analog", so it
    # must not zero out has_analog for a declared analog datasheet.
    profile["has_analog"] = (
        _l5_has_analog(l5) or _l1_declares_analog_class(l1)
    )
    profile["has_fsm"] = _l6_has_fsm(l6)

    raw_proto = _l2_protocol_type(l2)
    l3_phys = _l3_physical_layer_text(l3)
    profile["protocol_class"] = _normalise_protocol_class(
        raw_proto, l3_phys, profile["has_inout_id_bus"]
    )

    # Mixed-signal inference
    profile["is_mixed_signal"] = (
        profile["has_analog"] and
        (profile["has_command_protocol"] or profile["has_fsm"])
    )
    profile["is_pure_analog"] = (
        profile["has_analog"]
        and not profile["has_command_protocol"]
        and not profile["has_fsm"]
    )
    profile["is_pure_digital"] = (
        not profile["has_analog"]
        and (profile["has_command_protocol"] or profile["has_fsm"])
    )

    # Class assignment
    if l1 is None and l2 is None and l3 is None:
        # Path-A skeleton or pre-Phase 1 project. Conservative default.
        # If facts.yaml exists assume bare_fpga / unknown.
        if (project / "facts.yaml").is_file():
            profile["ic_class"] = "bare_fpga"
            profile["decisive_evidence"] = (
                "no_l1_l2_l3_docs + facts.yaml present → bare_fpga")
        else:
            profile["ic_class"] = "unknown"
            profile["decisive_evidence"] = (
                "no_l1_l2_l3_docs (pre-phase1) → unknown (fail-closed)")
        return profile

    if profile["protocol_class"] == "aid_class":
        profile["ic_class"] = "aid_class_half_duplex"
        profile["decisive_evidence"] = "protocol_class==aid_class"
        return profile

    # ORGANIC #613 — data-converter / mixed-signal-with-digital-readout class.
    # A data converter (sigma-delta / SAR / pipeline ADC, or DAC) has analog
    # content AND a digital serial readout (1-bit serial outputs / dout-style
    # bitstream) but NO SW-visible command protocol and NO control FSM, so it
    # would otherwise collapse to pure_analog (rtl_gen=null + fallback_skill=
    # null → Phase 2 SKIPs RTL entirely, leaving NO generation path for the
    # digital decimation / serial-readout datapath it genuinely needs).
    # Detect it ABOVE the pure_analog fall-through, gated on a digital
    # serial-readout signature that a pure-analog PMIC/LDO/amplifier never has
    # (so pure_analog stays pure_analog). CRITICAL: is_pure_analog is set False
    # so the design does NOT receive the pure-analog digital-backend WAIVE
    # (both _project_is_pure_analog and _is_pure_analog_no_rtl_track key on that
    # FLAG) — a data converter HAS a digital datapath that must reach
    # synth → PnR → GDS via the registry's fallback_skill=spec-to-rtl.
    # chip-AGNOSTIC: structural (has_analog + serial-readout vocab), no chip.
    if (profile["has_analog"]
            and not profile["has_command_protocol"]
            and not profile["has_fsm"]
            and _v1_6_613_has_digital_serial_readout(l1, l5)):
        profile["is_data_converter"] = True
        profile["is_pure_analog"] = False
        profile["ic_class"] = "data_converter"
        profile["decisive_evidence"] = (
            "is_data_converter (has_analog + digital serial readout, no cmd, "
            "no fsm) — analog→digital interface recognised; NOT pure_analog "
            "so the digital decimation/serial-readout datapath reaches the "
            "digital backend via spec-to-rtl (#613)")
        return profile

    if profile["is_pure_analog"]:
        # Wave 42 (v0.119.70) / SF5 — fault-injection hardening.
        # If L1/L5 paint the IC as pure_analog yet the RTL exposes
        # cmd-driven digital constructs (cmd_buf / opcode / etc.),
        # the project is mis-claiming class. Downgrade to `unknown`
        # so fail-closed gates re-engage.
        if _has_cmd_driven_rtl_evidence(project):
            profile["ic_class"] = "unknown"
            profile["class_downgrade_reason"] = (
                "RTL has cmd-driven evidence but L docs claim "
                "pure_analog — class downgrade triggered "
                "(Wave 42 / SF5)"
            )
            profile["decisive_evidence"] = (
                "is_pure_analog but cmd-driven RTL evidence → "
                "downgrade to unknown (Wave 42 / SF5)")
            return profile
        profile["ic_class"] = "pure_analog"
        profile["decisive_evidence"] = (
            "is_pure_analog (has_analog, no cmd, no fsm)")
        return profile

    if profile["is_mixed_signal"] and profile["has_otp"]:
        profile["ic_class"] = "mixed_signal_otp"
        profile["decisive_evidence"] = "is_mixed_signal + has_otp"
        return profile

    if profile["is_mixed_signal"]:
        # Mixed signal w/o OTP collapses to digital_cmd_driven if it has
        # commands; else mixed_signal_otp without otp is rare — fall back.
        # Guard against processor_cpu misfire (ORGANIC #450 idiom, mirrors
        # the #542 bus_peripheral guard): a CPU's ISA opcode enum harvests
        # as has_command_protocol but carries no protocol framing, and must
        # route to the ISA-bearing processor_cpu detector below, not here.
        if (profile["has_command_protocol"]
                and not _looks_like_processor_cpu(l1, l2)):
            profile["ic_class"] = "digital_cmd_driven"
            profile["decisive_evidence"] = (
                "is_mixed_signal (no otp) + has_command_protocol")
            return profile

    if (profile["is_pure_digital"] and profile["has_command_protocol"]
            and not _looks_like_processor_cpu(l1, l2)):
        profile["ic_class"] = "digital_cmd_driven"
        profile["decisive_evidence"] = (
            "is_pure_digital + has_command_protocol")
        return profile

    # v0.1.62 — bus_interconnect_protocol detector. AMBA AXI/AHB/APB/ACE,
    # Wishbone, TileLink, CHI, OCP, AvalonMM, STBus and similar all share a
    # structural signature: per-direction channels carrying valid/ready (or
    # req/ack) handshakes between explicit master/slave (or manager/subordinate)
    # roles with burst transfers. The detector counts these structural
    # features in L1+L2 description text — NO benchmark-specific brand names
    # (per memory 'enhancements must be general, not keyword'). digital
    # adders/filters/hashes don't talk about channels+handshake+master/slave,
    # so this branch is positive only for genuine bus protocol specs.
    if l1 is not None or l2 is not None:
        if (not profile["has_analog"]
                and not profile["has_command_protocol"]
                and _looks_like_bus_interconnect_protocol(l1, l2)):
            profile["ic_class"] = "bus_interconnect_protocol"
            profile["decisive_evidence"] = (
                "no analog/cmd + bus-interconnect structural signature "
                "(>=4 features + >=2 named channels)")
            return profile

    # v0.1.77 — serial_peripheral_protocol detector. SPI/I2C/UART/I2S-style
    # serial peripheral specs share a structural signature distinct from
    # bus_interconnect_protocol: small fixed pin count (≤8 external), master/
    # slave (or controller/target) roles, shift register + clock-or-baud-
    # rate control. Detector counts ≥3 of 6 structural features (no brand
    # keywords). The detector function lives below `_looks_like_bus_
    # interconnect_protocol` so test_detector_general_not_brand_keyword
    # (which only scans the bus-protocol detector block) does not pick up
    # the serial-protocol feature regexes (e.g. "chip select" → false-hit
    # on "CHI" otherwise).
    if l1 is not None or l2 is not None:
        if (not profile["has_analog"]
                and not _looks_like_bus_interconnect_protocol(l1, l2)
                and _looks_like_serial_peripheral_protocol(l1, l2)):
            profile["ic_class"] = "serial_peripheral_protocol"
            profile["decisive_evidence"] = (
                "no analog + serial-peripheral structural signature "
                "(>=3 features, not bus-interconnect)")
            return profile

    # ORGANIC #542 — crypto_accelerator BEFORE bus_peripheral and
    # processor_cpu. Crypto IPs often also have a register interface, but
    # the cipher-algorithm evidence is the primary discriminator. CPUs never
    # identify their core function with cipher algorithm names. Deny-guarded:
    # must name a real algorithm family (AES/SHA/HMAC/etc.) + >=1 other
    # crypto feature.
    if l1 is not None or l2 is not None:
        if (not profile["has_analog"]
                and _looks_like_crypto_accelerator(l1, l2)):
            profile["ic_class"] = "crypto_accelerator"
            profile["decisive_evidence"] = (
                "no analog + crypto-accelerator structural signature "
                "(algorithm_family deny-guard + >=2 features, #542)")
            return profile

    # ORGANIC #542 — bus_peripheral BEFORE processor_cpu and arithmetic
    # catch-all. SW-visible register map + bus subordinate interface WITHOUT
    # ISA/instruction evidence. Deny-guarded: must have explicit register_map
    # evidence (hjson/regmap/SW-accessible-register vocabulary). Guarded
    # against bus_interconnect_protocol (wire-level protocol spec) and
    # processor_cpu (instruction-execution) misfire.
    if l1 is not None or l2 is not None:
        if (not profile["has_analog"]
                and not _looks_like_bus_interconnect_protocol(l1, l2)
                and not _looks_like_processor_cpu(l1, l2)
                and _looks_like_bus_peripheral(l1, l2)):
            profile["ic_class"] = "bus_peripheral"
            profile["decisive_evidence"] = (
                "no analog + no bus-protocol + no cpu + bus-peripheral "
                "structural signature (register_map deny-guard + >=3 "
                "features, #542)")
            return profile

    # ORGANIC-20260606 #450 — processor_cpu BEFORE the arithmetic
    # catch-all: a CPU verifies by executing instructions + checking
    # architectural state, not by arithmetic-primitive semantics. The
    # detector requires ISA-bearing evidence (deny-guarded), so datapath
    # primitives (multipliers, hash cores) keep falling through.
    if l1 is not None or l2 is not None:
        if (not profile["has_analog"]
                and _looks_like_processor_cpu(l1, l2)):
            profile["ic_class"] = "processor_cpu"
            profile["decisive_evidence"] = (
                "no analog + processor-cpu structural signature "
                "(>=3 features incl. ISA-bearing deny-guard)")
            return profile

    # v1.6.523 — for #358 P2 root fix. Pure digital + no protocol + no analog +
    # L1/L2 present → digital_arithmetic_primitive (NOT bare_fpga, which
    # implies FPGA-only with no silicon target — wrong for ASIC datapath
    # primitives like multipliers, SoC cores w/o command interface, etc.).
    # Registry entry digital_arithmetic_primitive (v1.6.522) has fallback_skill
    # = spec-to-rtl, so this branch correctly routes the runner to AI fallback
    # without the prior pure_analog cascade FAIL.
    if l1 is not None or l2 is not None:
        if not profile["has_analog"] and not profile["has_command_protocol"]:
            profile["ic_class"] = "digital_arithmetic_primitive"
            profile["decisive_evidence"] = (
                "L1/L2 present + no analog + no cmd protocol + no "
                "protocol/cpu signature → arithmetic-primitive catch-all")
            return profile

    profile["ic_class"] = "unknown"
    profile["decisive_evidence"] = (
        "no classification branch matched → unknown (fail-closed)")
    return profile


# v0.1.62 — bus_interconnect_protocol structural detector.
# General, not bench-keyword: scores 6 orthogonal structural features in
# L1+L2 description text and triggers on threshold ≥ 3. No brand strings.
_BUS_PROTO_FEATURES: List[tuple[str, re.Pattern]] = [
    # 1. valid/ready (or req/ack) handshake — the per-cycle commit primitive
    ("valid_ready_handshake",
     re.compile(r"\bvalid\b.{0,80}?\bready\b|\bready\b.{0,80}?\bvalid\b|"
                r"\breq(?:uest)?\b.{0,40}?\back(?:nowledge)?\b",
                re.IGNORECASE | re.DOTALL)),
    # 2. channels — bus protocols partition into multiple typed channels
    ("multiple_channels",
     re.compile(r"\bchannels?\b", re.IGNORECASE)),
    # 3. master/slave or manager/subordinate role labels
    ("master_slave_roles",
     re.compile(r"\b(?:master|manager)s?\b.{0,200}?"
                r"\b(?:slave|subordinate|target)s?\b|"
                r"\b(?:slave|subordinate|target)s?\b.{0,200}?"
                r"\b(?:master|manager)s?\b",
                re.IGNORECASE | re.DOTALL)),
    # 4. burst transfers — addressed-then-streamed transactions
    ("burst_transfers",
     re.compile(r"\bbursts?\b|\bbeat(?:s|ed|ing)?\b\s+(?:of\s+)?(?:data|transfer)",
                re.IGNORECASE)),
    # 5. interconnect / topology / arbitration — protocol talks about fabric
    ("interconnect_topology",
     re.compile(r"\binterconnect\b|\barbitration\b|\bfabric\b",
                re.IGNORECASE)),
    # 6. handshake mentioned as a concept (separate from the literal pair)
    ("handshake_concept",
     re.compile(r"\bhandshakes?\b", re.IGNORECASE)),
]


def _harvest_strings(obj: Any, sink: List[str], max_strings: int = 4000,
                      max_depth: int = 8) -> None:
    """Walk nested dict/list and append every string leaf to `sink`. Bounded
    so a 100KB L doc with 5000 keys doesn't blow out. Skips obvious metadata
    fields (`extraction_evidence`, `extraction_strategy`) that contain only
    snippets re-quoted from the input and would double-count features.

    `_generator` is on that list for a stronger reason than double-counting:
    it is the emitter's own bookkeeping (which release wrote this file), so
    NOTHING in it is a fact about the chip. Measured: when its taxonomy
    digest was first emitted as `"sha256:<hex>"`, the `algorithm_family`
    pattern below matched it and nine documents' `ic_class` flipped from
    `bus_peripheral` to `crypto_accelerator` — the classifier reading its
    own toolchain's version record as evidence of a cipher core."""
    if len(sink) >= max_strings or max_depth <= 0:
        return
    if isinstance(obj, str):
        sink.append(obj)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("extraction_evidence", "extraction_strategy",
                     "auto_cited_sections", "vendor_short_literals",
                     _GENERATOR_STAMP_KEY):
                continue
            _harvest_strings(v, sink, max_strings, max_depth - 1)
    elif isinstance(obj, list):
        for v in obj:
            _harvest_strings(v, sink, max_strings, max_depth - 1)


def _looks_like_bus_interconnect_protocol(
        l1: Optional[dict], l2: Optional[dict]) -> bool:
    """True iff the L1+L2 content exhibits the bus-protocol structural
    signature: ≥4 of the 6 features AND >=2 explicit NAMED channels
    (e.g. 'read channel', 'address channel', 'write channel') — this
    distinguishes multi-channel bus protocols (AMBA AXI/AHB/APB,
    Wishbone, TileLink, OCP) from single-data-line serial peripherals
    (I2C, SPI, UART) that happen to mention 'master/slave' or
    'arbitration'. Walks ALL string leaves; NO brand-name keywords.
    """
    parts: List[str] = []
    for layer in (l1, l2):
        if isinstance(layer, dict):
            _harvest_strings(layer, parts)
    text = "\n".join(parts)
    if not text:
        return False
    hits = sum(1 for _, pat in _BUS_PROTO_FEATURES if pat.search(text))
    if hits < 4:
        return False
    # v0.1.79 — require ≥2 distinct NAMED channels (read/write/address/
    # data/response/snoop/command channel). I2C / SPI / UART specs mention
    # "channels" generically (often as an abstract concept) but do NOT
    # enumerate multiple typed channels; multi-channel bus protocols do.
    _NAMED_CH_RE = re.compile(
        r"\b(?:read|write|address|data|response|command|request|reply|"
        r"snoop|control|coherent)\s+channel\b",
        re.IGNORECASE)
    distinct_named = set(m.group(0).lower() for m in _NAMED_CH_RE.finditer(text))
    return len(distinct_named) >= 2


# v0.1.77 — serial_peripheral_protocol structural detector.
# General, not bench-keyword: scores 6 orthogonal structural features in
# L1+L2 description text and triggers on threshold ≥ 3.
# Placed AFTER _looks_like_bus_interconnect_protocol so the
# test_detector_general_not_brand_keyword anchor (which scans only the
# bus-protocol detector block) does not flag serial-protocol features
# such as "chip select" (substring "CHI").
_SERIAL_PROTO_FEATURES: List[tuple[str, re.Pattern]] = [
    # 1. role-pair: master/slave OR controller/target OR transmitter/receiver
    #    OR DTE/DCE. Any of these dual-role pairs marks a serial peripheral.
    ("role_pair",
     re.compile(r"\b(?:master|controller)s?\b.{0,200}?"
                r"\b(?:slave|target|peripheral|subordinate)s?\b|"
                r"\b(?:slave|target|peripheral|subordinate)s?\b.{0,200}?"
                r"\b(?:master|controller)s?\b|"
                r"\b(?:transmitter|transmit)s?\b.{0,200}?"
                r"\b(?:receiver|receive)s?\b|"
                r"\b(?:receiver|receive)s?\b.{0,200}?"
                r"\b(?:transmitter|transmit)s?\b|"
                r"\bDTE\b.{0,200}?\bDCE\b|\bDCE\b.{0,200}?\bDTE\b",
                re.IGNORECASE | re.DOTALL)),
    # 2. shift-register primitive
    ("shift_register",
     re.compile(r"\bshift\s+registers?|\bshifting\b|\bshifted\b",
                re.IGNORECASE)),
    # 3. serial / synchronous serial / asynchronous serial
    ("serial_concept",
     re.compile(r"\b(?:synchronous|asynchronous)?\s*serial\b",
                re.IGNORECASE)),
    # 4. clock / bit-rate control primitive — generator OR divisor OR
    #    prescaler OR bit-time/bit-rate (frame-based protocols like CAN
    #    use "nominal bit rate" / "bit time" / "bit timing" instead of
    #    "baud" terminology).
    ("clock_baud_control",
     re.compile(r"\bbaud\s*(?:rate|divisor|generator)\b|"
                r"\b(?:clock|sclk|sck)\s+"
                r"(?:divisor|prescal(?:er|e)|select|generator)\b|"
                r"\b(?:nominal\s+)?bit\s+(?:rate|time|timing)\b",
                re.IGNORECASE)),
    # 5. small fixed external pin count (≤ 8 pins, often 2-4) — for the
    #    pure wire-protocol-spec family. UART chip specs have more pins
    #    so won't fire here, but they hit the role_pair / shift_register
    #    features instead.
    ("small_pin_count",
     re.compile(r"\b(?:total of|has)\s+\d+\s+external\s+pin|"
                r"\b(?:two|three|four|five|six|2|3|4|5|6)\s+(?:external\s+)?pins?\b",
                re.IGNORECASE)),
    # 6. dedicated function pin / start-stop framing / data line / frame
    #    delimiter (frame-based protocols use START OF FRAME / END OF
    #    FRAME markers rather than per-bit start/stop bits).
    ("dedicated_function_pin",
     re.compile(r"\b(?:slave\s+select|chip\s+select|start\s+bit|stop\s+bit|"
                r"data\s+line|clock\s+line|enable\s+pin|select\s+pin|"
                r"asynchronous\s+communication\s+bits|"
                r"start\s+of\s+frame|end\s+of\s+frame|frame\s+delimiter)\b",
                re.IGNORECASE)),
]


# ---------------------------------------------------------------------
# ORGANIC #542 — crypto_accelerator detector. Hardware AES/SHA/HMAC/ECC
# and similar cipher engines pair an algorithm data-path with a register
# interface. Two mandatory features: (a) algorithm_family names a real
# cipher algorithm — deny-guard prevents prose like "encrypted data path"
# from false-firing; (b) at least one other crypto feature. No brand names.
_CRYPTO_FEATURES: List[tuple] = [
    ("algorithm_family", re.compile(
        r"\bAES\b|\bSHA[-_]?(?:[0-9]+)?\b|\bHMAC\b|"
        r"\bChaCha(?:20)?\b|\bPoly1305\b|\bECC\b|\bRSA\b|"
        r"\b3DES\b|\bblowfish\b|\bcamellia\b",
        re.IGNORECASE)),
    ("crypto_operation", re.compile(
        r"\b(?:encrypt|decrypt|crypt)(?:ion|ing|or)?\b|"
        r"\b(?:sign|verif)(?:ature|ication|ying|y|ies)?\b|"
        r"\bhash\s+(?:digest|function|core|computation|output)\b|"
        r"\bmessage\s+digest\b",
        re.IGNORECASE)),
    ("key_material", re.compile(
        r"\bkey\s+(?:schedule|expansion|loading|management|material|"
        r"length|size|register|stream)\b|"
        r"\b(?:initialization\s+vector|IV)\b|\bnonce\b|\bsalt\b",
        re.IGNORECASE)),
    ("cipher_mechanics", re.compile(
        r"\bkey\s+(?:schedule|expansion|round)\b|"
        r"\b[Ss][- ]?[Bb]ox\b|\bsubstitution[- ]permutation\b|"
        r"\bGalois\s+field\b|\bGF\s*\(\s*2\b|"
        r"\bblock\s+cipher\b|\bstream\s+cipher\b|"
        r"\b(?:ECB|CBC|CTR|GCM|OFB|CFB)\b",
        re.IGNORECASE)),
    ("width_marker", re.compile(
        r"\b(?:128|192|256)[- ]?(?:bit|b)\b|"
        r"\b(?:KEYLEN|KEY_LEN|KEY_SIZE|KEY_WIDTH)\b",
        re.IGNORECASE)),
]


def _looks_like_crypto_accelerator(l1, l2) -> bool:
    """ORGANIC #542 — True iff L1+L2 exhibit the mandatory algorithm_family
    feature PLUS at least one additional crypto feature (>=2 total).
    Walks all string leaves. No benchmark-specific names."""
    parts: List[str] = []
    for layer in (l1, l2):
        if isinstance(layer, dict):
            _harvest_strings(layer, parts)
    text = "\n".join(parts)
    if not text:
        return False
    hit_names = {name for name, pat in _CRYPTO_FEATURES if pat.search(text)}
    if "algorithm_family" not in hit_names:
        return False  # deny-guard: must name a real cipher algorithm
    return len(hit_names) >= 2


# ORGANIC #542 — bus_peripheral detector. Register-mapped peripheral IP:
# SW-visible register map + bus subordinate interface. Mandatory feature:
# register_map (requires explicit register-map/regmap/hjson/SW-accessible-
# register evidence — prevents generic bus specs from false-firing).
_BUS_PERIPHERAL_FEATURES: List[tuple] = [
    ("register_map", re.compile(
        r"\bregister\s+map\b|\bregmap\b|\bhjson\b|"
        r"\baddress\s+map\b|"
        r"\bmemory[- ]mapped\s+(?:register|interface)\b|"
        r"\bSW[- ]?(?:accessible|visible)\s+register\b",
        re.IGNORECASE)),
    ("bus_subordinate", re.compile(
        r"\bsubordinat(?:e|ing)\b|\bslave\s+(?:interface|port|connection)\b|"
        r"\btarget\s+(?:interface|port|connection)\b|"
        r"\bregister[- ]?(?:bank|block|file)\b",
        re.IGNORECASE)),
    ("bus_interface", re.compile(
        r"\bTL[-_ ]?UL\b|\bTILELINK[- ]UL\b|\bAPB\b|\bAXI[- ]?Lite\b|"
        r"\bAHB\b|\bWishbone\b|\bAvalonMM\b|\bbusif\b",
        re.IGNORECASE)),
    ("register_fields", re.compile(
        r"\bbit\s+field\b|\bRW\b|\bRO\b|\bWO\b|\bW1C\b|"
        r"\bread[- ]?only\s+register\b|\bwrite[- ]?only\s+register\b|"
        r"\bstatus\s+register\b|\bcontrol\s+register\b",
        re.IGNORECASE)),
    ("address_decode", re.compile(
        r"\baddress\s+(?:decode|offset|space)\b|"
        r"\bbase\s+address\b|"
        r"\boffset\b.{0,40}\b0x[0-9A-Fa-f]+\b",
        re.IGNORECASE | re.DOTALL)),
]


def _looks_like_bus_peripheral(l1, l2) -> bool:
    """ORGANIC #542 — True iff L1+L2 exhibit the mandatory register_map
    feature PLUS >=3 bus_peripheral features total. Walks all string leaves.
    No benchmark-specific names."""
    parts: List[str] = []
    for layer in (l1, l2):
        if isinstance(layer, dict):
            _harvest_strings(layer, parts)
    text = "\n".join(parts)
    if not text:
        return False
    hit_names = {name for name, pat in _BUS_PERIPHERAL_FEATURES
                 if pat.search(text)}
    if "register_map" not in hit_names:
        return False  # deny-guard: must have explicit register-map evidence
    return len(hit_names) >= 3


# ---------------------------------------------------------------------
# ORGANIC-20260606 #450 — processor_cpu detector. The registry has had
# the class since v1.6.522 (rtl_gen=null → spec-to-rtl / IP-catalog
# glue) but NO inference branch ever returned it: every CPU fell to the
# digital_arithmetic_primitive catch-all, so class-gated gates, #439
# tb_gen routing and oracle shapes used arithmetic semantics on cores
# that need instruction-execution + architectural-state verification.
# Structural, brand-free features; the ISA-bearing feature (f1/f2) is
# MANDATORY so prose like "command processor" can never false-fire.
_PROCESSOR_CPU_FEATURES = [
    ("isa_family", re.compile(
        r"\bRISC[-_ ]?V\b|\bRV(?:32|64)[IMAFDCEB]*\b", re.IGNORECASE)),
    ("instruction_semantics", re.compile(
        r"\binstruction\s+(?:set|fetch|decode|memory|bus|stream)\b|"
        r"\bISA\b", re.IGNORECASE)),
    ("architectural_state", re.compile(
        r"\bprogram\s+counter\b|\bregister\s+file\b|"
        r"\barchitectural\s+state\b", re.IGNORECASE)),
    ("core_noun", re.compile(
        r"\b(?:CPU|processor|microprocessor|soft[- ]?core)\b",
        re.IGNORECASE)),
    ("memory_bus", re.compile(
        r"\b(?:wishbone|ibus|dbus)\b|memory[- ]mapped|"
        r"\bsram_(?:addr|rdata|wdata)\b", re.IGNORECASE)),
    ("execution_units", re.compile(
        r"\bload[/-]store\b|\bbranch\s+instruction|\bALU\b",
        re.IGNORECASE)),
]


def _looks_like_processor_cpu(l1, l2) -> bool:
    """True iff L1+L2 exhibit >=3 processor features AND at least one
    ISA-bearing feature (isa_family / instruction_semantics). Walks all
    string leaves; NO benchmark-specific core names (#450)."""
    parts = []
    for layer in (l1, l2):
        if isinstance(layer, dict):
            _harvest_strings(layer, parts)
    text = "\n".join(parts)
    if not text:
        return False
    hit_names = {name for name, pat in _PROCESSOR_CPU_FEATURES
                 if pat.search(text)}
    if not ({"isa_family", "instruction_semantics"} & hit_names):
        return False        # deny-guard: no ISA context, no CPU claim
    return len(hit_names) >= 3


def _looks_like_serial_peripheral_protocol(
        l1: Optional[dict], l2: Optional[dict]) -> bool:
    """True iff the L1+L2 content exhibits ≥3 of the 6 serial-peripheral
    structural features. Walks ALL string leaves so the detector works
    across L doc schema variations. NO benchmark-specific brand names.
    """
    parts: List[str] = []
    for layer in (l1, l2):
        if isinstance(layer, dict):
            _harvest_strings(layer, parts)
    text = "\n".join(parts)
    if not text:
        return False
    hits = sum(1 for _, pat in _SERIAL_PROTO_FEATURES if pat.search(text))
    return hits >= 3


# ---------------------------------------------------------------------
# Convenience: per-class L-doc requirement table (used by M1).
# ---------------------------------------------------------------------
# Each entry maps a class to (mandatory_layers, conditional_layers).
# Conditional layers are conditioned on profile booleans:
#   "L5"  -> has_analog
#   "L11" -> has_otp OR has_calibration
#   "L12" -> has_calibration
#   "L13" -> has_lab_calibration
_CONDITIONAL_LAYER_GUARDS = {
    "L5": ("has_analog",),
    "L11": ("has_otp", "has_calibration"),
    "L12": ("has_calibration",),
    "L13": ("has_lab_calibration",),
    "L7": ("has_command_protocol", "has_fsm"),
    "L10": ("has_command_protocol",),
    "L6": ("has_fsm", "has_command_protocol"),
    "L3": ("has_command_protocol",),
    # Completeness layers (L24-L27). All four are guarded on profile flags
    # that no CURRENT detector sets → they default absent → the conditional
    # layer resolves to `skip` → it is NOT presence-enforced → NO false-fail
    # on any current chip. They auto-activate (→ mandatory) the moment a
    # detector/profile sets the flag (e.g. a future dedicated MEMS or memory-
    # module class, or a project that has entered the physical-signoff flow).
    #   L24 signoff / L25 reliability-mission-profile → `targets_signoff`
    #     (a fabricated chip that has reached / declared physical signoff).
    #   L26 MEMS/transduction  → `is_mems` OR `has_mechanical_transduction`.
    #   L27 memory-module SPD  → `is_memory_module`.
    "L24": ("targets_signoff",),
    "L25": ("targets_signoff",),
    "L26": ("is_mems", "has_mechanical_transduction"),
    "L27": ("is_memory_module",),
}


# Completeness layers (L24-L27) — added to `conditional` for EVERY class so
# `required_layers` classifies them (never silently drops one). Each is guarded
# (see _CONDITIONAL_LAYER_GUARDS) on a profile flag that no current detector
# sets, so they resolve to `skip` by default → NOT presence-enforced → NO
# false-fail on any current chip. This keeps the L1-L13 mandatory floor
# byte-unchanged (incl. the fail-closed unknown/bare_fpga → 13 mandatory) while
# making L24/L25 enforceable once a project declares `targets_signoff` and
# L26/L27 enforceable once a dedicated MEMS / memory-module class opts in.
_COMPLETENESS_CONDITIONAL = ["L24", "L25", "L26", "L27"]

_CLASS_LAYER_REQUIREMENTS = {
    "aid_class_half_duplex": {
        "mandatory": ["L1", "L2", "L3", "L4", "L5", "L6", "L7",
                      "L8", "L9", "L10", "L11", "L12", "L13"],
        "conditional": list(_COMPLETENESS_CONDITIONAL),
    },
    "digital_cmd_driven": {
        "mandatory": ["L1", "L2", "L3", "L4", "L6", "L7", "L8", "L9", "L10"],
        "conditional": ["L5", "L11", "L12", "L13"] + _COMPLETENESS_CONDITIONAL,
    },
    "mixed_signal_otp": {
        "mandatory": ["L1", "L2", "L3", "L4", "L5", "L6", "L7",
                      "L8", "L9", "L10", "L11"],
        "conditional": ["L12", "L13"] + _COMPLETENESS_CONDITIONAL,
    },
    "pure_analog": {
        "mandatory": ["L1", "L2", "L5", "L8", "L13"],
        "conditional": ["L3", "L6", "L7", "L10", "L11", "L12"]
                       + _COMPLETENESS_CONDITIONAL,
    },
    "bare_fpga": {
        # Maintain legacy 13/13 path — fail-closed when we can't tell.
        "mandatory": ["L1", "L2", "L3", "L4", "L5", "L6", "L7",
                      "L8", "L9", "L10", "L11", "L12", "L13"],
        "conditional": list(_COMPLETENESS_CONDITIONAL),
    },
    "unknown": {
        # Fail-closed default — every existing project keeps the legacy
        # 13/13 contract until L1/L2 are produced.
        "mandatory": ["L1", "L2", "L3", "L4", "L5", "L6", "L7",
                      "L8", "L9", "L10", "L11", "L12", "L13"],
        "conditional": list(_COMPLETENESS_CONDITIONAL),
    },
}


# Universe of layers that `required_layers` classifies as mandatory / skip.
# L1-L13 (the classic presence set) + the completeness layers L24-L27. The
# advanced/protocol layers L14-L23 are intentionally NOT presence-enforced by
# this brain (they remain opt-in, same as before), so they are excluded here.
_ALL_LAYERS = [f"L{i}" for i in range(1, 14)] + ["L24", "L25", "L26", "L27"]


def required_layers(profile: Dict[str, Any]) -> Dict[str, List[str]]:
    """Return {"mandatory": [...], "skip": [...]} for the given profile.

    Used by phase1_all_l_docs_present_check (M1) to drop conditional
    layers when the IC class doesn't carry them.

    Wave 36: any layer that is neither mandatory nor conditional for
    the class gets added to skip — e.g. for `pure_analog`, L4/L9 are
    not part of either list and should be SKIP, not "missing".
    """
    cls = profile.get("ic_class", "unknown")
    spec = _CLASS_LAYER_REQUIREMENTS.get(
        cls, _CLASS_LAYER_REQUIREMENTS["unknown"]
    )
    mandatory = list(spec["mandatory"])
    conditional = list(spec["conditional"])

    skip: List[str] = []
    for layer in conditional:
        guards = _CONDITIONAL_LAYER_GUARDS.get(layer, ())
        # Conditional layer becomes mandatory iff ANY of its guards is
        # True in the profile; else it gets SKIPped.
        triggers = [g for g in guards if profile.get(g) is True]
        if triggers:
            mandatory.append(layer)
        else:
            skip.append(layer)
    # Add any L1..L13 layer not already classified as mandatory or
    # conditional → silent skip.
    classified = set(mandatory) | set(skip)
    for layer in _ALL_LAYERS:
        if layer not in classified:
            skip.append(layer)
    return {"mandatory": mandatory, "skip": skip}


# ---------------------------------------------------------------------
# v1.6.523 — verification-track accessor (for #358-followon: generic
# digital IP / CPUs / arithmetic primitives that the AID half-duplex
# reference TB can NEVER bind). Reads programs/ic_class_registry.json
# and surfaces the per-class `verification_track` + applicability flags
# so the phase2 runner + flow_compliance_check can SKIP (not FAIL)
# gates that are structurally inapplicable to the detected class.
#
# Fail-closed default: an unknown / unregistered class is treated as
# `aid_protocol` with every flag applicable, so existing AID-class FAIL
# logic stays fully engaged when we have no positive evidence.
# ---------------------------------------------------------------------
_REGISTRY_PATH = Path(__file__).resolve().parent / "ic_class_registry.json"

# Fail-closed default — applies when the class is unknown / unregistered
# OR the registry is missing the verification-track fields.
_DEFAULT_VERIFICATION_FLAGS: Dict[str, Any] = {
    "verification_track": "aid_protocol",
    "command_protocol_applicable": True,
    "analog_applicable": True,
    "half_duplex_bus": True,
    "registry_matched": False,
}


def _load_registry() -> dict:
    try:
        return json.loads(_REGISTRY_PATH.read_text())
    except Exception:
        return {"classes": []}


def _lookup_registry_class(ic_class: str) -> Optional[dict]:
    """Find a registry class entry by name OR synonym (chip-AGNOSTIC)."""
    if not ic_class:
        return None
    reg = _load_registry()
    for c in (reg.get("classes") or []):
        if c.get("name") == ic_class:
            return c
        if ic_class in (c.get("synonyms") or []):
            return c
    return None


def class_tree_node_for(ic_class: str) -> Dict[str, Any]:
    """re #495 Stage 2 — translate a REGISTRY class name into a class-tree node.

    The registry (snake_case) and ``agents/class_kb/class-tree.yaml``
    (kebab-case) share no names, so a ``class_path`` written by the registry
    side cannot be resolved by the tree side. Each registry entry now declares
    where it belongs, with a status that says what that declaration is WORTH:

      ``mapped``                   node exists and its template carries a floor
      ``mapped_floorless``         node exists, template deliberately has no
                                   floor (any-ic / digital-ic are categorical
                                   intermediates) — resolving there is honest
                                   and scores nothing
      ``mapped_template_missing``  node exists, NO template — resolving there is
                                   measurably identical to not resolving at all
      ``unmappable``               no node can be asserted without over-claiming

    Returns ``{"node", "status", "basis", "registry_matched"}``. An unknown name
    fails closed to ``status="unregistered"`` and ``node=None`` so no caller can
    mistake ignorance for a mapping. chip-AGNOSTIC: a table lookup.
    """
    cfg = _lookup_registry_class(ic_class)
    if cfg is None:
        return {"node": None, "status": "unregistered", "basis": "",
                "registry_matched": False}
    node = cfg.get("class_tree_node")
    return {
        "node": node if isinstance(node, str) and node else None,
        "status": cfg.get("class_tree_node_status") or "undeclared",
        "basis": cfg.get("class_tree_node_basis") or "",
        "registry_matched": True,
    }


def class_verification_flags(ic_class: str) -> Dict[str, Any]:
    """Return the verification-track applicability flags for ``ic_class``.

    Keys:
      verification_track            -- "aid_protocol" | "generic_full_stack"
      command_protocol_applicable   -- bool
      analog_applicable             -- bool
      half_duplex_bus               -- bool
      registry_matched              -- bool (False = fail-closed default)

    Fail-closed: an unknown / unregistered class returns the AID-protocol
    default (every flag applicable) so no existing FAIL path is weakened.
    """
    cfg = _lookup_registry_class(ic_class)
    flags = dict(_DEFAULT_VERIFICATION_FLAGS)
    if cfg is None:
        flags["ic_class"] = ic_class
        return flags
    flags["registry_matched"] = True
    flags["ic_class"] = ic_class
    # Only override defaults with explicitly-present registry fields, so
    # a partially-annotated entry still fails closed on absent fields.
    if isinstance(cfg.get("verification_track"), str):
        flags["verification_track"] = cfg["verification_track"]
    for k in ("command_protocol_applicable", "analog_applicable",
              "half_duplex_bus"):
        if isinstance(cfg.get(k), bool):
            flags[k] = cfg[k]
    return flags


# ---------------------------------------------------------------------
# Protocol-synth dispatch reachability (ORGANIC-20260531, v0.2.32)
# ---------------------------------------------------------------------
# `detect_ic_class` is the routing key for the Phase-1 protocol-synth
# dispatch blocks in phase1_doc_one_shot_runner.py ([14e/15] R55 + the
# post-R55 [14e2/15] bus_interconnect block). Those blocks gate the ~80
# hand-wired built-in `*_protocol_synth` calls behind an `if ic_class in
# (...)` test. If `detect_ic_class` returns a class that NO dispatch block
# fires for, every built-in protocol synth is SILENTLY skipped (the inline
# structural detectors — the real gate — never even run). That is the
# silent-skip hazard ORGANIC-20260531 was filed on (the Avalon
# digital_arithmetic_primitive routing surprise).
#
# ROOT-CAUSE FIX (Option A from the backlog): the inline protocol detectors
# are content-only and self-gating (each carries its own mutex), so the
# ic_class gate adds NO safety — only the silent-skip hazard. We therefore
# make the dispatch reachable for EVERY class `detect_ic_class` can return.
# `ALL_IC_CLASSES` is the closed set of class strings the function assigns;
# `test_protocol_synth_dispatch_reachability.py` pins it against the source
# so it cannot drift. `PROTOCOL_SYNTH_DISPATCH_CLASSES` is the SINGLE source
# of truth the runner imports for its gate, and equals `ALL_IC_CLASSES` so
# no class is silently unrouted. If a future class is ever deliberately left
# out of the dispatch set, the runner's reachability self-check surfaces an
# EXPLICIT `protocol_dispatch_skipped.json` signal (fail-closed) instead of
# silently dropping the protocol synths.
#
# General, not benchmark-keyword: these are class TAXONOMY strings (the same
# tokens `detect_ic_class` assigns), never a chip / vendor / benchmark name.
ALL_IC_CLASSES: frozenset = frozenset({
    "unknown",
    "bare_fpga",
    "aid_class_half_duplex",
    "processor_cpu",           # ORGANIC-20260606 #450
    "crypto_accelerator",      # ORGANIC #542
    "bus_peripheral",          # ORGANIC #542
    "pure_analog",
    "mixed_signal_otp",
    "digital_cmd_driven",
    "bus_interconnect_protocol",
    "serial_peripheral_protocol",
    "digital_arithmetic_primitive",
    "data_converter",          # ORGANIC #613
})

# Every class reaches the protocol-synth dispatch (Option A). Kept as a
# distinct name (not a literal `= ALL_IC_CLASSES` inline at the call site)
# so a future narrowing is a one-line, test-covered change here rather than
# an edit buried in the 51k-line runner.
PROTOCOL_SYNTH_DISPATCH_CLASSES: frozenset = frozenset(ALL_IC_CLASSES)


def protocol_synth_dispatch_classes() -> frozenset:
    """ic_classes for which the runner's protocol-synth dispatch fires.

    The runner imports this as the gate for its hand-wired protocol-synth
    chain so the gate has ONE source of truth instead of a tuple literal
    copied into the runner. Equals `ALL_IC_CLASSES` (every class reachable)
    per the ORGANIC-20260531 root-cause fix.
    """
    return PROTOCOL_SYNTH_DISPATCH_CLASSES


def protocol_synth_unreachable_classes() -> frozenset:
    """Classes `detect_ic_class` can return that NO dispatch block fires for.

    This is the silent-skip set. Empty == the dispatch is fully reachable
    (the closed state). A non-empty result means a class is silently dropped
    and the runner's self-check must surface it as an explicit signal.
    """
    return frozenset(ALL_IC_CLASSES) - frozenset(PROTOCOL_SYNTH_DISPATCH_CLASSES)


def is_aid_protocol_track(ic_class: str) -> bool:
    """True iff the class verifies via the AID half-duplex reference TB.

    A class is on the AID track iff verification_track == "aid_protocol"
    AND half_duplex_bus is True. Anything else (generic_full_stack, or a
    protocol-track class whose half_duplex_bus flag is explicitly False)
    cannot bind the 3-port clk/reset_n/id_bus reference TB.
    """
    flags = class_verification_flags(ic_class)
    return (flags.get("verification_track") == "aid_protocol"
            and flags.get("half_duplex_bus") is True)


__all__ = [
    "detect_ic_class",
    "required_layers",
    "class_verification_flags",
    "is_aid_protocol_track",
    "ALL_IC_CLASSES",
    "PROTOCOL_SYNTH_DISPATCH_CLASSES",
    "protocol_synth_dispatch_classes",
    "protocol_synth_unreachable_classes",
]


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: ic_class_profile.py <project_dir>")
        sys.exit(2)
    project = Path(sys.argv[1]).resolve()
    profile = detect_ic_class(project)
    print(json.dumps(profile, indent=2))
