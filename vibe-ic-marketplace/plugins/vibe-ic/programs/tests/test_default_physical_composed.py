"""Accepted physical source controls for Steps16/31/37.5ip; no native claim."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _physical_current as current


def put(project, name, text):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path
















def test_current_inputs_are_in_scope(tmp_path):
    escaped = tmp_path.parent / "escaped_current.txt"
    escaped.write_text("outside")
    try:
        with pytest.raises(ValueError, match="CURRENT_PATH_ESCAPES"):
            current.entry(tmp_path, escaped)
    finally:
        escaped.unlink()




def test_kit_gate_refuses_unbound_views(tmp_path):
    import digital_hardmacro_check as kit
    from test_digital_hardmacro_gen import make_project
    make_project(tmp_path)
    hm = tmp_path / "phase3/stage4/hardmacro"
    hm.mkdir()
    put(tmp_path, "phase3/stage4/hardmacro/macro_a.v", "module macro_a(); endmodule\n")
    result = kit.run_audit(tmp_path)
    assert result.passed is False
    assert "IP_KIT_CURRENT_REFUSED" in {f.rule for f in result.findings}
