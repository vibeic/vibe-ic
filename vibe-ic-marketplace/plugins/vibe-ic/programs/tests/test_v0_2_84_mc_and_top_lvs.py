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
    """Resolve mcp-eda/src/index.js relative to the repo root by
    walking up from this test file — NEVER a hardcoded absolute home path
    (the old `/home/<dev>/...` literal passed locally but does not
    exist on the CI runner at `/home/runner/work/...`, so the test failed
    the moment the suite ran to completion). The mcp is an
    OPTIONAL sibling of the plugin marketplace, so the test skips when it
    is absent rather than erroring."""
    for anc in Path(__file__).resolve().parents:
        cand = anc / "mcp-eda" / "src" / "index.js"
        if cand.is_file():
            return cand
    return Path("mcp-eda/src/index.js")  # sentinel; skip below


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
    def fake(container, sp, cwd=None):
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
    # 20 DISTINCT in-range values (real mismatch spread, all within [1.7,1.9])
    # → real 100% yield. ORGANIC #142: identical samples would now be flagged
    # degenerate, so a real full-yield run must show spread.
    vals = [round(1.75 + i * 0.005, 3) for i in range(20)]  # 1.75..1.845
    monkeypatch.setattr(ARS, "_run_ngspice", _fake_ngspice(vals))
    monkeypatch.setattr(ARS, "_container_path", lambda c, r, p_: str(p_))
    rep = MC.run_block(p, "ldo", "x", "sky130", 20)
    assert rep["verdict"] == "PASS" and rep["mc_yield_pct"] == 100.0


def test_mc_degenerate_all_identical_is_unscoreable(tmp_path, monkeypatch):
    """ORGANIC #142 no-leak — N IDENTICAL samples (sigma≈0, the typical-corner
    mc_mm_switch=0 degenerate case) must be flagged UNSCOREABLE, NEVER reported
    as a real 100%/0% yield."""
    p = _mc_project(tmp_path)
    monkeypatch.setattr(ARS, "_ngspice_available", lambda c: True)
    monkeypatch.setattr(ARS, "_run_ngspice", _fake_ngspice([1.8] * 30))
    monkeypatch.setattr(ARS, "_container_path", lambda c, r, p_: str(p_))
    rep = MC.run_block(p, "ldo", "x", "sky130", 30)
    assert rep["verdict"] == "UNSCOREABLE"
    assert "mc_yield_pct" not in rep or rep.get("mc_yield_pct") is None
    assert "spread" in rep["reason"] or "distinct" in rep["reason"]
    # the honest per-spec record marks the degeneracy
    assert rep["spec_yield"]["vout"]["degenerate"] is True


def test_mc_real_spread_accepted(tmp_path, monkeypatch):
    """A real mismatch spread (≥2 distinct values) is scored normally — the
    mismatch-section idiom (tt_mm) produces this."""
    p = _mc_project(tmp_path)
    monkeypatch.setattr(ARS, "_ngspice_available", lambda c: True)
    # 7 in-range + 3 out-of-range, all distinct → 70% yield
    vals = [1.78, 1.80, 1.82, 1.84, 1.86, 1.88, 1.72, 1.60, 1.95, 1.98]
    monkeypatch.setattr(ARS, "_run_ngspice", _fake_ngspice(vals))
    monkeypatch.setattr(ARS, "_container_path", lambda c, r, p_: str(p_))
    rep = MC.run_block(p, "ldo", "x", "sky130", 10)
    assert rep["rc"] == 0
    assert rep["mc_yield_pct"] == 70.0
    assert rep["spec_yield"]["vout"]["distinct_values"] >= 2


def test_mc_skips_honestly_without_specs(tmp_path, monkeypatch):
    blk = tmp_path / "phase2" / "analog" / "ldo"
    blk.mkdir(parents=True)
    # A RUNNABLE deck (has a .meas analysis card) but no spec.json → the
    # specs-absent SKIP path, not the UNSCOREABLE (no-runnable-deck) path.
    (blk / "ldo.sp").write_text(
        "* deck\n.meas dc vout FIND v(out) AT=1u\n.end\n")
    rep = MC.run_block(tmp_path, "ldo", "x", "sky130", 5)
    assert rep["rc"] == 2 and "spec" in rep["reason"]


# ── ORGANIC #142 — runnable-deck preference + UNSCOREABLE honesty ───────────

def test_find_deck_prefers_runnable_over_bare_subckt(tmp_path):
    """A bare A3 `.subckt` library sorts first alphabetically but is NOT
    runnable; the runnable sizing_loop deck (with a .control/.meas analysis)
    must be selected instead."""
    blk = tmp_path / "phase3" / "analog" / "ldo"
    (blk).mkdir(parents=True)
    # bare A3 subckt library (no analysis card) — sorts first as `ldo.sp`
    (blk / "ldo.sp").write_text(
        ".subckt ldo vdd vss vin vout\nr1 vin vout 1k\n.ends ldo\n")
    # runnable deck in a subdir _find_deck never used to search
    sl = blk / "sizing_loop"
    sl.mkdir()
    (sl / "run_tt.sp").write_text(
        "* ldo tb\n.control\nop\necho \"MEAS vout=\" $&v(out)\n.endc\n.end\n")
    deck, rank = MC._find_deck(tmp_path, "ldo")
    assert deck is not None
    assert deck.name == "run_tt.sp"
    assert rank == 3  # runnable AND scoreable (echo MEAS)


def test_bare_subckt_only_is_unscoreable_not_zero_scored(tmp_path, monkeypatch):
    """A block dir with ONLY a bare `.subckt` library → honest UNSCOREABLE
    verdict; MC must NOT run N empty iterations that each score 0."""
    blk = tmp_path / "phase3" / "analog" / "delta_sigma"
    blk.mkdir(parents=True)
    (blk / "delta_sigma.sp").write_text(
        ".subckt delta_sigma vdd vss vin dout\n"
        "* no analysis card — a reusable library only\n"
        "r1 vin dout 1k\n.ends delta_sigma\n")
    spec = tmp_path / "phase1" / "analog" / "delta_sigma"
    spec.mkdir(parents=True)
    (spec / "spec.json").write_text(json.dumps(
        {"specs": [{"name": "vout", "min": 0.0, "max": 1.0}]}))
    # Guard: ngspice must NEVER be invoked on a bare-subckt-only block.
    called = {"n": 0}
    monkeypatch.setattr(ARS, "_ngspice_available",
                        lambda c: (called.__setitem__("n", called["n"] + 1)
                                   or True))
    rep = MC.run_block(tmp_path, "delta_sigma", "x", "sky130", 30)
    assert rep["verdict"] == "UNSCOREABLE"
    assert rep["rc"] == 2
    assert "bare .subckt" in rep["reason"]
    assert called["n"] == 0  # never even probed ngspice → no empty runs
    # and no mc_runs dir of empty decks was created
    assert not (blk / "mc_runs").exists()


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
    # ORGANIC #142 — the MISMATCH corner section (tt_mm) is loaded, not `mc`.
    assert all("sky130.lib.spice tt_mm" in d.read_text() for d in decks)


@pytest.mark.skipif(not MCP_SRC.is_file(),
                    reason="mcp-eda/src/index.js not present "
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
    """The real commands end in `... 2>&1 | tee <log>`, so the tool's own log
    IS written on every real run. The fake must write it too: the program now
    requires each tool's log to have been (re)written by THIS invocation and
    to carry the tool's completion marker, because file PRESENCE alone was
    satisfied by outputs carried forward from another run entirely."""
    def fake(container, cmd, timeout=600, **_):
        if cmd.startswith("command -v") or cmd.startswith("test -f") \
                or cmd.startswith("test -d"):
            return 0, "", ""
        if "klayout" in cmd:
            import re as _re
            m = _re.search(r"MERGED_OUT=(\S+)", cmd)
            Path(m.group(1)).parent.mkdir(parents=True, exist_ok=True)
            Path(m.group(1)).write_bytes(b"\x00\x06merged")
            t = _re.search(r"tee (\S+/merge\.log)", cmd)
            if t:
                Path(t.group(1)).write_text("KLAYOUT_MERGE_DONE\n")
            return 0, "KLAYOUT_MERGE_DONE", ""
        if "magic" in cmd:
            import re as _re
            m = _re.search(r"SPICE_OUT=(\S+)", cmd)
            Path(m.group(1)).write_text(".subckt chip_top a b\n.ends\n")
            t = _re.search(r"tee (\S+/ext2spice_merged\.log)", cmd)
            if t:
                Path(t.group(1)).write_text("MAGIC_EXT2SPICE_DONE\n")
            return 0, "MAGIC_EXT2SPICE_DONE", ""
        if "netgen" in cmd:
            import re as _re
            # The report path moved off the command line and into the Tcl the
            # program tells netgen to `source`: netgen's `lvs` takes a two-
            # element {file cell} list per side, and the schematic side is
            # always several files, so they must be read into one netlist first
            # -- which needs a script. Read what the program actually wrote,
            # exactly as netgen would.
            m = _re.search(r"source\s+(\S+\.tcl)", cmd)
            assert m, f"netgen invoked without a script to source: {cmd}"
            tcl = Path(m.group(1)).read_text()
            rpt = _re.search(r"(\S+/top_lvs\.rpt)",
                             tcl.replace("{", " ").replace("}", " "))
            assert rpt, f"the netgen script names no report file:\n{tcl}"
            Path(rpt.group(1)).parent.mkdir(parents=True, exist_ok=True)
            Path(rpt.group(1)).write_text("Netgen 1.5\n" + lvs_text)
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
