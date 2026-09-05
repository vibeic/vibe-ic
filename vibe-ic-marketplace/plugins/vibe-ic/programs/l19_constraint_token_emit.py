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

TOOL = "l19_constraint_token_emit"

_L19_NAME = "L19_CONSTRAINTS_PDK.json"
_DECL_KEY = "constraint_declarations"
_PRESENCE_KEY = "constraints_present"

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
    known = {_identity(r) for r in existing if isinstance(r, dict)}

    emitted = [r for r in found if _identity(r) not in known]

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

    wrote = False
    if (emitted or context_emitted_count) and not dry_run:
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
        doc["fields"] = fields
        # Provenance the layer did not have: which inputs it was read from.
        srcs = doc.get("source_documents")
        srcs = list(srcs) if isinstance(srcs, list) else []
        for r in emitted + [r for rows in context_emitted.values() for r in rows]:
            if r["source"] not in srcs:
                srcs.append(r["source"])
        doc["source_documents"] = srcs
        if doc.get("extraction_status") == "NOT_YET_EXTRACTED":
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
              f"{rep.get('pre_existing', 0)} already present)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
