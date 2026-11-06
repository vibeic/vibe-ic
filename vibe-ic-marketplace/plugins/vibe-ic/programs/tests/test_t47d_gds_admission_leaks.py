"""The live SDR and handoff paths may write masks only after admission."""
import json

import foundry_handoff_pack_gen as H
import phase3_one_shot_runner as R
from _hostpaths import require_repo




def test_failed_gate_refuses_handoff_even_with_old_sources(tmp_path):
    project = tmp_path / "run"
    source = project / "phase3/stage3/pnr/unit.filled.gds"
    source.parent.mkdir(parents=True)
    source.write_bytes(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "tests", "fixtures", "density_fill", "filled.gds").read_bytes())
    gate = project / "reports/phase3/prestream_gate.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(json.dumps({"verdict": "FAIL", "layout_digest": "b" * 64,
                                "failed_gates": ["antenna"]}))
    old_kit = project / "phase3/stage4/foundry_handoff/mask_spec.json"
    old_kit.parent.mkdir(parents=True, exist_ok=True)
    old_kit.write_text('{"previous_run": true}\n')
    assert H.main([str(project)]) == 2
    assert not source.exists()
    assert not list((project / "phase3/stage4/foundry_handoff").glob("*.gds"))
    assert list(old_kit.parent.iterdir()) == []












def test_handoff_refuses_stale_stage4_copy_with_pass_gate(tmp_path):
    project = tmp_path / "run"
    pnr = R._pl.pnr_dir(project)
    pnr.mkdir(parents=True)
    source = pnr / "unit.gds"
    source.write_bytes(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "tests", "fixtures", "density_fill", "filled.gds").read_bytes())
    alias = R._pl.gds_dir(project) / "unit.gds"
    alias.parent.mkdir(parents=True)
    alias.write_bytes(source.read_bytes() + b"stale copy")
    gate = project / "reports/phase3/prestream_gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps({"verdict": "PASS", "layout_digest": "a" * 64}))
    basis = []
    for name in ("routed.def", "constraint.sdc", "netlist.v"):
        path = pnr / name
        path.write_text("fixture input\n")
        basis.append(path)
    R._ga.admit_gds(project, source, "a" * 64, basis)
    assert H.main([str(project)]) == 2
    assert not alias.exists()
    assert not list(R._pl.foundry_handoff_dir(project).glob("*.gds"))


def test_handoff_refuses_an_unrecorded_extra_mask(tmp_path):
    project = tmp_path / "run"
    pnr = R._pl.pnr_dir(project)
    pnr.mkdir(parents=True)
    source = pnr / "unit.gds"
    source.write_bytes(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "tests", "fixtures", "density_fill", "filled.gds").read_bytes())
    alias = R._pl.gds_dir(project) / "unit.gds"
    alias.parent.mkdir(parents=True)
    alias.write_bytes(source.read_bytes())
    gate = project / "reports/phase3/prestream_gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps({"verdict": "PASS", "layout_digest": "a" * 64}))
    basis = []
    for name in ("routed.def", "constraint.sdc", "netlist.v"):
        path = pnr / name
        path.write_text("fixture input\n")
        basis.append(path)
    R._ga.admit_gds(project, source, "a" * 64, basis)
    extra = alias.parent / "unit_extra.gds"
    extra.write_bytes(source.read_bytes())
    assert H.main([str(project)]) == 2
    assert not extra.exists()
    assert not list(R._pl.foundry_handoff_dir(project).glob("*.gds"))
