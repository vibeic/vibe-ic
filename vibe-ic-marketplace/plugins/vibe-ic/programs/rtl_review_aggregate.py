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
    """One finding in the aggregated report.

    RULING F2036-H. `not_measured_reason` is non-empty on exactly the records
    that are NOT findings about the RTL at all — an auditor that did not run.
    Such a record is still listed (a check that did not run is reported, never
    counted as a pass) but it is excluded from every count that feeds the score,
    and `ReviewReport.auditors_not_run` names it separately. A score is defined
    over code findings; "this check did not run" is a fact about the INVOCATION,
    and smearing it into an informational finding about the RTL is the
    two-state collapse this repo refuses everywhere — PASS, FAIL and
    NOT_MEASURED are three states.
    """
    category: str
    severity: str            # ERROR | WARN | INFO
    rule_id: str
    file: str
    line: int
    message: str
    source: str              # which sub-program emitted this
    not_measured_reason: str = ""   # non-empty ⇒ absence, not a finding

    @property
    def not_measured(self) -> bool:
        return bool(self.not_measured_reason)

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
        if f.not_measured:
            # RULING F2036-H: listed, never counted. The score is defined over
            # code findings and an auditor that did not run is not one.
            return
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


# ---------------------------------------------------------------------------
# THE SECOND HALF OF #2036, from PR #2039: evidence that is READABLE but not
# TRUSTWORTHY.
#
# `_read_producer_json` and `_finding_records` above answer one question — did
# the producer leave us anything we can read at all? If not, the CLI refuses and
# writes NO report, because a report that exists is a report someone will quote,
# and a score computed from nothing is a measured zero over an unmeasured thing.
#
# But an array that parses can still contain a record that is not a finding:
# `{}`, `{"severity": "surprise"}`, a record with no severity at all. The loader
# used to accept every one of those with SILENT DEFAULTS — `severity` became
# "INFO", `rule` became "unknown", `file` became "" and `line` became 0 — so a
# producer emitting junk contributed harmless INFO noise and the review stayed
# clean. And `rtl_precheck_gate` reporting `"auditors": []` — nothing ran at all
# — scored 10/10 PASS.
#
# The line drawn here, and it is the whole doctrine of this file:
#
#   NO EVIDENCE  (file absent, unparseable, rc reached no verdict, a shape that
#                 is not this producer's report)  -> REFUSE: raise, exit 3,
#                 write nothing.
#   EVIDENCE PRESENT BUT PARTLY UNTRUSTWORTHY (a record that is not a usable
#                 finding; an execution list that recorded nothing) -> REPORT:
#                 a named ERROR record inside the emitted report, so the real
#                 evidence beside it survives and the review can never be clean.
# ---------------------------------------------------------------------------
#: rule_id carried by the named ERROR record each loader emits for untrustworthy
#: evidence. Stable strings — downstream greps for them.
_INVALID_EVIDENCE_RULE = {
    "rtl_hygiene_lint": "hygiene_report_invalid",
    "reset_discipline_check": "reset_report_invalid",
    "rtl_precheck_gate": "precheck_report_invalid",
}

_FINDING_SEVERITIES = ("ERROR", "WARN", "INFO")


def _untrusted_evidence(program: str, json_path: Path, reason: str) -> Finding:
    """A named ERROR record standing in for evidence that cannot be trusted."""
    return Finding(
        category="correctness_smells",
        severity="ERROR",
        rule_id=_INVALID_EVIDENCE_RULE[program],
        file=str(json_path),
        line=0,
        message=f"{program} evidence is unavailable or invalid: {reason}",
        source=program,
    )


def _finding_record_defect(item: Dict[str, Any]) -> Optional[str]:
    """Name why `item` is not a usable finding, or None if it is one.

    Checked against what the producers actually emit, not against a doc:
    `rtl_hygiene_lint` and `reset_discipline_check` both write `rule`, `file`,
    `line`, `severity`, `message` on every record (plus `symbol` and, for the
    hygiene lint, `block_eligible` / `advisory_note`, which are not required
    here). Extra keys are fine; a missing or wrong-typed required one is not.
    """
    missing = [k for k in ("rule", "file", "message")
               if not isinstance(item.get(k), str)]
    if missing:
        return f"lacks a string {'/'.join(missing)}"
    line = item.get("line")
    if not isinstance(line, int) or isinstance(line, bool) or line < 0:
        return f"has line {line!r}, not a non-negative integer"
    if item.get("severity") not in _FINDING_SEVERITIES:
        return (f"has severity {item.get('severity')!r}, not one of "
                f"{'/'.join(_FINDING_SEVERITIES)}")
    return None


def _auditor_record_defect(rec: Dict[str, Any]) -> Optional[str]:
    """Name why `rec` is not a usable AuditorResult, or None if it is one.

    MEASURED against `rtl_precheck_gate.AuditorResult`, which is what the
    producer actually serialises: `name` / `passed` / `exit_code` are always
    written, `skipped` / `skip_reason` / `stdout_tail` / `stderr_tail` carry
    defaults. A record missing the first three is not a result — reading it as
    one would silently attribute a verdict to an auditor that never reported.
    """
    if not isinstance(rec.get("name"), str) or not rec["name"].strip():
        return "lacks a non-empty string 'name'"
    if not isinstance(rec.get("passed"), bool):
        return f"has passed {rec.get('passed')!r}, not a boolean"
    exit_code = rec.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        return f"has exit_code {exit_code!r}, not an integer"
    return None


def _partition_finding_records(
        records: List[dict], program: str,
        json_path: Path) -> Tuple[List[dict], List[Finding]]:
    """Split a producer's records into usable findings and named defects."""
    usable: List[dict] = []
    defects: List[Finding] = []
    for index, item in enumerate(records):
        defect = _finding_record_defect(item)
        if defect is None:
            usable.append(item)
            continue
        defects.append(_untrusted_evidence(
            program, json_path, f"finding {index} {defect}"))
    return usable, defects


def _load_hygiene_findings(json_path: Path, rc: Optional[int] = None,
                           stderr: str = "") -> List[Finding]:
    """Parse `rtl_hygiene_lint --json` output into a Finding list.

    The producer emits a BARE ARRAY (`[]` for a clean file). Reading it as
    `data.get("findings", [])` raised `AttributeError: 'list' object has no
    attribute 'get'` and took the whole aggregate down with exit 1 and no report
    at all — on an ordinary clean flip-flop (issue #2036).
    """
    data = _read_producer_json(json_path, "rtl_hygiene_lint", rc, stderr)
    usable, out = _partition_finding_records(
        _finding_records(data, "rtl_hygiene_lint"), "rtl_hygiene_lint",
        json_path)
    for item in usable:
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
    usable, out = _partition_finding_records(
        _finding_records(data, "reset_discipline_check"),
        "reset_discipline_check", json_path)
    for item in usable:
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

    # THE PUREST FORM OF #2036, and the one the landed fix still read as clean:
    # a report whose execution list is EMPTY says NOTHING RAN. That is not a
    # clean file — it is an unmeasured one, and it used to score 10/10 PASS.
    if not auditors:
        return [_untrusted_evidence(
            "rtl_precheck_gate", json_path,
            f"the 'auditors' {type(auditors).__name__} is empty — no auditor "
            f"was measured, which is not a clean result")]

    out: List[Finding] = []
    for index, rec in enumerate(records):
        defect = _auditor_record_defect(rec)
        if defect is not None:
            out.append(_untrusted_evidence(
                "rtl_precheck_gate", json_path, f"auditor {index} {defect}"))
            continue
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
                message=f"auditor did not run (NOT_MEASURED): {reason}",
                source=f"rtl_precheck_gate.{auditor_name}",
                not_measured_reason=reason))
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
    #: RULING F2036-H. Every auditor that did not run, by name and reason.
    #: Populated from exactly the records the score no longer counts, so the
    #: number can never be quoted without its coverage.
    auditors_not_run: List[Dict[str, str]] = field(default_factory=list)

    def coverage_note(self) -> str:
        """The clause that must travel with the score, or "" if fully covered."""
        if not self.auditors_not_run:
            return ""
        listed = "; ".join(f"{a['auditor']} — {a['why']}"
                           for a in self.auditors_not_run)
        n = len(self.auditors_not_run)
        return f"{n} auditor{'' if n == 1 else 's'} not run: {listed}"

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
            "auditors_not_run": [dict(a) for a in self.auditors_not_run],
            "coverage_note": self.coverage_note(),
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

    # RULING F2036-H — the not-run records are lifted out of the score and
    # named in their own field. They stay listed in `per_category` because a
    # check that did not run is REPORTED, never counted as a pass; what changes
    # is that it is no longer counted as a FINDING ABOUT THE RTL either.
    auditors_not_run = [
        {"auditor": f.rule_id, "why": f.not_measured_reason, "source": f.source}
        for f in findings if f.not_measured]

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
        auditors_not_run=auditors_not_run,
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
    # RULING F2036-H: a score is never printed bare when an auditor did not
    # run. A number that can be quoted without its coverage is #2036 one level
    # up — "nothing was reported" reading as "there was nothing to report".
    note = rep.coverage_note()
    coverage = f" — {note}" if note else ""
    out.append(f"- **Score**: {rep.score}/10 ({rep.severity_band}){coverage}")
    out.append(f"- **Verdict**: {rep.verdict}{coverage}")
    out.append(f"- **Files reviewed**: {len(rep.files_reviewed)}")
    out.append(f"- **Errors**: {rep.total_errors}")
    out.append(f"- **Warnings**: {rep.total_warns}")
    out.append(f"- **Infos**: {rep.total_infos}")
    out.append(f"- **Auditors not run**: {len(rep.auditors_not_run)}")
    out.append("")

    # § Not measured — absence, reported as absence
    if rep.auditors_not_run:
        out.append("## Not measured")
        out.append("")
        out.append("These auditors did not run. They are neither a pass nor a "
                   "finding; the score above is over the auditors that ran.")
        out.append("")
        for a in rep.auditors_not_run:
            out.append(f"- **{a['auditor']}** — {a['why']}  (via {a['source']})")
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
                if f.severity != sev or f.not_measured:
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
                   help="Exit non-zero if verdict != PASS, or if any auditor "
                        "did not run (RULING F2036-H)")
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

    # RULING F2036-H — `--strict` and incomplete coverage.
    #
    # DOWNGRADE (exit 1), not REFUSAL (exit 3), and the reason is which claim
    # each code makes. Exit 3 means "no verdict was reached and no report
    # exists"; that is false here — a real review ran over the auditors that
    # did run and its findings are real evidence, and refusing would destroy
    # them. Exit 1 means "I reviewed this and I will not certify it as PASS",
    # which is exactly true when a check did not run. So the report is still
    # written, it names what did not run, and `--strict` refuses the pass.
    if args.strict and report.auditors_not_run:
        print(f"rtl_review_aggregate: --strict refuses to certify PASS — "
              f"{report.coverage_note()}", file=sys.stderr)
        return 1
    if args.strict and report.verdict != "PASS":
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
