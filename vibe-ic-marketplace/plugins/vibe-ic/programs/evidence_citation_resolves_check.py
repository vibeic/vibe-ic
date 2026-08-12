#!/usr/bin/env python3
"""evidence_citation_resolves_check.py — a cited evidence artifact must EXIST.

THIS GATE BLOCKS (rc=1) on any NEW dangling citation.

WHY THIS GATE EXISTS
--------------------
An evidence document that says "see `foo.log`" and ships no `foo.log` is
unverifiable, and the failure is SILENT: the sentence reads exactly the same
whether the artifact is there or not. Nothing in the flow ever opened the
file, so nothing ever noticed.

MEASURED (#361, 2026-07-26). Over ALL of `benchmark-data/`, counting `.log`
only: 39 cited, 27 unresolvable against ANY base — 69%. Over this gate's own
DEFAULT SCOPE (`benchmark-data/ic`, `.log` + `.rpt`): 110 cited, 65
unresolvable. The root cause is not author carelessness: `.gitignore` ignores
`*.log` repo-wide, so committing a proof log requires `git add -f` and the
22 logs that ARE tracked all got in that way. The structural hole and the
absent gate together made "claims a proof, ships no artifact" the default
outcome rather than a mistake — it was found by hitting it twice in one
review (a PR fixing exactly that defect reproduced it one level down).

WHAT IT CHECKS
--------------
Every backticked citation in a Markdown file whose token looks like an
artifact filename with an evidence-bearing extension must RESOLVE to a file
on disk. Resolution walks a ladder of bases — the citing document's own
directory, then each ancestor up to the scan root — because citations in
this tree are written relative to either the document or the IC root.

    MEASUREMENT NOTE, stated because getting it wrong is the same class of
    error this gate exists to catch: a single-base resolver (document
    directory only) reports 35 unresolvable instead of 27. It counts every
    IC-root-relative citation as dangling. The ladder is not a convenience;
    without it the gate would fabricate findings.

BASELINE, AND WHY IT MAY ONLY SHRINK
------------------------------------
65 dangling citations already exist in the default scope. Failing the tree
on all of them would
make the gate un-landable and it would be disabled, which is how a gate ends
up reporting FAIL while blocking nothing. So the known set is recorded in a
baseline file and this gate FAILs on:

  * any citation NOT in the baseline that does not resolve — a NEW hole; and
  * a baseline that has GROWN, or that lists entries which now resolve —
    both mean the baseline was edited to accommodate a regression instead of
    the regression being fixed. The baseline is a debt register, not a
    waiver list: it may only shrink.

Regenerate it deliberately with `--write-baseline` (and only ever to a
SMALLER set — the gate re-checks that on the next run).

chip-AGNOSTIC: pure Markdown/filesystem structure. No design, PDK, vendor or
value literal appears here.

USAGE
-----
    python3 evidence_citation_resolves_check.py [ROOT] [--json OUT]
                                                [--write-baseline]

EXIT CODES
----------
    0 = PASS (every citation resolves, or the unresolved set is within a
        baseline that has not grown)
    1 = FAIL (a new dangling citation, or the baseline grew / went stale)
    2 = SKIP (no scan root — nothing to check)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Extensions that carry sign-off EVIDENCE. Deliberately narrow: this gate
# judges "the proof you pointed at is missing", not "every path in prose".
_EVIDENCE_EXT = (".log", ".rpt", ".sby")

# DOCUMENTS a reader is sent to (vibe-ic#1044, second half). A sign-off document
# that says "see `u_hawaii_adc/RESULT.md`" and ships no such file is exactly as
# unverifiable as one pointing at a missing log — and #1044's own consequence
# line is about these, not about logs: the four artefacts #1028 deletes that
# `METHODOLOGY.md` cites are `.md` files.
#
# THE DIRECTORY COMPONENT IS THE DISCRIMINATOR, and it is what keeps this from
# manufacturing findings. Measured over the default scope, unresolved `.md`
# citations split cleanly in two:
#
#     56  BARE filename       `RESULT.md`, `SOURCE_MANIFEST.md`
#     52  carries a directory `u_hawaii_adc/RESULT.md`, `spm/RESULT.md`
#
# A bare `RESULT.md` names a KIND of document — every run has one, and the
# sentence "each run ships a RESULT.md" claims no particular file exists.
# `u_hawaii_adc/RESULT.md` names ONE. Judging the first class would fire on
# 56 legitimately-complete documents, which is a bug in the gate rather than a
# finding; judging the second catches every citation #1044 names.
#
# Same shape of rule as the comma-in-a-brace-group one above: the notation the
# author used says which of the two they meant, and the gate reads it rather
# than guessing.
_DOCUMENT_EXT = (".md",)

# A backticked token that looks like a file path. Anchored so prose in
# backticks (a command line, a sentence) is never mistaken for a citation.
#
# `{`, `}` AND `,` ARE IN THE CLASS ON PURPOSE (vibe-ic#1044). Without them a
# BRACE-EXPANSION citation — `run/{setup,hold}_ss.rpt`, the shell notation this
# corpus writes multi-artifact citations in — does not match this pattern AT
# ALL, so it is not judged, not counted, and not reported. Measured over the
# default scope: 284 such tokens across 36 of 328 documents, expanding to 608
# paths, 12 of which carry an evidence extension and NONE of which resolve.
#
# The failure was invisible from outside by construction, which is what makes
# it this campaign's own shape: the gate ran, produced a verdict, and the
# verdict was green. `benchmark-data/ic/METHODOLOGY.md` is squarely in scope
# and contributed ZERO citations — nothing in the output distinguished "I read
# this document and its citations resolve" from "this document was never in my
# population". See `_zero_citation_docs` below, which is the half of this fix
# that makes the class un-recurrable rather than merely fixed.
_CITE_RE = re.compile(r"`([A-Za-z0-9_./+{},-]+)`")

# Tokens that are TEMPLATES / GLOBS, not citations of a specific artifact.
# Judging these would manufacture findings against text that never claimed a
# particular file exists.
#
# `\{[^}]*\}` STAYS, and the distinction it now draws is the whole fix: a
# brace group WITH A COMMA names several specific artifacts
# (`{setup,hold}.rpt` = two files), while a comma-less one is a placeholder
# (`{run}.log` names none). That is not a judgement call — it is exactly what
# a shell does: `echo {x}.log` prints `{x}.log` unexpanded, `echo {a,b}.log`
# prints two paths. So comma groups are EXPANDED before this pattern runs and
# comma-less ones reach it intact and are rejected as templates, as before.
# Applied AFTER expansion, so a residual `*`, `?`, `<...>` or bare `N` is
# rejected exactly as it always was.
_TEMPLATE_RE = re.compile(r"[*?]|<[^>]*>|\{[^}]*\}|\bN\b")

#: One brace group CONTAINING A COMMA, innermost-first. The comma is the
#: load-bearing part — see `_TEMPLATE_RE`.
_BRACE_RE = re.compile(r"\{([^{}]*,[^{}]*)\}")

#: A citation may not expand without bound. A token with many nested groups is
#: prose, not a citation, and expanding it would let one line of text dominate
#: the denominator. Bounded LOUDLY: over the corpus the largest real expansion
#: is 6, so 64 is ~10x headroom and anything above it is reported, never
#: silently dropped.
_MAX_EXPANSIONS = 64


def expand_braces(tok: str) -> List[str]:
    """`a/{x,y}.rpt` -> `['a/x.rpt', 'a/y.rpt']`; no braces -> `[tok]`.

    Shell brace-expansion semantics, innermost group first, WITHOUT globbing:
    this resolves what the author wrote, it does not consult the filesystem.
    A token whose expansion exceeds `_MAX_EXPANSIONS` returns `[]` and is
    reported by the caller rather than dropped.
    """
    m = _BRACE_RE.search(tok)
    if not m:
        return [tok]
    out: List[str] = []
    for alt in m.group(1).split(","):
        out.extend(expand_braces(tok[:m.start()] + alt.strip() + tok[m.end():]))
        if len(out) > _MAX_EXPANSIONS:
            return []
    return out

# The baseline lives with the DATA it describes, not in plugin source: its
# entries are benchmark-data document paths and therefore carry design names,
# which `source_chip_agnostic_check` (rightly) forbids anywhere under
# `programs/`. The program itself stays chip-AGNOSTIC; only the debt register
# names the designs whose evidence is missing.
_BASELINE_NAME = "evidence_citation_baseline.json"

# DEFAULT SCOPE — the IC sign-off trees, where a document asking a reader to
# believe a result points at the artifact that backs it.
_DEFAULT_ROOT_REL = "benchmark-data/ic"

# OUT OF SCOPE BY DEFAULT, stated here rather than left as a silent narrowing:
# `benchmark-data/evaluation/` holds PER-TASK, machine-generated run outputs
# (one summary document per benchmark item, regenerated wholesale on every
# campaign). Measured 2026-07-26: 14354 documents, 129 citations, 124
# unresolved — i.e. its reports are simply not retained, by design. Gating it
# would fail on every benchmark commit for a reason no author can act on, and
# a gate that must be bypassed to work is a gate that gets deleted. Scan it
# deliberately by passing the path; the count is disclosed on every run so
# nobody can mistake "not scanned" for "clean".
_DISCLOSED_OUT_OF_SCOPE = (
    "benchmark-data/evaluation",
    "per-task generated run outputs; reports not retained by design "
    "(measured 2026-07-26: 124 of 129 citations unresolved)")


def tracked_files(root: Path) -> Optional[set]:
    """The set of git-TRACKED paths under `root`, or None when that cannot be
    determined (not a repo / no git).

    LOAD-BEARING, and learned the hard way: the first version of this gate
    judged plain filesystem existence, so its baseline was computed from a
    working tree that also held UNTRACKED artifacts. It was green locally and
    RED in CI — 12 baseline entries "resolved" (their citing documents are
    untracked, so the citation was never produced) and 9 new dangling
    citations appeared. A gate whose verdict depends on what happens to be
    lying in the author's tree is a false certificate of exactly the kind
    this gate exists to remove.

    The question is "does the REPO ship the proof", not "does this machine
    have it" — so an untracked local artifact must NOT satisfy a citation.
    """
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "-z"],
                           capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out = r.stdout.decode("utf-8", "replace")
    # `-s` gives "<mode> <sha> <stage>\t<path>". Keep REGULAR files only.
    # Mode 120000 is a SYMLINK: its blob is a path string, not document
    # content, and it ships no content at all — 121 of the 122 tracked
    # symlinks under this tree point at ABSOLUTE paths outside the
    # repository, so they resolve on the machine that made them and dangle
    # for everyone else. Reading through them is exactly what made this gate
    # count 440 documents locally and 422 in CI. Judging the index's file
    # MODE keeps the verdict a pure function of the index and never touches
    # the filesystem to decide what exists. Mode 160000 (submodule) is
    # likewise not content.
    names = []
    for ent in out.split("\0"):
        if not ent or "\t" not in ent:
            continue
        meta, path = ent.split("\t", 1)
        if meta.split(" ", 1)[0] in ("100644", "100755"):
            names.append(path)
    if not names:
        return None
    # LOGICAL paths, never `resolve()`. `benchmark-data/ic` carries 787
    # symlinks; resolving follows them to targets that exist on the author's
    # machine and not in a fresh checkout, which is precisely how this gate
    # enumerated 440 documents locally and 422 in CI on the SAME commit. With
    # logical relative paths the verdict is a pure function of the git index
    # and therefore identical in every environment.
    return {n for n in names}



def _resolves_outside_the_scan_root(cite: str, root: Path) -> bool:
    """Does `cite` name a real file that simply lives ABOVE the scan root?

    Structural, and it consults the filesystem rather than a list of directory
    names — a name list would rot the moment a top-level directory is added,
    and this file already argues that case for `_REPO_TOOL_DIRS` elsewhere in
    the repo. Walks up from the root and asks whether the citation resolves
    against any ancestor; if it does, the document is correct and this gate is
    simply not the one that judges it.
    """
    if Path(cite).is_absolute():
        return False              # absolute is non-portable; already never resolvable
    base = root.parent
    for _ in range(4):            # benchmark-data/ic -> benchmark-data -> repo root
        try:
            if (base / cite).is_file():
                return True
        except OSError:
            return False
        if base.parent == base:
            break
        base = base.parent
    return False

def _is_citation(tok: str) -> bool:
    low = tok.lower()
    if low.endswith(_EVIDENCE_EXT):
        pass
    elif low.endswith(_DOCUMENT_EXT) and "/" in tok:
        pass                      # see `_DOCUMENT_EXT`: the directory is the claim
    else:
        return False
    if _TEMPLATE_RE.search(tok):
        return False
    return True


#: A suffix that reads as a real file extension rather than a version number
#: or a sentence's full stop. Bounded on purpose: `.json` yes, `.5` no,
#: `.markdown` yes, `.and-then-some` no.
_EXT_RE = re.compile(r"^\.[A-Za-z0-9]{1,8}$")


def unjudged_dangling_ext(md: Path, tok: str, root: Path,
                          tracked: Optional[set] = None) -> Optional[str]:
    """The extension of `tok` when it is a citation this gate SEES, does NOT
    judge, and which does not resolve. `None` otherwise. vibe-ic#1044.

    THE THIRD LAYER OF #1044, AND THE SAME SHAPE AS THE FIRST TWO.

    The brace fix stopped tokens being invisible to the PATTERN. Judging
    `_DOCUMENT_EXT` citations that carry a directory moved one class from
    unseen to ruled-on. This stops WHAT IS STILL LEFT from being invisible to
    the OUTPUT: a token that matched, expanded, names one specific artifact,
    and points at nothing — but which `_is_citation` rejects, so it leaves
    with a bare `continue`. Not counted, not printed, indistinguishable from a
    token that was judged and cleared. That is the exact indistinguishability
    this issue was filed about, one level in.

    MEASURED on `origin/withdraw/nonpassing-published-runs` (a8e254ad): the
    four artifacts `METHODOLOGY.md` cites are deleted on that branch, the
    brace fix makes all of its expansions VISIBLE, and every one of them is
    `.md` or a directory — so the gate saw eleven dangling references and
    said PASS anyway. `_DOCUMENT_EXT` now judges the four with a directory
    component; the rest are disclosed here.

    THIS DISCLOSES; IT DOES NOT JUDGE. The judged set is exactly
    `_EVIDENCE_EXT` plus directory-bearing `_DOCUMENT_EXT`, both argued at
    their definitions. Widening past that carries a further corpus cost that
    was measured and NOT granted (224 `.json`, 97 `.v`, 69 `.py`, 45 `.gds`
    backticked tokens sit behind that line, plus the 56 BARE `.md` names that
    `_DOCUMENT_EXT` deliberately excludes). Making that call here,
    unilaterally, would be the scope change by the back door. So the count is
    printed and the verdict is untouched: a reader can see the number and
    decide, which they could not do before.

    THE DISCRIMINATOR IS `_is_citation`, NOT A SECOND COPY OF THE EXTENSION
    RULE. Asking the same predicate the gate judges by is what guarantees the
    two populations partition rather than overlap — a token cannot be both
    judged and disclosed as unjudged, and one cannot drift from the other
    when the judged set next changes.
    """
    if _TEMPLATE_RE.search(tok):
        return None                      # a template names no artifact
    ext = Path(tok).suffix
    if not _EXT_RE.match(ext):
        return None                      # not a file reference
    if _is_citation(tok):
        return None                      # judged by the gate proper
    if resolve_citation(md, tok, root, tracked) is not None:
        return None                      # points at something; nothing to say
    return ext.lower()


def resolve_citation(md: Path, cite: str, root: Path,
                     tracked: Optional[set] = None) -> Optional[Path]:
    """Resolve `cite` against the ladder: the citing document's directory,
    then each ancestor up to (and including) `root`. Returns the resolved
    path or None.

    The ladder is load-bearing — see the MEASUREMENT NOTE in the module
    docstring. A document-directory-only resolver reports ~30% more
    findings, all of them false.
    """
    _ = tracked  # membership is tested on logical paths below
    if Path(cite).is_absolute():
        # An absolute path is non-portable by construction: it can only
        # resolve on the machine that wrote it, so it substantiates nothing
        # for any other reader. Never resolvable, regardless of this host.
        return None
    import posixpath
    try:
        rel_dir = md.parent.relative_to(root).as_posix()
    except ValueError:
        return None
    if rel_dir == ".":
        rel_dir = ""
    while True:
        cand_rel = posixpath.normpath(
            posixpath.join(rel_dir, cite) if rel_dir else cite)
        if not cand_rel.startswith(".."):
            if tracked is not None:
                if cand_rel in tracked:
                    return root / cand_rel
            elif (root / cand_rel).is_file():
                return root / cand_rel
        if not rel_dir:
            return None
        rel_dir = posixpath.dirname(rel_dir)


# JSON GATE REPORTS (#366). A report that declares a `verdict` AND names the
# artifact substantiating it is making the same promise a Markdown citation
# makes, in a different container. Measured 2026-07-26 over benchmark-data/ic:
# 788 such reports, 118 artifact references, 75 unresolvable in the TRACKED
# tree — including three spm PDK cells whose `formal_evidence.json` carries
# verdict PASS with "PROOF_CHAIN_OK ... substantiated by an elaboratable .sby
# + SymbiYosys PASS transcript" while no `.sby` and no transcript exist
# anywhere in the repo.
#
# The gate that wrote those reports is NOT at fault: it verifies the paths
# before emitting PASS, and they existed on disk when it ran. The evidence
# then could not be SHIPPED — `*.sby.log` matches `.gitignore`'s repo-wide
# `*.log`, so zero are tracked. A PASS that no reader can re-verify is the
# same false certificate as a fabricated one; only the mechanism differs.
_VERDICT_KEY = "verdict"


def _json_artifact_refs(path: Path) -> List[Tuple[str, str]]:
    """[(field, cited_path)] for a JSON GATE REPORT — a dict carrying a
    `verdict`. Anything else is data, not a claim, and is not judged."""
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or _VERDICT_KEY not in data:
        return []
    # A report that names its evidence AND states the evidence is ABSENT is
    # not making an unsubstantiated claim — it is disclosing one. The defect
    # this gate exists for is a PASS resting on evidence nobody can open;
    # counting an explicit `evidence_present: false` as a dangling citation
    # would penalise exactly the correction that fixes it (vibe-ic#381: three
    # reports were changed from an unbacked PASS to a disclosed
    # UNSUBSTANTIATED, and this gate would have kept flagging them for the
    # path string they honestly still name).
    if data.get("evidence_present") is False:
        return []
    out: List[Tuple[str, str]] = []
    for k, v in data.items():
        if isinstance(v, str) and _is_citation(v):
            out.append((str(k), v))
    return out


# ── DISCLOSED citations (vibe-ic#448 + the caravel landing) ────────────────
#
# `CITATION_ROUTING.txt` is the per-cell record of whether a reader can follow
# each citation, and OUT_OF_PUBLISHED_SCOPE is the decision it exists to
# express: the publisher copies phase1/, phase2/, phase3/reports/ and reports/,
# so a run-directory citation is correct WHERE THE RUN PUT IT and unfollowable
# HERE. That is a DISCLOSURE, not a hole — the reader is told, in a tracked
# artefact, exactly what they cannot reach.
#
# This gate used to count those as dangling, so the two mechanisms built for the
# same problem returned different verdicts on the same citation, and a cell that
# had done the disclosure correctly still could not land.
#
# ONLY the two decisions that give a STRUCTURAL reason the reader cannot follow
# it: the publisher's layout excludes the path, or the path is absolute and
# therefore unfollowable on any machine but the author's. Both are facts about
# the deliverable, and both are checkable.
#
# `DANGLING` and `DANGLING_UNDER_PASS` are deliberately NOT honoured. They mean
# "the publisher found no file", which is the HOLE, not a reason for it — and
# honouring them would let any new hole be laundered by writing one line into a
# routing file, which is precisely the shrink-only baseline discipline this gate
# exists to enforce. Considered and rejected while wiring this: it would have
# cleared the two remaining caravel findings and made the baseline meaningless.
#
# A RESOLVES row can never suppress a finding here — and cannot lie either,
# since `citation_routing_is_true_check` blocks a RESOLVES row whose file is not
# findable from the cell as committed.
_ROUTING_NAME = "CITATION_ROUTING.txt"
_DISCLOSURE_DECISIONS = {"OUT_OF_PUBLISHED_SCOPE", "UNFOLLOWABLE_ABSOLUTE"}


def _disclosed_map(root: Path, tracked: Optional[set]) -> Dict[Tuple[str, str], str]:
    """{(doc_rel_to_ROOT, cited): decision} for every disclosure recorded in a
    TRACKED routing file. Untracked records are ignored: a disclosure that is
    not published cannot inform a reader."""
    out: Dict[Tuple[str, str], str] = {}
    names = ([t for t in tracked if t.endswith("/" + _ROUTING_NAME)]
             if tracked is not None else
             [str(p.relative_to(root)) for p in root.rglob(_ROUTING_NAME)])
    for rel in sorted(names):
        cell = (root / rel).parent
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or " :: " not in s:
                continue
            rest, _, decision = s.rpartition(" ")
            if decision not in _DISCLOSURE_DECISIONS or " :: " not in rest:
                continue
            doc, _, cited = rest.partition(" :: ")
            try:
                key_doc = (cell / doc.strip()).relative_to(root).as_posix()
            except ValueError:
                continue
            out[(key_doc, cited.strip())] = decision
    return out


def scan(root: Path, tracked: Optional[set] = None
         ) -> Tuple[List[Dict[str, str]], int, int, List[str],
                    List[Dict[str, str]], List[Dict[str, str]],
                    List[Dict[str, str]]]:
    """`(dangling, cited_total, docs_scanned, zero_citation_docs, oversize,
    unjudged, outside)`.

    The last three are DISCLOSURE channels, never folded into the verdict:
    `oversize` is a token past the expansion bound, `unjudged` a dangling
    reference outside the judged extensions (`unjudged_dangling_ext`), and
    `outside` one that resolves against the repository but ABOVE this gate's
    scan root (`_resolves_outside_the_scan_root`). Each exists because the
    silent `continue` it replaces was indistinguishable from a clean read.

    Only TRACKED documents are scanned and only TRACKED artifacts satisfy a
    citation when `tracked` is available — see `tracked_files`.

    `zero_citation_docs` IS PART OF THE VERDICT'S EVIDENCE, not a statistic
    (vibe-ic#1044). A document that contributes no citation is the one shape
    this gate cannot distinguish from a document it read and cleared, and that
    indistinguishability is exactly how brace-notation blindness survived: the
    gate reported `434 doc(s), 221 citation(s)` and PASS while `METHODOLOGY.md`
    — in scope, 70 backticked tokens — contributed nothing. Reported now, so a
    future notation this extractor cannot see shows up as a population that
    moved rather than as a green run.
    """
    dangling: List[Dict[str, str]] = []
    zero_docs: List[str] = []
    oversize: List[Dict[str, str]] = []
    unjudged: List[Dict[str, str]] = []
    outside: List[Dict[str, str]] = []
    disclosed = _disclosed_map(root, tracked)
    cited = 0
    docs = 0
    # ENUMERATE FROM THE TRACKED LIST, never from a filesystem walk. A
    # walk-then-filter enumerated 440 documents locally and 422 in CI on the
    # SAME commit — directory traversal is environment-dependent (symlinks,
    # traversal order, name encoding) in ways `git ls-files` is not. The
    # baseline is a set of digests, so any enumeration difference between
    # where it is WRITTEN and where it is CHECKED shows up as phantom
    # "resolved" entries. One source of truth for what exists.
    _mds = (sorted(root / t for t in tracked if t.lower().endswith(".md"))
            if tracked is not None else sorted(root.rglob("*.md")))
    for md in _mds:
        try:
            text = md.read_text(errors="replace")
        except OSError:
            continue
        docs += 1
        _contributed = 0
        for raw in _CITE_RE.findall(text):
            expansions = expand_braces(raw)
            if not expansions:
                # over the bound: disclosed, never silently dropped
                oversize.append({"doc": str(md.relative_to(root)),
                                 "citation": raw})
                continue
            for tok in expansions:
                if not _is_citation(tok):
                    # SEEN, NOT JUDGED — disclosed rather than dropped
                    # silently. See `unjudged_dangling_ext`. #1044.
                    _ux = unjudged_dangling_ext(md, tok, root, tracked)
                    if _ux is not None:
                        unjudged.append({"doc": str(md.relative_to(root)),
                                         "citation": tok, "ext": _ux})
                    continue
                cited += 1
                _contributed += 1
                if resolve_citation(md, tok, root, tracked) is None:
                    _d = str(md.relative_to(root))
                    if (_d, tok) in disclosed:
                        continue
                    if _resolves_outside_the_scan_root(tok, root):
                        # The artefact EXISTS; it just lives above this gate's
                        # root, so the resolution ladder — which stops at the
                        # root on purpose — cannot see it. Measured: 7 such
                        # citations. Calling them dangling would be the gate
                        # reporting its own scope as the document's defect,
                        # which is the exact failure #1044 is about.
                        outside.append({"doc": _d, "citation": tok})
                        continue
                    dangling.append({"doc": _d, "citation": tok})
        if not _contributed:
            zero_docs.append(str(md.relative_to(root)))
    _jsons = (sorted(root / t for t in tracked if t.lower().endswith(".json"))
              if tracked is not None else sorted(root.rglob("*.json")))
    for js in _jsons:
        refs = _json_artifact_refs(js)
        if refs:
            docs += 1
        for field, tok in refs:
            cited += 1
            if resolve_citation(js, tok, root, tracked) is None:
                _d = str(js.relative_to(root))
                if (_d, tok) in disclosed:
                    continue
                dangling.append({"doc": _d, "citation": f"[{field}] {tok}"})
    return dangling, cited, docs, zero_docs, oversize, unjudged, outside


def _working_tree_dirt(root: Path) -> List[str]:
    """Untracked or modified paths under `root`, as git reports them. Empty
    when the tree is clean or git is unavailable (the caller degrades)."""
    try:
        r = subprocess.run(["git", "-C", str(root), "status", "--porcelain",
                            "--", "."], capture_output=True, text=True,
                           timeout=120)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    return [ln[3:] for ln in r.stdout.splitlines() if ln.strip()]


def _key(d: Dict[str, str]) -> str:
    """Human-readable identity: `<doc>::<citation>`. Printed at RUN time,
    never written to the baseline — see `_digest`."""
    return f"{d['doc']}::{d['citation']}"


def _digest(key: str) -> str:
    """What the BASELINE stores.

    The register must not publish the paths it lists. Some benchmark-data
    directory names embed a commercial foundry product name, and a landed
    diff is permanent public content — writing the literal paths would make
    this gate a leak vector (caught by `nda_diff_scan_check` on its first
    attempt to land, exactly as intended). A digest gives the register the
    only thing it actually needs — set membership — while the offending
    paths stay fully visible to whoever RUNS the gate, printed from the live
    scan. Machine-checkable without disclosure; readable on demand."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _load_baseline(path: Path) -> Optional[List[str]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    ents = data.get("unresolved") if isinstance(data, dict) else data
    return sorted({str(e) for e in ents}) if isinstance(ents, list) else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="cited evidence artifacts must exist (#361)")
    ap.add_argument("root", nargs="?", default=None)
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the CURRENT unresolved set; it may only "
                         "ever shrink from there")
    ap.add_argument("--scope-expanded", metavar="REASON",
                    help="permit a GROWING baseline for this write, because "
                         "the gate now LOOKS at more than it did (a wider "
                         "scope finds pre-existing debt; that is not a "
                         "regression). Requires a reason, which is recorded "
                         "in the baseline beside the previous size — a "
                         "deliberate, auditable act, never a bypass flag.")
    args = ap.parse_args(argv)

    here = Path(__file__).resolve()
    explicit_root = bool(args.root)
    if args.root:
        root = Path(args.root)
    else:
        root = next((b / _DEFAULT_ROOT_REL for b in here.parents
                     if (b / _DEFAULT_ROOT_REL).is_dir()), None)
    if root is None or not root.is_dir():
        print("[SKIP] evidence_citation_resolves_check: no scan root "
              f"({args.root or _DEFAULT_ROOT_REL} not found).")
        return 2

    baseline_path = (Path(args.baseline) if args.baseline
                     else root.parent / _BASELINE_NAME)
    tracked = tracked_files(root)
    dangling, cited, docs, zero_docs, oversize, unjudged, outside = scan(
        root, tracked)
    now = sorted({_key(d) for d in dangling})

    if args.write_baseline:
        # REFUSE to record a baseline from a DIRTY tree. This is not caution,
        # it is the bug that shipped: the first baseline was generated from a
        # working tree holding untracked artifacts, so it was green locally
        # and RED in CI (12 entries "resolved", 9 new dangling). A debt
        # register describing the author's laptop is worse than none.
        if args.scope_expanded is not None and len(
                args.scope_expanded.strip()) < 30:
            print("[FAIL] --scope-expanded needs a real reason (>=30 chars) "
                  "naming what the gate now looks at that it did not before.")
            return 1
        dirty = _working_tree_dirt(root)
        if dirty:
            print(f"[FAIL] refusing to write a baseline from a DIRTY tree — "
                  f"{len(dirty)} untracked/modified path(s) under {root} "
                  f"would change what resolves. Generate it from a clean "
                  f"checkout (e.g. `git worktree add --detach <tmp> HEAD`).")
            for d in dirty[:5]:
                print(f"   {d}")
            return 1
        prev = _load_baseline(baseline_path) or []
        if prev and len(now) > len(prev) and args.scope_expanded is None:
            print(f"[FAIL] refusing to GROW the baseline "
                  f"({len(prev)} -> {len(now)}). The baseline is a debt "
                  f"register, not a waiver list. If the gate now LOOKS at "
                  f"more than it did, say so with --scope-expanded '<why>' "
                  f"— a wider scope finding pre-existing debt is not a "
                  f"regression, but it must be recorded, not assumed.")
            return 1
        baseline_path.write_text(json.dumps(
            {"_comment": ("Known-unresolved evidence citations (#361). MAY "
                          "ONLY SHRINK. Entries are sha256-32 digests of "
                          "'<doc>::<citation>' — the paths themselves are "
                          "NOT stored (some embed a commercial foundry "
                          "product name and a landed diff is permanent "
                          "public content). Run the gate to see them."),
             "unresolved": sorted(_digest(k) for k in now),
             **({"scope_expansion": {
                 "previous_size": len(prev),
                 "reason": args.scope_expanded.strip()}}
                if args.scope_expanded is not None and len(now) > len(prev)
                else {})}, indent=2)
            + "\n")
        print(f"wrote {baseline_path} ({len(now)} entr(ies))")
        return 0

    base = _load_baseline(baseline_path)
    now_dig = {_digest(k): k for k in now}
    findings: List[str] = []
    if base is None:
        findings = list(now)
        stale: List[str] = []
    else:
        findings = [k for k in now if _digest(k) not in set(base)]
        # entries the baseline claims are broken but that now resolve: the
        # debt was paid and the register must be updated, else the register
        # slowly turns into permission.
        stale = [d for d in base if d not in now_dig]

    result = {
        "program": "evidence_citation_resolves_check",
        "docs_scanned": docs,
        "citations_checked": cited,
        "unresolved_total": len(now),
        # THE DENOMINATOR, per vibe-ic#1044. A gate that says PASS without
        # saying over WHAT is unfalsifiable, and this repo has ruled on that
        # (`gate_zero_denominator_refuses_check`). `docs_contributing_zero` is
        # the number that would have exposed the brace blindness on the day it
        # was introduced.
        "docs_contributing_zero_citations": len(zero_docs),
        "oversize_tokens": oversize,
        # SEEN but outside the judged extensions, and dangling. Disclosed,
        # never folded into the verdict — see `unjudged_dangling_ext`.
        "unjudged_dangling": unjudged,
        "unjudged_dangling_count": len(unjudged),
        "out_of_scan_root": len(outside),
        "baseline_size": (len(base) if base is not None else None),
        "new_dangling": findings,
        "stale_baseline_entries": stale,
        "passed": not findings and not stale,
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2) + "\n")

    print(f"evidence_citation_resolves_check: {docs} doc(s), "
          f"{cited} citation(s) checked under {root}")
    if outside:
        print(f"  OUT OF SCOPE   : {len(outside)} citation(s) resolve against the "
              f"repository but ABOVE this gate's scan root — the document is "
              f"correct and this gate is not the one that judges it")
    print(f"  contributed 0  : {len(zero_docs)} of {docs} document(s) yielded "
          f"NO citation this extractor can see — not evidence of cleanliness, "
          f"and the number that exposes a notation it is blind to (#1044)")
    if oversize:
        print(f"  NOT expanded   : {len(oversize)} token(s) over the "
              f"{_MAX_EXPANSIONS}-path expansion bound, listed so a bound is "
              f"never a silent drop:")
        for o in oversize[:5]:
            print(f"     {o['doc']} :: {o['citation'][:90]}")
    # SEEN, NOT JUDGED. Printed unconditionally when non-empty, and worded so
    # a green verdict cannot be read as "no dangling references": it is
    # "no dangling references OF THE KIND THIS GATE JUDGES". #1044.
    if unjudged:
        _exts: Dict[str, int] = {}
        for u in unjudged:
            _exts[u["ext"]] = _exts.get(u["ext"], 0) + 1
        _top = ", ".join(f"{e} x{n}" for e, n in
                         sorted(_exts.items(), key=lambda kv: -kv[1])[:6])
        print(f"  SEEN not judged: {len(unjudged)} citation(s) point at "
              f"nothing but fall outside the judged set "
              f"({'/'.join(_EVIDENCE_EXT)}, and "
              f"{'/'.join(_DOCUMENT_EXT)} carrying a directory), so this "
              f"gate does NOT rule on them — a PASS below means 'no dangling "
              f"EVIDENCE or DOCUMENT citation', not 'no dangling citation' "
              f"({_top})")
        for u in unjudged[:5]:
            print(f"     {u['doc']} :: {u['citation'][:90]}")
    if not explicit_root:
        print(f"  NOT scanned    : {_DISCLOSED_OUT_OF_SCOPE[0]} — "
              f"{_DISCLOSED_OUT_OF_SCOPE[1]}")
    if tracked is None:
        print("  WARNING        : git-tracked file set unavailable — falling "
              "back to plain filesystem existence. An UNTRACKED local "
              "artifact can satisfy a citation here, so this run is weaker "
              "than CI's and its baseline must not be committed.")
    print(f"  unresolved now : {len(now)}"
          + (f"   baseline: {len(base)}" if base is not None else
             "   (no baseline recorded)"))
    if stale:
        print(f"[FAIL] {len(stale)} baseline entr(ies) now RESOLVE — the "
              f"debt was paid; shrink the baseline so it cannot become a "
              f"standing waiver:")
        for d in stale[:10]:
            print(f"   (resolved) digest {d}")
    if findings:
        print(f"[FAIL] {len(findings)} NEW dangling evidence citation(s) — "
              f"the document points at a proof it does not ship:")
        for k in findings[:20]:
            print(f"   {k}")
        if len(findings) > 20:
            print(f"   ... and {len(findings) - 20} more (not truncated "
                  f"silently — this line is the disclosure)")
    if not findings and not stale:
        print(f"[PASS] every cited evidence artifact resolves, or is "
              f"within a baseline that has not grown.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
