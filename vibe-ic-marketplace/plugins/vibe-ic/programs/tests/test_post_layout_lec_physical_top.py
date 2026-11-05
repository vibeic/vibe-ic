"""Post-layout LEC must prove the routed physical wrapper hierarchy."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import phase3_one_shot_runner as R  # noqa: E402
import lec_post_layout_check as L  # noqa: E402


















def test_exact_netlist_stub_precedes_distribution_blackboxes_in_emitter():
    source = Path(R.__file__).read_text()
    emit = source[source.index("def _emit_lec_post_layout("):]
    emit = emit[:emit.index("# --- POST-LAYOUT EQUIVALENCE")]
    assert "blackbox = [stub_c] + blackbox" in emit
    assert "blackbox = blackbox + [stub_c]" not in emit













@pytest.mark.parametrize("functional", [True, False])
def test_gold_supply_strip_is_confined_to_gold_half(functional):
    ys = L.build_yosys_equiv_script(
        "gold.v", "gate.v", "lib.lib", "chip_top",
        strip_gold_ports=["VDD", "VSS"], functional_lib=functional)
    gold_half, gate_half = ys.split("design -stash gold", 1)
    assert "delete chip_top/w:VDD" in gold_half
    assert "delete chip_top/w:VSS" in gold_half
    assert "delete chip_top/w:VDD" not in gate_half
    assert "delete chip_top/w:VSS" not in gate_half


@pytest.mark.parametrize("functional", [True, False])
def test_supply_constants_survive_prep_pruning_with_native_yosys(tmp_path, functional):
    import shutil
    import subprocess
    yosys = shutil.which("yosys")
    if not yosys:
        pytest.skip("native Yosys required")
    lib = tmp_path / "empty.lib"
    lib.write_text("library(test) {}\n")
    gold, gate = tmp_path / "gold.v", tmp_path / "gate.v"
    gold.write_text("module chip(input a, input VDD, output y); assign y=a; endmodule\n")
    gate.write_text("module chip(input a, output y); wire VDD; assign y=a; endmodule\n")
    script = tmp_path / "proof.ys"
    def run():
        script.write_text(L.build_yosys_equiv_script(
            str(gold), str(gate), str(lib), "chip", functional_lib=functional,
            constant_gold_wires={"VDD": 1}, constant_gate_wires={"VDD": 1},
            strip_gold_ports=["VDD"]) + "\nequiv_status -assert\n")
        return subprocess.run([yosys, "-s", str(script)], capture_output=True, text=True)
    result = run()
    (tmp_path / "positive.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout[-1500:] + result.stderr
    assert "Equivalence successfully proven" in result.stdout
    gate.write_text(gate.read_text().replace("assign y=a", "assign y=~a"))
    mutant = run()
    (tmp_path / "mutant.log").write_text(mutant.stdout + mutant.stderr)
    assert mutant.returncode != 0
    assert "unproven" in mutant.stdout.lower() + mutant.stderr.lower()
