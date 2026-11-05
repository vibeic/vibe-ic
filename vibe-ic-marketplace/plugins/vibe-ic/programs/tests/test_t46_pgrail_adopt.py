"""The adopted route and the preroute PG connect retain their own state."""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as R  # noqa: E402


def _tcl(body: str, tmp_path: Path):
    assert shutil.which("tclsh")
    script = tmp_path / "probe.tcl"
    script.write_text(body)
    return subprocess.run(["tclsh", str(script)], text=True, cwd=tmp_path,
                          capture_output=True, check=False)










def test_both_antenna_boundaries_gate_before_the_next_stage():
    src = Path(R.__file__).read_text()
    for tag in ("after_postroute_antenna_repair",
                "after_postroute_antenna_reconverge"):
        probe = f'_unrouted_probe_tcl("{tag}", out_dir_c)'
        guard = f'_unrouted_boundary_guard_tcl("{tag}")'
        assert src.index(probe) < src.index(guard)
        assert guard in src
    assert '_wire_content_census_tcl("_vic_adopt_wire") + common' in src
    assert '{spef_repair_block}{_adopt_route_presence_guard_tcl()}' in src


def test_successful_scoped_antenna_route_cannot_drop_a_held_net(tmp_path):
    # The fork reported success while three of its supposedly held nets lost
    # wire. Reuse the existing Tcl ODB emulator but make the native call return
    # success, which was the missing branch of its damage census.
    from test_r0915_121_a_pass_answers_for_every_wire_it_took import (  # noqa: E402
        _H, _tcl as antenna_tcl,
    )
    harness = (_H % {"seq": "5 5 0", "inserts": "d1", "unwire": "nX",
                     "shrink": ""}).replace(
                         'error "DRT-0206 checkConnectivity"', 'return ""')
    r = _tcl(harness + antenna_tcl(), tmp_path)
    assert r.returncode != 0
    assert "ANTENNA_SCOPED_HELD_WIRE_DAMAGE" in r.stdout
    assert "ANTENNA_DIODE_ROLLED_BACK" in r.stdout
    assert "ANTENNA_REPAIR_REFUSED_ROLLBACK_REQUEST:" in r.stdout
    assert "nX" in r.stdout


def test_successful_scoped_antenna_route_keeps_an_intact_held_net(tmp_path):
    from test_r0915_121_a_pass_answers_for_every_wire_it_took import (  # noqa: E402
        _H, _tcl as antenna_tcl,
    )
    harness = (_H % {"seq": "5 5 0", "inserts": "d1", "unwire": "",
                     "shrink": ""}).replace(
                         'error "DRT-0206 checkConnectivity"', 'return ""')
    r = _tcl(harness + antenna_tcl(), tmp_path)
    assert r.returncode == 0, r.stderr
    assert "ANTENNA_SCOPED_HELD_WIRE_DAMAGE" not in r.stdout
