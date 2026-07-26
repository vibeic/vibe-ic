#!/usr/bin/env python3
"""benchmark_evidence_publish.py — stage a CONVERGED (IC × PDK) run's evidence
into the canonical benchmark-data layout (the PUBLISH half of the program-first
publish contract).

WHY THIS EXISTS (owner directive 2026-07-25)
============================================
"The way we publish a CONVERGED (IC × PDK) result's evidence into
benchmark-data/ic/ must become a PROGRAM in the plugin (program-first), so
EVERY future push to benchmark-data/ic/<IC>/ automatically follows the same
structure — never again a lone RESULT.md or a messy folder."

This program takes a completed run directory + the IC / PDK / plugin-version and
STAGES exactly the canonical structure into
`benchmark-data/ic/<IC>/v<version>_<PDK>/`, copying the right evidence, EXCLUDING
the large gitignored files (*.gds/*.def/*.spef/*.oas), generating the
GDS_MANIFEST (sha256 + byte size), and REFUSING to publish a run that is NOT
converged. Its companion `benchmark_evidence_structure_check.py` validates the
result (and this program runs it as a post-stage self-check).

  It STAGES ONLY — it never `git add` / `git commit` / `git push`. Publishing to
  the repo stays a deliberate human/agent act. The program prints the exact
  `git add` command; a person commits it.

THE CANONICAL STRUCTURE it produces
===================================
    benchmark-data/ic/<IC>/v<version>_<PDK>/
        RESULT.md                           independent-audit verdict (required)
        provenance.jsonl                    (copied if present)
        phase1/…                            L* generated_docs + input_doc + json
        phase2/…                            RTL + synth + constraints
        phase3/reports/…                    DRC/STA rpt (if present)
        phase3/stage4/gds/GDS_MANIFEST.txt  <name> <bytes>B sha256:<hash>
        reports/…                           reports/phase3 + audit + orchestrator…
    benchmark-data/ic/<IC>/input/           shared design input (staged once)

LAYOUT ARTEFACTS ARE ROUTED BY SIZE, NOT BY EXTENSION (#419). Within the
PUBLISHED SCOPE — the copied subtrees listed above plus the signoff GDS —
*.gds, *.def, *.spef and *.oas under the ceiling are STAGED; above it the
blob is not copied and the routing decision is RECORDED so the omission is
legible. Size does NOT widen that scope: an artefact in a subtree this
program does not publish stays unpublished however small it is, and is
recorded as such rather than passed over in silence.

  This paragraph used to declare these four extensions excluded as a matter
  of construction, on the grounds that they were gitignored or too large, and
  both halves had stopped being true. `.gitignore` negates
  `.gds`/`.def` back for `benchmark-data/ic/**`, and `.spef`/`.oas` were never
  ignored at all. "Too large" is a property of the FILE: this project's own
  GDS range from 0.73 MB (spm) to 105 MB (sha256). Dropping by extension threw
  away the small artefact a reviewer wants in order to avoid the large one
  nobody can commit — so a cell published by this program carried LESS
  evidence than the hand-staged cells it replaced.

  THE SIGNOFF GDS IS PART OF THAT POPULATION, and until this change it was
  not. v1.6.61 replaced the extension test with a size test, but the size
  test only ever saw files inside the copied subtrees (phase1, phase2,
  phase3/reports, reports) — and the signoff GDS lives in
  `phase3/stage4/gds/`, which is not one of them. So a 0.8 MB GDS, three
  orders of magnitude under the ceiling and explicitly accepted by
  `.gitignore`, was still dropped: measured on a synthetic run at v1.6.61,
  the published cell contained ZERO layout artefacts and the program
  reported "excluded raw: 0", because the file it silently omitted was never
  offered to the predicate. The GDS the manifest is ABOUT is now staged when
  it fits, which is what makes the reference cells' shape reproducible by
  program rather than by hand.

EVERY LAYOUT ARTEFACT LEAVES A RECORD — `LAYOUT_ROUTING.txt` at the cell root,
one line per layout artefact found under the source run directory:

    <relpath> <bytes>B sha256:<64hex> <DECISION> <destination>
    DECISION ∈ STAGED | ROUTED_AWAY | NOT_PUBLISHED

A reader can therefore distinguish "big, stored elsewhere, here is its hash"
from "in the run but out of published scope" from "never existed" — three
states the count on stdout collapsed into one, because stdout is not part of
the deliverable. `--oversize-route` names the destination for the routed-away
ones; it defaults to `not-retained`, which is the honest answer when nobody
has said otherwise. A cell that records "not-retained" is a better deliverable
than one that quietly looks whole.

Raw PnR scratch under phase3/stage3 and the per-step scratch (steps/) are
still not staged: that is a decision about what counts as evidence, which is
separate from how big a file is. NOTE that the three hand-staged reference
cells DO carry `phase3/stage3/pnr/routed.def` and `phase3/stage3/extracted/
*.spef`, so on that subtree this program still publishes less than they do.
Widening it is an evidence-policy call, not a size call, and is deliberately
left alone here.

THE CONVERGENCE GUARD (anti-fabrication)
========================================
Only a run whose machine verdict is PASS or PASS_WITH_WAIVERS is publishable.
The verdict is read from the run's own
`reports/audit/phase23_completion_audit.json` (`flow_compliance_check.py`'s
canonical machine artifact). No audit artifact, a FAIL verdict, a missing/FAIL
RESULT.md, or no streamed GDS -> the program REFUSES and stages nothing. A
failing run can never be staged as if it passed.

chip-AGNOSTIC: the IC, PDK and version are parameters; NO IC / PDK / vendor /
SKU literal appears in this program's logic.

USAGE
=====
    python3 benchmark_evidence_publish.py \
        --run-dir /path/to/completed_run \
        --ic <IC> --pdk <PDK> --plugin-version 1.5.66 \
        --dest-root benchmark-data \
        [--result-md RESULT.md] [--input-docs docs/] [--gds streamed.gds] \
        [--force] [--dry-run] [--json out.json]

EXIT CODES
==========
    0  staged (or, with --dry-run, would stage) a conformant evidence folder
    1  REFUSED — not converged / missing required input / nonconformant result
    2  usage / I/O error
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess

import _published_tree
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# The layout artefacts. These used to be dropped from every copied subtree by
# EXTENSION, on the stated grounds that they were "gitignored / too large".
# Neither half is true any more (#419):
#
#   * `.gds` / `.def` are ignored at the repo root AND negated back for
#     `benchmark-data/ic/**` — git accepts them. `.spef` / `.oas` were never
#     ignored at all, so the spm cells' .spef files needed no force-add.
#   * "too large" is a property of the FILE, not of its extension. Measured
#     spread across this project's own GDS: 0.73 MB (spm) to 105 MB (sha256),
#     three orders of magnitude. The extension rule threw away the 0.8 MB
#     artefact a reviewer wants in order to avoid the 105 MB one nobody can
#     commit, and a cell published TODAY therefore carried less evidence than
#     the hand-staged cells this program replaced.
#
# So they are ROUTED BY SIZE, and either way the manifest records the sha256,
# which is what makes an artefact verifiable whether or not it is stored.
_LAYOUT_EXTS = (".gds", ".def", ".spef", ".oas")

# Must match `tracked_blob_size_guard._CEILING`, which is the gate that
# actually blocks the commit. `_size_policy_drift_check` below fails if these
# two, `.gitignore`, and this module's docstring ever stop agreeing.
_SIZE_CEILING = 50 * 1000 * 1000
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CONVERGED = ("PASS", "PASS_WITH_WAIVERS")

# Evidence subtrees copied verbatim (minus excluded extensions). Order = the
# canonical committed shape of the reference cells; NOT phase3/stage3 (raw PnR),
# NOT steps/ (per-step scratch), NOT sim/ (empty in the reference).
_COPY_SUBTREES = (
    "phase1",
    "phase2",
    Path("phase3") / "reports",
    "reports",
)
_COPY_FILES = ("provenance.jsonl",)


class Refuse(Exception):
    """A guard tripped; publish must not proceed."""


# --------------------------------------------------------------------------
# Verdict helpers.
# --------------------------------------------------------------------------

def _audit_verdict(run_dir: Path, verdict_json: Optional[Path]) -> Tuple[str, Path]:
    """Return (verdict, source_path) from the run's flow-compliance audit JSON."""
    cand = verdict_json or (run_dir / "reports" / "audit" / "phase23_completion_audit.json")
    if not cand.is_file():
        raise Refuse(
            f"convergence unverifiable: no audit verdict at {cand} "
            f"(run flow_compliance_check.py --strict first, or pass --verdict-json)")
    try:
        data = json.loads(cand.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        raise Refuse(f"cannot parse audit verdict {cand}: {exc}")
    verdict = str(data.get("verdict", "")).upper().replace("-", "_")
    if not verdict:
        raise Refuse(f"audit verdict at {cand} has no 'verdict' field")
    return verdict, cand


def _result_md_verdict(result_md: Path) -> Optional[str]:
    """Best-effort verdict token from a RESULT.md's VERDICT section."""
    try:
        upper = result_md.read_text(encoding="utf-8", errors="replace").upper()
    except Exception:
        return None
    m = re.search(r"^#{1,6}\s*VERDICT\b", upper, re.MULTILINE)
    region = upper
    if m:
        start = m.end()
        nxt = re.search(r"^#{1,6}\s", upper[start:], re.MULTILINE)
        region = upper[start:start + nxt.start()] if nxt else upper[start:]
    for tok in ("PASS_WITH_WAIVERS", "PASS", "FAIL"):
        for tm in re.finditer(r"\b" + re.escape(tok) + r"\b", region):
            if tok == "PASS" and region[tm.start():tm.start() + 17] == "PASS_WITH_WAIVERS":
                continue
            return tok
    return None


# --------------------------------------------------------------------------
# Copy helpers.
# --------------------------------------------------------------------------

def is_layout_artefact(p: Path) -> bool:
    """True for the four extensions whose routing this program decides."""
    return p.suffix.lower() in _LAYOUT_EXTS


def over_ceiling(p: Path, ceiling: int = _SIZE_CEILING) -> bool:
    """True when `p` is too big to commit.

    Named and exported on purpose: `size_policy_drift_check` CALLS this to
    confirm the decision follows the declared ceiling. A checker that only
    greps for the constant proves the policy is spelled, not that it is
    obeyed — and a mutant that reverts to an extension rule while leaving the
    constant in place passed exactly such a grep.
    """
    try:
        return p.stat().st_size > ceiling
    except OSError:
        # Unreadable size is not evidence of smallness. Route it away and let
        # the record carry what is known, rather than copying blind.
        return True


def _excluded(p: Path) -> bool:
    """A layout artefact is excluded only when it is TOO BIG to commit.

    #419. The predicate used to be `suffix in _RAW_EXTS` — an extension test
    standing in for a size test. Everything else is copied as before; a
    layout artefact under the ceiling now ships, and one over it is skipped
    for the reason that is actually true of it.
    """
    return is_layout_artefact(p) and over_ceiling(p)


def _record(p: Path, rel_base: Path, decision: str,
            route: str, sha: Optional[str] = None) -> dict:
    """One line's worth of routing evidence for a single layout artefact.

    `path` is always relative to the RUN directory — one frame of reference
    for all three decisions, so the lines can be compared with each other.
    For an artefact staged into the CELL it is also the path inside the cell,
    because the copied subtrees keep their run-relative layout. That does NOT
    hold for the shared design input, which is staged to `ic/<IC>/input/`;
    its `destination` column says `shared-input` precisely because the path
    column cannot be read as a cell path there.
    """
    try:
        size = p.stat().st_size
    except OSError:
        size = -1
    try:
        rel = p.resolve().relative_to(rel_base).as_posix()
    except ValueError:
        rel = p.name
    dest = {"STAGED": "in-cell",
            "ROUTED_AWAY": route,
            "NOT_PUBLISHED": "source-run-only"}[decision]
    return {
        "path": rel,
        "bytes": size,
        "sha256": sha if sha is not None else (_sha256(p) if size >= 0 else ""),
        "decision": decision,
        "destination": dest,
        "src": str(p.resolve()),
    }


def _copy_tree(src: Path, dst: Path, dry: bool,
               rel_base: Optional[Path] = None,
               route: str = "not-retained") -> Tuple[int, List[dict]]:
    """Copy every non-excluded regular file under src into dst (preserving
    relative layout).

    Returns (files_copied, layout_records) — one record per LAYOUT artefact
    seen, whether it was staged or routed away. The routed-away ones used to
    be a bare integer that reached stdout and nothing else; an omission that
    leaves no trace in the deliverable is indistinguishable from an artefact
    that never existed.
    """
    copied = 0
    records: List[dict] = []
    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(src)
        if _excluded(f):
            if rel_base is not None:
                records.append(_record(f, rel_base, "ROUTED_AWAY", route))
            continue
        if is_layout_artefact(f) and rel_base is not None:
            records.append(_record(f, rel_base, "STAGED", route))
        target = dst / rel
        if not dry:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
        copied += 1
    return copied, records


def _inventory_unpublished(run_dir: Path, seen: set, route: str) -> List[dict]:
    """Every layout artefact under the run that the cell does NOT carry and
    that was never offered to the size rule — phase3/stage3 scratch, steps/,
    anything outside the published subtrees.

    Without this the record could not support the claim a reader most needs
    from it. An artefact in neither the cell nor the record would be
    ambiguous between "never existed" and "exists in the run, published
    scope just does not include it" — and those call for opposite actions.
    Recording the sha256 is what turns recovery into a verifiable file copy
    rather than a guess about which of two same-named layouts is the one the
    verdict describes.

    ONE LINE PER UNDERLYING BLOB, not per path that reaches it. Converged runs
    alias their artefacts: this run carries 63 symlinks under `steps/` pointing
    back into `phase3/stage3/`, 8 of them layout artefacts. `rglob` yields the
    symlink and its target as separate entries, and `_record` resolves before
    computing the path column, so both would emit a BYTE-IDENTICAL line. That
    is not extra evidence — it is the same evidence twice, and it inflates the
    counts printed beside it. Dedupe on the resolved path, accumulating as we
    go; `seen` (the caller's staged set) is read, never mutated.
    """
    out = []
    recorded = set(seen)
    for f in sorted(run_dir.rglob("*")):
        if not f.is_file() or not is_layout_artefact(f):
            continue
        real = f.resolve()
        if real in recorded:
            continue
        recorded.add(real)
        out.append(_record(f, run_dir, "NOT_PUBLISHED", route))
    return out


def _find_gds(run_dir: Path, explicit: Optional[Path]) -> List[Path]:
    """Return the streamed GDS file(s) to manifest.

    --gds wins; else every *.gds directly in the canonical streamout dir
    phase3/stage4/gds/ (one manifest line each, matching the reference shape);
    else, as a fallback, the single largest *.gds anywhere under the run.
    """
    if explicit is not None:
        if not explicit.is_file():
            raise Refuse(f"--gds {explicit} not found")
        return [explicit]
    canonical = run_dir / "phase3" / "stage4" / "gds"
    if canonical.is_dir():
        hits = sorted(p for p in canonical.glob("*.gds") if p.is_file())
        if hits:
            return hits
    anywhere = sorted((p for p in run_dir.rglob("*.gds") if p.is_file()),
                      key=lambda p: p.stat().st_size, reverse=True)
    if anywhere:
        return [anywhere[0]]
    raise Refuse(
        "no streamed *.gds found under the run — a converged tapeout must have "
        "a GDS to manifest (pass --gds to point at it)")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_manifest(gds_files: List[Path], dst_gds_dir: Path,
                    dry: bool) -> Tuple[str, List[Tuple[Path, str]]]:
    """Emit GDS_MANIFEST.txt. ALWAYS — whether or not the GDS itself ships.

    Returns (printable summary, [(gds_path, sha256)]) so the caller can stage
    the blobs that fit without hashing them a second time.
    """
    hashed = [(g, _sha256(g)) for g in gds_files]
    lines = [f"{g.name} {g.stat().st_size}B sha256:{sha}" for g, sha in hashed]
    body = "\n".join(lines) + "\n"
    if not dry:
        dst_gds_dir.mkdir(parents=True, exist_ok=True)
        (dst_gds_dir / "GDS_MANIFEST.txt").write_text(body, encoding="utf-8")
    return "; ".join(lines), hashed


_ROUTING_FILENAME = "LAYOUT_ROUTING.txt"
_ROUTE_CHOICES = ("not-retained", "git-lfs", "github-release")

_ROUTING_HEADER = (
    "# LAYOUT_ROUTING — every *.gds/*.def/*.spef/*.oas found under the source\n"
    "# run, and what was decided about each one. Paths are relative to that\n"
    "# run; for anything STAGED it is also the path inside this cell.\n"
    "#\n"
    "#   STAGED        the blob is in this cell.\n"
    "#   ROUTED_AWAY   in published scope but over the commit ceiling. The\n"
    "#                 destination column says where it went; 'not-retained'\n"
    "#                 means nobody claimed to have kept it.\n"
    "#   NOT_PUBLISHED exists in the source run, in a subtree this cell does\n"
    "#                 not publish (PnR scratch, per-step scratch). Not a\n"
    "#                 size decision — small ones are not published either.\n"
    "#\n"
    "# The sha256 is recorded in all three cases: it is what makes an\n"
    "# artefact verifiable without being stored, and what turns recovering\n"
    "# one from a source host into a checkable file copy rather than a guess.\n"
    "#\n"
    "# SCOPE, stated so it is not over-read: this is every layout artefact\n"
    "# found under the SOURCE RUN DIRECTORY at publish time. It cannot speak\n"
    "# for artefacts the run never wrote there, and it is a record of what\n"
    "# was decided — not a promise that a ROUTED_AWAY blob still exists\n"
    "# wherever the destination column says it went.\n"
    "#\n"
    "# ONE LINE PER BLOB, not per path: converged runs symlink their artefacts\n"
    "# (steps/<step>/routed.def -> phase3/stage3/pnr/routed.def). Aliases are\n"
    "# collapsed onto the resolved path, so a line count here is a count of\n"
    "# distinct artefacts, not of directory entries.\n"
    "# <relpath> <bytes>B sha256:<64hex> <DECISION> <destination>\n"
)


def _write_routing(records: List[dict], dest: Path, dry: bool) -> None:
    """Write the per-cell routing record. Emitted even when nothing was routed
    away: a record that only appears on omission cannot be relied on to prove
    that nothing was omitted."""
    body = _ROUTING_HEADER + "".join(
        f"{r['path']} {r['bytes']}B sha256:{r['sha256']} "
        f"{r['decision']} {r['destination']}\n"
        for r in sorted(records, key=lambda r: r["path"]))
    if not dry:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / _ROUTING_FILENAME).write_text(body, encoding="utf-8")


_CITATION_ROUTING_FILENAME = "CITATION_ROUTING.txt"

_CITATION_HEADER = (
    "# CITATION_ROUTING — every path a published JSON CITES as its evidence,\n"
    "# and whether a reader of THIS cell can follow it (vibe-ic#448).\n"
    "#\n"
    "#   <doc> :: <cited path> <DECISION>\n"
    "#   DECISION in RESOLVES | OUT_OF_PUBLISHED_SCOPE |\n"
    "#                DANGLING_UNDER_PASS | DANGLING | UNFOLLOWABLE_ABSOLUTE\n"
    "#\n"
    "# OUT_OF_PUBLISHED_SCOPE is the one that needed a name. The publisher\n"
    "# copies phase1/, phase2/, phase3/reports/ and reports/ — a run-directory\n"
    "# citation such as `phase3/stage3/sta/x.rpt` is therefore correct WHERE\n"
    "# THE RUN PUT IT and unfollowable HERE. Measured on the three converged\n"
    "# cells: each asserts `timing_closed_multi_corner: true` citing\n"
    "# `phase3/stage3/sta/sta_mcorner_ocv.rpt`, which the published layout\n"
    "# never carries. The evidence was not lost; the POINTER was published\n"
    "# unchanged, so a reader following it finds nothing and is told nothing.\n"
    "#\n"
    "# This is the same repair LAYOUT_ROUTING.txt makes for blobs: an artefact\n"
    "# that is out of scope is RECORDED as out of scope rather than vanishing.\n"
    "# It does not decide whether the claim is TRUE — the run may well have\n"
    "# closed timing — only whether this cell lets you check it.\n"
    "#\n"
    "# Emitted even when every citation resolves: a record that only appears\n"
    "# on failure cannot be used to prove there were none.\n")

# Extensions that name an EVIDENCE artefact rather than prose.
_CITE_KEYS = frozenset({
    "report", "rpt", "log", "evidence", "artifact", "artefact",
    "source", "path", "file", "sby", "sby_log",
})

_CITED_EXT = (".rpt", ".log", ".json", ".txt", ".def", ".spef", ".v", ".sv")
_CITED_RE = re.compile(
    r"(?:phase\d/stage\d|phase\d/reports|reports|steps)/[\w./*-]+"
    r"(?:" + "|".join(re.escape(e) for e in _CITED_EXT) + r")")


def collect_citation_records(dest: Path) -> List[Dict[str, str]]:
    """Every evidence path the STAGED tree's own JSONs cite, and whether it
    resolves inside the published cell.

    Read from the STAGED tree, not the run, because the question is what a
    reader of THIS cell can follow.
    """
    out: List[Dict[str, str]] = []
    if not dest.is_dir():
        return out
    seen = set()
    # Walk the PUBLISHED tree, not this machine's disk. At publish time `dest`
    # is a freshly staged directory and the two agree; run as an AUDIT over an
    # already-published cell they do not, and a working checkout carries
    # untracked `clean_run_*` leftovers a reader never receives. Measured while
    # building this: the first version attributed citations to a directory that
    # is not in the published tree at all. Same defect this repo fixed in four
    # programs (#447) — reproduced here, in the fix for it.
    docs = sorted(dest.rglob("*.json"))
    docs = _published_tree.filter_to_published(dest, docs)
    for doc in docs:
        try:
            text = doc.read_text(errors="replace")
        except OSError:
            continue
        rel_doc = doc.relative_to(dest).as_posix()
        asserted = _citations_under_a_pass(text)
        absolute = _absolute_citation_values(text)
        for cited in sorted(set(_CITED_RE.findall(text)) | absolute):
            key = (rel_doc, cited)
            if key in seen:
                continue
            seen.add(key)
            if cited.startswith("/"):
                # UNFOLLOWABLE BY CONSTRUCTION. An absolute path under someone's
                # home directory can never resolve for a reader, on any machine
                # but the author's. That is a different fact from "the file is
                # not here", and reporting them the same way sends a reader
                # looking for a missing artefact instead of fixing a pointer.
                #
                # MEASURED over the tracked corpus: 108 CITATION fields carry
                # one, across 7 ICs — including two of the three CONVERGED
                # cells, whose `post_route_signoff_corner.json` cites
                # `/home/<user>/campaign_.../sta_spef_multicorner.rpt`.
                #
                # Narrow on purpose: a blanket "no absolute paths under
                # benchmark-data" rule matches 682 files and 9781 occurrences,
                # nearly all of them logs recording WHERE a run happened, which
                # is legitimate provenance. Only a path something is expected
                # to FOLLOW is a defect.
                decision = "UNFOLLOWABLE_ABSOLUTE"
            elif (dest / cited).exists():
                decision = "RESOLVES"
            elif any(cited.startswith(f"phase{n}/stage") for n in "123"):
                decision = "OUT_OF_PUBLISHED_SCOPE"
            elif cited in asserted:
                decision = "DANGLING_UNDER_PASS"
            else:
                decision = "DANGLING"
            out.append({"doc": rel_doc, "cited": cited,
                        "decision": decision})
    return out


def _absolute_citation_values(text: str) -> set:
    """Absolute paths sitting in a CITATION-shaped KEY.

    Key-based, not text-based, and the difference is the whole point. Matching
    absolute paths in the TEXT finds 914 of them across the tracked corpus —
    nearly all logs recording WHERE a run happened, which is legitimate
    provenance and not a defect. Restricting to keys something is expected to
    FOLLOW gives 108, across 7 ICs, and those are real: two of the three
    CONVERGED cells cite `/home/<user>/campaign_.../sta_spef_multicorner.rpt`
    as the evidence for their sign-off corner.
    """
    out: set = set()
    try:
        doc = json.loads(text)
    except Exception:
        return out

    def is_cite_key(k: str) -> bool:
        k = k.lower()
        return (k in _CITE_KEYS
                or k.endswith(("_report", "_rpt", "_log", "_path", "_file")))

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and v.startswith("/") and is_cite_key(k):
                    out.add(v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return out


def _citations_under_a_pass(text: str) -> set:
    """Paths cited inside a record whose own status/verdict is a PASS.

    THE PLAN-VERSUS-CLAIM SPLIT, and the reason the routing file is usable.
    A step that has not run naming the report it WOULD write is a PLAN; a step
    that says PASS while naming a report that is not there is a CLAIM whose
    evidence is absent. Both look identical as a path.

    MEASURED over the published corpus: of the dangling citations,
    35 sit in SKIP/not-run records, 24 in FAIL records, 64 in records with no
    status to judge, and **11 under a PASS**. Only that last group asserts
    anything, so only it is anyone's bug — a 45x reduction in what a reader
    has to look at.
    """
    found: set = set()
    try:
        doc = json.loads(text)
    except Exception:
        return found

    def _has_status(o) -> bool:
        return isinstance(o, dict) and bool(o.get("status") or o.get("verdict"))

    def _own_text(o) -> str:
        """This record's own content, EXCLUDING nested status-bearing records.

        A first version serialised the whole subtree, which over-attributed
        badly: a document with a top-level `verdict: PASS` made EVERY citation
        in the file "asserted", including ones inside nested SKIP steps.
        Measured: 312 across the corpus instead of the real figure. A claim is
        made by the NEAREST enclosing record, not by every ancestor.
        """
        if isinstance(o, dict):
            parts = []
            for k, v in o.items():
                if _has_status(v):
                    continue
                if isinstance(v, list):
                    v = [x for x in v if not _has_status(x)]
                parts.append(json.dumps({k: v}, ensure_ascii=False))
            return " ".join(parts)
        return json.dumps(o, ensure_ascii=False)

    def walk(o):
        if isinstance(o, dict):
            st = str(o.get("status") or o.get("verdict") or "").upper()
            if st.startswith("PASS"):
                found.update(_CITED_RE.findall(_own_text(o)))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return found


def write_citation_routing(dest: Path, records: List[Dict[str, str]],
                           dry: bool = False) -> None:
    body = _CITATION_HEADER + "".join(
        f"{r['doc']} :: {r['cited']} {r['decision']}\n"
        for r in sorted(records, key=lambda r: (r["doc"], r["cited"])))
    if not dry:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / _CITATION_ROUTING_FILENAME).write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------
# Publish.
# --------------------------------------------------------------------------

def publish(args: argparse.Namespace) -> dict:
    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        raise Refuse(f"--run-dir {run_dir} is not a directory")

    # --- parameter sanity (structure, not chips) ---
    if not _VERSION_RE.match(args.plugin_version):
        raise Refuse(f"--plugin-version {args.plugin_version!r} is not X.Y.Z")
    for label, val in (("--ic", args.ic), ("--pdk", args.pdk)):
        if not _SAFE_TOKEN_RE.match(val):
            raise Refuse(f"{label} {val!r} is not a safe path token "
                         f"(letters/digits/._- , no separators/spaces)")

    verdir_name = f"v{args.plugin_version}_{args.pdk}"

    # --- convergence guard ---
    verdict_json = Path(args.verdict_json).resolve() if args.verdict_json else None
    verdict, verdict_src = _audit_verdict(run_dir, verdict_json)
    if verdict not in _CONVERGED:
        raise Refuse(
            f"run verdict is {verdict} (from {verdict_src}); only a converged "
            f"run (PASS / PASS_WITH_WAIVERS) may be published as evidence")

    # --- RESULT.md (independent audit) required + consistent ---
    result_md = Path(args.result_md).resolve() if args.result_md else (run_dir / "RESULT.md")
    if not result_md.is_file() or result_md.stat().st_size == 0:
        raise Refuse(
            f"independent-audit RESULT.md required but missing/empty at {result_md} "
            f"(write the audit verdict first, or pass --result-md)")
    rmd_verdict = _result_md_verdict(result_md)
    if rmd_verdict == "FAIL":
        raise Refuse(f"RESULT.md at {result_md} states verdict FAIL — inconsistent "
                     f"with a converged publish")

    # --- streamed GDS (for the manifest) ---
    gds_files = _find_gds(run_dir, Path(args.gds).resolve() if args.gds else None)

    # --- destination ---
    dest_root = Path(args.dest_root).resolve()
    ic_root = dest_root / "ic" / args.ic
    dest = ic_root / verdir_name
    if dest.exists() and any(dest.iterdir()) and not args.force:
        raise Refuse(f"destination {dest} already exists and is non-empty "
                     f"(pass --force to overwrite)")

    dry = args.dry_run
    staged: List[str] = []
    route = getattr(args, "oversize_route", "not-retained")
    layout_records: List[dict] = []

    if not dry:
        if dest.exists() and args.force:
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)

    # RESULT.md
    if not dry:
        shutil.copy2(result_md, dest / "RESULT.md")
    staged.append("RESULT.md")

    # single files
    for fname in _COPY_FILES:
        src = run_dir / fname
        if src.is_file():
            if not dry:
                shutil.copy2(src, dest / fname)
            staged.append(fname)

    # subtrees
    for sub in _COPY_SUBTREES:
        src = run_dir / sub
        if not src.is_dir():
            continue
        c, recs = _copy_tree(src, dest / sub, dry, rel_base=run_dir, route=route)
        layout_records.extend(recs)
        if c:
            staged.append(f"{sub}/ ({c} files)")

    # GDS_MANIFEST — always, whether or not the GDS itself fits.
    gds_dir = dest / "phase3" / "stage4" / "gds"
    manifest_line, hashed = _write_manifest(gds_files, gds_dir, dry)
    staged.append("phase3/stage4/gds/GDS_MANIFEST.txt")

    # The signoff GDS itself. `phase3/stage4` is not a copy subtree, so until
    # this existed the GDS was omitted at EVERY size — the size routing could
    # not reach the one artefact the manifest is actually about.
    for g, sha in hashed:
        if over_ceiling(g):
            layout_records.append(
                _record(g, run_dir, "ROUTED_AWAY", route, sha=sha))
            continue
        if not dry:
            gds_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(g, gds_dir / g.name)
        layout_records.append(_record(g, run_dir, "STAGED", route, sha=sha))
        staged.append(f"phase3/stage4/gds/{g.name}")

    # shared design input (staged once per IC). BEFORE the routing record is
    # written: these files can live under the run too, and one recorded as
    # NOT_PUBLISHED after having been staged would be a false entry in the
    # one file whose whole value is that it can be trusted.
    shared_input = ic_root / "input"
    input_result, input_recs = _stage_shared_input(run_dir, args, shared_input,
                                                   dry, route)
    layout_records.extend(input_recs)

    # Complete the inventory: layout artefacts the published scope excludes.
    seen = {Path(r["src"]) for r in layout_records}
    layout_records.extend(_inventory_unpublished(run_dir, seen, route))

    # The routing record — emitted even when nothing was routed away.
    _write_routing(layout_records, dest, dry)
    # Same treatment for CITED artefacts as for blobs (#448): a citation the
    # published layout cannot carry is RECORDED as out of scope rather than
    # left to dangle. Read from the STAGED tree, so it answers the reader's
    # question — "can I follow this from what I received?" — not the run's.
    citation_records = collect_citation_records(dest)
    write_citation_routing(dest, citation_records, dry)
    staged.append(_ROUTING_FILENAME)
    staged.append(_CITATION_ROUTING_FILENAME)
    excluded_total = sum(1 for r in layout_records if r["decision"] == "ROUTED_AWAY")

    summary = {
        "ic": args.ic,
        "pdk": args.pdk,
        "plugin_version": args.plugin_version,
        "verdict": verdict,
        "verdict_source": str(verdict_src),
        "result_md_verdict": rmd_verdict,
        "dest": str(dest),
        "gds_manifest": manifest_line,
        "gds_source": [str(g) for g in gds_files],
        "staged": staged,
        "excluded_raw_files": excluded_total,
        "layout_routing": layout_records,
        "oversize_route": route,
        "shared_input": input_result,
        "dry_run": dry,
    }

    # --- post-stage self-check (structure conformance) ---
    if not dry:
        ok, detail = _self_check(dest)
        summary["self_check"] = detail
        if not ok:
            raise Refuse(
                f"post-stage self-check FAILED — the staged folder is NOT "
                f"conformant:\n{detail}")

    return summary


def _stage_shared_input(run_dir: Path, args: argparse.Namespace,
                        shared_input: Path, dry: bool,
                        route: str = "not-retained") -> Tuple[str, List[dict]]:
    """Copy the design-input docs to ic/<IC>/input/ once. Non-fatal: on a 2nd/3rd
    PDK for the same IC the shared input already exists and is left untouched.

    Returns (message, layout_records). Design docs are not normally layout
    artefacts, but the input dir usually sits UNDER the run — so anything the
    inventory would otherwise sweep up as NOT_PUBLISHED has to be accounted
    for here first, or the record would contradict itself.
    """
    if shared_input.is_dir() and any(shared_input.iterdir()) and not args.force:
        return f"kept existing {shared_input}", []
    src: Optional[Path] = None
    if args.input_docs:
        src = Path(args.input_docs).resolve()
        if not src.is_dir():
            raise Refuse(f"--input-docs {src} is not a directory")
    else:
        for cand in (run_dir / "input" / "docs",
                     run_dir / "input",
                     run_dir / "phase1" / "input_doc"):
            if cand.is_dir() and any(p.is_file() for p in cand.rglob("*")):
                src = cand
                break
    if src is None:
        return "no design-input docs found to stage (shared input unchanged)", []
    dst = shared_input / "docs"
    c, recs = _copy_tree(src, dst, dry, rel_base=run_dir, route=route)
    for r in recs:
        if r["decision"] == "STAGED":
            r["destination"] = "shared-input"
    return f"staged {c} input doc(s) -> {dst}", recs


def _self_check(dest: Path) -> Tuple[bool, str]:
    """Run the companion structure checker on the freshly staged folder."""
    checker = Path(__file__).resolve().parent / "benchmark_evidence_structure_check.py"
    if not checker.is_file():
        return True, f"structure checker not found at {checker}; skipped self-check"
    out = subprocess.run(
        [sys.executable, str(checker), str(dest)],
        capture_output=True, text=True, check=False)
    return out.returncode == 0, (out.stdout + out.stderr).strip()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Stage a converged (IC × PDK) run's evidence into the "
                    "canonical benchmark-data layout (stages only; never commits).")
    ap.add_argument("--run-dir", required=True, help="completed run directory")
    ap.add_argument("--ic", required=True, help="IC name (a parameter)")
    ap.add_argument("--pdk", required=True, help="PDK tag (a parameter)")
    ap.add_argument("--plugin-version", required=True, help="plugin version X.Y.Z")
    ap.add_argument("--dest-root", default="benchmark-data",
                    help="root under which ic/<IC>/... is staged (default: benchmark-data)")
    ap.add_argument("--result-md", default=None,
                    help="independent-audit RESULT.md (default: <run-dir>/RESULT.md)")
    ap.add_argument("--input-docs", default=None,
                    help="design-input docs dir -> ic/<IC>/input/docs/ (default: auto)")
    ap.add_argument("--gds", default=None,
                    help="explicit streamed .gds for the manifest (default: auto-find)")
    ap.add_argument("--verdict-json", default=None,
                    help="phase23_completion_audit.json "
                         "(default: <run-dir>/reports/audit/phase23_completion_audit.json)")
    ap.add_argument("--oversize-route", default="not-retained",
                    choices=list(_ROUTE_CHOICES),
                    help="where a layout artefact over the commit ceiling went. "
                         "Recorded per-artefact in LAYOUT_ROUTING.txt. Default "
                         "'not-retained' — the honest answer when nobody has "
                         "said otherwise; naming git-lfs / github-release is a "
                         "claim the operator is making.")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing destination / shared input")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + guard but write nothing")
    ap.add_argument("--json", default=None, help="write a machine-readable summary here")
    args = ap.parse_args(argv)

    try:
        summary = publish(args)
    except Refuse as r:
        print(f"REFUSED: {r}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    verb = "WOULD STAGE" if summary["dry_run"] else "STAGED"
    print(f"[{verb}] {summary['ic']} × {summary['pdk']}  ->  {summary['dest']}")
    print(f"  verdict     : {summary['verdict']} (source: {summary['verdict_source']})")
    print(f"  GDS_MANIFEST: {summary['gds_manifest']}")
    recs = summary["layout_routing"]
    kept = [r for r in recs if r["decision"] == "STAGED"]
    away = [r for r in recs if r["decision"] == "ROUTED_AWAY"]
    unpub = [r for r in recs if r["decision"] == "NOT_PUBLISHED"]
    print(f"  layout      : {len(kept)} staged, {len(away)} routed away "
          f"(-> {summary['oversize_route']}), {len(unpub)} not published, of "
          f"{len(recs)} artefact(s) — all recorded in {_ROUTING_FILENAME}")
    for r in away:
        print(f"      ROUTED_AWAY {r['bytes'] / 1e6:.1f} MB  {r['path']} "
              f"-> {r['destination']}  sha256:{r['sha256'][:12]}…")
    print(f"  shared input: {summary['shared_input']}")
    for s in summary["staged"]:
        print(f"    + {s}")
    if not summary["dry_run"]:
        print(f"  self-check  : PASS")
        print(f"\nNOT COMMITTED. To land this evidence, review then:")
        print(f"    git add {summary['dest']} "
              f"{Path(summary['dest']).parent / 'input'}")
        print(f"    git commit  # (a deliberate act — this program never commits)")

    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
