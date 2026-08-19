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
   not exist on disk AND nothing in the ledger accounts for that.
   A reader following the pointer finds nothing and is told nothing.
4. PROVENANCE_HASH_MISMATCH — declared SHA256 does not match the
   on-disk file. Output was tampered or claim is fabricated.
4a. PROVENANCE_RELOCATION_UNVERIFIED (#434) — a row discloses that a
   declared output ships under a different name, but the target is
   absent or does not carry the declared digest. See below.
4b. PROVENANCE_PRUNE_UNEXPLAINED (#434) — a not-shipped disclosure
   with no stated reason. See below.
4c. PROVENANCE_PRUNE_CONTRADICTED (#434) — a row discloses an output
   as not shipped, and exactly that artefact is at that path. See
   below.
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

Publish-time disclosures: a THIRD outcome, not a waiver (#434)
--------------------------------------------------------------
#414 gave `provenance_declared_output_check --reconcile` two additive
row-level disclosures, written when a deliverable is published:

    outputs_relocated_at_publish  {declared path: shipped path}
    outputs_pruned_at_publish     [declared paths]
    outputs_pruned_reason         why they are not here

This gate then ERRORed on exactly the rows those disclosures describe:
102 PROVENANCE_OUTPUT_FILE_MISSING across the 21 tracked ledgers, every
one of them a row #414 had deliberately annotated. So the cheapest way
to make this gate green was to DELETE the disclosure — restoring the
dangling pointer #414 removed. That is the trap #434 was filed about.

    A MARKER THAT SUPPRESSES A CHECK IS A WAIVER.
    A MARKER THAT CHANGES THE CHECK'S QUESTION IS A FACT.
    THIS IS THE SECOND. Here is what that costs the row, concretely:

* A RELOCATION MAKES THE GATE DO MORE WORK, NOT LESS. Before #434 the
  row was one existence test that failed. Now the gate follows the
  pointer, checks the target is inside the project, hashes it, and
  requires the digest to EQUAL the declared one. Only then is the
  output VERIFIED — the bytes really are here, under another name.
  A relocation to a file that is absent, outside the project, or
  carrying any other digest is PROVENANCE_RELOCATION_UNVERIFIED
  (ERROR) — strictly harder to satisfy than the absence it replaced,
  and it cannot launder a changed artefact into a passing one.

* A NOT-SHIPPED DISCLOSURE MUST BE (a) EXPLAINED, (b) TRUE, and (c)
  BACKED BY A DIGEST. `outputs_pruned_at_publish` with no non-empty
  `outputs_pruned_reason` is a bare silencer, and the gate refuses it:
  PROVENANCE_PRUNE_UNEXPLAINED (ERROR). The declared digest still has
  to pass the sha256 shape and cross-entry consistency checks — those
  run BEFORE any of this. And PRESENCE IS TESTED FIRST, ALWAYS: if the
  path exists, the file is hashed and a mismatch is reported exactly
  as before, so adding a pruned marker can never silence a
  PROVENANCE_HASH_MISMATCH. If the path exists AND hashes as declared
  AND the row says it was not shipped, the disclosure is provably
  false — PROVENANCE_PRUNE_CONTRADICTED (ERROR).

Only after all of that does an absent, explained, digest-carrying,
uncontradicted output become the third outcome:

    PROVENANCE_OUTPUT_NOT_VERIFIABLE_HERE, severity DISCLOSED

which is non-fatal and is NOT silent: the count appears in the PASS
line and every instance is listed in the `--json` report. "PASS" on
this gate has never meant "every claim was exercised", and after #434
it says so in words.

WHY THIS GATE STILL RUNS ON A PUBLISHED DELIVERABLE
---------------------------------------------------
#432 established that the run directory is the right population for
the PRODUCER-side question ("did the run make this?"). The obvious
next move was to say this gate is producer-side too and should not run
on curated cells at all. Measured across the 21 tracked ledgers (156
declared outputs) that answer is wrong:

    present at the declared path, hashes as declared        54
    absent, disclosed as relocated, hashes at the target    12
    absent, disclosed as not shipped, digest recorded       90
    absent, no disclosure of any kind                        0

Dropping the gate on published cells would discard 66 real byte-level
verifications — the only place the SHIPPED bytes of a deliverable are
checked against the run's own record, from the deliverable's own
directory — to remove 102 findings that were never wrong about the
facts, only about the verdict. The consumer-side question ("is what I
received what was made?") is at its MOST meaningful on the curated
tree, because that tree is what a reader actually receives. So the
gate stays and the outcome splits.

`--require-outputs-present` exists for the other population: on a RUN
directory nothing has been published yet, so a not-shipped disclosure
is itself suspicious, and the flag promotes every DISCLOSED finding
back to ERROR. Population is chosen by an explicit flag, never guessed
from the presence of a marker.

Read alongside `provenance_declared_output_check` (#414), which asks
the same question of the git INDEX at repo scope. This gate reads the
WORKING TREE, because on a live run directory nothing is tracked at
all; the two populations differ and that is deliberate.

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
                                                          [--require-outputs-present]

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
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

import _published_tree


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
    # ERROR    — fatal, the audit chain is broken here.
    # WARNING  — non-fatal, something looks wrong about the record.
    # DISCLOSED (#434) — non-fatal, and nothing is wrong: the ledger
    #   itself states this output is not in this tree and says why.
    #   A THIRD severity rather than a WARNING because there is no
    #   defect to act on, and rather than silence because 90 of 156
    #   declared outputs across the tracked corpus land here — a
    #   reader who is not told that would take "PASS" to mean all 156
    #   were exercised. Fatality is computed from ERROR alone, so
    #   adding this severity cannot change any existing verdict.
    severity: str = "ERROR"   # ERROR / WARNING / DISCLOSED


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


# #434 — publish-time disclosures written by
# `provenance_declared_output_check --reconcile` (#414). The key names are
# matched EXACTLY, with no aliases and no fuzzy suffix matching, unlike the
# removal-event recognizer above. That recognizer is loose because it has to
# accept ledgers written by tools it does not own; these three keys have
# exactly one writer in the tree, and every additional spelling accepted here
# would be one more way to spell "stop asking".
_RELOCATED_KEY = "outputs_relocated_at_publish"
_PRUNED_KEY = "outputs_pruned_at_publish"
_PRUNED_REASON_KEY = "outputs_pruned_reason"


def _ellipsis(text: str, limit: int) -> str:
    """Quote the head of a stated reason. The full text stays in the ledger
    and in `--json`; the finding only has to show the reader that a reason
    was given and roughly what it says."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _publish_disclosures(entry: dict) -> Tuple[Dict[str, str], set, str]:
    """Return (relocated {declared -> shipped}, pruned {declared}, reason).

    Scoped to THIS row: a row that declares an output must itself disclose
    it. A disclosure in a neighbouring row says nothing about this row's
    claim, and letting one leak across rows would mean a single marker
    anywhere in the ledger could account for a path everywhere in it.

    Non-dict / non-list / non-string values degrade to empty, so a malformed
    disclosure accounts for nothing and the output falls through to
    PROVENANCE_OUTPUT_FILE_MISSING — never the other way round.
    """
    rel_raw = entry.get(_RELOCATED_KEY)
    relocated = {k: v for k, v in rel_raw.items()
                 if isinstance(k, str) and isinstance(v, str) and v} \
        if isinstance(rel_raw, dict) else {}
    pruned_raw = entry.get(_PRUNED_KEY)
    pruned = {p for p in pruned_raw if isinstance(p, str) and p} \
        if isinstance(pruned_raw, list) else set()
    reason = entry.get(_PRUNED_REASON_KEY)
    reason = reason.strip() if isinstance(reason, str) else ""
    return relocated, pruned, reason


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


def _published_paths(project: Path) -> Optional[FrozenSet[str]]:
    """The set of paths this deliverable actually SHIPS, or None if that is
    not a meaningful question here.

    Found by the gatekeeper landing #434, on the very corpus the change was
    measured against. "Is this output shipped?" was answered by asking the
    LOCAL DISK, but shipped-ness is a property of the published tree, which is
    what git tracks. Measured on 21 tracked ledgers: 37 declared outputs exist
    on disk while being UNTRACKED — leftover run artefacts on the author's
    machine that no reader who clones this repository ever receives. Their
    presence turned three cells' honest `not shipped` disclosures into
    PROVENANCE_PRUNE_CONTRADICTED, so the SAME commit passed in a fresh
    worktree (tracked files only) and failed in a working checkout.

    A gate whose verdict depends on untracked leftovers is not measuring the
    artefact; it is measuring the machine.

    The discriminator is the LEDGER ITSELF. A deliverable is published exactly
    when its `provenance.jsonl` is part of the published tree; then shipped
    means tracked. A raw run directory — outside a repository, or inside one
    but not committed — has published nothing yet, so the question does not
    apply and presence on disk remains the answer.
    """
    return _published_tree.published_paths(project, require="provenance.jsonl")


def audit(project: Path, strict_timing: bool = False,
          max_entries: Optional[int] = None,
          require_outputs_present: bool = False,
          ) -> Tuple[str, List[ProvenanceFinding]]:
    """Verdict + findings. Thin wrapper over `audit_counted` so that every
    existing 2-tuple caller keeps working; #434 needed the per-outcome
    counts as well, and a verdict line that cannot state them is how "PASS"
    comes to mean "all 156 declared outputs were exercised"."""
    verdict, findings, _counts = audit_counted(
        project, strict_timing=strict_timing, max_entries=max_entries,
        require_outputs_present=require_outputs_present)
    return verdict, findings


def audit_counted(project: Path, strict_timing: bool = False,
                  max_entries: Optional[int] = None,
                  require_outputs_present: bool = False,
                  ) -> Tuple[str, List[ProvenanceFinding], Dict[str, int]]:
    """As `audit`, plus the #434 outcome census:

        declared              every path in every entry's `outputs`
        verified_present      present at the declared path, hashes
        verified_relocated    absent, disclosed relocated, target hashes
        not_verifiable_here   absent, disclosed not shipped, digest kept
    """
    _counts = {"declared": 0, "verified_present": 0,
               "verified_relocated": 0, "not_verifiable_here": 0}
    # #434 follow-up (gatekeeper): "shipped" is a property of the PUBLISHED
    # tree, not of this machine's disk. None -> not a published deliverable,
    # so presence on disk remains the honest answer.
    published = _published_paths(project)

    def _shipped(rel: str) -> bool:
        return (project / rel).is_file() if published is None else rel in published

    entries, err = _load_provenance(project)
    if err:
        return "FAIL", [ProvenanceFinding(
            entry_index=-1, tool="-", rule="PROVENANCE_PARSE_ERROR",
            detail=err)], _counts
    if entries is None:
        return "VACUOUS_PASS", [], _counts
    if not entries:
        return "VACUOUS_PASS", [], _counts
    findings: List[ProvenanceFinding] = []
    verified_present = 0
    verified_relocated = 0
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
        # #365 — a per-invocation COMMAND-AUDIT record (record == "invocation",
        # written by phase3_one_shot_runner._log_invocation) whose call site
        # DECLARED no output legitimately carries none. The writer's own
        # contract: "Declared by the CALL SITE, hashed here. Absent when the
        # caller declared nothing or nothing it declared was produced — empty is
        # honest." Such a row makes NO artefact claim, so it cannot hide an
        # unverified artefact: any invocation row that DOES declare outputs still
        # falls through to full on-disk hash verification below, and an
        # ARTEFACT-declaration row (record != "invocation") with empty outputs
        # still FAILs PROVENANCE_OUTPUTS_MISSING. DISCLOSE it (so a reader sees
        # these command rows were not artefact-verified) rather than silence or
        # FAIL. Regression fixed: the #365 invocation records post-date this
        # gate, which was written for the one-row-per-artefact model, so every
        # phase-3 run with report/probe tool invocations (sta report runs,
        # yosys lib-probe / post-layout LEC, klayout grid-snap, tap-geometry
        # measurement) FAILed the completion audit even with clean sign-off.
        if (e.get("record") == "invocation"
                and (not outputs or not isinstance(outputs, dict))):
            _mk = e.get("marker")
            _mk = _ellipsis(str(_mk), 80) if _mk else "-"
            findings.append(ProvenanceFinding(
                entry_index=i, tool=tool,
                rule="PROVENANCE_INVOCATION_NO_DECLARED_OUTPUT",
                severity="DISCLOSED",
                detail=("command-audit invocation record declared no output "
                        f"(marker={_mk}) — empty is honest per the "
                        "_log_invocation writer contract; the row makes no "
                        "artefact claim to verify")))
            continue
        if not outputs or not isinstance(outputs, dict):
            findings.append(ProvenanceFinding(
                entry_index=i, tool=tool,
                rule="PROVENANCE_OUTPUTS_MISSING",
                detail="entry has no 'outputs' key or it is empty/non-dict"))
            continue
        # #434 — this row's publish-time disclosures, if any. Read once per
        # row; consulted ONLY after presence and hash have been decided.
        relocated_map, pruned_set, pruned_reason = _publish_disclosures(e)
        for rel_path, claimed in outputs.items():
            _counts["declared"] += 1
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
            if not _shipped(rel_path):
                # Deliberate non-verification made visible: the file is right
                # there but is not part of what this deliverable publishes, so
                # its bytes are not the reader's bytes. Silently skipping it
                # would be a hidden decision.
                untracked_leftover = on_disk.is_file()
                if untracked_leftover:
                    findings.append(ProvenanceFinding(
                        entry_index=i, tool=tool, severity="DISCLOSED",
                        rule="PROVENANCE_OUTPUT_PRESENT_BUT_UNTRACKED",
                        detail=f"declared output '{rel_path}' is on this disk "
                               f"but is NOT tracked by the published tree; a "
                               f"reader who clones does not receive it, so it "
                               f"is judged as not shipped rather than "
                               f"verified from a local leftover"))
                # v0.2.102 — for #493 part 3. A path legitimately removed
                # by a later prune/supersede event is expected to be
                # absent; do not flag it as a missing-output fault.
                if rel_path in removed_paths:
                    continue
                # #434 — an absence the ledger accounts for. Order matters:
                # relocation is tried FIRST and, if it is present but broken,
                # it ERRORs rather than falling through to the pruned branch.
                # A row that claims the file ships elsewhere does not get to
                # fall back on "it does not ship" when the claim fails.
                if rel_path in relocated_map:
                    tgt_rel = relocated_map[rel_path]
                    tgt = project / tgt_rel
                    if not _is_inside_project(project, tgt):
                        findings.append(ProvenanceFinding(
                            entry_index=i, tool=tool,
                            rule="PROVENANCE_PATH_OUTSIDE_PROJECT",
                            detail=f"declared output '{rel_path}' is disclosed "
                                   f"as relocated to '{tgt_rel}', which "
                                   f"resolves outside the project root"))
                        continue
                    try:
                        tgt_hex = (_file_sha256(tgt)
                                   if (_shipped(tgt_rel) and tgt.is_file())
                                   else None)
                    except OSError:
                        tgt_hex = None
                    if tgt_hex is None:
                        findings.append(ProvenanceFinding(
                            entry_index=i, tool=tool,
                            rule="PROVENANCE_RELOCATION_UNVERIFIED",
                            detail=f"declared output '{rel_path}' is disclosed "
                                   f"as relocated to '{tgt_rel}', which is not "
                                   f"a readable file here; the disclosure does "
                                   f"not account for the absence"))
                        continue
                    if tgt_hex.lower() != declared_hex:
                        findings.append(ProvenanceFinding(
                            entry_index=i, tool=tool,
                            rule="PROVENANCE_RELOCATION_UNVERIFIED",
                            detail=f"declared output '{rel_path}' is disclosed "
                                   f"as relocated to '{tgt_rel}', but that file "
                                   f"is sha256:{tgt_hex}, not the declared "
                                   f"sha256:{declared_hex}; a relocation may "
                                   f"only repoint at the SAME bytes"))
                        continue
                    # Verified — the bytes the run recorded are here, under
                    # the name the disclosure gives. Counted, not flagged.
                    verified_relocated += 1
                    continue
                if rel_path in pruned_set:
                    if not pruned_reason:
                        findings.append(ProvenanceFinding(
                            entry_index=i, tool=tool,
                            rule="PROVENANCE_PRUNE_UNEXPLAINED",
                            detail=f"declared output '{rel_path}' is listed in "
                                   f"'{_PRUNED_KEY}' with no non-empty "
                                   f"'{_PRUNED_REASON_KEY}'; a marker that "
                                   f"states no reason silences the check "
                                   f"instead of answering it, and is refused"))
                        continue
                    findings.append(ProvenanceFinding(
                        entry_index=i, tool=tool,
                        severity=("ERROR" if require_outputs_present
                                  else "DISCLOSED"),
                        rule="PROVENANCE_OUTPUT_NOT_VERIFIABLE_HERE",
                        detail=(f"declared output '{rel_path}' is not in this "
                                f"tree and the ledger says so: sha256:"
                                f"{declared_hex} was recorded by the run and "
                                f"cannot be checked here. Reason given: "
                                f"{_ellipsis(pruned_reason, 120)}")
                               + (" — --require-outputs-present: on a run "
                                  "directory nothing has been published yet, "
                                  "so a not-shipped disclosure is itself the "
                                  "fault." if require_outputs_present else "")))
                    continue
                if untracked_leftover:
                    # NOT "does not exist on disk" — it plainly does, and this
                    # gate said so one finding earlier. Two contradictory
                    # verdicts on one row is the defect #434 was filed about,
                    # reproduced by the fix for it. Still a FAULT: the ledger
                    # declares an output the deliverable does not ship and
                    # nothing accounts for that. Only the REASON changes.
                    findings.append(ProvenanceFinding(
                        entry_index=i, tool=tool,
                        rule="PROVENANCE_OUTPUT_NOT_SHIPPED_UNDISCLOSED",
                        detail=f"declared output '{rel_path}' is on this disk "
                               f"but the published tree does not carry it, and "
                               f"no disclosure accounts for that; a reader who "
                               f"clones receives nothing and is told nothing, "
                               f"while the author sees a file and believes it "
                               f"shipped"))
                    continue
                findings.append(ProvenanceFinding(
                    entry_index=i, tool=tool,
                    rule="PROVENANCE_OUTPUT_FILE_MISSING",
                    detail=f"declared output '{rel_path}' does not exist on "
                           f"disk, and no disclosure in this entry accounts "
                           f"for it; a reader following the ledger finds "
                           f"nothing and is told nothing"))
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
                # NOTE the fall-through: a pruned marker on a path that DOES
                # exist never suppresses the mismatch above, because presence
                # is tested before any disclosure is read. That ordering is
                # the whole anti-gaming property — "mark it pruned" must not
                # be a way to silence a changed artefact.
            else:
                verified_present += 1
                if rel_path in pruned_set:
                    findings.append(ProvenanceFinding(
                        entry_index=i, tool=tool,
                        rule="PROVENANCE_PRUNE_CONTRADICTED",
                        detail=f"'{rel_path}' is listed in '{_PRUNED_KEY}' as "
                               f"not shipped, but a file with exactly the "
                               f"declared sha256:{declared_hex} is at that "
                               f"path; the disclosure is false"))
    # Synthetic-timing detection (warning-only by default)
    pattern = _detect_synthetic_timing(entries)
    if pattern is not None:
        sev = "ERROR" if strict_timing else "WARNING"
        findings.append(ProvenanceFinding(
            entry_index=-1, tool="-",
            rule="ATTEST_TIMING_SUSPICIOUS",
            severity=sev, detail=pattern))
    _counts["verified_present"] = verified_present
    _counts["verified_relocated"] = verified_relocated
    _counts["not_verifiable_here"] = sum(
        1 for f in findings
        if f.rule == "PROVENANCE_OUTPUT_NOT_VERIFIABLE_HERE")
    # Fatality is still ERROR-only. DISCLOSED is deliberately outside this
    # set — and `--require-outputs-present` does not add a case here, it
    # raises the severity at the point of emission, so there is exactly one
    # definition of "fatal" in this file.
    fatal = [f for f in findings if f.severity == "ERROR"]
    return ("FAIL" if fatal else "PASS"), findings, _counts


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
    ap.add_argument("--require-outputs-present", action="store_true",
                    help="#434: upgrade PROVENANCE_OUTPUT_NOT_VERIFIABLE_HERE "
                         "from DISCLOSED to ERROR. For auditing a RUN "
                         "directory, where nothing has been published yet and "
                         "a not-shipped disclosure is itself suspicious. On a "
                         "curated deliverable this is the wrong question — see "
                         "the module docstring for the measurement.")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, findings, counts = audit_counted(
        project,
        strict_timing=args.strict_timing,
        max_entries=args.max_entries,
        require_outputs_present=args.require_outputs_present)

    report = {
        "gate": "provenance_output_hash_completeness_check",
        "verdict": verdict,
        "project": str(project),
        "strict_timing": args.strict_timing,
        "require_outputs_present": args.require_outputs_present,
        "findings_count": len(findings),
        "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
        "warnings_count": sum(1 for f in findings if f.severity == "WARNING"),
        # #434 — the outcome census. `declared` is the denominator a reader
        # needs to know what a PASS did and did not cover; without it,
        # "PASS" reads as "all of it".
        "disclosed_count": sum(1 for f in findings
                               if f.severity == "DISCLOSED"),
        "outcome_census": counts,
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

    # #434 — the census goes on the verdict line itself, on PASS and on
    # FAIL alike. A bare "PASS: on-disk verifiable" over a ledger where 7 of
    # 17 outputs were never opened is the sentence this issue exists to stop.
    census = (f"{counts['declared']} declared output(s): "
              f"{counts['verified_present']} verified on disk, "
              f"{counts['verified_relocated']} verified through a disclosed "
              f"relocation, {counts['not_verifiable_here']} NOT VERIFIABLE "
              f"HERE (absent, disclosed as not shipped, digest recorded)")
    if verdict == "PASS":
        warn = report['warnings_count']
        msg = f"PASS: provenance.jsonl — {census}"
        if warn:
            msg += f"; {warn} non-fatal warning(s)"
        print(msg)
        for f in findings:
            tag = "WARN" if f.severity == "WARNING" else f.severity
            print(f"  {tag} [{f.rule}]: {f.detail}", file=sys.stderr)
        return 0
    print(f"FAIL: {report['errors_count']} provenance fault(s) — {census}",
          file=sys.stderr)
    # ERRORs first: the fatal findings are what the exit code is about, and
    # a DISCLOSED row filling the first ten lines would bury them.
    ordered = ([f for f in findings if f.severity == "ERROR"]
               + [f for f in findings if f.severity != "ERROR"])
    for f in ordered[:10]:
        print(f"  [{f.severity}] [{f.rule}] entry#{f.entry_index} ({f.tool}): "
              f"{f.detail}", file=sys.stderr)
    if len(ordered) > 10:
        print(f"  … and {len(ordered) - 10} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
