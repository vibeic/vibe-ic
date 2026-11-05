"""Scoped producer/lineage SOFTWARE controls; no simulator or reset outcome fabricated.

Actual reset monitor outcomes are read separately from E's retained native controls.
"""

import _l10_execution as records
import testbench_gen as producer
from test_l10_execution_evidence import _project
from test_flow109_d13_metric_binding import put




def test_emitter_selects_exact_case_without_touching_original_tb(tmp_path):
    project,l10=_project(tmp_path,('vector_alpha','vector_beta'))
    put(project/'phase2/stage1/rtl/dut.v','module dut(input a,output y); assign y=a; endmodule\n')
    old=project/'phase2/stage1/sim/tb/tb_driver.v';before=(old.read_bytes(),old.stat().st_mtime_ns)
    out=project/'separate/tb';report={}
    assert producer.emit_unit_tbs(project,top='dut',out_dir=out,
        case_ids=['vector_alpha'],report=report)==1
    assert sorted(p.stem for p in out.glob('*.v'))==['vector_alpha']
    assert (old.read_bytes(),old.stat().st_mtime_ns)==before
    assert producer.emit_unit_tbs(project,top='dut',out_dir=out,
        case_ids=['unknown'],report={})==-2




def test_missing_selected_bench_refuses_without_clearing_original(tmp_path):
    project, l10 = _project(tmp_path)
    old = records.write_record(project,l10,[],producer='original')
    before = (old.read_bytes(),old.stat().st_mtime_ns)
    def forbidden(*a,**k):raise AssertionError('no native process permitted')
    report={}
    assert producer.run_unit_tbs(project, report=report, dispatch=forbidden,
        case_ids=['vector_alpha'],output_dir=project/'separate') == -2
    assert (old.read_bytes(),old.stat().st_mtime_ns)==before
