#!/usr/bin/env python3
"""
eda_report_audit.py -- Multi-mode EDA report checker for backend skills.

Deterministic compliance program that verifies EDA sign-off reports contain
the expected analysis categories and quantitative data.

Modes:
  drc      -- DRC report: violation categories + counts
  lvs      -- LVS report: mismatch categories
  power    -- Power report: leakage AND dynamic values
  em       -- EM report: current density values
  ir_drop  -- IR-drop report: voltage drop values
  sta      -- STA report: WNS/TNS + setup/hold

Usage:
    python3 eda_report_audit.py <project_dir> --mode drc
    python3 eda_report_audit.py <project_dir> --mode sta --json out.json

Exit codes:
    0 = PASS (report exists with expected content)
    1 = FAIL (missing report or missing categories)

No external tool dependencies -- pure Python.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import glob
import hashlib
import io
import json
import subprocess
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path

import _atomic_output  # noqa: E402  (#1082 same-dir temp + atomic rename)
import _audit_receipt  # noqa: E402  (#2057 content-addressed subject digest)
from typing import Any, Dict, List, Optional, Sequence, Tuple

import lvs_verdict_tokens as _lvt  # #524 — shared netgen terminal-verdict tokens
import _signoff_drc_format as _sdf  # the ONE producer/dialect answer
# Chip-agnostic multi-dialect timing-slack extractor, already hardened for
# the report shapes real designs actually emit (worst-slack summary lines,
# WNS/TNS tokens, and a SETUP/HOLD section split) — reused rather than
# re-derived, per Bucket-A-ladder step 1 (ALREADY-PROGRAM).
import sta_corner_record_completeness_check as _sta_slack

import _sta_basis
from _mcp_measurement import strip_stamp as _meas_strip
import _gate_authorship as _ga  # R-0915-152 (who invoked this writer)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    #: What this audit says about ITSELF, when "passed / did not pass" is not
    #: the whole truth. Emitted as a top-level `verdict` key ONLY when set, so
    #: no existing report gains a field. `flow_compliance_check.
    #: _json_report_signals_vacuous` already reads exactly this key off a
    #: gate's own --json report; this is the producer side of that reader.
    verdict: str = ""
    #: #2057 — THE POPULATION `summary.files_found` COUNTS, by name. It is set
    #: on the same line as that count, from the same list, so the two can never
    #: describe different things. `main()` turns it into the `subject` block of
    #: the emitted report and does NOT emit this field itself: the report
    #: carries the content-addressed digest, not a machine's path list.
    subject_files: List[str] = field(default_factory=list)


# v0.119.21: tool-unavailable-for-PDK waiver. Custom open-source PDKs
# (<foundry> PDKs etc.) lack characterization data the IR / EM
# / SI / power / SPEF tools need. Blocking the gate forever penalises
# honest projects; instead require a documented waiver with reason ≥20
# chars (matches the waivers schema's anti-rubber-stamp policy).
_UNAVAILABLE_KEYS = {
    "power":   "power_report_unavailable_reason",
    "ir_drop": "ir_drop_report_unavailable_reason",
    "em":      "em_report_unavailable_reason",
    "si":      "si_report_unavailable_reason",
}


def _waived_for_pdk(project_dir, mode: str) -> str:
    import json as _json
    waivers = project_dir / "waivers.json"
    if not waivers.is_file():
        return ""
    try:
        data = _json.loads(waivers.read_text())
    except Exception:
        return ""
    key = _UNAVAILABLE_KEYS.get(mode)
    if not key:
        return ""
    val = data.get(key, "")
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list):
        return "\n".join(str(x).strip() for x in val if str(x).strip())
    return ""


# ---------------------------------------------------------------------------
# File discovery helpers
# ---------------------------------------------------------------------------
# #525 (field round-4 adjacent finding) — recursive report discovery used to
# ingest STALE copies under backup/aside directories (a `_stale_bak/` antenna
# report with 56 violations was parsed alongside the clean live one and
# flipped the verdict). Exclude path components that are hidden (dot-dirs)
# or carry an explicit backup token. Token matching is boundary-aware so
# legitimate names ("golden", "bakery") never match.
# v1.3.94 (spm commercial-PDK sign-off) — added `snapshot`/`snap` and
# `prebuild`: an in-tree `_known_good_snapshot_v1393/` copy of a design's
# reports (a common human backup pattern) carried a STALE netgen lvs.rpt
# (mismatch) + a pre-repair antenna stub, and the recursive report scan
# ingested BOTH alongside the clean live sign-off — the snapshot's mismatch
# then flipped the LVS/antenna verdict. A canonical report tree never uses a
# "snapshot" component, so it is unambiguously a backup-flavored aside.
_BACKUP_TOKEN_RE = re.compile(
    r"(?:^|[._\-])(bak|backup|backups|stale|old|trash|movedaside|aside"
    r"|snapshots?|snap|prebuild)"
    r"(?:$|[._\-])", re.IGNORECASE)


def _is_backup_path(p: Path, root: Path) -> bool:
    """True when any path component between root and the file is hidden or
    backup-flavored (the canonical report tree never uses such names)."""
    try:
        parts = p.relative_to(root).parts
    except ValueError:
        parts = p.parts
    for part in parts:
        if part.startswith("."):
            return True
        if _BACKUP_TOKEN_RE.search(part):
            return True
    return False


# SELF-CONSUMPTION. Several modes glob `.json` as well as `.rpt`
# (`*antenna*.json`, `*ir_drop*`, `*electromigration*`, `*power_grid*`), so this
# program's OWN `--json` verdict document — which lands in the same
# `reports/phase3/` tree it audits — is discovered on the NEXT run and parsed as
# if it were a tool report. Measured before this guard, on a project holding one
# real `reports/phase3/antenna.rpt`::
#
#     $ eda_report_audit proj --mode antenna --json reports/phase3/antenna_signoff.json
#     files_found = 1
#     $ eda_report_audit proj --mode antenna          # same project, second run
#     files_found = 2      # <- its own verdict document
#
# WHAT THIS GUARD IS, STATED HONESTLY: it is NOT a pre-existing measured defect.
# Its population on tracked data before this change is ZERO. The corpus holds 9
# `eda_report_audit:*` verdict documents (`git ls-files benchmark-data`), all of
# them `eda_report_audit:lvs` at `reports/phase3/lvs.json` — and lvs mode globs
# `*lvs*.rpt` / `*lvs*.log` / `*LVS*.rpt` / `*LVS*.log` / `*comp*.out`, none of
# which match a `.json`. So no verdict document this plugin has ever published
# was re-ingested, and running the guard over the whole corpus changes nothing
# (126 discovery measurements, base == this tree everywhere).
#
# The condition is CREATED by the argv-forwarding + collision fix in the same
# change: once the wrappers honour `--json`, steps 24 and 26 write
# `reports/phase3/ir_drop_signoff.json` and `.../antenna_signoff.json`, which
# `*ir_drop*` and `*antenna*.json` DO match. The guard closes a hole this
# change opens, in the same change — that is the correct order, and it is why
# the audit output can be given a readable name at all instead of inheriting
# `gds_antenna_deck_check`'s workaround ("nothing this gate writes may contain
# the substring antenna").
#
# The verdict document is recognised by CONTENT, not by name: every document
# this program writes carries a top-level ``"program": "eda_report_audit:<mode>"``
# (see ``AuditResult``). Keying on the self-describing field rather than on a
# filename keeps the guard working whatever path a caller passes to ``--json``,
# and removes the naming landmine other gates had to work around
# (``gds_antenna_deck_check``: "nothing this gate writes may contain the
# substring antenna").
_SELF_DOC_PROGRAM_PREFIX = "eda_report_audit:"
# A verdict document is small; refuse to slurp a large file just to classify it.
_SELF_DOC_MAX_BYTES = 512 * 1024


def _is_own_verdict_document(p: Path) -> bool:
    """True when `p` is a document THIS program wrote (an ``AuditResult`` dump).

    Content-based on purpose: the caller chooses the ``--json`` path, so a
    name-based rule would only move the landmine.
    """
    if p.suffix.lower() != ".json":
        return False
    try:
        if p.stat().st_size > _SELF_DOC_MAX_BYTES:
            return False
        doc = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return False
    return (isinstance(doc, dict)
            and isinstance(doc.get("program"), str)
            and doc["program"].startswith(_SELF_DOC_PROGRAM_PREFIX))


# STEP SCOPING. Discovery is a project-wide `rglob`, with no relationship to
# the step whose gate is asking. Measured on the real completed run
# `campaign_pr427/spm/converge_ihp-sg13g2`, step 21's router-DRC gate
# (`drc_report_check . --mode drc`)::
#
#     files_found = 5
#     best_file   = steps/31_physical_verification_drc_lvs_erc_density/
#                   drc_signoff.rpt
#
# Step 21 declares `phase3/stage3/pnr/routed.drc.rpt`; the file its verdict was
# reported against belongs to STEP 31. The five hits mix the router's own DRC
# (routed.drc.rpt, reports/phase3/drc_router.rpt) with the KLayout sign-off DRC
# (three copies of step 31's), and `real_violation_total` is summed across all
# of them. Both directions are wrong: step 31's report can carry step 21's gate
# when the router's own is absent, and step 31's violations can fail step 21.
#
# `--under <rel>` (repeatable) restricts discovery to the given subtree(s), so a
# step's gate can be pointed at the artefacts that step declares. It is opt-in:
# omitted, discovery is project-wide exactly as before, so no existing caller
# changes behaviour.
_SCOPE_ROOTS: Optional[List[Path]] = None
#: `--subject` (repeatable): the caller's own subject files; see `_discover`.
_SUBJECTS: Optional[List[Path]] = None


def _scope_root(r) -> Path:
    """Canonical form of one `--under` root, without ever raising.

    `Path.resolve()` is the SECOND place a symlink loop reaches — the root
    itself is a declared artefact path, and `--under reports/phase3/
    drc_signoff.rpt` naming a looping link aborted the run before discovery
    even started. Degrading to the absolute literal path is fail-safe: a
    candidate is admitted only if ITS resolved form sits under a root, and a
    loop resolves to nothing, so the scope matches nothing and the gate
    reports "no report under the declared scope" (rc 1) instead of crashing.
    """
    p = Path(r)
    try:
        return p.resolve()
    except (OSError, RuntimeError):
        return Path(os.path.abspath(str(p)))


class scoped_discovery:  # noqa: N801 — a context manager, used as a verb
    """Restrict `_discover` to `roots` for the duration of the block."""

    def __init__(self, roots: Optional[List[Path]]):
        self._roots = [_scope_root(r) for r in roots] if roots else None
        self._prev = None

    def __enter__(self):
        global _SCOPE_ROOTS
        self._prev = _SCOPE_ROOTS
        _SCOPE_ROOTS = self._roots
        return self

    def __exit__(self, *exc):
        global _SCOPE_ROOTS
        _SCOPE_ROOTS = self._prev
        return False


class named_subjects:  # noqa: N801 — a context manager, used as a verb
    """Name the subject files (`--subject`) for the duration of the block."""

    def __init__(self, subjects: Optional[List[Path]]):
        self._subjects = list(subjects) if subjects is not None else None
        self._prev = None

    def __enter__(self):
        global _SUBJECTS
        self._prev = _SUBJECTS
        _SUBJECTS = self._subjects
        return self

    def __exit__(self, *exc):
        global _SUBJECTS
        _SUBJECTS = self._prev
        return False


def _in_scope(p: Path) -> bool:
    """Is this path inside an active `--under` scope?

    ONE question — membership. It deliberately does NOT ask whether the path
    can be read: a dangling symlink at a step's declared evidence path must
    stay DISCOVERABLE so the mode's own check can NAME it and gate on it
    (`DRC_REPORT_NOT_READABLE`, and now `STA_REPORT_NOT_READABLE`). Dropping
    it here instead would delete the finding and hand back a green verdict
    over a certificate that does not exist — measured: making this predicate
    reject unreadable paths flipped `edge_llm_accel --mode drc` from rc 1 to
    rc 0 across the tracked corpus.

    `Path.resolve()` on Python 3.12 raises **RuntimeError** — not OSError —
    on a symlink LOOP (`pathlib.check_eloop`), and the `except OSError` guard
    that stood here did not fire on it. REPRODUCED: two `.rpt` symlinks
    pointing at each other under a `--under` scope crashed this program with
    an uncaught traceback and no verdict at all.
    """
    if not _SCOPE_ROOTS:
        return True
    try:
        rp = p.resolve()
    except (OSError, RuntimeError):
        return False
    for root in _SCOPE_ROOTS:
        try:
            rp.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _identity(p: Path):
    """The key two paths share when they are ONE physical file.

    `(st_dev, st_ino)` from a link-following `stat()`, which is the identity
    the defect is actually about: the step runners publish each canonical
    report a second time as a symlink under `steps/<phase>/<stage>/<step>/`,
    and `stat -L` shows one inode for the pair while the two literal `Path`
    objects are two distinct keys. A path-keyed dedup therefore let the same
    physical file through twice and every per-file quantity (violations,
    errors) was summed twice.

    Inode identity, not resolved-path identity, because it is the strictly
    wider and strictly cheaper of the two and it costs nothing to be right
    about the second case as well:

        symlink / target        same inode   collapse   (the measured defect)
        hard link pair          same inode   collapse   (resolve() keeps both)
        independent copies      2 inodes     both kept
        two BROKEN symlinks     stat fails   both kept  (see below)

    A file `stat()` cannot reach is keyed on its LITERAL path — which is
    exactly the pre-dedup behaviour for that path, so nothing an unreadable
    path does can remove a readable report from the audit. That covers both
    dangling symlinks (`FileNotFoundError`, and `resolve(strict=False)` would
    have silently collapsed two DIFFERENT dangling links onto one shared
    target) and symlink loops (`OSError: ELOOP` — note `Path.resolve()` raises
    a bare `RuntimeError` there instead, which is the trap `_in_scope`
    documents; `stat()` reports the errno straight, so the loop degrades here
    rather than needing to be caught).
    """
    try:
        st = p.stat()
    except OSError:
        return ("path", p)
    return ("inode", st.st_dev, st.st_ino)


def _content_key(p: Path):
    """The key two paths share when they are one MEASUREMENT, not one file.

    `_identity` above collapses aliases of a single physical file. It does not
    — and by its own documented table must not — collapse INDEPENDENT COPIES,
    which carry two inodes. That is the remaining half of the same defect, and
    the flow creates it on purpose.

    MEASURED (subservient x gf180mcuD, plugin v1.13.40, image 0.3.39). The
    phase-3 runner canonicalizes the router DRC report by writing ONE body
    string to TWO paths (`phase3_one_shot_runner.py`, "Mirror to reports/
    phase3/ where the gate's --json output lands")::

        stat -Lc '%d:%i %s'  phase3/stage3/pnr/routed.drc.rpt   66306:86959502 19113
        stat -Lc '%d:%i %s'  reports/phase3/drc_router.rpt      66306:86959503 19113
        md5sum   both                        10ef04cdcae8e7ef2f0abaead418ea16

    Two inodes, identical bytes, one router pass. `--under` scoping already
    narrows the router-DRC gate from 3 files to these 2, and the inode dedup
    already collapses each one's `steps/**` symlink — 4 literal paths become 2
    keys — but the two copies both survive and every per-file quantity is
    summed twice::

        drc_router.rpt says   [INFO DRT-0199] Number of violations = 18
        the gate recorded     real_violation_total = 36
                              tool_corroborated_files = 2

    18 x 2. The gate multiplied a count by how many times the flow had written
    it down, and then reported the second write as independent corroboration of
    the first. It over-reports, so no dirty design is graded clean — but the
    sign-off number a reader would quote is wrong by the copy count, and it is
    wrong for EVERY design, since the mirroring is unconditional.

    A DRC violation is a property of the layout, not an event: two reports with
    the same bytes are one measurement of it however many times the flow filed
    them. So the key is the content digest.

    EMPTY FILES ARE DELIBERATELY EXCLUDED. Two zero-byte reports have identical
    content and are NOT one measurement — they are two measurements that did
    not happen, and v1.13.21's ABSENT/EMPTY/POPULATED split counts them
    separately in `empty_report_files`. Collapsing them would hide one of two
    holes behind the other, which is the exact failure mode that split was
    landed to end. Size is the pre-filter as well as the carve-out: a digest is
    computed only for a file whose size collides with another survivor's, so
    the common case (no duplicates) reads nothing.

    Unreadable files degrade to their own literal path — the same fail-safe
    `_identity` takes — so nothing a file the audit cannot read does can remove
    a readable report from the audit.

    OPT-IN, AND DRC-ONLY TODAY, deliberately. `_discover` serves six modes
    (drc/lvs/sta/power/em/ir) and the double-filing is measured in exactly one
    of them: `phase3_one_shot_runner` has a single "Mirror to reports/phase3/"
    site and it is the router-DRC one; every other `write_text(body)` in that
    runner files its report once. Turning this on project-wide would change
    discovery for five modes on no evidence, and it does: with it applied
    unconditionally, `test_sta_gate_step_scope::test_d1_unscoped_discovery_is_
    unchanged` drops from 5 files to 2, because that fixture writes two bodies
    across five paths. Widening it to another mode is a separate change and
    needs its own measured double-file, not this one's.
    """
    try:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return ("sha256", h.hexdigest())
    except OSError:
        return ("path", p)


def _name_token_match(name: str, prefixes: Sequence[str]) -> bool:
    """True iff some TOKEN of `name`'s stem STARTS WITH one of `prefixes`.

    The report-discovery globs are substring matches: `*ir*.rpt` matches any
    name with the two letters "ir" ANYWHERE in it. MEASURED 2026-08-29,
    spm x gf180mcuD: `sta_spef_repaired.rpt` -- an OpenSTA timing report --
    was pulled into BOTH the EM and the IR-drop audit, because "repa(ir)ed"
    contains "ir". Each audit then judged it against its own tool-signature and
    byte-size floors, which a timing report cannot meet, and emitted two
    severity=ERROR findings apiece:

        EM_REPORT_TOO_SMALL      report 976 B is below minimum 1024 B --
                                 suggests a hand-typed stub
        EM_NO_TOOL_SIGNATURE     report lacks any known em tool signature
        IR_DROP_REPORT_TOO_SMALL (same file)
        IR_DROP_NO_TOOL_SIGNATURE(same file)

    Four ERROR findings accusing a genuine STA report of being a hand-typed EM
    stub, from one glob. Both steps still PASSed -- the verdict needs only one
    authentic report and the real `em.rpt` (3314 B, OpenROAD PSM, 32101
    segments) is authentic -- so the findings never changed a verdict; they
    changed what the operator was TOLD. The phase-3 headline for the step read
    `PASS em_signoff EM_REPORT_TOO_SMALL: ... suggests a hand-typed stub`.

    Splitting the stem on non-alphanumerics and requiring a token to START with
    the prefix keeps every intentional name (`em.rpt`, `ir_drop.rpt`,
    `power_grid.rpt`, `static_ir.rpt`, `irdrop.rpt`, `pnr_em.rpt`) and drops
    the accidental interior match. chip-AGNOSTIC: filename lexing only."""
    stem = name.rsplit(".", 1)[0] if "." in name else name
    toks = [t for t in re.split(r"[^0-9a-zA-Z]+", stem.lower()) if t]
    return any(t.startswith(pre) for t in toks for pre in prefixes)


def _discover(project_dir: Path, patterns: List[str],
              exclude_name_tokens: Sequence[str] = (),
              collapse_identical: bool = False,
              defer_to_final: Optional[Tuple[str, str]] = None,
              deferred: Optional[List[Path]] = None) -> List[Path]:
    """Glob for files matching any of the given patterns recursively,
    skipping hidden / backup-flavored directories (#525), this program's own
    verdict documents, names carrying any of `exclude_name_tokens`, and
    anything outside an active `--under` scope. Aliases of one physical file
    collapse to a single entry (see `_identity`).

    `--subject` (F15): when the caller NAMES its subject files, those are the
    subject -- no glob is walked.  The step-23 wrapper names the per-corner
    reports STAPostPNR wrote (sha-verified against the tool's receipt before
    the audit starts), whose names no report glob matches."""
    if _SUBJECTS is not None:
        return [p for p in _SUBJECTS if p.is_file() and _in_scope(p)]
    found: List[Path] = []
    for pat in patterns:
        found.extend(project_dir.rglob(pat))
    # THE KEY IS CLAIMED ONLY BY A PATH THAT SURVIVES EVERY FILTER.
    # The filters key on the LITERAL path while `seen` keys on the physical
    # file, so the two disagree about which alias is which. With `seen.add`
    # above the filters, a backup/hidden/out-of-scope/excluded-name alias that
    # `rglob` happens to reach FIRST claimed the key and was then dropped —
    # and the canonical report behind it was skipped as a duplicate of a path
    # that is not in the output. Measured, one real report plus one same-inode
    # alias under a `*_bak/` directory::
    #
    #     alias reached first     _discover -> []            files_found=0
    #     alias reached later     _discover -> [drc_signoff] files_found=1
    #
    # `rglob` walks shallower matches first and siblings in directory order, so
    # which of the two the audit saw was decided by the alias's NAME AND DEPTH.
    # Adding the key last makes the surviving path the one that owns it, and
    # the filters idempotent with respect to walk order.
    #
    # `exclude_name_tokens` is here, rather than as a comprehension over the
    # RETURNED list, for exactly that reason. STA's report-class exclusion
    # (`crosstalk`/`drc`/`lvs`/... in the basename) used to run downstream of
    # this loop, so an alias whose basename carried an excluded token could
    # claim the key, evict the canonical report, and then be deleted by the
    # name filter — leaving the mode with ZERO files and a fabricated
    # `STA_REPORT_EXISTS` FAIL for a design whose STA report is right there::
    #
    #     alias `..._drc_alias.rpt` walked first, filter downstream
    #                             passed=False files_found=0 [STA_REPORT_EXISTS]
    #     same tree, filter inside _discover
    #                             passed=True  files_found=1
    #
    # `step_output_collector` renames a mirrored artefact to
    # `{parent.name}__{basename}` on a basename collision, so the flow itself
    # can produce a basename the canonical report does not have.
    seen = set()
    unique = []
    tokens = tuple(t.lower() for t in exclude_name_tokens)
    # `defer_to_final=(name_regex, final_name)`: a file whose name matches is
    # a copy that defers to `final_name` beside it, and is left out (listed in
    # `deferred`) ONLY when that final report is itself discovered. Filtered
    # here, before any key is claimed, for the reason above: a byte-identical
    # copy walked first must not evict the final report and then vanish.
    for p in found:
        key = _identity(p)
        if key in seen:
            continue
        if _is_backup_path(p, project_dir):
            continue
        if _is_own_verdict_document(p):
            continue
        if tokens and any(t in p.name.lower() for t in tokens):
            continue
        if not _in_scope(p):
            continue
        if defer_to_final and re.fullmatch(defer_to_final[0], p.name, re.I):
            final = p.with_name(defer_to_final[1])
            if (final.is_file() and not _is_backup_path(final, project_dir)
                    and _in_scope(final)):
                if deferred is not None and p not in deferred:
                    deferred.append(p)
                continue
        seen.add(key)
        unique.append(p)
    return _collapse_identical_content(unique) if collapse_identical else unique


def _collapse_identical_content(paths: List[Path]) -> List[Path]:
    """Drop survivors that are a byte-for-byte re-filing of an earlier one.

    Runs AFTER every filter and after the inode dedup, for the same reason
    those are ordered as they are: the key must be claimed by a path that is
    actually in the output. See `_content_key` for the measurement.

    Size is the pre-filter. A digest is read only for files whose size is
    shared by at least one other survivor, so a tree with no duplicates does
    no extra I/O at all, and a size we cannot stat leaves the file in place.
    """
    sizes = {}
    for p in paths:
        try:
            sz = p.stat().st_size
        except OSError:
            sz = None
        sizes[p] = sz
    counts = {}
    for sz in sizes.values():
        if sz:                      # 0 and None never collide -- see _content_key
            counts[sz] = counts.get(sz, 0) + 1
    seen = set()
    out = []
    for p in paths:
        sz = sizes[p]
        if not sz or counts.get(sz, 0) < 2:
            out.append(p)
            continue
        key = _content_key(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# THE MACHINE-READABLE HALF (steps 25 and 33)
#
# The flow declares BOTH halves of the same measurement::
#
#     step 25  reports/phase3/em.rpt      reports/phase3/em.json
#     step 33  reports/phase3/power.rpt   reports/phase3/power.json
#
# and `phase3_one_shot_runner` writes them together from one PSM / OpenSTA run.
# `_check_em` / `_check_power` discovered the `.rpt`-family only, so the JSON
# half — the half that carries the NUMBERS rather than the prose — was never
# opened by the gate that signs the step off. The text screens are keyword
# screens, and the emitted prose contains the keyword unconditionally:
#
#   em.rpt always ends with
#       "current density (Jpeak, derived): <max_cur> A per segment width"
#   which matches `current\s*density` even when em_segments.csv was never
#   produced, i.e. when `segments_analysed == 0` and `max_cur == 0.0`. The
#   keyword screen cannot tell a real EM measurement from an empty one; the
#   companion JSON says so in a field.
#
# So the companion is now READ, and read AS JSON — never text-scanned. (A text
# scan would be worse than nothing here: `re.search("mA", '"max_segment_...',
# re.I)` matches the substring "ma" in "max_segment_current_A" and would
# manufacture a density hit out of a field NAME.)
#
# CONTRADICTION AND VACUITY ARE FINDINGS; ABSENCE IS DISCLOSED. A project whose
# producer never wrote the companion keeps exactly the pre-change behaviour and
# the summary records `machine_readable_found: 0`, so a reader can see the
# verdict rests on the text alone.
# ---------------------------------------------------------------------------
#: ``mode -> (canonical declared path, basename searched project-wide)``.
#: Spelled as `flow/phase1_phase2_phase3.yaml` spells them.
_COMPANION_JSON = {
    "em": ("reports/phase3/em.json", "em.json"),
    "power": ("reports/phase3/power.json", "power.json"),
}


def _companion_docs(project_dir: Path, mode: str):
    """``[(path, parsed dict or None), ...]`` for a mode's declared JSON half.

    ``None`` means the file is there and is NOT a readable JSON object — that
    is a finding, not a reason to look away.
    """
    canonical, basename = _COMPANION_JSON[mode]
    cands: List[Path] = []
    direct = project_dir / canonical
    if (direct.is_file()
            and not _is_backup_path(direct, project_dir)
            and not _is_own_verdict_document(direct)
            and _in_scope(direct)):
        cands.append(direct)
    # `rglob(<basename>)` matches the exact filename only, so a run tree that
    # nests its reports one level deeper is still read and nothing else is.
    for q in _discover(project_dir, [basename]):
        if q not in cands:
            cands.append(q)
    out = []
    for q in cands:
        try:
            doc = json.loads(q.read_text(errors="replace"))
        except (OSError, ValueError):
            out.append((q, None))
            continue
        out.append((q, doc if isinstance(doc, dict) else None))
    return out


def _rel(path: Path, project_dir: Path) -> str:
    try:
        return str(path.relative_to(project_dir))
    except ValueError:
        return str(path)


# Tool signatures — a real EDA-tool report will contain AT LEAST one of these
# distinctive strings. Hand-authored stubs rarely reproduce them. Added
# 2026-04-22 after the <benchmark> v0.47 pilot where <1.5 KB hand-typed stubs
# passed every *_report_check via category-keyword matching alone.
TOOL_SIGNATURES = {
    "drc": [
        "klayout",             # KLayout DRC runset output
        "openroad",            # OpenROAD detailed-route DRC
        "detailed_route",
        "magic",               # Magic DRC
        "calibre",             # Calibre DRC
        "drt-",                # OpenROAD drt messages
        "lvs mismatch",        # DRC reports sometimes chain with LVS context
        "DRC clean",
        "violation report",
    ],
    "lvs": [
        "netgen",              # Netgen LVS
        "NET count",           # Netgen summary
        "Equivalence test",
        "Circuits match",
        "Circuits don't match",
        "Number of topologically valid",
        "calibre", "lvs_check",
    ],
    "power": [
        "openroad",
        "Power Report",        # OpenROAD report_power
        "Total Power",
        "Switching Power",
        "Leakage Power",
        "Internal Power",
        "Group: sequential",   # OpenROAD breakdown
        "Group: combinational",
        "mW\n", " uW\n", "  nW\n",
    ],
    "em": [
        "openroad",
        "Electromigration",
        "EM lifetime",
        "current density",
        "RMS current",
        "Peak current",
        "redhawk", "voltus",
    ],
    "ir_drop": [
        "openroad",
        "IR drop",
        "PSM",                 # Power Supply Metal (OpenROAD analyzer)
        "static IR",
        "dynamic IR",
        "worst voltage",
        "power grid",
        "voltage drop",
    ],
    "sta": [
        "OpenSTA",
        "Report",
        "Startpoint",
        "Endpoint",
        "data arrival time",
        "slack",
        "primetime",
    ],
    "antenna": [
        "openroad",            # OpenROAD check_antennas
        "check_antenna",
        "ANT-",                # OpenROAD ANT-0001/0002 message codes
        "antenna check",
        "net violations",      # "Found N net violations"
        "pin violations",
        "gate-oxide",
        # KLayout's own antenna output, in the exact forms it writes:
        # the RDB description line, and the rule descriptions' "gate oxide"
        # (a SPACE — the hyphenated form above never matches it).
        "report for antenna", "gate oxide area",
    ],
}

# Minimum reasonable file size (bytes) for a real report on a non-trivial
# design. A stub that only sums "violations: 0" across ~6 categories fits in
# well under 500 B, so the threshold filters obvious hand-typed cases while
# still allowing small open-flow outputs. Tuned from observed runs:
#   aon_timer OpenSTA pre-PnR:      5.2 KB
#   aon_timer Fault ATPG coverage:  225 KB
#   <benchmark>   Yosys synth stats:      3.1 KB
#   Agent's 2026-04-22 DRC stub:    0.62 KB  ← should be rejected
MIN_REPORT_BYTES = {
    "drc":     2048,
    "lvs":     1536,
    "power":   2048,
    "em":      1024,
    "ir_drop": 1024,
    "sta":     1024,
    "antenna": 200,   # OpenROAD check_antennas clean reports are short but real
}


def _has_tool_signature(text: str, mode: str) -> tuple[bool, str]:
    """Return (found, matched_pattern) — case-insensitive."""
    sigs = TOOL_SIGNATURES.get(mode, [])
    lower = text.lower()
    for sig in sigs:
        if sig.lower() in lower:
            return True, sig
    return False, ""


# A "strong" signature set per mode: distinctive multi-marker combinations
# that a hand-typed stub could not carry without effectively reproducing a
# real tool's content. When ALL markers of any group are present, the
# byte-size floor is waived (but the basic tool-signature requirement still
# applies). This prevents a genuinely real but COMPACT report from a SMALL
# design (e.g. an spm with a single timing path → a ~0.9 KB report_checks
# path table that legitimately carries Startpoint/Endpoint/arrival/slack)
# from being false-rejected as a "hand-typed stub". chip-AGNOSTIC: keyed on
# universal tool-output structure, not on any chip's signals.
STRONG_SIGNATURE_GROUPS = {
    "sta": [
        # A real OpenSTA report_checks path table.
        ["data arrival time", "data required time", "slack"],
        ["startpoint", "endpoint", "slack"],
    ],
    # v1.3.94 — a real KLayout NetlistComparer authoritative LVS report is
    # legitimately COMPACT (the comparer emits a verdict + device/net/pin
    # tallies, not a netgen-style multi-KB device-by-device transcript), so a
    # genuinely-clean small design (e.g. an spm on a commercial PDK) fell under
    # the 1536 B netgen-tuned floor and false-rejected as a "hand-typed stub".
    # The four-marker fingerprint below (engine name + comparer class + the
    # comparer-specific "power-only devices dropped" phrase + the terminal
    # verdict) is content a stub could not carry without reproducing the real
    # comparer's structured output. chip-AGNOSTIC.
    "lvs": [
        ["klayout", "netlistcomparer", "power-only devices dropped",
         "circuits match uniquely"],
    ],
    # An OpenROAD PSM `analyze_power_grid` IR-drop SUMMARY is legitimately
    # COMPACT: the runner emits a small structured JSON (engine id + power
    # nets + worst-drop + verdict), not a multi-KB transcript. So a
    # genuinely-real report from ANY design fell under the 1024 B floor
    # (MIN_REPORT_BYTES["ir_drop"]) and was false-rejected as a "hand-typed
    # stub" — the SAME small-design false-positive already fixed for `sta`
    # and `lvs` above, but never wired for `ir_drop`, which shares that
    # floor. Measured: 16 of 16 authentic openroad-psm ir_drop.json across
    # benchmark-data are <1024 B (197-611 B). The triple below is the
    # producer's self-identifying output — engine id + the producing
    # OpenROAD command + the power-net schema field — content a
    # "violations: 0" stub could not carry without reproducing a real PSM
    # run. The basic tool-signature requirement still gates. chip-AGNOSTIC:
    # universal PSM output structure, no chip / net / vendor / node literal.
    "ir_drop": [
        ["openroad-psm", "analyze_power_grid", "power_nets"],
    ],
}


def _has_strong_signature(text: str, mode: str) -> bool:
    lower = text.lower()
    for group in STRONG_SIGNATURE_GROUPS.get(mode, []):
        if all(marker.lower() in lower for marker in group):
            return True
    return False


# ---------------------------------------------------------------------------
# DOES THIS REPORT DESCRIBE THIS DESIGN? (vibe-ic#1119, A3_CROSS_DESIGN)
#
# THE DEFECT, MEASURED. The repository's adversarial role, run with a donor,
# copies a DIFFERENT
# design's same-named reports over a cell's and re-runs the cell's own sign-off
# gates. Against `spm/v1.9.96_gf180mcuD` with 149 artefacts taken from
# `sha256/clean_run_v1427_20260715`:
#
#     drc_report_check        rc 0 -> 0    SUCCEEDED
#     em_report_check         rc 0 -> 0    SUCCEEDED
#     ir_drop_report_check    rc 0 -> 0    SUCCEEDED
#     lvs / erc_density / antenna          SUCCEEDED
#
# Six sign-off gates certified one design using another design's evidence, and
# they did it while READING files that say whose evidence it is in plain text:
#
#     cell   phase3/reports/drc.rpt   <top-cell>chip_top</top-cell>
#     donor  phase3/reports/drc.rpt   <top-cell>sha256</top-cell>
#
# The identity was never hidden. Nothing asked. `report_belongs_to_project_check`
# (vibe-ic#587) already asks exactly this question of RUNNER json — "is this
# report about this project at all?" — and the same question had never been put
# to the TOOL reports a sign-off gate reads.
#
# WHAT IS COMPARED, AND WHY IT SURVIVES THE ATTACK. The reference is the set of
# module names the project's own Verilog declares. That is the DESIGN, not a
# statement about it: an attacker who replaces it has replaced the design rather
# than forged evidence about it, and the substitution attack does not touch it
# (it copies only `.rpt` / `.json` / `.log`). Measured on the published cell:
# 342 module names, `chip_top` among them and `sha256` not.
#
# ONLY TWO DIALECTS ARE READ, deliberately. A KLayout report database's
# `<top-cell>` and OpenROAD ODB's `Design:` line are unambiguous and
# tool-written. netgen's `Circuit 1:` lines were tried and REJECTED: they name
# sub-circuits rather than the design, and netgen truncates them to a fixed
# column, so `gf180mcu_fd_sc_mcu7t5v0__aoi21_` is not a name any tree declares.
# Reading them produced six false foreign-design findings on a pristine
# published cell. A binding that reddens honest evidence would be removed within
# the week and would take the real check with it.
#
# WHAT A REPORT THAT DECLARES NOTHING GETS. `NOT_DETERMINED`, recorded in the
# summary, and NOT a pass of this question — `antenna`, `lvs`, `power` and `sta`
# reports on the published cell name no design at all, which is a real gap and
# is published as one rather than being spelled "clean". This check can only
# ever FAIL a report that names a design this project does not contain; it
# cannot manufacture a verdict for one that names nothing.
_DESIGN_SOURCE_SUFFIXES = ("*.v", "*.sv")

_VERILOG_MODULE_RE = re.compile(
    r"(?m)^[ \t]*module[ \t]+([A-Za-z_][A-Za-z0-9_$]*)")

_DESIGN_NAME = r"([A-Za-z_][A-Za-z0-9_$]*)"

#: The tool-written declarations of WHOSE design a report is about, each with
#: how many of its matches count: ``"all"`` where every match is a top-level
#: statement, ``"last"`` where the format states sub-circuits first and the
#: design last.
_REPORT_DESIGN_RES = (
    # The RUNNER's own stamp, e.g. "measured_design: chip_top", written by
    # phase3_one_shot_runner alongside the sha256 of the DEF the tool read.
    #
    # SPELLED DIFFERENTLY FROM THE ODB LINE ON PURPOSE. `Design:` is what
    # OpenROAD prints about itself; `measured_design:` is the runner asserting
    # what it fed the tool. Collapsing them would let a report claim tool
    # provenance it does not have, and the distinction costs one regex.
    #
    # It exists because two producers wrote reports with NO design in them at
    # all: `reports/phase3/antenna.rpt` was byte-identical across two designs on
    # two PDKs, and `reports/density.{rpt,json}` differed only in their numbers.
    # No gate-side rule can bind evidence that carries no distinguishing byte.
    (re.compile(r"(?im)^[ \t]*measured_design[ \t]*:[ \t]*" + _DESIGN_NAME
                + r"[ \t]*$"), "all"),
    # KLayout report database (drc, erc/density)
    (re.compile(r"<top[-_]cell>\s*" + _DESIGN_NAME + r"\s*</top[-_]cell>"),
     "all"),
    # OpenROAD ODB, e.g. "[INFO ODB-0128] Design: chip_top"
    (re.compile(r"(?im)(?:^|\])[ \t]*Design[ \t]*:[ \t]*" + _DESIGN_NAME
                + r"[ \t]*$"), "all"),
    # netgen LVS, e.g. "Device classes chip_top and chip_top are equivalent."
    #
    # LAST MATCH ONLY, and that is the whole reason this dialect is usable.
    # netgen compares bottom-up: every standard cell gets one of these lines
    # before the design does, so "all" would enrol the entire cell library and
    # call a project foreign to its own PDK on any tree that does not also
    # carry the library's Verilog. Measured on the published cell and its
    # donor, in both `lvs.rpt` and `lvs_power_aware.rpt`, the last such line is
    # the top-level comparison and sits immediately above `Final result:` —
    # `chip_top` for the cell, `sha256` for the donor.
    #
    # This is NOT the `Circuit 1: ... |Circuit 2: ...` header, which was tried
    # first and rejected: netgen pads those to a fixed column, so a name longer
    # than the field arrives truncated and matches nothing that exists.
    (re.compile(r"(?im)^[ \t]*Device classes[ \t]+" + _DESIGN_NAME
                + r"[ \t]+and[ \t]+" + _DESIGN_NAME
                + r"[ \t]+are equivalent"), "last"),
)

#: `NOT_DETERMINED` is a THIRD value beside True/False and is spelled out so a
#: reader of the json cannot mistake it for either.
DESIGN_BINDING_NOT_DETERMINED = "NOT_DETERMINED"

_design_names_cache: dict = {}


def _project_design_names(project_dir: Path) -> set:
    """Every module name the project's own Verilog declares.

    Cached per project because a mode checker asks once and the walk is over
    every `.v`/`.sv` in the tree.
    """
    key = str(Path(project_dir).resolve())
    if key in _design_names_cache:
        return _design_names_cache[key]
    names: set = set()
    root = Path(project_dir)
    for pattern in _DESIGN_SOURCE_SUFFIXES:
        for fp in root.rglob(pattern):
            if not fp.is_file():
                continue
            try:
                names.update(_VERILOG_MODULE_RE.findall(
                    fp.read_text(errors="replace")))
            except OSError:
                continue
    _design_names_cache[key] = names
    return names


def _report_declared_designs(text: str) -> set:
    """The design names a report states it is about. Empty when it states none."""
    out: set = set()
    for rx, which in _REPORT_DESIGN_RES:
        found = rx.findall(text)
        if not found:
            continue
        if which == "last":
            found = found[-1:]
        for item in found:
            # A pattern with two groups (netgen names both sides of the
            # comparison) yields a tuple; a mismatch between them is itself
            # worth surfacing, so both are kept.
            if isinstance(item, tuple):
                out.update(n for n in item if n)
            else:
                out.add(item)
    return out


def _check_report_design_binding(files: List[Path], project_dir: Path,
                                 mode: str, result: AuditResult):
    """(ok, binding) — ok is False only for a report naming a FOREIGN design.

    `binding` is True (at least one report named this design), False (a report
    named another design) or `NOT_DETERMINED` (no report named any design).
    """
    declared = _project_design_names(project_dir)
    if not declared:
        # No Verilog in the tree: there is nothing to be foreign TO. Saying
        # "belongs" here would be a verdict about a comparison never made.
        return True, DESIGN_BINDING_NOT_DETERMINED
    foreign_seen = False
    own_seen = False
    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except (OSError, ValueError):
            continue
        names = _report_declared_designs(text)
        foreign = sorted(n for n in names if n not in declared)
        if foreign:
            foreign_seen = True
            result.findings.append(Finding(
                rule=f"{mode.upper()}_REPORT_IS_ABOUT_ANOTHER_DESIGN",
                severity="ERROR",
                message=(f"report states it is about {', '.join(foreign)}, "
                         f"which this project's Verilog does not declare. A "
                         f"sign-off gate that accepts it is certifying this "
                         f"design with another design's evidence (#1119 "
                         f"A3_CROSS_DESIGN)."),
                file=str(fp)))
        elif names:
            own_seen = True
    if foreign_seen:
        return False, False
    return True, (True if own_seen else DESIGN_BINDING_NOT_DETERMINED)


#: A RUNNER writes these; a TOOL writes the rest. Authenticity may not be
#: established from one, and neither may inauthenticity.
#:
#: THE DEFECT THIS CLOSES (vibe-ic#1119, attack A1_TAMPER_DESTRUCTIVE).
#: Overwriting every `*.rpt` in a published cell with the line "TAMPERED BY THE
#: ADVERSARY" flips six of seven sign-off gates rc 0 -> 1. `ir_drop` stayed at
#: rc 0, and its own json said why::
#:
#:     "passed": true,
#:     "findings": [
#:       {"rule": "IR_DROP_REPORT_TOO_SMALL",      "severity": "ERROR", ...},
#:       {"rule": "IR_DROP_NO_TOOL_SIGNATURE",     "severity": "ERROR", ...}
#:     ],
#:     "summary": {"tool_authentic": true, ...}
#:
#: Two ERROR findings, naming `reports/phase3/ir_drop.rpt` as a 26-byte
#: forgery, and a PASS. `_check_tool_authenticity` returns True when ANY
#: candidate passes, and the candidate that passed was
#: `reports/phase3/ir_drop.json` — which the attack never touched because it is
#: not a `.rpt`, and which the RUNNER writes: `step_canonicalize_artefacts` ->
#: `_emit_ir_em_reports` puts the PSM measurement there. So the gate's statement
#: that the IR-drop evidence is authentic was a statement about the runner's own
#: summary of it, and the tool's destroyed output was outvoted by it.
#:
#: THAT IS A SHAPE THIS REPOSITORY HAD ALREADY NAMED. `flow_matrix/README.md`
#: records two artefact findings that closed for the same reason — "the gate
#: believed a summary the RUNNER wrote instead of the output the TOOL wrote" —
#: and says in as many words that it "is the shape to look for next".
#:
#: MEASURED before changing it, over the pristine published cell: every one of
#: the seven modes has at least one authentic NON-json report, so no honest
#: evidence depends on a json to be believed. Only `ir_drop` and `antenna` had a
#: json carrying the verdict at all.
#:
#: NOTHING IS CHECKED LESS, and the json is not stopped from being CHECKED —
#: only from OUTVOTING. Every candidate is still judged and still produces its
#: findings; em's and power's companions still gate through `machine_ok`, and
#: ir_drop's `worst_ir_uv` / `budget_uv` comparison is untouched.
#:
#: A SUMMARY MAY STILL CARRY THE VERDICT WHEN IT IS ALL THERE IS, and that is not
#: a loophole, it is a measured requirement: `test_ir_drop_compact_report_strong
#: _signature` records that 16 of 16 authentic `openroad-psm` ir_drop.json in the
#: corpus are 197-611 B, under the 1024 B floor, and the strong-signature group
#: exists so those are not called hand-typed stubs. A first version of this fix
#: skipped every `.json` outright and broke both directions of that file. The
#: rule is therefore about PRECEDENCE, not about kind: where the tool's own
#: output is present, it is the thing that has to be genuine.
_RUNNER_WRITTEN_SUFFIXES = (".json",)


def _check_tool_authenticity(files: List[Path], mode: str,
                              result: AuditResult, *,
                              measured_rdb_files: Optional[set[Path]] = None) -> bool:
    """Append findings for missing tool signature + undersized reports.

    Returns True only if at least one candidate passed both checks — but a
    RUNNER-written summary counts only when no TOOL-written report was
    discovered at all. Where the tool's own output is present, that output is
    what must be genuine, and a summary of it cannot testify on its behalf.
    """
    any_authentic = False
    any_runner_authentic = False
    tool_written_present = any(
        fp.suffix not in _RUNNER_WRITTEN_SUFFIXES and fp.is_file()
        for fp in files)
    import _mcp_measurement as _meas
    for fp in files:
        try:
            size = fp.stat().st_size
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        # A `# MCP_MEASUREMENT:` stamp is metadata ABOUT this report, not part
        # of it. Both screens below are measured on what the TOOL wrote, so a
        # report cannot buy its way past a size floor or a signature match by
        # carrying a stamp that names the tool. MEASURED: without this, a
        # stamped 873 B link-failure report cleared the 1024 B floor and
        # matched the signature list, and two checks that had correctly refused
        # it began passing it.
        text, _stamp_bytes = _meas.strip_stamp(text)
        size -= _stamp_bytes
        # AN EMPTY REPORT IS NOT A HAND-TYPED STUB (vibe-ic, lane rbsha4).
        # Both screens below are about a SMALL FILE WITH CONTENT: one asks
        # whether there is too little of it to be real, the other whether the
        # text names a tool. A zero-byte file has no typed content to be a stub
        # and no text to carry a signature, so both accusations are category
        # errors against it -- and the EMPTY case already has an owner that
        # states the correct meaning: "the tool wrote its report and had no
        # violation to write, read as ZERO violations". MEASURED 2026-09-07
        # (sha256 x sky130A, v1.19.26, image 0.3.49): one 0-byte
        # routed_router.drc.rpt drew all THREE findings at once -- an INFO
        # saying it is a legitimate empty report and two ERRORs saying it is
        # not real tool output. By the flow's own design a CLEAN detailed route
        # writes exactly this file, so the screens accused every clean route.
        #
        # `continue` and NOT `any_authentic = True`, deliberately: dropping a
        # false accusation must not become a free pass. Silence is not
        # testimony, so an empty report still testifies to nothing and cannot
        # satisfy the authenticity requirement on its own.
        if size <= 0:
            continue
        # Waive the byte-size floor when the report carries a strong,
        # multi-marker tool signature (a real-but-compact small-design
        # report). The tool-signature requirement below still gates.
        strong = _has_strong_signature(text, mode)
        ok_size = size >= MIN_REPORT_BYTES.get(mode, 1024) or strong
        ok_sig, matched = _has_tool_signature(text, mode)
        # Native KLayout RDBs need not spell the engine's name. The DRC
        # caller supplies only parsed, countable RDBs with the same file's
        # measured KLayout invocation and current physical subject proved.
        # This supplies identity only; the byte floor still applies.
        if mode == "drc" and fp in (measured_rdb_files or ()):
            ok_sig = True
        if ok_size and ok_sig:
            if fp.suffix in _RUNNER_WRITTEN_SUFFIXES and tool_written_present:
                # Judged, and its findings kept — but it does not get to answer
                # for the tool report sitting beside it.
                any_runner_authentic = True
            else:
                any_authentic = True
            continue
        rel = str(fp)
        if not ok_size:
            result.findings.append(Finding(
                rule=f"{mode.upper()}_REPORT_TOO_SMALL", severity="ERROR",
                message=(f"report {size} B is below minimum "
                         f"{MIN_REPORT_BYTES.get(mode,1024)} B — "
                         f"suggests a hand-typed stub, not a real "
                         f"{mode} tool output"),
                file=rel,
            ))
        if not ok_sig:
            result.findings.append(Finding(
                rule=f"{mode.upper()}_NO_TOOL_SIGNATURE", severity="ERROR",
                message=(f"report lacks any known {mode} tool signature "
                         f"(one of: {TOOL_SIGNATURES[mode][:4]}... ). "
                         f"Hand-typed reports rejected."),
                file=rel,
            ))
    if any_authentic:
        return True
    if tool_written_present:
        # There WAS tool output and none of it was genuine. `any_runner_authentic`
        # is deliberately not consulted here: that is the A1 finding.
        return False
    return any_runner_authentic


# ---------------------------------------------------------------------------
# Mode checkers
# ---------------------------------------------------------------------------
# sha256×sky130A / #SS-SETUP — user-vs-foundry-stdcell DRC rule classification,
# IDENTICAL to the phase-3 drc step (_v1_6_604_classify_stdcell_violations). An
# open-PDK KLayout sign-off deck flags foundry-QUALIFIED std-cell-internal
# geometry (sky130 li.*/ct./licon/m1./met1./mcon — all BELOW the detailed
# router's met2 signal stack, and the contact/li layers are never emitted by the
# router) that the foundry's own Calibre sign-off passes. The phase-3 drc step
# already tiers those as WAIVED (0 user_routing_violations); but this auditor
# used to count the RAW <item> total, so a run the flow itself calls DRC-clean
# (0 user) FAILed here purely on foundry cell-library false-positives — the exact
# reason sky130 lagged gf180/ihp (whose decks lack the li family). The honesty
# gate is PRESERVED: any met2+/via2+ rule is ALWAYS user-routing and can NEVER be
# waived, so a genuine routing/enclosure/spacing defect on the signal stack still
# FAILs. chip-AGNOSTIC: rule-family grammar, no design/PDK/vendor literal.
_DRC_USER_ROUTING_RULE_PREFIXES = (
    "m2.", "met2.", "m2", "met2", "m3.", "met3.", "m3", "met3",
    "m4.", "met4.", "m4", "met4", "m5.", "met5.", "m5", "met5",
    "via2", "via3", "via4",
)
_DRC_FOUNDRY_STDCELL_RULE_PREFIXES = (
    "li.", "ct.", "licon", "m1.", "met1.", "mcon",
)


def _drc_rule_is_foundry_stdcell(rule: Optional[str]) -> bool:
    """True iff `rule` names a foundry-qualified std-cell-INTERNAL rule family
    that the phase-3 drc step waives — but NEVER for a met2+/via2+ user-routing
    rule (the honesty gate takes precedence). chip-AGNOSTIC.

    NOTE this answers only "is the RULE FAMILY one that CAN be waived". It does
    NOT establish that a given violation is actually std-cell-internal — that is
    a claim about WHERE the geometry is, and only the report's own `<cell>`
    attribution can support it. See `_drc_item_is_foundry_stdcell`.
    """
    r = (rule or "").strip().strip("'\"").lower()
    if any(r.startswith(p) for p in _DRC_USER_ROUTING_RULE_PREFIXES):
        return False
    return any(r.startswith(p) for p in _DRC_FOUNDRY_STDCELL_RULE_PREFIXES)


# A waiver that says "std-cell-INTERNAL" is a claim about WHERE the geometry
# sits, and a KLayout RDB states that on every item in a `<cell>` element. The
# rule-prefix test alone never read it — proxy instead of property.
#
# MEASURED on the tracked corpus, over the 85,593 items the prefix test waives
# across six real Phase-3 runs::
#
#     run A   40240 items   39805 (98.9%) attributed to `chip_top`
#     run B   19145 items   18875 (98.6%) attributed to `chip_top`
#     run C    7284 items    6896 (94.7%) attributed to `chip_top`
#     run D    5293 items    5062 (95.6%) attributed to `chip_top`
#
# `chip_top` is the design's OWN top cell — the RDB says so in its `<top-cell>`
# element. Only 1.1%–5.3% of the waived items are attributed to an actual
# foundry std-cell master. The attribution is informative rather than
# universally flattened, precisely BECAUSE those few hundred per run DO resolve
# to `sky130_fd_sc_hd__*` masters: KLayout kept the hierarchy it could.
#
# So the waiver's stated premise is contradicted by the report's own field on
# ~95% of what it waives. The rule family stays necessary — the met2+/via2+
# honesty gate is untouched — but it is no longer SUFFICIENT: a waiver must now
# be backed by the attribution it claims. An item the report places at the
# design's own top cell is user geometry and is COUNTED.
#
# chip-AGNOSTIC: matches the foundry cell-library NAMESPACE grammar shipped by
# the open PDKs, never a design/part/vendor literal.
_FOUNDRY_CELL_NAMESPACE_RE = re.compile(
    r"^(?:sky130_(?:fd|ef)_(?:sc|pr|io)\w*__|gf180mcu_fd_\w+__|sg13g2_\w+_)",
    re.I)


def _drc_cell_is_foundry_master(cell: Optional[str]) -> bool:
    """True iff `cell` names a foundry cell-library master (the only place
    std-cell-INTERNAL geometry can be). chip-AGNOSTIC namespace grammar."""
    c = (cell or "").strip().strip("'\"")
    return bool(c) and bool(_FOUNDRY_CELL_NAMESPACE_RE.match(c))


def _drc_item_is_foundry_stdcell(rule: Optional[str],
                                 cell: Optional[str]) -> bool:
    """True iff this violation may be tiered out as foundry std-cell-internal.

    BOTH must hold: the rule family must be waivable (never met2+/via2+), AND
    the report must itself attribute the item to a foundry cell master. When
    the report carries no attribution at all, the claim is unsupported and the
    item COUNTS — an absent field is not evidence.
    """
    return (_drc_rule_is_foundry_stdcell(rule)
            and _drc_cell_is_foundry_master(cell))


def _strip_leading_comment_block(text: str) -> str:
    """Drop a leading run of blank and `#`-comment lines, returning the body.

    THE DEFECT THIS CLOSES. `phase3_one_shot_runner.step_canonicalize_artefacts`
    publishes the Step-31 sign-off DRC certificate by PREPENDING a 4-line `#`
    provenance preamble to the KLayout RDB::

        # Sign-off DRC report (... Step 31 alias).
        # Source: phase3/reports/drc.rpt
        # Tool: klayout
        #
        <?xml version="1.0" encoding="utf-8"?>

    The dialect sniff below is `text.lstrip().startswith(...)`, anchored to the
    first non-WHITESPACE character of the whole file. `#` is not whitespace, so
    both prefix tests failed, `ET.fromstring` was NEVER CALLED, and the three
    text regexes then ran over 2–12 MB of RDB — which carries rule names and
    coordinates but no summary count (`grep -ic violation` over one such report
    returns 0). Every branch missed and the function returned None.

    Scoped as the flow declares it — step 31 is `drc_report_check . --mode drc
    --under reports/phase3/drc_signoff.rpt`, a SINGLE-FILE scope — that one
    file is the entire discovery set, so `determined_files == 0` and the gate
    reported DRC_VIOLATION_COUNT_UNDETERMINED on eight tracked runs.

    NOT "the header breaks parsing" — 22 other tracked reports carry a `#`
    preamble and read fine, because their bodies are text and the text greps
    never cared. The failure needs the preamble AND an XML-only body. Stripping
    the preamble unconditionally would be the wrong fix shape for that reason;
    it is stripped here only to find the dialect, and the text greps still run
    on the original bytes.
    """
    lines = text.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        s = line.strip()
        if s and not s.startswith("#"):
            return "".join(lines[idx:])
    return ""


#: expat's `XML_Parse` takes the buffer length as a C `int`, so a single call
#: with a body >= 2**31 bytes raises `OverflowError: size does not fit in an
#: int` — NOT an `ET.ParseError`. `ET.fromstring` hands the whole body to expat
#: in one such call, so on a KLayout RDB at/over this size it CRASHES its
#: caller. MEASURED: a 2,480,593,258-byte FreePDK45 sign-off `drc_signoff.rpt`
#: (nangate45) crashed `_drc_real_violation_count`, so Step-31 Physical
#: Verification returned "launch-failed CRASHED" — the checker could neither
#: pass nor FAIL the design. `_count_rdb_items_streaming` streams the same body
#: through `iterparse`, which feeds expat in sub-INT_MAX chunks.
_EXPAT_SINGLE_BUFFER_MAX = 2 ** 31 - 1


def _count_rdb_items_streaming(body: str) -> Optional[Tuple[int, int]]:
    """`(user, foundry_stdcell)` KLayout-RDB item counts for a body too large
    for `ET.fromstring`, or None when unreadable.

    Streams the body through `xml.etree.ElementTree.iterparse`, which reads and
    feeds expat incrementally so no single `XML_Parse` call ever exceeds the
    C-int length limit that makes `ET.fromstring` raise `OverflowError` at/over
    2**31 bytes. The per-item attribution and the terminal None cases are the
    SAME as the in-memory branch below — only how the bytes reach the parser
    changes:
      * `<items>` container absent (bare `<report-database>`) -> None;
      * truncated / malformed mid-stream -> `ET.ParseError` -> None;
      * well-formed with N items -> the (user, stdcell) split.
    `_el.clear()` drops each processed item so memory stays bounded on a
    multi-million-item report. Pure; no I/O beyond the in-memory buffer.
    """
    user = 0
    stdcell = 0
    seen_items = False
    try:
        for _ev, _el in ET.iterparse(io.StringIO(body), events=("end",)):
            if _el.tag == "item":
                _cat = _el.find("category")
                _rule = _cat.text if _cat is not None else ""
                _cel = _el.find("cell")
                _cell = _cel.text if _cel is not None else ""
                if _drc_item_is_foundry_stdcell(_rule, _cell):
                    stdcell += 1
                else:
                    user += 1
                _el.clear()
            elif _el.tag == "items":
                seen_items = True
    except ET.ParseError:
        return None
    if not seen_items:
        return None
    return (user, stdcell)


def _drc_real_violation_count(text: str) -> Optional[Tuple[int, int]]:
    """Return `(user_routing, foundry_stdcell_excluded)` DRC violation counts in
    a report body, or None if a count cannot be determined. Three dialects,
    chip-agnostic (grammar, not any design/PDK/vendor literal):

      klayout RDB/.lyrdb XML   count actual <item> elements under <items>,
                               SPLIT by each item's <category> rule into
                               user-routing (the gating count) vs foundry-
                               qualified std-cell-internal (disclosed, waived —
                               same tiering as the phase-3 drc step).
      SVRF-native              the per-rule `FAIL|PASS|SKIP <rule> ... -> <n>`
                               tally the foundry deck's native runner emits.
                               The design-level violation count is the number
                               of FAILing RULES; this report never emits a
                               "total violations:" line.
      plain-text summary       "total violations: N" / "N violations" /
                               the magic-style "DRC errors found: N" — no
                               per-item rule, so the whole N is treated as
                               user-routing (conservative: never auto-waived).

    THE SVRF DIALECT IS NEW AND ITS ABSENCE WAS LOAD-BEARING. The flow's own
    authority order for the sign-off DRC alias (`phase3_one_shot_runner`) puts
    the SVRF report ABOVE the KLayout OSS-deck report — it is the foundry's own
    rule deck. `signoff_audit` has parsed that dialect since the day a clean
    4533-PASS sign-off was measured as UNPARSED and hard-FAILed the tapeout
    checklist. This function never learned it. MEASURED on origin/main, the
    same clean report at the sign-off path::

        drc_report_check . --mode drc --under reports/phase3/drc_signoff.rpt
            -> rc=1  determined_files:0  real_violation_total:0

    i.e. the HIGHEST-authority producer was the one the Step-31 substance gate
    could not read, while the router's projection — the LOWEST — measured rc=0.
    The grammar is imported from `_signoff_drc_format`, not re-authored: three
    private copies of it is how the divergence happened.

    Returns None (never (0,0)) when NEITHER dialect yields a number — an
    unreadable or unrecognised report must not be credited as clean.
                               SPLIT by each item's <category> rule AND its
                               <cell> attribution into user-routing (the gating
                               count) vs foundry-qualified std-cell-internal
                               (disclosed, waived). Recognised whether the RDB
                               starts at byte 0 or behind a `#` preamble.
      plain-text summary       an anchored summary line ("violation count
                               summary: N", "violation report: N", "total
                               violations: N", the magic-style "DRC errors
                               found: N"), else a bare "N violations" — no
                               per-item rule, so the whole N is treated as
                               user-routing (conservative: never auto-waived).

    Returns None (never (0,0)) when no dialect yields a trustworthy number — an
    unreadable or unrecognised report must not be credited as clean. THE CALLER
    MUST TREAT None AS "NOT READABLE" AND FAIL, never as an absence of
    violations; `_check_drc` does, per file, and says which file.

    MEASURED, the reason this function exists: the prior check counted which
    RULE-CATEGORY WORDS merely appeared anywhere in the text; counting real
    <item> elements is immune to a fabricated failure SENTENCE injected
    elsewhere in the file. The user/std-cell split (added for sha256×sky130A)
    keeps that immunity while no longer FAILing a clean design on the open
    deck's foundry-cell false-positives — the honesty gate keeps every met2+
    signal-stack defect gating.
    """
    body = _strip_leading_comment_block(text)
    stripped = body.lstrip()
    if stripped.startswith("<?xml") or stripped.startswith("<report-database"):
        # THE XML BRANCH IS TERMINAL. A body that ANNOUNCED itself as a KLayout
        # RDB and then could not be counted is UNREADABLE — it must never fall
        # through to the text greps below.
        #
        # MEASURED, why this matters (real corpus RDB, 7,284 items):
        #     intact                                          -> (0, 7284)
        #     truncated mid-file                              -> None
        #     truncated + "<!-- summary: 0 violations -->"     -> (0, 0)  CLEAN
        # and a well-formed `<report-database>` with `<items>` ABSENT:
        #     bare                                            -> None
        #     + "0 violations"                                -> (0, 0)  CLEAN
        # A KLayout run killed mid-write (disk/OOM/timeout) on a dirty design
        # was graded CLEAN if any "N violations"-shaped sentence existed
        # anywhere in the bytes — the exact injection this function was written
        # to close, re-entered through the parse-failure door.
        # A body at/over expat's single-call length limit crashes
        # `ET.fromstring` with OverflowError (see `_EXPAT_SINGLE_BUFFER_MAX`);
        # stream it instead so the checker returns a verdict rather than
        # crashing. Below the limit the ORIGINAL in-memory path is unchanged,
        # byte-for-byte, so every existing corpus report is graded identically.
        if len(body) > _EXPAT_SINGLE_BUFFER_MAX:
            return _count_rdb_items_streaming(body)
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return None
        except OverflowError:
            # Under the char threshold but over expat's BYTE limit (a multibyte
            # encoding), or an allocation ceiling: stream rather than crash.
            return _count_rdb_items_streaming(body)
        items = root.find(".//items")
        if items is None:
            return None
        user = 0
        stdcell = 0
        for _it in items.findall("item"):
            _cat = _it.find("category")
            _rule = _cat.text if _cat is not None else ""
            _cel = _it.find("cell")
            _cell = _cel.text if _cel is not None else ""
            if _drc_item_is_foundry_stdcell(_rule, _cell):
                stdcell += 1
            else:
                user += 1
        return (user, stdcell)
    # SVRF FIRST (#705). The flow's own authority order for the sign-off DRC
    # alias puts the foundry's native rule-deck report ABOVE the KLayout
    # OSS-deck report, and this function never learned that dialect: measured on
    # a clean 4533-PASS sign-off, the HIGHEST-authority producer was the one the
    # Step-31 substance gate could not read (rc=1, determined_files:0) while the
    # router's projection — the LOWEST — measured rc=0. The grammar is imported
    # from `_signoff_drc_format`, not re-authored; three private copies of it is
    # how the divergence happened.
    _svrf = _sdf.svrf_fail_count(text)
    if _svrf is not None:
        return (_svrf, 0)
    # Text dialects. ANCHORED summary patterns are tried FIRST, so a real
    # summary line wins over an incidental "N violations" phrase regardless of
    # where each sits in the file. The text greps run on the ORIGINAL text, so
    # the 22 corpus reports that carry a `#` preamble AND a text body are
    # byte-for-byte unaffected (measured: 22/22 identical).
    # `^[INFO] COUNT: N` is MAGIC's own count as the LibreLane `Magic.DRC` step
    # writes it, and MEASURED on a real run it is the only verdict marker that
    # appears at all — `DRC errors found: N` is never emitted by that flow, so
    # a clean Magic DRC returned None here and the file was reported UNREADABLE
    # while the shuttle operator's arm passed the same layout. ANCHORED to line
    # start (and to the optional [INFO] tag) so it cannot pick up an incidental
    # "count: N" from prose elsewhere in an 11 MB transcript; it sits with the
    # other ANCHORED patterns, above the loose fallback, for the same reason
    # they do.
    for _rx in (r"violation\s+count\s+summary\s*:\s*(\d+)",
                r"violation\s+report\s*:\s*(\d+)",
                r"total\s+violations?\s*[:=]?\s*(\d+)",
                r"DRC errors? found:\s*(\d+)",
                r"(?m)^\s*(?:\[INFO\]\s*)?COUNT\s*:\s*(\d+)\s*$"):
        m = re.search(_rx, text, re.I)
        if m:
            return (int(m.group(1)), 0)
    # THE LOOSE FALLBACK, AND WHY IT TAKES THE MAXIMUM (vibe-ic#726).
    #
    # It used to take the FIRST match anywhere in the file. Measured on a real
    # tracked report with NO injection of any kind —
    # `subservient/reports/phase3/drc_router.rpt` — dropping the first 30 lines
    # flips the verdict from 72 violations to CLEAN, because the anchored
    # summary lives at lines 21-22 and OpenROAD's `detailed_route` progress
    # output below it reads
    #
    #     Completing 10% with 0 violations.
    #
    # Those lines are present in EVERY router report in the corpus. So a
    # truncated report — a tool killed mid-write, a log rotated, a tail copied —
    # was graded clean by its own progress counter.
    #
    # Progress lines are dropped by SHAPE, not by tool name, and then the
    # MAXIMUM of what remains is taken. Maximum is the fail-safe direction: this
    # is already the last resort, reached only when no anchored summary parsed,
    # and under-reporting grades a dirty design clean while over-reporting only
    # triggers a look.
    _progress = re.compile(r"\b(?:completing|progress|elapsed|iter(?:ation)?)\b"
                           r"|\b\d+\s?%\b", re.I)
    counts = [int(m.group(1))
              for ln in text.splitlines() if not _progress.search(ln)
              for m in re.finditer(r"(\d+)\s+(?:total\s+)?violations?\b", ln, re.I)]
    if counts:
        return (max(counts), 0)
    return None


def _drc_tool_final_violation_count(text: str) -> Optional[int]:
    """The TOOL's own last word on its violation count, or ``None``.

    THE DEFECT THIS CLOSES (63x8 artefact finding, step 21 / dimension 2).
    ``reports/phase3/drc_router.rpt`` carries BOTH a runner-written summary at
    the top AND the router's own transcript below it. `_drc_real_violation_
    count` reads the summary and stops. MEASURED on the published run named by
    the ledger entry ART-ROUTER-FINAL-ITERATION, rewriting the router's FINAL
    detailed-route iteration from ``Number of violations = 0`` to ``= 12`` and
    leaving the summary alone::

        drc_report_check . --mode drc --under ... --json ...
            -> rc=0   real_violation_total=0

    A routed design finishing with 12 unresolved violations, certified clean,
    with the contradicting number sitting in the file the gate had just parsed.
    The same gate on the same file DOES redden when the SUMMARY is edited — so
    the green was a statement about the runner's arithmetic, not the router's.

    THE GRAMMAR IS IMPORTED, NOT RE-AUTHORED. `_sdf.router_iter_last_count` is
    the one implementation `phase3_one_shot_runner._drt_final_violations` and
    `signoff_audit`'s plain-text reader already share, and its module comment
    says why: three private copies of it is how the readers of one report came
    to return different numbers for it. A fourth copy here would be the same
    mistake with this defect's name on it — and it would be the WORSE fourth
    copy, because a cross-check that reads a different grammar from the runner
    it is checking would raise contradictions that are its own.

    That parser also owns the two facts a hand-rolled pattern gets wrong: the
    count is per-ITERATION and falls as the router converges, so only the LAST
    is a verdict; and an older build spells the same tally
    ``Completing 100% with N violations``, which must be an EXCLUSIVE fallback
    or one report is counted twice.

    Returns ``None`` when the body carries no router-iteration grammar at all —
    a KLayout RDB, an SVRF tally, a foundry deck transcript. That is NOT a zero
    and must never be collapsed to one: it means this report has no tool-final
    word to corroborate against, and `_check_drc` discloses that as an
    uncorroborated file rather than crediting the silence as agreement.
    """
    return _sdf.router_iter_last_count(text)


def _empty_router_drc_receipt(report: Path) -> Optional[Path]:
    """The completed route's digest-bound zero receipt for this empty report.

    An adjacent log, including an older route's log, is not evidence that the
    invocation which wrote this report finished cleanly.
    """
    if report.name != "routed_router.drc.rpt":
        return None
    # Step snapshots publish this report as a symlink. The receipt belongs to
    # the file that actually wrote the bytes, beside the canonical report and
    # its log/DEF, not beside the snapshot link. step_pnr writes it only in
    # <project>/phase3/stage3/pnr, so the project is read from the LITERAL
    # path (the parent of its `steps/` tree, or of that pnr directory) and
    # the RESOLVED report must be that project's canonical one. A dangling
    # alias, a redirected leaf link and a redirected DIRECTORY (any symlinked
    # component inside the project) all fail that comparison.
    try:
        literal = Path(os.path.abspath(report))
        projects = []
        if literal.parts[-4:-1] == ("phase3", "stage3", "pnr"):
            projects.append(literal.parents[3])
        steps_root = next((parent for parent in literal.parents
                           if parent.name == "steps"), None)
        if steps_root is not None:
            projects.append(steps_root.parent)
        report = literal.resolve(strict=True)
        if not any(report == project.resolve()
                   / "phase3/stage3/pnr/routed_router.drc.rpt"
                   for project in projects):
            return None
    except (OSError, RuntimeError):
        return None
    receipt = report.parent / "routed_router.drc.receipt.json"
    log = report.parent / "openroad.log"
    try:
        rec = json.loads(receipt.read_text())
        def_name = rec.get("routed_def")
        if (rec.get("schema") != "vibeic.router_drc_receipt.v1"
                or rec.get("producer") != "phase3_one_shot_runner.step_pnr"
                or rec.get("report") != report.name or rec.get("log") != log.name
                or rec.get("route_completed") is not True
                or rec.get("current_invocation_count") != 0
                or not isinstance(def_name, str)
                or Path(def_name).name != def_name or not def_name.endswith(".def")
                or rec.get("final_drt_count") != 0):
            return None
        routed_def = report.parent / def_name
        for path, key in ((report, "report_sha256"), (log, "log_sha256"),
                          (routed_def, "routed_def_sha256")):
            if hashlib.sha256(path.read_bytes()).hexdigest() != rec.get(key):
                return None
        if _drc_tool_final_violation_count(log.read_text(errors="replace")) != 0:
            return None
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return receipt


def _measured_klayout_receipt_files(project_dir: Path,
                                    files: Sequence[Path]) -> set[Path]:
    """Return RDB reports bound to one successful measured KLayout invocation.

    A KLayout RDB can express a zero by carrying an empty ``<items>`` element,
    but it need not print a textual final-count line.  That shape is not a
    certificate by itself.  The only alternate corroboration accepted here is
    the runner's append-only invocation record: it must bind an existing GDS
    input and both the exact report and its command transcript by digest.

    This is intentionally narrower than trusting a prose receipt.  A stale
    report, a missing transcript, a changed GDS, a non-zero tool exit, or a
    back-filled (non-measured) declaration returns no corroboration.
    """
    ledger = project_dir / "provenance.jsonl"
    if not ledger.is_file():
        return set()

    def digest(path: Path) -> Optional[str]:
        if not path.is_file():
            return None
        h = hashlib.sha256()
        try:
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
        except OSError:
            return None
        return "sha256:" + h.hexdigest()

    records = []
    for line in ledger.read_text(errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            records.append(row)

    bound: set[Path] = set()
    for report in files:
        try:
            rel = report.resolve().relative_to(project_dir.resolve()).as_posix()
        except (OSError, ValueError):
            continue
        report_sha = digest(report)
        # ONE PATH, USED FOR BOTH HALVES OF THE LOOKUP.
        #
        # THE DEFECT, MEASURED (lane icgate1, 2026-09-21) on `spm x gf180mcuD`
        # run8's own bytes and its own `provenance.jsonl`: the report was
        # RESOLVED to build `rel` — so the ledger is queried under the
        # canonical name — while the transcript was taken from the LITERAL path
        # this loop happened to be handed. Those are two different frames for
        # one question, and `_discover` decides which by walk order.
        #
        # The step-output collector publishes each canonical report a second
        # time as a SYMLINK under `steps/<phase>/<stage>/<step>/` and publishes
        # NO `.log` beside it (`ls -la` on that run lists drc_signoff.rpt,
        # erc.rpt, lvs.json, lvs.rpt, magic_illegal_overlap.json, outputs.json
        # — no transcript). `_identity` collapses the pair by inode, so exactly
        # ONE of the two survives discovery and WHICH ONE is decided by
        # `os.scandir` order — a property of the directory, not of the design.
        #
        # SAME tree, SAME ledger, SAME inode, the ONLY variable being which
        # alias was handed over:
        #     reports/phase3/drc_signoff.rpt          -> corroborated 1
        #     steps/.../31_.../drc_signoff.rpt        -> corroborated 0
        # run8 drew the second, so `receipt_corroborated_files: 0` and
        # DRC_ZERO_NOT_MEASURED over a real, measured, exit-0, digest-bound
        # KLayout sign-off whose row the runner had already written
        # (`phase3_one_shot_runner._rebind_measured_drc_invocation_to_canonical_path`).
        # A sign-off gate refused a clean layout because of a directory hash.
        #
        # NOTHING IS RELAXED. The transcript must still EXIST, its digest must
        # still equal the digest the ledger declared for it, the report's
        # digest must still match, and a GDS input must still match on disk.
        # All this changes is that the file read and the key queried are now
        # derived from the same `rel` — so an alias cannot answer a question
        # about a file it is an alias OF.
        transcript = project_dir / Path(rel).with_suffix(".log")
        log_sha = digest(transcript)
        if not report_sha or not log_sha:
            continue
        # The publisher copies the native RDB and transcript, but declares
        # only the RDB's immutable transform.  Follow that single copy; the
        # transcript must be the native sibling and remain byte-identical.
        # Neither the transform nor equal bytes alone are a measurement.
        source_rel = rel
        for transform in reversed(records):
            if (transform.get("record") != "declared_transform" or
                    transform.get("producing_step") != "drc:signoff"):
                continue
            outputs = transform.get("outputs") or {}
            try:
                named = [value for name, value in outputs.items()
                         if (project_dir / name).resolve() == report.resolve()]
                if not named:
                    continue
                inputs = transform.get("inputs") or {}
                if (named != [report_sha] or len(inputs) != 1 or
                        transform.get("exit_code") != 0):
                    source_rel = None
                    break
                name, expected = next(iter(inputs.items()))
                source = (project_dir / name).resolve()
                source_rel = source.relative_to(project_dir.resolve()).as_posix()
                source_log = source.with_suffix(".log")
                if (expected != digest(source) or expected != report_sha or
                        source.read_bytes() != report.read_bytes() or
                        digest(source_log) != log_sha or
                        source_log.read_bytes() != transcript.read_bytes()):
                    source_rel = None
                break
            except (OSError, ValueError, TypeError, AttributeError):
                source_rel = None
                break
        if source_rel is None:
            continue
        for row in reversed(records):
            outputs, inputs = row.get("outputs"), row.get("inputs")
            if (row.get("record") != "invocation" or
                    row.get("measured") is not True or
                    row.get("tool") != "klayout" or
                    row.get("exit_code") != 0 or
                    not isinstance(outputs, dict) or not isinstance(inputs, dict)):
                continue
            if outputs.get(source_rel) != report_sha:
                continue
            log_rel = str(Path(source_rel).with_suffix(".log"))
            if outputs.get(log_rel) != log_sha:
                continue
            has_bound_gds = False
            for input_rel, input_sha in inputs.items():
                if not isinstance(input_rel, str) or not input_rel.lower().endswith(".gds"):
                    continue
                candidate = project_dir / input_rel
                try:
                    candidate.resolve().relative_to(project_dir.resolve())
                except (OSError, ValueError):
                    continue
                if input_sha == digest(candidate):
                    has_bound_gds = True
                    break
            if has_bound_gds:
                bound.add(report)
                break
    return bound



#: How much of a sibling tool log this reader will read to answer "did the deck
#: mention this rule class at all". Bounded: a log is an unbounded artefact and
#: this is a diagnostic line, not a measurement.
_SIBLING_LOG_READ_BYTES = 4_000_000


def _category_also_named_beside(cat_regex: "re.Pattern[str]",
                                files: Sequence[Path],
                                project_dir: Path) -> str:
    """The tool log beside a scoped report that DOES name this rule class.

    Returns its project-relative path, or "" if none does.

    Reads ONLY — nothing here enters `cats_found`, the violation count, the
    verdict or any summary number. It answers one diagnostic question a reader
    otherwise cannot: was this rule class absent from the REPORT, or absent
    from the RUN?
    """
    seen: set = set()
    for fp in files:
        for sib in sorted(Path(fp).parent.glob("*.log")):
            if sib in seen or sib in set(files):
                continue
            seen.add(sib)
            try:
                text = sib.open("r", errors="replace").read(
                    _SIBLING_LOG_READ_BYTES)
            except OSError:
                continue
            if cat_regex.search(text):
                return _rel(sib, project_dir)
    return ""


def _category_absence_message(cat: str, cat_regex: "re.Pattern[str]",
                              files: Sequence[Path],
                              project_dir: Path) -> str:
    """Why a rule class is not named in the reports — as a fact about the
    REPORT, never as a claim about the design.

    R-icgate3 — MEASURED on spm run15 (8HD-4, `_lane_icspm5/run15`), step 31's
    sign-off audit, whose FIRST finding read

        DRC category 'density' not found in reports

    A reader takes that as "density was not checked". It was. The run's own
    tool log (`reports/phase3/drc_signoff.log`) records

        Selected decks: ... cup, density, df_10, ...
        Executing rule PL.8 / M1.4 / M2.4 / M3.4 / M4.4 / M5.4

    and the report carries ZERO items for any of them, i.e. all six PASSED.
    They are missing from the report because this open PDK's density deck calls
    `extent.output(...)` INSIDE the `if` that detects the violation, so a clean
    density rule emits no category at all. The report declares 764 rule classes
    and 762 of them carry zero items, so the format does declare clean rules —
    these six are the exception, and 11 of the 774 rules the log says executed
    never declared a class, the six density rules among them.

    The old sentence could only be satisfied by a die that FAILS density: it
    reported the good outcome as a gap. It stays a WARNING and stays
    informational (this probe has never gated `passed`); what changes is that
    it now names the SCOPE it searched and, when the deck's own log names the
    class, says so — which is the difference between "not checked" and "checked
    and clean".

    chip-AGNOSTIC: no IC, vendor, SKU or process is reasoned about; the rule
    class words are this reader's own existing table.
    """
    where = ", ".join(sorted(_rel(f, project_dir) for f in files)) or "no report"
    beside = _category_also_named_beside(cat_regex, files, project_dir)
    if beside:
        return (f"DRC category '{cat}' is not named in the report(s) this audit "
                f"was scoped to ({where}), but the tool's own log beside them "
                f"({beside}) DOES name it. A report that lists only VIOLATIONS "
                f"cannot name a rule class that passed, so this is not evidence "
                f"the class went unchecked — read {beside} for what the deck "
                f"ran")
    return (f"DRC category '{cat}' is not named in the report(s) this audit was "
            f"scoped to ({where}), and no tool log beside them names it either. "
            f"Whether the deck has a rule of this class cannot be decided from "
            f"these artefacts")


def _check_drc(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:drc", passed=False)
    # `.lyrdb` IS THE KLAYOUT REPORT DATABASE, and this audit already knows how
    # to read one: `_drc_real_violation_count` lists "klayout RDB/.lyrdb XML" as
    # its first accepted dialect and `_count_rdb_items_streaming` parses it.
    # Until this line it could not FIND one — the glob accepted only
    # .rpt/.log/.txt, which is not the extension KLayout writes.
    # MEASURED (gf180mcuD chip path, 2026-08-21): a chip whose KLayout DRC is
    # genuinely 0-violation, with `drc.klayout.lyrdb` sitting in the project,
    # returned "No DRC report found" -> `Checker.KLayoutDRC` FAIL on our own
    # precheck arm, while the shuttle operator's arm PASSED the same GDS. Step
    # 37.5ic reads opposite conclusive verdicts from its two arms as a
    # DISAGREEMENT and refuses — so a discovery gap here manufactures the exact
    # outcome that step calls its most valuable signal. Selection is by CONTENT
    # (the parser sniffs `<items>`), so widening the glob cannot mis-parse a
    # file: an unreadable one still returns None and is reported unreadable.
    intermediate: List[Path] = []
    files = _discover(project_dir, ["*drc*.rpt", "*drc*.log", "*drc*.txt",
                                     "*drc*.lyrdb",
                                     "*DRC*.rpt", "*DRC*.log", "*DRC*.txt",
                                     "*DRC*.lyrdb"],
                      collapse_identical=True,
                      defer_to_final=(r"routed_router\.drc\.iter[0-9]+\.rpt",
                                      "routed_router.drc.rpt"),
                      deferred=intermediate)
    # step_pnr copies each routing rung's report to routed_router.drc.iterN.rpt
    # beside routed_router.drc.rpt (the last rung's copy is byte-identical to
    # it). Those copies are not the final route's answer and do not vote --
    # but only while the final report they defer to is itself discovered;
    # with it absent an iteration copy is the only router evidence and votes.
    ignored_intermediate = [str(p.relative_to(project_dir))
                            for p in intermediate]
    if not files:
        result.findings.append(Finding(
            rule="DRC_REPORT_EXISTS", severity="ERROR",
            message="No DRC report found (searched *drc*.rpt/log/txt/lyrdb)"))
        result.summary = {"files_found": 0, "categories_found": [],
                          "ignored_intermediate_reports": ignored_intermediate}
        return result

    categories_re = {
        "spacing": re.compile(r"spac", re.I),
        "width": re.compile(r"width|min\s*width", re.I),
        "density": re.compile(r"density", re.I),
        # THE WORD IS NOT THE VOCABULARY (vibe-ic#2172's third recorded item).
        # A KLayout gf180 sign-off RDB names its antenna rules `ANT.8`,
        # `ANT.16_ii_ANT.4`, and describes them as "related gate oxide area".
        # It never writes the word "antenna". MEASURED on the published corpus:
        # `ic/spm/v1.9.96_gf180mcuD/reports/phase3/drc_signoff.rpt` carries 20
        # antenna rule instances and the literal count is 0, so the report was
        # classified `[spacing, width, via, enclosure]` -- antenna absent from a
        # report that is 20/20 antenna.
        #
        # NOT simply reused from `_TOOL_SIGNATURES["antenna"]` below, and that
        # is deliberate: the two tables answer different questions. That one
        # asks "did an antenna TOOL write this", so it carries `openroad` and
        # `net violations` -- tokens that would put every OpenROAD DRC report
        # into the antenna category here. This one asks "does this report talk
        # about antenna RULES", and its tokens are the ones the decks
        # themselves write.
        #
        # `ANT[.-]\d` is anchored on both sides for a reason: `\b` plus a
        # required separator AND digit is what keeps SLANT, GIANT, ANTI and a
        # bare "ANT" out. OVER-MATCH CONTROL over the 31 DRC reports of the
        # published corpus: 14 matched before and still match, 2 files / 1 ROOT
        # gained (the spm report above, and it is the same report under two
        # paths), 15 still do not match. Nothing was swept in.
        "antenna": re.compile(r"antenna|\bANT[.-]\d|gate[- ]oxide", re.I),
        "via": re.compile(r"\bvia\b", re.I),
        "enclosure": re.compile(r"enclos", re.I),
    }
    # A STATED COUNT, IN EITHER WORD ORDER.
    # This was `\b(\d+)\s*(violation|error|issue|total)` alone, which
    # requires the NUMBER FIRST: it sees "0 violations" and misses "total
    # violations: 0", "violation count summary: 0" and "DRC errors found:
    # 0" -- the forms KLayout and Magic actually write, and three of the
    # five `_drc_real_violation_count` reads. While the gap was only a
    # WARNING it cost nothing; once v1.20.61 made an uncorroborated zero
    # DRC_ZERO_NOT_MEASURED it refused every legitimately clean KLayout or
    # Magic report, because the gate believed no count had been stated
    # while holding the count it had just parsed out of that very line.
    #
    # STATED, NOT INFERRED, and the distinction is the whole ruling: the
    # sha256 case v1.20.61 was written for is an RDB whose count is
    # INFERRED from zero <item> elements -- a zero produced by not
    # looking. Nothing textual is added for that dialect here, so it stays
    # uncorroborated and stays refused.
    count_re = re.compile(
        r"\b(\d+)\s*(?:violation|error|issue|total)"
        r"|(?:total\s+violations?|violation\s+count\s+summary"
        r"|violation\s+report|DRC\s+errors?\s+found)\s*[:=]?\s*\d+",
        re.I)
    cats_found: List[str] = []
    has_count = False
    best_file = ""
    determined_files = 0
    real_total = 0
    stdcell_excluded = 0
    worst_file = ""
    # DISCLOSURE ONLY, never gating here. Which PRODUCER wrote each report the
    # audit read, decided from the report's own bytes. `_check_drc` serves BOTH
    # the router-DRC gate (step 21, where an `openroad` producer is exactly
    # right) and the sign-off gate (step 31, where it is not), so the producer
    # cannot be judged at this level — only recorded, so the caller that owns
    # the sign-off policy can judge it. See `drc_report_check --signoff`.
    producers: List[dict] = []
    unreadable: List[str] = []
    # A report that is PRESENT and EMPTY. Tracked apart from
    # `unreadable` because they are different answers -- see the
    # three-state note in the read loop below.
    empty: List[str] = []
    empty_paths: List[Path] = []
    # THE TOOL'S OWN FINAL WORD, alongside the summary that claims to report it.
    # Both are recorded per file and BOTH are disclosed, so a reader never has
    # to take the gate's word for which one the number came from.
    tool_total = 0
    summary_total = 0
    tool_corroborated = 0
    receipt_corroborated = 0
    contradictions: List[dict] = []
    measured_receipts = _measured_klayout_receipt_files(project_dir, files)
    measured_rdb_files: set[Path] = set()

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError as exc:
            # A DISCOVERED report that cannot be opened at all — a dangling
            # symlink, a permission error, a vanished file. Previously a bare
            # `continue`: the file was dropped from the denominator with no
            # finding of any severity, and the verdict was formed from whatever
            # siblings happened to parse.
            unreadable.append(f"{fp} ({type(exc).__name__})")
            continue
        _p = _sdf.classify_text(text)
        _prod = _p.as_dict()
        _prod["file"] = _rel(fp, project_dir)
        _prod["attribution_disagreement"] = _sdf.attribution_disagrees(_p)
        producers.append(_prod)
        for cat, regex in categories_re.items():
            if regex.search(text) and cat not in cats_found:
                cats_found.append(cat)
        # A per-rule SVRF tally STATES its count -- once per rule, in the
        # tool's own grammar -- so it is a stated count, not an inferred
        # one. `_drc_real_violation_count` already reads it through
        # `_sdf.svrf_fail_count`; the same dialect answer decides here,
        # rather than a second grammar that could drift from it.
        if count_re.search(text) or _sdf.SVRF_RESULT_RE.search(text):
            has_count = True
        if not best_file:
            best_file = str(fp)
        n = _drc_real_violation_count(text)
        # ---- THREE STATES, NOT TWO -----------------------------------
        # A DRC report is ABSENT (never discovered -- the question could
        # not be put, and nothing here measured this design), EMPTY (the
        # tool wrote its report and had nothing to write: the question WAS
        # put and the answer is zero), or POPULATED (the answer is whatever
        # it parses to). Only the third can carry a violation.
        #
        # Collapsing EMPTY into "no determinable count" made a CLEAN route
        # FAIL. OpenROAD's `detailed_route -output_drc` writes a zero-byte
        # file exactly when it found no residual violation, so under the
        # previous reading the cleaner the route, the redder this gate --
        # and a route WITH violations, which writes a parseable report,
        # passed the readability check the clean one failed.
        #
        # MEASURED 2026-08-30, spm x gf180mcuD, one tree, one gate:
        #     routed_router.drc.rpt ABSENT -> passed True,  unreadable 0
        #     routed_router.drc.rpt EMPTY  -> passed False, unreadable 1
        # The sibling consumer added in the SAME commit that started
        # requesting the report (`_router_drc_report_block`) already reads
        # empty as clean; this is the other consumer of that artefact.
        #
        # RECORDED, NEVER SILENT (flow-change-acceptance 6): an empty
        # report is NAMED in `empty_reports` and in a finding of its own,
        # so "clean" never becomes indistinguishable from "the tool died
        # before writing anything". It is credited as a count only -- the
        # scope-wide `tool_authentic` requirement is untouched, so an empty
        # file cannot on its own attest that any tool ran.
        #
        # chip-AGNOSTIC: emptiness of the tool's own output; no design,
        # PDK, layer or vendor literal.
        if n is None and not text.strip():
            empty.append(_rel(fp, project_dir))
            empty_paths.append(fp)
            determined_files += 1
        elif n is None:
            unreadable.append(str(fp))
        if n is not None:
            determined_files += 1
            if fp in measured_receipts:
                receipt_corroborated += 1
                if (_p.kind == _sdf.KLAYOUT and _p.is_signoff_deck
                        and _p.evidence == "klayout <report-database>"
                        and re.match(r'(?:<\?xml\s[^?]*\?>\s*)?<report-database\b',
                                     _strip_leading_comment_block(text).lstrip())
                        and not _has_tool_signature(text, "drc")[0]):
                    measured_rdb_files.add(fp)
            _user_n, _std_n = n
            stdcell_excluded += _std_n
            summary_total += _user_n
            # --- THE TOOL'S OWN OUTPUT IS THE AUTHORITY --------------------
            # The count above came from a SUMMARY line. Where the same report
            # also quotes the tool's own terminal count, the two are statements
            # of one quantity and a disagreement between them is a FINDING in
            # its own right — never a tie broken silently in the summary's
            # favour. A runner that mis-summarises its own tool must not be
            # invisible, in either direction.
            _tool_n = _drc_tool_final_violation_count(text)
            if _tool_n is not None:
                tool_corroborated += 1
                tool_total += _tool_n
                if _tool_n != _user_n:
                    contradictions.append({
                        "file": _rel(fp, project_dir),
                        "summary_says": _user_n, "tool_says": _tool_n})
                    result.findings.append(Finding(
                        rule="DRC_SUMMARY_CONTRADICTS_TOOL", severity="ERROR",
                        message=(
                            f"the summary line in this report says "
                            f"{_user_n} violation(s) and the TOOL's own final "
                            f"iteration in the same file says {_tool_n}. One "
                            f"of the two is wrong and nothing here can say "
                            f"which, so nothing is certified: a post-route DRC "
                            f"verdict is only as good as the agreement between "
                            f"the tool that measured it and the summary that "
                            f"republishes it. The gating total below takes the "
                            f"LARGER of the two."),
                        file=str(fp)))
                # Fail-safe direction, and the reason it is safe to take: a
                # disagreement is ALREADY an ERROR above, so the maximum never
                # decides a verdict the tool-authority reading would not also
                # decide. It only decides the NUMBER reported, and reporting
                # the smaller of two irreconcilable counts is the one choice
                # that can grade a dirty design clean.
                _user_n = max(_user_n, _tool_n)
            if _user_n > 0:
                real_total += _user_n
                if not worst_file:
                    worst_file = str(fp)

    # Category-presence stays as diagnostic CONTEXT (which rule classes this
    # PDK deck's report format even talks about) — informational only, never
    # gating. The prior version of this file let it gate `passed` alone.
    for cat, regex in categories_re.items():
        if cat not in cats_found:
            result.findings.append(Finding(
                rule="DRC_CATEGORY_PRESENT", severity="WARNING",
                message=_category_absence_message(cat, regex, files,
                                                  project_dir),
                file=best_file))
    # FX_LL21_DECLARED_OUTPUTS -- ONE ANSWER FOR AN EMPTY REPORT. An EMPTY
    # report has no category to name BY CONSTRUCTION, so "no categories" is
    # not a finding about it; whether its zero is a measurement is decided
    # below by the current route's digest-bound completion receipt.
    # (MEASURED, spm x gf180mcuD full chip, 2026-09-28: a scope of two empty
    # router reports read `DRC_REPORT_EMPTY ... read as ZERO` at INFO and
    # `DRC_CATEGORIES_EXIST: No DRC violation categories` at ERROR.)
    all_empty = bool(files) and len(empty_paths) == len(files)
    if not cats_found and not all_empty:
        result.findings.append(Finding(
            rule="DRC_CATEGORIES_EXIST", severity="ERROR",
            message="No DRC violation categories found in report",
            file=best_file))
    if not has_count:
        result.findings.append(Finding(
            rule="DRC_VIOLATION_COUNT", severity="WARNING",
            message="No violation count pattern found in DRC report",
            file=best_file))

    # NOT READABLE IS NOT A MEASUREMENT — and it is not zero.
    #
    # This is the defect that let the sign-off preamble survive: `passed` only
    # ever required `determined_files > 0`, never `determined_files ==
    # files_found`, and DRC_VIOLATION_COUNT_UNDETERMINED only fired when NOT ONE
    # file parsed. So in any multi-file scope an unreadable report was dropped
    # SILENTLY — no finding, at any severity — and the verdict was formed from
    # whatever siblings happened to parse.
    #
    # MEASURED on tracked data, `benchmark-data/ic/edge_llm_accel` project-wide:
    #     passed=True  files_found=2  determined_files=1  ERRORs: []
    # where the second "file" is a DANGLING SYMLINK at a Step-31 evidence path —
    # a green DRC verdict over a sign-off certificate that does not exist.
    #
    # Every unreadable report is now named at ERROR and gates. rc stays 1, not
    # 2: `flow_compliance_check._check_program_exit_zero` credits rc 2 as a
    # VACUOUS_PASS and returns passed=True UNCONDITIONALLY, so a refusal exiting
    # 2 would turn this gate GREEN — a cheaper false certificate than the one
    # being closed. "Nothing was certified" on a blocking sign-off gate is a
    # FAIL, not a skip.
    # The EMPTY state, disclosed by name. INFO: it is a legitimate ZERO,
    # not a defect -- but a reader must be able to see that the zero came
    # from a report with no bytes in it rather than from a parsed count.
    if empty:
        _e_shown = ", ".join(empty[:5])
        _e_more = f" (+{len(empty) - 5} more)" if len(empty) > 5 else ""
        result.findings.append(Finding(
            rule="DRC_REPORT_EMPTY", severity="INFO",
            message=(f"{len(empty)} of {len(files)} discovered DRC report(s) "
                     f"are PRESENT and EMPTY -- the tool wrote its report and "
                     f"had no violation to write; each is a ZERO only with the "
                     f"current route's digest-bound final-count receipt "
                     f"(DRC_EMPTY_ZERO_CORROBORATED / DRC_EMPTY_NOT_MEASURED). "
                     f"This is NOT an absent report, which is not measured at "
                     f"all and still refuses: {_e_shown}{_e_more}"),
            file=empty[0]))
    if unreadable:
        _shown = ", ".join(unreadable[:5])
        _more = f" (+{len(unreadable) - 5} more)" if len(unreadable) > 5 else ""
        result.findings.append(Finding(
            rule="DRC_REPORT_NOT_READABLE", severity="ERROR",
            message=(f"{len(unreadable)} of {len(files)} discovered DRC "
                     f"report(s) yielded NO determinable violation count and "
                     f"were NOT MEASURED — not zero, not clean: {_shown}"
                     f"{_more}"),
            file=unreadable[0].split(" (")[0]))

    # AN EMPTY REPORT IS A ZERO ONLY WITH THIS ROUTE'S RECEIPT. The receipt
    # names the report, current log and routed DEF by digest and records the
    # router's final count. Arbitrary sibling reports/logs cannot speak for it.
    empty_evidence: Dict[str, List[str]] = {}
    empty_uncorroborated: List[str] = []
    for fp in empty_paths:
        rel = _rel(fp, project_dir)
        receipt = _empty_router_drc_receipt(fp)
        if receipt is not None:
            empty_evidence[rel] = [_rel(receipt, project_dir)]
        else:
            log = fp.parent / "openroad.log"
            try:
                count = _drc_tool_final_violation_count(
                    log.read_text(errors="replace"))
            except OSError:
                count = None
            empty_uncorroborated.append(rel + " -- no current digest-bound "
                                       "routing receipt proves final count 0"
                                       + (f" ({count})" if count is not None else ""))
    if empty_uncorroborated:
        result.findings.append(Finding(
            rule="DRC_EMPTY_NOT_MEASURED", severity="ERROR",
            message=(f"{len(empty_uncorroborated)} PRESENT-and-EMPTY DRC "
                     f"report(s) have no current digest-bound completion "
                     f"evidence from the tool "
                     f"that wrote them, so their zero is NOT_MEASURED, not "
                     f"clean: {'; '.join(empty_uncorroborated[:5])}"),
            file=str(empty_paths[0])))
    elif all_empty and empty_evidence:
        result.findings.append(Finding(
            rule="DRC_EMPTY_ZERO_CORROBORATED", severity="INFO",
            message=("every discovered DRC report is PRESENT and EMPTY and the "
                     "router's digest-bound final count for each is 0: "
                     + "; ".join(f"{k} <- {', '.join(v)}"
                                 for k, v in sorted(empty_evidence.items()))),
            file=str(empty_paths[0])))

    # THE GATING CHECK — the real count, not the vocabulary.
    if determined_files == 0:
        result.findings.append(Finding(
            rule="DRC_VIOLATION_COUNT_UNDETERMINED", severity="ERROR",
            message=("no discovered DRC report yielded a determinable real "
                     "violation count (neither klayout <items> nor a "
                     "recognised text summary) — a sign-off gate must not "
                     "pass on vocabulary presence alone"),
            file=best_file))
    elif real_total > 0:
        result.findings.append(Finding(
            rule="DRC_REAL_VIOLATIONS_FOUND", severity="ERROR",
            message=f"{real_total} real DRC violation(s) found across "
                    f"{determined_files} report(s) with a determinable count",
            file=worst_file))

    # RDB grammar and a count alone cannot identify a measured engine. The
    # set above already intersects the SAME report's digest-bound KLayout
    # invocation (including its transcript and GDS). Reuse the current
    # physical reader as well; a generic DRC obligation cannot supply engine
    # identity, and an incomplete LibreLane obligation never falls back.
    if measured_rdb_files:
        try:
            import librelane_signoff_evidence as _native
            current = _native.obligation(project_dir, "drc")
            if current is None:
                import _physical_current as _pc
                direct = _pc.read_direct_half(project_dir, "drc")
                if direct.get("verdict") == "CURRENT" and direct.get("tool") == "klayout":
                    report = (project_dir / direct["outputs"]["report"]["path"]).resolve()
                    measured_rdb_files = {fp for fp in measured_rdb_files
                                          if fp.resolve() == report}
                else:
                    measured_rdb_files.clear()
            elif current.get("verdict") != "PASS":
                measured_rdb_files.clear()
        except (OSError, ValueError, TypeError, KeyError):
            measured_rdb_files.clear()

    # Tool-authenticity check — rejects hand-typed stubs (added 2026-04-22)
    authentic = _check_tool_authenticity(
        files, "drc", result, measured_rdb_files=measured_rdb_files)
    own_design, design_binding = _check_report_design_binding(
        files, project_dir, "drc", result)

    # DISCLOSE (never silent) the foundry-qualified std-cell-internal count that
    # was tiered out of the gating total — same waiver the phase-3 drc step
    # applies. A reader sees exactly how many violations were set aside and why.
    #
    # Severity is WARNING, not INFO. A waiver is a decision to not look at
    # something; the number of things not looked at is the single most
    # review-relevant fact a sign-off audit carries, and INFO is the tier a
    # reader skims. The phase-3 runner records these same runs with
    # `review_required: true` in its own step_drc record — an audit that
    # disclosed the same set at INFO was quieter than the runner it echoes.
    # WARNING is non-gating, so no verdict changes; only the volume does.
    if stdcell_excluded > 0:
        result.findings.append(Finding(
            rule="DRC_FOUNDRY_STDCELL_EXCLUDED", severity="WARNING",
            message=(f"{stdcell_excluded} DRC violation(s) tiered out of the "
                     f"sign-off gating total as foundry-qualified std-cell-"
                     f"INTERNAL: a waivable rule family (li./ct./licon/m1./"
                     f"met1./mcon — below the router's met2 signal stack) AND "
                     f"attributed by the report itself to a foundry cell "
                     f"master. Items in the same rule families attributed to "
                     f"the design's own cells are NOT waived and are counted "
                     f"in the {real_total} user-routing violation(s) the "
                     f"met2+/via2+ honesty gate reports. REVIEW REQUIRED."),
            file=best_file))
    # `contradictions` gates EXPLICITLY rather than by relying on the maximum
    # above having made `real_total` non-zero. It always will today — two counts
    # that disagree cannot both be zero — but a verdict that depends on that
    # coincidence would be silently undone by any later change to how the total
    # is formed, and this is the whole decision being added.
    # A ZERO NOBODY CORROBORATED IS NOT A MEASURED ZERO (sha256 sign-off DRC).
    #
    # MEASURED on the sha256 sign-off tree (lane rbsha5, 2026-09-08, v1.19.29,
    # sky130A). `reports/phase3/drc_signoff.json` shipped:
    #
    #     passed true · real_violation_total 0 · has_count FALSE
    #     tool_corroborated_files 0 · tool_uncorroborated_files 1
    #     empty_report_files 0 · determined_files 1
    #
    # The 22 385-byte KLayout RDB it read carries the deck's full rule list and
    # ZERO `<item>` and ZERO `<values>` elements. The gate credited that as a
    # determined zero, while its own finding said `DRC_VIOLATION_COUNT: No
    # violation count pattern found in DRC report`. A sign-off DRC verdict of
    # "clean" was therefore formed from a report that stated no count and that
    # nothing corroborated -- a zero produced by not looking.
    #
    # The empty case has its own receipt requirement above; this guard only
    # applies to nonempty reports whose prose does not state a count.
    #
    # NOR IS THIS A RELAXATION IN THE OTHER DIRECTION: it can only ever turn a
    # PASS into a refusal, never a FAIL into a pass. `real_total > 0` already
    # fails, and this clause is reached only when the total is zero.
    _uncorroborated_zero = (real_total == 0 and not has_count
                            and determined_files > 0
                            and tool_corroborated == 0
                            and receipt_corroborated == 0 and not empty)
    if _uncorroborated_zero:
        result.findings.append(Finding(
            rule="DRC_ZERO_NOT_MEASURED", severity="ERROR",
            message=(
                f"{determined_files} discovered DRC report(s) yielded a total "
                f"of 0, but NO report stated a violation count and NONE was "
                f"corroborated by the tool's own total or by a digest-bound "
                f"measured KLayout invocation, and none of them is "
                f"empty. This is NOT_MEASURED, not clean: a sign-off gate may "
                f"not certify a design on a zero it did not establish. "
                f"An EMPTY report is a legitimate zero and is not this."),
            file=best_file))
    # An all-empty scope carries no bytes a signature check could read; the
    # route receipt bound to each report, log and DEF (above) attests that the
    # tool ran and finished this invocation.
    if all_empty and empty_evidence and not empty_uncorroborated:
        authentic = True
    result.passed = (own_design and determined_files > 0 and real_total == 0 and authentic
                     and not unreadable and not contradictions
                     and not _uncorroborated_zero and not empty_uncorroborated)
    result.subject_files = [str(f) for f in files]
    result.summary = {"files_found": len(files), "categories_found": cats_found,
                      "ignored_intermediate_reports": ignored_intermediate,
                      "design_binding": design_binding,
                      "has_count": has_count, "tool_authentic": authentic,
                      "determined_files": determined_files,
                      "real_violation_total": real_total,
                      # BOTH numbers, always, so a reader can see which one the
                      # gating total came from instead of inferring it.
                      "summary_violation_total": summary_total,
                      "tool_violation_total": tool_total,
                      # The corroboration DENOMINATOR: of the reports that
                      # yielded a count, how many also quoted the tool's own
                      # final word to check it against. A report with no tool
                      # transcript is not corroborated and is not pretended to
                      # be — see `tool_uncorroborated_files`.
                      "tool_corroborated_files": tool_corroborated,
                      "receipt_corroborated_files": receipt_corroborated,
                      "tool_uncorroborated_files": (determined_files
                                                    - tool_corroborated),
                      "tool_contradictions": contradictions,
                      "foundry_stdcell_excluded": stdcell_excluded,
                      "producers": producers,
                      "unreadable_files": len(unreadable),
                      "unreadable": unreadable[:20],
                      # PRESENT-and-EMPTY, kept apart from both `unreadable`
                      # (present, unparseable) and absence (never discovered).
                      "empty_report_files": len(empty),
                      "empty_reports": empty[:20],
                      "empty_report_evidence": empty_evidence,
                      "empty_reports_not_measured": empty_uncorroborated[:20]}
    return result


def _lvs_blocked_verdict(project_dir: Path) -> Optional[dict]:
    """The runner's BLOCKED LVS verdict, or None.

    Reads `reports/phase3/lvs_verdict.json` — the runner's own machine-readable
    verdict artifact — and returns it ONLY when it records a BLOCKED status.
    Any other status, or an absent/unreadable/malformed file, returns None so
    the caller behaves exactly as before. Read-only: the netgen transcript that
    the #189 classifier and this gate both parse is never touched.
    """
    p = Path(project_dir) / "reports" / "phase3" / "lvs_verdict.json"
    try:
        data = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    status = str(data.get("status") or data.get("result") or "").strip().upper()
    if status == "BLOCKED":
        return data
    # R-0915-69b — A REFUSAL WEARING ANOTHER STATUS IS STILL A REFUSAL.
    #
    # MEASURED, sha256 x sky130A, lane icsha2 run15, front door. The runner
    # refused to run netgen because magic's extraction feedback reported 22
    # illegal overlaps, and said so by name in this very file — finding
    # `LVS_EXTRACTION_ILLEGAL_OVERLAP`, message "netgen was NOT run". It wrote
    # that record under `"status": "FAIL"`, so the literal-BLOCKED test above
    # returned None, and step 31 published "No LVS report found (searched
    # *lvs*.rpt/log, *comp*.out)" — an unattributed absence — over a named
    # refusal sitting in the same directory.
    #
    # The producer now records the fact this needs, MEASURED rather than
    # declared: `compare_performed` is the presence of a non-empty
    # `reports/phase3/lvs.rpt` at the instant the verdict was written. When it
    # is explicitly False there was no compare, whatever word the status
    # carries, and the caller must report the runner's own reason instead of an
    # absence.
    #
    # `is False`, NOT falsy: a verdict written before this field existed has no
    # key, `.get` returns None, and that record takes the old path unchanged.
    # This widens what gets ATTRIBUTED, never what passes — `_check_lvs` keeps
    # `passed = False` on both branches, and a record whose status is PASS can
    # only reach here with no transcript on disk, which is itself a state no
    # sign-off may pass over in silence.
    if data.get("compare_performed") is False:
        return data
    return None


def _check_lvs(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:lvs", passed=False)
    from lvs_tapeout_signoff_check import native_project_verdict
    try:
        native = native_project_verdict(project_dir)
    except (OSError, ValueError, KeyError) as exc:
        result.findings.append(Finding("LVS_NATIVE_NOT_MEASURED", "ERROR", str(exc)))
        result.summary = {"files_found": 0, "terminal_verdict": "INCOMPLETE"}
        return result
    if native is not None:
        result.passed = native["status"] == "PASS"
        result.summary = {"files_found": 1,
                          "terminal_verdict": "MATCH" if result.passed else "MISMATCH",
                          "native": native}
        result.subject_files = [native["native_result"]["path"]]
        if not result.passed:
            result.findings.append(Finding("LVS_NATIVE_MISMATCH", "ERROR",
                                          "official PDK final-GDS circuit/pin comparison failed"))
        return result
    files = _discover(project_dir, ["*lvs*.rpt", "*lvs*.log", "*LVS*.rpt",
                                     "*LVS*.log", "*comp*.out"])
    if not files:
        # A BLOCKED run produces NO netgen report by construction — extraction
        # never ran, because an input could not support it. "No LVS report
        # found" is true but says nothing about WHY, which is the ambiguity
        # BLOCKED exists to remove. When the runner recorded a BLOCKED verdict,
        # report THAT (with the offending file and the missing capability)
        # instead. This never grants a pass: `passed` stays False on both
        # paths — it only replaces an unattributed absence with the reason.
        blocked = _lvs_blocked_verdict(project_dir)
        if blocked:
            # CZT-19 — BLOCKED now has TWO causes and they are not the same
            # finding. The original one is an INPUT that cannot support
            # extraction. The second is a run the supervisor STOPPED: magic or
            # netgen was killed as hung, so no compare completed. Reporting the
            # second under `LVS_BLOCKED_INPUT_INCAPABLE` would name a cause the
            # evidence does not support — the inputs were fine; the run was
            # stopped. The rule token is chosen from the record's OWN finding,
            # so the existing token keeps its existing meaning.
            _bf = str(blocked.get("finding") or "").strip().upper()
            _stopped = _bf.endswith("_STALLED") or bool(blocked.get("stopped_as"))
            _status = str(blocked.get("status") or blocked.get("result")
                          or "").strip().upper()
            if _stopped:
                _rule = "LVS_BLOCKED_RUN_STOPPED"
                _cause = ("the LVS run was stopped before it could complete "
                          "(no forward progress)")
            elif _status == "BLOCKED":
                _rule = "LVS_BLOCKED_INPUT_INCAPABLE"
                _cause = "an extraction input cannot support extraction"
            else:
                # R-0915-69b — reached only via `compare_performed is False`:
                # the flow decided, by name, not to compare. A THIRD cause, so
                # the two existing tokens keep their exact existing meanings.
                _rule = "LVS_BLOCKED_NO_COMPARE"
                _cause = ("the flow refused to run the compare and no netgen "
                          "transcript exists, so nothing was compared")
            _sup = blocked.get("supervision")
            _sup_note = ""
            if isinstance(_sup, dict) and _sup:
                _sup_note = (
                    f" Supervisor evidence: watched={_sup.get('watched')!r}, "
                    f"since_last_progress_s="
                    f"{_sup.get('since_last_progress_s')}.")
            result.findings.append(Finding(
                rule=_rule, severity="ERROR",
                message=(
                    "LVS is BLOCKED, not failed and not clean: "
                    + str(blocked.get("message") or _cause)
                    + " No compare completed, so NOTHING is known about this "
                      "design's LVS state. Sign-off must not proceed."
                    + _sup_note),
                file=str(blocked.get("tech_file") or "")))
            result.summary = {"files_found": 0, "categories_found": [],
                              "terminal_verdict": "BLOCKED",
                              "blocked": True,
                              "blocked_finding": blocked.get("finding"),
                              "blocked_stopped_as": blocked.get("stopped_as"),
                              "blocked_input": blocked.get("tech_file")}
            return result
        result.findings.append(Finding(
            rule="LVS_REPORT_EXISTS", severity="ERROR",
            message="No LVS report found (searched *lvs*.rpt/log, *comp*.out)"))
        result.summary = {"files_found": 0, "categories_found": []}
        return result

    # ORGANIC (post-#557 interaction) — CANONICAL-REPORT SCOPING. The runner
    # can leave a STALE, ABANDONED-ATTEMPT LVS-adjacent report on disk: the
    # GAP-E2E-9 power-aware upgrade path (`_try_power_aware_lvs`) tries a
    # stricter power-aware compare and writes ITS OWN transcript to
    # `reports/phase3/lvs_power_aware.rpt`, but is STRICTLY MONOTONIC — when
    # that attempt does not reach a clean match it returns None and the
    # runner falls through to the plain-netlist path, which writes the real
    # CANONICAL sign-off report to `reports/phase3/lvs.rpt`. The abandoned
    # attempt's file is never deleted, and it still matches the broad
    # `*lvs*.rpt` discovery glob above. Concatenating every discovered file
    # into one `blob` (the pre-fix behaviour) then lets that abandoned
    # attempt's own terminal MISMATCH token silently override a genuinely
    # clean canonical verdict — a real PASS reported as a false FAIL.
    # MEASURED: caravel_user_project x sky130A — `reports/phase3/lvs.rpt`
    # (canonical) ends "Final result: Circuits match uniquely.", while the
    # stale `reports/phase3/lvs_power_aware.rpt` (an abandoned 4-rail
    # power-aware retry) ends "Final result: Top level cell failed pin
    # matching.". The runner's OWN verdict artifact
    # (`reports/phase3/lvs_verdict.json`) independently confirms PASS/
    # LVS_MATCH against `reports/phase3/lvs.rpt` — this gate re-derives its
    # verdict from that SAME canonical report's own text (never trusting the
    # runner's self-report), it just stops letting an unrelated file name-
    # collide with it.
    #
    # `reports/phase3/lvs.rpt` is a FIXED, flow-defined project-structure
    # path — declared by flow/phase1_phase2_phase3.yaml's Step 31 and written
    # by every LVS code path in phase3_one_shot_runner.py under that same
    # name for every IC and every PDK — never a chip/design literal, so
    # preferring it is chip-AGNOSTIC. When it exists, classify SOLELY on its
    # own text; an auxiliary file that merely shares the `*lvs*` substring
    # must never inject or override the canonical verdict. Any project shape
    # without that canonical path falls back to the prior aggregate-blob
    # behaviour, unchanged.
    canonical = project_dir / "reports" / "phase3" / "lvs.rpt"
    scoped_files = [canonical] if canonical.is_file() else files

    categories_re = {
        "instance": re.compile(r"instance", re.I),
        "net": re.compile(r"\bnet\b", re.I),
        "device": re.compile(r"device", re.I),
        "parameter": re.compile(r"parameter", re.I),
    }
    cats_found: List[str] = []
    best_file = ""
    blob = ""

    for fp in scoped_files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        blob += "\n" + text
        for cat, regex in categories_re.items():
            if regex.search(text) and cat not in cats_found:
                cats_found.append(cat)
        if not best_file:
            best_file = str(fp)

    if not cats_found:
        result.findings.append(Finding(
            rule="LVS_CATEGORIES_EXIST", severity="ERROR",
            message="No LVS mismatch categories found in report",
            file=best_file))

    authentic = _check_tool_authenticity(scoped_files, "lvs", result)
    own_design, design_binding = _check_report_design_binding(
        scoped_files, project_dir, "lvs", result)

    # ORGANIC-20260608 #507 (CRITICAL) — terminal-verdict gate. Pre-#507
    # `passed` was decided SOLELY by (category-keyword present + tool
    # signature), so a report whose netgen verdict is "Netlists do not
    # match." (41×, real spm_e2e) FALSE-PASSed Step-31 LVS sign-off. A
    # real netgen compare ALWAYS prints one of two terminal verdict
    # tokens; the gate must parse them, mirroring the runner's #477
    # step_lvs logic so gate and runner never disagree:
    #   * matched  = "Circuits/Netlists match uniquely" → eligible PASS
    #   * mismatch = "do not match" / "failed pin matching" / "NET
    #                MISMATCH" / "失配" → hard FAIL (named finding)
    #   * neither  = INCOMPLETE (compare killed mid-run) → FAIL (#477)
    # A mismatch token is AUTHORITATIVE: it FAILs even if sub-cells also
    # printed "match uniquely" and even if categories+signature are
    # present. chip-AGNOSTIC: pure netgen verdict-token parse.
    # #524 — the verdict now comes from the SHARED classifier
    # (lvs_verdict_tokens) so this gate and the phase3 runner can never drift
    # again; it also adds the netgen property-error terminal FAIL ('Property
    # errors were found' / 'match uniquely with property errors' — empirically
    # a real LVS fail even when the topology line says 'Circuits match
    # uniquely') and the Final-result guard (a per-subcell 'match uniquely'
    # line in a truncated hierarchical run is INCOMPLETE, never a PASS).
    _verdict_cls = _lvt.classify(blob)
    matched = _verdict_cls == "MATCH"
    mismatched = _verdict_cls == "MISMATCH"
    if mismatched:
        result.findings.append(Finding(
            rule="LVS_NETLISTS_DO_NOT_MATCH", severity="ERROR",
            message=("netgen terminal verdict is a MISMATCH ('Netlists do "
                     "not match.' / 'failed pin matching') — the layout is "
                     "NOT LVS-clean; Step-31 LVS sign-off must FAIL (#507)."),
            file=best_file))
        verdict = "MISMATCH"
    elif matched:
        verdict = "MATCH"
    else:
        result.findings.append(Finding(
            rule="LVS_NO_TERMINAL_VERDICT", severity="ERROR",
            message=("netgen report carries NEITHER 'Circuits match "
                     "uniquely' NOR a mismatch token — the compare did not "
                     "run to completion (INCOMPLETE, not a conclusive "
                     "result); sign-off must FAIL (#507/#477)."),
            file=best_file))
        verdict = "INCOMPLETE"

    # PASS requires: a conclusive MATCH verdict AND a mismatch category
    # keyword found (report structure) AND an authentic tool signature.
    result.passed = (own_design and verdict == "MATCH"
                     and len(cats_found) > 0 and authentic)
    result.subject_files = [str(f) for f in files]
    result.summary = {"files_found": len(files), "categories_found": cats_found,
                      "design_binding": design_binding,
                      "tool_authentic": authentic,
                      "terminal_verdict": verdict,
                      "canonical_report_used": scoped_files is not files}
    return result


def _check_power(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:power", passed=False)
    canonical = project_dir / 'reports/phase3/power.rpt'
    current_route = canonical.exists() or (project_dir / 'phase3/stage3/pnr').exists()
    current_bound = False
    # Audit the declared adopted product. A native source report can be short
    # and unsigned; its authenticity comes from its checked run_chain receipt,
    # current inputs and exact adoption, not from a signature we add to it.
    if current_route:
        try:
            import _opensta_current as current
            from _ppa import power
            current.power_binding(project_dir)
            doc = json.loads((project_dir / 'reports/phase3/power.json').read_text())
            expected = power.signoff_record(power.read_power_report(canonical),
                source='reports/phase3/power.rpt', analysis_mode=doc.get('analysis_mode'))
            if doc != expected or doc.get('power_measurement') != 'MEASURED':
                raise current.Refusal('CURRENT_POWER_DOWNSTREAM_RESULT_MISMATCH')
            current_bound = True
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result.findings.append(Finding(rule='POWER_CURRENT_INPUTS_UNBOUND',
                severity='ERROR', message=str(exc), file=str(canonical)))
    reason = None if current_route else _waived_for_pdk(project_dir, "power")
    if reason and len(reason) >= 20:
        result.findings.append(Finding(
            rule="WAIVED_TOOL_UNAVAILABLE", severity="INFO",
            message=f"power report waived for this PDK: {reason[:80]}"))
        result.passed = True
        result.summary = {"waived": True, "reason": reason}
        return result
    files = ([canonical] if canonical.is_file() else []) if current_route else _discover(
        project_dir, ["*power*.rpt", "*power*.log", "*Power*.rpt", "*Power*.log"])
    if not files:
        result.findings.append(Finding(
            rule="POWER_REPORT_EXISTS", severity="ERROR",
            message="No power report found (searched *power*.rpt/log)"))
        result.summary = {"files_found": 0, "has_leakage": False, "has_dynamic": False}
        return result

    leak_re = re.compile(r"leakage|static\s*power", re.I)
    dyn_re = re.compile(r"dynamic|switching|internal\s*power", re.I)
    has_leak = False
    has_dyn = False
    best_file = ""
    # `phase3_one_shot_runner._emit_power_report` writes the analysis basis
    # into the report as `POWER_ANALYSIS_MODE: <vector_vcd|vectorless_sdc>`
    # and power.json mirrors it in `analysis_mode`. Collect what the TEXT says
    # so the companion's claim can be corroborated rather than believed.
    mode_re = re.compile(r"^\s*POWER_ANALYSIS_MODE:\s*(\S+)\s*$", re.M)
    stated_modes = set()

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        if leak_re.search(text):
            has_leak = True
        if dyn_re.search(text):
            has_dyn = True
        stated_modes.update(m.strip() for m in mode_re.findall(text))
        if not best_file:
            best_file = str(fp)

    if not has_leak:
        result.findings.append(Finding(
            rule="POWER_LEAKAGE_REPORTED", severity="ERROR",
            message="No leakage/static power value found in report",
            file=best_file))
    if not has_dyn:
        result.findings.append(Finding(
            rule="POWER_DYNAMIC_REPORTED", severity="ERROR",
            message="No dynamic/switching power value found in report",
            file=best_file))

    authentic = _check_tool_authenticity(files, "power", result)
    own_design, design_binding = _check_report_design_binding(
        files, project_dir, "power", result)

    if current_bound and own_design:
        design_binding = True  # The routed module and recorded tool subject were checked.

    # The declared machine-readable half (reports/phase3/power.json). It
    # carries no number of its own, but it does carry two claims ABOUT the
    # measurement — which report it summarises, and how the switching power
    # was obtained — and both are checkable against the text half.
    machine_ok = True
    companions = []
    for path, doc in _companion_docs(project_dir, "power"):
        rel = _rel(path, project_dir)
        if doc is None:
            machine_ok = False
            result.findings.append(Finding(
                rule="POWER_MEASUREMENT_UNREADABLE", severity="ERROR",
                message=("the machine-readable power measurement declared "
                         "alongside the report is not a readable JSON object; "
                         "the verdict would rest on the text report's keywords "
                         "alone, and unmeasured is not zero"),
                file=rel))
            continue
        src = doc.get("source")
        claimed_mode = doc.get("analysis_mode")
        companions.append({"file": rel, "source": src,
                           "analysis_mode": claimed_mode})
        if isinstance(src, str) and src.strip() \
                and not (project_dir / src.strip()).is_file():
            machine_ok = False
            result.findings.append(Finding(
                rule="POWER_SOURCE_MISSING", severity="ERROR",
                message=(f"power companion names its source report as "
                         f"{src!r}, which does not exist — the summary "
                         f"describes a report nobody can read"),
                file=rel))
        if (isinstance(claimed_mode, str) and claimed_mode.strip()
                and stated_modes and claimed_mode.strip() not in stated_modes):
            machine_ok = False
            result.findings.append(Finding(
                rule="POWER_ANALYSIS_MODE_CONTRADICTED", severity="ERROR",
                message=(f"power companion claims analysis_mode="
                         f"{claimed_mode!r} but every discovered power report "
                         f"states POWER_ANALYSIS_MODE in {sorted(stated_modes)} "
                         f"— vector-driven and vectorless switching power are "
                         f"different measurements and the disclosure does not "
                         f"match the report it summarises"),
                file=rel))

    result.passed = (own_design and has_leak and has_dyn and authentic and machine_ok
                     and (not current_route or current_bound)
                     and not any(f.severity == 'ERROR' for f in result.findings))
    result.subject_files = [str(f) for f in files]
    result.summary = {"files_found": len(files), "has_leakage": has_leak,
                      "design_binding": design_binding,
                      "current_binding": "CURRENT" if current_bound else "REFUSED" if current_route else "NOT_REQUIRED",
                      "has_dynamic": has_dyn, "tool_authentic": authentic,
                      "analysis_modes_in_report": sorted(stated_modes),
                      "machine_readable_found": len(companions),
                      "machine_readable": companions}
    return result


def _check_em(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:em", passed=False)
    reason = _waived_for_pdk(project_dir, "em")
    if reason and len(reason) >= 20:
        result.findings.append(Finding(
            rule="WAIVED_TOOL_UNAVAILABLE", severity="INFO",
            message=f"EM report waived for this PDK: {reason[:80]}"))
        result.passed = True
        result.summary = {"waived": True, "reason": reason}
        return result
    # `*em*.rpt` / `*ir*.rpt` are SUBSTRING globs; require a NAME TOKEN to
    # start with the prefix so an STA report named ...repa(ir)ed.rpt is not
    # judged as EM output. See _name_token_match.
    files = [f for f in _discover(project_dir, ["*em*.rpt", "*electromigration*",
                                                "*EM*.rpt", "*ir*.rpt"])
             if _name_token_match(f.name, ("em", "electromigration", "ir"))]
    if not files:
        result.findings.append(Finding(
            rule="EM_REPORT_EXISTS", severity="ERROR",
            message="No EM report found (searched *em*.rpt, *electromigration*, *ir*.rpt)"))
        result.summary = {"files_found": 0, "has_density": False}
        return result

    density_re = re.compile(r"Javg|Jpeak|mA|A/cm|current\s*density", re.I)
    # A CURRENT MAGNITUDE, not just the words. PSM prints
    # `Maximum current    : 6.85e-05 A` to stdout and the emitter copies those
    # lines into em.rpt; that is an independent measurement of the same grid,
    # separate from the per-segment CSV the companion JSON summarises. Used
    # below to tell "the CSV half is empty" (still measured) from "nothing was
    # measured at all" (the false-clean).
    current_re = re.compile(r"current\s*:?\s*([0-9]+\.?[0-9]*(?:[eE][+-]?\d+)?)"
                            r"\s*A\b", re.I)
    has_density = False
    positive_current = False
    best_file = ""

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        if density_re.search(text):
            has_density = True
        for raw in current_re.findall(text):
            try:
                if float(raw) > 0.0:
                    positive_current = True
                    break
            except ValueError:
                continue
        if not best_file:
            best_file = str(fp)

    if not has_density:
        result.findings.append(Finding(
            rule="EM_DENSITY_VALUES", severity="ERROR",
            message="No current density values (Javg/Jpeak/mA/A/cm) found",
            file=best_file))

    authentic = _check_tool_authenticity(files, "em", result)
    own_design, design_binding = _check_report_design_binding(
        files, project_dir, "em", result)

    # The declared machine-readable half (reports/phase3/em.json). The text
    # screen above always matches the emitted "current density (Jpeak,
    # derived): ..." line, including on a run where NO segment was analysed;
    # the companion states the segment count, so it can tell those apart.
    machine_ok = True
    companions = []
    for path, doc in _companion_docs(project_dir, "em"):
        rel = _rel(path, project_dir)
        if doc is None:
            machine_ok = False
            result.findings.append(Finding(
                rule="EM_MEASUREMENT_UNREADABLE", severity="ERROR",
                message=("the machine-readable EM measurement declared "
                         "alongside the report is not a readable JSON object; "
                         "the verdict would rest on the text report's keywords "
                         "alone, and unmeasured is not zero"),
                file=rel))
            continue
        segs = doc.get("segments_analysed")
        peak = doc.get("max_segment_current_A")
        companions.append({"file": rel, "segments_analysed": segs,
                           "max_segment_current_A": peak})
        empty_segments = (isinstance(segs, int) and not isinstance(segs, bool)
                          and segs <= 0)
        zero_peak = isinstance(peak, (int, float)) and float(peak) == 0.0
        if not (empty_segments and zero_peak):
            continue
        if positive_current:
            # The per-segment CSV half is empty but PSM's own stdout carried a
            # non-zero current for this grid: the EM screen DID measure, just
            # not per segment. Disclose the narrower basis, do not fail it.
            result.findings.append(Finding(
                rule="EM_PER_SEGMENT_HALF_EMPTY", severity="INFO",
                message=("EM companion carries no per-segment data "
                         "(segments_analysed=0, max_segment_current_A=0.0); "
                         "the verdict rests on the tool's aggregate current "
                         "lines in the text report, not on a per-segment "
                         "current-density screen"),
                file=rel))
            continue
        machine_ok = False
        result.findings.append(Finding(
            rule="EM_MEASUREMENT_VACUOUS", severity="ERROR",
            message=("EM companion reports segments_analysed=0 AND "
                     "max_segment_current_A=0.0, and no discovered EM report "
                     "carries a positive current magnitude either — NOTHING "
                     "was measured, so the 'current density (Jpeak, derived): "
                     "0.000e+00' line the keyword screen matched is a "
                     "formatted zero, not an electromigration result"),
            file=rel))

    result.passed = own_design and has_density and authentic and machine_ok
    result.subject_files = [str(f) for f in files]
    result.summary = {"files_found": len(files), "has_density": has_density,
                      "design_binding": design_binding,
                      "positive_current_in_report": positive_current,
                      "tool_authentic": authentic,
                      "machine_readable_found": len(companions),
                      "machine_readable": companions}
    return result


def _check_ir_drop(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:ir_drop", passed=False)
    reason = _waived_for_pdk(project_dir, "ir_drop")
    if reason and len(reason) >= 20:
        result.findings.append(Finding(
            rule="WAIVED_TOOL_UNAVAILABLE", severity="INFO",
            message=f"IR-drop report waived for this PDK: {reason[:80]}"))
        result.passed = True
        result.summary = {"waived": True, "reason": reason}
        return result
    # Same substring-glob hazard as the EM checker above.
    files = [f for f in _discover(project_dir, ["*ir*.rpt", "*power_grid*",
                                                "*IR*.rpt", "*ir_drop*",
                                                "*voltage_drop*"])
             if _name_token_match(f.name, ("ir", "power", "voltage", "psm"))]
    if not files:
        result.findings.append(Finding(
            rule="IR_REPORT_EXISTS", severity="ERROR",
            message="No IR-drop report found (searched *ir*.rpt, *power_grid*)"))
        result.summary = {"files_found": 0, "has_drop_value": False}
        return result

    drop_re = re.compile(r"mV|%\s*Vdd|voltage\s*drop|IR\s*drop", re.I)
    has_drop = False
    best_file = ""

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        if drop_re.search(text):
            has_drop = True
        if not best_file:
            best_file = str(fp)

    if not has_drop:
        result.findings.append(Finding(
            rule="IR_DROP_VALUES", severity="ERROR",
            message="No voltage drop values (mV / %Vdd) found in report",
            file=best_file))

    authentic = _check_tool_authenticity(files, "ir_drop", result)
    own_design, design_binding = _check_report_design_binding(
        files, project_dir, "ir_drop", result)

    # ORGANIC-20260606 #444 — budget comparison: when the runner's
    # ir_drop.json carries worst_ir_uv + budget_uv, the step gate applies
    # the SAME comparison signoff_ladder_run uses, so the step verdict
    # can never PASS beside a memo that reads the same numbers as over
    # budget. Values-present-only reports (legacy) gate as before.
    budget_ok = True
    worst_uv = budget_uv = None
    # A COVERAGE-INCOMPLETE run is NOT_MEASURED, never a budget pass. The
    # producer writes, in this same file, which power nets `analyze_power_grid`
    # REFUSED (`nets_analysis_failed`) and what that does to the number
    # (`verdict_basis`). A refused net emits no `IR drop` line, so the worst
    # case is the worst of the nets that SUCCEEDED -- the failure makes the
    # number SMALLER and the budget likelier to pass. Reading only
    # `worst_ir_uv`/`budget_uv` therefore converts a partial analysis into a
    # clean pass. MEASURED on u_hawaii_adc (ihp-sg13g2, reports/phase3):
    # ir_drop.json `verdict: "FAIL"`, `nets_analysis_failed: ["IOVDD"]`,
    # `verdict_basis: "... the worst-case IR reported is the worst of the nets
    # that SUCCEEDED and is not a statement about the design"` -- and beside it
    # ir_drop_signoff.json `passed: true, ir_within_budget: true`.
    # `ir_within_budget` becomes None (NOT_MEASURED) rather than False: the
    # gate must not claim the design is OVER budget either, because the
    # population it would be claiming that over is the incomplete one.
    ir_coverage_complete = True
    nets_failed: list = []
    producer_verdict = None
    for rel in ("reports/phase3/ir_drop.json", "reports/ir_drop.json"):
        jp = project_dir / rel
        if not jp.is_file():
            continue
        try:
            jd = json.loads(jp.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        # THE NUMBER FIRST: the coverage reading below depends on it.
        over_budget = False
        if isinstance(jd, dict) and isinstance(
                jd.get("worst_ir_uv"), (int, float)) and isinstance(
                jd.get("budget_uv"), (int, float)):
            worst_uv, budget_uv = float(jd["worst_ir_uv"]), float(jd["budget_uv"])
            if worst_uv > budget_uv:
                over_budget = True
                budget_ok = False
                result.findings.append(Finding(
                    rule="IR_OVER_BUDGET", severity="ERROR",
                    message=(f"worst IR drop {worst_uv:.3g} µV exceeds the "
                             f"{budget_uv:.3g} µV budget (#444)"),
                    file=rel))
        if isinstance(jd, dict):
            raw_failed = jd.get("nets_analysis_failed")
            if isinstance(raw_failed, list) and raw_failed:
                nets_failed = [str(n) for n in raw_failed]
            producer_verdict = jd.get("verdict")
            # A PRODUCER FAIL HAS THREE CAUSES, and the producer's own rule
            # (`psm_analysis_coverage.ir_verdict`) ranks them: an unreached
            # terminal, a refused net, and only then the budget. A FAIL beside
            # a number that is itself OVER budget is explained by the number.
            # A FAIL beside a number WITHIN budget can only be coverage -- the
            # producer refused a net or could not reach a terminal, whether or
            # not it named one -- and that is the case 5dc74b88f was written
            # for. Reading EVERY FAIL as coverage-incomplete turned a plainly
            # over-budget run (120 µV against 35) into NOT_MEASURED, which
            # hid the one thing the run had established.
            if nets_failed or (producer_verdict == "FAIL" and not over_budget):
                ir_coverage_complete = False
                because = (
                    f"the grid analysis REFUSED {len(nets_failed)} power net(s) "
                    f"({', '.join(nets_failed)})" if nets_failed
                    else "the producer recorded verdict FAIL on a number within "
                         "budget, which its own rule reserves for a refused net "
                         "or an unreached terminal")
                result.findings.append(Finding(
                    rule="IR_COVERAGE_INCOMPLETE", severity="ERROR",
                    message=(
                        f"{because}, so the reported worst-case IR is the worst "
                        f"of the nets that SUCCEEDED and is NOT a statement "
                        f"about the design. Recorded NOT_MEASURED: a refused "
                        f"net makes the number smaller and the budget likelier "
                        f"to pass."),
                    file=rel))
        break

    result.passed = (own_design and has_drop and authentic and budget_ok
                     and ir_coverage_complete)
    result.subject_files = [str(f) for f in files]
    result.summary = {"files_found": len(files), "has_drop_value": has_drop,
                      "design_binding": design_binding,
                      "tool_authentic": authentic,
                      "worst_ir_uv": worst_uv, "budget_uv": budget_uv,
                      # OVER budget is decided on the nets that WERE analysed
                      # and cannot be undone by the ones that were not: a
                      # refused net can only RAISE the worst case. So False
                      # stands on any coverage; only a pass needs every net,
                      # and a within-budget number over an incomplete
                      # population is None (NOT_MEASURED), as 5dc74b88f ruled.
                      "ir_within_budget": (False if not budget_ok
                                           else (True if ir_coverage_complete
                                                 else None)),
                      "ir_coverage_complete": ir_coverage_complete,
                      "ir_nets_analysis_failed": nets_failed,
                      "ir_producer_verdict": producer_verdict}
    return result


# ---------------------------------------------------------------------------
# STA BASIS — which SIDE of place-and-route a timing number came from.
#
# THE DEFECT THIS CLOSES. `phase3/stage3/sta/per_corner/` is ONE directory
# written by TWO producers at TWO different bases: `step_prelayout_signoff`
# fills it BEFORE PnR (every report stamped `STA_BASIS: PRE_LAYOUT_ESTIMATE`)
# and `step_canonicalize_artefacts` fills it AFTER route (`POST_ROUTE_SPEF`).
# `_emit_multi_corner_sta` skips a corner whose report already exists, so on
# any project where the pre-layout producer ran first the directory holds
# PRE-LAYOUT reports FOREVER — and the post-route sign-off gate counted them
# as its own multi-corner substantiation. MEASURED (v1.9.77, three distinct
# PRE_LAYOUT_ESTIMATE corner reports, post-route scope declared)::
#
#     rc=0  multi_corner_executed=True  corner_reports_distinct=3
#     scoped_under=['phase3/stage3/sta/post_route_timing.rpt']
#
# `--under` did not reach this scan: `corner_dirs` is a raw project-wide
# `glob.glob`. Routing it through `_in_scope` is the WRONG repair — under
# single-file scopes it zeroes the corner evidence for step 10 AND step 23,
# destroying the substantiation the pre-layout STA run exists to provide.
#
# So `--under` reaches the corner scan as a BASIS DECLARATION instead of a
# path filter, and the counter is SPLIT by the basis each report discloses
# about itself. A post-route summary cannot be substantiated by pre-layout
# reports, and a pre-layout summary cannot be substantiated by post-route
# ones. chip/PDK-AGNOSTIC: flow-stage vocabulary only, no chip or tool name.
# The token table and the stamp reader now live in `programs/_sta_basis.py`,
# imported rather than restated. They were duplicated into two other changes,
# and across a 24-stamp corpus the copies disagreed with this one on 7 — the
# copies dropped the prefix NORMALISATION and returned the raw capture, so
# `POST_ROUTE_SPEF` never equalled the canonical `POST_ROUTE` any consumer
# compares against. Aliased here so every existing reference keeps working.
_STA_BASIS_SCOPE_TOKENS = _sta_basis.BASIS_TOKENS
_STA_BASIS_STAMP_RE = _sta_basis.STAMP_RE
#: A report that says, in its own header, that its number was COPIED or
#: APPROXIMATED from a post-PnR run. Keyed on the SELF-DISCLOSURE — both a
#: derivation verb and a post-layout source — never on the emitter's version
#: string, which rots the moment the emitter moves.
_STA_DERIVATION_VERBS = ("approximat", "derived from", "derived by",
                         "copy of", "copied from", "verbatim",
                         "auto-staged", "autostaged", "staged from",
                         "re-used from", "reused from", "taken from")
_STA_POST_LAYOUT_SOURCES = ("post-pnr", "post pnr", "post_pnr",
                            "post-route", "post route", "post_route",
                            "post-layout", "post layout", "post_layout")


def _scope_declared_basis(project_dir: Path) -> Optional[str]:
    """The STA basis the ACTIVE `--under` scope declares, or None.

    Read from the scope PROJECT-RELATIVE, which is how the flow declares it.
    `_SCOPE_ROOTS` holds resolved ABSOLUTE paths, and matching tokens against
    those means the project's OWN directory name decides the answer: a run
    checked out at `.../post_route_backup/` made every scope look POST_ROUTE.
    CAUGHT BY ITS OWN TEST — pytest's `tmp_path` is named after the test
    function, and `test_a_stamped_post_route_report_...` produced a directory
    containing "post_route", so a PRE_LAYOUT scope resolved to two hits and
    silently degraded to "no basis declared".

    None means "the caller declared no side of PnR" — an unscoped project-wide
    invocation, an ambiguous scope, or a scope naming neither side. Every
    basis-aware branch below is a no-op then, so a caller that states no scope
    keeps exactly the pre-change behaviour.
    """
    if not _SCOPE_ROOTS:
        return None
    try:
        base = project_dir.resolve()
    except (OSError, RuntimeError):
        base = project_dir
    rels = []
    for root in _SCOPE_ROOTS:
        try:
            rels.append(str(root.relative_to(base)).lower())
        except ValueError:
            # A scope outside the project: judge it on its own name only,
            # never on the directories it happens to sit under.
            rels.append(root.name.lower())
    hits = {basis for basis, toks in _STA_BASIS_SCOPE_TOKENS.items()
            for rel in rels if any(t in rel for t in toks)}
    return hits.pop() if len(hits) == 1 else None


def _report_declared_basis(text: str) -> Optional[str]:
    """The basis a report DISCLOSES ABOUT ITSELF, from its `STA_BASIS:` stamp.

    Delegates to `_sta_basis.declared_basis` — the single reader. Kept as a
    module-level name because three call sites below and several tests import
    it; the behaviour is unchanged."""
    return _sta_basis.declared_basis(text)


def _self_discloses_post_layout_derivation(text: str) -> bool:
    """Does the report's own LEADING COMMENT BLOCK say the number was taken
    from a post-PnR run?

    MEASURED — the header on all EIGHT tracked corpus roots that carry a
    `phase3/stage3/sta/pre_pnr_timing.rpt`, seven of which returned rc 0::

        # Auto-staged by phase3_one_shot_runner v1.6.36
        # Source: OpenROAD report_checks (post-link, pre-floorplan slack
        # is approximated by the unconstrained slack in the post-PnR
        # report below — for production sign-off, run a separate
        # pre-floorplan STA pass).

    A step named "Pre-layout STA" was certified on a report whose own header
    says it is an approximation from the post-PnR run. The predicate needs a
    derivation verb AND a post-layout source in the same leading comment
    block, so step 23's `post_route_timing.rpt` header — which names
    "post-route" with no derivation claim — does not trip it.
    """
    block = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if block:
                break
            continue
        if not s.startswith("#"):
            break
        block.append(s.lower())
    head = " ".join(block)
    return (any(v in head for v in _STA_DERIVATION_VERBS)
            and any(s in head for s in _STA_POST_LAYOUT_SOURCES))


#: `_report_declared_basis` / `_scope_declared_basis` (this file, via
#: `_sta_basis`) speak "PRE_LAYOUT" / "POST_ROUTE". `sta_corner_record_
#: completeness_check` (`_sta_slack`) speaks "PRE_LAYOUT" / "SIGNOFF" for the
#: identical two concepts. One name each, so a caller crossing the boundary
#: cannot typo a comparison that silently never matches.
_BASIS_TO_SLACK_BASIS = {"POST_ROUTE": "SIGNOFF", "PRE_LAYOUT": "PRE_LAYOUT"}


def _signoff_basis_corners_elsewhere(project_dir: Path, declared_basis: str) -> int:
    """How many DISTINCT (axis, corner) pairs has ANY evidence this project's
    OWN commit carries — not just per_corner/ — actually measured at
    *declared_basis*?

    WHY THIS EXISTS. `_emit_multi_corner_sta` (the per_corner/ writer) is
    called twice: once pre-layout (Step 10, unconditional) and once post-route
    — but the post-route call only fires when the project has STAGED its own
    `input/pdk/liberty/*.lib`, which no default run does. A default run's real
    post-route multi-corner sign-off instead comes from
    `_emit_mcorner_ocv_sta` / the multicorner-SPEF emitter, which resolve their
    corners through `_resolve_signoff_corner_libs` — the container's own PDK
    corners, auto-discovered, no staging required — and write
    `sta_mcorner_ocv.rpt` / the multicorner-SPEF report, NEVER per_corner/. So
    per_corner/ sits at its Step-10 pre-layout snapshot forever on a default
    run, while real post-route evidence exists a directory over.

    `sta_corner_record_completeness_check` already reads BOTH sources (that is
    its entire job — see its own module docstring) and already resolves each
    corner's basis correctly (an un-stamped `sta_mcorner_ocv.rpt` defaults to
    its own BASIS_SIGNOFF, since that emitter only ever runs post-route). This
    reuses that resolution rather than re-deriving it a second, possibly
    disagreeing way.

    Fail-safe: any exception (unreadable declarations, a project shape this
    reader does not recognise) returns 0 — the STA_CORNER_BASIS_MISMATCH
    caller then falls back to per_corner/ alone, exactly today's behaviour.
    """
    target = _BASIS_TO_SLACK_BASIS.get(declared_basis)
    if target is None:
        return 0
    try:
        decl = _sta_slack.read_declarations(project_dir)
        records = _sta_slack.read_records(project_dir, decl)
    except Exception:
        return 0
    return len({
        key for key, rec in records.items()
        if target in (rec.get("basis_used") or {}).values()
    })


#: OpenSTA reports in the time unit of the FIRST LIBERTY it read and never
#: calls `set_cmd_units` unless a deck asks. `report_units` prints `time 1ps`;
#: a deck that sets them prints `set_cmd_units -time ps`. Both are read.
#: `STA_TIME_UNIT: ns` — the deck's OWN statement, stamped after read_liberty
#: from `sta::unit_scale_abbreviation time` + `sta::unit_suffix time`. Added at
#: round 3 because `STA_BASIS_LIBERTY` is a CONTAINER path on image-PDK runs:
#: a host-side reader cannot open that liberty, so the branch below could not
#: settle the unit and the number was refused on every such run. OpenSTA knows
#: the unit inside the deck; one line makes the artefact self-describing, and
#: this is then simply "the report states its own unit".
#: R-0915-154 — THE DECK'S OWN NAMED GAP, AND IT IS READ HERE. A deck that
#: cannot answer `sta::unit_scale_abbreviation` writes this instead of writing
#: nothing, so "this deck could not state its unit" and "this deck was never
#: asked" stop being the same silence. `_sta_time_unit` quotes it in the reason
#: it publishes, which is what makes the stamp a disclosure rather than a
#: decoration nothing consumes.
# A stamp starts on its own line. Keep prefix whitespace on that line and
# include the comment's whitespace only when '#' is present. Two overlapping
# whitespace stars around an optional '#' backtrack quadratically through
# every indented path-table row before a tail stamp (issue #3342).
_STA_TIME_UNIT_NOT_STATED_RE = re.compile(
    r"(?:^|\n)[^\S\n]*(?:#[^\S\n]*)?STA_TIME_UNIT_NOT_STATED\s*:\s*(?P<why>[^\n]*)")

_STA_TIME_UNIT_RE = re.compile(
    r"(?:^|\n)[^\S\n]*(?:#[^\S\n]*)?(?:STA_TIME_UNIT\s*:\s*|set_cmd_units\s+-time\s+"
    r"|time\s+1)(?P<unit>[munpf]?s)\b", re.I)

#: Multiplier onto NANOSECONDS.
_STA_TIME_TO_NS = {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1.0,
                   "ps": 1e-3, "fs": 1e-6}


#: The report names the liberty it timed against; a liberty DECLARES its time
#: unit. After the round-2 review that is the only authority this tree has.
_STA_BASIS_LIBERTY_RE = re.compile(
    r"(?:^|\n)[^\S\n]*(?:#[^\S\n]*)?STA_BASIS_LIBERTY\s*:\s*(?P<path>\S+)", re.I)
_LIBERTY_TIME_UNIT_RE = re.compile(
    r"\btime_unit\s*:\s*\"?\s*1?\s*(?P<unit>[munpf]?s)\s*\"?\s*;", re.I)


#: How many bytes of a liberty are read to find its `time_unit`. A liberty is
#: tens of MB; the declaration is in its opening lines (MEASURED on
#: gf180mcu_fd_sc_mcu7t5v0__ff_n40C_5v50.lib: byte offset 769 of 20,416,204).
_LIBERTY_HEAD_BYTES = 65536

#: The image a CALLER states this audit should read image-internal PDK files
#: from, set by `sta_report_check --image`. `None` means "ask the run's own
#: `reports/container_image.json`". It is never a default container name: a
#: default answers for whatever is running on this host now, which is a
#: different question from "what did this run time against".
_STA_IMAGE_OVERRIDE: Optional[str] = None


def set_image_override(ref: Optional[str]) -> None:
    """State the image this audit may read image-internal PDK files from."""
    global _STA_IMAGE_OVERRIDE
    _STA_IMAGE_OVERRIDE = (ref or "").strip() or None


def _run_image_ref(project: Optional[Path]) -> Tuple[Optional[str], str]:
    """The image THIS RUN used, from the run's own record — never a default.

    `reports/container_image.json` is where the runner writes the identity it
    actually ran against (`image_ref`, a repo@digest). That is the authority: a
    guessed default container answers for whatever happens to be running on
    this host NOW, which is a different question and can be a different image.
    """
    if project is None:
        return None, "no project was given, so the run's own image is unknown"
    rec = Path(project) / "reports" / "container_image.json"
    try:
        doc = json.loads(rec.read_text())
    except (OSError, ValueError) as exc:
        return None, (f"the run records no readable image identity at "
                      f"reports/container_image.json ({type(exc).__name__})")
    ref = doc.get("image_ref") or doc.get("image") or ""
    if not isinstance(ref, str) or not ref.strip():
        return None, ("reports/container_image.json names no image_ref, so "
                      "the image this run used is unstated")
    return ref.strip(), ""


def _liberty_head_from_image(lib: Path, image: str) -> Tuple[Optional[str], str]:
    """The liberty's opening bytes read FROM the image, or None with a reason.

    THE PDK IS IMAGE CONTENT, NOT A MOUNT, and that is why the mount map alone
    could not answer. MEASURED on this host: the EDA container reports mounts
    for the lane and for `/foss/designs` and NONE covering `/foss/pdks`; the
    liberty lives at `/foss/pdks/...` INSIDE the image (20,416,204 bytes) and
    does not exist on the host at any spelling. So a host-side audit that only
    translates mounts still cannot read it, and the review that found this was
    right: the first cut's test faked a mount and proved nothing about the real
    case.

    Read-only and side-effect free: `--rm`, no volumes, no network use beyond
    what docker already has locally, and the image is the one the RUN recorded.
    """
    try:
        import shlex as _shlex
        try:
            import _docker_memory as _dmem
        except ImportError:                                  # pragma: no cover
            from . import _docker_memory as _dmem            # type: ignore
        # EVERY `docker run` CARRIES THE CEILING. This one reads 64 KB out of a
        # 20 MB liberty and will never approach it — but the rule is about the
        # SITE, not this site's appetite: a container created without a ceiling
        # is one the host cannot bound, and an audit is exactly the place a
        # future edit would grow. Spliced in after the run verb, as
        # `test_no_docker_run_escapes_the_ceiling` requires.
        argv = (["docker", "run"] + _dmem.docker_memory_flags()
                + ["--rm", "--entrypoint", "/bin/sh", image,
                   "-c",
                   f"head -c {_LIBERTY_HEAD_BYTES} {_shlex.quote(str(lib))}"])
        r = subprocess.run(argv, capture_output=True, text=True,
                           errors="replace", timeout=180)
    except Exception as exc:                                 # noqa: BLE001
        return None, (f"the image could not be reached to read it "
                      f"({type(exc).__name__})")
    if r.returncode != 0 or not (r.stdout or "").strip():
        _why = (r.stderr or "").strip().splitlines()
        return None, (f"the image was reached but the path is not readable in "
                      f"it (rc={r.returncode}"
                      + (f": {_why[0][:120]}" if _why else "") + ")")
    return r.stdout, ""


def _liberty_as_this_process_can_open_it(lib: Path) -> Tuple[Path, str]:
    """The liberty path THIS process can open, and how it got there.

    THE SAME REPORT MUST READ THE SAME ON THE HOST AND IN THE CONTAINER, and
    before this it did not. An STA deck runs inside the EDA image and stamps
    `STA_BASIS_LIBERTY: /foss/pdks/...`, which is a CONTAINER path. This audit
    runs wherever its caller runs -- and the phase-3 runner calls it on the
    HOST, where `/foss/pdks` does not exist. So the liberty was unreadable, no
    time unit could be established, and a report carrying `worst slack max
    15.20` published NO slack number at all. MEASURED on spm run23 after the
    2026-09-24 phase-3 re-run: `ic_release_docs_gen` refused with STA_NO_SLACK
    over a report whose numbers were right there in the transcript.

    TRANSLATED, NEVER GUESSED. `_designs_root.host_spelling` is the one
    definition of "what is this container path on the host", derived from the
    mounts docker actually reports; this does not strip a prefix or assume
    `/foss` maps anywhere. Every failure -- no docker, no mount covering the
    path, a translated path that still is not there -- returns the ORIGINAL
    path, so the caller's own "could not be read" branch still fires and the
    unit stays unestablished BY NAME. A translation that cannot be made is not
    a unit.
    """
    try:
        if lib.exists():
            return lib, ""
    except OSError:
        return lib, ""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import _designs_root as _dr
        tr = _dr.host_spelling(lib, mounts=_dr.container_mounts())
        cand = Path(tr.path) if getattr(tr, "path", None) else None
        if cand is not None and cand.exists():
            return cand, (f"; the container path was resolved to the host "
                          f"through the mount docker reports ({tr.basis})")
    except Exception:                                        # noqa: BLE001
        # No docker, no daemon, no mount that covers it -- all the same
        # answer here: this process cannot open it, and says so below.
        pass
    return lib, ""


def _liberty_time_unit(text: str,
                       project: Optional[Path] = None,
                       image: Optional[str] = None) -> Tuple[Optional[str], str]:
    """The time unit of the liberty this report says it timed against.

    THREE PLACES THE SAME FILE CAN BE, IN ORDER, AND NONE OF THEM GUESSED:
      1. readable at the name the report states — the in-container case;
      2. a mount docker reports maps it onto this host — a bind-mounted tree;
      3. it is IMAGE CONTENT (`/foss/pdks/...`), so it is read from the image
         THE RUN RECORDED. On a standard host the PDK is in the image and is
         mounted nowhere, which is why (2) alone left the unit unestablished
         and a report full of slack numbers published none.
    Whichever answers, the basis SAYS SO. If none does, the unit stays
    unestablished by name — a file that cannot be read is not a unit.
    """
    m = _STA_BASIS_LIBERTY_RE.search(text or "")
    if not m:
        return None, "the report names no STA_BASIS_LIBERTY"
    lib = Path(m.group("path"))
    lib, _mapped = _liberty_as_this_process_can_open_it(lib)
    head = None
    try:
        with lib.open("r", errors="replace") as fh:
            head = fh.read(_LIBERTY_HEAD_BYTES)
    except OSError as exc:
        _local_why = f"{type(exc).__name__}"
        ref, _ref_why = (image, "") if image else _run_image_ref(project)
        if ref:
            head, _img_why = _liberty_head_from_image(lib, ref)
            if head is not None:
                _mapped = (f"; read from image {ref}:{lib} because the path is "
                           f"image content and no mount maps it onto this host")
            else:
                return None, (f"the report names liberty {lib.name} and it "
                              f"could not be read ({_local_why}); {_img_why}")
        else:
            return None, (f"the report names liberty {lib.name} and it could "
                          f"not be read ({_local_why}); and {_ref_why}")
    lm = _LIBERTY_TIME_UNIT_RE.search(head)
    if not lm:
        return None, f"liberty {lib.name} declares no time_unit{_mapped}"
    # THE TRANSLATION IS DISCLOSED ON THE SUCCESS PATH TOO. A reader comparing
    # two runs must be able to see that one of them read the liberty through a
    # mount translation rather than at the name the report states; a note that
    # appears only when the read FAILS would hide exactly the case where the
    # answer depended on this process's view of the filesystem.
    return lm.group("unit").lower(), (f"read from the liberty this report "
                                      f"timed against: {lib.name} "
                                      f"time_unit {lm.group('unit')}{_mapped}")


def _sta_time_unit(text: str,
                   project: Optional[Path] = None,
                   image: Optional[str] = None) -> Tuple[Optional[str], str]:
    """The report's own time unit, or `None` with the reason it is unknown.

    MEASURED by the pre-landing review (2026-09-23): the runner supports
    liberties declaring `time_unit : "1ps"` and never calls `set_cmd_units`, so
    a canonical report on such a flow reads `wns max -35.20` in PICOSECONDS.
    Publishing that under a key named `_ns` states 1000x the real violation --
    and in the met direction turns 45.2 ps of headroom into 45.2 ns of it.
    """
    m = _STA_TIME_UNIT_RE.search(text or "")
    if m:
        unit = m.group("unit").lower()
        if unit in _STA_TIME_TO_NS:
            return unit, f"read from the report: {m.group(0).strip()}"
        return None, f"the report states an unrecognised time unit {unit!r}"
    # THE DECK SAID IT COULD NOT ANSWER. That is a measurement about the
    # INTERPRETER, not about the design, and it is carried into the reason so a
    # reader is told which of the two silences this is (R-0915-154: a stamp
    # nothing reads is not a disclosure — this one is read, here).
    _ns = _STA_TIME_UNIT_NOT_STATED_RE.search(text or "")
    _deck_said = ""
    if _ns:
        _deck_said = (f"; the deck stated it could not establish the unit "
                      f"({_ns.group('why').strip()})")
    # NO DECK IN THIS TREE PRINTS ONE. `git grep report_units|set_cmd_units`
    # over the plugin finds only this file's own comments, so the branch above
    # never fires on a report the flow wrote -- which is why the round-2
    # review called round 1 "disclosed, not fixed". The liberty the report
    # NAMES is the authority, and it has one.
    unit, basis = _liberty_time_unit(text, project=project, image=image)
    if unit in _STA_TIME_TO_NS:
        return unit, basis + _deck_said
    return None, (basis + _deck_said
                  + "; and the report states no time unit of its own, "
                  "so no number is published under an _ns name")


def _neg_only(v: Optional[float]) -> Optional[float]:
    """The value if it is a violation, else nothing. See `_slack_row`."""
    return v if (v is not None and v < 0) else None


def _slack_row(fp: Any, slacks: Dict[str, Optional[float]],
               text: str, project: Optional[Path] = None,
               image: Optional[str] = None) -> Dict[str, Any]:
    """One report's setup / hold / TNS, in ns where the unit is established.

    The three field NAMES are `extract_slacks`' own, kept verbatim so the
    audit's receipt and the completeness gate cannot drift into two
    vocabularies for one measurement.

    PROVENANCE IS THE REPORT'S OWN BYTES, NOT ITS PATH, and an existing test
    is why. `test_sta_gate_step_scope::test_the_step_mirror_does_not_cost_the_
    gate_its_declared_report` publishes the SAME report at a second, mirrored
    path and asserts the gate's summary does not move. A `file` field made it
    move -- same numbers, different string -- so the answer depended on which
    copy the walk happened to reach first. A digest is stable across mirrors
    by construction, and it is the better provenance anyway: it says WHAT was
    read, which a path renamed tomorrow no longer does. `subject_files` still
    carries the paths.
    """
    unit, basis = _sta_time_unit(text, project=project, image=image)
    # A MEASUREMENT WHOSE UNIT IS UNKNOWN IS NOT A MEASUREMENT -- round 2's
    # rule, and it still holds for a MET number. It does NOT hold for a
    # VIOLATION, and round 3 is where that showed: a violation's SIGN does not
    # depend on the unit. -1.20 is negative in ps, ns and seconds alike.
    #
    # MEASURED by the round-3 review: dropping a unit-less row removed its
    # negative from the headline, so an unscoped audit over
    # post_route_timing.rpt (ns liberty, met 0.50) plus per_corner/sta_SS.rpt
    # (no liberty, wns -1.20) published `setup_wns_ns: 0.50, MEASURED` beside
    # `real_violation_found: true`. And in the stamp branch it subtracted the
    # very negative whose survival that branch's own comment promises.
    #
    # So the row ALWAYS carries what was read. `_ns` names are used only when
    # the unit is established; otherwise the values ride under unit-neutral
    # names with `time_unit: null` beside them, and the headline decides what
    # may be published.
    scale = _STA_TIME_TO_NS.get(unit, 1.0) if unit else 1.0
    if unit is None:
        return {"source_sha256": "sha256:" + hashlib.sha256(
                    (text or "").encode("utf-8", errors="replace")).hexdigest(),
                "time_unit": None, "time_unit_stated": False,
                "time_unit_basis": basis,
                # UNIT-NEUTRAL NAMES, AND ONLY FOR A VIOLATION. No `_ns`
                # claim is made and the value is exactly what the report
                # printed. A MET number with no unit is still refused --
                # round 2's rule, which was right: 35.20 could be 35.20 ns of
                # headroom or 0.0352 ns of it, and publishing the larger
                # reading is exactly "a better number than one you read".
                # A NEGATIVE number needs no unit to be evidence: it is a
                # violation in every unit, and that is why it survives.
                "setup_wns": _neg_only(slacks.get("setup_wns_ns")),
                "hold_wns": _neg_only(slacks.get("hold_wns_ns")),
                "tns": _neg_only(slacks.get("tns_ns")),
                # A MET reading is not published (see above) -- but the fact
                # that one EXISTS is, because it could be smaller than any
                # number we can scale. Round 4: a unit-less met 0.30 beside an
                # ns 5.00 published 5.00 as the worst, which is a better
                # number than one we read.
                "unscaled_met_readings": sum(
                    1 for k in ("setup_wns_ns", "hold_wns_ns", "tns_ns")
                    if (slacks.get(k) is not None and slacks.get(k) >= 0)),
                "setup_wns_ns": None, "hold_wns_ns": None, "tns_ns": None}
    row: Dict[str, Any] = {
        "source_sha256": "sha256:" + hashlib.sha256(
            (text or "").encode("utf-8", errors="replace")).hexdigest(),
        "time_unit": unit,
        "time_unit_stated": unit is not None,
        "time_unit_basis": basis}
    for key in ("setup_wns_ns", "hold_wns_ns", "tns_ns"):
        val = slacks.get(key)
        row[key] = None if val is None else round(val * scale, 12)
    return row


#: R-0915-159 -- POST-ROUTE SIGN-OFF IS NEVER CREDITED FROM THE IN-SESSION REPORT.
#: `phase3_one_shot_runner` writes `post_route_timing.rpt` as a COPY
#: (`# STA_ALIAS_BASIS: <name>`) of the first fresh basis in
#: `_CANONICAL_POST_ROUTE_STA_BASES`, and the LAST of those is the in-session
#: `pnr/sta.rpt` (named `sta.rpt` in the header), whose PnR corner-binding Tcl
#: stamps `STA_PARASITICS_PROVENANCE: PNR_SESSION_UNVERIFIED`. Both lines are a
#: closed grammar the flow writes itself, read between line anchors.
_STA_ALIAS_BASIS_RE = re.compile(
    r"^[ \t]*(?:#[ \t]*)?STA_ALIAS_BASIS[ \t]*:[ \t]*(sta(?:_[a-z0-9]+)*\.rpt)[ \t]*$",
    re.MULTILINE)
_STA_PNR_SESSION_UNVERIFIED_RE = re.compile(
    r"^[ \t]*(?:#[ \t]*)?STA_PARASITICS_PROVENANCE[ \t]*:[ \t]*"
    r"PNR_SESSION_UNVERIFIED[ \t]*$", re.MULTILINE)
#: The one basis name that IS the in-session report.
_STA_IN_SESSION_BASIS = "sta.rpt"


def _sta_in_session_evidence(text: str) -> Optional[str]:
    """Why this report is the in-session STA, or None when it is not."""
    alias = _STA_ALIAS_BASIS_RE.search(text)
    stamp = bool(_STA_PNR_SESSION_UNVERIFIED_RE.search(text))
    if alias and alias.group(1) == _STA_IN_SESSION_BASIS:
        return ("its STA_ALIAS_BASIS is sta.rpt (the in-session PnR report)"
                + (" and it carries STA_PARASITICS_PROVENANCE: "
                   "PNR_SESSION_UNVERIFIED" if stamp else ""))
    if stamp:
        return ("it carries STA_PARASITICS_PROVENANCE: PNR_SESSION_UNVERIFIED"
                + (f" (STA_ALIAS_BASIS: {alias.group(1)})" if alias else ""))
    return None


def _check_sta(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:sta", passed=False)
    # THE DECISION POINT FOR THE TOOL-MEASUREMENT CONTRACT (STA half).
    #
    # Everything below this line used to decide the timing verdict from the
    # SHAPE OF THE BYTES alone, and MEASURED 2026-08-27 that is not enough:
    # a netlist with no `clk` port produced `[WARNING STA-0366] port 'clk' not
    # found`, a source-less clock, and `wns max 0.00` -- and this function set
    # `any_verdict_determined=True, real_violation_found=False`, i.e. accepted
    # a fabricated perfect score as a met timing verdict. Nothing in the bytes
    # distinguishes it from a genuinely clean run, because nothing in the bytes
    # CAN: the missing fact is one only the tool knows.
    #
    # The tool now states it, on the report's own first line, and this is where
    # that statement is read -- at the point where the verdict is decided, not
    # beside it.
    import _mcp_measurement as _meas
    declared_basis = _scope_declared_basis(project_dir)
    # The `*sta*` glob substring-matches unrelated report classes whose names
    # merely CONTAIN "sta" — most notably "cro**sta**lk" (si_crosstalk.rpt).
    # A Signal-Integrity / crosstalk / noise report is NOT an STA timing
    # report and legitimately carries no OpenSTA/Startpoint signature, so it
    # must not be swept into the STA-mode authenticity check (it would force a
    # spurious STA_NO_TOOL_SIGNATURE FAIL for every project that emits an SI
    # report). Drop files whose names denote a different report class.
    # chip-AGNOSTIC: keyed on report-class name tokens, not any chip's signals.
    #
    # Passed INTO `_discover` rather than applied to its result: a name filter
    # that runs downstream of the alias dedup lets an excluded alias claim the
    # canonical report's key and then deletes the only survivor. See the
    # `exclude_name_tokens` note in `_discover`.
    _STA_EXCLUDE = ("crosstalk", "si_", "_si.", "noise", "antenna", "drc",
                    "lvs", "_em.", "ir_drop", "power")
    files = _discover(project_dir, ["*sta*.rpt", "*timing*.rpt",
                                     "*STA*.rpt", "*timing*.log"],
                      exclude_name_tokens=_STA_EXCLUDE)
    if not files:
        result.findings.append(Finding(
            rule="STA_REPORT_EXISTS", severity="ERROR",
            message="No STA report found (searched *sta*.rpt, *timing*.rpt)"))
        result.summary = {"files_found": 0, "has_wns_tns": False,
                          "has_setup_hold": False}
        return result

    wns_tns_re = re.compile(r"WNS|TNS|worst\s*negative\s*slack|total\s*negative\s*slack",
                            re.I)
    # THE NUMBER, NOT ONLY THAT THERE IS ONE.
    #
    # MEASURED on spm run22 (lane icspm5): this audit published
    # `"has_wns_tns": true` over a transcript reading "worst slack max 14.31 /
    # tns max 0.00 / worst slack min 0.51 / tns min 0.00", and its receipt
    # carried no slack number at all. `_ic_release_artefacts._sta_class` reads
    # that receipt, found none, and refused the release documents with
    # STA_NO_SLACK while the run's own sign-off reported +0.940 ns.
    #
    # THE NUMBERS COME FROM `extract_slacks`, NOT FROM A SECOND PARSER HERE,
    # and the pre-landing review (2026-09-23) is why. The first version of this
    # change matched slack lines with a regex of its own and disagreed with the
    # function this audit's OWN VERDICT already uses, in three ways:
    #
    #   * it harvested before the `measured is False` stamp filter and without
    #     the no-paths rule, so an unconstrained run -- which prints
    #     `tns max 0.00 / wns max 0.00` under `worst slack max INF` -- published
    #     0.0 / 0.0 as MEASURED. That run's own verdict is
    #     STA_VALUE_UNDETERMINED, and STA_NO_SLACK went silent on it: the exact
    #     fail-open this change removed, rebuilt through the echo of an empty
    #     path set;
    #   * its number pattern had no exponent, so OpenSTA's numeric infinity
    #     `1.0e+30` was read as a 1.0 ns worst slack;
    #   * it labelled OpenSTA's `max`/`min` as CORNERS. They are the SETUP and
    #     HOLD analyses. Taking the worse of the two published run22's HOLD
    #     0.51 as the design's WNS while the setup margin was 14.31.
    #
    # One question, one answer.
    slack_rows: List[Dict[str, Any]] = []

    setup_hold_re = re.compile(r"setup|hold", re.I)
    # An OpenSTA `report_checks` PATH-TABLE report is the per-path equivalent of
    # a WNS/TNS summary: it ends each path with "slack (MET)" / "slack
    # (VIOLATED)" and labels the analysis with "Path Type: max" (= setup) or
    # "min" (= hold). Tiny designs (e.g. spm with a single timing path) emit
    # exactly this table and NEVER the literal "WNS"/"TNS" or "setup"/"hold"
    # summary words — so the strict token search false-FAILed a genuinely real
    # report. Accept the path-table form as satisfying both requirements.
    # chip-AGNOSTIC: matches universal OpenSTA report_checks structure.
    pathtable_slack_re = re.compile(r"slack\s*\((?:MET|VIOLATED)\)", re.I)
    pathtype_re = re.compile(r"Path\s*Type\s*:\s*(?:max|min)", re.I)
    violated_re = re.compile(r"slack\s*\(\s*VIOLATED\s*\)", re.I)
    has_wns_tns = False
    has_setup_hold = False
    best_file = ""
    # THE REAL VERDICT, not just report-shape presence. `has_wns_tns` /
    # `has_setup_hold` above only established that a timing report of SOME
    # recognised shape exists — they say nothing about whether the design
    # actually met timing. MEASURED, the reason these two exist: a real,
    # tool-authentic sta_spef_based.rpt with its one genuine path's real
    # verdict hand-flipped from "slack (MET)" to "slack (VIOLATED)" (i.e. a
    # report a corrupted design would produce) still contains a path table
    # and setup/hold labelling, so the prior check still passed it.
    any_verdict_determined = False
    real_violation_found = False
    violation_evidence = ""
    # PROVENANCE OF THE REPORT ITSELF (see `_self_discloses_post_layout_
    # derivation`). Reports whose own disclosure contradicts the basis the
    # scope declares, keyed by real path so a canonical file and its
    # per-step symlink mirror are one offender, not two.
    basis_offenders = {}          # realpath -> (as-discovered path, reason)
    # "I FOUND A FILE" MUST MEAN A FILE THAT CAN BE READ. MEASURED on
    # `benchmark-data/ic/edge_llm_accel`, step 10's scoped gate::
    #
    #     files_found: 1
    #     scoped_under_missing: ["phase3/stage3/sta/pre_pnr_timing.rpt"]
    #     findings: STA_SETUP_HOLD / STA_VALUE_UNDETERMINED / STA_WNS_TNS,
    #               every one of them with file: ""
    #
    # `steps/10_pre_layout_sta_multi_corner/pre_pnr_timing.rpt` is a symlink
    # to a file that does not exist. Being DANGLING it resolves to exactly
    # the scope root, so `_in_scope` admits it — correctly, because a
    # declared evidence path that is not there is a finding, not something to
    # look away from. What was wrong is what happened NEXT: `read_text()`
    # raised OSError into a bare `continue`, so the summary published one
    # file found on ZERO readable bytes, beside a field naming that same path
    # as MISSING and three findings that could cite no file at all.
    #
    # Same repair, same shape and same rule name as `_check_drc`'s
    # DRC_REPORT_NOT_READABLE ("a green DRC verdict over a sign-off
    # certificate that does not exist"): the unreadable path is NAMED, it is
    # an ERROR, and `readable_files` is published beside `files_found` so the
    # two can never again be read as the same number.
    unreadable: List[str] = []
    #: Reports whose own producer states it measured no timing. Split by the
    #: only distinction that matters here: a run that COULD NOT measure (its
    #: numbers would be fabricated) versus one that ran and had NOTHING to
    #: measure (a purely combinational block has no timing paths, and never
    #: did). Collapsing these is wrong in both directions -- refuse the second
    #: and the gate refuses every combinational design until somebody bypasses
    #: it, which is a deleted gate; accept the first and this is unchanged.
    not_measured_hard: List[tuple] = []      # (path, class, reason)
    not_measured_benign: List[tuple] = []    # (path, reason)
    #: R-0915-159: reports that ARE the in-session STA. They never vote as
    #: sign-off evidence; a real violation written in one still counts (a
    #: stamp can decline to ADD a verdict, never subtract one written down).
    in_session: List[tuple] = []             # (path, why)

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError as exc:
            unreadable.append(f"{fp} ({exc.__class__.__name__})")
            continue
        _why_session = _sta_in_session_evidence(text)
        # R-0915-159 is a POST-ROUTE rule. In a PRE_LAYOUT scope (Step 10) the
        # in-session report is judged the way Step 10 judges a report: it is
        # post-place-and-route by construction, so it contradicts the scope
        # and is recorded below as Step 10's OWN finding
        # (STA_BASIS_CONTRADICTS_SCOPE), never under the post-route wording.
        _pre_layout_session = (_why_session
                               if declared_basis == "PRE_LAYOUT" else None)
        if _pre_layout_session:
            _why_session = None
        if _why_session:
            in_session.append((str(fp), _why_session))
            if violated_re.search(text) or any(
                    v < 0 for v in _sta_slack.extract_slacks(text).values()
                    if v is not None):
                real_violation_found = True
                any_verdict_determined = True
                if not violation_evidence:
                    violation_evidence = str(fp)
            continue
        # UNDECLARED is its own state and changes nothing: a report with no
        # stamp is judged exactly as it was before this contract existed. It
        # is NOT read as measured:false -- that would convert every report the
        # runner wrote (and every published one) into a fabrication claim,
        # which is a different lie in the opposite direction.
        _m = _meas.from_text(text, f"stamp:{fp}")
        if _m.hard_miss:
            not_measured_hard.append((str(fp), _m.reason_class, _m.reason))
        elif _m.nothing_to_measure:
            not_measured_benign.append((str(fp), _m.reason))
        if declared_basis is not None:
            stamped = _report_declared_basis(text)
            why = ""
            if stamped is not None and stamped != declared_basis:
                why = f"its own STA_BASIS stamp says {stamped}"
            elif (stamped is None and declared_basis == "PRE_LAYOUT"
                    and _self_discloses_post_layout_derivation(text)):
                why = ("its own header discloses the number as copied or "
                       "approximated from the post-PnR run")
            elif _pre_layout_session:
                why = (f"it is the in-session PnR STA — {_pre_layout_session} "
                       f"— which is post-place-and-route by construction")
            if why:
                try:
                    key = str(fp.resolve())
                except (OSError, RuntimeError):
                    key = str(fp)
                basis_offenders.setdefault(key, (str(fp), why))
        has_pathtable = bool(pathtable_slack_re.search(text))
        if wns_tns_re.search(text) or has_pathtable:
            has_wns_tns = True
        if setup_hold_re.search(text) or pathtype_re.search(text) or has_pathtable:
            has_setup_hold = True
        if not best_file:
            best_file = str(fp)

        # A report whose producer says it measured nothing does not get a
        # vote on whether a verdict was determined. The 0.00 is still IN the
        # file (it is what the tool printed) and is still shown, it simply no
        # longer counts as evidence that timing was analysed.
        #
        # BUT A SELF-REPORT MUST NOT BE ABLE TO ERASE EVIDENCE IN ITS OWN FILE.
        # Skipping the loop body outright would mean a `NOTHING_TO_MEASURE`
        # stamp sitting on top of a report full of `slack (VIOLATED)` lines
        # deleted every one of them — the producer's word outvoting the
        # producer's own output, which is the shape of every defect this
        # contract exists to close, rebuilt one layer up. A stamp can decline
        # to ADD a verdict; it can never subtract one that is written down.
        if _m.declared and _m.measured is False:
            _slacks = _sta_slack.extract_slacks(text)
            _vals = [v for v in _slacks.values() if v is not None]
            if violated_re.search(text) or any(v < 0 for v in _vals):
                real_violation_found = True
                any_verdict_determined = True
                if not violation_evidence:
                    violation_evidence = str(fp)
                result.findings.append(Finding(
                    rule="STA_STAMP_CONTRADICTED_BY_ITS_OWN_REPORT",
                    severity="ERROR",
                    message=(f"the producer stamped this report "
                             f"[{_m.reason_class}] — it states no timing was "
                             f"measured — while the report itself contains a "
                             f"real violation (a VIOLATED path entry or a "
                             f"negative slack). A tool's statement about a run "
                             f"cannot delete the run's own output"),
                    file=str(fp)))
                # A STAMP CANNOT SUBTRACT A VIOLATION THAT IS WRITTEN DOWN.
                # It declines to ADD a verdict, so the non-negative summaries
                # in a not-measured report are not published -- but a negative
                # slack in the producer's own output is evidence, and this is
                # the branch where it survives.
                _neg = {k: (v if (v is not None and v < 0) else None)
                        for k, v in _slacks.items()}
                if any(v is not None for v in _neg.values()):
                    _nrow = _slack_row(fp, _neg, text,
                                      project=project_dir,
                                      image=_STA_IMAGE_OVERRIDE)
                    if not any(r["source_sha256"] == _nrow["source_sha256"]
                               for r in slack_rows):
                        slack_rows.append(_nrow)
            continue

        if has_pathtable:
            any_verdict_determined = True
            if violated_re.search(text):
                real_violation_found = True
                if not violation_evidence:
                    violation_evidence = str(fp)
        # Reuse the already-hardened multi-dialect slack extractor (worst-
        # slack summary lines, WNS/TNS tokens, SETUP/HOLD section split)
        # rather than re-deriving numeric parsing here.
        slacks = _sta_slack.extract_slacks(text)
        vals = [v for v in slacks.values() if v is not None]
        if vals:
            any_verdict_determined = True
            # THE SAME NUMBERS THE VERDICT IS MADE OF, published rather than
            # discarded. `vals` is what decides `any_verdict_determined` on the
            # line above; publishing anything else would be a second answer to
            # a question already answered here.
            _row = _slack_row(fp, slacks, text,
                              project=project_dir,
                              image=_STA_IMAGE_OVERRIDE)
            # A MIRROR IS NOT A SECOND MEASUREMENT. Byte-identical reports
            # discovered at two paths are one reading, and counting them twice
            # would inflate `datapoints` with the run's own bookkeeping.
            if not any(r["source_sha256"] == _row["source_sha256"]
                       for r in slack_rows):
                slack_rows.append(_row)
            if any(v < 0 for v in vals):
                real_violation_found = True
                if not violation_evidence:
                    violation_evidence = str(fp)

    #: True when EVERY report examined honestly reported nothing to measure and
    #: none reported a hard miss: the step ran and had nothing to judge.
    #: Computed BEFORE the shape findings because those findings ask a question
    #: that has no answer in this case -- a design with no timing paths has no
    #: WNS line and no setup/hold section, and saying so three times over is
    #: accusing a report of being a stub when its producer has stated in
    #: writing why there is no number in it.
    #: `any_verdict_determined` is in this conjunction for the contradiction
    #: case above: a stamped-benign report that nevertheless carries a real
    #: violation sets it, and must not then be dispositioned as vacuous.
    nothing_to_judge = (bool(not_measured_benign) and not not_measured_hard
                        and not any_verdict_determined)
    #: R-0915-159: every readable report is the in-session STA, so no
    #: SPEF-based sign-off STA ran. That is NOT_MEASURED, never a shape defect
    #: of the report and never PASS.
    only_in_session = (bool(in_session) and not real_violation_found
                       and len(in_session) == len(files) - len(unreadable))
    if only_in_session:
        _f0, _why0 = in_session[0]
        result.findings.append(Finding(
            rule="STA_SIGNOFF_BASIS_IS_IN_SESSION", severity="ERROR",
            message=(f"no SPEF-based sign-off STA ran: {len(in_session)} "
                     f"discovered report(s) are the in-session PnR STA — "
                     f"{_why0}. Its RC is unattested, so post-route sign-off "
                     f"is NOT MEASURED (R-0915-159), never credited from it"),
            file=_f0))
    if not has_wns_tns and not nothing_to_judge and not only_in_session:
        result.findings.append(Finding(
            rule="STA_WNS_TNS", severity="ERROR",
            message="No WNS/TNS slack values found in STA report",
            file=best_file))
    if not has_setup_hold and not nothing_to_judge and not only_in_session:
        result.findings.append(Finding(
            rule="STA_SETUP_HOLD", severity="ERROR",
            message="No setup/hold analysis found in STA report",
            file=best_file))
    # THE REFUSAL, naming what was missing. This is the case the contract
    # exists for: the tool ran, produced a report of exactly the right shape,
    # and states in that report that it measured no timing.
    for _f, _cls, _why in not_measured_hard:
        result.findings.append(Finding(
            rule="STA_TOOL_REPORTS_NOT_MEASURED", severity="ERROR",
            message=(f"the tool that produced this report states it measured "
                     f"NO timing [{_cls}]: {_why} — a sign-off verdict read "
                     f"off this run would be fabricated, and the numbers it "
                     f"contains are not evidence that timing was analysed"),
            file=_f))
    # THE HONEST THIRD STATE. Not a pass (nothing was measured), not a failure
    # (there was nothing to measure). Disclosed, and the step is marked vacuous
    # rather than wearing a timing sign-off it never performed.
    for _f, _why in not_measured_benign:
        result.findings.append(Finding(
            rule="STA_NOTHING_TO_MEASURE", severity="INFO",
            message=(f"the tool that produced this report states there was "
                     f"nothing to measure: {_why} — this is not a defect, and "
                     f"it is not a timing sign-off either"),
            file=_f))
    if only_in_session:
        result.verdict = "NOT_MEASURED"
    elif nothing_to_judge:
        # `STA_VALUE_UNDETERMINED` would be the WRONG finding here — it accuses
        # the report of resting on shape alone, when its producer has stated in
        # writing why there is no number. Say the true thing instead.
        result.verdict = "VACUOUS_PASS"
    elif not any_verdict_determined:
        result.findings.append(Finding(
            rule="STA_VALUE_UNDETERMINED", severity="ERROR",
            message=("no discovered STA report yielded a determinable real "
                     "slack value (neither a WNS/TNS/worst-slack number nor "
                     "a MET/VIOLATED path-table entry) — a sign-off gate "
                     "must not pass on report-shape presence alone"),
            file=best_file))
    elif real_violation_found:
        result.findings.append(Finding(
            rule="STA_REAL_VIOLATION_FOUND", severity="ERROR",
            message="a real timing violation (negative slack, or a "
                    "VIOLATED path-table entry) was found in a discovered "
                    "STA report",
            file=violation_evidence))

    if unreadable:
        _shown = ", ".join(unreadable[:5])
        _more = f" (+{len(unreadable) - 5} more)" if len(unreadable) > 5 else ""
        result.findings.append(Finding(
            rule="STA_REPORT_NOT_READABLE", severity="ERROR",
            message=(f"{len(unreadable)} of {len(files)} discovered STA "
                     f"report(s) could not be opened and were NOT MEASURED — "
                     f"'files_found' counts a path, not evidence: {_shown}"
                     f"{_more}"),
            file=unreadable[0].split(" (")[0]))

    # THE PROVENANCE PREDICATE. A step that declares a basis must not be
    # certified on a report that says it is the OTHER basis. This is the one
    # thing #778's scope could not do on its own: scoping decides WHICH file
    # carries the verdict, not whether that file is what the step needs.
    if basis_offenders:
        _first, _why = sorted(basis_offenders.values())[0]
        result.findings.append(Finding(
            rule="STA_BASIS_CONTRADICTS_SCOPE", severity="ERROR",
            message=(f"the declared scope is a {declared_basis} sign-off, but "
                     f"{len(basis_offenders)} discovered report(s) disclose a "
                     f"different basis — {_why}. A {declared_basis} verdict "
                     f"reached over such a report is a verdict about the "
                     f"other side of place-and-route"),
            file=_first))

    authentic = _check_tool_authenticity(files, "sta", result)
    own_design, design_binding = _check_report_design_binding(
        files, project_dir, "sta", result)

    # #437(c) — multi-corner SUBSTANCE: a per_corner/ directory IS a
    # multi-corner-STA claim, and the claim needs >= 2 NON-IDENTICAL
    # corner reports. The audited rot: per_corner dirs EMPTY, and corner
    # reports that are byte-identical single-corner copies. No per_corner
    # dir at all = honest single-corner run, no claim, no check.
    # chip-AGNOSTIC: canonical-layout paths + content hashing only.
    corners_ok = True
    corner_reports = 0
    corner_distinct = 0
    # Distinct corner reports SPLIT by the basis each one discloses about
    # itself. `UNDECLARED` is the third tier: a report carrying no
    # `STA_BASIS:` stamp does not say which side of PnR it came from, so it
    # cannot substantiate a basis-specific claim — but it is not a
    # CONTRADICTION either, so it warns rather than fails (the fail-safe
    # exit for the "don't know" bucket).
    basis_distinct = {"PRE_LAYOUT": 0, "POST_ROUTE": 0, "UNDECLARED": 0}
    # A caller that NAMED its subject (`--subject`, the step-23 tool arm) is
    # judged on those files alone: the per_corner/ sweep is our own deck's.
    corner_dirs = sorted({Path(p) for pat in
                          ("phase*/stage*/sta/per_corner",
                           "reports/phase*/sta/per_corner",
                           # step 10's own directory (CUT_W1A split); the
                           # basis split below keeps the two apart
                           "phase*/stage*/sta/prelayout_per_corner",
                           "reports/phase*/sta/prelayout_per_corner")
                          for p in glob.glob(str(project_dir / pat))
                          if Path(p).is_dir()}) if _SUBJECTS is None else []
    for cd in corner_dirs:
        rpts = sorted(p for p in cd.glob("*.rpt")
                      if p.is_file() and p.stat().st_size > 0)
        if not rpts:
            corners_ok = False
            result.findings.append(Finding(
                rule="STA_PER_CORNER_EMPTY", severity="ERROR",
                message="per_corner/ claims multi-corner STA but contains "
                        "no corner report (#437c)",
                file=str(cd)))
            continue
        digests = {hashlib.sha256(p.read_bytes()).hexdigest() for p in rpts}
        corner_reports += len(rpts)
        corner_distinct += len(digests)
        # Same per-directory DISTINCT accounting as the line above, kept per
        # basis: two byte-identical corner reports are one piece of evidence
        # whichever basis they disclose.
        _by_basis = {}
        for p in rpts:
            try:
                _txt = p.read_text(errors="replace")
            except OSError:
                continue
            _b = _report_declared_basis(_txt) or "UNDECLARED"
            _by_basis.setdefault(_b, set()).add(
                hashlib.sha256(p.read_bytes()).hexdigest())
        for _b, _d in _by_basis.items():
            basis_distinct[_b] = basis_distinct.get(_b, 0) + len(_d)
        if len(rpts) < 2 or len(digests) < 2:
            corners_ok = False
            result.findings.append(Finding(
                rule="STA_CORNERS_NOT_DISTINCT", severity="ERROR",
                message=f"multi-corner STA requires >=2 non-identical "
                        f"corner reports; found {len(rpts)} report(s), "
                        f"{len(digests)} distinct (#437c)",
                file=str(cd)))

    # THE SPLIT COUNTER. When the scope declares a basis, only corner reports
    # that disclose THAT basis substantiate it. Unscoped (`declared_basis is
    # None`) this is the identical expression as before, so a caller that
    # states no scope sees no behaviour change at all.
    corner_distinct_matching = (corner_distinct if declared_basis is None
                                else basis_distinct.get(declared_basis, 0))
    _contradicting = (0 if declared_basis is None else sum(
        n for b, n in basis_distinct.items()
        if b not in (declared_basis, "UNDECLARED")))
    if (declared_basis is not None and _contradicting and corner_distinct_matching < 2
            and _signoff_basis_corners_elsewhere(project_dir, declared_basis) < 2):
        # The item this closes: a POST_ROUTE summary substantiated by
        # PRE_LAYOUT corner reports (and the mirror case). The per_corner
        # directory IS a multi-corner claim — for THIS step it is a broken
        # one, so it fails exactly as an empty dir or identical copies do.
        #
        # UNLESS real sign-off evidence exists OUTSIDE per_corner/ — see
        # `_signoff_basis_corners_elsewhere`, the exception this ONE clause
        # adds. per_corner/ is populated pre-layout by every run and refreshed
        # post-route ONLY when a caller stages `input/pdk/liberty/*.lib`
        # itself; a default run's real post-route multi-corner sign-off lands
        # in `sta_mcorner_ocv.rpt` / the multicorner-SPEF report instead,
        # discovered via the container's own PDK corners
        # (`_resolve_signoff_corner_libs`), and per_corner/ is simply never
        # touched again. MEASURED (spm x sky130A/gf180mcuD, 2026-08-07): a
        # real post-route run with `sta_corner: all analyzed sign-off corners
        # MET` still failed this check on per_corner/'s untouched Step-10
        # pre-layout snapshot alone.
        corners_ok = False
        result.findings.append(Finding(
            rule="STA_CORNER_BASIS_MISMATCH", severity="ERROR",
            message=(f"the declared scope is a {declared_basis} sign-off, but "
                     f"the per_corner evidence is {_contradicting} distinct "
                     f"report(s) of the OTHER basis and only "
                     f"{corner_distinct_matching} of {declared_basis} — a "
                     f"{declared_basis} multi-corner claim cannot be "
                     f"substantiated by corner reports that disclose "
                     f"themselves as the other side of place-and-route"),
            file=str(corner_dirs[0]) if corner_dirs else ""))

    # ORGANIC-20260606 #442 — explicit single-corner DISCLOSURE: when no
    # per_corner evidence (>=2 distinct corner reports) exists, the STA
    # is single-corner and must say so — never silently wear the step's
    # "multi-corner sign-off" name. Advisory (does not flip passed); the
    # broken-claim cases above (empty dir / identical copies) still FAIL.
    #
    # A WARNING THAT IS ALWAYS ON IS A WARNING NOBODY READS. Step 10 is named
    # "Pre-layout STA (multi-corner)" and, unlike step 23, has no dedicated
    # corner gate of its own — so this advisory is its ONLY multi-corner
    # statement. Measured on the 54 tracked phase-3 roots: all 7 that resolve
    # a step-10 report emitted it, on `corner_dirs_found: 0`. It now counts
    # the corner evidence of the step's OWN basis (step 10's scope names its
    # own `per_corner/` directory alongside its summary report), so a genuine
    # pre-layout multi-corner run silences it and its absence is the only
    # thing that fires it.
    # R-0915-87(4) — COUNT THE SIGN-OFF CORNERS THE RUN ACTUALLY PRODUCED.
    # MEASURED on subservient r27: sta_mcorner_ocv.rpt carries SETUP@SS and
    # HOLD@FF, each `STA_BASIS: POST_ROUTE_SPEF`, and this summary still said
    # STA_SINGLE_CORNER_ONLY because only per_corner/ was counted — while the
    # SAME function already asked `_signoff_basis_corners_elsewhere` about that
    # report to exempt the basis-mismatch rule. The multi-corner decision now
    # asks the same reader (no second parser of the report). POST_ROUTE scope
    # only: step 10's PRE_LAYOUT decision is unchanged.
    signoff_corners = (_signoff_basis_corners_elsewhere(project_dir, "POST_ROUTE")
                       if declared_basis == "POST_ROUTE" else 0)
    multi_corner_executed = corners_ok and max(corner_distinct_matching,
                                               signoff_corners) >= 2
    if not multi_corner_executed and corners_ok:
        _of = f" {declared_basis}" if declared_basis else ""
        result.findings.append(Finding(
            rule="STA_SINGLE_CORNER_ONLY", severity="WARNING",
            message=(f"no multi-corner{_of} STA evidence (>=2 distinct"
                     f"{_of} per-corner reports) — this is a SINGLE-CORNER "
                     f"analysis and must not be presented as multi-corner "
                     f"sign-off (#442)")))

    # `not basis_offenders` is part of the verdict, not a note beside it: a
    # gate that emits an ERROR finding and still returns rc 0 is the "reported
    # another question" failure one layer up.
    result.passed = (own_design and (has_wns_tns or nothing_to_judge)
                      and (has_setup_hold or nothing_to_judge)
                      and authentic and corners_ok
                      and (any_verdict_determined or nothing_to_judge)
                      and not real_violation_found
                      and not not_measured_hard
                      and not basis_offenders and not unreadable
                      and not only_in_session)

    # THE GOVERNING NUMBERS, ONE PER ANALYSIS. `min` across the reports,
    # because a datasheet quotes the worst case and taking the worst can only
    # be conservative -- but NEVER across the two analyses. In OpenSTA `max` is
    # the SETUP analysis and `min` is HOLD; they answer different questions and
    # a single key meaning both is a key no reader can use. The pre-landing
    # review measured the cost on this very run: the merged key published the
    # hold worst slack 0.51 while the setup margin was 14.31.
    def _worst(field: str) -> Optional[float]:
        vals = [r[field] for r in slack_rows if r.get(field) is not None]
        return min(vals) if vals else None

    _headline = {k: v for k, v in (("setup_wns_ns", _worst("setup_wns_ns")),
                                   ("hold_wns_ns", _worst("hold_wns_ns")),
                                   ("tns_ns", _worst("tns_ns")))
                 if v is not None}

    # NEVER A BETTER NUMBER THAN ONE YOU READ. A row whose unit did not settle
    # still knows the SIGN of what it read, and a negative is a violation in
    # every unit. Publishing a met headline while such a row exists is the
    # audit stating a margin the design does not have.
    _unscoped_neg = {k: v for k, v in
                     (("setup_wns", _worst("setup_wns")),
                      ("hold_wns", _worst("hold_wns")),
                      ("tns", _worst("tns")))
                     if v is not None and v < 0}
    # WITHDRAW WHENEVER A MET HEADLINE WOULD BE A CLAIM WE CANNOT SUPPORT,
    # and round 4 named two shapes the round-3 rule missed because it keyed on
    # a unit-less NEGATIVE ROW:
    #
    #   * a violation that never becomes a row at all -- a `report_checks`
    #     path table carrying `slack (VIOLATED)` and no summary line, or a
    #     measured:false stamp over a VIOLATED path. Both set
    #     `real_violation_found` and contribute no number, and the met
    #     headline stood beside them;
    #   * a unit-less MET reading. It is not published (its scale is unknown)
    #     but it could be SMALLER than anything we can scale, so calling the
    #     scaled number "the worst" is a better number than one we read.
    _unscaled_met = sum(r.get("unscaled_met_readings") or 0
                        for r in slack_rows)
    _withdraw = bool(_unscoped_neg) or _unscaled_met > 0 or (
        real_violation_found and not any(v < 0 for v in _headline.values()))
    if _withdraw:
        # Keep only what is evidence: a negative, in whatever unit it was
        # read. A met number is withdrawn -- it cannot stand for a design
        # another report says is violating, nor outrank a reading we could
        # not scale.
        _headline = {k: v for k, v in _headline.items() if v < 0}
        _headline.update(_unscoped_neg)
    _units_stated = [r for r in slack_rows if r.get("time_unit_stated")]
    _unit_basis = (_units_stated[0]["time_unit_basis"] if _units_stated
                   else (slack_rows[0]["time_unit_basis"] if slack_rows
                         else "no report carried a slack to attach a unit to"))

    result.subject_files = [str(f) for f in files]
    result.summary = {"files_found": len(files),
                      # The third value, published beside the verdict rather
                      # than folded into it. `sta_not_measured_hard` is why a
                      # refusal happened; `sta_nothing_to_measure` is why a
                      # design with no clock is honestly green without a
                      # fabricated 0.00 anywhere in the record.
                      "sta_not_measured_hard": [
                          {"file": f, "class": c, "reason": r}
                          for f, c, r in not_measured_hard],
                      "sta_nothing_to_measure": [
                          {"file": f, "reason": r}
                          for f, r in not_measured_benign],
                      "sta_in_session_reports": [
                          {"file": f, "reason": r} for f, r in in_session],
                      "design_binding": design_binding,
                      # `files_found` counts DISCOVERED PATHS; this counts the
                      # ones that yielded bytes. They were the same number by
                      # assumption, never by measurement.
                      "readable_files": len(files) - len(unreadable),
                      "unreadable_files": len(unreadable),
                      "has_wns_tns": has_wns_tns,
                      # THE NUMBERS THIS AUDIT READ, or the named absence.
                      # Never a verdict without its number: a consumer that
                      # needs the slack can read it here, and a run whose
                      # transcript really carries none says so BY NAME rather
                      # than by an empty key a reader must interpret.
                      #
                      # NOTHING NUMERIC IS PUBLISHED UNDER A SLACK-NAMED KEY
                      # WHEN NO SLACK WAS MEASURED, and that is the whole
                      # discipline of this block rather than a style choice.
                      # `_ic_release_artefacts._numbers_under_key` decides
                      # STA_NO_SLACK by asking whether ANY number appears
                      # anywhere under a key naming slack/wns/tns. A first
                      # draft of this change published `"slack_datapoints":
                      # len(slack_rows)` beside the rows; MEASURED by mutation
                      # (lane icspm5, 2026-09-23) that key alone satisfied the
                      # release reader -- a transcript with no timing in it
                      # published `slack_datapoints: 0`, the reader found a
                      # number under a slack key, and the refusal that exists
                      # to stop exactly that run went silent. A counter is not
                      # a measurement, so the count lives under `slack_scan`
                      # where no key names the quantity, and the headline
                      # numbers below appear ONLY when they were read.
                      **_headline,
                      "slack_ns": slack_rows,
                      "slack_scan": {"datapoints": len(slack_rows),
                                     "reports_read": len(files) - len(unreadable)},
                      "slack_measurement": (
                          "MEASURED" if _headline else "NOT_MEASURED"),
                      # Which of the published numbers are in nanoseconds.
                      # A unit-neutral name above means the report stated no
                      # unit and none could be derived; its SIGN is still
                      # evidence and is why it is published at all.
                      "slack_values_in_ns": sorted(
                          k for k in _headline if k.endswith("_ns")),
                      "slack_time_unit": (
                          _units_stated[0]["time_unit"] if _units_stated
                          else None),
                      "slack_time_unit_stated": bool(_units_stated),
                      "slack_time_unit_basis": _unit_basis,
                      "slack_not_measured_reason": (
                          None if _headline else
                          "no setup/hold worst-slack or TNS number survived "
                          "the same rules this audit's own verdict applies: a "
                          "report stamped not-measured contributes only a "
                          "negative slack; a block that reported no paths "
                          "contributes neither its wns nor its tns echo; and "
                          "a report whose time unit cannot be established "
                          "publishes no number at all (" + _unit_basis + ")"
                          + ("; and a met reading was WITHDRAWN because this "
                             "scope carries a violation, or a reading whose "
                             "unit could not be established and which may be "
                             "smaller than any number that could be scaled"
                             if _withdraw else "")),
                      "has_setup_hold": has_setup_hold,
                      "tool_authentic": authentic,
                      "corner_dirs_found": len(corner_dirs),
                      "signoff_corners_from_sta_records": signoff_corners,
                      "corner_reports": corner_reports,
                      "corner_reports_distinct": corner_distinct,
                      # NAME THE QUESTION THAT WAS ASKED. `corners_ok` is
                      # "no BROKEN multi-corner claim was found" — it
                      # starts True and only goes False when a per_corner
                      # directory EXISTS and is empty or holds identical
                      # copies. A project with no per_corner directory at
                      # all therefore published
                      #   "multi_corner_substantiated": true
                      # beside "corner_dirs_found": 0, "corner_reports": 0,
                      # "corner_reports_distinct": 0 and
                      # "multi_corner_executed": false — a field asserting
                      # substantiation on zero evidence, in the JSON a
                      # compliance report prints as the step's evidence.
                      # The property field is `multi_corner_executed`,
                      # which was already correct; this one is renamed to
                      # what it measures. Same repair as #699 on the PG
                      # audit ("a check that answers one question and
                      # reports another is worse than no check").
                      "multi_corner_claim_not_broken": corners_ok,
                      "multi_corner_executed": multi_corner_executed,
                      # WHICH SIDE OF PnR THIS VERDICT IS ABOUT, and what the
                      # corner evidence actually was. `multi_corner_executed`
                      # above now counts only `corner_reports_distinct_of_
                      # declared_basis`; the by-basis breakdown is published
                      # beside it so a reader can see the reports that were
                      # DISCARDED as belonging to the other side, rather than
                      # reading a bare count and assuming it is all evidence.
                      "declared_sta_basis": declared_basis,
                      "corner_reports_distinct_by_basis": dict(basis_distinct),
                      "corner_reports_distinct_of_declared_basis":
                          corner_distinct_matching,
                      "reports_contradicting_declared_basis":
                          len(basis_offenders),
                      "any_verdict_determined": any_verdict_determined,
                      "real_violation_found": real_violation_found}
    return result


#: A KLayout antenna rule name, in the namespace the open PDKs use (`ANT.1`,
#: `ANT.16_i_ANT.2`). Anchored, so it cannot match "important" or a stray word.
_KLAYOUT_ANT_RULE_RE = re.compile(r"(?m)^\s*[\"<]?\s*(ANT[._-]\w+)", re.I)


def _antenna_klayout_count(text: str) -> Optional[int]:
    """Antenna violations from KLAYOUT's own two output shapes, or None.

    MEASURED, gf180mcuD chip path 2026-08-22. `_check_antenna` knew exactly one
    idiom -- OpenROAD's `check_antennas` ("Found N net violations") -- and
    KLayout's antenna check, which IS the antenna sign-off on gf180mcuD, emits
    neither that nor anything like it. On a chip the shuttle operator's own
    container passed 16/16 with `25 rules, 0 non-zero`, our own arm reported

        {"files_found": 2, "violations": null, "clean": null, "tool_authentic": false}

    i.e. it could not reach a verdict at all on this PDK. The two shapes:

      REPORT DATABASE (`antenna.klayout.lyrdb`) -- the same `<report-database>`
        container the DRC deck writes, with `<description>Report for antenna_*`
        and `ANT.*` category names. Violations are `<item>` elements.
      PER-RULE TALLY (`antenna.klayout.json`) -- `{"ANT.1": 0, "ANT.8": 0, ...}`,
        one entry per rule. Violations are the sum.

    RETURNS None, NOT 0, whenever it cannot conclude -- an empty tally, a tally
    whose keys are not antenna rules, a non-numeric value, an RDB with no
    `<items>`. UNMEASURED IS NOT ZERO: a `{}` that became "clean" would credit
    a run that measured nothing as a passing antenna sign-off, which is the
    exact direction this audit exists to refuse.
    """
    import instrument_calibration as _cal
    _cal.assert_calibrated("eda_report_audit::_antenna_klayout_count")
    head = text[:4096]
    # --- the per-rule JSON tally ---
    s = text.lstrip()
    if s.startswith("{"):
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            obj = None
        if isinstance(obj, dict) and obj:
            keys = list(obj.keys())
            if not any(_KLAYOUT_ANT_RULE_RE.match(f'"{k}"') for k in keys):
                return None          # a JSON that is not an antenna tally
            total = 0
            for v in obj.values():
                if isinstance(v, bool) or not isinstance(v, int):
                    return None      # a value we cannot add is not a zero
                total += v
            return total
        return None                  # `{}` is a run that measured nothing
    # --- the KLayout report database ---
    if "<report-database" in head:
        # THE WHOLE TEXT, not the first 64 KiB. A rule name past that bound is
        # still a rule name, and reading its absence FROM THE WINDOW as absence
        # FROM THE FILE is the substitution
        # `declaration_searched_only_inside_a_truncated_window` refuses: a
        # long report database whose first antenna rule sits late was
        # classified `not an antenna report` and returned None, which this
        # audit reads as "no count" and not as "zero violations". The scan is
        # linear and only ever widens the classification, so the bound bought
        # nothing it was worth losing that for.
        # PDK-native KLayout runs may leave <description/> empty. Their real
        # RDB names each executed rule as <name>ANT.*</name>; the older
        # line-start matcher does not match that XML element. A clean native
        # run was therefore misread as NOT_MEASURED despite 25 ANT categories.
        looks_antenna = ("report for antenna" in head.lower()
                         or bool(_KLAYOUT_ANT_RULE_RE.search(text))
                         or bool(re.search(r"<name>\s*ANT[._-]\w+\s*</name>",
                                           text, re.I)))
        if not looks_antenna:
            return None
        counted = _count_rdb_items_streaming(text)
        if counted is None:
            return None
        return counted[0] + counted[1]
    return None


def _check_antenna(project_dir: Path) -> AuditResult:
    """Antenna (gate-oxide) substance check — the missing sibling of em/ir_drop.
    Step 26 historically gated only on antenna.rpt PRESENCE; this parses the
    violation count so a present-but-violating report FAILs. Modeled on
    _check_em: PDK-waiver aware, FAILs on a missing report, and exactly mirrors
    the EM/IR `program_exit_zero` semantics so it does not regress projects whose
    antenna report is clean."""
    result = AuditResult(program="eda_report_audit:antenna", passed=False)
    reason = _waived_for_pdk(project_dir, "antenna")
    if reason and len(reason) >= 20:
        result.findings.append(Finding(
            rule="WAIVED_TOOL_UNAVAILABLE", severity="INFO",
            message=f"Antenna report waived for this PDK: {reason[:80]}"))
        result.passed = True
        result.summary = {"waived": True, "reason": reason}
        return result
    # Same gap, same reason, same measurement: KLayout's antenna check writes
    # `antenna.klayout.lyrdb` beside its .json, and the .lyrdb is the one that
    # carries the per-rule item list.
    files = [p for p in _discover(project_dir, [
        "*antenna*.rpt", "*antenna*.json", "*antenna*.lyrdb",
        "*ANT*.rpt", "*ANT*.lyrdb"])
        if p.name != "antenna_repair_transaction.json"]
    # A rollback transaction is a runner decision, not an antenna-tool report.
    # The measurement remains in the iteration reports and antenna.rpt; asking
    # this metadata document for an OpenROAD signature invents a tool refusal.
    if not files:
        result.findings.append(Finding(
            rule="ANTENNA_REPORT_EXISTS", severity="ERROR",
            message="No antenna report found (searched *antenna*.rpt, *antenna*.json)"))
        result.summary = {"files_found": 0, "violations": None}
        return result

    # Parse violation counts from the OpenROAD check_antennas idiom:
    #   "Found N net violations." / "Found M pin violations."
    #   "antenna check: N net violations, M pin violations"
    #   "antenna clean: YES|NO"
    # These are whole machine-written lines, not phrases inside a comment or
    # diagnostic sentence. In particular, "Not Found 0 ..." is no count.
    found_re = re.compile(
        r"^(?:\[INFO ANT-[0-9]{4}\][ \t]+)?Found[ \t]+(\d+)"
        r"[ \t]+(net|pin|antenna)[ \t]+violations?\.?[ \t]*$", re.I | re.M)
    pair_re = re.compile(
        r"^antenna check:[ \t]+(\d+)[ \t]+net[ \t]+violations?,?"
        r"[ \t]+(\d+)[ \t]+pin[ \t]+violations?[ \t]*$", re.I | re.M)
    clean_re = re.compile(
        r"^antenna clean:[ \t]*(YES|NO|TRUE|FALSE)[ \t]*$", re.I | re.M)
    total_viol = None
    clean_flag = None
    best_file = ""
    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        if not best_file:
            best_file = str(fp)
        m = clean_re.search(text)
        if m:
            clean_flag = m.group(1).upper() in ("YES", "TRUE")
        # Prefer the authoritative "[INFO ANT] Found N net/pin violations" lines;
        # only fall back to the "N net violations, M pin violations" summary line
        # when the Found-lines are absent, so the two never double-count.
        found_hits = list(found_re.finditer(text))
        cnt = 0
        seen = False
        if found_hits:
            # A report can contain the tool summary and a tail of the same
            # transcript. They describe one check, not separate violations.
            # Keep the last count for each kind, as check_antennas does.
            by_kind = {}
            for mm in found_hits:
                by_kind[mm.group(2).lower()] = int(mm.group(1))
            cnt = sum(by_kind.values())
            seen = True
        else:
            for mm in pair_re.finditer(text):
                cnt += int(mm.group(1)) + int(mm.group(2)); seen = True
        if not seen:
            # KLayout's own two shapes — the antenna sign-off on any PDK whose
            # deck is KLayout-based. Only consulted when the OpenROAD idiom
            # found nothing, so the two can never double-count.
            kl = _antenna_klayout_count(text)
            if kl is not None:
                cnt = kl
                seen = True
        if seen:
            total_viol = (total_viol or 0) + cnt

    authentic = _check_tool_authenticity(files, "antenna", result)
    own_design, design_binding = _check_report_design_binding(
        files, project_dir, "antenna", result)
    # Determine pass: a parseable count of 0 (or an explicit "clean: YES") is a
    # clean antenna result; >0 is a real violation FAIL. A present report with NO
    # parseable count is treated like _check_em's missing-content case → ERROR
    # (catches a malformed/empty antenna report), consistent with the siblings.
    if total_viol is None and clean_flag is None:
        result.findings.append(Finding(
            rule="ANTENNA_VIOLATION_COUNT", severity="ERROR",
            message="No antenna violation count or clean-status found in report",
            file=best_file))
        result.passed = False
    elif (total_viol or 0) > 0 or clean_flag is False:
        result.findings.append(Finding(
            rule="ANTENNA_VIOLATIONS_ZERO", severity="ERROR",
            message=f"Antenna violations present: {total_viol or 'see report'} "
                    f"(net+pin); insert diode or re-route",
            file=best_file))
        result.passed = False
    else:
        result.passed = authentic and own_design
    # A VERDICT MAY NOT IGNORE A REPORT IT COULD NOT READ.
    #
    # MEASURED, spm x gf180mcuD, image label 0.3.46, through the front door
    # (lane czspmfp, FP-18). `reports/phase3/antenna_signoff.json`:
    #
    #     "passed": true,   rc 0
    #     ANTENNA_REPORT_TOO_SMALL   ERROR  phase3/stage3/pnr/antenna_iter_0.rpt
    #     ANTENNA_NO_TOOL_SIGNATURE  ERROR  (same file)
    #     ANTENNA_REPORT_TOO_SMALL   ERROR  phase3/stage3/pnr/antenna_iter_1.rpt
    #     ANTENNA_NO_TOOL_SIGNATURE  ERROR  (same file)
    #     "summary": {"files_found": 4, "tool_authentic": true, ...}
    #
    # Both blamed files are ZERO BYTES, and `Checker.KLayoutAntenna` read PASS
    # off this document. `_check_tool_authenticity` returns True as soon as ONE
    # candidate is genuine, and the verdict consulted only that boolean — so the
    # audit discovered two empty files, wrote down that they are not antenna
    # tool output, and then formed a verdict as though it had never looked.
    #
    # 0 BYTES IS NOT 0 VIOLATIONS. An empty report is "could not read it", not
    # "read it and it was clean", so the honest tier is NOT_MEASURED. This is
    # the same gate `_check_drc` already applies through its own `unreadable`
    # list, arriving at the antenna checker through a different door.
    #
    # THE RULE IS ABOUT UNREAD FILES, NOT ABOUT FINDINGS IN GENERAL, and the
    # narrowing is measured rather than cautious. A first version of this gated
    # on ANY severity=ERROR finding and turned `tests/test_wrapper_argv_
    # forwarding.py` red on a 144 B `reports/phase3/antenna.json` — the
    # RUNNER's own summary, sitting beside a genuine 3319 B `antenna.rpt`,
    # read without difficulty, and accused of being a hand-typed stub purely by
    # the byte floor. This module already records why that accusation must not
    # gate: `test_ir_drop_compact_report_strong_signature` measured 16 of 16
    # authentic `openroad-psm` ir_drop.json in the corpus at 197-611 B, under
    # their own floor. A compact summary is mis-accused; an empty file was
    # never read. Only the second is NOT_MEASURED.
    _unread: List[str] = []
    for fp in files:
        try:
            if fp.stat().st_size == 0:
                _unread.append(str(fp))
                continue
            _t = fp.read_text(errors="replace")
        except OSError as _exc:
            _unread.append(f"{fp} ({_exc})")
            continue
        # A `# MCP_MEASUREMENT:` stamp is metadata ABOUT the report, not part
        # of it — the same strip `_check_tool_authenticity` applies, so a file
        # holding nothing but a stamp is empty here too.
        _t, _ = _meas_strip(_t)
        if not _t.strip():
            _unread.append(str(fp))
    if result.passed and _unread:
        result.passed = False
        result.verdict = "NOT_MEASURED"
        result.findings.append(Finding(
            rule="ANTENNA_REPORT_NOT_READ", severity="ERROR",
            message=(f"{len(_unread)} of the {len(files)} discovered antenna "
                     f"report(s) hold no bytes at all and were NOT MEASURED — "
                     f"not zero, not clean. The count above is a statement "
                     f"about the reports that COULD be read, and a sign-off "
                     f"may not pass over evidence it never opened: "
                     f"{', '.join(_unread)}"),
            file=_unread[0].split(" (")[0]))

    # BOTH SIDES, and the ORDER is the point (#2057 x #2058). `subject_files` is
    # "THE POPULATION `summary.files_found` COUNTS, by name … set on the same
    # line as that count, from the same list, so the two can never describe
    # different things" — its own words. The tier above changes the VERDICT over
    # that population, never the population, so it runs first and this stays
    # where #2057 put it: immediately before the summary it names. A reader of
    # the emitted receipt sees the same file list the count was taken from, and
    # a NOT_MEASURED verdict about it.
    result.subject_files = [str(f) for f in files]
    result.summary = {"files_found": len(files), "violations": total_viol,
                      "design_binding": design_binding,
                      "clean": clean_flag, "tool_authentic": authentic,
                      # Two counts a reader would otherwise have to derive by
                      # filtering the findings list themselves. `unread_files`
                      # is the gating one; `own_error_findings` is taken from
                      # the FINAL list so it agrees with the document it is
                      # published in rather than with an intermediate state.
                      "unread_files": len(_unread),
                      "own_error_findings": sum(
                          1 for f in result.findings if f.severity == "ERROR")}
    return result


# ---------------------------------------------------------------------------
# Mode dispatch
# ---------------------------------------------------------------------------
MODE_MAP = {
    "drc": _check_drc,
    "lvs": _check_lvs,
    "power": _check_power,
    "em": _check_em,
    "ir_drop": _check_ir_drop,
    "sta": _check_sta,
    "antenna": _check_antenna,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Multi-mode EDA report compliance checker")
    parser.add_argument("project_dir", help="Project directory to scan")
    parser.add_argument("--mode", required=True, choices=list(MODE_MAP.keys()),
                        help="Report type to check")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    parser.add_argument(
        "--image", default=None,
        help="The image this run timed against, used to read PDK files "
             "that are IMAGE CONTENT rather than mounted (a repo@digest). "
             "Defaults to the run's own reports/container_image.json. "
             "Never a default container name: a default answers for "
             "whatever runs on this host now, not for what this run "
             "timed against.")
    parser.add_argument(
        "--under", action="append", default=None, metavar="REL",
        help="restrict report discovery to this project-relative subtree "
             "(repeatable). Omitted, discovery is project-wide. Use it to scope "
             "a step's gate to the artefacts that step declares, so another "
             "step's report cannot carry — or fail — this one.")
    parser.add_argument(
        "--subject", action="append", default=None, metavar="REL",
        help="audit exactly these project-relative files (repeatable) "
             "instead of globbing for them; each must also sit under "
             "--under when a scope is given")
    args = parser.parse_args(argv)

    set_image_override(getattr(args, "image", None))
    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        result = AuditResult(program=f"eda_report_audit:{args.mode}", passed=False)
        result.findings.append(Finding(
            rule="PROJECT_DIR_EXISTS", severity="ERROR",
            message=f"Project directory does not exist: {project_dir}"))
        result.summary = {"files_found": 0}
    else:
        checker = MODE_MAP[args.mode]
        roots = ([project_dir / rel for rel in args.under]
                 if args.under else None)
        with scoped_discovery(roots), named_subjects(
                [project_dir / rel for rel in args.subject]
                if args.subject else None):
            result = checker(project_dir)
        if roots:
            # The scope is part of the verdict: a reader must be able to see
            # WHICH artefacts this verdict was reached over.
            result.summary["scoped_under"] = list(args.under)
            # …and WHICH of those scopes did not exist. Without this a typo'd
            # `--under does/not/exist` produces a byte-identical finding to a
            # genuinely absent report ("No <X> report found"), so a broken
            # declaration reads as a real miss. Individual absent scopes are
            # legitimate — step 21 names a canonicalised copy that a given run
            # may not have produced — so the per-scope fact is DISCLOSURE only.
            missing = [rel for rel in args.under
                       if not (project_dir / rel).exists()]
            result.summary["scoped_under_missing"] = missing
            if missing and len(missing) == len(args.under):
                # EVERY declared scope is absent: discovery was structurally
                # impossible, so whatever this verdict says about reports is
                # about the scope, not about the project. WARNING, not ERROR —
                # the rc is already 1 from the report-not-found finding, and
                # promoting this would flip rc on a scope that is merely
                # partially absent were the rule ever loosened.
                result.findings.append(Finding(
                    rule="SCOPE_NOT_FOUND", severity="WARNING",
                    message=(f"none of the --under scope(s) {missing} exist "
                             f"under {project_dir} — no file could be "
                             f"discovered regardless of what the project "
                             f"contains. A report-not-found finding alongside "
                             f"this one is caused by the scope, not by a "
                             f"missing report.")))

    report = asdict(result)
    # Only when the audit actually declared one — an always-present empty key
    # would be a field that says nothing on every report ever written.
    if not report.get("verdict"):
        report.pop("verdict", None)

    # #2057 — THE `--json` DOCUMENT IS ITS OWN RECEIPT.
    #
    # The four `eda_report_audit` wrappers that sit inside phase-3 sign-off
    # (`drc_report_check`, `lvs_report_check`, `ir_drop_report_check`,
    # `sta_report_check`) write to a caller-chosen `--json` path which IS a
    # declared step output — `reports/phase3/lvs.json` at step 31,
    # `reports/phase3/sta/post_route_summary.json` at step 23, and so on.
    # #2050 left all four UNREGISTERED and blocking rather than write a second
    # artefact into a sign-off directory whose contents are accounted
    # elsewhere. The ruling on #2057 is that no second file is needed: this
    # document becomes the receipt by carrying the one field it lacked.
    #
    # `subject` is `_audit_receipt.subject_of` over exactly the population
    # `summary.files_found` counts — a content-addressed digest over
    # basename + sha256, identical in any checkout and different for any other
    # subject, so a stale audit beside a fresh report is detectable instead of
    # indistinguishable. `basis` states whether the digest witnessed bytes
    # (`content`) or only paths (`path`); it is never assumed.
    #
    # Every mode gains it, not only the four: this is the single write site
    # behind six sign-off wrappers, and a field present on some reports and
    # absent on others would make its absence ambiguous.
    report["subject"] = _audit_receipt.subject_of(
        report.pop("subject_files", []), relative_to=project_dir)
    # R-0915-152 -- the document states WHO INVOKED this writer, beside the
    # verdict it already composes. Unstated role == producer, so the run's
    # own path is unchanged.
    # ONE EDIT FOR SIX WRAPPERS: `drc_report_check`, `sta_report_check`,
    # `em_report_check`, `ir_drop_report_check`, `antenna_report_check` and
    # `lvs_report_check` all import this `main`, and between them own 8 of the
    # shared pairs -- drc and sta each serve two steps.
    _ga.stamp(report)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        # #1082 — the final filename exists ONLY IF this audit completed. This
        # one write site is the declared-output writer behind six sign-off gates
        # (drc / antenna / em / ir_drop / sta / lvs `_report_check`), so the
        # invariant lands for all six here rather than six times over.
        #
        # `open(path,'w')` truncates at open, so the previous line left a 0-byte
        # or partial file under the FINAL name whenever this process died
        # mid-write — measured with a real SIGKILL: `exists=True size=12
        # content='{"partial": '`. A downstream consumer opening that cannot tell
        # it from a complete empty report.
        _atomic_output.atomic_write_text(args.json, report_json)

    print(report_json)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
