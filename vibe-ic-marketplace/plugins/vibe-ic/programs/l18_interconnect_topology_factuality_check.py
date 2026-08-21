#!/usr/bin/env python3
"""l18_interconnect_topology_factuality_check.py — SEMANTIC gate for L18.

VERDICT MODE: **ADVISES** by default (exit 0, findings reported).
`--strict` promotes ERROR findings to a blocking exit 1.

WHY IT ADVISES AND DOES NOT BLOCK (stated explicitly, per the gate contract)
---------------------------------------------------------------------------
L18_INTERCONNECT_TOPOLOGY has NO downstream consumer. Only the Phase-1 one-shot
runner self-reads it and its own producer writes it. Blocking a flow on a
document that nothing consumes would be pure friction with no defect prevented
— the opposite of the L21 lesson, which is about the layer the BACKEND actually
reads. So the honest verdict mode is ADVISE.

That does NOT make the gate optional. Because no consumer ever touches L18,
nothing catches its non-facts: a real run shipped
`default_signal_values = {"always": "6'b0. |", "which": "40 bit wide counters"}`
— English function words harvested by a case-insensitive regex — while
`extraction_status` said EXTRACTED. Unchallenged non-facts are exactly what
feeds a false CAPTURED into completeness accounting. `--strict` exists so the
day L18 gains a consumer, the gate is promoted by flipping one flag rather than
by writing a new program.

THE PRINCIPLE THIS GATE ENCODES
-------------------------------
  A layer is complete when the requirement is present IN THE LAYER THAT
  CONSUMES IT, in an actionable form — not when a token appears somewhere.

With no consumer, the strongest available restatement is: every claim L18 makes
must be a FACT ABOUT THIS DESIGN, corroborated by the design's own declared
entities. A claim naming nothing this design has is a non-fact regardless of
how populated the field looks.

WHAT IT CATCHES
---------------
E1 DEFAULT_VALUE_KEY_IS_NOT_A_DESIGN_ENTITY
    `default_signal_values` is a signal->default map. Every KEY must resolve
    against this design's own declared entity universe (built by walking the
    run's other L-docs). A key that resolves to nothing is not a signal — it is
    regex spill. Fires only when the layer claims extraction success, and the
    finding reports the exact resolve/total split.
E2 DEFAULT_VALUE_IS_A_HARVEST_ARTIFACT
    A default VALUE carrying table-formatting debris (a pipe, a run of >=5
    spaces, a trailing markdown cell separator) was scraped out of a rendered
    table, not parsed. General: no protocol or design literal involved.
E3 STATUS_CONTRADICTS_PAYLOAD
    extraction_status claims success while every payload field is empty (or
    every fact-bearing field failed E1/E2). The status field lies.
W4 STATUS_PARTIALLY_EARNED
    The weaker, correctly-scoped sibling of E3: the status claims success, some
    fact-bearing field failed E1/E2, but others did NOT. The failures are real
    (E1/E2 still fire on their own), yet "the success status is not earned" is
    false — so this reports the exact failed/surviving split instead.
W1 NARRATIVE_UNCORROBORATED
    A narrative sub-document (`id_routing`, `multi_copy_atomicity`,
    `typical_topologies`, `axprot_polarity`) names identifier-shaped entities
    of which NONE resolve in this design. Warning, never error: identifying
    entities inside prose is inherently approximate, so it must not carry a
    verdict.
W2 CANONICAL_FILENAME_CONTRACT_SPLIT
    The schema's own L18 filename mapping (parsed out of
    tools/phase1_engine/schema.py, not hardcoded) names a file absent from this
    run while a differently-named L18 doc IS present. Any tool that resolves
    L18 through the schema map reads nothing.
W3 NO_EXTRACTION_EVIDENCE.
I  HONEST_EMPTY — nothing extracted and the status says so. PASSES.

HOW THE PAYLOAD IS IDENTIFIED, AND WHY IT IS BY SUBTRACTION
-----------------------------------------------------------
E3 and W4 both hinge on the question "which fields did this document actually
populate?", so getting that set wrong makes the verdict overreach even when
each individual sub-finding is sound.

This gate originally answered it with an ALLOW-LIST of payload container names.
That list matched exactly the fixed key schema of ONE producer — the generic
extractor — while the per-protocol synthesizers write a far richer and
open-ended set. Measured over the tracked corpus, documents carry 92 distinct
payload container names; the allow-list enumerated 7. So the gate assessed
"every fact-bearing field failed" through a window that could not see most of
the payload, and asserted a scope it had never examined.

An allow-list cannot be repaired by lengthening it: the payload vocabulary is
OPEN — a synthesizer names a container after whatever the source document calls
that concept, and a new one appears with every new source. What IS closed, small
and stable is the schema/provenance ENVELOPE (document identity, producer
identity, extraction status, evidence). So the payload is identified by
SUBTRACTING the closed envelope from the producer's own payload container,
never by enumerating the open payload. A container the gate has never heard of
now counts as payload by default, which is the fail-safe direction: an
unrecognised container makes the gate claim LESS, not more.

GENERALITY / NO-CHEATING STATEMENT
----------------------------------
No design name, PDK name, vendor part number, protocol name, or pin/signal
literal appears in this file. The entity universe comes from the run's OWN
L-docs (with L18 itself excluded so it can never self-corroborate); the
canonical filename comes from the schema module's OWN table.

SINGLE TRACK, HONESTLY DECLARED
-------------------------------
ONE deterministic track. No AI second track is claimed.

USAGE
    python3 l18_interconnect_topology_factuality_check.py <project>
            [--json OUT] [--strict] [--schema-file PATH]

EXIT CODES
    0 = advisory pass (default mode always returns 0 when the doc is readable)
    1 = ERROR finding AND --strict
    2 = not applicable / unreadable
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_STATUS_FOUND_NOTHING = {
    "EXTRACTION_FOUND_NOTHING", "FOUND_NOTHING", "NOT_FOUND", "NOTHING_FOUND",
    "EMPTY", "NONE", "NOT_APPLICABLE", "N/A", "NA", "SKIPPED", "ABSENT",
    "NO_CONTENT", "NOT_PRESENT",
}
_STATUS_SUCCESS = {
    "EXTRACTED", "CAPTURED", "OK", "COMPLETE", "PRESENT", "SUCCESS", "DONE",
}

_NARRATIVE_KEYS = ("id_routing", "multi_copy_atomicity", "typical_topologies",
                   "axprot_polarity", "topology_notes")

# The CLOSED half of the document. Everything here is schema bookkeeping —
# which layer this is, which producer wrote it, whether extraction succeeded,
# what it was traced to. None of it is ever a claim ABOUT the design, so none
# of it can make a success status earned. Keys beginning with an underscore are
# private producer bookkeeping by convention and are excluded by SHAPE, not by
# name, so new ones need no maintenance here.
#
# This set is the gate's only enumeration of container names, and it is
# deliberately the one that is enumerable: it is fixed by the emitter, whereas
# the payload names are chosen per source document.
_ENVELOPE_KEYS = {
    "fields", "doc_class", "doc_id", "doc_name", "ic_name", "ic_class",
    "schema_version", "emitted_by", "generated_at", "replaces",
    "extraction_status", "status", "extraction_evidence", "evidence",
    "extraction_source",
}

_ENTITY_NAME_KEYS = {
    "name", "signal", "signal_name", "pin", "pin_name", "port", "port_name",
    "net", "net_name", "wire", "wire_name", "mnemonic", "register",
    "reg_name", "field_name", "identifier", "source_pin", "top_module",
    "instance", "instance_name", "module",
}
_ENTITY_LIST_KEYS = {
    "ports", "pins", "signals", "top_ports", "top_level_ports", "dtop_ports",
    "top_module_pins", "internal_wires", "nets", "clocks", "resets",
    "clock_domains", "reset_domains", "parameters", "opcodes",
}
_TOKEN_SHAPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]{1,63}$")
_IDENT_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

# A default VALUE scraped straight out of a rendered table keeps the table's
# formatting debris. General shape test — no protocol/design literal.
_HARVEST_ARTIFACT = re.compile(r"\|| {5,}|\t")

_SCHEMA_L18_MAP = re.compile(r"[\"']L18[\"']\s*:\s*[\"']([A-Za-z0-9_]+\.json)[\"']")


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    evidence: Dict[str, Any] = field(default_factory=dict)


def _read_json(p: Path) -> Optional[dict]:
    try:
        d = json.loads(p.read_text(errors="ignore"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _unwrap(d: Optional[dict]) -> dict:
    if not isinstance(d, dict):
        return {}
    if isinstance(d.get("fields"), dict):
        merged = dict(d)
        merged.update(d["fields"])
        return merged
    return d


def _as_dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _is_envelope(key: Any) -> bool:
    """True for schema/provenance bookkeeping, false for anything claim-like."""
    k = str(key)
    return k in _ENVELOPE_KEYS or k.startswith("_")


def _is_populated(v: Any) -> bool:
    if isinstance(v, (list, dict)):
        return bool(v)
    if isinstance(v, str):
        return bool(v.strip())
    return False


def populated_payload_fields(unwrapped: dict) -> List[str]:
    """Every container this document populated, by subtracting the envelope.

    `unwrapped` is the producer's payload container merged over the top level,
    so this works on both the nested and the flat document shape without
    knowing which one it was handed. Sorted, so the report is stable across
    key-insertion order.
    """
    return sorted(k for k, v in unwrapped.items()
                  if not _is_envelope(k) and _is_populated(v))


def fact_bearing_fields(populated: List[str]) -> List[str]:
    """The subset a success status can actually be earned by.

    Narrative sub-documents are excluded on the same ground W1 states: they are
    prose, identifying entities inside prose is approximate, and approximate
    evidence must not carry a verdict — in EITHER direction. A narrative may not
    convict the layer, so it may not acquit it either.
    """
    return [k for k in populated if k not in _NARRATIVE_KEYS]


def _norm(tok: str) -> str:
    tok = re.sub(r"\[[^\]]*\]", "", str(tok or "")).strip()
    return tok.strip("`'\"*_ \t").lower()


def _collect_entity_names(node: Any, out: Set[str], depth: int = 0) -> None:
    if depth > 12:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            lk = str(k).lower()
            if isinstance(v, str):
                if lk in _ENTITY_NAME_KEYS and _TOKEN_SHAPE.match(v.strip()):
                    n = _norm(v)
                    if len(n) >= 2:
                        out.add(n)
            elif isinstance(v, list) and lk in _ENTITY_LIST_KEYS:
                for it in v:
                    if isinstance(it, str) and _TOKEN_SHAPE.match(it.strip()):
                        n = _norm(it)
                        if len(n) >= 2:
                            out.add(n)
            _collect_entity_names(v, out, depth + 1)
    elif isinstance(node, list):
        for it in node:
            _collect_entity_names(it, out, depth + 1)


def build_entity_universe(gd: Path, exclude: Set[str]) -> Set[str]:
    universe: Set[str] = set()
    for p in sorted(gd.glob("L*.json")):
        if p.name in exclude:
            continue
        d = _read_json(p)
        if d is not None:
            _collect_entity_names(d, universe)
    return universe


def _identifier_tokens(node: Any, out: Optional[Set[str]] = None) -> Set[str]:
    if out is None:
        out = set()
    if isinstance(node, str):
        for m in _IDENT_TOKEN.finditer(node):
            t = m.group(0)
            if re.search(r"[A-Z]{2}", t) or "_" in t:
                out.add(t)
    elif isinstance(node, dict):
        for k, v in node.items():
            _identifier_tokens(str(k), out)
            _identifier_tokens(v, out)
    elif isinstance(node, list):
        for it in node:
            _identifier_tokens(it, out)
    return out


def canonical_l18_filename(schema_file: Optional[Path]) -> Optional[str]:
    """Read the schema module's OWN L18 filename mapping."""
    if schema_file is None:
        schema_file = (Path(__file__).resolve().parent.parent
                       / "tools" / "phase1_engine" / "schema.py")
    if not schema_file.is_file():
        return None
    try:
        txt = schema_file.read_text(errors="ignore")
    except OSError:
        return None
    m = _SCHEMA_L18_MAP.search(txt)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
def audit(project: Path,
          schema_file: Optional[Path]) -> Tuple[List[Finding], Dict[str, Any]]:
    findings: List[Finding] = []
    info: Dict[str, Any] = {}

    gd = project / "phase1" / "generated_docs"
    if not gd.is_dir():
        findings.append(Finding("SKIP", "NO_GENERATED_DOCS",
                                f"{gd} does not exist"))
        return findings, info

    on_disk = sorted(p.name for p in gd.glob("L18_*.json"))
    if not on_disk:
        findings.append(Finding("SKIP", "NO_L18_DOC",
                                "no L18_*.json in generated_docs"))
        return findings, info

    doc_name = on_disk[0]
    raw = _read_json(gd / doc_name)
    if raw is None:
        findings.append(Finding("SKIP", "INVALID_JSON",
                                f"{doc_name} is not readable JSON"))
        return findings, info

    l18 = _unwrap(raw)
    status = str(raw.get("extraction_status") or raw.get("status")
                 or l18.get("extraction_status") or "").strip().upper()
    info.update({"l18_files_on_disk": on_disk, "l18_audited": doc_name,
                 "extraction_status": status or None})

    # -- W2 canonical filename split ----------------------------------------
    canon = canonical_l18_filename(schema_file)
    info["schema_canonical_l18"] = canon
    if canon and canon not in on_disk:
        findings.append(Finding(
            "WARNING", "CANONICAL_FILENAME_CONTRACT_SPLIT",
            f"the schema table maps L18 -> {canon!r}, which does not exist in "
            f"this run; the doc on disk is {on_disk}. Any tool resolving L18 "
            f"through the schema map reads nothing and raises no error.",
            {"schema_says": canon, "on_disk": on_disk}))

    universe = build_entity_universe(gd, exclude=set(on_disk))
    info["entity_universe_size"] = len(universe)

    dsv = _as_dict(l18.get("default_signal_values"))
    payload_nonempty = populated_payload_fields(l18)
    info["payload_fields_populated"] = payload_nonempty

    # Which populated field each ERROR below implicates. E3/W4 compare this
    # against the fact-bearing set; a finding that implicates no field leaves
    # the set alone, which keeps the scope claim conservative by construction.
    failed_fields: Set[str] = set()

    # -- E1 default_signal_values keys must be design entities ---------------
    unresolved: List[str] = []
    resolved: List[str] = []
    for k in dsv:
        (resolved if _norm(k) in universe else unresolved).append(str(k))
    info["default_signal_values_total"] = len(dsv)
    info["default_signal_values_resolved"] = len(resolved)
    if dsv and not resolved:
        failed_fields.add("default_signal_values")
        findings.append(Finding(
            "ERROR", "DEFAULT_VALUE_KEY_IS_NOT_A_DESIGN_ENTITY",
            f"all {len(dsv)} default_signal_values key(s) resolve to NOTHING "
            f"in this design's own declared entity universe "
            f"({len(universe)} entities from its other L-docs). A "
            f"signal->default map whose keys are not signals is regex spill, "
            f"not extraction — and with no consumer, nothing else would ever "
            f"catch it.",
            {"unresolved_keys": unresolved[:20],
             "sample": {k: dsv[k] for k in unresolved[:4]}}))
    elif unresolved:
        findings.append(Finding(
            "WARNING", "DEFAULT_VALUE_KEY_IS_NOT_A_DESIGN_ENTITY",
            f"{len(unresolved)}/{len(dsv)} default_signal_values key(s) do not "
            f"resolve to any entity this design declares.",
            {"unresolved_keys": unresolved[:20]}))

    # -- E2 harvest artifacts in the values ---------------------------------
    artifacts = {k: v for k, v in dsv.items()
                 if isinstance(v, str) and _HARVEST_ARTIFACT.search(v)}
    if artifacts:
        failed_fields.add("default_signal_values")
        findings.append(Finding(
            "ERROR", "DEFAULT_VALUE_IS_A_HARVEST_ARTIFACT",
            f"{len(artifacts)} default value(s) still carry rendered-table "
            f"debris (a cell separator, a tab, or a >=5-space run). These were "
            f"scraped out of a rendered table rather than parsed, so the "
            f"'fact' is a formatting accident.",
            {"values": {k: v[:80] for k, v in list(artifacts.items())[:6]}}))

    # -- E4 template content the producer says it never extracted ------------
    if status in _STATUS_FOUND_NOTHING and payload_nonempty:
        findings.append(Finding(
            "ERROR", "TEMPLATE_WITHOUT_EXTRACTION",
            f"{doc_name} reports extraction_status={status!r} — the producer "
            f"says it extracted nothing from this design's source — yet "
            f"{payload_nonempty} are populated. Content the producer did not "
            f"extract cannot describe this design; it is template content "
            f"from an unrelated protocol, and every presence/non-empty "
            f"heuristic reads this layer as POPULATED.",
            {"populated": payload_nonempty,
             "sample": {k: l18.get(k) for k in payload_nonempty[:2]}}))

    # -- W1 narrative corroboration ------------------------------------------
    for key in _NARRATIVE_KEYS:
        v = l18.get(key)
        if not v or (isinstance(v, (list, dict)) and not v):
            continue
        toks = _identifier_tokens(v)
        if not toks:
            continue
        hits = sorted(t for t in toks if _norm(t) in universe)
        if not hits:
            findings.append(Finding(
                "WARNING", "NARRATIVE_UNCORROBORATED",
                f"{key} names {len(toks)} identifier-shaped entit(ies), NONE "
                f"of which this design declares anywhere. The sub-document "
                f"describes some other design.",
                {"field": key, "tokens": sorted(toks)[:20],
                 "value_sample": json.dumps(v, default=str)[:240]}))

    # -- E3 status vs payload ------------------------------------------------
    # The claim "EVERY fact-bearing field failed" is universal, so it is tested
    # universally: the fact-bearing set must be fully covered by the set of
    # fields the findings above actually implicate. The earlier form fired on
    # the mere EXISTENCE of one error, which asserted a scope it had not
    # measured — an overreaching verdict on top of genuine sub-findings.
    hard_errors = [f for f in findings if f.severity == "ERROR"]
    fact_bearing = fact_bearing_fields(payload_nonempty)
    surviving = [k for k in fact_bearing if k not in failed_fields]
    info["payload_fields_fact_bearing"] = fact_bearing
    info["payload_fields_failed"] = sorted(failed_fields & set(fact_bearing))
    info["payload_fields_surviving"] = surviving
    if status in _STATUS_SUCCESS and not payload_nonempty:
        findings.append(Finding(
            "ERROR", "STATUS_CONTRADICTS_PAYLOAD",
            f"{doc_name} reports extraction_status={status!r} with every "
            f"payload field empty. Completeness accounting that trusts the "
            f"status will record this layer as CAPTURED while it holds "
            f"nothing.", {"status": status}))
    elif (status in _STATUS_SUCCESS and payload_nonempty and hard_errors
          and fact_bearing and not surviving):
        findings.append(Finding(
            "ERROR", "STATUS_CONTRADICTS_PAYLOAD",
            f"{doc_name} reports extraction_status={status!r}, but every "
            f"fact-bearing field it populated ({fact_bearing}) failed the "
            f"factuality tests above. The success status is not earned.",
            {"status": status, "populated": payload_nonempty,
             "fact_bearing": fact_bearing,
             "failed_categories": sorted({f.category for f in hard_errors})}))
    elif (status in _STATUS_SUCCESS and hard_errors and surviving
          and failed_fields & set(fact_bearing)):
        findings.append(Finding(
            "WARNING", "STATUS_PARTIALLY_EARNED",
            f"{doc_name} reports extraction_status={status!r} and "
            f"{sorted(failed_fields & set(fact_bearing))} failed the "
            f"factuality tests above — but {len(surviving)} other fact-bearing "
            f"field(s) did not, so the status is partly earned and the "
            f"failures are scoped to the field(s) named. Reported rather than "
            f"blocked: the failures already carry their own ERROR, and "
            f"restating them as a verdict over the whole layer would condemn "
            f"content that was never tested.",
            {"status": status,
             "failed": sorted(failed_fields & set(fact_bearing)),
             "surviving": surviving}))
    elif status in _STATUS_FOUND_NOTHING and not payload_nonempty:
        findings.append(Finding(
            "INFO", "HONEST_EMPTY",
            f"{doc_name} holds nothing and says so "
            f"(extraction_status={status!r}). Truthful — PASS."))

    ev = raw.get("extraction_evidence") or raw.get("evidence")
    if status in _STATUS_SUCCESS and not ev:
        findings.append(Finding(
            "WARNING", "NO_EXTRACTION_EVIDENCE",
            f"extraction_status={status!r} but extraction_evidence is empty, "
            f"so no claim in this layer is traceable to a source line."))

    return findings, info


def build_report(project: Path, findings: List[Finding],
                 info: Dict[str, Any], strict: bool) -> dict:
    errs = [f for f in findings if f.severity == "ERROR"]
    return {
        "program": "l18_interconnect_topology_factuality_check",
        "version": "1.0.0",
        "layer": "L18",
        "verdict_mode": "BLOCKS" if strict else "ADVISES",
        "project": str(project),
        "summary": {
            "pass": not errs,
            "error_count": len(errs),
            "warning_count": sum(1 for f in findings
                                 if f.severity == "WARNING"),
            "finding_count": len(findings),
            "blocking": bool(strict and errs),
        },
        "info": info,
        "findings": [asdict(f) for f in findings],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="L18 interconnect-topology factuality gate (advisory)")
    ap.add_argument("project", type=Path,
                    help="run root containing phase1/generated_docs")
    ap.add_argument("--json", default=None, help="write JSON report here")
    ap.add_argument("--strict", action="store_true",
                    help="promote ERROR findings to a blocking exit 1")
    ap.add_argument("--schema-file", type=Path, default=None,
                    help="phase1_engine/schema.py holding the L18 filename map")
    args = ap.parse_args(argv)

    findings, info = audit(args.project, args.schema_file)
    report = build_report(args.project, findings, info, args.strict)
    out = json.dumps(report, indent=2, ensure_ascii=False, default=str)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)

    if any(f.severity == "SKIP" for f in findings):
        return 2
    if args.strict and any(f.severity == "ERROR" for f in findings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
