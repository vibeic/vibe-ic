#!/usr/bin/env python3
"""
provenance_output_hash_completeness_check.py — verify that
`<project>/provenance.jsonl` carries a complete, on-disk-verifiable
hash chain of every tool invocation's outputs.

Per the v1.6.30 anti-fabrication doctrine (rule #2): "Provenance
entries carry SHA256 of every output. Synthetic timestamps will be
flagged. Empty is honest; fabricated is dishonest."

Backlog reference:
  ORGANIC-20260508-provenance-output-hash-completeness.yaml (P1)

Failure modes
-------------
1. PROVENANCE_OUTPUTS_MISSING — entry has no `outputs` key, or it's
   empty. The audit cannot tie this tool invocation to any artefact.
2. PROVENANCE_HASH_SHAPE_INVALID — an output value is not a
   `sha256:<64-hex>` string. Audit chain unreadable.
3. PROVENANCE_OUTPUT_FILE_MISSING — the declared output path does
   not exist on disk. Tool claimed to produce something it didn't.
4. PROVENANCE_HASH_MISMATCH — declared SHA256 does not match the
   on-disk file. Output was tampered or claim is fabricated.
5. PROVENANCE_PATH_OUTSIDE_PROJECT (v1.6.32) — declared output path
   resolves outside the project root (absolute path or `..` traversal).
   Audit chain only attests artefacts owned by the project; outside
   paths can be fabricated externally.
6. PROVENANCE_HASH_INCONSISTENT (v1.6.32) — same output path appears
   in two entries with different declared hashes. The audit chain
   contradicts itself; one of the two is wrong.
7. ATTEST_TIMING_SUSPICIOUS (WARNING, not FAIL) — entry timestamps
   exhibit synthetic patterns. v1.6.32 widened the heuristic beyond
   "all on :00 seconds" to also catch:
     * all entries on `:NN:00` minute boundaries with second jitter
       (e.g. 10:01:00, 10:05:00, 10:11:00);
     * monotonic gaps that are exact multiples of 60 / 300 / 600s
       and ≥3 such regular gaps in a row.
   `--strict-timing` upgrades to ERROR.

VACUOUS_PASS
------------
* `<project>/provenance.jsonl` does not exist. Audit chain has not
  been established yet (legitimate for early-stage projects). The
  wider canonical-flow audit catches missing-provenance via other
  presence gates if it's required at the project's phase.

* `<project>/provenance.jsonl` exists but is empty. Same rationale.

Usage
-----
    python3 provenance_output_hash_completeness_check.py <project_dir>
                                                          [--json <out>]
                                                          [--strict-timing]
                                                          [--max-entries N]

Exit codes
    0  PASS / VACUOUS_PASS
    1  one or more entries fail completeness or hash verification
    2  argument or I/O error

chip-AGNOSTIC. No vendor / IC / specific tool name hardcoded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


_RE_SHA256 = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
_RE_TIMESTAMP_SECONDS = re.compile(r"T\d{2}:\d{2}:(\d{2})")
_RE_TIMESTAMP_HMS = re.compile(
    r"T(?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})(?:\.(?P<frac>\d+))?")


@dataclass
class ProvenanceFinding:
    entry_index: int
    tool: str
    rule: str
    detail: str
    severity: str = "ERROR"   # ERROR / WARNING


def _file_sha256(path: Path, max_bytes: Optional[int] = None) -> str:
    """Compute lowercase hex sha256 of `path`. Reads in 1 MiB chunks."""
    h = hashlib.sha256()
    read = 0
    chunk = 1 << 20  # 1 MiB
    with path.open("rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
            read += len(buf)
            if max_bytes and read >= max_bytes:
                break
    return h.hexdigest()


def _parse_seconds(ts) -> Optional[int]:
    """Tolerant parse: accept ISO 8601 strings; ignore other types
    (numeric unix epochs, None, etc.) — the heuristic only acts on
    ISO timestamps because numeric epochs are typically genuine."""
    if not isinstance(ts, str):
        return None
    m = _RE_TIMESTAMP_SECONDS.search(ts)
    if not m:
        return None
    return int(m.group(1))


def _parse_hms_to_seconds(ts) -> Optional[float]:
    """Parse 'YYYY-MM-DDTHH:MM:SS[.frac]Z' to seconds-of-day (float).
    Returns None for non-string or non-matching timestamps."""
    if not isinstance(ts, str):
        return None
    m = _RE_TIMESTAMP_HMS.search(ts)
    if not m:
        return None
    h, mn, s = int(m.group("H")), int(m.group("M")), int(m.group("S"))
    frac = m.group("frac")
    sub = float("0." + frac) if frac else 0.0
    return h * 3600 + mn * 60 + s + sub


def _detect_synthetic_timing(entries: List[dict]) -> Optional[str]:
    """v1.6.32: three patterns trigger ATTEST_TIMING_SUSPICIOUS:

      A. Every entry has :00 seconds (legacy v1.6.31 pattern).
      B. Every entry has 0 sub-second precision (no .frac portion or
         all zero) AND clusters on round-minute boundaries
         (i.e. seconds-of-day mod 60 == 0). Catches entries timestamped
         10:01:00 / 10:05:00 / 10:11:00 etc. — the v10627-noris case.
      C. ≥3 consecutive monotonic gaps that are EXACT multiples of
         60 / 300 / 600 seconds (regular cadence, fabricated).

    Requires ≥3 entries to have any opinion at all (avoid spurious
    flags on tiny logs). Returns a diagnostic or None.
    """
    secs: List[int] = []
    soda: List[float] = []
    fracs_all_zero = True
    for e in entries:
        ts = e.get("timestamp", "")
        s = _parse_seconds(ts)
        if s is None:
            return None
        secs.append(s)
        v = _parse_hms_to_seconds(ts)
        if v is None:
            return None
        soda.append(v)
        m = _RE_TIMESTAMP_HMS.search(ts) if isinstance(ts, str) else None
        frac = m.group("frac") if m else None
        if frac and any(c != "0" for c in frac):
            fracs_all_zero = False
    if len(secs) < 3:
        return None

    # Pattern A — all entries on :00 seconds
    if all(s == 0 for s in secs):
        return (f"all {len(secs)} entries timestamped on :00 second "
                f"boundaries — synthetic pattern (real tool runs hit "
                f"various seconds)")

    # Pattern B — all entries on round-minute boundaries with no
    # sub-second jitter (catches the v10627-noris case where the
    # CHANGELOG describes 10:01:00, 10:05:00, 10:11:00, 11:30:00 etc.)
    if fracs_all_zero and all(int(v) % 60 == 0 for v in soda):
        return (f"all {len(soda)} entries on round-minute boundaries "
                f"with zero sub-second precision — synthetic pattern "
                f"(real tool runs have sub-second jitter)")

    # Pattern C — ≥3 consecutive gaps that are exact multiples of
    # 60 / 300 / 600 seconds
    if len(soda) >= 4:
        gaps = [soda[i + 1] - soda[i] for i in range(len(soda) - 1)]
        for unit in (60, 300, 600):
            run = 0
            for g in gaps:
                if g > 0 and abs(g - round(g / unit) * unit) < 0.01:
                    run += 1
                    if run >= 3:
                        return (f"{run}+ consecutive gaps are exact "
                                f"multiples of {unit}s — fabricated "
                                f"regular cadence (real tools have "
                                f"variable runtime)")
                else:
                    run = 0
    return None


def _is_inside_project(project: Path, candidate: Path) -> bool:
    """v1.6.32 path-traversal guard. Resolve both paths (no strict, so
    non-existent paths are still resolvable) and verify candidate is
    a descendant of project. Catches `outputs: {"../../foo": "..."}`
    and absolute paths that reach outside the project tree."""
    try:
        proj_resolved = project.resolve()
        cand_resolved = candidate.resolve()
    except OSError:
        return False
    try:
        cand_resolved.relative_to(proj_resolved)
        return True
    except ValueError:
        return False


def _load_provenance(project: Path) -> Tuple[Optional[List[dict]], Optional[str]]:
    """Returns (entries, error_or_None). entries=None when file missing."""
    p = project / "provenance.jsonl"
    if not p.is_file():
        return None, None
    entries: List[dict] = []
    for line_no, raw in enumerate(p.read_text(encoding="utf-8").splitlines(),
                                  start=1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            entries.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            return None, f"line {line_no}: invalid JSON: {exc}"
    return entries, None


def audit(project: Path, strict_timing: bool = False,
          max_entries: Optional[int] = None
          ) -> Tuple[str, List[ProvenanceFinding]]:
    entries, err = _load_provenance(project)
    if err:
        return "FAIL", [ProvenanceFinding(
            entry_index=-1, tool="-", rule="PROVENANCE_PARSE_ERROR",
            detail=err)]
    if entries is None:
        return "VACUOUS_PASS", []
    if not entries:
        return "VACUOUS_PASS", []
    findings: List[ProvenanceFinding] = []
    to_check = entries[:max_entries] if max_entries else entries
    # Track hashes per relative output path to flag cross-entry
    # contradictions (PROVENANCE_HASH_INCONSISTENT, v1.6.32).
    seen_hashes: Dict[str, Tuple[int, str]] = {}
    for i, e in enumerate(to_check):
        tool = e.get("tool", "?")
        outputs = e.get("outputs")
        if not outputs or not isinstance(outputs, dict):
            findings.append(ProvenanceFinding(
                entry_index=i, tool=tool,
                rule="PROVENANCE_OUTPUTS_MISSING",
                detail="entry has no 'outputs' key or it is empty/non-dict"))
            continue
        for rel_path, claimed in outputs.items():
            if not isinstance(claimed, str) or not _RE_SHA256.match(claimed):
                findings.append(ProvenanceFinding(
                    entry_index=i, tool=tool,
                    rule="PROVENANCE_HASH_SHAPE_INVALID",
                    detail=f"output '{rel_path}': value '{claimed!r}' is not "
                           f"a 'sha256:<64-hex>' string"))
                continue
            declared_hex = claimed.split(":", 1)[1].lower()
            # Cross-entry consistency: same rel_path must declare same
            # hash. (Different tools producing the same artefact would
            # be unusual; the audit chain should reflect a single owner.)
            prev = seen_hashes.get(rel_path)
            if prev is not None and prev[1] != declared_hex:
                findings.append(ProvenanceFinding(
                    entry_index=i, tool=tool,
                    rule="PROVENANCE_HASH_INCONSISTENT",
                    detail=f"output '{rel_path}' declared sha256:"
                           f"{declared_hex} here, but entry#{prev[0]} "
                           f"declared sha256:{prev[1]}"))
                # Continue with on-disk verification anyway.
            else:
                seen_hashes[rel_path] = (i, declared_hex)
            on_disk = project / rel_path
            # v1.6.32 path-traversal guard
            if not _is_inside_project(project, on_disk):
                findings.append(ProvenanceFinding(
                    entry_index=i, tool=tool,
                    rule="PROVENANCE_PATH_OUTSIDE_PROJECT",
                    detail=f"declared output '{rel_path}' resolves outside "
                           f"the project root; audit chain only attests "
                           f"project-owned artefacts"))
                continue
            if not on_disk.exists():
                findings.append(ProvenanceFinding(
                    entry_index=i, tool=tool,
                    rule="PROVENANCE_OUTPUT_FILE_MISSING",
                    detail=f"declared output '{rel_path}' does not exist on "
                           f"disk; tool claim cannot be verified"))
                continue
            try:
                actual = _file_sha256(on_disk)
            except OSError as exc:
                findings.append(ProvenanceFinding(
                    entry_index=i, tool=tool,
                    rule="PROVENANCE_OUTPUT_FILE_MISSING",
                    detail=f"could not read '{rel_path}' to verify hash: {exc}"))
                continue
            if actual.lower() != declared_hex:
                findings.append(ProvenanceFinding(
                    entry_index=i, tool=tool,
                    rule="PROVENANCE_HASH_MISMATCH",
                    detail=f"output '{rel_path}': declared sha256:{declared_hex} "
                           f"vs on-disk sha256:{actual}"))
    # Synthetic-timing detection (warning-only by default)
    pattern = _detect_synthetic_timing(entries)
    if pattern is not None:
        sev = "ERROR" if strict_timing else "WARNING"
        findings.append(ProvenanceFinding(
            entry_index=-1, tool="-",
            rule="ATTEST_TIMING_SUSPICIOUS",
            severity=sev, detail=pattern))
    fatal = [f for f in findings if f.severity == "ERROR"]
    return ("FAIL" if fatal else "PASS"), findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify provenance.jsonl declares + matches output "
                    "SHA256 for every tool invocation.")
    ap.add_argument("project_dir")
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--strict-timing", action="store_true",
                    help="upgrade ATTEST_TIMING_SUSPICIOUS from WARNING "
                         "to ERROR (default: warning-only).")
    ap.add_argument("--max-entries", type=int,
                    help="audit only the first N provenance entries "
                         "(default: all)")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, findings = audit(project,
                              strict_timing=args.strict_timing,
                              max_entries=args.max_entries)

    report = {
        "gate": "provenance_output_hash_completeness_check",
        "verdict": verdict,
        "project": str(project),
        "strict_timing": args.strict_timing,
        "findings_count": len(findings),
        "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
        "warnings_count": sum(1 for f in findings if f.severity == "WARNING"),
        "findings": [asdict(f) for f in findings],
    }
    if verdict == "VACUOUS_PASS":
        report["reason"] = ("provenance.jsonl missing or empty; audit "
                            "chain not yet established.")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
        return 0
    if verdict == "PASS":
        warn = report['warnings_count']
        msg = f"PASS: provenance.jsonl is on-disk verifiable"
        if warn:
            msg += f" ({warn} non-fatal warning(s))"
        print(msg)
        for f in findings:
            print(f"  WARN [{f.rule}]: {f.detail}", file=sys.stderr)
        return 0
    print(f"FAIL: {report['errors_count']} provenance fault(s):", file=sys.stderr)
    for f in findings[:10]:
        print(f"  [{f.severity}] [{f.rule}] entry#{f.entry_index} ({f.tool}): "
              f"{f.detail}", file=sys.stderr)
    if len(findings) > 10:
        print(f"  … and {len(findings) - 10} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
