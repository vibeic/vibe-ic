#!/usr/bin/env python3
"""benchmark_evidence_index.py — say which published cells CONVERGED and which
did not, without opening a JSON per cell (vibe-ic#440).

WHY THIS EXISTS
===============
`benchmark-data/ic/` is what this project points at when it says a cell
converged, and it also holds runs that did not. Measured at the time of
writing: 28 published cells, of which **3** carry an audit verdict of
PASS_WITH_WAIVERS. The other 25 are a failure record or carry no machine
verdict at all — and nothing in the tree says so where a reader looks.

That is not a cosmetic gap. Five cells assert success in the one document
`PUBLISHING.md` designates as the required verdict artefact while their own
`reports/audit/phase23_completion_audit.json` reads FAIL:

    <cell>/RESULT.md          "OVERALL: PRODUCTION-READY"
    <cell>/reports/audit/...  {"verdict": "FAIL", step_counts F=9}

A reader who opens the RESULT.md — the file the publish contract tells them to
open — gets the opposite of the machine verdict. In one cell the run's own
orchestrator report says PASS_WITH_WAIVERS while its audit says FAIL, so the
contradiction is internal to a single published cell.

DELETION IS NOT THE REPAIR (#421, refused on measurement)
=========================================================
Removing the failed runs makes "we never ran this" and "we ran it, it failed,
and we kept the record" the same state — the false-certificate shape this repo
has spent considerable effort removing everywhere else. The failure evidence is
the more valuable half for anyone debugging the flow, and these directories are
load-bearing: they carry the tracked L4 documents that two BLOCKING corpus
gates walk, and some are the reproduction a landed fix was verified against.
So: LABEL, DO NOT DELETE. This program labels.

WHY GENERATED AND GATED, RATHER THAN WRITTEN
============================================
The repo already tried the hand-written version. `BENCHMARK_IC_CAMPAIGN_STATUS.md`
is a hand-maintained status table, and at the time of writing all three of its
citations for the three cells that DID converge point at directories that do
not exist — the folders were renamed to the canonical `v<X.Y.Z>_<PDK>` shape and
the table was not. The one index this repo has is already the file nobody can
trust, and it rotted precisely where it mattered most.

So this index is a PURE FUNCTION of the tracked artefacts plus one curated
sidecar, and `--check` regenerates it and requires byte-equality. There is no
timestamp and no version stamp in the output, because a field that changes on
every run makes byte-equality useless and byte-equality is the whole mechanism:

    a cell whose audit verdict changes while its index row does not is a FAIL.

The same comparison also catches a cell added with no row, a row left behind
for a removed cell, a hand-edit, and a curated note that outlived its cell.

WHAT IS DERIVED vs CURATED
==========================
Derived (never hand-written, re-read from the tree on every run):
  audit verdict     reports/audit/phase23_completion_audit.json -> "verdict"
  step counts       ...the same file's "step_counts" — the MAGNITUDE behind the
                    verdict, which is what separates "failed one gate" from
                    "27 steps never ran". Both read FAIL.
  orchestrator      reports/orchestrator/{vibe_ic,phase3,phase2}_one_shot.json
  RESULT.md         present? and the verdict it declares
  corpus member     does the cell carry TRACKED phase1/generated_docs/ — i.e.
                    is it part of the population the two blocking corpus gates
                    walk? This is the fact that makes deletion expensive, so it
                    is shown on every row rather than argued about per cell.

Curated (the one thing no artefact states): `retention.json`, mapping a cell to
why it is retained — "the reproduction for #N". A cell absent from it gets the
derived default. The sidecar lives beside the index under `benchmark-data/`,
NOT under `programs/`: cell paths carry design and PDK names, and everything
under `programs/` is scanned by `source_chip_agnostic_check`.

CLASSIFICATION
==============
  CONVERGED EVIDENCE  audit verdict is PASS or PASS_WITH_WAIVERS
  RETAINED FAILURE    audit verdict is anything else
  UNAUDITED RECORD    no audit artefact — no machine verdict exists either way

The third bucket is deliberately not folded into either of the others. "No
audit was run" and "an audit ran and failed" are different states, and
collapsing them is the same error as deleting the failures.

WHERE THE CORPUS IS, NOW THAT IT IS NOT HERE (vibe-ic#1710 shape)
=================================================================
The published corpus moved to `vibeic/benchmark-data`, so `<repo>/benchmark-data/ic`
does not exist in this repository. This program used to answer that with

    [benchmark_evidence_index] no such directory: <repo>/benchmark-data/ic   rc=1

and rc=1 in this program MEANS "the index disagrees with the artefacts it
describes" — a claim about the index. There was no such disagreement: the tree
had moved and the gate had not been told. A gate that reports a defect it did
not measure is the same false certificate as a gate that reports a pass it did
not measure, just pointed the other way.

So the corpus is RESOLVED rather than hardcoded, and the three outcomes that
were one word are kept apart — the shape `benchmark_evidence_structure_check`
landed for the same event, spelling `VIBE_IC_BENCHMARK_DATA` the same way,
because a gate and a test suite that disagree about where the corpus lives will
disagree about whether it was checked:

    $VIBE_IC_BENCHMARK_DATA set, no readable
      `<it>/ic`                        -> UNDETERMINED (rc=2). Somebody said where
                                          the corpus is and was wrong. NEVER excused,
                                          with or without the flag below.
    nothing set, none in this repo,
      caller passed --corpus-may-be-absent
                                       -> NO_CORPUS (rc=0). Nothing was scanned, and
                                          NOTHING IS CLAIMED to have been scanned. No
                                          INDEX.md is generated or compared.
    nothing set, none in this repo,
      nobody said so                   -> UNDETERMINED (rc=2). Unchanged.

The override is ANNOUNCED: an index built from a different tree than the one
named on the command line, silently, is how a stale index would be certified
fresh. The opt-in is a FLAG THE CALL SITE PASSES, never a default — that is the
only thing keeping the rc=0 row from becoming the general answer.

AND WHEN THE CORPUS IS THERE BUT EMPTY, THAT IS A MEASUREMENT
=============================================================
`<corpus>/ic` present with no cell in it is "I looked, there is nothing", which
is a different fact from "there was nowhere to look" — collapsing them is the
same error in the other direction. The rendered index says which one it is in
words, so a reader of an empty INDEX.md can tell an empty CLASSIFICATION from an
absent CORPUS without knowing how the file was produced. Under NO_CORPUS no
INDEX.md is written at all, precisely so that an index full of empty sections
can never be mistaken for a corpus that published nothing.

chip-AGNOSTIC: no IC, PDK, vendor or SKU literal appears in this program. Cells
are discovered by walking the published tree; their identity lives only in the
generated Markdown and the curated sidecar, both under the corpus root.

Exit: 0 = PASS or NO_CORPUS, 1 = FAIL (drift, or a curated entry naming no
cell), 2 = UNDETERMINED (the corpus could not be resolved, so nothing was
scanned — which is not a pass).
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _published_tree  # noqa: E402  (the ONE tracked-ness resolver — never re-implement)

GATE = "benchmark_evidence_index"

#: Where a caller may point us at a clone of the published-corpus repository.
#: Spelled exactly as `benchmark_evidence_structure_check.CORPUS_ENV` and
#: `programs/tests/_published_corpus.CORPUS_ENV` spell it — one name for one
#: thing. Two spellings would mean two answers to "was the corpus checked?".
CORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"

IC_SUBDIR = "benchmark-data/ic"
INDEX_NAME = "INDEX.md"
RETENTION_NAME = "retention.json"

AUDIT_REL = "reports/audit/phase23_completion_audit.json"
RESULT_REL = "RESULT.md"
CORPUS_MARKER = "phase1/generated_docs/"
ORCH_ORDER = ("vibe_ic_one_shot", "phase3_one_shot", "phase2_one_shot")

CONVERGED_VERDICTS = {"PASS", "PASS_WITH_WAIVERS"}

CONVERGED = "CONVERGED EVIDENCE"
RETAINED_FAILURE = "RETAINED FAILURE"
UNAUDITED = "UNAUDITED RECORD"
SECTIONS = (CONVERGED, RETAINED_FAILURE, UNAUDITED)

_SECTION_BLURB = {
    CONVERGED: (
        "The cell's own audit artefact reads PASS or PASS_WITH_WAIVERS. This is "
        "what the project means when it says a cell converged."),
    RETAINED_FAILURE: (
        "An audit ran and did NOT converge. These are retained on purpose: "
        "deleting them would make \"we never ran this\" and \"we ran it, it "
        "failed, and we kept the record\" the same state. Read the step counts "
        "— they separate one failed gate from a flow that never reached the "
        "steps at all."),
    UNAUDITED: (
        "No `%s` exists for this cell, so there is NO machine verdict either "
        "way. A claim made in its RESULT.md is unbacked by an audit artefact; "
        "that is not the same as a failure, and it is not a pass." % AUDIT_REL),
}

# RESULT.md verdict extraction. Ordered most-explicit first; the fallback is
# reported as UNSTATED rather than guessed, because a token found anywhere in a
# long narrative document is not a declared verdict and must not be shown as
# one. Half of these documents state their outcome in prose only.
#
# `_LEAD` absorbs the markdown that can precede a declared verdict without
# changing it: blockquote markers and list bullets. Measured — a document
# opening `> STATUS: COMPLETE — flow closed, verified` read as UNSTATED purely
# because the line was inside a blockquote, which under-reported a cell whose
# audit says FAIL. Formatting is not semantics.
_LEAD = r"^[ \t]*(?:[>*+-][ \t]*)*"
_VERDICT_PATTERNS = (
    re.compile(_LEAD + r"(?:\*\*)?OVERALL(?:\*\*)?[ \t]*[:：][ \t]*(?:\*\*)?[ \t]*"
               r"([A-Z][A-Z_-]{2,30})", re.M),
    re.compile(_LEAD + r"(?:\*\*)?Overall\s+verdict(?:\*\*)?[ \t]*[:：][ \t]*"
               r"(?:\*\*)?[ \t]*([A-Z][A-Z_]{2,30})", re.M | re.I),
    re.compile(_LEAD + r"(?:\*\*)?(?:VERDICT|STATUS)(?:\*\*)?[ \t]*[:：][ \t]*"
               r"(?:\*\*)?[ \t]*([A-Z][A-Z_-]{2,30})", re.M),
)
_UNSTATED = "UNSTATED"
_ABSENT = "—"


# ─────────────────────────────────────────────────────────────────────
# Reading the tree
# ─────────────────────────────────────────────────────────────────────

def _read_json(ic_root: Path, tracked: Optional[frozenset], rel: str):
    """Parse a TRACKED json under the ic root, or None.

    Untracked is None on purpose: a file the tree does not publish is not
    evidence a reader who clones ever receives, and counting it would make
    this index differ between a working checkout and a fresh clone — the
    host-dependence `_published_tree` exists to end.
    """
    if tracked is not None and rel not in tracked:
        return None
    p = ic_root / rel
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return "UNPARSEABLE"


def result_verdict(text: str) -> str:
    """The verdict a RESULT.md DECLARES, or UNSTATED.

    Deliberately strict. An earlier draft fell back to "the first PASS/FAIL
    token anywhere in the file", which reported a declared PASS for documents
    whose only match was the word PASS inside a sentence about something else.
    A guessed verdict in the artefact built to stop guessed verdicts is worse
    than an honest UNSTATED.
    """
    for pat in _VERDICT_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).upper().rstrip("-_")
    return _UNSTATED


def discover_cells(ic_root: Path,
                   tracked: Optional[frozenset]) -> List[str]:
    """Published cell directories, relative to the ic root.

    A cell is any directory carrying a tracked audit artefact, a tracked
    RESULT.md, or tracked phase1/generated_docs/ content. The union is
    intentional: keying on the audit alone would hide exactly the cells that
    have no audit, which is one of the three states this index exists to make
    visible.
    """
    cells = set()
    if tracked is None:                      # not a published tree — use disk
        for strip in (AUDIT_REL, RESULT_REL):
            for p in ic_root.rglob(strip):
                rel = p.relative_to(ic_root).as_posix()
                if rel.endswith("/" + strip):
                    cells.add(rel[: -len(strip) - 1])
        for p in ic_root.rglob(CORPUS_MARKER.rstrip("/")):
            rel = p.relative_to(ic_root).as_posix()
            parent = rel[: -len(CORPUS_MARKER.rstrip("/")) - 1]
            if parent:
                cells.add(parent)
        return sorted(cells)

    for t in tracked:
        for marker in ("/" + AUDIT_REL, "/" + RESULT_REL):
            if t.endswith(marker):
                cells.add(t[: -len(marker)])
        idx = t.find("/" + CORPUS_MARKER)
        if idx > 0:
            cells.add(t[:idx])
    return sorted(c for c in cells if c)


def measure_cell(ic_root: Path, tracked: Optional[frozenset],
                 cell: str) -> Dict[str, str]:
    audit = _read_json(ic_root, tracked, f"{cell}/{AUDIT_REL}")
    if audit is None:
        verdict, steps = _ABSENT, _ABSENT
    elif audit == "UNPARSEABLE" or not isinstance(audit, dict):
        verdict, steps = "UNPARSEABLE", _ABSENT
    else:
        verdict = str(audit.get("verdict") or _UNSTATED)
        sc = audit.get("step_counts")
        if isinstance(sc, dict):
            steps = "P{} F{} M{} W{}".format(
                sc.get("PASS", 0), sc.get("FAIL", 0),
                sc.get("MISSING", 0), sc.get("WAIVED", 0))
        else:
            steps = _ABSENT

    orch = []
    for name in ORCH_ORDER:
        o = _read_json(ic_root, tracked,
                       f"{cell}/reports/orchestrator/{name}.json")
        if isinstance(o, dict) and o.get("verdict"):
            orch.append("{}={}".format(
                name.replace("_one_shot", ""), o["verdict"]))

    rrel = f"{cell}/{RESULT_REL}"
    if (tracked is not None and rrel in tracked) or \
       (tracked is None and (ic_root / rrel).is_file()):
        try:
            rv = result_verdict((ic_root / rrel).read_text(errors="replace"))
        except OSError:
            rv = _UNSTATED
    else:
        rv = _ABSENT

    if tracked is not None:
        corpus = any(t.startswith(f"{cell}/{CORPUS_MARKER}") for t in tracked)
    else:
        corpus = (ic_root / cell / CORPUS_MARKER.rstrip("/")).is_dir()

    if verdict == _ABSENT:
        section = UNAUDITED
    elif verdict in CONVERGED_VERDICTS:
        section = CONVERGED
    else:
        section = RETAINED_FAILURE

    return {
        "cell": cell,
        "audit": verdict,
        "steps": steps,
        "orchestrator": "; ".join(orch) if orch else _ABSENT,
        "result_md": rv,
        "corpus": "yes" if corpus else "no",
        "section": section,
    }


def load_retention(ic_root: Path) -> Tuple[Dict[str, str], List[str]]:
    """The curated (`cell -> why it is retained`, free notes) pair.

    Values are prose written by a maintainer. Keys are validated against the
    discovered cells by the caller — a note for a cell that no longer exists
    is a finding, not something to render. `notes` carries what belongs to no
    single row, e.g. a citation this repo repeats that its cited issue does
    not actually make.
    """
    p = ic_root / RETENTION_NAME
    if not p.is_file():
        return {}, []
    try:
        raw = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"[{GATE}] {RETENTION_NAME} is unreadable: {e}")
    if not isinstance(raw, dict):
        raise SystemExit(f"[{GATE}] {RETENTION_NAME}: top level must be an object")
    entries = raw.get("retained_for", {})
    if not isinstance(entries, dict):
        raise SystemExit(
            f"[{GATE}] {RETENTION_NAME}: 'retained_for' must be an object")
    notes = raw.get("notes", [])
    if not isinstance(notes, list):
        raise SystemExit(f"[{GATE}] {RETENTION_NAME}: 'notes' must be a list")
    return ({str(k): str(v) for k, v in entries.items()},
            [str(n) for n in notes])


# ─────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    """Make a value safe to sit in a Markdown table cell.

    A newline in a curated note would silently split one row into two, and a
    generated index that renders wrong is exactly the file nobody trusts.
    """
    return " ".join(s.replace("|", "\\|").split())


def render(rows: List[Dict[str, str]], retention: Dict[str, str],
           notes: Optional[List[str]] = None) -> str:
    n = len(rows)
    by_section = {s: [r for r in rows if r["section"] == s] for s in SECTIONS}
    out: List[str] = []
    out.append("# `benchmark-data/ic/` — what each published cell IS")
    out.append("")
    out.append("<!-- GENERATED FILE — do not hand-edit.")
    out.append("     Regenerate:  python3 vibe-ic-marketplace/plugins/vibe-ic/"
               "programs/benchmark_evidence_index.py --write")
    out.append("     Verify:      python3 vibe-ic-marketplace/plugins/vibe-ic/"
               "programs/benchmark_evidence_index.py --check")
    out.append("     The only hand-maintained input is `retention.json` "
               "beside this file. -->")
    out.append("")
    out.append(
        "This tree holds converged evidence AND runs that did not converge, "
        "and the folder name deliberately does not say which "
        "(`PUBLISHING.md`: the verdict lives in `RESULT.md`, "
        "and a `clean_run_*`/`pass_*` prefix would strip the committed phase "
        "folders). This index is the answer that costs no JSON to read.")
    out.append("")
    out.append(
        "**Nothing here is deleted for failing.** Removing a failed run would "
        "make \"we never ran this\" and \"we ran it, it failed, and we kept "
        "the record\" the same state. Cells marked `corpus: yes` are also the "
        "population two BLOCKING gates walk "
        "(`cross_layer_reference_check --corpus`, "
        "`l4_systemrdl_export audit-corpus`).")
    out.append("")
    out.append("| classification | cells |")
    out.append("|---|---|")
    for s in SECTIONS:
        out.append(f"| {s} | {len(by_section[s])} |")
    out.append(f"| **total** | **{n}** |")
    out.append("")
    if n == 0:
        # AN EMPTY RESULT IS NOT A ZERO UNLESS IT SAYS WHICH ONE IT IS.
        # A reader who opens an index with three empty sections cannot
        # otherwise tell "the corpus was walked and published nothing" from
        # "the corpus was not there" — and only the first of those is a
        # measurement. The second never reaches this renderer at all: with no
        # resolvable corpus the gate prints NO_CORPUS and writes no file, so
        # the mere EXISTENCE of this document means a corpus was walked.
        out.append(
            "**Zero published cells were discovered.** This index is generated "
            "only from a corpus that was resolved and walked, so this is a "
            "MEASUREMENT — the corpus was read and it publishes nothing — and "
            "not a missing corpus. When no corpus can be resolved the generator "
            "writes no index at all and reports `NO_CORPUS`, naming the location "
            "it did not find; see the regenerate command above.")
        out.append("")

    for s in SECTIONS:
        sec = by_section[s]
        out.append(f"## {s} — {len(sec)}")
        out.append("")
        out.append(_SECTION_BLURB[s])
        out.append("")
        if not sec:
            # Not a bare "_none._": an empty CLASSIFICATION and an absent CORPUS
            # are different facts and the reader gets the one that is true.
            out.append("_None — the corpus was walked and no published cell "
                       "falls into this classification. This is not the corpus "
                       "being unavailable; an index is generated only from a "
                       "corpus that was read._")
            out.append("")
            continue
        out.append("| cell | audit verdict | steps | orchestrator | "
                   "RESULT.md says | corpus | retained for |")
        out.append("|---|---|---|---|---|---|---|")
        for r in sec:
            note = retention.get(r["cell"], "")
            if not note:
                note = ("corpus member — walked by both blocking corpus gates"
                        if r["corpus"] == "yes" else "record only")
            out.append("| `{}` | {} | {} | {} | {} | {} | {} |".format(
                _esc(r["cell"]), _esc(r["audit"]), _esc(r["steps"]),
                _esc(r["orchestrator"]), _esc(r["result_md"]),
                r["corpus"], _esc(note)))
        out.append("")

    out.append("## Reading the columns")
    out.append("")
    out.append(
        "- **audit verdict** — `verdict` in the cell's "
        f"`{AUDIT_REL}`. `{_ABSENT}` means the artefact does not exist: no "
        "machine verdict was ever recorded, which is neither a pass nor a "
        "failure.")
    out.append(
        "- **steps** — `step_counts` from the same file: PASS / FAIL / "
        "MISSING / WAIVED. This is the magnitude behind the verdict. `F1` and "
        "`M27` both read FAIL and are not the same result.")
    out.append(
        "- **orchestrator** — the `verdict` each "
        "`reports/orchestrator/*_one_shot.json` recorded. Where it disagrees "
        "with the audit column, the disagreement is real and is shown rather "
        "than resolved.")
    out.append(
        "- **RESULT.md says** — the verdict the human-facing document "
        "DECLARES on an `OVERALL:` / `VERDICT:` / `STATUS:` line. "
        f"`{_UNSTATED}` means it states its outcome in prose only, so no "
        f"verdict was extracted; `{_ABSENT}` means there is no RESULT.md. "
        "Where this column disagrees with **audit verdict**, the cell "
        "contradicts itself — that is the condition this index was built to "
        "make visible.")
    out.append(
        "- **corpus** — the cell carries tracked `phase1/generated_docs/`, so "
        "it is inside the population both blocking corpus gates count. "
        "Changing that population changes their recorded counts.")
    out.append(
        "- **retained for** — from `retention.json` where a maintainer has "
        "recorded one; otherwise derived. Absence is not evidence a cell is "
        "unused: several with no recorded reason are read directly by tests "
        "under `programs/tests/`.")
    out.append("")
    if notes:
        out.append("## Notes")
        out.append("")
        for note in notes:
            out.append(f"- {note}")
        out.append("")
    return "\n".join(out) + "\n"


# ─────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────

def resolve_ic_root(repo_root: Path,
                    announce: bool = False) -> Tuple[Path, str]:
    """(the `ic/` directory to walk, where that path came from).

    `env` when `$VIBE_IC_BENCHMARK_DATA` named it, `repo` when it is this
    repository's own `benchmark-data/ic`. The path is returned WHETHER OR NOT it
    exists — deciding what an absent one means is `main`'s job, and it is a
    different decision per origin: an absent env-named tree is a broken pointer,
    an absent repo-local one is a corpus that lives elsewhere.

    THE POINTER REPLACES A MISSING CORPUS; IT DOES NOT REPLACE A PRESENT ONE.
    `benchmark_evidence_structure_check` lets the pointer win outright, and there
    that is right: its `--tree benchmark-data` is a hardcoded literal nobody
    chose. `--root` here is different — a caller who names a root that DOES carry
    `benchmark-data/ic` has named a readable corpus, and walking a different one
    instead is precisely the "scanned a tree other than the one on the command
    line" failure the announcement exists to prevent. MEASURED: letting the
    pointer win unconditionally turned 15 of the 21 tests in
    `test_issue440_benchmark_evidence_index.py` red for every developer who has
    the pointer set — each fixture builds its own corpus under a tmp root and
    every one of them was silently redirected at the real one.

    Either way the choice is ANNOUNCED, including when the pointer is set and NOT
    followed: a pointer a reader believes is in force, that is not, is the same
    ambiguity in the other direction.

    The clone carries `ic/` at its top (`vibeic/benchmark-data`), which is why
    the env value gets `/ic` appended rather than `/benchmark-data/ic`.
    """
    local = repo_root / IC_SUBDIR
    env = os.environ.get(CORPUS_ENV)
    if local.is_dir():
        if env and announce:
            print(f"[{GATE}] note: walking the corpus at the named root "
                  f"({local}); {CORPUS_ENV}={env} is set and NOT followed, "
                  f"because the named root carries a corpus of its own.",
                  file=sys.stderr)
        return local, "repo"
    if env:
        ic_root = Path(env) / "ic"
        if announce:
            # ANNOUNCED, ALWAYS. An index re-derived from a tree other than the
            # one the command line names, in silence, would let a stale index be
            # certified fresh against whatever tree happened to be handy.
            print(f"[{GATE}] note: {CORPUS_ENV} overrides "
                  f"{local} -> {ic_root}", file=sys.stderr)
        return ic_root, "env"
    return local, "repo"


def build(repo_root: Path,
          ic_root: Optional[Path] = None) -> Tuple[str, List[str]]:
    """(rendered index, findings). Findings are non-render problems."""
    if ic_root is None:
        ic_root, _ = resolve_ic_root(repo_root)
    if not ic_root.is_dir():
        raise SystemExit(f"[{GATE}] no such directory: {ic_root}")
    tracked = _published_tree.published_paths(ic_root)
    cells = discover_cells(ic_root, tracked)
    rows = [measure_cell(ic_root, tracked, c) for c in cells]
    retention, notes = load_retention(ic_root)

    findings = []
    known = {r["cell"] for r in rows}
    for k in sorted(retention):
        if k not in known:
            findings.append(
                f"{RETENTION_NAME} records a reason for `{k}`, which is not a "
                f"published cell. A retention note that outlives its cell is "
                f"the stale-citation shape this index exists to prevent.")
    return render(rows, retention, notes), findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate/verify benchmark-data/ic/INDEX.md — which "
                    "published cells converged and which are a retained "
                    "failure record.")
    ap.add_argument("--root", default=None,
                    help="repo root (default: infer from this file). "
                         f"${CORPUS_ENV} OVERRIDES the corpus this resolves to, "
                         "because the published corpus now lives in its own "
                         "repository; the override is announced.")
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="the caller asserts this repo need not carry the corpus. "
                         "Turns 'no corpus discoverable anywhere' from UNDETERMINED "
                         "(rc=2) into NO_CORPUS (rc=0), which generates and compares "
                         "NOTHING and says so. It does NOT excuse a corpus pointer "
                         f"that is set and broken: ${CORPUS_ENV} naming a tree with "
                         "no readable ic/ is UNDETERMINED with or without this.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true",
                   help="regenerate the index in place")
    g.add_argument("--check", action="store_true",
                   help="verify the committed index matches the tree (default)")
    args = ap.parse_args(argv)

    repo_root = (Path(args.root).resolve() if args.root
                 else Path(__file__).resolve().parents[4])
    ic_root, origin = resolve_ic_root(repo_root, announce=True)
    index_path = ic_root / INDEX_NAME

    if not ic_root.is_dir():
        # THREE OUTCOMES, AND COLLAPSING ANY TWO OF THEM IS THE DEFECT.
        # Before this branch all three were the one line "no such directory",
        # exiting 1 — the code this program uses for "the index disagrees with
        # the artefacts", which was a finding against an index that was fine.
        if origin == "env":
            print(f"[{GATE}] UNDETERMINED: {CORPUS_ENV}="
                  f"{os.environ.get(CORPUS_ENV)} is set and has no readable "
                  f"{ic_root}, so this gate walked no corpus and generated no "
                  f"index. A pointer that is set and wrong is a broken "
                  f"configuration, not an absent corpus.", file=sys.stderr)
            return 2
        if args.corpus_may_be_absent:
            print(f"[{GATE}] NO_CORPUS: nothing at {ic_root} and {CORPUS_ENV} "
                  f"is unset. The published corpus lives in its own repository "
                  f"and this repo is not required to carry it. NOTHING WAS "
                  f"SCANNED, no {INDEX_NAME} was generated, and no committed "
                  f"{INDEX_NAME} was compared — point {CORPUS_ENV} at a clone "
                  f"to make this gate check something.", file=sys.stderr)
            return 0
        print(f"[{GATE}] UNDETERMINED: no such directory: {ic_root}, so this "
              f"gate walked no corpus and generated no index. A check that "
              f"could not look has not passed. Point {CORPUS_ENV} at a clone "
              f"of the published-corpus repository, or pass "
              f"--corpus-may-be-absent if this repo is not required to carry "
              f"one.", file=sys.stderr)
        return 2

    want, findings = build(repo_root, ic_root)

    # The index can now live OUTSIDE this repository (a clone named by the
    # pointer), so it is named by a path that is relative when it can be and
    # absolute when it cannot. `Path.relative_to` raises on the env case, and a
    # traceback where a verdict belongs is not a verdict.
    try:
        shown = index_path.relative_to(repo_root)
    except ValueError:
        shown = index_path

    if args.write:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(want, encoding="utf-8")
        print(f"[{GATE}] wrote {shown}")
        for f in findings:
            print(f"  [FINDING] {f}")
        return 1 if findings else 0

    if not index_path.is_file():
        print(f"[{GATE}] FAIL: {shown} does not "
              f"exist. The tree publishes cells whose verdicts a reader cannot "
              f"see. Run with --write.")
        return 1

    have = index_path.read_text(encoding="utf-8", errors="replace")
    if have == want and not findings:
        n = have.count("\n| `")
        print(f"[{GATE}] PASS: {shown} matches the "
              f"tree ({n} cell row(s)).")
        return 0

    print(f"[{GATE}] FAIL: {shown} disagrees with "
          f"the artefacts it describes.")
    for f in findings:
        print(f"  [FINDING] {f}")
    if have != want:
        print("  The index is stale — a cell's measured state changed and its "
              "row did not (or a cell was added/removed). Diff "
              "(committed -> tree):")
        diff = difflib.unified_diff(
            have.splitlines(), want.splitlines(),
            fromfile="INDEX.md (committed)", tofile="INDEX.md (from the tree)",
            lineterm="", n=1)
        for i, line in enumerate(diff):
            if i >= 60:
                print("    … (truncated)")
                break
            print("    " + line)
        # NAME THE REPOSITORY THE RESULT LANDS IN (measured 2026-08-21).
        #
        # "commit the result" was written when the index lived here. It now can
        # live in the corpus clone, and this gate is run from vibe-ic — so a
        # reader who follows the remedy commits in the wrong repository, finds
        # nothing to commit, and is left with a red gate and a correct tree.
        # The code twelve lines up already knows the index can be outside; only
        # the remedy had not been told.
        #
        # A printed remedy is executed, not read. One that names the wrong place
        # is the same defect as one that does not run.
        try:
            # RESOLVE BEFORE COMPARING. `relative_to` is LEXICAL, and `ic_root`
            # comes from $VIBE_IC_BENCHMARK_DATA unresolved (:556), so a value
            # carrying `..` — or a symlink — makes this predicate answer about
            # the spelling instead of the file. MEASURED: an index at
            # `<repo>/../../benchmark-data/ic/INDEX.md` is OUTSIDE the repo and
            # the lexical test called it "this repository", printing exactly the
            # wrong-repository remedy this block was added to prevent. The fix
            # had the defect it fixes.
            index_path.resolve().relative_to(repo_root)
            where = "this repository"
        except ValueError:
            where = ("the corpus clone that owns it — NOT this repository, "
                     "which does not track that file")
        print(f"  Fix: re-run with --write, then commit {shown} in {where}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
