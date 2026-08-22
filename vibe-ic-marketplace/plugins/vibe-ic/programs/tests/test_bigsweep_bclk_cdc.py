import os,sys
from pathlib import Path
PROGRAMS=Path(os.environ.get("VIBE_PROGRAMS",str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0,str(PROGRAMS))
import latency_conformance_check as L
def test_bclk_recognized_aclk_pair():
    assert L._is_clock("bclk") is True
    assert L._is_clock("aclk") is True
def test_bclk_not_data_port():
    assert L._is_clock("block") is False
    assert L._is_clock("lock") is False
if __name__=="__main__":
    import pytest; raise SystemExit(pytest.main([__file__,"-v"]))
