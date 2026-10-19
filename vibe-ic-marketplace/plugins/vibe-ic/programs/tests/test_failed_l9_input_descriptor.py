"""Public descriptors must not publish a successful INPUT roster from failed L9."""
from pathlib import Path
import json
import os
import subprocess
import sys

import pytest

PROGRAM = Path(os.environ.get("DESCRIPTOR_TEST_PROGRAM",
    str(Path(__file__).resolve().parents[1] / "phase1_doc_one_shot_runner.py")))
SOURCE = """# Hardware Interfaces
The module **`neutral`** has these interfaces.
- Primary Clock: **`clk_i`**
- Other Clocks: **`clk_edn_i`**

| Signal | Direction | Width | Description |
|---|---|---:|---|
| `d_i` | input | 1 | Data input |
| `q_o` | output | 1 | Data output |
| rst_n | input | 1 | Active-low reset |

| Clock | Reset | Polarity | Assertion | Release | Release synchronizer stages |
|---|---|---|---|---|---|
| clk_i | rst_n | active-low | asynchronous | synchronous to clk_i | 2 |
| clk_edn_i | rst_n | active-low | asynchronous | synchronous to clk_edn_i | 2 |
"""


@pytest.mark.parametrize("flag", ["--describe-interface-binding-input",
                                  "--describe-qualified-output-input"])
def test_failed_l9_refuses_descriptor_until_real_producer_recovers(tmp_path, flag):
    project = tmp_path / "project"
    docs = project / "input/docs"
    rtl = project / "phase2/stage1/rtl"
    docs.mkdir(parents=True)
    rtl.mkdir(parents=True)
    (docs / "interfaces.md").write_text(SOURCE)
    (rtl / "neutral.sv").write_text(
        "module neutral(input logic clk_i, clk_edn_i, rst_n, d_i, output logic q_o);\n"
        "always_ff @(posedge clk_i or negedge rst_n)\n"
        "if (!rst_n) q_o <= 0; else q_o <= d_i;\nendmodule\n")
    base = [sys.executable, str(PROGRAM), str(project),
            "--ic-name", "neutral", "--pdk", "sky130A"]
    journal = []

    def run(label, options=()):
        done = subprocess.run(base + list(options), capture_output=True, text=True)
        (tmp_path / (label + ".stdout")).write_text(done.stdout)
        (tmp_path / (label + ".stderr")).write_text(done.stderr)
        journal.append({"label": label, "argv": base + list(options),
                        "rc": done.returncode})
        (tmp_path / "EXECUTION.json").write_text(json.dumps(journal, indent=2))
        return done

    l9 = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    run("normal-producer")
    assert not json.loads(l9.read_text()).get("phase1_step_error")
    good_bytes = l9.read_bytes()
    good = run("normal-descriptor", [flag])
    assert good.returncode == 0, good.stdout + good.stderr
    before = json.loads(good.stdout)
    assert {r["name"]: r["width"] for r in before["interface"]}["clk_i"] == 1
    assert l9.read_bytes() == good_bytes

    # A real ordinary producer refuses deliberately stale author INPUT.
    binding = project / "plugin_input/interface-bindings.json"
    binding.parent.mkdir()
    binding.write_text(json.dumps({"schema": "vibeic.phase1-interface-bindings.v1",
        "input_files": {}, "interface": [], "context": {}, "physical_ports": [],
        "logical_bindings": [], "decisions": []}))
    l9.rename(tmp_path / "normal-L9.before-refusal.json")
    run("refused-producer")
    failed_bytes = l9.read_bytes()
    failed = json.loads(failed_bytes)
    assert failed.get("phase1_step_error") is True
    assert "input_files" in failed.get("error_message", "")
    refused = run("refused-descriptor", [flag])
    actual_rc = refused.returncode
    # Assert the real CLI value, not absence of a made-up report.
    assert actual_rc == 2, {"actual_rc": actual_rc, "stdout": refused.stdout,
                             "stderr": refused.stderr}
    assert "failed L9" in refused.stderr
    assert refused.stdout.strip() == ""
    assert l9.read_bytes() == failed_bytes

    # Recover by rerunning the producer from unchanged source documents.
    binding.rename(tmp_path / "stale-author-input.json")
    l9.rename(tmp_path / "failed-L9.before-recovery.json")
    run("recovered-producer")
    assert not json.loads(l9.read_text()).get("phase1_step_error")
    restored_bytes = l9.read_bytes()
    restored = run("recovered-descriptor", [flag])
    assert restored.returncode == 0, restored.stdout + restored.stderr
    after = json.loads(restored.stdout)
    assert after["input_files"] == before["input_files"]
    assert after["interface"] == before["interface"]
    assert l9.read_bytes() == restored_bytes
