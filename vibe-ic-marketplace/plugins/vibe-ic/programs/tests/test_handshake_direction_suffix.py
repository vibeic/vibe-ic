"""Direction-suffix aliases must reach the existing contract composer safely.

Synthetic naming permutations exercise the new behavior. A checked-in public
interface artifact is a negative control, not a claim to solve that document.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import canonical_primitive_synth as synth
from _hostpaths import require_repo


def description(valid="valid", ready="ready"):
    return f"""Module name: transport_stage
Registered handshake with a skid buffer. Preserve accepted words in order.
Use active-high asynchronous reset.
Input ports:
clk: clock
rst: reset
{valid}_i: upstream valid
{ready}_i: downstream ready
data_i [7:0]: input payload
Output ports:
{ready}_o: upstream ready
{valid}_o: downstream valid
data_o [7:0]: output payload
"""


@pytest.mark.parametrize("valid,ready", [("valid", "ready"), ("vld", "rdy")])
def test_aliases_emit_through_existing_cli(valid, ready, tmp_path):
    prompt = tmp_path / "description.txt"
    prompt.write_text(description(valid, ready))
    rtl = tmp_path / "candidate.v"
    result = subprocess.run(
        [sys.executable, str(PROGRAMS / "canonical_primitive_synth.py"),
         "--from-desc", str(prompt), "--out", str(rtl)],
        capture_output=True, text=True, timeout=30)
    # Observed process verdict: pre-fix returns DEFER/2, not a missing symbol.
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["shape"] == "elastic_handshake_stage"
    contract = synth.extract_handshake_contract(prompt.read_text())
    assert contract.up == {"valid": valid + "_i", "ready": ready + "_o",
                           "data": "data_i"}
    assert contract.down == {"valid": valid + "_o", "ready": ready + "_i",
                             "data": "data_o"}
    assert contract.unresolved == []
    # The existing queue scoreboard checks order, accepted-word conservation,
    # backpressure and needless-stall invariants on actual composed RTL.
    tb = tmp_path / "tb.v"
    tb.write_text(synth.emit_scoreboard_tb(contract))
    executable = tmp_path / "sim.vvp"
    compiled = subprocess.run(
        ["iverilog", "-g2012", "-s", "tb_transport_stage", "-o",
         str(executable), str(rtl), str(tb)],
        capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    simulated = subprocess.run(["vvp", str(executable)], capture_output=True,
                               text=True, timeout=30)
    assert simulated.returncode == 0, simulated.stdout + simulated.stderr
    assert "PASS" in simulated.stdout and "FAIL" not in simulated.stdout


@pytest.mark.parametrize("change,reason", [
    (lambda s: s.replace("ready_o: upstream ready\n", ""), "incomplete"),
    (lambda s: s.replace("valid_i: upstream valid", "valid_i: upstream valid\n"
                        "vld_i: another input-valid signal"), "ambiguous"),
    (lambda s: s.replace("valid_i: upstream valid", "valid_o: upstream valid")
               .replace("valid_o: downstream valid", "valid_i: downstream valid"),
     "direction"),
    (lambda s: s.replace("data_i [7:0]", "aux_valid: additional named channel\n"
                        "data_i [7:0]"), "mixed"),
])
def test_uncertain_alias_roles_are_named_deferrals(change, reason, tmp_path):
    desc = change(description())
    prompt = tmp_path / "description.txt"
    prompt.write_text(desc)
    output = tmp_path / "must_not_exist.v"
    result = subprocess.run(
        [sys.executable, str(PROGRAMS / "canonical_primitive_synth.py"),
         "--from-desc", str(prompt), "--out", str(output)],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert not output.exists()
    why = json.loads(result.stdout)["defer_reason"]
    assert why and why["route"] == "ai_author"
    assert reason in " ".join(why["unresolved"]).lower()


def test_alias_controls_cannot_be_selected_as_payload():
    dirs = {"valid_i": "in", "ready_i": "in", "clk": "in",
            "rst": "in", "data_i": "in"}
    assert synth._data_port_for("", dirs, "in", set()) == "data_i"


def test_storage_policy_is_still_required():
    desc = description().replace("Registered handshake with a skid buffer.",
                                 "A handshake interface.")
    assert synth.detect_shape(desc) is None
    why = synth.route_to_ai_reason(desc)
    assert why and any("storage" in item for item in why["unresolved"])


def test_existing_prefix_contract_is_unchanged():
    renames = {"valid_i": "up_valid", "ready_o": "up_ready",
               "valid_o": "dn_valid", "ready_i": "dn_ready",
               "data_i": "up_data", "data_o": "dn_data"}
    desc = description()
    for old, new in renames.items():
        desc = desc.replace(old, new)
    assert synth.detect_shape(desc) == "elastic_handshake_stage"
    contract = synth.extract_handshake_contract(desc)
    assert contract.up["data"] == "up_data"
    assert contract.down["data"] == "dn_data"
    assert contract.unresolved == []


def test_real_pin_table_does_not_gain_an_invented_ready_channel():
    root = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                        "programs", "tests", "fixtures", "real_benchmark")
    desc = (root / "datasheet_pin_table_interface.md").read_text()
    assert "Direction" in desc and "valid_in" in desc
    assert synth.detect_shape(desc) is None
