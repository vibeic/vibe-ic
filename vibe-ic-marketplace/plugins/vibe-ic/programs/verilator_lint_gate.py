#!/usr/bin/env python3
"""verilator_lint_gate.py — the step-2 judge of LibreLane Verilator.Lint.

Default consumes the completed native Checker.LintErrors,
Checker.LintTimingConstructs and Checker.LintWarnings states. The transcript
arm below is retained for existing standalone/explicit dual callers.

LibreLane's `Verilator.Lint` runs `verilator --lint-only --Wall` with LATCH as
an error and COUNTS what it prints (`design__lint_error__count`,
`design__lint_warning__count`). It gates nothing on warnings: on the t78 spm
reference 451 warnings passed with `ERROR_ON_LINTER_WARNINGS` false. This gate
reads the step's own transcript and config and decides:

  * every `%Error` blocks (a parse/elaboration error, or LATCH under the
    step's default `LINTER_ERROR_ON_LATCH`);
  * a curated set of warning codes blocks when it is reported inside the
    design's own sources (never inside a PDK blackbox model).  The set is the
    Verilator class of every defect `rtl_hygiene_lint` blocked at
    `--severity ERROR` in regex, plus LATCH and the P0 structural codes:
      UNDRIVEN     <- undriven-wire, undriven-output-port
      MULTIDRIVEN  <- multidriven-register (#740), multidriven-continuous-procedural
      PROCASSWIRE  <- multidriven-continuous-procedural
      COMBDLY      <- nonblocking-in-always-comb
      LATCH        <- if-no-else-latch (when LATCH is not already an error)
      SELRANGE, PINNOTFOUND <- p0_tool_frontend_check.BLOCKING_CODES
    Every other warning stays visible in the report and does not block;
  * the linted file set must be non-empty and equal to the file set synthesis
    reads (`--expect-file`). The step-2 lint once globbed only `*.sv`, linted
    zero files of a `.v` design and wrote PASS (icslot58 d7819ce47).

The transcript reading is cross-checked against LibreLane's own counters in
`state_out.json`; a disagreement is NOT_MEASURED, never a verdict.

Exit: 0 PASS, 1 FAIL, 2 NOT_MEASURED (missing step output, empty input,
uncalibrated reader or reader/tool disagreement).

    verilator_lint_gate.py --step-dir <.../NN-verilator-lint> \
        --expect-file a.v --expect-file b.sv --json out.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402
import instrument_calibration as _calibration  # noqa: E402

GATE = "verilator_lint_gate"

BLOCKING_WARNINGS = frozenset({
    "UNDRIVEN", "MULTIDRIVEN", "PROCASSWIRE", "COMBDLY", "LATCH",
    "SELRANGE", "PINNOTFOUND"})

# `%Warning-CODE: file:line:col: message` / `%Error-CODE: ...` / `%Error: ...`.
_HEAD = re.compile(
    r"^%(?P<sev>Warning|Error)(?:-(?P<code>[A-Z][A-Z0-9_]*))?:\s*"
    r"(?:(?P<file>[^\s:][^:]*):(?P<line>\d+):(?:(?P<col>\d+):)?\s*)?"
    r"(?P<msg>.*)$")
_EXITING = re.compile(r"^%Error: Exiting due to (\d+) error\(s\)")


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def parse_transcript(text: str) -> dict:
    """Diagnostics and the tool's own error total, from a Verilator log."""
    _calibration.assert_calibrated("verilator_lint_gate::parse_transcript")
    diagnostics = []
    exiting: Optional[int] = None
    for raw in text.splitlines():
        line = raw.strip()
        found = _EXITING.match(line)
        if found:
            exiting = int(found.group(1))
            continue
        head = _HEAD.match(line)
        if not head:
            continue
        diagnostics.append({
            "severity": head.group("sev").upper(),
            "code": head.group("code"),
            "file": head.group("file"),
            "line": int(head.group("line")) if head.group("line") else None,
            "message": head.group("msg").strip()})
    return {"diagnostics": diagnostics, "exiting_errors": exiting}


def blocking(diagnostics: Iterable[dict], design_files: Iterable[str]) -> list:
    design = {str(Path(f).resolve()) for f in design_files}
    rows = []
    for row in diagnostics:
        if row["severity"] == "ERROR":
            rows.append(row)
        elif row["code"] in BLOCKING_WARNINGS and row["file"] and \
                str(Path(row["file"]).resolve()) in design:
            rows.append(row)
    return rows


def _judge_calibration(text: str) -> Optional[str]:
    parsed = parse_transcript(text)
    files = {row["file"] for row in parsed["diagnostics"] if row["file"]}
    return "BLOCKING" if blocking(parsed["diagnostics"], files) else None


def _native_checker_failure(step_dir, folder, sid, metric, metrics, failure):
    """Read an actual failed invocation without manufacturing a success receipt."""
    import librelane_contract as contract
    try:
        if not isinstance(failure, dict) or failure.get('code') != 'LL_STEP_FAILED' or folder is None:
            return None
        match = re.fullmatch(r'LL_STEP_FAILED: ([A-Za-z.]+): rc=(\d+); (.+)', failure.get('detail', ''))
        if (match is None or match[1] != sid or int(match[2]) != 255
                or Path(match[3]).resolve() != (folder / 'invocation.log').resolve()
                or (folder / 'state_out.json').exists()):
            return None
        artifacts = failure.get('artifact_readset')
        required = [folder / name for name in ('config.json', 'state_in.json',
                    'input_fingerprint.json', 'invocation.log', 'pdk_root.json')]
        required += [step_dir / name for name in ('vibeic_receipt.json', 'state_out.json',
                    'config.json', 'input_fingerprint.json', 'verilator-lint.log', 'invocation.log')]
        if (not isinstance(artifacts, dict) or any(str(path) not in artifacts for path in required)
                or any(not Path(name).is_file() or hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest
                       for name, digest in artifacts.items())):
            return None
        contract.validate_step_receipt(step_dir, 'Verilator.Lint')
        config = json.loads((folder / 'config.json').read_bytes())
        state = json.loads((folder / 'state_in.json').read_bytes())
        fingerprint = json.loads((folder / 'input_fingerprint.json').read_bytes())
        flag = {'Checker.LintErrors': 'ERROR_ON_LINTER_ERRORS',
                'Checker.LintTimingConstructs': 'ERROR_ON_LINTER_TIMING_CONSTRUCTS',
                'Checker.LintWarnings': 'ERROR_ON_LINTER_WARNINGS'}[sid]
        value = metrics.get(metric)
        if (fingerprint.get('step') != sid or config.get('meta', {}).get('step') != sid
                or config.get(flag, sid != 'Checker.LintWarnings') is not True
                or type(value) is not int or value <= 0 or state.get('metrics') != metrics
                or fingerprint.get('state') != hashlib.sha256((folder / 'state_in.json').read_bytes()).hexdigest()
                or fingerprint.get('local_image') != json.loads((step_dir / 'input_fingerprint.json').read_bytes()).get('local_image')):
            return None
        text = (folder / 'invocation.log').read_text()
        labels = {'Checker.LintErrors': 'Lint errors', 'Checker.LintWarnings': 'Lint warnings',
                  'Checker.LintTimingConstructs': 'Timing constructs'}
        diagnostic = (f'{value} {labels[sid]} found.' if sid != 'Checker.LintTimingConstructs'
                      else 'Timing constructs found in the RTL.')
        if (f"Running '{sid}'" not in text or diagnostic not in text
                or 'An error occurred while executing your step:' not in text):
            return None
        return {'value': value, 'blocking': True, 'failed_step': sid, 'exit_code': int(match[2]),
                'state_in': str(folder / 'state_in.json'),
                'sha256': _sha(folder / 'state_in.json'), 'invocation_log_sha256': _sha(folder / 'invocation.log'),
                'execution_status': 'NATIVE_FAILED_NO_SUCCESS_STATE'}
    except (contract.Refusal, OSError, ValueError, KeyError, TypeError):
        return None


def judge(step_dir: Path, expected: list[Path], *, checker_dirs=None, native_failure=None) -> dict:
    report: dict = {"gate": GATE, "tool": "LibreLane Verilator.Lint",
                    "step_dir": str(step_dir), "blocking_warning_codes":
                    sorted(BLOCKING_WARNINGS)}
    log = step_dir / "verilator-lint.log"
    state = step_dir / "state_out.json"
    config = step_dir / "config.json"
    missing = [p.name for p in (log, state, config) if not p.is_file()]
    if missing:
        report.update(verdict="NOT_MEASURED", reason_class="TOOL_OUTPUT_ABSENT",
                      reason=f"Verilator.Lint step output missing: {missing}")
        return report
    report["sha256"] = {p.name: _sha(p) for p in (log, state, config)}
    try:
        metrics = json.loads(state.read_text()).get("metrics", {})
        linted = [str(Path(p).resolve()) for p in
                  json.loads(config.read_text()).get("VERILOG_FILES") or []]
    except (OSError, ValueError, AttributeError) as exc:
        report.update(verdict="NOT_MEASURED", reason_class="TOOL_OUTPUT_UNREADABLE",
                      reason=str(exc))
        return report
    want = sorted(str(Path(p).resolve()) for p in expected)
    report["file_set"] = {"linted": sorted(linted), "expected": want,
                          "missing": sorted(set(want) - set(linted)),
                          "extra": sorted(set(linted) - set(want))}
    if not want or not linted:
        report.update(verdict="NOT_MEASURED", reason_class="INPUT_ABSENT",
                      reason=f"lint file set is empty (linted {len(linted)}, "
                             f"expected {len(want)}); a lint of nothing states "
                             f"nothing about the design")
        return report
    if checker_dirs is not None:
        # Default consumes LibreLane's native checks. Re-parsing warning text
        # and calibrating a second verdict must not overrule completed native
        # checkers. The legacy transcript arm remains for explicit dual use.
        report.pop("blocking_warning_codes", None)
        report["authority"] = "LibreLane native lint checkers"
        report["tool_metrics"] = metrics
        report["counts"] = {"errors": metrics.get("design__lint_error__count"),
                            "warnings": metrics.get("design__lint_warning__count")}
        report["native_checks"] = {}
        if report["file_set"]["missing"] or report["file_set"]["extra"]:
            report.update(verdict="FAIL", reason_class="LINT_FILE_SET_MISMATCH",
                          reason="the linted files are not the files synthesis reads")
            return report
        required = {"Checker.LintErrors": "design__lint_error__count",
                    "Checker.LintTimingConstructs": "design__lint_timing_construct__count",
                    "Checker.LintWarnings": "design__lint_warning__count"}
        for sid, metric in required.items():
            folder = Path(checker_dirs[sid]) if sid in checker_dirs else None
            try:
                cfg = json.loads((folder / "config.json").read_text())
                checked = json.loads((folder / "state_out.json").read_text())["metrics"]
                value = checked[metric]
                if (cfg.get("meta", {}).get("step") != sid
                        or type(value) is not int or value < 0
                        or value != metrics.get(metric)):
                    raise ValueError("native checker identity or metrics disagree")
                flag = {"Checker.LintErrors": "ERROR_ON_LINTER_ERRORS",
                        "Checker.LintTimingConstructs": "ERROR_ON_LINTER_TIMING_CONSTRUCTS",
                        "Checker.LintWarnings": "ERROR_ON_LINTER_WARNINGS"}[sid]
                enabled = cfg.get(flag, sid != "Checker.LintWarnings")
                if sid != "Checker.LintWarnings" and enabled is not True:
                    raise ValueError("required native checker disabled")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                # A failed native checker has no success-only state_out. Its
                # actual run_chain refusal, completed lint receipt, identical
                # checker input counters and native failure diagnostic remain
                # distinct from an absent/unexecuted checker. Qualification and
                # original launch/adoption are separately required by D11.
                failure = _native_checker_failure(step_dir, folder, sid, metric,
                    metrics, native_failure) if native_failure is not None else None
                if failure is not None:
                    report["native_checks"][sid] = failure
                    report.update(verdict="FAIL", reason_class="LINT_BLOCKING",
                        reason="recorded native required checker failure", native_failure=failure)
                else:
                    report.update(verdict="NOT_MEASURED", reason_class="NATIVE_CHECK_ABSENT_OR_MISMATCH",
                                  reason=f"{sid}: {exc}")
                return report
            report["native_checks"][sid] = {
                "state_out": str(folder / "state_out.json"), "value": value,
                "sha256": _sha(folder / "state_out.json"), "blocking": enabled}
        values = [metrics.get(name) for name in (
            "design__lint_error__count", "design__lint_timing_construct__count",
            "design__inferred_latch__count", "design__lint_warning__count")]
        if any(type(value) is not int or value < 0 for value in values):
            report.update(verdict="NOT_MEASURED", reason_class="NATIVE_METRIC_ABSENT",
                          reason="native lint counters are absent or malformed")
        elif any(values[:3]) or (values[3] and report["native_checks"]["Checker.LintWarnings"]["blocking"]):
            report.update(verdict="FAIL", reason_class="LINT_BLOCKING",
                          reason="native lint error, timing construct or inferred latch")
        else:
            report.update(verdict="PASS", reason=(
                f"{len(linted)} file(s); native errors/timing constructs/latches=0; "
                f"warnings={values[3]} (native warning policy retained)"))
        return report
    try:
        parsed = parse_transcript(log.read_text(errors="replace"))
    except _calibration.Uncalibrated as exc:
        report.update(verdict="NOT_MEASURED", reason_class=exc.reason_class,
                      reason=str(exc))
        return report
    diags = parsed["diagnostics"]
    errors = sum(1 for row in diags if row["severity"] == "ERROR")
    warnings = sum(1 for row in diags if row["severity"] == "WARNING")
    report["counts"] = {"errors": errors, "warnings": warnings,
                        "exiting_errors": parsed["exiting_errors"]}
    report["tool_metrics"] = {k: metrics.get(k) for k in (
        "design__lint_error__count", "design__lint_warning__count",
        "design__inferred_latch__count", "design__lint_timing_construct__count")}
    tool_errors = metrics.get("design__lint_error__count")
    tool_warnings = metrics.get("design__lint_warning__count")
    if tool_warnings != warnings or tool_errors != (parsed["exiting_errors"] or 0) \
            or (tool_errors and not errors):
        report.update(verdict="NOT_MEASURED", reason_class="INSTRUMENT_DISAGREES",
                      reason=(f"transcript reading ({errors} error, {warnings} "
                              f"warning) disagrees with the tool's counters "
                              f"({tool_errors} error, {tool_warnings} warning)"))
        return report
    report["diagnostics"] = diags
    report["blocking"] = blocking(diags, linted)
    if report["file_set"]["missing"] or report["file_set"]["extra"]:
        report.update(verdict="FAIL", reason_class="LINT_FILE_SET_MISMATCH",
                      reason="the linted files are not the files synthesis reads")
    elif report["blocking"]:
        first = report["blocking"][0]
        report.update(verdict="FAIL", reason_class="LINT_BLOCKING",
                      reason=(f"{len(report['blocking'])} blocking diagnostic(s); "
                              f"first {first['severity']}-{first['code']} at "
                              f"{first['file']}:{first['line']}"))
    else:
        report.update(verdict="PASS", reason=(
            f"{len(linted)} file(s) linted; {errors} error, {warnings} "
            f"non-blocking warning(s)"))
    return report


def combine_arms(tool: dict, direct: Optional[list], direct_rc: int) -> dict:
    """Dual step 2: the union of both arms' blocking findings.

    `direct` is rtl_hygiene_lint's JSON finding list (None when it could not
    run). Findings are listed per arm so the corpus measurement the review asks
    for (true defects vs false positives per arm) reads from one record."""
    direct_rows = [row for row in (direct or [])
                   if row.get("severity") == "ERROR" and row.get("block_eligible", True)]
    tool_keys = {(Path(r["file"]).name, r["line"]) for r in tool.get("blocking", [])
                 if r.get("file")}
    direct_keys = {(Path(str(r.get("file"))).name, r.get("line")) for r in direct_rows}
    if tool.get("verdict") == "FAIL" or direct_rows or direct_rc == 1:
        verdict = "FAIL"
    elif tool.get("verdict") != "PASS" or direct is None or direct_rc not in (0, 1):
        verdict = "NOT_MEASURED"
    else:
        verdict = "PASS"
    return {"gate": GATE, "mode": "dual", "verdict": verdict,
            "arms": {"librelane": {"verdict": tool.get("verdict"),
                                    "blocking": tool.get("blocking", [])},
                     "direct": {"exit_code": direct_rc, "blocking": direct_rows}},
            "only_librelane": sorted(map(list, tool_keys - direct_keys)),
            "only_direct": sorted(map(list, direct_keys - tool_keys))}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--step-dir", type=Path, required=True)
    ap.add_argument("--expect-file", type=Path, action="append", default=[])
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args(argv)
    report = judge(args.step_dir, args.expect_file)
    write_json(args.json, report)
    print(f"{GATE}: {report['verdict']} — {report.get('reason', '')}")
    return {"PASS": 0, "FAIL": 1}.get(report["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
