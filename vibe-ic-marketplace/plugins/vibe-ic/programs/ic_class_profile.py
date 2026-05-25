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
        if isinstance(v, list) and v:
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
    for j in (l4, l11, l14_otp):
        if not isinstance(j, dict):
            continue
        for k in otp_keys:
            v = j.get(k)
            if v:
                return True
        # Nested under L4_REGMAP / L11_OTP_CONTENT structure
        for nested_key in (
            "L4_REGMAP", "L11_OTP_CONTENT", "L14_OTP_CONTENT",
        ):
            nv = j.get(nested_key)
            if isinstance(nv, dict):
                for k in nested_otp_keys:
                    if nv.get(k):
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


def _l5_has_analog(l5: Optional[dict]) -> bool:
    """v1.6.523 — for #358 P2 root fix. Filter low_confidence stubs
    (v1.6.269 emitter behavior) so docs that legitimately mention
    'no DAC needed' / 'ESD by PDK default' as N/A context don't
    falsely classify the chip as pure_analog. Only high-confidence
    analog blocks count as positive analog markers.
    """
    if not isinstance(l5, dict):
        return False
    if l5.get("no_analog") is True:
        return False
    for k in ("analog_blocks", "blocks", "adi_blocks", "topology",
             "wake_modes", "rx_event_pipeline_summary"):
        v = l5.get(k)
        if isinstance(v, list) and v:
            high_conf = [b for b in v
                         if not (isinstance(b, dict) and b.get("low_confidence", False))]
            if high_conf:
                return True
        elif v and not isinstance(v, list):
            return True
    return False


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
def detect_ic_class(project_dir: Path) -> Dict[str, Any]:
    """Return an IC class profile dict for the given project.

    See module docstring for the full contract.  Falls back to
    `class="unknown"` on missing input — gates must treat this as
    fail-closed (run their existing FAIL logic).
    """
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
        "ic_class": "unknown",
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
    profile["has_analog"] = _l5_has_analog(l5)
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
        # Path-A skeleton or pre-Phase-2a project. Conservative default.
        # If facts.yaml exists assume bare_fpga / unknown.
        if (project / "facts.yaml").is_file():
            profile["ic_class"] = "bare_fpga"
        else:
            profile["ic_class"] = "unknown"
        return profile

    if profile["protocol_class"] == "aid_class":
        profile["ic_class"] = "aid_class_half_duplex"
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
            return profile
        profile["ic_class"] = "pure_analog"
        return profile

    if profile["is_mixed_signal"] and profile["has_otp"]:
        profile["ic_class"] = "mixed_signal_otp"
        return profile

    if profile["is_mixed_signal"]:
        # Mixed signal w/o OTP collapses to digital_cmd_driven if it has
        # commands; else mixed_signal_otp without otp is rare — fall back.
        if profile["has_command_protocol"]:
            profile["ic_class"] = "digital_cmd_driven"
            return profile

    if profile["is_pure_digital"] and profile["has_command_protocol"]:
        profile["ic_class"] = "digital_cmd_driven"
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
            return profile

    profile["ic_class"] = "unknown"
    return profile


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
}


_CLASS_LAYER_REQUIREMENTS = {
    "aid_class_half_duplex": {
        "mandatory": ["L1", "L2", "L3", "L4", "L5", "L6", "L7",
                      "L8", "L9", "L10", "L11", "L12", "L13"],
        "conditional": [],
    },
    "digital_cmd_driven": {
        "mandatory": ["L1", "L2", "L3", "L4", "L6", "L7", "L8", "L9", "L10"],
        "conditional": ["L5", "L11", "L12", "L13"],
    },
    "mixed_signal_otp": {
        "mandatory": ["L1", "L2", "L3", "L4", "L5", "L6", "L7",
                      "L8", "L9", "L10", "L11"],
        "conditional": ["L12", "L13"],
    },
    "pure_analog": {
        "mandatory": ["L1", "L2", "L5", "L8", "L13"],
        "conditional": ["L3", "L6", "L7", "L10", "L11", "L12"],
    },
    "bare_fpga": {
        # Maintain legacy 13/13 path — fail-closed when we can't tell.
        "mandatory": ["L1", "L2", "L3", "L4", "L5", "L6", "L7",
                      "L8", "L9", "L10", "L11", "L12", "L13"],
        "conditional": [],
    },
    "unknown": {
        # Fail-closed default — every existing project keeps the legacy
        # 13/13 contract until L1/L2 are produced.
        "mandatory": ["L1", "L2", "L3", "L4", "L5", "L6", "L7",
                      "L8", "L9", "L10", "L11", "L12", "L13"],
        "conditional": [],
    },
}


_ALL_LAYERS = [f"L{i}" for i in range(1, 14)]


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


__all__ = [
    "detect_ic_class",
    "required_layers",
]


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: ic_class_profile.py <project_dir>")
        sys.exit(2)
    project = Path(sys.argv[1]).resolve()
    profile = detect_ic_class(project)
    print(json.dumps(profile, indent=2))
