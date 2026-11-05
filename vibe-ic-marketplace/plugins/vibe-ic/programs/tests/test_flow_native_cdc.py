import json
from pathlib import Path
import shutil

import pytest

from flow_native_adapters import execute


@pytest.mark.parametrize("declared", [True, False])
def test_declared_synchronous_reset_needs_no_intermediate_intent_file(tmp_path, declared):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    rtl = tmp_path / "unit.v"
    rtl.write_text("module unit(input clk,reset_n,d,output reg q); "
                   "always @(posedge clk) if(!reset_n) q<=0; else q<=d; endmodule\n")
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L8.json").write_text(json.dumps({"reset_domains": [
        {"name": "reset_n", "polarity": "active_low", **({"sync": "synchronous"} if declared else {})}]}))
    result = execute(tmp_path, tmp_path / "output", {"adapter": "cdc", "rtl": [str(rtl)], "top": "unit"}, {})
    report = next(Path(p) for p in result["reports"] if p.endswith("cdc.json"))
    actual = json.loads(report.read_text())
    assert result["metrics"]["unresolved_crossings"] == 0
    assert actual["resets"]["unresolved_role_candidates"] == 0


def test_native_asynchronous_reset_cycle_still_fails(tmp_path):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    rtl = tmp_path / "cycle.v"
    rtl.write_text("module cycle(input clk,d,output reg q,r); "
                  "always @(posedge clk or posedge r) if(r) q<=0; else q<=d; "
                  "always @(posedge clk or posedge q) if(q) r<=0; else r<=d; endmodule\n")
    result = execute(tmp_path, tmp_path / "output", {"adapter": "cdc", "rtl": [str(rtl)], "top": "cycle"}, {})
    assert result["metrics"]["unresolved_crossings"] > 0
