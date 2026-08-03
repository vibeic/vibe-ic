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

import argparse
import glob
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple

import lvs_verdict_tokens as _lvt  # #524 — shared netgen terminal-verdict tokens
import _signoff_drc_format as _sdf  # the ONE producer/dialect answer
# Chip-agnostic multi-dialect timing-slack extractor, already hardened for
# the report shapes real designs actually emit (worst-slack summary lines,
# WNS/TNS tokens, and a SETUP/HOLD section split) — reused rather than
# re-derived, per Bucket-A-ladder step 1 (ALREADY-PROGRAM).
import sta_corner_record_completeness_check as _sta_slack


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


class scoped_discovery:  # noqa: N801 — a context manager, used as a verb
    """Restrict `_discover` to `roots` for the duration of the block."""

    def __init__(self, roots: Optional[List[Path]]):
        self._roots = [Path(r).resolve() for r in roots] if roots else None
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


def _in_scope(p: Path) -> bool:
    if not _SCOPE_ROOTS:
        return True
    try:
        rp = p.resolve()
    except OSError:
        return False
    for root in _SCOPE_ROOTS:
        try:
            rp.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _discover(project_dir: Path, patterns: List[str]) -> List[Path]:
    """Glob for files matching any of the given patterns recursively,
    skipping hidden / backup-flavored directories (#525), this program's own
    verdict documents, and anything outside an active `--under` scope."""
    found: List[Path] = []
    for pat in patterns:
        found.extend(project_dir.rglob(pat))
    # Deduplicate, preserve order
    seen = set()
    unique = []
    for p in found:
        if p in seen:
            continue
        seen.add(p)
        if _is_backup_path(p, project_dir):
            continue
        if _is_own_verdict_document(p):
            continue
        if not _in_scope(p):
            continue
        unique.append(p)
    return unique


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
}


def _has_strong_signature(text: str, mode: str) -> bool:
    lower = text.lower()
    for group in STRONG_SIGNATURE_GROUPS.get(mode, []):
        if all(marker.lower() in lower for marker in group):
            return True
    return False


def _check_tool_authenticity(files: List[Path], mode: str,
                              result: AuditResult) -> bool:
    """Append findings for missing tool signature + undersized reports.
    Returns True only if at least one candidate passed both checks."""
    any_authentic = False
    for fp in files:
        try:
            size = fp.stat().st_size
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        # Waive the byte-size floor when the report carries a strong,
        # multi-marker tool signature (a real-but-compact small-design
        # report). The tool-signature requirement below still gates.
        strong = _has_strong_signature(text, mode)
        ok_size = size >= MIN_REPORT_BYTES.get(mode, 1024) or strong
        ok_sig, matched = _has_tool_signature(text, mode)
        if ok_size and ok_sig:
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
    return any_authentic


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
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return None
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
    for _rx in (r"violation\s+count\s+summary\s*:\s*(\d+)",
                r"violation\s+report\s*:\s*(\d+)",
                r"total\s+violations?\s*[:=]?\s*(\d+)",
                r"DRC errors? found:\s*(\d+)"):
        m = re.search(_rx, text, re.I)
        if m:
            return (int(m.group(1)), 0)
    m = re.search(r"(\d+)\s+(?:total\s+)?violations?\b", text, re.I)
    if m:
        return (int(m.group(1)), 0)
    return None


def _check_drc(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:drc", passed=False)
    files = _discover(project_dir, ["*drc*.rpt", "*drc*.log", "*drc*.txt",
                                     "*DRC*.rpt", "*DRC*.log", "*DRC*.txt"])
    if not files:
        result.findings.append(Finding(
            rule="DRC_REPORT_EXISTS", severity="ERROR",
            message="No DRC report found (searched *drc*.rpt/log/txt)"))
        result.summary = {"files_found": 0, "categories_found": []}
        return result

    categories_re = {
        "spacing": re.compile(r"spac", re.I),
        "width": re.compile(r"width|min\s*width", re.I),
        "density": re.compile(r"density", re.I),
        "antenna": re.compile(r"antenna", re.I),
        "via": re.compile(r"\bvia\b", re.I),
        "enclosure": re.compile(r"enclos", re.I),
    }
    count_re = re.compile(r"\b(\d+)\s*(violation|error|issue|total)", re.I)
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
        if count_re.search(text):
            has_count = True
        if not best_file:
            best_file = str(fp)
        n = _drc_real_violation_count(text)
        if n is None:
            unreadable.append(str(fp))
        if n is not None:
            determined_files += 1
            _user_n, _std_n = n
            stdcell_excluded += _std_n
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
                message=f"DRC category '{cat}' not found in reports",
                file=best_file))
    if not cats_found:
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

    # Tool-authenticity check — rejects hand-typed stubs (added 2026-04-22)
    authentic = _check_tool_authenticity(files, "drc", result)

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
    result.passed = (determined_files > 0 and real_total == 0 and authentic
                     and not unreadable)
    result.summary = {"files_found": len(files), "categories_found": cats_found,
                      "has_count": has_count, "tool_authentic": authentic,
                      "determined_files": determined_files,
                      "real_violation_total": real_total,
                      "foundry_stdcell_excluded": stdcell_excluded,
                      "producers": producers,
                      "unreadable_files": len(unreadable),
                      "unreadable": unreadable[:20]}
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
    return data if status == "BLOCKED" else None


def _check_lvs(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:lvs", passed=False)
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
            result.findings.append(Finding(
                rule="LVS_BLOCKED_INPUT_INCAPABLE", severity="ERROR",
                message=(
                    "LVS is BLOCKED, not failed and not clean: "
                    + str(blocked.get("message")
                          or "an extraction input cannot support extraction")
                    + " No netlist could be extracted, so no compare ran and "
                      "NOTHING is known about this design's LVS state. "
                      "Sign-off must not proceed."),
                file=str(blocked.get("tech_file") or "")))
            result.summary = {"files_found": 0, "categories_found": [],
                              "terminal_verdict": "BLOCKED",
                              "blocked": True,
                              "blocked_finding": blocked.get("finding"),
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
    result.passed = (verdict == "MATCH"
                     and len(cats_found) > 0 and authentic)
    result.summary = {"files_found": len(files), "categories_found": cats_found,
                      "tool_authentic": authentic,
                      "terminal_verdict": verdict,
                      "canonical_report_used": scoped_files is not files}
    return result


def _check_power(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:power", passed=False)
    reason = _waived_for_pdk(project_dir, "power")
    if reason and len(reason) >= 20:
        result.findings.append(Finding(
            rule="WAIVED_TOOL_UNAVAILABLE", severity="INFO",
            message=f"power report waived for this PDK: {reason[:80]}"))
        result.passed = True
        result.summary = {"waived": True, "reason": reason}
        return result
    files = _discover(project_dir, ["*power*.rpt", "*power*.log",
                                     "*Power*.rpt", "*Power*.log"])
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

    result.passed = has_leak and has_dyn and authentic and machine_ok
    result.summary = {"files_found": len(files), "has_leakage": has_leak,
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
    files = _discover(project_dir, ["*em*.rpt", "*electromigration*",
                                     "*EM*.rpt", "*ir*.rpt"])
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

    result.passed = has_density and authentic and machine_ok
    result.summary = {"files_found": len(files), "has_density": has_density,
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
    files = _discover(project_dir, ["*ir*.rpt", "*power_grid*", "*IR*.rpt",
                                     "*ir_drop*", "*voltage_drop*"])
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

    # ORGANIC-20260606 #444 — budget comparison: when the runner's
    # ir_drop.json carries worst_ir_uv + budget_uv, the step gate applies
    # the SAME comparison signoff_ladder_run uses, so the step verdict
    # can never PASS beside a memo that reads the same numbers as over
    # budget. Values-present-only reports (legacy) gate as before.
    budget_ok = True
    worst_uv = budget_uv = None
    for rel in ("reports/phase3/ir_drop.json", "reports/ir_drop.json"):
        jp = project_dir / rel
        if not jp.is_file():
            continue
        try:
            jd = json.loads(jp.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(jd, dict) and isinstance(
                jd.get("worst_ir_uv"), (int, float)) and isinstance(
                jd.get("budget_uv"), (int, float)):
            worst_uv, budget_uv = float(jd["worst_ir_uv"]), float(jd["budget_uv"])
            if worst_uv > budget_uv:
                budget_ok = False
                result.findings.append(Finding(
                    rule="IR_OVER_BUDGET", severity="ERROR",
                    message=(f"worst IR drop {worst_uv:.3g} µV exceeds the "
                             f"{budget_uv:.3g} µV budget (#444)"),
                    file=rel))
        break

    result.passed = has_drop and authentic and budget_ok
    result.summary = {"files_found": len(files), "has_drop_value": has_drop,
                      "tool_authentic": authentic,
                      "worst_ir_uv": worst_uv, "budget_uv": budget_uv,
                      "ir_within_budget": budget_ok}
    return result


def _check_sta(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:sta", passed=False)
    files = _discover(project_dir, ["*sta*.rpt", "*timing*.rpt",
                                     "*STA*.rpt", "*timing*.log"])
    # The `*sta*` glob substring-matches unrelated report classes whose names
    # merely CONTAIN "sta" — most notably "cro**sta**lk" (si_crosstalk.rpt).
    # A Signal-Integrity / crosstalk / noise report is NOT an STA timing
    # report and legitimately carries no OpenSTA/Startpoint signature, so it
    # must not be swept into the STA-mode authenticity check (it would force a
    # spurious STA_NO_TOOL_SIGNATURE FAIL for every project that emits an SI
    # report). Drop files whose names denote a different report class.
    # chip-AGNOSTIC: keyed on report-class name tokens, not any chip's signals.
    _STA_EXCLUDE = ("crosstalk", "si_", "_si.", "noise", "antenna", "drc",
                    "lvs", "_em.", "ir_drop", "power")
    files = [f for f in files
             if not any(tok in f.name.lower() for tok in _STA_EXCLUDE)]
    if not files:
        result.findings.append(Finding(
            rule="STA_REPORT_EXISTS", severity="ERROR",
            message="No STA report found (searched *sta*.rpt, *timing*.rpt)"))
        result.summary = {"files_found": 0, "has_wns_tns": False,
                          "has_setup_hold": False}
        return result

    wns_tns_re = re.compile(r"WNS|TNS|worst\s*negative\s*slack|total\s*negative\s*slack",
                            re.I)
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

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        has_pathtable = bool(pathtable_slack_re.search(text))
        if wns_tns_re.search(text) or has_pathtable:
            has_wns_tns = True
        if setup_hold_re.search(text) or pathtype_re.search(text) or has_pathtable:
            has_setup_hold = True
        if not best_file:
            best_file = str(fp)

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
            if any(v < 0 for v in vals):
                real_violation_found = True
                if not violation_evidence:
                    violation_evidence = str(fp)

    if not has_wns_tns:
        result.findings.append(Finding(
            rule="STA_WNS_TNS", severity="ERROR",
            message="No WNS/TNS slack values found in STA report",
            file=best_file))
    if not has_setup_hold:
        result.findings.append(Finding(
            rule="STA_SETUP_HOLD", severity="ERROR",
            message="No setup/hold analysis found in STA report",
            file=best_file))
    if not any_verdict_determined:
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

    authentic = _check_tool_authenticity(files, "sta", result)

    # #437(c) — multi-corner SUBSTANCE: a per_corner/ directory IS a
    # multi-corner-STA claim, and the claim needs >= 2 NON-IDENTICAL
    # corner reports. The audited rot: per_corner dirs EMPTY, and corner
    # reports that are byte-identical single-corner copies. No per_corner
    # dir at all = honest single-corner run, no claim, no check.
    # chip-AGNOSTIC: canonical-layout paths + content hashing only.
    corners_ok = True
    corner_reports = 0
    corner_distinct = 0
    corner_dirs = sorted({Path(p) for pat in
                          ("phase*/stage*/sta/per_corner",
                           "reports/phase*/sta/per_corner")
                          for p in glob.glob(str(project_dir / pat))
                          if Path(p).is_dir()})
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
        if len(rpts) < 2 or len(digests) < 2:
            corners_ok = False
            result.findings.append(Finding(
                rule="STA_CORNERS_NOT_DISTINCT", severity="ERROR",
                message=f"multi-corner STA requires >=2 non-identical "
                        f"corner reports; found {len(rpts)} report(s), "
                        f"{len(digests)} distinct (#437c)",
                file=str(cd)))

    # ORGANIC-20260606 #442 — explicit single-corner DISCLOSURE: when no
    # per_corner evidence (>=2 distinct corner reports) exists, the STA
    # is single-corner and must say so — never silently wear the step's
    # "multi-corner sign-off" name. Advisory (does not flip passed); the
    # broken-claim cases above (empty dir / identical copies) still FAIL.
    multi_corner_executed = corners_ok and corner_distinct >= 2
    if not multi_corner_executed and corners_ok:
        result.findings.append(Finding(
            rule="STA_SINGLE_CORNER_ONLY", severity="WARNING",
            message=("no multi-corner STA evidence (>=2 distinct "
                     "per-corner reports) — this is a SINGLE-CORNER "
                     "analysis and must not be presented as multi-corner "
                     "sign-off (#442)")))

    result.passed = (has_wns_tns and has_setup_hold and authentic and corners_ok
                      and any_verdict_determined and not real_violation_found)
    result.summary = {"files_found": len(files), "has_wns_tns": has_wns_tns,
                      "has_setup_hold": has_setup_hold,
                      "tool_authentic": authentic,
                      "corner_dirs_found": len(corner_dirs),
                      "corner_reports": corner_reports,
                      "corner_reports_distinct": corner_distinct,
                      "multi_corner_substantiated": corners_ok,
                      "multi_corner_executed": multi_corner_executed,
                      "any_verdict_determined": any_verdict_determined,
                      "real_violation_found": real_violation_found}
    return result


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
    files = _discover(project_dir, ["*antenna*.rpt", "*antenna*.json",
                                     "*ANT*.rpt"])
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
    found_re = re.compile(r"Found\s+(\d+)\s+(?:net|pin|antenna)\s+violation", re.I)
    pair_re = re.compile(r"(\d+)\s+net\s+violations?,?\s+(\d+)\s+pin\s+violations?", re.I)
    clean_re = re.compile(r"antenna\s+clean\s*:\s*(YES|NO|TRUE|FALSE)", re.I)
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
            for mm in found_hits:
                cnt += int(mm.group(1)); seen = True
        else:
            for mm in pair_re.finditer(text):
                cnt += int(mm.group(1)) + int(mm.group(2)); seen = True
        if seen:
            total_viol = (total_viol or 0) + cnt

    authentic = _check_tool_authenticity(files, "antenna", result)
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
        result.passed = authentic
    result.summary = {"files_found": len(files), "violations": total_viol,
                      "clean": clean_flag, "tool_authentic": authentic}
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
        "--under", action="append", default=None, metavar="REL",
        help="restrict report discovery to this project-relative subtree "
             "(repeatable). Omitted, discovery is project-wide. Use it to scope "
             "a step's gate to the artefacts that step declares, so another "
             "step's report cannot carry — or fail — this one.")
    args = parser.parse_args(argv)

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
        with scoped_discovery(roots):
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
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
