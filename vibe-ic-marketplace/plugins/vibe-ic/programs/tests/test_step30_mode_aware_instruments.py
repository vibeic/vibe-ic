import subprocess
import path_spice_tool as spice

IMAGE = "sha256:" + "a" * 64


def test_step30_docker_uses_f1_supervised_runner(monkeypatch, tmp_path):
    calls = []
    import librelane_contract as ll

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(ll, "run_container", run)
    monkeypatch.setattr(spice._dmem, "docker_memory_flags", lambda: [])
    result = spice._docker(IMAGE, tmp_path, [], ["ngspice", "-b", "deck.sp"], tmp_path)
    assert result.returncode == 0
    assert calls and calls[0][1] == {"supervised": True}
    assert result._vibeic_lifecycle["pid"]
    assert result._vibeic_lifecycle["start_ns"] <= result._vibeic_lifecycle["end_ns"]
