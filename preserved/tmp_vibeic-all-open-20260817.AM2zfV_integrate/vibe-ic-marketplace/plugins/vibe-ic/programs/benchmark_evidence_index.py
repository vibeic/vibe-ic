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

chip-AGNOSTIC: no IC, PDK, vendor or SKU literal appears in this program. Cells
are discovered by walking the published tree; their identity lives only in the
generated Markdown and the curated sidecar, both under `benchmark-data/`.

Exit: 0 = PASS, 1 = FAIL (drift, or a curated entry naming no cell).
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _published_tree  # noqa: E402  (the ONE tracked-ness resolver — never re-implement)

GATE = "benchmark_evidence_index"

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
        "(`benchmark-data/PUBLISHING.md`: the verdict lives in `RESULT.md`, "
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

    for s in SECTIONS:
        sec = by_section[s]
        out.append(f"## {s} — {len(sec)}")
        out.append("")
        out.append(_SECTION_BLURB[s])
        out.append("")
        if not sec:
            out.append("_none._")
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

def build(repo_root: Path, data_root: Optional[Path] = None) -> Tuple[str, List[str]]:
    """(rendered index, findings). Findings are non-render problems.

    ``repo_root`` retains the historical in-tree layout.  ``data_root`` is the
    top level of the canonical external ``vibeic/benchmark-data`` checkout,
    where the same tree is tracked as ``ic/`` rather than
    ``benchmark-data/ic/``.  The two forms select the same published cells;
    callers must choose one explicitly so an absent in-tree corpus cannot be
    mistaken for an empty external one.
    """
    ic_root = ((data_root / "ic") if data_root is not None
               else (repo_root / IC_SUBDIR))
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
                    help="repo root (default: infer from this file)")
    ap.add_argument(
        "--data-root", default=None,
        help=("top level of the external vibeic/benchmark-data checkout; "
              "mutually exclusive with --root and reads ic/INDEX.md"))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true",
                   help="regenerate the index in place")
    g.add_argument("--check", action="store_true",
                   help="verify the committed index matches the tree (default)")
    args = ap.parse_args(argv)

    if args.root and args.data_root:
        ap.error("--root and --data-root are mutually exclusive")
    repo_root = (Path(args.root).resolve() if args.root
                 else Path(__file__).resolve().parents[4])
    data_root = Path(args.data_root).resolve() if args.data_root else None
    index_path = ((data_root / "ic") if data_root is not None
                  else (repo_root / IC_SUBDIR)) / INDEX_NAME

    want, findings = build(repo_root, data_root)

    if args.write:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(want, encoding="utf-8")
        display_root = data_root if data_root is not None else repo_root
        print(f"[{GATE}] wrote {index_path.relative_to(display_root)}")
        for f in findings:
            print(f"  [FINDING] {f}")
        return 1 if findings else 0

    if not index_path.is_file():
        display_root = data_root if data_root is not None else repo_root
        print(f"[{GATE}] FAIL: {index_path.relative_to(display_root)} does not "
              f"exist. The tree publishes cells whose verdicts a reader cannot "
              f"see. Run with --write.")
        return 1

    have = index_path.read_text(encoding="utf-8", errors="replace")
    if have == want and not findings:
        n = have.count("\n| `")
        display_root = data_root if data_root is not None else repo_root
        print(f"[{GATE}] PASS: {index_path.relative_to(display_root)} matches the "
              f"tree ({n} cell row(s)).")
        return 0

    display_root = data_root if data_root is not None else repo_root
    print(f"[{GATE}] FAIL: {index_path.relative_to(display_root)} disagrees with "
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
        print("  Fix: re-run with --write and commit the result.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
