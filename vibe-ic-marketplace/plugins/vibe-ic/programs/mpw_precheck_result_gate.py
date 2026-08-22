#!/usr/bin/env python3
"""v1.2.76 — mpw_precheck RESULT parser gate (TAPEOUT-SIGNOFF P0#2, parser half).

RETIRED SHUTTLE (vibe-ic#1744) — READ THIS BEFORE TRUSTING A VERDICT FROM HERE
=============================================================================
The counterparty this program addresses, the Efabless/chipIgnite open-MPW
shuttle, CEASED OPERATING IN 2025. It no longer accepts submissions and it no
longer refuses them. Nothing below is broken; it is pointed at a party that
stopped answering.

That distinction is the whole point of keeping this file. A gate we wrote can
be made to pass by editing it; an external refusal cannot. This was the ONE
interface in the tree whose verdict was not ultimately ours, and it is now
aimed at nothing — so a run that produces no evidence here means
NOT DETERMINED, permanently, and never "nothing to worry about".

The LIVE external refusal is `tapeout_readiness_check.py`, which wraps the
shuttle operator's own tool for the currently-running open-MPW path. Ask that
one for a submittability verdict. This file is kept, not deleted, so the
retirement is on the record rather than looking like an orphan.

Doctrine: the Efabless/chipIgnite sky130 open-MPW shuttle gate is
`efabless/mpw_precheck` — a Docker suite that runs a fixed ladder of
license / makefile / default / documentation / consistency / gpio_defines /
XOR / Magic-DRC / KLayout-FEOL-BEOL-offgrid / LVS / oeb checks and prints
per-check `... Check Passed` / `... Check Failed` lines plus a final
`All Checks Passed!` (or a `N Check(s) Failed`) summary. Today the plugin's
`caravel_integration_runner.py` only emits the Docker *command_hint* and
returns NOT_RUN — NO program CONSUMES the precheck output, so the plugin can
never assert a shuttle-submittable verdict.

This program is the deterministic PARSER GATE: given a COMPLETED mpw_precheck
run directory (its top-level `*.log`, its `logs/` and per-check subdirs), it
scrapes each stage's pass/fail from the real log conventions and rolls them up:

  * PASS               — every REQUIRED check has positive PASSED evidence and
                         none failed.
  * FAIL               — one or more required checks FAILED (they are named), or
                         the run's own summary line reports failure.
  * INCOMPLETE         — the run is present but at least one required check
                         produced NO pass/fail evidence (it never ran / was cut
                         short). NOT a pass.
  * SKIPPED_CONDITION  — the run directory is absent/empty, or carries no usable
                         precheck evidence at all. NOT a pass.

§4.05 (absent evidence NEVER yields PASS): a PASS is emitted ONLY when EVERY
required check carries an explicit machine-readable PASSED line. A missing run,
an empty directory, or a check that simply never logged a verdict can only ever
produce SKIPPED_CONDITION / INCOMPLETE — never a fabricated PASS.

Chip-AGNOSTIC: pure log-parse. No chip name, no project literal appears in any
matching rule. Robust to the OLDER (`<Check> Check Passed`, top-level `*.log`)
and NEWER (`{{SUCCESS}} <Check> Check Passed`, `logs/` + per-check subdirs)
mpw_precheck log layouts.

The live Docker DRIVER (actually invoking `mpw_precheck.py`) is a SEPARATE
piece; this program is the offline, deterministic consumer of its output.

CLI:
    python3 mpw_precheck_result_gate.py <rundir> [--required-check consistency ...]
                                        [--project <label>] [--out-json out.json]
Exit 0 = PASS. Exit 1 = FAIL / INCOMPLETE / SKIPPED_CONDITION (hard gate).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


# The TOOL half only. The release half is never restated here — #800: a
# version literal is correct for exactly the release it was typed in.
ATTRIBUTION = "mpw_precheck_result_gate"

# ---------------------------------------------------------------------------
# Canonical mpw_precheck stage ladder.
#
# Each entry: canonical key -> tuple of name-phrase variants that appear inside
# a real precheck log's "<name> Check Passed/Failed" line. The variants are
# normalised (lower-cased, punctuation flattened to single spaces) before the
# substring test, so both `gpio_defines`, `GPIO-Defines` and `GPIO Defines`
# resolve to the same stage. This mirrors the check list the plugin already
# models in `caravel_integration_runner.step_c1_run_precheck` (the first seven)
# extended with the layout checks the full shuttle precheck runs.
#
# Version-drift note: newer mpw_precheck releases split the KLayout deck into
# more sub-checks (met_min_ca_density, zeroarea, fom_density, ...). Those are
# NOT in the default required set to avoid a brittle over-commitment; a caller
# that wants them gated passes them via --required-check. Any stage seen in a
# log is always reported, required or not.
# ---------------------------------------------------------------------------
PRECHECK_STAGES: Dict[str, Tuple[str, ...]] = {
    "license":         ("license",),
    "makefile":        ("makefile",),
    "default":         ("default",),
    "documentation":   ("documentation",),
    "consistency":     ("consistency",),
    "gpio_defines":    ("gpio defines", "gpio_defines", "gpio-defines"),
    "xor":             ("xor",),
    "magic_drc":       ("magic drc", "magic_drc", "magic-drc"),
    "klayout_feol":    ("klayout feol", "klayout_feol", "feol"),
    "klayout_beol":    ("klayout beol", "klayout_beol", "beol"),
    "klayout_offgrid": ("klayout offgrid", "klayout_offgrid", "offgrid"),
    "lvs":             ("lvs",),
    "oeb":             ("oeb",),
}

# Human labels for the report.
STAGE_LABELS: Dict[str, str] = {
    "license": "License", "makefile": "Makefile", "default": "Default",
    "documentation": "Documentation", "consistency": "Consistency",
    "gpio_defines": "GPIO-Defines", "xor": "XOR", "magic_drc": "Magic DRC",
    "klayout_feol": "KLayout FEOL", "klayout_beol": "KLayout BEOL",
    "klayout_offgrid": "KLayout Offgrid", "lvs": "LVS", "oeb": "OEB",
}

# The full shuttle-submittable required set (the honest default). A precheck run
# that omits any of these is INCOMPLETE, not PASS.
DEFAULT_REQUIRED: Tuple[str, ...] = tuple(PRECHECK_STAGES.keys())

# Longest variants first so the most specific name wins the stage assignment
# (e.g. "klayout feol" beats the bare "feol").
_VARIANT_INDEX: List[Tuple[str, str]] = sorted(
    ((v, key) for key, variants in PRECHECK_STAGES.items() for v in variants),
    key=lambda pair: len(pair[0]), reverse=True,
)

# Per-check status lines. `check(s)?` / `check(s)` are both tolerated. The lead
# capture is restricted to name-like characters so log braces (`{{SUCCESS}}`)
# and sentence prefixes are skipped rather than swallowed.
_NAME = r"([A-Za-z0-9 _/\-]+?)"
_PASS_RE = re.compile(_NAME + r"\s+check(?:\(s\)|s)?\s+passed\b", re.IGNORECASE)
_FAIL_RE = re.compile(_NAME + r"\s+check(?:\(s\)|s)?\s+failed\b", re.IGNORECASE)

# Final run summary.
_SUMMARY_PASS_RE = re.compile(r"all\s+checks\s+passed", re.IGNORECASE)
_SUMMARY_FAIL_RE = re.compile(
    r"\b\d+\s+check(?:\(s\)|s)?\s+failed", re.IGNORECASE)

# Bound each log read so a pathological multi-hundred-MB tool dump can't blow up.
_MAX_LOG_BYTES = 8 * 1024 * 1024


@dataclass
class CheckResult:
    check_id: str          # canonical stage key
    name: str              # human label
    verdict: str           # PASS / FAIL / MISSING
    source: Optional[str] = None   # relative path of the log the evidence came from
    evidence: str = ""     # the matched log line (trimmed)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PrecheckGateReport:
    rundir: str
    project: str
    overall_verdict: str          # PASS / FAIL / INCOMPLETE / SKIPPED_CONDITION
    required_checks: List[str]
    checks: List[CheckResult] = field(default_factory=list)
    failed_checks: List[str] = field(default_factory=list)
    missing_checks: List[str] = field(default_factory=list)
    summary_line: Optional[str] = None
    logs_scanned: List[str] = field(default_factory=list)
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rundir": self.rundir,
            "project": self.project,
            "overall_verdict": self.overall_verdict,
            "required_checks": self.required_checks,
            "checks": [c.as_dict() for c in self.checks],
            "failed_checks": self.failed_checks,
            "missing_checks": self.missing_checks,
            "summary_line": self.summary_line,
            "logs_scanned": self.logs_scanned,
            "notes": self.notes,
            "emitted_by": _pmd.emitted_by(ATTRIBUTION),
        }


# ---------------------------------------------------------------------------
# Log collection & parsing
# ---------------------------------------------------------------------------
def collect_log_texts(rundir: Path) -> List[Tuple[Path, str]]:
    """Return (path, text) for every `*.log` under `rundir` (recursively).

    rglob('*.log') covers ALL layouts named in the task: the top-level
    `<rundir>/*.log`, the newer `<rundir>/logs/*.log` + nested per-check subdir
    logs, and the older `<rundir>/*/*.log`. Non-`.log` tool dumps are ignored;
    the authoritative pass/fail lines are always emitted to `.log` files by
    mpw_precheck's logger. Bounded read per file.
    """
    out: List[Tuple[Path, str]] = []
    if not rundir.exists() or not rundir.is_dir():
        return out
    for p in sorted(rundir.rglob("*.log")):
        if not p.is_file():
            continue
        try:
            if p.stat().st_size > _MAX_LOG_BYTES:
                with p.open("r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read(_MAX_LOG_BYTES)
            else:
                text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.append((p, text))
    return out


def _normalise(phrase: str) -> str:
    """Lower-case and flatten any non-alphanumeric run to a single space."""
    return re.sub(r"[^a-z0-9]+", " ", phrase.lower()).strip()


def _map_phrase_to_stage(phrase: str) -> Optional[str]:
    """Resolve a captured '<name> check' phrase to a canonical stage key.

    Most-specific (longest) variant wins. Returns None for phrases that match no
    stage (e.g. the `N Check(s) Failed` summary, or a raw-tool 'drc' fragment) so
    they can never masquerade as a stage verdict.
    """
    norm = " " + _normalise(phrase) + " "
    for variant, key in _VARIANT_INDEX:
        if (" " + variant + " ") in norm:
            return key
    return None


def parse_check_statuses(
    texts: List[Tuple[Path, str]], rundir: Path
) -> Dict[str, CheckResult]:
    """Scrape per-stage PASS/FAIL across every log.

    FAIL is sticky: if ANY log line reports a stage failed, that stage is FAIL
    even if another line reports it passed (never hide a failure — §4.05). A
    stage with only PASSED evidence is PASS. Stages with no evidence are simply
    absent from the returned dict.
    """
    status: Dict[str, str] = {}
    source: Dict[str, str] = {}
    evidence: Dict[str, str] = {}

    def _record(stage: str, verdict: str, path: Path, line: str) -> None:
        prev = status.get(stage)
        # FAIL is sticky and dominates.
        if prev == "FAIL" and verdict != "FAIL":
            return
        if prev is None or verdict == "FAIL":
            status[stage] = verdict
            try:
                source[stage] = str(path.relative_to(rundir))
            except ValueError:
                source[stage] = str(path)
            evidence[stage] = line.strip()[:200]

    for path, text in texts:
        for line in text.splitlines():
            for m in _FAIL_RE.finditer(line):
                stage = _map_phrase_to_stage(m.group(1))
                if stage:
                    _record(stage, "FAIL", path, line)
            for m in _PASS_RE.finditer(line):
                stage = _map_phrase_to_stage(m.group(1))
                if stage:
                    _record(stage, "PASS", path, line)

    return {
        stage: CheckResult(
            check_id=stage,
            name=STAGE_LABELS.get(stage, stage),
            verdict=status[stage],
            source=source.get(stage),
            evidence=evidence.get(stage, ""),
        )
        for stage in status
    }


def parse_summary(texts: List[Tuple[Path, str]]) -> Tuple[Optional[str], Optional[str]]:
    """Return (summary_verdict, summary_line).

    summary_verdict is 'PASS' if a final `All Checks Passed` line exists, 'FAIL'
    if a `N Check(s) Failed` summary exists, else None. A FAIL summary dominates
    a PASS summary (a run that both passed early and failed later is a FAIL).
    """
    summary_verdict: Optional[str] = None
    summary_line: Optional[str] = None
    for _path, text in texts:
        for line in text.splitlines():
            if _SUMMARY_FAIL_RE.search(line):
                return "FAIL", line.strip()[:200]
            if summary_verdict is None and _SUMMARY_PASS_RE.search(line):
                summary_verdict = "PASS"
                summary_line = line.strip()[:200]
    return summary_verdict, summary_line


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def evaluate(
    rundir: Path,
    required: Optional[List[str]] = None,
    project: str = "",
) -> PrecheckGateReport:
    """Parse `rundir` and roll up the aggregate gate verdict."""
    req = list(required) if required else list(DEFAULT_REQUIRED)

    if not rundir.exists() or not rundir.is_dir():
        return PrecheckGateReport(
            rundir=str(rundir), project=project,
            overall_verdict="SKIPPED_CONDITION",
            required_checks=req,
            missing_checks=list(req),
            notes="mpw_precheck run directory is absent — no precheck was run. "
                  "§4.05: absent evidence cannot be a PASS.",
        )

    texts = collect_log_texts(rundir)
    logs_scanned: List[str] = []
    for p, _t in texts:
        try:
            logs_scanned.append(str(p.relative_to(rundir)))
        except ValueError:
            logs_scanned.append(str(p))

    if not texts:
        return PrecheckGateReport(
            rundir=str(rundir), project=project,
            overall_verdict="SKIPPED_CONDITION",
            required_checks=req,
            missing_checks=list(req),
            notes="run directory contains no mpw_precheck *.log files — no "
                  "usable precheck evidence. §4.05: cannot PASS.",
        )

    found = parse_check_statuses(texts, rundir)
    summary_verdict, summary_line = parse_summary(texts)

    if not found and summary_verdict is None:
        return PrecheckGateReport(
            rundir=str(rundir), project=project,
            overall_verdict="SKIPPED_CONDITION",
            required_checks=req,
            missing_checks=list(req),
            summary_line=summary_line,
            logs_scanned=logs_scanned,
            notes="logs present but no parseable per-check verdict or summary — "
                  "no usable precheck evidence. §4.05: cannot PASS.",
        )

    # Assemble the ordered check list: required stages first (in canonical
    # order), then any extra stages seen in the logs but not required.
    checks: List[CheckResult] = []
    failed: List[str] = []
    missing: List[str] = []
    for stage in req:
        if stage in found:
            cr = found[stage]
            checks.append(cr)
            if cr.verdict == "FAIL":
                failed.append(stage)
        else:
            checks.append(CheckResult(
                check_id=stage, name=STAGE_LABELS.get(stage, stage),
                verdict="MISSING"))
            missing.append(stage)
    for stage, cr in found.items():
        if stage not in req:
            checks.append(cr)  # reported for transparency, not gated
            if cr.verdict == "FAIL" and stage not in failed:
                # An extra (non-required) failing stage is still a real failure.
                failed.append(stage)

    # Verdict roll-up (§4.05 ordering: any FAIL evidence dominates; a missing
    # required check can never be promoted to PASS).
    notes = ""
    if failed:
        verdict = "FAIL"
        notes = "required check(s) failed: " + ", ".join(sorted(failed))
    elif summary_verdict == "FAIL":
        verdict = "FAIL"
        notes = ("run summary reports failure though no individual failing "
                 "check line was attributable — treated as FAIL, not PASS.")
    elif missing:
        verdict = "INCOMPLETE"
        notes = ("required check(s) never produced a pass/fail verdict: "
                 + ", ".join(sorted(missing))
                 + ". §4.05: a check that never ran is not a PASS.")
    else:
        verdict = "PASS"
        notes = ("every required check passed"
                 + (" (corroborated by 'All Checks Passed' summary)"
                    if summary_verdict == "PASS" else ""))

    return PrecheckGateReport(
        rundir=str(rundir), project=project,
        overall_verdict=verdict,
        required_checks=req,
        checks=checks,
        failed_checks=sorted(failed),
        missing_checks=sorted(missing),
        summary_line=summary_line,
        logs_scanned=logs_scanned,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="mpw_precheck RESULT parser gate — consume a completed "
                    "efabless/mpw_precheck run dir and emit a hard pass/fail "
                    "shuttle-submittable verdict (§4.05: absent → never PASS).")
    p.add_argument("rundir", type=Path,
                   help="mpw_precheck run/output directory (its *.log, logs/ "
                        "and per-check subdirs).")
    p.add_argument("--required-check", action="append", default=[],
                   dest="required_checks", metavar="CHECK",
                   help="Override the required check set (repeatable). Default: "
                        "the full shuttle ladder. Names are canonical keys, e.g. "
                        "consistency, xor, magic_drc, lvs, oeb.")
    p.add_argument("--project", default="",
                   help="Optional label for the report (not used in any "
                        "matching rule — the gate stays chip-AGNOSTIC).")
    p.add_argument("--out-json", type=Path,
                   help="Also write the verdict JSON to this path.")
    args = p.parse_args(argv)

    rep = evaluate(
        args.rundir,
        required=args.required_checks or None,
        project=args.project,
    )
    payload = rep.as_dict()
    text = json.dumps(payload, indent=2)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(text, encoding="utf-8")
    print(text)
    return 0 if rep.overall_verdict == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
