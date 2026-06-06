"""v0.2.91 — external-review improvement batch (two reviewer feedbacks
on flow v2.3, verified against the codebase).

Pins:
  * P0-1 three-natures density split: dfm_screen no longer re-gates
    density (Step 34 owns it) — cross-reference finding only, rc never
    1 from density (pinned in test_v0_2_85_dfm_screen.py);
  * R1 UPF deliverable: l21_to_upf_emit renders L21 power intent into
    IEEE-1801 UPF + self-validates with the pre-existing
    upf_syntax_check (which finally has an input);
  * R2 post-synth power preview emit (source pin);
  * R3 ip_integration_check: macro file-set alignment / lib corner
    coverage / L21 supply consistency;
  * P1-5 PENDING_FOUNDRY items flow into the tapeout checklist
    reviewer_todo;
  * P2-6 advanced-node trigger (pinned in test_v0_2_85_dfm_screen.py).
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ip_integration_check as IIC   # noqa: E402
import l21_to_upf_emit as UPF        # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_P3_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()
_YAML = (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text()


# ── R1: UPF emission ────────────────────────────────────────────────────────

def _l21_project(tmp_path, domains):
    g = tmp_path / "phase1" / "generated_docs"
    g.mkdir(parents=True)
    (g / "L21_POWER_INTENT.json").write_text(json.dumps({
        "fields": {"power_domains": domains,
                   "isolation_cells": [{"name": "io_iso", "domain":
                                        domains[0]["name"],
                                        "clamp_value": 0}] if domains else [],
                   "level_shifters": []}}))
    return tmp_path


def test_upf_emitted_and_self_validated(tmp_path):
    p = _l21_project(tmp_path, [
        {"name": "core", "supply": "VDD_CORE", "retention": True},
        {"name": "io", "supply": "VDD_IO"}])
    rc = UPF.main([str(p), "--top", "chip_top"])
    assert rc == 0
    upf = (p / "phase2/stage2/constraints/chip_top.upf").read_text()
    assert "create_power_domain PD_core" in upf
    assert "create_power_domain PD_io" in upf
    assert "set_retention RET_core" in upf
    assert "set_isolation ISO_io_iso" in upf
    assert "do not consume UPF" in upf  # honesty header


def test_upf_skips_without_domains(tmp_path):
    p = _l21_project(tmp_path, [])
    assert UPF.main([str(p)]) == 2
    assert not (p / "phase2/stage2/constraints/chip_top.upf").exists()


# ── R3: IP integration checklist ───────────────────────────────────────────

def _macro(tmp_path, name="sram0", lef=True, gds=True,
           libs=("tt",), supply=None):
    d = tmp_path / "input" / "pdk_local" / "vendorx" / name
    d.mkdir(parents=True)
    if lef:
        (d / f"{name}.lef").write_text("MACRO x\nEND x\n")
    if gds:
        (d / f"{name}.gds").write_bytes(b"\x00\x06gds")
    for c in libs:
        body = "library(x){\n"
        if supply:
            body += f'  voltage_map({supply}, 1.8);\n'
        body += "}\n"
        (d / f"{name}_{c}.lib").write_text(body)
    (d / f"{name}.v").write_text(f"module {name}();\nendmodule\n")
    return tmp_path


def test_complete_multicorner_macro_passes(tmp_path):
    p = _macro(tmp_path, libs=("tt", "ss", "ff"))
    rep = IIC.audit(p)
    assert rep["rc"] == 0 and rep["verdict"] == "PASS", rep


def test_missing_gds_fails_fileset(tmp_path):
    p = _macro(tmp_path, gds=False)
    rep = IIC.audit(p)
    assert rep["rc"] == 1
    assert any(f["rule"] == "IP_FILESET_INCOMPLETE" for f in rep["findings"])


def test_single_corner_lib_is_review(tmp_path):
    p = _macro(tmp_path, libs=("tt",))
    rep = IIC.audit(p)
    assert rep["rc"] == 0 and rep["verdict"] == "PASS_WITH_REVIEW"
    assert any(f["rule"] == "IP_SINGLE_CORNER_LIB" for f in rep["findings"])


def test_l21_supply_mismatch_flagged(tmp_path):
    p = _macro(tmp_path, libs=("tt", "ss"), supply="VDD_PLL")
    g = tmp_path / "phase1" / "generated_docs"
    g.mkdir(parents=True)
    (g / "L21_POWER_INTENT.json").write_text(json.dumps({
        "fields": {"power_domains": [
            {"name": "core", "supply": "VDD_CORE"}]}}))
    rep = IIC.audit(p)
    assert any(f["rule"] == "IP_POWER_DOMAIN_MISMATCH"
               for f in rep["findings"])


def test_no_macros_vacuous(tmp_path):
    assert IIC.audit(tmp_path)["rc"] == 2


def test_yaml_step15_wires_ip_check():
    assert "ip_integration_check ." in _YAML


# ── R2: post-synth power preview (source pin) ──────────────────────────────

def test_power_preview_emitted_at_pre_layout_stage():
    i = _P3_SRC.index("pre_pnr_power_preview.rpt")
    window = _P3_SRC[i - 900:i + 700]
    assert "_emit_power_report" in window
    assert "review R2" in window


# ── P1-5: PENDING_FOUNDRY → tapeout checklist ──────────────────────────────

def test_pending_foundry_items_reach_checklist(tmp_path):
    hd = tmp_path / "phase3" / "stage4" / "foundry_handoff"
    hd.mkdir(parents=True)
    (hd / "mask_spec.json").write_text(json.dumps({
        "pdk": "x", "cell_count": 1,
        "PENDING_FOUNDRY_mask_layers": "Author: ...",
        "PENDING_FOUNDRY_reticle_steppers": "Author: ..."}))
    plugin = Path(__file__).resolve().parent.parent.parent
    r = subprocess.run(
        [sys.executable,
         str(plugin / "programs" / "tapeout_checklist_gen.py"),
         str(tmp_path)],
        capture_output=True, text=True)
    rep = json.loads(
        (tmp_path / "reports/audit/tapeout_checklist.json").read_text())
    assert len(rep["pending_foundry_items"]) == 2
    assert any("PENDING_FOUNDRY open item" in t
               for t in rep["reviewer_todo"])
