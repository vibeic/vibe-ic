"""Bounded native M1 input/merge exercise; not whole-design physical signoff.

OpenROAD reads and serializes the neutral placed DEF, then actual KLayout
merges the current A8-like views. No complete digital routing is claimed.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mixed_signal_top_lvs_run as M1
import mixed_signal_power_domain_run as M2


def exercise(root):
    import pya
    from _hostpaths import require_repo
    source = require_repo("vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/m2_placed")
    project = root / "project"
    shutil.copytree(source, project)
    pnr = project / "phase3/stage3/pnr"
    ms = project / "phase3/mixed_signal"
    ms.mkdir(parents=True, exist_ok=True)
    tech = root / "neutral.lef"
    tech.write_text('''VERSION 5.8 ;
BUSBITCHARS "[]" ;
DIVIDERCHAR "/" ;
UNITS DATABASE MICRONS 1000 ; END UNITS
LAYER metal1
 TYPE ROUTING ; DIRECTION HORIZONTAL ; PITCH 0.2 ; WIDTH 0.1 ; SPACING 0.1 ;
END metal1
'''+"\n".join(f'''MACRO {cell}
 CLASS BLOCK ; ORIGIN 0 0 ; SIZE 0.5 BY 0.5 ; SYMMETRY X Y R90 ;
END {cell}
''' for cell in ("plain", "shift_cell", "clamp_cell"))+"END LIBRARY\n")
    script = root / "serialize.tcl"
    script.write_text(f'read_lef {{{tech}}}\nread_def {{{pnr / "routed.def"}}}\nwrite_def {{{pnr / "boundary.def"}}}\nexit\n')
    with (root / "openroad.log").open("w") as log:
        subprocess.run(["openroad", "-exit", str(script)], stdout=log, stderr=subprocess.STDOUT, check=True)
    # The direct stream-out convention delivers <top>.def; keep the alias
    # identical so M2 consumes the same actual OpenROAD output.
    shutil.copyfile(pnr / "boundary.def", pnr / "routed.def")
    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("boundary")
    layer = ly.layer(1, 0)
    for i, name in enumerate(("plain", "shift_cell", "clamp_cell", "plain")):
        cell = ly.cell(name) or ly.create_cell(name)
        if cell.is_empty():
            cell.shapes(layer).insert(pya.Box(0, 0, 500, 500))
        top.insert(pya.CellInstArray(cell.cell_index(), pya.Trans((i + 1) * 1000, 1000)))
    ly.write(str(pnr / "boundary.gds"))
    macro = project / "phase3/analog/hardmacro/plain"
    macro.mkdir(parents=True)
    ml = pya.Layout()
    ml.dbu = 0.001
    mc = ml.create_cell("plain")
    leaf = ml.create_cell("current_leaf")
    leaf.shapes(ml.layer(1, 0)).insert(pya.Box(0, 0, 400, 400))
    mc.insert(pya.CellInstArray(leaf.cell_index(), pya.Trans()))
    ml.write(str(macro / "plain.gds"))
    (macro / "plain.v").write_text("module plain(input A, output Y); endmodule\n")
    # A carried-forward file is deliberately present on the normal output path.
    carried = (ms / "top_merged.gds").read_bytes()
    result = M1.run(project, "boundary", "host", None, pdk_source="no physical PDK declared for neutral structural fixture")
    merged = ms / "top_merged.gds"
    assert merged.read_bytes() != carried, result
    output = pya.Layout()
    output.read(str(merged))
    assert [output.cell(i).name for i in output.each_top_cell()] == ["boundary"]
    assert len(list(output.cell("boundary").each_inst())) == 4
    assert output.cell("plain").bbox().width() == 400
    assert len([i for i in output.cell("boundary").each_inst() if output.cell(i.cell_index).name == "plain"]) == 2
    assert result["verdict"] == "SKIP" and "PDK" in result["reason"], result
    paths, libs = M2.inputs(project, "boundary")
    assert paths["gds"] == merged
    assert M2.main([str(project), "--container", "host"]) == 0
    assert M2.main([str(project), "--check-only"]) == 0
    m2 = json.loads((project / "reports/analog/mixed_signal/power_domain_run.json").read_text())
    result["scope"] = "actual OpenROAD DEF serialization + KLayout merge + unchanged native M2; no full route or physical LVS signoff"
    native_cases = {}
    for orient, (rot, mirror) in M1._DEF_ORIENT_TO_KLAYOUT.items():
        arm = root / ("orientation_" + orient)
        shutil.copytree(project, arm)
        apnr = arm / "phase3/stage3/pnr"
        for name in ("routed.def", "boundary.def"):
            path = apnr / name
            path.write_text(path.read_text().replace("( 1000 1000 ) N", "( 1000 1000 ) " + orient))
        digital = pya.Layout()
        digital.read(str(pnr / "boundary.gds"))
        digital_top = digital.cell("boundary")
        for inst in digital_top.each_inst():
            if digital.cell(inst.cell_index).name == "plain" and inst.trans.disp.x == 1000:
                inst.trans = pya.Trans(rot, mirror, 1000, 1000)
        # Exercise replacement of an old, hierarchical digital macro body.
        old_plain = digital.cell("plain")
        old_plain.clear()
        old_leaf = digital.create_cell("old_leaf")
        old_leaf.shapes(digital.layer(1, 0)).insert(pya.Box(0, 0, 600, 600))
        old_plain.insert(pya.CellInstArray(old_leaf.cell_index(), pya.Trans()))
        digital.write(str(apnr / "boundary.gds"))
        r = M1.run(arm, "boundary", "host", None)
        merged_arm = pya.Layout()
        merged_arm.read(str(arm / "phase3/mixed_signal/top_merged.gds"))
        assert [merged_arm.cell(i).name for i in merged_arm.each_top_cell()] == ["boundary"]
        assert not merged_arm.has_cell("old_leaf")
        assert merged_arm.cell("plain").bbox().width() == 400
        observed = [inst.trans for inst in merged_arm.cell("boundary").each_inst()
                    if merged_arm.cell(inst.cell_index).name == "plain"]
        assert pya.Trans(rot, mirror, 1000, 1000) in observed
        native_cases["orientation_" + orient] = "current KLayout merge verified"
    for damage in ("wrong_digital_top", "wrong_macro_cell", "digital_def_mismatch", "duplicate_digital_macro"):
        arm = root / damage
        shutil.copytree(project, arm)
        digital = pya.Layout()
        digital.read(str(pnr / "boundary.gds"))
        digital_top = digital.cell("boundary")
        if damage == "wrong_digital_top":
            digital_top.name = "other_top"
        elif damage in ("digital_def_mismatch", "duplicate_digital_macro"):
            for inst in digital_top.each_inst():
                if digital.cell(inst.cell_index).name == "plain" and inst.trans.disp.x == 1000:
                    if damage == "digital_def_mismatch":
                        inst.trans = pya.Trans(1100, 1000)
                    else:
                        digital_top.insert(pya.CellInstArray(inst.cell_index, inst.trans))
                    break
        else:
            wrong = pya.Layout()
            wrong.read(str(macro / "plain.gds"))
            wrong.cell("plain").name = "other_macro"
            wrong.write(str(arm / "phase3/analog/hardmacro/plain/plain.gds"))
        digital.write(str(arm / "phase3/stage3/pnr/boundary.gds"))
        r = M1.run(arm, "boundary", "host", None)
        assert r["verdict"] == "FAIL", r
        native_cases[damage] = "actual KLayout refusal verified"
    result["native_cases"] = native_cases
    (root / "native-result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    exercise(Path(sys.argv[1]).resolve())
