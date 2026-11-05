"""Native pre-layout mixed-signal simulation and its engineering consumers."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile

from _atomic_artefact import write_json
import mixed_signal_cosim_check as cosim_check
import mixed_signal_m3_run as m3

def _literal_measured_failures(project):
    """Return simulation error counters that cannot be a successful M02 result.

    Scenario-specific voltage limits remain owned by L22.  In contrast, a
    sampled wrapper with response errors or unknown observations did not
    successfully correlate, even if an incomplete criteria list allowed the
    scenario's self-verdict to say PASS.
    """
    try:
        body = m3.read(project / m3.COSIM)
    except m3.Refusal:
        return []
    failures = []
    for row in body.get("scenarios", []) if isinstance(body.get("scenarios"), list) else []:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            continue
        for name in ("response_mismatches", "response_errors", "unknown_samples"):
            value = metrics.get(name)
            if (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and value > 0):
                failures.append({"scenario": row.get("id"), "metric": name,
                                 "measured": value, "required": 0})
    return failures


def execute(project, context):
    project = Path(project).resolve()
    parent = project / "reports/native_tools"
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="mixed-prelayout-", dir=parent))
    status, reason, producer, audit = "NOT_MEASURED", "M02_NOT_MEASURED", None, None
    literal_failures = []
    try:
        from _mixed_signal_native import CONTRACT
        contract = m3.read(project / CONTRACT)
        top = context.get("top") or contract.get("top")
        producer = m3.produce(project, top, context.get("container", "host"))
        audit = m3.audit(project, "cosim")
        output = attempt / "cosim-consumer.json"
        gate_rc = cosim_check.main([str(project), "--require-current-production",
                                    "--json", str(output)])
        gate = json.loads(output.read_text())
        literal_failures = _literal_measured_failures(project)
        measured_fail = (producer.get("cosim_verdict") == "FAIL"
                         or audit.get("verdict") == "FAIL" or gate_rc == 1
                         or bool(literal_failures))
        if measured_fail:
            status, reason = "FAIL", "M02_MEASURED_FAIL"
        elif (producer.get("cosim_verdict") == "PASS" and audit.get("verdict") == "PASS"
              and gate_rc == 0 and gate.get("passed") is True):
            status, reason = "PASS", "M02_CURRENT_NATIVE_COSIM_COMPONENT_PASS"
        else:
            reason = "M02_NATIVE_COSIM_INCOMPLETE"
    except (m3.Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        rule = getattr(exc, "rule", "M02_INVALID_EVIDENCE")
        status = "FAIL" if rule in ("FAILED_MEASUREMENT", "NATIVE_EXECUTION_FAILED") else "NOT_MEASURED"
        reason = rule + ": " + str(exc)
    report = {"component_status": status, "reason": reason,
              "producer": producer, "cosim_audit": audit,
              "literal_measured_failures": literal_failures,
              "scope": "declared pre-layout mixed component; physical SI is unmeasured"}
    write_json(attempt / "result.json", report)
    return report
