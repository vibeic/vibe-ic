"""Production Step-16 dispatch controls; source/software evidence only."""
from pathlib import Path
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))




















def test_copied_dispatcher_dependency_shadow_still_refused(tmp_path, monkeypatch):
    from execution_provider_catalog import proven_dispatcher_closure
    worker = PROGRAMS / 'execution_release_worker.py'
    entry = tmp_path / 'copied_worker.py'
    entry.write_bytes(worker.read_bytes())
    monkeypatch.setenv('PYTHONPATH', str(PROGRAMS))
    (tmp_path / 'execution_release_rows.py').write_text('ROWS = {}\n')
    with pytest.raises(ValueError, match='copied worker import resolution differs'):
        proven_dispatcher_closure(entry, worker)
