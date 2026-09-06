"""v0.1.50 — rtl-review skill backing aggregator (Pattern-B → program).

The PoC of the v0.1.50 doctrine sweep (`SKILLS_PROGRAM_TRIAGE.md`): the
existing `skills/rtl-review/SKILL.md` enumerates a deterministic
6-category checklist + a 0-10 scoring rubric and asks Claude to "go
through every category" by reading the file. This is the doctrine
violation — the rules are in prompt-space, not tool-space.

This program codifies the same rubric as a deterministic aggregator:

  1. Synthesis hazards (ERROR)        ← rtl_hygiene_lint (existing)
                                        + uninit registered output rule
  2. Reset / clock-domain hygiene     ← reset_discipline_check (existing)
                                        +rtl_precheck_gate aggregate
  3. Style / readability (WARN/INFO)  ← rtl_hygiene_lint severity rules
  4. Correctness smells               ← rtl_hygiene_lint
                                        + rtl_precheck_gate sub-checks
  5. Parameter / width issues         ← rtl_hygiene_lint
  6. Port fidelity                    ← spec_rtl_port_fidelity_check

Then the 0-10 scoring rubric in skills/rtl-review/SKILL.md becomes a
function:

  errors == 0 && warns == 0          → 10 (production-ready)
  errors == 0 && warns ≤ 3 (INFO)    → 8-9
  errors == 0 && 1 ≤ warns ≤ 6       → 6-7
  errors == 1 || warns ≥ 7           → 4-5
  errors == 2..N                     → 2-3
  errors ≥ N or not synthesizable    → 0-1

Doctrine: program runs first, returns the structured verdict. The skill
becomes a thin Pattern-A wrapper: "run rtl_review_aggregate, narrate
its residuals, **refuse to claim a higher score than the program
returns**." Claude is the backstop for residual prose, not the rule
applicator.

Unit tests: `programs/tests/test_rtl_review_aggregate.py`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


# ---------------------------------------------------------------------------
# Category mapping — which finding-key from which sub-program goes into
# which of the 6 rtl-review categories. This is the ONE place the
# category taxonomy is encoded; the skill's prose is now redundant
# (and will be compressed to a Pattern-A wrapper).
# ---------------------------------------------------------------------------
CATEGORY_NAMES = (
    "synthesis_hazards",          # § 1 — ERROR
    "reset_clock_hygiene",        # § 2 — ERROR/WARN
    "style_readability",          # § 3 — WARN/INFO
    "correctness_smells",         # § 4 — WARN
    "param_width",                # § 5 — WARN
    "port_fidelity",              # § 6 — ERROR/WARN
)

# Which rtl_hygiene_lint rule-id maps to which category. The keys are
# the canonical rule-id strings emitted in the program's JSON output.
HYGIENE_RULE_CATEGORY: Dict[str, str] = {
    # § 1 synthesis hazards
    "latch_inferred": "synthesis_hazards",
    "multiple_drivers": "synthesis_hazards",
    "sensitivity_incomplete": "synthesis_hazards",
    "initial_block_outside_tb": "synthesis_hazards",
    "non_synth_construct": "synthesis_hazards",
    "comb_feedback": "synthesis_hazards",
    "uninit_registered_output": "synthesis_hazards",
    # § 2 reset/clock hygiene (also fed by reset_discipline_check separately)
    "flop_no_reset": "reset_clock_hygiene",
    "mixed_sync_async_reset": "reset_clock_hygiene",
    "cross_clock_no_synchronizer": "reset_clock_hygiene",
    "gated_clock_no_icg": "reset_clock_hygiene",
    # § 3 style / readability
    "magic_number": "style_readability",
    "no_default_nettype": "style_readability",
    "tabs_vs_spaces": "style_readability",
    "long_module": "style_readability",
    "verbose_name": "style_readability",
    # § 4 correctness smells
    "blocking_in_seq": "correctness_smells",
    "nonblocking_in_comb": "correctness_smells",
    "case_not_full": "correctness_smells",
    "case_not_unique": "correctness_smells",
    "x_in_assignment": "correctness_smells",
    # § 5 parameter / width
    "width_mismatch": "param_width",
    "param_redef_unsafe": "param_width",
    "implicit_int_width": "param_width",
    # § 6 port fidelity (also fed by spec_rtl_port_fidelity_check)
    "port_dir_mismatch": "port_fidelity",
    "port_width_mismatch": "port_fidelity",
    "missing_port": "port_fidelity",
    "extra_port": "port_fidelity",
}


@dataclass
class Finding:
    """One finding in the aggregated report."""
    category: str
    severity: str            # ERROR | WARN | INFO
    rule_id: str
    file: str
    line: int
    message: str
    source: str              # which sub-program emitted this

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CategorySummary:
    """Per-category aggregated counts + sample findings."""
    name: str
    errors: int = 0
    warns: int = 0
    infos: int = 0
    findings: List[Finding] = field(default_factory=list)

    def add(self, f: Finding) -> None:
        self.findings.append(f)
        if f.severity == "ERROR":
            self.errors += 1
        elif f.severity == "WARN":
            self.warns += 1
        else:
            self.infos += 1


# ---------------------------------------------------------------------------
# Scoring rubric — verbatim from skills/rtl-review/SKILL.md, codified.
# The rubric in the skill was 6 prose bullets; this is the deterministic
# implementation. Pytest pins every boundary.
# ---------------------------------------------------------------------------
def compute_score(total_errors: int, total_warns: int,
                  total_infos: int,
                  is_synthesizable: bool = True) -> int:
    """Compute the 0-10 rtl-review score.

    The skill's rubric:
      10:  no errors, no warnings, production-ready
      8-9: clean code with minor info items
      6-7: some warnings, no blocking errors
      4-5: multiple warnings or one error
      2-3: multiple errors, significant rework needed
      0-1: not synthesizable, major structural issues

    "Multiple" here means >= 2 (consistent with the rubric's language).
    """
    if not is_synthesizable:
        return 0
    if total_errors == 0 and total_warns == 0 and total_infos == 0:
        return 10
    if total_errors == 0 and total_warns == 0 and 1 <= total_infos <= 5:
        return 9
    if total_errors == 0 and total_warns == 0:
        return 8
    if total_errors == 0 and total_warns == 1:
        return 7
    if total_errors == 0 and 2 <= total_warns <= 4:
        return 6
    if total_errors == 1:
        return 5
    if 2 <= total_errors <= 3:
        return 3
    if total_errors >= 4:
        return 2
    # Fallback: many warnings, no errors
    if total_warns >= 5:
        return 4
    return 5  # conservative


def score_to_verdict(score: int) -> str:
    """Map numeric score to PASS / WARN / FAIL verdict."""
    if score >= 8:
        return "PASS"
    if score >= 6:
        return "WARN"
    return "FAIL"


def severity_band(score: int) -> str:
    """Human label for the score band, matching the skill's rubric."""
    bands = {
        10: "production-ready",
        9: "clean with minor info",
        8: "clean with minor info",
        7: "some warnings, no blocking errors",
        6: "some warnings, no blocking errors",
        5: "one error or multiple warnings",
        4: "multiple warnings",
        3: "multiple errors, rework needed",
        2: "multiple errors, rework needed",
        1: "not synthesizable",
        0: "not synthesizable",
    }
    return bands.get(score, "unknown")


# ---------------------------------------------------------------------------
# Sub-program invocation. Each helper SHOULD return a list of Finding —
# either by parsing the sub-program's --json output, or, on missing
# program / parse error, returning an empty list and surfacing a
# warning string. NEVER silently swallow.
# ---------------------------------------------------------------------------
PROGRAMS_DIR = Path(__file__).resolve().parent


def _run_program_json(program_name: str, args: List[str],
                       json_out: Path) -> Tuple[int, str, str]:
    """Run a sub-program with --json and capture stdout/stderr.

    Returns (exit_code, stdout, stderr). Does not raise.
    """
    cmd = [sys.executable, str(PROGRAMS_DIR / program_name)] + args + [
        "--json", str(json_out)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, check=False)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout running {program_name}"
    except FileNotFoundError:
        return 127, "", f"program not found: {program_name}"


class ProducerOutputError(RuntimeError):
    """A sub-program's output could not be consumed.

    ISSUE #2036. Every loader here used to answer three very different
    questions with the same value — an empty list:

      * the producer ran and legitimately found nothing;
      * the producer's JSON file was absent;
      * the JSON parsed but was a shape this consumer does not understand.

    "I could not read this" is not "there was nothing to report". Collapsing
    them turns a broken tool chain into a clean review with a high score, which
    is the one failure mode this repo refuses everywhere. The unreadable cases
    now raise, and the CLI reports the refusal by name and exits non-zero.
    """


#: Exit codes a producer may return while still having written a usable report.
#: `rtl_hygiene_lint` and `reset_discipline_check` return 1 when they FOUND
#: something and `rtl_precheck_gate` returns 1 when a verdict failed — those are
#: results. Anything else (2 = UNDETERMINED/usage, 124 = timeout, 127 = missing)
#: means no verdict was reached, and no verdict is not a clean file.
_PRODUCER_RESULT_RCS = (0, 1)


def _read_producer_json(json_path: Path, program: str, rc: Optional[int] = None,
                        stderr: str = "") -> Any:
    """Read a sub-program's `--json` artifact, or refuse loudly.

    Never returns a default. Raises `ProducerOutputError` naming the program and
    the reason, so the difference between "clean" and "unreadable" survives.
    """
    if rc is not None and rc not in _PRODUCER_RESULT_RCS:
        tail = (stderr or "").strip().splitlines()
        detail = f": {tail[-1]}" if tail else ""
        raise ProducerOutputError(
            f"{program} exited {rc} without reaching a verdict{detail}")
    if not json_path.exists():
        raise ProducerOutputError(
            f"{program} wrote no JSON at {json_path} — its findings are "
            f"unknown, not empty")
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        raise ProducerOutputError(
            f"{program} JSON at {json_path} is unparseable: {exc}") from exc


def _finding_records(data: Any, program: str, key: str = "findings") -> List[dict]:
    """Normalize a producer's payload to a list of finding records.

    MEASURED against the producers themselves, not against a doc:
    `rtl_hygiene_lint.py --json` writes `json.dumps([asdict(f) for f in ...])`
    and `reset_discipline_check.py --json` does the same — a BARE ARRAY, `[]`
    for a clean file. The object envelope `{"findings": [...]}` is accepted as
    well so a producer that grows a header does not break this consumer. Any
    OTHER shape is refused by name rather than read as empty.
    """
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict) and isinstance(data.get(key), list):
        records = data[key]
    else:
        raise ProducerOutputError(
            f"{program} JSON is a {type(data).__name__}, not a list of "
            f"findings nor an object with a '{key}' list — refusing to read it "
            f"as an empty result")
    bad = [r for r in records if not isinstance(r, dict)]
    if bad:
        raise ProducerOutputError(
            f"{program} JSON contains {len(bad)} non-object finding record(s) "
            f"(first: {bad[0]!r}) — refusing to read them as an empty result")
    return records


def _load_hygiene_findings(json_path: Path, rc: Optional[int] = None,
                           stderr: str = "") -> List[Finding]:
    """Parse `rtl_hygiene_lint --json` output into a Finding list.

    The producer emits a BARE ARRAY (`[]` for a clean file). Reading it as
    `data.get("findings", [])` raised `AttributeError: 'list' object has no
    attribute 'get'` and took the whole aggregate down with exit 1 and no report
    at all — on an ordinary clean flip-flop (issue #2036).
    """
    data = _read_producer_json(json_path, "rtl_hygiene_lint", rc, stderr)
    out: List[Finding] = []
    for item in _finding_records(data, "rtl_hygiene_lint"):
        rule_id = item.get("rule", "unknown")
        category = HYGIENE_RULE_CATEGORY.get(rule_id, "style_readability")
        out.append(Finding(
            category=category,
            severity=item.get("severity", "INFO"),
            rule_id=rule_id,
            file=item.get("file", ""),
            line=item.get("line", 0),
            message=item.get("message", ""),
            source="rtl_hygiene_lint",
        ))
    return out


def _load_reset_findings(json_path: Path, rc: Optional[int] = None,
                         stderr: str = "") -> List[Finding]:
    """Parse `reset_discipline_check --json` output.

    Same producer shape as the hygiene lint — a bare array — and so the same
    latent crash; it was simply never reached, because the hygiene loader threw
    first.
    """
    data = _read_producer_json(json_path, "reset_discipline_check", rc, stderr)
    out: List[Finding] = []
    for item in _finding_records(data, "reset_discipline_check"):
        out.append(Finding(
            category="reset_clock_hygiene",
            severity=item.get("severity", "WARN"),
            rule_id=item.get("rule", "reset"),
            file=item.get("file", ""),
            line=item.get("line", 0),
            message=item.get("message", ""),
            source="reset_discipline_check",
        ))
    return out


def _load_precheck_findings(json_path: Path, rc: Optional[int] = None,
                            stderr: str = "") -> List[Finding]:
    """Parse `rtl_precheck_gate --json` output.

    THE ENVELOPE THIS USED TO ASSUME NEVER EXISTED. The comment here claimed
    `{auditor: {findings: [...], verdict: ...}}` and the code called
    `data.get("auditors", {}).items()`. `rtl_precheck_gate.run_gate` in fact
    emits `"auditors": [r.as_dict() for r in results]` — a LIST of
    `AuditorResult` records (`name` / `passed` / `exit_code` / `skipped` /
    `skip_reason` / `stdout_tail` / `stderr_tail`), with no per-finding array at
    all. `.items()` on a list is the same `AttributeError` class as #2036; it
    was simply never reached, because the hygiene loader raised first.

    One Finding is emitted per FAILED auditor, and a SKIPPED auditor becomes an
    INFO — a check that did not run is reported, never counted as a pass.
    """
    data = _read_producer_json(json_path, "rtl_precheck_gate", rc, stderr)
    if not isinstance(data, dict):
        raise ProducerOutputError(
            f"rtl_precheck_gate JSON is a {type(data).__name__}, not the "
            f"documented report object — refusing to read it as an empty result")
    auditors = data.get("auditors")
    if isinstance(auditors, dict):
        # An object envelope keyed by auditor name is accepted too, so a future
        # producer change does not silently zero this consumer out.
        records = [dict(v, name=k) for k, v in auditors.items()
                   if isinstance(v, dict)]
        if len(records) != len(auditors):
            raise ProducerOutputError(
                "rtl_precheck_gate 'auditors' object holds non-object values "
                "— refusing to read it as an empty result")
    elif isinstance(auditors, list):
        records = [a for a in auditors if isinstance(a, dict)]
        if len(records) != len(auditors):
            raise ProducerOutputError(
                "rtl_precheck_gate 'auditors' list holds non-object entries "
                "— refusing to read it as an empty result")
    else:
        raise ProducerOutputError(
            f"rtl_precheck_gate JSON has no usable 'auditors' collection "
            f"(got {type(auditors).__name__}) — refusing to read it as an "
            f"empty result")

    out: List[Finding] = []
    for rec in records:
        auditor_name = str(rec.get("name", "unknown"))
        # Map auditor name to category — most precheck auditors target
        # § 4 correctness smells, but specific ones target § 1 or § 2.
        cat = "correctness_smells"
        low = auditor_name.lower()
        if "reset" in low:
            cat = "reset_clock_hygiene"
        elif "port" in low:
            cat = "port_fidelity"
        elif "synth" in low or "latch" in low:
            cat = "synthesis_hazards"

        if rec.get("skipped"):
            reason = str(rec.get("skip_reason", "")).strip() or "no reason given"
            out.append(Finding(
                category=cat, severity="INFO", rule_id=auditor_name,
                file="", line=0,
                message=f"auditor did not run: {reason}",
                source=f"rtl_precheck_gate.{auditor_name}"))
            continue
        if rec.get("passed"):
            continue
        tail = str(rec.get("stderr_tail") or rec.get("stdout_tail") or "").strip()
        detail = tail.splitlines()[-1] if tail else "no output captured"
        out.append(Finding(
            category=cat, severity="ERROR", rule_id=auditor_name,
            file="", line=0,
            message=f"auditor failed (exit {rec.get('exit_code', '?')}): {detail}",
            source=f"rtl_precheck_gate.{auditor_name}"))
    return out


# ---------------------------------------------------------------------------
# Top-level aggregate
# ---------------------------------------------------------------------------
@dataclass
class ReviewReport:
    rtl_dir: str
    files_reviewed: List[str]
    per_category: Dict[str, CategorySummary]
    score: int
    verdict: str         # PASS | WARN | FAIL
    severity_band: str
    total_errors: int
    total_warns: int
    total_infos: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rtl_dir": self.rtl_dir,
            "files_reviewed": self.files_reviewed,
            "per_category": {
                k: {
                    "errors": v.errors,
                    "warns": v.warns,
                    "infos": v.infos,
                    "findings": [f.as_dict() for f in v.findings],
                } for k, v in self.per_category.items()
            },
            "score": self.score,
            "verdict": self.verdict,
            "severity_band": self.severity_band,
            "total_errors": self.total_errors,
            "total_warns": self.total_warns,
            "total_infos": self.total_infos,
            "emitted_by": _pmd.emitted_by("rtl_review_aggregate"),
        }


def aggregate(
    findings: List[Finding],
    rtl_dir: str = "",
    files_reviewed: Optional[List[str]] = None,
    is_synthesizable: bool = True,
) -> ReviewReport:
    """Pure-function aggregator over a Finding list. Useful for unit tests
    and for callers that already ran the sub-programs themselves.
    """
    per_cat: Dict[str, CategorySummary] = {
        n: CategorySummary(name=n) for n in CATEGORY_NAMES}
    # Unknown-category findings fall into style_readability per skill rubric.
    for f in findings:
        cat = f.category if f.category in per_cat else "style_readability"
        per_cat[cat].add(f)

    total_errors = sum(c.errors for c in per_cat.values())
    total_warns = sum(c.warns for c in per_cat.values())
    total_infos = sum(c.infos for c in per_cat.values())
    score = compute_score(total_errors, total_warns, total_infos,
                          is_synthesizable=is_synthesizable)
    return ReviewReport(
        rtl_dir=rtl_dir,
        files_reviewed=list(files_reviewed or []),
        per_category=per_cat,
        score=score,
        verdict=score_to_verdict(score),
        severity_band=severity_band(score),
        total_errors=total_errors,
        total_warns=total_warns,
        total_infos=total_infos,
    )


def review_rtl_dir(rtl_dir: Path, tmp_dir: Path) -> ReviewReport:
    """Drive the 3 sub-programs over a directory of RTL files and aggregate.

    Each sub-program's EXIT CODE is now carried into its loader. It used to be
    discarded, so a producer that crashed, timed out or was missing entirely
    contributed an empty finding list indistinguishable from a clean file
    (#2036). A producer that reached no verdict now raises
    `ProducerOutputError` rather than improving the score.
    """
    files = sorted([p for p in rtl_dir.rglob("*")
                    if p.suffix in (".v", ".sv") and p.is_file()])
    findings: List[Finding] = []

    if files:
        # rtl_hygiene_lint files...
        hygiene_json = tmp_dir / "hygiene.json"
        rc, _out, err = _run_program_json(
            "rtl_hygiene_lint.py",
            [str(f) for f in files],
            hygiene_json)
        findings.extend(_load_hygiene_findings(hygiene_json, rc, err))

    # reset_discipline_check directory-recursive
    reset_json = tmp_dir / "reset.json"
    rc, _out, err = _run_program_json(
        "reset_discipline_check.py",
        ["--rtl-dir", str(rtl_dir)],
        reset_json)
    findings.extend(_load_reset_findings(reset_json, rc, err))

    # rtl_precheck_gate aggregate
    precheck_json = tmp_dir / "precheck.json"
    rc, _out, err = _run_program_json(
        "rtl_precheck_gate.py",
        ["--rtl-dir", str(rtl_dir)],
        precheck_json)
    findings.extend(_load_precheck_findings(precheck_json, rc, err))

    return aggregate(
        findings,
        rtl_dir=str(rtl_dir),
        files_reviewed=[str(f.relative_to(rtl_dir)) for f in files],
    )


# ---------------------------------------------------------------------------
# Markdown output (the report shape the skill expected the LLM to author)
# ---------------------------------------------------------------------------
def report_to_markdown(rep: ReviewReport) -> str:
    """Emit the report in the rtl-review skill's documented shape.

    The skill's prose template was:
      ## Summary
      ## Findings
      ### Errors (must fix)
      ### Warnings (should fix)
      ### Info (consider)
      ## Recommendations
      ## Next step
    """
    out: List[str] = []
    out.append(f"# RTL review — {rep.rtl_dir or 'unspecified'}")
    out.append("")
    out.append(f"_Emitted by `rtl_review_aggregate.py` (Vibe-IC plugin "
               f"v{_pmd.running_plugin_version()}). "
               f"Score and category counts are deterministic; refuse to claim "
               f"a higher score than this report._")
    out.append("")

    # § Summary
    out.append("## Summary")
    out.append("")
    out.append(f"- **Score**: {rep.score}/10 ({rep.severity_band})")
    out.append(f"- **Verdict**: {rep.verdict}")
    out.append(f"- **Files reviewed**: {len(rep.files_reviewed)}")
    out.append(f"- **Errors**: {rep.total_errors}")
    out.append(f"- **Warnings**: {rep.total_warns}")
    out.append(f"- **Infos**: {rep.total_infos}")
    out.append("")

    # § Per-category
    out.append("## Per-category")
    out.append("")
    out.append("| Category | ERROR | WARN | INFO |")
    out.append("|---|---|---|---|")
    for name in CATEGORY_NAMES:
        c = rep.per_category[name]
        out.append(f"| {name} | {c.errors} | {c.warns} | {c.infos} |")
    out.append("")

    # § Findings sorted by severity
    out.append("## Findings")
    out.append("")
    for label, sev in (("Errors (must fix)", "ERROR"),
                       ("Warnings (should fix)", "WARN"),
                       ("Info (consider)", "INFO")):
        out.append(f"### {label}")
        out.append("")
        any_in_section = False
        for cat in CATEGORY_NAMES:
            for f in rep.per_category[cat].findings:
                if f.severity != sev:
                    continue
                any_in_section = True
                out.append(
                    f"- `[{f.category}]` **{f.rule_id}** in `{f.file}:{f.line}` "
                    f"— {f.message}  (via {f.source})")
        if not any_in_section:
            out.append("_None._")
        out.append("")

    # § Next step
    out.append("## Next step")
    out.append("")
    if rep.verdict == "PASS":
        out.append("Proceed to synthesis / next phase. No blocking issues.")
    elif rep.verdict == "WARN":
        out.append("Address warnings before tapeout, but Phase 2 can continue.")
    else:
        out.append("Fix errors and re-run rtl_review_aggregate before "
                   "advancing. Errors block downstream gates.")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli() -> int:
    p = argparse.ArgumentParser(
        description="Deterministic rtl-review aggregator (Pattern-B program).")
    p.add_argument("--rtl-dir", type=Path, required=True,
                   help="Directory of .v / .sv files to review")
    p.add_argument("--tmp-dir", type=Path, default=None,
                   help="Working dir for sub-program JSON (default: rtl-dir/.review)")
    p.add_argument("--out-md", type=Path, default=None,
                   help="Markdown report path (default: stdout)")
    p.add_argument("--out-json", type=Path, default=None,
                   help="JSON report path (machine-readable)")
    p.add_argument("--strict", action="store_true",
                   help="Exit non-zero if verdict != PASS")
    args = p.parse_args()

    if not args.rtl_dir.exists():
        print(f"rtl-dir does not exist: {args.rtl_dir}", file=sys.stderr)
        return 2

    tmp_dir = args.tmp_dir or (args.rtl_dir / ".review")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # #2036: an unreadable producer is a REFUSAL, never a clean review. It
    # exits 3 (distinct from 1 = "reviewed, verdict not PASS" and 2 = usage) and
    # writes NO report, so nothing downstream can mistake it for a score.
    try:
        report = review_rtl_dir(args.rtl_dir, tmp_dir)
    except ProducerOutputError as exc:
        print(f"rtl_review_aggregate: REFUSING to emit a review — {exc}",
              file=sys.stderr)
        return 3
    md = report_to_markdown(report)

    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(
            json.dumps(report.as_dict(), indent=2), encoding="utf-8")

    if args.strict and report.verdict != "PASS":
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
