#!/usr/bin/env python3
"""l19_constraint_token_emit.py — lift the constraints a design states in its
OWN PROSE into L19, the layer that carries them.

VERDICT SEMANTICS: **REPAIRS** (exit 0 unless L19 is unreadable). Not a gate.

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
# The L-document write chokepoint — records the producing release.
import l_doc_generator_stamp as _stamp  # noqa: E402

TOOL = "l19_constraint_token_emit"

_L19_NAME = "L19_CONSTRAINTS_PDK.json"
_DECL_KEY = "constraint_declarations"
_PRESENCE_KEY = "constraints_present"

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
    fields = doc.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    existing = fields.get(_DECL_KEY)
    existing = existing if isinstance(existing, list) else []
    known = {_identity(r) for r in existing if isinstance(r, dict)}

    emitted = [r for r in found if _identity(r) not in known]

    wrote = False
    if emitted and not dry_run:
        fields[_DECL_KEY] = existing + emitted
        # The layer now carries the design's constraints, so the presence
        # flag is no longer merely unset — it is TRUE, on evidence. This is
        # the value `spi_protocol_synth`'s `setdefault` overlay yields to,
        # which is also what suppresses its contradicting note.
        fields[_PRESENCE_KEY] = True
        doc["fields"] = fields
        # Provenance the layer did not have: which inputs it was read from.
        srcs = doc.get("source_documents")
        srcs = list(srcs) if isinstance(srcs, list) else []
        for r in emitted:
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
        "found_count": len(found),
        "pre_existing": len(existing),
        "emitted_count": len(emitted),
        "emitted": emitted,
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
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

    n = rep.get("emitted_count", 0)
    if rep.get("status") != "OK":
        print(f"{TOOL}: {rep.get('status')} — {rep.get('reason')}")
        return 1 if rep.get("status") == "ERROR" else 0
    elif n:
        detail = ", ".join(_describe(r) for r in rep["emitted"][:8])
        more = "" if n <= 8 else f", +{n - 8} more"
        print(f"{TOOL}: lifted {n} constraint declaration(s) from the "
              f"design's own inputs into L19 — {detail}{more}")
    else:
        print(f"{TOOL}: no constraint declaration to lift "
              f"({rep.get('found_count', 0)} found, "
              f"{rep.get('pre_existing', 0)} already present)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
