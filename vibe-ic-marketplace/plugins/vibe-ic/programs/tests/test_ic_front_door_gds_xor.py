"""Ruling #88 D3: on the IC front door, D77's XOR key is KLayout's own XOR of
the delivered GDS against the signoff GDS of the same carrier.

The PASS and FAIL cases run the real deck (LibreLane's klayout/xor.drc through
`klayout -b`) wherever the EDA image provides it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import _gds_admission as admission
import gds_xor_check as g
import signoff_metrics_aggregate as aggregate
from _gdsii import minimal_gdsii_bytes

DELIVERED = "phase3/stage4/gds/TOP.gds"
SIGNOFF = "phase3/stage3/pnr/TOP.gds"
LAYOUT_DIGEST = "d" * 64


def _native_available() -> bool:
    if shutil.which("klayout") is None:
        return False
    try:
        import klayout.db  # noqa: F401
    except ImportError:
        return False
    probe = subprocess.run(["python3", "-c", g.NATIVE_XOR_SCRIPT_PROBE],
                           capture_output=True, text=True)
    return probe.returncode == 0 and probe.stdout.strip().endswith("/klayout/xor.drc")


needs_native = pytest.mark.skipif(not _native_available(),
                                  reason="KLayout with LibreLane's xor.drc is not in this environment")


def _layout(path: Path, *, extra_shape: bool = False) -> None:
    import klayout.db as db
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TOP")
    sub = layout.create_cell("SUB")
    sub.shapes(layout.layer(68, 20)).insert(db.Box(0, 0, 1000, 1000))
    top.insert(db.CellInstArray(sub.cell_index(), db.Trans(db.Point(5000, 0))))
    top.shapes(layout.layer(69, 20)).insert(db.Box(0, 0, 2000, 500))
    if extra_shape:
        top.shapes(layout.layer(68, 20)).insert(db.Box(10000, 10000, 11000, 11000))
    path.parent.mkdir(parents=True, exist_ok=True)
    layout.write(str(path))


def _admit(project: Path) -> None:
    """The signoff stream, admitted exactly as step 37 admits it."""
    basis = project / "phase3/stage3/pnr/TOP.def"
    basis.write_text("DESIGN TOP ;\n")
    (project / "reports/phase3").mkdir(parents=True, exist_ok=True)
    (project / "reports/phase3/prestream_gate.json").write_text(
        json.dumps({"verdict": "PASS", "layout_digest": LAYOUT_DIGEST}))
    admission.admit_gds(project, project / SIGNOFF, LAYOUT_DIGEST, [basis])


def _carrier(project: Path, *, extra_shape: bool = False) -> Path:
    _layout(project / DELIVERED)
    _layout(project / SIGNOFF, extra_shape=extra_shape)
    _admit(project)
    return project


def _structure_only_carrier(project: Path) -> Path:
    for rel in (DELIVERED, SIGNOFF):
        (project / rel).parent.mkdir(parents=True, exist_ok=True)
        (project / rel).write_bytes(minimal_gdsii_bytes(cell="TOP"))
    _admit(project)
    return project


def _receipt(project: Path) -> dict:
    return json.loads((project / g.REPORT_REL).read_text())


@needs_native
def test_identical_geometry_is_pass_and_d77_reads_zero(tmp_path):
    report = g.native_delivered_xor(_carrier(tmp_path))
    assert report == _receipt(tmp_path)
    assert (report["verdict"], report["rc"], report["design__xor_difference__count"]) == ("PASS", 0, 0)
    assert report["layer_differences"] == [
        {"layer": 68, "datatype": 20, "differences": 0},
        {"layer": 69, "datatype": 20, "differences": 0}]
    assert report["design_layer_differences"] == []
    assert report["reference"]["kind"] == "signoff_gds"
    assert report["reference"]["path"] == SIGNOFF and report["delivered"]["path"] == DELIVERED
    assert report["native"]["script"].endswith("/klayout/xor.drc")
    assert report["native"]["argv"][1:3] == ["-b", "-r"]
    cell = aggregate._xor(tmp_path)
    assert cell.value == 0 and cell.source == g.REPORT_REL
    assert "delivered GDS against the signoff GDS" in cell.basis


@needs_native
def test_one_shape_difference_is_fail(tmp_path):
    report = g.native_delivered_xor(_carrier(tmp_path, extra_shape=True))
    assert (report["verdict"], report["rc"], report["design__xor_difference__count"]) == ("FAIL", 1, 1)
    assert report["design_layer_differences"] == [{"layer": 68, "datatype": 20, "differences": 1}]
    assert {row["layer"]: row["differences"] for row in report["layer_differences"]} == {68: 1, 69: 0}
    assert aggregate._xor(tmp_path).value == 1


@needs_native
@pytest.mark.parametrize("swap_timing", ["before_native", "after_native"])
def test_signoff_gds_replaced_during_native_run_is_not_measured(tmp_path, monkeypatch, swap_timing):
    import _klayout_launch as kl
    project = _carrier(tmp_path, extra_shape=True)
    control = g.native_delivered_xor(project)
    assert (control["verdict"], control["design__xor_difference__count"]) == ("FAIL", 1)
    runner = kl.find_runner(project=project)
    run = runner.run_argv

    def replace_signoff():
        (project / SIGNOFF).write_bytes((project / DELIVERED).read_bytes())

    def swap_at_native_run(argv, env, *, timeout=1800):
        if argv[:2] == ["python3", "-c"]:
            return run(argv, env, timeout=timeout)
        if swap_timing == "before_native":
            replace_signoff()
        result = run(argv, env, timeout=timeout)
        if swap_timing == "after_native":
            replace_signoff()
        return result

    monkeypatch.setattr(runner, "run_argv", swap_at_native_run)
    report = g.native_delivered_xor(project, runner=runner)
    assert report["native"]["rc"] == 0
    assert not admission.admitted_gds(project, project / SIGNOFF)
    assert (report["verdict"], report["rc"]) == ("NOT_MEASURED", 2)
    assert "signoff GDS changed after admission" in report["reason"]
    assert "design__xor_difference__count" not in report
    assert aggregate._xor(project).value == aggregate.NOT_MEASURED


class _BrokenKLayout:
    """Resolves the deck, then the tool run fails."""
    kind, detail = "host", "stub"

    def covers(self, _path):
        return True

    def cpath(self, path):
        return str(path)

    def klayout_bin(self):
        return "klayout"

    def run_argv(self, argv, env, *, timeout=1800):
        if argv[:2] == ["python3", "-c"]:
            return 0, "/image/librelane/scripts/klayout/xor.drc\n", ""
        return 1, "", "ERROR: In xor.drc: unreadable layout"


def test_tool_failure_is_not_measured(tmp_path):
    report = g.native_delivered_xor(_structure_only_carrier(tmp_path), runner=_BrokenKLayout())
    assert (report["verdict"], report["rc"]) == ("NOT_MEASURED", 2)
    assert report["reason"].startswith("XOR_NATIVE_FAILED: rc=1")
    assert "design__xor_difference__count" not in report
    cell = aggregate._xor(tmp_path)
    assert cell.value == aggregate.NOT_MEASURED and "XOR_NATIVE_FAILED" in cell.reason


def test_absent_tool_is_not_measured(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBEIC_KLAYOUT_FORCE_ABSENT", "1")
    report = g.native_delivered_xor(_structure_only_carrier(tmp_path))
    assert report["verdict"] == "NOT_MEASURED"
    assert report["reason"].startswith("XOR_TOOL_ABSENT")


def test_a_stream_not_admitted_for_signoff_is_not_measured(tmp_path):
    project = _structure_only_carrier(tmp_path)
    (project / "reports/phase3/prestream_gate.json").write_text(
        json.dumps({"verdict": "FAIL", "layout_digest": LAYOUT_DIGEST}))
    report = g.native_delivered_xor(project, runner=_BrokenKLayout())
    assert report["verdict"] == "NOT_MEASURED"
    assert report["reason"].startswith("XOR_SIGNOFF_GDS_NOT_ADMITTED")
