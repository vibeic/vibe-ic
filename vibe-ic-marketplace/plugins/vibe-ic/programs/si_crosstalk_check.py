#!/usr/bin/env python3
"""Verify signal integrity / crosstalk analysis was performed."""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple
import _path_layout as _pl


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


# ---------------------------------------------------------------------------
# v1.7.64 — FAIL-CLOSED advisory disclosure (#437 follow-up, Step 27 / d5).
#
# The pre-v1.7.64 predicate ALLOW-LISTED two emitter verdict strings
# ("ADVISORY_SCREEN_ONLY", "SI_SPEF_SCREEN_PASS") plus the substring
# "advisory" in `method`. Measured on a real converged run, the no-SPEF
# fallback emitter writes a THIRD string, "SCREEN_PASS", whose method text
# says "decoupled-C wire-RC screen ... full coupling-cap crosstalk needs a
# SPEF" and whose note says "this is a structural screen, not a full SI
# sign-off" — and the gate reported a bare `verdict: PASS`,
# `advisory_screen_only: false`, zero findings. An artefact that explicitly
# disclaims sign-off was laundered into sign-off by an allow-list miss.
#
# The predicate is now inverted: an SI artefact is ADVISORY unless it
# POSITIVELY declares timing-window SI sign-off. A new emitter string can no
# longer buy a clean PASS by not being on a list. rc is unchanged (WARNING,
# not ERROR) — this is a disclosure fix, not a new pass/fail rule.
# ---------------------------------------------------------------------------

# An explicit boolean is the canonical positive declaration.
_SIGNOFF_DECL_KEYS = ("timing_window_signoff", "si_signoff", "full_si_signoff")

# Textual positive declaration, for third-party emitters carrying no boolean:
# the artefact must name timing-window / switching-window SI analysis...
_SIGNOFF_TEXT_MARKERS = (
    "timing-window", "timing window",
    "switching-window", "switching window",
)
# ...AND must not describe itself as a screen / bound / watch-list, which is
# what every non-sign-off SI artefact in this codebase calls itself.
_SCREEN_MARKERS = (
    "screen", "advisory", "watch-list", "watchlist",
    "upper bound", "not a full si sign-off", "not a full si signoff",
    "not sign-off", "not signoff", "deferred",
)


def declares_si_signoff(blob: str, data: dict | None = None) -> bool:
    """True only when the artefact POSITIVELY declares timing-window SI
    sign-off. Everything else — including an artefact that says nothing at
    all about its own tier — is treated as an advisory screen."""
    if data is not None and any(bool(data.get(k)) for k in _SIGNOFF_DECL_KEYS):
        return True
    low = blob.lower()
    if any(m in low for m in _SCREEN_MARKERS):
        return False
    return any(m in low for m in _SIGNOFF_TEXT_MARKERS)



# ── D9: the artefact must be COHERENT WITH ITSELF ──────────────────────────
# vibe-ic D9 census scored step 27 EXISTENCE-ONLY: every number in
# si_crosstalk.json could be scaled and sign-flipped and this gate's verdict
# did not move. It read `violations_count` and asked only whether it was > 0,
# so a count of -7 sailed through.
#
# NO ORACLE, and none is needed. Nothing below knows what any value SHOULD be
# for any design — a real run ships no answer key. Every rule here is either a
# DOMAIN bound that holds for any circuit ever built, or an arithmetic relation
# the document asserts BETWEEN ITS OWN FIELDS:
#
#   * a coupling ratio is Cc/(Cc+Cg), a fraction of a capacitance by a larger
#     capacitance, so it lies in [0, 1] for every net in every technology;
#   * a mean cannot exceed the max of the same population;
#   * a count of nets cannot be negative;
#   * nets with ratio > 0.9 are a SUBSET of nets with ratio > 0.5, which are a
#     subset of the nets analysed. That containment is exact, not a heuristic:
#     it follows from the thresholds the field NAMES carry.
#
# A document that breaks one of these was not produced by measuring a circuit,
# so every conclusion drawn from it — including this gate's own — is about
# numbers nobody computed.
_RATIO_FIELDS = ("max_coupling_ratio", "mean_coupling_ratio")
_COUNT_FIELDS = ("nets_analyzed", "nets_elevated_coupling_gt0p5",
                 "nets_coupling_dominated_gt0p9", "violations_count")
#: widest-to-narrowest; each must contain the next
_CONTAINMENT = ("nets_analyzed", "nets_elevated_coupling_gt0p5",
                "nets_coupling_dominated_gt0p9")


def _num(data: dict, key: str):
    """The value at `key` iff it is a real number. `bool` is excluded on
    purpose: it is an int subclass, and reading True as 1 would invent a
    measurement out of a flag."""
    v = data.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _incoherent(data: dict) -> List[Finding]:
    """Every self-consistency / domain violation the document commits."""
    out: List[Finding] = []
    if not isinstance(data, dict):
        return out

    for key in _RATIO_FIELDS:
        v = _num(data, key)
        if v is not None and not (0.0 <= v <= 1.0):
            out.append(Finding("ERROR", "SI_RATIO_OUT_OF_DOMAIN",
                               f"{key}={v} is not a ratio: Cc/(Cc+Cg) lies in "
                               f"[0,1] for every net in every technology"))

    lo, hi = _num(data, "mean_coupling_ratio"), _num(data, "max_coupling_ratio")
    if lo is not None and hi is not None and lo > hi:
        out.append(Finding("ERROR", "SI_MEAN_EXCEEDS_MAX",
                           f"mean_coupling_ratio={lo} exceeds "
                           f"max_coupling_ratio={hi} over the same population"))

    for key in _COUNT_FIELDS:
        v = _num(data, key)
        if v is not None and v < 0:
            out.append(Finding("ERROR", "SI_NEGATIVE_COUNT",
                               f"{key}={v}: a count of nets cannot be negative"))

    for wide, narrow in zip(_CONTAINMENT, _CONTAINMENT[1:]):
        a, b = _num(data, wide), _num(data, narrow)
        if a is not None and b is not None and a >= 0 and b >= 0 and b > a:
            out.append(Finding("ERROR", "SI_SUBSET_EXCEEDS_SUPERSET",
                               f"{narrow}={b} exceeds {wide}={a}, but the "
                               f"first names a strictly narrower threshold "
                               f"than the second"))
    return out


def audit(project_dir: Path) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    rpt = _pl.report_path(project_dir, "si_crosstalk.rpt")
    jsn = _pl.report_path(project_dir, "si_crosstalk.json")
    waiver = project_dir / "waivers.json"
    stats = {"report_found": False, "format": "", "violations": 0}

    # Both formats consume the same strict producer evidence. Removing the
    # JSON companion must not let retained text bypass current validation.
    if jsn.exists() or rpt.exists():
        import _opensta_current as current
        try:
            current.si_binding(project_dir)
            stats['current_binding'] = 'CURRENT'
        except (OSError, ValueError, KeyError, TypeError) as exc:
            stats['current_binding'] = 'NOT_MEASURED'
            findings.append(Finding('ERROR', 'SI_CURRENT_INPUTS_UNBOUND', str(exc)))

    if jsn.exists():
        stats["report_found"] = True
        stats["format"] = "json"
        try:
            data = json.loads(jsn.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            findings.append(Finding("ERROR", "BAD_JSON",
                                    f"Cannot parse si_crosstalk.json: {exc}"))
            return findings, stats

        for key in ("max_crosstalk_noise", "violations_count"):
            if key not in data:
                findings.append(Finding("ERROR", "MISSING_FIELD",
                                        f"si_crosstalk.json missing '{key}'"))

        findings.extend(_incoherent(data))

        if (data.get('delta_delay') or {}).get('verdict') == 'FAIL' or data.get('delta_delay_verdict') == 'FAIL':
            findings.append(Finding('ERROR', 'SI_DELTA_DELAY_FAIL',
                                    'The current timing-window delta-delay measurement failed'))

        violations = data.get("violations_count", 0)
        stats["violations"] = violations

        # ORGANIC-20260606 (#437 follow-up comment) — advisory-screen
        # DISCLOSURE: the open-flow emitters hardwire violations_count=0
        # and honestly say so; the gate must not launder that into a clean
        # sign-off PASS. Surface the tier + the coupling-dominated
        # watch-list. v1.7.64 makes the predicate fail-closed (see the
        # module-level note on `declares_si_signoff`).
        blob = " ".join(str(data.get(k, "")) for k in
                        ("verdict", "method", "mode", "tool", "note"))
        is_advisory = not declares_si_signoff(blob, data)
        stats["advisory_screen_only"] = is_advisory
        dominated = data.get("nets_coupling_dominated_gt0p9")
        if is_advisory:
            findings.append(Finding(
                "WARNING", "SI_ADVISORY_SCREEN_ONLY",
                "SI artifact does not declare timing-window SI sign-off — "
                "treated as an ADVISORY screen (the open-flow screens are "
                "floating-victim capacitive bounds with violations_count "
                "hardwired 0); review required before presenting as "
                "sign-off (#437)",
                details=f"verdict={data.get('verdict', '(absent)')!r}"))
            if isinstance(dominated, (int, float)) and dominated > 0:
                findings.append(Finding(
                    "WARNING", "SI_COUPLING_DOMINATED_WATCHLIST",
                    f"{int(dominated)} net(s) coupling-dominated "
                    f"(Cc/(Cc+Cg) > 0.9) on the advisory watch-list — "
                    f"review with a timing-window SI tool (#437)"))
        if isinstance(violations, (int, float)) and violations > 0:
            has_waiver = False
            if waiver.exists():
                try:
                    w = json.loads(waiver.read_text())
                    waivers = w if isinstance(w, list) else w.get("waivers", [])
                    has_waiver = any(
                        e.get("step") == "si_crosstalk" or
                        e.get("category") == "si_crosstalk"
                        for e in waivers if isinstance(e, dict)
                    )
                except (json.JSONDecodeError, OSError):
                    pass
            if not has_waiver:
                findings.append(Finding("ERROR", "SI_VIOLATIONS",
                                        f"{violations} crosstalk violations without waiver"))

    elif rpt.exists():
        stats["report_found"] = True
        stats["format"] = "rpt"
        if rpt.stat().st_size == 0:
            findings.append(Finding("ERROR", "EMPTY_RPT",
                                    "si_crosstalk.rpt is empty"))
        else:
            # v1.7.64 — the same fail-closed disclosure applies to the .rpt
            # form. Otherwise the JSON tightening is trivially bypassed by
            # emitting only the text report, whose own body says
            # "crosstalk screen: PASS".
            try:
                text = rpt.read_text(errors="replace")[:64 * 1024]
            except OSError:
                text = ""
            rpt_advisory = not declares_si_signoff(text)
            stats["advisory_screen_only"] = rpt_advisory
            if rpt_advisory:
                findings.append(Finding(
                    "WARNING", "SI_ADVISORY_SCREEN_ONLY",
                    "SI artifact does not declare timing-window SI "
                    "sign-off — treated as an ADVISORY screen; review "
                    "required before presenting as sign-off (#437)"))
    else:
        findings.append(Finding("ERROR", "NO_REPORT",
                                "Neither si_crosstalk.rpt nor si_crosstalk.json found"))

    return findings, stats


def build_report(findings: List[Finding], stats: dict,
                 project_dir: str) -> dict:
    ok = all(f.severity != "ERROR" for f in findings)
    advisory = stats.get("advisory_screen_only", False)
    return {
        "program": "si_crosstalk_check",
        "version": "1.1.0",
        "project_dir": project_dir,
        # #437 follow-up: the headline names the tier — an advisory
        # capacitive screen is never presented as plain sign-off PASS.
        "verdict": ("ADVISORY_SCREEN_ONLY" if ok and advisory
                    else "PASS" if ok else "FAIL"),
        "summary": {
            "report_found": stats["report_found"],
            "format": stats["format"],
            "violations": stats["violations"],
            "advisory_screen_only": advisory,
            "findings_count": len(findings),
            "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
            "pass": ok,
        },
        "findings": [asdict(f) for f in findings],
    }


def _d48_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('D48_DUPLICATE_INPUT_KEY: ' + key)
        result[key] = value
    return result


def _d48_inputs(project):
    import analog_bound_measurements as measured
    config = project / 'input/flow109/D48.json'
    data = json.loads(config.read_text(), object_pairs_hook=_d48_unique)
    inputs = {'settings': {'path': str(config), 'sha256': measured.sha(config)}}
    for role in ('netlist', 'testbench', 'coupling_model'):
        view = data[role]
        path = project / view['path']
        resolved = path.resolve(strict=True)
        if (not resolved.is_relative_to(project) or resolved != path.absolute()
                or not resolved.is_file() or measured.sha(resolved) != view['sha256']):
            raise ValueError('D48_INPUT_UNBOUND: ' + role)
        inputs[role] = {'path': str(resolved), 'sha256': view['sha256']}
    analysis = data['analysis']
    if analysis.get('kind') != 'TRAN':
        raise ValueError('D48_EXPLICIT_TRAN_REQUIRED')
    windows = data['windows']
    if not isinstance(windows, list) or not windows:
        raise ValueError('D48_DECLARED_WINDOWS_REQUIRED')
    names = set()
    for window in windows:
        name = window['id']
        if not isinstance(name, str) or not name or name in names:
            raise ValueError('D48_UNIQUE_WINDOW_IDS_REQUIRED')
        names.add(name)
        for key in ('baseline_v', 'from_s', 'to_s', 'max_noise_v', 'min_aggressor_swing_v'):
            value = window[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('D48_FINITE_WINDOW_LIMIT_REQUIRED: ' + key)
        if window['max_noise_v'] < 0 or window['min_aggressor_swing_v'] <= 0:
            raise ValueError('D48_INVALID_NOISE_OR_EXCITATION_LIMIT')
        for key in ('aggressor', 'victim'):
            if not isinstance(window[key], str) or not re.fullmatch(
                    r'v\([A-Za-z0-9_.$:/#\[\]!-]+\)', window[key], re.I):
                raise ValueError('D48_EXPLICIT_VOLTAGE_VECTOR_REQUIRED: ' + key)
        if window['aggressor'].casefold() == window['victim'].casefold():
            raise ValueError('D48_DISTINCT_AGGRESSOR_AND_VICTIM_REQUIRED')
    closure = measured.consumed_input_views(project, Path(inputs['testbench']['path']))
    included = {view['path'] for view in closure.values()}
    if not {inputs[role]['path'] for role in ('netlist', 'coupling_model')} <= included:
        raise ValueError('D48_CIRCUIT_OR_COUPLING_NOT_IN_EXECUTED_CLOSURE')
    return data, inputs


def _d48_bindings(data, binary):
    measurements, capture = {}, {}
    for index, window in enumerate(data['windows']):
        prefix = 'w' + str(index)
        for suffix, expression, statistic in (
                ('noise', f"abs({window['victim']}-({window['baseline_v']:.17g}))", 'MAX'),
                ('amax', window['aggressor'], 'MAX'), ('amin', window['aggressor'], 'MIN')):
            measurements[prefix + '_' + suffix] = {
                'analysis': 'TRAN', 'expression': expression, 'statistic': statistic,
                'from_s': window['from_s'], 'to_s': window['to_s']}
        capture[prefix + '_aggressor'] = window['aggressor']
        capture[prefix + '_victim'] = window['victim']
    return {'analysis': data['analysis'], 'measurements': measurements, 'capture': capture,
            'execution': {'threads': 1, 'wait_policy': 'PASSIVE', 'ngspice_bin': binary}}


def _d48_consume(project, native, data, inputs):
    """Consume this producer's execution and capture. No stored evidence is upgraded."""
    import analog_bound_measurements as measured
    if native.get('status') != 'PASS':
        return native.get('status', 'NOT_MEASURED'), 'D48_NATIVE_MEASUREMENT_' + str(native.get('status')), []
    executions = native.get('executions')
    if not isinstance(executions, list) or len(executions) != 1:
        raise ValueError('D48_EXECUTED_CAPTURE_REQUIRED')
    execution = executions[0]
    if execution.get('returncode') != 0 or not execution.get('argv'):
        raise ValueError('D48_SUCCESSFUL_NATIVE_EXECUTION_REQUIRED')
    log = Path(execution['log'])
    if measured.sha(log) != execution['log_sha256']:
        raise ValueError('D48_NATIVE_LOG_CHANGED')
    current, why = measured.validate_consumed_inputs(project, native['native_inputs'])
    if not current:
        raise ValueError('D48_NATIVE_CLOSURE_UNBOUND: ' + why)
    for view in [*inputs.values(), *native['native_inputs'].values()]:
        if measured.sha(view['path']) != view['sha256']:
            raise ValueError('D48_EXECUTED_INPUT_CHANGED: ' + view['path'])
    capture = native['capture']
    path = Path(capture['path'])
    if measured.sha(path) != capture['sha256']:
        raise ValueError('D48_CAPTURE_CHANGED_OR_TRUNCATED')
    rows = path.read_text().splitlines()
    expected = ['time', *('bound_' + name for name in native['bindings']['capture'])]
    if not rows or rows[0].split() != expected:
        raise ValueError('D48_NATIVE_CAPTURE_VECTORS_INVALID')
    samples = [list(map(float, row.split())) for row in rows[1:]]
    if (len(samples) < 2 or any(len(row) != len(expected) or
            any(not math.isfinite(value) for value in row) for row in samples)
            or any(b[0] <= a[0] for a, b in zip(samples, samples[1:]))):
        raise ValueError('D48_NATIVE_CAPTURE_INCOMPLETE')
    analysis = data['analysis']
    tolerance = analysis['step_s'] * 1e-5
    if (samples[0][0] > analysis.get('start_s', 0) + tolerance
            or samples[-1][0] < analysis['stop_s'] - tolerance
            or any(b[0] - a[0] > analysis['step_s'] * 1.01
                   for a, b in zip(samples, samples[1:]))):
        raise ValueError('D48_NATIVE_CAPTURE_INTERVAL_INCOMPLETE')
    results = []
    for index, window in enumerate(data['windows']):
        first, last = window['from_s'], window['to_s']
        selected = [row for row in samples if first <= row[0] <= last]
        for boundary in (first, last):
            if any(row[0] == boundary for row in selected):
                continue
            bracket = next(((a, b) for a, b in zip(samples, samples[1:])
                            if a[0] < boundary < b[0]), None)
            if bracket is None:
                raise ValueError('D48_WINDOW_NOT_CAPTURED')
            a, b = bracket
            fraction = (boundary - a[0]) / (b[0] - a[0])
            selected.append([boundary, *(x + fraction * (y - x) for x, y in zip(a[1:], b[1:]))])
        aggressor = [row[1 + index * 2] for row in selected]
        victim = [row[2 + index * 2] for row in selected]
        peak = max(abs(value - window['baseline_v']) for value in victim)
        maximum, minimum = max(aggressor), min(aggressor)
        values = native['measurements']
        for suffix, observed in (('noise', peak), ('amax', maximum), ('amin', minimum)):
            # ngspice's text measurement and wrdata have different print precision.
            if not math.isclose(observed, values['w' + str(index) + '_' + suffix], rel_tol=5e-5, abs_tol=1e-12):
                raise ValueError('D48_CAPTURE_AND_NATIVE_MEASUREMENT_DISAGREE')
        results.append({**window, 'peak_noise_v': peak, 'aggressor_swing_v': maximum - minimum,
                        'samples': len(selected), 'noise_status':
                        'FAIL' if peak > window['max_noise_v'] else 'PASS'})
    if any(row['noise_status'] == 'FAIL' for row in results):
        return 'FAIL', 'D48_NOISE_LIMIT_EXCEEDED', results
    if any(row['aggressor_swing_v'] < row['min_aggressor_swing_v'] for row in results):
        return 'NOT_MEASURED', 'D48_AGGRESSOR_NOT_EXERCISED', results
    return 'PASS', 'D48_DECLARED_COUPLING_METHOD_ONLY', results


def execute(project, context):
    """D48 analog native method. Excess noise blocks; partial SI stays NOT_MEASURED.

    input/flow109/D48.json binds netlist, testbench and coupling_model by path
    and sha256. Its TRAN analysis and windows explicitly declare aggressor,
    victim, baseline_v, from_s, to_s, max_noise_v and min_aggressor_swing_v.
    Required population, timing-window signoff, delay and physical provenance
    are outside this method result. Digital audit predicates are independent.
    """
    import shutil
    import uuid
    import analog_bound_measurements as measured
    from analog_native_flow import NativeCommands
    from flow109_admission import require_launch_admission, AdmissionRefusal
    import librelane_contract as launch
    from _atomic_artefact import write_json
    project = Path(project).resolve(strict=True)
    output = project / 'reports/flow109/D48' / uuid.uuid4().hex
    output.mkdir(parents=True)
    record = dict(step_id='D48', context_sha256=context.get('context_sha256'),
                  component_status='NOT_MEASURED', default_row_status='NOT_MEASURED',
                  flow109_acceptance='NOT_MEASURED', whole_flow_acceptance='NOT_MEASURED',
                  completed=False, native_started=False, delivery_accepted=False,
                  qualification='NOT_CLAIMED', outputs=[], windows=[],
                  required_population_status='NOT_MEASURED', timing_window_signoff=False,
                  timing_window_status='NOT_MEASURED',
                  delay_status='NOT_MEASURED', physical_binding_status='NOT_MEASURED')
    try:
        if (context.get('requested_step') != 'D48' or context.get('native_step_id') != 'flow109.D48'
                or context.get('resolved_row', {}).get('profile', {}).get('id') != 'analog_die'):
            raise ValueError('D48_CONTEXT_INVALID')
        record['launch_admission'] = require_launch_admission(project, 'flow109.D48', {'flow109_context': context})
        record['native_launch'] = launch.local_image_attestation()
        data, inputs = _d48_inputs(project)
        record['inputs'] = inputs
        binary = shutil.which('ngspice')
        if not binary:
            raise ValueError('D48_NGSPICE_UNAVAILABLE')
        bindings = _d48_bindings(data, binary)
        measured.emit_deck(Path(inputs['testbench']['path']).read_text(), bindings, output / 'curve.dat')
        runner = NativeCommands(project, output, '', record['native_launch']['image'], step='D48')
        native = measured.run_measurements(project, Path(inputs['netlist']['path']),
            Path(inputs['testbench']['path']), bindings, output, runner)
        record['native'] = native
        record['native_started'] = runner.count > 0
        native_path = output / 'native.json'
        write_json(native_path, native)
        status, reason, windows = _d48_consume(project, native, data, inputs)
        if _d48_inputs(project) != (data, inputs) or launch.local_image_attestation() != record['native_launch']:
            raise ValueError('D48_INPUT_OR_LAUNCH_CHANGED')
        record.update(component_status=status, reason=reason, windows=windows)
        files = [native_path, *(Path(path) for path in native.get('outputs', []) if path)]
        record['outputs'] = [{'path': str(path.relative_to(project)), 'sha256': measured.sha(path)}
                             for path in files if path.is_file()]
    except (ValueError, OSError, KeyError, TypeError, AttributeError, AdmissionRefusal, launch.Refusal) as exc:
        if record['component_status'] != 'FAIL':
            record['component_status'] = 'NOT_MEASURED'
        record['reason'] = 'D48_REFUSED: ' + str(exc)
    if record['component_status'] == 'FAIL':
        record['default_row_status'] = record['flow109_acceptance'] = 'FAIL'
    write_json(output / 'component.json', record)
    return record


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description="Check signal integrity / crosstalk analysis")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        print(f"ERROR: not a directory: {project_dir}", file=sys.stderr)
        return 2

    findings, stats = audit(project_dir)
    report = build_report(findings, stats, str(project_dir))
    out = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    print(out)
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
