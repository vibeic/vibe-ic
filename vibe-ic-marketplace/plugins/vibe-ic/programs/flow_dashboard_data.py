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
#   completion (DONE) — was the step reached AND judged? Everything EXCEPT
#                       running/pending is DONE ("resolved"): the flow got there
#                       and produced a verdict, whatever that verdict is.
#   outcome           — WHAT the verdict was: pass / fail / skipped / waived /
#                       na / external / partial.
# So a fail, a disclosed skip, an n/a and an external step are ALL "done" — they
# were evaluated. Only running (in progress) and pending (not reached) are not.
_RESOLVED = frozenset(
    {"pass", "skipped", "waived", "fail", "missing", "partial", "na", "external"}
)
_UNRESOLVED = frozenset({"running", "pending"})

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
    as forever-running (the exact spm 26/59 display bug)."""
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
        live = newest_mtime > 0.0 and (time.time() - newest_mtime) <= _RUNNING_WINDOW_S
        missing = n_total - n_present
        if live:
            return "running", f"{n_present}/{n_total} outputs · writing"
        return "partial", f"{n_present}/{n_total} outputs · {missing} secondary absent"
    return "pending", ""


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
    Analog A1-A9 + mixed M1-M4 apply only when the design declared analog blocks
    (`phase1/analog/analog_block_list.json` — the exact file the --full gate
    conditions on); manufacturing 40-44 only once silicon is physically back
    (`phase3/stage5_manufacturing/silicon_received.json`). When neither holds
    those lanes are honestly `na` / `external`, not a misleading `pending`."""
    analog = (project / "phase1" / "analog" / "analog_block_list.json").exists()
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


def collect(project, full: bool = False) -> dict:
    """Collect the live dashboard data for `project`.

    `project` may be a str or Path. `full=True` runs the authoritative
    compliance gate matrix; the default is the fast file-stat-only lightweight
    mode. Never raises: any failure in full mode falls back to lightweight."""
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
                newest_mtime,
            )
            # Honesty refinement: a bare `pending` is misleading for lanes that
            # will NEVER run for THIS design. Reclassify (matches --full's
            # SKIPPED-CONDITION but names the reason at a glance).
            if status == "pending":
                pk = _phase_key_for(step)
                if sid == "P0" and _p0_preflight_passed(project_path):
                    status, detail = "pass", (
                        "structural pre-flight passed (flow reached synthesis)")
                elif pk in ("analog", "mixed") and not analog_applicable:
                    status, detail = "na", (
                        "not applicable — design declares no analog / "
                        "mixed-signal content")
                elif pk == "manufacturing" and not silicon_received:
                    status, detail = "external", (
                        "external — off-machine (fab / wafer-sort / packaging / "
                        "final-test / qual)")

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
        "phases": phases_out,
    }


# --------------------------------------------------------------------------- #
# AUTO — cheap while live, authoritative once idle (the "no lightweight" ask)
# --------------------------------------------------------------------------- #
# The tension: authoritative (full) status re-runs the whole gate matrix
# (~seconds per IC), which is far too heavy to poll while a build is actively
# writing files. AUTO resolves it: it ALWAYS does the cheap lightweight pass
# first; if any step is RUNNING it returns that (a live build stays real-time);
# only once the tree is QUIESCENT does it escalate to the authoritative full
# verdicts. A tree-fingerprint cache means the expensive full run happens ONCE
# per settled state — subsequent idle polls reuse it until an output actually
# changes, so idle polling is free regardless of cadence.
_AUTO_FULL_CACHE: Dict[str, tuple] = {}  # project -> (fingerprint, full_result)


def _fingerprint_from(data: dict) -> tuple:
    """A cheap change-signature of a project tree, derived from an ALREADY
    collected lightweight dict (no extra disk walk).

    It is deliberately MTIME-FREE: the set of existing output paths plus each
    step's lightweight status. Rationale — full mode (flow_compliance_check)
    REWRITES its own tracked report files in place on every run, which bumps
    mtimes without the build having progressed; an mtime fingerprint would then
    never match and the expensive full run would repeat every poll. Existence +
    status changes only when the flow genuinely advances (a new output appears
    or a step's verdict flips), which is exactly when a re-escalation is due."""
    paths: List[str] = []
    statuses: List[tuple] = []
    for ph in data.get("phases", []):
        for st in ph.get("steps", []):
            statuses.append((str(st.get("id", "")), str(st.get("status", ""))))
            for o in st.get("outputs", []):
                if o.get("exists"):
                    paths.append(str(o.get("rel") or o.get("abs") or ""))
    return (tuple(sorted(paths)), tuple(statuses))


def collect_auto(project) -> dict:
    """Adaptive status: lightweight while a build is live, authoritative (full)
    once the tree is quiescent — cached per settled state. Never raises."""
    light = collect(project, full=False)
    # A live build (any running step) stays cheap + real-time.
    if int(light.get("summary", {}).get("running", 0) or 0) > 0:
        light["mode"] = "auto:live"
        return light
    # Quiescent → authoritative. Reuse the cached full run while the tree is
    # unchanged so idle polls don't re-run the gate matrix.
    key = str(Path(project).expanduser().resolve())
    fp = _fingerprint_from(light)
    cached = _AUTO_FULL_CACHE.get(key)
    if cached is not None and cached[0] == fp:
        return cached[1]
    full = collect(project, full=True)
    if full.get("mode") == "full":  # only cache a genuinely authoritative result
        full["mode"] = "auto:full"
        _AUTO_FULL_CACHE[key] = (fp, full)
    else:
        # full fell back to lightweight (checker missing/errored) — surface it,
        # don't poison the cache with a non-authoritative result.
        full["mode"] = "auto:lightweight"
    return full


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


def _ic_card(project: str, full: bool, auto: bool = False) -> dict:
    """Collect ONE project into a compact fleet card: the full summary plus a
    per-phase mini progress and the list of currently-running steps. The heavy
    per-step `outputs` payload is dropped so a fleet of N ICs stays light.
    Never raises: a project that fails to collect becomes an error card."""
    try:
        d = collect_auto(project) if auto else collect(project, full=full)
    except Exception as exc:  # pragma: no cover - collect() is contractually safe
        name = Path(project).name or project
        return {
            "project": str(project),
            "project_name": name,
            "mode": "",
            "flow_version": "",
            "error": f"collect() failed: {exc}",
            "summary": {},
            "phases_mini": [],
            "running_steps": [],
        }
    phases_mini = []
    running_steps = []
    for ph in d.get("phases", []):
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
        "project": d.get("project", str(project)),
        "project_name": d.get("project_name", Path(project).name),
        "mode": d.get("mode", ""),
        "flow_version": d.get("flow_version", ""),
        "summary": d.get("summary", {}),
        "phases_mini": phases_mini,
        "running_steps": running_steps,
    }


def collect_fleet(projects, full: bool = False, root: str = "", auto: bool = False) -> dict:
    """Collect MANY projects for the fleet overview.

    *projects* is an explicit iterable of project paths. When empty and *root*
    is given, the root is scanned via discover_projects(). With *auto*, each IC
    uses collect_auto() (cheap while live, authoritative once idle). Returns a
    stable JSON contract mirroring collect() at the aggregate level:

        {kind:"fleet", plugin_version, root, count,
         agg: {<same summary keys, summed>, ic_count, ic_running, ic_done},
         fleet: [ <_ic_card>, ... ]}

    Never raises."""
    plist = [str(p) for p in (projects or [])]
    if not plist and root:
        plist = discover_projects(root)

    cards = [_ic_card(p, full, auto=auto) for p in plist]

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
    ap.add_argument(
        "--auto",
        action="store_true",
        help="adaptive: lightweight while live, authoritative (full) once idle",
    )
    ap.add_argument("--json", help="write the collected dict to this file")
    args = ap.parse_args(argv)

    if args.fleet:
        data = collect_fleet([], full=args.full, root=args.project, auto=args.auto)
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

    data = collect_auto(args.project) if args.auto else collect(args.project, full=args.full)
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
