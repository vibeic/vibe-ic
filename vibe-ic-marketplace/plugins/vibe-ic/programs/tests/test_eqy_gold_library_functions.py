import shutil
import subprocess

import pytest
import librelane_eqy as native


@pytest.mark.parametrize('changed', [False, True])
def test_gold_blackbox_uses_same_native_liberty_functions(tmp_path, changed):
    if not shutil.which('eqy') or not shutil.which('yosys'):
        pytest.skip('native EQY and Yosys required')
    rtl = tmp_path/'top.sv'
    rtl.write_text('(* blackbox *) module INV(input A,output Y); endmodule\n'
        'module top(input [1:0] a,output y); wire x=a[0]^a[1]; INV u(x,y); endmodule\n')
    mapped = tmp_path/'mapped.v'
    mapped.write_text('module top(input [1:0] a,output y); assign y=' +
                      ('' if changed else '~') + '(a[0]^a[1]); endmodule\n')
    liberty = tmp_path/'cells.lib'
    liberty.write_text('library(neutral) {cell(INV) {pin(A) {direction:input;}'
                       'pin(Y) {direction:output; function:"!A";}}}\n')
    path = tmp_path/'top.eqy'
    path.write_text(native.eqy_script('top',[rtl],mapped,str(liberty),
                                     synthesis={'USE_SLANG':True}))
    run = subprocess.run(['timeout','--kill-after=2','10','eqy','-f','-d',
                          str(tmp_path/'scratch'),str(path)],
                         cwd=tmp_path,capture_output=True,text=True)
    (tmp_path/'native.log').write_text(run.stdout+run.stderr)
    assert run.returncode != 124, 'native EQY stalled on the unmodelled gold cell'
    assert (tmp_path/'scratch'/('FAIL' if changed else 'PASS')).is_file(), run.stdout+run.stderr
