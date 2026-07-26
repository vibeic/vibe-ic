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

LAYOUT ARTEFACTS ARE ROUTED BY SIZE, NOT BY EXTENSION (#419). *.gds, *.def,
*.spef and *.oas under 50 MB are STAGED; above it they are skipped and the
GDS_MANIFEST carries the sha256 so the artefact stays verifiable without being
stored. The manifest is emitted either way.

  This paragraph used to declare these four extensions excluded as a matter
  of construction, on the grounds that they were gitignored or too large, and
  both halves had stopped being true. `.gitignore` negates
  `.gds`/`.def` back for `benchmark-data/ic/**`, and `.spef`/`.oas` were never
  ignored at all. "Too large" is a property of the FILE: this project's own
  GDS range from 0.73 MB (spm) to 105 MB (sha256). Dropping by extension threw
  away the small artefact a reviewer wants in order to avoid the large one
  nobody can commit — so a cell published by this program carried LESS
  evidence than the hand-staged cells it replaced.

Raw PnR scratch under phase3/stage3 and the per-step scratch (steps/) are
still not staged: that is a decision about what counts as evidence, which is
separate from how big a file is.

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

def _excluded(p: Path) -> bool:
    """A layout artefact is excluded only when it is TOO BIG to commit.

    #419. The predicate used to be `suffix in _RAW_EXTS` — an extension test
    standing in for a size test. Everything else is copied as before; a
    layout artefact under the ceiling now ships, and one over it is skipped
    for the reason that is actually true of it.
    """
    if p.suffix.lower() not in _LAYOUT_EXTS:
        return False
    try:
        return p.stat().st_size > _SIZE_CEILING
    except OSError:
        # Unreadable size is not evidence of smallness. Skip and let the
        # manifest carry what is known, rather than copying blind.
        return True


def _copy_tree(src: Path, dst: Path, dry: bool) -> Tuple[int, int]:
    """Copy every non-excluded regular file under src into dst (preserving
    relative layout). Returns (files_copied, files_excluded)."""
    copied = excluded = 0
    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue
        if _excluded(f):
            excluded += 1
            continue
        rel = f.relative_to(src)
        target = dst / rel
        if not dry:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
        copied += 1
    return copied, excluded


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


def _write_manifest(gds_files: List[Path], dst_gds_dir: Path, dry: bool) -> str:
    lines = [f"{g.name} {g.stat().st_size}B sha256:{_sha256(g)}" for g in gds_files]
    body = "\n".join(lines) + "\n"
    if not dry:
        dst_gds_dir.mkdir(parents=True, exist_ok=True)
        (dst_gds_dir / "GDS_MANIFEST.txt").write_text(body, encoding="utf-8")
    return "; ".join(lines)


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
    excluded_total = 0

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
        c, e = _copy_tree(src, dest / sub, dry)
        excluded_total += e
        if c:
            staged.append(f"{sub}/ ({c} files)")

    # GDS_MANIFEST
    manifest_line = _write_manifest(gds_files, dest / "phase3" / "stage4" / "gds", dry)
    staged.append("phase3/stage4/gds/GDS_MANIFEST.txt")

    # shared design input (staged once per IC)
    shared_input = ic_root / "input"
    input_result = _stage_shared_input(run_dir, args, shared_input, dry)

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
                        shared_input: Path, dry: bool) -> str:
    """Copy the design-input docs to ic/<IC>/input/ once. Non-fatal: on a 2nd/3rd
    PDK for the same IC the shared input already exists and is left untouched."""
    if shared_input.is_dir() and any(shared_input.iterdir()) and not args.force:
        return f"kept existing {shared_input}"
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
        return "no design-input docs found to stage (shared input unchanged)"
    dst = shared_input / "docs"
    c, _ = _copy_tree(src, dst, dry)
    return f"staged {c} input doc(s) -> {dst}"


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
    print(f"  excluded raw: {summary['excluded_raw_files']} *.gds/*.def/*.spef/*.oas file(s)")
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
