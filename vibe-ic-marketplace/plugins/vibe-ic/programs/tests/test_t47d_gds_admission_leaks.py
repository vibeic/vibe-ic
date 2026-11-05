"""The live SDR and handoff paths may write masks only after admission."""
import json

import foundry_handoff_pack_gen as H
import phase3_one_shot_runner as R
from _hostpaths import require_repo
from test_phase3_postpnr_disclosure_and_gds_guard import _project, _drive, _plan, NEW_DIE, NEW_UTIL, TOP




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






def test_stale_digest_quarantines_gds_without_rerunning_pnr(tmp_path, monkeypatch):
    # Legacy geometry/cache/admission unit; no completed Default finishing receipt.
    project = _project(tmp_path / "run", cached_die=NEW_DIE, cached_util=NEW_UTIL)
    admission = R._ga.admission_path(project)
    record = json.loads(admission.read_text())
    record["layout_digest"] = "0" * 64
    admission.write_text(json.dumps(record) + "\n")
    drive = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL, execution_mode="ultra")
    R.main()
    assert "pnr" not in drive.called
    assert "gds" in drive.called
    assert "skipped re-run" not in _plan(project)["gds"]["detail"]
    assert list((project / "phase3/scratch/gds_quarantine").glob("*/record.json"))


def test_matching_digest_and_pass_gate_reuses_both_caches(tmp_path, monkeypatch):
    # Legacy geometry/cache/admission unit; no completed Default finishing receipt.
    project = _project(tmp_path / "run", cached_die=NEW_DIE, cached_util=NEW_UTIL)
    gds = R._pl.pnr_dir(project) / f"{TOP}.gds"
    gate = json.loads((project / "reports/phase3/prestream_gate.json").read_text())
    assert R._ga.admitted_gds(project, gds, gate["layout_digest"])
    drive = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL, execution_mode="ultra")
    R.main()
    assert "pnr" not in drive.called
    assert "gds" not in drive.called
    assert "skipped re-run" in _plan(project)["gds"]["detail"]




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
