"""v0.2.81 — #449: generator↔checker TODO semantics aligned.

Field-audit residual of #446: the generator's LEGIT foundry-supplied
fields were named TODO_* and the checker ERRORs on any \\bTODO\\b token
— the generator's own fresh output could never pass its own gate
without a waiver.

Pins (acceptance criteria from the issue):
  * fresh v0.2.81 generator output (no design-derivable TODO) runs the
    checker → PASS, with PENDING_FOUNDRY_* listed as NAMED open items
    (INFO finding + report field), not ERROR;
  * a design-derivable TODO planted in a member → still ERROR
    (FOUNDRY_HANDOFF_TODO_MARKERS);
  * generator emits zero \\bTODO\\b tokens into the pack (source +
    output pins) — foundry-supplied fields use PENDING_FOUNDRY_*.

chip-AGNOSTIC: synthetic generic fixtures.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import foundry_handoff_pack_gen as FH  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
CHECKER = PLUGIN / "programs" / "foundry_handoff_package_check.py"


def _proj(tmp_path):
    p = tmp_path / "alpha"
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "chip_top.sv").write_text("module top_a(input clk);\nendmodule\n")
    synth = p / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "netlist.v").write_text(
        "module top(input clk);\n  buf_cell _0_ (.A(clk), .X());\nendmodule\n")
    (p / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    gds = p / "phase3" / "stage4" / "gds"
    gds.mkdir(parents=True)
    (gds / "alpha.gds").write_bytes(b"\x00\x06\x00\x02alpha")
    lib = p / "input" / "pdk" / "liberty"
    lib.mkdir(parents=True)
    (lib / "examplepdk_sc_hd__tt.lib").write_text("library(x){}")
    return p


def _run_checker(p):
    r = subprocess.run(
        [sys.executable, str(CHECKER), str(p),
         "--json", str(p / "gate.json")],
        capture_output=True, text=True)
    return r.returncode, json.loads((p / "gate.json").read_text())


def test_fresh_generator_output_passes_own_gate(tmp_path):
    p = _proj(tmp_path)
    assert FH.main([str(p)]) == 0
    rc, rep = _run_checker(p)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    assert rep["pending_foundry_fields"], "open items must be listed"
    assert any(f["rule"] == "FOUNDRY_HANDOFF_PENDING_FOUNDRY"
               and f["severity"] == "INFO" for f in rep["findings"])
    assert not any(f["rule"] == "FOUNDRY_HANDOFF_TODO_MARKERS"
                   for f in rep["findings"])


def test_design_derivable_todo_still_errors(tmp_path):
    p = _proj(tmp_path)
    FH.main([str(p)])
    # plant a design-derivable TODO residue into a member
    ms = p / "phase3/stage4/foundry_handoff/mask_spec.json"
    d = json.loads(ms.read_text())
    d["gds_path"] = "TODO fill me"
    ms.write_text(json.dumps(d))
    rc, rep = _run_checker(p)
    assert rc == 1
    assert any(f["rule"] == "FOUNDRY_HANDOFF_TODO_MARKERS"
               for f in rep["findings"])


def test_underscore_suffixed_todo_key_still_errors(tmp_path):
    # v0.2.82 field-audit hardening: `TODO_foo` keys (underscore = word
    # char, no \b boundary) must not bypass the design-derivable scan
    p = _proj(tmp_path)
    FH.main([str(p)])
    ms = p / "phase3/stage4/foundry_handoff/mask_spec.json"
    d = json.loads(ms.read_text())
    d["TODO_sneaky_field"] = "hand-crafted bypass attempt"
    ms.write_text(json.dumps(d))
    rc, rep = _run_checker(p)
    assert rc == 1
    assert any(f["rule"] == "FOUNDRY_HANDOFF_TODO_MARKERS"
               for f in rep["findings"])


def test_generator_emits_no_todo_tokens(tmp_path):
    p = _proj(tmp_path)
    FH.main([str(p)])
    hd = p / "phase3/stage4/foundry_handoff"
    for member in hd.iterdir():
        if member.suffix.lower() in (".gds",):
            continue
        txt = member.read_text(errors="replace")
        assert not re.search(r"\bTODO\b|\bTBD\b", txt), member.name
    # foundry-supplied fields use the structured namespace
    ms = json.loads((hd / "mask_spec.json").read_text())
    assert "PENDING_FOUNDRY_mask_layers" in ms
    kit = json.loads((hd / "corner_test_vectors.json").read_text())
    assert "PENDING_FOUNDRY_voltage_corners" in kit
