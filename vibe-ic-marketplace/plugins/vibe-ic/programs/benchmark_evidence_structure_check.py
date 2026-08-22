#!/usr/bin/env python3
"""benchmark_evidence_structure_check.py — CI gate for published benchmark
evidence folders (the STRUCTURE half of the program-first publish contract).

WHY THIS EXISTS (owner directive 2026-07-25)
============================================
"The way we publish a CONVERGED (IC × PDK) result's evidence into
benchmark-data/ic/ must become a PROGRAM in the plugin (program-first), so
EVERY future push to benchmark-data/ic/<IC>/ automatically follows the same
structure — never again a lone RESULT.md or a messy folder."

`benchmark_evidence_publish.py` STAGES the canonical structure; THIS program
VALIDATES it. Wire it into CI (or run it by hand) so a malformed publish is
caught before it lands, and a third-party contributor publishing a new IC gets
an unambiguous PASS/FAIL against the same rules the reference cells satisfy.

THE CANONICAL STRUCTURE (a converged IC × PDK cell)
===================================================
    benchmark-data/ic/<IC>/v<plugin-version>_<PDK>/
        RESULT.md                           independent-audit verdict
        phase1/generated_docs/              the L* JSON design docs
        phase2/                             RTL + synth + constraints
        (phase3/reports/ OR reports/phase3/) DRC/LVS/STA/IR/EM rpt+json
        phase3/stage4/gds/GDS_MANIFEST.txt  <name> <bytes>B sha256:<hash>
    benchmark-data/ic/<IC>/input/           shared design input (once per IC)

WHAT THIS GATE ENFORCES (each is a named nonconformance on failure)
===================================================================
  NAMING            folder basename is exactly `v<major>.<minor>.<patch>_<PDK>`
                    (plugin VERSION first, then PDK). The common mistakes are
                    named + rejected explicitly:
                      * `clean_run_*`  — a gitignored prefix that would STRIP the
                        committed phase folders (the evidence never lands).
                      * `pass_*` / `fail_*` / `PASS_*` — a verdict prefix; the
                        verdict belongs in RESULT.md, never in the folder name.
  RESULT_PRESENT    RESULT.md exists and is non-empty.
  CONVERGED         RESULT.md's VERDICT is PASS or PASS_WITH_WAIVERS. A FAIL (or
                    an unstated) verdict is NOT publishable evidence — a failing
                    run must never be staged as if it passed.
  PHASE1_DOCS       phase1/generated_docs/ present with >= 1 file.
  PHASE2            phase2/ present with >= 1 file.
  PHASE3_REPORTS    at least one of phase3/reports/ or reports/phase3/ present
                    with >= 1 file.
  GDS_MANIFEST      phase3/stage4/gds/GDS_MANIFEST.txt present, non-empty, and
                    every content line matches `<filename> <int>B sha256:<64hex>`
                    (>= 1 valid line). ALWAYS required, whether or not the GDS
                    itself ships: it is what keeps an artefact verifiable when
                    it is too large to store.
  IC_LEVEL_LAYOUT   checked on the `ic/<IC>/` directory ITSELF, not on a cell.
                    Only two kinds of entry belong at that level: the shared
                    `input/`, and one `v<major>.<minor>.<patch>_<PDK>` directory
                    per converged cell. Anything else is run output that landed
                    beside the cells instead of inside one, so it is attributable
                    to no plugin version and no PDK.
                      Until this rule existed the per-cell walk simply did not
                    ENUMERATE such an entry: `_discover_evidence_folders` keeps
                    a child only when it looks version-y, carries a rejected
                    prefix, or holds a RESULT.md, so a bare `phase1/` `phase3/`
                    `reports/` at the IC level was skipped in silence and the
                    tree still reported "N/N conformant". A misnamed publish was
                    named; an UNNAMED one was invisible.
                      This rule RECORDS the divergence — it never decides that
                    the content should be retired. Deciding that is the owner's
                    call, and the entries can equally be MOVED into the cell they
                    belong to; both routes need the violation measured first.
                      An `ic/<IC>/` that published NOTHING is not a unit that
                    passed this rule; it is a unit the rule never got to judge.
                    See ZERO DENOMINATOR below — that distinction is the whole
                    subject of the rule, moved one level up.
                      Under `--changed-since` the rule judges the entries THIS
                    CHANGE CREATED and RECORDS the rest. See ADDED vs
                    PRE-EXISTING below.

ADDED vs PRE-EXISTING: A RECORD MUST NOT BECOME A VETO (vibe-ic#1538)
====================================================================
`test_matrix_d3_outputs_produced` ends every unevidenced verdict with one
instruction — "commit (or register in the manifest) a run tree that carries it".
Taking it was refused, and the refusal was this rule: 8 of the 9 ICs that carry
run output were laid out before the `v<ver>_<PDK>` convention, so EVERY tracked
change under one of their pre-existing IC-level entries was failed by entries
the change did not create. Measured on origin/main: a commit that ADDS NOTHING
— one comment line appended to an already-tracked file under a stray — produced
the byte-identical 15-entry finding as a commit that adds four files. The
repository printed a remedy and then refused the action.

`_changed_ic_dirs` already scoped the diff to the stray entries themselves, but
that only exempts a push that publishes BESIDE a stray; a push that touches a
file UNDER one still met the whole legacy register. So `--changed-since` now
splits the finding at the granularity the rule actually judges — the entries
directly under `ic/<IC>/`:

  * an entry that is NOT in the baseline listing was created by this change and
    is a FAILURE, exactly as before;
  * an entry that IS in the baseline listing is DISCLOSED on its own line as a
    pre-existing divergence, recorded and not accepted, and does not fail.

The register is read from git at the baseline rev rather than kept in a file,
which is what gives it the discipline every other shrink-only register in this
repo is held to, without a list to forget to update:
  * it CANNOT GROW — a stray absent at the baseline FAILs the moment it appears;
  * it SHRINKS BY ITSELF — migrating or retiring an entry removes it from the
    register in the same commit, with nothing to re-record;
  * it is NEVER STANDING PERMISSION — every run reprints the full pre-existing
    set, and a full `--tree` run (no `--changed-since`, the audit shape) still
    FAILs on every one of them, unchanged.
The lenient direction is bounded to entries git can prove predate the change; a
baseline that cannot be read grandfathers NOTHING and says so.

ZERO DENOMINATOR: A UNIT THAT EXAMINED NOTHING IS NOT A UNIT THAT PASSED (#967)
==============================================================================
Adding the IC-level rule (#952) made an EMPTY `ic/<IC>/` — no `input/`, no cell,
no published entry of any kind — a CONFORMANT unit: `main()` relaxed the
"nothing to check" refusal from `if not targets:` to `if not targets and not
ic_dirs:`, so a tree of three empty IC directories printed **3/3 conformant**
and exited 0 where the program had previously refused with rc 2. The rule was
not wrong (an empty directory genuinely has no stray entries); the ROLL-UP was,
because it credited a number that reads like coverage to a tree that published
nothing. That is the same misreading #952 was written against.

The repo already fixes the answer, in two rules that apply at two levels, and
this program obeys both rather than inventing a third:

  * `gate_discloses_denominator_check` — "a PASS must say how much it looked
    at ... A gate may say PASS over zero items as long as a reader can SEE that
    it was zero: a count, or an explicit 'no corpus' / 'nothing to check' /
    SKIP." So a per-unit zero is DISCLOSED, never silently folded into a tally:
    an IC directory with no published entry prints `[SKIP]` with its zero, and
    is counted in neither the numerator nor the denominator. Every conforming
    unit now also prints the count it judged.
  * `gate_zero_denominator_refuses_check` — "the gate states it read NOTHING and
    still exits 0 ... Either make it refuse (rc 2 is the disclosed-skip
    convention)". So when NOTHING at all was examined — every discovered unit
    skipped, no evidence folder anywhere — the whole run refuses with rc 2,
    which is precisely the pre-#952 behaviour restored at the right place.

`--changed-since` is untouched: grandfathering already answers "nothing changed
to enforce" with rc 0 and a disclosure, and that is the CI shape
`gatekeeper-land.sh` runs on every push that does not touch benchmark-data.
  NO_RAW_GEOMETRY   no *.gds / *.def / *.spef / *.oas ABOVE THE 50 MB COMMIT
                    CEILING is committed under the folder (#419). It used to
                    reject them by extension, and that rule FAILED all three
                    reference cells — the most complete evidence this repo
                    publishes — because `.gitignore` accepts layout artefacts
                    under `benchmark-data/ic/**` and those cells carry them.
                    Size is what decides whether a file can be committed at
                    all, so size is what is checked. When run inside a git
                    repo the scan is over git-tracked (+ optionally staged)
                    files, so a locally-gitignored scratch artifact does not
                    false-FAIL; outside a repo it is a filesystem scan.

chip-AGNOSTIC: the IC, PDK and version are read off the path; NO IC / PDK /
vendor / SKU literal appears in this program's logic.

USAGE
=====
    # validate one evidence folder
    python3 benchmark_evidence_structure_check.py benchmark-data/ic/<IC>/v1.5.66_<PDK>

    # validate every published cell in a tree (the CI shape)
    python3 benchmark_evidence_structure_check.py --tree benchmark-data

    # also count files staged (git add'd) but not yet committed
    python3 benchmark_evidence_structure_check.py --include-staged <folder>

    # machine-readable
    python3 benchmark_evidence_structure_check.py --tree benchmark-data --json out.json

    # CI shape: enforce ONLY the evidence folders this push touched, so future
    # pushes are correct-by-construction while pre-existing folders are
    # grandfathered (never retroactively failed by an unrelated PR).
    python3 benchmark_evidence_structure_check.py --tree benchmark-data \
        --changed-since origin/main

EXIT CODES
==========
    0  every EXAMINED unit CONFORMS (>= 1 unit was examined)
    1  at least one folder is NONCONFORMANT
    2  usage / I/O error, or NOTHING WAS EXAMINED — no evidence folder and no
       IC directory that published anything. A zero denominator is a refusal,
       not a pass (#967).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# --------------------------------------------------------------------------
# Contract constants (structure, not chips).
# --------------------------------------------------------------------------

# `v<major>.<minor>.<patch>_<PDK>` — version FIRST, then a non-empty PDK tag.
#: Where the published corpus is, now that it is not in this repository.
#:
#: Spelled the same way `programs/tests/_published_corpus.py` spells it, on purpose:
#: one name for one thing. A gate and a test suite that disagree about where the
#: corpus lives will disagree about whether it was checked.
CORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"

_NAME_RE = re.compile(r"^v\d+\.\d+\.\d+_.+$")

# Folder-name prefixes that are known-wrong and get a specific message.
_BAD_PREFIXES = ("clean_run_", "pass_", "fail_", "PASS_", "FAIL_")

# Layout artefacts. Until #419 this rule rejected them outright by extension,
# and it therefore FAILED all three reference cells — the most complete
# evidence this repo publishes — because they carry exactly these files and
# `.gitignore` accepts them. Now judged BY SIZE, which is the property that
# actually decides whether an artefact can be committed at all.
_LAYOUT_EXTS = (".gds", ".def", ".spef", ".oas")

# Must equal `tracked_blob_size_guard._CEILING` and
# `benchmark_evidence_publish._SIZE_CEILING`. `size_policy_drift_check.py`
# fails when they stop agreeing — five mechanisms disagreed about this before
# #419 and each of them looked locally reasonable.
_SIZE_CEILING = 50 * 1000 * 1000


def is_layout_artefact(p: Path) -> bool:
    """True for the four extensions whose committability this gate judges."""
    return p.suffix.lower() in _LAYOUT_EXTS


def over_ceiling(p: Path, ceiling: int = _SIZE_CEILING) -> bool:
    """True when `p` is too big to commit.

    A helper, NOT this module's decision. `size_policy_drift_check` probes
    `check_folder` below, because that is where the extension-only rule #419
    removed actually lived: reverting `check_folder` while leaving this
    function correct beside it is a real regression that a probe of this
    function cannot see. Naming the decision precisely is the point — an
    earlier version of the gate probed here and rubber-stamped exactly that
    mutant.
    """
    return p.stat().st_size > ceiling

# GDS_MANIFEST line: "<filename> <int>B sha256:<64 hex>"
_MANIFEST_LINE_RE = re.compile(r"^\S+ \d+B sha256:[0-9a-fA-F]{64}$")

# Converged verdict tokens (order matters: match the most specific first).
_VERDICT_TOKENS = ("PASS_WITH_WAIVERS", "PASS", "FAIL")
_CONVERGED = ("PASS", "PASS_WITH_WAIVERS")


#: How each `FolderResult.kind` reads in the roll-up. A kind with no entry here
#: still prints, under its own name — the line must never lose a population just
#: because nobody added a label for it.
_KIND_LABEL = {"cell": "published cell", "ic-root": "IC-level root"}


@dataclass
class FolderResult:
    path: str
    # "cell" = a v<ver>_<PDK> evidence folder; "ic-root" = the ic/<IC>/ directory
    # itself, whose only rule is IC_LEVEL_LAYOUT. Kept explicit so a reader (and
    # the --json consumer) can tell the two apart: an ic-root has no PDK, no
    # version and no verdict, and printing it as a cell with three None fields
    # reads like a cell that lost its identity.
    kind: str = "cell"
    ic: Optional[str] = None
    pdk: Optional[str] = None
    version: Optional[str] = None
    verdict: Optional[str] = None
    # None = NO VERDICT WAS RENDERED (see `skip`). Deliberately not False: a
    # unit that examined nothing did not fail, and deliberately not True: it did
    # not pass either. A --json consumer summing `conforms is True` gets the
    # honest numerator; one summing falsiness over-reports failures, which is
    # the safe direction for a check whose whole subject is an undeserved PASS.
    conforms: Optional[bool] = True
    # How much this unit actually looked at, so a PASS says so on its own line
    # (`gate_discloses_denominator_check`). None for a unit whose denominator is
    # a fixed rule set rather than a discovered population (a cell).
    examined: Optional[int] = None
    # True iff the unit's denominator was ZERO. Excluded from BOTH the numerator
    # and the denominator of the roll-up, and disclosed as `[SKIP]`.
    skipped: bool = False
    # IC-level entries this change did NOT create, recorded rather than charged
    # to it (vibe-ic#1538). Machine-readable on purpose: a disclosure only a
    # human can read cannot be tracked for growth by anything but a human, and
    # this one exists precisely so its size can be watched.
    pre_existing: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)   # "RULE: message"
    checks: Dict[str, Optional[bool]] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)     # "RULE: why it passed differently"

    def fail(self, rule: str, msg: str) -> None:
        self.conforms = False
        self.failures.append(f"{rule}: {msg}")
        self.checks[rule] = False

    def skip(self, rule: str, why: str) -> None:
        """Record that the rule had NOTHING to judge (#967).

        Not `ok()`: a rule that found no violations because there was nothing
        that COULD violate it has not been satisfied, it has been vacated, and
        folding the two together is how "3/3 conformant" gets printed over a
        tree that published nothing."""
        self.skipped = True
        self.conforms = None
        self.checks[rule] = None
        self.notes.append(f"{rule}: {why}")

    def ok(self, rule: str, note: str = "") -> None:
        """Record a pass. `note` is for a rule that passed on a DIFFERENT basis
        than its default — an escape that is silent is indistinguishable from a
        rule that was simply met, which is the reading this whole check exists
        to prevent."""
        self.checks.setdefault(rule, True)
        if note:
            self.notes.append(f"{rule}: {note}")


# --------------------------------------------------------------------------
# git-awareness (so "committed" is enforced precisely, without false-FAIL on
# locally-gitignored scratch files).
# --------------------------------------------------------------------------

def _git_toplevel(folder: Path) -> Optional[Path]:
    try:
        out = subprocess.run(
            ["git", "-C", str(folder), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except Exception:
        pass
    return None


def _git_listed_files(repo: Path, folder: Path, include_staged: bool) -> Set[Path]:
    """Absolute paths of git-tracked (and optionally staged) files under folder.

    The pathspec is RESOLVED first, and that is load-bearing rather than tidy.
    `git -C <repo>` interprets a relative pathspec against the REPO ROOT, not
    against the caller's cwd, so a folder named relatively -- which is exactly
    how the shipped invocation reaches this, `--tree ../../../benchmark-data`
    from the plugin directory -- escapes the repo and matches nothing. git then
    exits 0 with empty output, the caller reads "no tracked files here", and
    every entry is filtered away as untracked scratch.

    Measured 2026-08-11 on origin/main, same tree, same commit, one argument
    style apart:

        --tree ../../../benchmark-data   ->  9 IC dirs, 0 failing, "13/28 conformant"
        --tree /abs/path/benchmark-data  ->  9 IC dirs, 8 failing, 93 entries

    The relative form is a PASS earned by looking at nothing.
    """
    repo = Path(repo).resolve()
    folder = Path(folder).resolve()
    files: Set[Path] = set()
    cmds = [["git", "-C", str(repo), "ls-files", "--", str(folder)]]
    if include_staged:
        cmds.append(
            ["git", "-C", str(repo), "diff", "--cached", "--name-only", "--", str(folder)]
        )
    for cmd in cmds:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except Exception:
            continue
        if out.returncode != 0:
            continue
        for line in out.stdout.splitlines():
            line = line.strip()
            if line:
                files.add((repo / line).resolve())
    return files


def _raw_scan_set(folder: Path, include_staged: bool) -> Tuple[List[Path], str]:
    """Return (files_to_scan_for_raw_geometry, mode).

    Inside a git repo -> git-tracked (+staged) set (== "committed"). Otherwise
    -> a filesystem walk (catches a pre-commit / non-repo malformed publish).
    """
    repo = _git_toplevel(folder)
    if repo is not None:
        listed = _git_listed_files(repo, folder, include_staged)
        return sorted(listed), "git-tracked" + ("+staged" if include_staged else "")
    fs = [p for p in folder.rglob("*") if p.is_file()]
    return sorted(fs), "filesystem"


def _has_file(d: Path) -> bool:
    """True iff directory d exists and contains at least one regular file."""
    if not d.is_dir():
        return False
    for _root, _dirs, files in os.walk(d):
        if files:
            return True
    return False


# --------------------------------------------------------------------------
# RESULT.md verdict extraction.
# --------------------------------------------------------------------------

def _extract_verdict(result_md: Path) -> Optional[str]:
    """Return the converged/failed verdict token declared in RESULT.md, or None.

    Prefers the token bolded/stated inside the `## VERDICT` section; falls back
    to the first recognized token anywhere in the file. chip-AGNOSTIC — keys off
    the verdict vocabulary only.
    """
    try:
        text = result_md.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    upper = text.upper()

    # Prefer the VERDICT section body.
    m = re.search(r"^#{1,6}\s*VERDICT\b", upper, re.MULTILINE)
    search_regions = []
    if m:
        start = m.end()
        nxt = re.search(r"^#{1,6}\s", upper[start:], re.MULTILINE)
        end = start + nxt.start() if nxt else len(upper)
        search_regions.append(upper[start:end])
    search_regions.append(upper)  # fallback: whole file

    for region in search_regions:
        best_pos = None
        best_tok = None
        for tok in _VERDICT_TOKENS:
            for tm in re.finditer(r"\b" + re.escape(tok) + r"\b", region):
                # Do not let the PASS inside PASS_WITH_WAIVERS win over the
                # longer token at the same position.
                if tok == "PASS" and region[tm.start():tm.start() + len("PASS_WITH_WAIVERS")] == "PASS_WITH_WAIVERS":
                    continue
                pos = tm.start()
                if best_pos is None or pos < best_pos:
                    best_pos, best_tok = pos, tok
        if best_tok is not None:
            return best_tok
    return None


# --------------------------------------------------------------------------
# GDS_MANIFEST validation.
# --------------------------------------------------------------------------

def _check_manifest(manifest: Path) -> Tuple[bool, str]:
    if not manifest.is_file():
        return False, f"missing {manifest.name} at phase3/stage4/gds/"
    try:
        lines = manifest.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        return False, f"unreadable manifest: {exc}"
    content = [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    if not content:
        return False, "manifest is empty (no <name> <bytes>B sha256:<hash> line)"
    for ln in content:
        if not _MANIFEST_LINE_RE.match(ln):
            return False, f"malformed manifest line: {ln!r} (want '<file> <int>B sha256:<64hex>')"
    return True, f"{len(content)} manifest line(s) valid"


# --------------------------------------------------------------------------
# The single-folder validator.
# --------------------------------------------------------------------------

def check_folder(folder: Path, include_staged: bool = False) -> FolderResult:
    folder = folder.resolve()
    res = FolderResult(path=str(folder))
    name = folder.name

    # Try to attribute IC from the path (…/ic/<IC>/<verdir>). Best-effort only.
    parent = folder.parent
    if parent.parent.name == "ic":
        res.ic = parent.name

    # ---- NAMING ----------------------------------------------------------
    matched_bad = next((p for p in _BAD_PREFIXES if name.startswith(p)), None)
    if matched_bad == "clean_run_":
        res.fail("NAMING",
                 f"'{name}' uses the gitignored `clean_run_` prefix — the "
                 f"committed phase folders would be STRIPPED. Rename to "
                 f"v<plugin-version>_<PDK>.")
    elif matched_bad:
        res.fail("NAMING",
                 f"'{name}' uses a verdict/status prefix `{matched_bad}` — the "
                 f"verdict belongs in RESULT.md, not the folder name. Rename to "
                 f"v<plugin-version>_<PDK>.")
    elif not _NAME_RE.match(name):
        res.fail("NAMING",
                 f"'{name}' is not v<major>.<minor>.<patch>_<PDK> "
                 f"(plugin VERSION first, then PDK).")
    else:
        res.ok("NAMING")
        mv = re.match(r"^v(\d+\.\d+\.\d+)_(.+)$", name)
        if mv:
            res.version, res.pdk = mv.group(1), mv.group(2)

    # ---- RESULT_PRESENT + CONVERGED -------------------------------------
    result_md = folder / "RESULT.md"
    if not result_md.is_file() or result_md.stat().st_size == 0:
        res.fail("RESULT_PRESENT", "RESULT.md is missing or empty")
    else:
        res.ok("RESULT_PRESENT")
        verdict = _extract_verdict(result_md)
        res.verdict = verdict
        if verdict is None:
            res.fail("CONVERGED",
                     "RESULT.md states no recognizable verdict "
                     "(want PASS or PASS_WITH_WAIVERS in a VERDICT section)")
        elif verdict not in _CONVERGED:
            res.fail("CONVERGED",
                     f"RESULT.md verdict is {verdict} — only a converged run "
                     f"(PASS / PASS_WITH_WAIVERS) may be published as evidence")
        else:
            res.ok("CONVERGED")

    # ---- PHASE1_DOCS -----------------------------------------------------
    if _has_file(folder / "phase1" / "generated_docs"):
        res.ok("PHASE1_DOCS")
    else:
        res.fail("PHASE1_DOCS", "phase1/generated_docs/ missing or empty")

    # ---- PHASE2 ----------------------------------------------------------
    # `phase2/` is the RTL -> synth -> constraints stage of the DIGITAL flow. An
    # analog cell does not have one: it runs the A-track (A1-A9) from the L docs
    # to a layout, and its evidence lives in reports/analog*.
    #
    # This rule used to be unconditional, so it asked "does phase2/ exist" and
    # its answer was read as "is this evidence folder complete". MEASURED on
    # u_hawaii_adc x sky130A, a cell that had just PASSED its own flow gate with
    # PASS=8 FAIL=0 MISSING=0 (exit 0): the run holds phase1/ and phase3/ only,
    # `ic_class` is `data_converter`, and `reports/analog/` is populated. The
    # structure gate nonetheless failed it for missing a stage its flow never
    # runs — and so blocked publication of a converged cell.
    #
    # The escape is EVIDENCE-BOUND, not a waiver: it requires the folder to
    # positively show an analog track. A DIGITAL cell with no phase2/ still
    # fails, which is the case this rule exists for.
    _analog_evidence = [p for p in (folder / "reports").glob("analog*")
                        if p.exists()] if (folder / "reports").is_dir() else []
    if _has_file(folder / "phase2"):
        res.ok("PHASE2")
    elif _analog_evidence:
        res.ok("PHASE2",
               "analog track: no phase2/ RTL stage, evidence in "
               + ", ".join(sorted(p.name for p in _analog_evidence)))
    else:
        res.fail("PHASE2", "phase2/ missing or empty")

    # ---- PHASE3_REPORTS --------------------------------------------------
    if _has_file(folder / "phase3" / "reports") or _has_file(folder / "reports" / "phase3"):
        res.ok("PHASE3_REPORTS")
    else:
        res.fail("PHASE3_REPORTS",
                 "neither phase3/reports/ nor reports/phase3/ has any files")

    # ---- GDS_MANIFEST ----------------------------------------------------
    ok, msg = _check_manifest(folder / "phase3" / "stage4" / "gds" / "GDS_MANIFEST.txt")
    if ok:
        res.ok("GDS_MANIFEST")
    else:
        res.fail("GDS_MANIFEST", msg)

    # ---- NO_RAW_GEOMETRY -------------------------------------------------
    scan, mode = _raw_scan_set(folder, include_staged)
    layout = [p for p in scan if is_layout_artefact(p)]
    over = []
    for p in layout:
        try:
            if over_ceiling(p):
                over.append((p, p.stat().st_size))
        except OSError:
            continue
    if over:
        rels = ", ".join(
            f"{str(p.relative_to(folder))} ({s / 1e6:.0f} MB)"
            for p, s in sorted(over, key=lambda t: -t[1])[:10])
        res.fail("NO_RAW_GEOMETRY",
                 f"layout artefact(s) over the "
                 f"{_SIZE_CEILING / 1e6:.0f} MB commit ceiling ({mode}): "
                 f"{rels} — route these to git-lfs or a GitHub Release and "
                 f"keep the sha256 in GDS_MANIFEST.txt, which is what makes "
                 f"the artefact verifiable without being stored")
    else:
        res.ok("NO_RAW_GEOMETRY")

    return res


# --------------------------------------------------------------------------
# Tree discovery.
# --------------------------------------------------------------------------

def _changed_file_set(base: str, anchor: Path) -> Tuple[Optional[Set[Path]], str]:
    """Absolute paths added/modified since `base`, or (None, why) if undeterminable."""
    repo = _git_toplevel(anchor if anchor.exists() else Path.cwd())
    if repo is None:
        return None, "not a git repo"
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "diff", "--name-only", "--diff-filter=d",
             f"{base}...HEAD"],
            capture_output=True, text=True, check=False, timeout=60)
        if out.returncode != 0:
            # fall back to a two-dot diff (base not an ancestor / shallow clone)
            out = subprocess.run(
                ["git", "-C", str(repo), "diff", "--name-only", "--diff-filter=d",
                 base, "HEAD"],
                capture_output=True, text=True, check=False, timeout=60)
        if out.returncode != 0:
            return None, f"git diff against {base} failed"
    except Exception as exc:
        return None, f"git diff error: {exc}"
    return ({(repo / ln.strip()).resolve()
             for ln in out.stdout.splitlines() if ln.strip()},
            f"changed-since {base}")


def _changed_ic_dirs(base: str, ic_dirs: List[Path],
                     include_staged: bool) -> Tuple[Optional[List[Path]], str]:
    """Filter IC dirs to those whose OWN STRAY ENTRIES have a file changed since
    `base`.

    Deliberately NOT "any file under the IC dir changed". Publishing a new,
    perfectly conforming cell into an IC that already carries legacy strays
    touches the IC dir, and grandfathering exists precisely so that push is not
    failed by evidence it did not create. Scoping the diff to the stray entries
    themselves keeps the CI shape honest in both directions: a push that ADDS
    run output at the IC level is caught, and one that merely publishes beside
    pre-existing strays is not. Full `--tree` (no --changed-since) still reports
    every legacy violation.
    """
    changed, mode = _changed_file_set(base, ic_dirs[0] if ic_dirs else Path.cwd())
    if changed is None:
        return None, mode
    kept: List[Path] = []
    for ic in ic_dirs:
        roots = [s.resolve() for s in ic_level_strays(ic, include_staged)]
        if any(c == r or str(c).startswith(str(r) + os.sep)
               for r in roots for c in changed):
            kept.append(ic)
    return kept, mode


def _changed_evidence_roots(base: str, targets: List[Path]) -> Tuple[Optional[List[Path]], str]:
    """Filter `targets` to the evidence folders that have >= 1 file changed since
    `base` (added/modified; deletions ignored). Returns (kept, mode).

    `kept is None` signals "could not determine the change set". The caller
    REFUSES with rc 2 (vibe-ic#1254) — it used to fail-OPEN with rc 0 so CI
    plumbing never became a flaky blocker, but rc 0 is the one thing every
    caller branches on, so the disclosure in the message was invisible where it
    counted. rc 2 keeps the anti-flake promise without the lie: it is this
    file's own disclosed-skip convention (see the header's citation of
    `gate_zero_denominator_refuses_check`), and the pre-push hook renders it as
    `NOT CHECKED — the gate could not run`, not as a finding against the change.

    Distinct from "determined, and nothing changed", which is still rc 0 with a
    disclosure — that is a real answer, and grandfathering depends on it.
    """
    changed, mode = _changed_file_set(base, targets[0] if targets else Path.cwd())
    if changed is None:
        return None, mode
    kept = [t for t in targets
            if any(str(c).startswith(str(t.resolve()) + os.sep) or c == t.resolve()
                   for c in changed)]
    return kept, f"changed-since {base}"


def ic_level_entries(ic_dir: Path,
                     include_staged: bool = False) -> Tuple[List[Path], List[Path]]:
    """Return (published, strays) for the entries directly under `ic/<IC>/`.

    `published` is the POPULATION the IC_LEVEL_LAYOUT rule judges — every entry
    that counts as published content at that level: inside a git repo, a child
    holding >= 1 tracked (optionally staged) file; outside one, every child.
    `strays` is the subset that is neither the shared `input/` nor a
    `v<major>.<minor>.<patch>_<PDK>` cell.

    Split out for #967. `ic_level_strays` alone could not tell "this IC has
    entries and all of them are allowed" from "this IC has no entries at all",
    because both answer `[]` — and the roll-up read the second as a unit that
    passed. The denominator has to be a value the caller can see, not a shape
    the caller has to infer from an empty list.

    The stray set is UNCHANGED by the split: the git-tracked filter now runs
    before the allowed-entry filters instead of after, and every entry the
    tracked filter drops was already dropped (an untracked `input/`, cell or
    stray was a stray in neither ordering).
    """
    if not ic_dir.is_dir():
        return [], []
    repo = _git_toplevel(ic_dir)
    tracked: Optional[Set[Path]] = None
    if repo is not None:
        tracked = _git_listed_files(repo, ic_dir, include_staged)

    published: List[Path] = []
    strays: List[Path] = []
    for child in sorted(ic_dir.iterdir()):
        if tracked is not None:
            here = child.resolve()
            if not any(p == here or str(p).startswith(str(here) + os.sep)
                       for p in tracked):
                continue        # a developer's local scratch: not PUBLISHED
        published.append(child)
        if child.name == "input" and child.is_dir():
            continue
        if child.is_dir() and _NAME_RE.match(child.name):
            continue
        strays.append(child)
    return published, strays


def ic_level_strays(ic_dir: Path, include_staged: bool = False) -> List[Path]:
    """Entries directly under `ic/<IC>/` that the layout contract does not allow.

    Allowed: the shared `input/`, and one `v<major>.<minor>.<patch>_<PDK>`
    directory per converged cell. EVERYTHING else is returned — a stray run
    directory (`phase1/`, `phase3/`, `reports/`, `steps/`), a loose file
    (`RESULT.md`, `provenance.jsonl`) that belongs inside a cell, and a
    rejected-prefix folder (`clean_run_*`, `pass_*`) which is at the wrong
    LEVEL as well as under the wrong NAME.

    A rejected-prefix folder is deliberately reported by BOTH rules: NAMING says
    its contents would be stripped on the way in, IC_LEVEL_LAYOUT says it is not
    a cell. Those are different consequences and collapsing them would lose one.

    Git-aware, for the same reason NO_RAW_GEOMETRY is: inside a repo an entry
    counts only if it holds >= 1 tracked (optionally staged) file, so a local
    scratch directory a developer left beside the cells is not a finding about
    what was PUBLISHED. Outside a repo, every entry counts.

    Kept as the public name it has always been; the population half of the same
    walk is `ic_level_entries`.
    """
    return ic_level_entries(ic_dir, include_staged=include_staged)[1]


def _baseline_rev(base: str, repo: Path) -> str:
    """The rev the change set is measured FROM, matching `_changed_file_set`.

    That function diffs `base...HEAD` — three dots, i.e. from the MERGE BASE —
    so the register of entries "this change did not create" has to be read at
    the same point. Reading it at `base` itself would grandfather an entry that
    `base` acquired independently and the branch re-created, which is the one
    direction this split must not be wrong in. Falls back to `base` when
    merge-base cannot be computed, mirroring the two-dot fallback there.
    """
    try:
        out = subprocess.run(["git", "-C", str(repo), "merge-base", base, "HEAD"],
                             capture_output=True, text=True, check=False, timeout=60)
    except Exception:
        return base
    if out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip()
    return base


def ic_level_entry_names_at(base: str, ic_dir: Path) -> Tuple[Optional[Set[str]], str]:
    """Names of the entries directly under `ic/<IC>/` AS OF `base` (vibe-ic#1538).

    Returns `(names, mode)`, or `(None, why)` when the baseline could not be
    read. `None` is NOT "nothing pre-existed": the caller grandfathers nothing
    on it and says so, because a register derived from a listing that failed is
    a licence, not a record — the same distinction `--changed-since` itself
    draws between "determined, and nothing changed" and "could not determine".

    An IC directory that did not exist at `base` yields an EMPTY set with rc 0
    from git, which is the honest answer: every entry in it is new.
    """
    repo = _git_toplevel(ic_dir)
    if repo is None:
        return None, "not a git repo"
    try:
        rel = ic_dir.resolve().relative_to(Path(repo).resolve()).as_posix()
    except ValueError:
        return None, f"{ic_dir} is outside the repository"
    baseline = _baseline_rev(base, repo)
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "--name-only", baseline, f"{rel}/"],
            capture_output=True, text=True, check=False, timeout=60)
    except Exception as exc:
        return None, f"git ls-tree error: {exc}"
    if out.returncode != 0:
        return None, f"git ls-tree {baseline} failed"
    return ({Path(ln.strip()).name for ln in out.stdout.splitlines() if ln.strip()},
            baseline)


def check_ic_level_layout(ic_dir: Path,
                          include_staged: bool = False,
                          pre_existing_names: Optional[Set[str]] = None,
                          baseline_mode: str = "") -> FolderResult:
    """Validate the `ic/<IC>/` directory itself against the layout contract.

    `pre_existing_names` is the diff-scoped half (vibe-ic#1538): the entry names
    that already existed at the baseline rev. `None` — the default, and what a
    full `--tree` audit passes — means NOT diff-scoped, and every stray is a
    failure exactly as before. An EMPTY set is a different statement: nothing
    predates this change, so every stray is charged to it.
    """
    res = FolderResult(path=str(ic_dir), kind="ic-root", ic=ic_dir.name)
    published, strays = ic_level_entries(ic_dir, include_staged=include_staged)
    res.examined = len(published)
    if not published:
        # #967 — ZERO DENOMINATOR. Nothing was published at this level, so the
        # layout contract judged nothing. `not strays` is true here for the same
        # reason it is true of a perfectly laid-out IC, and reporting both as
        # PASS is what let "3/3 conformant" be printed over three empty
        # directories. rc-wise this is the disclosed-skip convention
        # (`gate_zero_denominator_refuses_check`), not a verdict.
        res.skip("IC_LEVEL_LAYOUT",
                 "0 published entries under this IC directory — no input/, no "
                 "v<ver>_<PDK> cell, nothing at all, so the layout contract had "
                 "nothing to judge. Not counted as a conformant unit: a unit "
                 "that examined nothing is not a unit that passed.")
        return res
    if not strays:
        res.ok("IC_LEVEL_LAYOUT")
        return res

    def _named(entries: List[Path]) -> str:
        return ", ".join(s.name + ("/" if s.is_dir() else "") for s in entries)

    # vibe-ic#1538 — ADDED vs PRE-EXISTING. Only the diff-scoped shape splits
    # them; a full audit run keeps every stray as a finding.
    if pre_existing_names is None:
        added, carried = strays, []
    else:
        added = [s for s in strays if s.name not in pre_existing_names]
        carried = [s for s in strays if s.name in pre_existing_names]
    res.pre_existing = [s.name + ("/" if s.is_dir() else "") for s in carried]

    if carried:
        res.notes.append(
            f"IC_LEVEL_LAYOUT: {len(carried)} pre-existing IC-level "
            f"entr{'y' if len(carried) == 1 else 'ies'} recorded, NOT accepted, "
            f"and not charged to this change (already present at "
            f"{baseline_mode or 'the baseline'}): {_named(carried)}. This set may "
            f"only shrink — an entry that is not in it FAILs the moment it "
            f"appears, and a full `--tree` run with no --changed-since still "
            f"FAILs every one of these.")

    if not added:
        # Grandfathered, and LOUDLY: the note above prints on PASS for exactly
        # this case. Charging the change for entries it did not create is what
        # turns this record into a veto on whoever touches the IC next.
        res.ok("IC_LEVEL_LAYOUT")
        return res

    scope = ""
    if pre_existing_names is not None:
        scope = (f" ADDED by this change"
                 + (f" ({len(carried)} further pre-existing "
                    f"entr{'y' if len(carried) == 1 else 'ies'} are recorded "
                    f"above and are not what failed this)" if carried else ""))
    res.fail(
        "IC_LEVEL_LAYOUT",
        f"{len(added)} entr{'y' if len(added) == 1 else 'ies'} at the IC level "
        f"{'is' if len(added) == 1 else 'are'} neither input/ nor a "
        f"v<ver>_<PDK> cell{scope}: {_named(added)}. Run output "
        f"here is attributable to no plugin version and no PDK. Move it into the "
        f"cell it belongs to, or retire it deliberately — this rule records the "
        f"divergence, it does not decide which.")
    return res


def _discover_ic_dirs(root: Path) -> List[Path]:
    """Every `ic/<IC>/` directory under a benchmark-data-ish root."""
    ic_root = root / "ic" if (root / "ic").is_dir() else root
    if not ic_root.is_dir():
        return []
    # An IC directory is one that carries the shared input/ or >= 1 subdirectory;
    # a loose file beside the IC folders is not an IC.
    return sorted(p for p in ic_root.iterdir() if p.is_dir())


def _discover_evidence_folders(root: Path) -> List[Path]:
    """Find every candidate evidence folder under a benchmark-data-ish root.

    A candidate is any child of an `ic/<IC>/` directory (except the shared
    `input/`) that either matches the v<ver>_<PDK> name OR contains a RESULT.md
    — so a MISNAMED publish (clean_run_*, pass_*) is discovered and FAILed,
    never silently skipped.
    """
    ic_root = root / "ic" if (root / "ic").is_dir() else root
    found: List[Path] = []
    if not ic_root.is_dir():
        return found
    for ic_dir in sorted(p for p in ic_root.iterdir() if p.is_dir()):
        for child in sorted(p for p in ic_dir.iterdir() if p.is_dir()):
            if child.name == "input":
                continue
            looks_versiony = bool(_NAME_RE.match(child.name)) or \
                any(child.name.startswith(pfx) for pfx in _BAD_PREFIXES)
            if looks_versiony or (child / "RESULT.md").is_file():
                found.append(child)
    return found


# --------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------

def _n_entries(n: int) -> str:
    return f"{n} published entr{'y' if n == 1 else 'ies'}"


def _print_folder(res: FolderResult) -> None:
    # SKIP is checked FIRST: `res.conforms` is None for a skipped unit, and the
    # `PASS if conforms else FAIL` ternary would have called it a FAIL — the
    # opposite over-statement to the one #967 is about, and just as wrong.
    tag = "SKIP" if res.skipped else ("PASS" if res.conforms else "FAIL")
    ident = res.path
    if res.kind == "ic-root":
        # A conforming IC-level unit now STATES ITS DENOMINATOR on its own line
        # (`gate_discloses_denominator_check`): "N/N conformant" is only
        # readable as coverage if each N says what it counted.
        suffix = ""
        if res.skipped:
            suffix = (f"  (IC={res.ic} IC-level layout: examined nothing — "
                      f"{_n_entries(res.examined or 0)}; NOT counted as a unit)")
        elif res.conforms and res.pre_existing:
            # NOT "all allowed" — this unit conforms because the entries that
            # are not allowed predate the change (vibe-ic#1538). Printing the
            # unqualified line here would be the escape being silent, which is
            # the reading this whole check exists to prevent.
            suffix = (f"  (IC={res.ic} IC-level layout: "
                      f"{_n_entries(res.examined or 0)} examined, "
                      f"{len(res.pre_existing)} pre-existing and recorded, "
                      f"0 added by this change)")
        elif res.conforms:
            suffix = (f"  (IC={res.ic} IC-level layout: "
                      f"{_n_entries(res.examined or 0)} examined, all allowed)")
        print(f"[{tag}] {ident}{suffix}")
    else:
        print(f"[{tag}] {ident}"
              + (f"  (IC={res.ic} PDK={res.pdk} v{res.version} verdict={res.verdict})"
                 if res.conforms else ""))
    # Notes print on PASS too — a rule that passed on a different basis is
    # exactly the thing a reader must be able to see, and only-on-failure
    # printing would hide it in the case that matters.
    for n in res.notes:
        print(f"    ~ {n}")
    if not res.conforms:
        for f in res.failures:
            print(f"    x {f}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Validate published benchmark-data evidence folder(s) "
                    "against the canonical converged-cell structure.")
    ap.add_argument("paths", nargs="*",
                    help="evidence folder(s) v<ver>_<PDK> to validate")
    ap.add_argument("--tree", metavar="ROOT", default=None,
                    help="discover + validate every published cell under ROOT "
                         "(e.g. benchmark-data or benchmark-data/ic). If "
                         f"${CORPUS_ENV} is set it OVERRIDES this, because the "
                         "published corpus now lives in its own repository.")
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="the caller asserts this repo need not carry the corpus. "
                         "Turns 'no corpus discoverable anywhere' from UNDETERMINED "
                         "into NO_CORPUS (rc=0). It does NOT excuse a corpus pointer "
                         f"that is set and broken: ${CORPUS_ENV} pointing at "
                         "something unreadable is UNDETERMINED with or without this.")
    ap.add_argument("--include-staged", action="store_true",
                    help="also treat git-staged (not-yet-committed) files as "
                         "committed for the NO_RAW_GEOMETRY scan")
    ap.add_argument("--changed-since", metavar="BASE", default=None,
                    help="only validate discovered folders with a file changed "
                         "since BASE (added/modified) — the CI diff-scoped shape; "
                         "pre-existing folders are grandfathered, and at the IC "
                         "level only entries this change CREATED fail (the ones "
                         "that predate BASE are recorded, not charged to it)")
    ap.add_argument("--json", metavar="OUT", default=None,
                    help="write a machine-readable summary JSON here")
    args = ap.parse_args(argv)

    # THE POINTER WINS OVER THE PATH. Both shipped call sites pass the literal
    # `--tree benchmark-data`, a relative path that no longer exists in this repo.
    # Rewriting both call sites instead would leave every OTHER caller — agents,
    # local runs, the benchmark-agent skill — still pointed at a directory that is
    # gone, and each would have to learn the new location separately.
    #
    # The override is announced, because a gate that silently scans a different
    # tree than the one named on its command line is how `--tree ../../../
    # benchmark-data` came to report "13/28 conformant" over 9 IC dirs while an
    # absolute path over the same tree found 8 failing and 93 entries (2026-08-11,
    # recorded above). Whatever this gate scanned, it says so.
    _env_tree = os.environ.get(CORPUS_ENV)
    if _env_tree and args.tree:
        print(f"note: {CORPUS_ENV} overrides --tree {args.tree} -> {_env_tree}",
              file=sys.stderr)
        args.tree = _env_tree
    elif _env_tree and not args.tree and not args.paths:
        print(f"note: scanning {CORPUS_ENV} -> {_env_tree}", file=sys.stderr)
        args.tree = _env_tree

    targets: List[Path] = [Path(p) for p in args.paths]
    ic_dirs: List[Path] = []
    if args.tree:
        targets.extend(_discover_evidence_folders(Path(args.tree)))
        # The IC directories themselves. Only --tree walks these: a caller who
        # names one cell is asking about that cell, not about its siblings.
        ic_dirs = _discover_ic_dirs(Path(args.tree))

    if not targets and not ic_dirs:
        # DISCOVERING NOTHING BECAUSE THE TREE IS NOT THERE IS NOT A CLEAN RESULT
        # (vibe-ic#1254). `--tree benchmark-data` is a RELATIVE path, so a caller
        # whose cwd is not the repo root discovers zero folders and, before this,
        # exited 0 -- the gate reported clean over a tree it never found. The
        # pre-push hook invokes it exactly that way, which is where it matters:
        # the enforced gate on what reaches the remote.
        #
        # An EMPTY-but-present tree still returns 0 below: that is a real
        # determination ("I looked, there is nothing"), and collapsing it into
        # this branch would be the same error in the other direction.
        if args.tree and not Path(args.tree).is_dir():
            # THREE OUTCOMES, AND COLLAPSING ANY TWO OF THEM IS THE DEFECT.
            #
            #  pointer SET and broken      -> UNDETERMINED. Somebody said where the
            #                                 corpus is and was wrong. Never excused.
            #  nothing set, none local,
            #    caller says it may live
            #    elsewhere                 -> NO_CORPUS (rc=0). Nothing to scan, and
            #                                 nothing is claimed to have been scanned.
            #  nothing set, none local,
            #    nobody said that          -> UNDETERMINED. Unchanged: an absent tree
            #                                 in a repo meant to carry one is exactly
            #                                 what this branch was written for.
            env_tree = os.environ.get(CORPUS_ENV)
            if env_tree:
                print(f"UNDETERMINED: {CORPUS_ENV}={env_tree} is set and did not "
                      f"resolve to a readable corpus, so this gate discovered "
                      f"nothing and scanned nothing. A pointer that is set and "
                      f"wrong is a broken configuration, not an absent corpus.",
                      file=sys.stderr)
                return 2
            if args.corpus_may_be_absent:
                print(f"NO_CORPUS: nothing at {args.tree} and {CORPUS_ENV} is "
                      f"unset. The published corpus lives in its own repository and "
                      f"this repo is not required to carry it. NOTHING WAS SCANNED "
                      f"and nothing is claimed — point {CORPUS_ENV} at a clone to "
                      f"make this gate check something.", file=sys.stderr)
                return 0
            print(f"UNDETERMINED: --tree {args.tree} is not a directory, so this "
                  f"gate discovered nothing and scanned nothing. A check that "
                  f"could not look has not passed.", file=sys.stderr)
            return 2
        if args.changed_since:
            print(f"benchmark_evidence_structure_check: no evidence folders "
                  f"discovered (nothing to diff against {args.changed_since}).")
            return 0
        print("ERROR: no evidence folders to check "
              "(pass a folder path or --tree ROOT).", file=sys.stderr)
        return 2

    if args.changed_since:
        kept, mode = _changed_evidence_roots(args.changed_since, targets)
        if kept is None:
            # FAIL-OPEN IN AN ENFORCED GATE IS A LICENCE, NOT A DISCLOSURE
            # (vibe-ic#1254). The old text said "checking nothing (fail-open)"
            # and then exited 0, so the sentence was honest and the exit code
            # was not -- and only the exit code is read by the pre-push hook,
            # by CI, and by every caller that branches on rc. The stated reason
            # for the fail-open was that CI plumbing must not become a flaky
            # blocker; rc 2 keeps that promise honestly, because the hook
            # renders 2 as `NOT CHECKED - the gate could not run` rather than
            # as a finding against the change, which is exactly the
            # distinction it was written to draw.
            print(f"UNDETERMINED: benchmark_evidence_structure_check could not "
                  f"determine the change set ({mode}), so it scanned NOTHING. "
                  f"This is not a pass.", file=sys.stderr)
            return 2
        kept_ic, _ = _changed_ic_dirs(args.changed_since, ic_dirs,
                                      args.include_staged)
        ic_dirs = kept_ic or []
        if not kept and not ic_dirs:
            print(f"benchmark_evidence_structure_check: no evidence folders "
                  f"changed since {args.changed_since} — nothing to enforce.")
            return 0
        targets = kept

    results: List[FolderResult] = []
    for ic in ic_dirs:
        pre_names: Optional[Set[str]] = None
        baseline_mode = ""
        if args.changed_since:
            # vibe-ic#1538 — read the register of entries that predate this
            # change. An unreadable baseline grandfathers NOTHING (the strict
            # direction) and says why, rather than quietly widening the escape.
            pre_names, baseline_mode = ic_level_entry_names_at(
                args.changed_since, ic)
            if pre_names is None:
                pre_names = set()
                baseline_mode = (f"NO baseline — it could not be read "
                                 f"({baseline_mode}), so nothing was "
                                 f"grandfathered")
        results.append(check_ic_level_layout(
            ic, include_staged=args.include_staged,
            pre_existing_names=pre_names, baseline_mode=baseline_mode))
    for t in targets:
        if not t.exists():
            r = FolderResult(path=str(t))
            r.fail("PATH", "does not exist")
            results.append(r)
            continue
        if not t.is_dir():
            r = FolderResult(path=str(t))
            r.fail("PATH", "not a directory")
            results.append(r)
            continue
        results.append(check_folder(t, include_staged=args.include_staged))

    for r in results:
        _print_folder(r)

    # #967 — the printed count is the count ACTUALLY EXAMINED. A unit whose
    # denominator was zero is in neither the numerator nor the denominator, and
    # is disclosed on its own instead of being absorbed into "N/N conformant".
    examined = [r for r in results if not r.skipped]
    skipped = [r for r in results if r.skipped]
    passed = sum(1 for r in examined if r.conforms)
    failed = len(examined) - passed
    tail = ""
    if skipped:
        tail = (f", {len(skipped)} skipped (examined nothing: "
                + "; ".join(f"{r.ic or Path(r.path).name}={_n_entries(r.examined or 0)}"
                            for r in skipped)
                + ") — counted as neither conformant nor nonconformant")
    # THE FRACTION DOES NOT SAY WHAT IT COUNTED, and over this corpus the two
    # possible answers differ by every published cell in the repository.
    # MEASURED on `vibeic/benchmark-data`, `--tree` at two commits:
    #
    #     146d665 (pre-withdrawal)  kinds {ic-root: 9, cell: 4}  "13/13 conformant"
    #     3b58ccd42 (today)         kinds {ic-root: 9, cell: 0}   "9/9 conformant"
    #
    # Both lines are TRUE and neither states the cell count, so a reader of the
    # CI log gets the same sentence shape from a corpus with four published
    # cells and from a corpus with none. The per-unit rows and `--json` already
    # separate them (`kind`); the ROLL-UP did not, and the roll-up is what a
    # reader takes the impression from.
    #
    # THE CELL COUNT IS PRINTED EVEN WHEN IT IS ZERO, and especially then: a
    # clause that appears only when there are cells would leave the empty corpus
    # with exactly the silence this discloses. Every other kind is derived from
    # the results rather than named here, so a kind added later cannot fall out
    # of the line without anyone noticing.
    by_kind = Counter(r.kind for r in examined)
    cells = by_kind.pop("cell", 0)
    others = ", ".join(f"{n} {_KIND_LABEL.get(k, k)}(s)"
                       for k, n in sorted(by_kind.items()))
    population = (f" — over {cells} published cell(s)"
                  + (f" and {others}" if others else ""))
    print(f"\nbenchmark_evidence_structure_check: "
          f"{passed}/{len(examined)} conformant, {failed} nonconformant"
          f"{tail}{population}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {"checked": len(examined),
                 "conformant": passed,
                 "nonconformant": failed,
                 "skipped_examined_nothing": len(skipped),
                 "discovered": len(results),
                 "folders": [asdict(r) for r in results]},
                indent=2),
            encoding="utf-8")

    if not examined:
        # Every discovered unit examined nothing. `gate_zero_denominator_refuses
        # _check`: "the gate states it read NOTHING and still exits 0 ... Either
        # make it refuse (rc 2 is the disclosed-skip convention)". This restores
        # the pre-#952 refusal at the level where the hole actually opened.
        if args.changed_since:
            # Grandfathering already answers rc 0 with a disclosure, and that is
            # the shape every push runs. Not widened, not narrowed.
            print(f"benchmark_evidence_structure_check: nothing changed since "
                  f"{args.changed_since} that published anything — "
                  f"nothing to enforce.")
            return 0
        print(f"ERROR: nothing was examined — {len(skipped)} IC director"
              f"{'y' if len(skipped) == 1 else 'ies'} discovered and every one "
              f"published nothing (no input/, no v<ver>_<PDK> cell, no entry of "
              f"any kind), and no evidence folder was found. A unit that "
              f"examined nothing is not a unit that passed, so this is a "
              f"refusal rather than a tally of {len(skipped)} conformant "
              f"unit(s). (The N/N form is deliberately not printed here: a "
              f"reader — or a grep — must not be able to lift a coverage "
              f"number out of a run that covered nothing.)",
              file=sys.stderr)
        return 2

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
