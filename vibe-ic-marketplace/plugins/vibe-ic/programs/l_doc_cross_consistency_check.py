#!/usr/bin/env python3
"""l_doc_cross_consistency_check.py — D3 program-first capture of the
``phase1-output-verify`` skill's "Cross-doc consistency" checklist (item 3).

ENFORCEMENT: advisory

Background
==========
``skills/phase1-output-verify/SKILL.md`` asked the AI to perform, *by eye*,
a set of inter-document set-membership relations over the typed L*.json
layer documents emitted by ``phase1_one_shot_runner``. Two of those
relations are purely structural (set-membership over already-typed JSON
fields) and need no judgment — they are extracted here so the skill can
delegate instead of narrate.

Implemented relations (chip-AGNOSTIC, declarative)
==================================================
R_pin_table_subset_ports
    Every L1 ``pin_table[]`` pin name must appear in the L9 integration
    spec's port list (``ports`` / ``top_ports`` / ``top_level_ports`` /
    ``dtop_top_level.ports`` — first populated wins), modulo aliases
    declared on the L1 entry (``aliases`` / ``rtl_name`` / ``board_name``).
    The flow's chip-top wrapper is generated from L9, so an L1 pin that
    never lands in L9 silently disappears from the design.

    ATTRIBUTION (#791) — a violation of this relation is one of two
    defects living in DIFFERENT files, and the finding names which:

      ``L1_PIN_TABLE_NON_PORT``    (WARN)  the L1 pin table carries a
          token that was never a pin — repair the L1 extractor; the
          design is intact.
      ``L9_PORT_LIST_INCOMPLETE``  (ERROR) a pin the documents declare
          as a port never reached L9 — the port is gone from the design.
      ``UNATTRIBUTED``             (WARN)  the typed corpus establishes
          neither side. Never guessed onto L9 (which would manufacture a
          port defect) nor onto L1 (which would silence a real one).

    The split is ATTRIBUTION ONLY: the relation verdict, the
    ``violations`` list and the program exit code are unchanged.

R_otp_bytes_subset_layout
    Every address referenced by an L11 ``otp_bytes[]`` entry
    (``address`` / ``addr`` / ``offset`` / ``byte_offset``) must be a
    declared field/offset in the L4 ``otp_layout`` (its ``fields[]`` or
    ``read_map[]``/``write_map[]`` offsets, plus any field with an
    explicit ``offset``/``address``). An OTP image byte that targets an
    address the regmap never declares is an inconsistent burn map.

Escape valves (the established Phase-1 ``no_<field>_in_input`` convention)
=========================================================================
A relation is reported **N/A** (not FAIL) — never silently PASSed — when
the *target* side is legitimately empty AND the corresponding extractor
escape-valve flag is set, e.g. L9 ``ports`` empty with
``no_top_module_in_input``/``no_integration_in_input``, or L4
``otp_layout`` empty with ``no_otp_in_input``/``no_otp_layout_in_input``.
This mirrors how ``phase1_structured_field_substance_check.py`` honors the
same flags so the gate does not false-fire on CPU / analog / no-OTP ICs.

What is intentionally NOT here (kept as AI judgment in the skill)
================================================================
The skill's other two listed relations require structure the typed
corpus does not actually carry, so encoding them as a program would mean
inventing a threshold/field the spec never gives (forbidden):
  * "L3.opcodes hex set ⊂ L9.fsm_states transitions" — L3 opcodes are
    instruction encoding patterns, not bus command hex bytes, and L9
    carries no ``transitions`` sub-structure.
  * "L3.verdict_byte_offset == rig_topology.fingerprint_byte_index" —
    ``rig_topology.fingerprint_byte_index`` does not exist anywhere in
    the typed L docs.
Those stay in the skill prose as a judgment residual.

Usage
=====
    python3 l_doc_cross_consistency_check.py <project_dir|generated_docs_dir>
    python3 l_doc_cross_consistency_check.py <dir> --json [out.json]

Exit codes
==========
    0  PASS (>=1 relation actually judged and none violated)
    0  VACUOUS_PASS — generated_docs absent, OR every relation came back
       N/A so the gate judged NOTHING. Both print the ``VACUOUS_PASS:``
       line-start sentinel that ``flow_compliance_check`` reads, so the
       step is credited in the VACUOUS_PASS tier rather than as a plain
       PASS. rc is 0 because neither case is a failure.
    1  FAIL (a real cross-doc subset violation)
    2  argument or I/O error

Wiring
======
ADVISORY at flow step D1 (``advisory_program_exit_zero``). It is not
blocking because it reddens published runs whose L1 ``pin_table`` carries
extractor pollution rather than genuinely lost pins; see the PR that wired
it for the measured per-run split. Promotion to ``program_exit_zero``
requires the L1 extractor repair, then a re-measurement — not a judgement
call.

#791 makes that split MACHINE-READABLE rather than a claim in this
paragraph. Measured over all 108 tracked run roots (12 FAIL / 81 N/A /
15 PASS, and every ``violations`` list — unchanged by the split): of 58
absent pins, 20 are ``L1_PIN_TABLE_NON_PORT``, 5 are
``L9_PORT_LIST_INCOMPLETE`` and 33 are ``UNATTRIBUTED``; 11 of the 12
FAILing roots resolve to a SINGLE cause. Enforcement is deliberately NOT
changed here — promoting the ``L9_PORT_LIST_INCOMPLETE`` half to blocking
would redden 1 published root, which is a flow-wiring decision with its
own measurement, not a side effect of naming the defect properly.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# L-doc discovery + lenient load (corpus uses raw 0x.. hex literals)
# ---------------------------------------------------------------------------
def _lenient_load(path: Path) -> Optional[Any]:
    if not path.is_file():
        return None
    text = path.read_text(errors="ignore")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return json.loads(re.sub(
                r'(?P<pfx>[:\[\,\s])0x([0-9a-fA-F]+)',
                lambda m: m.group("pfx") + str(int(m.group(2), 16)),
                text,
            ))
        except Exception:
            return None


def _find_gen_dir(target: Path) -> Optional[Path]:
    """Resolve the generated_docs directory from a project dir, a
    phase1 dir, or the generated_docs dir itself."""
    if (target / "L1_DATASHEET.json").is_file() or \
       any(target.glob("L1_*.json")):
        return target
    for cand in (
        target / "phase1" / "generated_docs",
        target / "generated_docs",
    ):
        if cand.is_dir():
            return cand
    return None


def _load_layer(gen_dir: Path, prefix: str) -> Optional[Dict[str, Any]]:
    """Load the first L<prefix>_*.json (or L<prefix>.json) under gen_dir."""
    exact = gen_dir / f"{prefix}.json"
    if exact.is_file():
        return _lenient_load(exact)
    for cand in sorted(gen_dir.glob(f"{prefix}_*.json")):
        obj = _lenient_load(cand)
        if isinstance(obj, dict):
            return obj
    return None


def _flag_set(doc: Optional[Dict[str, Any]], *flag_keys: str) -> bool:
    if not isinstance(doc, dict):
        return False
    return any(doc.get(k) is True for k in flag_keys)


# ---------------------------------------------------------------------------
# Field accessors
# ---------------------------------------------------------------------------
def _norm(s: Any) -> str:
    return str(s).strip().lower()


def _l1_pin_aliases(entry: Dict[str, Any]) -> List[str]:
    """All names an L1 pin can legitimately appear under in L9."""
    out: List[str] = []
    for k in ("name", "rtl_name", "board_name"):
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            out.append(_norm(v))
    al = entry.get("aliases")
    if isinstance(al, list):
        out.extend(_norm(a) for a in al if isinstance(a, str) and a.strip())
    return out


def _l1_pin_primary(entry: Dict[str, Any]) -> str:
    for k in ("name", "rtl_name", "board_name"):
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            return _norm(v)
    return ""


def _l9_port_names(l9: Dict[str, Any]) -> Tuple[List[str], str]:
    """Return (port_names, source_key). First populated source wins."""
    # direct list-valued keys
    for key in ("ports", "top_ports", "top_level_ports", "top_module_pins"):
        v = l9.get(key)
        if isinstance(v, list) and v:
            names = [_norm(p.get("name") or p.get("rtl_name") or p.get("signal"))
                     for p in v if isinstance(p, dict)]
            names = [n for n in names if n]
            if names:
                return names, key
    # nested dtop_top_level.ports (may be list or grouped dict)
    dtop = l9.get("dtop_top_level")
    if isinstance(dtop, dict):
        v = dtop.get("ports")
        flat: List[Dict[str, Any]] = []
        if isinstance(v, list):
            flat = [p for p in v if isinstance(p, dict)]
        elif isinstance(v, dict):
            for grp in v.values():
                if isinstance(grp, list):
                    flat.extend(p for p in grp if isinstance(p, dict))
                elif isinstance(grp, dict):
                    flat.append(grp)
        names = [_norm(p.get("name") or p.get("rtl_name") or p.get("signal"))
                 for p in flat]
        names = [n for n in names if n]
        if names:
            return names, "dtop_top_level.ports"
    return [], ""


def _addr_of(entry: Dict[str, Any]) -> Optional[int]:
    """Coerce an OTP-byte / OTP-field address to an int, accepting
    int, '0x..' hex, or decimal-string forms."""
    for k in ("address", "addr", "offset", "byte_offset"):
        if k not in entry:
            continue
        v = entry[k]
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            s = v.strip()
            try:
                return int(s, 16) if s.lower().startswith("0x") else int(s, 10)
            except ValueError:
                continue
    return None


def _l11_otp_addrs(l11: Dict[str, Any]) -> List[int]:
    ob = l11.get("otp_bytes")
    out: List[int] = []
    if isinstance(ob, list):
        for e in ob:
            if isinstance(e, dict):
                a = _addr_of(e)
                if a is not None:
                    out.append(a)
    return out


def _l4_otp_declared_addrs(l4: Dict[str, Any]) -> Tuple[set, bool]:
    """Return (declared_addr_set, layout_present). An OTP layout is
    'present' if otp_layout exists and carries any fields/maps."""
    ol = l4.get("otp_layout")
    if not isinstance(ol, dict):
        return set(), False
    addrs: set = set()
    present = False
    for list_key in ("fields", "read_map", "write_map"):
        seq = ol.get(list_key)
        if isinstance(seq, list) and seq:
            present = True
            for e in seq:
                if isinstance(e, dict):
                    a = _addr_of(e)
                    if a is not None:
                        addrs.add(a)
    return addrs, present


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------
@dataclass
class RelationFinding:
    relation: str
    verdict: str          # PASS | FAIL | N/A
    detail: str = ""
    violations: Optional[List[Any]] = None
    # ORGANIC #791 — per-violation ATTRIBUTION. `violations` keeps its legacy
    # flat-name shape for every existing consumer; `causes` is the added
    # answer to "which file do I open?".
    causes: Optional[List[Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# ORGANIC #791 — ATTRIBUTION of an absent pin
#
# ONE VERDICT WAS HIDING TWO DEFECTS. `R_pin_table_subset_ports` reported
# "N L1 pin(s) absent from L9 ports" for two populations that live in
# DIFFERENT files:
#
#   * the L1 pin table carries a token that was never a pin (a register /
#     enum identifier, a language keyword, an SDC directive, a stdcell
#     library token, the design's OWN module name, a glob) — the design is
#     intact and the L1 EXTRACTOR is what needs repair;
#   * a pin the documents really do declare as a port never reached L9 —
#     the chip-top wrapper is generated from L9, so the port silently
#     disappears from the design, and L9 is what needs repair.
#
# A maintainer reading the old verdict could not tell which file to open,
# and the counts were not comparable across cells (14 absent on one cell
# was mostly extractor noise; 2 on another was a real supply pin). Naming
# the wrong subject is the defect class this repo has closed twice already
# (#760 — a gate blamed the testbench for a bad L9 field; #761 — a SKIP
# stated a filter fact as a layer fact); this is the same shape again.
#
# WHAT THE SPLIT MAY AND MAY NOT DO
# ---------------------------------
# It may NOT filter. Every pin that was a violation before is a violation
# after; the relation verdict, the `violations` list and the program exit
# code are unchanged. A "fix" that made half the population disappear
# would silence the genuinely-lost ports along with the extractor noise —
# the failure mode the issue explicitly demands be guarded against.
# ATTRIBUTION ONLY.
#
# WHY THERE IS A THIRD BUCKET
# ---------------------------
# Measured over every tracked run root: two absent pins can be BYTE-
# IDENTICAL in the typed corpus and still belong to different defects — an
# AES mode-encoding symbol and an analog supply pin both arrive as
# `{name, mode, rtl_name, board_name, function, evidence}` and nothing
# else. The structural key the issue proposed ("a field inside a register
# definition, a member of an enum") was checked against the corpus and is
# ABSENT: the register map does not declare those names either, so keying
# on it would be a dead predicate. Inventing a field the documents never
# give is what this gate's own header forbids. Such a pin is reported
# `UNATTRIBUTED` — a true statement about the evidence — never guessed
# onto L9 (which would manufacture a port defect) and never onto L1
# (which would silence a real one).
#
# chip-AGNOSTIC: HDL identifier syntax, IEEE 1364/1800 reserved words, the
# SDC / stdcell SHAPE predicates already encoded in the extractor, and the
# design's OWN extracted name. No chip, vendor, PDK or IC literal.
# ---------------------------------------------------------------------------
CAUSE_L1_NON_PORT = "L1_PIN_TABLE_NON_PORT"
CAUSE_L9_INCOMPLETE = "L9_PORT_LIST_INCOMPLETE"
CAUSE_UNATTRIBUTED = "UNATTRIBUTED"

# Severity is per DEFECT, not per rule. A port the documents declare that
# never reached the layer the chip-top wrapper is generated from is gone
# from the silicon — ERROR. A non-pin token in a document leaves the design
# intact — WARN. An unattributable pin cannot be charged to either side —
# WARN, and it says so. The relation's own verdict and the program's exit
# code are deliberately NOT derived from these: changing enforcement is a
# flow-wiring decision with its own measured blast radius, not a side
# effect of naming the defect properly.
_CAUSE_SEVERITY = {
    CAUSE_L9_INCOMPLETE: "ERROR",
    CAUSE_L1_NON_PORT: "WARN",
    CAUSE_UNATTRIBUTED: "WARN",
}
_CAUSE_ACTION = {
    CAUSE_L9_INCOMPLETE: "fix L9: the port list is incomplete",
    CAUSE_L1_NON_PORT: "fix L1: the pin table names a non-port",
    CAUSE_UNATTRIBUTED:
        "unattributed: the typed corpus establishes neither side",
}
# Loudest first, so the actionable half leads the string.
_CAUSE_ORDER = (CAUSE_L9_INCOMPLETE, CAUSE_L1_NON_PORT, CAUSE_UNATTRIBUTED)

# A direction a walker actually ESTABLISHED. The Phase-1 pin merge already
# encodes this invariant verbatim ("every genuine port reaches this pass
# with mode ∈ {input, output, inout}; `mode=unspecified` means no walker
# ever established a direction — the signature of a bare identifier
# mention"). This is one more consumer of that rule, not a new one.
_FUNCTIONAL_DIRECTIONS = frozenset({
    "input", "output", "inout", "in", "out", "i", "o", "io",
    "bidir", "bidirectional",
})
_HDL_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

# `io_standard` values the Phase-1 extractor derives from the pin NAME rather
# than from the document. They corroborate nothing — see
# `_pin_port_only_attribute`.
_NAME_DERIVED_IO_STANDARDS = frozenset({"power", "ground"})

_HDL_PREDICATES: Optional[Tuple[Any, Any, Any]] = None


def _hdl_token_predicates() -> Tuple[Any, Any, Any]:
    """The EXTRACTOR's own non-port token predicates, reused not re-copied.

    `phase1_doc_one_shot_runner` is the single home of the reserved-word set
    and of the SDC-directive / stdcell-library SHAPE rejectors. Importing
    them keeps ONE definition; a second copy here would rot away from the
    first the day a keyword is added.

    Optional, so this gate still runs standalone against a corpus with no
    runner importable — and the degradation is FAIL-SAFE in the right
    direction: without the predicates the affected names fall through to
    ``UNATTRIBUTED``, never to a confident blame on the wrong file.
    """
    global _HDL_PREDICATES
    if _HDL_PREDICATES is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            import phase1_doc_one_shot_runner as _R
            _HDL_PREDICATES = (frozenset(_R._VERILOG_RESERVED_KEYWORDS),
                               _R._is_sdc_directive_token,
                               _R._is_stdcell_lib_shape_token)
        except Exception:  # nosec — attribution must never break the gate
            _HDL_PREDICATES = (frozenset(), None, None)
    return _HDL_PREDICATES


def _pin_direction(entry: Dict[str, Any]) -> Tuple[str, bool]:
    """(established direction, a direction key was PRESENT at all).

    The two are different evidence. `mode="unspecified"` is a walker's
    explicit "I looked and could not establish one" — the signature of a
    bare identifier mention. A MISSING key means no walker recorded
    anything, which establishes nothing in either direction and must not be
    read as proof the name is not a port.
    """
    present = False
    for k in ("mode", "direction"):
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            present = True
            if _norm(v) in _FUNCTIONAL_DIRECTIONS:
                return _norm(v), True
    return "", present


def _pin_port_only_attribute(entry: Dict[str, Any]) -> str:
    """Name the attribute only a real port DECLARATION SITE can fill.

    A pad / constraints table gives an `io_standard`; a port declaration
    gives a bit range. Prose that merely mentions an identifier gives
    neither. Extraction-strategy provenance is deliberately NOT used: the
    loose backtick scanner is registered among the port-table strategies
    and appears on BOTH populations, so it separates nothing.

    `POWER` / `GROUND` are excluded because they are NOT document-stated:
    the Phase-1 extractor DERIVES them from the pin's own NAME (a name
    containing VDD/VCC becomes `POWER`, VSS/GND becomes `GROUND`), while
    every other value requires positive evidence in the doc text. Treating
    a name-derived marker as corroboration would be circular — the name
    would be vouching for itself — and the measured cost of getting this
    wrong is concrete: a supply RAIL lifted out of a "Supplies / levels"
    VOLTAGE table would be reported as a port L9 lost, sending the reader
    to the wrong file for a row that was never a port entry.
    """
    ios = entry.get("io_standard")
    if (isinstance(ios, str) and ios.strip()
            and _norm(ios) not in _NAME_DERIVED_IO_STANDARDS):
        return "io_standard"
    w = entry.get("width")
    if isinstance(w, int) and not isinstance(w, bool) and w >= 1:
        return "width"
    msb, lsb = entry.get("msb"), entry.get("lsb")
    if (isinstance(msb, int) and not isinstance(msb, bool)
            and isinstance(lsb, int) and not isinstance(lsb, bool)):
        return "bit_range"
    return ""


def _design_self_names(l1: Optional[Dict[str, Any]],
                       l9: Optional[Dict[str, Any]]) -> set:
    """The design's OWN module / IC names, from the typed corpus only."""
    out: set = set()
    for doc, keys in ((l9, ("top_module", "top_module_name", "ic_name")),
                      (l1, ("ic_name", "product_name", "chip_name"))):
        if not isinstance(doc, dict):
            continue
        for k in keys:
            v = doc.get(k)
            if isinstance(v, str) and v.strip() and v.strip() != "UNKNOWN_IC":
                out.add(_norm(v))
    return out


def _classify_absent_pin(entry: Dict[str, Any], primary: str,
                         self_names: set) -> Tuple[str, str]:
    """(cause, reason) for ONE absent pin. Decisive non-port tests first.

    Each early test names a class that can NEVER be a port whatever else the
    entry carries, so a fabricated direction cannot promote it.
    """
    reserved, is_sdc, is_stdcell = _hdl_token_predicates()
    nm = primary or ""
    low = _norm(nm)
    if not _HDL_IDENT_RE.match(nm):
        # `wbs_*` — a glob is not a name any port can have.
        return CAUSE_L1_NON_PORT, "not_an_hdl_identifier"
    if low in reserved:
        # `input` / `output` / `logic` — the language forbids the name.
        return CAUSE_L1_NON_PORT, "hdl_reserved_word"
    if low in self_names:
        # A design's own top module is not one of its ports.
        return CAUSE_L1_NON_PORT, "design_own_module_name"
    if is_sdc is not None and is_sdc(nm):
        return CAUSE_L1_NON_PORT, "sdc_constraint_directive"
    if is_stdcell is not None and is_stdcell(nm):
        return CAUSE_L1_NON_PORT, "stdcell_library_token"
    _dir, dir_key_present = _pin_direction(entry)
    if not _dir and dir_key_present:
        return CAUSE_L1_NON_PORT, "no_direction_established"
    attr = _pin_port_only_attribute(entry)
    if _dir and attr:
        return (CAUSE_L9_INCOMPLETE,
                "port_declaration_corroborated_by_" + attr)
    return CAUSE_UNATTRIBUTED, "no_structural_corroboration_in_typed_corpus"


def _attribute_absent_pins(absent: List[Tuple[str, Dict[str, Any]]],
                           self_names: set) -> List[Dict[str, Any]]:
    """Per-pin attribution records, sorted by pin name."""
    recs = []
    for primary, entry in absent:
        cause, reason = _classify_absent_pin(entry, primary, self_names)
        recs.append({"pin": primary, "cause": cause, "reason": reason,
                     "severity": _CAUSE_SEVERITY[cause]})
    return sorted(recs, key=lambda r: r["pin"])


def _cause_summary(causes: List[Dict[str, Any]]) -> str:
    """`1 L9_PORT_LIST_INCOMPLETE (fix L9: …), 2 L1_PIN_TABLE_NON_PORT (…)`."""
    counts: Dict[str, int] = {}
    for rec in causes:
        counts[rec["cause"]] = counts.get(rec["cause"], 0) + 1
    return ", ".join("%d %s (%s)" % (counts[c], c, _CAUSE_ACTION[c])
                     for c in _CAUSE_ORDER if counts.get(c))


def _rel_pin_table_subset_ports(l1, l9) -> RelationFinding:
    rid = "R_pin_table_subset_ports"
    if not isinstance(l1, dict) or not isinstance(l9, dict):
        return RelationFinding(rid, "N/A", "L1 or L9 absent")
    pins = l1.get("pin_table")
    if not isinstance(pins, list) or not pins:
        if _flag_set(l1, "no_pin_table_in_input", "no_pinout_in_input"):
            return RelationFinding(rid, "N/A", "L1 pin_table legitimately empty (no_pin_table_in_input)")
        return RelationFinding(rid, "N/A", "L1 pin_table empty (no pins to relate)")
    port_names, src = _l9_port_names(l9)
    if not port_names:
        if _flag_set(l9, "no_top_module_in_input", "no_integration_in_input",
                     "no_ports_in_input"):
            return RelationFinding(rid, "N/A",
                                   "L9 port list legitimately empty (no_top_module_in_input)")
        # Target side empty WITHOUT an escape flag while L1 has pins =>
        # honest FAIL: the pins cannot land anywhere.
        # #791 — this branch conflated the same two defects, so it is
        # attributed by the same classifier: an L1 pin table that is pure
        # extractor noise must not read as "L9 lost every port".
        # The counts in the summary cover the WHOLE population; the two
        # published lists keep the legacy 20-item cap and are cut from the
        # same document order, so they can never name different pins.
        _absent = [(_l1_pin_primary(p), p) for p in pins
                   if isinstance(p, dict)]
        _causes = _attribute_absent_pins(_absent, _design_self_names(l1, l9))
        _first20 = {nm for nm, _p in _absent[:20]}
        return RelationFinding(rid, "FAIL",
                               f"L1 declares {len(_absent)} "
                               f"pins but L9 has no port list and no escape flag"
                               + (f" — {_cause_summary(_causes)}" if _causes else ""),
                               violations=[nm for nm, _p in _absent[:20]],
                               causes=[c for c in _causes
                                       if c["pin"] in _first20])
    port_set = set(port_names)
    missing: List[str] = []
    absent_entries: List[Tuple[str, Dict[str, Any]]] = []
    for p in pins:
        if not isinstance(p, dict):
            continue
        aliases = _l1_pin_aliases(p)
        if not aliases:
            continue
        if not any(a in port_set for a in aliases):
            nm = _l1_pin_primary(p) or aliases[0]
            missing.append(nm)
            absent_entries.append((nm, p))
    if missing:
        # #791 — the count alone was uninterpretable. Attribute each absent
        # pin to the file that must change. The FAIL, the violation list and
        # the exit code are unchanged: this names the defect, it does not
        # filter it.
        seen: set = set()
        uniq = []
        for nm, p in absent_entries:
            if nm not in seen:
                seen.add(nm)
                uniq.append((nm, p))
        # The counts in the summary cover the WHOLE population; both
        # published lists are name-sorted and capped at 20, so they always
        # name the same pins.
        causes = _attribute_absent_pins(uniq, _design_self_names(l1, l9))
        published = sorted(set(missing))[:20]
        return RelationFinding(rid, "FAIL",
                               f"{len(missing)} L1 pin(s) absent from L9 ports[{src}]"
                               + (f" — {_cause_summary(causes)}" if causes else ""),
                               violations=published,
                               causes=[c for c in causes
                                       if c["pin"] in set(published)])
    return RelationFinding(rid, "PASS",
                           f"all {len(pins)} L1 pins present in L9 ports[{src}]")


def _rel_otp_bytes_subset_layout(l11, l4) -> RelationFinding:
    rid = "R_otp_bytes_subset_layout"
    if not isinstance(l11, dict) or not isinstance(l4, dict):
        return RelationFinding(rid, "N/A", "L11 or L4 absent")
    otp_addrs = _l11_otp_addrs(l11)
    if not otp_addrs:
        if _flag_set(l11, "no_otp_in_input", "no_otp_bytes_in_input",
                     "no_calibration_in_input"):
            return RelationFinding(rid, "N/A",
                                   "L11 otp_bytes legitimately empty (no_otp_in_input)")
        return RelationFinding(rid, "N/A", "L11 otp_bytes empty (no addresses to relate)")
    declared, layout_present = _l4_otp_declared_addrs(l4)
    if not layout_present:
        if _flag_set(l4, "no_otp_in_input", "no_otp_layout_in_input"):
            return RelationFinding(rid, "N/A",
                                   "L4 otp_layout legitimately empty (no_otp_layout_in_input)")
        return RelationFinding(rid, "FAIL",
                               f"L11 references {len(otp_addrs)} OTP byte address(es) "
                               f"but L4 otp_layout declares none and has no escape flag",
                               violations=sorted(set(otp_addrs))[:20])
    undeclared = sorted({a for a in otp_addrs if a not in declared})
    if undeclared:
        return RelationFinding(rid, "FAIL",
                               f"{len(undeclared)} L11 OTP address(es) not declared in L4 otp_layout",
                               violations=undeclared[:20])
    return RelationFinding(rid, "PASS",
                           f"all {len(set(otp_addrs))} L11 OTP addresses declared in L4 otp_layout")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def check(target: Path) -> Tuple[str, List[RelationFinding], Dict[str, Any]]:
    gen_dir = _find_gen_dir(target)
    if gen_dir is None:
        return "VACUOUS_PASS", [], {"generated_docs": None}
    l1 = _load_layer(gen_dir, "L1")
    l4 = _load_layer(gen_dir, "L4")
    l9 = _load_layer(gen_dir, "L9")
    l11 = _load_layer(gen_dir, "L11")
    findings = [
        _rel_pin_table_subset_ports(l1, l9),
        _rel_otp_bytes_subset_layout(l11, l4),
    ]
    fails = [f for f in findings if f.verdict == "FAIL"]
    passes = [f for f in findings if f.verdict == "PASS"]
    if fails:
        verdict = "FAIL"
    elif passes:
        verdict = "PASS"
    else:
        # EVERY relation came back N/A — the gate examined nothing. Awarding a
        # plain PASS here credits the ordinary verdict tier over zero relations,
        # which is the "empty scan mistaken for a clean one" defect this family
        # exists to prevent. Reachable on any IC that legitimately carries no
        # pin_table and no OTP. rc stays 0 (this is not a failure); the
        # `VACUOUS_PASS` line-start sentinel is what
        # `flow_compliance_check._stdout_signals_vacuous` reads to promote the
        # step to the VACUOUS_PASS tier instead of PASS.
        verdict = "VACUOUS_PASS"
    summary = {
        "generated_docs": str(gen_dir),
        "relations_checked": len(findings),
        "pass": sum(1 for f in findings if f.verdict == "PASS"),
        "fail": len(fails),
        "na": sum(1 for f in findings if f.verdict == "N/A"),
    }
    return verdict, findings, summary


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Cross-doc structural consistency over phase1 L*.json.")
    ap.add_argument("target", help="project dir, phase1 dir, or generated_docs dir")
    ap.add_argument("--json", nargs="?", const="-", default=None,
                    help="emit JSON report (to path, or stdout if no path)")
    args = ap.parse_args(argv)

    target = Path(args.target)
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    verdict, findings, summary = check(target)
    report = {
        "gate": "l_doc_cross_consistency_check",
        "verdict": verdict,
        "summary": summary,
        "findings": [asdict(f) for f in findings],
    }

    if args.json is not None:
        blob = json.dumps(report, indent=2, ensure_ascii=False)
        if args.json == "-":
            print(blob)
        else:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(blob + "\n", encoding="utf-8")
            print(f"{verdict}: l_doc_cross_consistency_check (report -> {out})")
    else:
        print(f"{verdict}: l_doc_cross_consistency_check — "
              f"pass={summary.get('pass', 0)} fail={summary.get('fail', 0)} "
              f"na={summary.get('na', 0)}")
        for f in findings:
            line = f"  [{f.verdict}] {f.relation}"
            if f.detail:
                line += f" — {f.detail}"
            print(line)
            if f.violations:
                print(f"      violations: {f.violations}")
            # #791 — print the per-pin attribution, so the console reader
            # gets the same answer as the JSON reader: which file to open.
            for rec in (f.causes or []):
                print(f"      [{rec['severity']}] {rec['pin']}: "
                      f"{rec['cause']} ({rec['reason']})")

    if verdict == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
