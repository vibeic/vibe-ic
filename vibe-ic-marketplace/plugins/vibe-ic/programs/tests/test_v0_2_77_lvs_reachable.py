"""v0.2.77 — #443: open-source LVS is structurally REACHABLE.

The audited rot: step_lvs auto-WAIVED in every configuration — even
with netgen on PATH — because no layout-extraction step existed
anywhere in phase3; LVS was permanently unreachable and the waiver
rationale ("deferred to dedicated extraction flow") shipped on every
project forever.

Pins (monkeypatched docker — no container needed):
  * with magic+netgen+PDK tech present and GDS+netlist inputs, step_lvs
    RUNS Magic ext2spice + netgen and the verdict comes from the real
    compare output ("Circuits match uniquely" → PASS, mismatch → FAIL);
  * the unconditional-WAIVE shape is GONE from the source;
  * missing tool / missing PDK tech → ENV_UNAVAILABLE naming the gap;
  * missing GDS/netlist inputs → WAIVED naming the missing input.

chip-AGNOSTIC: synthetic project + fake docker transcripts.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as runner  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()


def _pdk():
    return runner.PdkConfig(
        name="sky130A", liberty="/foss/pdks/x.lib", tech_lef="/t.tlef",
        cell_lef="/c.lef", cell_gds=None, site="s", drc_deck=None)


def _proj(tmp_path):
    # v0.3.13 #508/#509: LVS layout source is the routed DEF (Magic reads
    # it directly via def read + port makeall), not the GDS.
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "chip_top.def").write_bytes(
        b"VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n")
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text("module chip_top();\nendmodule\n")
    return tmp_path


def _fake_docker(transcripts, spice_body=".subckt chip_top a b\n.ends\n"):
    """Return a docker stub: tool checks OK, magic writes the extracted
    netlist, netgen prints the given transcript + writes lvs.rpt."""
    def fake(container, cmd, timeout=0, **_):
        if cmd.startswith("command -v") or cmd.startswith("test -f"):
            return (0, "", "")
        if "magic" in cmd and "SPICE_OUT=" in cmd:
            import re as _re
            m = _re.search(r"SPICE_OUT=(\S+)", cmd)
            Path(m.group(1)).write_text(spice_body)
            return (0, "MAGIC_EXT2SPICE_DONE", "")
        if "netgen" in cmd:
            import re as _re
            m = _re.search(r"(\S+/lvs\.rpt)", cmd)
            if m:
                Path(m.group(1)).parent.mkdir(parents=True, exist_ok=True)
                Path(m.group(1)).write_text(
                    "Netgen 1.5\n" + transcripts)
            return (0, transcripts, "")
        return (0, "", "")
    return fake


def test_lvs_runs_and_passes_on_match(tmp_path, monkeypatch):
    p = _proj(tmp_path)
    monkeypatch.setattr(runner, "_docker_exec",
                        _fake_docker("Final result: Circuits match uniquely.\n"))
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status == "PASS", (r.status, r.detail)
    assert (p / "reports" / "phase3" / "lvs.rpt").is_file()
    assert (p / "phase3/stage3/extracted/chip_top_extracted.sp").is_file()


def test_lvs_fails_on_real_mismatch(tmp_path, monkeypatch):
    p = _proj(tmp_path)
    monkeypatch.setattr(runner, "_docker_exec",
                        _fake_docker("Netlists do not match.\n"))
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status == "FAIL"
    assert "real compare ran" in r.detail


def test_missing_tools_env_unavailable(tmp_path, monkeypatch):
    p = _proj(tmp_path)
    monkeypatch.setattr(
        runner, "_docker_exec",
        lambda c, cmd, timeout=0, **_: (1, "", "") if cmd.startswith("command -v")
        else (0, "", ""))
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status == "ENV_UNAVAILABLE"
    assert "magic" in r.extras.get("missing_tool", "")


def test_missing_inputs_waived_with_name(tmp_path, monkeypatch):
    # tools present but no GDS / netlist
    monkeypatch.setattr(runner, "_docker_exec",
                        lambda c, cmd, timeout=0, **_: (0, "", ""))
    r = runner.step_lvs(tmp_path, "chip_top", _pdk(), "x")
    assert r.status == "WAIVED"
    assert "LVS inputs missing" in r.detail


def test_unconditional_waive_shape_is_gone():
    assert "deferred to dedicated extraction flow" not in _SRC
    assert "ext2spice" in _SRC and "_run_extraction_lvs" in _SRC
