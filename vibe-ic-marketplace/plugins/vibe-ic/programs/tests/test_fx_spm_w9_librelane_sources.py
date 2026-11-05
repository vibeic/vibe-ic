"""LibreLane step 24 must refuse a bridged core whose pins are PSM sources."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS / "tests"))

import librelane_ir_antenna as IR  # noqa: E402
from _tcl_walk import walk as _walk  # noqa: E402
from test_fx_spm_psm_source_model import _DB  # noqa: E402


def test_padless_promoted_pins_refuse_before_any_librelane_psm_solve(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    sources = [project / name for name in ("route.def", "net.v", "clock.sdc", "route.spef")]
    for source in sources:
        source.write_text("fixture\n")
    pdk_root = tmp_path / "pdk"
    (pdk_root / "gf180mcuD").mkdir(parents=True)

    def configs(_project, _image, _pdk, steps, **_kwargs):
        out = {}
        for step in steps:
            path = project / f"{step}.json"
            path.write_text(json.dumps({"DEFAULT_CORNER": "nom", "TECH_LEFS": {"*": "tech.lef"},
                                        "VDD_NETS": ["VDD"], "GND_NETS": ["VSS"]}))
            out[step] = path
        return out

    def bridge(*_args, **kwargs):
        dest = kwargs.get("output_dir")
        if dest is None:
            dest = _args[4]
        dest.mkdir(parents=True)
        odb = dest / "bridge.odb"
        odb.write_text("fixture\n")
        state = dest / "state_in.json"
        state.write_text(json.dumps({"odb": str(odb)}))
        return state

    def openroad(_project, _image, tcl, log, _mounts, _metrics=None):
        script = _DB + "set ::insts {inst_core}\n" + tcl.read_text()
        out, err, route = _walk(script, "", tmp_path)
        assert not err, f"{route}: {err}"
        log.write_text(out)
        return 0

    monkeypatch.setattr(IR, "resolve_step_configs", configs)
    monkeypatch.setattr(IR, "state_from_direct", bridge)
    monkeypatch.setattr(IR, "declared_supply_pads", lambda _project: {"declared": False})
    monkeypatch.setattr(IR, "_run_openroad", openroad)
    monkeypatch.setattr(IR, "run_chain", lambda *_args, **_kwargs:
                        pytest.fail("LibreLane PSM solved using the promoted supply BPins"))
    with pytest.raises(IR.Refusal, match="LL_IR_PROMOTED_PIN_SOURCES_UNSAFE"):
        IR.run_ir(project, "image", pdk_root, "gf180mcuD", routed_def=sources[0],
                  netlist=sources[1], sdc=sources[2], spef=sources[3],
                  budget_pct=10.0, budget_source="test")


def test_source_probe_preserves_a_dies_pad_bterms(tmp_path, monkeypatch):
    odb = tmp_path / "bridge.odb"
    odb.write_text("fixture\n")
    state = tmp_path / "state_in.json"
    state.write_text(json.dumps({"odb": str(odb)}))

    def openroad(_project, _image, tcl, log, _mounts, _metrics=None):
        script = _DB + "set ::insts {inst_pad}\n" + tcl.read_text()
        out, err, route = _walk(script, "", tmp_path)
        assert not err, f"{route}: {err}"
        log.write_text(out)
        return 0

    monkeypatch.setattr(IR, "_run_openroad", openroad)
    marker = IR.require_safe_default_sources(tmp_path, "image", state, [])
    assert marker["placed_pads"] == 1
    assert marker["supply_bpins"] == 3
