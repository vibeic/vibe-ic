"""Step31 uses current full-GDS LVS; DEF wiring is a disclosed triage arm."""
import json
from pathlib import Path
import pytest
import librelane_signoff_evidence as evidence


def test_default_lvs_consumers_refuse_a_retained_report_without_current_chain(tmp_path):
    report=tmp_path/'reports/phase3/lvs.rpt'; report.parent.mkdir(parents=True)
    report.write_text('Final result: Circuits match uniquely.\n')
    record=evidence.obligation(tmp_path,'lvs')
    assert record is not None, 'default LVS consumer still routes to DEF authority'
    assert record['verdict']=='NOT_MEASURED'
