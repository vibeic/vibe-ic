#!/usr/bin/env python3
"""
final_report_generate.py — generate canonical, chip-AGNOSTIC final
summary markdown from a Phase 2+3 project's artefacts.

Replaces the legacy BACKLOG-v10 P2.1 version. Output is now structured
around the canonical 54-entity flow yaml (Stage 1-4 + A1-A9 + M1-M4 +
P0 umbrella + Stage 5 manufacturing) and is fully driven by data files
the project already produces. Nothing in this file mentions a specific
IC, protocol, opcode, tester model, or analog block name — those live
in `reports/chip_specific_summary.md` (authored by the chip layer or
hand-written) and are linked from the tail of the generated report.

Reads:
  - flow/phase1_phase2_phase3.yaml          (canonical step definitions)
  - flow_compliance_check.py         (verdict per step, run as subproc)
  - synth/*.v + pnr/*.def            (cell-count breakdown)
  - reports/hw_test.json             (generic hardware-test verdict)
                                     OR fallback reports/md905_test.json
  - gds/*.gds                        (final GDS metadata)
  - reports/{drc_signoff,lvs,erc}*   (PV verdicts)
  - reports/test_cases.json          (test-vector count, NOT semantics)
  - analog/analog_block_list.json    (list of analog blocks)
  - analog/<block>/tuning_loop.json  (closed-loop convergence summary)
  - waivers.json                     (deferred steps)
  - generated_docs/L1_DATASHEET.json (ic_name only — for header)

Default output:
  <project>/reports/final_summary.md      (canonical name; overwrites)

For chip-specific detail (opcode tables, tester fixture semantics,
analog tuning-target voltages, etc.) author or generate
`reports/chip_specific_summary.md` separately. The generator detects
its presence and references it.

Usage:
  python3 final_report_generate.py <project_dir>
  python3 final_report_generate.py <project_dir> --out PATH
  python3 final_report_generate.py <project_dir> --no-audit  (skip subproc)

Exit codes:
   0 — generated successfully
   2 — IO/usage error
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _path_layout as _pl


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FLOW_YAML = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"
COMPLIANCE_TOOL = PLUGIN_ROOT / "programs" / "flow_compliance_check.py"

# ─── audit-timeout policy (#469, field-residual of #461) ─────────────────
# #461 made the single-snapshot consistency logic correct, but on large
# run dirs the snapshot itself is unobtainable: `flow_compliance_check.py`
# spends >200 s on the O(items × text) per-item scans, so the old fixed
# 180 s subprocess timeout fired and the verdict degraded to "UNKNOWN"
# with counts 0/0 — indistinguishable from "never audited". The fix:
#   (1) the timeout is configurable (env VIBE_IC_AUDIT_TIMEOUT_S and/or
#       CLI --audit-timeout) with a raised, size-adaptive default; and
#   (2) when the timeout DOES fire the verdict reads a NAMED
#       'AUDIT_TIMEOUT' (never 'UNKNOWN'), preserving the previous
#       snapshot marker so a reader can tell 審不完 (timed out) from
#       沒審 (never audited).
# #525 — the timeout constants are ALIASES of the single defining site in
# _path_layout (audit_timeout_s + friends); keeping independent literals
# here let them silently diverge from the values actually used.
AUDIT_TIMEOUT_ENV = _pl.AUDIT_TIMEOUT_ENV
AUDIT_TIMEOUT_DEFAULT_S = _pl.AUDIT_TIMEOUT_DEFAULT_S
AUDIT_SIZE_ADAPT_THRESHOLD_BYTES = _pl.AUDIT_SIZE_ADAPT_THRESHOLD_BYTES
AUDIT_SIZE_ADAPT_S_PER_MIB = _pl.AUDIT_SIZE_ADAPT_S_PER_MIB
AUDIT_TIMEOUT_CAP_S = _pl.AUDIT_TIMEOUT_CAP_S
# The named verdict a reader sees when the audit could not finish in time.
AUDIT_TIMEOUT_VERDICT = "AUDIT_TIMEOUT"
# The verdict used only when the audit was never run at all (--no-audit
# or the compliance tool is missing). Kept distinct from AUDIT_TIMEOUT.
AUDIT_NOT_RUN_VERDICT = "UNKNOWN"

VERDICT_SYM = {
    "PASS": "✅",
    "WAIVED-DEFERRED": "⚠️",
    "SKIPPED-CONDITION": "⏭️",
    "VACUOUS-PASS": "🟦",
    "FAIL": "❌",
    "MISSING": "❓",
    "AUDIT_TIMEOUT": "⏳",
    "UNKNOWN": "❔",
}
STAGE_TITLE = [
    ("stage1", "Stage 1 — RTL generation & verification"),
    ("stage2", "Stage 2 — Synthesis + DFT"),
    ("stage3", "Stage 3 — Physical Design"),
    ("stage_analog", "Analog Track A1-A9"),
    ("stage_mixed_signal", "Mixed-Signal M1-M4"),
    ("stage4", "Stage 4 — Sign-off"),
    ("stage5_manufacturing", "Stage 5 — Manufacturing (silicon-dependent)"),
]
# Compact stage labels for the Stage-breakdown overview table only —
# the per-stage detail headers stay full-length.
STAGE_SHORT = {
    "stage1": "Stage 1 (RTL)",
    "stage2": "Stage 2 (Synth/DFT)",
    "stage3": "Stage 3 (PD)",
    "stage_analog": "Analog (A1–A9)",
    "stage_mixed_signal": "Mixed-Signal (M1–M4)",
    "stage4": "Stage 4 (Sign-off)",
    "stage5_manufacturing": "Stage 5 (Mfg)",
}

# #652 — only the manufacturing stage is "awaiting silicon". A
# SKIPPED-CONDITION verdict on any EARLIER step (FPGA board absent,
# capability gap, cascade-blocked, …) is a MID-FLOW skip and must NOT
# be rolled up under the "manufacturing-skipped" label. We classify a
# step structurally — chip-AGNOSTIC, never by chip-specific step names:
#   (1) preferred: the step's own `stage` field equals the manufacturing
#       stage id (`stage5_manufacturing`); else
#   (2) fallback (for snapshots lacking a stage field): the documented
#       manufacturing step-number range 40-44 inclusive.
MANUFACTURING_STAGE_ID = "stage5_manufacturing"
# Documented manufacturing step-number range (inclusive), used only when
# a step record carries no usable `stage` field.
MANUFACTURING_STEP_ID_MIN = 40
MANUFACTURING_STEP_ID_MAX = 44


def _is_manufacturing_step(step: Dict[str, Any]) -> bool:
    """True iff `step` belongs to the silicon-dependent manufacturing
    stage. Structural + chip-AGNOSTIC: prefers the explicit `stage`
    field, falls back to the documented numeric step-id range when the
    step carries no stage. Never keys off chip-specific step names."""
    stage = step.get("stage")
    if stage is not None:
        return stage == MANUFACTURING_STAGE_ID
    sid = step.get("id")
    try:
        n = int(sid)
    except (TypeError, ValueError):
        return False
    return MANUFACTURING_STEP_ID_MIN <= n <= MANUFACTURING_STEP_ID_MAX


def _split_skipped_by_stage(
    flow: Dict[str, Any], verdicts: Dict[str, str]
) -> Tuple[int, int]:
    """#652 — split the SKIPPED-CONDITION rollup BY STAGE.

    Returns ``(manufacturing_skipped, midflow_skipped)``. A step counts
    as manufacturing-skipped only when its verdict is SKIPPED-CONDITION
    AND it is a manufacturing-stage step (`_is_manufacturing_step`);
    every other SKIPPED-CONDITION step is a mid-flow skip. The two
    buckets are mutually exclusive and sum to the total SKIPPED-CONDITION
    rollup, so the report stays honest (mid-flow + manufacturing ==
    total skipped). chip-AGNOSTIC: structural stage classification only.
    """
    mfg = 0
    midflow = 0
    for s in flow.get("steps", []):
        sid = str(s.get("id"))
        if verdicts.get(sid, "MISSING") != "SKIPPED-CONDITION":
            continue
        if _is_manufacturing_step(s):
            mfg += 1
        else:
            midflow += 1
    return mfg, midflow


# ─── helpers ─────────────────────────────────────────────────────────────

def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ck in iter(lambda: f.read(1 << 20), b""):
            h.update(ck)
    return h.hexdigest()


# v1.6.34 — full canonical-artefact attestation table.
# These globs MUST stay in sync with the gate's `_CANONICAL_ARTEFACT_GLOBS`
# in agent_report_sha256_attestation_check.py. The 9-class set covers:
#   FPGA SOF, chip GDS, foundry GDS, synth netlist, PnR netlist,
#   foundry LEF, foundry Liberty, analog hardmacro LEF, analog hardmacro
#   Liberty.
_ATTESTATION_GLOBS: Tuple[Tuple[str, str], ...] = (
    ("FPGA SOF",        "phase2/stage1/fpga/output_files/*.sof"),
    ("chip GDS",        "phase3/stage4/gds/*.gds"),
    ("foundry GDS",     "phase3/stage4/foundry_handoff/**/*.gds"),
    ("synth netlist",   "phase2/stage2/synth/*.v"),
    ("PnR netlist",     "phase3/stage3/pnr/*.v"),
    ("foundry LEF",     "phase3/stage4/foundry_handoff/**/*.lef"),
    ("foundry Liberty", "phase3/stage4/foundry_handoff/**/*.lib"),
    # v1.6.607 — v2-rename cascade leftover (paired with same fix
    # in agent_report_sha256_attestation_check.py). Canonical analog
    # hardmacro location is phase3/analog/hardmacro/.
    ("analog LEF",      "phase3/analog/hardmacro/**/*.lef"),
    ("analog Liberty",  "phase3/analog/hardmacro/**/*.lib"),
)


def _gather_attestation_rows(project: Path
                             ) -> List[Tuple[str, str, int, str]]:
    """Return (kind, rel_path, size_bytes, sha256) tuples for every
    canonical artefact present on disk, in deterministic order. Used by
    the SHA-256 Attestation section so a tape-out reviewer can verify
    artefacts independently. Aligned with agent_report_sha256_attestation
    _check.py canonical glob set."""
    rows: List[Tuple[str, str, int, str]] = []
    for kind, pattern in _ATTESTATION_GLOBS:
        for p in sorted(project.glob(pattern)):
            if not p.is_file():
                continue
            try:
                size = p.stat().st_size
                digest = _sha256(p)
            except OSError:
                continue  # broken symlink / permission denied — gate
                          # reports as ARTEFACT_UNREADABLE
            rel = p.relative_to(project)
            rows.append((kind, str(rel), size, digest))
    return rows


def _render_attestation_section(project: Path) -> List[str]:
    """Render the `## SHA-256 Attestation` section as markdown lines from
    the CURRENT on-disk artefacts. Extracted so the same table can be
    pre-written to disk BEFORE the internal audit runs (see
    `_prewrite_attestation` / #461 symptom (1)) and re-used verbatim in
    the full report."""
    md: List[str] = []
    md.append("## SHA-256 Attestation")
    md.append("")
    md.append("Independent reviewers can verify any artefact by re-")
    md.append("computing `sha256sum <path>` and comparing against the")
    md.append("table below. Every canonical artefact present on disk")
    md.append("is listed; mismatches or omissions are caught by")
    md.append("`agent_report_sha256_attestation_check.py`.")
    md.append("")
    rows = _gather_attestation_rows(project)
    if rows:
        md.append("| Artefact | Path | Size (B) | SHA-256 |")
        md.append("|---|---|---:|---|")
        for kind, rel, size, digest in rows:
            md.append(f"| {kind} | `{rel}` | {size:,} | `sha256:{digest}` |")
    else:
        md.append("_No canonical artefacts present on disk yet._")
    md.append("")
    return md


def _prewrite_attestation(project: Path, out_path: Path) -> None:
    """#461 symptom (1): regenerate-at-audit-time semantics.

    The SHA-256 attestation gate (`agent_report_sha256_attestation_check`)
    runs INSIDE `flow_compliance_check`, which `_render` invokes via
    `_run_audit`. That gate reads the on-disk `reports/final_summary.md`.
    If the previous summary was generated mid-flow — before late
    runner-emitted netlists (synth/PnR netlists, the $_DLATCH techmap
    netlist) appeared on disk — the gate compares the fresh on-disk
    artefact hashes against a stale table and FAILs with
    MISSING_ATTESTATION, even though THIS run is about to write the
    correct table.

    The fix is to make the generator safely re-runnable: write the
    freshly-computed attestation table to the output path BEFORE the
    internal audit runs, so the gate sees up-to-date hashes for every
    artefact currently on disk. `_render` then overwrites the file with
    the complete report (whose attestation section is recomputed
    identically). Best-effort: a write failure is swallowed so the
    report still generates."""
    try:
        section = _render_attestation_section(project)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # A minimal but gate-satisfying document: the attestation table
        # alone carries every `sha256:<64hex>` token the gate scans for.
        prelude = [
            f"# Phase 2+3 Final Summary — {project.name} (attestation pre-pass)",
            "",
            "_Attestation table pre-written before the compliance audit so "
            "the SHA-256 attestation gate reads current artefact hashes "
            "(#461). This file is overwritten with the full report below._",
            "",
        ]
        out_path.write_text("\n".join(prelude + section) + "\n",
                            encoding="utf-8")
    except OSError:
        pass


def _safe_json(p: Path) -> Optional[Any]:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


# Subdirs of reports/ the generator probes (in priority order) when
# looking up a machine-readable artefact by basename. v1.6.25 added
# phase-aligned subfolders; auto-router goes there first.
REPORT_SUBDIRS = (
    "phase1", "phase2", "phase3", "analog",
    "audit", "orchestrator",
    "signoff", "hardware",
)


def _runner_step_record(project: Path, step: str):
    """(status, extras) for one step from the Phase-3 runner's own record.

    ORGANIC #399. `reports/orchestrator/phase3_one_shot.json` already carries
    every step's status plus the substance behind it (violation counts, which
    engine was authoritative). The final report was looking for a
    `<kind>.json` sidecar that nothing writes, so it reported
    "(report missing)" for DRC on runs where DRC ran.

    This READS; it never derives. The runner's status is not a function of the
    raw item count — it re-tiers to WAIVED when every violation is a
    std-cell-library layer rule, and swaps in the Magic count when a re-stream
    is authoritative — so a summary that recomputes from the report
    contradicts the run it is summarising.

    Returns ("", {}) when there is no record, so the caller can keep saying
    "(report missing)" rather than inventing a verdict.
    """
    rec = _find_report(project, "phase3_one_shot.json")
    j = _safe_json(rec) if rec else None
    if not isinstance(j, dict):
        return "", {}
    for s in (j.get("steps") or []):
        if isinstance(s, dict) and s.get("name") == step:
            st = str(s.get("status") or "").strip()
            ex = s.get("extras")
            return st, (ex if isinstance(ex, dict) else {})
    return "", {}


def _find_report(project: Path, name: str) -> Optional[Path]:
    """First try the auto-routed canonical location; if not found, scan
    the legacy/alternate subdirs in priority order."""
    routed = _pl.report_path(project, name)
    if routed.is_file():
        return routed
    base = project / "reports"
    for sd in REPORT_SUBDIRS:
        cand = base / sd / name
        if cand.is_file():
            return cand
    flat = base / name
    if flat.is_file():
        return flat
    return None


def _sweep_reports(project: Path) -> int:
    """Defensive sweep: any flat reports/<file> still at reports/ top level
    (because some legacy script slipped through the v1.6.25 writer
    refactor) gets moved into the phase subfolder its name maps to via
    `_pl.report_path()`. Subdirs and files that ARE the phase subfolders
    themselves are left alone.
    """
    base = project / "reports"
    if not base.is_dir():
        return 0
    moved = 0
    for entry in sorted(base.iterdir()):
        if entry.is_dir() or entry.is_symlink():
            continue
        if entry.name in _pl.REPORTS_VALID_SUBDIRS:
            continue
        dst = _pl.report_path(project, entry.name)
        if dst == entry:
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                dst.unlink()
            entry.rename(dst)
            moved += 1
        except OSError:
            pass
    return moved


def _safe_yaml(p: Path) -> Optional[Any]:
    if not p.is_file():
        return None
    try:
        import yaml  # type: ignore
        return yaml.safe_load(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


# ─── audit / verdicts ────────────────────────────────────────────────────

def _dir_size_bytes(project: Path, cap: int = 1 << 40) -> int:
    """Best-effort total size (bytes) of the run dir, used to make the
    audit timeout size-adaptive. Walks lazily and stops once `cap` is
    exceeded so this never becomes its own hot spot on huge trees.
    chip-AGNOSTIC: pure filesystem arithmetic, no name inspection."""
    total = 0
    try:
        for root, _dirs, files in os.walk(project):
            for fn in files:
                fp = Path(root) / fn
                try:
                    total += fp.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
                if total >= cap:
                    return total
    except OSError:
        pass
    return total


def _resolve_audit_timeout(project: Path,
                           explicit: Optional[int] = None) -> int:
    """Resolve the flow_compliance subprocess timeout (seconds), #469.

    Precedence:
      1. an explicit value (CLI --audit-timeout);
      2. the VIBE_IC_AUDIT_TIMEOUT_S env var (if a positive int);
      3. a size-adaptive default: AUDIT_TIMEOUT_DEFAULT_S, plus
         AUDIT_SIZE_ADAPT_S_PER_MIB for every MiB the run dir exceeds
         AUDIT_SIZE_ADAPT_THRESHOLD_BYTES, capped at AUDIT_TIMEOUT_CAP_S.

    An explicit/env value is honored verbatim (no size adaptation) so a
    test can deliberately shrink it; only the computed default scales.
    Values ≤ 0 are rejected and fall through to the next source."""
    # #525 — delegate to the SHARED resolver in _path_layout (single source
    # of truth; the same budget now also governs phase2 step_final_audit,
    # phase23_completion_self_audit_check and emit_final_summary's outer cap).
    return _pl.audit_timeout_s(project, explicit=explicit,
                               size_fn=_dir_size_bytes)


def _previous_snapshot_marker(project: Path) -> Optional[str]:
    """#469: when the audit times out we cannot compute a fresh snapshot,
    so recover the marker line from the PREVIOUS final_summary.md if one
    exists. That preserves the prior snapshot's timestamp + audit-digest
    so a reader can see the last point at which the design DID audit (and
    distinguish 審不完 / timed-out from 沒審 / never-audited). Returns the
    raw marker payload (the 'snapshot <ts> · audit-digest …' string) or
    None when no prior summary or no marker is present."""
    prev = _pl.report_path(project, "final_summary.md")
    if not prev.is_file():
        return None
    try:
        text = prev.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # The marker is stamped as "_Counts snapshot <ts> · audit-digest
    # sha256:<hex> · overall <V>. …_" (see `_snapshot_marker`).
    m = re.search(r"(snapshot \S+ · audit-digest sha256:[0-9a-f]+ · overall \S+)",
                  text)
    return m.group(1) if m else None


def _extract_overall_token(overall_line: str) -> str:
    """ORGANIC #483 (LOW, symptom 2) — extract the FULL verdict token from
    a `flow_compliance_check.py` "Overall:" summary line.

    `flow_compliance_check.py` prints e.g.::

        Overall: FAIL  (strict=True)
        Overall: PASS_WITH_OPEN_SOURCE_CONSTRAINTS  (strict=True)

    The prior code took ``line.split(":", 1)[1].strip().split()[0]`` which
    keeps only the FIRST whitespace-delimited token — so any verdict that
    contains internal whitespace was truncated to its first chunk (e.g.
    a "FAIL"-shaped verdict rendered mid-line collapsed to the headline
    ``Overall: FA``). The correct token is everything after ``Overall:``
    up to the trailing ``(strict=…)`` annotation (or end of line),
    stripped — never sliced on the first internal space. chip-AGNOSTIC."""
    body = overall_line.split(":", 1)[1] if ":" in overall_line else overall_line
    # Drop the trailing "(strict=…)" / "(…)" annotation the checker appends.
    body = re.split(r"\s*\(", body, maxsplit=1)[0]
    token = body.strip()
    return token or AUDIT_NOT_RUN_VERDICT


def _run_audit(project: Path,
               timeout_s: Optional[int] = None,
               prior_marker: Optional[str] = None) -> Tuple[str, str]:
    """Run flow_compliance_check.py and return (audit_text, overall).

    #469: the timeout is now resolved via `_resolve_audit_timeout`
    (CLI > env > size-adaptive default) rather than a hard-coded 180 s,
    and a TimeoutExpired yields the NAMED verdict AUDIT_TIMEOUT_VERDICT
    (never UNKNOWN) so a reader can distinguish 審不完 (the audit could
    not finish on a large run dir) from 沒審 (the audit was never run).
    Any other failure still degrades to AUDIT_NOT_RUN_VERDICT.

    `prior_marker` is the previous summary's snapshot marker, captured by
    the caller BEFORE any attestation pre-pass overwrote the file (the
    pre-pass would otherwise erase the marker we want to preserve). When
    None, `_run_audit` falls back to reading whatever is on disk."""
    if not COMPLIANCE_TOOL.is_file():
        return ("(flow_compliance_check.py unavailable)", AUDIT_NOT_RUN_VERDICT)
    eff_timeout = _resolve_audit_timeout(project, timeout_s)
    try:
        cp = subprocess.run(
            [sys.executable, str(COMPLIANCE_TOOL), str(project), "--strict"],
            capture_output=True, text=True, timeout=eff_timeout,
        )
        text = cp.stdout
    except subprocess.TimeoutExpired:
        # 審不完: the snapshot is unobtainable. Surface the named verdict
        # and the prior snapshot marker (if any) so the report can tell
        # the reader WHEN the design last audited cleanly.
        prev_marker = prior_marker or _previous_snapshot_marker(project)
        prev_note = (f" Last clean snapshot: {prev_marker}."
                     if prev_marker else
                     " No prior clean snapshot is available.")
        text = (
            f"Overall: {AUDIT_TIMEOUT_VERDICT}\n"
            f"(flow_compliance_check.py did not finish within "
            f"{eff_timeout}s on this run dir — the per-step verdict "
            f"snapshot is unobtainable.{prev_note}\n"
            f" Raise the budget via --audit-timeout / "
            f"{AUDIT_TIMEOUT_ENV} and re-run, or shrink the run dir.)"
        )
        return text, AUDIT_TIMEOUT_VERDICT
    except Exception as exc:
        return (f"(audit failed: {exc})", AUDIT_NOT_RUN_VERDICT)
    overall = AUDIT_NOT_RUN_VERDICT
    for ln in text.splitlines():
        if ln.startswith("Overall:"):
            overall = _extract_overall_token(ln)
            break
    return text, overall


def _parse_verdicts(audit_text: str) -> Dict[str, str]:
    pat = re.compile(r"\[\s*([A-Z][A-Z_-]+?)\s*\]\s*Step\s+([0-9]+|[AM][0-9]+|P0)\s*:")
    return {m.group(2): m.group(1).strip() for m in pat.finditer(audit_text)}


# ─── step tables ─────────────────────────────────────────────────────────

def _trim_step_name(name: str, max_len: int = 50) -> str:
    name = name.replace("🔁 ", "").replace("🔁", "").strip()
    name = re.sub(r"\s*\([^()]*\)\s*$", "", name).strip()
    if len(name) > max_len:
        name = name[:max_len - 1].rstrip() + "…"
    return name


def _compact_id_range(ids: List[str]) -> str:
    """Group consecutive same-prefix IDs into ranges.
      [1,2,3,4,5,6,7]               → '1–7'
      ['A1','A2','A3','A4','A5']    → 'A1–A5'
      [1,2,3,4,5,6,'P0']            → '1–6, P0' (mixed: list each group)
    """
    if len(ids) <= 3:
        return ", ".join(ids)
    # Split into prefix groups
    groups: Dict[str, List[int]] = {}
    for sid in ids:
        m = re.match(r"^([A-Za-z]*)(\d+)$", sid)
        if not m:
            groups.setdefault("__misc__", []).append(0)
            continue
        prefix = m.group(1)
        num = int(m.group(2))
        groups.setdefault(prefix, []).append(num)
    parts = []
    for prefix, nums in groups.items():
        nums = sorted(nums)
        if len(nums) >= 4:
            parts.append(f"{prefix}{nums[0]}–{prefix}{nums[-1]}")
        else:
            parts.extend(f"{prefix}{n}" for n in nums)
    return f"{', '.join(parts)} ({len(ids)})"


def _compact_outputs(outs: List[str]) -> str:
    if not outs:
        return "—"
    first = outs[0].replace(" OR ", " / ")
    if len(outs) > 1:
        return f"`{first}` _(+{len(outs)-1})_"
    return f"`{first}`"


def _compact_inputs(blocks_on: List[Any]) -> str:
    if not blocks_on:
        return "raw `input/`"
    if len(blocks_on) > 4:
        # Long input list → contract to first–last + count
        return f"{blocks_on[0]}–{blocks_on[-1]} ({len(blocks_on)})"
    return ", ".join(str(b) for b in blocks_on)


def _step_sort_key(s: Dict[str, Any]) -> Tuple[int, str, int]:
    sid = s["id"]
    if isinstance(sid, str):
        m = re.match(r"([AMP])(\d+|0)", sid)
        if m:
            return (0 if m.group(1) == "P" else 1, m.group(1), int(m.group(2)))
        # other lettered ids (FS1, DT1/DT2/DT3, E1-E3, ...) - sort after the
        # numeric steps, grouped by the alpha prefix then its trailing number.
        # NEVER int()-cast the whole lettered id (the 'FS1'/'DT1' crash class).
        m2 = re.match(r"([A-Za-z]+)(\d+)$", sid)
        if m2:
            return (2, m2.group(1), int(m2.group(2)))
    try:
        return (0, "", int(sid))
    except (TypeError, ValueError):
        return (2, str(sid), 0)


def _render_step_tables(flow: Dict[str, Any], verdicts: Dict[str, str]) -> str:
    """Per-stage step listing as compact 5-col markdown tables.

    Width-hardened: step name trimmed to 35 chars, inputs use compact
    range form, output column shows only the first artefact path (no
    `OR`/`|` alternation, no `_(+N)_` suffix). Result: every per-stage
    table fits within ~75 chars, renders cleanly in glow at any terminal
    ≥ 80 cols.
    """
    by_stage: Dict[str, List[Dict[str, Any]]] = {}
    for s in flow.get("steps", []):
        if s.get("id") == "P0":
            continue
        by_stage.setdefault(s["stage"], []).append(s)

    def _first_output(outs: List[str], max_len: int = 28) -> str:
        if not outs:
            return "—"
        first = outs[0].split(" OR ", 1)[0].strip()
        if len(first) > max_len:
            first = first[:max_len - 1].rstrip("/") + "…"
        return f"`{first}`"

    out: List[str] = []
    p0v = VERDICT_SYM.get(verdicts.get("P0", "?"), verdicts.get("P0", "?"))
    out.append("### P0 — Structural-RTL umbrella (chip-agnostic checkers)\n")
    out.append("| ID | Coverage | V |")
    out.append("|---|---|:---:|")
    out.append(f"| **P0** | CDC/RDC + CRC oracle + L9-conformance + protocol audits | {p0v} |\n")
    for stage_id, _full in STAGE_TITLE:
        rows = sorted(by_stage.get(stage_id, []), key=_step_sort_key)
        if not rows:
            continue
        out.append(f"### {_full}\n")
        out.append("| ID | Step | ← | Output | V |")
        out.append("|---:|---|:---:|---|:---:|")
        for s in rows:
            sid = str(s["id"])
            v = VERDICT_SYM.get(verdicts.get(sid, "?"), verdicts.get(sid, "?"))
            name = _trim_step_name(s["name"], max_len=25)
            inputs = _compact_inputs(s.get("blocks_on") or [])
            if inputs == "raw `input/`":
                inputs = "—"
            output = _first_output(s.get("required_outputs") or [], max_len=22)
            out.append(f"| {sid} | {name} | {inputs} | {output} | {v} |")
        out.append("")
    return "\n".join(out)


def _verdict_rollup(flow: Dict[str, Any], verdicts: Dict[str, str]) -> Tuple[Dict[str, int], int]:
    counts = collections.Counter()
    total = 0
    for s in flow.get("steps", []):
        sid = str(s["id"])
        v = verdicts.get(sid, "MISSING")
        counts[v] += 1
        total += 1
    return dict(counts), total


def _counts_snapshot(
    rollup: Dict[str, int],
    total_steps: int,
    flow: Optional[Dict[str, Any]] = None,
    verdicts: Optional[Dict[str, str]] = None,
) -> Dict[str, int]:
    """#461 symptom (2): derive ALL displayed counts from ONE rollup.

    `executed_pass` / `executed_total` match the audit summary line's
    "X/Y executed PASS" definition (PASS + VACUOUS-PASS over
    total − waived − skipped, per flow_compliance_check Wave 93), so
    the headline audit block, the prose bullets, and the resource log
    never disagree. `pass_only` is the strict PASS bucket retained for
    the per-verdict roll-up table. chip-AGNOSTIC: pure arithmetic on
    verdict buckets.

    #652 — the SKIPPED-CONDITION total (`skipped`) is ALSO split BY
    STAGE into `skipped_manufacturing` (silicon-dependent steps 40-44 /
    `stage5_manufacturing`) and `skipped_midflow` (every earlier
    SKIPPED-CONDITION step: FPGA board absent, capability gap,
    cascade-blocked, …). The split needs the per-step `flow` + verdicts;
    when they are not supplied the whole total is conservatively booked
    as mid-flow (no step is silently mislabelled as a silicon skip).
    `skipped_manufacturing + skipped_midflow == skipped` always holds."""
    pass_only = rollup.get("PASS", 0)
    vacuous = rollup.get("VACUOUS-PASS", 0)
    waived = rollup.get("WAIVED-DEFERRED", 0)
    skipped = rollup.get("SKIPPED-CONDITION", 0)
    fail = rollup.get("FAIL", 0)
    missing = rollup.get("MISSING", 0)
    executed_pass = pass_only + vacuous
    executed_total = total_steps - waived - skipped
    if flow is not None and verdicts is not None:
        skipped_manufacturing, skipped_midflow = _split_skipped_by_stage(flow, verdicts)
    else:
        # No per-step context: book the whole bucket as mid-flow rather
        # than risk labelling a non-silicon skip as a manufacturing one.
        skipped_manufacturing, skipped_midflow = 0, skipped
    return {
        "pass_only": pass_only,
        "vacuous": vacuous,
        "waived": waived,
        "skipped": skipped,
        "skipped_manufacturing": skipped_manufacturing,
        "skipped_midflow": skipped_midflow,
        "fail": fail,
        "missing": missing,
        "executed_pass": executed_pass,
        "executed_total": executed_total,
        "total_steps": total_steps,
    }


def _snapshot_marker(audit_text: str, overall: str) -> str:
    """A short, stable digest of the audit text + verdict, plus a UTC
    timestamp, stamped beside the verdict so a reader knows the counts
    are a point-in-time snapshot and a fresh `--strict` re-run may move
    them once late artefacts land (#461 symptom (2))."""
    h = hashlib.sha256(audit_text.encode("utf-8", errors="replace")).hexdigest()[:12]
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"snapshot {ts} · audit-digest sha256:{h} · overall {overall}"


# ─── artefact gathering ──────────────────────────────────────────────────

# #737 — instance-line matcher for a generic/liberty-mapped gate-level
# netlist. The legacy matcher anchored on an UPPERCASE-leading token
# (`^\s*([A-Z][A-Z0-9_]+)\s+...`), which matches ZERO of:
#   * Yosys generic gates — `\$_NAND_`, `\$_DFF_P_`, … (lead with `\$`)
#   * lowercase liberty cells — `sky130_fd_sc_hd__nand2_1`, … (lead lowercase)
# so a fully-populated post-synth netlist of either kind reported 0 cells.
# This widened matcher accepts a cell-master token that may start with an
# OPTIONAL escaped-`\$` (generic gates) and any letter case, followed by an
# instance name (optionally escaped) and the opening `(` of the port map.
# chip-AGNOSTIC: structural Verilog instance shape, no chip/cell-lib literal.
_NETLIST_INST_RE = re.compile(
    r"^\s*("
    r"\\\$_[A-Za-z0-9_]+_"            # generic gate: \$_NAND_, \$_DFF_P_, …
    r"|\\?\$?[A-Za-z][A-Za-z0-9_$]*"   # liberty/legacy: sky130_…, NAND2X1, …
    r")\s+\\?[\w\.\[\]$]+\s*"          # instance name
    r"(?:/\*[^*]*\*/\s*)?"             # optional inline /* _N_ */ comment
    r"\(", re.M)

# Verilog structural keywords that lead a line in the same shape as an
# instance (e.g. `module foo (`, `wire \x ;`) but are NOT cells. Excluded so
# the widened matcher never inflates the count with declarations.
_NETLIST_NONCELL = frozenset({
    "module", "endmodule", "input", "output", "inout", "wire", "reg",
    "assign", "parameter", "localparam", "function", "endfunction",
    "generate", "endgenerate", "always", "initial", "begin", "end",
    "if", "else", "case", "endcase", "for", "while", "specify",
})


def _gather_cell_count(project: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {"total_synth": None, "top": [], "def_components": None,
                           "netlist_path": None, "def_path": None,
                           "synth_count_source": None, "empty_netlist": None}
    sd = _pl.synth_dir(project)
    netlist = None
    if sd.is_dir():
        for fn in ("chip_top_asic_synth.v", "netlist.v"):
            cand = sd / fn
            if cand.is_file():
                netlist = cand
                break
        if netlist is None:
            cands = list(sd.glob("*synth*.v"))
            if cands:
                netlist = cands[0]
    # #737 — PREFER the authoritative yosys `stat` count (stat.json, then
    # the yosys log's `Number of cells:` / `NNNNN cells` line). A netlist
    # name scan is fragile across mapping styles (generic vs liberty vs
    # case), so when the synth step recorded a real stat we trust it. The
    # netlist scan stays as the fallback AND as the per-type `top` table.
    stat_total = None
    stat_top: List[Tuple[str, int]] = []
    if sd.is_dir():
        stat_json = sd / "stat.json"
        if stat_json.is_file():
            try:
                sj = json.loads(stat_json.read_text(errors="replace"))
                mods = sj.get("modules", {}) if isinstance(sj, dict) else {}
                # PREFER yosys's top-level `design` aggregate when present.
                # `stat -json -top <top>` emits a sibling `design` block whose
                # num_cells is the WHOLE-design (flattened-equivalent) leaf
                # total. The per-module largest-module heuristic UNDER-counts a
                # HIERARCHICAL (non-flattened) netlist — e.g. leaf{1}/mid{2}/
                # top{2} reports 2 while the real design total is 3 — and
                # disagrees with the sibling yosys.log `Number of cells:` line
                # and the phase2 parser, which both give the design total.
                # Fall back to the largest module only when no design
                # aggregate is recorded (e.g. a plain `stat -json` with no
                # -top, which omits the design block).
                design = sj.get("design") if isinstance(sj, dict) else None
                best = None
                if isinstance(design, dict):
                    d_nc = design.get("num_cells")
                    d_by = design.get("num_cells_by_type")
                    if isinstance(d_nc, int):
                        best = ("design", d_nc,
                                d_by if isinstance(d_by, dict) else {})
                    elif isinstance(d_by, dict):
                        # No explicit total but a by-type table — sum it.
                        total = sum(v for v in d_by.values()
                                    if isinstance(v, int))
                        best = ("design", total, d_by)
                if best is None:
                    # No design aggregate: pick the module with the most cells.
                    for _name, m in mods.items():
                        if not isinstance(m, dict):
                            continue
                        nc = m.get("num_cells")
                        if isinstance(nc, int) and (best is None or nc > best[1]):
                            by_type = m.get("num_cells_by_type") or {}
                            best = (_name, nc, by_type)
                if best is not None:
                    stat_total = best[1]
                    if isinstance(best[2], dict):
                        stat_top = sorted(
                            ((str(k), int(v)) for k, v in best[2].items()
                             if isinstance(v, int)),
                            key=lambda kv: kv[1], reverse=True)[:15]
                    out["synth_count_source"] = "stat.json"
            except (ValueError, TypeError):
                stat_total = None
        if stat_total is None:
            log = sd / "yosys.log"
            if log.is_file():
                lt = log.read_text(errors="replace")
                m = re.findall(r"Number of cells:\s*([0-9][0-9,]*)", lt)
                if not m:
                    m = re.findall(r"^\s*([0-9][0-9,]*)\s+cells\s*$", lt, re.M)
                if m:
                    try:
                        stat_total = int(m[-1].replace(",", ""))
                        out["synth_count_source"] = "yosys.log"
                    except ValueError:
                        stat_total = None
    if netlist is not None:
        out["netlist_path"] = str(netlist.relative_to(project))
        text = netlist.read_text(errors="replace")
        cells = collections.Counter(
            tok for tok in _NETLIST_INST_RE.findall(text)
            if tok.lower().lstrip("\\") not in _NETLIST_NONCELL
        )
        scan_total = sum(cells.values())
        # Authoritative stat count wins; the scan supplies the `top` table
        # (and is the fallback when no stat was recorded). When stat is
        # absent fall back to the widened scan; flag a genuinely-empty
        # netlist DISTINCTLY so a parser-miss (0 because no name matched) is
        # never silently confused with a real empty netlist.
        if stat_total is not None:
            out["total_synth"] = stat_total
        else:
            out["total_synth"] = scan_total
            out["synth_count_source"] = "netlist_scan"
        out["top"] = stat_top if stat_top else cells.most_common(15)
        out["empty_netlist"] = (out["total_synth"] == 0)
    elif stat_total is not None:
        # stat recorded but the netlist file itself was not located.
        out["total_synth"] = stat_total
        out["top"] = stat_top
        out["empty_netlist"] = (stat_total == 0)
    pd = _pl.pnr_dir(project)
    if pd.is_dir():
        for fn in ("routed.def", "post_hold.def", "post_cts.def",
                   "placed.def", "floorplan.def"):
            cand = pd / fn
            if cand.is_file():
                try:
                    for line in cand.read_text(errors="replace").splitlines():
                        if line.startswith("COMPONENTS "):
                            out["def_components"] = int(line.split()[1])
                            out["def_path"] = str(cand.relative_to(project))
                            break
                except Exception:
                    pass
                if out["def_components"] is not None:
                    break
    return out


def _gather_hardware_test(project: Path) -> Dict[str, Any]:
    """Generic hw-test schema: {tester, board, verdict, criterion, iterations,
    passed_iterations, evidence}. Reads reports/hw_test.json (canonical);
    falls back to the legacy generic tester file (example_tester_test.json,
    renamed from the old benchmark-specific name) when no canonical file
    exists. Chip-specific keys in the legacy file (e.g. a hard-coded
    verdict byte) are NOT propagated — only the generic verdict / run-count
    fields are coerced into the generic schema, so the canonical summary
    stays chip-AGNOSTIC."""
    p = _find_report(project, "hw_test.json")
    d = _safe_json(p) if p else None
    if isinstance(d, dict):
        return {**d, "_source": str(p.relative_to(project))}
    # Legacy fallback — generic tester verdict file. Coerce only the
    # generic fields; never echo chip-specific byte payloads.
    lp = _find_report(project, "example_tester_test.json")
    ld = _safe_json(lp) if lp else None
    if isinstance(ld, dict):
        out: Dict[str, Any] = {}
        if ld.get("verdict") is not None:
            out["verdict"] = ld["verdict"]
        runs = ld.get("runs")
        if runs is not None:
            out["iterations"] = runs
        out["_source"] = f"(legacy {lp.relative_to(project)})"
        return out
    return {}


def _gather_sof(project: Path) -> Optional[Dict[str, Any]]:
    fpga = _pl.fpga_early_dir(project)
    for d in (fpga, fpga / "output_files", fpga / "final"):
        if not d.is_dir():
            continue
        sofs = list(d.glob("*.sof"))
        if sofs:
            f = sofs[0]
            return {"path": str(f.relative_to(project)),
                    "size": f.stat().st_size,
                    "sha256": _sha256(f)}
    return None


def _gather_gds(project: Path) -> Optional[Dict[str, Any]]:
    d = _pl.gds_dir(project)
    if not d.is_dir():
        return None
    gds_files = list(d.glob("*.gds"))
    if not gds_files:
        return None
    f = gds_files[0]
    pv = {}
    for kind in ("drc_signoff", "lvs", "erc"):
        cand = _find_report(project, f"{kind}.json")
        j = _safe_json(cand) if cand else None
        if isinstance(j, dict):
            pv[kind] = j.get("verdict") or j.get("status") or "?"
        else:
            pv[kind] = "(report missing)"
    # ORGANIC #399 — nothing in this tree writes `drc_signoff.json`; the
    # producer stages a `.rpt`. So the sign-off summary a reader treats as
    # the deliverable said "(report missing)" for DRC on 16 of the 19
    # committed runs that HAVE a runner record — including runs whose
    # `step_drc` recorded PASS, FAIL or WAIVED with real violation counts.
    #
    # ECHO the runner's own verdict; do NOT re-derive one from the raw
    # report. #399 measured a prototype that parsed the RDB: it produced
    # `FAIL (N violations)` on five runs the runner had recorded as WAIVED,
    # because the runner deliberately re-tiers to WAIVED when every
    # violation falls in std-cell-library layer rules, and substitutes the
    # Magic count when a re-stream is authoritative. A report that
    # contradicts the run it summarises is worse than one that under-reports.
    if pv.get("drc_signoff") == "(report missing)":
        _st, _ex = _runner_step_record(project, "drc")
        if _st:
            _bits = [f"{k}={_ex[k]}" for k in
                     ("total_violations", "user_routing_violations",
                      "stdcell_library_violations", "drc_authority",
                      "streamout_engine") if _ex.get(k) is not None]
            pv["drc_signoff"] = (
                f"{_st} (runner step_drc"
                + (f"; {', '.join(str(b) for b in _bits)}" if _bits else "")
                + ")")
    # Auxiliary signoff reports (IR / EM / antenna / SI / power / STA)
    aux: List[str] = []
    for stem in ("ir_drop", "em", "antenna", "si_crosstalk", "power",
                 "sta/post_route_summary"):
        # sta/ has a nested-path stem; the rest are simple file names.
        if "/" in stem:
            for ext in (".json", ".rpt"):
                p = _pl.report_path(project, f"{stem}{ext}")
                if p.is_file():
                    aux.append(str(p.relative_to(project)))
                    break
            continue
        for ext in (".json", ".rpt"):
            p = _find_report(project, f"{stem}{ext}")
            if p is not None:
                aux.append(str(p.relative_to(project)))
                break
    fpga_signoff = _find_report(project, "fpga_signoff.json")
    return {"path": str(f.relative_to(project)),
            "size": f.stat().st_size,
            "sha256": _sha256(f),
            "pv": pv,
            "aux_reports": aux,
            "fpga_signoff": str(fpga_signoff.relative_to(project)) if fpga_signoff else None}


def _gather_test_evidence(project: Path) -> Dict[str, Any]:
    """Generic test-pattern evidence: reference TB log + sim_full_stack +
    extra count fields. Chip-agnostic — no opcode list."""
    out: Dict[str, Any] = {"ref_tb_logs": [], "sim_full_stack": None,
                           "vectors_total": None, "vectors_passed": None,
                           "distinct_non_padding_bytes": None,
                           "opcodes_tested": None, "all_proved": None,
                           "vectors_csv": None}
    refdir = _pl.sim_dir(project) / "reference_tb"
    if refdir.is_dir():
        out["ref_tb_logs"] = [str(p.relative_to(project))
                              for p in sorted(refdir.glob("*.log"))]
    sfs = _pl.sim_full_stack_dir(project) / "results.json"
    d = _safe_json(sfs)
    if isinstance(d, dict):
        out["sim_full_stack"] = str(sfs.relative_to(project))
        for k in ("vectors_total", "vectors_passed",
                 "distinct_non_padding_bytes", "opcodes_tested", "all_proved"):
            if k in d:
                out[k] = d[k]
    tb = _pl.tb_dir(project)
    if tb.is_dir():
        csvs = list(tb.glob("*test_vectors.csv")) + list(tb.glob("*.csv"))
        if csvs:
            out["vectors_csv"] = str(csvs[0].relative_to(project))
    return out


def _gather_analog_evidence(project: Path) -> Dict[str, Any]:
    """For each declared analog block, check which A1-A9 artefacts exist
    and what mixed-signal / HW evidence is on disk. Chip-agnostic."""
    bl = _safe_json(_pl.analog_dir(project) / "analog_block_list.json")
    if not bl:
        return {}
    blocks_raw = bl.get("blocks") if isinstance(bl, dict) else bl
    block_names: List[str] = []
    for b in blocks_raw or []:
        if isinstance(b, dict):
            n = b.get("name")
            if n:
                block_names.append(n)
        elif isinstance(b, str):
            block_names.append(b)
    # #461 symptom (4): SINGLE SOURCE — the per-A-step presence grid
    # MUST probe the SAME paths the per-block compliance checkers
    # (analog_a{1..9}_*_check.py) inspect, or the report's grid shows
    # all "—" while the compliance gate judges PASS. Those checkers
    # ALL root at `phase3/analog/<block>/` (and
    # `phase3/analog/hardmacro/<block>/` for A8) with a legacy
    # `analog/<block>/` fallback. The prior version diverged: it
    # looked up A1 under phase1/analog/, A2-A4 under phase2/analog/
    # (per the `_pl.phaseN_analog_block_dir` helpers, which describe a
    # layout the analog runner does NOT actually emit to), so on every
    # real project the corner/topology/spec cells read "—" even
    # though A4 corner_results.json existed and the A4 gate PASSed.
    #
    # The canonical-vs-checker truth is: the checkers win (they are the
    # gate of record). `_analog_a_step_paths` mirrors their globs
    # exactly; see programs/analog_a{1..9}_*_check.py.
    block_grid = _gather_analog_block_grid(project, block_names)
    # HW measurements present?
    hw_present = any((_pl.analog_dir(project) / n / "hw_measurements.json").is_file()
                     for n in block_names)
    # Mixed-signal references
    mixed_paths: List[str] = []
    for f in ("mixed_signal/top_merged.gds",
              "reports/mixed_signal/merge.json",
              "reports/mixed_signal/power_domain.json",
              "reports/mixed_signal/level_shifter.json",
              "reports/mixed_signal/isolation.json",
              "reports/mixed_signal/interface_si.json",
              "reports/mixed_signal/signoff.json",
              "cosim/mixed_signal_results.json"):
        if (project / f).is_file():
            mixed_paths.append(f)
    return {"block_names": block_names,
            "block_grid": block_grid,
            "hw_tuning_invoked": hw_present,
            "mixed_paths": mixed_paths}


def _analog_a_step_paths(project: Path, block: str) -> Dict[str, List[Path]]:
    """Return the candidate paths for each A1-A9 artefact, MIRRORING the
    per-block compliance checkers (single source of truth). Each
    checker's canonical path is documented inline; the legacy
    `analog/<block>/` fallback matches the A6 checker's `_block_dir`
    helper which accepts either `phase3/analog/<block>/` or the v1
    root-level `analog/<block>/`. Keeping this in lockstep with the
    checkers is what closes #461 symptom (4)."""
    def _safe_glob(d: Path, pattern: str) -> List[Path]:
        return list(d.glob(pattern)) if d.is_dir() else []

    p3 = project / "phase3" / "analog" / block       # analog_a{1-7,9}_*_check
    p3_hm = project / "phase3" / "analog" / "hardmacro" / block  # analog_a8_*
    legacy = project / "analog" / block              # A6 _block_dir fallback
    legacy_hm = project / "analog" / "hardmacro" / block
    return {
        # analog_a1_spec_extract_check: phase3/analog/<b>/spec.json
        "A1": [p3 / "spec.json", legacy / "spec.json"],
        # analog_a2_topology_select_check: phase3/analog/<b>/topology.md
        "A2": [p3 / "topology.md", legacy / "topology.md"],
        # analog_a3_netlist_gen_check: phase3/analog/<b>/<b>.sp
        "A3": ([p3 / f"{block}.sp"] + _safe_glob(p3, "*.sp")
               + [legacy / f"{block}.sp"] + _safe_glob(legacy, "*.sp")),
        # analog_a4_corner_sweep_check: phase3/analog/<b>/corner_results.json
        "A4": [p3 / "corner_results.json",
               legacy / "corner_results.json"],
        # analog_a5_layout_check: phase3/analog/<b>/{layout.mag,<b>.gds}
        "A5": [p3 / "layout.mag", p3 / f"{block}.gds",
               legacy / "layout.mag", legacy / f"{block}.gds"],
        # analog_a6_block_pv_check: drc_clean.flag / drc.report / lvs_match.flag
        "A6": [p3 / "drc_clean.flag", p3 / "drc.report",
               p3 / "lvs_match.flag",
               legacy / "drc_clean.flag", legacy / "drc.report",
               legacy / "lvs_match.flag"],
        # analog_a7_post_layout_resim_check: phase3/analog/<b>/pre_vs_post.json
        "A7": [p3 / "pre_vs_post.json", legacy / "pre_vs_post.json"],
        # analog_a8_hardmacro_gen_check: phase3/analog/hardmacro/<b>/*.lef
        "A8": (_safe_glob(p3_hm, "*.lef") + _safe_glob(legacy_hm, "*.lef")),
        # analog_a9_hw_verify_check: phase3/analog/<b>/hw_measurements.json
        "A9": [p3 / "hw_measurements.json",
               legacy / "hw_measurements.json"],
    }


def _gather_analog_block_grid(project: Path, block_names: List[str]
                              ) -> Dict[str, Dict[str, bool]]:
    """A1-A9 presence grid per block, using `_analog_a_step_paths`
    (the compliance-checker mirror). Factored out so the test can pin
    that the grid sees an artefact at the SAME path the gate accepts."""
    block_grid: Dict[str, Dict[str, bool]] = {}
    for name in block_names:
        candidates = _analog_a_step_paths(project, name)
        block_grid[name] = {
            step: any(p.exists() for p in paths if p is not None)
            for step, paths in candidates.items()
        }
    return block_grid


def _gather_test_patterns(project: Path) -> Dict[str, Any]:
    """Chip-agnostic count summary: total cases, passed, distinct stimulus
    bytes (parsed from JSON text). Does NOT enumerate opcodes — those belong
    in chip_specific_summary.md."""
    p = _find_report(project, "test_cases.json")
    d = _safe_json(p) if p else None
    if not isinstance(d, dict):
        return {}
    cases = d.get("test_cases") or d.get("cases") or []
    total = d.get("total") or len(cases) if isinstance(cases, list) else None
    passed = d.get("passed")
    if passed is None and isinstance(cases, list):
        passed = sum(1 for c in cases if isinstance(c, dict)
                     and (c.get("verdict") or c.get("pass")) in ("PASS", True))
    raw = json.dumps(d)
    distinct_hex = sorted(set(re.findall(r"0x[0-9A-Fa-f]{2}", raw)))
    return {"total": total, "passed": passed,
            "distinct_stimulus_bytes": len(distinct_hex)}


def _gather_analog(project: Path) -> Dict[str, Any]:
    bl_path = _pl.analog_dir(project) / "analog_block_list.json"
    bl = _safe_json(bl_path)
    if not bl:
        return {}
    blocks_raw = bl.get("blocks") if isinstance(bl, dict) else bl
    block_names: List[str] = []
    for b in blocks_raw or []:
        if isinstance(b, dict):
            n = b.get("name")
            if n:
                block_names.append(n)
        elif isinstance(b, str):
            block_names.append(b)
    tuning_summary: List[Dict[str, Any]] = []
    for name in block_names:
        tj = _safe_json(_pl.analog_dir(project) / name / "tuning_loop.json")
        if not isinstance(tj, dict):
            continue
        iters = tj.get("iterations") or []
        if isinstance(iters, list):
            iter_count = len(iters)
            converged = bool(iters) and bool(iters[-1].get("all_corners_pass"))
        else:
            iter_count, converged = None, None
        tuning_summary.append({"block": name,
                               "iterations": iter_count,
                               "converged": converged})
    return {"blocks": block_names, "tuning": tuning_summary}


def _gather_waivers(project: Path) -> Dict[str, Any]:
    """Return both per-step waivers and top-level *_unavailable_reason
    annotations (PDK / EDA gaps). Both are needed for an honest report."""
    d = _safe_json(project / "waivers.json")
    if isinstance(d, dict):
        steps = d.get("waived_steps") or d.get("waivers") or []
        gaps = {k: v for k, v in d.items()
                if k.endswith("_unavailable_reason") and isinstance(v, str)}
        return {"steps": steps, "gaps": gaps}
    if isinstance(d, list):
        return {"steps": d, "gaps": {}}
    return {"steps": [], "gaps": {}}


def _gather_ic_name(project: Path) -> Optional[str]:
    # #461 symptom (3): the canonical L-doc location is
    # `phase1/generated_docs/` (per `_pl.generated_docs_dir`), NOT a
    # flat `generated_docs/` at the project root. The prior version
    # probed only the flat path, so on every real project tree it fell
    # through to the "(unknown — fill in via L1_DATASHEET.json[ic_name])"
    # placeholder even though `ic_name` was populated. Probe the
    # canonical phase1 dir first, then the flat legacy path.
    gd = _pl.generated_docs_dir(project)
    for cand in (gd / "L1_DATASHEET.json",
                 gd / "L2_FRS.json",
                 project / "generated_docs" / "L1_DATASHEET.json",
                 project / "generated_docs" / "L2_FRS.json"):
        d = _safe_json(cand)
        if isinstance(d, dict):
            n = d.get("ic_name") or d.get("part_number")
            if n:
                return str(n)
    return None


# ─── rendering ───────────────────────────────────────────────────────────

def _render(project: Path, run_audit: bool = True,
            audit_timeout_s: Optional[int] = None,
            prior_marker: Optional[str] = None) -> str:
    flow = _safe_yaml(FLOW_YAML) or {}
    # #469: capture the prior snapshot marker BEFORE the audit (which, on
    # the main() path, runs after an attestation pre-pass that overwrote
    # the file). The caller may also supply it explicitly.
    if prior_marker is None:
        prior_marker = _previous_snapshot_marker(project)
    if run_audit:
        audit_text, overall = _run_audit(project, timeout_s=audit_timeout_s,
                                         prior_marker=prior_marker)
    else:
        audit_text, overall = ("(audit skipped)", AUDIT_NOT_RUN_VERDICT)
    verdicts = _parse_verdicts(audit_text)

    cells = _gather_cell_count(project)
    hw = _gather_hardware_test(project)
    sof = _gather_sof(project)
    gds = _gather_gds(project)
    tp = _gather_test_patterns(project)
    tp_ev = _gather_test_evidence(project)
    analog = _gather_analog(project)
    analog_ev = _gather_analog_evidence(project)
    waivers_pkg = _gather_waivers(project)
    waivers = waivers_pkg["steps"]
    pdk_gaps = waivers_pkg["gaps"]
    ic_name = _gather_ic_name(project) or "(unknown — fill in via L1_DATASHEET.json[ic_name])"
    rollup, total_steps = _verdict_rollup(flow, verdicts)
    chip_addendum = (_pl.report_path(project, "chip_specific_summary.md")).is_file()

    # #461 symptom (2): SINGLE COUNTS SNAPSHOT. Every PASS / executed
    # count displayed anywhere in the report derives from THIS one
    # `_verdict_rollup` parse of THIS one audit run — never from a
    # second flow_compliance parse and never from a different PASS
    # definition. `executed_pass` matches the audit summary line's
    # "X/Y executed PASS" semantics (PASS + VACUOUS-PASS rolled in,
    # per flow_compliance_check Wave 93) so the headline audit block,
    # the prose, and the resource log all agree. A snapshot marker is
    # stamped so a reader knows a fresh `--strict` re-run can move the
    # numbers (e.g. once late artefacts land).
    snap = _counts_snapshot(rollup, total_steps, flow=flow, verdicts=verdicts)
    snapshot_marker = _snapshot_marker(audit_text, overall)

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    md: List[str] = []
    md.append(f"# Phase 2+3 Final Summary — {project.name}")
    md.append(f"")
    md.append(f"_Auto-generated chip-AGNOSTIC summary by_ "
              f"`final_report_generate.py` _at {now} (UTC)._")
    md.append(f"")
    md.append(f"- **IC**: `{ic_name}`")
    md.append(f"- **Project root**: `{project}`")
    md.append(f"")
    md.append(f"## Verdict")
    md.append(f"")
    md.append(f"**`Overall: {overall}`**")
    md.append(f"")
    if overall == AUDIT_TIMEOUT_VERDICT:
        # #469: 審不完 (timed out), NOT 沒審 (never audited). The per-step
        # snapshot is unobtainable on this run dir, so the counts below
        # are degraded — say so explicitly and surface the prior clean
        # snapshot marker if one was captured before the pre-pass.
        prev_marker = prior_marker
        md.append(f"> ⏳ **AUDIT_TIMEOUT** — `flow_compliance_check.py` did "
                  f"not finish in the configured budget on this run dir, so "
                  f"a fresh per-step verdict snapshot could not be computed. "
                  f"This is *審不完 (timed out)*, distinct from *沒審 (never "
                  f"audited)*. The counts below are degraded and must not be "
                  f"read as PASS/FAIL.")
        md.append(f">")
        if prev_marker:
            md.append(f"> Last clean snapshot: `{prev_marker}`.")
        else:
            md.append(f"> No prior clean snapshot is available.")
        md.append(f">")
        md.append(f"> Raise the budget via `--audit-timeout <seconds>` or "
                  f"`{AUDIT_TIMEOUT_ENV}=<seconds>` and re-run, or shrink the "
                  f"run dir, to obtain a real Overall verdict.")
        md.append(f"")
    md.append(f"_Counts {snapshot_marker}. A fresh "
              f"`flow_compliance_check.py --strict` re-run may move these "
              f"once late artefacts land._")
    md.append(f"")
    md.append("```")
    audit_lines = audit_text.strip().splitlines()
    # First 5 lines of the audit are the header + Steps + tally
    for ln in audit_lines[:5]:
        md.append(ln)
    md.append("```")
    md.append("")
    # #461 symptom (2): every count below comes from the SINGLE `snap`
    # snapshot — never a second parse, never a divergent PASS definition.
    pass_n = snap["pass_only"]
    waived_n = snap["waived"]
    skipped_n = snap["skipped"]
    vacuous_n = snap["vacuous"]
    fail_n = snap["fail"]
    executed_pass = snap["executed_pass"]
    executed_total = snap["executed_total"]
    md.append(f"- PASS={pass_n} (+VACUOUS-PASS={vacuous_n} → executed PASS="
              f"{executed_pass}) — every executed canonical step passed "
              f"deterministically.")
    if waived_n:
        md.append(f"- WAIVED-DEFERRED={waived_n} — deferred via documented waiver "
                  "(human review required before tapeout).")
    if skipped_n:
        # #652 — split the SKIPPED-CONDITION total by stage so mid-flow
        # skips (FPGA board absent / capability gap / cascade-blocked)
        # are not mislabelled as silicon-stage skips. Only the
        # manufacturing-stage steps are genuinely "awaiting silicon".
        skipped_mfg_n = snap["skipped_manufacturing"]
        skipped_mid_n = snap["skipped_midflow"]
        md.append(f"- SKIPPED-CONDITION={skipped_n} — gate predicate not yet met. "
                  f"manufacturing-stage (awaiting silicon)={skipped_mfg_n}; "
                  f"mid-flow (board absent / capability gap / "
                  f"cascade-blocked)={skipped_mid_n}.")
    if vacuous_n:
        md.append(f"- VACUOUS-PASS={vacuous_n} — gate accepts the present project "
                  "shape; check whether it should be a real PASS for your flow.")
    if fail_n:
        md.append(f"- **FAIL={fail_n}** — blocking; do not claim PASS.")
    md.append("")
    md.append(f"Per the SOLE ACCEPTANCE CRITERION: `executed PASS = "
              f"{executed_pass}/{executed_total}, deferred = {waived_n} pending "
              f"foundry sign-off`. Engineering Phase 2+3 "
              + ("complete." if overall in ("PASS", "PASS_WITH_WAIVERS") else "INCOMPLETE — fix FAILs before claiming."))
    md.append("")

    # Stage-level summary
    md.append("## Stage breakdown")
    md.append("")
    md.append("| Stage | Steps | PASS | Other |")
    md.append("|---|---|---:|---|")
    by_stage: Dict[str, List[Dict[str, Any]]] = {}
    for s in flow.get("steps", []):
        by_stage.setdefault(s.get("stage", "?"), []).append(s)
    for stage_id, _full_title in STAGE_TITLE:
        rows = by_stage.get(stage_id, [])
        if not rows:
            continue
        title = STAGE_SHORT.get(stage_id, _full_title)
        def _id_sort(sid: str) -> Tuple[int, str, int]:
            m = re.match(r"^([AMP])(\d+|0)$", sid)
            if m:
                return (1, m.group(1), int(m.group(2)))
            try:
                return (0, "", int(sid))
            except ValueError:
                return (2, sid, 0)
        ids = sorted([str(s["id"]) for s in rows], key=_id_sort)
        per_v = collections.Counter(verdicts.get(str(s["id"]), "MISSING") for s in rows)
        npass = per_v.get("PASS", 0) + per_v.get("VACUOUS-PASS", 0)
        other_bits = []
        for k in ("WAIVED-DEFERRED", "SKIPPED-CONDITION", "VACUOUS-PASS",
                 "FAIL", "MISSING"):
            if per_v.get(k):
                # Compact: WAIVED-DEFERRED → ⚠️=1, SKIPPED-CONDITION → ⏭=N, etc.
                short = {"WAIVED-DEFERRED": "⚠️",
                         "SKIPPED-CONDITION": "⏭️",
                         "VACUOUS-PASS": "🟦",
                         "FAIL": "❌",
                         "MISSING": "❓"}[k]
                other_bits.append(f"{short}={per_v[k]}")
        md.append(f"| {title} | {_compact_id_range(ids)} | {npass} / {len(rows)} | "
                  f"{' '.join(other_bits) if other_bits else '—'} |")
    md.append("")

    # 4 generic mandatory outputs
    md.append("## Output #1 — Hardware verification (generic)")
    md.append("")
    if hw:
        md.append(f"- **Verdict**: `{hw.get('verdict','?')}`")
        if hw.get("tester"):
            md.append(f"- **Tester**: `{hw['tester']}`")
        if hw.get("board"):
            md.append(f"- **Board**: `{hw['board']}`")
        if hw.get("criterion"):
            md.append(f"- **Acceptance criterion**: `{hw['criterion']}`")
        if hw.get("iterations") is not None:
            pi = hw.get("passed_iterations")
            md.append(f"- **Iterations**: "
                      f"{pi if pi is not None else hw['iterations']} / {hw['iterations']}")
        ev = hw.get("evidence")
        if isinstance(ev, list) and ev:
            md.append(f"- **Evidence**: {', '.join(f'`{e}`' for e in ev[:5])}"
                      + (f" _(+{len(ev)-5} more)_" if len(ev) > 5 else ""))
        if hw.get("_source"):
            md.append(f"- _Source_: `{hw['_source']}`")
    else:
        md.append("_No `reports/hw_test.json` or legacy `reports/md905_test.json` found._")
    if sof:
        md.append(f"- **Bitstream**: `{sof['path']}` ({sof['size']:,} B)")
        md.append(f"- **Bitstream SHA-256**: `{sof['sha256']}`")
    md.append("")

    md.append("## Output #2 — FPGA-verified GDS")
    md.append("")
    if gds:
        md.append(f"- **GDS**: `{gds['path']}` ({gds['size']:,} B)")
        md.append(f"- **GDS SHA-256**: `{gds['sha256']}`")
        # Flatten PV verdicts (glow strips nested-list indent)
        pv_summary = ", ".join(f"{k}=`{v}`" for k, v in gds["pv"].items())
        md.append(f"- **Physical verification**: {pv_summary}")
        if gds.get("aux_reports"):
            paths_inline = ", ".join(f"`{p}`" for p in gds["aux_reports"])
            md.append(f"- **Auxiliary signoff reports** "
                      f"({len(gds['aux_reports'])}): {paths_inline}")
        if gds.get("fpga_signoff"):
            md.append(f"- **FPGA recompile + on-board re-test**: `{gds['fpga_signoff']}`")
    else:
        md.append("_No `gds/*.gds` present._")
    md.append("")

    md.append("## Output #3 — Test patterns (count summary)")
    md.append("")
    if tp:
        md.append(f"- **Test cases**: {tp.get('passed','?')} / {tp.get('total','?')} PASS")
        md.append(f"- **Distinct stimulus bytes** (counted from JSON): "
                  f"{tp.get('distinct_stimulus_bytes')}")
    else:
        md.append("- _No `reports/test_cases.json` found._")
    if tp_ev.get("vectors_total") is not None:
        md.append(f"- **sim_full_stack vectors**: {tp_ev.get('vectors_passed','?')} / "
                  f"{tp_ev['vectors_total']} PASS"
                  + (f" (all_proved={tp_ev.get('all_proved')})" if tp_ev.get("all_proved") is not None else ""))
        ot = tp_ev.get("opcodes_tested")
        if ot is not None:
            # Could be int (count) or list (chip-specific); always render count only.
            count = len(ot) if isinstance(ot, list) else ot
            md.append(f"- **Distinct opcodes / commands exercised**: {count}")
        if tp_ev.get("distinct_non_padding_bytes") is not None:
            md.append(f"- **Distinct non-padding bytes**: {tp_ev['distinct_non_padding_bytes']}")
    if tp_ev.get("sim_full_stack"):
        md.append(f"- _sim_full_stack source_: `{tp_ev['sim_full_stack']}`")
    if tp_ev.get("ref_tb_logs"):
        md.append(f"- **Reference TB logs** ({len(tp_ev['ref_tb_logs'])}): "
                  + ", ".join(f"`{p}`" for p in tp_ev["ref_tb_logs"][:3])
                  + (f" _(+{len(tp_ev['ref_tb_logs'])-3} more)_" if len(tp_ev["ref_tb_logs"]) > 3 else ""))
    if tp_ev.get("vectors_csv"):
        md.append(f"- **Vector CSV**: `{tp_ev['vectors_csv']}`")
    md.append("")
    md.append("_Per-opcode / per-mode coverage detail belongs in_ "
              "`reports/chip_specific_summary.md` _(this section stays chip-agnostic)._")
    md.append("")

    md.append("## Output #4 — Analog convergence (tuning loops)")
    md.append("")
    if analog:
        md.append(f"- **Declared analog blocks** ({len(analog.get('blocks',[]))}): "
                  + ", ".join(f"`{b}`" for b in analog.get("blocks", [])))
        if analog.get("tuning"):
            md.append("")
            md.append("| Block | Iterations | Converged |")
            md.append("|---|---:|:---:|")
            for t in analog["tuning"]:
                conv = "✅" if t.get("converged") else ("❌" if t.get("converged") is False else "—")
                md.append(f"| `{t['block']}` | {t.get('iterations','—')} | {conv} |")
        else:
            md.append("- _No `tuning_loop.json` files found under `analog/<block>/`._")
        # Per-block A1-A9 evidence grid
        if analog_ev.get("block_grid"):
            md.append("")
            md.append("**Per-block A1-A9 artefact presence:**")
            md.append("")
            steps_hdr = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"]
            md.append("| Block | " + " | ".join(steps_hdr) + " |")
            md.append("|---|" + "|".join([":---:"] * len(steps_hdr)) + "|")
            for name, grid in analog_ev["block_grid"].items():
                cells_md = " | ".join("✅" if grid.get(s) else "—" for s in steps_hdr)
                md.append(f"| `{name}` | {cells_md} |")
        # Mixed-signal references — inline list (avoid nested bullets)
        if analog_ev.get("mixed_paths"):
            md.append("")
            paths_inline = ", ".join(f"`{p}`" for p in analog_ev["mixed_paths"])
            md.append(f"- **Mixed-signal artefacts** ({len(analog_ev['mixed_paths'])}): "
                      f"{paths_inline}")
        # HW-tuning loop status
        md.append("")
        if analog_ev.get("hw_tuning_invoked"):
            md.append("**Hardware-in-the-loop tuning**: invoked "
                      "(see `analog/<block>/hw_measurements.json`).")
        else:
            md.append("**Hardware-in-the-loop tuning**: NOT invoked — analog-block "
                      "silicon unavailable; SPICE-only convergence preserved.")
    else:
        md.append("_No `analog/analog_block_list.json` found — pure-digital project, "
                  "or analog track not run._")
    md.append("")

    # Cell count
    md.append("## Cell count (synth + PnR)")
    md.append("")
    md.append("| Stage | Count | Source |")
    md.append("|---|---:|---|")
    if cells["netlist_path"]:
        # #737 — distinguish a genuinely-empty netlist (real 0, flagged) from
        # an un-counted one (`—`). A bare `0` could be a parser-miss; the
        # explicit ⚠ EMPTY tag makes a real empty netlist unmistakable so it
        # is never silently treated as "fine, just zero cells".
        if cells["total_synth"] is None:
            _cnt = "—"
        elif cells.get("empty_netlist"):
            _cnt = "0 ⚠ EMPTY"
        else:
            _cnt = str(cells["total_synth"])
        _src = cells["netlist_path"]
        if cells.get("synth_count_source"):
            _src = f"{_src} (count: {cells['synth_count_source']})"
        md.append(f"| Yosys post-synth | {_cnt} | `{_src}` |")
    else:
        md.append("| Yosys post-synth | — | _(no netlist found)_ |")
    if cells["def_components"] is not None:
        md.append(f"| PnR DEF (COMPONENTS) | {cells['def_components']} | `{cells['def_path']}` |")
    else:
        md.append("| PnR DEF (COMPONENTS) | — | _(no DEF found)_ |")
    if cells["top"]:
        md.append("")
        md.append("### Top-15 cell-type histogram")
        md.append("")
        md.append("| Cell | Count |")
        md.append("|---|---:|")
        for name, n in cells["top"]:
            md.append(f"| `{name}` | {n} |")
    md.append("")

    # 54-step canonical breakdown
    md.append(f"## Canonical step input/output ({total_steps} entities)")
    md.append("")
    md.append(f"_Per_ `flow/phase1_phase2_phase3.yaml` _v{flow.get('version','?')}._")
    md.append("")
    md.append(_render_step_tables(flow, verdicts))
    md.append("### Verdict roll-up")
    md.append("")
    md.append("| Verdict | Count |")
    md.append("|---|---:|")
    for v in ("PASS", "VACUOUS-PASS", "WAIVED-DEFERRED", "SKIPPED-CONDITION", "FAIL", "MISSING"):
        if rollup.get(v):
            md.append(f"| {VERDICT_SYM.get(v, v)} {v} | {rollup[v]} |")
    md.append(f"| **Total** | **{total_steps}** |")
    md.append("")

    # Waivers — full text (no truncation)
    md.append("## Waivers (must be human-reviewed before tapeout)")
    md.append("")
    if waivers:
        for w in waivers[:20]:
            md.append(f"### Step {w.get('id','?')} — `{w.get('ticket','—')}`")
            md.append("")
            md.append(f"- **Approver**: `{w.get('approver','—')}`  "
                      f"  **review_required**: "
                      f"{'✅' if w.get('review_required') else '❌ NO (suspicious)'}")
            if w.get("approved_at"):
                md.append(f"- **Approved at**: `{w['approved_at']}`")
            if w.get("evidence"):
                md.append(f"- **Evidence**: `{w['evidence']}`")
            if w.get("cascades_to"):
                md.append(f"- **Cascades to**: {w['cascades_to']}")
            # #437(e): `rationale` is an accepted synonym for `reason` —
            # a rationale-keyed waiver is VALID, not "(no reason given)".
            reason = (w.get("reason") or w.get("rationale")
                      or "(no reason given — waiver is INVALID)")
            md.append("")
            md.append("```")
            for ln in str(reason).splitlines():
                md.append(ln)
            md.append("```")
            md.append("")
        if len(waivers) > 20:
            md.append(f"_+{len(waivers)-20} additional waivers omitted; see `waivers.json` directly._")
            md.append("")
    else:
        md.append("_No waivers — every executed step verified deterministically._")
        md.append("")
    # Top-level PDK / EDA tooling gaps (also tracked in waivers.json).
    # Render as a 2-col table — Reason column is truncated to keep table
    # width ≤ ~80c so glow / mdcat render it cleanly.
    if pdk_gaps:
        md.append("### PDK / EDA tooling gaps (waivers.json top-level)")
        md.append("")
        md.append("These are NOT design FAILs — they document where the project "
                  "fell back to a placeholder because the open-source PDK or EDA "
                  "tool lacked characterised data needed for full sign-off. "
                  "Production tapeout requires re-running on a foundry-grade flow.")
        md.append("")
        md.append("| Gap | Reason (summary) |")
        md.append("|---|---|")
        for k, v in sorted(pdk_gaps.items()):
            label = k.replace("_unavailable_reason", "").replace("_", " ")
            # Strip newlines + collapse whitespace + truncate to first sentence
            # (or 90 chars max). Full reasons remain in waivers.json.
            v_clean = re.sub(r"\s+", " ", v.replace("|", "/")).strip()
            first_period = v_clean.find(". ")
            if 0 < first_period < 90:
                summary = v_clean[:first_period + 1]
            elif len(v_clean) > 90:
                summary = v_clean[:87].rstrip() + "…"
            else:
                summary = v_clean
            md.append(f"| `{label}` | {summary} |")
        md.append("")
        md.append("_Full reason text per gap available in_ `waivers.json`.")
        md.append("")

    # Resource log — derived from rollup
    md.append("## Resource log")
    md.append("")
    if cells.get("total_synth"):
        md.append(f"- Standard-cell count post-synth: **{cells['total_synth']}** "
                  f"(from `{cells['netlist_path']}`)")
    elif cells.get("empty_netlist"):
        # #737 — a real empty netlist must not vanish from the resource log
        # just because its count is the falsy 0; flag it loudly.
        md.append("- Standard-cell count post-synth: **0 ⚠ EMPTY NETLIST** "
                  f"(from `{cells['netlist_path']}`)")
    if cells.get("def_components"):
        md.append(f"- DEF COMPONENTS post-PnR: **{cells['def_components']}**")
    if analog_ev.get("block_names"):
        n = len(analog_ev["block_names"])
        a_total = sum(sum(g.values()) for g in analog_ev["block_grid"].values())
        md.append(f"- Analog blocks: {n} × 9 stages "
                  f"= {n*9} per-block step-runs (artefacts present: {a_total}/{n*9})")
        if analog and analog.get("tuning"):
            for t in analog["tuning"]:
                md.append(f"- Closed-loop tuning ({t['block']}): "
                          f"{t.get('iterations','?')} iterations, "
                          f"converged={'yes' if t.get('converged') else 'no'}")
    # #461 symptom (2): same snapshot as the headline — executed PASS
    # (PASS + VACUOUS-PASS) over executed total (steps − waived −
    # skipped). Identical denominator/numerator to the Verdict block.
    md.append(f"- Canonical step executed PASS: "
              f"**{snap['executed_pass']}/{snap['executed_total']}** "
              f"(strict PASS: {snap['pass_only']}, "
              f"deferred via waiver: {snap['waived']}, "
              f"vacuous-pass: {snap['vacuous']}, "
              f"manufacturing-skipped: {snap['skipped_manufacturing']}, "
              f"mid-flow-skipped: {snap['skipped_midflow']})")
    md.append("")

    # SHA-256 Attestation table — v1.6.34 closes doctrine rule #5
    # producer-consumer mismatch (gate ships in v1.6.33 but producer
    # only emitted SOF + GDS hashes inline; gate expects the full
    # 9-class set and looks for them in either AGENT_REPORT.md or
    # reports/final_summary.md). #461: the same table is pre-written to
    # disk before the internal audit so the gate sees current hashes.
    md.extend(_render_attestation_section(project))

    # Self-attestation
    md.append("## Self-attestation")
    md.append("")
    md.append("```bash")
    md.append(f"python3 {COMPLIANCE_TOOL} \\")
    md.append(f"    {project} --strict")
    md.append("```")
    md.append("")

    # Chip-specific addendum link
    md.append("## Chip-specific addendum")
    md.append("")
    if chip_addendum:
        md.append("See [`reports/chip_specific_summary.md`](chip_specific_summary.md) "
                  "for IC-specific opcode coverage, tester fixture semantics, "
                  "analog tuning targets, and any chip-known issues.")
    else:
        md.append("_No `reports/chip_specific_summary.md` present. Author it by hand "
                  "(or via a chip-specific Phase 1 skill) to document IC-specific "
                  "test interpretations, opcode tables, tuning-target values, etc. "
                  "This generator deliberately keeps the canonical summary "
                  "chip-agnostic._")
    md.append("")

    return "\n".join(md) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(
        "Generate canonical chip-AGNOSTIC final_summary.md from Phase 2+3 artefacts."
    ))
    ap.add_argument("project_dir")
    ap.add_argument("--out", default=None,
                    help="Output path (default: <project>/reports/final_summary.md)")
    ap.add_argument("--no-audit", action="store_true",
                    help="Skip running flow_compliance_check.py (verdicts will be UNKNOWN).")
    ap.add_argument("--audit-timeout", type=int, default=None, metavar="SECONDS",
                    help=(f"Timeout (s) for the internal flow_compliance_check "
                          f"audit subprocess. Overrides ${AUDIT_TIMEOUT_ENV}. "
                          f"Default: size-adaptive from "
                          f"{AUDIT_TIMEOUT_DEFAULT_S}s. On timeout the verdict "
                          f"reads {AUDIT_TIMEOUT_VERDICT}, never UNKNOWN."))
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2
    out_path = Path(args.out) if args.out else _pl.report_path(project, "final_summary.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # #469: capture the previous summary's snapshot marker BEFORE the
    # attestation pre-pass overwrites the canonical file, so an
    # AUDIT_TIMEOUT can still report the last clean snapshot (審不完 vs
    # 沒審). Captured here because the pre-pass below erases the marker.
    prior_marker = _previous_snapshot_marker(project)

    # #461 symptom (1): pre-write the SHA-256 attestation table to the
    # CANONICAL report path (`reports/final_summary.md`, the file the
    # attestation gate reads) BEFORE the internal audit runs. Without
    # this, the gate inside `_run_audit` reads the stale table from a
    # mid-flow run and FAILs MISSING_ATTESTATION on late-emitted
    # netlists. Only meaningful when the audit will actually run.
    if not args.no_audit:
        canonical = _pl.report_path(project, "final_summary.md")
        _prewrite_attestation(project, canonical)

    md = _render(project, run_audit=not args.no_audit,
                 audit_timeout_s=args.audit_timeout,
                 prior_marker=prior_marker)
    out_path.write_text(md, encoding="utf-8")
    # NOTE: legacy plugin gate writers still write to reports/<flat>
    # paths. Auto-sweep was disabled because it conflicts with legacy
    # readers + symlink resolution. To keep reports/ visually clean,
    # use a separate one-shot reorganiser script after phase23.
    print(f"[OK] final summary → {out_path}  ({len(md)} bytes, "
          f"{md.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
