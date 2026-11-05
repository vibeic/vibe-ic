"""Scoped producer/lineage SOFTWARE controls; no simulator or reset outcome fabricated.

Actual reset monitor outcomes are read separately from E's retained native controls.
"""

import _l10_execution as records
import testbench_gen as producer
from test_l10_execution_evidence import _project








def test_missing_selected_bench_refuses_without_clearing_original(tmp_path):
    project, l10 = _project(tmp_path)
    old = records.write_record(project,l10,[],producer='original')
    before = (old.read_bytes(),old.stat().st_mtime_ns)
    def forbidden(*a,**k):raise AssertionError('no native process permitted')
    report={}
    assert producer.run_unit_tbs(project, report=report, dispatch=forbidden,
        case_ids=['vector_alpha'],output_dir=project/'separate') == -2
    assert (old.read_bytes(),old.stat().st_mtime_ns)==before
