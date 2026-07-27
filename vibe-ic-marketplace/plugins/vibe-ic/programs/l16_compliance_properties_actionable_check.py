#!/usr/bin/env python3
"""l16_compliance_properties_actionable_check.py — SEMANTIC gate for L16.

VERDICT MODE: **ADVISES**. The process exit code is unchanged — exit 1 on an
ERROR finding, `--advisory` downgrades it — but the mode this program DECLARES
about itself, which `flow_gate_enforcement_audit.py` reads and which decides
where the flow may wire it, is ADVISES.

ENFORCEMENT — WHY THE DECLARATION CHANGED (vibe-ic#316)
--------------------------------------------------------
It said BLOCKS, and nothing wired it anywhere: `flow_gate_enforcement_audit`
recorded it as an ORPHAN — declaring an intent it could not act on, because it
never ran. It was held out of the flow's advisory slot PRECISELY because it
said BLOCKS, so the over-claim was what kept it from executing at all.

That mattered more here than for its siblings, because this gate had never
returned a finding on a real input. Measured over the twelve cells published
under `benchmark-data/ic/`: rc=0 on eleven, SKIP on the twelfth. Its "zero
false positives" was VACUOUS — the same empty-result-read-as-a-clean-one shape
the gates below exist to reject, one level up. Promoting an unmeasured gate to
blocking would have been promoting a claim, not a capability.

Wired into the flow's advisory slot it now judges every real project. If it
starts finding things, the evidence to argue a promotion will exist; if it
never does over a real corpus, that is worth knowing too.

WHY THIS LAYER IS LOAD-BEARING
------------------------------
L16's readers are the SVA property-stub generator
(`professional_tb_gen.build_assertions`) and the compliance-vector catalog
(`phase2_scaffold_gen.emit_compliance_vectors`). They are not the same kind of
thing and #509 measured the difference: `professional_tb_gen` RUNS — the flow
wires it at `phase1_phase2_phase3.yaml` step `professional_tb_gen`, driven by
`design_one_shot_runner.step_professional_tb_gen` — while `phase2_scaffold_gen`
is a CONTRACT ORACLE no runner and no flow step calls, at any version. So the
first turns an L16 property into a verification obligation, and the second
states the obligation a conforming phase 2 would owe. Rail 1 below is
unaffected either way: a program that opens only a filename which exists in
zero runs cannot reach this layer whether it runs today or is the
specification something else must satisfy tomorrow.

A property that carries no machine-usable anchor
becomes a 120-char comment: the layer looks populated, the completeness report
says CAPTURED, and the verification obligation reaches NOBODY. That is the same
false-CAPTURED shape as the L21_POWER_INTENT defect that aborted a whole
detailed route — so the gate must be able to stop the flow rather than record a
FAIL that the flow ignores.

THE PRINCIPLE THIS GATE ENCODES
-------------------------------
  A layer is complete when the requirement is present IN THE LAYER THAT
  CONSUMES IT, in an actionable form — not when a token appears somewhere.

Two independent rails implement that:

RAIL 1 — CAN THE LAYER PHYSICALLY REACH ITS CONSUMER?  (DEAD_READ)
    The gate does not hardcode a filename. It PARSES the consumer programs'
    own source for every `L16*.json` string literal they open, groups those
    literals PER CONSUMER, and requires each consumer to have at least one
    literal that resolves to a file present in this run's generated_docs (a
    documented fallback chain is legitimate; a consumer whose every literal
    misses cannot reach the layer at all). A consumer reading only a filename
    that exists in zero runs is a SILENT DEAD READ: the layer can be perfect
    and still contribute nothing, with no error raised and no report entry.
    This rail keeps working if anyone renames the doc again.

RAIL 2 — IS THE CONTENT ACTIONABLE FOR THAT CONSUMER?  (ACTIONABILITY)
    A property is actionable when it carries at least one of:
      (a) an explicit signal anchor (`signals` / `referenced_signals` /
          `anchor_signals` / `ports`) that RESOLVES against this design's own
          declared entity universe;
      (b) a spec reference (`spec_ref` / `citation` / `ref` / `source_ref` /
          `reference`) that either points at an L-doc (`L3`, `L17`, ...),
          resolves to a declared entity, or names a normative clause
          (`A3.2.1`-shaped);
      (c) an identifier token inside its english_form/text that RESOLVES
          against this design's own declared entity universe.
    `anchor_token` NEVER counts: the extractor sets it to the modal verb
    ("must" / "shall" / "is_required"), which binds to nothing.

WHAT IT CATCHES
---------------
E1 CONSUMER_DEAD_READ  — a consumer's every L16 filename literal is absent from
   this run while a different L16 doc IS present. It cannot reach the layer.
E2 STATUS_CONTRADICTS_PAYLOAD — extraction_status claims success, zero
   properties emitted. A status field that lies is worse than a missing layer.
E3 NO_ACTIONABLE_PROPERTY_IN_CONSUMER_WINDOW — properties exist, but none
   inside the window the consumer actually reads carries a resolvable anchor.
   The SVA generator provably receives zero bindable obligations.
E4 PAYLOAD_WITHOUT_EXTRACTION — the MIRROR of E2, and the arm this file's
   own `_STATUS_FOUND_NOTHING` vocabulary was declared for and never wired to.
   The producer's own `extraction_status` says extraction contributed NOTHING,
   yet the layer ships properties. Both halves were written by the same
   emitter in the same emission, so the layer contradicts itself and no
   consumer can tell which of the properties extraction actually supports.
   E2 catches "status claims success, payload empty"; without E4 the opposite
   direction was unchecked, and a status field that lies is worse than a
   missing layer in EITHER direction.

   WHAT E4 DELIBERATELY DOES NOT ASSERT: where the content came from. The
   sibling rails L17-E1 / L18-E4 word the same shape as "template content from
   an unrelated protocol"; that provenance claim was MEASURED FALSE on the
   published parity corpus, where such payloads are authored per cell for that
   cell's own subject. E4 asserts only the self-contradiction, which is read
   directly off the two fields. Widening it to a provenance claim would
   reintroduce the over-reaching verdict that was removed one layer over.
W1 LOW_ACTIONABLE_RATIO (<50%)              — advisory.
W2 NO_EXTRACTION_EVIDENCE                   — advisory.
W3 CONSUMER_STALE_FILENAME_FALLBACK         — advisory: a literal that misses,
   in a consumer that has another literal which resolves.
I  HONEST_EMPTY — zero properties AND a status that says so. That is a
   truthful layer and PASSES: this gate never punishes honesty.

GENERALITY / NO-CHEATING STATEMENT
----------------------------------
No design name, PDK name, vendor part number, protocol name, or pin/signal
literal appears in this file. The entity universe is built by walking the run's
OWN L-doc JSON; the consumer filenames are parsed out of the consumer programs'
OWN source. The only constant tied to a consumer is `--consumer-window`
(default 8), which mirrors `professional_tb_gen`'s `properties[:8]` slice — a
consumer-contract constant, not a design literal.

SINGLE TRACK, HONESTLY DECLARED
-------------------------------
ONE deterministic track. No AI second track is claimed, so there is no
dual-track that can silently degenerate into one track contributing zero
(the `ai_captured_tokens_count: 0` failure).

USAGE
    python3 l16_compliance_properties_actionable_check.py <project>
            [--json OUT] [--advisory] [--consumer-window N]
            [--programs-dir DIR] [--min-actionable-ratio R]

EXIT CODES
    0 = pass (or --advisory)
    1 = at least one ERROR finding — BLOCKING
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

# ---------------------------------------------------------------------------
# Producer status vocabulary (producer tokens, not design literals)
# ---------------------------------------------------------------------------
_STATUS_FOUND_NOTHING = {
    "EXTRACTION_FOUND_NOTHING", "FOUND_NOTHING", "NOT_FOUND", "NOTHING_FOUND",
    "EMPTY", "NONE", "NOT_APPLICABLE", "N/A", "NA", "SKIPPED", "ABSENT",
    "NO_CONTENT", "NOT_PRESENT",
}
_STATUS_SUCCESS = {
    "EXTRACTED", "CAPTURED", "OK", "COMPLETE", "PRESENT", "SUCCESS", "DONE",
}

# Keys that may hold an explicit machine anchor.
_ANCHOR_SIGNAL_KEYS = ("signals", "referenced_signals", "anchor_signals",
                       "ports", "signal_names", "nets", "entities")
# Keys that may hold a spec reference.
_SPEC_REF_KEYS = ("spec_ref", "citation", "ref", "source_ref", "reference",
                  "clause", "section_ref")
# Explicitly NOT an anchor — it is the modal verb the extractor matched on.
_NON_ANCHOR_KEYS = ("anchor_token",)

_LDOC_REF = re.compile(r"\bL\d{1,2}\b")
_CLAUSE_REF = re.compile(r"\b[A-Za-z]{1,3}\d+(?:\.\d+)+\b")
_PROP_TEXT_KEYS = ("english_form", "text", "description", "statement",
                   "requirement", "property", "english", "rule")

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
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Consumer programs whose L16 read path is contractually load-bearing.
_CONSUMER_PROGRAMS = ("professional_tb_gen.py", "phase2_scaffold_gen.py")
_L16_FILENAME_LITERAL = re.compile(r"[\"'](L16[A-Za-z0-9_]*\.json)[\"']")


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    evidence: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
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
                    if len(n) >= 3:
                        out.add(n)
            elif isinstance(v, list) and lk in _ENTITY_LIST_KEYS:
                for it in v:
                    if isinstance(it, str) and _TOKEN_SHAPE.match(it.strip()):
                        n = _norm(it)
                        if len(n) >= 3:
                            out.add(n)
            _collect_entity_names(v, out, depth + 1)
    elif isinstance(node, list):
        for it in node:
            _collect_entity_names(it, out, depth + 1)


def build_entity_universe(gd: Path, exclude: Set[str]) -> Set[str]:
    """Every entity name this design declares in its OWN L-docs.

    The doc under test is always excluded so a layer can never corroborate its
    own claims with its own claims."""
    universe: Set[str] = set()
    for p in sorted(gd.glob("L*.json")):
        if p.name in exclude:
            continue
        d = _read_json(p)
        if d is not None:
            _collect_entity_names(d, universe)
    return universe


# ---------------------------------------------------------------------------
# Property collection + actionability
# ---------------------------------------------------------------------------
def collect_properties(doc: dict) -> List[Tuple[str, Any]]:
    """Every property-shaped list in the doc, as (container_key, item)."""
    flat = _unwrap(doc)
    out: List[Tuple[str, Any]] = []
    for k, v in flat.items():
        lk = str(k).lower()
        if not isinstance(v, list) or not v:
            continue
        if lk.startswith("propert") or "propert" in lk or "compliance" in lk:
            for it in v:
                out.append((str(k), it))
    return out


def property_anchor(item: Any, universe: Set[str]) -> Tuple[bool, str, Any]:
    """(is_actionable, how, evidence) for one L16 property."""
    if isinstance(item, str):
        hits = _resolving_tokens(item, universe)
        if hits:
            return True, "prose_token_resolves", sorted(hits)[:5]
        return False, "prose_only_no_resolvable_token", item[:120]

    if not isinstance(item, dict):
        return False, "unrecognised_shape", repr(item)[:120]

    # (a) explicit signal anchors
    for k in _ANCHOR_SIGNAL_KEYS:
        v = item.get(k)
        cands: List[str] = []
        if isinstance(v, str):
            cands = [v]
        elif isinstance(v, list):
            cands = [(x.get("name") if isinstance(x, dict) else x) for x in v]
        hits = [c for c in cands if isinstance(c, str)
                and _norm(c) in universe]
        if hits:
            return True, f"explicit_anchor:{k}", hits[:5]

    # (b) spec reference
    for k in _SPEC_REF_KEYS:
        v = item.get(k)
        if not isinstance(v, str) or not v.strip():
            continue
        if _LDOC_REF.search(v):
            return True, f"spec_ref:{k}->L-doc", v[:80]
        if _CLAUSE_REF.search(v):
            return True, f"spec_ref:{k}->clause", v[:80]
        if _norm(v) in universe:
            return True, f"spec_ref:{k}->entity", v[:80]

    # (c) prose token that resolves in the design's own entity universe
    for k in _PROP_TEXT_KEYS:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            hits = _resolving_tokens(v, universe)
            if hits:
                return True, f"prose_token_resolves:{k}", sorted(hits)[:5]

    keys = sorted(item.keys())
    only_modal = [k for k in _NON_ANCHOR_KEYS if k in item]
    how = ("only_modal_anchor_token" if only_modal
           else "no_anchor_of_any_kind")
    return False, how, {"keys": keys,
                        "anchor_token": item.get("anchor_token")}


def _resolving_tokens(text: str, universe: Set[str]) -> Set[str]:
    hits: Set[str] = set()
    for m in _WORD.finditer(text or ""):
        t = m.group(0)
        if len(t) < 3:
            continue
        if t.lower() in universe:
            hits.add(t)
    return hits


# ---------------------------------------------------------------------------
# Rail 1: consumer reachability
# ---------------------------------------------------------------------------
def consumer_l16_filenames(programs_dir: Path) -> List[Tuple[str, str, int]]:
    """(consumer_file, filename_literal, line) for every L16*.json a consumer
    program opens. Parsed from the consumer's OWN source — nothing hardcoded
    but the consumer program names themselves."""
    out: List[Tuple[str, str, int]] = []
    for fname in _CONSUMER_PROGRAMS:
        p = programs_dir / fname
        if not p.is_file():
            continue
        try:
            lines = p.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines, start=1):
            if ln.lstrip().startswith("#"):
                continue
            for m in _L16_FILENAME_LITERAL.finditer(ln):
                out.append((fname, m.group(1), i))
    return out


# ---------------------------------------------------------------------------
def audit(project: Path, programs_dir: Path, window: int,
          min_ratio: float) -> Tuple[List[Finding], Dict[str, Any]]:
    findings: List[Finding] = []
    info: Dict[str, Any] = {}

    gd = project / "phase1" / "generated_docs"
    if not gd.is_dir():
        findings.append(Finding("SKIP", "NO_GENERATED_DOCS",
                                f"{gd} does not exist"))
        return findings, info

    on_disk = sorted(p.name for p in gd.glob("L16_*.json"))
    if not on_disk:
        findings.append(Finding("SKIP", "NO_L16_DOC",
                                "no L16_*.json in generated_docs"))
        return findings, info
    info["l16_files_on_disk"] = on_disk

    # -- RAIL 1: DEAD READ ---------------------------------------------------
    reads = consumer_l16_filenames(programs_dir)
    info["consumer_l16_reads"] = [
        {"consumer": c, "filename": f, "line": ln, "exists": f in on_disk}
        for c, f, ln in reads]
    # A consumer is reachable when AT LEAST ONE of the L16 filename literals it
    # opens resolves on disk (a documented fallback chain is legitimate). A
    # consumer whose every literal misses cannot reach the layer at all.
    by_consumer: Dict[str, List[Tuple[str, int]]] = {}
    for c, f, ln in reads:
        by_consumer.setdefault(c, []).append((f, ln))
    dead_consumers = {c: lits for c, lits in by_consumer.items()
                      if not any(f in on_disk for f, _ in lits)}
    stale_literals = [(c, f, ln) for c, f, ln in reads
                      if f not in on_disk and c not in dead_consumers]
    if dead_consumers:
        findings.append(Finding(
            "ERROR", "CONSUMER_DEAD_READ",
            f"{len(dead_consumers)} consumer program(s) open ONLY L16 "
            f"filenames that do NOT exist in this run, while {on_disk} IS "
            f"present. The read returns nothing and raises no error, so this "
            f"layer's contribution to that consumer is ALWAYS empty no matter "
            f"how good L16 is — a silent dead read. A gate on L16 content "
            f"without this fix would enforce content that still reaches "
            f"nobody.",
            {"dead_consumers": {c: [{"opens": f, "line": ln}
                                    for f, ln in lits]
                                for c, lits in dead_consumers.items()},
             "present_on_disk": on_disk}))
    if stale_literals:
        findings.append(Finding(
            "WARNING", "CONSUMER_STALE_FILENAME_FALLBACK",
            f"{len(stale_literals)} L16 filename literal(s) in the consumers "
            f"do not exist in this run, but each of those consumers has "
            f"another literal that does resolve — a fallback chain, not a "
            f"dead read.",
            {"stale": [{"consumer": c, "opens": f, "line": ln}
                       for c, f, ln in stale_literals]}))
    if not reads:
        findings.append(Finding(
            "WARNING", "NO_CONSUMER_FOUND",
            f"none of {list(_CONSUMER_PROGRAMS)} was found under "
            f"{programs_dir}; the reachability rail could not run."))

    # -- RAIL 2: ACTIONABILITY ----------------------------------------------
    # Audit whichever L16 doc actually carries content (canonical name first).
    doc_name = on_disk[0]
    raw = _read_json(gd / doc_name)
    if raw is None:
        findings.append(Finding("SKIP", "INVALID_JSON",
                                f"{doc_name} is not readable JSON"))
        return findings, info

    status = str(raw.get("extraction_status") or raw.get("status")
                 or _unwrap(raw).get("extraction_status") or "").strip().upper()
    props = collect_properties(raw)
    info.update({"l16_audited": doc_name,
                 "extraction_status": status or None,
                 "properties_found": len(props),
                 "property_containers": sorted({k for k, _ in props})})

    universe = build_entity_universe(gd, exclude=set(on_disk))
    info["entity_universe_size"] = len(universe)

    if not props:
        if status in _STATUS_SUCCESS:
            findings.append(Finding(
                "ERROR", "STATUS_CONTRADICTS_PAYLOAD",
                f"{doc_name} reports extraction_status={status!r} but emits "
                f"ZERO properties. A completeness accounting that trusts the "
                f"status field will record this layer as CAPTURED while its "
                f"consumers receive nothing.",
                {"status": status, "top_level_keys": sorted(raw.keys())}))
        else:
            findings.append(Finding(
                "INFO", "HONEST_EMPTY",
                f"{doc_name} emits no properties and says so "
                f"(extraction_status={status!r}). Truthful — PASS."))
        return findings, info

    # -- E4 PAYLOAD_WITHOUT_EXTRACTION (the mirror of E2) --------------------
    # Reached only when the layer IS populated, so this arm and HONEST_EMPTY
    # above are exhaustive over the found-nothing statuses: empty is truthful
    # and passes, populated is self-contradictory and is reported.
    if status in _STATUS_FOUND_NOTHING:
        raw_ev = raw.get("extraction_evidence") or raw.get("evidence")
        findings.append(Finding(
            "ERROR", "PAYLOAD_WITHOUT_EXTRACTION",
            f"{doc_name} reports extraction_status={status!r} — the producer "
            f"says extraction contributed nothing — yet the layer ships "
            f"{len(props)} propert(ies), and extraction_evidence is "
            f"{'empty' if not raw_ev else 'present'}. Both fields were "
            f"written by the same emitter in the same emission, so the layer "
            f"contradicts itself: every property still reaches the SVA "
            f"generator's consumer window as a verification obligation, and "
            f"nothing downstream can tell which of them extraction actually "
            f"supports. This finding asserts ONLY that self-contradiction — "
            f"it makes no claim about where the content came from.",
            {"status": status,
             "properties_found": len(props),
             "extraction_evidence_empty": not bool(raw_ev),
             "emitted_by": raw.get("emitted_by"),
             "property_containers": sorted({k for k, _ in props})}))

    results = []
    for idx, (container, item) in enumerate(props):
        ok, how, ev = property_anchor(item, universe)
        results.append({"index": idx, "container": container,
                        "actionable": ok, "how": how, "evidence": ev})
    actionable = [r for r in results if r["actionable"]]
    ratio = len(actionable) / len(results)
    info["actionable_count"] = len(actionable)
    info["actionable_ratio"] = round(ratio, 4)
    info["consumer_window"] = window
    info["properties"] = results[:60]

    in_window = results[:max(1, window)]
    if not any(r["actionable"] for r in in_window):
        findings.append(Finding(
            "ERROR", "NO_ACTIONABLE_PROPERTY_IN_CONSUMER_WINDOW",
            f"None of the first {len(in_window)} propert(ies) — the window the "
            f"SVA consumer actually reads — carries a machine-usable anchor "
            f"(no resolvable signal anchor, no L-doc/clause spec_ref, no prose "
            f"identifier that resolves against this design's own declared "
            f"entities). Every one becomes a truncated comment; the SVA "
            f"generator provably receives ZERO bindable obligations, so this "
            f"layer is false-CAPTURED.",
            {"window": len(in_window),
             "why_not_actionable": [
                 {"index": r["index"], "how": r["how"],
                  "evidence": r["evidence"]} for r in in_window[:10]]}))
    elif ratio < min_ratio:
        findings.append(Finding(
            "WARNING", "LOW_ACTIONABLE_RATIO",
            f"only {len(actionable)}/{len(results)} "
            f"({ratio:.0%}) of L16 properties carry a machine-usable anchor; "
            f"the remainder reach the consumer as truncated prose comments.",
            {"unanchored": [
                {"index": r["index"], "how": r["how"]}
                for r in results if not r["actionable"]][:20]}))

    ev = raw.get("extraction_evidence") or raw.get("evidence")
    if status in _STATUS_SUCCESS and not ev:
        findings.append(Finding(
            "WARNING", "NO_EXTRACTION_EVIDENCE",
            f"extraction_status={status!r} but extraction_evidence is empty, "
            f"so no property in this layer is traceable to a source line."))

    return findings, info


def build_report(project: Path, findings: List[Finding],
                 info: Dict[str, Any]) -> dict:
    errs = [f for f in findings if f.severity == "ERROR"]
    return {
        "program": "l16_compliance_properties_actionable_check",
        "version": "1.0.0",
        "layer": "L16",
        # vibe-ic#316 — was "BLOCKS". Nothing wired this gate anywhere, so
        # `flow_gate_enforcement_audit` recorded it as an ORPHAN that declares
        # an intent it cannot act on: it could not block, it could not even
        # run. Held out of the advisory slot precisely BECAUSE it said BLOCKS,
        # which is how the declaration kept it from executing at all.
        # Measured over the 12 published cells under benchmark-data/ before
        # changing this: rc=0 on eleven, SKIP on one — it has never returned a
        # finding on a real input, so promoting it to blocking would be
        # promoting an unmeasured gate. ADVISES + wired into the flow's
        # advisory slot makes it judge real data; the evidence to argue a
        # promotion can then exist.
        "verdict_mode": "ADVISES",
        "project": str(project),
        "summary": {
            "pass": not errs,
            "error_count": len(errs),
            "warning_count": sum(1 for f in findings
                                 if f.severity == "WARNING"),
            "finding_count": len(findings),
        },
        "info": info,
        "findings": [asdict(f) for f in findings],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="L16 compliance-property actionability gate")
    ap.add_argument("project", type=Path,
                    help="run root containing phase1/generated_docs")
    ap.add_argument("--json", default=None, help="write JSON report here")
    ap.add_argument("--advisory", action="store_true",
                    help="report only; always exit 0 unless unreadable")
    ap.add_argument("--consumer-window", type=int, default=8,
                    help="properties the SVA consumer reads (default 8, "
                         "mirrors professional_tb_gen's properties[:8])")
    ap.add_argument("--min-actionable-ratio", type=float, default=0.5,
                    help="ratio below which a WARNING is raised")
    ap.add_argument("--programs-dir", type=Path, default=None,
                    help="directory holding the consumer programs "
                         "(default: this file's directory)")
    args = ap.parse_args(argv)

    programs_dir = args.programs_dir or Path(__file__).resolve().parent
    findings, info = audit(args.project, programs_dir,
                           args.consumer_window, args.min_actionable_ratio)
    report = build_report(args.project, findings, info)
    out = json.dumps(report, indent=2, ensure_ascii=False, default=str)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)

    if any(f.severity == "SKIP" for f in findings):
        return 2
    if args.advisory:
        return 0
    return 1 if any(f.severity == "ERROR" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
