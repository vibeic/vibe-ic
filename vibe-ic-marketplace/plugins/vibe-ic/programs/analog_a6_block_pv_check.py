#!/usr/bin/env python3
"""analog_a6_block_pv_check.py — A6 deterministic gate
(Per-Block Physical Verification: DRC + LVS).

Verifies that EVERY analog block listed in
`phase3/analog/analog_block_list.json` has REAL, evidence-backed
per-block physical verification:

  * DRC: zero violations.  Read from one of (first match wins):
      - analog/<block>/drc.report   (Magic / KLayout text DRC report)
      - analog/<block>/*.drc.report / *.lyrdb (KLayout)
      - analog/<block>/drc_clean.flag  (must carry an explicit
        `violations: 0` / `count=0` line — a bare flag is NOT enough)
    PASS only when the parsed violation COUNT == 0.

  * LVS: a match.  Read from one of (first match wins):
      - analog/<block>/lvs.report   (Netgen / Calibre text LVS report)
      - analog/<block>/comp.json    (Netgen JSON comparison)
      - analog/<block>/lvs_match.flag  (must carry an explicit
        `match`/`lvs: match` verdict — a bare flag is NOT enough)
    PASS only when the report declares a MATCH.

Behaviour
---------
* SKIP (rc=2)  — there are genuinely NO analog blocks (block list
                  absent or empty).  Real non-applicability.
* WAIVED (rc=0) — `waivers.json` declares the step waived (evidence
                  + ticket) AND every live finding is a MEASURED defect.
* PASS (rc=0)  — every block has DRC violations == 0 AND LVS == match.
* FAIL (rc=1)  — any block has DRC violations > 0, LVS mismatch, OR a
                  missing/empty/garbage DRC or LVS artefact for a block
                  that EXISTS.  NO vacuous PASS on absence.

NO FABRICATION (hard rule): a block that has a directory but is missing
real DRC or LVS evidence is an HONEST FAIL — never a silent PASS.

A WAIVER CANNOT COVER AN ABSENT MEASUREMENT (`_NON_WAIVABLE_RULES`).
A step waiver is an accepted-RISK statement about a defect somebody
measured: "DRC reports 3 violations and we ship anyway, ticket T-1".
Where nothing was measured there is no risk to accept — waiving
`A6_PV_BLOCK_DIR_MISSING` / `A6_PV_DRC_NO_EVIDENCE` /
`A6_PV_LVS_NO_EVIDENCE` would turn "the tool never ran" into rc 0, which
is the unmeasured-reported-as-zero failure this gate exists to refuse.
Measured on a project declaring one analog block with NO drc/lvs
artefacts at all plus a `waived_steps: [{id: analog_block_pv}]` entry:
the gate used to return WAIVED rc=0. Such findings now stay LIVE and the
step FAILs (rc=1) with `waiver_cannot_cover` naming them; any measured
DRC/LVS defect present alongside is still listed under
`suppressed_findings`, so the waiver keeps working for what a waiver is
for. This is also the ONLY per-block PV gate in the flow since A5
stopped reading A6's outputs (see `analog_a5_layout_check`'s SCOPE
section), so its non-silenceable core carries the whole class.

WHAT AN LVS MATCH DOES NOT SAY — the matching disclosure, carried through
--------------------------------------------------------------------------
This gate's LVS half is a TOPOLOGY compare. It is blind to common-centroid
placement, to interdigitated finger order and to dummies — and the last of
those it is worse than blind to, because a dummy is a device the schematic
does not have and it makes the compare HARDER. So a block laid out as N
isolated devices in N slots reaches the same green PASS here as a fully
matched one, and this gate's report was where a reader looked to find out.

It now carries `_analog_layout_matching`'s classification of every block into
its summary — `blocks_no_matching_structure`, `blocks_matching_undisclosed`,
`matching_disclosure` — on EVERY verdict path. This is a RECORD, not a rule:
no matching class changes this gate's verdict or exit code, because the
rules over that record belong to A5, where the layout is. What changes is
that "this block closed A6 with no matching structure" is now a field in the
artefact rather than an inference from its absence.

Preserves the CLI contract:
    python3 analog_a6_block_pv_check.py <project_dir> [--json <out>]
                                                       [--block <name>]
                                                       [--step-label <l>]
module-level main(argv) -> int (0 PASS/SKIP/WAIVED, 1 FAIL, 2 bad dir).

chip-AGNOSTIC. No vendor / IC / tool-specific data hard-coded.
"""
from __future__ import annotations

import argparse
import json
import re
from xml.etree import ElementTree
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_GATE_NAME = "analog_a6_block_pv_check"
_GATE_LABEL = "analog_block_pv"
_SKILL = "drc-fix + lvs-triage"

# Findings that report an ABSENT measurement rather than a measured defect.
# A step waiver may not suppress these — see the module docstring. The
# complement (A6_PV_DRC_VIOLATIONS / A6_PV_LVS_MISMATCH) is a measured
# defect and stays waivable, which is what the flow-wide waiver mechanism
# is for and what waivers_schema_check / waiver_legitimacy_check /
# foundry_signoff_plan_check separately police. chip-AGNOSTIC.
_NON_WAIVABLE_RULES = frozenset({
    "A6_PV_BLOCK_DIR_MISSING",
    "A6_PV_DRC_NO_EVIDENCE",
    "A6_PV_LVS_NO_EVIDENCE",
    # A contradiction between two parseable witnesses is not a measured risk
    # either: nobody can say WHICH of the two numbers the accepted risk is
    # about, so there is nothing for a waiver to accept. See
    # `_witness_disagreements`.
    "A6_PV_DRC_WITNESS_DISAGREEMENT",
    "A6_PV_LVS_WITNESS_DISAGREEMENT",
})

# ---------------------------------------------------------------------------
# block list (mirrors _analog_a_check_common.load_block_list — kept local so
# this gate has no hard dependency on import order).
# ---------------------------------------------------------------------------


def _load_block_list(project: Path) -> Optional[List[str]]:
    """Return declared analog block names, or None when no block-list
    file exists at all (digital-only / non-applicable).

    ROOTS. `phase1/analog/` is the root A6's OWN flow condition names
    (`condition.files_exist: ["phase1/analog/analog_block_list.json"]`) and the
    one `_analog_a_check_common.block_list_path` — which every A1-A5 gate uses
    — has probed since the A-gates were brought in line. This local reader
    probed only `phase3/analog/` and the legacy `analog/`, so on a project whose
    block list lives ONLY at the flow-declared root the step's condition fired,
    the gate ran, and it returned `SKIP (no analog blocks)` with rc=2 —
    which `flow_compliance_check._run_program` credits as VACUOUS_PASS. A6
    therefore reported "per-block PV non-applicable" for a project that
    declares analog blocks: UNMEASURED PRESENTED AS ZERO. Probing the same
    roots as the shared helper, in the same precedence order (canonical runner
    root first), closes it; a project carrying neither root still returns None
    and still SKIPs, so a genuinely digital IC is unaffected.
    """
    candidates = [
        project / "phase3" / "analog" / "analog_block_list.json",
        project / "phase1" / "analog" / "analog_block_list.json",
        project / "analog" / "analog_block_list.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        blocks = data.get("blocks") if isinstance(data, dict) else data
        if not isinstance(blocks, list):
            return []
        out: List[str] = []
        for entry in blocks:
            if isinstance(entry, str) and entry:
                out.append(entry)
            elif isinstance(entry, dict):
                name = entry.get("name") or entry.get("block")
                if isinstance(name, str) and name:
                    out.append(name)
        return out
    return None


def _block_dir(project: Path, block: str) -> Optional[Path]:
    """Return the on-disk per-block directory, preferring the
    v2-canonical phase3/analog/<block>/ tree, then the legacy
    analog/<block>/ tree. None when neither exists."""
    for cand in (project / "phase3" / "analog" / block,
                 project / "analog" / block):
        if cand.is_dir():
            return cand
    return None


# ---------------------------------------------------------------------------
# DRC parsing — return (violations:int|None, evidence:str).
#   violations is None when no parseable DRC evidence exists.
# ---------------------------------------------------------------------------

# Common "N violations / errors" phrasings emitted by Magic, KLayout,
# Calibre.  Chip-AGNOSTIC: matches the verb, not any IC/tool brand text.
_DRC_COUNT_RE = re.compile(
    r"(?:total\s+)?(?:drc\s+)?"
    r"(?:violation|error|geometr\w*\s+error)s?\s*[:=]?\s*(\d+)",
    re.IGNORECASE,
)
_DRC_ZERO_PHRASES = (
    "drc clean", "no drc violations", "0 drc errors", "no errors found",
    "drc passed", "violations: 0", "violations=0", "count: 0", "count=0",
    "0 violations", "0 errors",
)


def _parse_drc_count(text: str) -> Optional[int]:
    """Extract a DRC violation count from a DRC report's text.
    Returns the integer count, or None when no count phrase is found.
    A zero-phrase (e.g. 'DRC clean') resolves to 0."""
    low = text.lower()
    counts: List[int] = [int(m.group(1)) for m in _DRC_COUNT_RE.finditer(low)]
    if counts:
        # The worst (max) count is the conservative verdict: any
        # non-zero count anywhere in the report means NOT clean.
        return max(counts)
    if any(p in low for p in _DRC_ZERO_PHRASES):
        return 0
    return None


def parse_lyrdb(text: str) -> Optional[int]:
    """Violation count of a KLayout marker database, or None.

    A `.lyrdb` never contains an "N violations" phrase, so the free-text
    reader below can extract no count from one — in EITHER direction. The
    glob has always listed `*.lyrdb`, and it has always been inert: a
    sign-off-clean block and a violating block both landed on the
    "unparseable → no evidence → FAIL" branch, so the one report format
    the open-PDK KLayout path actually emits could never certify anything.

    The count is the number of `<item>` elements. The guard is the one
    LAW the zero-rules fix established: a database that declares NO
    `<category>` graded no rule, so its emptiness is silence, not a pass —
    that returns None (no evidence) rather than 0.
    """
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return None
    if root.tag != "report-database":
        return None
    if not list(root.iter("category")):
        return None
    return len(list(root.iter("item")))


def _drc_violations(bdir: Path) -> Tuple[Optional[int], str]:
    """Per-block DRC verdict. Returns (count, evidence_rel).
    count is None when there is NO parseable DRC evidence."""
    # 1. Explicit DRC report files (richest evidence).
    report_globs = ["drc.report", "*.drc.report", "*.lyrdb",
                    "drc.rpt", "*.drc"]
    for pat in report_globs:
        for f in sorted(bdir.glob(pat)):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not text.strip():
                continue
            if f.suffix == ".lyrdb":
                count = parse_lyrdb(text)
                if count is not None:
                    return count, f.name
                continue
            count = _parse_drc_count(text)
            if count is not None:
                return count, f.name
            # Report present but unparseable → treat as no-evidence so
            # the block FAILs honestly (we won't guess clean).
    # 2. drc_clean.flag — but only with an explicit zero-count line.
    flag = bdir / "drc_clean.flag"
    if flag.is_file():
        try:
            text = flag.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        count = _parse_drc_count(text)
        if count is not None:
            return count, flag.name
        # Bare flag with no count line → NOT acceptable evidence.
    return None, ""


# ---------------------------------------------------------------------------
# LVS parsing — return (matched:bool|None, evidence:str).
#   matched is None when no parseable LVS evidence exists.
# ---------------------------------------------------------------------------

_LVS_MATCH_PHRASES = (
    "circuits match uniquely", "netlists match", "lvs match",
    "lvs: match", "lvs passed", "match: true", "match=true",
    "result: match", "the netlists match",
)
_LVS_MISMATCH_PHRASES = (
    "circuits do not match", "netlists do not match", "lvs mismatch",
    "lvs: mismatch", "lvs failed", "match: false", "match=false",
    "result: mismatch", "property errors", "incorrect", "unmatched",
    "failed pin matching",  # #524 — netgen top-level pin-fail terminal verdict
)


def _parse_lvs_match(text: str) -> Optional[bool]:
    """Return True (match), False (mismatch), or None (no verdict)."""
    # #524 — netgen-specific terminal verdicts defer to the SHARED classifier
    # first (single source of truth); the tool-generic phrase lists below stay
    # for calibre/other-tool evidence shapes.
    try:
        import sys as _sys
        from pathlib import Path as _P
        _here = str(_P(__file__).resolve().parent)
        if _here not in _sys.path:
            _sys.path.insert(0, _here)
        import lvs_verdict_tokens as _lvt
        # A netgen report's verdict belongs to the SHARED classifier, which is
        # JSON-authoritative and fail-safe. Previously only the MISMATCH regex
        # was consulted, so a netgen transcript the classifier REFUSED could
        # still be talked into a match by the tool-generic phrase list below
        # (e.g. a reworded failure next to "netlists match") — the same
        # false-clean-by-wording hole the classifier itself just closed.
        if _lvt.is_netgen_report(text):
            verdict = _lvt.classify(text)
            if verdict == "MATCH":
                return True
            if verdict == "MISMATCH":
                return False
            return None  # INCOMPLETE — never upgraded by generic phrases
        if _lvt.MISMATCHED_RE.search(text):
            return False
    except Exception:  # nosec — best-effort; phrase lists below still apply
        pass
    low = text.lower()
    # Mismatch phrases win over match phrases (a report that mentions
    # both 'match' and 'do not match' is a mismatch).
    has_mismatch = any(p in low for p in _LVS_MISMATCH_PHRASES)
    has_match = any(p in low for p in _LVS_MATCH_PHRASES)
    if has_mismatch:
        return False
    if has_match:
        return True
    return None


def _lvs_match(bdir: Path) -> Tuple[Optional[bool], str]:
    """Per-block LVS verdict. Returns (matched, evidence_rel).
    matched is None when there is NO parseable LVS evidence."""
    # 1. Netgen JSON comparison (comp.json) — structured verdict.
    comp = bdir / "comp.json"
    if comp.is_file():
        try:
            data = json.loads(comp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = None
        if isinstance(data, dict):
            # Netgen-style: {"result": "match"|"mismatch"} or a count of
            # mismatched elements.
            res = str(data.get("result", "")).lower()
            if res in ("match", "matched", "pass"):
                return True, comp.name
            if res in ("mismatch", "fail", "failed"):
                return False, comp.name
            mismatches = data.get("mismatches")
            if isinstance(mismatches, int):
                return (mismatches == 0), comp.name
    # 2. Explicit LVS text report.
    for pat in ["lvs.report", "*.lvs.report", "lvs.rpt", "comp.out",
                "*.lvs"]:
        for f in sorted(bdir.glob(pat)):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not text.strip():
                continue
            verdict = _parse_lvs_match(text)
            if verdict is not None:
                return verdict, f.name
    # 3. lvs_match.flag — but only with an explicit match verdict line.
    flag = bdir / "lvs_match.flag"
    if flag.is_file():
        try:
            text = flag.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        verdict = _parse_lvs_match(text)
        if verdict is not None:
            return verdict, flag.name
        # Bare flag with no verdict line → NOT acceptable evidence.
    return None, ""


# ---------------------------------------------------------------------------
# per-block audit
# ---------------------------------------------------------------------------


def _evidence_gap(bdir: Path, flag_name: str, report_globs: List[str]) -> str:
    """Say WHY there is no parseable evidence, not merely that there is none.

    A6 owns the per-block PV verdict outright since the A5/A6 cycle was broken
    (see `analog_a5_layout_check`'s SCOPE section). A5's rules distinguished
    ABSENT / EMPTY / VERDICT-LESS so an operator could tell "run the tool" from
    "fix the tool's output"; that granularity is preserved here in the finding
    DETAIL rather than by splitting the rule id, so no existing consumer of
    `A6_PV_*_NO_EVIDENCE` changes shape. chip-AGNOSTIC: file states only.
    """
    reports = [p.name for g in report_globs for p in sorted(bdir.glob(g))]
    flag = bdir / flag_name
    if reports:
        state = (f"report(s) {reports} present but carry no parseable "
                 f"verdict")
    elif not flag.is_file():
        state = f"no report and no {flag_name} (the tool has not run)"
    else:
        try:
            text = flag.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            state = f"{flag_name} unreadable ({exc.__class__.__name__})"
        else:
            state = (f"{flag_name} is empty/whitespace — created, not "
                     f"signed off"
                     if not text.strip() else
                     f"{flag_name} carries no verdict line")
    return state


def _flag_drc_count(bdir: Path) -> Optional[int]:
    """The DRC count carried by ``drc_clean.flag`` alone, or None."""
    flag = bdir / "drc_clean.flag"
    if not flag.is_file():
        return None
    try:
        return _parse_drc_count(flag.read_text(encoding="utf-8",
                                               errors="replace"))
    except OSError:
        return None


def _flag_lvs_verdict(bdir: Path) -> Optional[bool]:
    """The LVS verdict carried by ``lvs_match.flag`` alone, or None."""
    flag = bdir / "lvs_match.flag"
    if not flag.is_file():
        return None
    try:
        return _parse_lvs_match(flag.read_text(encoding="utf-8",
                                               errors="replace"))
    except OSError:
        return None


def _witness_disagreements(bdir: Path, rel: str, block: str,
                           drc_count: Optional[int], drc_ev: str,
                           lvs_ok: Optional[bool], lvs_ev: str) -> List[dict]:
    """Two parseable PV witnesses for one block that CONTRADICT each other.

    ADDED 2026-07-28 at the convergence merge, to close a defect class that was
    lost when the A5/A6 dependency cycle was broken. The cycle was real and its
    removal was right: ``analog_a5_layout_check`` used to require
    ``drc_clean.flag`` / ``lvs_match.flag`` — A6's own declared outputs — before
    A5 could pass, while A6 declared ``blocks_on: [A5]``. A5's PV reads were
    withdrawn and A6 became the sole owner of the per-block PV verdict.

    What the withdrawal did NOT preserve: A5 read the FLAGS, while A6 prefers
    the REPORT and only falls back to the flag. A project where the two
    disagree was therefore rejected by old A5 and is accepted by both gates
    today. MEASURED on a block carrying ``drc_clean.flag: "violations: 5"``
    beside ``drc.report: "total violations: 0"``, and ``lvs_match.flag:
    "lvs: mismatch"`` beside ``lvs.report: "netlists match"``, with no waiver::

        test/matrix-63x8-coverage : A5 rc=1  (A5_DRC_NOT_CLEAN + A5_LVS_NOT_MATCH)
        after the cycle fix, before this rule : A5 rc=0 and A6 rc=0, findings []

    That is the same shape ``spare_cell_preservation_check`` gained
    RECORD_ARTEFACT_MISMATCH for in the same change: two artefacts of one run
    disagree and the gate silently believes the clean one. A resumed project
    produces it naturally — a stale flag beside a fresh report.

    NOT WAIVABLE by a step waiver, for the same reason the no-evidence rules
    are not: a waiver accepts a MEASURED risk, and here the measurement itself
    is in dispute — nobody can say which of the two numbers the risk is about.

    NO FALSE ALARM BY CONSTRUCTION: this fires only when BOTH witnesses parse
    to a verdict AND those verdicts differ. A block with one witness, or with a
    flag that carries no verdict line, reaches none of these branches.
    """
    out: List[dict] = []
    flag_drc = _flag_drc_count(bdir)
    if (drc_count is not None and flag_drc is not None
            and drc_ev != "drc_clean.flag"
            and (flag_drc > 0) != (drc_count > 0)):
        out.append({
            "block": block, "rule": "A6_PV_DRC_WITNESS_DISAGREEMENT",
            "rel_path": f"{rel}/{drc_ev}|drc_clean.flag",
            "detail": (f"two parseable DRC witnesses disagree: {drc_ev} "
                       f"reports {drc_count} violation(s) while "
                       f"drc_clean.flag reports {flag_drc}. One of them does "
                       f"not describe this layout, so neither is a sign-off "
                       f"verdict — re-run DRC and refresh both"),
        })
    flag_lvs = _flag_lvs_verdict(bdir)
    if (lvs_ok is not None and flag_lvs is not None
            and lvs_ev != "lvs_match.flag" and flag_lvs != lvs_ok):
        out.append({
            "block": block, "rule": "A6_PV_LVS_WITNESS_DISAGREEMENT",
            "rel_path": f"{rel}/{lvs_ev}|lvs_match.flag",
            "detail": (f"two parseable LVS witnesses disagree: {lvs_ev} "
                       f"reports {'match' if lvs_ok else 'mismatch'} while "
                       f"lvs_match.flag reports "
                       f"{'match' if flag_lvs else 'mismatch'}. One of them "
                       f"does not describe this layout, so neither is a "
                       f"sign-off verdict — re-run LVS and refresh both"),
        })
    return out


def _check_block(project: Path, block: str) -> Tuple[str, List[dict]]:
    """Return (status, findings) where status is PASS or FAIL.
    A block whose directory exists but lacks real DRC/LVS evidence is
    an honest FAIL (never a vacuous PASS)."""
    findings: List[dict] = []
    bdir = _block_dir(project, block)
    if bdir is None:
        findings.append({
            "block": block, "rule": "A6_PV_BLOCK_DIR_MISSING",
            "rel_path": f"analog/{block}/",
            "detail": ("no phase3/analog/<block>/ nor analog/<block>/ "
                       "directory; A5 layout did not run for this block"),
        })
        return "FAIL", findings

    rel = str(bdir.relative_to(project))

    drc_count, drc_ev = _drc_violations(bdir)
    if drc_count is None:
        findings.append({
            "block": block, "rule": "A6_PV_DRC_NO_EVIDENCE",
            "rel_path": f"{rel}/drc.report|drc_clean.flag",
            "detail": ("no parseable DRC result (need drc.report with a "
                       "violation count, or drc_clean.flag carrying an "
                       "explicit `violations: 0` line): "
                       + _evidence_gap(bdir, "drc_clean.flag",
                                       ["drc.report", "*.drc.report",
                                        "*.lyrdb", "drc.rpt", "*.drc"])),
        })
    elif drc_count > 0:
        findings.append({
            "block": block, "rule": "A6_PV_DRC_VIOLATIONS",
            "rel_path": f"{rel}/{drc_ev}",
            "detail": f"DRC reports {drc_count} violation(s) (must be 0)",
        })

    lvs_ok, lvs_ev = _lvs_match(bdir)
    if lvs_ok is None:
        findings.append({
            "block": block, "rule": "A6_PV_LVS_NO_EVIDENCE",
            "rel_path": f"{rel}/lvs.report|comp.json|lvs_match.flag",
            "detail": ("no parseable LVS result (need lvs.report / "
                       "comp.json with a match verdict, or lvs_match.flag "
                       "carrying an explicit `match` line): "
                       + _evidence_gap(bdir, "lvs_match.flag",
                                       ["lvs.report", "*.lvs.report",
                                        "lvs.rpt", "comp.out", "*.lvs",
                                        "comp.json"])),
        })
    elif lvs_ok is False:
        findings.append({
            "block": block, "rule": "A6_PV_LVS_MISMATCH",
            "rel_path": f"{rel}/{lvs_ev}",
            "detail": "LVS reports a mismatch (must be a match)",
        })

    findings.extend(_witness_disagreements(
        bdir, rel, block, drc_count, drc_ev, lvs_ok, lvs_ev))

    return ("FAIL" if findings else "PASS"), findings


# ---------------------------------------------------------------------------
# waivers
# ---------------------------------------------------------------------------


def _load_waivers(project: Path) -> list:
    for p in (project / "phase3" / "analog" / "waivers.json",
              project / "analog" / "waivers.json",
              project / "waivers.json"):
        if p.is_file():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            return d.get("waived_steps") or d.get("analog_waivers") or []
    return []


def _step_waived(project: Path, step_label: str):
    for w in _load_waivers(project):
        if not isinstance(w, dict):
            continue
        sid = str(w.get("id", "") or w.get("step", "")).strip()
        ticket = w.get("ticket", "")
        if sid == step_label or (step_label and step_label in str(ticket)):
            return w
    return None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _write(json_path, report) -> None:
    if not json_path:
        return
    out = Path(json_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog=_GATE_NAME, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project_dir")
    parser.add_argument("--json", default=None)
    parser.add_argument("--block", default=None,
                        help="restrict check to a single block (used by "
                             "analog_one_shot_runner)")
    parser.add_argument("--step-label", default=_GATE_LABEL)
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}",
              file=sys.stderr)
        return 2

    blocks_all = _load_block_list(project)

    # SKIP (rc=2) only when genuinely no analog blocks exist.
    if blocks_all is None or (not blocks_all and not args.block):
        report = {
            "gate": _GATE_NAME,
            "verdict": "SKIP",
            "step_label": args.step_label,
            "reason": ("no analog blocks declared (block list absent or "
                       "empty); per-block PV non-applicable"),
            "blocks_checked": 0,
            "blocks_pass": 0,
            "blocks_fail": 0,
            "findings": [],
        }
        _write(args.json, report)
        print(f"=== {_GATE_NAME} ({project.name}) ===")
        print(f"  verdict: SKIP (no analog blocks)")
        return 2

    # ORGANIC #676 — class-N/A skip (defence-in-depth). When the IC is
    # positively classified non-analog and every declared block is a
    # low_confidence phantom keyword hit (e.g. a "POR" digital-reset token
    # scraped into a phantom analog block on a pure-digital SoC), SKIP (rc=2)
    # instead of FAILing per-block PV. §4.05 no-leak: a real analog IC or a
    # confident (spec-backed) block never reaches this skip and is still gated.
    if not args.block:
        try:
            import _analog_a_check_common as _aac
            if _aac.analog_class_is_na(project):
                report = {
                    "gate": _GATE_NAME,
                    "verdict": "SKIP",
                    "step_label": args.step_label,
                    "reason": ("IC classified non-analog "
                               "(analog_applicable=false / generic_full_stack) "
                               "and all declared blocks are low_confidence "
                               "phantom keyword hits — per-block PV N/A "
                               "(ORGANIC #676)"),
                    "blocks_checked": 0,
                    "blocks_pass": 0,
                    "blocks_fail": 0,
                    "findings": [],
                }
                _write(args.json, report)
                print(f"=== {_GATE_NAME} ({project.name}) ===")
                print(f"  verdict: SKIP (digital class N/A, #676)")
                return 2
        except Exception:
            pass

    blocks = [args.block] if args.block else blocks_all

    # Step-level waiver (evidence + ticket) short-circuits to WAIVED.
    waiver = _step_waived(project, args.step_label)

    findings: List[dict] = []
    blocks_pass = 0
    for block in blocks:
        status, fs = _check_block(project, block)
        if status == "PASS":
            blocks_pass += 1
        else:
            findings.extend(fs)

    # THE RECORD, not a rule — see the module docstring. Read from the same
    # per-block artefact A5 holds to its rules, so the two gates cannot
    # disagree about one file, and merged into the summary on every path
    # below (they all splat `**summary`).
    import _analog_layout_matching as _lm
    disclosures = {b: _lm.read_disclosure(project / "phase3" / "analog" / b, b)
                   for b in blocks}

    summary = {
        "blocks_checked": len(blocks),
        "blocks_pass": blocks_pass,
        "blocks_fail": len({f["block"] for f in findings}),
        **_lm.summarise(disclosures),
    }

    # A waiver covers a MEASURED defect, never an absent measurement.
    unwaivable = [f for f in findings
                  if f.get("rule") in _NON_WAIVABLE_RULES]
    waivable = [f for f in findings
                if f.get("rule") not in _NON_WAIVABLE_RULES]

    if findings and waiver and unwaivable:
        verdict, rc = "FAIL", 1
        report = {
            "gate": _GATE_NAME, "verdict": verdict,
            "step_label": args.step_label, "waiver": waiver,
            **summary,
            "findings": unwaivable,
            "waiver_cannot_cover": [
                {"block": f.get("block"), "rule": f.get("rule")}
                for f in unwaivable],
            "waiver_scope_note": (
                f"waiver={waiver.get('ticket', '?')} suppressed "
                f"{len(waivable)} measured defect(s) but CANNOT cover "
                f"{len(unwaivable)} finding(s) that report no measurement "
                f"at all: a waiver accepts a known risk, and there is no "
                f"risk to accept where the tool never produced a result. "
                f"Run DRC/LVS for the named block(s), then waive what it "
                f"actually reports."),
            "suppressed_findings": waivable,
        }
        # The live findings are what the operator must act on.
        findings = unwaivable
    elif findings and waiver:
        verdict, rc = "WAIVED", 0
        report = {
            "gate": _GATE_NAME, "verdict": verdict,
            "step_label": args.step_label, "waiver": waiver,
            **summary,
            "findings": [{
                "severity": "WAIVED", "rule": "STEP_WAIVED",
                "message": (f"waiver={waiver.get('ticket', '?')}: "
                            f"{waiver.get('reason', '?')}"),
            }],
            "suppressed_findings": findings,
        }
    elif findings:
        verdict, rc = "FAIL", 1
        report = {
            "gate": _GATE_NAME, "verdict": verdict,
            "step_label": args.step_label, "waiver": None,
            **summary, "findings": findings,
        }
    else:
        verdict, rc = "PASS", 0
        report = {
            "gate": _GATE_NAME, "verdict": verdict,
            "step_label": args.step_label, "waiver": None,
            **summary, "findings": [],
        }

    _write(args.json, report)
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict} "
          f"({blocks_pass}/{len(blocks)} block(s) DRC-0 + LVS-match)")
    if verdict == "FAIL":
        for f in findings[:8]:
            print(f"  [{f.get('block', '?')}] {f.get('rule', '?')}: "
                  f"{f.get('detail', '')}", file=sys.stderr)
        if len(findings) > 8:
            print(f"  ... and {len(findings) - 8} more", file=sys.stderr)
    if waiver:
        print(f"  waiver:  {waiver.get('ticket', '?')}")
    # LAST, and on every path — same contract as `structure_only_disclosure`.
    _lm.matching_disclosure(_GATE_NAME, disclosures)
    return rc


if __name__ == "__main__":
    sys.exit(main())
