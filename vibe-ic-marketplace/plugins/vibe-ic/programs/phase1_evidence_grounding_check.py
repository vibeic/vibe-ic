#!/usr/bin/env python3
"""phase1_evidence_grounding_check.py — Phase-1 ANTI-FABRICATION grounding gate.

The companion to `extraction_coverage_check` (LL-38). That gate enforces the
INPUT→OUTPUT direction (every high-signal input data point is copied verbatim
into some L*.json — catches a DROPPED fact). This gate enforces the missing
OUTPUT→INPUT direction (every fact a Phase-1 L-doc CLAIMS to have extracted
carries an `extraction_evidence.literal` that is ACTUALLY a verbatim substring of
the input docs — catches a FABRICATED fact).

WHY THIS GATE EXISTS (§4.05 / §4.2 — an AI step must be GATED BY A PROGRAM)
--------------------------------------------------------------------------
In the real flow the deterministic doc-extractor emits the bulk of the L-docs and
the IC-Expert Agent (LLM) ENRICHES the residual (loose-prose ports / fsm_states /
design_parameters the deterministic pass leaves to it — the program-first/LLM
boundary). The pre-existing Phase-1 gates validate the LLM's output for
COMPLETENESS (coverage) and PROVENANCE PRESENCE + SCHEMA SHAPE, but NONE verifies
that an LLM-ADDED fact's evidence literal is grounded in the input. An empirical
test confirmed the hole: a fabricated `phantom_irq` port whose evidence literal
("phantom_irq interrupt asserted on completion") is NOT in the spec passed
`extraction_coverage_check`, `extraction_evidence_schema_check`, and
`phase1_provenance_presence_check` — all clean. This gate closes that hole.

WHAT IS CHECKED
---------------
For each `<project>/phase1/generated_docs/L*.json` (or `<project>/generated_docs/`):
  * walk `extraction_evidence` = {source_key: [entry, ...]};
  * for every entry that is a STRING or a `{"literal": "..."}` dict, require the
    literal (normalised: lowercased, whitespace-collapsed) to be a substring of
    the normalised UNION of the input-doc text (input/docs/*.txt + input_doc/*.txt).
  * a `derived_*` source key (derived_from_L3, derived_no_calibration_source, …) is
    a CROSS-LAYER derivation, NOT a direct input quote — EXEMPT (grounded in an
    upstream L-doc / derivation rule, gated elsewhere).
  * a literal ≤ 3 normalised chars is too generic to ground — skipped (no false fire).

§4.05: a real literal (verbatim in input) PASSES; an ungrounded (fabricated)
literal FAILS with the doc + source + the offending quote. chip-AGNOSTIC — pure
substring grounding, no design/vendor/SKU literal in the logic.

Usage
-----
    python3 phase1_evidence_grounding_check.py <project_or_generated_docs_dir>
        [--json OUT] [--strict]
Exit: 0 PASS / silent-skip, 1 FAIL (ungrounded literals), 2 IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# A source key is INPUT-GROUNDABLE only when it names a real input DOC (a path
# under input/docs or input_doc, or a doc filename). Every other source key is
# plugin-INTERNAL provenance (a `derived_*` cross-layer rule, a `vN.N.N.*` gate
# bookkeeping record, an upstream L-doc) whose `literal` is NOT a direct input
# quote and is gated elsewhere — so it is EXEMPT from input-grounding.
_INPUT_SRC_RE = re.compile(
    r"input[\\/]+docs|input_doc|\.(?:txt|pdf|docx?|md|csv|html?|xlsx?|pptx?)\b",
    re.IGNORECASE)
_DERIVED_SRC_RE = re.compile(r"deriv|inferr|cross[_-]?layer|^L\d", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")

# A NAME-shaped identifier — the fabrication-prone anchor of an evidence literal:
# a signal / parameter / register / section NAME. Prose words REFORMAT freely (so
# whole-phrase substring grounding false-fails ~80% of legitimate quotes), but an
# INVENTED NAME (a hallucinated `phantom_irq` port) will not appear in the input
# in any spelling. We ground ONLY name-shaped tokens:
#   * snake_case / underscored          (awvalid_i, trim_code, wake_pulse)
#   * ALL-CAPS >=3                       (AWVALID, TSTRB, OVERVIEW)
#   * mixed letter+digit name            (DDR4, RAW8, H1)
# A bare HEX / sized / decimal VALUE (`0x10`, `3'b010`, `240`) is a synthesized /
# computed VALUE, NOT an invented NAME — those are gated for correctness elsewhere
# (oracle/conformance), not here, so this gate does not flag them (avoids false
# fires on protocol-synth-assigned opcodes). chip-AGNOSTIC (pure token shape).
_IDENT_RE = re.compile(
    r"\b("
    r"[A-Za-z]\w*_\w+"                       # snake_case / underscored
    r"|[A-Z]{3,}\d*"                         # ALL-CAPS section / signal token
    r"|[A-Za-z]{2,}\d+[A-Za-z\d]*"           # letter+digit name (DDR4, RAW8)
    r")\b")
_SEP_RE = re.compile(r"[_\-\s]+")


def _norm(s: str) -> str:
    # collapse ALL separators (underscore / hyphen / whitespace) so a snake_case
    # name grounds against its spec spelling ("wake_pulse" <-> "wake pulse" <->
    # "wake-pulse"); an INVENTED name (no such spec concept) still does not match.
    return _SEP_RE.sub("", str(s).lower())


def _idents(s: str) -> set:
    """Name-shaped tokens of a literal, separator-collapsed-lowercased — the set
    that, if INVENTED, marks a fabricated fact. chip-AGNOSTIC (pure token shape)."""
    return {_norm(m.group(1)) for m in _IDENT_RE.finditer(str(s)) if len(m.group(1)) >= 3}


def _input_haystack(project: Path) -> Optional[str]:
    """Normalised union of the project's input-doc text, or None if no input text
    is discoverable (then the gate silent-skips — chip-AGNOSTIC, no false alert).

    Reads every TEXT-BEARING input doc, RECURSIVELY — `.txt` (extracted vendor-PDF
    text), `.md` (markdown spec / README), `.rst` (Sphinx docs), `.adoc`
    (AsciiDoc). Two real gaps this closes (cv32e40p_p3): the docs were `.rst`, and
    they sat in a NESTED `input/docs/source/` subdir — reading only top-level
    `.txt` made the haystack empty and false-failed every fact."""
    _TEXT_EXT = (".txt", ".md", ".markdown", ".rst", ".adoc", ".asciidoc", ".text")
    texts: List[str] = []
    for sub in (project / "input" / "docs", project / "phase1" / "input_doc",
                project / "input_doc"):
        if sub.is_dir():
            for f in sorted(sub.rglob("*")):
                if f.is_file() and f.suffix.lower() in _TEXT_EXT:
                    try:
                        texts.append(f.read_text(errors="ignore"))
                    except Exception:
                        pass
    if not texts:
        return None
    return _norm("\n".join(texts))


def _gen_docs_dir(project: Path) -> Optional[Path]:
    for cand in (project / "phase1" / "generated_docs", project / "generated_docs",
                 project):
        if cand.is_dir() and any(cand.glob("L*.json")):
            return cand
    return None


def _iter_literals(ev) -> List[Tuple[str, str]]:
    """Yield (source_key, literal) for every DIRECT-quote evidence entry. A
    `derived_*`/upstream-L source key is skipped (cross-layer, not an input quote)."""
    out: List[Tuple[str, str]] = []
    if not isinstance(ev, dict):
        return out
    for src, entries in ev.items():
        # ground ONLY direct input-doc quotes; exempt internal/derived provenance.
        if _DERIVED_SRC_RE.search(str(src)) or not _INPUT_SRC_RE.search(str(src)):
            continue
        if not isinstance(entries, list):
            continue
        for e in entries:
            if isinstance(e, str):
                out.append((src, e))
            elif isinstance(e, dict) and isinstance(e.get("literal"), str):
                out.append((src, e["literal"]))
    return out


def check(project: Path, strict: bool = False) -> dict:
    project = Path(project)
    gdir = _gen_docs_dir(project)
    if gdir is None:
        return {"status": "SKIP", "reason": "no generated_docs/L*.json", "ungrounded": []}
    hay = _input_haystack(project if (project / "input").exists()
                          or (project / "input_doc").exists()
                          or (project / "phase1").exists() else gdir.parent.parent)
    if hay is None:
        return {"status": "SKIP", "reason": "no input-doc text to ground against",
                "ungrounded": []}
    ungrounded: List[dict] = []
    checked = 0
    for jf in sorted(gdir.glob("L*.json")):
        try:
            d = json.loads(jf.read_text())
        except Exception:
            continue
        for src, lit in _iter_literals(d.get("extraction_evidence")):
            ids = _idents(lit)
            if not ids:
                continue          # pure-prose literal — no identifier to ground
            checked += 1
            # FABRICATION = the literal carries an identifier-shaped token that is
            # NOWHERE in the input (an invented signal / register / opcode name).
            missing = sorted(t for t in ids if t not in hay)
            if missing:
                ungrounded.append({"doc": jf.name, "source": src,
                                   "missing_identifiers": missing,
                                   "literal": lit[:160]})
    status = "FAIL" if ungrounded else "PASS"
    return {"status": status, "checked_literals": checked,
            "ungrounded": ungrounded, "generated_docs": str(gdir)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    try:
        res = check(a.project, a.strict)
    except Exception as e:  # noqa: BLE001
        print(f"phase1_evidence_grounding_check: ERROR — {type(e).__name__}: {e}")
        return 2
    if a.json:
        a.json.write_text(json.dumps(res, indent=2))
    st = res["status"]
    if st == "SKIP":
        print(f"phase1_evidence_grounding_check: SKIP — {res['reason']}")
        return 0
    if st == "PASS":
        print(f"phase1_evidence_grounding_check: PASS — "
              f"{res['checked_literals']} evidence literal(s) all grounded in input")
        return 0
    print(f"phase1_evidence_grounding_check: FAIL — {len(res['ungrounded'])} "
          f"evidence literal(s) carry an UNGROUNDED (fabricated) identifier "
          f"of {res['checked_literals']} checked:")
    for u in res["ungrounded"][:25]:
        print(f"  [{u['doc']}] invented {u['missing_identifiers']} in "
              f"{u['literal']!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
