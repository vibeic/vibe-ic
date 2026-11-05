"""Read native interface SI failures; substrate coupling remains unmeasured."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile

from _atomic_artefact import write_json
import mixed_signal_interface_si_check as si_check


def execute(project, context):
    project = Path(project).resolve()
    parent = project / "reports/native_tools"
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="substrate-coupling-", dir=parent))
    output = attempt / "interface-si-consumer.json"
    rc = si_check.main([str(project), "--require-current-production", "--json", str(output)])
    consumer = json.loads(output.read_text())
    rules = {row.get("rule") for row in consumer.get("findings", [])
             if isinstance(row, dict)}
    measured_fail = bool(rules & {"FAILED_MEASUREMENT", "NATIVE_EXECUTION_FAILED"})
    status = "FAIL" if measured_fail else "NOT_MEASURED"
    reason = ("M05_MEASURED_INTERFACE_FAIL" if status == "FAIL" else
              "M05_SUBSTRATE_SUPPLY_MODEL_UNSUPPORTED_OPEN_DEFAULT")
    report = {"component_status": status, "reason": reason,
              "consumer": consumer, "consumer_returncode": rc,
              "unsupported_scope": "No qualified PDK substrate extraction/model; ordinary wire RC and advisory crosstalk are insufficient."}
    write_json(attempt / "result.json", report)
    return report
