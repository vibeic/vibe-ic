"""U19 (IC_BLOCKER_AUDIT 2026-09-29): Step 37.5ic's release documents must name
the design and the PDK the run actually signed off.

MEASURED (spm IC/DIE run cx_spmic2_run, 2026-09-28): the run carried no
``input/project.json`` -- the only identity source ``tapeout_docs_gen`` read --
so it wrote ``BRIEF_NOT_MEASURED_NOT_MEASURED.html`` and
``SIGNOFF_NOT_MEASURED_NOT_MEASURED.html`` although the same tree held the
design's L1 ``ic_name`` and the PDK the sign-off tools ran on
(``phase3/librelane_pdk_root.provenance.json``). The fixtures below are that
tree's own values, minimised; the host path is dropped.

Rule now: design = --design / --ic-name, else input/project.json, else L1
``ic_name`` (``part_number``); PDK = --pdk, else the sign-off PDK record, else
input/project.json. Only when every source is absent is a field NOT_MEASURED,
and the program then names the sources it looked for.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parents[1] / "tapeout_docs_gen.py"

CLEAN = {
    "design__die__bbox": "0.0 0.0 3162.0 3162.0",
    "route__drc_errors": 0, "magic__drc_error__count": 0,
    "klayout__drc_error__count": 0, "klayout__density_error__count": 0,
    "antenna__violating__nets": 0, "antenna__violating__pins": 0,
    "design__lvs_error__count": 0, "design__lvs_unmatched_device__count": 0,
    "design__lvs_unmatched_net__count": 0, "design__lvs_unmatched_pin__count": 0,
    "design__xor_difference__count": 0,
    "timing__setup__ws": 0.5, "timing__setup__tns": 0.0,
    "timing__hold__ws": 0.3, "timing__hold__tns": 0,
    "design__max_slew_violation__count": 0, "design__max_cap_violation__count": 0,
}

# cx_spmic2_run/spm/phase1/generated_docs/L1_DATASHEET.json (identity keys only)
L1 = {"ic_name": "spm", "part_number": None}
# cx_spmic2_run/spm/phase3/librelane_pdk_root.provenance.json (host path dropped)
PDK_ROOT_RECEIPT = {
    "source": "resolved",
    "derivation": {"image_pdk_root": "/foss/pdks", "pdk": "gf180mcuD",
                   "pdk_from": "caller (the design's resolved PDK)",
                   "guest_path": "/foss/pdks/gf180mcuD"},
}


def _tree(root: Path, *, l1=True, receipt=True) -> Path:
    final = root / "phase3" / "final"
    final.mkdir(parents=True)
    (final / "metrics.json").write_text(json.dumps(CLEAN), encoding="utf-8")
    if l1:
        gd = root / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L1_DATASHEET.json").write_text(json.dumps(L1), encoding="utf-8")
    if receipt:
        (root / "phase3" / "librelane_pdk_root.provenance.json").write_text(
            json.dumps(PDK_ROOT_RECEIPT), encoding="utf-8")
    return root


def _run(project: Path, *extra):
    out = project / "reports" / "phase3" / "docs"
    r = subprocess.run([sys.executable, str(PROG), "--project", str(project),
                        "--out-dir", str(out), *extra],
                       capture_output=True, text=True)
    names = sorted(p.name for p in out.iterdir()) if out.is_dir() else []
    return r, names


def test_die_run_without_project_json_names_its_design_and_signoff_pdk(tmp_path):
    r, names = _run(_tree(tmp_path))
    assert r.returncode == 0, r.stderr
    assert names == ["BRIEF_spm_gf180mcuD.html", "SIGNOFF_spm_gf180mcuD.html"], names
    # the provenance of each identity is stated, not implied
    assert "phase1/generated_docs/L1_DATASHEET.json" in r.stdout, r.stdout
    assert "phase3/librelane_pdk_root.provenance.json" in r.stdout, r.stdout


def test_ic_name_flag_names_the_design(tmp_path):
    r, names = _run(_tree(tmp_path, l1=False), "--ic-name", "widget")
    assert r.returncode == 0, r.stderr
    assert names == ["BRIEF_widget_gf180mcuD.html", "SIGNOFF_widget_gf180mcuD.html"], names


def test_signoff_record_outranks_a_project_json_pdk(tmp_path):
    """The document describes what was signed off, so the used PDK names it."""
    project = _tree(tmp_path)
    (project / "input").mkdir()
    (project / "input" / "project.json").write_text(
        json.dumps({"design": "widget", "pdk": "otherpdk"}), encoding="utf-8")
    r, names = _run(project)
    assert r.returncode == 0, r.stderr
    assert names == ["BRIEF_widget_gf180mcuD.html", "SIGNOFF_widget_gf180mcuD.html"], names


def test_absent_sources_stay_not_measured_and_are_named(tmp_path):
    r, names = _run(_tree(tmp_path, l1=False, receipt=False))
    assert r.returncode == 0, r.stderr
    assert names == ["BRIEF_NOT_MEASURED_NOT_MEASURED.html",
                     "SIGNOFF_NOT_MEASURED_NOT_MEASURED.html"], names
    assert "L1_DATASHEET.json" in r.stdout and "librelane_pdk_root.provenance.json" in r.stdout, r.stdout
