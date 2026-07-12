"""#118 — step_yosys_synth's PRIMARY yosys docker fallback assumed the host
synth_dir is bind-mounted inside the container at the same path: it ran
`docker exec -w <host synth_dir>` blindly, dying rc=127 with an opaque OCI
"chdir to cwd ... no such file or directory" on a mount-less container
(reproduced live on an isolated no-mount vibeic/vibeic-eda:0.2.12: step FAIL
rc=127, no netlist; post-fix the same staging PASSes with the netlist
retrieved). The SV fallback three lines below already used the mount-aware
machinery (_phase2_container_workdir -> docker-cp staging -> netlist copy
back); the fix routes the primary fallback through the same machinery:
mounted -> unchanged in-place exec; unmounted -> stage sources + $readmemh
aux files into an ephemeral in-container dir, rewrite the script's host
paths, run there, copy the netlist back, clean up.

These tests pin the COMMAND SEQUENCE at the _run boundary (no docker
needed): the defect shape is "exec -w <host path> against an unmounted
container", the end state is "staged exec + netlist retrieval, no host-path
chdir".
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as R          # noqa: E402


def _stage_proj(tmp_path):
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "counter.v").write_text(
        "module counter (\n    input clk,\n    input resetn,\n"
        "    output reg [7:0] cnt\n);\n"
        "    always @(posedge clk) begin\n"
        "        if (!resetn) cnt <= 8'd0;\n"
        "        else cnt <= cnt + 8'd1;\n    end\nendmodule\n")
    return proj


_FAKE_NETLIST = (
    "module counter(clk, resetn, cnt);\n"
    "  input clk, resetn; output [7:0] cnt;\n"
    + "".join(
        f"  \\$_DFF_P_ q{i} (.C(clk), .D(d{i}), .Q(cnt[{i % 8}]));\n"
        for i in range(12))
    + "endmodule\n")


class _RunRecorder:
    """Fake R._run: host yosys is absent (127); docker calls are recorded and
    answered success; the netlist-retrieval docker cp materializes out_v."""

    def __init__(self, synth_dir):
        self.calls = []
        self.synth_dir = synth_dir

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        if cmd and cmd[0] == "yosys":
            return 127, "", "COMMAND_NOT_FOUND: simulated host without yosys"
        if cmd[:2] == ["docker", "cp"] and ":" in cmd[2]:
            # retrieval: container:src -> host dst; materialize the netlist
            Path(cmd[3]).write_text(_FAKE_NETLIST)
            return 0, "", ""
        if cmd[:2] == ["docker", "exec"] and "yosys -p" in " ".join(cmd):
            return 0, "Number of cells: 44", ""
        return 0, "", ""


def test_unmounted_container_routes_through_staging(tmp_path, monkeypatch):
    """Defect shape: unmounted container. End state: NO `docker exec -w
    <host synth_dir>`; sources docker-cp'd into an in-container staging dir,
    the script's host paths rewritten, the netlist copied back, staging
    cleaned up — and the step PASSes."""
    proj = _stage_proj(tmp_path)
    synth_dir = R._pl.synth_dir(proj)
    rec = _RunRecorder(synth_dir)
    monkeypatch.setattr(R, "_run", rec)
    monkeypatch.setattr(R, "_path_in_container", lambda p, c: False)
    monkeypatch.setattr(
        R, "_phase2_container_workdir",
        lambda c, p, s: ("/tmp/vibeic_test_stage", True))
    res = R.step_yosys_synth(proj, "counter", container="test-eda")
    assert res.status == "PASS", (res.status, res.detail)
    joined = ["\x20".join(c) for c in rec.calls]
    # the defect shape must be GONE: no exec -w <host synth_dir>
    assert not any(f"-w {synth_dir}" in j for j in joined), joined
    # sources staged in
    assert any(j.startswith("docker cp") and "test-eda:/tmp/vibeic_test_stage/"
               in j for j in joined), joined
    # yosys ran in the staging dir with REWRITTEN paths
    ex = [j for j in joined if "yosys -p" in j and "docker exec" in j]
    assert ex and "-w /tmp/vibeic_test_stage" in ex[0], ex
    assert str(synth_dir) not in ex[0], "host path leaked into staged script"
    # netlist retrieved to the host
    out_v = synth_dir / "netlist_yosys.v"
    assert out_v.is_file() and out_v.stat().st_size > 0
    # staging cleaned up
    assert any("rm -rf /tmp/vibeic_test_stage" in j for j in joined), joined


def test_mounted_container_behavior_frozen(tmp_path, monkeypatch):
    """Mounted container: the fallback stays byte-identical — one in-place
    `docker exec -w <host synth_dir>` with the UNREWRITTEN script, no staging
    docker cp of sources."""
    proj = _stage_proj(tmp_path)
    synth_dir = R._pl.synth_dir(proj)

    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if cmd and cmd[0] == "yosys":
            return 127, "", "COMMAND_NOT_FOUND: simulated"
        if cmd[:2] == ["docker", "exec"] and "yosys -p" in " ".join(cmd):
            # the mounted container writes through the bind mount
            (synth_dir / "netlist_yosys.v").write_text(_FAKE_NETLIST)
            return 0, "Number of cells: 44", ""
        return 0, "", ""

    monkeypatch.setattr(R, "_run", fake_run)
    monkeypatch.setattr(R, "_path_in_container", lambda p, c: True)
    res = R.step_yosys_synth(proj, "counter", container="test-eda")
    assert res.status == "PASS", (res.status, res.detail)
    joined = ["\x20".join(c) for c in calls]
    assert any(f"-w {synth_dir}" in j for j in joined), (
        "mounted branch must keep the in-place exec")
    assert not any(j.startswith("docker cp") for j in joined), (
        "mounted branch must not stage")
