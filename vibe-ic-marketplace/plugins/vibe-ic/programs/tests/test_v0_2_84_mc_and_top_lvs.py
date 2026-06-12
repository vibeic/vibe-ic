"""v0.2.84 — P1 capability batch: real analog Monte-Carlo yield +
real mixed-signal top-merged LVS.

The verified gaps (flow-completeness review):
  * the A4 gate enforced mc_yield_pct >= 95% but NOTHING computed the
    value (MCP monte_carlo_n was a dead parameter) — the gate was
    decorative;
  * M1 mixed_signal_merge_check was PASS-on-presence: a merged GDS
    existed → PASS, no LVS ever ran on it.

Pins:
  * analog_mc_yield_run: N seeded foundry-statistical-section runs →
    per-spec yield, worst-spec mc_yield_pct written into
    corner_results.json (the EXISTING A4 gate fires on it); honest
    SKIP (rc 2) when deck/specs/tooling absent;
  * MCP eda_spice_corner consumes monte_carlo_n (source pin);
  * mixed_signal_top_lvs_run merges (KLayout) + extracts (Magic) +
    compares (netgen) and writes merge.json/top_lvs.json with the
    REAL verdict;
  * M1 gate: presence-without-LVS → FAIL; LVS PASS → PASS; LVS FAIL
    → FAIL.

chip-AGNOSTIC: monkeypatched container + synthetic fixtures.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_mc_yield_run as MC                 # noqa: E402
import analog_corner_sweep_check as ACS          # noqa: E402
import analog_real_corner_sweep as ARS           # noqa: E402
import mixed_signal_top_lvs_run as TL            # noqa: E402


def _find_mcp_src() -> Path:
    """Resolve mcp-eda-server/src/index.js relative to the repo root by
    walking up from this test file — NEVER a hardcoded absolute home path
    (the old `/home/reyerchu/...` literal passed locally but does not
    exist on the CI runner at `/home/runner/work/...`, so the test failed
    the moment the suite ran to completion). The mcp-eda-server is an
    OPTIONAL sibling of the plugin marketplace, so the test skips when it
    is absent rather than erroring."""
    for anc in Path(__file__).resolve().parents:
        cand = anc / "mcp-eda-server" / "src" / "index.js"
        if cand.is_file():
            return cand
    return Path("mcp-eda-server/src/index.js")  # sentinel; skip below


MCP_SRC = _find_mcp_src()


# ── analog_mc_yield_run ─────────────────────────────────────────────────────

def _mc_project(tmp_path):
    blk = tmp_path / "phase2" / "analog" / "ldo"
    blk.mkdir(parents=True)
    (blk / "ldo.sp").write_text(
        "* ldo deck\n.meas dc vout FIND v(out) AT=1u\n.end\n")
    spec = tmp_path / "phase1" / "analog" / "ldo"
    spec.mkdir(parents=True)
    (spec / "spec.json").write_text(json.dumps({
        "specs": [{"name": "vout", "min": 1.7, "max": 1.9}]}))
    return tmp_path


def _fake_ngspice(values):
    """Sequence of vout values, one per MC iteration."""
    it = iter(values)
    def fake(container, sp):
        v = next(it)
        return True, {"vout": v}, f"vout = {v}\n"
    return fake


def test_mc_yield_written_and_gate_fires(tmp_path, monkeypatch):
    p = _mc_project(tmp_path)
    monkeypatch.setattr(ARS, "_ngspice_available", lambda c: True)
    # 10 runs: 8 in [1.7,1.9], 2 out → 80% yield
    vals = [1.8] * 8 + [1.65, 1.95]
    monkeypatch.setattr(ARS, "_run_ngspice", _fake_ngspice(vals))
    monkeypatch.setattr(ARS, "_container_path", lambda c, r, p_: str(p_))
    rep = MC.run_block(p, "ldo", "x", "sky130", 10)
    assert rep["rc"] == 0
    assert rep["mc_yield_pct"] == 80.0
    cr = json.loads(
        (p / "phase3/analog/ldo/corner_results.json").read_text())
    assert cr["mc_yield_pct"] == 80.0
    assert cr["_mc_provenance"] == "real_ngspice_mc"
    assert cr["mc_runs"] == 10
    # the EXISTING A4-track gate now fires LOW_MC_YIELD on real data
    cr.update({"total_corners": 9, "results_found": 9,
               "corners": [{"name": f"c{i}", "simulator_run": True}
                           for i in range(9)],
               "spec_results": [{"name": "vout", "status": "PASS"}]})
    (p / "phase3/analog/ldo/corner_results.json").write_text(json.dumps(cr))
    r = ACS.run_audit(p)
    assert any(f.rule == "LOW_MC_YIELD" for f in r.findings)
    assert r.passed is False


def test_mc_full_yield_passes_gate(tmp_path, monkeypatch):
    p = _mc_project(tmp_path)
    monkeypatch.setattr(ARS, "_ngspice_available", lambda c: True)
    monkeypatch.setattr(ARS, "_run_ngspice", _fake_ngspice([1.8] * 20))
    monkeypatch.setattr(ARS, "_container_path", lambda c, r, p_: str(p_))
    rep = MC.run_block(p, "ldo", "x", "sky130", 20)
    assert rep["verdict"] == "PASS" and rep["mc_yield_pct"] == 100.0


def test_mc_skips_honestly_without_specs(tmp_path, monkeypatch):
    blk = tmp_path / "phase2" / "analog" / "ldo"
    blk.mkdir(parents=True)
    (blk / "ldo.sp").write_text("* deck\n.end\n")
    rep = MC.run_block(tmp_path, "ldo", "x", "sky130", 5)
    assert rep["rc"] == 2 and "spec" in rep["reason"]


def test_mc_seeds_are_distinct_in_decks(tmp_path, monkeypatch):
    p = _mc_project(tmp_path)
    monkeypatch.setattr(ARS, "_ngspice_available", lambda c: True)
    monkeypatch.setattr(ARS, "_run_ngspice", _fake_ngspice([1.8] * 3))
    monkeypatch.setattr(ARS, "_container_path", lambda c, r, p_: str(p_))
    MC.run_block(p, "ldo", "x", "sky130", 3)
    decks = sorted((p / "phase2/analog/ldo/mc_runs").glob("mc_*.sp"))
    seeds = [d.read_text().split(".option seed=")[1].split("\n")[0]
             for d in decks]
    assert seeds == ["1", "2", "3"]
    assert all("sky130.lib.spice mc" in d.read_text() for d in decks)


@pytest.mark.skipif(not MCP_SRC.is_file(),
                    reason="mcp-eda-server/src/index.js not present "
                           "(optional sibling; not in the plugin bundle)")
def test_mcp_monte_carlo_param_is_wired():
    src = MCP_SRC.read_text()
    assert "monte_carlo_n was declared since v0.108 but NEVER" in src
    assert 'mcSeed: i' in src
    assert "mc_yield_pct" in src
    assert ".option seed=${mcSeed}" in src.replace("`", "")


# ── mixed_signal_top_lvs_run + M1 gate ─────────────────────────────────────

def _ms_project(tmp_path):
    g = tmp_path / "phase3" / "stage4" / "gds"
    g.mkdir(parents=True)
    (g / "chip_top.gds").write_bytes(b"\x00\x06digital")
    hm = tmp_path / "phase3" / "analog" / "hardmacro" / "ldo"
    hm.mkdir(parents=True)
    (hm / "ldo.gds").write_bytes(b"\x00\x06macro")
    (hm / "ldo.v").write_text("module ldo(input en, output vout);\nendmodule\n")
    sy = tmp_path / "phase2" / "stage2" / "synth"
    sy.mkdir(parents=True)
    (sy / "chip_top_synth.v").write_text("module chip_top();\nendmodule\n")
    return tmp_path


def _fake_ms_docker(lvs_text):
    def fake(container, cmd, timeout=600):
        if cmd.startswith("command -v") or cmd.startswith("test -f"):
            return 0, "", ""
        if "klayout" in cmd:
            import re as _re
            m = _re.search(r"MERGED_OUT=(\S+)", cmd)
            Path(m.group(1)).parent.mkdir(parents=True, exist_ok=True)
            Path(m.group(1)).write_bytes(b"\x00\x06merged")
            return 0, "KLAYOUT_MERGE_DONE", ""
        if "magic" in cmd:
            import re as _re
            m = _re.search(r"SPICE_OUT=(\S+)", cmd)
            Path(m.group(1)).write_text(".subckt chip_top a b\n.ends\n")
            return 0, "MAGIC_EXT2SPICE_DONE", ""
        if "netgen" in cmd:
            import re as _re
            m = _re.search(r"(\S+/top_lvs\.rpt)", cmd)
            Path(m.group(1)).parent.mkdir(parents=True, exist_ok=True)
            Path(m.group(1)).write_text("Netgen 1.5\n" + lvs_text)
            return 0, lvs_text, ""
        return 0, "", ""
    return fake


def test_top_lvs_pass_emits_substantiated_merge(tmp_path, monkeypatch):
    p = _ms_project(tmp_path)
    monkeypatch.setattr(TL, "_docker_exec",
                        _fake_ms_docker("Final result: Circuits match uniquely.\n"))
    rep = TL.run(p, "chip_top", "x", "sky130A")
    assert rep["rc"] == 0 and rep["verdict"] == "PASS"
    merge = json.loads(
        (p / "reports/analog/mixed_signal/merge.json").read_text())
    assert merge["verdict"] == "PASS" and merge["top_lvs"] == "PASS"
    assert (p / "phase3/mixed_signal/top_merged.gds").is_file()
    # M1 gate now PASSes on substantiation
    import mixed_signal_merge_check as M1
    assert M1.main([str(p)]) == 0


def test_top_lvs_mismatch_fails(tmp_path, monkeypatch):
    p = _ms_project(tmp_path)
    monkeypatch.setattr(TL, "_docker_exec",
                        _fake_ms_docker("Netlists do not match.\n"))
    rep = TL.run(p, "chip_top", "x", "sky130A")
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL"
    import mixed_signal_merge_check as M1
    assert M1.main([str(p)]) == 1


def test_m1_presence_without_lvs_now_fails(tmp_path):
    # the audited stub shape: merged GDS exists, nothing else
    ms = tmp_path / "phase3" / "mixed_signal"
    ms.mkdir(parents=True)
    (ms / "top_merged.gds").write_bytes(b"\x00\x06merged")
    import mixed_signal_merge_check as M1
    out_json = tmp_path / "m1.json"
    rc = M1.main([str(tmp_path), "--json", str(out_json)])
    assert rc == 1
    rep = json.loads(out_json.read_text())
    assert any(f["rule"] == "MERGE_NOT_LVS_SUBSTANTIATED"
               for f in rep["findings"])


def test_top_lvs_skips_honestly_without_inputs(tmp_path):
    rep = TL.run(tmp_path, "chip_top", "x", "sky130A")
    assert rep["rc"] == 2 and "inputs missing" in rep["reason"]
