#!/usr/bin/env python3
"""
phase1_consistency_check.py — Cross-layer consistency gate (K4).

After each L1-L23 layer is produced, verify that values that appear in
multiple layers actually agree. Catches the "L3 says CRC poly 0x07, L8R
says 0x31" class of bug BEFORE it reaches RTL generation.

Rule types
----------
  Equal       path_a == path_b (scalar or canonicalised)
  KeysEqual   set(keys(path_a)) == set(keys(path_b))
  Subset      set_a ⊆ set_b
  Derives     path_c == f(path_a, path_b, ...)

Usage
-----
    python3 phase1_consistency_check.py generated_docs/
    python3 phase1_consistency_check.py --json generated_docs/
    python3 phase1_consistency_check.py --only L3,L8R generated_docs/  # partial check

Exit codes
----------
    0 — all rules pass (or all triggered rules pass)
    1 — one or more rules failed
    2 — argument or I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# v0.62 Bug #4: shared no-protocol sentinel logic — keeps doc-presence and
# consistency gates in sync on which layers are protocol-implied.
sys.path.insert(0, str(Path(__file__).parent))
from _phase1_sentinel import (  # noqa: E402
    SENTINEL_OPTIONAL_LAYERS,
    is_no_protocol_sentinel_active_in_docs,
)


# ---------------------------------------------------------------------------
# Lenient JSON loader (benchmark uses 0x70 hex literals)
# ---------------------------------------------------------------------------
def lenient_load(path: Path):
    if not path.exists():
        return None
    text = path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(re.sub(
            r'(?P<pfx>[:\[\,\s])0x([0-9a-fA-F]+)',
            lambda m: m.group("pfx") + str(int(m.group(2), 16)),
            text,
        ))


FILE_BY_LAYER = {
    "L1":  "L1_DATASHEET.json",
    "L2":  "L2_FRS.json",
    "L3":  "L3_CMD_PROTOCOL.json",
    "L4":  "L4_REGMAP.json",
    "L5":  "L5_ADI_SPEC.json",
    "L6":  "L6_CONTROL_LOGIC.json",
    "L7":  "L7_TEST_DEBUG.json",
    "L8":  "L8_TIMING_WAVEFORM.json",
    "L8R": "L8_RTL_CONSTANTS.json",
    "L9":  "L9_INTEGRATION_SPEC.json",
}


def fetch_path(docs: Dict[str, Any], layered_path: str) -> Any:
    """layered_path: e.g. 'L3.frame_format.crc'; returns value or None if missing."""
    layer, _, rest = layered_path.partition(".")
    if layer not in docs:
        return None
    node = docs[layer]
    if not rest:
        return node
    for part in rest.split("."):
        # Handle list[index] tokens like 'command_set[0].name'
        m = re.match(r"(.+?)\[(\d+)\]$", part)
        if m:
            name, idx = m.group(1), int(m.group(2))
            if not isinstance(node, dict) or name not in node:
                return None
            node = node[name]
            if not isinstance(node, list) or idx >= len(node):
                return None
            node = node[idx]
        else:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
    return node


def l8r_clock_frequency_hz(docs: Dict[str, Any]) -> Any:
    """Resolve the current or legacy L8R clock-frequency representation.

    The producer migrated from ``clock_frequency_hz`` to a top-level
    ``clock_mhz`` plus per-domain ``freq_hz``/``freq_mhz`` fields.  A
    consistency consumer must accept those equivalent schema spellings, while
    still returning ``None`` when the producer supplied no clock at all.
    """
    legacy = fetch_path(docs, "L8R.clock_frequency_hz")
    if isinstance(legacy, (int, float)):
        return legacy

    mhz = fetch_path(docs, "L8R.clock_mhz")
    if isinstance(mhz, (int, float)):
        return mhz * 1_000_000

    domains = fetch_path(docs, "L8R.clock_domains")
    if isinstance(domains, list):
        for domain in domains:
            if not isinstance(domain, dict):
                continue
            hz = domain.get("freq_hz")
            if isinstance(hz, (int, float)):
                return hz
            domain_mhz = domain.get("freq_mhz")
            if isinstance(domain_mhz, (int, float)):
                return domain_mhz * 1_000_000
    return None


# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------
@dataclass
class Rule:
    id: str
    kind: str           # equal | keys_equal | subset | derives | substring_in
    severity: str       # error | warn | info
    a: str              # layer-qualified path
    b: str = ""
    reason: str = ""
    fn: Optional[Callable] = None  # for 'derives'
    applies_if: Optional[Callable[[Dict[str, Any]], bool]] = None  # skip rule if False


def canonicalise_crc(v: Any) -> str:
    """Extract a comparable CRC-poly token from various string forms.
    Returns '__none__' if the value clearly means 'no CRC' (for ICs that
    don't carry CRC on the wire — I2C, SPI, UART, APB)."""
    if v is None:
        return "__none__"
    s = str(v).lower().strip()
    # Common "no CRC" sentinels
    if re.match(r'^(none|no|n/a|not applicable)\b', s) or s == "":
        return "__none__"
    if "no crc" in s or "no inherent crc" in s or "no checksum" in s or "per-byte ack" in s:
        return "__none__"
    m = re.search(r'poly[=\s]*(0x[0-9a-f]+|\d+)', s) or re.search(r'0x([0-9a-f]+)', s)
    if m:
        tok = m.group(1) if m.group(1).startswith("0x") else "0x" + m.group(1)
        return tok.lower()
    if re.fullmatch(r'0x[0-9a-f]+', s) or re.fullmatch(r'\d+', s):
        return s
    return ""


# Initial rule set — 12 rules covering the most critical cross-layer
# consistency that bites during RTL generation / synthesis.
RULES: List[Rule] = [
    Rule(id="R_ic_name_l1_l2",
         kind="substring_in", severity="warn",
         a="L2.ic_name", b="L1.ic_name",
         reason="L2 ic_name should be a substring of (or identical to) L1 ic_name."),

    Rule(id="R_crc_poly_l3_l8r",
         kind="equal", severity="error",
         a="L3.frame_format.crc", b="L8R.crc8_polynomial",
         reason="CRC polynomial in L3 protocol spec must match L8R RTL constant.",
         applies_if=lambda docs: (fetch_path(docs, "L3.frame_format.crc") is not None
                                   and fetch_path(docs, "L8R.crc8_polynomial") is not None)),

    Rule(id="R_crc_init_l3_l8r",
         kind="substring_in", severity="warn",
         a="L8R.crc8_init", b="L3.frame_format.crc",
         reason="L8R CRC init should be referenced in L3 frame_format.crc text.",
         applies_if=lambda docs: (fetch_path(docs, "L3.frame_format.crc") is not None
                                   and fetch_path(docs, "L8R.crc8_init") is not None)),

    Rule(id="R_pinout_l1_l5",
         kind="subset", severity="warn",
         a="L1.pinout_keys", b="L5.analog_digital_interfaces_signals",
         reason="L1 pins typically map to 1..N L5 ADI signals (e.g. ID_BUS → BUS_RX/BUS_TX/BUS_OE); warn-only.",
         applies_if=lambda docs: (aggregate_value(docs, "L1.pinout_keys") is not None
                                   and aggregate_value(docs, "L5.analog_digital_interfaces_signals") is not None)),

    Rule(id="R_submodules_l6_l9",
         kind="subset", severity="error",
         a="L6.submodule_control_logic_keys", b="L9.instantiation_order_all",
         reason="Every submodule in L6 must appear in L9 instantiation_order.",
         applies_if=lambda docs: (aggregate_value(docs, "L6.submodule_control_logic_keys") is not None
                                   and aggregate_value(docs, "L9.instantiation_order_all") is not None)),

    Rule(id="R_clock_freq_positive",
         kind="derives", severity="error",
         a="L8R.clock_frequency_hz",
         reason="The L8R clock frequency must be positive (legacy "
                "clock_frequency_hz or current clock_mhz/clock_domains).",
         fn=lambda v: isinstance(v, (int, float)) and v > 0),

    Rule(id="R_bit_period_cycles",
         kind="derives", severity="warn",
         a="L8R.bit_period_cycles",
         reason="bit_period_cycles should equal round(L8.aid_bit_timing.bit_period_us * 1e-6 * clock_frequency_hz).",
         fn=None),  # evaluated specially below

    Rule(id="R_layer_documents_present",
         kind="derives", severity="error",
         a="__all_layers_present",
         reason="All 10 Phase-1 layer documents must exist before L9 gate.",
         fn=None),

    Rule(id="R_source_documents_nonempty",
         kind="derives", severity="warn",
         a="L1.source_documents",
         reason="L1 should cite source documents when produced from references.",
         fn=lambda v: isinstance(v, list) and len(v) >= 1),

    Rule(id="R_key_features_minlen",
         kind="derives", severity="warn",
         a="L1.overview.key_features",
         reason="L1 key_features should list at least 3 items.",
         fn=lambda v: isinstance(v, list) and len(v) >= 3),

    Rule(id="R_protocol_cmd_count",
         kind="derives", severity="warn",
         a="L3.command_set",
         reason="L3 command_set should list at least 1 command (protocol-ic only).",
         fn=lambda v: isinstance(v, list) and len(v) >= 1,
         applies_if=lambda docs: fetch_path(docs, "L3.command_set") is not None),

    Rule(id="R_test_modes_minlen",
         kind="derives", severity="warn",
         a="L7.test_modes",
         reason="L7 should enumerate at least one test mode.",
         fn=lambda v: isinstance(v, list) and len(v) >= 1),

    # --- New rules mined from 127-IC benchmark + real Yosys failure ---
    Rule(id="R_l9_no_dtop_self_collision",
         kind="derives", severity="error",
         a="L9.__self_collision_check",
         reason="L9 submodule key must not collide with dtop module name "
                "(Yosys gives 'Re-definition of module' error). "
                "Caught real bug in apb_gpio during phase2_pilot_synth.",
         fn=None),

    Rule(id="R_l5_l9_width_by_name",
         kind="derives", severity="warn",
         a="L5_L9.__width_by_name",
         reason="For any signal name present in both L5.analog_digital_interfaces "
                "and L9.dtop_top_level.ports, the declared widths should agree. "
                "Mined from benchmark: 94-99% of co-occurring signals have matching widths.",
         fn=None),

    Rule(id="R_l4_l5_width_by_name",
         kind="derives", severity="warn",
         a="L4_L5.__width_by_name",
         reason="For any field name present in both L4.register_map and L5 ADI list, "
                "width_bits should match.",
         fn=None),

    # ADVISORY: an L2/L15 "per-<axis>" (per-channel/per-column/per-bank/...)
    # parameterization of a quantity must be backed by an L4 register ARRAY,
    # not a single scalar register applied globally. High-precision (bound to
    # the exact register name); warn-only so it never hard-fails the gate.
    Rule(id="R_l2_per_axis_l4_array",
         kind="derives", severity="warn",
         a="L2_L4.__per_axis_granularity",
         reason="When L2/L15 asserts a per-<axis> (per-channel/column/bank/lane/…) "
                "parameterization of a quantity, L4 must expose it as a register "
                "ARRAY/table, not a single scalar register.",
         fn=None),
]


# ---------------------------------------------------------------------------
# Special accessors for aggregate values
# ---------------------------------------------------------------------------
def aggregate_value(docs: Dict[str, Any], token: str) -> Any:
    if token == "L1.pinout_keys":
        p = fetch_path(docs, "L1.pinout")
        return sorted(p.keys()) if isinstance(p, dict) else None
    if token == "L5.analog_digital_interfaces_signals":
        v = fetch_path(docs, "L5.analog_digital_interfaces")
        if not isinstance(v, list): return None
        return sorted({d.get("signal") for d in v if isinstance(d, dict) and "signal" in d})
    if token == "L6.submodule_control_logic_keys":
        v = fetch_path(docs, "L6.submodule_control_logic")
        return sorted(v.keys()) if isinstance(v, dict) else None
    if token == "L9.instantiation_order_all":
        v = fetch_path(docs, "L9.instantiation_order")
        # Extract submodule names from entries like "u_dclk (DCLK) - comment"
        raw = None
        if isinstance(v, dict):
            for key in ("order", "ordering"):
                if key in v and isinstance(v[key], list):
                    raw = v[key]; break
        elif isinstance(v, list):
            raw = v
        if raw is None:
            return None
        import re as _re
        names = set()
        for item in raw:
            if isinstance(item, str):
                # Match "u_xxx (XXX)" or "xxx" forms; extract class name then lowercase
                m = _re.search(r'\b([A-Z][A-Z0-9_]{1,20})\b', item)
                if m:
                    names.add(m.group(1).lower())
                else:
                    # Try instance name after "u_"
                    m = _re.search(r'u_(\w+)', item)
                    if m: names.add(m.group(1).lower())
        return sorted(names)
    if token == "__all_layers_present":
        return [l for l in FILE_BY_LAYER if l not in docs]
    return None


# ---------------------------------------------------------------------------
# Per-<axis> granularity cross-layer consistency (L2/L15 vs L4 regmap)
# ---------------------------------------------------------------------------
# When an FRS / behavioural requirement asserts that a quantity is
# parameterized PER an axis (per-channel / per-column / per-bank / per-lane …)
# the register map must expose that quantity as an ARRAY / table, not a single
# scalar register. The run that surfaced this: L2 said "per-output-channel
# scale" but L4 exposed one scalar SCALE register (and the RTL applied it
# globally) — a real doc-vs-doc inconsistency the gate missed.
#
# The check is HIGH-PRECISION by construction: it fires ONLY when a per-<axis>
# phrase is grammatically bound to the EXACT NAME of an L4 register that is a
# SCALAR (not an array). Anchoring on the register name (not a loose keyword
# co-occurrence) keeps false-positives near zero — a doc that literally writes
# "per-channel <regname>" almost always means an array of that register. It is
# advisory (severity=warn) so it never hard-fails the gate; the recall limit
# (the FRS noun must match the register name) is the SAFE direction for an
# advisory. chip-AGNOSTIC: a general parameterization-axis vocabulary + English
# grammar, no chip/vendor/SKU literal.
_PER_AXIS_WORDS = (
    "channel", "channels", "column", "columns", "row", "rows",
    "bank", "banks", "lane", "lanes", "tap", "taps", "way", "ways",
    "core", "cores", "element", "elements", "port", "ports",
    "pixel", "pixels", "band", "bands", "head", "heads",
    "filter", "filters", "kernel", "kernels", "partition", "partitions",
    "slice", "slices", "segment", "segments", "group", "groups",
    "neuron", "neurons", "unit", "units", "pe", "pes",
)
_AXIS_ALT = r'(?:' + '|'.join(_PER_AXIS_WORDS) + r')'
# Register/entry fields that mark an ARRAY (a count / replication / dimension).
_L4_ARRAY_COUNT_KEYS = ("count", "array_size", "num", "instances", "depth",
                        "array_length", "copies", "n", "num_entries", "entries")
_L4_ARRAY_FLAG_KEYS = ("array", "is_array", "replicated", "per_channel",
                       "per_axis", "banked", "indexed")


def _l4_register_entries(docs: Dict[str, Any]) -> List[dict]:
    """Every L4 register entry (dict form), across the regmap key variants."""
    for key in ("register_map", "registers", "regmap", "register_list",
                "control_registers_logical", "runtime_registers"):
        v = fetch_path(docs, f"L4.{key}")
        if isinstance(v, list):
            return [e for e in v if isinstance(e, dict)]
        if isinstance(v, dict):
            # dict-of-registers → synthesise entries carrying the key as name
            return [{"name": k, **(val if isinstance(val, dict) else {})}
                    for k, val in v.items()]
    return []


def _regname_re(name: str) -> Optional[str]:
    """Regex fragment matching a register NAME as it appears in prose, allowing
    an underscore to read as space/hyphen/underscore. Returns None for a name
    too short/blank to anchor safely (< 3 significant chars)."""
    parts = [p for p in re.split(r'_+', name.strip()) if p]
    if not parts or sum(len(p) for p in parts) < 3:
        return None
    return r'[\s\-_]+'.join(re.escape(p) for p in parts)


def _l4_register_is_array(entry: dict, all_names: List[str]) -> bool:
    """True when an L4 register entry denotes an ARRAY (so per-axis is honored)."""
    for k in _L4_ARRAY_COUNT_KEYS:
        v = entry.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and v > 1:
            return True
    for k in _L4_ARRAY_FLAG_KEYS:
        if entry.get(k) is True:
            return True
    name = str(entry.get("name", "")).strip()
    # An index/array form in the name: SCALE[8] / SCALE[i] / SCALEx8 / SCALE_7.
    if re.search(r'\[\s*\w+\s*\]|x\d+$|_\d+$', name):
        return True
    # Enumerated siblings: >=2 registers named <base><digits> / <base>_<digits>.
    base = name.lower()
    if base:
        sib = re.compile(r'^' + re.escape(base) + r'_?\w*\d+$')
        if sum(1 for s in all_names if s.lower() != base and sib.match(s.lower())) >= 2:
            return True
    return False


def _l2_l15_text(docs: Dict[str, Any]) -> str:
    """Concatenate the human-readable strings of the FRS/behavioural layers
    (L2, and L15 if the doc-set carries it) into one lower-cased blob."""
    chunks: List[str] = []

    def _walk(node):
        if isinstance(node, str):
            chunks.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    for layer in ("L2", "L15"):
        if layer in docs:
            _walk(docs[layer])
    return " ".join(chunks).lower()


def _per_axis_binds_register(text: str, regname: str) -> Optional[str]:
    """Return the matched per-<axis> phrase when ``text`` grammatically binds a
    per-<axis> parameterization to ``regname``, else None. Three bound forms:
      A  per[-]<mods><axis>[-]<name>      "per-output-channel scale"
      B  <name> per <mods><axis>          "a separate scale per channel"
      C  <axis>-wise <name>               "channel-wise scale"
    """
    nre = _regname_re(regname)
    if not nre:
        return None
    name_p = r'(?:' + nre + r')s?'        # tolerate a prose plural (scale/scales)
    mods = r'(?:[A-Za-z]+[\s\-]+){0,2}'   # up to 2 axis modifiers (output-, first-)
    pats = [
        re.compile(r'\bper[\s\-]+' + mods + r'(' + _AXIS_ALT + r')[\s\-]+' + name_p + r'\b', re.I),
        re.compile(r'\b' + name_p + r'[\s\-]+per[\s\-]+' + mods + r'(' + _AXIS_ALT + r')\b', re.I),
        re.compile(r'\b(' + _AXIS_ALT + r')[\s\-]?wise[\s\-]+' + name_p + r'\b', re.I),
    ]
    for p in pats:
        m = p.search(text)
        if m:
            return m.group(1)
    return None


def _per_axis_scalar_findings(docs: Dict[str, Any]) -> List[Tuple[str, str]]:
    """List of (register_name, axis) where L2/L15 asserts a per-<axis>
    parameterization of a register that L4 exposes as a SCALAR."""
    entries = _l4_register_entries(docs)
    if not entries:
        return []
    text = _l2_l15_text(docs)
    if "per" not in text and "wise" not in text:   # cheap early-out
        return []
    all_names = [str(e.get("name", "")) for e in entries]
    hits: List[Tuple[str, str]] = []
    for e in entries:
        name = str(e.get("name", "")).strip()
        if not name or _l4_register_is_array(e, all_names):
            continue
        axis = _per_axis_binds_register(text, name)
        if axis:
            hits.append((name, axis))
    return hits


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    rule_id: str
    severity: str
    passed: bool
    detail: str = ""


def evaluate(docs: Dict[str, Any], rules: List[Rule]) -> List[Finding]:
    out: List[Finding] = []
    # v0.62 Bug #4: detect once per evaluate() call so per-rule logic
    # below can ask "is the no-protocol sentinel active?" without
    # re-parsing JSON.
    no_protocol = is_no_protocol_sentinel_active_in_docs(docs)
    for r in rules:
        # Skip class-inappropriate rules
        if r.applies_if is not None:
            try:
                if not r.applies_if(docs):
                    out.append(Finding(r.id, "info", True, "N/A for this IC class"))
                    continue
            except Exception:
                pass
        a_val = aggregate_value(docs, r.a) if r.a.startswith("L") and "_keys" in r.a \
            or r.a.endswith("_signals") or r.a.endswith("_all") or r.a.startswith("__") \
            else fetch_path(docs, r.a)

        if r.kind == "equal":
            b_val = fetch_path(docs, r.b)
            # Canonicalise for CRC poly comparisons
            if "crc" in r.a.lower() or "crc" in r.b.lower():
                a_c = canonicalise_crc(a_val)
                b_c = canonicalise_crc(b_val)
                passed = bool(a_c) and bool(b_c) and a_c == b_c
                detail = f"a={a_val!r} (→{a_c}); b={b_val!r} (→{b_c})"
            else:
                passed = a_val is not None and b_val is not None and a_val == b_val
                detail = f"a={a_val!r}; b={b_val!r}"
            out.append(Finding(r.id, r.severity, passed, detail if not passed else ""))

        elif r.kind == "subset":
            b_val = aggregate_value(docs, r.b)
            if a_val is None or b_val is None:
                out.append(Finding(r.id, r.severity, False, f"missing side (a={a_val!r}, b={b_val!r})"))
                continue
            # Fuzzy subset: a ⊆ b if every element in a has a matching
            # entry in b. Match criteria (any one):
            #   - exact string equality
            #   - after stripping leading u_/i_/ic-name_ and trailing
            #     _fsm/_unit/_mem/_block/_stage/_core/_wrapper/_subsystem
            #   - one name contains the other as substring (either way)
            #   - they share a distinctive non-trivial word (>= 3 chars)
            GENERIC_SUFFIXES = ("_fsm", "_unit", "_mem", "_block", "_stage",
                                "_core", "_wrapper", "_subsystem",
                                "_logic", "_ctrl", "_module")
            GENERIC_TOKENS = {"core", "top", "dtop", "ctrl", "logic",
                              "stage", "unit", "block", "module", "wrapper"}
            def normalize(x):
                x = str(x).lower().strip()
                # Strip common instance prefixes
                for prefix in ("u_", "i_"):
                    if x.startswith(prefix): x = x[len(prefix):]
                # Strip generic class suffixes (repeatedly)
                changed = True
                while changed:
                    changed = False
                    for suffix in GENERIC_SUFFIXES:
                        if x.endswith(suffix):
                            x = x[:-len(suffix)]
                            changed = True
                return x
            def tokens(x):
                return {t for t in re.split(r'[_\-\s]+', str(x).lower())
                        if t and len(t) >= 3 and t not in GENERIC_TOKENS}
            a_items = [(orig, normalize(orig), tokens(orig)) for orig in a_val]
            b_items = [(normalize(orig), tokens(orig)) for orig in b_val]
            missing = []
            for orig, a_n, a_toks in a_items:
                matched = False
                for b_n, b_toks in b_items:
                    if a_n == b_n or a_n in b_n or b_n in a_n:
                        matched = True; break
                    if a_toks and b_toks and (a_toks & b_toks):
                        matched = True; break
                if not matched:
                    missing.append(orig)
            passed = len(missing) == 0
            detail = f"missing in b: {sorted(missing)}" if not passed else ""
            out.append(Finding(r.id, r.severity, passed, detail))

        elif r.kind == "keys_equal":
            b_val = aggregate_value(docs, r.b)
            passed = a_val is not None and b_val is not None and set(a_val) == set(b_val)
            detail = f"diff: only_a={sorted(set(a_val or [])-set(b_val or []))}, only_b={sorted(set(b_val or [])-set(a_val or []))}" if not passed else ""
            out.append(Finding(r.id, r.severity, passed, detail))

        elif r.kind == "substring_in":
            b_val = fetch_path(docs, r.b)
            if a_val is None or b_val is None:
                out.append(Finding(r.id, r.severity, False, f"a={a_val!r}, b={b_val!r}"))
                continue
            passed = str(a_val).strip('"\'').lower() in str(b_val).lower()
            detail = f"'{a_val}' not found in '{str(b_val)[:80]}'" if not passed else ""
            out.append(Finding(r.id, r.severity, passed, detail))

        elif r.kind == "derives":
            # R_bit_period_cycles: evaluate separately
            if r.id == "R_clock_freq_positive":
                if no_protocol and "L8R" not in docs:
                    out.append(Finding(
                        r.id, "info", True,
                        "skipped — L8R is sentinel-optional and absent"))
                    continue
                clock_hz = l8r_clock_frequency_hz(docs)
                passed = isinstance(clock_hz, (int, float)) and clock_hz > 0
                detail = f"resolved clock frequency was {clock_hz!r} Hz"
                out.append(Finding(
                    r.id, r.severity, passed, "" if passed else detail))
                continue
            if r.id == "R_l9_no_dtop_self_collision":
                # Extract dtop module name + submodule keys
                dtop = fetch_path(docs, "L9.dtop_top_level") or {}
                dtop_name = ""
                if isinstance(dtop, dict):
                    dtop_name = str(dtop.get("module_name") or dtop.get("name") or "").lower()
                if not dtop_name:
                    dtop_name = str(fetch_path(docs, "L9.ic_name") or "").lower()
                subs = fetch_path(docs, "L9.submodules") or {}
                collisions = []
                if isinstance(subs, dict) and dtop_name:
                    for k in subs.keys():
                        if str(k).lower() == dtop_name:
                            collisions.append(k)
                passed = not collisions
                detail = f"submodule(s) named same as dtop '{dtop_name}': {collisions}" if collisions else ""
                out.append(Finding(r.id, r.severity, passed, detail))
                continue
            if r.id == "R_l5_l9_width_by_name":
                # Build {signal_name -> width} from L5 and L9 ports, compare
                def name_width_map(items):
                    m = {}
                    if not isinstance(items, list):
                        return m
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        name = str(it.get("signal") or it.get("name") or "").lower().strip()
                        if not name:
                            continue
                        w = it.get("width")
                        if w is None:
                            w = it.get("width_bits") or it.get("bits")
                        if w is None:
                            continue
                        try:
                            m[name] = int(w)
                        except (TypeError, ValueError):
                            continue
                    return m
                l5 = fetch_path(docs, "L5.analog_digital_interfaces")
                l9_ports = fetch_path(docs, "L9.dtop_top_level.ports")
                # flatten grouped dict form
                if isinstance(l9_ports, dict):
                    flat = []
                    for v in l9_ports.values():
                        if isinstance(v, list): flat.extend(v)
                        elif isinstance(v, dict): flat.append(v)
                    l9_ports = flat
                m5 = name_width_map(l5)
                m9 = name_width_map(l9_ports)
                common = set(m5) & set(m9)
                mismatches = [n for n in common if m5[n] != m9[n]]
                if not common:
                    out.append(Finding(r.id, "info", True, "N/A — no shared signal names"))
                    continue
                passed = not mismatches
                detail = f"width mismatches ({len(mismatches)}/{len(common)}): "
                detail += ", ".join(f"{n}:L5={m5[n]},L9={m9[n]}" for n in mismatches[:5])
                out.append(Finding(r.id, r.severity, passed, detail if not passed else f"{len(common)} common signals, all widths agree"))
                continue
            if r.id == "R_l4_l5_width_by_name":
                def l4_widths(regmap):
                    m = {}
                    if isinstance(regmap, list):
                        for r_ in regmap:
                            if isinstance(r_, dict):
                                name = str(r_.get("name") or "").lower().strip()
                                w = r_.get("width_bits") or r_.get("width")
                                if name and w is not None:
                                    try: m[name] = int(w)
                                    except Exception: pass
                    return m
                l4 = fetch_path(docs, "L4.register_map") or fetch_path(docs, "L4.control_registers_logical")
                l5 = fetch_path(docs, "L5.analog_digital_interfaces")
                m4 = l4_widths(l4)
                m5 = {}
                if isinstance(l5, list):
                    for it in l5:
                        if isinstance(it, dict):
                            name = str(it.get("signal") or it.get("name") or "").lower().strip()
                            w = it.get("width") or it.get("width_bits")
                            if name and w is not None:
                                try: m5[name] = int(w)
                                except Exception: pass
                common = set(m4) & set(m5)
                if not common:
                    out.append(Finding(r.id, "info", True, "N/A — no shared field names"))
                    continue
                mismatches = [n for n in common if m4[n] != m5[n]]
                passed = not mismatches
                detail = f"width mismatches: " + ", ".join(f"{n}:L4={m4[n]},L5={m5[n]}" for n in mismatches[:5])
                out.append(Finding(r.id, r.severity, passed, detail if not passed else f"{len(common)} common fields, all widths agree"))
                continue
            if r.id == "R_l2_per_axis_l4_array":
                hits = _per_axis_scalar_findings(docs)
                if not hits:
                    out.append(Finding(r.id, "info", True,
                                       "N/A — no per-<axis> quantity bound to a scalar register"))
                    continue
                detail = ("; ".join(
                    f"L2/L15 says per-{axis} '{name}' but L4 exposes '{name}' as a "
                    f"single scalar register (expected an array/table)"
                    for name, axis in hits[:5]))
                out.append(Finding(r.id, r.severity, False, detail))
                continue
            if r.id == "R_bit_period_cycles":
                cycles = fetch_path(docs, "L8R.bit_period_cycles")
                bit_us = fetch_path(docs, "L8.aid_bit_timing.bit_period_us")
                clk = l8r_clock_frequency_hz(docs)
                if cycles is None or bit_us is None or clk is None:
                    out.append(Finding(r.id, r.severity, True, "skipped — a prerequisite value absent"))
                    continue
                expected = round(float(bit_us) * clk / 1e6)
                passed = int(cycles) == expected
                detail = f"have {cycles}, expected {expected} (= {bit_us} us × {clk} Hz / 1e6)"
                out.append(Finding(r.id, r.severity, passed, detail if not passed else ""))
                continue
            if r.id == "R_layer_documents_present":
                missing = aggregate_value(docs, "__all_layers_present") or []
                # v0.62 Bug #4: when no-protocol sentinel is active, layers
                # in SENTINEL_OPTIONAL_LAYERS (L3, L8R) are legitimately
                # absent — drop them from the "missing" list before judging.
                if no_protocol:
                    missing = [m for m in missing if m not in SENTINEL_OPTIONAL_LAYERS]
                passed = len(missing) == 0
                detail = f"missing layers: {missing}" if missing else ""
                if no_protocol and not missing:
                    detail = "no-protocol sentinel active; L3/L8R legitimately absent"
                out.append(Finding(r.id, r.severity, passed, detail))
                continue
            # v0.62 Bug #4: skip rules whose target layer is sentinel-optional
            # AND the project declared the no-protocol sentinel AND the layer
            # JSON is genuinely absent. Avoids false-FAIL like "L8R.clock_
            # frequency_hz value was None" on memory / analog ICs.
            target_layer = r.a.split(".", 1)[0] if "." in r.a else None
            if (
                no_protocol
                and target_layer in SENTINEL_OPTIONAL_LAYERS
                and target_layer not in docs
            ):
                out.append(Finding(
                    r.id, "info", True,
                    f"skipped — {target_layer} is sentinel-optional and absent",
                ))
                continue
            # Generic predicate
            a_val = fetch_path(docs, r.a)
            try:
                passed = bool(r.fn(a_val)) if r.fn else a_val is not None
            except Exception as e:
                passed = False
                detail = f"predicate raised: {e}"
                out.append(Finding(r.id, r.severity, passed, detail))
                continue
            detail = f"value was {a_val!r}" if not passed else ""
            out.append(Finding(r.id, r.severity, passed, detail))

    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def load_docs(docs_dir: Path) -> Dict[str, Any]:
    docs = {}
    for layer, fname in FILE_BY_LAYER.items():
        p = docs_dir / fname
        obj = lenient_load(p)
        if obj is not None:
            docs[layer] = obj
    return docs


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("docs_dir", help="Path to generated_docs/")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(argv)

    docs = load_docs(Path(args.docs_dir))
    findings = evaluate(docs, RULES)
    errors = [f for f in findings if f.severity == "error" and not f.passed]
    warns = [f for f in findings if f.severity == "warn" and not f.passed]

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2, ensure_ascii=False))
    else:
        for f in findings:
            tag = "PASS" if f.passed else ("WARN" if f.severity == "warn" else "FAIL")
            line = f"  [{tag}] {f.rule_id}"
            if f.detail:
                line += f"  — {f.detail[:160]}"
            print(line)
        print(f"\n{len(findings)-len(errors)-len(warns)}/{len(findings)} rules passed; "
              f"errors={len(errors)}, warnings={len(warns)}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
