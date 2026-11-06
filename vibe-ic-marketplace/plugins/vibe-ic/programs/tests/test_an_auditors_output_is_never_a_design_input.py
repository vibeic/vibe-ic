"""An AUDITOR output is never a design input -- and a DIRECTORY cannot say which is which.

R-0915-151. `design_input_digest` subtracts the auditor's own writes before hashing the
design, so that "the tally moved" can be read as a statement about the DESIGN. The first
cut of that subtraction identified an auditor output by its LOCATION: anything under
`reports/audit/`. That is wrong here for a reason specific to this repo, and these arms are
the measurement of it.

`_path_layout.report_path` is an AUTO-ROUTER: a report name whose head it does not
recognise is routed to `reports/audit/` as the catch-all. So that directory holds
PRODUCER records and even the IC-expert's own answer file, side by side with the audit --
every fixture path below is produced by calling the real router, so these arms cannot
drift away from where the flow actually writes.

The two halves, and both must hold at once:
  * a producer record or a human/AI answer file that happens to sit there IS a design
    input: editing it must move the design hash, and a tally that moves with it is
    attributable to the design;
  * the auditor's own document is STILL not one, identified by what it IS -- a receipt
    stamping `program: flow_compliance_check`, a `*.superseded-<n>.json` minted only by the
    republish, and the completion audit named by its EXACT path, because MEASURED it
    carries no `program` key of its own (`flow_compliance_check.py` stamps the compliance
    RECEIPT, not the audit document).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _path_layout as _pl               # noqa: E402

_AUDITOR = "flow_compliance_check"






@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A project with a real design input, and the audit directory's real tenants."""
    p = tmp_path / "proj"
    (p / "input").mkdir(parents=True)
    (p / "input" / "spec.md").write_text("# a counter\n")
    # Every one of these is written by a PRODUCER (or, for the answer file, by the
    # IC expert); the router is what puts them under reports/audit/.
    for name, body in (
            ("expert_parse_track.json", {"program": "phase1_expert_parse_track",
                                         "layers": ["L1"]}),
            ("xor_allow_macros.json", {"allow": ["sram_16x8"]}),
            ("phase1_sufficiency.json", {"sufficient": True}),
            ("phase1/l21_rail_producers.json", {"rails": ["VDD"]}),
            ("phase2/gates/sdc_gen.json", {"program": "sdc_gen", "clocks": 1}),
            ("phase1/expert_parse_track_pack/l_doc_expectations.json",
             {"L1": {"expected": 4}}),
    ):
        f = _pl.report_path(p, name)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(body))
    return p


#: The producer files the router puts in the auditor's directory, by the NAME the
#: producer passes to the router -- not by the routed path, so the arm follows the
#: router if the routing ever changes.
PRODUCER_RECORDS = [
    "expert_parse_track.json",
    "xor_allow_macros.json",
    "phase1_sufficiency.json",
    "phase1/l21_rail_producers.json",
    "phase2/gates/sdc_gen.json",
    "phase1/expert_parse_track_pack/l_doc_expectations.json",
]




















def test_the_writer_removes_its_own_temp_when_the_replace_did_not_happen(tmp_path):
    """Driven through the real writer's own expression, with the replace made to fail.

    Not a hand-placed file: the arm reproduces the writer's shape -- write the temp, then
    `os.replace` raises -- and asserts the `finally` removed it and re-raised the ORIGINAL
    error rather than a cleanup error.
    """
    import os as _os
    audit_path = tmp_path / "reports" / "audit" / "phase23_completion_audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = audit_path.with_name(f"{audit_path.name}.{_os.getpid()}.tmp")

    boom = OSError(28, "No space left on device")

    def _replace(a, b):
        raise boom

    # the writer's shape, verbatim in structure
    with pytest.raises(OSError) as caught:
        try:
            tmp.write_text('{"verdict": "PASS"}')
            _replace(tmp, audit_path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    assert caught.value is boom, "the cleanup masked the original failure"
    assert not tmp.exists(), "the temp outlived the write that created it"
    assert not audit_path.exists()
