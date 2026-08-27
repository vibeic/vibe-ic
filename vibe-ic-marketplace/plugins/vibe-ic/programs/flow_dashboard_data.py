#!/usr/bin/env python3
"""flow_dashboard_data.py — DATA PROVIDER for the live Vibe-IC flow dashboard.

This module is the single source of truth for a live execution dashboard that
renders the canonical Phase 1 / 2 / 3 flow (plus the Analog A1-A9, Mixed-Signal
M1-M4, and Manufacturing 40-44 tracks) for a given design project. A CLI and a
web renderer are built against the EXACT `collect()` JSON contract below — the
shape is intentionally stable; renderers depend on the enumerated keys verbatim.

It has two modes:

  * LIGHTWEIGHT (default) — FAST. Only file stat / glob against the project
    tree; no gate programs are run. Status is inferred from which
    `required_outputs` exist plus disclosed-skip sentinels.

  * FULL (`full=True`) — AUTHORITATIVE. Runs `flow_compliance_check.py` as a
    subprocess (the real gate matrix) and maps each step's compliance verdict
    to a dashboard status. Falls back to lightweight (with a `note`) if the
    compliance checker is missing or errors — it never crashes.

The canonical flow is `<plugin_root>/flow/phase1_phase2_phase3.yaml`. Every dict
in it with an `id` and (`name` or `required_outputs`) is a step; bare
container / grouping nodes (the stage wrappers) are skipped.

Usage (CLI / fixture generator):
    python3 flow_dashboard_data.py <project> [--full] [--json <out>]

Public API (the ONLY thing the renderers call):
    collect(project, full=False) -> dict
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Resolve the plugin root as the parent of the programs/ dir this module lives
# in, so the flow yaml is found regardless of the caller's cwd.
PROGRAMS_DIR = Path(__file__).resolve().parent
FLOW_YAML = PROGRAMS_DIR.parent / "flow" / "phase1_phase2_phase3.yaml"
# The vibe-ic plugin manifest — the header badge shows THIS version (the shipped
# plugin), not the flow-schema version. Parent of programs/ is the plugin root.
PLUGIN_JSON = PROGRAMS_DIR.parent / ".claude-plugin" / "plugin.json"


def _plugin_version() -> str:
    """Return the vibe-ic plugin `version` from .claude-plugin/plugin.json, or ""
    if unreadable. Never raises — the dashboard degrades to no badge."""
    try:
        doc = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        v = doc.get("version")
        return "" if v is None else str(v)
    except Exception:
        return ""

# Splitting a `required_outputs` entry into acceptable ALTERNATIVES
# (e.g. 'phase2/stage1/rtl/*.sv OR phase2/stage1/rtl/*.v').
_OR_RE = re.compile(r"\s+OR\s+")

# The canonical dashboard statuses (kept in sync with the contract).
#   partial = primary output present, some SECONDARY output absent, and no sign
#             of a live writer (stale mtime). Honest middle state between a
#             running build and a gated PASS — lightweight mode CANNOT claim a
#             gated verdict, so it says "partial" and defers to --full.
#   na       = a lane that does NOT apply to THIS design (e.g. the analog
#              A1-A9 / mixed-signal M1-M4 steps on a pure-digital block). It
#              will never run — not "not started yet". Matches --full's
#              SKIPPED-CONDITION, but names the reason at a glance.
#   external = an off-machine step outside the flow (manufacturing 40-44:
#              fab / wafer-sort / packaging / final-test / qual). Also never run
#              by us, but for a different reason than `na`.
_STATUSES = (
    "pass", "skipped", "waived", "fail", "missing",
    "running", "partial", "na", "external", "pending",
)

# Two orthogonal axes:
#   completion (DONE) — did the step reach a TERMINAL, JUDGED disposition? A
#                       step is DONE ("resolved") only if it ran to a verdict OR
#                       was decided not to run: pass / fail / skipped / waived /
#                       na / external. A *fail* is Done (it ran and was judged).
#   outcome           — WHAT that disposition was.
# NOT done ("unresolved"): running (in progress), pending (not reached), partial
# (started but outputs incomplete) and missing (the expected deliverable is
# absent — the step did not complete). `missing`/`partial` are deliberately NOT
# Done: a step whose output never materialized has not been "done", even though
# a --full compliance pass renders a definite MISSING verdict for it. (This is
# why running --full must not inflate Done: a MISSING gate verdict is a gap, not
# a completion.)
_RESOLVED = frozenset(
    {"pass", "skipped", "waived", "fail", "na", "external"}
)
_UNRESOLVED = frozenset({"running", "pending", "partial", "missing"})

# A present output touched within this many seconds is taken as evidence a
# writer is ACTIVELY producing this step right now -> "running". Older than
# this with outputs still incomplete -> "partial" (not live). Lightweight mode
# has no process handle, so mtime recency is the only honest liveness signal.
_RUNNING_WINDOW_S = 45.0

# Cap on how many resolved outputs are attached per step (display sanity).
_OUTPUTS_CAP = 6

# --- phase display definitions (order is load-bearing: renderers show 6 lanes)
_PHASES = [
    {"key": "phase1", "label": "Phase 1 · Spec → Design Docs", "icon": "\U0001f4dd"},
    {"key": "phase2", "label": "Phase 2 · RTL → Synthesis → Verify", "icon": "⚙️"},
    {"key": "phase3", "label": "Phase 3 · Place & Route → Sign-off", "icon": "\U0001f3d7️"},
    {"key": "analog", "label": "Analog · A1–A9", "icon": "\U0001f50a"},
    {"key": "mixed", "label": "Mixed-Signal · M1–M4", "icon": "\U0001f500"},
    {"key": "manufacturing", "label": "Manufacturing & Test · 40–44", "icon": "\U0001f3ed"},
]

_MFG_IDS = {"40", "41", "42", "43", "44"}


# --------------------------------------------------------------------------- #
# Flow parsing
# --------------------------------------------------------------------------- #
def _iter_steps(doc: Any) -> List[dict]:
    """Every dict with an `id` and (`name` or `required_outputs`) is a step.

    Same walk as flow_step_executor_coverage_check.py::_iter_steps."""
    out: List[dict] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if "id" in o and ("name" in o or "required_outputs" in o):
                out.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return out


def _is_bare_container(step: dict) -> bool:
    """A bare container / grouping node has NEITHER required_outputs NOR a gate
    NOR any executor (mcp_tools / programs / skills). Same "bare container" idea
    as flow_step_executor_coverage_check.py, adapted to also KEEP any node that
    carries a `stage` (e.g. the P0 umbrella has stage='stage1' but no outputs —
    it is a real step, not a grouping wrapper). The 8 stage wrappers in the
    canonical yaml carry no `stage` field of their own (their id IS the stage),
    so this drops exactly those and keeps every real leaf step."""
    return (
        not step.get("stage")
        and not step.get("required_outputs")
        and not step.get("gate")
        and not step.get("mcp_tools")
        and not step.get("programs")
        and not step.get("skills")
    )


def _load_flow(flow_yaml: Path = FLOW_YAML) -> Tuple[dict, List[dict]]:
    """Return (top_level_doc, [real step dicts in yaml order])."""
    import yaml  # available — flow_compliance_check.py uses it

    doc = yaml.safe_load(flow_yaml.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        doc = {}
    steps = [s for s in _iter_steps(doc) if not _is_bare_container(s)]
    return doc, steps


_ID_A_RE = re.compile(r"^A\d+$")
_ID_M_RE = re.compile(r"^M\d+$")


def _phase_key_for(step: dict) -> str:
    """Map a step to exactly one display-phase key, evaluated in phase order so
    the first matching lane wins (e.g. id '39' is stage4 but the phase2 rule
    claims it first for FPGA on-board bring-up). Fallback lane is phase2."""
    sid = str(step.get("id"))
    stage = str(step.get("stage") or "")
    # 1) phase1
    if sid in ("P0", "D1") or stage == "phase1":
        return "phase1"
    # 2) phase2 — RTL/synth/verify + FPGA on-board bring-up (39)
    if stage in ("stage1", "stage2") or sid == "39":
        return "phase2"
    # 3) phase3 — place & route / sign-off
    if stage in ("stage3", "stage4"):
        return "phase3"
    # 4) analog
    if _ID_A_RE.match(sid) or stage == "stage_analog":
        return "analog"
    # 5) mixed-signal
    if _ID_M_RE.match(sid) or stage == "stage_mixed_signal":
        return "mixed"
    # 6) manufacturing & test
    if stage == "stage5_manufacturing" or sid in _MFG_IDS:
        return "manufacturing"
    # safe fallback
    return "phase2"


# --------------------------------------------------------------------------- #
# Gate one-line summary
# --------------------------------------------------------------------------- #
def _gate_summary(gate: Any) -> str:
    """Collapse a step's `gate` predicate dict into a compact one-liner."""
    if not gate:
        return ""
    if isinstance(gate, str):
        return gate[:140]
    if not isinstance(gate, dict):
        return str(gate)[:140]
    parts: List[str] = []
    for k, v in gate.items():
        if k == "program_exit_zero":
            tok = str(v).split()[0] if str(v).split() else str(v)
            parts.append(f"exit0:{tok}")
        elif k == "files_exist":
            pats = v if isinstance(v, list) else [v]
            parts.append("files:" + ",".join(str(p) for p in pats[:3]))
        elif k == "json_field_true":
            if isinstance(v, dict):
                parts.append(
                    f"json:{v.get('file', '?')}.{v.get('field', '?')}=={v.get('expect')}"
                )
            else:
                parts.append("json_field_true")
        elif k in ("all_of", "any_of"):
            if isinstance(v, list):
                parts.append(f"{k}({len(v)})")
            elif isinstance(v, bool):
                # 'any_of: True' is a modifier flag alongside files_exist
                continue
            else:
                parts.append(k)
        else:
            parts.append(str(k))
    return " ; ".join(parts)[:180]


def _gate_program_tokens(gate: Any) -> List[str]:
    """Program-name tokens referenced by a gate's program_exit_zero clauses."""
    toks: List[str] = []

    def scan(g: Any) -> None:
        if isinstance(g, dict):
            for k, v in g.items():
                if k == "program_exit_zero":
                    s = str(v).split()
                    if s:
                        toks.append(s[0])
                else:
                    scan(v)
        elif isinstance(g, list):
            for x in g:
                scan(x)

    scan(gate)
    return toks


# --------------------------------------------------------------------------- #
# Output resolution
# --------------------------------------------------------------------------- #
def _split_alts(spec: str) -> List[str]:
    return [a.strip() for a in _OR_RE.split(str(spec).strip()) if a.strip()]


def _glob_existing(project: Path, pattern: str) -> List[Path]:
    """Existing paths under `project` matching `pattern` (a relative glob or a
    literal path). Sorted for determinism; tolerant of bad patterns."""
    pattern = pattern.strip().lstrip("/")
    if not pattern:
        return []
    try:
        if "*" in pattern or "?" in pattern or "[" in pattern:
            return sorted(p for p in project.glob(pattern) if p.exists())
        p = project / pattern
        return [p] if p.exists() else []
    except (OSError, ValueError):
        return []


def _resolve_spec(project: Path, spec: str) -> Tuple[bool, Dict[str, Any]]:
    """Resolve one `required_outputs` spec (which may list OR-alternatives).

    Returns (present, entry). `present` is True if ANY alternative resolves to
    at least one existing path. `entry` prefers a real existing match; otherwise
    it is the FIRST literal alternative with exists=False so the UI can show the
    EXPECTED location before it is produced."""
    alts = _split_alts(spec)
    for alt in alts:
        matches = _glob_existing(project, alt)
        if matches:
            m = matches[0]
            try:
                st = m.stat()
                size, mtime = int(st.st_size), float(st.st_mtime)
            except OSError:
                size, mtime = 0, 0
            rel = os.path.relpath(str(m), str(project))
            return True, {
                "rel": rel,
                "abs": str(m),
                "exists": True,
                "size": size,
                "mtime": mtime,
            }
    first = alts[0] if alts else str(spec).strip()
    return False, {
        "rel": first,
        "abs": str(project / first.lstrip("/")),
        "exists": False,
        "size": 0,
        "mtime": 0,
    }


def _resolve_outputs(
    project: Path, required_outputs: Any
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Resolve every output-spec. Returns (entries_capped, n_present, n_total).

    One entry per output-spec; the full present/total counts drive status even
    though only the first `_OUTPUTS_CAP` entries are attached for display."""
    entries: List[Dict[str, Any]] = []
    n_present = 0
    specs = required_outputs or []
    for spec in specs:
        present, entry = _resolve_spec(project, spec)
        if present:
            n_present += 1
        entries.append(entry)
    return entries[:_OUTPUTS_CAP], n_present, len(specs)


# --------------------------------------------------------------------------- #
# Disclosed-skip detection (lightweight)
# --------------------------------------------------------------------------- #
def _output_dirs(required_outputs: Any) -> List[str]:
    """Directory portions of the required_outputs (up to the first glob comp)."""
    dirs: List[str] = []
    seen = set()
    for spec in required_outputs or []:
        for alt in _split_alts(spec):
            parts = [p for p in alt.split("/") if p]
            dir_parts: List[str] = []
            for p in parts[:-1]:  # drop the filename component
                if "*" in p or "?" in p or "[" in p:
                    break
                dir_parts.append(p)
            if dir_parts:
                d = "/".join(dir_parts)
                if d not in seen:
                    seen.add(d)
                    dirs.append(d)
    return dirs


_SKIP_VERDICTS = {"SKIP", "SKIPPED", "SKIPPED-CONDITION"}


def _disclosed_skip(project: Path, required_outputs: Any) -> Tuple[bool, str]:
    """A step is a DISCLOSED-SKIP if any *.json in its output dirs self-reports a
    top-level `verdict` in {SKIP, SKIPPED, SKIPPED-CONDITION} (case-insensitive,
    `_` treated as `-`), or a sentinel file `*_not_run.json` / `*_skipped*.json`
    exists there. Returns (is_skip, short_reason)."""
    for d in _output_dirs(required_outputs):
        dp = project / d
        if not dp.is_dir():
            continue
        try:
            jfiles = sorted(dp.glob("*.json"))
        except OSError:
            continue
        for jf in jfiles:
            name = jf.name.lower()
            if fnmatch.fnmatch(name, "*_not_run.json") or fnmatch.fnmatch(
                name, "*_skipped*.json"
            ):
                return True, f"{d}/{jf.name}"
            try:
                data = json.loads(jf.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                vd = str(data.get("verdict", "")).upper().replace("_", "-")
                if vd in _SKIP_VERDICTS:
                    return True, f"{d}/{jf.name}: verdict={vd}"
    return False, ""


def _umbrella_reports_exist(project: Path, step: dict) -> bool:
    """For a step with NO required_outputs (an umbrella like P0): True if any of
    its gate `programs` have written a report under reports/. Bounded — only
    scans when the step actually declares program tokens."""
    reports = project / "reports"
    if not reports.is_dir():
        return False
    toks = set()
    for p in step.get("programs") or []:
        t = str(p).split()[0] if str(p).split() else ""
        if t:
            toks.add(t.lower())
    for t in _gate_program_tokens(step.get("gate")):
        if t:
            toks.add(t.lower())
    if not toks:
        return False
    try:
        for jf in reports.rglob("*.json"):
            stem = jf.stem.lower()
            if any(t in stem for t in toks):
                return True
    except OSError:
        return False
    return False


# --------------------------------------------------------------------------- #
# Status logic
# --------------------------------------------------------------------------- #
def _lightweight_status(
    project: Path, step: dict, n_present: int, n_total: int,
    primary_present: bool = False, newest_mtime: float = 0.0,
    live: bool = True,
) -> Tuple[str, str]:
    """FAST status from file existence only. Returns (status, detail).

    `primary_present` = the step's FIRST required-output spec resolved to a real
    file. It gates the disclosed-skip: output DIRECTORIES are shared between
    steps (e.g. phase2/stage2/synth/ holds BOTH step-9 netlist.v and step-12's
    post_dft_not_run.json sentinel), so a skip-sentinel in the dir must NOT mark
    a step skipped when that step's own primary product already exists — the
    sentinel belongs to a different, later step in the same directory.

    `newest_mtime` = the most recent mtime among this step's PRESENT outputs.
    It separates a genuinely live "running" step (a writer touched an output in
    the last `_RUNNING_WINDOW_S`) from a finished step whose primary product
    exists but a SECONDARY report is absent ("partial"). Lightweight mode has no
    process handle, so we must NOT assert "running" from partial file counts
    alone — that mislabels every completed step with an optional missing report
    as forever-running (the exact spm 26/59 display bug).

    `live` = this call is answering "what is true RIGHT NOW", and its answer
    will be re-asked. Only such a call may return "running", because "running"
    is a claim about the instant it was made and about nothing else. A caller
    that PERSISTS the answer into a file (step_output_collector ->
    steps/index.json) passes live=False: a durable record is by construction
    read later than it was written, so a frozen "running" there can never be
    re-evaluated and says "still working" forever -- indistinguishable from a
    step that IS still working, which is the one distinction a reader needs.
    With live=False the same evidence yields the mtime-free answer this
    classifier already has for a non-live writer ("partial", naming how many
    outputs landed), which states a FINISHED observation instead of an
    unfinishable one. It is NOT a reinterpretation of "running" as "done":
    a step that produced nothing records "pending" and a step that produced
    part of its contract records "partial"; neither can become "pass"."""
    if n_total == 0:
        # umbrella / container-ish step with no outputs to judge cheaply
        if _umbrella_reports_exist(project, step):
            return "pass", ""
        return "pending", ""
    dskip, dreason = _disclosed_skip(project, step.get("required_outputs"))
    if dskip and not primary_present and n_present < n_total:
        return "skipped", dreason
    if n_present == n_total:
        return "pass", ""
    if n_present > 0:
        # Some outputs present, not all. Only call it "running" if a writer
        # touched an output very recently; otherwise it RAN and a secondary
        # artifact is absent -> honest "partial" (run --full for the verdict).
        live_now = (live and newest_mtime > 0.0
                    and (time.time() - newest_mtime) <= _RUNNING_WINDOW_S)
        missing = n_total - n_present
        if live_now:
            return "running", f"{n_present}/{n_total} outputs · writing"
        return "partial", f"{n_present}/{n_total} outputs · {missing} secondary absent"
    return "pending", ""


# Statuses a given mode's classifier CANNOT emit, so their count is structurally
# 0 and must never be rendered as if it were a measurement. `_lightweight_status`
# decides purely on output-file presence and has no branch returning "fail" or
# "missing"; printing "fail 0" from it states a verdict the mode never computed.
#
# `fail` is CONDITIONAL for lightweight since `_runner_verdict_overrides` was
# wired in, and `collect` resolves it per project: with no runner verdict to
# join, lightweight still has no branch that can say "fail" and its 0 is not a
# measurement; with at least one joined, the count is real and printing "n/a"
# over a genuine failure would be the same defect pointing the other way. See
# the `summary_unavailable` assembly in `collect`.
_UNEXPRESSIBLE = {
    "lightweight": frozenset({"fail", "missing"}),
    "full": frozenset(),
}


# --------------------------------------------------------------------------- #
# THE RUNNER'S OWN VERDICT, JOINED ONTO THE FLOW STEP IT RAN
# --------------------------------------------------------------------------- #
# A step's status was derived here from output-file EXISTENCE alone, while the
# process that actually executed the step recorded its verdict in
# reports/orchestrator/<phase>_one_shot.json under a runner-internal name. The
# two records then described the same step and disagreed: measured on a
# 3-problem VerilogEval-Human run, `yosys_synth` returned FAIL (rc=0 from yosys
# but synth_netlist_check rejected a 0-cell netlist) AFTER it had already
# written both artefacts step 9 declares -- so existence said "pass" and the
# runner said FAIL, and steps/index.json (what a dashboard, a human and any
# per-step tally read) published the pass.
#
# THE MAPPING IS NOT INVENTED HERE. `step_preflight.RUNNER_PLANS` already
# declares, per runner, the ORDERED dispatch sites and the flow step ids each
# site executes -- ("yosys_synth", ("9",)) among them. It is the runner's own
# plan, read off its main() and machine-checked against the flow, and it is
# what makes this join a lookup rather than a guess. (The comment in
# `_orchestrator_failures` below used to say no such mapping existed in this
# repo; it did, one module away.)
#
# THREE DELIBERATE LIMITS, each of which makes a wrong attribution impossible
# rather than unlikely:
#   1. SINGLE-STEP SITES ONLY. A site whose span is several ids (`pnr` covers
#      15-22) failed SOMEWHERE in that span and the record cannot say where;
#      painting one verdict across eight rows sends the reader somewhere
#      specific and wrong. Those spans stay unattributed, exactly as before.
#   2. NAME IDENTITY IS REQUIRED, NOT ASSUMED. A site participates only if its
#      name appears verbatim as a `steps[].name` in that runner's report. The
#      analog runner's sites are named "A1".."A9" while its StepResults are
#      "A1_spec_extract".., so nothing of its is joined -- self-limiting, with
#      no allowlist to keep in sync.
#   3. FAILURE VERDICTS ONLY, and only the site's FINAL one. A runner PASS does
#      not license this record to claim pass when the artefacts are absent, so
#      the asymmetry is fail-closed: the executing process is the only witness
#      that a step FAILED, while file existence remains the honest witness that
#      it delivered. "Final" matters -- the RTL repair/retry loop re-dispatches `rtl_gen`,
#      whose records read BLOCKED then PASS, and only the last one is the run's
#      answer for step 1.
# Reports are folded in flow order, so a later phase re-running the same step
# (phase 3's `synth` is step 9 too) supersedes the earlier phase's verdict.

# Report file -> the RunnerPlan whose site names its `steps[]` uses. ORDERED by
# flow progression: a later entry supersedes an earlier one for the same step.
_ORCHESTRATOR_REPORT_RUNNERS: Tuple[Tuple[str, str], ...] = (
    ("phase2_one_shot.json", "design_one_shot_runner"),
    ("analog_one_shot.json", "analog_one_shot_runner"),
    ("phase3_one_shot.json", "phase3_one_shot_runner"),
)


def _is_failure_verdict(raw: str) -> bool:
    """A runner status that means the step did NOT succeed.

    Covers the FAIL tiers (FAIL, FAIL_RTL_REPAIR_INERT, ...) and the pre-flight
    refusal word BLOCKED, which `step_preflight` documents as "never green"
    and both runners' `_aggregate_verdict` already group with FAIL."""
    up = str(raw or "").upper()
    return "FAIL" in up or up == "BLOCKED"


def _runner_verdict_overrides(project: Path) -> Dict[str, dict]:
    """Flow step id -> the runner's OWN failure verdict for that step.

    Empty when nothing is joinable (no report, no plan, no name match). Never
    raises: a status pipeline that crashes on a malformed report is worse than
    one that declines to join."""
    out: Dict[str, dict] = {}
    try:
        import step_preflight as _spf
    except Exception:                                    # noqa: BLE001
        return out
    odir = project / "reports" / "orchestrator"
    for fname, runner in _ORCHESTRATOR_REPORT_RUNNERS:
        plan = getattr(_spf, "RUNNER_PLANS", {}).get(runner)
        if plan is None:
            continue
        # Site name -> the ONE flow step it executes (limit 1 above).
        solo = {site: ids[0] for site, ids in plan.sites if len(ids) == 1}
        if not solo:
            continue
        try:
            doc = json.loads((odir / fname).read_text(
                encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        # Each site's FINAL record in this report (limit 3 above).
        final: Dict[str, dict] = {}
        for st in doc.get("steps") or []:
            if not isinstance(st, dict):
                continue
            name = str(st.get("name") or "")
            if name in solo:                              # limit 2 above
                final[name] = st
        # WITHIN one report, two sites can execute the SAME flow step -- phase
        # 3 splits step 31 (DRC + LVS + ERC + Density) across `drc` and `lvs`.
        # Those are contemporaneous dispatches of one step, so ANY of them
        # failing means the step failed; folding them by iteration order would
        # let a passing `drc` erase a failing `lvs` purely because of where it
        # sits in the list. MEASURED on a published tree: drc PASS + lvs FAIL,
        # where step 31 stood recorded as `pass`.
        this_report: Dict[str, Optional[dict]] = {}
        for name, st in final.items():
            sid = solo[name]
            raw = str(st.get("status") or "")
            if not _is_failure_verdict(raw):
                this_report.setdefault(sid, None)
                continue
            this_report[sid] = {
                "status": "fail",
                "detail": (f"{runner}:{name} {raw}"
                           + (f" - {st.get('detail')}" if st.get("detail")
                              else "")),
                "source": f"reports/orchestrator/{fname}",
                "runner_step": name,
                "runner_status": raw,
            }
        # ACROSS reports the later phase supersedes, in both directions: a
        # phase-3 `synth` that PASSes clears a phase-2 `yosys_synth` failure
        # for the same step 9, and vice versa.
        for sid, rec in this_report.items():
            if rec is None:
                out.pop(sid, None)
            else:
                out[sid] = rec
    return out


def _orchestrator_failures(project: Path) -> List[dict]:
    """Failing step records quoted VERBATIM from reports/orchestrator/*.json.

    These are the runner's OWN authoritative per-step verdicts, reported as a
    flat list so a reader sees every one of them, including the ones that
    cannot be attributed to a single flow row.

    ATTRIBUTION now happens in `_runner_verdict_overrides` above, through
    `step_preflight.RUNNER_PLANS` -- the runner's own declared dispatch plan.
    This docstring used to state that no mapping between the two vocabularies
    existed in this repo and that inventing one would paint a FAIL onto the
    wrong row; the first half was false (the plan is one module away) and the
    second half is answered by that function's three limits, which keep the
    join to sites that execute exactly one flow step and whose name the report
    actually carries. Spans that cannot be attributed still appear ONLY here,
    unattributed, which is what this list is for.

    `status` is preserved exactly as written (FAIL, FAIL_RTL_REPAIR_INERT, ...); it is
    matched case-insensitively but never normalised, because the distinct tiers
    carry distinct remediation.
    """
    out: List[dict] = []
    odir = project / "reports" / "orchestrator"
    try:
        files = sorted(p for p in odir.glob("*.json") if p.is_file())
    except OSError:
        return out
    for jf in files:
        try:
            doc = json.loads(jf.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        for st in doc.get("steps") or []:
            if not isinstance(st, dict):
                continue
            raw = str(st.get("status") or "")
            if "FAIL" not in raw.upper():
                continue
            out.append({
                "source": jf.name,
                "name": str(st.get("name") or ""),
                "status": raw,
                "detail": str(st.get("detail") or ""),
            })
    return out


def _map_compliance_status(raw_status: str) -> str:
    """Map a flow_compliance_check verdict to a dashboard status."""
    raw = str(raw_status or "").upper().replace("_", "-")
    if raw in ("PASS", "VACUOUS-PASS"):
        return "pass"
    if raw in (
        "SKIPPED-CONDITION",
        "SKIPPED",
        "SKIP",
        "DEFERRED-BY-UPSTREAM",
        "DEFERRED",
        "CONDITIONAL-SKIP",
    ):
        return "skipped"
    if raw in ("WAIVED", "WAIVED-DEFERRED"):
        return "waived"
    if raw == "FAIL":
        return "fail"
    if raw == "MISSING":
        return "missing"
    # robustness beyond the enumerated set: obvious pass/waiver tiers
    # (PASS_WITH_WAIVERS, WAIVED-*) still resolve to a valid status.
    if raw.startswith("PASS"):
        return "pass"
    if raw.startswith("WAIVED"):
        return "waived"
    return "pending"


def _run_compliance(project: Path) -> Optional[List[dict]]:
    """Run flow_compliance_check.py --json and return its steps[] (or None on
    any failure — the caller then falls back to lightweight). A non-zero exit is
    EXPECTED (the checker exits 1 on any FAIL/MISSING) and tolerated."""
    import subprocess

    fc = PROGRAMS_DIR / "flow_compliance_check.py"
    if not fc.is_file():
        return None
    # Write the compliance --json IN-TREE (under the project), not /tmp: the
    # phase23_completion_audit records this path, and P0's
    # project_outputs_in_tree_check flags any recorded artifact living at a
    # VOLATILE path (/tmp/…) — so a /tmp temp here would inject a phantom P0
    # FAIL about the dashboard's own scratch file. An in-tree path is never
    # flagged. Kept under reports/ (created if needed) and removed afterwards.
    out_dir = project / "reports"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        out_dir = project
    out_json = out_dir / ".dashboard_compliance.json"
    try:
        subprocess.run(
            [sys.executable, str(fc), str(project), "--json", str(out_json)],
            timeout=600,
            capture_output=True,
        )
        data = json.loads(out_json.read_text(encoding="utf-8"))
        steps = data.get("steps")
        return steps if isinstance(steps, list) else None
    except Exception:
        return None
    finally:
        try:
            out_json.unlink()
        except OSError:
            pass


def _compliance_detail(comp_step: dict) -> str:
    reasons = comp_step.get("reasons") or []
    if reasons:
        return str(reasons[0])[:200]
    return ""


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def _lane_applicability(project: Path) -> Tuple[bool, bool]:
    """(analog_applicable, silicon_received) — cheap project-level signals that
    MIRROR the flow's own step conditions, so lightweight agrees with --full.
    Analog A1-A9 + mixed M1-M4 apply when the design declared analog blocks;
    manufacturing 40-44 only once silicon is physically back
    (`phase3/stage5_manufacturing/silicon_received.json`). When neither holds
    those lanes are honestly `na` / `external`, not a misleading `pending`.

    The analog block list is probed at BOTH canonical locations. The flow yaml
    conditions on `phase1/analog/analog_block_list.json`, but the only two
    producers — `phase1_doc_one_shot_runner` (L5_ADI_SPEC emit) and
    `analog_one_shot_runner` — write it through `_path_layout.analog_dir()`,
    i.e. `phase3/analog/analog_block_list.json`; the phase1 spelling is
    reachable only via `migrate_to_layout_p` on a legacy project-root tree.
    `flow_compliance_check._glob_first` hides this with a phase{1,2,3}/analog →
    canonical remap, but this module does raw `Path.exists()`, so on a REAL
    analog run it read `False` and marked the whole Analog + Mixed-Signal
    lanes "na — design declares no analog blocks". That is a false
    not-applicable on the load-bearing lane, and it made lightweight DISAGREE
    with --full, which is exactly what this helper exists to prevent.

    PRESENCE OF THE FILE IS NOT DECLARATION OF ANALOG WORK. Widening the probe
    on `Path.exists()` alone would install the MIRROR IMAGE of the defect it
    fixes: measured over the 17 tracked projects in this repo that carry an
    `analog_block_list.json`, all 17 move `False -> True`, and 8 of them
    (`ethernet`, `i2c`, `jesd204`, `lin`, `spdif`, `usb`, `ic/sha256`,
    `ic/subservient`) satisfy `_analog_a_check_common.analog_class_is_na` —
    their only "analog block" is a `low_confidence: true` keyword phantom
    (i2c's `dac` / `oscillator` come from a PDF abbreviation table's
    "Analog-to-Digital"). A pure-digital design's dashboard would flip the
    whole Analog A1-A9 + Mixed-Signal M1-M4 lane from `na` to applicable — a
    FALSE applicable, exactly symmetric to the false not-applicable above.

    So the ORGANIC #676 predicate that already governs the analog P0 gates is
    consulted here too, and this module is made to agree with them rather than
    invent a second answer. It can only ever move `True -> False`: an import or
    read failure degrades to the plain `.exists()` behaviour above, never to a
    fail-open `True`."""
    analog = (
        (project / "phase3" / "analog" / "analog_block_list.json").exists()
        or (project / "phase1" / "analog" / "analog_block_list.json").exists()
    )
    if analog:
        try:
            import _analog_a_check_common as _aac
            if _aac.analog_class_is_na(project):
                analog = False
        except Exception:
            pass          # degrade to the presence-only answer; never fail open
    silicon = (project / "phase3" / "stage5_manufacturing"
               / "silicon_received.json").exists()
    return analog, silicon


def _p0_preflight_passed(project: Path) -> bool:
    """P0 (structural-RTL pre-flight umbrella) has NO output artifact of its own,
    so lightweight cannot observe it directly. It gates RTL entry to the flow and
    synthesis runs strictly AFTER it — so a produced synth netlist is proof the
    pre-flight ran and passed. Deterministic, no false-positive (there is no
    netlist without a passed pre-flight)."""
    synth = project / "phase2" / "stage2" / "synth"
    return synth.is_dir() and any(synth.glob("*.v"))


def _reclassify_inapplicable_lane(sid, step, status, detail, project_path,
                                  analog_applicable, silicon_received):
    """Reclassify a "no real work" status for a lane that does NOT apply to THIS
    design. Lane applicability is a property of the design, NOT of which mode
    observed it — so this MUST run in both lightweight and --full mode, and the
    two modes must AGREE. Without it, --full marks the analog A1-A9 / mixed
    M1-M4 lanes of a pure-digital chip as MISSING (a false gap) and the
    off-machine manufacturing 40-44 lanes as SKIPPED, where lightweight
    correctly calls them `na` / `external`. A real pass/fail/waive stands."""
    pk = _phase_key_for(step)
    # P0 (structural pre-flight umbrella) has no artifact of its own: a produced
    # synth netlist proves it ran and passed.
    if sid == "P0" and status == "pending" and _p0_preflight_passed(project_path):
        return "pass", "structural pre-flight passed (flow reached synthesis)"
    # For a non-applicable lane, ANY "nothing meaningful happened" verdict
    # (pending / missing / a disclosed skip) is more honestly named na/external.
    _NO_WORK = ("pending", "missing", "skipped")
    if status not in _NO_WORK:
        return status, detail
    if pk in ("analog", "mixed") and not analog_applicable:
        return "na", ("not applicable — design declares no analog / "
                      "mixed-signal content")
    if pk == "manufacturing" and not silicon_received:
        return "external", ("external — off-machine (fab / wafer-sort / "
                            "packaging / final-test / qual)")
    return status, detail


def _unavailable_statuses(mode: str, verdicts: Dict[str, dict]) -> set:
    """Statuses whose 0 in this collect is structural rather than measured.

    Lightweight's `fail` leaves the set exactly when a runner verdict was
    attributable to a flow step: at that point the mode CAN say fail, so the
    count is a real one. With nothing joined it stays in, because a 0 that only
    means "this classifier has no fail branch" must not be read as "nothing
    failed" -- the defect this set was introduced to remove."""
    out = set(_UNEXPRESSIBLE.get(mode, frozenset()))
    if verdicts:
        out.discard("fail")
    return out


def collect(project, full: bool = False, live: bool = True) -> dict:
    """Collect the live dashboard data for `project`.

    `project` may be a str or Path. `full=True` runs the authoritative
    compliance gate matrix; the default is the fast file-stat-only lightweight
    mode. Never raises: any failure in full mode falls back to lightweight.

    `live=False` says the caller is going to PERSIST this answer (see
    `_lightweight_status`), so no step may be classified "running" -- a stored
    record is read later than it was written and cannot re-evaluate liveness.
    Default True keeps the polling dashboard's behaviour unchanged."""
    project_path = Path(project).expanduser().resolve()

    doc, steps = _load_flow()

    fv = doc.get("flow_version")
    if fv is None:
        fv = doc.get("version")
    flow_version = "" if fv is None else str(fv)

    # In full mode, run the compliance gate matrix once and index by str(id).
    comp_by_id: Dict[str, dict] = {}
    note = ""
    mode = "lightweight"
    if full:
        comp_steps = _run_compliance(project_path)
        if comp_steps is None:
            note = (
                "full mode requested but flow_compliance_check.py was "
                "unavailable or errored; fell back to lightweight file-stat mode"
            )
        else:
            mode = "full"
            for cs in comp_steps:
                if isinstance(cs, dict) and "id" in cs:
                    comp_by_id[str(cs["id"])] = cs

    # Build per-phase step lists (all 6 lanes always emitted, in order).
    phase_steps: Dict[str, List[dict]] = {p["key"]: [] for p in _PHASES}

    # Cheap project-level lane applicability (lightweight-only refinement).
    analog_applicable, silicon_received = _lane_applicability(project_path)

    # The runner's own failure verdicts, keyed by flow step id. Read ONCE.
    verdicts = _runner_verdict_overrides(project_path)

    for step in steps:
        sid = str(step.get("id"))
        outputs, n_present, n_total = _resolve_outputs(
            project_path, step.get("required_outputs")
        )

        if mode == "full" and sid in comp_by_id:
            comp = comp_by_id[sid]
            status = _map_compliance_status(comp.get("status"))
            detail = _compliance_detail(comp)
        else:
            primary_present = bool(outputs) and bool(outputs[0].get("exists"))
            newest_mtime = max(
                (float(o.get("mtime") or 0.0) for o in outputs if o.get("exists")),
                default=0.0,
            )
            status, detail = _lightweight_status(
                project_path, step, n_present, n_total, primary_present,
                newest_mtime, live=live,
            )
        # Honesty refinement (BOTH modes): a `pending`/`missing` for a lane that
        # will NEVER run for THIS design is misleading — name the reason at a
        # glance (na / external) instead of a false gap.
        status, detail = _reclassify_inapplicable_lane(
            sid, step, status, detail, project_path,
            analog_applicable, silicon_received,
        )

        # LAST, and it WINS. The process that executed the step is the only
        # witness that it failed; every classifier above this line reasons from
        # artefacts, and this step's artefacts were written BEFORE its verdict
        # was reached. Applying the join last is what makes it impossible for
        # steps/index.json to publish "pass" over the runner's own FAIL.
        vd = verdicts.get(sid)
        if vd is not None:
            status = vd["status"]
            detail = vd["detail"]

        blocks_on = step.get("blocks_on")
        if not isinstance(blocks_on, list):
            blocks_on = [] if blocks_on is None else [blocks_on]

        step_obj = {
            "id": sid,
            "name": str(step.get("name") or ""),
            "stage": str(step.get("stage") or ""),
            "status": status,
            "status_label": status.upper(),
            "blocks_on": blocks_on,
            "gate": _gate_summary(step.get("gate")),
            "detail": detail or "",
            "outputs": outputs,
        }
        phase_steps[_phase_key_for(step)].append(step_obj)

    # Assemble phases + summary.
    #   resolved (DONE) = reached AND judged = every status except running/pending.
    #   passed          = the subset whose verdict was a clean PASS.
    summary = {"total": 0}
    for s in _STATUSES:
        summary[s] = 0
    summary["resolved"] = 0
    summary["passed"] = 0

    phases_out: List[dict] = []
    for p in _PHASES:
        plist = phase_steps[p["key"]]
        resolved = sum(1 for st in plist if st["status"] in _RESOLVED)
        passed = sum(1 for st in plist if st["status"] == "pass")
        for st in plist:
            summary["total"] += 1
            summary[st["status"]] += 1
        summary["resolved"] += resolved
        summary["passed"] += passed
        phases_out.append(
            {
                "key": p["key"],
                "label": p["label"],
                "icon": p["icon"],
                "resolved": resolved,   # DONE = judged (any verdict)
                "passed": passed,       # the PASS subset
                "done": resolved,       # back-compat alias (= resolved)
                "total": len(plist),
                "steps": plist,
            }
        )

    return {
        "project": str(project_path),
        "project_name": project_path.name,
        "mode": mode,
        "flow_version": flow_version,
        "plugin_version": _plugin_version(),
        "note": note,
        "summary": summary,
        "summary_unavailable": sorted(_unavailable_statuses(mode, verdicts)),
        "orchestrator_failures": _orchestrator_failures(project_path),
        "phases": phases_out,
    }


# --------------------------------------------------------------------------- #
# CARD FINGERPRINT — an on-demand full run stays pinned until the tree changes
# --------------------------------------------------------------------------- #
# The dashboard loads every IC LIGHTWEIGHT (fast file-stat) and offers a per-IC
# "Run full" button. When pressed, that ONE IC is re-collected in full
# (authoritative gate matrix, ~seconds) and the result is pinned by the web
# layer's per-project cache so subsequent polls keep showing the authoritative
# card (no button) WITHOUT re-running the gate matrix. This fingerprint is the
# cache key: it changes only when the flow genuinely advances, at which point
# the card falls back to lightweight + button (inviting a fresh full run).


def _fingerprint_from(data: dict) -> tuple:
    """A cheap change-signature of a project tree, derived from an ALREADY
    collected LIGHTWEIGHT dict (no extra disk walk).

    It is deliberately MTIME-FREE and computed from LIGHTWEIGHT statuses: the
    set of existing output paths plus each step's lightweight status. Rationale
    — full mode (flow_compliance_check) REWRITES its own tracked report files in
    place on every run, which bumps mtimes without the build having progressed;
    an mtime fingerprint would then never match. Existence + lightweight status
    change only when the flow genuinely advances (a new output appears or a step
    completes), which is exactly when a pinned full result should be dropped.
    Always fingerprint a LIGHTWEIGHT collect on both store and validate so the
    two sides compare the same status vocabulary."""
    paths: List[str] = []
    statuses: List[tuple] = []
    for ph in data.get("phases", []):
        for st in ph.get("steps", []):
            statuses.append((str(st.get("id", "")), str(st.get("status", ""))))
            for o in st.get("outputs", []):
                if o.get("exists"):
                    paths.append(str(o.get("rel") or o.get("abs") or ""))
    return (tuple(sorted(paths)), tuple(statuses))


# --------------------------------------------------------------------------- #
# FLEET — many projects at a glance (multi-IC / multi-subagent overview)
# --------------------------------------------------------------------------- #
# A directory is treated as a Vibe-IC project when it carries at least one of
# these flow markers — enough to have a dashboard, without misfiring on random
# sibling dirs (e.g. a shared `logs/` or `pdk/`).
_PROJECT_MARKERS = (
    "phase1",
    "phase2",
    "phase3",
    "input/docs",
    "reports/orchestrator",
)


def _looks_like_project(path: Path) -> bool:
    try:
        if not path.is_dir():
            return False
    except OSError:
        return False
    for m in _PROJECT_MARKERS:
        if (path / m).exists():
            return True
    return False


def discover_projects(root: str) -> List[str]:
    """Return the immediate child directories of *root* that look like Vibe-IC
    projects, sorted by name. If *root* itself is a project (and has no project
    children), return just [root] so `--fleet <single-project>` still works.
    Never raises: an unreadable root yields []."""
    root_path = Path(root).expanduser().resolve()
    found: List[str] = []
    try:
        children = sorted(
            (c for c in root_path.iterdir() if not c.name.startswith(".")),
            key=lambda c: c.name.lower(),
        )
    except OSError:
        children = []
    for c in children:
        if _looks_like_project(c):
            found.append(str(c))
    if not found and _looks_like_project(root_path):
        found.append(str(root_path))
    return found


def card_from_detail(detail: dict, full_flag: bool, fingerprint) -> dict:
    """Build a compact fleet card from an ALREADY-collected detail dict (a
    collect() result). The heavy per-step `outputs` payload is dropped so a
    fleet of N ICs stays light. Pure — no I/O — so the caller can build a card
    from a detail it already has (and cache both together).

    The card carries two fields the UI keys on:
      * ``full``        — True iff this card holds AUTHORITATIVE (gate-verdict)
                          numbers; a lightweight card is False and gets a
                          "Run full" button.
      * ``fingerprint`` — a mtime-free change-signature (always from a
                          LIGHTWEIGHT collect) that lets the web layer pin a
                          full result until the tree actually changes."""
    phases_mini = []
    running_steps = []
    for ph in detail.get("phases", []):
        phases_mini.append(
            {
                "key": ph.get("key", ""),
                "label": ph.get("label", ""),
                "icon": ph.get("icon", ""),
                "resolved": int(ph.get("resolved", ph.get("done", 0)) or 0),
                "total": int(ph.get("total", 0) or 0),
            }
        )
        for st in ph.get("steps", []):
            if str(st.get("status", "")).lower() == "running":
                running_steps.append(
                    {
                        "id": st.get("id", ""),
                        "name": st.get("name", ""),
                        "phase": ph.get("key", ""),
                    }
                )
    return {
        "project": detail.get("project", ""),
        "project_name": detail.get("project_name", ""),
        "mode": detail.get("mode", ""),
        "flow_version": detail.get("flow_version", ""),
        "full": bool(full_flag),
        "fingerprint": list(fingerprint) if fingerprint is not None else None,
        "summary": detail.get("summary", {}),
        "phases_mini": phases_mini,
        "running_steps": running_steps,
    }


def _ic_card(project: str, full: bool = False) -> dict:
    """Collect ONE project and return its compact fleet card. Never raises: a
    project that fails to collect becomes an error card."""
    try:
        d = collect(project, full=full)
        # Fingerprint ALWAYS from a lightweight collect so store/validate match.
        light = d if not full else collect(project, full=False)
        fingerprint = _fingerprint_from(light)
    except Exception as exc:  # pragma: no cover - collect() is contractually safe
        name = Path(project).name or project
        return {
            "project": str(project),
            "project_name": name,
            "mode": "",
            "flow_version": "",
            "full": False,
            "fingerprint": None,
            "error": f"collect() failed: {exc}",
            "summary": {},
            "phases_mini": [],
            "running_steps": [],
        }
    # authoritative only when full mode genuinely ran (not a silent fallback)
    return card_from_detail(d, bool(full and d.get("mode") == "full"), fingerprint)


def collect_card(project, full: bool = False) -> dict:
    """Public single-IC fleet card (used by the web layer's per-card 'Run full'
    button). full=True runs the authoritative gate matrix for this ONE IC."""
    return _ic_card(str(project), full=full)


def collect_card_and_detail(project, full: bool = True):
    """Return (card, detail, fingerprint) in a single pass so the web layer can
    pin BOTH the compact card (fleet view) AND the full detail (drill-down page)
    from one gate run — keeping the two views consistent. Never raises."""
    try:
        detail = collect(project, full=full)
        light = detail if not full else collect(project, full=False)
        fingerprint = _fingerprint_from(light)
    except Exception as exc:  # pragma: no cover - collect() is contractually safe
        name = Path(project).name or str(project)
        err_card = {
            "project": str(project), "project_name": name, "mode": "",
            "flow_version": "", "full": False, "fingerprint": None,
            "error": f"collect() failed: {exc}", "summary": {},
            "phases_mini": [], "running_steps": [],
        }
        return err_card, {"error": f"collect() failed: {exc}"}, None
    full_ok = bool(full and detail.get("mode") == "full")
    card = card_from_detail(detail, full_ok, fingerprint)
    return card, detail, fingerprint


def collect_fleet(projects, full: bool = False, root: str = "") -> dict:
    """Collect MANY projects for the fleet overview.

    *projects* is an explicit iterable of project paths. When empty and *root*
    is given, the root is scanned via discover_projects(). Cards are LIGHTWEIGHT
    by default (fast — the page loads instantly and each card offers a per-IC
    "Run full" button); full=True collects the whole fleet authoritatively.
    Returns a stable JSON contract mirroring collect() at the aggregate level:

        {kind:"fleet", plugin_version, root, count,
         agg: {<same summary keys, summed>, ic_count, ic_running, ic_done},
         fleet: [ <_ic_card>, ... ]}

    Never raises."""
    plist = [str(p) for p in (projects or [])]
    if not plist and root:
        plist = discover_projects(root)

    cards = [_ic_card(p, full=full) for p in plist]

    # Aggregate the per-IC summaries into one fleet-wide roll-up.
    agg: Dict[str, int] = {k: 0 for k in _STATUSES}
    agg["total"] = 0
    agg["resolved"] = 0
    agg["passed"] = 0
    ic_running = 0
    ic_done = 0
    for c in cards:
        s = c.get("summary") or {}
        for k in _STATUSES:
            agg[k] += int(s.get(k, 0) or 0)
        agg["total"] += int(s.get("total", 0) or 0)
        agg["resolved"] += int(s.get("resolved", s.get("done", 0)) or 0)
        agg["passed"] += int(s.get("passed", 0) or 0)
        run = int(s.get("running", 0) or 0)
        if run > 0:
            ic_running += 1
        tot = int(s.get("total", 0) or 0)
        if tot and int(s.get("resolved", s.get("done", 0)) or 0) >= tot:
            ic_done += 1
    agg["ic_count"] = len(cards)
    agg["ic_running"] = ic_running
    agg["ic_done"] = ic_done

    return {
        "kind": "fleet",
        "plugin_version": _plugin_version(),
        "root": str(Path(root).expanduser().resolve()) if root else "",
        "count": len(cards),
        "agg": agg,
        "fleet": cards,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", help="path to the design project directory")
    ap.add_argument(
        "--full",
        action="store_true",
        help="authoritative mode: run flow_compliance_check.py (slow)",
    )
    ap.add_argument(
        "--fleet",
        action="store_true",
        help="treat PROJECT as a parent dir; collect ALL child projects (fleet view)",
    )
    ap.add_argument("--json", help="write the collected dict to this file")
    args = ap.parse_args(argv)

    if args.fleet:
        data = collect_fleet([], full=args.full, root=args.project)
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        if args.json:
            Path(args.json).write_text(payload + "\n", encoding="utf-8")
        else:
            print(payload)
        a = data["agg"]
        print(
            f"[flow_dashboard_data] FLEET {data['count']} IC(s) "
            f"({a['ic_running']} running, {a['ic_done']} done) "
            f"total={a['total']} done={a['resolved']} running={a['running']}",
            file=sys.stderr,
        )
        return 0

    data = collect(args.project, full=args.full)
    payload = json.dumps(data, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    s = data["summary"]
    print(
        f"[flow_dashboard_data] {data['project_name']} mode={data['mode']} "
        f"total={s['total']} done={s['resolved']} (pass={s['passed']} "
        f"fail={s['fail']} skipped={s['skipped']} waived={s['waived']} "
        f"na={s['na']} external={s['external']} partial={s['partial']}) "
        f"running={s['running']} pending={s['pending']}",
        file=sys.stderr,
    )
    if data["note"]:
        print(f"[flow_dashboard_data] note: {data['note']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
