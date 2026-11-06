"""D01 declaration owner/report/reader seam; not full Phase-1 acceptance.

Document extraction, packaging and expert analysis are out-of-scope edges.
The real main, declaration emitter, owner hook and routed report writer run;
no test constructs a successful D01 producer receipt.
"""
from __future__ import annotations

import os
from pathlib import Path


import fault_scan_chain_insert as scan












def test_l20_canonical_d01_existing_accepted_readset():
    import dft_atpg_coverage_check as applicability
    import flow_compliance_check as compliance
    project = Path(os.environ['L20_CANONICAL_SUBJECT'])
    binding, problems = scan.load_d09_dft_contract(project)
    assert binding is not None and problems == [], problems
    observed = applicability.l20_dft_applicability(project)
    assert observed['asserts_dft'] is False, observed
    assert observed['source_authority']['declaration'] == {
        'path': binding['path'], 'sha256': binding['sha256']}
    assert compliance._check_condition(project, {'l_doc_declares': {
        'l_doc': 'L20', 'all_absent': {'scan_chains': []}}}) is False
