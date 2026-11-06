"""Native absent-tool behavior remains available to analog and hardmacro tools."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import _plugin_tree
import _container_exec as CE
import _eda_pin as PIN
from _stated_eda_image import state_the_image_for_children

PROGRAMS = Path(_plugin_tree.plugin_path("programs"))
CONTAINER = "vibeic-eda"

RUNNABLE_DECK = (
    "* tb\n"
    ".subckt blk vin vout\n"
    "R1 vin vout 1k\n"
    ".ends\n"
    "X1 vin vout blk\n"
    "Vdd vin 0 3.0\n"
    ".tran 1n 100n\n"
    ".meas tran vout_v AVG v(vout)\n"
    ".end\n")

LIVENESS_DECK = ("* runner transient\n"
                 "Vdd vdd 0 1.8\nVss vss 0 0\n"
                 "R1 vdd nall 1k\nR2 nall ndac 1k\nR3 ndac nq_n 1k\n"
                 ".control\ntran 1n 100n\n.endc\n.end\n")

@pytest.fixture(autouse=True)
def _the_stated_image(monkeypatch):
    """The pin is STATED, in this process and in every program it spawns
    (lane rfimg2). It used to be read from THIS HOST's docker at collection
    (`PIN.IMAGE_DIGEST` in a module constant), so inside the image (no docker)
    the whole file was a collection error, and on a host the arms compared the
    stub container against whatever that host happened to hold."""
    state_the_image_for_children(monkeypatch)

def _stub_docker(tmp_path: Path, digest: str) -> Path:
    """A `docker` on PATH reporting `digest` as the container's image.

    `inspect` is how the pin state is measured; every other verb exits 0 with
    no output, so a MATCH arm walks the ordinary path and lands on the ordinary
    "the simulator is not in this container" — the capability gap that IS
    honest here, and the thing a mismatch must never be reported as.
    """
    d = tmp_path / "stub_bin"
    d.mkdir(parents=True, exist_ok=True)
    (d / "docker").write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "a = sys.argv[1:]\n"
        "if a and a[0] == 'inspect':\n"
        f"    print('sha256:aaaa\\trepo@{digest}')\n"
        "    sys.exit(0)\n"
        "sys.exit(0)\n",
        encoding="utf-8")
    (d / "docker").chmod(0o755)
    return d

def _env_with(stub_bin: Path) -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}{os.pathsep}{env.get('PATH', '')}"
    return env

def _run(prog: str, *args: str, env: dict) -> subprocess.CompletedProcess:
    """A program as a SUBPROCESS, because the defect is an exception reaching
    an EXIT CODE: an in-process call sees the exception and never learns what
    rc a caller was handed."""
    return subprocess.run([sys.executable, str(PROGRAMS / prog), *args],
                          capture_output=True, text=True, env=env, check=False)

def _analog_block(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    b = project / "phase3" / "analog" / "blk"
    b.mkdir(parents=True)
    (b / "spec.json").write_text(
        json.dumps({"specs": [{"name": "vout_v", "min": 1.7, "max": 1.9}]}),
        encoding="utf-8")
    (b / "tb_blk.sp").write_text(RUNNABLE_DECK, encoding="utf-8")
    # A4's A3-precondition is checked BEFORE the simulator probe, and rightly:
    # a block with no A3 netlist has nothing of this design to measure. So the
    # deck is here, and the run reaches the probe the refusal fires from.
    (b / "blk.sp").write_text(
        "* _provenance: producer=analog_a3_netlist_emit schema=1\n"
        ".subckt blk vin vout\n"
        "R1 vin vout 1k\n"
        ".ends\n", encoding="utf-8")
    return project

def test_a_matching_container_still_answers_the_ordinary_capability_gap(
        tmp_path, monkeypatch):
    """THE PAIRED ARM. The stub has no ngspice, so the honest answer on a
    container AT the pin is `False` — and that answer must still be reachable,
    or this fix has simply made every container refuse."""
    import analog_real_corner_sweep as ARS
    ARS._NGSPICE_CACHE.clear()
    monkeypatch.setenv(
        "PATH", f"{_stub_docker(tmp_path, PIN.IMAGE_DIGEST)}"
                f"{os.pathsep}{os.environ['PATH']}")
    assert ARS._ngspice_available(CONTAINER) is False

def test_a4_on_a_matching_container_takes_the_ordinary_path(tmp_path):
    """THE PAIRED ARM: the stub holds the pin and has no ngspice, so A4 must
    reach its ordinary "ngspice not in container" and its ordinary rc."""
    project = _analog_block(tmp_path)
    cp = _run("analog_real_corner_sweep.py", str(project), "--block", "blk",
              "--container", CONTAINER,
              env=_env_with(_stub_docker(tmp_path, PIN.IMAGE_DIGEST)))
    assert cp.returncode != CE.EX_ENV_REFUSED, cp.stderr
    assert "ngspice not in container" in cp.stderr, cp.stderr

def test_mc_yield_on_a_matching_container_still_skips_for_an_absent_ngspice(
        tmp_path):
    """THE PAIRED ARM. SKIP for a genuinely absent simulator is the CORRECT
    answer and must survive this change."""
    project = _analog_block(tmp_path)
    cp = _run("analog_mc_yield_run.py", str(project), "--block", "blk",
              "--n", "2", "--container", CONTAINER,
              env=_env_with(_stub_docker(tmp_path, PIN.IMAGE_DIGEST)))
    rep = json.loads(cp.stdout)
    assert rep["verdict"] == "SKIP", rep
    assert cp.returncode != CE.EX_ENV_REFUSED

def _lec_project(tmp_path: Path) -> Path:
    project = tmp_path / "lecproj"
    (project / "phase2/stage1/rtl").mkdir(parents=True)
    (project / "phase2/stage2/synth").mkdir(parents=True)
    src = "module top(input a, output y); assign y = ~a; endmodule\n"
    (project / "phase2/stage1/rtl/top.v").write_text(src, encoding="utf-8")
    (project / "phase2/stage2/synth/netlist.v").write_text(src,
                                                           encoding="utf-8")
    return project

def test_lec_run_on_a_matching_container_takes_the_ordinary_path(tmp_path):
    """THE PAIRED ARM. The stub holds the pin and has no yosys, so lec_run must
    reach its ordinary disclosed-skip and write its ordinary report."""
    project = _lec_project(tmp_path)
    cp = _run("lec_run.py", str(project), "--top", "top",
              "--container", CONTAINER,
              env=_env_with(_stub_docker(tmp_path, PIN.IMAGE_DIGEST)))
    assert cp.returncode != CE.EX_ENV_REFUSED, cp.stderr
    assert (project / "reports" / "lec.json").is_file(), cp.stderr

def _liveness_block(tmp_path: Path) -> Path:
    """A block whose type DECLARES liveness nodes, so the run reaches the
    simulator probe rather than the honest `NOT_DECLARED` gap before it."""
    import analog_a2_topology_emit as A2
    project = tmp_path / "livproj"
    b = project / "phase3" / "analog" / "blk" / "sizing_loop"
    b.mkdir(parents=True)
    entry = A2.LIBRARY["delta_sigma"]
    (b.parent / "topology.json").write_text(json.dumps({
        "block_type": "delta_sigma",
        "rails": entry["rails"],
        A2.LIVENESS_NODES_KEY: entry[A2.LIVENESS_NODES_KEY]}), encoding="utf-8")
    (b / "pt0.sp").write_text(LIVENESS_DECK, encoding="utf-8")
    (b / "pt0.ngspice.log").write_text("* the runner ran it\n", encoding="utf-8")
    return project

def test_the_liveness_export_still_refuses_honestly_for_an_absent_ngspice(
        tmp_path):
    """THE PAIRED ARM. "ngspice is not reachable" for a container AT the pin
    that really has no ngspice is the CORRECT answer and must survive."""
    project = _liveness_block(tmp_path)
    cp = _run("analog_loop_liveness_samples_emit.py", str(project),
              "--block", "blk", "--container", CONTAINER,
              env=_env_with(_stub_docker(tmp_path, PIN.IMAGE_DIGEST)))
    assert cp.returncode != CE.EX_ENV_REFUSED, cp.stderr
    rec = json.loads(cp.stdout)
    assert rec["verdict"] == "REFUSED", rec
    assert "ngspice is not reachable" in rec["reason"], rec

def test_the_magic_reason_still_names_an_absent_tool_on_a_matching_container(
        tmp_path, monkeypatch):
    """THE PAIRED ARM. The capability gap is the CORRECT sentence when the
    container really is the pinned one and really has no magic."""
    import digital_hardmacro_gen as HM
    monkeypatch.setenv(
        "PATH", f"{_stub_docker(tmp_path, PIN.IMAGE_DIGEST)}"
                f"{os.pathsep}{os.environ['PATH']}")
    why = HM.magic_absent_reason(CONTAINER)
    assert "not on PATH inside container" in why, why
