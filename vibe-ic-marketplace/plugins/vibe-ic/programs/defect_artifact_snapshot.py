#!/usr/bin/env python3
"""programs/defect_artifact_snapshot.py — v0.2.98

Filing-side helper for the field-agent / community-backlog filing flow
(issue #487, LOW).

WHY THIS EXISTS
---------------
Backlog issues cite LIVE run-dir files as the defect evidence ("the
truncated report at <run>/reports/foo.rpt"). But run directories EVOLVE
between filing and verification: a healthy rerun can replace the very file
that was cited as the defect, so by the time the field agent's
acceptance/audit pass dereferences the path, the defect artifact is gone
and the verdict silently binds to mutable state.

This program is the fix at FILING TIME. Given an issue number/slug and a
list of artifact paths, it copies each artifact, byte-for-byte, into an
IMMUTABLE capture archive and writes a manifest.json recording, for each
member:

  * the original (live) source path,
  * a sha256 of the captured bytes,
  * the source file's mtime taken from the filesystem at capture time,
  * the issue reference (number/slug).

The agent then pastes BOTH the snapshot path and the live path into the
issue's 證據區 (evidence section), so the downstream
`defect_artifact_fixture_check` can prefer the frozen snapshot over the
mutable live file.

ARCHIVE CONVENTION
------------------
No pre-existing on-disk "session capture" archive convention was found in
this repo (only the run-time provenance log + scope/device capture tools,
which are unrelated). This program therefore DEFINES the convention the
issue specifies:

    <repo-root>/community/captures/<slug>/

where <slug> is the sanitized issue slug (and, when an issue number is
given, prefixed so the directory is greppable by issue). Inside the
archive directory:

    <slug>/
        <basename-of-each-captured-artifact>   (immutable copy)
        manifest.json                          (provenance below)

`<repo-root>` is discovered by walking up from this file until a directory
containing `community/` is found; falling back to four parents up
(programs → vibe-ic → plugins → vibe-ic-marketplace → repo-root).

MANIFEST SCHEMA (manifest.json)
-------------------------------
{
  "issue_ref": "#487"  | "487"  | "<slug>",
  "issue_number": 487 | null,
  "slug": "<sanitized-slug>",
  "captured_at": "<ISO-8601 UTC>",
  "archive_dir": "<absolute path to the capture dir>",
  "artifacts": [
    {
      "source_path": "<absolute live path at capture time>",
      "snapshot_path": "<absolute immutable copy path>",
      "snapshot_rel": "community/captures/<slug>/<basename>",
      "basename": "<basename>",
      "sha256": "sha256:<hex>",        # of the CAPTURED bytes
      "source_mtime": "<ISO-8601 UTC>",# fs mtime of the source at capture
      "source_mtime_epoch": <float>,
      "size_bytes": <int>
    },
    ...
  ]
}

OUTPUT (for pasting into the issue 證據區)
-----------------------------------------
Human output prints, per artifact, BOTH the snapshot path and the live
path in a paste-ready form, e.g.:

    snapshot: community/captures/issue-487-truncated-report/foo.rpt
    live:     /abs/run/reports/foo.rpt

`--json` writes the full manifest-shaped verdict report.

EXIT CODES
----------
  0  PASS  — every named artifact was captured into the archive and the
            manifest was written.
  1  FAIL  — at least one named artifact could not be captured (missing
            source / unreadable / write error); partial captures are
            recorded but the run is a FAIL so the filer notices.
  2  usage — bad args (no slug/issue, no artifacts).

chip-AGNOSTIC: nothing here depends on any chip / vendor / SKU literal.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


# --------------------------------------------------------------------------
# Archive-home discovery
# --------------------------------------------------------------------------
def find_repo_root(start: Optional[Path] = None) -> Path:
    """Walk up from `start` (default: this file) to the canonical repo root.

    Preference order:
      1. the ancestor that has BOTH a `.git` and a `community/` dir (the
         true git-toplevel repo root — the marketplace mirror lacks `.git`),
      2. the first ancestor with a `community/` dir,
      3. four parents up (programs → vibe-ic → plugins →
         vibe-ic-marketplace → repo-root).
    """
    here = (start or Path(__file__)).resolve()
    first_community: Optional[Path] = None
    for anc in here.parents:
        has_community = (anc / "community").is_dir()
        if has_community and first_community is None:
            first_community = anc
        if has_community and (anc / ".git").exists():
            return anc
    if first_community is not None:
        return first_community
    parents = here.parents
    return parents[4] if len(parents) > 4 else parents[-1]


def captures_root(repo_root: Optional[Path] = None) -> Path:
    root = repo_root or find_repo_root()
    return root / "community" / "captures"


# --------------------------------------------------------------------------
# Slug / issue-ref handling
# --------------------------------------------------------------------------
_SLUG_CLEAN_RE = re.compile(r"[^a-z0-9]+")


def sanitize_slug(raw: str) -> str:
    s = _SLUG_CLEAN_RE.sub("-", raw.strip().lower()).strip("-")
    return s or "untitled"


def derive_dir_slug(issue_number: Optional[int], slug: Optional[str]) -> str:
    """Greppable archive directory name. When an issue number is supplied,
    prefix the slug with `issue-<n>-` so the archive is locatable by issue."""
    base = sanitize_slug(slug) if slug else ""
    if issue_number is not None:
        prefix = f"issue-{issue_number}"
        if base and not base.startswith(prefix):
            return f"{prefix}-{base}"
        return base or prefix
    return base or "untitled"


def issue_ref_string(issue_number: Optional[int], slug: Optional[str]) -> str:
    if issue_number is not None:
        return f"#{issue_number}"
    return slug or "untitled"


# --------------------------------------------------------------------------
# Hash / time helpers (match provenance_logger conventions)
# --------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _utc_iso_from_epoch(epoch: float) -> str:
    return (_dt.datetime.fromtimestamp(epoch, _dt.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"))


def _utcnow_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# Snapshot core
# --------------------------------------------------------------------------
@dataclass
class ArtifactRecord:
    source_path: str
    snapshot_path: str = ""
    snapshot_rel: str = ""
    basename: str = ""
    sha256: str = ""
    source_mtime: str = ""
    source_mtime_epoch: float = 0.0
    size_bytes: int = 0
    captured: bool = False
    error: str = ""


@dataclass
class SnapshotResult:
    verdict: str                       # PASS | FAIL
    issue_ref: str
    issue_number: Optional[int]
    slug: str
    archive_dir: str
    captured_at: str
    artifacts: List[ArtifactRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _unique_basename(dest_dir: Path, src: Path, taken: set) -> str:
    """Avoid clobbering when two source artifacts share a basename."""
    base = src.name or "artifact"
    if base not in taken:
        return base
    stem = src.stem or "artifact"
    suffix = src.suffix
    i = 1
    while True:
        cand = f"{stem}.{i}{suffix}"
        if cand not in taken:
            return cand
        i += 1


def snapshot_artifacts(
    artifact_paths: List[str],
    issue_number: Optional[int],
    slug: Optional[str],
    repo_root: Optional[Path] = None,
) -> SnapshotResult:
    root = (repo_root.resolve() if repo_root else find_repo_root())
    dir_slug = derive_dir_slug(issue_number, slug)
    archive_dir = captures_root(root) / dir_slug
    archive_dir.mkdir(parents=True, exist_ok=True)
    iref = issue_ref_string(issue_number, slug)
    captured_at = _utcnow_iso()

    records: List[ArtifactRecord] = []
    errors: List[str] = []
    taken: set = set()
    # Pre-reserve already-present member names so re-runs are idempotent and
    # don't collide with a manifest written earlier.
    for existing in archive_dir.iterdir() if archive_dir.is_dir() else []:
        if existing.name != "manifest.json":
            taken.add(existing.name)

    for raw in artifact_paths:
        rec = ArtifactRecord(source_path=str(Path(raw)))
        src = Path(raw)
        try:
            if not src.exists():
                rec.error = "source not found"
                errors.append(f"{raw}: source not found")
                records.append(rec)
                continue
            if not src.is_file():
                rec.error = "source is not a regular file"
                errors.append(f"{raw}: source is not a regular file")
                records.append(rec)
                continue
            src_abs = src.resolve()
            rec.source_path = str(src_abs)
            st = src.stat()
            base = _unique_basename(archive_dir, src, taken)
            taken.add(base)
            dest = archive_dir / base
            # Copy bytes (immutable snapshot). copy2 preserves source mtime
            # on the copy too, but the manifest is the source of truth.
            shutil.copy2(str(src), str(dest))
            rec.basename = base
            rec.snapshot_path = str(dest.resolve())
            try:
                rec.snapshot_rel = str(dest.resolve().relative_to(root))
            except ValueError:
                rec.snapshot_rel = str(dest)
            rec.sha256 = sha256_file(dest)
            rec.source_mtime_epoch = st.st_mtime
            rec.source_mtime = _utc_iso_from_epoch(st.st_mtime)
            rec.size_bytes = st.st_size
            rec.captured = True
        except OSError as exc:
            rec.error = f"capture error: {exc}"
            errors.append(f"{raw}: {exc}")
        records.append(rec)

    verdict = "PASS" if records and all(r.captured for r in records) \
        else "FAIL"
    result = SnapshotResult(
        verdict=verdict,
        issue_ref=iref,
        issue_number=issue_number,
        slug=dir_slug,
        archive_dir=str(archive_dir.resolve()),
        captured_at=captured_at,
        artifacts=records,
        errors=errors,
    )

    # Write the manifest (records the captured set, including failures so
    # the filer sees what is missing). Only members that captured are
    # listed under "artifacts"; failures are echoed under "errors".
    _write_manifest(archive_dir, result)
    return result


def _write_manifest(archive_dir: Path, result: SnapshotResult) -> None:
    manifest = {
        "issue_ref": result.issue_ref,
        "issue_number": result.issue_number,
        "slug": result.slug,
        "captured_at": result.captured_at,
        "archive_dir": result.archive_dir,
        "artifacts": [
            {
                "source_path": r.source_path,
                "snapshot_path": r.snapshot_path,
                "snapshot_rel": r.snapshot_rel,
                "basename": r.basename,
                "sha256": r.sha256,
                "source_mtime": r.source_mtime,
                "source_mtime_epoch": r.source_mtime_epoch,
                "size_bytes": r.size_bytes,
            }
            for r in result.artifacts if r.captured
        ],
        "errors": result.errors,
    }
    (archive_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _format_paste_block(result: SnapshotResult) -> str:
    lines: List[str] = []
    lines.append(f"# defect-artifact snapshot for {result.issue_ref}")
    lines.append(f"# archive: {result.archive_dir}")
    lines.append("")
    for r in result.artifacts:
        if r.captured:
            lines.append(f"snapshot: {r.snapshot_rel or r.snapshot_path}")
            lines.append(f"live:     {r.source_path}")
            lines.append(f"sha256:   {r.sha256}")
            lines.append(f"mtime:    {r.source_mtime}")
            lines.append("")
        else:
            lines.append(f"MISSING:  {r.source_path}  ({r.error})")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Freeze the LIVE run-dir artifacts a backlog issue "
                    "cites as defect evidence into an immutable capture "
                    "archive, and print both the snapshot path and the "
                    "live path for pasting into the issue 證據區.")
    ap.add_argument("--issue", type=int, default=None,
                    help="issue number (e.g. 487)")
    ap.add_argument("--slug", default=None,
                    help="short slug for the archive dir (e.g. "
                         "truncated-report-snapshot); required if --issue "
                         "is omitted")
    ap.add_argument("--artifact", action="append", default=[],
                    metavar="PATH",
                    help="a live artifact path to snapshot (repeatable)")
    ap.add_argument("--json", default=None,
                    help="write a JSON manifest-shaped verdict report here")
    ap.add_argument("--repo-root", default=None,
                    help="repo root under which the "
                         "community/captures/<slug>/ archive is written "
                         "(default: auto-discover)")
    args = ap.parse_args(argv)

    if args.issue is None and not args.slug:
        print("ERROR: provide --issue and/or --slug", file=sys.stderr)
        return 2
    if not args.artifact:
        print("ERROR: provide at least one --artifact PATH", file=sys.stderr)
        return 2

    result = snapshot_artifacts(
        artifact_paths=args.artifact,
        issue_number=args.issue,
        slug=args.slug,
        repo_root=Path(args.repo_root) if args.repo_root else None,
    )

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(asdict(result), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")

    # Human paste-ready output (snapshot + live per artifact).
    sys.stdout.write(_format_paste_block(result))

    if result.verdict == "PASS":
        print(f"\nPASS: {len(result.artifacts)} artifact(s) frozen into "
              f"{result.archive_dir}")
        return 0

    print(f"\nFAIL: {len(result.errors)} artifact(s) could not be "
          f"captured:", file=sys.stderr)
    for e in result.errors:
        print(f"  - {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
