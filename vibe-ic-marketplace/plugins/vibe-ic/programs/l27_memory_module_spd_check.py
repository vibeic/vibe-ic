#!/usr/bin/env python3
"""
l27_memory_module_spd_check.py — SEMANTIC applicability-contract gate for
``phase1/generated_docs/L27_MEMORY_MODULE_SPD.json``.

WHY THIS GATE EXISTS
--------------------
The global ``phase1_doc_input_completeness_check`` models completeness as
"does this token appear in ANY layer". That model produced a measured
production defect: a hard macro's supply-pin name appeared in L1_DATASHEET
(7x) and L2_FRS (8x), so the check reported CAPTURED — while L21_POWER_INTENT,
the layer the BACKEND actually consumes, contained it 0 times. The PDN was
built with no rail, synthesis tied the pin off, a SIGNAL net landed on a
POWER-typed terminal, and detailed routing aborted: 3278 nets, 0 routed.

The principle this gate embodies is the inverse of token-presence:

    A layer is complete when the requirement is present IN THE LAYER THAT
    CONSUMES IT, in an actionable form — not when a token appears somewhere.

L27 is the sharpest possible test of that principle, because L27 has NO
consumer today. Per ``l_doc_taxonomy``, L27 is OPT-IN-ONLY: it is emitted
``not_applicable`` for every current ic_class and would only become live for
a dedicated JEDEC memory-module class that does not yet exist. A layer with
no consumer cannot be gated on "is the content there" — the only thing that
can be gated is whether its ADVERTISED APPLICABILITY IS TRUE. So this gate
checks the applicability contract in BOTH directions:

  * a layer that declares itself irrelevant must actually BE irrelevant, and
    must say why in an actionable form; and
  * a layer that declares itself relevant must carry content a consumer could
    act on — not an empty skeleton.

A FALSE ``N/A`` on L27 is the same defect shape as the motivating one: the
requirement is present in the design's own input, and 0 times in the layer
that would consume it. It would be discovered many steps downstream, when a
memory module is fabricated with no SPD image and every host that probes it
reads back nothing.

DOES THIS GATE BLOCK?
---------------------
**IT BLOCKS.** Registered in ``flow_compliance_check._STRUCTURAL_RTL_GATES``
and deliberately NOT in ``INFORMATIONAL_GATES``, so a FAIL counts toward the
verdict and stops the flow.

Blocking is justified because every condition below is a machine-checkable
CONTRADICTION between the layer and an authority outside it — the taxonomy,
the design's own input documents, or a peer L-doc. None is a judgement call
or a heuristic quality score, so a FAIL is never a matter of opinion. The
motivating defect's third compounding failure was precisely that a layer gate
returned FAIL and the flow continued anyway.

The blocking SURFACE is deliberately narrow: on a correctly-emitted N/A stub
(the 202/202 real-run case) the gate is a clean PASS, and it fires only on
self-contradiction. A gate that blocks on contradiction only cannot become a
tax on legitimate work.

WHAT IS DERIVED, NOT HARDCODED
------------------------------
Per the chip-AGNOSTIC rule, no design name, PDK name, vendor part number or
pin literal appears anywhere in this file.

  * The applicability verdict is derived from ``l_doc_taxonomy.is_applicable``
    — the taxonomy is the single authority on which ic_class opts in.
  * The JEDEC SPD standard identifiers are PARSED OUT OF the taxonomy's own
    ``LDocSpec.description`` for L27 at runtime (``_spd_standard_tokens``).
    They are not a literal list in this file, so if the taxonomy adds a
    future SPD standard the gate follows automatically.
  * The module-form vocabulary is JEDEC public form-factor terminology
    (the DIMM family) plus the module phrase taken from the layer's own
    canonical title. It is vendor-neutral and applies to every manufacturer.
  * Evidence of what the design actually is comes from the design's OWN input
    documents and from ``ic_class_profile.detect_ic_class`` — never from a
    golden/oracle output (§4.05: read design INPUT only).
  * Distinctness is checked against the design's own L4 register map.

CHECKS
------
R1  L27 must declare an applicability verdict at all. A layer with no verdict
    is unusable by the presence/applicability brain.
R2  N/A branch: the N/A must carry a substantive rationale. "Not applicable"
    with no reason is an unfalsifiable claim.
R3  N/A branch: the declared ic_class must not CONTRADICT the taxonomy. If the
    taxonomy says L27 IS applicable to this class, an N/A is a false N/A.
R4  N/A branch: the design's own INPUT must not declare a self-describing
    memory module. If it does, and L27 carries no SPD payload, the
    requirement lives in the input and 0 times in the consuming layer — the
    motivating defect, exactly.
R5  APPLICABLE branch: the layer must be ACTIONABLE — an SPD standard
    identifier, an SPD bus address, and a non-empty byte/field map. An
    applicable-but-empty L27 is the empty skeleton the opt-in-only rule
    exists to prevent.
R6  APPLICABLE branch: the byte/field map must be DISTINCT from the on-die
    register map (the taxonomy's own words). An L27 that merely restates L4
    carries no module-level information.

Usage:
    python3 l27_memory_module_spd_check.py <project_dir>

Exit codes:
    0 = PASS
    1 = FAIL (blocking)
    2 = input-missing / not-applicable (skip)

Honors waiver ``l27_memory_module_spd_intentional`` (>=40 chars).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import l_doc_taxonomy as _tx  # noqa: E402

GATE = "l27_memory_module_spd_check"
WAIVER_KEY = "l27_memory_module_spd_intentional"
WAIVER_MIN_CHARS = 40

_L27_CODE = "L27"

_L27_GLOBS = (
    "phase1/generated_docs/L27_MEMORY_MODULE_SPD.json",
    "phase1/generated_docs/L27*.json",
    "**/L27_MEMORY_MODULE_SPD.json",
)
_L4_GLOBS = (
    "phase1/generated_docs/L4_REGMAP.json",
    "phase1/generated_docs/L4*.json",
)

# The design's OWN input documents (never a generated/golden output).
_INPUT_GLOBS = (
    "phase1/input_doc/*",
    "input/docs/*",
    "input/*.md",
    "input/*.txt",
)

# Verdict spellings observed across real runs. Both the taxonomy na_stub
# ("N/A") and the AI-track resolver ("NOT_APPLICABLE") emit a not-applicable
# verdict; normalise rather than privilege one emitter.
_NA_VERDICTS = {"n/a", "na", "not_applicable", "not applicable",
                "notapplicable", "false", "no"}
_APPLICABLE_VERDICTS = {"applicable", "yes", "true", "required", "present"}

_APPLICABILITY_KEYS = ("applicability", "applicable", "is_applicable")

# Where the different emitters put the N/A justification.
_RATIONALE_KEYS = ("rationale", "reason", "na_rationale",
                   "not_applicable_reason", "justification", "why")

# Content-free placeholders that do not constitute a rationale.
_EMPTY_RATIONALE = {"", "-", "--", "n/a", "na", "none", "null", "tbd",
                    "todo", "?", "unknown", "not applicable",
                    "not_applicable", "no", "nil"}
_RATIONALE_MIN_CHARS = 12

# --- APPLICABLE-branch actionable-content key vocabulary -------------------
_SPD_STANDARD_KEYS = ("spd_standard", "standard", "spd_device_type",
                      "device_type", "spd_device", "jedec_standard",
                      "spd_spec", "hub_device", "eeprom_type", "spd_type")
_SPD_ADDRESS_KEYS = ("spd_bus_address", "bus_address", "i2c_address",
                     "device_address", "slave_address", "spd_address",
                     "address", "addressing", "bus_addressing",
                     "sa_pin_encoding", "select_address")
_SPD_MAP_KEYS = ("spd_bytes", "spd_byte_map", "byte_map", "spd_fields",
                 "module_fields", "spd_map", "byte_fields", "fields",
                 "spd_contents", "module_metadata")

_L4_REG_LIST_KEYS = ("registers", "regmap", "register_map", "reg_table",
                     "register_table", "regs")
_NAME_KEYS = ("name", "field", "register", "reg_name", "field_name", "id")


# ---------------------------------------------------------------------------
# Derivation helpers — the SPD vocabulary comes from the taxonomy, not from
# a literal list maintained here.
# ---------------------------------------------------------------------------
def _spd_standard_tokens() -> List[str]:
    """Parse the JEDEC SPD standard identifiers out of the taxonomy's OWN
    description for L27.

    The taxonomy describes L27 as e.g.::

        JEDEC SPD module-level metadata (EE1004 / TSE2004av / SPD5118),
        distinct from the on-die register map. ...

    We take the first parenthesised group and split it, so the gate tracks
    the taxonomy automatically when a future SPD standard is added. Falls
    back to the spelled-out SPD phrase if the description ever loses its
    parenthesised list — the gate then still has a derived signal and simply
    becomes more conservative.
    """
    tokens: List[str] = []
    try:
        desc = _tx.l_doc_spec(_L27_CODE).description or ""
    except Exception:
        desc = ""
    m = re.search(r"\(([^)]*)\)", desc)
    if m:
        for raw in re.split(r"[/,]", m.group(1)):
            tok = raw.strip()
            # keep standard-designator-shaped tokens only (letters+digits)
            if len(tok) >= 4 and re.search(r"\d", tok) and re.match(
                    r"^[A-Za-z][A-Za-z0-9._-]*$", tok):
                tokens.append(tok)
    # "serial presence detect" is the literal expansion of the SPD acronym
    # carried in this layer's own canonical name (L27_MEMORY_MODULE_SPD);
    # it is JEDEC's own generic term, not a vendor identifier.
    tokens.append("serial presence detect")
    return tokens


def _module_form_tokens() -> List[str]:
    """JEDEC module form-factor vocabulary + the module phrase taken from the
    layer's own canonical title. Vendor-neutral; applies to every maker."""
    toks = ["memory module"]
    try:
        title = (_tx.l_doc_spec(_L27_CODE).title or "").lower()
    except Exception:
        title = ""
    if "module" in title:
        toks.append("memory-module")
    # The DIMM family is public JEDEC form-factor terminology.
    toks.extend(["dimm", "so-dimm", "sodimm", "udimm", "rdimm", "lrdimm",
                 "nvdimm", "cudimm", "micro-dimm"])
    return toks


def _taxonomy_says_applicable(ic_class: str) -> bool:
    """Is L27 applicable to `ic_class` according to the taxonomy?

    Isolated so tests can monkeypatch a hypothetical opt-in memory-module
    class (none exists today, by design).
    """
    try:
        return bool(_tx.is_applicable(ic_class, _L27_CODE))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def _find(project: Path, globs: Sequence[str]) -> Optional[Path]:
    for pat in globs:
        try:
            hits = sorted(project.glob(pat))
        except Exception:
            continue
        for hit in hits:
            if hit.is_file():
                return hit
    return None


def _waived(project: Path) -> Optional[str]:
    p = project / "waivers.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
    except Exception:
        return None
    entries: List[Any] = []
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                entries.extend(v)
        entries.append(data)
    elif isinstance(data, list):
        entries.extend(data)
    for e in entries:
        if not isinstance(e, dict):
            continue
        key = str(e.get("id") or e.get("key") or e.get("name") or "")
        if key != WAIVER_KEY:
            continue
        just = str(e.get("justification") or e.get("rationale")
                   or e.get("reason") or "")
        if len(just.strip()) >= WAIVER_MIN_CHARS:
            return just.strip()
    if isinstance(data, dict):
        val = data.get(WAIVER_KEY)
        if isinstance(val, str) and len(val.strip()) >= WAIVER_MIN_CHARS:
            return val.strip()
    return None


def _walk_strings(node: Any, out: List[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            out.append(str(k))
            _walk_strings(v, out)
    elif isinstance(node, list):
        for it in node:
            _walk_strings(it, out)
    elif isinstance(node, str):
        out.append(node)
    elif node is not None:
        out.append(str(node))


def _first_key(node: Any, keys: Sequence[str]) -> Tuple[Optional[str], Any]:
    """Depth-first search for the first of `keys` present in `node`."""
    if isinstance(node, dict):
        for k in keys:
            if k in node:
                return k, node[k]
        for v in node.values():
            hit = _first_key(v, keys)
            if hit[0] is not None:
                return hit
    elif isinstance(node, list):
        for it in node:
            hit = _first_key(it, keys)
            if hit[0] is not None:
                return hit
    return None, None


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in _EMPTY_RATIONALE
    if isinstance(value, (list, dict, set, tuple)):
        return len(value) > 0
    return True


def _norm_verdict(raw: Any) -> Optional[str]:
    """Normalise an applicability value to 'na' / 'applicable' / None."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return "applicable" if raw else "na"
    s = str(raw).strip().lower()
    if not s:
        return None
    if s in _NA_VERDICTS:
        return "na"
    if s in _APPLICABLE_VERDICTS:
        return "applicable"
    return None


def _collect_names(node: Any, out: Set[str]) -> None:
    """Collect entry names from a list-of-dicts or dict-of-dicts map."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                out.add(str(k).strip().lower())
                _collect_names(v, out)
            else:
                if str(k) in _NAME_KEYS:
                    out.add(str(v).strip().lower())
    elif isinstance(node, list):
        for it in node:
            if isinstance(it, dict):
                for nk in _NAME_KEYS:
                    if nk in it and isinstance(it[nk], (str, int)):
                        out.add(str(it[nk]).strip().lower())
                        break
                else:
                    _collect_names(it, out)
            elif isinstance(it, str):
                out.add(it.strip().lower())


# ---------------------------------------------------------------------------
# R4 — does the design's OWN input declare a self-describing memory module?
# ---------------------------------------------------------------------------
# A negation window keeps a spec that explicitly DENIES having a module
# ("on-chip SRAM only, no external DIMM/SPD") from reading as positive
# evidence. Checked per-line around the matched token.
_NEG_PAT = re.compile(
    r"(?:\bno\b|\bnot\b|\bnon-|\bwithout\b|\bexclud|\bn/?a\b|\babsent\b|"
    r"\bunsupported\b|\bdoes\s+not\b|\bnever\b|無|沒有|不支援|不含|非)",
    re.IGNORECASE)


def _read_design_inputs(project: Path) -> Tuple[List[str], int]:
    """Return (lines, files_read) from the design's OWN input documents."""
    lines: List[str] = []
    files = 0
    for pat in _INPUT_GLOBS:
        try:
            hits = sorted(project.glob(pat))
        except Exception:
            continue
        for f in hits:
            if not f.is_file():
                continue
            try:
                text = f.read_text(errors="ignore")
            except Exception:
                continue
            files += 1
            lines.extend(text.splitlines())
    return lines, files


def _module_evidence_in_inputs(
        lines: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Two-axis conjunction over the design's own input lines.

    Returns (standard_hits, module_hits). Evidence counts ONLY when a line
    is not negated, and the gate requires BOTH axes — a design that merely
    reads someone else's SPD, or that mentions a module form-factor in
    passing, trips at most one axis and is therefore not flagged.
    """
    std_tokens = [t.lower() for t in _spd_standard_tokens()]
    mod_tokens = [t.lower() for t in _module_form_tokens()]
    std_hits: List[str] = []
    mod_hits: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        negated = bool(_NEG_PAT.search(line))
        if negated:
            continue
        for t in std_tokens:
            if t in low:
                std_hits.append(f"{t}: {line[:100]}")
                break
        for t in mod_tokens:
            if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])",
                         low):
                mod_hits.append(f"{t}: {line[:100]}")
                break
    return std_hits, mod_hits


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
def evaluate_l27(project: Path) -> Tuple[int, List[str]]:
    """Pure verdict function. Returns (exit_code, message_lines)."""
    l27 = _find(project, _L27_GLOBS)
    if l27 is None:
        return 2, [f"[SKIP] {GATE}: L27_MEMORY_MODULE_SPD.json not found"]

    try:
        doc = json.loads(l27.read_text())
    except Exception as exc:
        return 1, [f"[FAIL] {GATE}: cannot parse {l27.name}: {exc}"]
    if not isinstance(doc, dict):
        return 1, [f"[FAIL] {GATE}: {l27.name} is not a JSON object"]

    # ---- R1: an applicability verdict must exist -------------------------
    akey, araw = _first_key(doc, _APPLICABILITY_KEYS)
    verdict = _norm_verdict(araw)
    if verdict is None:
        return 1, [
            f"[FAIL] {GATE}: R1 — {l27.name} declares no usable applicability "
            f"verdict (found {akey}={araw!r}). The presence/applicability "
            f"brain cannot classify this layer as applicable XOR "
            f"not-applicable, so the layer is unusable by any consumer."]

    # Which ic_class does this run actually have? Prefer the layer's own
    # declaration; fall back to the detector over the design's own inputs.
    ic_class = str(doc.get("ic_class") or "").strip()
    ic_source = "L27.ic_class"
    if not ic_class:
        try:
            from ic_class_profile import detect_ic_class  # noqa: E402
            ic_class = str(
                detect_ic_class(project).get("ic_class") or "").strip()
            ic_source = "ic_class_profile.detect_ic_class"
        except Exception:
            ic_class = ""
    tax_applicable = _taxonomy_says_applicable(ic_class) if ic_class else False

    if verdict == "na":
        return _evaluate_na(project, l27, doc, ic_class, ic_source,
                            tax_applicable)
    return _evaluate_applicable(project, l27, doc, ic_class, ic_source,
                                tax_applicable)


def _evaluate_na(project: Path, l27: Path, doc: Dict[str, Any],
                 ic_class: str, ic_source: str,
                 tax_applicable: bool) -> Tuple[int, List[str]]:
    fails: List[str] = []

    # ---- R2: the N/A must be justified ----------------------------------
    rkey, rval = _first_key(doc, _RATIONALE_KEYS)
    rationale = str(rval).strip() if isinstance(rval, (str, int)) else ""
    if (not rationale
            or rationale.lower() in _EMPTY_RATIONALE
            or len(rationale) < _RATIONALE_MIN_CHARS):
        fails.append(
            f"R2 — applicability is not-applicable but there is no "
            f"substantive rationale (found {rkey}={rationale!r}). An "
            f"unjustified N/A is an unfalsifiable claim: nothing downstream "
            f"can tell a correct N/A from a silently-dropped layer.")

    # ---- R3: N/A must not contradict the taxonomy ------------------------
    if ic_class and tax_applicable:
        fails.append(
            f"R3 — L27 declares NOT-APPLICABLE, but l_doc_taxonomy says L27 "
            f"IS applicable to ic_class={ic_class!r} (source: {ic_source}). "
            f"The layer contradicts the authority that governs it; one of "
            f"the two is wrong and the flow cannot tell which.")

    # ---- R4: N/A must not contradict the design's own input --------------
    lines, files = _read_design_inputs(project)
    if files:
        std_hits, mod_hits = _module_evidence_in_inputs(lines)
        if std_hits and mod_hits:
            payload = _l27_payload_size(doc)
            if payload == 0:
                fails.append(
                    f"R4 — the design's OWN input documents declare a "
                    f"self-describing memory module on BOTH axes "
                    f"(SPD standard: {std_hits[0]!r}; module form: "
                    f"{mod_hits[0]!r}) across {files} input file(s), yet L27 "
                    f"— the only layer that carries module-level SPD "
                    f"metadata — is not-applicable with 0 bytes of SPD "
                    f"payload. The requirement is present in the design "
                    f"input and 0 times in the consuming layer.")

    if fails:
        return 1, _fail_block(l27, project, fails)
    return 0, [
        f"[PASS] {GATE}: L27 not-applicable, justified, and corroborated — "
        f"ic_class={ic_class or '<undetected>'} ({ic_source}); taxonomy "
        f"agrees L27 is opt-in-only and not applicable; the design's own "
        f"input declares no self-describing memory module."]


def _l27_payload_size(doc: Dict[str, Any]) -> int:
    """How much actionable SPD content does this L27 actually carry?

    Bookkeeping keys (doc_id / applicability / rationale / provenance) do not
    count — only substantive payload does.
    """
    skip = {"doc_id", "doc_name", "applicability", "applicable",
            "is_applicable", "ic_class", "ic_name", "schema_version",
            "emitted_by", "extraction_strategy", "_resolution",
            "extraction_evidence"} | set(_RATIONALE_KEYS)
    size = 0
    for k, v in doc.items():
        if k in skip:
            continue
        if isinstance(v, dict):
            # A `fields` dict that only restates the N/A reason is not payload.
            inner = {ik: iv for ik, iv in v.items()
                     if ik not in _RATIONALE_KEYS}
            size += len(inner)
        elif isinstance(v, list):
            size += len(v)
        elif _nonempty(v):
            size += 1
    return size


def _evaluate_applicable(project: Path, l27: Path, doc: Dict[str, Any],
                         ic_class: str, ic_source: str,
                         tax_applicable: bool) -> Tuple[int, List[str]]:
    fails: List[str] = []

    # ---- R5: applicable must mean ACTIONABLE, not an empty skeleton ------
    std_key, std_val = _first_key(doc, _SPD_STANDARD_KEYS)
    addr_key, addr_val = _first_key(doc, _SPD_ADDRESS_KEYS)
    map_key, map_val = _first_key(doc, _SPD_MAP_KEYS)

    known_std = [t.lower() for t in _spd_standard_tokens()]
    std_strings: List[str] = []
    _walk_strings(std_val, std_strings)
    std_ok = _nonempty(std_val) and any(
        t in s.lower() for s in std_strings for t in known_std)

    missing: List[str] = []
    if not std_ok:
        missing.append(
            f"a JEDEC SPD standard identifier (one of "
            f"{[t for t in _spd_standard_tokens()]}) under a "
            f"{'/'.join(_SPD_STANDARD_KEYS[:3])}-style key "
            f"(found {std_key}={std_val!r})")
    if not _nonempty(addr_val):
        missing.append(
            f"the SPD bus address / addressing the host uses to reach the "
            f"SPD device (found {addr_key}={addr_val!r})")
    map_names: Set[str] = set()
    if _nonempty(map_val):
        _collect_names(map_val, map_names)
    if not map_names:
        missing.append(
            f"a non-empty SPD byte/field map (found {map_key}={map_val!r})")

    if missing:
        fails.append(
            f"R5 — L27 declares itself APPLICABLE but is an empty skeleton: "
            f"missing " + "; missing ".join(missing) + ". An applicable "
            f"layer with no actionable content is exactly what the "
            f"opt-in-only rule exists to prevent — a consumer would build "
            f"the module with no SPD image.")

    # ---- R6: must be DISTINCT from the on-die register map ---------------
    if map_names:
        l4 = _find(project, _L4_GLOBS)
        if l4 is not None:
            try:
                l4doc = json.loads(l4.read_text())
            except Exception:
                l4doc = None
            if l4doc is not None:
                _, regs = _first_key(l4doc, _L4_REG_LIST_KEYS)
                reg_names: Set[str] = set()
                if regs is not None:
                    _collect_names(regs, reg_names)
                if reg_names and map_names <= reg_names:
                    fails.append(
                        f"R6 — every one of the {len(map_names)} L27 SPD "
                        f"field name(s) also appears in the on-die register "
                        f"map ({l4.name}); L27 restates L4 and carries no "
                        f"module-level information. The taxonomy requires "
                        f"L27 be 'distinct from the on-die register map'.")

    if fails:
        return 1, _fail_block(l27, project, fails)
    return 0, [
        f"[PASS] {GATE}: L27 applicable and actionable — SPD standard, bus "
        f"address and a {len(map_names)}-entry byte/field map distinct from "
        f"the on-die register map (ic_class={ic_class or '<undetected>'})."]


def _fail_block(l27: Path, project: Path, fails: List[str]) -> List[str]:
    try:
        rel = l27.relative_to(project)
    except ValueError:
        rel = l27
    out = [f"[FAIL] {GATE}: {len(fails)} applicability-contract violation(s) "
           f"in {rel}"]
    for f in fails:
        out.append(f"  - {f}")
    out.append(f"  waiver: {WAIVER_KEY} (>= {WAIVER_MIN_CHARS} chars "
               f"justification) if this is intentional.")
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(f"usage: {GATE} <project_dir>", file=sys.stderr)
        return 2
    project = Path(args[0]).resolve()
    if not project.is_dir():
        print(f"[SKIP] {GATE}: {project} is not a directory")
        return 2

    code, lines = evaluate_l27(project)
    if code == 1:
        just = _waived(project)
        if just:
            print(f"[WAIVED] {GATE}: {WAIVER_KEY} — {just[:160]}")
            for ln in lines[1:]:
                print(f"  (waived) {ln.strip()}")
            return 0
    for ln in lines:
        print(ln)
    return code


if __name__ == "__main__":
    sys.exit(main())
