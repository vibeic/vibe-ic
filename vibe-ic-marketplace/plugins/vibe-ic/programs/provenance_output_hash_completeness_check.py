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
8. PROVENANCE_REMOVAL_EMPTY (v0.2.102) — an entry marked as a removal /
   supersede event but with an empty `removed` / `superseded` list. A
   removal must reference what it removed.
9. PROVENANCE_REMOVAL_FILE_STILL_PRESENT (v0.2.102) — a removal event
   claims to have removed a path that still exists on disk. The removal
   did not actually happen.

7. ATTEST_TIMING_SUSPICIOUS (WARNING, not FAIL) — entry timestamps
   exhibit synthetic patterns. v1.6.32 widened the heuristic beyond
   "all on :00 seconds" to also catch:
     * all entries on `:NN:00` minute boundaries with second jitter
       (e.g. 10:01:00, 10:05:00, 10:11:00);
     * monotonic gaps that are exact multiples of 60 / 300 / 600s
       and ≥3 such regular gaps in a row.
   `--strict-timing` upgrades to ERROR.

Removal / supersede events (v0.2.102, for #493 part 3)
------------------------------------------------------
A prune/supersede entry records the REMOVAL of a previous entry's
outputs rather than the production of new artefacts. Such an entry is
recognised by a removal marker (`event` ending in `prune`/`remove`/
`supersede`, or `op`/`type` in {remove, removal, prune, supersede,
delete}) AND it MUST carry empty `outputs` together with a NON-EMPTY
`removed` / `superseded` list referencing the original entry's paths.
For a well-formed removal event, empty `outputs` is ACCEPTED (it
produces nothing) and the removed paths are verified to be ABSENT on
disk (a removal that left the file behind is a contradiction →
PROVENANCE_REMOVAL_FILE_STILL_PRESENT). A removal marker with empty
`removed` list is malformed → PROVENANCE_REMOVAL_EMPTY. This does NOT
weaken the gate for NORMAL entries: an entry without a removal marker
that has empty `outputs` still FAILs with PROVENANCE_OUTPUTS_MISSING.

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
_RE_BARE_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
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
         10:01:00 / 10:05:00 / 10:11:00 etc. — the v10627-vendor case.
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
    # sub-second jitter (catches the v10627-vendor case where the
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


# v0.2.102 — for #493 part 3. Removal / supersede event recognition.
# A prune/supersede entry records the REMOVAL of a prior entry's outputs
# rather than producing artefacts. Recognised by a removal marker in
# `op` / `type` (exact, case-insensitive) OR `event` (suffix), and it
# carries a non-empty removed/superseded list.
_REMOVAL_OP_MARKERS = {
    "remove", "removal", "removed", "prune", "pruned",
    "supersede", "superseded", "delete", "deleted",
}
_REMOVAL_EVENT_SUFFIXES = ("prune", "remove", "supersede", "delete")
_REMOVED_LIST_KEYS = ("removed", "superseded", "removed_outputs",
                      "pruned", "supersedes")


def _removal_list(entry: dict) -> Optional[list]:
    """Return the non-empty removed/superseded list of a removal entry,
    [] if the entry is a removal but the list is empty/malformed, or
    None if the entry is NOT a removal event at all."""
    is_removal = False
    for key in ("op", "type", "operation"):
        v = entry.get(key)
        if isinstance(v, str) and v.strip().lower() in _REMOVAL_OP_MARKERS:
            is_removal = True
            break
    if not is_removal:
        ev = entry.get("event")
        if isinstance(ev, str):
            evl = ev.strip().lower()
            if any(evl.endswith(suf) or evl.endswith(suf + "d") or
                   f"_{suf}" in evl or evl == suf
                   for suf in _REMOVAL_EVENT_SUFFIXES):
                is_removal = True
    if not is_removal:
        return None
    # Gather the removed/superseded references.
    refs: List = []
    for key in _REMOVED_LIST_KEYS:
        v = entry.get(key)
        if isinstance(v, list):
            refs.extend(v)
    return refs


# A13 (#173) — `ip_catalog_pull` (ip_catalog_pull.py) records the RTL files it
# copied as an `outputs_sha256` LIST of bare sha256 hex digests plus a
# `files_pulled` count. That is a legitimate AGGREGATE provenance shape, distinct
# from the per-path `outputs` dict the in-runner tool entries use. The check only
# ever looked at `outputs`, so a catalog-pull entry (present on EVERY reused-IP /
# SoC-class design — ibex, picorv32, sha256_core, …) false-FAILed with
# PROVENANCE_OUTPUTS_MISSING — the "2 faults after a normal clean full run" (two
# pulled IPs → two entries). The current writer ALSO emits `outputs` (v1.0.74), so
# NEW runs verify via that dict below; this recognizer additionally accepts the
# aggregate list form so a list-only / pre-v1.0.74 record is not false-flagged.
# §4.05 — an EMPTY or malformed aggregate list STILL faults; a normal (non-pull)
# entry with empty `outputs` is UNAFFECTED (still PROVENANCE_OUTPUTS_MISSING).
def _ip_catalog_pull_aggregate(entry: dict) -> Optional[list]:
    """Return the `outputs_sha256` aggregate-hash list of an `ip_catalog_pull`
    provenance event (possibly empty), or None when the entry is NOT such an
    event. Recognised strictly by `event == "ip_catalog_pull"` so the acceptance
    is scoped to the documented catalog-pull schema and never relaxes the
    `outputs`-dict requirement for ordinary tool-invocation entries."""
    ev = entry.get("event")
    if not (isinstance(ev, str) and ev.strip().lower() == "ip_catalog_pull"):
        return None
    lst = entry.get("outputs_sha256")
    return lst if isinstance(lst, list) else []


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
    # v0.2.102 — for #493 part 3. Pre-scan removal/supersede events so a
    # NORMAL pull entry's output that was legitimately removed by a later
    # prune event is not flagged PROVENANCE_OUTPUT_FILE_MISSING. The
    # prune event references the original outputs in its removed list.
    removed_paths: set = set()
    for e in to_check:
        refs = _removal_list(e)
        if not refs:
            continue
        for ref in refs:
            rel = ref.get("path") if isinstance(ref, dict) else ref
            if isinstance(rel, str) and rel:
                removed_paths.add(rel)
    for i, e in enumerate(to_check):
        tool = e.get("tool", "?")
        outputs = e.get("outputs")
        # v0.2.102 — for #493 part 3. Removal / supersede event shape.
        # Recognise BEFORE the empty-outputs check so a well-formed
        # removal (empty outputs + non-empty removed list) is accepted,
        # while a NORMAL entry with empty outputs still FAILs below.
        removal_refs = _removal_list(e)
        if removal_refs is not None:
            tool = e.get("tool", e.get("event", "prune"))
            # A removal must reference what it removed.
            if not removal_refs:
                findings.append(ProvenanceFinding(
                    entry_index=i, tool=tool,
                    rule="PROVENANCE_REMOVAL_EMPTY",
                    detail="entry is marked as a removal/supersede event "
                           "but its removed/superseded list is empty"))
                continue
            # Outputs, if present, must be empty for a removal event
            # (it produces nothing). A non-empty outputs map on a
            # removal entry is verified normally below to avoid a hole.
            if isinstance(outputs, dict) and outputs:
                # Fall through to normal output verification AND still
                # validate the removed paths are gone.
                pass
            # Each removed path must actually be ABSENT on disk.
            for ref in removal_refs:
                rel = ref.get("path") if isinstance(ref, dict) else ref
                if not isinstance(rel, str) or not rel:
                    continue
                on_disk = project / rel
                if not _is_inside_project(project, on_disk):
                    findings.append(ProvenanceFinding(
                        entry_index=i, tool=tool,
                        rule="PROVENANCE_PATH_OUTSIDE_PROJECT",
                        detail=f"removed path '{rel}' resolves outside the "
                               f"project root"))
                    continue
                if on_disk.exists():
                    findings.append(ProvenanceFinding(
                        entry_index=i, tool=tool,
                        rule="PROVENANCE_REMOVAL_FILE_STILL_PRESENT",
                        detail=f"removal event claims to have removed "
                               f"'{rel}' but it still exists on disk"))
            # If the removal also (unexpectedly) declared outputs, verify
            # them; otherwise this entry is complete — skip the
            # empty-outputs FAIL below.
            if not (isinstance(outputs, dict) and outputs):
                continue
        # A13 (#173) — an `ip_catalog_pull` event records its outputs as an
        # `outputs_sha256` aggregate list (bare hex) + `files_pulled` count, not
        # a per-path `outputs` dict. When it carries a USABLE `outputs` dict
        # (v1.0.74+ writer) fall through and verify that on-disk; otherwise
        # validate the aggregate list here so the pull is not false-flagged
        # OUTPUTS_MISSING. An empty / malformed / count-mismatched aggregate
        # STILL faults (§4.05 — no fabricated completeness).
        _agg = _ip_catalog_pull_aggregate(e)
        if _agg is not None and not (isinstance(outputs, dict) and outputs):
            tool = e.get("tool", e.get("event", "ip_catalog_pull"))
            if not _agg:
                findings.append(ProvenanceFinding(
                    entry_index=i, tool=tool,
                    rule="PROVENANCE_OUTPUTS_MISSING",
                    detail="ip_catalog_pull event carries neither an 'outputs' "
                           "dict nor a non-empty 'outputs_sha256' aggregate "
                           "list"))
                continue
            bad = [h for h in _agg
                   if not (isinstance(h, str) and _RE_BARE_SHA256.match(h))]
            if bad:
                findings.append(ProvenanceFinding(
                    entry_index=i, tool=tool,
                    rule="PROVENANCE_HASH_SHAPE_INVALID",
                    detail=f"ip_catalog_pull 'outputs_sha256' has {len(bad)} "
                           f"entry(ies) that are not bare sha256 hex digests"))
                continue
            fp = e.get("files_pulled")
            if isinstance(fp, int) and fp != len(_agg):
                findings.append(ProvenanceFinding(
                    entry_index=i, tool=tool,
                    rule="PROVENANCE_OUTPUTS_MISSING",
                    detail=f"ip_catalog_pull declares files_pulled={fp} but "
                           f"'outputs_sha256' lists {len(_agg)} hash(es) — the "
                           f"pulled-file hash record is incomplete"))
                continue
            # Well-formed aggregate-hash record — accepted. The bare-hash list
            # attests the pulled file set; per-path on-disk verification is not
            # possible without paths (that is what the v1.0.74 `outputs` dict
            # adds, verified above when present).
            continue
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
                # v0.2.102 — for #493 part 3. A path legitimately removed
                # by a later prune/supersede event is expected to be
                # absent; do not flag it as a missing-output fault.
                if rel_path in removed_paths:
                    continue
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
