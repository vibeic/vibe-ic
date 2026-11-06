"""M1 current-input contract. Tool fakes exercise orchestration, not native signoff."""
import hashlib
import json
import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mixed_signal_top_lvs_run as M1
import mixed_signal_power_domain_run as M2

TOP = "integration_top"


def project(root):
    files = {
        f"phase3/stage3/pnr/{TOP}.gds": b"current digital",
        "phase3/stage3/pnr/routed.def": (
            f"DESIGN {TOP} ;\nUNITS DISTANCE MICRONS 1000 ;\n"
            "COMPONENTS 1 ;\n- u_analog analog_unit + FIXED ( 2000 3000 ) N ;\n"
            "END COMPONENTS\nEND DESIGN\n").encode(),
        f"phase3/stage3/pnr/{TOP}_pnr.v": (
            f"module {TOP}(input en, output sense);\n"
            "analog_unit u_analog (.en(en), .sense(sense));\nendmodule\n").encode(),
        "phase3/analog/hardmacro/analog_unit/analog_unit.gds": b"current macro",
        "phase3/analog/hardmacro/analog_unit/analog_unit.v":
            b"module analog_unit(input en, output sense); endmodule\n",
        f"phase2/stage2/synth/{TOP}_synth.v": (
            f"module {TOP}(input en, output sense);\n"
            "analog_unit u_analog (.en(en), .sense(sense));\nendmodule\n").encode(),
        f"phase2/stage2/constraints/{TOP}.upf": b"# M2 input binding fixture\n",
        "input/pdk/liberty/neutral.lib": b"library(neutral) {}\n",
    }
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    import os
    os.utime(root / f"phase3/stage3/pnr/{TOP}.gds", None)
    return root


def fake_tools(root, monkeypatch):
    calls = []
    ms = root / "phase3/mixed_signal"
    rp = root / "reports/analog/mixed_signal"

    def fake(container, cmd, timeout=600, **kwargs):
        calls.append(cmd)
        if cmd.startswith(("command -v", "test -f", "test -d")):
            return 0, "", ""
        if "M1_TOOL_IDENTITY" in cmd:
            return 0, json.dumps({"executable": "/tools/klayout",
                                  "sha256": "a" * 64, "version": "KLayout test-double"}), ""
        if "klayout -b" in cmd:
            tokens = shlex.split(cmd)
            env = dict(t.split("=", 1) for t in tokens if "=" in t)
            out = Path(env["MERGED_OUT"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"fresh merge " + hashlib.sha256(
                (root / f"phase3/stage3/pnr/{TOP}.gds").read_bytes()).digest())
            (ms / "merge.log").write_text("KLAYOUT_MERGE_DONE\n")
            placement = json.loads(Path(env["PLACEMENTS_JSON"]).read_text())["placements"]
            placed = [{"macro": cell, **p} for cell, items in placement.items() for p in items]
            Path(env["MERGE_JSON"]).write_text(json.dumps({
                "design_top": TOP, "single_top": True, "top_cells_after": [TOP],
                "placed": placed, "macros": [{"macro": "analog_unit", "action": "added"}]}))
            return 0, "KLAYOUT_MERGE_DONE", ""
        if "magic -dnull" in cmd:
            (ms / f"{TOP}_merged_extracted.sp").write_text(f".subckt {TOP} en sense\n.ends\n")
            (ms / "ext2spice_merged.log").write_text("MAGIC_EXT2SPICE_DONE\n")
            return 0, "MAGIC_EXT2SPICE_DONE", ""
        if "netgen -batch" in cmd:
            rp.mkdir(parents=True, exist_ok=True)
            (rp / "top_lvs.rpt").write_text("Final result: Circuits match uniquely.\n")
            return 0, "Final result: Circuits match uniquely.", ""
        return 0, "", ""

    monkeypatch.setattr(M1, "_docker_exec", fake)
    return calls


def test_unbound_carried_merge_must_execute_klayout(tmp_path, monkeypatch):
    p = project(tmp_path)
    out = p / "phase3/mixed_signal/top_merged.gds"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"carried from another run")
    calls = fake_tools(p, monkeypatch)
    result = M1.run(p, TOP, "host", "declared_pdk")
    assert out.read_bytes() != b"carried from another run", result
    assert any("klayout -b" in call for call in calls), result
    assert result["verdict"] == "PASS", result






def test_new_invocation_rebuilds_even_a_previously_bound_merge(tmp_path, monkeypatch):
    p = project(tmp_path)
    calls = fake_tools(p, monkeypatch)
    assert M1.run(p, TOP, "host", "declared_pdk")["verdict"] == "PASS"
    calls.clear()
    (p / f"phase3/stage3/pnr/{TOP}.gds").write_bytes(b"revised digital")
    result = M1.run(p, TOP, "host", "declared_pdk")
    assert result["verdict"] == "PASS", result
    assert any("klayout -b" in call for call in calls), result


def test_unchanged_m2_reads_exact_current_m1_digest(tmp_path, monkeypatch):
    p = project(tmp_path)
    fake_tools(p, monkeypatch)
    assert M1.run(p, TOP, "host", "declared_pdk")["verdict"] == "PASS"
    paths, libs = M2.inputs(p, TOP)
    merged = p / "phase3/mixed_signal/top_merged.gds"
    assert paths["gds"] == merged


@pytest.mark.parametrize("bad", ["unrelated_gds", "ambiguous_gds", "wrong_def_top", "missing_def",
                                    "unplaced", "duplicate_instance", "wrong_view", "missing_view", "wrong_instance"])
def test_invalid_digital_or_macro_evidence_refuses(tmp_path, monkeypatch, bad):
    p = project(tmp_path)
    dg = p / f"phase3/stage3/pnr/{TOP}.gds"
    de = p / "phase3/stage3/pnr/routed.def"
    view = p / "phase3/analog/hardmacro/analog_unit/analog_unit.v"
    if bad == "unrelated_gds":
        dg.rename(dg.with_name("unrelated.gds"))
    elif bad == "ambiguous_gds":
        other = p / f"phase3/stage4/gds/{TOP}.gds"
        other.parent.mkdir(parents=True)
        other.write_bytes(b"another generation")
    elif bad == "missing_def":
        de.rename(de.with_suffix(".absent"))
    elif bad == "wrong_def_top":
        de.write_text(de.read_text().replace(TOP, "other_top"))
    elif bad == "unplaced":
        de.write_text(de.read_text().replace("FIXED ( 2000 3000 ) N", "UNPLACED"))
    elif bad == "duplicate_instance":
        de.write_text(de.read_text().replace("END COMPONENTS", "- u_analog analog_unit + FIXED ( 1 1 ) N ;\nEND COMPONENTS"))
    elif bad == "wrong_view":
        view.write_text(view.read_text().replace("module analog_unit", "module other_cell"))
    elif bad == "missing_view":
        view.rename(view.with_suffix(".absent"))
    elif bad == "wrong_instance":
        de.write_text(de.read_text().replace("u_analog", "u_other"))
    calls = fake_tools(p, monkeypatch)
    result = M1.run(p, TOP, "host", "declared_pdk")
    assert result["verdict"] != "PASS", result
    assert not any("magic -dnull" in call for call in calls), result


def test_ambiguous_def_tops_do_not_resolve_alphabetically(tmp_path):
    p = project(tmp_path)
    other = p / "phase3/stage3/pnr/aaa.def"
    other.write_text("DESIGN other_top ;\n")
    resolved, reason = M1.resolve_top(p)
    assert resolved is None, (resolved, reason)


def test_physical_top_alias_is_bound_by_same_stem_def(tmp_path, monkeypatch):
    import os
    p = project(tmp_path)
    pnr = p / "phase3/stage3/pnr"
    (pnr / f"{TOP}.gds").rename(pnr / "delivery_name.gds")
    (pnr / "routed.def").rename(pnr / "delivery_name.def")
    os.utime(pnr / "delivery_name.gds", None)
    digital, _, _, netlist, detail = M1.current_merge_inputs(p, TOP)
    assert digital.name == "delivery_name.gds"
    assert detail["def_source"] == "delivery_name.def"
    assert netlist.name == f"{TOP}_pnr.v"


def test_duplicate_unplaced_record_cannot_hide_behind_placed_macro(tmp_path, monkeypatch):
    import os
    p = project(tmp_path)
    path = p / "phase3/stage3/pnr/routed.def"
    path.write_text(path.read_text().replace("COMPONENTS 1", "COMPONENTS 2")
                    .replace("END COMPONENTS", "- u_analog analog_unit + UNPLACED ;\nEND COMPONENTS"))
    os.utime(p / f"phase3/stage3/pnr/{TOP}.gds", None)
    fake_tools(p, monkeypatch)
    result = M1.run(p, TOP, "host", "declared_pdk")
    assert result["verdict"] == "FAIL", result
    assert "duplicate" in result["reason"], result






def test_nonzero_klayout_cannot_publish_even_with_fresh_done_marker(tmp_path, monkeypatch):
    p = project(tmp_path)
    fake_tools(p, monkeypatch)
    original = M1._docker_exec
    def fail(container, cmd, **kwargs):
        rc, out, err = original(container, cmd, **kwargs)
        return (3, out, err) if "klayout -b" in cmd else (rc, out, err)
    monkeypatch.setattr(M1, "_docker_exec", fail)
    result = M1.run(p, TOP, "host", "declared_pdk")
    assert result["verdict"] == "FAIL", result






def test_failed_current_invocation_cannot_leave_previous_gate_admission(tmp_path, monkeypatch):
    p = project(tmp_path)
    fake_tools(p, monkeypatch)
    assert M1.run(p, TOP, "host", "declared_pdk")["verdict"] == "PASS"
    path = p / "phase3/stage3/pnr/routed.def"
    path.write_text(path.read_text().replace("u_analog", "u_other"))
    assert M1.main([str(p), "--top", TOP, "--pdk", "declared_pdk", "--container", "host"]) == 1


def test_checked_in_def_identity_is_read_without_first_file_fallback(tmp_path):
    from _hostpaths import require_repo
    source = require_repo("vibe-ic-marketplace/plugins/vibe-ic/programs/calibration/cal_views.def")
    pnr = tmp_path / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_bytes(source.read_bytes())
    expected = M1.def_design_name(source.read_text())
    assert expected
    assert M1.resolve_top(tmp_path)[0] == expected
