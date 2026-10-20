"""#3319: the normal installer must expose its serving bundle, read-only.

These drive the existing Docker-argv harness; the separate native receipt
executes the unchanged pad producer under these generated mounts.
"""
import importlib.util
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "restart_mount_fixture", Path(__file__).with_name("test_restart_eda_mount_preservation.py"))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
Harness, _state = _fixture.Harness, _fixture._state
COPIES = (PLUGIN.parents[2] / "tools/vibeic-eda/restart-eda.sh",
          PLUGIN / "tools/vibeic-eda/restart-eda.sh")
RUNTIME_BIND = f"{PLUGIN}:{PLUGIN}:ro"


@pytest.mark.parametrize("script", COPIES, ids=("repository", "packaged"))
def test_fresh_install_exposes_the_whole_serving_bundle(tmp_path, script):
    designs = tmp_path / "designs"
    designs.mkdir()
    h = Harness(tmp_path, _state(exists=False))
    result = h.run(script, DESIGNS_DIR=designs)
    assert result.returncode == 0, result.stderr
    assert h.mount_args() == [RUNTIME_BIND, f"{designs}:{designs}",
                              f"{designs}:/foss/designs"]
    assert h.run_argv()[-3:] == ["--skip", "sleep", "infinity"]


@pytest.mark.parametrize("script", COPIES, ids=("repository", "packaged"))
def test_restart_keeps_design_and_pdk_mounts_with_serving_bundle(tmp_path, script):
    designs, pdk = tmp_path / "designs", tmp_path / "pdk"
    designs.mkdir()
    pdk.mkdir()
    h = Harness(tmp_path, _state(
        binds=[f"{designs}:{designs}:rw", f"{designs}:/foss/designs:rw"],
        mounts=[{"Type": "bind", "Source": str(pdk), "Target": "/pdk",
                 "ReadOnly": True}]))
    result = h.run(script)
    assert result.returncode == 0, result.stderr
    assert h.mount_args() == [RUNTIME_BIND, f"{designs}:{designs}:rw",
                              f"{designs}:/foss/designs:rw", f"{pdk}:/pdk:ro"]


@pytest.mark.parametrize("script", COPIES, ids=("repository", "packaged"))
def test_old_mapping_at_serving_path_is_replaced_readonly(tmp_path, script):
    old = tmp_path / "old-bundle"
    old.mkdir()
    h = Harness(tmp_path, _state(binds=[f"{old}:{PLUGIN}:rw"]))
    result = h.run(script)
    assert result.returncode == 0, result.stderr
    assert h.mount_args() == [RUNTIME_BIND]


@pytest.mark.parametrize("script", COPIES, ids=("repository", "packaged"))
def test_readback_must_confirm_the_serving_bundle_mount(tmp_path, script):
    h = Harness(tmp_path, _state())
    fake = h.bin / "docker"
    fake.write_text(fake.read_text().replace(
        "return res\n", f"return [m for m in res if m[0] != {str(PLUGIN)!r}]\n"))
    result = h.run(script)
    assert result.returncode == 3, (result.stdout, result.stderr)
    assert str(PLUGIN) in result.stderr
    assert "readback failed" in result.stderr
    assert any(c[0] == "rename" and c[-1] == "vibeic-eda" for c in h.calls())
