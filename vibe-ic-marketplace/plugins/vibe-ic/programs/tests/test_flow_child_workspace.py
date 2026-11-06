"""Fresh child public runs receive authored inputs, without reusing a run."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import flow_macro_views as macros


HOOK = '''import cocotb
@cocotb.test()
async def check_tile(dut):
    assert dut.z.value == dut.a.value
    print("PROFESSIONAL_TB PASS")
'''


def supplied(project):
    docs = project / "input/docs"
    docs.mkdir(parents=True)
    (docs / "requirements.md").write_text("Harden compute_tile for integration.\n")
    source = project / "input/design_src/tile.v"
    source.parent.mkdir()
    source.write_text("module compute_tile(input a, output z); assign z=a; endmodule\n")
    return source.parent / "config.json", {"DESIGN_NAME": "compute_tile", "VERILOG_FILES": [str(source)]}


def run_child(project, config, raw, observe):
    def public(argv):
        observe(Path(argv[2]))
        return subprocess.CompletedProcess(argv, 9, "", "observed fresh public-entry inputs")
    return macros._child(project, "compute_tile", config, raw, "sky130A", SimpleNamespace(run=public))


def hook(child):
    return child / "phase2/stage1/sim_professional/compute_tile/expert_reference_tb.py"


def test_supplied_child_hook_reaches_the_professional_consumer(tmp_path):
    from professional_tb_gen import _load_expert_reference_tb
    config, raw = supplied(tmp_path)
    (config.parent / "expert_reference_tb.py").write_text(HOOK)

    def observe(child):
        assert hook(child).read_text() == HOOK
        assert _load_expert_reference_tb(hook(child).parent) == HOOK

    child, summary, code = run_child(tmp_path, config, raw, observe)
    assert summary == {} and code == 9
    assert hook(child).is_file()


def test_selected_child_rtl_and_authored_hook_survive_fresh_runs(tmp_path):
    from flow_config import build_config
    config, raw = supplied(tmp_path)
    workspace = tmp_path / "work/flow/children/compute_tile"
    rtl = workspace / "phase2/stage1/rtl/tile.v"
    rtl.parent.mkdir(parents=True)
    declaration = workspace / "plugin_output/declaration.json"
    declaration.parent.mkdir()
    declaration.write_text(json.dumps({"top_module": "compute_tile"}))
    authored = hook(workspace)
    authored.parent.mkdir(parents=True)
    (config.parent / "expert_reference_tb.py").write_text("# original supplied model\n")
    header = config.parent / "nested/limits.vh"
    header.parent.mkdir()
    header.write_text("`define VALUE 1\n")
    seen = []
    for version in (1, 2):
        repaired = ('`include "nested/limits.vh"\n'
                    f"module compute_tile(input a, output z); assign z=a^{version & 1}; endmodule\n")
        rtl.write_text(repaired)
        authored.write_text(HOOK + f"# authored version {version}\n")

        def observe(child):
            seen.append(child)
            assert (child / "input/rtl/tile.v").read_text() == repaired
            assert (child / "input/rtl/nested/limits.vh").read_text() == header.read_text()
            assert hook(child).read_text() == authored.read_text()
            # Normal Phase 2 selection must remain authoritative after staging.
            canonical = child / "phase2/stage1/rtl/tile.v"
            canonical.parent.mkdir(parents=True)
            canonical.write_text(repaired + "// current Phase 2 selection\n")
            docs = child / "phase1/generated_docs"
            docs.mkdir(parents=True)
            (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "compute_tile"}))
            native = build_config(child, route="ip", pdk="sky130A")
            assert native["VERILOG_FILES"] == [str(canonical)]

        _, summary, code = run_child(tmp_path, config, raw, observe)
        assert summary == {} and code == 9
    assert len(set(seen)) == 2
    assert Path(raw["VERILOG_FILES"][0]).read_text().endswith("assign z=a; endmodule\n")
