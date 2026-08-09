#!/usr/bin/env python3
"""#902 — the PINNED, VERIFIED container image must be the one that simulates.

The defect
----------
`vibe_ic_one_shot_runner` verifies WHICH image `--container` runs
(`_capture_container_image` -> `container_image_provenance.verify`, and under
`--require-image` it aborts the run on MISMATCH). It then hands the phase
runners only `--container`. `design_one_shot_runner._iverilog_exec_container`
decided WHERE the sim executes and answered HOST-FIRST: if `shutil.which(
"iverilog")` found anything at all on the host, the compile+run went to the
HOST and the verified image was never used.

MEASURED 2026-08-10 across five machines running this same plugin against the
same pinned container image:

    host with no host-side iverilog   -> container Icarus 14.0 (devel)
    host with /usr/local/bin/iverilog -> HOST      Icarus 12.0 (stable)
    host with /usr/bin/iverilog       -> HOST      Icarus 11.0 (stable)

Three different Icarus MAJORS compiling the same RTL, chosen by what the
operating system happened to have installed. A cross-host result difference
therefore could not be attributed to the design.

How this file is structured
---------------------------
Only RETURNED VALUES and EMITTED JSON are asserted — never the presence or
absence of a string in a source file.

The two groups are a MUTATION PAIR, and each has a job:

  GROUP A  the fix does something.
           Every test here FAILS when `design_one_shot_runner.py` is restored
           from origin/main, and passes after the fix.

  GROUP B  the opposite verdict is still REACHABLE — host execution has not
           been made impossible.
           Every test here is written ONLY against shapes that exist on BOTH
           sides (`_run_iverilog_stage`, `_iverilog_available`), so it PASSES
           on the unfixed program too. That is the point: a decision function
           that can only ever answer "container" would be exactly as broken as
           one that can only ever answer "host", and group B is what rules it
           out. If group B ever starts failing on the unfixed program, it has
           stopped testing what it claims to.

chip-AGNOSTIC: no design name, PDK name or part number anywhere — synthetic
container names, synthetic paths, synthetic digests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as dosr  # noqa: E402

# Synthetic, content-addressed image identity. Not any real image.
FAKE_DIGEST = "sha256:" + "ab" * 32
FAKE_TAG = "example.invalid/synthetic-eda:9.9.9"


@pytest.fixture(autouse=True)
def _clear_identity_cache():
    """The image-identity probe is memoised per process; clear it so each test
    observes its own monkeypatched docker."""
    cache = getattr(dosr, "_SIM_IMAGE_IDENTITY_CACHE", None)
    if cache is not None:
        cache.clear()
    yield
    if cache is not None:
        cache.clear()


def _host_has_iverilog(monkeypatch):
    monkeypatch.setattr("shutil.which",
                        lambda t: "/usr/bin/iverilog" if t == "iverilog"
                        else None)


def _host_has_no_iverilog(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _t: None)


def _container_carries_iverilog(monkeypatch, yes: bool = True):
    monkeypatch.setattr(dosr, "_tool_in_container",
                        lambda _c, t: yes and t == "iverilog")


def _mounts(monkeypatch, visible: bool = True):
    monkeypatch.setattr(dosr, "_path_in_container", lambda _p, _c: visible)
    monkeypatch.setattr(dosr, "_to_container_path", lambda p, _c: str(p))


def _capture_dispatch(monkeypatch):
    """Record which of the two execution paths the stage actually took."""
    seen = {}

    def _fake_docker_exec(container, cmd, timeout=600, **_k):
        seen["where"] = "container"
        seen["container"] = container
        seen["cmd"] = cmd
        return 0, "CONTAINER_STDOUT", ""

    def _fake_run(argv, cwd=None, timeout=600, env=None):
        seen["where"] = "host"
        seen["argv"] = list(argv)
        seen["cwd"] = str(cwd)
        return 0, "HOST_STDOUT", ""

    monkeypatch.setattr(dosr, "_docker_exec", _fake_docker_exec)
    monkeypatch.setattr(dosr, "_run", _fake_run)
    return seen


def _fake_image_identity(monkeypatch, status="ok"):
    import container_image_provenance as cip

    def _fake_inspect(name):
        if status != "ok":
            return {"status": status, "container": name}
        return {"status": "ok", "container": name,
                "image_ref": FAKE_TAG, "image_id": FAKE_DIGEST,
                "running": True, "created": "2026-01-01T00:00:00Z"}

    monkeypatch.setattr(cip, "inspect_container", _fake_inspect)


# =========================================================================
# GROUP A — the verified pin IS the one used.
# Every test here FAILS against origin/main.
# =========================================================================
def test_A1_container_wins_even_when_host_also_has_iverilog(monkeypatch, tmp_path):
    """The exact #902 shape: BOTH sides have iverilog. Before the fix the host
    won and the verified image was bypassed; now the container wins."""
    _host_has_iverilog(monkeypatch)
    _container_carries_iverilog(monkeypatch)
    _mounts(monkeypatch, visible=True)
    _fake_image_identity(monkeypatch)
    seen = _capture_dispatch(monkeypatch)

    argv = ["iverilog", "-g2012", "-o", str(tmp_path / "a.vvp"),
            str(tmp_path / "tb.v")]
    rc, out, _err = dosr._run_iverilog_stage(argv, tmp_path, "synth_box", 120)

    assert seen["where"] == "container"
    assert (rc, out) == (0, "CONTAINER_STDOUT")
    assert seen["container"] == "synth_box"


def test_A2_vvp_run_follows_the_compile_into_the_container(monkeypatch, tmp_path):
    """The .vvp RUN must land in the same image as the compile, otherwise the
    two halves of one sim come from two toolchains."""
    _host_has_iverilog(monkeypatch)
    _container_carries_iverilog(monkeypatch)
    _mounts(monkeypatch, visible=True)
    _fake_image_identity(monkeypatch)
    seen = _capture_dispatch(monkeypatch)

    rc, out, _err = dosr._sim_run_or_reuse(
        "iverilog_g2012", tmp_path / "a.vvp", 0, "", "", tmp_path,
        timeout=120, container="synth_box")

    assert seen["where"] == "container"
    assert (rc, out) == (0, "CONTAINER_STDOUT")
    assert "vvp" in seen["cmd"]


def test_A3_provenance_records_the_digest_not_only_the_tag(monkeypatch, tmp_path):
    """The run record must name the image by CONTENT ADDRESS. A tag is mutable:
    on one measured host the container named after the EDA image ran a
    several-release older tag than its siblings on the same machine."""
    _host_has_iverilog(monkeypatch)
    _container_carries_iverilog(monkeypatch)
    _mounts(monkeypatch, visible=True)
    _fake_image_identity(monkeypatch)
    _capture_dispatch(monkeypatch)

    dosr._run_iverilog_stage(["iverilog", "-o", str(tmp_path / "a.vvp")],
                             tmp_path, "synth_box", 120)

    rec = json.loads((tmp_path / "sim_toolchain.json").read_text())
    assert rec["exec"] == "container"
    assert rec["container"] == "synth_box"
    assert rec["image_id"] == FAKE_DIGEST
    assert rec["image_id"].startswith("sha256:")
    # the tag is recorded, but it is NOT the identity field
    assert rec["image_ref_mutable_tag"] == FAKE_TAG


def test_A4_provenance_HOST_branch_is_reachable(monkeypatch, tmp_path):
    """Opposite verdict of the RECORDER: it must be able to emit `host` and
    claim no image. A recorder that can only ever emit `container` would be the
    same defect class as a monitor whose success branch is unreachable."""
    _host_has_iverilog(monkeypatch)
    _capture_dispatch(monkeypatch)

    dosr._run_iverilog_stage(["iverilog", "-o", str(tmp_path / "a.vvp")],
                             tmp_path, "", 120)

    rec = json.loads((tmp_path / "sim_toolchain.json").read_text())
    assert rec["exec"] == "host"
    assert rec["container"] is None
    assert "image_id" not in rec            # no image was used; claim none
    assert rec["iverilog_path"] == "/usr/bin/iverilog"


def test_A5_provenance_is_honest_when_identity_cannot_be_resolved(
        monkeypatch, tmp_path):
    """No docker to ask -> say so; never fabricate a digest."""
    _host_has_iverilog(monkeypatch)
    _container_carries_iverilog(monkeypatch)
    _mounts(monkeypatch, visible=True)
    _fake_image_identity(monkeypatch, status="docker_absent")
    _capture_dispatch(monkeypatch)

    dosr._run_iverilog_stage(["iverilog", "-o", str(tmp_path / "a.vvp")],
                             tmp_path, "synth_box", 120)

    rec = json.loads((tmp_path / "sim_toolchain.json").read_text())
    assert rec["exec"] == "container"
    assert "image_id" not in rec
    assert rec["image_identity_unresolved"] == "docker_absent"


@pytest.mark.parametrize("host_has,cont_has", [
    (True, True), (True, False), (False, True), (False, False)])
def test_A6_availability_and_execution_never_disagree(monkeypatch, tmp_path,
                                                      host_has, cont_has):
    """`_iverilog_available` already preferred the CONTAINER while the
    execution decision preferred the HOST. Whenever the sim is reported
    available, it must actually run on a side that has the tool, and the two
    decisions must be reached the same way."""
    monkeypatch.setattr(
        "shutil.which",
        (lambda t: "/usr/bin/iverilog" if t == "iverilog" else None)
        if host_has else (lambda _t: None))
    _container_carries_iverilog(monkeypatch, yes=cont_has)
    _mounts(monkeypatch, visible=True)
    _fake_image_identity(monkeypatch)
    seen = _capture_dispatch(monkeypatch)

    assert dosr._iverilog_available("box") is (host_has or cont_has)
    dosr._run_iverilog_stage(["iverilog", "-o", str(tmp_path / "a.vvp")],
                             tmp_path, "box", 120)

    # the container is preferred whenever it can do the job
    assert seen["where"] == ("container" if cont_has else "host")


# =========================================================================
# GROUP B — the OPPOSITE verdict is still reachable.
# Every test here PASSES on BOTH the unfixed and the fixed program: it uses
# only shapes that exist on both sides. This is what proves the fix did not
# turn the decision into an unconditional "always dispatch".
# =========================================================================
def test_B1_no_container_supplied_runs_on_host(monkeypatch, tmp_path):
    """True host mode. argv reaches the host verbatim, cwd = run_dir."""
    _host_has_iverilog(monkeypatch)
    monkeypatch.setattr(dosr, "_tool_in_container",
                        lambda *_a: pytest.fail(
                            "must not probe a container that was not supplied"))
    seen = _capture_dispatch(monkeypatch)

    argv = ["iverilog", "-g2012", "-o", str(tmp_path / "a.vvp"),
            str(tmp_path / "tb.v")]
    rc, out, _err = dosr._run_iverilog_stage(argv, tmp_path, "", 120)

    assert seen["where"] == "host"
    assert (rc, out) == (0, "HOST_STDOUT")
    assert seen["argv"] == argv
    assert seen["cwd"] == str(tmp_path)


def test_B2_container_without_iverilog_falls_back_to_host(monkeypatch, tmp_path):
    """A container that carries no iverilog must not swallow the sim."""
    _host_has_iverilog(monkeypatch)
    _container_carries_iverilog(monkeypatch, yes=False)
    seen = _capture_dispatch(monkeypatch)

    rc, out, _err = dosr._run_iverilog_stage(
        ["iverilog", "-o", str(tmp_path / "a.vvp")], tmp_path, "empty_box", 120)

    assert seen["where"] == "host"
    assert (rc, out) == (0, "HOST_STDOUT")


def test_B3_container_blind_to_the_project_tree_falls_back_to_host(
        monkeypatch, tmp_path):
    """`--container` may name a container with no bind-mount covering the
    project. Dispatching there would only fail on missing files, so when the
    host can run the sim it stays on the host. This escape existed before the
    fix (as a side effect of host-first) and must remain reachable after it."""
    _host_has_iverilog(monkeypatch)
    _container_carries_iverilog(monkeypatch)
    _mounts(monkeypatch, visible=False)
    seen = _capture_dispatch(monkeypatch)

    rc, out, _err = dosr._run_iverilog_stage(
        ["iverilog", "-o", str(tmp_path / "a.vvp")], tmp_path, "unmounted", 120)

    assert seen["where"] == "host"
    assert (rc, out) == (0, "HOST_STDOUT")


def test_B4_container_only_iverilog_still_dispatches(monkeypatch, tmp_path):
    """The pre-existing container path is untouched: host has nothing, the
    container has iverilog -> dispatch, with paths translated."""
    _host_has_no_iverilog(monkeypatch)
    _container_carries_iverilog(monkeypatch)
    _mounts(monkeypatch, visible=True)
    _fake_image_identity(monkeypatch)
    seen = _capture_dispatch(monkeypatch)

    rc, out, _err = dosr._run_iverilog_stage(
        ["iverilog", "-o", str(tmp_path / "a.vvp")], tmp_path, "only_box", 120)

    assert seen["where"] == "container"
    assert (rc, out) == (0, "CONTAINER_STDOUT")
    assert dosr.TOOLS_IN_CONTAINER + "/bin" in seen["cmd"]


def test_B5_blind_container_still_wins_when_the_host_cannot_simulate(
        monkeypatch, tmp_path):
    """The mount escape is guarded: falling back to a host with NO iverilog
    would trade a path error for `command not found`. With nothing on the host,
    the container is still where the sim goes."""
    _host_has_no_iverilog(monkeypatch)
    _container_carries_iverilog(monkeypatch)
    _mounts(monkeypatch, visible=False)
    _fake_image_identity(monkeypatch)
    seen = _capture_dispatch(monkeypatch)

    rc, out, _err = dosr._run_iverilog_stage(
        ["iverilog", "-o", str(tmp_path / "a.vvp")], tmp_path, "unmounted", 120)

    assert seen["where"] == "container"
    assert (rc, out) == (0, "CONTAINER_STDOUT")


def test_B6_neither_side_has_iverilog_stays_unavailable(monkeypatch):
    """Absent in BOTH -> availability False, so the deterministic no-sim WAIVE
    still fires and no fake sim verdict is produced."""
    _host_has_no_iverilog(monkeypatch)
    _container_carries_iverilog(monkeypatch, yes=False)
    assert dosr._iverilog_available("some_box") is False


def test_B7_verilator_escape_never_dispatches_a_vvp(monkeypatch, tmp_path):
    """`verilator_sva` already ran its native binary; the shared gate must reuse
    the captured result and touch neither execution path."""
    _host_has_iverilog(monkeypatch)
    _container_carries_iverilog(monkeypatch)
    _mounts(monkeypatch, visible=True)
    monkeypatch.setattr(dosr, "_docker_exec",
                        lambda *_a, **_k: pytest.fail("must not dispatch"))
    monkeypatch.setattr(dosr, "_run",
                        lambda *_a, **_k: pytest.fail("must not run vvp"))

    rc, out, err = dosr._sim_run_or_reuse(
        "verilator_sva", tmp_path / "never.vvp", 0, "ALREADY_RAN", "",
        tmp_path, timeout=120, container="synth_box")
    assert (rc, out, err) == (0, "ALREADY_RAN", "")
