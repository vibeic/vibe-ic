"""Reconcile L4's register-map CLAIMS with the register list it carries.

Three L4 fields talk about the same fact and can disagree:

    registers[]            — the substance: what the document actually carries
    register_map_present   — the claim "this design has a SW-visible register map"
    no_registers_in_input  — the claim "the input documents declare no registers"

Issue #516 measured the disagreement on a real project: an L4 that named its
source document, recorded that registers ARE present in the input, asserted a
register map IS present, and carried an empty list. A document making a
positive claim its own content contradicts is the same defect shape #512
removed (fabricated registers) and #514 removed (`no_electrical_specs_in_input`
disagreeing with the specs beside it).

The root cause of the `register_map_present` half is not the extractor: it is
that the claim was never derived from anything. Every protocol-synth overlay
routes through one `_apply_universal` helper which does an unconditional
``setdefault("register_map_present", True)`` on EVERY dispatched design, so the
key is stamped True on documents whose register list is empty and on documents
nobody ever looked at. A claim nothing substantiates is not a default; it is an
assertion the flow cannot back.

DIRECTION OF REPAIR — the substance wins, always. `registers[]` carries
per-row `evidence` pointing at the document and line it came from; the two
booleans carry none. So a claim the list contradicts is withdrawn or corrected,
and the list is never edited to make a claim come true.

THE RULES (each one is a separate, separately-tested decision):

R1  `register_map_present: True` is substantiated ONLY by a non-empty
    `registers`. With an empty list the key is REMOVED, not set to False.
    Absent means "this flow makes no claim either way", which is the honest
    state when nothing was found and nothing in the input said there is
    nothing. It is also behaviour-neutral: every consumer in the tree tests
    ``is False`` (`l4_regmap_phase2_emitter_contract_check`,
    `l_doc_structured_field_count_check`, `flow_compliance_check`), so absent
    and True are read identically and withdrawing an unsupported True cannot
    hand any gate a pass it did not already have. Rewriting it to False WOULD
    hand out that pass — it is the N/A escape hatch — which is why R1 removes
    rather than negates. (Issue #516 constraint 3: "if a claim cannot be
    substantiated it must not be emitted. Do not solve this by weakening the
    claims into always-false.")

R2  `register_map_present: False` is left alone when the list is empty. Phase 1
    sets that value in exactly one place, from an explicit in-document
    assertion that the design has no SW-visible register map, and it records
    the evidence when it does. That is a substantiated claim; the fact that the
    list is empty agrees with it.

R3  `no_registers_in_input: True` is falsified only by a register whose OWN
    evidence names an input document. This is deliberately narrower than
    "falsified by a non-empty list": `registers[]` also accumulates entries
    from synth overlays and prose promotion that carry `evidence: null`, and
    those say nothing about what the input declares. Flipping the claim on
    their account would launder a non-input register into a statement about the
    input — the exact move #512 was filed against. A register with input
    evidence, by contrast, IS the input declaring a register, so the claim is
    corrected to False.

R4  A `register_map_present: False` sitting beside a non-empty list is a
    genuine two-source conflict: the document asserted there is no register map
    and the flow then found registers. Neither side is silently preferred.
    It is recorded under `register_map_claim_conflict` for a human, and both
    fields are left as they are. Fail-closed beats guessing.

Pure and I/O-free: `reconcile_register_map_claims` mutates the dict it is given
and returns the list of changes, so it is callable from the phase-1 runner, from
a gate, or from a test without a project on disk. Chip-AGNOSTIC — it reads
nothing but the three fields and the per-register evidence shape.
"""

from __future__ import annotations

from typing import Any, Dict, List

CLAIM_PRESENT = "register_map_present"
CLAIM_NONE_IN_INPUT = "no_registers_in_input"
CONFLICT_KEY = "register_map_claim_conflict"

# A register's `evidence` names an input document when it points INTO the
# project's input tree. Both spellings occur in the tree: the L4 emitters stamp
# `input/docs/<name>` and the post-emit table scan stamps the extracted-text
# mirror `phase1/input_doc/<name>`. Matching on the path prefix keeps this
# chip-AGNOSTIC (no filename, no design, no extension list).
_INPUT_EVIDENCE_PREFIXES = ("input/docs", "input_doc", "input/")


def _evidence_sources(reg: Dict[str, Any]) -> List[str]:
    """Every source string a register record offers, across the two evidence
    shapes in the tree: a bare string, or a dict carrying `source`. Also walks
    `corroborating_evidence`, whose entries use both shapes."""
    out: List[str] = []

    def _add(ev: Any) -> None:
        if isinstance(ev, str):
            out.append(ev)
        elif isinstance(ev, dict):
            src = ev.get("source")
            if isinstance(src, str):
                out.append(src)
        elif isinstance(ev, list):
            for item in ev:
                _add(item)

    _add(reg.get("evidence"))
    _add(reg.get("corroborating_evidence"))
    return out


def _cites_input_document(reg: Dict[str, Any]) -> bool:
    """True when this register's evidence names a document under the project's
    input tree — i.e. the input really does declare this register."""
    for src in _evidence_sources(reg):
        norm = src.replace("\\", "/").lstrip("./")
        for prefix in _INPUT_EVIDENCE_PREFIXES:
            if norm.startswith(prefix) or f"/{prefix}" in norm:
                return True
    return False


def register_records(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The `registers` entries that are actual records. A non-list `registers`,
    or stray non-dict members, carry no claim-bearing content."""
    regs = doc.get("registers")
    if not isinstance(regs, list):
        return []
    return [r for r in regs if isinstance(r, dict)]


def reconcile_register_map_claims(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Apply R1-R4 to `doc` in place. Returns one record per change made
    (empty list when the document's claims already agreed with its content).

    Idempotent: running it twice makes no second change.
    """
    changes: List[Dict[str, Any]] = []
    if not isinstance(doc, dict):
        return changes

    records = register_records(doc)
    present = doc.get(CLAIM_PRESENT, None)
    has_present_key = CLAIM_PRESENT in doc

    # ── R1 / R2 / R4 — the `register_map_present` claim ──────────────────
    if not records:
        # R1: nothing substantiates a positive claim. Withdraw it; do NOT
        # negate it (see the module docstring — False is the N/A escape).
        # R2 leaves an explicit, evidence-backed False untouched.
        if has_present_key and present is not False:
            del doc[CLAIM_PRESENT]
            changes.append({
                "rule": "R1",
                "field": CLAIM_PRESENT,
                "action": "removed",
                "was": present,
                "why": ("claimed a register map is present while carrying no "
                        "register records; nothing substantiates the claim, so "
                        "it is withdrawn rather than asserted"),
            })
    else:
        if present is False:
            # R4: the document said there is no register map and the flow
            # then found registers. Record it; resolve nothing.
            if doc.get(CONFLICT_KEY) is None:
                doc[CONFLICT_KEY] = (
                    f"{CLAIM_PRESENT} is False but {len(records)} register "
                    "record(s) are present; the in-document assertion and the "
                    "extracted list disagree and neither was preferred "
                    "automatically")
                changes.append({
                    "rule": "R4",
                    "field": CONFLICT_KEY,
                    "action": "recorded",
                    "register_count": len(records),
                    "why": ("an explicit no-register-map assertion cannot be "
                            "silently overruled by extraction, nor extraction "
                            "by it"),
                })

    # ── R3 — the `no_registers_in_input` claim ───────────────────────────
    if doc.get(CLAIM_NONE_IN_INPUT) is True:
        evidenced = [r for r in records if _cites_input_document(r)]
        if evidenced:
            doc[CLAIM_NONE_IN_INPUT] = False
            changes.append({
                "rule": "R3",
                "field": CLAIM_NONE_IN_INPUT,
                "action": "set_false",
                "was": True,
                "input_evidenced_registers": len(evidenced),
                "why": ("claimed the input declares no registers while "
                        f"{len(evidenced)} register record(s) cite an input "
                        "document as their own evidence"),
            })

    return changes
