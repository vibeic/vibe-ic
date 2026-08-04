#!/usr/bin/env python3
"""
hold_closure_check.py — Step 20 (Post-CTS hold fixing) substance gate.

Scope (be honest about it)
--------------------------
Step 20 is the post-CTS hold-FIXING step (`skills/hold-fix`). CTS inserts
clock-tree insertion delay, which makes short data paths arrive too early at
the capture flop and creates hold violations. This step inserts hold buffers /
delay cells on those short paths so hold slack reaches >= 0 at the fast (FF)
corner. The CANONICAL final hold sign-off is Step 23 (post-route, multi-corner
STA). This gate only confirms that the Step-20 fixing step did REAL WORK; it
does NOT claim full multi-corner hold sign-off.

Historic hole (what this guards)
--------------------------------
The Step-20 gate previously gated on `files_exist: [post_hold.def]` ONLY — it
passed the moment the file appeared, with zero verification that hold fixing
actually happened. A flow could:
  * emit a `post_hold.def` that is byte-identical to the pre-hold input
    (`post_cts.def`) — i.e. the hold-fix step ran but inserted nothing, or was
    skipped and the input was simply copied, OR
  * leave a hold report behind that shows NEGATIVE hold slack (violation never
    closed),
and the presence-only gate would still PASS. Both are real backend failures.

Substance verification (deterministic, no fabrication)
------------------------------------------------------
1. The required artefact `phase3/stage3/pnr/post_hold.def` MUST exist, be
   non-empty, and parse as a DEF (DESIGN/COMPONENTS/END DESIGN). Absent / empty
   / unparseable => honest FAIL (rc=1) — NEVER a vacuous pass on absence.

2. PRIMARY (preferred) evidence — a parsed hold report.
   If a hold-slack report is present (canonical `phase3/stage3/sta` /
   `phase3/stage3/cts` / `phase3/stage3/pnr` `*hold*` / min-path reports, or any
   report carrying an explicit "hold ... slack" / "min ... slack" number), parse
   the WORST hold slack:
     * worst hold slack <  0  => FAIL (hold violation NOT closed).
     * worst hold slack >= 0  => PASS. (hold WNS >= 0 is a STRUCTURAL signoff
       fact, not a fabricated chip-specific threshold — slack < 0 is a
       violation by definition in STA.)
   The FAIL verdict also NAMES THE ARC KIND (#762): when the worst violating
   path's required time is a `library non-sequential hold time` increment, the
   message says so and points at the integration-level repair, because that
   violation is a stability window the macro's own Liberty declares between two
   SIGNAL pins and hold-buffer insertion provably cannot close it. This changes
   the WORDING, never the verdict — a negative hold slack still FAILs.

3. FALLBACK evidence — DEF diff vs the pre-hold input.
   When NO parseable hold report exists, prove the fixing step did real work by
   diffing `post_hold.def` against its pre-hold input `post_cts.def`:
     * byte-identical (same sha256)  => FAIL (no fixing actually happened —
       the input was copied through).
     * post_hold instance count <  post_cts instance count => FAIL (fixing
       cannot REMOVE instances; hold fixing only adds buffers/delay cells).
     * post_hold instance count >  post_cts (buffers/delay cells inserted)
       => PASS, reporting the inserted-instance delta.
     * post_hold instance count == post_cts but the files differ (e.g. only
       net/placement edits, no new cell) — we cannot positively confirm a
       hold-buffer was inserted, AND there is no hold report to confirm slack
       >= 0, so this is an HONEST FAIL (insufficient evidence), never a
       vacuous pass.
   When `post_cts.def` is ALSO missing we have neither a report nor a baseline
   to diff against — HONEST FAIL (cannot verify fixing happened).

Verdicts
--------
* PASS   (rc=0) — hold report worst slack >= 0, OR (no report) post_hold.def
                  provably differs from post_cts.def with a non-negative
                  inserted-instance delta.
* FAIL   (rc=1) — required DEF missing/empty/unparseable, hold report shows
                  negative slack, post_hold.def byte-identical to post_cts.def,
                  instance-count regression, or insufficient evidence.
* WAIVED (rc=0) — waivers.json declares this step waived (ticket + reason).
* SKIP   (rc=2) — project dir not found (operational, not a backend failure).

chip-AGNOSTIC. No vendor / IC / tool / PDK literal is hard-coded. No numeric
hold bound is invented — the only bound used is the universal STA structural
fact that hold slack >= 0 (negative = violation).

Usage
-----
    python3 hold_closure_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # pragma: no cover - standalone fallback
    _pl = None


_GATE_NAME = "hold_closure_check"
_GATE_LABEL = "hold_closure"


# --------------------------------------------------------------------------
# Waiver support (mirrors wafer_sort_yield_check.py shape)
# --------------------------------------------------------------------------
def _load_waivers(project: Path):
    p = project / "waivers.json"
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(errors="replace"))
    except Exception:
        return []
    if isinstance(data, dict):
        return data.get("waived_steps") or []
    return []


def _step_waived(project: Path, step_label: str):
    for w in _load_waivers(project):
        if not isinstance(w, dict):
            continue
        sid = str(w.get("id", "")).strip()
        ticket = str(w.get("ticket", ""))
        if sid == step_label or step_label in ticket:
            return w
    return None


# --------------------------------------------------------------------------
# Path resolution
# --------------------------------------------------------------------------
def _pnr_dir(project: Path) -> Path:
    if _pl is not None and hasattr(_pl, "pnr_dir"):
        return _pl.pnr_dir(project)
    return project / "phase3" / "stage3" / "pnr"


def _cts_dir(project: Path) -> Path:
    if _pl is not None and hasattr(_pl, "cts_dir"):
        return _pl.cts_dir(project)
    return project / "phase3" / "stage3" / "cts"


def _sta_dir(project: Path) -> Path:
    if _pl is not None and hasattr(_pl, "sta_dir"):
        return _pl.sta_dir(project)
    return project / "phase3" / "stage3" / "sta"


# --------------------------------------------------------------------------
# DEF parsing
# --------------------------------------------------------------------------
def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


_DESIGN_RE = re.compile(r"^\s*DESIGN\b", re.M)
_END_DESIGN_RE = re.compile(r"^\s*END\s+DESIGN\b", re.M)
_COMPONENTS_HDR_RE = re.compile(r"COMPONENTS\s+(\d+)\s*;")


def _looks_like_def(text: str) -> bool:
    """A real DEF has a DESIGN statement and an END DESIGN; COMPONENTS section
    is expected for a placed/post-CTS/post-hold DEF."""
    return bool(_DESIGN_RE.search(text)) and bool(_END_DESIGN_RE.search(text))


def _count_components(path: Path) -> int:
    """Count instances in the COMPONENTS section. Prefer the declared count in
    the `COMPONENTS <n> ;` header; fall back to counting `-` instance lines."""
    in_components = False
    count = 0
    try:
        with path.open(errors="replace") as f:
            for line in f:
                s = line.strip()
                if s.startswith("COMPONENTS"):
                    m = _COMPONENTS_HDR_RE.match(s)
                    if m:
                        return int(m.group(1))
                    in_components = True
                elif s.startswith("END COMPONENTS"):
                    in_components = False
                elif in_components and s.startswith("-"):
                    count += 1
    except OSError:
        return 0
    return count


# --------------------------------------------------------------------------
# Hold-report parsing
# --------------------------------------------------------------------------
# Patterns that carry an explicit hold (min-path) slack number. We deliberately
# only mine HOLD / MIN-path slack — never the setup/max slack — so we do not
# mis-read a setup report as a hold violation. Matches the OpenSTA /
# report_checks idioms:
#   "hold slack ... -0.123"     (report summary)
#   "min slack ... 0.045"
#   "slack (MET) ... 0.045" within a "-path_delay min" block
#   "Hold WNS = -0.012"
#   JSON-ish: "hold_wns_ns": -0.01  /  "worst_hold_slack": ...
_HOLD_SLACK_PATTERNS = [
    re.compile(r"hold[^\n]*?\bslack\b[^\n\-0-9]*(-?\d+\.?\d*)", re.I),
    re.compile(r"\bWHS\b[^\n\-0-9]*(-?\d+\.?\d*)", re.I),
    re.compile(r"hold[_ ]?wns[^\n\-0-9]*(-?\d+\.?\d*)", re.I),
    re.compile(r"worst[_ ]?hold[_ ]?slack[^\n\-0-9]*(-?\d+\.?\d*)", re.I),
    re.compile(r"min[_ ]?slack[^\n\-0-9]*(-?\d+\.?\d*)", re.I),
]


def _find_hold_reports(project: Path) -> List[Path]:
    """Discover candidate hold-slack reports in canonical phase3 dirs.
    Returns files whose name suggests a hold / min-path report, plus any STA
    report that may contain a hold section."""
    cands: List[Path] = []
    seen = set()
    search_dirs = [_sta_dir(project), _cts_dir(project), _pnr_dir(project)]
    name_globs = [
        "*hold*.rpt", "*hold*.txt", "*hold*.log", "*hold*.json",
        "*min*path*.rpt", "*min_slack*.rpt", "post_hold*.rpt",
    ]
    for d in search_dirs:
        if not d.is_dir():
            continue
        for g in name_globs:
            for p in d.glob(g):
                if p.is_file() and p not in seen:
                    seen.add(p)
                    cands.append(p)
    return cands


# --------------------------------------------------------------------------
# Arc-kind attribution for the violating path (vibe-ic#762)
# --------------------------------------------------------------------------
# A negative hold slack whose required time is dominated by a LIBRARY
# NON-SEQUENTIAL arc is not a clock-skew problem and hold-buffer insertion
# cannot close it. The macro's own Liberty states a stability window between
# two SIGNAL pins (`timing_type : non_seq_hold_falling`), and STA prints it in
# the path as an explicit `library non-sequential hold time` increment:
#
#     9.00    9.34   library non-sequential hold time
#
# Reporting only the slack (`-8.68`) points the reader at the router — closing
# 8.68 ns of DATA-path hold with buffers is on the order of 87 stages — when
# the repair is at the integration level (hold the constrained pin across the
# strobe, or launch the strobe from a later edge). So the verdict NAMES the arc
# kind. It does NOT change the verdict: a negative hold slack still FAILs.
#
# Universal `report_checks` wording, no tool/PDK/vendor literal.
_PATH_BLOCK_RE = re.compile(r"(?m)^[ \t]*Startpoint[ \t]*:")
_PATH_END_SLACK_RE = re.compile(
    r"(-?\d+\.?\d*)\s+slack\s*\((?:MET|VIOLATED)\)", re.I)
_NON_SEQ_INCR_RE = re.compile(
    r"(?m)^[ \t]*(-?\d+\.?\d*)[ \t]+-?\d+\.?\d*[ \t]+library[ \t]+"
    r"non-?sequential[ \t]+(setup|hold)[ \t]+time", re.I)
_ENDPOINT_RE = re.compile(r"(?m)^[ \t]*Endpoint[ \t]*:[ \t]*(\S+)")
_STARTPOINT_RE = re.compile(r"(?m)^[ \t]*Startpoint[ \t]*:[ \t]*(\S+)")


def _non_sequential_hold_paths(text: str) -> List[dict]:
    """Path blocks in a `report_checks` report whose required time includes a
    `library non-sequential hold time` increment.

    Returns ``[{slack, non_seq_ns, startpoint, endpoint}, ...]``. Empty for any
    report that carries no such increment, so a design with no non-sequential
    arc is byte-identically unaffected."""
    out: List[dict] = []
    bounds = [m.start() for m in _PATH_BLOCK_RE.finditer(text or "")]
    if not bounds:
        return out
    bounds.append(len(text or ""))
    for i in range(len(bounds) - 1):
        block = (text or "")[bounds[i]:bounds[i + 1]]
        incs = [(float(m.group(1)), m.group(2).lower())
                for m in _NON_SEQ_INCR_RE.finditer(block)]
        incs = [(v, k) for v, k in incs if k == "hold"]
        if not incs:
            continue
        slacks = []
        for m in _PATH_END_SLACK_RE.finditer(block):
            try:
                slacks.append(float(m.group(1)))
            except (TypeError, ValueError):
                continue
        sp = _STARTPOINT_RE.search(block)
        ep = _ENDPOINT_RE.search(block)
        out.append({
            "slack": min(slacks) if slacks else None,
            "non_seq_ns": max(v for v, _ in incs),
            "startpoint": sp.group(1) if sp else None,
            "endpoint": ep.group(1) if ep else None,
        })
    return out


def _non_seq_attribution(path: Path) -> List[dict]:
    try:
        return _non_sequential_hold_paths(path.read_text(errors="replace"))
    except OSError:
        return []


def _parse_worst_hold_slack(path: Path) -> Tuple[Optional[float], List[float]]:
    """Return (worst_slack, all_slacks). worst_slack is the MINIMUM hold slack
    found (most negative). None when no hold-slack number is parseable."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None, []
    slacks: List[float] = []
    for pat in _HOLD_SLACK_PATTERNS:
        for m in pat.finditer(text):
            try:
                slacks.append(float(m.group(1)))
            except (TypeError, ValueError):
                continue
    # OpenSTA / OpenROAD `report_checks -path_delay min` TABLE form: the report
    # declares "Path Type: min" (= hold / min-path) and ends each path with
    # "<value>   slack (MET|VIOLATED)". This is the canonical hold report the
    # runner now emits (post_hold_timing.rpt) and it carries NO "min slack" /
    # "hold slack" summary token, so the patterns above miss it. When the report
    # is a min-path (hold) report, mine the "slack (MET|VIOLATED)" path-end
    # values directly. chip-AGNOSTIC: matches universal report_checks structure.
    if not slacks and re.search(r"Path\s*Type\s*:\s*min", text, re.I):
        for m in re.finditer(r"(-?\d+\.?\d*)\s+slack\s*\((?:MET|VIOLATED)\)",
                             text, re.I):
            try:
                slacks.append(float(m.group(1)))
            except (TypeError, ValueError):
                continue
    if not slacks:
        return None, []
    return min(slacks), slacks


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
def _read_def(path: Path) -> Tuple[Optional[str], int, Optional[str]]:
    """Return (text, size, error). text is None on read error."""
    try:
        size = path.stat().st_size
    except OSError as e:
        return None, 0, f"stat failed: {e}"
    try:
        text = path.read_text(errors="replace")
    except OSError as e:
        return None, size, f"read failed: {e}"
    return text, size, None


def evaluate(project: Path) -> Tuple[str, int, List[dict], dict]:
    """Return (verdict, rc, findings, summary)."""
    findings: List[dict] = []
    summary: dict = {}

    pnr = _pnr_dir(project)
    post_hold = pnr / "post_hold.def"
    post_cts = pnr / "post_cts.def"
    summary["post_hold_def"] = str(post_hold)
    summary["post_cts_def"] = str(post_cts)

    # ---- waiver path (only relevant when the artefact is missing) ----
    waiver = _step_waived(project, _GATE_LABEL)

    # ---- 1. required DEF must exist + be non-empty + parse as DEF ----
    if not post_hold.is_file():
        if waiver:
            findings.append({
                "severity": "WAIVED", "rule": "STEP_WAIVED",
                "message": f"waiver={waiver.get('ticket', '?')}: "
                           f"{waiver.get('reason', '?')}",
            })
            return "WAIVED", 0, findings, summary
        findings.append({
            "severity": "FAIL", "rule": "POST_HOLD_DEF_MISSING",
            "message": "phase3/stage3/pnr/post_hold.def not found — the "
                       "Step-20 hold-fixing step produced no output (cannot "
                       "verify hold fixing happened)",
        })
        return "FAIL", 1, findings, summary

    ph_text, ph_size, ph_err = _read_def(post_hold)
    summary["post_hold_size"] = ph_size
    if ph_err is not None:
        findings.append({
            "severity": "FAIL", "rule": "POST_HOLD_DEF_UNREADABLE",
            "message": f"cannot read post_hold.def: {ph_err}",
        })
        return "FAIL", 1, findings, summary
    if ph_size == 0 or not (ph_text or "").strip():
        findings.append({
            "severity": "FAIL", "rule": "POST_HOLD_DEF_EMPTY",
            "message": "post_hold.def is empty",
        })
        return "FAIL", 1, findings, summary
    if not _looks_like_def(ph_text or ""):
        findings.append({
            "severity": "FAIL", "rule": "POST_HOLD_DEF_UNPARSEABLE",
            "message": "post_hold.def lacks DESIGN / END DESIGN structure — "
                       "not a valid DEF",
        })
        return "FAIL", 1, findings, summary

    ph_components = _count_components(post_hold)
    summary["post_hold_components"] = ph_components
    findings.append({
        "severity": "INFO", "rule": "POST_HOLD_DEF_OK",
        "message": f"post_hold.def parsed: {ph_size} B, "
                   f"components={ph_components}",
    })

    # ---- 2. PRIMARY: parse a hold-slack report if one exists ----
    hold_reports = _find_hold_reports(project)
    parsed_any_report = False
    worst_overall: Optional[float] = None
    non_seq_paths: List[dict] = []
    for rpt in hold_reports:
        worst, slacks = _parse_worst_hold_slack(rpt)
        if worst is None:
            continue
        parsed_any_report = True
        rel = str(rpt.relative_to(project)) if str(rpt).startswith(str(project)) \
            else str(rpt)
        findings.append({
            "severity": "INFO", "rule": "HOLD_REPORT_READ",
            "message": f"{rel}: worst hold slack {worst} "
                       f"({len(slacks)} slack value(s) parsed)",
        })
        for blk in _non_seq_attribution(rpt):
            blk["report"] = rel
            non_seq_paths.append(blk)
        worst_overall = worst if worst_overall is None else min(worst_overall, worst)

    if parsed_any_report:
        summary["evidence"] = "hold_report"
        summary["worst_hold_slack"] = worst_overall
        if non_seq_paths:
            summary["non_sequential_hold_paths"] = non_seq_paths
        # Universal STA structural fact: hold slack < 0 is a violation.
        if worst_overall is not None and worst_overall < 0:
            # #762 — NAME the arc kind when the worst violating path's required
            # time is a library NON-SEQUENTIAL hold arc. Same FAIL, accurate
            # vocabulary: the previous message said "re-CTS / insert delay
            # cells", which is the one repair that provably cannot close it.
            worst_ns = None
            for blk in non_seq_paths:
                s = blk.get("slack")
                if isinstance(s, float) and abs(s - worst_overall) < 1e-9:
                    worst_ns = blk
                    break
            if worst_ns is not None:
                summary["worst_hold_arc_kind"] = "library_non_sequential_hold"
                summary["worst_hold_non_seq_ns"] = worst_ns.get("non_seq_ns")
                msg = (
                    f"hold report shows NEGATIVE worst hold slack "
                    f"{worst_overall} — and the WORST path's required time is "
                    f"a library NON-SEQUENTIAL hold arc of "
                    f"{worst_ns.get('non_seq_ns')} ns "
                    f"(endpoint {worst_ns.get('endpoint')}), not a clock-skew "
                    f"shortfall. A non-sequential arc is a stability window "
                    f"the macro's OWN Liberty declares between two SIGNAL "
                    f"pins, so it is an INTEGRATION requirement: hold the "
                    f"constrained pin across the reference edge (de-assert "
                    f"the driving register's enable) or launch the strobe "
                    f"from a later edge. Hold-buffer / delay-cell insertion "
                    f"cannot close it — the whole window would have to be "
                    f"built out of delay stages. See "
                    f"macro_non_seq_arc_contract_check, which reports this "
                    f"requirement at Step 7 from the staged macro's own "
                    f"Liberty.")
            else:
                msg = (f"hold report shows NEGATIVE worst hold slack "
                       f"{worst_overall} — hold violation not closed by "
                       f"Step-20 fixing (re-CTS / insert delay cells)")
                if non_seq_paths:
                    summary["worst_hold_arc_kind"] = "sequential"
                    msg += (f"; NB {len(non_seq_paths)} OTHER path(s) in this "
                            f"report are constrained by a library "
                            f"non-sequential hold arc — those are integration "
                            f"requirements that delay cells cannot close")
            findings.append({
                "severity": "FAIL", "rule": "HOLD_SLACK_NEGATIVE",
                "message": msg,
            })
            return "FAIL", 1, findings, summary
        findings.append({
            "severity": "INFO", "rule": "HOLD_SLACK_NONNEGATIVE",
            "message": f"hold report worst hold slack {worst_overall} >= 0 — "
                       f"hold closed at the analysed corner (final multi-corner "
                       f"sign-off is Step 23 post-route STA)",
        })
        return "PASS", 0, findings, summary

    # ---- 3. FALLBACK: DEF diff vs the pre-hold input (post_cts.def) ----
    summary["evidence"] = "def_diff"
    if not post_cts.is_file():
        findings.append({
            "severity": "FAIL", "rule": "NO_HOLD_EVIDENCE",
            "message": "no parseable hold report AND pre-hold input "
                       "post_cts.def is missing — cannot verify that the "
                       "Step-20 hold-fixing step did any real work",
        })
        return "FAIL", 1, findings, summary

    pc_text, pc_size, pc_err = _read_def(post_cts)
    summary["post_cts_size"] = pc_size
    if pc_err is not None or pc_size == 0 or not (pc_text or "").strip():
        findings.append({
            "severity": "FAIL", "rule": "POST_CTS_DEF_UNUSABLE",
            "message": "no hold report AND pre-hold input post_cts.def is "
                       f"empty/unreadable ({pc_err or 'empty'}) — cannot diff "
                       "to verify hold fixing happened",
        })
        return "FAIL", 1, findings, summary

    pc_components = _count_components(post_cts)
    summary["post_cts_components"] = pc_components

    # 3a. byte-identical => the input was copied through, no fixing happened.
    if _sha(post_hold) == _sha(post_cts):
        findings.append({
            "severity": "FAIL", "rule": "POST_HOLD_IDENTICAL_TO_INPUT",
            "message": "post_hold.def is byte-identical to its pre-hold input "
                       "post_cts.def (same sha256) — the hold-fixing step "
                       "inserted nothing / the input was copied through",
        })
        return "FAIL", 1, findings, summary

    delta = ph_components - pc_components
    summary["inserted_instance_delta"] = delta

    # 3b. instance-count regression => fixing cannot REMOVE cells.
    if delta < 0:
        findings.append({
            "severity": "FAIL", "rule": "INSTANCE_COUNT_REGRESSION",
            "message": f"post_hold.def has fewer components "
                       f"({ph_components}) than post_cts.def ({pc_components}) "
                       f"— hold fixing only adds buffers/delay cells, never "
                       f"removes them",
        })
        return "FAIL", 1, findings, summary

    # 3c. buffers/delay cells inserted => real work.
    if delta > 0:
        findings.append({
            "severity": "INFO", "rule": "HOLD_CELLS_INSERTED",
            "message": f"post_hold.def added {delta} component(s) vs "
                       f"post_cts.def ({pc_components} -> {ph_components}) — "
                       f"hold buffer/delay-cell insertion did real work "
                       f"(NB: numeric hold sign-off is Step 23 post-route STA)",
        })
        return "PASS", 0, findings, summary

    # 3d. files differ but instance count unchanged AND no hold report.
    # We cannot positively confirm a hold-buffer was inserted, and have no
    # slack number to confirm closure — honest FAIL (insufficient evidence).
    findings.append({
        "severity": "FAIL", "rule": "NO_INSERTED_CELLS_NO_REPORT",
        "message": f"post_hold.def differs from post_cts.def but the component "
                   f"count is unchanged ({ph_components}) and there is no "
                   f"parseable hold report — cannot confirm a hold buffer/delay "
                   f"cell was inserted nor that hold slack is >= 0",
    })
    return "FAIL", 1, findings, summary


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _emit(args, project: Path, verdict: str, findings: List[dict],
          summary: dict) -> None:
    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": _GATE_LABEL,
        "summary": summary,
        "findings": findings,
    }
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    if "worst_hold_slack" in summary:
        print(f"  worst hold slack: {summary['worst_hold_slack']}")
    if "worst_hold_arc_kind" in summary:
        print(f"  worst-path arc kind: {summary['worst_hold_arc_kind']}"
              + (f" ({summary['worst_hold_non_seq_ns']} ns)"
                 if "worst_hold_non_seq_ns" in summary else ""))
    if "inserted_instance_delta" in summary:
        print(f"  inserted instance delta: {summary['inserted_instance_delta']}")
    for f in findings:
        if f["severity"] in ("FAIL", "WAIVED"):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Step 20 post-CTS hold-fixing substance gate")
    parser.add_argument("project_dir", help="Project directory to scan")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}",
              file=sys.stderr)
        return 2

    verdict, rc, findings, summary = evaluate(project)
    _emit(args, project, verdict, findings, summary)
    return rc


if __name__ == "__main__":
    sys.exit(main())
