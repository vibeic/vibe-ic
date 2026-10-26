#!/usr/bin/env python3
"""l19_constraint_token_emit.py — lift the constraints a design states in its
OWN PROSE into L19, the layer that carries them.

VERDICT SEMANTICS: **REPAIRS** (exit 0 unless L19 is unreadable). Not a gate.
ENFORCEMENT: **ADVISORY producer** at the Phase-1 runner boundary.  A missing
declaration emits zero and changes nothing; an unreadable L19 returns a named
ERROR which the runner prints as a named fail-open adapter failure.

The measured defect
------------------------------------------------------------------
Reproduced on a real Phase-1 document run at pre-fix `origin/main`
(`5062b12480fb`, plugin v1.15.14). The design's L9 input document states:

    §9.1   an SDC block containing `set_units` and `create_clock`
    §9.1.3 `set_input_delay` / `set_output_delay` at 20% of the period
    §9.1B  a `MAX_FANOUT_CONSTRAINT` table, per std-cell library
    §9.2.1 an `FP_CORE_UTIL` / `PL_TARGET_DENSITY` table, per PDK family
    §9.3   `FP_PDN_VOFFSET` / `FP_PDN_HOFFSET` / `FP_PDN_SKIPTRIM`

and the emitted `L19_CONSTRAINTS_PDK.json` carried NONE of them. Measured
with the plugin's own `phase1_expert_parse_track.phrase_present` over the
emitted layer: 10 of 10 tokens present in the input, 0 of 10 present in L19.

The layer did not merely omit them. It stated the opposite:

    "constraints_present": false,
    "notes": "Spec does not state PDK / timing constraints; these are
              deferred to integration."

A missing fact is a hole a downstream consumer can notice. A stated
falsehood is one it cannot: the note is the half a human reads, and it
told the reader to stop looking.

Why the existing ingest did not cover it
------------------------------------------------------------------
`_post_emit_sdc_constraints` reads STAGED `*.sdc` FILES and
`_post_emit_floorplan_contract` reads a STAGED OpenLane `config.json` /
`DIE_AREA`. Both are correct and neither applies here: this design ships
no deck and no config — it ships the constraint as a table in a document,
which is the normal shape for a specification handed to an implementer.
So the two file-based ingests found nothing, `constraints_present` was
never set, and `spi_protocol_synth`'s neutral overlay (which uses
`setdefault`, and therefore yields to any real extraction) filled the gap
with the false negative and its note.

That overlay is ALREADY built to yield: its own block comment records the
same class of contradiction ("an L19 carrying a `pdk_target` read from the
design's own input prose … was emitted alongside a note saying the spec
does not include PDK / timing constraints"). It just had nothing to yield
TO. This emitter is that missing producer, and it is wired to run BEFORE
the overlay so the existing `setdefault` + contradiction machinery does
the rest — no module here rewrites another module's note.

What is emitted, and what is NOT
------------------------------------------------------------------
`fields.constraint_declarations[]`, one record per DECLARATION:

    kind        "flow_setting" | "sdc_directive"
    token       the key (`FP_CORE_UTIL`) or the directive (`create_clock`)
    value       the bound value, for a flow setting; absent for a directive
    scope       the design's own scope for the value — the row key of a
                column-oriented table (a std-cell library, a PDK family).
                NEVER dropped: two rows of one table are two different
                targets, and collapsing them lets the last one win.
    section     the heading PATH the design filed it under
    domain_anchor  the part of that path (or of the document title) that
                files it under the constraints domain — see `_DOMAIN_RE`.
                Recorded so "why is this in L19" is answerable FROM THE
                LAYER rather than by re-running the extractor.
    source/line project-relative provenance
    evidence    the document's own row

Three implementation-context fields are also projected when, and only when,
the design's own prose declares them explicitly:

    fields.reference_flow[]         a NAMED reference-flow path plus the
                                    surrounding declaration; the path is
                                    recorded but never opened here
    fields.implementation_route[]   a section explicitly labelled as the
                                    implementation route / intended path
    fields.verification_oracle[]    a section explicitly labelled as the
                                    verification oracle; names only, never
                                    oracle contents

These are L19 implementation context, not constraints, so they do not set
`constraints_present`.  They carry the same project-relative source, line,
evidence and extraction-strategy provenance as constraint declarations.

Whether or not anything is lifted, the layer records THE READ SET —
`documents_consulted[]`, every input document this emitter opened with a
`yielded` flag — outside `fields`, because reading a document is not
extracting from it. Without it a layer that carries only prompt-stated facts
is indistinguishable from one whose emitter never opened the design
documents, and the two were in fact confused (vibe-ic#2128).

`constraints_present` becomes True — and ONLY on evidence. With no
declaration found, this emitter writes nothing at all and the layer keeps
whatever the file-based ingests and the overlay put there, which is the
honest state for a design that really did defer its constraints.

NOT emitted:
  * no `*_status` result field — Phase 1 reads a specification, and a
    specification states targets, not outcomes;
  * no clock PERIOD table. `create_clock`'s per-library period is owned by
    `sdc_constraints` / the L8 clock-domain ingest, and a second producer
    for one fact is how two layers come to disagree. The directive record
    carries the period row as `evidence` so the provenance is not lost.

Refusals (never invent a constraint)
------------------------------------------------------------------
  * a key with no value bound to it is a MENTION, not a setting, and is
    dropped — see `constraint_prose_tokens.table_bindings`;
  * a key the design filed under some OTHER subject is that subject's, not
    this layer's. A CPU's `IC_SIZE_BYTES` belongs to L8, a crypto block's
    `KEY_SHARE0_0` to L5, a power IC's `VOUT_COMMAND` to L15. See the
    DOMAIN ANCHOR block below — it is the correction a corpus sweep forced,
    and without it this emitter put ~350 of another layer's constants into
    the constraints layer across the tracked corpus;
  * a code block is CODE. `export TOOLCHAIN=/path` has the exact shape of a
    setting and is not one — see `constraint_prose_tokens._code_block_lines`;
  * duplicate corpora are counted once. Path A ships each input as both
    `phase1/input_doc/x.txt` and `input/docs/x.md`; the same declaration
    read twice is one declaration, and an evidence count that doubles
    with the corpus layout is a copy count wearing an evidence count's
    name;
  * re-running is idempotent — a declaration already present for the same
    (kind, token, scope, value) is not duplicated, and an existing entry
    is never modified or removed.

chip-AGNOSTIC: SDC command names, UPPER_SNAKE key SHAPE, and the
physical-design DOMAIN vocabulary. No design name, PDK name, cell-library
name or vendor literal anywhere in this file or in
`constraint_prose_tokens` — and note that being chip-agnostic was never the
hard part. The rejected alternative (a whitelist of one tool's variable
names) is equally chip-agnostic and equally wrong; what separates them is
what each puts in the layer, which only a corpus sweep can tell you.

Usage:
    python3 l19_constraint_token_emit.py <project_dir> [--json OUT] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from l_doc_consumer_contract import (  # noqa: E402
    input_doc_texts,
    project_relative_source,
)
import constraint_prose_tokens as _cpt  # noqa: E402
import _prose_polarity as _polarity  # noqa: E402
import _atomic_artefact as _aa  # noqa: E402
# The L-document write chokepoint — records the producing release.
import l_doc_generator_stamp as _stamp  # noqa: E402
import l_doc_consumer_contract as _ldc  # noqa: E402

TOOL = "l19_constraint_token_emit"

_L19_NAME = "L19_CONSTRAINTS_PDK.json"
_DECL_KEY = "constraint_declarations"
_PRESENCE_KEY = "constraints_present"
#: vibe-ic#2091 — the layer's own record of the design's clock target, INCLUDING
#: when there is not one. See `_clock_target_record`.
_CLOCK_TARGET_KEY = "clock_target"
#: The ONE tier of the period ladder that is keyed by the run's library/PDK.
#: Every other tier answers without consulting a PDK at all, so a PDK name
#: written beside a period they produced is an unbacked claim (vibe-ic#2159).
_PDK_KEYED_TIER = "declared_pdk_table"
#: vibe-ic#2128 — the layer's record of WHICH design documents this emitter
#: actually read, INCLUDING the ones that yielded nothing. See
#: `_documents_consulted`.
_CONSULTED_KEY = "documents_consulted"

# Explicit prose declarations that belong to L19's implementation-context
# contract.  These are domain words, never a design, PDK, tool, standard or
# vendor name.  A mere occurrence of "implementation", "route" or "oracle"
# is not enough: implementation/oracle records require a labelled markdown
# heading, numbered item or colon label.  A reference-flow record requires a
# concrete path.  This is the same declaration-vs-mention boundary the
# constraint half enforces for UPPER_SNAKE keys.
_IMPLEMENTATION_ROUTE_RE = re.compile(
    r"\bimplementation\s+(?:route|path)\b|\bintended\s+path\b|"
    r"實作路徑|实现路径", re.IGNORECASE)
_VERIFICATION_ORACLE_RE = re.compile(
    r"\b(?:functional\s+)?verification\s+oracle\b|"
    r"功能驗證\s*oracle|功能验证\s*oracle", re.IGNORECASE)
_REFERENCE_FLOW_PATH_RE = re.compile(
    r"(?P<path>(?:input[/\\])?(?:reference[_-]?flow|ref[_-]?flow)"
    r"(?:[/\\][A-Za-z0-9_.{}*?\-]+)+[/\\]?)", re.IGNORECASE)
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_NUMBERED_DECL_RE = re.compile(r"^\s*\d+[.)]\s+")

# ─────────────────────────────────────────────────────────────────────
# THE DOMAIN ANCHOR — the shape rule alone is not enough, and this is the
# correction a corpus sweep forced
# ─────────────────────────────────────────────────────────────────────
# `constraint_prose_tokens.is_flow_setting_token` answers "does this LOOK
# like a configuration key". Swept dry-run across 105 published run dirs,
# that alone put into the CONSTRAINTS layer:
#
#   * a CPU's RTL parameters      IC_SIZE_BYTES, IC_LINE_W, BUS_W, ADDR_W
#   * a crypto block's REGISTERS  KEY_SHARE0_0 … KEY_SHARE1_7
#   * a power IC's COMMAND CODES  VOUT_COMMAND, STATUS_BYTE, VIN_ON
#
# Every one has the shape and a value beside it; not one is a flow
# constraint. They belong to L8 (RTL constants), L5 (register map) and L15
# (encoding tables) respectively, and publishing them here would make L19 a
# dumping ground for every named constant in a corpus — the same "a roster
# somebody wrote" failure `l24_signoff_gate_emit` refuses.
#
# The anchor is the SUBJECT the design itself filed the binding under: its
# heading path, or the document's own title. The vocabulary is the
# physical-design domain — a domain, not a tool and not a chip, exactly like
# the sign-off vocabulary in L24.
#
# DELIBERATELY OMITTED, and the omission is the careful part: bare `core`,
# `area`, `pin`, `io`, `place`, `clock`. Each is a legitimate section title
# in a design document about something else entirely — a CPU has a "Core"
# section, a datasheet has a "Pin" section — and admitting them would undo
# the sweep. The multi-word forms (`core utilization`, `die area`, `clock
# constraint`) carry the domain; the bare nouns do not.
#
# SDC DIRECTIVES ARE NOT ANCHORED. `create_clock` is self-identifying: it is
# a word of the constraint language and cannot mean anything else.
_DOMAIN_RE = re.compile(
    r"floor\s?plan|placement|routing|congestion|power\s+(?:network|grid|"
    r"delivery|plan)|pdn|synthes|timing|sdc|constraint|utilis|utiliz|"
    r"density|fanout|die\s+area|core\s+area|core\s+util|aspect\s+ratio|"
    r"corner|pdk|process\s+node|technology\s+node|physical|tape-?out|"
    r"sign-?off|macro\s+placement|pad\s+ring|clock\s+(?:constraint|"
    r"definition|period|tree)"
    r"|約束|约束|佈局規劃|布局规划|佈線|布线|電源網路|电源网络|"
    r"合成|時序|时序|面積|面积|密度|簽核|签核|實體驗證|实体验证",
    re.IGNORECASE)


def _domain_anchored(section: str, title: str) -> Optional[str]:
    """The subject that files this binding under the constraints domain."""
    for candidate in (section or "", title or ""):
        m = _DOMAIN_RE.search(candidate)
        if m:
            return candidate
    return None


_TITLE_RE = re.compile(r"^\s*#\s+(.*\S)\s*$", re.MULTILINE)


def _generated_docs(project: Path) -> Path:
    return project / "phase1" / "generated_docs"


def _identity(rec: Dict[str, Any]) -> tuple:
    """What makes two declaration records THE SAME declaration.

    Source and line are deliberately NOT part of it: the same table
    shipped under two corpus paths is one declaration stated once, and
    including the path would count the corpus layout as evidence.
    """
    return (rec.get("kind"), rec.get("token"),
            rec.get("scope"), rec.get("value"))


def _authority_key(rec: Dict[str, Any]) -> Optional[tuple]:
    """The consumer-visible authority slot for one valued declaration."""
    token = rec.get("token")
    if not isinstance(token, str) or not token.strip():
        return None
    if rec.get("value") is None:
        return None
    scope = rec.get("scope")
    normalized_scope = (
        re.sub(r"\s+", " ", str(scope).strip()).casefold()
        if scope not in (None, "") else None)
    return (token.strip().upper(), normalized_scope)


def _authority_value(value: Any) -> tuple:
    """Compare structured/prose spellings using the consumer's value shape."""
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)):
        try:
            return ("number", Decimal(str(value)).normalize())
        except InvalidOperation:
            pass
    text = re.sub(r"\s+", " ", str(value).strip())
    lowered = text.casefold()
    if lowered.startswith("true"):
        return ("bool", True)
    if lowered.startswith("false"):
        return ("bool", False)
    numeric = text[:-1].strip() if text.endswith("%") else text
    try:
        return ("number", Decimal(numeric).normalize())
    except InvalidOperation:
        return ("text", text.casefold())


def _new_declarations_without_authority_conflict(
        existing: List[Dict[str, Any]],
        found: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Refuse differing values before a later consumer can apply priority.

    Same token/scope is one authority slot.  An identical repeated value is
    corroboration and retains the first record's existing provenance; a
    different scope or token remains an independent declaration.
    """
    authorities: Dict[tuple, tuple] = {}
    identities = {_identity(r) for r in existing if isinstance(r, dict)}

    for rec in existing + found:
        if not isinstance(rec, dict):
            continue
        key = _authority_key(rec)
        if key is None:
            continue
        value = _authority_value(rec.get("value"))
        prior = authorities.get(key)
        if prior is not None and prior != value:
            token, scope = key
            scope_text = scope if scope is not None else "<global>"
            raise ValueError(
                "L19_CONSTRAINT_AUTHORITY_CONFLICT: "
                f"{token}@{scope_text}")
        authorities.setdefault(key, value)

    emitted: List[Dict[str, Any]] = []
    existing_authorities = {
        _authority_key(rec): _authority_value(rec.get("value"))
        for rec in existing if isinstance(rec, dict)
        and _authority_key(rec) is not None
    }
    for rec in found:
        key = _authority_key(rec)
        if key is not None and key in existing_authorities:
            # Equal authority values were proven above.  Keep the first
            # producer's record and provenance, matching existing dedupe.
            continue
        if _identity(rec) not in identities:
            emitted.append(rec)
            identities.add(_identity(rec))
    return emitted


def _paragraphs(text: str):
    """Yield ``(line, lines)`` for non-empty prose paragraphs.

    Wrapped declaration lines must stay together: a path is commonly placed
    on the line after the tools or route it qualifies.  Blank lines are the
    conservative boundary; crossing one would let an unrelated paragraph
    lend tokens to a declaration.
    """
    start: Optional[int] = None
    block: List[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            if start is None:
                start = line_no
            block.append(line.strip())
            continue
        if block:
            yield start, block
            start, block = None, []
    if block:
        yield start, block


def _is_labelled_declaration(lines: List[str], pattern: re.Pattern) -> bool:
    """True only for a heading/list/label that explicitly names a contract."""
    if not lines:
        return False
    first = lines[0]
    if not pattern.search(first):
        return False
    if _MARKDOWN_HEADING_RE.match(first) or _NUMBERED_DECL_RE.match(first):
        return True
    # Unnumbered ``Implementation route: ...`` / ``Verification oracle: ...``
    # is the remaining declaration shape.  Ordinary sentences that merely use
    # the words are refused.
    m = pattern.search(first)
    prefix = first[:m.start()].strip(" *_`") if m else "not-a-label"
    return bool(m and not prefix and re.search(r"[:：]", first[m.start():]))


def _heading_section(paragraphs: List[tuple], index: int) -> List[str]:
    """A markdown heading paragraph plus its body up to the next peer.

    Markdown convention places a blank line after a heading, so treating blank
    lines as the end of every declaration recorded a title and dropped the
    value below it.  Numbered/colon declarations keep their paragraph boundary;
    only a real ``#`` heading owns subsequent paragraphs.
    """
    lines = list(paragraphs[index][1])
    first = lines[0] if lines else ""
    match = re.match(r"^\s{0,3}(#{1,6})\s+", first)
    if not match:
        return lines
    level = len(match.group(1))
    for _, later in paragraphs[index + 1:]:
        later_first = later[0] if later else ""
        next_heading = re.match(r"^\s{0,3}(#{1,6})\s+", later_first)
        if next_heading and len(next_heading.group(1)) <= level:
            break
        lines.extend(later)
    return lines


def _declaration_has_payload(lines: List[str], pattern: re.Pattern) -> bool:
    """A label alone is not an implementation contract."""
    if len(lines) > 1:
        return True
    first = lines[0] if lines else ""
    match = pattern.search(first)
    if not match:
        return False
    suffix = first[match.end():].strip(" *_`():：.—-")
    return bool(suffix)


def collect_implementation_context(project: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Explicit implementation-context declarations from design prose only.

    The named reference/oracle artifacts are never opened.  ``input_doc_texts``
    limits reads to the prompt/document corpus, and this function records only
    the declaration text and path name found there.
    """
    found: Dict[str, List[Dict[str, Any]]] = {
        "reference_flow": [],
        "implementation_route": [],
        "verification_oracle": [],
    }
    seen: set = set()

    def add(field: str, source_path: Path, line: int, lines: List[str],
            **extra: Any) -> None:
        evidence = " ".join(lines).strip()
        if not evidence:
            return
        key = (field, re.sub(r"\s+", " ", evidence).casefold())
        if key in seen:
            return
        seen.add(key)
        src, outside = project_relative_source(source_path, project)
        rec: Dict[str, Any] = {
            "kind": field,
            "source": src,
            "line": line,
            "evidence": evidence,
            "extraction_strategy": f"{TOOL}:explicit_{field}",
        }
        rec.update(extra)
        if outside:
            rec["source_outside_project"] = True
        found[field].append(rec)

    for path, text in input_doc_texts(project):
        paragraphs = list(_paragraphs(text))
        for index, (line_no, lines) in enumerate(paragraphs):
            evidence = " ".join(lines)
            if _is_labelled_declaration(lines, _IMPLEMENTATION_ROUTE_RE):
                declared = _heading_section(paragraphs, index)
                positive = [line for line in declared
                            if not _polarity.is_denied(line)]
                if _declaration_has_payload(positive,
                                            _IMPLEMENTATION_ROUTE_RE):
                    add("implementation_route", path, line_no, positive)
            if _is_labelled_declaration(lines, _VERIFICATION_ORACLE_RE):
                declared = _heading_section(paragraphs, index)
                positive = [line for line in declared
                            if not _polarity.is_denied(line)]
                if _declaration_has_payload(positive,
                                            _VERIFICATION_ORACLE_RE):
                    add("verification_oracle", path, line_no, positive)
            path_match = _REFERENCE_FLOW_PATH_RE.search(evidence)
            if path_match:
                lo, hi = _polarity.sentence_scope(
                    evidence, path_match.start(), path_match.end())
                if not _polarity.is_denied(evidence[lo:hi]):
                    add("reference_flow", path, line_no, lines,
                        path=path_match.group("path"))
    return found


def collect(project: Path) -> List[Dict[str, Any]]:
    """Every constraint declaration the design's own inputs state."""
    texts = input_doc_texts(project)
    titles = {}
    for path, text in texts:
        m = _TITLE_RE.search(text)
        titles[str(path)] = m.group(1).strip() if m else Path(path).stem
    scan = _cpt.scan_inputs(texts)
    out: List[Dict[str, Any]] = []
    seen: set = set()

    def add(rec: Dict[str, Any]) -> None:
        key = _identity(rec)
        if key in seen:
            return
        seen.add(key)
        out.append(rec)

    for s in scan["settings"]:
        if _polarity.is_denied(str(s.get("evidence") or "")):
            continue      # a denied binding is evidence of absence, not a value
        anchor = _domain_anchored(str(s.get("section") or ""),
                                  titles.get(s["source"], ""))
        if anchor is None:
            continue      # a named constant of some other layer's domain
        src, outside = project_relative_source(s["source"], project)
        rec = {
            "kind": "flow_setting",
            "token": s["token"],
            "value": s["value"],
            "scope": s["scope"],
            "section": s.get("section") or None,
            "domain_anchor": anchor,
            "source": src,
            "line": s["line"],
            "evidence": s["evidence"],
            "extraction_strategy": f"{TOOL}:{s['orientation']}",
        }
        if outside:
            rec["source_outside_project"] = True
        add(rec)
    for d in scan["directives"]:
        if _polarity.is_denied(str(d.get("evidence") or "")):
            continue      # a denied directive must not become an L19 mandate
        src, outside = project_relative_source(d["source"], project)
        rec = {
            "kind": "sdc_directive",
            "token": d["directive"],
            "value": None,
            "scope": None,
            "source": src,
            "line": d["line"],
            "evidence": d["evidence"],
            "extraction_strategy": f"{TOOL}:sdc_directive",
        }
        if outside:
            rec["source_outside_project"] = True
        add(rec)
    return out


def _run_bound_provenance(project: Path, _ctp) -> Optional[Dict[str, Any]]:
    """The RUN's own clock-target record, when this project has one.

    vibe-ic#2159 — WHICH RECORD IS AUTHORITATIVE, AND WHY IT IS THIS ONE.
    ``reports/phase3/clock_target_provenance.json`` is written by the Phase-3
    runner with the PDK the run ACTUALLY BUILT AGAINST (`pdk_name`, the
    resolved technology), so it is the one record whose PDK name is bound to
    the number by construction.  #2136 settled the same question for the area
    baseline: the denominator belongs to the technology the run used, never to
    a technology named somewhere in the documents.  L19 therefore mirrors this
    record when it exists rather than re-deriving a second opinion.

    Returns None when there is no readable run record — which is NOT_MEASURED,
    not "the run named nothing".
    """
    try:
        rep = json.loads((project / _ctp.PROVENANCE_REL).read_text(
            errors="replace"))
    except Exception:
        return None
    if not isinstance(rep, dict) or rep.get("period_ns") is None:
        return None
    return rep


def _clock_target_record(project: Path, fields: Dict[str, Any]
                         ) -> Optional[Dict[str, Any]]:
    """L19's record of the clock target — or of its ABSENCE (vibe-ic#2091).

    WHY AN ABSENCE IS A RECORD
    ==========================
    Measured on opentitan_aes x sky130A: the input states no target clock
    period anywhere, L19 said nothing about that, and the flow went on to sign
    off post-route timing against a period it supplied itself (WNS -42.140 ns)
    with no artefact anywhere saying the number was never asked for.

    A layer that is SILENT about a missing constraint and a layer that is
    silent about a constraint it simply did not read are indistinguishable
    downstream, and only one of them is a question for the user.  So the
    absence is written down, with the sentence the input would have had to
    contain, exactly as `clock_target_provenance` phrases it for the STA
    record.  Nothing is defaulted here: when nothing is stated, no number is
    published — only the fact that nothing is stated.

    WHY THIS RECORD DOES NOT NAME A PDK OF ITS OWN (vibe-ic#2159)
    =============================================================
    Measured on `subservient` (lane rbsub6, 8HD-9): this record read
    ``pdk: "sky130", tier: "l8_declared", period_ns: 20.0`` while the run's own
    record read ``pdk: "gf180mcuD", tier: "declared_pdk_table",
    period_ns: 20.0`` citing ``L9_constraints_floorplan.md:34`` — and the
    design's own table in that very file gives ``sky130_fd_sc_hd -> 10 ns``.
    So "sky130 -> 20 ns" contradicted the document it was derived beside.

    The mechanism was this function: it read the PDK from L19's own
    ``pdk_target`` — the technology the DOCUMENTS name as intended — and then
    stamped that name onto a period that the PDK-keyed tier had not produced
    (``l8_declared`` is a PDK-INDEPENDENT tier: an L8 ``clock_mhz``).  A PDK
    name beside a number is a claim that the number belongs to that PDK, and
    here it did not.

    The contract this now follows:

      * when the RUN has published its own provenance, L19 records the SAME
        pdk, tier and period — one run, one answer;
      * otherwise L19 names a PDK only when the tier that answered is itself
        PDK-KEYED (`declared_pdk_table` matched a row for that library);
      * in every other case the pdk is ``NOT_STATED``.  The document-declared
        intent is preserved under ``pdk_target_declared``, which no reader can
        mistake for "the PDK this number belongs to".

    Never another PDK's tier carrying this PDK's number.

    Returns None when the provenance reader is unavailable, which is
    NOT_MEASURED and must not be written as an absence.
    """
    try:
        import clock_target_provenance as _ctp
    except Exception:
        return None
    pdk = ""
    for key in ("pdk_target", "pdk", "pdk_name"):
        val = fields.get(key)
        if isinstance(val, str) and val.strip():
            pdk = val.strip()
            break

    def _rel_cite(cite):
        if not (isinstance(cite, str) and cite):
            return cite
        path, _, tail = cite.rpartition(":")
        rel, _outside = _ldc.project_relative_source(path or cite, project)
        return f"{rel}:{tail}" if path else rel

    def _rel_row(row):
        """Relativise an input path embedded in the resolver's row prose.

        ``clock_target_provenance`` is a run-record producer and therefore
        cites its source absolutely.  This row is copied into L19, a portable
        design artefact, so only the embedded source path is normalised; the
        numeric declaration and surrounding evidence text stay byte-for-byte
        otherwise.
        """
        if not (isinstance(row, str) and row):
            return row
        out = row
        bases = sorted({str(project), str(project.resolve())},
                       key=len, reverse=True)
        for base in bases:
            prefix = base.rstrip("/")
            if not prefix:
                continue
            pattern = re.compile(re.escape(prefix) + r"/[^\s—]+")

            def _replace(match):
                token = match.group(0)
                path, sep, line = token.rpartition(":")
                suffix = f":{line}" if sep and line.isdigit() else ""
                raw_path = path if suffix else token
                rel, _outside = _ldc.project_relative_source(
                    raw_path, project)
                return rel + suffix

            out = pattern.sub(_replace, out)
        return out

    # ── the run's own record wins, when there is one ────────────────────────
    run = _run_bound_provenance(project, _ctp)
    if run is not None:
        return {"status": "DECLARED",
                "period_ns": float(run["period_ns"]),
                "pdk": (run.get("pdk") or "") or None,
                "tier": run.get("tier"),
                "assumed": bool(run.get("assumed")),
                "pdk_source": "run_provenance",
                "pdk_target_declared": pdk or None,
                "evidence": _rel_cite(run.get("cite")) or _ctp.PROVENANCE_REL,
                "row": _rel_row(run.get("row", "")),
                "note": ("mirrors the run's own clock-target provenance at "
                         f"{_ctp.PROVENANCE_REL}; the PDK named here is the "
                         "one the run built against")}

    try:
        rep = _ctp.resolve(project, pdk=pdk)
    except Exception:
        return None
    if rep.get("period_ns") is not None:
        # An L document is a DESIGN artefact the flow diffs across runs, so its
        # provenance must be project-relative — an absolute path records the
        # checkout and the machine. `clock_target_provenance` cites absolutely
        # because its own consumer is a RUN RECORD; the split is
        # `l_doc_consumer_contract.project_relative_source`'s, and the emitter
        # side of it is this line.
        cite = _rel_cite(rep.get("cite"))
        pdk_keyed = rep["tier"] == _PDK_KEYED_TIER
        return {"status": "DECLARED",
                "period_ns": rep["period_ns"],
                # NOT the document's intent: only a PDK the answering tier
                # actually keyed on. See the docstring (#2159).
                "pdk": pdk if (pdk_keyed and pdk) else None,
                "pdk_source": ("declared_pdk_table_match" if pdk_keyed
                               else "NOT_STATED"),
                "pdk_target_declared": pdk or None,
                "tier": rep["tier"],
                "evidence": cite,
                "row": _rel_row(rep.get("row", ""))}
    return {"status": "NOT_STATED",
            "period_ns": None,
            "pdk": None,
            "pdk_source": "NOT_STATED",
            "pdk_target_declared": pdk or None,
            "tiers_consulted": rep.get("tiers_consulted", []),
            "reason": rep.get("would_have_stated", ""),
            "note": ("recorded as an EXPLICIT absence; any period a later "
                     "stage uses is an ASSUMPTION and must be reported as "
                     "one, never as this design's specification")}


# ─────────────────────────────────────────────────────────────────────
# THE READ SET — vibe-ic#2128
# ─────────────────────────────────────────────────────────────────────
# `source_documents` records only the documents that YIELDED a record. A
# document read and found to state nothing therefore leaves no trace at all,
# and when a design states nothing anywhere this emitter writes NOTHING, so
# the layer cannot distinguish:
#
#     (a) the design documents were read and state no constraint, from
#     (b) the design documents were never opened.
#
# Measured: on `benchmark-data/ic/opentitan_aes` this emitter opens all eight
# design documents under `input/docs/` and every record it emits nevertheless
# cites the prompt, because the prompt is the only input that states a
# declaration in an admitted shape. Read from the layer alone that is
# indistinguishable from (b) — and it was read as (b), and filed as a defect
# (vibe-ic#2128). The read set is the one field that separates them.
#
# It is provenance, never a constraint: it is written outside `fields`, it
# never sets `constraints_present`, and it never advances `extraction_status`
# — reading a document is not extracting from it.
def _documents_consulted(project: Path,
                         yielding: set) -> List[Dict[str, Any]]:
    """Every input document this emitter read, and whether it yielded.

    Derived from the SAME `input_doc_texts` call the collectors use, so the
    record cannot drift from the read it describes.
    """
    out: List[Dict[str, Any]] = []
    for path, _text in input_doc_texts(project):
        src, outside = project_relative_source(path, project)
        rec: Dict[str, Any] = {"source": src, "yielded": src in yielding}
        if outside:
            rec["source_outside_project"] = True
        out.append(rec)
    return out


def run(project: Path, dry_run: bool = False) -> Dict[str, Any]:
    l19_path = _generated_docs(project) / _L19_NAME
    if not l19_path.is_file():
        return {"tool": TOOL, "status": "SKIPPED",
                "reason": f"{_L19_NAME} absent (phase1 has not run?)",
                "emitted_count": 0, "emitted": []}
    try:
        doc = json.loads(l19_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"tool": TOOL, "status": "ERROR",
                "reason": f"{_L19_NAME} unreadable: {exc}",
                "emitted_count": 0, "emitted": []}
    if not isinstance(doc, dict):
        return {"tool": TOOL, "status": "ERROR",
                "reason": f"{_L19_NAME} is not an object",
                "emitted_count": 0, "emitted": []}

    found = collect(project)
    context_found = collect_implementation_context(project)
    fields = doc.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    existing = fields.get(_DECL_KEY)
    existing = existing if isinstance(existing, list) else []
    emitted = _new_declarations_without_authority_conflict(existing, found)

    context_emitted: Dict[str, List[Dict[str, Any]]] = {}
    for field, records in context_found.items():
        current = fields.get(field)
        # Preserve an existing non-list contract verbatim.  This emitter may
        # enrich an absent/list field; it never silently reshapes a field some
        # other producer already owns.
        if current is not None and not isinstance(current, list):
            context_emitted[field] = []
            continue
        current_list = current if isinstance(current, list) else []
        current_ids = {
            (str(r.get("kind")),
             re.sub(r"\s+", " ", str(r.get("evidence") or "")).casefold())
            for r in current_list if isinstance(r, dict)
        }
        context_emitted[field] = [
            r for r in records
            if (str(r.get("kind")),
                re.sub(r"\s+", " ", str(r.get("evidence") or "")).casefold())
            not in current_ids
        ]

    context_emitted_count = sum(len(v) for v in context_emitted.values())

    # vibe-ic#2091 — never overwrite a record another producer already owns;
    # this only fills a field that is absent.
    clock_target = (None if _CLOCK_TARGET_KEY in fields
                    else _clock_target_record(project, fields))

    # vibe-ic#2128 — the read set. Computed from every record this emitter
    # would publish (pre-existing ones included: they came from this same
    # read), so "yielded" answers "did THIS document state anything L19
    # carries", not "did this run happen to add something new".
    yielding = {r.get("source") for r in existing if isinstance(r, dict)}
    yielding |= {r["source"] for r in found}
    yielding |= {r["source"] for rows in context_found.values() for r in rows}
    yielding.discard(None)
    consulted = _documents_consulted(project, yielding)
    # Never reshape a key some other producer already owns as a non-list.
    consulted_current = doc.get(_CONSULTED_KEY)
    consulted_owned = (consulted_current is None
                       or isinstance(consulted_current, list))
    consulted_changed = consulted_owned and consulted_current != consulted

    wrote = False
    emitted_anything = bool(emitted or context_emitted_count or clock_target)
    if (emitted_anything or consulted_changed) and not dry_run:
        if clock_target:
            fields[_CLOCK_TARGET_KEY] = clock_target
        if emitted:
            fields[_DECL_KEY] = existing + emitted
        # The layer now carries the design's constraints, so the presence
        # flag is no longer merely unset — it is TRUE, on evidence. This is
        # the value `spi_protocol_synth`'s `setdefault` overlay yields to,
        # which is also what suppresses its contradicting note.
            fields[_PRESENCE_KEY] = True
        for field, records in context_emitted.items():
            if not records:
                continue
            current = fields.get(field)
            fields[field] = (current if isinstance(current, list) else []) + records
        # A read-set-only write touches provenance and nothing else: it must
        # not create or reshape `fields`, nor restate `source_documents`.
        if emitted_anything:
            doc["fields"] = fields
            # Provenance the layer did not have: which inputs it was read from.
            srcs = doc.get("source_documents")
            srcs = list(srcs) if isinstance(srcs, list) else []
            for r in emitted + [r for rows in context_emitted.values()
                                for r in rows]:
                if r["source"] not in srcs:
                    srcs.append(r["source"])
            doc["source_documents"] = srcs
        if consulted_changed:
            doc[_CONSULTED_KEY] = consulted
        # Reading a document is not extracting from it: a read-set-only write
        # must never advance the layer's extraction status.
        if emitted_anything and doc.get("extraction_status") == "NOT_YET_EXTRACTED":
            doc["extraction_status"] = "PARTIALLY_EXTRACTED"
        _stamp.dump(l19_path, doc)
        wrote = True

    return {
        "tool": TOOL,
        "status": "OK",
        "dry_run": dry_run,
        "found_count": len(found) + sum(len(v) for v in context_found.values()),
        "pre_existing": len(existing),
        "emitted_count": len(emitted) + context_emitted_count,
        "constraint_emitted_count": len(emitted),
        "context_emitted_count": context_emitted_count,
        "emitted": emitted,
        "context_emitted": context_emitted,
        "clock_target": clock_target,
        "documents_consulted": consulted,
        "documents_consulted_count": len(consulted),
        "documents_consulted_yielded": sum(1 for r in consulted
                                           if r.get("yielded")),
        "doc_written": str(l19_path) if wrote else None,
    }


def _describe(rec: Dict[str, Any]) -> str:
    if rec["kind"] == "sdc_directive":
        return f"{rec['token']}()"
    scope = f"@{rec['scope']}" if rec.get("scope") else ""
    return f"{rec['token']}{scope}={rec['value']}"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog=TOOL, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    rep = run(project, dry_run=args.dry_run)
    if args.json:
        _aa.write_json(args.json, rep)

    n = rep.get("emitted_count", 0)
    if rep.get("status") != "OK":
        print(f"{TOOL}: {rep.get('status')} — {rep.get('reason')}")
        return 1 if rep.get("status") == "ERROR" else 0
    elif n:
        detail = ", ".join(_describe(r) for r in rep["emitted"][:8])
        context_n = rep.get("context_emitted_count", 0)
        constraint_n = rep.get("constraint_emitted_count", 0)
        if detail:
            detail = f" — {detail}"
        print(f"{TOOL}: lifted {constraint_n} constraint declaration(s) and "
              f"{context_n} implementation-context declaration(s) from the "
              f"design's own inputs into L19{detail}")
    else:
        print(f"{TOOL}: no constraint declaration to lift "
              f"({rep.get('found_count', 0)} found, "
              f"{rep.get('pre_existing', 0)} already present) — "
              f"read {rep.get('documents_consulted_count', 0)} input "
              f"document(s), {rep.get('documents_consulted_yielded', 0)} of "
              f"which state one")
    return 0


if __name__ == "__main__":
    sys.exit(main())
