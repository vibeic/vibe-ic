"""R6 Python execution closure controls; source/software evidence only."""
from pathlib import Path
import sys


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
from execution_provider_catalog import implementation_closure
































def test_nonstandard_script_suffix_preserves_local_import_closure(tmp_path):
    entry = tmp_path / 'entry.script'
    helper = tmp_path / 'helper.py'
    entry.write_text('import helper\n')
    helper.write_text('VALUE = 1\n')
    assert implementation_closure(entry, search=[tmp_path]) == {entry, helper}


def test_installed_native_closure_reports_observed_binding(tmp_path):
    import importlib.util
    native = Path(importlib.util.find_spec('cocotb.simulator').origin).resolve()
    entry = tmp_path / 'entry.py'; entry.write_text('import cocotb.simulator\n')
    try:
        closure = implementation_closure(entry, search=[native.parent.parent])
        actual = 'BOUND' if native in closure else 'UNBOUND'
    except ValueError:
        actual = 'REFUSED'
    assert actual == 'BOUND'
