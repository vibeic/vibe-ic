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
  IC_LEVEL_LAYOUT   nothing sits directly under `ic/<IC>/` except `input/` and
                    `v<major>.<minor>.<patch>_<PDK>/` cells (#905). Run output
                    left at that level is attributable to no plugin version and
                    no PDK. Reported, never repaired: where such a folder
                    belongs — and whether it may be retired at all — is a
                    maintainer's decision about published evidence, not a
                    gate's.
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
    0  every checked folder CONFORMS
    1  at least one folder is NONCONFORMANT
    2  usage / I/O error (nothing meaningful was checked)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# --------------------------------------------------------------------------
# Contract constants (structure, not chips).
# --------------------------------------------------------------------------

# `v<major>.<minor>.<patch>_<PDK>` — version FIRST, then a non-empty PDK tag.
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


@dataclass
class FolderResult:
    path: str
    ic: Optional[str] = None
    pdk: Optional[str] = None
    version: Optional[str] = None
    verdict: Optional[str] = None
    conforms: bool = True
    failures: List[str] = field(default_factory=list)   # "RULE: message"
    checks: Dict[str, bool] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)     # "RULE: why it passed differently"

    def fail(self, rule: str, msg: str) -> None:
        self.conforms = False
        self.failures.append(f"{rule}: {msg}")
        self.checks[rule] = False

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
    """Absolute paths of git-tracked (and optionally staged) files under folder."""
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

def _changed_evidence_roots(base: str, targets: List[Path]) -> Tuple[Optional[List[Path]], str]:
    """Filter `targets` to the evidence folders that have >= 1 file changed since
    `base` (added/modified; deletions ignored). Returns (kept, mode).

    `kept is None` signals "could not determine the change set" — the caller
    fail-OPENS (checks nothing, exits 0) so CI plumbing never becomes a flaky
    blocker; the real guards are the per-folder rules + the publish self-check.
    """
    anchor = targets[0] if targets else Path.cwd()
    repo = _git_toplevel(anchor if anchor.exists() else Path.cwd())
    if repo is None:
        return None, "not a git repo"
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "diff", "--name-only", "--diff-filter=d",
             f"{base}...HEAD"],
            capture_output=True, text=True, check=False)
        if out.returncode != 0:
            # fall back to a two-dot diff (base not an ancestor / shallow clone)
            out = subprocess.run(
                ["git", "-C", str(repo), "diff", "--name-only", "--diff-filter=d",
                 base, "HEAD"],
                capture_output=True, text=True, check=False)
        if out.returncode != 0:
            return None, f"git diff against {base} failed"
    except Exception as exc:
        return None, f"git diff error: {exc}"
    changed = {(repo / ln.strip()).resolve() for ln in out.stdout.splitlines() if ln.strip()}
    kept = [t for t in targets
            if any(str(c).startswith(str(t.resolve()) + os.sep) or c == t.resolve()
                   for c in changed)]
    return kept, f"changed-since {base}"


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


def _discover_ic_level_strays(root: Path,
                              discovered: List[Path]) -> List[Path]:
    """Every DIRECTORY directly under `ic/<IC>/` the contract does not admit
    and that `_discover_evidence_folders` never looked at (vibe-ic#905).

    `benchmark-data/ic/<IC>/` admits exactly two kinds of entry: the shared
    `input/`, and one `v<major>.<minor>.<patch>_<PDK>/` per converged
    (version x PDK) cell. Anything else at that level is run output
    attributable to no plugin version and no PDK.

    THE DISCOVERY ABOVE CANNOT SEE THOSE. It admits a child only when the name
    LOOKS versiony (`v<ver>_<PDK>`, or one of the known-wrong prefixes) or the
    child carries a `RESULT.md`. A bare `phase1/`, `reports/` or `sim/`
    matches neither, so the gate that OWNS this contract has been grading the
    cells while saying nothing about the strays sitting beside them — a gate
    silent about the exact violation it is named for.

    MEASURED on this repo's published corpus at the commit this rule landed
    on: `_discover_evidence_folders` saw 19 folders across 9 IC directories;
    48 stray directories across 8 of those 9 were invisible to it. #905 named
    3 of the 48.

    Entries already returned by `_discover_evidence_folders` are excluded, so
    a misnamed cell is reported ONCE — by NAMING, with its specific message —
    and never twice.

    FILES at the IC level are deliberately OUT OF SCOPE. Several ICs carry a
    top-level `RESULT.md` / `provenance.jsonl` / `SOURCE_MANIFEST.md`, and
    whether those are part of the contract or violations of it has not been
    measured here. A rule that reported them would be asserting something this
    change did not check.
    """
    ic_root = root / "ic" if (root / "ic").is_dir() else root
    seen = {p.resolve() for p in discovered}
    strays: List[Path] = []
    if not ic_root.is_dir():
        return strays
    for ic_dir in sorted(p for p in ic_root.iterdir() if p.is_dir()):
        for child in sorted(p for p in ic_dir.iterdir() if p.is_dir()):
            if child.name == "input" or _NAME_RE.match(child.name):
                continue
            if child.resolve() in seen:
                continue
            strays.append(child)
    return strays


def check_ic_level_stray(stray: Path) -> FolderResult:
    """One named nonconformance for a stray directory at the IC level.

    REPORTS, does not repair. Deleting a published run makes "we never ran
    this" and "we ran it, it failed, and we kept the record" the same state;
    moving one re-attributes its output to a version that did not produce it.
    Both are decisions about published evidence that belong to a maintainer.
    The gate's job is that neither can be taken by accident, or missed.
    """
    res = FolderResult(path=str(stray.resolve()))
    parent = stray.parent
    if parent.parent.name == "ic":
        res.ic = parent.name
    res.fail("IC_LEVEL_LAYOUT",
             f"'{stray.name}/' sits directly under ic/{res.ic or '<IC>'}/, where "
             f"the contract admits only `input/` and "
             f"`v<major>.<minor>.<patch>_<PDK>/`. Output here is attributable "
             f"to no plugin version and no PDK. Move it into the versioned "
             f"cell whose run produced it, or record why it is kept — this "
             f"gate reports the divergence, it does not decide its fate.")
    return res


# --------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------

def _print_folder(res: FolderResult) -> None:
    tag = "PASS" if res.conforms else "FAIL"
    ident = res.path
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
                         "(e.g. benchmark-data or benchmark-data/ic)")
    ap.add_argument("--include-staged", action="store_true",
                    help="also treat git-staged (not-yet-committed) files as "
                         "committed for the NO_RAW_GEOMETRY scan")
    ap.add_argument("--changed-since", metavar="BASE", default=None,
                    help="only validate discovered folders with a file changed "
                         "since BASE (added/modified) — the CI diff-scoped shape; "
                         "pre-existing folders are grandfathered")
    ap.add_argument("--json", metavar="OUT", default=None,
                    help="write a machine-readable summary JSON here")
    args = ap.parse_args(argv)

    targets: List[Path] = [Path(p) for p in args.paths]
    # IC-level strays (#905) are carried SEPARATELY from `targets`: they are not
    # candidate cells, so `check_folder`'s per-cell rules would grade them
    # against a structure they were never meant to have.
    strays: List[Path] = []
    if args.tree:
        discovered = _discover_evidence_folders(Path(args.tree))
        targets.extend(discovered)
        strays = _discover_ic_level_strays(Path(args.tree), discovered)

    if not targets and not strays:
        if args.changed_since:
            print(f"benchmark_evidence_structure_check: no evidence folders "
                  f"discovered (nothing to diff against {args.changed_since}).")
            return 0
        print("ERROR: no evidence folders to check "
              "(pass a folder path or --tree ROOT).", file=sys.stderr)
        return 2

    if args.changed_since:
        # Strays are diff-scoped by the SAME rule as cells: a pre-existing one
        # is grandfathered, so landing this rule cannot retroactively fail a PR
        # that did not touch it. It fires exactly when a push adds or edits
        # output at the IC level, which is the point at which it is cheap.
        kept, mode = _changed_evidence_roots(args.changed_since, targets + strays)
        if kept is None:
            print(f"benchmark_evidence_structure_check: change set undeterminable "
                  f"({mode}); checking nothing (fail-open).")
            return 0
        if not kept:
            print(f"benchmark_evidence_structure_check: no evidence folders "
                  f"changed since {args.changed_since} — nothing to enforce.")
            return 0
        kept_set = {p.resolve() for p in kept}
        stray_set = {p.resolve() for p in strays}
        targets = [t for t in kept if t.resolve() not in stray_set]
        strays = [s for s in strays if s.resolve() in kept_set]

    results: List[FolderResult] = []
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

    for s in strays:
        results.append(check_ic_level_stray(s))

    for r in results:
        _print_folder(r)

    passed = sum(1 for r in results if r.conforms)
    failed = len(results) - passed
    print(f"\nbenchmark_evidence_structure_check: "
          f"{passed}/{len(results)} conformant, {failed} nonconformant")

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {"checked": len(results),
                 "conformant": passed,
                 "nonconformant": failed,
                 "folders": [asdict(r) for r in results]},
                indent=2),
            encoding="utf-8")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
